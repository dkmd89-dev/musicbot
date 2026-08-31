"""
META-02 (docs/archive/MusicBot_METADATA_QUALITY_PHASE0_AUDIT.md, Read-Only-Audit
vom 2026-08-26): services/metadata/title_cleaner.py::apply_title_cleanup_rules()
verlangte im feat/ft-Cleanup-Pattern nach dem optionalen Punkt zwingend
mindestens ein Leerzeichen (\\s+) - identische Wurzelursache wie META-01
(utils/youtube_parser.py) und wie das bereits gefixte DUP-04
(services/duplicate/detector.py). Ohne Leerzeichen nach dem Punkt
("feat.Someone") blieb der Featuring-Credit unveraendert im finalen,
getaggten Titel stehen statt entfernt zu werden.

Fix: dieselbe Alternation wie bei META-01/DUP-04 - nach "feat"/"ft"
entweder (a) ein Punkt gefolgt von optionalem Whitespace, oder (b)
mindestens ein Leerzeichen (ohne Punkt). "featuring" bleibt bei der
bisherigen Pflicht-Leerzeichen-Logik.

Nutzt dieselbe Teststruktur wie das bestehende
tests/test_metadata_modules.py (TestTitleCleaner) und denselben
Ueberkorrektur-Schutz-Fall ("Featherweight") wie
tests/test_duplicate_detector_feat_ft_normalization.py (DUP-04).
"""

from services.metadata.title_cleaner import TitleCleaner


class TestApplyTitleCleanupRulesFeatFtNoSpaceAfterDot:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_feat_dot_no_space_in_parens_is_removed(self):
        assert (
            self.cleaner.apply_title_cleanup_rules("Song (feat.Someone)") == "Song"
        )

    def test_ft_dot_no_space_in_parens_is_removed(self):
        assert self.cleaner.apply_title_cleanup_rules("Song (ft.Someone)") == "Song"

    def test_feat_dot_no_space_plain_is_removed(self):
        assert self.cleaner.apply_title_cleanup_rules("Song feat.Someone") == "Song"

    def test_existing_spaced_variant_still_works(self):
        """Regressionsschutz: die bereits vorher funktionierende,
        durch Leerzeichen getrennte Variante bleibt unveraendert
        (deckungsgleich mit test_clean_title_with_feat in
        tests/test_metadata_modules.py)."""
        assert (
            self.cleaner.apply_title_cleanup_rules("Song (feat. Someone)") == "Song"
        )


class TestApplyTitleCleanupRulesDoesNotOvercorrect:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_featherweight_mix_is_not_treated_as_featuring_credit(self):
        """Ueberkorrektur-Schutz (DUP-04-Pendant): 'Featherweight Mix'
        beginnt zufaellig mit 'Feat', ist aber kein Featuring-Credit -
        muss unangetastet bleiben."""
        result = self.cleaner.apply_title_cleanup_rules("Song (Featherweight Mix)")
        assert "Featherweight" in result

    def test_word_containing_ft_substring_is_not_mangled(self):
        """Regressionsschutz fuer ARTISTNORM-002 (siehe
        tests/test_metadata_modules.py::test_clean_title_with_ft_substring_word_is_not_mangled),
        muss auch nach der META-02-Aenderung weiterhin gelten."""
        result = self.cleaner.apply_title_cleanup_rules("Wir trafen Kraftklub gestern")
        assert result == "Wir trafen Kraftklub gestern"
