# -*- coding: utf-8 -*-
"""
ARCH — Artist Identity Resolution & Mapping Separation
=====================================================

PHASE A — Characterization (Sicherheitsnetz VOR der Migration)
-------------------------------------------------------------

Dieser Test dokumentiert das **aktuelle** (Pre-Migration-)Verhalten der
Artist-Identity-/Mapping-Auflösung, wie es der Audit (Findings F-01…F-07)
festgestellt hat. Er ändert **keinen** Produktionscode und behauptet
**nicht**, dass das hier festgehaltene Verhalten wünschenswert ist — er
friert es lediglich ein, damit jede folgende Migrationsphase (B–G)
nachweisbar nur das ändert, was sie ändern soll.

Leitsatz CLAUDE.md §3.A:  Characterize → Decide → Extract → Audit → Regression.
Dies ist der *Characterize*-Schritt.

Jede Testgruppe nennt die Phase, die das jeweilige Verhalten später
bewusst verändern wird. Wenn eine dieser Phasen umgesetzt ist, MUSS der
entsprechende Test hier angepasst werden (bewusste Verhaltensänderung,
nicht stillschweigende Regression).

Isolationsstruktur identisch zu
tests/test_artist_overrides_miksu_macloud_duo.py (tmp_path-Fixtures,
`reset_singletons`-autouse aus conftest.py leert den SingletonMixin-Cache).
"""

import json
from types import SimpleNamespace

import pytest

