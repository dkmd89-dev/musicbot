// control_center/static/pages/library.js
// Library-Übersicht = Metadaten-Werkstatt (Nutzerentscheidung 2026-09-28):
// Artists finden, nach offenen Metadaten-Themen filtern, zum Bearbeiten auf
// die Artist-Seite springen. CC-UI L2 nach docs/CONTROL_CENTER_UI_STANDARD.md
// (Sprite-Icons, Zustände über ccState, Tabellen für alle Listen).
// Endpunkte unverändert:
//   GET /api/v1/library/artists-overview   persistenter Report, KEIN Scan
//   GET /api/v1/library/health/cached      Kennzahlen, Health, Aufmerksamkeit
//   GET /api/v1/library/health/score-history
//   GET /api/v1/library/{tracks,artists,albums,mapping-summary}  Live-Scan auf Klick

// ── Artists (persistenter Report) ────────────────────────────────────────
let _artistsOverviewCache = [];

// Phase E (CC-LIB-FINAL): progressive Anzeige - reines Client-Slicing des
// bereits geladenen Caches, bei neuer Suche/Sortierung/Filter zurück auf
// die erste Seite.
const _ARTISTS_PAGE_SIZE = 15;
let _artistsVisibleCount = _ARTISTS_PAGE_SIZE;

// Filterwert "alle Artists mit mindestens einem offenen Thema".
const _ARTIST_FILTER_ANY = "__any";

function _issueLabel(code) {
  return _ISSUE_LABELS[code] || code;
}

function _artistRowHtml(a) {
  const href = `${CC_BASE}/library/${encodeURIComponent(a.artist)}`;
  const hs = a.health_score;
  // Punkt + Score (Phase E, dieselben .dot-Klassen wie Repair-History).
  const dotClass = hs >= 90 ? "dot-ok" : hs >= 70 ? "dot-warn" : "dot-error";
  const codes = a.issue_codes || [];
  const topics = codes.length
    ? `<span class="badge bg-yellow-lt" title="${_escapeHtml(codes.map(_issueLabel).join(", "))}">${codes.length} offen</span>`
    : '<span class="text-secondary">–</span>';

  return `
    <tr class="artist-row" data-href="${_escapeHtml(href)}" tabindex="0" role="link">
      <td>
        <div class="d-flex align-items-center gap-2 min-w-0">
          ${ccIcon("microphone", "text-secondary flex-shrink-0")}
          <span class="fw-medium text-truncate" title="${_escapeHtml(a.artist)}">${_escapeHtml(a.artist)}</span>
        </div>
      </td>
      <td class="text-secondary text-end">${a.file_count}</td>
      <td class="text-secondary text-end d-none d-sm-table-cell">${a.album_count}</td>
      <td class="text-end text-nowrap"><span class="dot ${dotClass}"></span>${hs}</td>
      <td class="d-none d-md-table-cell">${topics}</td>
      <td class="text-end">
        <a href="${_escapeHtml(href)}" class="btn btn-sm btn-ghost-teal" aria-label="${_escapeHtml(a.artist)} bearbeiten">
          ${ccIcon("edit")}<span class="d-none d-lg-inline ms-1">Bearbeiten</span>
        </a>
      </td>
    </tr>
  `;
}

// Nutzer-Ergänzung (CC-AC-7): deterministische Sortierung, Artistname
// (A-Z) als Tie-Breaker.
const _ARTIST_SORT_COMPARATORS = {
  name: (a, b) => a.artist.localeCompare(b.artist),
  files: (a, b) => b.file_count - a.file_count || a.artist.localeCompare(b.artist),
  albums: (a, b) => b.album_count - a.album_count || a.artist.localeCompare(b.artist),
  health: (a, b) => b.health_score - a.health_score || a.artist.localeCompare(b.artist),
  // CC-AC-8 Schritt 4: für "welcher Artist ist am schlechtesten?"
  health_asc: (a, b) => a.health_score - b.health_score || a.artist.localeCompare(b.artist),
};

function _artistMatchesIssueFilter(a, filter) {
  if (!filter) return true;
  const codes = a.issue_codes || [];
  return filter === _ARTIST_FILTER_ANY ? codes.length > 0 : codes.includes(filter);
}

