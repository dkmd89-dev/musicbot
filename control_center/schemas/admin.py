# control_center/schemas/admin.py
# -*- coding: utf-8 -*-
"""
Schemas für /api/v1/admin/users — GET (read-only Liste) sowie
CC-AC-10B: POST/PATCH/DELETE (User Management Write-Parität).

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

from pydantic import BaseModel, Field


class UserEntry(BaseModel):
    telegram_id: int
    role: str
    navidrome_user: Optional[str] = None
    created_at: Optional[str] = None


class UsersResponse(BaseModel):
    users: list[UserEntry]


# ── CC-AC-10B: Write-Endpunkte ──────────────────────────────────────────
#
# Eigenes Response-Schema (statt UserEntry) für Mutationen: UserEntry lässt
# "permissions" absichtlich weg (siehe Docstring oben, von
# test_get_users_response_omits_permissions_field abgesichert) — die
# Mutations-Endpunkte selbst betreffen aber teils genau dieses Feld, daher
# eigenes, vollständigeres Schema statt UserEntry nachträglich zu ändern.


class UserDetailResponse(BaseModel):
    telegram_id: int
    role: str
    navidrome_user: Optional[str] = None
    created_at: Optional[str] = None
    permissions: list[str] = Field(default_factory=list)


class DeleteUserResponse(BaseModel):
    telegram_id: int
    role: str


class CreateUserRequest(BaseModel):
    telegram_id: int
    navidrome_user: str


class UpdateNavidromeRequest(BaseModel):
    navidrome_user: str


class UpdateRoleRequest(BaseModel):
    role: str


class UpdatePermissionsRequest(BaseModel):
    permissions: list[str]
