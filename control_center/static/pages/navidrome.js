// control_center/static/pages/navidrome.js
// Navidrome-Seite: Status, Scan, Browse, Suche, Playlists, Favoriten,
// Entdecken - mit Modal-Stack-Navigation (Back-Button + Breadcrumb)
// und Cover-Art via /api/v1/navidrome/cover/{id}.

// =====================================================================
// State
// =====================================================================
const _navState = {
  artistsPage: 0,   artistsPageSize: 30,
  albumsPage: 0,    albumsPageSize: 15,
  albumsArtistId: null,
  playlistsPage: 0, playlistsPageSize: 20,
};

// =====================================================================
// Helper
// =====================================================================
function _navEndpoints() {
  const el = document.getElementById("navidrome-status-row");
  const status = el?.dataset.statusEndpoint || "/api/v1/navidrome/status";
  const scan   = el?.dataset.scanEndpoint   || "/api/v1/navidrome/scan";
  const base   = status.replace(/\/status$/, "");
  return { base, status, scan };
}

async function _navFetch(path, options = {}) {
  const { base } = _navEndpoints();
  const opts = {
    credentials: "same-origin",
    ...options,
    headers: {
      "X-Requested-With": "XMLHttpRequest",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  };
  const res = await fetch(apiUrl(base + path), opts);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : (body.detail.message || detail);
      }
    } catch (_) { /* ignore */ }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function _navEsc(s) {
  return (typeof _escapeHtml === "function")
    ? _escapeHtml(String(s ?? ""))
    : String(s ?? "");
}
function _navErr(el, err) {
  if (el) el.innerHTML = `<div class="text-danger">❌ ${_navEsc(err.message || err)}</div>`;
}
function _navEmpty(el, msg) {
  if (el) el.innerHTML = `<div class="text-muted">${_navEsc(msg)}</div>`;
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
function _coverImg(coverId, size = 300, aspect = "1") {
  if (coverId) {
    return `<img src="${_coverUrl(coverId, size)}" alt=""
                 style="width:100%;height:100%;object-fit:cover;display:block;"
                 loading="lazy" onerror="this.style.display='none'">`;
  }
  return `<div class="d-flex align-items-center justify-content-center bg-secondary-lt"
               style="width:100%;height:100%;aspect-ratio:${aspect};">
            <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-lg text-muted"
                 width="24" height="24" viewBox="0 0 24 24" stroke-width="1.5"
                 stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">
              <path stroke="none" d="M0 0h24v24H0z" fill="none"/>
              <path d="M3 3m0 3a3 3 0 0 1 3 -3h12a3 3 0 0 1 3 3v12a3 3 0 0 1 -3 3h-12a3 3 0 0 1 -3 -3z"/>
              <path d="M9 17v-8l6 4l-6 4"/>
            </svg>
          </div>`;
}

// =====================================================================
// Status
// =====================================================================
function renderNavidromeStatus(el, data) {
  const connectedEl = document.getElementById("navidrome-status");
  const statusEl    = document.getElementById("navidrome-connected-status");
  const countEl     = document.getElementById("navidrome-artist-count");

  if (data.connected) {
    connectedEl.textContent = "Online";
    statusEl.className = "status status-success";
    statusEl.textContent = "Navidrome erreichbar";
  } else {
    connectedEl.textContent = "Offline";
    statusEl.className = "status status-danger";
    statusEl.textContent = "Nicht erreichbar";
  }
  countEl.textContent = data.artist_count != null
    ? _navEsc(String(data.artist_count)) : "–";
}
function loadNavidromeStatus() {
  const { status } = _navEndpoints();
  return _loadInto("navidrome-status-row", status, renderNavidromeStatus, loadNavidromeStatus);
}

// =====================================================================
// Scan
// =====================================================================
async function triggerNavidromeScan() {
  const btn = document.getElementById("navidrome-scan-btn");
  const out = document.getElementById("navidrome-scan-output");
  if (!btn || !out) return;
  btn.disabled = true;
  out.textContent = "Scan läuft…";
  try {
    const data = await _navFetch("/scan", { method: "POST" });
    out.textContent = data.success
      ? `✅ Scan erfolgreich (rc=${data.returncode})\n${data.stdout || ""}`
      : `❌ Scan fehlgeschlagen (rc=${data.returncode})\n${data.stderr || ""}`;
    loadNavidromeStatus();
  } catch (err) {
    out.textContent = `❌ Fehler: ${err.message}`;
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
// View-Renderer
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
// Artist-Liste (Hauptseite)
// =====================================================================
async function loadArtists(page = _navState.artistsPage) {
  _navState.artistsPage = page;
  const list = document.getElementById("nav-artists-list");
  const pageEl = document.getElementById("nav-artists-page");
  if (!list) return;
  list.innerHTML = "Lädt…";

  try {
    const q = `?page=${page}&page_size=${_navState.artistsPageSize}`;
    const data = await _navFetch(`/artists${q}`);

    if (!data.items.length) {
      _navEmpty(list, "Keine Artists gefunden.");
    } else {
      const cards = data.items.map(a => {
        // Navidrome-Cover-Fallback: artist_id funktioniert als Cover-ID,
        // weil Navidrome artist.jpg im Artist-Verzeichnis automatisch ausliefert.
        const coverId = a.cover_art || a.coverArt || a.id || null;
        const initial = (a.name || "?").charAt(0).toUpperCase();
        const avatarInner = coverId
          ? _coverImg(coverId, 300)
          : `<span class="artist-initial">${_navEsc(initial)}</span>`;
        const albumCount = (a.album_count ?? 0);
        const albumLabel = albumCount === 1 ? "Album" : "Alben";
        return `
          <a href="#" class="artist-card nav-artist-link"
             data-id="${_navEsc(a.id)}" data-name="${_navEsc(a.name)}">
            <div class="artist-avatar">${avatarInner}</div>
            <div class="artist-name">${_navEsc(a.name)}</div>
            <div class="artist-meta">${albumCount} ${albumLabel}</div>
          </a>
        `;
      }).join("");
      list.innerHTML = `<div class="artist-grid">${cards}</div>`;
    }

    if (pageEl) pageEl.textContent = `Seite ${page + 1} · insgesamt ${data.total}`;
    document.getElementById("nav-artists-prev").disabled = page <= 0;
    document.getElementById("nav-artists-next").disabled = !data.has_next;
    _wireDetailLinks(list);
  } catch (err) {
    _navErr(list, err);
  }
}

// =====================================================================
// Album-Liste (Hauptseite)
// =====================================================================
async function loadAlbums(page = _navState.albumsPage) {
  _navState.albumsPage = page;
  const list = document.getElementById("nav-albums-list");
  const pageEl = document.getElementById("nav-albums-page");
  if (!list) return;
  list.innerHTML = "Lädt…";

  try {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(_navState.albumsPageSize),
    });
    if (_navState.albumsArtistId) params.set("artist_id", _navState.albumsArtistId);

    const data = await _navFetch(`/albums?${params.toString()}`);

    if (!data.items.length) {
      _navEmpty(list, "Keine Alben gefunden.");
    } else {
      list.innerHTML = `<div class="row row-cards">${data.items.map(a => `
        <div class="col-6 col-md-4 col-lg-3">
          <a href="#" class="card card-link nav-album-link"
             data-id="${_navEsc(a.id)}" data-name="${_navEsc(a.name)}">
            <div style="aspect-ratio:1;overflow:hidden;background:#1a1a1a;">
              ${_coverImg(a.cover_art, 300)}
            </div>
            <div class="card-body p-2">
              <div class="text-truncate fw-bold">${_navEsc(a.name)}</div>
              <div class="text-muted small text-truncate">${_navEsc(a.artist || "")}</div>
              <div class="text-muted small">${a.year ? _navEsc(String(a.year)) : ""}</div>
            </div>
          </a>
        </div>`).join("")}</div>`;
    }

    if (pageEl) pageEl.textContent = `Seite ${page + 1}`;
    document.getElementById("nav-albums-prev").disabled = page <= 0;
    document.getElementById("nav-albums-next").disabled = !data.has_next;
    _wireDetailLinks(list);
  } catch (err) {
    _navErr(list, err);
  }
}

// =====================================================================
// Genres
// =====================================================================
async function loadGenres() {
  const list = document.getElementById("nav-genres-list");
  if (!list) return;
  list.innerHTML = "Lädt…";
  try {
    const data = await _navFetch("/genres");
    if (!data.items.length) {
      _navEmpty(list, "Keine Genres gefunden.");
    } else {
      const rows = data.items.map(g => `
        <tr>
          <td>
            <a href="#" class="nav-genre-link" data-name="${_navEsc(g.name)}">
              🎭 ${_navEsc(g.name)}
            </a>
          </td>
          <td class="text-end text-muted">${g.song_count ?? ""}</td>
        </tr>
      `).join("");
      list.innerHTML = `
        <table class="table table-sm table-vcenter">
          <thead><tr><th>Genre</th><th class="text-end">Songs</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
      list.querySelectorAll(".nav-genre-link").forEach(a => {
        a.addEventListener("click", (ev) => {
          ev.preventDefault();
          _navView.push({ type: "genre", id: a.dataset.name, label: a.dataset.name });
        });
      });
    }
  } catch (err) {
    _navErr(list, err);
  }
}

// =====================================================================
// Suche
// =====================================================================
async function runSearch(ev) {
  if (ev) ev.preventDefault();
  const input = document.getElementById("nav-search-input");
  const type  = document.getElementById("nav-search-type");
  const out   = document.getElementById("nav-search-results");
  if (!input || !out) return;

  const q = (input.value || "").trim();
  if (!q) { out.innerHTML = ""; return; }

  out.innerHTML = "Suche läuft…";
  try {
    const params = new URLSearchParams({ q, type: type?.value || "all" });
    const data = await _navFetch(`/search?${params.toString()}`);

    const sections = [];
    if (data.artists?.length) {
      sections.push(`<h4 class="mt-3">🎤 Artists</h4>` + _renderList(
        data.artists,
        a => `<a href="#" class="nav-artist-link" data-id="${_navEsc(a.id)}" data-name="${_navEsc(a.name)}">🎤 ${_navEsc(a.name)}</a>`
      ));
    }
    if (data.albums?.length) {
      sections.push(`<h4 class="mt-3">💿 Alben</h4>` + _renderList(
        data.albums,
        a => `<a href="#" class="nav-album-link" data-id="${_navEsc(a.id)}" data-name="${_navEsc(a.name)}">💿 ${_navEsc(a.name)} <span class="text-muted">– ${_navEsc(a.artist || "")}</span></a>`
      ));
    }
    if (data.songs?.length) {
      sections.push(`<h4 class="mt-3">🎵 Songs</h4>` + _renderList(
        data.songs,
        s => `<a href="#" class="nav-song-link" data-id="${_navEsc(s.id)}" data-name="${_navEsc(s.title)}">🎵 ${_navEsc(s.title)} <span class="text-muted">– ${_navEsc(s.artist || "")}</span></a>`
      ));
    }

    if (!sections.length) { out.innerHTML = `<div class="text-muted">Keine Ergebnisse.</div>`; return; }
    out.innerHTML = sections.join("");
    _wireDetailLinks(out);
  } catch (err) {
    _navErr(out, err);
  }
}

function _renderList(items, fn) {
  return `<ul class="list-unstyled mb-0">${items.map(i => `<li class="py-1">${fn(i)}</li>`).join("")}</ul>`;
}

// =====================================================================
// Playlists (CRUD)
// =====================================================================
async function loadPlaylists(page = _navState.playlistsPage) {
  _navState.playlistsPage = page;
  const list = document.getElementById("nav-playlists-list");
  const pageEl = document.getElementById("nav-playlists-page");
  if (!list) return;
  list.innerHTML = "Lädt…";

  try {
    const q = `?page=${page}&page_size=${_navState.playlistsPageSize}`;
    const data = await _navFetch(`/playlists${q}`);

    if (!data.items.length) {
      _navEmpty(list, "Keine Playlists vorhanden. Erstelle die erste mit ➕ Neue Playlist.");
    } else {
      const rows = data.items.map(p => `
        <tr>
          <td>
            <a href="#" class="nav-playlist-link"
               data-id="${_navEsc(p.id)}" data-name="${_navEsc(p.name)}">
              📋 ${_navEsc(p.name)}
            </a>
          </td>
          <td class="text-muted d-none d-sm-table-cell">${_navEsc(p.owner || "")}</td>
          <td class="text-end text-muted">${p.song_count}</td>
          <td class="text-end" style="white-space:nowrap;">
            <button class="btn btn-sm btn-icon btn-ghost-secondary nav-playlist-rename"
                    data-id="${_navEsc(p.id)}" data-name="${_navEsc(p.name)}" title="Umbenennen">
              <svg xmlns="http://www.w3.org/2000/svg" class="icon" width="24" height="24"
                   viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none"
                   stroke-linecap="round" stroke-linejoin="round">
                <path stroke="none" d="M0 0h24v24H0z" fill="none"/>
                <path d="M7 7h-1a2 2 0 0 0 -2 2v9a2 2 0 0 0 2 2h9a2 2 0 0 0 2 -2v-1"/>
                <path d="M20.385 6.585a2.1 2.1 0 0 0 -2.97 -2.97l-8.415 8.385v3h3l8.385 -8.415z"/>
                <path d="M16 5l3 3"/>
              </svg>
            </button>
            <button class="btn btn-sm btn-icon btn-ghost-danger nav-playlist-delete"
                    data-id="${_navEsc(p.id)}" data-name="${_navEsc(p.name)}" title="Löschen">
              <svg xmlns="http://www.w3.org/2000/svg" class="icon" width="24" height="24"
                   viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none"
                   stroke-linecap="round" stroke-linejoin="round">
                <path stroke="none" d="M0 0h24v24H0z" fill="none"/>
                <path d="M4 7l16 0"/>
                <path d="M10 11l0 6"/>
                <path d="M14 11l0 6"/>
                <path d="M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2 -2l1 -12"/>
                <path d="M9 7v-3a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v3"/>
              </svg>
            </button>
          </td>
        </tr>
      `).join("");
      list.innerHTML = `
        <table class="table table-sm table-vcenter">
          <thead><tr>
            <th>Playlist</th>
            <th class="d-none d-sm-table-cell">Besitzer</th>
            <th class="text-end">Songs</th>
            <th></th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
      list.querySelectorAll(".nav-playlist-link").forEach(a => {
        a.addEventListener("click", (ev) => {
          ev.preventDefault();
          _navView.push({ type: "playlist", id: a.dataset.id, label: a.dataset.name });
        });
      });
      list.querySelectorAll(".nav-playlist-rename").forEach(b => {
        b.addEventListener("click", () => renamePlaylistPrompt(b.dataset.id, b.dataset.name));
      });
      list.querySelectorAll(".nav-playlist-delete").forEach(b => {
        b.addEventListener("click", () => deletePlaylistConfirm(b.dataset.id, b.dataset.name));
      });
    }

    if (pageEl) pageEl.textContent = `Seite ${page + 1} · insgesamt ${data.total}`;
    document.getElementById("nav-playlists-prev").disabled = page <= 0;
    document.getElementById("nav-playlists-next").disabled = !data.has_next;
  } catch (err) {
    _navErr(list, err);
  }
}

async function createPlaylist() {
  const name = prompt("Name der neuen Playlist:");
  if (name == null) return;
  const trimmed = name.trim();
  if (!trimmed) { alert("Name darf nicht leer sein."); return; }
  try {
    await _navFetch("/playlists", {
      method: "POST",
      body: JSON.stringify({ name: trimmed }),
    });
    loadPlaylists(0);
  } catch (err) { alert(`❌ Fehler: ${err.message}`); }
}

async function renamePlaylistPrompt(id, current) {
  const name = prompt(`Neuer Name für „${current}":`, current);
  if (name == null) return;
  const trimmed = name.trim();
  if (!trimmed) { alert("Name darf nicht leer sein."); return; }
  try {
    await _navFetch(`/playlists/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify({ name: trimmed }),
    });
    loadPlaylists();
  } catch (err) { alert(`❌ Fehler: ${err.message}`); }
}

async function deletePlaylistConfirm(id, name) {
  if (!confirm(`Playlist „${name}" wirklich löschen?\n\nDiese Aktion kann nicht rückgängig gemacht werden!`)) return;
  try {
    await _navFetch(`/playlists/${encodeURIComponent(id)}`, { method: "DELETE" });
    loadPlaylists();
  } catch (err) { alert(`❌ Fehler: ${err.message}`); }
}

// =====================================================================
// Favoriten
// =====================================================================
async function loadFavorites() {
  const list = document.getElementById("nav-favorites-list");
  if (!list) return;
  list.innerHTML = "Lädt…";

  try {
    const data = await _navFetch("/favorites");
    const hasAny = data.artists?.length || data.albums?.length || data.songs?.length;
    if (!hasAny) { _navEmpty(list, "Noch keine Favoriten markiert."); return; }

    const sections = [];
    if (data.artists?.length) {
      sections.push(`<h4>🎤 Artists</h4>` + _renderList(
        data.artists,
        a => `<a href="#" class="nav-artist-link" data-id="${_navEsc(a.id)}" data-name="${_navEsc(a.name)}">🎤 ${_navEsc(a.name)}</a>`
      ));
    }
    if (data.albums?.length) {
      sections.push(`<h4 class="mt-3">💿 Alben</h4>` + _renderList(
        data.albums,
        a => `<a href="#" class="nav-album-link" data-id="${_navEsc(a.id)}" data-name="${_navEsc(a.name)}">💿 ${_navEsc(a.name)} <span class="text-muted">– ${_navEsc(a.artist || "")}</span></a>`
      ));
    }
    if (data.songs?.length) {
      sections.push(`<h4 class="mt-3">🎵 Songs</h4>` + _renderList(
        data.songs,
        s => `<a href="#" class="nav-song-link" data-id="${_navEsc(s.id)}" data-name="${_navEsc(s.title)}">🎵 ${_navEsc(s.title)} <span class="text-muted">– ${_navEsc(s.artist || "")}</span></a>`
      ));
    }
    list.innerHTML = sections.join("");
    _wireDetailLinks(list);
  } catch (err) { _navErr(list, err); }
}

// =====================================================================
// Entdecken
// =====================================================================
async function loadRandom() {
  const out = document.getElementById("nav-discover-list");
  if (!out) return;
  out.innerHTML = "Lädt…";
  try {
    const data = await _navFetch("/random?size=25");
    if (!data.songs?.length) { _navEmpty(out, "Keine Songs gefunden."); return; }
    out.innerHTML = `<h4>🎲 Zufällige Songs</h4>` + _renderList(
      data.songs,
      s => `<a href="#" class="nav-song-link" data-id="${_navEsc(s.id)}" data-name="${_navEsc(s.title)}">🎵 ${_navEsc(s.title)} <span class="text-muted">– ${_navEsc(s.artist || "")}</span></a>`
    );
    _wireDetailLinks(out);
  } catch (err) { _navErr(out, err); }
}

async function loadNewest() {
  const out = document.getElementById("nav-discover-list");
  if (!out) return;
  out.innerHTML = "Lädt…";
  try {
    const data = await _navFetch("/newest?page=0&page_size=15");
    if (!data.items?.length) { _navEmpty(out, "Keine Alben gefunden."); return; }
    out.innerHTML = `<h4>🆕 Neue Alben</h4>` + _renderList(
      data.items,
      a => `<a href="#" class="nav-album-link" data-id="${_navEsc(a.id)}" data-name="${_navEsc(a.name)}">💿 ${_navEsc(a.name)} <span class="text-muted">– ${_navEsc(a.artist || "")}</span></a>`
    );
    _wireDetailLinks(out);
  } catch (err) { _navErr(out, err); }
}

// =====================================================================
// Detail-Links verdrahten (Modal-Stack)
// =====================================================================
function _wireDetailLinks(root) {
  if (!root) return;
  root.querySelectorAll(".nav-artist-link").forEach(a => {
    if (a.dataset.wired) return;
    a.dataset.wired = "1";
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      _navView.push({ type: "artist", id: a.dataset.id, label: a.dataset.name || "Artist" });
    });
  });
  root.querySelectorAll(".nav-album-link").forEach(a => {
    if (a.dataset.wired) return;
    a.dataset.wired = "1";
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      _navView.push({ type: "album", id: a.dataset.id, label: a.dataset.name || "Album" });
    });
  });
  root.querySelectorAll(".nav-song-link").forEach(a => {
    if (a.dataset.wired) return;
    a.dataset.wired = "1";
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      _navView.push({ type: "song", id: a.dataset.id, label: a.dataset.name || "Song" });
    });
  });
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
// Init
// =====================================================================
function initPage() {
  checkAuth().then((who) => {
    if (!who) return;

    loadNavidromeStatus();
    document.getElementById("navidrome-scan-btn")
      ?.addEventListener("click", triggerNavidromeScan);

    document.querySelectorAll('[data-bs-toggle="tab"][data-navtab]').forEach(a => {
      a.addEventListener("shown.bs.tab", () => {
        const t = a.dataset.navtab;
        if (t === "artists")   loadArtists();
        if (t === "albums")    loadAlbums();
        if (t === "genres")    loadGenres();
        if (t === "playlists") loadPlaylists();
        if (t === "favorites") loadFavorites();
      });
    });

    document.getElementById("nav-artists-prev")?.addEventListener("click",
      () => loadArtists(Math.max(0, _navState.artistsPage - 1)));
    document.getElementById("nav-artists-next")?.addEventListener("click",
      () => loadArtists(_navState.artistsPage + 1));
    document.getElementById("nav-albums-prev")?.addEventListener("click",
      () => loadAlbums(Math.max(0, _navState.albumsPage - 1)));
    document.getElementById("nav-albums-next")?.addEventListener("click",
      () => loadAlbums(_navState.albumsPage + 1));
    document.getElementById("nav-playlists-prev")?.addEventListener("click",
      () => loadPlaylists(Math.max(0, _navState.playlistsPage - 1)));
    document.getElementById("nav-playlists-next")?.addEventListener("click",
      () => loadPlaylists(_navState.playlistsPage + 1));

    document.getElementById("nav-search-form")?.addEventListener("submit", runSearch);
    document.getElementById("nav-playlist-new")?.addEventListener("click", createPlaylist);
    document.getElementById("nav-discover-random")?.addEventListener("click", loadRandom);
    document.getElementById("nav-discover-newest")?.addEventListener("click", loadNewest);

    document.getElementById("nav-detail-back")?.addEventListener("click", () => _navView.back());
    document.getElementById("nav-detail-modal")?.addEventListener("hidden.bs.modal", () => {
      _navView.stack = [];
    });

    loadArtists(0);
  });
}
initPage();
