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

// Issue-Codes -> Kurzlabel/Severity-Tier/Icon (CC-LIB-FINAL Library-Home:
// hierher verschoben aus library_artist_detail.html's frueherem, nur
// lokalem _TRACK_ISSUE_LABELS - zweiter Konsument ist jetzt library.html's
// Aufmerksamkeit-Karte, dieselbe Quelle statt einer zweiten, driftenden
// Kopie. Vollstaendig gegen services/library_health/issues.py::ISSUE_SPECS
// abgeglichen (alle dort definierten Codes sind unten vertreten).
const _ISSUE_LABELS = {
  META_NOT_ANALYZABLE: "Tags nicht lesbar",
  META_ARTIST_MISSING: "Artist fehlt",
  META_TITLE_MISSING: "Titel fehlt",
  META_TITLE_NOT_CLEAN: "Titel enthält Parsing-/Formatierungsreste",
  META_ALBUM_MISSING: "Album fehlt",
  META_ALBUM_ARTIST_MISSING: "Album-Artist fehlt",
  META_YEAR_MISSING: "Jahr fehlt",
  META_YEAR_INVALID: "Jahr ungültig",
  META_GENRE_MISSING: "Genre fehlt",
  META_TRACK_NUMBER_MISSING: "Tracknummer fehlt",
  META_MB_RECORDING_MISSING: "MusicBrainz Recording-ID fehlt",
  META_MB_RELEASE_MISSING: "MusicBrainz Release-ID fehlt",
  META_ISRC_MISSING: "ISRC fehlt",
  ARTWORK_MISSING: "Cover fehlt",
  ARTWORK_INVALID: "Cover nicht dekodierbar",
  ARTWORK_LOW_RESOLUTION: "Cover-Auflösung niedrig",
  ARTWORK_NON_SQUARE: "Cover nicht quadratisch",
  LYRICS_MISSING: "Lyrics fehlen",
  LYRICS_EMPTY: "Lyrics-Tag leer",
  LYRICS_INVALID: "Lyrics-Tag wirkt nicht wie Liedtext",
  AUDIO_NOT_ANALYZABLE: "Audio nicht analysierbar",
  AUDIO_NO_STREAM: "Kein Audio-Stream",
  AUDIO_CORRUPT: "Audio-Datei beschädigt",
  AUDIO_LOW_BITRATE: "Bitrate niedrig",
  AUDIO_VERY_SHORT: "Sehr kurze Laufzeit",
  LOUDNESS_TAG_MISSING: "Kein Loudness-Tag",
  LOUDNESS_OFF_TARGET: "Lautheit weicht vom Ziel ab",
  LOUDNESS_TAG_INVALID: "Loudness-Tag ungültig",
  LOUDNESS_TAG_PARTIAL: "Loudness-Tag unvollständig",
  STRUCTURE_INVALID_PATH: "Ungewöhnliche Verzeichnisstruktur",
  STRUCTURE_FILE_OUTSIDE_HIERARCHY: "Datei außerhalb der erwarteten Hierarchie",
  FILENAME_TITLE_MISMATCH: "Dateiname passt nicht zum Titel",
  FILENAME_SUSPICIOUS: "Dateiname wirkt fehlerhaft",
  FILENAME_EXTENSION_UNEXPECTED: "Unerwartete Dateiendung",
  MULTI_ARTIST_SUSPICIOUS: "Artist-Tag wirkt wie Mehrfach-Artist-Konkatenation",
  MULTI_ARTIST_INCONSISTENT: "Artist-/Album-Artist-Felder widersprüchlich",
  MULTI_ARTIST_DUPLICATE: "Artist mehrfach im Multi-Artist-Feld",
  GENRE_EMPTY: "Genre-Tag leer",
  GENRE_INVALID: "Genre außerhalb der Konvention",
  GENRE_DELIMITER_INCONSISTENT: "Genre-Trennzeichen uneinheitlich",
  ALBUM_TRACK_GAP: "Lücke in der Tracknummerierung",
  ALBUM_NAME_INCONSISTENT: "Albumname im Ordner uneinheitlich",
  ALBUM_ARTIST_INCONSISTENT: "Album-Artist im Ordner uneinheitlich",
  ALBUM_YEAR_INCONSISTENT: "Jahr im Album uneinheitlich",
  ALBUM_GENRE_INCONSISTENT: "Genre im Album uneinheitlich",
  ALBUM_RELEASE_ID_INCONSISTENT: "MusicBrainz Release-ID im Album uneinheitlich",
  ALBUM_COVER_INCONSISTENT: "Cover im Album uneinheitlich",
  ALBUM_DUPLICATE_TRACK_NUMBER: "Tracknummer im Album doppelt vergeben",
  ARTIST_DIR_TAG_MISMATCH: "Artist-Ordner weicht vom Artist-Tag ab",
  ARTIST_NAME_VARIANTS: "Artist-Ordner wirken wie Schreibvarianten",
  DUPLICATE_EXACT: "Exaktes Duplikat (identische Datei)",
  DUPLICATE_RECORDING: "Duplikat (gleiche Aufnahme/ISRC)",
  DUPLICATE_SUSPECTED: "Vermutliches Duplikat (Artist+Titel)",
};

