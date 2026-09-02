"""
TAG-01 (entdeckt vom Nutzer via echten Navidrome/Symfonium-Abgleich am
2026-08-31, im Anschluss an den Clueso-feat.-Chapo102-Testdownload):
TagWriter.write_tags() schrieb das Multi-Artist-Feld "ARTISTS" (das von
Navidrome fuer "Zusaetzlicher Interpret"/zusaetzliche Interpreten-
Verknuepfung gelesen wird) als EINEN mit "; " zusammengefuegten String
statt als mehrere separate Werte:

  MP4: audio["----:com.apple.iTunes:ARTISTS"] = [artists_semicolon.encode(...)]
  MP3: audio.add(TXXX(desc="ARTISTS", text=artists_semicolon))

Nutzer-Beobachtung (real, Symfonium): bei "Clueso feat. Chapo102" wurde
nur "Clueso" korrekt als Interpret erkannt, unter "Zusaetzlicher
Interpret" erschien "Clueso; CHAPO102" als EIN zusammengefuegter String
(nicht gesplittet) - der Track war unter dem Artist "CHAPO102" gar nicht
auffindbar. Direkte mutagen-Pruefung des real erzeugten Testfiles
bestaetigte: die STANDARD-Artist-Atome (©ART/TPE1) waren bereits korrekt
als mehrere separate Werte geschrieben (['Clueso', 'CHAPO102']) - nur das
zusaetzliche, von Navidrome fuer Multi-Artist-Splitting gelesene
"ARTISTS"-Feld (MusicBrainz-Picard-Konvention) enthielt EINEN Wert statt
mehrerer.

Zusaetzlicher Nebenbefund: audio["ARTISTS"] = [artists_semicolon] (ohne
"----:com.apple.iTunes:"-Praefix) ist gar kein gueltiger 4-Byte-MP4-Atom-
Schluessel - mutagen kappt/interpretiert ihn zu einem bedeutungslosen
"ARTI"-Atom (direkt verifiziert), das von keiner bekannten Software
gelesen wird. Reiner Datenmuell, entfernt.

Fix: beide Pfade schreiben jetzt eine LISTE separater Werte (ein Eintrag
je Kuenstler) statt eines zusammengefuegten Strings - Standard-Konvention
fuer Multi-Value-ID3v2.4-TXXX-Frames bzw. MP4-Freeform-Atome (Picard-
kompatibel), die Navidrome zum Splitten in einzelne Interpreten
benoetigt.

Nutzt fuer M4A dasselbe echte-Datei-Muster wie
tests/test_tag_writer_atomic_replace.py (_make_real_m4a via ffmpeg).
"""

import shutil
import subprocess
from unittest.mock import Mock

import pytest
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from services.metadata.tag_writer import TagWriter

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def _make_real_m4a(path, duration_seconds=1):
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_seconds}",
            "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )


@pytest.fixture
def writer():
    return TagWriter(logger=Mock())


@pytest.fixture
def mp3_path(tmp_path):
    path = tmp_path / "track.mp3"
    path.write_bytes(b"not-a-real-mp3-file")
    return path


class TestMp3ArtistsTxxxIsMultiValued:
    def test_feat_artists_are_written_as_separate_txxx_values(self, writer, mp3_path):
        """TAG-01-Kernfall (MP3-Seite)."""
        writer.write_tags(
            target_path=mp3_path,
            artist="Clueso",
            title="Jedes Jahr",
            album_info={},
            track_number=None,
            genres_result=None,
            feat_artists=["CHAPO102"],
        )

        tags = ID3(mp3_path)
        artists_txxx = tags.getall("TXXX:ARTISTS")
        assert len(artists_txxx) == 1
        assert list(artists_txxx[0].text) == ["Clueso", "CHAPO102"]

    def test_three_artists_all_appear_as_separate_values(self, writer, mp3_path):
        writer.write_tags(
            target_path=mp3_path,
            artist="Main Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result=None,
            feat_artists=["Feature One", "Feature Two"],
        )

        tags = ID3(mp3_path)
        artists_txxx = tags.getall("TXXX:ARTISTS")
        assert list(artists_txxx[0].text) == [
            "Main Artist",
            "Feature One",
            "Feature Two",
        ]


class _FakeNormalizer:
    """Simuliert einen ArtistNormalizer mit einem Mapping-Override, das
    einen rohen Feature-Artist auf denselben kanonischen String abbildet
    wie der bereits finale Haupt-Artist (Live-Fund 2026-09-02)."""

    def __init__(self, mapping: dict):
        self._mapping = {k.lower(): v for k, v in mapping.items()}

    def normalize(self, name: str) -> str:
        return self._mapping.get(name.strip().lower(), name)


