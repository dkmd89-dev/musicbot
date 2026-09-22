# control_center/routers/ui.py
# -*- coding: utf-8 -*-
"""
Seiten-Routen (Jinja2, serverseitig gerendert) — ui_prompt.txt Phase 1
"UI STRUCTURE REDESIGN".

Ersetzt das vorherige Einzel-Dashboard (control_center/templates/
dashboard.html, ~1100 Zeilen, alle Panels auf einer Seite) durch eine
Mehrseiten-Struktur mit gemeinsamer Sidebar/Header-Navigation
(control_center/templates/_base.html) — reine Reorganisation
bestehender Funktionalität (jedes Panel/jede JS-Funktion unverändert auf
seine neue Seite verschoben), keine neue Business-Logik, kein neues
Frontend-Framework (weiterhin Jinja2 + Vanilla JS + CSS, Master-Prompt
Abschnitt 7).

Jede Route hier ist bewusst UNAUTHENTIFIZIERT (reines HTML-Grundgerüst
ohne Library-/Nutzerdaten — GET ohne Seiteneffekte, identisches Prinzip
wie die bisherige "/"-Route). Die eigentlichen Daten holt jede Seite
client-seitig über die bereits geschützten API-Endpunkte (GET
/api/v1/auth/whoami zuerst — ein 401 dort schaltet clientseitig auf die
Login-Ansicht um, siehe static/common.js::checkAuth()).

"/logs" ist die einzige Seite ohne direktes Vorbild im vorherigen
Einzel-Dashboard und zeigt ehrlich "Noch nicht implementiert" statt eine
nicht vorhandene Funktion vorzutäuschen (Master-Prompt Regel 38).

"/findings", "/repairs" und "/jobs" existierten als eigene Seiten (siehe
docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md), wurden aber im
Zuge von api_health.md ("Sidebar enthält genau einen 🩺 Health
Menüpunkt") vollständig in "/health" konsolidiert (control_center/
templates/health.html + static/pages/health.js) — ihre APIs
(routers/findings.py, routers/repair.py, routers/jobs.py) blieben dabei
unveraendert, nur die drei Seiten-Routen und -Templates entfielen.
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


def _render(request: Request, template_name: str, page_id: str) -> HTMLResponse:
    config = Config()
    return _templates.TemplateResponse(
        template_name,
        {
            "request": request,
            "bot_username": config.BOT_USERNAME or None,
            "page_id": page_id,
            # Subpath-Betrieb hinter nginx (siehe control_center/root_path.py):
            # "" im Direktbetrieb, sonst z. B. "/controlcenter".
            "base_path": request.scope.get("root_path", ""),
        },
    )


@router.get("/", response_class=HTMLResponse)
def overview(request: Request) -> HTMLResponse:
    return _render(request, "overview.html", "overview")


@router.get("/downloads", response_class=HTMLResponse)
def downloads_page(request: Request) -> HTMLResponse:
    return _render(request, "downloads.html", "downloads")


@router.get("/library", response_class=HTMLResponse)
def library_page(request: Request) -> HTMLResponse:
    return _render(request, "library.html", "library")


@router.get("/library/{artist}", response_class=HTMLResponse)
def library_artist_detail_page(request: Request, artist: str) -> HTMLResponse:
    """Artist-Detail (Library Artist-Centric UX, CC-AC-1) — `artist` wird
    hier bewusst NICHT serverseitig aufgeloest/validiert (dieselbe
    Trennung wie alle anderen Seiten-Routen: unauthentifiziertes HTML-
    Grundgerüst, die eigentlichen Daten inkl. 404-Behandlung holt die
    Seite client-seitig über GET /api/v1/library/artists-overview/{artist}
    — „unbekannter Artist" bleibt dadurch ein sauberer API-Fehler statt
    eines Server-Renderfehlers). `page_id="library"` hält den
    Sidebar-Eintrag „📚 Library" aktiv markiert, identisches Prinzip wie
    Unterseiten in anderen Bereichen dieses Control Centers."""
    return _render(request, "library_artist_detail.html", "library")


@router.get("/metadata", response_class=HTMLResponse)
def metadata_page(request: Request) -> HTMLResponse:
    return _render(request, "metadata.html", "metadata")


@router.get("/statistics", response_class=HTMLResponse)
def statistics_page(request: Request) -> HTMLResponse:
    return _render(request, "statistics.html", "statistics")


@router.get("/health", response_class=HTMLResponse)
def health_page(request: Request) -> HTMLResponse:
    return _render(request, "health.html", "health")


@router.get("/navidrome", response_class=HTMLResponse)
def navidrome_page(request: Request) -> HTMLResponse:
    return _render(request, "navidrome.html", "navidrome")


@router.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request) -> HTMLResponse:
    return _render(request, "logs.html", "logs")


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request) -> HTMLResponse:
    return _render(request, "admin.html", "admin")
