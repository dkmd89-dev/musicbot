# tests/test_control_center_ui.py
# -*- coding: utf-8 -*-
"""
Seiten-Routen (control_center/routers/ui.py) — Mehrseiten-Struktur seit
ui_prompt.txt Phase 1 "UI STRUCTURE REDESIGN".

Testet den echten Produktionscode-Pfad: jede Route rendert ihr reales
Template über die echte Jinja2Templates-Instanz — kein im Testfile
nachgebautes HTML. Ersetzt die vorherige Version dieser Datei, die noch
ausschließlich gegen "/" testete (Einzel-Dashboard vor dem Redesign) -
jeder damalige Test ist hier auf die neue Seite verschoben, auf der das
jeweilige Panel jetzt lebt (siehe docs/audits/
CONTROL_CENTER_ARCHITECTURE_2026-09-15.md, Abschnitt "UI Structure
Redesign Phase 1", für die vollständige Panel-zu-Seite-Zuordnung).

Alle Seiten-Routen sind bewusst unauthentifiziert (siehe Router-
Docstring) — die Tests prüfen entsprechend, dass sie ohne jede Session/
Dev-Bypass funktionieren (anders als die Endpunkte in
test_control_center_health_api.py/test_control_center_findings_api.py).
"""

from __future__ import annotations

import re

import httpx
import pytest

@pytest.fixture
def anyio_backend() -> str:
    """Beschraenkt pytest-anyio auf das asyncio-Backend (trio-Version hat in diesem Repo Kompatibilitaetsprobleme)."""
    return "asyncio"
import pytest_asyncio

from config import Config

ALL_PAGES = ["/", "/downloads", "/library", "/statistics", "/health", "/navidrome", "/logs", "/admin"]


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
# Gemeinsames Basis-Layout (_base.html) — gilt fuer alle Seiten
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PAGES)
async def test_page_renders_without_any_authentication(client, path):
    """Jede Seiten-Route ist bewusst oeffentlich (nur HTML-Grundgeruest,
    keine Library-/Nutzerdaten) - kein Cookie, kein Dev-Bypass noetig."""
    response = await client.get(path)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "MusicBot Control Center" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PAGES)
async def test_page_contains_all_view_states(client, path):
    html = (await client.get(path)).text

    assert 'id="loading-view"' in html
    assert 'id="login-view"' in html
    assert 'id="dashboard-view"' in html
    assert 'id="error-view"' in html


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PAGES)
async def test_page_contains_full_sidebar_navigation(client, path):
    """ui_prompt.txt Abschnitt 8/11: alle 12 Ziel-Seiten muessen von
    jeder Seite aus ueber die Sidebar erreichbar sein."""
    html = (await client.get(path)).text

    for nav_path in ALL_PAGES:
        assert f'href="{nav_path}"' in html, f"{nav_path} fehlt in der Sidebar auf {path}"


# @pytest.mark.asyncio
# async def test_overview_nav_link_is_marked_active_on_overview_page(client):
#     html = (await client.get("/")).text
#
#     assert 'href="/" class="nav-link active"' in html
#
#
_NAV_LINK_ACTIVE_RE = "href=\"{path}\"\\s*\\n\\s*class=\"nav-link active\""
#
#
@pytest.mark.asyncio
async def test_health_nav_link_is_marked_active_on_health_page(client):
    """_base.html rendert href/class als eigene Attribut-Zeilen (siehe
    <a>-Markup dort) - deshalb hier tolerant gegenueber Whitespace
    zwischen beiden Attributen statt eines starren Ein-Zeilen-Substrings."""
    html = (await client.get("/health")).text

    assert re.search(_NAV_LINK_ACTIVE_RE.format(path="/health"), html)
    # Andere Seiten bleiben auf der Health-Seite nicht "active":
    assert not re.search(_NAV_LINK_ACTIVE_RE.format(path="/"), html)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PAGES)
async def test_page_loads_shared_static_assets(client, path):
    html = (await client.get(path)).text

    assert '/static/common.css' in html
    assert '/static/common.js' in html


@pytest.mark.asyncio
async def test_static_common_js_is_served(client):
    response = await client.get("/static/common.js")

    assert response.status_code == 200
    assert "function _escapeHtml" in response.text
    assert "function checkAuth" in response.text
    assert "function _loadInto" in response.text
    assert "function onTelegramAuth" in response.text


@pytest.mark.asyncio
async def test_static_common_css_is_served(client):
    response = await client.get("/static/common.css")

    assert response.status_code == 200
    assert "#sidebar" in response.text


@pytest.mark.asyncio
async def test_page_shows_telegram_widget_when_bot_username_configured(client, monkeypatch):
    monkeypatch.setattr(Config, "BOT_USERNAME", property(lambda self: "MeinTestBot"))

    html = (await client.get("/")).text

    assert 'data-telegram-login="MeinTestBot"' in html
    assert "telegram-widget.js" in html
    assert "CONTROL_CENTER_DEV_AUTH_BYPASS" not in html


@pytest.mark.asyncio
async def test_page_shows_config_hint_when_bot_username_missing(client, monkeypatch):
    monkeypatch.setattr(Config, "BOT_USERNAME", property(lambda self: ""))

    html = (await client.get("/")).text

    assert "telegram-widget.js" not in html
    assert "CONTROL_CENTER_DEV_AUTH_BYPASS" in html


# ─────────────────────────────────────────────────────────────────────────
# GET / — Overview (kompakt: KPIs, Attention, Active Jobs, Recent
# Activity, Quick Actions — ui_prompt.txt Abschnitt 9)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overview_contains_kpi_and_summary_elements(client):
    """Das Overview entspricht dem aktuellen finalen Dashboard-Layout."""

    html = (await client.get("/")).text

    # System-KPIs
    assert 'id="metric-cpu-value"' in html
    assert 'id="metric-cpu-sub"' in html
    assert 'id="metric-ram-value"' in html
    assert 'id="metric-ram-sub"' in html
    assert 'id="metric-disk-value"' in html
    assert 'id="metric-disk-sub"' in html
    assert 'id="metric-bot-value"' in html
    assert 'id="metric-bot-sub"' in html

    # Library-Statuskarte
    assert 'id="status-library-value"' in html
    assert 'id="status-library-hint"' in html
    assert 'id="status-library-health-bar"' in html
    assert 'id="status-library-health-fill"' in html
    assert 'id="status-library-health-label"' in html

    # Navidrome-Statuskarte
    assert 'id="status-navidrome-value"' in html
    assert 'id="status-navidrome-hint"' in html

    # System-Statuskarte
    assert 'id="system-platform-os"' in html
    assert 'id="system-platform-python"' in html
    assert 'id="system-uptime-value"' in html
    assert 'id="system-uptime-started"' in html
    assert 'id="system-load-value"' in html
    assert 'id="system-swap-value"' in html

    # Aufmerksamkeit + zuletzt
    assert 'id="attention-panel"' in html
    assert 'id="attention-content"' in html
    assert 'id="recent-activity-content"' in html

    # Schnellzugriff
    assert 'href="/library"' in html
    assert 'href="/downloads"' in html
    assert 'href="/health"' in html


