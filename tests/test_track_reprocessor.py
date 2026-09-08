# tests/test_track_reprocessor.py
# -*- coding: utf-8 -*-
"""
Production-Audit 2026-09-08, P3: services/metadata/track_reprocessor.py
(1012 Zeilen) hatte bisher kein dediziertes Testfile - die reinen,
netzwerkfreien Helferfunktionen wurden nur indirekt über
tests/test_reprocess_artist_metadata.py mitgetestet. Dieses Testfile
deckt sie direkt ab (CLAUDE.md Abschnitt 7: Produktionscode wirklich
testen).

process_file() selbst (der async End-to-End-Pfad) ist bereits an zwei
Stellen abgedeckt: tests/test_reprocess_artist_metadata.py (ueber den
importlib-geladenen Skript-Re-Export) und
tests/test_library_repair_executor_l2_real_pipeline.py (direkt gegen
apply_level2()) - hier bewusst nicht dupliziert.
"""

from services.metadata.track_reprocessor import (
    check_unresolved,
    count_existing_genre_entries,
    diff_snapshots,
    flatten_existing_artists,
    genre_would_downgrade,
    strip_producer_credit,
    strip_remix_suffix,
)


class _GenreResult:
    def __init__(self, primary=None, secondary=None):
        self.primary = primary
        self.secondary = secondary or []


# ── diff_snapshots ──────────────────────────────────────────────────────

class TestDiffSnapshots:
    def test_no_changes_yields_empty_dict(self):
        snap = {"title": ["A"], "artist": ["B"]}
        assert diff_snapshots(snap, dict(snap)) == {}

    def test_changed_field_is_reported_with_before_after(self):
        before = {"title": ["Alt"]}
        after = {"title": ["Neu"]}
        assert diff_snapshots(before, after) == {
            "title": {"before": ["Alt"], "after": ["Neu"]}
        }

    def test_stream_info_and_audio_essence_md5_are_excluded(self):
        """Diese beiden Felder werden separat als Integritaetsmarker
        geprueft (executor.py), duerfen NICHT als normale Tag-Aenderung
        im changes-Dict auftauchen."""
        before = {"stream_info": {"codec": "aac"}, "audio_essence_md5": "abc"}
        after = {"stream_info": {"codec": "mp3"}, "audio_essence_md5": "def"}
        assert diff_snapshots(before, after) == {}

    def test_missing_key_in_after_is_treated_as_none(self):
        before = {"year": ["2020"]}
        after = {}
        assert diff_snapshots(before, after) == {
            "year": {"before": ["2020"], "after": None}
        }


# ── flatten_existing_artists ────────────────────────────────────────────

class TestFlattenExistingArtists:
    def test_single_clean_artist_unchanged(self):
        assert flatten_existing_artists(["Solo Artist"]) == ["Solo Artist"]

    def test_semicolon_glued_legacy_value_is_split(self):
        assert flatten_existing_artists(["CHAPO102; Gustav"]) == ["CHAPO102", "Gustav"]

    def test_feat_notation_splits_main_and_featuring(self):
        assert flatten_existing_artists(["makko feat. toobrokeforfiji"]) == [
            "makko", "toobrokeforfiji",
        ]

    def test_duplicates_across_entries_are_deduplicated(self):
        result = flatten_existing_artists(["makko", "makko"])
        assert result == ["makko"]

    def test_empty_input_yields_empty_list(self):
        assert flatten_existing_artists([]) == []
        assert flatten_existing_artists(None) == []


# ── count_existing_genre_entries ────────────────────────────────────────

class TestCountExistingGenreEntries:
    def test_empty_yields_zero(self):
        assert count_existing_genre_entries([]) == 0
        assert count_existing_genre_entries([""]) == 0

    def test_single_unseparated_value_counts_as_one(self):
        assert count_existing_genre_entries(["Pop"]) == 1

    def test_current_semicolon_separator(self):
        assert count_existing_genre_entries(["Pop; Rock; Indie"]) == 3

    def test_legacy_slash_separator(self):
        assert count_existing_genre_entries(["Pop / Rock"]) == 2


