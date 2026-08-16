"""
Characterization-Tests fuer FilenameFixerTool (utils/filenamefixer.py),
Phase 1 Engineering Baseline - File/Library Processing.
"""

from pathlib import Path

import pytest

from utils.filenamefixer import FilenameFixerTool


class FakeConfig:
    """Minimale Config-Attribute, die FilenameFixerTool._do_init tatsaechlich
    liest. GENRE_MAPPING_DIR zeigt standardmaessig auf ein leeres tmp-Verzeichnis
    (kein special_channel.yaml) -> _special_channels bleibt leer, damit die
    Standard-Musik-Pfad-Logik isoliert getestet werden kann."""

    def __init__(self, tmp_path: Path, mapping_dir: Path = None):
        self.LIBRARY_DIR = tmp_path / "library"
        self.FAIL_DIR = tmp_path / "fail"
        self.PROCESSED_DIR = tmp_path / "processed"
        self.TEMP_DIR = tmp_path / "temp"
        self.GENRE_MAPPING_DIR = mapping_dir or (tmp_path / "empty_mapping")


@pytest.fixture
def tool(tmp_path):
    return FilenameFixerTool(FakeConfig(tmp_path))


# ─────────────────────────────────────────────────────────────────────────
# build_final_path: Standard-Musik-Pfad (kein Spezialkanal)
# ─────────────────────────────────────────────────────────────────────────


class TestBuildFinalPathStandard:
    def test_single_uses_year_title_under_artist_singles_folder(self, tool):
        path = tool.build_final_path(
            artist="Some Artist",
            title="Some Song",
            year="2021",
            extension="m4a",
            is_single_download=True,
        )

        assert path.parent == tool.library_dir / "Some Artist" / "Singles"
        assert path.name == "2021 - Some Song.m4a"

    def test_single_without_year_uses_hash_placeholder(self, tool):
        path = tool.build_final_path(
            artist="Some Artist",
            title="Some Song",
            extension="mp3",
            is_single_download=True,
        )
        assert path.name == "#### - Some Song.mp3"

    def test_album_track_uses_track_number_and_year_album_folder(self, tool):
        path = tool.build_final_path(
            artist="Some Artist",
            title="Track Title",
            album="Some Album",
            year="2019",
            track_number=3,
            extension="flac",
        )

        assert path.parent == (
            tool.library_dir / "Some Artist" / "2019 - Some Album"
        )
        assert path.name == "03 - Track Title.flac"

    def test_album_track_without_track_number_uses_00_prefix(self, tool):
        path = tool.build_final_path(
            artist="Some Artist",
            title="Track Title",
            album="Some Album",
            year="2019",
            extension="flac",
        )
        assert path.name == "00 - Track Title.flac"

    def test_album_tag_literally_single_routes_to_singles_folder(self, tool):
        path = tool.build_final_path(
            artist="Some Artist",
            title="Song",
            album="Single",
            year="2022",
            extension="m4a",
        )
        assert path.parent == tool.library_dir / "Some Artist" / "Singles"

    def test_only_main_artist_before_feat_used_for_folder(self, tool):
        path = tool.build_final_path(
            artist="Main Artist feat. Guest Artist",
            title="Song",
            album="Some Album",
            year="2020",
            extension="m4a",
        )
        assert path.parent.parent.name == "Main Artist"

    def test_forbidden_filesystem_characters_are_stripped(self, tool):
        path = tool.build_final_path(
            artist='Artist: "Weird"/Name',
            title="Song?",
            album="Album*",
            year="2020",
            extension="m4a",
        )
        assert '"' not in str(path)
        assert "?" not in path.name
        assert ":" not in str(path.relative_to(tool.library_dir))


class TestBuildFinalPathSpecialChannels(object):
    @pytest.fixture
    def podcast_mapping_dir(self, tmp_path):
        mapping_dir = tmp_path / "mapping_with_podcast"
        mapping_dir.mkdir()
        (mapping_dir / "special_channel.yaml").write_text(
            """
SPECIAL_CHANNELS:
  Podcast:
    - Test Podcast Channel
  Compilations:
    - Test Compilation Channel
""",
            encoding="utf-8",
        )
        return mapping_dir

    @pytest.fixture
    def podcast_tool(self, tmp_path, podcast_mapping_dir):
        return FilenameFixerTool(FakeConfig(tmp_path, mapping_dir=podcast_mapping_dir))

    def test_podcast_channel_routes_to_podcast_dir_with_episode_number(
        self, podcast_tool
    ):
        path = podcast_tool.build_final_path(
            artist="Test Podcast Channel",
            title="17/2026 - Chaos beim Rennen",
            album="Test Podcast Channel",
            uploader="Test Podcast Channel",
            extension="m4a",
        )

        assert path.parent.name == "Test Podcast Channel"
        assert path.name == "172026 - Chaos beim Rennen.m4a"
        # Podcast-Dateien liegen unter self._podcast_dir, nicht direkt unter
        # library_dir/Podcast/... wie vor v2.1 (siehe Modul-Docstring). Ohne
        # PODCAST_DIR-Env/Config faellt _podcast_dir auf library_dir/Podcast
        # zurueck (Zeile 242 in filenamefixer.py) - das ist hier der Fall.
        assert path.parent == podcast_tool._podcast_dir / "Test Podcast Channel"
        assert podcast_tool._podcast_dir == podcast_tool.library_dir / "Podcast"

    def test_compilation_channel_uses_artist_dash_title_format(self, podcast_tool):
        path = podcast_tool.build_final_path(
            artist="Some Artist",
            title="Some Song",
            uploader="Test Compilation Channel",
            extension="m4a",
        )

        assert path.name == "Some Artist - Some Song.m4a"
        assert path.parent.name == "Test Compilation Channel"
        assert str(path).startswith(str(podcast_tool.library_dir))


# ─────────────────────────────────────────────────────────────────────────
# move_to_library: fehlende Quelle / bereits vorhandenes Ziel
# ─────────────────────────────────────────────────────────────────────────


class TestMoveToLibrary:
    def test_missing_source_raises_filenotfounderror(self, tool, tmp_path):
        missing = tmp_path / "does_not_exist.mp3"
        with pytest.raises(FileNotFoundError):
            tool.move_to_library(missing, artist="Artist", title="Title")

    def test_existing_destination_is_renamed_not_overwritten(self, tool, tmp_path):
        source1 = tmp_path / "source1.mp3"
        source1.write_bytes(b"first file content")
        first_target = tool.move_to_library(
            source1,
            artist="Some Artist",
            title="Some Song",
            year="2022",
            is_single=True,
        )
        assert first_target.read_bytes() == b"first file content"

        source2 = tmp_path / "source2.mp3"
        source2.write_bytes(b"second file content")
        second_target = tool.move_to_library(
            source2,
            artist="Some Artist",
            title="Some Song",
            year="2022",
            is_single=True,
        )

        # Kein Ueberschreiben: zweite Datei bekommt " (1)" angehaengt,
        # beide Dateien bleiben mit ihrem jeweiligen Inhalt erhalten.
        assert second_target != first_target
        assert second_target.name == "2022 - Some Song (1).mp3"
        assert first_target.exists()
        assert first_target.read_bytes() == b"first file content"
        assert second_target.read_bytes() == b"second file content"

    def test_move_uses_source_extension(self, tool, tmp_path):
        source = tmp_path / "source.flac"
        source.write_bytes(b"data")
        target = tool.move_to_library(source, artist="Artist", title="Title", is_single=True)
        assert target.suffix == ".flac"
