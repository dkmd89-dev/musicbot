"""
AE-11 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md): TagWriter.write_tags()
schrieb ueber mutagen.audio.save() direkt in-place in die bereits an ihrem
finalen Library-Pfad liegende Mediendatei (rb+, chunk-basiertes
Byte-Shifting, kein Tempfile/Rename - direkt im installierten
mutagen-Quellcode verifiziert). Ein Fehler waehrend dieses Vorgangs konnte
die zuvor gueltige Datei beschaedigen UND wurde von write_tags() intern
verschluckt (kein Re-Raise) - der uebergeordnete FINDING-2-Cleanup
(enhanced_metadata_processor.py) wurde dadurch nie erreicht, obwohl er
genau fuer diesen Fall entworfen wurde.

Empirisch im AE-11-Audit reproduziert: mutagen/ffprobe melden eine derart
beschaedigte Datei faelschlich als gesund (korrekte Dauer, kein Fehler) -
nur ein echter Decode-Pass deckt die Korruption auf. Deshalb pruefen Test D
und E hier zusaetzlich zur Byte-Identitaet auch einen echten
ffmpeg-Decode-Pass (wenn ffmpeg auf PATH verfuegbar ist).

Fix: write_tags() taggt jetzt eine temporaere Sibling-Kopie (garantiert
selbes Verzeichnis/Dateisystem, exakt das bereits in
utils/filenamefixer.py::move_to_library() etablierte Muster) und ersetzt
das Original erst bei vollem Erfolg atomar per Path.replace(). Bei jedem
Fehler bleibt das Original byteidentisch, die temporaere Datei wird
entfernt, und die urspruengliche Exception wird unveraendert weitergereicht
statt verschluckt zu werden.
"""

import shutil
import subprocess
from unittest.mock import Mock

import pytest
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from services.metadata.tag_writer import TagWriter

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def _make_real_mp3(path, duration_seconds=1):
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_seconds}",
            "-c:a", "libmp3lame", "-b:a", "192k", str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )


def _make_real_m4a(path, duration_seconds=1):
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_seconds}",
            "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )


def _ffmpeg_decode_succeeds(path) -> bool:
    # -map 0:a:0 beschraenkt den Decode-OUTPUT auf den Audio-Stream - ein
    # eingebettetes Cover wird von mutagen/ffmpeg als separater
    # Bild-("Video"-)Stream behandelt. ffmpegs anfaengliche Stream-Analyse
    # versucht dennoch, JEDEN Stream (auch das absichtlich ungueltige
    # Test-Fake-Cover in diesen Tests) kurz anzusehen und schreibt dabei
    # eine harmlose Warnung auf stderr, unabhaengig vom -map. Massgeblich
    # fuer "wurde der Audio-Stream sauber dekodiert" ist daher der
    # Returncode des tatsaechlich gemappten Outputs, nicht ein leeres
    # stderr.
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


@pytest.fixture
def writer():
    return TagWriter(logger=Mock())


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg nicht auf PATH verfuegbar")
class TestRealMp3AtomicReplace:
    def test_write_failure_leaves_original_untouched_and_cleans_up_tmp(
        self, writer, tmp_path, monkeypatch
    ):
        """Test A + D: simulierter Fehler waehrend audio.save() (deterministisch,
        kein Timing) - Original bleibt byteidentisch, kein Tmp-Rest, Exception
        propagiert."""
        path = tmp_path / "track.mp3"
        _make_real_mp3(path)
        original_bytes = path.read_bytes()

        def raising_save(self, *a, **kw):
            raise OSError("SIMULATED audio.save() FAILURE")

        monkeypatch.setattr("mutagen.id3.ID3.save", raising_save)

        with pytest.raises(OSError, match="SIMULATED audio.save"):
            writer.write_tags(
                target_path=path,
                artist="Artist",
                title="Title",
                album_info={},
                track_number=None,
                genres_result=None,
            )

        assert path.read_bytes() == original_bytes, (
            "Original muss nach fehlgeschlagenem Tagging byteidentisch bleiben"
        )
        assert _ffmpeg_decode_succeeds(path), (
            "Original muss nach fehlgeschlagenem Tagging weiterhin sauber "
            "dekodierbar sein"
        )
        leftover = list(tmp_path.glob(".track.mp3.tmp_*"))
        assert not leftover, f"Temporaere Datei(en) nicht aufgeraeumt: {leftover}"

    def test_successful_tagging_replaces_atomically(self, writer, tmp_path):
        """Test B: erfolgreicher Lauf - neue Tags vorhanden, Original-Pfad
        zeigt jetzt auf die getaggte Datei, kein Tmp-Rest, Decode bleibt
        sauber."""
        path = tmp_path / "track.mp3"
        _make_real_mp3(path)

        writer.write_tags(
            target_path=path,
            artist="Real Artist",
            title="Real Title",
            album_info={"album": "Real Album", "year": 2026},
            track_number=3,
            genres_result=None,
            cover_art=b"\xff\xd8\xff" + b"\x00" * 500,
        )

        assert path.exists()
        tags = ID3(path)
        assert tags["TIT2"].text == ["Real Title"]
        assert tags["TPE1"].text == ["Real Artist"]
        assert tags.getall("APIC:Cover")[0].data == b"\xff\xd8\xff" + b"\x00" * 500

        assert _ffmpeg_decode_succeeds(path), "Getaggte Datei muss sauber dekodierbar sein"
        leftover = list(tmp_path.glob(".track.mp3.tmp_*"))
        assert not leftover, f"Temporaere Datei(en) nach Erfolg nicht aufgeraeumt: {leftover}"


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg nicht auf PATH verfuegbar")
class TestRealM4aAtomicReplace:
    def test_write_failure_leaves_original_untouched_and_cleans_up_tmp(
        self, writer, tmp_path, monkeypatch
    ):
        """Test A + E: analog zu MP3, fuer den MP4-Pfad."""
        path = tmp_path / "track.m4a"
        _make_real_m4a(path)
        original_bytes = path.read_bytes()

        def raising_save(self, *a, **kw):
            raise OSError("SIMULATED audio.save() FAILURE")

        monkeypatch.setattr("mutagen.mp4.MP4.save", raising_save)

        with pytest.raises(OSError, match="SIMULATED audio.save"):
            writer.write_tags(
                target_path=path,
                artist="Artist",
                title="Title",
                album_info={},
                track_number=None,
                genres_result=None,
            )

        assert path.read_bytes() == original_bytes, (
            "Original muss nach fehlgeschlagenem Tagging byteidentisch bleiben"
        )
        assert _ffmpeg_decode_succeeds(path), (
            "Original muss nach fehlgeschlagenem Tagging weiterhin sauber "
            "dekodierbar sein"
        )
        leftover = list(tmp_path.glob(".track.m4a.tmp_*"))
        assert not leftover, f"Temporaere Datei(en) nicht aufgeraeumt: {leftover}"

    def test_successful_tagging_replaces_atomically(self, writer, tmp_path):
        """Test B fuer MP4/M4A."""
        path = tmp_path / "track.m4a"
        _make_real_m4a(path)

        writer.write_tags(
            target_path=path,
            artist="Real Artist",
            title="Real Title",
            album_info={"album": "Real Album", "year": 2026},
            track_number=3,
            genres_result=None,
            cover_art=b"\xff\xd8\xff" + b"\x00" * 500,
        )

        assert path.exists()
        tags = MP4(path)
        assert tags["©nam"] == ["Real Title"]
        assert tags["©ART"] == ["Real Artist"]
        assert tags["covr"][0] == b"\xff\xd8\xff" + b"\x00" * 500

        assert _ffmpeg_decode_succeeds(path), "Getaggte Datei muss sauber dekodierbar sein"
        leftover = list(tmp_path.glob(".track.m4a.tmp_*"))
        assert not leftover, f"Temporaere Datei(en) nach Erfolg nicht aufgeraeumt: {leftover}"


