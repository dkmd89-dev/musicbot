"""
Live-Fund 2026-09-02 (Nutzer-Report, echter Testdownload nach Loeschen
von Toobrokeforfiji aus der isolierten Test-Library):
utils/youtube_parser.py::parse_youtube_title() scheiterte an
'toobrokeforfiji, Sin Davis & makko  40 Stunden Woche prod. overshiaat
official video' - alle bestehenden Standard-Trennzeichen ("-", "|",
":", ...) griffen nicht, da YouTube hier die komplette Artist-Liste
("Artist1, Artist2 & Artist3") nur durch ein DOPPELTES Leerzeichen vom
eigentlichen Songtitel trennt. Der komplette String landete
unveraendert im "Kein Artist gefunden"-Fallback.

Zwei Loesungsversuche AN SPAETERER STELLE in der Pipeline scheiterten,
bevor die Root Cause hier korrekt lokalisiert wurde:
1. services/metadata/title_cleaner.py::light_title_cleanup() - das
   Doppel-Leerzeichen-Signal war zu diesem Zeitpunkt bereits durch
   parse_youtube_title()'s eigene Whitespace-Normalisierung verloren.
2. "Bekannte Feature-Artists als Parameter nutzen" - in genau diesem
   Fall sind die Feature-Artists nirgends in der Pipeline bereits
   bekannt, weil der Parser selbst am Erkennen scheiterte (das IST das
   Problem, das geloest werden soll).

Fix: Vorverarbeitungsschritt GANZ am Anfang von parse_youtube_title(),
auf dem noch unveraenderten Roh-Titel (vor jeder Klammer-/Whitespace-
Normalisierung) - ersetzt ein doppeltes Leerzeichen durch das bereits
unterstuetzte Standard-Trennzeichen " - ", wenn der linke Teil als
Multi-Artist-Liste erkennbar ist (>= 2 Namen via
_split_multi_artists()). Die bestehende, bereits gut getestete
Parsing-Pipeline (Klammer-Bereinigung, Feature-Extraktion,
Multi-Artist-Split, Confidence) laeuft danach unveraendert weiter.
"""

from utils.youtube_parser import parse_youtube_title


class TestParseYoutubeTitleDoubleSpaceMultiArtist:
    def test_three_artists_comma_and_ampersand(self):
        """Kernfall, real via Live-Testdownload reproduziert."""
        result = parse_youtube_title(
            "toobrokeforfiji, Sin Davis & makko  40 Stunden Woche prod. "
            "overshiaat official video"
        )
        assert result["artist"] == "toobrokeforfiji"
        assert result["all_artists"] == ["toobrokeforfiji", "Sin Davis", "makko"]
        assert result["song_title"] == (
            "40 Stunden Woche prod. overshiaat official video"
        )
        assert result["confidence"] == 1.0

    def test_two_artists_comma_only(self):
        result = parse_youtube_title("Ski Aggu, Sido  Party Sahne")
        assert result["artist"] == "Ski Aggu"
        assert result["all_artists"] == ["Ski Aggu", "Sido"]
        assert result["song_title"] == "Party Sahne"

    def test_original_title_preserved_unmodified(self):
        """original_title muss der echte, unveraenderte Rohtitel bleiben
        (inkl. Doppel-Leerzeichen) - nicht der intern umgeschriebene."""
        raw = "toobrokeforfiji, Sin Davis & makko  40 Stunden Woche"
        result = parse_youtube_title(raw)
        assert result["original_title"] == raw

    def test_full_pipeline_via_title_cleaner_produces_clean_title(self):
        """End-zu-End: song_title aus parse_youtube_title() an
        light_title_cleanup() weitergegeben ergibt den vollstaendig
        bereinigten Titel, ohne dass light_title_cleanup() selbst
        angepasst werden musste."""
        from services.metadata.title_cleaner import TitleCleaner

        result = parse_youtube_title(
            "toobrokeforfiji, Sin Davis & makko  40 Stunden Woche prod. "
            "overshiaat official video"
        )
        cleaned = TitleCleaner().light_title_cleanup(
            result["song_title"], "Toobrokeforfiji"
        )
        assert cleaned == "40 Stunden Woche"

    def test_single_name_before_double_space_untouched(self):
        """Sicherheitsfall: nur EIN Name vor dem doppelten Leerzeichen
        (keine erkennbare Multi-Artist-Liste) - loest das Muster NICHT
        aus, faellt weiterhin in den generischen Fallback."""
        result = parse_youtube_title("Toobrokeforfiji  40 Stunden Woche")
        assert result["artist"] is None

    def test_random_double_space_in_normal_title_untouched(self):
        """Sicherheitsfall: ein zufaelliges doppeltes Leerzeichen in
        einem normalen Songtitel ohne Komma-/&-Praefix darf nicht als
        Artist-Trenner missverstanden werden."""
        result = parse_youtube_title("Blauer  Tag")
        assert result["artist"] is None
        assert result["song_title"] == "Blauer Tag"

    def test_standard_dash_format_still_works(self):
        """Bestehender Normalfall bleibt durch den neuen, davor
        laufenden Vorverarbeitungsschritt unangetastet."""
        result = parse_youtube_title("Ariana Grande - 7 rings")
        assert result["artist"] == "Ariana Grande"
        assert result["song_title"] == "7 rings"

    def test_no_double_space_at_all_unchanged(self):
        result = parse_youtube_title("Peter Fox - Alles Neu")
        assert result["artist"] == "Peter Fox"
        assert result["song_title"] == "Alles Neu"
