# tests/test_control_center_library_page.py
# -*- coding: utf-8 -*-
"""
CC-UI Library — Schritt L1 (Nutzerentscheidung 2026-09-28):

- U1: das Inline-JS von /library und /library/{artist} liegt byte-identisch
  in static/pages/library.js bzw. static/pages/library_artist.js. Das
  Verhalten sichern die bestehenden Tests ab, die das Skript jetzt aus
  diesen Dateien lesen (test_artist_*_ui.py, test_artist_detail_master_view.py,
  test_library_home_dashboard.py, test_control_center_ui.py).
- U16: /metadata (Stub-Seite, nirgends verlinkt) leitet auf /library um.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parent.parent
CC_DIR = ROOT / "control_center"


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    transport = httpx.ASGITransport(app=create_app())
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("path, script", [
    ("/library", "library.js"),
    ("/library/Bausa", "library_artist.js"),
])
async def test_library_pages_load_their_script_from_static_pages(client, path, script):
    html = (await client.get(path)).text
    assert f'<script src="/static/pages/{script}"></script>' in html
    # kein Inline-Skript mehr im Seiteninhalt (nur noch die Shell-Skripte)
    content = html[html.index('id="dashboard-view"'):]
    assert "<script>" not in content.split(f'/static/pages/{script}')[0]
    served = (await client.get(f"/static/pages/{script}")).text
    assert served == (CC_DIR / "static" / "pages" / script).read_text(encoding="utf-8")


@pytest.mark.parametrize("template", ["library.html", "library_artist_detail.html"])
def test_templates_have_no_inline_script(template):
    assert "<script>" not in (CC_DIR / "templates" / template).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_library_script_uses_prefixed_src_behind_proxy(client):
    html = (await client.get("/library/Bausa", headers={"X-Forwarded-Prefix": "/cc"})).text
    assert '<script src="/cc/static/pages/library_artist.js"></script>' in html


@pytest.mark.asyncio
async def test_metadata_redirects_to_library(client):
    r = await client.get("/metadata", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/library"
    assert not (CC_DIR / "templates" / "metadata.html").exists()


@pytest.mark.asyncio
async def test_metadata_redirect_keeps_proxy_prefix(client):
    r = await client.get("/metadata", headers={"X-Forwarded-Prefix": "/cc"}, follow_redirects=False)
    assert r.headers["location"] == "/cc/library"


@pytest.mark.asyncio
async def test_metadata_redirect_ignores_hostile_prefix(client):
    """Kein offener Redirect: ungültige Prefixe verwirft normalize_prefix()."""
    r = await client.get("/metadata", headers={"X-Forwarded-Prefix": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/library"
