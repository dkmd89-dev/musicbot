"""
Live-Fund 2026-09-03 (Nutzer-Report, echter Testdownload): der Repost-/
Compilation-Kanal "GermanHype" lernte faelschlich einen Alias
'GermanHype' -> 'Peter Maffay' in auto_learned_artist_aliases.json, obwohl
der Titel-Parser 'Peter Maffay' korrekt AUS DEM TITEL erkannt hatte
(artist_source='youtube_parsed', NICHT 'channel_fallback' - der Kanalname
war an der eigentlichen Artist-Bestimmung gar nicht beteiligt).

Root Cause: enhanced_metadata_processor.py verwendete
track_metadata.get("uploader") IMMER PRIORITAER als raw_name fuer
AutoLearnManager.learn_artist() - unabhaengig von der artist_source. Im
Normalfall (eigener Kuenstler-Kanal) ist das korrekt und sogar
erwuenscht: der Kanalname IST dort meist die authentische, rohe
Schreibweise des Kuenstlernamens (z.B. Kanal 'MAKKO' waehrend der
normalisierte Name 'Makko' lautet) - das Lernen von Schreibvarianten
funktioniert nur deshalb. Bei Repost-/Compilation-Kanaelen weicht der
Kanalname aber komplett vom tatsaechlich erkannten Kuenstler ab.

Verworfener erster Loesungsansatz: raw_name pauschal auf
track_metadata.get("artist") umstellen (statt uploader) - waere ZU BREIT
gewesen, da dieses Feld bei den meisten YouTube-Downloads (gerade bei
artist_source='youtube_parsed', wo der Artist ja WEIL kein strukturiertes
artist-Feld vorhanden aus dem Titel geparst werden musste) leer ist -
haette das gesamte automatische Alias-Learning fuer die haeufigste Quelle
faktisch stillgelegt.

ERSTER FIX-VERSUCH (unvollstaendig, per Debug-Log widerlegt): pruefte nur
den Kanalnamen (uploader) gegen canonical_name und fiel bei fehlender
Aehnlichkeit BLIND auf track_metadata['artist'] zurueck. Live per
Debug-Log bewiesen (Fall Calvin Harris/GermanHype, 2026-09-03 06:00 Uhr):
services/downloader/download_utils.py setzt track_metadata['artist'] BEIM
DOWNLOAD-SCHRITT bereits auf 'video_info.get("artist") or
video_info.get("uploader")' (Zeile 1301, Single-Track-Pfad; identisches
Muster Zeile 1103 im Playlist-Pfad) - bei Videos ohne echtes yt-dlp-
Artist-Tag (Normalfall bei Repost-Kanaelen) ist track_metadata['artist']
daher NICHT unabhaengig vom Kanalnamen, sondern schlicht IDENTISCH damit.
Der blinde Fallback liess den Kanalnamen dadurch ueber einen Umweg
trotzdem durch.

Vollstaendiger Fix: ArtistProcessor.raw_name_for_learning() prueft JETZT
BEIDE Kandidaten (uploader UND track_metadata['artist']) gegen den
canonical_name - nur ein Kandidat, der dem bereits bestimmten Kuenstler
tatsaechlich aehnelt (identisch oder Teilstring in eine der beiden
Richtungen, case-insensitiv), wird als roher Name fuer das Lernen
geliefert. Bewiesener alleiniger Produktions-Schreibpfad (repoweit
verifiziert, 2026-09-03): enhanced_metadata_processor.py ->
ArtistProcessor.raw_name_for_learning() -> AutoLearnManager.learn_artist()
-> _save_alias() -> auto_learned_artist_aliases.json.
utils/artist_map.py::learn_from_feedback()/add_auto_learned_alias() sind
ein zweiter, aber bereits dokumentiert toter Codepfad ohne Aufrufer
(siehe tests/test_artist_config_mapping_dir_isolation.py).
_is_non_artist_channel() (auto_learn.py) und der channel_name-Parameter
von learn_artist() sind ebenfalls unbenutzt (repoweit verifiziert keine
Aufrufer/Verwendung) - haetten den Fall 'GermanHype' ohnehin nicht
erkannt (kein passendes Suffix-Muster).
"""

from services.metadata.artist_processor import ArtistProcessor


def _processor():
    return ArtistProcessor(artist_normalizer=None)


