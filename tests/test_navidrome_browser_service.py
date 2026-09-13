# tests/test_navidrome_browser_service.py
# -*- coding: utf-8 -*-
"""
Unit-Tests für services/navidrome/browser_service.py.

Architecture Refactoring Audit, Migrationsstufe 4 (siehe
docs/audits/NAVIDROME_MENU_HANDLER_REFACTORING_MIGRATION_PLAN_2026-09-13.md):
1:1 aus handlers/navidrome_menu_handler.py::handle_browse_albums()
extrahiert. `navidrome_api` wird als Mock injiziert (Regel 7 - externe
Services in Unit-Tests mocken), `get_albums_page()` selbst ist reine
Orchestrierung ohne eigenen State - direkt testbar ohne Telegram-Update/
NavidromeMenuHandler.

Die vorher bestehenden Tests in tests/test_navidrome_menu_handler.py
(TestBrowseAlbumsCharacterization, aus der Stufe-3-Vorbereitung)
bleiben als End-to-End-Regressionsschutz (Connection-Check + Service-
Aufruf + Error-Handling + Rendering über edit_message_text()) bestehen
- diese Datei hier testet ausschließlich die Service-Funktion isoliert.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

from services.navidrome.browser_service import get_albums_page


def _make_api(response):
    api = Mock()
    api.make_request = Mock(return_value=response)
    return api


class TestGetAlbumsPageWithoutArtistId:
    def test_uses_album_list2_endpoint_with_offset_and_size(self):
        api = _make_api(
            {
                "subsonic-response": {
                    "albumList2": {
                        "album": [{"id": "al1", "name": "Album One"}]
                    }
                }
            }
        )

        albums, title_prefix = asyncio.run(
            get_albums_page(api, page=2, artist_id=None, page_size=15)
        )

        assert albums == [{"id": "al1", "name": "Album One"}]
        assert title_prefix == "💿 Alle Alben"
        args, _kwargs = api.make_request.call_args
        assert args[0] == "getAlbumList2"
        assert args[1] == {
            "type": "alphabeticalByArtist", "size": 15, "offset": 30,
        }

    def test_missing_album_list_returns_empty(self):
        api = _make_api({"subsonic-response": {}})

        albums, _title_prefix = asyncio.run(
            get_albums_page(api, page=0, artist_id=None, page_size=15)
        )

        assert albums == []


class TestGetAlbumsPageWithArtistId:
    def test_uses_get_artist_endpoint_and_paginates_locally(self):
        api = _make_api(
            {
                "subsonic-response": {
                    "artist": {
                        "album": [
                            {"id": f"al{i}", "name": f"Album {i}"} for i in range(20)
                        ]
                    }
                }
            }
        )

        albums, title_prefix = asyncio.run(
            get_albums_page(api, page=1, artist_id="ar1", page_size=15)
        )

        assert title_prefix == "🎤 Alben des Künstlers"
        assert len(albums) == 5  # Rest der 20 Alben ab Index 15
        assert albums[0]["id"] == "al15"
        args, _kwargs = api.make_request.call_args
        assert args[0] == "getArtist"
        assert args[1] == {"id": "ar1"}

    def test_missing_artist_returns_empty(self):
        api = _make_api({"subsonic-response": {}})

        albums, _title_prefix = asyncio.run(
            get_albums_page(api, page=0, artist_id="ar1", page_size=15)
        )

        assert albums == []

    def test_page_beyond_available_albums_returns_empty(self):
        api = _make_api(
            {
                "subsonic-response": {
                    "artist": {"album": [{"id": "al1", "name": "Album One"}]}
                }
            }
        )

        albums, _title_prefix = asyncio.run(
            get_albums_page(api, page=5, artist_id="ar1", page_size=15)
        )

        assert albums == []
