# MusicBot Engineering Baseline v13

> **Status: 🟢 FROZEN (2026-09-30) — Freeze-Gate APPROVED, siehe Abschnitt 6.**
>
> Verifizierter Engineering-Referenzzustand nach dem v12-Freeze
> (2026-09-29). Umfasst die vollständige **Mapping-Administration im
> Control Center** (M1–M7, UI 5.0–5.4, Backup/Restore, Runtime-Status,
> YAML-Editor, Genre-Hierarchie-Editor) samt zwei dabei gefundenen
> Laufzeitfehlern sowie die **Artist-Resolution-Phase A/B** (Architecture
> Gate, AR-1/AR-2/AR-3 CLOSED, AR-5/AR-6 DEFER, AR-4 offene
> Architekturentscheidung) und HIER-1 (Testrobustheit). Eingefrorener
> Vorgänger: `docs/archive/MusicBot_ENGINEERING_BASELINE_v12.md` (Freeze
> 2026-09-29). Der laufende Stand aller offenen/zurückgestellten Punkte
> bleibt `docs/FINDINGS_INDEX.md`.

---

## 1. Metadaten

| Feld | Wert |
|---|---|
| Baseline | v13 (FROZEN 2026-09-30) |
| Vorgänger | `docs/archive/MusicBot_ENGINEERING_BASELINE_v12.md` (Freeze 2026-09-29, 6576 passed / 1 skipped / 11 subtests passed / 0 failed) |
| Letzte Full-Suite-Zahl (Stand `main` = `7dffbb9`: nach Artist Resolution AR-1/AR-2/AR-3/AR-5 und HIER-1; Lauf 2026-09-30, 910,68 s, auf dem Baum von `main` vor dem Merge-Commit — identischer Inhalt) | **7217 passed, 1 skipped, 11 subtests passed, 0 failed, 5 warnings** |
| Frühere Läufe am selben Tag | (1) `main` = `de42f12` + M6/M7, 580,63 s: 7205 passed / 1 skipped / 0 failed. (2) `main` = `48bcf7c` (nach AR-1/2/3/5): 7214 passed / **3 failed** / 1 skipped, 666,56 s — die 3 Fehlschläge waren HIER-1 (fester Zählstand `== 187` vs. 188 Einträge nach `Afro-Hip`), keine Artist-Resolution-Regression; behoben mit #403 |
| Zuwachs seit v12-Freeze | +641 passed (6576 → 7217), 0 failed. Seit dem Lauf mit 7205: +12 neue Artist-Resolution-Tests — `test_artist_genre_cross_process_lock.py` (4), `test_genre_processor_learned_source.py` (5), `test_auto_learned_genre_cross_process_lock.py` (3) |
| Einordnung eines früheren Laufs am selben Tag | 2 Fehler in `test_genre_specificity_characterization.py` (74 statt 75 Spezifitäts-Paare): Ursache waren zwei beim manuellen Testen im Control Center entfernte Alias-Zeilen in der **echten** `mapping/genre_aliases.yaml` (`deutsch hip-hop`, `afro house`), kein Codefehler; nach Wiederherstellen des Ausgangsstands grün (belegt durch das Backup-Protokoll und einen sauberen Worktree-Lauf: 36 passed) |
| HIER-1 (behoben) | Drei Hierarchie-Tests pinnten fest `== 187` Einträge der echten `mapping/genre_hierarchy.yaml` (188 seit `Afro-Hip: Afro`, `cc460f3`). Seit #403 zählen sie die Keys direkt aus der Datei. Die Mapping-Daten blieben unverändert; ob `Afro-Hip` fachlich gewollt ist, ist eine separate, offene Entscheidung (FINDINGS_INDEX HIER-1) |
| Neue Tests seit v12 (nur gezielte/thematische Läufe, keine Full-Suite) | 473 gesammelte Tests in 23 neuen Testdateien (`pytest --collect-only`), dazu Ergänzungen in `test_bot_runtime_snapshot_task.py` und den UI-Seitenlisten-Tests |
| ARCH-Phasen | keine eigene ARCH-Nummer. Die Control-Center-Arbeit ist ein Feature; die Artist-Resolution-Phase (A: Architecture Gate, B: AR-1/AR-2/AR-3) ist ein kontrollierter Architektur-Schritt nach der Migration Phase A–E, Bericht `docs/audits/ARTIST_RESOLUTION_ARCHITECTURE_GATE_2026-09-30.md` |
| Freeze-Status | 🟢 **FROZEN 2026-09-30** — G3 (Nutzer: „funktioniert alles“), G4 und G6 erfüllt, Freeze-Gate-Audit in Abschnitt 6 APPROVED |

---

