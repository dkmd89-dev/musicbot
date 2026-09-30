// control_center/static/pages/mappings.js
// Mapping-Administration (Phase 5.1c): Kacheln als Tabs, darunter die Daten des
// gewählten Mapping-Typs (Tabelle mit Suche und Paging bzw. Chip-Liste bzw.
// Kategorien). Nur lesend. Fachlogik (Validierung, Normalisierung, Etag) liegt
// ausschließlich im Backend (services/mapping_admin.py); diese Seite zeigt an,
// was GET /api/v1/admin/mappings/{mapping_id} liefert. Suche und Paging laufen
// clientseitig, weil die API die komplette Liste ohne Paginierung liefert.
// Bearbeiten (alle sechs Typen) und die Versionen liegen in
// mappings_editor.js; diese Datei liefert die Aktionsknöpfe (data-action) und
// stellt dem Editor window.ccMappingsPage.reloadType() und treeHtml() bereit.
(function () {
  "use strict";

  const PAGE_SIZE = 50;

  const chips = (items) => (items || []).map((t) => `<span class="badge bg-secondary-lt me-1">${_escapeHtml(t)}</span>`).join("");

  // Reihenfolge = Darstellung. `count` liest die Kennzahl aus der Antwort,
  // `rows`/`view` bestimmen die Darstellung im Tab.
  const MAPPING_TYPES = [
    {
      id: "channel-genre", title: "Channel-Genre", icon: "tag", unit: "Kanäle", kind: "table", editable: true,
      searchLabel: "Kanäle suchen",
      count: (b) => (b.entries || []).length,
      items: (b) => b.entries || [],
      matches: (e, q) => [e.key, e.primary, (e.secondary || []).join(" "), e.description || ""].join(" ").toLowerCase().includes(q),
      head: '<th>Kanal</th><th>Primär</th><th>Sekundär</th><th class="d-none d-md-table-cell">Beschreibung</th>',
      row: (e) => `<td class="text-break">${_escapeHtml(e.key)}</td><td>${_escapeHtml(e.primary)}</td>`
        + `<td>${chips(e.secondary)}</td><td class="d-none d-md-table-cell text-secondary">${_escapeHtml(e.description || "")}</td>`,
    },
    {
      id: "genre-aliases", title: "Genre-Aliase", icon: "link", unit: "Aliase", kind: "table", editable: true,
      searchLabel: "Aliase suchen",
      count: (b) => (b.entries || []).length,
      items: (b) => b.entries || [],
      matches: (e, q) => `${e.key} ${e.canonical}`.toLowerCase().includes(q),
      head: "<th>Alias</th><th>Zielgenre</th>",
      row: (e) => `<td class="text-break">${_escapeHtml(e.key)}</td><td>${_escapeHtml(e.canonical)}</td>`,
    },
    {
      id: "genre-overrides", title: "Genre-Overrides", icon: "adjustments", unit: "Overrides", kind: "table", editable: true,
      searchLabel: "Overrides suchen",
      count: (b) => (b.entries || []).length,
      items: (b) => b.entries || [],
      matches: (e, q) => `${e.key} ${e.override}`.toLowerCase().includes(q),
      head: '<th>Key <span class="text-secondary fw-normal small">(case-sensitiv)</span></th><th>Override</th>',
      row: (e) => `<td class="text-break">${_escapeHtml(e.key)}</td><td>${_escapeHtml(e.override)}</td>`,
    },
    {
      id: "genre-filters", title: "Genre-Filter", icon: "filter", unit: "Filter", kind: "chips", listEditable: true,
      searchLabel: "Filter suchen",
      count: (b) => (b.values || []).length,
      items: (b) => b.values || [],
      matches: (v, q) => String(v).toLowerCase().includes(q),
    },
    {
      id: "special-channels", title: "Spezialkanäle", icon: "microphone", unit: "Kategorien", kind: "categories", listEditable: true,
      searchLabel: "Kanäle suchen",
      count: (b) => (b.categories || []).length,
      items: (b) => b.categories || [],
      detail: (b) => {
        const channels = (b.categories || []).reduce((n, c) => n + (c.channels || []).length, 0);
        return `${channels.toLocaleString("de-DE")} Kanäle`;
      },
    },
    {
      id: "genre-hierarchy", title: "Genre-Hierarchie", icon: "hierarchy", unit: "Genres", kind: "tree", treeEditable: true, noYaml: true,
      searchLabel: "Genres suchen",
      count: (b) => (b.entries || []).length,
      items: (b) => b.entries || [],
      matches: (e, q) => String(e.genre).toLowerCase().includes(q),
      detail: (b) => `${fmt((b.entries || []).filter((e) => e.parent === null || e.parent === undefined).length)} Wurzeln`,
    },
  ];

  // Zustand je Typ: geladene Antwort, Fehler, Suchtext, Seite. `status` ist der
  // Runtime-Status ("gespeichert" vs. "vom Bot angewendet") aus GET .../mappings/status.
  const state = { active: MAPPING_TYPES[0].id, byId: {}, status: null, treeOpen: new Set() };
  MAPPING_TYPES.forEach((t) => { state.byId[t.id] = { body: null, error: null, loading: true, query: "", page: 1 }; });

  const typeById = (id) => MAPPING_TYPES.find((t) => t.id === id);
  const fmt = (n) => Number(n).toLocaleString("de-DE");

  // ── Baumansicht (Genre-Hierarchie) ─────────────────────────────────────

  // Gemeinsamer Baum-Renderer für die Übersicht und den Editor. Die Tiefe kommt vom
  // Backend (entry.depth), der Renderer rechnet nichts fachlich nach. Aufklappen
  // läuft über eine Menge geöffneter Genres (`opts.open`) und `opts.toggleAction`;
  // `nodeExtras`/`nodeActions` liefern zusätzliche Badges bzw. Aktionsknöpfe je Knoten.
  function treeHtml(entries, opts) {
    const o = opts || {};
    const names = new Set(entries.map((e) => e.genre));
    const byName = new Map(entries.map((e) => [e.genre, e]));
    const children = new Map();
    const roots = [];
    entries.forEach((e) => {
      if (e.parent === null || e.parent === undefined || !names.has(e.parent)) roots.push(e);
      else children.set(e.parent, (children.get(e.parent) || []).concat([e]));
    });
    const q = String(o.query || "").trim().toLowerCase();
    const visible = new Set();
    if (q) {
      entries.filter((e) => String(e.genre).toLowerCase().includes(q)).forEach((e) => {
        let cur = e;
        while (cur && !visible.has(cur.genre)) { visible.add(cur.genre); cur = byName.get(cur.parent); }
      });
    }
    const byLabel = (a, b) => String(a.genre).localeCompare(String(b.genre), "de");
    const node = (e) => {
      const kids = (children.get(e.genre) || []).filter((k) => !q || visible.has(k.genre)).sort(byLabel);
      const total = (children.get(e.genre) || []).length;
      const open = !!q || (o.open && o.open.has(e.genre));
      const toggle = total
        ? `<button type="button" class="btn btn-sm btn-icon btn-ghost-secondary cc-mapping-tree-toggle${open ? "" : " cc-mapping-tree-closed"}" data-action="${_escapeHtml(o.toggleAction || "tree-toggle")}"
            data-genre="${_escapeHtml(e.genre)}" aria-expanded="${open}" title="${_escapeHtml(e.genre)} ${open ? "zuklappen" : "aufklappen"}"
            aria-label="${_escapeHtml(e.genre)} ${open ? "zuklappen" : "aufklappen"}">${ccIcon("chevron-down")}</button>`
        : '<span class="cc-mapping-tree-spacer" aria-hidden="true"></span>';
      const depth = e.depth === undefined ? "" : `<span class="badge bg-secondary-lt">Tiefe ${_escapeHtml(String(e.depth))}</span>`;
      const count = total ? `<span class="badge bg-teal-lt">${_escapeHtml(fmt(total))} Unterelement${total === 1 ? "" : "e"}</span>` : "";
      const row = `<div class="cc-mapping-tree-row d-flex flex-wrap align-items-center gap-1">${toggle}
        <span class="cc-mapping-tree-name text-break">${_escapeHtml(e.genre)}</span>${depth}${count}${o.nodeExtras ? o.nodeExtras(e, total) : ""}
        <span class="ms-auto d-flex flex-nowrap gap-1">${o.nodeActions ? o.nodeActions(e, total) : ""}</span></div>`;
      return `<div class="cc-mapping-tree-node">${row}${open && kids.length ? `<div class="cc-mapping-tree-children">${kids.map(node).join("")}</div>` : ""}</div>`;
    };
    const shown = roots.filter((e) => !q || visible.has(e.genre)).sort(byLabel);
    // Genres, die keine Wurzel erreicht (z. B. ein Zyklus im Entwurf), würden sonst
    // unsichtbar und ließen sich nicht mehr korrigieren: eigener Abschnitt.
    const reached = new Set();
    const reach = (e) => { reached.add(e.genre); (children.get(e.genre) || []).forEach((k) => { if (!reached.has(k.genre)) reach(k); }); };
    roots.forEach(reach);
    const detached = entries.filter((e) => !reached.has(e.genre) && (!q || String(e.genre).toLowerCase().includes(q))).sort(byLabel);
    const detachedHtml = detached.length
      ? `<div class="cc-mapping-tree-detached mt-3"><div class="text-danger small mb-1">${ccIcon("alert", "icon-sm me-1")}Nicht mit einer Wurzel verbunden (Zyklus?): ${_escapeHtml(fmt(detached.length))}</div>`
        + detached.map((e) => `<div class="cc-mapping-tree-row d-flex flex-wrap align-items-center gap-1"><span class="cc-mapping-tree-spacer" aria-hidden="true"></span>
            <span class="cc-mapping-tree-name text-break">${_escapeHtml(e.genre)}</span><span class="badge bg-red-lt">unter ${_escapeHtml(String(e.parent))}</span>${o.nodeExtras ? o.nodeExtras(e, 0) : ""}
            <span class="ms-auto d-flex flex-nowrap gap-1">${o.nodeActions ? o.nodeActions(e, 0) : ""}</span></div>`).join("") + "</div>"
      : "";
    if (!shown.length && !detached.length) return '<div class="text-secondary">Kein Genre passt zur Suche.</div>';
    return `<div class="cc-mapping-tree">${shown.map(node).join("")}</div>${detachedHtml}`;
  }

  // ── Kacheln ────────────────────────────────────────────────────────────

  // ── Runtime-Status ─────────────────────────────────────────────────────

  const RUNTIME_STATES = {
    applied: { kind: "ok", label: "Angewendet" },
    pending_restart: { kind: "warn", label: "Neustart nötig" },
    unknown: { kind: "neutral", label: "Runtime unbekannt" },
    unavailable: { kind: "error", label: "Datei fehlt" },
  };

  function runtimeStatusOf(id) {
    return state.status && state.status.byId ? state.status.byId[id] || null : null;
  }

  // Läuft der Bot nicht (veralteter/fehlender Snapshot), gilt der Vergleich nur für den letzten Lauf:
  // kein grünes "Angewendet", sondern ein neutraler Hinweis.
  function runtimeDef(st) {
    if (state.status && state.status.bot_running === false && (st.state === "applied" || st.state === "pending_restart")) {
      return { kind: "neutral", label: "Bot läuft nicht" };
    }
    return RUNTIME_STATES[st.state] || RUNTIME_STATES.unknown;
  }

  function runtimeBadgeHtml(id) {
    const st = runtimeStatusOf(id);
    if (!st) return "";
    const def = runtimeDef(st);
    return `<div class="mt-1" title="${_escapeHtml(st.message)}">${ccStatusBadge(def.kind, def.label)}</div>`;
  }

  function renderRuntimeStatus() {
    const el = document.getElementById("mappings-pane-status");
    if (!el) return;
    const st = runtimeStatusOf(state.active);
    if (!st) {
      const failed = state.status && state.status.error;
      el.hidden = !failed;
      el.innerHTML = failed
        ? `<div class="text-secondary small">${ccIcon("info", "icon-sm me-1")}Der Runtime-Status ist gerade nicht abrufbar.</div>` : "";
      return;
    }
    const def = runtimeDef(st);
    const restart = st.state === "pending_restart"
      ? ` <a class="ms-1" href="${_escapeHtml(apiUrl("/admin"))}">Bot neu starten (Administration)</a>` : "";
    const started = state.status.bot_started_at
      ? `<span class="text-secondary small ms-2">Bot gestartet ${_escapeHtml(new Date(state.status.bot_started_at).toLocaleString("de-DE"))}</span>` : "";
    el.hidden = false;
    el.innerHTML = `<div class="d-flex flex-wrap align-items-center gap-1">${ccStatusBadge(def.kind, def.label)}
      <span class="text-secondary small ms-1 text-break">${_escapeHtml(st.message)}</span>${restart}${started}</div>`
      + (st.note ? `<div class="text-secondary small mt-1">${ccIcon("info", "icon-sm me-1")}${_escapeHtml(st.note)}</div>` : "");
  }

  async function loadStatus() {
    try {
      const body = (await ccApi("GET", "/api/v1/admin/mappings/status")) || {};
      const byId = {};
      (body.statuses || []).forEach((entry) => { byId[entry.mapping_id] = entry; });
      state.status = { byId, snapshot_status: body.snapshot_status, bot_running: !!body.bot_running, bot_started_at: body.bot_started_at || null };
    } catch (err) {
      if (err && err.status === 401) return;
      state.status = { byId: {}, error: true };
    }
    renderTiles();
    renderRuntimeStatus();
  }

  function tileHtml(type) {
    const st = state.byId[type.id];
    const active = type.id === state.active;
    let value;
    if (st.loading) value = '<span class="placeholder-glow"><span class="placeholder col-4"></span></span>';
    else if (st.error) value = `<span class="text-danger small">${ccIcon("alert", "icon-sm me-1")}nicht erreichbar</span>`;
    else value = `<span class="h2 mb-0">${_escapeHtml(fmt(type.count(st.body)))}</span><span class="text-secondary small">${_escapeHtml(type.unit)}</span>`;
    const warnings = st.body && st.body.warnings ? st.body.warnings.length : 0;
    const warningText = `${fmt(warnings)} Hinweis${warnings === 1 ? "" : "e"}`;
    const badge = warnings
      ? `<span class="badge bg-yellow-lt ms-auto align-self-center" title="${_escapeHtml(warningText)}" aria-label="${_escapeHtml(warningText)}">${ccIcon("alert", "icon-sm me-1")}${_escapeHtml(fmt(warnings))}</span>` : "";
    return `
      <div class="col-6 col-md-4 col-xl">
        <button type="button" class="card card-sm w-100 text-start cc-mapping-tile${active ? " active" : ""}"
                data-action="tab" data-type="${_escapeHtml(type.id)}" role="tab" aria-selected="${active}">
          <div class="card-body">
            <div class="d-flex align-items-center gap-2 mb-1">
              <span class="avatar avatar-sm bg-teal-lt">${ccIcon(type.icon)}</span>
              <span class="subheader mb-0">${_escapeHtml(type.title)}</span>
            </div>
            <div class="d-flex align-items-baseline gap-2">${value}${badge}</div>
            ${runtimeBadgeHtml(type.id)}
          </div>
        </button>
      </div>`;
  }

  function renderTiles() {
    const el = document.getElementById("mappings-tiles");
    if (el) el.innerHTML = MAPPING_TYPES.map(tileHtml).join("");
  }

  // ── Karte des gewählten Typs ───────────────────────────────────────────

  function renderHead() {
    const type = typeById(state.active);
    const st = state.byId[type.id];
    const el = document.getElementById("mappings-pane-head");
    if (!el) return;
    const total = st.body ? type.count(st.body) : 0;
    const extra = st.body && type.detail ? ` · ${_escapeHtml(type.detail(st.body))}` : "";
    el.innerHTML = `
      <h3 class="card-title me-auto">${_escapeHtml(type.title)}
        <span class="text-secondary fw-normal">· ${_escapeHtml(fmt(total))} ${_escapeHtml(type.unit)}${extra}</span></h3>
      <div class="input-icon">
        <span class="input-icon-addon">${ccIcon("search")}</span>
        <input type="search" class="form-control form-control-sm" data-action="search"
               placeholder="${_escapeHtml(type.searchLabel)}" aria-label="${_escapeHtml(type.searchLabel)}"
               value="${_escapeHtml(st.query)}">
      </div>
      <div class="btn-list">
        <button type="button" class="btn btn-sm" data-action="versions" data-type="${_escapeHtml(type.id)}">${ccIcon("history", "me-1")}Versionen</button>
        ${type.noYaml ? "" : `<button type="button" class="btn btn-sm" data-action="yaml" data-type="${_escapeHtml(type.id)}" title="Rohtext bearbeiten (für Fortgeschrittene)">${ccIcon("code", "me-1")}YAML</button>`}
        ${type.editable ? `<button type="button" class="btn btn-sm btn-primary" data-action="new" data-type="${_escapeHtml(type.id)}">${ccIcon("plus", "me-1")}Neuer Eintrag</button>` : ""}
        ${type.listEditable ? `<button type="button" class="btn btn-sm btn-primary" data-action="edit-list" data-type="${_escapeHtml(type.id)}">${ccIcon("edit", "me-1")}Bearbeiten</button>` : ""}
        ${type.treeEditable ? `<button type="button" class="btn btn-sm btn-primary" data-action="edit-tree" data-type="${_escapeHtml(type.id)}">${ccIcon("edit", "me-1")}Bearbeiten</button>` : ""}
      </div>`;
  }

  function warningsHtml(warnings) {
    if (!warnings || !warnings.length) return "";
    return warnings.map((w) =>
      `<div class="alert alert-warning mb-2" role="alert"><div class="d-flex">${ccIcon("alert", "me-2")}<div class="text-break">${_escapeHtml(w)}</div></div></div>`
    ).join("");
  }

  // Clientseitige Suche über die komplette Liste (die API paginiert nicht).
  function filtered(type, st) {
    const q = st.query.trim().toLowerCase();
    const all = type.items(st.body);
    return q ? all.filter((e) => type.matches(e, q)) : all;
  }

  function pageOf(found, st) {
    const pages = Math.max(1, Math.ceil(found.length / PAGE_SIZE));
    st.page = Math.min(Math.max(1, st.page), pages);
    return { pages, slice: found.slice((st.page - 1) * PAGE_SIZE, st.page * PAGE_SIZE) };
  }

  function editCell(type, entry) {
    const label = `${entry.key} bearbeiten`;
    return `<td><button type="button" class="btn btn-sm btn-icon btn-ghost-secondary" data-action="edit"
      data-type="${_escapeHtml(type.id)}" data-key="${_escapeHtml(entry.key)}"
      title="${_escapeHtml(label)}" aria-label="${_escapeHtml(label)}">${ccIcon("edit")}</button></td>`;
  }

  function renderBody() {
    const type = typeById(state.active);
    const st = state.byId[type.id];
    const body = document.getElementById("mappings-pane-body");
    const foot = document.getElementById("mappings-pane-foot");
    if (!body) return;
    if (foot) { foot.hidden = true; foot.innerHTML = ""; }

    if (st.loading) { ccState.loading(body); return; }
    if (st.error) { renderFailure(type, st.error, body); return; }
    if (!type.count(st.body)) {
      ccState.empty(body, "Noch keine Einträge", "Die Datei enthält keine Einträge dieses Typs.");
      return;
    }

    if (type.kind === "table") {
      const found = filtered(type, st);
      const { pages, slice } = pageOf(found, st);
      if (!found.length) {
        body.innerHTML = '<div class="card-body">' + '<div class="empty py-3"><p class="empty-title">Keine Treffer</p>'
          + '<p class="empty-subtitle text-secondary">Kein Eintrag passt zur Suche.</p></div></div>';
        return;
      }
      body.innerHTML = warningsHtml(st.body.warnings)
        + `<div class="table-responsive"><table class="table card-table table-vcenter"><thead><tr>${type.head}<th class="w-1"></th></tr></thead><tbody>`
        + slice.map((e) => `<tr>${type.row(e)}${editCell(type, e)}</tr>`).join("") + "</tbody></table></div>";
      renderFoot(found.length, pages, st);
    } else if (type.kind === "tree") {
      body.innerHTML = '<div class="card-body">' + warningsHtml(st.body.warnings)
        + '<div class="text-secondary small mb-2">Die Tiefe im Baum ist die Genre-Priorität: bei mehreren Tags gewinnt das tiefere (spezifischere) Genre.</div>'
        + treeHtml(type.items(st.body), { query: st.query, open: state.treeOpen, toggleAction: "tree-toggle" }) + "</div>";
    } else if (type.kind === "chips") {
      const found = filtered(type, st);
      body.innerHTML = '<div class="card-body">' + warningsHtml(st.body.warnings)
        + (found.length
          ? `<div class="d-flex flex-wrap gap-1 cc-mapping-scroll">${found.map((v) => `<span class="badge bg-secondary-lt">${_escapeHtml(v)}</span>`).join("")}</div>`
          : '<div class="text-secondary">Kein Filter passt zur Suche.</div>')
        + "</div>";
      if (foot) { foot.hidden = false; foot.innerHTML = `<div class="text-secondary small">${_escapeHtml(fmt(found.length))} von ${_escapeHtml(fmt(type.count(st.body)))} Filtern</div>`; }
    } else {
      const q = st.query.trim().toLowerCase();
      const cats = type.items(st.body).map((c, i) => ({ c, i }))
        .map(({ c, i }) => ({ name: c.name, position: i + 1, all: c.channels || [],
          shown: q ? (c.channels || []).filter((ch) => String(ch).toLowerCase().includes(q) || c.name.toLowerCase().includes(q)) : (c.channels || []) }))
        .filter((c) => !q || c.shown.length);
      body.innerHTML = '<div class="card-body">' + warningsHtml(st.body.warnings)
        + `<div class="alert alert-info" role="note"><div class="d-flex">${ccIcon("info", "me-2")}<div>`
        + "Die Reihenfolge der Kategorien ist die Priorität (die frühere gewinnt). Die Runtime merged weiterhin mit "
        + "<code>Config.SPECIAL_CHANNELS</code> — hier wird nur die YAML-Quelle angezeigt.</div></div></div>"
        + (cats.length
          ? '<div class="row g-2">' + cats.map((c) => `
            <div class="col-12 col-lg-4"><div class="border rounded p-3 h-100">
              <div class="d-flex align-items-center gap-2 mb-2">
                <span class="badge bg-teal-lt cc-mapping-prio d-inline-flex align-items-center justify-content-center">${_escapeHtml(String(c.position))}</span>
                <strong class="me-auto text-break">${_escapeHtml(c.name)}</strong>
                <span class="text-secondary small">${_escapeHtml(fmt(c.all.length))} Kanäle</span>
              </div>
              <div class="d-flex flex-wrap gap-1">${c.shown.map((ch) => `<span class="badge bg-secondary-lt">${_escapeHtml(ch)}</span>`).join("")}</div>
            </div></div>`).join("") + "</div>"
          : '<div class="text-secondary">Kein Kanal passt zur Suche.</div>')
        + "</div>";
    }
  }

  function renderFoot(total, pages, st) {
    const foot = document.getElementById("mappings-pane-foot");
    if (!foot) return;
    const from = (st.page - 1) * PAGE_SIZE + 1;
    const to = Math.min(total, st.page * PAGE_SIZE);
    foot.hidden = false;
    foot.innerHTML = '<div class="d-flex align-items-center w-100">' + `<span class="text-secondary small">${PAGE_SIZE} pro Seite · ${_escapeHtml(fmt(from))}–${_escapeHtml(fmt(to))} von ${_escapeHtml(fmt(total))}</span>`
      + (pages > 1
        ? '<div class="btn-list ms-auto flex-nowrap align-items-center">'
          + `<button type="button" class="btn btn-sm btn-icon" data-action="page" data-page="${st.page - 1}" aria-label="Vorherige Seite"${st.page <= 1 ? " disabled" : ""}>‹</button>`
          + `<span class="text-secondary small">Seite ${_escapeHtml(fmt(st.page))} / ${_escapeHtml(fmt(pages))}</span>`
          + `<button type="button" class="btn btn-sm btn-icon" data-action="page" data-page="${st.page + 1}" aria-label="Nächste Seite"${st.page >= pages ? " disabled" : ""}>›</button></div>`
        : "") + "</div>";
  }

  function renderFailure(type, err, el) {
    const status = err && err.status;
    if (status === 401) return; // ccApi hat bereits auf die Login-Ansicht umgeschaltet
    if (status === 403) { ccState.denied(el); return; }
    // Nur bei 5xx/Netzwerk ist "Erneut versuchen" sinnvoll (Standard Abschnitt 7).
    const retryable = !status || status >= 500;
    const message = (err && err.message) || "Nicht erreichbar.";
    ccState.error(el, `${type.title} nicht erreichbar: ${message}`, retryable ? () => loadType(type) : undefined);
  }

  function renderAll() {
    renderTiles();
    renderHead();
    renderRuntimeStatus();
    renderBody();
  }

  // ── Laden ──────────────────────────────────────────────────────────────

  async function loadType(type) {
    const st = state.byId[type.id];
    st.loading = true; st.error = null;
    renderAll();
    try {
      st.body = (await ccApi("GET", `/api/v1/admin/mappings/${type.id}`)) || {};
    } catch (err) {
      st.body = null; st.error = err;
    }
    st.loading = false;
    renderAll();
  }

  function loadAll() {
    return Promise.all([...MAPPING_TYPES.map(loadType), loadStatus()]);
  }

  // ── Ereignisse (delegiert) ─────────────────────────────────────────────

  function onClick(event) {
    const el = event.target && event.target.closest ? event.target.closest("[data-action]") : null;
    if (!el) return;
    const action = el.dataset.action;
    if (action === "tab" && typeById(el.dataset.type)) {
      state.active = el.dataset.type;
      renderAll();
    } else if (action === "tree-toggle") {
      const genre = el.dataset.genre;
      if (state.treeOpen.has(genre)) state.treeOpen.delete(genre); else state.treeOpen.add(genre);
      renderBody();
    } else if (action === "page") {
      state.byId[state.active].page = Number(el.dataset.page) || 1;
      renderBody();
    }
  }

  function onInput(event) {
    const el = event.target && event.target.closest ? event.target.closest('[data-action="search"]') : null;
    if (!el) return;
    const st = state.byId[state.active];
    st.query = el.value || "";
    st.page = 1;
    renderBody();
  }

  // Schnittstelle fuer mappings_editor.js: nach Speichern/Restore den Bestand neu laden.
  window.ccMappingsPage = {
    // Nach Speichern/Restore: Bestand UND Runtime-Status neu laden (die Datei hat sich geändert).
    reloadType(id) { const type = typeById(id); return type ? Promise.all([loadType(type), loadStatus()]) : Promise.resolve(); },
    typeInfo(id) { const type = typeById(id); return type ? { id: type.id, title: type.title, unit: type.unit, editable: !!type.editable, listEditable: !!type.listEditable, treeEditable: !!type.treeEditable } : null; },
    treeHtml,
  };

  function initPage() {
    checkAuth().then((who) => {
      if (!who) return;
      const root = document.getElementById("mappings-root");
      if (root) { root.addEventListener("click", onClick); root.addEventListener("input", onInput); }
      document.getElementById("mappings-reload-btn")?.addEventListener("click", loadAll);
      renderAll();
      loadAll();
    });
  }

  initPage();
})();
