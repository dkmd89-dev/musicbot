# Requirements: Control Center Download UI (Client Consolidation Phase D.11)

> **Document**: 01-requirements.md
> **Parent**: [Index](00-index.md)

## Feature Overview

Das Control Center bekommt eine vollständige Downloads-Web-Oberfläche als zweiten Client der bestehenden Download-Domain (Telegram = erster Client). Der Backend-Weg (D.10) ist bereits vollständig implementiert, getestet und committed — dieser Plan liefert ausschließlich die fehlende UI-Schicht: Download starten, Live-Jobstatus/Fortschritt beobachten, abbrechen, Ergebnis sehen, sowie eine um die Metadaten-Checkliste und einen „Erneut versuchen"-Button erweiterte Verlaufstabelle.

## Functional Requirements

### Must Have
- [ ] Start-Formular (URL-Eingabe + Button) auf `/downloads`, sendet `POST /api/v1/jobs/download`
- [ ] Live-Jobstatus für den eigenen, gerade laufenden Job: Fortschrittsbalken (`job.progress`) + Statustext (`job.message`), Polling `GET /api/v1/jobs/download/{job_id}` alle 1000ms (AR #3)
- [ ] Cancel-Button, aktiv während `PENDING`/`RUNNING`, ruft `POST /api/v1/jobs/download/{job_id}/cancel`
- [ ] Ergebnisanzeige nach Abschluss: `SUCCEEDED`+`outcome=success` → Erfolg, `SUCCEEDED`+`outcome=duplicate` → Duplikat-Meldung, `FAILED` → `job.error`, `CANCELLED` → Abbruch-Hinweis — jeweils 1:1 aus dem vom Backend gelieferten, bereits fertig formatierten Text (AR #5)
- [ ] Verlaufstabelle (bestehend) erweitert um die 5 Metadaten-Checkliste-Badges (`genre_ok`/`lyrics_ok`/`cover_ok`/`mb_ok`/`loudness_ok`, tri-state) (AR #4)
- [ ] „🔁 Erneut versuchen"-Button pro Verlaufszeile, sendet `POST /api/v1/jobs/download` mit `url=entry.url` desselben Eintrags (AR #11)
- [ ] Neue `control_center/static/pages/downloads.js`, bestehende Inline-Logik (`loadDownloads`/`renderDownloads`) wird dorthin übernommen (AR #1)
- [ ] Immer nur EIN eigener aktiver Job gleichzeitig im UI (Start-Button deaktiviert, solange der eigene Job läuft) (AR #2)

### Should Have
_(keine zusätzlichen Punkte — Scope bewusst minimal gehalten, siehe Out of Scope)_

### Won't Have (Out of Scope)
- Neue Download-Pipeline, neue yt-dlp-Integration, neue Duplicate-Engine, neue History-Engine (Auftragsvorgabe, ohnehin nicht nötig — Backend vollständig vorhanden)
- Pause/Resume (nicht vorhanden, nicht Teil dieser Phase)
- Globale Telegram+CC-Live-Download-Aggregation — d. h. Telegram-initiierte, fremde Downloads im CC sichtbar machen (Architektur unterstützt das laut Audit-Dokument Abschnitt 5.2 aktuell nicht — `ActiveDownloadRegistry` ist reiner In-Process-Zustand des Bot-Prozesses)
- Speed/ETA-Anzeige — keine strukturierten Backend-Daten vorhanden (`ProgressTracker` kennt nur `processed_items`/`total_items`/`current_item`, kein Byte-/Zeitfortschritt)
- Steuerbare Metadata-/Cover-/Lyrics-/MusicBrainz-/Loudness-/Genre-Optionen im Start-Formular — existieren nirgends im Code als steuerbarer Parameter, auch nicht in Telegram (verifiziert, keine erfundene Option)
- Mehrere gleichzeitige eigene Downloads als Liste im UI (AR #2)
- Backend-/Service-/Schema-Änderungen jeder Art — alle benötigten Endpunkte/Felder existieren bereits vollständig und getestet
- Cross-Process-Race-/Locking-Analyse für `DuplicateCache`/`DownloadHistoryStore` — offenes, laut Audit-Dokument Abschnitt 5.6 explizit separat zu entscheidendes Risiko, wird durch diese UI-Phase nicht mitgelöst
- Änderungen am Dashboard-Downloads-Panel in `overview.html`/`overview.js` (AR #8)
- Manuelle Duplicate-Entscheidung im Frontend — die Backend-Entscheidung (`DuplicateDetector.check_for_duplicates()`) ist bereits vollautomatisch, kein Override-Pfad existiert

## Technical Requirements

### Performance
- Polling-Intervall für den eigenen aktiven Job: 1000ms (identisch zu allen bestehenden Job-Panels: `health.js` Repair/Level3/Health-Scan, `admin.js` Backup, Duplikat-Check in `library_artist_detail.html`)
- Verlaufstabelle: bestehendes 30000ms-Auto-Refresh unverändert

### Compatibility
- Ausschließlich bestehendes Tabler-CSS + Vanilla JS, kein neues UI-Framework, keine neue CSS-Bibliothek, keine unnötige Erweiterung von `common.css` (Auftragsvorgabe)

### Security
- CSRF: bestehender `verify_same_origin`-Schutz auf `POST`-Endpunkten bleibt unverändert (kein manuelles CSRF-Token nötig, Browser setzt `Origin` automatisch bei `same-origin`-Fetch)
- XSS: jeder dynamische Wert (`job.message`, `job.error`, `entry.title`, `entry.artist`, `entry.url`) MUSS vor DOM-Einfügung durch `_escapeHtml()` laufen — keine Ausnahme (AR #10)
- Keine Duplizierung der serverseitigen SSRF-Domain-Allowlist (`is_supported_download_url()`) im Frontend — das Frontend zeigt nur den vom Server gelieferten `422 URL_NOT_SUPPORTED`-Fehler an, validiert selbst nur auf "nicht leer"

## Scope Decisions

| Decision | Options Considered | Chosen | Rationale | AR Ref |
| -------- | ------------------- | ------ | --------- | ------ |
| `downloads.js` anlegen vs. Inline-Script behalten | A/B | A — neue Datei | Konsistenz mit allen anderen CC-Seiten | AR #1 |
| Mehrere gleichzeitige eigene Downloads im UI | A/B | A — nur ein aktiver Job | Entspricht dem etablierten Job-Panel-Muster, deutlich weniger neuer UI-Zustand | AR #2 |
| Fortschrittsanzeige-Stil | A/B | A — numerischer Progress-Bar | Konsistent mit Repair-/Duplikat-Check-Panels, die dieselben groben Meilensteine genauso zeigen | AR #3 |
| Metadaten-Checkliste in Verlaufstabelle | In/Out of Scope | In Scope | Backend liefert die Daten bereits vollständig, reine UI-Ergänzung | AR #4 |
| Ergebnis-Darstellung | A/B | A — 1:1 vorformatierter Block | Garantierte Telegram-Parität ohne fragiles Parsen eines Anzeige-Strings | AR #5 |
| Test-Dateikonvention | Generisches `.spec.test.py` vs. Projekt-Konvention | Projekt-Konvention (`tests/test_control_center_ui.py` erweitert) | pytest-Default-Discovery + CLAUDE.md §8.A | AR #6 |
| Backtick-Codespans-Rendering | — | Konvertierung zu `<code>` | Kosmetisch, Precedent in `admin.js` | AR #7 |
| Overview-Dashboard-Panel anfassen | In/Out of Scope | Out of Scope | Auftrags-Scope nennt explizit nur `downloads.html` + Referenzseiten | AR #8 |
| Job-Status-Persistenz über Reload | Neu bauen vs. Precedent übernehmen | Precedent übernehmen (keine Persistenz) | Identisch zu allen bestehenden Job-Panels, kein unbewusster Verhaltenswechsel | AR #9 |
| Escaping-Pflicht dynamischer Werte | — | Verpflichtend | CLAUDE.md P0 Security, bereits einmal als XSS-Fund in genau diesem Panel behoben | AR #10 |
| „Erneut versuchen"-Button | In/Out of Scope | In Scope | Echte Telegram-Parität (Nutzer-Priorität 4 laut Telegram-Code), minimaler Zusatzaufwand (ruft bestehenden Endpunkt) | AR #11 |

> **Traceability:** Jede Scope-Entscheidung referenziert den Ambiguity-Register-Eintrag (AR #), der sie aufgelöst hat. Siehe `00-ambiguity-register.md`.

## Telegram-Paritätsmatrix

> Legende Kategorie: 1 vollständig vorhanden · 2 Backend vorhanden, UI fehlt · 3 Domain vorhanden, API fehlt · 4 API vorhanden, UI fehlt · 5 Telegram-spezifisch, nicht erforderlich · 6 echte fachliche Lücke · 7 bewusst außerhalb des Scopes

| Funktion | Telegram | Domain | CC API | CC UI (vor diesem Plan) | Kategorie | Maßnahme |
| -------- | -------- | ------ | ------ | ------------------------ | --------- | -------- |
| Download starten (URL) | ✅ Text-Nachricht | ✅ `YoutubeDownloader`/`download_pipeline_core.py` | ✅ `POST /api/v1/jobs/download` | ❌ kein Formular | 4 | UI bauen (dieser Plan) |
| Playlist-Download | ✅ automatisch erkannt (`list=`) | ✅ | ✅ (generisches URL-Feld, keine separate Option nötig) | ❌ | 4 | Durch generisches URL-Feld abgedeckt (dieser Plan) |
| Live-Fortschritt/Statustext | ✅ Message-Edits | ✅ `ProgressTracker` | ✅ `job.progress`/`job.message` (grobe Meilensteine) | ❌ | 4 | UI bauen (dieser Plan) |
| Cancel | ✅ Inline-Button | ✅ `ActiveDownload.cancel_event` | ✅ `POST .../cancel` (`_cancel_bridge()`, echtes Mid-Flight-Cancel) | ❌ | 4 | UI bauen (dieser Plan) |
| Ergebnisanzeige (Erfolg/Duplikat/Fehlschlag/Abbruch) | ✅ `DownloadResultReporter`-Text | ✅ | ✅ `result.message`/`error` im `JobSchema` | ❌ | 4 | UI bauen (dieser Plan) |
| Download-Verlauf (eigener/chat-übergreifend) | ✅ `get_recent(chat_id)` | ✅ `DownloadHistoryStore` | ✅ `GET /api/v1/downloads/history` (ADMIN, chat-übergreifend) | ✅ teilweise (Titel/Artist/Status/Zeit) | 2 | UI erweitern (dieser Plan) |
| Metadaten-Checkliste (genre/lyrics/cover/mb/loudness) | ✅ eingebettet in Verlaufsanzeige | ✅ | ✅ Schema liefert bereits alle 5 Flags | ❌ nicht angezeigt | 2 | UI ergänzen (dieser Plan) |
| „🔁 Erneut versuchen" | ✅ `dl:retry:{position}` | ✅ (ruft denselben Pfad wie ein normaler Download auf) | ✅ (derselbe `POST /api/v1/jobs/download`, kein neuer Endpunkt nötig) | ❌ | 4 | UI ergänzen (dieser Plan, AR #11) |
| Speed/ETA | ❌ nicht strukturiert vorhanden (auch Telegram zeigt nur Item-Zähler, keine Byte-/Zeitrate) | ❌ `ProgressTracker` kennt keine Rate | — | — | 7 | Bewusst außerhalb des Scopes (Auftragsvorgabe) |
| Steuerbare Metadata/Cover/Lyrics/MusicBrainz/Loudness/Genre-Option | ❌ nicht vorhanden | ❌ läuft immer automatisch, kein Opt-in/Opt-out-Parameter | ❌ `DownloadJobRequest` hat nur `url` | — | 7 | Keine Option erfinden (Auftragsvorgabe „keine erfundenen Optionen") |
| Mehrere gleichzeitige Downloads gleichzeitig sichtbar | (Telegram: je Chat/Nachricht faktisch parallel möglich) | (technisch nicht limitiert außer globaler `download_slot()`-Grenze) | (kein Limit pro Nutzer) | — | 5 | Web-UI-spezifische, bewusste Entscheidung: nur 1 aktiver Job im UI (AR #2) — kein Telegram-Paritätsanspruch hier |
| Live-Status fremder/Telegram-initiierter Downloads im CC | — | — | — | — | 7 | Explizit separater, nicht Teil dieser Phase (Audit-Dokument Abschnitt 5.2) |
| Duplicate Detection (automatische Entscheidung) | ✅ vollautomatisch | ✅ `DuplicateDetector.check_for_duplicates()` | ✅ bereits in `_run_download_job()` integriert | (über Ergebnisanzeige sichtbar) | 1 | Bereits vollständig vorhanden, nur die Ergebnisanzeige selbst fehlt (siehe oben) |

## Acceptance Criteria

1. [ ] `/downloads` zeigt ein Start-Formular; eine gültige, vom Server akzeptierte URL erstellt einen Job und zeigt dessen Live-Status an
2. [ ] Eine vom Server abgelehnte URL (`422 URL_NOT_SUPPORTED`) zeigt die Serverfehlermeldung an, ohne dass ein Job erstellt wird
3. [ ] Während `PENDING`/`RUNNING` ist der Start-Button deaktiviert, der Cancel-Button aktiv, der Fortschrittsbalken + Statustext aktualisieren sich per 1s-Polling
4. [ ] Cancel während eines laufenden Jobs führt zu `CANCELLED` und einer entsprechenden Anzeige; der Start-Button wird danach wieder aktiv
5. [ ] `SUCCEEDED`/`outcome=success`, `SUCCEEDED`/`outcome=duplicate` und `FAILED` zeigen jeweils die korrekte, unveränderte Backend-Nachricht escaped an
6. [ ] Die Verlaufstabelle zeigt zusätzlich zu Status/Titel/Artist/Zeit die 5 Metadaten-Badges korrekt tri-state (✅/❌/➖)
7. [ ] Ein Klick auf „🔁 Erneut versuchen" bei einem Verlaufseintrag startet einen neuen Job mit derselben URL
8. [ ] Kein dynamischer Wert erscheint ungeescaped im DOM (verifiziert per Test mit einem präparierten Titel/URL)
9. [ ] `tests/test_control_center_ui.py` (angepasst + erweitert) grün, `tests/test_control_center_download_jobs.py` weiterhin grün (unverändert, keine Backend-Änderung)
10. [ ] Dokumentation aktualisiert: `docs/audits/CLIENT_CONSOLIDATION_PHASE_D_DOWNLOAD_RUNTIME_2026-09-27.md` Abschnitt 6/„Nächster Schritt" auf „✅ CLOSED" nachgezogen, `docs/FINDINGS_INDEX.md`-Zeile „Downloads nicht aus dem Control Center startbar" auf vollständig geschlossen aktualisiert (nur der D.11-Teil; das Cross-Process-Risiko aus Abschnitt 5.6 bleibt explizit offen)
