# services/library_health/tag_reader.py
# -*- coding: utf-8 -*-
"""
Read-only I/O-Adapter fuer den Library Health Scanner (Prompt Abschnitt
2/33 — WRITER-SAFETY).

Buendelt das Lesen von:
  - Audio-Tags (m4a/mp4 voll, mp3 best-effort)
  - Audio-Stream-Eigenschaften (ffprobe)
  - eingebettetem Artwork (mutagen + Pillow)

WARUM ein eigenes Modul und nicht services/metadata/... wiederverwenden:
`import services.metadata.*` triggert services/metadata/__init__.py, das
TagWriter / EnhancedMetadataProcessor / CoverProcessor u. a. importiert —
Komponenten mit Schreibpfaden. Der Scanner darf diese laut Prompt
Abschnitt 33 nicht einmal in den Import-Graph aufnehmen.
`tests/test_library_health_readonly_safety.py` verifiziert das aktiv.

Die MP4-Atom-Namen sind deckungsgleich zu services/metadata/tag_writer.py
(dort die Autoritaet fuer die AKTUELLE Pipeline) und
scripts/resolve_duplicates.py::read_tags(). Bewusst nachgebildet statt
importiert — identisches Muster wie services/duplicate/classification.py
gegenueber detector.py.

KEIN mutagen .save(), KEIN Schreib-Modus, KEIN Anlegen von Dateien.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Optional

from .models import AnalysisState

# ─────────────────────────────────────────────────────────────────────────
# Atom-/Frame-Namen
# ─────────────────────────────────────────────────────────────────────────

_MP4_MB_ATOMS = {
    "mb_recording_id": "----:com.apple.iTunes:MusicBrainz Recording Id",
    "mb_artist_id": "----:com.apple.iTunes:MusicBrainz Artist Id",
    "mb_release_id": "----:com.apple.iTunes:MusicBrainz Release Id",
    "mb_release_group_id": "----:com.apple.iTunes:MusicBrainz Release Group Id",
    "isrc": "----:com.apple.iTunes:ISRC",
}

_MP4_ARTISTS_FREEFORM_ATOM = "----:com.apple.iTunes:ARTISTS"

# ReplayGain / Loudness — freeform. loudness_normalized ist eine Altlast
# (siehe scripts/normalize_test_library_loudness.py Docstring).
_MP4_REPLAYGAIN_ATOMS = {
    "replaygain_track_gain": "----:com.apple.iTunes:replaygain_track_gain",
    "replaygain_track_peak": "----:com.apple.iTunes:replaygain_track_peak",
    "replaygain_album_gain": "----:com.apple.iTunes:replaygain_album_gain",
    "replaygain_album_peak": "----:com.apple.iTunes:replaygain_album_peak",
    "loudness_normalized": "----:com.apple.iTunes:loudness_normalized",
}

_SUPPORTED_TAG_EXTS = (".m4a", ".mp4", ".m4v")
_MP3_EXT = ".mp3"


# ─────────────────────────────────────────────────────────────────────────
# Ergebnis-Container
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class TagData:
    state: AnalysisState
    artist: Optional[str] = None
    album_artist: Optional[str] = None
    title: Optional[str] = None
    album: Optional[str] = None
    year: Optional[str] = None
    genre: Optional[str] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    artists_primary_tag: list[str] = field(default_factory=list)     # alle ©ART / TPE1-Werte
    artists_freeform: list[str] = field(default_factory=list)        # ----:...:ARTISTS / TXXX:ARTISTS
    mb_recording_id: Optional[str] = None
    mb_artist_id: Optional[str] = None
    mb_release_id: Optional[str] = None
    mb_release_group_id: Optional[str] = None
    isrc: Optional[str] = None
    lyrics: Optional[str] = None
    replaygain: dict = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ArtworkData:
    state: AnalysisState
    present: bool = False
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    size_bytes: Optional[int] = None
    is_square: Optional[bool] = None
    sha256: Optional[str] = None
    error: Optional[str] = None


@dataclass
class StreamData:
    state: AnalysisState
    has_audio_stream: bool = False
    codec: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    duration_seconds: Optional[float] = None
    bitrate: Optional[int] = None
    corrupt: bool = False
    error: Optional[str] = None


@dataclass
class LoudnessData:
    """Ergebnis einer FFmpeg-loudnorm-*Analyse* (kein Re-Encode, kein
    Output-File). NOT_ANALYZABLE, wenn ffmpeg fehlt / scheitert / keine
    Analyse-Ausgabe liefert."""
    state: AnalysisState
    integrated_lufs: Optional[float] = None
    true_peak: Optional[float] = None
    lra: Optional[float] = None
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────
# Helfer
# ─────────────────────────────────────────────────────────────────────────


def _first_str(values) -> Optional[str]:
    if not values:
        return None
    v = values[0]
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


def _all_str(values) -> list[str]:
    out: list[str] = []
    for v in values or []:
        if isinstance(v, bytes):
            out.append(v.decode("utf-8", errors="replace"))
        else:
            out.append(str(v))
    return out


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────
# Tags
# ─────────────────────────────────────────────────────────────────────────


def read_tags(path: Path) -> TagData:
    """Liest den aktuell gespeicherten Tag-Zustand direkt von der Platte.
    Wirft nie — ein unlesbarer Container ergibt state=NOT_ANALYZABLE
    (Prompt Abschnitt 9: 'nicht analysierbar != nicht vorhanden')."""
    ext = path.suffix.lower()
    try:
        if ext in _SUPPORTED_TAG_EXTS:
            return _read_mp4_tags(path)
        if ext == _MP3_EXT:
            return _read_mp3_tags(path)
        return TagData(state=AnalysisState.NOT_ANALYZABLE,
                       error=f"Kein Tag-Reader fuer {ext}")
    except Exception as e:  # noqa: BLE001 — bewusst: jede Datei robust
        return TagData(state=AnalysisState.NOT_ANALYZABLE, error=repr(e))


def _read_mp4_tags(path: Path) -> TagData:
    from mutagen.mp4 import MP4

    audio = MP4(path)
    tags = audio.tags
    if tags is None:
        return TagData(state=AnalysisState.MISSING, error="kein MP4-Tag-Block")

    trkn = tags.get("trkn")
    disk = tags.get("disk")
    lyr = _first_str(tags.get("©lyr"))

    data = TagData(
        state=AnalysisState.PRESENT,
        artist=_first_str(tags.get("©ART")),
        album_artist=_first_str(tags.get("aART")),
        title=_first_str(tags.get("©nam")),
        album=_first_str(tags.get("©alb")),
        year=_first_str(tags.get("©day")),
        genre=_first_str(tags.get("©gen")),
        track_number=trkn[0][0] if trkn and trkn[0] else None,
        disc_number=disk[0][0] if disk and disk[0] else None,
        artists_primary_tag=_all_str(tags.get("©ART")),
        artists_freeform=_all_str(tags.get(_MP4_ARTISTS_FREEFORM_ATOM)),
        lyrics=lyr,
    )
    for key, atom in _MP4_MB_ATOMS.items():
        setattr(data, key, _first_str(tags.get(atom)))
    for name, atom in _MP4_REPLAYGAIN_ATOMS.items():
        val = _first_str(tags.get(atom))
        if val is not None:
            data.replaygain[name] = val
    return data


def _read_mp3_tags(path: Path) -> TagData:
    from mutagen.id3 import ID3, ID3NoHeaderError

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return TagData(state=AnalysisState.MISSING, error="kein ID3-Header")

    def _text(frame_id: str) -> Optional[str]:
        frame = tags.get(frame_id)
        if frame is None or not getattr(frame, "text", None):
            return None
        return str(frame.text[0])

    def _text_all(frame_id: str) -> list[str]:
        frame = tags.get(frame_id)
        if frame is None or not getattr(frame, "text", None):
            return []
        return [str(t) for t in frame.text]

    track_raw = _text("TRCK")
    disc_raw = _text("TPOS")
    uslt = next((v for k, v in tags.items() if k.startswith("USLT")), None)

    # freeform TXXX
    replaygain: dict = {}
    artists_freeform: list[str] = []
    for key, frame in tags.items():
        if not key.startswith("TXXX:"):
            continue
        desc = key[5:].lower()
        if desc.startswith("replaygain_"):
            replaygain[desc] = str(frame.text[0]) if frame.text else ""
        elif desc == "artists":
            artists_freeform = [str(t) for t in (frame.text or [])]

    return TagData(
        state=AnalysisState.PRESENT,
        artist=_text("TPE1"),
        album_artist=_text("TPE2"),
        title=_text("TIT2"),
        album=_text("TALB"),
        year=_text("TDRC"),
        genre=_text("TCON"),
        track_number=_int_or_none(track_raw.split("/")[0]) if track_raw else None,
        disc_number=_int_or_none(disc_raw.split("/")[0]) if disc_raw else None,
        artists_primary_tag=_text_all("TPE1"),
        artists_freeform=artists_freeform,
        lyrics=str(uslt.text) if uslt is not None else None,
        replaygain=replaygain,
        # tag_writer.py schreibt fuer MP3 nachweislich keine MB-IDs/ISRC.
    )


# ─────────────────────────────────────────────────────────────────────────
# Artwork
# ─────────────────────────────────────────────────────────────────────────


def read_artwork(path: Path) -> ArtworkData:
    """Liest das erste eingebettete Cover und misst Groesse/Format via
    Pillow (bereits Projekt-Dependency). Kein Netzwerk, keine Cover-Suche
    (Prompt Abschnitt 11)."""
    ext = path.suffix.lower()
    try:
        if ext in _SUPPORTED_TAG_EXTS:
            raw, mime = _extract_mp4_cover(path)
        elif ext == _MP3_EXT:
            raw, mime = _extract_mp3_cover(path)
        else:
            return ArtworkData(state=AnalysisState.NOT_ANALYZABLE,
                               error=f"kein Artwork-Reader fuer {ext}")
    except Exception as e:  # noqa: BLE001
        return ArtworkData(state=AnalysisState.NOT_ANALYZABLE, error=repr(e))

    if raw is None:
        return ArtworkData(state=AnalysisState.MISSING, present=False)

    data = ArtworkData(
        state=AnalysisState.PRESENT,
        present=True,
        mime_type=mime,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    try:
        from PIL import Image

        with Image.open(BytesIO(raw)) as img:
            data.width, data.height = img.width, img.height
            if not data.mime_type and img.format:
                data.mime_type = f"image/{img.format.lower()}"
        data.is_square = data.width == data.height if data.width and data.height else None
    except Exception as e:  # noqa: BLE001 — Cover-Bytes nicht dekodierbar
        data.state = AnalysisState.INVALID
        data.error = repr(e)
    return data


def _extract_mp4_cover(path: Path):
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(path)
    tags = audio.tags or {}
    covr = tags.get("covr")
    if not covr:
        return None, None
    cover = covr[0]
    fmt = getattr(cover, "imageformat", None)
    mime = None
    if fmt == MP4Cover.FORMAT_JPEG:
        mime = "image/jpeg"
    elif fmt == MP4Cover.FORMAT_PNG:
        mime = "image/png"
    return bytes(cover), mime


def _extract_mp3_cover(path: Path):
    from mutagen.id3 import ID3, ID3NoHeaderError

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return None, None
    apic_key = next((k for k in tags.keys() if k.startswith("APIC")), None)
    if apic_key is None:
        return None, None
    apic = tags[apic_key]
    return apic.data, getattr(apic, "mime", None) or None


# ─────────────────────────────────────────────────────────────────────────
# Audio-Stream (ffprobe)
# ─────────────────────────────────────────────────────────────────────────

_CORRUPT_MARKERS = (
    "moov atom not found",
    "invalid data found",
    "error while decoding",
    "could not find codec parameters",
    "partial file",
)


def probe_stream(path: Path, timeout: int = 30) -> StreamData:
    """Rein lesende ffprobe-Analyse (kein Output-File). Ein Fehler ergibt
    NOT_ANALYZABLE bzw. — bei eindeutigen Korruptions-Markern — INVALID
    mit corrupt=True (Prompt Abschnitt 15)."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            capture_output=True, timeout=timeout,
        )
    except FileNotFoundError:
        return StreamData(state=AnalysisState.NOT_ANALYZABLE,
                          error="ffprobe nicht auf PATH")
    except subprocess.TimeoutExpired:
        return StreamData(state=AnalysisState.NOT_ANALYZABLE, error="ffprobe Timeout")
    except Exception as e:  # noqa: BLE001
        return StreamData(state=AnalysisState.NOT_ANALYZABLE, error=repr(e))

    stderr_text = result.stderr.decode("utf-8", errors="replace").lower()

    if result.returncode != 0:
        corrupt = any(m in stderr_text for m in _CORRUPT_MARKERS)
        return StreamData(
            state=AnalysisState.INVALID if corrupt else AnalysisState.NOT_ANALYZABLE,
            corrupt=corrupt,
            error=stderr_text.strip()[:300] or f"ffprobe rc={result.returncode}",
        )

    try:
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        return StreamData(state=AnalysisState.NOT_ANALYZABLE, error=repr(e))

    streams = data.get("streams") or []
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format") or {}

    if audio_stream is None:
        return StreamData(state=AnalysisState.PRESENT, has_audio_stream=False)

    return StreamData(
        state=AnalysisState.PRESENT,
        has_audio_stream=True,
        codec=audio_stream.get("codec_name"),
        sample_rate=_int_or_none(audio_stream.get("sample_rate")),
        channels=_int_or_none(audio_stream.get("channels")),
        duration_seconds=_float_or_none(fmt.get("duration") or audio_stream.get("duration")),
        bitrate=_int_or_none(fmt.get("bit_rate") or audio_stream.get("bit_rate")),
    )


