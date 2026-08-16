# -*- coding: utf-8 -*-
import json
import hashlib
import time
from pathlib import Path
from typing import Optional, Dict, Callable, Union
from logger import get_module_logger


class LyricsCache:
    def __init__(
        self, 
        cache_dir: Optional[Union[str, Path]] = None, 
        logger_factory: Optional[Callable] = None,
        config: Optional[object] = None
    ):
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("lyrics_cache")
        
        # Bestimme Cache-Verzeichnis
        if cache_dir:
            self.cache_path = Path(cache_dir)
        elif config and hasattr(config, 'LYRICS_CACHE_DIR_RESOLVED'):
            self.cache_path = config.LYRICS_CACHE_DIR_RESOLVED
        elif config and hasattr(config, 'LYRICS_CACHE_DIR'):
            self.cache_path = Path(config.LYRICS_CACHE_DIR)
        else:
            self.cache_path = Path(__file__).parent.parent / "cache" / "lyrics_cache"
        
        self.cache_ttl = 86400 * 90
        if config and hasattr(config, 'LYRICS_CACHE_TTL'):
            self.cache_ttl = config.LYRICS_CACHE_TTL
        
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"📜 LyricsCache initialisiert: {self.cache_path}")

    def _get_key(self, artist: str, title: str) -> str:
        raw = f"{artist.strip().lower()}::{title.strip().lower()}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def get(self, artist: str, title: str, check_expiry: bool = True) -> Optional[Dict]:
        key = self._get_key(artist, title)
        path = self.cache_path / f"{key}.json"
        if not path.exists():
            self.logger.debug(f"🔍 Cache-Miss: {artist} - {title}")
            return None
        
        if check_expiry:
            file_age = time.time() - path.stat().st_mtime
            if file_age > self.cache_ttl:
                self.logger.debug(f"⏰ Cache expired: {artist} - {title}")
                return None
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.logger.debug(f"📖 Cache-Hit: {artist} - {title}")
                return data
        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Lesen: {e}")
            return None

    def store(self, artist: str, title: str, metadata: Dict) -> None:
        key = self._get_key(artist, title)
        path = self.cache_path / f"{key}.json"
        metadata["_cached_at"] = time.time()
        metadata["_cache_ttl"] = self.cache_ttl
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            self.logger.debug(f"💾 Cache gespeichert: {artist} - {title}")
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Speichern: {e}")

    def invalidate(self, artist: str, title: str) -> None:
        key = self._get_key(artist, title)
        path = self.cache_path / f"{key}.json"
        if path.exists():
            path.unlink()
            self.logger.info(f"🗑️ Cache invalidated: {artist} - {title}")

    def _delete_file(self, path: Path, reason: str) -> None:
        try:
            path.unlink(missing_ok=True)
            self.logger.info(f"🗑️ Cache-Datei gelöscht ({reason}): {path.name}")
        except OSError as e:
            self.logger.error(f"❌ Konnte Cache-Datei nicht löschen ({path.name}): {e}")

    def cleanup(self) -> Dict[str, int]:
        """
        Bereinigt den Lyrics-Cache aktiv.

        Entfernt:
          1. Leere Dateien (0 Bytes)
          2. Korrupte JSON-Dateien (nicht parsbar)
          3. Per TTL (mtime) abgelaufene Einträge

        Anders als MetadataCache.cleanup() gibt es hier kein library_path-Feld,
        also kein Orphan-Konzept - stattdessen wird die vorhandene
        TTL/mtime-Logik aus get() auch fürs tatsächliche Löschen genutzt.
        """
        self.logger.info(f"🧹 LyricsCache cleanup gestartet: {self.cache_path}")

        stats = {
            "deleted_empty": 0,
            "deleted_corrupt": 0,
            "deleted_expired": 0,
            "kept": 0,
        }

        json_files = list(self.cache_path.glob("*.json"))
        self.logger.info(f"   📂 {len(json_files)} Cache-Dateien gefunden")

        for cache_file in json_files:
            if cache_file.stat().st_size == 0:
                self._delete_file(cache_file, "cleanup: leer")
                stats["deleted_empty"] += 1
                continue

            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    json.load(f)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                self.logger.warning(
                    f"⚠️ Korrupte Cache-Datei gefunden: {cache_file.name} – {e}"
                )
                self._delete_file(cache_file, "cleanup: korruptes JSON")
                stats["deleted_corrupt"] += 1
                continue

            file_age = time.time() - cache_file.stat().st_mtime
            if file_age > self.cache_ttl:
                self._delete_file(cache_file, "cleanup: TTL abgelaufen")
                stats["deleted_expired"] += 1
                continue

            stats["kept"] += 1

        total_deleted = (
            stats["deleted_empty"] + stats["deleted_corrupt"] + stats["deleted_expired"]
        )
        self.logger.info(
            f"✅ LyricsCache cleanup abgeschlossen:\n"
            f"   🗑️ Gelöscht gesamt : {total_deleted}\n"
            f"      • Leer          : {stats['deleted_empty']}\n"
            f"      • Korrupt       : {stats['deleted_corrupt']}\n"
            f"      • Abgelaufen    : {stats['deleted_expired']}\n"
            f"   ✅ Behalten        : {stats['kept']}"
        )
        return stats
