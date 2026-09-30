# control_center/routers/mapping_status.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/admin/mappings/status — "gespeichert" vs. "vom Bot angewendet".

Read-only (ADMIN). Vergleicht den aktuellen Datei-Stand der bearbeitbaren
Mapping-Dateien mit den Hashes, die der Bot im Laufzeit-Snapshot meldet
(services/mapping_runtime_state.py). Muss VOR dem Router mit `/{mapping_id}`
registriert werden, sonst würde "status" als Mapping-ID gelesen.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from config import Config
from services.access_control import AccessLevel
from services.bot_runtime_snapshot import read_bot_runtime_snapshot
from services.mapping_runtime_state import evaluate

from ..dependencies import require_min_access_level
from ..schemas.mapping_status import MappingStatusResponse, evaluation_to_response
from .mapping_admin import _mapping_dir

router = APIRouter(
    prefix="/api/v1/admin/mappings",
    tags=["mapping-status"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)


@router.get("/status", response_model=MappingStatusResponse)
def get_mapping_status() -> MappingStatusResponse:
    return evaluation_to_response(evaluate(_mapping_dir(), read_bot_runtime_snapshot(Config())))
