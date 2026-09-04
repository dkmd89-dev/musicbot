# services/library_repair/external_metadata.py
# -*- coding: utf-8 -*-
"""
Level-3 (EXTERNAL_METADATA) — fehlende MusicBrainz-IDs / ISRC nachtragen.

Reine Entscheidungslogik (kein Netzwerk, kein Dateisystem): aus dem
aktuellen Tag-Zustand + einem MusicBrainz-Match-Ergebnis wird bestimmt,
WELCHE freeform-Atome ergaenzt werden.

Grundregel (Prompt Abschnitt 8): kein blindes Ueberschreiben. Nur
FEHLENDE IDs werden ergaenzt, und nur wenn der Match eindeutig ist — die
Eindeutigkeit prueft bereits `MusicBrainzClient._get_best_match()`
(Config.MUSICBRAINZ_MIN_SIMILARITY / MIN_ARTIST_SIMILARITY, MB-01-Fix):
kein sicherer Treffer -> leeres Ergebnis -> hier nichts zu tun.
"""

from __future__ import annotations

import re
from typing import Optional

# Atom-Namen deckungsgleich zu services/metadata/tag_writer.py::_mb_tag_map
ATOM = {
    "recording_id": "----:com.apple.iTunes:MusicBrainz Recording Id",
    "artist_id": "----:com.apple.iTunes:MusicBrainz Artist Id",
    "release_id": "----:com.apple.iTunes:MusicBrainz Release Id",
    "release_group_id": "----:com.apple.iTunes:MusicBrainz Release Group Id",
    "isrc": "----:com.apple.iTunes:ISRC",
}

HANDLED_ISSUE_CODES = frozenset({
    "META_MB_RECORDING_MISSING",
    "META_MB_RELEASE_MISSING",
    "META_ISRC_MISSING",
})

_MBID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_ISRC_RE = re.compile(r"^[A-Za-z]{2}[A-Za-z0-9]{3}\d{7}$")


def _blank(v) -> bool:
    return v is None or not str(v).strip()


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def title_is_trustworthy(file_title: str) -> bool:
    """Belt-and-suspenders zusaetzlich zur MB-Schwelle: offensichtlich
    unsaubere/geparste Titel (Produzenten-Credit, dateinamens-illegale
    Zeichen, absurde Laenge) NICHT fuer eine externe ID-Zuordnung nutzen —
    dann lieber gar keine ID als eine falsche."""
    if _blank(file_title):
        return False
    t = file_title.strip()
    if len(t) > 120:
        return False
    if re.search(r"\bprod\.?\b|\bremix\b.*\bremix\b", t, re.IGNORECASE):
        return False
    if re.search(r'[<>:"/\\|?*]', t):
        return False
    return True


def plan_id_writes(current: dict, mb_result: dict, *, file_title: str = "") -> dict[str, list[str]]:
    """`current`: {id_key -> vorhandener Wert | None}. `mb_result`:
    Rueckgabe von MusicBrainzClient.fetch_metadata() (leer = kein Match).

    Rueckgabe: {atom_name -> [wert]} nur fuer FEHLENDE Felder mit gueltigem
    MB-Wert. Leeres Dict = nichts zu tun.
    """
    if not mb_result:
        return {}
    if file_title and not title_is_trustworthy(file_title):
        return {}
    # zusaetzliche Plausibilitaet: der MB-Titel muss zum Datei-Titel passen
    mb_title = mb_result.get("title") or ""
    if file_title and mb_title:
        ft, mt = _norm_title(file_title), _norm_title(mb_title)
        if ft and mt and not (ft in mt or mt in ft or _token_overlap(ft, mt) >= 0.6):
            return {}

    writes: dict[str, list[str]] = {}
    for key in ("recording_id", "artist_id", "release_id", "release_group_id", "isrc"):
        if not _blank(current.get(key)):
            continue
        val = mb_result.get(key)
        if _blank(val):
            continue
        val = str(val).strip()
        if key == "isrc":
            if not _ISRC_RE.match(val):
                continue
        elif not _MBID_RE.match(val):
            continue
        writes[ATOM[key]] = [val]
    return writes


def _token_overlap(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(len(sa), len(sb))
