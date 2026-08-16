# yt_music_bot/handlers/duplicate_handler.py
# -*- coding: utf-8 -*-


import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import Config
from logger import get_module_logger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler
from utils.metadata_cache import MetadataCache

from utils.artist_map import ArtistNormalizer
from utils.youtube_parser import parse_youtube_title


@dataclass
class DuplicateEntry:
    """Repräsentiert einen Duplikat-Eintrag im Cache"""

    artist: str
    title: str
    url: str
    file_path: Optional[Path]
    download_date: datetime
    file_hash: Optional[str] = None
    metadata_hash: str = None
    duplicate_count: int = 1


class DuplicateCache:
    """Cache für Duplikat-Erkennung basierend auf MetadataCache"""

    def __init__(
        self, cache_dir: str = "duplicate_cache", logger: Optional[Any] = None
    ):
        # NEU: Logger als Abhängigkeit
        self.logger = logger or get_module_logger("DuplicateCache")
        self.cache_path = Path(cache_dir) if cache_dir else Path(DUPLICATE_CACHE_DIR)
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.metadata_cache = MetadataCache()

        # Separate Duplikat-Dateien
        self.url_cache_file = self.cache_path / "url_duplicates.json"
        self.content_cache_file = self.cache_path / "content_duplicates.json"

        # Caches laden
        self.url_cache = self._load_url_cache()
        self.content_cache = self._load_content_cache()

        self.logger.info(f"💾 DuplicateCache initialisiert: {self.cache_path}")

    def _load_url_cache(self) -> Dict[str, DuplicateEntry]:
        """Lädt URL-basierte Duplikate"""
        try:
            if self.url_cache_file.exists():
                with open(self.url_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cache = {}
                    for url_hash, entry_data in data.items():
                        cache[url_hash] = DuplicateEntry(
                            artist=entry_data["artist"],
                            title=entry_data["title"],
                            url=entry_data["url"],
                            file_path=(
                                Path(entry_data["file_path"])
                                if entry_data.get("file_path")
                                else None
                            ),
                            download_date=datetime.fromisoformat(
                                entry_data["download_date"]
                            ),
                            file_hash=entry_data.get("file_hash"),
                            metadata_hash=entry_data.get("metadata_hash"),
                            duplicate_count=entry_data.get("duplicate_count", 1),
                        )
                    self.logger.debug(f"📋 URL-Cache geladen: {len(cache)} Einträge")
                    return cache
        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Laden des URL-Cache: {e}")
        return {}

    def _load_content_cache(self) -> Dict[str, DuplicateEntry]:
        """Lädt Content-basierte Duplikate (Artist + Titel)"""
        try:
            if self.content_cache_file.exists():
                with open(self.content_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cache = {}
                    for content_hash, entry_data in data.items():
                        cache[content_hash] = DuplicateEntry(
                            artist=entry_data["artist"],
                            title=entry_data["title"],
                            url=entry_data["url"],
                            file_path=(
                                Path(entry_data["file_path"])
                                if entry_data.get("file_path")
                                else None
                            ),
                            download_date=datetime.fromisoformat(
                                entry_data["download_date"]
                            ),
                            file_hash=entry_data.get("file_hash"),
                            metadata_hash=entry_data.get("metadata_hash"),
                            duplicate_count=entry_data.get("duplicate_count", 1),
                        )
                    self.logger.debug(
                        f"🎵 Content-Cache geladen: {len(cache)} Einträge"
                    )
                    return cache
        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Laden des Content-Cache: {e}")
        return {}

    def _save_caches(self):
        """Speichert beide Caches"""
        try:
            url_data = {
                url_hash: {
                    "artist": entry.artist,
                    "title": entry.title,
                    "url": entry.url,
                    "file_path": str(entry.file_path) if entry.file_path else None,
                    "download_date": entry.download_date.isoformat(),
                    "file_hash": entry.file_hash,
                    "metadata_hash": entry.metadata_hash,
                    "duplicate_count": entry.duplicate_count,
                }
                for url_hash, entry in self.url_cache.items()
            }
            with open(self.url_cache_file, "w", encoding="utf-8") as f:
                json.dump(url_data, f, indent=2, ensure_ascii=False)

            content_data = {
                content_hash: {
                    "artist": entry.artist,
                    "title": entry.title,
                    "url": entry.url,
                    "file_path": str(entry.file_path) if entry.file_path else None,
                    "download_date": entry.download_date.isoformat(),
                    "file_hash": entry.file_hash,
                    "metadata_hash": entry.metadata_hash,
                    "duplicate_count": entry.duplicate_count,
                }
                for content_hash, entry in self.content_cache.items()
            }
            with open(self.content_cache_file, "w", encoding="utf-8") as f:
                json.dump(content_data, f, indent=2, ensure_ascii=False)

            self.logger.debug("💾 Duplikat-Caches erfolgreich gespeichert")
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Speichern der Caches: {e}")

    def get_url_hash(self, url: str) -> str:
        normalized_url = url.split("&")[0].split("?")[0]
        return hashlib.md5(normalized_url.encode("utf-8")).hexdigest()

    def get_content_hash(self, artist: str, title: str) -> str:
        normalized_key = f"{artist.strip().lower()}::{title.strip().lower()}"
        return hashlib.md5(normalized_key.encode("utf-8")).hexdigest()

    def add_entry(self, entry: DuplicateEntry):
        url_hash = self.get_url_hash(entry.url)
        content_hash = self.get_content_hash(entry.artist, entry.title)

        if url_hash in self.url_cache:
            self.url_cache[url_hash].duplicate_count += 1
        else:
            self.url_cache[url_hash] = entry

        if content_hash in self.content_cache:
            self.content_cache[content_hash].duplicate_count += 1
        else:
            self.content_cache[content_hash] = entry

        self._save_caches()
        self.logger.info(
            f"📝 Neuer Duplikat-Eintrag hinzugefügt: {entry.artist} - {entry.title}"
        )

    def check_url_duplicate(self, url: str) -> Optional[DuplicateEntry]:
        if not url:
            return None
        cache_key = self._normalize_url_for_cache(url)
        self.logger.debug(f"🔍 URL-Cache-Check: '{url}' -> Key: '{cache_key}'")

        for entry_hash, entry in self.url_cache.items():
            entry_key = self._normalize_url_for_cache(entry.url)
            if entry_key == cache_key:
                entry.duplicate_count += 1
                self.logger.info(f"🔗 URL-Duplikat im Cache gefunden: {cache_key}")
                return entry

        self.logger.debug(f"✅ URL-Cache: kein Duplikat für '{cache_key}'")
        return None

    def _normalize_url_for_cache(self, url: str) -> str:
        if not url:
            return ""
        try:
            from urllib.parse import urlparse, parse_qs

            parsed_url = urlparse(url)
            if "youtube.com/playlist" in url or "playlist?list=" in url:
                query_params = parse_qs(parsed_url.query)
                list_id = query_params.get("list", [None])[0]
                return (
                    f"youtube_playlist:{list_id}"
                    if list_id
                    else f"youtube_playlist:{url}"
                )
            elif "youtube.com/watch" in url or "youtu.be" in url:
                if "youtu.be" in url:
                    video_id = parsed_url.path.strip("/")
                    return (
                        f"youtube_video:{video_id}"
                        if video_id
                        else f"youtube_video:{url}"
                    )
                else:
                    query_params = parse_qs(parsed_url.query)
                    video_id = query_params.get("v", [None])[0]
                    return (
                        f"youtube_video:{video_id}"
                        if video_id
                        else f"youtube_video:{url}"
                    )
            else:
                normalized = f"{parsed_url.netloc}{parsed_url.path}"
                if parsed_url.query:
                    normalized += f"?{parsed_url.query}"
                return normalized
        except Exception as e:
            self.logger.warning(f"⚠️ Fehler bei URL-Normalisierung: {e}")
            return url

    def check_content_duplicate(
        self, artist: str, title: str
    ) -> Optional[DuplicateEntry]:
        content_hash = self.get_content_hash(artist, title)
        result = self.content_cache.get(content_hash)
        if result:
            self.logger.info(
                f"🎵 Content-Duplikat im Cache gefunden: {artist} - {title}"
            )
        else:
            self.logger.debug(
                f"✅ Content-Cache: kein Duplikat für '{artist} - {title}'"
            )
        return result

    def cleanup_old_entries(self, days_old: int = 30):
        cutoff_date = datetime.now() - timedelta(days=days_old)
        old_url_keys = [
            k for k, e in self.url_cache.items() if e.download_date < cutoff_date
        ]
        for key in old_url_keys:
            del self.url_cache[key]
        old_content_keys = [
            k for k, e in self.content_cache.items() if e.download_date < cutoff_date
        ]
        for key in old_content_keys:
            del self.content_cache[key]
        if old_url_keys or old_content_keys:
            self._save_caches()
            self.logger.info(
                f"🧹 {len(old_url_keys) + len(old_content_keys)} alte Duplikat-Einträge entfernt"
            )


class EnhancedDuplicateHandler:
    def __init__(self, config: Config, logger_factory: Optional[Callable] = None):
        # Logger mit Dependency Injection
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("EnhancedDuplicateHandler")

        self.config = config
        self.db_path = getattr(
            config, "DUPLICATE_CACHE_DIR", Path("./duplicate_db.json")
        )

        # FEHLER BEHOBEN: DuplicateCache initialisieren
        self.duplicate_cache = DuplicateCache(
            cache_dir=getattr(config, "DUPLICATE_CACHE_DIR", "duplicate_cache"),
            logger=self.logger_factory("DuplicateCache"),
        )

        self.artist_normalizer = (
            ArtistNormalizer(artist_config=getattr(self.config, "artist_config", None))
            if hasattr(self.config, "artist_config")
            else None
        )

        self.error_handler: "Optional[EnhancedErrorHandler]" = None

        self.stats = {
            "url_duplicates_found": 0,
            "content_duplicates_found": 0,
            "new_entries_added": 0,
            "total_checks": 0,
            "duplicates_skipped": 0,
        }
        self.logger.info("🔍 EnhancedDuplicateHandler initialisiert")

    def _get_default_config(self):
        class FallbackConfig:
            DUPLICATE_CACHE_DIR = "duplicate_cache"
            LIBRARY_DIR = Path("./music_library")

        return FallbackConfig()

    def check_for_duplicates(
        self,
        url: str,
        raw_artist: str = None,
        raw_title: str = None,
        track_metadata: Dict = None,
    ) -> Tuple[bool, Optional[DuplicateEntry], str]:
        self.stats["total_checks"] += 1
        self.logger.debug(f"🔍 Prüfe Duplikate für: {url}")

        url_duplicate = self.duplicate_cache.check_url_duplicate(url)
        if url_duplicate:
            self.stats["url_duplicates_found"] += 1
            self.stats["duplicates_skipped"] += 1
            self.logger.info(
                f"🔗 URL-Duplikat gefunden: {url_duplicate.artist} - {url_duplicate.title}"
            )
            return True, url_duplicate, "url"

        if raw_artist and raw_title:
            normalized_artist = self._normalize_artist_for_comparison(raw_artist)
            cleaned_title = self._clean_title_for_comparison(
                raw_title, normalized_artist
            )
            content_duplicate = self.duplicate_cache.check_content_duplicate(
                normalized_artist, cleaned_title
            )
            if content_duplicate:
                self.stats["content_duplicates_found"] += 1
                self.stats["duplicates_skipped"] += 1
                self.logger.info(
                    f"🎵 Content-Duplikat gefunden: {content_duplicate.artist} - {content_duplicate.title}"
                )
                return True, content_duplicate, "content"

        title_to_parse = raw_title or (
            track_metadata and track_metadata.get("title", "")
        )
        if title_to_parse:
            parsed = parse_youtube_title(title_to_parse)
            if parsed.get("artist") and parsed.get("song_title"):
                parsed_artist = self._normalize_artist_for_comparison(parsed["artist"])
                parsed_title = self._clean_title_for_comparison(
                    parsed["song_title"], parsed_artist
                )
                parsed_duplicate = self.duplicate_cache.check_content_duplicate(
                    parsed_artist, parsed_title
                )
                if parsed_duplicate:
                    self.stats["content_duplicates_found"] += 1
                    self.stats["duplicates_skipped"] += 1
                    self.logger.info(
                        f"🔍 Parsed-Content-Duplikat gefunden: {parsed_duplicate.artist} - {parsed_duplicate.title}"
                    )
                    return True, parsed_duplicate, "parsed_content"

        # 📁 Library-Fallback: Prüfe ob Datei bereits physisch in der Library existiert.
        # Greift auch wenn register_download nie aufgerufen wurde (z.B. nach Neustart).
        title_for_lib = raw_title or (
            track_metadata and track_metadata.get("title", "")
        )
        artist_for_lib = raw_artist or (
            track_metadata and track_metadata.get("artist", "")
        )
        if artist_for_lib and title_for_lib:
            lib_path = self.check_library_duplicate(artist_for_lib, title_for_lib)
            if lib_path:
                self.stats["content_duplicates_found"] += 1
                self.stats["duplicates_skipped"] += 1
                lib_entry = DuplicateEntry(
                    artist=artist_for_lib,
                    title=title_for_lib,
                    url=url,
                    file_path=lib_path,
                    download_date=datetime.now(),
                )
                # Eintrag nachträglich in Cache registrieren
                self.duplicate_cache.add_entry(lib_entry)
                self.logger.info(
                    f"📁 Library-Duplikat erkannt und Cache aktualisiert: "
                    f"'{artist_for_lib} - {title_for_lib}'"
                )
                return True, lib_entry, "library"

        self.logger.debug("✅ Kein Duplikat gefunden")
        return False, None, "none"

    def check_library_duplicate(self, artist: str, title: str):
        """
        🔎 Prüft direkt in der Library ob Artist/Titel bereits als Datei existiert.
        Fallback wenn der Cache-Eintrag fehlt (z.B. nach Neustart ohne register_download).
        """
        library_dir = getattr(self.config, "LIBRARY_DIR", None)
        if not library_dir:
            return None

        library_path = Path(library_dir)
        if not library_path.exists():
            return None

        normalized_artist = self._normalize_artist_for_comparison(artist)
        cleaned_title = self._clean_title_for_comparison(title, normalized_artist)
        audio_extensions = {".m4a", ".mp3", ".flac", ".ogg", ".opus", ".wav"}

        # Suche den passenden Artist-Ordner in der Library
        search_dirs = []
        try:
            for artist_dir in library_path.iterdir():
                if artist_dir.is_dir():
                    norm_dir = re.sub(r"\s+", " ", artist_dir.name.strip().lower())
                    if norm_dir == normalized_artist.lower():
                        search_dirs.append(artist_dir)
        except Exception as e:
            self.logger.warning(f"⚠️ Library-Scan Fehler: {e}")
            return None

        for search_dir in search_dirs:
            try:
                for file in search_dir.rglob("*"):
                    if file.suffix.lower() not in audio_extensions:
                        continue
                    stem = file.stem
                    # Jahr-Prefix "2025 - " entfernen
                    stem = re.sub(r"^\d{4}\s*-\s*", "", stem)
                    stem_clean = self._clean_title_for_comparison(
                        stem, normalized_artist
                    )
                    if stem_clean.lower() == cleaned_title.lower():
                        self.logger.info(
                            f"📁 Library-Duplikat: '{file.name}' "
                            f"(Artist: {artist}, Titel: {title})"
                        )
                        return file
            except Exception as e:
                self.logger.warning(f"⚠️ Fehler beim Durchsuchen von {search_dir}: {e}")

        return None

    def register_download(
        self,
        url: str,
        artist: str,
        title: str,
        file_path: Optional[Path] = None,
        metadata: Dict = None,
    ):
        entry = DuplicateEntry(
            artist=artist,
            title=title,
            url=url,
            file_path=file_path,
            download_date=datetime.now(),
            metadata_hash=self._create_metadata_hash(metadata) if metadata else None,
        )
        if file_path and file_path.exists():
            entry.file_hash = self._create_file_hash(file_path)

        self.duplicate_cache.add_entry(entry)
        self.stats["new_entries_added"] += 1
        self.logger.info(f"📝 Download registriert: {artist} - {title}")

    def _normalize_artist_for_comparison(self, artist: str) -> str:
        if not artist:
            return "Unknown"
        if self.artist_normalizer:
            try:
                normalized = self.artist_normalizer.normalize(artist)
                if normalized and normalized.lower() != "unknown":
                    return normalized
            except Exception as e:
                self.logger.debug(f"⚠️ Artist-Normalisierung fehlgeschlagen: {e}")
        cleaned = artist.strip()
        for suffix in [" - Topic", " VEVO", " Official"]:
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip()
        return cleaned if cleaned else "Unknown"

    def _clean_title_for_comparison(self, title: str, artist: str = None) -> str:
        if not title:
            return "Unknown"
        cleaned = title.strip()
        if artist and artist.lower() in cleaned.lower():
            for pattern in [
                f"{artist} - ",
                f"{artist} – ",
                f"{artist}: ",
                f"{artist} | ",
            ]:
                if cleaned.lower().startswith(pattern.lower()):
                    cleaned = cleaned[len(pattern) :].strip()
                    break
        import re

        patterns_to_remove = [
            r"\(Official.*?\)",
            r"\[.*?\]",
            r"\(feat\.?\s+.*?\)",
            r"\(ft\.?\s+.*?\)",
            r"\(.*?Version\)",
            r"\(Live.*?\)",
            r"\(Remix\)",
        ]
        for pattern in patterns_to_remove:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned if cleaned else "Unknown"

    def _create_metadata_hash(self, metadata: Dict) -> str:
        if not metadata:
            return None
        relevant_keys = ["title", "artist", "duration", "upload_date"]
        relevant_data = {
            k: v for k, v in metadata.items() if k in relevant_keys and v is not None
        }
        metadata_string = json.dumps(relevant_data, sort_keys=True)
        return hashlib.md5(metadata_string.encode("utf-8")).hexdigest()

    def _create_file_hash(self, file_path: Path) -> str:
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                chunk = f.read(65536)
                if chunk:
                    hash_md5.update(chunk)
                f.seek(-65536, 2)
                chunk = f.read(65536)
                if chunk:
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Erstellen des Datei-Hash: {e}")
            return None

    def get_statistics(self) -> Dict:
        total_checks = max(self.stats["total_checks"], 1)
        duplicates_found = (
            self.stats["url_duplicates_found"] + self.stats["content_duplicates_found"]
        )
        return {
            **self.stats,
            "url_cache_size": len(self.duplicate_cache.url_cache),
            "content_cache_size": len(self.duplicate_cache.content_cache),
            "duplicate_rate": (duplicates_found / total_checks) * 100,
            "savings_percentage": (self.stats["duplicates_skipped"] / total_checks)
            * 100,
        }

    def cleanup_cache(self, days_old: int = 30):
        self.duplicate_cache.cleanup_old_entries(days_old)

    def invalidate_entry(self, url: str = None, artist: str = None, title: str = None):
        removed_count = 0
        if url:
            url_hash = self.duplicate_cache.get_url_hash(url)
            if url_hash in self.duplicate_cache.url_cache:
                del self.duplicate_cache.url_cache[url_hash]
                removed_count += 1
        if artist and title:
            content_hash = self.duplicate_cache.get_content_hash(artist, title)
            if content_hash in self.duplicate_cache.content_cache:
                del self.duplicate_cache.content_cache[content_hash]
                removed_count += 1
        if removed_count > 0:
            self.duplicate_cache._save_caches()
            self.logger.info(f"🗑️ {removed_count} Duplikat-Einträge invalidiert")

    async def show_statistics_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        Zeigt das Duplikat-Statistik-Menü via Callback.
        Ersetzt die Logik von `find_duplicates`.
        """
        query = update.callback_query
        try:
            stats = self.get_statistics()

            # Fallback für total_checks=0, um DivisionByZero zu vermeiden
            total_checks = max(stats.get("total_checks", 0), 1)
            duplicates_found = stats.get("url_duplicates_found", 0) + stats.get(
                "content_duplicates_found", 0
            )
            duplicates_skipped = stats.get("duplicates_skipped", 0)

            # Sicherstellen, dass Raten berechnet werden können
            duplicate_rate = (
                (duplicates_found / total_checks) * 100 if total_checks > 0 else 0
            )
            savings_percentage = (
                (duplicates_skipped / total_checks) * 100 if total_checks > 0 else 0
            )

            response = (
                "♻️ **Duplikat-Statistiken**\n\n"
                f"📊 Gesamte Prüfungen: {stats.get('total_checks', 0)}\n"
                f"🔗 URL-Duplikate: {stats.get('url_duplicates_found', 0)}\n"
                f"🎵 Content-Duplikate: {stats.get('content_duplicates_found', 0)}\n"
                f"📝 Neue Einträge: {stats.get('new_entries_added', 0)}\n"
                f"🚫 Übersprungen: {duplicates_skipped}\n"
                f"💾 URL-Cache: {stats.get('url_cache_size', 0)}\n"
                f"💾 Content-Cache: {stats.get('content_cache_size', 0)}\n"
                f"📈 Duplikat-Rate: {duplicate_rate:.1f}%\n"
                f"💰 Einsparungen: {savings_percentage:.1f}%"
            )

            keyboard = InlineKeyboardMarkup(
                [
                    # Zurück zum Duplikat-Menü, nicht zum Admin-Hauptmenü
                    [
                        InlineKeyboardButton(
                            "⬅️ Zurück", callback_data="menu:admin_duplicates"
                        )
                    ]
                ]
            )

            await query.edit_message_text(
                response, reply_markup=keyboard, parse_mode="Markdown"
            )
        except Exception as e:
            self.logger.error(f"❌ Fehler bei Duplikat-Statistik: {e}", exc_info=True)
            await query.edit_message_text(
                f"❌ Fehler beim Laden der Duplikat-Statistiken: {e}",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "⬅️ Zurück", callback_data="menu:admin_duplicates"
                            )
                        ]
                    ]
                ),
            )

    async def show_clear_cache_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt Bestätigungs-Dialog für das Leeren des Duplikat-Cache."""
        query = update.callback_query

        text = """⚠️ **Duplikat-Cache leeren**

Bist du sicher, dass du den gesamten Duplikat-Cache (URLs und Content) löschen möchtest?

Diese Aktion kann nicht rückgängig gemacht werden!"""

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Ja, Cache leeren",
                        callback_data="dup:clear_cache_execute",  # Aktion ausführen
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "❌ Abbrechen",
                        callback_data="menu:admin_duplicates",  # Zurück zum Menü
                    ),
                ],
            ]
        )

        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode="Markdown"
        )

    async def execute_clear_cache(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        Führt das Leeren des Cache durch.
        Ersetzt die Logik von `clear_duplicate_cache`.
        """
        query = update.callback_query
        try:
            stats_before = self.get_statistics()

            deleted_files = []
            for file_path in [
                self.duplicate_cache.url_cache_file,
                self.duplicate_cache.content_cache_file,
            ]:
                if file_path.exists():
                    file_path.unlink()
                    deleted_files.append(file_path.name)

            # Caches im Speicher leeren
            self.duplicate_cache.url_cache = {}
            self.duplicate_cache.content_cache = {}

            # Statistiken im Speicher zurücksetzen
            self.stats = {
                "url_duplicates_found": 0,
                "content_duplicates_found": 0,
                "new_entries_added": 0,
                "total_checks": 0,
                "duplicates_skipped": 0,
            }
            # Cache-Objekt neu laden (oder leeren)
            self.duplicate_cache = DuplicateCache(
                cache_dir=str(self.duplicate_cache.cache_path),
                logger=self.logger_factory("DuplicateCache"),
            )

            response = (
                "✅ **Cache geleert**\n\n"
                "Der Duplikat-Cache wurde erfolgreich zurückgesetzt.\n\n"
                f"Gelöschte Einträge:\n"
                f"• URL-Cache: {stats_before.get('url_cache_size', 0)}\n"
                f"• Content-Cache: {stats_before.get('content_cache_size', 0)}\n"
                f"• Dateien: {', '.join(deleted_files) if deleted_files else 'Keine'}"
            )
            self.logger.info(f"🧹 Duplikat-Cache durch Admin geleert: {deleted_files}")

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Zurück", callback_data="menu:admin_duplicates"
                        )
                    ]
                ]
            )

            await query.edit_message_text(
                response, reply_markup=keyboard, parse_mode="Markdown"
            )
        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Löschen des Duplikat-Cache: {e}", exc_info=True
            )
            await query.edit_message_text(
                f"❌ Fehler beim Löschen des Duplikat-Cache: {e}",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "⬅️ Zurück", callback_data="menu:admin_duplicates"
                            )
                        ]
                    ]
                ),
            )


async def find_duplicates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram-Handler für Duplikat-Suche (Kompatibilität)"""
    logger = get_module_logger("DuplicateHandler_Telegram")
    try:
        # Konfiguration aus dem Context holen oder Standardkonfig verwenden
        config = (
            context.bot_data.get("config")
            or EnhancedDuplicateHandler()._get_default_config()
        )
        duplicate_handler = EnhancedDuplicateHandler(
            config=config, logger_factory=get_module_logger
        )
        stats = duplicate_handler.get_statistics()
        response = (
            "🔍 **Duplikat-Erkennungsstatistiken:**\n\n"
            f"📊 Gesamte Prüfungen: {stats['total_checks']}\n"
            f"🔗 URL-Duplikate gefunden: {stats['url_duplicates_found']}\n"
            f"🎵 Content-Duplikate gefunden: {stats['content_duplicates_found']}\n"
            f"📝 Neue Einträge hinzugefügt: {stats['new_entries_added']}\n"
            f"🚫 Übersprungene Downloads: {stats['duplicates_skipped']}\n"
            f"💾 URL-Cache-Größe: {stats['url_cache_size']}\n"
            f"💾 Content-Cache-Größe: {stats['content_cache_size']}\n"
            f"📈 Duplikat-Rate: {stats['duplicate_rate']:.1f}%\n"
            f"💰 Einsparungen: {stats['savings_percentage']:.1f}%"
        )
        await update.message.reply_text(response, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"❌ Fehler bei Duplikat-Suche: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Fehler bei der Duplikat-Analyse. Siehe Logs für Details."
        )


async def clear_duplicate_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram-Handler zum Löschen des Duplikat-Cache (Kompatibilität)"""
    logger = get_module_logger("DuplicateHandler_Telegram")
    try:
        # Konfiguration aus dem Context holen oder Standardkonfig verwenden
        config = (
            context.bot_data.get("config")
            or EnhancedDuplicateHandler()._get_default_config()
        )
        duplicate_handler = EnhancedDuplicateHandler(
            config=config, logger_factory=get_module_logger
        )
        stats_before = duplicate_handler.get_statistics()
        cache_path = duplicate_handler.duplicate_cache.cache_path
        deleted_files = []
        for file_path in [
            duplicate_handler.duplicate_cache.url_cache_file,
            duplicate_handler.duplicate_cache.content_cache_file,
        ]:
            if file_path.exists():
                file_path.unlink()
                deleted_files.append(file_path.name)

        duplicate_handler.duplicate_cache.url_cache = {}
        duplicate_handler.duplicate_cache.content_cache = {}

        response = (
            "🧹 Duplikat-Cache erfolgreich geleert!\n\n"
            "Gelöschte Einträge:\n"
            f"• URL-Cache: {stats_before['url_cache_size']}\n"
            f"• Content-Cache: {stats_before['content_cache_size']}\n"
            f"• Dateien gelöscht: {', '.join(deleted_files) if deleted_files else 'Keine'}"
        )
        await update.message.reply_text(response)
        logger.info(f"🧹 Duplikat-Cache durch Benutzer geleert: {deleted_files}")
    except Exception as e:
        logger.error(f"❌ Fehler beim Löschen des Duplikat-Cache: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Fehler beim Löschen des Duplikat-Cache. Siehe Logs für Details."
        )
