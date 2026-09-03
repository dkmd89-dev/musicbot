# services/metadata/auto_learn.py
# -*- coding: utf-8 -*-

import asyncio
import re
import time
import yaml
from collections import Counter
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Dict, List, Any, Optional, Set, Tuple, TYPE_CHECKING
from logger import get_module_logger

if TYPE_CHECKING:
    from utils.artist_map import ArtistNormalizer
    from utils.genre_map import GenreMapper


# Kappungsgrenze fuer die pro Artist/Genre gespeicherte Beobachtungshistorie
# (observation_log) - verhindert unbegrenztes Wachstum der YAML-Dateien bei
# vielstrackigen Artists, behaelt aber genug Historie fuer eine belastbare
# Mehrheitsentscheidung (Auto-Learn-Auftrag Abschnitt 7/12).
_MAX_OBSERVATION_LOG = 10
_MAX_PRIMARY_ARTISTS_SEEN = 10

# CONFIDENCE-AUDIT Abschnitt 3: Schwellenwerte als benannte Konstanten statt
# eingebetteter Zahlenwerte - besser auffindbar/dokumentiert, ABSICHTLICH
# aber keine YAML-Konfigurationsschicht (config.py o.ae.) dafuer eingefuehrt.
# Begruendung (Audit-Auftrag Abschnitt 3: "keine unnoetige Konfigurations-
# architektur bauen"): die Schwellen sind bereits zentral an genau dieser
# einen Stelle definiert und werden bereits identisch fuer Artist- UND
# Genre-Observations verwendet (_confidence_tier() ist die einzige Quelle
# fuer beide Domaenen, siehe Aufrufer in learn_genre()/_compute_genre_decision()
# und in _write_featured_observation_sync()/_compute_featured_artist_decision())
# - es gibt aktuell keinen Anwendungsfall, der unterschiedliche Schwellen je
# Domaene oder eine Laufzeit-Aenderung ohne Codeaenderung erfordert. Eine
# YAML-Konfigurationsschicht (auto_learn.genre.learned_threshold/...) haette
# hier nur zusaetzliche Komplexitaet ohne konkreten Bedarf eingefuehrt.
_LEARNED_THRESHOLD = 2  # ab dieser Beobachtungszahl: LEARNED
_CONFIRMED_THRESHOLD = 4  # ab dieser Beobachtungszahl: CONFIRMED

# Genre-Lock-in (2026-09-03): ab dieser Beobachtungszahl EINES Genre-Werts
# wird dieser Wert als "locked_primary" dauerhaft festgeschrieben - weitere,
# abweichende Beobachtungen aendern primary nicht mehr bei jeder einzelnen
# neuen Beobachtung (frueheres Verhalten: reines Mehrheitsvotum ueber die
# letzten _MAX_OBSERVATION_LOG Beobachtungen, siehe
# _aggregate_genre_observations()). Ein Herausforderer-Genre uebernimmt den
# Lock erst, wenn seine (unbegrenzte) Beobachtungszahl das
# _GENRE_LOCK_OVERTURN_MULTIPLIER-fache der aktuellen (live, nicht
# eingefrorenen) Beobachtungszahl des gelockten Werts erreicht oder
# uebersteigt. Siehe _compute_genre_lock_decision()/
# _derive_genre_primary_secondary() sowie docs/GENRE_SYSTEM.md Abschnitt 4.a.
_GENRE_LOCK_THRESHOLD = 3
_GENRE_LOCK_OVERTURN_MULTIPLIER = 3


def _confidence_tier(observations: int) -> str:
    """
    Deterministische, nachvollziehbare Konfidenz-/Status-Einstufung fuer
    Auto-Learn-Beobachtungen - fuer Artist- UND Genre-Observations
    gleichermassen verwendet (Auto-Learn-Auftrag Abschnitt 6/17):

        1 Beobachtung                          -> OBSERVED
        _LEARNED_THRESHOLD..<_CONFIRMED_THRESHOLD Beobachtungen -> LEARNED
        >=_CONFIRMED_THRESHOLD Beobachtungen    -> CONFIRMED (Auftrag
                                     Abschnitt 17 nennt dies "HIGH
                                     CONFIDENCE" - hier auf die in
                                     Abschnitt 6 explizit benannte
                                     3-Stufen-Statushierarchie vereinheitlicht,
                                     keine vierte Stufe erfunden)

    Bewusst keine ML-/Wahrscheinlichkeits-basierte Bewertung - rein
    beobachtungszahlbasiert und damit vollstaendig nachvollziehbar.

    WICHTIGE EINSCHRAENKUNG (Confidence-Audit-Auftrag Abschnitt 4, live
    verifiziert am NOAH-Fall): dieser Mechanismus schuetzt ausschliesslich
    vor EINER EINZELNEN fehlerhaften Beobachtung, die sofort zu einem
    dauerhaften Mapping wuerde. Er kann NICHT erkennen, ob eine externe
    Quelle (Last.fm/MusicBrainz) SYSTEMATISCH/KONSISTENT denselben falschen
    Wert liefert (z.B. bei einer Namenskollision mit einem gleichnamigen,
    anderen Kuenstler) - liefert dieselbe fehlerhafte Quelle
    _CONFIRMED_THRESHOLD-mal denselben falschen Wert, erreicht dieser Wert
    trotzdem CONFIRMED. Confidence-Gating ist ein Schutz gegen einzelne
    Ausreisser, keine Loesung fuer Artist-Identitaets-/Namenskonflikte in
    externen Metadata-Quellen (dafuer waere ein MusicBrainz-ID-basierter
    Abgleich noetig - nicht Teil dieser Implementierung).
    """
    if observations <= 1:
        return "OBSERVED"
    if observations < _CONFIRMED_THRESHOLD:
        return "LEARNED"
    return "CONFIRMED"


