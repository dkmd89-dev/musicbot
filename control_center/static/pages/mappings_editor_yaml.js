// control_center/static/pages/mappings_editor_yaml.js
// Mapping-Administration: YAML-Editor (Rohtext, für Fortgeschrittene) als Modus des
// Editors (Kern: mappings_editor.js). Der Server prüft den Text streng und schreibt
// ihn unverändert (Kommentare bleiben); hier wird nur angezeigt und gesendet.
(function () {
  "use strict";

  const E = window.ccMappingsEditor;
  const { API, ed, $, info, panel, setHeader, setFooter, showApiError, changeBadge, diffLine, warningsHtml, scheduleFormPreview, onConflict } = E;

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

  E.modes.yaml = {
    needsKey: false,
    previewRequest: () => ({ path: `${API}/${ed.typeId}/yaml/preview`, body: { text: ed.yamlText } }),
    renderPreview: renderYamlPreview,
    onPreviewError: (err) => {
      if (err && err.status === 422) { renderYamlErrors(err.message); return true; }
      return false;
    },
    saveRequest: () => ({
      url: `${API}/${ed.typeId}/yaml`,
      payload: { text: ed.yamlText },
      confirm: {
        title: `${info(ed.typeId).title} als YAML speichern?`,
        text: "Der Text wird unverändert in die Datei geschrieben (Kommentare bleiben erhalten). Die bisherige Datei wird vorher als Version gesichert.",
      },
      toastTitle: "YAML gespeichert",
    }),
    reopen: () => openYaml(ed.typeId),
  };

  E.actions.yaml = (el) => openYaml(el.dataset.type);

  E.inputHandlers.push((event) => {
    const t = event.target;
    if (ed.mode !== "yaml" || !t || !t.dataset || t.dataset.field !== "yaml-text") return false;
    ed.yamlText = String(t.value === undefined ? "" : t.value);   // unverändert, nie trimmen
    scheduleFormPreview();
    return true;
  });
})();
