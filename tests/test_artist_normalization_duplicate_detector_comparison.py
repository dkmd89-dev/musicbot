"""
P0-E (docs/audits/P0_DUPLICATE_DETECTOR_AUDIT_2026-09-02.md): Vergleich der
Artist-Normalisierung zwischen der Metadaten-Pipeline (ArtistProcessor,
services/metadata/artist_processor.py) und der Duplicate-Detection
(DuplicateDetector._normalize_artist_for_comparison(),
services/duplicate/detector.py) - der seit Beginn der P0-Phase
zurueckgestellte strukturelle Punkt.

Kernbefund: DuplicateDetector.artist_normalizer bleibt in der echten
Produktion IMMER None. Der Grund: __init__ konstruiert ihn nur, wenn
`hasattr(config, "artist_config")` wahr ist
(services/duplicate/detector.py:94-98) - die reale config.Config besitzt
dieses Attribut nirgends im Repo (verifiziert per grep). Ausserdem waere
der Konstruktor-Aufruf selbst defekt (ArtistNormalizer(artist_config=...)
- _do_init() erwartet das Keyword "config", nicht "artist_config") - das
faellt aber nie auf, weil der Zweig nie erreicht wird UND ArtistNormalizer
ein SingletonMixin ist (ein spaeterer Fehlaufruf mit falschem Keyword auf
eine bereits andernorts korrekt konstruierte Instanz wird von
SingletonMixin.__init__() stillschweigend ignoriert).

Praktische Folge: DuplicateDetector normalisiert Artist-Namen IMMER ueber
ihre eigene, kurze String-Fallback-Liste
(" - Topic"/" VEVO"/" Official"-Suffixe, KEIN Komma-Split, KEIN
"Music"/"Records"-Suffix) statt ueber den echten, gemeinsam genutzten
ArtistNormalizer/ArtistProcessor-Pfad (VEVO/Topic/Official/Music/Records-
Suffixe UND Komma-Split fuer Multi-Artist-Strings). Diese Tests
dokumentieren die konkreten Faelle, in denen das auseinanderlaeuft, und
belegen mit einem Ende-zu-Ende-Szenario einen echten False-Negative in
check_for_duplicates() - siehe TestEndToEndFalseNegative.

Nutzt dieselbe FakeConfig-Struktur wie test_duplicate_detector_hash_
consistency.py (kein artist_config -> self.artist_normalizer bleibt None,
identisch zur echten Produktions-Config).
"""

from pathlib import Path
import tempfile

import pytest

from services.duplicate.detector import DuplicateDetector
from services.metadata.artist_processor import ArtistProcessor
from utils.artist_map import ArtistNormalizer, ArtistConfig
from utils.singleton import SingletonMixin


class FakeConfig:
    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")


@pytest.fixture
def handler(tmp_path):
    return DuplicateDetector(FakeConfig(tmp_path))


@pytest.fixture
def artist_processor(tmp_path):
    """
    Eigene, isolierte ArtistNormalizer-Instanz fuer den Vergleich - der
    Singleton-Cache wird davor geleert, damit dieser Test nicht von einer
    zufaellig bereits andernorts konstruierten Instanz abhaengt (siehe
    reset_singletons autouse-Fixture in conftest.py, die das ohnehin schon
    zwischen Tests tut - hier zusaetzlich explizit fuer Klarheit).
    """
    SingletonMixin._instances.clear()
    lib_dir = tmp_path / "artist_processor_library"
    lib_dir.mkdir()
    normalizer = ArtistNormalizer(
        ArtistConfig(library_dir=lib_dir, override_file=tmp_path / "overrides.json")
    )
    return ArtistProcessor(artist_normalizer=normalizer)


class TestDuplicateDetectorArtistNormalizerIsAlwaysNoneInProduction:
    """
    Grundlage fuer alle folgenden Vergleiche: bestaetigt, dass die reale
    Config keine artist_config setzt und DuplicateDetector deshalb immer
    auf die eigene String-Fallback-Normalisierung angewiesen ist.
    """

    def test_real_config_has_no_artist_config_attribute(self):
        from config import Config

        assert not hasattr(Config, "artist_config")

    def test_handler_artist_normalizer_is_none_with_production_like_config(
        self, handler
    ):
        assert handler.artist_normalizer is None