# FFmpeg-loudnorm-Analyse-Parameter — deckungsgleich zu
# utils/audio_enhancer.py::normalize_loudness() (erster Analyse-Durchlauf)
# und scripts/normalize_test_library_loudness.py::measure_loudness().
# I=-16 entspricht AudioEnhancer.TARGET_LUFS['music'] (bewusst NICHT aus
# utils.audio_enhancer importiert — das Modul enthaelt den Re-Encode-
# Schreibpfad und ist im Import-Graph des read-only Scanners verboten,
# siehe tests/test_library_health_readonly_safety.py).
_LOUDNORM_ANALYSE_AF = "loudnorm=I=-16:LRA=11:TP=-1.5:print_format=json"
_LOUDNORM_JSON_RE = re.compile(r'\{[^{}]*"input_i"[^{}]*\}')


def measure_loudness(path: Path, timeout: int = 90) -> LoudnessData:
    """Rein lesende integrierte-Lautheit-Messung (LUFS) + True Peak via
    `ffmpeg -af loudnorm=…:print_format=json -f null -`. Schreibt NICHTS
    (Ziel ist `null`). Gibt bei jedem Fehler NOT_ANALYZABLE zurueck, nie
    eine Exception (Prompt Abschnitt 34).

    Deutlich langsamer als probe_stream (dekodiert den kompletten Stream) —
    der Scanner ruft das nur bei ausdruecklicher Anforderung auf
    (`run_scan(measure_loudness=True)` / `--measure-loudness`)."""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-i", str(path),
                "-af", _LOUDNORM_ANALYSE_AF, "-f", "null", "-",
            ],
            capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return LoudnessData(state=AnalysisState.NOT_ANALYZABLE, error="ffmpeg nicht auf PATH")
    except subprocess.TimeoutExpired:
        return LoudnessData(state=AnalysisState.NOT_ANALYZABLE, error="ffmpeg Timeout")
    except Exception as e:  # noqa: BLE001
        return LoudnessData(state=AnalysisState.NOT_ANALYZABLE, error=repr(e))

    stderr_text = result.stderr.decode("utf-8", errors="replace")
    match = _LOUDNORM_JSON_RE.search(stderr_text)
    if not match:
        return LoudnessData(
            state=AnalysisState.NOT_ANALYZABLE,
            error=(stderr_text.strip()[-300:] or "keine loudnorm-Analyse-Ausgabe"),
        )
    try:
        data = json.loads(match.group())
        lufs = float(data["input_i"])
        tp = float(data["input_tp"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        return LoudnessData(state=AnalysisState.NOT_ANALYZABLE, error=f"loudnorm-JSON: {e!r}")

    # FFmpeg meldet -inf/-70 fuer echte Stille — kein sinnvoller LUFS-Wert.
    if lufs <= -70.0:
        return LoudnessData(state=AnalysisState.NOT_ANALYZABLE,
                            error=f"loudnorm meldet Stille (input_i={lufs})")

    return LoudnessData(
        state=AnalysisState.PRESENT,
        integrated_lufs=lufs,
        true_peak=tp,
        lra=_float_or_none(data.get("input_lra")),
    )


def _float_or_none(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
