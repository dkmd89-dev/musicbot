#!/usr/bin/env python3
# scripts/normalize_test_library_loudness.py
# -*- coding: utf-8 -*-
"""
Isoliertes LUFS-Reprocessing fuer die Test-Bibliothek unter
/tmp/musicbot_test/library.

Ziel: bestehende Audiodateien in der isolierten Testbibliothek mit der
bereits vorhandenen, produktiv genutzten utils/audio_enhancer.py::
AudioEnhancer.normalize_loudness() auf die MusicBot-Ziel-Lautheit fuer
Musik (AudioEnhancer.get_target_lufs("music"), aktuell -16.0 LUFS)
bringen - KEINE eigene FFmpeg-loudnorm-Implementierung, KEINE Aenderung
an utils/audio_enhancer.py selbst.

Bewusst SYNCHRON (kein asyncio, kein asyncio.to_thread()): die
Produktionspipeline wrappt AudioEnhancer.normalize_loudness() in
asyncio.to_thread(), weil sie im geteilten Telegram-Bot-Event-Loop laeuft
und diesen sonst fuer alle Nutzer blockieren wuerde (FINDING-7,
tests/test_enhanced_metadata_processor_loudness_blocking.py). Dieses
Script ist ein eigenstaendiger, einmalig gestarteter Batch-Prozess ohne
geteilten Event-Loop - es gibt nichts, das durch einen synchronen Aufruf
blockiert werden koennte. Eine async-Huelle waere hier unnoetige
Komplexitaet ohne Nutzen (anders als scripts/reprocess_artist_metadata.py,
das ECHTE async Produktions-Subprozessoren wie GenreProcessor/
LyricsProcessor/CoverProcessor wiederverwendet und deshalb selbst async
sein muss).

WICHTIGER UNTERSCHIED zur Produktionspipeline: dort laeuft die Loudness-
Normalisierung VOR dem Tag-Schreiben (Schritt 15b von 17) - ein
Metadatenverlust durch das FFmpeg-Re-Encoding waere dort folgenlos, da
alle Tags danach ohnehin frisch geschrieben werden. Dieses Script
arbeitet dagegen auf BEREITS fertig getaggten Library-Dateien - ein
Metadatenverlust waere hier real sichtbar und wird deshalb explizit vor/
nach jeder Normalisierung geprueft (siehe METADATA_FIELDS unten). FFmpegs
loudnorm-Re-Encoding setzt kein "-map_metadata"/"-map 0" (siehe
utils/audio_enhancer.py) - ob Metadaten/Cover erhalten bleiben, ist damit
reines FFmpeg-Standardverhalten, nicht garantiert (ARCH-017,
docs/archive/arch/MusicBot_ARCH-017_Download_Audio_Enhancement_Characterization.md,
Abschnitt 6: "nicht weiter verifiziert, ausserhalb Scope").

GEFUNDENER DEFEKT in AudioEnhancer.normalize_loudness() (live reproduziert
waehrend der Implementierung dieses Scripts, NICHT behoben - nur
dokumentiert, wie vom Auftrag verlangt): der "apply"-FFmpeg-Aufruf
(utils/audio_enhancer.py, cmd_apply) setzt weder "-map 0:a" noch "-vn"
noch "-c:v copy". Enthaelt die Eingabedatei bereits ein eingebettetes
Cover (covr-Atom - IMMER der Fall bei bereits fertig heruntergeladenen
MusicBot-Tracks, aber NIE der Fall an der Aufrufstelle in der
Produktionspipeline, da dort noch vor dem Tag-Schreiben aufgerufen wird -
deshalb bisher nie aufgefallen), behandelt FFmpegs mp4-Demuxer das Cover
als eigenstaendigen Videostream. Der apply-Aufruf versucht dann, DIESEN
Videostream zusaetzlich zum Audio zu re-encodieren (H.264 via libx264),
was der ipod/mp4-Muxer in dieser Konstellation ablehnt ("Could not find
tag for codec h264 in stream #0" / "Conversion failed!" / "Nothing was
written into output file"). FFmpeg legt die Zieldatei aber bereits VOR
diesem Fehler an (0 Byte). AudioEnhancer.normalize_loudness() prueft nach
subprocess.run() weder den Return-Code noch die Dateigroesse, sondern nur
"if temp_path.exists()" - eine leere Datei erfuellt diese Bedingung, wird
per temp_path.replace(path) ueber die intakte Originaldatei geschrieben,
und die Funktion liefert True (Erfolg!) zurueck, obwohl die Originaldatei
soeben durch eine leere 0-Byte-Datei ersetzt wurde.

Da dieses Script explizit NICHT utils/audio_enhancer.py aendern darf
(Auftrag: "nur dokumentieren, nicht ungefragt beheben"), aber gleichzeitig
die Testbibliothek nicht beschaedigen darf, sichert process_file() JEDE
Datei vor dem Normalize-Aufruf in eine lokale .bak-Kopie und stellt sie
automatisch wieder her, falls die Datei danach leer/nicht mehr als
Audiodatei lesbar ist (siehe _is_file_intact()/BACKUP-Handling in
process_file()). Das ist eine Absicherung IN DIESEM Script, keine
Aenderung an AudioEnhancer selbst.

Die Tags "replaygain_track_gain"/"loudness_normalized" (freeform,
com.apple.iTunes) werden von der AKTUELLEN Pipeline (tag_writer.py,
enhanced_metadata_processor.py) nirgends geschrieben - reine Altlast in
vorhandenen Testdateien aus einer frueheren Codeversion. Die Skip-
Entscheidung dieses Scripts basiert deshalb ausschliesslich auf einer
frischen FFmpeg-loudnorm-Analyse-Messung, nicht auf einem Tag-Wert.

HARTE SICHERHEITSREGEL: darf ausschliesslich innerhalb von
/tmp/musicbot_test/library schreiben. Siehe validate_scan_root()/
validate_file_within_root() fuer die vollstaendigen Guards (Symlink-
Aufloesung via .resolve(strict=True), explizite Denylist fuer alle
bekannten Produktions-/Fremdpfade als Defense-in-Depth zusaetzlich zur
Allowlist-Pruefung).

Nutzung:
    python scripts/normalize_test_library_loudness.py --dry-run
    python scripts/normalize_test_library_loudness.py
    python scripts/normalize_test_library_loudness.py --path /tmp/musicbot_test/library/CHAPO102
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from mutagen.mp4 import MP4

from utils.audio_enhancer import AudioEnhancer

# ─────────────────────────────────────────────────────────────────────────
# Konstanten
# ─────────────────────────────────────────────────────────────────────────

ALLOWED_ROOT = Path("/tmp/musicbot_test/library")

# Bekannte Produktions-/Fremdpfade - explizite Denylist als Defense-in-Depth
# zusaetzlich zur Allowlist-Pruefung in validate_scan_root() (Auftrag,
# Abschnitt "HARTE SICHERHEITSREGEL").
FORBIDDEN_ROOTS = [
    Path("/mnt/4tb/library"),
    Path("/mnt/128ssd"),
    Path("/mnt/musik_bilder"),
    Path("/mnt/media"),
    Path("/tmp/musicbot_test/metadaten"),
]

SUPPORTED_EXTENSIONS = {".m4a", ".mp4", ".mp3"}

TARGET_LUFS = AudioEnhancer.get_target_lufs("music")  # -16.0, NICHT hardcodiert
LUFS_TOLERANCE = 0.5  # dB - kein bestehendes Toleranzfenster im Repository
# gefunden (grep -rn "LUFS_TOLERANCE" ergab 0 Treffer) - Auftragsvorschlag
# uebernommen, hier als einzige Quelle der Wahrheit definiert und
# dokumentiert.

DURATION_WARN_SECONDS = 2.0  # Schwelle fuer eine auffaellige, im Report
# markierte (aber nicht automatisch als FAILED gewertete) Laufzeit-
# Abweichung nach dem Re-Encoding - reines Rundungsrauschen an
# Frame-Grenzen liegt ueblicherweise weit darunter.

REPORT_JSON_PATH = Path("/tmp/musicbot_test/loudness_reprocessing_report.json")

# Metadaten-Felder, die vor/nach der Normalisierung verglichen werden
# (Auftrag, Abschnitt "Metadata / Container").
MB_ID_ATOM_MAP = {
    "recording_id": "----:com.apple.iTunes:MusicBrainz Track Id",
    "artist_id": "----:com.apple.iTunes:MusicBrainz Artist Id",
    "release_id": "----:com.apple.iTunes:MusicBrainz Album Id",
    "release_group_id": "----:com.apple.iTunes:MusicBrainz Release Group Id",
    "isrc": "----:com.apple.iTunes:ISRC",
}


class PathSafetyError(Exception):
    """Wird bei jeder Verletzung der Path-Safety-Guards ausgeloest."""


# ─────────────────────────────────────────────────────────────────────────
# Path-Safety
# ─────────────────────────────────────────────────────────────────────────


def validate_scan_root(path: Path) -> Path:
    """
    Harte Path-Safety-Guards. Loest bei jeder Verletzung PathSafetyError
    aus - der Aufrufer darf danach KEINE Datei anfassen. Symlinks werden
    durch .resolve(strict=True) vollstaendig aufgeloest, bevor irgendeine
    Grenzpruefung stattfindet.
    """
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        raise PathSafetyError(f"Pfad existiert nicht: {path}")
    except OSError as e:
        raise PathSafetyError(f"Pfad nicht aufloesbar: {path} ({e})")

    if not resolved.is_dir():
        raise PathSafetyError(f"Pfad ist kein Verzeichnis: {resolved}")

    # Denylist zuerst und unabhaengig von der Allowlist-Pruefung unten -
    # ein Treffer hier ist immer ein harter Stopp mit eindeutiger, benannter
    # Fehlermeldung (Defense-in-Depth, analog zum Produktions-Guard in
    # scripts/reprocess_artist_metadata.py::validate_input_path()).
    for forbidden in FORBIDDEN_ROOTS:
        try:
            forbidden_resolved = forbidden.resolve()
        except OSError:
            continue
        if resolved == forbidden_resolved or forbidden_resolved in resolved.parents:
            raise PathSafetyError(
                f"Pfad zeigt auf einen verbotenen Bereich ({forbidden}): {resolved}"
            )

    allowed_resolved = ALLOWED_ROOT.resolve()
    if resolved != allowed_resolved and allowed_resolved not in resolved.parents:
        raise PathSafetyError(
            f"Pfad liegt ausserhalb der erlaubten Testbibliothek "
            f"{allowed_resolved}: {resolved}"
        )

    return resolved


def validate_file_within_root(file_path: Path, root: Path) -> bool:
    """Symlink-Schutz auf Dateiebene: eine innerhalb des Scan-Roots
    gefundene Datei koennte selbst ein Symlink sein, der nach aussen zeigt.
    Gibt False zurueck (statt zu werfen), damit main() einzelne
    verdaechtige Dateien ueberspringen (SAFETY_BLOCKED) kann, ohne den
    gesamten Lauf abzubrechen."""
    try:
        resolved_file = file_path.resolve(strict=True)
        resolved_root = root.resolve()
    except OSError:
        return False
    return resolved_root == resolved_file or resolved_root in resolved_file.parents


# ─────────────────────────────────────────────────────────────────────────
# Lautheits-Messung (reine Analyse, kein Schreiben) - dieselbe FFmpeg-
# loudnorm-Analyse-Technik wie AudioEnhancer.normalize_loudness()s eigener
# erster Durchlauf (utils/audio_enhancer.py, Zeilen 75-90), hier separat
# verwendet, da normalize_loudness() selbst keine reine Messfunktion ohne
# Anwendung anbietet.
# ─────────────────────────────────────────────────────────────────────────


def measure_loudness(path: Path, target_lufs: float = TARGET_LUFS) -> dict:
    """
    Misst die aktuelle integrierte Lautheit (LUFS) und den True Peak einer
    Datei, OHNE sie zu veraendern. Gibt bei Fehlern {"error": "..."}
    zurueck statt zu werfen.
    """
    try:
        cmd = [
            "ffmpeg", "-nostdin", "-i", str(path),
            "-af", f"loudnorm=I={target_lufs}:LRA=11:TP=-1.5:print_format=json",
            "-f", "null", "-",
        ]
        result = subprocess.run(
            cmd, capture_output=True, timeout=60,
            stdin=subprocess.DEVNULL,
        )
        # BUGFIX (live entdeckt): FFmpeg bricht seine eigene Konsolen-
        # Zeilenumbruch-Darstellung von Eingabe-Metadaten (z.B. Lyrics-Tags)
        # nicht an UTF-8-Zeichengrenzen um - bei text=True/strict decoding
        # fuehrt ein mitten durchtrenntes Mehrbyte-Zeichen (real reproduziert:
        # "weiß" -> b'wei\xc3\n', getrennt zwischen den zwei Bytes von "ß")
        # zu einem UnicodeDecodeError und liesse die Messung fuer die
        # betroffene Datei faelschlich als MEASUREMENT_FAILED erscheinen,
        # obwohl die eigentliche loudnorm-Analyse erfolgreich war. Bytes
        # roh einlesen und mit errors="replace" dekodieren - dasselbe
        # bereits im Repository etablierte Muster wie
        # scripts/reprocess_artist_metadata.py::_freeform_str()
        # (bytes(v).decode("utf-8", errors="replace")).
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        match = re.search(r'\{[^{}]*"input_i"[^{}]*\}', stderr_text)
        if not match:
            return {
                "error": "Keine loudnorm-Analyse-Ausgabe gefunden",
                "integrated_lufs": None,
                "true_peak": None,
            }
        data = json.loads(match.group())
        return {
            "integrated_lufs": float(data["input_i"]),
            "true_peak": float(data["input_tp"]),
            "lra": float(data.get("input_lra", 0)),
            "threshold": float(data.get("input_thresh", 0)),
            "error": None,
        }
    except subprocess.TimeoutExpired:
        return {"error": "ffmpeg Timeout bei Lautheitsmessung", "integrated_lufs": None, "true_peak": None}
    except Exception as e:
        return {"error": str(e), "integrated_lufs": None, "true_peak": None}


# ─────────────────────────────────────────────────────────────────────────
# Stream-/Metadata-Snapshot
# ─────────────────────────────────────────────────────────────────────────


def _sha256(data):
    if not data:
        return None
    return hashlib.sha256(data).hexdigest()


def _freeform_str(values):
    out = []
    for v in values or []:
        try:
            out.append(bytes(v).decode("utf-8", errors="replace"))
        except Exception:
            out.append(str(v))
    return out


def ffprobe_stream_info(path: Path) -> dict:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            capture_output=True, text=True, timeout=30, check=True,
        )
        data = json.loads(result.stdout)
        audio_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
            {},
        )
        fmt = data.get("format", {})
        return {
            "codec": audio_stream.get("codec_name"),
            "sample_rate": audio_stream.get("sample_rate"),
            "channels": audio_stream.get("channels"),
            "duration": fmt.get("duration"),
            "bitrate": fmt.get("bit_rate"),
        }
    except Exception as e:
        return {"error": str(e)}


def _is_file_intact(path: Path) -> bool:
    """
    Schneller Sanity-Check nach einem AudioEnhancer.normalize_loudness()-
    Aufruf: existiert die Datei, ist sie nicht leer, und liefert ffprobe
    einen lesbaren Audio-Stream? Schutz gegen den im Modul-Docstring
    dokumentierten AudioEnhancer-Cover-Stream-Defekt (leere 0-Byte-Datei
    nach fehlgeschlagenem Re-Encode, von normalize_loudness() faelschlich
    als Erfolg gemeldet).
    """
    try:
        if not path.exists() or path.stat().st_size == 0:
            return False
    except OSError:
        return False
    info = ffprobe_stream_info(path)
    return bool(info.get("codec")) and "error" not in info


def snapshot_metadata(path: Path) -> dict:
    """Liest den aktuellen, tatsaechlich gespeicherten Tag-/Cover-Zustand
    direkt von der Platte (frisches mutagen.mp4.MP4(path))."""
    try:
        audio = MP4(path)
    except Exception as e:
        return {"error": str(e)}

    tags = audio.tags or {}

    def _t(key):
        v = tags.get(key)
        return list(v) if v else []

    cover = tags.get("covr")
    cover_bytes = bytes(cover[0]) if cover else None

    mb_ids = {}
    for key, atom in MB_ID_ATOM_MAP.items():
        v = _freeform_str(tags.get(atom))
        mb_ids[key] = v[0] if v else None

    trkn = tags.get("trkn")
    track_number = trkn[0][0] if trkn else None

    return {
        "artist": _t("©ART"),
        "artists_freeform": _freeform_str(tags.get("----:com.apple.iTunes:ARTISTS")),
        "album_artist": _t("aART"),
        "title": _t("©nam"),
        "album": _t("©alb"),
        "year": _t("©day"),
        "genre": _t("©gen"),
        "track_number": track_number,
        "mb_ids": mb_ids,
        "lyrics_present": bool(tags.get("©lyr")),
        "cover_present": bool(cover),
        "cover_sha256": _sha256(cover_bytes),
    }


def diff_metadata(before: dict, after: dict) -> dict:
    """Reiner Feld-Diff - meldet JEDE Abweichung, korrigiert nichts
    (Auftrag: 'Nicht stillschweigend korrigieren')."""
    if before.get("error") or after.get("error"):
        return {"error": f"before={before.get('error')} after={after.get('error')}"}
    changes = {}
    for key in before:
        if before.get(key) != after.get(key):
            changes[key] = {"before": before.get(key), "after": after.get(key)}
    return changes


# ─────────────────────────────────────────────────────────────────────────
# Verzeichnis-Integritaet
# ─────────────────────────────────────────────────────────────────────────


def snapshot_directory_tree(root: Path) -> dict:
    """Rein lesendes Inventar (relative Pfade) fuer den Struktur-Vergleich
    vor/nach dem Lauf - darf sich niemals aendern (kein Verschieben/
    Umbenennen/Loeschen in diesem Script)."""
    files = sorted(
        str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
    )
    dirs = sorted(
        str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir()
    )
    return {"files": files, "dirs": dirs, "file_count": len(files)}


# ─────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────


def log(text: str = ""):
    print(text, flush=True)


# ─────────────────────────────────────────────────────────────────────────
# Kern: eine Datei verarbeiten
# ─────────────────────────────────────────────────────────────────────────


def process_file(path: Path, scan_root: Path, dry_run: bool) -> dict:
    rel = str(path.relative_to(scan_root))
    result = {
        "file": rel,
        "before_lufs": None,
        "target_lufs": TARGET_LUFS,
        "tolerance": LUFS_TOLERANCE,
        "after_lufs": None,
        "before_true_peak": None,
        "after_true_peak": None,
        "action": None,
        "status": None,
        "audio_reencoding": False,
        "codec_before": None,
        "codec_after": None,
        "bitrate_before": None,
        "bitrate_after": None,
        "sample_rate_before": None,
        "sample_rate_after": None,
        "channels_before": None,
        "channels_after": None,
        "duration_before": None,
        "duration_after": None,
        "duration_delta_seconds": None,
        "duration_warning": False,
        "metadata_diff": {},
        "cover_before_sha256": None,
        "cover_after_sha256": None,
        "cover_lost": False,
        "error": None,
    }

    log(f"\n🎵 {rel}")

    if not validate_file_within_root(path, scan_root):
        result["status"] = "SAFETY_BLOCKED"
        result["error"] = "Datei liegt (ggf. via Symlink) ausserhalb des erlaubten Roots"
        log(f"   🚫 SAFETY_BLOCKED: {result['error']}")
        return result

    stream_before = ffprobe_stream_info(path)
    meta_before = snapshot_metadata(path)
    result["codec_before"] = stream_before.get("codec")
    result["bitrate_before"] = stream_before.get("bitrate")
    result["sample_rate_before"] = stream_before.get("sample_rate")
    result["channels_before"] = stream_before.get("channels")
    result["duration_before"] = stream_before.get("duration")
    result["cover_before_sha256"] = meta_before.get("cover_sha256")

    measured = measure_loudness(path)
    if measured.get("error"):
        result["status"] = "MEASUREMENT_FAILED"
        result["error"] = measured["error"]
        log(f"   ❌ MEASUREMENT_FAILED: {measured['error']}")
        return result

    before_lufs = measured["integrated_lufs"]
    result["before_lufs"] = before_lufs
    result["before_true_peak"] = measured["true_peak"]

    delta = before_lufs - TARGET_LUFS
    needs_normalization = abs(delta) > LUFS_TOLERANCE
    result["action"] = "NORMALIZE" if needs_normalization else "SKIP"

    log(f"   Current: {before_lufs:.1f} LUFS")
    log(f"   Target:  {TARGET_LUFS:.1f} LUFS (Toleranz ±{LUFS_TOLERANCE:.1f})")
    log(f"   Delta:   {delta:+.1f}")
    log(f"   Action:  {result['action']}")

    if not needs_normalization:
        result["status"] = "SKIPPED_ALREADY_NORMALIZED"
        result["after_lufs"] = before_lufs
        result["after_true_peak"] = measured["true_peak"]
        result["codec_after"] = result["codec_before"]
        result["bitrate_after"] = result["bitrate_before"]
        result["sample_rate_after"] = result["sample_rate_before"]
        result["channels_after"] = result["channels_before"]
        result["duration_after"] = result["duration_before"]
        result["cover_after_sha256"] = result["cover_before_sha256"]
        log(f"   ⚪ SKIPPED_ALREADY_NORMALIZED")
        return result

    if dry_run:
        result["status"] = "NORMALIZE" if needs_normalization else "SKIPPED_ALREADY_NORMALIZED"
        log(f"   🔒 DRY-RUN: keine Datei veraendert")
        return result

    # Backup VOR dem Aufruf - Absicherung gegen den im Modul-Docstring
    # dokumentierten AudioEnhancer-Cover-Stream-Defekt (leere Datei bei
    # Erfolg=True). Aenderung ist ausschliesslich hier in diesem Script,
    # nicht an AudioEnhancer selbst.
    backup_path = path.with_name(f".{path.name}.lufs_backup")
    shutil.copy2(path, backup_path)

    try:
        success = AudioEnhancer.normalize_loudness(str(path), target_lufs=TARGET_LUFS)
    except Exception as e:
        backup_path.replace(path)
        result["status"] = "FAILED"
        result["error"] = (
            f"AudioEnhancer.normalize_loudness() warf: {e} "
            f"(Original-Datei aus Backup wiederhergestellt)"
        )
        log(f"   ❌ FAILED: {result['error']}")
        return result

    if not success:
        backup_path.unlink(missing_ok=True)
        result["status"] = "FAILED"
        result["error"] = "AudioEnhancer.normalize_loudness() lieferte False"
        log(f"   ❌ FAILED: {result['error']}")
        return result

    if not _is_file_intact(path):
        # Bekannter AudioEnhancer-Defekt ausgeloest (siehe Modul-Docstring):
        # normalize_loudness() meldete True, hat die Datei aber leer/
        # unlesbar hinterlassen. Original-Datei aus dem Backup wiederherstellen
        # statt den Datenverlust stehen zu lassen.
        backup_path.replace(path)
        result["status"] = "FAILED"
        result["error"] = (
            "AudioEnhancer.normalize_loudness() hat die Datei beschaedigt/leer "
            "hinterlassen, obwohl es True zurueckgab (bekannter Defekt - siehe "
            "Modul-Docstring: FFmpeg versucht ohne '-map 0:a'/'-vn' auch das "
            "eingebettete Cover als Videostream zu re-encodieren, was im "
            "ipod/mp4-Container fehlschlaegt). Original-Datei aus Backup "
            "wiederhergestellt - kein Datenverlust."
        )
        log(f"   ❌ FAILED: {result['error']}")
        return result

    backup_path.unlink(missing_ok=True)
    result["audio_reencoding"] = True

    remeasured = measure_loudness(path)
    stream_after = ffprobe_stream_info(path)
    meta_after = snapshot_metadata(path)

    result["after_lufs"] = remeasured.get("integrated_lufs")
    result["after_true_peak"] = remeasured.get("true_peak")
    result["codec_after"] = stream_after.get("codec")
    result["bitrate_after"] = stream_after.get("bitrate")
    result["sample_rate_after"] = stream_after.get("sample_rate")
    result["channels_after"] = stream_after.get("channels")
    result["duration_after"] = stream_after.get("duration")
    result["cover_after_sha256"] = meta_after.get("cover_sha256")

    try:
        if result["duration_before"] is not None and result["duration_after"] is not None:
            delta_dur = abs(float(result["duration_after"]) - float(result["duration_before"]))
            result["duration_delta_seconds"] = delta_dur
            if delta_dur > DURATION_WARN_SECONDS:
                result["duration_warning"] = True
    except (TypeError, ValueError):
        pass

    result["metadata_diff"] = diff_metadata(meta_before, meta_after)
    result["cover_lost"] = bool(meta_before.get("cover_present")) and not meta_after.get("cover_present")

    if result["cover_lost"]:
        result["status"] = "FAILED_METADATA_INTEGRITY"
        result["error"] = "Cover ging beim Re-Encoding verloren"
        log(f"   ❌ FAILED_METADATA_INTEGRITY: Cover verloren")
    else:
        result["status"] = "NORMALIZED"
        log(
            f"   ✅ NORMALIZED: {result['after_lufs']:.1f} LUFS "
            f"(Ziel {TARGET_LUFS:.1f} ±{LUFS_TOLERANCE:.1f})"
        )

    log(f"   Audio re-encoding: YES")
    log(f"   Codec: {result['codec_before']} -> {result['codec_after']}")
    log(f"   Bitrate: {result['bitrate_before']} -> {result['bitrate_after']}")
    if result["duration_warning"]:
        log(
            f"   ⚠️  Duration-Abweichung: {result['duration_before']}s -> "
            f"{result['duration_after']}s (Δ{result['duration_delta_seconds']:.2f}s)"
        )
    if result["metadata_diff"]:
        log(f"   ⚠️  Metadata-Diff: {result['metadata_diff']}")

    return result


# ─────────────────────────────────────────────────────────────────────────
# main()
# ─────────────────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Nur analysieren - keine Datei veraendern",
    )
    parser.add_argument(
        "--path", default=str(ALLOWED_ROOT),
        help=f"Zu verarbeitendes Verzeichnis (Standard: {ALLOWED_ROOT}). "
             f"Muss innerhalb von {ALLOWED_ROOT} liegen.",
    )
    args = parser.parse_args(argv)

    try:
        scan_root = validate_scan_root(Path(args.path))
    except PathSafetyError as e:
        log(f"❌ PATH SAFETY: {e}")
        return 2

    log("🔊 LUFS REPROCESSING" + (" – DRY RUN" if args.dry_run else ""))
    log("")
    log(f"Scan-Root: {scan_root}")
    log(f"Target: {TARGET_LUFS:.1f} LUFS")
    log(f"Tolerance: {LUFS_TOLERANCE:.1f} LUFS")

    structure_before = snapshot_directory_tree(scan_root)

    files = sorted(
        p for p in scan_root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    log(f"\nFiles scanned: {len(files)}")

    results = []
    for path in files:
        results.append(process_file(path, scan_root, args.dry_run))

    structure_after = snapshot_directory_tree(scan_root)
    structure_ok = structure_before == structure_after

    normalized = [r for r in results if r["status"] == "NORMALIZED"]
    skipped = [r for r in results if r["status"] == "SKIPPED_ALREADY_NORMALIZED"]
    would_normalize = [r for r in results if r["status"] == "NORMALIZE"]
    failed = [r for r in results if r["status"] in ("FAILED", "FAILED_METADATA_INTEGRITY")]
    safety_blocked = [r for r in results if r["status"] == "SAFETY_BLOCKED"]
    measurement_failed = [r for r in results if r["status"] == "MEASUREMENT_FAILED"]
    metadata_integrity_ok = not any(r["metadata_diff"] for r in results if r["status"] == "NORMALIZED")
    metadata_integrity_ok = metadata_integrity_ok and not any(r["cover_lost"] for r in results)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scan_root": str(scan_root),
        "dry_run": args.dry_run,
        "target_lufs": TARGET_LUFS,
        "tolerance": LUFS_TOLERANCE,
        "files_scanned": len(files),
        "normalized": len(normalized),
        "would_normalize": len(would_normalize),
        "skipped": len(skipped),
        "failed": len(failed),
        "safety_blocked": len(safety_blocked),
        "measurement_failed": len(measurement_failed),
        "metadata_integrity": "PASS" if metadata_integrity_ok else "FAIL",
        "structure_integrity": "PASS" if structure_ok else "FAIL",
        "results": results,
    }

    try:
        REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        log(f"\n📄 Report: {REPORT_JSON_PATH}")
    except OSError as e:
        log(f"⚠️  Report konnte nicht geschrieben werden: {e}")

    path_safety_ok = len(safety_blocked) == 0

    log("\n" + "=" * 60)
    log("LUFS TEST REPROCESSING")
    log("=" * 60)
    log("")
    log(f"Target: {TARGET_LUFS:.1f} LUFS")
    log(f"Tolerance: {LUFS_TOLERANCE:.1f} LUFS")
    log("")
    log(f"Scanned: {len(files)}")
    if args.dry_run:
        log(f"Already normalized: {len(skipped)}")
        log(f"Needs normalization: {len(would_normalize)}")
    else:
        log(f"Normalized: {len(normalized)}")
        log(f"Skipped: {len(skipped)}")
    log(f"Failed: {len(failed)}")
    log("")
    log(f"Metadata integrity: {'PASS' if metadata_integrity_ok else 'FAIL'}")
    log(f"Structure integrity: {'PASS' if structure_ok else 'FAIL'}")
    log(f"Path safety: {'PASS' if path_safety_ok else 'FAIL'}")

    overall_pass = (
        not failed and not safety_blocked and not measurement_failed
        and structure_ok and metadata_integrity_ok
    )
    log(f"\nOverall: {'PASS' if overall_pass else 'FAIL'}")

    if safety_blocked or not structure_ok:
        return 2
    if failed or measurement_failed:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as _fatal_err:
        # Exit-Code 3: schwerer Initialisierungsfehler (z.B. ffmpeg/ffprobe
        # nicht auf PATH, unerwarteter Absturz ausserhalb der pro-Datei-
        # Fehlerbehandlung in process_file()). Ein Fehler bei EINER Datei
        # fuehrt NICHT hierher (siehe process_file()s eigenes try/except),
        # nur ein Fehler, der main() selbst am Weiterlaufen hindert.
        log(f"❌ SCHWERER INITIALISIERUNGSFEHLER: {_fatal_err}")
        sys.exit(3)
