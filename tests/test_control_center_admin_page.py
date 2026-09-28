# tests/test_control_center_admin_page.py
# -*- coding: utf-8 -*-
"""
CC-UI Administration — Darstellung nach docs/CONTROL_CENTER_UI_STANDARD.md.

Die echte static/pages/admin.js läuft zusammen mit der echten
static/common.js in node gegen einen Fake-DOM und eine Fake-API (Muster wie
tests/test_control_center_downloads_page.py). Endpunkte und Fachlogik
bleiben unverändert; geprüft werden Darstellung, Bestätigungsdialoge statt
confirm(), Escaping und der Regressionsfall Backup-Job-Status.

Regression (2026-09-28): pollBackupJob() verglich job.status mit
"succeeded"/"failed"/"cancelled", die API liefert aber JobStatus.value in
Großbuchstaben ("SUCCEEDED", ...). Ein erfolgreiches Backup endete dadurch
nach 60 Versuchen mit "Zeitüberschreitung beim Warten auf das Backup.",
ein fehlgeschlagenes ebenso (statt der echten Fehlermeldung).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parent.parent
CC_DIR = ROOT / "control_center"
COMMON_JS = CC_DIR / "static" / "common.js"
ADMIN_JS = CC_DIR / "static" / "pages" / "admin.js"
ADMIN_HTML = CC_DIR / "templates" / "admin.html"
_NODE = shutil.which("node")
needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")

_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    transport = httpx.ASGITransport(app=create_app())
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


# ─────────────────────────────────────────────────────────────────────────
# Template / statisch
# ─────────────────────────────────────────────────────────────────────────


def test_admin_template_and_js_follow_standard():
    js = ADMIN_JS.read_text(encoding="utf-8")
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert not _EMOJI.search(js) and not _EMOJI.search(html)
    assert "window.confirm" not in js and "confirm(" not in js.replace("ccConfirm(", "")
    assert "<svg xmlns" not in js and "<svg xmlns" not in html      # nur Sprite
    assert 'style="' not in js.replace('style="width: ', "") and 'style="' not in html
    assert "row-list" not in js and "empty-note" not in js


@pytest.mark.asyncio
async def test_admin_page_uses_standard_header_sections_and_offcanvas(client):
    html = (await client.get("/admin")).text

    assert '<div class="page-pretitle">Verwaltung</div>' in html
    assert '<use href="#i-settings"/></svg>Administration</h2>' in html
    assert 'id="admin-user-stats-offcanvas"' in html
    stats = html[html.index('id="admin-user-stats-offcanvas"'):]
    assert 'id="admin-user-stats-content"' in stats[: stats.index("</div>\n</div>")]
    for icon in ("robot", "tool", "archive", "copy", "alert", "users", "trash", "books"):
        assert f'id="i-{icon}"' in html, f"Symbol i-{icon} fehlt im gerenderten Sprite"


# ─────────────────────────────────────────────────────────────────────────
# admin.js real ausgeführt
# ─────────────────────────────────────────────────────────────────────────

_HARNESS = r"""
const fs = require("fs");
const [commonPath, jsPath, scenarioJson] = process.argv.slice(2);
const sc = JSON.parse(scenarioJson);
const els = {};
const mkEl = (id) => {
  const cls = new Set(); const attrs = {}; const listeners = {};
  const el = {
    id, hidden: false, textContent: "", innerHTML: "", className: "", style: {}, disabled: false,
    value: "", dataset: {},
    classList: { add: (c) => cls.add(c), remove: (...cs) => cs.forEach((c) => cls.delete(c)),
                 contains: (c) => cls.has(c), toggle: () => {} },
    setAttribute: (k, v) => { attrs[k] = v; }, getAttribute: (k) => attrs[k],
    querySelector: () => null, addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
    appendChild: () => {}, remove: () => {},
    _listeners: listeners,
  };
  return el;
};
global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
global.document = {
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  createElement: () => mkEl("created"),
  addEventListener: () => {},
  documentElement: { getAttribute: () => "dark", setAttribute: () => {} },
  body: { appendChild: () => {}, classList: { toggle() {}, remove() {}, contains: () => false } },
};
(sc.preset || []).forEach((p) => { document.getElementById(p.id)[p.key] = p.value; });
const confirms = [];
global.window = { confirm: (t) => { confirms.push(t); return sc.confirm !== false; } };
const toasts = [];
global.console = { ...console, error: () => {} };
const realSetTimeout = setTimeout;
global.setTimeout = (fn, ms) => realSetTimeout(fn, Math.min(ms || 0, 1));
const calls = [];
const responses = sc.responses;
global.fetch = async (url, opts) => {
  const method = (opts && opts.method) || "GET";
  calls.push({ call: method + " " + url, body: opts && opts.body || null,
               xrw: !!(opts && opts.headers && opts.headers["X-Requested-With"]) });
  const key = method + " " + url.split("?")[0];
  let r = responses[key];
  if (Array.isArray(r)) r = r.length > 1 ? r.shift() : r[0];
  if (!r) r = { status: 500, body: { error: { message: "unerwartet: " + key } } };
  return { status: r.status, ok: r.status >= 200 && r.status < 300,
           text: async () => (r.body === undefined ? "" : JSON.stringify(r.body)),
           json: async () => r.body };
};
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(jsPath, "utf-8")
  + "\n;ccToast = (kind, title, text) => { toasts.push([kind, title, text || ''].join('|')); };";
