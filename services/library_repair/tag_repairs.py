# services/library_repair/tag_repairs.py
# -*- coding: utf-8 -*-
"""
Level-1 (SAFE_AUTOMATIC) Tag-Reparaturen — reine Funktionen.

(aktuelle Tag-Werte) -> (neue Tag-Werte) | None

`None` heisst „keine sichere/eindeutige Reparatur" (Prompt Abschnitt 6:
„Keine Änderung durchführen, wenn das Ergebnis nicht eindeutig ist").
Kein Dateisystem-Zugriff — die I/O macht executor.py.

Bewusst KEIN Rename hier (Prompt Abschnitt 7/14): Level-1-Dateinamen-
korrekturen sind ein separater, eigener Schritt mit der Rename-Safety-
Maschinerie.

Die Multi-Artist-Split-Logik spiegelt bewusst
services/metadata/models.py::split_main_and_featuring() (dieselben
Trenner, dieselbe Reihenfolge) — lokale, import-leichte Nachbildung wie
services/duplicate/classification.py gegenüber detector.py, damit dieses
Modul ohne die schwere services.metadata-Importkette unit-testbar bleibt.
"""

from __future__ import annotations

import re
from typing import Optional

_GENRE_OLD_SEP = " / "
_GENRE_NEW_SEP = "; "

# Deckungsgleich zu split_main_and_featuring(): feat/ft/featuring/with,
# dann ','/'&'/'und'/'and'.
_FEAT_KEYWORD = re.compile(r"\s*\b(?:feat\b\.?|ft\b\.?|featuring\b|with\b)\s+(.+)$", re.IGNORECASE)
_ARTIST_SPLIT = re.compile(r"\s*[,&]\s*|\s+(?:und|and)\s+", re.IGNORECASE)


def split_joined_artist(value: str) -> list[str]:
    """'makko & toobrokeforfiji'      -> ['makko', 'toobrokeforfiji']
       'makko feat. X & Y'            -> ['makko', 'X', 'Y']
       'makko'                        -> ['makko']"""
    value = (value or "").strip()
    if not value:
        return []
    m = _FEAT_KEYWORD.search(value)
    if m:
        main = value[: m.start()].strip()
        feats = [a.strip() for a in _ARTIST_SPLIT.split(m.group(1)) if a.strip()]
        return ([main] if main else []) + feats
    parts = [p.strip() for p in _ARTIST_SPLIT.split(value) if p.strip()]
    return parts or [value]


def _dedupe_ci(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        k = v.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(v.strip())
    return out


# ─────────────────────────────────────────────────────────────────────────
# GENRE_DELIMITER_INCONSISTENT
# ─────────────────────────────────────────────────────────────────────────


def repair_genre_delimiter(genre: Optional[str]) -> Optional[str]:
    """' / ' -> '; ' (nur wenn eindeutig: altes Trennzeichen vorhanden,
    neues nicht). Kein Wertverlust, deterministisch."""
    if not genre or _GENRE_OLD_SEP not in genre or _GENRE_NEW_SEP in genre:
        return None
    parts = [p.strip() for p in genre.split(_GENRE_OLD_SEP) if p.strip()]
    if len(parts) < 2:
        return None
    new = _GENRE_NEW_SEP.join(parts)
    return new if new != genre else None


# ─────────────────────────────────────────────────────────────────────────
# MULTI_ARTIST_*  ->  (neue ©ART-Liste, neue ARTISTS-Freeform-Liste)
# ─────────────────────────────────────────────────────────────────────────


def repair_multi_artist(
    primary_values: list[str],
    freeform_values: list[str],
) -> Optional[tuple[list[str], list[str]]]:
    """Bringt ©ART und das ARTISTS-Freeform-Atom in den kanonischen Zustand:
    beide dieselbe, dedupte, als SEPARATE Werte gespeicherte Artist-Liste
    (MusicBot-Regel, Prompt Abschnitt 7/„Multi-Artist"). Reihenfolge des
    Haupt-Artists bleibt erhalten.

    Rückgabe None, wenn nichts zu tun ist ODER das Ergebnis nicht eindeutig
    bestimmbar ist.
    """
    primary_values = [v for v in (primary_values or []) if v and v.strip()]
    freeform_values = [v for v in (freeform_values or []) if v and v.strip()]
    if not primary_values:
        return None

    # (a) ©ART als EIN zusammengeklebter String -> aufsplitten
    if len(primary_values) == 1:
        split = split_joined_artist(primary_values[0])
    else:
        split = list(primary_values)
    split = _dedupe_ci(split)

    # (b) Freeform als Referenz nehmen, wenn es eine plausible, mit dem
    #     ©ART-Split deckungsgleiche Menge ist (nur Reihenfolge/Trenner
    #     unterschieden). Sonst den ©ART-Split verwenden.
    ff = _dedupe_ci(freeform_values)
    if ff and {a.lower() for a in ff} == {a.lower() for a in split}:
        canonical = ff if len(ff) >= len(split) else split
    elif ff and not split[1:] and len(ff) > 1:
        # ©ART war nur ein Name, Freeform hat mehr -> Freeform ist reicher
        canonical = ff
    else:
        canonical = split

    if len(canonical) < 1:
        return None

    new_primary = canonical
    # Bei genau einem Artist das ARTISTS-Freeform-Atom nicht erzwingen —
    # nur eine vorhandene Dublette darin bereinigen (kein Zwangs-Entfernen,
    # das nur unnoetige Schreibvorgaenge erzeugt).
    new_freeform = canonical if len(canonical) > 1 else _dedupe_ci(freeform_values)

    unchanged = (
        new_primary == primary_values
        and new_freeform == freeform_values
    )
    return None if unchanged else (new_primary, new_freeform)


# ─────────────────────────────────────────────────────────────────────────
# META_ALBUM_ARTIST_MISSING / ALBUM_ARTIST_INCONSISTENT
# ─────────────────────────────────────────────────────────────────────────


def repair_album_artist(
    current_album_artist: Optional[str],
    primary_values: list[str],
    *,
    directory_artist: Optional[str] = None,
) -> Optional[str]:
    """Album-Artist = Haupt-Artist des Tracks (bzw. der Verzeichnis-Artist,
    wenn angegeben und plausibel). Deterministisch."""
    primary_values = [v for v in (primary_values or []) if v and v.strip()]
    target = None
    if directory_artist and directory_artist.strip():
        target = directory_artist.strip()
    elif primary_values:
        target = primary_values[0].strip()
    if not target:
        return None
    if current_album_artist and current_album_artist.strip().lower() == target.lower():
        return None
    return target
