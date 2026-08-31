"""
Characterization-Tests fuer services/clients/navidrome_api.py
(NavidromeAPI-Adapter).

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
- siehe docs/archive/arch/MusicBot_ARCH-009_Phase1_Bestandsaufnahme.md). Die
zugehoerigen TestGetScanStatus/TestGetFullServerInfo-Klassen wurden
entfernt. check_connection() bleibt bewusst erhalten (dokumentierter
BUG-007-Beleg fuer eine bewusst zurueckgestellte, geplante Nutzung).

ARCH-009 Phase 4 (2026-08-24): die Docker-/Subprocess-/Timeout-Steuerung
von execute_scan() wurde nach api/navidrome_scan_trigger.py
(NavidromeScanTrigger) ausgelagert - siehe
docs/archive/arch/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md.

ARCH-009 Phase 5 (2026-08-24): execute_scan() ist seitdem ein reiner,
telegramfreier Pass-Through zu NavidromeScanTrigger.run_scan() - keine
Telegram-Formatierung, kein Exception-Handling mehr in NavidromeAPI. Die
MarkdownV2-Formatierung liegt jetzt vollstaendig in
handlers/menu/rich_menu_handler.py (siehe
docs/archive/arch/MusicBot_ARCH-009_Phase5_Telegram_Verantwortlichkeiten_Analyse.md).
TestExecuteScan testet seitdem nur noch den Pass-Through-Vertrag: gibt
execute_scan() unveraendert das ScanRunResult von run_scan() zurueck bzw.
reicht es dessen Exceptions (ScanTimeoutError, AttributeError, ...)
unveraendert durch? Die Telegram-Formatierung selbst wird jetzt in
tests/test_rich_menu_handler.py::TestHandleNavidromeScan getestet, die
Subprocess-Charakterisierung weiterhin in tests/test_navidrome_scan_trigger.py.

ARCH-009 Phase 7 (2026-08-24): NavidromeAPI ist jetzt instanziierbar mit
injizierbarer Config (DI) statt einer rein statischen Klasse - make_request/
check_connection/get_artists/get_now_playing/search sind jetzt echte
Instanzmethoden statt @classmethod. TestCheckConnection/TestGetArtists/
TestGetNowPlaying/TestSearch konstruieren daher jetzt eine Instanz
(`NavidromeAPI()`) und patchen deren make_request statt der Klasse.
Neu (Phase 7): TestDependencyInjection verifiziert die eigentliche
DI-Faehigkeit (unterschiedliche injizierte Configs ergeben unabhaengige
Instanzen).

ARCH-009 Phase 8 (2026-08-24): der reine Navidrome-API-Adapter (alle in
dieser Datei getesteten Methoden) wurde von api/navidrome_api.py nach
services/clients/navidrome_api.py verschoben (Option B, siehe
docs/archive/arch/MusicBot_ARCH-009_Phase8_Zielverschiebung_ServicesClients_Analyse.md).
execute_scan() ist NICHT Teil dieser Verschiebung - bleibt als
eigenstaendiger Rest in api/navidrome_api.py und wird seitdem separat in
tests/test_navidrome_api_execute_scan.py getestet (dort auch weiterhin
Pass-Through-Vertrag zu NavidromeScanTrigger, siehe ARCH-009 Phase 5).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from services.clients.navidrome_api import NavidromeAPI


class TestCheckConnection:
    def test_returns_true_when_ping_status_ok(self):
        api = NavidromeAPI()
        with patch.object(
            api, "make_request", return_value={"subsonic-response": {"status": "ok"}}
        ):
            result = asyncio.run(api.check_connection())
        assert result is True

    def test_returns_false_when_ping_status_not_ok(self):
        api = NavidromeAPI()
        with patch.object(
            api, "make_request", return_value={"subsonic-response": {"status": "failed"}}
        ):
            result = asyncio.run(api.check_connection())
        assert result is False

    def test_returns_false_instead_of_raising_when_make_request_fails(self):
        api = NavidromeAPI()
        with patch.object(
            api, "make_request", side_effect=ConnectionError("unreachable")
        ):
            result = asyncio.run(api.check_connection())
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
        api = NavidromeAPI()
        with patch.object(api, "make_request", return_value=response):
            artists = asyncio.run(api.get_artists())

        assert len(artists) == 3
        assert artists[0]["name"] == "AC/DC"

    def test_missing_artists_key_returns_empty_list_not_error(self):
        api = NavidromeAPI()
        with patch.object(api, "make_request", return_value={"subsonic-response": {}}):
            artists = asyncio.run(api.get_artists())
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
        api = NavidromeAPI()
        with patch.object(api, "make_request", return_value=response):
            result = asyncio.run(api.get_now_playing())

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
        api = NavidromeAPI()
        with patch.object(api, "make_request", return_value=response):
            result = asyncio.run(api.get_now_playing())
        assert len(result) == 2

    def test_no_now_playing_key_returns_empty_list(self):
        api = NavidromeAPI()
        with patch.object(
            api, "make_request", return_value={"subsonic-response": {}}
        ):
            result = asyncio.run(api.get_now_playing())
        assert result == []

    def test_missing_song_fields_default_to_na(self):
        response = {
            "subsonic-response": {
                "nowPlaying": {"entry": {"song": {}, "username": "robin"}}
            }
        }
        api = NavidromeAPI()
        with patch.object(api, "make_request", return_value=response):
            result = asyncio.run(api.get_now_playing())
        assert result[0]["song"]["title"] == "N/A"


class TestSearch:
    def test_extracts_search_result3_from_response(self):
        response = {
            "subsonic-response": {
                "searchResult3": {"song": [{"title": "Found Song"}]}
            }
        }
        api = NavidromeAPI()
        with patch.object(api, "make_request", return_value=response) as mock_mr:
            result = asyncio.run(api.search("test query"))

        assert result == {"song": [{"title": "Found Song"}]}
        _args, kwargs = mock_mr.call_args
        called_args = mock_mr.call_args[0]
        assert "search3" in called_args


class TestDependencyInjection:
    """
    ARCH-009 Phase 7: verifiziert die eigentliche DI-Faehigkeit von
    NavidromeAPI - unterschiedliche injizierte Configs ergeben
    unabhaengige, voneinander isolierte Instanzen.
    """

    def test_injected_config_is_used_for_auth_params(self):
        class FakeConfig:
            NAVIDROME_URL = "http://fake.example.test"
            NAVIDROME_USER = "fake-user"
            NAVIDROME_PASS = "fake-pass"

        api = NavidromeAPI(FakeConfig())

        assert api._auth_params["u"] == "fake-user"
        assert api._auth_params["p"] == "fake-pass"

    def test_two_instances_with_different_configs_are_independent(self):
        class FakeConfigA:
            NAVIDROME_URL = "http://a.example.test"
            NAVIDROME_USER = "user-a"
            NAVIDROME_PASS = "pass-a"

        class FakeConfigB:
            NAVIDROME_URL = "http://b.example.test"
            NAVIDROME_USER = "user-b"
            NAVIDROME_PASS = "pass-b"

        api_a = NavidromeAPI(FakeConfigA())
        api_b = NavidromeAPI(FakeConfigB())

        assert api_a._auth_params["u"] == "user-a"
        assert api_b._auth_params["u"] == "user-b"
        assert api_a._auth_params is not api_b._auth_params

    def test_no_args_construction_uses_real_global_config(self):
        """
        NavidromeAPI() ohne Argumente muss weiterhin die echte globale
        Config-Singleton-Instanz verwenden (Bestandsschutz - identisches
        Verhalten zur vorherigen Klassenattribut-Variante).
        """
        from config import get_config

        api = NavidromeAPI()
        real_config = get_config()

        assert api._auth_params["u"] == real_config.NAVIDROME_USER
        assert api._auth_params["p"] == real_config.NAVIDROME_PASS
