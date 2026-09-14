# services/library_repair/artist.py
# -*- coding: utf-8 -*-
"""
Library-Maintenance — Artist-Domain-Logik (ARCH-032 Phase 1).

Reine Funktionen: Casing-Normalisierung von Artist-Namen (©ART/ARTISTS)
gegen mapping/artist_overrides.json / mapping/case_preserve.yaml.

Extrahiert aus scripts/fix_artist_casing.py (ARCH-031 Migrationsplan
Phase 1) — Verhalten unveraendert:
  - NUR reine Casing-Mappings (key.casefold() == value.casefold())
  - keine Namens-Erweiterungen (z. B. "miksu" -> "Miksu & Macloud" bleibt
    Aufgabe des ArtistIdentityResolver, nicht dieses Moduls — andere
    Fragestellung: Identitaetsentscheidung zur Download-Zeit vs.
    Casing-Konsistenz bereits geschriebener Dateien, ARCH-031 B.1)

Kein Dateisystem-Zugriff ausser dem Lesen der beiden Mapping-Dateien;
keine Mutagen-/Backup-/Journal-Logik (die gehoert nach executor.py,
ARCH-031 B.3). Bewusst kein Import von services.metadata/
ArtistIdentityResolver — Praezedenz: tag_repairs.py's leichtgewichtige
Nachbildung von split_main_and_featuring() statt schwerer Importkette.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple


def load_casing_map(mapping_dir: Path) -> Dict[str, str]:
    """Liest case_preserve.yaml (Fallback) + artist_overrides.json
    (ueberschreibt, gleiche Datei wie ArtistIdentityResolver/
    Config.ARTIST_OVERRIDE_FILE) aus `mapping_dir` (z. B.
    Config.GENRE_MAPPING_DIR) und liefert {casefold(name): canonical_name}
    fuer reine Casing-Mappings. Identische Semantik zu
    scripts/fix_artist_casing.py::load_casing_map()."""
    m: Dict[str, str] = {}

    cp_path = mapping_dir / "case_preserve.yaml"
    if cp_path.exists():
        import yaml

        data = yaml.safe_load(cp_path.read_text(encoding="utf-8")) or {}
        for k, v in (data.get("case_preserve") or {}).items():
            if isinstance(k, str) and isinstance(v, str):
                if k.casefold() == v.casefold():
                    m[k.casefold()] = v

    ao_path = mapping_dir / "artist_overrides.json"
    if ao_path.exists():
        data = json.loads(ao_path.read_text(encoding="utf-8")) or {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                if k.casefold() == v.casefold():
                    m[k.casefold()] = v

    return m


def _to_str(x) -> str:
    if isinstance(x, bytes):
        return x.decode("utf-8", errors="replace")
    return str(x)


def normalize_values(
    values: List, casing_map: Dict[str, str]
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Wendet die Casing-Map auf eine Liste von Tag-Werten an (©ART- oder
    ARTISTS-Freeform-Werte, wie von mutagen gelesen). Liefert
    (neue_werte, [(alt, neu), ...] nur fuer tatsaechlich geaenderte
    Eintraege). Identische Semantik zu
    scripts/fix_artist_casing.py::normalize_values()."""
    new: List[str] = []
    changes: List[Tuple[str, str]] = []
    for v in values:
        s = _to_str(v)
        canon = casing_map.get(s.casefold())
        if canon and canon != s:
            new.append(canon)
            changes.append((s, canon))
        else:
            new.append(s)
    return new, changes
