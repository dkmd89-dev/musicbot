"""
Characterization-Tests fuer die Retry-Schleife in
enhanced_download_with_retry() (services/downloader/download_utils.py:224).

Vorher 0 dedizierte Tests fuer diese Schleife (siehe
docs/archive/MusicBot_ENGINEERING_BASELINE_v2.md, Abschnitt 14, RETRY-COVERAGE).
Dieses Modul dokumentiert das TATSAECHLICHE aktuelle Verhalten, es aendert
nichts daran.

Regel 7 (externe Abhaengigkeiten mocken): EnhancedDownloadProcessor ist ein
echter SingletonMixin (utils/singleton.py) - ein Klassen-Mock verhindert,
dass Tests versehentlich eine aus einem frueheren Testlauf gecachte Instanz
mit echten Pfaden/Config beruehren. _process_playlist_download() und
_process_single_download() werden ebenfalls gemockt, da sie bereits eigene
Tests haben (tests/test_download_utils_metadata_translation.py) - dieses
Modul testet ausschliesslich die Retry-/Backoff-/Fehlerbehandlungs-Logik der
umschliessenden Schleife selbst. asyncio.sleep wird gemockt, um die
exponentielle Backoff-Wartezeit nicht real abzuwarten und um die
tatsaechlich verwendeten Wartezeiten zu verifizieren.

Dokumentierte Eigenheiten des aktuellen Verhaltens (bewusst NICHT gefixt,
nur charakterisiert):
  - Die Fehlermeldungsformate unterscheiden sich zwischen dem DownloadError-
    Zweig ("Download nach N Versuchen fehlgeschlagen: ...") und dem
    generischen Exception-Zweig ("Unerwarteter Fehler: ..." - ohne
    Versuchsanzahl).
  - Der finale Return nach der for-Schleife ("Maximale Versuche (N)
    erreicht...") ist fuer max_retries >= 1 unerreichbarer Code, da beide
    except-Zweige beim letzten Versuch bereits zurueckkehren. Er ist nur bei
    max_retries=0 erreichbar (dann ohne jeden Download-Versuch).
  - Retry umfasst den GESAMTEN try-Block, nicht nur extract_info_async() -
    auch Exceptions aus _process_playlist_download()/_process_single_download()
    loesen einen erneuten Versuch aus.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, call, patch

import pytest

from services.downloader.download_utils import enhanced_download_with_retry
from services.downloader.errors import DownloadError


def run_async(coro):
    return asyncio.run(coro)


def make_mock_processor():
    processor = Mock()
    processor.config = Mock()
    processor.filename_fixer = Mock()
    processor.download_executor = Mock()
    processor.download_executor.build_ydl_opts = Mock(return_value={})
    processor.download_executor.extract_info_async = AsyncMock()
    return processor


@pytest.fixture
def deps():
    """Patcht alle externen Abhaengigkeiten von enhanced_download_with_retry()."""
    processor = make_mock_processor()
    with patch("services.downloader.download_utils.Config"), patch(
        "services.downloader.download_utils.EnhancedDownloadProcessor"
    ) as mock_processor_cls, patch(
        "services.downloader.download_utils._process_playlist_download",
        new_callable=AsyncMock,
    ) as mock_playlist, patch(
        "services.downloader.download_utils._process_single_download",
        new_callable=AsyncMock,
    ) as mock_single, patch(
        "asyncio.sleep", new_callable=AsyncMock
    ) as mock_sleep:
        mock_processor_cls.return_value = processor
        yield {
            "processor": processor,
            "playlist": mock_playlist,
            "single": mock_single,
            "sleep": mock_sleep,
        }


class TestSuccessOnFirstAttempt:
    def test_single_track_success(self, deps):
        deps["processor"].download_executor.extract_info_async.return_value = {
            "id": "v1",
            "title": "T",
            "uploader": "U",
            "duration": 180,
        }
        deps["single"].return_value = {"artist": "A", "title": "T"}

        result = run_async(
            enhanced_download_with_retry(
                url="https://youtube.com/watch?v=v1", chat_id=1, update_id=1
            )
        )

        assert result["success"] is True
        assert result["type"] == "single"
        assert result["track_info"] == {"artist": "A", "title": "T"}
        deps["processor"].download_executor.extract_info_async.assert_awaited_once()
        deps["sleep"].assert_not_awaited()

    def test_playlist_success_counts_successful_tracks(self, deps):
        deps["processor"].download_executor.extract_info_async.return_value = {
            "id": "pl1",
            "title": "PL",
            "uploader": "U",
            "entries": [{}, {}, {}],
        }
        deps["playlist"].return_value = [
            {"success": True},
            {"success": True},
            {"success": False},
        ]

        result = run_async(
            enhanced_download_with_retry(
                url="https://youtube.com/playlist?list=pl1", chat_id=1, update_id=1
            )
        )

        assert result["success"] is True
        assert result["type"] == "playlist"
        assert result["total_tracks"] == 3
        assert result["successful_tracks"] == 2
        deps["sleep"].assert_not_awaited()

    def test_empty_entries_list_is_treated_as_single_not_playlist(self, deps):
        """Dokumentiertes Verhalten: info.get('entries') == [] ist falsy,
        die Verzweigung faellt auf den Single-Pfad zurueck."""
        deps["processor"].download_executor.extract_info_async.return_value = {
            "id": "v1",
            "entries": [],
        }
        deps["single"].return_value = {"artist": "A", "title": "T"}

        result = run_async(
            enhanced_download_with_retry(
                url="https://youtube.com/watch?v=v1", chat_id=1, update_id=1
            )
        )

        assert result["type"] == "single"
        deps["playlist"].assert_not_awaited()


class TestRetryAndBackoff:
    def test_no_info_returned_raises_download_error_and_retries(self, deps):
        deps["processor"].download_executor.extract_info_async.side_effect = [
            None,
            {"id": "v1", "title": "T"},
        ]
        deps["single"].return_value = {"artist": "A", "title": "T"}

        result = run_async(
            enhanced_download_with_retry(
                url="https://youtube.com/watch?v=v1", chat_id=1, update_id=1
            )
        )

        assert result["success"] is True
        assert deps["processor"].download_executor.extract_info_async.await_count == 2
        deps["sleep"].assert_awaited_once_with(1)  # 2**0

    def test_exception_from_playlist_processing_also_triggers_retry(self, deps):
        """Der Retry-Schutz umfasst die gesamte Pipeline, nicht nur
        extract_info_async()."""
        deps["processor"].download_executor.extract_info_async.return_value = {
            "id": "pl1",
            "entries": [{}],
        }
        deps["playlist"].side_effect = [
            RuntimeError("playlist boom"),
            [{"success": True}],
        ]

        result = run_async(
            enhanced_download_with_retry(
                url="https://youtube.com/playlist?list=pl1", chat_id=1, update_id=1
            )
        )

        assert result["success"] is True
        assert deps["playlist"].await_count == 2
        deps["sleep"].assert_awaited_once_with(1)

    def test_backoff_uses_exponential_seconds_2_pow_attempt(self, deps):
        deps["processor"].download_executor.extract_info_async.side_effect = (
            DownloadError("boom")
        )

        result = run_async(
            enhanced_download_with_retry(
                url="https://youtube.com/watch?v=v1",
                chat_id=1,
                update_id=1,
                max_retries=4,
            )
        )

        assert result["success"] is False
        deps["sleep"].assert_has_awaits([call(1), call(2), call(4)])

    def test_download_error_exhausts_all_retries_with_attempt_count_in_message(
        self, deps
    ):
        deps["processor"].download_executor.extract_info_async.side_effect = (
            DownloadError("yt-dlp kaputt")
        )

        result = run_async(
            enhanced_download_with_retry(
                url="https://youtube.com/watch?v=v1",
                chat_id=1,
                update_id=1,
                max_retries=3,
            )
        )

        assert result["success"] is False
        # DownloadError.__str__() formatiert als "Download-Fehler [CODE]: details"
        # (services/downloader/errors.py) - das landet unveraendert in last_error.
        assert result["error"] == (
            "Download nach 3 Versuchen fehlgeschlagen: "
            "Download-Fehler [GENERIC]: yt-dlp kaputt"
        )
        assert deps["processor"].download_executor.extract_info_async.await_count == 3
        assert deps["sleep"].await_count == 2  # nach Versuch 1 und 2, nicht nach 3

    def test_generic_exception_exhausts_retries_with_different_message_format(
        self, deps
    ):
        """Dokumentierte Inkonsistenz: der generische Exception-Zweig nennt
        im Gegensatz zum DownloadError-Zweig die Versuchsanzahl NICHT in der
        Fehlermeldung."""
        deps["processor"].download_executor.extract_info_async.side_effect = (
            RuntimeError("unerwartet kaputt")
        )

        result = run_async(
            enhanced_download_with_retry(
                url="https://youtube.com/watch?v=v1",
                chat_id=1,
                update_id=1,
                max_retries=2,
            )
        )

        assert result["success"] is False
        assert result["error"] == "Unerwarteter Fehler: unerwartet kaputt"
        assert "Versuchen" not in result["error"]

    def test_default_max_retries_is_three(self, deps):
        deps["processor"].download_executor.extract_info_async.side_effect = (
            DownloadError("boom")
        )

        result = run_async(
            enhanced_download_with_retry(
                url="https://youtube.com/watch?v=v1", chat_id=1, update_id=1
            )
        )

        assert result["success"] is False
        assert deps["processor"].download_executor.extract_info_async.await_count == 3


class TestMaxRetriesEdgeCase:
    def test_max_retries_zero_returns_immediately_without_any_attempt(self, deps):
        """Dokumentiertes Verhalten: range(0) durchlaeuft die Schleife nie,
        der finale Return nach der Schleife greift sofort - ohne dass
        extract_info_async() je aufgerufen wird."""
        result = run_async(
            enhanced_download_with_retry(
                url="https://youtube.com/watch?v=v1",
                chat_id=1,
                update_id=1,
                max_retries=0,
            )
        )

        assert result["success"] is False
        assert result["error"] == "Maximale Versuche (0) erreicht. Letzter Fehler: None"
        deps["processor"].download_executor.extract_info_async.assert_not_awaited()
        deps["sleep"].assert_not_awaited()
