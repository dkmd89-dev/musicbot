// control_center/static/pages/mappings_editor.js
// Mapping-Administration (Phase 5.2/5.3): Editor im Offcanvas für Channel-Genre,
// Genre-Aliase und Genre-Overrides (ein Eintrag = eine Vorschau = ein PUT), für
// die Listen-Typen Genre-Filter (Chip-Liste) und Spezialkanäle (Kategorien in
// Prioritätsreihenfolge; ein Entwurf = eine Vorschau = ein PUT), den YAML-Editor
// (Rohtext, für Fortgeschrittene) sowie die Versionen (Backup/Restore) aller
// Mapping-Typen.
//
// Fachlogik liegt ausschließlich im Backend: Validierung, Normalisierung, Etag,
// Konflikterkennung und die Warnungen kommen aus POST .../preview; diese Datei
// zeigt an und sendet. Kein Fake-Erfolg: erst die Antwort des PUT/Restore
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

  // Listen-Typen: der ganze Bestand ist der Entwurf, das Backend bewertet ihn als Ganzes.
  const LISTS = {
    "genre-filters": {
      payload: (d) => ({ values: d.values }),
      load: (res) => ({ values: (res.values || []).slice() }),
    },
    "special-channels": {
      payload: (d) => ({ categories: d.categories }),
      load: (res) => ({ categories: (res.categories || []).map((c) => ({ name: c.name, channels: (c.channels || []).slice() })) }),
    },
  };
  const isList = (typeId) => !!LISTS[typeId];

  const ed = {
    mode: null, typeId: null, isNew: false, key: "", form: {}, preview: null,
    seq: 0, timer: null, saving: false, version: null, versionPreview: null,
    draft: {}, filterQuery: "", yamlText: "", yamlMeta: null,
  };
  const isYaml = () => ed.mode === "yaml";

  const $ = (id) => document.getElementById(id);
  const info = (id) => (window.ccMappingsPage && window.ccMappingsPage.typeInfo(id)) || { id, title: id, unit: "" };
  const fmtTime = (iso) => { const d = new Date(iso); return isNaN(d) ? String(iso) : d.toLocaleString("de-DE"); };
  const fmtBytes = (n) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1).replace(".", ",")} KB`);

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
    if (!isYaml() && !isList(ed.typeId) && !ed.key) { renderPreviewHint("Schlüssel eingeben — die Vorschau erscheint automatisch."); return; }
    renderPreviewHint("Vorschau wird berechnet …");
    const seq = ed.seq;
    ed.timer = setTimeout(() => runFormPreview(seq), PREVIEW_DELAY_MS);
  }

  function renderPreviewHint(text) {
    const el = $("mappings-editor-preview");
    if (el) el.innerHTML = `<div class="text-secondary">${ccIcon("info", "icon-sm me-1")}${_escapeHtml(text)}</div>`;
  }

  async function runFormPreview(seq) {
    const yaml = isYaml();
    const list = !yaml && isList(ed.typeId);
    const path = yaml ? `${API}/${ed.typeId}/yaml/preview`
      : (list ? `${API}/${ed.typeId}/preview` : `${API}/${ed.typeId}/preview?key=${encodeURIComponent(ed.key)}`);
    let body;
    try {
      body = await ccApi("POST", path, yaml ? { text: ed.yamlText } : (list ? LISTS[ed.typeId].payload(ed.draft) : FORMS[ed.typeId].payload(ed.form)));
    } catch (err) {
      if (seq !== ed.seq) return; // veraltete Antwort verwerfen
      if (yaml && err && err.status === 422) { renderYamlErrors(err.message); return; }
      showApiError($("mappings-editor-preview"), err);
      return;
    }
    if (seq !== ed.seq) return;   // ein neuerer Tastendruck hat Vorrang
    ed.preview = body;
    if (yaml) renderYamlPreview(body); else if (list) renderListPreview(body); else renderFormPreview(body);
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

  async function saveEntry() {
    if (ed.saving || !ed.preview || !isWritable(ed.preview.change)) return;
    const type = info(ed.typeId);
    const yaml = isYaml();
    const list = !yaml && isList(ed.typeId);
    const text = yaml
      ? "Der Text wird unverändert in die Datei geschrieben (Kommentare bleiben erhalten). Die bisherige Datei wird vorher als Version gesichert."
      : list
      ? "Der geänderte Bestand ersetzt die Datei. Die Datei wird neu geschrieben, Kommentare gehen verloren; die bisherige Datei wird als Version gesichert."
      : (ed.preview.change === "create"
        ? "Der Eintrag wird neu angelegt. Die Datei wird neu geschrieben, Kommentare gehen verloren."
        : "Der Eintrag wird geändert. Die Datei wird neu geschrieben, Kommentare gehen verloren.");
    const ok = await ccConfirm({
      title: yaml ? `${type.title} als YAML speichern?` : (list ? `${type.title} speichern?` : `${type.title}: '${ed.key}' speichern?`),
      text,
      confirmLabel: "Speichern",
    });
    if (!ok) return;
    ed.saving = true;
    const save = $("mappings-editor-save"); if (save) save.disabled = true;
    const msg = $("mappings-editor-message");
    try {
      const payload = yaml ? { text: ed.yamlText } : (list ? LISTS[ed.typeId].payload(ed.draft) : FORMS[ed.typeId].payload(ed.form));
      const url = yaml ? `${API}/${ed.typeId}/yaml` : (list ? `${API}/${ed.typeId}` : `${API}/${ed.typeId}?key=${encodeURIComponent(ed.key)}`);
      const res = await ccApi("PUT", url, Object.assign({}, payload, { etag: ed.preview.etag }));
      ccToast("ok", res.written ? (yaml ? "YAML gespeichert" : "Mapping gespeichert") : "Keine Änderung", res.message);
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
    if (ed.mode === "versions") await openVersions(ed.typeId);
    else if (ed.mode === "list") await openList(ed.typeId);
    else if (ed.mode === "yaml") await openYaml(ed.typeId);
    else await openEntry(ed.typeId, ed.key, ed.isNew);
  }

  // ── YAML-Editor (Rohtext, für Fortgeschrittene) ────────────────────────

  async function openYaml(typeId) {
    Object.assign(ed, { mode: "yaml", typeId, preview: null, version: null });
    ed.seq += 1; clearTimeout(ed.timer);
    setHeader(info(typeId).title, "YAML");
    setFooter(true, "");
    const body = $("mappings-editor-body");
    panel().show();
    if (body) ccState.loading(body);
    try {
      ed.yamlMeta = await ccApi("GET", `${API}/${typeId}/yaml`) || {};
    } catch (err) { showApiError(body, err); return; }
    ed.yamlText = ed.yamlMeta.text || "";
    renderYamlEditor();
    scheduleFormPreview();
  }

  function renderYamlEditor() {
    const body = $("mappings-editor-body");
    if (!body) return;
    const kb = Math.round((ed.yamlMeta.max_bytes || 0) / 1024);
    body.innerHTML = `
      <div class="alert alert-warning" role="note"><div class="d-flex">${ccIcon("alert", "me-2")}<div>
        <strong>Fortgeschritten:</strong> Der Text wird unverändert in die Datei geschrieben, <strong>Kommentare bleiben erhalten</strong>.
        Er wird vorher streng geprüft: genau ein Dokument, keine Anker/Aliase, Tags oder doppelten Keys, höchstens ${_escapeHtml(String(kb))} KB;
        dazu gelten dieselben fachlichen Regeln wie im normalen Editor. Für die meisten Änderungen ist der normale Editor die bessere Wahl.</div></div></div>
      <label class="form-label" for="mappings-f-yaml">${_escapeHtml(ed.yamlMeta.filename || "YAML")}</label>
      <textarea id="mappings-f-yaml" class="form-control cc-mapping-yaml mb-3" data-field="yaml-text" rows="18"
        spellcheck="false" wrap="off" autocomplete="off" autocapitalize="off">${_escapeHtml(ed.yamlText)}</textarea>
      <div id="mappings-editor-message"></div>
      <h4 class="text-uppercase text-secondary fs-5 mb-2">Vorschau</h4>
      <div id="mappings-editor-preview" class="cc-mapping-diff p-3"></div>`;
  }

  function textDiffHtml(lines) {
    if (!lines || !lines.length) return "";
    const cls = (l) => (l.startsWith("+++") || l.startsWith("---") || l.startsWith("@@") ? "cc-t-time" : (l.startsWith("+") ? "cc-t-ok" : (l.startsWith("-") ? "cc-t-err" : "")));
    return `<pre class="cc-terminal cc-mapping-textdiff mt-2 mb-0">${lines.map((l) => `<span class="${cls(l)}">${_escapeHtml(l)}</span>`).join("\n")}</pre>`;
  }

  function renderYamlPreview(body) {
    const el = $("mappings-editor-preview");
    if (!el) return;
    const items = [].concat(
      (body.added || []).map((t) => diffLine("add", _escapeHtml(t))),
      (body.removed || []).map((t) => diffLine("del", _escapeHtml(t))),
      (body.changed || []).map((t) => diffLine("mod", _escapeHtml(t))),
    ).join("");
    let lines;
    if (body.change === "unchanged") lines = '<div class="text-secondary">Keine Änderung gegenüber dem gespeicherten Stand.</div>';
    else if (body.change === "format") lines = '<div class="text-secondary">Kein fachlicher Unterschied — nur Formatierung oder Kommentare ändern sich.</div>';
    else lines = items;
    el.innerHTML = `<div class="mb-2">${changeBadge(body.change)} <span class="text-secondary small ms-1">change: ${_escapeHtml(body.change)}</span></div>${lines}${textDiffHtml(body.text_diff)}`;
    const msg = $("mappings-editor-message");
    if (msg) msg.innerHTML = warningsHtml(body.warnings)
      + `<div class="alert alert-info" role="note"><div class="d-flex">${ccIcon("info", "me-2")}<div>Der Bot lädt die Mapping-Dateien beim Start: die Änderung wirkt nach Bot-Neustart. Die bisherige Datei wird vorher als Version gesichert.</div></div></div>`;
  }

  // 422: alle Prüffehler des Backends, eine Zeile je Fehler (Text wird nie geschrieben).
  function renderYamlErrors(message) {
    const el = $("mappings-editor-preview");
    if (!el) return;
    const lines = String(message || "Der Text ist ungültig.").split("\n").filter((l) => l.trim());
    el.innerHTML = `<div class="text-danger mb-1">${ccIcon("alert", "icon-sm me-1")}Der Text kann so nicht gespeichert werden:</div>
      <ul class="mb-0 text-danger small">${lines.map((l) => `<li class="text-break">${_escapeHtml(l)}</li>`).join("")}</ul>`;
    const msg = $("mappings-editor-message"); if (msg) msg.innerHTML = "";
    const save = $("mappings-editor-save"); if (save) save.disabled = true;
  }

  // ── Listen-Typen: Filter und Spezialkanäle ─────────────────────────────

  async function openList(typeId) {
    Object.assign(ed, { mode: "list", typeId, preview: null, version: null, filterQuery: "" });
    ed.seq += 1; clearTimeout(ed.timer);
    setHeader(info(typeId).title, "Bearbeiten");
    setFooter(true, "");
    const body = $("mappings-editor-body");
    panel().show();
    if (body) ccState.loading(body);
    try {
      ed.draft = LISTS[typeId].load(await ccApi("GET", `${API}/${typeId}`) || {});
    } catch (err) { showApiError(body, err); return; }
    renderListEditor();
    scheduleFormPreview();
  }

  function removeBtn(action, data, label) {
    const attrs = Object.entries(data).map(([k, v]) => `data-${k}="${_escapeHtml(v)}"`).join(" ");
    return `<button type="button" class="btn-close ms-1" data-action="${action}" ${attrs} aria-label="${_escapeHtml(label)}"></button>`;
  }

  function filterChipsHtml() {
    const q = ed.filterQuery.trim().toLowerCase();
    const shown = ed.draft.values.filter((v) => !q || v.toLowerCase().includes(q));
    if (!shown.length) return '<span class="text-secondary small">Kein Filter passt zur Suche.</span>';
    return shown.map((v) => `<span class="badge bg-secondary-lt cc-mapping-chip">${_escapeHtml(v)}${removeBtn("flt-remove", { value: v }, `${v} entfernen`)}</span>`).join("");
  }

  function categoryCardHtml(cat, i, total) {
    const arrow = (dir, disabled) => `<button type="button" class="btn btn-sm btn-icon btn-ghost-secondary" data-action="cat-${dir}" data-index="${i}"
      title="${_escapeHtml(cat.name)} nach ${dir === "up" ? "oben" : "unten"}" aria-label="${_escapeHtml(cat.name)} nach ${dir === "up" ? "oben" : "unten"}"${disabled ? " disabled" : ""}>${ccIcon("arrow-" + dir)}</button>`;
    return `
      <div class="card card-sm mb-2"><div class="card-body">
        <div class="d-flex align-items-center gap-2 mb-2">
          <span class="badge bg-teal-lt cc-mapping-prio d-inline-flex align-items-center justify-content-center">${i + 1}</span>
          <strong class="me-auto text-break">${_escapeHtml(cat.name)}</strong>
          ${arrow("up", i === 0)}${arrow("down", i === total - 1)}
          <button type="button" class="btn btn-sm btn-icon btn-ghost-danger" data-action="cat-remove" data-index="${i}"
            title="${_escapeHtml(cat.name)} entfernen" aria-label="${_escapeHtml(cat.name)} entfernen">${ccIcon("trash")}</button>
        </div>
        <div class="d-flex flex-wrap gap-1 mb-2">${cat.channels.map((ch) => `<span class="badge bg-secondary-lt cc-mapping-chip">${_escapeHtml(ch)}${removeBtn("ch-remove", { index: i, channel: ch }, `${ch} entfernen`)}</span>`).join("")}</div>
        <input id="mappings-ch-input-${i}" class="form-control form-control-sm" data-field="ch-input" data-index="${i}"
          placeholder="Kanal hinzufügen und Enter" aria-label="Kanal zu ${_escapeHtml(cat.name)} hinzufügen">
      </div></div>`;
  }

  function renderListEditor() {
    const body = $("mappings-editor-body");
    if (!body) return;
    let inner;
    if (ed.typeId === "genre-filters") {
      inner = `
        <div class="input-icon mb-2"><span class="input-icon-addon">${ccIcon("search")}</span>
          <input type="search" class="form-control form-control-sm" data-field="flt-search" placeholder="Filter suchen (${_escapeHtml(String(ed.draft.values.length))} Einträge)" aria-label="Filter durchsuchen" value="${_escapeHtml(ed.filterQuery)}"></div>
        <div id="mappings-f-chips" class="cc-mapping-scroll border rounded p-2 mb-2 d-flex flex-wrap gap-1">${filterChipsHtml()}</div>
        <div class="row g-2 mb-3"><div class="col"><input id="mappings-flt-input" class="form-control form-control-sm" data-field="flt-input" placeholder="Neuer Filter (wird kleingeschrieben)" aria-label="Neuer Filter"></div>
          <div class="col-auto"><button type="button" class="btn btn-sm" data-action="flt-add">${ccIcon("plus", "me-1")}Hinzufügen</button></div></div>`;
    } else {
      const cats = ed.draft.categories;
      inner = `
        <div class="alert alert-info" role="note"><div class="d-flex">${ccIcon("info", "me-2")}<div>Die <strong>Reihenfolge der Kategorien ist die Priorität</strong>: steht ein Kanal in mehreren, gewinnt die höhere.
          Die Runtime merged weiterhin mit <code>Config.SPECIAL_CHANNELS</code> — hier wird nur die YAML-Quelle verwaltet.</div></div></div>
        <div id="mappings-f-cats">${cats.map((c, i) => categoryCardHtml(c, i, cats.length)).join("")}</div>
        <div class="row g-2 mb-3"><div class="col"><input id="mappings-cat-input" class="form-control form-control-sm" data-field="cat-name" placeholder="Neue Kategorie" aria-label="Neue Kategorie"></div>
          <div class="col-auto"><button type="button" class="btn btn-sm" data-action="cat-add">${ccIcon("plus", "me-1")}Neue Kategorie</button></div></div>`;
    }
    body.innerHTML = `
      <div class="d-flex align-items-center gap-2 mb-3"><span class="badge flex-shrink-0 text-nowrap bg-yellow-lt">${ccIcon("edit", "icon-sm me-1")}Bestand bearbeiten</span>
        <span class="text-secondary small">Änderungen werden erst nach Vorschau und Bestätigung geschrieben.</span></div>
      ${inner}
      <div id="mappings-editor-message"></div>
      <h4 class="text-uppercase text-secondary fs-5 mb-2">Vorschau</h4>
      <div id="mappings-editor-preview" class="cc-mapping-diff p-3"></div>`;
  }

  const fieldEl = (name) => document.querySelector(`#mappings-editor-body [data-field="${name}"]`);

  function refocus(id) { const el = $(id); if (el && el.focus) el.focus(); }

  function draftChanged(focusId) {
    if (ed.typeId === "genre-filters") { const chips = $("mappings-f-chips"); if (chips) chips.innerHTML = filterChipsHtml(); }
    else renderListEditor();
    scheduleFormPreview();
    if (focusId) refocus(focusId);
  }

  const hasCi = (list, value) => list.some((x) => x.toLowerCase() === value.toLowerCase());

  function listAction(a, el) {
    const d = ed.draft;
    const i = Number(el.dataset.index);
    if (a === "flt-add") { const input = fieldEl("flt-input"); const value = input ? input.value : ""; if (input) input.value = ""; addFilter(value); }
    else if (a === "flt-remove") { d.values = d.values.filter((v) => v !== el.dataset.value); draftChanged(); }
    else if (a === "cat-up" && i > 0) { [d.categories[i - 1], d.categories[i]] = [d.categories[i], d.categories[i - 1]]; draftChanged(); }
    else if (a === "cat-down" && i < d.categories.length - 1) { [d.categories[i + 1], d.categories[i]] = [d.categories[i], d.categories[i + 1]]; draftChanged(); }
    else if (a === "cat-remove") { d.categories.splice(i, 1); draftChanged(); }
    else if (a === "ch-remove") { d.categories[i].channels = d.categories[i].channels.filter((c) => c !== el.dataset.channel); draftChanged(`mappings-ch-input-${i}`); }
    else if (a === "cat-add") { const input = fieldEl("cat-name"); const value = input ? input.value : ""; if (input) input.value = ""; addCategory(value); }
  }

  function addFilter(raw) {
    const value = String(raw || "").trim();
    if (!value || hasCi(ed.draft.values, value)) return;
    ed.draft.values = ed.draft.values.concat([value]);
    draftChanged("mappings-flt-input");
  }

  function addCategory(raw) {
    const name = String(raw || "").trim();
    if (!name || ed.draft.categories.some((c) => c.name.toLowerCase() === name.toLowerCase())) return;
    ed.draft.categories = ed.draft.categories.concat([{ name, channels: [] }]);
    draftChanged("mappings-cat-input");
  }

  function addChannel(index, raw) {
    const channel = String(raw || "").trim();
    const cat = ed.draft.categories[index];
    if (!channel || !cat || hasCi(cat.channels, channel)) return;
    cat.channels = cat.channels.concat([channel]);
    draftChanged(`mappings-ch-input-${index}`);
  }

  function renderListPreview(body) {
    const el = $("mappings-editor-preview");
    if (!el) return;
    const lines = [].concat(
      body.order_change ? [diffLine("mod", _escapeHtml(body.order_change))] : [],
      (body.added || []).map((t) => diffLine("add", _escapeHtml(t))),
      (body.removed || []).map((t) => diffLine("del", _escapeHtml(t))),
    ).join("");
    const empty = body.change === "unchanged"
      ? '<div class="text-secondary">Keine Änderung gegenüber dem gespeicherten Stand.</div>'
      : (lines || '<div class="text-secondary">Kein fachlicher Unterschied — die Datei würde nur bereinigt zurückgeschrieben.</div>');
    const comment = body.comment_warning
      ? `<div class="alert alert-info mt-2 mb-0" role="note"><div class="d-flex">${ccIcon("info", "me-2")}<div>${_escapeHtml(body.comment_warning)}</div></div></div>` : "";
    el.innerHTML = `<div class="mb-2">${changeBadge(body.change)} <span class="text-secondary small ms-1">change: ${_escapeHtml(body.change)}</span></div>${lines || empty}${comment}`;
    const msg = $("mappings-editor-message");
    if (msg) msg.innerHTML = warningsHtml(body.warnings)
      + `<div class="alert alert-info" role="note"><div class="d-flex">${ccIcon("info", "me-2")}<div>Der Bot lädt die Mapping-Dateien beim Start: die Änderung wirkt nach Bot-Neustart. Die bisherige Datei wird vorher als Version gesichert.</div></div></div>`;
  }

  // ── Versionen ──────────────────────────────────────────────────────────

  async function openVersions(typeId) {
    Object.assign(ed, { mode: "versions", typeId, version: null, versionPreview: null, preview: null });
    ed.seq += 1; clearTimeout(ed.timer);
    setHeader(info(typeId).title, "Versionen");
    setFooter(false, "");
    const body = $("mappings-editor-body");
    panel().show();
    if (body) ccState.loading(body);
    try {
      const res = await ccApi("GET", `${API}/${typeId}/backups`);
      renderVersions(res || { versions: [], max_versions: 0 });
    } catch (err) { showApiError(body, err); }
  }

  function renderVersions(res) {
    const body = $("mappings-editor-body");
    if (!body) return;
    if (!res.versions.length) {
      ccState.empty(body, "Noch keine Versionen", "Vor dem ersten Speichern wird die bisherige Datei als Version gesichert.");
      return;
    }
    body.innerHTML = `
      <p class="text-secondary small">Vor jedem Speichern wird die bisherige Datei unverändert (mit Kommentaren) gesichert.
        Aufbewahrt werden die letzten ${_escapeHtml(String(res.max_versions))} Versionen.</p>
      <div class="table-responsive border rounded mb-3"><table class="table card-table table-vcenter table-sm mb-0">
        <thead><tr><th>Erstellt</th><th class="d-none d-sm-table-cell">Größe</th><th class="w-1"></th></tr></thead><tbody>
        ${res.versions.map((v) => `<tr>
          <td>${_escapeHtml(fmtTime(v.created_at))}</td>
          <td class="d-none d-sm-table-cell text-secondary">${_escapeHtml(fmtBytes(v.size))}</td>
          <td><button type="button" class="btn btn-sm" data-action="ver-preview" data-version="${_escapeHtml(v.version_id)}">Vergleichen</button></td>
        </tr>`).join("")}</tbody></table></div>
      <div id="mappings-editor-message"></div>
      <div id="mappings-editor-preview"></div>`;
  }

  async function previewVersion(versionId) {
    ed.version = versionId; ed.versionPreview = null;
    const el = $("mappings-editor-preview");
    if (el) ccState.loading(el);
    try {
      const res = await ccApi("POST", `${API}/${ed.typeId}/backups/${encodeURIComponent(versionId)}/preview`);
      if (ed.version !== versionId) return;
      ed.versionPreview = res;
      renderVersionPreview(res);
    } catch (err) { showApiError(el, err); }
  }

  function renderVersionPreview(res) {
    const el = $("mappings-editor-preview");
    if (!el) return;
    const lines = [].concat(
      (res.added || []).map((t) => diffLine("add", _escapeHtml(t))),
      (res.removed || []).map((t) => diffLine("del", _escapeHtml(t))),
      (res.changed || []).map((t) => diffLine("mod", _escapeHtml(t))),
    ).join("");
    const same = res.change === "unchanged";
    el.innerHTML = `
      <h4 class="text-uppercase text-secondary fs-5 mb-2">Version vom ${_escapeHtml(fmtTime(res.created_at))} gegenüber dem aktuellen Stand</h4>
      <div class="cc-mapping-diff p-3 mb-3">
        <div class="mb-2">${changeBadge(res.change)}</div>
        ${same ? '<div class="text-secondary">Diese Version entspricht dem aktuellen Stand.</div>'
               : (lines || '<div class="text-secondary">Kein fachlicher Unterschied (nur Formatierung/Kommentare).</div>')}
      </div>
      ${warningsHtml(res.warnings)}
      ${same ? "" : `<button type="button" class="btn btn-primary" data-action="ver-restore">${ccIcon("history", "me-1")}Diese Version wiederherstellen</button>`}`;
  }

  async function restoreVersion() {
    const plan = ed.versionPreview;
    if (ed.saving || !plan || plan.change === "unchanged") return;
    const type = info(ed.typeId);
    const ok = await ccConfirm({
      title: `${type.title}: Version wiederherstellen?`,
      text: `Der Stand vom ${fmtTime(plan.created_at)} ersetzt die aktuelle Datei. Der aktuelle Stand wird vorher selbst als Version gesichert.`,
      confirmLabel: "Wiederherstellen",
    });
    if (!ok) return;
    ed.saving = true;
    try {
      const res = await ccApi("POST", `${API}/${ed.typeId}/backups/${encodeURIComponent(plan.version_id)}/restore`, { etag: plan.etag });
      ccToast("ok", res.written ? "Version wiederhergestellt" : "Keine Änderung", res.message);
      await window.ccMappingsPage.reloadType(ed.typeId);
      await openVersions(ed.typeId);
    } catch (err) {
      if (err && err.status === 409) await onConflict(err);
      else showApiError($("mappings-editor-message"), err);
    } finally {
      ed.saving = false;
    }
  }

  // ── Ereignisse (delegiert) ─────────────────────────────────────────────

  function onClick(event) {
    const el = event.target && event.target.closest ? event.target.closest("[data-action]") : null;
    if (!el) return;
    const a = el.dataset.action;
    if (a === "edit" && FORMS[el.dataset.type]) openEntry(el.dataset.type, el.dataset.key, false);
    else if (a === "new" && FORMS[el.dataset.type]) openEntry(el.dataset.type, "", true);
    else if (a === "edit-list" && isList(el.dataset.type)) openList(el.dataset.type);
    else if (a === "yaml") openYaml(el.dataset.type);
    else if (isList(ed.typeId) && ed.mode === "list" && /^(flt-|cat-|ch-)/.test(a)) listAction(a, el);
    else if (a === "versions") openVersions(el.dataset.type);
    else if (a === "save") saveEntry();
    else if (a === "ver-preview") previewVersion(el.dataset.version);
    else if (a === "ver-restore") restoreVersion();
    else if (a === "sec-remove") { ed.form.secondary = (ed.form.secondary || []).filter((g) => g !== el.dataset.genre); refreshChips(); scheduleFormPreview(); }
  }

  function refreshChips() {
    const chips = $("mappings-f-chips");
    if (chips) chips.innerHTML = chipsHtml(ed.form.secondary);
  }

  function onInput(event) {
    const t0 = event.target;
    if (isYaml() && t0 && t0.dataset && t0.dataset.field === "yaml-text") {
      ed.yamlText = String(t0.value === undefined ? "" : t0.value);   // unverändert, nie trimmen
      scheduleFormPreview();
      return;
    }
    if (ed.mode === "list" && t0 && t0.dataset && t0.dataset.field === "flt-search") {
      ed.filterQuery = String(t0.value || "");
      const chips = $("mappings-f-chips"); if (chips) chips.innerHTML = filterChipsHtml();
      return;
    }
    if (ed.mode !== "entry") return;
    const t = event.target;
    if (!t || !t.dataset || !t.dataset.field || t.dataset.field === "sec-input") return;
    readForm();
    scheduleFormPreview();
  }

  function onKeydown(event) {
    const t = event.target;
    if (ed.mode === "list" && t && t.dataset && event.key === "Enter") {
      const field = t.dataset.field;
      if (field === "flt-input" || field === "ch-input" || field === "cat-name") {
        if (event.preventDefault) event.preventDefault();
        const value = t.value;
        t.value = "";
        if (field === "flt-input") addFilter(value);
        else if (field === "cat-name") addCategory(value);
        else addChannel(Number(t.dataset.index), value);
      }
      return;
    }
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

  // mappings.js meldet sich nach checkAuth(); der Editor hängt sich danach an.
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
