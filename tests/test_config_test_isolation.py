"""
TESTENV-01 (entdeckt via Live-Test-Download am 2026-08-26, siehe
docs/archive/MusicBot_TESTENV01_ISOLATION_AUDIT.md): config_test.py::Config
ueberschreibt zwar BASE_DIR auf /tmp/musicbot_test, viele davon
ABGELEITETE Pfade in der Basis-Config.py::Config-Klasse sind aber als
"BASE_DIR / '...'"-Ausdruecke direkt im Klassenkoerper der PRODUKTIONS-
Klasse definiert - Python wertet das einmalig bei der Definition dieser
Klasse aus, nicht dynamisch neu pro Subklasse. Da config_test.py::Config
diese abgeleiteten Attribute nie EINZELN neu setzt, erben sie unveraendert
die zur Produktionszeit berechneten absoluten Pfade unter
/mnt/128ssd/musicbot/ - die eingebaute Sicherheitspruefung
_verify_isolation() prueft nur LIBRARY_DIR und gibt dadurch falsche
Sicherheit.

Live reproduziert: ein Test-Download in der isolierten Testumgebung
(run_test_bot.py) hat dadurch tatsaechlich die ECHTE Produktions-
Duplicate-Cache (/mnt/128ssd/musicbot/cache/duplicate_cache/*.json) UND
die echten Mapping-Dateien (mapping/auto_learned_artists.yaml,
mapping/auto_learned_genre.yaml, da GENRE_MAPPING_DIR ebenfalls betroffen
ist) veraendert - eine Test-Aktion mit Seiteneffekt auf Produktionsdaten.

Betroffene, VOR dem Fix nicht isolierte Attribute: DUPLICATE_CACHE_DIR,
METADATA_CACHE_DIR, LYRICS_CACHE_DIR, DATA_DIR, ESCAPE_DIR,
ARTIST_OVERRIDE_FILE, ARTIST_OVERRIDE_EXPANDED_FILE, GENRE_MAPPING_DIR,
PLAY_HISTORY_FILE, TEMP_DIR, PROCESSED_DIR, FAIL_DIR, ARCHIVE_DIR.

Fix: config_test.py::Config ueberschreibt jetzt jedes dieser Attribute
einzeln (relativ zu seinem eigenen BASE_DIR), und _verify_isolation()
prueft ALLE davon statt nur LIBRARY_DIR.
"""

import config
import config_test


PRODUCTION_BASE_DIR = str(config.Config.BASE_DIR)

# Alle Pfad-/Datei-Attribute der Basis-Config, die von BASE_DIR abgeleitet
# sind (siehe config.py, Abschnitte "DIRECTORY STRUCTURE", "CACHE
# STRUCTURE", "MAPPING & HISTORY"). LIBRARY_DIR/PODCAST_DIR sind bewusst
# NICHT BASE_DIR-abgeleitet (eigene Absolutpfade in config.py) und daher
# hier nicht relevant.
BASE_DIR_DERIVED_ATTRS = [
    "DOWNLOAD_DIR",
    "TEMP_DIR",
    "PROCESSED_DIR",
    "FAIL_DIR",
    "ARCHIVE_DIR",
    "DATA_DIR",
    "ESCAPE_DIR",
    "METADATA_CACHE_DIR",
    "DUPLICATE_CACHE_DIR",
    "LYRICS_CACHE_DIR",
    "LOG_DIR",
    "LOG_FILE",
    "ARTIST_OVERRIDE_FILE",
    "ARTIST_OVERRIDE_EXPANDED_FILE",
    "GENRE_MAPPING_DIR",
    "PLAY_HISTORY_FILE",
]


class TestAllBaseDirDerivedPathsAreIsolatedFromProduction:
    def test_no_base_dir_derived_attribute_points_at_production(self):
        leaking = [
            attr
            for attr in BASE_DIR_DERIVED_ATTRS
            if str(getattr(config_test.Config, attr)).startswith(
                PRODUCTION_BASE_DIR
            )
        ]
        assert leaking == [], (
            f"Diese Attribute zeigen trotz Test-Config auf die echte "
            f"Produktion ({PRODUCTION_BASE_DIR}): {leaking}"
        )

    def test_duplicate_cache_dir_is_isolated(self):
        """META-04/TESTENV-01-Kernfall: real polluted die Produktions-
        Duplicate-Cache durch einen Test-Download."""
        assert not str(config_test.Config.DUPLICATE_CACHE_DIR).startswith(
            PRODUCTION_BASE_DIR
        )

    def test_genre_mapping_dir_is_isolated(self):
        """Erklaert, warum mapping/auto_learned_*.yaml durch den
        Test-Download beschrieben wurden."""
        assert not str(config_test.Config.GENRE_MAPPING_DIR).startswith(
            PRODUCTION_BASE_DIR
        )

    def test_isolated_paths_are_all_under_test_base_dir(self):
        for attr in BASE_DIR_DERIVED_ATTRS:
            value = str(getattr(config_test.Config, attr))
            assert value.startswith(str(config_test.Config.BASE_DIR)), (
                f"{attr} = {value!r} liegt nicht unter "
                f"{config_test.Config.BASE_DIR}"
            )


class TestVerifyIsolationCatchesAllLeaks:
    def test_verify_isolation_checks_more_than_just_library_dir(self):
        """Regressionsschutz: _verify_isolation() darf nicht wieder auf
        eine reine LIBRARY_DIR-Pruefung zurueckfallen - simuliert einen
        Leak in einem NICHT-LIBRARY_DIR-Attribut und erwartet, dass die
        Pruefung ihn erkennt."""
        import importlib

        original = config_test.Config.DUPLICATE_CACHE_DIR
        try:
            config_test.Config.DUPLICATE_CACHE_DIR = config.Config.DUPLICATE_CACHE_DIR
            raised = False
            try:
                config_test._verify_isolation()
            except RuntimeError:
                raised = True
            assert raised, (
                "_verify_isolation() haette einen Leak in "
                "DUPLICATE_CACHE_DIR erkennen muessen"
            )
        finally:
            config_test.Config.DUPLICATE_CACHE_DIR = original
