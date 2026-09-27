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


class TestCrossInstanceVisibility:
    """Regression (FINDINGS_INDEX: "Wartungsmodus aus dem Control Center wirkt
    nicht auf den laufenden Bot"): Bot und Control Center halten je eine EIGENE
    Store-Instanz auf dieselbe Datei. Der Bot erzeugt sie einmal (langlebig),
    das CC pro Request neu. Ein Schreibvorgang der einen Instanz muss fuer die
    andere sichtbar werden, ohne Neustart."""

    def test_state_written_by_another_instance_becomes_visible(self, tmp_path):
        path = str(tmp_path / "maintenance_mode.json")
        bot_side = MaintenanceModeStore(state_file=path)   # langlebig, wie im Bot
        cc_side = MaintenanceModeStore(state_file=path)    # frisch pro CC-Request
        assert bot_side.is_active() is False

        cc_side.set_active(True, changed_by_user_id=42)

        assert bot_side.is_active() is True

    def test_deactivation_by_another_instance_becomes_visible(self, tmp_path):
        path = str(tmp_path / "maintenance_mode.json")
        bot_side = MaintenanceModeStore(state_file=path)
        bot_side.set_active(True, changed_by_user_id=1)
        MaintenanceModeStore(state_file=path).set_active(False, changed_by_user_id=42)

        assert bot_side.is_active() is False

    def test_get_state_shows_who_changed_it_externally(self, tmp_path):
        path = str(tmp_path / "maintenance_mode.json")
        bot_side = MaintenanceModeStore(state_file=path)
        MaintenanceModeStore(state_file=path).set_active(True, changed_by_user_id=42)

        state = bot_side.get_state()

        assert state.active is True
        assert state.changed_by_user_id == 42

    def test_repeated_toggles_are_all_seen(self, tmp_path):
        """Auch schnell aufeinanderfolgende Wechsel (gleiche mtime moeglich)."""
        path = str(tmp_path / "maintenance_mode.json")
        bot_side = MaintenanceModeStore(state_file=path)
        cc_side = MaintenanceModeStore(state_file=path)
        for expected in (True, False, True, False, True):
            cc_side.set_active(expected, changed_by_user_id=42)
            assert bot_side.is_active() is expected

    def test_unchanged_file_is_not_reloaded(self, tmp_path, monkeypatch):
        store = MaintenanceModeStore(state_file=str(tmp_path / "maintenance_mode.json"))
        store.set_active(True, changed_by_user_id=1)
        calls = []
        original = store._load
        monkeypatch.setattr(store, "_load", lambda: calls.append(1) or original())

        for _ in range(50):
            assert store.is_active() is True
            store.get_state()

        assert calls == []  # nur stat(), kein erneutes Parsen

    def test_own_write_does_not_trigger_a_reload(self, tmp_path, monkeypatch):
        store = MaintenanceModeStore(state_file=str(tmp_path / "maintenance_mode.json"))
        calls = []
        original = store._load
        monkeypatch.setattr(store, "_load", lambda: calls.append(1) or original())

        store.set_active(True, changed_by_user_id=1)
        assert store.is_active() is True

        assert calls == []

    def test_file_deleted_externally_falls_back_to_not_active(self, tmp_path):
        """Sicherheitsdefault der Klasse: fehlende Datei == nicht aktiv."""
        store = MaintenanceModeStore(state_file=str(tmp_path / "maintenance_mode.json"))
        store.set_active(True, changed_by_user_id=1)
        store.state_file.unlink()

        assert store.is_active() is False

    def test_file_corrupted_externally_falls_back_to_not_active(self, tmp_path):
        store = MaintenanceModeStore(state_file=str(tmp_path / "maintenance_mode.json"))
        store.set_active(True, changed_by_user_id=1)
        store.state_file.write_text("{not valid json", encoding="utf-8")

        assert store.is_active() is False  # wirft nie, sperrt nie versehentlich alle aus

    def test_corrupted_file_is_reported_once_not_on_every_check(self, tmp_path):
        store = MaintenanceModeStore(state_file=str(tmp_path / "maintenance_mode.json"))
        store.set_active(True, changed_by_user_id=1)
        store.state_file.write_text("{not valid json", encoding="utf-8")
        warnings = []
        store.logger = type("L", (), {"warning": lambda self, m: warnings.append(m),
                                      "info": lambda self, m: None,
                                      "error": lambda self, m: None})()

        store.is_active()
        after_first_check = list(warnings)
        for _ in range(20):
            store.is_active()

        assert sum("Fehler beim Laden" in w for w in after_first_check) == 1
        assert warnings == after_first_check  # keine weiteren Meldungen bei unveraenderter Datei

    def test_failed_save_keeps_in_memory_state_and_is_not_overwritten_by_stale_file(self, tmp_path, monkeypatch):
        """Bestehendes Verhalten: schlaegt das Schreiben fehl, gilt der In-Memory-
        Zustand weiter (Datei unveraendert -> kein Reload)."""
        store = MaintenanceModeStore(state_file=str(tmp_path / "maintenance_mode.json"))
        monkeypatch.setattr(MaintenanceModeStore, "_write_json_atomic",
                            staticmethod(lambda path, data: (_ for _ in ()).throw(OSError("disk full"))))

        store.set_active(True, changed_by_user_id=1)

        assert store.is_active() is True
