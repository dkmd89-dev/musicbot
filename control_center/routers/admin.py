# control_center/routers/admin.py
# -*- coding: utf-8 -*-
"""
/api/v1/admin/users — Nutzer-/Rollenverwaltung.

GET ist reine Orchestrierung: liest ausschliesslich die bestehende,
persistente data/user_data.json ueber services/user_data.py::
load_user_data() (dieselbe Common-Core-Extraktion, die auch
control_center/dependencies.py fuer die MODERATOR-Aufloesung nutzt) —
kein Schreibzugriff (Master-Prompt Regel 12: GET ohne Seiteneffekte).

CC-AC-10B (User Management Write-Parität, freigegebene CC-AC-10.md):
POST/PATCH/DELETE rufen services/user_admin.py auf — denselben
Telegram-freien Application-Layer, den handlers/admin/
user_management_handler.py in einer künftigen Phase (CC-AC-10G laut
CC-AC-10.md §20) ebenfalls nutzen könnte, bewusst in diesem Slice noch
NICHT migriert (Telegram bleibt unverändert, kein Risiko für dessen
Characterization-Tests). Dieselbe SEC-005-Owner-Guard-Logik wie die
Telegram-Seite (nur config.OWNER_USER_ID darf die Owner-Rolle vergeben).

Authentifiziert mit mindestens AccessLevel.ADMIN — Rollen-/Navidrome-
Zuordnung anderer Nutzer ist eindeutig Administrationsdaten, identische
Schwelle wie routers/findings.py/repair.py/downloads.py. Schreibende
Endpunkte sind zusaetzlich per verify_same_origin() CSRF-geschuetzt
(identisches Muster wie routers/admin_maintenance.py).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from config import Config
from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services import user_admin
from services.user_data import load_user_data, save_user_data

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.admin import (
    CreateUserRequest,
    DeleteUserResponse,
    UpdateNavidromeRequest,
    UpdatePermissionsRequest,
    UpdateRoleRequest,
    UserDetailResponse,
    UserEntry,
    UsersResponse,
)
from ..schemas.errors import ErrorDetail

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.admin")


def _user_data_path(config: Config) -> Path:
    return Path(config.DATA_DIR) / "user_data.json"


def _detail_response(telegram_id: str, entry: dict) -> UserDetailResponse:
    return UserDetailResponse(
        telegram_id=int(telegram_id),
        role=entry.get("role", "user"),
        navidrome_user=entry.get("navidrome_user"),
        created_at=entry.get("created_at"),
        permissions=entry.get("permissions", []),
    )


def _not_found(e: user_admin.UserNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=404, detail=ErrorDetail(code="USER_NOT_FOUND", message=str(e)).model_dump()
    )


def _conflict(e: user_admin.UserAlreadyExistsError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=ErrorDetail(code="USER_ALREADY_EXISTS", message=str(e)).model_dump(),
    )


def _validation_error(e: user_admin.UserAdminError) -> HTTPException:
    return HTTPException(
        status_code=422, detail=ErrorDetail(code="USER_VALIDATION_ERROR", message=str(e)).model_dump()
    )


def _forbidden(e: user_admin.OwnerPromotionDeniedError) -> HTTPException:
    return HTTPException(
        status_code=403, detail=ErrorDetail(code="OWNER_PROMOTION_DENIED", message=str(e)).model_dump()
    )


def _save_or_500(config: Config, users: dict) -> None:
    if not save_user_data(users, _user_data_path(config), logger=_logger):
        raise HTTPException(
            status_code=500,
            detail=ErrorDetail(
                code="USER_DATA_WRITE_FAILED", message="Benutzerdaten konnten nicht gespeichert werden."
            ).model_dump(),
        )


@router.get("/users", response_model=UsersResponse)
def get_users() -> UsersResponse:
    config = Config()
    user_data = load_user_data(_user_data_path(config), logger=_logger)

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


@router.post(
    "/users",
    response_model=UserDetailResponse,
    status_code=201,
    dependencies=[Depends(verify_same_origin)],
)
def post_create_user(payload: CreateUserRequest) -> UserDetailResponse:
    config = Config()
    users = load_user_data(_user_data_path(config), logger=_logger)
    telegram_id = str(payload.telegram_id)

    try:
        entry = user_admin.create_user(users, telegram_id, payload.navidrome_user)
    except user_admin.UserAlreadyExistsError as e:
        raise _conflict(e) from e
    except user_admin.UserAdminError as e:
        raise _validation_error(e) from e

    _save_or_500(config, users)
    _logger.info(f"✅ [control_center] Benutzer {telegram_id} angelegt")
    return _detail_response(telegram_id, entry)


@router.patch(
    "/users/{telegram_id}/navidrome",
    response_model=UserDetailResponse,
    dependencies=[Depends(verify_same_origin)],
)
def patch_navidrome_user(telegram_id: str, payload: UpdateNavidromeRequest) -> UserDetailResponse:
    config = Config()
    users = load_user_data(_user_data_path(config), logger=_logger)

    try:
        entry = user_admin.update_navidrome_user(users, telegram_id, payload.navidrome_user)
    except user_admin.UserNotFoundError as e:
        raise _not_found(e) from e
    except user_admin.UserAdminError as e:
        raise _validation_error(e) from e

    _save_or_500(config, users)
    _logger.info(f"✅ [control_center] Navidrome-User für {telegram_id} aktualisiert")
    return _detail_response(telegram_id, entry)


@router.patch(
    "/users/{telegram_id}/role",
    response_model=UserDetailResponse,
    dependencies=[Depends(verify_same_origin)],
)
def patch_user_role(
    telegram_id: str, payload: UpdateRoleRequest, acting_user_id: int = Depends(get_current_user_id)
) -> UserDetailResponse:
    config = Config()
    users = load_user_data(_user_data_path(config), logger=_logger)

    try:
        entry = user_admin.set_user_role(
            users,
            telegram_id,
            payload.role,
            acting_user_id=acting_user_id,
            owner_user_id=getattr(config, "OWNER_USER_ID", None),
        )
    except user_admin.OwnerPromotionDeniedError as e:
        _logger.warning(
            f"🚫 [control_center] Nicht-Owner {acting_user_id} versuchte, "
            f"User {telegram_id} zum Owner zu befördern - abgelehnt"
        )
        raise _forbidden(e) from e
    except user_admin.InvalidRoleError as e:
        raise _validation_error(e) from e
    except user_admin.UserNotFoundError as e:
        raise _not_found(e) from e

    _save_or_500(config, users)
    _logger.info(f"✅ [control_center] Rolle für {telegram_id} geändert: {payload.role}")
    return _detail_response(telegram_id, entry)


@router.patch(
    "/users/{telegram_id}/permissions",
    response_model=UserDetailResponse,
    dependencies=[Depends(verify_same_origin)],
)
def patch_user_permissions(telegram_id: str, payload: UpdatePermissionsRequest) -> UserDetailResponse:
    config = Config()
    users = load_user_data(_user_data_path(config), logger=_logger)

    try:
        entry = user_admin.set_user_permissions(users, telegram_id, payload.permissions)
    except user_admin.UserNotFoundError as e:
        raise _not_found(e) from e
    except user_admin.InvalidPermissionError as e:
        raise _validation_error(e) from e

    _save_or_500(config, users)
    _logger.info(f"✅ [control_center] Berechtigungen für {telegram_id} aktualisiert")
    return _detail_response(telegram_id, entry)


@router.delete(
    "/users/{telegram_id}",
    response_model=DeleteUserResponse,
    dependencies=[Depends(verify_same_origin)],
)
def delete_user(telegram_id: str) -> DeleteUserResponse:
    config = Config()
    users = load_user_data(_user_data_path(config), logger=_logger)

    try:
        removed = user_admin.delete_user(users, telegram_id)
    except user_admin.UserNotFoundError as e:
        raise _not_found(e) from e

    _save_or_500(config, users)
    _logger.info(f"🗑️ [control_center] Benutzer {telegram_id} gelöscht")
    return DeleteUserResponse(telegram_id=int(telegram_id), role=removed.get("role", "user"))
