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

    assert 'id="health-tiles"' in html
    assert 'id="navidrome-status"' in html
    assert 'id="kpi-active-jobs"' in html
    assert 'id="kpi-open-findings"' in html
    assert 'id="attention-panel"' in html
    assert 'id="active-jobs-summary"' in html
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
# GET /metadata — Genre setzen (erste schreibende Metadata-Fähigkeit)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metadata_page_has_genre_set_panel(client):
    html = (await client.get("/metadata")).text

    assert "Genre setzen" in html
    assert 'id="genre-set-artist-input"' in html
    assert 'id="genre-preview-btn"' in html
    assert 'id="genre-set-content"' in html
    assert 'id="genre-set-execute-btn" class="small" disabled' in html
    assert "/genre-preview" in html
    assert "/set-genre" in html


@pytest.mark.asyncio
async def test_metadata_page_confirm_dialog_mentions_backup_and_files(client):
    """Master-Prompt Regel 11: verstaendliche Bestaetigung vor der ersten
    Metadata-Bearbeitungs-Ausfuehrung."""
    html = (await client.get("/metadata")).text

    assert "wirklich setzen" in html
    assert "Dateien in der Library" in html


# ─────────────────────────────────────────────────────────────────────────
# GET /statistics
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_statistics_page_has_all_panels(client):
    html = (await client.get("/statistics")).text

    assert 'id="statistics-content"' in html
    assert 'id="genre-stats-content"' in html
    assert 'id="music-dna-content"' in html
    assert "/api/v1/statistics/me" in html
    assert "/api/v1/statistics/me/genres" in html
    assert "/api/v1/statistics/me/music-dna" in html
    assert "loadGenreStats" in html
    assert "loadMusicDna" in html
    assert "renderGenreStats" in html
    assert "renderMusicDna" in html


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
async def test_logs_page_is_honestly_marked_as_not_implemented(client):
    """Master-Prompt Regel 38: keine Funktion vortaeuschen, die
    Backend-seitig nicht existiert - klar als "Not implemented"
    kennzeichnen."""
    html = (await client.get("/logs")).text

    assert "Noch nicht implementiert" in html


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
