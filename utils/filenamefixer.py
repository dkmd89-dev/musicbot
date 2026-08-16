# utils/filenamefixer.py
# -*- coding: utf-8 -*-
"""
FilenameFixerTool  –  Organisiert Medien in der Library-Struktur.

ÄNDERUNGEN v2.1 (PODCAST_DIR):
  • Podcast-Episoden landen jetzt in einem eigenen Root-Verzeichnis (self._podcast_dir),
    das aus Config.PODCAST_DIR_RESOLVED bzw. der Umgebungsvariable PODCAST_DIR stammt.
  • Vorher: /mnt/musik_bilder/library/Podcast/<Kanal>/<Titel>.m4a   ← FALSCH
  • Jetzt:  /mnt/musik_bilder/Podcast/<Kanal>/<Titel>.m4a           ← KORREKT
  • Compilations und Playlist bleiben unverändert unter LIBRARY_DIR.
  • Der Wert ist vollständig über .env konfigurierbar (PODCAST_DIR=/dein/pfad).
"""

import re
import os
import time
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Optional, Tuple, List, Callable, Dict
from dataclasses import dataclass
from datetime import datetime
import mutagen

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from config import Config
from utils.helpers import verify_file, safe_rename, sanitize_filename
from utils.singleton import SingletonMixin

# ─────────────────────────────────────────────────────────────────────────────
# SPECIAL CHANNEL YAML LOADER
# ─────────────────────────────────────────────────────────────────────────────


def load_special_channels_from_yaml(mapping_dir: Path) -> Dict[str, List[str]]:
    """
    Lädt die Spezialkanal-Konfiguration aus mapping/special_channel.yaml.

    Gibt ein Dict zurück, das dem bisherigen Config.SPECIAL_CHANNELS-Format entspricht:
        { "Compilations": ["Deep Territory", "MrRevillz", ...], ... }

    Warum YAML statt config.py:
      - Neue Kanäle können ohne Bot-Neustart hinzugefügt werden
      - Konsistent mit channel_genre.yaml, artist_genre.yaml etc.
      - Kein Python-Code für reine Datenpflege nötig

    Fallback:
      Wenn die Datei fehlt oder nicht gelesen werden kann, wird ein leeres
      Dict zurückgegeben. Der Aufrufer (FilenameFixerTool.__init__) verwendet
      dann Config.SPECIAL_CHANNELS als Fallback.
    """
    if not _YAML_AVAILABLE:
        return {}

    yaml_path = Path(mapping_dir) / "special_channel.yaml"
    if not yaml_path.exists():
        return {}

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        from collections import OrderedDict

        result = OrderedDict()

        raw_channels = data.get("SPECIAL_CHANNELS", {}) if data else {}

        for category, channels in raw_channels.items():
            if isinstance(channels, list):
                result[category] = [str(c).strip() for c in channels if c]
            elif channels:
                result[category] = [str(channels).strip()]

        return result

    except Exception as e:
        logging.getLogger("filenamefixer").error(f"Fehler beim Laden: {e}")
        return {}


def load_special_channels_merged(config) -> Dict[str, List[str]]:
    """
    Hilfsfunktion für Module die keinen FilenameFixerTool haben (z.B. download_utils,
    enhanced_metadata_processor beim Spezialkanal-Check).

    Lädt SPECIAL_CHANNELS aus YAML (bevorzugt) oder Config (Fallback) und gibt
    das gemergte Dict zurück. Nutzt dasselbe Merge-Verfahren wie FilenameFixerTool.

    Verwendung:
        special_cfg = load_special_channels_merged(self.config)
        info = get_special_channel_info(channel_name, special_cfg)
    """
    mapping_dir = getattr(config, "GENRE_MAPPING_DIR", Path("mapping"))
    yaml_channels = load_special_channels_from_yaml(mapping_dir)
    config_channels = getattr(config, "SPECIAL_CHANNELS", {})

    if not yaml_channels:
        return config_channels

    merged: Dict[str, List[str]] = {}
    for cat in set(yaml_channels) | set(config_channels):
        yaml_list = yaml_channels.get(cat, [])
        config_list = config_channels.get(cat, [])
        seen = {c.lower() for c in yaml_list}
        extra = [c for c in config_list if c.lower() not in seen]
        merged[cat] = yaml_list + extra
    return merged


