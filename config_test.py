#!/usr/bin/env python3
# config_test.py – Test-Konfiguration (erbt von Produktion)

import os
from pathlib import Path
from dotenv import load_dotenv

# Lade .env für den Test-Token
load_dotenv()

# Importiere die originale Config-Klasse
from config import Config as ProdConfig

class Config(ProdConfig):
    """
    Test-Konfiguration – überschreibt Pfade und Token.
    Alle nicht überschriebenen Attribute werden von der Produktions-Config geerbt.
    """
    
    # Alle Pfade auf /tmp/musicbot_test/ umleiten
    BASE_DIR = Path("/tmp/musicbot_test")
    LIBRARY_DIR = BASE_DIR / "library"
    PODCAST_DIR = BASE_DIR / "podcast"
    DOWNLOAD_DIR = BASE_DIR / "downloads"
    BACKUP_DIR = BASE_DIR / "backup"
    CACHE_DIR = BASE_DIR / "cache"
    LOG_DIR = BASE_DIR / "logs"
    LOG_FILE = LOG_DIR / "bot.log"
    STATS_DIR = BASE_DIR / "stats"
    
    # Token überschreiben (aus Umgebungsvariable)
    BOT_TOKEN = os.getenv("TEST_TELEGRAM_TOKEN")
    if not BOT_TOKEN:
        raise ValueError(
            "❌ TEST_TELEGRAM_TOKEN nicht gesetzt!\n"
            "   Bitte setze: export TEST_TELEGRAM_TOKEN='dein_token'"
        )
    
    # Test-spezifische Einstellungen
    LOG_LEVEL = "DEBUG"
    ENABLE_STATISTICS = False    # Deaktiviert für Tests
    ENABLE_BACKUP = False
    
    # Admin-IDs (optional – hier deine Telegram-ID eintragen)
    ADMIN_USER_IDS = []   # z.B. [123456789]

# ============================================================================
# WICHTIG: get_config() gibt eine INSTANZ zurück (nicht die Klasse!)
# ============================================================================
def get_config():
    """Gibt eine Instanz der Test-Config zurück – so werden @property aufgelöst."""
    return Config()

# ============================================================================
# Sicherheitsprüfung: NIE auf /mnt/ zeigen!
# ============================================================================
def _verify_isolation():
    config = get_config()
    if str(config.LIBRARY_DIR).startswith("/mnt/"):
        raise RuntimeError(
            "❌ Test-Config zeigt auf /mnt/ – das ist PRODUKTION!\n"
            f"   LIBRARY_DIR = {config.LIBRARY_DIR}\n"
            "   Ändere BASE_DIR in /tmp/ oder ~/test/"
        )
    return True

_verify_isolation()