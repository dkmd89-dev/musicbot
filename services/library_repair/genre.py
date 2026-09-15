# services/library_repair/genre.py
# -*- coding: utf-8 -*-
"""
Library-Maintenance — Genre-Domain-Logik (ARCH-032 Phase 1).

Reine Funktionen fuer zwei Maintenance-Actions:
  - legacy-genre-cleanup: Legacy-Freeform-Atom
    '----:com.apple.iTunes:GENRE' entfernen, WENN das kanonische '©gen'
    vorhanden ist (extrahiert aus scripts/remove_legacy_genre_atom.py)
  - set-genre: '©gen' gezielt setzen, manuell oder aus
    mapping/artist_genre.yaml (extrahiert aus scripts/set_genre.py)

Liest bewusst dieselbe mapping/artist_genre.yaml wie
utils/genre_map.py::GenreMapper (Manual-Tier von determine_genre()) —
GEWOLLTE Duplikation (ARCH-031 B.2, siehe
tests/test_library_repair_genre.py::test_genre_from_mapping_matches_genre_mapper_manual_tier
fuer den Cross-Consistency-Schutz gegen Schema-Drift). GenreMapper ist
ein schwergewichtiges SingletonMixin mit externen API-Clients
(download-zeit-orientiert), dieses Modul bleibt bewusst leichtgewichtig
(Praezedenz: tag_repairs.py's Nachbildung von split_main_and_featuring()
statt Import von services.metadata).

Kein Dateisystem-Zugriff ausser dem Lesen von artist_genre.yaml und -
seit Library Genre Management v2 (Chat-Charakterisierung 2026-09-15,
siehe save_manual_genre_mapping() unten) - dem gezielten Schreiben
genau dieser einen Datei fuer `--update-manual-mapping`. Weiterhin
KEINE Mutagen-/Backup-/Journal-Logik (das bleibt executor.py
vorbehalten, ARCH-031 B.3) - artist_genre.yaml ist eine Config-/
Mapping-Datei, keine Library-Audiodatei, daher kein Audio-Essenz-
Backup-Bedarf, identisch zur bisherigen CLI-Argumentation.

save_manual_genre_mapping() war urspruenglich (ARCH-031 A.4) bewusst
CLI-only (scripts/library_repair.py::_update_manual_genre_mapping()) -
mit Library Genre Management v2 nach hier extrahiert, DAMIT sowohl die
CLI (duenner Wrapper) als auch der neue Telegram-Handler (der laut
CLAUDE.md §4 niemals direkt auf Dateien schreiben darf) dieselbe,
einzige Schreiblogik verwenden. Keine Verhaltensaenderung gegenueber
der vorherigen CLI-Funktion.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

CANONICAL_GENRE_ATOM = "\xa9gen"
LEGACY_GENRE_ATOM = "----:com.apple.iTunes:GENRE"


class GenreDomainError(Exception):
    """Reine Domain-Fehler dieses Moduls (z. B. artist_genre.yaml fehlt) -
    bewusst KEIN Import von maintenance_service.MaintenanceServiceError
    hier (genre.py bleibt die untere, abhaengigkeitsfreie Domain-Schicht,
    siehe Modul-Docstring; maintenance_service.py importiert genre.py,
    nicht umgekehrt - ein Ruecking-Import wuerde einen Zyklus erzeugen).
    Aufrufer in maintenance_service.py fangen dies ab und wandeln es in
    MaintenanceServiceError um."""


# ─────────────────────────────────────────────────────────────────────────
# set-genre: Genre-Wert-Normalisierung
# ─────────────────────────────────────────────────────────────────────────


def normalize_genre_input(raw: str) -> str:
    """Akzeptiert 'A; B' / 'A, B' / 'A / B' und liefert 'A; B'. Identische
    Semantik zu scripts/set_genre.py::normalize_genre_input()."""
    s = raw.strip()
    for sep in (" / ", ", "):
        if sep in s:
            s = s.replace(sep, "; ")
    parts = [p.strip() for p in s.split(";") if p.strip()]
    return "; ".join(parts)


# ─────────────────────────────────────────────────────────────────────────
# set-genre: Mapping-Lookup (artist_genre.yaml)
# ─────────────────────────────────────────────────────────────────────────


def genre_from_mapping(artist: str, mapping_path: Path) -> Optional[str]:
    """Liest primary+secondary aus artist_genre.yaml fuer einen Artist
    (case-insensitive Key-Lookup). Liefert 'A; B; C' oder None, wenn der
    Artist nicht im Mapping steht. Identische Semantik zu
    scripts/set_genre.py::genre_from_mapping()."""
    import yaml

    if not mapping_path.exists():
        return None
    data = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    mapping = data.get("ARTIST_GENRE_MAP") or {}

    key = artist.casefold()
    entry = None
    for k, v in mapping.items():
        if isinstance(k, str) and k.casefold() == key:
            entry = v
            break

    if not entry or not isinstance(entry, dict):
        return None

    primary = (entry.get("primary") or "").strip()
    secondary = entry.get("secondary") or []
    if not isinstance(secondary, list):
        secondary = []

    parts = [primary] + [str(x).strip() for x in secondary if str(x).strip()]
    seen = set()
    uniq: List[str] = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    return "; ".join(uniq) if uniq else None


@dataclass(frozen=True)
class ManualMappingSaveResult:
    """Ergebnis eines save_manual_genre_mapping()-Aufrufs - fuer die
    Praesentationsschicht (CLI-Print, Telegram-Ergebnistext), keine
    eigene Statuslogik ausser 'was ist passiert'."""

    written: bool  # True nur bei echtem Schreiben (dry_run=False + Aenderung)
    unchanged: bool  # True, wenn bereits identisch in artist_genre.yaml stand
    dry_run: bool
    artist_key: str
    primary: str
    secondary: List[str]
    mapping_path: str


def save_manual_genre_mapping(
    artist: str, genre: str, mapping_dir: Path, *, dry_run: bool = True,
) -> ManualMappingSaveResult:
    """Traegt `genre` (bereits normalisiert, z. B. ueber
    normalize_genre_input()) als manuelles Mapping in artist_genre.yaml
    ein - identische Semantik zu scripts/library_repair.py::
    _update_manual_genre_mapping() (dorthin ARCH-031 A.4 urspruenglich
    CLI-only ausgelagert, hierher extrahiert siehe Modul-Docstring).

    `genre` wird an ';' in primary/secondary aufgeteilt (erster Teil =
    primary, Rest = secondary) - identisch zur bisherigen CLI-Logik.
    Case-insensitiver Artist-Key (lowercase), wie GenreMapper/
    AutoLearnManager es fuer artist_genre.yaml erwarten.

    Schreibt NUR bei dry_run=False UND tatsaechlicher Aenderung
    (identischer Bestandseintrag => unchanged=True, written=False, kein
    Schreibzugriff). Atomarer Write (tmp + replace()), identisch zum
    bisherigen Verhalten."""
    import yaml

    path = mapping_dir / "artist_genre.yaml"
    if not path.exists():
        raise GenreDomainError(
            f"{path} fehlt — Mapping-Update nicht möglich."
        )

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mapping = data.get("ARTIST_GENRE_MAP") or {}

    parts = [p.strip() for p in genre.split(";") if p.strip()]
    primary = parts[0] if parts else genre
    secondary = parts[1:] if len(parts) > 1 else []

    key = artist.lower()
    existing = mapping.get(key)
    new_entry = {
        "primary": primary,
        "secondary": secondary,
        "description": (existing or {}).get(
            "description",
            "Manuell gesetzt via library_repair.py --maintenance-action set-genre",
        ),
    }

    if existing == new_entry:
        return ManualMappingSaveResult(
            written=False, unchanged=True, dry_run=dry_run, artist_key=key,
            primary=primary, secondary=secondary, mapping_path=str(path),
        )

    if dry_run:
        return ManualMappingSaveResult(
            written=False, unchanged=False, dry_run=True, artist_key=key,
            primary=primary, secondary=secondary, mapping_path=str(path),
        )

    mapping[key] = new_entry
    data["ARTIST_GENRE_MAP"] = mapping
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    tmp.replace(path)
    return ManualMappingSaveResult(
        written=True, unchanged=False, dry_run=False, artist_key=key,
        primary=primary, secondary=secondary, mapping_path=str(path),
    )


def known_artist_keys(mapping_path: Path) -> List[str]:
    """Bekannte Artist-Keys aus artist_genre.yaml, sortiert — fuer
    Fehlermeldungen, wenn ein Artist nicht gefunden wird. Identische
    Semantik zu scripts/set_genre.py::_known_artist_keys()."""
    import yaml

    if not mapping_path.exists():
        return []
    data = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    return sorted(
        k for k in (data.get("ARTIST_GENRE_MAP") or {}).keys() if isinstance(k, str)
    )


# ─────────────────────────────────────────────────────────────────────────
# legacy-genre-cleanup: Entfernungs-Entscheidung
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LegacyGenreDecision:
    """Ergebnis der reinen Entscheidung, ob das Legacy-Atom entfernt
    werden darf. `should_remove=False` heisst: nichts zu tun (kein
    Legacy-Atom ODER kein ©gen vorhanden — wuerde Information verlieren,
    Regel aus scripts/remove_legacy_genre_atom.py unveraendert)."""

    should_remove: bool
    reason: Optional[str] = None  # gesetzt, wenn should_remove=False
    legacy_text: Optional[str] = None
    canonical_text: Optional[str] = None
    content_mismatch: bool = False  # informativ: Legacy-Inhalt != ©gen-Inhalt


def _atom_as_text(v) -> str:
    if isinstance(v, list) and v:
        x = v[0]
        if isinstance(x, bytes):
            return x.decode("utf-8", errors="replace")
        return str(x)
    return str(v)


def decide_legacy_genre_removal(legacy_value, canonical_value) -> LegacyGenreDecision:
    """legacy_value/canonical_value: Rohwerte der beiden Atome, wie von
    mutagen gelesen (Liste oder None/leer). Identische Semantik zu
    scripts/remove_legacy_genre_atom.py::fix_one()'s Entscheidungsteil —
    inhaltliche Abweichung zwischen Legacy- und ©gen-Wert blockiert die
    Entfernung NICHT (wird nur informativ als `content_mismatch`
    markiert), unveraendertes Originalverhalten."""
    if legacy_value is None:
        return LegacyGenreDecision(should_remove=False, reason="kein Legacy-Atom")

    if not canonical_value:
        return LegacyGenreDecision(
            should_remove=False,
            reason="kein ©gen vorhanden (würde Information verlieren)",
        )

    legacy_text = _atom_as_text(legacy_value)
    legacy_normalized = legacy_text.replace(", ", "; ").replace(" / ", "; ")
    canonical_text = canonical_value[0] if canonical_value else ""

    return LegacyGenreDecision(
        should_remove=True,
        legacy_text=legacy_text,
        canonical_text=canonical_text,
        content_mismatch=(legacy_normalized != canonical_text),
    )
