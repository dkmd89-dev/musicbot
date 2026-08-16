# yt_music_bot/cookie_handler.py

import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Any

# NEU: Nur die Funktion zum Erstellen eines Loggers importieren
from logger import get_module_logger


class CookieHandler:
    """Verwaltet Cookie-Dateien für YouTube-Downloads."""

    def __init__(
        self,
        cookie_path: Optional[str] = None,
        bot_directory: Optional[str] = None,
        logger: Optional[Any] = None,  # NEU: Logger als Abhängigkeit
    ):
        """Initialisiert den Cookie-Handler.

        Args:
            cookie_path: Optionaler Pfad zur Cookie-Datei.
            bot_directory: Optionaler Pfad zum Bot-Verzeichnis (nur verwendet, wenn cookie_path nicht gesetzt ist).
            logger: Eine konfigurierte Logger-Instanz. Wird keine übergeben, wird eine neue erstellt.
        """
        # NEU: Logger-Instanz über `self` verfügbar machen
        self.logger = logger or get_module_logger("CookieHandler")

        self.bot_directory = bot_directory or os.path.dirname(os.path.abspath(__file__))
        self.cookie_path = cookie_path or os.path.join(
            self.bot_directory, "cookies.txt"
        )
        self.logger.debug("CookieHandler initialisiert.")

    def has_cookies(self) -> bool:
        """Überprüft, ob die Cookie-Datei existiert und gültig ist."""
        if not os.path.exists(self.cookie_path):
            return False
        if os.path.getsize(self.cookie_path) < 10:  # Mindestgröße
            return False
        return True

    def backup_cookies(self) -> Optional[str]:
        """Erstellt ein Backup der Cookie-Datei."""
        if not self.has_cookies():
            return None

        backup_dir = os.path.join(self.bot_directory, "backups")
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"cookies_{timestamp}.txt")

        try:
            shutil.copy2(self.cookie_path, backup_path)
            # NEU: Logging über self.logger
            self.logger.info(f"🍪 Cookie-Backup erstellt: {backup_path}")
            return backup_path
        except Exception as e:
            # NEU: Logging über self.logger
            self.logger.error(f"❌ Fehler beim Cookie-Backup: {str(e)}")
            return None

    def install_cookies(self, new_cookie_path: str) -> bool:
        """Installiert eine neue Cookie-Datei."""
        if not os.path.exists(new_cookie_path):
            # NEU: Logging über self.logger
            self.logger.error(f"❌ Cookie-Datei nicht gefunden: {new_cookie_path}")
            return False

        if self.has_cookies():
            self.backup_cookies()

        try:
            shutil.copy2(new_cookie_path, self.cookie_path)
            # NEU: Logging über self.logger
            self.logger.info(f"✅ Neue Cookie-Datei installiert von {new_cookie_path}")
            return True
        except Exception as e:
            # NEU: Logging über self.logger
            self.logger.error(f"❌ Fehler beim Installieren der Cookie-Datei: {str(e)}")
            return False

    def get_cookie_info(self) -> dict:
        """Gibt Informationen über die Cookie-Datei zurück."""
        if not self.has_cookies():
            return {"status": "missing", "message": "Keine Cookie-Datei gefunden"}

        try:
            stat = os.stat(self.cookie_path)
            modified = datetime.fromtimestamp(stat.st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            size = stat.st_size

            with open(self.cookie_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                domain_count = content.count(".youtube.com")

            return {
                "status": "valid",
                "path": self.cookie_path,
                "size": size,
                "modified": modified,
                "domains": domain_count,
                "message": f"Cookie-Datei gefunden ({size} Bytes, {domain_count} YouTube-Domains)",
            }
        except Exception as e:
            # NEU: Logging über self.logger
            self.logger.error(f"Fehler beim Lesen der Cookie-Datei: {str(e)}")
            return {
                "status": "error",
                "path": self.cookie_path,
                "message": f"Fehler beim Lesen der Cookie-Datei: {str(e)}",
            }
