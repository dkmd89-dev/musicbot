# control_center/routers/ui.py
# -*- coding: utf-8 -*-
"""
GET / — Dashboard-Seite (Vertical Slice "Health/Dashboard", Schritt 4).

Serverseitig gerendertes HTML (Jinja2) + Vanilla-JS-Polling statt eines
SPA-Frameworks — bewusste Entscheidung, siehe docs/audits/
CONTROL_CENTER_ARCHITECTURE_2026-09-15.md Abschnitt 5 ("Frontend").

Diese Route selbst ist bewusst UNAUTHENTIFIZIERT (reines HTML-Grundgerüst
ohne Library-/Nutzerdaten — GET ohne Seiteneffekte, Master-Prompt Regel 12).
Die eigentlichen Daten (Health-Kacheln, Nutzer-/Login-Status) holt das
Frontend-JS erst client-seitig über die bereits geschützten API-Endpunkte
(GET /api/v1/auth/whoami, GET /api/v1/library/health) — ein 401 dort
schaltet clientseitig auf die Login-Ansicht mit dem Telegram-Login-Widget
um. Kein Business-Logic-Code hier (CLAUDE.md §4) — nur Rendering.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import Config

router = APIRouter(tags=["ui"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    config = Config()
    return _templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "bot_username": config.BOT_USERNAME or None},
    )
