# Artist Resolution — Phase A: Architecture Gate (2026-09-30)

Status: **STOP — Architekturentscheidung erforderlich.** Nur Analyse, kein Code, keine Mapping-Änderung.
Grundlage: Code auf `main` @ `1a39874`. Alle Aussagen mit Fundstelle; nicht Verifiziertes ist als solches markiert.

## 1. Kernbefund

Die Annahme des Master-Prompts ("`artist_overrides.json` ist ein manueller Genre-Override neben `artist_genre.yaml`") **trifft nicht zu**.
Im Bestand gibt es **zwei getrennte Fachdomänen**, die sich nie konkurrieren:

| Domäne | Frage | Quellen |
|---|---|---|
| **Identität / Name** | "Wie heißt dieser Artist kanonisch?" | `artist_overrides.json` > `known_artists.yaml` > `auto_learned_artist_aliases.json` > Library-Ordner > Parser |
| **Genre** | "Welches Genre hat dieser (bereits kanonische) Artist?" | `artist_genre.yaml` > `auto_learned_genre.json` (nur `LEARNED`) > Channel/Regeln/Hierarchie > MusicBrainz > Last.fm > Feature-Inferenz |

Fall A des Prompts (`artist_genre` Rock vs. `artist_overrides` Hip Hop) **kann nicht entstehen**: `artist_overrides.json` enthält nur `roher Name → kanonischer Name` (`mapping/artist_overrides.json`, 28 Einträge, alle String→String).

## 2. SOURCE/WRITER-MATRIX

| Quelle | Reader | Writer | Autorität | Derived? | Ladezeit / Reload | Lock | Atomic | UI |
|---|---|---|---|---|---|---|---|---|
| `artist_genre.yaml` | `GenreMapper._load_all_mappings` (`utils/genre_map.py:228`); Lesepfade in `services/library_repair/genre.py`, `auto_learn.py:1121` | (1) CC: `apply_manual_genre_mapping` → `save_manual_genre_mapping`; (2) Telegram: `handlers/library_maintenance_handler.py:1121`; (3) CLI: `scripts/library_repair.py:177` | **Genre, manuell, höchste** | nein | nur beim Start (Singleton). `reload()` existiert, wird in Produktion nirgends aufgerufen, hat bekannten Bug (`_find_mapping_dir("mapping")` hartcodiert, `genre_revalidation.py:102`) | CC: nur `threading.Lock` (`genre.py:242`); Telegram/CLI: **keiner** | ja (tmp + replace, fester tmp-Name, kein fsync) | Library → Artist → Genre-Mapping (ETag/409/Preview vorhanden) |
| `artist_overrides.json` | `ArtistNormalizer._load_overrides` (`utils/artist_map.py:967`), `ArtistIdentityResolver`, `filenamefixer`, `library_repair/artist.py`, EMP-Gate | **keiner im Code** (nur Handpflege; `artist_map` schreibt seit Phase C nicht mehr) | **Identität, manuell, höchste** | nein | beim Start (Normalizer) / `resolver.refresh()` | – | – | keine |
| `known_artists.yaml` | `ArtistIdentityResolver` Tier 2, `AutoLearnManager._is_artist_known` | nur `AutoLearnManager._write_known_artist_sync` (`auto_learn.py:751`) | **Identität, faktisch autoritativ (Tier 2, `known=True`)**, auch Handedits werden gelesen | ja (auto-erzeugt), wirkt aber als Entscheidungsquelle | Start + `refresh()` bei geänderten Quellen | nur `threading.Lock` im Bot-Prozess | ja | keine |
| `auto_learned_genre.json` | `GenreMapper` (Merge, nur nicht-`OBSERVED`, nur wenn Key nicht in `artist_map`), `auto_learn._read_genre_entry` | `AutoLearnManager._write_genre_observation_sync` (Bot); Revalidation-Subprozess über `learn_genre` | Genre, **gelernt** | ja | nur beim Start | nur `threading.Lock`; Subprozess **ohne** Cross-Process-Lock | ja | keine (CC nur Preview/Revalidate-Job) |

