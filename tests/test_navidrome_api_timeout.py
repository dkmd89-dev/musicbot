"""
Regressionstest fuer einen in Phase 3 gefundenen Zuverlaessigkeits-Bug:
NavidromeAPI.make_request() rief requests.get() ohne timeout auf. Haengt
Navidrome (nicht abgestuerzt, nur langsam/nicht antwortend), blockiert der
Aufruf unbegrenzt. Da make_request ueber asyncio.to_thread mit dem
geteilten Default-Executor aufgerufen wird (u.a. von check_connection(),
get_artists(), search()), kann das bei wiederholten Aufrufen den gesamten
Thread-Pool erschoepfen und damit den ganzen Bot lahmlegen, nicht nur die
Navidrome-Funktionen.

ARCH-009 Phase 7 (2026-08-24): make_request()/_build_url() sind jetzt
Instanzmethoden (DI) statt @classmethod/@staticmethod - Tests konstruieren
daher eine NavidromeAPI()-Instanz statt die Klasse direkt zu verwenden.

ARCH-009 Phase 8 (2026-08-24): NavidromeAPI (der reine Adapter) wurde nach
services/clients/navidrome_api.py verschoben - Import und
requests.get-Patch-Ziel entsprechend angepasst.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from services.clients.navidrome_api import NavidromeAPI
from config import Config


def _fake_response():
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"subsonic-response": {"status": "ok"}}
    response.status_code = 200
    return response


class TestTimeoutIsPassed:
    def test_make_request_passes_a_timeout_to_requests_get(self):
        api = NavidromeAPI()
        with patch.object(
            api,
            "_build_url",
            return_value="https://navidrome.example.test/rest/ping.view",
        ), patch("services.clients.navidrome_api.requests.get", return_value=_fake_response()) as mock_get:
            api.make_request("ping")

        assert mock_get.call_count == 1
        _args, kwargs = mock_get.call_args
        assert "timeout" in kwargs
        assert kwargs["timeout"] is not None
        assert kwargs["timeout"] > 0

    def test_timeout_uses_configured_value(self):
        api = NavidromeAPI()
        with patch.object(Config, "NAVIDROME_REQUEST_TIMEOUT", 7), patch.object(
            api,
            "_build_url",
            return_value="https://navidrome.example.test/rest/ping.view",
        ), patch(
            "services.clients.navidrome_api.requests.get", return_value=_fake_response()
        ) as mock_get:
            api.make_request("ping")

        assert mock_get.call_args.kwargs["timeout"] == 7


class TestTimeoutExceptionIsHandled:
    def test_requests_timeout_is_not_silently_swallowed(self):
        """
        Ein requests.exceptions.Timeout muss weiterhin propagiert werden
        (ueber den bestehenden allgemeinen except-Block), nicht als
        Erfolg maskiert werden.

        NAVIDROME-PASSWORD-LOG-LEAK-Fix (Post-Baseline-Triage FINDING-3):
        der allgemeine except-Block wandelt die Original-Exception seither
        bewusst in ein RuntimeError mit bereinigter Nachricht um (statt sie
        unveraendert weiterzureichen) - andernfalls wuerde requests' eigene
        Exception-Message (bzw. deren Traceback-Chaining via exc_info=True
        bei Aufrufern) die Klartext-Subsonic-Credentials aus den Request-
        Query-Params (u=/p=) leaken. Kein Aufrufer im Repo unterscheidet
        nach Exception-Typ (repo-weit geprueft), der Typwechsel ist daher
        unkritisch - entscheidend ist weiterhin nur, dass ueberhaupt eine
        Exception propagiert (kein Erfolg maskiert wird).
        """
        api = NavidromeAPI()
        with patch.object(
            api,
            "_build_url",
            return_value="https://navidrome.example.test/rest/ping.view",
        ), patch(
            "services.clients.navidrome_api.requests.get",
            side_effect=requests.exceptions.Timeout("timed out"),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                api.make_request("ping")
