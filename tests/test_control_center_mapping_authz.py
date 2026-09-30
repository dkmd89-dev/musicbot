# -*- coding: utf-8 -*-
"""
Autorisierung der Mapping-Administration: JEDER Endpunkt verlangt mindestens
ADMIN (serverseitig, nicht nur als UI-Check) und ohne Session gibt es 401.
Rollen werden wie in tests/test_control_center_admin_duplicates_api.py per
dependency_overrides gesetzt.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from config import Config
from services.access_control import AccessLevel

_SAME_ORIGIN = {"Origin": "http://testserver"}
_B = "/api/v1/admin/mappings"
_V = "20260101T000000_000000Z"

# (Methode, Pfad, Body) — deckt alle Mapping-Routen ab
ENDPOINTS = [
    ("GET", f"{_B}/status", None),
    ("GET", f"{_B}/genre-aliases", None),
    ("GET", f"{_B}/genre-aliases/entry?key=x", None),
    ("POST", f"{_B}/genre-aliases/preview?key=x", {"canonical": "Jazz"}),
    ("PUT", f"{_B}/genre-aliases?key=x", {"canonical": "Jazz", "etag": "e"}),
    ("GET", f"{_B}/genre-filters", None),
    ("POST", f"{_B}/genre-filters/preview", {"values": ["rock"]}),
    ("PUT", f"{_B}/genre-filters", {"values": ["rock"], "etag": "e"}),
    ("GET", f"{_B}/special-channels", None),
    ("POST", f"{_B}/special-channels/preview", {"categories": []}),
    ("PUT", f"{_B}/special-channels", {"categories": [], "etag": "e"}),
    ("GET", f"{_B}/genre-aliases/backups", None),
    ("POST", f"{_B}/genre-aliases/backups/{_V}/preview", None),
    ("POST", f"{_B}/genre-aliases/backups/{_V}/restore", {"etag": "e"}),
    ("GET", f"{_B}/genre-aliases/yaml", None),
    ("POST", f"{_B}/genre-aliases/yaml/preview", {"text": "GENRE_ALIASES: {}\n"}),
    ("PUT", f"{_B}/genre-aliases/yaml", {"text": "GENRE_ALIASES: {}\n", "etag": "e"}),
]


def _ids():
    return [f"{m} {p.split('?')[0].replace(_B, '')}" for m, p, _ in ENDPOINTS]


@pytest_asyncio.fixture
async def client_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(Config, "GENRE_MAPPING_DIR", tmp_path / "mapping")

    import httpx

    from control_center.app import create_app
    from control_center.dependencies import get_current_access_level

    clients = []

    async def make(level=None):
        app = create_app()
        if level is not None:
            app.dependency_overrides[get_current_access_level] = lambda: level
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
        clients.append(c)
        return c

    yield make
    for c in clients:
        await c.aclose()


async def _call(client, method, path, body):
    return await client.request(method, path, json=body, headers=_SAME_ORIGIN)


@pytest.mark.asyncio
@pytest.mark.parametrize("level", [AccessLevel.PUBLIC, AccessLevel.USER, AccessLevel.MODERATOR], ids=lambda l: l.name)
@pytest.mark.parametrize("method,path,body", ENDPOINTS, ids=_ids())
async def test_every_endpoint_rejects_roles_below_admin(client_factory, monkeypatch, level, method, path, body):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))
    client = await client_factory(level)

    r = await _call(client, method, path, body)

    assert r.status_code == 403, f"{method} {path} als {level.name}: {r.status_code}"
    assert r.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.parametrize("level", [AccessLevel.ADMIN, AccessLevel.OWNER], ids=lambda l: l.name)
@pytest.mark.parametrize("method,path,body", ENDPOINTS, ids=_ids())
async def test_admin_and_owner_pass_the_authorization_check(client_factory, monkeypatch, level, method, path, body):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))
    client = await client_factory(level)

    r = await _call(client, method, path, body)

    assert r.status_code != 403 and r.status_code != 401, f"{method} {path} als {level.name}: {r.status_code}"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", ENDPOINTS, ids=_ids())
async def test_without_session_every_endpoint_is_401(client_factory, method, path, body):
    client = await client_factory()   # kein Dev-Bypass, kein Cookie

    r = await _call(client, method, path, body)

    assert r.status_code == 401, f"{method} {path}: {r.status_code}"
