# services/mapping_yaml.py
# -*- coding: utf-8 -*-
"""
YAML-Editor der Mapping-Administration: Rohtext einer Mapping-Datei lesen,
pruefen und (mit Etag und Backup) unveraendert zurueckschreiben.

Der Text kommt vom Client und ist damit nicht vertrauenswuerdig:

- nie ein unsicherer Loader (nur `yaml.safe_load` und der Event-Parser),
- genau ein Dokument, keine Anker/Aliase (Alias-Bombe), keine Merge-Keys,
  keine expliziten Tags, keine doppelten Keys, einfache Text-Keys,
- begrenzte Groesse, Tiefe und Knotenzahl, keine Steuerzeichen,
- genau der erwartete Root-Key (die Loader der Runtime fallen sonst auf das
  ganze Dokument zurueck),
- danach dieselben fachlichen Validatoren wie im Visual Editor.

Geschrieben wird der validierte Text unveraendert (Kommentare bleiben
erhalten); Zeilenenden werden auf LF normalisiert. Schreiben laeuft unter dem
Schreib-Lock, mit Etag (SHA-256 der Datei) und Backup wie jeder andere Write.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services import mapping_admin as ma
from services.mapping_restore import describe_text, diff_items

MAX_RAW_BYTES = 512 * 1024
MAX_DEPTH = 6
MAX_EVENTS = 60_000
MAX_ERRORS = 20
MAX_DIFF_LINES = 400

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class _Invalid(ma.MappingInvalidInputError):
    """Kurzform fuer Eingabefehler dieses Moduls."""


@dataclass(frozen=True)
class RawFile:
    mapping_id: str
    filename: str
    text: str
    etag: str
    size: int
    max_bytes: int = MAX_RAW_BYTES


@dataclass
class RawPlan:
    mapping_id: str
    change: str  # "update" | "format" | "unchanged"
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    text_diff: List[str] = field(default_factory=list)
    etag: str = ""


@dataclass(frozen=True)
class RawResult:
    written: bool
    unchanged: bool
    new_etag: str


# Der Baum (genre-hierarchy) wird bewusst nur ueber die strukturierte Ansicht
# bearbeitet: ein Rohtext-Editor umginge Zyklen-/Parent-Pruefung und Preview.
_NO_YAML_EDITOR_KINDS = frozenset({"genre-hierarchy"})


def _require_yaml_editor(descriptor: ma.MappingDescriptor) -> None:
    if descriptor.kind in _NO_YAML_EDITOR_KINDS:
        raise ma.MappingUnknownIdError(
            f"Für {descriptor.mapping_id} gibt es keinen YAML-Editor (Baum-Datei: nur über die Hierarchie-Ansicht bearbeitbar)."
        )


def _etag(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ── Lesen ────────────────────────────────────────────────────────────────


def read_raw(mapping_id: str, mapping_dir: Path) -> RawFile:
    descriptor = ma.get_descriptor(mapping_id)  # Allowlist, bevor ein Pfad entsteht
    _require_yaml_editor(descriptor)
    path = ma.mapping_file_path(descriptor, mapping_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ma.MappingUnavailableError(f"{descriptor.filename} konnte nicht gelesen werden.") from e
    return RawFile(mapping_id, descriptor.filename, text, _etag(text), len(text.encode("utf-8")))


# ── Sicheres Parsen ──────────────────────────────────────────────────────


def _prepare_text(text: object) -> str:
    if not isinstance(text, str):
        raise _Invalid("Der YAML-Text muss ein Text sein.")
    if len(text.encode("utf-8")) > MAX_RAW_BYTES:
        raise _Invalid(f"Der YAML-Text ist zu groß (max. {MAX_RAW_BYTES // 1024} KB).")
    if _CONTROL.search(text):
        raise _Invalid("Der YAML-Text enthält Steuerzeichen.")
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise _Invalid("Der YAML-Text ist leer.")
    return text if text.endswith("\n") else text + "\n"


def _scan_events(text: str) -> None:
    """Prueft den Event-Strom, OHNE Objekte zu bauen: ein Dokument, keine Anker/
    Aliase/Tags/Merge-Keys, einfache und eindeutige Keys, begrenzte Tiefe und Groesse."""
    import yaml

    stack: List[Dict[str, Any]] = []
    documents = 0
    count = 0

    def on_value(event: Any, scalar: bool) -> None:
        if not stack or stack[-1]["kind"] != "map":
            return
        top = stack[-1]
        if top["expect_key"]:
            if not scalar:
                raise _Invalid("Ein Key muss ein einfacher Text sein.")
            key = event.value
            if key == "<<":
                raise _Invalid("Merge-Keys (<<) sind nicht erlaubt.")
            if key in top["keys"]:
                raise _Invalid(f"Doppelter Key: {key!r}.")
            top["keys"].add(key)
            top["expect_key"] = False
        else:
            top["expect_key"] = True

    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            count += 1
            if count > MAX_EVENTS:
                raise _Invalid("Der YAML-Text ist zu umfangreich.")
            if isinstance(event, yaml.DocumentStartEvent):
                documents += 1
                if documents > 1:
                    raise _Invalid("Erlaubt ist genau ein YAML-Dokument (kein '---' zwischen mehreren).")
            if isinstance(event, yaml.AliasEvent):
                raise _Invalid("Anker und Aliase (&, *) sind nicht erlaubt.")
            if getattr(event, "anchor", None):
                raise _Invalid("Anker und Aliase (&, *) sind nicht erlaubt.")
            if getattr(event, "tag", None):
                raise _Invalid("YAML-Tags (!, !!) sind nicht erlaubt.")
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                on_value(event, scalar=False)
                stack.append({"kind": "map" if isinstance(event, yaml.MappingStartEvent) else "seq", "keys": set(), "expect_key": True})
                if len(stack) > MAX_DEPTH:
                    raise _Invalid(f"Der YAML-Text ist zu tief verschachtelt (max. {MAX_DEPTH} Ebenen).")
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                stack.pop()
            elif isinstance(event, yaml.ScalarEvent):
                on_value(event, scalar=True)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (Zeile {mark.line + 1}, Spalte {mark.column + 1})" if mark else ""
        problem = getattr(e, "problem", None) or "Syntaxfehler"
        raise _Invalid(f"Der Text ist kein gültiges YAML{where}: {problem}.") from e


def _load_payload(descriptor: ma.MappingDescriptor, text: str) -> Any:
    import yaml

    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise _Invalid("Das Dokument muss ein Mapping (Schlüssel: Wert) sein.")
    if descriptor.root_key not in data:
        raise _Invalid(f"Der Root-Key {descriptor.root_key} fehlt.")
    extra = [str(k) for k in data if k != descriptor.root_key]
    if extra:
        raise _Invalid(f"Unerwartete Top-Level-Keys: {', '.join(extra)} (erlaubt ist nur {descriptor.root_key}).")
    return data[descriptor.root_key]


# ── Fachliche Validierung je Typ ─────────────────────────────────────────


def _text(value: Any, what: str) -> Any:
    """YAML liest `5`, `true` oder `2020` als Zahl/Bool; in Mapping-Dateien muessen
    Keys und Werte Text sein (die Runtime ruft `.lower()`/`.strip()` darauf auf)."""
    if value is None:
        raise _Invalid(f"{what} fehlt (Pflichtfeld).")
    if not isinstance(value, str):
        raise _Invalid(f"{what} muss ein Text sein (in Anführungszeichen setzen, falls es wie eine Zahl aussieht).")
    return value


def _collect(errors: List[str], label: str, fn) -> Any:
    try:
        return fn()
    except ma.MappingInvalidInputError as e:
        errors.append(f"{label}: {e}")
        return None


def _validate_channel_genre(payload: Any) -> List[str]:
    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(payload, dict):
        raise _Invalid("CHANNEL_GENRE_MAP muss ein Mapping sein.")
    for key, value in payload.items():
        label = str(key)
        _collect(errors, label, lambda: ma.validate_channel_name(_text(key, "Der Key")))
        if not isinstance(value, dict):
            errors.append(f"{label}: Eintrag muss ein Mapping mit primary/secondary/description sein.")
            continue
        unknown = sorted(set(map(str, value)) - {"primary", "secondary", "description"})
        if unknown:
            errors.append(f"{label}: Unbekanntes Feld: {', '.join(unknown)}.")
        primary = _collect(errors, label, lambda: ma.validate_genre(_text(value.get("primary"), "primary"), "Primär-Genre"))
        if primary is not None:
            result = _collect(errors, label, lambda: ma.validate_secondary_list(value.get("secondary"), primary))
            if result:
                warnings += [f"{label}: {w}" for w in result[1]]
        desc = value.get("description")
        _collect(errors, label, lambda: ma.validate_description(None if desc is None else _text(desc, "description")))
    _raise_if(errors)
    return warnings


def _validate_key_value(payload: Any, root: str, value_label: str, *, case_sensitive: bool) -> List[str]:
    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(payload, dict):
        raise _Invalid(f"{root} muss ein Mapping sein.")
    seen: Dict[str, str] = {}
    for key, value in payload.items():
        label = str(key)
        clean = _collect(errors, label, lambda: ma.validate_alias_key(_text(key, "Der Key")))
        _collect(errors, label, lambda: ma.validate_genre(_text(value, value_label), value_label))
        if clean is None:
            continue
        if case_sensitive:
            warnings += ma.override_key_warnings(clean)
        else:
            fold = clean.casefold()
            if fold in seen:
                warnings.append(f"'{clean}' und '{seen[fold]}' unterscheiden sich nur in der Schreibweise; die Runtime liest beide als denselben Key.")
            seen[fold] = clean
    _raise_if(errors)
    return warnings


def _validate_filters(payload: Any) -> List[str]:
    if not isinstance(payload, list):
        raise _Invalid("IGNORE_SECONDARY muss eine Liste sein.")
    for item in payload:
        _text(item, "Jeder Filter")
    normalized, warnings = ma.normalize_filter_list(payload, strict=True)
    if normalized != payload:
        warnings = list(warnings) + [
            f"{len(payload) - len(normalized) if len(payload) != len(normalized) else 'Einige'} Einträge sind nicht normalisiert "
            "(Groß-/Kleinschreibung, Leerzeichen oder Duplikate); die Runtime findet Filter nur kleingeschrieben."
        ]
    return list(warnings)


def _validate_special(payload: Any) -> List[str]:
    if not isinstance(payload, dict):
        raise _Invalid("SPECIAL_CHANNELS muss ein Mapping (Kategorie: Kanal-Liste) sein.")
    for name, channels in payload.items():
        _text(name, "Der Kategoriename")
        if not isinstance(channels, list):
            raise _Invalid(f"Kategorie {name!r}: Die Kanäle müssen eine Liste sein.")
        for channel in channels:
            _text(channel, f"Kategorie {name!r}: Jeder Kanalname")
    categories = [{"name": name, "channels": channels} for name, channels in payload.items()]
    _cats, warnings = ma.normalize_special_categories(categories, strict=True)
    return list(warnings)


def _raise_if(errors: List[str]) -> None:
    if errors:
        shown = errors[:MAX_ERRORS]
        more = f"\n… und {len(errors) - MAX_ERRORS} weitere Fehler." if len(errors) > MAX_ERRORS else ""
        raise _Invalid("\n".join(shown) + more)


def _validate(descriptor: ma.MappingDescriptor, payload: Any) -> List[str]:
    kind = descriptor.kind
    if kind == "channel-genre":
        return _validate_channel_genre(payload)
    if kind == "genre-alias":
        return _validate_key_value(payload, descriptor.root_key, "Zielgenre", case_sensitive=False)
    if kind == "genre-override":
        return _validate_key_value(payload, descriptor.root_key, "Zielgenre", case_sensitive=True)
    if kind == "genre-filter":
        return _validate_filters(payload)
    if kind == "special-channel":
        return _validate_special(payload)
    raise ma.MappingUnknownIdError(f"Unbekannter kind: {kind!r}")


def validate_raw_text(mapping_id: str, text: object) -> Tuple[str, List[str]]:
    """Prueft einen Rohtext vollstaendig. Rueckgabe: (normalisierter Text, Warnungen).
    Wirft MappingInvalidInputError mit allen gefundenen Fehlern (eine Zeile je Fehler)."""
    descriptor = ma.get_descriptor(mapping_id)
    _require_yaml_editor(descriptor)
    prepared = _prepare_text(text)
    _scan_events(prepared)
    payload = _load_payload(descriptor, prepared)
    return prepared, _validate(descriptor, payload)


# ── Plan / Diff ──────────────────────────────────────────────────────────


def _text_diff(current: str, new: str) -> List[str]:
    lines = list(difflib.unified_diff(current.splitlines(), new.splitlines(), "aktuell", "neu", n=2, lineterm=""))
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + [f"… Diff gekürzt ({len(lines) - MAX_DIFF_LINES} weitere Zeilen)"]
    return lines


def _as_prepared(text: str) -> str:
    """Aktueller Dateiinhalt in derselben Form wie ein vorbereiteter Text (LF, ein Schlusszeilenumbruch)."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return text if text.endswith("\n") else text + "\n"


