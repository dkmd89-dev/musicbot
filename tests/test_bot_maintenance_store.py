"""
Bot-Wartungsmodus (docs/MusicBot_TELEGRAM_MENU_SYSTEM.md, Ein-/Ausschalten
über Telegram-Inline-Buttons): Tests für
services/bot_maintenance.py::MaintenanceModeStore.

Struktureller Zwilling zu tests/test_download_history_store.py
(DownloadHistoryStore) - gleiches Muster: pro-Test-tmp_path-Fixture,
Persistenz über eine frische Instanz verifiziert statt nur
In-Memory-State.
"""

import json

import pytest

from services.bot_maintenance import MaintenanceModeStore, MaintenanceState


@pytest.fixture
def store(tmp_path):
    return MaintenanceModeStore(state_file=str(tmp_path / "maintenance_mode.json"))


class TestDefaultState:
    def test_missing_file_defaults_to_not_active(self, tmp_path):
        fresh = MaintenanceModeStore(state_file=str(tmp_path / "fresh" / "maintenance_mode.json"))
        assert fresh.is_active() is False

    def test_corrupted_file_falls_back_to_not_active_without_raising(self, tmp_path):
        state_file = tmp_path / "corrupt.json"
        state_file.write_text("{not valid json", encoding="utf-8")
        broken = MaintenanceModeStore(state_file=str(state_file))
        assert broken.is_active() is False


class TestSetActiveAndPersistence:
    def test_set_active_true_is_reflected_immediately(self, store):
        store.set_active(True, changed_by_user_id=12345)
        assert store.is_active() is True

    def test_set_active_false_is_reflected_immediately(self, store):
        store.set_active(True, changed_by_user_id=12345)
        store.set_active(False, changed_by_user_id=12345)
        assert store.is_active() is False

    def test_state_survives_reload_from_disk(self, store):
        store.set_active(True, changed_by_user_id=999)
        reloaded = MaintenanceModeStore(state_file=str(store.state_file))
        assert reloaded.is_active() is True

    def test_written_file_is_valid_json_with_expected_fields(self, store):
        store.set_active(True, changed_by_user_id=42)
        with open(store.state_file, encoding="utf-8") as f:
            data = json.load(f)
        assert data["active"] is True
        assert data["changed_by_user_id"] == 42
        assert data["changed_at"]  # nicht leer

    def test_get_state_returns_full_state_object(self, store):
        store.set_active(True, changed_by_user_id=7)
        state = store.get_state()
        assert isinstance(state, MaintenanceState)
        assert state.active is True
        assert state.changed_by_user_id == 7


class TestMaintenanceStateRoundtrip:
    def test_to_dict_from_dict_roundtrip(self):
        state = MaintenanceState(
            active=True, changed_at="2026-09-03T12:00:00", changed_by_user_id=1
        )
        restored = MaintenanceState.from_dict(state.to_dict())
        assert restored == state

    def test_from_dict_missing_fields_defaults_to_not_active(self):
        state = MaintenanceState.from_dict({})
        assert state.active is False
        assert state.changed_at is None
        assert state.changed_by_user_id is None
