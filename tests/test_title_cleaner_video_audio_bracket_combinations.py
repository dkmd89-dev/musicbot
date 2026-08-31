"""
META-11-Nachtrag (entdeckt via zweiten Live-Test-Download am 2026-08-26,
direkt im Anschluss an MB-01): der urspruengliche META-11-Fix
(docs/archive/MusicBot_METADATA_QUALITY_PHASE4_META11_AUDIT.md) ergaenzte \b vor
"video"/"audio" sowie ein explizites deutsches Kompositum-Pattern, deckte
aber nur die exakten Wortfolgen "(official [music] video)" bzw. "(audio)"
ab. Reale YouTube-Titel kombinieren diese Schluesselwoerter jedoch mit
weiteren Woertern wie "HD" oder "Lyric":

    "Time After Time (Official HD Video)"  -> "Time After Time (Official HD"
    "Song (Official Audio)"                -> "Song (Official"
    "Song (HD Audio)"                      -> "Song (HD"
    "Song (Official Lyric Video)"          -> "Song (Official Lyric"

(jeweils nur das letzte Wort vor der schliessenden Klammer wurde entfernt,
der Rest blieb mit haengender Klammer stehen - exakt dasselbe Bug-Muster
wie im urspruenglichen META-11-Fall, nur mit anderen Zusatzwoertern).

Live reproduziert: "Time After Time (Official HD Video)" (Cyndi Lauper)
in der isolierten Testumgebung.

Fix: die geklammerte Form wird jetzt zuerst und robust behandelt - jede
schliessende Klammer, deren Inhalt "video" oder "audio" als eigenstaendiges
Wort enthaelt, wird komplett entfernt, unabhaengig von sonstigen Woertern
davor (analog zum bereits bewaehrten Muster in apply_title_cleanup_rules(),
META-03). Betrifft light_title_cleanup() UND build_search_title()
(services/metadata/title_cleaner.py).
"""

from services.metadata.title_cleaner import TitleCleaner


class TestLightTitleCleanupVideoAudioBracketCombinations:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_official_hd_video_combo_is_fully_removed(self):
        """Kernfall, real via Live-Download reproduziert."""
        result = self.cleaner.light_title_cleanup(
            "Time After Time (Official HD Video)", "Cyndi Lauper"
        )
        assert result == "Time After Time"

    def test_official_audio_is_fully_removed(self):
        result = self.cleaner.light_title_cleanup("Song (Official Audio)", "Artist")
        assert result == "Song"

    def test_hd_audio_combo_is_fully_removed(self):
        result = self.cleaner.light_title_cleanup("Song (HD Audio)", "Artist")
        assert result == "Song"

    def test_official_lyric_video_combo_is_fully_removed(self):
        result = self.cleaner.light_title_cleanup(
            "Song (Official Lyric Video)", "Artist"
        )
        assert result == "Song"

    def test_no_dangling_bracket_remains_in_any_combination(self):
        cases = [
            "Time After Time (Official HD Video)",
            "Song (Official Audio)",
            "Song (HD Audio)",
            "Song (Official Lyric Video)",
        ]
        for title in cases:
            result = self.cleaner.light_title_cleanup(title, "Artist")
            assert "(" not in result
            assert ")" not in result


class TestBuildSearchTitleVideoAudioBracketCombinations:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_official_hd_video_combo_is_fully_removed(self):
        result = self.cleaner.build_search_title(
            parsed_title="Time After Time (Official HD Video)",
            original_title="Cyndi Lauper - Time After Time (Official HD Video)",
            final_artist="Cyndi Lauper",
        )
        assert result == "Time After Time"

    def test_official_audio_is_fully_removed(self):
        result = self.cleaner.build_search_title(
            parsed_title="Song (Official Audio)",
            original_title="Artist - Song (Official Audio)",
            final_artist="Artist",
        )
        assert result == "Song"


class TestVideoAudioBracketFixRegression:
    """Bereits vorher funktionierende Faelle (META-11, META-03-artige
    Ueberkorrektur-Schutzfaelle) muessen weiterhin identisch funktionieren."""

    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_german_compound_musikvideo_still_works(self):
        result = self.cleaner.light_title_cleanup(
            "Weil ich dich liebe (Offizielles Musikvideo)", "Westernhagen"
        )
        assert result == "Weil ich dich liebe"

    def test_english_official_music_video_still_works(self):
        result = self.cleaner.light_title_cleanup(
            "Song Title (Official Music Video)", "Artist"
        )
        assert result == "Song Title"

    def test_bracketless_video_suffix_still_works(self):
        result = self.cleaner.light_title_cleanup("Song Title Video", "Artist")
        assert result == "Song Title"

    def test_musikvideo_not_falsely_matched_mid_title(self):
        result = self.cleaner.light_title_cleanup(
            "Musikvideo Festival Highlights", "Artist"
        )
        assert result == "Musikvideo Festival Highlights"

    def test_parenthetical_without_video_or_audio_keyword_is_untouched(self):
        """Ueberkorrektur-Schutz: eine Klammer ohne "video"/"audio" darf
        durch das neue, breitere Bracket-Pattern nicht angetastet werden."""
        result = self.cleaner.light_title_cleanup("(Extended Cut) Song", "Artist")
        assert result == "(Extended Cut) Song"
