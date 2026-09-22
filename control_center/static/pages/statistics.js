// control_center/static/pages/statistics.js
const _statsState = {
    month: null,
    genres: null,
    dna: null,
    timeline: null,
  };

  function _renderProgressRow(
    label,
    count,
    maxCount,
    suffix = "",
    rank = null,
    variant = "month",
  ) {
    const pct = maxCount > 0 ? (count / maxCount) * 100 : 0;
    const rankHtml =
      rank !== null
        ? `<span class="text-secondary me-2">${rank}.</span>`
        : "";

    return `
      <div class="mb-3">
        <div class="d-flex align-items-center gap-2 mb-1">
          <span class="flex-fill text-truncate">
            ${rankHtml}${_escapeHtml(label)}
          </span>
          <span class="fw-semibold flex-shrink-0">${count}${suffix}</span>
        </div>
        <div class="progress progress-sm">
          <div
            class="progress-bar"
            style="width: ${pct}%"
            role="progressbar"
            aria-valuenow="${pct.toFixed(1)}"
            aria-valuemin="0"
            aria-valuemax="100"
          ></div>
        </div>
      </div>
    `;
  }

  function _getGenreEmoji(label) {
    const key = label.toLowerCase();

    if (key.includes("deutschrap")) return "🇩🇪";
    if (key.includes("alternative") && key.includes("hip")) return "🎧";
    if (key.includes("deutschpop") || (key.includes("deutsch") && key.includes("pop"))) return "🇩🇪";
    if (key.includes("hip hop") || key.includes("rap")) return "🎤";
    if (key.includes("pop")) return "🎹";
    if (key.includes("rock")) return "🎸";
    if (
      key.includes("electronic") ||
      key.includes("edm") ||
      key.includes("house") ||
      key.includes("techno")
    ) return "🎧";
    if (key.includes("jazz")) return "🎷";
    if (key.includes("classical") || key.includes("klassik")) return "🎻";
    if (key.includes("metal")) return "🤘";
    if (key.includes("punk")) return "🎸";
    if (key.includes("indie")) return "🎸";
    if (key.includes("r&b") || key.includes("soul")) return "🎙️";
    if (key.includes("reggae")) return "🌴";
    if (key.includes("country")) return "🤠";
    if (key.includes("folk")) return "🪕";

    return "🎵";
  }

  function _updateKpiHeader() {
    const m = _statsState.month;
    const d = _statsState.dna;

    const playsEl = document.getElementById("kpi-plays");
    const songsEl = document.getElementById("kpi-songs");
    const repeatEl = document.getElementById("kpi-repeat");
    const genresEl = document.getElementById("kpi-genres");

    if (playsEl) {
      playsEl.textContent = m?.total_plays ?? "–";
    }

    if (songsEl) {
      songsEl.textContent = d?.unique_songs ?? "–";
    }

    if (repeatEl) {
      repeatEl.textContent =
        d?.repeat_rate_pct !== null && d?.repeat_rate_pct !== undefined
          ? `${d.repeat_rate_pct}%`
          : "–";
    }

    if (genresEl) {
      genresEl.textContent = d?.top_genres_pct?.length ?? "–";
    }
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

    if (
      !stats.has_data ||
      !stats.top_artists ||
      !stats.top_artists.length
    ) {
      el.innerHTML =
        '<p class="empty-note mb-0">Keine Wiedergabedaten für diesen Zeitraum.</p>';
      return;
    }

    const maxArtistCount = stats.top_artists[0].count;

    const artistsHtml = stats.top_artists
      .slice(0, 5)
      .map((a, i) =>
        _renderProgressRow(
          a.label,
          a.count,
          maxArtistCount,
          "",
          i + 1,
          "month",
        ),
      )
      .join("");

    el.innerHTML = artistsHtml;
  }

  function renderAllTimeGenres(el, body) {
    _statsState.genres = body;

    if (
      !body.has_data ||
      !body.top_genres ||
      !body.top_genres.length
    ) {
      el.innerHTML =
        '<p class="empty-note mb-0">Keine Genre-Daten.</p>';
      return;
    }

    const maxGenreCount = body.top_genres[0].count;

    const genresHtml = body.top_genres
      .slice(0, 5)
      .map((g, index) => {
        const emoji = _getGenreEmoji(g.label);

        return _renderProgressRow(
          `${emoji} ${g.label}`,
          g.count,
          maxGenreCount,
          "",
          index + 1,
          "genres",
        );
      })
      .join("");

    el.innerHTML = genresHtml;
  }

  function renderMusicTimeline(el, timeline) {
    _statsState.timeline = timeline;

    if (!timeline?.has_data || !timeline.track_count) {
      el.innerHTML = '<p class="empty-note mb-0">Keine Wiedergaben heute.</p>';
      return;
    }

    const formatDuration = (seconds) => {
      const totalMinutes = Math.floor(Number(seconds || 0) / 60);
      const hours = Math.floor(totalMinutes / 60);
      const minutes = totalMinutes % 60;
      return hours
        ? `${hours}h ${minutes}m`
        : `${minutes}m`;
    };

    const entry = (value, icon, empty = "–") => {
      if (!value?.label) {
        return `<span class="text-secondary">${empty}</span>`;
      }

      const count = value.count ?? 0;

      return `
        <div class="d-flex align-items-center gap-2">
          <span class="fs-4" aria-hidden="true">${icon}</span>
          <div class="min-w-0">
            <div class="fw-semibold text-truncate">${_escapeHtml(value.label)}</div>
            <div class="text-secondary small">${count} ${count === 1 ? "Play" : "Plays"}</div>
          </div>
        </div>
      `;
    };

    el.innerHTML = `
      <div class="row g-2 mb-3">
        <div class="col-4">
          <div class="text-secondary small">Plays</div>
          <div class="h2 mb-0">${timeline.track_count ?? "–"}</div>
        </div>
        <div class="col-4">
          <div class="text-secondary small">Hörzeit</div>
          <div class="h2 mb-0">${formatDuration(timeline.listening_seconds)}</div>
        </div>
        <div class="col-4">
          <div class="text-secondary small">Neu</div>
          <div class="h2 mb-0">${timeline.new_track_count ?? "–"}</div>
        </div>
      </div>

      <div class="d-flex flex-column gap-3">
        <div>
          <div class="text-secondary small mb-1">Top Künstler</div>
          ${entry(timeline.top_artist, "🔥")}
        </div>

        <div>
          <div class="text-secondary small mb-1">Top Album</div>
          ${entry(timeline.top_album, "💿")}
        </div>

        <div>
          <div class="text-secondary small mb-1">Top Genre</div>
          ${entry(timeline.top_genre, "🎸")}
        </div>

        <div>
          <div class="text-secondary small mb-1">Meistgehört</div>
          ${entry(timeline.most_replayed_track, "❤️", "Keine Daten")}
        </div>
      </div>
    `;
  }

  function renderMusicDna(el, dna) {
    _statsState.dna = dna;
    _updateKpiHeader();

    if (!dna.has_data) {
      el.innerHTML =
        '<p class="empty-note mb-0">Keine Music-DNA-Daten.</p>';
      return;
    }

    const tod = dna.time_of_day_pct || {};

    const timeOfDay = [
      ["🌅", "Morgens", tod.morgens],
      ["☀️", "Nachmittags", tod.nachmittags],
      ["🌆", "Abends", tod.abends],
      ["🌙", "Nachts", tod.nachts],
    ];

    const todHtml = timeOfDay
      .map(
        ([emoji, label, value]) => `
          <div class="col-6 col-md-3">
            <div class="text-center py-2">
              <div class="fs-3 mb-1" aria-hidden="true">${emoji}</div>
              <div class="text-secondary small">${label}</div>
              <div class="h2 mb-0">${value ?? 0}%</div>
            </div>
          </div>
        `,
      )
      .join("");

    const maxGenrePct =
      dna.top_genres_pct && dna.top_genres_pct.length
        ? dna.top_genres_pct[0].pct
        : 1;

    const genrePctHtml = (dna.top_genres_pct || [])
      .slice(0, 5)
      .map((genre, index) => {
        const emoji = _getGenreEmoji(genre.label);

        return `
          <div class="mb-3">
            <div class="d-flex align-items-center gap-2 mb-1">
              <span class="text-secondary flex-shrink-0">${index + 1}.</span>
              <span class="fw-semibold flex-fill text-truncate">
                ${emoji} ${_escapeHtml(genre.label)}
              </span>
              <span class="fw-semibold flex-shrink-0">${genre.pct}%</span>
            </div>
            <div class="progress progress-sm">
              <div
                class="progress-bar"
                style="width: ${
                  maxGenrePct > 0
                    ? (genre.pct / maxGenrePct) * 100
                    : 0
                }%"
                role="progressbar"
                aria-valuenow="${genre.pct}"
                aria-valuemin="0"
                aria-valuemax="100"
              ></div>
            </div>
          </div>
        `;
      })
      .join("");

    const maxArtistPct =
      dna.top_artists_pct && dna.top_artists_pct.length
        ? dna.top_artists_pct[0].pct
        : 1;

    const artistPctHtml = (dna.top_artists_pct || [])
      .slice(0, 5)
      .map(
        (artist, index) => `
          <div class="mb-3">
            <div class="d-flex align-items-center gap-2 mb-1">
              <span class="text-secondary flex-shrink-0">${index + 1}.</span>
              <span class="fw-semibold flex-fill text-truncate">
                ${_escapeHtml(artist.label)}
              </span>
              <span class="fw-semibold flex-shrink-0">${artist.pct}%</span>
            </div>
            <div class="progress progress-sm">
              <div
                class="progress-bar"
                style="width: ${
                  maxArtistPct > 0
                    ? (artist.pct / maxArtistPct) * 100
                    : 0
                }%"
                role="progressbar"
                aria-valuenow="${artist.pct}"
                aria-valuemin="0"
                aria-valuemax="100"
              ></div>
            </div>
          </div>
        `,
      )
      .join("");

    const repeatRate =
      dna.repeat_rate_pct !== null &&
      dna.repeat_rate_pct !== undefined
        ? `${dna.repeat_rate_pct}%`
        : "–";

    el.innerHTML = `
      <!-- Tageszeit -->
      <div class="mb-4">
        <div class="d-flex align-items-center gap-2 mb-2">
          <span class="fs-3" aria-hidden="true">🕐</span>
          <h3 class="card-title mb-0">Tageszeit</h3>
        </div>

        <div class="row g-0 border rounded">
          ${todHtml}
        </div>
      </div>

      <!-- Genres + Heavy Rotation -->
      <div class="row">
        <div class="col-lg-6 mb-4 mb-lg-0">
          <div class="d-flex align-items-center gap-2 mb-3">
            <span class="fs-3" aria-hidden="true">🎤</span>
            <h3 class="card-title mb-0">Genres</h3>
          </div>

          ${
            genrePctHtml ||
            '<p class="empty-note mb-0">Keine Genre-Daten.</p>'
          }
        </div>

        <div class="col-lg-6">
          <div class="d-flex align-items-center gap-2 mb-3">
            <span class="fs-3" aria-hidden="true">🔥</span>
            <h3 class="card-title mb-0">Heavy Rotation</h3>
          </div>

          ${
            artistPctHtml ||
            '<p class="empty-note mb-0">Keine Artist-Daten.</p>'
          }
        </div>
      </div>
    `;
  }

  async function loadStatistics(period = "month") {
    const artistsEl = document.getElementById("monthly-artists");
    const genresEl = document.getElementById("all-time-genres");
    const dnaEl = document.getElementById("music-dna-content");
    const timelineEl = document.getElementById("music-timeline");

    if (!artistsEl || !genresEl || !dnaEl || !timelineEl) return;

    artistsEl.innerHTML = '<div class="empty-note">Lädt…</div>';
    genresEl.innerHTML = '<div class="empty-note">Lädt…</div>';
    dnaEl.innerHTML = '<div class="empty-note">Lädt…</div>';
    timelineEl.innerHTML = '<div class="empty-note">Lädt…</div>';

    try {
      await Promise.all([
        _loadInto(
          "monthly-artists",
          `/api/v1/statistics/me?period=${encodeURIComponent(period)}`,
          renderMonthlyArtists,
        ),
        _loadInto(
          "all-time-genres",
          "/api/v1/statistics/me/genres",
          renderAllTimeGenres,
        ),
        _loadInto(
          "music-dna-content",
          "/api/v1/statistics/me/music-dna",
          renderMusicDna,
        ),
        _loadInto(
          "music-timeline",
          "/api/v1/statistics/me/timeline",
          renderMusicTimeline,
        ),
      ]);
    } catch (err) {
      console.error("Statistics konnten nicht geladen werden:", err);
    }
  }

  function initStatisticsPage() {
    const periodEl = document.getElementById("statistics-period");

    periodEl?.addEventListener("change", () => {
      loadStatistics(periodEl.value);
    });

    loadStatistics(periodEl?.value || "month");
  }

    async function initPage() {
	    const who = await checkAuth();
	    if (!who) return;
	    initStatisticsPage();
	  }

	  initPage();
