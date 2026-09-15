# control_center/schemas/errors.py
# -*- coding: utf-8 -*-
"""
Einheitliches Fehlerformat (Master-Prompt Abschnitt 31):

    {"error": {"code": "...", "message": "...", "request_id": "..."}}

Interne Exception-Details werden nie ungefiltert an den Client
weitergegeben — "message" ist immer ein stabiler, generischer Text,
Details landen ausschliesslich im Server-Log (siehe
control_center/routers/health.py und control_center/app.py).
"""

from __future__ import annotations

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None
