# tests/test_control_center_statistics_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/statistics/me — eigene Play-History-Statistik.

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router löst über services/user_data.py::get_navidrome_user() den
Navidrome-Username auf und ruft dann
services/statistik_service.py::StatistikService.generate_stats()
unverändert auf.

StatistikService.CHARTS_DIR/USER_HISTORY_DIR sind Klassenattribute (an
Config.STATS_DIR/Config.PLAY_HISTORY_FILE gebunden bei Modul-Import) -
hier wie in tests/test_statistik_service.py per monkeypatch auf tmp_path
umgebogen, BEVOR der Router seine eigene StatistikService()-Instanz
konstruiert (beide teilen sich dieselben, monkeypatchten Klassenattribute).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.statistik_service import StatistikService


def _entry(artist: str, title: str, days_ago: int = 0):
    timestamp = (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {
        "timestamp": timestamp,
        "tracks": [
            {
                "title": title, "artist": artist, "album": "Album",
                "id": "1", "duration": 180, "player": "test-player",
                "username": "alice",
            }
        ],
    }


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    """Dieses Testfile prüft die Statistics-Fachlogik, nicht die
    Authentifizierung (dafür: tests/test_control_center_auth.py)."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture(autouse=True)
def _isolated_statistik_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(StatistikService, "CHARTS_DIR", tmp_path / "stats_charts")
    monkeypatch.setattr(StatistikService, "USER_HISTORY_DIR", tmp_path / "user_histories")


@pytest.fixture
def user_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(Config, "DATA_DIR", data_dir)
    return data_dir


def _write_user_data(data_dir, telegram_id: int, navidrome_user: str):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "user_data.json").write_text(
        json.dumps({str(telegram_id): {"navidrome_user": navidrome_user}}),
        encoding="utf-8",
    )


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
async def test_get_statistics_404_when_no_navidrome_user_configured(client, user_data_dir):
    # OWNER_USER_ID aus dem Dev-Bypass hat keinen Eintrag in user_data.json
    response = await client.get("/api/v1/statistics/me")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NAVIDROME_USER_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_get_statistics_has_data_false_when_no_history(client, user_data_dir, monkeypatch):
    config = Config()
    _write_user_data(user_data_dir, config.OWNER_USER_ID, "alice")

    response = await client.get("/api/v1/statistics/me")

    assert response.status_code == 200
    body = response.json()
    assert body["has_data"] is False
    assert body["navidrome_username"] == "alice"


@pytest.mark.asyncio
async def test_get_statistics_returns_top_artists_ranked_by_play_count(client, user_data_dir):
    config = Config()
    _write_user_data(user_data_dir, config.OWNER_USER_ID, "alice")
    service = StatistikService()
    service._save_history(
        [
            _entry("Bausa", "Song A"),
            _entry("Bausa", "Song B"),
            _entry("Kollegah", "Song C"),
        ],
        "alice",
    )

    response = await client.get("/api/v1/statistics/me")

    assert response.status_code == 200
    body = response.json()
    assert body["has_data"] is True
    assert body["total_plays"] == 3
    assert body["top_artists"][0] == {"label": "Bausa", "count": 2}
    assert body["top_artists"][1] == {"label": "Kollegah", "count": 1}


@pytest.mark.asyncio
async def test_get_statistics_accepts_period_query_param(client, user_data_dir):
    config = Config()
    _write_user_data(user_data_dir, config.OWNER_USER_ID, "alice")
    service = StatistikService()
    service._save_history([_entry("Bausa", "Song A")], "alice")

    response = await client.get("/api/v1/statistics/me", params={"period": "week"})

    assert response.status_code == 200
    assert response.json()["period"] == "week"


@pytest.mark.asyncio
async def test_get_statistics_rejects_invalid_period(client, user_data_dir):
    config = Config()
    _write_user_data(user_data_dir, config.OWNER_USER_ID, "alice")

    response = await client.get("/api/v1/statistics/me", params={"period": "decade"})

    assert response.status_code == 422
