"""
META-03 (docs/archive/MusicBot_METADATA_QUALITY_PHASE0_AUDIT.md, Read-Only-Audit
vom 2026-08-26): services/metadata/title_cleaner.py::apply_title_cleanup_rules()
enthielt ein Pattern, das Marketing-Suffixe wie "(Official Video)" entfernt,
dabei aber Klammer-Oeffnung ("\\(?") und Klammer-Schluss ("\\)?") unabhaengig
voneinander optional behandelte. Enthielt eine Klammer neben bekannten
Schluesselwoertern (official/music/lyric/video/audio/live/version/remaster/
hd/4k/vevo/explicit) auch ein NICHT gelistetes Wort (z.B. "Visual",
"Trailer", "Bonus Track"), wurde nur der Schluesselwort-Teil entfernt - die
schliessende Klammer blieb als haengendes Fragment im Titel stehen.

Real in der Library bestaetigt: "Bebe Rexha/Singles/2026 - Sad Girls
(Official Visual).m4a" -> Titel-Tag wurde zu "Sad Girls Visual)" statt
"Sad Girls" bereinigt.

Fix: das Pattern wurde in zwei Teile gesplittet -
  (a) geklammerte Form: verlangt zwingend eine echte schliessende Klammer,
      first-word muss ein bekanntes Schluesselwort sein, alles bis zur
      schliessenden Klammer wird mitentfernt (unabhaengig davon, ob die
      weiteren Woerter selbst in der Liste stehen) - kann also nie mehr
      eine haengende Klammer hinterlassen.
  (b) klammerlose Form: unveraendert wie zuvor (nur bekannte Schluesselwoerter
      werden entfernt, ohne Klammer-Handling).
Beide zusammen reproduzieren exakt das vorherige Verhalten fuer alle
bereits funktionierenden Faelle (reines Schluesselwort-Klammer-Inhalt,
klammerlose Suffixe) und beheben zusaetzlich den Faellen mit gemischtem
Klammer-Inhalt.

Nutzt dieselbe Teststruktur wie tests/test_metadata_modules.py
(TestTitleCleaner::test_apply_cleanup_rules).
"""

from services.metadata.title_cleaner import TitleCleaner


class TestApplyTitleCleanupRulesMixedBracketContent:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_official_plus_unlisted_word_in_parens_is_fully_removed(self):
        """META-03-Kernfall, real in Library bestaetigt."""
        result = self.cleaner.apply_title_cleanup_rules("Sad Girls (Official Visual)")
        assert result == "Sad Girls"

    def test_official_plus_unlisted_trailer_in_parens_is_fully_removed(self):
        result = self.cleaner.apply_title_cleanup_rules("Song (Official Trailer)")
        assert result == "Song"

    def test_hd_plus_multiple_unlisted_words_in_parens_is_fully_removed(self):
        result = self.cleaner.apply_title_cleanup_rules("Song (HD Bonus Track)")
        assert result == "Song"

    def test_no_dangling_closing_bracket_remains_in_any_case(self):
        for title in [
            "Sad Girls (Official Visual)",
            "Song (Official Trailer)",
            "Song (HD Bonus Track)",
        ]:
            result = self.cleaner.apply_title_cleanup_rules(title)
            assert ")" not in result
            assert "(" not in result


class TestApplyTitleCleanupRulesMarketingSuffixRegression:
    """Bereits vorher funktionierende Faelle - deckungsgleich mit
    tests/test_metadata_modules.py::test_apply_cleanup_rules."""

    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_fully_keyword_bracket_still_fully_removed(self):
        result = self.cleaner.apply_title_cleanup_rules(
            "Song Title (Official Music Video)"
        )
        assert result == "Song Title"

    def test_bracketless_suffix_after_pipe_still_removed(self):
        result = self.cleaner.apply_title_cleanup_rules("Song Title | Official Video")
        assert result == "Song Title"

    def test_explicit_and_hd_combo_still_removed(self):
        result = self.cleaner.apply_title_cleanup_rules(
            "Song Title (explicit) [HD]"
        )
        assert result == "Song Title"

    def test_bare_trailing_4k_still_removed(self):
        result = self.cleaner.apply_title_cleanup_rules("Rotkäppchen 4K")
        assert result == "Rotkäppchen"


class TestApplyTitleCleanupRulesDoesNotOvercorrect:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_parenthetical_without_any_known_keyword_is_untouched(self):
        """Ueberkorrektur-Schutz: eine Klammer, deren erstes Wort KEIN
        bekanntes Marketing-Schluesselwort ist, darf nicht angetastet
        werden."""
        result = self.cleaner.apply_title_cleanup_rules("(Extended Cut) Song")
        assert result == "(Extended Cut) Song"
