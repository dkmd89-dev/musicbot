# MusicBot Engineering Baseline v5

> Nächster verifizierter Engineering-Referenzzustand nach einem strikt
> read-only Post-Baseline-v4 Health & Risk Audit
> (`docs/archive/MusicBot_POST_BASELINE_v4_HEALTH_RISK_AUDIT.md`) und der
> anschließend freigegebenen, eng umrissenen Behebung der dabei gefundenen
> drei P1-Findings. `docs/archive/MusicBot_ENGINEERING_BASELINE_v4.md` bleibt als
> eingefrorene, historische Referenz unverändert bestehen.

---

## 1. Baseline Metadata

| Feld | Wert |
|---|---|
| Datum | 2026-08-26 |
| Vorherige Baseline | `docs/archive/MusicBot_ENGINEERING_BASELINE_v4.md` (1107 passed / 0 failed, eingefroren) |
| Herleitung | `docs/archive/MusicBot_POST_BASELINE_v4_HEALTH_RISK_AUDIT.md` (Findings 1–3) |
| Test-Kommando | `python3 -m pytest tests/ -q` |
| Testergebnis | **1123 passed, 0 failed**, 19 subtests passed, 1 Warning (bekannte, harmlose Pytest-Collection-Warning aus v3/v4, unverändert) |
| Python-Version | 3.12.3 |

---

## 2. Executive Summary

Der Post-Baseline-v4-Audit fand keine Regression gegenüber v4 (1107/0 exakt
reproduziert, AE-10/11/12 direkt im Code re-verifiziert, unverändert intakt),
aber drei neue, konkret belegte P1-Findings außerhalb des von AE-10/11/12
abgedeckten Scopes — alle in P0-Bereichen (Duplicate Detection, Security):

1. **Finding 1**: `DuplicateDetector.check_for_duplicates()` wurde produktiv
   nur mit `url=` aufgerufen — die Content-/Parser-/Library-Fallback-Ebenen
   waren im echten Pre-Download-Pfad toter Code (z. B. dieselbe Aufnahme
   unter anderer Video-ID erneut hochgeladen, wurde vor dem Download nicht
   erkannt).
2. **Finding 2**: `move_to_library()` gab bei einer Zieldateinamens-Kollision
   nur den (umbenannten) `Path` zurück, kein Signal — der dafür bereits
   vorhandene Cleanup in `klassen/download_handler.py`
   (`renamed_due_to_conflict`) war seit jeher toter Code.
3. **Finding 3**: der Fanart.tv-API-Key konnte bei `LOG_LEVEL=DEBUG` über
   `str(requests.RequestException)` im Klartext geloggt werden
   (`services/metadata/cover_processor.py`), analog zu einem bereits in
   `services/clients/navidrome_api.py` behobenen Bug.

Alle drei wurden mit dem kleinsten sinnvollen Fix behoben, jeweils mit
dediziertem(n) Regressionstest(s), die gegen den Vor-Fix-Stand per
`git stash` als fehlschlagend verifiziert wurden. Zusätzlich wurde eine
reine Dokumentations-Ungenauigkeit korrigiert (siehe Abschnitt 4).

---

## 3. Geschlossene Findings (seit v4)

| Finding | Bereich | Kernaussage |
|---|---|---|
| Finding 1 `check_for_duplicates()` | Duplicate Detection | Leichtgewichtiger yt-dlp-Vorab-Abruf (`extract_info(download=False)`) vor dem Duplikat-Check ermittelt jetzt Artist/Titel und aktiviert Content-/Parser-/Library-Fallback-Ebenen. Playlist-URLs und fehlgeschlagene Abrufe fallen sauber auf die bisherige URL-only-Prüfung zurück (kein Blocker). Bewusste Kosten/Nutzen-Entscheidung: ein zusätzlicher Netzwerk-Roundtrip pro Download-Versuch. |
| Finding 2 `renamed_due_to_conflict` | Duplicate Detection / Library | `move_to_library()` gibt jetzt `(Path, bool)` zurück; das Kollisions-Signal fließt über `MetadataResult` und die Übersetzungsschicht (`metadata_result_translator.py`, `DownloadResult`) bis zum bereits vorhandenen, jetzt erstmals wirksamen Cleanup in `download_handler.py`. |
| Finding 3 `cover_processor.py` Secret-Leak | Security | `_scrub_credentials()` (analog `navidrome_api.py`) entfernt den `api_key`-Query-Parameter aus dem Exception-String, bevor er geloggt wird. |
| Dokumentation `enhanced_error_handler.py` | Dokumentation | Baseline v3/v4 bezeichnete den Handler fälschlich als „PLANNED / NOT INTEGRATED" — tatsächlich seit dem Initial-Commit vollständig integriert (`bot.py` registriert ihn als globalen Telegram-Error-Handler). Reine Korrektur, kein Codefehler. |

