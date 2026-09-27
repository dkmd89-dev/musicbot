# Client Consolidation — Phasen A–D, Fokus Phase D (Download-Runtime)

**Auftrag:** `/mnt/128ssd/client_consolidation.txt` ("MUSICBOT — client consolidation & NEXT PARITY PHASE").
**Ziel:** Telegram = Client, Control Center = Client, `services/` = zentrale Fachlogik.
**Stand dieses Dokuments:** 2026-09-27 (CC-Job-Verdrahtung für Downloads implementiert, CC-UI noch offen).

---

## 1. Status-Übersicht

| Phase | Inhalt | Status | Beleg |
|---|---|---|---|
| A | User Management konsolidieren | ✅ CLOSED | PR #326 (`d3ca2cf`) |
| B | Logger-Reste bereinigen | ✅ CLOSED | PR #327 (`4b70637`) |
| C | Web-Parity-Matrix aktualisieren | ✅ CLOSED (reine Doku-Phase) | PR #328 (`f8e3787`) |
| D.1–D.6 | Downloads: Inventar + Architektur-Analyse | ✅ CLOSED | dieses Dokument, Abschnitt 5.1 |
| D.7 | Downloads: Architekturentscheidung (Nutzer) | ✅ ENTSCHIEDEN | Abschnitt 5.1/5.2 |
| D.8 | Concurrency-Slot-Mechanismus (Option B) | ✅ IMPLEMENTED | PR #329 (`c27dbf1`), PR #330 (`03965b8`) |
| D.9 | Telegram-freie Pipeline-Extraktion | ✅ IMPLEMENTED | PR #331 (`e5650bd`) |
| D.10 | **CC Job-Verdrahtung (Download starten/Status/Cancel)** | ✅ IMPLEMENTED | Abschnitt 5.4 (Commit ausstehend, siehe dort) |
| D.11 | **CC Download-UI** (Dashboard/Downloads → Download starten → Jobstatus → Fortschritt/Ergebnis → Cancel) | 🔲 OPEN — **nächster Schritt** | Abschnitt 6 |
| — | Cross-Process-Schreibzugriff Duplicate-/History-Dateien | ⚠️ **RISIKO, NICHT VALIDIERT** | Abschnitt 5.6 |

---

## 2. Phase A — User Management (CLOSED)

Single Write Path: `handlers/admin/user_management_handler.py::UserManagementHandler` besitzt keine eigene Rollen-/Owner-Guard-/Permission-/Persistenzlogik mehr — delegiert vollständig an `services/user_admin.py`. `services/user_data.py::update_user_data(mutator)` sperrt den kompletten Load→Mutator→Save-Zyklus prozessübergreifend per `fcntl.flock` — sowohl Telegram als auch `control_center/routers/admin.py` nutzen ausschließlich diesen Zyklus.

Details/Tests: `docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md` §2.3 B / `docs/FINDINGS_INDEX.md` Zeile "User-Verwaltung: Doppelimplementierung" (CLOSED).

## 3. Phase B — Logger-Reste (CLOSED)

`enhanced_logger_menu_handler.py::_load_module_configs()`/`_save_module_configs()` lesen/schreiben jetzt über `services/logger_admin.py::read_logger_config()`/`atomic_write_json()` statt eigener, nicht-atomarer `json.load`/`json.dump`. Zusätzlich B.2 (Modul-Inventar-Abgleich): 71 im Code aktive, aber in `data/module_logger_config.json` fehlende Module nachgetragen (Backfill mit `file_handler=False`/`console_handler=False`, Nutzerentscheidung).

Details/Tests: `docs/FINDINGS_INDEX.md` Zeile "Logger: verbleibende Datei-I/O im Telegram-Handler" (CLOSED).

## 4. Phase C — Web-Parity-Matrix (CLOSED, reine Doku-Phase)

Kein Code-Change. Matrix in `docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md` Abschnitt 2.1 gegen den aktuellen Code neu verifiziert (nicht aus PR-Beschreibungen): Benutzerverwaltung und Logger-Verwaltung von 🟠 auf ✅ gehoben (Phasen A/B). Gesamtstatus des Audits: 🟡 ANALYSIS COMPLETE — DECISION PENDING (Backups, Duplikat-Cache, Error-Verwaltung, Downloads bleiben offen).

Details: `docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md` Abschnitt 9.

---

## 5. Phase D — Downloads / Cross-Process-Architektur

### 5.1 Inventar & Architektur-Analyse (D.1–D.6)

Vollständiges Funktions-Inventar (Start/Progress/Cancel/Retry/History/Queue/Search) gegen den Code verifiziert:

