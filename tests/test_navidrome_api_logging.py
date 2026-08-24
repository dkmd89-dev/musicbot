"""
Regressionstest fuer SEC-001 (Engineering Baseline, docs/MusicBot_ENGINEERING_BASELINE.md).

api.navidrome_api.NavidromeAPI.make_request loggte frueher die vollstaendigen
Request-Params inkl. NAVIDROME_USER/NAVIDROME_PASS im Klartext ueber
log_handler_info(). Der einzige bisherige Schutz war logging.ERROR auf dem
Modul-Logger "NavidromeAPI" - der wird jedoch von der Telegram-Admin-Funktion
"globales Log-Level setzen" (handlers/enhanced_logger_menu_handler.py,
set_global_log_level) bei jeder Level-Aenderung ueberschrieben, da dort ueber
alle _module_loggers iteriert und deren Level gesetzt wird.

Dieser Test simuliert genau dieses Szenario: das Modul-Logger-Level wird wie
durch die Admin-Funktion auf INFO angehoben, danach darf das Navidrome-Passwort
in keinem Log-Record mehr auftauchen.

ARCH-009 Phase 7 (2026-08-24): _auth_params/make_request()/_build_url()
sind jetzt Instanzattribut bzw. Instanzmethoden (DI) statt Klassenattribut/
@classmethod/@staticmethod - der Test patcht daher eine NavidromeAPI()-
Instanz statt der Klasse.
"""

import logging
from unittest.mock import MagicMock, patch

from logger import get_module_logger
from api.navidrome_api import NavidromeAPI


def test_navidrome_password_not_logged_when_module_log_level_raised(caplog):
    fake_auth_params = {
        "u": "musicbot_admin",
        "p": "s3cr3t-navidrome-pass",
        "v": "1.16.1",
        "c": "telegram-bot",
        "f": "json",
    }

    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"subsonic-response": {"status": "ok"}}
    fake_response.status_code = 200

    navidrome_logger = get_module_logger("NavidromeAPI")
    original_level = navidrome_logger.logger.level
    # Simuliert genau enhanced_logger_menu_handler.set_global_log_level(),
    # das bei jeder Aenderung ALLE _module_loggers-Level ueberschreibt.
    navidrome_logger.logger.setLevel(logging.INFO)

    api = NavidromeAPI()

    try:
        with patch.object(api, "_auth_params", fake_auth_params), patch.object(
            api,
            "_build_url",
            return_value="https://navidrome.example.test/rest/ping.view",
        ), patch("api.navidrome_api.requests.get", return_value=fake_response):
            with caplog.at_level(logging.INFO):
                api.make_request("ping")
    finally:
        navidrome_logger.logger.setLevel(original_level)

    log_text = "\n".join(record.getMessage() for record in caplog.records)

    assert log_text, "Es sollte mindestens ein Log-Record erzeugt worden sein (INFO ist jetzt aktiv)."
    assert fake_auth_params["p"] not in log_text
    assert fake_auth_params["u"] not in log_text