class TestFeatArtistDuplicateAfterNormalizationIsDeduped:
    """
    Live-Fund 2026-09-02 (Nutzer-Report, Nachfolge des Miksu & Macloud-
    Mapping-Fixes in mapping/artist_overrides.json): ein roher Feature-
    Artist-Eintrag ("Miksu") normalisiert ueber einen Override auf denselben
    kanonischen String wie der bereits finale Haupt-Artist ("Miksu &
    Macloud") - ohne Dedup nach der Normalisierung landete der Duo-Name
    doppelt im ARTISTS-Tag ("Miksu & Macloud; Miksu & Macloud; MACLOUD;
    makko" statt "Miksu & Macloud; MACLOUD; makko").
    """

    def test_feat_artist_matching_final_artist_after_normalization_is_removed(
        self, mp3_path
    ):
        writer = TagWriter(
            logger=Mock(),
            artist_normalizer=_FakeNormalizer(
                {
                    "miksu": "Miksu & Macloud",
                    "macloud": "MACLOUD",
                    "makko": "makko",
                }
            ),
        )
        writer.write_tags(
            target_path=mp3_path,
            artist="Miksu & Macloud",
            title="Nachts wach",
            album_info={},
            track_number=None,
            genres_result=None,
            feat_artists=["Miksu", "Macloud", "makko"],
        )

        tags = ID3(mp3_path)
        artists_txxx = tags.getall("TXXX:ARTISTS")
        assert list(artists_txxx[0].text) == ["Miksu & Macloud", "MACLOUD", "makko"]

    def test_dedup_is_case_insensitive_and_keeps_first_occurrence_order(
        self, mp3_path
    ):
        writer = TagWriter(
            logger=Mock(),
            artist_normalizer=_FakeNormalizer({}),  # Identitaets-Normalisierung
        )
        writer.write_tags(
            target_path=mp3_path,
            artist="Main Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result=None,
            feat_artists=["main artist", "Feature One", "MAIN ARTIST", "Feature One"],
        )

        tags = ID3(mp3_path)
        artists_txxx = tags.getall("TXXX:ARTISTS")
        assert list(artists_txxx[0].text) == ["Main Artist", "Feature One"]


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg nicht auf PATH verfuegbar")
class TestM4aArtistsFreeformIsMultiValued:
    def test_feat_artists_are_written_as_separate_freeform_values(
        self, writer, tmp_path
    ):
        """TAG-01-Kernfall (M4A-Seite, real vom Nutzer via Navidrome/
        Symfonium beobachtet)."""
        path = tmp_path / "track.m4a"
        _make_real_m4a(path)

        writer.write_tags(
            target_path=path,
            artist="Clueso",
            title="Jedes Jahr",
            album_info={},
            track_number=None,
            genres_result=None,
            feat_artists=["CHAPO102"],
        )

        audio = MP4(path)
        artists_freeform = audio["----:com.apple.iTunes:ARTISTS"]
        assert [bytes(v).decode("utf-8") for v in artists_freeform] == [
            "Clueso",
            "CHAPO102",
        ]

    def test_standard_art_atom_remains_correctly_multi_valued(self, writer, tmp_path):
        """Regressionsschutz: das bereits korrekte Standard-Atom (©ART)
        darf durch den Fix nicht veraendert werden."""
        path = tmp_path / "track.m4a"
        _make_real_m4a(path)

        writer.write_tags(
            target_path=path,
            artist="Clueso",
            title="Jedes Jahr",
            album_info={},
            track_number=None,
            genres_result=None,
            feat_artists=["CHAPO102"],
        )

        audio = MP4(path)
        assert audio["©ART"] == ["Clueso", "CHAPO102"]

    def test_no_bogus_arti_atom_is_written(self, writer, tmp_path):
        """Nebenbefund-Regressionsschutz: der ungueltige "ARTISTS"-Schluessel
        (kein echtes MP4-Atom, wurde vorher zu bedeutungslosem "ARTI"
        gekappt) darf nicht mehr geschrieben werden."""
        path = tmp_path / "track.m4a"
        _make_real_m4a(path)

        writer.write_tags(
            target_path=path,
            artist="Clueso",
            title="Jedes Jahr",
            album_info={},
            track_number=None,
            genres_result=None,
            feat_artists=["CHAPO102"],
        )

        audio = MP4(path)
        assert "ARTI" not in audio
        assert "ARTISTS" not in audio
