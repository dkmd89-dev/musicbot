# MusicBot — Download Pipeline Stability Phase — PHASE 2G/2H: DL-06

> Fix-, Review- und Abschluss-Dokumentation für DL-06. Basis:
> `docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2D_DL01_AUDIT.md`
> (PHASE-2F-Audit, dort erstmals als neues Finding identifiziert),
> aufbauend auf Commit `b7857e7` (DL-02, DUP-01/DUP-08, DUP-02).
> Dieses Dokument wird von einem Code-Kommentar in
> `services/downloader/download/download_executor.py` referenziert und
> ist damit die maßgebliche Statusquelle für DL-06.

**Status: DL-06 — TECHNISCH FREIGEGEBEN / ABGESCHLOSSEN**

---

## 1. Finding (aus PHASE 2F)

**ID:** DL-06 — P1 — Playlist-Track-Download ohne Cleanup bei
yt-dlp-/FFmpeg-internem Fehler.

**Datei/Funktion:** `services/downloader/download/download_executor.py::DownloadExecutor.download_single_track()`.

**Root Cause:** Strukturell identisch zu DL-02 (bereits für
`_process_single_download()` in `download_utils.py` behoben): schlägt
`yt_dlp.YoutubeDL(...).extract_info(url, download=True)` intern fehl (z. B.
FFmpeg-Postprocessing), wird `download_info` nie zugewiesen;
`find_downloaded_file()` kann die Rohdatei ohne dieses Dict nicht
lokalisieren. DL-02s Fix (progress_hooks-basierte Pfaderfassung) wurde nie
auf diesen zweiten, unabhängigen yt-dlp-Aufrufpfad übertragen — es gab
keinen einzigen Cleanup-Aufruf in `download_single_track()`.

---

## 2. Fix (PHASE 2G)

Identisches Prinzip wie DL-02, mit einer bewussten Anpassung: da
`download_single_track()` (anders als `_process_single_download()`) eine
echte Retry-Schleife besitzt, werden `raw_downloaded_path`, der
`_capture_raw_downloaded_path`-Hook und `hooked_track_ydl_opts` **innerhalb**
der `for attempt in range(...)`-Schleife neu gebunden — pro Versuch isoliert,
damit ein Cleanup nie den Pfad eines früheren Versuchs trifft.

- Import ergänzt: `cleanup_single_download_artifact`.
- `progress_hooks` additiv registriert (`track_ydl_opts` selbst unmutiert,
  neues `hooked_track_ydl_opts`-Dict per Spread).
- Cleanup ausschließlich im bestehenden `except Exception as e:`-Block, kein
  `finally`, keine Cancellation-Ausweitung (kein
  `except asyncio.CancelledError`, kein `asyncio.shield()`).
- `cleanup_single_download_artifact()` selbst unverändert wiederverwendet.

**Geänderte Datei:** ausschließlich
`services/downloader/download/download_executor.py` (33 Zeilen, nur
Additionen).

**Neue Tests:**
`tests/test_download_executor_playlist_track_cleanup.py` — 7 Tests:
Cleanup nach Fehler, kein Cleanup ohne Hook, Erfolgsregression, unbeteiligtes
Artefakt geschützt, Retry-Isolation (2 Tests), echte parallele Downloads.

---

## 3. Review (PHASE 2H)

Vollständiger, unabhängiger Review durchgeführt (Diff-Review anhand aller 15
Prüfpunkte, Retry-Semantik direkt am Code nachvollzogen, Parallelitäts-
Isolation bestätigt, yt-dlp-Datenfluss unabhängig gegen den installierten
Quellcode neu verifiziert statt aus PHASE 2C/2G übernommen, alle 7 Tests
einzeln bewertet, Vor-Fix-Verifikation unabhängig reproduziert).

**Ergebnis:** DL-06 TECHNISCH FREIGEGEBEN.

**Vor-Fix-Verifikation (zweifach reproduziert, PHASE 2G und PHASE 2H):**
```
git stash push -- services/downloader/download/download_executor.py
python3 -m pytest tests/test_download_executor_playlist_track_cleanup.py -v
→ 5 failed, 2 passed
```
Fehlgeschlagen (diskriminierend): Cleanup-nach-Fehler, unbeteiligtes
Artefakt, beide Retry-Isolation-Tests, Parallelität. Bereits vorher grün
(Sicherheits-/Nicht-Regressions-Guards): „kein Hook → kein Cleanup",
Erfolgsregression.

**Vollständige Testsuite (PHASE 2H):**
```
1157 passed, 1 warning, 19 subtests passed in 65.40s (0:01:05)
```
0 failed, 0 errors. Bekannte `PytestCollectionWarning` unverändert.

