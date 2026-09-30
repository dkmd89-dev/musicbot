# -*- coding: utf-8 -*-
"""
Mapping-Administration, Seitengerüst (Phase 5.0): Route, Sidebar-Eintrag,
Seitenkopf nach UI-Standard und Icons. Die Mapping-Karten folgen später.
"""
import re
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

CC_DIR = Path(__file__).resolve().parent.parent / "control_center"
TEMPLATE = CC_DIR / "templates" / "mappings.html"
MAPPINGS_JS = CC_DIR / "static" / "pages" / "mappings.js"
ICONS = CC_DIR / "templates" / "_icons.html"


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    transport = httpx.ASGITransport(app=create_app())
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


def _sidebar(html: str) -> str:
    start = html.index('id="sidebar"')
    return html[start:html.index("</aside>", start)]


@pytest.mark.asyncio
async def test_mappings_page_is_served_with_page_script(client):
    r = await client.get("/mappings")

    assert r.status_code == 200
    assert '<script src="/static/pages/mappings.js"></script>' in r.text
    assert "<title>Mappings" in r.text


@pytest.mark.asyncio
async def test_mappings_page_follows_ui_standard_header(client):
    html = (await client.get("/mappings")).text

    assert '<div class="page-pretitle">Wartung</div>' in html
    assert '<h2 class="page-title">' in html
    assert '<use href="#i-tag"/>' in html


def test_mappings_template_has_no_inline_script_logic_or_inline_style():
    # UI-Standard §1 Regel 4 und §12: Seiten-JS nur in static/pages, kein Inline-Style.
    source = TEMPLATE.read_text(encoding="utf-8")
    assert 'style="' not in source
    assert not re.search(r"<script(?![^>]*\bsrc=)", source)
    assert "onclick" not in source


@pytest.mark.asyncio
async def test_mappings_has_own_sidebar_entry_in_maintenance_group_not_under_admin(client):
    html = (await client.get("/mappings")).text
    sidebar = _sidebar(html)

    assert re.search(r'href="/mappings"\s*\n\s*class="nav-link active"', html)
    assert "Mappings" in sidebar
    # Reihenfolge: nach Health, vor der System-Gruppe; Administration bleibt unten abgesetzt.
    assert sidebar.index('href="/health"') < sidebar.index('href="/mappings"') < sidebar.index("System")
    assert sidebar.index('href="/mappings"') < sidebar.index('href="/admin"')
    admin_block = sidebar[sidebar.index('href="/admin"') - 200:]
    assert 'href="/mappings"' not in admin_block


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/", "/health", "/admin"])
async def test_mappings_entry_is_not_active_on_other_pages(client, path):
    html = (await client.get(path)).text

    assert 'href="/mappings"' in html
    assert not re.search(r'href="/mappings"\s*\n\s*class="nav-link active"', html)


@pytest.mark.asyncio
async def test_mappings_links_respect_subpath_prefix(client):
    html = (await client.get("/mappings", headers={"X-Forwarded-Prefix": "/controlcenter"})).text

    assert 'href="/controlcenter/mappings"' in html
    assert '<script src="/controlcenter/static/pages/mappings.js"></script>' in html


def test_sprite_has_arrow_icons_for_category_ordering():
    sprite = ICONS.read_text(encoding="utf-8")
    for icon in ("arrow-up", "arrow-down"):
        assert re.search(rf'<symbol fill="none" stroke="currentColor"[^>]*id="i-{icon}"', sprite)


def test_mappings_js_has_no_inline_handlers_or_confirm():
    js = MAPPINGS_JS.read_text(encoding="utf-8")
    assert "confirm(" not in js.replace("ccConfirm(", "")
    assert "onclick" not in js
