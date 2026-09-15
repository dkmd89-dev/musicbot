# tests/test_control_center_downloads_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/downloads/history — Download-Center (read-only).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router ruft services/downloader/download_history.py::DownloadHistoryStore
unverändert auf. Fixtures werden über die echte add_entry()-API aufgebaut
statt die JSON-Datei direkt zu schreiben — identisches Prinzip wie
tests/test_control_center_findings_api.py.

Kein ffmpeg nötig — reine JSON-Persistenz, kein Library-Scan.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.downloader.download_history import DownloadHistoryStore


@pytest.fixture
def history_dir(tmp_path):
    return tmp_path / "download_history"


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    """Dieses Testfile prüft die Download-History-Fachlogik, nicht die
    Authentifizierung (dafür: tests/test_control_center_auth.py)."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


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
async def test_get_download_history_empty_when_no_store_file(client, history_dir, monkeypatch):
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", history_dir)

    response = await client.get("/api/v1/downloads/history")

    assert response.status_code == 200
    assert response.json() == {"entries": []}


@pytest.mark.asyncio
async def test_get_download_history_merges_chats_newest_first(client, history_dir, monkeypatch):
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", history_dir)
    store = DownloadHistoryStore(cache_dir=str(history_dir))
    store.add_entry(1, url="u1", title="Alt", artist="A", status="success")
    store.add_entry(2, url="u2", title="Neu", artist="B", status="failed")

    body = (await client.get("/api/v1/downloads/history")).json()

    assert [e["title"] for e in body["entries"]] == ["Neu", "Alt"]
    assert body["entries"][0]["chat_id"] == 2
    assert body["entries"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_get_download_history_includes_metadata_checklist(client, history_dir, monkeypatch):
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", history_dir)
    store = DownloadHistoryStore(cache_dir=str(history_dir))
    store.add_entry(
        1, url="u", title="T", artist="A", status="success",
        genre_ok=True, lyrics_ok=False, cover_ok=None, mb_ok=True, loudness_ok=None,
    )

    entry = (await client.get("/api/v1/downloads/history")).json()["entries"][0]

    assert entry["genre_ok"] is True
    assert entry["lyrics_ok"] is False
    assert entry["cover_ok"] is None
    assert entry["mb_ok"] is True
    assert entry["loudness_ok"] is None


@pytest.mark.asyncio
async def test_get_download_history_respects_limit_query_param(client, history_dir, monkeypatch):
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", history_dir)
    store = DownloadHistoryStore(cache_dir=str(history_dir))
    for i in range(5):
        store.add_entry(1, url=f"u{i}", title=f"T{i}", artist="A", status="success")

    response = await client.get("/api/v1/downloads/history", params={"limit": 2})

    assert response.status_code == 200
    assert len(response.json()["entries"]) == 2


@pytest.mark.asyncio
async def test_get_download_history_rejects_invalid_limit(client, history_dir, monkeypatch):
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", history_dir)

    response = await client.get("/api/v1/downloads/history", params={"limit": 0})

    assert response.status_code == 422