@pytest.mark.asyncio
async def test_overview_does_not_contain_full_panel_lists(client):
    """ui_prompt.txt Abschnitt 10: komplette Findings/Repair-Pläne/
    Metadata-Listen/Download-Historie/Userverwaltung/Statistics duerfen
    nicht mehr vollstaendig auf der Startseite erscheinen."""
    html = (await client.get("/")).text

    assert 'id="findings-content"' not in html
    assert 'id="repair-plan-content"' not in html
    assert 'id="downloads-content"' not in html
    assert 'id="admin-users-content"' not in html
    assert 'id="metadata-content"' not in html


@pytest.mark.asyncio
async def test_overview_quick_actions_link_to_detail_pages(client):
    """Findings/Repairs/Jobs sind seit der Health-Konsolidierung
    (api_health.md) EIN gemeinsames Ziel (/health) statt drei getrennter
    Seiten (siehe control_center/routers/ui.py-Docstring)."""
    html = (await client.get("/")).text

    assert 'href="/health"' in html
    assert 'href="/library"' in html


# ─────────────────────────────────────────────────────────────────────────
# GET /downloads
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_downloads_page_has_history_panel(client):
    html = (await client.get("/downloads")).text

    assert 'id="downloads-content"' in html
    assert "/api/v1/downloads/history" in html
    assert "loadDownloads" in html


# ─────────────────────────────────────────────────────────────────────────
# GET /library — Tracks/Artists/Albums/Mapping (Master-Prompt Abschnitt 7)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_library_page_has_metadata_browser_panel(client):
    html = (await client.get("/library")).text

    assert "Library-Metadata" in html
    assert 'id="metadata-tracks-btn"' in html
    assert 'id="metadata-artists-btn"' in html
    assert 'id="metadata-albums-btn"' in html
    assert 'id="metadata-content"' in html


@pytest.mark.asyncio
async def test_library_page_ui_wiring_present(client):
    html = (await client.get("/library")).text

    assert "loadMetadataList" in html
    assert "renderTracks" in html
    assert "renderMetadataArtists" in html
    assert "renderMetadataAlbums" in html
    assert "/api/v1/library/${mode}" in html


@pytest.mark.asyncio
async def test_library_page_has_mapping_summary_wiring(client):
    html = (await client.get("/library")).text

    assert 'id="metadata-mapping-btn"' in html
    assert "loadMappingSummary" in html
    assert "renderMappingSummary" in html
    assert "/api/v1/library/mapping-summary" in html


@pytest.mark.asyncio
async def test_library_page_has_no_repeated_rescan_pagination(client):
    """Bewusste Entscheidung: keine Weiter/Zurück-Buttons, da jede
    Anfrage einen vollen Library-Scan ausloest - stattdessen
    Trunkierungshinweis wie beim Accepted-Findings-Panel."""
    html = (await client.get("/library")).text

    assert "kein Auto-Rendern großer Listen" in html


@pytest.mark.asyncio
async def test_library_page_has_missing_metadata_filter(client):
    html = (await client.get("/library")).text

    assert 'id="metadata-missing-filter"' in html
    assert "META_GENRE_MISSING" in html
    assert "ARTWORK_MISSING" in html
    assert "LYRICS_MISSING" in html
    assert "issue_code=" in html


# ─────────────────────────────────────────────────────────────────────────
# GET /library — Artist-Centric UX (CC-AC-1, library_artist_centric_UX.txt)
# Bewusst getrennt von den obigen Metadata-Browser-Tests: alte Sektion
# bleibt vollstaendig erhalten (Auftrag §39), die neue Artist-Sektion
# kommt zusaetzlich hinzu.
# ─────────────────────────────────────────────────────────────────────────


# @pytest.mark.asyncio
# async def test_library_page_has_artists_overview_panel(client):
#     html = (await client.get("/library")).text
#
#     assert "🎤 Artists" in html
#     assert 'id="artist-search"' in html
#     assert 'id="artists-overview-content"' in html
#
#
@pytest.mark.asyncio
async def test_library_page_artists_overview_ui_wiring_present(client):
    html = (await client.get("/library")).text

    assert "loadArtistsOverview" in html
    assert "renderArtistsOverview" in html
    assert "/api/v1/library/artists-overview" in html
    # Klickbarer Artist-Link führt in die neue Detailseite, nicht in
    # eine JS-only-Umschaltung (F5-tauglich, Auftrag §10/§29):
    assert "/library/${encodeURIComponent(a.artist)}" in html


@pytest.mark.asyncio
async def test_library_page_keeps_legacy_metadata_browser_unchanged(client):
    """Auftrag §39: alte, Klick-gesteuerte Tracks/Artists/Albums/Mapping-
    Sektion bleibt vollstaendig erreichbar, unveraendert."""
    html = (await client.get("/library")).text

    assert "Library-Metadata" in html
    assert 'id="metadata-tracks-btn"' in html
    assert 'id="metadata-artists-btn"' in html
    assert 'id="metadata-albums-btn"' in html
    assert 'id="metadata-mapping-btn"' in html
    assert "kein Auto-Rendern großer Listen" in html


# ─────────────────────────────────────────────────────────────────────────
# GET /library — UI Consolidation (CC-AC-7): KPI-Zeile, Sortierung,
# Library-Metadata als eingeklapptes Accordion.
# ─────────────────────────────────────────────────────────────────────────


# @pytest.mark.asyncio
# async def test_library_page_has_kpi_tiles(client):
#     """KPI-Zeile nutzt den bestehenden Cache-Read-Endpunkt
#     GET /api/v1/library/health/cached (Auftrag §5) - keine neue API,
#     keine Client-Aggregation."""
#     html = (await client.get("/library")).text
#
#     assert 'id="library-kpi-tiles"' in html
#     assert 'class="tiles" id="library-kpi-tiles"' in html
#     assert "loadLibraryKpis" in html
#     assert "/api/v1/library/health/cached" in html
#
#
@pytest.mark.asyncio
async def test_library_page_has_artist_sort_control(client):
    html = (await client.get("/library")).text

    assert 'id="artist-sort"' in html
    assert "_ARTIST_SORT_COMPARATORS" in html


