#!/usr/bin/env python3
# run_test_bot.py – Startet den Bot mit Test-Konfiguration (isoliert)

import os
import sys
import argparse
from pathlib import Path


def _mask_token_in_message(message: str, token: str, masked: str) -> str:
    """
    Security-Sweep-Fund (docs/FINDINGS_INDEX.md): die Telegram-Bot-API
    authentifiziert per Token IN DER URL (".../bot<TOKEN>/getMe"), nicht
    per Header. requests haengt bei Verbindungsfehlern (Timeout, DNS,
    Connection Refused) die vollstaendige Request-URL unmaskiert in die
    Exception-Message ein - str(exc) direkt auszugeben wuerde den
    kompletten BOT_TOKEN ins Terminal/eine mitgeschnittene Log-Datei
    schreiben. Analog zu Config.mask_sensitive()/_scrub_credentials() in
    services/clients/navidrome_api.py (dort bereits fuer denselben
    requests-URL-in-Exception-Mechanismus gefixt, SEC-001 + Post-
    Baseline-Triage FINDING-3) - hier dieselbe Klasse Fund fuer den
    Telegram-Bot-API-URL-Auth-Fall.

    Reine, von Config/Modulzustand entkoppelte Funktion (nimmt den
    bereits maskierten Ersatzwert als Parameter entgegen, statt selbst
    Config.mask_sensitive() aufzurufen) - dadurch am Modulkopf platzierbar
    und ohne Ausfuehrung des restlichen Skripts direkt importierbar/
    testbar (siehe tests/test_run_test_bot_token_masking.py).
    """
    if not token or token not in message:
        return message
    return message.replace(token, masked)


if __name__ == "__main__":
    # 1. .env laden (für den Test-Token)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("⚠️  python-dotenv nicht installiert – verwende System-Umgebungsvariablen")

    # 2. Test-Config importieren
    import config_test

    # 3. Konfiguration aus der Config-Klasse holen
    Config = config_test.Config

    # Überschreibe das Modul "config" in sys.modules, damit bot.py beim Import
    # die Test-Config verwendet (statt der Produktions-Config)
    sys.modules['config'] = config_test

    # 4. Argumente parsen
    parser = argparse.ArgumentParser(description="MusicBot Test-Starter")
    parser.add_argument("--debug", action="store_true", help="Debug-Modus aktivieren")
    parser.add_argument("--dry-run", action="store_true", help="Nur Simulation, nichts ausführen")
    parser.add_argument("--clean", action="store_true", help="Test-Verzeichnis leeren und neu anlegen")
    args = parser.parse_args()

    # 5. Clean-Modus: Test-Verzeichnis zurücksetzen
    if args.clean:
        import shutil
        test_dir = Config.BASE_DIR
        if test_dir.exists():
            print(f"🧹 Lösche Test-Verzeichnis: {test_dir}")
            shutil.rmtree(test_dir)
        print("✅ Test-Verzeichnis neu erstellen")
        for d in [Config.LIBRARY_DIR, Config.DOWNLOAD_DIR,
                  Config.CACHE_DIR, Config.LOG_DIR]:
            d.mkdir(parents=True, exist_ok=True)
        print("✅ Bereinigt. Beende.")
        sys.exit(0)

    # 6. Umgebungsvariablen für den Bot setzen (optional)
    if args.debug:
        os.environ["LOG_LEVEL"] = "DEBUG"

    # 7. Bot starten (aus bot.py)
    print("🚀 Starte Test-Bot mit isolierter Konfiguration...")
    print(f"   Library: {Config.LIBRARY_DIR}")
    print(f"   Token:   {Config.BOT_TOKEN[:10]}... (gekürzt)")

    # PHASE 2I (Test-Environment-Diagnose): Test- und Produktions-Bot sind zwei
    # unterschiedliche Telegram-Bot-Accounts (unterschiedliche Tokens in .env:
    # BOT_TOKEN vs. TEST_TELEGRAM_TOKEN). Eine Testnachricht an den falschen
    # Bot-Account erreicht diesen Prozess nie, obwohl der Bot fehlerfrei
    # startet und pollt - deshalb hier explizit anzeigen, mit welchem
    # @username tatsächlich getestet werden muss.
    try:
        import requests
        _resp = requests.get(
            f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getMe", timeout=10
        )
        _bot_username = _resp.json().get("result", {}).get("username", "?")
        print(f"   Bot:     @{_bot_username}  ← DIESEN Bot-Account in Telegram anschreiben!")
    except Exception as _e:
        _safe_err = _mask_token_in_message(
            str(_e), Config.BOT_TOKEN, Config.mask_sensitive(Config.BOT_TOKEN)
        )
        print(f"   ⚠️  Bot-Identität konnte nicht abgefragt werden: {_safe_err}")

    # Importiere die Hauptfunktion aus bot.py
    try:
        from bot import main
        main()
    except (ImportError, AttributeError):
        # Falls bot.py keine main() hat, führe die Datei direkt aus
        print("ℹ️  bot.py hat keine main()-Funktion – führe Skript aus.")
        with open("bot.py", "r", encoding="utf-8") as f:
            code = compile(f.read(), "bot.py", "exec")
            exec(code)
