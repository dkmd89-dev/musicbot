// control_center/static/pages/navidrome.js
// Navidrome-Seite (CC-UI N1): Kopf mit Suche/Status/Scan, Pill-Reiter, Start
// mit Regalen, Cover-/Artist-Raster mit "Mehr laden". Die Detailansichten
// (Artist/Album/Song/Genre/Playlist) laufen bis N2 unverändert im Modal-Stack.
// Cover-Art via /api/v1/navidrome/cover/{id}.

// =====================================================================
// State
// =====================================================================
const _navState = {
  tab: "start",       // aktiver Reiter (oder "search")
  prevTab: "start",   // letzter echter Reiter, Ziel beim Verlassen der Suche
  searchSeq: 0,       // verwirft veraltete Suchantworten
  loaded: {},         // Reiter -> bereits geladen
  artists:   { page: 0, size: 30, html: "" },
  albums:    { page: 0, size: 30, html: "" },
  playlists: { page: 0, size: 20, html: "" },
};

// =====================================================================
// Helper
// =====================================================================
function _navEndpoints() {
  const el = document.getElementById("navidrome-status-row");
  const status = el?.dataset?.statusEndpoint || "/api/v1/navidrome/status";
  const scan   = el?.dataset?.scanEndpoint   || "/api/v1/navidrome/scan";
  const base   = status.replace(/\/status$/, "");
  return { base, status, scan };
}

// Lesender Zugriff auf die Navidrome-API (Fehler: CcApiError mit Meldung).
function _navFetch(path) {
  const { base } = _navEndpoints();
  return ccApi("GET", base + path);
}

function _navEsc(s) {
  return (typeof _escapeHtml === "function")
    ? _escapeHtml(String(s ?? ""))
    : String(s ?? "");
}
function _fmtDuration(sec) {
  if (!sec && sec !== 0) return "";
  const m = Math.floor(sec / 60);
  const s = String(sec % 60).padStart(2, "0");
  return `${m}:${s}`;
}
function _coverUrl(coverId, size = 300) {
  if (!coverId) return "";
  const { base } = _navEndpoints();
  return apiUrl(`${base}/cover/${encodeURIComponent(coverId)}?size=${size}`);
}
// Cover mit Platzhalter darunter: schlägt das Laden fehl, bleibt das Icon sichtbar.
function _coverImg(coverId, size = 300) {
  const fallback = `<div class="nav-cover-fallback">${ccIcon("disc", "icon-lg")}</div>`;
  if (!coverId) return `<div class="nav-cover-wrap">${fallback}</div>`;
  return `<div class="nav-cover-wrap">${fallback}
    <img class="nav-cover-img" src="${_coverUrl(coverId, size)}" alt=""
         loading="lazy" onerror="this.style.display='none'"></div>`;
}

// =====================================================================
// Status
// =====================================================================
function renderNavidromeStatus(data) {
  const badge = document.getElementById("navidrome-status");
  const countEl = document.getElementById("navidrome-artist-count");
  if (badge) {
    const online = !!data.connected;
    badge.className = "badge " + (online ? "bg-green-lt" : "bg-red-lt");
    badge.innerHTML = ccIcon(online ? "check" : "alert", "icon-sm me-1") + (online ? "Online" : "Offline");
  }
  if (countEl) {
    countEl.textContent = data.artist_count != null ? `${data.artist_count} Artists` : "";
  }
}
async function loadNavidromeStatus() {
  const { status } = _navEndpoints();
  try {
    renderNavidromeStatus(await ccApi("GET", status));
  } catch (err) {
    if (err && err.status === 401) return;
    renderNavidromeStatus({ connected: false });
  }
}

// =====================================================================
// Scan (Ausgabe im Seitenpanel, Ergebnis als Toast)
// =====================================================================
async function triggerNavidromeScan() {
  const btn = document.getElementById("navidrome-scan-btn");
  const out = document.getElementById("navidrome-scan-output");
  const logBtn = document.getElementById("navidrome-scan-log-btn");
  if (!btn || !out) return;
  btn.disabled = true;
  out.textContent = "Scan läuft…";
  if (logBtn) logBtn.classList.remove("d-none");
  try {
    const { scan } = _navEndpoints();
    const data = await ccApi("POST", scan);
    if (data.success) {
      out.textContent = `Scan erfolgreich (rc=${data.returncode})\n${data.stdout || ""}`;
      ccToast("ok", "Scan abgeschlossen");
    } else {
      out.textContent = `Scan fehlgeschlagen (rc=${data.returncode})\n${data.stderr || ""}`;
      ccToast("error", "Scan fehlgeschlagen", "Details in der Scan-Ausgabe.");
    }
    loadNavidromeStatus();
  } catch (err) {
    out.textContent = `Fehler: ${err.message}`;
    ccToast("error", "Scan nicht möglich", err.message);
  } finally {
    btn.disabled = false;
  }
}