def _normalize_channel_name(channel_name: str) -> str:
    """
    Bereinigt Channel-Namen von yt-dlp-typischen Präfixen wie 'by '.

    Beispiele:
        'by HighOnTracks'   → 'HighOnTracks'
        'By Deep Territory' → 'Deep Territory'
        'HighOnTracks'      → 'HighOnTracks'  (unverändert)
    """
    if not channel_name:
        return channel_name
    return re.sub(r"^by\s+", "", channel_name.strip(), flags=re.IGNORECASE).strip()


def get_special_channel_info(
    channel_name: str, special_channels_config: dict
) -> Optional[Tuple[str, str]]:
    """
    Alias für get_special_channel_info_prioritized (Rückwärtskompatibel)
    """
    return get_special_channel_info_prioritized(channel_name, special_channels_config)


def get_special_channel_info_prioritized(
    channel_name: str, special_channels_config: dict
) -> Optional[Tuple[str, str]]:
    """
    Durchsucht die Kategorien in der REIHENFOLGE der Config.
    Die erste gefundene Kategorie gewinnt.
    """
    if not channel_name:
        return None

    normalized = _normalize_channel_name(channel_name).lower()
    raw_lower = channel_name.lower().strip()

    for category, channels in special_channels_config.items():
        for c in channels:
            c_lower = c.lower().strip()
            if raw_lower == c_lower or normalized == c_lower:
                return category, c
            if c_lower in raw_lower or c_lower in normalized:
                return category, c

    return None


def get_special_category(
    channel_name: str, special_channels_config: dict
) -> Optional[str]:
    """
    Sucht die spezielle Kategorie für einen Kanalnamen.
    """
    result = get_special_channel_info(channel_name, special_channels_config)
    return result[0] if result else None


@dataclass
class FixerStats:
    total: int = 0
    fixed: int = 0
    skipped: int = 0
    moved_to_fail: int = 0


