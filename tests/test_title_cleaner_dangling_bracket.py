"""
Live-Fund 2026-09-02 (Nutzer-Report, echter Testlauf Artist "makko"):
services/metadata/title_cleaner.py::TitleCleaner.light_title_cleanup()
liess einen Titel mit einer nie geschlossenen Klammer unveraendert
stehen: 'MAKKO 7er STOCK (Dir.' blieb 'MAKKO 7er STOCK (Dir.' statt zu
'MAKKO 7er STOCK' bereinigt zu werden - vermutlich ein abgeschnittener
Regie-/Video-Credit ('(Dir. by X)'), dessen schliessende Klammer im
YouTube-Titel fehlt.

Dasselbe Muster existierte bereits als letztes Sicherheitsnetz in
TitleCleaner.apply_title_cleanup_rules() (r"\\s*\\([^)]*$", "") -
diese Methode hat aber repoweit verifiziert keine Produktionsaufrufer
(siehe test_title_cleaner_producer_credit_suffix.py) und lief fuer
diesen Titel nie. light_title_cleanup() hatte bisher keine
entsprechende Regel.

Fix: dieselbe, bereits etablierte Regel (nie geschlossene '(' bzw. '['
bis Titelende entfernen) als letzte Regel in light_title_cleanup()
ergaenzt - faengt auf, was von allen vorherigen, spezifischeren Regeln
uebrig bleibt. Balancierte Klammern (mit echtem schliessenden
Gegenstueck, z.B. "(feat. X)", "[Remix]") bleiben unangetastet.
"""

from services.metadata.title_cleaner import TitleCleaner


class TestLightTitleCleanupDanglingBracket:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_dangling_open_paren_removed(self):
        """Kernfall, real via Live-Testlauf reproduziert."""
        result = self.cleaner.light_title_cleanup(
            "MAKKO 7er STOCK (Dir.", "makko"
        )
        assert result == "MAKKO 7er STOCK"

    def test_dangling_open_bracket_removed(self):
        result = self.cleaner.light_title_cleanup("Song [Remix by", "Artist")
        assert result == "Song"

    def test_balanced_parentheses_untouched(self):
        """Sicherheitsfall: eine ECHTE, geschlossene Klammer darf nicht
        angefasst werden."""
        result = self.cleaner.light_title_cleanup("Song (feat. X)", "Artist")
        assert result == "Song (feat. X)"

    def test_balanced_brackets_untouched(self):
        result = self.cleaner.light_title_cleanup("Song [Remix]", "Artist")
        assert result == "Song [Remix]"

    def test_title_without_brackets_unchanged(self):
        result = self.cleaner.light_title_cleanup("Blauer Tag", "Möwe")
        assert result == "Blauer Tag"

    def test_combines_correctly_with_producer_credit_and_quote_rules(self):
        """Zusammenspiel mit den bereits bestehenden Regeln (Reihenfolge-
        kritisch, siehe Kommentare in light_title_cleanup())."""
        result = self.cleaner.light_title_cleanup(
            'Song (prod. by X) (Official Video)', "Artist"
        )
        assert result == "Song"