// Severity-Tier je Code, 1:1 aus services/library_health/issues.py::
// ISSUE_SPECS uebernommen (bei neuen/geaenderten Codes dort mitpflegen -
// dieselbe Pflicht wie zuvor bei der library.html-lokalen _WARNING_CODES,
// jetzt nur vollstaendig inkl. ERROR/CRITICAL statt nur WARNING). Alle
// nicht gelisteten Codes gelten als INFO.
const _ISSUE_ERROR_CODES = new Set([
  "META_NOT_ANALYZABLE", "META_ARTIST_MISSING", "META_TITLE_MISSING",
  "ARTWORK_INVALID", "AUDIO_NOT_ANALYZABLE", "AUDIO_NO_STREAM",
  "AUDIO_CORRUPT", "ALBUM_DUPLICATE_TRACK_NUMBER",
]);
const _ISSUE_WARNING_CODES = new Set([
  "ALBUM_ARTIST_INCONSISTENT", "ALBUM_NAME_INCONSISTENT", "ALBUM_TRACK_GAP",
  "ARTWORK_MISSING", "AUDIO_LOW_BITRATE", "DUPLICATE_EXACT",
  "DUPLICATE_RECORDING", "GENRE_EMPTY", "LOUDNESS_TAG_INVALID",
  "LYRICS_EMPTY", "LYRICS_INVALID", "META_ALBUM_ARTIST_MISSING",
  "META_ALBUM_MISSING", "META_GENRE_MISSING", "META_TITLE_NOT_CLEAN",
  "META_YEAR_INVALID", "META_YEAR_MISSING", "MULTI_ARTIST_SUSPICIOUS",
  "STRUCTURE_FILE_OUTSIDE_HIERARCHY", "STRUCTURE_INVALID_PATH",
]);
function _issueSeverityTier(code) {
  if (_ISSUE_ERROR_CODES.has(code)) return "ERROR";
  if (_ISSUE_WARNING_CODES.has(code)) return "WARNING";
  return "INFO";
}
const _ISSUE_SEVERITY_RANK = { ERROR: 3, WARNING: 2, INFO: 1 };

// Grobe Icon-Zuordnung nach Code-Praefix - reine Praesentation (kein
// fachlicher Ersatz fuer Severity/Label), fuer kompakte Listendarstellung
// (library.html's Aufmerksamkeit-Karte).
function _issueIcon(code) {
  if (code.indexOf("META_MB_") === 0) return "🎵";
  if (code.indexOf("META_") === 0) return "📋";
  if (code.indexOf("ARTWORK_") === 0) return "🖼️";
  if (code.indexOf("LYRICS_") === 0) return "📝";
  if (code.indexOf("AUDIO_") === 0) return "🎚️";
  if (code.indexOf("LOUDNESS_") === 0) return "🔊";
  if (code.indexOf("FILENAME_") === 0) return "📄";
  if (code.indexOf("STRUCTURE_") === 0) return "🗂️";
  if (code.indexOf("MULTI_ARTIST") === 0) return "👥";
  if (code.indexOf("ALBUM_") === 0) return "💿";
  if (code.indexOf("ARTIST_") === 0) return "🎤";
  if (code.indexOf("GENRE_") === 0) return "🎭";
  if (code.indexOf("DUPLICATE_") === 0) return "🧬";
  return "⚠️";
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
    const logoutBtn = document.getElementById("logout-btn");
    if (logoutBtn) logoutBtn.hidden = false;
    showOnly("dashboard-view");
    return who;
  } catch (err) {
    showError("Netzwerkfehler: " + err.message);
    return null;
  }
}

