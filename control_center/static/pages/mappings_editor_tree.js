// control_center/static/pages/mappings_editor_tree.js
// Mapping-Administration: Editor für die Genre-Hierarchie (Baum) als Modus des Editors
// (Kern: mappings_editor.js). Der ganze Baum ist der Entwurf; ein Entwurf = eine Vorschau
// = ein PUT. Zyklen, unbekannte Eltern, doppelte Namen und die Prioritätswirkung
// (Tiefe) bewertet ausschließlich das Backend (POST .../preview). Lokal geprüft wird nur,
// ob ein Genre im Entwurf noch Unterelemente hat — dann wird das Entfernen blockiert,
// damit nie stillschweigend ein Unterbaum verschwindet.
(function () {
  "use strict";

  const E = window.ccMappingsEditor;
  const { API, ed, $, info, panel, setHeader, setFooter, showApiError, changeBadge, diffLine, warningsHtml, scheduleFormPreview } = E;
  const TYPE_ID = "genre-hierarchy";
  const ROOT_LABEL = "Wurzel (kein Eltern-Genre)";

  // ed.tree: entries = Entwurf [{genre, parent}], original = {genre: parent} vom Laden,
  // removed = entfernte Einträge (mit Rückgängig), form = offenes Formular, open = geöffnete Knoten.
  const T = () => ed.tree;
  const byGenre = (genre) => T().entries.find((e) => e.genre === genre);
  const childrenOf = (genre) => T().entries.filter((e) => e.parent === genre);
  const parentLabel = (parent) => (parent === null || parent === undefined ? "Wurzel" : parent);

  async function openTree() {
    Object.assign(ed, { mode: "tree", typeId: TYPE_ID, preview: null, version: null });
    ed.seq += 1; clearTimeout(ed.timer);
    setHeader(info(TYPE_ID).title, "Bearbeiten");
    setFooter(true, "");
    const body = $("mappings-editor-body");
    panel().show();
    if (body) ccState.loading(body);
    try {
      const res = (await ccApi("GET", `${API}/${TYPE_ID}`)) || {};
      const entries = (res.entries || []).map((e) => ({ genre: e.genre, parent: e.parent === undefined ? null : e.parent }));
      const original = {};
      entries.forEach((e) => { original[e.genre] = e.parent; });
      ed.tree = { entries, original, removed: [], form: null, open: new Set(), query: "", notice: "" };
    } catch (err) { showApiError(body, err); return; }
    renderTreeEditor();
    scheduleFormPreview();
  }

  // ── Darstellung ────────────────────────────────────────────────────────

  function parentOptions(selected, exclude) {
    const names = T().entries.map((e) => e.genre).filter((g) => g !== exclude).sort((a, b) => a.localeCompare(b, "de"));
    const opt = (value, label) => `<option value="${_escapeHtml(value)}"${value === selected ? " selected" : ""}>${_escapeHtml(label)}</option>`;
    return opt("", ROOT_LABEL) + names.map((g) => opt(g, g)).join("");
  }

  function formHtml() {
    const f = T().form;
    if (!f) return "";
    const adding = f.kind === "add";
    return `
      <div class="card card-sm mb-3"><div class="card-body">
        <h4 class="card-title">${adding ? "Neues Genre" : `Eltern-Genre ändern: ${_escapeHtml(f.genre)}`}</h4>
        <div class="row g-2">
          ${adding ? `<div class="col-12 col-sm-6"><label class="form-label" for="mappings-tree-name">Name</label>
            <input id="mappings-tree-name" class="form-control" data-field="tree-name" value="${_escapeHtml(f.name || "")}" maxlength="100"></div>` : ""}
          <div class="col-12 col-sm-6"><label class="form-label" for="mappings-tree-parent">Eltern-Genre</label>
            <select id="mappings-tree-parent" class="form-select" data-field="tree-parent">${parentOptions(f.parent, adding ? null : f.genre)}</select></div>
        </div>
        <div class="btn-list mt-3">
          <button type="button" class="btn btn-sm btn-primary" data-action="tree-form-apply">${ccIcon("check", "me-1")}Zum Entwurf hinzufügen</button>
          <button type="button" class="btn btn-sm" data-action="tree-form-cancel">Abbrechen</button>
        </div>
      </div></div>`;
  }

  function nodeExtras(entry) {
    const original = T().original;
    if (!(entry.genre in original)) return `<span class="badge bg-green-lt">${ccIcon("plus", "icon-sm me-1")}neu</span>`;
    if (original[entry.genre] !== entry.parent) {
      return `<span class="badge bg-yellow-lt">${ccIcon("edit", "icon-sm me-1")}verschoben (war ${_escapeHtml(parentLabel(original[entry.genre]))})</span>`;
    }
    return "";
  }

  function nodeActions(entry) {
    const g = _escapeHtml(entry.genre);
    return `<button type="button" class="btn btn-sm btn-icon btn-ghost-secondary" data-action="tree-parent" data-genre="${g}"
        title="Eltern-Genre von ${g} ändern" aria-label="Eltern-Genre von ${g} ändern">${ccIcon("edit")}</button>
      <button type="button" class="btn btn-sm btn-icon btn-ghost-danger" data-action="tree-remove" data-genre="${g}"
        title="${g} entfernen" aria-label="${g} entfernen">${ccIcon("trash")}</button>`;
  }

  function removedHtml() {
    const removed = T().removed;
    if (!removed.length) return "";
    return `<div class="mb-3"><h4 class="text-uppercase text-secondary fs-5 mb-2">Entfernt (${_escapeHtml(String(removed.length))})</h4>
      <div class="d-flex flex-wrap gap-1">${removed.map((e) => `<span class="badge bg-red-lt cc-mapping-chip">${_escapeHtml(e.genre)}
        <button type="button" class="btn btn-sm btn-link p-0 ms-1" data-action="tree-restore" data-genre="${_escapeHtml(e.genre)}"
          aria-label="${_escapeHtml(e.genre)} wiederherstellen">rückgängig</button></span>`).join("")}</div></div>`;
  }

  function treeView() {
    return window.ccMappingsPage.treeHtml(T().entries, {
      query: T().query, open: T().open, toggleAction: "tree-node-toggle", nodeExtras, nodeActions,
    });
  }

  function noticeHtml() {
    const text = T().notice;
    return text ? `<div class="alert alert-warning mb-3" role="alert"><div class="d-flex">${ccIcon("alert", "me-2")}<div class="text-break">${_escapeHtml(text)}</div></div></div>` : "";
  }

  function renderTreeEditor() {
    const body = $("mappings-editor-body");
    if (!body) return;
    body.innerHTML = `
      <div class="d-flex align-items-center gap-2 mb-3"><span class="badge flex-shrink-0 text-nowrap bg-yellow-lt">${ccIcon("edit", "icon-sm me-1")}Baum bearbeiten</span>
        <span class="text-secondary small">Änderungen werden erst nach Vorschau und Bestätigung geschrieben. Kommentare der Datei bleiben erhalten.</span></div>
      <div class="alert alert-info" role="note"><div class="d-flex">${ccIcon("info", "me-2")}<div>Die <strong>Tiefe im Baum ist die Genre-Priorität</strong>: ein anderes Eltern-Genre verschiebt die Priorität des ganzen Unterbaums.
        Genres mit Unterelementen lassen sich nicht entfernen — zuerst Unterelemente verschieben oder entfernen. Umbenennen ist hier nicht möglich (Aliase und Artist-Mappings verweisen auf die Namen).</div></div></div>
      <div id="mappings-tree-notice">${noticeHtml()}</div>
      <div class="d-flex flex-wrap gap-2 mb-2">
        <div class="input-icon flex-grow-1"><span class="input-icon-addon">${ccIcon("search")}</span>
          <input type="search" class="form-control form-control-sm" data-field="tree-search" placeholder="Genre suchen (${_escapeHtml(String(T().entries.length))} Genres)" aria-label="Genres durchsuchen" value="${_escapeHtml(T().query)}"></div>
        <button type="button" class="btn btn-sm" data-action="tree-add">${ccIcon("plus", "me-1")}Genre hinzufügen</button>
      </div>
      <div id="mappings-tree-form">${formHtml()}</div>
      <div id="mappings-tree-view" class="cc-mapping-scroll border rounded p-2 mb-3">${treeView()}</div>
      <div id="mappings-tree-removed">${removedHtml()}</div>
      <div id="mappings-editor-message"></div>
      <h4 class="text-uppercase text-secondary fs-5 mb-2">Vorschau</h4>
      <div id="mappings-editor-preview" class="cc-mapping-diff p-3"></div>`;
  }

  // Nur den Baum neu zeichnen (Suche/Aufklappen), damit Eingabefokus und Formular erhalten bleiben.
  function refreshView() {
    const el = $("mappings-tree-view");
    if (el) el.innerHTML = treeView();
  }

  function draftChanged() {
    T().notice = "";
    renderTreeEditor();
    scheduleFormPreview();
  }

  // ── Entwurf ändern ─────────────────────────────────────────────────────

  const fieldValue = (name) => {
    const el = document.querySelector(`#mappings-editor-body [data-field="${name}"]`);
    return el ? String(el.value || "").trim() : "";
  };

  function applyForm() {
    const f = T().form;
    if (!f) return;
    const parent = fieldValue("tree-parent") || null;
    if (f.kind === "add") {
      const name = fieldValue("tree-name");
      if (!name) { T().notice = "Bitte einen Namen eingeben."; renderTreeEditor(); return; }
      T().entries = T().entries.concat([{ genre: name, parent }]);
      if (parent) T().open.add(parent);
    } else {
      const entry = byGenre(f.genre);
      if (entry) entry.parent = parent;
      if (parent) T().open.add(parent);
    }
    T().form = null;
    draftChanged();
  }

  function removeGenre(genre) {
    const kids = childrenOf(genre);
    if (kids.length) {
      const names = kids.slice(0, 5).map((k) => k.genre).join(", ") + (kids.length > 5 ? ", …" : "");
      T().notice = `„${genre}“ hat ${kids.length} Unterelement${kids.length === 1 ? "" : "e"} (${names}). `
        + "Zuerst die Unterelemente verschieben oder entfernen — es wird nichts kaskadierend gelöscht.";
      const el = $("mappings-tree-notice"); if (el) el.innerHTML = noticeHtml();
      return;
    }
    const entry = byGenre(genre);
    if (!entry) return;
    T().entries = T().entries.filter((e) => e.genre !== genre);
    // Ein neu angelegtes Genre verschwindet einfach wieder; nur bestehende Genres sind "entfernt".
    if (genre in T().original) T().removed = T().removed.concat([{ genre, parent: T().original[genre] }]);
    draftChanged();
  }

  function restoreGenre(genre) {
    const item = T().removed.find((e) => e.genre === genre);
    if (!item) return;
    T().removed = T().removed.filter((e) => e.genre !== genre);
    T().entries = T().entries.concat([{ genre, parent: item.parent }]);
    draftChanged();
  }

  // ── Vorschau ───────────────────────────────────────────────────────────

  function errorListHtml(message) {
    const lines = String(message || "Ungültige Hierarchie.").split("\n").filter(Boolean);
    return `<div class="alert alert-danger mb-0" role="alert"><div class="d-flex">${ccIcon("alert", "me-2")}<ul class="cc-mapping-errors text-break">${lines.map((l) => `<li>${_escapeHtml(l)}</li>`).join("")}</ul></div></div>`;
  }

  function changeLine(c) {
    const g = `<code>${_escapeHtml(c.genre)}</code>`;
    const more = (c.affected_count || 0) > (c.affected || []).length ? ` und ${c.affected_count - c.affected.length} weitere` : "";
    const below = c.affected_count
      ? `<div class="ms-4 small text-secondary">Betrifft ${_escapeHtml(String(c.affected_count))} untergeordnete${c.affected_count === 1 ? "s Genre" : " Genres"}: ${_escapeHtml((c.affected || []).join(", "))}${_escapeHtml(more)}</div>` : "";
    if (c.kind === "added") return diffLine("add", `${g} neu unter <strong>${_escapeHtml(parentLabel(c.new_parent))}</strong> (Tiefe ${_escapeHtml(String(c.new_depth))})`);
    if (c.kind === "removed") return diffLine("del", `${g} entfernt (war unter ${_escapeHtml(parentLabel(c.old_parent))})`) + below;
    const depth = c.old_depth !== c.new_depth
      ? ` <span class="badge bg-yellow-lt">Priorität: Tiefe ${_escapeHtml(String(c.old_depth))} → ${_escapeHtml(String(c.new_depth))}</span>` : "";
    return diffLine("mod", `${g} — Eltern-Genre: <span class="cc-mapping-diff-del">${_escapeHtml(parentLabel(c.old_parent))}</span> → <strong>${_escapeHtml(parentLabel(c.new_parent))}</strong>${depth}`) + below;
  }

  function renderTreePreview(body) {
    const el = $("mappings-editor-preview");
    if (!el) return;
    const lines = body.change === "unchanged"
      ? '<div class="text-secondary">Keine Änderung gegenüber dem gespeicherten Stand.</div>'
      : (body.changes || []).map(changeLine).join("");
    el.innerHTML = `<div class="mb-2">${changeBadge(body.change)} <span class="text-secondary small ms-1">change: ${_escapeHtml(body.change)}</span></div>${lines}`;
    const msg = $("mappings-editor-message");
    if (msg) msg.innerHTML = warningsHtml(body.warnings)
      + `<div class="alert alert-info" role="note"><div class="d-flex">${ccIcon("info", "me-2")}<div>Der Bot lädt die Mapping-Dateien beim Start: die Änderung wirkt nach Bot-Neustart. Die bisherige Datei wird vorher als Version gesichert.</div></div></div>`;
  }

  const payload = () => ({ entries: T().entries.map((e) => ({ genre: e.genre, parent: e.parent })) });

  E.modes.tree = {
    needsKey: false,
    previewRequest: () => ({ path: `${API}/${TYPE_ID}/preview`, body: payload() }),
    renderPreview: renderTreePreview,
    // 422: alle Fehler des Backends als Liste zeigen; „Übernehmen“ bleibt gesperrt.
    onPreviewError: (err) => {
      if (!err || err.status !== 422) return false;
      const el = $("mappings-editor-preview");
      if (el) el.innerHTML = errorListHtml(err.message);
      const msg = $("mappings-editor-message"); if (msg) msg.innerHTML = "";
      return true;
    },
    saveRequest: () => {
      const p = ed.preview || {};
      const n = (list) => (list || []).length;
      return {
        url: `${API}/${TYPE_ID}`,
        payload: payload(),
        confirm: {
          title: "Genre-Hierarchie speichern?",
          text: `${n(p.added)} neu, ${n(p.changed)} verschoben, ${n(p.removed)} entfernt. Nur die betroffenen Zeilen der Datei ändern sich, Kommentare bleiben erhalten; `
            + "die bisherige Datei wird als Version gesichert. Für neue Downloads ist danach ein Bot-Neustart nötig.",
        },
        toastTitle: "Hierarchie gespeichert",
      };
    },
    reopen: () => openTree(),
  };

  // ── Ereignisse ─────────────────────────────────────────────────────────

  const inTree = (fn) => (el) => { if (ed.mode === "tree") fn(el); };
  E.actions["edit-tree"] = (el) => { if (el.dataset.type === TYPE_ID) openTree(); };
  E.actions["tree-add"] = inTree(() => { T().form = { kind: "add", name: "", parent: null }; T().notice = ""; renderTreeEditor(); });
  E.actions["tree-parent"] = inTree((el) => {
    const entry = byGenre(el.dataset.genre);
    if (!entry) return;
    T().form = { kind: "parent", genre: entry.genre, parent: entry.parent };
    T().notice = "";
    renderTreeEditor();
  });
  E.actions["tree-form-apply"] = inTree(applyForm);
  E.actions["tree-form-cancel"] = inTree(() => { T().form = null; renderTreeEditor(); });
  E.actions["tree-remove"] = inTree((el) => removeGenre(el.dataset.genre));
  E.actions["tree-restore"] = inTree((el) => restoreGenre(el.dataset.genre));
  E.actions["tree-node-toggle"] = inTree((el) => {
    const genre = el.dataset.genre;
    if (T().open.has(genre)) T().open.delete(genre); else T().open.add(genre);
    refreshView();
  });

  E.inputHandlers.push((event) => {
    const t = event.target;
    if (ed.mode !== "tree" || !t || !t.dataset || t.dataset.field !== "tree-search") return false;
    T().query = String(t.value || "");
    refreshView();
    return true;
  });

  E.keydownHandlers.push((event) => {
    const t = event.target;
    if (ed.mode !== "tree" || !t || !t.dataset || event.key !== "Enter" || t.dataset.field !== "tree-name") return false;
    if (event.preventDefault) event.preventDefault();
    applyForm();
    return true;
  });
})();
