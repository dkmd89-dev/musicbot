# services/downloader/active_downloads.py
# -*- coding: utf-8 -*-
"""
ActiveDownloadRegistry – prozessweite Registry der pro Chat gerade
laufenden Downloads (Telegram Download-Control-Center, 2026-09-02).

Verantwortlichkeit (Single Responsibility):
  - Reiner Zustand: welcher Chat hat gerade einen aktiven Download,
    mit welchem Fortschritt (ProgressTracker), und wie kann er
    abgebrochen werden (cancel_event).
  - KEIN Telegram-Bezug (services/-Schicht, siehe CLAUDE.md Abschnitt 4)
    - haelt ausschliesslich chat_id (int) und reine Datentypen.
  - KEIN Download selbst, KEINE yt-dlp-Logik.

Lebensdauer: GENAU EINE Instanz pro Bot-Prozess, im Gegensatz zu
DownloadHandler (services/downloader-Aufrufer), das pro Telegram-Update
neu instanziiert wird (siehe klassen/download_handler.py-Docstring).
Muss daher auf einem langlebigen Objekt gehalten werden - konkret
RichMenuHandler, das ueber die gesamte Bot-Laufzeit besteht - und per
Dependency Injection an jeden neuen DownloadHandler durchgereicht werden.

Thread-Sicherheit: cancel_event ist ein threading.Event (nicht
asyncio.Event), weil der Cancel-Check aus dem yt-dlp-progress_hooks-
Callback heraus erfolgt - der laeuft in einem Executor-Thread
(asyncio.run_in_executor), nicht im Event-Loop-Thread. Ein
asyncio.Event waere dort nicht sicher abfragbar. Das eigentliche
"Abbrechen"-Setzen geschieht dagegen im Event-Loop-Thread (Telegram-
Callback-Handler) - threading.Event ist fuer genau diesen
Cross-Thread-Anwendungsfall gebaut und benoetigt keinen Event-Loop-Bezug.
_lock schuetzt zusaetzlich das Registry-Dict selbst (register/
unregister/get koennen aus verschiedenen Tasks nebenlaeufig aufgerufen
werden).
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from logger import get_module_logger
from services.downloader.progress_tracker import ProgressTracker


@dataclass
class ActiveDownload:
    """Zustand eines gerade laufenden Downloads für EINEN Chat."""

    chat_id: int
    url: str
    download_type: str  # "single" | "playlist"
    title: str = ""
    started_at: float = field(default_factory=time.monotonic)
    tracker: ProgressTracker = field(default_factory=ProgressTracker)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    # Wird von enhanced_download_with_retry()/_process_playlist_download()
    # gesetzt, sobald ein Abbruch tatsächlich wirksam wurde - erlaubt
    # DownloadHandler, nach Rückkehr von download_audio() zwischen "echter
    # Fehlschlag" und "vom Nutzer abgebrochen" zu unterscheiden, auch für
    # den Playlist-Pfad (dessen Rückgabewert sonst keinen expliziten
    # Cancelled-Status trägt - eine Playlist mit 0 verbleibenden Tracks
    # ist technisch trotzdem "success": True).
    cancelled: bool = False

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def request_cancel(self) -> None:
        """Fordert den Abbruch an (thread-sicher, wirkt sofort auf den
        naechsten progress_hooks-Aufruf UND den naechsten Playlist-Track-
        Start)."""
        self.cancel_event.set()

    def is_cancel_requested(self) -> bool:
        return self.cancel_event.is_set()


class ActiveDownloadRegistry:
    """Verwaltet pro Chat höchstens einen aktiven Download."""

    def __init__(self, logger_factory=None):
        self._active: Dict[int, ActiveDownload] = {}
        self._lock = threading.Lock()
        self.logger = (logger_factory or get_module_logger)("ActiveDownloadRegistry")

    def register(self, chat_id: int, url: str, download_type: str) -> ActiveDownload:
        """Registriert einen neuen aktiven Download für chat_id. Ersetzt
        einen eventuell noch vorhandenen (verwaisten) alten Eintrag -
        DownloadHandler ruft unregister() im finally-Block auf, ein
        verwaister Eintrag kann daher nur nach einem Absturz vorkommen."""
        entry = ActiveDownload(chat_id=chat_id, url=url, download_type=download_type)
        with self._lock:
            self._active[chat_id] = entry
        self.logger.info(
            f"📥 [ACTIVE-DL] Registriert: chat_id={chat_id}, type={download_type}"
        )
        return entry

    def unregister(self, chat_id: int) -> None:
        with self._lock:
            self._active.pop(chat_id, None)
        self.logger.info(f"📤 [ACTIVE-DL] Deregistriert: chat_id={chat_id}")

    def get(self, chat_id: int) -> Optional[ActiveDownload]:
        with self._lock:
            return self._active.get(chat_id)

    def is_active(self, chat_id: int) -> bool:
        return self.get(chat_id) is not None
