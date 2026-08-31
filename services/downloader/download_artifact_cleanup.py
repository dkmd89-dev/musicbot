# services/downloader/download_artifact_cleanup.py
# -*- coding: utf-8 -*-
"""
Cleanup fuer verwaiste Download-Artefakte in Config.DOWNLOAD_DIR.

Ersetzt das nie aktivierte, in ARCH-003/P-1 entfernte
FileUtils.clean_temp_files() (siehe
docs/archive/arch/MusicBot_ARCH-003_Services_Phase1_Analyse.md). Der alte Name war
irrefuehrend: betroffen ist Config.DOWNLOAD_DIR, nicht Config.TEMP_DIR
(TEMP_DIR hat repo-weit keine einzige echte Datei-Operation).

Zwei unabhaengige Strategien:

  - cleanup_single_download_artifact() (Strategie C, primaer): gezielter
    Cleanup EINER konkreten Datei im Fehlerpfad von
    EnhancedMetadataProcessor.process_single_track() - dort ist zum
    Zeitpunkt des Fehlers exakt bekannt, welche Datei betroffen ist.

  - cleanup_download_artifacts() (Strategie A, Fallback): konservativer
    Sweep beim Bot-Start fuer Reste, die Strategie C nicht abdeckt (z.B.
    ein gescheiterter yt-dlp-Download, bevor process_single_track()
    ueberhaupt aufgerufen wird). Nur aufrufen, bevor der Bot mit
    start_polling() beginnt, Updates zu verarbeiten - dann ist garantiert
    kein Download aktiv.

Bewusst NICHT abgedeckt: .part/.ytdl-Dateien werden von
cleanup_download_artifacts() nie angefasst (siehe Docstring dort).
"""

import time
from pathlib import Path
from typing import Optional

# Endungen, die garantiert aus der Downloadpipeline stammen (siehe
# download_executor.py::build_ydl_opts/download_single_track,
# config.py YDL_OPTS). .part/.ytdl sind bewusst NICHT enthalten.
_KNOWN_ARTIFACT_SUFFIXES = (
    ".m4a",
    ".mp3",
    ".webm",
    ".opus",
    ".info.json",
    ".jpg",
    ".webp",
)


def _is_within_directory(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def cleanup_single_download_artifact(
    original_path: Optional[Path],
    download_dir: Optional[Path],
    logger,
) -> None:
    """
    Strategie C: raeumt eine einzelne, konkret gescheiterte Download-Datei
    (+ zugehoerige .info.json, falls vorhanden) auf.

    Sicherheitsregeln:
      - No-op, wenn original_path oder download_dir None ist (z.B. ein
        Config-Fake in Tests ohne DOWNLOAD_DIR-Attribut), original_path
        nicht (mehr) existiert, oder ausserhalb von download_dir liegt.
        Letzteres deckt insbesondere den Fall ab, dass move_to_library()
        vor dem Fehler bereits gelaufen ist - die Datei existiert dann am
        alten Pfad nicht mehr und wird korrekt uebersprungen.
      - Fehler beim Loeschen werden nur geloggt, nie weitergereicht - ein
        Cleanup-Fehler darf die eigentliche Fehlermeldung des Aufrufers
        nicht verdecken.
    """
    if original_path is None or download_dir is None:
        return

    try:
        original_path = Path(original_path)
        download_dir = Path(download_dir)

        if not original_path.exists():
            return
        if not _is_within_directory(original_path, download_dir):
            logger.debug(
                f"🧹 [CLEANUP] Ueberspringe {original_path} - liegt ausserhalb "
                f"von {download_dir}"
            )
            return

        original_path.unlink()
        logger.info(f"🧹 [CLEANUP] Verwaiste Download-Datei entfernt: {original_path}")

        info_json = original_path.with_suffix(".info.json")
        if info_json.exists() and _is_within_directory(info_json, download_dir):
            info_json.unlink()
            logger.info(f"🧹 [CLEANUP] Zugehoerige .info.json entfernt: {info_json}")

    except Exception as e:
        logger.warning(
            f"⚠️ [CLEANUP] Aufraeumen von {original_path} fehlgeschlagen "
            f"(nicht kritisch): {e}"
        )


def cleanup_download_artifacts(
    download_dir: Path,
    logger,
    max_age_hours: float = 24.0,
) -> int:
    """
    Strategie A: konservativer Start-Sweep. Nur aufrufen, bevor der Bot
    start_polling() erreicht - dann ist garantiert kein Download aktiv.

    Sicherheitsregeln:
      - Nur direkte Kinder von download_dir, nicht rekursiv, Verzeichnisse
        werden uebersprungen.
      - Nur bekannte Downloadpipeline-Endungen
        (_KNOWN_ARTIFACT_SUFFIXES) - alles andere bleibt unangetastet.
      - .part/.ytdl-Dateien werden NIE geloescht, auch nicht bei hohem
        Alter - das Kernrisiko (fertige, aber nie verschobene Dateien)
        ist bereits ueber die Endungs-Whitelist abgedeckt, der Zusatznutzen
        eines .part-Cleanups waere gering, das Risiko unnoetig.
      - Nur Dateien aelter als max_age_hours (mtime).

    Gibt die Anzahl geloeschter Dateien zurueck.
    """
    download_dir = Path(download_dir)
    if not download_dir.exists():
        return 0

    now = time.time()
    max_age_seconds = max_age_hours * 3600
    deleted = 0

    for entry in download_dir.iterdir():
        if not entry.is_file():
            continue
        if not entry.name.endswith(_KNOWN_ARTIFACT_SUFFIXES):
            continue

        try:
            age_seconds = now - entry.stat().st_mtime
        except OSError:
            continue

        if age_seconds <= max_age_seconds:
            continue

        try:
            entry.unlink()
            deleted += 1
            logger.info(
                f"🧹 [CLEANUP] Verwaistes Artefakt entfernt "
                f"({age_seconds / 3600:.1f}h alt): {entry}"
            )
        except Exception as e:
            logger.warning(f"⚠️ [CLEANUP] Konnte {entry} nicht loeschen: {e}")

    if deleted:
        logger.info(
            f"🧹 [CLEANUP] Start-Cleanup abgeschlossen: {deleted} Artefakt(e) entfernt"
        )
    else:
        logger.debug("🧹 [CLEANUP] Start-Cleanup: keine verwaisten Artefakte gefunden")

    return deleted
