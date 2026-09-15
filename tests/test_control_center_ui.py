# tests/test_control_center_ui.py
# -*- coding: utf-8 -*-
"""
GET / — Dashboard-Seite, Vertical Slice "Health/Dashboard", Schritt 4.

Testet den echten Produktionscode-Pfad: control_center/routers/ui.py
rendert das reale Template control_center/templates/dashboard.html über
die echte Jinja2Templates-Instanz — kein im Testfile nachgebautes HTML.

Diese Route ist bewusst unauthentifiziert (siehe Router-Docstring) — die
Tests prüfen entsprechend, dass GET / ohne jede Session/Dev-Bypass
funktioniert (anders als die Endpunkte in test_control_center_health_api.py/
test_control_center_findings_api.py).
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from config import Config


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_dashboard_renders_without_any_authentication(client):
    """GET / ist bewusst oeffentlich (nur HTML-Grundgeruest, keine
    Library-/Nutzerdaten) - kein Cookie, kein Dev-Bypass noetig."""
    response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "MusicBot Control Center" in response.text


@pytest.mark.asyncio
async def test_dashboard_contains_all_view_states(client):
    response = await client.get("/")
    html = response.text

    assert 'id="loading-view"' in html
    assert 'id="login-view"' in html
    assert 'id="dashboard-view"' in html
    assert 'id="error-view"' in html


@pytest.mark.asyncio
async def test_dashboard_fetches_real_api_endpoints_from_js(client):
    """Stellt sicher, dass das Template tatsaechlich gegen die echten,
    bereits implementierten Endpunkte spricht (kein Tippfehler/Drift)."""
    html = (await client.get("/")).text

    assert "/api/v1/auth/whoami" in html
    assert "/api/v1/library/health" in html
    assert "/api/v1/auth/telegram-callback" in html
    assert "/api/v1/library/findings" in html
    assert "/api/v1/library/repair-plan" in html
    assert "/api/v1/downloads/history" in html
    assert "/api/v1/statistics/me" in html


@pytest.mark.asyncio
async def test_dashboard_contains_all_new_section_panels(client):
    """Findings/Repair-Plan/Downloads/Statistics-Erweiterung (Nachtrag zu
    Schritt 4) - jeder Bereich braucht sein eigenes Content-Element, in
    das das Client-JS rendert."""
    html = (await client.get("/")).text

    assert 'id="findings-content"' in html
    assert 'id="repair-plan-content"' in html
    assert 'id="downloads-content"' in html
    assert 'id="statistics-content"' in html


@pytest.mark.asyncio
async def test_dashboard_repair_plan_has_dedicated_manual_trigger(client):
    """Repair-Plan ist bewusst NICHT im 30s-Polling (voller Library-Scan)
    - es muss einen eigenen manuellen Button geben, keinen impliziten
    Auto-Load beim Seitenaufruf."""
    html = (await client.get("/")).text

    assert 'id="repair-plan-btn"' in html


@pytest.mark.asyncio
async def test_dashboard_shows_telegram_widget_when_bot_username_configured(client, monkeypatch):
    monkeypatch.setattr(Config, "BOT_USERNAME", property(lambda self: "MeinTestBot"))

    html = (await client.get("/")).text

    assert 'data-telegram-login="MeinTestBot"' in html
    assert "telegram-widget.js" in html
    assert "CONTROL_CENTER_DEV_AUTH_BYPASS" not in html


@pytest.mark.asyncio
async def test_dashboard_shows_config_hint_when_bot_username_missing(client, monkeypatch):
    monkeypatch.setattr(Config, "BOT_USERNAME", property(lambda self: ""))

    html = (await client.get("/")).text

    assert "telegram-widget.js" not in html
    assert "CONTROL_CENTER_DEV_AUTH_BYPASS" in html
