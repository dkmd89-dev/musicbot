// control_center/static/pages/mappings_editor.js
// Mapping-Administration: Kern des Editors im Offcanvas (Panel, gemeinsame
// Darstellungshelfer, Vorschau-Ablauf, Speichern mit Bestätigung, 409-Dialog)
// und der Eintrags-Editor für Channel-Genre, Genre-Aliase und Genre-Overrides
// (ein Eintrag = eine Vorschau = ein PUT).
//
// Weitere Modi hängen sich über window.ccMappingsEditor ein und werden nach dieser
// Datei geladen: mappings_editor_lists.js (Filter, Spezialkanäle),
// mappings_editor_yaml.js (Rohtext), mappings_editor_versions.js (Backup/Restore).
// Ein Modus liefert previewRequest/renderPreview/saveRequest/reopen (siehe modes).
//
// Fachlogik liegt ausschließlich im Backend: Validierung, Normalisierung, Etag,
// Konflikterkennung und die Warnungen kommen aus POST .../preview; diese Dateien
// zeigen an und senden. Kein Fake-Erfolg: erst die Antwort des PUT/Restore
// löst Toast und Neuladen aus.
(function () {
  "use strict";

  const API = "/api/v1/admin/mappings";
  const PREVIEW_DELAY_MS = 400;
  const SEARCH_ROOT_ID = "mappings-root";

  // Formularfelder je Typ. `payload` baut den Request-Body aus dem Formular,
  // `fromEntry` füllt das Formular aus einem vorhandenen Eintrag.
  const FORMS = {
    "channel-genre": {
      keyLabel: "Kanal",
      payload: (f) => ({ primary: f.primary, secondary: f.secondary, description: f.description || null }),
      fromEntry: (e) => ({ primary: e.primary, secondary: e.secondary || [], description: e.description || "" }),
      empty: () => ({ primary: "", secondary: [], description: "" }),
    },
    "genre-aliases": {
      keyLabel: "Alias",
      payload: (f) => ({ canonical: f.canonical }),
      fromEntry: (e) => ({ canonical: e.canonical }),
      empty: () => ({ canonical: "" }),
    },
    "genre-overrides": {
      keyLabel: "Key (case-sensitiv)",
      payload: (f) => ({ override: f.override }),
      fromEntry: (e) => ({ override: e.override }),
      empty: () => ({ override: "" }),
    },
  };

  const ed = {
    mode: null, typeId: null, isNew: false, key: "", form: {}, preview: null,
    seq: 0, timer: null, saving: false, version: null, versionPreview: null,
    draft: {}, filterQuery: "", yamlText: "", yamlMeta: null,
  };

  const $ = (id) => document.getElementById(id);
  const info = (id) => (window.ccMappingsPage && window.ccMappingsPage.typeInfo(id)) || { id, title: id, unit: "" };

  // Registry, in die sich die Modi einhängen (siehe Kopfkommentar).
  const modes = {};      // Modusname -> { needsKey, previewRequest(), renderPreview(body), onPreviewError(err), saveRequest(), reopen() }
  const actions = {};    // data-action -> fn(element)
  const inputHandlers = [];    // fn(event) -> true, wenn behandelt
  const keydownHandlers = [];  // fn(event) -> true, wenn behandelt

  // ── Panel ──────────────────────────────────────────────────────────────

  function panel() {
    const el = $("mappings-editor");
    const Offcanvas = window.tabler && window.tabler.Offcanvas;
    return {
      show() { if (Offcanvas && el) Offcanvas.getOrCreateInstance(el).show(); else if (el) el.classList.add("show"); },
      hide() { if (Offcanvas && el) Offcanvas.getOrCreateInstance(el).hide(); else if (el) el.classList.remove("show"); },
    };
  }

  function setHeader(sub, title) {
    const s = $("mappings-editor-sub"); if (s) s.textContent = sub;
    const t = $("mappings-editor-title"); if (t) t.textContent = title;
  }

  function setFooter(showSave, status) {
    const save = $("mappings-editor-save");
    if (save) { save.hidden = !showSave; save.disabled = true; }
    const st = $("mappings-editor-status");
    if (st) st.textContent = status || "";
  }

  function errorHtml(message) {
    return `<div class="alert alert-danger" role="alert"><div class="d-flex">${ccIcon("alert", "me-2")}<div class="text-break">${_escapeHtml(message)}</div></div></div>`;
  }

  // Fehler der API im Editor zeigen (Draft bleibt). 401: ccApi hat die Login-Ansicht gewählt.
  function showApiError(target, err) {
    if (!target) return;
    if (err && err.status === 401) return;
    if (err && err.status === 403) { ccState.denied(target); return; }
    target.innerHTML = errorHtml((err && err.message) || "Nicht erreichbar.");
  }

  // ── Eintrag: Formular ──────────────────────────────────────────────────

  function chipsHtml(items) {
    return (items || []).map((g) => `<span class="badge bg-teal-lt cc-mapping-chip">${_escapeHtml(g)}<button type="button" class="btn-close ms-1"
      data-action="sec-remove" data-genre="${_escapeHtml(g)}" aria-label="${_escapeHtml(g)} entfernen"></button></span>`).join("");
  }

  function formHtml() {
    const type = ed.typeId;
    const f = ed.form;
    const keyField = `
      <div class="col-12 col-sm-6">
        <label class="form-label" for="mappings-f-key">${_escapeHtml(FORMS[type].keyLabel)}</label>
        <input id="mappings-f-key" class="form-control" data-field="key" value="${_escapeHtml(ed.key)}"${ed.isNew ? "" : " readonly"}>
      </div>`;
    let fields = "";
    if (type === "channel-genre") {
      fields = `
        <div class="col-12 col-sm-6"><label class="form-label" for="mappings-f-primary">Primärgenre</label>
          <input id="mappings-f-primary" class="form-control" data-field="primary" value="${_escapeHtml(f.primary)}"></div>
        <div class="col-12"><label class="form-label" for="mappings-f-sec">Sekundärgenres</label>
          <div id="mappings-f-chips" class="d-flex flex-wrap gap-1 mb-2">${chipsHtml(f.secondary)}</div>
          <input id="mappings-f-sec" class="form-control form-control-sm" data-field="sec-input" placeholder="Genre hinzufügen und Enter"></div>
        <div class="col-12"><label class="form-label" for="mappings-f-description">Beschreibung</label>
          <input id="mappings-f-description" class="form-control" data-field="description" value="${_escapeHtml(f.description)}"></div>`;
    } else if (type === "genre-aliases") {
      fields = `<div class="col-12 col-sm-6"><label class="form-label" for="mappings-f-canonical">Zielgenre</label>
        <input id="mappings-f-canonical" class="form-control" data-field="canonical" value="${_escapeHtml(f.canonical)}"></div>`;
    } else {
      fields = `<div class="col-12 col-sm-6"><label class="form-label" for="mappings-f-override">Zielgenre (Override)</label>
        <input id="mappings-f-override" class="form-control" data-field="override" value="${_escapeHtml(f.override)}"></div>`;
    }
    return `
      <div class="d-flex align-items-center gap-2 mb-3">
        <span class="badge flex-shrink-0 text-nowrap ${ed.isNew ? "bg-green-lt" : "bg-yellow-lt"}">${ccIcon(ed.isNew ? "plus" : "edit", "icon-sm me-1")}${ed.isNew ? "Neuer Eintrag" : "Eintrag bearbeiten"}</span>
        <span class="text-secondary small">Änderungen werden erst nach Vorschau und Bestätigung geschrieben.</span>
      </div>
      <div class="row g-2 mb-3">${keyField}${fields}</div>
      <div id="mappings-editor-message"></div>
      <h4 class="text-uppercase text-secondary fs-5 mb-2">Vorschau</h4>
      <div id="mappings-editor-preview" class="cc-mapping-diff p-3"></div>`;
  }

  function readForm() {
    const val = (field) => { const el = document.querySelector(`#mappings-editor-body [data-field="${field}"]`); return el ? String(el.value || "").trim() : ""; };
    ed.key = ed.isNew ? val("key") : ed.key;
    if (ed.typeId === "channel-genre") { ed.form.primary = val("primary"); ed.form.description = val("description"); }
    else if (ed.typeId === "genre-aliases") ed.form.canonical = val("canonical");
    else ed.form.override = val("override");
  }

  // ── Eintrag: Vorschau ──────────────────────────────────────────────────

  function scheduleFormPreview() {
    clearTimeout(ed.timer);
    ed.seq += 1;
    ed.preview = null;
    const save = $("mappings-editor-save"); if (save) save.disabled = true;
    if (modes[ed.mode].needsKey && !ed.key) { renderPreviewHint("Schlüssel eingeben — die Vorschau erscheint automatisch."); return; }
    renderPreviewHint("Vorschau wird berechnet …");
    const seq = ed.seq;
    ed.timer = setTimeout(() => runFormPreview(seq), PREVIEW_DELAY_MS);
  }

  function renderPreviewHint(text) {
    const el = $("mappings-editor-preview");
    if (el) el.innerHTML = `<div class="text-secondary">${ccIcon("info", "icon-sm me-1")}${_escapeHtml(text)}</div>`;
  }

  async function runFormPreview(seq) {
    const mode = modes[ed.mode];
    const request = mode.previewRequest();
    let body;
    try {
      body = await ccApi("POST", request.path, request.body);
    } catch (err) {
      if (seq !== ed.seq) return; // veraltete Antwort verwerfen
      if (mode.onPreviewError && mode.onPreviewError(err)) return;
      showApiError($("mappings-editor-preview"), err);
      return;
    }
    if (seq !== ed.seq) return;   // ein neuerer Tastendruck hat Vorrang
    ed.preview = body;
    mode.renderPreview(body);
    const save = $("mappings-editor-save");
    if (save) save.disabled = !isWritable(body.change);
  }

  // Diese Änderungsarten schreibt das Backend (cleanup = bereinigte Datei zurückschreiben).
  const isWritable = (change) => change === "create" || change === "update" || change === "cleanup" || change === "format";

  function changeBadge(change) {
    if (change === "format") return `<span class="badge bg-yellow-lt">${ccIcon("edit", "icon-sm me-1")}Formatierung/Kommentare</span>`;
    if (change === "cleanup") return `<span class="badge bg-yellow-lt">${ccIcon("edit", "icon-sm me-1")}Bereinigung</span>`;
    if (change === "create") return `<span class="badge bg-green-lt">${ccIcon("plus", "icon-sm me-1")}Neu</span>`;
    if (change === "update") return `<span class="badge bg-yellow-lt">${ccIcon("edit", "icon-sm me-1")}Änderung</span>`;
    return `<span class="badge bg-secondary-lt">${ccIcon("check", "icon-sm me-1")}Keine Änderung</span>`;
  }

  const diffLine = (kind, text) => {
    const cls = { add: "cc-mapping-diff-add", del: "cc-mapping-diff-del", mod: "cc-mapping-diff-mod" }[kind];
    const icon = { add: "plus", del: "minus", mod: "edit" }[kind];
    return `<div class="${cls} text-break">${ccIcon(icon, "icon-sm me-1")}${text}</div>`;
  };

  function warningsHtml(warnings) {
    return (warnings || []).map((w) => `<div class="alert alert-warning mb-2" role="alert"><div class="d-flex">${ccIcon("alert", "me-2")}<div class="text-break">${_escapeHtml(w)}</div></div></div>`).join("");
  }

  function formDiff(body) {
    const key = `<code>${_escapeHtml(body.key)}</code>`;
    const ex = body.existing;
    if (ed.typeId === "genre-aliases") {
      return ex ? diffLine("mod", `${key}: <span class="cc-mapping-diff-del">${_escapeHtml(ex.canonical)}</span> → <strong>${_escapeHtml(body.canonical)}</strong>`)
                : diffLine("add", `${key}: ${_escapeHtml(body.canonical)}`);
    }
    if (ed.typeId === "genre-overrides") {
      return ex ? diffLine("mod", `${key}: <span class="cc-mapping-diff-del">${_escapeHtml(ex.override)}</span> → <strong>${_escapeHtml(body.override)}</strong>`)
                : diffLine("add", `${key}: ${_escapeHtml(body.override)}`);
    }
    // channel-genre
    let html = "";
    if (!ex) html += diffLine("add", `${key}: ${_escapeHtml(body.primary)}`);
    else if (body.primary_changed) html += diffLine("mod", `Primär: <span class="cc-mapping-diff-del">${_escapeHtml(ex.primary)}</span> → <strong>${_escapeHtml(body.primary)}</strong>`);
    (body.added || []).forEach((g) => { html += diffLine("add", `Sekundär: ${_escapeHtml(g)}`); });
    (body.removed || []).forEach((g) => { html += diffLine("del", `Sekundär: ${_escapeHtml(g)}`); });
    if (ex && (ex.description || "") !== (body.description || "")) {
      html += diffLine("mod", `Beschreibung: <span class="cc-mapping-diff-del">${_escapeHtml(ex.description || "—")}</span> → <strong>${_escapeHtml(body.description || "—")}</strong>`);
    }
    return html;
  }

  function renderFormPreview(body) {
    const el = $("mappings-editor-preview");
    if (!el) return;
    const lines = body.change === "unchanged" ? '<div class="text-secondary">Keine Änderung gegenüber dem gespeicherten Stand.</div>' : formDiff(body);
    const comment = body.comment_warning
      ? `<div class="alert alert-info mt-2 mb-0" role="note"><div class="d-flex">${ccIcon("info", "me-2")}<div>${_escapeHtml(body.comment_warning)}</div></div></div>` : "";
    el.innerHTML = `<div class="mb-2">${changeBadge(body.change)} <span class="text-secondary small ms-1">change: ${_escapeHtml(body.change)}</span></div>${lines}${comment}`;
    const msg = $("mappings-editor-message");
    if (msg) msg.innerHTML = warningsHtml(body.warnings)
      + `<div class="alert alert-info" role="note"><div class="d-flex">${ccIcon("info", "me-2")}<div>Der Bot lädt die Mapping-Dateien beim Start: die Änderung wirkt nach Bot-Neustart. Die bisherige Datei wird vorher als Version gesichert.</div></div></div>`;
  }

  // ── Eintrag: Öffnen und Speichern ──────────────────────────────────────

  async function openEntry(typeId, key, isNew) {
    Object.assign(ed, { mode: "entry", typeId, isNew, key: isNew ? "" : key, form: FORMS[typeId].empty(), preview: null, version: null });
    ed.seq += 1; clearTimeout(ed.timer);
    setHeader(info(typeId).title, isNew ? "Neuer Eintrag" : key);
    setFooter(true, "");
    const body = $("mappings-editor-body");
    panel().show();
    if (!isNew) {
      if (body) ccState.loading(body);
      try {
        const res = await ccApi("GET", `${API}/${typeId}/entry?key=${encodeURIComponent(key)}`);
        if (res && res.exists && res.entry) ed.form = FORMS[typeId].fromEntry(res.entry);
        else { ed.isNew = true; ed.key = key; }
      } catch (err) { showApiError(body, err); return; }
    }
    if (body) body.innerHTML = formHtml();
    scheduleFormPreview();
  }

  async function saveDraft() {
    if (ed.saving || !ed.preview || !isWritable(ed.preview.change)) return;
    const mode = modes[ed.mode];
    const request = mode.saveRequest();
    const ok = await ccConfirm({ title: request.confirm.title, text: request.confirm.text, confirmLabel: "Speichern" });
    if (!ok) return;
    ed.saving = true;
    const save = $("mappings-editor-save"); if (save) save.disabled = true;
    const msg = $("mappings-editor-message");
    try {
      const res = await ccApi("PUT", request.url, Object.assign({}, request.payload, { etag: ed.preview.etag }));
      ccToast("ok", res.written ? request.toastTitle : "Keine Änderung", res.message);
      panel().hide();
      window.ccMappingsPage.reloadType(ed.typeId);
    } catch (err) {
      if (err && err.status === 409) await onConflict(err);
      else showApiError(msg, err);
      if (save) save.disabled = !ed.preview;
    } finally {
      ed.saving = false;
    }
  }

  // 409: nichts wurde überschrieben. Der Nutzer entscheidet: Entwurf verwerfen und neu laden, oder weiterarbeiten.
  async function onConflict(err) {
    const reload = await ccConfirm({
      title: "Andere Änderung erkannt",
      text: `${err.message} Neu laden verwirft deinen Entwurf.`,
      confirmLabel: "Neu laden und verwerfen",
    });
    if (!reload) return;
    await window.ccMappingsPage.reloadType(ed.typeId);
    await modes[ed.mode].reopen();
  }

  // ── Eintrags-Modus registrieren ────────────────────────────────────────

  modes.entry = {
    needsKey: true,
    previewRequest: () => ({
      path: `${API}/${ed.typeId}/preview?key=${encodeURIComponent(ed.key)}`,
      body: FORMS[ed.typeId].payload(ed.form),
    }),
    renderPreview: renderFormPreview,
    saveRequest: () => ({
      url: `${API}/${ed.typeId}?key=${encodeURIComponent(ed.key)}`,
      payload: FORMS[ed.typeId].payload(ed.form),
      confirm: {
        title: `${info(ed.typeId).title}: '${ed.key}' speichern?`,
        text: ed.preview.change === "create"
          ? "Der Eintrag wird neu angelegt. Die Datei wird neu geschrieben, Kommentare gehen verloren."
          : "Der Eintrag wird geändert. Die Datei wird neu geschrieben, Kommentare gehen verloren.",
      },
      toastTitle: "Mapping gespeichert",
    }),
    reopen: () => openEntry(ed.typeId, ed.key, ed.isNew),
  };

  // ── Ereignisse (delegiert) ─────────────────────────────────────────────

  actions.edit = (el) => { if (FORMS[el.dataset.type]) openEntry(el.dataset.type, el.dataset.key, false); };
  actions.new = (el) => { if (FORMS[el.dataset.type]) openEntry(el.dataset.type, "", true); };
  actions.save = () => saveDraft();
  actions["sec-remove"] = (el) => {
    ed.form.secondary = (ed.form.secondary || []).filter((g) => g !== el.dataset.genre);
    refreshChips();
    scheduleFormPreview();
  };

  function onClick(event) {
    const el = event.target && event.target.closest ? event.target.closest("[data-action]") : null;
    const handler = el ? actions[el.dataset.action] : null;
    if (handler) handler(el);
  }

  function refreshChips() {
    const chips = $("mappings-f-chips");
    if (chips) chips.innerHTML = chipsHtml(ed.form.secondary);
  }

  function onInput(event) {
    if (inputHandlers.some((handle) => handle(event))) return;
    if (ed.mode !== "entry") return;
    const t = event.target;
    if (!t || !t.dataset || !t.dataset.field || t.dataset.field === "sec-input") return;
    readForm();
    scheduleFormPreview();
  }

  function onKeydown(event) {
    if (keydownHandlers.some((handle) => handle(event))) return;
    const t = event.target;
    if (ed.mode !== "entry" || !t || !t.dataset || t.dataset.field !== "sec-input") return;
    if (event.key !== "Enter" && event.key !== ",") return;
    if (event.preventDefault) event.preventDefault();
    const genre = String(t.value || "").trim();
    if (!genre) return;
    if (!(ed.form.secondary || []).some((g) => g.toLowerCase() === genre.toLowerCase())) ed.form.secondary = (ed.form.secondary || []).concat([genre]);
    t.value = "";
    refreshChips();
    scheduleFormPreview();
  }

  function init() {
    const root = $(SEARCH_ROOT_ID);
    if (root) root.addEventListener("click", onClick);
    const editor = $("mappings-editor");
    if (editor) {
      editor.addEventListener("click", onClick);
      editor.addEventListener("input", onInput);
      editor.addEventListener("keydown", onKeydown);
    }
  }

  // Schnittstelle für die Modus-Dateien (werden nach dieser Datei geladen).
  window.ccMappingsEditor = {
    API, ed, $, info, modes, actions, inputHandlers, keydownHandlers,
    panel, setHeader, setFooter, showApiError, changeBadge, diffLine, warningsHtml,
    scheduleFormPreview, onConflict,
  };

  // mappings.js meldet sich nach checkAuth(); der Editor hängt sich danach an.
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
