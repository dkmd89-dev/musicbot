# tests/test_library_repair_journal.py
# -*- coding: utf-8 -*-
"""
Production-Audit 2026-09-08, P3: services/library_repair/journal.py hatte
bisher kein dediziertes Testfile - RepairJournal/JournalEntry wurden nur
indirekt ueber tests/test_library_repair_executor.py mitgeprueft. Direkte
Unit-Tests fuer append/flush/Roundtrip (CLAUDE.md Abschnitt 7).
"""

import json

from services.library_repair.journal import JournalEntry, RepairJournal


def _entry(**over):
    base = dict(
        timestamp="2026-01-01T00:00:00+00:00", file="A/Singles/2020 - x.m4a",
        issue_code="GENRE_DELIMITER_INCONSISTENT", action="GENRE_DELIMITER_NORMALIZE",
        status="SUCCESS",
    )
    base.update(over)
    return JournalEntry(**base)


class TestRecordAndFlush:
    def test_record_appends_to_in_memory_entries(self, tmp_path):
        j = RepairJournal(tmp_path / "journal.jsonl")
        j.record(_entry())
        assert len(j.entries) == 1

    def test_flush_writes_one_line_per_entry_and_clears_buffer(self, tmp_path):
        path = tmp_path / "journal.jsonl"
        j = RepairJournal(path)
        j.record(_entry(file="a.m4a"))
        j.record(_entry(file="b.m4a", status="SKIPPED"))
        j.flush()
        assert j.entries == []
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["file"] == "a.m4a"
        assert json.loads(lines[1])["status"] == "SKIPPED"

    def test_flush_is_append_only_across_multiple_calls(self, tmp_path):
        path = tmp_path / "journal.jsonl"
        j = RepairJournal(path)
        j.record(_entry(file="a.m4a"))
        j.flush()
        j.record(_entry(file="b.m4a"))
        j.flush()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert [json.loads(l)["file"] for l in lines] == ["a.m4a", "b.m4a"]

    def test_flush_with_no_entries_does_not_create_file(self, tmp_path):
        path = tmp_path / "journal.jsonl"
        j = RepairJournal(path)
        j.flush()
        assert not path.exists()

    def test_flush_creates_missing_parent_directories(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "journal.jsonl"
        j = RepairJournal(path)
        j.record(_entry())
        j.flush()
        assert path.exists()


class TestJournalEntryRoundtrip:
    def test_all_fields_survive_json_roundtrip(self, tmp_path):
        path = tmp_path / "journal.jsonl"
        j = RepairJournal(path)
        j.record(_entry(
            before={"genre_tag": ["Pop / Rock"]}, after={"genre_tag": ["Pop; Rock"]},
            sha256_before="aaa", sha256_after="bbb",
            audio_sha256_before="MD5=x", audio_sha256_after="MD5=x",
            backup_path="/backups/a.m4a.bak", error=None, dry_run=False,
        ))
        j.flush()
        loaded = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert loaded["before"] == {"genre_tag": ["Pop / Rock"]}
        assert loaded["after"] == {"genre_tag": ["Pop; Rock"]}
        assert loaded["audio_sha256_before"] == loaded["audio_sha256_after"] == "MD5=x"
        assert loaded["backup_path"] == "/backups/a.m4a.bak"
        assert loaded["dry_run"] is False

    def test_optional_fields_default_sensibly(self):
        e = JournalEntry(timestamp="t", file="a.m4a", issue_code="X", action="Y",
                         status="SKIPPED")
        assert e.before == {}
        assert e.after == {}
        assert e.error is None
        assert e.backup_path is None
        assert e.dry_run is False


class TestSummary:
    def test_summary_counts_by_status_before_flush(self, tmp_path):
        j = RepairJournal(tmp_path / "journal.jsonl")
        j.record(_entry(status="SUCCESS"))
        j.record(_entry(status="SUCCESS"))
        j.record(_entry(status="SKIPPED"))
        s = j.summary()
        assert s["total"] == 3
        assert s["SUCCESS"] == 2
        assert s["SKIPPED"] == 1

    def test_summary_reflects_only_unflushed_entries(self, tmp_path):
        """flush() leert den In-Memory-Puffer - summary() spiegelt bewusst
        nur noch nicht geschriebene Eintraege, keine historische
        Gesamtzahl."""
        path = tmp_path / "journal.jsonl"
        j = RepairJournal(path)
        j.record(_entry())
        j.flush()
        assert j.summary()["total"] == 0