// =====================================================================
// Modal-Stack
// =====================================================================
function _navForceClose(el) {
  if (!el) return;
  el.classList.remove("show");
  el.style.display = "none";
  el.setAttribute("aria-hidden", "true");
  el.removeAttribute("aria-modal");
  document.body.classList.remove("modal-open");
  document.body.style.removeProperty("overflow");
  document.body.style.removeProperty("padding-right");
  document.querySelectorAll(".modal-backdrop").forEach(b => b.remove());
}

const _navView = {
  stack: [],

  async push(view) {
    this.stack.push(view);
    await this._render();
  },

  async jumpTo(index) {
    this.stack = this.stack.slice(0, index + 1);
    await this._render();
  },

  async back() {
    if (this.stack.length > 1) {
      this.stack.pop();
      await this._render();
    } else {
      this.close();
    }
  },

  close() {
    this.stack = [];
    const el = document.getElementById("nav-detail-modal");
    if (!el) return;
    if (window.bootstrap?.Modal) {
      try {
        bootstrap.Modal.getOrCreateInstance(el).hide();
        return;
      } catch (_) { /* fallthrough auf Force-Close */ }
    }
    _navForceClose(el);
  },

  async _render() {
    const modalEl = document.getElementById("nav-detail-modal");
    const bodyEl  = document.getElementById("nav-detail-body");
    const titleEl = document.getElementById("nav-detail-title");
    const backBtn = document.getElementById("nav-detail-back");

    if (!this.stack.length) return;

    if (window.bootstrap?.Modal) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    } else {
      modalEl.style.display = "block";
      modalEl.classList.add("show");
    }

    const top = this.stack[this.stack.length - 1];
    titleEl.textContent = top.label || "Details";

    // Back-Button IMMER sichtbar - bei Root als Schliessen-X,
    // tiefer im Stack als Zurueck-Pfeil.
    backBtn.classList.remove("d-none");
    if (this.stack.length <= 1) {
      backBtn.title = "Schließen";
      backBtn.setAttribute("aria-label", "Schließen");
      backBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="icon" width="24" height="24"
           viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none"
           stroke-linecap="round" stroke-linejoin="round">
        <path stroke="none" d="M0 0h24v24H0z" fill="none"/>
        <path d="M18 6l-12 12"/>
        <path d="M6 6l12 12"/>
      </svg>`;
    } else {
      backBtn.title = "Zurück";
      backBtn.setAttribute("aria-label", "Zurück");
      backBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="icon" width="24" height="24"
           viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none"
           stroke-linecap="round" stroke-linejoin="round">
        <path stroke="none" d="M0 0h24v24H0z" fill="none"/>
        <path d="M15 6l-6 6l6 6"/>
      </svg>`;
    }

    bodyEl.innerHTML = `<div class="text-center text-muted py-5">
      <div class="spinner-border text-primary" role="status"></div>
      <div class="mt-2">Lädt…</div>
    </div>`;

    try {
      const html = await this._renderContent(top);
      bodyEl.innerHTML = this._breadcrumbHtml() + html;
      _wireDetailLinks(bodyEl);
      _wireBreadcrumbJump(bodyEl);
    } catch (err) {
      bodyEl.innerHTML = this._breadcrumbHtml() +
        `<div class="alert alert-danger">❌ ${_navEsc(err.message)}</div>`;
      _wireBreadcrumbJump(bodyEl);
    }
  },

  _breadcrumbHtml() {
    if (this.stack.length <= 1) return "";
    const items = this.stack.map((v, i) => {
      const label = _navEsc(v.label || "");
      const isLast = i === this.stack.length - 1;
      return isLast
        ? `<li class="breadcrumb-item active" aria-current="page">${label}</li>`
        : `<li class="breadcrumb-item"><a href="#" data-nav-jump="${i}">${label}</a></li>`;
    }).join("");
    return `<nav aria-label="breadcrumb"><ol class="breadcrumb">${items}</ol></nav>`;
  },

  async _renderContent(view) {
    switch (view.type) {
      case "artist":   return await _renderArtistView(view.id);
      case "album":    return await _renderAlbumView(view.id);
      case "song":     return await _renderSongView(view.id);
      case "genre":    return await _renderGenreView(view.id);
      case "playlist": return await _renderPlaylistView(view.id);
      case "topSongs": return await _renderTopSongsView(view.id, view.artistName);
      default:         return `<div class="text-muted">Unbekannte Ansicht.</div>`;
    }
  },
};

function _wireBreadcrumbJump(root) {
  root.querySelectorAll("[data-nav-jump]").forEach(a => {
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      _navView.jumpTo(parseInt(a.dataset.navJump, 10));
    });
  });
}

