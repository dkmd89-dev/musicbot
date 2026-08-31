"""
DUP-06 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md):

Sowohl services/downloader/download_utils.py::enhanced_download_with_retry()
als auch klassen/download_handler.py::_probe_artist_title_for_duplicate_check()
behandelten ein yt-dlp-Ergebnis mit "entries" als Playlist - fuer eine
automatisch generierte YouTube-Mix-/Radio-Liste (list=RD...) liefert yt-dlp
GENAUSO ein entries-tragendes Ergebnis wie fuer eine echte Playlist
(list=PL...), da beide ueber denselben Playlist-faehigen Extractor
(YoutubeTabIE) laufen, solange noplaylist nicht gesetzt ist (verifiziert
gegen den installierten yt-dlp-Quellcode, Version 2026.08.19:
extractor/youtube/_base.py::_PLAYLIST_ID_RE fuehrt "RD" als eigenes Praefix,
extractor/common.py::_yes_playlist() liest den noplaylist-Parameter).

Fix: eine gemeinsame Erkennungsfunktion
services.downloader.download_utils.is_youtube_mix_url() prueft den
list-Query-Parameter der URL auf das Praefix "RD" (case-sensitiv, wie
yt-dlps eigene Konvention) und wird an BEIDEN o.g. Stellen vor dem
jeweiligen extract_info_async()-Aufruf genutzt, um additiv
ydl_opts["noplaylist"] = True zu setzen. Die bestehende entries-basierte
Playlist-/Single-Verzweigung selbst bleibt an beiden Stellen unveraendert -
fuer list=RD...-URLs entsteht durch noplaylist=True schlicht kein entries
mehr. Echte Playlists (list=PL...) sind vom Praefix-Check ausgeschlossen
und bleiben unveraendert.

Nutzt fuer enhanced_download_with_retry() dasselbe deps-Fixture-Muster wie
tests/test_download_utils_retry.py (Regel 7: EnhancedDownloadProcessor ist
ein echter SingletonMixin, ein Klassen-Mock verhindert versehentliche
Beruehrung einer gecachten Instanz). Fuer
_probe_artist_title_for_duplicate_check() dasselbe
object.__new__(DownloadHandler)-Muster wie
tests/test_download_handler_playlist_duplicate_registration.py.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from klassen.download_handler import DownloadHandler
from services.downloader.download_utils import (
    enhanced_download_with_retry,
    is_youtube_mix_url,
)


def run_async(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# Teil 1: enhanced_download_with_retry() - tatsaechlich uebergebene ydl_opts
# ═══════════════════════════════════════════════════════════════════════════


def make_mock_processor():
    processor = Mock()
    processor.config = Mock()
    processor.filename_fixer = Mock()
    processor.download_executor = Mock()
    processor.download_executor.build_ydl_opts = Mock(
        return_value={"format": "bestaudio[ext=m4a]/bestaudio/best", "outtmpl": "x"}
    )
    processor.download_executor.extract_info_async = AsyncMock()
    return processor


@pytest.fixture
def deps():
    """Patcht alle externen Abhaengigkeiten von enhanced_download_with_retry()
    (identisches Muster wie tests/test_download_utils_retry.py)."""
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
    ):
        mock_processor_cls.return_value = processor
        yield {"processor": processor, "playlist": mock_playlist, "single": mock_single}


def _called_ydl_opts(deps):
    """Extrahiert die tatsaechlich an extract_info_async() uebergebenen
    ydl_opts aus dem Mock-Call - nicht die isolierte Helper-Funktion."""
    call = deps["processor"].download_executor.extract_info_async.call_args
    return call.args[1]


class TestEnhancedDownloadWithRetrySetsNoplaylistForMixUrls:
    def test_1_rdmm_sets_noplaylist_true(self, deps):
        deps["processor"].download_executor.extract_info_async.return_value = {
            "id": "v1", "title": "T", "uploader": "U", "duration": 10,
        }
        deps["single"].return_value = {"artist": "A", "title": "T"}

        run_async(enhanced_download_with_retry(
            url="https://www.youtube.com/watch?v=ABC&list=RDMM",
            chat_id=1, update_id=1,
        ))

        assert _called_ydl_opts(deps).get("noplaylist") is True

    def test_2_rd_with_long_id_sets_noplaylist_true(self, deps):
        deps["processor"].download_executor.extract_info_async.return_value = {
            "id": "v1", "title": "T", "uploader": "U", "duration": 10,
        }
        deps["single"].return_value = {"artist": "A", "title": "T"}

        run_async(enhanced_download_with_retry(
            url="https://www.youtube.com/watch?v=ABC&list=RD123456789",
            chat_id=1, update_id=1,
        ))

        assert _called_ydl_opts(deps).get("noplaylist") is True

    def test_3_rd_with_additional_query_params_sets_noplaylist_true(self, deps):
        deps["processor"].download_executor.extract_info_async.return_value = {
            "id": "v1", "title": "T", "uploader": "U", "duration": 10,
        }
        deps["single"].return_value = {"artist": "A", "title": "T"}

        run_async(enhanced_download_with_retry(
            url="https://www.youtube.com/watch?v=ABC&list=RD123456789&index=3&t=42s",
            chat_id=1, update_id=1,
        ))

        assert _called_ydl_opts(deps).get("noplaylist") is True

    def test_4_reordered_query_params_still_sets_noplaylist_true(self, deps):
        deps["processor"].download_executor.extract_info_async.return_value = {
            "id": "v1", "title": "T", "uploader": "U", "duration": 10,
        }
        deps["single"].return_value = {"artist": "A", "title": "T"}

        run_async(enhanced_download_with_retry(
            url="https://www.youtube.com/watch?list=RDMM&v=ABC",
            chat_id=1, update_id=1,
        ))

        assert _called_ydl_opts(deps).get("noplaylist") is True

    def test_5_real_playlist_does_not_set_noplaylist(self, deps):
        deps["processor"].download_executor.extract_info_async.return_value = {
            "id": "pl1", "title": "PL", "uploader": "U", "entries": [{}],
        }
        deps["playlist"].return_value = [{"success": True}]

        run_async(enhanced_download_with_retry(
            url="https://www.youtube.com/watch?v=ABC&list=PL123456789",
            chat_id=1, update_id=1,
        ))

        assert "noplaylist" not in _called_ydl_opts(deps)

    def test_6_normal_video_without_list_does_not_set_noplaylist(self, deps):
        deps["processor"].download_executor.extract_info_async.return_value = {
            "id": "v1", "title": "T", "uploader": "U", "duration": 10,
        }
        deps["single"].return_value = {"artist": "A", "title": "T"}

        run_async(enhanced_download_with_retry(
            url="https://www.youtube.com/watch?v=ABC",
            chat_id=1, update_id=1,
        ))

        assert "noplaylist" not in _called_ydl_opts(deps)

    def test_7_existing_ydl_opts_are_preserved(self, deps):
        deps["processor"].download_executor.extract_info_async.return_value = {
            "id": "v1", "title": "T", "uploader": "U", "duration": 10,
        }
        deps["single"].return_value = {"artist": "A", "title": "T"}

        run_async(enhanced_download_with_retry(
            url="https://www.youtube.com/watch?v=ABC&list=RDMM",
            chat_id=1, update_id=1,
        ))

        called = _called_ydl_opts(deps)
        assert called.get("format") == "bestaudio[ext=m4a]/bestaudio/best"
        assert called.get("outtmpl") == "x"
        assert called.get("noplaylist") is True

    def test_9_existing_entries_based_playlist_processing_is_unaffected(self, deps):
        """Regressionsschutz: eine echte Playlist muss weiterhin ueber
        _process_playlist_download() laufen - die bestehende entries-
        Verzweigung selbst wurde nicht veraendert."""
        deps["processor"].download_executor.extract_info_async.return_value = {
            "id": "pl1", "title": "PL", "uploader": "U", "entries": [{}, {}],
        }
        deps["playlist"].return_value = [{"success": True}, {"success": True}]

        result = run_async(enhanced_download_with_retry(
            url="https://www.youtube.com/watch?v=ABC&list=PL123456789",
            chat_id=1, update_id=1,
        ))

        deps["playlist"].assert_awaited()
        deps["single"].assert_not_awaited()
        assert result["type"] == "playlist"


# ═══════════════════════════════════════════════════════════════════════════
# Teil 2: _probe_artist_title_for_duplicate_check() - tatsaechlich
# uebergebene ydl_opts
# ═══════════════════════════════════════════════════════════════════════════


def make_probe_handler():
    handler = object.__new__(DownloadHandler)
    handler.logger = Mock()
    handler.config = Mock()
    handler.downloader = Mock()
    executor = Mock()
    executor.build_ydl_opts = Mock(return_value={"format": "bestaudio"})
    executor.extract_info_async = AsyncMock(
        return_value={"id": "v1", "title": "T", "uploader": "U"}
    )
    handler.downloader.enhanced_download_processor = Mock()
    handler.downloader.enhanced_download_processor.download_executor = executor
    return handler, executor


class TestProbeSetsNoplaylistForMixUrls:
    def test_8_probe_sets_noplaylist_true_for_mix_url(self):
        handler, executor = make_probe_handler()

        run_async(handler._probe_artist_title_for_duplicate_check(
            "https://www.youtube.com/watch?v=ABC&list=RDMM"
        ))

        called_ydl_opts = executor.extract_info_async.call_args.args[1]
        assert called_ydl_opts.get("noplaylist") is True

    def test_probe_does_not_set_noplaylist_for_real_playlist(self):
        handler, executor = make_probe_handler()

        run_async(handler._probe_artist_title_for_duplicate_check(
            "https://www.youtube.com/watch?v=ABC&list=PL123456789"
        ))

        called_ydl_opts = executor.extract_info_async.call_args.args[1]
        assert "noplaylist" not in called_ydl_opts

    def test_probe_does_not_set_noplaylist_for_normal_video(self):
        handler, executor = make_probe_handler()

        run_async(handler._probe_artist_title_for_duplicate_check(
            "https://www.youtube.com/watch?v=ABC"
        ))

        called_ydl_opts = executor.extract_info_async.call_args.args[1]
        assert "noplaylist" not in called_ydl_opts


# ═══════════════════════════════════════════════════════════════════════════
# Teil 3: beide Produktionsstellen nutzen denselben Erkennungsmechanismus
# ═══════════════════════════════════════════════════════════════════════════


class TestBothProductionSitesShareTheSameDetectionMechanism:
    def test_download_handler_imports_the_same_function_object(self):
        """Stellt sicher, dass klassen/download_handler.py die Funktion aus
        services/downloader/download_utils.py importiert statt eine eigene,
        potenziell abweichende Regex-/Parsing-Logik zu implementieren."""
        import klassen.download_handler as dh_module

        assert dh_module.is_youtube_mix_url is is_youtube_mix_url


# ═══════════════════════════════════════════════════════════════════════════
# Teil 4: Helper-Funktion direkt (Edge Cases aus der Analyse)
# ═══════════════════════════════════════════════════════════════════════════


class TestIsYoutubeMixUrlHelperEdgeCases:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.youtube.com/watch?v=ABC&list=RDMM", True),
            ("https://www.youtube.com/watch?v=ABC&list=RD123456789", True),
            ("https://www.youtube.com/watch?v=ABC&list=PL123456789", False),
            ("https://www.youtube.com/watch?v=ABC", False),
            ("https://www.youtube.com/watch?list=RDMM&v=ABC", True),
            ("https://www.youtube.com/watch?v=ABC&list=rdmm", False),
        ],
    )
    def test_edge_cases(self, url, expected):
        assert is_youtube_mix_url(url) is expected
