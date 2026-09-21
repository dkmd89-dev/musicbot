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

import httpx
import pytest
import pytest_asyncio

from config import Config

ALL_PAGES = [
    "/", "/downloads", "/library", "/metadata", "/statistics", "/findings",
    "/repairs", "/jobs", "/health", "/navidrome", "/logs", "/admin",
]


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


@pytest.mark.asyncio
async def test_overview_nav_link_is_marked_active_on_overview_page(client):
    html = (await client.get("/")).text

    assert 'href="/" class="nav-link active"' in html


@pytest.mark.asyncio
async def test_findings_nav_link_is_marked_active_on_findings_page(client):
    html = (await client.get("/findings")).text

    assert 'href="/findings" class="nav-link active"' in html
    # Andere Seiten bleiben auf der Findings-Seite nicht "active":
    assert 'href="/" class="nav-link active"' not in html


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
    html = (await client.get("/")).text

    # PR #285 (0337713) hat das Overview-Dashboard umgebaut:
    # health-tiles, navidrome-status, kpi-grid und active-jobs-summary
    # wurden durch die neue System-Status-Bar + 3-Spalten-Statuszeile
    # ersetzt (kein Bug, beabsichtigtes Redesign).
    assert 'id="system-status-value"' in html
    assert 'id="status-library-value"' in html
    assert 'id="status-navidrome-value"' in html
    assert 'id="status-jobs-value"' in html
    assert 'id="attention-panel"' in html
    assert 'id="recent-activity-content"' in html


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
    html = (await client.get("/")).text

    assert 'href="/findings"' in html
    assert 'href="/repairs"' in html
    assert 'href="/jobs"' in html
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


@pytest.mark.asyncio
async def test_library_page_has_artists_overview_panel(client):
    html = (await client.get("/library")).text

    assert "🎤 Artists" in html
    assert 'id="artist-search"' in html
    assert 'id="artists-overview-content"' in html


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


@pytest.mark.asyncio
async def test_library_page_has_kpi_tiles(client):
    """KPI-Zeile nutzt den bestehenden Cache-Read-Endpunkt
    GET /api/v1/library/health/cached (Auftrag §5) - keine neue API,
    keine Client-Aggregation."""
    html = (await client.get("/library")).text

    assert 'id="library-kpi-tiles"' in html
    assert 'class="tiles" id="library-kpi-tiles"' in html
    assert "loadLibraryKpis" in html
    assert "/api/v1/library/health/cached" in html


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


@pytest.mark.asyncio
async def test_artist_detail_page_keeps_library_nav_active(client):
    """page_id="library" haelt den Sidebar-Eintrag auf der Artist-
    Detailseite aktiv (Auftrag: Artist ist eine Unterseite von Library,
    kein eigener Sidebar-Eintrag)."""
    html = (await client.get("/library/Bausa")).text

    assert 'href="/library" class="nav-link active"' in html