**Verbleibende, nicht blockierende Beobachtungen (P3, dokumentiert statt
ungefragt behoben):**
- Testlücke: kein expliziter Test für „Versuch 1 feuert Hook + wird
  bereinigt, Versuch 2 feuert seinen Hook NICHT (Fehler vor
  Rohdownload-Ende)". Durch direkte Code-Analyse (Pro-Iteration-Neubindung)
  bereits als strukturell korrekt bestätigt; im Fehlerfall ohnehin durch
  `cleanup_single_download_artifact()`s eigenen `.exists()`-Guard
  abgesichert.
- Totes Testcode-Fragment: `class _InjectingExecutor(DownloadExecutor): pass`
  in `install_fake_ydl()` (Testdatei), ungenutzt, keine funktionale
  Auswirkung.

---

## 4. Produktions-End-to-End-Bestätigung (PHASE 2H, Abschluss)

Nach dem technischen Review wurde ein realer Produktions-Download über den
laufenden Bot durchgeführt (Telegram → DownloadHandler → Duplikatprüfung →
yt-dlp → Postprocessing → EnhancedMetadataProcessor → MusicBrainz → Lyrics →
Cover → Loudness → `move_to_library()` → TagWriter → DuplicateCache →
Telegram-Erfolgsmeldung).

**Beispiel:** Nina Chuba – RAGE GIRL →
`/mnt/4tb/library/Nina Chuba/Singles/2025 - RAGE GIRL.m4a`

**Ergebnis:** Download, Postprocessing, Metadaten, Cover, Lyrics, Loudness,
Library-Move, Tagging und Telegram-Erfolgsmeldung liefen ohne Exception und
ohne sichtbare Regression durch.

**Hinweis zur separaten Testumgebung (Stand PHASE 2H):** Der Downloadlauf
konnte dort zu diesem Zeitpunkt noch nicht reproduziert werden. Das wurde
hier ausdrücklich **nicht** als DL-06-Fehler gewertet, da (a) der reale
Produktionspfad erfolgreich funktioniert hat und (b) alle
DL-06-Regressionstests vollständig grün waren (Abschnitt 3). Die Ursache
der fehlenden Reproduzierbarkeit war zu diesem Zeitpunkt explizit nicht
Teil dieser Phase — siehe Abschnitt 5 für die inzwischen erfolgte
Aufklärung und Bestätigung.

---

## 5. Test-Umgebungs-Bestätigung (PHASE 2I, Nachtrag)

Die in Abschnitt 4 offen gelassene fehlende Reproduzierbarkeit in der
separaten Testumgebung wurde in PHASE 2I aufgeklärt: **kein Code-Bug**,
sondern die Testumgebung lief unter einem eigenständigen Telegram-Bot-
Account (`@dkmd_test_bot`, eigener `TEST_TELEGRAM_TOKEN` in `.env`,
getrennt vom Produktions-`BOT_TOKEN`) — Testnachrichten waren zunächst an
den falschen (Produktions-)Bot gesendet worden. Details siehe
`docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2I_TEST_ENVIRONMENT.md`.

Nach der Korrektur wurde DL-06 zusätzlich **live in der Testumgebung über
den echten Playlist-Pfad bestätigt**: ein 5-Track-Playlist-Download über
`@dkmd_test_bot` lief vollständig durch (5/5 Tracks erfolgreich,
`download_single_track()` real durchlaufen, korrekte Einzel-Registrierung
im DuplicateCache). Da dieser Testlauf ein vollständiger Erfolgsfall war,
wurde der DL-06-Cleanup-Pfad dabei nicht ausgelöst — das ist erwartet und
kein Freigabehindernis, da dieser Pfad bereits vollständig durch die 7
dedizierten Regressionstests (Abschnitt 3) abgesichert ist, inklusive
Vor-Fix-Diskriminierung.

---

## 6. Scope-Bestätigung

Einzige Produktions-Codeänderung für DL-06: `download_executor.py`. Keine
Änderung an `download_utils.py`, `download_artifact_cleanup.py`,
`enhanced_metadata_processor.py` (DL-01, separat, unverändert),
`klassen/download_handler.py`, `services/duplicate/*`. DL-07 und DL-08
bewusst nicht bearbeitet (bleiben offene, separat vorgemerkte Findings, s.
PHASE-2F-Audit).

---

## 7. Abschluss

DL-06 gilt hiermit als **technisch freigegeben und abgeschlossen — inkl.
realer Bestätigung des Erfolgspfads in Produktion UND Testumgebung**. Der
Gesamtstatus der übergeordneten
`docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md` bleibt **PLANNED**, da
DL-08 (P2) sowie die aus PHASE 0/1 verbliebenen Punkte (u. a. DUP-03,
DUP-05) weiterhin offen sind — dieses Dokument bestätigt ausschließlich den
Abschluss von DL-06.
