// control_center/static/pages/navidrome_player.js
// Player der Navidrome-Seite (CC-UI N4). Läuft nur auf /navidrome: spielt über
// GET /api/v1/navidrome/stream/{song_id} (N3) - der Browser kennt nur sein
// Session-Cookie, keine Navidrome-Zugangsdaten. Zustand (Warteschlange, Position,
// Shuffle/Repeat, Lautstärke) bleibt per localStorage über Neuladen erhalten;
// nach dem Neuladen startet nichts von allein.
// Muss VOR navidrome.js geladen werden (navidrome.js ruft NavPlayer auf).

const _NP_BASE = "/api/v1/navidrome";
const _NP_STORAGE_KEY = "cc-nav-player-v1";
const _NP_MAX_QUEUE = 500;
const _NP_SAVE_INTERVAL_S = 5;
const _NP_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

function _npFmt(sec) {
  if (!isFinite(sec) || sec < 0) return "0:00";
  const s = Math.floor(sec);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function _npEsc(s) { return _escapeHtml(String(s ?? "")); }
function _npStreamUrl(id) { return apiUrl(`${_NP_BASE}/stream/${encodeURIComponent(id)}`); }
function _npCoverUrl(id, size) {
  return id ? apiUrl(`${_NP_BASE}/cover/${encodeURIComponent(id)}?size=${size}`) : "";
}
function _npCover(id, size, cls) {
  const fallback = `<span class="nav-cover-fallback">${ccIcon("disc")}</span>`;
  const img = id
    ? `<img class="nav-cover-img" src="${_npCoverUrl(id, size)}" alt="" onerror="this.style.display='none'">`
    : "";
  return `<span class="nav-np-cover-box ${cls || ""}">${fallback}${img}</span>`;
}
function _npBtn(act, icon, label, extra) {
  return `<button type="button" class="btn btn-icon btn-ghost-secondary nav-np-btn ${extra || ""}"
    data-np-act="${act}" title="${label}" aria-label="${label}">${ccIcon(icon)}</button>`;
}

const NavPlayer = {
  queue: [],          // Reihenfolge, in der gespielt wird (das zeigt die Warteschlange)
  original: [],       // ursprüngliche Reihenfolge (zum Zurückschalten von Shuffle)
  index: -1,
  shuffle: false,
  repeat: "off",      // off | all | one
  volume: 0.8,
  playing: false,
  resumeAt: 0,        // Position (s), die beim ersten Abspielen nach dem Neuladen gesetzt wird
  _uid: 0,
  _audio: null,
  _srcUid: null,      // uid des Titels, dessen Stream gerade im Audio-Element steht
  _failures: 0,       // aufeinanderfolgende Fehler (Abbruch, wenn alle Titel scheitern)
  _lastSave: 0,
  _seeking: false,

  // ---- Zugriff -------------------------------------------------------
  current() { return this.index >= 0 ? (this.queue[this.index] || null) : null; },

  // ---- Init ----------------------------------------------------------
  init() {
    if (this._audio || typeof Audio === "undefined") return;
    const a = new Audio();
    a.preload = "metadata";
    this._audio = a;
    this._restore();
    a.volume = this.volume;
    a.addEventListener("timeupdate", () => this._onTimeUpdate());
    a.addEventListener("loadedmetadata", () => this._onLoadedMetadata());
    a.addEventListener("ended", () => { this._failures = 0; this.next(true); });
    a.addEventListener("play", () => { this.playing = true; this._render(); });
    a.addEventListener("pause", () => { this.playing = false; this._render(); this._save(); });
    a.addEventListener("error", () => this._onError());

    for (const id of ["nav-player-bar", "nav-fullplayer-body", "nav-queue-body"]) {
      const el = document.getElementById(id);
      if (!el) continue;
      el.addEventListener("click", (ev) => this._onClick(ev));
      el.addEventListener("input", (ev) => this._onInput(ev));
      el.addEventListener("pointerdown", () => { this._seeking = true; });
      el.addEventListener("pointerup", () => { this._seeking = false; });
    }
    document.getElementById("nav-queue-clear")?.addEventListener("click", () => this.clear());
    this._bindMediaSession();
    this._bindMetadata();
    this._render();
  },

  // ---- Wiedergabe-Steuerung -----------------------------------------
  _makeItem(s, ctx) {
    return {
      uid: ++this._uid,
      id: String(s.id),
      title: s.title || "",
      artist: s.artist || "",
      artist_id: s.artist_id || "",
      album: s.album || "",
      album_id: s.album_id || "",
      duration: s.duration || 0,
      // Album-Cover, sonst Album-ID (Navidrome löst rohe IDs auf), sonst Song-ID
      cover: (ctx && ctx.cover_art) || s.cover_art || s.album_id || s.id,
    };
  },

  _shuffleQueue() {
    const cur = this.current();
    const rest = this.queue.filter((it) => it !== cur);
    for (let i = rest.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [rest[i], rest[j]] = [rest[j], rest[i]];
    }
    this.queue = cur ? [cur, ...rest] : rest;
    this.index = cur ? 0 : -1;
  },

  // Neue Warteschlange aus einer Songliste; startet bei `start` (bei Shuffle: zufällig).
  playList(songs, start, ctx, opts) {
    const items = (songs || []).filter((s) => s && _NP_ID_RE.test(String(s.id))).slice(0, _NP_MAX_QUEUE)
      .map((s) => this._makeItem(s, ctx));
    if (!items.length) return;
    const wantShuffle = !!(opts && opts.shuffle);
    this.original = items.slice();
    this.queue = items.slice();
    this.index = wantShuffle ? Math.floor(Math.random() * items.length)
      : Math.min(Math.max(start || 0, 0), items.length - 1);
    if (wantShuffle) this.shuffle = true;
    if (this.shuffle) this._shuffleQueue();
    this._load(this.index, true);
  },

  _addItems(songs, ctx, afterCurrent) {
    const items = (songs || []).filter((s) => s && _NP_ID_RE.test(String(s.id)))
      .map((s) => this._makeItem(s, ctx));
    if (!items.length) return 0;
    if (!this.queue.length) { this.playList(songs, 0, ctx); return items.length; }
    items.length = Math.min(items.length, Math.max(0, _NP_MAX_QUEUE - this.queue.length));
    if (!items.length) return 0;
    const cur = this.current();
    if (afterCurrent) {
      this.queue.splice(this.index + 1, 0, ...items);
      const origPos = cur ? this.original.findIndex((it) => it.uid === cur.uid) : -1;
      this.original.splice(origPos + 1, 0, ...items);
    } else {
      this.queue.push(...items);
      this.original.push(...items);
    }
    this._render();
    this._save();
    return items.length;
  },
  addNext(songs, ctx) {
    const n = this._addItems(songs, ctx, true);
    if (n) ccToast("ok", "Als Nächstes eingereiht");
  },
  addEnd(songs, ctx) {
    const n = this._addItems(songs, ctx, false);
    if (n) ccToast("ok", "Zur Warteschlange hinzugefügt");
  },

  // Lädt den Titel an Position i; autoplay=false lässt den Player angehalten.
  _load(i, autoplay) {
    if (i < 0 || i >= this.queue.length) return;
    this.index = i;
    this.resumeAt = 0;
    this._srcUid = null;
    this._ensureSrc();
    this._render();
    this._bindMetadata();
    this._save();
    if (autoplay) this._play();
  },

  _ensureSrc() {
    const cur = this.current();
    if (!cur || !this._audio || this._srcUid === cur.uid) return;
    this._audio.src = _npStreamUrl(cur.id);
    this._srcUid = cur.uid;
  },

  _play() {
    if (!this._audio || !this.current()) return;
    this._ensureSrc();
    const p = this._audio.play();
    if (p && typeof p.catch === "function") {
      p.catch((err) => {
        // Abbruch durch schnelles Weiterschalten ist normal; alles andere melden.
        if (err && err.name !== "AbortError") this._onError();
      });
    }
  },

  toggle() {
    if (!this._audio || !this.current()) return;
    if (this._audio.paused) this._play(); else this._audio.pause();
  },

  next(fromEnded) {
    if (!this.queue.length) return;
    if (fromEnded && this.repeat === "one") {
      this._audio.currentTime = 0;
      this._play();
      return;
    }
    let i = this.index + 1;
    if (i >= this.queue.length) {
      if (this.repeat === "all") {
        i = 0;
      } else {
        if (fromEnded) {                       // Ende der Warteschlange: anhalten, am Anfang stehen
          this._audio.pause();
          this._audio.currentTime = 0;
          this._render();
        }
        return;
      }
    }
    this._load(i, true);
  },

  prev() {
    if (!this.queue.length) return;
    if (this._audio.currentTime > 3) { this._audio.currentTime = 0; return; }
    if (this.index > 0) { this._load(this.index - 1, true); return; }
    if (this.repeat === "all" && this.queue.length > 1) { this._load(this.queue.length - 1, true); return; }
    this._audio.currentTime = 0;
  },

  _duration() {
    const a = this._audio;
    if (a && isFinite(a.duration) && a.duration > 0) return a.duration;
    const cur = this.current();
    return cur ? (cur.duration || 0) : 0;
  },

  seek(fraction) {
    const cur = this.current();
    if (!cur) return;
    const f = Math.min(Math.max(Number(fraction) || 0, 0), 1);
    const target = f * this._duration();
    if (this._srcUid === cur.uid) this._audio.currentTime = target;
    else this.resumeAt = target;               // nach dem Neuladen noch nicht geladen
    this._updateProgress();
  },

  setVolume(v) {
    this.volume = Math.min(Math.max(Number(v) || 0, 0), 1);
    if (this._audio) this._audio.volume = this.volume;
    this._save();
  },

  toggleShuffle() {
    const cur = this.current();
    this.shuffle = !this.shuffle;
    if (this.shuffle) {
      this._shuffleQueue();
    } else {
      this.queue = this.original.slice();
      this.index = cur ? this.queue.findIndex((it) => it.uid === cur.uid) : -1;
    }
    this._render();
    this._save();
  },

  cycleRepeat() {
    this.repeat = this.repeat === "off" ? "all" : (this.repeat === "all" ? "one" : "off");
    this._render();
    this._save();
  },

  jump(uid) {
    const i = this.queue.findIndex((it) => it.uid === uid);
    if (i >= 0) this._load(i, true);
  },

  remove(uid) {
    const i = this.queue.findIndex((it) => it.uid === uid);
    if (i < 0) return;
    const wasCurrent = i === this.index;
    const wasPlaying = this.playing;
    this.queue.splice(i, 1);
    this.original = this.original.filter((it) => it.uid !== uid);
    if (!this.queue.length) { this.clear(); return; }
    if (i < this.index) this.index -= 1;
    if (wasCurrent) {
      this._load(Math.min(this.index, this.queue.length - 1), wasPlaying);
    } else {
      this._render();
      this._save();
    }
  },

  clear() {
    if (this._audio) {
      this._audio.pause();
      this._audio.removeAttribute("src");
      this._audio.load();
    }
    this.queue = [];
    this.original = [];
    this.index = -1;
    this.playing = false;
    this.resumeAt = 0;
    this._srcUid = null;
    this._render();
    try { localStorage.removeItem(_NP_STORAGE_KEY); } catch (e) { /* ignorieren */ }
  },

  // ---- Audio-Ereignisse ---------------------------------------------
  _onTimeUpdate() {
    this._failures = 0;
    this._updateProgress();
    const t = this._audio.currentTime || 0;
    if (Math.abs(t - this._lastSave) >= _NP_SAVE_INTERVAL_S) this._save();
  },

  _onLoadedMetadata() {
    if (this.resumeAt > 0) {
      this._audio.currentTime = this.resumeAt;
      this.resumeAt = 0;
    }
    this._updateProgress();
  },

  // Nicht abspielbar: melden und mit dem nächsten Titel weitermachen; scheitern
  // alle hintereinander, bleibt der Player stehen (keine Endlosschleife).
  _onError() {
    const cur = this.current();
    if (!cur) return;
    this._failures += 1;
    ccToast("error", "Wiedergabe fehlgeschlagen", cur.title || cur.id);
    if (this._failures >= this.queue.length || this.index + 1 >= this.queue.length) {
      this._failures = 0;
      this.playing = false;
      this._render();
      return;
    }
    this._load(this.index + 1, true);
  },

  // ---- Persistenz ----------------------------------------------------
  _save() {
    try {
      if (!this.queue.length) { localStorage.removeItem(_NP_STORAGE_KEY); return; }
      const t = this._audio && this._srcUid === (this.current() || {}).uid
        ? (this._audio.currentTime || 0) : this.resumeAt;
      this._lastSave = t;
      localStorage.setItem(_NP_STORAGE_KEY, JSON.stringify({
        v: 1, queue: this.queue, original: this.original.map((it) => it.uid),
        index: this.index, position: t, shuffle: this.shuffle, repeat: this.repeat, volume: this.volume,
      }));
    } catch (e) { /* localStorage gesperrt: Player läuft ohne Persistenz */ }
  },

  _restore() {
    try {
      const raw = localStorage.getItem(_NP_STORAGE_KEY);
      if (!raw) return;
      const d = JSON.parse(raw);
      if (!d || d.v !== 1 || !Array.isArray(d.queue)) return;
      const queue = d.queue.filter((it) => it && typeof it.id === "string" && _NP_ID_RE.test(it.id)
        && Number.isInteger(it.uid)).slice(0, _NP_MAX_QUEUE).map((it) => ({
        uid: it.uid, id: it.id, title: String(it.title || ""), artist: String(it.artist || ""),
        artist_id: String(it.artist_id || ""), album: String(it.album || ""), album_id: String(it.album_id || ""),
        duration: Number(it.duration) || 0, cover: String(it.cover || ""),
      }));
      if (!queue.length) return;
      const byUid = new Map(queue.map((it) => [it.uid, it]));
      const original = (Array.isArray(d.original) ? d.original : []).map((u) => byUid.get(u)).filter(Boolean);
      this.queue = queue;
      this.original = original.length === queue.length ? original : queue.slice();
      this.index = Number.isInteger(d.index) && d.index >= 0 && d.index < queue.length ? d.index : 0;
      this.shuffle = !!d.shuffle;
      this.repeat = ["off", "all", "one"].includes(d.repeat) ? d.repeat : "off";
      this.volume = typeof d.volume === "number" && d.volume >= 0 && d.volume <= 1 ? d.volume : 0.8;
      this.resumeAt = Number(d.position) > 0 ? Number(d.position) : 0;
      this._uid = Math.max(...queue.map((it) => it.uid));
    } catch (e) { /* kaputter Speicher: leer starten */ }
  },

  // ---- Media Session (Sperrbildschirm, Medientasten) -----------------
  _bindMediaSession() {
    const ms = typeof navigator !== "undefined" ? navigator.mediaSession : null;
    if (!ms || typeof ms.setActionHandler !== "function") return;
    const set = (name, fn) => { try { ms.setActionHandler(name, fn); } catch (e) { /* nicht unterstützt */ } };
    set("play", () => { if (this._audio.paused) this.toggle(); });
    set("pause", () => { if (!this._audio.paused) this.toggle(); });
    set("previoustrack", () => this.prev());
    set("nexttrack", () => this.next(false));
    set("seekto", (d) => { if (d && typeof d.seekTime === "number" && this._duration()) this.seek(d.seekTime / this._duration()); });
  },

  _bindMetadata() {
    const cur = this.current();
    const ms = typeof navigator !== "undefined" ? navigator.mediaSession : null;
    if (!cur || !ms || typeof MediaMetadata === "undefined") return;
    try {
      ms.metadata = new MediaMetadata({
        title: cur.title, artist: cur.artist, album: cur.album,
        artwork: cur.cover ? [{ src: _npCoverUrl(cur.cover, 512), sizes: "512x512" }] : [],
      });
    } catch (e) { /* ignorieren */ }
  },

  // ---- Oberfläche ----------------------------------------------------
  _artistAlbum(cur) {
    const artist = cur.artist_id
      ? `<a href="#/artist/${encodeURIComponent(cur.artist_id)}">${_npEsc(cur.artist)}</a>` : _npEsc(cur.artist);
    const album = cur.album_id
      ? `<a href="#/album/${encodeURIComponent(cur.album_id)}" class="text-reset">${_npEsc(cur.album)}</a>` : _npEsc(cur.album);
    return [artist, album].filter((x) => x).join(" · ");
  },

  _transport(big) {
    const playIcon = this.playing ? "player-pause" : "player-play";
    const playLabel = this.playing ? "Pause" : "Wiedergabe";
    const repeatIcon = this.repeat === "one" ? "repeat-once" : "repeat";
    return `
      ${_npBtn("shuffle", "shuffle", "Zufällig", this.shuffle ? "nav-np-on" : "")}
      ${_npBtn("prev", "skip-back", "Vorheriger Titel")}
      <button type="button" class="btn btn-icon btn-primary rounded-circle nav-np-play ${big ? "nav-np-play-lg" : ""}"
        data-np-act="toggle" title="${playLabel}" aria-label="${playLabel}">${ccIcon(playIcon)}</button>
      ${_npBtn("next", "skip-forward", "Nächster Titel")}
      ${_npBtn("repeat", repeatIcon, "Wiederholen: " + ({ off: "aus", all: "alle", one: "ein Titel" })[this.repeat], this.repeat !== "off" ? "nav-np-on" : "")}`;
  },

  _volume(idSuffix) {
    return `<span class="nav-np-vol-icon">${ccIcon("volume")}</span>
      <input type="range" min="0" max="100" step="1" value="${Math.round(this.volume * 100)}"
        class="form-range nav-np-range" data-np-range="volume" aria-label="Lautstärke" id="nav-np-vol${idSuffix}">`;
  },

  _barHtml(cur) {
    return `
      <div class="nav-np-info">
        <button type="button" class="nav-np-coverbtn d-md-none" data-bs-toggle="offcanvas"
          data-bs-target="#nav-fullplayer" aria-label="Player öffnen">${_npCover(cur.cover, 120)}</button>
        <a class="nav-np-coverbtn d-none d-md-block" href="${_npEsc(cur.album_id ? "#/album/" + encodeURIComponent(cur.album_id) : "#")}"
          tabindex="-1" aria-hidden="true">${_npCover(cur.cover, 120)}</a>
        <div class="min-w-0">
          <div class="fw-medium text-truncate">${_npEsc(cur.title)}</div>
          <div class="text-secondary small text-truncate">${this._artistAlbum(cur)}</div>
        </div>
      </div>
      <div class="nav-np-transport">${this._transport(false)}</div>
      <div class="nav-np-seek d-none d-md-flex">
        <span class="small text-secondary" id="nav-np-cur">0:00</span>
        <input type="range" min="0" max="1000" step="1" value="0" class="form-range nav-np-range"
          data-np-range="seek" aria-label="Position" id="nav-np-seek">
        <span class="small text-secondary" id="nav-np-dur">0:00</span>
      </div>
      <div class="nav-np-vol d-none d-lg-flex">${this._volume("")}</div>
      <button type="button" class="btn btn-icon btn-ghost-secondary nav-np-btn nav-np-queue"
        data-bs-toggle="offcanvas" data-bs-target="#nav-queue-offcanvas"
        title="Warteschlange" aria-label="Warteschlange">${ccIcon("playlist")}</button>
      <div class="nav-np-mini d-md-none"><i id="nav-np-mini-fill"></i></div>`;
  },

  _fullHtml(cur) {
    return `
      <div class="nav-np-full-cover">${_npCover(cur.cover, 600)}</div>
      <div class="mt-3">
        <div class="h2 mb-1">${_npEsc(cur.title)}</div>
        <div class="text-secondary">${this._artistAlbum(cur)}</div>
      </div>
      <div class="d-flex align-items-center gap-2 mt-3">
        <span class="small text-secondary" id="nav-np-full-cur">0:00</span>
        <input type="range" min="0" max="1000" step="1" value="0" class="form-range nav-np-range"
          data-np-range="seek" aria-label="Position" id="nav-np-full-seek">
        <span class="small text-secondary" id="nav-np-full-dur">0:00</span>
      </div>
      <div class="d-flex justify-content-between align-items-center mt-2">${this._transport(true)}</div>
      <div class="d-flex align-items-center gap-2 mt-3">${this._volume("-full")}</div>`;
  },

  _queueHtml() {
    if (!this.queue.length) {
      return `<div class="empty py-5"><p class="empty-title">Warteschlange leer</p>
        <p class="empty-subtitle text-secondary">Titel per Klick abspielen oder mit „Als Nächstes“ einreihen.</p></div>`;
    }
    return `<div class="list-group list-group-flush">${this.queue.map((it, i) => `
      <div class="list-group-item list-group-item-action nav-queue-row ${i === this.index ? "nav-queue-current" : ""}"
           role="button" tabindex="0" data-np-act="jump" data-uid="${it.uid}">
        <div class="row align-items-center g-2">
          <div class="col-auto nav-song-lead text-secondary">${i === this.index ? ccIcon("player-play", "icon-sm text-teal") : i + 1}</div>
          <div class="col-auto">${_npCover(it.cover, 80, "nav-np-cover-sm")}</div>
          <div class="col min-w-0">
            <div class="text-truncate fw-medium ${i === this.index ? "text-teal" : ""}">${_npEsc(it.title)}</div>
            <div class="text-secondary small text-truncate">${_npEsc(it.artist)}</div>
          </div>
          <div class="col-auto text-secondary small">${it.duration ? _npFmt(it.duration) : ""}</div>
          <div class="col-auto"><button type="button" class="btn btn-icon btn-ghost-secondary btn-sm" data-np-act="remove"
            data-uid="${it.uid}" title="Entfernen" aria-label="Aus Warteschlange entfernen">${ccIcon("x")}</button></div>
        </div>
      </div>`).join("")}</div>`;
  },

  _render() {
    const bar = document.getElementById("nav-player-bar");
    const cur = this.current();
    document.body.classList.toggle("nav-has-player", !!cur);
    if (bar) {
      bar.hidden = !cur;
      if (cur) bar.innerHTML = this._barHtml(cur);
    }
    const full = document.getElementById("nav-fullplayer-body");
    if (full && cur) full.innerHTML = this._fullHtml(cur);
    const qBody = document.getElementById("nav-queue-body");
    if (qBody) qBody.innerHTML = this._queueHtml();
    const summary = document.getElementById("nav-queue-summary");
    if (summary) {
      const total = this.queue.reduce((s, it) => s + (it.duration || 0), 0);
      summary.textContent = this.queue.length
        ? `${this.queue.length} Titel${total ? " · " + Math.round(total / 60) + " min" : ""}` : "";
    }
    this.decorate();
    this._updateProgress();
  },

  // Fortschritt ohne Neuaufbau (läuft bei jedem timeupdate).
  _updateProgress() {
    const cur = this.current();
    if (!cur) return;
    const live = this._srcUid === cur.uid && this._audio;
    const t = live ? (this._audio.currentTime || 0) : this.resumeAt;
    const d = this._duration();
    const f = d > 0 ? Math.min(t / d, 1) : 0;
    for (const id of ["nav-np-cur", "nav-np-full-cur"]) {
      const el = document.getElementById(id);
      if (el) el.textContent = _npFmt(t);
    }
    for (const id of ["nav-np-dur", "nav-np-full-dur"]) {
      const el = document.getElementById(id);
      if (el) el.textContent = _npFmt(d);
    }
    if (!this._seeking) {
      for (const id of ["nav-np-seek", "nav-np-full-seek"]) {
        const el = document.getElementById(id);
        if (el) el.value = String(Math.round(f * 1000));
      }
    }
    const mini = document.getElementById("nav-np-mini-fill");
    if (mini) mini.style.width = `${(f * 100).toFixed(1)}%`;
  },

  // Markiert in den Songlisten der Seite den laufenden Titel.
  decorate() {
    const cur = this.current();
    document.querySelectorAll(".nav-song-row").forEach((row) => {
      row.classList.toggle("nav-song-current", !!cur && row.dataset.songId === cur.id);
    });
  },

  // ---- Bedienung (Event-Delegation) ---------------------------------
  _onClick(ev) {
    const t = ev.target && ev.target.closest ? ev.target : null;
    if (!t) return;
    const el = t.closest("[data-np-act]");
    if (!el) return;
    const act = el.dataset.npAct;
    // closest() liefert das innerste Element: ein Klick auf "Entfernen" in einer
    // Warteschlangen-Zeile trifft zuerst den Entfernen-Knopf, nie die Zeile.
    if (act === "remove") this.remove(Number(el.dataset.uid));
    else if (act === "jump") this.jump(Number(el.dataset.uid));
    else if (act === "toggle") this.toggle();
    else if (act === "prev") this.prev();
    else if (act === "next") this.next(false);
    else if (act === "shuffle") this.toggleShuffle();
    else if (act === "repeat") this.cycleRepeat();
  },

  _onInput(ev) {
    const t = ev.target;
    if (!t || !t.dataset) return;
    if (t.dataset.npRange === "seek") this.seek(Number(t.value) / 1000);
    else if (t.dataset.npRange === "volume") this.setVolume(Number(t.value) / 100);
  },
};