def _aggregate_genre_observations(
    observation_log: List[Dict[str, Any]],
) -> Tuple[str, List[str]]:
    """
    Leitet aus mehreren Genre-Beobachtungen eine belastbare primary/secondary-
    Kombination per Mehrheitsentscheidung ab (Auto-Learn-Auftrag Abschnitt 12:
    "nicht einfach last value wins"). Gleiches Counter-Mehrheitsvotum-Idiom
    wie GenreProcessor._infer_genre_from_feat_artists() - keine neue
    parallele Normalisierungs-/Bewertungslogik.

    TIE-BREAK (Confidence-Audit-Auftrag Abschnitt 8): bei echtem Gleichstand
    (z.B. 2x Genre A, 2x Genre B) liefert Counter.most_common() deterministisch
    den zuerst BEOBACHTETEN (im observation_log zuerst aufgetretenen) Wert -
    Python-Standardverhalten von Counter bei gleicher Haeufigkeit, keine
    eigene Zufalls-/Heuristik-Logik. Es wird bewusst KEIN neuer "UNRESOLVED"-
    o.ae. Status fuer Genre-Konflikte eingefuehrt (Auftrag: "keine neue
    Status-Hierarchie erfinden") - ein Gleichstand bleibt bei der bereits
    vorhandenen OBSERVED/LEARNED/CONFIRMED-Einstufung, rein basierend auf der
    Gesamt-Beobachtungszahl, unabhaengig davon ob die Beobachtungen intern
    uneinig sind. Das ist bewusst nachvollziehbar/deterministisch statt
    "intelligent", siehe Docstring von _confidence_tier().
    """
    primary_counter = Counter(
        obs["primary"] for obs in observation_log if obs.get("primary")
    )
    if not primary_counter:
        return "", []
    primary = primary_counter.most_common(1)[0][0]

    secondary_counter: Counter = Counter()
    for obs in observation_log:
        for genre in obs.get("secondary") or []:
            secondary_counter[genre] += 1
    secondary = [
        genre
        for genre, _ in secondary_counter.most_common(8)
        if genre.lower() != primary.lower()
    ][:5]

    return primary, secondary


def _compute_genre_lock_decision(
    genre_counts: Dict[str, int],
    locked_primary: Optional[str],
    observed_primary: str,
) -> Tuple[Optional[str], Dict[str, int]]:
    """
    Reine Lock-in-Entscheidung fuer EINE neue Genre-Beobachtung (2026-09-03,
    Genre-Lock-in-Auftrag). Inkrementiert genre_counts[observed_primary] und
    entscheidet, ob/welches Genre gelockt ist:

    - Noch kein Lock (locked_primary is None): sobald
      genre_counts[observed_primary] >= _GENRE_LOCK_THRESHOLD erreicht ist,
      wird observed_primary gelockt (Rueckgabe: neuer locked_primary-Wert).
      Vorher bleibt der Rueckgabewert None ("Vorlock-Phase") - der Aufrufer
      (_derive_genre_primary_secondary()) verwendet in dieser Phase weiterhin
      unveraendert _aggregate_genre_observations() fuer primary/secondary,
      exakt wie vor Einfuehrung des Lock-in.
    - Lock aktiv (locked_primary gesetzt): bleibt beim gelockten Wert, ausser
      der (LIVE, nicht beim Lock-Zeitpunkt eingefrorene) Zaehler des
      observed_primary erreicht/uebersteigt das
      _GENRE_LOCK_OVERTURN_MULTIPLIER-fache des aktuellen Zaehlers des
      gelockten Werts - dann wechselt der Lock auf observed_primary. Ist der
      gelockte Wert selbst der beobachtete (Reconfirmation), bleibt der Lock
      unveraendert bestehen, sein Zaehler steigt lediglich mit.

    genre_counts ist bewusst UNGEDECKELT (im Unterschied zum auf
    _MAX_OBSERVATION_LOG begrenzten observation_log) - nur so bleibt ein
    einmal erreichter Lock nachvollziehbar, auch wenn die Rohbeobachtung
    laengst aus dem gekappten Log herausgefallen ist (siehe
    _derive_genre_primary_secondary()).
    """
    updated_counts = dict(genre_counts)
    updated_counts[observed_primary] = updated_counts.get(observed_primary, 0) + 1

    if locked_primary is None:
        if updated_counts[observed_primary] >= _GENRE_LOCK_THRESHOLD:
            return observed_primary, updated_counts
        return None, updated_counts

    if observed_primary == locked_primary:
        return locked_primary, updated_counts

    locked_count = updated_counts.get(locked_primary, 0)
    challenger_count = updated_counts[observed_primary]
    if challenger_count >= _GENRE_LOCK_OVERTURN_MULTIPLIER * locked_count:
        return observed_primary, updated_counts
    return locked_primary, updated_counts


def _derive_genre_primary_secondary(
    existing_entry: Optional[dict],
    observation_log: List[Dict[str, Any]],
    observed_primary: str,
) -> Dict[str, Any]:
    """
    Orchestriert die Genre-Lock-in-Entscheidung fuer eine neue Beobachtung
    und liefert das vollstaendige primary/secondary/locked_primary/
    genre_counts-Ergebnis (2026-09-03, Genre-Lock-in-Auftrag). Ersetzt an
    beiden Schreibpfaden (_compute_genre_decision() fuer Dry-Run,
    _write_genre_observation_sync() fuer den echten Schreibpfad) den
    vorherigen direkten Aufruf von _aggregate_genre_observations() - MUSS an
    beiden Stellen identisch aufgerufen werden, sonst weicht die
    Dry-Run-Vorschau vom echten Schreibergebnis ab
    (test_dry_run_genre_prediction_matches_live_outcome).

    Migrations-Backfill: existiert ein Alt-Eintrag OHNE 'genre_counts' (vor
    Einfuehrung des Lock-in geschrieben), wird genre_counts aus
    observation_log[:-1] rekonstruiert - die aktuelle Beobachtung ist zu
    diesem Zeitpunkt bereits als letztes Element in observation_log
    enthalten und darf nicht doppelt gezaehlt werden.

    Rueckgabe-Dict: {"primary": str, "secondary": List[str],
    "locked_primary": Optional[str], "genre_counts": Dict[str, int]}.
    Solange kein Lock aktiv ist, ist "locked_primary" None und
    primary/secondary entsprechen exakt dem bisherigen
    _aggregate_genre_observations()-Ergebnis (keine Verhaltensaenderung in
    der Vorlock-Phase).
    """
    existing_entry = existing_entry or {}
    locked_primary = existing_entry.get("locked_primary")
    genre_counts: Dict[str, int] = dict(existing_entry.get("genre_counts") or {})

    if not genre_counts and observation_log:
        # Legacy-Backfill: observation_log enthaelt die aktuelle Beobachtung
        # bereits als letztes Element - beim Backfill ausschliessen, sie
        # wird gleich unten regulaer ueber _compute_genre_lock_decision()
        # gezaehlt.
        backfill_counter: Counter = Counter(
            obs["primary"] for obs in observation_log[:-1] if obs.get("primary")
        )
        genre_counts = dict(backfill_counter)

    new_locked, updated_counts = _compute_genre_lock_decision(
        genre_counts, locked_primary, observed_primary
    )

    if new_locked is None:
        primary, secondary = _aggregate_genre_observations(observation_log)
        return {
            "primary": primary,
            "secondary": secondary,
            "locked_primary": None,
            "genre_counts": updated_counts,
        }

    # Lock aktiv: primary ist der gelockte Wert. secondary enthaelt die
    # bisherigen Sub-Genre-Tags (aus dem Mehrheitsvotum ueber observation_log)
    # PLUS explizit alle anderen genre_counts-Werte ausser dem gelockten
    # Wert selbst (2026-09-03, per Nutzerentscheidung: ein durch die
    # Lock-Regel abgelehnter/ueberstimmter Wert erscheint sichtbar in
    # secondary statt nur implizit ueber genre_counts) - nach Haeufigkeit
    # sortiert, auf 5 gedeckelt, dedupliziert.
    _, aggregated_secondary = _aggregate_genre_observations(observation_log)
    challenger_ranking = sorted(
        (g for g in updated_counts if g != new_locked),
        key=lambda g: updated_counts[g],
        reverse=True,
    )
    secondary = list(aggregated_secondary)
    for genre in challenger_ranking:
        if genre.lower() == new_locked.lower():
            continue
        if genre not in secondary:
            secondary.append(genre)
    secondary = secondary[:5]

    return {
        "primary": new_locked,
        "secondary": secondary,
        "locked_primary": new_locked,
        "genre_counts": updated_counts,
    }