- **Fachlogik bereits Telegram-frei:** `services/downloader/downloader.py::YoutubeDownloader`, `services/duplicate/detector.py::DuplicateDetector` — beide halten laut eigenem Docstring (`docs/audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md`) bewusst kein Telegram-Objekt.
- **`ActiveDownloadRegistry`** (`services/downloader/active_downloads.py`) lebt ausschließlich im Bot-Prozess-Speicher (eine Instanz, gehalten von `RichMenuHandler`) — bereits am 2026-09-15 bewusst entschieden (`docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md`, Abschnitt "Erweiterung — Download-Center"): CC bekommt nur den persistenten `DownloadHistoryStore` (`GET /api/v1/downloads/history`), keinen Live-Status.
- **Kein Search-Feature** existiert (kein Finding, kein Scope).
- **Queue:** nur `Config.MAX_CONCURRENT_DOWNLOADS` über ein modulglobales `asyncio.Semaphore` in `klassen/download_handler.py` — faktisch nur prozessglobal (siehe 5.2).

### 5.2 Architekturentscheidungen (Nutzer, 2026-09-28)

**Entscheidung 2 (Downloads aus dem Web starten?): JA.**

**Beschlossene Architektur:** CC-lokaler Job über das bestehende `services/jobs/job_registry.py::JobRegistry`-Muster (identisch zu `repair_safe_automatic`/`repair_level3`) — direkter Aufruf von `YoutubeDownloader`/`DuplicateDetector`/`download_pipeline_core.py` im CC-Prozess, **kein** Cross-Prozess-Zugriff auf die Telegram-eigene `ActiveDownloadRegistry`. Damit ist **Entscheidung 1** (Cross-Prozess-Snapshot-Mechanismus, ursprünglich für Error-Verwaltung/Logger-Zähler/Live-Downloads vorgesehen) für den Anwendungsfall "CC startet eigene Downloads" **nicht** mehr Voraussetzung — sie bleibt nur noch relevant für den weiterhin offenen, separaten Anwendungsfall "CC sieht Telegram-initiierte Live-Downloads" (nicht Teil dieser Phase).

**Concurrency-Entscheidung ("Option B"):** `MAX_CONCURRENT_DOWNLOADS` Slot-Dateien unter `Config.DATA_DIR/download_slots/`, atomar belegt per `os.open(O_CREAT|O_EXCL|O_WRONLY)` — Erweiterung des bereits produktiven Mutex-Musters aus `services/library_repair/run_tracking.py::acquire_repair_lock()` von 1 Slot auf N Slots, von Bot- **und** CC-Prozess gemeinsam genutzt. Charakterisierungsfund dabei: das bisherige `asyncio.Semaphore` **wartet** bei Erschöpfung (kein Fail-Fast) — der neue Mechanismus bildet das bewusst per Poll-Loop nach (Regel 2, kein stiller Verhaltenswechsel). Verwaiste Slots nach Prozessabsturz: **nur Diagnose** (PID+Timestamp im Slot-Inhalt), **kein** automatisches Freigeben — identisch zum bestehenden Repair-Lock-Verhalten, keine neue Fehlerklasse (PID-Wiederverwendung, TTL-Schätzung) eingeführt.

Vollständige Optionsabwägung (A/B/C) und Begründung: Konversationsverlauf dieser Phase; hier nur das Ergebnis dokumentiert.

### 5.3 Concurrency-Implementierung (D.8, ✅ IMPLEMENTED)

- `services/downloader/download_concurrency.py` (neu): `acquire_download_slot()`/`release_download_slot()`/`download_slot()` (Async-Context-Manager), `read_slot_info()` für Diagnose. PR #329 (`c27dbf1`).
- `klassen/download_handler.py::handle_url()`: modulglobales `asyncio.Semaphore` (`_download_semaphore`/`_get_download_semaphore`) entfernt, nutzt jetzt `download_slot()`. PR #330 (`03965b8`).
- Tests: `tests/test_download_concurrency.py` (13, u. a. Wartesemantik unter Ressourcenknappheit, Exception-sicheres Freigeben).

### 5.4 Telegram-freie Pipeline-Extraktion (D.9, ✅ IMPLEMENTED)

Characterization-Ergebnis (`klassen/download_handler.py::DownloadHandler`, CLAUDE.md §19 "bekannte Risikoklasse — nicht automatisch zerlegen"): die Fachregeln (Duplikat-Ebenen inkl. Vorab-Probe, Datei-Konflikt-Erkennung, Playlist-Wrapper-Erkennung, dreiwertige Metadata-Checkliste für die History) waren bereits intern Telegram-frei, aber als private Instanzmethoden nicht ohne zweite Implementierung von CC nutzbar.