class TestRawNameForLearningNormalCase:
    """Der haeufigste, unveraenderte Fall: eigener Kuenstler-Kanal, uploader
    aehnelt dem canonical_name - Kanalname wird weiterhin gelernt."""

    def test_exact_match_uses_uploader(self):
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "Makko"}, canonical_name="Makko"
        )
        assert result == "Makko"

    def test_case_variant_uses_uploader(self):
        """Der eigentliche Lern-Zweck: Kanal 'MAKKO' (roh) -> normalisiert
        'Makko' - genau das muss weiterhin funktionieren."""
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "MAKKO"}, canonical_name="Makko"
        )
        assert result == "MAKKO"

    def test_uploader_is_substring_of_canonical(self):
        """z.B. Kanal 'Miksu' fuer Duo 'Miksu & Macloud'."""
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "Miksu"}, canonical_name="Miksu & Macloud"
        )
        assert result == "Miksu"

    def test_canonical_is_substring_of_uploader(self):
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "Makko - Topic"}, canonical_name="Makko"
        )
        assert result == "Makko - Topic"


class TestRawNameForLearningRepostChannel:
    """Live-Fund: Repost-/Compilation-Kanal, Kanalname hat nichts mit dem
    tatsaechlich erkannten Kuenstler zu tun - darf NICHT gelernt werden."""

    def test_germanhype_peter_maffay_case_returns_empty(self):
        """Der real reproduzierte Bug-Fall."""
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "GermanHype"}, canonical_name="Peter Maffay"
        )
        assert result == ""

    def test_germanhype_oimara_case_returns_empty(self):
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "GermanHype"}, canonical_name="Oimara"
        )
        assert result == ""

    def test_falls_back_to_artist_field_when_it_resembles_canonical(self):
        """track_metadata['artist'] wird NUR verwendet, wenn es SELBST dem
        canonical_name aehnelt - nicht blind, sobald uploader verworfen
        wurde."""
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "GermanHype", "artist": "Peter Maffay"},
            canonical_name="Peter Maffay",
        )
        assert result == "Peter Maffay"

    def test_calvin_harris_case_artist_field_also_contaminated_with_channel(self):
        """
        Der TATSAECHLICH live reproduzierte Fall (per Debug-Log bewiesen,
        2026-09-03): services/downloader/download_utils.py setzt
        track_metadata['artist'] bereits BEIM DOWNLOAD-SCHRITT auf
        'video_info.get("artist") or video_info.get("uploader")' - bei
        Videos ohne echtes yt-dlp-Artist-Tag (der Normalfall bei Repost-
        Kanaelen) ist track_metadata['artist'] daher IDENTISCH mit dem
        Kanalnamen, nicht unabhaengig davon. Der erste (unvollstaendige)
        Fix pruefte nur 'uploader' gegen canonical_name und liess
        'artist_field' danach UNGEPRUEFT als Fallback durch - genau das
        fuehrte dazu, dass 'GermanHype' trotzdem gelernt wurde (raw_name_
        for_learning() gab 'GermanHype' zurueck, weil artist_field ==
        uploader == 'GermanHype').
        """
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "GermanHype", "artist": "GermanHype"},
            canonical_name="Calvin Harris",
        )
        assert result == "", (
            "artist_field muss GENAUSO gegen canonical_name geprueft werden "
            "wie uploader - beide koennen mit dem Kanalnamen kontaminiert sein"
        )


class TestRawNameForLearningEdgeCases:
    def test_no_uploader_falls_back_to_artist_field(self):
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"artist": "Some Artist"}, canonical_name="Some Artist"
        )
        assert result == "Some Artist"

    def test_nothing_available_returns_empty(self):
        processor = _processor()
        result = processor.raw_name_for_learning({}, canonical_name="Artist")
        assert result == ""

    def test_no_canonical_name_still_uses_uploader(self):
        """Ohne canonical_name kann keine Aehnlichkeit geprueft werden -
        konservativ das bisherige Verhalten (uploader bevorzugt)
        beibehalten, kein Overreach in einen nicht beobachteten Fall."""
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "SomeChannel"}, canonical_name=""
        )
        assert result == "SomeChannel"


# ─────────────────────────────────────────────────────────────────────────
# End-to-End: tatsaechlicher Persistenzpfad (Nutzer-Auftrag Abschnitt 5:
# "nicht nur die Helper-Funktion testen" - Aufruf ueber
# AutoLearnManager.learn_artist() bis zur echten
# auto_learned_artist_aliases.json-Datei, mit raw_name_for_learning() als
# vorgeschaltetem, bewiesenem alleinigem Produktions-Entry-Point).
# ─────────────────────────────────────────────────────────────────────────

import asyncio
import json
from pathlib import Path

import pytest

from services.metadata.auto_learn import AutoLearnManager
from utils.artist_map import ArtistNormalizer, ArtistConfig
from utils.genre_map import GenreMapper


class _Config:
    def __init__(self, mapping_dir: Path):
        self.GENRE_MAPPING_DIR = mapping_dir


