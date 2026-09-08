# tests/test_library_repair_executor.py
# -*- coding: utf-8 -*-
"""Level-1 Repair Executor gegen echte m4a-Dateien (Prompt Abschnitt 13-17).

Prüft: Safety-Blockade, DRY-RUN schreibt nichts, echter Lauf ändert nur
die Ziel-Atome, Audio-Essenz bleibt byte-identisch, Backup + Journal
vorhanden, Rollback bei Verifikationsfehler."""

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from mutagen.mp4 import MP4, MP4FreeForm

from services.library_repair.executor import (
    apply_album_cover_unify,
    apply_cover_repairs,
    apply_external_metadata,
    apply_level1,
    apply_level1_rename,
    apply_level2,
    apply_replaygain,
    safety_check,
)
from services.library_repair.journal import RepairJournal
from services.library_repair.models import RepairAction, RepairCandidate, RepairLevel

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")


def _m4a(path: Path, *, genre=None, artist=None, artists_ff=None, album_artist=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(path),
            "-y",
            "-loglevel",
            "error",
        ],
        check=True,
    )
    a = MP4(path)
    a["©nam"] = ["T"]
    if genre:
        a["©gen"] = [genre]
    if artist:
        a["©ART"] = artist if isinstance(artist, list) else [artist]
    if album_artist:
        a["aART"] = [album_artist]
    if artists_ff:
        a["----:com.apple.iTunes:ARTISTS"] = [
            MP4FreeForm(x.encode()) for x in artists_ff
        ]
    a.save()


def _cand(rel, code):
    return RepairCandidate(
        issue_code=code,
        action=RepairAction.MULTI_ARTIST_SPLIT,
        level=RepairLevel.SAFE_AUTOMATIC,
        severity="INFO",
        scope="file",
        path=rel,
    )


def _read(path):
    t = MP4(path).tags or {}

    def _x(v):
        return [b.decode() if isinstance(b, bytes) else str(b) for b in (v or [])]

    return {
        "gen": _x(t.get("©gen")),
        "art": _x(t.get("©ART")),
        "aart": _x(t.get("aART")),
        "ff": _x(t.get("----:com.apple.iTunes:ARTISTS")),
    }


def _audio_md5(path):
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-f", "md5", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout.strip()


@pytest.fixture
def lib(tmp_path):
    return tmp_path / "library"


@requires_ffmpeg
def test_dry_run_changes_nothing(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p, genre="Pop / Rock")
    md5_before = _audio_md5(p)
    j = RepairJournal(lib / "journal.jsonl")
    outcomes = apply_level1(
        [_cand("A/Singles/2020 - x.m4a", "GENRE_DELIMITER_INCONSISTENT")],
        lib,
        j,
        dry_run=True,
    )
    assert outcomes[0].status == "DRY_RUN"
    assert _read(p)["gen"] == ["Pop / Rock"]  # unverändert
    assert _audio_md5(p) == md5_before
    assert not (lib.parent / ".library_repair_backups").exists()
    assert j.entries[0].status == "DRY_RUN"


@requires_ffmpeg
def test_genre_delimiter_applied_audio_untouched(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p, genre="Pop / Rock / Indie")
    md5_before = _audio_md5(p)
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1(
        [_cand("A/Singles/2020 - x.m4a", "GENRE_DELIMITER_INCONSISTENT")],
        lib,
        j,
        dry_run=False,
    )
    assert outcomes[0].status == "SUCCESS"
    assert _read(p)["gen"] == ["Pop; Rock; Indie"]
    assert _audio_md5(p) == md5_before  # Ton unverändert
    backups = list((lib.parent / ".library_repair_backups").rglob("*.bak"))
    assert len(backups) == 1  # Rollback möglich, ausserhalb der Library
    assert not list(lib.rglob("*.bak")) and not list(lib.rglob("*.repair*"))
    j.flush()
    assert (lib / "j.jsonl").exists()


@requires_ffmpeg
def test_multi_artist_split_and_align(lib):
    p = lib / "makko" / "2020 - Album" / "01 - t.m4a"
    _m4a(p, artist=["makko & toobrokeforfiji"], artists_ff=["makko", "toobrokeforfiji"])
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1(
        [_cand("makko/2020 - Album/01 - t.m4a", "MULTI_ARTIST_INCONSISTENT")],
        lib,
        j,
        dry_run=False,
    )
    assert outcomes[0].status == "SUCCESS"
    r = _read(p)
    assert r["art"] == ["makko", "toobrokeforfiji"]
    assert r["ff"] == ["makko", "toobrokeforfiji"]


@requires_ffmpeg
def test_nothing_to_do_is_skipped(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p, genre="Pop; Rock")
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1(
        [_cand("A/Singles/2020 - x.m4a", "GENRE_DELIMITER_INCONSISTENT")],
        lib,
        j,
        dry_run=False,
    )
    assert outcomes[0].status == "SKIPPED"
    assert not (lib.parent / ".library_repair_backups").exists()


