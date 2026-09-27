// control_center/static/common.js
// Gemeinsame JS-Helfer fuer alle Control-Center-Seiten (ui_prompt.txt
// Phase 1 "UI STRUCTURE REDESIGN"). Aus dem vorherigen Einzel-Dashboard
// (dashboard.html) unveraendert extrahiert, um Duplikation ueber jetzt
// 12 Seiten hinweg zu vermeiden - weiterhin Vanilla JS, keine Bibliothek,
// kein Build-Schritt (Master-Prompt Abschnitt 7).
//
// Jede Seite definiert eine eigene Funktion `initPage()` (in ihrem
// eigenen {% block scripts %}), die checkAuth() aufruft und danach ihre
// seiteneigenen load*()-Funktionen startet. onTelegramAuth() (unten)
// ruft nach erfolgreichem Login dieselbe seiteneigene initPage() erneut
// auf.

// Subpath-Betrieb hinter nginx (z. B. /controlcenter): der Server rendert den
// Prefix als <meta name="cc-base"> (leer im Direktbetrieb auf :8420).
// Jeder API-Aufruf laeuft durch apiUrl() - nie einen root-absoluten Pfad
// direkt an fetch() uebergeben.
const CC_BASE = ((document.querySelector('meta[name="cc-base"]') || {}).content || "");
function apiUrl(path) {
  return CC_BASE + path;
}

const VIEWS = ["loading-view", "login-view", "dashboard-view", "error-view"];
function showOnly(id) {
  VIEWS.forEach((v) => {
    const el = document.getElementById(v);
    if (el) el.hidden = (v !== id);
  });
}
function showError(msg) {
  const el = document.getElementById("error-view");
  if (el) el.textContent = msg;
  showOnly("error-view");
}

// Health-Status -> Tabler-Farbtoken (Phase E CC-LIB-FINAL: von health.js
// hierher verschoben, reine Verschiebung ohne Verhaltensaenderung - zweiter
// Konsument ist jetzt library.html's Library-Health-Karte, damit beide
// Seiten denselben Status<->Farbe-Vertrag verwenden statt einer eigenen,
// gröberen Schwellenwert-Logik).
const _HEALTH_STATUS_COLOR = {
  EXCELLENT: "green", GOOD: "lime", FAIR: "yellow", POOR: "orange", CRITICAL: "red",
};

// Score-Verlauf als Sparkline-SVG (Phase E CC-LIB-FINAL: von health.js
// hierher verschoben, reine Verschiebung ohne Verhaltensaenderung -
// zweiter Konsument ist jetzt library.html's Library-Health-Karte,
// gleicher Endpunkt GET /api/v1/library/health/score-history). Reihenfolge
// der API: aelteste zuerst. Gleichbleibende Scores werden als flache Linie
// gezeichnet.
function _sparklineSvg(entries) {
  const W = 240, H = 32, PAD = 4;
  const scored = entries.filter((e) => typeof e.score === "number");
  if (!scored.length) return "";
  const vals = scored.map((e) => e.score);
  const min = Math.min.apply(null, vals);
  const max = Math.max.apply(null, vals);
  const x = (i) => scored.length === 1 ? W / 2 : PAD + i * (W - 2 * PAD) / (scored.length - 1);
  const y = (v) => max === min ? H / 2 : PAD + (max - v) * (H - 2 * PAD) / (max - min);
  const pts = scored.map((e, i) => x(i).toFixed(1) + "," + y(e.score).toFixed(1)).join(" ");
  const last = scored[scored.length - 1];
  const dots = scored.map((e, i) => {
    const when = e.timestamp ? new Date(e.timestamp).toLocaleString() : "";
    return `<circle cx="${x(i).toFixed(1)}" cy="${y(e.score).toFixed(1)}" r="${e === last ? 3.5 : 2}" fill="currentColor"><title>${_escapeHtml(String(e.score))} · ${_escapeHtml(e.status || "UNSCORED")} · ${_escapeHtml(when)}</title></circle>`;
  }).join("");
  return `<svg class="text-primary" viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="max-width:${W}px" role="img" aria-label="Score-Verlauf der letzten ${scored.length} Läufe">` +
    `<polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>${dots}</svg>`;
}

