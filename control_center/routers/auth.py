# control_center/routers/auth.py
# -*- coding: utf-8 -*-
"""
POST /api/v1/auth/telegram-callback + POST /api/v1/auth/navidrome-login
+ POST /api/v1/auth/logout + GET /api/v1/auth/whoami.

Reine Orchestrierung: ruft ausschliesslich die Verifikations-/Session-
Funktionen aus control_center/dependencies.py auf, keine eigene
Krypto-/Fachlogik hier.

BOT_TOKEN verlaesst diesen Prozess nie in Richtung Client (CLAUDE.md §12
/ Master-Prompt Regel 15/20) — nur zur serverseitigen Signaturpruefung
verwendet, niemals geloggt oder in einer Response zurueckgegeben.
"""

from __future__ import annotations

from pathlib import Path

from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response

from config import Config
from logger import get_module_logger
from services import web_auth
from services.user_data import load_user_data
from services.access_control import AccessLevel

from ..dependencies import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    create_session_token,
    get_current_access_level,
    get_current_user_id,
    verify_same_origin,
    verify_session_token,
    verify_telegram_login,
)
from ..schemas.auth import (
    AuthStatusResponse,
    NavidromeLoginPayload,
    TelegramLoginPayload,
    WhoAmIResponse,
)
from ..schemas.errors import ErrorDetail

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_logger = get_module_logger("control_center.auth")

_TRUSTED_PROXY_HOSTS = {"127.0.0.1", "::1"}


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        # Subpath-Betrieb (siehe control_center/root_path.py): Cookie nur an
        # den eigenen Prefix binden (z. B. "/controlcenter"), damit es nicht
        # an andere Apps derselben Domain (Immich, Navidrome, ...) geht.
        # Direktbetrieb (root_path == "") -> "/" wie bisher.
        path=request.scope.get("root_path", "") or "/",
    )


def _clear_session_cookie(response: Response, request: Request) -> None:
    """Gegenstück zu _set_session_cookie(): identischer Path/Secure/
    HttpOnly/SameSite - ein abweichender Path würde das Cookie nicht
    löschen (Subpath-Betrieb hinter nginx, siehe root_path.py)."""
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path=request.scope.get("root_path", "") or "/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def _client_ip(request: Request) -> str:
    """Client-IP für das Login-Rate-Limit. X-Forwarded-For nur, wenn die
    Verbindung vom lokalen nginx kommt (uvicorn bindet an 127.0.0.1) -
    dann der letzte Eintrag (von nginx per $proxy_add_x_forwarded_for
    angehängt, nicht vom Client fälschbar)."""
    host = request.client.host if request.client else "unknown"
    if host in _TRUSTED_PROXY_HOSTS:
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return host


def _get_login_limiter(request: Request) -> web_auth.LoginRateLimiter:
    limiter = getattr(request.app.state, "login_rate_limiter", None)
    if limiter is None:
        limiter = web_auth.LoginRateLimiter()
        request.app.state.login_rate_limiter = limiter
    return limiter


@router.post("/telegram-callback", response_model=AuthStatusResponse)
def telegram_callback(
    payload: TelegramLoginPayload, request: Request, response: Response
) -> AuthStatusResponse:
    config = Config()
    data = payload.model_dump(exclude_none=True)

    if not verify_telegram_login(data, bot_token=config.BOT_TOKEN):
        raise HTTPException(
            status_code=401,
            detail=ErrorDetail(
                code="TELEGRAM_LOGIN_INVALID",
                message="Telegram-Login-Signatur ungültig oder abgelaufen.",
            ).model_dump(),
        )

    token = create_session_token(payload.id, bot_token=config.BOT_TOKEN)
    _set_session_cookie(response, request, token)
    return AuthStatusResponse()


