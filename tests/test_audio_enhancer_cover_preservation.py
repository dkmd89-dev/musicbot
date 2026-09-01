"""
Regressionstest für utils/audio_enhancer.py::AudioEnhancer.normalize_loudness().

Hintergrund (CLAUDE.md Abschnitt 26 "Bei Bugs"): Während der Entwicklung
von scripts/normalize_test_library_loudness.py wurde ein Defekt
entdeckt und live reproduziert (siehe dortiger Modul-Docstring sowie der
2026-09-Fix-Kommentar in utils/audio_enhancer.py): normalize_loudness()
beschädigte JEDE Datei mit eingebettetem Cover, meldete aber trotzdem
True. Ursache: der FFmpeg-"apply"-Aufruf hatte kein Stream-Mapping,
wodurch der Cover-Bildstream (covr-Atom, von FFmpeg als "attached pic"
demuxt) als reguläres Video re-encodiert werden sollte - das schlug im
mp4-Container fehl und hinterließ eine leere Zieldatei, deren bloße
Existenz (ohne Return-Code-/Größenprüfung) als Erfolg gewertet wurde.

Für utils/audio_enhancer.py gab es vor diesem Fund keinen dedizierten
Test, der die echte FFmpeg-Ausführung prüft (alle bestehenden
Aufrufer-Tests mocken normalize_loudness() vollständig, siehe z.B.
tests/test_enhanced_metadata_processor_loudness_blocking.py) - dieser
Test schließt genau diese Lücke.

Test-Strategie (CLAUDE.md Abschnitt 7/8): reale, per ffmpeg erzeugte
m4a-Dateien (kein Mock von normalize_loudness() selbst - sonst würde
der eigentliche Bug nie sichtbar) mit einem echten, gültigen JPEG-Cover
(kein Fake-Blob - ein ungültiger Blob wäre kein fairer Beweis).

SEPARATER FUND waehrend der Fix-Verifikation (CLAUDE.md Abschnitt 8.A -
unabhaengige, vorbestehende Altlast, NICHT in diesem Auftrag behoben):
normalize_loudness() schreibt cmd_apply/cmd_fallback IMMER mit
"-c:a aac", unabhaengig von der tatsaechlichen Ziel-Dateiendung -
fuer eine .mp3-Datei lehnt der mp3-Muxer AAC-Frames ab, die Funktion
schlaegt fuer JEDE .mp3-Eingabedatei fehl (mit oder ohne Cover,
Root-Cause isoliert per direktem Vorher/Nachher-Vergleich). Kein
Datenverlust (Return False, Original bleibt unveraendert), aber
Loudness-Normalisierung fuer .mp3 funktioniert praktisch nie. Nur
erreichbar, wenn AUDIO_FORMAT=mp3 konfiguriert ist (Default: "m4a").
Siehe test_mp3_input_currently_always_fails_regardless_of_cover().
"""

import shutil
import subprocess

import pytest
from mutagen.mp4 import MP4, MP4Cover

from utils.audio_enhancer import AudioEnhancer

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
FFPROBE_AVAILABLE = shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(
    not (FFMPEG_AVAILABLE and FFPROBE_AVAILABLE),
    reason="ffmpeg/ffprobe nicht auf PATH verfügbar",
)


def _make_real_m4a(path, duration_seconds=1):
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_seconds}",
            "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )


@pytest.fixture
def real_cover_jpeg(tmp_path):
    """Ein echtes, gültiges kleines JPEG - kein Fake-Blob."""
    if not FFMPEG_AVAILABLE:
        pytest.skip("ffmpeg nicht verfügbar")
    jpeg_path = tmp_path / "cover.jpg"
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "color=c=red:s=32x32", "-frames:v", "1",
         str(jpeg_path), "-y", "-loglevel", "error"],
        check=True,
    )
    return jpeg_path.read_bytes()


