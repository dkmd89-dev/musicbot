
  // Library Artist-Centric UX (CC-AC-1, library_artist_centric_UX.txt):
  // Artists werden beim Laden automatisch angezeigt (aus dem
  // PERSISTENTEN Report, GET /api/v1/library/artists-overview - KEIN
  // Scan-Trigger, Auftrag §7a). Bewusst getrennt von der bestehenden
  // "Library-Metadata"-Sektion unten (Klick-gesteuerter Live-Scan ueber
  // GET /api/v1/library/artists - unveraendert erhalten, Auftrag §39
  // "alte Routen nicht ungeprueft entfernen").
  let _artistsOverviewCache = [];

  // Phase E (CC-LIB-FINAL) Dashboard-Optimierung: progressive Anzeige
  // statt einer einzigen langen Tabelle (Auftrag §9/§11 "Progressive
  // Disclosure") - reines Client-seitiges Slicing des bereits geladenen
  // artists-overview-Caches, kein zusaetzlicher Request. Wird bei jeder
  // neuen Suche/Sortierung auf die erste Seite zurueckgesetzt, bleibt bei
  // "Weitere laden" erhalten.
  const _ARTISTS_PAGE_SIZE = 15;
  let _artistsVisibleCount = _ARTISTS_PAGE_SIZE;

  // CC-AC-8 Schritt 3: Kompakte Tabler-Artist-Zeile.
  // Artist, Track-/Album-Zahlen und Health werden als getrennte,
  // kompakt ausgerichtete Spalten dargestellt.
  function _artistRowHtml(a) {
    const href = `${CC_BASE}/library/${encodeURIComponent(a.artist)}`;
    const hs = a.health_score;
    // Phase E (CC-LIB-FINAL) Dashboard-Optimierung: Punkt statt Pille+Symbol
    // (dieselben .dot-ok/.dot-warn/.dot-error-Klassen wie Repair-History
    // in health.js - keine neue Farbkonvention).
    const dotClass = hs >= 90 ? "dot-ok" : hs >= 70 ? "dot-warn" : "dot-error";

    return `
      <tr
        class="artist-row"
        data-href="${_escapeHtml(href)}"
        tabindex="0"
        role="link"
      >
        <td class="py-2">
          <div class="d-flex align-items-center gap-2 min-width-0">
            <svg xmlns="http://www.w3.org/2000/svg"
                 width="18" height="18"
                 viewBox="0 0 24 24"
                 fill="none"
                 stroke="currentColor"
                 stroke-width="2"
                 stroke-linecap="round"
                 stroke-linejoin="round"
                 class="icon text-secondary flex-shrink-0"
                 aria-hidden="true">
              <path d="M9 18V5l12-2v13"/>
              <circle cx="6" cy="18" r="3"/>
              <circle cx="18" cy="16" r="3"/>
            </svg>
            <span class="fw-medium text-truncate" title="${_escapeHtml(a.artist)}">
              ${_escapeHtml(a.artist)}
            </span>
          </div>
        </td>
        <td class="py-2 text-secondary small text-end">
          ${a.file_count}
        </td>
        <td class="py-2 text-secondary small text-end">
          ${a.album_count}
        </td>
        <td class="py-2 text-end">
          <span class="dot ${dotClass}"></span>${hs}
        </td>
      </tr>
    `;
  }
  // Nutzer-Ergänzung (CC-AC-7): deterministische Sortierung - jedes
  // Kriterium verwendet den Artistnamen (A-Z) als sekundaeres
  // Tie-Breaker-Kriterium, damit die Reihenfolge bei Gleichstand stabil
  // bleibt statt sich unkontrolliert zu aendern.
  const _ARTIST_SORT_COMPARATORS = {
    name: (a, b) => a.artist.localeCompare(b.artist),
    files: (a, b) => b.file_count - a.file_count || a.artist.localeCompare(b.artist),
    albums: (a, b) => b.album_count - a.album_count || a.artist.localeCompare(b.artist),
    health: (a, b) => b.health_score - a.health_score || a.artist.localeCompare(b.artist),
    // CC-AC-8 Schritt 4: für "welcher Artist ist am schlechtesten?"
    health_asc: (a, b) => a.health_score - b.health_score || a.artist.localeCompare(b.artist),
  };

  function _renderArtistsOverviewList() {
    const el = document.getElementById("artists-overview-content");
    const query = (document.getElementById("artist-search").value || "").trim().toLowerCase();
    const sortKey = document.getElementById("artist-sort").value || "name";
    const filtered = query
      ? _artistsOverviewCache.filter((a) => a.artist.toLowerCase().includes(query))
      : _artistsOverviewCache.slice();
    if (!filtered.length) {
      el.innerHTML = query
        ? '<p class="empty-note">Keine Artists für diese Suche gefunden.</p>'
        : '<p class="empty-note">Keine Artists gefunden.</p>';
      return;
    }
    filtered.sort(_ARTIST_SORT_COMPARATORS[sortKey] || _ARTIST_SORT_COMPARATORS.name);

    const shown = filtered.slice(0, _artistsVisibleCount);
    const rest = filtered.length - shown.length;
    const loadMore = rest > 0
      ? `<div class="text-center mt-3">
           <p class="text-secondary small mb-2">${shown.length} von ${filtered.length} Artists</p>
           <button type="button" class="btn btn-outline-secondary btn-sm" id="artists-load-more-btn">Weitere laden</button>
         </div>`
      : "";

    el.innerHTML = `
      <div class="table-responsive">
        <table class="table table-vcenter table-hover table-striped mb-0">
          <thead>
            <tr>
              <th>Artist</th>
              <th class="text-end">Tracks</th>
              <th class="text-end">Alben</th>
              <th class="text-end">Health</th>
            </tr>
          </thead>
          <tbody>
            ${shown.map((a) => _artistRowHtml(a)).join("")}
          </tbody>
        </table>
      </div>
      ${loadMore}
    `;

    const artistTable = el.querySelector("table");
    const artistTbody = artistTable?.querySelector("tbody");

    artistTbody?.addEventListener("click", (event) => {
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
    if (body.stale) {
      const note = document.createElement("p");
      note.className = "hint";
      note.textContent = `Stand: ${body.generated_at || "unbekannt"} (nicht mehr aktuell)`;
      el.parentNode.insertBefore(note, el);
    }
    _renderArtistsOverviewList();
  }

  function loadArtistsOverview() {
    return _loadInto(
      "artists-overview-content", "/api/v1/library/artists-overview",
      renderArtistsOverview, loadArtistsOverview,
    );
  }

  function _resetArtistsPagingAndRender() {
    _artistsVisibleCount = _ARTISTS_PAGE_SIZE;
    _renderArtistsOverviewList();
  }
  document.getElementById("artist-search").addEventListener("input", _resetArtistsPagingAndRender);
  document.getElementById("artist-sort").addEventListener("change", _resetArtistsPagingAndRender);

  // Library-KPI-Zeile (Nutzer-Ergänzung CC-AC-7): nutzt den bestehenden
  // Cache-Read-Endpunkt GET /api/v1/library/health/cached (Auftrag §5 -
  // "falls ein bestehender Endpunkt alle KPIs liefert, diesen verwenden"),
  // KEINE neue API, KEINE Client-Aggregation. Fehlerisolation bewusst
  // eigenstaendig (eigenes try/catch statt _loadInto()): ein Fehler hier
  // darf die Artist-Liste/den Rest der Seite nicht beeintraechtigen - bei
  // Fehler oder fehlenden Feldern bleibt die KPI-Zeile schlicht
  // ausgeblendet, niemals geschaetzte Werte.
  async function loadLibraryKpis() {
    try {
      const res = await fetch(apiUrl("/api/v1/library/health/cached"), { credentials: "same-origin" });
      if (!res.ok) return;
      const body = await res.json();
      const lib = body.library || {};
      if (typeof lib.artists !== "number" || typeof lib.files !== "number" || typeof lib.albums !== "number") return;
      document.getElementById("library-kpi-artists").textContent = lib.artists;
      document.getElementById("library-kpi-tracks").textContent = lib.files;
      document.getElementById("library-kpi-albums").textContent = lib.albums;

      document.getElementById("library-kpi-tiles").hidden = false;

      // CC-LIB-FINAL Library-Home: "Zuletzt gescannt" prominent unter dem
      // Seitentitel statt nur klein im Health-Panel — scan.completed_at
      // kommt aus derselben bereits geladenen /health/cached-Antwort,
      // kein zusätzlicher Request.
      const _scan = body.scan || {};
      document.getElementById("library-last-scan").textContent = _scan.completed_at
        ? `Zuletzt gescannt: ${_formatDateTime(_scan.completed_at)}`
        : "";

      // CC-AC-8 Schritt 2: Health-Snapshot + Attention-Block aus derselben
      // Antwort befüllen — kein zusätzlicher Request.
      _renderLibraryHealthSnapshot(body);
      _renderLibraryAttention(body);
    } catch (err) {
      // Fehlerisolation: KPI-Zeile + beide Blöcke bleiben ausgeblendet,
      // kein Page-Error.
      document.getElementById("library-health-panel").hidden = true;
      document.getElementById("library-attention-panel").hidden = true;
    }
  }

  // CC-AC-8 Schritt 3: Health-Panel kompakter (Option 1).
  // Die Health-Zahl steht bereits in der KPI-Kachel oben — hier nur noch
  // Status-Label, Kernzahlen und Trend. Der "Stand"-Zeitstempel (scan.
  // completed_at) steht seit CC-LIB-FINAL prominent unter dem Seitentitel
  // (loadLibraryKpis()) statt hier klein im Panel — keine Dopplung.
  function _renderLibraryHealthSnapshot(body) {
    const el = document.getElementById("library-health-content");
    const h = body.health || {};
    const s = body.statistics || {};
    if (typeof h.score !== "number") {
      document.getElementById("library-health-panel").hidden = true;
      return;
    }

    const summary = (typeof s.total_files === "number")
      ? `${s.total_files} Tracks · ${s.total_artists} Artists · ${s.total_albums} Alben`
      : "";

    // Phase E (CC-LIB-FINAL) Dashboard-Optimierung: derselbe Status<->Farbe-
    // Vertrag wie health.js's Health-Kachel (_HEALTH_STATUS_COLOR, seit
    // dieser Phase in common.js) statt einer eigenen, gröberen
    // Schwellenwert-Logik - identisches Aussehen auf beiden Seiten.
    const color = _HEALTH_STATUS_COLOR[h.status] || "secondary";
    const pct = Math.max(0, Math.min(100, Number(h.score)));

    // Die fruehere ✓/⚠/✕-Badgereihe (fehlerfrei/Warn/Error) ist in die
    // "Aufmerksamkeit"-Karte gewandert (_renderLibraryAttention, dort mit
    // demselben issues_by_severity - keine doppelte Zahl auf dieser Karte
    // mehr) - diese Karte beantwortet nur noch "wie gesund ist die Library
    // insgesamt", nicht mehr zusaetzlich "was genau ist kaputt".
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

      <a href="${CC_BASE}/health" class="btn btn-outline-primary w-100 mt-3">Health öffnen →</a>
    `;

    loadLibraryHealthSparkline();
  }

  // Phase E (CC-LIB-FINAL): eigener, isolierter Request fuer den
  // Score-Verlauf (GET /api/v1/library/health/score-history, derselbe
  // Endpunkt/dieselbe _sparklineSvg() wie health.js) - unabhaengig von
  // /health/cached, damit ein Fehler hier nie die restliche Health-Karte
  // beeintraechtigt (identisches Fehlerisolationsprinzip wie
  // loadLibraryKpis()).
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

  // CC-LIB-FINAL Library-Home: Trend als Differenz erster vs. letzter
  // Score-Wert im sichtbaren score-history-Fenster (Auftrag: "GET
  // /api/v1/health/score-history liefert die Reihe bereits" — kein neuer
  // Endpunkt, keine neue Anfrage, dieselbe Antwort wie die Sparkline
  // oben). API liefert aelteste zuerst (siehe _sparklineSvg()-Kommentar),
  // erster Eintrag ist also der aelteste sichtbare, letzter der aktuellste
  // Scan. Unter zwei gewerteten Laeufen gibt es keinen sinnvollen Trend.
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

  // CC-LIB-FINAL Library-Home (Nutzer-Freigabe): Aufmerksamkeit-Karte als
  // Zeilenliste der haeufigsten offenen Issue-Codes (Icon + Anzahl +
  // Klartext-Label aus dem gemeinsamen _ISSUE_LABELS, common.js) statt
  // Code-Badges. Kandidaten sind ALLE Codes aus statistics.issues_by_code
  // (nicht mehr nur WARNING-Codes wie zuvor) - sortiert nach Severity-Tier
  // absteigend (_ISSUE_SEVERITY_RANK, common.js), dann Anzahl absteigend,
  // Top 3. Errors werden dadurch nicht mehr nur als Summe angezeigt: ein
  // ERROR-/CRITICAL-Code mit offenen Treffern landet automatisch oben in
  // der Liste. Der separate Errors-Hinweis bleibt zusaetzlich als
  // Sicherheitsnetz erhalten (P0-Prioritaet, CLAUDE.md Abschnitt 23) fuer
  // den Fall, dass ein zukuenftiger ERROR-Code hier noch nicht in
  // _ISSUE_ERROR_CODES nachgepflegt wurde.
  function _renderLibraryAttention(body) {
    const el = document.getElementById("library-attention-content");
    const s = body.statistics || {};
    const bySev = s.issues_by_severity || {};
    const byCode = s.issues_by_code || {};

    const errors = (bySev.ERROR || 0) + (bySev.CRITICAL || 0);
    const warnings = bySev.WARNING || 0;
    const infos = bySev.INFO || 0;
    const total = errors + warnings + infos;

    // CC-AC-8 Schritt 4: Empty State — wenn wirklich alles 0 ist,
    // einen grünen "Keine kritischen Probleme"-Hinweis zeigen statt
    // drei Null-Zeilen. (Nur bei vollständig leerem Report.)
    if (total === 0) {
      el.innerHTML = '<p class="empty-note empty-note-ok">✓ Keine kritischen Probleme.</p>' +
        `<a href="${CC_BASE}/findings" class="btn btn-outline-primary w-100 mt-2">Findings öffnen →</a>`;
      return;
    }

    const errorBadge = errors > 0
      ? `<div class="mb-2"><span class="badge bg-red-lt text-red">${errors} Errors</span></div>`
      : "";

    const topIssues = Object.entries(byCode)
      .filter(([, n]) => n > 0)
      .sort((a, b) => {
        const rankDiff = _ISSUE_SEVERITY_RANK[_issueSeverityTier(b[0])] - _ISSUE_SEVERITY_RANK[_issueSeverityTier(a[0])];
        return rankDiff !== 0 ? rankDiff : b[1] - a[1];
      })
      .slice(0, 3);

    const rows = topIssues.map(([code, n]) => `
      <div class="d-flex align-items-center gap-2 py-1">
        <span class="fw-bold" style="min-width: 1.5em;">${_escapeHtml(String(n))}</span>
        <span>${_issueIcon(code)}</span>
        <span class="text-secondary">${_escapeHtml(_ISSUE_LABELS[code] || code)}</span>
      </div>
    `).join("");

    el.innerHTML = `
      ${errorBadge}
      ${rows}
      <div class="text-secondary small mt-2">Top ${topIssues.length} nach Severity · ${total} offen insgesamt</div>
      <a href="${CC_BASE}/findings" class="btn btn-outline-primary w-100 mt-3">Findings öffnen →</a>
    `;
  }

  // Master-Prompt Abschnitt 7 "METADATA MANAGEMENT" / ui_prompt.txt
  // Abschnitt 14 "LIBRARY" - Tracks/Artists/Albums/Mapping-Browser.
  // Bewusst KEINE Weiter/Zurück-Pagination-Buttons: jede Server-Anfrage
  // loest einen vollen Library-Scan aus (identisch zu Repair-Plan/L2-L3)
  // - stattdessen erste Seite + Trunkierungshinweis.
  const _METADATA_PAGE_SIZE = 50;

  function renderTracks(el, body) {
    if (!body.tracks.length) { el.innerHTML = '<p class="empty-note">Keine Tracks.</p>'; return; }
    const trunc = body.total > body.tracks.length
      ? `<p class="empty-note">Zeige ${body.tracks.length} von ${body.total} — weitere nicht geladen (kein Auto-Rendern großer Listen).</p>`
      : "";
    el.innerHTML = trunc + '<div class="row-list">' + body.tracks.map((t) => `
      <div class="row-item" title="${_escapeHtml(t.relative_path)}">
        <div class="row-main">${_escapeHtml(t.artist || "?")} — ${_escapeHtml(t.title || t.filename)}</div>
        <div class="row-count">${_escapeHtml(t.album || "")}</div>
      </div>
    `).join("") + "</div>";
  }

  function renderMetadataArtists(el, body) {
    if (!body.artists.length) { el.innerHTML = '<p class="empty-note">Keine Artists.</p>'; return; }
    const trunc = body.total > body.artists.length
      ? `<p class="empty-note">Zeige ${body.artists.length} von ${body.total} — weitere nicht geladen (kein Auto-Rendern großer Listen).</p>`
      : "";
    el.innerHTML = trunc + '<div class="row-list">' + body.artists.map((a) => `
      <div class="row-item">
        <div class="row-main">${_escapeHtml(a.artist)}</div>
        <div class="row-count">${a.file_count} Dateien, ${a.album_count} Alben — Score ${a.health_score}</div>
      </div>
    `).join("") + "</div>";
  }

  function renderMetadataAlbums(el, body) {
    if (!body.albums.length) { el.innerHTML = '<p class="empty-note">Keine Alben.</p>'; return; }
    const trunc = body.total > body.albums.length
      ? `<p class="empty-note">Zeige ${body.albums.length} von ${body.total} — weitere nicht geladen (kein Auto-Rendern großer Listen).</p>`
      : "";
    el.innerHTML = trunc + '<div class="row-list">' + body.albums.map((a) => `
      <div class="row-item">
        <div class="row-main">${_escapeHtml(a.artist)} — ${_escapeHtml(a.album)}</div>
        <div class="row-count">${a.file_count} Dateien — Score ${a.health_score}</div>
      </div>
    `).join("") + "</div>";
  }

  const _METADATA_RENDERERS = {
    tracks: renderTracks, artists: renderMetadataArtists, albums: renderMetadataAlbums,
  };

  function loadMetadataList(mode) {
    document.getElementById("metadata-content").innerHTML =
      '<span class="empty-note">Scan läuft, kann eine Weile dauern…</span>';
    let url = `/api/v1/library/${mode}?limit=${_METADATA_PAGE_SIZE}&offset=0`;
    if (mode === "tracks") {
      const missing = document.getElementById("metadata-missing-filter").value;
      if (missing) url += `&issue_code=${encodeURIComponent(missing)}`;
    }
    return _loadInto("metadata-content", url, _METADATA_RENDERERS[mode]);
  }

  document.getElementById("metadata-tracks-btn").addEventListener("click", () => loadMetadataList("tracks"));
  document.getElementById("metadata-artists-btn").addEventListener("click", () => loadMetadataList("artists"));
  document.getElementById("metadata-albums-btn").addEventListener("click", () => loadMetadataList("albums"));

  function renderMappingSummary(el, body) {
    el.innerHTML = `
      <div class="counts-grid">
        <div><strong>${body.artists}</strong><br>Artists</div>
        <div><strong>${body.channels}</strong><br>Channels</div>
        <div><strong>${body.hierarchy}</strong><br>Hierarchy</div>
        <div><strong>${body.rules}</strong><br>Rules</div>
        <div><strong>${body.aliases}</strong><br>Aliases</div>
        <div><strong>${body.overrides}</strong><br>Overrides</div>
        <div><strong>${body.unique_primary_genres}</strong><br>Primäre Genres</div>
      </div>
    `;
  }
  function loadMappingSummary() {
    document.getElementById("metadata-content").innerHTML = '<span class="empty-note">Lädt…</span>';
    return _loadInto("metadata-content", "/api/v1/library/mapping-summary", renderMappingSummary);
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