from services.metadata.artist_processor import ArtistProcessor
from services.metadata.models import ArtistIdentity
from utils.artist_map import ArtistConfig, ArtistNormalizer


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def library_dir(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    return lib


@pytest.fixture
def mapping_dir(tmp_path):
    d = tmp_path / "mapping"
    d.mkdir()
    return d


@pytest.fixture
def override_path(tmp_path):
    return tmp_path / "artist_overrides.json"


def _write_overrides(path, data: dict):
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_normalizer(library_dir, override_path, mapping_dir):
    return ArtistNormalizer(
        ArtistConfig(
            library_dir=library_dir,
            override_file=override_path,
            mapping_dir=mapping_dir,
        )
    )


# ═════════════════════════════════════════════════════════════════════════════
# GRUPPE 1 — ArtistProcessor.determine_best_artist():
#            Prioritätskette + KEINE Identity-/`known`-Information
#
# Wird geändert durch: Phase B (Resolver-Aufruf nach determine_best_artist),
#                      Phase D (normalize() wird String-only).
# ═════════════════════════════════════════════════════════════════════════════


class TestDetermineBestArtistPriorityChain_PreMigration:
    """§10 des Audits: `determine_best_artist()` liefert `(artist, source,
    feat)` — ein 3-Tupel OHNE `known`-Flag, ohne Identity-Auflösung."""

    @pytest.fixture
    def processor(self, library_dir, override_path, mapping_dir):
        _write_overrides(override_path, {})
        return ArtistProcessor(_make_normalizer(library_dir, override_path, mapping_dir))

    def test_return_shape_is_three_tuple_without_known_flag(self, processor):
        result = processor.determine_best_artist(
            raw_artist=None,
            parsed_artist="Some Artist",
            dominant_artist=None,
            channel_name="Some Channel",
        )
        assert isinstance(result, tuple)
        assert len(result) == 3
        artist, source, feat = result
        assert isinstance(artist, str)
        assert isinstance(source, str)
        assert isinstance(feat, list)

    def test_dominant_wins(self, processor):
        artist, source, _ = processor.determine_best_artist(
            raw_artist="Raw Artist",
            parsed_artist="Parsed Artist",
            dominant_artist="Dominant Artist",
            channel_name="Channel",
        )
        assert artist == "Dominant Artist"
        assert source == "playlist_dominant"

    def test_parsed_wins_over_raw_and_channel(self, processor):
        artist, source, _ = processor.determine_best_artist(
            raw_artist="Raw Artist",
            parsed_artist="Parsed Artist",
            dominant_artist=None,
            channel_name="Channel",
        )
        assert artist == "Parsed Artist"
        assert source == "youtube_parsed"

    def test_raw_wins_over_channel(self, processor):
        artist, source, _ = processor.determine_best_artist(
            raw_artist="Raw Artist",
            parsed_artist=None,
            dominant_artist=None,
            channel_name="Channel",
        )
        assert artist == "Raw Artist"
        assert source == "raw_metadata"

    def test_channel_is_last_fallback(self, processor):
        artist, source, _ = processor.determine_best_artist(
            raw_artist=None,
            parsed_artist=None,
            dominant_artist=None,
            channel_name="Channel Only",
        )
        assert artist == "Channel Only"
        assert source == "channel_fallback"

    def test_ben_zucker_parsed_beats_repost_channel(self, processor):
        """Der Audit-Referenzfall: Parser-Artist 'Ben Zucker' gewinnt gegen
        den Repost-Kanal 'ICH FIND SCHLAGER TOLL'. Kanalname wird NICHT zur
        Artist-Identität. `source` ist die Rohnamen-Herkunft, kein
        Identity-Signal."""
        artist, source, _ = processor.determine_best_artist(
            raw_artist=None,
            parsed_artist="Ben Zucker",
            dominant_artist=None,
            channel_name="ICH FIND SCHLAGER TOLL",
        )
        assert artist == "Ben Zucker"
        assert source == "youtube_parsed"


# ═════════════════════════════════════════════════════════════════════════════
# GRUPPE 2 — ArtistNormalizer.normalize() = REINE String-Normalisierung
#
# STAND NACH PHASE D+E (Schritt 6 + 19):
#   - normalize() macht KEINEN Override-/Alias-Lookup mehr.
#   - _check_overrides() wurde in Phase E entfernt (0 Produktions-Aufrufer).
#   - Override-/Alias-/known_artists-/Library-Auflösung: ArtistIdentityResolver.
#
# Vorher (Pre-Migration): normalize() löste Overrides/Aliase als erster
# Schritt auf.
# ═════════════════════════════════════════════════════════════════════════════


def _make_resolver(normalizer, mapping_dir):
    from services.metadata.artist_identity_resolver import ArtistIdentityResolver

    return ArtistIdentityResolver(normalizer, mapping_dir)


class TestNormalizeIsPureStringNormalisation_PhaseD:
    def test_manual_override_not_applied_by_normalize_but_by_resolver(
        self, library_dir, override_path, mapping_dir
    ):
        # "xyzkuenstler" ist bewusst KEIN in _compile_patterns hartkodierter
        # Korrektur-Sonderfall (anders als z.B. "Bausashaus"->"Bausa").
        _write_overrides(override_path, {"xyzkuenstler": "XYZ Künstler"})
        n = _make_normalizer(library_dir, override_path, mapping_dir)
        # normalize(): reine String-Normalisierung, KEIN Override
        assert n.normalize("xyzkuenstler") == "Xyzkuenstler"
        # Resolver: Override-Auflösung + Quelle
        ident = _make_resolver(n, mapping_dir).resolve("xyzkuenstler")
        assert ident.canonical == "XYZ Künstler"
        assert ident.source == "artist_override"

    def test_accent_restoring_override_only_via_resolver(
        self, library_dir, override_path, mapping_dir
    ):
        _write_overrides(override_path, {"christina sturmer": "Christina Stürmer"})
        n = _make_normalizer(library_dir, override_path, mapping_dir)
        # normalize() fügt keine Akzente hinzu
        assert n.normalize("CHRISTINA STURMER") == "Christina Sturmer"
        assert (
            _make_resolver(n, mapping_dir).resolve("christina sturmer").canonical
            == "Christina Stürmer"
        )

    def test_auto_learned_alias_only_via_resolver(
        self, library_dir, override_path, mapping_dir
    ):
        _write_overrides(override_path, {})
        (mapping_dir / "auto_learned_artist_aliases.json").write_text(
            json.dumps({"auto_learned": {"artistx alias": "Artist X"}}),
            encoding="utf-8",
        )
        n = _make_normalizer(library_dir, override_path, mapping_dir)
        assert n.normalize("artistx alias") == "Artistx Alias"
        ident = _make_resolver(n, mapping_dir).resolve("artistx alias")
        assert ident == ArtistIdentity("Artist X", "auto_learned_alias", True)

    def test_manual_override_beats_auto_learned_alias_in_resolver(
        self, library_dir, override_path, mapping_dir
    ):
        _write_overrides(override_path, {"foo": "Manual Foo"})
        (mapping_dir / "auto_learned_artist_aliases.json").write_text(
            json.dumps({"auto_learned": {"foo": "Auto Foo"}}), encoding="utf-8"
        )
        n = _make_normalizer(library_dir, override_path, mapping_dir)
        ident = _make_resolver(n, mapping_dir).resolve("foo")
        assert ident.canonical == "Manual Foo"
        assert ident.source == "artist_override"

    def test_plain_name_string_normalisation_unchanged(
        self, library_dir, override_path, mapping_dir
    ):
        _write_overrides(override_path, {})
        n = _make_normalizer(library_dir, override_path, mapping_dir)
        assert n.normalize("ben zucker") == "Ben Zucker"

    def test_check_overrides_method_removed_in_phase_e(
        self, library_dir, override_path, mapping_dir
    ):
        _write_overrides(override_path, {"foo": "Bar"})
        n = _make_normalizer(library_dir, override_path, mapping_dir)
        # Phase E: die Methode ist entfernt …
        assert not hasattr(n, "_check_overrides")
        # … normalize() ist reine String-Normalisierung:
        assert n.normalize("foo") == "Foo"
        # … der Override wird ausschließlich vom Resolver aufgelöst:
        assert _make_resolver(n, mapping_dir).resolve("foo").canonical == "Bar"

    def test_normalize_return_type_is_plain_string(
        self, library_dir, override_path, mapping_dir
    ):
        _write_overrides(override_path, {"x": "X"})
        n = _make_normalizer(library_dir, override_path, mapping_dir)
        out = n.normalize("x")
        assert isinstance(out, str) and not isinstance(out, tuple)


class TestNormalizeDoesNotConsultKnownArtistsYaml_PreMigration:
    """F-03: known_artists.yaml wird von ArtistNormalizer weder geladen noch
    im normalize()-Pfad geprüft. Ein Eintrag NUR dort ändert nichts.

    Wird geändert durch: Phase B/D (known_artists.yaml wird echte
    Resolver-Lesequelle, Priorität 2)."""

    def test_entry_only_in_known_artists_yaml_does_not_affect_normalize(
        self, library_dir, override_path, mapping_dir
    ):
        _write_overrides(override_path, {})
        # known_artists.yaml enthält die autoritative Schreibweise "UFO361".
        # Würde die Datei als Identity-Quelle gelesen, müsste eine
        # Kleinschreibungs-Variante darauf abgebildet werden.
        (mapping_dir / "known_artists.yaml").write_text(
            "known_artists:\n- UFO361\n- Ben Zucker\n", encoding="utf-8"
        )
        n = _make_normalizer(library_dir, override_path, mapping_dir)

        # "Ben Zucker" ist nur wegen der reinen String-Normalisierung
        # "richtig", nicht wegen known_artists.yaml:
        assert n.normalize("Ben Zucker") == "Ben Zucker"
        # known_artists.yaml wird NICHT als Identity-Quelle konsultiert:
        # die autoritative Schreibweise "UFO361" wird NICHT wiederhergestellt.
        assert n.normalize("ufo361") == "Ufo361"
        # Der Normalizer hält die Datei nicht einmal im Speicher:
        assert not hasattr(n, "known_artists")


# ═════════════════════════════════════════════════════════════════════════════
# GRUPPE 3 — Library-Ordner ↔ artist_overrides.json
#
# STAND NACH PHASE C+D (Schritt 5+6, Finding F-05):
#   - Phase C: Library-Ordner werden NICHT mehr nach artist_overrides.json
#     persistiert.
#   - Phase D/E: der frühere in-memory-Spiegel in self.overrides und
#     _check_overrides()/_mirror_library_artists_in_overrides()/_save_overrides()
#     sind entfernt. Library-Identität ausschließlich über self.library_index
#     + ArtistIdentityResolver.
#
# Vorher (Pre-Migration): die bloße Konstruktion mutierte die Datei auf Platte.
# ═════════════════════════════════════════════════════════════════════════════


class TestLibraryArtistsNotPersistedIntoOverridesFile_PhaseC:
    def test_library_folder_is_NOT_written_into_override_file_on_init(
        self, tmp_path, mapping_dir
    ):
        lib = tmp_path / "library"
        lib.mkdir()
        (lib / "Some New Artist").mkdir()
        override_path = tmp_path / "artist_overrides.json"
        _write_overrides(override_path, {})

        _make_normalizer(lib, override_path, mapping_dir)

        # Phase C: die Datei auf der Platte bleibt unverändert.
        persisted = json.loads(override_path.read_text(encoding="utf-8"))
        assert persisted == {}

    def test_library_folder_resolves_via_resolver_not_normalize(
        self, tmp_path, mapping_dir
    ):
        lib = tmp_path / "library"
        lib.mkdir()
        (lib / "Gustav").mkdir()
        override_path = tmp_path / "artist_overrides.json"
        _write_overrides(override_path, {})

        n = _make_normalizer(lib, override_path, mapping_dir)
        # Phase D/E: kein in-memory-Spiegel, kein _check_overrides mehr:
        assert not hasattr(n, "_check_overrides")
        # normalize() bleibt reine String-Normalisierung:
        assert n.normalize("gustav") == "Gustav"
        # Identität kommt aus dem Resolver (library_identity):
        ident = _make_resolver(n, mapping_dir).resolve("gustav")
        assert ident.source == "library_identity"
        assert ident.canonical == "Gustav"
        # Datei auf Platte unverändert:
        assert json.loads(override_path.read_text(encoding="utf-8")) == {}

    def test_library_index_is_populated_and_refreshable(self, tmp_path, mapping_dir):
        lib = tmp_path / "library"
        lib.mkdir()
        (lib / "Gustav").mkdir()
        override_path = tmp_path / "artist_overrides.json"
        _write_overrides(override_path, {})

        n = _make_normalizer(lib, override_path, mapping_dir)
        assert n.library_index.get(n._normalize_key("Gustav")) == "Gustav"

        (lib / "Neuer Künstler").mkdir()
        n.refresh_library_index()
        assert n.library_index.get(n._normalize_key("Neuer Künstler")) == "Neuer Künstler"


# ═════════════════════════════════════════════════════════════════════════════
# GRUPPE 4 — AutoLearnManager._is_artist_known():
#            Post-Decision-Gate, liest known_artists.yaml / overrides /
#            library / aliases — NICHT Teil der Artist-Entscheidung.
#
# Wird geändert durch: Phase E (Known/Alias-Trennung; _is_artist_known()
#       ggf. durch Resolver ersetzt/DEPRECATE).
# ═════════════════════════════════════════════════════════════════════════════


class TestIsArtistKnownGate_PreMigration:
    @pytest.fixture
    def manager(self, library_dir, override_path, mapping_dir):
        from services.metadata.auto_learn import AutoLearnManager

        _write_overrides(override_path, {"badchieff": "Badchieff"})
        normalizer = _make_normalizer(library_dir, override_path, mapping_dir)
        cfg = SimpleNamespace(GENRE_MAPPING_DIR=mapping_dir)
        return AutoLearnManager(cfg, normalizer, genre_mapper=None)

    def test_known_via_known_artists_yaml(self, manager, mapping_dir):
        (mapping_dir / "known_artists.yaml").write_text(
            "known_artists:\n- Ben Zucker\n", encoding="utf-8"
        )
        assert manager._is_artist_known("Ben Zucker") is True

    def test_known_via_manual_override_value(self, manager):
        assert manager._is_artist_known("Badchieff") is True

    def test_unknown_when_absent_everywhere(self, manager):
        assert manager._is_artist_known("Nie Gesehener Künstler") is False

    def test_known_via_library_folder(self, tmp_path, mapping_dir):
        from services.metadata.auto_learn import AutoLearnManager

        lib = tmp_path / "library"
        lib.mkdir()
        (lib / "Clueso").mkdir()
        override_path = tmp_path / "artist_overrides.json"
        _write_overrides(override_path, {})
        normalizer = _make_normalizer(lib, override_path, mapping_dir)
        cfg = SimpleNamespace(GENRE_MAPPING_DIR=mapping_dir)
        manager = AutoLearnManager(cfg, normalizer, genre_mapper=None)
        assert manager._is_artist_known("Clueso") is True


# ═════════════════════════════════════════════════════════════════════════════
# GRUPPE 5 — DuplicateDetector teilt sich den normalize()-Pfad
#
# Wird berührt durch: Phase D (normalize()-Reduktion darf den Duplicate
#       Detector nicht unbeabsichtigt verändern → Regressionsanker).
# ═════════════════════════════════════════════════════════════════════════════


class TestDuplicateDetectorSharesNormalizePath_PreMigration:
    def test_override_applies_in_duplicate_comparison(self, tmp_path, mapping_dir):
        from services.duplicate.detector import DuplicateDetector

        lib = tmp_path / "library"
        lib.mkdir()
        override_path = tmp_path / "artist_overrides.json"
        _write_overrides(
            override_path,
            {"miksu": "Miksu & Macloud", "miksu / macloud": "Miksu & Macloud"},
        )
        cfg = SimpleNamespace(
            LIBRARY_DIR=lib,
            ARTIST_OVERRIDE_FILE=override_path,
            GENRE_MAPPING_DIR=mapping_dir,
            DUPLICATE_CACHE_DIR=tmp_path / "dupcache",
        )
        det = DuplicateDetector(cfg)
        assert det._normalize_artist_for_comparison("Miksu") == "Miksu & Macloud"
        assert (
            det._normalize_artist_for_comparison("Miksu / Macloud")
            == "Miksu & Macloud"
        )


# ═════════════════════════════════════════════════════════════════════════════
# GRUPPE 6 — EnhancedMetadataProcessor end-to-end (Artist-Identity)
#
# STAND NACH PHASE B (Schritt 8/10/13):
#   - artist_source stammt jetzt vom ArtistIdentityResolver (echte Quelle),
#     die pauschale Überschreibung mit "first_artist_from_title" ist ENTFERNT
#     (F-02 behoben).
#   - MetadataResult.artist_known ist gesetzt (F-01/Schritt 13).
#   - Repost-Kanal wird weiterhin nicht zur Artist-Identität.
#
# Vorher (Pre-Migration) galt hier: artist_source == "first_artist_from_title",
# kein artist_known-Feld. Bewusst geändert in Phase B.
#
# Wird weiter berührt durch: Phase C (library_identity-Label),
#                            Phase F (musicbrainz_mbid).
# ═════════════════════════════════════════════════════════════════════════════


class TestEnhancedMetadataProcessorArtistIdentity_PhaseB:
    @pytest.fixture
    def processor(self, tmp_path, mapping_dir_copy, monkeypatch):
        from utils.audio_enhancer import AudioEnhancer
        from services.metadata.enhanced_metadata_processor import (
            EnhancedMetadataProcessor,
        )

        cfg = SimpleNamespace(
            LIBRARY_DIR=tmp_path / "library",
            DOWNLOAD_DIR=tmp_path / "downloads",
            FAIL_DIR=tmp_path / "fail",
            PROCESSED_DIR=tmp_path / "processed",
            TEMP_DIR=tmp_path / "temp",
            LOG_DIR=tmp_path / "logs",
            GENRE_MAPPING_DIR=mapping_dir_copy,
            ARTIST_OVERRIDE_FILE=tmp_path / "artist_overrides.json",
            METADATA_CACHE_DIR=tmp_path / "metadata_cache",
            DUPLICATE_CACHE_DIR=tmp_path / "duplicate_cache",
            FANART_API_KEY=None,
        )
        monkeypatch.setattr(
            AudioEnhancer, "normalize_loudness", staticmethod(lambda *a, **kw: True)
        )
        proc = EnhancedMetadataProcessor(cfg)

        class _FakeExternal:
            async def fetch_metadata(self, *a, **kw):
                return {}

        proc._mb_client = _FakeExternal()
        proc._lfm_client = _FakeExternal()

        async def _no_lyrics(*a, **kw):
            return None, None

        async def _no_album(*a, **kw):
            return None

        monkeypatch.setattr(
            proc.lyrics_processor, "fetch_lyrics_with_fallback", _no_lyrics
        )
        monkeypatch.setattr(
            proc.album_processor, "fetch_album_from_musicbrainz", _no_album
        )
        return proc

    @pytest.fixture
    def filename_fixer(self, tmp_path, mapping_dir_copy):
        from utils.filenamefixer import FilenameFixerTool

        cfg = SimpleNamespace(
            LIBRARY_DIR=tmp_path / "library",
            DOWNLOAD_DIR=tmp_path / "downloads",
            FAIL_DIR=tmp_path / "fail",
            PROCESSED_DIR=tmp_path / "processed",
            TEMP_DIR=tmp_path / "temp",
            LOG_DIR=tmp_path / "logs",
            GENRE_MAPPING_DIR=mapping_dir_copy,
        )
        return FilenameFixerTool(cfg)

    def _run_ben_zucker(self, processor, filename_fixer, tmp_path):
        import asyncio

        source = tmp_path / "benzucker.mp3"
        source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

        track_metadata = {
            "title": "Ben Zucker - Na und?! (Offizielles Musikvideo)",
            "artist": "ICH FIND SCHLAGER TOLL",
            "uploader": "ICH FIND SCHLAGER TOLL",
            "channel": "ICH FIND SCHLAGER TOLL",
            "id": "kAsAoyaqh1Y",
            "filepath": str(source),
            "cover_art": b"fake-cover-bytes",
            "genre": "Schlager",
        }
        return asyncio.run(
            processor.process_single_track(
                track_metadata=track_metadata, filename_fixer=filename_fixer
            )
        )

    def test_ben_zucker_channel_not_used_and_identity_resolved(
        self, processor, filename_fixer, tmp_path
    ):
        result = self._run_ben_zucker(processor, filename_fixer, tmp_path)

        assert result.success is True
        # Kanalname wird NICHT zur Artist-Identität:
        assert result.artist == "Ben Zucker"
        # Phase B: keine pauschale "first_artist_from_title"-Überschreibung mehr.
        assert result.artist_source != "first_artist_from_title"
        # Ben Zucker ist in der (frischen) Test-mapping-Kopie nirgends
        # hinterlegt → Resolver übernimmt den Parser-Kandidaten:
        assert result.artist_source == "parser"
        # Phase B / Schritt 13: artist_known ist jetzt gesetzt.
        assert result.artist_known is False

    def test_ben_zucker_known_artist_yields_known_source(
        self, processor, filename_fixer, tmp_path
    ):
        """Ist Ben Zucker vorab in known_artists.yaml registriert, meldet die
        Pipeline die echte Identity-Quelle und known=True (→ kein AutoLearn)."""
        known = processor.artist_identity_resolver._mapping_dir / "known_artists.yaml"
        existing = known.read_text(encoding="utf-8") if known.exists() else "known_artists:\n"
        known.write_text(existing + "- Ben Zucker\n", encoding="utf-8")
        processor.artist_identity_resolver.refresh()

        result = self._run_ben_zucker(processor, filename_fixer, tmp_path)

        assert result.artist == "Ben Zucker"
        assert result.artist_source == "known_artist"
        assert result.artist_known is True