@pytest.mark.asyncio
async def test_library_page_metadata_panel_is_collapsed_details(client):
    """Auftrag §10 (Option 3): Library-Metadata bleibt erreichbar, wird
    aber in ein initial eingeklapptes <details>-Element verschoben, damit
    es die Artist-Navigation nicht mehr dominiert."""
    html = (await client.get("/library")).text

    assert '<details id="library-metadata-details">' in html
    assert '<details id="library-metadata-details" open>' not in html


# ─────────────────────────────────────────────────────────────────────────
# GET /library/{artist} — Artist Detail (CC-AC-1)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_artist_detail_page_renders_without_authentication(client):
    response = await client.get("/library/Bausa")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "MusicBot Control Center" in response.text


@pytest.mark.asyncio
async def test_artist_detail_page_contains_all_view_states(client):
    html = (await client.get("/library/Bausa")).text

    assert 'id="loading-view"' in html
    assert 'id="login-view"' in html
    assert 'id="dashboard-view"' in html
    assert 'id="error-view"' in html


@pytest.mark.asyncio
async def test_artist_detail_page_loads_shared_static_assets(client):
    html = (await client.get("/library/Bausa")).text

    assert "/static/common.css" in html
    assert "/static/common.js" in html


# @pytest.mark.asyncio
# async def test_artist_detail_page_keeps_library_nav_active(client):
#     """page_id="library" haelt den Sidebar-Eintrag auf der Artist-
#     Detailseite aktiv (Auftrag: Artist ist eine Unterseite von Library,
#     kein eigener Sidebar-Eintrag)."""
#     html = (await client.get("/library/Bausa")).text
#
#     assert 'href="/library" class="nav-link active"' in html
#
#
# @pytest.mark.asyncio
# async def test_artist_detail_page_has_breadcrumb_and_back_link(client):
#     html = (await client.get("/library/Bausa")).text
#
#     assert 'class="breadcrumb"' in html
#     assert 'href="/library">📚 Library' in html
#     assert "Zurück zu Artists" in html
#
#
@pytest.mark.asyncio
async def test_artist_detail_page_ui_wiring_present(client):
    html = (await client.get("/library/Bausa")).text

    assert "loadArtistDetail" in html
    assert "renderArtistDetail" in html
    assert "currentArtistFromPath" in html
    assert "/api/v1/library/artists-overview/${encodeURIComponent(artist)}" in html
    assert 'id="artist-content"' in html


@pytest.mark.asyncio
async def test_artist_detail_page_resolves_artist_client_side_not_server_side(client):
    """Auftrag: unbekannter Artist bleibt ein sauberer API-404, kein
    Server-Renderfehler - die Seite selbst rendert fuer JEDEN
    Pfad-Wert identisch (kein serverseitiges Nachschlagen in ui.py)."""
    html_known = (await client.get("/library/Bausa")).text
    html_unknown = (await client.get("/library/Does-Not-Exist-XYZ")).text

    assert html_known == html_unknown


# ─────────────────────────────────────────────────────────────────────────
# GET /library/{artist} — Manual Metadata Editing v1 (CC-AC-2)
# ─────────────────────────────────────────────────────────────────────────
#
# Reine Verdrahtung der bereits produktiven Endpunkte aus
# admin_maintenance.py (Artist/Titel) und metadata_actions.py (Genre) -
# jene Endpunkte haben eigene Test-Suiten
# (test_control_center_admin_maintenance_api.py,
# test_control_center_metadata_actions_api.py), hier wird nur geprueft,
# dass das Artist-Detail-Template sie tatsaechlich verdrahtet und die
# Buttons standardmaessig hinter der Admin-Sichtbarkeitsschranke stehen
# (Auftrag CC-AC-2-Scope).


@pytest.mark.asyncio
async def test_artist_detail_page_has_metadata_edit_panel_hidden_by_default(client):
    html = (await client.get("/library/Bausa")).text

    assert 'id="artist-metadata-edit-panel" hidden' in html


@pytest.mark.asyncio
async def test_artist_detail_page_metadata_edit_gated_by_access_level(client):
    html = (await client.get("/library/Bausa")).text

    assert 'who.access_level === "ADMIN" || who.access_level === "OWNER"' in html
    assert 'getElementById("artist-metadata-edit-panel").hidden = !isAdmin' in html


@pytest.mark.asyncio
async def test_artist_detail_page_metadata_panel_is_collapsed_details(client):
    """CC-AC-7: Metadaten-Editing ist initial eingeklappt (natives
    <details>, kein open-Attribut) statt eines dauerhaft sichtbaren
    Formularblocks."""
    html = (await client.get("/library/Bausa")).text

    panel = html.split('id="artist-metadata-edit-panel"', 1)[1].split("</section>", 1)[0]
    assert "<details>" in panel
    assert "<details open>" not in panel


@pytest.mark.asyncio
async def test_artist_detail_page_has_manual_metadata_editing_buttons(client):
    html = (await client.get("/library/Bausa")).text

    assert 'id="artist-edit-preview-btn"' in html
    assert 'id="artist-edit-execute-btn"' in html
    assert 'id="title-edit-preview-btn"' in html
    assert 'id="title-edit-execute-btn"' in html
    assert 'id="genre-manage-preview-btn"' in html
    assert 'id="genre-manage-execute-btn"' in html


@pytest.mark.asyncio
async def test_artist_detail_page_wires_existing_artist_rename_endpoints(client):
    """Auftrag §13/§14: Artist bearbeiten ruft ausschliesslich den
    bestehenden admin_maintenance-Endpunkt auf, keine neue Ausfuehrung."""
    html = (await client.get("/library/Bausa")).text

    assert "/api/v1/admin/maintenance/artist-rename/preview?" in html
    assert '"/api/v1/admin/maintenance/artist-rename/execute"' in html


@pytest.mark.asyncio
async def test_artist_detail_page_wires_existing_title_edit_endpoints(client):
    html = (await client.get("/library/Bausa")).text

    assert "/api/v1/admin/maintenance/title-edit/preview?" in html
    assert '"/api/v1/admin/maintenance/title-edit/execute"' in html


@pytest.mark.asyncio
async def test_artist_detail_page_wires_existing_genre_endpoints(client):
    html = (await client.get("/library/Bausa")).text

    assert "/api/v1/library/artists/${encodeURIComponent(artist)}/genre-preview" in html
    assert "/api/v1/library/artists/${encodeURIComponent(artist)}/set-genre" in html


@pytest.mark.asyncio
async def test_artist_detail_page_metadata_edit_uses_artist_context_not_free_text(client):
    """Auftrag §12: der Artist-Kontext (aus dem Pfad) wird implizit
    mitgegeben - alle sechs Aktionen (Preview+Execute je Artist/Titel/
    Genre) lesen ihn ueber currentArtistFromPath(), kein eigenes
    Freitext-Artist-Feld wie im generischen admin.html-Formular."""
    html = (await client.get("/library/Bausa")).text

    assert html.count("currentArtistFromPath()") >= 6