- `services/downloader/download_pipeline_core.py` (neu): reiner Move der 8 Telegram-freien Bausteine — `is_supported_download_url()` (SSRF-Domain-Allowlist), `process_single_download_result()`, `probe_artist_title_for_duplicate_check()`, `check_duplicates_before_download()`, `record_history_entry()`, `register_single_track_duplicate()`, `register_playlist_track_duplicates()`, `resolve_file_conflict_as_duplicate()`.
- `klassen/download_handler.py`: entsprechende Methoden sind jetzt dünne Delegatoren mit identischen Signaturen (1183 → 988 Zeilen); bestehende Tests, die sie direkt aufrufen/patchen, funktionieren unverändert.
- Charakterisierungsfund/Fix während der Extraktion: `self.config`-Zugriff musste auf `getattr(self, "config", None)` umgestellt werden, weil die try/except-Hülle in `probe_artist_title_for_duplicate_check()` einen fehlenden Zugriff nur abfängt, wenn er innerhalb dieser Hülle liegt — sonst hätte er bei per `object.__new__()` konstruierten Testinstanzen unkontrolliert durchgeschlagen.
- PR #331 (`e5650bd`). Tests: `tests/test_download_pipeline_core.py` (31), volle thematische Regression (`-k "download or duplicate or rich_menu"`, 1160+ Tests) grün.

### 5.5 CC Job-Verdrahtung (D.10, ✅ IMPLEMENTED)

Erster CC-eigener Download-Weg (`docs/FINDINGS_INDEX.md` "Downloads nicht aus dem Control Center startbar").

- `control_center/routers/jobs.py`: neuer `user_router` (**`AccessLevel.USER`**, bewusst getrennt vom bestehenden ADMIN-only `router` — Parität zu Telegram, jeder authentifizierte Nutzer darf für sich selbst downloaden, nicht nur Admins):
  - `POST /api/v1/jobs/download` (Body: `{"url": "..."}`, CSRF-geschützt) — validiert die URL serverseitig gegen `download_pipeline_core.is_supported_download_url()`, erstellt einen `JobRegistry`-Job (`kind="download_track"`).
  - `GET /api/v1/jobs/download/{job_id}` / `POST /api/v1/jobs/download/{job_id}/cancel` — **auf den eigenen `initiator` beschränkt** (eigene `_get_own_download_job_or_404()`, nicht die generische, ADMIN-only `_get_job_or_404()`): ein Nutzer kann per erratener/hochgezählter `job_id` weder den Status noch den Cancel-Endpunkt eines fremden Jobs erreichen.
- `_run_download_job()`: Sequenz Duplikat-Vorab-Check → Download → Datei-Konflikt-Behandlung → Metadaten-Pass-Through → Registrierung/History → Zusammenfassung — ruft dafür ausschließlich `YoutubeDownloader`/`DuplicateDetector`/`download_pipeline_core.py`/`DownloadResultReporter` auf, keine zweite Fachlogik-Implementierung. Die Sequenzierung selbst ist neu geschrieben (weil sie in `klassen/download_handler.py` mit Telegram-Statusnachrichten verzahnt ist), jede einzelne Fachregel ruft aber exakt dieselbe, einzige Implementierung wie der Telegram-Pfad auf.
- `_cancel_bridge()`: verbindet `JobRegistry.request_cancel()` mit `ActiveDownload.cancel_event` — echtes Mid-Flight-Cancel (nicht nur zwischen Pipeline-Schritten, wie bei `repair_safe_automatic` dokumentiert eingeschränkt).
- `chat_id` für `ActiveDownload`/`DownloadHistoryStore`/Duplikat-Registrierung = die eigene Telegram-ID des eingeloggten CC-Nutzers (`get_current_user_id()`) — ein CC-Download erscheint dadurch in derselben Verlaufsdatei wie ein Telegram-Download desselben Nutzers (private Chats: `chat_id == user_id`), keine synthetische ID.
- Nutzt `download_slot()` (5.3) für die globale Concurrency-Grenze.
- Bewusste Abweichung vom charakterisierten Telegram-Verhalten: "keine erfolgreichen Ergebnisse" bleibt bei Telegram stumm (nur Log-Warnung) — ein Job darf nicht dauerhaft `RUNNING` bleiben, daher hier `FAILED` statt Stille.
- Tests: `tests/test_control_center_download_jobs.py` (9 — Erfolg/Duplikat/Fehlschlag/Abbruch/leeres Ergebnis/URL-Validierung/CSRF/Access-Level-Schwelle/Ownership-Isolation). Volle Regression `-k "control_center or download or duplicate"`: 1493 passed, 1 skipped, 0 failed.
- **Commit-Status:** Im Arbeitsverzeichnis implementiert und getestet, **noch nicht committed** zum Zeitpunkt dieses Dokuments (Dateien: `control_center/app.py`, `control_center/routers/jobs.py`, `control_center/schemas/jobs.py`, `klassen/download_handler.py`, `services/downloader/download_pipeline_core.py`, plus Tests).

