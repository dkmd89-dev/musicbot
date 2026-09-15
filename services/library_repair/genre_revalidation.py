# services/library_repair/genre_revalidation.py
# -*- coding: utf-8 -*-
"""
Kontrollierte Genre-Revalidierung (Library Genre Management v2, Chat-
Charakterisierung 2026-09-15) — schliesst die in ARCH-022 charakterisierte
Luecke (tests/test_genre_processor_revalidation_gap.py): ein einmal
LEARNED/CONFIRMED gelerntes Genre wird nie mit frischen Last.fm-Tags
abgeglichen, weil GenreProcessor.determine_genre_with_fallbacks() bei
bereits bekanntem Genre frueh zurueckkehrt (Zeile ~162-168) und Last.fm
NIE erreicht.

Diese Funktion umgeht bewusst NUR hier, gezielt fuer den manuellen
Revalidierungs-Trigger, diesen fruehen Rueckgabepfad - durch DIREKTEN
Aufruf von GenreProcessor._fetch_genre_from_lastfm() statt
determine_genre_with_fallbacks(). Der normale Download-Pfad
(determine_genre_with_fallbacks() selbst) bleibt VOLLSTAENDIG
unveraendert - das ist keine Aenderung an der Pipeline, sondern ein
zweiter, eigener Aufrufer derselben bereits existierenden Fetch-Methode.

Nutzt fuer die eigentliche Lern-/Lock-/Overturn-Entscheidung
AUSSCHLIESSLICH die bereits bestehenden Mechanismen aus
services/metadata/auto_learn.py (AutoLearnManager.preview_genre_learning()/
learn_genre(), beide rufen intern _compute_genre_decision() /
_compute_genre_lock_decision() auf - EXAKT dieselbe Overturn-Regel wie im
normalen Download-Pfad, keine zweite Implementierung, keine geaenderten
Schwellenwerte).

Manuelles Mapping (artist_genre.yaml) wird ausschliesslich per
AutoLearnManager._is_genre_manually_defined() geschuetzt - eine
Revalidierung fuer einen manuell gemappten Artist liefert IMMER
outcome=BLOCKED_MANUAL und mutiert nichts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, List, Optional

from config import Config
from logger import get_module_logger
from services.library_repair.run_tracking import (
    KIND_MAINTENANCE,
    acquire_repair_lock,
    append_run_record,
    now_iso,
    release_repair_lock,
)

logger = get_module_logger("GenreRevalidation")

# Outcome-Werte (bewusst eine flache String-Enum statt einer neuen
# Status-Hierarchie - identisches Prinzip wie auto_learn.py's Entscheidung
# gegen einen neuen "UNRESOLVED"-Status, siehe dortigen Docstring):
OUTCOME_BLOCKED_MANUAL = "BLOCKED_MANUAL"
OUTCOME_NO_CANDIDATE = "NO_CANDIDATE"
OUTCOME_SAME_GENRE = "SAME_GENRE"
OUTCOME_OVERTURN_REJECTED = "OVERTURN_REJECTED"
OUTCOME_OVERTURN_ALLOWED = "OVERTURN_ALLOWED"


@dataclass
class RevalidationResult:
    """Ergebnis EINES Revalidierungs-Laufs (Preview ODER Apply - dieselbe
    Struktur, `mutated` unterscheidet). Enthaelt alle Felder fuer die
    Praesentationsschicht (CLI-Text, Telegram-Preview, Auftrag §17)."""

    artist: str
    outcome: str
    reason: str
    manual_mapping_protected: bool = False
    current_primary: Optional[str] = None
    current_secondary: List[str] = field(default_factory=list)
    candidate_primary: Optional[str] = None
    candidate_secondary: List[str] = field(default_factory=list)
    candidate_source: str = "lastfm"
    learning_status: Optional[str] = None  # predicted confidence tier
    locked_primary: Optional[str] = None
    observation_count: int = 0
    mutated: bool = False
    error_message: Optional[str] = None

    @property
    def overturn_allowed(self) -> bool:
        return self.outcome == OUTCOME_OVERTURN_ALLOWED


def _build_dependencies(config):
    """Konstruiert die drei bestehenden Genre-Komponenten frisch (kein
    Singleton-Zugriff auf eine ggf. bereits im Bot-Prozess laufende
    Instanz - dieses Modul laeuft wie doctor_runner/duplicate_runner in
    einem eigenen Subprozess, siehe scripts/revalidate_genre.py)."""
    from utils.artist_map import ArtistConfig, ArtistNormalizer
    from utils.genre_map import GenreMapper
    from services.metadata.auto_learn import AutoLearnManager
    from services.metadata.genre_processor import GenreProcessor

    from pathlib import Path as _Path

    mapping_dir = getattr(config, "GENRE_MAPPING_DIR", "mapping")
    genre_mapper = GenreMapper(mapping_dir=str(mapping_dir))
    # BEWUSST kein genre_mapper.reload() hier: GenreMapper.reload() hat
    # einen vorbestehenden, bei dieser Charakterisierung entdeckten Bug -
    # es sucht das Mapping-Verzeichnis ueber
    # self._find_mapping_dir("mapping") (hartcodierter String) statt
    # ueber den tatsaechlich konfigurierten mapping_dir dieser Instanz
    # neu, kann dadurch ein KOMPLETT ANDERES Verzeichnis laden als das,
    # mit dem die Instanz konstruiert wurde (separat als Finding
    # gemeldet, siehe docs/FINDINGS_INDEX.md - hier NICHT gefixt, ausserhalb
    # des Scopes). GenreMapper ist ein SingletonMixin - in echtem
    # Produktivbetrieb laeuft dieses Modul als eigener, frischer
    # Subprozess (scripts/revalidate_genre.py) pro Aufruf, wodurch
    # _do_init() (nicht reload()) einmalig und korrekt den konfigurierten
    # mapping_dir liest - kein Staleness-Risiko dort. Innerhalb einer
    # Test-Suite mit mehreren Aufrufen im selben Prozess siehe
    # tests/test_genre_revalidation.py (SingletonMixin._instances.clear()
    # zwischen simulierten Läufen, identisches Muster wie
    # tests/test_genre_processor_revalidation_gap.py).
    artist_config = ArtistConfig(
        library_dir=_Path(getattr(config, "LIBRARY_DIR", "library")),
        override_file=_Path(getattr(config, "ARTIST_OVERRIDE_FILE", "./artist_overrides.json")),
        mapping_dir=_Path(mapping_dir),
    )
    artist_normalizer = ArtistNormalizer(artist_config)
    genre_processor = GenreProcessor(config=config, genre_mapper=genre_mapper, logger=logger)
    auto_learn = AutoLearnManager(
        config=config, artist_normalizer=artist_normalizer, genre_mapper=genre_mapper,
        logger=logger,
    )
    return genre_mapper, genre_processor, auto_learn


async def run_genre_revalidation(
    artist: str, *, apply: bool = False, triggered_by: str = "cli",
    config: Any = None, lfm_client: Any = None,
) -> RevalidationResult:
    """Fuehrt EINE Revalidierung fuer `artist` durch - Last.fm-Fetch +
    Overturn-Entscheidung IMMER (auch im reinen Preview-Fall, um die
    Anzeige zu befuellen); der tatsaechliche Schreibvorgang
    (AutoLearnManager.learn_genre()) nur wenn `apply=True` UND
    outcome==OVERTURN_ALLOWED.

    `lfm_client` optional injizierbar fuer Tests (sonst wird ein echter
    LastFMClient() konstruiert - ECHTER externer API-Call, siehe
    scripts/revalidate_genre.py fuer den CLI-Aufrufer)."""
    config = config or Config
    artist = artist.strip()

    genre_mapper, genre_processor, auto_learn = _build_dependencies(config)

    manual_protected = auto_learn._is_genre_manually_defined(artist)
    current_entry = genre_mapper.get_artist_entry(artist.lower())
    current_primary = current_entry.primary if current_entry else None
    current_secondary = list(current_entry.secondary or []) if current_entry else []

    if manual_protected:
        return RevalidationResult(
            artist=artist, outcome=OUTCOME_BLOCKED_MANUAL,
            reason="Artist besitzt ein manuelles Mapping (artist_genre.yaml) - "
                   "Revalidierung wuerde es nicht ueberschreiben. Fuer eine "
                   "bewusste Aenderung „Genre setzen“ verwenden.",
            manual_mapping_protected=True,
            current_primary=current_primary, current_secondary=current_secondary,
        )

    if lfm_client is None:
        from services.clients.lastfm_client import LastFMClient

        lfm_client = LastFMClient()

    try:
        lfm_result = await genre_processor._fetch_genre_from_lastfm(
            artist, artist, lfm_client,
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"❌ Last.fm-Fetch fuer Revalidierung fehlgeschlagen ({artist}): {e}")
        return RevalidationResult(
            artist=artist, outcome=OUTCOME_NO_CANDIDATE,
            reason=f"Last.fm-Abfrage fehlgeschlagen: {e}",
            current_primary=current_primary, current_secondary=current_secondary,
            error_message=str(e),
        )

    if not lfm_result or not lfm_result.primary:
        return RevalidationResult(
            artist=artist, outcome=OUTCOME_NO_CANDIDATE,
            reason="Last.fm lieferte kein verwertbares Genre für diesen Artist.",
            current_primary=current_primary, current_secondary=current_secondary,
        )

    decision = auto_learn.preview_genre_learning(artist, lfm_result)

    baseline = decision["existing"].get("locked_primary") if decision["existing"] else None
    if not baseline:
        baseline = current_primary

    observed_primary = decision["observed_primary"]
    predicted_primary = decision["predicted_primary"]

    if observed_primary == baseline:
        outcome = OUTCOME_SAME_GENRE
        reason = "Last.fm bestätigt das aktuelle Genre - keine Änderung nötig."
    elif predicted_primary == baseline:
        outcome = OUTCOME_OVERTURN_REJECTED
        reason = (
            "Neuer Kandidat weicht ab, erfüllt aber die bestehende "
            "Overturn-Regel nicht (Herausforderer-Beobachtungen noch nicht "
            "stark genug gegenüber dem gelockten Genre)."
        )
    else:
        outcome = OUTCOME_OVERTURN_ALLOWED
        reason = "Neuer Kandidat erfüllt die Overturn-Regel - Änderung zulässig."

    result = RevalidationResult(
        artist=artist, outcome=outcome, reason=reason,
        current_primary=current_primary, current_secondary=current_secondary,
        candidate_primary=lfm_result.primary,
        candidate_secondary=list(lfm_result.secondary or []),
        candidate_source="lastfm",
        learning_status=decision["predicted_confidence"],
        locked_primary=decision["predicted_locked_primary"],
        observation_count=decision["predicted_observations"],
    )

    if not apply or outcome != OUTCOME_OVERTURN_ALLOWED:
        return result

    started_at = now_iso()
    acquire_repair_lock()
    try:
        written = await auto_learn.learn_genre(artist, lfm_result)
        result.mutated = written
        append_run_record({
            "repair_id": str(uuid.uuid4()),
            "started_at": started_at,
            "finished_at": now_iso(),
            "triggered_by": triggered_by,
            "level": "GENRE_REVALIDATION",
            "kind": KIND_MAINTENANCE,
            "artist": artist,
            "status": "SUCCESS" if written else "SKIPPED",
            "status_counts": {"SUCCESS": 1 if written else 0, "SKIPPED": 0 if written else 1, "FAILED": 0},
            "affected_files": [],
        })
        return result
    finally:
        release_repair_lock()