// Sicherheitshinweis (galt schon im vorherigen Einzel-Dashboard): Titel/
// Artist/Pfad/Message-Felder stammen aus Library-/Download-Metadaten
// (z. B. YouTube-Videotiteln) - nicht vertrauenswuerdig genug, um sie
// ungefiltert per innerHTML einzubetten (XSS, falls ein Titel HTML/
// Script enthaelt). Alle render*()-Funktionen escapen freien Text
// konsequent damit.
function _escapeHtml(value) {
  if (value == null) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Gemeinsamer Lade-/Fehlerbehandlungs-Pfad fuer read-only-Bereiche -
// einheitliches Status-Handling (401/403/404/Netzwerkfehler) auf allen
// Seiten. `retryFn` (optional, Library Artist-Centric UX CC-AC-1
// nachgezogen) haengt bei echten Fehlern (5xx/Netzwerk - NICHT bei 403/
// 404, die sind kein "einfach nochmal versuchen"-Fall) einen "Erneut
// versuchen"-Button an - alle bestehenden Aufrufer ohne diesen Parameter
// verhalten sich unveraendert (optionaler Parameter, `undefined` ist
// falsy).
function _retryButtonHtml(retryFn) {
  if (!retryFn) return "";
  window._ccRetryHandlers = window._ccRetryHandlers || {};
  const key = "retry_" + Math.random().toString(36).slice(2);
  window._ccRetryHandlers[key] = retryFn;
  return `<div class="retry-row"><button class="small" type="button" onclick="window._ccRetryHandlers['${key}']()">Erneut versuchen</button></div>`;
}
async function _loadInto(elementId, url, renderFn, retryFn) {
  const el = document.getElementById(elementId);
  if (!el) return;
  try {
    const res = await fetch(apiUrl(url), { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (res.status === 403) {
      el.innerHTML = '<span class="denied">Keine Berechtigung (Rolle reicht nicht).</span>';
      return;
    }
    if (res.status === 404) {
      const body = await res.json().catch(() => null);
      el.innerHTML = `<span class="empty-note">${body && body.error ? body.error.message : "Nicht gefunden."}</span>`;
      return;
    }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      el.innerHTML = `<span>Fehler: ${_escapeHtml(body && body.error ? body.error.message : String(res.status))}</span>${_retryButtonHtml(retryFn)}`;
      return;
    }
    renderFn(el, await res.json());
  } catch (err) {
    el.innerHTML = `<span>Netzwerkfehler: ${_escapeHtml(err.message)}</span>${_retryButtonHtml(retryFn)}`;
  }
}

// Prueft die Anmeldung (GET /api/v1/auth/whoami), zeigt Login-/Error-
// View bei Bedarf und schaltet sonst auf die Dashboard-View um. Liefert
// das whoami-Objekt zurueck (oder null, wenn bereits eine andere View
// angezeigt wurde) - jede Seite ruft danach ihre eigenen load*()-
// Funktionen auf.
async function checkAuth() {
  showOnly("loading-view");
  try {
    const res = await fetch(apiUrl("/api/v1/auth/whoami"), { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); return null; }
    if (!res.ok) { showError("Anmeldestatus konnte nicht geprüft werden."); return null; }
    const who = await res.json();
    const userEl = document.getElementById("current-user");
    if (userEl) userEl.textContent = `Angemeldet als #${who.user_id} (${who.access_level})`;
    showOnly("dashboard-view");
    return who;
  } catch (err) {
    showError("Netzwerkfehler: " + err.message);
    return null;
  }
}

function onTelegramAuth(user) {
  fetch(apiUrl("/api/v1/auth/telegram-callback"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(user),
  })
    .then((res) => {
      if (res.ok) {
        if (typeof initPage === "function") initPage();
      } else {
        showError("Telegram-Login fehlgeschlagen.");
      }
    })
    .catch((err) => showError("Netzwerkfehler: " + err.message));
}

// Mobile Sidebar-Drawer (Master-Prompt Abschnitt 12 "RESPONSIVE
// NAVIGATION") - reines CSS-Klassen-Toggle, keine Bibliothek.
function _initSidebarToggle() {
  const toggleBtn = document.getElementById("sidebar-toggle");
  if (!toggleBtn) return;
  toggleBtn.addEventListener("click", () => {
    document.body.classList.toggle("sidebar-open");
  });
  document.getElementById("sidebar")?.addEventListener("click", (event) => {
    if (event.target.closest("a")) document.body.classList.remove("sidebar-open");
  });
}
document.addEventListener("DOMContentLoaded", _initSidebarToggle);
