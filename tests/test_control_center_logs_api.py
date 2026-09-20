# tests/test_control_center_logs_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/logs — Master-Prompt Abschnitt 12 "LOGS & DIAGNOSTICS".

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router ruft services/logs/reader.py::read_logs() unverändert auf, gegen
eine isolierte temporäre Logdatei (Config.LOG_FILE gepatcht) — nie
gegen die echte Produktions-Logdatei.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from config import Config


def _line(time: str, component: str, message: str) -> str:
    return f"{time} ℹ️ [{component}] {message}"


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    """Dieses Testfile prueft die Logs-Fachlogik, nicht die
    Authentifizierung (dafuer: tests/test_control_center_auth.py)."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    path = tmp_path / "bot.log"
    monkeypatch.setattr(Config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(Config, "LOG_FILE", path)
    return path


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
async def test_get_logs_returns_parsed_entries(client, log_file):
    log_file.write_text(_line("10:00:00", "MAIN", "Testnachricht") + "\n", encoding="utf-8")

    response = await client.get("/api/v1/logs")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "bot.log"
    assert body["total_matched"] == 1
    entry = body["entries"][0]
    assert entry["time"] == "10:00:00"
    assert entry["level"] == "INFO"
    assert entry["component"] == "MAIN"
    assert entry["message"] == "Testnachricht"


@pytest.mark.asyncio
async def test_get_logs_empty_when_no_log_file_exists(client, log_file):
    response = await client.get("/api/v1/logs")

    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []
    assert body["available_sources"] == []


@pytest.mark.asyncio
async def test_get_logs_filters_by_level(client, log_file):
    log_file.write_text(
        "10:00:00 ℹ️ [MAIN] info-zeile\n10:00:01 ❌ [MAIN] error-zeile\n", encoding="utf-8"
    )

    response = await client.get("/api/v1/logs", params={"level": "ERROR"})

    body = response.json()
    assert body["total_matched"] == 1
    assert body["entries"][0]["message"] == "error-zeile"


@pytest.mark.asyncio
async def test_get_logs_filters_by_component(client, log_file):
    log_file.write_text(
        _line("10:00:00", "DOWNLOADHANDLER", "a") + "\n" + _line("10:00:01", "TELEGRAM_BOT", "b") + "\n",
        encoding="utf-8",
    )

    response = await client.get("/api/v1/logs", params={"component": "TELEGRAM_BOT"})

    body = response.json()
    assert body["total_matched"] == 1
    assert body["entries"][0]["message"] == "b"


@pytest.mark.asyncio
async def test_get_logs_filters_by_search(client, log_file):
    log_file.write_text(
        _line("10:00:00", "MAIN", "Download gestartet") + "\n" + _line("10:00:01", "MAIN", "etwas anderes") + "\n",
        encoding="utf-8",
    )

    response = await client.get("/api/v1/logs", params={"search": "gestartet"})

    body = response.json()
    assert body["total_matched"] == 1


@pytest.mark.asyncio
async def test_get_logs_respects_limit(client, log_file):
    lines = "\n".join(_line(f"10:00:{i:02d}", "MAIN", f"Nachricht {i}") for i in range(10))
    log_file.write_text(lines + "\n", encoding="utf-8")

    response = await client.get("/api/v1/logs", params={"limit": 3})

    body = response.json()
    assert len(body["entries"]) == 3
    assert body["total_matched"] == 10
    assert body["limit"] == 3


@pytest.mark.asyncio
async def test_get_logs_rejects_invalid_limit(client, log_file):
    response = await client.get("/api/v1/logs", params={"limit": 0})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_logs_lists_available_sources_including_rotated(client, log_file, tmp_path):
    log_file.write_text(_line("10:00:00", "MAIN", "aktuell") + "\n", encoding="utf-8")
    (tmp_path / "bot.log.1").write_text(_line("09:00:00", "MAIN", "rotiert") + "\n", encoding="utf-8")

    response = await client.get("/api/v1/logs")

    body = response.json()
    assert body["available_sources"] == ["bot.log", "bot.log.1"]


@pytest.mark.asyncio
async def test_get_logs_redacts_secrets_end_to_end(client, log_file):
    log_file.write_text(
        _line("10:00:00", "MAIN", "Anfrage mit token=super-secret-value gesendet") + "\n",
        encoding="utf-8",
    )

    response = await client.get("/api/v1/logs")

    body = response.json()
    assert "super-secret-value" not in response.text
    assert "[REDACTED]" in body["entries"][0]["message"]
