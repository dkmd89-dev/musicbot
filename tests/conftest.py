import pytest
from config import Config


@pytest.fixture
def config():
    return Config()


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
