# MusicBot — Download Pipeline Stability Phase — PHASE 2K: DL-08

> Analyse-, Fix- und Abschluss-Dokumentation für DL-08. Ursprünglich in
> PHASE 2F identifiziert (Audit-Dokument nicht als Datei im Repository
> erhalten — siehe Abschnitt 5), erstmals hier vollständig mit eigener
> Read-Only-Analyse und Controlled Fix dokumentiert.

**Status: DL-08 — TECHNISCH ABGESCHLOSSEN (uncommitted)**

---

## 1. Finding

**ID:** DL-08 — P2 — Playlist-Cancellation — Verlust bereits erfolgreicher
Playlist-Ergebnisse.

**Datei/Funktion:**
`services/downloader/download_utils.py::_process_playlist_download()`.

**Root Cause:** Die Track-Schleife sammelte Ergebnisse in einer rein
lokalen `results`-Liste, zurückgegeben erst am regulären Funktionsende
(`return results`). Die Schleife fing nur `except Exception`, nicht
`asyncio.CancelledError` (erbt seit Python 3.8 von `BaseException`). Trat
eine Cancellation während eines späteren Tracks auf, verließ die Funktion
sofort die Schleife, ohne `return results` zu erreichen — bereits
erfolgreiche Tracks gingen verloren und erreichten
`klassen/download_handler.py::_register_playlist_track_duplicates()` nie
mehr, obwohl sie real bereits in der Library lagen (Library-Datei
vorhanden, aber kein DuplicateCache-Eintrag — Inkonsistenzrisiko bei
späterem erneuten Download desselben Tracks).

---

## 2. Fachliche Entscheidung (explizit freigegeben)

Bereits erfolgreich abgeschlossene Tracks müssen trotz Playlist-Abbruch
weiterhin für den DuplicateCache registriert werden. Fehlgeschlagene und
der aktuell abgebrochene Track werden nicht registriert. `CancelledError`
wird in jedem Fall vollständig propagiert, nie verschluckt.

---

## 3. Vor-Fix-Diskriminierung

`tests/test_download_utils_playlist_cancellation.py` gegen den ungefixten
Code ausgeführt: **5 failed, 3 passed**. Fehlgeschlagen (diskriminierend):
Test A/B/D (`_process_playlist_download()`-Ebene, `partial_playlist_results`
fehlte), beide Registrierungstests (`handle_youtube_links()`-Ebene, nichts
im DuplicateCache). Bereits vorher grün (Regressions-Guards): Normalfall
unverändert, „kein Absturz ohne Attribut", „Cancellation nie verschluckt".

---

## 4. Fix

Zwei kleine, rein additive `except`-Zweige, keine Signaturänderung:

**`services/downloader/download_utils.py::_process_playlist_download()`** —
neuer `except asyncio.CancelledError as ce:` vor dem bestehenden
`except Exception`: hängt die bis dahin gesammelte `results`-Liste als
`ce.partial_playlist_results` an das Exception-Objekt, dann `raise`.

**`klassen/download_handler.py::handle_youtube_links()`** — neuer
`except asyncio.CancelledError as ce:` vor dem bestehenden
`except Exception`: liest `getattr(ce, "partial_playlist_results", None)`,
ruft bei vorhandenen Teilergebnissen das unveränderte
`self._register_playlist_track_duplicates(partial_results)` auf, dann
`raise`.

`enhanced_download_with_retry()`, `download_audio()`,
`handle_playlist_success()`, `_register_playlist_track_duplicates()` selbst
— unverändert (beide Zwischenebenen fingen `CancelledError` bereits vorher
nicht ab, lassen sie samt Attribut unverändert durch).

**Neue Tests:** `tests/test_download_utils_playlist_cancellation.py` — 8
Tests: 4 auf `_process_playlist_download()`-Ebene (Cancellation bei Track 3/
Track 1/Normalfall/aktiver Track nie in Teilergebnissen), 4 auf
`handle_youtube_links()`-Ebene mit realer `DuplicateDetector`-Instanz
(Kernfall Registrierung, Gegenprobe, „nackte" CancelledError ohne Attribut,
Propagation-Absicherung). Echte `asyncio.Task.cancel()`-Semantik, keine
simulierte Exception.

---

## 5. Testergebnisse

```
tests/test_download_utils_playlist_cancellation.py:                          8 passed
tests/test_enhanced_metadata_processor_cancellation.py (DL-01):              9 passed
tests/test_download_handler_playlist_duplicate_registration.py (DUP-01/08):  7 passed
tests/test_download_utils_retry.py:                                         10 passed
python3 -m pytest tests/test_download*.py tests/test_playlist*.py -q:      194 passed
```

Vollständige Suite (`pytest tests/ -q`) im Rahmen von DL-08 bewusst NICHT
ausgeführt (verbindliche Teststrategie, CLAUDE.md Abschnitt 8.A — erst am
Ende der gesamten Arbeitsphase).

---

## 6. Fehlende PHASE-2F-Audit-Grundlage (transparenter Hinweis)

DL-08 (sowie DL-06 und DL-07) wurden ursprünglich in einer „PHASE 2F"
genannten Audit-Runde identifiziert. Diese Audit-Runde existiert **nicht**
als eigene Datei im Repository und ist auch über die Git-Historie nicht
mehr auffindbar (`git log --all --grep="DL-08"`/`"PHASE 2F"` ohne Treffer)
— ihr einziger Nachweis lag bis zu diesem Dokument ausschließlich im
Konversationsverlauf. DL-08s vollständige Root-Cause-Analyse wurde daher im
Rahmen dieser Phase (2K) unabhängig neu durchgeführt und hier erstmals
persistent dokumentiert.

---

## 7. Scope-Bestätigung

Betroffene Dateien: `services/downloader/download_utils.py`,
`klassen/download_handler.py` — beide bereits durch DUP-06 (PHASE 2M)
zusätzlich additiv erweitert, ohne dass die hier beschriebenen DL-08-Zeilen
verändert wurden (per Diff verifiziert). Keine Änderung an
`enhanced_download_with_retry()`, `download_audio()`,
`handle_playlist_success()`, `_register_playlist_track_duplicates()`
selbst, DL-01, DL-06, DUP-01, DUP-02, DUP-08.

---

## 8. Abschluss

DL-08 gilt hiermit als **technisch abgeschlossen**, Tests grün,
Vor-Fix-Diskriminierung erfolgreich nachgewiesen, Cancellation-Propagation
bestätigt nicht unterdrückt. Kein Commit, kein Push (Stand zum Zeitpunkt
dieses Dokuments weiterhin uncommitted im Working Tree). Der Gesamtstatus
der übergeordneten `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md`
bleibt **PLANNED**.