@router.post(
    "/navidrome-login",
    response_model=AuthStatusResponse,
    dependencies=[Depends(verify_same_origin)],
)
def navidrome_login(
    payload: NavidromeLoginPayload, request: Request, response: Response
) -> AuthStatusResponse:
    """Backlog 9: Login mit Navidrome-Benutzer (auch ohne Telegram-Konto).
    Nur für vom Admin freigeschaltete Navidrome-Benutzer; Rolle höchstens
    ADMIN (Session mit auth="navidrome"). Passwort wird nie geloggt."""
    config = Config()
    limiter = _get_login_limiter(request)
    username = (payload.username or "").strip()
    user_key = f"user:{username.casefold()[:web_auth.MAX_USERNAME_LENGTH]}"
    ip_key = f"ip:{_client_ip(request)}"
    safe_username = username[:64]

    retry_after = limiter.retry_after([user_key, ip_key])
    if retry_after is not None:
        _logger.warning(f"🔒 Navidrome-Login gesperrt (Rate-Limit): user={safe_username!r} {ip_key}")
        raise HTTPException(
            status_code=429,
            detail=ErrorDetail(
                code="LOGIN_RATE_LIMITED",
                message="Zu viele Fehlversuche. Bitte später erneut versuchen.",
            ).model_dump(),
            headers={"Retry-After": str(retry_after)},
        )

    user_data = load_user_data(Path(config.DATA_DIR) / "user_data.json", logger=_logger)
    result = web_auth.authenticate_navidrome_login(
        user_data, username, payload.password.get_secret_value()
    )

    if result.status == web_auth.LOGIN_UNAVAILABLE:
        _logger.error(f"❌ Navidrome-Login nicht möglich (Navidrome nicht erreichbar): user={safe_username!r}")
        raise HTTPException(
            status_code=503,
            detail=ErrorDetail(
                code="NAVIDROME_UNAVAILABLE",
                message="Login über Navidrome derzeit nicht möglich. Telegram-Login funktioniert weiterhin.",
            ).model_dump(),
        )
    if result.status != web_auth.LOGIN_OK:
        limiter.register_failure([user_key, ip_key])
        _logger.warning(f"⚠️ Navidrome-Login fehlgeschlagen: user={safe_username!r} {ip_key}")
        raise HTTPException(
            status_code=401,
            detail=ErrorDetail(
                code="LOGIN_INVALID", message="Benutzername oder Passwort falsch."
            ).model_dump(),
        )

    limiter.reset([user_key])
    token = create_session_token(
        result.user_id, bot_token=config.BOT_TOKEN, auth=web_auth.AUTH_METHOD_NAVIDROME
    )
    _set_session_cookie(response, request, token)
    _logger.info(f"✅ Navidrome-Login: user={safe_username!r} -> user_id={result.user_id}")
    return AuthStatusResponse()


@router.post(
    "/logout",
    response_model=AuthStatusResponse,
    dependencies=[Depends(verify_same_origin)],
)
def logout(
    request: Request, response: Response, cc_session: Optional[str] = Cookie(default=None)
) -> AuthStatusResponse:
    """Abmelden: löscht das Session-Cookie im Browser. Idempotent - auch
    ohne (gültige) Session 200. Einschränkung (bewusst, dokumentiert): Die
    Session ist ein signiertes Cookie ohne serverseitigen Speicher - eine
    vorher kopierte Cookie-Kopie bliebe bis zum Ablauf gültig; sofort
    sperren weiterhin über Rolle/Löschen in der Nutzerverwaltung."""
    user_id = None
    if cc_session:
        user_id = verify_session_token(cc_session, bot_token=Config().BOT_TOKEN)
    _clear_session_cookie(response, request)
    if user_id is not None:
        _logger.info(f"👋 Abgemeldet: user_id={user_id}")
    return AuthStatusResponse()


@router.get("/whoami", response_model=WhoAmIResponse)
def whoami(
    user_id: int = Depends(get_current_user_id),
    access_level: AccessLevel = Depends(get_current_access_level),
) -> WhoAmIResponse:
    return WhoAmIResponse(user_id=user_id, access_level=access_level.name)