## 2. Recent Major Changes (seit v12-Freeze, 2026-09-29)

| Bereich | PR | Inhalt |
|---|---|---|
| **Mapping-Administration M1–M5** | #378 u. a. | Channel-Genre, Genre-Aliase, Genre-Overrides, Genre-Filter, Spezialkanäle über `services/mapping_admin.py` und `/api/v1/admin/mappings/{mapping_id}` (Allowlist, ADMIN, Vorschau, Etag, Kommentar-Hinweis) |
| **Mapping-UI 5.0–5.4** | #381, #384, #386, #388, #391, #392 | Seite `/mappings` (Kacheln als Tabs, Tabellen mit Suche/Paging, Chip-Listen, Prioritäts-Karten), Offcanvas-Editor (Formular, Listen, Vorschau/Diff, Konflikt-Dialog), Versionen |
| **B2 Schreib-Härtung** | #389 | eindeutiges tmp-Sibling, `fsync`, Aufräumen bei Fehler, Rechte bleiben, `fcntl`-Lock gegen gleichzeitige Schreiber aus Bot- und Control-Center-Prozess (Risiko R1 geschlossen) |
| **B1 Backup/Restore** | #390 | Version der Vorgängerdatei vor jedem Schreiben (`<DATA_DIR>/mapping_backups/…`, letzte 20), Restore als Etag-geschützter Write, Backup-Fehler bricht den Write ab |
| **B3 Runtime-Status** | #393 | Bot meldet beim Start die Datei-Hashes im Laufzeit-Snapshot; Control Center zeigt „Angewendet“ / „Neustart nötig“ / „Runtime unbekannt“ / „Bot läuft nicht“ (einzige Änderung am Bot) |
| **B4 YAML-Editor** | #394 | Rohtext mit strenger Prüfung (ein Dokument, keine Anker/Aliase/Tags/Merge-Keys/doppelten Keys, Tiefe ≤ 6, ≤ 512 KB), Text unverändert geschrieben (Kommentare bleiben) |
| **Mapping Phase 2: M6 Genre-Hierarchie** | #397 | Baum-Editor für `genre_hierarchy.yaml` (`services/mapping_hierarchy.py`, Tab „Genre-Hierarchie“): Ganzzustands-API mit Etag, Preview mit Prioritätswirkung, Zyklen-/Parent-/Duplikat-Validierung, Kinderschutz beim Entfernen, zeilenweiser Writer (Kommentare bleiben), Backup/Restore, Runtime-Status; kein YAML-Rohtext-Editor. Fund im Browser-Test: Genres eines Entwurfs-Zyklus waren nicht mehr sichtbar → eigener Abschnitt „Nicht mit einer Wurzel verbunden“ |
| **Mapping Phase 2: M7 Genre-Regeln** | #397 | Entscheidung: kein Editor. `genre_rules.yaml` ist Runtime-tot; Characterization-Tests, Korrektur der Aussage „keyword_rules 1:1 redundant“ (9 von 13), FINDINGS DEFER/ARCHITECTURE DECISION |
| **Fix: Spezialkanal-Priorität zufällig** | #379 | `set()`-Merge machte die Kategorie-Reihenfolge vom Hash-Seed abhängig; gemeinsamer Helfer behält die YAML-Reihenfolge |
| **Fix: Umordnen der Kategorien wurde nie geschrieben** | #390 | `plan_special_channels_update()` bewertete eine reine Umordnung als `unchanged`; der lockere Test verdeckte es |
| **Override-Key-Warnung** | #383 | `GenreMapper` sucht Overrides kleingeschrieben; ein Key mit Großbuchstaben greift zur Laufzeit nie — die Vorschau warnt |
| **Artist Resolution — Phase A (Architecture Gate)** | #398 | Analyse ohne Code: `artist_overrides.json` ist Namens-Identität, kein Genre-Override; zwei getrennte Ketten (Identität / Genre); Source/Writer-Matrix, Konflikt-Matrix, Auto-Learn-Flow. Bericht `docs/audits/ARTIST_RESOLUTION_ARCHITECTURE_GATE_2026-09-30.md` |
| **AR-1 (CLOSED)** | #398 | `artist_genre.yaml`: `save_manual_genre_mapping()` unter `cross_process_lock`; `apply_manual_genre_mapping()` hält den Lock um Etag-Prüfung und Write (409 statt Lost Update) |
| **AR-2 (CLOSED)** | #399 | `GenreMapper.learned_artist_keys`; `GenreProcessor` liefert `artist_exact_learned` für Einträge aus `auto_learned_genre.json`, `artist_exact_manual` für `artist_genre.yaml`; `auto_learn_disabled` unverändert |
| **AR-3 (CLOSED)** | #400, #402 | `auto_learned_genre.json` unter `cross_process_lock` (Bot + Revalidierungs-Subprozess); #402: Testrobustheit und Lock-Kommentare aus dem Review, nur Kommentare im Produktionscode |
| **AR-5 (DEFER)** | #401 | `GenreMapper.reload()` fehlerhaft (hartcodiertes `"mapping"`), aber ohne Caller; Neustart bleibt der dokumentierte Mechanismus. Kein Code geändert |
| **AR-4 (DEFER / offene Architekturentscheidung)** | – | `known_artists.yaml` ist Hybrid: auto geschrieben, als Identitäts-Autorität (Resolver Tier 2) gelesen |
| **AR-6 (DEFER)** | – | Kein Candidate/Accept/Reject für Auto-Learn; `LEARNED` wird nach Neustart ohne Nutzerentscheidung aktiv |
| **HIER-1 (Testrobustheit CLOSED)** | #403 | Drei Hierarchie-Tests ohne festen Zählstand (Anzahl aus der Datei); `Afro-Hip`-Frage separat offen |

