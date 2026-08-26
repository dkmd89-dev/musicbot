# MusicBot — TESTENV-01: Test-Environment Isolation Leak

> Entdeckt vom Nutzer live während der META-11-Verifikation (Metadata
> Quality Phase, 2026-08-26) — beim erneuten Senden eines bereits via
> Testumgebung heruntergeladenen Links meldete der Test-Bot fälschlich
> „Duplikat erkannt", obwohl die Test-Library per `run_test_bot.py
> --clean` zuvor vollständig gelöscht worden war.

**Status: TESTENV-01 — ABGESCHLOSSEN (committed).**

---

## 1. Finding

**ID:** TESTENV-01 — P0 (Cache/Duplicate Detection, Datenintegrität) —
`config_test.py` isoliert die Testumgebung nur unvollständig von der
echten Produktion.

**Root Cause:** In `config.py::Config` sind viele Pfade als
`BASE_DIR / "..."` direkt im Klassenkörper der **Produktions**-Klasse
berechnet. Python wertet das **einmalig bei der Definition dieser
Klasse** aus — nicht dynamisch neu, wenn eine Subklasse `BASE_DIR`
überschreibt. `config_test.py::Config(ProdConfig)` überschrieb bisher nur
`BASE_DIR` selbst sowie eine Teilmenge der abgeleiteten Attribute
(`LIBRARY_DIR`, `PODCAST_DIR`, `DOWNLOAD_DIR`, `BACKUP_DIR`, `CACHE_DIR`,
`LOG_DIR`, `LOG_FILE`, `STATS_DIR`). Alle anderen BASE_DIR-abgeleiteten
Attribute blieben unverändert von der Produktions-Klasse geerbt und
zeigten dadurch trotz „isolierter" Testumgebung weiterhin auf echte
Produktionspfade unter `/mnt/128ssd/musicbot/`:

```
DUPLICATE_CACHE_DIR, METADATA_CACHE_DIR, LYRICS_CACHE_DIR, DATA_DIR,
ESCAPE_DIR, ARTIST_OVERRIDE_FILE, ARTIST_OVERRIDE_EXPANDED_FILE,
GENRE_MAPPING_DIR, PLAY_HISTORY_FILE, TEMP_DIR, PROCESSED_DIR,
FAIL_DIR, ARCHIVE_DIR
```

Die eingebaute Sicherheitsprüfung `_verify_isolation()` prüfte bisher
**nur** `LIBRARY_DIR` — gab also falsche Sicherheit, obwohl 13 weitere
kritische Pfade nicht isoliert waren.

**Live-Nachweis (real, nicht nur theoretisch):**

- Die echte Produktions-Duplicate-Cache
  (`/mnt/128ssd/musicbot/cache/duplicate_cache/{url,content}_duplicates.json`)
  wurde durch einen Test-Download tatsächlich verändert — ein Eintrag mit
  Pfad `/tmp/musicbot_test/library/...` landete darin. Ein späterer
  **echter** Download desselben Songs über den Produktions-Bot hätte
  dadurch fälschlich als Duplikat abgelehnt werden können.
- Die echten Mapping-Dateien `mapping/auto_learned_artists.yaml` und
  `mapping/auto_learned_genre.yaml` wurden durch Auto-Learning während des
  Test-Downloads geschrieben (da `GENRE_MAPPING_DIR` ebenfalls betroffen
  war) — inhaltlich zwar korrekt (siehe Commit `b48cef4`), aber ein nicht
  beabsichtigter Seiteneffekt einer „isolierten" Testaktion auf
  Produktionsdaten.

---

## 2. Vor-Fix-Charakterisierung

```
config_test.Config.DUPLICATE_CACHE_DIR  -> /mnt/128ssd/musicbot/cache/duplicate_cache
config_test.Config.METADATA_CACHE_DIR   -> /mnt/128ssd/musicbot/cache/metadata_cache
config_test.Config.LYRICS_CACHE_DIR     -> /mnt/128ssd/musicbot/cache/lyrics_cache
config_test.Config.ARTIST_OVERRIDE_FILE -> /mnt/128ssd/musicbot/mapping/artist_overrides.json
config_test.Config.TEMP_DIR             -> /mnt/128ssd/musicbot/import/temp
config_test.Config.PROCESSED_DIR        -> /mnt/128ssd/musicbot/import/prozess
config_test.Config.FAIL_DIR             -> /mnt/128ssd/musicbot/import/fail
config_test.Config.ARCHIVE_DIR          -> /mnt/128ssd/musicbot/import/archiv
config_test.Config.DATA_DIR             -> /mnt/128ssd/musicbot/cache/data
config_test.Config.ESCAPE_DIR           -> /mnt/128ssd/musicbot/cache/escaped_scripts
config_test.Config.ARTIST_OVERRIDE_EXPANDED_FILE -> /mnt/128ssd/musicbot/mapping/artist_overrides_expanded.json
config_test.Config.GENRE_MAPPING_DIR    -> /mnt/128ssd/musicbot/mapping
config_test.Config.PLAY_HISTORY_FILE    -> /mnt/128ssd/musicbot/history/user_histories
```

`tests/test_config_test_isolation.py` gegen den ungefixten Stand: **5
failed, 0 passed** — alle neuen Tests diskriminierend fehlgeschlagen
(kein bereits funktionierender Fall, da die Lücke systemisch war).

---

## 3. Fix

**`config_test.py`:**

1. Jedes betroffene BASE_DIR-abgeleitete Attribut einzeln explizit auf
   `Config.BASE_DIR` (`/tmp/musicbot_test`) umgeleitet.
2. **Mapping-Sonderfall:** `GENRE_MAPPING_DIR`/`ARTIST_OVERRIDE_FILE`/
   `ARTIST_OVERRIDE_EXPANDED_FILE` sollen im Test dieselben kuratierten
   Regeln wie Produktion **lesen** (sonst wäre Genre-/Artist-Normalisierung
   im Test bedeutungslos), aber **nicht** in dieselbe Datei **schreiben**
   (Auto-Learning/Case-Preserve). Neue Funktion
   `_prepare_isolated_mapping_dir()` kopiert die echte `mapping/`-
   Konfiguration einmalig (falls das isolierte Verzeichnis noch nicht
   existiert) nach `/tmp/musicbot_test/mapping/` — Schreibzugriffe landen
   danach ausschließlich in der isolierten Kopie. `run_test_bot.py
   --clean` löscht die Kopie mit; der nächste Start kopiert automatisch
   wieder frisch von der echten Quelle.
3. `_verify_isolation()` prüft jetzt eine explizite Liste aller
   isolationspflichtigen Attribute (`_ISOLATION_REQUIRED_ATTRS`, 18
   Einträge) statt nur `LIBRARY_DIR`, und meldet bei einem Leak alle
   betroffenen Attribute konkret statt nur das erste.

**Bewusst NICHT isoliert (dokumentierte Ausnahmen):**

- `COOKIES_FILE` — bleibt absichtlich geteilt (read-only, sonst
  funktioniert die yt-dlp-Authentifizierung im Test nicht).
- `BACKUP_BOT_SOURCE_DIR`/`BACKUP_LIBRARY_SOURCE_DIR`/`BACKUP_DEST_DIR` —
  `ENABLE_BACKUP=False` deaktiviert diesen Codepfad im Test bereits
  vollständig, kein demonstriertes Risiko.

**Neue Tests:** `tests/test_config_test_isolation.py` — 5 Tests: 4
prüfen, dass alle 16 isolationspflichtigen Attribute tatsächlich isoliert
sind (inkl. der beiden konkret betroffenen Kernfälle
`DUPLICATE_CACHE_DIR`/`GENRE_MAPPING_DIR`), 1 Regressionstest stellt
sicher, dass `_verify_isolation()` auch künftig nicht wieder auf eine
reine `LIBRARY_DIR`-Prüfung zurückfällt (simulierter Leak wird erkannt).

---

## 4. Testergebnisse

```
STUFE 1 (gezielt):
tests/test_config_test_isolation.py:        5 passed

