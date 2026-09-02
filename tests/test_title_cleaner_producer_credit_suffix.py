"""
Live-Fund 2026-09-02 (Nutzer-Report, echter Testdownload in der isolierten
Testumgebung, Artist "makko", Track '"ADLIBS" prod. Safecall777'):
services/metadata/title_cleaner.py::TitleCleaner.light_title_cleanup()
enthielt keinerlei Regel zum Entfernen eines Produzenten-Credits.

light_title_cleanup() ist der einzige tatsaechlich erreichbare
Titel-Cleanup-Pfad der Produktions-Pipeline
(enhanced_metadata_processor.py, Schritt 7 "Bestimme finalen Titel", ruft
ausschliesslich diese Methode auf) - TitleCleaner.clean_track_title_
enhanced()/apply_title_cleanup_rules() haben repoweit verifiziert KEINE
Produktionsaufrufer (nur in eigenen Unit-Tests direkt aufgerufen, siehe
test_title_cleaner_feat_ft_no_space.py/test_title_cleaner_marketing_
suffix_bracket.py) und liefen fuer diesen Live-Download nie.

Real reproduziert: der Titel '"ADLIBS" prod. Safecall777' landete
unveraendert in Title-Tag, Album-Tag, Dateiname UND im an
MusicBrainz/Genius gesendeten Such-Titel. Auch der volle YouTube-Parser
(utils/youtube_parser.py::parse_youtube_title(), per Direktaufruf
verifiziert) haette diese klammerlose, trennerlose Form nicht erkannt -
dessen _clean_title_suffixes() deckt nur die geklammerte "(prod...)"-
oder Bindestrich-getrennte "- prod..."-Form ab (siehe
docs/FINDINGS_INDEX.md, dort separat als eigener Fund dokumentiert,
NICHT Teil dieses Fixes).

Fix: zwei neue Regeln in light_title_cleanup() - geklammerte Form
("(prod. by X)"/"(prod X)") und klammerlose/trennerlose Form am
Titelende ("Titel prod. X"). \\bprod\\b mit zwingendem "."/Whitespace
danach verhindert Fehltreffer in Woertern wie "Producer"/"Production".
"""

from services.metadata.title_cleaner import TitleCleaner


class TestLightTitleCleanupProducerCreditSuffix:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_bare_producer_credit_removed(self):
        """Kernfall, real via Live-Download reproduziert. Erwartetes
        Ergebnis inkl. Anfuehrungszeichen-Entfernung (Folge-Fund,
        siehe test_title_cleaner_wrapping_quotes.py) - die umschliessenden
        '"'-Zeichen werden erst NACH der Produzenten-Credit-Entfernung
        sichtbar/entfernbar."""
        result = self.cleaner.light_title_cleanup(
            '"ADLIBS" prod. Safecall777', "makko"
        )
        assert result == "ADLIBS"

    def test_parenthesized_producer_credit_removed(self):
        result = self.cleaner.light_title_cleanup(
            "Mama (prod. by Drumla)", "Zartmann"
        )
        assert result == "Mama"

    def test_parenthesized_producer_credit_without_dot_removed(self):
        result = self.cleaner.light_title_cleanup(
            "Mama (prod Drumla)", "Zartmann"
        )
        assert result == "Mama"

    def test_bare_producer_credit_with_by_removed(self):
        result = self.cleaner.light_title_cleanup(
            "Song prod. by Someone", "Artist"
        )
        assert result == "Song"

    def test_title_without_producer_credit_unchanged(self):
        result = self.cleaner.light_title_cleanup("Blauer Tag", "Möwe")
        assert result == "Blauer Tag"

    def test_producer_word_boundary_does_not_false_positive(self):
        """Sicherheitsfall: 'Producer'/'Production' als Teil eines echten
        Wortes duerfen nicht als Produzenten-Credit fehlinterpretiert
        werden (\\bprod\\b verlangt einen echten Wortabschluss direkt
        gefolgt von '.' oder Whitespace)."""
        assert (
            self.cleaner.light_title_cleanup("Producer's Dream", "Artist")
            == "Producer's Dream"
        )
        assert (
            self.cleaner.light_title_cleanup("Production Day", "Artist")
            == "Production Day"
        )

    def test_combines_correctly_with_existing_video_suffix_removal(self):
        """Beide Regelklassen (Video-Suffix + Produzenten-Credit) muessen
        in Kombination korrekt zusammenspielen, nicht nur isoliert."""
        result = self.cleaner.light_title_cleanup(
            'Song (prod. by X) (Official Video)', "Artist"
        )
        assert result == "Song"