---

## 3. Technical Debt — Mapping-Bereich (Stand 2026-09-30)

Schnappschuss der offenen Punkte dieses Themas; maßgeblich bleibt `docs/FINDINGS_INDEX.md`.

| Punkt | Prio | Anmerkung |
|---|---|---|
| `genre_hierarchy.yaml`, `genre_rules.yaml` nicht im Control Center bearbeitbar (M6/M7) | P3 | eigener Plan, braucht Hierarchie-/Regex-Validierung |
| `known_artists.yaml`, `case_preserve.yaml`, Auto-Learned-JSON, `artist_overrides.json` | P3 DEFER | Hybrid-/Auto-Learned-Dateien: Hybrid-Konflikt (R3) fachlich offen; R1 ist durch B2 geschlossen |
| Kein Löschen von Einträgen bei Channel-Genre/Aliasen/Overrides | P3 | kein DELETE-Endpunkt; Entfernen nur bei Filtern und Spezialkanälen |
| Override-Keys mit Großbuchstaben wirken zur Laufzeit nicht | P3 (akzeptiert) | Warnung umgesetzt; Runtime-Angleichung wäre eigener ARCH-Schritt |
| `bot_reload_required` bei `special-channels` konservativ | P3 | Teile der Prüfung lesen die Datei je Aufruf; in der UI als Hinweis sichtbar |
| Keine Server-Paginierung der Mapping-Listen | P3 | clientseitig (386 Aliase, 600 Filter); neuer Endpunkt wäre nötig |
| Kein Reload-Pfad im Bot („Anwenden“ ohne Neustart) | P3 | `GenreMapper.reload()` existiert, wird nicht aufgerufen; die UI zeigt den Zustand nur an |
| Artist Resolution: AR-4 (`known_artists.yaml` Hybrid), AR-6 (kein Candidate/Accept/Reject), AR-5 (`reload()` fehlerhaft, ohne Caller) | P2/P3 DEFER | Architekturentscheidungen stehen aus bzw. bewusst vertagt; AR-1/AR-2/AR-3 CLOSED |
| `Afro-Hip: Afro` in `genre_hierarchy.yaml` (mit `cc460f3` eingecheckt, nicht in der Commit-Message): fachlich gewollt? | P3 | Zählstand-Problem der Tests ist mit #403 beseitigt; die fachliche Bestätigung bzw. Rücknahme (CLAUDE.md §10) steht aus |
| Review-Punkte zu #400 ohne Umsetzung: veraltete Entscheidungswerte im Log (Punkt 1), `flock` ohne Timeout (2), Lock im gemeinsamen Helper (4) | P3 | Entscheidung offen, siehe Review von PR #400 |

---

## 4. Security- und Datensicherheits-Baseline (Stand 2026-09-30)

Kein neuer dokumentierter Datensicherheits-Vorfall seit v12-Freeze.

**Neue schützende Mechanismen:**

- **Allowlist statt Pfade:** der Client übergibt nur `mapping_id` (fünf feste Werte)
  und eine `version_id` aus der Liste; Dateipfade entstehen ausschließlich
  serverseitig. Versions-IDs werden nur gegen vorhandene Dateien aufgelöst.
- **ADMIN auf jedem Endpunkt** (serverseitig, `require_min_access_level`), schreibende
  Endpunkte zusätzlich Same-Origin; ein Test deckt alle 17 Routen für PUBLIC/USER/MODERATOR
  (403), ADMIN/OWNER (erlaubt) und ohne Session (401) ab.
