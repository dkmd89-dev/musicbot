# MusicBot — Download Pipeline Stability Phase — PHASE 2L: DUP-04

> Analyse-, Fix- und Abschluss-Dokumentation für DUP-04. Basis:
> `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md` (Finding
> erstmals identifiziert), umgesetzt nach Abschluss von DUP-03 (PHASE 2J),
> wie im PHASE-1-Plan als Reihenfolge vorgesehen.

**Status: DUP-04 — TECHNISCH ABGESCHLOSSEN (uncommitted)**

---

## 1. Finding (aus PHASE 0)

**ID:** DUP-04 — P2 — Duplicate Detection — „feat."/„Featuring"/„ft."-Regex
zu eng.

**Datei/Funktion:**
`services/duplicate/detector.py::DuplicateDetector._clean_title_for_comparison()`.

**Root Cause:** Die Muster `r"\(feat\.?\s+.*?\)"` und `r"\(ft\.?\s+.*?\)"`
verlangten nach dem optionalen Punkt zwingend mindestens ein Leerzeichen
(`\s+`). „Featuring" (volles Wort statt „feat"/„feat.") und
„feat.Someone"/„ft.Someone" (ohne Leerzeichen nach dem Punkt) matchten
dadurch nicht — diese Klammerinhalte blieben im Titel stehen, zwei
Aufnahmen mit sonst identischem Content erhielten unterschiedliche
Content-Hashes (False Negative).

---

## 2. Vor-Fix-Diskriminierung

`tests/test_duplicate_detector_feat_ft_normalization.py` gegen den
ungefixten Code ausgeführt: **3 failed, 6 passed**. Fehlgeschlagen
(diskriminierend): Test 2 (`feat.Someone`), Test 4 (`ft.Someone`), Test 5
(`Featuring Someone`). Bereits vorher grün: Test 1/3/6 (bereits
funktionierende Fälle), Test 7/8/9 (Überkorrektur-/DUP-03-Regressionsguards).

---

## 3. Fix

```diff
-            r"\(feat\.?\s+.*?\)",
-            r"\(ft\.?\s+.*?\)",
+            r"\(feat(?:\.\s*|uring\s*|\s+).*?\)",
+            r"\(ft(?:\.\s*|\s+).*?\)",
```

Jede Alternative konsumiert mindestens ein echtes, unterscheidendes Zeichen
(Punkt, „uring" oder Whitespace) — bewusst **kein** `\s*` anstelle von
`\s+`, um zu verhindern, dass ein Klammerinhalt wie „(Featherweight Mix)"
fälschlich als Featuring-Credit interpretiert und entfernt wird (naiver
Fallstrick, explizit geprüft und vermieden).

**Geänderte Datei:** ausschließlich `services/duplicate/detector.py` (16
Zeilen inkl. Kommentar). `check_for_duplicates()`, `check_library_duplicate()`,
`register_download()` unverändert.

**Neue Tests:** `tests/test_duplicate_detector_feat_ft_normalization.py` —
9 Tests: 6 positive Fälle (`feat.`/`feat.Someone`/`ft Someone`/
`ft.Someone`/`Featuring Someone`/Kombination mit `[Lyrics]`), 3
Überkorrektur-/Regressionsschutz-Tests (Featherweight-Mix-Fall, DUP-03-
Live-/Remix-Schutz weiterhin aktiv).

---

## 4. Testergebnisse

```
tests/test_duplicate_detector_feat_ft_normalization.py:                9 passed
tests/test_duplicate_detector_hash_consistency.py (DUP-02):            5 passed
tests/test_duplicate_detector_live_version_false_positive.py (DUP-03): 7 passed
tests/test_duplicate*.py (gesamt):                                    38 passed
```

Vollständige Suite bewusst NICHT ausgeführt (verbindliche Teststrategie,
CLAUDE.md Abschnitt 8.A).

---

## 5. Scope-Bestätigung

Einzige Produktions-Codeänderung für DUP-04: `services/duplicate/detector.py`
(zusätzlich zu den bereits vorhandenen DUP-03-Zeilen in derselben Funktion).
Keine Änderung an DUP-01/DUP-02/DUP-08-Code, DL-01/DL-06/DL-08-Code,
`config_test.py`, `mapping/case_preserve.yaml`, `run_test_bot.py`.

---

## 6. Abschluss

DUP-04 gilt hiermit als **technisch abgeschlossen**, Tests grün,
Vor-Fix-Diskriminierung erfolgreich nachgewiesen, DUP-02/DUP-03-
Regressionsschutz bestätigt. Kein Commit, kein Push (Stand zum Zeitpunkt
dieses Dokuments weiterhin uncommitted im Working Tree). Der Gesamtstatus
der übergeordneten `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md`
bleibt **PLANNED**.
