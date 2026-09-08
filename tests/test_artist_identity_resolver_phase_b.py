# -*- coding: utf-8 -*-
"""
ARCH — Artist Identity Resolution & Mapping Separation
=====================================================

PHASE B — Schritt 2 (ArtistIdentity) + Schritt 3/4 (ArtistIdentityResolver)
--------------------------------------------------------------------------

Testet die neuen, noch NICHT in die Pipeline verdrahteten Bausteine
isoliert:

  * services/metadata/models.py::ArtistIdentity
  * services/metadata/artist_identity_resolver.py::ArtistIdentityResolver

Verdrahtung in EnhancedMetadataProcessor folgt in Schritt 7/8 (weiterhin
Phase B), AutoLearn-Gate in Schritt 10, MetadataResult.artist_known in
Schritt 13.

Isolationsstruktur wie tests/test_artist_overrides_miksu_macloud_duo.py.
"""

import json

import pytest

from services.metadata.artist_identity_resolver import ArtistIdentityResolver
from services.metadata.models import ARTIST_IDENTITY_SOURCES, ArtistIdentity
from utils.artist_map import ArtistConfig, ArtistNormalizer


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def resolver_mapping_dir(tmp_path):
    """Gemeinsames mapping/-Verzeichnis: artist_overrides.json wird hier
    abgelegt (== ArtistNormalizer.config.override_file, so wie in Produktion
    Config.ARTIST_OVERRIDE_FILE == Config.GENRE_MAPPING_DIR/artist_overrides.json).
    known_artists.yaml / auto_learned_artist_aliases.json liegen ebenfalls hier."""
    d = tmp_path / "mapping"
    d.mkdir()
    return d


@pytest.fixture
def normalizer_factory(tmp_path, resolver_mapping_dir):
    def _make(library_names=(), overrides=None):
        lib = tmp_path / "norm_library"
        lib.mkdir(exist_ok=True)
        for name in library_names:
            (lib / name).mkdir(exist_ok=True)
        ovr = resolver_mapping_dir / "artist_overrides.json"
        if overrides is not None or not ovr.exists():
            ovr.write_text(json.dumps(overrides or {}), encoding="utf-8")
        return ArtistNormalizer(
            ArtistConfig(
                library_dir=lib,
                override_file=ovr,
                mapping_dir=resolver_mapping_dir,
            )
        )

    return _make


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════════════
# Schritt 2 — ArtistIdentity
# ═════════════════════════════════════════════════════════════════════════════


class TestArtistIdentity:
    def test_valid_construction(self):
        ident = ArtistIdentity(canonical="Ben Zucker", source="known_artist", known=True)
        assert ident.canonical == "Ben Zucker"
        assert ident.source == "known_artist"
        assert ident.known is True

    def test_all_documented_sources_accepted(self):
        for src in ARTIST_IDENTITY_SOURCES:
            known = src != "parser"
            ident = ArtistIdentity(canonical="X", source=src, known=known)
            assert ident.source == src

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            ArtistIdentity(canonical="X", source="channel_fallback", known=True)

    def test_parser_source_cannot_be_known(self):
        with pytest.raises(ValueError):
            ArtistIdentity(canonical="X", source="parser", known=True)

    def test_is_frozen(self):
        ident = ArtistIdentity(canonical="X", source="parser", known=False)
        with pytest.raises(Exception):
            ident.canonical = "Y"


# ═════════════════════════════════════════════════════════════════════════════
# Schritt 3/4 — ArtistIdentityResolver: einzelne Stufen
# ═════════════════════════════════════════════════════════════════════════════


