# services/statistik_service.py
"""
StatistikService – Fassade über die Wiedergabestatistik-Bausteine.

ARCH-003 (P-6): war vorher ein einzelner "God Service", der Persistenz,
externen API-Zugriff (Navidrome-Polling), Business-Statistik-Berechnung
und Chart-Rendering (matplotlib) vermischte. Jetzt in 4 fokussierte,
einzeln injizierbare/testbare Klassen aufgeteilt (services/statistik/):

  PlayHistoryRepository  – Lesen/Schreiben/Bereinigen der JSON-Verlaufsdateien
  PlayHistoryPoller       – Hintergrund-Polling gegen NavidromeAPI
  StatisticsCalculator    – Statistik-Berechnung aus dem Verlauf
  ChartRenderer           – matplotlib-Balkendiagramme

Diese Klasse selbst ist eine bewusst dünne, temporäre Fassade: sie bietet
exakt dieselbe öffentliche API wie vorher (inkl. der als "privat"
gekennzeichneten, aber von tests/test_statistik_service.py direkt
getesteten Methoden `_load_history`/`_save_history`/`_cleanup_old_entries`
sowie der Klassenattribute `CHARTS_DIR`/`USER_HISTORY_DIR`), damit
bot.py/handlers/mugge_statistik_handler.py unverändert bleiben können.
"""

from typing import Any, Dict, List, Optional

from services.clients.navidrome_api import NavidromeAPI
from config import Config
from logger import get_module_logger

from services.statistik.chart_renderer import ChartRenderer
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
        self._renderer = ChartRenderer(
            self.CHARTS_DIR, logger=get_module_logger("ChartRenderer")
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
        self, period: str = "month", navidrome_username: str = None
    ) -> Optional[Dict[str, Any]]:
        return self._calculator.generate_stats(period, navidrome_username)

    def get_last_played_song(
        self, navidrome_username: str = None
    ) -> Optional[Dict[str, Any]]:
        return self._calculator.get_last_played_song(navidrome_username)

    def get_play_count_by_artist(
        self, artist_name: str, navidrome_username: str = None, period: str = "month"
    ) -> int:
        return self._calculator.get_play_count_by_artist(
            artist_name, navidrome_username, period
        )

    def export_stats_to_json(
        self, navidrome_username: str = None, period: str = "month"
    ):
        return self._calculator.export_stats_to_json(navidrome_username, period)

    # ─────────────────────────────────────────────────────────────────────
    # Chart-Rendering (→ ChartRenderer)
    # ─────────────────────────────────────────────────────────────────────

    def create_chart(self, stats: Dict[str, Any], chart_type: str = "songs"):
        return self._renderer.create_chart(stats, chart_type)