@requires_ffmpeg
def test_safety_blocks_symlink(lib):
    real = lib / "_outside" / "r.m4a"
    _m4a(real)
    link_dir = lib / "A" / "Singles"
    link_dir.mkdir(parents=True)
    link = link_dir / "2020 - x.m4a"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("keine Symlinks")
    assert safety_check(link, lib) == "Symlink"
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1(
        [_cand("A/Singles/2020 - x.m4a", "GENRE_DELIMITER_INCONSISTENT")],
        lib,
        j,
        dry_run=False,
    )
    assert outcomes[0].status == "SKIPPED"
    assert "Safety" in outcomes[0].reason


def test_safety_blocks_path_outside_library(tmp_path):
    outside = tmp_path / "elsewhere" / "x.m4a"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"x")
    lib = tmp_path / "library"
    lib.mkdir()
    assert "außerhalb" in (safety_check(outside, lib) or "")


def test_safety_blocks_unsupported_extension(tmp_path):
    lib = tmp_path / "library"
    (lib / "A").mkdir(parents=True)
    f = lib / "A" / "x.flac"
    f.write_bytes(b"x" * 10)
    assert "nicht unterstütztes Format" in (safety_check(f, lib) or "")


@requires_ffmpeg
def test_rename_removes_producer_cruft_content_unchanged(lib):
    p = lib / "makko" / "Singles" / "2020 - Gelb prod. Xarbeats.m4a"
    _m4a(p)
    a = MP4(p)
    a["©nam"] = ["Gelb"]
    a["©day"] = ["2020"]
    a.save()
    md5_before = _audio_md5(p)
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1_rename(
        [
            _cand(
                "makko/Singles/2020 - Gelb prod. Xarbeats.m4a",
                "FILENAME_TITLE_MISMATCH",
            )
        ],
        lib,
        j,
        dry_run=False,
    )
    assert outcomes[0].status == "SUCCESS"
    new = lib / "makko" / "Singles" / "2020 - Gelb.m4a"
    assert new.exists() and not p.exists()
    assert _audio_md5(new) == md5_before
    assert outcomes[0].after == {"path": "makko/Singles/2020 - Gelb.m4a"}


@requires_ffmpeg
def test_rename_dry_run_does_not_move(lib):
    p = lib / "A" / "Singles" / "2021 -  Song.m4a"
    _m4a(p)
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1_rename(
        [_cand("A/Singles/2021 -  Song.m4a", "FILENAME_SUSPICIOUS")],
        lib,
        j,
        dry_run=True,
    )
    assert outcomes[0].status == "DRY_RUN"
    assert p.exists()


@requires_ffmpeg
def test_rename_skips_when_target_exists(lib):
    p = lib / "A" / "Singles" / "2020 - Song prod. X.m4a"
    _m4a(p)
    a = MP4(p)
    a["©nam"] = ["Song"]
    a["©day"] = ["2020"]
    a.save()
    _m4a(lib / "A" / "Singles" / "2020 - Song.m4a")  # Zielname existiert schon
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1_rename(
        [_cand("A/Singles/2020 - Song prod. X.m4a", "FILENAME_TITLE_MISMATCH")],
        lib,
        j,
        dry_run=False,
    )
    assert outcomes[0].status == "SKIPPED"
    assert p.exists()


@requires_ffmpeg
def test_rename_stays_in_same_directory(lib):
    p = lib / "A" / "Singles" / "2021 -  Song.m4a"
    _m4a(p)
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1_rename(
        [_cand("A/Singles/2021 -  Song.m4a", "FILENAME_SUSPICIOUS")],
        lib,
        j,
        dry_run=False,
    )
    assert outcomes[0].status == "SUCCESS"
    moved = list((lib / "A" / "Singles").glob("*.m4a"))
    assert len(moved) == 1 and moved[0].parent == p.parent


def _png_bytes(px):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (px, px), (5, 6, 7)).save(buf, "PNG")
    return buf.getvalue()


