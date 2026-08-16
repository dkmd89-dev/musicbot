# -*- coding: utf-8 -*-
#!/usr/bin/env python3
import logging
from typing import Dict, List
from pathlib import Path
from telegram import Bot
from telegram.error import TelegramError

# Lokale Module
from config import Config

# Logging konfigurieren
logger = logging.getLogger(__name__)


class NotificationService:
    """Service-Klasse für das Senden von Benachrichtigungen über verschiedene Kanäle."""

    def __init__(self, log_dir: Path = Config.LOG_DIR):
        """
        Initialisiert den NotificationService.

        Args:
            log_dir (Path): Verzeichnis für Logdateien. Standard: Config.LOG_DIR.
        """
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(
            f"NotificationService initialisiert mit Log-Verzeichnis: {self.log_dir}"
        )

    def generate_telegram_status(
        self, stats: Dict[str, any], error_samples: List[str], max_files: int = 5
    ) -> str:
        """Generiert eine Telegram-freundliche Statusmeldung."""
        logger.debug("Generiere Telegram-Statusmeldung.")

        message = ["*Musikorganisation abgeschlossen* 🎵"]
        message.append(f"📊 *Statistiken*:")
        message.append(f"- Verarbeitete Dateien: {stats['processed']}")
        message.append(f"- Duplikate übersprungen: {stats['duplicates']}")
        message.append(f"- Fehler: {stats['errors']}")
        if "new_artists" in stats:
            message.append(f"- Neue Künstler: {stats['new_artists']}")
        if "new_albums" in stats:
            message.append(f"- Neue Alben: {stats['new_albums']}")

        if stats.get("moved_files"):
            message.append("\n*Verschobene Dateien* 📂")
            for i, (original, destination, file_type) in enumerate(
                stats["moved_files"][:max_files], 1
            ):
                message.append(f"{i}. *{original}* ({file_type})")
                message.append(f"   ➡️ {Path(destination).name}")
            if len(stats["moved_files"]) > max_files:
                message.append(
                    f"... und {len(stats['moved_files']) - max_files} weitere. Siehe Log für Details."
                )

        if stats["errors"] > 0 and error_samples:
            message.append("\n*Fehlerbeispiele* ⚠️")
            for error in error_samples[:3]:
                message.append(f"- {error}")

        message.append(f"\nDetails in Logdateien: `{self.log_dir}`")
        return "\n".join(message)

    async def send_telegram_message(self, message: str) -> bool:
        """
        Sendet eine Nachricht an den Telegram-Chat. Token und Chat-ID werden aus Config geholt.
        """
        bot_token = Config.BOT_TOKEN
        chat_id = Config.ADMIN_CHAT_ID

        logger.debug(f"Sende Telegram-Nachricht an Chat-ID {chat_id}.")
        try:
            bot = Bot(token=bot_token)
            await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
            logger.info("Telegram-Nachricht erfolgreich gesendet.")
            return True
        except TelegramError as e:
            logger.error(
                f"Fehler beim Senden der Telegram-Nachricht: {e}", exc_info=True
            )
            return False
        except Exception as e:
            logger.critical(
                f"Unerwarteter Fehler beim Senden der Telegram-Nachricht: {e}",
                exc_info=True,
            )
            return False

    def send_console_message(self, message: str) -> None:
        """Gibt eine Nachricht auf der Konsole aus."""
        logger.debug("Gebe Nachricht auf Konsole aus.")
        print(message)
