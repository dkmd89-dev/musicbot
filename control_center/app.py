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
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from config import Config
from logger import get_module_logger, set_process_role, setup_enhanced_logging

from services.jobs.job_registry import JobRegistry
from services.logger_admin import LoggerApplyRateLimiter

from .routers import (
    admin,
    admin_duplicates,
    admin_maintenance,
    admin_operations,
    admin_runtime,
    auth,
    downloads,
    findings,
    health,
    jobs,
    library_overview,
    logger,
    logs,
    metadata,
    metadata_actions,
    navidrome,
    repair,
    statistics,
    ui,
)
from .root_path import ForwardedPrefixMiddleware
from .schemas.errors import ErrorDetail

_logger = get_module_logger("control_center.app")

# D.12a: eigene Log-Datei des CC-Prozesses - bewusst NICHT bot.log, damit
# nicht zwei Prozesse (bot.py + control-center.service) dieselbe
# RotatingFileHandler-Datei rotieren. services/logs/reader.py findet sie
# automatisch ueber LOG_DIR/*.log*.
CONTROL_CENTER_LOG_FILENAME = "control_center.log"


def setup_control_center_logging(config: Config | None = None) -> None:
    """Initialisiert das Logging des CC-Prozesses mit dem bestehenden
    setup_enhanced_logging() (identische Parameter wie bot.py, nur eigene
    Datei). Vorher hatte der CC-Prozess keinen Root-Handler: INFO/DEBUG
    aller get_module_logger()-Logger (YoutubeDownloader, pipeline_core,
    JobRegistry, ...) gingen verloren, WARNING+ landete nur ueber
    logging.lastResort auf stderr.

    Wird ausschliesslich aus dem Startup-Event aufgerufen (siehe
    create_app()): setup_enhanced_logging() entfernt alle Root-Handler -
    Tests via httpx.ASGITransport loesen kein Lifespan-Event aus und
    bleiben dadurch unberuehrt (caplog o. Ae.)."""
    # D.12b.1: Rolle setzen, BEVOR der erste EnhancedMetadataProcessor
    # (Singleton) konstruiert wird - siehe download_utils.py:277.
    set_process_role("control_center")
    config = config or Config()
    log_file = Path(config.LOG_DIR) / CONTROL_CENTER_LOG_FILENAME
    setup_enhanced_logging(
        log_file=str(log_file),
        level=getattr(config, "LOG_LEVEL", "INFO"),
        use_colors=True,
        use_emojis=True,
    )
    _logger.info(f"✅ Control-Center-Logging eingerichtet: {log_file}")


def create_app() -> FastAPI:
    app = FastAPI(title="MusicBot Control Center", version="0.1.0")
    # EINE JobRegistry-Instanz pro App/Prozess (siehe routers/jobs.py-
    # Docstring) - ueber app.state statt Modul-Level-Global, damit jeder
    # frische create_app()-Aufruf (wie in allen Tests) automatisch eine
    # isolierte Registry bekommt.
    app.state.job_registry = JobRegistry()

    # CC-LOGGER-L5.3: Rate-Limit + Single-Flight fuer /logger/apply.
    # Pro App-Instanz (create_app()-Aufruf) isoliert, damit Tests
    # keinen geteilten Zustand sehen. Kein Modul-Level-Singleton.
    app.state.logger_apply_limiter = LoggerApplyRateLimiter(min_interval_seconds=60.0)

    # D.12a: Logging erst beim Startup (nur unter uvicorn), nicht beim
    # Import/create_app() - siehe setup_control_center_logging().
    app.add_event_handler("startup", setup_control_center_logging)

    # Subpath-Betrieb hinter nginx (X-Forwarded-Prefix -> scope["root_path"],
    # siehe control_center/root_path.py) - ohne Header wirkungslos.
    app.add_middleware(ForwardedPrefixMiddleware)
    app.include_router(health.router)
    app.include_router(findings.router)
    app.include_router(repair.router)
    app.include_router(metadata.router)
    app.include_router(metadata_actions.router)
    app.include_router(library_overview.router)
    app.include_router(downloads.router)
    app.include_router(statistics.router)
    app.include_router(navidrome.router)
    app.include_router(admin.router)
    app.include_router(admin_maintenance.router)
    app.include_router(admin_duplicates.router)
    app.include_router(admin_operations.router)
    app.include_router(admin_runtime.router)
    app.include_router(jobs.router)
    app.include_router(jobs.user_router)
    app.include_router(logs.router)
    app.include_router(logger.router)
    app.include_router(auth.router)
    app.include_router(ui.router)

    # Gemeinsame CSS/JS fuer die Mehrseiten-Navigation (ui_prompt.txt
    # Phase 1) - statische Dateien, kein Build-Schritt, weiterhin
    # Vanilla JS/CSS (Master-Prompt Abschnitt 7).
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

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
        # Header einer HTTPException durchreichen (z.B. Retry-After bei
        # 429). FastAPI/Starlette setzt sie normalerweise am Response —
        # ein eigener Exception-Handler umgeht das, deshalb hier explizit.
        # None ist der Default (nichts zu setzen), leere Dicts behandeln
        # wir als "nichts".
        headers = exc.headers if getattr(exc, "headers", None) else None
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": detail},
            headers=headers,
        )

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
