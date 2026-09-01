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
    ) -> Tuple[Path, bool]:
        """
        Verschiebt eine Datei von PROCESSED_DIR in die Library-Struktur.
        Podcast-Dateien landen automatisch in self._podcast_dir.

        Gibt (final_target, renamed_due_to_conflict) zurück - Letzteres ist
        True, wenn der berechnete Zielname bereits existierte und die Datei
        deshalb mit " (N)"-Suffix abgelegt wurde (siehe P1-Fund, Post-
        Baseline-v4 Health & Risk Audit, Finding 2: dieses Signal wurde
        vorher gar nicht erst zurückgegeben, der darauf wartende Cleanup in
        klassen/download_handler.py war dadurch toter Code).
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

        # TOCTOU-Fix (Baseline v6 Technical Debt): eine reine .exists()-
        # Pruefung vor dem spaeteren Path.replace() konnte das Fenster
        # zwischen Pruefung und tatsaechlichem Schreiben nicht schliessen -
        # bei zwei Prozessen, die zufaellig denselben Zielnamen berechnen
        # (z.B. der laufende Bot + ein gleichzeitig manuell gestarteter
        # scripts/reprocess_artist_metadata.py-Lauf, der bewusst dieselbe
        # move_to_library()-Implementierung wiederverwendet), konnten beide
        # die Pruefung passieren, bevor einer geschrieben hatte - der
        # Verlierer wurde durch das anschliessende Path.replace() dann
        # stillschweigend ueberschrieben (Datenverlust, keine Korruption -
        # das Copy+Rename-Muster aus FINDING-6 schuetzt bereits davor).
        # os.O_EXCL beansprucht den jeweiligen Kandidatennamen atomar auf
        # Betriebssystemebene (funktioniert damit auch prozessuebergreifend,
        # kein reiner In-Prozess-Lock) - bei Kollision wird der naechste
        # Kandidat probiert, exakt dieselbe "(N)"-Namenskonvention wie
        # bisher.
        final_target = None
        attempt = 0
        while final_target is None:
            candidate = (
                target_path
                if attempt == 0
                else target_path.with_name(
                    f"{target_path.stem} ({attempt}){target_path.suffix}"
                )
            )
            try:
                claim_fd = os.open(
                    str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
                os.close(claim_fd)
                final_target = candidate
            except FileExistsError:
                attempt += 1

        renamed_due_to_conflict = final_target != target_path
        if renamed_due_to_conflict:
            self.logger.warning(
                f"⚠️ [LIBRARY] Name existiert — umbenannt zu: {final_target.name}"
            )

        # FINDING-6 (docs/archive/MusicBot_PHASE4_FAILURE_PATH_AUDIT.md): shutil.move()
        # nutzt os.rename() (atomar) nur, wenn Quelle und Ziel auf demselben
        # Dateisystem liegen - DOWNLOAD_DIR und LIBRARY_DIR liegen in der
        # tatsaechlichen Konfiguration (config.py) auf unterschiedlichen
        # Mountpoints, wodurch shutil.move() intern auf copy2()+unlink()
        # zurueckfaellt. Ein Prozessabbruch waehrend dieses Kopiervorgangs
        # konnte eine unvollstaendige Datei am Zielpfad hinterlassen. Fix:
        # in eine temporaere Datei IM Zielverzeichnis kopieren (garantiert
        # dasselbe Dateisystem wie final_target), dann atomar per
        # Path.replace() an den finalen Namen umbenennen - final_target
        # existiert dadurch nie in einem unvollstaendigen Zustand.
        tmp_target = final_target.with_name(
            f".{final_target.name}.tmp_{int(time.time() * 1000)}"
        )
        try:
            shutil.copy2(str(source_path), str(tmp_target))
            tmp_target.replace(final_target)
        except Exception as e:
            self.logger.error(
                f"❌ [LIBRARY] Fehler beim Verschieben: {e}", exc_info=True
            )
            try:
                tmp_target.unlink(missing_ok=True)
            except OSError:
                pass
            # final_target wurde oben per os.O_EXCL bereits als leere Datei
            # geclaimt (0 Bytes) - schlaegt der eigentliche Copy+Replace-
            # Schritt fehl, darf dieser leere Platzhalter nicht in der
            # Library liegen bleiben (Path.replace() ist atomar: entweder
            # es lief vollstaendig durch, oder final_target haelt hier noch
            # unveraendert den leeren Claim).
            try:
                final_target.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        try:
            source_path.unlink()
        except OSError as e:
            # Datei ist bereits sicher am Zielpfad - ein fehlgeschlagenes
            # Aufraeumen der jetzt redundanten Quelldatei darf die
            # erfolgreiche Verschiebung nicht nachtraeglich zum Fehlschlag
            # machen (gleiches Prinzip wie cleanup_single_download_artifact()).
            self.logger.warning(
                f"⚠️ [LIBRARY] Datei verschoben, Quelldatei konnte aber "
                f"nicht entfernt werden: {source_path} ({e})"
            )

        self.logger.info(f"✅ [LIBRARY] Datei verschoben nach: {final_target}")
        return final_target, renamed_due_to_conflict

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

    def fix(self, text: str) -> str:
        """Einfacher Wrapper um sanitize_filename()."""
        return sanitize_filename(str(text or ""))
