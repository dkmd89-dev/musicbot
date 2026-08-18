"""
Unit-Tests für YearResolver (services/downloader/download/year_resolver.py)
— vorher 0 Tests, live in EnhancedDownloadProcessor._do_init() verdrahtet
(download_utils.py), gefunden über die systematische Ungetestet-Prüfung.
"""

from unittest.mock import Mock

import pytest

from services.downloader.download.year_resolver import YearResolver


@pytest.fixture
def resolver():
    return YearResolver(logger=Mock())


class TestExtractYearFromText:
    def test_extracts_year_from_title(self, resolver):
        assert resolver._extract_year_from_text("Song (1987 Remaster)") == 1987

    def test_continuous_yyyymmdd_digit_run_is_not_matched(self, resolver):
        """
        Charakterisiert einen gefundenen Bug (jetzt an der Aufrufstelle
        resolve_playlist_year() behoben, siehe TestResolvePlaylistYear):
        _extract_year_from_text() selbst kann ein Jahr aus einer
        durchgehenden YYYYMMDD-Ziffernfolge (yt-dlp-Standardformat fuer
        upload_date, z.B. "20230815") NICHT extrahieren - die (?!\\d)-
        Wortgrenze im Regex verhindert JEDEN Treffer, da direkt nach dem
        Jahr weitere Ziffern (MMDD) folgen. Funktioniert nur mit einem
        Trennzeichen (siehe naechster Test) oder in Freitext-Titeln.
        """
        assert resolver._extract_year_from_text("20230815") is None

    def test_extracts_year_from_hyphenated_date(self, resolver):
        assert resolver._extract_year_from_text("2023-08-15") == 2023

    def test_no_year_returns_none(self, resolver):
        assert resolver._extract_year_from_text("No year here") is None

    def test_empty_string_returns_none(self, resolver):
        assert resolver._extract_year_from_text("") is None

    def test_year_below_1950_is_not_matched(self, resolver):
        assert resolver._extract_year_from_text("Song from 1899") is None

    def test_digit_adjacent_to_year_is_not_matched(self, resolver):
        # Wortgrenzen-Schutz: "19999" enthaelt "1999" als Teilstring, darf
        # aber wegen (?!\d) nicht als Jahr 1999 erkannt werden.
        assert resolver._extract_year_from_text("19999") is None

    def test_year_2030_and_beyond_is_not_matched_despite_year_max(self, resolver):
        """
        Charakterisiert eine gefundene Inkonsistenz: YEAR_MAX ist auf 2035
        gesetzt, aber YEAR_PATTERN (20[0-2]\\d) deckt nur 2000-2029 ab.
        Jahre ab 2030 werden ueber den Regex-Pfad daher NIE erkannt, obwohl
        sie laut YEAR_MIN/YEAR_MAX gueltig waeren. Nicht behoben (noch nicht
        aktiv relevant, aktuelles Jahr < 2030) - siehe Baseline-Dokumentation.
        """
        assert resolver._extract_year_from_text("Song (2030 Release)") is None
        assert resolver.YEAR_MAX == 2035  # bestaetigt die Diskrepanz zur Regex


class TestDetermineDominantYearFromEntries:
    def test_empty_entries_returns_none(self, resolver):
        assert resolver.determine_dominant_year_from_entries([]) is None

    def test_release_year_field_has_highest_priority(self, resolver):
        entries = [{"release_year": 2020, "year": 2019, "upload_date": "20180101"}]
        assert resolver.determine_dominant_year_from_entries(entries) == 2020

    def test_year_field_used_when_release_year_missing(self, resolver):
        entries = [{"year": 2019, "upload_date": "20180101"}]
        assert resolver.determine_dominant_year_from_entries(entries) == 2019

    def test_upload_date_used_when_year_fields_missing(self, resolver):
        entries = [{"upload_date": "20180315"}]
        assert resolver.determine_dominant_year_from_entries(entries) == 2018

    def test_title_regex_used_as_last_resort(self, resolver):
        entries = [{"title": "Classic Hit (1995 Version)"}]
        assert resolver.determine_dominant_year_from_entries(entries) == 1995

    def test_most_common_year_wins(self, resolver):
        entries = [
            {"year": 2020},
            {"year": 2020},
            {"year": 2019},
        ]
        assert resolver.determine_dominant_year_from_entries(entries) == 2020

    def test_invalid_year_values_are_skipped(self, resolver):
        entries = [{"year": "not-a-year"}, {"year": 2021}]
        assert resolver.determine_dominant_year_from_entries(entries) == 2021

    def test_year_outside_valid_range_is_skipped(self, resolver):
        entries = [{"year": 1800}, {"year": 2021}]
        assert resolver.determine_dominant_year_from_entries(entries) == 2021

    def test_no_valid_years_anywhere_returns_none(self, resolver):
        entries = [{"title": "No year at all"}, {}]
        assert resolver.determine_dominant_year_from_entries(entries) is None


class TestResolvePlaylistYear:
    def test_entries_source_has_highest_priority(self, resolver):
        entries = [{"year": 2020}]
        result = resolver.resolve_playlist_year(
            entries, {"year": 2015}, {"upload_date": "20100101"}
        )
        assert result == 2020

    def test_falls_back_to_processed_playlist_year(self, resolver):
        result = resolver.resolve_playlist_year(
            [], {"year": 2015}, {"upload_date": "20100101"}
        )
        assert result == 2015

    def test_falls_back_to_playlist_info_upload_date(self, resolver):
        result = resolver.resolve_playlist_year([], {}, {"upload_date": "20100101"})
        assert result == 2010

    def test_no_source_available_returns_none(self, resolver):
        assert resolver.resolve_playlist_year([], {}, {}) is None

    def test_invalid_processed_playlist_year_falls_through(self, resolver):
        result = resolver.resolve_playlist_year(
            [], {"year": "invalid"}, {"upload_date": "20100101"}
        )
        assert result == 2010

    def test_processed_playlist_year_out_of_range_falls_through(self, resolver):
        result = resolver.resolve_playlist_year(
            [], {"year": 1800}, {"upload_date": "20100101"}
        )
        assert result == 2010