class TestResolverTiers:
    def test_override_exact_key(self, normalizer_factory, resolver_mapping_dir):
        _write_json(
            resolver_mapping_dir / "artist_overrides.json", {"bausashaus": "Bausa"}
        )
        r = ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
        ident = r.resolve("bausashaus")
        assert ident == ArtistIdentity("Bausa", "artist_override", True)

    def test_override_normalized_key(self, normalizer_factory, resolver_mapping_dir):
        _write_json(
            resolver_mapping_dir / "artist_overrides.json",
            {"christina sturmer": "Christina Stürmer"},
        )
        r = ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
        ident = r.resolve("CHRISTINA STÜRMER")
        assert ident.canonical == "Christina Stürmer"
        assert ident.source == "artist_override"
        assert ident.known is True

    def test_override_value_match(self, normalizer_factory, resolver_mapping_dir):
        """Input entspricht bereits dem kanonischen Override-Wert."""
        _write_json(
            resolver_mapping_dir / "artist_overrides.json",
            {"miksu": "Miksu & Macloud"},
        )
        r = ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
        ident = r.resolve("Miksu & Macloud")
        assert ident.canonical == "Miksu & Macloud"
        assert ident.source == "artist_override"

    def test_known_artist_tier(self, normalizer_factory, resolver_mapping_dir):
        _write_json(resolver_mapping_dir / "artist_overrides.json", {})
        (resolver_mapping_dir / "known_artists.yaml").write_text(
            "known_artists:\n- Ben Zucker\n", encoding="utf-8"
        )
        r = ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
        ident = r.resolve("ben zucker")
        assert ident == ArtistIdentity("Ben Zucker", "known_artist", True)

    def test_auto_learned_alias_tier(self, normalizer_factory, resolver_mapping_dir):
        _write_json(resolver_mapping_dir / "artist_overrides.json", {})
        _write_json(
            resolver_mapping_dir / "auto_learned_artist_aliases.json",
            {"auto_learned": {"artistx alias": "Artist X"}},
        )
        r = ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
        ident = r.resolve("artistx alias")
        assert ident == ArtistIdentity("Artist X", "auto_learned_alias", True)

    def test_self_alias_is_ignored(self, normalizer_factory, resolver_mapping_dir):
        """Schritt 11: "X" → "X" ist kein Alias."""
        _write_json(resolver_mapping_dir / "artist_overrides.json", {})
        _write_json(
            resolver_mapping_dir / "auto_learned_artist_aliases.json",
            {"auto_learned": {"Solo Artist": "Solo Artist"}},
        )
        r = ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
        ident = r.resolve("Solo Artist")
        assert ident.source == "parser"
        assert ident.known is False

    def test_library_identity_tier(self, normalizer_factory, resolver_mapping_dir):
        _write_json(resolver_mapping_dir / "artist_overrides.json", {})
        r = ArtistIdentityResolver(
            normalizer_factory(library_names=["Clueso"]), resolver_mapping_dir
        )
        ident = r.resolve("clueso")
        assert ident == ArtistIdentity("Clueso", "library_identity", True)

    def test_unknown_falls_through_to_parser(
        self, normalizer_factory, resolver_mapping_dir
    ):
        _write_json(resolver_mapping_dir / "artist_overrides.json", {})
        r = ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
        ident = r.resolve("völlig neuer künstler")
        assert ident.source == "parser"
        assert ident.known is False
        # canonical = string-normalisierter Kandidat
        assert ident.canonical == "Völlig Neuer Künstler"

    def test_empty_name(self, normalizer_factory, resolver_mapping_dir):
        _write_json(resolver_mapping_dir / "artist_overrides.json", {})
        r = ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
        ident = r.resolve("   ")
        assert ident == ArtistIdentity("", "parser", False)


# ═════════════════════════════════════════════════════════════════════════════
# Schritt 3 — Priorität & Determinismus (Schritt 14)
# ═════════════════════════════════════════════════════════════════════════════


