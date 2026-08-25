# /mnt/128ssd/musicbot/config_test.py
"""
Test-Konfiguration für den MusicBot
Verwendet isolierte Verzeichnisse und Test-Token.
Niemals mit Produktions-Config verwechseln!
"""

import os
from pathlib import Path

# ============================================================================
# BASIS-VERZEICHNIS (ALLE Tests isoliert in /tmp)
# ============================================================================
# !!! WICHTIG: Nichts in /mnt/4tb/ oder /mnt/128ssd/ schreiben !!!
BASE_DIR = Path("/tmp/musicbot_test")  # Temporäres Verzeichnis

# Alle Unterverzeichnisse unter /tmp/musicbot_test/
TEST_DIR = BASE_DIR
LIBRARY_DIR = BASE_DIR / "library"
PODCAST_DIR = BASE_DIR / "podcast"
DOWNLOAD_DIR = BASE_DIR / "downloads"
BACKUP_DIR = BASE_DIR / "backup"
CACHE_DIR = BASE_DIR / "cache"
LOG_DIR = BASE_DIR / "logs"

# Verzeichnisse automatisch anlegen
for d in [LIBRARY_DIR, PODCAST_DIR, DOWNLOAD_DIR, BACKUP_DIR, CACHE_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================================
# TELEGRAM - TEST BOT (VON @BotFather ERSTELLT!)
# ============================================================================
# !!! NIEMALS den echten Produktions-Token hier verwenden !!!
# Erstelle einen neuen Bot über @BotFather mit einem anderen Namen
TELEGRAM_TOKEN = os.getenv("TEST_TELEGRAM_TOKEN", "DEIN_TEST_BOT_TOKEN_HIER")

# ============================================================================
# NAVIDROME (für Tests - optional)
# ============================================================================
NAVIDROME_URL = os.getenv("TEST_NAVIDROME_URL", "http://localhost:4533")
NAVIDROME_USER = os.getenv("TEST_NAVIDROME_USER", "testuser")
NAVIDROME_PASSWORD = os.getenv("TEST_NAVIDROME_PASSWORD", "testpass")

# ============================================================================
# API KEYS (für Tests - Dummy oder echte Test-Keys)
# ============================================================================
LASTFM_API_KEY = os.getenv("TEST_LASTFM_API_KEY", "dummy_key")
GENIUS_API_KEY = os.getenv("TEST_GENIUS_API_KEY", "dummy_key")
MUSICBRAINZ_USER = os.getenv("TEST_MUSICBRAINZ_USER", "")

# ============================================================================
# BOT SETTINGS
# ============================================================================
LOG_LEVEL = "DEBUG"
ENABLE_STATISTICS = False  # In Tests deaktivieren
ENABLE_BACKUP = False       # In Tests deaktivieren
ENABLE_DOWNLOADS = True     # Downloads erlaubt (aber in TEST-Verzeichnis!)

# ============================================================================
# PFADE - ZUR SICHERHEIT NOCHMALS PRÜFEN
# ============================================================================
def verify_isolation():
    """Prüft ob wir wirklich im Test-Modus sind"""
    if str(LIBRARY_DIR).startswith("/mnt/"):
        raise RuntimeError(
            "❌ Test-Config zeigt auf /mnt/ - das ist PRODUKTION!\n"
            f"   LIBRARY_DIR = {LIBRARY_DIR}\n"
            "   Ändere BASE_DIR in /tmp/ oder ~/test/"
        )
    return True

# Führe Prüfung beim Import aus
verify_isolation()
