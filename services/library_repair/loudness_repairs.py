# services/library_repair/loudness_repairs.py
# -*- coding: utf-8 -*-
"""
Reine Entscheidungslogik fuer den Loudness-Executor (Level LOUDNESS).

Kein I/O, kein FFmpeg — nur die Frage „muss diese Datei neu codiert
werden, und war das Ergebnis danach korrekt?". Die eigentliche
Normalisierung macht `utils/audio_enhancer.py::AudioEnhancer.
normalize_loudness()` (verlustbehaftetes AAC-Re-Encode), die Messung der
Scanner (`services/library_health/tag_reader.py::measure_loudness`).

Ziel-Lautheit `-16.0 LUFS` = `AudioEnhancer.TARGET_LUFS['music']`
(bewusst nicht importiert — dieses Modul bleibt abhaengigkeitsfrei).
"""

from __future__ import annotations

from typing import Optional

TARGET_LUFS = -16.0

# Toleranz fuer die FIX-Entscheidung — enger als die Melde-Schwelle des
# Scanners (LOUDNESS_OFF_TARGET_DB = 2.0). Wer schon gemeldet wurde, ist
# > 2 dB daneben; hier wird jede Datei > 1 dB daneben tatsaechlich
# normalisiert (deckungsgleich zur Absicht von
# scripts/normalize_test_library_loudness.py, dort LUFS_TOLERANCE = 0.5 —
# hier bewusst etwas grosszuegiger, um marginale Re-Encodes zu vermeiden).
FIX_TOLERANCE_DB = 1.0

# Nach dem Re-Encode muss die neue Messung so nah am Ziel liegen. loudnorm
# trifft in der Praxis ~0.1–0.5 dB; 1.5 dB Rest-Abweichung ist noch ok,
# alles darueber gilt als fehlgeschlagene Normalisierung → Rollback.
POST_TOLERANCE_DB = 1.5

# Groesste erlaubte Laufzeit-Abweichung nach dem Re-Encode (Frame-Grenzen /
# Encoder-Delay). Darueber → Rollback (die Datei wurde beschnitten/verlaengert).
MAX_DURATION_DELTA_SECONDS = 1.0

HANDLED_ISSUE_CODES = frozenset({"LOUDNESS_OFF_TARGET"})

NORMALIZE = "NORMALIZE"
SKIP = "SKIP"


def decide_loudness_action(
    current_lufs: Optional[float],
    *,
    target: float = TARGET_LUFS,
    tolerance: float = FIX_TOLERANCE_DB,
) -> tuple[str, str]:
    """NORMALIZE, wenn die gemessene Lautheit mehr als `tolerance` dB vom
    Ziel abweicht, sonst SKIP. Ohne Messung immer SKIP („nicht raten")."""
    if current_lufs is None:
        return SKIP, "keine LUFS-Messung vorhanden"
    delta = current_lufs - target
    if abs(delta) <= tolerance:
        return SKIP, f"bereits auf Ziel ({current_lufs:.1f} LUFS, {delta:+.1f} dB)"
    return (
        NORMALIZE,
        f"{current_lufs:.1f} LUFS ({delta:+.1f} dB) → Neucodierung auf {target:.0f} LUFS",
    )


def verify_normalized(
    after_lufs: Optional[float],
    duration_before: Optional[float],
    duration_after: Optional[float],
    *,
    target: float = TARGET_LUFS,
) -> tuple[bool, str]:
    """Prueft das Ergebnis eines Re-Encodes: Lautheit jetzt am Ziel UND
    Laufzeit praktisch unveraendert. Gibt (ok, Begruendung) zurueck."""
    if after_lufs is None:
        return False, "Lautheit nach dem Re-Encode nicht messbar"
    delta = after_lufs - target
    if abs(delta) > POST_TOLERANCE_DB:
        return False, (
            f"Lautheit nach Re-Encode weiterhin daneben "
            f"({after_lufs:.1f} LUFS, {delta:+.1f} dB > {POST_TOLERANCE_DB})"
        )
    if duration_before is not None and duration_after is not None:
        dd = abs(duration_after - duration_before)
        if dd > MAX_DURATION_DELTA_SECONDS:
            return False, (
                f"Laufzeit-Abweichung nach Re-Encode {dd:.2f}s "
                f"(> {MAX_DURATION_DELTA_SECONDS}s) — Datei beschnitten/verlaengert"
            )
    return True, f"{after_lufs:.1f} LUFS ({delta:+.1f} dB)"
