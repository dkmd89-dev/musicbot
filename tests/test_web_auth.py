# tests/test_web_auth.py
# -*- coding: utf-8 -*-
"""
Web-Paritäts-Backlog 9 — Login mit Navidrome-Benutzer: Fachlogik
(services/web_auth.py), Web-Benutzer (services/user_admin.py::
create_web_user) und Navidrome-Prüfung (services/clients/navidrome_api.py::
verify_navidrome_credentials, requests gemockt — kein echter Navidrome).
"""

from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest
import requests

from services import user_admin
from services.access_control import AccessLevel
from services.clients import navidrome_api
from services.clients.navidrome_api import (
    CREDENTIALS_INVALID,
    CREDENTIALS_OK,
    CREDENTIALS_UNAVAILABLE,
    verify_navidrome_credentials,
)
from services.web_auth import (
    AUTH_METHOD_NAVIDROME,
    AUTH_METHOD_TELEGRAM,
    LOGIN_INVALID,
    LOGIN_OK,
    LOGIN_UNAVAILABLE,
    LoginRateLimiter,
    authenticate_navidrome_login,
    cap_access_level,
    resolve_user_id_for_navidrome_user,
)

SECRET = "Sup3r-Geheim!"


class _Cfg:
    NAVIDROME_URL = "http://navidrome.local:4533/"


# ── verify_navidrome_credentials ─────────────────────────────────────────


@pytest.mark.parametrize("status,expected", [(200, CREDENTIALS_OK), (401, CREDENTIALS_INVALID), (403, CREDENTIALS_INVALID), (500, CREDENTIALS_UNAVAILABLE)])
def test_verify_maps_status_codes(monkeypatch, status, expected):
    post = Mock(return_value=Mock(status_code=status))
    monkeypatch.setattr(navidrome_api.requests, "post", post)

    assert verify_navidrome_credentials("alice", SECRET, config=_Cfg()) == expected
    url = post.call_args[0][0]
    assert url == "http://navidrome.local:4533/auth/login"
    assert SECRET not in url  # Passwort nie in der URL
    assert post.call_args.kwargs["json"] == {"username": "alice", "password": SECRET}


def test_verify_network_error_is_unavailable_and_password_not_logged(monkeypatch, caplog):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError(f"failed for {SECRET}")

    monkeypatch.setattr(navidrome_api.requests, "post", boom)
    caplog.set_level(logging.DEBUG)

    assert verify_navidrome_credentials("alice", SECRET, config=_Cfg()) == CREDENTIALS_UNAVAILABLE
    assert SECRET not in caplog.text


def test_verify_without_url_is_unavailable(monkeypatch):
    post = Mock()
    monkeypatch.setattr(navidrome_api.requests, "post", post)
    cfg = _Cfg()
    cfg.NAVIDROME_URL = ""

    assert verify_navidrome_credentials("alice", SECRET, config=cfg) == CREDENTIALS_UNAVAILABLE
    post.assert_not_called()


# ── Web-Benutzer ─────────────────────────────────────────────────────────


def test_create_web_user_allocates_negative_ids():
    users = {"123": {"role": "user", "navidrome_user": "bob"}}

    first_id, first = user_admin.create_web_user(users, "alice")
    second_id, _ = user_admin.create_web_user(users, "carol", role="admin")

    assert (first_id, second_id) == ("-1", "-2")
    assert first["account_type"] == "web" and first["role"] == "user"
    assert users["-2"]["role"] == "admin"
    assert user_admin.is_web_user_id(int(first_id))


def test_create_web_user_rejects_owner_and_duplicates():
    users = {"123": {"role": "user", "navidrome_user": "Bob"}}

    with pytest.raises(user_admin.OwnerPromotionDeniedError):
        user_admin.create_web_user(users, "alice", role="owner")
    with pytest.raises(user_admin.UserAlreadyExistsError):
        user_admin.create_web_user(users, "bob")  # ohne Groß-/Kleinschreibung
    with pytest.raises(user_admin.InvalidRoleError):
        user_admin.create_web_user(users, "alice", role="root")
    with pytest.raises(user_admin.UserAdminError):
        user_admin.create_web_user(users, "   ")


# ── Zuordnung / Login ────────────────────────────────────────────────────


USERS = {
    "111": {"role": "admin", "navidrome_user": "Robin"},
    "-1": {"role": "user", "navidrome_user": "alice", "account_type": "web"},
    "222": {"role": "user", "navidrome_user": "dup"},
    "-2": {"role": "user", "navidrome_user": "DUP", "account_type": "web"},
}


