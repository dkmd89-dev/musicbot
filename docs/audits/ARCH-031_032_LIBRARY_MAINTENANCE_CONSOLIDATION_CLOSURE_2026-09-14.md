# ARCH-031/032 — Library Repair Telegram Integration & Maintenance Consolidation — Abschlussbericht

**Datum:** 2026-09-14
**Status:** 🟢 CLOSED — vollständig umgesetzt, gemergt, eingefroren
**PR:** [#244](https://github.com/dkmd89-dev/musicbot/pull/244) (gemergt, `706b9b5`)
**Betroffene Baseline:** `docs/MusicBot_ENGINEERING_BASELINE_v10.md` (Freeze 2026-09-14)

---

## 1. Executive Summary

Auftrag: `library_repair` soll vollständig über den Telegram-Handler ausführbar
werden (Executor Level 1–3), sodass keine CLI-Befehle mehr nötig sind, und
drei neue, eigenständige Wartungsskripte
(`fix_artist_casing.py`/`remove_legacy_genre_atom.py`/`set_genre.py`,
Commit `6037abf`) sollen in eine gemeinsame Repair-Domäne konsolidiert
werden.

Ergebnis in drei Phasen:

1. **ARCH-031** — reine Characterization- und Entscheidungsphase (kein
   Code). Vollständige Analyse der drei Scripts, der bestehenden
   `services/library_repair/`-Infrastruktur und der Telegram-Integration;
   elf verbindliche Architekturentscheidungen (B.1–B.11); Migrationsplan
   Phase 1–5.
2. **ARCH-032** — vollständige Umsetzung von Phase 1–4 (Library
   Maintenance Consolidation): neue Domain-Module, Executor-Erweiterung,
   geteilte Run-Tracking-Infrastruktur, zentraler CLI-Einstiegspunkt,
   Telegram-Menüpunkt „🧹 Library-Wartung". Phase 5 (Telegram Level-2/3,
   ARCH-033) bewusst **nicht** angefasst — eigene, spätere Phase.
3. **Cache-Import-Fix** + **Baseline-v10-Freeze** — bei der Verifikation
   eine vorbestehende, unabhängige kaputte Änderung gefunden und
   behoben; anschließend die laufende Baseline mit einem echten
   Freeze-Gate-Audit eingefroren.

Alles über einen PR gemergt, Git danach aufgeräumt (Branch gelöscht,
lokaler `main` synchron zu `origin/main`).

**Kernzahl:** volle Testsuite **4250 passed / 1 skipped / 11 subtests
passed / 0 failed** (Nutzer-Lauf, 250,52 s) — 0 Regressionen über die
gesamte Serie.

---

## 2. ARCH-031 — Characterization & Decision

