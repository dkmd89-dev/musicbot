// control_center/static/pages/mappings_editor_versions.js
// Mapping-Administration: Versionen (Backup/Restore) aller Mapping-Typen als Modus des
// Editors (Kern: mappings_editor.js). Restore ist ein Etag-geschützter Write im
// Backend; hier wird nur verglichen, bestätigt und gesendet.
(function () {
  "use strict";

  const E = window.ccMappingsEditor;
  const { API, ed, $, info, panel, setHeader, setFooter, showApiError, changeBadge, diffLine, warningsHtml, scheduleFormPreview, onConflict } = E;

  const fmtTime = (iso) => { const d = new Date(iso); return isNaN(d) ? String(iso) : d.toLocaleString("de-DE"); };
  const fmtBytes = (n) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1).replace(".", ",")} KB`);

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

  // Versionen sind kein Entwurf: kein previewRequest/saveRequest, nur reopen (nach 409).
  E.modes.versions = { needsKey: false, reopen: () => openVersions(ed.typeId) };

  E.actions.versions = (el) => openVersions(el.dataset.type);
  E.actions["ver-preview"] = (el) => previewVersion(el.dataset.version);
  E.actions["ver-restore"] = () => restoreVersion();
})();
