# tests/test_user_data.py
# -*- coding: utf-8 -*-
"""
services/user_data.py — Telegram-freie Kernlogik für data/user_data.json,
extrahiert aus handlers/admin/user_management_handler.py::
UserManagementHandler (Master-Prompt Regel 51 "Common Core").

Siehe tests/test_user_management_handler.py für die Bestätigung, dass
UserManagementHandler._load_users()/get_navidrome_user() nach der
Extraktion unverändertes Verhalten zeigen (dünne Delegatoren).
"""

from __future__ import annotations

import json
import threading

import pytest

from services.user_data import (
    get_navidrome_user,
    get_user_role,
    load_user_data,
    update_user_data,
)


class TestLoadUserData:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert load_user_data(tmp_path / "does-not-exist.json") == {}

    def test_valid_file_is_loaded(self, tmp_path):
        path = tmp_path / "user_data.json"
        path.write_text(json.dumps({"123": {"role": "admin"}}), encoding="utf-8")
        assert load_user_data(path) == {"123": {"role": "admin"}}

    def test_corrupted_file_returns_empty_dict_without_raising(self, tmp_path):
        path = tmp_path / "user_data.json"
        path.write_text("{not valid json", encoding="utf-8")
        assert load_user_data(path) == {}

    def test_corrupted_file_logs_error_when_logger_given(self, tmp_path):
        path = tmp_path / "user_data.json"
        path.write_text("{not valid json", encoding="utf-8")
        logged = []

        class _FakeLogger:
            def error(self, msg):
                logged.append(msg)

        load_user_data(path, logger=_FakeLogger())
        assert len(logged) == 1
        assert "User-Daten" in logged[0]


class TestGetNavidromeUser:
    def test_returns_configured_value(self):
        user_data = {"222": {"navidrome_user": "robin"}}
        assert get_navidrome_user(user_data, 222) == "robin"

    def test_returns_none_when_unset(self):
        assert get_navidrome_user({"222": {}}, 222) is None

    def test_returns_none_for_blank_string(self):
        user_data = {"222": {"navidrome_user": "   "}}
        assert get_navidrome_user(user_data, 222) is None

    def test_returns_none_for_unknown_telegram_id(self):
        assert get_navidrome_user({}, 999) is None


class TestGetUserRole:
    def test_returns_configured_role(self):
        assert get_user_role({"1": {"role": "moderator"}}, 1) == "moderator"

    def test_returns_none_for_unknown_telegram_id(self):
        assert get_user_role({}, 1) is None


class TestUpdateUserData:
    """A.7 (Client Consolidation Phase A, "Cross-Process-Persistenzstrategie"):
    update_user_data() ist der einzige Weg, auf dem beide Clients
    (UserManagementHandler._update_users(), control_center/routers/admin.py)
    mutierende User-Management-Operationen ausführen — der ganze
    Load->Mutator->Save-Zyklus läuft dabei hinter einem fcntl.flock auf
    einer <path>.lock-Datei, damit bot.service und control-center.service
    (zwei unabhängige, dauerhaft laufende Prozesse auf derselben
    data/user_data.json) sich nicht gegenseitig ein Update überschreiben."""

    def test_mutator_result_and_mutated_dict_are_saved(self, tmp_path):
        path = tmp_path / "user_data.json"

        def _mutate(users):
            users["1"] = {"role": "user"}
            return "created"

        result, users, saved = update_user_data(_mutate, path)

        assert result == "created"
        assert saved is True
        assert users == {"1": {"role": "user"}}
        assert load_user_data(path) == {"1": {"role": "user"}}

    def test_mutator_exception_aborts_cycle_without_saving(self, tmp_path):
        """Ein Mutator, der eine UserAdminError-artige Exception wirft (z. B.
        SEC-005-Owner-Guard), darf den bereits geladenen, in-memory
        mutierten Zustand NICHT persistieren — sonst würde z. B. eine
        abgelehnte Owner-Degradierung trotzdem geschrieben."""
        path = tmp_path / "user_data.json"
        path.write_text(json.dumps({"1": {"role": "owner"}}), encoding="utf-8")

        class _OwnerGuardDenied(Exception):
            pass

        def _mutate(users):
            users["1"]["role"] = "user"  # wuerde den Owner degradieren
            raise _OwnerGuardDenied("abgelehnt")

        with pytest.raises(_OwnerGuardDenied):
            update_user_data(_mutate, path)

        assert load_user_data(path) == {"1": {"role": "owner"}}

    def test_concurrent_updates_do_not_lose_writes(self, tmp_path):
        """Simuliert das Lost-Update-Race zwischen bot.service und
        control-center.service über parallele Threads, die alle denselben
        Zaehler in derselben Datei erhoehen. Ohne den Lock wuerden manche
        Erhoehungen auf einem veralteten, bereits ueberholten Stand
        aufsetzen und dadurch verloren gehen."""
        path = tmp_path / "user_data.json"
        path.write_text(json.dumps({"counter": {"n": 0}}), encoding="utf-8")

        def _increment(users):
            users["counter"]["n"] += 1

        threads = [
            threading.Thread(target=update_user_data, args=(_increment, path))
            for _ in range(25)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert load_user_data(path)["counter"]["n"] == 25

    def test_lock_file_created_next_to_data_file(self, tmp_path):
        path = tmp_path / "user_data.json"
        update_user_data(lambda users: None, path)
        assert (tmp_path / "user_data.json.lock").exists()
