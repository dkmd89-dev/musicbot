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

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

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


def _find_mapping_key(mapping: dict, artist: str) -> Optional[str]:
    """Tatsaechlicher (ggf. gemischt geschriebener) Key eines Artists in
    ARTIST_GENRE_MAP — casefold-Lookup, identisch zu genre_from_mapping().
    None, wenn der Artist nicht vorkommt."""
    wanted = artist.casefold()
    for k in mapping:
        if isinstance(k, str) and k.casefold() == wanted:
            return k
    return None


def save_manual_genre_mapping(
    artist: str, genre: str, mapping_dir: Path, *, dry_run: bool = True,
    default_description: Optional[str] = None,
) -> ManualMappingSaveResult:
    """Traegt `genre` (bereits normalisiert, z. B. ueber
    normalize_genre_input()) als manuelles Mapping in artist_genre.yaml
    ein - identische Semantik zu scripts/library_repair.py::
    _update_manual_genre_mapping() (dorthin ARCH-031 A.4 urspruenglich
    CLI-only ausgelagert, hierher extrahiert siehe Modul-Docstring).

    `genre` wird an ';' in primary/secondary aufgeteilt (erster Teil =
    primary, Rest = secondary) - identisch zur bisherigen CLI-Logik.
    Case-insensitiver Artist-Key: ein BESTEHENDER Eintrag wird unter seinem
    tatsaechlichen Key aktualisiert (auch bei gemischter Schreibweise wie
    "Dua Lipa" — sonst entstuende ein zweiter, kleingeschriebener Key, den
    genre_from_mapping() (erster casefold-Treffer) und GenreMapper
    (lowercased Keys) unterschiedlich aufloesen wuerden). Ein NEUER Eintrag
    bekommt den lowercase-Key, wie GenreMapper/AutoLearnManager es erwarten.

    `default_description` gilt nur fuer NEUE Eintraege (bestehende behalten
    ihre Beschreibung); None -> bisheriger CLI-Text.

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

    key = _find_mapping_key(mapping, artist) or artist.lower()
    existing = mapping.get(key)
    new_entry = {
        "primary": primary,
        "secondary": secondary,
        "description": (existing or {}).get(
            "description",
            default_description
            or "Manuell gesetzt via library_repair.py --maintenance-action set-genre",
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


# ─────────────────────────────────────────────────────────────────────────
# Genre-Mapping bearbeiten (Primary + Secondary) — Control Center
#
# Lesen/Pruefen/Schreiben EINES Artist-Eintrags in artist_genre.yaml. Die
# Fachlogik liegt hier (Web und Telegram sind gleichrangige Clients); der
# Schreibvorgang selbst bleibt save_manual_genre_mapping().
# ─────────────────────────────────────────────────────────────────────────

MAX_GENRE_LENGTH = 100
MAX_SECONDARY_GENRES = 20
MAX_ARTIST_LENGTH = 200
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

# Schreib-Serialisierung innerhalb dieses Prozesses (Check-and-Write). Der
# Bot-Prozess schreibt artist_genre.yaml nur ueber Telegram/CLI.
_MAPPING_WRITE_LOCK = threading.Lock()


class GenreMappingUnavailableError(GenreDomainError):
    """artist_genre.yaml fehlt oder ist nicht lesbar."""


class GenreMappingConflictError(GenreDomainError):
    """Der Eintrag wurde seit der Vorschau geaendert (veralteter Etag)."""


@dataclass(frozen=True)
class GenreMappingEntry:
    key: str  # tatsaechlicher Key in der Datei
    primary: str
    secondary: List[str]
    description: Optional[str]


@dataclass(frozen=True)
class GenreMappingPlan:
    """Ergebnis von plan_manual_genre_mapping() — reine Vorschau."""

    artist_key: str          # bestehender Key bzw. lowercase-Key bei "create"
    change: str              # "create" | "update" | "unchanged"
    existing: Optional[GenreMappingEntry]
    primary: str             # normalisiert
    secondary: List[str]     # normalisiert
    primary_changed: bool
    added: List[str]         # Genres (primary+secondary), die neu sind
    removed: List[str]       # Genres, die wegfallen
    warnings: List[str]
    etag: str                # Ist-Zustand des Eintrags VOR der Aenderung


def _mapping_file(mapping_dir: Path) -> Path:
    return Path(mapping_dir) / "artist_genre.yaml"


def _load_mapping(mapping_path: Path) -> dict:
    """ARTIST_GENRE_MAP als dict; wirft GenreMappingUnavailableError."""
    import yaml

    if not mapping_path.exists():
        raise GenreMappingUnavailableError(f"{mapping_path} fehlt — Genre-Mapping nicht verfuegbar.")
    try:
        data = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise GenreMappingUnavailableError(f"{mapping_path} nicht lesbar: {e}") from e
    mapping = data.get("ARTIST_GENRE_MAP") if isinstance(data, dict) else None
    return mapping if isinstance(mapping, dict) else {}


def _entry_from_raw(key: str, raw: object) -> Optional[GenreMappingEntry]:
    if not isinstance(raw, dict):
        return None
    secondary = raw.get("secondary") or []
    if not isinstance(secondary, list):
        secondary = []
    return GenreMappingEntry(
        key=key,
        primary=str(raw.get("primary") or "").strip(),
        secondary=[str(x).strip() for x in secondary if str(x).strip()],
        description=raw.get("description"),
    )


def read_genre_mapping_entry(artist: str, mapping_path: Path) -> Optional[GenreMappingEntry]:
    """Strukturierter Eintrag (primary/secondary getrennt) oder None, wenn der
    Artist nicht im Mapping steht oder die Datei fehlt (casefold-Lookup)."""
    try:
        mapping = _load_mapping(mapping_path)
    except GenreMappingUnavailableError:
        return None
    key = _find_mapping_key(mapping, artist)
    return _entry_from_raw(key, mapping[key]) if key is not None else None


def known_genres(mapping_path: Path) -> List[str]:
    """Alle in artist_genre.yaml vorkommenden Genre-Namen (primary + secondary),
    ohne Duplikate (casefold), alphabetisch — Vorschlagsliste fuer die UI und
    Grundlage der Tippfehler-Warnung."""
    try:
        mapping = _load_mapping(mapping_path)
    except GenreMappingUnavailableError:
        return []
    seen: dict = {}
    for k, raw in mapping.items():
        entry = _entry_from_raw(str(k), raw)
        if entry is None:
            continue
        for g in [entry.primary] + entry.secondary:
            if g:
                seen.setdefault(g.casefold(), g)
    return sorted(seen.values(), key=str.casefold)


def _validate_genre_name(value: object, label: str) -> str:
    raw = str(value if value is not None else "")
    if _CONTROL_CHARS.search(raw):  # vor der Whitespace-Bereinigung (Zeilenumbruch != Leerzeichen)
        raise GenreDomainError(f"{label} enthaelt Steuerzeichen.")
    text = re.sub(r"\s+", " ", raw).strip()
    if not text:
        raise GenreDomainError(f"{label} darf nicht leer sein.")
    if ";" in text:
        raise GenreDomainError(f"{label} darf kein ';' enthalten (Genres einzeln angeben): {text!r}")
    if len(text) > MAX_GENRE_LENGTH:
        raise GenreDomainError(f"{label} ist laenger als {MAX_GENRE_LENGTH} Zeichen.")
    return text


def normalize_genre_fields(primary: object, secondary: object) -> Tuple[str, List[str]]:
    """Prueft und normalisiert die Eingabe: Whitespace bereinigt, Leere
    entfernt, Duplikate (casefold) und ein zum Primary gleiches Secondary
    entfernt; Schreibweise und Reihenfolge des Nutzers bleiben erhalten.
    Wirft GenreDomainError bei leerem Primary, ';', Steuerzeichen,
    zu langen Werten oder mehr als MAX_SECONDARY_GENRES Eintraegen."""
    clean_primary = _validate_genre_name(primary, "Primary-Genre")
    items = list(secondary or [])
    if len(items) > MAX_SECONDARY_GENRES:
        raise GenreDomainError(f"Maximal {MAX_SECONDARY_GENRES} Secondary-Genres erlaubt.")
    clean: List[str] = []
    seen = {clean_primary.casefold()}
    for raw in items:
        if raw is None or not str(raw).strip():
            continue
        g = _validate_genre_name(raw, "Secondary-Genre")
        if g.casefold() not in seen:
            seen.add(g.casefold())
            clean.append(g)
    return clean_primary, clean


def _validate_artist_name(artist: object) -> str:
    text = str(artist if artist is not None else "").strip()
    if not text:
        raise GenreDomainError("Artist darf nicht leer sein.")
    if _CONTROL_CHARS.search(text):
        raise GenreDomainError("Artist enthaelt Steuerzeichen.")
    if len(text) > MAX_ARTIST_LENGTH:
        raise GenreDomainError(f"Artist ist laenger als {MAX_ARTIST_LENGTH} Zeichen.")
    return text


def genre_mapping_etag(entry: Optional[GenreMappingEntry], artist_key: str) -> str:
    """Opaker Fingerabdruck des bearbeitbaren Ist-Zustands (Key, primary,
    secondary; nicht die Beschreibung). "Nicht vorhanden" hat ebenfalls einen
    Etag — so faellt auch ein zwischenzeitlich angelegter Eintrag auf."""
    payload = (
        {"missing": artist_key.casefold()}
        if entry is None
        else {"key": entry.key, "primary": entry.primary, "secondary": entry.secondary}
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def get_genre_mapping(artist: str, mapping_dir: Path) -> Tuple[Optional[GenreMappingEntry], str]:
    """Aktueller Eintrag (oder None) plus Etag fuer die Bearbeitung. Wirft
    GenreDomainError (Artist ungueltig) bzw. GenreMappingUnavailableError."""
    artist = _validate_artist_name(artist)
    mapping = _load_mapping(_mapping_file(mapping_dir))
    key = _find_mapping_key(mapping, artist)
    entry = _entry_from_raw(key, mapping[key]) if key is not None else None
    return entry, genre_mapping_etag(entry, key if key is not None else artist.lower())


def plan_manual_genre_mapping(
    artist: str, primary: object, secondary: object, mapping_dir: Path,
) -> GenreMappingPlan:
    """Reine Vorschau (kein Schreibzugriff): was wuerde sich im Mapping fuer
    diesen Artist aendern? Wirft GenreDomainError (Eingabe) bzw.
    GenreMappingUnavailableError (Datei fehlt/kaputt)."""
    artist = _validate_artist_name(artist)
    new_primary, new_secondary = normalize_genre_fields(primary, secondary)
    path = _mapping_file(mapping_dir)
    mapping = _load_mapping(path)

    key = _find_mapping_key(mapping, artist)
    existing = _entry_from_raw(key, mapping[key]) if key is not None else None
    artist_key = key if key is not None else artist.lower()

    new_all = [new_primary] + new_secondary
    old_all = ([existing.primary] + existing.secondary) if existing else []
    old_fold = {g.casefold() for g in old_all}
    new_fold = {g.casefold() for g in new_all}
    added = [g for g in new_all if g.casefold() not in old_fold]
    removed = [g for g in old_all if g and g.casefold() not in new_fold]

    if existing is None:
        change = "create"
    elif existing.primary == new_primary and existing.secondary == new_secondary:
        change = "unchanged"
    else:
        change = "update"

    already_known = {g.casefold() for g in known_genres(path)}
    warnings = [
        f"Genre {g!r} kommt sonst nirgends im Mapping vor — Tippfehler?"
        for g in added if g.casefold() not in already_known
    ]

    return GenreMappingPlan(
        artist_key=artist_key,
        change=change,
        existing=existing,
        primary=new_primary,
        secondary=new_secondary,
        primary_changed=existing is None or existing.primary != new_primary,
        added=added,
        removed=removed,
        warnings=warnings,
        etag=genre_mapping_etag(existing, artist_key),
    )


def apply_manual_genre_mapping(
    artist: str, primary: object, secondary: object, mapping_dir: Path, *,
    expected_etag: str, default_description: Optional[str] = None,
) -> Tuple[GenreMappingPlan, ManualMappingSaveResult]:
    """Schreibt Primary/Secondary eines Artists in artist_genre.yaml, aber nur,
    wenn der Eintrag seit der Vorschau unveraendert ist (`expected_etag`,
    sonst GenreMappingConflictError, nichts wird geschrieben). Check und
    Write laufen unter einem Lock. Schreiben selbst: save_manual_genre_mapping()
    (atomar, andere Eintraege und deren Reihenfolge bleiben unveraendert)."""
    with _MAPPING_WRITE_LOCK:
        plan = plan_manual_genre_mapping(artist, primary, secondary, mapping_dir)
        if plan.etag != expected_etag:
            raise GenreMappingConflictError(
                "Der Mapping-Eintrag wurde seit der Vorschau geaendert — bitte neu laden."
            )
        result = save_manual_genre_mapping(
            artist.strip(), "; ".join([plan.primary] + plan.secondary), mapping_dir,
            dry_run=False, default_description=default_description,
        )
    return plan, result


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
