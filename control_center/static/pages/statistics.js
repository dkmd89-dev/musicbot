// control_center/static/pages/statistics.js
// Hörstatistik des angemeldeten Nutzers (GET /api/v1/statistics/me*).
// CC-UI Statistics nach docs/CONTROL_CENTER_UI_STANDARD.md: Sprite-Icons
// statt Emojis, Zustände über ccState, Laden über ccApi, Music DNA als
// Blickfang (Nutzerentscheidung 2026-09-28). Endpunkte und Berechnungen
// unverändert - alle Werte kommen fertig aus der API.

const _statsState = {
  month: null,
  genres: null,
  dna: null,
  timeline: null,
};

const _STATS_PERIOD_LABELS = { week: "Woche", month: "Monat", year: "Jahr" };

// Tageszeit-Buckets aus services/statistik/statistics_calculator.py.
const _STATS_TIME_OF_DAY = [
  ["morgens", "Morgens", "sunrise"],
  ["nachmittags", "Nachmittags", "sun"],
  ["abends", "Abends", "sunset"],
  ["nachts", "Nachts", "moon"],
];

function _statsBar(pct, extraClass) {
  const width = Math.max(0, Math.min(100, Number(pct) || 0));
  return `<div class="progress progress-sm${extraClass ? " " + extraClass : ""}">`
    + `<div class="progress-bar bg-teal" style="width: ${width}%" role="progressbar"`
    + ` aria-valuenow="${width.toFixed(1)}" aria-valuemin="0" aria-valuemax="100"></div></div>`;
}

// Rangliste: Rang, Name, Wert, Balken relativ zum ersten Eintrag.
function _statsRankedList(items, valueFn, suffix) {
  const max = items.length ? valueFn(items[0]) : 0;
  return items.map((item, i) => {
    const value = valueFn(item);
    return '<div class="mb-3">'
      + '<div class="d-flex align-items-center gap-2 mb-1">'
      + `<span class="text-secondary flex-shrink-0">${i + 1}.</span>`
      + `<span class="flex-fill text-truncate">${_escapeHtml(item.label)}</span>`
      + `<span class="fw-semibold flex-shrink-0">${_escapeHtml(value)}${suffix || ""}</span>`
      + "</div>"
      + _statsBar(max > 0 ? (value / max) * 100 : 0)
      + "</div>";
  }).join("");
}

function _updateKpiHeader() {
  const m = _statsState.month;
  const d = _statsState.dna;
  const set = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };

  set("kpi-plays", m?.total_plays ?? "–");
  set("kpi-songs", d?.unique_songs ?? "–");
  set("kpi-repeat",
    d?.repeat_rate_pct !== null && d?.repeat_rate_pct !== undefined ? `${d.repeat_rate_pct}%` : "–");
  // Top-Genre statt "Genres": top_genres_pct ist auf top_n gekappt, dessen
  // Länge war keine Genre-Anzahl (Nutzerentscheidung 2026-09-28).
  const topGenre = d?.top_genres_pct?.[0];
  set("kpi-genres", topGenre ? topGenre.label : "–");
  set("kpi-genres-sub", topGenre ? `All-Time, ${topGenre.pct}% der Plays` : "All-Time");
}

function renderMonthlyArtists(el, stats) {
  _statsState.month = stats;
  _updateKpiHeader();

  const periodEl = document.getElementById("monthly-artists-period");
  if (periodEl) {
    periodEl.textContent = stats.period
      ? stats.period.charAt(0).toUpperCase() + stats.period.slice(1)
      : "";
  }

  if (!stats.has_data || !stats.top_artists || !stats.top_artists.length) {
    ccState.empty(el, "Keine Wiedergaben", "Für diesen Zeitraum liegen keine Wiedergabedaten vor.");
    return;
  }
  el.innerHTML = _statsRankedList(stats.top_artists.slice(0, 5), (a) => a.count);
}

