# services/metadata/loudness_replaygain.py
# -*- coding: utf-8 -*-
"""
Verlustfreie Loudness-Behandlung für die Download-Pipeline (Schritt 15b).

Ersetzt den früheren FFmpeg-loudnorm-**Re-Encode**
(`utils/audio_enhancer.py::normalize_loudness()`, ~22 s pro Track + AAC→AAC-
Generationsverlust) durch einen schnellen EBU-R128-Scan, der einen
ReplayGain-2.0-Tag schreibt — der Audio-Stream bleibt **byte-identisch**.
Navidrome (und jeder RG-fähige Player) bringt die Datei damit auf die
Ziel-Lautheit.

Primärpfad: `rsgain` (~1,5 s, schreibt die Tags selbst).
Fallback (kein `rsgain` auf PATH): eine reine FFmpeg-loudnorm-**Analyse**
(kein Output-File, identisch zu `services/library_health/tag_reader.py::
measure_loudness()`) + Tag-Write via mutagen.

Tag-Format deckungsgleich zum Library-Repair-Loudness-Executor
(`services/library_repair/replaygain_repairs.py`): Freeform-Atome
`----:com.apple.iTunes:replaygain_track_gain` / `_peak`, Gain als
`"<x.xx> dB"`, Peak linear (1.0 = 0 dBFS). Referenz = Ziel-LUFS (Musik
−16, bewusst nicht die RG-2.0-Norm −18 — siehe replaygain_repairs.py).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from logger import get_module_logger

logger = get_module_logger("LoudnessReplayGain")

_GAIN_ATOM = "----:com.apple.iTunes:replaygain_track_gain"
_PEAK_ATOM = "----:com.apple.iTunes:replaygain_track_peak"

_SUPPORTED = (".m4a", ".mp4", ".m4v", ".mp3")

# > diese Abweichung (dB) vom Ziel → Tag schreiben. Deckungsgleich zur
# Melde-Schwelle des Health-Scanners (LOUDNESS_OFF_TARGET_DB) und zu
# replaygain_repairs.TOLERANCE_DB.
_TOLERANCE_DB = 2.0

_LOUDNORM_JSON_RE = re.compile(r'\{[^{}]*"input_i"[^{}]*\}')


def _peak_linear_from_dbtp(true_peak_dbtp: Optional[float]) -> float:
    """dBTP → linearer Peak (RG-Konvention: 1.0 = 0 dBFS). Fehlt der Wert:
    konservativ 1.0."""
    if true_peak_dbtp is None:
        return 1.0
    return round(10.0 ** (true_peak_dbtp / 20.0), 6)


def _rsgain_available() -> bool:
    return shutil.which("rsgain") is not None


def _run_rsgain(path: Path, target_lufs: int, timeout: int) -> bool:
    """`rsgain custom` scannt und schreibt die RG-2.0-Tags direkt in die
    Datei (kein Re-Encode). `-L` erzwingt die kleingeschriebenen
    Atomnamen, die der Health-Scanner/Navidrome erwarten."""
    cmd = [
        "rsgain",
        "custom",
        "-l",
        str(target_lufs),
        "-s",
        "i",  # scan + write RG 2.0 tags
        "-t",  # true peak
        "-L",  # lowercase tag names
        "-q",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        logger.warning(
            f"rsgain returncode={result.returncode} für {path.name}: "
            f"{(result.stderr or result.stdout or '').strip()[-300:]}"
        )
        return False
    return True


def _measure_loudness_ffmpeg(
    path: Path, timeout: int
) -> Tuple[Optional[float], Optional[float]]:
    """Reine FFmpeg-loudnorm-Analyse (kein Output-File) → (LUFS, dBTP).
    Identisch zu library_health.tag_reader.measure_loudness(), hier lokal
    gehalten, damit dieses Modul nicht in den Import-Graph des read-only
    Scanners zurückgreift."""
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-i",
                str(path),
                "-af",
                "loudnorm=I=-16:LRA=11:TP=-1.5:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning(f"FFmpeg-loudnorm-Analyse fehlgeschlagen für {path.name}: {e!r}")
        return None, None
    match = _LOUDNORM_JSON_RE.search(result.stderr or "")
    if not match:
        return None, None
    try:
        data = json.loads(match.group())
        lufs = float(data["input_i"])
        tp = float(data["input_tp"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None, None
    if lufs <= -70.0:  # FFmpeg meldet -inf/-70 bei echter Stille
        return None, None
    return lufs, tp


def _write_tags_mutagen(path: Path, gain_db: float, peak_linear: float) -> bool:
    try:
        ext = path.suffix.lower()
        if ext in (".m4a", ".mp4", ".m4v"):
            from mutagen.mp4 import MP4, MP4FreeForm

            audio = MP4(path)
            audio[_GAIN_ATOM] = [MP4FreeForm(f"{gain_db:.2f} dB".encode("utf-8"))]
            audio[_PEAK_ATOM] = [MP4FreeForm(f"{peak_linear:.6f}".encode("utf-8"))]
            audio.save()
            return True
        if ext == ".mp3":
            from mutagen.id3 import ID3, TXXX

            try:
                tags = ID3(path)
            except Exception:  # noqa: BLE001 - kein/ungültiges ID3
                tags = ID3()
            tags.setall(
                "TXXX:replaygain_track_gain",
                [
                    TXXX(
                        encoding=3,
                        desc="replaygain_track_gain",
                        text=[f"{gain_db:.2f} dB"],
                    )
                ],
            )
            tags.setall(
                "TXXX:replaygain_track_peak",
                [
                    TXXX(
                        encoding=3,
                        desc="replaygain_track_peak",
                        text=[f"{peak_linear:.6f}"],
                    )
                ],
            )
            tags.save(path)
            return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"mutagen-RG-Tag-Write fehlgeschlagen für {path.name}: {e!r}")
    return False


def apply_replaygain_tags(
    filepath: str, target_lufs: float = -16.0, *, timeout: int = 90
) -> Tuple[bool, Optional[float]]:
    """Schreibt einen verlustfreien ReplayGain-Track-Tag (Referenz
    `target_lufs`). Der Audio-Stream wird NICHT verändert.

    Rückgabe: `(ok, gain_db)` — `ok=True`, sobald ein RG-Tag vorhanden ist
    (neu geschrieben oder — im Toleranzband — bereits nah am Ziel und daher
    bewusst nicht geschrieben). `gain_db` ist der berechnete/geschriebene
    Track-Gain, oder `None` wenn keine Messung möglich war.
    """
    path = Path(filepath)
    if not path.exists():
        logger.error(f"Datei nicht gefunden: {path}")
        return False, None
    if path.suffix.lower() not in _SUPPORTED:
        logger.debug(f"Überspringe ReplayGain für {path.suffix}")
        return True, None

    target_int = int(round(target_lufs))

    # ── Primärpfad: rsgain schreibt die Tags selbst ──────────────────────
    if _rsgain_available():
        try:
            if _run_rsgain(path, target_int, timeout):
                gain = _read_gain_db(path)
                logger.info(
                    f"🔊 ReplayGain (rsgain, Ziel {target_int} LUFS): "
                    f"gain={gain if gain is not None else '?'} dB — {path.name}"
                )
                return True, gain
        except subprocess.TimeoutExpired:
            logger.warning(
                f"rsgain Timeout für {path.name} — Fallback auf FFmpeg-Analyse"
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"rsgain-Fehler für {path.name}: {e!r} — Fallback")

    # ── Fallback: FFmpeg-Analyse + mutagen-Write ─────────────────────────
    measured_lufs, true_peak = _measure_loudness_ffmpeg(path, timeout)
    if measured_lufs is None:
        logger.warning(
            f"🔊⚠️ Keine Lautheits-Messung möglich für {path.name} — "
            f"kein ReplayGain-Tag geschrieben"
        )
        return False, None

    gain_db = target_lufs - measured_lufs
    if abs(gain_db) <= _TOLERANCE_DB:
        logger.info(
            f"🔊 ReplayGain: {path.name} liegt bei {measured_lufs:.1f} LUFS "
            f"(≤ {_TOLERANCE_DB} dB vom Ziel) — kein Tag nötig"
        )
        return True, gain_db

    peak_linear = _peak_linear_from_dbtp(true_peak)
    ok = _write_tags_mutagen(path, gain_db, peak_linear)
    if ok:
        logger.info(
            f"🔊 ReplayGain (FFmpeg-Fallback, Ziel {target_lufs} LUFS): "
            f"gemessen {measured_lufs:.1f} → gain {gain_db:+.2f} dB — {path.name}"
        )
    return ok, gain_db


def _read_gain_db(path: Path) -> Optional[float]:
    """Liest den geschriebenen replaygain_track_gain zur Bestätigung/zum
    Logging zurück."""
    try:
        ext = path.suffix.lower()
        if ext in (".m4a", ".mp4", ".m4v"):
            from mutagen.mp4 import MP4

            raw = (MP4(path).tags or {}).get(_GAIN_ATOM)
            if raw:
                v = raw[0]
                s = v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
                m = re.match(r"\s*(-?\d+(?:\.\d+)?)", s)
                return float(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        pass
    return None