// =====================================================================
// View-Renderer (Detailansichten im Modal, bis N2 unverändert)
// =====================================================================
async function _renderArtistView(id) {
  const data = await _navFetch(`/artists/${encodeURIComponent(id)}`);
  const albumCount = data.album_count ?? (data.albums?.length || 0);
  const albumWord = albumCount === 1 ? "Album" : "Alben";

  const albumsHtml = (data.albums?.length)
    ? `<div class="row row-cards mt-3">${data.albums.map(a => `
        <div class="col-6 col-md-4">
          <a href="#" class="card card-link nav-album-link"
             data-id="${_navEsc(a.id)}" data-name="${_navEsc(a.name)}">
            <div style="aspect-ratio:1;overflow:hidden;background:#1a1a1a;">
              ${_coverImg(a.cover_art, 300)}
            </div>
            <div class="card-body p-2">
              <div class="text-truncate fw-bold">${_navEsc(a.name)}</div>
              <div class="text-muted small text-truncate">
                ${a.year ? _navEsc(String(a.year)) : ""}${a.song_count ? ` · ${a.song_count} Songs` : ""}
              </div>
            </div>
          </a>
        </div>`).join("")}</div>`
    : `<div class="text-muted mt-3">Keine Alben gefunden.</div>`;

  return `
    <div class="d-flex align-items-center gap-3 mb-3">
      <span class="avatar avatar-lg bg-primary-lt">
        <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-lg" width="24" height="24"
             viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" fill="none"
             stroke-linecap="round" stroke-linejoin="round">
          <path stroke="none" d="M0 0h24v24H0z" fill="none"/>
          <path d="M8 7a4 4 0 1 0 8 0a4 4 0 0 0 -8 0"/>
          <path d="M6 21v-2a4 4 0 0 1 4 -4h4a4 4 0 0 1 4 4v2"/>
        </svg>
      </span>
      <div class="min-w-0">
        <h2 class="mb-0 text-truncate">${_navEsc(data.name)}</h2>
        <div class="text-muted">${albumCount} ${albumWord}</div>
      </div>
      <div class="ms-auto">
        <button class="btn btn-sm btn-outline-primary"
                data-nav-action="top-songs"
                data-artist-id="${_navEsc(data.id)}"
                data-artist-name="${_navEsc(data.name)}">
          🔥 Top Songs
        </button>
      </div>
    </div>
    ${albumsHtml}
  `;
}

async function _renderAlbumView(id) {
  const data = await _navFetch(`/albums/${encodeURIComponent(id)}`);
  const artistLink = data.artist_id
    ? `<a href="#" class="nav-artist-link" data-id="${_navEsc(data.artist_id)}" data-name="${_navEsc(data.artist || "")}">${_navEsc(data.artist || "")}</a>`
    : _navEsc(data.artist || "");

  const metaParts = [];
  if (data.year) metaParts.push(_navEsc(String(data.year)));
  if (data.song_count) metaParts.push(`${data.song_count} Songs`);
  if (data.duration) metaParts.push(_fmtDuration(data.duration));

  const songsHtml = (data.songs?.length)
    ? `<table class="table table-sm table-vcenter mt-3">
         <tbody>${data.songs.map((s, i) => `
           <tr>
             <td class="text-muted" style="width:2.5rem;">${s.track ?? (i + 1)}</td>
             <td>
               <a href="#" class="nav-song-link"
                  data-id="${_navEsc(s.id)}" data-name="${_navEsc(s.title)}">
                 ${_navEsc(s.title)}
               </a>
             </td>
             <td class="text-end text-muted" style="width:5rem;">${s.duration ? _fmtDuration(s.duration) : ""}</td>
           </tr>`).join("")}</tbody>
       </table>`
    : `<div class="text-muted mt-3">Keine Songs.</div>`;

  return `
    <div class="row g-3">
      <div class="col-md-4">
        <div class="rounded overflow-hidden" style="aspect-ratio:1;background:#1a1a1a;">
          ${_coverImg(data.cover_art, 500)}
        </div>
      </div>
      <div class="col-md-8">
        <h2 class="mb-1">${_navEsc(data.name)}</h2>
        <div class="text-muted mb-2">${artistLink}${metaParts.length ? " · " + metaParts.join(" · ") : ""}</div>
      </div>
    </div>
    ${songsHtml}
  `;
}

async function _renderSongView(id) {
  const data = await _navFetch(`/songs/${encodeURIComponent(id)}`);
  const genres = (data.genres || []).join(", ") || data.genre || "–";
  const artistLink = data.artist_id
    ? `<a href="#" class="nav-artist-link" data-id="${_navEsc(data.artist_id)}" data-name="${_navEsc(data.artist || "")}">${_navEsc(data.artist || "")}</a>`
    : _navEsc(data.artist || "–");
  const albumLink = data.album_id
    ? `<a href="#" class="nav-album-link" data-id="${_navEsc(data.album_id)}" data-name="${_navEsc(data.album || "")}">${_navEsc(data.album || "")}</a>`
    : _navEsc(data.album || "–");

  return `
    <div class="d-flex gap-3 align-items-start">
      <div class="rounded overflow-hidden flex-shrink-0" style="width:120px;height:120px;background:#1a1a1a;">
        ${_coverImg(data.cover_art, 300)}
      </div>
      <div class="min-w-0">
        <h2 class="mb-1">🎵 ${_navEsc(data.title)}</h2>
        <div class="text-muted">${artistLink}</div>
        <div class="text-muted small">${albumLink}</div>
      </div>
    </div>
    <dl class="row mt-3 mb-0">
      <dt class="col-4 col-sm-3">Dauer</dt><dd class="col-8 col-sm-9">${data.duration ? _fmtDuration(data.duration) : "–"}</dd>
      <dt class="col-4 col-sm-3">Genre</dt><dd class="col-8 col-sm-9">${_navEsc(genres)}</dd>
      <dt class="col-4 col-sm-3">Jahr</dt><dd class="col-8 col-sm-9">${data.year ?? "–"}</dd>
      <dt class="col-4 col-sm-3">Play-Count</dt><dd class="col-8 col-sm-9">${data.play_count ?? "–"}</dd>
    </dl>
  `;
}

