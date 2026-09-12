"""
Phase F1 (Family Hub) - Characterization-/Regressionstests für
services/family/family_repository.py.

Persistenzmuster ist 1:1 aus UserManagementHandler._save_users()
übernommen (siehe Docstring dort sowie
tests/test_user_management_atomic_persistence.py) - dieselbe
Test-Strategie: Path() wird während der Konstruktion auf ein tmp_path
umgeleitet, damit KEIN Test jemals die reale data/family_data.json
berührt.
"""

from pathlib import Path
from unittest.mock import patch

from services.family.family_repository import FamilyRepository


def _make_repository(tmp_path):
    family_data_file = tmp_path / "family_data.json"

    def _fake_path(p, *args, **kwargs):
        if p == "data/family_data.json":
            return family_data_file
        return Path(p, *args, **kwargs)

    with patch(
        "services.family.family_repository.Path", side_effect=_fake_path
    ):
        repo = FamilyRepository()
    return repo, family_data_file


class TestLoadFamilies:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        assert repo.get_all_families() == {}

    def test_existing_file_is_loaded_into_cache(self, tmp_path):
        family_data_file = tmp_path / "family_data.json"
        family_data_file.write_text(
            '{"main": {"name": "Familie", "members": {}}}', encoding="utf-8"
        )

        def _fake_path(p, *args, **kwargs):
            if p == "data/family_data.json":
                return family_data_file
            return Path(p, *args, **kwargs)

        with patch(
            "services.family.family_repository.Path", side_effect=_fake_path
        ):
            repo = FamilyRepository()

        assert repo.get_all_families() == {"main": {"name": "Familie", "members": {}}}

    def test_corrupt_json_returns_empty_dict_and_does_not_raise(self, tmp_path):
        family_data_file = tmp_path / "family_data.json"
        family_data_file.write_text("{not valid json", encoding="utf-8")

        def _fake_path(p, *args, **kwargs):
            if p == "data/family_data.json":
                return family_data_file
            return Path(p, *args, **kwargs)

        with patch(
            "services.family.family_repository.Path", side_effect=_fake_path
        ):
            repo = FamilyRepository()

        assert repo.get_all_families() == {}


class TestSaveFamiliesAtomicWrite:
    def test_interrupted_write_leaves_previous_valid_data_untouched(
        self, tmp_path, monkeypatch
    ):
        repo, family_data_file = _make_repository(tmp_path)

        ok = repo._save_families({"main": {"name": "Familie", "members": {}}})
        assert ok is True
        original_content = family_data_file.read_text(encoding="utf-8")

        monkeypatch.setattr(
            "services.family.family_repository.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        result = repo._save_families({})  # würde die Familie "entfernen"

        assert result is False
        assert family_data_file.read_text(encoding="utf-8") == original_content

    def test_interrupted_write_leaves_no_leftover_tmp_file(self, tmp_path, monkeypatch):
        repo, _ = _make_repository(tmp_path)
        monkeypatch.setattr(
            "services.family.family_repository.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        repo._save_families({"main": {"name": "Familie", "members": {}}})

        leftover = list(tmp_path.glob("*.tmp_*"))
        assert leftover == []

    def test_interrupted_write_does_not_update_in_memory_cache(
        self, tmp_path, monkeypatch
    ):
        repo, _ = _make_repository(tmp_path)
        repo._save_families({"main": {"name": "Familie", "members": {}}})

        monkeypatch.setattr(
            "services.family.family_repository.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        repo._save_families({})

        assert "main" in repo.family_data_cache

    def test_successful_write_updates_file_and_cache(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        ok = repo._save_families({"main": {"name": "Familie", "members": {}}})

        assert ok is True
        assert "main" in repo.family_data_cache
        reloaded = repo._load_families()
        assert reloaded == {"main": {"name": "Familie", "members": {}}}


class TestGetFamily:
    def test_get_family_returns_empty_dict_for_unknown_id(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        assert repo.get_family("unknown") == {}

    def test_get_all_families_returns_a_copy_not_the_live_cache(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        repo._save_families({"main": {"name": "Familie", "members": {}}})

        snapshot = repo.get_all_families()
        del snapshot["main"]

        assert "main" in repo.family_data_cache


class TestUpdateMember:
    def _seed(self, repo):
        repo._save_families(
            {
                "main": {
                    "name": "Familie",
                    "members": {
                        "111": {
                            "display_name": "Papa",
                            "navidrome_user": "papa",
                            "active": True,
                            "notifications": True,
                        }
                    },
                }
            }
        )

    def test_merges_updates_into_existing_member(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        self._seed(repo)

        ok = repo.update_member("main", "111", {"notifications": False})

        assert ok is True
        assert repo.family_data_cache["main"]["members"]["111"]["notifications"] is False
        # Andere Felder bleiben unangetastet
        assert repo.family_data_cache["main"]["members"]["111"]["display_name"] == "Papa"

    def test_persists_to_disk(self, tmp_path):
        repo, family_data_file = _make_repository(tmp_path)
        self._seed(repo)

        repo.update_member("main", "111", {"notifications": False})

        reloaded = repo._load_families()
        assert reloaded["main"]["members"]["111"]["notifications"] is False

    def test_returns_false_for_unknown_family_id(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        self._seed(repo)

        ok = repo.update_member("does-not-exist", "111", {"notifications": False})

        assert ok is False

    def test_returns_false_for_unknown_telegram_id(self, tmp_path):
        repo, _ = _make_repository(tmp_path)
        self._seed(repo)

        ok = repo.update_member("main", "999", {"notifications": False})

        assert ok is False

    def test_failed_write_does_not_mutate_live_cache(self, tmp_path, monkeypatch):
        repo, _ = _make_repository(tmp_path)
        self._seed(repo)

        monkeypatch.setattr(
            "services.family.family_repository.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        ok = repo.update_member("main", "111", {"notifications": False})

        assert ok is False
        assert repo.family_data_cache["main"]["members"]["111"]["notifications"] is True
