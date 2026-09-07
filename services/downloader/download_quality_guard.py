# services/downloader/download_quality_guard.py
# -*- coding: utf-8 -*-
"""
Phase 3, P2.3 (Bad Download Detector) — Stufe A: rein beobachtende
Qualitätsprüfung der frisch heruntergeladenen Rohdatei, VOR der
Metadaten-Pipeline. Loggt auffällige Dauer/Bitrate, greift aber NICHT in
die Pipeline ein — kein Reject, kein Abbruch, die Datei durchläuft in
jedem Fall die volle Metadaten-Pipeline wie bisher.

Bewusst OHNE Import von services/library_health: der Health-Scanner ist
ein read-only Diagnose-Werkzeug für die bereits gespeicherte Library
(eigene Test-Garantie `test_scanner_import_graph_has_no_writer_modules`,
eigener Lebenszyklus) — eine Kopplung des P0-Download-Pfads an dieses
Paket würde diese Grenze unnötig aufweichen, nur um einen kleinen
ffprobe-Aufruf zu sparen. Sollte künftig ein dritter Aufrufer für dieselbe
Logik entstehen, ist eine Extraktion nach `utils/` (CLAUDE.md Abschnitt 4)
der richtige Zeitpunkt (Rule of Three) — aktuell mit nur diesem einen
Gate-Fall wäre das vorzeitige Abstraktion.

WICHTIG — Health-Threshold ≠ Reject-Threshold: Die unten definierten
Schwellenwerte entscheiden NUR, was in dieser Beobachtungsphase (Stufe A)
als "auffällig genug für einen Log-Hinweis" gilt. Sie beantworten eine
andere Frage als die Health-Scanner-Schwellen (dort: "ist eine bereits in
der Library liegende, unveränderliche Datei diagnostisch auffällig?") und
sind bewusst eigenständig benannt, nicht aus
`services/library_health/file_analysis.py` importiert — auch wenn sie zum
Zeitpunkt dieser Änderung zufällig denselben Ausgangswerten entsprechen.
Sie sind KEINE Vorwegnahme eines künftigen Stufe-B-Reject-Schwellenwerts:
ein eventuelles Stufe-B-Gate braucht eigene, aus den hier über einen
Beobachtungszeitraum gesammelten realen Daten abgeleitete Werte und ein
separates, explizites Nutzer-Go (siehe Phase-3-Plan, P2.3).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from logger import get_module_logger

logger = get_module_logger("DownloadQualityGuard")

# Unverbindlicher Ausgangspunkt für die Beobachtungsphase (Stufe A) —
# siehe Modul-Docstring: kein Anspruch, für DIESEN Zweck bereits
# kalibriert zu sein (anders als die Health-Scanner-Werte, die gegen die
# reale Produktionslibrary kalibriert wurden).
OBSERVE_MIN_BITRATE_BPS = 128_000
OBSERVE_MIN_DURATION_SECONDS = 20.0
# Download-spezifisches Signal ohne Health-Scanner-Pendant: eine Datei,
# die deutlich kürzer ist als die vom Quell-Anbieter gemeldete Dauer,
# deutet auf einen abgebrochenen/verstümmelten Download hin.
OBSERVE_DURATION_MISMATCH_RATIO = 0.5


@dataclass
class QualityObservation:
    """Ergebnis einer Stufe-A-Beobachtung — rein informativ, löst selbst
    keine Aktion aus."""

    path: str
    duration_seconds: Optional[float]
    bitrate: Optional[int]
    expected_duration_seconds: Optional[float]
    flags: List[str] = field(default_factory=list)

    @property
    def suspicious(self) -> bool:
        return bool(self.flags)


def _probe_duration_and_bitrate(
    path: Path, timeout: int = 30
) -> Tuple[Optional[float], Optional[int]]:
    """Minimaler, lokaler ffprobe-Aufruf — liest NUR Dauer + Bitrate aus
    dem Format-Container (deutlich schmaler als
    services/library_health/tag_reader.py::probe_stream(), das zusätzlich
    Codec/Kanäle/Korruptionserkennung liefert, hier aber nicht gebraucht
    wird). Bei jedem Fehler (Timeout, fehlendes ffprobe, kaputte/leere
    Datei, unerwartetes JSON) `(None, None)` — read-only, wirft nie."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, timeout=timeout,
        )
        if result.returncode != 0:
            return None, None
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        fmt = data.get("format", {})
        duration = float(fmt["duration"]) if fmt.get("duration") else None
        bitrate = int(fmt["bit_rate"]) if fmt.get("bit_rate") else None
        return duration, bitrate
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError,
            json.JSONDecodeError):
        return None, None


