# control_center/schemas/admin.py
# -*- coding: utf-8 -*-
"""
Response-Schema für GET /api/v1/admin/users.

Dünnes Mapping über data/user_data.json hinweg (services/user_data.py::
load_user_data()) — reduziert auf die Felder, die
handlers/admin/user_management_handler.py in seiner eigenen
Benutzerlisten-Ansicht bereits anzeigt (role/navidrome_user/created_at),
kein 1:1-Durchreichen des Roh-Dicts (z. B. "permissions" bewusst
ausgelassen — nicht Teil der aktuellen Anzeige-Anforderung).

Der Owner (config.OWNER_USER_ID) wird primär per .env konfiguriert, NICHT
über data/user_data.json verwaltet — er kann dort trotzdem zusätzlich als
Eintrag auftauchen (in der Produktionsdatei bereits beobachtet, z. B. mit
role="owner"), das ist kein Fehler dieser Route: sie zeigt unverändert,
was tatsächlich in der Datei steht. Massgeblich für die AccessLevel-
Auflösung bleibt in jedem Fall ausschliesslich config.OWNER_USER_ID
(siehe control_center/dependencies.py), niemals ein hier angezeigter
role-Wert. Enthält ebenfalls NICHT "pending_users"
(Nutzer, die auf Freigabe warten) — das ist In-Memory-Zustand von
UserManagementHandler im Bot-Prozess, identisches Cross-Prozess-Problem
wie bei ActiveDownloadRegistry (siehe control_center/routers/downloads.py).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class UserEntry(BaseModel):
    telegram_id: int
    role: str
    navidrome_user: Optional[str] = None
    created_at: Optional[str] = None


class UsersResponse(BaseModel):
    users: list[UserEntry]