async function _renderGenreView(name) {
  const data = await _navFetch(`/genres/${encodeURIComponent(name)}`);
  const songsHtml = (data.songs?.length)
    ? `<table class="table table-sm table-vcenter mt-3">
         <tbody>${data.songs.map((s, i) => `
           <tr>
             <td class="text-muted" style="width:2.5rem;">${i + 1}</td>
             <td>
               <a href="#" class="nav-song-link" data-id="${_navEsc(s.id)}" data-name="${_navEsc(s.title)}">
                 ${_navEsc(s.title)}
               </a>
               <div class="text-muted small text-truncate">${_navEsc(s.artist || "")} · ${_navEsc(s.album || "")}</div>
             </td>
             <td class="text-end text-muted" style="width:5rem;">${s.duration ? _fmtDuration(s.duration) : ""}</td>
           </tr>`).join("")}</tbody>
       </table>`
    : `<div class="text-muted mt-3">Keine Songs.</div>`;
  return `<h2 class="mb-3">🎭 ${_navEsc(name)}</h2>${songsHtml}`;
}

async function _renderPlaylistView(id) {
  const data = await _navFetch(`/playlists/${encodeURIComponent(id)}`);
  const songsHtml = (data.songs?.length)
    ? `<table class="table table-sm table-vcenter mt-3">
         <tbody>${data.songs.map((s, i) => `
           <tr>
             <td class="text-muted" style="width:2.5rem;">${i + 1}</td>
             <td>
               <a href="#" class="nav-song-link" data-id="${_navEsc(s.id)}" data-name="${_navEsc(s.title)}">
                 ${_navEsc(s.title)}
               </a>
               <div class="text-muted small text-truncate">${_navEsc(s.artist || "")}</div>
             </td>
             <td class="text-end text-muted" style="width:5rem;">${s.duration ? _fmtDuration(s.duration) : ""}</td>
           </tr>`).join("")}</tbody>
       </table>`
    : `<div class="text-muted mt-3">Diese Playlist ist leer.</div>`;
  return `
    <h2 class="mb-1">📋 ${_navEsc(data.name)}</h2>
    <div class="text-muted mb-3">
      ${_navEsc(data.owner || "")} · ${data.song_count} Songs${data.duration ? ` · ${_fmtDuration(data.duration)}` : ""}
    </div>
    ${songsHtml}
  `;
}

async function _renderTopSongsView(artistId, artistName) {
  const data = await _navFetch(`/artists/${encodeURIComponent(artistId)}/top?count=25`);
  const songsHtml = (data.songs?.length)
    ? `<table class="table table-sm table-vcenter mt-3">
         <tbody>${data.songs.map((s, i) => `
           <tr>
             <td class="text-muted" style="width:2.5rem;">${i + 1}</td>
             <td>
               <a href="#" class="nav-song-link" data-id="${_navEsc(s.id)}" data-name="${_navEsc(s.title)}">
                 ${_navEsc(s.title)}
               </a>
               <div class="text-muted small text-truncate">${_navEsc(s.album || "")}</div>
             </td>
           </tr>`).join("")}</tbody>
       </table>`
    : `<div class="text-muted mt-3">Keine Songs.</div>`;
  return `<h2 class="mb-3">🔥 Top Songs – ${_navEsc(artistName)}</h2>${songsHtml}`;
}

// =====================================================================
// Kacheln (Alben/Artists/Songs) - gemeinsam für Regale, Raster und Suche
// =====================================================================
function _navAlbumTile(a) {
  const sub = [a.artist || "", a.year ? String(a.year) : ""].filter(Boolean).join(" · ");
  return `
    <a href="#" class="nav-tile nav-album-link" data-id="${_navEsc(a.id)}" data-name="${_navEsc(a.name)}">
      <div class="nav-cover">${_coverImg(a.cover_art, 300)}</div>
      <div class="nav-tile-title">${_navEsc(a.name)}</div>
      <div class="nav-tile-sub">${_navEsc(sub)}</div>
    </a>`;
}

function _navArtistCard(a) {
  // Navidrome-Cover-Fallback: artist_id funktioniert als Cover-ID, weil
  // Navidrome artist.jpg im Artist-Verzeichnis automatisch ausliefert.
  const coverId = a.cover_art || a.coverArt || a.id || null;
  const initial = (a.name || "?").charAt(0).toUpperCase();
  const avatarInner = coverId
    ? `<span class="artist-initial">${_navEsc(initial)}</span>
       <img class="nav-cover-img" src="${_coverUrl(coverId, 300)}" alt="" loading="lazy"
            onerror="this.style.display='none'">`
    : `<span class="artist-initial">${_navEsc(initial)}</span>`;
  const meta = a.album_count != null
    ? `<div class="artist-meta">${a.album_count} ${a.album_count === 1 ? "Album" : "Alben"}</div>`
    : "";
  return `
    <a href="#" class="artist-card nav-artist-link" data-id="${_navEsc(a.id)}" data-name="${_navEsc(a.name)}">
      <div class="artist-avatar">${avatarInner}</div>
      <div class="artist-name">${_navEsc(a.name)}</div>
      ${meta}
    </a>`;
}

