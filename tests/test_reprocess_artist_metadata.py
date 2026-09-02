"""
Tests fuer das offizielle Reprocessing-Tool (scripts/reprocess_artist_metadata.py).

`scripts/` ist bewusst kein Python-Package (kein Download-/Server-Code,
sondern ein eigenstaendiges CLI-Werkzeug) - das Modul wird deshalb ueber
importlib direkt per Dateipfad geladen statt per Package-Import.

Test-Strategie (CLAUDE.md Abschnitt 7/8): reine, netzwerkfreie Logik
(Path-Safety, Multi-Artist-Split, UNRESOLVED-Erkennung, Snapshot/Diff)
wird isoliert und deterministisch getestet. Der End-to-End-Pfad
(`process_file()`) verwendet den ECHTEN Produktions-`TagWriter` (fuer die
TAG-01-Validierung), aber Mocks fuer die externen Adapter
(GenreProcessor/LyricsProcessor/CoverProcessor - echte MusicBrainz/Genius/
Cover-API-Aufruf), passend zur bestehenden Mocking-Policy des Repos.
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from mutagen.mp4 import MP4, MP4FreeForm

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "reprocess_artist_metadata.py"

_spec = importlib.util.spec_from_file_location("reprocess_artist_metadata", MODULE_PATH)
rpam = importlib.util.module_from_spec(_spec)
sys.modules["reprocess_artist_metadata"] = rpam
_spec.loader.exec_module(rpam)

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
FFPROBE_AVAILABLE = shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(
    not (FFMPEG_AVAILABLE and FFPROBE_AVAILABLE), reason="ffmpeg/ffprobe nicht auf PATH verfuegbar"
)

ALLOWED_ROOT = rpam.ALLOWED_ROOT  # /tmp/musicbot_test
METADATEN_ROOT = rpam.DEFAULT_METADATEN_ROOT  # /tmp/musicbot_test/metadaten


def _make_real_m4a(path: Path, duration_seconds: int = 1):
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_seconds}",
            "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )


@pytest.fixture
def isolated_artist_dir():
    """Ein echtes, temporaeres Artist-Verzeichnis UNTER der real erlaubten
    Testwurzel (/tmp/musicbot_test/metadaten) - ALLOWED_ROOT ist ein
    Modul-Konstante und an diese Konvention gebunden (identisch zur
    bereits etablierten config_test.py-Konvention dieses Projekts)."""
    import uuid

    artist_dir = METADATEN_ROOT / f"_pytest_reprocess_{uuid.uuid4().hex[:8]}"
    singles_dir = artist_dir / "Singles"
    singles_dir.mkdir(parents=True)
    yield artist_dir
    shutil.rmtree(artist_dir, ignore_errors=True)


@pytest.fixture
def tagged_m4a(isolated_artist_dir):
    """Eine echte, per ffmpeg erzeugte m4a-Datei mit Basis-Tags, im
    Singles-Unterordner des isolierten Artist-Verzeichnisses."""
    path = isolated_artist_dir / "Singles" / "2024 - Test Titel.m4a"
    _make_real_m4a(path)
    audio = MP4(path)
    audio["©nam"] = ["Test Titel"]
    audio["©ART"] = ["Test Artist"]
    audio["aART"] = ["Test Artist"]
    audio["©alb"] = ["Test Titel"]
    audio["©day"] = ["2024"]
    audio.save()
    return path


class DummyMBIdsResult:
    def __init__(self, primary=None, secondary=None, source="unit_test", mb_ids=None):
        self.primary = primary
        self.secondary = secondary or []
        self.source = source
        self.mb_ids = mb_ids or {}


def make_processor_stub(cover_bytes=None, cover_source=None, lyrics="Test Lyrics", lyrics_source="genius"):
    """Baut ein minimales Stand-in-Objekt mit genau den Attributen, die
    process_file() tatsaechlich verwendet. artist_normalizer/title_cleaner
    sind Identity-Mocks (ihre eigene Korrektheit ist andernorts bereits
    charakterisiert, tests/test_artist_map.py etc.) - genre/lyrics/cover
    sind echte externe Adapter und werden deshalb gemockt. tag_writer ist
    IMMER der echte Produktions-TagWriter (siehe process_file-Aufrufer).
    """
    from services.metadata.tag_writer import TagWriter

    processor = Mock()
    processor.artist_normalizer.normalize.side_effect = lambda a: a
    processor.title_cleaner.light_title_cleanup.side_effect = lambda title, artist: title
    processor.title_cleaner.build_search_title.side_effect = (
        lambda parsed_title, original_title, final_artist: original_title
    )
    processor.genre_processor.determine_genre_with_fallbacks = AsyncMock(
        return_value=DummyMBIdsResult(primary="Pop", secondary=[])
    )
    processor.lyrics_processor.fetch_lyrics_with_fallback = AsyncMock(
        return_value=(lyrics, lyrics_source)
    )
    processor.cover_processor.get_cover_art = Mock(return_value=(cover_bytes, cover_source))
    processor.tag_writer = TagWriter(logger=Mock())
    # auto_learn_manager: fuer die bestehenden Rename-/Tag-fokussierten Tests
    # hier bewusst neutral gemockt (kein Feature-Artist, kein Genre-Lernen) -
    # das eigentliche Auto-Learn-Verhalten wird dediziert in
    # tests/test_reprocess_artist_metadata_auto_learn.py gegen den echten
    # AutoLearnManager getestet.
    processor.auto_learn_manager = Mock()
    processor.auto_learn_manager.preview_featured_artists = Mock(return_value=[])
    processor.auto_learn_manager.observe_featured_artists = AsyncMock(return_value=[])
    processor.auto_learn_manager.preview_genre_learning = Mock(
        return_value={
            "artist": None,
            "observed_primary": None,
            "observed_secondary": [],
            "decision": "SKIPPED_NO_GENRE",
            "existing": None,
            "predicted_primary": None,
            "predicted_secondary": [],
            "predicted_observations": 0,
            "predicted_confidence": None,
        }
    )
    processor.auto_learn_manager.learn_genre = AsyncMock(return_value=False)
    return processor


# ─────────────────────────────────────────────────────────────────────────
# Path-Safety
# ─────────────────────────────────────────────────────────────────────────


class TestPathSafety:
    def test_valid_test_input_accepted(self, isolated_artist_dir):
        resolved = rpam.validate_input_path(isolated_artist_dir, METADATEN_ROOT)
        assert resolved == isolated_artist_dir.resolve()

    def test_missing_input_rejected(self):
        with pytest.raises(rpam.PathSafetyError, match="existiert nicht"):
            rpam.validate_input_path(METADATEN_ROOT / "does_not_exist_xyz", METADATEN_ROOT)

    def test_file_instead_of_directory_rejected(self, isolated_artist_dir):
        f = isolated_artist_dir / "not_a_dir.txt"
        f.write_text("x")
        with pytest.raises(rpam.PathSafetyError, match="kein Verzeichnis"):
            rpam.validate_input_path(f, METADATEN_ROOT)

    def test_metadaten_root_itself_rejected(self):
        with pytest.raises(rpam.PathSafetyError, match="nicht die Wurzel"):
            rpam.validate_input_path(METADATEN_ROOT, METADATEN_ROOT)

    def test_production_path_rejected(self, tmp_path):
        """Production-Root-Ablehnung isoliert getestet: metadaten_root wird
        auf ein Elternverzeichnis einer simulierten Produktions-Library
        gesetzt, damit die Wurzel-Pruefung besteht und gezielt der
        Produktions-spezifische Guard greift - ohne von der echten
        /mnt/4tb/library-Mount-Verfuegbarkeit abzuhaengen."""
        fake_prod = tmp_path / "library"
        fake_prod.mkdir()
        real_default = rpam.DEFAULT_PRODUCTION_ROOT
        try:
            rpam.DEFAULT_PRODUCTION_ROOT = fake_prod
            with pytest.raises(rpam.PathSafetyError, match="Produktionsbibliothek"):
                rpam.validate_input_path(fake_prod, tmp_path)
        finally:
            rpam.DEFAULT_PRODUCTION_ROOT = real_default

    def test_path_traversal_rejected(self, isolated_artist_dir):
        traversal = isolated_artist_dir / ".." / ".." / ".."
        with pytest.raises(rpam.PathSafetyError):
            rpam.validate_input_path(traversal, METADATEN_ROOT)

    def test_symlink_escaping_allowed_root_rejected(self, isolated_artist_dir, tmp_path):
        outside_target = tmp_path / "outside_target"
        outside_target.mkdir()
        symlink_path = isolated_artist_dir / "escape_link"
        symlink_path.symlink_to(outside_target, target_is_directory=True)
        with pytest.raises(rpam.PathSafetyError, match="nicht unterhalb|ausserhalb"):
            rpam.validate_input_path(symlink_path, METADATEN_ROOT)

    def test_file_symlink_escaping_root_flagged(self, isolated_artist_dir, tmp_path):
        outside_file = tmp_path / "outside.m4a"
        outside_file.write_bytes(b"fake")
        inside_link = isolated_artist_dir / "Singles" / "linked.m4a"
        inside_link.symlink_to(outside_file)
        assert rpam.validate_file_within_root(inside_link, isolated_artist_dir) is False

    def test_regular_file_within_root_accepted(self, tagged_m4a, isolated_artist_dir):
        assert rpam.validate_file_within_root(tagged_m4a, isolated_artist_dir) is True


# ─────────────────────────────────────────────────────────────────────────
# Multi-Artist (TAG-01-Split, ausschliesslich bestehende Logik)
# ─────────────────────────────────────────────────────────────────────────


class TestFlattenExistingArtists:
    def test_single_artist_passthrough(self):
        assert rpam.flatten_existing_artists(["CHAPO102"]) == ["CHAPO102"]

    def test_already_separate_values_stay_separate(self):
        assert rpam.flatten_existing_artists(
            ["CHAPO102", "Bausa", "MIKSU", "MACLOUD"]
        ) == ["CHAPO102", "Bausa", "MIKSU", "MACLOUD"]

    def test_semicolon_joined_legacy_string_split(self):
        """TAG-01-Altlast: ein einzelnes Listenelement mit ';'-getrenntem
        Inhalt (aelterer Bug-Stand, siehe WARSCHAU.m4a-Fund)."""
        assert rpam.flatten_existing_artists(["CHAPO102; Gustav"]) == ["CHAPO102", "Gustav"]

    def test_feat_keyword_split(self):
        assert rpam.flatten_existing_artists(["Artist A feat. Artist B"]) == [
            "Artist A", "Artist B",
        ]

    def test_duplicates_removed_case_insensitive(self):
        assert rpam.flatten_existing_artists(["CHAPO102; chapo102"]) == ["CHAPO102"]

    def test_empty_input(self):
        assert rpam.flatten_existing_artists([]) == []
        assert rpam.flatten_existing_artists(None) == []


# ─────────────────────────────────────────────────────────────────────────
# UNRESOLVED-Erkennung
# ─────────────────────────────────────────────────────────────────────────


class TestCheckUnresolved:
    def _base_snapshot(self, **overrides):
        base = {"replaygain_track_gain": ["0.05 dB"], "loudness_normalized": ["true"]}
        base.update(overrides)
        return base

    def test_missing_replaygain_flagged(self):
        after = self._base_snapshot(replaygain_track_gain=[], loudness_normalized=[])
        reasons = rpam.check_unresolved({}, after, "Clean Title")
        assert any("ReplayGain" in r for r in reasons)

    def test_present_replaygain_not_flagged_for_that_reason(self):
        after = self._base_snapshot()
        reasons = rpam.check_unresolved({}, after, "Clean Title")
        assert not any("ReplayGain" in r for r in reasons)

    def test_title_with_illegal_filename_char_flagged(self):
        after = self._base_snapshot()
        reasons = rpam.check_unresolved({}, after, "WER HAT DIESE FRAU GESEHEN?")
        assert any("nicht darstellbar" in r for r in reasons)

    def test_clean_title_not_flagged(self):
        after = self._base_snapshot()
        reasons = rpam.check_unresolved({}, after, "Ganz normaler Titel")
        assert not any("nicht darstellbar" in r for r in reasons)

    def test_feat_notation_parens_not_flagged(self):
        """Final-Audit-Fund: sanitize_filename() aendert '(feat. X)' zu
        'feat. X' (FEAT_NOTATION_PATTERN, harmlose, beabsichtigte
        Reformatierung) - das ist KEIN illegales Zeichen und darf nicht
        als UNRESOLVED gemeldet werden (real bei Nina Chubas 'Verlaufen
        (feat. SIDO)' faelschlich ausgeloest)."""
        after = self._base_snapshot()
        reasons = rpam.check_unresolved({}, after, "Verlaufen (feat. SIDO)")
        assert not any("nicht darstellbar" in r for r in reasons)


# ─────────────────────────────────────────────────────────────────────────
# Snapshot / Diff / Audio-Essenz
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestSnapshotAndAudioEssence:
    def test_snapshot_reads_actual_tags_from_disk(self, tagged_m4a, isolated_artist_dir):
        snap = rpam.snapshot(tagged_m4a, isolated_artist_dir)
        assert snap["title"] == ["Test Titel"]
        assert snap["artist"] == ["Test Artist"]
        assert snap["filename"] == "2024 - Test Titel.m4a"

    def test_snapshot_rereads_after_external_modification(self, tagged_m4a, isolated_artist_dir):
        """Beweist, dass snapshot() kein In-Memory-Objekt cached, sondern
        wirklich erneut von der Platte liest."""
        rpam.snapshot(tagged_m4a, isolated_artist_dir)  # erster Read
        audio = MP4(tagged_m4a)
        audio["©nam"] = ["Geaenderter Titel"]
        audio.save()
        second = rpam.snapshot(tagged_m4a, isolated_artist_dir)
        assert second["title"] == ["Geaenderter Titel"]

    def test_diff_snapshots_excludes_stream_info_and_audio_essence(self):
        before = {"title": ["A"], "stream_info": {"bitrate": "1"}, "audio_essence_md5": "x"}
        after = {"title": ["A"], "stream_info": {"bitrate": "2"}, "audio_essence_md5": "y"}
        assert rpam.diff_snapshots(before, after) == {}

    def test_diff_snapshots_reports_real_changes(self):
        before = {"title": ["A"]}
        after = {"title": ["B"]}
        assert rpam.diff_snapshots(before, after) == {"title": {"before": ["A"], "after": ["B"]}}

    def test_audio_essence_md5_stable_across_tag_only_rewrite(self, tagged_m4a):
        """Kernbeweis der Audiointegritaet: TagWriter darf die Audio-Essenz
        nicht veraendern (siehe TAG01-Testbericht)."""
        from services.metadata.tag_writer import TagWriter

        before_hash = rpam.audio_essence_md5(tagged_m4a)
        writer = TagWriter(logger=Mock())
        writer.write_tags(
            target_path=tagged_m4a, artist="Neuer Artist", title="Neuer Titel",
            album_info={}, track_number=None, genres_result=None,
        )
        after_hash = rpam.audio_essence_md5(tagged_m4a)
        assert before_hash == after_hash
        assert not before_hash.startswith("ERROR")


# ─────────────────────────────────────────────────────────────────────────
# process_file() End-to-End (echter TagWriter, gemockte externe Adapter)
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestProcessFileEndToEnd:
    @pytest.mark.asyncio
    async def test_dry_run_writes_no_tags_and_leaves_file_untouched(
        self, tagged_m4a, isolated_artist_dir
    ):
        processor = make_processor_stub()
        before_hash = rpam.audio_essence_md5(tagged_m4a)
        before_mtime = tagged_m4a.stat().st_mtime

        result = await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=True,
        )

        assert result["dry_run"] is True
        assert tagged_m4a.exists()
        assert tagged_m4a.stat().st_mtime == before_mtime
        assert rpam.audio_essence_md5(tagged_m4a) == before_hash

    @pytest.mark.asyncio
    async def test_dry_run_predicts_changes_without_writing(self, tagged_m4a, isolated_artist_dir):
        """Dry-Run muss geplante Aenderungen tatsaechlich SICHTBAR machen
        (Abschnitt 6 des Auftrags: 'geplante Metadata-Aenderungen
        analysieren') statt nur die unveraenderte Datei zu spiegeln."""
        processor = make_processor_stub()
        processor.title_cleaner.light_title_cleanup.side_effect = (
            lambda title, artist: "Vorhergesagter Neuer Titel"
        )
        before_hash = rpam.audio_essence_md5(tagged_m4a)

        result = await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=True,
        )

        assert result["changes"].get("title") == {
            "before": ["Test Titel"], "after": ["Vorhergesagter Neuer Titel"],
        }
        assert result["status"] == "changed"
        # Trotz vorhergesagter Aenderung: Datei bleibt komplett unangetastet.
        assert MP4(tagged_m4a)["©nam"] == ["Test Titel"]
        assert rpam.audio_essence_md5(tagged_m4a) == before_hash

    @pytest.mark.asyncio
    async def test_filename_rename_stays_within_same_parent_directory(
        self, tagged_m4a, isolated_artist_dir
    ):
        processor = make_processor_stub()
        processor.title_cleaner.light_title_cleanup.side_effect = (
            lambda title, artist: "Ein Ganz Anderer Titel"
        )
        original_parent = tagged_m4a.parent

        result = await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        renamed = original_parent / "2024 - Ein Ganz Anderer Titel.m4a"
        assert renamed.exists()
        assert renamed.parent == original_parent
        assert renamed.suffix == ".m4a"
        assert not tagged_m4a.exists()
        assert result["status"] == "changed"

    @pytest.mark.asyncio
    async def test_filename_collision_blocked_and_marked_unresolved(
        self, tagged_m4a, isolated_artist_dir
    ):
        colliding_target = tagged_m4a.parent / "2024 - Ein Anderer Titel.m4a"
        colliding_target.write_bytes(b"bereits vorhandene, andere Datei")

        processor = make_processor_stub()
        processor.title_cleaner.light_title_cleanup.side_effect = (
            lambda title, artist: "Ein Anderer Titel"
        )

        result = await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        assert tagged_m4a.exists(), "Quelldatei darf bei einer Kollision nicht verschwinden"
        assert colliding_target.read_bytes() == b"bereits vorhandene, andere Datei"
        assert any("Kollision" in u or "existiert bereits" in u for u in result["unresolved"])

    @pytest.mark.asyncio
    async def test_multi_artist_semicolon_split_written_via_real_tagwriter(
        self, isolated_artist_dir
    ):
        path = isolated_artist_dir / "Singles" / "2026 - WARSCHAU.m4a"
        _make_real_m4a(path)
        audio = MP4(path)
        audio["©nam"] = ["WARSCHAU"]
        audio["©ART"] = ["CHAPO102; Gustav"]
        audio["aART"] = ["CHAPO102; Gustav"]
        audio["©alb"] = ["WARSCHAU"]
        audio["©day"] = ["2026"]
        audio.save()

        processor = make_processor_stub()

        result = await rpam.process_file(
            path, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        final_path = isolated_artist_dir / "Singles" / "2026 - WARSCHAU.m4a"
        after = MP4(final_path)
        assert list(after["©ART"]) == ["CHAPO102", "Gustav"]
        freeform = after["----:com.apple.iTunes:ARTISTS"]
        assert [bytes(v).decode("utf-8") for v in freeform] == ["CHAPO102", "Gustav"]
        assert result["status"] == "changed"

    @pytest.mark.asyncio
    async def test_freeform_artists_field_merged_when_more_complete_than_standard_tag(
        self, isolated_artist_dir
    ):
        """Real bei Nina Chuba entdeckt: ©ART enthielt nur den Hauptkuenstler,
        das Freeform-Feld "ARTISTS" aber zusaetzlich einen Feature-Artist als
        zusammengeklebten Wert (['Hauptkuenstler; Feature'] - TAG-01-Altlast).
        Beide Quellen muessen gemeinsam ausgewertet werden."""
        path = isolated_artist_dir / "Singles" / "2025 - Verlaufen.m4a"
        _make_real_m4a(path)
        audio = MP4(path)
        audio["©nam"] = ["Verlaufen"]
        audio["©ART"] = ["Nina Chuba"]  # Feature-Artist fehlt hier komplett
        audio["aART"] = ["Nina Chuba"]
        audio["©alb"] = ["Verlaufen"]
        audio["©day"] = ["2025"]
        audio["----:com.apple.iTunes:ARTISTS"] = [
            MP4FreeForm("Nina Chuba; SIDO".encode("utf-8"))
        ]
        audio.save()

        processor = make_processor_stub()

        result = await rpam.process_file(
            path, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        after = MP4(path)
        assert list(after["©ART"]) == ["Nina Chuba", "SIDO"]
        freeform = after["----:com.apple.iTunes:ARTISTS"]
        assert [bytes(v).decode("utf-8") for v in freeform] == ["Nina Chuba", "SIDO"]
        assert result["status"] == "changed"

    @pytest.mark.asyncio
    async def test_rename_blocked_when_title_has_filename_illegal_characters(
        self, tagged_m4a, isolated_artist_dir
    ):
        """Real beim Nina-Chuba-Validierungslauf aufgetreten: Titel
        'F*cked Up' wurde trotz gleichzeitiger UNRESOLVED-Meldung zu
        'F cked Up.m4a' umbenannt (Leerzeichen statt '*', schlechter als
        der urspruengliche Dateiname). Ein Titel mit dateinamens-illegalen
        Zeichen darf den Rename nicht mehr nur melden, sondern muss ihn
        aktiv verhindern."""
        processor = make_processor_stub()
        processor.title_cleaner.light_title_cleanup.side_effect = (
            lambda title, artist: "F*cked Up"
        )
        original_name = tagged_m4a.name

        result = await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        assert tagged_m4a.exists(), "Datei muss unter ihrem urspruenglichen Namen bleiben"
        assert tagged_m4a.name == original_name
        bad_rename = tagged_m4a.parent / "2024 - F cked Up.m4a"
        assert not bad_rename.exists()
        assert any("dateinamens-illegale Zeichen" in u for u in result["unresolved"])
        # Der Titel-TAG selbst darf trotzdem aktualisiert werden - nur der
        # Dateiname bleibt unangetastet.
        assert MP4(tagged_m4a)["©nam"] == ["F*cked Up"]

    @pytest.mark.asyncio
    async def test_rename_proceeds_for_harmless_feat_notation_reformatting(
        self, tagged_m4a, isolated_artist_dir
    ):
        """Gegenprobe zum vorigen Test: '(feat. X)' im Titel ist KEIN
        illegales Zeichen (FEAT_NOTATION_PATTERN-Reformatierung ist
        beabsichtigt) - der Rename muss ganz normal stattfinden, keine
        UNRESOLVED-Meldung deswegen."""
        processor = make_processor_stub()
        processor.title_cleaner.light_title_cleanup.side_effect = (
            lambda title, artist: "Verlaufen (feat. SIDO)"
        )

        result = await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        renamed = tagged_m4a.parent / "2024 - Verlaufen feat. SIDO.m4a"
        assert renamed.exists(), "Rename muss trotz '(feat. X)' im Titel stattfinden"
        assert not any("dateinamens-illegale Zeichen" in u for u in result["unresolved"])
        assert not any("nicht darstellbar" in u for u in result["unresolved"])

    @pytest.mark.asyncio
    async def test_unresolved_when_replaygain_missing(self, tagged_m4a, isolated_artist_dir):
        processor = make_processor_stub()

        result = await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        assert any("ReplayGain" in u for u in result["unresolved"])

    @pytest.mark.asyncio
    async def test_after_snapshot_matches_independent_reread(self, tagged_m4a, isolated_artist_dir):
        """Kein In-Memory-Objekt: nach process_file() unabhaengig erneut
        von der Platte lesen und mit dem im Result gemeldeten Diff
        vergleichen."""
        processor = make_processor_stub()
        processor.title_cleaner.light_title_cleanup.side_effect = (
            lambda title, artist: "Frisch Verifizierter Titel"
        )

        result = await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        renamed = tagged_m4a.parent / "2024 - Frisch Verifizierter Titel.m4a"
        independent_read = MP4(renamed)
        assert list(independent_read["©nam"]) == ["Frisch Verifizierter Titel"]
        assert result["changes"]["title"]["after"] == ["Frisch Verifizierter Titel"]

    @pytest.mark.asyncio
    async def test_no_audio_reencoding_module_never_imports_audio_enhancer(self):
        # AudioEnhancer wird im Docstring als Begruendung ERWAEHNT (siehe
        # Modul-Docstring), aber nirgends gebunden/importiert - ohne Import
        # existiert im Modul-Namespace kein aufrufbares Symbol dafuer.
        assert "AudioEnhancer" not in dir(rpam)
        assert not hasattr(rpam, "normalize_loudness")
        source = MODULE_PATH.read_text(encoding="utf-8")
        assert "from utils.audio_enhancer import" not in source
        assert "import audio_enhancer" not in source


class TestCorruptedFileErrorIsolation:
    """
    Phase-1-Optimierungsauftrag (2026-09-02, CLAUDE.md Abschnitt 9
    'Fehlerbehandlung': 'beschaedigte Dateien, nicht lesbare Tags' -
    'Ein fehlerhafter Track darf nicht automatisch den gesamten
    Artist-Lauf zerstoeren'): process_file() liest den BEFORE-Snapshot
    (snapshot(), inkl. mutagen.mp4.MP4(path)) VOR dem eigentlichen
    try/except-Block. Fuer eine echte, unlesbare/beschaedigte .m4a-Datei
    wirft mutagen dabei eine Exception, die NICHT vom bestehenden
    try/except in process_file() abgefangen wird - sie propagiert
    ungefangen aus process_file() heraus und wuerde in main() die
    komplette for-Schleife ueber alle Dateien des Artists abbrechen,
    statt nur DIESE eine Datei als 'error' zu protokollieren und mit den
    uebrigen Dateien fortzufahren."""

    @pytest.mark.asyncio
    async def test_unreadable_file_returns_error_result_instead_of_raising(
        self, isolated_artist_dir
    ):
        corrupted = isolated_artist_dir / "Singles" / "2024 - Corrupted.m4a"
        corrupted.write_bytes(b"this-is-not-a-valid-mp4-container")

        processor = make_processor_stub()

        result = await rpam.process_file(
            corrupted, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        assert result["status"] == "error"
        assert result["error"]

    @pytest.mark.asyncio
    async def test_one_corrupted_file_does_not_abort_processing_of_other_files(
        self, isolated_artist_dir, tagged_m4a
    ):
        """Reproduziert die eigentliche Auswirkung direkt auf Loop-Ebene
        (wie main()): eine beschaedigte Datei VOR einer gesunden Datei in
        derselben Iteration darf die gesunde Datei nicht unverarbeitet
        lassen."""
        corrupted = isolated_artist_dir / "Singles" / "2024 - Corrupted.m4a"
        corrupted.write_bytes(b"this-is-not-a-valid-mp4-container")

        processor = make_processor_stub()
        log = rpam.ReprocessLogger(isolated_artist_dir / "test.log")

        results = []
        for f in sorted(isolated_artist_dir.rglob("*.m4a")):
            r = await rpam.process_file(
                f, isolated_artist_dir, processor, Mock(), Mock(), log,
                dry_run=False,
            )
            results.append(r)

        statuses = {r["file"]: r["status"] for r in results}
        assert any(s == "error" for s in statuses.values())
        assert any(s != "error" for s in statuses.values()), (
            "Die gesunde Datei wurde nicht erreicht/verarbeitet - die "
            "beschaedigte Datei hat die Schleife vorzeitig beendet."
        )


# ─────────────────────────────────────────────────────────────────────────
# Genre-Separator
#
# Der produktive TagWriter (services/metadata/tag_writer.py) schrieb das
# primaere Genre-Tag (©gen) bei mehreren Genres frueher mit " / " als
# Separator (z.B. "Hip Hop / Deutschrap / Emo Rap / Cloud Rap"). Seit
# Phase 2 (2026-09) schreibt TagWriter direkt "; " (z.B. "Hip Hop;
# Deutschrap; Emo Rap; Cloud Rap") - vorab ueber ein auf dieses
# Reprocessing-Script begrenztes Phase-1-Shim kontrolliert validiert.
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestGenreSeparator:
    @pytest.mark.asyncio
    async def test_real_write_uses_semicolon_separator_for_multiple_genres(
        self, tagged_m4a, isolated_artist_dir
    ):
        processor = make_processor_stub()
        processor.genre_processor.determine_genre_with_fallbacks = AsyncMock(
            return_value=DummyMBIdsResult(
                primary="Hip Hop",
                secondary=["Deutschrap", "Emo Rap", "Cloud Rap"],
            )
        )

        result = await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        after = MP4(tagged_m4a)
        assert after["©gen"] == ["Hip Hop; Deutschrap; Emo Rap; Cloud Rap"]
        # Freeform-GENRE-Atom bleibt komma-separiert (unveraendert).
        freeform_genre = after["----:com.apple.iTunes:GENRE"]
        assert bytes(freeform_genre[0]).decode("utf-8") == "Hip Hop, Deutschrap, Emo Rap, Cloud Rap"
        assert result["status"] == "changed"

    @pytest.mark.asyncio
    async def test_real_write_single_genre_untouched(self, tagged_m4a, isolated_artist_dir):
        """Einzelnes Genre (kein secondary) - kein Separator im Spiel."""
        processor = make_processor_stub()  # Default: primary="Pop", secondary=[]

        await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        after = MP4(tagged_m4a)
        assert after["©gen"] == ["Pop"]

    @pytest.mark.asyncio
    async def test_dry_run_predicts_semicolon_separator(self, tagged_m4a, isolated_artist_dir):
        """Dry-Run darf keine Datei schreiben, muss aber das tatsaechliche
        TagWriter-Endergebnis vorhersagen."""
        processor = make_processor_stub()
        processor.genre_processor.determine_genre_with_fallbacks = AsyncMock(
            return_value=DummyMBIdsResult(
                primary="Hip Hop",
                secondary=["Deutschrap", "Emo Rap", "Cloud Rap"],
            )
        )
        before_hash = rpam.audio_essence_md5(tagged_m4a)

        result = await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=True,
        )

        assert result["changes"]["genre_tag"] == {
            "before": [], "after": ["Hip Hop; Deutschrap; Emo Rap; Cloud Rap"],
        }
        # Weiterhin komplett unangetastet.
        assert MP4(tagged_m4a).get("©gen") is None
        assert rpam.audio_essence_md5(tagged_m4a) == before_hash


class TestGenreDowngradeProtection:
    """
    Phase-1-Optimierungsauftrag (2026-09-02): der bestehende ©gen-Tag kann
    bereits mehrere Genre-Werte enthalten (z.B. aus einem frueheren,
    reichhaltigeren Reprocessing-Lauf oder manueller Pflege). Eine neue
    determine_genre_with_fallbacks()-Anfrage kann - je nach aktueller
    MusicBrainz-/Last.fm-/Mapping-Antwort - diesmal nur ein einzelnes,
    schwaecheres Ergebnis liefern (kein Fehler, sondern normales
    Antwortverhalten externer Quellen). Analog zur bereits bestehenden
    MB-IDs-Regel ("keine vorhandenen korrekten IDs unnoetig ueberschreiben")
    soll ein bereits reichhaltigerer bestehender Genre-Tag nicht durch ein
    schwaecheres frisches Ergebnis ERSETZT werden - stattdessen UNRESOLVED,
    analog zum bereits etablierten "nicht raten"-Muster (z.B.
    Dateinamens-illegale-Zeichen-Rename-Block).
    """

    @pytest.mark.asyncio
    async def test_richer_existing_genre_is_not_downgraded_by_weaker_fresh_result(
        self, tagged_m4a, isolated_artist_dir
    ):
        audio = MP4(tagged_m4a)
        audio["©gen"] = ["Hip Hop; Deutschrap; Emo Rap; Cloud Rap"]
        audio.save()

        processor = make_processor_stub()  # Default: primary="Pop", secondary=[]

        result = await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        after = MP4(tagged_m4a)
        assert after["©gen"] == ["Hip Hop; Deutschrap; Emo Rap; Cloud Rap"], (
            "Ein reichhaltigerer bestehender Genre-Tag darf nicht durch ein "
            "schwaecheres frisches Einzel-Genre-Ergebnis ersetzt werden."
        )
        assert any("Genre" in u for u in result["unresolved"]), (
            "Die unterlassene Genre-Aktualisierung muss als UNRESOLVED "
            "protokolliert werden, nicht stillschweigend uebersprungen."
        )

    @pytest.mark.asyncio
    async def test_legacy_slash_separator_is_also_recognized(
        self, tagged_m4a, isolated_artist_dir
    ):
        """Vor der '; '-Separator-Umstellung (2026-09, tag_writer.py)
        geschriebene Bestandsdateien nutzen ' / ' als Trenner - die
        Downgrade-Erkennung muss auch diese aeltere Schreibweise als
        Mehrfach-Genre zaehlen, nicht als einen einzelnen langen String."""
        audio = MP4(tagged_m4a)
        audio["©gen"] = ["Hip Hop / Deutschrap / Emo Rap"]
        audio.save()

        processor = make_processor_stub()  # Default: primary="Pop", secondary=[]

        await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        after = MP4(tagged_m4a)
        assert after["©gen"] == ["Hip Hop / Deutschrap / Emo Rap"]

    @pytest.mark.asyncio
    async def test_equal_or_richer_fresh_result_still_overwrites(
        self, tagged_m4a, isolated_artist_dir
    ):
        """Gegenprobe: liefert die frische Bestimmung GLEICH viele oder mehr
        Genre-Werte, greift der Schutz nicht - eine echte Verbesserung/
        gleichwertige Neubestimmung wird weiterhin normal geschrieben."""
        audio = MP4(tagged_m4a)
        audio["©gen"] = ["Hip Hop; Deutschrap"]
        audio.save()

        processor = make_processor_stub()
        processor.genre_processor.determine_genre_with_fallbacks = AsyncMock(
            return_value=DummyMBIdsResult(
                primary="Hip Hop", secondary=["Deutschrap", "Cloud Rap"],
            )
        )

        await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        after = MP4(tagged_m4a)
        assert after["©gen"] == ["Hip Hop; Deutschrap; Cloud Rap"]

    @pytest.mark.asyncio
    async def test_dry_run_prediction_matches_protected_live_outcome(
        self, tagged_m4a, isolated_artist_dir
    ):
        """Dry-Run-Vorhersage muss identisch zum echten Schreibverhalten
        sein - auch fuer den neuen Schutzpfad."""
        audio = MP4(tagged_m4a)
        audio["©gen"] = ["Hip Hop; Deutschrap; Emo Rap; Cloud Rap"]
        audio.save()
        before_hash = rpam.audio_essence_md5(tagged_m4a)

        processor = make_processor_stub()  # Default: primary="Pop", secondary=[]

        result = await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=True,
        )

        assert "genre_tag" not in result["changes"]
        assert any("Genre" in u for u in result["unresolved"])
        assert MP4(tagged_m4a)["©gen"] == ["Hip Hop; Deutschrap; Emo Rap; Cloud Rap"]
        assert rpam.audio_essence_md5(tagged_m4a) == before_hash


# ─────────────────────────────────────────────────────────────────────────
# Album- vs. Singles-Dateinamenskonvention
#
# Waehrend der Vorbereitung des zweiten Validierungslaufs (Nina Chuba, echte
# Mehr-Album-Discographie) entdeckt: die urspruengliche Implementierung
# wandte die Singles-Konvention ("{Jahr} - {Titel}.ext") blind auf JEDE
# Datei an - CHAPO102 bestand ausschliesslich aus Singles und deckte diesen
# Pfad nie ab. Fuer echte Album-Tracks (Dateiname "{Tracknummer} - {Titel}",
# Parent-Ordner z.B. "2023 - Glas") haette das jede Album-Datei faelschlich
# in die Jahres-Konvention umbenannt. Fix: Unterscheidung anhand des
# tatsaechlichen Parent-Ordnernamens ("Singles") bzw. des tatsaechlich
# vorhandenen trkn-Tags - kein Raten.
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestAlbumVsSinglesFilenameConvention:
    @pytest.fixture
    def album_track_with_number(self, isolated_artist_dir):
        album_dir = isolated_artist_dir / "2020 - Power EP"
        album_dir.mkdir()
        path = album_dir / "01 - Alter Titel.m4a"
        _make_real_m4a(path)
        audio = MP4(path)
        audio["©nam"] = ["Alter Titel"]
        audio["©ART"] = ["Nina Chuba"]
        audio["aART"] = ["Nina Chuba"]
        audio["©alb"] = ["Power EP"]
        audio["©day"] = ["2020"]
        audio["trkn"] = [(1, 0)]
        audio.save()
        return path

    @pytest.fixture
    def album_track_without_number(self, isolated_artist_dir):
        album_dir = isolated_artist_dir / "2020 - Power EP"
        album_dir.mkdir()
        path = album_dir / "Alter Titel Ohne Tracknummer.m4a"
        _make_real_m4a(path)
        audio = MP4(path)
        audio["©nam"] = ["Alter Titel Ohne Tracknummer"]
        audio["©ART"] = ["Nina Chuba"]
        audio["aART"] = ["Nina Chuba"]
        audio["©alb"] = ["Power EP"]
        audio["©day"] = ["2020"]
        audio.save()
        return path

    @pytest.mark.asyncio
    async def test_album_track_renamed_via_track_number_not_year(
        self, album_track_with_number, isolated_artist_dir
    ):
        processor = make_processor_stub()
        processor.title_cleaner.light_title_cleanup.side_effect = (
            lambda title, artist: "Neuer Titel"
        )

        result = await rpam.process_file(
            album_track_with_number, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        renamed = album_track_with_number.parent / "01 - Neuer Titel.m4a"
        assert renamed.exists(), "Album-Track muss ueber Tracknummer, nicht Jahr umbenannt werden"
        wrong_year_based = album_track_with_number.parent / "2020 - Neuer Titel.m4a"
        assert not wrong_year_based.exists()
        assert result["status"] == "changed"

    @pytest.mark.asyncio
    async def test_album_track_without_track_number_is_not_renamed(
        self, album_track_without_number, isolated_artist_dir
    ):
        processor = make_processor_stub()
        processor.title_cleaner.light_title_cleanup.side_effect = (
            lambda title, artist: "Neuer Titel"
        )
        original_name = album_track_without_number.name

        result = await rpam.process_file(
            album_track_without_number, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        assert album_track_without_number.exists(), (
            "Ohne trkn-Tag darf kein Rename geraten werden - Datei muss "
            "unter ihrem urspruenglichen Namen liegen bleiben"
        )
        assert album_track_without_number.name == original_name
        # Titel-Tag selbst darf trotzdem aktualisiert werden - nur der
        # Dateiname bleibt unangetastet.
        assert result["changes"].get("title", {}).get("after") == ["Neuer Titel"]


# ─────────────────────────────────────────────────────────────────────────
# Verzeichnis-Invariante
# ─────────────────────────────────────────────────────────────────────────


class TestDirectorySnapshot:
    def test_snapshot_directory_tree_detects_no_change(self, tagged_m4a, isolated_artist_dir):
        before = rpam.snapshot_directory_tree(isolated_artist_dir)
        after = rpam.snapshot_directory_tree(isolated_artist_dir)
        assert before == after

    def test_snapshot_directory_tree_detects_new_file(self, tagged_m4a, isolated_artist_dir):
        before = rpam.snapshot_directory_tree(isolated_artist_dir)
        (isolated_artist_dir / "Singles" / "neu.m4a").write_bytes(b"x")
        after = rpam.snapshot_directory_tree(isolated_artist_dir)
        assert before != after
        assert set(after["files"]) - set(before["files"]) == {"Singles/neu.m4a"}

    def test_snapshot_directory_tree_detects_new_directory(self, tagged_m4a, isolated_artist_dir):
        before = rpam.snapshot_directory_tree(isolated_artist_dir)
        (isolated_artist_dir / "Album").mkdir()
        after = rpam.snapshot_directory_tree(isolated_artist_dir)
        assert "Album" in after["dirs"] - before["dirs"]


# ─────────────────────────────────────────────────────────────────────────
# Cover-Reprocessing: Suche IMMER, auch bei bereits vorhandenem Cover
# (Phase 1, 2026-09-02 - docs/METADATA_REPROCESSING.md Abschnitt 6 behauptet
# dies bereits, war aber bisher nicht durch einen eigenen Test abgesichert)
# ─────────────────────────────────────────────────────────────────────────


class TestCoverAlwaysSearched:
    @pytest.mark.asyncio
    async def test_cover_search_runs_even_when_cover_already_embedded(
        self, tagged_m4a, isolated_artist_dir
    ):
        audio = MP4(tagged_m4a)
        from mutagen.mp4 import MP4Cover

        audio["covr"] = [MP4Cover(b"existing-cover-bytes", imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()

        processor = make_processor_stub(cover_bytes=None, cover_source=None)

        await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        processor.cover_processor.get_cover_art.assert_called_once()

    @pytest.mark.asyncio
    async def test_cover_search_runs_in_dry_run_too(self, tagged_m4a, isolated_artist_dir):
        processor = make_processor_stub(cover_bytes=None, cover_source=None)

        await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=True,
        )

        processor.cover_processor.get_cover_art.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────
# MusicBrainz-IDs: bestehende korrekte IDs werden nicht unnoetig ueberschrieben
# (Phase 1, 2026-09-02 - process_file() implementiert dies bereits korrekt,
# war aber bisher nicht durch einen eigenen Test abgesichert)
# ─────────────────────────────────────────────────────────────────────────


class TestMusicBrainzIdsNotOverwritten:
    @pytest.mark.asyncio
    async def test_existing_recording_id_wins_over_differing_fresh_id(
        self, tagged_m4a, isolated_artist_dir
    ):
        from mutagen.mp4 import MP4FreeForm

        audio = MP4(tagged_m4a)
        audio["----:com.apple.iTunes:MusicBrainz Recording Id"] = [
            MP4FreeForm(b"existing-recording-id-0000")
        ]
        audio.save()

        processor = make_processor_stub()
        processor.genre_processor.determine_genre_with_fallbacks = AsyncMock(
            return_value=DummyMBIdsResult(
                primary="Pop", secondary=[],
                mb_ids={"recording_id": "different-fresh-recording-id-1111"},
            )
        )

        await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        after = MP4(tagged_m4a)
        recording_id = bytes(
            after["----:com.apple.iTunes:MusicBrainz Recording Id"][0]
        ).decode("utf-8")
        assert recording_id == "existing-recording-id-0000"

    @pytest.mark.asyncio
    async def test_missing_id_is_filled_from_fresh_result(
        self, tagged_m4a, isolated_artist_dir
    ):
        """Gegenprobe: fehlt eine ID im Bestand, wird sie aus dem frischen
        Ergebnis ergaenzt - der Schutz gilt nur fuer bereits VORHANDENE
        Werte, nicht als generelle Sperre."""
        processor = make_processor_stub()
        processor.genre_processor.determine_genre_with_fallbacks = AsyncMock(
            return_value=DummyMBIdsResult(
                primary="Pop", secondary=[],
                mb_ids={"recording_id": "fresh-recording-id-2222"},
            )
        )

        await rpam.process_file(
            tagged_m4a, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        after = MP4(tagged_m4a)
        recording_id = bytes(
            after["----:com.apple.iTunes:MusicBrainz Recording Id"][0]
        ).decode("utf-8")
        assert recording_id == "fresh-recording-id-2222"


# ─────────────────────────────────────────────────────────────────────────
# main() - Integrationstests (Phase 1, 2026-09-02: bisher vollstaendig
# ungetestet - CLI-Parsing, Post-Run-Safety-Check-Aggregation,
# Fehlerisolierung auf Schleifenebene)
# ─────────────────────────────────────────────────────────────────────────


class TestMainIntegration:
    @pytest.mark.asyncio
    async def test_mixed_success_and_error_summary_and_overall_status(
        self, isolated_artist_dir, tagged_m4a, monkeypatch
    ):
        corrupted = isolated_artist_dir / "Singles" / "2024 - Corrupted.m4a"
        corrupted.write_bytes(b"not-a-valid-mp4-container")

        stub_processor = make_processor_stub()
        stub_processor.aclose = AsyncMock(return_value=None)
        stub_processor.cleanup = Mock(return_value=None)

        monkeypatch.setattr(rpam, "EnhancedMetadataProcessor", lambda config: stub_processor)
        monkeypatch.setattr(rpam, "MusicBrainzClient", lambda: Mock())
        monkeypatch.setattr(rpam, "LastFMClient", lambda: Mock())
        monkeypatch.setattr(
            sys, "argv",
            [
                "reprocess_artist_metadata.py",
                "--input", str(isolated_artist_dir),
                "--dry-run",
                "--no-production-check",
            ],
        )

        summary = await rpam.main()

        assert summary["files_processed"] == 2
        assert summary["errors"] == 1
        assert summary["changed"] + summary["unchanged"] == 1
        assert summary["directory_structure_changes"] == 0
        assert summary["files_created"] == 0
        assert summary["files_deleted"] == 0
        assert summary["production_file_changes"] == 0
        # Ein Fehler im Lauf darf den Gesamtstatus nicht als sauberes PASS
        # ausweisen - auch wenn die uebrige Datei erfolgreich verarbeitet
        # wurde.
        assert summary["overall"] == "FAIL"

    @pytest.mark.asyncio
    async def test_no_production_check_flag_disables_production_comparison(
        self, isolated_artist_dir, tagged_m4a, monkeypatch
    ):
        stub_processor = make_processor_stub()
        stub_processor.aclose = AsyncMock(return_value=None)
        stub_processor.cleanup = Mock(return_value=None)

        monkeypatch.setattr(rpam, "EnhancedMetadataProcessor", lambda config: stub_processor)
        monkeypatch.setattr(rpam, "MusicBrainzClient", lambda: Mock())
        monkeypatch.setattr(rpam, "LastFMClient", lambda: Mock())
        monkeypatch.setattr(
            sys, "argv",
            [
                "reprocess_artist_metadata.py",
                "--input", str(isolated_artist_dir),
                "--dry-run",
                "--no-production-check",
            ],
        )

        summary = await rpam.main()

        assert summary["errors"] == 0
        assert summary["files_processed"] == 1
        assert summary["directory_structure_changes"] == 0
