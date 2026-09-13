# services/statistik_service.py
"""
StatistikService – Fassade über die Wiedergabestatistik-Bausteine.

ARCH-003 (P-6): war vorher ein einzelner "God Service", der Persistenz,
externen API-Zugriff (Navidrome-Polling) und Business-Statistik-
Berechnung vermischte. Jetzt in fokussierte, einzeln injizierbare/
testbare Klassen aufgeteilt (services/statistik/):

  PlayHistoryRepository  – Lesen/Schreiben/Bereinigen der JSON-Verlaufsdateien
  PlayHistoryPoller       – Hintergrund-Polling gegen NavidromeAPI
  StatisticsCalculator    – Statistik-Berechnung aus dem Verlauf

Diese Klasse selbst ist eine bewusst dünne, temporäre Fassade: sie bietet
exakt dieselbe öffentliche API wie vorher (inkl. der als "privat"
gekennzeichneten, aber von tests/test_statistik_service.py direkt
getesteten Methoden `_load_history`/`_save_history`/`_cleanup_old_entries`
sowie der Klassenattribute `CHARTS_DIR`/`USER_HISTORY_DIR`), damit
bot.py/handlers/mugge_statistik_handler.py unverändert bleiben können.

Statistics Menu UX & Output Optimization: `ChartRenderer` (matplotlib-
Balkendiagramme) samt `create_chart()`-Wrapper entfernt - die Telegram-
Rückblicke/Rankings senden keine PNG-Bilder mehr, `create_chart()` hatte
danach 0 verbleibende Aufrufer im gesamten Projekt (verifiziert). Siehe
docs/MusicBot_TELEGRAM_MENU_SYSTEM.md Abschnitt 10.
"""

from typing import Any, Dict, List, Optional

from services.clients.navidrome_api import NavidromeAPI
from config import Config
from logger import get_module_logger

from services.statistik.play_history_poller import PlayHistoryPoller
from services.statistik.play_history_repository import PlayHistoryRepository
from services.statistik.statistics_calculator import StatisticsCalculator


class StatistikService:
    """
    Fassade: Erfassung, Speicherung und Analyse von Wiedergabestatistiken,
    pro Navidrome-Benutzer.
    """

    # Verzeichnis für Diagramme
    CHARTS_DIR = Config.STATS_DIR

    # Basis-Verzeichnis für Benutzer-Verlaufsdateien
    USER_HISTORY_DIR = Config.PLAY_HISTORY_FILE

    def __init__(self, navidrome_api=None):
        """
        `navidrome_api` ist optional injizierbar (ARCH-003, P-8-Muster) -
        ohne Angabe wird wie bisher eine echte NavidromeAPI() konstruiert.
        """
        self.logger = get_module_logger("statistik")
        self.CHARTS_DIR.mkdir(exist_ok=True)
        self.USER_HISTORY_DIR.mkdir(exist_ok=True)

        self.api = navidrome_api if navidrome_api is not None else NavidromeAPI()

        self._repository = PlayHistoryRepository(
            self.USER_HISTORY_DIR, logger=get_module_logger("PlayHistoryRepository")
        )
        self._poller = PlayHistoryPoller(
            self.api,
            self._repository,
            logger=get_module_logger("PlayHistoryPoller"),
        )
        self._calculator = StatisticsCalculator(
            self._repository,
            self.CHARTS_DIR,
            logger=get_module_logger("StatisticsCalculator"),
        )

        self.logger.info(
            "📊 StatistikService erfolgreich initialisiert (Benutzerspezifischer Modus)"
        )

    # ─────────────────────────────────────────────────────────────────────
    # Polling (→ PlayHistoryPoller)
    # ─────────────────────────────────────────────────────────────────────

    def start_polling(self):
        self._poller.start_polling()

    async def stop_polling(self):
        await self._poller.stop_polling()

    async def update_play_history(self) -> bool:
        return await self._poller.update_play_history()

    # ─────────────────────────────────────────────────────────────────────
    # Persistenz (→ PlayHistoryRepository) - inkl. der als "privat"
    # gekennzeichneten, aber extern getesteten Methoden.
    # ─────────────────────────────────────────────────────────────────────

    def _sanitize_filename(self, username: str) -> str:
        return self._repository.sanitize_username(username)

    def _get_history_file_for_user(self, navidrome_username: str):
        return self._repository.history_file_for_user(navidrome_username)

    def _load_history(self, navidrome_username: str) -> List[Dict[str, Any]]:
        return self._repository.load(navidrome_username)

    def _save_history(self, history: List[Dict[str, Any]], navidrome_username: str):
        self._repository.save(history, navidrome_username)

    def _cleanup_old_entries(self, navidrome_username: str):
        self._repository.cleanup_old_entries(navidrome_username)

    # ─────────────────────────────────────────────────────────────────────
    # Statistik-Berechnung (→ StatisticsCalculator)
    # ─────────────────────────────────────────────────────────────────────

    def generate_stats(
        self,
        period: str = "month",
        navidrome_username: str = None,
        now=None,
    ) -> Optional[Dict[str, Any]]:
        """`now` optional injizierbar (Statistics Menu UX & Architecture
        Optimization) - für deterministische Tests, durchgereicht an
        StatisticsCalculator.generate_stats()."""
        return self._calculator.generate_stats(period, navidrome_username, now=now)

    def generate_year_stats(
        self, navidrome_username: str = None, now=None
    ) -> Optional[Dict[str, Any]]:
        """Jahresstatistik (KPIs/Monatsaktivität/Highlight). Siehe
        StatisticsCalculator.generate_year_stats(). `now` optional
        injizierbar für deterministische Tests."""
        return self._calculator.generate_year_stats(navidrome_username, now=now)

    def get_last_played_song(
        self, navidrome_username: str = None
    ) -> Optional[Dict[str, Any]]:
        return self._calculator.get_last_played_song(navidrome_username)

    def generate_timeline_stats(
        self, navidrome_username: str = None, now=None
    ) -> Optional[Dict[str, Any]]:
        """Music-Timeline (Heute/Woche/Monat). Siehe StatisticsCalculator.
        `now` optional injizierbar für deterministische Tests."""
        return self._calculator.generate_timeline_stats(navidrome_username, now=now)

    def get_play_count_by_artist(
        self, artist_name: str, navidrome_username: str = None, period: str = "month"
    ) -> int:
        return self._calculator.get_play_count_by_artist(
            artist_name, navidrome_username, period
        )

    def generate_genre_stats(
        self, navidrome_username: str = None, top_n: int = 10
    ) -> Optional[Dict[str, Any]]:
        """Top-`top_n`-Genres nach Plays (All-Time, NAV-F8). Siehe
        StatisticsCalculator.generate_genre_stats()."""
        return self._calculator.generate_genre_stats(navidrome_username, top_n=top_n)

    def export_stats_to_json(
        self, navidrome_username: str = None, period: str = "month"
    ):
        return self._calculator.export_stats_to_json(navidrome_username, period)
