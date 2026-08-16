"""
Regressionstest fuer einen in dieser Session gefundenen Download-Bug:
DownloadHandler.handle_url() (klassen/download_handler.py) leitete frueher
JEDE nicht-Spotify http(s)://-URL ungeprueft an yt-dlp weiter. yt-dlp
unterstuetzt hunderte Extractors und macht serverseitige HTTP-Requests -
ohne Domain-Allowlist konnte jeder Telegram-Nutzer, der den Bot anschreiben
kann, den Server beliebige URLs abrufen lassen (SSRF-artiges Risiko).

_is_supported_download_url() prueft jetzt explizit auf unterstuetzte
YouTube-Domains, inkl. Schutz gegen klassische Domain-Confusion-Tricks
(z.B. "youtube.com.evil.com" oder "notyoutube.com").
"""

from klassen.download_handler import _is_supported_download_url


class TestSupportedYoutubeDomains:
    def test_youtube_com_is_supported(self):
        assert _is_supported_download_url("https://www.youtube.com/watch?v=abc123")
        assert _is_supported_download_url("https://youtube.com/watch?v=abc123")

    def test_youtu_be_is_supported(self):
        assert _is_supported_download_url("https://youtu.be/abc123")

    def test_music_youtube_com_is_supported(self):
        assert _is_supported_download_url("https://music.youtube.com/watch?v=abc123")


class TestUnsupportedUrlsAreRejected:
    def test_random_domain_is_rejected(self):
        assert not _is_supported_download_url("https://example.com/video.mp4")

    def test_internal_network_address_is_rejected(self):
        assert not _is_supported_download_url("http://192.168.1.1/admin")
        assert not _is_supported_download_url("http://localhost:8080/secret")
        assert not _is_supported_download_url("http://169.254.169.254/latest/meta-data/")

    def test_file_scheme_is_rejected(self):
        assert not _is_supported_download_url("file:///etc/passwd")

    def test_empty_or_malformed_url_is_rejected(self):
        assert not _is_supported_download_url("")
        assert not _is_supported_download_url("not a url at all")


class TestDomainConfusionTricksAreRejected:
    """
    Klassische Domain-Confusion-Angriffe: ein Domainname, der youtube.com
    als Substring enthaelt, aber tatsaechlich eine andere Domain ist.
    """

    def test_youtube_com_as_subdomain_suffix_is_rejected(self):
        assert not _is_supported_download_url("https://youtube.com.evil.com/video")

    def test_youtube_com_as_prefix_trick_is_rejected(self):
        assert not _is_supported_download_url("https://notyoutube.com/video")
        assert not _is_supported_download_url("https://evil-youtube.com/video")

    def test_youtube_in_path_only_is_rejected(self):
        assert not _is_supported_download_url("https://evil.com/youtube.com/video")