**Nummern-Hinweis:** der Auftrag bezeichnete diese Phase ursprünglich als
„ARCH-030" — bereits vergeben (`MusicBot_ARCH-030_Error_Handler_F7_Closure.md`,
PR #243). Analog zum dokumentierten ARCH-021/022-Präzedenzfall auf
**ARCH-031** verschoben; die beiden Folge-Implementierungsphasen liefen
entsprechend als **ARCH-032**/**ARCH-033** statt der ursprünglich
skizzierten „031"/„032".

### 2.1 Characterization (Kurzfassung)

- Alle drei Scripts: identisches Sicherheitsmodell (Dry-Run-Default,
  Backup außerhalb der Library, Audio-Essenz-MD5, Append-Only-Journal),
  aber **~70 % duplizierte Boilerplate** gegenüber bereits vorhandenem
  Code in `services/library_repair/executor.py` (`safety_check()`,
  `_audio_essence_md5()`, SHA-256, Backup-/Temp-Sibling-/Replace-Muster).
- **Kritischer Befund:** die drei Scripts journalten nach
  `/tmp/musicbot_test/*.jsonl` statt in die Produktions-Journal-Datei —
  bisherige Läufe wären in Repair-Historie/-Statistik unsichtbar
  geblieben.
- Kein Health-Issue-Code deckte Artist-Casing oder Legacy-Genre-Atome ab
  — die drei Scripts standen strukturell außerhalb des
  Finding→Plan→Execute-Flows.

### 2.2 Verbindliche Entscheidungen (B.1–B.11)

| # | Entscheidung |
|---|---|
| B.1/B.2 | Artist-/Genre-Domain-Logik in neuen, leichtgewichtigen Modulen (`artist.py`/`genre.py`) — bewusst **kein** Import von `ArtistIdentityResolver`/`GenreMapper` (andere Fragestellung bzw. zu schwere Importkette, Präzedenz `tag_repairs.py`) |
| B.3 | Mutation ausschließlich in `executor.py` — Domain-Module und Services führen nie selbst Mutagen-Writes aus |
| B.4 | Neue Verifikationsfunktion `tags_fingerprint()` für die drei neuen Maintenance-Actions — bewusst **nicht** rückwirkend auf `apply_level1()` angewendet (Regressionsrisiko) |
| B.5 | **„Library-Maintenance-Actions" als eigener, NICHT Health-Finding-getriebener Flow** (ADR-0001) — `services/library_health/` bleibt P0-unangetastet, kein neuer Issue-Code |
| B.6 | Gemeinsames `run_tracking.py` statt eigenständigem `maintenance_service.py` mit dupliziertem Lock/Journal/Run-Index (ADR-0004, Variante C: Extraktion statt Duplikat oder Vermischung) |
| B.7 | Telegram-Handler ruft ausschließlich den Service auf, keine eigene Mutagen-/Backup-Logik |
| B.8 | Artist-Auswahl index-basiert, bestehendes Muster aus `reprocessing_menu_handler.py` wiederverwendet — kein Rohpfad aus `callback_data` |
| B.9 | Level 2/3 (ARCH-033) bewusst **getrennt** von ARCH-032 — anderes Risikoprofil (Netzwerk, Minuten-Laufzeit, Auto-Learn-Mutation vs. rein lokal/deterministisch) |
| B.10 | `--artist` CLI+Telegram, `--path`/`--all`/`--update-manual-mapping`/`--only-if-missing` CLI-only |
| B.11 | Doctor-Boundary (`doctor_runner.py`/`library_doctor_handler.py`) bleibt unverändert auf `SAFE_AUTOMATIC` begrenzt |

Vollständiges Protokoll:
[`docs/MusicBot_ARCH-031_Library_Repair_Telegram_Integration_Characterization.md`](../MusicBot_ARCH-031_Library_Repair_Telegram_Integration_Characterization.md),
[`docs/adr/0001`–`0004`](../adr/).

---

## 3. ARCH-032 — Implementation (Phase 1–4)

### Phase 1 — Domain Extraction

| Datei | Inhalt |
|---|---|
| `services/library_repair/artist.py` (neu) | `load_casing_map()`, `normalize_values()` — reine Funktionen, identisches Verhalten zu `fix_artist_casing.py` |
| `services/library_repair/genre.py` (neu) | `genre_from_mapping()`, `normalize_genre_input()`, `known_artist_keys()`, `decide_legacy_genre_removal()` |

Cross-Consistency-Test gegen `GenreMapper` (echte `mapping/artist_genre.yaml`,
read-only) fängt künftige Schema-Drift zwischen beiden Lesepfaden ab.
**34 neue Tests.**

### Phase 2 — Executor Consolidation

`services/library_repair/executor.py` erweitert um:

- `tags_fingerprint()` — SHA-256 über alle Nicht-Ziel-Atome, Beweis, dass
  nur die beabsichtigten Atome verändert wurden.
- `apply_artist_casing()`, `apply_legacy_genre_cleanup()`, `apply_set_genre()`
  — alle nach dem `apply_level1()`-Muster: `safety_check()`, `_sha256()`,
  `_audio_essence_md5()`, `_read_atoms()`/`_write_atoms()`/`_delete_atoms()`,
  `_je_named()` wiederverwendet, keine Duplikation.

Trennlinie Domain/Executor eingehalten: der Executor importiert
`artist.py`/`genre.py` direkt (wie `apply_level1()` bereits `tag_repairs.py`
importiert) und erhält Domain-Daten (Casing-Map, vorbestimmter Zielwert)
als Parameter — keine Domain-Regeln im Executor selbst, kein
Callback-Parameter.

**28 neue Tests** (Success/DryRun/Safety/Rollback/Audio-Essenz/
Target-Non-Target/Journal je Funktion), **55 bestehende Executor-Tests
unverändert grün** (83/83 gesamt nach dieser Phase).

### Phase 3 — Run Tracking, Maintenance Service, CLI, Script-Removal

- **`run_tracking.py`** (neu, ADR-0004): Lock/Journal-Fenster/Run-Index/
  History/Statistik aus `repair_service.py` extrahiert — reiner Move,
  keine Verhaltensänderung. `repair_service.py` re-exportiert alle
  verschobenen Namen (inkl. `Config` selbst, da
  `tests/test_repair_service.py`s bestehende Fixture sonst gebrochen
  wäre). Neues additives `"kind": "repair"|"maintenance"`-Feld in
  Run-Records.
- **`maintenance_service.py`** (neu): Command-Flow-Orchestrierung
  (`preview_*()`/`execute_*()` je Aktion). Preview ruft denselben
  Executor-Pfad mit `dry_run=True` auf wie Execute — garantiert
  identische Domain-Entscheidung.
- **`library_artists.py`** (neu): `list_library_artist_dirs()`/
  `resolve_artist_by_index()` — index-basierte Artist-Auswahl gegen die
  Produktions-Library.
- **`scripts/library_repair.py`** erweitert um
  `--maintenance-action {artist-casing,legacy-genre-cleanup,set-genre}`
  — ein zentraler CLI-Einstiegspunkt statt vier separater Scripts.
- **Script-Removal:** repository-weites Audit (Python-Imports, Shell/
  CI/Cron/Makefile, Tests, Docs) fand **keine funktionalen Aufrufer** der
  drei Original-Scripts — entfernt (kein dokumentierter Produktionslauf,
  kein Wrapper-Ballast).

**72 neue Tests.**

### Phase 4 — Telegram Maintenance

- **`handlers/library_maintenance_handler.py`** (neu): Flow „Artist
  wählen → Aktion wählen → Preview (read-only) → explizite Bestätigung →
  Execute → Ergebnis". `set-genre` über Telegram bewusst nur im
  `--from-mapping`-Modus (kein Freitext-Eingabefeld).
- **Callback-Präfix `libmaint:`** — bewusst **nicht** `maint:`: bei der
  Verdrahtung eine **echte, bis dahin unentdeckte Kollision** mit dem
  bereits produktiven Bot-Wartungsmodus-Präfix gefunden und vermieden,
  bevor sie live ging.
- Lock-Status wird vor jedem Execute explizit geprüft
  (Doppelklick-Schutz), zusätzlich zur eigentlichen Race-sicheren
  Durchsetzung in `acquire_repair_lock()`.
- Verdrahtung: `handlers/menu/actions/library.py` (neuer Dispatcher mit
  eigenem Admin-Check, Defense-in-Depth wie `doctor:`/`review:`/`repair:`),
  `rich_menu_system.py` (Setter + Wrapper + Prefix-Dispatch),
  `rich_menu_handler.py` (Konstruktion, Injection, `CallbackQueryHandler`-
  Registrierung für `^libmaint:` — ohne diese Registrierung wäre jeder
  Callback stillschweigend verpufft, derselbe „Bug B"-Fall wie bei allen
  bisherigen Präfixen), `definitions.py` (neuer Menüpunkt).
- Zwei bestehende Tests mussten an die additive Strukturänderung
  angepasst werden (`_FakeSystem` um neuen Handler-Namen ergänzt,
  TGPERM-001-Sweep-Test um `libmaint:` in `_GATED_PREFIXES` ergänzt,
  Handler-Status-Tracker-Count 17→18) — reine Anpassung, keine Assertion
  abgeschwächt.

**44 neue Tests** (Handler-interne Logik + Dispatch-/Gating-Ebene).

---

## 4. Cache-Import-Fix (außerhalb des ursprünglichen Auftrags, auf Bitte behoben)

Bei der ARCH-032-Verifikation entdeckt: `services/duplicate/cache.py` und
`services/metadata/cache.py` hatten bereits zu Sessionbeginn uncommittete,
vom Auftrag unabhängige kaputte Änderungen — `from config import
DUPLICATE_CACHE_DIR`/`METADATA_CACHE_DIR`, obwohl beide nur als
`Config`-Klassenattribute existieren. Blockierte jeden Import von
`handlers/menu/rich_menu_system.py`.

Auf expliziten Nutzer-Auftrag behoben:

- **`services/duplicate/cache.py`**: Import auf `from config import Config`
  korrigiert; `cache_dir`-Parameter wiederhergestellt (Entfernen hätte
  `detector.py`/`duplicate_handler.py` + 6 Testaufrufer gebrochen, die
  alle explizit `cache_dir=` übergeben). Default jetzt `None` →
  `Config.DUPLICATE_CACHE_DIR` — behebt nebenbei einen vorbestehenden
  toten Fallback-Zweig (undefinierter Name, nie ausgelöst, da der alte
  Default immer truthy war).
- **`services/metadata/cache.py`**: `_video_id_index_path` wieder aus dem
  injizierten `metadata_cache.cache_path` abgeleitet statt aus einem
  fest verdrahteten zentralen Verzeichnis — sonst echte
  Test-Isolations-Regression (TESTENV-01-Fehlerklasse: isolierte
  Test-Caches hätten ihren Index im echten Produktionsverzeichnis
  abgelegt).

**36 gezielte + 106 thematische Tests grün.**

---

## 5. Test-Evidenz (Gesamtübersicht)

| Ebene | Ergebnis |
|---|---|
| Phase 1 (gezielt) | 34 passed |
| Phase 2 (gezielt + Regression) | 83 passed (28 neu + 55 bestehend) |
| Phase 3 (gezielt) | 72 passed |
| Phase 4 (gezielt) | 44 passed |
| **Summe neue Tests** | **178** |
| Thematischer Sweep (alle 4 Phasen + gesamtes Menu-System) | 771 passed, 0 failed |
| Cache-Fix (gezielt + thematisch) | 36 + 106 passed |
| Handler-Status-Tracker-Regressionsfix | 10 passed |
| **Volle Suite (Nutzer, CLAUDE.md §8.A)** | **4250 passed / 1 skipped / 11 subtests passed / 0 failed** (250,52 s) |

0 Regressionen über die gesamte Serie. Keine Produktions-Library berührt
— alle Tests liefen gegen `tmp_path`/ffmpeg-generierte isolierte
Test-Dateien.

---

## 6. Baseline v10 Freeze

Im Anschluss auf Nutzer-Auftrag „Baseline v10 einfrieren" ein echtes,
eigenständiges **Freeze-Gate-Audit** durchgeführt (nicht automatisch mit
der Freeze-Anfrage gleichgesetzt, CLAUDE.md-Vorgabe):

| Kriterium | Ergebnis |
|---|---|
| Offene P0/P1-Findings | **0** (repoweit gegen `docs/FINDINGS_INDEX.md` verifiziert — jede `P0`-/`P1`-markierte Zeile CLOSED) |
| Volle Testsuite | 4250 passed / 1 skipped / 11 subtests passed / 0 failed |
| Bekannte Regressionen | keine |
| Schichtgrenzen-Verletzungen | keine (alle neuen Module additiv innerhalb der CLAUDE.md-§4-Schichten) |
| Produktions-Datensicherheit | kein Crash/Korruption/Datenverlust während der gesamten Serie |

**Verdikt: 🟢 APPROVED.**

Mechanische Nacharbeit (CLAUDE.md: Freeze-Abschluss ist selbsttätig nach
einem APPROVED):

- `docs/MusicBot_ENGINEERING_BASELINE_v10.md`: DRAFT-Kopf ersetzt,
  Abschnitte 4 (Technical Debt Snapshot, 10 offene P2/P3-Punkte), 5
  (Security-Baseline: TGPERM-001 + PMA-F1/F2, beide CLOSED) und 6
  (Architecture Freeze, GO mit Evidenz-Tabelle) befüllt, „Baseline
  Frozen (2026-09-14)"-Footer gesetzt.
- `docs/MusicBot_ENGINEERING_BASELINE_v9.md` → `docs/archive/` verschoben
  (`git mv`, Inhalt unverändert, Präzedenz wie v8).
- Referenzen nachgezogen: `README.md`, `docs/INDEX.md`, `CLAUDE.md`
  (Baseline-Pflege-Abschnitt), `docs/FINDINGS_INDEX.md`, sowie die zwei
  lebenden Dokumente `MusicBot_ARCHITECTURE_EVOLUTION.md`/
  `MusicBot_TELEGRAM_MENU_SYSTEM.md`. Rein historische ARCH-Audit-Dokumente
  (ARCH-025/029/030, `FULL_PROJECT_ARCHITECTURE_AUDIT_2026-09-12.md`)
  bewusst **nicht** angefasst — sie beschreiben den Stand zum jeweiligen
  Analysezeitpunkt (Projektkonvention).

---

## 7. Git / PR

Alle Commits dieser Serie entstanden zunächst direkt auf lokalem `main`
(kein Branch). Für den Merge nachträglich korrekt eingebettet:

1. Feature-Branch `arch-032/library-maintenance-consolidation` am
   damaligen `main`-HEAD erstellt (alle 11 Commits gesichert).
2. Branch gepusht, **PR #244** erstellt (`main` ← `arch-032/library-maintenance-consolidation`).
3. PR gemergt (`gh pr merge --merge --delete-branch`) → `706b9b5` auf
   `origin/main`.
4. Lokaler `main` per Fast-Forward synchronisiert (kein `reset --hard`
   nötig — der Sicherheits-Classifier hätte das ohnehin blockiert; ein
   normaler `git pull`/Fast-Forward reichte, da der lokale `main`-Tip
   bereits Vorfahre des Merge-Commits war).
5. Lokaler und Remote-Feature-Branch gelöscht, veraltete
   Remote-Tracking-Refs geprunt (`git remote prune origin`).

**Endzustand:** `main` lokal == `origin/main` (`706b9b5`), keine offenen
PRs, keine verwaisten Branches.

**Bewusst unangetastet** (nicht Teil dieses Auftrags, bereits zu
Sessionbeginn uncommittet): `mapping/artist_genre.yaml`,
`mapping/auto_learned_featured_artists.json`, `.claude/settings.json`.

---

## 8. Findings — Geschlossen / Weiterhin offen

**Geschlossen in dieser Serie:**

- ARCH-032 (Library Maintenance Consolidation, Phasen 1–4) — vollständig
- Cache-Import-Fix (`services/duplicate/cache.py`/`services/metadata/cache.py`)

**Weiterhin offen** (alle P2/P3, bewusst zurückgestellt,
siehe `docs/FINDINGS_INDEX.md`/`docs/LIBRARY_REPAIR.md` §11.4):

| Punkt | Priorität |
|---|---|
| `GENRE_EMPTY`/`META_GENRE_MISSING` künftig über leichteren `set-genre --from-mapping`-Pfad? | P3 |
| `tags_fingerprint()`-Retrofit auf `apply_level1()`? | P3 |
| `--update-manual-mapping` als künftige, review-pflichtige Telegram-Funktion? | P3 |
| `--only-if-missing` als Telegram-Option? | P3 |
| **ARCH-033** — Telegram Level-2/Level-3 Repair (`execute_level2_repair`/`execute_level3_repair`, Pro-Artist-Freigabe, ADR-0003) | P2, noch nicht begonnen |

---

## 9. Definition of Done

```text
[x] ARCH-031 Characterization + verbindliche Entscheidung abgeschlossen
[x] ARCH-032 Phase 1-4 vollständig umgesetzt
[x] ARCH-033 bewusst NICHT angefasst (eigene Phase)
[x] Repository-weites Script-Removal-Audit vor dem Löschen durchgeführt
[x] Cache-Import-Fix (Nutzer-Auftrag) behoben, keine Regression
[x] 178 neue gezielte Tests + thematischer Sweep (771) + Cache-Fix (142) gruen
[x] Volle Suite durch den Nutzer: 4250 passed / 1 skipped / 0 failed
[x] Keine Produktions-Library veraendert
[x] Freeze-Gate-Audit als eigener Schritt durchgefuehrt -> APPROVED
[x] Baseline v10 eingefroren, v9 archiviert, Referenzen nachgezogen
[x] docs/LIBRARY_REPAIR.md §11, FINDINGS_INDEX.md, ADR-0001-0004 aktuell
[x] PR #244 erstellt und gemergt
[x] Git aufgeraeumt (Branch geloescht, main synchron, Refs geprunt)
```

---

## 10. Verdikt

**🟢 CLOSED.** Alle beauftragten Phasen (ARCH-031 Decision, ARCH-032
Implementation Phase 1–4, Cache-Fix, Baseline-v10-Freeze, PR-Merge,
Git-Cleanup) sind vollständig, verifiziert und dokumentiert
abgeschlossen. ARCH-033 (Telegram Level-2/Level-3) ist die einzige noch
offene, in ARCH-031 bereits beschlossene Folgephase — bewusst nicht Teil
dieser Serie.
