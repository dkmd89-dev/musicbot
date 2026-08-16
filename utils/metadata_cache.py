# -*- coding: utf-8 -*-
# utils/metadata_cache.py

import json
import hashlib
import time
from pathlib import Path
from typing import Optional, Dict, Union, Callable, Any

from config import Config
from logger import get_module_logger

# NEU: Aktuelle Cache-Schema-Version
_CACHE_VERSION = 2


class MetadataCache:
    """
    Dateibasierter JSON-Metadaten-Cache (ein JSON-File pro Track).

    Key-Schema : MD5( lower(artist) + "::" + lower(title) )
    Dateiname  : {hex-key}.json  im cache_path-Verzeichnis

    Robustheit:
      - JSONDecodeError       → korrupte Datei wird sofort gelöscht (FIX-E)
      - Leere Datei (0 Bytes) → wird sofort gelöscht               (FIX-E2)
      - cleanup()             → entfernt korrupte + verwaiste Einträge (FIX-E3)

    NEU (v2):
      - MB-IDs: recording_id, artist_id, release_id, release_group_id, isrc
      - cover_source: "coverartarchive" | "youtube_max" | "youtube_hq" | None
      - _version: int für Migration alter Einträge
    """

    def __init__(
        self,
        cache_dir: Optional[Union[str, Path]] = None,
        logger_factory: Optional[Callable] = None,
    ):
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("metadata_cache")

        if isinstance(cache_dir, str):
            cache_dir = Path(cache_dir)

        self.cache_path: Path = cache_dir or getattr(
            Config, "METADATA_CACHE_DIR", Path("metadata_cache")
        )
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.logger.debug(f"💾 MetadataCache initialisiert: {self.cache_path}")

    # ─────────────────────────────────────────────────────────────────────────
    # NEU: Migration alter Cache-Einträge
    # ─────────────────────────────────────────────────────────────────────────

    def _migrate_old_entry(self, data: Dict) -> Dict:
        """
        Migriert einen alten Cache-Eintrag auf das aktuelle Schema.
        Fehlende Felder werden mit None / Standardwert befüllt.
        Gibt das migrierte Dict zurück.
        """
        version = data.get("_version", 1)

        if version >= _CACHE_VERSION:
            return data

        # Migration von v1 → v2: Neue Felder hinzufügen
        if version < 2:
            new_fields = {
                "musicbrainz_recording_id": None,
                "musicbrainz_artist_id": None,
                "musicbrainz_release_id": None,
                "musicbrainz_release_group_id": None,
                "isrc": None,
                "cover_source": None,
            }
            for field, default in new_fields.items():
                if field not in data:
                    data[field] = default

            data["_version"] = 2
            self.logger.debug(
                f"💾 Cache-Eintrag migriert: v1 → v2 "
                f"(title={data.get('title', '?')!r})"
            )

        return data

    # ─────────────────────────────────────────────────────────────────────────
    # Interne Hilfsmethoden
    # ─────────────────────────────────────────────────────────────────────────

    def _get_key(self, artist: str, title: str) -> str:
        """MD5-Hash aus normalisiertem 'artist::title'."""
        artist_clean = artist.strip().lower() if artist else ""
        title_clean  = title.strip().lower()  if title  else ""
        raw = f"{artist_clean}::{title_clean}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _cache_file(self, artist: str, title: str) -> Path:
        """Gibt den vollständigen Pfad zur Cache-Datei zurück."""
        return self.cache_path / f"{self._get_key(artist, title)}.json"

    def _delete_file(self, path: Path, reason: str) -> None:
        """Löscht eine Cache-Datei und loggt den Grund."""
        try:
            path.unlink(missing_ok=True)
            self.logger.info(f"🗑️ Cache-Datei gelöscht ({reason}): {path.name}")
        except OSError as e:
            self.logger.error(
                f"❌ Konnte Cache-Datei nicht löschen ({path.name}): {e}"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ─────────────────────────────────────────────────────────────────────────

    def get(self, artist: str, title: str) -> Optional[Dict]:
        """
        Liest einen Cache-Eintrag.

        Rückgabe:
            Dict  – bei Cache-Hit (ggf. migriert)
            None  – bei Cache-Miss, korrupter oder leerer Datei

        ✅ FIX-E:  JSONDecodeError → Datei wird automatisch gelöscht.
        ✅ FIX-E2: Leere Datei     → Datei wird automatisch gelöscht.
        NEU: Migriert alte Einträge automatisch auf v2-Schema.
        """
        path = self._cache_file(artist, title)

        if not path.exists():
            self.logger.debug(f"🔍 Cache-Miss: {artist} - {title}")
            return None

        # FIX-E2: Leere Datei sofort entfernen
        if path.stat().st_size == 0:
            self._delete_file(path, "leere Datei")
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # NEU: Migration falls nötig
            data = self._migrate_old_entry(data)

            self.logger.debug(f"📖 Cache-Hit: {artist} - {title}")
            return data

        except json.JSONDecodeError as e:
            # FIX-E: Korrupte JSON-Datei löschen
            self.logger.warning(
                f"⚠️ Fehler beim Lesen des Cache: {path.name} - {e}. "
                f"Datei wird gelöscht."
            )
            self._delete_file(path, "korruptes JSON")
            return None

        except OSError as e:
            self.logger.warning(
                f"⚠️ Fehler beim Lesen des Cache (OS): {path.name} - {e}"
            )
            return None

        except Exception as e:
            self.logger.error(
                f"❌ Unerwarteter Fehler beim Lesen des Cache: {path.name} - {e}"
            )
            return None

    def store(self, artist: str, title: str, metadata: Dict) -> None:
        """
        Schreibt einen Cache-Eintrag atomar (write → rename).

        NEU: Fügt automatisch _version und neue Felder hinzu falls nicht vorhanden.
        Atomares Schreiben verhindert korrupte Dateien bei Absturz.
        """
        if not isinstance(metadata, dict):
            self.logger.error(
                f"❌ store() erwartet ein Dict, erhielt: {type(metadata).__name__}"
            )
            return

        # NEU: Sicherstellen dass alle v2-Felder vorhanden sind
        metadata.setdefault("musicbrainz_recording_id", None)
        metadata.setdefault("musicbrainz_artist_id", None)
        metadata.setdefault("musicbrainz_release_id", None)
        metadata.setdefault("musicbrainz_release_group_id", None)
        metadata.setdefault("isrc", None)
        metadata.setdefault("cover_source", None)
        metadata["_version"] = _CACHE_VERSION  # NEU: Version setzen

        path = self._cache_file(artist, title)
        tmp_path = path.with_suffix(f".tmp_{int(time.time() * 1000)}")

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False, default=str)
            tmp_path.replace(path)
            self.logger.debug(f"💾 Cache gespeichert: {artist} - {title}")

        except OSError as e:
            self.logger.error(
                f"❌ Fehler beim Speichern des Cache: {path.name} - {e}"
            )
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

        except Exception as e:
            self.logger.error(
                f"❌ Unerwarteter Fehler beim Speichern des Cache: {path.name} - {e}"
            )
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def invalidate(self, artist: str, title: str) -> None:
        """Entfernt einen einzelnen Cache-Eintrag."""
        path = self._cache_file(artist, title)
        if path.exists():
            self._delete_file(path, f"invalidiert: {artist} - {title}")
        else:
            self.logger.warning(
                f"⚠️ Cache-Eintrag nicht gefunden, keine Aktion nötig: "
                f"{artist} - {title}"
            )

    def exists(self, artist: str, title: str) -> bool:
        """
        Schneller Existenz-Check ohne Deserialisierung.
        Gibt False zurück wenn die Datei leer oder 0 Bytes groß ist.
        """
        path = self._cache_file(artist, title)
        return path.exists() and path.stat().st_size > 0

    # ─────────────────────────────────────────────────────────────────────────
    # Wartung
    # ─────────────────────────────────────────────────────────────────────────

    def cleanup(self) -> Dict[str, int]:
        """
        FIX-E3: Bereinigt den Cache aktiv.

        Entfernt:
          1. Leere Dateien  (0 Bytes)
          2. Korrupte JSON-Dateien (nicht parsbar)
          3. Verwaiste Einträge (library_path existiert nicht mehr auf Disk)

        NEU: Migriert valide v1-Einträge auf v2-Schema (in-place).
        """
        self.logger.info(
            f"🧹 MetadataCache cleanup gestartet: {self.cache_path}"
        )

        stats = {
            "deleted_empty":    0,
            "deleted_corrupt":  0,
            "deleted_orphaned": 0,
            "migrated":         0,  # NEU
            "kept":             0,
        }

        json_files = list(self.cache_path.glob("*.json"))
        self.logger.info(f"   📂 {len(json_files)} Cache-Dateien gefunden")

        for cache_file in json_files:
            # 1. Leere Datei
            if cache_file.stat().st_size == 0:
                self._delete_file(cache_file, "cleanup: leer")
                stats["deleted_empty"] += 1
                continue

            # 2. Korrupte JSON-Datei
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                self.logger.warning(
                    f"⚠️ Korrupte Cache-Datei gefunden: {cache_file.name} – {e}"
                )
                self._delete_file(cache_file, "cleanup: korruptes JSON")
                stats["deleted_corrupt"] += 1
                continue

            # NEU: Migration alter Einträge
            old_version = data.get("_version", 1)
            data = self._migrate_old_entry(data)
            if data.get("_version", 1) > old_version:
                try:
                    tmp_path = cache_file.with_suffix(
                        f".tmp_{int(time.time() * 1000)}"
                    )
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
                    tmp_path.replace(cache_file)
                    stats["migrated"] += 1
                    self.logger.debug(
                        f"💾 Cache-Eintrag migriert: {cache_file.name}"
                    )
                except Exception as e:
                    self.logger.warning(
                        f"⚠️ Migration fehlgeschlagen für {cache_file.name}: {e}"
                    )

            # 3. Verwaister Eintrag
            library_path_str = data.get("library_path")
            if library_path_str:
                library_path = Path(library_path_str)
                if not library_path.exists():
                    self.logger.debug(
                        f"🔍 Verwaister Eintrag: {cache_file.name} "
                        f"→ {library_path} existiert nicht"
                    )
                    self._delete_file(cache_file, "cleanup: verwaist")
                    stats["deleted_orphaned"] += 1
                    continue

            stats["kept"] += 1

        total_deleted = (
            stats["deleted_empty"]
            + stats["deleted_corrupt"]
            + stats["deleted_orphaned"]
        )
        self.logger.info(
            f"✅ MetadataCache cleanup abgeschlossen:\n"
            f"   🗑️ Gelöscht gesamt : {total_deleted}\n"
            f"      • Leer          : {stats['deleted_empty']}\n"
            f"      • Korrupt       : {stats['deleted_corrupt']}\n"
            f"      • Verwaist      : {stats['deleted_orphaned']}\n"
            f"   🔄 Migriert        : {stats['migrated']}\n"
            f"   ✅ Behalten        : {stats['kept']}"
        )
        return stats

    def clear_all(self) -> int:
        """
        Löscht ALLE Cache-Dateien im cache_path.
        Gibt die Anzahl der gelöschten Dateien zurück.
        Vorsicht: Nicht rückgängig zu machen.
        """
        deleted = 0
        for cache_file in self.cache_path.glob("*.json"):
            try:
                cache_file.unlink()
                deleted += 1
            except OSError as e:
                self.logger.error(
                    f"❌ Konnte {cache_file.name} nicht löschen: {e}"
                )
        self.logger.warning(
            f"🗑️ clear_all(): {deleted} Cache-Dateien gelöscht"
        )
        return deleted

    def get_stats(self) -> Dict[str, Any]:
        """
        Gibt Statistiken über den aktuellen Cache zurück.

        NEU: Zählt auch v1-Einträge die noch migriert werden müssen.
        """
        json_files   = list(self.cache_path.glob("*.json"))
        total_size   = sum(f.stat().st_size for f in json_files)
        empty_files  = sum(1 for f in json_files if f.stat().st_size == 0)
        corrupt = 0
        needs_migration = 0  # NEU

        for f in json_files:
            if f.stat().st_size == 0:
                continue
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                # NEU: Versionsprüfung
                if data.get("_version", 1) < _CACHE_VERSION:
                    needs_migration += 1
            except (json.JSONDecodeError, UnicodeDecodeError):
                corrupt += 1

        return {
            "total_files":      len(json_files),
            "total_size_bytes": total_size,
            "total_size_mb":    round(total_size / 1_048_576, 2),
            "corrupt_files":    corrupt,
            "empty_files":      empty_files,
            "needs_migration":  needs_migration,   # NEU
            "cache_version":    _CACHE_VERSION,    # NEU
            "cache_dir":        str(self.cache_path.resolve()),
        }