## 3. CURRENT RESOLUTION CHAIN

**Identität** (`artist_identity_resolver.py:resolve`): `artist_override` > `known_artist` > `auto_learned_alias` > `library_identity` > (`musicbrainz_mbid`: bewusst nicht implementiert) > `parser`.

**Genre** (`genre_processor.py`, `genre_map.py:determine_genre`): (1) `artist_map` exakt (lowercase-Key; enthält manuelle **und** gemergte `LEARNED`-Einträge) → (2) Spezialkanal/Channel/Fuzzy-Artist (Schwelle 85)/Regeln/Hierarchie → (3) MusicBrainz → (4) Last.fm → (5) Feature-Inferenz.

## 4. TARGET RESOLUTION CHAIN des Prompts vs. Bestand

| Prompt-Ziel | Bestand | Abweichung |
|---|---|---|
| 1 manuell `artist_genre.yaml` | identisch | keine |
| 2 Override `artist_overrides.json` | Namens-Identität, **vor** dem Genre-Schritt, kein Genre | **Fehlannahme** |
| 3 Auto-Learn / Candidate | `OBSERVED`(1) → `LEARNED`(≥2, wird beim nächsten Start **ohne User-Entscheidung** aktiv) → Lock-in ab 3 | Kein Candidate/Accept/Reject-Konzept |
| known_artists = derived | Datei ist auto-erzeugt, wirkt aber als Identitäts-Autorität | Hybrid (vgl. Plan-Risiko R3) |

## 5. CONFLICT MATRIX

| Fall | Ergebnis im Bestand |
|---|---|
| A: genre.yaml vs. overrides.json | nicht möglich (verschiedene Domänen) |
| B: genre.yaml Rock vs. Auto-Learn Pop | Auto-Learn **blockiert** (`BLOCKED_MANUAL`, `auto_learn.py:_compute_genre_decision`); Merge überspringt vorhandene Keys (`genre_map.py`, "manual hat immer Vorrang"). **Regel MANUAL > AUTO wird eingehalten.** |
| C: Kandidat akzeptieren | existiert nicht; Übernahme = automatisch ab `LEARNED` |
| D: Vorschlag ablehnen | existiert nicht (keine Reject-Liste) |
| E: manuelle Änderung → Auto-Learn-State | Eintrag in `auto_learned_genre.json` bleibt liegen, wird aber durch den manuellen Key überdeckt (kein Cleanup) |
| F: Artist gelöscht | keine Kaskade auf eine der drei Dateien |

## 6. AUTO-LEARN-FLOW (Genre)

Download → `GenreProcessor` liefert Ergebnis → `learn_genre()` → `_compute_genre_decision` (manuell? → blockiert) → Beobachtung in `observation_log` (max. N) → Mehrheitsvotum → `confidence` `OBSERVED`/`LEARNED` → atomarer JSON-Write → `clear_caches()` (kein Reload!) → aktiv erst nach Bot-Neustart und nur ab `LEARNED`. Identität: `learn_artist` nur Quelle `youtube_parsed`; `raw==canonical` → `known_artists.yaml`, sonst Alias-JSON.

## 7. Normalisierung

| Ebene | Regel |
|---|---|
| Genre-Lookup (`artist_map`) | `strip().lower()`, **kein** Unicode-/Akzent-Folding, exakter String; zusätzlich Fuzzy ≥ 85 (`artist_fuzzy`) |
| Identität (`_normalize_key`) | lower + NFKD + Combining-Marks entfernen (Bohse = Böhse) |
| Schreibpfad `_find_mapping_key` | `casefold` |

Zusammenführungsrisiko: der **Fuzzy-Match ≥ 85 auf `artist_map`** (inkl. gelernter Einträge) kann ähnlich geschriebene, verschiedene Artists auf dasselbe Genre abbilden. Absicherung: nur Schwelle, kein ID-Bezug. Nicht Teil dieser Phase geändert.

