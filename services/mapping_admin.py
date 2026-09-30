# services/mapping_admin.py
# -*- coding: utf-8 -*-
"""
Mapping-Administration — Application-Layer (M2, 2026-09-29).

Generische Verwaltung schreibbarer Mapping-Dateien aus dem Control Center.

Unterstuetzte Mapping-Typen:
  channel-genre  channel_genre.yaml   key -> {primary, secondary, description}
  genre-alias    genre_aliases.yaml   alias -> canonical genre

Design (siehe docs/audits/MAPPING_ADMIN_CHARACTERIZATION_AND_PROPOSAL_2026-09-29.md):
  - Mapping-ID-Allowlist; keine Dateipfade aus dem Client.
  - MappingDescriptor pro Mapping (id, filename, root_key, kind).
  - Kind-Logik in privaten Helfern (kein Framework); Dispatch ueber descriptor.kind.
  - Etag ueber den gesamten Mapping-Stand (Create wie Update geschuetzt).
  - Atomarer Write (tmp + replace), Prozess-Write-Lock.
  - Kommentarverlust: yaml.safe_dump entfernt Kommentarzeilen. Die API-Antwort
    traegt einen entsprechenden Warnhinweis; dieses Modul loggt nichts.

M1-Kompatibilitaet: list_channel_genres / get_channel_genre /
plan_channel_genre_update / apply_channel_genre_update bleiben als duenne
Shims auf die generische API erhalten.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.library_repair.genre import (
    GenreDomainError,
    validate_genre_name as _validate_genre_name_domain,
)
from services import mapping_backups
from utils.atomic_file import atomic_write_text as _atomic_write_text
from utils.file_lock import cross_process_lock


# ─────────────────────────────────────────────────────────────────────────
# Descriptor / Allowlist
# ─────────────────────────────────────────────────────────────────────────

MAPPING_ID_CHANNEL_GENRE = "channel-genre"
MAPPING_ID_GENRE_ALIASES = "genre-aliases"

# M1-Kompatibilitaets-Konstanten (von bestehenden Tests referenziert)
MAPPING_FILENAME_CHANNEL_GENRE = "channel_genre.yaml"
MAPPING_ROOT_KEY_CHANNEL_GENRE = "CHANNEL_GENRE_MAP"
MAPPING_FILENAME_GENRE_ALIASES = "genre_aliases.yaml"
MAPPING_ROOT_KEY_GENRE_ALIASES = "GENRE_ALIASES"
MAPPING_ID_GENRE_OVERRIDES = "genre-overrides"
MAPPING_FILENAME_GENRE_OVERRIDES = "genre_overrides.yaml"
MAPPING_ROOT_KEY_GENRE_OVERRIDES = "GENRE_OVERRIDES"
MAPPING_ID_GENRE_FILTERS = "genre-filters"
MAPPING_FILENAME_GENRE_FILTERS = "genre_filters.yaml"
MAPPING_ROOT_KEY_GENRE_FILTERS = "IGNORE_SECONDARY"
MAPPING_ID_SPECIAL_CHANNELS = "special-channels"
MAPPING_FILENAME_SPECIAL_CHANNELS = "special_channel.yaml"
MAPPING_ROOT_KEY_SPECIAL_CHANNELS = "SPECIAL_CHANNELS"
MAPPING_ID_GENRE_HIERARCHY = "genre-hierarchy"
MAPPING_FILENAME_GENRE_HIERARCHY = "genre_hierarchy.yaml"
MAPPING_ROOT_KEY_GENRE_HIERARCHY = "GENRE_HIERARCHY"


@dataclass(frozen=True)
class MappingDescriptor:
    mapping_id: str
    filename: str
    root_key: str
    kind: str
    lookup_exact_first: bool = False


_MAPPING_DESCRIPTORS: Dict[str, MappingDescriptor] = {
    MAPPING_ID_CHANNEL_GENRE: MappingDescriptor(
        mapping_id=MAPPING_ID_CHANNEL_GENRE,
        filename="channel_genre.yaml",
        root_key="CHANNEL_GENRE_MAP",
        kind="channel-genre",
    ),
    MAPPING_ID_GENRE_ALIASES: MappingDescriptor(
        mapping_id=MAPPING_ID_GENRE_ALIASES,
        filename="genre_aliases.yaml",
        root_key="GENRE_ALIASES",
        kind="genre-alias",
    ),
    MAPPING_ID_GENRE_OVERRIDES: MappingDescriptor(
        mapping_id=MAPPING_ID_GENRE_OVERRIDES,
        filename="genre_overrides.yaml",
        root_key="GENRE_OVERRIDES",
        kind="genre-override",
        lookup_exact_first=True,
    ),
    MAPPING_ID_GENRE_FILTERS: MappingDescriptor(
        mapping_id=MAPPING_ID_GENRE_FILTERS,
        filename=MAPPING_FILENAME_GENRE_FILTERS,
        root_key=MAPPING_ROOT_KEY_GENRE_FILTERS,
        kind="genre-filter",
    ),
    MAPPING_ID_SPECIAL_CHANNELS: MappingDescriptor(
        mapping_id=MAPPING_ID_SPECIAL_CHANNELS,
        filename=MAPPING_FILENAME_SPECIAL_CHANNELS,
        root_key=MAPPING_ROOT_KEY_SPECIAL_CHANNELS,
        kind="special-channel",
    ),
    # Baum (Kind -> Eltern|null), Logik und zeilenweiser Writer in
    # services/mapping_hierarchy.py.
    MAPPING_ID_GENRE_HIERARCHY: MappingDescriptor(
        mapping_id=MAPPING_ID_GENRE_HIERARCHY,
        filename=MAPPING_FILENAME_GENRE_HIERARCHY,
        root_key=MAPPING_ROOT_KEY_GENRE_HIERARCHY,
        kind="genre-hierarchy",
    ),
}


def _get_descriptor(mapping_id: str) -> MappingDescriptor:
    descriptor = _MAPPING_DESCRIPTORS.get(mapping_id)
    if descriptor is None:
        raise MappingUnknownIdError(f"Unbekannte mapping_id: {mapping_id!r}")
    return descriptor


# ─────────────────────────────────────────────────────────────────────────
# Fehlerklassen
# ─────────────────────────────────────────────────────────────────────────


class MappingDomainError(Exception):
    """Basisklasse fuer alle Fehler dieses Moduls."""


class MappingUnavailableError(MappingDomainError):
    """Mapping-Datei fehlt oder ist nicht lesbar/korrupt."""


class MappingConflictError(MappingDomainError):
    """Mapping-Stand wurde seit der Vorschau geaendert (veralteter Etag)."""


class MappingInvalidInputError(MappingDomainError):
    """Eingabewert ungueltig."""


class MappingUnknownIdError(MappingDomainError):
    """mapping_id nicht in der Allowlist."""


class MappingBackupError(MappingDomainError):
    """Vor dem Schreiben konnte kein Backup angelegt werden — es wurde nichts geschrieben."""


class MappingBackupNotFoundError(MappingDomainError):
    """Angeforderte Version existiert nicht."""


# ─────────────────────────────────────────────────────────────────────────
# Validierung
# ─────────────────────────────────────────────────────────────────────────

MAX_CHANNEL_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 500
MAX_SECONDARY_ENTRIES = 20
MAX_GENRE_ALIAS_KEY_LENGTH = 200
MAX_GENRE_FILTER_VALUE_LENGTH = 100
MAX_SPECIAL_CATEGORY_NAME_LENGTH = 100
MAX_SPECIAL_CHANNEL_NAME_LENGTH = 200

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _validated_genre(value: object, label: str) -> str:
    """Ruft den bestehenden Domain-Validator und wandelt GenreDomainError
    in MappingInvalidInputError (API-Schicht)."""
    try:
        return _validate_genre_name_domain(value, label)
    except GenreDomainError as e:
        raise MappingInvalidInputError(str(e)) from e


def _validate_channel_name(value: object) -> str:
    if value is None:
        raise MappingInvalidInputError("Channel-Name darf nicht leer sein.")
    if not isinstance(value, str):
        raise MappingInvalidInputError("Channel-Name muss ein Text sein.")
    if "\n" in value or "\r" in value:
        raise MappingInvalidInputError("Channel-Name darf keine Zeilenumbrueche enthalten.")
    trimmed = value.strip()
    if not trimmed:
        raise MappingInvalidInputError("Channel-Name darf nicht leer sein.")
    if len(trimmed) > MAX_CHANNEL_LENGTH:
        raise MappingInvalidInputError(
            f"Channel-Name zu lang (max. {MAX_CHANNEL_LENGTH} Zeichen)."
        )
    if _CONTROL_CHARS.search(trimmed):
        raise MappingInvalidInputError("Channel-Name enthaelt Steuerzeichen.")
    return trimmed


def _validate_description(value: object) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MappingInvalidInputError("Beschreibung muss ein Text sein.")
    if "\n" in value or "\r" in value:
        raise MappingInvalidInputError("Beschreibung darf keine Zeilenumbrueche enthalten.")
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) > MAX_DESCRIPTION_LENGTH:
        raise MappingInvalidInputError(
            f"Beschreibung zu lang (max. {MAX_DESCRIPTION_LENGTH} Zeichen)."
        )
    if _CONTROL_CHARS.search(trimmed):
        raise MappingInvalidInputError("Beschreibung enthaelt Steuerzeichen.")
    return trimmed


def _validate_secondary_list(raw: object, primary: str) -> Tuple[List[str], List[str]]:
    warnings: List[str] = []
    if raw is None:
        return [], warnings
    if not isinstance(raw, (list, tuple)):
        raise MappingInvalidInputError("Secondary-Genres muessen eine Liste sein.")
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


def _validate_alias_key(value: object) -> str:
    """Alias-Namen haben dieselben Regeln wie Genre-Namen (kein Newline,
    keine Steuerzeichen, nicht leer), plus das 200-Zeichen-Limit."""
    if value is None:
        raise MappingInvalidInputError("Alias darf nicht leer sein.")
    if not isinstance(value, str):
        raise MappingInvalidInputError("Alias muss ein Text sein.")
    if "\n" in value or "\r" in value:
        raise MappingInvalidInputError("Alias darf keine Zeilenumbrueche enthalten.")
    trimmed = value.strip()
    if not trimmed:
        raise MappingInvalidInputError("Alias darf nicht leer sein.")
    if len(trimmed) > MAX_GENRE_ALIAS_KEY_LENGTH:
        raise MappingInvalidInputError(
            f"Alias zu lang (max. {MAX_GENRE_ALIAS_KEY_LENGTH} Zeichen)."
        )
    if _CONTROL_CHARS.search(trimmed):
        raise MappingInvalidInputError("Alias enthaelt Steuerzeichen.")
    return trimmed


def _normalize_filter_list(
    raw_values: object, *, strict: bool,
) -> Tuple[List[str], List[str]]:
    """strip -> lower -> casefold-dedupe (erste Occurrence gewinnt).
    Reihenfolge bleibt erhalten. strict=True (User-Input): 422 bei
    leerem/Nicht-Text/zu lang/Steuerzeichen. strict=False (Datei-Input):
    ueberspringt solche Werte mit einer Warnung."""
    if raw_values is None:
        return [], []
    if not isinstance(raw_values, (list, tuple)):
        if strict:
            raise MappingInvalidInputError("Filter-Liste muss eine Liste sein.")
        return [], ["Filter-Liste war keine Liste; keine Filter geladen."]
    warnings: List[str] = []
    seen: set = set()
    result: List[str] = []
    skipped_non_string = 0
    skipped_empty = 0
    skipped_too_long = 0
    skipped_control = 0
    duplicate_count = 0
    for item in raw_values:
        if not isinstance(item, str):
            if strict:
                raise MappingInvalidInputError("Filter-Wert muss ein Text sein.")
            skipped_non_string += 1
            continue
        if "\n" in item or "\r" in item:
            if strict:
                raise MappingInvalidInputError("Filter-Wert darf keine Zeilenumbrueche enthalten.")
            skipped_control += 1
            continue
        trimmed = item.strip()
        if not trimmed:
            if strict:
                raise MappingInvalidInputError("Filter-Wert darf nicht leer sein.")
            skipped_empty += 1
            continue
        if len(trimmed) > MAX_GENRE_FILTER_VALUE_LENGTH:
            if strict:
                raise MappingInvalidInputError(
                    f"Filter-Wert zu lang (max. {MAX_GENRE_FILTER_VALUE_LENGTH} Zeichen)."
                )
            skipped_too_long += 1
            continue
        if _CONTROL_CHARS.search(trimmed):
            if strict:
                raise MappingInvalidInputError("Filter-Wert enthaelt Steuerzeichen.")
            skipped_control += 1
            continue
        clean = trimmed.lower()
        fold = clean.casefold()
        if fold in seen:
            duplicate_count += 1
            continue
        seen.add(fold)
        result.append(clean)
    if skipped_non_string:
        warnings.append(f"{skipped_non_string} Nicht-Text-Werte uebersprungen.")
    if skipped_empty:
        warnings.append(f"{skipped_empty} leere Werte uebersprungen.")
    if skipped_too_long:
        warnings.append(f"{skipped_too_long} zu lange Werte uebersprungen.")
    if skipped_control:
        warnings.append(f"{skipped_control} Werte mit Steuerzeichen uebersprungen.")
    if duplicate_count:
        warnings.append(f"{duplicate_count} casefold-Duplikate zusammengefuehrt.")
    return result, warnings


def _validate_special_category_name(value: object) -> str:
    if value is None or not isinstance(value, str):
        raise MappingInvalidInputError("Kategorie-Name muss ein Text sein.")
    if "\n" in value or "\r" in value:
        raise MappingInvalidInputError("Kategorie-Name darf keine Zeilenumbrueche enthalten.")
    trimmed = value.strip()
    if not trimmed:
        raise MappingInvalidInputError("Kategorie-Name darf nicht leer sein.")
    if len(trimmed) > MAX_SPECIAL_CATEGORY_NAME_LENGTH:
        raise MappingInvalidInputError(
            f"Kategorie-Name zu lang (max. {MAX_SPECIAL_CATEGORY_NAME_LENGTH} Zeichen)."
        )
    if _CONTROL_CHARS.search(trimmed):
        raise MappingInvalidInputError("Kategorie-Name enthaelt Steuerzeichen.")
    return trimmed


def _validate_special_channel_name(value: object) -> str:
    if value is None or not isinstance(value, str):
        raise MappingInvalidInputError("Kanalname muss ein Text sein.")
    if "\n" in value or "\r" in value:
        raise MappingInvalidInputError("Kanalname darf keine Zeilenumbrueche enthalten.")
    trimmed = value.strip()
    if not trimmed:
        raise MappingInvalidInputError("Kanalname darf nicht leer sein.")
    if len(trimmed) > MAX_SPECIAL_CHANNEL_NAME_LENGTH:
        raise MappingInvalidInputError(
            f"Kanalname zu lang (max. {MAX_SPECIAL_CHANNEL_NAME_LENGTH} Zeichen)."
        )
    if _CONTROL_CHARS.search(trimmed):
        raise MappingInvalidInputError("Kanalname enthaelt Steuerzeichen.")
    return trimmed


def _normalize_special_categories(
    raw_categories: object, *, strict: bool,
) -> Tuple[List[SpecialChannelCategory], List[str]]:
    """Kategorien in Reihenfolge, Kanalnamen in Reihenfolge, Case bleibt
    erhalten. strict=True: 422 bei strukturellen Fehlern. strict=False:
    ueberspringt unsauberes mit Warnung (fuer die Datei-Sicht)."""
    warnings: List[str] = []
    if raw_categories is None:
        return [], warnings
    if not isinstance(raw_categories, (list, tuple)):
        if strict:
            raise MappingInvalidInputError("Kategorien muessen eine Liste sein.")
        return [], ["Kategorien-Struktur war keine Liste; nichts geladen."]

    seen_cat_names: set = set()
    result: List[SpecialChannelCategory] = []
    category_collision = 0
    category_empty = 0
    for cat in raw_categories:
        if not isinstance(cat, dict):
            if strict:
                raise MappingInvalidInputError("Jede Kategorie muss ein Objekt sein.")
            continue
        name_raw = cat.get("name")
        try:
            name = _validate_special_category_name(name_raw)
        except MappingInvalidInputError:
            if strict:
                raise
            continue
        name_fold = name.casefold()
        if name_fold in seen_cat_names:
            if strict:
                raise MappingInvalidInputError(
                    f"Kategorie {name!r} kollidiert case-insensitiv mit einer anderen."
                )
            category_collision += 1
            continue
        channels_raw = cat.get("channels")
        if channels_raw is None:
            channels_raw = []
        if not isinstance(channels_raw, (list, tuple)):
            if strict:
                raise MappingInvalidInputError(
                    f"Kategorie {name!r}: channels muss eine Liste sein."
                )
            continue
        if strict and not channels_raw:
            raise MappingInvalidInputError(
                f"Kategorie {name!r} ist leer — leere Kategorien sind nicht erlaubt."
            )
        seen_channels: set = set()
        clean_channels: List[str] = []
        channel_dupes = 0
        for ch in channels_raw:
            try:
                ch_clean = _validate_special_channel_name(ch)
            except MappingInvalidInputError:
                if strict:
                    raise
                continue
            ch_fold = ch_clean.casefold()
            if ch_fold in seen_channels:
                channel_dupes += 1
                continue
            seen_channels.add(ch_fold)
            clean_channels.append(ch_clean)
        if not clean_channels and not strict:
            category_empty += 1
            continue
        if channel_dupes:
            warnings.append(
                f"Kategorie {name!r}: {channel_dupes} casefold-Duplikate zusammengefuehrt."
            )
        seen_cat_names.add(name_fold)
        result.append(SpecialChannelCategory(name=name, channels=clean_channels))

    if category_collision:
        warnings.append(f"{category_collision} Kategorien mit casefold-Kollision uebersprungen.")
    if category_empty:
        warnings.append(f"{category_empty} leere Kategorien uebersprungen.")

    # Cross-Kategorie-Warnung
    seen_channel_cat: Dict[str, str] = {}
    for cat in result:
        for ch in cat.channels:
            key = ch.casefold()
            if key in seen_channel_cat:
                warnings.append(
                    f"Kanal {ch!r} kommt in {seen_channel_cat[key]!r} und "
                    f"{cat.name!r} vor — {seen_channel_cat[key]!r} gewinnt wegen Prioritaet."
                )
            else:
                seen_channel_cat[key] = cat.name
    return result, warnings


# ─────────────────────────────────────────────────────────────────────────
# Dataclasses (kind-spezifisch)
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChannelGenreEntry:
    key: str
    primary: str
    secondary: List[str]
    description: Optional[str]


@dataclass(frozen=True)
class ChannelGenrePlan:
    mapping_id: str
    key: str
    change: str
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


@dataclass(frozen=True)
class GenreAliasEntry:
    key: str
    canonical: str


@dataclass(frozen=True)
class GenreAliasPlan:
    mapping_id: str
    key: str
    change: str
    existing: Optional[GenreAliasEntry]
    canonical: str
    canonical_changed: bool
    warnings: List[str]
    etag: str


@dataclass(frozen=True)
class GenreAliasSaveResult:
    written: bool
    unchanged: bool
    key: str
    canonical: str
    new_etag: str


@dataclass(frozen=True)
class GenreOverrideEntry:
    key: str
    override: str


@dataclass(frozen=True)
class GenreOverridePlan:
    mapping_id: str
    key: str
    change: str
    existing: Optional[GenreOverrideEntry]
    override: str
    override_changed: bool
    warnings: List[str]
    etag: str


@dataclass(frozen=True)
class GenreOverrideSaveResult:
    written: bool
    unchanged: bool
    key: str
    override: str
    new_etag: str


@dataclass(frozen=True)
class GenreFilterPlan:
    mapping_id: str
    change: str  # "update" | "cleanup" | "unchanged" (kein "create")
    added: List[str]
    removed: List[str]
    values: List[str]
    warnings: List[str]
    etag: str


@dataclass(frozen=True)
class GenreFilterSaveResult:
    written: bool
    unchanged: bool
    values: List[str]
    new_etag: str


@dataclass(frozen=True)
class SpecialChannelCategory:
    name: str
    channels: List[str]


@dataclass(frozen=True)
class SpecialChannelPlan:
    mapping_id: str
    change: str  # "update" | "cleanup" | "unchanged"
    categories: List[SpecialChannelCategory]
    added: List[str]
    removed: List[str]
    warnings: List[str]
    etag: str
    # Text "alt -> neu", wenn sich nur die Kategorie-Reihenfolge (= Prioritaet) aendert.
    order_change: Optional[str] = None


@dataclass(frozen=True)
class SpecialChannelSaveResult:
    written: bool
    unchanged: bool
    categories: List[SpecialChannelCategory]
    new_etag: str


# ─────────────────────────────────────────────────────────────────────────
# Datei-Zugriff
# ─────────────────────────────────────────────────────────────────────────


def _mapping_path(descriptor: MappingDescriptor, mapping_dir: Path) -> Path:
    return Path(mapping_dir) / descriptor.filename


def _load_raw_mapping(descriptor: MappingDescriptor, mapping_dir: Path) -> Dict[str, Any]:
    import yaml

    path = _mapping_path(descriptor, mapping_dir)
    if not path.exists():
        raise MappingUnavailableError(f"{path} existiert nicht.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as e:
        raise MappingUnavailableError(f"{path} konnte nicht gelesen werden: {e!r}") from e

    raw = data.get(descriptor.root_key, data) or {}
    if not isinstance(raw, dict):
        raise MappingUnavailableError(
            f"{path}: '{descriptor.root_key}' ist kein Dict."
        )
    return raw


def _find_mapping_key(
    mapping: Dict[str, Any], key: str, descriptor: MappingDescriptor,
) -> Optional[str]:
    """Exakter Treffer zuerst (nur wenn descriptor.lookup_exact_first gesetzt),
    danach casefold-Fallback. Bei genre-override bleiben case-sensitive
    Schreibweisen ('Hip-Hop' neben 'hip-hop') erhalten."""
    if descriptor.lookup_exact_first and key in mapping:
        return key
    wanted = key.casefold()
    for k in mapping:
        if isinstance(k, str) and k.casefold() == wanted:
            return k
    return None


_WRITE_LOCK = threading.Lock()

def _snapshot_before_write(
    descriptor: "MappingDescriptor", mapping_dir: Path, backup_dir: Optional[Path],
) -> None:
    """Legt die bisherige Datei als Version ab, bevor sie ueberschrieben wird.
    Ohne `backup_dir` (interne Aufrufer/Tests) entfaellt das; mit `backup_dir`
    bricht ein Backup-Fehler den Write ab, damit nie ohne Rueckweg geschrieben wird."""
    if backup_dir is None:
        return
    try:
        mapping_backups.snapshot(backup_dir, descriptor.mapping_id, _mapping_path(descriptor, mapping_dir))
    except OSError as e:
        raise MappingBackupError(
            "Backup konnte nicht angelegt werden — es wurde nichts geschrieben."
        ) from e


@contextmanager
def _write_guard(descriptor: "MappingDescriptor", mapping_dir: Path):
    """Serialisiert Read-Modify-Write auf einer Mapping-Datei: Thread-Lock
    (dieser Prozess) plus Datei-Lock (`fcntl.flock`, Bot- und Control-Center-
    Prozess). Ohne den Datei-Lock koennten zwei Prozesse denselben Stand lesen
    und sich gegenseitig ueberschreiben."""
    with _WRITE_LOCK, cross_process_lock(_mapping_path(descriptor, mapping_dir)):
        yield


def _dump_raw_mapping(
    descriptor: MappingDescriptor, mapping_dir: Path, mapping: Dict[str, Any],
) -> None:
    import yaml

    path = _mapping_path(descriptor, mapping_dir)
    data = {descriptor.root_key: mapping}
    _atomic_write_text(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def _load_raw_list(
    descriptor: MappingDescriptor, mapping_dir: Path,
) -> List[object]:
    """Rohliste aus dem Root-Key (z.B. IGNORE_SECONDARY)."""
    import yaml

    path = _mapping_path(descriptor, mapping_dir)
    if not path.exists():
        raise MappingUnavailableError(f"{path} existiert nicht.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as e:
        raise MappingUnavailableError(f"{path} konnte nicht gelesen werden: {e!r}") from e
    raw = data.get(descriptor.root_key, data) or []
    if not isinstance(raw, list):
        raise MappingUnavailableError(
            f"{path}: '{descriptor.root_key}' ist keine Liste."
        )
    return list(raw)


def _dump_raw_list(
    descriptor: MappingDescriptor, mapping_dir: Path, values: List[str],
) -> None:
    import yaml

    path = _mapping_path(descriptor, mapping_dir)
    data = {descriptor.root_key: list(values)}
    _atomic_write_text(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


# ─────────────────────────────────────────────────────────────────────────
# Etags
# ─────────────────────────────────────────────────────────────────────────


def _etag_of(items: list) -> str:
    payload = json.dumps(items, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _channel_genre_etag(mapping: Dict[str, Any]) -> str:
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
    return _etag_of(items)


def _genre_alias_etag(mapping: Dict[str, Any]) -> str:
    items = []
    for k in sorted(mapping.keys(), key=lambda s: s.casefold() if isinstance(s, str) else ""):
        v = mapping[k]
        if not isinstance(v, str):
            continue
        items.append([k.casefold() if isinstance(k, str) else k, str(v).strip()])
    return _etag_of(items)


def _genre_override_etag(mapping: Dict[str, Any]) -> str:
    """Sortiert nach casefold (deterministisch), hasht aber die ROHEN Keys —
    'Hip-Hop' und 'hip-hop' bleiben zwei verschiedene Eintraege."""
    items = []
    for k in sorted(mapping.keys(), key=lambda s: s.casefold() if isinstance(s, str) else ""):
        v = mapping[k]
        if not isinstance(v, str):
            continue
        items.append([str(k), str(v).strip()])
    return _etag_of(items)


def _genre_filter_etag(values: List[str]) -> str:
    """Etag ueber die normierte Liste IN REIHENFOLGE — M4 bewusst anders
    als die key-basierten M2/M3-Etats. ["rock","indie"] != ["indie","rock"]."""
    payload = json.dumps(list(values), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _compute_etag(descriptor: MappingDescriptor, mapping: Dict[str, Any]) -> str:
    if descriptor.kind == "channel-genre":
        return _channel_genre_etag(mapping)
    if descriptor.kind == "genre-alias":
        return _genre_alias_etag(mapping)
    if descriptor.kind == "genre-override":
        return _genre_override_etag(mapping)
    raise MappingUnknownIdError(f"Unbekannter kind: {descriptor.kind!r}")


# ─────────────────────────────────────────────────────────────────────────
# Entry-Parser (kind-spezifisch)
# ─────────────────────────────────────────────────────────────────────────


def _parse_channel_genre_entry(key: str, raw: Any) -> Optional[ChannelGenreEntry]:
    if not isinstance(raw, dict):
        return None
    primary = (raw.get("primary") or "").strip()
    if not primary:
        return None
    secondary = raw.get("secondary") or []
    if not isinstance(secondary, list):
        secondary = []
    secondary_clean = [str(x).strip() for x in secondary if str(x).strip()]
    description = raw.get("description")
    if description is not None:
        description = str(description).strip() or None
    return ChannelGenreEntry(
        key=key, primary=primary, secondary=secondary_clean, description=description,
    )


def _parse_genre_alias_entry(key: str, raw: Any) -> Optional[GenreAliasEntry]:
    if not isinstance(raw, str):
        return None
    canonical = raw.strip()
    if not canonical:
        return None
    return GenreAliasEntry(key=key, canonical=canonical)


def _parse_genre_override_entry(key: str, raw: Any) -> Optional[GenreOverrideEntry]:
    if not isinstance(raw, str):
        return None
    override = raw.strip()
    if not override:
        return None
    return GenreOverrideEntry(key=key, override=override)


def _load_raw_special_categories(descriptor: MappingDescriptor, mapping_dir: Path) -> Dict[str, List[object]]:
    """Rohdaten als geordnetes dict {Kategorie: [Kanaele]}. Wirft
    MappingUnavailableError bei fehlender/korrupter Datei."""
    import yaml

    path = _mapping_path(descriptor, mapping_dir)
    if not path.exists():
        raise MappingUnavailableError(f"{path} existiert nicht.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as e:
        raise MappingUnavailableError(f"{path} konnte nicht gelesen werden: {e!r}") from e
    raw = data.get(descriptor.root_key, data) or {}
    if not isinstance(raw, dict):
        raise MappingUnavailableError(
            f"{path}: '{descriptor.root_key}' ist kein Dict."
        )
    return raw


def _dump_special_categories(
    descriptor: MappingDescriptor,
    mapping_dir: Path,
    categories: List[SpecialChannelCategory],
) -> None:
    import yaml

    path = _mapping_path(descriptor, mapping_dir)
    # plain dict: Python 3.7+ behaelt Einfuegereihenfolge; yaml.safe_dump
    # kann OrderedDict nicht serialisieren.
    payload = {c.name: list(c.channels) for c in categories}
    data = {descriptor.root_key: payload}
    _atomic_write_text(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def _special_channels_etag(categories: List[SpecialChannelCategory]) -> str:
    """Etag: Kategorien in Reihenfolge, Kanaele pro Kategorie sortiert."""
    payload = [
        [c.name, sorted(c.channels, key=lambda s: s.casefold())]
        for c in categories
    ]
    data = json.dumps(payload, ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────
# Generische Public API
# ─────────────────────────────────────────────────────────────────────────


def list_mapping(mapping_id: str, mapping_dir: Path) -> List[Any]:
    descriptor = _get_descriptor(mapping_id)
    mapping = _load_raw_mapping(descriptor, mapping_dir)
    if descriptor.kind == "channel-genre":
        parser = _parse_channel_genre_entry
    elif descriptor.kind == "genre-alias":
        parser = _parse_genre_alias_entry
    elif descriptor.kind == "genre-override":
        parser = _parse_genre_override_entry
    else:
        raise MappingUnknownIdError(f"Unbekannter kind: {descriptor.kind!r}")
    result = []
    for k in sorted(mapping.keys(), key=lambda s: s.casefold() if isinstance(s, str) else ""):
        entry = parser(k, mapping[k])
        if entry is not None:
            result.append(entry)
    return result


def get_mapping_entry(
    mapping_id: str, key: str, mapping_dir: Path,
) -> Tuple[Optional[Any], str]:
    descriptor = _get_descriptor(mapping_id)
    mapping = _load_raw_mapping(descriptor, mapping_dir)
    etag = _compute_etag(descriptor, mapping)
    actual_key = _find_mapping_key(mapping, key, descriptor)
    if actual_key is None:
        return None, etag
    if descriptor.kind == "channel-genre":
        parser = _parse_channel_genre_entry
    elif descriptor.kind == "genre-alias":
        parser = _parse_genre_alias_entry
    elif descriptor.kind == "genre-override":
        parser = _parse_genre_override_entry
    else:
        raise MappingUnknownIdError(f"Unbekannter kind: {descriptor.kind!r}")
    return parser(actual_key, mapping[actual_key]), etag


def plan_mapping_update(
    mapping_id: str, key: str, payload: Dict[str, Any], mapping_dir: Path,
) -> Any:
    descriptor = _get_descriptor(mapping_id)
    if descriptor.kind == "channel-genre":
        return _plan_channel_genre(key, payload, descriptor, mapping_dir)
    if descriptor.kind == "genre-alias":
        return _plan_genre_alias(key, payload, descriptor, mapping_dir)
    if descriptor.kind == "genre-override":
        return _plan_genre_override(key, payload, descriptor, mapping_dir)
    raise MappingUnknownIdError(f"Unbekannter kind: {descriptor.kind!r}")


def apply_mapping_update(
    mapping_id: str, key: str, payload: Dict[str, Any], mapping_dir: Path,
    expected_etag: str, *, backup_dir: Optional[Path] = None,
) -> Tuple[Any, Any]:
    descriptor = _get_descriptor(mapping_id)
    with _write_guard(descriptor, mapping_dir):
        plan = plan_mapping_update(mapping_id, key, payload, mapping_dir)
        if plan.etag != expected_etag:
            raise MappingConflictError(
                "Der Mapping-Stand wurde seit der Vorschau geaendert. "
                "Bitte neu laden und erneut pruefen."
            )
        mapping = _load_raw_mapping(descriptor, mapping_dir)

        if plan.change == "unchanged":
            return plan, _unchanged_result(descriptor, plan)

        actual_key = _find_mapping_key(mapping, plan.key, descriptor) or plan.key
        _snapshot_before_write(descriptor, mapping_dir, backup_dir)
        if descriptor.kind == "channel-genre":
            mapping[actual_key] = {
                "primary": plan.primary,
                "secondary": list(plan.secondary),
                "description": plan.description,
            }
        elif descriptor.kind == "genre-alias":
            mapping[actual_key] = plan.canonical
        elif descriptor.kind == "genre-override":
            mapping[actual_key] = plan.override
        else:
            raise MappingUnknownIdError(f"Unbekannter kind: {descriptor.kind!r}")

        _dump_raw_mapping(descriptor, mapping_dir, mapping)
        new_etag = _compute_etag(descriptor, _load_raw_mapping(descriptor, mapping_dir))
        return plan, _written_result(descriptor, plan, actual_key, new_etag)


def _unchanged_result(descriptor: MappingDescriptor, plan: Any) -> Any:
    if descriptor.kind == "channel-genre":
        return ChannelGenreSaveResult(
            written=False, unchanged=True, key=plan.key,
            primary=plan.primary, secondary=list(plan.secondary),
            new_etag=plan.etag,
        )
    if descriptor.kind == "genre-alias":
        return GenreAliasSaveResult(
            written=False, unchanged=True, key=plan.key,
            canonical=plan.canonical, new_etag=plan.etag,
        )
    return GenreOverrideSaveResult(
        written=False, unchanged=True, key=plan.key,
        override=plan.override, new_etag=plan.etag,
    )


def _written_result(
    descriptor: MappingDescriptor, plan: Any, actual_key: str, new_etag: str,
) -> Any:
    if descriptor.kind == "channel-genre":
        return ChannelGenreSaveResult(
            written=True, unchanged=False, key=actual_key,
            primary=plan.primary, secondary=list(plan.secondary),
            new_etag=new_etag,
        )
    if descriptor.kind == "genre-alias":
        return GenreAliasSaveResult(
            written=True, unchanged=False, key=actual_key,
            canonical=plan.canonical, new_etag=new_etag,
        )
    return GenreOverrideSaveResult(
        written=True, unchanged=False, key=actual_key,
        override=plan.override, new_etag=new_etag,
    )


# ─────────────────────────────────────────────────────────────────────────
# Kind-spezifische Plan-Logik
# ─────────────────────────────────────────────────────────────────────────


def _plan_channel_genre(
    channel: str, payload: Dict[str, Any], descriptor: MappingDescriptor, mapping_dir: Path,
) -> ChannelGenrePlan:
    clean_channel = _validate_channel_name(channel)
    clean_primary = _validated_genre(payload.get("primary", ""), "Primary-Genre")
    clean_secondary, warnings = _validate_secondary_list(
        payload.get("secondary", []), clean_primary
    )
    clean_description = _validate_description(payload.get("description"))

    mapping = _load_raw_mapping(descriptor, mapping_dir)
    etag = _channel_genre_etag(mapping)
    actual_key = _find_mapping_key(mapping, clean_channel, descriptor)

    if actual_key is None:
        return ChannelGenrePlan(
            mapping_id=descriptor.mapping_id,
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

    existing = _parse_channel_genre_entry(actual_key, mapping[actual_key])
    if existing is None:
        return ChannelGenrePlan(
            mapping_id=descriptor.mapping_id,
            key=actual_key, change="create", existing=None,
            primary=clean_primary, secondary=clean_secondary,
            description=clean_description, primary_changed=True,
            added=list(clean_secondary), removed=[], warnings=warnings, etag=etag,
        )

    primary_changed = existing.primary.strip() != clean_primary
    existing_secondary_fold = {g.casefold() for g in existing.secondary}
    new_secondary_fold = {g.casefold() for g in clean_secondary}
    added = [g for g in clean_secondary if g.casefold() not in existing_secondary_fold]
    removed = [g for g in existing.secondary if g.casefold() not in new_secondary_fold]
    no_change = (
        not primary_changed and not added and not removed
        and (existing.description or "") == (clean_description or "")
    )
    return ChannelGenrePlan(
        mapping_id=descriptor.mapping_id,
        key=actual_key,
        change="unchanged" if no_change else "update",
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


def _plan_genre_alias(
    alias: str, payload: Dict[str, Any], descriptor: MappingDescriptor, mapping_dir: Path,
) -> GenreAliasPlan:
    clean_alias = _validate_alias_key(alias)
    clean_canonical = _validated_genre(payload.get("canonical", ""), "Canonical-Genre")

    mapping = _load_raw_mapping(descriptor, mapping_dir)
    etag = _genre_alias_etag(mapping)
    actual_key = _find_mapping_key(mapping, clean_alias, descriptor)

    if actual_key is None:
        return GenreAliasPlan(
            mapping_id=descriptor.mapping_id,
            key=clean_alias.lower(),
            change="create",
            existing=None,
            canonical=clean_canonical,
            canonical_changed=True,
            warnings=[],
            etag=etag,
        )

    existing = _parse_genre_alias_entry(actual_key, mapping[actual_key])
    if existing is None:
        return GenreAliasPlan(
            mapping_id=descriptor.mapping_id,
            key=actual_key, change="create", existing=None,
            canonical=clean_canonical, canonical_changed=True,
            warnings=[], etag=etag,
        )

    canonical_changed = existing.canonical.strip() != clean_canonical
    return GenreAliasPlan(
        mapping_id=descriptor.mapping_id,
        key=actual_key,
        change="update" if canonical_changed else "unchanged",
        existing=existing,
        canonical=clean_canonical,
        canonical_changed=canonical_changed,
        warnings=[],
        etag=etag,
    )


def _override_key_runtime_warnings(key: str) -> List[str]:
    """GenreMapper.normalize_genre_name() sucht mit strip().lower() im
    Override-Dict. Ein Key mit Grossbuchstaben wird gespeichert (exact-first),
    greift zur Laufzeit aber nie — das muss der Nutzer vor dem Speichern wissen."""
    runtime_key = key.strip().lower()
    if key == runtime_key:
        return []
    return [
        f"Der Key {key!r} greift zur Laufzeit nicht: die Genre-Pipeline sucht "
        f"Overrides kleingeschrieben. Wirksam waere {runtime_key!r}."
    ]


def _plan_genre_override(
    key: str, payload: Dict[str, Any], descriptor: MappingDescriptor, mapping_dir: Path,
) -> GenreOverridePlan:
    """Wie _plan_genre_alias, aber:
    - Original-Key-Case bleibt beim Create erhalten (kein lowercase).
    - Lookup laeuft ueber descriptor.lookup_exact_first=True (exakter Key
      zuerst, dann casefold-Fallback) — bestehende Schreibvarianten wie
      'Hip-Hop' und 'hip-hop' bleiben separat.
    """
    clean_key = _validate_alias_key(key)
    clean_override = _validated_genre(payload.get("override", ""), "Override-Genre")
    warnings = _override_key_runtime_warnings(clean_key)

    mapping = _load_raw_mapping(descriptor, mapping_dir)
    etag = _genre_override_etag(mapping)
    actual_key = _find_mapping_key(mapping, clean_key, descriptor)

    if actual_key is None:
        return GenreOverridePlan(
            mapping_id=descriptor.mapping_id,
            key=clean_key,
            change="create",
            existing=None,
            override=clean_override,
            override_changed=True,
            warnings=list(warnings),
            etag=etag,
        )

    warnings = _override_key_runtime_warnings(actual_key)
    existing = _parse_genre_override_entry(actual_key, mapping[actual_key])
    if existing is None:
        return GenreOverridePlan(
            mapping_id=descriptor.mapping_id,
            key=actual_key, change="create", existing=None,
            override=clean_override, override_changed=True,
            warnings=list(warnings), etag=etag,
        )

    override_changed = existing.override.strip() != clean_override
    return GenreOverridePlan(
        mapping_id=descriptor.mapping_id,
        key=actual_key,
        change="update" if override_changed else "unchanged",
        existing=existing,
        override=clean_override,
        override_changed=override_changed,
        warnings=list(warnings),
        etag=etag,
    )


# ─────────────────────────────────────────────────────────────────────────
# M1-Kompatibilitaets-Shims
# ─────────────────────────────────────────────────────────────────────────


def list_channel_genres(mapping_dir: Path) -> List[ChannelGenreEntry]:
    return list_mapping(MAPPING_ID_CHANNEL_GENRE, mapping_dir)


def get_channel_genre(
    channel: str, mapping_dir: Path,
) -> Tuple[Optional[ChannelGenreEntry], str]:
    return get_mapping_entry(MAPPING_ID_CHANNEL_GENRE, channel, mapping_dir)


def plan_channel_genre_update(
    channel: str,
    primary: str,
    secondary: List[str],
    description: Optional[str],
    mapping_dir: Path,
) -> ChannelGenrePlan:
    return plan_mapping_update(
        MAPPING_ID_CHANNEL_GENRE, channel,
        {"primary": primary, "secondary": secondary, "description": description},
        mapping_dir,
    )


def apply_channel_genre_update(
    channel: str,
    primary: str,
    secondary: List[str],
    description: Optional[str],
    mapping_dir: Path,
    expected_etag: str,
) -> Tuple[ChannelGenrePlan, ChannelGenreSaveResult]:
    return apply_mapping_update(
        MAPPING_ID_CHANNEL_GENRE, channel,
        {"primary": primary, "secondary": secondary, "description": description},
        mapping_dir, expected_etag,
    )


# ─────────────────────────────────────────────────────────────────────────
# Genre-Alias-Komfort-Shims (M2)
# ─────────────────────────────────────────────────────────────────────────


def list_genre_aliases(mapping_dir: Path) -> List[GenreAliasEntry]:
    return list_mapping(MAPPING_ID_GENRE_ALIASES, mapping_dir)


def get_genre_alias(
    alias: str, mapping_dir: Path,
) -> Tuple[Optional[GenreAliasEntry], str]:
    return get_mapping_entry(MAPPING_ID_GENRE_ALIASES, alias, mapping_dir)


def plan_genre_alias_update(
    alias: str, canonical: str, mapping_dir: Path,
) -> GenreAliasPlan:
    return plan_mapping_update(
        MAPPING_ID_GENRE_ALIASES, alias, {"canonical": canonical}, mapping_dir,
    )


def apply_genre_alias_update(
    alias: str, canonical: str, mapping_dir: Path, *, expected_etag: str,
) -> Tuple[GenreAliasPlan, GenreAliasSaveResult]:
    return apply_mapping_update(
        MAPPING_ID_GENRE_ALIASES, alias, {"canonical": canonical},
        mapping_dir, expected_etag,
    )


# ─────────────────────────────────────────────────────────────────────────
# Genre-Override-Komfort-Shims (M3)
# ─────────────────────────────────────────────────────────────────────────


def list_genre_overrides(mapping_dir: Path) -> List[GenreOverrideEntry]:
    return list_mapping(MAPPING_ID_GENRE_OVERRIDES, mapping_dir)


def get_genre_override(
    key: str, mapping_dir: Path,
) -> Tuple[Optional[GenreOverrideEntry], str]:
    return get_mapping_entry(MAPPING_ID_GENRE_OVERRIDES, key, mapping_dir)


def plan_genre_override_update(
    key: str, override: str, mapping_dir: Path,
) -> GenreOverridePlan:
    return plan_mapping_update(
        MAPPING_ID_GENRE_OVERRIDES, key, {"override": override}, mapping_dir,
    )


def apply_genre_override_update(
    key: str, override: str, mapping_dir: Path, *, expected_etag: str,
) -> Tuple[GenreOverridePlan, GenreOverrideSaveResult]:
    return apply_mapping_update(
        MAPPING_ID_GENRE_OVERRIDES, key, {"override": override},
        mapping_dir, expected_etag,
    )


# ─────────────────────────────────────────────────────────────────────────
# Genre-Filter (M4) — Liste statt Entry-Modell
# ─────────────────────────────────────────────────────────────────────────


def get_genre_filter_state(
    mapping_dir: Path,
) -> Tuple[List[str], str, List[str]]:
    """Rueckgabe: (normierte Werte, etag, warnings). Normalisiert die
    Rohliste aus der Datei (strip -> lower -> casefold-dedupe) — bei
    casefold-Duplikaten in der Datei wird das in `warnings` berichtet,
    die Datei bleibt unangetastet."""
    descriptor = _get_descriptor(MAPPING_ID_GENRE_FILTERS)
    raw = _load_raw_list(descriptor, mapping_dir)
    values, warnings = _normalize_filter_list(raw, strict=False)
    etag = _genre_filter_etag(values)
    return values, etag, warnings


def plan_genre_filter_update(
    values: object, mapping_dir: Path,
) -> GenreFilterPlan:
    descriptor = _get_descriptor(MAPPING_ID_GENRE_FILTERS)
    raw = _load_raw_list(descriptor, mapping_dir)
    current_values, current_warnings = _normalize_filter_list(raw, strict=False)
    current_etag = _genre_filter_etag(current_values)

    new_values, new_warnings = _normalize_filter_list(values, strict=True)

    all_warnings = list(new_warnings)

    # "cleanup": normalisierte Sicht == Ziel, aber die ROH-Datei ist
    # unsauber (Duplikate/Gross-/Kleinschreibung/Leerzeichen). Ein PUT
    # ist dann die kontrollierte Migration der Datei.
    raw_is_clean = list(raw) == list(current_values)

    if current_values == new_values:
        if raw_is_clean:
            change = "unchanged"
        else:
            change = "cleanup"
            if current_warnings:
                all_warnings.append(
                    "Die Datei enthaelt unsaubere Eintraege (Duplikate/"
                    "Gross-Kleinschreibung/Leerzeichen). Ein Speichern "
                    "schreibt die bereinigte Liste zurueck."
                )
    else:
        change = "update"

    current_fold = {v.casefold() for v in current_values}
    new_fold = {v.casefold() for v in new_values}
    added = [v for v in new_values if v.casefold() not in current_fold]
    removed = [v for v in current_values if v.casefold() not in new_fold]

    return GenreFilterPlan(
        mapping_id=descriptor.mapping_id,
        change=change,
        added=added,
        removed=removed,
        values=new_values,
        warnings=all_warnings,
        etag=current_etag,
    )


def apply_genre_filter_update(
    values: object, mapping_dir: Path, *, expected_etag: str, backup_dir: Optional[Path] = None,
) -> Tuple[GenreFilterPlan, GenreFilterSaveResult]:
    with _write_guard(_get_descriptor(MAPPING_ID_GENRE_FILTERS), mapping_dir):
        plan = plan_genre_filter_update(values, mapping_dir)
        if plan.etag != expected_etag:
            raise MappingConflictError(
                "Der Mapping-Stand wurde seit der Vorschau geaendert. "
                "Bitte neu laden und erneut pruefen."
            )
        if plan.change == "unchanged":
            return plan, GenreFilterSaveResult(
                written=False, unchanged=True,
                values=list(plan.values), new_etag=plan.etag,
            )
        # change in {"update", "cleanup"} -> schreiben
        descriptor = _get_descriptor(MAPPING_ID_GENRE_FILTERS)
        _snapshot_before_write(descriptor, mapping_dir, backup_dir)
        _dump_raw_list(descriptor, mapping_dir, plan.values)
        new_etag = _genre_filter_etag(plan.values)
        return plan, GenreFilterSaveResult(
            written=True, unchanged=False,
            values=list(plan.values), new_etag=new_etag,
        )


def list_genre_filters(mapping_dir: Path) -> List[str]:
    """Komfort-Shim: nur die normierte Werteliste."""
    values, _etag, _warnings = get_genre_filter_state(mapping_dir)
    return values


# ─────────────────────────────────────────────────────────────────────────
# Special-Channel (M5) — geordnete Kategorien
# ─────────────────────────────────────────────────────────────────────────


def get_special_channels_state(
    mapping_dir: Path,
) -> Tuple[List[SpecialChannelCategory], str, List[str]]:
    """Rueckgabe: (Kategorien, etag, warnings). Reihenfolge der Kategorien
    ist Semantik (Prioritaet). Datei bleibt unangetastet."""
    descriptor = _get_descriptor(MAPPING_ID_SPECIAL_CHANNELS)
    raw = _load_raw_special_categories(descriptor, mapping_dir)
    raw_list = [{"name": k, "channels": list(v) if isinstance(v, list) else []}
                for k, v in raw.items()]
    categories, warnings = _normalize_special_categories(raw_list, strict=False)
    etag = _special_channels_etag(categories)
    return categories, etag, warnings


def _raw_special_is_clean(
    descriptor: MappingDescriptor,
    mapping_dir: Path,
    normalized: List[SpecialChannelCategory],
) -> bool:
    """True, wenn die Roh-Datei semantisch identisch zur normalisierten
    Sicht ist. Prueft zusaetzlich die ROHEN Kanal-Laengen, damit Duplikate
    erkannt werden (die Normalisierung dedupliziert, sonst waere der
    Vergleich ein Zirkelschluss)."""
    raw = _load_raw_special_categories(descriptor, mapping_dir)
    # Laengen der Roh-Kanaele vs. normalisierte Laengen
    raw_cat_names = list(raw.keys())
    norm_cat_names = [c.name for c in normalized]
    if raw_cat_names != norm_cat_names:
        return False
    for raw_key, cat in zip(raw_cat_names, normalized):
        raw_channels = raw[raw_key] if isinstance(raw[raw_key], list) else []
        if len(raw_channels) != len(cat.channels):
            return False
        # Vergleich der Rohkanäle mit normalisierten (case- und whitespace-strikt)
        for raw_ch, norm_ch in zip(raw_channels, cat.channels):
            if not isinstance(raw_ch, str):
                return False
            if raw_ch.strip() != norm_ch:
                return False
    return True


def plan_special_channels_update(
    categories_input: object, mapping_dir: Path,
) -> SpecialChannelPlan:
    descriptor = _get_descriptor(MAPPING_ID_SPECIAL_CHANNELS)
    current_categories, current_warnings = _normalize_special_categories(
        [{"name": k, "channels": list(v) if isinstance(v, list) else []}
         for k, v in _load_raw_special_categories(descriptor, mapping_dir).items()],
        strict=False,
    )
    current_etag = _special_channels_etag(current_categories)
    raw_is_clean = _raw_special_is_clean(descriptor, mapping_dir, current_categories)

    new_categories, new_warnings = _normalize_special_categories(
        categories_input, strict=True,
    )

    all_warnings = list(new_warnings)

    # Diff: Kategorien
    current_cat_map = {c.name.casefold(): c for c in current_categories}
    new_cat_map = {c.name.casefold(): c for c in new_categories}
    added: List[str] = []
    removed: List[str] = []
    for key, cat in new_cat_map.items():
        cur = current_cat_map.get(key)
        if cur is None:
            added.append(f"Kategorie {cat.name!r}")
            for ch in cat.channels:
                added.append(f"{cat.name}: {ch}")
            continue
        cur_fold = {c.casefold() for c in cur.channels}
        for ch in cat.channels:
            if ch.casefold() not in cur_fold:
                added.append(f"{cat.name}: {ch}")
    for key, cat in current_cat_map.items():
        new = new_cat_map.get(key)
        if new is None:
            removed.append(f"Kategorie {cat.name!r}")
            for ch in cat.channels:
                removed.append(f"{cat.name}: {ch}")
            continue
        new_fold = {c.casefold() for c in new.channels}
        for ch in cat.channels:
            if ch.casefold() not in new_fold:
                removed.append(f"{cat.name}: {ch}")

    # Reihenfolge der Kategorien ist die Prioritaet: eine reine Umordnung ist
    # eine Aenderung, auch wenn kein Kanal/keine Kategorie dazukommt oder wegfaellt.
    common_before = [c.name.casefold() for c in current_categories if c.name.casefold() in new_cat_map]
    common_after = [c.name.casefold() for c in new_categories if c.name.casefold() in current_cat_map]
    reordered = common_before != common_after
    order_change = (
        "Reihenfolge: " + ", ".join(c.name for c in current_categories)
        + " → " + ", ".join(c.name for c in new_categories)
        if reordered else None
    )

    # change-Bewertung
    if not added and not removed and not reordered and raw_is_clean:
        change = "unchanged"
    elif not added and not removed and not reordered and not raw_is_clean:
        change = "cleanup"
        if current_warnings:
            all_warnings.append(
                "Die Datei enthaelt unsaubere Eintraege (Duplikate/"
                "Gross-Kleinschreibung/Leerzeichen). Ein Speichern "
                "schreibt die bereinigte Struktur zurueck."
            )
    else:
        change = "update"

    return SpecialChannelPlan(
        mapping_id=descriptor.mapping_id,
        change=change,
        categories=new_categories,
        added=added,
        removed=removed,
        warnings=all_warnings,
        etag=current_etag,
        order_change=order_change,
    )


def apply_special_channels_update(
    categories_input: object, mapping_dir: Path, *, expected_etag: str, backup_dir: Optional[Path] = None,
) -> Tuple[SpecialChannelPlan, SpecialChannelSaveResult]:
    with _write_guard(_get_descriptor(MAPPING_ID_SPECIAL_CHANNELS), mapping_dir):
        plan = plan_special_channels_update(categories_input, mapping_dir)
        if plan.etag != expected_etag:
            raise MappingConflictError(
                "Der Mapping-Stand wurde seit der Vorschau geaendert. "
                "Bitte neu laden und erneut pruefen."
            )
        if plan.change == "unchanged":
            return plan, SpecialChannelSaveResult(
                written=False, unchanged=True,
                categories=list(plan.categories), new_etag=plan.etag,
            )
        descriptor = _get_descriptor(MAPPING_ID_SPECIAL_CHANNELS)
        _snapshot_before_write(descriptor, mapping_dir, backup_dir)
        _dump_special_categories(descriptor, mapping_dir, plan.categories)
        new_etag = _special_channels_etag(plan.categories)
        return plan, SpecialChannelSaveResult(
            written=True, unchanged=False,
            categories=list(plan.categories), new_etag=new_etag,
        )


def list_special_channel_categories(mapping_dir: Path) -> List[SpecialChannelCategory]:
    cats, _etag, _w = get_special_channels_state(mapping_dir)
    return cats


# ─────────────────────────────────────────────────────────────────────────
# Oeffentliche Bausteine fuer services/mapping_restore.py
# ─────────────────────────────────────────────────────────────────────────

get_descriptor = _get_descriptor
write_guard = _write_guard
mapping_file_path = _mapping_path
snapshot_before_write = _snapshot_before_write
write_mapping_text = _atomic_write_text

# Fachliche Validatoren, die auch der YAML-Editor (services/mapping_yaml.py) nutzt —
# eine Regelquelle fuer Visual Editor und Rohtext.
validate_channel_name = _validate_channel_name
validate_alias_key = _validate_alias_key
validate_genre = _validated_genre
validate_description = _validate_description
validate_secondary_list = _validate_secondary_list
normalize_filter_list = _normalize_filter_list
normalize_special_categories = _normalize_special_categories
override_key_warnings = _override_key_runtime_warnings
etag_of = _etag_of


def check_restorable(mapping_id: str, text: str) -> None:
    """Zusaetzliche fachliche Pruefung einer wiederherzustellenden Version.
    Nur der Hierarchie-Baum braucht sie (Zyklus/unbekannter Parent wuerde die
    Runtime-Prioritaeten verfaelschen); die uebrigen Typen sind flach."""
    if _get_descriptor(mapping_id).kind == "genre-hierarchy":
        from services import mapping_hierarchy

        mapping_hierarchy.check_text(text)


def mapping_file_names() -> Dict[str, str]:
    """Allowlist: mapping_id -> Dateiname der im Control Center bearbeitbaren Dateien."""
    return {d.mapping_id: d.filename for d in _MAPPING_DESCRIPTORS.values()}


def get_current_etag(mapping_id: str, mapping_dir: Path) -> str:
    """Etag des aktuellen Mapping-Stands, so wie ihn auch GET/Preview liefern."""
    descriptor = _get_descriptor(mapping_id)
    if descriptor.kind == "genre-filter":
        return get_genre_filter_state(mapping_dir)[1]
    if descriptor.kind == "special-channel":
        return get_special_channels_state(mapping_dir)[1]
    if descriptor.kind == "genre-hierarchy":
        from services import mapping_hierarchy  # lazy: mapping_hierarchy importiert dieses Modul

        return mapping_hierarchy.get_hierarchy_state(mapping_dir)[1]
    return _compute_etag(descriptor, _load_raw_mapping(descriptor, mapping_dir))


def describe_mapping(mapping_id: str, mapping_dir: Path) -> Dict[str, str]:
    """Fachlicher Inhalt einer Mapping-Datei als flache Zuordnung
    `Schluessel -> Wert` (fuer Diffs zwischen Staenden). Wirft
    MappingUnavailableError, wenn die Datei nicht lesbar ist."""
    descriptor = _get_descriptor(mapping_id)
    if descriptor.kind == "genre-filter":
        return {v: v for v in get_genre_filter_state(mapping_dir)[0]}
    if descriptor.kind == "special-channel":
        items: Dict[str, str] = {}
        for position, category in enumerate(get_special_channels_state(mapping_dir)[0], start=1):
            items[f"Kategorie {category.name}"] = f"Position {position}"
            for channel in category.channels:
                items[f"{category.name}: {channel}"] = channel
        return items
    if descriptor.kind == "genre-hierarchy":
        from services import mapping_hierarchy

        return mapping_hierarchy.describe_hierarchy(mapping_dir)
    result: Dict[str, str] = {}
    for entry in list_mapping(mapping_id, mapping_dir):
        if descriptor.kind == "channel-genre":
            result[entry.key.casefold()] = (
                f"{entry.primary} · {', '.join(entry.secondary) or '—'} · {entry.description or '—'}"
            )
        elif descriptor.kind == "genre-alias":
            result[entry.key.casefold()] = entry.canonical
        else:  # genre-override: Keys sind case-sensitiv
            result[entry.key] = entry.override
    return result