Details je Fund: `docs/archive/MusicBot_POST_BASELINE_v4_HEALTH_RISK_AUDIT.md`.

---

## 4. Dokumentations-Korrektur: `enhanced_error_handler.py`

Bisherige Einträge in v3/v4 („PLANNED / NOT INTEGRATED, unverändert") waren
sachlich falsch und werden hiermit zurückgezogen. Tatsächlicher Stand,
direkt im Code verifiziert: `bot.py` erstellt den Handler in `initialize()`
und registriert ihn via `self.application.add_error_handler(self.error_handler.handle_telegram_error)`;
`handlers/menu/rich_menu_handler.py` nutzt ihn aktiv für Callback-/
Command-Fehlerbehandlung. Ursprung dieser Integration: Initial-Commit
(`f000cc0`, 2026-08-16) — kein neues Verhalten dieser Runde, nur eine
längst überfällige Dokumentationskorrektur.

---

## 5. Bewusst akzeptierte Risiken / Entscheidungen (unverändert seit v4)

Alle in Baseline v4 Abschnitt 4/8 gelisteten Punkte (`duplicate/cache.py`
INV-01, `move_to_library()` TOCTOU, `tag_writer.py` fsync-Kommentar,
`handlers/test_menu_handler.py` Admin-only-INV-01) bleiben unverändert
bestehen — durch diesen Audit nicht berührt, keine neue Evidenz.

Neu als DEFERRED aufgenommen (P2/P3, siehe Audit-Dokument Abschnitt 5):

- Verwaiste Teildatei bei Task-Cancellation in `download_executor.py::download_single_track()` (P2, chiefly Shutdown-Szenario).
- `services/statistik/statistics_calculator.py::export_stats_to_json()` — nicht-atomarer Write (P3, One-Shot-Artefakt).
- Undokumentierter Loudness-Normalisierungs-Schritt in der Metadata-Pipeline + Debug-Log-Rauschen auf INFO-Level (P3).
- `pylast.LastFMNetwork.__repr__()` würde Secrets einbetten, aktuell nirgends geloggt (P3, latent).

---

## 6. Aktueller Architekturzustand

Unverändert gegenüber v4 in Bezug auf Layer-Grenzen und Orchestrierungsfluss.
Neu (Finding 1): `klassen/download_handler.py::handle_url()` macht vor dem
eigentlichen Download jetzt einen zusätzlichen, eigenständigen
`extract_info(download=False)`-Aufruf (`_probe_artist_title_for_duplicate_check()`)
ausschließlich für den Duplikat-Check — unabhängig vom später folgenden
echten Download-Aufruf, keine strukturelle Änderung der Pipeline-Reihenfolge.

```text
Telegram → ExtendedBot → RichMenuHandler → DownloadHandler
    → handle_url() → _check_duplicates_before_download()
        → _probe_artist_title_for_duplicate_check() (NEU, Finding 1)
        → DuplicateDetector.check_for_duplicates(url, raw_artist, raw_title)
    → download_utils.py (Pipeline-Orchestrator)
    → EnhancedMetadataProcessor.process_single_track()
        → move_to_library() → (Path, renamed_due_to_conflict) (Finding 2)
        → Tags (Copy+Tag+Replace + asyncio.to_thread, AE-11+AE-12, unverändert)
    → Navidrome
```

---

## 7. Aktuelle Security-Baseline

Finding 3 geschlossen (`cover_processor.py`, Credential-Scrubbing analog
`navidrome_api.py`). Sonst unverändert gegenüber v4.

---

## 8. Aktuelle Technical Debt

| ID | Problem | Status | Priorität |
|---|---|---|---|
| ENHANCED-ERROR-HANDLER | Doku-Fehler korrigiert (siehe Abschnitt 4) | CLOSED (Dokumentation) | — |
| `move_to_library()` TOCTOU | Same-File-Kollisionsfenster | DEFER, unverändert seit v4 | P2 |
| `tag_writer.py` fsync-Kommentar | Veraltete Begründung im Code-Kommentar | DEFER, unverändert seit v4 | P3 |
| `duplicate/cache.py` INV-01 | Bewusst nicht async | DEFER, unverändert seit v4 | P2 |
| `handlers/test_menu_handler.py` | INV-01, bis 900s, admin-only | DEFER, unverändert seit v4 | P2 |
| `download_executor.py::download_single_track()` Cancellation-Cleanup | Verwaiste Teildatei bei Task-Cancellation | DEFER (neu, siehe Abschnitt 5) | P2 |
| `statistics_calculator.py::export_stats_to_json()` | Nicht-atomarer Write | DEFER (neu, siehe Abschnitt 5) | P3 |
| Loudness-Schritt undokumentiert + Debug-Log-Rauschen | Kosmetisch | DEFER (neu, siehe Abschnitt 5) | P3 |
| `pylast.LastFMNetwork.__repr__()` | Latentes Secret-Leak-Risiko | DEFER (neu, siehe Abschnitt 5) | P3 |
| `.info.json`-Reste in `import/downloads/` u. Ä. | (siehe v3/v4) | unverändert | P2/P3 |

---

## 9. Neue offene Risiken

Keine. Jeder Fix wurde einzeln mit Pre-Fix-Diskriminierung (`git stash`)
gegen den Vor-Fix-Stand als fehlschlagend verifiziert; die volle Testsuite
lief nach jedem Fix und am Ende erneut grün.

---

## 10. Regressionsergebnis

```text
python3 -m pytest tests/ -q
1123 passed, 1 warning, 19 subtests passed in 88.51s
```

**Neue Tests dieser Runde:**

| Finding | Testdatei(en) | Anzahl |
|---|---|---|
| Finding 3 (Security) | `test_cover_processor_credential_scrubbing.py` | 6 |
| Finding 1 (Duplicate) | `test_download_handler_duplicate_check_artist_title_probe.py` | 7 |
| Finding 2 (Duplicate) | `test_download_utils_metadata_translation.py` (3 neue Tests: 2 Playlist-Pfad, 1 Single-Pfad) + 1 erweiterte Assertion in `test_filenamefixer.py` (kein Test-Zuwachs) | 3 |
| **Summe** | | **16** |

1107 (v4) + 16 = 1123 — exakt reproduziert, keine unerklärte Differenz.

Kein einziger Regressionsschritt hat einen vorher bestandenen Test zum
Fehlschlagen gebracht.

---

## 11. Definition of Baseline

> Dieses Dokument repräsentiert den nächsten verifizierten
> Engineering-Referenzzustand von MusicBot nach dem Post-Baseline-v4
> Health & Risk Audit und der Behebung der dabei gefundenen drei
> P1-Findings sowie einer Dokumentationskorrektur.

Bei Widersprüchen zwischen diesem Dokument und älteren Dokumenten gilt
weiterhin: aktueller Code > tatsächlich ausgeführte Tests > aktuelle
technische Dokumentation > historische Dokumentation.
`docs/archive/MusicBot_ENGINEERING_BASELINE_v4.md` bleibt als eingefrorene,
historische Referenz (1107/0) unverändert bestehen und wird durch dieses
Dokument **abgelöst**, nicht ersetzt, als aktueller Referenzpunkt.
`docs/archive/MusicBot_POST_BASELINE_v4_HEALTH_RISK_AUDIT.md` bleibt als
Analyseartefakt/Herleitung dieser Baseline unverändert bestehen.

---

## 12. Architecture Freeze

```
🟢 ARCHITECTURE FREEZE — APPROVED (unverändert)
```

Der Post-Baseline-v4-Audit hat den bestehenden Freeze (Baseline v4,
`docs/archive/MusicBot_FINAL_ARCHITECTURE_CLOSURE.md`) nicht neu geöffnet — die
drei gefundenen P1-Findings waren eng umrissene, unabhängige Ein-Datei-Fixes
nach bereits im Repo etablierten Mustern (`run_in_executor`,
`_scrub_credentials`, explizite Parameter-Durchreichung), keiner davon
katastrophal (kein Crash, keine Korruption, kein Datenverlust, kein
Lockout). Der Freeze bleibt APPROVED.

---

## Baseline Frozen (2026-08-26)

Analog zur Closure von v3/v4: dieses Dokument ist mit Erstellung bereits
vollständig (drei P1-Fixes + Dokumentationskorrektur abgeschlossen,
1123 passed / 0 failed) und wird ab sofort **eingefroren**.

**Diese Datei ist damit abgeschlossen.** Neue Findings, Nachträge oder
technische Schulden gehören ab jetzt in eine neue Datei
`MusicBot_ENGINEERING_BASELINE_v6.md`, nicht mehr hierher.
