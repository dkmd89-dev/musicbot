# MusicBot — Download Pipeline Stability Phase — PHASE 2J: DUP-03

> Fix- und Abschluss-Dokumentation für DUP-03. Basis:
> `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md` (Finding
> erstmals identifiziert), aufbauend auf Commit `b7857e7` (DL-02,
> DUP-01/DUP-08, DUP-02).

**Status: DUP-03 — TECHNISCH ABGESCHLOSSEN (uncommitted)**

---

## 1. Finding (aus PHASE 0)

**ID:** DUP-03 — P1 — Duplicate Detection — Normalisierungs-False-Positive
bei „(Live …)"/„(… Version)"/„(Remix)".

**Datei/Funktion:**
`services/duplicate/detector.py::DuplicateDetector._clean_title_for_comparison()`.

**Root Cause:** Drei Regex-Muster in `patterns_to_remove`
(`r"\(.*?Version\)"`, `r"\(Live.*?\)"`, `r"\(Remix\)"`) entfernten den
gesamten Klammerinhalt unabhängig von seiner Spezifität. `"Hello (Live at
Glastonbury 2016)"` und `"Hello"` (Studio-Original) ergaben nach Bereinigung
identisch `"Hello"` → gleicher Content-Hash → die Live-Version wurde
fälschlich als Duplikat blockiert und nie heruntergeladen. Ebenso betroffen:
`"(… Version)"`- und `"(Remix)"`-Suffixe.

---

## 2. Vor-Fix-Diskriminierung

Direkte Reproduktion gegen den ungefixten Code (vor jeder Änderung, inline
Python-Skript):

```
'Hello' vs 'Hello (Live at Glastonbury 2016)' -> cleaned: 'Hello' / 'Hello' -> Kollision (Bug)=True
'Hello' vs 'Hello (Live Version)'             -> cleaned: 'Hello' / 'Hello' -> Kollision (Bug)=True
'Hello' vs 'Hello (Remix)'                    -> cleaned: 'Hello' / 'Hello' -> Kollision (Bug)=True
'Hello' vs 'Hello (Radio Version)'            -> cleaned: 'Hello' / 'Hello' -> Kollision (Bug)=True
```

Alle 4 vorgesehenen Fälle reproduzierten den Fehler eindeutig.

---

## 3. Fix

**Minimale Änderung:** die drei zu breiten Muster ersatzlos aus
`patterns_to_remove` entfernt — keine neue Regex, keine Positivliste, keine
neue Normalisierungslogik.

```diff
         patterns_to_remove = [
             r"\(Official.*?\)",
             r"\[.*?\]",
             r"\(feat\.?\s+.*?\)",
             r"\(ft\.?\s+.*?\)",
-            r"\(.*?Version\)",
-            r"\(Live.*?\)",
-            r"\(Remix\)",
         ]
```

**Geänderte Datei:** ausschließlich `services/duplicate/detector.py` (3
Zeilen entfernt). `check_for_duplicates()`, `check_library_duplicate()`,
`register_download()` unverändert (nutzen dieselbe Funktion weiterhin
unverändert mit).

**Bewusstes Scope-Limit (kein Versäumnis):** die breite
eckige-Klammer-Regel `r"\[.*?\]"` wurde bewusst NICHT verändert. Ein
hypothetischer Fall `"Hello [Live]"` bleibt daher außerhalb des
DUP-03-Scopes.

**Neue Tests:** `tests/test_duplicate_detector_live_version_false_positive.py`
— 7 Tests: 4 Live-/Version-/Remix-/Radio-Version-Fälle (kein Duplikat), 1
Regressionsschutz gegen Überkorrektur (zwei identische Live-Reuploads
weiterhin als Duplikat erkannt), 2 Nicht-Regressions-Guards
(„(Official Video)"/„(Official Audio)" bleiben weiterhin strippbar).

---

## 4. Testergebnisse

```
tests/test_duplicate_detector_live_version_false_positive.py: 7 passed
tests/test_duplicate_detector_hash_consistency.py (DUP-02):    5 passed
tests/test_duplicate*.py (gesamt, Stand zum Zeitpunkt des Fixes): 29 passed
python3 -m pytest tests/ -q (Abschlusskontrolle):              1164 passed, 1 warning, 19 subtests
```

0 failed, 0 errors innerhalb des `tests/`-Scopes. Ein zusätzlicher,
unscoped `pytest -q`-Lauf zeigte 7 Fehlschläge in `mapping/test_genre_map.py`
— per doppelter `git stash`-Isolation (Produktionsfix und neue Testdatei
beide zurückgenommen) nachweislich unabhängig von DUP-03, außerhalb des
`tests/`-Scopes, nicht behoben (siehe Abschnitt 5).

---

## 5. Bekannte, nicht blockierende Beobachtung

`mapping/test_genre_map.py` zeigt 7 vorbestehende, DUP-03-unabhängige
Fehlschläge (`GenreResult`-Objekt vs. String-Vergleich), ausschließlich
sichtbar bei projektweitem `pytest -q` ohne `tests/`-Einschränkung — alle
bisherigen „vollständige Suite"-Läufe dieser Arbeitsphase liefen scoped
(`pytest tests/ -q`) und hatten dieses Verzeichnis nie erfasst. Nicht Teil
von DUP-03, nicht ungefragt behoben.

---

## 6. Scope-Bestätigung

Einzige Produktions-Codeänderung für DUP-03: `services/duplicate/detector.py`
(3 Zeilen entfernt). Keine Änderung an `config_test.py`,
`mapping/case_preserve.yaml`, `run_test_bot.py`, DL-01/DL-06-Code,
DUP-01/DUP-02/DUP-08-Code.

---

## 7. Abschluss

DUP-03 gilt hiermit als **technisch abgeschlossen**, Tests grün,
Vor-Fix-Diskriminierung erfolgreich nachgewiesen. Kein Commit, kein Push
(Stand zum Zeitpunkt dieses Dokuments weiterhin uncommitted im Working
Tree). Der Gesamtstatus der übergeordneten
`docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md` bleibt **PLANNED**.
