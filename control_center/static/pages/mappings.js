// control_center/static/pages/mappings.js
// Mapping-Administration (Phase 5.1): fünf Karten mit dem Live-Bestand je
// Mapping-Typ, nur lesend. Fachlogik (Validierung, Normalisierung, Etag) liegt
// ausschließlich im Backend (services/mapping_admin.py); diese Seite zeigt an,
// was GET /api/v1/admin/mappings/{mapping_id} liefert. Bearbeiten folgt in den
// nächsten Ausbaustufen — hier gibt es bewusst keine Schaltfläche dafür.
(function () {
  "use strict";

  // Reihenfolge = Darstellung. `count` liest die Kennzahl aus der Antwort,
  // `detail` optional eine Zusatzzeile (z. B. Kanäle je Kategorie-Summe).
  const MAPPING_TYPES = [
    {
      id: "channel-genre", title: "Channel-Genre", icon: "tag", unit: "Kanäle",
      description: "Primär- und Sekundärgenre je YouTube-Kanal.",
      count: (b) => (b.entries || []).length,
    },
    {
      id: "genre-aliases", title: "Genre-Aliase", icon: "link", unit: "Aliase",
      description: "Schreibweisen, die auf ein kanonisches Genre abgebildet werden.",
      count: (b) => (b.entries || []).length,
    },
    {
      id: "genre-overrides", title: "Genre-Overrides", icon: "adjustments", unit: "Overrides",
      description: "Feste Zielgenres, die vor den Aliasen greifen.",
      count: (b) => (b.entries || []).length,
    },
    {
      id: "genre-filters", title: "Genre-Filter", icon: "filter", unit: "Filter",
      description: "Tags, die als Sekundärgenre ignoriert werden.",
      count: (b) => (b.values || []).length,
    },
    {
      id: "special-channels", title: "Spezialkanäle", icon: "microphone", unit: "Kategorien",
      description: "Podcast-, Compilation- und Playlist-Kanäle. Die Reihenfolge der Kategorien ist die Priorität.",
      count: (b) => (b.categories || []).length,
      detail: (b) => {
        const channels = (b.categories || []).reduce((n, c) => n + (c.channels || []).length, 0);
        return `${channels.toLocaleString("de-DE")} Kanäle in ${(b.categories || []).length.toLocaleString("de-DE")} Kategorien`;
      },
    },
  ];

  function cardId(type) { return `mappings-card-${type.id}`; }

  function cardHtml(type) {
    return `
      <div class="col-12 col-md-6 col-xl-4">
        <div class="card card-sm h-100" id="${cardId(type)}">
          <div class="card-body">
            <div class="row align-items-center g-3 mb-2">
              <div class="col-auto"><span class="avatar bg-teal-lt">${ccIcon(type.icon)}</span></div>
              <div class="col min-w-0">
                <div class="subheader">${_escapeHtml(type.title)}</div>
                <div class="text-secondary small">${_escapeHtml(type.description)}</div>
              </div>
            </div>
            <div id="${cardId(type)}-body"></div>
          </div>
        </div>
      </div>`;
  }

  function warningsHtml(warnings) {
    if (!warnings || !warnings.length) return "";
    return '<ul class="list-unstyled mt-2 mb-0">' + warnings.map((w) =>
      `<li class="text-yellow small text-break">${ccIcon("alert", "icon-sm me-1")}${_escapeHtml(w)}</li>`
    ).join("") + "</ul>";
  }

  function renderCount(type, body) {
    const el = document.getElementById(`${cardId(type)}-body`);
    if (!el) return;
    const n = type.count(body);
    if (!n) {
      ccState.empty(el, "Noch keine Einträge", "Die Datei enthält keine Einträge dieses Typs.");
      return;
    }
    const detail = type.detail ? `<div class="text-secondary small">${_escapeHtml(type.detail(body))}</div>` : "";
    el.innerHTML = `
      <div class="d-flex align-items-baseline gap-2">
        <span class="h1 mb-0">${_escapeHtml(n.toLocaleString("de-DE"))}</span>
        <span class="text-secondary">${_escapeHtml(type.unit)}</span>
      </div>
      ${detail}${warningsHtml(body.warnings)}`;
  }

  function renderFailure(type, err) {
    const el = document.getElementById(`${cardId(type)}-body`);
    if (!el) return;
    const status = err && err.status;
    if (status === 401) return; // ccApi hat bereits auf die Login-Ansicht umgeschaltet
    if (status === 403) { ccState.denied(el); return; }
    // Nur bei 5xx/Netzwerk ist "Erneut versuchen" sinnvoll (Standard Abschnitt 7).
    const retryable = !status || status >= 500;
    const message = (err && err.message) || "Nicht erreichbar.";
    ccState.error(el, `${type.title} nicht erreichbar: ${message}`, retryable ? () => loadCard(type) : undefined);
  }

  async function loadCard(type) {
    const el = document.getElementById(`${cardId(type)}-body`);
    if (el) ccState.loading(el);
    try {
      const body = await ccApi("GET", `/api/v1/admin/mappings/${type.id}`);
      renderCount(type, body || {});
    } catch (err) {
      renderFailure(type, err);
    }
  }

  function loadAll() {
    return Promise.all(MAPPING_TYPES.map(loadCard));
  }

  function renderCards() {
    const root = document.getElementById("mappings-content");
    if (!root) return;
    root.innerHTML = MAPPING_TYPES.map(cardHtml).join("");
  }

  function initPage() {
    checkAuth().then((who) => {
      if (!who) return;
      renderCards();
      document.getElementById("mappings-reload-btn")?.addEventListener("click", loadAll);
      loadAll();
    });
  }

  initPage();
})();
