# tests/test_duplicate_execution.py
# -*- coding: utf-8 -*-
"""
Tests für services/duplicate/execution.py (MusicBot — Duplicate
Resolution Phase 3: SAFE EXECUTE IMPLEMENTATION).

WICHTIG (Lehre aus einem echten Vorfall während dieser Phase): dieses
Modul verwendet AUSSCHLIESSLICH `tmp_path` (pytest-eigenes, pro-Test
isoliertes Verzeichnis) - NIEMALS /tmp/musicbot_test/library direkt.
Ein frueherer, noch nicht angepasster Test in tests/test_resolve_duplicates.py
hat waehrend dieser Phase versehentlich `rd.main(["--execute"])` ohne
Pfad-Scoping gegen die echte, geteilte Testbibliothek ausgefuehrt und 4
reale Dateien geloescht (inhaltlich korrekt - siehe
docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md Abschnitt 23 - aber
ein prozeduraler Fehler). Alle Execute-Tests dieser Datei nutzen deshalb
ausschliesslich einfache, synthetische Byte-Dateien in `tmp_path` - kein
Bezug zur realen/geteilten Bibliothek.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from services.duplicate.classification import (
    Candidate,
    Classification,
    normalize_artist_for_identity,
    normalize_title_for_identity,
)
from services.duplicate.resolution import GroupAction, resolve_group
from services.duplicate.execution import (
    FileDeleteStatus,
    FileFingerprint,
    build_execution_plan,
    compute_file_sha256,
    execute_group,
    revalidate_group,
)


def _write(path: Path, content: bytes = b"synthetic-audio-bytes") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _candidate(
    path, artist="Artist", title="Title", classification=Classification.SINGLE,
    duration_seconds=100.0, mb_recording_id=None, isrc=None, album=None,
):
    return Candidate(
        path=Path(path),
        artist=artist,
        title=title,
        normalized_artist=normalize_artist_for_identity(artist),
        normalized_title=normalize_title_for_identity(title, artist),
        classification=classification,
        duration_seconds=duration_seconds,
        mb_recording_id=mb_recording_id,
        isrc=isrc,
        album=album,
    )


def _always_within_root(path: Path) -> bool:
    return True


def _never_within_root(path: Path) -> bool:
    return False


class _MatchingRebuild:
    """"Happy Path"-Stub fuer build_candidate_from_path(): gibt fuer
    jeden bekannten Pfad denselben Candidate zurueck, der auch beim
    Plan-Bau verwendet wurde - simuliert "nichts hat sich geaendert"."""

    def __init__(self):
        self._by_path = {}

    def register(self, candidate: Candidate) -> Candidate:
        self._by_path[candidate.path] = candidate
        return candidate

    def __call__(self, path: Path) -> Candidate:
        if path in self._by_path:
            return self._by_path[path]
        # Unbekannter Pfad -> neutral, fuehrt zu AMBIGUOUS-artiger
        # Nicht-Identitaet, niemals versehentlich als Match interpretiert.
        return _candidate(path, artist="", title="")


# ─────────────────────────────────────────────────────────────────────────
# FileFingerprint / compute_file_sha256
# ─────────────────────────────────────────────────────────────────────────


class TestFingerprint:
    def test_capture_returns_matching_fingerprint(self, tmp_path):
        f = tmp_path / "a.m4a"
        _write(f, b"hello world")
        fp = FileFingerprint.capture(f)
        assert fp is not None
        assert fp.size == len(b"hello world")
        assert fp.sha256 == compute_file_sha256(f)

    def test_capture_returns_none_for_missing_file(self, tmp_path):
        assert FileFingerprint.capture(tmp_path / "missing.m4a") is None

    def test_sha256_changes_with_content(self, tmp_path):
        f = tmp_path / "a.m4a"
        _write(f, b"version-1")
        h1 = compute_file_sha256(f)
        _write(f, b"version-2")
        h2 = compute_file_sha256(f)
        assert h1 != h2


# ─────────────────────────────────────────────────────────────────────────
# build_execution_plan() — nur RESOLVED, niemals MANUAL_REVIEW/AMBIGUOUS/
# UNKNOWN (Auftrag Abschnitt 11, Test 3/4/15)
# ─────────────────────────────────────────────────────────────────────────


class TestBuildExecutionPlanOnlyIncludesResolved:
    def test_manual_review_decision_produces_empty_plan(self, tmp_path):
        """Test 3: MANUAL_REVIEW wird niemals gelöscht - erreicht den
        Execution Plan gar nicht erst."""
        keep = _write_and_candidate(tmp_path, "album/01.m4a", classification=Classification.ALBUM_LIKE)
        other = _write_and_candidate(tmp_path, "album2/01.m4a", classification=Classification.ALBUM_LIKE)
        keep.title = other.title = "Song"
        keep.normalized_title = other.normalized_title = "Song"
        keep.duration_seconds, other.duration_seconds = 100.0, 105.0  # Mismatch -> REVIEW
        decision = resolve_group([keep, other])
        assert decision.action == GroupAction.MANUAL_REVIEW
        plan = build_execution_plan([decision])
        assert plan == []

    def test_keep_both_ambiguous_decision_produces_empty_plan(self, tmp_path):
        """Test 4 (sinngemäß UNKNOWN/AMBIGUOUS): AMBIGUOUS-Kandidaten
        erreichen den Plan nie."""
        a = _write_and_candidate(tmp_path, "weird1/x.m4a", classification=Classification.AMBIGUOUS)
        b = _write_and_candidate(tmp_path, "weird2/x.m4a", classification=Classification.AMBIGUOUS)
        a.title = b.title = "Song"
        a.normalized_title = b.normalized_title = "Song"
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.KEEP_BOTH
        plan = build_execution_plan([decision])
        assert plan == []

    def test_three_way_group_with_one_ambiguous_produces_empty_plan(self, tmp_path):
        """Test 15: MANUAL_REVIEW innerhalb einer Gruppe (durch EINEN
        AMBIGUOUS-Kandidaten ausgelöst) verhindert das Planen der
        GESAMTEN Gruppe - auch der eindeutigen Kandidaten."""
        album = _write_and_candidate(tmp_path, "album/01.m4a", classification=Classification.ALBUM_LIKE)
        single = _write_and_candidate(tmp_path, "singles/x.m4a", classification=Classification.SINGLE)
        ambiguous = _write_and_candidate(tmp_path, "weird/x.m4a", classification=Classification.AMBIGUOUS)
        for c in (album, single, ambiguous):
            c.title = "Song"
            c.normalized_title = "Song"
        decision = resolve_group([album, single, ambiguous])
        assert decision.action == GroupAction.MANUAL_REVIEW
        plan = build_execution_plan([decision])
        assert plan == []

    def test_resolved_decision_produces_one_plan_entry(self, tmp_path):
        album = _write_and_candidate(tmp_path, "album/01.m4a", classification=Classification.ALBUM_LIKE)
        single = _write_and_candidate(tmp_path, "singles/x.m4a", classification=Classification.SINGLE)
        for c in (album, single):
            c.title = "Song"
            c.normalized_title = "Song"
        decision = resolve_group([album, single])
        assert decision.action == GroupAction.RESOLVED
        plan = build_execution_plan([decision])
        assert len(plan) == 1
        assert plan[0].keep.path == album.path
        assert [fp.path for fp in plan[0].remove] == [single.path]


def _write_and_candidate(tmp_path, rel_path, **kwargs) -> Candidate:
    f = tmp_path / rel_path
    _write(f)
    return _candidate(f, **kwargs)


# ─────────────────────────────────────────────────────────────────────────
# revalidate_group() — Fingerprint/Path-Safety/semantische Neuentscheidung
# (Auftrag Abschnitt 6/7/8, Tests 6-14)
# ─────────────────────────────────────────────────────────────────────────


class TestRevalidateGroup:
    def _resolved_plan_entry(self, tmp_path):
        album = _write_and_candidate(tmp_path, "album/01.m4a", classification=Classification.ALBUM_LIKE)
        single = _write_and_candidate(tmp_path, "singles/x.m4a", classification=Classification.SINGLE)
        for c in (album, single):
            c.title = "Song"
            c.normalized_title = "Song"
        decision = resolve_group([album, single])
        plan = build_execution_plan([decision])
        rebuild = _MatchingRebuild()
        rebuild.register(album)
        rebuild.register(single)
        return plan[0], rebuild

    def test_unchanged_group_passes_revalidation(self, tmp_path):
        entry, rebuild = self._resolved_plan_entry(tmp_path)
        result = revalidate_group(entry, _always_within_root, rebuild)
        assert result.ok is True

    def test_sha256_changed_blocks_delete(self, tmp_path):
        """Test 6."""
        entry, rebuild = self._resolved_plan_entry(tmp_path)
        entry.remove[0].path.write_bytes(b"tampered-content-different-length")
        result = revalidate_group(entry, _always_within_root, rebuild)
        assert result.ok is False
        assert result.stage == "fingerprint"

    def test_file_size_changed_blocks_delete(self, tmp_path):
        """Test 7."""
        entry, rebuild = self._resolved_plan_entry(tmp_path)
        entry.remove[0].path.write_bytes(b"x" * (entry.remove[0].size + 100))
        result = revalidate_group(entry, _always_within_root, rebuild)
        assert result.ok is False
        assert result.stage == "fingerprint"

    def test_remove_file_disappeared_blocks_delete(self, tmp_path):
        """Test 8."""
        entry, rebuild = self._resolved_plan_entry(tmp_path)
        entry.remove[0].path.unlink()
        result = revalidate_group(entry, _always_within_root, rebuild)
        assert result.ok is False
        assert result.stage == "fingerprint"

    def test_keep_file_disappeared_blocks_delete(self, tmp_path):
        """Test 9."""
        entry, rebuild = self._resolved_plan_entry(tmp_path)
        entry.keep.path.unlink()
        result = revalidate_group(entry, _always_within_root, rebuild)
        assert result.ok is False
        assert result.stage == "fingerprint"

    def test_keep_file_changed_blocks_delete(self, tmp_path):
        """Test 10."""
        entry, rebuild = self._resolved_plan_entry(tmp_path)
        entry.keep.path.write_bytes(b"tampered-keep-content")
        result = revalidate_group(entry, _always_within_root, rebuild)
        assert result.ok is False
        assert result.stage == "fingerprint"

    def test_path_outside_allowed_root_blocks_delete(self, tmp_path):
        """Test 11."""
        entry, rebuild = self._resolved_plan_entry(tmp_path)
        result = revalidate_group(entry, _never_within_root, rebuild)
        assert result.ok is False
        assert result.stage == "path_safety"

    def test_semantic_recheck_catches_metadata_drift(self, tmp_path):
        """Test 14: Safety Gate nach Dry-Run nicht mehr PASS -> blocked.
        Simuliert, dass sich zwischen Plan und Execute die Duration
        geändert hat (z. B. Re-Encode) und nun das Safety Gate greifen
        würde."""
        entry, _ = self._resolved_plan_entry(tmp_path)

        drifted = _MatchingRebuild()
        keep_drifted = _candidate(
            entry.keep.path, title="Song", classification=Classification.ALBUM_LIKE,
            duration_seconds=100.0,
        )
        remove_drifted = _candidate(
            entry.remove[0].path, title="Song", classification=Classification.SINGLE,
            duration_seconds=999.0,  # jetzt stark abweichend -> Safety Gate BLOCKED
        )
        drifted.register(keep_drifted)
        drifted.register(remove_drifted)

        result = revalidate_group(entry, _always_within_root, drifted)
        assert result.ok is False
        assert result.stage == "semantic"

    def test_two_remove_candidates_one_corrupted_blocks_entire_group(self, tmp_path):
        """Test 16: Gruppen-Atomarität - EIN korrumpierter REMOVE-
        Kandidat blockiert die GESAMTE Gruppe, nicht nur diesen einen."""
        album = _write_and_candidate(tmp_path, "album/01.m4a", classification=Classification.ALBUM_LIKE)
        single_1 = _write_and_candidate(tmp_path, "singles/x.m4a", classification=Classification.SINGLE)
        single_2 = _write_and_candidate(tmp_path, "singles/x (1).m4a", classification=Classification.SINGLE)
        for c in (album, single_1, single_2):
            c.title = "Song"
            c.normalized_title = "Song"
        decision = resolve_group([album, single_1, single_2])
        assert decision.action == GroupAction.RESOLVED
        assert len(decision.remove_proposals) == 2
        plan = build_execution_plan([decision])
        entry = plan[0]
        assert len(entry.remove) == 2

        # EIN Kandidat wird korrumpiert
        entry.remove[0].path.write_bytes(b"corrupted")

        rebuild = _MatchingRebuild()
        rebuild.register(album)
        rebuild.register(single_1)
        rebuild.register(single_2)

        result = revalidate_group(entry, _always_within_root, rebuild)
        assert result.ok is False
        # Group-Atomaritaet auf execute_group()-Ebene bestaetigt (siehe
        # TestExecuteGroup unten) - hier: KEIN Teil-Erfolg, beide Dateien
        # existieren nach revalidate_group() weiterhin unveraendert.
        assert single_1.path.exists()
        assert single_2.path.exists()


# ─────────────────────────────────────────────────────────────────────────
# execute_group() — tatsächliches Löschen (Auftrag Abschnitt 9/12/13/14/16,
# Tests 1/5/16/17)
# ─────────────────────────────────────────────────────────────────────────


class TestExecuteGroup:
    def _resolved_plan_entry(self, tmp_path):
        album = _write_and_candidate(tmp_path, "album/01.m4a", classification=Classification.ALBUM_LIKE)
        single = _write_and_candidate(tmp_path, "singles/x.m4a", classification=Classification.SINGLE)
        for c in (album, single):
            c.title = "Song"
            c.normalized_title = "Song"
        decision = resolve_group([album, single])
        plan = build_execution_plan([decision])
        rebuild = _MatchingRebuild()
        rebuild.register(album)
        rebuild.register(single)
        return plan[0], rebuild, album, single

    def test_validated_remove_file_is_deleted(self, tmp_path):
        """Test 1."""
        entry, rebuild, album, single = self._resolved_plan_entry(tmp_path)
        result = execute_group(entry, _always_within_root, rebuild)
        assert result.group_ok is True
        assert not single.path.exists()
        assert album.path.exists()
        assert result.file_results[0].status == FileDeleteStatus.DELETED

    def test_keep_file_is_never_among_deleted(self, tmp_path):
        """Test 5."""
        entry, rebuild, album, single = self._resolved_plan_entry(tmp_path)
        result = execute_group(entry, _always_within_root, rebuild)
        deleted_paths = {r.path for r in result.file_results if r.status == FileDeleteStatus.DELETED}
        assert entry.keep.path not in deleted_paths
        assert album.path.exists()
        assert result.keep_intact is True

    def test_corrupted_group_skips_deletion_entirely(self, tmp_path):
        """Test 16 (execute-Ebene): eine invalide Gruppe löscht GAR
        NICHTS - auch nicht die eigentlich noch validen Kandidaten."""
        album = _write_and_candidate(tmp_path, "album/01.m4a", classification=Classification.ALBUM_LIKE)
        single_1 = _write_and_candidate(tmp_path, "singles/x.m4a", classification=Classification.SINGLE)
        single_2 = _write_and_candidate(tmp_path, "singles/x (1).m4a", classification=Classification.SINGLE)
        for c in (album, single_1, single_2):
            c.title = "Song"
            c.normalized_title = "Song"
        decision = resolve_group([album, single_1, single_2])
        plan = build_execution_plan([decision])
        entry = plan[0]
        entry.remove[0].path.write_bytes(b"corrupted")

        rebuild = _MatchingRebuild()
        rebuild.register(album)
        rebuild.register(single_1)
        rebuild.register(single_2)

        result = execute_group(entry, _always_within_root, rebuild)
        assert result.group_ok is False
        assert single_1.path.exists()
        assert single_2.path.exists()
        assert album.path.exists()
        assert all(
            r.status == FileDeleteStatus.SKIPPED_GROUP_INVALID for r in result.file_results
        )

    def test_delete_failure_reports_failed_status(self, tmp_path):
        """Test 17: Delete schlägt fehl -> korrekter Fehlerstatus, kein
        stilles Weitermachen, keine falsche Erfolgsmeldung."""
        entry, rebuild, album, single = self._resolved_plan_entry(tmp_path)

        with patch.object(Path, "unlink", side_effect=OSError("Permission denied (simuliert)")):
            result = execute_group(entry, _always_within_root, rebuild)

        assert result.group_ok is False
        assert result.file_results[0].status == FileDeleteStatus.FAILED
        assert "Permission denied" in result.file_results[0].error
        assert single.path.exists()  # tatsaechlich nicht geloescht

    def test_remove_path_identical_to_keep_path_is_refused_defensively(self, tmp_path):
        """INV-D16 defensiv, zweite Verteidigungslinie: selbst wenn die
        semantische Stufe-2-Neuentscheidung in revalidate_group() (die
        diese Sabotage strukturell bereits verhindern würde, da
        resolve_group() den KEEP-Kandidaten nie in remove_proposals
        aufnimmt) übersprungen/gepatcht wird, verweigert die Delete-
        Schleife in execute_group() das Löschen eines mit KEEP
        identischen Pfades trotzdem explizit zur Laufzeit."""
        entry, rebuild, album, single = self._resolved_plan_entry(tmp_path)
        entry.remove.append(entry.keep)  # Sabotage: KEEP als weiteren REMOVE-Kandidaten injiziert

        from services.duplicate.execution import RevalidationResult

        with patch(
            "services.duplicate.execution.revalidate_group",
            return_value=RevalidationResult(ok=True),
        ):
            result = execute_group(entry, _always_within_root, rebuild)

        keep_result = next(r for r in result.file_results if r.path == entry.keep.path)
        assert keep_result.status == FileDeleteStatus.FAILED
        assert "KEEP" in keep_result.error
        assert entry.keep.path.exists()
