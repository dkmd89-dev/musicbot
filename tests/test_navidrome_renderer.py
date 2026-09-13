# tests/test_navidrome_renderer.py
# -*- coding: utf-8 -*-
"""
Unit-Tests für handlers/navidrome_renderer.py.

Architecture Refactoring Audit, Migrationsstufe 1 (siehe
docs/audits/NAVIDROME_MENU_HANDLER_REFACTORING_MIGRATION_PLAN_2026-09-13.md):
1:1 aus handlers/navidrome_menu_handler.py extrahiert
(handle_album_detail()/handle_song_detail()/handle_playlist_detail()/
_format_track_duration()) - reine, zustandslose Funktionen, daher OHNE
jeglichen Mock testbar (kein NavidromeAPI, kein Telegram-Update, kein
asyncio.to_thread). Die vorher bestehenden Tests in
tests/test_navidrome_menu_handler.py (TestAlbumDetailNavF9/
TestSongDetailNavF9/TestPlaylistDetailNavF5/TestFormatTrackDuration
[verschoben]) bleiben als End-to-End-Regressionsschutz (Connection-Check
+ API-Aufruf + Error-Handling + Rendering über edit_message_text())
bestehen - diese Datei hier testet ausschließlich die reine
Rendering-Funktion isoliert.

Migrationsstufe 3: ergänzt um render_browse_artists()/
render_browse_albums()/render_browse_genres() - ebenfalls 1:1
extrahiert. Die vorher bestehenden Tests in
tests/test_navidrome_menu_handler.py (TestBrowseArtistsCharacterization/
TestBrowseAlbumsCharacterization/TestBrowseGenresCharacterization, aus
der Stufe-3-Vorbereitung) bleiben unverändert als End-to-End-
Regressionsschutz bestehen.
"""

from handlers.navidrome_renderer import (
    format_track_duration,
    render_album_detail,
    render_browse_albums,
    render_browse_artists,
    render_browse_genres,
    render_playlist_detail,
    render_song_detail,
)


class TestFormatTrackDuration:
    def test_formats_seconds_as_minutes_seconds(self):
        assert format_track_duration(187) == "3:07"
        assert format_track_duration(60) == "1:00"
        assert format_track_duration(0) == "0:00"

    def test_handles_missing_or_invalid_value(self):
        assert format_track_duration(None) == "0:00"
        assert format_track_duration("n/a") == "0:00"


class TestRenderAlbumDetail:
    def test_renders_text_and_tracklist_buttons(self):
        album = {
            "id": "a1",
            "name": "Test Album",
            "artist": "Test Artist",
            "artistId": "ar1",
            "songCount": 2,
            "duration": 245,
            "year": 2023,
            "song": [
                {"id": "s1", "title": "Track One", "track": 1},
                {"id": "s2", "title": "Track Two", "track": 2},
            ],
        }

        text, markup = render_album_detail(album)

        assert "Test Artist" in text
        assert "2023" in text
        buttons = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert "nav_song_s1" in buttons
        assert "nav_song_s2" in buttons
        assert "nav_artist_ar1" in buttons
        assert "menu:navidrome" in buttons

    def test_special_chars_are_escaped(self):
        album = {
            "id": "a1",
            "name": "Greatest Hits (Deluxe)!",
            "artist": "Artist & Friends",
            "song": [],
        }

        text, _markup = render_album_detail(album)

        assert "(Deluxe)!" not in text
        assert "\\(Deluxe\\)\\!" in text

    def test_tracklist_capped_at_25_songs(self):
        album = {
            "id": "a1", "name": "Big Album", "artist": "X",
            "song": [{"id": f"s{i}", "title": f"Track {i}"} for i in range(30)],
        }

        text, markup = render_album_detail(album)

        song_buttons = [
            b for row in markup.inline_keyboard for b in row
            if b.callback_data.startswith("nav_song_")
        ]
        assert len(song_buttons) == 25
        assert "+5 weitere Songs nicht angezeigt" in text

    def test_no_artist_id_omits_artist_button(self):
        album = {"id": "a1", "name": "Album", "artist": "X", "song": []}

        _text, markup = render_album_detail(album)

        buttons = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert not any(cb.startswith("nav_artist_") for cb in buttons)


