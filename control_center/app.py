# control_center/app.py
# -*- coding: utf-8 -*-
"""
FastAPI-App-Factory fuer das MusicBot Control Center.

create_app() baut die App und registriert alle Router — kein Modul-Level-
Zustand ausser der App-Instanz selbst, damit Tests bei Bedarf eine frische
Instanz erzeugen koennen.

Start (lokale Entwicklung, siehe
docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md Abschnitt 7
"Deployment" — eigener Prozess neben bot.py, nur 127.0.0.1):

    uvicorn control_center.app:app --host 127.0.0.1 --port 8420
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from logger import get_module_logger

from .routers import health
from .schemas.errors import ErrorDetail

_logger = get_module_logger("control_center.app")


def create_app() -> FastAPI:
    app = FastAPI(title="MusicBot Control Center", version="0.1.0")
    app.include_router(health.router)

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        # Vereinheitlicht jede HTTPException auf das Fehlerformat aus
        # Master-Prompt Abschnitt 31 ({"error": {...}}) — Router setzen
        # `detail` bereits als ErrorDetail-Dict (siehe
        # control_center/routers/health.py); ein Fallback deckt
        # FastAPI-interne HTTPExceptions (z.B. Validierungsfehler) ab, die
        # `detail` als reinen String liefern.
        detail = exc.detail
        if not isinstance(detail, dict):
            detail = ErrorDetail(code="HTTP_ERROR", message=str(detail)).model_dump()
        return JSONResponse(status_code=exc.status_code, content={"error": detail})

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Letzte Sicherheitsnetz-Ebene (Master-Prompt Abschnitt 31): Router
        # fangen ihre erwarteten Fehlerfaelle bereits selbst per
        # HTTPException ab — dieser Handler greift nur bei wirklich
        # unerwarteten Bugs und gibt die interne Exception-Message
        # niemals an den Client weiter (nur ins Server-Log).
        request_id = uuid.uuid4().hex
        _logger.error(f"[{request_id}] Unbehandelte Exception: {exc!r}")
        return JSONResponse(
            status_code=500,
            content={
                "error": ErrorDetail(
                    code="INTERNAL_ERROR",
                    message="Ein unerwarteter Fehler ist aufgetreten.",
                    request_id=request_id,
                ).model_dump()
            },
        )

    return app


app = create_app()
