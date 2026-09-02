"""
Artist-Normalisierungs-Parität zwischen der Metadaten-Pipeline
(ArtistProcessor, services/metadata/artist_processor.py) und der
Duplicate-Detection (DuplicateDetector._normalize_artist_for_comparison(),
services/duplicate/detector.py).

Historie (der seit Beginn der P0-Phase zurueckgestellte strukturelle Punkt):

- P0-E (docs/audits/P0_DUPLICATE_DETECTOR_AUDIT_2026-09-02.md) fand: DuplicateDetector.
  artist_normalizer blieb in der echten Produktion IMMER None (config.Config
  besitzt nirgends ein artist_config-Attribut, das __init__ vorher fuer die
  ArtistNormalizer-Konstruktion voraussetzte). DuplicateDetector normalisierte
  Artist-Namen deshalb ausschliesslich ueber eine eigene, unvollstaendige
  String-Fallback-Liste - live reproduzierter False-Negative-Bug als Folge
  (siehe TestEndToEndRegression). P0-E erweiterte diese Fallback-Liste als
  Sofortmassnahme (Komma-Split, "Music"/"Records"-Suffixe).

- P1 (docs/audits/P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md)
  hat die eigentliche Ursache behoben: DuplicateDetector konstruiert jetzt
  denselben ArtistConfig/ArtistNormalizer wie EnhancedMetadataProcessor,
  UND haelt zusaetzlich einen echten ArtistProcessor, dessen
  clean_artist_before_normalization() vor jedem normalize()-Aufruf laeuft
  (waehrend der Extract-Phase entdeckt: ArtistNormalizer.normalize() entfernt
  Channel-Suffixe wie "- Topic" nicht selbststaendig - das ist exklusiv
  Aufgabe von clean_artist_before_normalization()). DuplicateDetector nutzt
  damit strukturell denselben Pfad wie die Metadaten-Pipeline, nicht nur
  zufaellig uebereinstimmende Ergebnisse. Die alte, eigene Suffix-Liste
  bleibt nur noch als Notfall-Fallback bestehen (siehe Kommentar in
  _normalize_artist_for_comparison()).

Diese Tests beweisen die Paritaet jetzt STRUKTURELL (zwei unabhaengig
konstruierte ArtistProcessor-Pipelines fuer denselben Rohwert), nicht mehr
nur fallweise wie in der urspruenglichen P0-E-Fassung dieser Datei.
"""

import shutil
from pathlib import Path

import pytest

from services.duplicate.detector import DuplicateDetector
from services.metadata.artist_processor import ArtistProcessor
from utils.artist_map import ArtistNormalizer, ArtistConfig
from utils.singleton import SingletonMixin


def _safe_mapping_dir_copy(tmp_path: Path) -> Path:
    """
    Isolierte Kopie des echten mapping/-Verzeichnisses. Ohne sie faellt
    ArtistNormalizer bei mapping_dir=None intern auf das echte, relative
    mapping/-Verzeichnis zurueck (ISOLATION-001-Muster, siehe conftest.py)
    und koennte echte Mapping-Dateien beschreiben (z.B. case_preserve.yaml
    Auto-Save) - live waehrend der P1-Extract-Phase dieser Datei selbst
    aufgetreten (siehe docs/audits/
    P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md).
    """
    mapping_dest = tmp_path / "mapping"
    if not mapping_dest.exists():
        shutil.copytree(
            Path(__file__).resolve().parent.parent / "mapping", mapping_dest
        )
    return mapping_dest


class FakeConfig:
    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")
        self.GENRE_MAPPING_DIR = _safe_mapping_dir_copy(tmp_path)


@pytest.fixture
def handler(tmp_path):
    return DuplicateDetector(FakeConfig(tmp_path))


@pytest.fixture
def artist_processor(tmp_path):
    """
    Zweite, unabhaengig konstruierte ArtistProcessor/ArtistNormalizer-
    Instanz (eigener tmp-Library-Pfad) fuer den Vergleich - der Singleton-
    Cache wird davor geleert, damit dies nachweislich NICHT dieselbe
    Objektinstanz wie handler.artist_processor ist (sonst waere der
    Vergleich tautologisch). Beweist Paritaet auf Code-Ebene (dieselbe
    Logik in clean_artist_before_normalization()/normalize()), nicht nur
    zufaellig geteilten Zustand.
    """
    SingletonMixin._instances.clear()
    lib_dir = tmp_path / "artist_processor_library"
    lib_dir.mkdir()
    normalizer = ArtistNormalizer(
        ArtistConfig(
            library_dir=lib_dir,
            override_file=tmp_path / "overrides.json",
            mapping_dir=_safe_mapping_dir_copy(tmp_path),
        )
    )
    return ArtistProcessor(artist_normalizer=normalizer)