@pytest.mark.asyncio
async def test_artist_detail_page_has_breadcrumb_and_back_link(client):
    html = (await client.get("/library/Bausa")).text

    assert 'class="breadcrumb"' in html
    assert 'href="/library">📚 Library' in html
    assert "Zurück zu Artists" in html


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
    "Netzwerkfehler"-Wording wie beim aequivalenten Job-Start auf
    repairs.html::startLevel23Job()."""
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


@pytest.mark.asyncio
async def test_artist_detail_page_has_album_pickers_not_free_text_path(client):
    """Auftrag §63-67 (CC-AC-3): Album-Auswahl per Picker (<select>),
    kein Freitext-Pfadfeld wie bei "Titel bearbeiten"."""
    html = (await client.get("/library/Bausa")).text

    assert '<select id="album-edit-album-select">' in html
    assert '<select id="albumartist-edit-album-select">' in html


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
    admin.html-Formular bzw. der Plan-Liste auf repairs.html."""
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
    Einschraenkung wie repairs.html::test_repairs_page_level23_has_no_cancel_button."""
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
# GET /metadata — Genre setzen (erste schreibende Metadata-Fähigkeit)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metadata_page_has_genre_set_hint_block(client):
    """CC-AC-Cleanup: das Formular wurde durch einen Hinweis-Block mit
    Deep-Link auf /library ersetzt (kanonisch jetzt im Artist-Kontext,
    library_artist_detail.html::genre-manage-*). Der Endpunkt selbst
    (/set-genre) bleibt unveraendert aktiv, nur hier nicht mehr verdrahtet."""
    html = (await client.get("/metadata")).text

    assert "Genre setzen" in html
    assert "Genre-Verwaltung" in html
    assert 'id="genre-set-artist-input"' not in html
    assert 'id="genre-preview-btn"' not in html
    assert 'id="genre-set-execute-btn"' not in html
    assert '<a href="/library">→ Zu /library (Artist wählen)</a>' in html


# ─────────────────────────────────────────────────────────────────────────
# GET /statistics
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_statistics_page_has_all_panels(client):
    html = (await client.get("/statistics")).text

    # PR #285 (f3ab155) hat das Statistics-Dashboard umgebaut:
    # statistics-content/genre-stats-content wurden umbenannt,
    # die load*-Wrapper durch direkte _loadInto(...)-Aufrufe ersetzt,
    # renderGenreStats -> renderAllTimeGenres, kpi-header neu.
    # Kein Bug, beabsichtigtes Redesign.
    assert 'id="kpi-header"' in html
    assert 'id="monthly-artists"' in html
    assert 'id="all-time-genres"' in html
    assert 'id="music-dna-content"' in html
    assert "/api/v1/statistics/me" in html
    assert "/api/v1/statistics/me/genres" in html
    assert "/api/v1/statistics/me/music-dna" in html
    assert "renderMonthlyArtists" in html
    assert "renderAllTimeGenres" in html
    assert "renderMusicDna" in html
    assert "_loadInto(" in html


# ─────────────────────────────────────────────────────────────────────────
# GET /findings
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_findings_page_fetches_real_api_endpoints(client):
    html = (await client.get("/findings")).text

    assert "/api/v1/library/findings" in html
    assert 'id="findings-content"' in html


@pytest.mark.asyncio
async def test_findings_page_has_accept_wiring(client):
    """Accept-Button-Verdrahtung fuer den ersten schreibenden Endpunkt
    (POST .../accept) - Event-Delegation auf dem Content-Container,
    damit re-gerenderte Buttons nach jedem Poll weiter funktionieren."""
    html = (await client.get("/findings")).text

    assert "acceptFinding" in html
    assert "accept-btn" in html
    assert "/accept" in html


@pytest.mark.asyncio
async def test_findings_page_has_accepted_toggle_and_unaccept_wiring(client):
    html = (await client.get("/findings")).text

    assert 'id="accepted-findings-toggle"' in html
    assert 'id="accepted-findings-content"' in html
    assert "/api/v1/library/findings/accepted" in html
    assert "unacceptFinding" in html
    assert "unaccept-btn" in html
    assert "/unaccept" in html


@pytest.mark.asyncio
async def test_findings_page_escapes_untrusted_text(client):
    """Sicherheitsnachtrag: Titel/Artist/Pfad/Message-Felder werden vor
    dem innerHTML-Einsatz escaped (XSS-Schutz)."""
    html = (await client.get("/findings")).text

    assert "_escapeHtml(" in html


# ─────────────────────────────────────────────────────────────────────────
# GET /repairs — Repair-Plan (SAFE_AUTOMATIC) + L2/L3
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repairs_page_has_dedicated_manual_trigger(client):
    """Repair-Plan ist bewusst NICHT im 30s-Polling (voller Library-Scan)
    - es muss einen eigenen manuellen Button geben, keinen impliziten
    Auto-Load beim Seitenaufruf."""
    html = (await client.get("/repairs")).text

    assert 'id="repair-plan-btn"' in html


@pytest.mark.asyncio
async def test_repairs_page_start_button_disabled_until_plan_loaded(client):
    """Der Start-Button fuer die erste dateiveraendernde Faehigkeit
    (repair_safe_automatic) darf nicht klickbar sein, bevor eine echte,
    aktuelle Kandidatenzahl fuer den Bestaetigungsdialog vorliegt."""
    html = (await client.get("/repairs")).text

    assert 'id="repair-start-btn" class="small" disabled' in html


@pytest.mark.asyncio
async def test_repairs_page_job_ui_wiring_present(client):
    html = (await client.get("/repairs")).text

    assert "startRepairJob" in html
    assert "cancelRepairJob" in html
    assert "/api/v1/jobs/repair-safe-automatic" in html
    assert 'id="repair-cancel-btn"' in html
    assert 'id="repair-job-content"' in html


@pytest.mark.asyncio
async def test_repairs_page_confirm_dialog_mentions_backup_and_files(client):
    """Master-Prompt Regel 11/32: Bestaetigung vor einer destruktiven
    Operation muss verstaendlich machen, was passiert."""
    html = (await client.get("/repairs")).text

    assert "Backup" in html
    assert "Dateien in der Library" in html


@pytest.mark.asyncio
async def test_repairs_page_plan_text_distinguishes_safe_automatic_from_total(client):
    html = (await client.get("/repairs")).text

    assert "davon" in html
    assert "SAFE_AUTOMATIC (per Button unten ausführbar)" in html


@pytest.mark.asyncio
async def test_repairs_page_has_level23_panel_with_dedicated_manual_trigger(client):
    html = (await client.get("/repairs")).text

    assert "L2/L3-Reparaturen" in html
    assert 'id="level23-plan-btn"' in html
    assert 'id="level23-artists-content"' in html
    assert 'id="level23-job-content"' in html


@pytest.mark.asyncio
async def test_repairs_page_level23_ui_wiring_present(client):
    html = (await client.get("/repairs")).text

    assert "loadLevel23Artists" in html
    assert "startLevel23Job" in html
    assert "renderLevel23Artists" in html
    assert "/api/v1/library/repair-plan/by-artist" in html
    assert "/api/v1/jobs/repair-level" in html
    assert "level23-btn" in html


@pytest.mark.asyncio
async def test_repairs_page_level23_has_no_cancel_button(client):
    """Kooperatives Abbrechen ist fuer repair_level2/repair_level3
    wirkungslos - ein Abbrechen-Button wuerde eine nicht existierende
    Faehigkeit vortaeuschen (Master-Prompt Regel 39/38)."""
    html = (await client.get("/repairs")).text

    assert "cancelLevel23Job" not in html
    assert 'id="level23-cancel-btn"' not in html


@pytest.mark.asyncio
async def test_repairs_page_level23_confirm_dialog_mentions_musicbrainz(client):
    html = (await client.get("/repairs")).text

    assert "wirklich starten für" in html
    assert "MusicBrainz" in html


# ─────────────────────────────────────────────────────────────────────────
# GET /jobs — neues Job Center (ui_prompt.txt Abschnitt 17), nutzt die
# bereits bestehende Jobs-API (GET /api/v1/jobs), bisher ohne eigene
# Listen-Darstellung.
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jobs_page_has_job_list_panel(client):
    html = (await client.get("/jobs")).text

    assert 'id="jobs-content"' in html
    assert 'id="jobs-refresh-btn"' in html
    assert "/api/v1/jobs" in html
    assert "loadJobs" in html
    assert "renderJobs" in html


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
    assert "/api/v1/library/health" in html
    assert "/api/v1/navidrome/status" in html


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

    assert 'id="admin-users-content"' in html
    assert "loadAdminUsers" in html


@pytest.mark.asyncio
async def test_admin_page_has_cross_user_statistics_wiring(client):
    """Cross-User-Admin-Ansicht: anklickbarer navidrome_user pro Zeile
    zeigt dessen Statistik (GET /api/v1/statistics/{navidrome_username})."""
    html = (await client.get("/admin")).text

    assert 'id="admin-user-stats-content"' in html
    assert "view-stats-btn" in html
    assert "loadUserStatsForAdmin" in html
    assert "data-navidrome-user" in html


@pytest.mark.asyncio
async def test_admin_page_has_library_maintenance_hint_block(client):
    """CC-AC-Cleanup: die vier vormals dupliziert vorhandenen
    Library-Maintenance-Formulare (Artist Casing, Legacy Genre Cleanup,
    Artist umbenennen, Titel bearbeiten) wurden durch einen Hinweis-Block
    mit Deep-Link auf /library ersetzt (kanonisch jetzt im Artist-Kontext,
    library_artist_detail.html). Die Endpunkte selbst
    (admin/maintenance/*) bleiben unveraendert aktiv, nur hier nicht mehr
    verdrahtet."""
    html = (await client.get("/admin")).text

    assert "Library-Maintenance" in html
    assert 'id="mnt-artist-casing-artist"' not in html
    assert 'id="mnt-legacy-genre-cleanup-artist"' not in html
    assert 'id="mnt-artist-rename-artist"' not in html
    assert 'id="mnt-title-edit-artist"' not in html
    assert "MAINTENANCE_ACTIONS" not in html
    assert '<a href="/library">→ Zu /library (Artist wählen)</a>' in html