function _navSongRow(s, withAlbum) {
  const sub = [s.artist || "", withAlbum ? (s.album || "") : ""].filter(Boolean).join(" · ");
  return `
    <a href="#" class="list-group-item list-group-item-action nav-song-link"
       data-id="${_navEsc(s.id)}" data-name="${_navEsc(s.title)}">
      <div class="row align-items-center g-2">
        <div class="col-auto"><span class="avatar avatar-sm bg-teal-lt">${ccIcon("music")}</span></div>
        <div class="col min-w-0">
          <div class="text-truncate fw-medium">${_navEsc(s.title)}</div>
          <div class="text-secondary small text-truncate">${_navEsc(sub)}</div>
        </div>
        <div class="col-auto text-secondary small">${s.duration ? _fmtDuration(s.duration) : ""}</div>
      </div>
    </a>`;
}

function _navSection(title, icon, bodyHtml) {
  return `<section class="mb-4">
    <h3 class="subheader mb-2">${ccIcon(icon, "icon-sm me-1")}${_navEsc(title)}</h3>${bodyHtml}</section>`;
}
function _navAlbumGrid(items) {
  return `<div class="nav-grid">${items.map(_navAlbumTile).join("")}</div>`;
}
function _navArtistGrid(items) {
  return `<div class="nav-grid nav-grid-artists">${items.map(_navArtistCard).join("")}</div>`;
}
function _navSongList(items, withAlbum) {
  return `<div class="list-group list-group-flush">${items.map(s => _navSongRow(s, withAlbum)).join("")}</div>`;
}
function _navShelfRow(html) {
  return `<div class="nav-shelf-row">${html}</div>`;
}

// =====================================================================
// Start: Regale (jedes lädt unabhängig, Fehler nur im jeweiligen Regal)
// =====================================================================
async function loadShelfNewest() {
  const el = document.getElementById("nav-shelf-newest");
  if (!el) return;
  ccState.loading(el);
  try {
    const data = await _navFetch("/newest?page=0&page_size=12");
    if (!data.items?.length) { ccState.empty(el, "Noch keine Alben", "Neue Alben erscheinen nach dem nächsten Scan."); return; }
    el.innerHTML = _navShelfRow(data.items.map(_navAlbumTile).join(""));
    _wireDetailLinks(el);
  } catch (err) { ccState.error(el, err.message, loadShelfNewest); }
}

// "Zufällig für dich": zufällige Songs -> ihre (einmaligen) Alben, damit die
// Kacheln Cover zeigen. Kein eigener Endpunkt nötig; ein fehlschlagendes Album
// wird übersprungen.
async function loadShelfRandom() {
  const el = document.getElementById("nav-shelf-random");
  if (!el) return;
  ccState.loading(el);
  try {
    const data = await _navFetch("/random?size=40");
    const ids = [];
    const seen = new Set();
    for (const s of (data.songs || [])) {
      if (s.album_id && !seen.has(s.album_id)) {
        seen.add(s.album_id);
        ids.push(s.album_id);
        if (ids.length >= 8) break;
      }
    }
    const albums = (await Promise.all(
      ids.map(id => _navFetch(`/albums/${encodeURIComponent(id)}`).catch(() => null))
    )).filter(Boolean);
    if (!albums.length) { ccState.empty(el, "Keine Vorschläge", "Es wurden keine Songs gefunden."); return; }
    el.innerHTML = _navShelfRow(albums.map(_navAlbumTile).join(""));
    _wireDetailLinks(el);
  } catch (err) { ccState.error(el, err.message, loadShelfRandom); }
}

async function loadShelfArtists() {
  const el = document.getElementById("nav-shelf-artists");
  if (!el) return;
  ccState.loading(el);
  try {
    const data = await _navFetch("/artists?page=0&page_size=12");
    if (!data.items?.length) { ccState.empty(el, "Keine Artists gefunden."); return; }
    el.innerHTML = _navShelfRow(data.items.map(_navArtistCard).join(""));
    _wireDetailLinks(el);
  } catch (err) { ccState.error(el, err.message, loadShelfArtists); }
}

// Favoriten-Regal nur, wenn es favorisierte Alben gibt (sonst bleibt es weg).
async function loadShelfFavorites() {
  const section = document.getElementById("nav-shelf-favorites-section");
  const el = document.getElementById("nav-shelf-favorites");
  if (!section || !el) return;
  try {
    const data = await _navFetch("/favorites");
    const albums = (data.albums || []).slice(0, 12);
    if (!albums.length) { section.hidden = true; return; }
    el.innerHTML = _navShelfRow(albums.map(_navAlbumTile).join(""));
    section.hidden = false;
    _wireDetailLinks(el);
  } catch (err) { section.hidden = true; }
}

