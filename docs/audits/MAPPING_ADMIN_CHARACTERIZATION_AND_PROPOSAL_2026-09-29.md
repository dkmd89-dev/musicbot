# Mapping Administration im Control Center — Characterization + Architecture Proposal

**Stand:** 2026-09-29 · **Status:** DRAFT (Phase 1+2, noch kein Code)
**Auftrag:** `mapping.txt` (Master Prompt Mapping Integration)
**Vorgehen:** Characterization am Code (Phase 1) → Architektur-Entscheidung (Phase 2) → explizites GO/NO-GO. Phase 3+ (Implementierung, UI, Tests) erst nach GO.

---

## Phase 1 — Characterization

### 1.1 Mapping-Inventur

Alle Mapping-Dateien liegen in `mapping/` (nicht `data/` — `data/` enthält nur Laufzeit-Zustand: Findings, Reports, Journals, User-Daten).

| Datei | Zweck | Reader (Code) | Writer (Code) | manuell/auto | Format | Reload | Neustart nötig |
|---|---|---|---|---|---|---|---|
| `artist_genre.yaml` | Genre pro Artist | `GenreMapper`, `library_repair/genre.py` | `library_repair/genre.py::save_manual_genre_mapping` + **bestehender CC-Pfad** | manuell (CC+Editor) | YAML | keiner | **ja** |
| `channel_genre.yaml` | Genre pro YouTube-Kanal | `GenreMapper` | niemand | manuell | YAML | keiner | ja |
| `genre_hierarchy.yaml` | Genre-Prioritäts-Hierarchie | `GenreProcessor` | niemand | manuell | YAML | keiner | ja |
| `genre_aliases.yaml` | Alias → Canonical-Genre | `GenreProcessor`, `GenreMapper` | niemand | manuell | YAML | keiner | ja |
| `genre_filters.yaml` | Ignore-Liste Sekundär-Genres | `GenreProcessor` | niemand | manuell | YAML | keiner | ja |
| `genre_overrides.yaml` | Genre-Overrides | `GenreMapper` | niemand | manuell | YAML | keiner | ja |
| `genre_rules.yaml` | Regex-Regeln | `GenreMapper` | niemand | manuell | YAML | keiner | ja |
| `artist_overrides.json` | Casing-Kanonisierung | `library_repair/artist.py`, `ArtistNormalizer` | niemand | manuell | JSON | keiner | ja |
| `case_preserve.yaml` | Casing-Mapping (Original-Schreibweise) | `ArtistNormalizer` | **`ArtistNormalizer._save_case_preserve_entry`** (Bot-Auto-Learn) | **Hybrid** | YAML | keiner | ja |
| `known_artists.yaml` | Bestätigte Artist-Identitäten | `ArtistIdentityResolver` | **`AutoLearnManager._write_known_artist_sync`** (Bot-Auto-Learn) | **Hybrid** | YAML | keiner | ja |
| `special_channel.yaml` | Spezialkanäle (Podcast/Audiobook) | `filenamefixer`, `enhanced_metadata_processor` | niemand | manuell | YAML | keiner | ja |
| `auto_learned_genre.json` | Gelernte Genre-Zuordnungen | `AutoLearnManager` | `AutoLearnManager._write_genre_observation_sync` | **auto** | JSON | `reload_auto_learned()` nur für Aliases | ja |
| `auto_learned_artist_aliases.json` | Kanal-Namen → kanonische Artists | `ArtistNormalizer`, `AutoLearnManager` | `AutoLearnManager._write_alias_sync` | **auto** | JSON | **`ArtistNormalizer.reload_auto_learned()`** vorhanden, aber niemand ruft auf | ja |
| `auto_learned_featured_artists.json` | Feature-Artist-Beobachtungen | `AutoLearnManager` | `AutoLearnManager._observe_single_featured_artist` | **auto** | JSON | keiner | ja |

