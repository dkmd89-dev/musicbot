#!/usr/bin/env python3
"""
Test-Bot Starter
Startet den Bot mit Test-Konfiguration in isolierter Umgebung.

Verwendung:
    python run_test_bot.py              # Normaler Testbetrieb
    python run_test_bot.py --debug      # Debug-Modus mit mehr Logs
    python run_test_bot.py --dry-run    # Nur Initialisierung testen
"""

import os
import sys
import asyncio
import logging
from pathlib import Path
import argparse

# Setze Test-Umgebungsvariable
os.environ["MUSICBOT_ENV"] = "test"

# Füge Projekt zum Pfad hinzu
sys.path.insert(0, str(Path(__file__).parent))

# Importiere Test-Konfiguration statt der normalen Config
import config_test as config

# Logging für den Test-Modus
logging.basicConfig(
    level=logging.DEBUG if '--debug' in sys.argv else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.LOG_DIR / "test_bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)


async def run_test_bot(debug=False, dry_run=False):
    """Startet den Bot im Test-Modus"""
    
    print(f"\n{'='*60}")
    print(f"🧪 MUSICBOT TEST-Umgebung")
    print(f"{'='*60}")
    print(f"📁 Test-Verzeichnis: {config.TEST_DIR}")
    print(f"📁 Library: {config.LIBRARY_DIR}")
    print(f"📁 Logs: {config.LOG_DIR}")
    print(f"📁 Downloads: {config.DOWNLOAD_DIR}")
    print(f"🤖 Bot-Token: {config.TELEGRAM_TOKEN[:10]}...")
    print(f"🔍 Debug: {'JA' if debug else 'NEIN'}")
    print(f"💨 Dry-Run: {'JA' if dry_run else 'NEIN'}")
    print(f"{'='*60}\n")
    
    if dry_run:
        logger.info("🔍 DRY-RUN: Initialisiere nur Komponenten...")
        # Hier kannst du die Initialisierung testen
        # ohne den Bot wirklich zu starten
        
        # Teste Imports
        try:
            import bot as production_bot
            from klassen.download_handler import DownloadHandler
            logger.info("✅ Alle Module können geladen werden")
        except Exception as e:
            logger.error(f"❌ Import-Fehler: {e}")
            return
        
        # Teste Config
        for attr in ['LIBRARY_DIR', 'DOWNLOAD_DIR', 'LOG_DIR']:
            if hasattr(config, attr):
                logger.info(f"   ✅ {attr}: {getattr(config, attr)}")
            else:
                logger.warning(f"   ⚠️  {attr} nicht in config_test")
        
        logger.info("✅ DRY-RUN abgeschlossen")
        return
    
    try:
        # Importiere den Bot (mit Test-Config)
        import bot as production_bot
        
        # Ersetze die Config im Bot-Modul
        import importlib
        import config as original_config
        
        # Patch: Ersetze die Config-Module
        original_config.__dict__.update(config.__dict__)
        
        # Erstelle eine neue Bot-Instanz
        # (Passe dies an deine Bot-Initialisierung an)
        from klassen.bot_runner import BotRunner
        
        # Deaktiviere Produktions-Features für Tests
        bot_runner = BotRunner(
            config=config,
            enable_backup=False,
            enable_statistics=False
        )
        
        logger.info("🚀 Starte Test-Bot Polling...")
        await bot_runner.start_polling()
        
    except KeyboardInterrupt:
        logger.info("\n⏹️  Test-Bot durch Benutzer gestoppt")
    except Exception as e:
        logger.error(f"❌ Fehler im Test-Bot: {e}")
        if debug:
            import traceback
            traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="MusicBot Test-Umgebung")
    parser.add_argument("--debug", action="store_true", help="Debug-Modus")
    parser.add_argument("--dry-run", action="store_true", help="Nur Initialisierung testen")
    parser.add_argument("--clean", action="store_true", help="Test-Verzeichnis leeren")
    args = parser.parse_args()
    
    if args.clean:
        import shutil
        test_dir = Path(__file__).parent / "test_env"
        if test_dir.exists():
            print(f"🧹 Lösche Test-Verzeichnis: {test_dir}")
            shutil.rmtree(test_dir)
            print("✅ Test-Verzeichnis gelöscht")
        return
    
    try:
        asyncio.run(run_test_bot(args.debug, args.dry_run))
    except KeyboardInterrupt:
        print("\n⏹️  Abbruch durch Benutzer")
        sys.exit(0)


if __name__ == "__main__":
    main()
