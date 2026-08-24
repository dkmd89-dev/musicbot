# api/navidrome_api.py

"""
NavidromeAPI (Rest) - enthält ausschließlich execute_scan().

ARCH-009 Phase 8: der reine Navidrome-API-Integrationsadapter
(__init__, _build_url, make_request, check_connection, get_artists,
get_now_playing, search) wurde nach services/clients/navidrome_api.py
verschoben (Option B, siehe
docs/MusicBot_ARCH-009_Phase8_Zielverschiebung_ServicesClients_Analyse.md).

execute_scan() bleibt bewusst hier: delegiert an NavidromeScanTrigger
(lokale Docker-/Subprocess-Steuerung, keine echte Subsonic-API-
Kommunikation, siehe ARCH-009 Phase 3/6) und gehört daher nicht in den
reinen Integrationsadapter unter services/clients/. Einziger Consumer:
handlers/menu/rich_menu_handler.py - unverändert, ruft weiterhin
NavidromeAPI.execute_scan() über diesen Importpfad auf.

ACHTUNG: Es gibt zwei verschiedene Klassen namens `NavidromeAPI` im
Repo - diese hier (nur execute_scan()) und
services.clients.navidrome_api.NavidromeAPI (die sechs reinen
API-Methoden). Bewusst getrennt gehalten (ARCH-009 Phase 8, Option B)
statt vermischt.
"""

import logging

from logger import log_handler_info, get_module_logger

from api.navidrome_scan_trigger import NavidromeScanTrigger, ScanRunResult

# ===== LOGGER AUF ERROR SETZEN (nur Fehler protokollieren) =====
_navidrome_logger = get_module_logger("NavidromeAPI")
_navidrome_logger.logger.setLevel(logging.ERROR)


class NavidromeAPI:
    """
    Rest-Klasse nach ARCH-009 Phase 8: enthält ausschließlich
    execute_scan(). Der eigentliche Navidrome-API-Adapter liegt in
    services.clients.navidrome_api.NavidromeAPI.
    """

    @classmethod
    async def execute_scan(cls) -> ScanRunResult:
        """
        Führt einen Navidrome-Scan aus.

        ARCH-009 Phase 5: reiner, telegramfreier Pass-Through zu
        NavidromeScanTrigger.run_scan(). execute_scan() enthält seitdem
        keinerlei Telegram-Präsentationslogik mehr (kein EMOJI, kein
        escape_md_v2, kein MarkdownV2) und reicht Exceptions
        (insbesondere ScanTimeoutError sowie AttributeError/TypeError bei
        fehlerhafter Konfiguration) unverändert durch. Die
        Telegram-MarkdownV2-Formatierung liegt seitdem vollständig im
        Consumer handlers/menu/rich_menu_handler.py::_handle_navidrome_scan()
        (siehe docs/MusicBot_ARCH-009_Phase5_Telegram_Verantwortlichkeiten_Analyse.md).

        ARCH-009 Phase 7: bleibt bewusst ein @classmethod (zustandsloser
        Pass-Through, benötigt keine injizierte Config/Instanz).
        """
        log_handler_info("Starte Navidrome Scan-Prozess.", context="NavidromeAPI")
        return await NavidromeScanTrigger.run_scan()
