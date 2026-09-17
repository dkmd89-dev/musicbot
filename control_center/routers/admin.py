# control_center/routers/admin.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/admin/users — registrierte Nutzer/Rollen (read-only).

Reine Orchestrierung: liest ausschliesslich die bestehende, persistente
data/user_data.json ueber services/user_data.py::load_user_data()
(dieselbe Common-Core-Extraktion, die auch control_center/dependencies.py
fuer die MODERATOR-Aufloesung nutzt) — kein Schreibzugriff (Master-Prompt
Regel 12: GET ohne Seiteneffekte). Keine Rollenverwaltung hier (Aendern/
Hinzufuegen/Entfernen bleibt vollstaendig der Telegram-Admin-UI
vorbehalten, siehe handlers/admin/user_management_handler.py) — dieser
Schritt ist explizit auf "nur anzeigen" begrenzt.

Authentifiziert mit mindestens AccessLevel.ADMIN — Rollen-/Navidrome-
Zuordnung anderer Nutzer ist eindeutig Administrationsdaten, identische
Schwelle wie routers/findings.py/repair.py/downloads.py.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from config import Config
from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.user_data import load_user_data

from ..dependencies import require_min_access_level
from ..schemas.admin import UserEntry, UsersResponse

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.admin")


@router.get("/users", response_model=UsersResponse)
def get_users() -> UsersResponse:
    config = Config()
    user_data = load_user_data(Path(config.DATA_DIR) / "user_data.json", logger=_logger)

    users = [
        UserEntry(
            telegram_id=int(telegram_id),
            role=data.get("role", "user"),
            navidrome_user=data.get("navidrome_user"),
            created_at=data.get("created_at"),
        )
        for telegram_id, data in user_data.items()
        if telegram_id.isdigit()
    ]
    users.sort(key=lambda u: u.telegram_id)
    return UsersResponse(users=users)
