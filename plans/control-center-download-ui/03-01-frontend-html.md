# Frontend: HTML: Control Center Download UI (D.11)

> **Document**: 03-01-frontend-html.md
> **Parent**: [Index](00-index.md)

## Overview

Erweitert `control_center/templates/downloads.html` um zwei neue Elemente (Start-Formular + Aktiver-Job-Anzeige, in EINER Card zusammengefasst, analog zum Repair-Panel-Muster in `health.html`) und die bestehende Verlaufs-Card um Metadaten-Badges + Retry-Button. Entfernt das Inline-`<script>`, bindet stattdessen `downloads.js` ein.

## Architecture

### Current Architecture
Eine Card „📋 Verlauf" mit `<div id="downloads-content">`, Inline-`<script>` am Dateiende.

### Proposed Changes
Zwei Cards in dieser Reihenfolge (Start/Status zuerst, Verlauf danach — Download-Start ist die primäre Aktion der Seite):

1. **Card „⬇️ Download starten"** — Start-Formular + Aktiver-Job-Status (ein und dieselbe Card, Inhalt wechselt je nach Zustand, analog `health.html`s Repair-Card)
2. **Card „📋 Verlauf"** — bestehend, erweitert um Metadaten-Badges + Retry-Button pro Zeile

## Implementation Details

### Markup — Card „Download starten"

```html
<div class="card mb-3">
  <div class="card-header">
    <h3 class="card-title">⬇️ Download starten</h3>
  </div>
  <div class="card-body">
    <form id="download-start-form" class="row g-2 align-items-center mb-3">
      <div class="col-auto flex-fill">
        <input
          type="text"
          id="download-url-input"
          class="form-control"
          placeholder="YouTube-URL (Video oder Playlist)"
          autocomplete="off"
          required
        />
      </div>
      <div class="col-auto">
        <button type="submit" id="download-start-btn" class="btn btn-primary">
          Download starten
        </button>
      </div>
    </form>
    <div id="download-status-content"></div>
  </div>
</div>
```

