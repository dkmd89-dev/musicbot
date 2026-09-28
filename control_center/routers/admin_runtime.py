# control_center/routers/admin_runtime.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/admin/runtime-snapshot — Bot-Laufzeit-Snapshot read-only
(Web-Paritäts-Entscheidung 1 = E1, 2026-09-28).

Zeigt Fehlerstatistik, letzte (bereinigte) Fehler und Duplikat-
Sitzungszähler des Bot-Prozesses mit sichtbarem Datenstand. Keine
Schreibaktion: Zurücksetzen bleibt Telegram-only (E1). Dünner Router,
Fachlogik in services/bot_runtime_snapshot.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from config import Config
from services.access_control import AccessLevel
from services.bot_runtime_snapshot import read_bot_runtime_snapshot

from ..dependencies import require_min_access_level
from ..schemas.runtime_snapshot import RuntimeSnapshotResponse, snapshot_result_to_response

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin-runtime"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)


@router.get("/runtime-snapshot", response_model=RuntimeSnapshotResponse)
def get_runtime_snapshot() -> RuntimeSnapshotResponse:
    return snapshot_result_to_response(read_bot_runtime_snapshot(Config()))
