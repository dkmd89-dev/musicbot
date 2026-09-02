"""
Security-Sweep-Fund (docs/FINDINGS_INDEX.md): run_test_bot.py baut eine
Telegram-Bot-API-URL mit dem vollstaendigen BOT_TOKEN direkt in der URL
(".../bot<TOKEN>/getMe", so authentifiziert die Telegram-Bot-API - kein
Header). Schlaegt der Request fehl (Timeout, DNS, Connection Refused),
haengt requests die komplette Request-URL - inkl. Token - unmaskiert in
die Exception-Message ein. Der bisherige `except Exception as _e: print(f"...{_e}")`
haette den kompletten Token ins Terminal/eine mitgeschnittene Log-Datei
geschrieben.

Analog zu SEC-001 + Post-Baseline-Triage FINDING-3
(services/clients/navidrome_api.py::_scrub_credentials(), siehe
tests/test_navidrome_api_logging.py) - hier dieselbe Fehlerklasse fuer
den URL-Auth-Fall der Telegram-Bot-API statt Subsonic-Query-Params.

run_test_bot.py ist ein eigenstaendiges CLI-Werkzeug ohne __main__-Guard
vorher gewesen (dadurch NICHT sicher importierbar - jeder Import haette
argparse.parse_args(), einen echten .env-Load, sys.modules-Manipulation
und einen echten Netzwerk-Request ausgefuehrt). Guard ergaenzt (analog zu
scripts/reprocess_artist_metadata.py), _mask_token_in_message() als reine,
von Config entkoppelte Funktion an den Modulkopf gezogen - jetzt sicher
per importlib ladbar, ohne die geguardete Ausfuehrungslogik anzustossen.
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "run_test_bot.py"

_spec = importlib.util.spec_from_file_location("run_test_bot", MODULE_PATH)
run_test_bot = importlib.util.module_from_spec(_spec)
sys.modules["run_test_bot"] = run_test_bot
_spec.loader.exec_module(run_test_bot)


class TestImportHasNoSideEffects:
    def test_module_exposes_masking_function_without_running_main_block(self):
        """Grundvoraussetzung fuer alle folgenden Tests: der Import selbst
        darf argparse/.env-Load/Netzwerk-Request/Bot-Start NICHT ausloesen
        - nur moeglich, weil die eigentliche Ausfuehrung jetzt hinter
        `if __name__ == "__main__":` liegt."""
        assert hasattr(run_test_bot, "_mask_token_in_message")


class TestMaskTokenInMessage:
    def test_token_occurrence_is_replaced_with_masked_value(self):
        token = "123456789:AAFakeTokenForTestingPurposesOnly1234"
        masked = "***1234"
        message = (
            "HTTPSConnectionPool(host='api.telegram.org', port=443): "
            f"Max retries exceeded with url: /bot{token}/getMe "
            "(Caused by ConnectTimeoutError(...))"
        )

        result = run_test_bot._mask_token_in_message(message, token, masked)

        assert token not in result
        assert masked in result

    def test_message_without_token_occurrence_is_returned_unchanged(self):
        message = "Connection refused"
        result = run_test_bot._mask_token_in_message(
            message, "some-token-not-in-message", "***xxxx"
        )
        assert result == message

    def test_empty_token_does_not_corrupt_message(self):
        """Randfall-Schutz: ein leerer Token (sollte durch die BOT_TOKEN-
        Property in der Praxis nie auftreten, siehe config.py) darf die
        Nachricht nicht durch ein degeneriertes str.replace("", ...)
        zwischen jedem Zeichen zerhacken."""
        message = "some error message"
        result = run_test_bot._mask_token_in_message(message, "", "***")
        assert result == message

    def test_realistic_telegram_connect_timeout_message_is_fully_scrubbed(self):
        """End-to-End-artiges Beispiel mit dem tatsaechlichen Nachrichten-
        format, das requests.exceptions.ConnectTimeout liefert."""
        token = "987654321:ZZFakeTokenForRegressionTest0000"
        masked = "***0000"
        message = (
            "HTTPSConnectionPool(host='api.telegram.org', port=443): "
            f"Read timed out. (read timeout=10) for url: /bot{token}/getMe"
        )

        result = run_test_bot._mask_token_in_message(message, token, masked)

        assert token not in result
        assert "api.telegram.org" in result  # Rest der Meldung bleibt informativ
        assert "getMe" in result