// Backlog 9: Login mit Navidrome-Benutzer. Passwort wird nur im POST-Body
// an den eigenen Server geschickt (der es an Navidrome weiterreicht) und
// sofort aus dem Feld gelöscht - nie in URL, Storage oder Konsole.
async function onNavidromeLogin(event) {
  event.preventDefault();
  const userEl = document.getElementById("navidrome-login-username");
  const pwEl = document.getElementById("navidrome-login-password");
  const btn = document.getElementById("navidrome-login-btn");
  const msgEl = document.getElementById("navidrome-login-message");
  if (!userEl || !pwEl) return;
  const password = pwEl.value;
  pwEl.value = "";
  if (btn) btn.disabled = true;
  if (msgEl) msgEl.textContent = "";
  try {
    const res = await fetch(apiUrl("/api/v1/auth/navidrome-login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ username: userEl.value, password }),
    });
    if (res.ok) {
      if (typeof initPage === "function") initPage();
      return;
    }
    const body = await res.json().catch(() => null);
    if (msgEl) msgEl.textContent = (body && body.error && body.error.message) || `Anmeldung fehlgeschlagen (${res.status}).`;
  } catch (err) {
    if (msgEl) msgEl.textContent = "Netzwerkfehler bei der Anmeldung.";
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Abmelden: Server löscht das Session-Cookie (POST, Same-Origin-Check),
// danach Login-Ansicht. Auch bei Fehler lokal abmelden-Zustand zeigen.
async function onLogout() {
  const btn = document.getElementById("logout-btn");
  if (btn) btn.disabled = true;
  try {
    await fetch(apiUrl("/api/v1/auth/logout"), { method: "POST", credentials: "same-origin" });
  } catch (err) {
    // Netzwerkfehler: Cookie evtl. noch gesetzt - Neuladen zeigt den echten Zustand.
  }
  const userEl = document.getElementById("current-user");
  if (userEl) userEl.textContent = "";
  if (btn) { btn.hidden = true; btn.disabled = false; }
  showOnly("login-view");
}

document.addEventListener("DOMContentLoaded", () => {
  const logoutBtn = document.getElementById("logout-btn");
  if (logoutBtn) logoutBtn.addEventListener("click", onLogout);
});

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("navidrome-login-form");
  if (form) form.addEventListener("submit", onNavidromeLogin);
});

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
// Der Schalter liegt im Header (nicht in der Sidebar, die auf dem Handy
// aus dem Bild geschoben wird); aria-expanded folgt dem Zustand.
// Schließen: Schalter, Tipp auf den Hintergrund, Escape, Klick auf einen Link.
function _setSidebarOpen(open) {
  document.body.classList.toggle("sidebar-open", open);
  const btn = document.getElementById("sidebar-toggle");
  if (btn) {
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    btn.setAttribute("aria-label", open ? "Menü schließen" : "Menü öffnen");
  }
}
function _initSidebarToggle() {
  const toggleBtn = document.getElementById("sidebar-toggle");
  if (!toggleBtn) return;
  toggleBtn.addEventListener("click", () => {
    _setSidebarOpen(!document.body.classList.contains("sidebar-open"));
  });
  document.getElementById("sidebar")?.addEventListener("click", (event) => {
    if (event.target.closest("a")) _setSidebarOpen(false);
  });
  document.getElementById("sidebar-backdrop")?.addEventListener("click", () => _setSidebarOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.body.classList.contains("sidebar-open")) _setSidebarOpen(false);
  });
}
document.addEventListener("DOMContentLoaded", _initSidebarToggle);

// ══════════════════════════════════════════════════════════════════════
// CC-UI-1: gemeinsame UI-Helfer nach docs/CONTROL_CENTER_UI_STANDARD.md
// (Abschnitte 2, 3, 7, 8, 12). Rein additiv - keine bestehende Funktion
// ist verändert; Seiten stellen erst in ihren eigenen PRs darauf um.
// ══════════════════════════════════════════════════════════════════════

// Icon aus dem Sprite (templates/_icons.html), Standard Abschnitt 3.
function ccIcon(id, extraClass) {
  const cls = "icon" + (extraClass ? " " + extraClass : "");
  return `<svg class="${_escapeHtml(cls)}" aria-hidden="true"><use href="#i-${_escapeHtml(id)}"/></svg>`;
}

