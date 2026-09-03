# services/downloader/download_history.py
# -*- coding: utf-8 -*-
"""
DownloadHistoryStore – JSON-basierter Persistenz-Speicher für den
Download-Verlauf pro Chat (Telegram Download-Control-Center, Folgeschritt
"📋 Download-Verlauf" / "🔁 Erneut versuchen", siehe docs/FINDINGS_INDEX.md).

Struktureller Zwilling zu services/duplicate/cache.py (ARCH-018): reine
Persistenzlogik ohne Telegram-Bezug, atomares Schreiben (write-tmp +
Path.replace(), analog zu DuplicateCache._write_json_atomic()/INV-02),
kein eigenes INV-01-Risiko über das bei DuplicateCache bereits akzeptierte
Maß hinaus (Einträge sind wenige Felder, keine großen Payloads).

Ein Eintrag wird an genau vier Stellen in klassen/download_handler.py
geschrieben (Single-Erfolg, Playlist-Erfolg pro Track, Fehlschlag,
Abbruch) - siehe dortige add_history_entry()-Aufrufe. Deckelung auf die
letzten MAX_ENTRIES_PER_CHAT Einträge pro Chat, älteste zuerst entfernt.
"""

import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from logger import get_module_logger

MAX_ENTRIES_PER_CHAT = 20


@dataclass
class DownloadHistoryEntry:
    """Ein einzelner Verlaufseintrag. status: 'success' | 'failed' | 'cancelled'."""

    url: str
    title: str
    artist: str
    status: str
    timestamp: str  # ISO-Format, datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DownloadHistoryEntry":
        return cls(
            url=data.get("url", ""),
            title=data.get("title", "Unbekannt"),
            artist=data.get("artist", "Unbekannt"),
            status=data.get("status", "success"),
            timestamp=data.get("timestamp", ""),
        )


class DownloadHistoryStore:
    """Verwaltet den persistenten Download-Verlauf, ein JSON-Dokument
    (chat_id -> Liste von Einträgen, älteste zuerst) im konfigurierten
    Cache-Verzeichnis."""

    def __init__(
        self, cache_dir: str = "cache/download_history", logger: Optional[Any] = None
    ):
        self.logger = logger or get_module_logger("DownloadHistoryStore")
        self.cache_path = Path(cache_dir)
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.history_file = self.cache_path / "download_history.json"

        self._data: Dict[str, List[Dict[str, Any]]] = self._load()
        self.logger.info(f"📋 DownloadHistoryStore initialisiert: {self.cache_path}")

    def _load(self) -> Dict[str, List[Dict[str, Any]]]:
        try:
            if self.history_file.exists():
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Laden des Download-Verlaufs: {e}")
        return {}

    def _save(self) -> None:
        try:
            self._write_json_atomic(self.history_file, self._data)
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Speichern des Download-Verlaufs: {e}")

    @staticmethod
    def _write_json_atomic(path: Path, data: dict) -> None:
        """Schreibt JSON atomar (write-tmp -> rename), analog zu
        DuplicateCache._write_json_atomic() (INV-02)."""
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

    def add_entry(
        self,
        chat_id: int,
        *,
        url: str,
        title: str,
        artist: str,
        status: str,
    ) -> None:
        """Fügt einen neuen Verlaufseintrag an (jüngste zuletzt in der
        internen Liste). Deckelt auf MAX_ENTRIES_PER_CHAT, älteste zuerst
        entfernt. Speichert sofort (analog zu DuplicateCache.add_entry())."""
        key = str(chat_id)
        entry = DownloadHistoryEntry(
            url=url,
            title=title or "Unbekannt",
            artist=artist or "Unbekannt",
            status=status,
            timestamp=datetime.now().isoformat(),
        )
        entries = self._data.setdefault(key, [])
        entries.append(entry.to_dict())
        if len(entries) > MAX_ENTRIES_PER_CHAT:
            del entries[: len(entries) - MAX_ENTRIES_PER_CHAT]
        self._save()

    def get_recent(
        self, chat_id: int, limit: int = MAX_ENTRIES_PER_CHAT
    ) -> List[DownloadHistoryEntry]:
        """Liefert die letzten Einträge für einen Chat, neueste zuerst."""
        raw = self._data.get(str(chat_id), [])
        entries = [DownloadHistoryEntry.from_dict(d) for d in reversed(raw)]
        return entries[:limit]

    def get_entry_by_position(
        self, chat_id: int, position: int
    ) -> Optional[DownloadHistoryEntry]:
        """position bezieht sich auf die Reihenfolge von get_recent()
        (0 = neuester Eintrag) - so wie die Liste in der Telegram-UI
        gerendert wird, damit callback_data-Indizes stabil zur Anzeige
        passen."""
        recent = self.get_recent(chat_id)
        if 0 <= position < len(recent):
            return recent[position]
        return None
