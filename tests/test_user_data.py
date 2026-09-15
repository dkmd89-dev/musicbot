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

from services.user_data import get_navidrome_user, get_user_role, load_user_data


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
