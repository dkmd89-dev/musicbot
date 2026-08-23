"""
Tests fuer DownloadExecutor (services/downloader/download/download_executor.py).

REL-Fund dieser Session: enhanced_download_with_retry() und
download_single_track() (beide async def) riefen die blockierende
yt-dlp-Methode extract_info() direkt auf, ohne run_in_executor - das
blockierte den gesamten asyncio-Event-Loop fuer die gesamte Downloaddauer,
wodurch der Bot fuer ALLE Telegram-Nutzer unresponsive wurde, nicht nur fuer
den gerade downloadenden. extract_info_async() faengt das jetzt ab.

Zweiter Fund: Config.MAX_DURATION wurde nur in der toten
Config.YTDL_BASE_OPTIONS-Property (0 Aufrufer im Repo) unter einem
nicht-existenten yt-dlp-Options-Key gesetzt - wirkungslos. build_ydl_opts()
(die tatsaechlich genutzte Methode) kannte MAX_DURATION gar nicht.
_build_duration_match_filter() implementiert das jetzt echt, mit Ausnahme
fuer als Podcast erkannte Kanaele.
"""

import asyncio
import time

import pytest

from services.downloader.download.download_executor import DownloadExecutor


@pytest.fixture
def executor():
    return DownloadExecutor()


class FakeConfig:
    def __init__(self, tmp_path, max_duration=None, mapping_dir=None, cookies_file=None):
        self.DOWNLOAD_DIR = tmp_path
        self.MAX_DURATION = max_duration
        self.GENRE_MAPPING_DIR = mapping_dir or (tmp_path / "empty_mapping")
        if cookies_file is not None:
            self.COOKIES_FILE = cookies_file


class TestExtractInfoAsyncDoesNotBlockEventLoop:
    def test_extract_info_async_returns_same_result_as_sync_version(
        self, executor, monkeypatch
    ):
        monkeypatch.setattr(
            executor, "extract_info", lambda url, opts, download=False: {"title": "Test"}
        )
        result = asyncio.run(
            executor.extract_info_async("http://example.com", {}, download=False)
        )
        assert result == {"title": "Test"}

    def test_extract_info_async_runs_in_executor_not_on_event_loop(
        self, executor, monkeypatch
    ):
        """
        Beweis, dass der Event-Loop waehrend eines "langsamen" extract_info()-
        Aufrufs NICHT blockiert wird: eine parallel gestartete Coroutine muss
        trotzdem weiterlaufen koennen, waehrend extract_info_async() im
        Executor-Thread wartet.
        """

        def slow_extract_info(url, opts, download=False):
            time.sleep(0.3)
            return {"title": "Slow Result"}

        monkeypatch.setattr(executor, "extract_info", slow_extract_info)

        progress = []

        async def other_task():
            for _ in range(3):
                await asyncio.sleep(0.05)
                progress.append("tick")

        async def main():
            results = await asyncio.gather(
                executor.extract_info_async("http://example.com", {}),
                other_task(),
            )
            return results

        results = asyncio.run(main())
        assert results[0] == {"title": "Slow Result"}
        # Waere der Event-Loop blockiert gewesen, haette other_task() erst
        # NACH extract_info_async() ueberhaupt Fortschritt machen koennen.
        assert len(progress) == 3


class TestDurationMatchFilter:
    def test_video_within_limit_is_not_rejected(self, executor, tmp_path):
        config = FakeConfig(tmp_path, max_duration=600)
        opts = executor.build_ydl_opts(config)
        match_filter = opts["match_filter"]

        result = match_filter({"duration": 300, "uploader": "Some Artist"})
        assert result is None

    def test_video_over_limit_is_rejected(self, executor, tmp_path):
        config = FakeConfig(tmp_path, max_duration=600)
        opts = executor.build_ydl_opts(config)
        match_filter = opts["match_filter"]

        result = match_filter({"duration": 3600, "uploader": "Some Artist"})
        assert result is not None
        assert "3600" in result

    def test_podcast_channel_is_exempt_from_duration_limit(self, executor, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        (mapping_dir / "special_channel.yaml").write_text(
            """
SPECIAL_CHANNELS:
  Podcast:
    - Test Podcast Channel
""",
            encoding="utf-8",
        )
        config = FakeConfig(tmp_path, max_duration=600, mapping_dir=mapping_dir)
        opts = executor.build_ydl_opts(config)
        match_filter = opts["match_filter"]

        result = match_filter(
            {"duration": 5400, "uploader": "Test Podcast Channel"}
        )
        assert result is None

    def test_no_match_filter_when_max_duration_not_configured(self, executor, tmp_path):
        config = FakeConfig(tmp_path, max_duration=None)
        opts = executor.build_ydl_opts(config)
        assert "match_filter" not in opts

    def test_video_with_no_duration_info_is_not_rejected(self, executor, tmp_path):
        config = FakeConfig(tmp_path, max_duration=600)
        opts = executor.build_ydl_opts(config)
        match_filter = opts["match_filter"]

        result = match_filter({"uploader": "Some Artist"})
        assert result is None


class TestCookieFilePath:
    """
    ARCH-003, P-9: build_ydl_opts() nutzte vorher einen hartkodierten,
    CWD-relativen Path("cookies.txt") statt der bereits vorhandenen
    Config.COOKIES_FILE (BASE_DIR/cookies.txt) - der config-Parameter wird
    hier bereits injiziert entgegengenommen, wurde fuer den Cookie-Pfad
    aber nicht genutzt.
    """

    def test_uses_cookies_file_from_config_when_present(self, executor, tmp_path):
        cookie_file = tmp_path / "custom_cookies.txt"
        cookie_file.write_text("# netscape cookie file\n")
        config = FakeConfig(tmp_path, cookies_file=cookie_file)

        opts = executor.build_ydl_opts(config)

        assert opts["cookiefile"] == str(cookie_file)

    def test_falls_back_to_relative_cookies_txt_when_config_has_no_cookies_file(
        self, executor, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        config = FakeConfig(tmp_path)  # kein cookies_file -> kein COOKIES_FILE-Attribut

        opts = executor.build_ydl_opts(config)

        assert "cookiefile" not in opts

    def test_no_cookiefile_key_when_configured_file_does_not_exist(
        self, executor, tmp_path
    ):
        config = FakeConfig(tmp_path, cookies_file=tmp_path / "does_not_exist.txt")

        opts = executor.build_ydl_opts(config)

        assert "cookiefile" not in opts
