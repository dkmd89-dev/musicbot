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

Kein Dateisystem-Zugriff ausser dem Lesen von artist_genre.yaml; keine
Mutagen-/Backup-/Journal-Logik (siehe executor.py, ARCH-031 B.3).
`--update-manual-mapping` (Schreiben von artist_genre.yaml selbst) ist
bewusst NICHT hier: CLI-only-Vorgang, siehe ARCH-031 A.4.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

CANONICAL_GENRE_ATOM = "\xa9gen"
LEGACY_GENRE_ATOM = "----:com.apple.iTunes:GENRE"


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