def _fmt(value, unit: str = "", decimals: Optional[int] = None) -> str:
    """Einheitliche 'N/A'-Konvention fuer fehlende Analysewerte im Log
    (etabliertes Muster, siehe docs/FINDINGS_INDEX.md zu
    download_result_reporter.py::build_final_summary_message())."""
    if value is None:
        return "N/A"
    if decimals is not None:
        return f"{value:.{decimals}f}{unit}"
    return f"{value}{unit}"


def check_download_quality(
    path: Path, expected_duration: Optional[float] = None
) -> QualityObservation:
    """Reine Beobachtung (Stufe A) — liest Dauer/Bitrate der fertigen
    Download-Datei per ffprobe und markiert Auffälligkeiten per Log.
    Greift NICHT in die Pipeline ein: der Rückgabewert wird von den
    Aufrufstellen bewusst nur geloggt, nie zur Ablehnung verwendet.

    Loggt IMMER einen Start- und einen Abschluss-Log (Status OK/
    SUSPICIOUS/PROBE_FAILED) - unabhängig vom Ergebnis. Vorher war bei
    einem unauffälligen Download (keine Flags) im Log nicht erkennbar,
    ob der Detector überhaupt gelaufen ist oder ob er nie aufgerufen
    wurde. Reine Logging-Ergänzung - die Bewertungslogik selbst
    (Schwellenwerte, Flags) ist unverändert."""
    logger.info(f"[QUALITY-CHECK] Bad Download Detector gestartet: {path}")

    duration, bitrate = _probe_duration_and_bitrate(Path(path))
    flags: List[str] = []

    if duration is not None and duration < OBSERVE_MIN_DURATION_SECONDS:
        flags.append(
            f"sehr kurz ({duration:.1f}s < {OBSERVE_MIN_DURATION_SECONDS:.0f}s)"
        )

    if bitrate is not None and bitrate < OBSERVE_MIN_BITRATE_BPS:
        flags.append(
            f"niedrige Bitrate ({bitrate} bps < {OBSERVE_MIN_BITRATE_BPS} bps)"
        )

    if (
        duration is not None
        and expected_duration is not None
        and expected_duration > 0
        and duration < expected_duration * OBSERVE_DURATION_MISMATCH_RATIO
    ):
        flags.append(
            f"deutlich kürzer als erwartet ({duration:.1f}s vs. "
            f"erwartete {expected_duration:.1f}s)"
        )

    observation = QualityObservation(
        path=str(path), duration_seconds=duration, bitrate=bitrate,
        expected_duration_seconds=expected_duration, flags=flags,
    )

    # PROBE_FAILED nur, wenn ffprobe GAR KEIN Signal liefern konnte (beide
    # Werte None) - liegt mindestens ein Wert vor, wird ganz normal anhand
    # der vorhandenen Daten OK/SUSPICIOUS bewertet (unveraendert gegenueber
    # vorher: dieselben drei Flag-Bedingungen wie zuvor).
    if duration is None and bitrate is None:
        status = "PROBE_FAILED"
    elif observation.suspicious:
        status = "SUSPICIOUS"
    else:
        status = "OK"

    logger.info(
        f"[QUALITY-CHECK] Analyse abgeschlossen → {status} | "
        f"file={observation.path} | "
        f"duration={_fmt(duration, 's', 1)} | "
        f"bitrate={_fmt(bitrate, 'bps')} | "
        f"expected_duration={_fmt(expected_duration, 's', 1)}"
    )

    if observation.suspicious:
        logger.warning(
            f"⚠️ [QUALITY-OBSERVE] Auffälliger Download (Stufe A, nur "
            f"Beobachtung, kein Reject): {path} — {'; '.join(flags)}"
        )

    return observation