class TestNormalizationDivergence:
    """
    Konkrete Faelle, in denen DuplicateDetector._normalize_artist_for_
    comparison() (eigene, kurze Suffix-Liste) und der ArtistProcessor-Pfad
    (clean_artist_before_normalization() + ArtistNormalizer.normalize(),
    genau wie ihn die Metadaten-Pipeline fuer denselben Rohwert verwenden
    wuerde) unterschiedliche Ergebnisse liefern.
    """

    @staticmethod
    def _artist_processor_result(artist_processor, raw: str) -> str:
        cleaned = artist_processor.clean_artist_before_normalization(raw)
        if not cleaned:
            return "Unknown"
        return artist_processor.artist_normalizer.normalize(cleaned)

    @pytest.mark.parametrize(
        "raw,expected_shared_result",
        [
            ("Kygo - Topic", "Kygo"),
            ("Kygo VEVO", "Kygo"),
            ("Kygo Official", "Kygo"),
        ],
    )
    def test_topic_vevo_official_suffixes_agree(
        self, handler, artist_processor, raw, expected_shared_result
    ):
        """Gegenprobe: fuer die drei Suffixe, die DuplicateDetector explizit
        in seiner eigenen Liste hat, stimmen beide Pfade ueberein."""
        dd_result = handler._normalize_artist_for_comparison(raw)
        ap_result = self._artist_processor_result(artist_processor, raw)

        assert dd_result.lower() == expected_shared_result.lower()
        assert ap_result.lower() == expected_shared_result.lower()

    def test_music_suffix_diverges(self, handler, artist_processor):
        """
        DuplicateDetectors eigene Liste kennt nur " - Topic"/" VEVO"/
        " Official" - "Music" (das ArtistProcessor.
        clean_artist_before_normalization() sehr wohl entfernt, siehe P0-A/
        P0-D) fehlt. Realistisches Beispiel: viele YouTube-Kanaele von
        Labels/Artists tragen "... Music" im Namen.
        """
        raw = "SomeArtist Music"
        dd_result = handler._normalize_artist_for_comparison(raw)
        ap_result = self._artist_processor_result(artist_processor, raw)

        assert dd_result == "SomeArtist Music"  # unveraendert - Suffix nicht erkannt
        assert ap_result == "Someartist"  # Suffix entfernt + normalisiert
        assert dd_result.lower() != ap_result.lower()

    def test_records_suffix_diverges(self, handler, artist_processor):
        """Analog zu Music - "Records" fehlt ebenfalls in der eigenen
        Suffix-Liste von DuplicateDetector."""
        raw = "SomeArtist Records"
        dd_result = handler._normalize_artist_for_comparison(raw)
        ap_result = self._artist_processor_result(artist_processor, raw)

        assert dd_result == "SomeArtist Records"
        assert ap_result == "Someartist"
        assert dd_result.lower() != ap_result.lower()

    def test_comma_separated_multi_artist_diverges(self, handler, artist_processor):
        """
        ArtistProcessor.clean_artist_before_normalization() nimmt bei einem
        kommagetrennten Multi-Artist-String (z.B. ein kombinierter Upload-
        Kanalname fuer eine Kollaboration) nur den ersten Namen als
        Hauptartist. DuplicateDetector kennt diese Regel nicht (nur
        erreichbar, wenn self.artist_normalizer gesetzt waere - ist er in
        Produktion nie) und behaelt den kompletten String.
        """
        raw = "Artist One, Artist Two"
        dd_result = handler._normalize_artist_for_comparison(raw)
        ap_result = self._artist_processor_result(artist_processor, raw)

        assert dd_result == "Artist One, Artist Two"
        assert ap_result == "Artist One"
        assert dd_result.lower() != ap_result.lower()


class TestEndToEndFalseNegative:
    """
    Beweist die praktische Konsequenz der Divergenz an einem realistischen
    Ablauf: register_download() wird (wie in der echten Pipeline, siehe
    klassen/download_handler.py::handle_single_track_success()) mit dem
    bereits durch ArtistProcessor bereinigten Artist aufgerufen. Ein
    spaeterer Pre-Download-Check (wie
    klassen/download_handler.py::_probe_artist_title_for_duplicate_check())
    liefert dagegen den ROHEN YouTube-Uploader-/Channel-Namen, noch bevor
    die Pipeline ueberhaupt laeuft.
    """

    def test_reupload_via_music_suffixed_channel_is_not_detected_as_duplicate(
        self, handler
    ):
        """
        AKTUELLES (fehlerhaftes) Verhalten, live reproduziert: derselbe Song
        wird zunaechst unter dem bereits bereinigten Artist "Someartist"
        registriert. Ein Re-Upload/erneuter Download-Versuch desselben
        Songs, dessen YouTube-Kanal "SomeArtist Music" heisst, wird beim
        Pre-Download-Check NICHT als Duplikat erkannt - False Negative, weil
        DuplicateDetector den Suffix "Music" nicht kennt (siehe
        TestNormalizationDivergence.test_music_suffix_diverges).

        Dieser Test haelt den AKTUELLEN Bug-Zustand fest (Characterization),
        keine Fixture-Manipulation - die Assertion beschreibt bewusst das
        WEITERHIN unerwuenschte 'is_dup is False'. Wird der Fix (Suffix-
        Liste um Music/Records erweitern + Komma-Split ergaenzen)
        umgesetzt, MUSS dieser Test umgekehrt werden (is_dup wird dann True)
        - das ist beabsichtigt und im Audit-Dokument als offener Fix-
        Kandidat vermerkt.
        """
        handler.register_download(
            "https://www.youtube.com/watch?v=AAA111",
            "Someartist",
            "Cool Song",
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=BBB222",
            raw_artist="SomeArtist Music",
            raw_title="Cool Song",
        )

        assert is_dup is False
        assert reason == "none"
