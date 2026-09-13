# tests/test_statistik_format_helpers.py
# -*- coding: utf-8 -*-
"""
Tests für handlers/statistik_format_helpers.py (MASTER PHASE B, Abschnitt
26.1: geteilte Presentation-Helfer für Personal- und Family-Statistics).

Diese Funktionen wurden 1:1 aus handlers/mugge_statistik_handler.py
extrahiert - die bestehenden Tests dort (TestFormatPlays/TestFormatRank/
TestFormatDateRange in tests/test_mugge_statistik_handler.py) bleiben
unverändert bestehen (StatistikHandler delegiert jetzt nur noch hierhin).
Diese Datei testet die Funktionen direkt, ohne Handler-Instanz.
"""

from datetime import datetime

from handlers.statistik_format_helpers import (
    RANK_MEDALS,
    SEPARATOR,
    format_date_range,
    format_plays,
    format_rank,
)


class TestFormatPlays:
    def test_singular(self):
        assert format_plays(1) == "1 Play"

    def test_plural(self):
        assert format_plays(2) == "2 Plays"
        assert format_plays(0) == "0 Plays"


class TestFormatRank:
    def test_top_three_use_medals(self):
        assert format_rank(1) == "🥇"
        assert format_rank(2) == "🥈"
        assert format_rank(3) == "🥉"

    def test_rank_four_and_below_are_numeric(self):
        assert format_rank(4) == "4."
        assert format_rank(10) == "10."

    def test_rank_medals_constant_has_exactly_three_entries(self):
        assert set(RANK_MEDALS.keys()) == {1, 2, 3}


class TestFormatDateRange:
    def test_same_month(self):
        assert (
            format_date_range(datetime(2026, 9, 7), datetime(2026, 9, 14))
            == "07.–13.09.2026"
        )

    def test_month_change(self):
        assert (
            format_date_range(datetime(2026, 9, 28), datetime(2026, 10, 5))
            == "28.09.–04.10.2026"
        )

    def test_year_change(self):
        assert (
            format_date_range(datetime(2026, 12, 28), datetime(2027, 1, 4))
            == "28.12.2026–03.01.2027"
        )

    def test_full_year(self):
        assert (
            format_date_range(datetime(2026, 1, 1), datetime(2027, 1, 1))
            == "01.01.–31.12.2026"
        )


class TestSeparatorConstant:
    def test_separator_is_20_chars(self):
        assert len(SEPARATOR) == 20
