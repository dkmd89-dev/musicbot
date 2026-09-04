# services/library_repair/cover_repairs.py
# -*- coding: utf-8 -*-
"""
Cover-Reparatur — reine Entscheidungslogik (Prompt Abschnitt 9).

Bestimmt aus (aktuellem Cover-Zustand, gefundenem Kandidaten-Cover), ob und
wie ersetzt wird — KEIN Netzwerk, KEIN Dateisystem. Die Cover-Suche selbst
macht der bestehende `services/metadata/cover_processor.py::CoverProcessor`
(vom executor injiziert).

Grundregel (Prompt Abschnitt 9): „Reparatur darf nur erfolgen, wenn ein
besseres bzw. eindeutig passendes Cover gefunden wurde. Nicht einfach
vorhandene Cover überschreiben."
"""

from __future__ import annotations

from typing import Optional

# gleiche Schwellen wie services/library_health/file_analysis.py
MIN_EDGE_PX = 400
SQUARE_TOLERANCE = 0.05
# ein Ersatz bei LOW_RESOLUTION lohnt nur bei einem SPUERBAREN Zugewinn
MIN_LOW_RES_IMPROVEMENT_PX = 200

HANDLED_ISSUE_CODES = frozenset({
    "ARTWORK_MISSING",
    "ARTWORK_INVALID",
    "ARTWORK_LOW_RESOLUTION",
    "ARTWORK_NON_SQUARE",
})

# ADD / REPLACE / SKIP
ADD = "ADD"
REPLACE = "REPLACE"
SKIP = "SKIP"


def _aspect_off(w: int, h: int) -> float:
    return abs(w - h) / max(w, h)


def decide_cover_action(
    issue_code: str,
    *,
    current_present: bool,
    current_state: str,                 # AnalysisState-Wert: PRESENT/MISSING/INVALID/...
    current_w: Optional[int],
    current_h: Optional[int],
    candidate_w: Optional[int],
    candidate_h: Optional[int],
) -> tuple[str, str]:
    """(action, reason). action == SKIP heisst: bestehendes Cover behalten."""
    if not candidate_w or not candidate_h:
        return SKIP, "kein Kandidaten-Cover gefunden / nicht dekodierbar"

    cand_min = min(candidate_w, candidate_h)
    cand_square = _aspect_off(candidate_w, candidate_h) <= SQUARE_TOLERANCE

    # Ein Ersatz-Cover muss immer die Mindestanforderungen erfuellen.
    if cand_min < MIN_EDGE_PX:
        return SKIP, f"Kandidat {candidate_w}x{candidate_h} unter {MIN_EDGE_PX}px"
    if not cand_square:
        return SKIP, f"Kandidat {candidate_w}x{candidate_h} nicht quadratisch"

    if issue_code in ("ARTWORK_MISSING", "ARTWORK_INVALID"):
        if not current_present or current_state in ("MISSING", "INVALID"):
            return ADD, f"Cover ergaenzt ({candidate_w}x{candidate_h})"
        return SKIP, "Cover inzwischen vorhanden"

    # ab hier existiert bereits ein (dekodierbares) Cover
    if current_w is None or current_h is None:
        return SKIP, "aktuelle Cover-Groesse unbekannt — kein sicherer Vergleich"
    cur_min = min(current_w, current_h)

    if issue_code == "ARTWORK_LOW_RESOLUTION":
        if cand_min >= max(cur_min + MIN_LOW_RES_IMPROVEMENT_PX, MIN_EDGE_PX):
            return REPLACE, (f"hoehere Aufloesung {candidate_w}x{candidate_h} "
                             f"statt {current_w}x{current_h}")
        return SKIP, f"Kandidat {candidate_w}x{candidate_h} nicht deutlich besser"

    if issue_code == "ARTWORK_NON_SQUARE":
        # quadratischer Kandidat, aber kein Aufloesungsverlust
        if cand_min >= cur_min:
            return REPLACE, (f"quadratisches Cover {candidate_w}x{candidate_h} "
                             f"statt {current_w}x{current_h}")
        return SKIP, f"quadratischer Kandidat {candidate_w}x{candidate_h} kleiner als aktuell"

    return SKIP, f"kein Cover-Repair fuer {issue_code}"
