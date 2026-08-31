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


class TestBuildFinalPathTraversalSecurity:
    """
    Regressionstest für einen in Phase 2 gefundenen Path-Traversal-Bug:
    sanitize_filename() ließ literale ".."-Pfadsegmente unangetastet durch,
    sodass ein Artist-/Album-/Titel-Tag mit dem Wert ".." (z.B. aus
    manipulierten YouTube-Metadaten) den Zielpfad aus library_dir
    herausführen konnte. Vor dem Fix landete die Datei nachweislich eine
    Ebene über library_dir statt darunter.
    """

    def test_double_dot_artist_does_not_escape_library_dir(self, tool):
        path = tool.build_final_path(
            artist="..",
            title="Song",
            album="Album",
            year="2020",
            extension="m4a",
        )
        assert path.resolve().is_relative_to(tool.library_dir.resolve())

    def test_double_dot_album_does_not_escape_library_dir(self, tool):
        path = tool.build_final_path(
            artist="Some Artist",
            title="Song",
            album="..",
            year="2020",
            extension="m4a",
        )
        assert path.resolve().is_relative_to(tool.library_dir.resolve())

    def test_double_dot_title_does_not_escape_library_dir(self, tool):
        path = tool.build_final_path(
            artist="Some Artist",
            title="..",
            album="Album",
            year="2020",
            extension="m4a",
        )
        assert path.resolve().is_relative_to(tool.library_dir.resolve())

    def test_combined_double_dot_artist_and_album_does_not_escape(self, tool):
        # Verkettete ".."-Segmente ueber mehrere Felder waeren ohne den Fix
        # noch weiter nach oben eskaliert als ein einzelnes Feld.
        path = tool.build_final_path(
            artist="..",
            title="Song",
            album="..",
            year="2020",
            extension="m4a",
        )
        assert path.resolve().is_relative_to(tool.library_dir.resolve())


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
        first_target, first_renamed = tool.move_to_library(
            source1,
            artist="Some Artist",
            title="Some Song",
            year="2022",
            is_single=True,
        )
        assert first_target.read_bytes() == b"first file content"
        assert first_renamed is False

        source2 = tmp_path / "source2.mp3"
        source2.write_bytes(b"second file content")
        second_target, second_renamed = tool.move_to_library(
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
        # P1-Fund (Post-Baseline-v4 Health & Risk Audit, Finding 2): die
        # Kollision muss jetzt tatsaechlich signalisiert werden - vorher gab
        # es dieses zweite Rueckgabeelement gar nicht.
        assert second_renamed is True

    def test_move_uses_source_extension(self, tool, tmp_path):
        source = tmp_path / "source.flac"
        source.write_bytes(b"data")
        target, renamed = tool.move_to_library(source, artist="Artist", title="Title", is_single=True)
        assert target.suffix == ".flac"
        assert renamed is False


class TestMoveToLibraryAtomicity:
    """
    FINDING-6 (docs/archive/MusicBot_PHASE4_FAILURE_PATH_AUDIT.md): move_to_library()
    nutzte vorher shutil.move() direkt - faellt bei unterschiedlichen
    Dateisystemen (wie in der tatsaechlichen Konfiguration DOWNLOAD_DIR vs.
    LIBRARY_DIR) intern auf copy2()+unlink() zurueck, ohne Schutz gegen
    einen Abbruch waehrend des Kopiervorgangs. Jetzt: Kopie in eine
    temporaere Datei IM Zielverzeichnis, dann atomarer Path.replace().
    """

    def test_failed_copy_leaves_no_partial_file_at_target(
        self, tool, tmp_path, monkeypatch
    ):
        source = tmp_path / "source.mp3"
        source.write_bytes(b"real audio bytes")

        monkeypatch.setattr(
            "utils.filenamefixer.shutil.copy2",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )

        with pytest.raises(OSError):
            tool.move_to_library(source, artist="Artist", title="Title", is_single=True)

        # Quelldatei ist unangetastet - noch am Originalort, mit Originalinhalt.
        assert source.exists()
        assert source.read_bytes() == b"real audio bytes"

        # Kein Teil-/Muellfile im Zielverzeichnis.
        target_dir = tool.library_dir / "Artist" / "Singles"
        leftovers = list(target_dir.glob("*")) if target_dir.exists() else []
        assert leftovers == []

    def test_failed_copy_removes_its_own_tmp_file(self, tool, tmp_path, monkeypatch):
        source = tmp_path / "source.mp3"
        source.write_bytes(b"real audio bytes")

        monkeypatch.setattr(
            "utils.filenamefixer.shutil.copy2",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )

        with pytest.raises(OSError):
            tool.move_to_library(source, artist="Artist", title="Title", is_single=True)

        target_dir = tool.library_dir / "Artist" / "Singles"
        tmp_leftovers = (
            list(target_dir.glob("*.tmp_*")) if target_dir.exists() else []
        )
        assert tmp_leftovers == []

    def test_source_cleanup_failure_does_not_fail_an_otherwise_successful_move(
        self, tool, tmp_path, monkeypatch
    ):
        """
        Schlaegt nur das abschliessende Loeschen der (jetzt redundanten)
        Quelldatei fehl, ist die Datei bereits sicher am Zielort -
        move_to_library() muss trotzdem erfolgreich zurueckkehren.
        """
        source = tmp_path / "source.mp3"
        source.write_bytes(b"real audio bytes")

        # Path nutzt __slots__ (keine Instanz-Attribute) - patcht daher die
        # Klassenmethode fuer die Testdauer (monkeypatch stellt sie danach
        # automatisch wieder her), delegiert aber fuer jeden anderen Pfad
        # an die echte Implementierung.
        original_unlink = Path.unlink

        def selective_failing_unlink(self_path, *a, **kw):
            if self_path == source:
                raise OSError("permission denied")
            return original_unlink(self_path, *a, **kw)

        monkeypatch.setattr(Path, "unlink", selective_failing_unlink)

        target, renamed = tool.move_to_library(
            source, artist="Artist", title="Title", is_single=True
        )

        assert target.exists()
        assert target.read_bytes() == b"real audio bytes"
        assert renamed is False
