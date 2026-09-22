# control_center/schemas/admin_operations.py
# -*- coding: utf-8 -*-
"""
Schemas für CC-AC-10C (Bot & Operations): Backup, Wartungsmodus,
Bot-Neustart.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class BackupEntryResponse(BaseModel):
    name: str
    size: int
    created_at: str


class BackupListResponse(BaseModel):
    backups: list[BackupEntryResponse]
    max_keep: int


class CreateBackupRequest(BaseModel):
    backup_type: Literal["bot", "library"]


class DeleteBackupResponse(BaseModel):
    name: str
    deleted: bool


class MaintenanceStatusResponse(BaseModel):
    active: bool
    changed_at: Optional[str] = None
    changed_by_user_id: Optional[int] = None


class SetMaintenanceRequest(BaseModel):
    active: bool


class RestartResponse(BaseModel):
    message: str