function loadStart() {
  loadShelfNewest();
  loadShelfRandom();
  loadShelfArtists();
  loadShelfFavorites();
}

// =====================================================================
// Raster mit "Mehr laden" (Artists, Alben)
// =====================================================================
const _NAV_GRIDS = {
  artists: {
    listId: "nav-artists-list", footerId: "nav-artists-footer", path: "/artists",
    item: _navArtistCard, gridClass: "nav-grid nav-grid-artists",
    emptyTitle: "Keine Artists gefunden.",
  },
  albums: {
    listId: "nav-albums-list", footerId: "nav-albums-footer", path: "/albums",
    item: _navAlbumTile, gridClass: "nav-grid",
    emptyTitle: "Keine Alben gefunden.",
  },
};

async function _navLoadGrid(key, reset) {
  const cfg = _NAV_GRIDS[key];
  const st = _navState[key];
  const list = document.getElementById(cfg.listId);
  const footer = document.getElementById(cfg.footerId);
  if (!list) return;
  if (reset) {
    st.page = 0;
    st.html = "";
    ccState.loading(list);
    if (footer) footer.innerHTML = "";
  }
  try {
    const data = await _navFetch(`${cfg.path}?page=${st.page}&page_size=${st.size}`);
    if (reset && !data.items.length) { ccState.empty(list, cfg.emptyTitle); return; }
    st.html += data.items.map(cfg.item).join("");
    list.innerHTML = `<div class="${cfg.gridClass}">${st.html}</div>`;
    _wireDetailLinks(list);
    _navRenderMore(footer, data.has_next, () => { st.page += 1; _navLoadGrid(key, false); });
  } catch (err) {
    if (reset) ccState.error(list, err.message, () => _navLoadGrid(key, true));
    else ccToast("error", "Mehr laden fehlgeschlagen", err.message);
  }
}

function _navRenderMore(footer, hasNext, onMore) {
  if (!footer) return;
  if (!hasNext) { footer.innerHTML = ""; return; }
  footer.innerHTML = `<button type="button" class="btn">${ccIcon("plus", "me-1")}Mehr laden</button>`;
  const btn = footer.querySelector("button");
  if (btn) btn.addEventListener("click", onMore);
}

const loadArtists = (reset = true) => _navLoadGrid("artists", reset);
const loadAlbums  = (reset = true) => _navLoadGrid("albums", reset);

// =====================================================================
// Genres
// =====================================================================
async function loadGenres() {
  const list = document.getElementById("nav-genres-list");
  if (!list) return;
  ccState.loading(list);
  try {
    const data = await _navFetch("/genres");
    if (!data.items.length) { ccState.empty(list, "Keine Genres gefunden."); return; }
    list.innerHTML = `<div class="d-flex flex-wrap gap-2">${data.items.map(g => `
      <a href="#" class="btn btn-pill nav-genre-link" data-name="${_navEsc(g.name)}">
        ${ccIcon("tag", "icon-sm me-1")}${_navEsc(g.name)}
        ${g.song_count != null ? `<span class="badge bg-secondary-lt ms-2">${_navEsc(String(g.song_count))}</span>` : ""}
      </a>`).join("")}</div>`;
    _wireDetailLinks(list);
  } catch (err) { ccState.error(list, err.message, loadGenres); }
}

// =====================================================================
// Suche (Ergebnisse ersetzen den Reiterinhalt; leeres Feld -> zurück)
// =====================================================================
async function runSearch(ev) {
  if (ev) ev.preventDefault();
  const input = document.getElementById("nav-search-input");
  const out   = document.getElementById("nav-search-results");
  if (!input || !out) return;

  const q = (input.value || "").trim();
  if (!q) { _navLeaveSearch(); return; }

  const seq = ++_navState.searchSeq;
  _navShowTab("search");
  ccState.loading(out);
  try {
    const params = new URLSearchParams({ q, type: "all" });
    const data = await _navFetch(`/search?${params.toString()}`);
    if (seq !== _navState.searchSeq) return;   // veraltete Antwort

    const sections = [];
    if (data.artists?.length) sections.push(_navSection("Artists", "microphone", _navArtistGrid(data.artists)));
    if (data.albums?.length)  sections.push(_navSection("Alben", "disc", _navAlbumGrid(data.albums)));
    if (data.songs?.length)   sections.push(_navSection("Songs", "music", _navSongList(data.songs, true)));

    if (!sections.length) { ccState.empty(out, "Keine Ergebnisse", `Nichts gefunden für „${q}“.`); return; }
    out.innerHTML = sections.join("");
    _wireDetailLinks(out);
  } catch (err) {
    if (seq !== _navState.searchSeq) return;
    ccState.error(out, err.message, () => runSearch());
  }
}

function _navLeaveSearch() {
  _navState.searchSeq += 1;
  if (_navState.tab === "search") _navShowTab(_navState.prevTab || "start");
}

