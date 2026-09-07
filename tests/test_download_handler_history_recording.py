"""
Download-Verlauf (docs/FINDINGS_INDEX.md, "Download-Verlauf/Erneut-
versuchen, persistenter Speicher"): Tests für die vier Hook-Punkte in
klassen/download_handler.py, die einen DownloadHistoryEntry schreiben -
handle_single_track_success() (Single-Erfolg), _register_playlist_track_duplicates()
(Playlist-Erfolg, ein Eintrag pro Track), handle_download_failure()
(Fehlschlag), _handle_download_cancelled() (Abbruch).

Nutzt eine REALE DownloadHistoryStore-Instanz (tmp_path) statt Mocks, um
tatsächlich persistierte Einträge statt nur Funktionsaufrufe zu prüfen -
analog zu tests/test_download_handler_playlist_duplicate_registration.py
(reale DuplicateDetector-Instanz aus demselben Grund). DownloadHandler hat
einen schweren Konstruktor - object.__new__() umgeht ihn bewusst
(etabliertes Muster dieser Session).
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from klassen.download_handler import DownloadHandler
from services.downloader.download_history import DownloadHistoryStore
from services.downloader.download_result_reporter import DownloadResultReporter


def run_async(coro):
    return asyncio.run(coro)


def make_handler(tmp_path, chat_id=999, with_history=True):
    handler = object.__new__(DownloadHandler)
    handler.logger = Mock()
    handler.duplicate_detector = Mock()
    handler.duplicate_detector.register_download = Mock()
    handler.duplicate_detector.get_statistics = Mock(return_value={})
    handler.result_reporter = DownloadResultReporter(logger=Mock())

    status_msg = Mock()
    status_msg.edit_text = AsyncMock()
    handler.status_msg = status_msg

    update = Mock()
    update.effective_chat = Mock()
    update.effective_chat.id = chat_id
    update.message = Mock()
    update.message.text = "https://youtu.be/RETRY_SOURCE"
    update.message.reply_text = AsyncMock(return_value=status_msg)
    handler.update = update

    if with_history:
        handler.download_history = DownloadHistoryStore(
            cache_dir=str(tmp_path / "download_history")
        )
    return handler


class TestSingleTrackSuccessRecordsHistoryEntry:
    def test_single_success_writes_success_entry(self, tmp_path):
        handler = make_handler(tmp_path)
        result = {
            "title": "Mein Song",
            "artist": "Mein Artist",
            "original_url": "https://youtu.be/ABC",
            "library_path": str(tmp_path / "library" / "song.m4a"),
        }

        run_async(handler.handle_single_track_success(result))

        entries = handler.download_history.get_recent(999)
        assert len(entries) == 1
        assert entries[0].title == "Mein Song"
        assert entries[0].artist == "Mein Artist"
        assert entries[0].url == "https://youtu.be/ABC"
        assert entries[0].status == "success"

    def test_playlist_wrapper_delegate_call_does_not_write_a_bogus_entry(
        self, tmp_path
    ):
        """handle_playlist_success() delegiert fuer den type=='playlist'-
        Fall an handle_single_track_success(playlist_result) - der Wrapper
        traegt kein echtes title/artist ("?"-Platzhalter). Ein Eintrag
        darf hier NICHT entstehen, die echten Pro-Track-Eintraege kommen
        aus _register_playlist_track_duplicates() (siehe Testklasse
        unten)."""
        handler = make_handler(tmp_path)
        playlist_wrapper = {"type": "playlist", "tracks": []}

        run_async(handler.handle_single_track_success(playlist_wrapper))

        assert handler.download_history.get_recent(999) == []

    def test_missing_history_store_does_not_raise(self, tmp_path):
        handler = make_handler(tmp_path, with_history=False)
        result = {"title": "T", "artist": "A", "url": "https://youtu.be/X"}

        # Darf nicht crashen, obwohl handler.download_history nie gesetzt
        # wurde (object.__new__()-Testkonstruktion, kein __init__()).
        run_async(handler.handle_single_track_success(result))


class TestPlaylistTrackSuccessRecordsHistoryEntry:
    def _track(self, title, artist, url, success=True, renamed=False):
        return {
            "success": success,
            "title": title,
            "artist": artist,
            "url": url,
            "library_path": None,
            "renamed_due_to_conflict": renamed,
        }

    def test_each_successful_track_gets_its_own_entry(self, tmp_path):
        handler = make_handler(tmp_path)
        tracks = [
            self._track("Track 1", "Artist 1", "https://youtu.be/1"),
            self._track("Track 2", "Artist 2", "https://youtu.be/2"),
        ]

        handler._register_playlist_track_duplicates(tracks)

        entries = handler.download_history.get_recent(999)
        assert len(entries) == 2
        assert {e.title for e in entries} == {"Track 1", "Track 2"}

    def test_failed_track_in_playlist_gets_no_entry(self, tmp_path):
        handler = make_handler(tmp_path)
        tracks = [
            self._track("Erfolgreich", "A", "https://youtu.be/1"),
            self._track("Gescheitert", "A", "https://youtu.be/2", success=False),
        ]

        handler._register_playlist_track_duplicates(tracks)

        entries = handler.download_history.get_recent(999)
        assert len(entries) == 1
        assert entries[0].title == "Erfolgreich"

    def test_renamed_due_to_conflict_track_gets_no_entry(self, tmp_path):
        """Deckt sich mit der bestehenden Duplikat-Registrierungs-Logik:
        eine kollidierte Kopie repraesentiert denselben Content wie ein
        bereits vorhandener Cache-Eintrag - kein neuer Verlaufseintrag."""
        handler = make_handler(tmp_path)
        tracks = [self._track("Kollidiert", "A", "https://youtu.be/1", renamed=True)]

        handler._register_playlist_track_duplicates(tracks)

        assert handler.download_history.get_recent(999) == []

    def test_placeholder_artist_track_gets_no_entry(self, tmp_path):
        """Deckt sich mit derselben Guard-Bedingung wie die Duplikat-
        Registrierung (artist in ('?', 'Unbekannt', 'Unknown Artist'))."""
        handler = make_handler(tmp_path)
        tracks = [self._track("Titel", "?", "https://youtu.be/1")]

        handler._register_playlist_track_duplicates(tracks)

        assert handler.download_history.get_recent(999) == []


class TestDownloadFailureRecordsHistoryEntry:
    def test_failure_writes_failed_entry_with_original_url(self, tmp_path):
        handler = make_handler(tmp_path)

        run_async(handler.handle_download_failure("Netzwerkfehler"))

        entries = handler.download_history.get_recent(999)
        assert len(entries) == 1
        assert entries[0].status == "failed"
        assert entries[0].url == "https://youtu.be/RETRY_SOURCE"
        assert entries[0].title == "Unbekannt"

    def test_missing_history_store_does_not_raise(self, tmp_path):
        handler = make_handler(tmp_path, with_history=False)

        run_async(handler.handle_download_failure("Fehler"))


class TestDownloadCancelledRecordsHistoryEntry:
    def test_cancelled_writes_cancelled_entry_with_original_url(self, tmp_path):
        handler = make_handler(tmp_path)

        run_async(handler._handle_download_cancelled())

        entries = handler.download_history.get_recent(999)
        assert len(entries) == 1
        assert entries[0].status == "cancelled"
        assert entries[0].url == "https://youtu.be/RETRY_SOURCE"

    def test_missing_history_store_does_not_raise(self, tmp_path):
        handler = make_handler(tmp_path, with_history=False)

        run_async(handler._handle_download_cancelled())


class TestMetadataChecklistPopulation:
    """Phase 3, P2.2 - die fuenf *_ok-Felder werden aus dem echten
    DownloadResult.to_dict()-Format (result/track-Dict) befuellt."""

    def test_single_success_populates_checklist_from_result_dict(self, tmp_path):
        handler = make_handler(tmp_path)
        result = {
            "title": "Mein Song", "artist": "Mein Artist",
            "original_url": "https://youtu.be/ABC",
            "genres": {"primary": "Pop"},
            "lyrics_available": True,
            "cover_embedded": False,
            "mb_ids_present": True,
            "loudness_normalized": False,
        }

        run_async(handler.handle_single_track_success(result))

        entry = handler.download_history.get_recent(999)[0]
        assert entry.genre_ok is True
        assert entry.lyrics_ok is True
        assert entry.cover_ok is False
        assert entry.mb_ok is True
        assert entry.loudness_ok is False

    def test_single_success_without_result_fields_is_false_not_none(self, tmp_path):
        """Ein reales DownloadResult.to_dict() setzt diese Felder immer
        (Default False/None-als-fehlend-Genre) - kein 'unbekannt' innerhalb
        eines erfolgreichen Laufs. Fehlen die Schluessel komplett (wie in
        diesem bewusst minimalen Test-Dict), ist das Ergebnis identisch zu
        einem echten expliziten False/None-Wert."""
        handler = make_handler(tmp_path)
        result = {"title": "T", "artist": "A", "url": "https://youtu.be/X"}

        run_async(handler.handle_single_track_success(result))

        entry = handler.download_history.get_recent(999)[0]
        assert entry.genre_ok is False
        assert entry.lyrics_ok is False
        assert entry.cover_ok is False
        assert entry.mb_ok is False
        assert entry.loudness_ok is False

    def test_playlist_track_success_populates_checklist(self, tmp_path):
        handler = make_handler(tmp_path)
        track = {
            "success": True, "title": "Track 1", "artist": "Artist 1",
            "url": "https://youtu.be/1", "library_path": None,
            "renamed_due_to_conflict": False,
            "genres": {"primary": "Hip-Hop"}, "lyrics_available": False,
            "cover_embedded": True, "mb_ids_present": False,
            "loudness_normalized": True,
        }

        handler._register_playlist_track_duplicates([track])

        entry = handler.download_history.get_recent(999)[0]
        assert entry.genre_ok is True
        assert entry.lyrics_ok is False
        assert entry.cover_ok is True
        assert entry.mb_ok is False
        assert entry.loudness_ok is True

    def test_cancelled_entry_has_all_five_fields_none(self, tmp_path):
        handler = make_handler(tmp_path)

        run_async(handler._handle_download_cancelled())

        entry = handler.download_history.get_recent(999)[0]
        assert entry.genre_ok is None
        assert entry.lyrics_ok is None
        assert entry.cover_ok is None
        assert entry.mb_ok is None
        assert entry.loudness_ok is None

    def test_failed_entry_has_all_five_fields_none(self, tmp_path):
        handler = make_handler(tmp_path)

        run_async(handler.handle_download_failure("Netzwerkfehler"))

        entry = handler.download_history.get_recent(999)[0]
        assert entry.genre_ok is None
        assert entry.lyrics_ok is None
        assert entry.cover_ok is None
        assert entry.mb_ok is None
        assert entry.loudness_ok is None


class TestHistoryWriteFailureDoesNotBreakDownloadFlow:
    def test_broken_history_store_logs_warning_but_does_not_raise(self, tmp_path):
        handler = make_handler(tmp_path)
        handler.download_history.add_entry = Mock(side_effect=RuntimeError("disk full"))
        result = {"title": "T", "artist": "A", "url": "https://youtu.be/X"}

        # Darf trotz kaputtem Verlaufsspeicher nicht crashen - derselbe
        # Grundsatz wie cleanup_single_download_artifact().
        run_async(handler.handle_single_track_success(result))

        handler.logger.warning.assert_called_once()
