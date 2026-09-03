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
    #
    # TESTENV-01 (docs/archive/MusicBot_TESTENV01_ISOLATION_AUDIT.md): in
    # config.py::Config sind viele Pfade als "BASE_DIR / '...'" direkt im
    # Klassenkoerper der PRODUKTIONS-Klasse berechnet - das wird einmalig
    # bei DEREN Definition ausgewertet, nicht dynamisch pro Subklasse neu.
    # Ein Ueberschreiben von BASE_DIR allein reicht deshalb NICHT aus, um
    # davon abgeleitete Attribute zu isolieren - jedes einzelne muss hier
    # explizit neu gesetzt werden. Live bestaetigt: ohne diese Ergaenzung
    # schrieb ein Test-Download tatsaechlich in die echte Produktions-
    # Duplicate-Cache und in echte Mapping-Dateien
    # (mapping/auto_learned_*.yaml).
    BASE_DIR = Path("/tmp/musicbot_test")
    LIBRARY_DIR = BASE_DIR / "library"
    PODCAST_DIR = BASE_DIR / "podcast"
    DOWNLOAD_DIR = BASE_DIR / "downloads"
    PROCESSED_DIR = BASE_DIR / "import" / "prozess"
    FAIL_DIR = BASE_DIR / "import" / "fail"
    ARCHIVE_DIR = BASE_DIR / "import" / "archiv"
    BACKUP_DIR = BASE_DIR / "backup"
    CACHE_DIR = BASE_DIR / "cache"
    DATA_DIR = BASE_DIR / "cache" / "data"
    ESCAPE_DIR = BASE_DIR / "cache" / "escaped_scripts"
    METADATA_CACHE_DIR = BASE_DIR / "cache" / "metadata_cache"
    DUPLICATE_CACHE_DIR = BASE_DIR / "cache" / "duplicate_cache"
    LYRICS_CACHE_DIR = BASE_DIR / "cache" / "lyrics_cache"
    DOWNLOAD_HISTORY_DIR = BASE_DIR / "cache" / "download_history"
    LOG_DIR = BASE_DIR / "logs"
    LOG_FILE = LOG_DIR / "bot.log"
    STATS_DIR = BASE_DIR / "stats"
    # Mapping-/Override-Dateien werden gelesen (fuer sinnvolle Testergebnisse
    # sollen dieselben Regeln wie in Produktion gelten) - aber nicht am
    # selben Ort GESCHRIEBEN, da Auto-Learning/Case-Preserve/Override-Sync
    # sonst dieselbe Datei-Korruption/Vermischung wie bei den Caches oben
    # verursachen wuerde. Deshalb: lesend von der echten mapping/-Kopie in
    # ein isoliertes Test-Mapping-Verzeichnis vorkopiert (siehe
    # _prepare_isolated_mapping_dir() unten), nicht direkt auf die
    # Produktionsdatei verweisen.
    GENRE_MAPPING_DIR = BASE_DIR / "mapping"
    ARTIST_OVERRIDE_FILE = GENRE_MAPPING_DIR / "artist_overrides.json"
    ARTIST_OVERRIDE_EXPANDED_FILE = (
        GENRE_MAPPING_DIR / "artist_overrides_expanded.json"
    )
    PLAY_HISTORY_FILE = BASE_DIR / "history" / "user_histories"
    
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
# TESTENV-01: isolierte Mapping-Kopie vorbereiten
# ============================================================================
def _prepare_isolated_mapping_dir() -> None:
    """
    Kopiert die echte mapping/-Konfiguration einmalig (falls das isolierte
    Test-Verzeichnis noch nicht existiert) nach Config.GENRE_MAPPING_DIR,
    damit Genre-/Artist-Normalisierung im Test dieselben kuratierten Regeln
    wie in Produktion nutzt (artist_overrides.json, genre_hierarchy.yaml,
    case_preserve.yaml, ...). Auto-Learning/Case-Preserve-Schreibzugriffe
    landen dadurch ausschließlich in der isolierten Kopie, nie in der
    echten mapping/-Quelle. `run_test_bot.py --clean` löscht die Kopie mit
    - der nächste Start kopiert dann automatisch wieder frisch von der
    echten Quelle.
    """
    import shutil

    real_mapping_dir = Path(__file__).parent / "mapping"
    test_mapping_dir = Config.GENRE_MAPPING_DIR
    if test_mapping_dir.exists():
        return
    if not real_mapping_dir.exists():
        return
    test_mapping_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(real_mapping_dir, test_mapping_dir)


_prepare_isolated_mapping_dir()

# TESTENV-01-Nachtrag: PLAY_HISTORY_FILE existiert in Produktion bereits
# dauerhaft und wird dort nirgends per mkdir() angelegt - in der frisch
# isolierten Testumgebung fehlte das Verzeichnis dadurch beim ersten
# Start nach --clean (StatisticsHandler/History-Polling scheiterte mit
# FileNotFoundError, Bot lief aber mit deaktivierter Statistik weiter).
Config.PLAY_HISTORY_FILE.mkdir(parents=True, exist_ok=True)

# ============================================================================
# Sicherheitsprüfung: NIE auf Produktionspfade zeigen!
# ============================================================================
# TESTENV-01: alle von BASE_DIR abgeleiteten Schreib-/Lese-Pfade, die
# isoliert sein MÜSSEN (siehe Kommentar bei der Klassendefinition oben).
# COOKIES_FILE ist bewusst NICHT enthalten - die echte cookies.txt wird
# absichtlich geteilt (read-only, sonst funktioniert die yt-dlp-
# Authentifizierung im Test nicht). Backup-Quell-/Zielpfade sind bewusst
# NICHT enthalten - ENABLE_BACKUP=False deaktiviert diesen Codepfad im
# Test bereits vollständig.
_ISOLATION_REQUIRED_ATTRS = [
    "LIBRARY_DIR",
    "PODCAST_DIR",
    "DOWNLOAD_DIR",
    "TEMP_DIR",
    "PROCESSED_DIR",
    "FAIL_DIR",
    "ARCHIVE_DIR",
    "DATA_DIR",
    "ESCAPE_DIR",
    "METADATA_CACHE_DIR",
    "DUPLICATE_CACHE_DIR",
    "LYRICS_CACHE_DIR",
    "LOG_DIR",
    "LOG_FILE",
    "ARTIST_OVERRIDE_FILE",
    "ARTIST_OVERRIDE_EXPANDED_FILE",
    "GENRE_MAPPING_DIR",
    "PLAY_HISTORY_FILE",
]


def _verify_isolation():
    config = get_config()
    prod_base_dir = str(ProdConfig.BASE_DIR)
    leaking = [
        attr
        for attr in _ISOLATION_REQUIRED_ATTRS
        if str(getattr(config, attr, "")).startswith(prod_base_dir)
        or str(getattr(config, attr, "")) == str(getattr(ProdConfig, attr, None))
    ]
    if leaking:
        details = "\n".join(
            f"   {attr} = {getattr(config, attr)}" for attr in leaking
        )
        raise RuntimeError(
            "❌ Test-Config zeigt bei folgenden Pfaden weiterhin auf die "
            f"echte Produktion ({prod_base_dir}):\n{details}\n"
            "   Jeder BASE_DIR-abgeleitete Pfad muss in config_test.py "
            "einzeln überschrieben werden (siehe TESTENV-01)."
        )
    return True

_verify_isolation()