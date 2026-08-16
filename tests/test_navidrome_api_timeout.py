"""
Regressionstest fuer einen in Phase 3 gefundenen Zuverlaessigkeits-Bug:
NavidromeAPI.make_request() rief requests.get() ohne timeout auf. Haengt
Navidrome (nicht abgestuerzt, nur langsam/nicht antwortend), blockiert der
Aufruf unbegrenzt. Da make_request ueber asyncio.to_thread mit dem
geteilten Default-Executor aufgerufen wird (check_connection,
get_scan_status, get_full_server_info etc.), kann das bei wiederholten
Aufrufen den gesamten Thread-Pool erschoepfen und damit den ganzen Bot
lahmlegen, nicht nur die Navidrome-Funktionen.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from api.navidrome_api import NavidromeAPI
from config import Config


def _fake_response():
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"subsonic-response": {"status": "ok"}}
    response.status_code = 200
    return response


class TestTimeoutIsPassed:
    def test_make_request_passes_a_timeout_to_requests_get(self):
        with patch.object(
            NavidromeAPI,
            "_build_url",
            return_value="https://navidrome.example.test/rest/ping.view",
        ), patch("api.navidrome_api.requests.get", return_value=_fake_response()) as mock_get:
            NavidromeAPI.make_request("ping")

        assert mock_get.call_count == 1
        _args, kwargs = mock_get.call_args
        assert "timeout" in kwargs
        assert kwargs["timeout"] is not None
        assert kwargs["timeout"] > 0

    def test_timeout_uses_configured_value(self):
        with patch.object(Config, "NAVIDROME_REQUEST_TIMEOUT", 7), patch.object(
            NavidromeAPI,
            "_build_url",
            return_value="https://navidrome.example.test/rest/ping.view",
        ), patch(
            "api.navidrome_api.requests.get", return_value=_fake_response()
        ) as mock_get:
            NavidromeAPI.make_request("ping")

        assert mock_get.call_args.kwargs["timeout"] == 7


class TestTimeoutExceptionIsHandled:
    def test_requests_timeout_is_not_silently_swallowed(self):
        """
        Ein requests.exceptions.Timeout muss weiterhin propagiert werden
        (ueber den bestehenden allgemeinen except-Block), nicht als
        Erfolg maskiert werden.
        """
        with patch.object(
            NavidromeAPI,
            "_build_url",
            return_value="https://navidrome.example.test/rest/ping.view",
        ), patch(
            "api.navidrome_api.requests.get",
            side_effect=requests.exceptions.Timeout("timed out"),
        ):
            with pytest.raises(requests.exceptions.Timeout):
                NavidromeAPI.make_request("ping")
