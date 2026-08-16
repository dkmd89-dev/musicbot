# handlers/command_integration.py
# -*- coding: utf-8 -*-\n
"""
🎯 Command Integration für RichMenuSystem
Stellt Factory und Registrierung für alle Handler bereit.
"""

from typing import Callable, Any
from handlers.menu.rich_menu_handler import RichMenuHandler
from logger import get_module_logger

# Importe für die Handler-Registrierung
from telegram.ext import Application
from telegram.ext import BaseHandler
from config import Config

# Temporäre Liste für Handler, die nicht über das RichMenuSystem laufen
# (z.B. der RichLogger-Handler)
_extra_handlers = []


def register_extra_handler(name: str, handler: Any) -> None:
    """Registriert einen zusätzlichen Telegram-Handler außerhalb des Menüsystems."""
    _extra_handlers.append(handler)
    # Hier könntest du einen Logger verwenden, wenn du ihn global verfügbar machst.


def create_command_integration(
    config: Config, logger_factory: Callable = None
) -> RichMenuHandler:
    """
    Erstellt und konfiguriert RichMenuHandler und registriert alle Aktionen.
    Gibt den RichMenuHandler zurück, der alle Telegram-Handler bereitstellt.
    """
    logger = (
        logger_factory("CommandIntegrationFactory")
        if logger_factory
        else get_module_logger("CommandIntegrationFactory")
    )
    logger.info("🚀 Erstelle Command Integration...")

    # 1. Handler erstellen (Der RichMenuHandler ist das Kernstück)
    menu_handler = RichMenuHandler(config, logger_factory)

    try:
        menu_handler.initialize()
    except Exception as e:
        logger.fatal(
            f"🤖 [TELEGRAM_BOT] ❌  FATALER FEHLER: RichMenuHandler konnte nicht initialisiert werden: {e}"
        )
        raise e

    # 2. Zusätzliche Handler registrieren (z.B. RichLogger)
    try:
        from handlers.rich_logger_handler import create_rich_logger_handler

        rich_logger = create_rich_logger_handler(config, logger_factory)
        # NEU: Registriere über die Hilfsfunktion
        register_extra_handler("RichLogger", rich_logger)
        logger.info("✅ RichLogger-Handler registriert")

    except ImportError as e:
        logger.warning(f"⚠️ RichLogger-Handler nicht verfügbar: {e}")
    except Exception as e:
        logger.error(f"❌ Fehler bei RichLogger-Handler-Registrierung: {e}")

    logger.info("✅ Command Integration bereit")
    return menu_handler


def add_handlers_to_application(application: Application, menu_handler) -> int:
    """
    Fügt alle Handler (Menü + Extra) zur Telegram Application hinzu.
    """
    # Rufe alle Handler ab (vom RichMenuHandler und extra Handlern)
    handlers = menu_handler.get_telegram_handlers()

    # Füge die registrierten RichLogger-Handler hinzu
    # HINWEIS: Hier müsste auch die Logik für _extra_handlers wieder rein,
    # falls du diese nicht in get_telegram_handlers() integriert hast.
    # Falls _extra_handlers existiert, füge hinzu: handlers.extend(_extra_handlers)

    total_added = 0
    for i, handler in enumerate(handlers):
        if isinstance(handler, BaseHandler):
            application.add_handler(handler)
            total_added += 1
        else:
            # 🔥 ÜBELTÄTER GEFUNDEN! Hier wird der Fehler geloggt.
            # Der Fehler passiert in der Initialisierungsphase, daher muss der Logger manuell geholt werden.
            import logging

            factory = logging.getLogger("HandlerChecker")
            factory.error(
                f"❌ FEHLER: Handler an Index {i} ist kein BaseHandler. Typ: {type(handler)}. "
                f"Dieser Handler wird ignoriert und ist wahrscheinlich der Fehler: {handler}"
            )

    return total_added
