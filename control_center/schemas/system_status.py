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
    # control_center_overview Phase 2: Bot-Service-Uptime + Platform.
    # Semantisch korrekt aus systemctl ActiveEnterTimestamp (NICHT
    # psutil.boot_time), siehe services/system_status.py.
    bot_started_at: Optional[str] = None
    bot_uptime_seconds: Optional[int] = None
    bot_uptime_formatted: Optional[str] = None
    platform_os: Optional[str] = None
    platform_release: Optional[str] = None
    platform_python: Optional[str] = None
    platform_arch: Optional[str] = None
    # control_center_overview Phase 5B: Load Average + Swap
    load_avg_1: Optional[float] = None
    load_avg_5: Optional[float] = None
    load_avg_15: Optional[float] = None
    swap_percent: Optional[float] = None
    swap_used_gb: Optional[float] = None
    swap_total_gb: Optional[float] = None
