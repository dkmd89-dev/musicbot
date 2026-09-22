# control_center/schemas/system_status.py
# -*- coding: utf-8 -*-
"""Response-Schema für GET /api/v1/admin/system/status."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class SystemStatusResponse(BaseModel):
    cpu_percent: float
    cpu_count: int
    memory_percent: float
    memory_used_mb: float
    memory_total_mb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    bot_service_name: str
    bot_service_active: Optional[bool] = None