# ── genre_would_downgrade ───────────────────────────────────────────────

class TestGenreWouldDowngrade:
    def test_no_result_never_downgrades(self):
        assert genre_would_downgrade(["Pop; Rock; Indie"], None) is False

    def test_result_without_primary_never_downgrades(self):
        assert genre_would_downgrade(["Pop; Rock"], _GenreResult(primary=None)) is False

    def test_fewer_fresh_values_than_existing_is_downgrade(self):
        existing = ["Pop; Rock; Indie"]
        fresh = _GenreResult(primary="Pop", secondary=[])
        assert genre_would_downgrade(existing, fresh) is True

    def test_equal_or_more_fresh_values_is_not_downgrade(self):
        existing = ["Pop; Rock"]
        fresh = _GenreResult(primary="Pop", secondary=["Rock", "Indie"])
        assert genre_would_downgrade(existing, fresh) is False


# ── strip_producer_credit ───────────────────────────────────────────────

class TestStripProducerCredit:
    def test_parenthesized_credit_removed(self):
        assert strip_producer_credit('"ADLIBS" (prod. by Safecall777)') == '"ADLIBS"'

    def test_bare_trailing_credit_removed(self):
        assert strip_producer_credit('"ADLIBS" prod. Safecall777') == '"ADLIBS"'

    def test_title_without_credit_unchanged(self):
        assert strip_producer_credit("Ganz normaler Titel") == "Ganz normaler Titel"

    def test_falls_back_to_original_if_nothing_would_remain(self):
        assert strip_producer_credit("prod. X") == "prod. X"


# ── strip_remix_suffix ──────────────────────────────────────────────────

class TestStripRemixSuffix:
    def test_trailing_remix_suffix_removed(self):
        assert strip_remix_suffix("Blauer Tag (Robin Schulz Remix)") == "Blauer Tag"

    def test_title_without_remix_unchanged(self):
        assert strip_remix_suffix("Ganz normaler Titel") == "Ganz normaler Titel"

    def test_non_trailing_parenthesis_is_not_touched(self):
        assert strip_remix_suffix("Titel (Live) Rest") == "Titel (Live) Rest"


# ── check_unresolved ─────────────────────────────────────────────────────

class TestCheckUnresolved:
    def _after(self, **over):
        base = {"replaygain_track_gain": [], "loudness_normalized": []}
        base.update(over)
        return base

    def test_missing_loudness_data_is_unresolved(self):
        reasons = check_unresolved({}, self._after(), "Sauberer Titel")
        assert any("ReplayGain/Loudness" in r for r in reasons)

    def test_present_replaygain_tag_is_not_unresolved_for_loudness(self):
        after = self._after(replaygain_track_gain=["-3.5 dB"])
        reasons = check_unresolved({}, after, "Sauberer Titel")
        assert not any("ReplayGain/Loudness" in r for r in reasons)

    def test_illegal_characters_in_title_are_unresolved(self):
        after = self._after(replaygain_track_gain=["-3.5 dB"])
        reasons = check_unresolved({}, after, "F*cked Up")
        assert any("nicht darstellbar" in r for r in reasons)

    def test_harmless_feat_reformatting_is_not_unresolved(self):
        """Final-Audit-Fund (siehe Kommentar in track_reprocessor.py):
        eine reine FEAT_NOTATION-Umformatierung darf NICHT als
        UNRESOLVED gemeldet werden, nur echte illegale Zeichen."""
        after = self._after(replaygain_track_gain=["-3.5 dB"])
        reasons = check_unresolved({}, after, "Verlaufen (feat. SIDO)")
        assert reasons == []

    def test_clean_case_yields_no_reasons(self):
        after = self._after(replaygain_track_gain=["-3.5 dB"])
        assert check_unresolved({}, after, "Sauberer Titel") == []
