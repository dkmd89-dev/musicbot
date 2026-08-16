# -*- coding: utf-8 -*-
# services/organizer
# Standardbibliotheken
import argparse
import hashlib
import logging
import os
import re
import shutil
import sys
import platform
from datetime import datetime
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from logging.handlers import RotatingFileHandler

# Externe Abhängigkeiten
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen import MutagenError

# Lokale Module
from config import Config
from services.notification_service import NotificationService  # Korrigierter Import

# Logging konfigurieren
logger = logging.getLogger(__name__)


def setup_debug_logging():
    """
    Richtet ein separates Debug-Log ein.
    """
    debug_log_path = Config.LOG_DIR / "debug.log"
    Config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    debug_handler = RotatingFileHandler(
        debug_log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )
    debug_handler.setFormatter(debug_formatter)
    logging.getLogger().addHandler(debug_handler)
    logging.getLogger().setLevel(logging.DEBUG)
    logger.debug("Debug-Logging aktiviert.")


class MusicOrganizer:
    """Intelligente Musikorganisation mit erweiterter Künstlererkennung"""

    def __init__(self, source_dir: Optional[Path] = None):
        self.source_dir = source_dir if source_dir else Config.PROCESSED_DIR
        self.target_dir = Config.LIBRARY_DIR
        self.archive_dir = Config.ARCHIVE_DIR
        self.log_dir = Config.LOG_DIR
        self.file_hashes: Set[str] = set()
        self.stats = {"processed": 0, "duplicates": 0, "errors": 0}
        self.error_log: List[str] = []
        self.moved_files: List[Tuple[str, str, str]] = (
            []
        )  # (original, destination, file_type)

        self.target_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        for special_dir in Config.ORGANIZER_CONFIG["special_dirs"]:
            (self.target_dir / special_dir).mkdir(exist_ok=True)
            logger.debug(f"Spezialverzeichnis '{special_dir}' erstellt oder vorhanden.")

        self.missing_album_log = (
            self.log_dir / Config.ORGANIZER_CONFIG["missing_album_log"]
        )
        if not self.missing_album_log.exists():
            self.missing_album_log.touch()
            logger.info(
                f"Logdatei für fehlende Album-Tags '{self.missing_album_log.name}' erstellt."
            )

        self.created_albums: Set[Path] = set()

        if Config.ORGANIZER_CONFIG["duplicate_check"]:
            self._hashes_initialized = False
            logger.debug("Duplikatsprüfung aktiviert.")
        else:
            self._hashes_initialized = True
            logger.debug("Duplikatsprüfung deaktiviert.")

        logger.info(
            f"MusicOrganizer initialisiert. Quelle: {self.source_dir}, Ziel: {self.target_dir}"
        )

    def _setup_logging(self) -> None:
        """
        Konfiguriert das Haupt-Logging für die Konsole und eine rotierende Datei.
        """
        root_logger = logging.getLogger()

        if not any(
            isinstance(h, RotatingFileHandler)
            and "music_organizer.log" in h.baseFilename
            for h in root_logger.handlers
        ):
            log_formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
            )
            file_handler = RotatingFileHandler(
                Config.LOG_DIR / "music_organizer.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(log_formatter)
            root_logger.addHandler(file_handler)
            logger.debug("FileHandler für 'music_organizer.log' hinzugefügt.")

        if not any(
            isinstance(h, logging.StreamHandler) and h.stream == sys.stdout
            for h in root_logger.handlers
        ):
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(
                logging.Formatter("%(levelname)s - %(message)s")
            )
            root_logger.addHandler(console_handler)
            logger.debug("StreamHandler (Konsole) hinzugefügt.")

        if root_logger.level == logging.NOTSET:
            root_logger.setLevel(logging.INFO)
            logger.debug("Root-Logger Level auf INFO gesetzt.")

    def _reset_stats(self) -> None:
        """Setzt alle Statistiken zurück"""
        self.stats = {"processed": 0, "duplicates": 0, "errors": 0}
        self.error_log = []
        self.moved_files = []
        logger.debug("Statistiken zurückgesetzt.")

    def get_error_samples(self, max_samples: int = 3) -> List[str]:
        """Gibt eine Auswahl von Fehlermeldungen zurück"""
        logger.debug(f"Anfrage für {max_samples} Fehlerbeispiele.")
        return self.error_log[:max_samples]

    @property
    def organization_stats(self) -> Dict[str, int]:
        """Gibt aktuelle Statistiken als Dictionary zurück"""
        logger.debug("Abfrage der Organisationsstatistiken.")
        return self.stats.copy()

    def _load_existing_hashes(self) -> None:
        """Lädt vorhandene Datei-Hashes für Duplikatsprüfung"""
        if not self.target_dir.exists():
            logger.warning(
                f"Zielverzeichnis {self.target_dir} existiert nicht. Keine Hashes zu laden."
            )
            return

        logger.info("Lade vorhandene Datei-Hashes für Duplikatsprüfung...")
        count = 0
        for root, _, files in os.walk(self.target_dir):
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() not in Config.SUPPORTED_FORMATS:
                    logger.debug(
                        f"Datei übersprungen (kein unterstütztes Format): {file_path.name}"
                    )
                    continue
                try:
                    file_hash = self._calculate_file_hash(file_path)
                    self.file_hashes.add(file_hash)
                    count += 1
                except Exception as e:
                    logger.warning(f"Konnte Hash nicht berechnen für {file_path}: {e}")
        logger.info(f"{count} Datei-Hashes geladen.")
        self._hashes_initialized = True

    def _calculate_file_hash(self, file_path: Path) -> str:
        """Berechnet MD5-Hash einer Datei für Duplikatsprüfung"""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            logger.debug(f"Hash berechnet für {file_path.name}")
            return hash_md5.hexdigest()
        except IOError as e:
            logger.error(
                f"Fehler beim Lesen der Datei {file_path} für Hash-Berechnung: {e}"
            )
            raise

    def _is_duplicate(self, file_path: Path) -> bool:
        """Prüft ob Datei bereits im Zielverzeichnis existiert (basierend auf Inhalt)"""
        if not Config.ORGANIZER_CONFIG["duplicate_check"]:
            logger.debug("Duplikatsprüfung ist deaktiviert.")
            return False

        if not hasattr(self, "_hashes_initialized") or not self._hashes_initialized:
            self._load_existing_hashes()
            self._hashes_initialized = True

        try:
            file_hash = self._calculate_file_hash(file_path)
            if file_hash in self.file_hashes:
                logger.info(f"Duplikat gefunden und übersprungen: {file_path}")
                return True
            logger.debug(f"Kein Duplikat für {file_path.name} gefunden.")
            return False
        except Exception as e:
            logger.warning(f"Fehler bei Duplikatsprüfung für {file_path}: {e}")
            return False

    def _parse_artist_from_filename(self, filename: str) -> Tuple[str, str]:
        """Erweiterte Regex-Patterns für Dateinamen mit besserer Künstlererkennung"""
        original_filename = Path(filename).stem
        logger.debug(
            f"Versuche Künstler und Titel aus Dateinamen zu parsen: {original_filename}"
        )
        for pattern in Config.ORGANIZER_CONFIG["filename_patterns"]:
            match = re.match(pattern, original_filename, re.IGNORECASE)
            if match:
                artist = match.group("artist").replace("_", " ").strip()
                title = match.group("title").replace("_", " ").strip()
                if artist and title:
                    logger.debug(
                        f"Erfolgreich aus Dateinamen geparst: Künstler='{artist}', Titel='{title}'"
                    )
                    return self.clean_artist_name(artist), title
        logger.debug(
            f"Konnte Künstler/Titel nicht aus Dateinamen parsen. Fallback: Künstler='{Config.ORGANIZER_CONFIG['fallback_artist']}', Titel='{original_filename}'"
        )
        return (
            self.clean_artist_name(Config.ORGANIZER_CONFIG["fallback_artist"]),
            original_filename,
        )

    def _truncate_path(self, path: Path, max_length: int = 200) -> Path:
        """Kürzt zu lange Pfade für Windows-Kompatibilität"""
        if len(str(path)) <= max_length:
            logger.debug(f"Pfad ist kurz genug: {path}")
            return path

        stem = path.stem[: (max_length - len(path.suffix) - 10)]
        truncated = path.with_name(f"{stem}_TRUNCATED{path.suffix}")
        logger.warning(f"Pfad gekürzt: {path} -> {truncated}")
        return truncated

    def get_audio_metadata(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Extrahiert Metadaten aus Audiodatei mit verbesserter Künstlererkennung"""
        logger.debug(f"Versuche Metadaten für {file_path} zu extrahieren.")
        try:
            audio = None
            suffix = file_path.suffix.lower()
            if suffix == ".mp3":
                audio = EasyID3(file_path)
            elif suffix == ".flac":
                audio = FLAC(file_path)
            elif suffix in (".m4a", ".mp4"):
                audio = MP4(file_path)
            elif suffix in (".ogg", ".opus"):
                audio = OggOpus(file_path)
            else:
                logger.debug(
                    f"Nicht unterstütztes Audioformat: {suffix} für {file_path.name}"
                )
                return None

            metadata = self._parse_metadata(audio, file_path)
            logger.debug(f"Metadaten für {file_path.name} extrahiert: {metadata}")
            return metadata
        except MutagenError as e:
            logger.warning(
                f"Mutagen-Fehler beim Lesen der Metadaten für {file_path}: {e}"
            )
            if Config.ORGANIZER_CONFIG["parse_artist_from_filename"]:
                artist, title = self._parse_artist_from_filename(file_path.name)
                fallback_metadata = {
                    "artist": artist,
                    "title": title,
                    "album": Config.METADATA_DEFAULTS["album"],
                    "year": Config.METADATA_DEFAULTS["year"],
                    "tracknumber": Config.METADATA_DEFAULTS["track_number"],
                    "album_artist": artist,
                    "genre": [Config.METADATA_DEFAULTS["genre"]],
                    "album_type": "single",
                    "is_single": True,
                }
                logger.debug(
                    f"Metadaten-Lesefehler, Fallback auf Dateinamen-Parsing für {file_path.name}: {fallback_metadata}"
                )
                return fallback_metadata
            return None
        except Exception as e:
            logger.error(
                f"Unerwarteter Fehler beim Metadaten-Lesen für {file_path}: {e}",
                exc_info=True,
            )
            return None

    def _parse_metadata(self, audio: Any, file_path: Path) -> Dict[str, Any]:
        """Verarbeitet Rohmetadaten zu strukturierten Daten"""
        metadata = {
            "artist": self._get_artist(audio, file_path),
            "title": self._get_title(audio, file_path),
            "album": self._get_album(audio),
            "year": self._get_year(audio),
            "tracknumber": self._get_track_number(audio),
            "album_artist": self._get_album_artist(audio),
            "genre": self._get_genre(audio),
            "album_type": self._infer_album_type(audio),
        }
        metadata["is_single"] = self._is_single_track(metadata)
        logger.debug(f"Rohmetadaten für {file_path.name} geparst.")
        return metadata

    def _get_artist(self, audio: Any, file_path: Optional[Path] = None) -> str:
        """Verbesserte Künstlererkennung mit erweiterten Fallbacks"""
        artist = ""
        if isinstance(audio, MP4):
            artist = audio.get("\xa9ART", [""])[0]
        else:
            artist = audio.get("artist", [""])[0]

        if (
            not artist
            and file_path
            and Config.ORGANIZER_CONFIG["parse_artist_from_filename"]
        ):
            parsed_artist, _ = self._parse_artist_from_filename(file_path.name)
            if parsed_artist != Config.ORGANIZER_CONFIG["fallback_artist"]:
                artist = parsed_artist
                logger.debug(
                    f"Künstler aus Dateinamen als Fallback für '{file_path.name}' verwendet: '{artist}'"
                )

        artist = (
            self.clean_artist_name(artist)
            if artist
            else Config.ORGANIZER_CONFIG["fallback_artist"]
        )
        logger.debug(f"Bereinigter Künstler: '{artist}'")

        override = Config.ORGANIZER_CONFIG.get("playlist_force_artist")
        if override:
            if (file_path and "playlist" in file_path.stem.lower()) or (
                override.lower() in artist.lower()
            ):
                logger.debug(
                    f"Künstler durch Playlist-Override erzwungen: '{override}' (ursprünglich: '{artist}')"
                )
                artist = override

        return artist

    def clean_artist_name(self, artist: str) -> str:
        """Bereinigt Künstlernamen radikal - behält nur Artist1 und entfernt alles andere"""
        if not artist:
            logger.debug(
                f"Leerer Künstlername. Fallback auf: {Config.ORGANIZER_CONFIG['fallback_artist']}"
            )
            return Config.ORGANIZER_CONFIG["fallback_artist"]

        original_artist = artist.strip()
        logger.debug(f"Reinige Künstler: '{original_artist}'")

        separators = [
            r"\sfeat\.",
            r"\sft\.",
            r"\swith",
            r"\s&",
            r"\sx",
            r"\s/",
            r"\s\+",
            r"\sVS\.?",
            r"\spresents",
            r"\smeets",
            r"\sund",
            r"\smit",
            r",",
            r";",
        ]
        separator_pattern = "|".join(separators)
        artist = re.split(separator_pattern, artist, flags=re.IGNORECASE)[0].strip()
        artist = re.sub(r"[\(\[{].*?[\)\]}]", "", artist).strip()
        artist = re.sub(r"[^\w\säöüßÄÖÜ\-]", "", artist)
        artist = re.sub(r"\s+", " ", artist).strip()
        artist = re.sub(r"\bThe\s+", "", artist, flags=re.IGNORECASE)
        artist = re.sub(r"\bDJ\b", "", artist, flags=re.IGNORECASE)

        if not artist:
            cleaned_original = re.sub(r"[^\w\säöüßÄÖÜ\-]", "", original_artist)
            cleaned_original = re.sub(r"\s+", " ", cleaned_original).strip()
            if not cleaned_original:
                logger.debug(
                    f"Bereinigter Künstler ist leer. Fallback auf: {Config.ORGANIZER_CONFIG['fallback_artist']}"
                )
                return Config.ORGANIZER_CONFIG["fallback_artist"]
            logger.debug(
                f"Bereinigter Künstler war leer, Fallback auf bereinigten Originalwert: '{cleaned_original}'"
            )
            return cleaned_original

        logger.debug(f"Final bereinigter Künstlername: '{artist}'")
        return artist

    def contains_whitelisted_artist(self, artist_raw: str) -> Optional[str]:
        """Prüft auf EXAKTE Artist-Matches (keine Teilstrings)"""
        if not artist_raw:
            logger.debug("Leerer Künstlername für Whitelist-Prüfung.")
            return None

        whitelist = [
            a.lower() for a in Config.ORGANIZER_CONFIG.get("filter_artists", [])
        ]
        logger.debug(f"Whitelisted Artists: {whitelist}")
        parts = re.split(
            r"\s(?:feat\.|ft\.|with|&|x|\/|\+|vs\.?|presents|meets|und|mit)\s",
            artist_raw,
            flags=re.IGNORECASE,
        )
        parts = [re.sub(r"\([^)]*\)", "", p).strip() for p in parts]

        for part in parts:
            part_clean = re.sub(r"[^\w\säöüßÄÖÜ\-]", "", part).strip().lower()
            logger.debug(f"Prüfe Part '{part_clean}'")
            if part_clean in whitelist:
                logger.info(
                    f"Künstler '{artist_raw}' ist in der Whitelist enthalten (Match: '{part_clean}')."
                )
                return part_clean

        logger.debug(f"Künstler '{artist_raw}' nicht in der Whitelist gefunden.")
        return None

    def _get_title(self, audio: Any, file_path: Path) -> str:
        """Extrahiert Titel mit Fallback auf Dateinamen-Parsing"""
        title = ""
        if isinstance(audio, MP4):
            title = audio.get("\xa9nam", [""])[0]
        else:
            title = audio.get("title", [""])[0]

        if not title and Config.ORGANIZER_CONFIG["parse_artist_from_filename"]:
            _, parsed_title = self._parse_artist_from_filename(file_path.name)
            if parsed_title != file_path.stem:
                title = parsed_title
                logger.debug(
                    f"Titel aus Dateinamen als Fallback für '{file_path.name}' verwendet: '{title}'"
                )

        final_title = self.sanitize_filename(title) if title else file_path.stem
        logger.debug(
            f"Extrahierter/bereinigter Titel für '{file_path.name}': '{final_title}'"
        )
        return final_title

    def _get_album(self, audio: Any) -> str:
        """Extrahiert Album mit intelligentem Fallback"""
        album = ""
        if isinstance(audio, MP4):
            album = audio.get("\xa9alb", [""])[0]
        else:
            album = audio.get("album", [""])[0]

        final_album = (
            self.sanitize_filename(album)
            if album
            else Config.METADATA_DEFAULTS["album"]
        )
        logger.debug(f"Extrahierter/bereinigter Albumtitel: '{final_album}'")
        return final_album

    def _get_year(self, audio: Any) -> str:
        """Extrahiert Jahr mit Validierung"""
        year = ""
        if isinstance(audio, MP4):
            year = audio.get("\xa9day", [""])[0]
        else:
            year = audio.get("date", [""])[0]

        match = re.search(r"\d{4}", str(year))
        final_year = match.group(0) if match else Config.METADATA_DEFAULTS["year"]
        logger.debug(f"Extrahierter/validierter Jahr: '{final_year}'")
        return final_year

    def _get_track_number(self, audio: Any) -> str:
        """Extrahiert Tracknummer mit Formatierung"""
        track = ""
        if isinstance(audio, MP4):
            track = (
                str(audio.get("trkn", [(0, 0)])[0][0])
                if "trkn" in audio
                else Config.METADATA_DEFAULTS["track_number"]
            )
        else:
            track = audio.get(
                "tracknumber", [Config.METADATA_DEFAULTS["track_number"]]
            )[0]

        track = re.sub(r"\D", "", str(track).split("/")[0])
        final_track = (
            f"{int(track):02d}"
            if track.isdigit()
            else Config.METADATA_DEFAULTS["track_number"]
        )
        logger.debug(f"Extrahierte/formatierte Tracknummer: '{final_track}'")
        return final_track

    def _get_album_artist(self, audio: Any) -> str:
        """Extrahiert Albumkünstler mit Fallback auf Hauptkünstler"""
        album_artist = ""
        if isinstance(audio, MP4):
            album_artist = audio.get("aART", [""])[0]
        else:
            album_artist = audio.get("albumartist", [""])[0]

        artist = self._get_artist(audio)
        final_album_artist = (
            self.sanitize_filename(album_artist) if album_artist else artist
        )
        logger.debug(f"Extrahierter/bereinigter Albumkünstler: '{final_album_artist}'")
        return final_album_artist

    def _get_genre(self, audio: Any) -> List[str]:
        """Extrahiert Genre(s) mit Bereinigung"""
        genre_list = []
        if isinstance(audio, MP4):
            genre_list = audio.get("\xa9gen", [])
        else:
            genre_list = audio.get("genre", [])

        genres = []
        for g in genre_list:
            if isinstance(g, str):
                genres.extend(g.split(";"))

        final_genres = [
            self.sanitize_filename(g) for g in genres if g and str(g).strip()
        ]
        if not final_genres:
            final_genres = [Config.METADATA_DEFAULTS["genre"]]
            logger.debug(f"Kein Genre gefunden. Fallback auf: {final_genres}")
        else:
            logger.debug(f"Extrahierte/bereinigte Genres: {final_genres}")
        return final_genres

    def _infer_album_type(self, audio: Any) -> str:
        """Verbesserte Album-Typ-Erkennung mit Compilation-Logik"""
        album_artist = self._get_album_artist(audio).lower()
        album = self._get_album(audio).lower()

        album_type = "album"
        if "various artists" in album_artist or "compilation" in album:
            album_type = "compilation"
        elif "single" in album:
            album_type = "single"
        elif "ep" in album:
            album_type = "ep"
        logger.debug(
            f"Inferierter Album-Typ: '{album_type}' (Album-Artist: '{album_artist}', Album: '{album}')"
        )
        return album_type

    def _is_single_track(self, metadata: Dict[str, Any]) -> bool:
        """Bestimmt ob es sich um einen Single-Track handelt"""
        is_single = False
        if metadata["album_type"] in ["single", "ep"]:
            is_single = True
            logger.debug(
                f"Als Single erkannt aufgrund Album-Typ: {metadata['album_type']}"
            )
        elif metadata["album"].lower() == metadata["title"].lower():
            is_single = True
            logger.debug(
                f"Als Single erkannt da Album- und Titelname identisch: '{metadata['album']}'"
            )
        elif (
            not metadata["album"]
            or metadata["album"] == Config.METADATA_DEFAULTS["album"]
        ):
            is_single = True
            logger.debug(
                f"Als Single erkannt da kein oder 'Unknown' Albumname: '{metadata['album']}'"
            )
        elif metadata["album_type"] == "compilation":
            is_single = True
            logger.debug("Als Single erkannt da Compilation-Album.")

        logger.debug(
            f"Track '{metadata['title']}' ist als Single-Track klassifiziert: {is_single}"
        )
        return is_single

    def create_unique_dir(self, base_path: Path) -> Path:
        """Erstellt einen eindeutigen Ordnerpfad falls der Basisordner existiert"""
        if not base_path.exists():
            logger.debug(f"Basisordner '{base_path}' existiert nicht, wird verwendet.")
            return base_path

        if base_path.is_dir() and any(base_path.iterdir()):
            counter = 1
            while True:
                new_path = base_path.with_name(f"{base_path.name} ({counter})")
                if not new_path.exists():
                    logger.info(
                        f"Eindeutigen Ordnerpfad erstellt für '{base_path.name}': '{new_path}'"
                    )
                    return new_path
                counter += 1
        logger.debug(
            f"Basisordner '{base_path}' existiert und ist leer oder enthält nur Unterordner. Wird verwendet."
        )
        return base_path

    def _get_destination_path(self, metadata: Dict[str, Any], suffix: str) -> Path:
        """Generiert Zielpfad basierend auf Metadaten"""
        logger.debug(f"Starte _get_destination_path für Metadaten: {metadata}")

        artist_raw = metadata.get("artist", Config.ORGANIZER_CONFIG["fallback_artist"])
        artist = self.sanitize_filename(self.clean_artist_name(artist_raw))
        title = self.sanitize_filename(metadata.get("title", "Unbekannter Titel"))
        year = str(metadata.get("year", Config.METADATA_DEFAULTS.get("year", "0000")))
        track_num = str(
            metadata.get(
                "tracknumber", Config.METADATA_DEFAULTS.get("track_number", "01")
            )
        )
        is_single = metadata.get("is_single", False)
        album = self.sanitize_filename(
            metadata.get(
                "album", Config.METADATA_DEFAULTS.get("album", "Unknown Album")
            )
        )

        logger.debug(
            f"Bereinigte Metadaten für Pfadgenerierung: Artist='{artist}', Title='{title}', Year='{year}', Track='{track_num}', Album='{album}', IsSingle={is_single}"
        )

        if is_single:
            dir_format_str = Config.ORGANIZER_CONFIG["single_dir_format"]
            filename_format_str = Config.ORGANIZER_CONFIG["track_filename_format"]
            relative_dir_path = Path(
                dir_format_str.format(
                    artist=artist,
                    album=album,
                    year=year,
                    title=title,
                    tracknumber=track_num,
                )
            )
            filename = f"{filename_format_str.format(year=year, title=title, tracknumber=track_num)}{suffix}"
            final_path = Config.LIBRARY_DIR / artist / relative_dir_path / filename
            logger.debug(f"Generierter Single-Pfad (vor Bereinigung): {final_path}")
        else:
            dir_format_str = Config.ORGANIZER_CONFIG["album_dir_format"]
            filename_format_str = Config.ORGANIZER_CONFIG["track_filename_format"]
            album_dir_name = dir_format_str.format(
                year=year,
                album=album,
                artist=artist,
                title=title,
                tracknumber=track_num,
            )
            album_base_path = Config.LIBRARY_DIR / artist / "Albums" / album_dir_name
            final_album_path = self.create_unique_dir(album_base_path)

            if final_album_path not in self.created_albums:
                self.created_albums.add(final_album_path)
                logger.debug(
                    f"Album-Ordner '{final_album_path}' zur Liste der erstellten Alben hinzugefügt."
                )

            filename = f"{filename_format_str.format(tracknumber=track_num, title=title, year=year)}{suffix}"
            final_path = final_album_path / filename
            logger.debug(
                f"Generierter Album-Track-Pfad (vor Bereinigung): {final_path}"
            )

        if platform.system() == "Windows":
            final_path = self._truncate_path(final_path)

        logger.debug(f"Finaler Zielpfad: {final_path}")
        return final_path

    def _archive_file(self, file_path: Path) -> None:
        """Verschiebt eine erfolgreich kopierte Datei ins Archiv"""
        if not Config.ORGANIZER_CONFIG["archive_processed"]:
            logger.debug(f"Archivierung von '{file_path.name}' deaktiviert.")
            return

        try:
            archive_path_base = self.archive_dir / file_path.name
            archive_path = archive_path_base
            if archive_path.exists():
                counter = 1
                while archive_path.exists():
                    archive_path = (
                        self.archive_dir
                        / f"{file_path.stem} ({counter}){file_path.suffix}"
                    )
                    counter += 1
                logger.info(
                    f"Archivpfad für {file_path.name} angepasst zu {archive_path.name} wegen Existenz."
                )

            shutil.move(str(file_path), str(archive_path))
            logger.info(
                f"Datei '{file_path.name}' ins Archiv verschoben: {archive_path}"
            )
        except Exception as e:
            logger.error(
                f"Fehler beim Archivieren von {file_path.name} nach {archive_path}: {e}",
                exc_info=True,
            )

    def _process_file(self, file_path: Path) -> None:
        """Verarbeitet eine einzelne Datei mit Fehlerklassen-Differenzierung"""
        logger.info(f"Verarbeite Datei: {file_path.name}")
        try:
            if (
                not file_path.is_file()
                or file_path.suffix.lower() not in Config.SUPPORTED_FORMATS
            ):
                logger.debug(
                    f"Datei '{file_path.name}' übersprungen (keine Datei oder nicht unterstütztes Format)."
                )
                return

            if self._is_duplicate(file_path):
                self.stats["duplicates"] += 1
                return

            metadata = self.get_audio_metadata(file_path)
            if not metadata:
                logger.warning(
                    f"Metadaten konnten nicht gelesen oder geparst werden für: {file_path.name}. Überspringe Datei."
                )
                self.stats["errors"] += 1
                self.error_log.append(
                    f"{file_path.name}: Metadaten konnten nicht gelesen/geparst werden"
                )
                return

            if not self.contains_whitelisted_artist(metadata["artist"]):
                logger.info(
                    f"Übersprungen (Künstler '{metadata['artist']}' nicht in Whitelist): {file_path.name}"
                )
                return

            dest_path = self._get_destination_path(metadata, file_path.suffix)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            logger.debug(
                f"Zielverzeichnis '{dest_path.parent}' erstellt oder vorhanden."
            )

            if dest_path.exists():
                logger.warning(
                    f"Zielpfad existiert bereits: {dest_path.name}. Prüfe auf Duplikat oder benenne um."
                )
                try:
                    if self._calculate_file_hash(
                        file_path
                    ) == self._calculate_file_hash(dest_path):
                        logger.info(
                            f"Inhaltsgleiches Duplikat am Ziel gefunden und übersprungen: {file_path.name}"
                        )
                        self.stats["duplicates"] += 1
                        self._archive_file(file_path)
                        return
                except Exception as hash_error:
                    logger.error(
                        f"Fehler bei Hash-Vergleich für Konfliktlösung zwischen {file_path.name} und {dest_path.name}: {hash_error}"
                    )

                base = dest_path.stem
                suffix = dest_path.suffix
                counter = 1
                original_dest_path = dest_path
                while dest_path.exists():
                    dest_path = dest_path.with_name(f"{base} ({counter}){suffix}")
                    counter += 1
                logger.info(
                    f"Dateinamenskonflikt gelöst. Datei '{original_dest_path.name}' wird als '{dest_path.name}' kopiert."
                )

            shutil.copy2(file_path, dest_path)
            file_hash = self._calculate_file_hash(dest_path)
            self.file_hashes.add(file_hash)
            self.stats["processed"] += 1
            self.moved_files.append(
                (file_path.name, str(dest_path), file_path.suffix.lower())
            )
            logger.info(f"Erfolgreich kopiert: {file_path.name} -> {dest_path.name}")

            self._archive_file(file_path)

        except (OSError, shutil.Error) as e:
            self.stats["errors"] += 1
            error_msg = f"Dateisystemfehler für '{file_path.name}': {e}"
            self.error_log.append(error_msg)
            logger.error(error_msg, exc_info=True)
        except MutagenError as e:
            self.stats["errors"] += 1
            error_msg = f"Metadaten-Verarbeitungsfehler für '{file_path.name}': {e}"
            self.error_log.append(error_msg)
            logger.warning(error_msg, exc_info=True)
        except Exception as e:
            self.stats["errors"] += 1
            error_msg = f"Unerwarteter kritischer Fehler beim Verarbeiten von '{file_path.name}': {e}"
            self.error_log.append(error_msg)
            logger.critical(error_msg, exc_info=True)

    def _get_new_artists(self) -> Set[str]:
        """Ermittelt neu hinzugefügte Künstler"""
        current_artists = set()
        for item in self.target_dir.iterdir():
            if (
                item.is_dir()
                and item.name not in Config.ORGANIZER_CONFIG["special_dirs"]
            ):
                current_artists.add(item.name)
        logger.debug(f"Aktuell vorhandene Künstlerordner: {current_artists}")
        return current_artists

    def _get_new_albums(self) -> Set[Path]:
        """Ermittelt neu hinzugefügte Alben"""
        logger.debug(f"Neu erstellte Album-Pfade (Cache): {self.created_albums}")
        return self.created_albums

    def organize_files(self) -> Dict[str, Any]:
        """Organisiert Musikdateien und gibt erweiterte Statistiken zurück"""
        self._reset_stats()
        logger.info(f"Starte intelligente Musikorganisation von: {self.source_dir}")

        if Config.ORGANIZER_CONFIG["duplicate_check"] and not self._hashes_initialized:
            self._load_existing_hashes()

        found_files_count = 0
        for file_path in self.source_dir.rglob("*"):
            if (
                file_path.is_file()
                and file_path.suffix.lower() in Config.SUPPORTED_FORMATS
            ):
                found_files_count += 1
                self._process_file(file_path)

        if found_files_count == 0:
            logger.info(
                f"Keine unterstützten Audiodateien im Quellverzeichnis '{self.source_dir}' gefunden."
            )

        logger.info(
            f"Verarbeitung abgeschlossen. {self.stats['processed']} Dateien kopiert, "
            f"{self.stats['duplicates']} Duplikate übersprungen, "
            f"{self.stats['errors']} Fehler aufgetreten."
        )

        new_artists = self._get_new_artists()
        new_albums = self._get_new_albums()

        return {
            "processed": self.stats["processed"],
            "duplicates": self.stats["duplicates"],
            "errors": self.stats["errors"],
            "new_artists": len(new_artists),
            "new_albums": len(new_albums),
            "error_samples": self.get_error_samples(),
            "moved_files": self.moved_files,
        }

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Bereinigt Dateinamen von ungültigen Zeichen"""
        if not name:
            logger.debug("Leerer Name für Bereinigung, rückgabe 'Unknown'.")
            return "Unknown"

        original_name = name
        for char in Config.ORGANIZER_CONFIG["filename_sanitize_chars"]:
            name = name.replace(char, "_")
        name = re.sub(r"\s+", " ", name).strip()
        logger.debug(f"Bereinigter Dateiname von '{original_name}' zu '{name}'.")
        return name

    def _get_artist_folder(self, artist: str) -> Path:
        """Hilfsmethode für einfache Organisation"""
        artist_name = "Unknown" if not artist else artist
        sanitized_artist_name = self.sanitize_filename(artist_name)
        folder = self.target_dir / sanitized_artist_name
        folder.mkdir(exist_ok=True)
        logger.debug(f"Künstlerordner für einfache Organisation: {folder}")
        return folder

    def simple_organize_files(self) -> Dict[str, Any]:
        """Einfache Organisationsmethode"""
        self._reset_stats()
        logger.info(f"Starte einfache Verarbeitung von: {self.source_dir}")

        if isinstance(Config.AUDIO_FORMAT, list):
            search_format = Config.AUDIO_FORMAT[0]
        else:
            search_format = Config.AUDIO_FORMAT

        found_files_count = 0
        for file_path in self.source_dir.glob(f"*{search_format}"):
            found_files_count += 1
            try:
                audio = mutagen.File(file_path)
                if audio is None:
                    logger.warning(
                        f"Konnte Metadaten für {file_path.name} nicht laden (mutagen.File). Überspringe."
                    )
                    self.stats["errors"] += 1
                    self.error_log.append(
                        f"{file_path.name}: Metadaten konnten nicht geladen werden (simple)"
                    )
                    continue

                artist = audio.get(
                    "artist",
                    [
                        (
                            file_path.stem.split(" - ")[0]
                            if " - " in file_path.stem
                            else "Unknown"
                        )
                    ],
                )[0]

                dest = self._get_artist_folder(artist) / file_path.name

                if dest.exists():
                    if self._calculate_file_hash(
                        file_path
                    ) == self._calculate_file_hash(dest):
                        logger.info(
                            f"Duplikat gefunden und übersprungen (einfach): {file_path.name}"
                        )
                        self.stats["duplicates"] += 1
                        self._archive_file(file_path)
                        continue
                    else:
                        base = dest.stem
                        suffix = dest.suffix
                        counter = 1
                        while dest.exists():
                            dest = dest.with_name(f"{base} ({counter}){suffix}")
                            counter += 1
                        logger.warning(
                            f"Konflikt in einfacher Organisation gelöst. Datei {file_path.name} wird als {dest.name} verschoben."
                        )

                shutil.move(str(file_path), str(dest))
                self.stats["processed"] += 1
                self.moved_files.append(
                    (file_path.name, str(dest), file_path.suffix.lower())
                )
                logger.info(f"Verschoben (einfach): {file_path.name} -> {dest.name}")
            except Exception as e:
                self.stats["errors"] += 1
                error_msg = (
                    f"Fehler bei einfacher Organisation für '{file_path.name}': {e}"
                )
                self.error_log.append(error_msg)
                logger.error(error_msg, exc_info=True)
                continue

        if found_files_count == 0:
            logger.info(
                f"Keine '{search_format}' Dateien im Quellverzeichnis '{self.source_dir}' für einfache Organisation gefunden."
            )

        logger.info(
            f"Einfache Verarbeitung abgeschlossen. {self.stats['processed']} Dateien verschoben, "
            f"{self.stats['duplicates']} Duplikate übersprungen, "
            f"{self.stats['errors']} Fehler aufgetreten."
        )
        return {
            "processed": self.stats["processed"],
            "duplicates": self.stats["duplicates"],
            "errors": self.stats["errors"],
            "moved_files": self.moved_files,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Organisiere Musikdateien")
    parser.add_argument(
        "--source", type=Path, help="Quellverzeichnis (Standard: aus Config)"
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        help="Verwende einfache Organisationsmethode",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Aktiviere detailliertes Debug-Logging in eine separate Datei.",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Sende Statusmeldung an Telegram.",
    )
    parser.add_argument(
        "--telegram-bot-token",
        type=str,
        help="Telegram Bot-Token für Benachrichtigungen.",
    )
    parser.add_argument(
        "--telegram-chat-id",
        type=str,
        help="Telegram Chat-ID für Benachrichtigungen.",
    )
    args = parser.parse_args()

    if args.debug:
        setup_debug_logging()

    organizer = MusicOrganizer(source_dir=args.source)
    organizer._setup_logging()

    notification_service = NotificationService(log_dir=Config.LOG_DIR)

    if args.simple:
        stats = organizer.simple_organize_files()
    else:
        stats = organizer.organize_files()

    # Konsolenausgabe
    print("\n--- Zusammenfassung ---")
    print(f"Verarbeitete Dateien: {stats['processed']}")
    print(f"Duplikate übersprungen: {stats['duplicates']}")
    print(f"Fehler aufgetreten: {stats['errors']}")
    if "new_artists" in stats:
        print(f"Neue Künstler hinzugefügt: {stats['new_artists']}")
    if "new_albums" in stats:
        print(f"Neue Alben hinzugefügt: {stats['new_albums']}")

    if stats["moved_files"]:
        print("\n--- Erfolgreich verschobene Dateien ---")
        for original, destination, file_type in stats["moved_files"]:
            print(f"✅ Original: '{original}'")
            print(f"   Zielpfad: '{destination}'")
            print(f"   Typ:      '{file_type}'")
            print("-" * 30)

    error_samples = organizer.get_error_samples()
    if error_samples:
        print("\n--- Beispiele für Fehler ---")
        for error in error_samples:
            print(f"- {error}")

    print(f"\nDetails finden Sie in den Logdateien im Verzeichnis: {Config.LOG_DIR}")

    # Telegram-Benachrichtigung
    if args.telegram:
        if not args.telegram_bot_token or not args.telegram_chat_id:
            print("Fehler: Telegram Bot-Token und Chat-ID müssen angegeben werden.")
            logger.error(
                "Telegram-Benachrichtigung fehlgeschlagen: Bot-Token oder Chat-ID fehlen."
            )
        else:
            telegram_message = notification_service.generate_telegram_status(
                stats, error_samples
            )
            print("\n--- Telegram Statusmeldung ---")
            print(telegram_message)
            success = asyncio.run(
                notification_service.send_telegram_message(
                    telegram_message, args.telegram_bot_token, args.telegram_chat_id
                )
            )
            if not success:
                print(
                    "Fehler beim Senden der Telegram-Nachricht. Siehe Logs für Details."
                )
