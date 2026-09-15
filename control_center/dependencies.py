# control_center/dependencies.py
# -*- coding: utf-8 -*-
"""
Auth-Grundgerüst (Vertical Slice "Health/Dashboard", Schritt 3):
Telegram-Login-Widget-Verifikation + signierte Session-Cookies +
Dev-Auth-Bypass, gemäß docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md
Abschnitt 3.

Reuse: Die AccessLevel-Auflösung nutzt denselben, bereits Telegram-freien
Auth-Kern wie der Bot selbst (handlers/menu/permissions.py::
get_user_access_level(), handlers/menu/models.py::AccessLevel) — beide
Module erklären in ihrem eigenen Docstring ausdrücklich, keine Abhängigkeit
auf Telegram-Infrastruktur zu haben. Das ist Wiederverwendung von bereits
isolierter, Telegram-freier Auth-Logik (Master-Prompt Regel 51 "Common
Core"), kein Bruch der handlers/-Schichtgrenze im Sinne von CLAUDE.md §4.

MODERATOR-Auflösung (Nachtrag): get_user_access_level() nimmt ein Objekt
mit `.user_data_cache`-Attribut als `user_mgmt_handler` entgegen (siehe
dortiger hasattr()-Check) — statt dafür die schwerere, Telegram-
gekoppelte handlers/admin/user_management_handler.py::UserManagementHandler
zu importieren, baut _UserDataCacheAdapter unten ein minimales
Adapter-Objekt um services/user_data.py::load_user_data() (dieselbe,
jetzt geteilte Telegram-freie Kernlogik, Master-Prompt Regel 51 "Common
Core"). permissions.py selbst bleibt dabei unverändert.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Optional

from fastapi import Cookie, Depends, HTTPException

from config import Config
from handlers.menu.models import AccessLevel
from handlers.menu.permissions import get_user_access_level
from logger import get_module_logger
from services.user_data import load_user_data

from .schemas.errors import ErrorDetail

_logger = get_module_logger("control_center.auth")

SESSION_COOKIE_NAME = "cc_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 Tage
TELEGRAM_AUTH_MAX_AGE_SECONDS = 24 * 3600  # Telegram-eigene Empfehlung: 1 Tag


# ─────────────────────────────────────────────────────────────────────────
# Telegram-Login-Widget-Verifikation
# ─────────────────────────────────────────────────────────────────────────


def verify_telegram_login(data: dict, *, bot_token: str) -> bool:
    """Verifiziert die vom Telegram-Login-Widget signierten Daten
    (Standard-Telegram-Algorithmus, siehe docs/audits/
    CONTROL_CENTER_ARCHITECTURE_2026-09-15.md Abschnitt 3, Schritt 4):

        secret_key = SHA256(bot_token)
        check_hash = HMAC-SHA256(secret_key, data_check_string)

    Prüft zusätzlich auth_date-Frische (Telegram-eigene Empfehlung) —
    verhindert Replay eines abgefangenen, aber längst abgelaufenen
    Login-Payloads."""
    received_hash = data.get("hash")
    if not received_hash:
        return False

    check_fields = {k: v for k, v in data.items() if k != "hash" and v is not None}
    data_check_string = "\n".join(f"{k}={check_fields[k]}" for k in sorted(check_fields))

    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, str(received_hash)):
        return False

    try:
        auth_age = time.time() - float(check_fields.get("auth_date"))
    except (TypeError, ValueError):
        return False
    return 0 <= auth_age <= TELEGRAM_AUTH_MAX_AGE_SECONDS


# ─────────────────────────────────────────────────────────────────────────
# Signierte Session-Cookies
# ─────────────────────────────────────────────────────────────────────────


def _session_secret(bot_token: str) -> bytes:
    """Leitet den Session-Signing-Key aus BOT_TOKEN ab, statt ein
    zusätzliches Secret einzuführen (Master-Prompt Regel 25: Konfigurations-
    fläche minimieren, solange kein konkreter Bedarf für ein eigenes
    SESSION_SECRET besteht). Eine Bot-Token-Rotation invalidiert dadurch
    automatisch alle bestehenden Sessions — für den aktuellen
    Single-Server-MVP-Scope akzeptabel."""
    return hashlib.sha256(f"control_center_session_v1:{bot_token}".encode("utf-8")).digest()


def create_session_token(user_id: int, *, bot_token: str) -> str:
    payload = {"user_id": user_id, "issued_at": time.time()}
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    signature = hmac.new(
        _session_secret(bot_token), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_session_token(token: str, *, bot_token: str) -> Optional[int]:
    """Gibt die user_id zurück, wenn Signatur gültig und Session nicht
    abgelaufen ist — sonst None. Ein ungültiger/abgelaufener Client-Cookie
    ist ein Normalfall (z. B. nach Ablauf oder Bot-Token-Rotation), keine
    Exception."""
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError:
        return None

    expected_signature = hmac.new(
        _session_secret(bot_token), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        return None

    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
        user_id = int(payload["user_id"])
        issued_at = float(payload["issued_at"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None

    if time.time() - issued_at > SESSION_TTL_SECONDS:
        return None
    return user_id


# ─────────────────────────────────────────────────────────────────────────
# FastAPI-Dependencies
# ─────────────────────────────────────────────────────────────────────────


def _unauthorized(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=401, detail=ErrorDetail(code=code, message=message).model_dump()
    )


def get_current_user_id(cc_session: Optional[str] = Cookie(default=None)) -> int:
    config = Config()

    if config.CONTROL_CENTER_DEV_AUTH_BYPASS:
        _logger.warning(
            "⚠️ CONTROL_CENTER_DEV_AUTH_BYPASS aktiv — Anfrage wird ohne "
            "echte Authentifizierung als OWNER behandelt. NIEMALS in einer "
            "von aussen erreichbaren Umgebung aktivieren."
        )
        return config.OWNER_USER_ID

    if not cc_session:
        raise _unauthorized("NOT_AUTHENTICATED", "Keine gültige Session.")

    user_id = verify_session_token(cc_session, bot_token=config.BOT_TOKEN)
    if user_id is None:
        raise _unauthorized("SESSION_INVALID", "Session ungültig oder abgelaufen.")
    return user_id


class _UserDataCacheAdapter:
    """Minimaler Adapter fuer get_user_access_level()'s duck-typed
    `user_mgmt_handler`-Parameter (siehe Modul-Docstring)."""

    def __init__(self, user_data: dict) -> None:
        self.user_data_cache = user_data


def get_current_access_level(
    user_id: int = Depends(get_current_user_id),
) -> AccessLevel:
    config = Config()
    user_data = load_user_data(Path(config.DATA_DIR) / "user_data.json", logger=_logger)
    adapter = _UserDataCacheAdapter(user_data)
    return get_user_access_level(user_id, config, user_mgmt_handler=adapter)


def require_min_access_level(minimum: AccessLevel):
    """Dependency-Factory — Authorization läuft serverseitig in jedem
    Router, nicht als reiner UI-Check (Master-Prompt Regel 30)."""

    def _check(level: AccessLevel = Depends(get_current_access_level)) -> AccessLevel:
        if level.value < minimum.value:
            raise HTTPException(
                status_code=403,
                detail=ErrorDetail(
                    code="FORBIDDEN", message="Nicht ausreichend berechtigt."
                ).model_dump(),
            )
        return level

    return _check
