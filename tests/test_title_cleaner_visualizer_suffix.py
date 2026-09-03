"""
Live-Fund 2026-09-03 (Nutzer-Report, echter Testdownload in der isolierten
Testumgebung, Artist "Oimara" x "Max Giesinger", Track
'GROSSSTADT (Offizieller Visualizer)'):
services/metadata/title_cleaner.py::TitleCleaner.light_title_cleanup()
enthaelt Regeln fuer geklammerte "(...video...)"/"(...audio...)"-Suffixe
(META-11), aber KEINE Regel fuer "Visualizer" (ein separates, gaengiges
YouTube-Marketing-Suffix fuer Musikvideos mit statischem/animiertem
Hintergrund statt echtem Video-Content) - "Visualizer" enthaelt weder
"video" noch "audio" als eigenstaendiges Wort, das bestehende
`\\b(?:video|audio)\\b`-Wortmuster erfasst es daher nicht.

light_title_cleanup() ist der einzige tatsaechlich erreichbare
Titel-Cleanup-Pfad der Produktions-Pipeline fuer Title-/Album-Tag und
Dateinamen (siehe docs/FINDINGS_INDEX.md, mehrfach dokumentiert). Real
reproduziert: Title-Tag UND Album-Tag UND Dateiname behielten
"(Offizieller Visualizer)" unveraendert.

Zusaetzlich betroffen: TitleCleaner.build_search_title() (fuer die
Album-MusicBrainz-Suche, enhanced_metadata_processor.py:551 ->
AlbumProcessor.fetch_album_from_musicbrainz()) hat dasselbe fehlende
Wortmuster - im Unterschied zur Genre-MusicBrainz-/Last.fm-Suche (die
zusaetzlich durch genre_processor.py::_prepare_search_title() abgesichert
ist, welche bereits ein explizites "(visualizer)"-Pattern hat) liefe die
Album-Suche ohne diesen Fix weiterhin mit dem unbereinigten Suchtitel.

Fix: das bestehende `\\b(?:video|audio)\\b`-Wortmuster um "visualizer"
erweitert - an beiden betroffenen Stellen in title_cleaner.py (identisches
Pattern, siehe META-11-Kommentar dort).
"""

from services.metadata.title_cleaner import TitleCleaner


class TestLightTitleCleanupVisualizerSuffix:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_bare_visualizer_suffix_removed(self):
        """Kernfall, real via Live-Download reproduziert."""
        result = self.cleaner.light_title_cleanup(
            "GROSSSTADT (Offizieller Visualizer)", "Oimara"
        )
        assert result == "GROSSSTADT"

    def test_english_visualizer_suffix_removed(self):
        result = self.cleaner.light_title_cleanup(
            "Some Song (Official Visualizer)", "Artist"
        )
        assert result == "Some Song"

    def test_bare_visualizer_without_official_removed(self):
        result = self.cleaner.light_title_cleanup(
            "Some Song (Visualizer)", "Artist"
        )
        assert result == "Some Song"

    def test_visualizer_video_combination_removed(self):
        """Sicherheitsfall: 'Visualizer Video' enthaelt bereits 'video' -
        muss auch ohne den Fix schon funktioniert haben (Regressionsschutz,
        nicht Teil des eigentlichen Bugs)."""
        result = self.cleaner.light_title_cleanup(
            "Some Song (Official Visualizer Video)", "Artist"
        )
        assert result == "Some Song"

    def test_unrelated_bracket_content_stays_untouched(self):
        """Sicherheitsfall: eine Klammer, die weder 'video'/'audio' noch
        'visualizer' enthaelt, bleibt unangetastet (kein Overreach)."""
        result = self.cleaner.light_title_cleanup(
            "Some Song (Remix)", "Artist"
        )
        assert result == "Some Song (Remix)"


class TestBuildSearchTitleVisualizerSuffix:
    def setup_method(self):
        self.cleaner = TitleCleaner()

    def test_visualizer_suffix_removed_for_album_search(self):
        """Album-MusicBrainz-Suche (enhanced_metadata_processor.py:551)
        nutzt build_search_title() direkt, OHNE die zusaetzliche
        _prepare_search_title()-Absicherung der Genre-Suche - muss daher
        selbst korrekt bereinigen."""
        result = self.cleaner.build_search_title(
            "GROSSSTADT (Offizieller Visualizer)",
            "GROSSSTADT (Offizieller Visualizer)",
            "Oimara",
        )
        assert result == "GROSSSTADT"