def test_resolve_linked_telegram_and_web_users():
    assert resolve_user_id_for_navidrome_user(USERS, "robin") == 111
    assert resolve_user_id_for_navidrome_user(USERS, "alice") == -1
    assert resolve_user_id_for_navidrome_user(USERS, "unknown") is None
    assert resolve_user_id_for_navidrome_user(USERS, "dup") is None  # mehrdeutig


def test_login_ok_for_linked_user():
    result = authenticate_navidrome_login(USERS, "Robin", SECRET, verifier=lambda u, p: CREDENTIALS_OK)

    assert result.status == LOGIN_OK and result.user_id == 111


def test_not_enabled_account_looks_like_wrong_password():
    wrong_pw = authenticate_navidrome_login(USERS, "alice", "x", verifier=lambda u, p: CREDENTIALS_INVALID)
    not_enabled = authenticate_navidrome_login(USERS, "fremd", SECRET, verifier=lambda u, p: CREDENTIALS_OK)

    assert wrong_pw == not_enabled
    assert wrong_pw.status == LOGIN_INVALID and wrong_pw.user_id is None


def test_navidrome_is_asked_before_enablement_check():
    verifier = Mock(return_value=CREDENTIALS_INVALID)

    authenticate_navidrome_login(USERS, "fremd", SECRET, verifier=verifier)

    verifier.assert_called_once_with("fremd", SECRET)


def test_unavailable_and_input_limits():
    assert authenticate_navidrome_login(USERS, "alice", SECRET, verifier=lambda u, p: CREDENTIALS_UNAVAILABLE).status == LOGIN_UNAVAILABLE
    never = Mock()
    assert authenticate_navidrome_login(USERS, "", SECRET, verifier=never).status == LOGIN_INVALID
    assert authenticate_navidrome_login(USERS, "alice", "", verifier=never).status == LOGIN_INVALID
    assert authenticate_navidrome_login(USERS, "a" * 500, SECRET, verifier=never).status == LOGIN_INVALID
    never.assert_not_called()


def test_cap_access_level():
    assert cap_access_level(AccessLevel.OWNER, AUTH_METHOD_NAVIDROME) == AccessLevel.ADMIN
    assert cap_access_level(AccessLevel.ADMIN, AUTH_METHOD_NAVIDROME) == AccessLevel.ADMIN
    assert cap_access_level(AccessLevel.USER, AUTH_METHOD_NAVIDROME) == AccessLevel.USER
    assert cap_access_level(AccessLevel.OWNER, AUTH_METHOD_TELEGRAM) == AccessLevel.OWNER


# ── Rate-Limit ───────────────────────────────────────────────────────────


def test_rate_limiter_blocks_after_max_failures_and_expires():
    now = [1000.0]
    limiter = LoginRateLimiter(max_failures=3, window_seconds=60, clock=lambda: now[0])
    keys = ["user:alice", "ip:1.2.3.4"]

    for _ in range(3):
        assert limiter.retry_after(keys) is None
        limiter.register_failure(keys)
    wait = limiter.retry_after(keys)
    assert wait is not None and 0 < wait <= 61
    assert limiter.retry_after(["ip:1.2.3.4"]) is not None  # IP allein gesperrt
    assert limiter.retry_after(["user:bob", "ip:9.9.9.9"]) is None

    now[0] += 61
    assert limiter.retry_after(keys) is None


def test_rate_limiter_reset_only_given_keys():
    limiter = LoginRateLimiter(max_failures=1, window_seconds=60, clock=lambda: 0.0)
    limiter.register_failure(["user:alice", "ip:1.2.3.4"])

    limiter.reset(["user:alice"])

    assert limiter.retry_after(["user:alice"]) is None
    assert limiter.retry_after(["ip:1.2.3.4"]) is not None


def test_rate_limiter_does_not_grow_with_unknown_keys():
    now = [0.0]
    limiter = LoginRateLimiter(max_failures=5, window_seconds=60, clock=lambda: now[0])
    for i in range(1000):
        limiter.retry_after([f"user:x{i}", f"ip:10.0.{i // 256}.{i % 256}"])
    assert limiter.tracked_keys() == 0

    limiter.register_failure(["user:alice"])
    now[0] += 61
    limiter.retry_after(["user:alice"])
    assert limiter.tracked_keys() == 0


def test_rate_limiter_sweeps_expired_keys_above_cap(monkeypatch):
    from services import web_auth

    monkeypatch.setattr(web_auth, "MAX_TRACKED_KEYS", 10)
    now = [0.0]
    limiter = LoginRateLimiter(max_failures=5, window_seconds=60, clock=lambda: now[0])
    for i in range(10):
        limiter.register_failure([f"ip:old{i}"])
    now[0] += 61
    limiter.register_failure(["ip:a", "ip:b"])

    assert limiter.tracked_keys() == 2
