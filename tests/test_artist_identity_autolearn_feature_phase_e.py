# -*- coding: utf-8 -*-
"""
ARCH — Artist Identity Resolution & Mapping Separation
=====================================================

PHASE E — Schritt 11: Feature-Artist-Kanonikalisierung + Known-Check über den
ArtistIdentityResolver (statt nur ArtistNormalizer.normalize() +
_is_artist_known()-Dateiscan).
"""

import json

import pytest

from services.metadata.artist_identity_resolver import ArtistIdentityResolver
from services.metadata.auto_learn import AutoLearnManager
from utils.artist_map import ArtistConfig, ArtistNormalizer


@pytest.fixture
def mapping_dir(tmp_path):
    d = tmp_path / "mapping"
    d.mkdir()
    return d


@pytest.fixture
def normalizer(tmp_path, mapping_dir):
    lib = tmp_path / "library"
    lib.mkdir()
    ovr = mapping_dir / "artist_overrides.json"
    ovr.write_text(json.dumps({"bausashaus": "Bausa"}), encoding="utf-8")
    return ArtistNormalizer(
        ArtistConfig(library_dir=lib, override_file=ovr, mapping_dir=mapping_dir)
    )


@pytest.fixture
def resolver(normalizer, mapping_dir):
    return ArtistIdentityResolver(normalizer, mapping_dir)


def _manager(config_stub, normalizer, resolver=None):
    return AutoLearnManager(
        config_stub, normalizer, genre_mapper=None, artist_identity_resolver=resolver
    )


@pytest.fixture
def config_stub(mapping_dir):
    from types import SimpleNamespace

    return SimpleNamespace(GENRE_MAPPING_DIR=mapping_dir)


class TestFeaturedArtistUsesResolver:
    def test_alias_feature_is_canonicalised_and_skipped_as_known(
        self, config_stub, normalizer, resolver
    ):
        mgr = _manager(config_stub, normalizer, resolver)
        decision = mgr._compute_featured_artist_decision(
            primary_artist="Some Primary",
            raw_feat="bausashaus",
            track_context="ctx",
        )
        assert decision["canonical"] == "Bausa"
        assert decision["decision"] == "SKIPPED_KNOWN"

    def test_unknown_feature_would_be_learned_with_resolver_canonical(
        self, config_stub, normalizer, resolver
    ):
        mgr = _manager(config_stub, normalizer, resolver)
        decision = mgr._compute_featured_artist_decision(
            primary_artist="Some Primary",
            raw_feat="neuartiger kuenstler xy",
            track_context="ctx",
        )
        assert decision["canonical"] == "Neuartiger Kuenstler Xy"
        assert decision["decision"] == "WOULD_LEARN"

    def test_without_resolver_falls_back_to_normalize(
        self, config_stub, normalizer
    ):
        mgr = _manager(config_stub, normalizer, resolver=None)
        decision = mgr._compute_featured_artist_decision(
            primary_artist="Some Primary",
            raw_feat="bausashaus",
            track_context="ctx",
        )
        # normalize() hat den "Bausashaus"->"Bausa"-Pattern-Sonderfall …
        assert decision["canonical"] == "Bausa"
        # … aber die Entscheidung basiert auf _is_artist_known()-Dateiscan,
        # der den Override ebenfalls kennt:
        assert decision["decision"] == "SKIPPED_KNOWN"