function renderAllTimeGenres(el, body) {
  _statsState.genres = body;

  if (!body.has_data || !body.top_genres || !body.top_genres.length) {
    ccState.empty(el, "Keine Genre-Daten");
    return;
  }
  el.innerHTML = _statsRankedList(body.top_genres.slice(0, 5), (g) => g.count);
}

function _statsFormatDuration(seconds) {
  const totalMinutes = Math.floor(Number(seconds || 0) / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function renderMusicTimeline(el, timeline) {
  _statsState.timeline = timeline;

  if (!timeline?.has_data || !timeline.track_count) {
    ccState.empty(el, "Heute noch nichts gehört");
    return;
  }

  const entry = (title, value, icon) => {
    const body = value?.label
      ? `<div class="fw-semibold text-truncate">${_escapeHtml(value.label)}</div>`
        + `<div class="text-secondary small">${value.count ?? 0} ${(value.count ?? 0) === 1 ? "Play" : "Plays"}</div>`
      : '<div class="text-secondary">–</div>';
    return '<div class="d-flex align-items-center gap-3">'
      + `<span class="avatar avatar-sm bg-teal-lt">${ccIcon(icon)}</span>`
      + `<div class="min-w-0"><div class="subheader">${title}</div>${body}</div></div>`;
  };

  el.innerHTML = '<div class="row g-2 mb-3">'
    + `<div class="col-4"><div class="subheader">Plays</div><div class="h2 mb-0">${_escapeHtml(timeline.track_count ?? "–")}</div></div>`
    + `<div class="col-4"><div class="subheader">Hörzeit</div><div class="h2 mb-0">${_statsFormatDuration(timeline.listening_seconds)}</div></div>`
    + `<div class="col-4"><div class="subheader">Neu</div><div class="h2 mb-0">${_escapeHtml(timeline.new_track_count ?? "–")}</div></div>`
    + "</div>"
    + '<div class="d-flex flex-column gap-3">'
    + entry("Top Künstler", timeline.top_artist, "microphone")
    + entry("Top Album", timeline.top_album, "disc")
    + entry("Top Genre", timeline.top_genre, "tag")
    + entry("Meistgehört", timeline.most_replayed_track, "heart")
    + "</div>";
}

// Profil-Highlight in der DNA-Karte (Wert groß, Beschriftung klein).
function _statsHighlight(icon, label, value, sub) {
  return '<div class="col-6 col-lg-3"><div class="cc-dna-highlight h-100">'
    + `<div class="subheader">${ccIcon(icon, "icon-sm me-1")}${label}</div>`
    + `<div class="h2 mb-0 text-truncate">${value}</div>`
    + `<div class="text-secondary small text-truncate">${sub}</div>`
    + "</div></div>";
}

function renderMusicDna(el, dna) {
  _statsState.dna = dna;
  _updateKpiHeader();

  if (!dna.has_data) {
    ccState.empty(el, "Noch kein Hörprofil", "Die Music DNA entsteht aus deinen Wiedergaben in Navidrome.");
    return;
  }

  const tod = dna.time_of_day_pct || {};
  const peak = _STATS_TIME_OF_DAY.reduce(
    (best, t) => ((tod[t[0]] ?? 0) > (tod[best[0]] ?? 0) ? t : best), _STATS_TIME_OF_DAY[0]);
  const topGenre = dna.top_genres_pct?.[0];
  const topArtist = dna.top_artists_pct?.[0];
  const repeat = dna.repeat_rate_pct !== null && dna.repeat_rate_pct !== undefined
    ? `${dna.repeat_rate_pct}%` : "–";

  const highlights = '<div class="row g-3 mb-4">'
    + _statsHighlight("tag", "Dein Genre",
      topGenre ? _escapeHtml(topGenre.label) : "–", topGenre ? `${topGenre.pct}% deiner Plays` : "keine Genre-Daten")
    + _statsHighlight("flame", "Heavy Rotation",
      topArtist ? _escapeHtml(topArtist.label) : "–", topArtist ? `${topArtist.pct}% deiner Plays` : "keine Artist-Daten")
    + _statsHighlight(peak[2], "Deine Zeit",
      (tod[peak[0]] ?? 0) > 0 ? peak[1] : "–", (tod[peak[0]] ?? 0) > 0 ? `${tod[peak[0]]}% deiner Plays` : "keine Daten")
    + _statsHighlight("repeat", "Repeat-Rate", repeat,
      `${_escapeHtml(dna.unique_songs ?? "–")} Songs, ${_escapeHtml(dna.total_plays ?? "–")} Plays`)
    + "</div>";

  const timeOfDay = '<div class="subheader mb-2">Tageszeit</div><div class="row g-2 mb-4">'
    + _STATS_TIME_OF_DAY.map(([key, label, icon]) => {
      const value = tod[key] ?? 0;
      const isPeak = key === peak[0] && value > 0;
      return '<div class="col-6 col-md-3">'
        + `<div class="cc-dna-tod${isPeak ? " cc-dna-tod-peak" : ""}">`
        + `<div class="d-flex align-items-center gap-2 mb-2">${ccIcon(icon, isPeak ? "text-teal" : "text-secondary")}`
        + `<span class="text-secondary small">${label}</span>`
        + `<span class="ms-auto h3 mb-0">${value}%</span></div>`
        + _statsBar(value)
        + "</div></div>";
    }).join("")
    + "</div>";

  const genres = (dna.top_genres_pct || []).slice(0, 5);
  const artists = (dna.top_artists_pct || []).slice(0, 5);
  const lists = '<div class="row g-4">'
    + `<div class="col-lg-6"><div class="subheader mb-2">${ccIcon("tag", "icon-sm me-1")}Genres</div>`
    + (genres.length ? _statsRankedList(genres, (g) => g.pct, "%") : '<p class="text-secondary mb-0">Keine Genre-Daten.</p>')
    + "</div>"
    + `<div class="col-lg-6"><div class="subheader mb-2">${ccIcon("flame", "icon-sm me-1")}Heavy Rotation</div>`
    + (artists.length ? _statsRankedList(artists, (a) => a.pct, "%") : '<p class="text-secondary mb-0">Keine Artist-Daten.</p>')
    + "</div></div>";

  el.innerHTML = highlights + timeOfDay + lists;
}

// Lädt einen Endpunkt in eine Karte; Fehler/Leer/Berechtigung über ccState.
async function _statsLoad(elementId, path, renderFn) {
  const el = document.getElementById(elementId);
  if (!el) return;
  ccState.loading(el);
  try {
    renderFn(el, await ccApi("GET", path));
  } catch (err) {
    if (err.status === 401) return;
    if (err.status === 403) { ccState.denied(el); return; }
    if (err.status === 404) {
      // z. B. NAVIDROME_USER_NOT_CONFIGURED - kein Fehler, sondern fehlende Zuordnung.
      ccState.empty(el, "Keine Statistik verfügbar", err.message);
      return;
    }
    ccState.error(el, err.message || "Fehler beim Laden.", () => _statsLoad(elementId, path, renderFn));
  }
}

function loadStatistics(period = "month") {
  const scopeEl = document.getElementById("kpi-plays-scope");
  if (scopeEl) scopeEl.textContent = _STATS_PERIOD_LABELS[period] || "Zeitraum";
  return Promise.all([
    _statsLoad("monthly-artists", `/api/v1/statistics/me?period=${encodeURIComponent(period)}`, renderMonthlyArtists),
    _statsLoad("all-time-genres", "/api/v1/statistics/me/genres", renderAllTimeGenres),
    _statsLoad("music-dna-content", "/api/v1/statistics/me/music-dna", renderMusicDna),
    _statsLoad("music-timeline", "/api/v1/statistics/me/timeline", renderMusicTimeline),
  ]);
}

function initStatisticsPage() {
  const periodEl = document.getElementById("statistics-period");
  periodEl?.addEventListener("change", () => loadStatistics(periodEl.value));
  loadStatistics(periodEl?.value || "month");
}

async function initPage() {
  const who = await checkAuth();
  if (!who) return;
  initStatisticsPage();
}

initPage();
