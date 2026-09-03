# services/duplicate/cache.py
# -*- coding: utf-8 -*-
"""
DuplicateCache – JSON-basierter Persistenz-Cache für die
Duplicate-Detection (URL- und Content-Hashes).

ARCH-018 Phase 2 (docs/archive/arch/MusicBot_ARCH-018_Duplicate_Handler_Characterization.md):
verschoben aus handlers/duplicate_handler.py. Reine Cache-/Persistenzlogik
ohne Telegram-Bezug (Abschnitt 6 der Characterization, "fachlicher Kern") –
unverändert in Verhalten und Signatur übernommen.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime, timedelta

from logger import get_module_logger
from services.downloader.models import DuplicateEntry


class DuplicateCache:
    """Cache für Duplikat-Erkennung basierend auf MetadataCache"""

    def __init__(
        self, cache_dir: str = "duplicate_cache", logger: Optional[Any] = None
    ):
        # NEU: Logger als Abhängigkeit
        self.logger = logger or get_module_logger("DuplicateCache")
        self.cache_path = Path(cache_dir) if cache_dir else Path(DUPLICATE_CACHE_DIR)
        self.cache_path.mkdir(parents=True, exist_ok=True)

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
        """
        Speichert beide Caches.

        INV-02 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md, Abschnitt 27, P0-B):
        vorher direktes open(mode="w") - ein Prozessabbruch waehrend
        json.dump() konnte url_duplicates.json/content_duplicates.json leeren
        oder korrumpieren. Jetzt: write-tmp + atomarer rename, analog zu
        MetadataCache.store() (utils/metadata_cache.py). INV-01 (Event-Loop-
        Blockierung) wird hier bewusst NICHT behoben: eine to_thread()-
        Umstellung wuerde eine Async-Kaskade durch DuplicateDetector,
        EnhancedDuplicateHandler (Telegram-Schicht) und die Aufrufer in
        klassen/download_handler.py erzwingen ("mass conversion" - ausserhalb
        des Scopes dieser Phase), waehrend die tatsaechliche Blockierungsdauer
        bei den hier typischen Cache-Groessen nicht als meaningful gemessen
        ist (im Gegensatz zu den real gemessenen backup_handler.py/
        enhanced_status_handler.py-Funden). Da add_entry()/_save_caches()
        weiterhin vollstaendig synchron (kein await dazwischen) im
        Event-Loop-Thread laufen, bleibt die bisherige, zufaellige
        Serialisierung zwischen gleichzeitigen Downloads erhalten - der
        atomare Schreibvorgang fuehrt dadurch KEINE neue Race Condition ein.
        """
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
            self._write_json_atomic(self.url_cache_file, url_data)

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
            self._write_json_atomic(self.content_cache_file, content_data)

            self.logger.debug("💾 Duplikat-Caches erfolgreich gespeichert")
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Speichern der Caches: {e}")

    @staticmethod
    def _write_json_atomic(path: Path, data: dict) -> None:
        """Schreibt JSON atomar (write-tmp -> rename)."""
        tmp_path = path.with_suffix(f".tmp_{int(time.time() * 1000)}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path.replace(path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def get_url_hash(self, url: str) -> str:
        # Nutzt dieselbe YouTube-bewusste Normalisierung wie check_url_duplicate()
        # (CACHE-001-Fix): vorher normalisierte get_url_hash() nur grob (Query-
        # String abschneiden), waehrend check_url_duplicate() ueber
        # _normalize_url_for_cache() z.B. youtu.be/<id> und watch?v=<id> als
        # gleiche URL erkennt. add_entry()/invalidate_entry() nutzten den
        # groben Hash als Dict-Key - eine Invalidierung mit einer anders
        # formatierten, aber aequivalenten URL schlug dadurch still fehl.
        normalized_url = self._normalize_url_for_cache(url)
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
                # duplicate_count-Konsistenz-Fix (2026-09-03, Nutzer-
                # Charakterisierung): vorher wurde der erhoehte Zaehler NUR
                # im In-Memory-State gehalten (kein _save_caches() danach) -
                # ging bei einem Bot-Neustart verloren, ausser ein
                # spaeterer add_entry()-Aufruf fuer einen ANDEREN Eintrag
                # loeste zufaellig einen Save aus. Jetzt zuverlaessig
                # persistiert, analog zu check_content_duplicate() unten.
                self._save_caches()
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
            elif "youtube.com/shorts/" in url:
                # P0-F-Fix (docs/audits/P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md):
                # ein Short und sein aequivalenter watch?v=<id>-Link
                # verweisen auf dieselbe Video-ID, fielen vorher aber in
                # den generischen netloc+path-Zweig unten und galten
                # dadurch faelschlich als zwei verschiedene URLs. Video-ID
                # ist der erste Pfad-Abschnitt nach "/shorts/" - ein
                # eventueller Query-String (z.B. "?feature=share") spielt
                # dabei keine Rolle, da urlparse ihn bereits von path
                # trennt.
                video_id = parsed_url.path.rsplit("/shorts/", 1)[-1].strip("/")
                return (
                    f"youtube_video:{video_id}" if video_id else f"youtube_video:{url}"
                )
            elif "youtube.com/embed/" in url or "youtube.com/live/" in url:
                # Charakterisierung 2026-09-03 (docs/FINDINGS_INDEX.md):
                # analog zum P0-F-Shorts-Fix - youtube.com/embed/<id>
                # (eingebettete Player-Links) und youtube.com/live/<id>
                # (z.B. der spaeter verfuegbare VOD-Link eines beendeten
                # Livestreams) verweisen auf dieselbe Video-ID wie
                # watch?v=<id>, fielen vorher aber ebenfalls in den
                # generischen netloc+path-Zweig unten und galten dadurch
                # faelschlich als andere URL. Beide Pfad-Formen teilen
                # sich denselben Zweig, da die Video-ID an derselben
                # Position (letzter Pfad-Abschnitt) steht.
                marker = "/embed/" if "youtube.com/embed/" in url else "/live/"
                video_id = parsed_url.path.rsplit(marker, 1)[-1].strip("/")
                return (
                    f"youtube_video:{video_id}" if video_id else f"youtube_video:{url}"
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
            # duplicate_count-Konsistenz-Fix (2026-09-03, Nutzer-
            # Charakterisierung "Konsistent zaehlen"): vorher mutierte
            # dieser Pfad NIE bei einem reinen Check - nur add_entry()
            # erhoehte den Zaehler, was bei einem erkannten Content-
            # Duplikat aber gerade NICHT passiert (der Download bricht ab,
            # es wird kein neuer Eintrag registriert). check_url_duplicate()
            # erhoehte dagegen bei JEDEM Lese-Treffer - eine echte
            # Asymmetrie, live an Testdaten belegt (siehe
            # tests/test_duplicate_cache_duplicate_count_consistency.py).
            # Jetzt identisches Verhalten auf beiden Pfaden.
            result.duplicate_count += 1
            self._save_caches()
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