const api = new Function("toasts", src + "\nreturn { createBackup, deleteBackup, toggleMaintenance, clearDuplicateCache, restartBot, loadUserStatsForAdmin, createWebUser };")(toasts);
const tick = () => new Promise((r) => realSetTimeout(r, 15));
(async () => {
  await tick(); await tick();
  for (const op of sc.ops || []) {
    if (op.op === "call") await api[op.fn](...(op.args || []));
    if (op.op === "callEvent") await api[op.fn]({ preventDefault: () => {} });
    if (op.op === "set") { document.getElementById(op.id)[op.key] = op.value; }
    await tick();
  }
  const out = {};
  for (const [id, e] of Object.entries(els)) out[id] = { html: e.innerHTML, text: e.textContent, className: e.className, hidden: e.hidden, disabled: e.disabled, value: e.value };
  console.log(JSON.stringify({ els: out, calls, confirms, toasts }));
})().catch((e) => { console.error(e); process.exit(1); });
"""

_WHOAMI = {"status": 200, "body": {"user_id": 1, "access_level": "OWNER"}}
_SYSTEM = {"status": 200, "body": {
    "cpu_percent": 12.5, "memory_percent": 40.0, "memory_used_mb": 1024, "memory_total_mb": 4096,
    "disk_percent": 50.0, "disk_used_gb": 50.0, "disk_total_gb": 100.0,
    "bot_service_active": True, "bot_service_name": "bot & co.service",
}}


def _base(**overrides):
    r = {
        "GET /api/v1/auth/whoami": _WHOAMI,
        "GET /api/v1/admin/system/status": _SYSTEM,
        "GET /api/v1/admin/maintenance": {"status": 200, "body": {"active": False}},
        "GET /api/v1/admin/duplicates/stats": {"status": 200, "body": {
            "url_entries": 12, "content_entries": 10,
            "oldest_entry": "2026-01-01T00:00:00", "newest_entry": "2026-09-01T00:00:00"}},
        "GET /api/v1/admin/runtime-snapshot": {"status": 200, "body": {"status": "missing", "message": "Kein Bot-Snapshot."}},
        "GET /api/v1/admin/users": {"status": 200, "body": {"users": []}},
        "GET /api/v1/admin/backups": {"status": 200, "body": {"backups": []}},
    }
    r.update(overrides)
    return r


def _run(tmp_path, responses=None, ops=None, confirm=True, preset=None) -> dict:
    scenario = {"responses": _base(**(responses or {})), "ops": ops or [], "confirm": confirm, "preset": preset or []}
    script = tmp_path / "admin_harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), str(COMMON_JS), str(ADMIN_JS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def _calls(out):
    return [c["call"] for c in out["calls"]]


# ── Regression: Backup-Job-Status ────────────────────────────────────────

_BACKUP_START = {"POST /api/v1/admin/backups": {"status": 202, "body": {"job_id": "job1"}}}


@needs_node
def test_backup_job_succeeded_is_recognised_and_list_reloads(tmp_path):
    responses = dict(_BACKUP_START)
    responses["GET /api/v1/jobs/job1"] = [
        {"status": 200, "body": {"job_id": "job1", "status": "RUNNING", "progress": 50}},
        {"status": 200, "body": {"job_id": "job1", "status": "SUCCEEDED", "progress": 100}},
    ]
    out = _run(tmp_path, responses=responses, ops=[{"op": "call", "fn": "createBackup", "args": ["bot"]}])

    assert "Zeitüberschreitung" not in json.dumps(out, ensure_ascii=False)
    assert _calls(out).count("GET /api/v1/jobs/job1") == 2
    assert _calls(out)[-1] == "GET /api/v1/admin/backups?backup_type=bot"
    assert any(t.startswith("ok|Backup erstellt") for t in out["toasts"])


@needs_node
def test_backup_job_failed_shows_real_error(tmp_path):
    responses = dict(_BACKUP_START)
    responses["GET /api/v1/jobs/job1"] = {"status": 200, "body": {"job_id": "job1", "status": "FAILED", "error": "Platte voll"}}
    out = _run(tmp_path, responses=responses, ops=[{"op": "call", "fn": "createBackup", "args": ["bot"]}])

    assert _calls(out).count("GET /api/v1/jobs/job1") == 1
    assert "Platte voll" in out["els"]["admin-backup-status"]["html"]
    assert "Zeitüberschreitung" not in json.dumps(out, ensure_ascii=False)
    assert any(t.startswith("error|Backup fehlgeschlagen|Platte voll") for t in out["toasts"])
    assert out["els"]["admin-backup-create-btn"]["disabled"] is False


@needs_node
def test_backup_list_table_and_delete_only_after_confirmation(tmp_path):
    backups = {"status": 200, "body": {"backups": [
        {"name": "<b>bot_2026.tar.gz</b>", "size": 5 * 1024 * 1024, "created_at": "2026-09-28T10:00:00"}]}}
    responses = {"GET /api/v1/admin/backups": backups,
                 "DELETE /api/v1/admin/backups/x.tar.gz": {"status": 200, "body": {"deleted": True}}}
    out = _run(tmp_path, responses=responses)
    html = out["els"]["admin-backup-status"]["html"]
    assert "table card-table" in html and "&lt;b&gt;bot_2026.tar.gz&lt;/b&gt;" in html and "5.0 MB" in html
    assert 'href="#i-trash"' in html and "admin-backup-delete" in html

    declined = _run(tmp_path, responses=responses, confirm=False,
                    ops=[{"op": "call", "fn": "deleteBackup", "args": ["x.tar.gz", "bot"]}])
    assert declined["confirms"] == ["„x.tar.gz“ wird endgültig gelöscht."]
    assert "DELETE /api/v1/admin/backups/x.tar.gz" not in _calls(declined)

    done = _run(tmp_path, responses=responses, ops=[{"op": "call", "fn": "deleteBackup", "args": ["x.tar.gz", "bot"]}])
    delete = [c for c in done["calls"] if c["call"] == "DELETE /api/v1/admin/backups/x.tar.gz"]
    assert delete and delete[0]["xrw"] is True
    assert "ok|Backup gelöscht|x.tar.gz" in done["toasts"]


@needs_node
def test_empty_backup_list(tmp_path):
    html = _run(tmp_path)["els"]["admin-backup-status"]["html"]
    assert 'class="empty' in html and "Keine Backups vorhanden" in html


@needs_node
@pytest.mark.parametrize("fn,endpoint", [
    ("restartBot", "POST /api/v1/admin/system/restart"),
    ("clearDuplicateCache", "POST /api/v1/admin/duplicates/clear"),
])
def test_destructive_actions_need_confirmation(tmp_path, fn, endpoint):
    responses = {"POST /api/v1/admin/system/restart": {"status": 200, "body": {"message": "Neustart in 2 s"}},
                 "POST /api/v1/admin/duplicates/clear": {"status": 200, "body": {"url_entries_removed": 3, "content_entries_removed": 2}}}
    declined = _run(tmp_path, responses=responses, confirm=False, ops=[{"op": "call", "fn": fn}])
    assert len(declined["confirms"]) == 1 and endpoint not in _calls(declined)

    confirmed = _run(tmp_path, responses=responses, ops=[{"op": "call", "fn": fn}])
    assert endpoint in _calls(confirmed)
    assert any(t.startswith("ok|") for t in confirmed["toasts"])


@needs_node
def test_clear_duplicates_sends_confirm_flag_and_reloads_stats(tmp_path):
    responses = {"POST /api/v1/admin/duplicates/clear": {"status": 200, "body": {"url_entries_removed": 3, "content_entries_removed": 2}}}
    out = _run(tmp_path, responses=responses, ops=[{"op": "call", "fn": "clearDuplicateCache"}])
    post = [c for c in out["calls"] if c["call"] == "POST /api/v1/admin/duplicates/clear"][0]
    assert json.loads(post["body"]) == {"confirm": True}
    assert _calls(out)[-1] == "GET /api/v1/admin/duplicates/stats"
    assert "3 URL- / 2 Content-Einträge entfernt." in out["els"]["admin-duplicates-message"]["text"]


@needs_node
def test_maintenance_confirmation_only_when_activating(tmp_path):
    post = {"POST /api/v1/admin/maintenance": {"status": 200, "body": {"active": True}}}

    declined = _run(tmp_path, responses=post, confirm=False, ops=[{"op": "call", "fn": "toggleMaintenance"}])
    assert declined["confirms"] == ["Im Telegram-Bot werden dann alle Nutzer außer Admins und Owner blockiert."]
    assert "POST /api/v1/admin/maintenance" not in _calls(declined)

    activated = _run(tmp_path, responses=post, ops=[{"op": "call", "fn": "toggleMaintenance"}])
    body = [c for c in activated["calls"] if c["call"] == "POST /api/v1/admin/maintenance"][0]["body"]
    assert json.loads(body) == {"active": True}

    active_state = dict(post)
    active_state["GET /api/v1/admin/maintenance"] = {"status": 200, "body": {"active": True}}
    deactivated = _run(tmp_path, responses=active_state, ops=[{"op": "call", "fn": "toggleMaintenance"}])
    assert deactivated["confirms"] == []                         # Deaktivieren ohne Nachfrage
    body = [c for c in deactivated["calls"] if c["call"] == "POST /api/v1/admin/maintenance"][0]["body"]
    assert json.loads(body) == {"active": False}


@needs_node
def test_maintenance_status_badge(tmp_path):
    els = _run(tmp_path, responses={"GET /api/v1/admin/maintenance": {"status": 200, "body": {"active": True}}})["els"]
    assert "bg-yellow-lt" in els["admin-maintenance-status"]["html"] and "Aktiv" in els["admin-maintenance-status"]["html"]
    assert els["admin-maintenance-toggle-btn"]["text"] == "Wartungsmodus deaktivieren"


@needs_node
def test_system_status_badge_and_service_name_escaped_once(tmp_path):
    els = _run(tmp_path)["els"]
    bot = els["admin-system-bot"]["html"]
    assert "bg-green-lt" in bot and "Aktiv" in bot
    assert "bot &amp; co.service" in bot and "&amp;amp;" not in bot
    assert els["admin-system-cpu"]["text"] == "12.5 %"
    assert "bg-green-lt" in els["admin-bot-operation-status"]["html"]


@needs_node
def test_users_table_escaped_without_emoji_and_roles(tmp_path):
    users = {"status": 200, "body": {"users": [
        {"telegram_id": 42, "role": "owner", "navidrome_user": "<i>robin</i>", "created_at": "2026-09-01T00:00:00"},
        {"telegram_id": -3, "role": "user", "navidrome_user": None, "created_at": None},
    ]}}
    html = _run(tmp_path, responses={"GET /api/v1/admin/users": users})["els"]["admin-users-content"]["html"]
    assert "table card-table" in html
    assert "&lt;i&gt;robin&lt;/i&gt;" in html and "<i>robin</i>" not in html
    assert 'class="badge bg-red-lt">owner' in html and 'class="badge bg-secondary-lt">user' in html
    assert "Web</span>" in html and "Telegram</span>" in html
    assert html.count("view-stats-btn") == 1 and 'data-navidrome-user="&lt;i&gt;robin&lt;/i&gt;"' in html
    assert not _EMOJI.search(html)


@needs_node
def test_create_web_user_posts_and_reloads(tmp_path):
    responses = {"POST /api/v1/admin/web-users": {"status": 201, "body": {"telegram_id": -4, "navidrome_user": "anna"}}}
    ops = [{"op": "set", "id": "admin-web-user-name", "key": "value", "value": "anna"},
           {"op": "set", "id": "admin-web-user-role", "key": "value", "value": "moderator"},
           {"op": "callEvent", "fn": "createWebUser"}]
    out = _run(tmp_path, responses=responses, ops=ops)

    post = [c for c in out["calls"] if c["call"] == "POST /api/v1/admin/web-users"][0]
    assert json.loads(post["body"]) == {"navidrome_user": "anna", "role": "moderator"}
    assert _calls(out)[-1] == "GET /api/v1/admin/users"
    assert "ok|Web-Benutzer angelegt|#-4 (anna)" in out["toasts"]
    assert out["els"]["admin-web-user-name"]["value"] == "" and out["els"]["admin-web-user-btn"]["disabled"] is False


@needs_node
def test_create_web_user_error_is_shown(tmp_path):
    responses = {"POST /api/v1/admin/web-users": {"status": 409, "body": {"error": {"message": "<gibt es schon>"}}}}
    out = _run(tmp_path, responses=responses, ops=[{"op": "callEvent", "fn": "createWebUser"}])
    assert "&lt;gibt es schon&gt;" in out["els"]["admin-web-user-message"]["html"]
    assert "error|Web-Benutzer nicht angelegt|<gibt es schon>" in out["toasts"]


@needs_node
def test_runtime_snapshot_states(tmp_path):
    missing = _run(tmp_path)["els"]
    assert "Kein Bot-Snapshot" in missing["admin-errors-content"]["html"]
    assert "kein Snapshot" in missing["admin-runtime-freshness"]["html"]

    body = {"status": "stale", "age_seconds": 600, "errors": {
        "total_exceptions": 3, "avg_processing_time": 0.1234, "recovery_success_rate": 0.5,
        "by_category": {"network": 2}, "by_module": {"yt": 1}, "by_severity": {"ERROR": 3},
        "recent": [{"timestamp": "2026-09-28T10:00:00", "type": "X", "severity": "ERROR", "module": "yt", "message": "<boom>"}]},
        "duplicates": {"total_checks": 10, "duplicates_skipped": 2, "url_duplicates_found": 1,
                       "content_duplicates_found": 1, "duplicate_rate": 20.0}}
    els = _run(tmp_path, responses={"GET /api/v1/admin/runtime-snapshot": {"status": 200, "body": body}})["els"]
    errors = els["admin-errors-content"]["html"]
    assert "&lt;boom&gt;" in errors and 'class="badge bg-red-lt"' in errors
    assert "0.123 s" in errors and "50.0 %" in errors
    assert "bg-yellow-lt" in els["admin-runtime-freshness"]["html"] and "veraltet" in els["admin-runtime-freshness"]["html"]
    assert "20.0 %" in els["admin-duplicates-session"]["html"]


@needs_node
def test_duplicate_stats_datagrid(tmp_path):
    html = _run(tmp_path)["els"]["admin-duplicates-stats"]["html"]
    assert "datagrid" in html and ">12<" in html and ">10<" in html and "2026 – " in html