### 1.2 Bestehender Schreibpfad (Referenz-Blaupause)

Der CC hat bereits einen vollständigen Pfad für **genau eine** Datei (`artist_genre.yaml`):

control_center/routers/metadata_actions.py
GET    /api/v1/library/artists/{artist}/genre-mapping
POST   /api/v1/library/artists/{artist}/genre-mapping/preview
PUT    /api/v1/library/artists/{artist}/genre-mapping
│
▼
services/library_repair/genre.py
get_genre_mapping / plan_manual_genre_mapping / apply_manual_genre_mapping
│
▼
atomic write: tmp + Path.replace()
Etag-Konflikterkennung: 409 bei veraltetem Etag
Response-Feld: bot_reload_required: true

```

Frontend: `library_artist.js` (~100 Zeilen, sauber strukturiert: `_genreMap`-State, Preview-Karte mit Diff-Chips, Confirm vor Save, Etag).

**Das ist die Blaupause.** Die Frage in Phase 2 lautet: generalisieren oder duplizieren?

### 1.3 Reload-/Wirksamkeits-Befund

- `GenreMapper.reload()` existiert, lädt alles neu, cleared `lru_cache`. **Wird aber nirgends aufgerufen** (`genre_revalidation.py:102` verweigert sich mit Begründung: hardkodierter Pfad).
- `ArtistNormalizer.reload_auto_learned()` existiert, lädt `auto_learned_artist_aliases.json` neu. **Wird nirgends aufgerufen** außer in Tests.
- **Konsequenz heute:** jede Mapping-Änderung ist erst nach Bot-Neustart wirksam. Der bestehende CC-Pfad sagt das ehrlich (`bot_reload_required: true`).

### 1.4 Persistenz-Befund

- **Atomarer Write:** im bestehenden CC-Pfad ja (`tmp + replace`). Bei `AutoLearnManager`: ja (`_write_yaml_atomic` / `_write_json_atomic`).
- **Cross-Process-Lock:** **nirgends im Mapping-Pfad.** Bei `artist_genre.yaml` vertretbar (Bot liest nur, CC schreibt). Bei `case_preserve.yaml` / `known_artists.yaml` **nicht** vertretbar — beide werden vom Bot geschrieben (Rule 2/3 bzw. `AutoLearnManager`), sobald der CC sie editieren kann, entsteht eine echte Lost-Update-Race.
- `services/user_data.py` und `utils/file_lock.py::cross_process_lock` existieren bereits (aus D.13) — wiederverwendbar.

### 1.5 Security-relevante Befunde

- Bestehender Genre-Mapping-Pfad: ADMIN, Same-Origin-Check, Etag-Konflikt, keine Path-Übergabe vom Client (nur `artist` als Pfad-Bestandteil, serverseitig aufgelöst).
- Was **fehlt**, sobald verallgemeinert: **Mapping-ID-Allowlist**, weil Dateinamen nicht mehr aus dem Client kommen dürfen.

### 1.6 Risiken / Findings (nur dokumentiert, nicht behoben)

| # | Risiko | Dateien | Schwere |
|---|---|---|---|
| R1 | Cross-Process-Write-Race | `case_preserve.yaml`, `known_artists.yaml`, `auto_learned_*.json` | **P2** — real, sobald CC diese Dateien schreibend anfasst |
| R2 | `GenreMapper.reload()` hardkodiert `"mapping"` (bekanntes DEFER) | `utils/genre_map.py:1007` | P3 — vorbestehend |
| R3 | Hybrid-Dateien: Bot-Auto-Learn + manuelle Pflege | `case_preserve.yaml`, `known_artists.yaml` | **P2** — Überschreibungs-Gefahr bei CC-Editor |
| R4 | `SingletonMixin`: erste Instanz bestimmt `mapping_dir` | `GenreMapper`, `ArtistNormalizer` | P3 — bekannte Singleton-Semantik |
| R5 | `@lru_cache` ohne Invalidierung | `GenreMapper.get_main_genre`, `normalize_genre_name` | P3 — Änderung wirkt selbst nach Reload verzögert |
| R6 | Kein Reset/Revert für Auto-Learned-Daten | `auto_learned_*.json` | P3 — wäre neue Fachlogik, kein UI-Add-on |

---

## Phase 2 — Architecture Proposal

### 2.1 Zielarchitektur

Control Center
└─ /api/v1/admin/mappings
├─ GET  /{mapping_id}                 (Stand + Etag)
├─ POST /{mapping_id}/preview         (Diff, kein Write)
├─ PUT  /{mapping_id}                 (Write + Etag-Konflikt → 409)
└─ GET  /{mapping_id}/auto-learned    (nur Statistik, read-only)
│
▼
services/mapping_admin.py   (NEU — kleinste notwendige Schicht)
│
├─ MappingDescriptor: id, path, format, schema, writer,
│                     lock_mode, reload_strategy
├─ ALLOWLIST (id → Descriptor) — keine freien Dateinamen
├─ cross_process_lock (nur bei lock_mode="cross_process")
└─ atomarer Write (tmp+replace, etag-Konflikt)
│
▼
bestehende Domain-Writer, wo vorhanden
(services/library_repair/genre.py für artist-genre)

### 2.2 Mapping-ID-Allowlist (Vorschlag, gruppiert)

| mapping_id | Datei | Modus | Lock | Priorität |
|---|---|---|---|---|
| `channel-genre` | `mapping/channel_genre.yaml` | edit | none | **M1 (Referenz)** |
| `artist-genre` | `mapping/artist_genre.yaml` | edit | none | M2 (Migration aus bestehendem Pfad) |
| `genre-aliases` | `mapping/genre_aliases.yaml` | edit | none | M2 |
| `genre-overrides` | `mapping/genre_overrides.yaml` | edit | none | M2 |
| `genre-hierarchy` | `mapping/genre_hierarchy.yaml` | edit + Zyklus-Check | none | M2 |
| `genre-filters` | `mapping/genre_filters.yaml` | edit | none | M2 |
| `genre-rules` | `mapping/genre_rules.yaml` | edit + Regex-Validierung | none | M2 |
| `special-channel` | `mapping/special_channel.yaml` | edit | none | M2 |
| `artist-overrides` | `mapping/artist_overrides.json` | edit | **cross_process** | M3 |
| `case-preserve` | `mapping/case_preserve.yaml` | edit | **cross_process** | M3 (mit R3-Finding) |
| `known-artists` | `mapping/known_artists.yaml` | edit | **cross_process** | M3 (mit R3-Finding) |
| `auto-learned-genre` | `mapping/auto_learned_genre.json` | **read-only + Statistik** | — | M4 |
| `auto-learned-artist-aliases` | `mapping/auto_learned_artist_aliases.json` | **read-only** | — | M4 |
| `auto-learned-featured-artists` | `mapping/auto_learned_featured_artists.json` | **read-only** | — | M4 |

### 2.3 Validation Strategy

Pro Datei spezifischer Validator in `services/mapping_admin.py` (oder als Unterfunktionen):
- **Root-Typ-Check** (dict/list, je nach Datei)
- **Schlüssel-/Wert-Typen** (str, list[str], dict[str, str])
- **Leere/NULL-Werte** ablehnen
- **Duplikate** case-insensitiv
- **Hierarchie:** Zyklus-Check (DFS)
- **Rules:** Regex-Kompilierbarkeit
- **Genre-Referenzen:** Werte müssen in der `genre_hierarchy.yaml`-Top-Level-Menge liegen (oder Alias)
- **Channel/Artist-Referenzen:** keine Kreuz-Validierung nötig

**Regel:** Validator ruft bestehende Domain-Funktionen, wo vorhanden (z.B. `library_repair/genre.py::validate_genre_name`).

### 2.4 Persistence Strategy

- **Atomarer Write** (`tmp + Path.replace`) für alle Dateien.
- **Etag pro Datei** (SHA-256 der ersten 16 Zeichen, wie bestehender Pfad).
- **Cross-Process-Lock** für `lock_mode="cross_process"` über `utils/file_lock.py::cross_process_lock`.
- **Lock-Scope:** Load → Mutation → Validate → Backup → Replace → Unlock.
- **Backup:** siehe 2.7.

### 2.5 Reload Strategy

Drei ehrliche Zustände je Datei in der API-Antwort:
- **`bot_reload_required: true`** — heute der Standard für alle Dateien (Bot lädt beim Start).
- **`bot_reload_available: false`** — heute für alle Dateien (kein Caller für `reload()`/`reload_auto_learned()`).
- Optional später (nicht Teil dieses Auftrags): ein `/api/v1/admin/mappings/reload`-Endpunkt würde `GenreMapper.reload()` im Bot-Prozess triggern — braucht Cross-Process-Kanal (existiert heute nicht).

**Kein Fake-Reload, kein Fake-Success.**

### 2.6 UI Strategy

- Neue Seite `/admin/mappings` (Tabler, UI-Standard), Kategorien:
  - **Manual Config** (editierbar): je mapping_id eine Karte mit Anzahl Einträge, „Bearbeiten"-Link.
  - **Auto-Learned** (read-only): je Datei Statistik (Anzahl, letzte Änderung, Verteilung), keine Edit-Aktion.
- Strukturierte Formulare, **keine YAML-Textareas** für Standarddaten.
- Diff/Preview vor jedem Save (Vorbild `renderGenreMappingPreview`).
- Confirm bei destruktiven Änderungen, Toasts, Fehler-/Empty-/Loading-Zustände.

### 2.7 Backup Strategy

- **Bestehendes Backup-System prüfen:** `services/library_repair/executor.py` nutzt `.library_repair_backups/` (für Audio-Backups). Mapping-Backups wären analog denkbar.
- **Für M1/M2 nicht nötig** (Etag + Git-Historie reichen als Rückverfolgung).
- **Für M3 relevant** (Hybrid-Dateien, Bot-Auto-Learn): eigenes Backup wäre eine Erweiterung — als **eigenes FINDINGS** zu dokumentieren, nicht Teil dieses Auftrags.

### 2.8 Test Strategy

**Unit (`tests/test_mapping_admin_service.py`):**
- Laden / Validieren / Mutation
- Invalid Input (Typen, Duplikate, Zyklus, Regex-Fehler)
- Missing file / Corrupt YAML → 5xx mit klarem Code
- Etag-Konflikt → 409
- Cross-Process-Lock (nur für M3)

**API (`tests/test_control_center_mapping_admin_api.py`):**
- Unauth → 401/403
- Non-Admin → 403
- Same-Origin fehlt → 403
- Valid put / invalid put
- Unbekannte mapping_id → 404
- Path-Traversal-Versuch via mapping_id → 404 (nicht 500)

**Persistence:**
- Atomarer Write unter simuliertem Crash
- Concurrent writer (zwei Threads, gleicher Lock → keine Lost Update)

**UI (Node-Harness analog `test_control_center_artist_page.py`):**
- Liste / Edit / Preview / Confirm / Success / Validation-Error / Empty

---

## GO / NO-GO — Empfehlung

### GO — für M1 + M2

- Der bestehende `artist_genre.yaml`-Pfad ist **qualitativ hochwertig** (Etag, atomarer Write, ehrliche Semantik). Er beweist, dass das Konzept trägt.
- Die restlichen manuellen Dateien (`channel_genre`, `genre_aliases`, `genre_overrides`, `genre_hierarchy`, `genre_filters`, `genre_rules`, `special_channel`) haben **keinen Bot-Schreibpfad** — kein Cross-Process-Risiko.
- Die Validatoren sind pro Datei überschaubar (Root-Typ, Duplikate, Zyklus, Regex).
- Der Service ist eine **kleine Application-Layer** (~200–300 Zeilen), keine parallele Mapping-Engine.

**Reihenfolge:**
- **M1** = `channel-genre` (einfachste Struktur, proof-of-concept der generalisierten Architektur)
- **M2** = die 6 weiteren manuellen Dateien, je in kleinen PRs
- **M2.5** = Migration des bestehenden `artist-genre`-Pfads auf die neue Struktur (rein mechanisch, Etag-/Format-Vertrag bleibt)

### NO-GO — für M3 (Hybrid-Dateien) in diesem Auftrag

- `case_preserve.yaml` und `known_artists.yaml` werden **vom Bot geschrieben** (Real-Trigger in `ArtistNormalizer` und `AutoLearnManager`).
- Cross-Process-Race ist mit dem bestehenden Lock-Muster lösbar, aber es ist **neue Lock-Semantik** im Mapping-Pfad.
- R3 (Überschreibungs-Gefahr durch Auto-Learn + manuelle Pflege) braucht eine fachliche Entscheidung: Was passiert bei Konflikt? Read-only im CC? Reines Append? Der Auftrag sagt bei "STOPP. Erst Befund dokumentieren" — genau hier.
- **Empfehlung:** M3 als eigenes FINDINGS (P2), Bearbeitung in eigener Phase nach M1+M2.

### NO-GO — für M4 (Auto-Learned) mit Schreibzugriff

- Auto-Learned-Daten sind **Beobachtungsdaten**, nicht Konfiguration. Der Auftrag verbietet explizit, sie wie normale Config zu behandeln.
- Read-only-Statistik (Punkt 2.6) ist sinnvoll und kann in M2.5 als eigenes Panel ergänzt werden.
- Kein Reset/Revert in diesem Auftrag.

---

## Offene Entscheidungen (Nutzer-Freigabe nötig)

1. **M1-Kandidat:** Vorschlag `channel-genre`. Alternativ `genre-aliases` (flacher, mehr Einträge).
2. **Reihenfolge M1/M2/M2.5:** so wie oben oder anders?
3. **Backup für M2:** nur Git + Etag, oder eigene `.mapping_backups/`-Infrastruktur?
4. **FINDINGS-Erzeugung:** R1/R3 als neue Einträge in `docs/FINDINGS_INDEX.md` noch vor M1?

---

## M1-Status (2026-09-29)

**IMPLEMENTIERT** — Channel-Genre-Administration als Referenzimplementierung.

| Baustein | Datei |
|---|---|
| Application-Layer | `services/mapping_admin.py` (neu) |
| Domain-Rename | `services/library_repair/genre.py::validate_genre_name` (vormals `_validate_genre_name`, oeffentlich gemacht fuer Wiederverwendung) |
| Schemas | `control_center/schemas/mapping_admin.py` (neu) |
| Router | `control_center/routers/mapping_admin.py` (neu, `/api/v1/admin/mappings/{mapping_id}`) |
| App-Registrierung | `control_center/app.py` (1 Zeile) |
| Tests | `tests/test_mapping_admin_service.py` (18) + `tests/test_control_center_mapping_admin_api.py` (12) |

**Nicht in M1 enthalten** (bewusst):
- Keine UI (Phase 5)
- Kein zweites Mapping (M2)
- Keine Hybrid-Dateien wie `case_preserve.yaml` / `known_artists.yaml` (M3, braucht Cross-Process-Lock)
- Kein Auto-Learned-Write (M4)
- Kein Reload-IPC (`GenreMapper.reload()` bleibt ungenutzt)
- Kein Backup-System
- Keine Aenderungen an bestehender Mapping-Fachlogik oder Dateiformaten

**Naechster Schritt:** M2 — die naechste manuelle Mapping-Datei (`genre-aliases` als Vorschlag).