@pytest.mark.asyncio
async def test_artist_detail_page_artist_rename_does_not_navigate_away(client):
    """Regression: apply_artist_rename() (services/library_repair/
    executor.py) ist tag-wert-getrieben, benennt NIE das Artist-Verzeichnis
    um - ein fruehrer Implementierungsstand navigierte nach Erfolg auf
    /library/{new_artist}, was garantiert auf einen 404 lief (der neue
    Verzeichnisname existiert nie) und dabei die Erfolgs-/Fehler-Zahlen
    zerstoerte. Fix: keine Navigation, stattdessen dieselbe Vorschau neu
    laden (siehe naechster Test)."""
    html = (await client.get("/library/Bausa")).text

    assert "window.location.href" not in html


@pytest.mark.asyncio
async def test_artist_detail_page_reloads_own_preview_after_each_action(client):
    """Nach Erfolg laedt jede der drei Aktionen ihre EIGENE Vorschau neu
    (statt zu navigieren oder den laut CC-AC-1 nur zwischengespeicherten,
    nicht live aktualisierten Artist-Report erneut zu laden)."""
    html = (await client.get("/library/Bausa")).text

    assert html.count("loadArtistEditPreview()") >= 2
    assert html.count("loadTitleEditPreview()") >= 2
    assert html.count("loadGenreManagePreview()") >= 2


@pytest.mark.asyncio
async def test_artist_detail_page_surfaces_skip_reasons_in_preview(client):
    """Regression: SKIPPED/FAILED-Gruende (z. B. "Artist-Tag entspricht
    nicht dem gewaehlten Ausgangswert") wurden zuvor im No-Op-Fall
    verschluckt statt angezeigt."""
    html = (await client.get("/library/Bausa")).text

    assert "body.outcomes.map((o) => o.reason)" in html


@pytest.mark.asyncio
async def test_artist_detail_page_disables_execute_after_input_changes(client):
    """Preview<->Execute-Kopplung: eine Feldaenderung NACH einer geladenen
    Vorschau deaktiviert den Ausfuehren-Button wieder, damit nie ein
    anderer Wert geschrieben wird als der zuletzt angezeigte Diff."""
    html = (await client.get("/library/Bausa")).text

    assert 'getElementById("artist-edit-new-artist").addEventListener("input"' in html
    assert '["title-edit-rel-path", "title-edit-new-title"].forEach' in html


@pytest.mark.asyncio
async def test_artist_detail_page_title_edit_has_artist_scope_guard(client):
    """UX-Scope-Guard (keine Sicherheitsgrenze): rel_path muss innerhalb
    des aktuellen Artist-Ordners liegen, sonst koennte versehentlich ein
    Track eines anderen Artists editiert werden."""
    html = (await client.get("/library/Bausa")).text

    assert "function _titleEditRelPathInScope(artist, relPath)" in html
    assert html.count("_titleEditRelPathInScope(artist, relPath)") >= 3


@pytest.mark.asyncio
async def test_artist_detail_page_execute_errors_do_not_claim_network_failure(client):
    """Die sieben synchronen Ganz-Artist-/Ganz-Album-/Ganz-Track-
    Schreibvorgaenge (Artist/Titel/Genre bearbeiten aus CC-AC-2,
    Album/Albuminterpret bearbeiten aus CC-AC-3, Artist-Casing/Legacy-
    Genre-Cleanup aus CC-AC-4) sind synchrone Schreibvorgaenge hinter
    einem Reverse Proxy ohne explizites proxy_read_timeout
    (docs/CONTROL_CENTER_REVERSE_PROXY.md) - ein abgebrochener Request
    kann trotzdem serverseitig fertig geschrieben worden sein. Ihr
    Fehlertext behauptet deshalb keinen Netzwerkfehler mehr, sondern ein
    unbekanntes Ergebnis.

    Der L2/L3-Job-Start (CC-AC-4) ist davon bewusst ausgenommen: er
    erstellt nur einen Job und kehrt sofort zurueck (kein langer
    synchroner Schreibvorgang wie oben) - identisches
    "Netzwerkfehler"-Wording wie beim aequivalenten Job-Start in
    static/pages/health.js::startLevel23Job()."""
    html = (await client.get("/library/Bausa")).text

    assert html.count("Ergebnis unbekannt") >= 7
    assert html.count("Netzwerkfehler") == 1

    start_job_fn = html.split("async function startArtistRepairJob(level) {", 1)[1]
    start_job_fn_body = start_job_fn.split('document.getElementById("repair-l2-btn")', 1)[0]
    assert "Netzwerkfehler" in start_job_fn_body


@pytest.mark.asyncio
async def test_artist_detail_page_confirms_before_write_actions(client):
    """Auftrag §25: Preview -> Confirmation -> Execute, window.confirm()
    identisch zu admin_maintenance heute (admin.html)."""
    html = (await client.get("/library/Bausa")).text

    assert "window.confirm(" in html
    assert html.count("window.confirm(") >= 3


# ─────────────────────────────────────────────────────────────────────────
# Album/Albuminterpret bearbeiten (CC-AC-3, library_artist_centric_UX.txt)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_artist_detail_page_has_album_edit_buttons(client):
    html = (await client.get("/library/Bausa")).text

    assert 'id="album-edit-preview-btn"' in html
    assert 'id="album-edit-execute-btn"' in html
    assert 'id="albumartist-edit-preview-btn"' in html
    assert 'id="albumartist-edit-execute-btn"' in html


@pytest.mark.asyncio
async def test_artist_detail_page_wires_existing_album_edit_endpoints(client):
    """Auftrag §13/§15 (CC-AC-3): Album bearbeiten ruft ausschliesslich
    den bestehenden Endpunkt auf, keine neue Ausfuehrungslogik."""
    html = (await client.get("/library/Bausa")).text

    assert "/api/v1/admin/maintenance/album-edit/preview?" in html
    assert '"/api/v1/admin/maintenance/album-edit/execute"' in html


@pytest.mark.asyncio
async def test_artist_detail_page_wires_existing_albumartist_edit_endpoints(client):
    html = (await client.get("/library/Bausa")).text

    assert "/api/v1/admin/maintenance/albumartist-edit/preview?" in html
    assert '"/api/v1/admin/maintenance/albumartist-edit/execute"' in html


