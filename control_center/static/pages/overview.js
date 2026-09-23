// Overview beantwortet die Leitfrage:
  // "Wie geht es meinem MusicBot gerade und was braucht Aufmerksamkeit?"
  // Siehe docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md.
  //
  // Hinweis: Es gibt KEINEN leichtgewichtigen Repair-Summary-Endpunkt.
  // GET /api/v1/library/repair-plan loest einen vollen Library-Scan aus
  // (~37s auf Produktion) und darf deshalb NICHT im Auto-Load laufen.
  // Die Attention-Zeile beschraenkt sich daher bewusst auf Findings
  // (GET /api/v1/library/findings/summary ist guenstig und persistent).
  // Repair-Kandidaten bleiben dem /repairs-Panel mit manuellem Trigger
  // vorbehalten.
  //
  // Health-Kachel: GET /api/v1/library/health/cached (nicht /health!) —
  // /health loest denselben ~37s-Scan aus wie /repair-plan und darf
  // deshalb ebenfalls nicht im Auto-Load laufen. /health/cached liest
  // stattdessen ausschliesslich den bereits vorhandenen persistenten
  // Report (siehe control_center/routers/health.py), identisches Prinzip
  // wie bei /artists-overview (CC-AC-1). /health selbst bleibt fuer die
  // dedizierte Health-Seite (health.html) unveraendert.

  // Aggregierter State für Systemstatus-Berechnung
  const _overviewState = {
    health: null,     // { status, score, library: { files, artists, albums } }
    navidrome: null,  // { connected, artist_count }
    findings: 0,
  };

  // Grobe relative Zeitangabe ("vor 2 Stunden") fuer den Health-Report-
  // Zeitpunkt (CONTROL_CENTER_OVERVIEW_V2.md Abschnitt 5) — kein neuer
  // Formatierungs-Helfer in common.js noetig, nur hier lokal gebraucht.
  function _timeAgo(isoString) {
    const then = new Date(isoString);
    if (isNaN(then.getTime())) return null;
    const diffMin = Math.round((Date.now() - then.getTime()) / 60000);
    if (diffMin < 1) return "gerade eben";
    if (diffMin < 60) return `vor ${diffMin} Minute${diffMin === 1 ? "" : "n"}`;
    const diffHr = Math.round(diffMin / 60);
    if (diffHr < 24) return `vor ${diffHr} Stunde${diffHr === 1 ? "" : "n"}`;
    const diffDay = Math.round(diffHr / 24);
    return `vor ${diffDay} Tag${diffDay === 1 ? "" : "en"}`;
  }

  // ══════════════════════════════════════════════════════════════════
  // System-Metriken
  // ══════════════════════════════════════════════════════════════════
    // ══════════════════════════════════════════════════════════════════
  // System-Metriken (control_center_overview Phase 3)
  //
  // Datenquelle: GET /api/v1/admin/system/status (ADMIN-Level, da der
  // gesamte Control Center faktisch admin-only ist).
  // Bot-Service-Uptime aus systemctl ActiveEnterTimestamp (NICHT
  // psutil.boot_time, das wäre die Host-Bootzeit).
  // ══════════════════════════════════════════════════════════════════

  function _metricColorClass(percent) {
    if (percent == null) return "";
    if (percent >= 90) return "metric-critical";
    if (percent >= 70) return "metric-warn";
    return "";
  }

  function _formatMb(mb) {
    if (mb == null) return "";
    if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
    return `${Math.round(mb)} MB`;
  }

  function _formatGb(gb) {
    if (gb == null) return "";
    if (gb >= 1024) return `${(gb / 1024).toFixed(2)} TB`;
    return `${gb.toFixed(1)} GB`;
  }

  function _formatStartedAt(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    const date = d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
    const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    return `seit ${date} ${time}`;
  }

  async function loadSystemMetrics() {
    const cpuVal   = document.getElementById("metric-cpu-value");
    const cpuSub   = document.getElementById("metric-cpu-sub");
    const ramVal   = document.getElementById("metric-ram-value");
    const ramSub   = document.getElementById("metric-ram-sub");
    const diskVal  = document.getElementById("metric-disk-value");
    const diskSub  = document.getElementById("metric-disk-sub");
    const botVal   = document.getElementById("metric-bot-value");
    const botSub   = document.getElementById("metric-bot-sub");
    const sysOs    = document.getElementById("system-platform-os");
    const sysPy    = document.getElementById("system-platform-python");
    const sysUp    = document.getElementById("system-uptime-value");
    const sysStart = document.getElementById("system-uptime-started");

    try {
      const res = await fetch(
        apiUrl("/api/v1/admin/system/status"),
        { credentials: "same-origin" },
      );

      if (res.status === 401) {
        showOnly("login-view");
        return;
      }

      const data = await res.json().catch(() => null);

      if (!res.ok) {
        throw new Error(
          data?.error?.message || data?.detail || `Fehler: ${res.status}`,
        );
      }

      // CPU
      if (cpuVal) {
        cpuVal.textContent = data.cpu_percent != null
          ? `${Number(data.cpu_percent).toFixed(1)} %` : "–";
        cpuVal.className = "h2 mb-0 " + _metricColorClass(data.cpu_percent);
      }
      if (cpuSub) {
        cpuSub.textContent = data.cpu_count ? `${data.cpu_count} Kerne` : "";
      }

      // RAM
      if (ramVal) {
        ramVal.textContent = data.memory_percent != null
          ? `${Number(data.memory_percent).toFixed(1)} %` : "–";
        ramVal.className = "h2 mb-0 " + _metricColorClass(data.memory_percent);
      }
      if (ramSub) {
        ramSub.textContent =
          data.memory_used_mb != null && data.memory_total_mb != null
            ? `${_formatMb(data.memory_used_mb)} / ${_formatMb(data.memory_total_mb)}`
            : "";
      }

      // Disk
      if (diskVal) {
        diskVal.textContent = data.disk_percent != null
          ? `${Number(data.disk_percent).toFixed(1)} %` : "–";
        diskVal.className = "h2 mb-0 " + _metricColorClass(data.disk_percent);
      }
      if (diskSub) {
        diskSub.textContent =
          data.disk_used_gb != null && data.disk_total_gb != null
            ? `${_formatGb(data.disk_used_gb)} / ${_formatGb(data.disk_total_gb)}`
            : "";
      }

      // Bot
      if (botVal) {
        if (data.bot_service_active === true) {
          botVal.textContent = "✅ Online";
          botVal.style.color = "var(--ok)";
        } else if (data.bot_service_active === false) {
          botVal.textContent = "❌ Offline";
          botVal.style.color = "var(--error)";
        } else {
          botVal.textContent = "–";
        }
      }
      if (botSub) {
        botSub.textContent = data.bot_uptime_formatted
          ? `${data.bot_uptime_formatted} Laufzeit` : "";
      }

      // System-Karte: Platform
      if (sysOs) {
        sysOs.textContent = data.platform_os
          ? `🐧 ${data.platform_os} ${data.platform_release || ""}`.trim() : "–";
      }
      if (sysPy) {
        const parts = [];
        if (data.platform_python) parts.push(`Python ${data.platform_python}`);
        if (data.platform_arch) parts.push(data.platform_arch);
        sysPy.textContent = parts.length ? `🐍 ${parts.join(" · ")}` : "–";
      }

      // System-Karte: Uptime
      if (sysUp) {
        sysUp.textContent = data.bot_uptime_formatted || "–";
      }
      if (sysStart) {
        sysStart.textContent = _formatStartedAt(data.bot_started_at);
      }

      // Load Average + Swap (Phase 5B)
      const sysLoad = document.getElementById("system-load-value");
      const sysSwap = document.getElementById("system-swap-value");

      if (sysLoad) {
        if (data.load_avg_1 != null && data.load_avg_5 != null && data.load_avg_15 != null) {
          sysLoad.textContent =
            `${data.load_avg_1.toFixed(2)} · ` +
            `${data.load_avg_5.toFixed(2)} · ` +
            `${data.load_avg_15.toFixed(2)}`;
        } else {
          sysLoad.textContent = "nicht verfügbar";
        }
      }

      if (sysSwap) {
        if (data.swap_total_gb != null && data.swap_used_gb != null) {
          if (data.swap_total_gb === 0) {
            sysSwap.textContent = "kein Swap";
          } else {
            const pct = data.swap_percent != null
              ? ` (${data.swap_percent.toFixed(0)} %)` : "";
            sysSwap.textContent =
              `${data.swap_used_gb.toFixed(1)} / ` +
              `${data.swap_total_gb.toFixed(1)} GB${pct}`;
          }
        } else {
          sysSwap.textContent = "nicht verfügbar";
        }
      }

    } catch (err) {
      if (cpuVal) cpuVal.textContent = "–";
      if (cpuSub) cpuSub.textContent = "Nicht abrufbar";
      if (ramVal) ramVal.textContent = "–";
      if (ramSub) ramSub.textContent = "";
      if (diskVal) diskVal.textContent = "–";
      if (diskSub) diskSub.textContent = "";
      if (botVal) botVal.textContent = "–";
      if (botSub) botSub.textContent = "";
      if (sysOs) sysOs.textContent = "–";
      if (sysPy) sysPy.textContent = "–";
      if (sysUp) sysUp.textContent = "–";
      if (sysStart) sysStart.textContent = "";
      console.error("System-Metriken konnten nicht geladen werden:", err);
    }
  }


  // control_center_overview Phase 5: Health-Score als Balken.
  function _renderLibraryHealthBar(health, stale) {
    const wrap = document.getElementById("status-library-health-bar");
    const fill = document.getElementById("status-library-health-fill");
    const label = document.getElementById("status-library-health-label");
    if (!wrap || !fill || !label) return;

    const score = (health && health.score != null) ? Number(health.score) : null;
    if (score == null) {
      wrap.hidden = true;
      return;
    }

    const pct = Math.max(0, Math.min(100, score));
    fill.style.width = `${pct}%`;

    let cls = "health-bar-fill ";
    if (score >= 90)      cls += "health-good";
    else if (score >= 70) cls += "health-warn";
    else                  cls += "health-bad";
    fill.className = cls;

    const status = (health && health.status) ? health.status : "";
    const staleNote = stale ? " · Bericht veraltet" : "";
    label.textContent = `${status} · ${score.toFixed(0)}/100${staleNote}`;
    wrap.hidden = false;
  }

  // ══════════════════════════════════════════════════════════════════
  // Navidrome-Status
  // ══════════════════════════════════════════════════════════════════
  async function loadFindings() {
    try {
      const res = await fetch(
        apiUrl("/api/v1/library/findings/summary"),
        { credentials: "same-origin" }
      );
      if (res.status === 401) { showOnly("login-view"); return; }
      if (!res.ok) return; // stiller Rückfall, Overview bleibt nutzbar
      const summary = await res.json();
      _overviewState.findings = summary.open || 0;
      _renderAttention();
    } catch (err) {
      // stiller Rückfall
    }
  }

  function _renderAttention() {
    const panel   = document.getElementById("attention-panel");
    const content = document.getElementById("attention-content");
    if (!panel || !content) return;

    const f = _overviewState.findings;
    panel.hidden = false;

    if (f === 0) {
      panel.classList.add("attention-panel--ok");
      panel.classList.remove("attention-panel--warn", "attention-panel--critical");
      content.innerHTML = `
        <div class="attention-empty">
          <div class="attention-badge attention-badge--ok">✓</div>
          <div>
            <div class="attention-headline">Alles sauber</div>
            <div class="attention-sub">Keine offenen Findings</div>
          </div>
        </div>`;
      return;
    }

    // Farbcodierung nach Menge
    let sev = "warn";
    if (f >= 25) sev = "critical";
    panel.classList.remove("attention-panel--ok");
    panel.classList.add(`attention-panel--${sev}`);

    const noun = f === 1 ? "Finding" : "Findings";
    content.innerHTML = `
      <div class="attention-count">
        <div class="attention-badge attention-badge--${sev}">${f}</div>
        <div>
          <div class="attention-headline">${noun} erfordern Aufmerksamkeit</div>
          <div class="attention-sub">Jetzt prüfen und priorisieren</div>
        </div>
      </div>`;
  }

  // ══════════════════════════════════════════════════════════════════
  // Jobs (KPI-Kachel mit Progressbar)
  // ══════════════════════════════════════════════════════════════════
  async function loadRecentActivity() {
    const el = document.getElementById("recent-activity-content");
    try {
      const res = await fetch(
        apiUrl("/api/v1/downloads/history?limit=5"),
        { credentials: "same-origin" }
      );
      if (res.status === 401) { showOnly("login-view"); return; }
      if (!res.ok) { el.textContent = "Verlauf nicht abrufbar."; return; }

      const body = await res.json();
      if (!body.entries.length) {
        el.innerHTML = '<p class="empty-note">Keine Aktivität.</p>';
        return;
      }

      el.innerHTML = '<div class="activity-list">' + body.entries.map((e) => {
        const ts = new Date(e.timestamp);
        const timeStr =
          ts.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" }) +
          " " +
          ts.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });

        const status = _escapeHtml(e.status);

        return `
          <div class="activity-item">
            <span class="badge badge-status-${status}">${status}</span>
            <div class="activity-main">
              <div class="activity-title">${_escapeHtml(e.title)}</div>
              <div class="activity-artist">${_escapeHtml(e.artist)}</div>
            </div>
            <div class="activity-time">${timeStr}</div>
          </div>
        `;
      }).join("") + "</div>";

    } catch (err) {
      el.textContent = "Netzwerkfehler: " + err.message;
    }
  }



  // ══════════════════════════════════════════════════════════════════
  // Library-Status
  // Nutzt ausschließlich den bestehenden persistenten Cache.
  // KEIN Library-Scan beim Laden der Overview.
  // ══════════════════════════════════════════════════════════════════
    // ══════════════════════════════════════════════════════════════════
  // Library-Status
  // Nutzt ausschließlich den bestehenden persistenten Cache.
  // KEIN Library-Scan beim Laden der Overview.
  // ══════════════════════════════════════════════════════════════════
  async function loadLibraryStatus() {
    const valueEl = document.getElementById("status-library-value");
    const hintEl  = document.getElementById("status-library-hint");

    try {
      const res = await fetch(
        apiUrl("/api/v1/library/health/cached"),
        { credentials: "same-origin" }
      );

      if (res.status === 401) {
        showOnly("login-view");
        return;
      }

      if (res.status === 404) {
        if (valueEl) valueEl.textContent = "Nicht geprüft";
        if (hintEl) hintEl.textContent = "Noch kein Health-Report vorhanden.";
        return;
      }

      if (!res.ok) {
        throw new Error(`Fehler: ${res.status}`);
      }

      const data = await res.json();
      _overviewState.health = data;

      const library = data.library || {};
      const health = data.health || {};

      if (valueEl) {
        valueEl.textContent =
          `${Number(library.files || 0).toLocaleString("de-DE")}`;
      }

      if (hintEl) {
        const parts = [
          `${Number(library.artists || 0).toLocaleString("de-DE")} Artists`,
          `${Number(library.albums || 0).toLocaleString("de-DE")} Alben`,
        ];
        if (health.status) {
          const score = health.score != null
            ? ` (${Number(health.score).toFixed(0)})` : "";
          parts.push(`Health: ${health.status}${score}`);
        }
        if (data.stale) parts.push("⚠️ veraltet");
        hintEl.textContent = parts.join(" · ");
      }

      // Health-Balken (Phase 5)
      _renderLibraryHealthBar(health, data.stale);

    } catch (err) {
      if (valueEl) valueEl.textContent = "–";
      if (hintEl) hintEl.textContent = "Library-Status nicht abrufbar.";
      console.error("Library-Status konnte nicht geladen werden:", err);
    }
  }

  // ══════════════════════════════════════════════════════════════════
  // Navidrome-Status
  // ══════════════════════════════════════════════════════════════════
  async function loadNavidromeStatus() {
    const valueEl = document.getElementById("status-navidrome-value");
    const hintEl = document.getElementById("status-navidrome-hint");

    try {
      const res = await fetch(
        apiUrl("/api/v1/navidrome/status"),
        { credentials: "same-origin" }
      );

      if (res.status === 401) {
        showOnly("login-view");
        return;
      }

      if (!res.ok) {
        throw new Error(`Fehler: ${res.status}`);
      }

      const data = await res.json();

      _overviewState.navidrome = data;

      if (data.connected) {
        if (valueEl) {
          valueEl.innerHTML =
            '<span class="status status-success">Online</span>';
        }

        if (hintEl) {
          hintEl.textContent =
            data.artist_count != null
              ? `${Number(data.artist_count).toLocaleString("de-DE")} Artists`
              : "Verbunden";
        }
      } else {
        if (valueEl) {
          valueEl.innerHTML =
            '<span class="status status-danger">Offline</span>';
        }

        if (hintEl) {
          hintEl.textContent = "Nicht erreichbar";
        }
      }

    } catch (err) {
      if (valueEl) {
        valueEl.innerHTML =
          '<span class="status status-warning">Unbekannt</span>';
      }

      if (hintEl) {
        hintEl.textContent = "Status nicht abrufbar.";
      }

      console.error("Navidrome-Status konnte nicht geladen werden:", err);
    }
  }

  // ══════════════════════════════════════════════════════════════════
  // Init
  // ══════════════════════════════════════════════════════════════════
  function initPage() {
    checkAuth().then((who) => {
      if (!who) return;
      loadSystemMetrics();
      loadLibraryStatus();
      loadNavidromeStatus();
      loadFindings();
      loadRecentActivity();
    });
  }
  initPage();