STUFE 2 (direkte Regression):
tests/test_config_import_side_effects.py:   8 passed

STUFE 3 (thematisch, alle config-bezogenen Tests):
45 passed

STUFE 4 (vollständige Suite, am Ende der Arbeitsphase):
1250 passed, 1 warning (vorbestehend, unabhängig), 19 subtests passed
(Baseline vor diesem Fix: 1245 passed → +5 neue Tests, 0 Regressionen)
```

Zusätzlich manuell verifiziert: frischer Import nach vollständigem
`rm -rf /tmp/musicbot_test` kopiert die Mapping-Konfiguration korrekt neu
und alle geprüften Pfade zeigen auf `/tmp/musicbot_test/...`.

---

## 5. Produktions-Cache-Bereinigung

Mit expliziter Nutzerfreigabe wurde der eine, durch den Test-Download
entstandene Fremdeintrag aus der echten Produktions-Duplicate-Cache
entfernt:

- `/mnt/128ssd/musicbot/cache/duplicate_cache/url_duplicates.json`
- `/mnt/128ssd/musicbot/cache/duplicate_cache/content_duplicates.json`

Beide Dateien enthielten ausschließlich diesen einen Test-Eintrag
(Westernhagen, Pfad `/tmp/musicbot_test/...`) und wurden auf `{}`
zurückgesetzt. `cache/` ist git-ignoriert, diese Änderung ist daher nicht
Teil des Commits — rein eine Laufzeit-Datenbereinigung.

Die auto-gelernten Mapping-Einträge (`mapping/auto_learned_artists.yaml`,
`mapping/auto_learned_genre.yaml`, Commit `b48cef4`) wurden **nicht**
zurückgenommen — inhaltlich korrekt und wertvoll (entsprechen exakt dem,
was ein echter Produktions-Download ebenfalls gelernt hätte).

---

## 6. Abschluss

TESTENV-01 gilt hiermit als **abgeschlossen**. Root Cause vollständig
identifiziert und live durch tatsächliche Produktions-Cache-Kontamination
bestätigt, Fix umfassend (alle 16 betroffenen Pfade plus verstärkte
Sicherheitsprüfung plus Mapping-Kopiermechanismus), vollständige Suite
grün (1250 passed, 0 failed, 0 errors). Betroffene Produktions-Cache-
Dateien bereinigt. Dieser Fund entstand direkt aus dem vom Nutzer
vorgeschlagenen Test-Download (siehe META-11) — ein zweiter, unabhängiger
Beleg für den Wert dieser Vorgehensweise. Commit/Push/PR/Merge auf
explizite Nutzerfreigabe hin durchgeführt (siehe Git-Historie).
