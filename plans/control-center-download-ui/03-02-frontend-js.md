# Frontend: JavaScript: Control Center Download UI (D.11)

> **Document**: 03-02-frontend-js.md
> **Parent**: [Index](00-index.md)

## Overview

Neue `control_center/static/pages/downloads.js`. Übernimmt die bestehende Verlaufs-Logik (`renderDownloads`/`loadDownloads`) aus dem bisherigen Inline-Script 1:1 (Regel 2 — kein unbewusster Verhaltenswechsel) und ergänzt Start/Poll/Cancel/Retry für den eigenen Download-Job, nach dem in `health.js`/`admin.js`/`library_artist_detail.html` bereits etablierten Muster.

## Architecture

### Current Architecture
Kein `downloads.js`. Logik liegt inline in `downloads.html`.

### Proposed Changes
Eine neue Datei, Modul-Ebene-Funktionen (kein IIFE — konsistent mit `statistics.js`), Initialisierung am Dateiende analog `statistics.js::initPage()`.

## Implementation Details

### State (Modul-Ebene, analog `_dupCheckTimer`/`_dupCheckJobId` in `library_artist_detail.html` bzw. `_currentRepairJobId`/`_repairJobPollTimer` in `health.js`)

```javascript
let _currentDownloadJobId = null;
let _downloadJobPollTimer = null;
```

### Neue Funktionen

```javascript
function _setDownloadFormBusy(busy)
// download-start-btn.disabled = busy; download-url-input.disabled = busy

function _stopDownloadPolling()
// clearInterval(_downloadJobPollTimer); _downloadJobPollTimer = null

function _tierBadge(value)
// value: true|false|null -> {klasse: "bg-success"|"bg-danger"|"bg-secondary", icon} — reine Formatierungshilfe für die 5 Metadaten-Flags (AR #4), tri-state, null NIE als false behandeln

function _renderDownloadResult(job)
// job.status === "SUCCEEDED": alert-success (outcome=success) oder alert-info (outcome=duplicate),
//   Inhalt = escaped(job.result.message) mit erhaltenen Zeilenumbruechen (weisser-space: pre-wrap)
//   und Backtick-Codespans zu <code> konvertiert (AR #7)
// job.status === "FAILED": alert-danger, Inhalt = escaped(job.error || "Unbekannter Fehler")
// job.status === "CANCELLED": alert-secondary, Inhalt = "Download abgebrochen." (+ escaped(job.message) falls vorhanden)

function _renderDownloadJob(job)
// PENDING/RUNNING: Progress-Bar (job.progress) + escaped(job.message) + Cancel-Button (mit
//   Klick-Handler auf cancelDownload gebunden bei jedem Render-Aufruf neu, da das Element
//   bei jedem Render-Zyklus neu erzeugt wird — kein Event-Leak, da das alte Element mitsamt
//   Listener aus dem DOM entfernt wird)
// sonst (terminal): _stopDownloadPolling(); _setDownloadFormBusy(false); _renderDownloadResult(job)

async function _pollDownloadJob(jobId)
// GET /api/v1/jobs/download/{jobId} — Muster identisch zu _pollRepairJob (health.js Zeile ~692):
//   401 -> showOnly("login-view"), _stopDownloadPolling(), return
//   !res.ok -> return (naechster Poll-Tick versucht es erneut, kein Abbruch bei transientem Fehler)
//   sonst -> _renderDownloadJob(await res.json())

async function startDownload(url)
// url als Parameter (nicht nur aus dem Input gelesen) - ermoeglicht Wiederverwendung durch
//   den Retry-Button (AR #11), ohne das sichtbare Eingabefeld zu manipulieren
// _setDownloadFormBusy(true); POST /api/v1/jobs/download {url}
//   401 -> showOnly("login-view")
//   !res.ok (z.B. 422) -> Fehlermeldung escaped in #download-status-content, _setDownloadFormBusy(false)
//   ok -> _currentDownloadJobId = job.job_id; _renderDownloadJob(job); _stopDownloadPolling();
//         _downloadJobPollTimer = setInterval(() => _pollDownloadJob(_currentDownloadJobId), 1000)

async function cancelDownload()
// POST /api/v1/jobs/download/{_currentDownloadJobId}/cancel — Muster identisch zu
//   cancelRepairJob (health.js Zeile 739): Button disabled waehrend des Requests,
//   KEIN window.confirm()-Dialog (kein Precedent dafuer im bestehenden Code)

function renderDownloads(el, body)
// aus dem bisherigen Inline-Script uebernommen + erweitert: pro entry zusaetzlich die 5
//   _tierBadge()-Badges + einen "download-retry-btn" mit data-url (siehe 03-01)

function loadDownloads()
// unveraendert aus dem bisherigen Inline-Script uebernommen:
//   _loadInto("downloads-content", "/api/v1/downloads/history?limit=10", renderDownloads)
```