// Status-Farben (Standard Abschnitt 2) - ein einziges Mapping.
const CC_STATUS_STYLE = {
  ok:      { color: "green",     icon: "check" },
  running: { color: "teal",      icon: "refresh" },
  warn:    { color: "yellow",    icon: "alert" },
  error:   { color: "red",       icon: "alert" },
  step:    { color: "purple",    icon: "tag" },
  neutral: { color: "secondary", icon: "info" },
};
// Vorhandene Werte aus der API -> Status-Art (Standard Abschnitt 2, Tabelle
// "Zuordnung vorhandener Werte"). Unbekannte Werte -> neutral.
const CC_STATUS_KIND = {
  // JobStatus
  PENDING: "neutral", RUNNING: "running", SUCCEEDED: "ok", FAILED: "error", CANCELLED: "neutral",
  // Download-Verlauf
  success: "ok", failed: "error", cancelled: "neutral", duplicate: "neutral",
  // Finding-Schwere
  CRITICAL: "error", ERROR: "error", WARNING: "warn", SUSPECTED: "warn", INFO: "neutral",
  // Health-Score
  EXCELLENT: "ok", GOOD: "ok", FAIR: "warn", POOR: "error",
  // Repair-Ergebnis
  SUCCESS: "ok", UNRESOLVED: "warn", SKIPPED: "warn",
};
function ccStatusKind(value) {
  return CC_STATUS_KIND[value] || "neutral";
}
// Badge immer Icon + Text (Farbe trägt nie allein die Information).
function ccStatusBadge(kind, label) {
  const style = CC_STATUS_STYLE[kind] || CC_STATUS_STYLE.neutral;
  return `<span class="badge bg-${style.color}-lt">${ccIcon(style.icon, "icon-sm me-1")}${_escapeHtml(label)}</span>`;
}

// Zustände Laden/Leer/Fehler/keine Berechtigung (Standard Abschnitt 7).
const ccState = {
  loading(el) {
    if (!el) return;
    el.innerHTML = '<div class="placeholder-glow" aria-busy="true">'
      + '<div class="placeholder col-9 mb-2"></div><div class="placeholder col-7 mb-2"></div>'
      + '<div class="placeholder col-5"></div></div>';
  },
  empty(el, title, subtitle, actionHtml) {
    if (!el) return;
    el.innerHTML = '<div class="empty py-4">'
      + `<div class="empty-icon">${ccIcon("inbox")}</div>`
      + `<p class="empty-title">${_escapeHtml(title || "Keine Einträge")}</p>`
      + (subtitle ? `<p class="empty-subtitle text-secondary">${_escapeHtml(subtitle)}</p>` : "")
      + (actionHtml ? `<div class="empty-action">${actionHtml}</div>` : "")
      + "</div>";
  },
  // retryFn nur bei 5xx/Netzwerk übergeben (nicht bei 403/404).
  error(el, message, retryFn) {
    if (!el) return;
    el.innerHTML = `<div class="text-danger mb-2">${ccIcon("alert", "me-1")}${_escapeHtml(message || "Fehler beim Laden.")}</div>`
      + (retryFn ? `<button type="button" class="btn btn-sm">${ccIcon("refresh", "me-1")}Erneut versuchen</button>` : "");
    const btn = retryFn ? el.querySelector("button") : null;
    if (btn) btn.addEventListener("click", () => retryFn());
  },
  denied(el) {
    if (!el) return;
    el.innerHTML = `<div class="alert alert-warning mb-0">${ccIcon("lock", "me-1")}Keine Berechtigung (Rolle reicht nicht).</div>`;
  },
};

// API-Zugriff für alle Methoden (Standard Abschnitt 12). Läuft immer über
// apiUrl() (Subpath-Betrieb). 401 -> Login-Ansicht. Fehler werfen
// CcApiError mit der Meldung aus {"error": {"message": ...}}.
class CcApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "CcApiError";
    this.status = status;
    this.body = body;
  }
}
async function ccApi(method, path, body) {
  const options = { method: method || "GET", credentials: "same-origin", headers: {} };
  // Wie die bisherigen Admin-Aufrufe: schreibende Requests als XHR kennzeichnen
  // (serverseitig schützt der Origin-Check, siehe dependencies.verify_same_origin).
  if (options.method !== "GET") options.headers["X-Requested-With"] = "XMLHttpRequest";
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const res = await fetch(apiUrl(path), options);
  if (res.status === 401) {
    showOnly("login-view");
    throw new CcApiError("Nicht angemeldet.", 401, null);
  }
  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch (e) { data = null; }
  }
  if (!res.ok) {
    const msg = (data && data.error && data.error.message) || `HTTP ${res.status}`;
    throw new CcApiError(msg, res.status, data);
  }
  return data;
}