class TestDuplicateDetectorArtistNormalizerIsNowWiredUp:
    """
    Grundlage fuer alle folgenden Vergleiche: bestaetigt den P1-Fix.
    self.artist_normalizer/self.artist_processor sind jetzt immer gesetzt -
    unconditional, ohne das fruehere hasattr(config, "artist_config")-Gate.
    """

    def test_real_config_still_has_no_artist_config_attribute(self):
        """
        Die reale config.Config hat weiterhin kein artist_config-Attribut -
        das war nie das Ziel. Der P1-Fix macht DuplicateDetector davon
        unabhaengig, statt das Attribut nachzuruesten.
        """
        from config import Config

        assert not hasattr(Config, "artist_config")

    def test_handler_artist_normalizer_and_artist_processor_are_wired_up(
        self, handler
    ):
        assert handler.artist_normalizer is not None
        assert handler.artist_processor is not None

    def test_singleton_construction_order_matches_real_bot_startup(self):
        """
        Live-Beleg fuer den in der P1-Charakterisierung dokumentierten
        Befund: in handlers/menu/rich_menu_handler.py wird DuplicateDetector
        VOR EnhancedMetadataProcessor konstruiert - DuplicateDetector ist
        damit im echten Bot-Start der erste Konstruktionsversuch des
        ArtistNormalizer-Singletons. Dieser Test bildet exakt diese
        Reihenfolge nach (Singleton-Cache vorher geleert) und stellt sicher,
        dass DuplicateDetector als "First Mover" korrekt funktioniert, statt
        sich implizit auf eine spaetere Korrektur durch
        EnhancedMetadataProcessor zu verlassen.
        """
        import tempfile

        SingletonMixin._instances.clear()
        tmp = Path(tempfile.mkdtemp())
        handler = DuplicateDetector(FakeConfig(tmp))

        assert handler.artist_normalizer is not None
        assert handler.artist_normalizer.normalize("Eminem") == "Eminem"


class TestNormalizationParity:
    """
    DuplicateDetector._normalize_artist_for_comparison() und der direkte
    ArtistProcessor-Pfad (clean_artist_before_normalization() +
    ArtistNormalizer.normalize(), wie ihn die Metadaten-Pipeline fuer
    denselben Rohwert verwendet) liefern nach dem P1-Fix fuer alle
    getesteten Faelle identische Ergebnisse - nicht mehr nur fuer die drei
    Faelle, die DuplicateDetector zufaellig in ihrer alten eigenen Liste
    hatte.
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
            ("SomeArtist Music", "Someartist"),
            ("SomeArtist Records", "Someartist"),
            ("Artist One, Artist Two", "Artist One"),
        ],
    )
    def test_dd_and_ap_agree_for_all_known_suffix_and_multi_artist_cases(
        self, handler, artist_processor, raw, expected_shared_result
    ):
        dd_result = handler._normalize_artist_for_comparison(raw)
        ap_result = self._artist_processor_result(artist_processor, raw)

        assert dd_result.lower() == expected_shared_result.lower()
        assert ap_result.lower() == expected_shared_result.lower()
        assert dd_result.lower() == ap_result.lower()


class TestEndToEndRegression:
    """
    Regressionsschutz fuer den urspruenglichen P0-E-Fund, jetzt durch die
    P1-Strukturkorrektur geloest: register_download() wird (wie in der
    echten Pipeline, siehe klassen/download_handler.py::
    handle_single_track_success()) mit dem bereits durch ArtistProcessor
    bereinigten Artist aufgerufen. Ein spaeterer Pre-Download-Check (wie
    klassen/download_handler.py::_probe_artist_title_for_duplicate_check())
    liefert dagegen den ROHEN YouTube-Uploader-/Channel-Namen, noch bevor
    die Pipeline ueberhaupt laeuft - muss trotzdem als Duplikat erkannt
    werden.
    """

    def test_reupload_via_music_suffixed_channel_is_detected_as_duplicate(
        self, handler
    ):
        """
        Pre-Fix-Diskriminierung (P0-E): dieser Test schlug am damals
        ungefixten Code nachweislich fehl (is_dup war False) - siehe
        docs/audits/P0_DUPLICATE_DETECTOR_AUDIT_2026-09-02.md. Blieb waehrend
        der P1-Extract-Phase zwischenzeitlich erneut rot (der reine
        ArtistNormalizer-Wiring-Fix ohne vorgeschaltetes
        clean_artist_before_normalization() reichte nicht aus, siehe
        docs/audits/P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md) -
        seit dem vollstaendigen P1-Fix dauerhaft gruen.
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

        assert is_dup is True
        assert reason == "content"

    def test_reupload_via_topic_suffixed_channel_is_detected_as_duplicate(
        self, handler
    ):
        """
        Zusaetzlicher P1-Regressionstest: "- Topic" war der Fall, an dem die
        Unvollstaendigkeit des reinen ArtistNormalizer-Wirings waehrend der
        Extract-Phase konkret auffiel (ArtistNormalizer.normalize() allein
        entfernt "- Topic" nicht) - deckt genau diesen Pfad jetzt explizit
        End-to-End ab.
        """
        handler.register_download(
            "https://www.youtube.com/watch?v=CCC333",
            "Someartist",
            "Cool Song",
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=DDD444",
            raw_artist="Someartist - Topic",
            raw_title="Cool Song",
        )

        assert is_dup is True
        assert reason == "content"
