# tests/test_youtube_downloader_telegram_decoupling.py
# -*- coding: utf-8 -*-
"""
Characterization-/Regressionstests fuer services/downloader/downloader.py::
YoutubeDownloader (docs/audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md).

Vorher hielt YoutubeDownloader.__init__() das komplette Telegram-`Update`-
Objekt (self.update) und griff in download_audio() direkt auf
update.effective_chat.id/update.update_id zu - eine echte services/-Schicht
mit direkter Kenntnis eines Telegram-Typs, obwohl download_audio() selbst
nur zwei einfache Werte (chat_id, update_id) braucht. Die aufgerufene
Zielfunktion (enhanced_download_with_retry() in download_utils.py) sowie
das bereits bestehende DownloadCoordinator-Protocol (services/downloader/
download/interfaces.py) nehmen chat_id/update_id bereits als einfache
Werte entgegen - YoutubeDownloader war die einzige Ausnahme in dieser
Modulfamilie.

Fix: Konstruktor nimmt jetzt chat_id: int und update_id: int direkt
entgegen (wie enhanced_download_with_retry()/DownloadCoordinator), statt
das gesamte Update-Objekt zu halten. Keine Verhaltensaenderung - die an
enhanced_download_with_retry() uebergebenen Werte sind identisch.

Vorher 0 Tests fuer diese Klasse (repoweit verifiziert). Regel 7: externe
Abhaengigkeiten (EnhancedDownloadProcessor, FilenameFixerTool,
enhanced_download_with_retry) werden gemockt/gepatcht - dieses Modul testet
ausschliesslich YoutubeDownloader.__init__()/download_audio() selbst.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from services.downloader.downloader import YoutubeDownloader


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture
def deps():
    """Patcht alle externen Abhaengigkeiten von YoutubeDownloader."""
    with patch(
        "services.downloader.downloader.EnhancedDownloadProcessor"
    ) as mock_edp_cls, patch(
        "services.downloader.downloader.FilenameFixerTool"
    ) as mock_fft_cls, patch(
        "services.downloader.downloader.enhanced_download_with_retry",
        new_callable=AsyncMock,
    ) as mock_retry:
        yield {
            "edp_cls": mock_edp_cls,
            "fft_cls": mock_fft_cls,
            "retry": mock_retry,
        }


def make_downloader(deps, chat_id=111, update_id=222):
    return YoutubeDownloader(
        chat_id=chat_id,
        update_id=update_id,
        config=Mock(),
        cookie_handler=Mock(),
    )


class TestConstructorNoLongerNeedsTelegramUpdateObject:
    def test_construction_accepts_plain_chat_id_and_update_id(self, deps):
        """Kernbeweis der Entkopplung: der Konstruktor funktioniert mit
        einfachen int-Werten, ganz ohne ein Telegram-Update-Objekt."""
        downloader = make_downloader(deps, chat_id=555, update_id=999)

        assert downloader.chat_id == 555
        assert downloader.update_id == 999
        assert not hasattr(downloader, "update")


class TestDownloadAudioPassesChatIdAndUpdateIdToRetry:
    def test_chat_id_and_update_id_forwarded_unchanged(self, deps):
        deps["retry"].return_value = {
            "success": True,
            "type": "single",
            "track_info": {},
        }
        downloader = make_downloader(deps, chat_id=42, update_id=1337)

        run_async(downloader.download_audio("https://youtube.com/watch?v=x"))

        deps["retry"].assert_awaited_once()
        _, kwargs = deps["retry"].await_args
        assert kwargs["chat_id"] == 42
        assert kwargs["update_id"] == 1337
        assert kwargs["url"] == "https://youtube.com/watch?v=x"

    def test_status_callback_is_forwarded_unchanged(self, deps):
        """Playlist-Progress-State 2026-09-02 (Nutzer-Wunsch): optionales
        status_callback wird unveraendert an enhanced_download_with_retry()
        durchgereicht - bleibt in dieser Schicht ein opakes Callable ohne
        Telegram-Typ, exakt wie duplicate_detector."""
        deps["retry"].return_value = {
            "success": True,
            "type": "single",
            "track_info": {},
        }
        callback = Mock()
        downloader = YoutubeDownloader(
            chat_id=1,
            update_id=2,
            config=Mock(),
            cookie_handler=Mock(),
            status_callback=callback,
        )

        run_async(downloader.download_audio("https://youtube.com/watch?v=x"))

        _, kwargs = deps["retry"].await_args
        assert kwargs["status_callback"] is callback

    def test_status_callback_defaults_to_none(self, deps):
        deps["retry"].return_value = {
            "success": True,
            "type": "single",
            "track_info": {},
        }
        downloader = make_downloader(deps)

        run_async(downloader.download_audio("https://youtube.com/watch?v=x"))

        _, kwargs = deps["retry"].await_args
        assert kwargs["status_callback"] is None

    def test_active_download_is_forwarded_unchanged(self, deps):
        """Download-Control-Center 2026-09-02: optionales active_download
        (services.downloader.active_downloads.ActiveDownload) wird
        unveraendert an enhanced_download_with_retry() durchgereicht."""
        deps["retry"].return_value = {
            "success": True,
            "type": "single",
            "track_info": {},
        }
        active_download = Mock()
        downloader = YoutubeDownloader(
            chat_id=1,
            update_id=2,
            config=Mock(),
            cookie_handler=Mock(),
            active_download=active_download,
        )

        run_async(downloader.download_audio("https://youtube.com/watch?v=x"))

        _, kwargs = deps["retry"].await_args
        assert kwargs["active_download"] is active_download

    def test_active_download_defaults_to_none(self, deps):
        deps["retry"].return_value = {
            "success": True,
            "type": "single",
            "track_info": {},
        }
        downloader = make_downloader(deps)

        run_async(downloader.download_audio("https://youtube.com/watch?v=x"))

        _, kwargs = deps["retry"].await_args
        assert kwargs["active_download"] is None


class TestDownloadAudioCancelledFlag:
    def test_cancelled_flag_is_propagated_on_failure(self, deps):
        deps["retry"].return_value = {
            "success": False,
            "error": "Download abgebrochen",
            "cancelled": True,
        }
        downloader = make_downloader(deps)

        result = run_async(downloader.download_audio("https://youtube.com/watch?v=x"))

        assert result == {
            "success": False,
            "error": "Download abgebrochen",
            "cancelled": True,
        }

    def test_cancelled_flag_defaults_to_false_on_normal_failure(self, deps):
        deps["retry"].return_value = {"success": False, "error": "boom"}
        downloader = make_downloader(deps)

        result = run_async(downloader.download_audio("https://youtube.com/watch?v=x"))

        assert result["cancelled"] is False

    def test_cancelled_flag_is_false_on_normal_success(self, deps):
        deps["retry"].return_value = {
            "success": True,
            "type": "single",
            "track_info": {},
        }
        downloader = make_downloader(deps)

        result = run_async(downloader.download_audio("https://youtube.com/watch?v=x"))

        assert result["cancelled"] is False

    def test_cancelled_flag_is_true_on_partially_completed_playlist(self, deps):
        deps["retry"].return_value = {
            "success": True,
            "type": "playlist",
            "tracks": [{"success": True}],
            "cancelled": True,
        }
        downloader = make_downloader(deps)

        result = run_async(
            downloader.download_audio("https://youtube.com/playlist?list=x")
        )

        assert result["cancelled"] is True


class TestDownloadAudioSingleTrackResultTransformation:
    def test_success_single_track_maps_fields(self, deps):
        processor = Mock()
        processor.get_processing_statistics.return_value = {"total_processed": 1}
        deps["retry"].return_value = {
            "success": True,
            "type": "single",
            "processor_instance": processor,
            "track_info": {"artist": "A", "title": "T", "cover_embedded": True},
        }
        downloader = make_downloader(deps)

        result = run_async(downloader.download_audio("https://youtube.com/watch?v=x"))

        assert result["success"] is True
        assert result["type"] == "single"
        assert result["processing_stats"] == {"total_processed": 1}
        assert result["track_info"] == {
            "artist": "A",
            "title": "T",
            "cover_embedded": True,
        }
        assert result["artist"] == "A"
        assert result["cover_embedded"] is True

    def test_cover_embedded_falls_back_to_cover_found(self, deps):
        deps["retry"].return_value = {
            "success": True,
            "type": "single",
            "track_info": {"cover_found": True},
        }
        downloader = make_downloader(deps)

        result = run_async(downloader.download_audio("https://youtube.com/watch?v=x"))

        assert result["cover_embedded"] is True


class TestDownloadAudioPlaylistResultTransformation:
    def test_success_playlist_maps_tracks_and_title(self, deps):
        deps["retry"].return_value = {
            "success": True,
            "type": "playlist",
            "tracks": [{"success": True}, {"success": True}],
            "playlist_title": "My Playlist",
        }
        downloader = make_downloader(deps)

        result = run_async(downloader.download_audio("https://youtube.com/playlist?list=x"))

        assert result["success"] is True
        assert result["type"] == "playlist"
        assert result["tracks"] == [{"success": True}, {"success": True}]
        assert result["title"] == "My Playlist"

    def test_playlist_title_defaults_when_missing(self, deps):
        deps["retry"].return_value = {
            "success": True,
            "type": "playlist",
            "tracks": [],
        }
        downloader = make_downloader(deps)

        result = run_async(downloader.download_audio("https://youtube.com/playlist?list=x"))

        assert result["title"] == "Playlist"


class TestDownloadAudioFailureAndErrorPaths:
    def test_unsuccessful_result_returns_error_dict(self, deps):
        deps["retry"].return_value = {"success": False, "error": "boom"}
        downloader = make_downloader(deps)

        result = run_async(downloader.download_audio("https://youtube.com/watch?v=x"))

        assert result == {"success": False, "error": "boom", "cancelled": False}

    def test_empty_result_returns_clean_error_dict(self, deps):
        """
        Regressionstest (docs/FINDINGS_INDEX.md, urspruenglich
        docs/audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md, Abschnitt
        "Remaining"): `if not download_result or ...` faengt
        download_result=None zwar korrekt ab, der direkt folgende
        `download_result.get(...)`-Aufruf im selben Zweig tat es vorher
        NICHT - AttributeError statt eines sauberen
        {"success": False, ...}. Gefixt: ein sauberer Guard liefert jetzt
        ein Fehler-Dict statt zu crashen, auch wenn
        enhanced_download_with_retry() (laut eigenem Vertrag,
        docs/audits/DL_RETRY_CLASSIFICATION_2026-09-01.md) in der Praxis
        nie None liefert.

        Pre-Fix-Diskriminierung: diese Assertion (kein Crash, sauberes
        Dict) schlug am ungefixten Code nachweislich mit AttributeError
        fehl.
        """
        deps["retry"].return_value = None
        downloader = make_downloader(deps)

        result = run_async(downloader.download_audio("https://youtube.com/watch?v=x"))

        assert result == {
            "success": False,
            "error": "Unbekannter Fehler.",
            "cancelled": False,
        }

    def test_exception_from_retry_propagates(self, deps):
        deps["retry"].side_effect = RuntimeError("kaputt")
        downloader = make_downloader(deps)

        with pytest.raises(RuntimeError, match="kaputt"):
            run_async(downloader.download_audio("https://youtube.com/watch?v=x"))