### 5.6 ⚠️ Offenes Risiko — Cross-Process-Schreibzugriff auf Duplicate-/History-Dateien (NICHT VALIDIERT)

**Dieser Punkt ist ausdrücklich NICHT als erledigt zu betrachten.**

Mit 5.5 sind `services/duplicate/detector.py::DuplicateDetector` (Duplikat-Cache, `DuplicateCache`-Datei unter `Config.DUPLICATE_CACHE_DIR`) und `services/downloader/download_history.py::DownloadHistoryStore` (`download_history.json`) zum ersten Mal **gleichzeitig aus zwei unabhängigen Prozessen heraus beschreibbar** (Bot-Prozess via Telegram-Download, CC-Prozess via `_run_download_job()`) — vorher gab es nur einen schreibenden Prozess.

- Die bestehende Datei-Persistenz-Semantik (atomares Schreiben, write-tmp + `Path.replace()`) wurde unverändert übernommen — **keine neue, dedizierte Race-Condition-/Locking-Analyse für den Zwei-Prozess-Schreibfall wurde in dieser Phase durchgeführt.**
- Insbesondere ungeprüft: gleichzeitiger Schreibzugriff auf `DuplicateCache` aus Bot- und CC-Prozess für **denselben** Duplikat-Eintrag (Check-then-Register-Race, DUP-05 — bisher nur *innerhalb* eines Prozesses durch `MAX_CONCURRENT_DOWNLOADS`/`download_slot()` begrenzt betrachtet, nicht über zwei Prozesse hinweg neu bewertet).
- `DownloadHistoryStore._save()` (write-tmp + `Path.replace()`, analog `DuplicateCache`) ist pro Schreibvorgang atomar, aber zwei nahezu gleichzeitige `add_entry()`-Aufrufe aus verschiedenen Prozessen könnten sich als klassisches Read-Modify-Write-Race gegenseitig überschreiben (kein `fcntl.flock`-Zyklus wie bei `services/user_data.py::update_user_data()` aus Phase A).
- **Bewusst kein Blocker für 5.5**, da das Grundrisiko (zwei Prozesse schreiben dieselbe Datei) nicht neu ist (Backups/Logger hatten ähnliche Fragen), aber es wurde in dieser Phase **nicht** dedizierte geprüft/geschlossen — anders als in Phase A (`user_data.json`, dort wurde ein Cross-Process-Lock explizit ergänzt).

**Follow-up (eigene, separat zu entscheidende Untersuchung, nicht Teil dieser Phase):** Race-/Locking-Analyse für `DuplicateCache` und `DownloadHistoryStore` unter echtem Zwei-Prozess-Parallelbetrieb (Bot + CC gleichzeitig aktiv), Entscheidung ob ein `fcntl.flock`-Zyklus analog `services/user_data.py` nötig ist.

---

## 6. Nächster Schritt (eindeutig)

**Nicht mehr Job-Verdrahtung — CC Download-UI:**

```
Dashboard/Downloads
    → Download starten (URL-Eingabe, POST /api/v1/jobs/download)
    → Jobstatus (Polling GET /api/v1/jobs/download/{job_id})
    → Fortschritt/Ergebnis (progress/message/result aus JobSchema)
    → Cancel (POST /api/v1/jobs/download/{job_id}/cancel)
```

Separat freizugebender Schritt, eigene Tests (`tests/test_control_center_ui.py`-Erweiterung, analog zum bestehenden Downloads-Panel). Die Cross-Process-Schreibzugriffs-Frage (5.6) bleibt unabhängig davon offen und wird durch die UI nicht mitgelöst.

---

## 7. Referenzen

- `/mnt/128ssd/client_consolidation.txt` (Auftrag Phase A–D)
- `docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md` (Abschnitte 8/9/11)
- `docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md` (Download-Center-Nachtrag, ursprüngliche Scope-Entscheidung)
- `docs/audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md` (Telegram-Freiheit von `YoutubeDownloader`/`DuplicateDetector`)
- `docs/FINDINGS_INDEX.md` (Zeile "Downloads nicht aus dem Control Center startbar")
- PRs: #326 (Phase A), #327 (Phase B), #328 (Phase C), #329/#330 (Concurrency), #331 (Pipeline-Extraktion)
