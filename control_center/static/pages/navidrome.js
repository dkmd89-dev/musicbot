// control_center/static/pages/navidrome.js
// Navidrome-Seite: Kopf mit Suche/Status/Scan, Pill-Reiter, Start mit Regalen,
// Cover-/Artist-Raster mit "Mehr laden" (N1) und Detailseiten per Hash-Routing
// (N2): #/artist/ID, #/album/ID, #/song/ID, #/genre/NAME, #/playlist/ID,
// #/top/ARTIST-ID. Alle Links sind echte Links (Zurück-Taste, Neu laden und
// Link kopieren funktionieren). Cover-Art via /api/v1/navidrome/cover/{id}.

// =====================================================================
// State
// =====================================================================
const _navState = {
  tab: "start",       // aktiver Reiter ("search"/"detail" sind keine Reiter)
  prevTab: "start",   // letzter echter Reiter, Ziel beim Verlassen von Suche/Detail
  searchSeq: 0,       // verwirft veraltete Suchantworten
  detailSeq: 0,       // verwirft veraltete Detailantworten
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

// Link auf eine Detailseite. type: artist | album | song | genre | playlist | top
function _navHref(type, id) {
  return `#/${type}/${encodeURIComponent(id)}`;
}
function _navParseHash(hash) {
  const m = /^#\/(artist|album|song|genre|playlist|top)\/(.+)$/.exec(hash || "");
  if (!m) return null;
  try { return { type: m[1], id: decodeURIComponent(m[2]) }; } catch (e) { return null; }
}
function _navLink(type, id, text, cls) {
  return `<a href="${_navEsc(_navHref(type, id))}"${cls ? ` class="${cls}"` : ""}>${_navEsc(text)}</a>`;
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
// Kacheln (Alben/Artists/Songs) - gemeinsam für Regale, Raster, Suche, Detail
// =====================================================================
function _navAlbumTile(a) {
  const sub = [a.artist || "", a.year ? String(a.year) : ""].filter(Boolean).join(" · ");
  return `
    <a href="${_navEsc(_navHref("album", a.id))}" class="nav-tile nav-album-link">
      <div class="nav-cover">${_coverImg(a.cover_art, 300)}</div>
      <div class="nav-tile-title">${_navEsc(a.name)}</div>
      <div class="nav-tile-sub">${_navEsc(sub)}</div>
    </a>`;
}

// Runder Artist-Avatar mit Initial; das Bild liegt darüber (bei Ladefehler bleibt der Buchstabe).
function _navArtistAvatar(a) {
  // Navidrome-Cover-Fallback: artist_id funktioniert als Cover-ID, weil
  // Navidrome artist.jpg im Artist-Verzeichnis automatisch ausliefert.
  const coverId = a.cover_art || a.coverArt || a.id || null;
  const initial = (a.name || "?").charAt(0).toUpperCase();
  const img = coverId
    ? `<img class="nav-cover-img" src="${_coverUrl(coverId, 300)}" alt="" loading="lazy"
            onerror="this.style.display='none'">`
    : "";
  return `<div class="artist-avatar"><span class="artist-initial">${_navEsc(initial)}</span>${img}</div>`;
}

function _navArtistCard(a) {
  const meta = a.album_count != null
    ? `<div class="artist-meta">${a.album_count} ${a.album_count === 1 ? "Album" : "Alben"}</div>`
    : "";
  return `
    <a href="${_navEsc(_navHref("artist", a.id))}" class="artist-card nav-artist-link">
      ${_navArtistAvatar(a)}
      <div class="artist-name">${_navEsc(a.name)}</div>
      ${meta}
    </a>`;
}

// Songlisten, aus denen der Player spielt: Schlüssel -> {songs, ctx}. Zeilen und
// Play-Knöpfe verweisen per data-np-list/-index darauf (N4).
const _navLists = {};

// Song-Zeile (Klick = ab hier abspielen): Nummer/Icon, Titel, Untertitel, Dauer,
// "Zur Warteschlange" und Details-Link. opts: key/index (Liste im Player),
// sub (Untertitel), number (Trackzahl statt Icon).
function _navSongRow(s, opts) {
  const o = opts || {};
  const lead = o.number != null
    ? `<span class="text-secondary">${_navEsc(String(o.number))}</span>`
    : `<span class="avatar avatar-sm bg-teal-lt">${ccIcon("music")}</span>`;
  return `
    <div class="list-group-item list-group-item-action nav-song-row" role="button" tabindex="0"
         data-song-id="${_navEsc(s.id)}" data-np-list="${_navEsc(o.key || "")}" data-np-index="${o.index ?? 0}"
         data-starred="${s.starred ? 1 : 0}">
      <div class="row align-items-center g-2">
        <div class="col-auto nav-song-lead">${lead}</div>
        <div class="col min-w-0">
          <div class="text-truncate fw-medium">${_navEsc(s.title)}</div>
          ${o.sub ? `<div class="text-secondary small text-truncate">${_navEsc(o.sub)}</div>` : ""}
        </div>
        <div class="col-auto text-secondary small">${s.duration ? _fmtDuration(s.duration) : ""}</div>
        <div class="col-auto" style="white-space:nowrap;">
          <button type="button" class="btn btn-icon btn-sm btn-ghost-secondary" data-np-add
                  title="Zur Warteschlange" aria-label="Zur Warteschlange hinzufügen">${ccIcon("plus")}</button>
          <div class="dropdown d-inline-block">
            <button type="button" class="btn btn-icon btn-sm btn-ghost-secondary" data-bs-toggle="dropdown"
                    aria-expanded="false" title="Weitere Aktionen" aria-label="Weitere Aktionen">${ccIcon("dots")}</button>
            <div class="dropdown-menu dropdown-menu-end">
              <button type="button" class="dropdown-item" data-np-menu="next">Als Nächstes</button>
              <button type="button" class="dropdown-item" data-np-menu="fav">${_navFavLabel(s.starred)}</button>
              <button type="button" class="dropdown-item" data-np-menu="playlist">Zur Playlist hinzufügen…</button>
            </div>
          </div>
          <a href="${_navEsc(_navHref("song", s.id))}" class="btn btn-icon btn-sm btn-ghost-secondary nav-song-link"
             title="Details" aria-label="Song-Details">${ccIcon("info-circle")}</a>
        </div>
      </div>
    </div>`;
}
function _navSongSub(s) {
  return [s.artist || "", s.album || ""].filter(Boolean).join(" · ");
}

function _navFavLabel(starred) {
  return starred ? "Aus Favoriten entfernen" : "Zu Favoriten hinzufügen";
}
// Favorit-Knopf (Stern) für Song-, Album- und Artist-Seiten (N5).
function _navFavButton(kind, id, starred) {
  return `<button type="button" class="btn btn-icon ${starred ? "nav-fav-on" : ""}" data-fav-kind="${kind}"
    data-fav-id="${_navEsc(id)}" data-fav-on="${starred ? 1 : 0}" aria-pressed="${starred ? "true" : "false"}"
    title="${_navFavLabel(starred)}" aria-label="${_navFavLabel(starred)}">${ccIcon(starred ? "star-filled" : "star")}</button>`;
}

// Abspielen / Zufällig / Als Nächstes / Zur Playlist für die Liste `key` (Detailseiten).
// opts.shuffle=false blendet "Zufällig" aus, opts.fav ist ein optionaler Favorit-Knopf.
function _navPlayButtons(key, opts) {
  const withShuffle = !(opts && opts.shuffle === false);
  return `<div class="d-flex flex-wrap gap-2 mb-3">
    <button type="button" class="btn btn-primary" data-np-play="all" data-np-list="${_navEsc(key)}">
      ${ccIcon("player-play", "me-1")}Abspielen</button>
    ${withShuffle ? `<button type="button" class="btn" data-np-play="shuffle" data-np-list="${_navEsc(key)}">
      ${ccIcon("shuffle", "me-1")}Zufällig</button>` : ""}
    <button type="button" class="btn" data-np-play="next" data-np-list="${_navEsc(key)}">
      ${ccIcon("playlist", "me-1")}Als Nächstes</button>
    <button type="button" class="btn" data-np-play="playlist" data-np-list="${_navEsc(key)}">
      ${ccIcon("plus", "me-1")}Zur Playlist</button>
    ${(opts && opts.fav) || ""}
  </div>`;
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
// opts: key (registriert die Liste für den Player), ctx ({cover_art}), numbered, noSub.
function _navSongList(items, opts) {
  const o = opts || {};
  if (o.key) _navLists[o.key] = { songs: items, ctx: o.ctx || null };
  return `<div class="list-group list-group-flush">${items.map((s, i) => _navSongRow(s, {
    key: o.key, index: i,
    sub: o.noSub ? "" : _navSongSub(s),
    number: o.numbered ? (s.track ?? (i + 1)) : null,
  })).join("")}</div>`;
}
function _navShelfRow(html) {
  return `<div class="nav-shelf-row">${html}</div>`;
}

// =====================================================================
// Detailseiten (N2): jede Funktion liefert das HTML der Seite
// =====================================================================
async function _renderArtistView(id) {
  const data = await _navFetch(`/artists/${encodeURIComponent(id)}`);
  const albumCount = data.album_count ?? (data.albums?.length || 0);
  const albums = data.albums?.length
    ? _navAlbumGrid(data.albums)
    : `<div class="text-secondary">Keine Alben gefunden.</div>`;
  return `
    <div class="d-flex align-items-center gap-3 mb-4 flex-wrap">
      ${_navArtistAvatar(data)}
      <div class="min-w-0 flex-fill">
        <div class="page-pretitle">Artist</div>
        <h2 class="mb-0 text-truncate">${_navEsc(data.name)}</h2>
        <div class="text-secondary">${albumCount} ${albumCount === 1 ? "Album" : "Alben"}</div>
      </div>
      <a class="btn" href="${_navEsc(_navHref("top", data.id))}">${ccIcon("flame", "me-1")}Top Songs</a>
      ${_navFavButton("artist", data.id, data.starred)}
    </div>
    ${_navSection("Alben", "disc", albums)}`;
}

async function _renderAlbumView(id) {
  const data = await _navFetch(`/albums/${encodeURIComponent(id)}`);
  const artist = data.artist_id
    ? _navLink("artist", data.artist_id, data.artist || "")
    : _navEsc(data.artist || "");
  const meta = [];
  if (data.year) meta.push(_navEsc(String(data.year)));
  if (data.song_count) meta.push(`${data.song_count} Songs`);
  if (data.duration) meta.push(_fmtDuration(data.duration));
  const hasSongs = !!data.songs?.length;
  const songs = hasSongs
    ? `<div class="card">${_navSongList(data.songs, {
        key: "detail", ctx: { cover_art: data.cover_art }, numbered: true, noSub: true })}</div>`
    : `<div class="text-secondary">Keine Songs.</div>`;
  return `
    <div class="row g-4 mb-4">
      <div class="col-12 col-sm-5 col-md-4 col-lg-3">
        <div class="nav-cover">${_coverImg(data.cover_art, 500)}</div>
      </div>
      <div class="col d-flex flex-column justify-content-end">
        <div class="page-pretitle">Album</div>
        <h2 class="mb-1">${_navEsc(data.name)}</h2>
        <div class="text-secondary mb-3">${artist}${meta.length ? " · " + meta.join(" · ") : ""}</div>
        ${hasSongs ? _navPlayButtons("detail", { fav: _navFavButton("album", data.id, data.starred) })
                   : `<div class="mb-3">${_navFavButton("album", data.id, data.starred)}</div>`}
      </div>
    </div>
    ${songs}`;
}

async function _renderSongView(id) {
  const data = await _navFetch(`/songs/${encodeURIComponent(id)}`);
  const genres = (data.genres || []).join(", ") || data.genre || "–";
  const artist = data.artist_id ? _navLink("artist", data.artist_id, data.artist || "") : _navEsc(data.artist || "–");
  const album = data.album_id ? _navLink("album", data.album_id, data.album || "") : _navEsc(data.album || "–");
  _navLists.detail = { songs: [data], ctx: { cover_art: data.cover_art } };
  return `
    <div class="row g-4 mb-3">
      <div class="col-12 col-sm-4 col-md-3 col-lg-2">
        <div class="nav-cover">${_coverImg(data.cover_art, 300)}</div>
      </div>
      <div class="col d-flex flex-column justify-content-end min-w-0">
        <div class="page-pretitle">Song</div>
        <h2 class="mb-1">${_navEsc(data.title)}</h2>
        <div class="text-secondary">${artist}</div>
        <div class="text-secondary small mb-3">${album}</div>
        ${_navPlayButtons("detail", { shuffle: false, fav: _navFavButton("song", data.id, data.starred) })}
      </div>
    </div>
    <div class="card"><div class="card-body"><div class="datagrid">
      <div class="datagrid-item"><div class="datagrid-title">Dauer</div><div class="datagrid-content">${data.duration ? _fmtDuration(data.duration) : "–"}</div></div>
      <div class="datagrid-item"><div class="datagrid-title">Genre</div><div class="datagrid-content">${_navEsc(genres)}</div></div>
      <div class="datagrid-item"><div class="datagrid-title">Jahr</div><div class="datagrid-content">${_navEsc(String(data.year ?? "–"))}</div></div>
      <div class="datagrid-item"><div class="datagrid-title">Play-Count</div><div class="datagrid-content">${_navEsc(String(data.play_count ?? "–"))}</div></div>
    </div></div></div>`;
}

async function _renderGenreView(name) {
  const data = await _navFetch(`/genres/${encodeURIComponent(name)}`);
  const songs = data.songs?.length
    ? `<div class="card">${_navSongList(data.songs, { key: "detail" })}</div>`
    : `<div class="text-secondary">Keine Songs.</div>`;
  return `
    <div class="mb-3">
      <div class="page-pretitle">Genre</div>
      <h2 class="mb-0">${ccIcon("tag", "me-2 text-teal")}${_navEsc(name)}</h2>
    </div>
    ${data.songs?.length ? _navPlayButtons("detail") : ""}
    ${songs}`;
}

async function _renderPlaylistView(id) {
  const data = await _navFetch(`/playlists/${encodeURIComponent(id)}`);
  const meta = [data.owner || "", `${data.song_count} Songs`, data.duration ? _fmtDuration(data.duration) : ""]
    .filter(Boolean).join(" · ");
  const songs = data.songs?.length
    ? `<div class="card">${_navSongList(data.songs, { key: "detail" })}</div>`
    : `<div class="text-secondary">Diese Playlist ist leer.</div>`;
  return `
    <div class="d-flex align-items-center gap-3 mb-4 flex-wrap">
      <span class="avatar avatar-lg bg-teal-lt">${ccIcon("playlist", "icon-lg")}</span>
      <div class="min-w-0 flex-fill">
        <div class="page-pretitle">Playlist</div>
        <h2 class="mb-0 text-truncate">${_navEsc(data.name)}</h2>
        <div class="text-secondary">${_navEsc(meta)}</div>
      </div>
      <div class="d-flex gap-2">
        <button type="button" class="btn nav-playlist-rename" data-id="${_navEsc(data.id)}" data-name="${_navEsc(data.name)}">
          ${ccIcon("edit", "me-1")}Umbenennen</button>
        <button type="button" class="btn btn-outline-danger nav-playlist-delete" data-id="${_navEsc(data.id)}" data-name="${_navEsc(data.name)}">
          ${ccIcon("trash", "me-1")}Löschen</button>
      </div>
    </div>
    ${data.songs?.length ? _navPlayButtons("detail") : ""}
    ${songs}`;
}

async function _renderTopSongsView(artistId) {
  const data = await _navFetch(`/artists/${encodeURIComponent(artistId)}/top?count=25`);
  const name = data.artist_name || "";
  const songs = data.songs?.length
    ? `<div class="card">${_navSongList(data.songs, { key: "detail", numbered: true })}</div>`
    : `<div class="text-secondary">Keine Songs.</div>`;
  return `
    <div class="mb-3">
      <div class="page-pretitle">Top Songs</div>
      <h2 class="mb-0">${ccIcon("flame", "me-2 text-teal")}${_navLink("artist", data.artist_id || artistId, name)}</h2>
    </div>
    ${data.songs?.length ? _navPlayButtons("detail") : ""}
    ${songs}`;
}

const _NAV_DETAIL = {
  artist: _renderArtistView,
  album: _renderAlbumView,
  song: _renderSongView,
  genre: _renderGenreView,
  playlist: _renderPlaylistView,
  top: _renderTopSongsView,
};

// Zeigt die Detailseite zum aktuellen Hash (kein Hash -> zurück zum Reiter).
async function _navRoute() {
  const route = _navParseHash(window.location.hash);
  if (!route) {
    _navState.detailSeq += 1;
    if (_navState.tab === "detail") _navShowTab(_navState.prevTab || "start");
    return;
  }
  const seq = ++_navState.detailSeq;
  const out = document.getElementById("nav-detail-content");
  _navShowTab("detail");
  if (typeof window.scrollTo === "function") window.scrollTo(0, 0);
  ccState.loading(out);
  try {
    const html = await _NAV_DETAIL[route.type](route.id);
    if (seq !== _navState.detailSeq) return;   // veraltete Antwort
    out.innerHTML = html;
    _navDecoratePlayer();
  } catch (err) {
    if (seq !== _navState.detailSeq) return;
    if (err && err.status === 404) ccState.empty(out, "Nicht gefunden", "Dieser Eintrag existiert nicht (mehr).");
    else ccState.error(out, err.message, _navRoute);
  }
}

// Player (navidrome_player.js) - fehlt er (z. B. in Tests), bleibt die Seite benutzbar.
function _navPlayer() {
  return typeof NavPlayer !== "undefined" ? NavPlayer : null;
}
function _navDecoratePlayer() {
  const player = _navPlayer();
  if (player) player.decorate();
}

// Klicks in Songlisten und auf die Play-Knöpfe der Detailseiten.
function _navPlaySongsFrom(list, index) {
  const player = _navPlayer();
  if (player && list && list.songs[index]) player.playList(list.songs, index, list.ctx);
}
function _navOnPlayClick(ev) {
  const player = _navPlayer();
  const t = ev.target && ev.target.closest ? ev.target : null;
  if (!t) return;
  const playBtn = t.closest("[data-np-play]");
  if (playBtn) {
    ev.preventDefault?.();
    const list = _navLists[playBtn.dataset.npList];
    if (!list || !list.songs.length) return;
    const kind = playBtn.dataset.npPlay;
    if (kind === "playlist") _navAddToPlaylist(list.songs);
    else if (!player) return;
    else if (kind === "all") player.playList(list.songs, 0, list.ctx);
    else if (kind === "shuffle") player.playList(list.songs, 0, list.ctx, { shuffle: true });
    else if (kind === "next") player.addNext(list.songs, list.ctx);
    return;
  }
  const row = t.closest(".nav-song-row");
  if (!row) return;
  const list = _navLists[row.dataset.npList];
  const index = Number(row.dataset.npIndex);
  const song = list && list.songs[index];
  const menu = t.closest("[data-np-menu]");
  if (menu) {                                   // "⋯"-Menü der Zeile (N5)
    ev.preventDefault?.();
    if (!song) return;
    const kind = menu.dataset.npMenu;
    if (kind === "next" && player) player.addNext([song], list.ctx);
    else if (kind === "fav") _navToggleSongFavorite(song, row, menu);
    else if (kind === "playlist") _navAddToPlaylist([song]);
    return;
  }
  if (t.closest("[data-np-add]")) {
    ev.preventDefault?.();
    if (song && player) player.addEnd([song], list.ctx);
    return;
  }
  if (t.closest("[data-bs-toggle='dropdown']")) return;   // Menü öffnen, nicht abspielen
  if (t.closest("a")) return;                              // Details-Link: normal navigieren
  _navPlaySongsFrom(list, index);
}
// Enter/Leertaste auf einer fokussierten Zeile = abspielen (Zeilen sind role="button").
function _navOnRowKey(ev) {
  if (ev.key !== "Enter" && ev.key !== " ") return;
  const t = ev.target;
  if (!t || !t.classList || !t.classList.contains("nav-song-row")) return;
  ev.preventDefault?.();
  _navPlaySongsFrom(_navLists[t.dataset.npList], Number(t.dataset.npIndex));
}

// ---- Favoriten setzen/entfernen (N5) ---------------------------------------
async function _navSetFavorite(kind, id, on) {
  try {
    const { base } = _navEndpoints();
    await ccApi(on ? "PUT" : "DELETE", `${base}/favorites/${kind}/${encodeURIComponent(id)}`);
  } catch (err) {
    ccToast("error", "Favorit nicht geändert", err.message);
    return false;
  }
  ccToast("ok", on ? "Zu Favoriten hinzugefügt" : "Aus Favoriten entfernt");
  if (kind === "song") _navPlayer()?.setStarred(id, on);
  if (_navState.tab === "favorites") {          // Liste sofort aktualisieren
    _navState.loaded.favorites = true;
    loadFavorites();
  } else {
    _navState.loaded.favorites = false;
  }
  if (_navState.loaded.start) loadShelfFavorites();
  return true;
}

async function _navToggleSongFavorite(song, row, menuItem) {
  const on = !song.starred;
  if (!(await _navSetFavorite("song", song.id, on))) return;
  song.starred = on;
  row.dataset.starred = on ? "1" : "0";
  menuItem.textContent = _navFavLabel(on);
}

// Sterne auf Song-/Album-/Artist-Seiten.
async function _navOnFavClick(ev) {
  const t = ev.target && ev.target.closest ? ev.target : null;
  const btn = t && t.closest("[data-fav-kind]");
  if (!btn) return;
  ev.preventDefault?.();
  const on = btn.dataset.favOn !== "1";
  if (!(await _navSetFavorite(btn.dataset.favKind, btn.dataset.favId, on))) return;
  btn.dataset.favOn = on ? "1" : "0";
  btn.classList.toggle("nav-fav-on", on);
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  btn.title = _navFavLabel(on);
  btn.innerHTML = ccIcon(on ? "star-filled" : "star");
}

// ---- Zur Playlist hinzufügen (N5) --------------------------------------------
// Liefert {id, name}, {create: true} oder null (abgebrochen).
async function _navChoosePlaylist() {
  let playlists;
  try {
    playlists = (await _navFetch("/playlists?page=0&page_size=100")).items || [];
  } catch (err) {
    ccToast("error", "Playlists nicht geladen", err.message);
    return null;
  }
  const Modal = window.tabler && window.tabler.Modal;
  const el = document.getElementById("nav-playlist-picker");
  if (!Modal || !el) {                           // ohne Tabler-JS: Nummernabfrage
    const lines = playlists.map((p, i) => `${i + 1}: ${p.name}`).join("\n");
    const answer = await ccPrompt({
      title: "Zur Playlist hinzufügen", text: `Nummer wählen (0 = neue Playlist):\n${lines}`,
      label: "Nummer", required: true, confirmLabel: "Weiter",
    });
    if (answer === null) return null;
    const n = parseInt(answer, 10);
    return n === 0 ? { create: true } : (playlists[n - 1] || null);
  }
  const list = document.getElementById("nav-playlist-picker-list");
  const newBtn = document.getElementById("nav-playlist-picker-new");
  list.innerHTML = playlists.length
    ? `<div class="list-group list-group-flush">${playlists.map(p => `
        <button type="button" class="list-group-item list-group-item-action d-flex align-items-center gap-2"
                data-pl-id="${_navEsc(p.id)}" data-pl-name="${_navEsc(p.name)}">
          ${ccIcon("playlist", "text-teal")}<span class="text-truncate flex-fill">${_navEsc(p.name)}</span>
          <span class="badge bg-secondary-lt">${_navEsc(String(p.song_count))}</span>
        </button>`).join("")}</div>`
    : `<div class="p-3 text-secondary">Noch keine Playlists - lege unten eine neue an.</div>`;
  return new Promise((resolve) => {
    let result = null;
    const modal = Modal.getOrCreateInstance(el);
    const onPick = (ev) => {
      const b = ev.target && ev.target.closest ? ev.target.closest("[data-pl-id]") : null;
      if (b) { result = { id: b.dataset.plId, name: b.dataset.plName }; modal.hide(); }
    };
    const onNew = () => { result = { create: true }; modal.hide(); };
    const onHidden = () => {
      list.removeEventListener("click", onPick);
      newBtn?.removeEventListener("click", onNew);
      el.removeEventListener("hidden.bs.modal", onHidden);
      resolve(result);
    };
    list.addEventListener("click", onPick);
    newBtn?.addEventListener("click", onNew);
    el.addEventListener("hidden.bs.modal", onHidden);
    modal.show();
  });
}

const _NAV_PLAYLIST_ADD_MAX = 500;   // wie das Backend

async function _navAddToPlaylist(songs) {
  const all = (songs || []).map(s => s.id).filter(Boolean);
  const ids = all.slice(0, _NAV_PLAYLIST_ADD_MAX);
  if (!ids.length) return;
  const choice = await _navChoosePlaylist();
  if (!choice) return;
  const { base } = _navEndpoints();
  let target = choice;
  if (choice.create) {
    const name = _navCleanName(await ccPrompt({
      title: "Neue Playlist", label: "Name", required: true, confirmLabel: "Anlegen",
    }));
    if (!name) return;
    try {
      const created = await ccApi("POST", `${base}/playlists`, { name });
      target = { id: created.playlist_id, name: created.name || name };
    } catch (err) { ccToast("error", "Playlist nicht angelegt", err.message); return; }
    if (!target.id) { ccToast("error", "Playlist nicht angelegt", "Navidrome lieferte keine Playlist-ID."); return; }
  }
  try {
    await ccApi("POST", `${base}/playlists/${encodeURIComponent(target.id)}/songs`, { song_ids: ids });
  } catch (err) { ccToast("error", "Nicht zur Playlist hinzugefügt", err.message); return; }
  _navState.loaded.playlists = false;            // Liste zeigt beim nächsten Öffnen die neue Anzahl
  ccToast("ok", `${ids.length} Titel zu „${target.name}“ hinzugefügt`,
    all.length > ids.length ? `Nur die ersten ${ids.length} von ${all.length} Titeln.` : "");
}

// Hash entfernen, ohne die Seite neu zu laden (feuert kein hashchange).
function _navClearHash() {
  if (window.location.hash && window.history && typeof window.history.pushState === "function") {
    window.history.pushState(null, "", window.location.pathname + window.location.search);
  }
}

// "Zurück" in der Seite: zurück zur Übersicht des zuletzt genutzten Reiters.
function _navBackToOverview() {
  _navClearHash();
  _navShowTab(_navState.prevTab || "start");
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
      <a href="${_navEsc(_navHref("genre", g.name))}" class="btn btn-pill nav-genre-link">
        ${ccIcon("tag", "icon-sm me-1")}${_navEsc(g.name)}
        ${g.song_count != null ? `<span class="badge bg-secondary-lt ms-2">${_navEsc(String(g.song_count))}</span>` : ""}
      </a>`).join("")}</div>`;
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
  _navClearHash();
  _navShowTab("search");
  ccState.loading(out);
  try {
    const params = new URLSearchParams({ q, type: "all" });
    const data = await _navFetch(`/search?${params.toString()}`);
    if (seq !== _navState.searchSeq) return;   // veraltete Antwort

    const sections = [];
    if (data.artists?.length) sections.push(_navSection("Artists", "microphone", _navArtistGrid(data.artists)));
    if (data.albums?.length)  sections.push(_navSection("Alben", "disc", _navAlbumGrid(data.albums)));
    if (data.songs?.length)   sections.push(_navSection("Songs", "music", `<div class="card">${_navSongList(data.songs, { key: "search" })}</div>`));

    if (!sections.length) { ccState.empty(out, "Keine Ergebnisse", `Nichts gefunden für „${q}“.`); return; }
    out.innerHTML = sections.join("");
    _navDecoratePlayer();
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
          <a href="${_navEsc(_navHref("playlist", p.id))}" class="nav-playlist-link text-reset fw-medium text-truncate d-block">${_navEsc(p.name)}</a>
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

// Nach Änderung einer Playlist: Liste neu laden; auf der Detailseite die Seite
// selbst (Umbenennen) bzw. zurück zur Playlist-Liste (Löschen).
function _navAfterPlaylistChange(kind) {
  const onDetail = _navState.tab === "detail";
  if (onDetail && kind === "rename") {
    _navState.loaded.playlists = false;   // Liste zeigt beim nächsten Öffnen den neuen Namen
    _navRoute();
    return;
  }
  if (onDetail && kind === "delete") {
    _navState.loaded.playlists = true;    // wird unten genau einmal geladen
    _navState.prevTab = "playlists";
    _navBackToOverview();
  }
  loadPlaylists(true);
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
    _navAfterPlaylistChange("rename");
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
    _navAfterPlaylistChange("delete");
  } catch (err) { ccToast("error", "Löschen fehlgeschlagen", err.message); }
}

// Ein Listener für Umbenennen/Löschen (Playlist-Liste und Detailseite; die
// Zeilen werden beim Nachladen ersetzt).
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
    if (data.songs?.length)   sections.push(_navSection("Songs", "music", `<div class="card">${_navSongList(data.songs, { key: "favorites" })}</div>`));
    if (!sections.length) { ccState.empty(list, "Noch keine Favoriten", "Markierte Artists, Alben und Songs erscheinen hier."); return; }
    list.innerHTML = sections.join("");
    _navDecoratePlayer();
  } catch (err) { ccState.error(list, err.message, loadFavorites); }
}

// =====================================================================
// Reiter (eigene Umschaltung; Inhalte werden beim ersten Öffnen geladen)
// =====================================================================
const _NAV_TABS = ["start", "artists", "albums", "genres", "playlists", "favorites", "search", "detail"];
const _NAV_OVERLAYS = ["search", "detail"];   // Panes ohne eigenen Reiter

function _navLoadTab(tab) {
  if (_navState.loaded[tab]) return;
  if (_NAV_OVERLAYS.includes(tab)) return;   // laden über runSearch()/_navRoute()
  _navState.loaded[tab] = true;
  if (tab === "start")     loadStart();
  if (tab === "artists")   loadArtists();
  if (tab === "albums")    loadAlbums();
  if (tab === "genres")    loadGenres();
  if (tab === "playlists") loadPlaylists();
  if (tab === "favorites") loadFavorites();
}

function _navShowTab(tab) {
  if (!_NAV_OVERLAYS.includes(tab)) _navState.prevTab = tab;
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
        _navState.detailSeq += 1;
        _navClearHash();
        _navShowTab(a.dataset.navtab);
      });
    });
    document.querySelectorAll("[data-nav-goto]").forEach(a => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        _navClearHash();
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
    document.getElementById("nav-detail-content")?.addEventListener("click", _navOnPlaylistClick);
    document.getElementById("nav-detail-content")?.addEventListener("click", _navOnFavClick);
    for (const id of ["nav-detail-content", "nav-search-results", "nav-favorites-list"]) {
      document.getElementById(id)?.addEventListener("click", _navOnPlayClick);
      document.getElementById(id)?.addEventListener("keydown", _navOnRowKey);
    }
    _navPlayer()?.init();
    document.getElementById("nav-shuffle-btn")?.addEventListener("click", loadShelfRandom);
    document.getElementById("nav-detail-back")?.addEventListener("click", _navBackToOverview);

    window.addEventListener("hashchange", _navRoute);
    if (_navParseHash(window.location.hash)) _navRoute();
    else _navShowTab("start");
  });
}
initPage();
