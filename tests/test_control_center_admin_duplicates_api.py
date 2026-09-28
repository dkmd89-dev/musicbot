# tests/test_control_center_admin_duplicates_api.py
# -*- coding: utf-8 -*-
"""
4b — /api/v1/admin/duplicates/stats + /clear (Web-Gegenstück zum
Telegram-Menü "Admin → Duplikate"). Echter Produktionspfad über
services/duplicate/admin.py und einen echten DuplicateCache auf tmp_path.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.access_control import AccessLevel
from services.downloader.models import DuplicateEntry
from services.duplicate.cache import DuplicateCache

_SAME_ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    d = tmp_path / "duplicate_cache"
    monkeypatch.setattr(Config, "DUPLICATE_CACHE_DIR", d)
    return d


def _add(cache_dir, video_id, artist, title):
    DuplicateCache(cache_dir=str(cache_dir)).add_entry(
        DuplicateEntry(
            artist=artist,
            title=title,
            url=f"https://www.youtube.com/watch?v={video_id}",
            file_path=None,
            download_date=datetime(2026, 9, 1, 12, 0, 0),
        )
    )


def _make_client(access_level=None):
    from control_center.app import create_app
    from control_center.dependencies import get_current_access_level

    app = create_app()
    if access_level is not None:
        app.dependency_overrides[get_current_access_level] = lambda: access_level
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest_asyncio.fixture
async def client():
    c = _make_client()
    try:
        yield c
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_stats_empty(client, cache_dir):
    r = await client.get("/api/v1/admin/duplicates/stats")

    assert r.status_code == 200
    assert r.json() == {"url_entries": 0, "content_entries": 0, "oldest_entry": None, "newest_entry": None}


@pytest.mark.asyncio
async def test_stats_with_entries(client, cache_dir):
    _add(cache_dir, "AAA1", "A", "Eins")
    _add(cache_dir, "BBB2", "B", "Zwei")

    body = (await client.get("/api/v1/admin/duplicates/stats")).json()

    assert body["url_entries"] == 2 and body["content_entries"] == 2
    assert body["oldest_entry"] == "2026-09-01T12:00:00"
    assert set(body) == {"url_entries", "content_entries", "oldest_entry", "newest_entry"}


@pytest.mark.asyncio
async def test_clear_requires_confirmation(client, cache_dir):
    _add(cache_dir, "AAA1", "A", "Eins")

    r = await client.post("/api/v1/admin/duplicates/clear", json={}, headers=_SAME_ORIGIN)

    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert (cache_dir / "url_duplicates.json").exists()


@pytest.mark.asyncio
async def test_clear_rejected_without_origin_header(client, cache_dir):
    _add(cache_dir, "AAA1", "A", "Eins")

    r = await client.post("/api/v1/admin/duplicates/clear", json={"confirm": True})

    assert r.status_code == 403
    assert (cache_dir / "url_duplicates.json").exists()


@pytest.mark.asyncio
async def test_clear_removes_cache(client, cache_dir):
    _add(cache_dir, "AAA1", "A", "Eins")
    long_lived_bot = DuplicateCache(cache_dir=str(cache_dir))

    r = await client.post("/api/v1/admin/duplicates/clear", json={"confirm": True}, headers=_SAME_ORIGIN)

    assert r.status_code == 200
    assert r.json() == {
        "url_entries_removed": 1,
        "content_entries_removed": 1,
        "deleted_files": ["url_duplicates.json", "content_duplicates.json"],
    }
    assert not (cache_dir / "url_duplicates.json").exists()
    # Seit D.13: die langlebige Bot-Instanz übernimmt den geleerten Stand.
    assert long_lived_bot.check_url_duplicate("https://www.youtube.com/watch?v=AAA1") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("path,method", [("/api/v1/admin/duplicates/stats", "get"), ("/api/v1/admin/duplicates/clear", "post")])
async def test_non_admin_is_forbidden(cache_dir, path, method):
    _add(cache_dir, "AAA1", "A", "Eins")
    async with _make_client(AccessLevel.USER) as c:
        if method == "get":
            r = await c.get(path)
        else:
            r = await c.post(path, json={"confirm": True}, headers=_SAME_ORIGIN)

    assert r.status_code == 403
    assert (cache_dir / "url_duplicates.json").exists()
