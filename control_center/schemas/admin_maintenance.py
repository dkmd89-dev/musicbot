# control_center/schemas/admin_maintenance.py
# -*- coding: utf-8 -*-
"""
Request-Schemas für POST /api/v1/admin/maintenance/artist-rename/execute
und POST /api/v1/admin/maintenance/title-edit/execute — die beiden
Aktionen mit manuellem Freitext-Zielwert (Preview-Endpunkte nutzen
stattdessen Query-Parameter, siehe control_center/routers/
admin_maintenance.py, identisches Muster wie AcceptFindingRequest in
schemas/findings.py).
"""

from __future__ import annotations

from pydantic import BaseModel


class ArtistRenameRequest(BaseModel):
    artist: str
    new_artist: str


class TitleEditRequest(BaseModel):
    artist: str
    rel_path: str
    new_title: str
