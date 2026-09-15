# tests/test_cover_sort_key.py
# -*- coding: utf-8 -*-
"""
Tests für _cover_sort_key() in services/metadata/cover_processor.py.

Der Sortier-Schlüssel ist die zentrale Stelle, die bei Score-Gleichstand
(Cap bei 150) entscheidet, welches Cover gewinnt. Vor dem Fix entschied
die Completion-Reihenfolge aus `as_completed()` — d.h. der schnellste
Netzwerk-Roundtrip gewann, nicht das beste Bild.

Diese Tests sichern die drei Tiebreaker-Stufen gegen Refactoring ab:
  1. total_score   – Hauptkriterium
  2. Pixel-Anzahl  – Auflösung als Tiebreaker
  3. file_size_kb  – Dateigröße als letzter Tiebreaker

Reale Fehlwahlen aus dem Produktionslauf 2026-09-14 sind als Regression-
Fälle dokumentiert (siehe docstrings der Testklassen).
"""

from __future__ import annotations

import pytest

from services.metadata.cover_processor import CoverCandidate, _cover_sort_key


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────


def make_candidate(
    source: str,
    score: int,
    width: int = 1000,
    height: int = 1000,
    file_size_kb: int = 200,
) -> CoverCandidate:
    """Erzeugt einen minimalen CoverCandidate für Sortier-Tests.

    Nur die für den Sortier-Key relevanten Felder werden gesetzt; data
    bleibt leer (b""), weil der Schlüssel es nicht liest.
    """
    return CoverCandidate(
        source=source,
        data=b"",
        width=width,
        height=height,
        file_size_kb=file_size_kb,
        total_score=score,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stufe 1: total_score
# ─────────────────────────────────────────────────────────────────────────────


class TestScoreTakesPrecedence:
    """Bei unterschiedlichem Score entscheidet der Score — die anderen
    Kriterien dürfen einen höheren Score NICHT überstimmen."""

    def test_higher_score_wins_regardless_of_resolution(self):
        # Ein 300×300 mit Score 160 MUSS gegen 5000×5000 mit Score 140
        # gewinnen — der Score ist das Hauptkriterium.
        small = make_candidate("caa", score=160, width=300, height=300)
        large = make_candidate("apple_music", score=140, width=5000, height=5000)
        assert max([small, large], key=_cover_sort_key) is small

    def test_higher_score_wins_regardless_of_file_size(self):
        tiny = make_candidate("caa", score=200, width=1000, height=1000, file_size_kb=10)
        fat = make_candidate("apple_music", score=150, width=1000, height=1000, file_size_kb=5000)
        assert max([tiny, fat], key=_cover_sort_key) is tiny


# ─────────────────────────────────────────────────────────────────────────────
# Stufe 2: Pixel-Anzahl (der eigentliche Fix)
# ─────────────────────────────────────────────────────────────────────────────


class TestResolutionTiebreaker:
    """Bei Score-Gleichstand entscheidet die Pixel-Anzahl.

    Regression 2026-09-14: vor dem Fix gewann bei Score 150 die zuerst
    zurückkommende Quelle — im Log nachweisbar bei CHAPO102 (Deezer
    1000×1000 vs. CAA 2000×2000), Montez (CAA 640×640 vs. Apple
    3832×2152) und Helene Fischer (Fanart 1000×1000 vs. Apple 3000×3000).
    """

    def test_chapo102_warschau_deezer_vs_caa(self):
        # Reale Fehlwahl: Deezer (1000×1000) gewann gegen CAA (2000×2000).
        deezer = make_candidate("deezer", score=150, width=1000, height=1000)
        caa = make_candidate("coverartarchive", score=150, width=2000, height=2000)
        winner = max([deezer, caa], key=_cover_sort_key)
        assert winner.source == "coverartarchive"
        assert winner.width == 2000

    def test_montez_wie_es_ist_caa_vs_apple(self):
        # Reale Fehlwahl: CAA (640×640) gewann gegen Apple (3832×2152).
        caa = make_candidate("coverartarchive", score=150, width=640, height=640)
        apple = make_candidate("apple_music", score=150, width=3832, height=2152)
        winner = max([caa, apple], key=_cover_sort_key)
        assert winner.source == "apple_music"
        # Pixel-Anzahl: 640² = 409.600 vs. 3832×2152 ≈ 8,25 Mio.
        assert winner.width * winner.height > caa.width * caa.height * 10

    def test_helene_fischer_fanart_vs_apple(self):
        # Reale Fehlwahl: Fanart.tv Artist (1000×1000) gewann gegen Apple
        # (3000×3000) und CAA (2000×2000).
        fanart = make_candidate("fanart_artist", score=150, width=1000, height=1000)
        caa = make_candidate("coverartarchive", score=150, width=2000, height=2000)
        apple = make_candidate("apple_music", score=150, width=3000, height=3000)
        winner = max([fanart, caa, apple], key=_cover_sort_key)
        assert winner.source == "apple_music"

    def test_non_square_bigger_pixel_area_wins(self):
        # 3832×1677 (Apple, non-square) vs. 640×640 (CAA, square)
        # Pixel-Anzahl: ~6,4 Mio. vs. 410k → Apple gewinnt,
        # auch wenn das Bild nicht quadratisch ist.
        caa = make_candidate("coverartarchive", score=150, width=640, height=640)
        apple = make_candidate("apple_music", score=150, width=3832, height=1677)
        winner = max([caa, apple], key=_cover_sort_key)
        assert winner.source == "apple_music"

    def test_asymmetric_resolution_counts_full_pixels(self):
        # 1000×5000 hat dieselbe Pixel-Anzahl wie 5000×1000 —
        # der Schlüssel multipliziert, sortiert nicht nach max_dim.
        a = make_candidate("a", score=150, width=1000, height=5000)
        b = make_candidate("b", score=150, width=5000, height=1000)
        # Beide haben 5 Mio. Pixel — Gleichstand in Stufe 2.
        # Dann entscheidet Stufe 3 (file_size_kb).
        a.file_size_kb = 100
        b.file_size_kb = 200
        # b hat größere Datei → gewinnt bei sonstigem Gleichstand
        winner = max([a, b], key=_cover_sort_key)
        assert winner is b


# ─────────────────────────────────────────────────────────────────────────────
# Stufe 3: Dateigröße
# ─────────────────────────────────────────────────────────────────────────────


class TestFileSizeTiebreaker:
    """Score und Pixel gleich → Dateigröße entscheidet (Kompressions-
    Heuristik: größere Datei deutet auf weniger JPEG-Artefakte hin)."""

    def test_larger_file_wins_on_full_tie(self):
        small = make_candidate("a", score=150, width=1000, height=1000, file_size_kb=100)
        large = make_candidate("b", score=150, width=1000, height=1000, file_size_kb=500)
        assert max([small, large], key=_cover_sort_key) is large

    def test_file_size_does_not_override_pixels(self):
        # Dateigröße ist NACH der Pixel-Anzahl — ein 1000×1000 mit
        # 5000 KB darf NICHT gegen ein 2000×2000 mit 100 KB gewinnen.
        fat_small = make_candidate("a", score=150, width=1000, height=1000, file_size_kb=5000)
        lean_large = make_candidate("b", score=150, width=2000, height=2000, file_size_kb=100)
        assert max([fat_small, lean_large], key=_cover_sort_key) is lean_large


# ─────────────────────────────────────────────────────────────────────────────
# Edge Cases: None / 0
# ─────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Robustheit gegen unvollständig befüllte Kandidaten.

    Sollte nie passieren, aber ein Crash im Sort-Key würde den ganzen
    Cover-Prozess killen — defensive Defaults sind billig.
    """

    def test_none_dimensions_treated_as_zero(self):
        # width=None, height=None → Pixel-Anzahl 0, kein TypeError
        c = make_candidate("x", score=150)
        c.width = None  # type: ignore[assignment]
        c.height = None  # type: ignore[assignment]
        c.file_size_kb = None  # type: ignore[assignment]
        # Sollte nicht crashen
        key = _cover_sort_key(c)
        assert key == (150, 0, 0)

    def test_zero_dimensions(self):
        c = make_candidate("x", score=150, width=0, height=0, file_size_kb=0)
        assert _cover_sort_key(c) == (150, 0, 0)

    def test_zero_score_is_valid(self):
        # Score 0 ist ein legitimer Wert (z.B. YouTube mit Penalty),
        # kein Fehler.
        c = make_candidate("youtube_max", score=0, width=1280, height=720)
        assert _cover_sort_key(c) == (0, 1280 * 720, 200)


# ─────────────────────────────────────────────────────────────────────────────
# Determinismus / Stabilität
# ─────────────────────────────────────────────────────────────────────────────


class TestDeterminism:
    """Sortier-Key muss deterministisch sein, unabhängig von der
    Reihenfolge der Eingabe."""

    def test_max_is_stable_regardless_of_input_order(self):
        c1 = make_candidate("a", score=150, width=1000, height=1000, file_size_kb=200)
        c2 = make_candidate("b", score=150, width=2000, height=2000, file_size_kb=400)
        c3 = make_candidate("c", score=140, width=5000, height=5000, file_size_kb=5000)
        expected = c2  # Score 150, größte Pixel-Anzahl
        for order in ([c1, c2, c3], [c3, c2, c1], [c2, c1, c3], [c3, c1, c2]):
            assert max(order, key=_cover_sort_key) is expected

    def test_sort_key_comparable_as_tuple(self):
        # _cover_sort_key muss ein vergleichbares Tupel liefern,
        # damit sorted()/max() funktionieren.
        c = make_candidate("a", score=150, width=1000, height=1000)
        key = _cover_sort_key(c)
        assert isinstance(key, tuple)
        assert all(isinstance(x, int) for x in key)