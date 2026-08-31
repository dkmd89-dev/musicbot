"""
Unit-Tests für TagWriter (services/metadata/tag_writer.py).

TagWriter wurde im Zuge von ARCH-001 aus EnhancedMetadataProcessor
extrahiert (_write_metadata_to_file_with_lyrics/_write_genres_m4a/
_write_genres_mp3/_extract_genre_parts -> eigene Klasse, 1:1 gleicher
Code, siehe docs/MusicBot_ARCH-001_Orchestrators.md). Diese Tests decken
den extrahierten Code jetzt isoliert ab, statt nur indirekt über den
E2E-Test (tests/test_metadata_processor_happy_path.py).

Für den MP3-Pfad wird - wie im bestehenden E2E-Test - absichtlich mit
ungültigen Bytes gearbeitet: mutagen.id3.ID3() kann trotz ungültigem
Header einen frischen Tag anlegen und speichern (siehe except-Zweig in
write_tags), das ist real genug um Titel/Artist/Genre-Tags zu schreiben
und per erneutem Laden zu verifizieren, ohne eine echte Audiodatei zu
brauchen. Für M4A/MP4 gibt es diesen Fallback nicht (mutagen.mp4.MP4()
braucht einen echten Container) - dafür wird nur das erwartete,
graceful Fehlverhalten bei ungültigen Bytes geprüft (kein Crash, Fehler
geloggt, keine Exception nach außen).
"""

from unittest.mock import Mock

import pytest
from mutagen.id3 import ID3, TCON, TXXX

from services.metadata.tag_writer import TagWriter


@pytest.fixture
def writer():
    return TagWriter(logger=Mock())


@pytest.fixture
def mp3_path(tmp_path):
    path = tmp_path / "track.mp3"
    path.write_bytes(b"not-a-real-mp3-file")
    return path


class TestWriteTagsMp3Basics:
    def test_title_and_artist_are_written(self, writer, mp3_path):
        writer.write_tags(
            target_path=mp3_path,
            artist="Some Artist",
            title="Some Title",
            album_info={},
            track_number=None,
            genres_result=None,
        )

        tags = ID3(mp3_path)
        assert tags["TIT2"].text == ["Some Title"]
        assert tags["TPE1"].text == ["Some Artist"]

    def test_album_year_track_number_are_written_when_present(self, writer, mp3_path):
        writer.write_tags(
            target_path=mp3_path,
            artist="Artist",
            title="Title",
            album_info={"album": "Some Album", "album_artist": "Album Artist", "year": 2024},
            track_number=5,
            genres_result=None,
        )

        tags = ID3(mp3_path)
        assert tags["TALB"].text == ["Some Album"]
        assert tags["TPE2"].text == ["Album Artist"]
        assert tags["TDRC"].text[0].text == "2024"
        assert tags["TRCK"].text == ["5"]

    def test_missing_album_info_keys_are_simply_skipped(self, writer, mp3_path):
        writer.write_tags(
            target_path=mp3_path,
            artist="Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result=None,
        )

        tags = ID3(mp3_path)
        assert "TALB" not in tags
        assert "TRCK" not in tags

    def test_missing_target_file_logs_error_and_returns_without_crash(self, writer, tmp_path):
        writer.write_tags(
            target_path=tmp_path / "does_not_exist.mp3",
            artist="Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result=None,
        )
        writer.logger.error.assert_called_once()

    def test_unknown_extension_warns_and_returns_without_crash(self, writer, tmp_path):
        path = tmp_path / "track.flac"
        path.write_bytes(b"whatever")

        writer.write_tags(
            target_path=path,
            artist="Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result=None,
        )
        writer.logger.warning.assert_called_once()


class TestWriteTagsGenreMp3:
    def test_primary_only_writes_single_genre(self, writer, mp3_path):
        writer.write_tags(
            target_path=mp3_path,
            artist="Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result={"primary": "Hip Hop", "secondary": []},
        )

        tags = ID3(mp3_path)
        assert tags["TCON"].text == ["Hip Hop"]

    def test_primary_and_secondary_are_combined(self, writer, mp3_path):
        writer.write_tags(
            target_path=mp3_path,
            artist="Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result={"primary": "Hip Hop", "secondary": ["Rap", "Trap"]},
        )

        tags = ID3(mp3_path)
        assert tags["TCON"].text == ["Hip Hop / Rap / Trap"]

    def test_secondary_list_is_capped_at_three(self, writer, mp3_path):
        writer.write_tags(
            target_path=mp3_path,
            artist="Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result={
                "primary": "Hip Hop",
                "secondary": ["Rap", "Trap", "Drill", "Boom Bap"],
            },
        )

        tags = ID3(mp3_path)
        assert tags["TCON"].text == ["Hip Hop / Rap / Trap / Drill"]

    def test_missing_genres_result_writes_no_genre_tag(self, writer, mp3_path):
        writer.write_tags(
            target_path=mp3_path,
            artist="Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result=None,
        )

        tags = ID3(mp3_path)
        assert "TCON" not in tags


