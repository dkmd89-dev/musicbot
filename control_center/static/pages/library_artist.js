
  // Library Artist-Centric UX (CC-AC-1) — Artist-Detail. Bewusst KEIN
  // serverseitig gerenderter Artist-Name (siehe ui.py::
  // library_artist_detail_page()-Docstring): der Artist-Name kommt aus
  // dem letzten Pfadsegment, ein unbekannter Artist bleibt ein sauberer
  // API-404 statt eines Server-Renderfehlers. F5-tauglich, da derselbe
  // Pfad bei jedem Laden identisch ausgewertet wird.
  function currentArtistFromPath() {
    const parts = window.location.pathname.split("/").filter(Boolean);
    return decodeURIComponent(parts[parts.length - 1] || "");
  }

  // Master-Detail (Phase E, CC-LIB-FINAL, Freigabe-Layout "Final —
  // Hybrid"): ein Album links auswaehlen, dessen Tracks + album-weite
  // Aktionen rechts - ersetzt die vorherige "alle Alben mit allen Tracks
  // untereinander aufgeklappt"-Ansicht. Gruppierung bleibt
  // verzeichnisbasiert (album_directory, NICHT der ©alb-Tag-Wert, der
  // abweichen kann, z.B. "Skyr" vs. "2019 - Skyr") - identische
  // Konvention wie body.albums[].album (beide stammen aus demselben
  // album_dir, siehe services/library_health/scoring.py), Tracks und
  // Alben lassen sich damit verlustfrei ueber denselben Schluessel
  // zuordnen.
  let _selectedAlbumKey = null;

  // Reine Datenfunktion (kein Rendering) - liefert je Album (inkl. der
  // "Ohne Album"/Singles-Sammelgruppe) einen stabilen Schluessel, eine
  // Anzeige-Bezeichnung, die Dateizahl und - falls vorhanden - den
  // Health-Score aus body.albums (Singles haben keinen eigenen
  // Alben-Score). Sortierung wie zuvor: alphabetisch, "de"-Locale.
  function _artistDetailAlbumEntries(body) {
    const entries = (body.albums || []).slice()
      .sort((a, b) => a.album.localeCompare(b.album, "de"))
      .map((a) => ({
        key: a.album, label: a.album, fileCount: a.file_count,
        healthScore: a.health_score, isSingles: false,
      }));
    const singles = (body.tracks || []).filter((t) => !t.album_directory);
    if (singles.length) {
      entries.push({
        key: "__singles__", label: "Ohne Album", fileCount: singles.length,
        healthScore: null, isSingles: true,
      });
    }
    return entries;
  }

  // Tracks eines Albums, sortiert nach Tracknummer dann Titel (de) -
  // identische Sortierlogik wie zuvor.
  function _tracksForAlbumKey(body, key) {
    const tracks = (body.tracks || []).filter((t) =>
      key === "__singles__" ? !t.album_directory : t.album_directory === key);
    return tracks.slice().sort((a, b) => {
      const aNum = (typeof a.track_number === "number") ? a.track_number : 9999;
      const bNum = (typeof b.track_number === "number") ? b.track_number : 9999;
      if (aNum !== bNum) return aNum - bNum;
      return (a.title || a.filename).localeCompare(b.title || b.filename, "de");
    });
  }

  // CC-UI L3a: Tabler-list-group statt row-list/select-row (U2); Name wird
  // gekürzt, Anzahl/Score stehen als Badge rechts (U17: kein Überlauf).
  function _renderAlbumListHtml(entries) {
    if (!entries.length) return '<div class="card-body text-secondary">Keine Alben vorhanden.</div>';
    return '<div class="list-group list-group-flush">' + entries.map((e) => `
      <button type="button" class="list-group-item list-group-item-action d-flex align-items-center gap-2${e.key === _selectedAlbumKey ? " active" : ""}" data-album-key="${_escapeHtml(e.key)}">
        ${ccIcon(e.isSingles ? "music" : "disc", "text-secondary flex-shrink-0")}
        <span class="flex-fill text-truncate">${_escapeHtml(e.label)}</span>
        <span class="badge bg-secondary-lt flex-shrink-0" title="Titel${e.healthScore != null ? " · Score" : ""}">${e.fileCount}${e.healthScore != null ? " · " + e.healthScore : ""}</span>
      </button>
    `).join("") + "</div>";
  }

  // CC-AC-9-Muster (natives <button>, keine eigene Tastatur-Nachbildung)
  // fortgesetzt: pro Track ZWEI Geschwister-Buttons - der bestehende
  // .track-row (oeffnet den Track-Drawer, unveraendertes Verhalten ueber
  // die bereits vorhandene #artist-content-Klick-Delegation weiter unten)
  // und ein neuer, IMMER sichtbarer (nicht nur bei Hover - Touch hat kein
  // Hover, Auftrag §15) Quick-Edit-Button fuer "Titel bearbeiten" (Auftrag
  // §12 Context-First: das einzige echte Track-Feld - Genre/Artist/
  // Album/Albuminterpret sind Artist- bzw. Album-weite Aktionen und
  // bleiben dort, siehe unten bzw. den Track-Drawer fuer den
  // vollstaendigen Aktions-Umfang).
  function _renderAlbumDetailHtml(body, entries) {
    const selected = entries.find((e) => e.key === _selectedAlbumKey);
    if (!selected) return '<div class="card-body text-secondary">Kein Album ausgewählt.</div>';
    const tracks = _tracksForAlbumKey(body, selected.key);

    const trackRows = tracks.length
      ? tracks.map((t) => `
          <div class="list-group-item d-flex align-items-center gap-1 p-0">
            <button type="button" class="track-row list-group-item-action d-flex align-items-center gap-2 flex-fill min-w-0 border-0 bg-transparent text-start px-3 py-2" data-track-path="${_escapeHtml(t.relative_path)}" title="${_escapeHtml(t.relative_path)}">
              ${t.track_number ? `<span class="text-secondary flex-shrink-0">${_escapeHtml(String(t.track_number))}.</span>` : ""}
              <span class="flex-fill text-truncate">${_escapeHtml(t.title || t.filename)}</span>
              ${t.issue_codes.length ? `<span class="badge bg-yellow-lt flex-shrink-0" title="${_escapeHtml(t.issue_codes.map((c) => _ISSUE_LABELS[c] || c).join(", "))}">${ccIcon("alert", "icon-sm me-1")}${t.issue_codes.length}</span>` : ""}
            </button>
            <button type="button" class="btn btn-sm btn-ghost-teal quick-edit-btn me-2 flex-shrink-0" data-quick-edit-title="${_escapeHtml(t.relative_path)}" title="Titel bearbeiten" aria-label="Titel bearbeiten: ${_escapeHtml(t.title || t.filename)}">${ccIcon("edit")}</button>
          </div>
        `).join("")
      : '<div class="card-body text-secondary">Keine Tracks in diesem Album.</div>';

    // Album-/Albuminterpret-Aktionen nur fuer echte Mehr-Track-Alben
    // (identische Einschraenkung wie der bestehende Track-Drawer via
    // _trackAlbumValue() weiter unten - die "Ohne Album"-Sammelgruppe
    // mischt mehrere voneinander unabhaengige Singles, hat also keinen
    // gemeinsamen Album-/Albuminterpret-Scope).
    const toolbar = selected.isSingles ? "" : `
      <div class="d-flex gap-2 flex-wrap">
        <button type="button" class="btn btn-sm" id="album-detail-edit-album-btn">${ccIcon("disc", "me-1")}Album bearbeiten</button>
        <button type="button" class="btn btn-sm" id="album-detail-edit-albumartist-btn">${ccIcon("users", "me-1")}Albuminterpret</button>
      </div>
    `;

    return `
      <div class="card-header flex-wrap gap-2">
        <div class="min-w-0 flex-fill">
          <h3 class="card-title text-truncate">${ccIcon(selected.isSingles ? "music" : "disc", "me-2 text-teal")}${_escapeHtml(selected.label)}</h3>
          <div class="card-subtitle">${tracks.length} Titel${selected.healthScore != null ? " · Score " + selected.healthScore : ""}</div>
        </div>
        ${toolbar}
      </div>
      <div class="segment-nav d-flex gap-3 px-3 pt-3 small">
        <span class="text-teal fw-medium">${ccIcon("music", "icon-sm me-1")}Tracks</span>
        ${_trackDrawerIsAdmin ? `<a href="#" id="artist-detail-open-metadata">${ccIcon("edit", "icon-sm me-1")}Metadaten bearbeiten</a>` : ""}
      </div>
      <div class="list-group list-group-flush mt-2">${trackRows}</div>
    `;
  }

  // Nach Album-Wahl (Klick auf einen Eintrag der linken Liste) beide
  // Haelften neu rendern - kein neuer API-Call, dieselben bereits
  // geladenen body.tracks/body.albums.
  function _rerenderAlbumMasterDetail() {
    if (!_artistDetailLastBody) return;
    const entries = _artistDetailAlbumEntries(_artistDetailLastBody);
    document.getElementById("artist-album-list").innerHTML = _renderAlbumListHtml(entries);
    document.getElementById("artist-album-detail").innerHTML = _renderAlbumDetailHtml(_artistDetailLastBody, entries);
  }

  // CC-AC-9: Nachschlagetabelle fuer den Track Detail Drawer - dieselben
  // body.tracks wie oben, keyed nach relative_path (eindeutig je Track,
  // bereits als Tooltip/Titel-Edit-Scope-Wert verwendet). KEIN neuer
  // API-Call.
  let _artistDetailTracksByPath = {};
  // Letzte artists-overview/{artist}-Antwort - fuer den Album-Wechsel
  // (kein neuer Request pro Klick auf einen Album-Listeneintrag).
  let _artistDetailLastBody = null;

  function renderArtistDetail(el, body) {
    _artistDetailTracksByPath = {};
    body.tracks.forEach((t) => { _artistDetailTracksByPath[t.relative_path] = t; });
    _artistDetailLastBody = body;

    document.getElementById("artist-title").textContent = body.artist;
    document.getElementById("breadcrumb-artist").textContent = body.artist;
    document.title = `${body.artist} – Library – MusicBot Control Center`;

    const staleNote = body.stale
      ? ` · <span class="text-warning">Stand: ${_escapeHtml(body.generated_at || "unbekannt")} (nicht mehr aktuell)</span>`
      : (body.generated_at ? ` · <span class="small">Stand: ${_escapeHtml(body.generated_at)}</span>` : "");
    document.getElementById("artist-subtitle").innerHTML =
      `${body.file_count} Dateien · ${body.album_count} Alben${staleNote}`;

    // Schwellen 90/70 wie der Health-Punkt in der Library-Liste (ok/warn/error).
    const scoreColor = body.health_score >= 90 ? "green"
      : body.health_score >= 70 ? "yellow" : "red";

    // 4. KPI-Kachel "Offene Findings" (Auftrag §9/§10 Dashboard) - Summe
    // der bereits geladenen Track-issue_codes, kein zusaetzlicher Request.
    const openFindings = body.tracks.reduce((sum, t) => sum + (t.issue_codes || []).length, 0);

    const entries = _artistDetailAlbumEntries(body);
    if (!_selectedAlbumKey || !entries.some((e) => e.key === _selectedAlbumKey)) {
      _selectedAlbumKey = entries.length ? entries[0].key : null;
    }

    const kpi = (icon, color, label, value, id) => `
      <div class="col-6 col-lg-3">
        <div class="card card-sm h-100"><div class="card-body"><div class="row align-items-center g-3">
          <div class="col-auto"><span class="avatar bg-${color}-lt">${ccIcon(icon)}</span></div>
          <div class="col min-w-0"><div class="subheader">${label}</div>
            <div class="h2 mb-0" data-kpi="${id}">${value}</div></div>
        </div></div></div>
      </div>`;

    el.innerHTML = `
      <div class="row row-cards mb-3">
        ${kpi("health", scoreColor, "Health Score", `<span class="text-${scoreColor}">${body.health_score}</span>`, "health")}
        ${kpi("music", "teal", "Dateien", body.file_count, "files")}
        ${kpi("disc", "blue", "Alben", body.album_count, "albums")}
        ${kpi("alert", openFindings ? "yellow" : "secondary", "Offene Findings", openFindings, "findings")}
      </div>
      <div class="row row-cards mb-3">
        <div class="col-lg-4">
          <div class="card h-100">
            <div class="card-header"><h3 class="card-title">${ccIcon("disc", "me-2 text-teal")}Alben</h3></div>
            <div id="artist-album-list">${_renderAlbumListHtml(entries)}</div>
          </div>
        </div>
        <div class="col-lg-8">
          <div class="card h-100">
            <div id="artist-album-detail">${_renderAlbumDetailHtml(body, entries)}</div>
          </div>
        </div>
      </div>
    `;

    _populateAlbumPickers(body);
    _populateTrackPickers(body);
  }

  // Album-Picker fuer "Album bearbeiten"/"Albuminterpret bearbeiten"
  // (CC-AC-3, library_artist_centric_UX.txt §63-67): KEINE neue
  // Datenquelle - Optionen kommen ausschliesslich aus der bereits
  // geladenen artists-overview/{artist}-Antwort (body.albums/body.tracks).
  // body.albums deckt nur Mehr-Track-Alben ab (services/library_health/
  // scoring.py::build_health_section() gruppiert nur Dateien mit
  // gesetztem album_directory - Singles haben album_directory=None,
  // siehe services/library_health/discovery.py::
  // _classify_section_and_dirs()). Damit Artists, die AUSSCHLIESSLICH
  // Singles besitzen (Auftrag §16, Beispiel "1986zig" in §6-Mockup), im
  // Picker nicht leer bleiben, werden Tracks OHNE album_directory
  // zusaetzlich aus body.tracks abgeleitet (deckt sowohl echte Singles
  // unter "Singles/<Datei>" als auch vereinzelte Dateien direkt im
  // Artist-Ordner ab - bewusst weiter gefasst als services/
  // library_repair/library_artists.py::list_artist_albums(), das NUR den
  // "Singles"-Ordner speziell behandelt; beide Faelle sind fuer
  // maintenance_service.py::album_targets() gueltige Ein-Track-Scopes,
  // Wert = relativer Pfad ohne Artist-Praefix). Nur .m4a (identische
  // Einschraenkung wie list_artist_albums() - ©alb/aART/©ART/©nam sind
  // MP4-/iTunes-Atome, siehe LIBRARY_REPAIR.md §15/§16).
  function _artistAlbumOptions(artist, body) {
    const options = (body.albums || []).map((a) => ({
      value: a.album, label: `${a.album} (${a.file_count} Dateien)`,
    }));
    const prefix = `${artist}/`;
    (body.tracks || []).forEach((t) => {
      if (t.album_directory || t.extension !== ".m4a") return;
      if (!t.relative_path.startsWith(prefix)) return;
      const value = t.relative_path.slice(prefix.length);
      options.push({ value, label: `${t.title || t.filename} (Single)` });
    });
    return options;
  }

  function _populateAlbumSelect(selectEl, options) {
    const previous = selectEl.value;
    selectEl.innerHTML = '<option value="">Album wählen …</option>' + options.map((o) => `
      <option value="${_escapeHtml(o.value)}">${_escapeHtml(o.label)}</option>
    `).join("");
    if (options.some((o) => o.value === previous)) selectEl.value = previous;
  }

  function _populateAlbumPickers(body) {
    const options = _artistAlbumOptions(body.artist, body);
    _populateAlbumSelect(document.getElementById("album-edit-album-select"), options);
  }

  // Track-Picker fuer "Titel bearbeiten" (Auftrag §6.2 CC-LIB-FINAL): der
  // Benutzer waehlt einen Track aus dem bestehenden Library-Kontext
  // (Album-Gruppierung, Trackname) statt einen technischen relativen
  // Dateipfad manuell einzutippen. KEINE neue Datenquelle - dieselben
  // body.tracks wie _renderTracksGroupedByAlbum()/_artistDetailTracksByPath
  // oben, der Options-Wert ist weiterhin relative_path (das erwartet die
  // bestehende API unveraendert), nur nicht mehr als Freitext sichtbar/
  // editierbar. Der Server bleibt die eigentliche Schranke
  // (maintenance_service.py::_title_edit_targets() Containment-Pruefung,
  // Auftrag §12/CC-LIB-FINAL Phase C) - ein Client-seitiger "Scope Guard"
  // ist strukturell nicht mehr noetig, da die Auswahl ausschliesslich aus
  // den bereits geladenen Tracks DIESES Artists gespeist wird.
  function _artistTrackOptionGroups(body) {
    const groups = new Map();
    (body.tracks || []).forEach((t) => {
      const key = t.album_directory || "Ohne Album";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(t);
    });
    const sortedKeys = [...groups.keys()].sort((a, b) => a.localeCompare(b, "de"));
    return sortedKeys.map((key) => ({
      label: key,
      options: groups.get(key).slice().sort((a, b) => {
        const aNum = (typeof a.track_number === "number") ? a.track_number : 9999;
        const bNum = (typeof b.track_number === "number") ? b.track_number : 9999;
        if (aNum !== bNum) return aNum - bNum;
        return (a.title || a.filename).localeCompare(b.title || b.filename, "de");
      }).map((t) => ({
        value: t.relative_path,
        label: (t.track_number ? `${t.track_number}. ` : "") + (t.title || t.filename),
      })),
    }));
  }

  function _populateTrackSelect(selectEl, groups) {
    const previous = selectEl.value;
    selectEl.innerHTML = '<option value="">Track wählen …</option>' + groups.map((g) => `
      <optgroup label="${_escapeHtml(g.label)}">
        ${g.options.map((o) => `<option value="${_escapeHtml(o.value)}">${_escapeHtml(o.label)}</option>`).join("")}
      </optgroup>
    `).join("");
    if (groups.some((g) => g.options.some((o) => o.value === previous))) selectEl.value = previous;
  }

  // CC-UI L4: Titel direkt in der Trackliste bearbeiten (Nutzerfreigabe) -
  // immer ein Track zur Zeit. Die Bearbeitungs-Box (#title-edit-box, mit
  // festen IDs und Listenern) wird unter die gewählte Zeile verschoben.
  function _populateTrackPickers(body) {
    const list = document.getElementById("title-edit-list");
    if (!list) return;
    const box = document.getElementById("title-edit-box");
    if (box && box.parentNode === list) list.parentNode.appendChild(box);  // Box vor dem Neu-Rendern retten
    const groups = _artistTrackOptionGroups(body);
    list.innerHTML = groups.map((g) => `
      <div class="subheader mt-2 mb-1">${_escapeHtml(g.label)}</div>
      <div class="list-group mb-2">${g.options.map((o) => `
        <button type="button" class="list-group-item list-group-item-action d-flex align-items-center gap-2" data-title-path="${_escapeHtml(o.value)}">
          <span class="flex-fill text-truncate">${_escapeHtml(o.label)}</span>${ccIcon("edit", "text-secondary flex-shrink-0")}
        </button>`).join("")}</div>
    `).join("");
    const selected = document.getElementById("title-edit-track-select").value;
    if (selected) _markTitleRow(selected);
  }

  function _markTitleRow(relPath) {
    const list = document.getElementById("title-edit-list");
    const box = document.getElementById("title-edit-box");
    if (!list || !list.querySelectorAll) return;
    list.querySelectorAll("[data-title-path]").forEach((row) => {
      const active = row.dataset.titlePath === relPath;
      row.classList.toggle("active", active);
      if (active && box && row.insertAdjacentElement) row.insertAdjacentElement("afterend", box);
    });
    if (box) box.hidden = !relPath;
  }

  // Track wählen: Titel vorbelegen, Vorschau zurücksetzen, Feld fokussieren.
  function _selectTitleTrack(relPath) {
    const t = _artistDetailTracksByPath[relPath];
    document.getElementById("title-edit-track-select").value = relPath;
    document.getElementById("title-edit-new-title").value = t ? (t.title || "") : "";
    const _tn = (_artistDetailTracksByPath[relPath] || {}).track_number;
    document.getElementById("track-number-edit-new-number").value = _tn || "";
    _updateTrackNumberHint(relPath);
    document.getElementById("title-edit-result-content").innerHTML = "";
    _markTitleRow(relPath);
    _autoTitlePreview();
    document.getElementById("title-edit-new-title").focus();
  }

  // CC-UI L3a: Laden über ccApi, Zustände über ccState (Standard §7/§12).
  async function loadArtistDetail() {
    const el = document.getElementById("artist-content");
    const artist = currentArtistFromPath();
    const backLink = `<a href="${CC_BASE}/library" class="btn btn-sm">${ccIcon("arrow-left", "me-1")}Zurück zu Artists</a>`;
    if (!artist) {
      ccState.empty(el, "Kein Artist angegeben", null, backLink);
      return;
    }
    try {
      renderArtistDetail(el, await ccApi("GET", `/api/v1/library/artists-overview/${encodeURIComponent(artist)}`));
    } catch (err) {
      if (err.status === 401) return;
      if (err.status === 403) { ccState.denied(el); return; }
      if (err.status === 404) { ccState.empty(el, "Artist nicht gefunden", err.message, backLink); return; }
      ccState.error(el, err.message || "Fehler beim Laden.", loadArtistDetail);
    }
  }

  // ── CC-UI L3b: gemeinsame Bausteine für Bestätigung und Rückmeldung ──────
  // Browser-confirm() -> Bestätigungs-Modal (Standard §8). Erste Zeile des
  // bisherigen Texts wird Titel, der Rest Text - Wortlaut unverändert. Ohne
  // Tabler-Modal (Tests/Fallback) wie bisher der Browser-Dialog mit vollem Text.
  function _artistConfirm(message, confirmLabel) {
    if (!(window.tabler && window.tabler.Modal)) return Promise.resolve(window.confirm(message));
    const [title, ...rest] = String(message).split("\n\n");
    return ccConfirm({ title, text: rest.join("\n\n"), confirmLabel: confirmLabel || "Ausführen", danger: true });
  }

  // Pflichtfeld-Hinweis direkt am Feld statt alert() (Nutzerentscheidung
  // 2026-09-28). Verschwindet bei der nächsten Eingabe.
  function _fieldHint(id, message) {
    const field = document.getElementById(id);
    if (!field) return;
    let fb = document.getElementById(`${id}-feedback`);
    if (!fb && typeof document.createElement === "function" && field.insertAdjacentElement) {
      fb = document.createElement("div");
      fb.id = `${id}-feedback`;
      fb.className = "invalid-feedback";
      field.insertAdjacentElement("afterend", fb);
    }
    if (fb) fb.textContent = message;
    field.classList.add("is-invalid");
    const clear = () => field.classList.remove("is-invalid");
    field.addEventListener("input", clear, { once: true });
    field.addEventListener("change", clear, { once: true });
    field.focus();
  }

  function _runningHtml(text) {
    return `<div class="d-flex align-items-center gap-2 text-secondary"><span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>${_escapeHtml(text)}</div>`;
  }

  const _RESULT_ICONS = { success: "check", danger: "alert", warning: "alert", info: "info" };
  function _resultAlert(kind, html) {
    return `<div class="alert alert-${kind} mb-0">${ccIcon(_RESULT_ICONS[kind] || "info", "me-1")}${html}</div>`;
  }

  function _executeToast(body) {
    ccToast(body.failed_count ? "error" : "success", body.failed_count ? "Teilweise fehlgeschlagen" : "Änderungen geschrieben",
      `${body.success_count} erfolgreich, ${body.failed_count} fehlgeschlagen, ${body.skipped_count} übersprungen.`);
  }

  function _executeResultHtml(body, noteText) {
    return _resultAlert(body.failed_count ? "warning" : "success",
      `${body.success_count} erfolgreich, ${body.failed_count} fehlgeschlagen, ${body.skipped_count} übersprungen.`)
      + (noteText ? `<div class="text-secondary small mt-2">${noteText}</div>` : "");
  }

  // Manual Metadata Editing v1 (CC-AC-2, library_artist_centric_UX.txt) -
  // reine Verdrahtung der bestehenden, bereits produktiven Endpunkte aus
  // control_center/routers/admin_maintenance.py (Artist/Titel) und
  // control_center/routers/metadata_actions.py (Genre) in den Artist-
  // Kontext dieser Seite - identisches Preview->Confirm->Execute-Muster
  // wie admin.html/metadata.html, hier mit implizitem
  // artist=currentArtistFromPath() statt eines Freitextfelds (Auftrag
  // §12 "Artist-Kontext ueber den gesamten Flow"). Keine neue
  // Ausfuehrungslogik (Auftrag §14).

  function _diffSummary(before, after) {
    const parts = [];
    for (const key of Object.keys(after)) {
      const b = Array.isArray(before[key]) ? before[key].join(", ") : (before[key] ?? "–");
      const a = Array.isArray(after[key]) ? after[key].join(", ") : (after[key] ?? "–");
      if (String(b) === String(a)) continue;
      parts.push(`${key}: ${b} → ${a}`);
    }
    return parts.join(" | ");
  }

  // Gruende, die einen echten No-Op belegen (Ziel-/Ist-Wert stimmen
  // bereits ueberein - executor.py's "bereits korrekt"/"nichts zu tun /
  // bereits korrekt"). Jeder andere Skip-Grund (z. B. "Artist-Tag
  // entspricht nicht dem gewaehlten Ausgangswert" bei einem tag-wert-
  // getriebenen Rename, oder "Safety: ...") bedeutet das Gegenteil: der
  // Wert stimmt NICHT ueberein, es wird deshalb NICHTS geschrieben - "keine
  // Aenderung noetig" waere hier eine falsche, sich selbst widersprechende
  // Aussage neben einer Skip-Begruendung (Freigabe fix.txt 2026-09-27).
  // Identisches Unterscheidungsprinzip wie Telegram
  // (handlers/library_maintenance_handler.py, preview.changed_count==0-
  // Zweige bei Artist-Rename/Titel-Edit), hier bewusst weiter als EINE
  // generische Funktion belassen (von 4 Aktionen gemeinsam genutzt).
  const _NOOP_SKIP_REASONS = new Set(["bereits korrekt", "nichts zu tun / bereits korrekt"]);

  // CC-UI L4: execBtnId darf null sein (Album-Reiter steuert seinen einen
  // Übernehmen-Button selbst über onCount); Buttons mit data-count-label
  // zeigen die Zahl der betroffenen Dateien ("Übernehmen · 12 Dateien").
  function _setExecuteButton(startBtn, count) {
    if (!startBtn) return;
    startBtn.disabled = !count;
    const label = startBtn.dataset && startBtn.dataset.countLabel;
    if (label) {
      startBtn.innerHTML = ccIcon("check", "me-1") + _escapeHtml(label)
        + (count ? ` · ${count} ${count === 1 ? "Datei" : "Dateien"}` : "");
    }
  }

  function renderMetadataEditPreview(el, body, execBtnId, onCount) {
    const startBtn = execBtnId ? document.getElementById(execBtnId) : null;
    const report = (count) => { _setExecuteButton(startBtn, count); if (onCount) onCount(count); };
    if (!body.target_count) {
      el.innerHTML = '<div class="text-secondary">Keine Dateien gefunden.</div>';
      report(0);
      return;
    }
    if (!body.changed_count) {
      // Gruende (z. B. "Artist-Tag entspricht nicht dem gewaehlten
      // Ausgangswert", "Safety: ...") sichtbar machen statt zu
      // verschlucken - sonst bleibt ein tag-/verzeichnis-abweichender
      // Artist ohne jeden Hinweis bei "keine Aenderung noetig" haengen.
      const reasons = [...new Set(body.outcomes.map((o) => o.reason).filter(Boolean))];
      const isGenuineNoop = reasons.length > 0 && reasons.every((r) => _NOOP_SKIP_REASONS.has(r));
      const reasonHtml = reasons.length
        ? '<ul class="list-unstyled mb-0 mt-2">' + reasons.map((r) => `
            <li class="text-secondary small text-break">${ccIcon("info", "icon-sm me-1")}${_escapeHtml(r)}</li>
          `).join("") + "</ul>"
        : "";
      const headline = isGenuineNoop
        ? `${body.target_count} Datei(en) — keine Änderung nötig.`
        : `${body.target_count} Datei(en) — wird übersprungen:`;
      el.innerHTML = `<div class="fw-medium">${headline}</div>${reasonHtml}`;
      report(0);
      return;
    }
    // CC-UI L3b: Diff steht UNTER dem Dateinamen (vorher .row-count daneben,
    // lief auf schmalen Bildschirmen über - FINDINGS_INDEX, U17).
    const rows = body.outcomes.filter((o) => o.status === "DRY_RUN").map((o) => `
      <div class="list-group-item py-2">
        <div class="text-truncate small" title="${_escapeHtml(o.file)}">${_escapeHtml(o.file)}</div>
        <div class="text-secondary small text-break">${_escapeHtml(_diffSummary(o.before, o.after))}</div>
      </div>
    `).join("");
    el.innerHTML = '<div class="d-flex align-items-center gap-2 mb-2"><span class="badge bg-teal-lt">Vorschau</span>'
      + '<span class="text-secondary small">nichts geschrieben</span></div>'
      + `<div class="fw-medium mb-2">${body.changed_count} von ${body.target_count} Datei(en) werden geändert:</div><div class="list-group">${rows}</div>`;
    report(body.changed_count);
  }

  // ── CC-UI L4: automatische Vorschau ────────────────────────────────────
  // Die Vorschau-Endpunkte sind read-only (dry_run=True, kein Backup, das
  // Journal wird nie geschrieben) - deshalb darf sie beim Tippen laufen,
  // verzögert um _AUTO_PREVIEW_MS nach der letzten Eingabe. Ältere Antworten
  // werden über eine Laufnummer je Vorschau verworfen (kein Überschreiben
  // einer neueren Vorschau durch eine langsamere alte).
  const _AUTO_PREVIEW_MS = 600;
  const _previewSeq = {};
  const _previewTimers = {};

  function _nextPreviewSeq(key) {
    _previewSeq[key] = (_previewSeq[key] || 0) + 1;
    return _previewSeq[key];
  }

  function _isCurrentPreview(key, seq) {
    return _previewSeq[key] === seq;
  }

  function _schedulePreview(key, fn) {
    clearTimeout(_previewTimers[key]);
    _previewTimers[key] = setTimeout(fn, _AUTO_PREVIEW_MS);
  }

  function _noChangeHtml(text) {
    return `<div class="text-secondary small">${ccIcon("info", "icon-sm me-1")}${_escapeHtml(text)}</div>`;
  }

  // -- Artist bearbeiten ---------------------------------------------------

  async function loadArtistEditPreview() {
    const artist = currentArtistFromPath();
    const newArtist = document.getElementById("artist-edit-new-artist").value.trim();
    if (!newArtist) { _fieldHint("artist-edit-new-artist", "Bitte neuen Artist-Namen eingeben."); return; }
    document.getElementById("artist-edit-execute-btn").disabled = true;
    document.getElementById("artist-edit-result-content").innerHTML = "";
    const params = new URLSearchParams({ artist, new_artist: newArtist }).toString();
    const seq = _nextPreviewSeq("artist");
    await _loadInto(
      "artist-edit-content",
      `/api/v1/admin/maintenance/artist-rename/preview?${params}`,
      (el, body) => { if (_isCurrentPreview("artist", seq)) renderMetadataEditPreview(el, body, "artist-edit-execute-btn"); },
    );
  }

  // CC-UI L4: Vorschau automatisch beim Tippen; leer/unverändert -> Hinweis
  // statt Request (der Pflichtfeld-Hinweis bleibt dem expliziten Klick).
  function _autoArtistPreview() {
    const content = document.getElementById("artist-edit-content");
    const value = document.getElementById("artist-edit-new-artist").value.trim();
    _setExecuteButton(document.getElementById("artist-edit-execute-btn"), 0);
    _nextPreviewSeq("artist");
    clearTimeout(_previewTimers.artist);
    if (!value || value === currentArtistFromPath()) {
      content.innerHTML = _noChangeHtml(value
        ? "Entspricht dem aktuellen Namen — keine Änderung."
        : "Neuen Namen eingeben — die Vorschau erscheint automatisch.");
      return;
    }
    content.innerHTML = _runningHtml("Vorschau wird berechnet…");
    _schedulePreview("artist", loadArtistEditPreview);
  }

  // Preview<->Execute-Kopplung: eine Feldaenderung NACH einer geladenen
  // Preview macht deren Diff ungueltig (Nutzer wuerde sonst einen anderen
  // Wert schreiben als angezeigt) - Execute-Button wird deshalb wieder
  // deaktiviert, bis erneut "Vorschau laden" gedrueckt wurde.
  document.getElementById("artist-edit-new-artist").addEventListener("input", () => {
    document.getElementById("artist-edit-execute-btn").disabled = true;
    _autoArtistPreview();
  });

  async function executeArtistEdit() {
    const artist = currentArtistFromPath();
    const newArtist = document.getElementById("artist-edit-new-artist").value.trim();
    if (!newArtist) return;
    const confirmed = await _artistConfirm(
      `Artist "${artist}" wirklich zu "${newArtist}" umbenennen?\n\n` +
      `Mit Backup abgesichert (SHA-256-/Audio-Essenz-Verifikation vor dem Schreiben) — ` +
      `aber es werden tatsächlich Dateien in der Library verändert.`
    );
    if (!confirmed) return;

    const execBtn = document.getElementById("artist-edit-execute-btn");
    const resultEl = document.getElementById("artist-edit-result-content");
    execBtn.disabled = true;
    resultEl.innerHTML = _runningHtml("Wird ausgeführt…");
    try {
      const res = await fetch(apiUrl("/api/v1/admin/maintenance/artist-rename/execute"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ artist, new_artist: newArtist }),
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      const body = await res.json();
      if (!res.ok) {
        resultEl.innerHTML = _resultAlert("danger", `Fehler: ${_escapeHtml((body.error && body.error.message) || String(res.status))}`);
        return;
      }
      // KEINE Navigation: apply_artist_rename() ist tag-wert-getrieben
      // (services/library_repair/executor.py::apply_artist_rename()) -
      // es wird NUR der ©ART/ARTISTS-Tag geschrieben, der Artist-
      // Verzeichnisname (der diese Seite adressiert) bleibt unveraendert.
      // Ein Redirect auf /library/{newArtist} waere ein garantierter
      // 404, da dieser Verzeichnisname nie existiert.
      // Erst Vorschau neu laden (sie leert das Ergebnisfeld), dann das Ergebnis
      // zeigen - vorher verschwand die Erfolgsmeldung sofort wieder (CC-UI L3b).
      const resultHtml = _executeResultHtml(body,
        `Nur die Tag-Werte wurden geschrieben — der Artist-Ordner „${_escapeHtml(artist)}" bleibt unverändert. ` +
        `Diese Übersicht stammt aus dem zwischengespeicherten Health-Report; ein Neuscan (Telegram „MusicBot Doctor" oder CLI) zeigt den neuen Tag-Wert.`);
      await loadArtistEditPreview();
      resultEl.innerHTML = resultHtml;
      _executeToast(body);
    } catch (err) {
      resultEl.innerHTML = _resultAlert("danger", `Ergebnis unbekannt — bitte Seite neu laden bzw. Repair-Journal prüfen (${_escapeHtml(err.message)}).`);
    } finally {
      execBtn.disabled = false;
    }
  }

  document.getElementById("artist-edit-preview-btn").addEventListener("click", loadArtistEditPreview);
  document.getElementById("artist-edit-execute-btn").addEventListener("click", executeArtistEdit);

  // -- Titel bearbeiten -----------------------------------------------------
  //
  // Auftrag §6.2 CC-LIB-FINAL: kein manuell einzutippender technischer
  // relativer Dateipfad mehr - der Track kommt aus dem bestehenden
  // Library-Kontext (title-edit-track-select, siehe
  // _artistTrackOptionGroups()/_populateTrackPickers() oben). Der
  // Options-Wert bleibt intern relative_path (unveraendertes API-
  // Vertrag), die Anzeige (Auswahlliste + Bestaetigungsdialog) zeigt
  // ausschliesslich Tracknamen/Album-Kontext. Der Server bleibt die
  // eigentliche Schranke (maintenance_service.py::_title_edit_targets()
  // Containment-Pruefung) - kein Client-seitiger Scope-Guard mehr noetig,
  // da die Auswahl strukturell nur Tracks dieses Artists enthaelt.

  const _titleState = { counts: { title: 0, track_number: 0 } };

  function _updateTrackNumberHint(relPath) {
    const el = document.getElementById("track-number-edit-hint");
    if (!el) return;
    const t = _artistDetailTracksByPath[relPath];
    if (!t) { el.textContent = ""; return; }
    const artist = currentArtistFromPath();
    const albumKey = _trackAlbumValue(artist, t);
    const used = Object.values(_artistDetailTracksByPath)
      .filter((x) => _trackAlbumValue(artist, x) === albumKey && x.track_number)
      .map((x) => x.track_number)
      .sort((a, b) => a - b);
    const unique = [...new Set(used)];
    el.textContent = unique.length ? `Belegt: ${unique.join(", ")}` : "";
  }

  function _updateTitleExecuteBtn() {
    _setExecuteButton(document.getElementById("title-edit-execute-btn"),
      Math.max(
        _titleState.counts.title || 0,
        _titleState.counts.track_number || 0,
      ));
  }

  function _titleEditTrackLabel(relPath) {
    const t = _artistDetailTracksByPath[relPath];
    return t ? (t.title || t.filename) : relPath;
  }

  async function loadTitleEditPreview() {
    const artist = currentArtistFromPath();
    const relPath = document.getElementById("title-edit-track-select").value;
    const newTitle = document.getElementById("title-edit-new-title").value.trim();
    if (!relPath) { _fieldHint("title-edit-track-select", "Bitte Track wählen."); return; }
    if (!newTitle) { _fieldHint("title-edit-new-title", "Bitte neuen Titel eingeben."); return; }
    document.getElementById("title-edit-execute-btn").disabled = true;
    document.getElementById("title-edit-result-content").innerHTML = "";
    const params = new URLSearchParams({ artist, rel_path: relPath, new_title: newTitle }).toString();
    const seq = _nextPreviewSeq("title");
    await _loadInto(
      "title-edit-content",
      `/api/v1/admin/maintenance/title-edit/preview?${params}`,
      (el, body) => { if (_isCurrentPreview("title", seq)) renderMetadataEditPreview(el, body, null, (n) => { _titleState.counts.title = n; _updateTitleExecuteBtn(); }); },
    );
  }

  async function loadTrackNumberEditPreview() {
    const artist = currentArtistFromPath();
    const relPath = document.getElementById("title-edit-track-select").value;
    const raw = document.getElementById("track-number-edit-new-number").value.trim();
    if (!relPath) { _fieldHint("title-edit-track-select", "Bitte Track wählen."); return; }
    if (!raw) { _fieldHint("track-number-edit-new-number", "Bitte neue Tracknummer eingeben."); return; }
    _titleState.counts.track_number = 0;
    _updateTitleExecuteBtn();
    document.getElementById("track-number-edit-result-content").innerHTML = "";
    const params = new URLSearchParams({ artist, rel_path: relPath, new_track_number: raw }).toString();
    const seq = _nextPreviewSeq("track_number");
    await _loadInto(
      "track-number-edit-content",
      `/api/v1/admin/maintenance/track-number-edit/preview?${params}`,
      (el, body) => {
        if (!_isCurrentPreview("track_number", seq)) return;
        renderMetadataEditPreview(el, body, null, (n) => { _titleState.counts.track_number = n; _updateTitleExecuteBtn(); });
      },
    );
  }

  function _autoTitlePreview() {
    const content = document.getElementById("title-edit-content");
    const relPath = document.getElementById("title-edit-track-select").value;
    const value = document.getElementById("title-edit-new-title").value.trim();
    const t = _artistDetailTracksByPath[relPath];
    _titleState.counts.title = 0;
    _updateTitleExecuteBtn();
    _nextPreviewSeq("title");
    clearTimeout(_previewTimers.title);
    if (!relPath || !value || (t && value === (t.title || ""))) {
      content.innerHTML = _noChangeHtml(!value ? "Neuen Titel eingeben — die Vorschau erscheint automatisch."
        : "Entspricht dem aktuellen Titel — keine Änderung.");
      return;
    }
    content.innerHTML = _runningHtml("Vorschau wird berechnet…");
    _schedulePreview("title", loadTitleEditPreview);
  }

  function _autoTrackNumberPreview() {
    const content = document.getElementById("track-number-edit-content");
    const relPath = document.getElementById("title-edit-track-select").value;
    const value = document.getElementById("track-number-edit-new-number").value.trim();
    const t = _artistDetailTracksByPath[relPath];
    _titleState.counts.track_number = 0;
    _updateTitleExecuteBtn();
    _nextPreviewSeq("track_number");
    clearTimeout(_previewTimers.track_number);
    if (!relPath || !value || (t && Number(value) === Number(t.track_number))) {
      content.innerHTML = _noChangeHtml(!value ? "Tracknummer eingeben — die Vorschau erscheint automatisch."
        : "Entspricht der aktuellen Tracknummer — keine Änderung.");
      return;
    }
    content.innerHTML = _runningHtml("Vorschau wird berechnet…");
    _schedulePreview("track_number", loadTrackNumberEditPreview);
  }

  async function executeTitleEdit(opts = {}) {
    const artist = currentArtistFromPath();
    const relPath = document.getElementById("title-edit-track-select").value;
    const newTitle = document.getElementById("title-edit-new-title").value.trim();
    if (!relPath || !newTitle) return;
    if (!opts.skipConfirm) {
      const confirmed = await _artistConfirm(
        `Titel für "${_titleEditTrackLabel(relPath)}" wirklich zu "${newTitle}" ändern?\n\n` +
        `Mit Backup abgesichert (SHA-256-/Audio-Essenz-Verifikation vor dem Schreiben) — ` +
        `aber es wird tatsächlich eine Datei in der Library verändert.`
      );
      if (!confirmed) return;
    }

    const execBtn = document.getElementById("title-edit-execute-btn");
    const resultEl = document.getElementById("title-edit-result-content");
    execBtn.disabled = true;
    resultEl.innerHTML = _runningHtml("Wird ausgeführt…");
    try {
      const res = await fetch(apiUrl("/api/v1/admin/maintenance/title-edit/execute"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ artist, rel_path: relPath, new_title: newTitle }),
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      const body = await res.json();
      if (!res.ok) {
        resultEl.innerHTML = _resultAlert("danger", `Fehler: ${_escapeHtml((body.error && body.error.message) || String(res.status))}`);
        return;
      }
      // Erst Vorschau neu laden (sie leert das Ergebnisfeld), dann das Ergebnis
      // zeigen - vorher verschwand die Erfolgsmeldung sofort wieder (CC-UI L3b).
      const resultHtml = _executeResultHtml(body, `Die Trackliste unten stammt aus dem zwischengespeicherten Health-Report und zeigt den neuen Titel erst nach einem Neuscan.`);
      await loadTitleEditPreview();
      resultEl.innerHTML = resultHtml;
      _executeToast(body);
    } catch (err) {
      resultEl.innerHTML = _resultAlert("danger", `Ergebnis unbekannt — bitte Seite neu laden bzw. Repair-Journal prüfen (${_escapeHtml(err.message)}).`);
    } finally {
      execBtn.disabled = false;
    }
  }

  async function executeTrackNumberEdit(opts = {}) {
    const artist = currentArtistFromPath();
    const relPath = document.getElementById("title-edit-track-select").value;
    const raw = document.getElementById("track-number-edit-new-number").value.trim();
    if (!relPath || !raw) return;
    if (!opts.skipConfirm) {
      const confirmed = await _artistConfirm(
        `Tracknummer für "${_titleEditTrackLabel(relPath)}" wirklich auf "${raw}" setzen?\n\n` +
        `Mit Backup abgesichert (SHA-256-/Audio-Essenz-Verifikation vor dem Schreiben) — ` +
        `aber es wird tatsächlich eine Datei in der Library verändert.`
      );
      if (!confirmed) return;
    }

    const execBtn = document.getElementById("title-edit-execute-btn");
    const resultEl = document.getElementById("track-number-edit-result-content");
    execBtn.disabled = true;
    resultEl.innerHTML = _runningHtml("Wird ausgeführt…");
    try {
      const res = await fetch(apiUrl("/api/v1/admin/maintenance/track-number-edit/execute"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ artist, rel_path: relPath, new_track_number: Number(raw) }),
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      const body = await res.json();
      if (!res.ok) {
        resultEl.innerHTML = _resultAlert("danger", `Fehler: ${_escapeHtml((body.error && body.error.message) || String(res.status))}`);
        return;
      }
      const resultHtml = _executeResultHtml(body, `Nur die Tracknummer (trkn) wurde geschrieben — die Trackliste unten stammt aus dem zwischengespeicherten Health-Report und zeigt den neuen Wert erst nach einem Neuscan.`);
      await loadTrackNumberEditPreview();
      resultEl.innerHTML = resultHtml;
      _executeToast(body);
    } catch (err) {
      resultEl.innerHTML = _resultAlert("danger", `Ergebnis unbekannt — bitte Seite neu laden bzw. Repair-Journal prüfen (${_escapeHtml(err.message)}).`);
    } finally {
      _updateTitleExecuteBtn();
    }
  }

  // Ein "Übernehmen" für den Track-Block: eine Bestätigung, dann nur die
  // geaenderten Felder schreiben (Titel zuerst, dann Tracknummer).
  async function executeTitleTab() {
    const relPath = document.getElementById("title-edit-track-select").value;
    const doTitle = _titleState.counts.title > 0;
    const doTrackNumber = _titleState.counts.track_number > 0;
    if (!relPath || (!doTitle && !doTrackNumber)) return;
    if (doTitle && doTrackNumber) {
      // Beide Felder: eine gemeinsame Bestaetigung, dann nacheinander.
      const newTitle = document.getElementById("title-edit-new-title").value.trim();
      const newNumber = document.getElementById("track-number-edit-new-number").value.trim();
      const t = _artistDetailTracksByPath[relPath];
      const lines = [
        `Titel: "${(t && t.title) || ""}" → "${newTitle}"`,
        `Tracknummer: ${(t && t.track_number) || "—"} → ${newNumber}`,
      ];
      const confirmed = await _artistConfirm(
        `Track "${_titleEditTrackLabel(relPath)}" wirklich ändern?\n\n` + lines.join("\n") + "\n\n" +
        `Mit Backup abgesichert (SHA-256-/Audio-Essenz-Verifikation vor dem Schreiben) — ` +
        `aber es werden tatsächlich Dateien in der Library verändert.`
      );
      if (!confirmed) return;
      await executeTitleEdit({ skipConfirm: true });
      await executeTrackNumberEdit({ skipConfirm: true });
      return;
    }
    if (doTitle) return executeTitleEdit();
    return executeTrackNumberEdit();
  }

  document.getElementById("title-edit-preview-btn").addEventListener("click", loadTitleEditPreview);
  document.getElementById("track-number-edit-preview-btn").addEventListener("click", loadTrackNumberEditPreview);
  document.getElementById("title-edit-execute-btn").addEventListener("click", executeTitleTab);
  document.getElementById("title-edit-new-title").addEventListener("input", () => {
    document.getElementById("title-edit-execute-btn").disabled = true;
    _autoTitlePreview();
  });
  document.getElementById("track-number-edit-new-number").addEventListener("input", () => {
    document.getElementById("title-edit-execute-btn").disabled = true;
    _autoTrackNumberPreview();
  });
  document.getElementById("title-edit-track-select").addEventListener("input", () => {
    document.getElementById("title-edit-execute-btn").disabled = true;
    _autoTitlePreview();
    _autoTrackNumberPreview();
  });

  // -- Album bearbeiten (Manual Metadata Editing v2, CC-AC-3) --------------
  //
  // Reine Verdrahtung der bestehenden Endpunkte
  // POST /api/v1/admin/maintenance/album-edit/{preview,execute}
  // (control_center/routers/admin_maintenance.py ->
  // services/library_repair/maintenance_service.py::
  // preview_album_edit()/execute_album_edit()) - identisches Preview-
  // >Confirm->Execute-Muster wie Artist/Titel oben, Album-Auswahl ueber
  // den Picker aus _artistAlbumOptions() statt eines Freitext-Pfads.

  // CC-UI L4 (Nutzerfreigabe): Albumname und Albuminterpret stehen in EINEM
  // Reiter mit EINEM "Übernehmen". Beide Felder sind mit den aktuellen
  // Tag-Werten des gewählten Albums vorbelegt; geändert wird nur, was vom
  // aktuellen Wert abweicht (zwei bestehende Endpunkte nacheinander, eine
  // Bestätigung). Das versteckte Feld albumartist-edit-album-select hält
  // denselben Album-Schlüssel wie die sichtbare Auswahl.
  const _albumState = { current: { album: "", albumartist: "", year: "" }, counts: { album: 0, albumartist: 0, year: 0 } };

  function _mostCommon(values) {
    const counts = new Map();
    values.filter((v) => v).forEach((v) => counts.set(v, (counts.get(v) || 0) + 1));
    let best = "";
    let bestN = 0;
    counts.forEach((n, v) => { if (n > bestN) { best = v; bestN = n; } });
    return best;
  }

  function _albumCurrentValues(albumKey) {
    const artist = currentArtistFromPath();
    const tracks = Object.values(_artistDetailTracksByPath).filter((t) => _trackAlbumValue(artist, t) === albumKey);
    return {
      album: _mostCommon(tracks.map((t) => t.album)),
      albumartist: _mostCommon(tracks.map((t) => t.album_artist)),
      // D2: Volldaten ("2024-05-17") auf 4 Zeichen kuerzen fuer die Vorbelegung.
      year: _mostCommon(tracks.map((t) => ("" + (t.year || "")).slice(0, 4))),
    };
  }

  // Beide Felder betreffen dieselben Dateien des Albums -> Anzahl Dateien =
  // Maximum der beiden Vorschauen (nicht die Summe).
  function _updateAlbumExecuteBtn() {
    _setExecuteButton(document.getElementById("album-edit-execute-btn"),
      Math.max(
        _albumState.counts.album || 0,
        _albumState.counts.albumartist || 0,
        _albumState.counts.year || 0,
      ));
  }

  // Album gewählt: versteckte Auswahl synchronisieren, Felder vorbelegen.
  function _selectAlbumForEdit(albumKey) {
    document.getElementById("album-edit-album-select").value = albumKey;
    document.getElementById("albumartist-edit-album-select").value = albumKey;
    _albumState.current = albumKey ? _albumCurrentValues(albumKey) : { album: "", albumartist: "", year: "" };
    document.getElementById("album-edit-new-album").value = _albumState.current.album;
    document.getElementById("albumartist-edit-new-albumartist").value = _albumState.current.albumartist;
    document.getElementById("year-edit-new-year").value = _albumState.current.year;
    document.getElementById("album-edit-result-content").innerHTML = "";
    document.getElementById("albumartist-edit-result-content").innerHTML = "";
    document.getElementById("year-edit-result-content").innerHTML = "";
    _autoAlbumPreview("album");
    _autoAlbumPreview("albumartist");
    _autoAlbumPreview("year");
  }

  async function loadAlbumEditPreview() {
    const artist = currentArtistFromPath();
    const album = document.getElementById("album-edit-album-select").value;
    const newAlbum = document.getElementById("album-edit-new-album").value.trim();
    if (!album) { _fieldHint("album-edit-album-select", "Bitte zuerst ein Album auswählen."); return; }
    if (!newAlbum) { _fieldHint("album-edit-new-album", "Bitte neuen Albumnamen eingeben."); return; }
    _albumState.counts.album = 0;
    _updateAlbumExecuteBtn();
    document.getElementById("album-edit-result-content").innerHTML = "";
    const params = new URLSearchParams({ artist, album, new_album: newAlbum }).toString();
    const seq = _nextPreviewSeq("album");
    await _loadInto(
      "album-edit-content",
      `/api/v1/admin/maintenance/album-edit/preview?${params}`,
      (el, body) => {
        if (!_isCurrentPreview("album", seq)) return;
        renderMetadataEditPreview(el, body, null, (n) => { _albumState.counts.album = n; _updateAlbumExecuteBtn(); });
      },
    );
  }

  async function loadAlbumArtistEditPreview() {
    const artist = currentArtistFromPath();
    const album = document.getElementById("albumartist-edit-album-select").value;
    const newAlbumArtist = document.getElementById("albumartist-edit-new-albumartist").value.trim();
    if (!album) { _fieldHint("album-edit-album-select", "Bitte zuerst ein Album auswählen."); return; }
    if (!newAlbumArtist) { _fieldHint("albumartist-edit-new-albumartist", "Bitte neuen Albuminterpret eingeben."); return; }
    _albumState.counts.albumartist = 0;
    _updateAlbumExecuteBtn();
    document.getElementById("albumartist-edit-result-content").innerHTML = "";
    const params = new URLSearchParams({ artist, album, new_album_artist: newAlbumArtist }).toString();
    const seq = _nextPreviewSeq("albumartist");
    await _loadInto(
      "albumartist-edit-content",
      `/api/v1/admin/maintenance/albumartist-edit/preview?${params}`,
      (el, body) => {
        if (!_isCurrentPreview("albumartist", seq)) return;
        renderMetadataEditPreview(el, body, null, (n) => { _albumState.counts.albumartist = n; _updateAlbumExecuteBtn(); });
      },
    );
  }

  async function loadYearEditPreview() {
    const artist = currentArtistFromPath();
    const album = document.getElementById("album-edit-album-select").value;
    const newYear = document.getElementById("year-edit-new-year").value.trim();
    if (!album) { _fieldHint("album-edit-album-select", "Bitte zuerst ein Album auswählen."); return; }
    if (!newYear) { _fieldHint("year-edit-new-year", "Bitte neues Jahr eingeben."); return; }
    _albumState.counts.year = 0;
    _updateAlbumExecuteBtn();
    document.getElementById("year-edit-result-content").innerHTML = "";
    const params = new URLSearchParams({ artist, album, new_year: newYear }).toString();
    const seq = _nextPreviewSeq("year");
    await _loadInto(
      "year-edit-content",
      `/api/v1/admin/maintenance/year-edit/preview?${params}`,
      (el, body) => {
        if (!_isCurrentPreview("year", seq)) return;
        renderMetadataEditPreview(el, body, null, (n) => { _albumState.counts.year = n; _updateAlbumExecuteBtn(); });
      },
    );
  }

  // Vorschau je Feld automatisch - nur wenn der Wert vom aktuellen abweicht.
  const _albumFieldConfig = {
    album: { contentId: "album-edit-content", inputId: "album-edit-new-album", label: "Albumname", loader: loadAlbumEditPreview },
    albumartist: { contentId: "albumartist-edit-content", inputId: "albumartist-edit-new-albumartist", label: "Albuminterpret", loader: loadAlbumArtistEditPreview },
    year: { contentId: "year-edit-content", inputId: "year-edit-new-year", label: "Jahr", loader: loadYearEditPreview },
  };

  function _autoAlbumPreview(field) {
    const cfg = _albumFieldConfig[field];
    const content = document.getElementById(cfg.contentId);
    const albumKey = document.getElementById("album-edit-album-select").value;
    const value = document.getElementById(cfg.inputId).value.trim();
    _albumState.counts[field] = 0;
    _updateAlbumExecuteBtn();
    _nextPreviewSeq(field);
    clearTimeout(_previewTimers[field]);
    if (!albumKey || !value || value === _albumState.current[field]) {
      content.innerHTML = albumKey ? _noChangeHtml(`${cfg.label}: keine Änderung.`) : "";
      return;
    }
    content.innerHTML = _runningHtml(`${cfg.label}: Vorschau wird berechnet…`);
    _schedulePreview(field, cfg.loader);
  }

  async function executeAlbumEdit(opts = {}) {
    const artist = currentArtistFromPath();
    const album = document.getElementById("album-edit-album-select").value;
    const newAlbum = document.getElementById("album-edit-new-album").value.trim();
    if (!album || !newAlbum) return;
    if (!opts.skipConfirm) {
      const confirmed = await _artistConfirm(
        `Album "${album}" wirklich zu "${newAlbum}" ändern?\n\n` +
        `Mit Backup abgesichert (SHA-256-/Audio-Essenz-Verifikation vor dem Schreiben) — ` +
        `aber es werden tatsächlich Dateien in der Library verändert.`
      );
      if (!confirmed) return;
    }

    const execBtn = document.getElementById("album-edit-execute-btn");
    const resultEl = document.getElementById("album-edit-result-content");
    execBtn.disabled = true;
    resultEl.innerHTML = _runningHtml("Wird ausgeführt…");
    try {
      const res = await fetch(apiUrl("/api/v1/admin/maintenance/album-edit/execute"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ artist, album, new_album: newAlbum }),
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      const body = await res.json();
      if (!res.ok) {
        resultEl.innerHTML = _resultAlert("danger", `Fehler: ${_escapeHtml((body.error && body.error.message) || String(res.status))}`);
        return;
      }
      // Erst Vorschau neu laden (sie leert das Ergebnisfeld), dann das Ergebnis
      // zeigen - vorher verschwand die Erfolgsmeldung sofort wieder (CC-UI L3b).
      const resultHtml = _executeResultHtml(body, `Nur der Album-Tag (©alb) wurde geschrieben — der Alben-Eintrag oben zeigt weiterhin den Verzeichnisnamen und bleibt unverändert; die Track-Liste unten übernimmt den neuen Wert erst nach einem Neuscan.`);
      _albumState.current.album = newAlbum;
      await loadAlbumEditPreview();
      resultEl.innerHTML = resultHtml;
      _executeToast(body);
    } catch (err) {
      resultEl.innerHTML = _resultAlert("danger", `Ergebnis unbekannt — bitte Seite neu laden bzw. Repair-Journal prüfen (${_escapeHtml(err.message)}).`);
    } finally {
      _updateAlbumExecuteBtn();
    }
  }

  async function executeAlbumArtistEdit(opts = {}) {
    const artist = currentArtistFromPath();
    const album = document.getElementById("albumartist-edit-album-select").value;
    const newAlbumArtist = document.getElementById("albumartist-edit-new-albumartist").value.trim();
    if (!album || !newAlbumArtist) return;
    if (!opts.skipConfirm) {
      const confirmed = await _artistConfirm(
        `Albuminterpret für Album "${album}" wirklich zu "${newAlbumArtist}" ändern?\n\n` +
        `Mit Backup abgesichert (SHA-256-/Audio-Essenz-Verifikation vor dem Schreiben) — ` +
        `aber es werden tatsächlich Dateien in der Library verändert.`
      );
      if (!confirmed) return;
    }

    const execBtn = document.getElementById("album-edit-execute-btn");
    const resultEl = document.getElementById("albumartist-edit-result-content");
    execBtn.disabled = true;
    resultEl.innerHTML = _runningHtml("Wird ausgeführt…");
    try {
      const res = await fetch(apiUrl("/api/v1/admin/maintenance/albumartist-edit/execute"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ artist, album, new_album_artist: newAlbumArtist }),
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      const body = await res.json();
      if (!res.ok) {
        resultEl.innerHTML = _resultAlert("danger", `Fehler: ${_escapeHtml((body.error && body.error.message) || String(res.status))}`);
        return;
      }
      // Erst Vorschau neu laden (sie leert das Ergebnisfeld), dann das Ergebnis
      // zeigen - vorher verschwand die Erfolgsmeldung sofort wieder (CC-UI L3b).
      const resultHtml = _executeResultHtml(body, `Nur der Albuminterpret-Tag (aART) wurde geschrieben — er wird in der Alben-/Track-Übersicht oben aktuell gar nicht angezeigt, auch nicht nach einem Neuscan.`);
      _albumState.current.albumartist = newAlbumArtist;
      await loadAlbumArtistEditPreview();
      resultEl.innerHTML = resultHtml;
      _executeToast(body);
    } catch (err) {
      resultEl.innerHTML = _resultAlert("danger", `Ergebnis unbekannt — bitte Seite neu laden bzw. Repair-Journal prüfen (${_escapeHtml(err.message)}).`);
    } finally {
      _updateAlbumExecuteBtn();
    }
  }

  async function executeYearEdit(opts = {}) {
    const artist = currentArtistFromPath();
    const album = document.getElementById("album-edit-album-select").value;
    const newYear = document.getElementById("year-edit-new-year").value.trim();
    if (!album || !newYear) return;
    if (!opts.skipConfirm) {
      const confirmed = await _artistConfirm(
        `Jahr für Album "${album}" wirklich zu "${newYear}" ändern?\n\n` +
        `Mit Backup abgesichert (SHA-256-/Audio-Essenz-Verifikation vor dem Schreiben) — ` +
        `aber es werden tatsächlich Dateien in der Library verändert.`
      );
      if (!confirmed) return;
    }

    const execBtn = document.getElementById("album-edit-execute-btn");
    const resultEl = document.getElementById("year-edit-result-content");
    execBtn.disabled = true;
    resultEl.innerHTML = _runningHtml("Wird ausgeführt…");
    try {
      const res = await fetch(apiUrl("/api/v1/admin/maintenance/year-edit/execute"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ artist, album, new_year: newYear }),
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      const body = await res.json();
      if (!res.ok) {
        resultEl.innerHTML = _resultAlert("danger", `Fehler: ${_escapeHtml((body.error && body.error.message) || String(res.status))}`);
        return;
      }
      // Erst Vorschau neu laden (sie leert das Ergebnisfeld), dann das Ergebnis zeigen.
      const resultHtml = _executeResultHtml(body, `Nur der Jahr-Tag (©day) wurde geschrieben — der Dateiname bleibt unverändert (die Rename-Konvention übernimmt den Tag-Präfix erst nach einem Rename-Lauf).`);
      _albumState.current.year = newYear;
      await loadYearEditPreview();
      resultEl.innerHTML = resultHtml;
      _executeToast(body);
    } catch (err) {
      resultEl.innerHTML = _resultAlert("danger", `Ergebnis unbekannt — bitte Seite neu laden bzw. Repair-Journal prüfen (${_escapeHtml(err.message)}).`);
    } finally {
      _updateAlbumExecuteBtn();
    }
  }

  // Ein "Übernehmen" für alle Felder: eine Bestätigung, dann nur die
  // geänderten Felder schreiben (Album zuerst, dann Albuminterpret, dann Jahr).
  async function executeAlbumTab() {
    const album = document.getElementById("album-edit-album-select").value;
    const doAlbum = _albumState.counts.album > 0;
    const doAlbumArtist = _albumState.counts.albumartist > 0;
    const doYear = _albumState.counts.year > 0;
    if (!album || (!doAlbum && !doAlbumArtist && !doYear)) return;
    const newAlbum = document.getElementById("album-edit-new-album").value.trim();
    const newAlbumArtist = document.getElementById("albumartist-edit-new-albumartist").value.trim();
    const newYear = document.getElementById("year-edit-new-year").value.trim();
    const lines = [];
    if (doAlbum) lines.push(`Albumname: "${_albumState.current.album}" → "${newAlbum}" (${_albumState.counts.album} Dateien)`);
    if (doAlbumArtist) lines.push(`Albuminterpret: "${_albumState.current.albumartist}" → "${newAlbumArtist}" (${_albumState.counts.albumartist} Dateien)`);
    if (doYear) lines.push(`Jahr: "${_albumState.current.year}" → "${newYear}" (${_albumState.counts.year} Dateien)`);
    const confirmed = await _artistConfirm(
      `Album "${album}" wirklich ändern?\n\n` + lines.join("\n") + "\n\n" +
      `Mit Backup abgesichert (SHA-256-/Audio-Essenz-Verifikation vor dem Schreiben) — ` +
      `aber es werden tatsächlich Dateien in der Library verändert.`
    );
    if (!confirmed) return;
    if (doAlbum) await executeAlbumEdit({ skipConfirm: true });
    if (doAlbumArtist) await executeAlbumArtistEdit({ skipConfirm: true });
    if (doYear) await executeYearEdit({ skipConfirm: true });
  }

  document.getElementById("album-edit-preview-btn").addEventListener("click", loadAlbumEditPreview);
  document.getElementById("albumartist-edit-preview-btn").addEventListener("click", loadAlbumArtistEditPreview);
  document.getElementById("album-edit-execute-btn").addEventListener("click", executeAlbumTab);
  document.getElementById("album-edit-album-select").addEventListener("change", (event) => {
    _selectAlbumForEdit(event.target.value);
  });
  document.getElementById("album-edit-new-album").addEventListener("input", () => _autoAlbumPreview("album"));
  document.getElementById("year-edit-new-year").addEventListener("input", () => _autoAlbumPreview("year"));
  document.getElementById("year-edit-preview-btn").addEventListener("click", loadYearEditPreview);
  ["albumartist-edit-album-select", "albumartist-edit-new-albumartist"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => _autoAlbumPreview("albumartist"));
  });

  // -- Genre-Verwaltung -------------------------------------------------------

  async function loadGenreManagePreview() {
    const artist = currentArtistFromPath();
    document.getElementById("genre-manage-execute-btn").disabled = true;
    document.getElementById("genre-manage-result-content").innerHTML = "";
    await _loadInto(
      "genre-manage-content",
      `/api/v1/library/artists/${encodeURIComponent(artist)}/genre-preview`,
      (el, body) => renderMetadataEditPreview(el, body, "genre-manage-execute-btn"),
    );
  }

  async function executeGenreManage() {
    const artist = currentArtistFromPath();
    const confirmed = await _artistConfirm(
      `Genre für "${artist}" wirklich setzen?\n\n` +
      `Mit Backup abgesichert (SHA-256-/Audio-Essenz-Verifikation vor dem Schreiben) — ` +
      `aber es werden tatsächlich Dateien in der Library verändert.`
    );
    if (!confirmed) return;

    const execBtn = document.getElementById("genre-manage-execute-btn");
    const resultEl = document.getElementById("genre-manage-result-content");
    execBtn.disabled = true;
    resultEl.innerHTML = _runningHtml("Wird ausgeführt…");
    try {
      const res = await fetch(apiUrl(`/api/v1/library/artists/${encodeURIComponent(artist)}/set-genre`), {
        method: "POST",
        credentials: "same-origin",
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      const body = await res.json();
      if (!res.ok) {
        resultEl.innerHTML = _resultAlert("danger", `Fehler: ${_escapeHtml((body.error && body.error.message) || String(res.status))}`);
        return;
      }
      // Erst Vorschau neu laden (sie leert das Ergebnisfeld), dann das Ergebnis
      // zeigen - vorher verschwand die Erfolgsmeldung sofort wieder (CC-UI L3b).
      const resultHtml = _executeResultHtml(body);
      await loadGenreManagePreview();
      resultEl.innerHTML = resultHtml;
      _executeToast(body);
    } catch (err) {
      resultEl.innerHTML = _resultAlert("danger", `Ergebnis unbekannt — bitte Seite neu laden bzw. Repair-Journal prüfen (${_escapeHtml(err.message)}).`);
    } finally {
      execBtn.disabled = false;
    }
  }

  // -- Genre-Mapping bearbeiten (Primary + Secondary) -------------------------
  //
  // Bearbeitet EINEN Eintrag in mapping/artist_genre.yaml ueber
  // GET/POST-preview/PUT /api/v1/library/artists/{artist}/genre-mapping.
  // Ablauf: laden -> bearbeiten -> "Aenderung pruefen" (Vorschau, schreibt
  // nichts) -> "Mapping speichern" (Bestaetigung, Etag gegen veraltete Staende).
  // Die Tags der Dateien setzt weiter "Genre setzen" (genre-preview/set-genre).

  const _genreMap = { entry: null, etag: null, primary: "", secondary: [], previewed: null };

  function genreChipsHtml(list) {
    if (!list.length) return '<span class="text-secondary small">Keine Secondary-Genres.</span>';
    return list.map((g) => `<span class="badge bg-blue-lt d-inline-flex align-items-center gap-1">${_escapeHtml(g)}<button type="button" class="btn-close genre-chip-remove" data-genre="${_escapeHtml(g)}" aria-label="${_escapeHtml(g)} entfernen"></button></span>`).join("");
  }

  function renderGenreMappingPreview(body) {
    const changeText = {
      create: "Neuer Mapping-Eintrag wird angelegt.",
      update: "Bestehender Mapping-Eintrag wird aktualisiert.",
      unchanged: "Keine Änderung — das Mapping ist bereits so gesetzt.",
    }[body.change] || body.change;
    const primaryLine = !body.existing
      ? `Primary: <strong>${_escapeHtml(body.primary)}</strong>`
      : (body.primary_changed
        ? `Primary: ${_escapeHtml(body.existing.primary)} → <strong>${_escapeHtml(body.primary)}</strong>`
        : `Primary: <strong>${_escapeHtml(body.primary)}</strong> (unverändert)`);
    const removed = body.removed.map((g) => `<span class="badge bg-red-lt">− ${_escapeHtml(g)}</span>`).join(" ");
    const added = body.added.map((g) => `<span class="badge bg-green-lt">+ ${_escapeHtml(g)}</span>`).join(" ");
    const orderOnly = body.change === "update" && !body.removed.length && !body.added.length
      ? '<div class="text-secondary small">Nur die Reihenfolge ändert sich.</div>' : "";
    const warnings = body.warnings.map((w) => `<div class="alert alert-warning py-2 mb-2">${_escapeHtml(w)}</div>`).join("");
    const result = [body.primary, ...body.secondary].map(_escapeHtml).join("; ");
    return `
      <div class="card card-sm"><div class="card-body">
        <div class="fw-semibold mb-2">${_escapeHtml(changeText)}</div>
        <div class="mb-1">${primaryLine}</div>
        ${removed ? `<div class="mb-1">Entfernt: ${removed}</div>` : ""}
        ${added ? `<div class="mb-1">Neu: ${added}</div>` : ""}
        ${orderOnly}
        <div class="text-secondary small mt-2">Ergebnis im Mapping: ${result}</div>
      </div></div>
      ${warnings ? `<div class="mt-2">${warnings}</div>` : ""}`;
  }

  function _genreMappingSyncForm() {
    document.getElementById("genre-mapping-primary").value = _genreMap.primary;
    document.getElementById("genre-mapping-secondary").innerHTML = genreChipsHtml(_genreMap.secondary);
  }

  function _genreMappingInvalidate() {
    _genreMap.previewed = null;
    document.getElementById("genre-mapping-save-btn").disabled = true;
    document.getElementById("genre-mapping-preview-content").innerHTML = "";
    document.getElementById("genre-mapping-result-content").innerHTML = "";
  }

  function applyGenreMapping(el, body) {
    _genreMap.entry = body.entry;
    _genreMap.etag = body.etag;
    _genreMap.primary = body.entry ? body.entry.primary : "";
    _genreMap.secondary = body.entry ? body.entry.secondary.slice() : [];
    document.getElementById("genre-mapping-datalist").innerHTML =
      body.known_genres.map((g) => `<option value="${_escapeHtml(g)}"></option>`).join("");
    el.innerHTML = body.exists
      ? `<span class="text-secondary small">Mapping-Key: <code>${_escapeHtml(body.entry.key)}</code></span>`
      : '<span class="text-secondary small">Für diesen Artist gibt es noch kein Mapping — Genres eingeben, um eines anzulegen.</span>';
    document.getElementById("genre-mapping-form").hidden = false;
    _genreMappingSyncForm();
    _genreMappingInvalidate();
  }

  async function loadGenreMapping() {
    const artist = currentArtistFromPath();
    await _loadInto(
      "genre-mapping-status",
      `/api/v1/library/artists/${encodeURIComponent(artist)}/genre-mapping`,
      applyGenreMapping,
    );
  }

  function _genreMappingAdd() {
    const input = document.getElementById("genre-mapping-add-input");
    const value = input.value.replace(/\s+/g, " ").trim();
    if (!value) { input.value = ""; return; }
    const fold = value.toLowerCase();
    const exists = _genreMap.secondary.some((g) => g.toLowerCase() === fold) || _genreMap.primary.trim().toLowerCase() === fold;
    if (!exists) _genreMap.secondary.push(value);
    input.value = "";
    _genreMappingSyncForm();
    _genreMappingInvalidate();
  }

  function _genreMappingError(res, body) {
    return (body && body.error && body.error.message) || String(res.status);
  }

  async function previewGenreMapping() {
    const artist = currentArtistFromPath();
    const previewEl = document.getElementById("genre-mapping-preview-content");
    const saveBtn = document.getElementById("genre-mapping-save-btn");
    _genreMappingInvalidate();
    previewEl.innerHTML = _runningHtml("Wird geprüft…");
    try {
      const res = await fetch(apiUrl(`/api/v1/library/artists/${encodeURIComponent(artist)}/genre-mapping/preview`), {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ primary: _genreMap.primary, secondary: _genreMap.secondary }),
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        previewEl.innerHTML = `<div class="alert alert-danger mb-0">${_escapeHtml(_genreMappingError(res, body))}</div>`;
        return;
      }
      previewEl.innerHTML = renderGenreMappingPreview(body);
      _genreMap.previewed = { primary: body.primary, secondary: body.secondary, etag: body.etag, change: body.change };
      saveBtn.disabled = body.change === "unchanged";
    } catch (err) {
      previewEl.innerHTML = `<div class="alert alert-danger mb-0">Vorschau fehlgeschlagen (${_escapeHtml(err.message)}).</div>`;
    }
  }

  async function saveGenreMapping() {
    const pv = _genreMap.previewed;
    if (!pv) return;
    const artist = currentArtistFromPath();
    const confirmed = await _artistConfirm(
      `Genre-Mapping für "${artist}" wirklich ändern?\n\n` +
      `Neu: ${[pv.primary, ...pv.secondary].join("; ")}\n\n` +
      `Das schreibt mapping/artist_genre.yaml. Für neue Downloads wirkt es erst nach einem Bot-Neustart; ` +
      `bereits getaggte Dateien ändern sich erst über "Genre setzen".`
    );
    if (!confirmed) return;

    const saveBtn = document.getElementById("genre-mapping-save-btn");
    const resultEl = document.getElementById("genre-mapping-result-content");
    saveBtn.disabled = true;
    resultEl.innerHTML = _runningHtml("Wird gespeichert…");
    try {
      const res = await fetch(apiUrl(`/api/v1/library/artists/${encodeURIComponent(artist)}/genre-mapping`), {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ primary: pv.primary, secondary: pv.secondary, etag: pv.etag }),
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      const body = await res.json().catch(() => null);
      if (res.status === 409) {
        await loadGenreMapping();
        document.getElementById("genre-mapping-result-content").innerHTML =
          '<div class="alert alert-warning mb-0">Der Mapping-Eintrag wurde zwischenzeitlich geändert. Die aktuelle Fassung wurde geladen — bitte die Änderung erneut prüfen.</div>';
        return;
      }
      if (!res.ok) {
        resultEl.innerHTML = `<div class="alert alert-danger mb-0">${_escapeHtml(_genreMappingError(res, body))}</div>`;
        saveBtn.disabled = false;
        return;
      }
      await loadGenreMapping();
      document.getElementById("genre-mapping-result-content").innerHTML =
        `<div class="alert alert-${body.written ? "success" : "info"} mb-0">${_escapeHtml(body.message)}</div>`;
      if (body.written) await loadGenreManagePreview();  // zeigt sofort, was "Genre setzen" jetzt aendern wuerde
    } catch (err) {
      resultEl.innerHTML = `<div class="alert alert-danger mb-0">Ergebnis unbekannt — bitte neu laden und prüfen (${_escapeHtml(err.message)}).</div>`;
    }
  }

  document.getElementById("genre-mapping-primary").addEventListener("input", (event) => {
    _genreMap.primary = event.target.value;
    _genreMappingInvalidate();
  });
  document.getElementById("genre-mapping-add-btn").addEventListener("click", _genreMappingAdd);
  document.getElementById("genre-mapping-add-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); _genreMappingAdd(); }
  });
  document.getElementById("genre-mapping-secondary").addEventListener("click", (event) => {
    const btn = event.target.closest(".genre-chip-remove");
    if (!btn) return;
    _genreMap.secondary = _genreMap.secondary.filter((g) => g !== btn.dataset.genre);
    _genreMappingSyncForm();
    _genreMappingInvalidate();
  });
  document.getElementById("genre-mapping-reset-btn").addEventListener("click", () => {
    _genreMap.primary = _genreMap.entry ? _genreMap.entry.primary : "";
    _genreMap.secondary = _genreMap.entry ? _genreMap.entry.secondary.slice() : [];
    _genreMappingSyncForm();
    _genreMappingInvalidate();
  });
  document.getElementById("genre-mapping-preview-btn").addEventListener("click", previewGenreMapping);
  document.getElementById("genre-mapping-save-btn").addEventListener("click", saveGenreMapping);
  // Lazy: erst beim Öffnen des Genre-Reiters laden (kein Request pro
  // Seitenaufruf) - siehe _showMetaTab().

  // -- Genre revalidieren (Last.fm + Overturn-Regel, als Job) -----------------
  //
  // POST /api/v1/jobs/genre-revalidation-preview | -apply (Job, Polling wie bei
  // L2/L3). Die Entscheidung trifft der Service (dieselbe Overturn-Regel wie
  // Telegram/CLI); die UI zeigt nur das Ergebnis. Kein Abbrechen (ein einzelner
  // atomarer Lauf, siehe jobs.py).

  const _GENRE_REVAL_OUTCOMES = {
    BLOCKED_MANUAL: ["warning", "Blockiert — manuelles Mapping vorhanden"],
    NO_CANDIDATE: ["warning", "Kein Kandidat"],
    SAME_GENRE: ["success", "Last.fm bestätigt das aktuelle Genre — keine Änderung nötig"],
    OVERTURN_REJECTED: ["warning", "Änderung abgelehnt — Overturn-Regel nicht erfüllt"],
    OVERTURN_ALLOWED: ["info", "Änderung zulässig"],
  };
  let _genreRevalTimer = null;
  let _genreRevalJobId = null;

  function _genreLine(primary, secondary) {
    if (!primary) return "(kein Genre)";
    return [primary, ...(secondary || [])].map(_escapeHtml).join("; ");
  }

  function genreRevalidationResultHtml(r) {
    const [kind, label] = _GENRE_REVAL_OUTCOMES[r.outcome] || ["secondary", r.outcome];
    const rows = [
      ["Aktuell", _genreLine(r.current_primary, r.current_secondary)],
      ["Kandidat (Last.fm)", r.candidate_primary ? _genreLine(r.candidate_primary, r.candidate_secondary) : "—"],
    ];
    if (r.learning_status) rows.push(["Lernstatus", _escapeHtml(r.learning_status)]);
    if (r.locked_primary) rows.push(["Gelocktes Primary", _escapeHtml(r.locked_primary)]);
    rows.push(["Beobachtungen", _escapeHtml(String(r.observation_count))]);
    const dl = rows.map(([k, v]) => `<dt class="col-5 col-md-3">${_escapeHtml(k)}</dt><dd class="col-7 col-md-9 mb-1 text-break">${v}</dd>`).join("");
    const error = r.error_message
      ? `<div class="alert alert-danger py-2 mb-2">Last.fm-Fehler: ${_escapeHtml(r.error_message)}</div>` : "";
    let outcomeNote;
    if (r.mode === "apply") {
      outcomeNote = r.mutated
        ? `<div class="alert alert-success py-2 mb-0">${ccIcon("check", "me-1")}Gelerntes Genre aktualisiert. Für neue Downloads wirksam nach einem Bot-Neustart; Audio-Dateien wurden nicht verändert.</div>`
        : '<div class="text-secondary small">Keine Änderung geschrieben.</div>';
    } else {
      outcomeNote = '<div class="text-secondary small">Vorschau — es wurde nichts geschrieben.</div>';
    }
    return `
      <div class="alert alert-${kind} py-2 mb-2"><div><div class="fw-semibold">${_escapeHtml(label)}</div><div class="small">${_escapeHtml(r.reason || "")}</div></div></div>
      ${error}
      <dl class="row gx-2 mb-2">${dl}</dl>
      ${outcomeNote}`;
  }

  function _genreRevalSetBusy(busy) {
    document.getElementById("genre-revalidation-preview-btn").disabled = busy;
    if (busy) document.getElementById("genre-revalidation-apply-btn").disabled = true;
  }

  function _stopGenreRevalPolling() {
    if (_genreRevalTimer) { clearInterval(_genreRevalTimer); _genreRevalTimer = null; }
  }

  function _renderGenreRevalidationJob(job) {
    const el = document.getElementById("genre-revalidation-content");
    if (job.status === "PENDING" || job.status === "RUNNING") {
      el.innerHTML = `<div class="d-flex align-items-center gap-2 mb-2"><span class="badge bg-teal-lt">${_escapeHtml(job.status)} (${job.progress.toFixed(0)}%)</span><span class="text-secondary small text-truncate">${_escapeHtml(job.message || "")}</span></div>`
        + `<div class="progress progress-sm"><div class="progress-bar bg-teal" style="width: ${Math.max(0, Math.min(100, Number(job.progress) || 0))}%"></div></div>`;
      return;
    }
    _stopGenreRevalPolling();
    _genreRevalSetBusy(false);
    if (job.status !== "SUCCEEDED") {
      el.innerHTML = `<div class="alert alert-danger mb-0">Fehlgeschlagen: ${_escapeHtml(job.error || "Unbekannter Fehler")}</div>`;
      return;
    }
    const r = job.result || {};
    el.innerHTML = genreRevalidationResultHtml(r);
    // "Änderung übernehmen" nur nach einer Vorschau, die die Änderung zulässt.
    document.getElementById("genre-revalidation-apply-btn").disabled =
      !(r.mode === "preview" && r.outcome === "OVERTURN_ALLOWED" && !r.error_message);
  }

  async function _pollGenreRevalidationJob(jobId) {
    try {
      const res = await fetch(apiUrl(`/api/v1/jobs/${encodeURIComponent(jobId)}`), { credentials: "same-origin" });
      if (res.status === 401) { showOnly("login-view"); _stopGenreRevalPolling(); return; }
      if (!res.ok) return;
      _renderGenreRevalidationJob(await res.json());
    } catch (err) {}
  }

  async function startGenreRevalidation(mode) {
    const artist = currentArtistFromPath();
    if (mode === "apply") {
      const confirmed = await _artistConfirm(
        `Genre-Revalidierung für "${artist}" anwenden?\n\n` +
        `Last.fm wird erneut abgefragt; nur wenn die Overturn-Regel dann noch erfüllt ist, ` +
        `wird das gelernte Genre in mapping/auto_learned_genre.json aktualisiert. ` +
        `Für neue Downloads wirkt das erst nach einem Bot-Neustart. Audio-Dateien werden nicht verändert.`
      );
      if (!confirmed) return;
    }
    _genreRevalSetBusy(true);
    document.getElementById("genre-revalidation-content").innerHTML = _runningHtml("Wird gestartet…");
    try {
      const res = await fetch(apiUrl(`/api/v1/jobs/genre-revalidation-${mode}`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ artist }),
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        document.getElementById("genre-revalidation-content").innerHTML =
          `<div class="alert alert-danger mb-0">Job konnte nicht gestartet werden: ${_escapeHtml((body && body.error && body.error.message) || String(res.status))}</div>`;
        _genreRevalSetBusy(false);
        return;
      }
      const job = await res.json();
      _genreRevalJobId = job.job_id;
      _renderGenreRevalidationJob(job);
      _stopGenreRevalPolling();
      _genreRevalTimer = setInterval(() => _pollGenreRevalidationJob(_genreRevalJobId), 1000);
    } catch (err) {
      document.getElementById("genre-revalidation-content").innerHTML =
        `<div class="alert alert-danger mb-0">Job konnte nicht gestartet werden (${_escapeHtml(err.message)}).</div>`;
      _genreRevalSetBusy(false);
    }
  }

  document.getElementById("genre-revalidation-preview-btn").addEventListener("click", () => startGenreRevalidation("preview"));
  document.getElementById("genre-revalidation-apply-btn").addEventListener("click", () => startGenreRevalidation("apply"));

  // -- Duplikat-Check (read-only Vorschlag, als Job) ---------------------------
  //
  // POST /api/v1/jobs/duplicate-check (Job, Polling wie bei der
  // Genre-Revalidierung). Bewusst KEIN Apply/Execute aus dem Web - identische
  // Sicherheitsgrenze wie Telegram (handlers/duplicate_check_handler.py):
  // Löschen bleibt CLI-only.

  let _dupCheckTimer = null;
  let _dupCheckJobId = null;

  function _shortPath(path) {
    if (!path) return "?";
    const parts = String(path).split("/");
    return parts[parts.length - 1];
  }

  function duplicateCheckResultHtml(r) {
    if (r.read_only_intact === false) {
      return `<div class="alert alert-danger mb-0">${ccIcon("alert", "me-1")}Sicherheitswarnung: Das Dateisystem hat sich während des Scans verändert — Ergebnis verworfen, bitte erneut versuchen.</div>`;
    }
    const groups = r.duplicate_groups || 0;
    if (groups === 0) {
      return `<div class="alert alert-success mb-0">Keine Duplikat-Gruppen gefunden (${_escapeHtml(String(r.files_scanned || 0))} Dateien geprüft).</div>`;
    }
    const resolved = r.resolved_groups || 0;
    const manual = r.manual_review_groups || 0;
    const decisions = r.decisions || [];
    const groupsHtml = decisions.map((d) => {
      const title = _escapeHtml(d.title || "?");
      const candidates = d.candidates || [];
      if (d.action === "RESOLVED") {
        const keepCandidate = candidates.find((c) => c.path === d.keep);
        const keepBitrate = keepCandidate && keepCandidate.bitrate ? ` (${keepCandidate.bitrate} kbps)` : "";
        const removeLines = (d.remove_proposal || []).map((rp) => {
          const rpCandidate = candidates.find((c) => c.path === rp);
          const rpBitrate = rpCandidate && rpCandidate.bitrate ? ` (${rpCandidate.bitrate} kbps)` : "";
          return `<div class="small text-danger">${ccIcon("trash", "icon-sm me-1")}Vorschlag entfernen: ${_escapeHtml(_shortPath(rp))}${rpBitrate}</div>`;
        }).join("");
        return `<div class="mb-2"><div class="fw-semibold">${ccIcon("music", "me-1 text-teal")}${title}</div><div class="small text-success">${ccIcon("check", "icon-sm me-1")}Behalten: ${_escapeHtml(_shortPath(d.keep))}${keepBitrate}</div>${removeLines}</div>`;
      }
      return `<div class="mb-2"><div class="fw-semibold">${ccIcon("music", "me-1 text-teal")}${title}</div><div class="small text-warning">${ccIcon("alert", "icon-sm me-1")}${_escapeHtml(d.action || "MANUAL_REVIEW")}: ${_escapeHtml(d.reason || "kein Grund angegeben")}</div></div>`;
    }).join("");
    return `
      <div class="alert alert-info py-2 mb-2">${groups} Duplikat-Gruppe(n) — ${resolved} mit Vorschlag, ${manual} zur manuellen Prüfung</div>
      ${groupsHtml}
      <div class="text-secondary small mt-2">Löschen nur über die CLI: <code>scripts/library_repair.py --allow-delete --artist ${_escapeHtml(currentArtistFromPath())} --apply</code></div>`;
  }

  function _dupCheckSetBusy(busy) {
    document.getElementById("duplicate-check-btn").disabled = busy;
  }

  function _stopDupCheckPolling() {
    if (_dupCheckTimer) { clearInterval(_dupCheckTimer); _dupCheckTimer = null; }
  }

  function _renderDuplicateCheckJob(job) {
    const el = document.getElementById("duplicate-check-content");
    if (job.status === "PENDING" || job.status === "RUNNING") {
      el.innerHTML = `<div class="d-flex align-items-center gap-2 mb-2"><span class="badge bg-teal-lt">${_escapeHtml(job.status)} (${job.progress.toFixed(0)}%)</span><span class="text-secondary small text-truncate">${_escapeHtml(job.message || "")}</span></div>`
        + `<div class="progress progress-sm"><div class="progress-bar bg-teal" style="width: ${Math.max(0, Math.min(100, Number(job.progress) || 0))}%"></div></div>`;
      return;
    }
    _stopDupCheckPolling();
    _dupCheckSetBusy(false);
    if (job.status !== "SUCCEEDED") {
      el.innerHTML = `<div class="alert alert-danger mb-0">Fehlgeschlagen: ${_escapeHtml(job.error || "Unbekannter Fehler")}</div>`;
      return;
    }
    el.innerHTML = duplicateCheckResultHtml(job.result || {});
  }

  async function _pollDuplicateCheckJob(jobId) {
    try {
      const res = await fetch(apiUrl(`/api/v1/jobs/${encodeURIComponent(jobId)}`), { credentials: "same-origin" });
      if (res.status === 401) { showOnly("login-view"); _stopDupCheckPolling(); return; }
      if (!res.ok) return;
      _renderDuplicateCheckJob(await res.json());
    } catch (err) {}
  }

  async function startDuplicateCheck() {
    const artist = currentArtistFromPath();
    _dupCheckSetBusy(true);
    document.getElementById("duplicate-check-content").innerHTML = _runningHtml("Wird gestartet…");
    try {
      const res = await fetch(apiUrl("/api/v1/jobs/duplicate-check"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ artist }),
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        document.getElementById("duplicate-check-content").innerHTML =
          `<div class="alert alert-danger mb-0">Job konnte nicht gestartet werden: ${_escapeHtml((body && body.error && body.error.message) || String(res.status))}</div>`;
        _dupCheckSetBusy(false);
        return;
      }
      const job = await res.json();
      _dupCheckJobId = job.job_id;
      _renderDuplicateCheckJob(job);
      _stopDupCheckPolling();
      _dupCheckTimer = setInterval(() => _pollDuplicateCheckJob(_dupCheckJobId), 1000);
    } catch (err) {
      document.getElementById("duplicate-check-content").innerHTML =
        `<div class="alert alert-danger mb-0">Job konnte nicht gestartet werden (${_escapeHtml(err.message)}).</div>`;
      _dupCheckSetBusy(false);
    }
  }

  document.getElementById("duplicate-check-btn").addEventListener("click", startDuplicateCheck);

  document.getElementById("genre-manage-preview-btn").addEventListener("click", loadGenreManagePreview);
  document.getElementById("genre-manage-execute-btn").addEventListener("click", executeGenreManage);

  // Library-Wartung (CC-AC-4, library_artist_centric_UX.txt) - reine
  // Verdrahtung der bereits produktiven Endpunkte aus
  // admin_maintenance.py (Artist-Casing, Legacy-Genre-Cleanup, identisches
  // Preview->Diff->Confirmation->Execution-Muster wie oben/admin.html) und
  // jobs.py (L2/L3, identisches Confirm->Start->1s-Polling-Muster wie
  // static/pages/health.js::startLevel23Job()/_pollLevel23Job(), vormals
  // repairs.html) - hier mit
  // implizitem artist=currentArtistFromPath() statt Freitextfeld bzw.
  // Artist-Auswahl aus einer Plan-Liste. Keine neue Ausfuehrungslogik.

  // -- Artist Casing korrigieren -------------------------------------------

  async function loadArtistCasingPreview() {
    const artist = currentArtistFromPath();
    document.getElementById("artist-casing-execute-btn").disabled = true;
    document.getElementById("artist-casing-result-content").innerHTML = "";
    const params = new URLSearchParams({ artist }).toString();
    await _loadInto(
      "artist-casing-content",
      `/api/v1/admin/maintenance/artist-casing/preview?${params}`,
      (el, body) => renderMetadataEditPreview(el, body, "artist-casing-execute-btn"),
    );
  }

  async function executeArtistCasing() {
    const artist = currentArtistFromPath();
    const confirmed = await _artistConfirm(
      `Artist-Casing für "${artist}" wirklich korrigieren?\n\n` +
      `Mit Backup abgesichert (SHA-256-/Audio-Essenz-Verifikation vor dem Schreiben) — ` +
      `aber es werden tatsächlich Dateien in der Library verändert.`
    );
    if (!confirmed) return;

    const execBtn = document.getElementById("artist-casing-execute-btn");
    const resultEl = document.getElementById("artist-casing-result-content");
    execBtn.disabled = true;
    resultEl.innerHTML = _runningHtml("Wird ausgeführt…");
    try {
      const params = new URLSearchParams({ artist }).toString();
      const res = await fetch(apiUrl(`/api/v1/admin/maintenance/artist-casing/execute?${params}`), {
        method: "POST",
        credentials: "same-origin",
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      const body = await res.json();
      if (!res.ok) {
        resultEl.innerHTML = _resultAlert("danger", `Fehler: ${_escapeHtml((body.error && body.error.message) || String(res.status))}`);
        return;
      }
      // Erst Vorschau neu laden (sie leert das Ergebnisfeld), dann das Ergebnis
      // zeigen - vorher verschwand die Erfolgsmeldung sofort wieder (CC-UI L3b).
      const resultHtml = _executeResultHtml(body);
      await loadArtistCasingPreview();
      resultEl.innerHTML = resultHtml;
      _executeToast(body);
    } catch (err) {
      resultEl.innerHTML = _resultAlert("danger", `Ergebnis unbekannt — bitte Seite neu laden bzw. Repair-Journal prüfen (${_escapeHtml(err.message)}).`);
    } finally {
      execBtn.disabled = false;
    }
  }

  document.getElementById("artist-casing-preview-btn").addEventListener("click", loadArtistCasingPreview);
  document.getElementById("artist-casing-execute-btn").addEventListener("click", executeArtistCasing);

  // -- Legacy Genre bereinigen ----------------------------------------------

  async function loadLegacyGenreCleanupPreview() {
    const artist = currentArtistFromPath();
    document.getElementById("legacy-genre-cleanup-execute-btn").disabled = true;
    document.getElementById("legacy-genre-cleanup-result-content").innerHTML = "";
    const params = new URLSearchParams({ artist }).toString();
    await _loadInto(
      "legacy-genre-cleanup-content",
      `/api/v1/admin/maintenance/legacy-genre-cleanup/preview?${params}`,
      (el, body) => renderMetadataEditPreview(el, body, "legacy-genre-cleanup-execute-btn"),
    );
  }

  async function executeLegacyGenreCleanup() {
    const artist = currentArtistFromPath();
    const confirmed = await _artistConfirm(
      `Legacy-Genre-Atome für "${artist}" wirklich entfernen?\n\n` +
      `Mit Backup abgesichert (SHA-256-/Audio-Essenz-Verifikation vor dem Schreiben) — ` +
      `aber es werden tatsächlich Dateien in der Library verändert.`
    );
    if (!confirmed) return;

    const execBtn = document.getElementById("legacy-genre-cleanup-execute-btn");
    const resultEl = document.getElementById("legacy-genre-cleanup-result-content");
    execBtn.disabled = true;
    resultEl.innerHTML = _runningHtml("Wird ausgeführt…");
    try {
      const params = new URLSearchParams({ artist }).toString();
      const res = await fetch(apiUrl(`/api/v1/admin/maintenance/legacy-genre-cleanup/execute?${params}`), {
        method: "POST",
        credentials: "same-origin",
      });
      if (res.status === 401) { showOnly("login-view"); return; }
      const body = await res.json();
      if (!res.ok) {
        resultEl.innerHTML = _resultAlert("danger", `Fehler: ${_escapeHtml((body.error && body.error.message) || String(res.status))}`);
        return;
      }
      // Erst Vorschau neu laden (sie leert das Ergebnisfeld), dann das Ergebnis
      // zeigen - vorher verschwand die Erfolgsmeldung sofort wieder (CC-UI L3b).
      const resultHtml = _executeResultHtml(body);
      await loadLegacyGenreCleanupPreview();
      resultEl.innerHTML = resultHtml;
      _executeToast(body);
    } catch (err) {
      resultEl.innerHTML = _resultAlert("danger", `Ergebnis unbekannt — bitte Seite neu laden bzw. Repair-Journal prüfen (${_escapeHtml(err.message)}).`);
    } finally {
      execBtn.disabled = false;
    }
  }

  document.getElementById("legacy-genre-cleanup-preview-btn").addEventListener("click", loadLegacyGenreCleanupPreview);
  document.getElementById("legacy-genre-cleanup-execute-btn").addEventListener("click", executeLegacyGenreCleanup);

  // CC-UI L4 (Nutzerentscheidung 2026-09-28): die L3-Reparatur gibt es nur
  // noch auf der Health-Seite (static/pages/health.js::startLevel23Job(),
  // derselbe Endpunkt POST /api/v1/jobs/repair-level3, dort nur für Artists
  // mit offenen L3-Befunden) - der Button hier war doppelt.

  // -- Track Detail Drawer (CC-AC-9, Track-Centric Library Actions) -------
  //
  // Reine Praesentation/Navigation ueber die bereits geladenen Track-Daten
  // (_artistDetailTracksByPath oben) - KEIN neuer API-Call, KEINE neue
  // Health-/Business-Logik. issue_codes kommen unveraendert aus
  // TrackSchema (services/library_health/issues.py::REGISTRY,
  // ausschliesslich Scope.FILE - services/library_health/models.py::
  // FileHealth.to_dict()) - die Labels unten sind reine Anzeige-
  // Uebersetzung, keine neue Diagnose (Auftrag §7). Die Aktionen im
  // Drawer fuehren selbst NICHTS aus: sie oeffnen/befuellen
  // ausschliesslich die bestehenden Formulare oben (Manual Metadata
  // Editing v1-3, CC-AC-2/3) und rufen deren bereits getestete
  // load*Preview()-Funktionen auf - Preview->Confirm->Execute bleibt
  // exakt der bestehende, unveraenderte Pfad (Auftrag §10).
  // CC-LIB-FINAL Library-Home: Label-Dict lebt jetzt zentral als
  // _ISSUE_LABELS in common.js (zweiter Konsument ist library.html's
  // Aufmerksamkeit-Karte) - hier keine eigene, driftende Kopie mehr.

  let _trackDrawerIsAdmin = false;
  let _trackDrawerCurrentArtist = null;
  let _trackDrawerCurrentTrack = null;
  let _trackDrawerTriggerEl = null;

  function _trackDrawerFieldsHtml(t) {
    const rows = [
      ["Titel", t.title], ["Artist", t.artist], ["Album", t.album],
      ["Album Artist", t.album_artist], ["Genre", t.genre], ["Jahr", t.year],
      ["Track", t.track_number], ["Disc", t.disc_number],
      ["MB Recording-ID", t.mb_recording_id], ["MB Release-ID", t.mb_release_id],
      ["ISRC", t.isrc],
    ];
    return '<div class="datagrid">' + rows.map(([label, value]) => `
      <div class="datagrid-item"><div class="datagrid-title">${_escapeHtml(label)}</div>
        <div class="datagrid-content text-break">${_escapeHtml(value ?? "–")}</div></div>
    `).join("") + "</div>";
  }

  function _trackDrawerHealthHtml(t) {
    if (!t.issue_codes.length) {
      return `<div class="text-success">${ccIcon("check", "me-1")}Keine bekannten Probleme laut letztem Health-Scan.</div>`;
    }
    return '<div class="d-flex flex-wrap gap-1">'
      + t.issue_codes.map((code) => ccStatusBadge("warn", _ISSUE_LABELS[code] || code)).join("") + "</div>";
  }

  // Album-Wert fuer diesen Track - identische Semantik wie
  // _artistAlbumOptions() oben/album_targets() (services/library_repair/
  // maintenance_service.py): Mehr-Track-Album -> album_directory,
  // Single (kein album_directory, .m4a) -> relativer Pfad ohne
  // Artist-Praefix. Liefert null, wenn album_targets() ohnehin leer
  // bleiben wuerde (nicht .m4a) - dann keine Album-/Albuminterpret-
  // Aktion anzeigen.
  function _trackAlbumValue(artist, t) {
    if (t.album_directory) return t.album_directory;
    const prefix = `${artist}/`;
    if (t.extension === ".m4a" && t.relative_path.startsWith(prefix)) {
      return t.relative_path.slice(prefix.length);
    }
    return null;
  }

  // CC-LIB-FINAL Metadaten-Workspace (Layout A): Artist/Titel/Album/
  // Albuminterpret/Genre sind jetzt Tabs (Bootstrap .tab-pane), nicht mehr
  // gleichzeitig sichtbar. Die Track-Drawer-/Album-Detail-Quick-Edit-Links
  // unten muessen deshalb zusaetzlich zum Aufklappen des Panels den
  // passenden Tab aktivieren, sonst scrollIntoView()/focus() liefen ins
  // Leere (Ziel-Feld waere durch einen anderen aktiven Tab verdeckt).
  // CC-UI L4: ein Editor-Seitenpanel (#md-editor) mit fünf Reitern statt
  // der Karten "Metadaten bearbeiten" und "Library-Wartung". Die alten
  // Reiter-IDs (meta-tab-*) werden auf die neuen Reiter abgebildet.
  const _MD_TAB_ALIASES = {
    "meta-tab-artist": "artist", "meta-tab-title": "title", "meta-tab-album": "album",
    "meta-tab-albumartist": "album", "meta-tab-genre": "genre",
  };

  function _showMetaTab(tab) {
    document.querySelectorAll("#md-tabs [data-md-tab]").forEach((a) => {
      const active = a.dataset.mdTab === tab;
      a.classList.toggle("active", active);
      a.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll("#md-editor [data-md-pane]").forEach((pane) => { pane.hidden = pane.dataset.mdPane !== tab; });
    if (tab === "genre" && !_genreMap.etag) loadGenreMapping();  // lazy wie bisher
    // Schritt 2 zeigt sofort, wie viele Dateien "Tags schreiben" ändern würde
    // (read-only Vorschau, einmal je Öffnen des leeren Reiters).
    if (tab === "genre" && !document.getElementById("genre-manage-content").innerHTML) loadGenreManagePreview();
    if (tab === "artist") _prefillArtistInput();
  }

  function _prefillArtistInput() {
    const input = document.getElementById("artist-edit-new-artist");
    if (input && !input.value) {
      input.value = currentArtistFromPath();
      _autoArtistPreview();
    }
  }

  function openMetadataEditor(tab) {
    if (!_trackDrawerIsAdmin) return;  // Editor nur für Admin (Endpunkte sind serverseitig gegated)
    _showMetaTab(tab || "artist");
    const Offcanvas = window.tabler && window.tabler.Offcanvas;
    const el = document.getElementById("md-editor");
    if (Offcanvas) Offcanvas.getOrCreateInstance(el).show();
    else el.classList.add("show");
  }

  function _openMetadataEditPanel(tabId) {
    openMetadataEditor(_MD_TAB_ALIASES[tabId] || tabId || "artist");
  }

  document.getElementById("artist-edit-open-btn").addEventListener("click", () => openMetadataEditor("artist"));
  document.getElementById("md-tabs").addEventListener("click", (event) => {
    const link = event.target.closest("[data-md-tab]");
    if (!link) return;
    event.preventDefault();
    _showMetaTab(link.dataset.mdTab);
  });
  document.getElementById("title-edit-list").addEventListener("click", (event) => {
    const row = event.target.closest("[data-title-path]");
    if (row) _selectTitleTrack(row.dataset.titlePath);
  });

  // Extrahiert aus _trackDrawerEditTitle() (Phase E, CC-LIB-FINAL): reiner
  // Refactor, kein Verhaltensunterschied fuer den Drawer-Pfad - zweiter
  // Aufrufer ist jetzt der Quick-Edit-Stift direkt in der Track-Zeile
  // (siehe #artist-content-Klick-Delegation weiter unten), der keinen
  // Drawer zu schliessen hat.
  function _quickEditTitleForTrack(t) {
    _openMetadataEditPanel("meta-tab-title");
    const trackSelect = document.getElementById("title-edit-track-select");
    const titleInput = document.getElementById("title-edit-new-title");
    trackSelect.value = t.relative_path;
    titleInput.value = t.title || "";
    document.getElementById("title-edit-execute-btn").disabled = true;
    _markTitleRow(t.relative_path);
    titleInput.scrollIntoView({ block: "center" });
    titleInput.focus();
    loadTitleEditPreview();
  }

  function _trackDrawerEditTitle() {
    const t = _trackDrawerCurrentTrack;
    closeTrackDrawer();
    _quickEditTitleForTrack(t);
  }

  function _trackDrawerEditArtist() {
    closeTrackDrawer();
    _openMetadataEditPanel("meta-tab-artist");
    _prefillArtistInput();
    const input = document.getElementById("artist-edit-new-artist");
    input.scrollIntoView({ block: "center" });
    input.focus();
  }

  // Extrahiert aus _trackDrawerEditAlbumField() (Phase E, CC-LIB-FINAL):
  // reiner Refactor, kein Verhaltensunterschied fuer den Drawer-Pfad -
  // zweiter Aufrufer sind jetzt die "Album bearbeiten"/"Albuminterpret
  // bearbeiten"-Buttons im Album-Detail-Header (siehe
  // #artist-content-Klick-Delegation weiter unten), dort ist
  // albumValue bereits der ausgewaehlte Album-Schluessel (kein Track
  // noetig, der aufloest werden muesste).
  function _quickEditAlbumField(albumValue, selectId, inputId) {
    _openMetadataEditPanel(selectId === "albumartist-edit-album-select" ? "meta-tab-albumartist" : "meta-tab-album");
    // CC-UI L4: eine sichtbare Album-Auswahl für beide Felder
    const select = document.getElementById("album-edit-album-select");
    if (albumValue !== null && [...select.options].some((o) => o.value === albumValue)) {
      select.value = albumValue;
      _selectAlbumForEdit(albumValue);
    }
    const input = document.getElementById(inputId);
    input.scrollIntoView({ block: "center" });
    input.focus();
  }

  function _trackDrawerEditAlbumField(selectId, inputId) {
    const albumValue = _trackAlbumValue(_trackDrawerCurrentArtist, _trackDrawerCurrentTrack);
    closeTrackDrawer();
    _quickEditAlbumField(albumValue, selectId, inputId);
  }

  function _trackDrawerEditGenre() {
    closeTrackDrawer();
    _openMetadataEditPanel("meta-tab-genre");
    document.getElementById("genre-mapping-editor").scrollIntoView({ block: "center" });
    if (!_genreMap.etag) loadGenreMapping();
    loadGenreManagePreview();
  }

  // CC-UI L4: statt "Library-Wartung" (Karte entfällt) -> Reiter Duplikate.
  function _trackDrawerOpenDuplicates() {
    closeTrackDrawer();
    openMetadataEditor("dupes");
  }

  const _TRACK_DRAWER_ACTION_HANDLERS = {
    title: _trackDrawerEditTitle,
    artist: _trackDrawerEditArtist,
    album: () => _trackDrawerEditAlbumField("album-edit-album-select", "album-edit-new-album"),
    albumartist: () => _trackDrawerEditAlbumField("albumartist-edit-album-select", "albumartist-edit-new-albumartist"),
    genre: _trackDrawerEditGenre,
    duplicates: _trackDrawerOpenDuplicates,
  };

  function _trackDrawerActionsHtml(artist, t) {
    if (!_trackDrawerIsAdmin) {
      return `<div class="text-secondary">${ccIcon("lock", "me-1")}Aktionen benötigen Admin-Berechtigung.</div>`;
    }
    const rows = [["title", "edit", "Titel bearbeiten"], ["artist", "microphone", "Artist bearbeiten"]];
    if (_trackAlbumValue(artist, t) !== null) {
      rows.push(["album", "disc", "Album bearbeiten"]);
      rows.push(["albumartist", "users", "Albuminterpret bearbeiten"]);
    }
    rows.push(["genre", "tag", "Genre bearbeiten"]);
    rows.push(["duplicates", "copy", "Duplikate prüfen (Artist-weit)"]);
    return '<div class="list-group">' + rows.map(([action, icon, label]) => `
      <button type="button" class="list-group-item list-group-item-action d-flex align-items-center gap-2" data-track-action="${action}">${ccIcon(icon, "text-teal")}${label}</button>
    `).join("") + '</div>' +
      '<div class="text-secondary small mt-2">Öffnet den Metadaten-Editor am passenden Reiter — geschrieben wird erst nach Bestätigung.</div>';
  }

  document.getElementById("track-drawer-actions").addEventListener("click", (event) => {
    const btn = event.target.closest("[data-track-action]");
    if (!btn || !_trackDrawerCurrentTrack) return;
    const handler = _TRACK_DRAWER_ACTION_HANDLERS[btn.dataset.trackAction];
    // Aktion springt zu einem Formular: Fokus danach NICHT zur Track-Zeile
    // zurückgeben (das Offcanvas schließt animiert, der Rücksprung käme
    // sonst nach dem Fokus auf dem Zielfeld).
    _trackDrawerTriggerEl = null;
    if (handler) handler();
  });

  // CC-UI L3a: Track-Detail als Tabler-Offcanvas (Standard §6). Fokus-Falle,
  // Escape und Backdrop-Klick übernimmt Tabler/Bootstrap (vorher ~40 Zeilen
  // eigene Logik); role="dialog"/aria-modal stehen statisch im Markup. Der
  // Fokus kehrt nach dem Schließen zur auslösenden Track-Zeile zurück
  // (Auftrag §16) - außer eine Drawer-Aktion springt zu einem Formular.
  function _trackDrawerOffcanvas() {
    const Offcanvas = window.tabler && window.tabler.Offcanvas;
    return Offcanvas ? Offcanvas.getOrCreateInstance(document.getElementById("track-drawer")) : null;
  }

  function openTrackDrawer(t) {
    const artist = currentArtistFromPath();
    _trackDrawerCurrentArtist = artist;
    _trackDrawerCurrentTrack = t;
    _trackDrawerTriggerEl = document.activeElement;

    document.getElementById("track-drawer-title").textContent = t.title || t.filename;
    document.getElementById("track-drawer-subtitle").textContent = `${t.artist || "?"} · ${t.album || "–"}`;
    document.getElementById("track-drawer-info").innerHTML = _trackDrawerFieldsHtml(t);
    document.getElementById("track-drawer-health").innerHTML = _trackDrawerHealthHtml(t);
    document.getElementById("track-drawer-actions").innerHTML = _trackDrawerActionsHtml(artist, t);

    const oc = _trackDrawerOffcanvas();
    if (oc) oc.show();
    else document.getElementById("track-drawer").classList.add("show");
  }

  function _trackDrawerAfterClose() {
    _trackDrawerCurrentTrack = null;
    if (_trackDrawerTriggerEl && document.body.contains(_trackDrawerTriggerEl)) {
      _trackDrawerTriggerEl.focus();
    }
    _trackDrawerTriggerEl = null;
  }

  function closeTrackDrawer() {
    const oc = _trackDrawerOffcanvas();
    if (oc) { oc.hide(); return; }  // Aufräumen in hidden.bs.offcanvas
    document.getElementById("track-drawer").classList.remove("show");
    _trackDrawerAfterClose();
  }

  document.getElementById("track-drawer").addEventListener("hidden.bs.offcanvas", _trackDrawerAfterClose);
  document.getElementById("track-drawer-close").addEventListener("click", closeTrackDrawer);

  // Eine einzige delegierte Klick-Behandlung fuer #artist-content (Phase
  // E, CC-LIB-FINAL) - die Track-Row-Oeffnung (Track-Drawer) war bereits
  // delegiert, hier um die vier neuen Master-Detail-Interaktionen
  // ergaenzt (Album waehlen, Titel-Quick-Edit, Album-/Albuminterpret-
  // Toolbar, Metadaten-/Wartung-Sprungmarken). Alle vier rufen
  // ausschliesslich bereits bestehende Funktionen auf (siehe oben) -
  // keine neue Ausfuehrungslogik.
  document.getElementById("artist-content").addEventListener("click", (event) => {
    const albumBtn = event.target.closest("[data-album-key]");
    if (albumBtn) {
      _selectedAlbumKey = albumBtn.dataset.albumKey;
      _rerenderAlbumMasterDetail();
      return;
    }
    const quickEditBtn = event.target.closest("[data-quick-edit-title]");
    if (quickEditBtn) {
      const track = _artistDetailTracksByPath[quickEditBtn.dataset.quickEditTitle];
      if (track) _quickEditTitleForTrack(track);
      return;
    }
    if (event.target.closest("#album-detail-edit-album-btn")) {
      _openMetadataEditPanel();
      _quickEditAlbumField(_selectedAlbumKey, "album-edit-album-select", "album-edit-new-album");
      return;
    }
    if (event.target.closest("#album-detail-edit-albumartist-btn")) {
      _openMetadataEditPanel();
      _quickEditAlbumField(_selectedAlbumKey, "albumartist-edit-album-select", "albumartist-edit-new-albumartist");
      return;
    }
    if (event.target.closest("#artist-detail-open-metadata")) {
      event.preventDefault();
      openMetadataEditor("artist");
      return;
    }
    const btn = event.target.closest(".track-row");
    if (!btn) return;
    const track = _artistDetailTracksByPath[btn.dataset.trackPath];
    if (track) openTrackDrawer(track);
  });

  function initPage() {
    checkAuth().then((who) => {
      if (!who) return;
      // Buttons nur sichtbar fuer Admin (Auftrag CC-AC-2-Scope, fuer die
      // Library-Wartung identisch fortgesetzt CC-AC-4-Scope) - die
      // zugrundeliegenden Endpunkte sind ohnehin serverseitig auf
      // AccessLevel.ADMIN gegated (Master-Prompt Regel 30, kein reiner
      // UI-Check als alleiniger Schutz), dies ist zusaetzlich die
      // sichtbare UX-Schranke.
      const isAdmin = who.access_level === "ADMIN" || who.access_level === "OWNER";
      document.getElementById("artist-edit-open-btn").hidden = !isAdmin;
      _trackDrawerIsAdmin = isAdmin;
      loadArtistDetail();
    });
  }
  initPage();