- `<form>` statt nacktem Button: ermöglicht Enter-Submit im URL-Feld ohne zusätzlichen JS-Listener auf `keydown` (Standard-Formularverhalten, `preventDefault()` in `downloads.js` übernimmt den `fetch()`-Aufruf statt eines echten Page-Submits).
- `#download-status-content` ist bei Seitenaufruf leer (Idle-Zustand: kein Job aktiv) — wird von `downloads.js` befüllt, sobald ein Job existiert. Leer bleibt bewusst ohne Platzhaltertext (kein „Kein aktiver Download"-Rauschen bei jedem Seitenaufruf, konsistent mit dem leeren `#duplicate-check-content` vor dem ersten Start in `library_artist_detail.html`).
- Kein separates `download-cancel-btn`-Element im statischen Markup (anders als `health.html`s `repair-cancel-btn`, der immer im DOM steht und nur `disabled` togglet) — **Entscheidung für dieses Dokument**: der Cancel-Button wird von `_renderDownloadJob()` dynamisch NUR während `PENDING`/`RUNNING` in `#download-status-content` gerendert (weniger permanentes DOM, Klick-Handler wird bei jedem Render per `addEventListener` auf das frisch gerenderte Element gesetzt — siehe `03-02-frontend-js.md` §Event-Delegation).

### Markup — Card „Verlauf" (erweitert)

Bestehende Struktur bleibt, `id="downloads-content"` bleibt (keine Breaking Change für den Container selbst — nur der Inhalt, den `renderDownloads()` hineinschreibt, wird um Badges + Button erweitert):

```html
<div class="card">
  <div class="card-header">
    <h3 class="card-title">📋 Verlauf</h3>
  </div>
  <div class="card-body">
    <div id="downloads-content">Lädt…</div>
  </div>
</div>
```

Pro Zeile (von `renderDownloads()` in `downloads.js` erzeugt, hier nur die Ziel-Struktur dokumentiert):

```html
<div class="row-item">
  <div class="row-item-main">
    <span class="badge badge-status-${status}">${statusLabel}</span>
    <span>${escapedArtist} – ${escapedTitle}</span>
    <span class="text-secondary">${timestamp}</span>
  </div>
  <div class="row-item-badges">
    <span class="badge bg-${genreOkColor}" title="Genre">🏷️</span>
    <span class="badge bg-${lyricsOkColor}" title="Lyrics">📜</span>
    <span class="badge bg-${coverOkColor}" title="Cover">🖼️</span>
    <span class="badge bg-${mbOkColor}" title="MusicBrainz">🎼</span>
    <span class="badge bg-${loudnessOkColor}" title="Loudness">🔊</span>
    <button type="button" class="btn btn-sm btn-outline-secondary download-retry-btn" data-url="${escapedUrl}">
      🔁
    </button>
  </div>
</div>
```

- Tri-State-Farbe (`genreOkColor` etc.): `true` → `success` (grün), `false` → `danger` (rot), `null`/`undefined` → `secondary` (grau, „keine Aussage möglich" — dreiwertige Semantik aus `DownloadHistoryEntry`-Docstring erhalten, NICHT stillschweigend als `false` behandeln, CLAUDE.md §14 Cache-Grundsatz sinngemäß auf Datenintegrität übertragen)
- `data-url="${escapedUrl}"` auf dem Retry-Button — `downloads.js` liest das Attribut beim Klick aus (Event-Delegation, siehe `03-02-frontend-js.md`), kein separates Popup/Modal.
- `${escapedUrl}` in einem HTML-Attribut: `_escapeHtml()` deckt Attribut-Kontext ab (identisch zur bestehenden Nutzung in `admin.js`/`health.js` für Attributwerte) — kein zusätzlicher Attribut-Escaper nötig.

### Integration Points
- `<script src="{{ base_path }}/static/pages/downloads.js" defer></script>` am Ende von `downloads.html`, ersetzt das bisherige Inline-`<script>` (gleiche Einbindungsart wie bei allen anderen Seiten, z. B. `health.html` — exakter `<script>`-Tag wird beim Implementieren 1:1 aus einer Referenzseite wie `statistics.html` übernommen, um Pfad-/Attribut-Konventionen (`{{ base_path }}`, `defer`) nicht zu erfinden).
- Kein neuer Template-Kontext von `control_center/routers/ui.py` nötig (siehe `02-current-state.md`).

## Error Handling

| Error Case | Handling Strategy | AR Ref |
| ---------- | ------------------ | ------ |
| Leeres URL-Feld bei Submit | HTML5 `required`-Attribut verhindert Submit clientseitig (kein Server-Roundtrip für den trivialen Fall) | — (universell, keine Fachlogik) |
| Serverseitig abgelehnte URL (`422`) | Fehlermeldung des Servers escaped in `#download-status-content` anzeigen, Formular bleibt nutzbar | AR #10 |
| Dynamische Werte in Verlaufszeilen/Status (Titel, Artist, URL, message, error) | Ausnahmslos `_escapeHtml()` vor Einfügung | AR #10 |
| Tri-State `null` bei Metadaten-Flags | Grauer/`secondary`-Badge, NICHT als „nicht erfolgreich" (rot) interpretieren | — (Datenintegrität, aus `DownloadHistoryEntry`-Docstring übernommen) |

> **Traceability:** Jede Design-Entscheidung referenziert den Ambiguity-Register-Eintrag (AR #), der sie aufgelöst hat. Siehe `00-ambiguity-register.md`.

## Testing Requirements
- UI-String-Matching-Tests (siehe `07-testing-strategy.md`): Vorhandensein von `id="download-url-input"`, `id="download-start-btn"`, `id="download-status-content"`, `<script src=".../downloads.js"`, Abwesenheit der alten Inline-`loadDownloads`-Definition in `downloads.html` selbst
