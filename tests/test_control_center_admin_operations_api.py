# tests/test_control_center_admin_operations_api.py
# -*- coding: utf-8 -*-
"""
CC-AC-10C: /api/v1/admin/backups, /api/v1/admin/maintenance,
/api/v1/admin/system/restart.
CC-AC-10D: /api/v1/admin/system/status (reine Host-Metriken + Bot-Service-
Check, siehe services/system_status.py-Docstring für den Scope).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): Backup
über services/backup_admin.py (siehe tests/test_backup_admin_service.py
für die reinen Unit-Tests der Fachlogik selbst), Wartungsmodus über das
echte services/bot_maintenance.py::MaintenanceModeStore, Neustart über
das echte utils/bot_restart_trigger.py::BotRestartTrigger (dessen
tatsächlicher systemctl-Aufruf gemockt wird — kein Test darf jemals
echten `sudo systemctl restart` auslösen).
"""

from __future__ import annotations

import time
from unittest.mock import Mock

import httpx
import pytest
import pytest_asyncio

from config import Config
from utils.bot_restart_trigger import BotRestartTrigger

_SAME_ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture(autouse=True)
def _mocked_restart_trigger(monkeypatch):
    """Verhindert unter allen Umständen einen echten `sudo systemctl
    restart`-Aufruf während der Tests."""
    monkeypatch.setattr(BotRestartTrigger, "trigger_restart", Mock())


@pytest.fixture
def backup_dirs(tmp_path, monkeypatch):
    bot_source = tmp_path / "bot"
    lib_source = tmp_path / "library"
    dest_dir = tmp_path / "backups"
    bot_source.mkdir()
    lib_source.mkdir()
    (bot_source / "config.py").write_text("x = 1")
    (lib_source / "track.mp3").write_text("audio")

    monkeypatch.setattr(Config, "BACKUP_BOT_SOURCE_DIR", bot_source)
    monkeypatch.setattr(Config, "BACKUP_LIBRARY_SOURCE_DIR", lib_source)
    monkeypatch.setattr(Config, "BACKUP_DEST_DIR", dest_dir)
    monkeypatch.setattr(Config, "BACKUP_MAX_KEEP", 2)
    return {"bot_source": bot_source, "lib_source": lib_source, "dest_dir": dest_dir}


@pytest.fixture
def maintenance_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(Config, "DATA_DIR", data_dir)
    return data_dir


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


# ─────────────────────────────────────────────────────────────────────────
# Backup
# ─────────────────────────────────────────────────────────────────────────


class TestListBackups:
    @pytest.mark.asyncio
    async def test_empty_when_no_backups(self, client, backup_dirs):
        response = await client.get("/api/v1/admin/backups", params={"backup_type": "bot"})

        assert response.status_code == 200
        assert response.json() == {"backups": [], "max_keep": 2}

    @pytest.mark.asyncio
    async def test_rejects_unknown_backup_type(self, client, backup_dirs):
        response = await client.get("/api/v1/admin/backups", params={"backup_type": "database"})

        assert response.status_code == 422


class TestCreateBackupJob:
    @pytest.mark.asyncio
    async def test_creates_bot_backup_job_and_completes(self, client, backup_dirs):
        response = await client.post(
            "/api/v1/admin/backups", json={"backup_type": "bot"}, headers=_SAME_ORIGIN,
        )

        assert response.status_code == 200
        job = response.json()
        assert job["kind"] == "backup_bot"
        assert job["status"] in {"PENDING", "RUNNING"}

        # Job läuft als asyncio.create_task() im Hintergrund - kurz pollen.
        for _ in range(50):
            status = (await client.get(f"/api/v1/jobs/{job['job_id']}")).json()
            if status["status"] in {"SUCCEEDED", "FAILED"}:
                break
            time.sleep(0.05)

        assert status["status"] == "SUCCEEDED"
        assert status["result"]["name"].startswith("bot_backup_")

        listed = (
            await client.get("/api/v1/admin/backups", params={"backup_type": "bot"})
        ).json()
        assert len(listed["backups"]) == 1

    @pytest.mark.asyncio
    async def test_rejected_without_origin_header(self, client, backup_dirs):
        response = await client.post("/api/v1/admin/backups", json={"backup_type": "bot"})

        assert response.status_code == 403


