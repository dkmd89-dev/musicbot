"""
Characterization-Tests fuer api/navidrome_api.py.

Vor dieser Session hatte NavidromeAPI ausser SEC-001 (Credential-Masking)
und REL-001 (Timeout) keinerlei Testabdeckung fuer die eigentliche
Geschaeftslogik - trotz P1-Status in CLAUDE.md ("externe Adapter",
"Navidrome"). Diese Tests dokumentieren das TATSAECHLICHE Verhalten der
produktiv genutzten Methoden (Regel: Characterization First), inkl. der
Subsonic-API-Eigenheiten (z.B. Einzel-Objekt statt Liste bei genau einem
Now-Playing-Eintrag) und der Fehlerbehandlungs-Inkonsistenz zwischen den
Methoden: check_connection() faengt Exceptions aus make_request() ab und
liefert einen sicheren Default (False), waehrend
get_artists()/search()/get_now_playing() Exceptions unveraendert
propagieren lassen (was in Produktion nur deshalb nicht auffaellt, weil
alle drei echten Aufrufer - navidrome_menu_handler.py, statistik_service.py
- selbst try/except um den Aufruf legen).

Alle Netzwerk-/Subprozess-Aufrufe werden gemockt (Regel 7 - externe
Dienste in Unit-Tests nicht real ansprechen).

ARCH-009 Phase 2 (2026-08-24): format_full_status_message()/
format_rescan_status_message()/format_web_interface_url_message()/
get_full_server_info()/get_scan_status()/test_api() wurden entfernt
(0 Produktions-Consumer, 0 bzw. nur diese eigenen Charakterisierungstests
- siehe docs/MusicBot_ARCH-009_Phase1_Bestandsaufnahme.md). Die
zugehoerigen TestGetScanStatus/TestGetFullServerInfo-Klassen wurden
entfernt. check_connection() bleibt bewusst erhalten (dokumentierter
BUG-007-Beleg fuer eine bewusst zurueckgestellte, geplante Nutzung).

ARCH-009 Phase 4 (2026-08-24): die Docker-/Subprocess-/Timeout-Steuerung
von execute_scan() wurde nach api/navidrome_scan_trigger.py
(NavidromeScanTrigger) ausgelagert - siehe
docs/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md.

ARCH-009 Phase 5 (2026-08-24): execute_scan() ist seitdem ein reiner,
telegramfreier Pass-Through zu NavidromeScanTrigger.run_scan() - keine
Telegram-Formatierung, kein Exception-Handling mehr in NavidromeAPI. Die
MarkdownV2-Formatierung liegt jetzt vollstaendig in
handlers/menu/rich_menu_handler.py (siehe
docs/MusicBot_ARCH-009_Phase5_Telegram_Verantwortlichkeiten_Analyse.md).
TestExecuteScan testet seitdem nur noch den Pass-Through-Vertrag: gibt
execute_scan() unveraendert das ScanRunResult von run_scan() zurueck bzw.
reicht es dessen Exceptions (ScanTimeoutError, AttributeError, ...)
unveraendert durch? Die Telegram-Formatierung selbst wird jetzt in
tests/test_rich_menu_handler.py::TestHandleNavidromeScan getestet, die
Subprocess-Charakterisierung weiterhin in tests/test_navidrome_scan_trigger.py.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.navidrome_api import NavidromeAPI
from api.navidrome_scan_trigger import NavidromeScanTrigger, ScanRunResult, ScanTimeoutError


class TestCheckConnection:
    def test_returns_true_when_ping_status_ok(self):
        with patch.object(
            NavidromeAPI, "make_request", return_value={"subsonic-response": {"status": "ok"}}
        ):
            result = asyncio.run(NavidromeAPI.check_connection())
        assert result is True

    def test_returns_false_when_ping_status_not_ok(self):
        with patch.object(
            NavidromeAPI, "make_request", return_value={"subsonic-response": {"status": "failed"}}
        ):
            result = asyncio.run(NavidromeAPI.check_connection())
        assert result is False

    def test_returns_false_instead_of_raising_when_make_request_fails(self):
        with patch.object(
            NavidromeAPI, "make_request", side_effect=ConnectionError("unreachable")
        ):
            result = asyncio.run(NavidromeAPI.check_connection())
        assert result is False


class TestGetArtists:
    def test_flattens_index_artist_structure(self):
        response = {
            "subsonic-response": {
                "artists": {
                    "index": [
                        {"artist": [{"id": "1", "name": "AC/DC"}]},
                        {"artist": [{"id": "2", "name": "Beatles"}, {"id": "3", "name": "Beck"}]},
                    ]
                }
            }
        }
        with patch.object(NavidromeAPI, "make_request", return_value=response):
            artists = asyncio.run(NavidromeAPI.get_artists())

        assert len(artists) == 3
        assert artists[0]["name"] == "AC/DC"

    def test_missing_artists_key_returns_empty_list_not_error(self):
        with patch.object(NavidromeAPI, "make_request", return_value={"subsonic-response": {}}):
            artists = asyncio.run(NavidromeAPI.get_artists())
        assert artists == []


class TestGetNowPlaying:
    def test_single_entry_object_is_normalized_to_list(self):
        """
        Subsonic-API-Eigenheit: bei genau einem aktiven Play liefert die
        API ein einzelnes Objekt statt einer Liste unter "entry".
        """
        response = {
            "subsonic-response": {
                "nowPlaying": {
                    "entry": {
                        "username": "robin",
                        "playerName": "Navidrome Web",
                        "song": {"title": "Song A", "artist": "Artist A", "album": "Album A", "id": "s1"},
                    }
                }
            }
        }
        with patch.object(NavidromeAPI, "make_request", return_value=response):
            result = asyncio.run(NavidromeAPI.get_now_playing())

        assert len(result) == 1
        assert result[0]["song"]["title"] == "Song A"
        assert result[0]["user"] == "robin"

    def test_multiple_entries_list_is_preserved(self):
        response = {
            "subsonic-response": {
                "nowPlaying": {
                    "entry": [
                        {"username": "a", "song": {"title": "T1"}},
                        {"username": "b", "song": {"title": "T2"}},
                    ]
                }
            }
        }
        with patch.object(NavidromeAPI, "make_request", return_value=response):
            result = asyncio.run(NavidromeAPI.get_now_playing())
        assert len(result) == 2

    def test_no_now_playing_key_returns_empty_list(self):
        with patch.object(
            NavidromeAPI, "make_request", return_value={"subsonic-response": {}}
        ):
            result = asyncio.run(NavidromeAPI.get_now_playing())
        assert result == []

    def test_missing_song_fields_default_to_na(self):
        response = {
            "subsonic-response": {
                "nowPlaying": {"entry": {"song": {}, "username": "robin"}}
            }
        }
        with patch.object(NavidromeAPI, "make_request", return_value=response):
            result = asyncio.run(NavidromeAPI.get_now_playing())
        assert result[0]["song"]["title"] == "N/A"


class TestSearch:
    def test_extracts_search_result3_from_response(self):
        response = {
            "subsonic-response": {
                "searchResult3": {"song": [{"title": "Found Song"}]}
            }
        }
        with patch.object(NavidromeAPI, "make_request", return_value=response) as mock_mr:
            result = asyncio.run(NavidromeAPI.search("test query"))

        assert result == {"song": [{"title": "Found Song"}]}
        _args, kwargs = mock_mr.call_args
        called_args = mock_mr.call_args[0]
        assert "search3" in called_args


class TestExecuteScan:
    """
    ARCH-009 Phase 5: execute_scan() ist ein reiner Pass-Through zu
    NavidromeScanTrigger.run_scan() - keine eigene Formatierung, kein
    eigenes Exception-Handling mehr.
    """

    def test_returns_run_scan_result_unchanged_on_success(self):
        expected = ScanRunResult(
            success=True, returncode=0, stdout="Scan complete", stderr=""
        )
        with patch.object(
            NavidromeScanTrigger, "run_scan", new=AsyncMock(return_value=expected)
        ):
            result = asyncio.run(NavidromeAPI.execute_scan())

        assert result is expected

    def test_returns_run_scan_result_unchanged_on_failure(self):
        expected = ScanRunResult(
            success=False, returncode=1, stdout="", stderr="boom"
        )
        with patch.object(
            NavidromeScanTrigger, "run_scan", new=AsyncMock(return_value=expected)
        ):
            result = asyncio.run(NavidromeAPI.execute_scan())

        assert result is expected

    def test_scan_timeout_error_propagates_unchanged(self):
        with patch.object(
            NavidromeScanTrigger,
            "run_scan",
            new=AsyncMock(side_effect=ScanTimeoutError(45)),
        ):
            with pytest.raises(ScanTimeoutError) as exc_info:
                asyncio.run(NavidromeAPI.execute_scan())

        assert exc_info.value.timeout_seconds == 45

    def test_missing_scan_command_attribute_error_propagates_unchanged(self):
        with patch.object(
            NavidromeScanTrigger,
            "run_scan",
            new=AsyncMock(
                side_effect=AttributeError(
                    "NAVIDROME_SCAN_COMMAND ist nicht in Config definiert oder leer."
                )
            ),
        ):
            with pytest.raises(AttributeError):
                asyncio.run(NavidromeAPI.execute_scan())