class FilenameFixerTool(SingletonMixin):
    """
    Organisiert Medien-Dateien in einer festgelegten Library-Struktur.
    Der Logger wird per Dependency Injection in diese Klasse injiziert.

    Verzeichnis-Schema:
      Musik-Library  : LIBRARY_DIR/<Artist>/<Jahr - Album>/<Track>.m4a
      Compilations   : LIBRARY_DIR/Compilations/<Kanal>/<Artist> - <Titel>.m4a
      Playlist       : LIBRARY_DIR/Playlist/<Name>/<Artist> - <Titel>.m4a
      Podcasts       : PODCAST_DIR/<Kanal>/<Episodentitel>.m4a      ← eigener Root!

    PODCAST_DIR stammt aus (Priorität absteigend):
      1. Umgebungsvariable / .env:  PODCAST_DIR=/dein/pfad
      2. Config.PODCAST_DIR_RESOLVED → Config.PODCAST_DIR (Klassenwert)
      3. Sicherer Fallback:          LIBRARY_DIR/Podcast
    """

    def _do_init(self, config: Config, logger_factory: Optional[Callable] = None):
        """
        Wird NUR beim ersten FilenameFixerTool()-Aufruf ausgeführt.
        """
        self.config = config

        # Logger
        self.logger = (
            logger_factory("filenamefixer")
            if logger_factory
            else self._get_default_logger()
        )

        # Verzeichnisse
        self.library_dir = Path(self.config.LIBRARY_DIR)
        self.stats = FixerStats()
        self.fail_dir = Path(self.config.FAIL_DIR)
        self.processed_dir = Path(self.config.PROCESSED_DIR)
        self.temp_dir = Path(self.config.TEMP_DIR)

        for d in [self.library_dir, self.fail_dir, self.processed_dir, self.temp_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # PODCAST_DIR
        _podcast_dir_env = os.getenv("PODCAST_DIR", "").strip()
        if _podcast_dir_env:
            self._podcast_dir = Path(_podcast_dir_env)
            self.logger.info(
                f"🎙️ [PODCAST_DIR] Aus Umgebungsvariable: {self._podcast_dir}"
            )
        elif hasattr(config, "PODCAST_DIR_RESOLVED"):
            self._podcast_dir = config.PODCAST_DIR_RESOLVED
            self.logger.info(
                f"🎙️ [PODCAST_DIR] Aus Config.PODCAST_DIR_RESOLVED: {self._podcast_dir}"
            )
        elif hasattr(config, "PODCAST_DIR"):
            self._podcast_dir = Path(config.PODCAST_DIR)
            self.logger.info(
                f"🎙️ [PODCAST_DIR] Aus Config.PODCAST_DIR: {self._podcast_dir}"
            )
        else:
            self._podcast_dir = self.library_dir / "Podcast"
            self.logger.warning(
                f"⚠️ [PODCAST_DIR] Kein PODCAST_DIR in Config/Env gefunden – Fallback: {self._podcast_dir}"
            )

        self._podcast_dir.mkdir(parents=True, exist_ok=True)

        # SPECIAL_CHANNELS
        _mapping_dir = getattr(self.config, "GENRE_MAPPING_DIR", Path("mapping"))
        _yaml_channels = load_special_channels_from_yaml(_mapping_dir)
        _config_channels = getattr(self.config, "SPECIAL_CHANNELS", {})

        if _yaml_channels:
            merged: Dict[str, List[str]] = {}
            all_categories = set(_yaml_channels) | set(_config_channels)
            for cat in all_categories:
                yaml_list = _yaml_channels.get(cat, [])
                config_list = _config_channels.get(cat, [])
                seen = {c.lower() for c in yaml_list}
                extra = [c for c in config_list if c.lower() not in seen]
                merged[cat] = yaml_list + extra
            self._special_channels = merged
            self.logger.info(
                f"⭐ SPECIAL_CHANNELS aus YAML geladen ({sum(len(v) for v in self._special_channels.values())} Kanäle gesamt)"
            )
        else:
            self._special_channels = _config_channels
            if _config_channels:
                self.logger.info(
                    f"⭐ SPECIAL_CHANNELS aus Config.SPECIAL_CHANNELS geladen ({sum(len(v) for v in self._special_channels.values())} Kanäle)"
                )

        self._BATCH_SIZE = 10
        self.logger.info("✅ FilenameFixerTool initialisiert.")

    def _get_default_logger(self):
        """Fallback-Logger wenn keine Factory injiziert wurde"""
        from logger import get_module_logger

        return get_module_logger("filename_fixer")

    def move_to_library(
        self,
        source_path: Path,
        artist: str = None,
        album: str = None,
        title: str = None,
        year: str = None,
        track_number: int = None,
        uploader: str = None,
        is_single: bool = False,
    ) -> Path:
        """
        Verschiebt eine Datei von PROCESSED_DIR in die Library-Struktur.
        Podcast-Dateien landen automatisch in self._podcast_dir.
        """
        if not source_path or not Path(source_path).exists():
            self.logger.error(f"❌ [LIBRARY] Quelldatei nicht gefunden: {source_path}")
            raise FileNotFoundError(f"Source file not found: {source_path}")

        ext = source_path.suffix.lstrip(".")
        safe_artist = artist or "Unknown Artist"
        safe_album = album or "Unknown Album"
        safe_title = title or source_path.stem
        safe_year = year or ""

        if is_single:
            self.logger.info(
                "🎯 [SINGLE-MODE] Einzelner Download erkannt → verwende Singles-Struktur (Album-Tag bleibt original)"
            )

        target_path = self.build_final_path(
            artist=safe_artist,
            title=safe_title,
            album=safe_album,
            year=safe_year,
            track_number=track_number,
            extension=ext,
            uploader=uploader or "",
            is_single_download=is_single,
        )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger.debug(f"📍 [LIBRARY] Zielpfad: {target_path}")

        final_target = target_path
        counter = 1
        while final_target.exists():
            final_target = target_path.with_name(
                f"{target_path.stem} ({counter}){target_path.suffix}"
            )
            counter += 1
        if final_target != target_path:
            self.logger.warning(
                f"⚠️ [LIBRARY] Name existiert — umbenannt zu: {final_target.name}"
            )

        try:
            shutil.move(str(source_path), str(final_target))
            self.logger.info(f"✅ [LIBRARY] Datei verschoben nach: {final_target}")
            return final_target
        except Exception as e:
            self.logger.error(
                f"❌ [LIBRARY] Fehler beim Verschieben: {e}", exc_info=True
            )
            raise

    def _ensure_within_roots(self, path: Path) -> Path:
        """
        Sicherheitsnetz gegen Directory Traversal (Defense in Depth zusaetzlich
        zu sanitize_filename): stellt sicher, dass ein per build_final_path()
        berechneter Zielpfad tatsaechlich unterhalb von library_dir oder
        _podcast_dir liegt, bevor er zurueckgegeben wird.
        """
        resolved = path.resolve()
        for root in (self.library_dir, self._podcast_dir):
            try:
                if resolved.is_relative_to(root.resolve()):
                    return path
            except OSError:
                continue
        self.logger.error(
            f"🚨 [SECURITY] Zielpfad verlaesst library_dir/_podcast_dir: {resolved}"
        )
        raise ValueError(
            f"Berechneter Zielpfad liegt außerhalb der Library-Verzeichnisse: {resolved}"
        )

    def build_final_path(
        self,
        artist: str,
        title: str,
        album: str = "Unknown Album",
        year: str = "",
        track_number: Optional[int] = None,
        extension: str = "m4a",
        uploader: str = "",
        is_single_download: bool = False,
    ) -> Path:
        """
        Erzeugt den finalen Zielpfad für eine Audiodatei basierend auf
        Metadaten und Library-Schema.

        Podcast-Routing (v2.1):
          Kategorie "Podcast" → self._podcast_dir  (kein library_dir-Prefix!)
          Alle anderen         → self.library_dir   (unverändert)
        """

        def clean(s: str) -> str:
            return re.sub(r'[\\/:*?"<>|]', "", s).strip()

        artist = clean(artist) or "Unknown Artist"

        def extract_main_artist(artist_str: str) -> str:
            parts = re.split(
                r"\s*(?:,|&| feat\.?| ft\.?| x )\s*", artist_str, flags=re.IGNORECASE
            )
            return parts[0].strip() if parts else artist_str

        library_artist = extract_main_artist(artist)
        title = clean(title) or "Unknown Title"
        album = clean(album) or "Unknown Album"
        uploader = clean(uploader)
        year = re.sub(r"[^\d]", "", str(year or "")).strip()

        special_channels_config = self._special_channels

        normalized_uploader = _normalize_channel_name(uploader)
        channel_info = get_special_channel_info(
            normalized_uploader, special_channels_config
        )

        if channel_info:
            category, canonical_channel = channel_info

            # ─────────────────────────────────────────────────────────────────
            # PODCAST-ZWEIG  (v2.1 — geänderter Root-Pfad)
            #
            # VORHER: self.library_dir / category / canonical_channel / ...
            #         → /mnt/musik_bilder/library/Podcast/Sky Sport Formel 1/...
            #
            # JETZT:  self._podcast_dir / canonical_channel / ...
            #         → /mnt/musik_bilder/Podcast/Sky Sport Formel 1/...
            #
            # "category" taucht im Pfad nicht mehr auf, da self._podcast_dir
            # bereits den Podcast-Root darstellt.
            # ─────────────────────────────────────────────────────────────────
            if category.lower() == "podcast":
                original_title = title

                # Episodennummer aus Titel extrahieren (z.B. "17/2026 - Titel")
                episode_number = ""
                display_title = original_title

                if original_title and "/" in original_title:
                    # Titel wie "01/2026 - Chaos bei Ferrari..."
                    parts = original_title.split(" - ", 1)
                    if len(parts) >= 1:
                        # Entferne Schrägstrich (z.B. "01/2026" → "012026")
                        episode_number = parts[0].replace("/", "").strip()
                        display_title = parts[1] if len(parts) > 1 else original_title

                filename = (
                    f"{episode_number} - {display_title}.{extension}"
                    if episode_number
                    else f"{display_title}.{extension}"
                )

                # Playlist-Unterordner (z.B. Podcast-Staffel / Playlist-Name)
                # album = canonical_channel bedeutet: kein eigener Unterordner nötig
                _podcast_subdir = (
                    sanitize_filename(album)
                    if album and album.lower() != canonical_channel.lower()
                    else ""
                )

                # ► Kern-Änderung v2.1: self._podcast_dir statt self.library_dir / category
                if _podcast_subdir:
                    special_path = (
                        self._podcast_dir  # z.B. /mnt/musik_bilder/Podcast
                        / canonical_channel  # z.B. Sky Sport Formel 1
                        / _podcast_subdir  # z.B. Backstage Boxengasse
                        / sanitize_filename(filename)
                    )
                    self.logger.debug(
                        f"⭐ Podcast-Pfad: {self._podcast_dir.name}/"
                        f"{canonical_channel}/{_podcast_subdir}/{filename}"
                    )
                else:
                    special_path = (
                        self._podcast_dir  # z.B. /mnt/musik_bilder/Podcast
                        / canonical_channel  # z.B. Sky Sport Formel 1
                        / sanitize_filename(filename)
                    )
                    self.logger.debug(
                        f"⭐ Podcast-Pfad: {self._podcast_dir.name}/"
                        f"{canonical_channel}/{filename}"
                    )

                return self._ensure_within_roots(special_path)

            # ─────────────────────────────────────────────────────────────────
            # COMPILATIONS / PLAYLIST  (unverändert)
            # Format: "Artist - Titel.m4a"
            # ─────────────────────────────────────────────────────────────────
            filename = f"{artist} - {title}.{extension}"
            special_path = (
                self.library_dir
                / category
                / canonical_channel
                / sanitize_filename(filename)
            )
            self.logger.debug(
                f"⭐ Spezialkanal-Regel: {category} / {canonical_channel} "
                f"(raw: '{uploader}') → {special_path}"
            )
            return self._ensure_within_roots(special_path)

        # ─────────────────────────────────────────────────────────────────────
        # STANDARD MUSIK-PFAD  (unverändert)
        # ─────────────────────────────────────────────────────────────────────
        is_single = (
            is_single_download
            or album.lower() in ["single", "singles"]
            or (album.lower() in ["unknown album", ""] and is_single_download)
        )

        if is_single_download:
            self.logger.info(
                f"🎯 [SINGLE-MODE] Erzwinge Singles-Struktur (Album: '{album}')"
            )
        elif album.lower() in ["single", "singles"]:
            self.logger.info(
                f"🎵 [SINGLE-DETECT] Album-Tag '{album}' erkannt → Singles-Struktur"
            )

        if is_single:
            album_folder = (
                self.library_dir / sanitize_filename(library_artist) / "Singles"
            )
            filename = f"{year or '####'} - {title}.{extension}"
            final_path = album_folder / sanitize_filename(filename)
            self.logger.info(f"🎵 [SINGLES] Zielpfad: {final_path}")
        else:
            subdir = f"{year or '####'} - {album}"
            album_folder = (
                self.library_dir
                / sanitize_filename(library_artist)
                / sanitize_filename(subdir)
            )
            filename = (
                f"{int(track_number):02d} - {title}.{extension}"
                if track_number is not None
                else f"00 - {title}.{extension}"
            )
            final_path = album_folder / sanitize_filename(filename)
            self.logger.debug(f"💿 Zielpfad für Album: {final_path}")

        return self._ensure_within_roots(final_path)

    async def organize_file(self, source_path: Path, video_info: dict) -> Path:
        """Organisiert eine heruntergeladene Datei in den Zielordner basierend auf video_info."""
        if not source_path.exists():
            self.logger.error(f"❌ Quelldatei existiert nicht: {source_path}")
            raise FileNotFoundError(f"Source file not found: {source_path}")

        target_folder_name = video_info.get("target_folder", "Standard")
        target_folder = self.library_dir / sanitize_filename(target_folder_name)
        target_folder.mkdir(parents=True, exist_ok=True)
        target_path = target_folder / source_path.name

        self.logger.info(f"📦 Verschiebe {source_path} → {target_path}")
        try:
            await safe_rename(source_path, target_path)
            self.logger.info(f"✅ Erfolgreich verschoben: {target_path}")
            return target_path
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Verschieben: {e}", exc_info=True)
            fail_path = self.fail_dir / source_path.name
            await safe_rename(source_path, fail_path)
            self.logger.warning(f"⚠️ Datei in Fail-Ordner verschoben: {fail_path}")
            return fail_path

    async def fix_and_move_file(
        self, file_path: Path, video_info: dict = None, is_single_download: bool = False
    ) -> Optional[Tuple[Path, Path]]:
        """
        Liest Metadaten aus und verschiebt die Datei in strukturierte Ordner.
        """
        if not file_path.exists() or not file_path.is_file():
            self.logger.error(f"❌ Datei nicht gefunden: {file_path}")
            self.stats.skipped += 1
            return None

        self.stats.total += 1

        if is_single_download:
            self.logger.info(
                f"🎵 [SINGLE-MODE] Bearbeite Einzeldownload: {file_path.name}"
            )
        else:
            self.logger.info(f"📄 Bearbeite Datei: {file_path.name}")

        for attempt in range(4):
            if await verify_file(file_path):
                break
            await asyncio.sleep(0.5)

        try:
            audio = mutagen.File(file_path, easy=True)
            if audio is None:
                raise ValueError("Datei konnte nicht gelesen werden.")
        except Exception as e:
            self.logger.error(f"❌ Metadaten-Fehler: {e}", exc_info=True)
            fail_path = self.fail_dir / file_path.name
            await safe_rename(file_path, fail_path)
            self.stats.moved_to_fail += 1
            return None

        artist = audio.get("artist", ["Unknown Artist"])[0]
        title = audio.get("title", [file_path.stem])[0]
        album = audio.get("album", ["Single"])[0]
        year = audio.get("date") or audio.get("originaldate")
        year = year[0] if year else ""
        track_number_str = audio.get("tracknumber")
        track_number = (
            int(track_number_str[0].split("/")[0]) if track_number_str else None
        )
        uploader = (video_info or {}).get("uploader", "")

        original_album = album
        if is_single_download:
            self.logger.info(
                f"🏷️ [SINGLE-MODE] Album-Tag bleibt '{original_album}' → Ordner wird 'Singles'"
            )

        final_path = self.build_final_path(
            artist=artist,
            title=title,
            album=album,
            year=year,
            track_number=track_number,
            extension=file_path.suffix.lstrip("."),
            uploader=uploader,
            is_single_download=is_single_download,
        )

        final_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            await safe_rename(file_path, final_path)
            self.stats.fixed += 1

            log_msg = (
                f"✅ [SINGLE-MODE] Einzeldownload erfolgreich verschoben: {final_path}"
                if is_single_download
                else f"✅ Datei erfolgreich verschoben: {final_path}"
            )
            self.logger.info(log_msg)

            return file_path, final_path
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Verschieben: {e}", exc_info=True)
            fail_path = self.fail_dir / file_path.name
            await safe_rename(file_path, fail_path)
            self.stats.moved_to_fail += 1
            return None

    async def process_directory(
        self,
        target_dir: Optional[Path] = None,
        single_mode: bool = False,
        return_moved_files: bool = False,
        force_single_structure: bool = False,
    ) -> Optional[List[Tuple[Path, Path]]]:
        """
        Verarbeitet alle Audiodateien im gegebenen Ordner.
        """
        dir_to_process = target_dir or self.processed_dir

        log_msg = (
            f"🎵 [SINGLE-MODE] Starte Verarbeitung mit Singles-Struktur: {dir_to_process}"
            if force_single_structure
            else f"🚀 Starte Verarbeitung: {dir_to_process}"
        )
        self.logger.info(log_msg)

        if not dir_to_process.exists():
            self.logger.error(f"❌ Verzeichnis nicht gefunden: {dir_to_process}")
            return [] if return_moved_files else None

        self.stats = FixerStats()
        audio_exts = self._get_supported_audio_extensions()
        audio_files = [
            f for ext in audio_exts for f in dir_to_process.glob(f"**/*.{ext}")
        ]

        if not audio_files:
            self.logger.info("🔭 Keine passenden Audiodateien gefunden.")
            return [] if return_moved_files else None

        is_single_processing = (
            single_mode or len(audio_files) == 1 or force_single_structure
        )

        if is_single_processing:
            if len(audio_files) == 1:
                self.logger.info(
                    "🎵 [AUTO-SINGLE] Nur eine Datei gefunden → aktiviere Single-Mode automatisch"
                )
            elif force_single_structure:
                self.logger.info(
                    f"🎵 [FORCE-SINGLE] {len(audio_files)} Dateien werden als Singles verarbeitet"
                )

        if single_mode:
            audio_files.sort(key=os.path.getmtime, reverse=True)
            audio_files = [audio_files[0]]

        moved_files = []
        tasks = [
            self.fix_and_move_file(
                f, video_info={}, is_single_download=is_single_processing
            )
            for f in audio_files
        ]
        results = await asyncio.gather(*tasks)

        if return_moved_files:
            moved_files.extend([r for r in results if r])

        self._log_processing_stats(is_single_processing)

        await self._clean_directories()
        return moved_files if return_moved_files else None

    def _log_processing_stats(self, is_single_mode: bool = False):
        """Gibt eine übersichtliche Statistik der Verarbeitung aus."""
        mode_indicator = "🎵 [SINGLE-MODE]" if is_single_mode else "📊"

        self.logger.info(
            f"{mode_indicator} Verarbeitung abgeschlossen: "
            f"✅ {self.stats.fixed} erfolgreich, "
            f"⏭️ {self.stats.skipped} übersprungen, "
            f"❌ {self.stats.moved_to_fail} fehlerhaft "
            f"(von {self.stats.total} gesamt)"
        )

    def _get_supported_audio_extensions(self) -> List[str]:
        """Liest unterstützte Audioendungen aus der Konfiguration oder nutzt Fallback."""
        exts_cfg = getattr(self.config, "SUPPORTED_FORMATS", None)
        exts = (
            [e.lstrip(".").lower() for e in exts_cfg]
            if exts_cfg
            else ["mp3", "m4a", "aac", "ogg", "opus", "wav", "flac", "wma", "alac"]
        )
        exts = sorted(set(exts))
        self.logger.debug(f"🎵 Unterstützte Dateiformate: {exts}")
        return exts

    async def _clean_directories(self):
        """Bereinigt temporäre oder leere Verzeichnisse nach Verarbeitung."""
        try:
            for item in self.temp_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            self.logger.debug("🧹 Temp-Verzeichnis bereinigt")
        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim tmp-Cleanup: {e}")

        try:
            for root, dirs, _ in os.walk(self.processed_dir, topdown=False):
                for d in dirs:
                    target = Path(root) / d
                    if not any(target.iterdir()):
                        target.rmdir()
            self.logger.debug("🧹 Leere Unterordner bereinigt")
        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Löschen leerer Unterordner: {e}")

    def fix(self, text: str) -> str:
        """Einfacher Wrapper um sanitize_filename()."""
        return sanitize_filename(str(text or ""))