class TestDeleteBackup:
    @pytest.mark.asyncio
    async def test_deletes_existing_backup(self, client, backup_dirs):
        backup_dirs["dest_dir"].mkdir(parents=True, exist_ok=True)
        (backup_dirs["dest_dir"] / "bot_backup_20260101_000000.tar.gz").write_text("data")

        response = await client.delete(
            "/api/v1/admin/backups/bot_backup_20260101_000000.tar.gz", headers=_SAME_ORIGIN,
        )

        assert response.status_code == 200
        assert response.json() == {"name": "bot_backup_20260101_000000.tar.gz", "deleted": True}
        assert not (backup_dirs["dest_dir"] / "bot_backup_20260101_000000.tar.gz").exists()

    @pytest.mark.asyncio
    async def test_rejects_path_traversal_sec006(self, client, backup_dirs):
        """"%2e%2e" (URL-kodiertes "..") bleibt EIN Pfadsegment, damit die
        Anfrage ueberhaupt die {filename}-Route erreicht - ein Segment mit
        eingebettetem "/" (z.B. "..%2F..%2Fetc%2Fpasswd") wird bereits von
        Starlettes Routing selbst mit 404 abgelehnt, bevor der Handler
        (und damit resolve_backup_path()) ueberhaupt erreicht wird."""
        backup_dirs["dest_dir"].mkdir(parents=True, exist_ok=True)

        response = await client.delete("/api/v1/admin/backups/%2e%2e", headers=_SAME_ORIGIN)

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_unknown_backup_returns_404(self, client, backup_dirs):
        backup_dirs["dest_dir"].mkdir(parents=True, exist_ok=True)

        response = await client.delete(
            "/api/v1/admin/backups/bot_backup_does_not_exist.tar.gz", headers=_SAME_ORIGIN,
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_rejected_without_origin_header(self, client, backup_dirs):
        backup_dirs["dest_dir"].mkdir(parents=True, exist_ok=True)
        (backup_dirs["dest_dir"] / "bot_backup_x.tar.gz").write_text("data")

        response = await client.delete("/api/v1/admin/backups/bot_backup_x.tar.gz")

        assert response.status_code == 403
        assert (backup_dirs["dest_dir"] / "bot_backup_x.tar.gz").exists()


# ─────────────────────────────────────────────────────────────────────────
# Wartungsmodus
# ─────────────────────────────────────────────────────────────────────────


class TestMaintenanceMode:
    @pytest.mark.asyncio
    async def test_defaults_to_inactive(self, client, maintenance_data_dir):
        response = await client.get("/api/v1/admin/maintenance")

        assert response.status_code == 200
        assert response.json()["active"] is False

    @pytest.mark.asyncio
    async def test_activates_and_persists(self, client, maintenance_data_dir):
        response = await client.post(
            "/api/v1/admin/maintenance", json={"active": True}, headers=_SAME_ORIGIN,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["active"] is True
        assert body["changed_by_user_id"] is not None

        again = (await client.get("/api/v1/admin/maintenance")).json()
        assert again["active"] is True

    @pytest.mark.asyncio
    async def test_deactivates(self, client, maintenance_data_dir):
        await client.post("/api/v1/admin/maintenance", json={"active": True}, headers=_SAME_ORIGIN)
        response = await client.post(
            "/api/v1/admin/maintenance", json={"active": False}, headers=_SAME_ORIGIN,
        )

        assert response.json()["active"] is False

    @pytest.mark.asyncio
    async def test_rejected_without_origin_header(self, client, maintenance_data_dir):
        response = await client.post("/api/v1/admin/maintenance", json={"active": True})

        assert response.status_code == 403
        assert (await client.get("/api/v1/admin/maintenance")).json()["active"] is False


# ─────────────────────────────────────────────────────────────────────────
# Bot-Neustart
# ─────────────────────────────────────────────────────────────────────────


class TestBotRestart:
    @pytest.mark.asyncio
    async def test_schedules_restart_via_trigger(self, client):
        response = await client.post("/api/v1/admin/system/restart", headers=_SAME_ORIGIN)

        assert response.status_code == 200
        assert "Neustart" in response.json()["message"]

        # call_later() ist real geplant (2s Verzoegerung) - der eigentliche
        # subprocess-Aufruf ist ueber die autouse-Fixture oben gemockt,
        # daher hier bewusst KEIN Warten auf den Timer-Fire.
        BotRestartTrigger.trigger_restart.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejected_without_origin_header(self, client):
        response = await client.post("/api/v1/admin/system/restart")

        assert response.status_code == 403


# ─────────────────────────────────────────────────────────────────────────
# System-Status (CC-AC-10D)
# ─────────────────────────────────────────────────────────────────────────


class TestSystemStatus:
    @pytest.mark.asyncio
    async def test_returns_host_metrics_and_service_status(self, client, monkeypatch):
        from services import system_status

        monkeypatch.setattr(system_status, "get_bot_service_active", lambda name: True)

        response = await client.get("/api/v1/admin/system/status")

        assert response.status_code == 200
        body = response.json()
        assert 0 <= body["cpu_percent"] <= 100
        assert body["memory_total_mb"] > 0
        assert body["disk_total_gb"] > 0
        assert body["bot_service_name"] == "bot"
        assert body["bot_service_active"] is True

    @pytest.mark.asyncio
    async def test_reports_unknown_service_status_as_null(self, client, monkeypatch):
        from services import system_status

        monkeypatch.setattr(system_status, "get_bot_service_active", lambda name: None)

        response = await client.get("/api/v1/admin/system/status")

        assert response.json()["bot_service_active"] is None