## 8. Findings (Vorschlag, noch nicht in `FINDINGS_INDEX` eingetragen)

| ID | Sev. | Befund | Fundstelle |
|---|---|---|---|
| AR-1 | **P1** | `artist_genre.yaml` wird von 3 Prozessen/Pfaden per Read-Modify-Write geschrieben; Telegram/CLI ohne jeden Lock, CC nur Thread-Lock → Lost Update möglich. `utils/file_lock.cross_process_lock` existiert und wird bereits von `mapping_admin`, `user_data`, `download_history` genutzt. | `services/library_repair/genre.py:242,150-225` |
| AR-2 | P2 | `GenreProcessor` labelt **gelernte** Einträge als `artist_exact_manual` und setzt `auto_learn_disabled=True`; Quelle "manuell" ist damit unehrlich. Erschwert jede spätere Anzeige "Resolution-Quelle". Tests pinnen das Label (`tests/test_genre_processor.py:233,525,596`). | `genre_processor.py:103-113` |
| AR-3 | P2 | `auto_learned_genre.json`: Bot-Thread-Lock + Revalidation-Subprozess ohne Cross-Process-Lock. | `auto_learn.py:_write_genre_observation_sync` |
| AR-4 | P2/DEFER | `known_artists.yaml` ist Hybrid (auto geschrieben, als Autorität gelesen). Entscheidung nötig, bevor Diagnose/Reset-UI sinnvoll ist. | `artist_identity_resolver.py:169` |
| AR-5 | P3 | `GenreMapper.reload()` nutzt hartcodiertes `"mapping"` und wird nirgends genutzt; Runtime-Reload-Semantik daher nur "Neustart". CC meldet das bereits ehrlich (`bot_reload_required`). | `utils/genre_map.py:1007` |
| AR-6 | DEFER | Candidate/Accept/Reject für Auto-Learn existiert nicht; `LEARNED` wird ohne User-Entscheidung aktiv. | s. §6 |

## 9. STOP-Regeln (Abschnitt 20 des Prompts)

| Regel | Getroffen? |
|---|---|
| 1 gleiche Autorität, Priorität unklar | Nein — aber Prämisse widerlegt (siehe §1) |
| 2 Auto-Learn überschreibt manuell | Nein (belegt) |
| 3 known_artists doch Autorität | **Ja** (Identität, Hybrid) |
| 4 mehrere Prozesse, kein sicherer Write Path | **Ja** für `artist_genre.yaml` (AR-1) und `auto_learned_genre.json` (AR-3) |
| 5 Normalisierung → falsche Merges | Teilweise (Fuzzy ≥ 85, AR im Genre-Lookup) |
| 6 Save meldet Erfolg ohne Runtime-Load | Nein, CC ehrlich |
| 7 UI dupliziert Library-Write-Path | noch nicht (nichts gebaut) |
| 12 Migration erforderlich | Nein |

## 10. Benötigte Architekturentscheidungen

1. **Zielmodell korrigieren:** Identität und Genre als zwei getrennte Ketten festschreiben; `artist_overrides.json` bekommt **keinen** Genre-Bezug. Phase C ("Artist Override UI") wäre eine Namens-/Alias-UI — anderes Risikoprofil (Umbenennung wirkt auf Dateinamen/Library).
2. **AR-1 zuerst:** `cross_process_lock` in `save_manual_genre_mapping` (kleinster Schritt; wirkt für CC, Telegram und CLI gleichzeitig, keine Verhaltensänderung).
3. **AR-2:** Quelle für gelernte Einträge ehrlich benennen (neues Label) — ändert gepinnte Tests, braucht Freigabe.
4. **Candidate/Accept/Reject (Phase D):** neues Feature, kein Bestandsschutz-Fall; erst nach Entscheidung, ob `LEARNED` weiterhin automatisch aktiv wird.
5. **known_artists (Phase E):** Hybrid-Status entscheiden (R3 im Mapping-Plan).