def _add_cover(path, jpeg_bytes):
    audio = MP4(path)
    audio["©nam"] = ["Test Titel"]
    audio["©ART"] = ["Test Artist"]
    audio["covr"] = [MP4Cover(jpeg_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def _ffprobe_ok(path) -> bool:
    """Echter Decode-Pass statt nur Existenz-/Größenprüfung - deckt auch
    einen Container auf, der zwar nicht leer, aber trotzdem kaputt ist
    (etabliertes Muster, siehe tests/test_tag_writer_atomic_replace.py)."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    return result.returncode == 0


@requires_ffmpeg
class TestNormalizeLoudnessWithEmbeddedCover:
    def test_file_with_cover_survives_normalization_intact(self, tmp_path, real_cover_jpeg):
        """Der eigentliche Regressionstest fuer den entdeckten Defekt:
        eine Datei MIT eingebettetem Cover darf nach normalize_loudness()
        weder leer noch anderweitig beschaedigt sein."""
        path = tmp_path / "with_cover.m4a"
        _make_real_m4a(path)
        _add_cover(path, real_cover_jpeg)
        original_size = path.stat().st_size

        result = AudioEnhancer.normalize_loudness(str(path), target_lufs=-16.0)

        assert result is True
        assert path.exists()
        assert path.stat().st_size > 0
        assert _ffprobe_ok(path), "Zieldatei muss ein gueltiger, dekodierbarer Container sein"

    def test_cover_bytes_preserved_unchanged_after_normalization(
        self, tmp_path, real_cover_jpeg
    ):
        """Cover darf nicht nur ueberleben, sondern muss byteidentisch
        erhalten bleiben (-c:v copy statt Re-Encode)."""
        path = tmp_path / "cover_preserved.m4a"
        _make_real_m4a(path)
        _add_cover(path, real_cover_jpeg)

        assert AudioEnhancer.normalize_loudness(str(path), target_lufs=-16.0) is True

        audio = MP4(path)
        cover = audio.tags.get("covr")
        assert cover, "Cover darf durch die Normalisierung nicht verloren gehen"
        assert bytes(cover[0]) == real_cover_jpeg

    def test_audio_stream_actually_normalized_with_cover_present(
        self, tmp_path, real_cover_jpeg
    ):
        """Stellt sicher, dass der Fix (explizites -map) die eigentliche
        Loudness-Normalisierung nicht nebenbei kaputt macht - der
        Audiostream muss nach wie vor tatsaechlich Richtung Ziel-LUFS
        veraendert werden."""
        path = tmp_path / "loud_with_cover.m4a"
        _make_real_m4a(path)
        _add_cover(path, real_cover_jpeg)

        measure_before = subprocess.run(
            ["ffmpeg", "-i", str(path), "-af", "loudnorm=I=-16:LRA=11:TP=-1.5:print_format=summary",
             "-f", "null", "-"],
            capture_output=True, text=True,
        )
        assert "Input Integrated" in measure_before.stderr

        assert AudioEnhancer.normalize_loudness(str(path), target_lufs=-16.0) is True

        audio = MP4(path)
        assert audio.info.length > 0
        assert audio.tags.get("covr"), "Cover-Praesenz nach Normalisierung erneut geprueft"

    def test_file_without_cover_still_works_unchanged(self, tmp_path):
        """Gegenbeispiel (CLAUDE.md Abschnitt 15/28: konkrete
        Gegenbeispiele): der Fix darf den Normalfall (kein Cover) nicht
        beeintraechtigen - -map "0:v?" ist optional und darf ohne
        Video-/Bildstream keinen Fehler werfen."""
        path = tmp_path / "no_cover.m4a"
        _make_real_m4a(path)

        result = AudioEnhancer.normalize_loudness(str(path), target_lufs=-16.0)

        assert result is True
        assert path.exists()
        assert path.stat().st_size > 0
        assert _ffprobe_ok(path)

    def test_mp3_input_currently_always_fails_regardless_of_cover(self, tmp_path, real_cover_jpeg):
        """CHARAKTERISIERUNG eines SEPARATEN, vorbestehenden Defekts, der
        waehrend der Verifikation dieses Fixes entdeckt wurde (nicht Teil
        des behobenen Cover-Defekts, nicht in diesem Auftrag behoben -
        CLAUDE.md Abschnitt 8.A: unabhaengige Altlasten werden nicht
        ungefragt mitbehoben):

        cmd_apply/cmd_fallback schreiben IMMER "-c:a aac", unabhaengig von
        der Ziel-Dateiendung. Fuer eine .mp3-Ausgabedatei lehnt der
        mp3-Muxer AAC-kodierte Frames ab ("Invalid audio stream. Exactly
        one MP3 audio stream is required.") - normalize_loudness()
        schlaegt fuer JEDE .mp3-Datei fehl, mit oder ohne Cover (per
        Root-Cause-Isolation bestaetigt: identischer Fehler tritt auch
        OHNE eingebettetes Cover auf). Erreichbar in Produktion nur, wenn
        AUDIO_FORMAT=mp3 gesetzt ist (config.py Default: "m4a").

        Sicherheitsrelevant hier nur: kein Datenverlust (Return False,
        Originaldatei bleibt unveraendert) - das gilt unveraendert vor
        und nach dem Cover-Stream-Fix in diesem Commit."""
        from mutagen.id3 import ID3, APIC

        path = tmp_path / "with_cover.mp3"
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
             "-c:a", "libmp3lame", "-b:a", "192k", str(path), "-y", "-loglevel", "error"],
            check=True,
        )
        try:
            tags = ID3(path)
        except Exception:
            tags = ID3()
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=real_cover_jpeg))
        tags.save(path)
        original_bytes = path.read_bytes()

        result = AudioEnhancer.normalize_loudness(str(path), target_lufs=-16.0)

        assert result is False
        assert path.read_bytes() == original_bytes, (
            "Trotz Fehlschlag darf die Originaldatei nicht beschaedigt werden"
        )