class TestHigherLevelFinding2CleanupIntegration:
    """Test C: der vollstaendige FINDING-2-Fehlerpfad aus
    enhanced_metadata_processor.py, nachgebaut mit derselben Cleanup-Logik
    (Zeilen 878-907) - beweist, dass eine jetzt tatsaechlich propagierende
    write_tags()-Exception den bereits vorhandenen Orphan-Cleanup erreicht,
    OHNE dass dabei ein bereits gueltiges Original geloescht wird, solange
    write_tags() selbst vor dem Replace scheitert."""

    def test_failed_write_tags_triggers_cleanup_of_incomplete_library_file(
        self, tmp_path, monkeypatch
    ):
        library_path = tmp_path / "library_track.mp3"
        # Simuliert das Ergebnis von move_to_library(): eine bereits an
        # ihrem finalen Library-Pfad liegende, valide Datei.
        _make_real_mp3(library_path) if FFMPEG_AVAILABLE else library_path.write_bytes(
            b"not-a-real-mp3-file"
        )

        writer = TagWriter(logger=Mock())

        def raising_save(self, *a, **kw):
            raise OSError("SIMULATED audio.save() FAILURE")

        if FFMPEG_AVAILABLE:
            monkeypatch.setattr("mutagen.id3.ID3.save", raising_save)

        # Nachbau des FINDING-2-Cleanup-Blocks aus
        # enhanced_metadata_processor.py:878-907.
        try:
            writer.write_tags(
                target_path=library_path,
                artist="Artist",
                title="Title",
                album_info={},
                track_number=None,
                genres_result=None,
            )
        except Exception:
            if library_path.exists():
                library_path.unlink()
            cleanup_triggered = True
            reraised = True
        else:
            cleanup_triggered = False
            reraised = False

        assert reraised, (
            "write_tags() muss bei einem Tagging-Fehler eine Exception werfen, "
            "damit der FINDING-2-Cleanup ueberhaupt erreicht wird"
        )
        assert cleanup_triggered
        assert not library_path.exists(), (
            "Der FINDING-2-Cleanup muss die unvollstaendig getaggte "
            "Library-Datei entfernen"
        )

    def test_successful_write_tags_never_triggers_finding2_cleanup(self, tmp_path):
        library_path = tmp_path / "library_track.mp3"
        if FFMPEG_AVAILABLE:
            _make_real_mp3(library_path)
        else:
            library_path.write_bytes(b"not-a-real-mp3-file")

        writer = TagWriter(logger=Mock())

        cleanup_triggered = False
        try:
            writer.write_tags(
                target_path=library_path,
                artist="Artist",
                title="Title",
                album_info={},
                track_number=None,
                genres_result=None,
            )
        except Exception:
            if library_path.exists():
                library_path.unlink()
            cleanup_triggered = True

        assert not cleanup_triggered, (
            "Erfolgreiches Tagging darf den FINDING-2-Cleanup nicht ausloesen"
        )
        assert library_path.exists(), (
            "Die erfolgreich getaggte Datei muss an ihrem Library-Pfad bleiben"
        )