// Bestätigungsdialog statt confirm() (Standard Abschnitt 8). Nutzt das
// vorhandene window.tabler.Modal; ohne Tabler-JS Rückfall auf confirm().
function ccConfirm(opts) {
  const o = opts || {};
  const Modal = window.tabler && window.tabler.Modal;
  if (!Modal) return Promise.resolve(window.confirm(o.text || o.title || "Fortfahren?"));
  let el = document.getElementById("cc-confirm-modal");
  if (!el) {
    el = document.createElement("div");
    el.id = "cc-confirm-modal";
    el.className = "modal modal-blur fade";
    el.tabIndex = -1;
    el.innerHTML = '<div class="modal-dialog modal-sm modal-dialog-centered"><div class="modal-content">'
      + '<div class="modal-status"></div>'
      + '<div class="modal-body text-center py-4"><h3 class="cc-confirm-title"></h3>'
      + '<div class="text-secondary cc-confirm-text"></div></div>'
      + '<div class="modal-footer"><div class="w-100 d-flex gap-2">'
      + '<button type="button" class="btn w-100 cc-confirm-cancel" data-bs-dismiss="modal">Zurück</button>'
      + '<button type="button" class="btn w-100 cc-confirm-ok"></button>'
      + "</div></div></div></div>";
    document.body.appendChild(el);
  }
  el.querySelector(".modal-status").className = "modal-status " + (o.danger ? "bg-danger" : "bg-teal");
  el.querySelector(".cc-confirm-title").textContent = o.title || "Fortfahren?";
  el.querySelector(".cc-confirm-text").textContent = o.text || "";
  const okBtn = el.querySelector(".cc-confirm-ok");
  okBtn.textContent = o.confirmLabel || "OK";
  okBtn.className = "btn w-100 cc-confirm-ok " + (o.danger ? "btn-danger" : "btn-primary");
  return new Promise((resolve) => {
    let result = false;
    const onOk = () => { result = true; modal.hide(); };
    const onHidden = () => {
      okBtn.removeEventListener("click", onOk);
      el.removeEventListener("hidden.bs.modal", onHidden);
      resolve(result);
    };
    const modal = Modal.getOrCreateInstance(el);
    okBtn.addEventListener("click", onOk);
    el.addEventListener("hidden.bs.modal", onHidden);
    modal.show();
  });
}

// Rückmeldung nach Aktionen (Standard Abschnitt 8). kind: "ok" | "error".
// Erfolg verschwindet nach ~4 s, Fehler bleiben stehen.
function ccToast(kind, title, text) {
  let container = document.getElementById("cc-toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "cc-toast-container";
    container.className = "toast-container position-fixed bottom-0 end-0 p-3";
    document.body.appendChild(container);
  }
  const isError = kind === "error";
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.setAttribute("role", isError ? "alert" : "status");
  toast.setAttribute("aria-live", isError ? "assertive" : "polite");
  toast.innerHTML = '<div class="toast-header">'
    + ccIcon(isError ? "alert" : "check", (isError ? "text-danger" : "text-teal") + " me-2")
    + `<strong class="me-auto">${_escapeHtml(title)}</strong>`
    + '<button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Schließen"></button></div>'
    + (text ? `<div class="toast-body">${_escapeHtml(text)}</div>` : "");
  container.appendChild(toast);
  const Toast = window.tabler && window.tabler.Toast;
  if (Toast) {
    toast.addEventListener("hidden.bs.toast", () => toast.remove());
    Toast.getOrCreateInstance(toast, { autohide: !isError, delay: 4000 }).show();
  } else {
    toast.classList.add("show");
    if (!isError) setTimeout(() => toast.remove(), 4000);
  }
  return toast;
}

// Hell/Dunkel-Umschalter (Standard Abschnitt 2). Startwert setzt bereits
// das Inline-Skript im <head> von _base.html; hier nur Klick + Icon.
function _ccCurrentTheme() {
  return document.documentElement.getAttribute("data-bs-theme") === "light" ? "light" : "dark";
}
function _ccSyncThemeToggleIcon() {
  const use = document.querySelector("#theme-toggle use");
  if (use) use.setAttribute("href", _ccCurrentTheme() === "dark" ? "#i-sun" : "#i-moon");
}
function ccSetTheme(theme) {
  const next = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-bs-theme", next);
  try { localStorage.setItem("cc-theme", next); } catch (e) { /* nur diese Sitzung */ }
  _ccSyncThemeToggleIcon();
}
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  _ccSyncThemeToggleIcon();
  btn.addEventListener("click", () => ccSetTheme(_ccCurrentTheme() === "dark" ? "light" : "dark"));
});
