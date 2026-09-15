# control_center/routers/auth.py
# -*- coding: utf-8 -*-
"""
POST /api/v1/auth/telegram-callback + GET /api/v1/auth/whoami.

Reine Orchestrierung: ruft ausschliesslich die Verifikations-/Session-
Funktionen aus control_center/dependencies.py auf, keine eigene
Krypto-/Fachlogik hier.

BOT_TOKEN verlaesst diesen Prozess nie in Richtung Client (CLAUDE.md §12
/ Master-Prompt Regel 15/20) — nur zur serverseitigen Signaturpruefung
verwendet, niemals geloggt oder in einer Response zurueckgegeben.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from config import Config
from handlers.menu.models import AccessLevel

from ..dependencies import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    create_session_token,
    get_current_access_level,
    get_current_user_id,
    verify_telegram_login,
)
from ..schemas.auth import AuthStatusResponse, TelegramLoginPayload, WhoAmIResponse
from ..schemas.errors import ErrorDetail

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/telegram-callback", response_model=AuthStatusResponse)
def telegram_callback(payload: TelegramLoginPayload, response: Response) -> AuthStatusResponse:
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
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return AuthStatusResponse()


@router.get("/whoami", response_model=WhoAmIResponse)
def whoami(
    user_id: int = Depends(get_current_user_id),
    access_level: AccessLevel = Depends(get_current_access_level),
) -> WhoAmIResponse:
    return WhoAmIResponse(user_id=user_id, access_level=access_level.name)
