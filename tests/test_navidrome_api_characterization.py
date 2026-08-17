"""
Characterization-Tests fuer api/navidrome_api.py.

Vor dieser Session hatte NavidromeAPI ausser SEC-001 (Credential-Masking)
und REL-001 (Timeout) keinerlei Testabdeckung fuer die eigentliche
Geschaeftslogik - trotz P1-Status in CLAUDE.md ("externe Adapter",
"Navidrome"). Diese Tests dokumentieren das TATSAECHLICHE Verhalten der
produktiv genutzten Methoden (Regel: Characterization First), inkl. der
Subsonic-API-Eigenheiten (z.B. Einzel-Objekt statt Liste bei genau einem
Now-Playing-Eintrag) und der Fehlerbehandlungs-Inkonsistenz zwischen den
Methoden: check_connection()/get_scan_status()/get_full_server_info()
fangen Exceptions aus make_request() ab und liefern sichere Defaults,
waehrend get_artists()/search()/get_now_playing() Exceptions unveraendert
propagieren lassen (was in Produktion nur deshalb nicht auffaellt, weil
alle drei echten Aufrufer - navidrome_menu_handler.py, statistik_service.py
- selbst try/except um den Aufruf legen).

Alle Netzwerk-/Subprozess-Aufrufe werden gemockt (Regel 7 - externe
Dienste in Unit-Tests nicht real ansprechen).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.navidrome_api import NavidromeAPI


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


class TestGetScanStatus:
    def test_returns_scan_status_dict_on_success(self):
        with patch.object(
            NavidromeAPI,
            "make_request",
            return_value={
                "subsonic-response": {"scanStatus": {"scanning": True, "count": 42}}
            },
        ):
            result = asyncio.run(NavidromeAPI.get_scan_status())
        assert result == {"scanning": True, "count": 42}

    def test_returns_empty_dict_instead_of_raising_on_failure(self):
        with patch.object(NavidromeAPI, "make_request", side_effect=TimeoutError("slow")):
            result = asyncio.run(NavidromeAPI.get_scan_status())
        assert result == {}


class TestGetFullServerInfo:
    def _responses(self, **overrides):
        base = {
            "getScanStatus": {
                "subsonic-response": {
                    "status": "ok",
                    "scanStatus": {"lastScan": "2026-08-01T00:00:00Z", "scanning": False},
                }
            },
            "getArtists": {
                "subsonic-response": {
                    "status": "ok",
                    "artists": {"index": [{"artist": [{"id": "1"}, {"id": "2"}]}]},
                }
            },
            "getAlbumList2": {
                "subsonic-response": {
                    "albumList2": {"album": [{"songCount": 10}, {"songCount": 5}]}
                }
            },
            "getGenres": {
                "subsonic-response": {
                    "status": "ok",
                    "genres": {"genre": [{"value": "Rock"}, {"value": "Pop"}]},
                }
            },
            "ping": {
                "subsonic-response": {"status": "ok", "version": "1.16.1"}
            },
        }
        base.update(overrides)
        return base

    def test_happy_path_aggregates_all_fields(self):
        responses = self._responses()

        def fake_make_request(endpoint, params=None):
            return responses[endpoint]

        with patch.object(NavidromeAPI, "make_request", side_effect=fake_make_request):
            info = asyncio.run(NavidromeAPI.get_full_server_info())

        assert info["artist_count"] == 2
        assert info["song_count"] == 15
        assert info["genre_count"] == 2
        assert info["server_version"] == "1.16.1"
        assert info["scanning"] is False
        assert info["last_scan"] == "2026-08-01T00:00:00Z"

    def test_exception_mid_way_leaves_remaining_fields_at_defaults(self):
        """
        Dokumentiert bestehendes Verhalten: alle funf Sub-Requests liegen in
        EINEM gemeinsamen try-Block. Schlaegt z.B. getArtists fehl, werden
        die NACHFOLGENDEN Requests (getAlbumList2/getGenres/ping) gar nicht
        mehr ausgefuehrt - nur die bereits vor dem Fehler gesetzten Felder
        (hier: last_scan/scanning aus getScanStatus) bleiben erhalten.
        """
        responses = self._responses()

        call_order = ["getScanStatus", "getArtists"]

        def fake_make_request(endpoint, params=None):
            if endpoint == "getArtists":
                raise ConnectionError("Navidrome nicht erreichbar")
            return responses[endpoint]

        with patch.object(NavidromeAPI, "make_request", side_effect=fake_make_request):
            info = asyncio.run(NavidromeAPI.get_full_server_info())

        assert info["scanning"] is False
        assert info["last_scan"] == "2026-08-01T00:00:00Z"
        # Nicht mehr erreichte Felder bleiben bei ihren Initialwerten
        assert info["artist_count"] == 0
        assert info["song_count"] == 0
        assert info["genre_count"] == 0
        assert info["server_version"] == "Unbekannt"


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
    def test_success_returns_true_with_stdout_message(self):
        fake_process = AsyncMock()
        fake_process.communicate.return_value = (b"Scan complete", b"")
        fake_process.returncode = 0
        fake_process.pid = 1234

        with patch(
            "api.navidrome_api.asyncio.create_subprocess_shell",
            return_value=fake_process,
        ):
            success, message = asyncio.run(NavidromeAPI.execute_scan())

        assert success is True
        assert "Scan complete" in message or "Scan erfolgreich" in message

    def test_nonzero_returncode_returns_false(self):
        fake_process = AsyncMock()
        fake_process.communicate.return_value = (b"", b"boom")
        fake_process.returncode = 1
        fake_process.pid = 1234

        with patch(
            "api.navidrome_api.asyncio.create_subprocess_shell",
            return_value=fake_process,
        ):
            success, message = asyncio.run(NavidromeAPI.execute_scan())

        assert success is False

    def test_timeout_returns_false_with_timeout_message(self):
        async def never_completes(*args, **kwargs):
            await asyncio.sleep(9999)

        fake_process = AsyncMock()
        fake_process.communicate.side_effect = never_completes
        fake_process.pid = 1234

        with patch(
            "api.navidrome_api.asyncio.create_subprocess_shell",
            return_value=fake_process,
        ), patch("api.navidrome_api._get_navidrome_config") as mock_cfg, patch(
            "api.navidrome_api.Config"
        ) as mock_config_cls:
            mock_cfg.return_value.NAVIDROME_SCAN_COMMAND = "echo test"
            mock_config_cls.NAVIDROME_SCAN_COMMAND = "echo test"
            # NAVIDROME_SCAN_TIMEOUT auf 0 setzen, damit wait_for sofort auslaeuft
            mock_config_cls.NAVIDROME_SCAN_TIMEOUT = 0.01
            success, message = asyncio.run(NavidromeAPI.execute_scan())

        assert success is False
        assert "länger" in message or "Timeout" in message or "warten" in message.lower()

    def test_missing_scan_command_returns_false_without_crashing(self):
        with patch("api.navidrome_api._get_navidrome_config") as mock_cfg:
            mock_cfg.return_value.NAVIDROME_SCAN_COMMAND = ""
            success, message = asyncio.run(NavidromeAPI.execute_scan())

        assert success is False
