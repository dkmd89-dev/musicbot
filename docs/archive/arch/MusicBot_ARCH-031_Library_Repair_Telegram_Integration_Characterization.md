# MusicBot ARCH-031 — Library Repair Telegram Integration & Maintenance Consolidation (Characterization + Decision)

**Status:** DECISION COMPLETE, KEINE IMPLEMENTIERUNG — Grundlage für ARCH-032
(Library Maintenance Consolidation) und ARCH-033 (Telegram Level-2/Level-3
Repair).

**Nummern-Hinweis (analog zum dokumentierten ARCH-021/022-Präzedenzfall,
siehe `docs/INDEX.md`):** der Auftrag bezeichnete diese Phase als
"ARCH-030" — dieser Bezeichner ist bereits vergeben
(`docs/MusicBot_ARCH-030_Error_Handler_F7_Closure.md`, PR #243, `bb6f2fe`,
gemergt). Diese Phase läuft daher als **ARCH-031**, die beiden
ursprünglich als "ARCH-031"/"ARCH-032" bezeichneten Folge-Phasen als
**ARCH-032**/**ARCH-033**.

**Ausgangspunkt:** `docs/designs/library-repair-telegram-integration-overview.md`
+ `docs/adr/0001`–`0003` (vorherige Design-Session, 2026-09-14) — diese
Phase vertieft Characterization, trifft die dort offen gelassenen
Architekturentscheidungen verbindlich und ergänzt `docs/adr/0004`.

---

## A. Current-State Characterization

### A.1 Bestehende Komponenten (unverändert, Grundlage)

| Komponente | Datei | Rolle |
|---|---|---|
| Repair Planner | `services/library_repair/planner.py` | Health-Issue-Code → `RepairSpec` (rein, kein I/O). `REGISTRY` deckt alle `ALL_CODES` aus `services/library_health/issues.py` ab (test-verifiziert). |
| Repair Executor | `services/library_repair/executor.py` (1748 Zeilen) | Einzige Schicht mit produktiver Datei-Mutation. `safety_check()`, `_sha256()`, `_audio_essence_md5()`, `apply_level1()`, `apply_level1_rename()`, `apply_cover_repairs()`, `apply_album_cover_unify()`, `apply_external_metadata()`, `apply_level2()`, `apply_replaygain()`. |
| Repair Service | `services/library_repair/repair_service.py` (520 Zeilen) | Finding-Flow-Orchestrierung: `build_repair_plan()`, `execute_safe_automatic_repair()`, Lock/Journal-Fenster/Run-Index/Statistik (aktuell alles hier, siehe ADR-0004). |
| Doctor Runner | `services/library_repair/doctor_runner.py` (214 Zeilen) | Reine Subprozess-Orchestrierung `library_health_check.py`/`library_repair.py --level SAFE_AUTOMATIC --apply`. Kein Import von `executor.py` direkt — geht über den CLI-Subprozess. |
| Journal | `services/library_repair/journal.py` | `RepairJournal` — Append-Only JSONL, EINE Produktions-Datei `<DATA_DIR>/library_repair_journal.jsonl`. |
| Telegram Finding-Flow | `handlers/repair_musicbot_handler.py` (507 Zeilen) | Analyze/Proposals/Preview/Confirm/Execute/History/Stats — ruft ausschließlich `repair_service.py` auf, keine eigene I/O. |
| Telegram Doctor-Shortcut | `handlers/library_doctor_handler.py` | Scan + `SAFE_AUTOMATIC`-Kurzweg über `doctor_runner.py`. |
| Genre-Fallback-Kette | `utils/genre_map.py::GenreMapper` (SingletonMixin) | `determine_genre()` (Manuell→Lokal→MusicBrainz→Last.fm→Feature-Artist), `normalize_genre_name()`, `validate_genre()`. Schwergewichtig (externe Clients), download-zeit-orientiert. |
| Artist-Identität | `services/metadata/artist_identity_resolver.py::ArtistIdentityResolver` | Download-zeit-Identitätsentscheidung (`artist_override > known_artist > auto_learned_alias > library_identity > musicbrainz_mbid > parser`). **Kein** Casing-Normalisierungswerkzeug für bereits geschriebene Dateien. |
| Multi-Artist-Split | `services/metadata/models.py::split_main_and_featuring()` | Von `tag_repairs.py` bewusst leichtgewichtig nachgebildet (`split_joined_artist()`), um `services.metadata` nicht zu importieren — **etabliertes Präzedenzmuster**, das ARCH-032 für `artist.py`/`genre.py` fortsetzt. |
| Artist-Auswahl-Präzedenz | `services/metadata/reprocessing_runner.py::list_available_artist_dirs()` + `handlers/menu/reprocessing_menu_handler.py::show_artist_list()`/`_resolve_artist_by_index()` | **Bereits etabliertes** Muster: Verzeichnisliste → indexbasierte `callback_data` (`reprocess:pick:<idx>`) statt Roh-String → Re-Resolve bei jedem Schritt. Listet aktuell **`/tmp/musicbot_test/metadaten`** (Test-Sandbox), NICHT die Produktions-Library — Mechanik ist aber 1:1 übertragbar. |

### A.2 Die drei neuen Scripts — vollständige Characterization

Ablaufschema (alle drei identisch):

```text
Input (--artist/--path/--all)
   ↓
collect_targets() — Artist-Verzeichnis- bzw. Pfad-Auflösung gegen Config.LIBRARY_DIR
   ↓
pro Datei: safety_check() (Symlink/Library-Grenze/.m4a/leer)
   ↓
Tag lesen (mutagen MP4)
   ↓
Entscheidung (rein, deterministisch)
   ↓
Dry-Run? → Vorschau, STOP
   ↓
Backup (.library_repair_backups/, außerhalb der Library)
   ↓
Schreiben auf temp-Sibling
   ↓
Verifikation (Ziel-Atome + Audio-Essenz-MD5 [+ tags_fingerprint bei fix_artist_casing/set_genre])
   ↓
atomarer replace()
   ↓
Journal-Append (EIGENE Datei unter /tmp/musicbot_test/*.jsonl — NICHT die Produktions-Journal-Datei)
```

| | Domain-Logik (rein) | I/O (Executor-Zuständigkeit) | Sicherheitslogik (bereits in `executor.py`) | Telegram-tauglich? |
|---|---|---|---|---|
| `fix_artist_casing.py` | `load_casing_map()`, `normalize_values()`, `_to_str()` | Backup/Temp-Sibling/Replace/Journal | `safety_check()`, `essence_md5()`, SHA-256 — **1:1-Duplikat** von `executor.py` | JA — Defekt ist datei-lokal, Entscheidung deterministisch, kein Netzwerk |
| `remove_legacy_genre_atom.py` | Legacy-vs-kanonisch-Vergleich in `fix_one()` (nicht separat extrahiert) | dito | dito | JA — rein lokal, deterministisch |
| `set_genre.py` | `normalize_genre_input()`, `genre_from_mapping()`, `_known_artist_keys()` | dito + optionaler `update_manual_mapping()`-Pfad (schreibt `mapping/artist_genre.yaml` direkt, **kein** Executor-Muster: kein Backup/keine Atomarität außer `.tmp`+`replace`) | dito | Tag-Write JA; `--update-manual-mapping` NEIN (siehe A.4) |

**Was darf niemals in den Telegram-Handler:** jegliche `mutagen`-Schreibzugriffe,
`ffmpeg`-Aufrufe, Backup-Pfad-Konstruktion, `tmp.replace()`, Journal-Writes —
das gilt für alle drei Scripts identisch und deckt sich mit der bestehenden
Schichtgrenze (`handlers/` hält keine Fachlogik, CLAUDE.md §4).

**Welche CLI-Semantik muss erhalten bleiben:** `--artist`/`--path`/`--all`
(Ziel-Auswahl), Dry-Run-Default, `--apply`. `set_genre.py` zusätzlich
`--genre`/`--from-mapping`/`--only-if-missing`/`--update-manual-mapping`.

### A.3 Journal-Abweichung (kritischer Befund, unverändert aus der Vorphase)

Alle drei Scripts schreiben nach `/tmp/musicbot_test/<script>_journal.jsonl`
statt `<DATA_DIR>/library_repair_journal.jsonl`. Damit sind bisherige
(falls durchgeführte) Läufe dieser Scripts **nicht** in
`repair_service.py::load_repair_history()`/`compute_repair_statistics()`
sichtbar — und `/tmp` kann bei einem Neustart geleert werden. Kein aktiver
Datenverlust an Library-Dateien (Backups liegen korrekt unter
`.library_repair_backups/`), aber ein Nachvollziehbarkeits-Gap.

### A.4 `set_genre.py --update-manual-mapping` — gesonderte Prüfung

Schreibt `mapping/artist_genre.yaml` (Fachlogik-Datei, CLAUDE.md §10)
direkt über einen eigenen `.tmp`+`replace()`-Pfad, **außerhalb** jeder
Executor-Journal-/Backup-Konvention (kein `.library_repair_backups`-Eintrag
für Mapping-Änderungen, kein Journal-Eintrag). Strukturell näher an einer
"Config-Änderung" als an einer "Library-Reparatur". Bestätigt: **CLI-only,
kein Telegram-Trigger in ARCH-032** — eine unbeaufsichtigte Telegram-
Mapping-Änderung ohne Review-Schritt würde CLAUDE.md §10 ("Mapping ändern
→ betroffene Beispiele identifizieren → Tests → Änderung → Tests erneut")
unterlaufen. Ob es je eine eigene, review-pflichtige Telegram-Admin-Funktion
wird, bleibt offen — **FOLLOW-UP**, nicht Teil von ARCH-032/033 (siehe G).

### A.5 Test-Bestand (Ist-Coverage)

| Testdatei | Tests | Deckt ab |
|---|---|---|
| `tests/test_library_repair_executor.py` | 55 | `apply_level1`/`apply_level1_rename`/`apply_cover_repairs`/`apply_external_metadata`/`apply_level2`/`apply_replaygain`, Safety/Backup/Rollback/Verify |
| `tests/test_repair_service.py` | 29 | Plan-Filterung, SAFE_AUTOMATIC-Flow, Lock, Verification-Gate, Historie/Statistik |
| `tests/test_repair_musicbot_handler.py` | 37 | Telegram-Handler-Flow, Berechtigungs-Re-Check |
| `tests/test_library_repair_tag_repairs.py` | 17 | reine L1-Tag-Funktionen |
| `tests/test_library_repair_journal.py` | 9 | `RepairJournal` |
| `tests/test_library_doctor_handler.py` | 32 | Doctor-Shortcut |
| `tests/test_library_repair_planner.py`, `_cover_repairs.py`, `_rename_repairs.py`, `_replaygain_repairs.py`, `_external_metadata.py`, `_cli_*`, `_disposition_matrix.py`, `_navidrome_automation.py`, `_executor_l2_real_pipeline.py` | (nicht einzeln gezählt) | Planner-Vollständigkeit, weitere Executor-Teilbereiche, CLI-Scope-Grenzen |
| `fix_artist_casing.py` / `remove_legacy_genre_atom.py` / `set_genre.py` | **0** | **Kein Test vorhanden** — bestätigt aus der Vorphase, kein dokumentierter Produktionslauf |

**Fehlende Coverage (Ziel für ARCH-032):** `artist.py`/`genre.py` (reine
Funktionen), `executor.py::apply_artist_casing/apply_legacy_genre_cleanup/apply_set_genre`
(Safety/Backup/Rollback wie die bestehenden 55 Executor-Tests),
`run_tracking.py` (Extraktions-Regressionstest — muss nach dem Refactor
identisch zu den bestehenden 29 `repair_service`-Tests bleiben),
`maintenance_service.py`, `library_maintenance_handler.py`,
`list_library_artist_dirs()`.

---

## B. Architecture Decision (verbindlich)

### B.1 Wo liegt Artist-Domain-Logik?

`services/library_repair/artist.py` (NEU). Enthält ausschließlich
`load_casing_map()`/`normalize_values()` — **Casing-Konsistenz bereits
geschriebener Dateien**, nicht Identitätsentscheidung. Bewusst getrennt
von `services/metadata/artist_identity_resolver.py` (download-zeit-
Identitätsentscheidung: WELCHER Name ist korrekt) — unterschiedliche
Fragen, unterschiedliche Lebenszyklen, kein Overlap. Kein Import von
`services.metadata` (Präzedenz: `tag_repairs.py`s bewusst leichtgewichtige
Nachbildung von `split_main_and_featuring()`).

### B.2 Wo liegt Genre-Domain-Logik?

`services/library_repair/genre.py` (NEU). Enthält `genre_from_mapping()`,
`normalize_genre_input()`, `_known_artist_keys()`, Legacy-Atom-Entscheidung.
Liest **dieselbe** `mapping/artist_genre.yaml` wie `GenreMapper`s
Manual-Tier — das ist **bewusste, dokumentierte Duplikation**, kein
versehentliches Auseinanderlaufen: `GenreMapper` ist SingletonMixin mit
schwerer Importkette (externe API-Clients), exakt das Muster, das
`tag_repairs.py` bereits für Multi-Artist-Logik vermeidet. Eine leichte,
reine YAML-Lese-Funktion ist für eine Maintenance-Action angemessener als
ein Singleton-Service-Import. **Risiko, dokumentiert statt "gefixt":**
falls sich das YAML-Schema von `artist_genre.yaml` künftig ändert, müssen
beide Stellen synchron aktualisiert werden — Regressionstest-Pflicht in
beiden Testdateien bei Schema-Änderungen (Notiz für `docs/GENRE_SYSTEM.md`).

### B.3 Wo findet Mutation statt?

Ausschließlich `executor.py` (bestätigt, unverändert). Neue Funktionen
`apply_artist_casing()`, `apply_legacy_genre_cleanup()`, `apply_set_genre()`
nach dem `apply_level1()`-Muster (ExecOutcome, RepairJournal, kein eigener
Journal-Pfad). Weder `artist.py`/`genre.py` noch `maintenance_service.py`
noch der Telegram-Handler dürfen `mutagen`-Schreibzugriffe, Backups oder
`replace()` selbst ausführen.

### B.4 `tags_fingerprint()`

**Entscheidung: JA, nach `executor.py` übernehmen** (modulweite Funktion,
kein neues Modul) — Pflicht für die drei neuen `apply_*()`, da sie ohnehin
neu geschrieben werden und die präzisere Verifikation ("nur die
Ziel-Atome haben sich geändert, alle anderen nicht") strukturell zu einer
Maintenance-Action passt, die per Definition **nur** ein bis zwei Atome
anfassen darf.

**Rückwirkende Anwendung auf `apply_level1()`: explizit NICHT Teil von
ARCH-032.** Begründung: `apply_level1()` ist bereits gegen Produktion
gelaufen (12/12 SUCCESS, siehe `docs/LIBRARY_REPAIR.md` §5) und von 55
bestehenden Tests abgedeckt; eine schärfere Verifikation könnte bei einem
bisher tolerierten Nebeneffekt (z. B. Meta-Atom-Reihenfolge durch
mutagen-`save()`) neu als `FAILED` statt `SUCCESS` erscheinen —
CLAUDE.md §21 Regel 2 ("Bestehendes Verhalten nicht unbewusst ändern").
**FOLLOW-UP**, eigene Characterization nötig (siehe G).

### B.5 `maintenance_service.py` — notwendig?

**JA, aber nicht wie ursprünglich skizziert** — siehe ADR-0004: die
gemeinsame Lock-/Journal-/Run-Index-Mechanik wird zuerst nach
`services/library_repair/run_tracking.py` extrahiert (Variante C statt A
oder B), `maintenance_service.py` und `repair_service.py` sind beide
dünne Konsumenten davon. Begründung siehe ADR-0004 (Separation of
Concerns ohne Infrastruktur-Duplikat).

### B.6 Journal/Lock/Run Index

Vollständig geteilt über `run_tracking.py` (ADR-0004). Ein gemeinsamer
Lock über beide Flows hinweg (kein Feingranularitäts-Lock pro Artist —
bewusste Vereinfachung, kein neues Nebenläufigkeitsrisiko). Run-Records
erhalten `"kind": "repair"|"maintenance"` (additiv, rückwärtskompatibel).

### B.7 Telegram-Maintenance-Integration

Neuer Handler `handlers/library_maintenance_handler.py`, neuer
Callback-Präfix `maint:` (registriert in `rich_menu_handler.py` analog zu
`doctor:`/`repair:`/`review:`), neuer Menüpunkt unter „Administration →
Bibliothek & Navidrome" (`handlers/menu/definitions.py`). Der Handler
enthält **keine** Mutagen-/Backup-/Journal-Logik (delegiert vollständig an
`maintenance_service.py`), analog zu `repair_musicbot_handler.py`s
bestehender Selbstbeschränkung.

### B.8 Artist-Auswahl

**Entscheidung: bestehendes Präzedenzmuster wiederverwenden, keine neue
parallele Artist-Resolution.** Neue Funktion
`services/library_repair/library_artists.py::list_library_artist_dirs()`
(analog zu `reprocessing_runner.list_available_artist_dirs()`, aber gegen
`Config.LIBRARY_DIR` statt `/tmp/musicbot_test/metadaten`), Telegram-Picker
per Index (`maint:pick:<idx>`) statt Roh-String in `callback_data` —
identische Anti-Injection-Technik wie im Reprocessing-Menü.

**Wichtige Klarstellung zur "directory name == artist name"-Frage
(Auftrag §15):** das Verzeichnis ist **ausschließlich ein Datei-Scope-
Selektor** (welche `.m4a`-Dateien werden betrachtet), **nicht** die
Quelle der eigentlichen Tag-Entscheidung. Die tatsächliche Änderung
(welcher Artist-Name/welches Genre geschrieben wird) ist bei allen drei
Maintenance-Actions **datengetrieben aus dem Tag-Inhalt bzw. dem Mapping**
(`artist.py::normalize_values()` vergleicht den *Tag-Wert* gegen die
Casing-Map, nicht den Verzeichnisnamen; `genre.py::genre_from_mapping()`
schlägt zwar den Artist-Namen im Mapping nach, aber das ist exakt dieselbe
Semantik wie die bereits etablierte CLI-Nutzung `--artist <Verzeichnis>`
und wie `planner.py::filter_plan(artist=...)` — **kein neues Risiko**,
sondern eine bereits im gesamten Repair-Flow etablierte Konvention.
`ArtistIdentityResolver` wird bewusst **nicht** wiederverwendet — andere
Fragestellung (siehe B.1).

### B.9 Level 2 / Level 3 Integration & Phasentrennung

**Entscheidung: getrennt in ARCH-033**, wie vom Nutzer vorgeschlagen
(dort ursprünglich "ARCH-032"). Begründung (Auftrag §17, bestätigt):

| Kriterium | Maintenance-Actions (ARCH-032) | L2/L3 (ARCH-033) |
|---|---|---|
| Netzwerk | keins (rein lokale Mapping-Dateien) | MusicBrainz/Genius/Last.fm |
| Laufzeit | Millisekunden/Datei | Minuten/Artist |
| Nebeneffekt | keiner (reine Tag-Werte) | Auto-Learn-Mapping-Mutation (L2), Cover-Nebeneffekt |
| Verifikationsmodell | `tags_fingerprint()` + Audio-Essenz (B.4) | Audio-Essenz + Pipeline-`status`-Check (bestehend) |
| Telegram-UX | 1 Artist, 1 Aktion, 1 Confirm | 1 Artist, Preview mit Warnhinweis, 1 Confirm (ADR-0003) |
| Rollback | Backup + atomarer Replace (identisch) | Backup + Audio-Essenz-Revalidierung (identisch, bereits implementiert in `apply_level2()`) |

Unterschiedliches Risikoprofil rechtfertigt getrennte Freigabe-/Test-
Zyklen — konsistent mit CLAUDE.md §3.A ("kleinsten sinnvollen
Migrationsschritt", "keine eigenmächtige Vorwegnahme mehrerer zukünftiger
ARCH-Phasen").

### B.10 CLI-Kompatibilität

| Flag | Ziel |
|---|---|
| `--artist` | CLI **und** Telegram (über `list_library_artist_dirs()`-Picker) |
| `--path` | CLI-only (kein Datei-Browser in Telegram vorgesehen) |
| `--all` | CLI-only (Blast-Radius, siehe ADR-0001-Nachbarbegründung) |
| `--only-if-missing` (set_genre) | CLI-only in dieser Phase; als Telegram-Option denkbar, nicht entschieden (FOLLOW-UP) |
| `--update-manual-mapping` | CLI-only, siehe A.4 |

### B.11 Doctor-Boundary

**Bestätigt unverändert.** `doctor_runner.py`/`library_doctor_handler.py`
bleiben strikt auf `SAFE_AUTOMATIC` begrenzt — keine Erweiterung als
Nebenprodukt dieser Phase (Auftrag §18, explizit eingehalten).

---

## C. Target Architecture

```text
Telegram
   │
   ├── Finding Repair (repair:*)
   │       ↓
   │   repair_service.py ──────────────┐
   │                                   │
   └── Maintenance (maint:*, NEU)      │
           ↓                          │
      maintenance_service.py (NEU) ────┤
           │                          │
           └──────────┬───────────────┘
                       ↓
               run_tracking.py (NEU, ADR-0004)
               [Lock · Journal-Fenster · Run-Index · History · Statistik]
                       │
                       ↓
                  executor.py
                       │
          ┌────────────┼────────────────────────────┐
          ↓            ↓                             ↓
       Safety        Backup                    apply_artist_casing()
   (safety_check,  (.library_repair_          apply_legacy_genre_cleanup()
    _sha256,        backups/, außerhalb        apply_set_genre()      (NEU)
    _audio_essence   der Library)              apply_level1/level2/…  (bestehend)
    _md5,
    tags_fingerprint NEU)
          │            │                             │
          └────────────┼─────────────────────────────┘
                       ↓
                Temp-Sibling → Verify → atomarer replace()
                       │
                       ↓
                 journal.py::RepairJournal
                       │
                       ↓
          <DATA_DIR>/library_repair_journal.jsonl   (EINE Datei, beide Flows)

Domain (rein, kein I/O):
  artist.py  (load_casing_map, normalize_values)
  genre.py   (genre_from_mapping, normalize_genre_input, legacy-atom-decision)
      │
      └──→ von maintenance_service.py konsumiert, NICHT von executor.py
           direkt importiert (executor.py bleibt reine Mechanik-Schicht,
           Domain-Entscheidungen kommen als Parameter herein — identisch
           zum bestehenden Muster tag_repairs.py → apply_level1()).

Artist-Auswahl (NEU):
  services/library_repair/library_artists.py::list_library_artist_dirs()
      │
      └──→ handlers/library_maintenance_handler.py (Index-Picker,
           Präzedenz: reprocessing_menu_handler.py)
```

Vollständiges C4-Container-Diagramm (aktualisiert):
[`docs/diagrams/c4-container-library-repair-telegram.puml`](diagrams/c4-container-library-repair-telegram.puml)
— **Hinweis:** dieses Dokument präzisiert `service.py` als
`run_tracking.py` + `maintenance_service.py` (zwei Module statt eines),
das Diagramm wird im Rahmen von ARCH-032 entsprechend nachgezogen.

---

## D. Migration Plan

**Phasen 1–4 = ARCH-032 (Library Maintenance Consolidation).
Phase 5 = ARCH-033 (Telegram Level-2/Level-3 Repair), hier nur skizziert.**

### Phase 1 — Domain Extraction

| | |
|---|---|
| Dateien | `services/library_repair/artist.py` (NEU), `services/library_repair/genre.py` (NEU) |
| Funktionen | `load_casing_map()`, `normalize_values()`, `_to_str()` → `artist.py`; `genre_from_mapping()`, `normalize_genre_input()`, `_known_artist_keys()`, Legacy-Atom-Entscheidung → `genre.py` |
| Abhängigkeiten | `mapping/artist_overrides.json`, `mapping/case_preserve.yaml`, `mapping/artist_genre.yaml` (nur Read) |
| Tests | `tests/test_library_repair_artist.py` (NEU), `tests/test_library_repair_genre.py` (NEU) — reine Unit-Tests, keine Fixtures nötig (wie `tag_repairs.py`) |
| Risiken | keine (reine Funktionen, kein bestehender Aufrufer betroffen) |
| Rollback | trivial (neue Dateien, keine Fremdreferenz) |
| DoD | 100% Funktionsparität zu den Original-Scripts nachgewiesen (Characterization-Tests mit denselben Eingaben wie die Original-Docstring-Beispiele) |

### Phase 2 — Executor Consolidation

| | |
|---|---|
| Dateien | `services/library_repair/executor.py` (erweitert) |
| Funktionen | NEU: `tags_fingerprint()`, `apply_artist_casing()`, `apply_legacy_genre_cleanup()`, `apply_set_genre()` (alle nach `apply_level1()`-Muster: `ExecOutcome`, `safety_check()`/`_sha256()`/`_audio_essence_md5()` wiederverwendet, kein Duplikat) |
| Abhängigkeiten | Phase 1 (`artist.py`/`genre.py` als Parameter-Input) |
| Tests | `tests/test_library_repair_executor.py` erweitert (Safety/Backup/Verify/Rollback je neuer Funktion, analog zu den bestehenden `apply_level1()`-Tests) |
| Risiken | gering — additiv, keine bestehende Funktion verändert. Einziges Risiko: `tags_fingerprint()` als neue modulweite Funktion braucht eindeutigen Namen ohne Kollision (geprüft: aktuell nicht belegt) |
| Rollback | additiv, trivial |
| DoD | Safety-Check/Backup/Rollback-Pfad für alle drei neuen Funktionen mit mind. je einem FAILED-Pfad-Test verifiziert (Verifikation schlägt fehl → Rollback → Backup bleibt erhalten) |

### Phase 3 — Maintenance Orchestration

| | |
|---|---|
| Dateien | `services/library_repair/run_tracking.py` (NEU, Extraktion aus `repair_service.py`, ADR-0004), `services/library_repair/maintenance_service.py` (NEU), `services/library_repair/library_artists.py` (NEU) |
| Funktionen | `run_tracking.py`: extrahierte Lock/Journal-Fenster/Run-Index/Historie/Statistik-Funktionen (unveränderte Signatur). `maintenance_service.py`: `preview_artist_casing()`, `execute_artist_casing_fix()`, `preview_legacy_genre_cleanup()`, `execute_legacy_genre_cleanup()`, `preview_set_genre()`, `execute_set_genre()`. `library_artists.py`: `list_library_artist_dirs()` |
| Abhängigkeiten | Phase 1 + 2; `repair_service.py` wird auf `run_tracking.py`-Import umgestellt (Re-Export für Rückwärtskompatibilität) |
| Tests | `tests/test_library_repair_run_tracking.py` (NEU, Extraktions-Regressionstest), `tests/test_library_repair_maintenance_service.py` (NEU), `tests/test_repair_service.py` (29 bestehende Tests MÜSSEN unverändert grün bleiben) |
| Risiken | mittel — Extraktion aus `repair_service.py` ist ein Refactor an bereits produktiv gelaufenem Code. Mitigation: reiner Move ohne Verhaltensänderung, Diff-Review gegen die 29 bestehenden Tests vor Merge |
| Rollback | `git revert` der Extraktion, `repair_service.py` fällt auf lokale Funktionen zurück |
| DoD | alle 29 bestehenden `test_repair_service.py`-Tests grün OHNE Änderung an ihren Assertions (nur ggf. Import-Pfad-Anpassung), neue Tests für Maintenance-Flow grün |

### Phase 4 — Telegram Maintenance

| | |
|---|---|
| Dateien | `handlers/library_maintenance_handler.py` (NEU), `handlers/menu/definitions.py` (erweitert), `handlers/menu/rich_menu_handler.py` (erweitert: `maint:`-Callback-Registrierung) |
| Funktionen | `LibraryMaintenanceHandler.handle_start/handle_artist_list/handle_pick_artist/handle_action_select/handle_preview/handle_confirm/handle_execute` (Struktur-Spiegel von `RepairMusicBotHandler`) |
| Abhängigkeiten | Phase 3 |
| Tests | `tests/test_library_maintenance_handler.py` (NEU, analog zu `test_repair_musicbot_handler.py`s 37 Tests: Berechtigungs-Re-Check, kein Auto-Start, Preview read-only) |
| Risiken | gering — rein additiver Telegram-Menüpunkt, kein bestehender Flow verändert |
| Rollback | Menüpunkt-Registrierung entfernen, Handler-Datei bleibt ungenutzt |
| DoD | Admin-Gating (Defense-in-Depth: MenuItem-Ebene + Callback-Dispatcher, TGPERM-001-Muster) verifiziert; "Öffnen des Menüs startet nie automatisch eine Aktion" (wie bei `repair:`/`review:`) getestet |

### Phase 5 — L2/L3 Telegram (ARCH-033, hier nur skizziert)

| | |
|---|---|
| Dateien | `services/library_repair/repair_service.py` (erweitert: `execute_level2_repair(artist)`, `execute_level3_repair(artist)`), `handlers/repair_musicbot_handler.py` (erweitert: Artist-Gruppierung, Pro-Artist-Preview/Confirm) |
| Abhängigkeiten | ADR-0003 (Pro-Artist-Bestätigung), bestehende `apply_level2()`/`apply_external_metadata()` (unverändert) |
| Tests | `tests/test_repair_service.py::TestExecuteLevel2Repair/TestExecuteLevel3Repair`, `tests/test_repair_musicbot_handler.py::TestLevel2Level3TelegramFlow` |
| Risiken | höher als Phase 1–4 (Netzwerk, Laufzeit, Auto-Learn-Mutation) — eigene Freigabe-Iteration in ARCH-033 |
| DoD | siehe `docs/adr/0003-telegram-level2-level3-per-artist-confirmation.md` |

---

## E. Bestehende Scripts — Entscheidung

**Gewählt: Variante zwischen Option A und B — Konsolidierung statt
1:1-Wrapper.** Nach Phase 1–4 (ARCH-032) sind `fix_artist_casing.py`,
`remove_legacy_genre_atom.py`, `set_genre.py` funktional vollständig durch
`services/library_repair/{artist,genre}.py` + `executor.py::apply_*()`
abgedeckt — außer den CLI-only-Fähigkeiten `--all`/`--path`/
`--update-manual-mapping` (B.10).

**Entscheidung:** die drei eigenständigen Script-Dateien werden **nicht**
als dauerhafte 1:1-Wrapper beibehalten (das würde drei weitere
CLI-Einstiegspunkte dauerhaft pflegen, für Funktionalität, die
`scripts/library_repair.py` bereits als zentralen CLI-Wrapper hat).
Stattdessen wird `scripts/library_repair.py` um einen neuen
Maintenance-Modus erweitert (z. B. `--maintenance-action {artist-casing,legacy-genre-cleanup,set-genre} [--all|--path|--artist] [--genre ...] [--only-if-missing] [--update-manual-mapping]`)
— **ein** CLI-Einstiegspunkt für die gesamte Library-Repair-Domäne statt
vier. Die drei Original-Scripts werden nach erfolgreicher Migration
**entfernt** (nicht als Wrapper belassen).

**Warum nicht Option A (Wrapper belassen):** es existiert **kein**
dokumentierter Produktionslauf der drei Scripts (A.5) — anders als bei
`reprocess_artist_metadata.py`, das vor seiner Service-Extraktion bereits
mehrfach validiert war (`docs/METADATA_REPROCESSING.md`). Es gibt daher
keine belegte Backward-Compatibility-Pflicht gegenüber einem externen
Nutzer dieser drei konkreten CLI-Signaturen.

**Warum nicht ersatzlos löschen ohne CLI-Ersatz (reines Option B):** die
`--all`/`--path`-Bulk-Fähigkeit hat einen legitimen eigenständigen
Anwendungsfall (z. B. library-weite Neu-Normalisierung nach einer
Mapping-Änderung) und braucht ein Zuhause — konsolidiert in
`scripts/library_repair.py` statt dauerhaft dupliziert.

**Exakte CLI-Flag-Gestaltung ist Implementierungsdetail von ARCH-032**,
hier nur die Richtungsentscheidung getroffen.

---

## F. ADR-/Dokumentations-Updates

| Dokument | Update nötig? | Begründung |
|---|---|---|
| `docs/adr/0001-library-maintenance-actions-not-finding-driven.md` | NEIN | Entscheidung bereits korrekt (kein CLI-Andock-Pfad, In-Process-Flow) — durch B.1–B.8 bestätigt, nicht revidiert |
| `docs/adr/0002-consolidate-repair-script-boilerplate.md` | NEIN | Duplikat-Tabelle weiterhin akkurat; `tags_fingerprint()`-Entscheidung dort bereits vorweggenommen, hier bestätigt (B.4) |
| `docs/adr/0003-telegram-level2-level3-per-artist-confirmation.md` | NEIN | Inhaltlich unverändert gültig, nur Phasennummer ändert sich (ARCH-032→ARCH-033 in der Prosa dieses Dokuments, nicht im ADR selbst, das keine Phasennummer nennt) |
| `docs/adr/0004-shared-run-tracking-module.md` | NEU erstellt (diese Phase) | Variante-A/B/C-Entscheidung war in der Vorphase noch offen |
| `docs/LIBRARY_REPAIR.md` | JA, in ARCH-032 (nicht hier) | neues §11 "Library-Maintenance-Actions", §9/§10 um `maint:`-Verweis ergänzen |
| `docs/FINDINGS_INDEX.md` | JA (diese Phase, siehe unten) | Eintrag aus der Vorphase auf "Entscheidung getroffen, Umsetzung ARCH-032/033" aktualisieren |
| `docs/MusicBot_ENGINEERING_BASELINE_v10.md` | JA, in ARCH-032/033 (nicht hier) | ARCH Status/Recent Major Changes nach Umsetzung, nicht für eine reine Entscheidungsphase (kein Code-Change) |
| `docs/designs/library-repair-telegram-integration-overview.md` | Kopfzeile ergänzt (diese Phase) | als Vorphasen-Ausgangspunkt markiert, dieses Dokument als Nachfolger referenziert |

---

## G. Findings / Follow-ups (klassifiziert)

| Punkt | Klassifikation | Notiz |
|---|---|---|
| Journal-Pfad-Abweichung der 3 Scripts (`/tmp/musicbot_test/*.jsonl`) | **WIRD IN ARCH-032 BEHOBEN** | Phase 2/3 — Journal-Vereinheitlichung ist Kernbestandteil |
| Fehlende Health-Issue-Codes für Casing/Legacy-Genre | **CLOSED (Entscheidung ADR-0001)** | bewusst kein Health-Issue-Code — Command-Flow statt Finding-Flow |
| `maintenance_service.py` Architektur (A/B/C) | **CLOSED (Entscheidung ADR-0004)** | Variante C — `run_tracking.py`-Extraktion |
| Artist-Auswahl-Sicherheit | **CLOSED (Entscheidung B.8)** | bestehendes Index-Picker-Muster wiederverwendet, kein neues Risiko |
| `GENRE_EMPTY`/`META_GENRE_MISSING` → leichterer `set_genre.py`-Pfad? | **STILL RELEVANT / FOLLOW-UP** | bewusst nicht in ARCH-032/033 entschieden — würde bestehendes, produktiv gelaufenes Planner-Verhalten ändern, eigene Characterization + Nutzerentscheidung nötig |
| `tags_fingerprint()` rückwirkend für `apply_level1()` | **STILL RELEVANT / FOLLOW-UP** | Regressionsrisiko gegen 55 bestehende Executor-Tests, eigene Prüfung nötig (B.4) |
| `set_genre.py --update-manual-mapping` als künftige Telegram-Admin-Funktion | **STILL RELEVANT / FOLLOW-UP** | CLI-only bestätigt für ARCH-032/033, langfristige Frage offen (A.4) |
| Exakte CLI-Flag-Gestaltung für konsolidiertes `library_repair.py` | **FOLLOW-UP (Teil von ARCH-032-Implementierung)** | Richtung entschieden (E), Details sind Implementierungsarbeit |
| Genre-YAML-Doppel-Lesepfad (`GenreMapper` vs. `genre.py`) | **ACCEPTED TECHNICAL DEBT** | bewusst in Kauf genommen (B.2), Synchronisationspflicht bei Schema-Änderungen dokumentiert |
| `--only-if-missing` als Telegram-Option | **FOLLOW-UP** | nicht entschieden, niedrige Priorität |
| Doctor-Boundary-Erweiterung auf L2/L3 | **CLOSED (bewusst nicht Teil dieser/nächster Phasen)** | B.11 |

---

## H. Final Review

### Architektur
- Doppelte Engines? **NEIN** nach Zielarchitektur — ein Executor, ein Journal, ein Lock, ein Run-Index (ADR-0004) für beide Flows.
- Doppelte Safety-Logik? **NEIN** — `safety_check()`/`_sha256()`/`_audio_essence_md5()` einmalig in `executor.py`, von allen `apply_*()` geteilt.
- Doppelte Journal-Logik? **NEIN** nach Migration (aktuell JA — A.3, wird behoben).
- Doppelte Lock-Logik? **NEIN** — ein gemeinsamer Lock (B.6).
- Doppelte Artist-Resolution? **NEIN** — bestehendes Index-Picker-Muster wiederverwendet (B.8), `ArtistIdentityResolver` bewusst nicht involviert (andere Fragestellung).

### Security
- Kann Telegram versehentlich `--all` auslösen? **NEIN** — Telegram bietet strukturell nur Artist-Picker (B.10), `--all`/`--path` existieren im Telegram-Codepfad gar nicht.
- Kann Telegram beliebige Pfade übergeben? **NEIN** — Index-basierte `callback_data` (B.8), kein Freitext-Pfad.
- Kann ein User außerhalb der Library schreiben? **NEIN** — `safety_check()` erzwingt Library-Grenze (unverändert, bereits gehärtet).
- Sind Admin-Grenzen klar? **JA** — Defense-in-Depth-Muster (MenuItem + Callback-Dispatcher) wie bei `repair:`/`review:`/`doctor:` fortgesetzt (Phase 4 DoD).

### Data Safety
- Backup vorhanden? **JA**, identisches Muster für alle neuen `apply_*()`.
- Audio Essence geschützt? **JA**, `_audio_essence_md5()` wiederverwendet.
- Atomic Replace? **JA**, identisches Muster.
- Rollback? **JA**, Backup-Restore bei fehlgeschlagener Verifikation.
- Target-/Non-target-Tag-Verification? **JA** — `tags_fingerprint()` (B.4), strenger als das bisherige L1-Muster.

### Maintainability
- Sind Scripts nur Wrapper? **Nach ARCH-032: entfernt** (E) — kein permanenter Wrapper-Ballast.
- Ist Domain-Logik testbar? **JA** — reine Funktionen ohne I/O (Phase 1).
- Ist Mutation zentral? **JA** — ausschließlich `executor.py` (B.3).
- Ist Orchestration sauber getrennt? **JA** — `run_tracking.py` (geteilt) vs. `repair_service.py`/`maintenance_service.py` (flow-spezifisch), ADR-0004.

### UX
- Ist Preview verständlich? Struktur identisch zum bewährten `repair_musicbot_handler.py`-Muster (Preview vor Confirm, read-only).
- Ist Confirmation eindeutig? JA — expliziter Tap pro Aktion, kein Auto-Start (Phase 4 DoD).
- Ist Artist-Auswahl sicher? JA (B.8).
- Sind L2/L3-Operationen ausreichend explizit? JA — Warnhinweis in Preview vorgesehen (ADR-0003), Pro-Artist statt Blanket-Confirm.

---

## I. Audit

**Was wissen wir sicher?**
Vollständige Characterization aller 3 Scripts, aller relevanten
Bestandskomponenten (Executor/Service/Doctor/Journal/Planner/Telegram-
Handler/Genre-/Artist-Domain-Infrastruktur/Artist-Auswahl-Präzedenz) und
des Test-Bestands (A). Alle in §4 des Auftrags verlangten
Architekturfragen (1–10) sind unter B.1–B.11 explizit beantwortet.

**Was ist Architekturentscheidung?**
B.1–B.11 sind verbindliche Entscheidungen dieser Phase, dokumentiert mit
Begründung und in ADR-0004 vertieft. Sie widersprechen keiner der
Vorphasen-ADRs (0001–0003), sondern verfeinern/bestätigen sie.

**Was ist noch offen?**
Vier explizite FOLLOW-UPs (G): GENRE_EMPTY/META_GENRE_MISSING-Pfad,
`tags_fingerprint()`-Retrofit auf L1, Zukunft von
`--update-manual-mapping` als Telegram-Funktion, exakte CLI-Flag-
Gestaltung des konsolidierten `library_repair.py`.

**Was wird in ARCH-032 umgesetzt?**
Phasen 1–4 (Domain Extraction, Executor Consolidation, Maintenance
Orchestration, Telegram Maintenance) — vollständig in D spezifiziert.

**Was wird in ARCH-033 umgesetzt?**
Phase 5 (Telegram L2/L3, `execute_level2_repair`/`execute_level3_repair`,
Artist-Gruppierung in `repair_musicbot_handler.py`) — Details in
`docs/adr/0003-telegram-level2-level3-per-artist-confirmation.md`.

**Was bleibt bewusst unverändert?**
`services/library_health/` (P0, keine neuen Issue-Codes, B.1-Begründung),
`doctor_runner.py`/`library_doctor_handler.py` (B.11), `GenreMapper`/
`ArtistIdentityResolver` (unverändert, nur bewusst NICHT wiederverwendet
für die Maintenance-Domäne, B.1/B.2), bestehende Executor-Funktionen
`apply_level1`/`apply_level2`/etc. (nur additiv erweitert, keine
Verhaltensänderung).

**Verdikt: 🟢 ENTSCHEIDUNG VOLLSTÄNDIG — ARCH-032 kann mit dem in Abschnitt
D spezifizierten Migrationsplan beginnen, ohne während der Implementierung
weitere grundlegende Architekturfragen klären zu müssen.**

---

## J. Definition of Done (dieser Phase)

```text
[x] Current-State Characterization abgeschlossen (A)
[x] drei Maintenance Scripts vollständig charakterisiert (A.2)
[x] Executor-Duplikate identifiziert (A.2-Tabelle)
[x] Domain-/Mutation-Grenze definiert (B.1–B.3)
[x] tags_fingerprint() Entscheidung getroffen (B.4)
[x] maintenance_service.py Entscheidung getroffen (B.5, ADR-0004)
[x] Journal/Lock/Run Index Zielarchitektur geklärt (B.6)
[x] Telegram Maintenance Zielarchitektur definiert (B.7)
[x] Artist Resolution geklärt (B.8)
[x] L2/L3 separat bewertet (B.9)
[x] ARCH-032 Entscheidung getroffen (D, Phasen 1–4)
[x] ARCH-033 Entscheidung getroffen (D, Phase 5 skizziert)
[x] CLI-Kompatibilität geklärt (B.10)
[x] Doctor Boundary bestätigt (B.11)
[x] GENRE_EMPTY / META_GENRE_MISSING bewusst bewertet (G, FOLLOW-UP)
[x] Testmatrix erstellt (A.5, D je Phase)
[x] Sicherheitsrisiken bewertet (H, Security-Abschnitt)
[x] Migrationsreihenfolge definiert (D)
[x] ADR-Auswirkungen dokumentiert (F)
[x] LIBRARY_REPAIR.md Update geplant (F, für ARCH-032)
[x] FINDINGS_INDEX.md Update geplant (siehe Commit dieser Phase)
[x] finale Review durchgeführt (H)
[x] finaler Audit durchgeführt (I)
```

Keine produktiven Library-Dateien wurden in dieser Phase verändert, keine
Reparatur ausgeführt, kein Telegram-Code geändert (§30 der Auftrags-
Scope-Grenze eingehalten).