class _InlineListDumper(yaml.SafeDumper):
    """YAML-Dumper mit Inline-Listen (flow_style) fuer 'secondary' - vorher
    ein lokales Duplikat innerhalb von learn_genre(), jetzt einmalig auf
    Modulebene, da von _write_yaml_atomic() fuer alle drei Schreibpfade
    gemeinsam genutzt."""

    def represent_list(self, data):
        return self.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


_InlineListDumper.add_representer(list, _InlineListDumper.represent_list)


class AutoLearnManager:
    """
    Verwaltet das automatische Lernen von Artist- und Genre-Informationen.

    Schreibt ausschließlich in:
      - auto_learned_artist_aliases.json    (Channel-Name-Aliase, ARCH-022:
        vorher auto_learned_artists.yaml, dann auto_learned_artist_aliases.yaml)
      - auto_learned_featured_artists.json  (Feature-Artist-Beobachtungen,
        ARCH-022: vorher derselbe "featured_artists"-Schluessel in
        auto_learned_artists.yaml, dann eigene .yaml-Datei)
      - auto_learned_genre.json    (Genre-Zuordnungen, ARCH-022: vorher .yaml)
      - known_artists.yaml         (bestaetigte Identitaets-Mappings, bleibt YAML)

    Liest NIEMALS aus artist_overrides.yaml oder artist_genre.yaml heraus,
    aber prüft diese als Duplikat-Schutz.

    INV-01/INV-02 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md, Abschnitt 27):
    Alle drei Schreibpfade liefen frueher synchron (open(mode="w")) direkt
    im Event-Loop-Thread, ohne asyncio.to_thread() und ohne Lock. Die
    Read-Modify-Write-Sequenz enthielt keinen await-Punkt, wodurch
    asyncios kooperatives Scheduling zufaellig eine Serialisierung
    zwischen gleichzeitig laufenden Tracks (MAX_CONCURRENT_DOWNLOADS=3)
    herstellte. Ein naiver asyncio.to_thread()-Fix ohne Lock haette diese
    zufaellige Sicherheit aufgehoben und eine echte Lost-Update-Race
    zwischen zwei parallelen Worker-Threads eingefuehrt. Der Fix
    kombiniert daher beides: asyncio.to_thread() fuer INV-01 (Event-Loop
    bleibt frei) PLUS ein threading.Lock (self._write_lock, Vorbild
    utils/artist_map.py::_write_lock) fuer die Serialisierung ueber echte
    OS-Threads hinweg, PLUS atomares Schreiben (tmp-Datei + Path.replace)
    fuer INV-02 (Vorbild utils/metadata_cache.py::store()).
    """

    ALLOWED_ARTIST_SOURCES = {"youtube_parsed", "first_artist_from_title"}

    def __init__(
        self,
        config,
        artist_normalizer: "ArtistNormalizer",
        genre_mapper: "GenreMapper",
        logger=None,
    ):
        self.config = config
        self.artist_normalizer = artist_normalizer
        self.genre_mapper = genre_mapper
        self.logger = logger or get_module_logger("AutoLearnManager")
        # INV-01/INV-02: ein gemeinsames Lock fuer alle vier Schreibpfade
        # (auto_learned_genre.json, known_artists.yaml,
        # auto_learned_artist_aliases.json, auto_learned_featured_artists.json,
        # ARCH-022: alle drei JSON-Dateien vorher YAML, die letzten beiden
        # ausserdem vorher eine gemeinsame Datei auto_learned_artists.yaml)
        # - bewusst EIN Lock statt vier
        # dateispezifischen Locks, da Schreibfrequenz niedrig ist und ein
        # einzelnes Lock die Komplexitaet/Deadlock-Flaeche minimiert
        # (CLAUDE.md §18: kleinste sinnvolle Aenderung).
        self._write_lock = Lock()

    # ─────────────────────────────────────────────────────────────────────────
    # Gemeinsame atomare Schreib-Hilfsmethode (INV-02)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _write_yaml_atomic(path: Path, data: dict, inline_lists: bool = False) -> None:
        """
        Schreibt YAML atomar (write-tmp -> rename), analog zu
        MetadataCache.store() (utils/metadata_cache.py). Muss unter
        self._write_lock aufgerufen werden.

        Nur noch fuer known_artists.yaml genutzt (manuell nachvollziehbare
        Datei, bleibt YAML) - die drei Auto-Learn-Dateien
        (auto_learned_genre.json, auto_learned_artist_aliases.json,
        auto_learned_featured_artists.json) nutzen seit ARCH-022
        _write_json_atomic() unten.
        """
        import yaml

        tmp_path = path.with_suffix(f".tmp_{int(time.time() * 1000)}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    data,
                    f,
                    Dumper=_InlineListDumper if inline_lists else yaml.SafeDumper,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=True,
                )
            tmp_path.replace(path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @staticmethod
    def _write_json_atomic(path: Path, data: dict) -> None:
        """
        Schreibt JSON atomar (write-tmp -> rename), analog zu
        _write_yaml_atomic() oben. ARCH-022: die drei rein maschinell
        geschriebenen/gelesenen Auto-Learn-Dateien (nie von Hand editiert,
        kein Kommentar-Bedarf) wurden von YAML auf JSON umgestellt - u.a.
        weil das bisherige _InlineListDumper-Konstrukt (oben) ein reiner
        YAML-Formatierungs-Workaround war, den JSON nicht braucht (Arrays
        sind dort immer "inline"). Muss unter self._write_lock aufgerufen
        werden.
        """
        import json

        tmp_path = path.with_suffix(f".tmp_{int(time.time() * 1000)}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
            tmp_path.replace(path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ─────────────────────────────────────────────────────────────────────────

    async def learn_genre(
        self,
        canonical_name: str,
        genre_result,
        raw_name: str = "",
    ) -> bool:
        """
        Schreibt/aggregiert Genre-Beobachtungen in auto_learned_genre.json.
        Gibt True zurück wenn geschrieben wurde (neuer ODER aktualisierter
        Eintrag), sonst False.

        Wird NICHT geschrieben wenn:
          - Artist in artist_genre.yaml (manuell) vorhanden ist (dauerhafter
            Block, siehe Abschnitt 13/14 des Auto-Learn-Auftrags)
          - genre_result ist None oder hat kein primary-Genre

        Genre-Learning ist UNABHAENGIG vom Artist-Namens-Override in
        artist_overrides.json (2026-09-03, Genre-Lock-in-Auftrag): frueher
        blockierte ein dortiger Eintrag das Genre-Lernen vollstaendig, obwohl
        artist_overrides.json ausschliesslich Artist-NAMENS-Normalisierung
        betrifft (raw_name -> canonical_name), nicht Genre. Verifiziert
        betraf das 78 von 174 Override-Artists ohne manuelles Genre in
        artist_genre.yaml (u.a. Toobrokeforfiji) - diese konnten dadurch NIE
        ein artist-weites Auto-Learn-Genre-Mapping erhalten. Der SEPARATE
        Feature-Artist-Override-Check (_is_artist_known()/
        _compute_featured_artist_decision()/observe_featured_artists())
        bleibt davon unberuehrt und weiterhin unveraendert.

        Ein bereits vorhandener AUTO-Learn-Eintrag blockiert NICHT mehr
        weitere Beobachtungen (frueheres Verhalten: einmal geschrieben,
        fuer immer eingefroren) - stattdessen wird die Beobachtung der
        vorhandenen observation_log hinzugefuegt und primary/secondary per
        Mehrheitsvotum neu abgeleitet (Abschnitt 11/12: "nicht last value
        wins"). Die Entscheidungsberechnung selbst ist reine, testbare Logik
        in _compute_genre_decision() - identisch fuer den Schreibpfad hier
        und den Dry-Run-Vorschaupfad preview_genre_learning().
        """
        decision = self._compute_genre_decision(canonical_name, genre_result)

        if decision["decision"] == "BLOCKED_MANUAL":
            self.logger.debug(
                f"🧠 [AUTO-LEARN] '{canonical_name}' manuell in artist_genre.yaml "
                f"definiert → kein Auto-Learning"
            )
            return False
        if decision["decision"] == "SKIPPED_NO_GENRE":
            return False

        self.logger.info(
            f"🧠 [AUTO-LEARN] Verarbeite Genre-Beobachtung für '{canonical_name}': "
            f"'{decision['observed_primary']}' (Quelle: {getattr(genre_result, 'source', 'unknown')}, "
            f"Beobachtung {decision['predicted_observations']}, "
            f"Konfidenz {decision['predicted_confidence']})"
        )

        try:
            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            auto_genre_path = mapping_dir / "auto_learned_genre.json"

            written = await asyncio.to_thread(
                self._write_genre_observation_sync,
                auto_genre_path,
                canonical_name.strip(),
                decision["observed_primary"],
                decision["observed_secondary"],
            )

            if not written:
                return False

            self.logger.info(
                f"🧠 [AUTO-LEARN] ✅ Genre {'aktualisiert' if decision['decision'] == 'WOULD_UPDATE' else 'gelernt'}: "
                f"'{canonical_name}' → primary='{decision['predicted_primary']}', "
                f"secondary={decision['predicted_secondary'][:3] if decision['predicted_secondary'] else 'keine'}, "
                f"observations={decision['predicted_observations']}, "
                f"confidence={decision['predicted_confidence']}"
            )

            if hasattr(self.genre_mapper, "clear_caches"):
                self.genre_mapper.clear_caches()

            return True

        except Exception as e:
            self.logger.warning(f"⚠️ [AUTO-LEARN] Genre-YAML fehlgeschlagen: {e}")
            return False

    def preview_genre_learning(self, canonical_name: str, genre_result) -> Dict[str, Any]:
        """
        Reine Dry-Run-Vorschau der Genre-Auto-Learn-Entscheidung - identische
        Logik wie learn_genre(), aber ohne jegliches Schreiben. Fuer
        scripts/reprocess_artist_metadata.py --dry-run (Auto-Learn-Auftrag
        Abschnitt 21).
        """
        return self._compute_genre_decision(canonical_name, genre_result)

    def _compute_genre_decision(
        self, canonical_name: str, genre_result
    ) -> Dict[str, Any]:
        """
        Reine Entscheidungsberechnung (kein I/O ausser dem lesenden
        Nachschlagen des bestehenden Eintrags) fuer Genre-Auto-Learn. Wird
        sowohl vom echten Schreibpfad (learn_genre) als auch vom
        Dry-Run-Vorschaupfad (preview_genre_learning) verwendet, damit
        Dry-Run und echter Lauf garantiert identisch entscheiden.
        """
        result: Dict[str, Any] = {
            "artist": canonical_name,
            "observed_primary": None,
            "observed_secondary": [],
            "decision": "SKIPPED_NO_GENRE",
            "existing": None,
            "predicted_primary": None,
            "predicted_secondary": [],
            "predicted_locked_primary": None,
            "predicted_genre_counts": {},
            "predicted_observations": 0,
            "predicted_confidence": None,
            "observation_log": [],
        }
        if not genre_result or not getattr(genre_result, "primary", None):
            return result

        observed_primary = genre_result.primary
        # BUGFIX 2026-09-03 (Oimara-Live-Fund): frueher gab es hier einen
        # "elif raw_tags"-Fallback, der bei leerem genre_result.secondary
        # ersatzweise die UNGEFILTERTEN raw_tags verwendete. genre_result.
        # secondary stammt bei den einzigen beiden tatsaechlichen raw_tags-
        # Quellen (MusicBrainz/Last.fm, siehe genre_processor.py::
        # _fetch_genre_from_musicbrainz()/_fetch_genre_from_lastfm()) bereits
        # aus prioritize_genres() - dort wurde IGNORE_SECONDARY (genre_filters.
        # yaml) bereits angewendet. raw_tags ist an denselben Stellen bewusst
        # die ROHE, ungefilterte Tag-Liste (fuer Nachvollziehbarkeit/Debugging
        # gedacht, nicht als Ersatzwert). Der Fallback umging die Filterung
        # dadurch systematisch: Last.fm lieferte fuer 'Oimara' nur
        # ['german', 'deutschland'] - 'german' steht explizit in
        # IGNORE_SECONDARY und wurde von prioritize_genres() korrekt zu
        # secondary=[] gefiltert, landete durch diesen Fallback aber trotzdem
        # in observed_secondary. Ein leeres secondary aus prioritize_genres()
        # ist ein bewusstes, korrektes Ergebnis (kein zweiter valider Tag
        # nach Filterung) - kein Mangel, der durch raw_tags kompensiert
        # werden muesste. Keine der uebrigen GenreResult-Quellen (manuelles
        # Genre, Feature-Artist-Inferenz) setzt raw_tags ueberhaupt, der
        # Fallback hatte also keinen legitimen Anwendungsfall.
        secondary_genres: List[str] = (
            list(genre_result.secondary[:5])
            if getattr(genre_result, "secondary", None)
            else []
        )
        result["observed_primary"] = observed_primary
        result["observed_secondary"] = secondary_genres

        if self._is_genre_manually_defined(canonical_name):
            result["decision"] = "BLOCKED_MANUAL"
            return result

        _existing_key, existing_entry = self._read_genre_entry(canonical_name)
        result["existing"] = existing_entry

        observation_log = (
            list(existing_entry.get("observation_log", [])) if existing_entry else []
        )
        observation_log.append(
            {"primary": observed_primary, "secondary": secondary_genres}
        )
        observation_log = observation_log[-_MAX_OBSERVATION_LOG:]

        derived = _derive_genre_primary_secondary(
            existing_entry, observation_log, observed_primary
        )

        result["decision"] = "WOULD_UPDATE" if existing_entry else "WOULD_LEARN"
        result["predicted_primary"] = derived["primary"]
        result["predicted_secondary"] = derived["secondary"]
        result["predicted_locked_primary"] = derived["locked_primary"]
        result["predicted_genre_counts"] = derived["genre_counts"]
        result["predicted_observations"] = len(observation_log)
        result["predicted_confidence"] = _confidence_tier(len(observation_log))
        result["observation_log"] = observation_log
        return result

    def _read_genre_entry(
        self, artist_name: str
    ) -> Tuple[Optional[str], Optional[dict]]:
        """
        Liest (nur lesend) einen bestehenden Auto-Learn-Genre-Eintrag,
        case-insensitiv. Gibt (bestehender_key_wie_in_yaml, entry) zurück,
        (None, None) wenn nicht vorhanden - der bestehende Key wird beim
        Schreiben wiederverwendet, um keine Duplikate mit abweichender
        Groß-/Kleinschreibung zu erzeugen.
        """
        try:
            import json

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            auto_file = mapping_dir / "auto_learned_genre.json"
            if not auto_file.exists():
                return None, None
            with open(auto_file, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            genre_map = data.get("ARTIST_GENRE_MAP", {})
            if artist_name in genre_map:
                return artist_name, genre_map[artist_name]
            search_lower = artist_name.lower()
            for key, value in genre_map.items():
                if str(key).lower() == search_lower:
                    return key, value
            return None, None
        except Exception as e:
            self.logger.debug(f"Fehler in _read_genre_entry: {e}")
            return None, None

    def _write_genre_observation_sync(
        self,
        auto_genre_path: Path,
        canonical_key: str,
        observed_primary: str,
        observed_secondary: List[str],
    ) -> bool:
        """
        Liest den bestehenden Eintrag (falls vorhanden), haengt die neue
        Beobachtung an, leitet primary/secondary per Mehrheitsvotum neu ab
        und schreibt atomar. Laeuft in einem Worker-Thread (asyncio.to_thread)
        - self._write_lock serialisiert konkurrierende Aufrufe ueber echte
        OS-Threads hinweg (INV-01+INV-02, siehe Klassen-Docstring).
        """
        with self._write_lock:
            import json

            data: dict = {}
            if auto_genre_path.exists():
                with open(auto_genre_path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}

            genre_map = data.get("ARTIST_GENRE_MAP", {})

            existing_key = canonical_key
            existing_entry = None
            if canonical_key in genre_map:
                existing_entry = genre_map[canonical_key]
            else:
                search_lower = canonical_key.lower()
                for key, value in genre_map.items():
                    if str(key).lower() == search_lower:
                        existing_key = key
                        existing_entry = value
                        break

            observation_log = (
                list(existing_entry.get("observation_log", []))
                if existing_entry
                else []
            )
            observation_log.append(
                {"primary": observed_primary, "secondary": observed_secondary}
            )
            observation_log = observation_log[-_MAX_OBSERVATION_LOG:]

            derived = _derive_genre_primary_secondary(
                existing_entry, observation_log, observed_primary
            )

            genre_map[existing_key] = {
                "primary": derived["primary"],
                "secondary": derived["secondary"],
                "description": "Auto-learned via Last.fm (rule)",
                "observations": len(observation_log),
                "confidence": _confidence_tier(len(observation_log)),
                "observation_log": observation_log,
                "locked_primary": derived["locked_primary"],
                "genre_counts": derived["genre_counts"],
            }
            data["ARTIST_GENRE_MAP"] = genre_map

            self._write_json_atomic(auto_genre_path, data)
            return True

    async def learn_artist(
        self,
        raw_name: str,
        canonical_name: str,
        source: str = "unknown",
        channel_name: str = "",
    ) -> bool:
        """
        Schreibt NUR Aliase in auto_learned_artist_aliases.json (ARCH-022:
        vorher auto_learned_artists.yaml, dann auto_learned_artist_aliases.yaml).
        Identitäts-Mappings (raw == canonical) gehen nach known_artists.yaml.
        """
        if source not in self.ALLOWED_ARTIST_SOURCES:
            self.logger.debug(f"🧠 [AUTO-LEARN] Überspringe Quelle '{source}'")
            return False

        if not raw_name or not canonical_name:
            return False

        raw_key = raw_name.strip()
        canonical_value = canonical_name.strip()

        # 1. Prüfe ob bereits bekannt
        if self._is_artist_known(canonical_value):
            self.logger.debug(f"🧠 [AUTO-LEARN] '{canonical_value}' bereits bekannt")
            return False

        # 2. Identitäts-Mapping (kein Alias) → known_artists.yaml
        if raw_key.casefold() == canonical_value.casefold():
            return await self._save_known_artist(canonical_value)

        # 3. Echter Alias → auto_learned_artist_aliases.json
        return await self._save_alias(raw_key, canonical_value)

    async def _save_known_artist(self, artist_name: str) -> bool:
        """Speichert einen bekannten Künstler in known_artists.yaml"""
        try:
            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            known_file = mapping_dir / "known_artists.yaml"

            written = await asyncio.to_thread(
                self._write_known_artist_sync, known_file, artist_name
            )
            if written:
                self.logger.info(
                    f"🧠 [AUTO-LEARN] ✅ Bekannter Künstler gespeichert: '{artist_name}'"
                )
            return written

        except Exception as e:
            self.logger.warning(
                f"⚠️ [AUTO-LEARN] known_artists.yaml fehlgeschlagen: {e}"
            )
        return False

    def _write_known_artist_sync(self, known_file: Path, artist_name: str) -> bool:
        """Sync-Kern von _save_known_artist() - siehe Klassen-Docstring INV-01/INV-02."""
        with self._write_lock:
            data = {"known_artists": []}
            if known_file.exists():
                with open(known_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {"known_artists": []}

            known_artists = set(a.lower() for a in data.get("known_artists", []))
            if artist_name.lower() in known_artists:
                return False

            data.setdefault("known_artists", []).append(artist_name)
            data["known_artists"] = sorted(set(data["known_artists"]))

            self._write_yaml_atomic(known_file, data)
            return True

    async def _save_alias(self, raw_name: str, canonical_name: str) -> bool:
        """Speichert einen Alias in auto_learned_artist_aliases.json
        (ARCH-022: vorher auto_learned_artists.yaml, dann
        auto_learned_artist_aliases.yaml - Namespace-Trennung vom
        "featured_artists"-Schluessel siehe _write_featured_observation_sync(),
        seitdem zusaetzlich JSON statt YAML - rein maschinell
        geschriebene/gelesene Datei, kein Kommentar-/Formatierungs-
        Bedarf)."""
        try:
            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            alias_file = mapping_dir / "auto_learned_artist_aliases.json"

            written = await asyncio.to_thread(
                self._write_alias_sync, alias_file, raw_name, canonical_name
            )
            if written:
                self.logger.info(
                    f"🧠 [AUTO-LEARN] ✅ Alias gelernt: '{raw_name}' → '{canonical_name}'"
                )
            else:
                self.logger.debug(
                    f"🧠 [AUTO-LEARN] Alias '{raw_name}' bereits vorhanden"
                )
            return written

        except Exception as e:
            self.logger.warning(
                f"⚠️ [AUTO-LEARN] auto_learned_artist_aliases.json fehlgeschlagen: {e}"
            )
        return False

    def _write_alias_sync(
        self, alias_file: Path, raw_name: str, canonical_name: str
    ) -> bool:
        """Sync-Kern von _save_alias() - siehe Klassen-Docstring INV-01/INV-02."""
        with self._write_lock:
            import json

            data = {"auto_learned": {}}
            if alias_file.exists():
                with open(alias_file, "r", encoding="utf-8") as f:
                    data = json.load(f) or {"auto_learned": {}}

            auto_learned = data.get("auto_learned", {})
            if raw_name.casefold() in (k.casefold() for k in auto_learned.keys()):
                return False

            data["auto_learned"][raw_name] = canonical_name
            self._write_json_atomic(alias_file, data)
            return True

    # ─────────────────────────────────────────────────────────────────────────
    # Feature-Artist-Beobachtung (Auto-Learn-Auftrag Abschnitt 4-10)
    #
    # Primary-/Feature-Trennung kommt bereits fertig vom Aufrufer (bestehende
    # TAG-01-Multi-Artist-Logik: split_main_and_featuring() /
    # ArtistProcessor.determine_best_artist()) - hier KEINE eigene
    # Artist-Parsing-Logik. Diese Methoden beobachten NUR, welche bereits
    # als "Feature-Artist" erkannten Namen wiederholt auftauchen, und lernen
    # AUSDRÜCKLICH KEIN Genre für sie (Abschnitt 16 - dafür existiert kein
    # Aufruf von learn_genre()/_write_genre_observation_sync() in diesem
    # Abschnitt).
    # ─────────────────────────────────────────────────────────────────────────

    async def observe_featured_artists(
        self,
        primary_artist: str,
        feat_artists: List[str],
        track_context: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Beobachtet Feature-Artists eines Tracks und aggregiert sie in
        auto_learned_featured_artists.json unter dem Schlüssel
        "featured_artists" (ARCH-022: eigene JSON-Datei, getrennt von
        auto_learned_artist_aliases.json für Channel-Name-Aliase - vorher
        beide Schlüssel in derselben YAML-Datei auto_learned_artists.yaml).

        Schreibt NIEMALS, wenn der (normalisierte) Name bereits anderweitig
        bekannt ist (Library/Overrides/known_artists/auto_learned - siehe
        _is_artist_known(), Abschnitt 10: manuelle Mappings gewinnen immer).

        Gibt eine Liste von Decision-Dicts zurück (ein Eintrag je
        Feature-Artist, gleiche Struktur wie preview_featured_artists() für
        identisches Dry-Run-/Live-Logging, Abschnitt 21/22).
        """
        return [
            await self._observe_single_featured_artist(
                primary_artist, raw_feat, track_context
            )
            for raw_feat in feat_artists
        ]

    def preview_featured_artists(
        self,
        primary_artist: str,
        feat_artists: List[str],
        track_context: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Reine Dry-Run-Vorschau (kein Schreiben) - identische
        Entscheidungslogik wie observe_featured_artists(), für
        scripts/reprocess_artist_metadata.py --dry-run.
        """
        return [
            self._compute_featured_artist_decision(
                primary_artist, raw_feat, track_context
            )
            for raw_feat in feat_artists
        ]

    def _compute_featured_artist_decision(
        self, primary_artist: str, raw_feat: str, track_context: str
    ) -> Dict[str, Any]:
        """
        Reine Entscheidungsberechnung (kein Schreiben) für einen einzelnen
        Feature-Artist. Wendet vor der Beobachtung die bestehende zentrale
        Artist-Normalisierung an (ArtistNormalizer.normalize() -
        case_preserve.yaml/artist_overrides.json/Kollaborations-Logik,
        Abschnitt 9 - keine eigene Normalisierung).
        """
        canonical = None
        if raw_feat and self.artist_normalizer is not None:
            canonical = self.artist_normalizer.normalize(raw_feat)

        decision: Dict[str, Any] = {
            "raw": raw_feat,
            "canonical": canonical,
            "primary_artist": primary_artist,
            "role": "featured_artist",
            "decision": "SKIPPED_INVALID",
            "reason": "leer oder nicht normalisierbar",
            "existing": None,
            "predicted_observations": 0,
            "predicted_confidence": None,
        }
        if not raw_feat or not canonical or canonical.strip().lower() == "unknown":
            return decision

        if canonical.strip().lower() == (primary_artist or "").strip().lower():
            decision["decision"] = "SKIPPED_IS_PRIMARY"
            decision["reason"] = "identisch mit Primary Artist"
            return decision

        if self._is_artist_known(canonical):
            decision["decision"] = "SKIPPED_KNOWN"
            decision["reason"] = (
                "bereits bekannt (Library/Overrides/known_artists/auto_learned) "
                "→ manuelle/bestehende Information hat Vorrang"
            )
            return decision

        _existing_key, existing_entry = self._read_featured_artist_entry(canonical)
        decision["existing"] = existing_entry
        decision["reason"] = None
        observations = (existing_entry.get("observations", 0) if existing_entry else 0) + 1
        decision["predicted_observations"] = observations
        decision["predicted_confidence"] = _confidence_tier(observations)
        decision["decision"] = "WOULD_UPDATE" if existing_entry else "WOULD_LEARN"
        return decision

    async def _observe_single_featured_artist(
        self, primary_artist: str, raw_feat: str, track_context: str
    ) -> Dict[str, Any]:
        decision = self._compute_featured_artist_decision(
            primary_artist, raw_feat, track_context
        )
        if decision["decision"] not in ("WOULD_LEARN", "WOULD_UPDATE"):
            return decision

        was_new = decision["decision"] == "WOULD_LEARN"
        try:
            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            alias_file = mapping_dir / "auto_learned_featured_artists.json"

            await asyncio.to_thread(
                self._write_featured_observation_sync,
                alias_file,
                decision["canonical"],
                primary_artist,
                track_context,
            )
            decision["decision"] = "LEARNED" if was_new else "UPDATED"
            self.logger.info(
                f"🧠 [AUTO-LEARN] ✅ Feature-Artist beobachtet: '{decision['canonical']}' "
                f"(Rolle: featured_artist, Beobachtungen: {decision['predicted_observations']}, "
                f"Status: {decision['predicted_confidence']}, Primary: '{primary_artist}')"
            )
        except Exception as e:
            self.logger.warning(
                f"⚠️ [AUTO-LEARN] Feature-Artist-Beobachtung fehlgeschlagen: {e}"
            )
            decision["decision"] = "ERROR"
            decision["reason"] = str(e)
        return decision

    def _read_featured_artist_entry(
        self, canonical_name: str
    ) -> Tuple[Optional[str], Optional[dict]]:
        """Liest (nur lesend) einen bestehenden Feature-Artist-Eintrag, case-insensitiv."""
        try:
            import json

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            alias_file = mapping_dir / "auto_learned_featured_artists.json"
            if not alias_file.exists():
                return None, None
            with open(alias_file, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            featured = data.get("featured_artists", {})
            if canonical_name in featured:
                return canonical_name, featured[canonical_name]
            search_lower = canonical_name.lower()
            for key, value in featured.items():
                if str(key).lower() == search_lower:
                    return key, value
            return None, None
        except Exception as e:
            self.logger.debug(f"Fehler in _read_featured_artist_entry: {e}")
            return None, None

    def _write_featured_observation_sync(
        self,
        alias_file: Path,
        canonical_name: str,
        primary_artist: str,
        track_context: str,
    ) -> bool:
        """
        Sync-Kern der Feature-Artist-Beobachtung (siehe Klassen-Docstring
        INV-01/INV-02). Schreibt in die eigene Datei
        auto_learned_featured_artists.json (ARCH-022: vorher gemeinsam mit
        dem "auto_learned"-Channel-Alias-Schluessel in derselben YAML-Datei -
        seit der Namespace-Trennung braucht diese Datei keinen
        "auto_learned"-Schluessel mehr; seitdem zusaetzlich JSON statt YAML).
        """
        with self._write_lock:
            import json

            data: dict = {}
            if alias_file.exists():
                with open(alias_file, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            data.setdefault("featured_artists", {})

            featured = data["featured_artists"]
            existing_key = canonical_name
            entry = None
            if canonical_name in featured:
                entry = featured[canonical_name]
            else:
                search_lower = canonical_name.lower()
                for key, value in featured.items():
                    if str(key).lower() == search_lower:
                        existing_key = key
                        entry = value
                        break

            if entry is None:
                entry = {
                    "canonical": canonical_name,
                    "role": "featured_artist",
                    "status": "OBSERVED",
                    "observations": 0,
                    "primary_artists": [],
                    "sources": [],
                }

            entry["observations"] = int(entry.get("observations", 0)) + 1
            entry["status"] = _confidence_tier(entry["observations"])

            primary_artists_seen = list(entry.get("primary_artists", []))
            if primary_artist and primary_artist not in primary_artists_seen:
                primary_artists_seen.append(primary_artist)
            entry["primary_artists"] = primary_artists_seen[-_MAX_PRIMARY_ARTISTS_SEEN:]

            sources = list(entry.get("sources", []))
            if "metadata" not in sources:
                sources.append("metadata")
            entry["sources"] = sources

            if track_context:
                entry["last_observed_track"] = track_context

            featured[existing_key] = entry
            data["featured_artists"] = featured

            self._write_json_atomic(alias_file, data)
            return True

    # ─────────────────────────────────────────────────────────────────────────
    # Hilfsmethoden
    # ─────────────────────────────────────────────────────────────────────────

    def _is_genre_already_learned(self, artist_name: str) -> bool:
        """
        Prüft ob Genre bereits in artist_genre.yaml oder auto_learned_genre.json
        existiert (case-insensitive).
        """
        try:
            import yaml

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))

            def search_in_map(genre_map: dict, search_name: str) -> bool:
                if not genre_map:
                    return False
                search_lower = search_name.lower()
                if search_name in genre_map:
                    return True
                for key in genre_map.keys():
                    if key.lower() == search_lower:
                        return True
                return False

            # Prüfe artist_genre.yaml (manuell)
            manual_file = mapping_dir / "artist_genre.yaml"
            if manual_file.exists():
                with open(manual_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                genre_map = data.get("ARTIST_GENRE_MAP", {})
                if search_in_map(genre_map, artist_name):
                    self.logger.debug(
                        f"🧠 [AUTO-LEARN] '{artist_name}' in artist_genre.yaml gefunden → überspringe"
                    )
                    return True

            # Prüfe auto_learned_genre.json (ARCH-022: vorher .yaml)
            import json

            auto_file = mapping_dir / "auto_learned_genre.json"
            if auto_file.exists():
                with open(auto_file, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                genre_map = data.get("ARTIST_GENRE_MAP", {})
                if search_in_map(genre_map, artist_name):
                    self.logger.debug(
                        f"🧠 [AUTO-LEARN] '{artist_name}' in auto_learned_genre.json gefunden → überspringe"
                    )
                    return True

        except Exception as e:
            self.logger.debug(f"Fehler in _is_genre_already_learned: {e}")
        return False

    def _is_genre_manually_defined(self, artist_name: str) -> bool:
        """
        Prüft NUR artist_genre.yaml (manuelle Konfiguration) - im Unterschied
        zu _is_genre_already_learned() (das zusätzlich auto_learned_genre.json
        einschließt und daher für die Frage "darf weiter aggregiert werden"
        zu weit greift). Nur ein manueller Eintrag blockiert Auto-Learn
        dauerhaft (Auto-Learn-Auftrag Abschnitt 13/14) - ein bereits
        vorhandener Auto-Learn-Eintrag soll stattdessen weiter aggregiert
        werden statt für immer eingefroren zu bleiben (Abschnitt 11/12).
        """
        try:
            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            manual_file = mapping_dir / "artist_genre.yaml"
            if not manual_file.exists():
                return False
            with open(manual_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            genre_map = data.get("ARTIST_GENRE_MAP", {})
            if not genre_map:
                return False
            if artist_name in genre_map:
                return True
            search_lower = artist_name.lower()
            return any(str(key).lower() == search_lower for key in genre_map.keys())
        except Exception as e:
            self.logger.debug(f"Fehler in _is_genre_manually_defined: {e}")
            return False

    def _is_artist_known(self, artist_name: str) -> bool:
        """Prüft ob Artist bekannt ist (Library, Overrides, known_artists.yaml, auto_learned_artist_aliases.json)"""
        if not artist_name:
            return False

        artist_key = artist_name.strip().casefold()

        # 1. Library Artists
        if hasattr(self.artist_normalizer, "library_artists"):
            for lib_artist in self.artist_normalizer.library_artists:
                if str(lib_artist).casefold() == artist_key:
                    return True

        # 2. Overrides
        if hasattr(self.artist_normalizer, "overrides_normalized"):
            for (
                override_key,
                override_val,
            ) in self.artist_normalizer.overrides_normalized.items():
                if (
                    str(override_key).casefold() == artist_key
                    or str(override_val).casefold() == artist_key
                ):
                    return True

        # 3. known_artists.yaml (neu)
        try:
            import yaml

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            known_file = mapping_dir / "known_artists.yaml"
            if known_file.exists():
                with open(known_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                known_artists = data.get("known_artists", [])
                if artist_name in known_artists or any(
                    a.casefold() == artist_key for a in known_artists
                ):
                    return True
        except Exception:
            pass

        # 4. auto_learned_artist_aliases.json (Alias-Quellen und -Ziele,
        #    ARCH-022: vorher .yaml)
        try:
            import json

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            alias_file = mapping_dir / "auto_learned_artist_aliases.json"
            if alias_file.exists():
                with open(alias_file, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                auto_learned = data.get("auto_learned", {})
                for raw_alias, canonical in auto_learned.items():
                    if (
                        str(raw_alias).casefold() == artist_key
                        or str(canonical).casefold() == artist_key
                    ):
                        return True
        except Exception:
            pass

        return False

    def _is_non_artist_channel(self, channel: str) -> bool:
        """
        Prüft ob ein Channel-Name auf einen Nicht-Artist-Channel hindeutet
        (Label, Compilation, Playlist, etc.).
        """
        if not channel:
            return False
        channel_lower = channel.strip().lower()
        non_artist_patterns = [
            r" - topic$",
            r"topic$",
            r"channel$",
            r"vevo$",
            r"music$",
            r"official$",
            r"records$",
            r"entertainment$",
            r"^various artists",
            r"compilation",
            r"playlist",
            r"mix$",
            r"hd$",
            r"lyrics$",
            r"beatz$",
            r"type beat",
        ]
        for pattern in non_artist_patterns:
            if re.search(pattern, channel_lower, re.IGNORECASE):
                self.logger.debug(f"🧠 [AUTO-LEARN] Non-Artist-Channel: '{channel}'")
                return True
        return False

    def create_genre_info_from_result(
        self, genres_result, raw_tags=None
    ) -> SimpleNamespace:
        """
        Konvertiert ein GenreResult-Objekt in ein serialisierbares SimpleNamespace.
        Nützlich für Auto-Learning wenn das Original-Objekt nicht direkt verwendbar ist.
        """
        return SimpleNamespace(
            primary=genres_result.primary,
            secondary=list(getattr(genres_result, "secondary", [])),
            source=getattr(genres_result, "source", "unknown"),
            raw_tags=list(raw_tags or getattr(genres_result, "raw_tags", [])),
        )

    def _load_auto_learned_artists(self) -> Dict[str, str]:
        """Lädt auto_learned_artist_aliases.json (ARCH-022: vorher
        auto_learned_artists.yaml, dann auto_learned_artist_aliases.yaml)."""
        try:
            import json

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            auto_file = mapping_dir / "auto_learned_artist_aliases.json"
            if not auto_file.exists():
                return {}

            with open(auto_file, "r", encoding="utf-8") as f:
                data = json.load(f) or {}

            return data.get("auto_learned", {})
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Fehler beim Laden der auto_learned_artists: {e}")
            return {}

    def _load_auto_learned_genres(self) -> Dict[str, Any]:
        """Lädt auto_learned_genre.json (ARCH-022: vorher .yaml)"""
        try:
            import json

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            auto_file = mapping_dir / "auto_learned_genre.json"
            if not auto_file.exists():
                return {}

            with open(auto_file, "r", encoding="utf-8") as f:
                data = json.load(f) or {}

            return data.get("ARTIST_GENRE_MAP", {})
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Fehler beim Laden der auto_learned_genres: {e}")
            return {}