class TestRenderSongDetail:
    def test_renders_text_and_navigation_buttons(self):
        song = {
            "id": "s1", "title": "Some Song", "artist": "Artist X",
            "artistId": "ar1", "album": "Album Y", "albumId": "al1",
            "track": 5, "year": 2022, "genre": "Pop", "duration": 187,
        }

        text, markup = render_song_detail(song)

        assert "Artist X" in text
        assert "Album Y" in text
        assert "3\\:07" in text  # 187s -> 3:07
        buttons = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert "nav_artist_ar1" in buttons
        assert "nav_album_al1" in buttons
        assert "menu:navidrome" in buttons

    def test_special_chars_are_escaped(self):
        song = {"id": "s1", "title": "Song (Live) - Remix!", "artist": "A"}

        text, _markup = render_song_detail(song)

        assert "(Live) - Remix!" not in text
        assert "\\(Live\\) \\- Remix\\!" in text

    def test_optional_fields_omitted_when_absent(self):
        song = {"id": "s1", "title": "Minimal Song", "artist": "A"}

        text, markup = render_song_detail(song)

        assert "Album:" not in text
        assert "Track:" not in text
        assert "Jahr:" not in text
        assert "Genre:" not in text
        buttons = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert not any(
            cb.startswith("nav_artist_") or cb.startswith("nav_album_")
            for cb in buttons
        )


class TestRenderPlaylistDetail:
    def test_renders_text_and_tracklist_buttons(self):
        playlist = {
            "id": "pl1", "name": "Test Playlist", "owner": "robin",
            "songCount": 2, "duration": 245,
            "entry": [
                {"id": "s1", "title": "Track One", "track": 1},
                {"id": "s2", "title": "Track Two", "track": 2},
            ],
        }

        text, markup = render_playlist_detail(playlist)

        assert "robin" in text
        buttons = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert "nav_song_s1" in buttons
        assert "nav_song_s2" in buttons
        assert "menu:navidrome" in buttons

    def test_special_chars_are_escaped(self):
        playlist = {"id": "pl1", "name": "Party (Deluxe)!", "owner": "", "entry": []}

        text, _markup = render_playlist_detail(playlist)

        assert "(Deluxe)!" not in text
        assert "\\(Deluxe\\)\\!" in text

    def test_tracklist_capped_at_25_songs(self):
        playlist = {
            "id": "pl1", "name": "Big Playlist", "owner": "",
            "entry": [{"id": f"s{i}", "title": f"Track {i}"} for i in range(30)],
        }

        text, markup = render_playlist_detail(playlist)

        song_buttons = [
            b for row in markup.inline_keyboard for b in row
            if b.callback_data.startswith("nav_song_")
        ]
        assert len(song_buttons) == 25
        assert "+5 weitere Songs nicht angezeigt" in text

    def test_no_owner_omits_ersteller_line(self):
        playlist = {"id": "pl1", "name": "No Owner Playlist", "owner": "", "entry": []}

        text, _markup = render_playlist_detail(playlist)

        assert "Ersteller" not in text


class TestRenderBrowseArtists:
    def test_renders_first_page_without_previous_button(self):
        artists = [{"id": "1", "name": "Artist A"}, {"id": "2", "name": "Artist B"}]

        text, markup = render_browse_artists(artists, page=0)

        assert "Seite 1" in text
        buttons = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert "nav_artist_1" in buttons
        assert "nav_artist_2" in buttons
        assert not any(cb.startswith("nav_browse_artists_") for cb in buttons)

    def test_middle_page_shows_both_navigation_buttons(self):
        artists = [{"id": str(i), "name": f"Artist {i}"} for i in range(45)]

        _text, markup = render_browse_artists(artists, page=1)

        buttons = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert "nav_browse_artists_0" in buttons
        assert "nav_browse_artists_2" in buttons

    def test_name_and_id_fall_back_to_alternate_fields(self):
        artists = [{"title": "Fallback Name", "artistId": "fb1"}]

        _text, markup = render_browse_artists(artists, page=0)

        buttons = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert "nav_artist_fb1" in buttons


