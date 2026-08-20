"""
Unit-Tests für PodcastRSSManager (utils/podcast_rss_manager.py)
— vorher 0 Tests, live in SpotifyDownloader verdrahtet
(spotify_downloader.py:123 `self.rss_manager = PodcastRSSManager(...)`,
genutzt in get_feed()/get_feed_by_name() für den RSS-Fallback-Downloadpfad
für Spotify-Podcasts), gefunden über die systematische Ungetestet-Prüfung.

Nutzt echte YAML-Dateien in tmp_path statt Mocks fuer yaml.safe_load/dump -
Datei-I/O auf die eigene podcast_rss_feeds.yaml ist Kernlogik dieser Klasse
(Regel 10: Mapping-Dateien sind Fachlogik), kein externer Service im Sinne
von Regel 7.

Kein neuer Bug gefunden - reine Charakterisierung. add_feed()/get_all_feeds()/
get_enabled_feeds()/get_statistics()/has_feed()/get_feed_url()/reload() haben
aktuell keine Aufrufer ausserhalb dieser Datei (nur get_feed()/get_feed_by_name()
werden von spotify_downloader.py genutzt), sind aber Teil der zusammenhaengenden
oeffentlichen Manager-API (add_feed() persistiert z.B. dauerhaft in die YAML-
Datei) - analog zu TEST-016 (ProgressFormatter) bewusst mitgetestet statt als
Legacy behandelt.
"""

import yaml

from utils.podcast_rss_manager import PodcastRSSFeed, PodcastRSSManager


