# MusicBot Engineering Baseline v12

> **Status: 🟢 FROZEN (2026-09-29) — Freeze-Gate APPROVED, siehe Abschnitt 6.**
>
> Verifizierter Engineering-Referenzzustand nach dem v11-Freeze
> (2026-09-28). Umfasst den Abschluss der Client Consolidation Phase D
> (D.12b.1, D.12b.2, D.12c-Nachtrag), den kompletten Ausbau des
> Metadaten-Editors (Jahr, Tracknummer, Feature-Artists), den
> Navidrome-Ausbau N1–N5 (Stream-API, Player, Favoriten/Scrobble/
> Playlists) und die abschließende CC-UI-Lieferung (Library L1–L4,
> Logs-Job-Filter, Overview O2). Eingefrorener Vorgänger:
> `docs/archive/MusicBot_ENGINEERING_BASELINE_v11.md` (Freeze 2026-09-28).
> Der laufende Stand aller offenen/zurückgestellten Punkte bleibt
> `docs/FINDINGS_INDEX.md`.

---

## 1. Metadaten

| Feld | Wert |
|---|---|
| Baseline | v12 |
| Vorgänger | `docs/archive/MusicBot_ENGINEERING_BASELINE_v11.md` (Freeze 2026-09-28, 6160 passed / 1 skipped / 0 failed / 11 subtests passed) |
| Letzte vom Nutzer gemeldete Full-Suite-Zahl (Freeze-Stand `main` = `1039e4b`, gemessen auf `5e4e421`, 2026-09-29) | **6576 passed, 1 skipped, 11 subtests passed, 0 failed, 5 warnings** (462,11 s) |
| Zuwachs seit v11-Freeze | +416 passed (6160 → 6576), 0 failed |
| Freeze-Datum | 2026-09-29 |
| Freeze-Status | 🟢 APPROVED — siehe Abschnitt 6 |

---

## 2. Änderungs-Status seit v11-Freeze

| Änderung | PR / Commit | Kurzbeschreibung | Ergebnis |
|---|---|---|---|
| **D.12b.1 — Prozess-Rolle + `propagate`-Parameter** | #367 | `logger.py::setup_module_logging()` bekommt Parameter `propagate` (Default `False` = alte Semantik); neue Prozess-Rolle `set_process_role()`/`get_process_role()` (Default `"bot"`); CC setzt `"control_center"` im Startup-Event. Behebt das Zwei-Prozess-Race auf `enhanced_metadata_processor.log`. | 5 neue Tests; FINDINGS-Zeile 514 → CLOSED |
| **D.12b.2 — Job-Attribution aller Download-Log-Zeilen + Reader-Filter** | #368 | `services/jobs/job_context.py` (ContextVar `bind_job()`), `logger.py::_JobIdFilter` an den Root-Handlern, konditionales `[JOB <id8>]`-Rendering im Formatter, `_run_download_job`-Wrapper, Reader-Filter `?job=<id8>` + `LogEntry.job_id`, Logs-JS Job-Feld. | 16 neue Tests + 157 UI/Logs/Page-Tests; Live verifiziert (14+ Module mit derselben Job-ID) |
| **Metadaten-Editor Schritt 1 — Jahr** | #374 | `apply_year_edit` (Album-Scope, `©day`), `preview_/execute_year_edit` mit `_validate_year` (1900 … Jahr+1), `GET/POST .../year-edit/…`, drittes Feld im Album-Reiter, ein Übernehmen für drei Felder. D2: Volldatum `2024-05-17` → `2024`. D4: nur Tags. | 11 Service-Tests + 3 API-Tests + 1 JS-Test |
| **Metadaten-Editor Schritt 2 — Tracknummer** | #375 | `apply_track_number_edit` (Ein-Track-Scope, `trkn`, Gesamtzahl bleibt erhalten), `_validate_track_number` (int 1..999), `GET/POST .../track-number-edit/…`, Zahlenfeld im Track-Block, Hinweis „Belegt im Album: …“. D3: v1 einzeln. | 13 Service-Tests + 3 API-Tests + 1 JS-Test |
| **Metadaten-Editor Schritt 3 — Feature-Artists** | #376 | `apply_feature_artists_edit` (`©ART = [Haupt] + Features` + `ARTISTS`-Freeform; ARTISTS gelöscht bei leerer Liste), `_validate_feature_artists` (Trim, max. 10, kein `;`, kein „feat./ft.“, case-insensitiv dedup), `GET/POST .../feature-artists-edit/…` inkl. `/current` für die Vorbelegung, dritter Block im Track-Bereich. D1/D5: Haupt-Artist bleibt, kein Auto-Learn. | 11 Service-Tests + 4 API-Tests + 1 JS-Test |
| **Navidrome N1–N5 (Ausbau abgeschlossen)** | #370–#373 | N1 Musik-Bereich mit Regalen/Rastern/Suche; N2 Detailseiten per Hash-Routing; N3 Stream-API `GET /api/v1/navidrome/stream/{song_id}` (Range-fähig, Credentials nur serverseitig); N4 Player-Leiste + Warteschlange + Media Session (`static/pages/navidrome_player.js`); N5 Favoriten `PUT/DELETE /favorites/{kind}/{item_id}`, Scrobble `POST /scrobble/{song_id}`, `POST /playlists/{playlist_id}/songs`. | 34 (N1/N2) + 26 (N3) + 28 (N4) + 46 (N5) Tests; FINDINGS-Zeile „Control Center: uneinheitliche UI“ fortgeschrieben |
| **CC-UI-Abschluss (Library L1–L4, Overview O2, Logs-Job-Filter)** | #355–#361 | L1 JS-Auslagerung + `/metadata`-Redirect; L2 Library-Übersicht als Metadaten-Werkstatt; L3a Artist-Detail-Seitengerüst + Offcanvas; L3b Dialoge + Wartung; L4 Metadaten-Editor als Seitenpanel (Basis für die drei Editor-Schritte oben). Overview O2 mit Statistics-Kachel und „Heute gehört“. Logs-Job-Filter UI-Anschluss. | 23 + 12 + 10 + 9 + 9 + 8 Tests (je nach Schritt) |
| **Test-Fix #377 — `TestUiRendering` an aktuelle UI-Struktur** | #377 | `[artist_detail]`-Variante entfernt (Funktion existiert nicht mehr seit L4); `[health_js]`-Harness um `_jobResultHtml`/`ccStatusBadge`/`ccToast` erweitert. | 10 vorbestehende rote Tests repariert → 51 passed |
| **Logs-Doku-Drift-Fix** | `30c5967` | `control_center/routers/logs.py` + `static/pages/logs.js` auf den Stand mit `?job=<id8>` gebracht (reader.py war schon korrekt). | Doku-only |
| **FINDINGS-Chronik + UI-Standard §15** | `5e4e421` | Chronik um Editor/Test-Fix/Logs-Drift ergänzt; Zeile 531 „Feature-Artists weiterhin ausstehend“ → Verweis auf Zeile 530; UI-Standard §15 „Heute gibt es keinen Stream-Endpunkt“ → „seit N3–N5 umgesetzt“. | Doku-only |