### Event-Delegation für den Retry-Button

Da Verlaufszeilen bei jedem 30s-Refresh komplett neu gerendert werden (bestehendes `innerHTML`-Ersetzungsmuster), wird der Klick-Handler NICHT pro Zeile einzeln per `addEventListener` gebunden (würde bei jedem Refresh neue, nie entfernte Listener anhäufen — Memory-Leak-Risiko). Stattdessen EIN delegierter Listener auf `#downloads-content` (Init-Zeit, einmalig):

```javascript
document.getElementById("downloads-content").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".download-retry-btn");
  if (btn) startDownload(btn.dataset.url);
});
```

Dieses Delegationsmuster ist neu gegenüber den bestehenden Referenzseiten (dort gibt es keine sich wiederholt neu rendernden Buttons mit Aktion) — explizit dokumentiert, da kein 1:1-Precedent existiert, aber Standard-DOM-Praxis für genau dieses Problem (kein neues Framework, reines Vanilla-JS-Muster).

### Initialisierung (Dateiende, analog `statistics.js::initPage()`)

```javascript
async function initDownloadsPage() {
  document.getElementById("download-start-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const input = document.getElementById("download-url-input");
    const url = input.value.trim();
    if (url) startDownload(url);
  });
  document.getElementById("downloads-content").addEventListener("click", (ev) => {
    const btn = ev.target.closest(".download-retry-btn");
    if (btn) startDownload(btn.dataset.url);
  });
  loadDownloads();
  setInterval(loadDownloads, 30000); // unveraendert aus dem bisherigen Inline-Script
}

initDownloadsPage();
```

- Kein clientseitiger Nachbau der `is_supported_download_url()`-Domain-Allowlist — `startDownload()` sendet jede nicht-leere URL an den Server und zeigt dessen `422`-Antwort escaped an (Auftragsvorgabe „keine Fachlogik in downloads.js").

## Integration Points
- `common.js`: `_escapeHtml`, `apiUrl`, `checkAuth`, `showOnly`, `_loadInto` — vorausgesetzt, nicht verändert.
- `control_center/routers/jobs.py` (`user_router`) + `control_center/routers/downloads.py` — konsumiert, nicht verändert.

## Error Handling

| Error Case | Handling Strategy | AR Ref |
| ---------- | ------------------ | ------ |
| `401` bei Poll oder Start | `showOnly("login-view")`, Polling stoppen (identisch zu allen bestehenden Job-Panels) | — (bestehendes Muster) |
| Netzwerkfehler bei `startDownload`/`cancelDownload` (`fetch` wirft) | `try/catch`, Fehlermeldung escaped anzeigen, Button-Zustand zurücksetzen | — (bestehendes Muster, `health.js`/`library_artist_detail.html`) |
| `job.result.message` enthält Backticks | Zu `<code>` konvertiert, kein Roh-Backtick sichtbar | AR #7 |
| Metadaten-Flag ist `null` | `bg-secondary`, nicht `bg-danger` | AR #4 (Datenintegrität aus `DownloadHistoryEntry`) |
| Dynamische Werte jeder Art vor DOM-Einfügung | `_escapeHtml()` ausnahmslos | AR #10 |
| Retry-Button-Klick während bereits ein eigener Job läuft | `startDownload()` wird trotzdem aufgerufen — Server lehnt technisch nichts ab (kein Limit pro Nutzer außer `download_slot()`), UI zeigt aber den neuen Job an und ersetzt die Anzeige des vorherigen (konsistent mit AR #2 „nur ein sichtbarer aktiver Job") | AR #2 |

> **Traceability:** Jede Design-Entscheidung referenziert den Ambiguity-Register-Eintrag (AR #), der sie aufgelöst hat. Siehe `00-ambiguity-register.md`.

## Testing Requirements
- String-Matching-Tests gegen den ausgelieferten `downloads.js`-Quelltext (identisches Muster zu bestehenden JS-Tests in `tests/test_control_center_ui.py`, z. B. für `health.js`/`logger.js`): Vorhandensein der Funktionsnamen `startDownload`, `cancelDownload`, `_pollDownloadJob`, `renderDownloads`, `_escapeHtml`-Aufrufe an den kritischen Stellen
- Kein Browser-Runtime-Test verfügbar (bestehende, bereits im Code dokumentierte Einschränkung — kein neues Testing-Gap, siehe `02-current-state.md`)