- **Rohtext (YAML-Editor):** nie ein unsicherer Loader; Event-Scan vor dem Laden; harte
  Grenzen (512 KB, Tiefe, Knotenzahl); früher `Content-Length`-Schutz (413); der Text
  wird nie geloggt.
- **Schreiben:** Etag gegen Lost Updates, Datei-Lock, atomarer Write mit `fsync`, Backup
  vor jedem Schreiben.
- **Snapshot:** der Abschnitt `mapping_files` enthält nur Dateinamen aus der Allowlist und
  Hashes — keine Pfade, keine Inhalte.

---

## 5. Freeze-Voraussetzungen (erfüllt)

- [x] G3: echte Änderung je Typ in der Produktion, Bot-Neustart, Restore (Nutzer, 2026-09-30: „funktioniert alles“)
- [x] G4: Browser-Durchlauf hell/dunkel, Handy, hinter dem echten Proxy (Nutzer, 2026-09-30: funktioniert)
- [x] G6: Vollsuite `python3 -m pytest tests/ -q` (2026-09-30, `main` = `7dffbb9`): 7217 passed / 0 failed (zwischenzeitlich 3 rote Hierarchie-Zählstand-Tests, behoben mit #403)
- [x] Zahlen in Abschnitt 1 aus dem zuletzt gemeldeten Lauf eingetragen (7217 passed / 0 failed)
- [x] Nach G3: Status auf FROZEN (2026-09-30, siehe Abschnitt 6)

---

## 6. Architecture Freeze

```
🟢 ARCHITECTURE FREEZE — APPROVED (2026-09-30)
```

**Freeze-Gate-Audit (2026-09-30, Stand `main` = `6adfd98`):**

| Kriterium | Ergebnis |
|---|---|
| Offene P0/P1-Findings | **0** (maschinell gegen `docs/FINDINGS_INDEX.md` geprüft: keine Zeile mit Status OPEN und Priorität P0/P1) |
| Vollständige Testsuite | **7217 passed, 1 skipped, 11 subtests passed, 0 failed** (910,68 s), von Claude mit ausdrücklicher Nutzerfreigabe auf dem Baum von `7dffbb9` ausgeführt (identisch mit `main` bis auf den anschließenden reinen Doku-Commit `de3f4e8`, #404). Der zuvor vom Nutzer gemeldete Lauf auf `48bcf7c` (7214 passed / 3 failed) zeigte die drei HIER-1-Zählstand-Tests; sie sind mit #403 behoben |
| Bekannte Regressionen | keine — die 3 zwischenzeitlich roten Hierarchie-Tests waren ein fester Zählstand (`== 187` vs. 188 Einträge nach `Afro-Hip`), keine Regression der Artist-Resolution-Arbeit (am Stand vor AR-1 ebenfalls rot) |
| Schichtgrenzen-Verletzungen | keine — `tests/test_services_layer_boundary.py` im grünen Volllauf enthalten |
| Produktions-Datensicherheit | **PASS** — kein neuer dokumentierter Vorfall seit v12-Freeze; die Mapping-Dateien wurden durch die Artist-Resolution-Arbeit nicht verändert |

**Bewusst offen (kein Freeze-Blocker):** `Afro-Hip: Afro` in `mapping/genre_hierarchy.yaml`
(mit `cc460f3` eingecheckt) — fachliche Bestätigung steht aus (P3, FINDINGS_INDEX HIER-1 Teil 2);
AR-4 (`known_artists.yaml` Hybrid), AR-5 (`GenreMapper.reload()`), AR-6 (Candidate/Accept/Reject)
sind DEFER; drei Review-Punkte zu #400 ohne Umsetzung (P3).

---

## Freeze-Checkliste (v13-Freeze, 2026-09-30)

- [x] Freeze-Gate-Audit → 🟢 APPROVED (alle Kriterien PASS)
- [x] Abschnitte 1–6 als Schnappschuss befüllt
- [x] „Baseline Frozen (2026-09-30)"-Footer gesetzt, DRAFT-Kopf entfernt
- [x] Referenzen umgestellt: `README.md`, `docs/INDEX.md`, `docs/FINDINGS_INDEX.md`, `CLAUDE.md`
- [x] `docs/MusicBot_ENGINEERING_BASELINE_v12.md` → `docs/archive/`

---

## Baseline Frozen (2026-09-30)

**Diese Datei ist damit abgeschlossen.** Neue Findings, Nachträge oder
technische Schulden gehören ab jetzt in `MusicBot_ENGINEERING_BASELINE_v14.md`,
sobald diese angelegt wird (Normalfall: beim nächsten ARCH-Phasen-Abschluss
mit Code-/YAML-Änderung). Der laufende Finding-Stand steht ausschließlich in
`docs/FINDINGS_INDEX.md`.
