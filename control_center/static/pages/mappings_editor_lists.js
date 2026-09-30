// control_center/static/pages/mappings_editor_lists.js
// Mapping-Administration: Editor für die Listen-Typen Genre-Filter (Chip-Liste) und
// Spezialkanäle (Kategorien in Prioritätsreihenfolge) als Modus des Editors (Kern:
// mappings_editor.js). Ein Entwurf = eine Vorschau = ein PUT; Bewertung und
// Validierung liegen im Backend.
(function () {
  "use strict";

  const E = window.ccMappingsEditor;
  const { API, ed, $, info, panel, setHeader, setFooter, showApiError, changeBadge, diffLine, warningsHtml, scheduleFormPreview, onConflict } = E;

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

  E.modes.list = {
    needsKey: false,
    previewRequest: () => ({ path: `${API}/${ed.typeId}/preview`, body: LISTS[ed.typeId].payload(ed.draft) }),
    renderPreview: renderListPreview,
    saveRequest: () => ({
      url: `${API}/${ed.typeId}`,
      payload: LISTS[ed.typeId].payload(ed.draft),
      confirm: {
        title: `${info(ed.typeId).title} speichern?`,
        text: "Der geänderte Bestand ersetzt die Datei. Die Datei wird neu geschrieben, Kommentare gehen verloren; die bisherige Datei wird als Version gesichert.",
      },
      toastTitle: "Mapping gespeichert",
    }),
    reopen: () => openList(ed.typeId),
  };

  E.actions["edit-list"] = (el) => { if (LISTS[el.dataset.type]) openList(el.dataset.type); };
  ["flt-add", "flt-remove", "cat-up", "cat-down", "cat-remove", "ch-remove", "cat-add"].forEach((name) => {
    E.actions[name] = (el) => { if (ed.mode === "list") listAction(name, el); };
  });

  E.inputHandlers.push((event) => {
    const t = event.target;
    if (ed.mode !== "list" || !t || !t.dataset || t.dataset.field !== "flt-search") return false;
    ed.filterQuery = String(t.value || "");
    const chips = $("mappings-f-chips"); if (chips) chips.innerHTML = filterChipsHtml();
    return true;
  });

  E.keydownHandlers.push((event) => {
    const t = event.target;
    if (ed.mode !== "list" || !t || !t.dataset || event.key !== "Enter") return false;
    const field = t.dataset.field;
    if (field !== "flt-input" && field !== "ch-input" && field !== "cat-name") return true;
    if (event.preventDefault) event.preventDefault();
    const value = t.value;
    t.value = "";
    if (field === "flt-input") addFilter(value);
    else if (field === "cat-name") addCategory(value);
    else addChannel(Number(t.dataset.index), value);
    return true;
  });
})();
