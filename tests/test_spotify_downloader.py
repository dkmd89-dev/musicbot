"""
Characterization-Tests fuer services/downloader/spotify_downloader.py
(SpotifyDownloader) - 914 Zeilen, vorher 0 Tests.

Regel 7: externe Netzwerkaufrufe (Spotify Embed-/oEmbed-API, yt-dlp,
RSS-Feeds) werden komplett gemockt.

BUG-004 (docs/MusicBot_ENGINEERING_BASELINE.md): _download_via_ytdlp_safe()
ermittelte die heruntergeladene Datei bisher ueber "neueste Datei im
gesamten download_dir" (glob + mtime-Sortierung). Dieses Verzeichnis ist
identisch mit Config.DOWNLOAD_DIR, das AUCH von der regulaeren
YouTube-Download-Pipeline genutzt wird (Config.SPOTIFY_DOWNLOAD_DIR
existiert in config.py, wurde aber nie angebunden - komplett unbenutzt).
Bei mehreren gleichzeitigen Downloads (MAX_CONCURRENT_DOWNLOADS erlaubt
das explizit seit REL-005) konnte die Datei eines PARALLEL laufenden,
fremden Downloads faelschlicherweise als "die eigene" erkannt werden -
falscher Audio-Inhalt unter falschen Metadaten. Fix: liest jetzt den von
yt-dlp tatsaechlich gemeldeten, nach Postprocessing korrigierten Pfad aus
download_info["filepath"] (live gegen den echten yt-dlp-Quellcode
verifiziert: FFmpegExtractAudioPP.run() aktualisiert "filepath" auf den
finalen, konvertierten Pfad).
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.downloader.spotify_downloader import (
    SpotifyDownloader,
    _extract_spotify_id,
    _is_spotify_url,
    _sanitize_spotify_url,
    _spotify_url_type,
)


class TestIsSpotifyUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://open.spotify.com/track/1a2b3c4d5e",
            "https://spotify.link/abc123",
            "https://spoti.fi/xyz",
            "OPEN.SPOTIFY.COM/track/abc",
        ],
    )
    def test_recognizes_spotify_urls(self, url):
        assert _is_spotify_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://youtube.com/watch?v=abc",
            "https://example.com/spotify-fan-page",
            "",
        ],
    )
    def test_rejects_non_spotify_urls(self, url):
        assert _is_spotify_url(url) is False


class TestSpotifyUrlType:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://open.spotify.com/track/abc123", "track"),
            ("https://open.spotify.com/album/abc123", "album"),
            ("https://open.spotify.com/playlist/abc123", "playlist"),
            ("https://open.spotify.com/episode/abc123", "episode"),
            ("https://open.spotify.com/show/abc123", "show"),
            ("https://open.spotify.com/artist/abc123", "unknown"),
        ],
    )
    def test_classifies_url_type(self, url, expected):
        assert _spotify_url_type(url) == expected


class TestExtractSpotifyId:
    def test_extracts_id_from_standard_url(self):
        assert (
            _extract_spotify_id("https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6")
            == "6rqhFgbbKwnb9MLmUQDhG6"
        )

    def test_robust_against_intl_locale_segment(self):
        """Spotify fuegt gelegentlich /intl-de/ zwischen Domain und Typ ein."""
        assert (
            _extract_spotify_id(
                "https://open.spotify.com/intl-de/track/6rqhFgbbKwnb9MLmUQDhG6"
            )
            == "6rqhFgbbKwnb9MLmUQDhG6"
        )

    def test_ignores_query_parameters(self):
        assert (
            _extract_spotify_id(
                "https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6?si=abc123"
            )
            == "6rqhFgbbKwnb9MLmUQDhG6"
        )

    def test_returns_none_for_unparseable_url(self):
        assert _extract_spotify_id("https://example.com/") is None


class TestSanitizeSpotifyUrl:
    def test_removes_tracking_parameters(self):
        assert (
            _sanitize_spotify_url("https://open.spotify.com/track/abc?si=xyz789")
            == "https://open.spotify.com/track/abc"
        )

    def test_removes_trailing_slash(self):
        assert (
            _sanitize_spotify_url("https://open.spotify.com/track/abc/")
            == "https://open.spotify.com/track/abc"
        )


class FakeConfig:
    def __init__(self, tmp_path):
        self.DOWNLOAD_DIR = tmp_path / "downloads"
        self.AUDIO_FORMAT = "m4a"
        self.AUDIO_QUALITY = "192"
        self.GENRE_MAPPING_DIR = "mapping"


def _make_downloader(tmp_path):
    config = FakeConfig(tmp_path)
    return SpotifyDownloader(config)


class TestRssManagerInjection:
    """
    ARCH-003, P-8: rss_manager ist jetzt optional injizierbar - vorher wurde
    IMMER intern ein echter PodcastRSSManager(mapping_dir, ...) konstruiert
    (Zugriff auf die reale mapping/-YAML), unabhaengig davon ob ein Test
    das ueberhaupt brauchte.
    """

    def test_uses_injected_rss_manager_instead_of_constructing_one(self, tmp_path):
        from unittest.mock import Mock

        fake_rss_manager = Mock()
        fake_rss_manager.feeds = {}
        config = FakeConfig(tmp_path)

        downloader = SpotifyDownloader(config, rss_manager=fake_rss_manager)

        assert downloader.rss_manager is fake_rss_manager

    def test_without_injection_constructs_real_rss_manager_as_before(self, tmp_path):
        downloader = _make_downloader(tmp_path)

        from utils.podcast_rss_manager import PodcastRSSManager

        assert isinstance(downloader.rss_manager, PodcastRSSManager)


class TestDownloadedFileDetectionBug004:
    def test_uses_filepath_from_ytdlp_result_not_newest_file_in_dir(self, tmp_path):
        """
        Kern-Regressionstest: ein fremder, "neuerer" Download liegt im
        selben Verzeichnis (simuliert einen parallel laufenden YouTube-
        Download). Die Datei-Erkennung darf trotzdem die per
        download_info["filepath"] tatsaechlich gemeldete eigene Datei
        waehlen, nicht die neueste im Verzeichnis.
        """
        downloader = _make_downloader(tmp_path)
        download_dir = downloader.download_dir

        own_file = download_dir / "Correct Artist - Correct Song.m4a"
        own_file.write_bytes(b"correct audio data")

        # Fremde, zeitlich NACH der eigenen Datei geschriebene Datei -
        # die alte "neueste Datei"-Logik wuerde faelschlich DIESE waehlen.
        foreign_file = download_dir / "Wrong Artist - Wrong Song.m4a"
        foreign_file.write_bytes(b"someone elses audio data")
        import os
        import time

        # Sicherstellen, dass foreign_file einen spaeteren mtime hat.
        now = time.time()
        os.utime(own_file, (now - 10, now - 10))
        os.utime(foreign_file, (now, now))

        meta = {"type": "track", "artist": "Correct Artist", "title": "Correct Song"}

        fake_ydl_instance = MagicMock()
        fake_ydl_instance.__enter__.return_value = fake_ydl_instance
        fake_ydl_instance.__exit__.return_value = False
        fake_ydl_instance.extract_info.return_value = {"filepath": str(own_file)}

        with patch(
            "yt_dlp.YoutubeDL", return_value=fake_ydl_instance
        ):
            result = asyncio.run(
                downloader._download_via_ytdlp_safe(meta, "https://open.spotify.com/track/x")
            )

        assert result["success"] is True
        assert result["track_info"]["filepath"] == str(own_file)

    def test_falls_back_to_newest_file_when_ytdlp_reports_no_filepath(self, tmp_path):
        """
        Charakterisiert den bewusst erhaltenen Fallback: liefert yt-dlp
        ausnahmsweise keinen Pfad, greift weiterhin die alte
        "neueste Datei"-Methode statt komplett zu scheitern.
        """
        downloader = _make_downloader(tmp_path)
        download_dir = downloader.download_dir

        only_file = download_dir / "Some Track.m4a"
        only_file.write_bytes(b"audio data")

        meta = {"type": "track", "artist": "Some Artist", "title": "Some Track"}

        fake_ydl_instance = MagicMock()
        fake_ydl_instance.__enter__.return_value = fake_ydl_instance
        fake_ydl_instance.__exit__.return_value = False
        # Truthy Ergebnis (Download war erfolgreich), aber ohne
        # "filepath"/"_filename"-Key - der seltene Fallback-Fall.
        fake_ydl_instance.extract_info.return_value = {"id": "some-video-id"}

        with patch("yt_dlp.YoutubeDL", return_value=fake_ydl_instance):
            result = asyncio.run(
                downloader._download_via_ytdlp_safe(meta, "https://open.spotify.com/track/x")
            )

        assert result["success"] is True
        assert result["track_info"]["filepath"] == str(only_file)
