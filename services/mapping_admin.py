# services/mapping_admin.py
# -*- coding: utf-8 -*-
"""
Mapping-Administration — Application-Layer (M1, 2026-09-29).

Kleinste notwendige Schicht für schreibende Mapping-Verwaltung aus dem
Control Center. Erster Anwendungsfall: `mapping/channel_genre.yaml`
(Channel → Genre-Zuordnung). Die Struktur ist bewusst so angelegt, dass
weitere Mapping-Dateien (M2+) als zusätzliche Descriptor-Einträge in
`_MAPPING_DESCRIPTORS` und mit eigenen `*_admin`-Funktionen ergänzt werden
können, ohne die bestehende Struktur zu ändern.

Bewusst NICHT in services/library_repair/genre.py erweitert: Mapping-
Administration ist ein eigener Bereich neben der Repair-Domain, auch
wenn beide dieselbe Datei lesen (channel_genre.yaml wird nur gelesen,
nie geschrieben — weder von der Pipeline noch vom CC).

Sicherheit / Design:
  - Keine Dateipfade aus dem Client. Der Router wählt über eine
    `mapping_id` aus einer serverseitigen Allowlist.
  - Etag-Konkurrenz bezieht sich auf den GESAMTEN Mapping-Stand, nicht
    nur den betroffenen Eintrag. Damit ist auch der Create-Fall gegen
    zwischenzeitliche Änderungen durch Dritte geschützt.
  - Atomarer Write (tmp + replace).
  - Kein cross_process_lock: channel_genre.yaml hat keinen zweiten
    Schreiber (siehe Characterization).
  - Genre-Validierung über services/library_repair/genre.py::
    validate_genre_name — keine zweite Validierungslogik.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from services.library_repair.genre import (
    GenreDomainError,
    validate_genre_name as _validate_genre_name_domain,
)


# ─────────────────────────────────────────────────────────────────────────
# Allowlist / Descriptor
# ─────────────────────────────────────────────────────────────────────────

MAPPING_ID_CHANNEL_GENRE = "channel-genre"

MAPPING_FILENAME_CHANNEL_GENRE = "channel_genre.yaml"
MAPPING_ROOT_KEY_CHANNEL_GENRE = "CHANNEL_GENRE_MAP"

_MAPPING_DESCRIPTORS: Dict[str, Dict[str, str]] = {
    MAPPING_ID_CHANNEL_GENRE: {
        "filename": MAPPING_FILENAME_CHANNEL_GENRE,
        "root_key": MAPPING_ROOT_KEY_CHANNEL_GENRE,
        "kind": "channel-genre",
    },
}


# ─────────────────────────────────────────────────────────────────────────
# Fehlerklassen
# ─────────────────────────────────────────────────────────────────────────


class MappingDomainError(Exception):
    """Basisklasse für alle Fehler dieses Moduls (analog GenreDomainError)."""


class MappingUnavailableError(MappingDomainError):
    """Mapping-Datei fehlt oder ist nicht lesbar/korrupt."""


class MappingConflictError(MappingDomainError):
    """Der Mapping-Stand wurde seit der Vorschau geändert (veralteter Etag)."""


class MappingInvalidInputError(MappingDomainError):
    """Eingabewert ungültig (leer, zu lang, Steuerzeichen, ...)."""


class MappingUnknownIdError(MappingDomainError):
    """mapping_id nicht in der Allowlist."""


# ─────────────────────────────────────────────────────────────────────────
# Validierungs-Konstanten
# ─────────────────────────────────────────────────────────────────────────

MAX_CHANNEL_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 500
MAX_SECONDARY_ENTRIES = 20

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


# ─────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChannelGenreEntry:
    key: str
    primary: str
    secondary: List[str]
    description: Optional[str]


@dataclass(frozen=True)
class ChannelGenrePlan:
    key: str
    change: str  # "create" | "update" | "unchanged"
    existing: Optional[ChannelGenreEntry]
    primary: str
    secondary: List[str]
    description: Optional[str]
    primary_changed: bool
    added: List[str]
    removed: List[str]
    warnings: List[str]
    etag: str


@dataclass(frozen=True)
class ChannelGenreSaveResult:
    written: bool
    unchanged: bool
    key: str
    primary: str
    secondary: List[str]
    new_etag: str


# ─────────────────────────────────────────────────────────────────────────
# Validierung
# ─────────────────────────────────────────────────────────────────────────


def _validated_genre(value: object, label: str) -> str:
    """Ruft den bestehenden Domain-Validator und konvertiert dessen
    GenreDomainError in MappingInvalidInputError — keine zweite
    Validierungslogik, nur eine Exception-Bruecke fuer die API-Schicht."""
    try:
        return _validate_genre_name_domain(value, label)
    except GenreDomainError as e:
        raise MappingInvalidInputError(str(e)) from e


def _validate_channel_name(value: object) -> str:
    """Channel-Namen sind permissiver als Artist-Namen ('.', ':', '_', '-'
    und Umlaute sind zulässig — z. B. 'kontor.tv', 'RTL: Crime')."""
    if value is None:
        raise MappingInvalidInputError("Channel-Name darf nicht leer sein.")
    if not isinstance(value, str):
        raise MappingInvalidInputError("Channel-Name muss ein Text sein.")
    if "\n" in value or "\r" in value:
        raise MappingInvalidInputError("Channel-Name darf keine Zeilenumbrüche enthalten.")
    trimmed = value.strip()
    if not trimmed:
        raise MappingInvalidInputError("Channel-Name darf nicht leer sein.")
    if len(trimmed) > MAX_CHANNEL_LENGTH:
        raise MappingInvalidInputError(
            f"Channel-Name zu lang (max. {MAX_CHANNEL_LENGTH} Zeichen)."
        )
    if _CONTROL_CHARS.search(trimmed):
        raise MappingInvalidInputError("Channel-Name enthält Steuerzeichen.")
    return trimmed


def _validate_description(value: object) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MappingInvalidInputError("Beschreibung muss ein Text sein.")
    if "\n" in value or "\r" in value:
        # Bewusst erlaubt in YAML, aber wir halten es einfach — keine Newlines.
        raise MappingInvalidInputError("Beschreibung darf keine Zeilenumbrüche enthalten.")
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) > MAX_DESCRIPTION_LENGTH:
        raise MappingInvalidInputError(
            f"Beschreibung zu lang (max. {MAX_DESCRIPTION_LENGTH} Zeichen)."
        )
    if _CONTROL_CHARS.search(trimmed):
        raise MappingInvalidInputError("Beschreibung enthält Steuerzeichen.")
    return trimmed


def _validate_secondary_list(raw: object, primary: str) -> Tuple[List[str], List[str]]:
    """Dedupliziert case-insensitiv gegen `primary` und untereinander.
    Liefert (bereinigte Liste, Warnungen)."""
    warnings: List[str] = []
    if raw is None:
        return [], warnings
    if not isinstance(raw, (list, tuple)):
        raise MappingInvalidInputError("Secondary-Genres müssen eine Liste sein.")
    if len(raw) > MAX_SECONDARY_ENTRIES:
        raise MappingInvalidInputError(
            f"Zu viele Secondary-Genres (max. {MAX_SECONDARY_ENTRIES})."
        )
    primary_fold = primary.casefold()
    seen: set = set()
    result: List[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise MappingInvalidInputError("Secondary-Genre muss ein Text sein.")
        clean = _validated_genre(item, "Secondary-Genre")
        fold = clean.casefold()
        if fold == primary_fold:
            warnings.append(f"'{clean}' entspricht dem Primary-Genre und wurde entfernt.")
            continue
        if fold in seen:
            warnings.append(f"'{clean}' war doppelt und wurde entfernt.")
            continue
        seen.add(fold)
        result.append(clean)
    return result, warnings


# ─────────────────────────────────────────────────────────────────────────
# Datei-Zugriff (Lesen, Etag, atomarer Write)
# ─────────────────────────────────────────────────────────────────────────


def _mapping_path(mapping_id: str, mapping_dir: Path) -> Path:
    descriptor = _MAPPING_DESCRIPTORS.get(mapping_id)
    if descriptor is None:
        raise MappingUnknownIdError(f"Unbekannte mapping_id: {mapping_id!r}")
    return Path(mapping_dir) / descriptor["filename"]


def _load_channel_map(mapping_dir: Path) -> Dict[str, dict]:
    """Rohdaten aus channel_genre.yaml. Wirft MappingUnavailableError bei
    fehlender oder korrupter Datei."""
    import yaml

    path = _mapping_path(MAPPING_ID_CHANNEL_GENRE, mapping_dir)
    if not path.exists():
        raise MappingUnavailableError(f"{path} existiert nicht.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as e:
        raise MappingUnavailableError(f"{path} konnte nicht gelesen werden: {e!r}") from e

    raw_map = data.get(MAPPING_ROOT_KEY_CHANNEL_GENRE, data) or {}
    if not isinstance(raw_map, dict):
        raise MappingUnavailableError(
            f"{path}: '{MAPPING_ROOT_KEY_CHANNEL_GENRE}' ist kein Dict."
        )
    return raw_map


def _find_mapping_key(mapping: Dict[str, dict], channel: str) -> Optional[str]:
    """Tatsächlicher (ggf. gemischt geschriebener) Key eines Channels —
    casefold-Lookup wie in library_repair/genre.py."""
    wanted = channel.casefold()
    for k in mapping:
        if isinstance(k, str) and k.casefold() == wanted:
            return k
    return None


def _entry_from_raw(key: str, raw: object) -> Optional[ChannelGenreEntry]:
    if not isinstance(raw, dict):
        return None
    primary = (raw.get("primary") or "").strip()
    secondary = raw.get("secondary") or []
    if not isinstance(secondary, list):
        secondary = []
    secondary_clean = [str(x).strip() for x in secondary if str(x).strip()]
    description = raw.get("description")
    if description is not None:
        description = str(description).strip() or None
    if not primary:
        return None
    return ChannelGenreEntry(
        key=key, primary=primary, secondary=secondary_clean, description=description,
    )


def _channel_mapping_etag(mapping: Dict[str, dict]) -> str:
    """Etag über den GESAMTEN Mapping-Stand (nicht nur einen Eintrag) —
    damit auch ein Create-Write gegen zwischenzeitliche Änderungen Dritter
    geschützt ist. Sortiert nach casefold-Key für deterministische Ausgabe."""
    items = []
    for k in sorted(mapping.keys(), key=lambda s: s.casefold() if isinstance(s, str) else ""):
        raw = mapping[k]
        if not isinstance(raw, dict):
            continue
        items.append([
            k,
            str(raw.get("primary", "")).strip(),
            [str(x).strip() for x in (raw.get("secondary") or []) if str(x).strip()],
            str(raw.get("description") or "").strip(),
        ])
    payload = json.dumps(items, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# Prozess-lokaler Write-Lock (Check-and-Write serialisieren). Der Bot-
# Prozess liest channel_genre.yaml nur — kein cross_process_lock nötig.
_WRITE_LOCK = threading.Lock()


def _dump_channel_map(mapping_dir: Path, mapping: Dict[str, dict]) -> None:
    import yaml

    path = _mapping_path(MAPPING_ID_CHANNEL_GENRE, mapping_dir)
    data = {MAPPING_ROOT_KEY_CHANNEL_GENRE: mapping}
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    tmp.replace(path)


# ─────────────────────────────────────────────────────────────────────────
# Öffentliche Funktionen (channel-genre)
# ─────────────────────────────────────────────────────────────────────────


def list_channel_genres(mapping_dir: Path) -> List[ChannelGenreEntry]:
    mapping = _load_channel_map(mapping_dir)
    result = []
    for k in sorted(mapping.keys(), key=lambda s: s.casefold() if isinstance(s, str) else ""):
        entry = _entry_from_raw(k, mapping[k])
        if entry is not None:
            result.append(entry)
    return result


def get_channel_genre(
    channel: str, mapping_dir: Path,
) -> Tuple[Optional[ChannelGenreEntry], str]:
    mapping = _load_channel_map(mapping_dir)
    key = _find_mapping_key(mapping, channel)
    etag = _channel_mapping_etag(mapping)
    if key is None:
        return None, etag
    return _entry_from_raw(key, mapping[key]), etag


def plan_channel_genre_update(
    channel: str,
    primary: str,
    secondary: List[str],
    description: Optional[str],
    mapping_dir: Path,
) -> ChannelGenrePlan:
    clean_channel = _validate_channel_name(channel)
    clean_primary = _validated_genre(primary, "Primary-Genre")
    clean_secondary, warnings = _validate_secondary_list(secondary, clean_primary)
    clean_description = _validate_description(description)

    mapping = _load_channel_map(mapping_dir)
    etag = _channel_mapping_etag(mapping)
    key = _find_mapping_key(mapping, clean_channel)

    if key is None:
        return ChannelGenrePlan(
            key=clean_channel.lower(),
            change="create",
            existing=None,
            primary=clean_primary,
            secondary=clean_secondary,
            description=clean_description,
            primary_changed=True,
            added=list(clean_secondary),
            removed=[],
            warnings=warnings,
            etag=etag,
        )

    existing = _entry_from_raw(key, mapping[key])
    if existing is None:
        # Rohdaten korrupt für diesen Key — als Create behandeln
        return ChannelGenrePlan(
            key=key,
            change="create",
            existing=None,
            primary=clean_primary,
            secondary=clean_secondary,
            description=clean_description,
            primary_changed=True,
            added=list(clean_secondary),
            removed=[],
            warnings=warnings,
            etag=etag,
        )

    primary_changed = existing.primary.strip() != clean_primary
    existing_secondary_fold = {g.casefold() for g in existing.secondary}
    new_secondary_fold = {g.casefold() for g in clean_secondary}
    added = [g for g in clean_secondary if g.casefold() not in existing_secondary_fold]
    removed = [g for g in existing.secondary if g.casefold() not in new_secondary_fold]

    no_change = (
        not primary_changed
        and not added
        and not removed
        and (existing.description or "") == (clean_description or "")
    )
    change = "unchanged" if no_change else "update"

    return ChannelGenrePlan(
        key=key,
        change=change,
        existing=existing,
        primary=clean_primary,
        secondary=clean_secondary,
        description=clean_description,
        primary_changed=primary_changed,
        added=added,
        removed=removed,
        warnings=warnings,
        etag=etag,
    )


def apply_channel_genre_update(
    channel: str,
    primary: str,
    secondary: List[str],
    description: Optional[str],
    mapping_dir: Path,
    expected_etag: str,
) -> Tuple[ChannelGenrePlan, ChannelGenreSaveResult]:
    """Atomarer Write. Prüft zuerst den Etag (409 bei Konflikt), führt dann
    den Write unter Prozess-Lock aus."""
    with _WRITE_LOCK:
        # Plan gegen den AKTUELLEN Stand — der Etag-Vergleich schützt vor
        # zwischenzeitlichen Änderungen (Create wie Update).
        plan = plan_channel_genre_update(channel, primary, secondary, description, mapping_dir)
        if plan.etag != expected_etag:
            raise MappingConflictError(
                "Der Mapping-Stand wurde seit der Vorschau geändert. "
                "Bitte neu laden und erneut prüfen."
            )

        mapping = _load_channel_map(mapping_dir)
        key = _find_mapping_key(mapping, plan.key) or plan.key.lower()

        new_entry = {
            "primary": plan.primary,
            "secondary": list(plan.secondary),
            "description": plan.description,
        }

        if plan.change == "unchanged":
            return plan, ChannelGenreSaveResult(
                written=False, unchanged=True, key=key,
                primary=plan.primary, secondary=list(plan.secondary),
                new_etag=plan.etag,
            )

        mapping[key] = new_entry
        _dump_channel_map(mapping_dir, mapping)
        new_etag = _channel_mapping_etag(_load_channel_map(mapping_dir))
        return plan, ChannelGenreSaveResult(
            written=True, unchanged=False, key=key,
            primary=plan.primary, secondary=list(plan.secondary),
            new_etag=new_etag,
        )