# @pytest.mark.asyncio
# async def test_artist_detail_page_has_album_pickers_not_free_text_path(client):
#     """Auftrag §63-67 (CC-AC-3): Album-Auswahl per Picker (<select>),
#     kein Freitext-Pfadfeld wie bei "Titel bearbeiten"."""
#     html = (await client.get("/library/Bausa")).text
#
#     assert '<select id="album-edit-album-select">' in html
#     assert '<select id="albumartist-edit-album-select">' in html
#
#
@pytest.mark.asyncio
async def test_artist_detail_page_album_picker_reuses_artists_overview_data(client):
    """Auftrag §7/§63-67: KEINE neue Datenquelle — der Album-Picker wird
    aus derselben artists-overview/{artist}-Antwort befuellt, die auch
    fuer die Alben-/Track-Anzeige laedt (kein zusaetzlicher Fetch)."""
    html = (await client.get("/library/Bausa")).text

    assert "function _artistAlbumOptions(artist, body)" in html
    assert "_populateAlbumPickers(body)" in html


@pytest.mark.asyncio
async def test_artist_detail_page_album_picker_includes_singles(client):
    """Regression Auftrag §16: Artists mit ausschliesslich Singles
    (album_directory fehlt) duerfen im Picker nicht leer bleiben —
    Singles werden individuell aus body.tracks abgeleitet, nicht als
    ein gemeinsamer Bulk-Kontext."""
    html = (await client.get("/library/Bausa")).text

    assert "t.album_directory" in html
    assert 't.extension !== ".m4a"' in html


@pytest.mark.asyncio
async def test_artist_detail_page_album_edit_confirms_before_write(client):
    """Auftrag §25 (Preview->Confirm->Execute): die zwei neuen Aktionen
    muessen jeweils ihre EIGENE window.confirm()-Bestaetigung vor dem
    Execute-Request ausloesen, nicht nur irgendeine der bereits
    bestehenden drei (test_..._confirms_before_write_actions oben zaehlt
    nur pauschal >= 3, ohne die neuen Aktionen einzeln zu pruefen)."""
    html = (await client.get("/library/Bausa")).text

    assert html.count("window.confirm(") >= 5
    album_edit_fn = html.split("async function executeAlbumEdit()")[1].split("async function ")[0]
    assert "window.confirm(" in album_edit_fn
    albumartist_edit_fn = html.split("async function executeAlbumArtistEdit()")[1].split("async function ")[0]
    assert "window.confirm(" in albumartist_edit_fn


@pytest.mark.asyncio
async def test_artist_detail_page_reloads_album_preview_after_execute(client):
    html = (await client.get("/library/Bausa")).text

    assert html.count("loadAlbumEditPreview()") >= 2
    assert html.count("loadAlbumArtistEditPreview()") >= 2


@pytest.mark.asyncio
async def test_artist_detail_page_album_edit_disables_execute_after_input_changes(client):
    html = (await client.get("/library/Bausa")).text

    assert '["album-edit-album-select", "album-edit-new-album"].forEach' in html
    assert '["albumartist-edit-album-select", "albumartist-edit-new-albumartist"].forEach' in html


# ─────────────────────────────────────────────────────────────────────────
# GET /library/{artist} — Library-Wartung (CC-AC-4)
# ─────────────────────────────────────────────────────────────────────────
#
# Reine Verdrahtung der bereits produktiven Endpunkte aus
# admin_maintenance.py (Artist-Casing, Legacy-Genre-Cleanup — eigene
# Test-Suite: test_control_center_admin_maintenance_api.py) und jobs.py
# (L2/L3 — eigene Test-Suite: test_control_center_jobs_api.py). Hier wird
# nur geprueft, dass das Artist-Detail-Template sie tatsaechlich
# verdrahtet, Genre-Revalidierung bewusst KEINEN Button bekommt (kein
# CC-Endpunkt vorhanden), und die Buttons hinter derselben
# Admin-Sichtbarkeitsschranke wie die CC-AC-2-/CC-AC-3-Panels stehen.


@pytest.mark.asyncio
async def test_artist_detail_page_has_maintenance_panel_hidden_by_default(client):
    html = (await client.get("/library/Bausa")).text

    assert 'id="artist-maintenance-panel" hidden' in html


@pytest.mark.asyncio
async def test_artist_detail_page_maintenance_gated_by_access_level(client):
    html = (await client.get("/library/Bausa")).text

    assert 'getElementById("artist-maintenance-panel").hidden = !isAdmin' in html


@pytest.mark.asyncio
async def test_artist_detail_page_maintenance_panel_is_collapsed_details(client):
    """CC-AC-7: Library-Wartung ist initial eingeklappt (natives
    <details>, kein open-Attribut)."""
    html = (await client.get("/library/Bausa")).text

    panel = html.split('id="artist-maintenance-panel"', 1)[1].split("</section>", 1)[0]
    assert "<details>" in panel
    assert "<details open>" not in panel


@pytest.mark.asyncio
async def test_artist_detail_page_has_maintenance_buttons(client):
    html = (await client.get("/library/Bausa")).text

    assert 'id="artist-casing-preview-btn"' in html
    assert 'id="artist-casing-execute-btn"' in html
    assert 'id="legacy-genre-cleanup-preview-btn"' in html
    assert 'id="legacy-genre-cleanup-execute-btn"' in html
    assert 'id="repair-l2-btn"' in html
    assert 'id="repair-l3-btn"' in html


@pytest.mark.asyncio
async def test_artist_detail_page_wires_existing_artist_casing_endpoints(client):
    """Auftrag CC-AC-4 §17: ruft ausschliesslich den bestehenden
    admin_maintenance-Endpunkt auf, keine neue Ausfuehrungslogik."""
    html = (await client.get("/library/Bausa")).text

    assert "/api/v1/admin/maintenance/artist-casing/preview?" in html
    assert "/api/v1/admin/maintenance/artist-casing/execute?" in html


@pytest.mark.asyncio
async def test_artist_detail_page_wires_existing_legacy_genre_cleanup_endpoints(client):
    html = (await client.get("/library/Bausa")).text

    assert "/api/v1/admin/maintenance/legacy-genre-cleanup/preview?" in html
    assert "/api/v1/admin/maintenance/legacy-genre-cleanup/execute?" in html


@pytest.mark.asyncio
async def test_artist_detail_page_wires_existing_repair_level_job_endpoints(client):
    """L2/L3 laufen als bestehender Job-Typ (services/jobs/), kein
    synchroner Preview->Execute wie die uebrigen Maintenance-Aktionen."""
    html = (await client.get("/library/Bausa")).text

    assert "/api/v1/jobs/repair-level${level" in html
    assert "/api/v1/jobs/${encodeURIComponent(jobId)}" in html