class TestWriteTagsFeatArtists:
    def test_feat_artists_are_added_as_secondary_artist_txxx(self, writer, mp3_path):
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
        assert tags["TPE1"].text == ["Main Artist", "Feature One", "Feature Two"]
        artists_txxx = tags.getall("TXXX:ARTISTS")
        assert len(artists_txxx) == 1
        # TAG-01 (docs/archive/MusicBot_TAG01_MULTI_ARTIST_TAG_AUDIT.md): mehrere
        # separate Werte statt eines mit "; " zusammengefuegten Strings -
        # Navidrome braucht das fuer Multi-Artist-Splitting (siehe
        # tests/test_tag_writer_multi_value_artists_tag.py fuer den
        # vollstaendigen Fund inkl. M4A-Seite).
        assert list(artists_txxx[0].text) == ["Main Artist", "Feature One", "Feature Two"]

    def test_feat_artists_are_normalized_when_normalizer_present(self, mp3_path):
        normalizer = Mock()
        normalizer.normalize.side_effect = lambda a: a.upper()
        writer = TagWriter(logger=Mock(), artist_normalizer=normalizer)

        writer.write_tags(
            target_path=mp3_path,
            artist="Main Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result=None,
            feat_artists=["feature one"],
        )

        normalizer.normalize.assert_called_once_with("feature one")
        tags = ID3(mp3_path)
        assert tags["TPE1"].text == ["Main Artist", "FEATURE ONE"]

    def test_normalizer_returning_falsy_falls_back_to_original_name(self, mp3_path):
        normalizer = Mock()
        normalizer.normalize.return_value = None
        writer = TagWriter(logger=Mock(), artist_normalizer=normalizer)

        writer.write_tags(
            target_path=mp3_path,
            artist="Main Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result=None,
            feat_artists=["feature one"],
        )

        tags = ID3(mp3_path)
        assert tags["TPE1"].text == ["Main Artist", "feature one"]

    def test_no_feat_artists_means_no_artists_txxx(self, writer, mp3_path):
        writer.write_tags(
            target_path=mp3_path,
            artist="Main Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result=None,
        )

        tags = ID3(mp3_path)
        assert not tags.getall("TXXX:ARTISTS")


class TestWriteTagsLyricsAndCover:
    def test_lyrics_are_stripped_and_written(self, writer, mp3_path):
        writer.write_tags(
            target_path=mp3_path,
            artist="Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result=None,
            lyrics="  Some lyrics text  \n",
        )

        tags = ID3(mp3_path)
        uslt = tags.getall("USLT::deu")
        assert len(uslt) == 1
        assert uslt[0].text == "Some lyrics text"

    def test_cover_art_is_written_as_apic(self, writer, mp3_path):
        writer.write_tags(
            target_path=mp3_path,
            artist="Artist",
            title="Title",
            album_info={},
            track_number=None,
            genres_result=None,
            cover_art=b"fake-jpeg-bytes",
        )

        tags = ID3(mp3_path)
        apic = tags.getall("APIC:Cover")
        assert len(apic) == 1
        assert apic[0].data == b"fake-jpeg-bytes"


class TestWriteTagsM4aGracefulFailure:
    def test_invalid_m4a_bytes_raise_log_and_leave_original_untouched(
        self, writer, tmp_path
    ):
        """
        AE-11 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md): write_tags() darf
        einen fehlgeschlagenen Tagging-Vorgang nicht mehr als Erfolg
        erscheinen lassen (verschluckte Exception) - die Exception muss
        jetzt propagieren, damit der uebergeordnete FINDING-2-Cleanup
        (enhanced_metadata_processor.py) tatsaechlich erreicht wird.
        """
        path = tmp_path / "track.m4a"
        original_bytes = b"not-a-real-m4a-container"
        path.write_bytes(original_bytes)

        with pytest.raises(Exception):
            writer.write_tags(
                target_path=path,
                artist="Artist",
                title="Title",
                album_info={},
                track_number=None,
                genres_result=None,
            )

        writer.logger.error.assert_called_once()
        assert path.read_bytes() == original_bytes, (
            "Original muss bei einem Tagging-Fehler byteidentisch bleiben"
        )
        leftover_tmp_files = list(tmp_path.glob(".track.m4a.tmp_*"))
        assert not leftover_tmp_files, (
            f"Temporaere Datei(en) nach Fehler nicht aufgeraeumt: {leftover_tmp_files}"
        )


class TestExtractGenreParts:
    def test_object_with_primary_secondary_attributes(self, writer):
        genres_result = Mock(primary="Hip Hop", secondary=["Rap"])
        primary, secondary = writer._extract_genre_parts(genres_result)
        assert primary == "Hip Hop"
        assert secondary == ["Rap"]

    def test_dict_with_primary_secondary_keys(self, writer):
        primary, secondary = writer._extract_genre_parts(
            {"primary": "Techno", "secondary": ["House"]}
        )
        assert primary == "Techno"
        assert secondary == ["House"]

    def test_dict_without_secondary_key_defaults_to_empty_list(self, writer):
        primary, secondary = writer._extract_genre_parts({"primary": "Techno"})
        assert primary == "Techno"
        assert secondary == []

    def test_unrecognized_type_returns_none_and_empty_list(self, writer):
        primary, secondary = writer._extract_genre_parts("not a genre result")
        assert primary is None
        assert secondary == []

    def test_none_returns_none_and_empty_list(self, writer):
        primary, secondary = writer._extract_genre_parts(None)
        assert primary is None
        assert secondary == []
