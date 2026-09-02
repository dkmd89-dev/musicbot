"""
Unit-Tests für DownloadResultReporter
(services/downloader/download_result_reporter.py).

Im Zuge von ARCH-001 aus klassen/download_handler.py extrahiert
(_build_duplicate_message/_extract_genres_from_data/_collect_playlist_genres/
_extract_stats_from_result/_send_final_summary/Teil von handle_playlist_success
-> eigene Klasse, 1:1 gleicher Code, siehe
docs/archive/arch/MusicBot_ARCH-001_Orchestrators.md). Bewusst NICHT mit extrahiert:
Duplikat-Cache-Registrierung (handle_single_track_success) und die
Playlist-Wrapper-Delegation (handle_playlist_success) - beides bleibt
Aufgabe von DownloadHandler, da es echte Seiteneffekte/Kontrollfluss-
Entscheidungen sind, keine reine Formatierung/Versand.

Diese Tests decken den extrahierten Code jetzt isoliert ab, statt nur
indirekt über DownloadHandler (der bislang keine dedizierte Testdatei hat).

ARCH-007/P-2 (2026-08-24): send_playlist_direct_summary()/send_final_summary()
wurden zu build_playlist_summary_message()/build_final_summary_message()
- geben nur noch Text zurueck statt selbst zu senden (services/ hat keine
Telegram-Abhaengigkeit mehr). Der tatsaechliche Versand (inkl.
status_msg/update-Fallback und TelegramError-Behandlung) liegt jetzt in
klassen/download_handler.py::_send_report_message() - die entsprechenden
Versand-/Fallback-/Fehlerbehandlungs-Tests wurden dorthin verschoben
(siehe tests/test_download_handler_send_report_message.py).
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from services.downloader.download_result_reporter import (
    DownloadResultReporter,
    _example_track_and_short_dir,
    _format_duration,
)
from services.downloader.models import DuplicateEntry


@pytest.fixture
def reporter():
    return DownloadResultReporter(logger=Mock())


class TestExtractGenresFromData:
    def test_dict_with_primary_and_secondary(self, reporter):
        result = reporter.extract_genres_from_data(
            {"primary": "Hip Hop", "secondary": ["Rap", "Trap"]}
        )
        assert result == ["Hip Hop", "Rap", "Trap"]

    def test_dict_with_only_primary(self, reporter):
        assert reporter.extract_genres_from_data({"primary": "Techno"}) == ["Techno"]

    def test_list_of_strings(self, reporter):
        assert reporter.extract_genres_from_data(["Rock", "Pop"]) == ["Rock", "Pop"]

    def test_list_of_dicts_extracts_primary(self, reporter):
        result = reporter.extract_genres_from_data(
            [{"primary": "Rock"}, {"primary": "Metal"}]
        )
        assert result == ["Rock", "Metal"]

    def test_plain_string(self, reporter):
        assert reporter.extract_genres_from_data("Jazz") == ["Jazz"]

    def test_none_returns_empty_list(self, reporter):
        assert reporter.extract_genres_from_data(None) == []

    def test_duplicates_are_removed_preserving_order(self, reporter):
        result = reporter.extract_genres_from_data(
            {"primary": "Hip Hop", "secondary": ["Hip Hop", "Rap"]}
        )
        assert result == ["Hip Hop", "Rap"]


class TestCollectPlaylistGenres:
    def test_sorted_by_frequency(self, reporter):
        tracks = [
            {"genres": {"primary": "Hip Hop"}},
            {"genres": {"primary": "Hip Hop"}},
            {"genres": {"primary": "Pop"}},
        ]
        assert reporter.collect_playlist_genres(tracks) == ["Hip Hop", "Pop"]

    def test_capped_at_four(self, reporter):
        tracks = [
            {"genres": "Genre1"},
            {"genres": "Genre2"},
            {"genres": "Genre3"},
            {"genres": "Genre4"},
            {"genres": "Genre5"},
        ]
        assert len(reporter.collect_playlist_genres(tracks)) == 4

    def test_empty_tracks_returns_empty_list(self, reporter):
        assert reporter.collect_playlist_genres([]) == []


class TestExtractStatsFromResult:
    def test_prefers_explicit_processing_stats_when_non_empty(self, reporter):
        result = {"processing_stats": {"total_processed": 5}}
        assert reporter.extract_stats_from_result(result, []) == {"total_processed": 5}

    def test_ignores_all_zero_explicit_stats_and_falls_through(self, reporter):
        result = {"processing_stats": {"total_processed": 0, "cache_hits": 0}}
        tracks = [{"artist_source": "youtube_parsed"}]
        stats = reporter.extract_stats_from_result(result, tracks)
        assert stats["total_processed"] == 1

    def test_falls_back_to_processor_instance_statistics(self, reporter):
        proc = Mock()
        proc.enhanced_metadata_processor = None
        proc.get_processing_statistics.return_value = {"total_processed": 3}
        proc.session_stats = {}
        result = {"processor_instance": proc}
        stats = reporter.extract_stats_from_result(result, [])
        assert stats["total_processed"] == 3

    def test_falls_back_to_track_aggregation(self, reporter):
        tracks = [
            {"artist_source": "youtube_parsed", "from_cache": True, "lyrics_available": True},
            {"artist_source": "unknown", "from_cache": False},
        ]
        stats = reporter.extract_stats_from_result({}, tracks)
        assert stats["total_processed"] == 2
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1
        assert stats["youtube_parser_used"] == 1
        assert stats["lyrics_found"] == 1

    def test_no_tracks_and_no_stats_returns_empty_dict(self, reporter):
        assert reporter.extract_stats_from_result({}, []) == {}


class TestBuildDuplicateMessage:
    def _entry(self, **overrides):
        defaults = dict(
            artist="Some Artist",
            title="Some Title",
            url="https://youtube.com/watch?v=abc",
            file_path=Path("/library/Some Artist/Some Title.mp3"),
            download_date=datetime(2026, 1, 15, 12, 30),
        )
        defaults.update(overrides)
        return DuplicateEntry(**defaults)

    def test_url_type_uses_url_label(self, reporter):
        msg = reporter.build_duplicate_message(self._entry(), "url")
        assert "🔗 URL-Treffer" in msg
        assert "Some Title" in msg
        assert "Some Artist" in msg
        assert "15.01.2026 12:30" in msg

    def test_file_conflict_type_uses_conflict_label(self, reporter):
        msg = reporter.build_duplicate_message(self._entry(), "file_conflict")
        assert "📄 Datei-Konflikt" in msg
        assert "🕒 Konflikt erkannt:" in msg

    def test_unknown_type_falls_back_to_generic_label(self, reporter):
        msg = reporter.build_duplicate_message(self._entry(), "totally_unknown")
        assert "🔍 Unbekannt" in msg

    def test_conflict_suffix_is_stripped_from_path(self, reporter):
        entry = self._entry(file_path=Path("/library/Artist/Title (1).mp3"))
        msg = reporter.build_duplicate_message(entry, "file_conflict")
        assert "Title.mp3" in msg
        assert "Title (1).mp3" not in msg


class TestBuildPlaylistSummaryMessage:
    def test_contains_core_fields(self, reporter):
        results = [{"success": True, "artist": "A", "album": "B", "year": 2024, "library_path": "/lib/A/x.mp3"}]

        sent_text = reporter.build_playlist_summary_message(results, results)

        assert "Künstler : A" in sent_text
        assert "Album    : B" in sent_text

    def test_filename_and_storage_location_use_inline_code_not_quotes(self, reporter):
        """Nutzer-Wunsch 2026-09-02: Dateiname/Speicherort als Inline-Code
        (Backticks) statt in Anführungszeichen - wirkt in Telegram sauberer."""
        results = [
            {
                "success": True,
                "artist": "A",
                "album": "B",
                "year": 2024,
                "library_path": "/lib/A/2024 - B/01 - x.mp3",
            }
        ]

        sent_text = reporter.build_playlist_summary_message(results, results)

        assert "`01 - x.mp3`" in sent_text
        assert "`A/2024 - B`" in sent_text
        assert '"01 - x.mp3"' not in sent_text


class TestBuildFinalSummaryMessageCancelled:
    """Download-Control-Center 2026-09-02: ein per ❌-Button abgebrochener
    Playlist-Download hat weiterhin result["success"] == True (die vor dem
    Abbruch fertig heruntergeladenen Tracks sind echte Erfolge) - Header
    und Tracks-Zeile machen die Teil-Fertigstellung trotzdem sichtbar."""

    def test_cancelled_playlist_shows_abort_header(self, reporter):
        result = {
            "type": "playlist",
            "tracks": [
                {"success": True, "artist": "A", "album": "B", "library_path": "/lib/A/1.mp3"},
                {"success": True, "artist": "A", "album": "B", "library_path": "/lib/A/2.mp3"},
            ],
            "source": "youtube",
            "cancelled": True,
        }

        sent_text = reporter.build_final_summary_message(result, {}, {})

        assert "🛑 Download abgebrochen" in sent_text
        assert "🎉 Download erfolgreich abgeschlossen!" not in sent_text
        assert "Tracks   : 2/2 abgebrochen bei" in sent_text

    def test_cancelled_mid_track_shows_last_successful_track_not_na(self, reporter):
        """
        Live-Fund 2026-09-02 (echter Abbruch-Test): der LETZTE Eintrag in
        tracks ist bei einem waehrend Track 2 abgebrochenen Download der
        abgebrochene Track selbst (kein library_path, siehe
        DownloadResult(success=False, error="Download abgebrochen", ...)
        in _process_playlist_download()) - "Beispiel-Track"/"Speicherort"
        zeigten dadurch faelschlich "N/A", obwohl Track 1 bereits
        erfolgreich fertig war.
        """
        result = {
            "type": "playlist",
            "tracks": [
                {
                    "success": True,
                    "artist": "01099",
                    "album": "orange",
                    "library_path": "/lib/01099/2025 - orange/01 - so heiß.m4a",
                },
                {
                    "success": False,
                    "title": "Track 2",
                    "error": "Download abgebrochen",
                    # kein library_path - wie im echten Abbruch-Fall
                },
            ],
            "source": "youtube",
            "cancelled": True,
        }

        sent_text = reporter.build_final_summary_message(result, {}, {})

        assert "`01 - so heiß.m4a`" in sent_text
        assert "`01099/2025 - orange`" in sent_text
        assert "`N/A`" not in sent_text  # Beispiel-Track/Speicherort betroffen

    def test_non_cancelled_playlist_keeps_success_header(self, reporter):
        result = {
            "type": "playlist",
            "tracks": [
                {"success": True, "artist": "A", "album": "B", "library_path": "/lib/A/1.mp3"},
            ],
            "source": "youtube",
            "cancelled": False,
        }

        sent_text = reporter.build_final_summary_message(result, {}, {})

        assert "🎉 Download erfolgreich abgeschlossen!" in sent_text
        assert "🛑 Download abgebrochen" not in sent_text
        assert "Tracks   : 1/1 erfolgreich" in sent_text


class TestBuildFinalSummaryMessage:
    def test_single_track_message_contains_core_fields(self, reporter):
        result = {
            "title": "Some Title",
            "artist": "Some Artist",
            "album": "Some Album",
            "year": 2024,
            "library_path": "/library/Some Artist/Some Title.mp3",
            "source": "youtube",
        }

        sent_text = reporter.build_final_summary_message(result, {}, {})

        assert "🎉 Download erfolgreich abgeschlossen!" in sent_text
        assert "Some Title" in sent_text
        assert "Some Artist" in sent_text
        assert "📺 YouTube" in sent_text
        assert "`Some Title.mp3`" in sent_text

    def test_playlist_type_uses_playlist_header_and_track_counts(self, reporter):
        result = {
            "type": "playlist",
            "tracks": [
                {"success": True, "artist": "A", "album": "B", "library_path": "/lib/A/1.mp3"},
                {"success": True, "artist": "A", "album": "B", "library_path": "/lib/A/2.mp3"},
                {"success": False},
            ],
            "source": "youtube",
        }

        sent_text = reporter.build_final_summary_message(result, {}, {})

        assert "🎉 Download erfolgreich abgeschlossen!" in sent_text
        assert "Tracks   : 2/3 erfolgreich" in sent_text

    def test_loudness_and_lyrics_stats_come_from_current_tracks_not_shared_processor_stats(
        self, reporter
    ):
        """Nutzer-Redesign 2026-09-02: processing_stats (der geteilte,
        nie zurueckgesetzte EnhancedMetadataProcessor-Zaehler) darf die
        "Lyrics gefunden"/"Loudness normalisiert"-Zeilen nicht beeinflussen
        - nur die tatsaechlichen Tracks DIESES Downloads zaehlen."""
        result = {
            "type": "playlist",
            "tracks": [
                {
                    "success": True,
                    "artist": "A",
                    "album": "B",
                    "library_path": "/lib/A/1.mp3",
                    "lyrics_available": True,
                    "loudness_normalized": True,
                },
                {
                    "success": True,
                    "artist": "A",
                    "album": "B",
                    "library_path": "/lib/A/2.mp3",
                    "lyrics_available": False,
                    "loudness_normalized": True,
                },
            ],
            "source": "youtube",
        }
        # Absichtlich stark veraltete/irrefuehrende Werte - duerfen NICHT
        # in der Meldung landen.
        stale_processing_stats = {"lyrics_found": 999, "total_processed": 999}

        sent_text = reporter.build_final_summary_message(
            result, stale_processing_stats, {}
        )

        assert "📜 Lyrics   : ✅ verfügbar (1/2 · 50%)" in sent_text
        assert "🔊 Loudness : ✅ normalisiert (2/2 · 100%)" in sent_text
        assert "999" not in sent_text

    def test_missing_library_path_shows_na_without_crash(self, reporter):
        result = {"title": "T", "artist": "A", "source": "youtube"}

        sent_text = reporter.build_final_summary_message(result, {}, {})

        assert "N/A" in sent_text
        reporter.logger.warning.assert_called_once()

    def test_duration_line_uses_duration_seconds_from_result(self, reporter):
        """Nutzer-Wunsch 2026-09-02: neue "⏱️ Dauer"-Zeile, gespeist aus
        duration_seconds (jetzt durch enhanced_download_with_retry() ->
        YoutubeDownloader.download_audio() durchgereicht)."""
        result = {
            "title": "T",
            "artist": "A",
            "library_path": "/library/A/Singles/T.m4a",
            "source": "youtube",
            "duration_seconds": 94,
        }

        sent_text = reporter.build_final_summary_message(result, {}, {})

        assert "⏱️ Dauer    : 1:34 min" in sent_text

    def test_duration_line_shows_na_when_missing(self, reporter):
        result = {"title": "T", "artist": "A", "library_path": "/library/A/Singles/T.m4a", "source": "youtube"}

        sent_text = reporter.build_final_summary_message(result, {}, {})

        assert "⏱️ Dauer    : N/A" in sent_text

    def test_storage_location_shows_only_artist_album_not_full_path(self, reporter):
        """Nutzer-Wunsch 2026-09-02: "Speicherort" zeigt nur noch
        Artist/Album statt des vollen Dateisystempfads."""
        result = {
            "type": "playlist",
            "tracks": [
                {
                    "success": True,
                    "artist": "Zartmann",
                    "album": "schönhauser EP",
                    "library_path": "/tmp/musicbot_test/library/Zartmann/2025 - schönhauser EP/08 - Track.m4a",
                }
            ],
            "source": "youtube",
        }

        sent_text = reporter.build_final_summary_message(result, {}, {})

        assert "`Zartmann/2025 - schönhauser EP`" in sent_text
        assert "/tmp/musicbot_test" not in sent_text

    def test_single_track_lyrics_and_loudness_omit_redundant_count(self, reporter):
        """Nutzer-Wunsch 2026-09-02: bei einem Einzeltitel (n=1) ist
        "(1/1 · 100%)" hinter Lyrics/Loudness reine Redundanz zum bereits
        gezeigten ✅/❌-Status - nur bei Playlists bleibt der Zaehler/die
        Prozentangabe sinnvoll und wird gezeigt (siehe
        test_loudness_and_lyrics_stats_come_from_current_tracks_not_shared_processor_stats)."""
        result = {
            "title": "T",
            "artist": "A",
            "library_path": "/library/A/Singles/T.m4a",
            "source": "youtube",
            "lyrics_available": True,
            "loudness_normalized": True,
        }

        sent_text = reporter.build_final_summary_message(result, {}, {})

        assert "📜 Lyrics   : ✅ verfügbar" in sent_text
        assert "🔊 Loudness : ✅ normalisiert" in sent_text
        assert "1/1" not in sent_text
        assert "100%" not in sent_text


class TestFormatDuration:
    def test_formats_minutes_and_seconds(self):
        assert _format_duration(94) == "1:34 min"

    def test_formats_under_a_minute(self):
        assert _format_duration(7) == "0:07 min"

    def test_none_returns_na(self):
        assert _format_duration(None) == "N/A"

    def test_rounds_to_nearest_second(self):
        assert _format_duration(59.6) == "1:00 min"


class TestExampleTrackAndShortDir:
    def test_extracts_filename_and_artist_album(self):
        fname, short_dir = _example_track_and_short_dir(
            "/tmp/musicbot_test/library/Zartmann/2025 - schönhauser EP/08 - Track.m4a"
        )
        assert fname == "08 - Track.m4a"
        assert short_dir == "Zartmann/2025 - schönhauser EP"

    def test_works_for_singles_structure(self):
        fname, short_dir = _example_track_and_short_dir(
            "/mnt/musik_bilder/library/Clueso/Singles/2017 - Achterbahn.m4a"
        )
        assert fname == "2017 - Achterbahn.m4a"
        assert short_dir == "Clueso/Singles"

    def test_none_returns_na_tuple(self):
        assert _example_track_and_short_dir(None) == ("N/A", "N/A")
