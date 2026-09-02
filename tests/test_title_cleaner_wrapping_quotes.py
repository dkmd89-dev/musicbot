"""
Live-Fund 2026-09-02 (Nutzer-Report, systematischer Scan von
/tmp/musicbot_test/metadaten nach weiteren ungueltigen Symbolen, im
Anschluss an den Produzenten-Credit-Fund fuer denselben Artist "makko"):
7 von 13 gescannten Tracks des Artists "makko" haben einen Titel, der
vollstaendig von Anfuehrungszeichen umschlossen ist -
'"ADLIBS"'/'"Bequem"'/'"Grad mal ein Jahr"'/'"Dein Lügner"'/'"Pueblo"'/
'"Ausreden"'/'"Jänner"'/'"Zickzack"' - offenbar eine YouTube-seitige
Stilisierung dieses Artists. Die Zeichen selbst wurden von
light_title_cleanup() bisher nie entfernt und landeten unveraendert im
Titel-/Album-Tag.

Der komplette /tmp/musicbot_test/metadaten-Bestand (13 Dateien, 2 Artists)
wurde zusaetzlich auf sonstige verdaechtige Unicode-Kategorien gescannt
(Symbole, ungewoehnliche Interpunktion) - kein weiterer echter Fund. Zum
Vergleich auch gegen /tmp/musicbot_test/library (114 Dateien) verifiziert:
ein Stern-Symbol in "Superst✩rs" (01099) ist eine bewusste kuenstlerische
Stilisierung (auch im Dateinamen identisch vorhanden), kein Bereinigungs-
fall - wird hier als Sicherheitsfall explizit mitgetestet.

Fix: entfernt genau EIN Anfuehrungszeichen-Paar, das den GESAMTEN
(bereits um Produzenten-Credits bereinigten) Titel umschliesst - Start
UND Ende. Deckt gerade sowie gaengige typografische Varianten
(deutsch/franzoesisch/englisch) ab. Ein einzelnes Apostroph MITTEN im
Titel (z.B. "It Ain't Me", "als ob ich's einfach hätte" - beide real in
der Library bestaetigt) bleibt unangetastet, da es nicht gleichzeitig am
Anfang UND Ende des Titels steht.
"""

from services.metadata.title_cleaner import TitleCleaner


class TestLightTitleCleanupWrappingQuotes:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_straight_double_quotes_removed(self):
        """Kernfall, real in der Library bestaetigt (7 Tracks)."""
        assert self.cleaner.light_title_cleanup('"ADLIBS"', "makko") == "ADLIBS"
        assert self.cleaner.light_title_cleanup('"Bequem"', "makko") == "Bequem"
        assert (
            self.cleaner.light_title_cleanup('"Grad mal ein Jahr"', "makko")
            == "Grad mal ein Jahr"
        )
        assert (
            self.cleaner.light_title_cleanup('"Dein Lügner"', "makko")
            == "Dein Lügner"
        )

    def test_combines_correctly_with_producer_credit_removal(self):
        """Die Anfuehrungszeichen werden erst NACH der Produzenten-Credit-
        Entfernung sichtbar - Reihenfolge-kritischer Fall, real via
        Live-Redownload reproduziert."""
        result = self.cleaner.light_title_cleanup(
            '"ADLIBS" prod. Safecall777', "makko"
        )
        assert result == "ADLIBS"

    def test_typographic_quote_variants_removed(self):
        assert self.cleaner.light_title_cleanup("„Song“", "Artist") == "Song"
        assert self.cleaner.light_title_cleanup("«Song»", "Artist") == "Song"
        assert self.cleaner.light_title_cleanup("‹Song›", "Artist") == "Song"
        assert self.cleaner.light_title_cleanup("‘Song’", "Artist") == "Song"
        assert self.cleaner.light_title_cleanup("“Song”", "Artist") == "Song"

    def test_title_without_quotes_unchanged(self):
        assert self.cleaner.light_title_cleanup("Blauer Tag", "Möwe") == "Blauer Tag"

    def test_apostrophe_mid_title_never_touched(self):
        """Sicherheitsfall: ein Apostroph MITTEN im Titel darf niemals als
        umschliessendes Anfuehrungszeichen-Paar fehlinterpretiert werden -
        beide Beispiele real in der Library bestaetigt."""
        assert (
            self.cleaner.light_title_cleanup("It Ain't Me", "Kygo")
            == "It Ain't Me"
        )
        assert (
            self.cleaner.light_title_cleanup(
                "als ob ich's einfach hätte", "Zartmann"
            )
            == "als ob ich's einfach hätte"
        )

    def test_trailing_question_mark_never_touched(self):
        """Sicherheitsfall: normale Interpunktion (kein Anfuehrungszeichen)
        bleibt unangetastet - real in der Library bestaetigt ('für immer?',
        Zartmann)."""
        assert self.cleaner.light_title_cleanup("für immer?", "Zartmann") == (
            "für immer?"
        )

    def test_artistic_stylized_symbol_never_touched(self):
        """Sicherheitsfall: ein bewusst kuenstlerisch stilisiertes Symbol
        (kein Anfuehrungszeichen) bleibt unangetastet - real in der
        Library bestaetigt ('Superst✩rs', 01099, auch im Dateinamen
        identisch vorhanden - keine Tag-Verunreinigung, sondern
        beabsichtigter Titel)."""
        assert (
            self.cleaner.light_title_cleanup("Superst✩rs", "01099")
            == "Superst✩rs"
        )

    def test_single_leading_or_trailing_quote_alone_not_stripped(self):
        """Nur ein VOLLSTAENDIGES, symmetrisches Paar wird entfernt - ein
        einzelnes fuehrendes oder abschliessendes Anfuehrungszeichen ohne
        Gegenstueck bleibt unangetastet (kein Rateverhalten)."""
        assert self.cleaner.light_title_cleanup('"Song', "Artist") == '"Song'
        assert self.cleaner.light_title_cleanup('Song"', "Artist") == 'Song"'