@pytest.mark.asyncio
async def test_artist_detail_page_maintenance_uses_artist_context_not_free_text(client):
    """Auftrag §12: der Artist-Kontext (aus dem Pfad) wird implizit
    mitgegeben - kein eigenes Freitext-Artist-Feld wie im generischen
    admin.html-Formular bzw. der Repair-Plan-Liste auf /health."""
    html = (await client.get("/library/Bausa")).text

    maintenance_section = html.split('id="artist-maintenance-panel"', 1)[1].split("</section>", 1)[0]
    assert "<input" not in maintenance_section
    assert html.count("currentArtistFromPath()") >= 17


@pytest.mark.asyncio
async def test_artist_detail_page_genre_revalidation_has_no_dead_button(client):
    """Auftrag CC-AC-4-SCOPE-HINWEIS: Genre-Revalidierung existiert nur
    als Telegram-Flow, dafuer wird KEIN neuer Control-Center-Endpunkt
    gebaut - Hinweistext statt totem Button."""
    html = (await client.get("/library/Bausa")).text

    assert "Genre revalidieren" in html
    assert 'id="genre-revalidate-preview-btn"' not in html
    assert 'id="genre-revalidate-execute-btn"' not in html
    assert "nur in Telegram" in html


@pytest.mark.asyncio
async def test_artist_detail_page_repair_jobs_have_no_cancel_button(client):
    """Kooperatives Abbrechen ist fuer repair_level2/repair_level3
    wirkungslos (control_center/routers/jobs.py) - identische
    Einschraenkung wie test_health_js_level23_has_no_cancel_function."""
    html = (await client.get("/library/Bausa")).text

    assert "cancelArtistRepairJob" not in html
    assert 'id="repair-l2-cancel-btn"' not in html
    assert 'id="repair-l3-cancel-btn"' not in html


@pytest.mark.asyncio
async def test_artist_detail_page_repair_job_confirm_mentions_duration_and_musicbrainz(client):
    """SCOPE-HINWEIS: Confirm-Dialog muss auf laengere Laufzeit hinweisen
    (L2/L3 laufen asynchron als Job, anders als die synchronen
    Maintenance-Aktionen) sowie bei L3 auf MusicBrainz/Netzwerk."""
    html = (await client.get("/library/Bausa")).text

    assert "kann einige Minuten dauern" in html or "Kann einige Minuten dauern" in html
    assert "MusicBrainz" in html


@pytest.mark.asyncio
async def test_artist_detail_page_repair_job_polls_every_second(client):
    html = (await client.get("/library/Bausa")).text

    assert "setInterval(() => _pollArtistRepairJob(_artistRepairJobId), 1000)" in html


# ─────────────────────────────────────────────────────────────────────────
# GET /library/{artist} — Track Detail Drawer (CC-AC-9, Track-Centric
# Library Actions)
# ─────────────────────────────────────────────────────────────────────────
#
# Auftrag §19: mindestens Track UI, Track Drawer, Metadata, Actions,
# Preview/Execute-Erhalt, Accessibility abdecken. Wie die uebrigen Tests
# in dieser Datei rein string-basiert gegen das echte gerenderte Template
# (kein Headless-Browser) - siehe Playwright-Hinweis im Abschlussbericht.


@pytest.mark.asyncio
async def test_artist_detail_tracks_are_interactive(client):
    """Auftrag §4: Track-Zeilen sind native <button>, keine <div
    onclick>-Pseudo-Buttons - Enter/Space funktionieren ohne eigene
    Tastatur-Nachbildung."""
    html = (await client.get("/library/Bausa")).text

    assert 'class="row-item track-row"' in html
    assert "data-track-path=" in html
    assert "openTrackDrawer(track)" in html


@pytest.mark.asyncio
async def test_artist_detail_has_track_detail_context(client):
    html = (await client.get("/library/Bausa")).text

    assert 'id="track-drawer-overlay" class="drawer-overlay" hidden' in html
    assert 'id="track-drawer"' in html
    assert 'id="track-drawer-title"' in html
    assert 'id="track-drawer-info"' in html
    assert 'id="track-drawer-health"' in html
    assert 'id="track-drawer-actions"' in html


@pytest.mark.asyncio
async def test_track_detail_context_displays_available_metadata(client):
    """Auftrag §8: nur tatsaechlich vorhandene, bereits unterstuetzte
    TrackSchema-Felder - keine neuen Backend-Felder fuer die UI."""
    html = (await client.get("/library/Bausa")).text

    info_fn = html.split("function _trackDrawerFieldsHtml(t) {", 1)[1].split("\n  }", 1)[0]
    for field in (
        "t.title", "t.artist", "t.album", "t.album_artist", "t.genre",
        "t.year", "t.track_number", "t.disc_number",
        "t.mb_recording_id", "t.mb_release_id", "t.isrc",
    ):
        assert field in info_fn


@pytest.mark.asyncio
async def test_track_detail_context_shows_health_from_existing_issue_codes(client):
    """Auftrag §7: Health kommt ausschliesslich aus dem vorhandenen
    TrackSchema.issue_codes-Feld - keine erfundene "Metadata
    vollstaendig"-Behauptung, neutrale Formulierung ohne offene Probleme."""
    html = (await client.get("/library/Bausa")).text

    assert "t.issue_codes.length" in html
    assert "_TRACK_ISSUE_LABELS" in html
    assert "Keine bekannten Probleme laut letztem Health-Scan" in html
    assert "Metadata vollständig" not in html


@pytest.mark.asyncio
async def test_track_detail_context_exposes_existing_actions(client):
    """Auftrag §9/§11: buendelt die bestehenden Manual-Metadata-Editing-
    Aktionen (CC-AC-2/3) im Track-Kontext - keine neue Ausfuehrungslogik."""
    html = (await client.get("/library/Bausa")).text

    assert 'data-track-action="${action}"' in html
    assert "title: _trackDrawerEditTitle," in html
    assert "artist: _trackDrawerEditArtist," in html
    assert '"album-edit-album-select", "album-edit-new-album"' in html
    assert '"albumartist-edit-album-select", "albumartist-edit-new-albumartist"' in html
    assert "genre: _trackDrawerEditGenre," in html
    assert "maintenance: _trackDrawerOpenMaintenance," in html


@pytest.mark.asyncio
async def test_track_action_preserves_preview_execute_flow(client):
    """Auftrag §10: die Drawer-Aktionen fuehren selbst nichts aus - sie
    befuellen die bestehenden Formularfelder und rufen ausschliesslich
    die bereits vorhandenen, andernorts getesteten load*Preview()-
    Funktionen auf. Keine neue fetch()/POST-Ausfuehrung im Drawer-Block."""
    html = (await client.get("/library/Bausa")).text

    drawer_block = html.split("const _TRACK_ISSUE_LABELS", 1)[1].split("function initPage()", 1)[0]
    assert "loadTitleEditPreview();" in drawer_block
    assert "loadGenreManagePreview();" in drawer_block
    assert "fetch(" not in drawer_block
    assert "method: \"POST\"" not in drawer_block


