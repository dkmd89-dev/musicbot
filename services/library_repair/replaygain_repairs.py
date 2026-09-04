# services/library_repair/replaygain_repairs.py
# -*- coding: utf-8 -*-
"""
Reine Berechnung des ReplayGain-Tags fuer den Loudness-Executor.

Kein I/O, kein FFmpeg. Der Executor schreibt daraus zwei Freeform-Atome
(`----:com.apple.iTunes:replaygain_track_gain` / `_peak`) — das Audio bleibt
byte-identisch. Ein ReplayGain-fähiger Player (Navidrome) bringt die Datei
damit auf die Ziel-Lautheit, **ohne** verlustbehaftetes Re-Encode.

**Referenz = −16 LUFS** (= `AudioEnhancer.TARGET_LUFS['music']`, bewusst
nicht importiert), NICHT die ReplayGain-2.0-Norm −18: die MusicBot-Download-
Pipeline normalisiert frische Downloads per FFmpeg-loudnorm auf −16 und
schreibt dabei KEINEN RG-Tag. Damit ein getaggter Altbestand in Navidrome
genauso laut klingt wie diese ungetaggten Dateien, muss der Gain auf −16
referenzieren.
"""

from __future__ import annotations

import re
from typing import Optional

TARGET_LUFS = -16.0

# > diese Abweichung (dB) vom Ziel → RG-Tag schreiben. Deckungsgleich zur
# Melde-Schwelle des Scanners (LOUDNESS_OFF_TARGET_DB).
TOLERANCE_DB = 2.0

GAIN_ATOM = "----:com.apple.iTunes:replaygain_track_gain"
PEAK_ATOM = "----:com.apple.iTunes:replaygain_track_peak"
# Weitere RG-Atome, die beim CLEAR mit entfernt werden (falls vorhanden).
_RG_ATOMS_ALL = (
    GAIN_ATOM, PEAK_ATOM,
    "----:com.apple.iTunes:replaygain_album_gain",
    "----:com.apple.iTunes:replaygain_album_peak",
    "----:com.apple.iTunes:replaygain_reference_loudness",
)

HANDLED_ISSUE_CODES = frozenset({"LOUDNESS_OFF_TARGET"})

SET = "SET"
CLEAR = "CLEAR"

_GAIN_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:dB)?\s*$", re.IGNORECASE)


def parse_gain_db(value) -> Optional[float]:
    """`'-4.80 dB'` / `'-4.8'` / `'3'` → float; sonst None."""
    if value is None:
        return None
    m = _GAIN_RE.match(str(value))
    return float(m.group(1)) if m else None


def effective_lufs(measured_lufs: Optional[float], gain_db: Optional[float]) -> Optional[float]:
    """Wie laut die Datei nach Anwendung eines vorhandenen RG-Gains
    tatsächlich klingt (measured + gain)."""
    if measured_lufs is None:
        return None
    return measured_lufs + (gain_db or 0.0)


def _peak_linear_from_dbtp(true_peak_dbtp: Optional[float]) -> float:
    """dBTP → linearer Peak (ReplayGain-Peak-Konvention: 1.0 = 0 dBFS).
    Bei fehlendem Wert konservativ 1.0."""
    if true_peak_dbtp is None:
        return 1.0
    return round(10.0 ** (true_peak_dbtp / 20.0), 6)


def compute_replaygain(
    measured_lufs: Optional[float],
    true_peak_dbtp: Optional[float] = None,
    *,
    existing_gain_db: Optional[float] = None,
    target: float = TARGET_LUFS,
    tolerance: float = TOLERANCE_DB,
) -> tuple[Optional[str], Optional[dict[str, list[str]]]]:
    """Entscheidet, was mit dem ReplayGain-Tag zu tun ist. Rückgabe:

      (SET, {atome})  — den berechneten Track-Gain-/Peak-Tag schreiben
      (CLEAR, None)   — vorhandene RG-Atome entfernen (die Datei liegt bereits
                        auf Ziel, trägt aber einen abweichenden Gain-Tag, der
                        einen RG-Player fehlleiten würde)
      (None, None)    — nichts zu tun

    `existing_gain_db` = aktuell im Tag stehender `replaygain_track_gain`
    (None = kein Tag). Ein RG-fähiger Player spielt die Datei bei
    `measured_lufs + (existing_gain_db oder 0)`; Ziel ist `target`."""
    if measured_lufs is None:
        return None, None

    target_gain = target - measured_lufs
    current_gain = existing_gain_db if existing_gain_db is not None else 0.0

    # Zustand ist bereits gut genug?
    if abs(target_gain - current_gain) <= tolerance:
        return None, None

    # Die Datei selbst liegt auf Ziel (target_gain ~ 0), trägt aber einen
    # anderslautenden Gain-Tag → Tag muss weg statt „auf 0" geschrieben zu
    # werden (ungetaggt = so laut wie die Neu-Downloads).
    if abs(target_gain) <= tolerance and existing_gain_db is not None:
        return CLEAR, None

    return SET, {
        GAIN_ATOM: [f"{target_gain:.2f} dB"],
        PEAK_ATOM: [f"{_peak_linear_from_dbtp(true_peak_dbtp):.6f}"],
    }