@requires_ffmpeg
def test_cover_added_when_missing_audio_untouched(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©ART"] = ["A"]
    a["©nam"] = ["x"]
    a.save()
    md5_before = _audio_md5(p)
    big = _png_bytes(1000)
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_cover_repairs(
        [_cand("A/Singles/2020 - x.m4a", "ARTWORK_MISSING")],
        lib,
        j,
        cover_fetcher=lambda ctx: (big, "test-source"),
        dry_run=False,
    )
    assert outcomes[0].status == "SUCCESS"
    assert bool(MP4(p).tags.get("covr"))
    assert _audio_md5(p) == md5_before
    assert list((lib.parent / ".library_repair_backups").rglob("*.bak"))


@requires_ffmpeg
def test_cover_not_replaced_when_candidate_not_better(lib):
    import io

    from mutagen.mp4 import MP4Cover
    from PIL import Image

    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    buf = io.BytesIO()
    Image.new("RGB", (900, 900), (1, 2, 3)).save(buf, "JPEG")
    a = MP4(p)
    a["©ART"] = ["A"]
    a["©nam"] = ["x"]
    a["covr"] = [MP4Cover(buf.getvalue(), imageformat=MP4Cover.FORMAT_JPEG)]
    a.save()
    before_sha = _read(p)  # sanity
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_cover_repairs(
        [_cand("A/Singles/2020 - x.m4a", "ARTWORK_LOW_RESOLUTION")],
        lib,
        j,
        cover_fetcher=lambda ctx: (_png_bytes(950), "s"),
        dry_run=False,
    )
    assert outcomes[0].status == "SKIPPED"  # 900 -> 950 zu wenig Zugewinn
    assert not (lib.parent / ".library_repair_backups").exists()


@requires_ffmpeg
def test_cover_dry_run_writes_nothing(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©ART"] = ["A"]
    a["©nam"] = ["x"]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_cover_repairs(
        [_cand("A/Singles/2020 - x.m4a", "ARTWORK_MISSING")],
        lib,
        j,
        cover_fetcher=lambda ctx: (_png_bytes(1200), "s"),
        dry_run=True,
    )
    assert outcomes[0].status == "DRY_RUN"
    assert not bool(MP4(p).tags.get("covr"))


@requires_ffmpeg
def test_cover_skips_when_fetcher_returns_none(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©ART"] = ["A"]
    a["©nam"] = ["x"]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_cover_repairs(
        [_cand("A/Singles/2020 - x.m4a", "ARTWORK_MISSING")],
        lib,
        j,
        cover_fetcher=lambda ctx: (None, None),
        dry_run=False,
    )
    assert outcomes[0].status == "SKIPPED"


def _m4a_with_cover(p, px, colour):
    import io

    from mutagen.mp4 import MP4Cover
    from PIL import Image

    _m4a(p)
    buf = io.BytesIO()
    Image.new("RGB", (px, px), colour).save(buf, "JPEG")
    a = MP4(p)
    a["©ART"] = ["A"]
    a["©nam"] = [p.stem]
    a["covr"] = [MP4Cover(buf.getvalue(), imageformat=MP4Cover.FORMAT_JPEG)]
    a.save()


@requires_ffmpeg
def test_album_cover_unify_lifts_small_to_biggest(lib):
    base = "A/2020 - Rec"
    p1 = lib / "A" / "2020 - Rec" / "01 - a.m4a"
    p2 = lib / "A" / "2020 - Rec" / "02 - b.m4a"
    p3 = lib / "A" / "2020 - Rec" / "03 - c.m4a"
    _m4a_with_cover(p1, 300, (1, 1, 1))
    _m4a_with_cover(p2, 1400, (2, 2, 2))  # bestes
    _m4a_with_cover(p3, 300, (3, 3, 3))
    md5_before = {p: _audio_md5(p) for p in (p1, p2, p3)}
    c = RepairCandidate(
        issue_code="ALBUM_COVER_INCONSISTENT",
        action=RepairAction.COVER_FETCH,
        level=RepairLevel.COVER,
        severity="INFO",
        scope="album",
        artist="A",
        album="2020 - Rec",
        related_files=[
            f"{base}/01 - a.m4a",
            f"{base}/02 - b.m4a",
            f"{base}/03 - c.m4a",
        ],
    )
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_album_cover_unify([c], lib, j, dry_run=False)
    ok = [o for o in outcomes if o.status == "SUCCESS"]
    assert len(ok) == 2  # p1 + p3 angehoben, p2 unberuehrt
    from mutagen.mp4 import MP4

    def dim(p):
        import io

        from PIL import Image

        return Image.open(io.BytesIO(bytes(MP4(p).tags["covr"][0]))).size

    assert dim(p1) == dim(p2) == dim(p3) == (1400, 1400)
    for p in (p1, p2, p3):
        assert _audio_md5(p) == md5_before[p]


@requires_ffmpeg
def test_album_cover_unify_skips_when_no_usable_cover(lib):
    base = "A/2020 - Rec"
    p1 = lib / "A" / "2020 - Rec" / "01 - a.m4a"
    p2 = lib / "A" / "2020 - Rec" / "02 - b.m4a"
    _m4a(p1)
    _m4a(p2)  # gar keine Cover
    c = RepairCandidate(
        issue_code="ALBUM_COVER_INCONSISTENT",
        action=RepairAction.COVER_FETCH,
        level=RepairLevel.COVER,
        severity="INFO",
        scope="album",
        artist="A",
        album="2020 - Rec",
        related_files=[f"{base}/01 - a.m4a", f"{base}/02 - b.m4a"],
    )
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_album_cover_unify([c], lib, j, dry_run=False)
    assert all(o.status == "SKIPPED" for o in outcomes)


@requires_ffmpeg
def test_external_metadata_adds_missing_ids_audio_untouched(lib):
    p = lib / "A" / "Singles" / "2020 - Real Song.m4a"
    _m4a(p)
    a = MP4(p)
    a["©ART"] = ["Real Artist"]
    a["©nam"] = ["Real Song"]
    a.save()
    md5_before = _audio_md5(p)
    mb = {
        "title": "Real Song",
        "artist": "Real Artist",
        "recording_id": "12345678-1234-1234-1234-1234567890ab",
        "artist_id": "12345678-1234-1234-1234-1234567890ab",
        "release_id": "abcdef01-2345-6789-abcd-ef0123456789",
        "release_group_id": "abcdef01-2345-6789-abcd-ef0123456789",
        "isrc": "DEA123456789",
    }
    j = RepairJournal(lib / "j.jsonl")
    c = RepairCandidate(
        issue_code="META_MB_RECORDING_MISSING",
        action=RepairAction.EXTERNAL_ID_LOOKUP,
        level=RepairLevel.EXTERNAL_METADATA,
        severity="INFO",
        scope="file",
        path="A/Singles/2020 - Real Song.m4a",
    )
    outcomes = apply_external_metadata(
        [c], lib, j, mb_lookup=lambda ar, ti: mb, dry_run=False
    )
    assert outcomes[0].status == "SUCCESS"
    from mutagen.mp4 import MP4 as _MP4

    t = _MP4(p).tags
    assert (
        bytes(t["----:com.apple.iTunes:MusicBrainz Recording Id"][0]).decode()
        == "12345678-1234-1234-1234-1234567890ab"
    )
    assert bytes(t["----:com.apple.iTunes:ISRC"][0]).decode() == "DEA123456789"
    assert _audio_md5(p) == md5_before


@requires_ffmpeg
def test_external_metadata_skips_dirty_title(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©ART"] = ["A"]
    a["©nam"] = ["Song prod. Xarbeats"]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    c = RepairCandidate(
        issue_code="META_ISRC_MISSING",
        action=RepairAction.EXTERNAL_ID_LOOKUP,
        level=RepairLevel.EXTERNAL_METADATA,
        severity="INFO",
        scope="file",
        path="A/Singles/2020 - x.m4a",
    )
    called = []
    outcomes = apply_external_metadata(
        [c], lib, j, mb_lookup=lambda ar, ti: called.append(1) or {}, dry_run=False
    )
    assert outcomes[0].status == "SKIPPED"
    assert not called  # unsauberer Titel -> gar keine externe Suche


@requires_ffmpeg
def test_external_metadata_no_match_skips(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©ART"] = ["A"]
    a["©nam"] = ["Clean Title"]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    c = RepairCandidate(
        issue_code="META_MB_RELEASE_MISSING",
        action=RepairAction.EXTERNAL_ID_LOOKUP,
        level=RepairLevel.EXTERNAL_METADATA,
        severity="INFO",
        scope="file",
        path="A/Singles/2020 - x.m4a",
    )
    outcomes = apply_external_metadata(
        [c], lib, j, mb_lookup=lambda ar, ti: {}, dry_run=False
    )
    assert outcomes[0].status == "SKIPPED"
    assert not (lib.parent / ".library_repair_backups").exists()


@requires_ffmpeg
def test_external_metadata_lookup_exception_is_failed_not_crash(lib):
    """Production-Audit 2026-09-08, Test-Gap: externe Service-Fehler
    (Timeout/Verbindungsfehler) im Repair-Kontext waren ungetestet. Eine
    Exception aus mb_lookup() (z.B. MusicBrainz-Timeout) darf die
    Ausfuehrung nicht crashen, sondern muss als FAILED landen - ohne
    Datei-/Backup-Aenderung."""
    p = lib / "A" / "Singles" / "2020 - Clean Title.m4a"
    _m4a(p)
    a = MP4(p)
    a["©ART"] = ["A"]
    a["©nam"] = ["Clean Title"]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    c = RepairCandidate(
        issue_code="META_ISRC_MISSING",
        action=RepairAction.EXTERNAL_ID_LOOKUP,
        level=RepairLevel.EXTERNAL_METADATA,
        severity="INFO",
        scope="file",
        path="A/Singles/2020 - Clean Title.m4a",
    )

    def _boom(artist, title):
        raise TimeoutError("MusicBrainz nicht erreichbar")

    outcomes = apply_external_metadata([c], lib, j, mb_lookup=_boom, dry_run=False)
    assert outcomes[0].status == "FAILED"
    assert "MusicBrainz-Suche" in outcomes[0].reason
    assert not (lib.parent / ".library_repair_backups").exists()


@requires_ffmpeg
def test_l2_reprocess_exception_rolls_back_without_crash(lib):
    """Production-Audit 2026-09-08, Test-Gap: eine unbehandelte Exception
    aus der injizierten reprocess()-Callable (z.B. ein durchschlagender
    Genius-/MusicBrainz-Verbindungsfehler innerhalb der echten Pipeline)
    muss FAILED + vollstaendigen Rollback ergeben statt den Repair-Lauf
    abzubrechen."""
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©nam"] = ["orig"]
    a.save()
    md5_before = _audio_md5(p)
    j = RepairJournal(lib / "j.jsonl")

    def _boom(path, artist_root, dry_run):
        raise ConnectionError("Genius nicht erreichbar")

    outcomes = apply_level2(
        [_l2_cand("makko/Singles/2020 - x.m4a", "LYRICS_MISSING")],
        lib,
        j,
        _boom,
        dry_run=False,
    )
    assert outcomes[0].status == "FAILED"
    assert "ConnectionError" in outcomes[0].reason
    assert MP4(p)["©nam"] == ["orig"]
    assert _audio_md5(p) == md5_before
    assert not list((lib.parent / ".library_repair_backups").rglob("*.bak"))


@requires_ffmpeg
def test_l1_batch_yields_independent_mixed_outcomes(lib):
    """Production-Audit 2026-09-08, Test-Gap: mehrere Kandidaten in EINEM
    apply_level1()-Aufruf mit gemischten Ergebnissen (SUCCESS + SKIPPED)
    waren ungetestet - jeder Executor-Test uebergab bisher nur einen
    einzelnen Kandidaten."""
    p_dirty = lib / "A" / "Singles" / "2020 - dirty.m4a"
    p_clean = lib / "A" / "Singles" / "2020 - clean.m4a"
    _m4a(p_dirty, genre="Pop / Rock")
    _m4a(p_clean, genre="Pop; Rock")  # bereits korrekt -> nichts zu tun
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1(
        [
            _cand("A/Singles/2020 - dirty.m4a", "GENRE_DELIMITER_INCONSISTENT"),
            _cand("A/Singles/2020 - clean.m4a", "GENRE_DELIMITER_INCONSISTENT"),
        ],
        lib,
        j,
        dry_run=False,
    )
    by_file = {o.file: o.status for o in outcomes}
    assert by_file == {
        "A/Singles/2020 - dirty.m4a": "SUCCESS",
        "A/Singles/2020 - clean.m4a": "SKIPPED",
    }


@requires_ffmpeg
def test_l2_batch_yields_independent_mixed_outcomes(lib):
    """Analog zu test_l1_batch_yields_independent_mixed_outcomes fuer
    apply_level2(): zwei Dateien in einem Aufruf, eine mit gefundenen
    Lyrics (SUCCESS), eine ohne (SKIPPED) - ein Fehlschlag bei einer Datei
    darf das Ergebnis der anderen nicht beeinflussen."""
    p_found = lib / "makko" / "Singles" / "2020 - found.m4a"
    p_missing = lib / "makko" / "Singles" / "2020 - missing.m4a"
    _m4a(p_found)
    _m4a(p_missing)
    j = RepairJournal(lib / "j.jsonl")

    def rp(path, artist_root, dry_run):
        if "found" in path.name:
            return {
                "file": path.name,
                "status": "changed",
                "error": None,
                "changes": {"lyrics_present": {"before": False, "after": True}},
                "unresolved": [],
                "audio_essence_changed": False,
                "audio_stream_changed": False,
            }
        return {
            "file": path.name,
            "status": "unchanged",
            "error": None,
            "changes": {},
            "unresolved": [],
            "audio_essence_changed": False,
            "audio_stream_changed": False,
        }

    outcomes = apply_level2(
        [
            _l2_cand("makko/Singles/2020 - found.m4a", "LYRICS_MISSING"),
            _l2_cand("makko/Singles/2020 - missing.m4a", "LYRICS_MISSING"),
        ],
        lib,
        j,
        rp,
        dry_run=False,
    )
    by_file = {o.file: o.status for o in outcomes}
    assert by_file == {
        "makko/Singles/2020 - found.m4a": "SUCCESS",
        "makko/Singles/2020 - missing.m4a": "SKIPPED",
    }


@requires_ffmpeg
def test_non_l1_codes_are_ignored(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p, genre="Pop / Rock")
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1(
        [
            _cand("A/Singles/2020 - x.m4a", "META_ISRC_MISSING"),
            _cand("A/Singles/2020 - x.m4a", "DUPLICATE_EXACT"),
        ],
        lib,
        j,
        dry_run=False,
    )
    assert outcomes == []  # nichts aus L1_TAG_CODES


# ─────────────────────────────────────────────────────────────────────────
# Level 2 — METADATA_REPROCESSING (reprocess()-Pipeline injiziert)
# ─────────────────────────────────────────────────────────────────────────


def _l2_cand(rel, code="META_TITLE_NOT_CLEAN"):
    return RepairCandidate(
        issue_code=code,
        action=RepairAction.METADATA_REPROCESS,
        level=RepairLevel.METADATA_REPROCESSING,
        severity="WARNING",
        scope="file",
        path=rel,
    )


def _fake_reprocess(
    *,
    status="changed",
    changes=None,
    error=None,
    audio_essence_changed=False,
    audio_stream_changed=False,
    unresolved=None,
    rewrite_title=None,
):
    """Baut ein process_file-artiges Ergebnis. `rewrite_title` schreibt den
    Titel-Tag tatsaechlich (simuliert den echten In-Place-Write der Pipeline,
    ohne den Audio-Stream anzufassen)."""

    def _fn(path, artist_root, dry_run, requested_issue=None):
        if rewrite_title is not None and not dry_run:
            a = MP4(path)
            a["©nam"] = [rewrite_title]
            a.save()

        return {
            "file": str(path.name),
            "status": status,
            "error": error,
            "changes": changes or {},
            "unresolved": unresolved or [],
            "audio_essence_changed": audio_essence_changed,
            "audio_stream_changed": audio_stream_changed,
            "auto_learn": {
                "featured_artists": [],
                "genre": None,
            },
        }

    return _fn


@requires_ffmpeg
def test_l2_dry_run_writes_nothing(lib):
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©nam"] = ['"x"']
    a.save()
    md5_before = _audio_md5(p)
    j = RepairJournal(lib / "j.jsonl")
    rp = _fake_reprocess(changes={"title": {"before": ['"x"'], "after": ["x"]}})
    outcomes = apply_level2(
        [_l2_cand("makko/Singles/2020 - x.m4a")], lib, j, rp, dry_run=True
    )
    assert outcomes[0].status == "DRY_RUN"
    assert outcomes[0].after == {"title": ["x"]}
    assert MP4(p)["©nam"] == ['"x"']  # unveraendert
    assert not (lib.parent / ".library_repair_backups").exists()
    assert _audio_md5(p) == md5_before


@requires_ffmpeg
def test_l2_execute_applies_and_keeps_audio(lib):
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©nam"] = ['"Ausreden"']
    a.save()
    md5_before = _audio_md5(p)
    j = RepairJournal(lib / "j.jsonl")
    rp = _fake_reprocess(
        changes={"title": {"before": ['"Ausreden"'], "after": ["Ausreden"]}},
        rewrite_title="Ausreden",
    )
    outcomes = apply_level2(
        [_l2_cand("makko/Singles/2020 - x.m4a")], lib, j, rp, dry_run=False
    )
    assert outcomes[0].status == "SUCCESS"
    assert outcomes[0].backup_path
    assert MP4(p)["©nam"] == ["Ausreden"]
    assert _audio_md5(p) == md5_before


@requires_ffmpeg
def test_l2_rolls_back_on_reported_audio_change(lib):
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©nam"] = ["orig"]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    rp = _fake_reprocess(
        status="changed", audio_essence_changed=True, rewrite_title="neu"
    )
    outcomes = apply_level2(
        [_l2_cand("makko/Singles/2020 - x.m4a")], lib, j, rp, dry_run=False
    )
    assert outcomes[0].status == "FAILED"
    assert MP4(p)["©nam"] == ["orig"]  # zurueckgerollt
    bdir = lib.parent / ".library_repair_backups"
    assert not list(bdir.rglob("*.bak"))  # Backup-Kopie nach Rollback entfernt


@requires_ffmpeg
def test_l2_rolls_back_on_pipeline_error(lib):
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©nam"] = ["orig"]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    rp = _fake_reprocess(status="error", error="boom", rewrite_title="neu")
    outcomes = apply_level2(
        [_l2_cand("makko/Singles/2020 - x.m4a")], lib, j, rp, dry_run=False
    )
    assert outcomes[0].status == "FAILED"
    assert MP4(p)["©nam"] == ["orig"]


@requires_ffmpeg
def test_l2_unchanged_is_skipped(lib):
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©nam"] = ["schon sauber"]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    rp = _fake_reprocess(status="unchanged", changes={})
    outcomes = apply_level2(
        [_l2_cand("makko/Singles/2020 - x.m4a")], lib, j, rp, dry_run=False
    )
    assert outcomes[0].status == "SKIPPED"


@requires_ffmpeg
def test_l2_surfaces_unresolved(lib):
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©nam"] = ["t"]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    rp = _fake_reprocess(
        changes={"title": {"before": ["t"], "after": ["t2"]}},
        unresolved=["ReplayGain/Loudness fehlt"],
        rewrite_title="t2",
    )
    outcomes = apply_level2(
        [_l2_cand("makko/Singles/2020 - x.m4a")], lib, j, rp, dry_run=False
    )
    assert outcomes[0].status == "SUCCESS"
    assert "UNRESOLVED" in outcomes[0].reason


@requires_ffmpeg
def test_l2_skipped_when_triggering_field_untouched(lib):
    """Production-Audit 2026-09-08: SUCCESS darf nur gelten, wenn das fuer
    den jeweiligen Issue-Code relevante Zielfeld sich tatsaechlich
    geaendert hat - nicht schon, wenn irgendein ANDERES Feld sich aendert.
    Realer Fund: LYRICS_MISSING wurde 11/11x als SUCCESS gemeldet, obwohl
    die Lyrics-Suche nur bei 6/11 Dateien tatsaechlich etwas fand (die
    Pipeline aenderte parallel andere Felder wie Cover/Genre)."""
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©nam"] = ["Alt"]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    # Titel aendert sich (Pipeline-Nebenwirkung), Lyrics-Suche blieb aber
    # erfolglos -> "lyrics_present" taucht NICHT im changes-Dict auf.
    rp = _fake_reprocess(
        changes={"title": {"before": ["Alt"], "after": ["Neu"]}},
        rewrite_title="Neu",
    )
    outcomes = apply_level2(
        [_l2_cand("makko/Singles/2020 - x.m4a", "LYRICS_MISSING")],
        lib,
        j,
        rp,
        dry_run=False,
    )
    assert outcomes[0].issue_code == "LYRICS_MISSING"
    assert outcomes[0].status == "SKIPPED"


@requires_ffmpeg
def test_l2_success_when_triggering_field_actually_changed(lib):
    """Gegenprobe: aendert sich das fuer den Issue-Code relevante
    Zielfeld tatsaechlich, bleibt SUCCESS korrekt erhalten."""
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    j = RepairJournal(lib / "j.jsonl")
    rp = _fake_reprocess(
        changes={
            "lyrics_present": {"before": False, "after": True},
            "title": {"before": ["Alt"], "after": ["Neu"]},
        },
        rewrite_title="Neu",
    )
    outcomes = apply_level2(
        [_l2_cand("makko/Singles/2020 - x.m4a", "LYRICS_MISSING")],
        lib,
        j,
        rp,
        dry_run=False,
    )
    assert outcomes[0].issue_code == "LYRICS_MISSING"
    assert outcomes[0].status == "SUCCESS"


@requires_ffmpeg
def test_l2_multiple_codes_get_independent_status(lib):
    """Zwei L2-Issue-Codes derselben Datei duerfen nicht mehr in einem
    einzigen Outcome verschmelzen (Root Cause: vorher wurde nur der
    alphabetisch erste Code als issue_code des Outcomes verwendet, der
    zweite Code ging fuer Journal/Verification komplett verloren)."""
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    j = RepairJournal(lib / "j.jsonl")
    rp = _fake_reprocess(
        changes={"title": {"before": ["Alt"], "after": ["Neu"]}},
        rewrite_title="Neu",
    )
    outcomes = apply_level2(
        [
            _l2_cand("makko/Singles/2020 - x.m4a", "META_TITLE_NOT_CLEAN"),
            _l2_cand("makko/Singles/2020 - x.m4a", "LYRICS_MISSING"),
        ],
        lib,
        j,
        rp,
        dry_run=False,
    )
    by_code = {oc.issue_code: oc.status for oc in outcomes}
    assert by_code == {"META_TITLE_NOT_CLEAN": "SUCCESS", "LYRICS_MISSING": "SKIPPED"}


@requires_ffmpeg
def test_l2_handles_reclassified_genre_codes(lib):
    """Production-Audit 2026-09-08: META_GENRE_MISSING/GENRE_EMPTY wurden
    von EXTERNAL_METADATA (kein Executor) nach METADATA_REPROCESSING
    verschoben - apply_level2() muss beide wie GENRE_INVALID behandeln."""
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    j = RepairJournal(lib / "j.jsonl")
    rp = _fake_reprocess(changes={"genre_tag": {"before": [], "after": ["Pop"]}})
    for code in ("META_GENRE_MISSING", "GENRE_EMPTY"):
        outcomes = apply_level2(
            [_l2_cand("makko/Singles/2020 - x.m4a", code)], lib, j, rp, dry_run=False
        )
        assert outcomes[0].issue_code == code
        assert outcomes[0].status == "SUCCESS"


@requires_ffmpeg
def test_l2_one_reprocess_call_per_file(lib):
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["©nam"] = ["t"]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    calls = []

    def rp(path, artist_root, dry_run):
        calls.append(path)
        assert artist_root == lib / "makko"
        return {
            "file": "x",
            "status": "unchanged",
            "error": None,
            "changes": {},
            "unresolved": [],
            "audio_essence_changed": False,
            "audio_stream_changed": False,
        }

    apply_level2(
        [
            _l2_cand("makko/Singles/2020 - x.m4a", "META_TITLE_NOT_CLEAN"),
            _l2_cand("makko/Singles/2020 - x.m4a", "GENRE_INVALID"),
        ],
        lib,
        j,
        rp,
        dry_run=False,
    )
    assert len(calls) == 1


@requires_ffmpeg
def test_l2_safety_blocks_symlink(lib):
    p = lib / "makko" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    link = lib / "makko" / "Singles" / "2020 - link.m4a"
    link.symlink_to(p)
    j = RepairJournal(lib / "j.jsonl")
    calls = []
    outcomes = apply_level2(
        [_l2_cand("makko/Singles/2020 - link.m4a")],
        lib,
        j,
        lambda *a: calls.append(1),
        dry_run=False,
    )
    assert outcomes[0].status == "SKIPPED"
    assert "Safety" in outcomes[0].reason
    assert not calls


# ─────────────────────────────────────────────────────────────────────────
# Level LOUDNESS — verlustfreier ReplayGain-Tag (measure_fn injiziert)
# ─────────────────────────────────────────────────────────────────────────


def _rg_cand(rel):
    return RepairCandidate(
        issue_code="LOUDNESS_OFF_TARGET",
        action=RepairAction.LOUDNESS_NORMALIZE,
        level=RepairLevel.LOUDNESS,
        severity="INFO",
        scope="file",
        path=rel,
    )


def _rg(path):
    from mutagen.mp4 import MP4

    t = MP4(path).tags or {}

    def _x(k):
        v = t.get(k)
        return bytes(v[0]).decode() if v else None

    return (
        _x("----:com.apple.iTunes:replaygain_track_gain"),
        _x("----:com.apple.iTunes:replaygain_track_peak"),
    )


@requires_ffmpeg
def test_replaygain_dry_run_writes_nothing(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p, genre="Pop")
    md5 = _audio_md5(p)
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_replaygain(
        [_rg_cand("A/Singles/2020 - x.m4a")],
        lib,
        j,
        measure_fn=lambda p: (-9.0, -1.0),
        dry_run=True,
    )
    assert outcomes[0].status == "DRY_RUN"
    assert outcomes[0].after["replaygain_track_gain"] == "-7.00 dB"
    assert _rg(p) == (None, None)
    assert _audio_md5(p) == md5
    assert not (lib.parent / ".library_repair_backups").exists()


@requires_ffmpeg
def test_replaygain_on_target_is_skipped(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_replaygain(
        [_rg_cand("A/Singles/2020 - x.m4a")],
        lib,
        j,
        measure_fn=lambda p: (-16.4, -1.0),
        dry_run=False,
    )
    assert outcomes[0].status == "SKIPPED"
    assert _rg(p) == (None, None)


@requires_ffmpeg
def test_replaygain_execute_writes_tag_audio_untouched(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p, genre="Pop", artist="A")
    md5_before = _audio_md5(p)
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_replaygain(
        [_rg_cand("A/Singles/2020 - x.m4a")],
        lib,
        j,
        measure_fn=lambda p: (-11.2, -1.0),
        dry_run=False,
    )
    assert outcomes[0].status == "SUCCESS", outcomes[0].reason
    gain, peak = _rg(p)
    assert gain == "-4.80 dB"  # -16 - (-11.2)
    assert peak is not None
    assert _audio_md5(p) == md5_before  # Audio BYTE-identisch
    assert MP4(p).tags["©gen"] == ["Pop"]  # andere Tags unberührt
    assert outcomes[0].backup_path


@requires_ffmpeg
def test_replaygain_no_measurement_is_skipped(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_replaygain(
        [_rg_cand("A/Singles/2020 - x.m4a")],
        lib,
        j,
        measure_fn=lambda p: (None, None),
        dry_run=False,
    )
    assert outcomes[0].status == "SKIPPED"
    assert "keine LUFS-Messung" in outcomes[0].reason


@requires_ffmpeg
def test_replaygain_safety_blocks_symlink(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    link = lib / "A" / "Singles" / "2020 - l.m4a"
    link.symlink_to(p)
    j = RepairJournal(lib / "j.jsonl")
    called = []
    outcomes = apply_replaygain(
        [_rg_cand("A/Singles/2020 - l.m4a")],
        lib,
        j,
        measure_fn=lambda p: called.append(1) or (-9.0, -1.0),
        dry_run=False,
    )
    assert outcomes[0].status == "SKIPPED"
    assert "Safety" in outcomes[0].reason
    assert not called


@requires_ffmpeg
def test_replaygain_clears_stale_tag_when_file_on_target(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["----:com.apple.iTunes:replaygain_track_gain"] = [MP4FreeForm(b"-4.26 dB")]
    a["----:com.apple.iTunes:replaygain_track_peak"] = [MP4FreeForm(b"0.812")]
    a.save()
    md5 = _audio_md5(p)
    j = RepairJournal(lib / "j.jsonl")
    # Datei liegt bereits auf -16.03 -> Tag ist irreführend -> CLEAR
    outcomes = apply_replaygain(
        [_rg_cand("A/Singles/2020 - x.m4a")],
        lib,
        j,
        measure_fn=lambda p: (-16.03, -4.0),
        dry_run=False,
    )
    assert outcomes[0].status == "SUCCESS", outcomes[0].reason
    assert _rg(p) == (None, None)  # RG-Atome entfernt
    assert _audio_md5(p) == md5


@requires_ffmpeg
def test_replaygain_overwrites_wrong_existing_tag(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["----:com.apple.iTunes:replaygain_track_gain"] = [MP4FreeForm(b"-2.00 dB")]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    # -9.4 LUFS, Tag -2 -> effektiv -11.4 -> daneben -> neuer Gain -6.60
    outcomes = apply_replaygain(
        [_rg_cand("A/Singles/2020 - x.m4a")],
        lib,
        j,
        measure_fn=lambda p: (-9.4, -1.0),
        dry_run=False,
    )
    assert outcomes[0].status == "SUCCESS"
    assert _rg(p)[0] == "-6.60 dB"


@requires_ffmpeg
def test_replaygain_skips_when_existing_tag_already_correct(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p)
    a = MP4(p)
    a["----:com.apple.iTunes:replaygain_track_gain"] = [MP4FreeForm(b"-5.00 dB")]
    a.save()
    j = RepairJournal(lib / "j.jsonl")
    # -11 LUFS + -5 dB = -16 -> passt schon
    outcomes = apply_replaygain(
        [_rg_cand("A/Singles/2020 - x.m4a")],
        lib,
        j,
        measure_fn=lambda p: (-11.0, -1.0),
        dry_run=False,
    )
    assert outcomes[0].status == "SKIPPED"
    assert _rg(p)[0] == "-5.00 dB"  # unangetastet