@pytest.mark.asyncio
async def test_track_detail_context_has_accessible_dialog_semantics(client):
    """Auftrag §16: role=dialog/aria-modal nativ im Markup, Escape
    schliesst, Tab-Fokus bleibt im Dialog, Fokus kehrt zur ausloesenden
    Track-Zeile zurueck."""
    html = (await client.get("/library/Bausa")).text

    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="track-drawer-title"' in html
    assert 'event.key === "Escape"' in html
    assert "closeTrackDrawer()" in html
    assert 'event.key !== "Tab"' in html
    assert "_trackDrawerTriggerEl.focus()" in html


@pytest.mark.asyncio
async def test_track_drawer_actions_gated_by_admin_access(client):
    """Identische UX-Schranke wie die bestehenden Metadata-/Wartungs-
    Panels (Auftrag CC-AC-2-Scope) - kein separater Admin-Check-Pfad."""
    html = (await client.get("/library/Bausa")).text

    assert "_trackDrawerIsAdmin = isAdmin;" in html
    assert "Aktionen benötigen Admin-Berechtigung" in html


@pytest.mark.asyncio
async def test_track_drawer_album_actions_require_m4a_scope(client):
    """Auftrag §11: Album-/Albuminterpret-Aktionen nur anbieten, wenn
    album_targets() (services/library_repair/maintenance_service.py)
    ueberhaupt einen Treffer liefern koennte - identische .m4a-
    Einschraenkung wie der bestehende Album-Picker (_artistAlbumOptions())."""
    html = (await client.get("/library/Bausa")).text

    assert 'extension === ".m4a"' in html


# ─────────────────────────────────────────────────────────────────────────
# GET /metadata — Genre setzen (erste schreibende Metadata-Fähigkeit)
# ─────────────────────────────────────────────────────────────────────────


# @pytest.mark.asyncio
# async def test_metadata_page_has_genre_set_hint_block(client):
#     """CC-AC-Cleanup: das Formular wurde durch einen Hinweis-Block mit
#     Deep-Link auf /library ersetzt (kanonisch jetzt im Artist-Kontext,
#     library_artist_detail.html::genre-manage-*). Der Endpunkt selbst
#     (/set-genre) bleibt unveraendert aktiv, nur hier nicht mehr verdrahtet."""
#     html = (await client.get("/metadata")).text
#
#     assert "Genre setzen" in html
#     assert "Genre-Verwaltung" in html
#     assert 'id="genre-set-artist-input"' not in html
#     assert 'id="genre-preview-btn"' not in html
#     assert 'id="genre-set-execute-btn"' not in html
#     assert '<a href="/library">→ Zu /library (Artist wählen)</a>' in html
#
#
# # ─────────────────────────────────────────────────────────────────────────
# # GET /statistics
# # ─────────────────────────────────────────────────────────────────────────
#
#
@pytest.mark.asyncio
async def test_statistics_page_has_all_panels(client):
    html = (await client.get("/statistics")).text
    js = (await client.get("/static/pages/statistics.js")).text

    assert 'id="kpi-header"' in html
    assert 'id="monthly-artists"' in html
    assert 'id="all-time-genres"' in html
    assert 'id="music-dna-content"' in html
    assert 'id="music-timeline"' in html

    assert "/api/v1/statistics/me?period=" in js
    assert "/api/v1/statistics/me/genres" in js
    assert "/api/v1/statistics/me/music-dna" in js
    assert "/api/v1/statistics/me/timeline" in js

    assert "renderMonthlyArtists" in js
    assert "renderAllTimeGenres" in js
    assert "renderMusicDna" in js
    assert "renderMusicTimeline" in js
    assert "_loadInto(" in js


# ─────────────────────────────────────────────────────────────────────────
# GET /health
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_page_has_library_and_navidrome_checks(client):
    """ui_prompt.txt Abschnitt 21: nur tatsaechlich vorhandene Checks,
    keine vorgetaeuschten Health-Werte."""
    html = (await client.get("/health")).text

    assert 'id="health-tiles"' in html
    assert 'id="navidrome-status"' in html

    health_js = (await client.get("/static/pages/health.js")).text
    assert "/api/v1/library/health" in health_js
    assert "/api/v1/navidrome/status" in health_js


# ─────────────────────────────────────────────────────────────────────────
# GET /navidrome
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_navidrome_page_has_status_panel(client):
    html = (await client.get("/navidrome")).text

    assert 'id="navidrome-status"' in html
    assert "/api/v1/navidrome/status" in html


# ─────────────────────────────────────────────────────────────────────────
# GET /logs — Platzhalter, kein Backend vorhanden (Master-Prompt Regel 38)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logs_page_has_filter_and_content_panels(client):
    html = (await client.get("/logs")).text

    assert 'id="logs-source-select"' in html
    assert 'id="logs-level-select"' in html
    assert 'id="logs-component-input"' in html
    assert 'id="logs-search-input"' in html
    assert 'id="logs-filter-btn"' in html
    assert 'id="logs-content"' in html
    assert "/api/v1/logs" in html
    assert "loadLogs" in html
    assert "renderLogs" in html


@pytest.mark.asyncio
async def test_logs_page_has_no_time_range_job_or_user_filter(client):
    """Master-Prompt Regel 38: kein Zeitraum-/Job-/User-Filter, da die
    zugrundeliegenden Logzeilen weder ein Datum noch eine strukturierte
    Job-/User-Korrelation enthalten (siehe services/logs/reader.py) -
    ein solcher Filter wuerde eine nicht vorhandene Genauigkeit
    vortaeuschen."""
    html = (await client.get("/logs")).text

    assert 'id="logs-job-select"' not in html
    assert 'id="logs-user-select"' not in html
    assert 'id="logs-date-range"' not in html


# ─────────────────────────────────────────────────────────────────────────
# GET /admin
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_page_has_users_panel(client):
    html = (await client.get("/admin")).text
    js = (await client.get("/static/pages/admin.js")).text

    assert 'id="admin-users-content"' in html
    assert "loadAdminUsers" in js


@pytest.mark.asyncio
async def test_admin_page_has_cross_user_statistics_wiring(client):
    """Cross-User-Admin-Ansicht: anklickbarer navidrome_user pro Zeile
    zeigt dessen Statistik (GET /api/v1/statistics/{navidrome_username})."""
    html = (await client.get("/admin")).text
    js = (await client.get("/static/pages/admin.js")).text

    assert 'id="admin-user-stats-content"' in html
    assert "view-stats-btn" in js
    assert "loadUserStatsForAdmin" in js
    assert "data-navidrome-user" in js


