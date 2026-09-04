# services/library_repair/rename_repairs.py
# -*- coding: utf-8 -*-
"""
Level-1 Dateinamen-Reparaturen — reine Funktionen (Namensberechnung, KEIN I/O).

(aktueller Dateiname + Tag-/Struktur-Kontext) -> neuer Dateiname | None

`None` = keine sichere/eindeutige Umbenennung (Prompt Abschnitt 6/7/14).
Umbenennung ausschliesslich INNERHALB desselben Verzeichnisses (der neue
Name enthaelt nie einen Pfadseparator).

Namenskonvention gespiegelt aus utils/filenamefixer.py::build_final_path()
(dort NICHT veraendert):
    Singles-Ordner :  "{Jahr} - {Titel}.{ext}"
    Album-Ordner   :  "{NN} - {Titel}.{ext}"
    Compilations/Playlist: "{Artist} - {Titel}.{ext}"
"""

from __future__ import annotations

import re
from typing import Optional

from utils.helpers import sanitize_filename
from utils.regex import ILLEGAL_CHARS_PATTERN

# Fuehrender Struktur-Praefix eines bestehenden Dateinamen-Stamms:
#   "03 - Titel"    "2021 - Titel"    "Artist - Titel"
_PREFIX = re.compile(r"^(?:\d{2,4}|.+?)\s+-\s+", re.IGNORECASE)
_WS = re.compile(r"\s+")
# Reiner Zusatz am Titel-Ende, den die Download-Pipeline ebenfalls entfernt:
#   " prod. X" / " (prod. X)" / " feat. X" / " (feat. X)"
_TRAILING_CRUFT = re.compile(
    r"\s*(?:\(?\s*(?:prod\.?|feat\.?|ft\.?|featuring)\b.*|\(.*\))\s*$",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    return _WS.sub(" ", ILLEGAL_CHARS_PATTERN.sub("", text or "")).strip().lower()


def repair_suspicious_filename(stem: str, extension: str) -> Optional[str]:
    """Doppelte Leerzeichen / illegale Zeichen / Randwhitespace bereinigen —
    rein deterministisch, keine semantische aenderung."""
    new_stem = sanitize_filename(stem)
    if not new_stem or new_stem == stem:
        return None
    return f"{new_stem}{extension}"


def repair_filename_title_mismatch(
    *,
    stem: str,
    extension: str,
    title: Optional[str],
    year: Optional[str] = None,          # nur Kompat., ungenutzt
    track_number: Optional[int] = None,  # nur Kompat., ungenutzt
    is_singles: bool = False,            # nur Kompat., ungenutzt
    library_section: str = "music",
) -> Optional[str]:
    """Ersetzt AUSSCHLIESSLICH den Titel-Teil des bestehenden Dateinamens
    durch den (sanitisierten) Titel-Tag und LAeSST DEN VORHANDENEN
    STRUKTUR-PRAeFIX ('NN - ' bzw. 'YYYY - ') unveraendert.

    Bewusst KEINE Neuberechnung des Praefixes aus einer geratenen
    Ordner-Konvention (realer Fehlerfall im Finalaudit: eine als Album
    klassifizierte Single haette '2025 - Titel' faelschlich zu '01 - Titel'
    gemacht). Der Scanner meldet FILENAME_TITLE_MISMATCH fuer den
    Titel-Teil — genau der wird korrigiert.

    Sicherheits-Leitplanke (gegen einen Tag-Tippfehler): der bestehende
    Titel-Teil muss den Titel-Tag als Praefix enthalten und sich nur durch
    abschliessenden Zusatz (prod./feat./geschlossene Klammer) davon
    unterscheiden. Andernfalls -> None (Manual Review).
    """
    if not title or not title.strip():
        return None
    if ILLEGAL_CHARS_PATTERN.search(title):
        return None  # "nicht raten"
    if library_section in ("compilations", "playlist"):
        return None  # "Artist - Titel" — Artist-Teil hier nicht sicher rekonstruierbar

    m = _PREFIX.match(stem)
    prefix = m.group(0) if m else ""
    title_part = stem[len(prefix):]

    tp_n, title_n = _norm(title_part), _norm(title)
    if tp_n == title_n:
        return None  # Titel-Teil bereits korrekt
    stripped_tp_n = _norm(_TRAILING_CRUFT.sub("", title_part))
    if not (tp_n.startswith(title_n) or stripped_tp_n == title_n):
        return None  # nicht nur additiver Zusatz -> unsicher

    clean_title = sanitize_filename(title)
    if not clean_title:
        return None
    new_stem = f"{prefix}{clean_title}"
    if new_stem == stem:
        return None
    return f"{new_stem}{extension}"