def write_yaml(mapping_dir, data):
    mapping_dir.mkdir(parents=True, exist_ok=True)
    with open(mapping_dir / "podcast_rss_feeds.yaml", "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True)


def make_manager(tmp_path, data=None):
    mapping_dir = tmp_path / "mapping"
    if data is not None:
        write_yaml(mapping_dir, data)
    else:
        mapping_dir.mkdir(parents=True, exist_ok=True)
    return PodcastRSSManager(mapping_dir=str(mapping_dir))


SAMPLE_DATA = {
    "podcasts": {
        "show123": {
            "name": "Fest & Flauschig",
            "rss_feed": "https://example.com/fest.xml",
            "enabled": True,
            "priority": 1,
            "source": "manual",
        },
        "show456": {
            "name": "Disabled Show",
            "rss_feed": "https://example.com/disabled.xml",
            "enabled": False,
        },
        "show789": {
            "name": "Invalid Show",
            "rss_feed": "",
        },
    }
}


# ─────────────────────────────────────────────────────────────────────────
# PodcastRSSFeed
# ─────────────────────────────────────────────────────────────────────────


class TestPodcastRSSFeed:
    def test_is_valid_true_when_enabled_and_has_url(self):
        feed = PodcastRSSFeed(spotify_show_id="x", name="X", rss_feed="http://x")
        assert feed.is_valid() is True

    def test_is_valid_false_when_disabled(self):
        feed = PodcastRSSFeed(
            spotify_show_id="x", name="X", rss_feed="http://x", enabled=False
        )
        assert feed.is_valid() is False

    def test_is_valid_false_when_no_rss_url(self):
        feed = PodcastRSSFeed(spotify_show_id="x", name="X", rss_feed="")
        assert feed.is_valid() is False

    def test_get_display_name_uses_name(self):
        feed = PodcastRSSFeed(spotify_show_id="id123", name="My Show", rss_feed="u")
        assert feed.get_display_name() == "My Show"

    def test_get_display_name_falls_back_to_id_when_name_empty(self):
        feed = PodcastRSSFeed(spotify_show_id="id123", name="", rss_feed="u")
        assert feed.get_display_name() == "id123"


# ─────────────────────────────────────────────────────────────────────────
# __init__ / _load_feeds
# ─────────────────────────────────────────────────────────────────────────


class TestLoadFeeds:
    def test_missing_file_results_in_empty_feeds(self, tmp_path):
        manager = make_manager(tmp_path)
        assert manager.feeds == {}

    def test_empty_file_results_in_empty_feeds(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        (mapping_dir / "podcast_rss_feeds.yaml").write_text("")
        manager = PodcastRSSManager(mapping_dir=str(mapping_dir))
        assert manager.feeds == {}

    def test_missing_podcasts_key_results_in_empty_feeds(self, tmp_path):
        manager = make_manager(tmp_path, data={"something_else": {}})
        assert manager.feeds == {}

    def test_valid_enabled_feed_is_loaded(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert "show123" in manager.feeds
        assert manager.feeds["show123"].name == "Fest & Flauschig"

    def test_disabled_feed_is_skipped(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert "show456" not in manager.feeds

    def test_enabled_but_missing_rss_url_is_skipped(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert "show789" not in manager.feeds

    def test_only_one_valid_feed_loaded_from_sample_data(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert len(manager.feeds) == 1

    def test_malformed_yaml_does_not_raise(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        (mapping_dir / "podcast_rss_feeds.yaml").write_text(
            "podcasts:\n  show1: [unclosed\n"
        )
        # Darf nicht raisen - Fehler wird intern geloggt.
        manager = PodcastRSSManager(mapping_dir=str(mapping_dir))
        assert manager.feeds == {}

    def test_defaults_applied_when_optional_fields_missing(self, tmp_path):
        data = {
            "podcasts": {
                "minimal": {"rss_feed": "https://example.com/min.xml"},
            }
        }
        manager = make_manager(tmp_path, data=data)
        feed = manager.feeds["minimal"]
        assert feed.name == "Unknown Podcast"
        assert feed.priority == 1
        assert feed.source == "unknown"
        assert feed.enabled is True


# ─────────────────────────────────────────────────────────────────────────
# get_feed
# ─────────────────────────────────────────────────────────────────────────


class TestGetFeed:
    def test_empty_id_returns_none(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert manager.get_feed("") is None
        assert manager.get_feed(None) is None

    def test_exact_match(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        feed = manager.get_feed("show123")
        assert feed is not None
        assert feed.spotify_show_id == "show123"

    def test_substring_match_query_contains_key(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        feed = manager.get_feed("prefix_show123_suffix")
        assert feed is not None
        assert feed.spotify_show_id == "show123"

    def test_substring_match_key_contains_query(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        feed = manager.get_feed("show1")
        assert feed is not None
        assert feed.spotify_show_id == "show123"

    def test_no_match_returns_none(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert manager.get_feed("totally_unrelated") is None


# ─────────────────────────────────────────────────────────────────────────
# get_feed_by_name
# ─────────────────────────────────────────────────────────────────────────


class TestGetFeedByName:
    def test_empty_name_returns_none(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert manager.get_feed_by_name("") is None

    def test_exact_case_insensitive_match(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        feed = manager.get_feed_by_name("fest & flauschig")
        assert feed is not None
        assert feed.spotify_show_id == "show123"

    def test_substring_match(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        feed = manager.get_feed_by_name("Flauschig")
        assert feed is not None
        assert feed.spotify_show_id == "show123"

    def test_no_match_returns_none(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert manager.get_feed_by_name("Nonexistent Show") is None


# ─────────────────────────────────────────────────────────────────────────
# has_feed / get_feed_url
# ─────────────────────────────────────────────────────────────────────────


class TestHasFeedAndUrl:
    def test_has_feed_true_for_known_id(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert manager.has_feed("show123") is True

    def test_has_feed_false_for_unknown_id(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert manager.has_feed("nope") is False

    def test_get_feed_url_returns_url(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert manager.get_feed_url("show123") == "https://example.com/fest.xml"

    def test_get_feed_url_returns_none_when_missing(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert manager.get_feed_url("nope") is None


# ─────────────────────────────────────────────────────────────────────────
# get_all_feeds / get_enabled_feeds / get_statistics
# ─────────────────────────────────────────────────────────────────────────


class TestCollections:
    def test_get_all_feeds_returns_a_copy(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        result = manager.get_all_feeds()
        result["injected"] = "should not affect manager"
        assert "injected" not in manager.feeds

    def test_get_enabled_feeds_only_returns_valid(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        enabled = manager.get_enabled_feeds()
        assert len(enabled) == 1
        assert enabled[0].spotify_show_id == "show123"

    def test_get_statistics_reflects_loaded_feeds(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        stats = manager.get_statistics()
        assert stats["total_feeds"] == 1
        assert stats["enabled_feeds"] == 1
        assert stats["disabled_feeds"] == 0
        assert stats["sources"] == {"manual": 1}
        assert stats["feeds"][0]["id"] == "show123"


# ─────────────────────────────────────────────────────────────────────────
# reload
# ─────────────────────────────────────────────────────────────────────────


class TestReload:
    def test_reload_picks_up_externally_modified_file(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)
        assert len(manager.feeds) == 1

        # Datei "von aussen" veraendern (z.B. manuelle Bearbeitung waehrend
        # der Bot laeuft, wie im Docstring von reload() beschrieben).
        write_yaml(
            tmp_path / "mapping",
            {
                "podcasts": {
                    "new_show": {
                        "name": "New Show",
                        "rss_feed": "https://example.com/new.xml",
                    }
                }
            },
        )

        manager.reload()

        assert "show123" not in manager.feeds
        assert "new_show" in manager.feeds


# ─────────────────────────────────────────────────────────────────────────
# add_feed
# ─────────────────────────────────────────────────────────────────────────


class TestAddFeed:
    def test_add_feed_creates_file_when_missing(self, tmp_path):
        manager = make_manager(tmp_path)

        result = manager.add_feed(
            spotify_id="brandnew",
            name="Brand New Show",
            rss_feed="https://example.com/brandnew.xml",
        )

        assert result is True
        assert "brandnew" in manager.feeds
        yaml_file = tmp_path / "mapping" / "podcast_rss_feeds.yaml"
        assert yaml_file.exists()

    def test_add_feed_preserves_existing_entries(self, tmp_path):
        manager = make_manager(tmp_path, data=SAMPLE_DATA)

        manager.add_feed(
            spotify_id="another_show",
            name="Another Show",
            rss_feed="https://example.com/another.xml",
        )

        assert "show123" in manager.feeds
        assert "another_show" in manager.feeds

    def test_add_feed_persists_to_disk_across_new_manager_instance(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.add_feed(
            spotify_id="persisted_show",
            name="Persisted Show",
            rss_feed="https://example.com/persisted.xml",
        )

        fresh_manager = PodcastRSSManager(mapping_dir=str(tmp_path / "mapping"))
        assert "persisted_show" in fresh_manager.feeds

    def test_add_feed_default_source_is_manual(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.add_feed(
            spotify_id="s1", name="S1", rss_feed="https://example.com/s1.xml"
        )
        assert manager.feeds["s1"].source == "manual"

    def test_add_feed_write_failure_returns_false(self, tmp_path, monkeypatch):
        manager = make_manager(tmp_path)

        def raise_on_open(*args, **kwargs):
            raise OSError("Simulated write failure")

        monkeypatch.setattr("builtins.open", raise_on_open)

        result = manager.add_feed(
            spotify_id="fail_show", name="Fail Show", rss_feed="https://example.com/f.xml"
        )

        assert result is False
