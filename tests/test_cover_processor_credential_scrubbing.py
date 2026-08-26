"""
P1-Fund (Post-Baseline-v4 Health & Risk Audit): CoverProcessor._get() gab
requests.RequestException bei einem Verbindungsfehler ungefiltert per
str(e) an self.logger.debug() weiter. Der Fanart.tv-API-Key wird als
params={"api_key": ...} an session.get() uebergeben - requests/urllib3
betten bei Connection-/Timeout-Fehlern die vollstaendige Request-URL
(inkl. Query-String) in die eigene str()-Repraesentation der Exception ein
(reales, dokumentiertes Verhalten, siehe auch der bereits fuer u=/p= in
services/clients/navidrome_api.py behobene, identische Fall). Bei
LOG_LEVEL=DEBUG (Config.LOG_LEVEL Default ist "INFO", aber user-konfigurierbar)
waere der Key damit im Klartext im Log gelandet.

Fix: _scrub_credentials() entfernt den api_key-Query-Parameter aus dem
Exception-String, bevor er geloggt wird - analoges Muster zu
navidrome_api.py::_scrub_credentials().
"""

from unittest.mock import Mock

import requests

from services.metadata.cover_processor import CoverProcessor, _scrub_credentials

SECRET = "SUPER_SECRET_FANART_KEY_123"


def make_processor():
    processor = CoverProcessor(fanart_api_key=SECRET, cache_enabled=False)
    processor.logger = Mock()
    return processor


class TestScrubCredentialsHelper:
    def test_api_key_as_only_param_is_scrubbed(self):
        text = f"... url: https://webservice.fanart.tv/v3/music/albums/x?api_key={SECRET} (Caused by ...)"
        scrubbed = _scrub_credentials(text)
        assert SECRET not in scrubbed
        assert "api_key=***" in scrubbed

    def test_api_key_combined_with_other_params_is_scrubbed(self):
        text = f"url: https://x/y?foo=bar&api_key={SECRET}&baz=qux"
        scrubbed = _scrub_credentials(text)
        assert SECRET not in scrubbed
        assert "foo=bar" in scrubbed
        assert "baz=qux" in scrubbed

    def test_case_insensitive_and_no_match_is_noop(self):
        assert _scrub_credentials(f"...?API_KEY={SECRET}...").find(SECRET) == -1
        assert _scrub_credentials("no secret here") == "no secret here"

    def test_empty_string_is_noop(self):
        assert _scrub_credentials("") == ""


class TestGetSwallowsAndScrubsConnectionError:
    def test_connection_error_with_embedded_api_key_is_not_logged_in_cleartext(self):
        """
        Deterministischer Beweis (kein Timing): simuliert exakt das reale
        requests/urllib3-Verhalten, indem die geworfene ConnectionError
        eine str()-Repraesentation mit eingebettetem api_key traegt - wie es
        echte HTTPSConnectionPool/MaxRetryError-Meldungen tatsaechlich tun.
        """
        processor = make_processor()
        raw_exception_text = (
            f"HTTPSConnectionPool(host='webservice.fanart.tv', port=443): "
            f"Max retries exceeded with url: /v3/music/albums/x?api_key={SECRET} "
            f"(Caused by ConnectTimeoutError(...))"
        )
        # Gegenprobe: die rohe Exception enthaelt den Key tatsaechlich -
        # sonst waere der Test bedeutungslos.
        assert SECRET in raw_exception_text

        def raising_get(*a, **kw):
            raise requests.exceptions.ConnectionError(raw_exception_text)

        processor.session.get = raising_get

        result = processor._get(
            "https://webservice.fanart.tv/v3/music/albums/x",
            params={"api_key": SECRET},
        )

        assert result is None
        processor.logger.debug.assert_called_once()
        logged_text = processor.logger.debug.call_args[0][0]
        assert SECRET not in logged_text, (
            f"Fanart-API-Key wurde im Klartext geloggt: {logged_text!r}"
        )

    def test_successful_request_is_unaffected(self):
        processor = make_processor()
        fake_response = Mock(status_code=200)
        processor.session.get = Mock(return_value=fake_response)

        result = processor._get(
            "https://webservice.fanart.tv/v3/music/albums/x",
            params={"api_key": SECRET},
        )

        assert result is fake_response
        processor.logger.debug.assert_not_called()
