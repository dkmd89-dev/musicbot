# control_center/routers/admin_operations.py
# -*- coding: utf-8 -*-
"""
CC-AC-10C (Bot & Operations) — Backup, Wartungsmodus, Bot-Neustart.
CC-AC-10D (Diagnostics & Monitoring, Teilbereich System-Status) —
GET /system/status: reine Host-Ressourcenmetriken + echter Bot-Service-
Check über services/system_status.py (siehe dortiger Docstring, warum
NICHT die Bot-eigenen Laufzeitzähler aus SystemMonitor mitgeliefert
werden — Cross-Prozess-Problem, analog zur Nutzer-Entscheidung, Logger-
Konfiguration und Error-Administration komplett aus CC-AC-10D
zurückzustellen).

Backup ruft services/backup_admin.py auf (neuer, Telegram-freier
Application-Layer, siehe dortiger Docstring — eigenständige
Implementierung statt Import aus handlers/admin/backup_handler.py, da
control_center/ laut CLAUDE.md §4 keine Fachlogik aus Telegram-
gekoppelten handlers/-Modulen importieren darf, nur aus services/ bzw.
der bereits Telegram-freien Auth-Logik in handlers/menu/permissions.py).
Backup-Erstellung läuft als asynchroner Job (services/jobs/job_registry.py,
identisches Muster wie routers/jobs.py) — gemessene Dauer ~9,5s+
(CC-AC-10A-Audit), blockierendes tarfile-I/O läuft über
loop.run_in_executor(), identisch zur Telegram-Seite (BackupHandler nutzt
denselben Executor-Ansatz für _create_archive(), INV-01).

Wartungsmodus nutzt services/bot_maintenance.py::MaintenanceModeStore
**direkt** — bereits vollständig Telegram-frei, keine neue
Application-Layer-Datei nötig (CC-AC-10.md §24: "Suche zuerst nach
vorhandener Logik"). State-Datei-Pfad wird wie bei services/user_data.py
über config.DATA_DIR aufgelöst (Test-Isolation), nicht über den in
services/bot_maintenance.py dokumentierten Hardcoded-Default — beide
Pfade sind in Produktion identisch (Config.DATA_DIR = BASE_DIR / "data").

Bot-Neustart nutzt utils/bot_restart_trigger.py::BotRestartTrigger
**direkt** — ebenfalls bereits Telegram-frei, keine eigene
Fachlogik/Validierung über die Auth-Prüfung hinaus (identisches Timing-
Muster wie handlers/admin/bot_restart_handler.py: Response zuerst,
`call_later()`-Verzögerung, damit die HTTP-Response noch zugestellt
werden kann, bevor systemctl den Prozess beendet).

**Nutzer-Entscheidung (2026-09-22, docs/FINDINGS_INDEX.md):**
Bot-Neustart wird bewusst web-fähig gemacht (entgegen der ursprünglichen
09-15-Einschätzung) — mit denselben Schutzmechanismen wie die Telegram-
Seite (ADMIN-Auth) plus CSRF, ohne zusätzliche Preview/Confirm-Stufe
(das Web-UI selbst zeigt bei Bedarf einen eigenen Bestätigungsdialog,
identisch zum bestehenden Telegram-Bestätigungsdialog — Serverseite
verlangt keine zweite Anfrage).

Authentifiziert mit mindestens AccessLevel.ADMIN. Schreibende Endpunkte
zusätzlich über verify_same_origin() CSRF-geschützt.
"""

from __future__ import annotations

import asyncio
import functools
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from config import Config
from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services import backup_admin, system_status
from services.bot_maintenance import MaintenanceModeStore
from services.jobs.job_registry import JobRegistry
from utils.bot_restart_trigger import BotRestartTrigger

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.admin_operations import (
    BackupEntryResponse,
    BackupListResponse,
    CreateBackupRequest,
    DeleteBackupResponse,
    MaintenanceStatusResponse,
    RestartResponse,
    SetMaintenanceRequest,
)
from ..schemas.errors import ErrorDetail
from ..schemas.jobs import JobSchema, job_to_schema
from ..schemas.system_status import SystemStatusResponse

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin-operations"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.admin_operations")

_RESTART_SERVICE_NAME = "bot"
_PRE_RESTART_DELAY_SECONDS = 2.0


def _get_job_registry(request: Request) -> JobRegistry:
    return request.app.state.job_registry


def _maintenance_store() -> MaintenanceModeStore:
    config = Config()
    return MaintenanceModeStore(state_file=str(Path(config.DATA_DIR) / "maintenance_mode.json"))


def _maintenance_status_response(store: MaintenanceModeStore) -> MaintenanceStatusResponse:
    state = store.get_state()
    return MaintenanceStatusResponse(
        active=state.active, changed_at=state.changed_at, changed_by_user_id=state.changed_by_user_id,
    )


# ── System-Status ────────────────────────────────────────────────────────