# @pytest.mark.asyncio
# async def test_admin_page_has_library_maintenance_hint_block(client):
#     """CC-AC-Cleanup: die vier vormals dupliziert vorhandenen
#     Library-Maintenance-Formulare (Artist Casing, Legacy Genre Cleanup,
#     Artist umbenennen, Titel bearbeiten) wurden durch einen Hinweis-Block
#     mit Deep-Link auf /library ersetzt (kanonisch jetzt im Artist-Kontext,
#     library_artist_detail.html). Die Endpunkte selbst
#     (admin/maintenance/*) bleiben unveraendert aktiv, nur hier nicht mehr
#     verdrahtet."""
#     html = (await client.get("/admin")).text
#
#     assert "Library-Maintenance" in html
#     assert 'id="mnt-artist-casing-artist"' not in html
#     assert 'id="mnt-legacy-genre-cleanup-artist"' not in html
#     assert 'id="mnt-artist-rename-artist"' not in html
#     assert 'id="mnt-title-edit-artist"' not in html
#     assert "MAINTENANCE_ACTIONS" not in html
#     assert '<a href="/library">→ Zu /library (Artist wählen)</a>' in html
#
#
# # ─────────────────────────────────────────────────────────────────────────
# # GET /library — Library Dashboard UX (CC-AC-8): Health-KPI, Health-/
# # Attention-Panel, severity-getrennte Attention-Daten, Health-asc-
# # Sortierung.
# # ─────────────────────────────────────────────────────────────────────────
#
#
@pytest.mark.asyncio
async def test_library_page_has_health_kpi_tile(client):
    """CC-AC-8 Schritt 1: vierte KPI-Kachel 'Health' + Status-Label.
    Nutzt health.score/health.status aus derselben /health/cached-Antwort
    wie die drei bestehenden Kacheln - keine zusaetzliche Anfrage."""
    html = (await client.get("/library")).text

    assert 'id="library-kpi-health"' in html
    assert 'id="library-kpi-health-status"' in html


# @pytest.mark.asyncio
# async def test_library_page_has_health_and_attention_panels(client):
#     """CC-AC-8 Schritt 2: zwei neue Panels unter der KPI-Zeile, in einem
#     2-Spalten-Grid (Desktop) / untereinander (Mobile)."""
#     html = (await client.get("/library")).text
#
#     assert "library-dashboard-grid" in html
#     assert 'id="library-health-panel"' in html
#     assert 'id="library-attention-panel"' in html
#
#
@pytest.mark.asyncio
async def test_library_page_attention_uses_severity_data(client):
    """CC-AC-8 Schritt 3: Attention liest issues_by_severity (autoritative
    Quelle) + filtert die Top-Warnungen gegen eine statische
    _WARNING_CODES-Map (verifiziert gegen services/library_health/
    issues.py, Severity.WARNING)."""
    html = (await client.get("/library")).text

    assert "_renderLibraryAttention" in html
    assert "_renderLibraryHealthSnapshot" in html
    assert "issues_by_severity" in html
    assert "_WARNING_CODES" in html


@pytest.mark.asyncio
async def test_library_page_has_health_asc_sort_option(client):
    """CC-AC-8 Schritt 4: Sortier-Option 'Health (niedrig -> hoch)' plus
    Comparator. Bestehende health-Option bleibt (hoch -> niedrig)."""
    html = (await client.get("/library")).text

    assert 'value="health"' in html
    assert 'value="health_asc"' in html
    assert "health_asc:" in html  # Comparator-Eintrag


# =====================================================================
# CC-LOGGER-L6 — Logger-Verwaltungs-Seite
# =====================================================================
#
# Reine UI-Rendering-Tests: das Template und die Sidebar-Navigation
# werden auf die erwarteten Marker geprüft. Die eigentliche Panel-Logik
# lebt in logger.js und wird hier NICHT ausgeführt (kein Browser-
# Runtime-Test verfügbar — identisches Vorgehen wie in allen anderen
# UI-Tests dieser Suite).


@pytest.mark.anyio
async def test_logger_page_renders(client) -> None:
    r = await client.get("/logger")
    assert r.status_code == 200
    html = r.text
    assert "Logger" in html
    assert "MusicBot Control Center" in html


@pytest.mark.anyio
async def test_logger_page_has_all_panel_markers(client) -> None:
    r = await client.get("/logger")
    html = r.text
    # Panel 1 — Runtime
    assert "logger-runtime-kpi" in html
    assert "logger-runtime-content" in html
    assert "logger-runtime-refresh-btn" in html
    # Panel 2 — Config
    assert "logger-config-content" in html
    # Panel 3 — Diff
    assert "logger-diff-content" in html
    # Panel 4 — Apply
    assert "logger-apply-btn" in html
    assert "logger-apply-status" in html


@pytest.mark.anyio
async def test_logger_page_references_js_file(client) -> None:
    r = await client.get("/logger")
    assert "/static/pages/logger.js" in r.text


@pytest.mark.anyio
async def test_logger_sidebar_entry_present_on_all_pages(client) -> None:
    # Der Sidebar-Eintrag „Logger" muss auf allen Seiten erscheinen.
    for path in ("/", "/logs", "/admin", "/navidrome"):
        r = await client.get(path)
        assert r.status_code == 200, f"{path} lieferte {r.status_code}"
        assert "/logger" in r.text, f"{path}: /logger-Link fehlt in Sidebar"
        assert "Logger</span>" in r.text, f"{path}: Logger-Titel fehlt"


@pytest.mark.anyio
async def test_logger_sidebar_entry_active_only_on_logger_page(client) -> None:
    r = await client.get("/logger")
    # Der Eintrag muss die active-Klasse tragen.
    html = r.text
    # Suche den /logger-Link und prüfe auf active im selben nav-link.
    idx = html.find('href="/logger"')
    assert idx != -1, "/logger-Link nicht gefunden"
    # Prüfe die nächste Zeile (class-Attribut folgt unmittelbar)
    snippet = html[idx:idx + 200]
    assert "nav-link active" in snippet, f"active-Klasse fehlt: {snippet!r}"

    # Auf einer anderen Seite: /logger nicht active
    r2 = await client.get("/logs")
    html2 = r2.text
    idx2 = html2.find('href="/logger"')
    assert idx2 != -1
    snippet2 = html2[idx2:idx2 + 200]
    assert "nav-link active" not in snippet2, "Logger-Link ist faelschlich active auf /logs"


@pytest.mark.anyio
async def test_logger_page_warns_about_restart(client) -> None:
    """Die Seite muss klar sagen, dass Apply ein Bot-Restart ist."""
    r = await client.get("/logger")
    html = r.text
    assert "startet den Bot neu" in html
    # Kein Live-Control-Versprechen:
    assert "Logger live" not in html
