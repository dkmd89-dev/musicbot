# services/mapping_hierarchy.py
# -*- coding: utf-8 -*-
"""
Genre-Hierarchie (genre_hierarchy.yaml) in der Mapping-Administration.

Die Datei ist ein Baum, keine Key/Value-Liste: `GENRE_HIERARCHY: {Kind: Eltern|null}`.
Die Runtime liest sie an zwei Stellen und leitet daraus die Genre-Prioritaet ab
(Tiefe im Baum = Prioritaet, siehe services/metadata/genre_processor.py und
utils/genre_map.py):

- Der Eltern-Name muss exakt (Gross-/Kleinschreibung) einem Key entsprechen,
  sonst zaehlt das Genre dort als Tiefe 0.
- Ein Parent-Wechsel verschiebt damit die Prioritaet des ganzen Unterbaums.

Dieses Modul verwaltet den Baum als Ganzes: der Client sendet den gewuenschten
Endzustand, geprueft wird der Endbaum (unbekannter Parent, Selbstbezug, Zyklus,
doppelte oder ungueltige Namen). Ein Genre mit Kindern kann so nie stillschweigend
verschwinden — seine Kinder verwiesen sonst auf einen unbekannten Parent.

Geschrieben wird zeilenweise: nur betroffene Zeilen aendern sich, Abschnitts-
kommentare und Reihenfolge bleiben erhalten (yaml.safe_dump wuerde die ganze
Datei umschreiben und alle Kommentare verwerfen). Vor dem Schreiben wird per
Rundlauf geprueft, dass der gepatchte Text genau dem Zielbaum entspricht;
andernfalls wird nichts geschrieben.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from services import mapping_admin as ma

MAX_ENTRIES = 2000
MAX_ERRORS = 20
MAX_LISTED_DESCENDANTS = 10
ROOT_LABEL = "Wurzel"

# Namen muessen als einfacher YAML-Text (ohne Anfuehrungszeichen) geschrieben
# werden koennen und vom zeilenweisen Writer wieder gelesen werden: kein ':',
# '#', Anfuehrungszeichen; erstes Zeichen Buchstabe oder Ziffer.
_NAME_PATTERN = re.compile(r"^[^\W_][\w &.+/-]*$")
_SECTION_START = re.compile(r"^GENRE_HIERARCHY:[ \t]*(#.*)?$")
_ENTRY_LINE = re.compile(
    r"^(?P<indent> +)(?P<key>[^\s#:'\"][^#:'\"]*?):[ \t]+(?P<value>[^\s#:'\"][^#:'\"]*?)(?P<tail>[ \t]*(?:#.*)?)$"
)

Hierarchy = Dict[str, Optional[str]]


@dataclass(frozen=True)
class HierarchyEntry:
    genre: str
    parent: Optional[str]
    depth: int
    children: int


@dataclass(frozen=True)
class HierarchyChange:
    genre: str
    kind: str  # "added" | "removed" | "parent_changed"
    old_parent: Optional[str]
    new_parent: Optional[str]
    old_depth: Optional[int]
    new_depth: Optional[int]
    affected: List[str] = field(default_factory=list)  # betroffene untergeordnete Genres (gekuerzt)
    affected_count: int = 0


@dataclass(frozen=True)
class HierarchyPlan:
    mapping_id: str
    change: str  # "update" | "unchanged"
    entries: List[HierarchyEntry]
    added: List[str]
    removed: List[str]
    changed: List[str]
    changes: List[HierarchyChange]
    warnings: List[str]
    etag: str


@dataclass(frozen=True)
class HierarchySaveResult:
    written: bool
    unchanged: bool
    entries: List[HierarchyEntry]
    new_etag: str


# ── Lesen ────────────────────────────────────────────────────────────────


def _descriptor() -> ma.MappingDescriptor:
    return ma.get_descriptor(ma.MAPPING_ID_GENRE_HIERARCHY)


def _read_text(mapping_dir: Path) -> str:
    path = ma.mapping_file_path(_descriptor(), mapping_dir)
    try:
        # newline="" behaelt Zeilenenden unveraendert; der zeilenweise Writer
        # lehnt Windows-Zeilenenden ab, statt sie unbemerkt umzuschreiben.
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as e:
        raise ma.MappingUnavailableError(f"{path} konnte nicht gelesen werden.") from e


def _parse_mapping(text: str, label: str) -> Hierarchy:
    import yaml

    descriptor = _descriptor()
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ma.MappingUnavailableError(f"{label}: kein gültiges YAML ({e.__class__.__name__}).") from e
    raw = data.get(descriptor.root_key) if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        raise ma.MappingUnavailableError(f"{label}: '{descriptor.root_key}' fehlt oder ist kein Dict.")
    result: Hierarchy = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not (value is None or isinstance(value, str)):
            raise ma.MappingUnavailableError(f"{label}: Eintrag {key!r} hat ein unerwartetes Format.")
        result[key] = value
    return result


def _load(mapping_dir: Path) -> Tuple[str, Hierarchy]:
    text = _read_text(mapping_dir)
    return text, _parse_mapping(text, _descriptor().filename)


def _etag(mapping: Hierarchy) -> str:
    return ma.etag_of([[genre, mapping[genre]] for genre in sorted(mapping)])


def _depths(mapping: Hierarchy) -> Dict[str, int]:
    """Tiefe je Genre wie die Runtime: Wurzel = 0; unbekannter Parent oder Zyklus
    ergibt 0 (die Runtime setzt nicht erreichbare Genres auf 0)."""
    depths: Dict[str, int] = {}
    for genre in mapping:
        depth, node, seen = 0, genre, {genre}
        while mapping.get(node) is not None:
            node = mapping[node]  # type: ignore[assignment]
            if node not in mapping or node in seen:
                depth = 0
                break
            seen.add(node)
            depth += 1
        depths[genre] = depth
    return depths


def _child_counts(mapping: Hierarchy) -> Dict[str, int]:
    counts: Dict[str, int] = {genre: 0 for genre in mapping}
    for parent in mapping.values():
        if parent in counts:
            counts[parent] += 1  # type: ignore[index]
    return counts


def _entries(mapping: Hierarchy) -> List[HierarchyEntry]:
    depths, counts = _depths(mapping), _child_counts(mapping)
    return [HierarchyEntry(g, p, depths[g], counts[g]) for g, p in mapping.items()]


def _descendants(mapping: Hierarchy, genre: str) -> List[str]:
    found: List[str] = []
    frontier = [genre]
    while frontier:
        node = frontier.pop(0)
        for child, parent in mapping.items():
            if parent == node and child not in found and child != genre:
                found.append(child)
                frontier.append(child)
    return found


def get_hierarchy_state(mapping_dir: Path) -> Tuple[List[HierarchyEntry], str, List[str]]:
    """(Eintraege in Dateireihenfolge, Etag, Warnungen). Eine handgepflegte Datei
    darf Fehler enthalten: sie werden als Warnung gemeldet, nicht als Ausnahme."""
    _text, mapping = _load(mapping_dir)
    return _entries(mapping), _etag(mapping), [f"Datei: {e}" for e in _tree_errors(mapping)]


def describe_hierarchy(mapping_dir: Path) -> Dict[str, str]:
    """Flache Sicht fuer Versions-Diffs: Genre -> Eltern (oder Wurzel)."""
    return {genre: parent or ROOT_LABEL for genre, parent in _load(mapping_dir)[1].items()}


# ── Validierung ──────────────────────────────────────────────────────────


def _tree_errors(mapping: Hierarchy) -> List[str]:
    errors: List[str] = []
    if mapping and all(parent is not None for parent in mapping.values()):
        errors.append("Es gibt kein Wurzel-Genre (Eltern leer).")
    by_fold: Dict[str, str] = {}
    for genre in mapping:
        by_fold.setdefault(genre.casefold(), genre)
    reported: set = set()
    for genre, parent in mapping.items():
        if parent is None:
            continue
        if parent == genre:
            errors.append(f"{genre!r}: Ein Genre kann nicht sein eigener Eltern-Eintrag sein.")
            continue
        if parent not in mapping:
            hint = by_fold.get(parent.casefold())
            suffix = f" (Meinten Sie {hint!r}? Die Schreibweise muss exakt stimmen.)" if hint else ""
            errors.append(f"{genre!r}: Eltern-Genre {parent!r} existiert nicht{suffix}.")
            continue
        path, node = [genre], parent
        while node is not None and node in mapping and node not in path:
            path.append(node)
            node = mapping[node]
        if node in path:
            cycle = path[path.index(node):]
            marker = frozenset(cycle)
            if marker not in reported:
                reported.add(marker)
                errors.append("Zyklus: " + " → ".join(cycle + [cycle[0]]) + ".")
    return errors


def _clean_name(value: object, label: str, errors: List[str]) -> Optional[str]:
    import yaml

    try:
        name = ma.validate_genre(value, label)
    except ma.MappingInvalidInputError as e:
        errors.append(str(e))
        return None
    if not _NAME_PATTERN.match(name):
        errors.append(
            f"{label} {name!r}: erlaubt sind Buchstaben, Ziffern, Leerzeichen und & . + / - "
            "(erstes Zeichen Buchstabe oder Ziffer)."
        )
        return None
    if not isinstance(yaml.safe_load(name), str):
        errors.append(f"{label} {name!r} würde in YAML nicht als Text gelesen (z. B. Zahl oder ja/nein).")
        return None
    return name


def _raise_if(errors: List[str]) -> None:
    if errors:
        more = f"\n… und {len(errors) - MAX_ERRORS} weitere Fehler." if len(errors) > MAX_ERRORS else ""
        raise ma.MappingInvalidInputError("\n".join(errors[:MAX_ERRORS]) + more)


def normalize_entries(payload: object) -> Hierarchy:
    """Prueft den vom Client gesendeten Endzustand und liefert Genre -> Eltern|None.
    Wirft MappingInvalidInputError mit allen gefundenen Fehlern (eine Zeile je Fehler)."""
    if not isinstance(payload, list):
        raise ma.MappingInvalidInputError("Die Hierarchie muss eine Liste von Einträgen sein.")
    if len(payload) > MAX_ENTRIES:
        raise ma.MappingInvalidInputError(f"Zu viele Einträge (max. {MAX_ENTRIES}).")
    errors: List[str] = []
    result: Hierarchy = {}
    seen_fold: Dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            errors.append("Jeder Eintrag muss ein Objekt mit 'genre' und 'parent' sein.")
            continue
        genre = _clean_name(item.get("genre"), "Genre", errors)
        raw_parent = item.get("parent")
        blank_parent = raw_parent is None or (isinstance(raw_parent, str) and not raw_parent.strip())
        parent = None if blank_parent else _clean_name(raw_parent, "Eltern-Genre", errors)
        if genre is None or (not blank_parent and parent is None):
            continue
        if genre.casefold() in seen_fold:
            errors.append(f"Doppeltes Genre: {genre!r} (bereits als {seen_fold[genre.casefold()]!r} vorhanden).")
            continue
        seen_fold[genre.casefold()] = genre
        result[genre] = parent
    if not errors:
        errors.extend(_tree_errors(result))
    if not errors and not result:
        errors.append("Die Hierarchie darf nicht leer sein.")
    _raise_if(errors)
    return result


def check_text(text: str) -> None:
    """Prueft einen kompletten Dateitext (z. B. eine wiederherzustellende Version)
    mit denselben Baum-Regeln wie ein Save."""
    try:
        mapping = _parse_mapping(text, "Diese Version")
    except ma.MappingUnavailableError as e:
        raise ma.MappingInvalidInputError(str(e)) from e
    _raise_if(_tree_errors(mapping))


# ── Plan ─────────────────────────────────────────────────────────────────


def _label(parent: Optional[str]) -> str:
    return parent if parent is not None else ROOT_LABEL


def _build_plan(payload: object, mapping_dir: Path) -> Tuple[HierarchyPlan, str, Hierarchy, Hierarchy]:
    text, current = _load(mapping_dir)
    new = normalize_entries(payload)
    old_depths, new_depths = _depths(current), _depths(new)

    changes: List[HierarchyChange] = []
    added: List[str] = []
    removed: List[str] = []
    changed: List[str] = []
    warnings: List[str] = []
    depth_shifts = 0

    for genre, parent in new.items():
        if genre not in current:
            added.append(f"{genre}: {_label(parent)}")
            changes.append(HierarchyChange(genre, "added", None, parent, None, new_depths[genre]))
        elif current[genre] != parent:
            below = _descendants(new, genre)
            changed.append(f"{genre}: {_label(current[genre])} → {_label(parent)}")
            changes.append(HierarchyChange(
                genre, "parent_changed", current[genre], parent, old_depths[genre], new_depths[genre],
                below[:MAX_LISTED_DESCENDANTS], len(below),
            ))
            if old_depths[genre] != new_depths[genre]:
                depth_shifts += 1 + len(below)
    lost_children: List[str] = []
    for genre, parent in current.items():
        if genre not in new:
            below = [g for g in _descendants(current, genre) if g not in new]
            removed.append(f"{genre}: {_label(parent)}")
            changes.append(HierarchyChange(
                genre, "removed", parent, None, old_depths[genre], None,
                below[:MAX_LISTED_DESCENDANTS], len(below),
            ))
            if below:
                lost_children.append(genre)

    if depth_shifts:
        warnings.append(
            f"Die Genre-Priorität (Tiefe im Baum) ändert sich für {depth_shifts} Genre(s); "
            "das wirkt auf die Auswahl bei mehreren Tags."
        )
    if lost_children:
        warnings.append(
            "Mit dem Eltern-Genre wurden auch alle untergeordneten Genres entfernt: "
            + ", ".join(sorted(lost_children)) + "."
        )
    if removed:
        warnings.append(
            "Entfernte Genres bleiben in Aliasen, Overrides und Artist-Mappings stehen; "
            "die Hierarchie kennt sie danach nicht mehr."
        )

    plan = HierarchyPlan(
        mapping_id=ma.MAPPING_ID_GENRE_HIERARCHY,
        change="unchanged" if new == current else "update",
        entries=_entries(new),
        added=added, removed=removed, changed=changed, changes=changes, warnings=warnings,
        etag=_etag(current),
    )
    return plan, text, current, new


def plan_hierarchy_update(payload: object, mapping_dir: Path) -> HierarchyPlan:
    return _build_plan(payload, mapping_dir)[0]


# ── Zeilenweiser Writer ──────────────────────────────────────────────────


def _is_filler(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _patch_text(text: str, current: Hierarchy, new: Hierarchy) -> str:
    """Wendet den Unterschied current -> new auf den Dateitext an. Nur die
    betroffenen Zeilen aendern sich: Eltern-Wechsel ersetzen den Wert (Kommentar am
    Zeilenende bleibt), entfernte Genres verlieren ihre Zeile, neue Genres werden
    hinter dem letzten Geschwister eingefuegt (ohne Geschwister: am Blockende)."""
    if "\r" in text:
        raise ma.MappingUnavailableError("genre_hierarchy.yaml hat Windows-Zeilenenden; zeilenweises Schreiben ist nicht möglich.")
    lines: List[List[Optional[str]]] = [[line, None] for line in text.split("\n")]
    start = next((i for i, (line, _k) in enumerate(lines) if _SECTION_START.match(line or "")), None)
    if start is None:
        raise ma.MappingUnavailableError("GENRE_HIERARCHY: nicht als eigene Zeile gefunden.")
    indent = "  "
    seen: set = set()
    for i in range(start + 1, len(lines)):
        line = lines[i][0] or ""
        if _is_filler(line):
            continue
        if not line.startswith(" "):
            break  # naechster Top-Level-Key: Blockende
        match = _ENTRY_LINE.match(line)
        if not match:
            raise ma.MappingUnavailableError(
                f"Zeile {i + 1} hat ein Format, das nicht zeilenweise geändert werden kann: {line.strip()[:60]!r}"
            )
        key = match.group("key").strip()
        if key in seen:
            raise ma.MappingUnavailableError(f"Doppelter Key in der Datei: {key!r}.")
        seen.add(key)
        lines[i][1] = key
        if len(seen) == 1:
            indent = match.group("indent")

    def index_of(key: str) -> int:
        return next(i for i, (_l, k) in enumerate(lines) if k == key)

    for genre, parent in new.items():
        if genre in current and current[genre] != parent:
            i = index_of(genre)
            match = _ENTRY_LINE.match(lines[i][0] or "")
            assert match is not None  # beim Einlesen bereits geprueft
            lines[i][0] = f"{match.group('indent')}{genre}: {'null' if parent is None else parent}{match.group('tail')}"
    for genre in current:
        if genre not in new:
            del lines[index_of(genre)]
    for genre, parent in new.items():
        if genre in current:
            continue
        siblings = [i for i, (_l, k) in enumerate(lines) if k is not None and new.get(k, "\0") == parent]
        entries = [i for i, (_l, k) in enumerate(lines) if k is not None]
        anchor = siblings[-1] if siblings else (entries[-1] if entries else start)
        lines.insert(anchor + 1, [f"{indent}{genre}: {'null' if parent is None else parent}", genre])

    patched = "\n".join(line or "" for line, _k in lines)
    # Rundlauf: was geschrieben wuerde, muss exakt dem Zielbaum entsprechen.
    if _parse_mapping(patched, "Ergebnis") != new:
        raise ma.MappingUnavailableError(
            "Die Änderung lässt sich nicht sicher zeilenweise schreiben — es wurde nichts geschrieben."
        )
    return patched


# ── Schreiben ────────────────────────────────────────────────────────────


def apply_hierarchy_update(
    payload: object, mapping_dir: Path, *, expected_etag: str, backup_dir: Optional[Path] = None,
) -> Tuple[HierarchyPlan, HierarchySaveResult]:
    descriptor = _descriptor()
    with ma.write_guard(descriptor, mapping_dir):
        plan, text, current, new = _build_plan(payload, mapping_dir)
        if plan.etag != expected_etag:
            raise ma.MappingConflictError(
                "Der Mapping-Stand wurde seit der Vorschau geändert. Bitte neu laden und erneut prüfen."
            )
        if plan.change == "unchanged":
            return plan, HierarchySaveResult(False, True, plan.entries, plan.etag)
        patched = _patch_text(text, current, new)
        ma.snapshot_before_write(descriptor, mapping_dir, backup_dir)
        ma.write_mapping_text(ma.mapping_file_path(descriptor, mapping_dir), patched)
        entries, new_etag, _warnings = get_hierarchy_state(mapping_dir)
        return plan, HierarchySaveResult(True, False, entries, new_etag)
