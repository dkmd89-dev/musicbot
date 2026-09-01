import shutil
from pathlib import Path

import pytest
from config import Config


@pytest.fixture
def config():
    return Config()


@pytest.fixture(scope="session", autouse=True)
def _safe_config_defaults(tmp_path_factory):
    """
    Patcht Config.LIBRARY_DIR/ARTIST_OVERRIDE_FILE/GENRE_MAPPING_DIR
    session-weit auf sichere tmp-Pfade.

    Hintergrund: mehrere Produktionsklassen fallen bei fehlendem/
    unvollstaendigem injiziertem Config automatisch auf die ECHTE
    config.Config() zurueck (PlaylistProcessor.__init__,
    MusicBrainzClient._get_artist_normalizer(),
    EnhancedDownloadProcessor.__init__). ArtistNormalizer ist ein
    SingletonMixin und scannt bei der ERSTEN Konstruktion automatisch
    Config.LIBRARY_DIR und schreibt neu gefundene Artists synchron in
    Config.ARTIST_OVERRIDE_FILE (utils/artist_map.py::
    _update_overrides_from_library_async()) - unabhaengig davon, ob der
    aufrufende Test das ueberhaupt beabsichtigt hat.

    Dieser Mechanismus hat bereits zweimal real mapping/case_preserve.yaml
    verunreinigt (siehe ISOLATION-001-Kommentar in
    enhanced_metadata_processor.py und die Doku in
    tests/test_musicbrainz_client.py) und einmal real
    mapping/artist_overrides.json (zwei zusaetzliche Artist-Eintraege aus
    der echten Produktionsbibliothek, entdeckt und zurueckgesetzt waehrend
    der Arbeit an DOC-01/download_pipeline_stability). Eine gezielte
    Bisektion der Verdachtsdateien konnte die exakte ausloesende Testzeile
    nicht isolieren (vermutlich Interaktionseffekt) - dieser Fix schliesst
    daher den Mechanismus zentral, statt jede betroffene Stelle einzeln
    nachzuruesten (bereits das dritte Auftreten desselben Musters).

    LIBRARY_DIR zeigt auf ein LEERES tmp-Verzeichnis (verhindert jeden
    "neue Artists gelernt"-Schreibzugriff bereits dadurch, dass es nichts
    zu scannen gibt). GENRE_MAPPING_DIR zeigt auf eine KOPIE des echten
    mapping/-Verzeichnisses (nicht leer), damit Tests, die absichtlich
    echten Mapping-Inhalt lesen (z.B.
    test_genre_alias_characterization.py::Config().GENRE_MAPPING_DIR),
    unveraendert funktionieren - Schreibzugriffe landen dabei in der
    Kopie, nie in den echten Dateien.
    """
    real_mapping_dir = Path(__file__).resolve().parent.parent / "mapping"
    safe_mapping_dir = tmp_path_factory.mktemp("safe_config_mapping")
    shutil.copytree(real_mapping_dir, safe_mapping_dir, dirs_exist_ok=True)
    safe_library_dir = tmp_path_factory.mktemp("safe_config_library")

    mp = pytest.MonkeyPatch()
    mp.setattr(Config, "LIBRARY_DIR", safe_library_dir)
    mp.setattr(Config, "ARTIST_OVERRIDE_FILE", safe_mapping_dir / "artist_overrides.json")
    mp.setattr(Config, "GENRE_MAPPING_DIR", safe_mapping_dir)
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def reset_singletons():
    """
    Leert den SingletonMixin-Instanzcache vor und nach jedem Test.

    EnhancedMetadataProcessor, GenreMapper und FilenameFixerTool sind
    SingletonMixin-basiert (utils/singleton.py) und besitzen keinen eigenen
    Reset-Mechanismus. Ohne diesen Reset wuerde die erste in einem Testlauf
    konstruierte Instanz (z.B. mit einem tmp_path-Config) fuer alle
    nachfolgenden Tests weiterverwendet.
    """
    from utils.singleton import SingletonMixin

    SingletonMixin._instances.clear()
    yield
    SingletonMixin._instances.clear()


@pytest.fixture
def mapping_dir_copy(tmp_path):
    """
    Kopie des echten mapping/-Verzeichnisses in tmp_path.

    Fuer Tests, die reale Genre-/Artist-Mapping-Logik (GenreMapper,
    ArtistNormalizer, AutoLearnManager) mit Schreibzugriff ausueben sollen,
    ohne die echten YAML-Dateien im Repo zu veraendern (Regel 3: Mapping-
    Aenderungen wie Codeaenderungen behandeln, niemals als Testnebenwirkung).
    """
    real_mapping_dir = Path(__file__).resolve().parent.parent / "mapping"
    dest = tmp_path / "mapping"
    shutil.copytree(real_mapping_dir, dest)
    return dest


@pytest.fixture
def sample_track_metadata():
    """Minimaler track_metadata-Dict, wie er aus dem YouTube-Download kommt."""
    return {
        "title": "Testartist - Testsong (Official Video)",
        "uploader": "Testartist",
        "channel": "Testartist",
        "genre": "Hip Hop",
        "duration": 180,
        "webpage_url": "https://www.youtube.com/watch?v=TEST12345",
        "id": "TEST12345",
    }
