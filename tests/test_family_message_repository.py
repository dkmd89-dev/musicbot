"""
Phase F3 (Family Hub) - Tests für services/family/family_message_repository.py.

Persistenzmuster analog zu tests/test_family_repository.py: Path() wird
während der Konstruktion umgeleitet, damit KEIN Test die reale
data/family_messages.json berührt.
"""

from pathlib import Path
from unittest.mock import patch

from services.family.family_message_repository import (
    MAX_STORED_MESSAGES_PER_FAMILY,
    FamilyMessageRepository,
)


def _make_repository(tmp_path):
    family_messages_file = tmp_path / "family_messages.json"

    def _fake_path(p, *args, **kwargs):
        if p == "data/family_messages.json":
            return family_messages_file
        return Path(p, *args, **kwargs)

    with patch(
        "services.family.family_message_repository.Path", side_effect=_fake_path
    ):
        repo = FamilyMessageRepository()
    return repo, family_messages_file


class TestAddMessage:
    def test_first_message_gets_id_1(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        entry = repo.add_message("main", "111", "Papa", "Hallo!")

        assert entry["id"] == 1
        assert entry["family_id"] == "main"
        assert entry["sender_user_id"] == "111"
        assert entry["sender_display_name"] == "Papa"
        assert entry["message"] == "Hallo!"
        assert "created_at" in entry

    def test_ids_increment_across_calls(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        first = repo.add_message("main", "111", "Papa", "Eins")
        second = repo.add_message("main", "222", "Mama", "Zwei")

        assert second["id"] == first["id"] + 1

    def test_ids_are_independent_per_family(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        repo.add_message("main", "111", "Papa", "Hallo Familie 1")
        other_first = repo.add_message("other", "555", "Fremd", "Hallo Familie 2")

        assert other_first["id"] == 1

    def test_message_persists_to_disk(self, tmp_path):
        repo, messages_file = _make_repository(tmp_path)
        repo.add_message("main", "111", "Papa", "Hallo!")

        reloaded = repo._load()
        assert reloaded["main"]["messages"][0]["message"] == "Hallo!"

    def test_history_is_capped_at_max_stored_messages(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        for i in range(MAX_STORED_MESSAGES_PER_FAMILY + 5):
            repo.add_message("main", "111", "Papa", f"Nachricht {i}")

        stored = repo.cache["main"]["messages"]
        assert len(stored) == MAX_STORED_MESSAGES_PER_FAMILY
        # Die ältesten wurden entfernt - die letzte Nachricht ist die neueste.
        assert stored[-1]["message"] == f"Nachricht {MAX_STORED_MESSAGES_PER_FAMILY + 4}"

    def test_failed_write_still_returns_entry_but_logs_error(self, tmp_path, monkeypatch):
        repo, _ = _make_repository(tmp_path)
        monkeypatch.setattr(
            "services.family.family_message_repository.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        entry = repo.add_message("main", "111", "Papa", "Hallo!")

        assert entry["message"] == "Hallo!"

    def test_failed_write_leaves_no_leftover_tmp_file(self, tmp_path, monkeypatch):
        repo, _ = _make_repository(tmp_path)
        monkeypatch.setattr(
            "services.family.family_message_repository.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        repo.add_message("main", "111", "Papa", "Hallo!")

        leftover = list(tmp_path.glob("*.tmp_*"))
        assert leftover == []


class TestGetRecentMessages:
    def test_returns_empty_list_for_unknown_family(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        assert repo.get_recent_messages("does-not-exist") == []

    def test_returns_messages_in_chronological_order(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        repo.add_message("main", "111", "Papa", "Eins")
        repo.add_message("main", "111", "Papa", "Zwei")
        repo.add_message("main", "111", "Papa", "Drei")

        recent = repo.get_recent_messages("main", limit=10)

        assert [m["message"] for m in recent] == ["Eins", "Zwei", "Drei"]

    def test_limit_returns_only_the_newest_n(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        for i in range(15):
            repo.add_message("main", "111", "Papa", f"Nachricht {i}")

        recent = repo.get_recent_messages("main", limit=10)

        assert len(recent) == 10
        assert recent[0]["message"] == "Nachricht 5"
        assert recent[-1]["message"] == "Nachricht 14"

    def test_does_not_leak_messages_of_other_family(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        repo.add_message("main", "111", "Papa", "Family 1")
        repo.add_message("other", "555", "Fremd", "Family 2")

        recent = repo.get_recent_messages("main", limit=10)

        assert [m["message"] for m in recent] == ["Family 1"]
