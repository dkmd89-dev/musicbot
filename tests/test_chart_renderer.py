"""
Unit-Tests für ChartRenderer (services/statistik/chart_renderer.py)
— extrahiert aus StatistikService (ARCH-003, P-6). Nutzt echtes matplotlib
(kein Mock, einziger Ort im Repository mit dieser Abhängigkeit) und rendert
in tmp_path.
"""

from unittest.mock import Mock

from services.statistik.chart_renderer import ChartRenderer


def make_renderer(tmp_path):
    return ChartRenderer(tmp_path, logger=Mock())


def make_stats(top_songs=None, top_artists=None, period="month", username="alice"):
    return {
        "period": period,
        "navidrome_username": username,
        "top_songs": [("Song A", 5), ("Song B", 3)] if top_songs is None else top_songs,
        "top_artists": (
            [("Bausa", 5), ("Kollegah", 3)] if top_artists is None else top_artists
        ),
    }


class TestCreateChart:
    def test_creates_png_file_for_songs(self, tmp_path):
        renderer = make_renderer(tmp_path)
        stats = make_stats()

        result = renderer.create_chart(stats, "songs")

        assert result is not None
        assert result.exists()
        assert result.suffix == ".png"

    def test_creates_png_file_for_artists(self, tmp_path):
        renderer = make_renderer(tmp_path)
        stats = make_stats()

        result = renderer.create_chart(stats, "artists")

        assert result is not None
        assert result.exists()

    def test_no_data_for_chart_type_returns_none(self, tmp_path):
        renderer = make_renderer(tmp_path)
        stats = make_stats(top_songs=[])

        result = renderer.create_chart(stats, "songs")

        assert result is None

    def test_filename_includes_period_and_sanitized_username(self, tmp_path):
        renderer = make_renderer(tmp_path)
        stats = make_stats(period="week", username="al/ice")

        result = renderer.create_chart(stats, "songs")

        assert "week" in result.name
        assert "al_ice" in result.name
        assert "/" not in result.name