// =====================================================================
// Playlists (Anlegen/Umbenennen/Löschen über Dialoge + Toasts)
// =====================================================================
function _navPlaylistRow(p) {
  const meta = [p.owner || "", `${p.song_count} Songs`, p.duration ? _fmtDuration(p.duration) : ""]
    .filter(Boolean).join(" · ");
  return `
    <div class="list-group-item">
      <div class="row align-items-center g-2">
        <div class="col-auto"><span class="avatar bg-teal-lt">${ccIcon("playlist")}</span></div>
        <div class="col min-w-0">
          <a href="#" class="nav-playlist-link text-reset fw-medium text-truncate d-block"
             data-id="${_navEsc(p.id)}" data-name="${_navEsc(p.name)}">${_navEsc(p.name)}</a>
          <div class="text-secondary small text-truncate">${_navEsc(meta)}</div>
        </div>
        <div class="col-auto" style="white-space:nowrap;">
          <button type="button" class="btn btn-icon btn-ghost-secondary nav-playlist-rename"
                  data-id="${_navEsc(p.id)}" data-name="${_navEsc(p.name)}"
                  title="Umbenennen" aria-label="Playlist umbenennen">${ccIcon("edit")}</button>
          <button type="button" class="btn btn-icon btn-ghost-danger nav-playlist-delete"
                  data-id="${_navEsc(p.id)}" data-name="${_navEsc(p.name)}"
                  title="Löschen" aria-label="Playlist löschen">${ccIcon("trash")}</button>
        </div>
      </div>
    </div>`;
}

async function loadPlaylists(reset = true) {
  const st = _navState.playlists;
  const list = document.getElementById("nav-playlists-list");
  const footer = document.getElementById("nav-playlists-footer");
  if (!list) return;
  if (reset) {
    st.page = 0;
    st.html = "";
    ccState.loading(list);
    if (footer) footer.innerHTML = "";
  }
  try {
    const data = await _navFetch(`/playlists?page=${st.page}&page_size=${st.size}`);
    if (reset && !data.items.length) {
      ccState.empty(list, "Keine Playlists vorhanden.", "Lege mit „Neue Playlist“ die erste an.");
      return;
    }
    st.html += data.items.map(_navPlaylistRow).join("");
    list.innerHTML = `<div class="list-group">${st.html}</div>`;
    _wireDetailLinks(list);
    _navRenderMore(footer, data.has_next, () => { st.page += 1; loadPlaylists(false); });
  } catch (err) {
    if (reset) ccState.error(list, err.message, () => loadPlaylists(true));
    else ccToast("error", "Mehr laden fehlgeschlagen", err.message);
  }
}

// Ein Name pro Zeile: Zeilenumbrüche aus dem Eingabefeld zu Leerzeichen.
function _navCleanName(name) {
  return String(name || "").replace(/\s+/g, " ").trim();
}

async function createPlaylist() {
  const raw = await ccPrompt({
    title: "Neue Playlist", label: "Name", required: true, confirmLabel: "Anlegen",
  });
  const name = _navCleanName(raw);
  if (!name) return;
  try {
    const { base } = _navEndpoints();
    await ccApi("POST", `${base}/playlists`, { name });
    ccToast("ok", "Playlist angelegt", name);
    loadPlaylists(true);
  } catch (err) { ccToast("error", "Playlist nicht angelegt", err.message); }
}

async function renamePlaylistPrompt(id, current) {
  const raw = await ccPrompt({
    title: "Playlist umbenennen", label: "Neuer Name", value: current,
    required: true, confirmLabel: "Umbenennen",
  });
  const name = _navCleanName(raw);
  if (!name || name === current) return;
  try {
    const { base } = _navEndpoints();
    await ccApi("PUT", `${base}/playlists/${encodeURIComponent(id)}`, { name });
    ccToast("ok", "Playlist umbenannt", name);
    loadPlaylists(true);
  } catch (err) { ccToast("error", "Umbenennen fehlgeschlagen", err.message); }
}

async function deletePlaylistConfirm(id, name) {
  const ok = await ccConfirm({
    title: `Playlist „${name}“ löschen?`,
    text: "Diese Aktion kann nicht rückgängig gemacht werden.",
    confirmLabel: "Löschen", danger: true,
  });
  if (!ok) return;
  try {
    const { base } = _navEndpoints();
    await ccApi("DELETE", `${base}/playlists/${encodeURIComponent(id)}`);
    ccToast("ok", "Playlist gelöscht", name);
    loadPlaylists(true);
  } catch (err) { ccToast("error", "Löschen fehlgeschlagen", err.message); }
}

// Ein Listener für Umbenennen/Löschen (die Zeilen werden beim Nachladen ersetzt).
function _navOnPlaylistClick(ev) {
  const target = ev.target && ev.target.closest ? ev.target : null;
  if (!target) return;
  const ren = target.closest(".nav-playlist-rename");
  if (ren) { ev.preventDefault(); renamePlaylistPrompt(ren.dataset.id, ren.dataset.name); return; }
  const del = target.closest(".nav-playlist-delete");
  if (del) { ev.preventDefault(); deletePlaylistConfirm(del.dataset.id, del.dataset.name); }
}