// Filter-Auswahl aus den Themen, die im Report tatsächlich vorkommen
// (Anzahl betroffener Artists, häufigste zuerst). Behält die Auswahl.
function _renderArtistIssueFilter() {
  const sel = document.getElementById("artist-issue-filter");
  if (!sel) return;
  const current = sel.value || "";
  const counts = {};
  let withAny = 0;
  _artistsOverviewCache.forEach((a) => {
    const codes = a.issue_codes || [];
    if (codes.length) withAny += 1;
    codes.forEach((c) => { counts[c] = (counts[c] || 0) + 1; });
  });
  const codes = Object.keys(counts).sort((x, y) => counts[y] - counts[x] || _issueLabel(x).localeCompare(_issueLabel(y)));
  if (current && current !== _ARTIST_FILTER_ANY && !counts[current]) counts[current] = 0, codes.push(current);
  sel.innerHTML = `<option value="">Alle Artists (${_artistsOverviewCache.length})</option>`
    + `<option value="${_ARTIST_FILTER_ANY}">Mit offenen Themen (${withAny})</option>`
    + codes.map((c) => `<option value="${_escapeHtml(c)}">${_escapeHtml(_issueLabel(c))} (${counts[c]})</option>`).join("");
  sel.value = current;
}

function _renderArtistsOverviewList() {
  const el = document.getElementById("artists-overview-content");
  const query = (document.getElementById("artist-search").value || "").trim().toLowerCase();
  const sortKey = document.getElementById("artist-sort").value || "name";
  const issueFilter = document.getElementById("artist-issue-filter")?.value || "";
  const filtered = _artistsOverviewCache.filter((a) =>
    (!query || a.artist.toLowerCase().includes(query)) && _artistMatchesIssueFilter(a, issueFilter));

  const countEl = document.getElementById("artists-overview-count");
  if (countEl) {
    countEl.textContent = filtered.length === _artistsOverviewCache.length
      ? `${filtered.length} Artists` : `${filtered.length} von ${_artistsOverviewCache.length} Artists`;
  }

  if (!filtered.length) {
    ccState.empty(el,
      query || issueFilter ? "Keine Artists für diese Auswahl" : "Keine Artists gefunden",
      query || issueFilter ? "Suche oder Filter anpassen." : "Der Library-Report enthält noch keine Artists.");
    return;
  }
  filtered.sort(_ARTIST_SORT_COMPARATORS[sortKey] || _ARTIST_SORT_COMPARATORS.name);

  const shown = filtered.slice(0, _artistsVisibleCount);
  const rest = filtered.length - shown.length;
  const loadMore = rest > 0
    ? `<div class="card-footer text-center">
         <p class="text-secondary small mb-2">${shown.length} von ${filtered.length} Artists</p>
         <button type="button" class="btn btn-sm" id="artists-load-more-btn">Weitere laden</button>
       </div>`
    : "";

  el.innerHTML = `
    <div class="table-responsive">
      <table class="table table-vcenter card-table table-hover mb-0">
        <thead>
          <tr>
            <th>Artist</th>
            <th class="text-end">Tracks</th>
            <th class="text-end d-none d-sm-table-cell">Alben</th>
            <th class="text-end">Health</th>
            <th class="d-none d-md-table-cell">Themen</th>
            <th class="w-1"><span class="visually-hidden">Aktion</span></th>
          </tr>
        </thead>
        <tbody>
          ${shown.map((a) => _artistRowHtml(a)).join("")}
        </tbody>
      </table>
    </div>
    ${loadMore}
  `;

  const artistTbody = el.querySelector("table")?.querySelector("tbody");
  artistTbody?.addEventListener("click", (event) => {
    if (event.target.closest("a")) return; // der Bearbeiten-Link navigiert selbst
    const row = event.target.closest("tr[data-href]");
    if (!row) return;
    window.location.href = row.dataset.href;
  });
  artistTbody?.addEventListener("keydown", (event) => {
    const row = event.target.closest("tr[data-href]");
    if (!row || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    window.location.href = row.dataset.href;
  });

  document.getElementById("artists-load-more-btn")?.addEventListener("click", () => {
    _artistsVisibleCount += _ARTISTS_PAGE_SIZE;
    _renderArtistsOverviewList();
  });
}

function renderArtistsOverview(el, body) {
  _artistsOverviewCache = body.artists;
  _artistsVisibleCount = _ARTISTS_PAGE_SIZE;
  // Fester Platz für den Stale-Hinweis (vorher bei jedem Neuladen
  // zusätzlich eingefügt und gestapelt).
  const staleEl = document.getElementById("artists-overview-stale");
  if (staleEl) {
    staleEl.hidden = !body.stale;
    staleEl.textContent = body.stale ? `Stand: ${body.generated_at || "unbekannt"} (nicht mehr aktuell)` : "";
  }
  _renderArtistIssueFilter();
  _renderArtistsOverviewList();
  // Einstieg aus der Overview ("In der Library bearbeiten"): ?issue=__any
  // bzw. ?issue=<CODE> setzt den Themen-Filter einmalig.
  if (_pendingIssueFilter) {
    const code = _pendingIssueFilter;
    _pendingIssueFilter = null;
    _showArtistsWithIssue(code);
  }
}

let _pendingIssueFilter = (() => {
  try {
    return new URLSearchParams((window.location && window.location.search) || "").get("issue");
  } catch (e) { return null; }
})();

// Lädt einen Endpunkt in ein Element; Zustände über ccState.
async function _libLoad(elementId, path, renderFn, retryFn) {
  const el = document.getElementById(elementId);
  if (!el) return;
  try {
    renderFn(el, await ccApi("GET", path));
  } catch (err) {
    if (err.status === 401) return;
    if (err.status === 403) { ccState.denied(el); return; }
    if (err.status === 404) { ccState.empty(el, "Nicht gefunden", err.message); return; }
    ccState.error(el, err.message || "Fehler beim Laden.", retryFn);
  }
}

function loadArtistsOverview() {
  return _libLoad("artists-overview-content", "/api/v1/library/artists-overview",
    renderArtistsOverview, loadArtistsOverview);
}

function _resetArtistsPagingAndRender() {
  _artistsVisibleCount = _ARTISTS_PAGE_SIZE;
  _renderArtistsOverviewList();
}
document.getElementById("artist-search").addEventListener("input", _resetArtistsPagingAndRender);
document.getElementById("artist-sort").addEventListener("change", _resetArtistsPagingAndRender);
document.getElementById("artist-issue-filter")?.addEventListener("change", _resetArtistsPagingAndRender);

// Aus der Aufmerksamkeit-Karte: Thema als Artist-Filter setzen und zur
// Artist-Liste springen (Werkstatt-Ablauf "finden -> bearbeiten").
function _showArtistsWithIssue(code) {
  const sel = document.getElementById("artist-issue-filter");
  if (!sel) return;
  sel.value = code;
  if (sel.value !== code) {
    // Thema kommt in keinem Artist vor: trotzdem auswählbar machen.
    sel.insertAdjacentHTML?.("beforeend", `<option value="${_escapeHtml(code)}">${_escapeHtml(_issueLabel(code))} (0)</option>`);
    sel.value = code;
  }
  _resetArtistsPagingAndRender();
  document.getElementById("library-artists-card")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

// ── Kennzahlen, Health, Aufmerksamkeit (GET /health/cached) ──────────────
// Nutzer-Ergänzung CC-AC-7: bestehender Cache-Read-Endpunkt, keine neue
// API, keine Client-Aggregation, niemals geschätzte Werte.
async function loadLibraryKpis() {
  const healthEl = document.getElementById("library-health-content");
  const attentionEl = document.getElementById("library-attention-content");
  try {
    const res = await fetch(apiUrl("/api/v1/library/health/cached"), { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (res.status === 404) {
      // Noch kein Health-Report: Leerzustand statt ewigem "wird geladen"
      // (vorher blieben beide Karten hier stehen).
      const hint = "Health-Scan auf der Health-Seite starten.";
      ccState.empty(healthEl, "Noch kein Health-Scan", hint,
        `<a href="${CC_BASE}/health" class="btn btn-sm">${ccIcon("health", "me-1")}Health öffnen</a>`);
      ccState.empty(attentionEl, "Noch keine Auswertung", hint);
      return;
    }
    if (!res.ok) {
      ccState.error(healthEl, `Health konnte nicht geladen werden (HTTP ${res.status}).`, loadLibraryKpis);
      ccState.error(attentionEl, `Aufmerksamkeit konnte nicht geladen werden (HTTP ${res.status}).`, loadLibraryKpis);
      return;
    }
    const body = await res.json();
    const lib = body.library || {};
    if (typeof lib.artists === "number" && typeof lib.files === "number" && typeof lib.albums === "number") {
      document.getElementById("library-kpi-artists").textContent = lib.artists;
      document.getElementById("library-kpi-tracks").textContent = lib.files;
      document.getElementById("library-kpi-albums").textContent = lib.albums;
      document.getElementById("library-kpi-tiles").hidden = false;
    }

    // CC-LIB-FINAL: "Zuletzt gescannt" prominent unter dem Seitentitel.
    const _scan = body.scan || {};
    document.getElementById("library-last-scan").textContent = _scan.completed_at
      ? `Zuletzt gescannt: ${_formatDateTime(_scan.completed_at)}`
      : "";

    _renderLibraryHealthSnapshot(body);
    _renderLibraryAttention(body);
  } catch (err) {
    ccState.error(healthEl, "Netzwerkfehler beim Laden der Health.", loadLibraryKpis);
    ccState.error(attentionEl, "Netzwerkfehler beim Laden der Aufmerksamkeit.", loadLibraryKpis);
  }
}

// CC-AC-8 Schritt 3: Health-Panel kompakt - Score, Status, Kernzahlen, Trend.
function _renderLibraryHealthSnapshot(body) {
  const el = document.getElementById("library-health-content");
  const h = body.health || {};
  const s = body.statistics || {};
  if (typeof h.score !== "number") {
    ccState.empty(el, "Kein Health-Score im Report");
    return;
  }

  const summary = (typeof s.total_files === "number")
    ? `${s.total_files} Tracks · ${s.total_artists} Artists · ${s.total_albums} Alben`
    : "";

  // Phase E: derselbe Status<->Farbe-Vertrag wie die Health-Seite.
  const color = _HEALTH_STATUS_COLOR[h.status] || "secondary";
  const pct = Math.max(0, Math.min(100, Number(h.score)));

  el.innerHTML = `
    <div class="d-flex align-items-baseline gap-2 mb-2">
      <div class="h1 mb-0">${h.score}</div>
      <span class="badge bg-${color}-lt">${_escapeHtml(h.status || "")}</span>
      <span id="library-health-trend" class="text-secondary small"></span>
    </div>

    <div class="progress progress-sm mb-2">
      <div class="progress-bar bg-${color}" style="width: ${pct}%" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"></div>
    </div>

    ${summary ? `<div class="text-secondary small">${summary}</div>` : ""}

    <a href="${CC_BASE}/health" class="btn btn-outline-primary w-100 mt-3">${ccIcon("health", "me-1")}Health öffnen</a>
  `;

  loadLibraryHealthSparkline();
}

// Phase E (CC-LIB-FINAL): eigener, isolierter Request für den Score-Verlauf.
function loadLibraryHealthSparkline() {
  return _loadInto(
    "library-health-sparkline", "/api/v1/library/health/score-history?limit=20",
    (el, body) => {
      _renderLibraryHealthTrend(body.entries);
      if (!body.entries.length) { el.innerHTML = ""; return; }
      el.innerHTML = `<div class="subheader mt-3 mb-1">Score-Verlauf</div>${_sparklineSvg(body.entries)}`;
    },
  );
}

// CC-LIB-FINAL: Trend = Differenz erster vs. letzter gewerteter Score im
// sichtbaren score-history-Fenster (älteste zuerst).
function _renderLibraryHealthTrend(entries) {
  const trendEl = document.getElementById("library-health-trend");
  if (!trendEl) return;
  const scored = entries.filter((e) => typeof e.score === "number");
  if (scored.length < 2) { trendEl.textContent = ""; return; }
  const delta = Math.round((scored[scored.length - 1].score - scored[0].score) * 10) / 10;
  const deltaText = delta > 0 ? `+${delta}` : delta < 0 ? `${delta}` : "±0";
  trendEl.textContent = `${deltaText} seit letztem Scan`;
}

// ISO-String -> "DD.MM.YYYY HH:MM" (lokale Zeit). Fallback: Original-String.
function _formatDateTime(iso) {
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ` +
      `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch (e) { return iso; }
}

// CC-LIB-FINAL Library-Home: häufigste offene Issue-Codes nach Severity-Tier,
// dann Anzahl, Top 3. Der Errors-Hinweis bleibt als Sicherheitsnetz (P0).
// CC-UI L2: jede Zeile filtert die Artist-Liste auf dieses Thema.
function _renderLibraryAttention(body) {
  const el = document.getElementById("library-attention-content");
  const s = body.statistics || {};
  const bySev = s.issues_by_severity || {};
  const byCode = s.issues_by_code || {};

  const errors = (bySev.ERROR || 0) + (bySev.CRITICAL || 0);
  const warnings = bySev.WARNING || 0;
  const infos = bySev.INFO || 0;
  const total = errors + warnings + infos;

  // Link auf die Findings der Health-Seite (/findings gibt es nicht - 404).
  const findingsLink = `<a href="${CC_BASE}/health#findings-content" class="btn btn-outline-primary w-100 mt-3">${ccIcon("search", "me-1")}Findings öffnen</a>`;

  if (total === 0) {
    el.innerHTML = '<div class="d-flex align-items-center gap-2 text-success">'
      + `${ccIcon("check")}<span>Keine kritischen Probleme.</span></div>` + findingsLink;
    return;
  }

  const errorBadge = errors > 0
    ? `<div class="mb-2">${ccStatusBadge("error", `${errors} Errors`)}</div>`
    : "";

  const topIssues = Object.entries(byCode)
    .filter(([, n]) => n > 0)
    .sort((a, b) => {
      const rankDiff = _ISSUE_SEVERITY_RANK[_issueSeverityTier(b[0])] - _ISSUE_SEVERITY_RANK[_issueSeverityTier(a[0])];
      return rankDiff !== 0 ? rankDiff : b[1] - a[1];
    })
    .slice(0, 3);

  const rows = topIssues.map(([code, n]) => `
    <button type="button" class="list-group-item list-group-item-action d-flex align-items-center gap-2 px-2"
            data-issue="${_escapeHtml(code)}" title="Betroffene Artists anzeigen">
      <span class="fw-bold cc-attention-count">${_escapeHtml(String(n))}</span>
      <span>${_issueIcon(code)}</span>
      <span class="text-secondary flex-fill text-truncate">${_escapeHtml(_issueLabel(code))}</span>
      ${ccIcon("filter", "text-secondary")}
    </button>
  `).join("");

  el.innerHTML = `
    ${errorBadge}
    ${rows ? `<div class="list-group list-group-flush">${rows}</div>` : ""}
    <div class="text-secondary small mt-2">Top ${topIssues.length} nach Severity · ${total} offen insgesamt</div>
    ${findingsLink}
  `;
  el.onclick = (event) => {
    const btn = event.target.closest?.("[data-issue]");
    if (btn) _showArtistsWithIssue(btn.dataset.issue);
  };
}

// ── Live-Scan (Library-Metadata) ─────────────────────────────────────────
// Master-Prompt Abschnitt 7 / ui_prompt.txt Abschnitt 14: Tracks/Artists/
// Albums/Mapping. Bewusst KEINE Weiter/Zurück-Pagination: jede Anfrage
// löst einen vollen Library-Scan aus - erste Seite + Kürzungshinweis.
const _METADATA_PAGE_SIZE = 50;

function _metadataTruncHint(shown, total) {
  return total > shown
    ? `<div class="alert alert-info">${ccIcon("info", "me-1")}Zeige ${shown} von ${total} — weitere nicht geladen (kein Auto-Rendern großer Listen).</div>`
    : "";
}

function _metadataTable(head, rows) {
  return '<div class="table-responsive"><table class="table table-vcenter table-sm mb-0">'
    + `<thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

function _artistEditLink(dir) {
  return dir
    ? `<a href="${CC_BASE}/library/${encodeURIComponent(dir)}" class="btn btn-sm btn-ghost-teal" aria-label="${_escapeHtml(dir)} bearbeiten">${ccIcon("edit")}</a>`
    : "";
}

function renderTracks(el, body) {
  if (!body.tracks.length) { ccState.empty(el, "Keine Tracks", "Kein Track entspricht dem Filter."); return; }
  el.innerHTML = _metadataTruncHint(body.tracks.length, body.total) + _metadataTable(
    '<th>Artist</th><th>Titel</th><th class="d-none d-md-table-cell">Album</th><th class="w-1"></th>',
    body.tracks.map((t) => `
      <tr title="${_escapeHtml(t.relative_path)}">
        <td class="text-truncate cc-col-name">${_escapeHtml(t.artist || "?")}</td>
        <td class="text-truncate cc-col-name">${_escapeHtml(t.title || t.filename)}</td>
        <td class="text-secondary text-truncate cc-col-name d-none d-md-table-cell">${_escapeHtml(t.album || "")}</td>
        <td>${_artistEditLink(t.artist_directory)}</td>
      </tr>`).join(""));
}

function renderMetadataArtists(el, body) {
  if (!body.artists.length) { ccState.empty(el, "Keine Artists"); return; }
  el.innerHTML = _metadataTruncHint(body.artists.length, body.total) + _metadataTable(
    '<th>Artist</th><th class="text-end">Dateien</th><th class="text-end">Alben</th><th class="text-end">Score</th><th class="w-1"></th>',
    body.artists.map((a) => `
      <tr>
        <td class="text-truncate cc-col-name">${_escapeHtml(a.artist)}</td>
        <td class="text-end">${a.file_count}</td>
        <td class="text-end">${a.album_count}</td>
        <td class="text-end">${a.health_score}</td>
        <td>${_artistEditLink(a.artist)}</td>
      </tr>`).join(""));
}

function renderMetadataAlbums(el, body) {
  if (!body.albums.length) { ccState.empty(el, "Keine Alben"); return; }
  el.innerHTML = _metadataTruncHint(body.albums.length, body.total) + _metadataTable(
    '<th>Album</th><th class="d-none d-sm-table-cell">Artist</th><th class="text-end">Dateien</th><th class="text-end">Score</th>',
    body.albums.map((a) => `
      <tr>
        <td class="text-truncate cc-col-name">${_escapeHtml(a.album)}</td>
        <td class="text-secondary text-truncate cc-col-name d-none d-sm-table-cell">${_escapeHtml(a.artist)}</td>
        <td class="text-end">${a.file_count}</td>
        <td class="text-end">${a.health_score}</td>
      </tr>`).join(""));
}

const _METADATA_RENDERERS = {
  tracks: renderTracks, artists: renderMetadataArtists, albums: renderMetadataAlbums,
};

function _setMetadataActive(btnId) {
  ["metadata-tracks-btn", "metadata-artists-btn", "metadata-albums-btn", "metadata-mapping-btn"].forEach((id) => {
    document.getElementById(id)?.classList?.toggle("active", id === btnId);
  });
}

function loadMetadataList(mode) {
  const el = document.getElementById("metadata-content");
  _setMetadataActive(`metadata-${mode}-btn`);
  ccState.loading(el);
  el.insertAdjacentHTML?.("afterbegin", `<div class="text-secondary small mb-2">${ccIcon("scan", "me-1")}Scan läuft, kann eine Weile dauern…</div>`);
  let url = `/api/v1/library/${mode}?limit=${_METADATA_PAGE_SIZE}&offset=0`;
  if (mode === "tracks") {
    const missing = document.getElementById("metadata-missing-filter").value;
    if (missing) url += `&issue_code=${encodeURIComponent(missing)}`;
  }
  return _libLoad("metadata-content", url, _METADATA_RENDERERS[mode], () => loadMetadataList(mode));
}

document.getElementById("metadata-tracks-btn").addEventListener("click", () => loadMetadataList("tracks"));
document.getElementById("metadata-artists-btn").addEventListener("click", () => loadMetadataList("artists"));
document.getElementById("metadata-albums-btn").addEventListener("click", () => loadMetadataList("albums"));

function renderMappingSummary(el, body) {
  const item = (label, value) => '<div class="datagrid-item">'
    + `<div class="datagrid-title">${label}</div><div class="datagrid-content h3 mb-0">${_escapeHtml(value)}</div></div>`;
  el.innerHTML = '<div class="datagrid">'
    + item("Artists", body.artists)
    + item("Channels", body.channels)
    + item("Hierarchy", body.hierarchy)
    + item("Rules", body.rules)
    + item("Aliases", body.aliases)
    + item("Overrides", body.overrides)
    + item("Primäre Genres", body.unique_primary_genres)
    + "</div>";
}
function loadMappingSummary() {
  _setMetadataActive("metadata-mapping-btn");
  ccState.loading(document.getElementById("metadata-content"));
  return _libLoad("metadata-content", "/api/v1/library/mapping-summary", renderMappingSummary, loadMappingSummary);
}
document.getElementById("metadata-mapping-btn").addEventListener("click", loadMappingSummary);

function initPage() {
  checkAuth().then((who) => {
    if (!who) return;
    loadArtistsOverview();
    loadLibraryKpis();
  });
}
initPage();