def _make_manager(mapping_dir: Path) -> AutoLearnManager:
    config = _Config(mapping_dir)
    artist_config = ArtistConfig(
        library_dir=mapping_dir.parent / "library",
        override_file=mapping_dir / "artist_overrides.json",
        mapping_dir=mapping_dir,
    )
    artist_normalizer = ArtistNormalizer(artist_config)
    genre_mapper = GenreMapper(mapping_dir=mapping_dir)
    return AutoLearnManager(
        config=config, artist_normalizer=artist_normalizer, genre_mapper=genre_mapper
    )


def _run(coro):
    return asyncio.run(coro)


def _read_aliases(mapping_dir: Path) -> dict:
    path = mapping_dir / "auto_learned_artist_aliases.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return (json.load(f) or {}).get("auto_learned", {})


class TestEndToEndPersistencePathChannelNameNeverPersisted:
    """
    Deckt exakt den vom Nutzer geforderten Beweis ab: der reale
    Produktionspfad enhanced_metadata_processor.py -> raw_name_for_
    learning() -> AutoLearnManager.learn_artist() -> _save_alias() ->
    auto_learned_artist_aliases.json darf einen Kanalnamen NIEMALS als
    Artist-Alias persistieren - unabhaengig davon, ob track_metadata['artist']
    (wie im echten Bug) mit dem Kanalnamen kontaminiert ist.
    """

    def _raw_name(self, track_metadata: dict, canonical: str) -> str:
        # Exakt derselbe Aufruf wie in enhanced_metadata_processor.py.
        processor = ArtistProcessor(artist_normalizer=None)
        return processor.raw_name_for_learning(track_metadata, canonical)

    def test_germanhype_calvin_harris_never_persisted(self, tmp_path):
        """Der real reproduzierte Bug-Fall, end-to-end bis zur Datei."""
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        track_metadata = {"uploader": "GermanHype", "artist": "GermanHype"}
        canonical = "Calvin Harris"
        raw_name = self._raw_name(track_metadata, canonical)

        result = _run(
            manager.learn_artist(
                raw_name=raw_name, canonical_name=canonical, source="youtube_parsed"
            )
        )
        assert result is False, "kein Alias haette geschrieben werden duerfen"

        aliases = _read_aliases(mapping_dir)
        assert "GermanHype" not in aliases
        assert aliases == {}

    def test_germanhype_peter_maffay_never_persisted(self, tmp_path):
        """Zweiter real reproduzierter Fall (Peter Maffay, derselbe Kanal)."""
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        track_metadata = {"uploader": "GermanHype", "artist": "GermanHype"}
        canonical = "Peter Maffay"
        raw_name = self._raw_name(track_metadata, canonical)

        _run(
            manager.learn_artist(
                raw_name=raw_name, canonical_name=canonical, source="youtube_parsed"
            )
        )
        assert "GermanHype" not in _read_aliases(mapping_dir)

    @pytest.mark.parametrize(
        "channel_name",
        [
            "Music Channel",
            "Topic Channel",
            "Some Label Compilation",
        ],
    )
    def test_generic_non_artist_channels_never_persisted(self, tmp_path, channel_name):
        """Nutzer-Auftrag Abschnitt 5: 'Music Channel'/'Topic Channel'/
        Label-Compilation-Kanal -> irgendein Artist muss ebenfalls
        geschuetzt sein - nicht nur der eine bekannte GermanHype-Fall."""
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        track_metadata = {"uploader": channel_name, "artist": channel_name}
        canonical = "Some Completely Different Artist"
        raw_name = self._raw_name(track_metadata, canonical)

        _run(
            manager.learn_artist(
                raw_name=raw_name, canonical_name=canonical, source="youtube_parsed"
            )
        )
        aliases = _read_aliases(mapping_dir)
        assert channel_name not in aliases

    def test_real_own_artist_channel_still_learns_alias(self, tmp_path):
        """
        Regressionsschutz - Kernanliegen: ein ECHTER Kuenstler-Kanal muss
        weiterhin lernen koennen. 'Miksu' (Kanal/roher Name) fuer das Duo
        'Miksu & Macloud' - ein echter, abweichender Alias (nicht nur ein
        Case-Unterschied, der stattdessen als Identitaets-Mapping nach
        known_artists.yaml ginge, siehe learn_artist() raw.casefold()==
        canonical.casefold()-Zweig). Dieser Fall darf durch den Fix NICHT
        kaputtgehen.
        """
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        track_metadata = {"uploader": "Miksu", "artist": "Miksu"}
        canonical = "Miksu & Macloud"
        raw_name = self._raw_name(track_metadata, canonical)

        result = _run(
            manager.learn_artist(
                raw_name=raw_name, canonical_name=canonical, source="youtube_parsed"
            )
        )
        assert result is True, "ein echter Kuenstler-Kanal muss weiterhin lernen"
        assert _read_aliases(mapping_dir).get("Miksu") == "Miksu & Macloud"
