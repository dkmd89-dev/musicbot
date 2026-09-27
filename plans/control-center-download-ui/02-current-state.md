# Current State: Control Center Download UI (D.11)

> **Document**: 02-current-state.md
> **Parent**: [Index](00-index.md)

## Existing Implementation

### What Exists

**Backend (vollständig, PR #332, committed):**
`control_center/routers/jobs.py::user_router` (Zeilen 457–461, `AccessLevel.USER`) stellt drei Endpunkte bereit:
- `POST /api/v1/jobs/download` (Zeilen 689–722) — Body `DownloadJobRequest{url: str}`, validiert serverseitig gegen `download_pipeline_core.is_supported_download_url()`, erstellt einen `JobRegistry`-Job (`kind="download_track"`), startet `_run_download_job()` als Background-Task.
- `GET /api/v1/jobs/download/{job_id}` (Zeilen 724–730) — liefert `JobSchema`, beschränkt auf den eigenen `initiator` via `_get_own_download_job_or_404()`.
- `POST /api/v1/jobs/download/{job_id}/cancel` (Zeilen 733–743) — bricht via `_cancel_bridge()` echtes Mid-Flight-Cancel aus, ebenfalls ownership-beschränkt.

`_run_download_job()` (Zeilen 501–686) ruft ausschließlich bereits Telegram-freie Fachlogik auf (`YoutubeDownloader`, `DuplicateDetector`, `services/downloader/download_pipeline_core.py`, `DownloadResultReporter`) — keine zweite Implementierung. Fortschritt wird an 5 festen Meilensteinen gesetzt (5/20/30/70/90/100 %, `registry.update_progress()`), `result` bei Erfolg enthält ausschließlich `{"outcome": "success"|"duplicate", "message": <fertig formatierter String>}`.

`GET /api/v1/downloads/history` (`control_center/routers/downloads.py`, ADMIN-only) liefert bereits alle benötigten Felder inkl. der 5 Metadaten-Checkliste-Flags (`control_center/schemas/downloads.py::DownloadHistoryEntrySchema`).

Vollständig getestet: `tests/test_control_center_download_jobs.py` (9 Tests: Erfolg/Duplikat/Fehlschlag/Abbruch/leeres Ergebnis/URL-Validierung/CSRF/Access-Level/Ownership-Isolation), `tests/test_control_center_auth.py` (3 Wiring-Tests für `/downloads/history`).

**Frontend (Lücke — Gegenstand dieses Plans):**
`control_center/templates/downloads.html` hat aktuell genau EIN Card „📋 Verlauf" mit einem Inline-`<script>`-Block (Zeilen 27–49), der `renderDownloads()`/`loadDownloads()` definiert und ausschließlich `GET /api/v1/downloads/history` abruft. Kein Start-Formular, kein Bezug zu den Job-Endpunkten, keine `downloads.js`-Datei (Glob auf `control_center/static/pages/*.js` liefert `admin.js`/`statistics.js`/`overview.js`/`navidrome.js`/`logger.js`/`health.js` — `downloads.js` fehlt als einzige).

**Etabliertes, wiederverwendbares Job-UI-Muster (bereits 3× im Code vorhanden):**
- `control_center/static/pages/health.js` — `startRepairJob()`/`_pollRepairJob()`/`cancelRepairJob()` (Zeilen ~692–757), `startLevel23Job()`/`_pollLevel23Job()` (~822–861), `startHealthScanJob()`/`_pollHealthScanJob()` (~111–142). Alle: `setInterval(..., 1000)`-Polling, Status-Rendering nach `job.status`, Start-Button disabled während `PENDING`/`RUNNING`, Cancel-Button direkt (kein Confirm-Dialog, siehe `cancelRepairJob()` Zeilen 739–753).
- `control_center/static/pages/admin.js` — `pollBackupJob()` (Zeile 257), identisches Muster für Backup-Jobs.
- `control_center/templates/library_artist_detail.html` (Zeilen 1639–1750) — Duplikat-Check-Job, identisches Muster inline im Template (statt eigener JS-Datei — dort bewusst so belassen, hier aber wegen des größeren Funktionsumfangs AR #1 anders entschieden).

Gemeinsamer globaler Helper `_escapeHtml()` (aus `common.js`, nicht neu zu definieren) wird in allen genannten Stellen konsequent auf jeden dynamischen Wert vor `innerHTML`-Einfügung angewendet.

**Telegram-Referenz für „Erneut versuchen":**
`handlers/menu/actions/download.py::handle_download_history()`/`handle_download_retry()` (Zeilen 296–379) — pro Verlaufseintrag ein `🔁`-Button, der `entry.url` erneut in denselben Pfad einspeist (`process_url()` → `handler.handle_url()`).

### Relevant Files

| File | Purpose | Changes Needed |
| ---- | ------- | --------------- |
| `control_center/templates/downloads.html` | Downloads-Seite (Template) | Start-Formular + Aktiver-Job-Card ergänzen, Inline-`<script>` entfernen (Logik nach `downloads.js`), Verlaufstabelle um 5 Metadaten-Badges + Retry-Button erweitern |
| `control_center/static/pages/downloads.js` | — (existiert nicht) | Neu anlegen: State-Machine für Start/Poll/Cancel, `renderDownloads()`/`loadDownloads()` aus dem Inline-Script übernehmen |
| `tests/test_control_center_ui.py` | UI-String-Matching-Tests | Bestehenden `test_downloads_page_has_history_panel` anpassen (prüft aktuell `loadDownloads` als Inline-Substring in `downloads.html` — nach Auslagerung muss stattdessen die Einbindung von `downloads.js` geprüft werden), neue Tests für Start-Formular, Job-Polling-Funktionen, Metadaten-Badges, Retry-Button ergänzen |
| `control_center/routers/jobs.py` | Job-Endpunkte | **Keine** — bereits vollständig |
| `control_center/schemas/jobs.py` | Job-Schemas | **Keine** — bereits vollständig |
| `control_center/routers/downloads.py` | History-Endpunkt | **Keine** — bereits vollständig |
| `control_center/schemas/downloads.py` | History-Schema | **Keine** — liefert die Metadaten-Flags bereits |
| `control_center/routers/ui.py` | `/downloads`-Route | **Keine** — reiner `_render(request, "downloads.html", "downloads")`-Aufruf ohne zusätzlichen Kontext (Zeile 72–74) |
| `services/downloader/*`, `services/jobs/*`, `klassen/download_handler.py` | Fachlogik | **Keine** |

### Code Analysis

`DownloadResultReporter` (`services/downloader/download_result_reporter.py`) liefert reinen, fertig formatierten Text zurück — **kein** Telegram-MarkdownV2-Escaping (verifiziert durch Volltextlektüre: nur Emojis, `\n`-Zeilen, Backtick-Codespans für Dateiname/Pfad). Für die Web-Anzeige genügt normales HTML-Escaping + Zeilenumbruch-Erhalt; kein Un-Escaping von Telegram-Markdown nötig.

`Job.progress` (`services/jobs/models.py`) ist ein `float`, aber in der Praxis nur eine von 6 festen Stufen (5/20/30/70/90/100) — der Status-Callback in `_run_download_job()` setzt sogar bei jedem Fortschrittsschritt innerhalb des Downloads denselben festen Wert `30.0` (Zeile ~536), unabhängig vom tatsächlichen `tracker.processed_items`. Die UI darf dies nicht als bytegenauen Fortschritt interpretieren oder suggerieren (AR #3 — Entscheidung: trotzdem als Balken anzeigen, konsistent mit den bereits bestehenden Job-Panels, die dasselbe grobe Verhalten zeigen).

## Gaps Identified

### Gap 1: Kein Start-Formular
**Current Behavior:** `/downloads` zeigt nur den Verlauf, es gibt keinen Weg, im Control Center einen Download zu starten.
**Required Behavior:** URL-Eingabe + Button, die `POST /api/v1/jobs/download` aufrufen.
**Fix Required:** Neue Card in `downloads.html` + `startDownload()` in `downloads.js`.

### Gap 2: Kein Live-Jobstatus/Cancel
**Current Behavior:** Kein UI-Element bezieht sich auf die Job-Endpunkte.
**Required Behavior:** Polling + Fortschrittsbalken/Statustext/Ergebnis/Cancel gemäß dem etablierten Job-Panel-Muster.
**Fix Required:** `downloads.js`: `_pollDownloadJob()`, `_renderDownloadJob()`, `cancelDownload()`.

### Gap 3: Verlaufstabelle ohne Metadaten-Checkliste
**Current Behavior:** `renderDownloads()` zeigt nur Status-Badge/Titel/Artist/Zeit, obwohl die API bereits `genre_ok`/`lyrics_ok`/`cover_ok`/`mb_ok`/`loudness_ok` liefert.
**Required Behavior:** 5 zusätzliche Tri-State-Badges pro Zeile.
**Fix Required:** `renderDownloads()` in `downloads.js` erweitern (reine Anzeige, kein Backend-Change).

### Gap 4: Kein „Erneut versuchen"
**Current Behavior:** Verlaufszeilen sind reine Anzeige ohne Aktion.
**Required Behavior:** Button pro Zeile, der denselben Job-Start-Endpunkt mit `url=entry.url` aufruft.
**Fix Required:** `renderDownloads()` + neuer Klick-Handler in `downloads.js`, ruft dieselbe `startDownload(url)`-Funktion wie das Formular auf (kein Code-Duplikat).

## Dependencies

### Internal Dependencies
- `control_center/static/common.js` (globale Helper: `_escapeHtml`, `apiUrl`, `checkAuth`, `showOnly`, `_loadInto`) — wird vorausgesetzt, nicht verändert
- Bestehendes Tabler-CSS + `common.css`-Klassen (`.badge-status-*`, `.progress`/`.progress-bar`) — wird wiederverwendet, keine neuen Klassen erwartet nötig
- `control_center/app.py` Static-Mount für `static/pages/*.js` — bereits vorhanden (alle anderen Seiten nutzen es identisch)

### External Dependencies
- Keine neuen. Kein neues npm-Package, kein neues Python-Package.

## Risks and Concerns

| Risk | Likelihood | Impact | Mitigation |
| ---- | ---------- | ------ | ---------- |
| Bestehender Test `test_downloads_page_has_history_panel` bricht durch die Auslagerung nach `downloads.js` | Hoch (sicher, da bewusste Änderung) | Niedrig | Test bewusst mit angepasst (Teil dieses Plans, nicht versehentliche Regression), siehe `07-testing-strategy.md` |
| Nutzer interpretiert den groben Meilenstein-Fortschrittsbalken als bytegenau | Mittel | Niedrig (kosmetisch) | Bewusste, dokumentierte AR-#3-Entscheidung, identisch zu bereits bestehenden Job-Panels — kein neues Risiko, nur ein bereits akzeptiertes Muster übernommen |
| Cross-Process-Schreibzugriff auf `DuplicateCache`/`DownloadHistoryStore` (Bot- und CC-Prozess gleichzeitig aktiv) — Races beim gleichzeitigen Schreiben | Unbekannt/nicht validiert (Audit-Dokument Abschnitt 5.6) | Potenziell mittel | **Explizit außerhalb des Scopes dieser Phase** — durch mehr UI-Nutzung (mehr CC-Downloads) steigt die Eintrittswahrscheinlichkeit, aber die UI-Phase selbst führt keine neue Schreiblogik ein. Separates, eigenständig zu entscheidendes Follow-up (bereits im Audit-Dokument benannt) |
| `DownloadResultReporter`-Textformat ändert sich künftig (z. B. neue Zeile) und bricht ein zu eng gefasstes String-Matching im UI-Test | Niedrig | Niedrig | Tests prüfen auf das Vorhandensein escapeter Kernbegriffe (Titel/Artist aus dem Fake-Result), nicht auf exakten Volltext-Match des gesamten `message`-Strings |
| `downloads.js` dupliziert versehentlich Fachlogik (z. B. SSRF-Domain-Allowlist) | Niedrig (explizit als Nicht-Ziel im Auftrag benannt) | Hoch, falls es passiert | Code-Review-Kriterium in `03-02-frontend-js.md`: JS darf `is_supported_download_url()` NICHT nachbauen, nur den 422-Fehler des Servers anzeigen |
