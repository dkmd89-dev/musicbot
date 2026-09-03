# Main-Codebase Health Check — 2026-09-03

Read-only-Ausgangspunkt: nach Abschluss der Downloader-Fehlertaxonomie-
Charakterisierung (`docs/FINDINGS_INDEX.md`, PR #129) waren keine
bekannten offenen Bugs mehr priorisierbar. Nutzer-Initiative: statt
weiterer Bugfixes ein systematischer Check, ob `main/` inzwischen
tatsächlich aufgeräumt/konsistent ist — verwaiste Dateien, ungenutzte
Scripts, leere Verzeichnisse, alte Migration-/Report-Dateien, ungenutzte
Handler/Adapter, tote APIs, historische Artefakte. Anders als bisherige
Findings: keine Suche nach einem bekannten Bug, sondern nach übrig
gebliebenem Code/Strukturen, die der Bot nicht mehr benötigt.

Methodik pro Kategorie unterschiedlich (bewusst, siehe CLAUDE.md
Abschnitt 20 — "leer" oder "ungenutzt sichtbar" ist kein Beweis für
"tot"): Modul-Referenzen per `grep` gegen den gesamten Baum (Produktion
+ Tests), `git log` für tatsächliche Aktivität, Doku-Cross-Reference
gegen `docs/INDEX.md`/`README.md`/`CLAUDE.md`, Verzeichnis-Referenzen
gegen `config.py`. Reihenfolge nach Nutzer-Priorisierung: erst eine
Kategorie vollständig, dann die nächste — kein breiter grober Scan mit
vielen unverifizierten False Positives.

## Baseline

| Feld | Wert |
|---|---|
| Ausgangspunkt | `main` nach PR #129 (Downloader-Fehlertaxonomie-Closure) |

## Ergebnis nach Kategorie

| Kategorie | Methode | Ergebnis |
|---|---|---|
| Ungenutzte Handler/Adapter/tote APIs | `grep` auf alle 17 Module in `handlers/` + `services/clients/` gegen Produktion+Tests, `git log` | **Sauber, kein Fund.** Alle 17 Module aktiv referenziert. Auffälligster Verdachtsfall `handlers/test_menu_handler.py` (Name klingt wie Test-Leftover) — tatsächlich legitimes, aktiv verdrahtetes Feature (Unit-Tests/Coverage über Telegram-Menü, instanziiert in `rich_menu_handler.py:190`). |
| Verwaiste Dateien / alte Migration-/Report-Dokumente | Root-Level-Scan auf `*.bak`/`*.old`/`*report*`/`*audit*`, `docs/`-Top-Level gegen `docs/INDEX.md`/`README.md`/`CLAUDE.md` cross-referenziert | **2 Doku-Lücken, kein totes Cleanup-Ziel.** `helfer/markdown_helfer.py` (genutzt von 3 Handlern) fehlte im Schichtmodell (CLAUDE.md Abschnitt 4). `docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md` (964 Zeilen, aktiv referenziert von `services/duplicate/resolution.py`/`classification.py`/`scripts/resolve_duplicates.py` + 5 Tests) war in keinem Index verlinkt. Beide nachgetragen. |
| Ungenutzte Scripts | `ls scripts/` + Cross-Check | **Sauber.** Nur 3 Dateien (`reprocess_artist_metadata.py`, `resolve_duplicates.py`, `normalize_test_library_loudness.py`), alle aktueller Bestand. |
| Leere Verzeichnisse / Cache-/Runtime-Struktur | 10 leere Verzeichnisse gefunden, jedes gegen `config.py`- und Code-Referenzen geprüft | **4 verwaist, 6 aktiv.** `import/prozess`/`import/temp`/`import/fail`/`import/archiv`/`cache/escaped_scripts`/`cache/data` sind aktive, per `config.py` referenzierte Laufzeit-Verzeichnisse (korrekt leer, da aktuell nichts durchläuft). `import/backup` (config-seitiges `BACKUP_DEST_DIR` zeigt auf einen anderen Pfad außerhalb des Repos), `import/spotify`, `data/artist_images`, `cache/audio_enhancer_cache` waren im gesamten Code unreferenziert — alle vier zusätzlich nicht versioniert (`.gitignore`), Entfernen war eine reine Dateisystem-Aktion, kein Commit. |
| Historische Artefakte | Stichprobe `docs/archive/` (77 Dateien) | Bereits sauber organisiert — bewusst benanntes Archiv, kein Cleanup-Bedarf. Kein vertiefter Einzel-Scan (Umfang mit Nutzer abgestimmt zurückgestellt, siehe Out of Scope). |

---

## Änderungen

- **PR #130** (`docs/health-check-index-gaps`, gemergt) — `CLAUDE.md`,
  `docs/INDEX.md`: `helfer/` im Schichtmodell ergänzt,
  `MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md` im Index verlinkt.
  Reine Dokumentationsänderung, keine Code-/Teständerung.
- Vier leere, unreferenzierte, nicht versionierte Verzeichnisse lokal
  entfernt (kein Git-Vorgang, da nie getrackt): `import/backup`,
  `import/spotify`, `data/artist_images`, `cache/audio_enhancer_cache`.

---

## Tests

Keine Codeänderung in dieser Phase — kein Testlauf nötig/durchgeführt.

---

## Out of Scope

Bewusst nicht vertieft in dieser Phase:

- **Funktions-/Methoden-Ebene innerhalb der 17 genutzten Handler/
  Adapter-Module** (einzelne tote Callback-Handler statt ganzer
  Module) — deutlich teurer und fehleranfälliger als ein
  Modul-Ebenen-Check: Telegram-Bots dispatchen viel über
  `callback_data`-Strings/`getattr()`, was simples `grep` mit
  False Positives bestraft. Eigene, separat zu entscheidende Stufe.
- **Tiefer Einzel-Scan von `docs/archive/`** (77 Dateien) auf
  tatsächlich noch zitierte vs. komplett verwaiste historische
  Dokumente — Stichprobe zeigte kein akutes Problem, vollständige
  Durchsicht wäre ein eigener, größerer Aufwand ohne bisher belegten
  Bedarf.

---

## Remaining Technical Debt

Keine neuen offenen P0-/P1-Findings aus diesem Health Check. Bereits
bestehende, unabhängige offene Punkte (`docs/FINDINGS_INDEX.md`)
bleiben unverändert: INV-01 (`duplicate/cache.py`, DEFER/P2),
Download-Verlauf-Feature, Hard-Cancel-FFmpeg (akzeptiert).

**Gesamtfazit:** `main/` war zum Zeitpunkt dieses Checks bereits
überwiegend sauber — die Funde waren klein (zwei Doku-Verweise, vier
leere Platzhalter-Verzeichnisse), kein größerer Cleanup-Bedarf über die
hier dokumentierten Kategorien hinaus.
