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

ALBUM_ISSUE_CODES = frozenset({"ALBUM_COVER_INCONSISTENT"})

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


# ─────────────────────────────────────────────────────────────────────────
# ALBUM_COVER_INCONSISTENT — Vereinheitlichung auf das beste vorhandene Cover
# ─────────────────────────────────────────────────────────────────────────


def pick_album_cover(covers: list[dict]) -> Optional[int]:
    """`covers`: je Track {"present","w","h","sha256","decodable"}.

    Rueckgabe: Index des BESTEN vorhandenen Covers (groesste kurze Kante,
    quadratisch, dekodierbar), oder None wenn kein brauchbares vorhanden
    ist. Deterministisch: Tie-Break nach Flaeche, dann sha256.
    """
    ranked = []
    for i, cv in enumerate(covers):
        if not cv.get("present") or not cv.get("decodable"):
            continue
        w, h = cv.get("w"), cv.get("h")
        if not w or not h:
            continue
        if _aspect_off(w, h) > SQUARE_TOLERANCE:
            continue
        ranked.append((min(w, h), w * h, cv.get("sha256") or "", i))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    return ranked[0][3]


def should_unify_track(track: dict, best: dict) -> tuple[str, str]:
    """(action, reason) fuer EINEN Album-Track gegen das gewaehlte
    Album-Cover. REPLACE nur, wenn der Track ein anderes und KEIN
    besseres Cover hat (nie herunterskalieren)."""
    if track.get("sha256") and track.get("sha256") == best.get("sha256"):
        return SKIP, "hat bereits das Album-Cover"
    tw, th = track.get("w"), track.get("h")
    bw, bh = best.get("w"), best.get("h")
    if not track.get("present"):
        return REPLACE, "Album-Cover ergaenzt"
    if tw and th and bw and bh and min(tw, th) > min(bw, bh):
        return SKIP, f"Track-Cover {tw}x{th} groesser als Album-Cover {bw}x{bh}"
    return REPLACE, f"auf Album-Cover {bw}x{bh} vereinheitlicht"