def plan_raw_update(mapping_id: str, text: object, mapping_dir: Path) -> RawPlan:
    prepared, warnings = validate_raw_text(mapping_id, text)
    current = read_raw(mapping_id, mapping_dir)
    if prepared == _as_prepared(current.text):
        return RawPlan(mapping_id, "unchanged", etag=current.etag, warnings=warnings)
    added, removed, changed = diff_items(
        describe_text(mapping_id, current.text), describe_text(mapping_id, prepared),
    ) if _readable(mapping_id, current.text) else ([], [], [])
    change = "update" if (added or removed or changed) else "format"
    return RawPlan(
        mapping_id, change, added, removed, changed, warnings, _text_diff(current.text, prepared), current.etag,
    )


def _readable(mapping_id: str, text: str) -> bool:
    """Die aktuelle Datei darf auch unlesbar sein (z. B. halb kaputt) — dann gibt es nur den Text-Diff."""
    try:
        describe_text(mapping_id, text)
        return True
    except ma.MappingDomainError:
        return False


def apply_raw_update(
    mapping_id: str, text: object, mapping_dir: Path, *, expected_etag: str, backup_dir: Optional[Path] = None,
) -> Tuple[RawPlan, RawResult]:
    descriptor = ma.get_descriptor(mapping_id)
    with ma.write_guard(descriptor, mapping_dir):
        plan = plan_raw_update(mapping_id, text, mapping_dir)
        if plan.etag != expected_etag:
            raise ma.MappingConflictError(
                "Die Mapping-Datei wurde seit dem Laden geändert. Bitte neu laden und erneut prüfen."
            )
        if plan.change == "unchanged":
            return plan, RawResult(False, True, plan.etag)
        prepared, _ = validate_raw_text(mapping_id, text)
        ma.snapshot_before_write(descriptor, mapping_dir, backup_dir)
        ma.write_mapping_text(ma.mapping_file_path(descriptor, mapping_dir), prepared)
        return plan, RawResult(True, False, read_raw(mapping_id, mapping_dir).etag)