// =====================================================================
// Favoriten
// =====================================================================
async function loadFavorites() {
  const list = document.getElementById("nav-favorites-list");
  if (!list) return;
  ccState.loading(list);
  try {
    const data = await _navFetch("/favorites");
    const sections = [];
    if (data.artists?.length) sections.push(_navSection("Artists", "microphone", _navArtistGrid(data.artists)));
    if (data.albums?.length)  sections.push(_navSection("Alben", "disc", _navAlbumGrid(data.albums)));
    if (data.songs?.length)   sections.push(_navSection("Songs", "music", _navSongList(data.songs, true)));
    if (!sections.length) { ccState.empty(list, "Noch keine Favoriten", "Markierte Artists, Alben und Songs erscheinen hier."); return; }
    list.innerHTML = sections.join("");
    _wireDetailLinks(list);
  } catch (err) { ccState.error(list, err.message, loadFavorites); }
}

// =====================================================================
// Detail-Links verdrahten (Modal-Stack)
// =====================================================================
function _wireDetailLinks(root) {
  if (!root) return;
  const wire = (selector, build) => {
    root.querySelectorAll(selector).forEach(a => {
      if (a.dataset.wired) return;
      a.dataset.wired = "1";
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        _navView.push(build(a));
      });
    });
  };
  wire(".nav-artist-link", a => ({ type: "artist", id: a.dataset.id, label: a.dataset.name || "Artist" }));
  wire(".nav-album-link", a => ({ type: "album", id: a.dataset.id, label: a.dataset.name || "Album" }));
  wire(".nav-song-link", a => ({ type: "song", id: a.dataset.id, label: a.dataset.name || "Song" }));
  wire(".nav-genre-link", a => ({ type: "genre", id: a.dataset.name, label: a.dataset.name }));
  wire(".nav-playlist-link", a => ({ type: "playlist", id: a.dataset.id, label: a.dataset.name }));
  root.querySelectorAll('[data-nav-action="top-songs"]').forEach(b => {
    if (b.dataset.wired) return;
    b.dataset.wired = "1";
    b.addEventListener("click", (ev) => {
      ev.preventDefault();
      _navView.push({
        type: "topSongs",
        id: b.dataset.artistId,
        artistName: b.dataset.artistName,
        label: "Top Songs",
      });
    });
  });
}

// =====================================================================
// Reiter (eigene Umschaltung; Inhalte werden beim ersten Öffnen geladen)
// =====================================================================
const _NAV_TABS = ["start", "artists", "albums", "genres", "playlists", "favorites", "search"];

function _navLoadTab(tab) {
  if (_navState.loaded[tab]) return;
  if (tab === "search") return;   // lädt über runSearch()
  _navState.loaded[tab] = true;
  if (tab === "start")     loadStart();
  if (tab === "artists")   loadArtists();
  if (tab === "albums")    loadAlbums();
  if (tab === "genres")    loadGenres();
  if (tab === "playlists") loadPlaylists();
  if (tab === "favorites") loadFavorites();
}

function _navShowTab(tab) {
  if (tab !== "search") _navState.prevTab = tab;
  _navState.tab = tab;
  document.querySelectorAll("[data-navtab]").forEach(a => {
    const on = a.dataset.navtab === tab;
    a.classList.toggle("active", on);
    a.setAttribute("aria-selected", on ? "true" : "false");
  });
  _NAV_TABS.forEach(t => {
    const pane = document.getElementById(`nav-pane-${t}`);
    if (!pane) return;
    pane.classList.toggle("active", t === tab);
    pane.classList.toggle("show", t === tab);
  });
  _navLoadTab(tab);
}

// =====================================================================
// Init
// =====================================================================
function initPage() {
  checkAuth().then((who) => {
    if (!who) return;

    loadNavidromeStatus();
    document.getElementById("navidrome-scan-btn")
      ?.addEventListener("click", triggerNavidromeScan);

    document.querySelectorAll("[data-navtab]").forEach(a => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        const input = document.getElementById("nav-search-input");
        if (input) input.value = "";
        _navState.searchSeq += 1;
        _navShowTab(a.dataset.navtab);
      });
    });
    document.querySelectorAll("[data-nav-goto]").forEach(a => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        _navShowTab(a.dataset.navGoto);
      });
    });

    const searchInput = document.getElementById("nav-search-input");
    document.getElementById("nav-search-form")?.addEventListener("submit", runSearch);
    searchInput?.addEventListener("input", () => {
      if (!(searchInput.value || "").trim() && _navState.tab === "search") _navLeaveSearch();
    });

    document.getElementById("nav-playlist-new")?.addEventListener("click", createPlaylist);
    document.getElementById("nav-playlists-list")?.addEventListener("click", _navOnPlaylistClick);
    document.getElementById("nav-shuffle-btn")?.addEventListener("click", loadShelfRandom);

    document.getElementById("nav-detail-back")?.addEventListener("click", () => _navView.back());
    document.getElementById("nav-detail-modal")?.addEventListener("hidden.bs.modal", () => {
      _navView.stack = [];
    });

    _navShowTab("start");
  });
}
initPage();
