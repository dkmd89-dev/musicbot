"""
Bug-Fund waehrend Live-Verifikation der Genre-Lock-in-Phase (2026-09-03):
Last.fm lieferte fuer den Artist 'Oimara' ausschliesslich die zwei Tags
['german', 'deutschland'] - reine Herkunfts-/Sprach-Tags, keine echten
Musikgenres. Beide sind NICHT in genre_hierarchy.yaml enthalten, 'german'
steht zusaetzlich explizit in genre_filters.yaml::IGNORE_SECONDARY.

GenreProcessor.prioritize_genres() filtert 'german' korrekt heraus (der
IGNORE_SECONDARY-Filter greift) - Ergebnis: primary='Deutschland' (Fallback:
bester verbleibender Tag, da keiner der Tags in der Hierarchie ist),
secondary=[] (nur noch 1 valider Tag nach Filterung uebrig, kein zweiter
fuer secondary).

BUG: AutoLearnManager._compute_genre_decision() (services/metadata/
auto_learn.py) sieht das LEERE secondary und faellt in einen
elif-raw_tags-Fallback zurueck - raw_tags enthaelt aber die UNGEFILTERTEN
Last.fm-Rohdaten (['german', 'deutschland']), OHNE den IGNORE_SECONDARY-
Filter erneut anzuwenden. Ergebnis: 'german' landet trotzdem in secondary,
obwohl es bewusst als Nicht-Genre-Tag gefiltert werden sollte.

Live beobachtet: auto_learned_genre.json enthielt fuer 'Oimara'
primary='Deutschland', secondary=['german'] statt secondary=[].

Betrifft sowohl den Last.fm- als auch den MusicBrainz-Pfad identisch
(beide setzen raw_tags=tags mit den ungefilterten Rohdaten in
genre_processor.py::_fetch_genre_from_lastfm()/
_fetch_genre_from_musicbrainz()).
"""

from types import SimpleNamespace

from services.metadata.auto_learn import AutoLearnManager


class _StubGenreMapper:
    def get_artist_entry(self, artist_name):
        return None

    def clear_caches(self):
        pass


class _StubArtistNormalizer:
    overrides_normalized = {}


class _Config:
    GENRE_MAPPING_DIR = "mapping"


def _genre_result(primary, secondary, raw_tags, source="lastfm_prioritized"):
    return SimpleNamespace(
        primary=primary,
        secondary=secondary,
        raw_tags=raw_tags,
        source=source,
    )


def _make_manager():
    return AutoLearnManager(
        config=_Config(),
        artist_normalizer=_StubArtistNormalizer(),
        genre_mapper=_StubGenreMapper(),
    )


class TestRawTagsFallbackRespectsIgnoreFilter:
    def test_ignored_tag_does_not_leak_into_secondary_via_raw_tags_fallback(self):
        """
        Reproduziert exakt den live beobachteten Oimara-Fall: primary wurde
        bereits (durch prioritize_genres()) unter Beruecksichtigung von
        IGNORE_SECONDARY bestimmt, secondary ist bewusst leer (kein zweiter
        valider Tag) - der raw_tags-Fallback darf 'german' NICHT wieder
        einschleusen, nur weil raw_tags ungefiltert war.
        """
        manager = _make_manager()
        genre_result = _genre_result(
            primary="Deutschland",
            secondary=[],
            raw_tags=["german", "deutschland"],
        )
        decision = manager._compute_genre_decision("Oimara", genre_result)
        assert decision["observed_secondary"] == [], (
            "'german' darf nicht ungefiltert aus raw_tags in secondary "
            "landen, nur weil das (bereits korrekt gefilterte) secondary "
            "leer war"
        )

    def test_musicbrainz_source_is_equally_affected(self):
        """Derselbe Bug betrifft identisch den MusicBrainz-Pfad, da auch
        dort raw_tags die ungefilterten Rohdaten enthaelt."""
        manager = _make_manager()
        genre_result = _genre_result(
            primary="Deutschland",
            secondary=[],
            raw_tags=["german", "deutschland"],
            source="musicbrainz_prioritized",
        )
        decision = manager._compute_genre_decision("Oimara", genre_result)
        assert decision["observed_secondary"] == []