class TestRenderBrowseAlbums:
    def test_renders_albums_with_all_albums_title(self):
        albums = [{"id": "al1", "name": "Album One", "artist": "X"}]

        text, markup = render_browse_albums(
            albums, "💿 Alle Alben", page=0, artist_id=None, page_size=15
        )

        assert "Alle Alben" in text
        buttons = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert "nav_album_al1" in buttons
        assert "nav_browse_artists" not in buttons

    def test_with_artist_id_shows_kuenstler_button_and_suffixed_pagination(self):
        albums = [{"id": f"al{i}", "name": f"Album {i}"} for i in range(15)]

        text, markup = render_browse_albums(
            albums, "🎤 Alben des Künstlers", page=0, artist_id="ar1", page_size=15
        )

        assert "Alben des Künstlers" in text
        buttons = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert "nav_browse_artists" in buttons
        assert "nav_browse_albums_1_ar1" in buttons

    def test_previous_button_includes_artist_id_suffix(self):
        albums = [{"id": "al1", "name": "Album One"}]

        _text, markup = render_browse_albums(
            albums, "🎤 Alben des Künstlers", page=1, artist_id="ar1", page_size=15
        )

        buttons = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert "nav_browse_albums_0_ar1" in buttons

    def test_full_page_without_artist_id_shows_unsuffixed_next_button(self):
        albums = [{"id": f"al{i}", "name": f"Album {i}"} for i in range(15)]

        _text, markup = render_browse_albums(
            albums, "💿 Alle Alben", page=0, artist_id=None, page_size=15
        )

        buttons = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert "nav_browse_albums_1" in buttons


class TestRenderBrowseGenres:
    def test_sorted_descending_by_song_count(self):
        genres = [
            {"value": "Pop", "songCount": 5},
            {"value": "Hip-Hop", "songCount": 50},
        ]

        text, markup = render_browse_genres(genres)

        buttons_in_order = [
            b.text for row in markup.inline_keyboard for b in row
            if b.callback_data.startswith("nav_genre_")
            and b.callback_data != "nav_genre_stats"
        ]
        assert buttons_in_order == ["🎭 Hip-Hop (50)", "🎭 Pop (5)"]
        assert "2 Genres verfügbar" in text

    def test_non_numeric_song_count_normalized_to_zero_no_crash(self):
        """NAV-F14-Regressionsschutz auf Renderer-Ebene."""
        genres = [
            {"value": "Zeta", "songCount": "n/a"},
            {"value": "Alpha", "songCount": "n/a"},
            {"value": "Real Genre", "songCount": 5},
        ]

        text, markup = render_browse_genres(genres)

        buttons_in_order = [
            b.text for row in markup.inline_keyboard for b in row
            if b.callback_data.startswith("nav_genre_")
            and b.callback_data != "nav_genre_stats"
        ]
        assert buttons_in_order == ["🎭 Real Genre (5)", "🎭 Alpha", "🎭 Zeta"]
        assert text  # kein Crash

    def test_max_20_genres_shown(self):
        genres = [{"value": f"Genre{i}", "songCount": i} for i in range(30)]

        _text, markup = render_browse_genres(genres)

        genre_buttons = [
            b for row in markup.inline_keyboard for b in row
            if b.callback_data.startswith("nav_genre_")
            and b.callback_data != "nav_genre_stats"
        ]
        assert len(genre_buttons) == 20

    def test_zero_song_count_omits_parens(self):
        genres = [{"value": "Obscure", "songCount": 0}]

        _text, markup = render_browse_genres(genres)

        buttons = {b.text for row in markup.inline_keyboard for b in row}
        assert "🎭 Obscure" in buttons
