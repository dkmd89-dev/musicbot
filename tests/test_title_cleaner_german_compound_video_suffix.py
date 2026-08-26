"""
META-11 (entdeckt via Live-Test-Download am 2026-08-26, siehe
docs/MusicBot_METADATA_QUALITY_PHASE4_META11_AUDIT.md): sowohl
services/metadata/title_cleaner.py::TitleCleaner.light_title_cleanup()
als auch ::build_search_title() enthielten ein Pattern zum Entfernen des
englischen YouTube-Suffixes "(Official Music Video)" bzw. "Video", das
das Schluesselwort "video" OHNE Wortgrenze (\\b) davor matchte:

    r"\\s*\\(?\\s*(?:official\\s+)?(?:music\\s+)?video\\s*\\)?\\s*$"

Deutsche YouTube-Titel enthalten sehr haeufig das zusammengesetzte Wort
"Musikvideo" (kein Leerzeichen zwischen "Musik" und "video", im
Gegensatz zum englischen "Music Video"). Da "video" ohne \\b-Anker auch
als reiner Teilstring matcht, wurde bei "(Offizielles Musikvideo)" nur
das Suffix "video)" entfernt (Uebereinstimmung startete mitten im Wort
"Musikvideo") - das Ergebnis war ein truemmerhaft abgeschnittener,
unbalancierter Titel: "Weil ich dich liebe (Offizielles Musik" statt
"Weil ich dich liebe" (das komplette "(Offizielles Musikvideo)" haette
entfernt werden muessen).

Live reproduziert mit echtem YouTube-Download (Marius Mueller-
Westernhagen - "Weil ich dich liebe (Offizielles Musikvideo)") in der
isolierten Testumgebung (run_test_bot.py, /tmp/musicbot_test/): der
korrumpierte Titel landete unveraendert in Title-Tag, Album-Tag,
Dateiname UND im an MusicBrainz/Last.fm gesendeten Such-Titel.

Fix: \\b vor "video" (in beiden betroffenen Patterns je Funktion) sowie
vor "audio" (identische Pattern-Form, gleiche potenzielle Schwachstelle,
z.B. bei einem hypothetischen deutschen Kompositum) ergaenzt. \\b
verhindert ein Match innerhalb eines zusammengesetzten Wortes (zwischen
zwei Wortzeichen existiert keine Wortgrenze), aendert aber nichts am
bereits funktionierenden Fall mit echtem Leerzeichen/Klammer davor.
"""

from services.metadata.title_cleaner import TitleCleaner


class TestLightTitleCleanupGermanCompoundVideoSuffix:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_musikvideo_compound_word_is_fully_removed(self):
        """META-11-Kernfall, real via Live-Download reproduziert."""
        result = self.cleaner.light_title_cleanup(
            "Weil ich dich liebe (Offizielles Musikvideo)", "Westernhagen"
        )
        assert result == "Weil ich dich liebe"

    def test_no_dangling_bracket_or_word_fragment_remains(self):
        result = self.cleaner.light_title_cleanup(
            "Weil ich dich liebe (Offizielles Musikvideo)", "Westernhagen"
        )
        assert "(" not in result
        assert ")" not in result
        assert "Musik" not in result


class TestBuildSearchTitleGermanCompoundVideoSuffix:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_musikvideo_compound_word_is_fully_removed(self):
        result = self.cleaner.build_search_title(
            parsed_title="Weil ich dich liebe (Offizielles Musikvideo)",
            original_title=(
                "Westernhagen - Weil ich dich liebe (Offizielles Musikvideo)"
            ),
            final_artist="Westernhagen",
        )
        assert result == "Weil ich dich liebe"


class TestGermanCompoundVideoSuffixDoesNotOvercorrect:
    """Ueberkorrektur-Schutz: der bereits funktionierende Fall mit
    echtem Leerzeichen (Englisch) und die eigentliche Songtitel-
    Bedeutung duerfen nicht beschaedigt werden."""

    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_english_official_music_video_still_fully_removed(self):
        result = self.cleaner.light_title_cleanup(
            "Song Title (Official Music Video)", "Artist"
        )
        assert result == "Song Title"

    def test_bare_video_suffix_still_removed(self):
        result = self.cleaner.light_title_cleanup("Song Title Video", "Artist")
        assert result == "Song Title"

    def test_real_word_ending_in_video_substring_is_not_falsely_matched_mid_title(
        self,
    ):
        """Ein Titel, in dem 'video' zufaellig als Teilstring in einem
        laengeren Wort VOR dem eigentlichen Ende steht (nicht als
        Suffix), darf ohnehin nicht durch dieses Suffix-Pattern
        betroffen sein (Anker $ sorgt bereits dafuer) - hier zusaetzlich
        sichergestellt, dass das \\b davor keine neue Luecke oeffnet."""
        result = self.cleaner.light_title_cleanup(
            "Musikvideo Festival Highlights", "Artist"
        )
        assert result == "Musikvideo Festival Highlights"


class TestBuildSearchTitleGermanCompoundAudioSuffixParity:
    """Gleiche Pattern-Form wie 'video', gleiche potenzielle Schwachstelle
    - hier nur als Regressionsschutz, kein konkreter Live-Fall bekannt."""

    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_bare_audio_suffix_still_removed(self):
        result = self.cleaner.light_title_cleanup("Song Title (Audio)", "Artist")
        assert result == "Song Title"