class TestResolverPriority:
    def test_override_beats_known_and_library(
        self, normalizer_factory, resolver_mapping_dir
    ):
        _write_json(
            resolver_mapping_dir / "artist_overrides.json", {"makko": "makko"}
        )
        (resolver_mapping_dir / "known_artists.yaml").write_text(
            "known_artists:\n- MAKKO\n", encoding="utf-8"
        )
        r = ArtistIdentityResolver(
            normalizer_factory(library_names=["MAKKO"]), resolver_mapping_dir
        )
        ident = r.resolve("makko")
        assert ident.source == "artist_override"
        assert ident.canonical == "makko"

    def test_known_beats_library(self, normalizer_factory, resolver_mapping_dir):
        _write_json(resolver_mapping_dir / "artist_overrides.json", {})
        (resolver_mapping_dir / "known_artists.yaml").write_text(
            "known_artists:\n- Clueso\n", encoding="utf-8"
        )
        r = ArtistIdentityResolver(
            normalizer_factory(library_names=["clueso"]), resolver_mapping_dir
        )
        ident = r.resolve("Clueso")
        assert ident.source == "known_artist"

    def test_deterministic_across_instances(
        self, normalizer_factory, resolver_mapping_dir
    ):
        _write_json(
            resolver_mapping_dir / "artist_overrides.json",
            {"a": "Canonical", "b": "Canonical", "canonical": "Canonical"},
        )
        idents = {
            ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
            .resolve("Canonical")
            for _ in range(5)
        }
        assert len(idents) == 1

    def test_stale_auto_generated_override_entry_still_reports_override(
        self, normalizer_factory, resolver_mapping_dir
    ):
        """Phase C: ein frueher automatisch erzeugter Self-Mapping-Eintrag in
        artist_overrides.json wird NICHT bereinigt (Bereinigung = Phase E) und
        meldet daher weiterhin source="artist_override". Beide (override /
        library_identity) liefern known=True, Gate identisch."""
        _write_json(
            resolver_mapping_dir / "artist_overrides.json", {"gustav": "Gustav"}
        )
        r = ArtistIdentityResolver(
            normalizer_factory(library_names=["Gustav"]), resolver_mapping_dir
        )
        ident = r.resolve("Gustav")
        assert ident.source == "artist_override"
        assert ident.known is True

    def test_library_only_reports_library_identity(
        self, normalizer_factory, resolver_mapping_dir
    ):
        """Phase C: Library-Ordner OHNE Eintrag in artist_overrides.json wird
        korrekt als source="library_identity" aufgelöst (vorher: der
        Normalizer haette den Ordner in die Datei geschrieben)."""
        _write_json(resolver_mapping_dir / "artist_overrides.json", {})
        r = ArtistIdentityResolver(
            normalizer_factory(library_names=["Gustav"]), resolver_mapping_dir
        )
        ident = r.resolve("Gustav")
        assert ident.source == "library_identity"
        assert ident.canonical == "Gustav"
        assert ident.known is True


# ═════════════════════════════════════════════════════════════════════════════
# Schritt 3 — refresh() / ctx / Ben-Zucker
# ═════════════════════════════════════════════════════════════════════════════


class TestResolverRefreshAndContext:
    def test_refresh_picks_up_new_known_artist(
        self, normalizer_factory, resolver_mapping_dir
    ):
        _write_json(resolver_mapping_dir / "artist_overrides.json", {})
        known_path = resolver_mapping_dir / "known_artists.yaml"
        known_path.write_text("known_artists: []\n", encoding="utf-8")
        r = ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
        assert r.resolve("Neuer Bekannter").known is False

        known_path.write_text(
            "known_artists:\n- Neuer Bekannter\n", encoding="utf-8"
        )
        r.refresh()
        ident = r.resolve("Neuer Bekannter")
        assert ident.source == "known_artist"
        assert ident.known is True

    def test_ctx_with_mbid_is_accepted_but_phase_f_inactive(
        self, normalizer_factory, resolver_mapping_dir
    ):
        _write_json(resolver_mapping_dir / "artist_overrides.json", {})
        r = ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
        ident = r.resolve(
            "Unbekannt",
            ctx={
                "artist_mbid": "8cb1685e-967d-4b32-8ba7-df94419aa004",
                "channel": "ICH FIND SCHLAGER TOLL",
                "uploader": "ICH FIND SCHLAGER TOLL",
            },
        )
        assert ident.source == "parser"
        assert ident.known is False

    def test_ben_zucker_unknown_mappings_is_parser(
        self, normalizer_factory, resolver_mapping_dir
    ):
        """Referenzfall bei sauberem Mapping-Zustand (nichts über Ben Zucker
        hinterlegt): canonical korrekt, aber known=False → AutoLearn dürfte
        laufen. Kanalname wird NICHT zur Identität."""
        _write_json(resolver_mapping_dir / "artist_overrides.json", {})
        r = ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
        ident = r.resolve(
            "Ben Zucker",
            ctx={"channel": "ICH FIND SCHLAGER TOLL"},
        )
        assert ident.canonical == "Ben Zucker"
        assert ident.source == "parser"
        assert ident.known is False

    def test_ben_zucker_known_after_registration(
        self, normalizer_factory, resolver_mapping_dir
    ):
        _write_json(resolver_mapping_dir / "artist_overrides.json", {})
        (resolver_mapping_dir / "known_artists.yaml").write_text(
            "known_artists:\n- Ben Zucker\n", encoding="utf-8"
        )
        r = ArtistIdentityResolver(normalizer_factory(), resolver_mapping_dir)
        ident = r.resolve("Ben Zucker")
        assert ident == ArtistIdentity("Ben Zucker", "known_artist", True)