---

## 3. Recent Major Changes (seit v11-Freeze, 2026-09-28)

- **D.12b.2 — Job-Attribution aller Download-Log-Zeilen (2026-09-29):** jede Log-Zeile innerhalb eines Download-Kontexts trägt jetzt `[JOB <id8>]`. Reader extrahiert das Token, `?job=<id8>` filtert API-seitig, Logs-Dashboard bietet ein Job-Feld. Additiv über ContextVar + Filter an den Root-Handlern.

- **D.12b.1 — Prozess-Rolle + `propagate`-Parameter (2026-09-29):** `enhanced_metadata_processor.log` wird nur noch vom Bot-Prozess geschrieben; der CC-Pfad propagiert stattdessen zum Root-Logger (`control_center.log`). Kein Zwei-Prozess-Rotieren mehr.

- **Metadaten-Editor komplett (2026-09-29):** drei aufeinander aufbauende PRs (#374–#376) schließen die Feature-Lücke im Editor. Jahr im Album-Reiter, Tracknummer und Feature-Artists im Track-Block — je 1:1 nach den bestehenden Vorlagen (`apply_album_edit`, `apply_title_edit`, `apply_artist_rename`).

- **Navidrome-Ausbau N1–N5 abgeschlossen (2026-09-29):** eigener Musik-Bereich mit Regalen, Hash-Routing, Stream-API, Player-Leiste mit Media Session, Favoriten/Scrobble/Zur-Playlist. Stream-Endpunkt Range-fähig, Credentials serverseitig (CLAUDE.md §12).

- **CC-UI abgeschlossen (2026-09-28/29):** Library + Artist-Detail (L1–L4) mit dem Editor als Seitenpanel; Logs-Dashboard mit Job-Filter; Overview O2.

- **`TestUiRendering` repariert (2026-09-29):** die 10 vorbestehenden roten Tests (nachweislich ab `7f37383` unabhängig vom Editor) hängen an veralteten Pfaden — `[artist_detail]` entfällt, `[health_js]`-Harness um `_jobResultHtml`/`ccStatusBadge`/`ccToast` erweitert. Test-only.

- **Doku-Konsistenz (2026-09-29):** Logs-Router + Logs-JS auf den D.12b.2-Stand; FINDINGS-Chronik um Editor/Test-Fix/Logs-Drift ergänzt; UI-Standard §15 aktualisiert.

---

## 4. Technical Debt — Snapshot (Stand 2026-09-29, Freeze-Zeitpunkt)

Seit v11-Freeze geschlossen (Auswahl, Details in `docs/FINDINGS_INDEX.md`):
**D.12b.1** (Zwei-Prozess-Rotieren `enhanced_metadata_processor.log`),
**D.12b.2** (Web-Download ohne Job-Zuordnung),
**Feature-Artists nicht bearbeitbar**,
**Tracknummer und Jahr nicht bearbeitbar**.

Kein offener P0/P1 zum Draft-Zeitpunkt (maschinell gegen
`docs/FINDINGS_INDEX.md` verifiziert — alle als `P0`/`P1` markierten
Zeilen sind `CLOSED`).

Verbleibend offen (25 Punkte, alle P2/P3 bzw. unpriorisiert —
Begründung je Zeile in `docs/FINDINGS_INDEX.md`):

| Punkt | Art | Priorität |
|---|---|---|
| ARCH-031-Follow-up F2 (`tags_fingerprint()` rückwirkend für `apply_level1()`) | DEFER | P3 |
| — (`utils/genre_map.py::GenreMapper.reload()`, ignoriert konfiguriertes `mapping_dir`) | DEFER | P3 |
| — (`services/library_repair/run_tracking.py::compute_repair_statistics()`, aggregierte Repair-Statistik weist `UNRESOLVED` nicht separat aus) | DEFER | P3 |
| — (ARCH-034/035, COVER/LOUDNESS/DUPLICATE über Telegram) | DEFER | P3 |
| — (`_split_artists()`, `services/statistik/statistics_calculator.py`) | akzeptiert | P3 |
| — (Family Hub, Challenge-Typ „Rate den Song") | DEFER | P3 |
| — (Family Hub, Challenge-Typ „Playlist für Stimmung erstellen") | DEFER | P3 |
| F-07 (MusicBrainz Artist-MBID nicht als Identitätssignal) | DEFER | P3 |
| — (Hard-Cancel während FFmpeg-Postprocessing wird nicht erkannt) | akzeptiert | P3 |
| — (P2.3 Stufe B — Bad Download Detector Reject-Gate) | DEFER | P2 |
| — (Metadata Confidence Score — Wiederverwendung vs. separater Score) | DEFER | — |
| — (Control Center, Subpath-Betrieb: echter Browser-/Telegram-Login-Test) | DEFER | P3 |
| — (ARCH-021 Menu-Subsystem, Session-Legacy-State: `max_sessions` ohne Durchsetzung + `MenuSession.state`/`.data`/`.message_id` ungenutzt) | DEFER | P3 |
| — (`config.py::DOWNLOAD_RETRY_COUNT`/`DOWNLOAD_RETRY_DELAY`, totes Config) | DEFER | P3 |
| — (Music DNA v1, bewusst zurückgestellte Dimensionen) | DEFER | P3 |
| — (Telegram-Delete für Duplikat-Check, Follow-up) | DEFER | P3 |
| — (Manual Album Artist Editing, `aART` kann durch `ALBUM_ARTIST_INCONSISTENT`-SAFE_AUTOMATIC-Repair auf den Verzeichnisnamen zurückgesetzt werden) | DEFER | P3 |
| — (Manual Artist Editing, tag-wert-getriebener Scope kann Dateien mit abweichendem Artist-Tag dauerhaft aus dem Rename ausschließen) | akzeptiert | P3 |
| — (Manual Metadata Editing v1/v2, gemeinsamer `libmaint_meta_new_value`-Session-Key ohne Flow-Identität) | akzeptiert | P3 |
| — (`album_targets()`, totes `is_symlink()`-Check im Einzeldatei-Scope-Zweig) | DEFER | P3 |
| — (CC-LOGGER-L7, globales Log-Level ohne Persistenz-Schema) | DEFER | P3 |
| — (CC-LOGGER-L7, Modul-Statistiken + volle Logger-Introspektion, Cross-Prozess-Blocker) | DEFER | P3 |
| — (`handlers/duplicate_handler.py::find_duplicates()`/`clear_duplicate_cache()`, Legacy ohne Aufrufer) | DEFER | P3 |
| — (`DuplicateDetector._in_flight` gilt nur pro Instanz/Prozess) | OPEN | P3 |
| — (Control Center: Mapping-Dateien `mapping/*.yaml`/`*.json` nicht im Control Center bearbeitbar) | OPEN | P3 |

25 offene Punkte (ggü. 27 in v11). Der Netto-Rückgang trotz neuer
Zurückstellung („Mapping-Dateien“) entsteht aus den vier v11-geschlossenen
Zeilen (D.12b.1, D.12b.2, Feature-Artists, Tracknummer/Jahr). Kein
offenes P0/P1.

---

## 5. Security- und Datensicherheits-Baseline (Stand 2026-09-29)

Kein neuer dokumentierter Datensicherheits-Vorfall seit v11-Freeze.

**Neue schützende Mechanismen seit v11-Freeze:**

- **Navidrome N3 Stream-Proxy:** Zugangsdaten (Subsonic `u=`/`p=`) bleiben
  serverseitig — nie in Antwort, Header oder Log. `raise_for_status()` wird
  bewusst nicht genutzt (dessen Meldung enthielte die URL samt Passwort);
  Verbindungsfehler werden maskiert. Song-ID auf `[A-Za-z0-9_-]{1,64}`
  begrenzt (sonst 422); `Range`-Header nur als genau ein Bereich geprüft.
- **Navidrome N5 Favoriten/Scrobble/Playlists:** Subsonic meldet Fehler oft
  als HTTP 200 + `status=failed` — das wird geprüft (Code 70 → 404, sonst
  502); Fehlertext/URL/Zugangsdaten gelangen nie in die Antwort.
- **D.12b.2 Job-Attribution:** `services/jobs/job_context.py` nutzt
  `contextvars` analog `step_context.py`; `_JobIdFilter` an den Root-
  Handlern. Keine Signaturänderung, kein LoggerAdapter, kein neues
  Logging-System.

**Aus v11 weiterhin gültig** (keine Änderung): Login mit Navidrome-Benutzer
(Rate-Limit, keine Konto-Rückschlüsse), Abmelden (stateless Session, Cookie-
Kopien bis Ablauf gültig), Bot-Runtime-Snapshot (redigiert), Cross-Process-
Konsistenz für `user_data.json`/Download-Verlauf/Duplikat-Cache/Wartungsmodus.

---

## 6. Architecture Freeze

```
🟢 ARCHITECTURE FREEZE — APPROVED (2026-09-29)
```

**Freeze-Gate-Audit (2026-09-29, Stand `main` = `1039e4b`):**

| Kriterium | Ergebnis |
|---|---|
| Offene P0/P1-Findings | **0** (maschinell gegen `docs/FINDINGS_INDEX.md` verifiziert) |
| Vollständige Testsuite | **6576 passed, 1 skipped, 11 subtests passed, 0 failed** (462,11 s), vom Nutzer auf `5e4e421` ausgeführt; zwischen `5e4e421` und dem Freeze-Stand `1039e4b` liegen ausschließlich zwei Doku-Commits (v12-DRAFT, Logs/FINDINGS-Doku) ohne Code-Änderung |
| Bekannte Regressionen | keine — die vorbestehenden 10 roten Tests in `tests/test_repair_result_semantics.py::TestUiRendering` wurden in #377 repariert (Test-only) |
| Schichtgrenzen-Verletzungen | keine — `tests/test_services_layer_boundary.py` grün im Freeze-Lauf; kein Import `services/` → `handlers`/`control_center`/`klassen`/`telegram`/`helfer`, kein Import `control_center/` → `handlers`/`klassen`/`telegram`/`helfer`, kein Import `utils/` → Präsentationsschichten |
| Produktions-Datensicherheit | **PASS** — kein neuer Vorfall seit v11-Freeze; v11-Vorfall (D.13-Lost-Update) bleibt dort dokumentiert |

Die Serie ist überwiegend additiv (neue Services, Router, Jobs,
UI-Erweiterungen, Editor-Felder, Log-Attribution). Die einzigen
bewussten Verhaltensänderungen seit v11 sind die dokumentierten Fixes
(D.12b.1 Prozess-Rolle, D.12b.2 Job-Attribution, Metadaten-Editor
Schritt 1–3, Test-Fix #377).

---

## Freeze-Checkliste (v12-Freeze, 2026-09-29)

- [x] Freeze-Gate-Audit → 🟢 APPROVED (alle Kriterien PASS)
- [x] Abschnitte 4–6 als Schnappschuss befüllt
- [x] „Baseline Frozen (2026-09-29)"-Footer gesetzt, DRAFT-Kopf entfernt
- [x] Referenzen umgestellt: `README.md`, `docs/INDEX.md`, `CLAUDE.md`
- [x] `docs/MusicBot_ENGINEERING_BASELINE_v11.md` → `docs/archive/`

---

## Baseline Frozen (2026-09-29)

**Diese Datei ist damit abgeschlossen.** Neue Findings, Nachträge oder
technische Schulden gehören ab jetzt in
`MusicBot_ENGINEERING_BASELINE_v13.md`, sobald diese angelegt wird
(Normalfall: beim nächsten ARCH-Phasen-Abschluss mit Code-/YAML-Änderung
nach diesem Freeze — bis dahin ist dieses Dokument der eingefrorene
Referenzpunkt). Der laufende Stand aller offenen/zurückgestellten Punkte
bleibt `docs/FINDINGS_INDEX.md`.