@router.get("/system/status", response_model=SystemStatusResponse)
def get_system_status() -> SystemStatusResponse:
    config = Config()
    resources = system_status.get_host_resources(str(config.BASE_DIR))
    active = system_status.get_bot_service_active(_RESTART_SERVICE_NAME)
    platform_info = system_status.get_platform_info()
    uptime = system_status.get_bot_service_uptime(_RESTART_SERVICE_NAME)
    return SystemStatusResponse(
        cpu_percent=resources.cpu_percent,
        cpu_count=resources.cpu_count,
        memory_percent=resources.memory_percent,
        memory_used_mb=resources.memory_used_mb,
        memory_total_mb=resources.memory_total_mb,
        disk_percent=resources.disk_percent,
        disk_used_gb=resources.disk_used_gb,
        disk_total_gb=resources.disk_total_gb,
        bot_service_name=_RESTART_SERVICE_NAME,
        bot_service_active=active,
        bot_started_at=uptime["bot_started_at"],
        bot_uptime_seconds=uptime["bot_uptime_seconds"],
        bot_uptime_formatted=uptime["bot_uptime_formatted"],
        platform_os=platform_info["platform_os"],
        platform_release=platform_info["platform_release"],
        platform_python=platform_info["platform_python"],
        platform_arch=platform_info["platform_arch"],
        load_avg_1=resources.load_avg_1,
        load_avg_5=resources.load_avg_5,
        load_avg_15=resources.load_avg_15,
        swap_percent=resources.swap_percent,
        swap_used_gb=resources.swap_used_gb,
        swap_total_gb=resources.swap_total_gb,
    )


# ── Backup ───────────────────────────────────────────────────────────────


@router.get("/backups", response_model=BackupListResponse)
def get_backups(backup_type: str = Query(...)) -> BackupListResponse:
    if backup_type not in backup_admin.BACKUP_TYPES:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(
                code="INVALID_BACKUP_TYPE", message=f"Unbekannter Backup-Typ: {backup_type}"
            ).model_dump(),
        )

    paths = backup_admin.BackupPaths.from_config(Config())
    entries = backup_admin.list_backups(paths, backup_type)
    return BackupListResponse(
        backups=[
            BackupEntryResponse(name=e.name, size=e.size, created_at=e.created_at.isoformat())
            for e in entries
        ],
        max_keep=paths.max_keep,
    )


async def _run_backup_job(registry: JobRegistry, job_id: str, backup_type: str) -> None:
    registry.mark_running(job_id)
    try:
        paths = backup_admin.BackupPaths.from_config(Config())
        loop = asyncio.get_event_loop()
        entry = await loop.run_in_executor(
            None, functools.partial(backup_admin.create_backup, paths, backup_type, logger=_logger),
        )
        registry.mark_succeeded(
            job_id,
            result={
                "name": entry.name, "size": entry.size, "created_at": entry.created_at.isoformat(),
            },
        )
        _logger.info(f"✅ [control_center] {backup_type}-Backup erstellt: {entry.name}")
    except Exception as e:  # noqa: BLE001
        _logger.error(f"❌ [control_center] {backup_type}-Backup fehlgeschlagen: {e!r}")
        registry.mark_failed(job_id, f"Backup fehlgeschlagen: {e}")


@router.post(
    "/backups",
    response_model=JobSchema,
    dependencies=[Depends(verify_same_origin)],
)
async def post_create_backup(
    payload: CreateBackupRequest,
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(_get_job_registry),
) -> JobSchema:
    job = registry.create(kind=f"backup_{payload.backup_type}", initiator=str(user_id))
    asyncio.create_task(_run_backup_job(registry, job.job_id, payload.backup_type))
    return job_to_schema(job)


@router.delete(
    "/backups/{filename}",
    response_model=DeleteBackupResponse,
    dependencies=[Depends(verify_same_origin)],
)
def delete_backup(filename: str) -> DeleteBackupResponse:
    paths = backup_admin.BackupPaths.from_config(Config())
    try:
        deleted_name = backup_admin.delete_backup(paths, filename)
    except backup_admin.InvalidBackupFilenameError as e:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(code="INVALID_BACKUP_FILENAME", message=str(e)).model_dump(),
        ) from e
    except backup_admin.BackupNotFoundError as e:
        raise HTTPException(
            status_code=404, detail=ErrorDetail(code="BACKUP_NOT_FOUND", message=str(e)).model_dump(),
        ) from e

    _logger.info(f"🗑️ [control_center] Backup gelöscht: {deleted_name}")
    return DeleteBackupResponse(name=deleted_name, deleted=True)


# ── Wartungsmodus ────────────────────────────────────────────────────────


@router.get("/maintenance", response_model=MaintenanceStatusResponse)
def get_maintenance_status() -> MaintenanceStatusResponse:
    return _maintenance_status_response(_maintenance_store())


@router.post(
    "/maintenance",
    response_model=MaintenanceStatusResponse,
    dependencies=[Depends(verify_same_origin)],
)
def post_set_maintenance(
    payload: SetMaintenanceRequest, user_id: int = Depends(get_current_user_id),
) -> MaintenanceStatusResponse:
    store = _maintenance_store()
    store.set_active(payload.active, changed_by_user_id=user_id)
    _logger.info(
        f"🛠️ [control_center] Wartungsmodus {'aktiviert' if payload.active else 'deaktiviert'} "
        f"von User {user_id}"
    )
    return _maintenance_status_response(store)


# ── Bot-Neustart ─────────────────────────────────────────────────────────


@router.post(
    "/system/restart",
    response_model=RestartResponse,
    dependencies=[Depends(verify_same_origin)],
)
async def post_restart(user_id: int = Depends(get_current_user_id)) -> RestartResponse:
    _logger.warning(f"🔄 [control_center] Bot-Neustart angefordert von Admin User-ID {user_id}")
    asyncio.get_running_loop().call_later(
        _PRE_RESTART_DELAY_SECONDS, BotRestartTrigger.trigger_restart, _RESTART_SERVICE_NAME,
    )
    return RestartResponse(message="Neustart wird in Kürze ausgeführt.")
