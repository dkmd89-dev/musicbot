"""
Regressionstests fuer FINDING-4 (docs/MusicBot_FINDING_4_FORENSIC_AUDIT.md)
— klassen/download_handler.py::handle_youtube_links()/handle_playlist_success().

Vor diesem Fix gab es 0 direkte Tests fuer beide Methoden. Der Forensic
Audit wies zwei Symptome derselben Grundursache nach: handle_youtube_links()
wertete an der entscheidenden Stelle nur ein Top-Level-success-Flag aus,
das fuer Playlist-Ergebnisse strukturell immer True ist (unabhaengig vom
tatsaechlichen Track-Erfolg) und fuer erschoepfte Single-Track-Retries zwar
akkurat False ist, aber nie in eine Telegram-Fehlermeldung uebersetzt wurde.

DownloadHandler hat einen schweren Konstruktor - object.__new__() umgeht
ihn bewusst (etabliertes Muster dieser Session, siehe
test_download_handler_process_single_download_result.py/
test_download_handler_send_report_message.py). Tests pruefen beobachtbares
Verhalten (die tatsaechlich an Telegram gesendete/editierte Nachricht),
nicht Implementierungsdetails.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from klassen.download_handler import DownloadHandler
from services.downloader.download_result_reporter import DownloadResultReporter


def run_async(coro):
    return asyncio.run(coro)


def make_status_msg():
    msg = Mock()
    msg.edit_text = AsyncMock()
    return msg


def make_handler(download_audio_result):
    """DownloadHandler-Instanz mit allen fuer handle_youtube_links()
    benoetigten Attributen, aber ohne echten Konstruktor-Aufruf."""
    handler = object.__new__(DownloadHandler)
    handler.logger = Mock()

    status_msg = make_status_msg()

    handler.update = Mock()
    handler.update.message = Mock()
    handler.update.message.text = "https://youtube.com/watch?v=abc123"
    handler.update.message.reply_text = AsyncMock(return_value=status_msg)
    handler.update.effective_chat = Mock(id=12345)
    handler.update.update_id = 1

    handler.duplicate_detector = Mock()
    handler.duplicate_detector.check_for_duplicates = Mock(
        return_value=(False, None, "none")
    )
    handler.duplicate_detector.register_download = Mock()
    handler.duplicate_detector.get_statistics = Mock(return_value={})

    handler.downloader = Mock()
    handler.downloader.download_audio = AsyncMock(return_value=download_audio_result)

    handler.result_reporter = DownloadResultReporter(logger=Mock())

    return handler, status_msg


class TestSingleTrackRetryExhaustionIsReported:
    def test_failed_download_result_triggers_failure_message(self):
        """
        FINDING-4 Variante A: enhanced_download_with_retry() erschoepft alle
        Versuche und liefert {"success": False, "error": "..."} als
        Rueckgabewert (keine Exception) - der Nutzer muss trotzdem eine
        Fehlermeldung erhalten, statt dass die Statusnachricht stumm bei
        "6/6 Zusammenfassung" stehen bleibt.
        """
        handler, status_msg = make_handler(
            {"success": False, "error": "Download nach 3 Versuchen fehlgeschlagen: Video nicht verfügbar"}
        )

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        # Beobachtbares Verhalten: die zuletzt an Telegram gesendete
        # Nachricht muss den tatsaechlichen Fehlergrund enthalten.
        assert status_msg.edit_text.await_count >= 1
        final_text = status_msg.edit_text.await_args.args[0]
        assert "Video nicht verfügbar" in final_text
        assert "fehlgeschlagen" in final_text.lower()

    def test_failed_download_result_without_error_field_still_reports_failure(self):
        """Fallback-Text greift, falls 'error' im Ergebnis fehlt."""
        handler, status_msg = make_handler({"success": False})

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        final_text = status_msg.edit_text.await_args.args[0]
        assert "fehlgeschlagen" in final_text.lower()


class TestPlaylistAllTracksFailedIsReported:
    def _playlist_result(self, track_successes):
        tracks = [{"success": ok, "title": f"Track {i}"} for i, ok in enumerate(track_successes, 1)]
        return {
            "success": True,
            "type": "playlist",
            "tracks": tracks,
            "processing_stats": {},
            "title": "Playlist",
        }

    def test_zero_of_n_successful_tracks_does_not_report_success(self):
        """
        FINDING-4 Variante B: enhanced_download_with_retry() meldet fuer
        Playlists immer success=True auf oberster Ebene, unabhaengig vom
        tatsaechlichen Track-Ergebnis. Bei 0/3 erfolgreichen Tracks darf
        NICHT "erfolgreich" im finalen Text stehen.
        """
        handler, status_msg = make_handler(
            self._playlist_result([False, False, False])
        )

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        final_text = status_msg.edit_text.await_args.args[0]
        assert "erfolgreich" not in final_text.lower()
        assert "fehlgeschlagen" in final_text.lower()

    def test_partial_success_still_reports_success_header(self):
        """
        Regressionsschutz: die bewusst akzeptierte Partial-Success-Semantik
        (mindestens 1 erfolgreicher Track) darf durch den FINDING-4-Fix
        NICHT veraendert werden - deckt sich mit dem bestehenden
        test_playlist_type_uses_playlist_header_and_track_counts in
        tests/test_download_result_reporter.py.
        """
        handler, status_msg = make_handler(
            self._playlist_result([True, True, False])
        )

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        final_text = status_msg.edit_text.await_args.args[0]
        assert "erfolgreich" in final_text.lower()

    def test_full_success_still_reports_success_header(self):
        handler, status_msg = make_handler(self._playlist_result([True, True, True]))

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        final_text = status_msg.edit_text.await_args.args[0]
        assert "erfolgreich" in final_text.lower()
