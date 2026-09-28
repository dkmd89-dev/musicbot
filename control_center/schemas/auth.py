# control_center/schemas/auth.py
# -*- coding: utf-8 -*-
"""Request-/Response-Schemas fuer die Telegram-Login-Widget-Integration."""

from __future__ import annotations

from pydantic import BaseModel, SecretStr


class TelegramLoginPayload(BaseModel):
    """Unveraendert vom Telegram-Login-Widget gelieferte Felder (docs/
    audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md Abschnitt 3, Schritt 2/3).
    Optionale Felder fehlen, wenn der Nutzer sie in seinem Telegram-Profil
    nicht gesetzt hat - Telegram sendet sie dann schlicht nicht mit."""

    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class AuthStatusResponse(BaseModel):
    status: str = "ok"


class WhoAmIResponse(BaseModel):
    user_id: int
    access_level: str


class NavidromeLoginPayload(BaseModel):
    """Backlog 9: Login mit Navidrome-Benutzer. Das Passwort wird nur an
    Navidrome (POST /auth/login) weitergereicht, nie gespeichert/geloggt."""

    username: str
    # SecretStr: Passwort erscheint nie in repr()/str()/Fehlerausgaben.
    password: SecretStr
