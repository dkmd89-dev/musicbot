# MusicBot — Metadata Quality Phase — PHASE 2: META-03

> Analyse-, Fix- und Abschluss-Dokumentation für META-03. Basis:
> `docs/MusicBot_METADATA_QUALITY_PHASE0_AUDIT.md` (Finding erstmals
> identifiziert), umgesetzt nach Abschluss von META-01/META-02 (PHASE 1),
> wie dort als offener Folge-Kandidat vorgesehen.

**Status: META-03 — ABGESCHLOSSEN (committed)**

---

## 1. Finding (aus PHASE 0)

**ID:** META-03 — P0 — Title — Nicht gelistete Marketing-Suffixe erzeugen
kaputten Titel mit hängender Klammer.

**Datei/Funktion:**
`services/metadata/title_cleaner.py::TitleCleaner.apply_title_cleanup_rules()`,
Pattern "Allgemeine Official/Video-Tags".

**Root Cause:** Das Pattern behandelte öffnende (`\(?`) und schließende
Klammer (`\)?`) unabhängig voneinander optional. Enthielt eine Klammer
neben bekannten Schlüsselwörtern (official/music/lyric/video/audio/live/
version/remaster/hd/4k/vevo/explicit) auch ein nicht gelistetes Wort
(z.B. „Visual", „Trailer", „Bonus Track"), wurde nur der Schlüsselwort-
Teil entfernt — die schließende Klammer blieb als hängendes Fragment im
Titel stehen.

Real in der Library bestätigt:
`Bebe Rexha/Singles/2026 - Sad Girls (Official Visual).m4a` → Titel-Tag
wurde zu „Sad Girls Visual)" statt „Sad Girls" bereinigt.

---

## 2. Vor-Fix-Diskriminierung

`tests/test_title_cleaner_marketing_suffix_bracket.py` gegen den
ungefixten Code ausgeführt: **4 failed, 5 passed**. Fehlgeschlagen
(diskriminierend): die drei Kernfälle (Official+Visual, Official+Trailer,
HD+Bonus Track) sowie der zusammenfassende "keine hängende Klammer"-Test.
Bereits vorher grün: alle vier Regressionsfälle (reines Schlüsselwort-
Klammer-Inhalt, klammerloser Suffix, explicit+HD-Kombi, bare „4K") und der
Überkorrektur-Schutz (Klammer ohne bekanntes Schlüsselwort bleibt
unangetastet).

---

## 3. Fix

```diff
-            (
-                r"\(?\s*(?:official|music|lyric|video|audio|live|version|remaster|hd|4k|vevo|explicit)"
-                r"(?:\s+(?:official|music|lyric|video|audio|live|version|remaster|hd|4k|vevo|explicit))*"
-                r"\s*\)?",
-                "",
-                re.IGNORECASE,
-            ),
+            (
+                r"\(\s*(?:official|music|lyric|video|audio|live|version|remaster|hd|4k|vevo|explicit)"
+                r"(?:\s+\S+)*\s*\)",
+                "",
+                re.IGNORECASE,
+            ),
+            (
+                r"\s*(?:official|music|lyric|video|audio|live|version|remaster|hd|4k|vevo|explicit)"
+                r"(?:\s+(?:official|music|lyric|video|audio|live|version|remaster|hd|4k|vevo|explicit))*"
+                r"\s*",
+                "",
+                re.IGNORECASE,
+            ),
```

Das ursprüngliche Einzel-Pattern wurde in zwei Pattern gesplittet:

1. **Geklammerte Form** — verlangt jetzt zwingend eine echte schließende
   Klammer (`\(` und `\)` beide obligatorisch, nicht mehr optional). Ist
   das erste Wort im Klammerinhalt ein bekanntes Schlüsselwort, wird der
   **gesamte** Klammerinhalt entfernt (`(?:\s+\S+)*` erlaubt beliebige
   Folgewörter, nicht nur gelistete) — kann dadurch nie mehr eine
   hängende Klammer hinterlassen, da ohne passende schließende Klammer
   gar nicht erst gematcht wird.
2. **Klammerlose Form** — unverändert zur bisherigen Logik (nur bekannte
   Schlüsselwörter, kein Klammer-Handling), deckt weiterhin Fälle wie
   „Song Title | Official Video" oder bare „4K"/„HD" ab.

Regex-Backtracking stellt sicher, dass bei mehreren Folgewörtern (z.B.
„(Official Video - Extended Cut)") die schließende Klammer korrekt erkannt
wird, auch wenn `\S+` sie zunächst probeweise mit-konsumiert (verifiziert
per Analyse und Test).

Eine Klammer, deren erstes Wort **kein** bekanntes Schlüsselwort ist
(z.B. „(Extended Cut)"), bleibt weiterhin vollständig unangetastet —
identisches Verhalten zu vorher, kein neues Überkorrektur-Risiko.

**Geänderte Datei:** ausschließlich `services/metadata/title_cleaner.py`.

**Neue Tests:** `tests/test_title_cleaner_marketing_suffix_bracket.py` —
9 Tests: 4 positive Kernfälle (Official+Visual, Official+Trailer,
HD+Bonus Track, „keine hängende Klammer" zusammenfassend), 4
Regressionstests (deckungsgleich mit bereits bestehenden Fällen aus
`tests/test_metadata_modules.py::test_apply_cleanup_rules`), 1
Überkorrektur-Schutz-Test.

---

## 4. Testergebnisse

```
STUFE 1 (gezielt):
tests/test_title_cleaner_marketing_suffix_bracket.py:  9 passed

STUFE 2 (direkte Regression):
tests/test_metadata_modules.py:                  15 passed (11 subtests)
tests/test_youtube_parser.py:                        43 passed
tests/test_title_cleaner_feat_ft_no_space.py:         6 passed

STUFE 3 (thematische Suite — Metadata + Genre + Duplicate-Pendant):
315 passed, 11 subtests passed

STUFE 4 (vollständige Suite, am Ende der Arbeitsphase):
1230 passed, 1 warning (vorbestehend, unabhängig), 19 subtests passed
(Baseline vor diesem Fix: 1221 passed → +9 neue Tests, 0 Regressionen)
```

---

## 5. Scope-Bestätigung

Einzige Produktionscode-Änderung: `services/metadata/title_cleaner.py`
(dasselbe Pattern-Array wie META-02, unmittelbar benachbart, aber
getrennter Regel-Eintrag — keine Interferenz zwischen den beiden Fixes,
durch die Testsuiten beider Findings gemeinsam bestätigt). Keine
Änderung an `utils/youtube_parser.py`, Duplicate-Detection, Download-
Pipeline, Config oder Mapping-Dateien.

---

## 6. Abschluss

META-03 gilt hiermit als **abgeschlossen**. Vor-Fix-Diskriminierung
erfolgreich nachgewiesen, Fix minimal und lokal auf das betroffene
Pattern begrenzt, vollständige Suite grün (1230 passed, 0 failed, 0
errors), Regressionsschutz und Überkorrektur-Schutz bestätigt. Damit sind
alle drei Kategorie-A-Findings aus PHASE 0 (META-01, META-02, META-03)
abgeschlossen. Commit/Push/PR/Merge auf explizite Nutzerfreigabe hin
durchgeführt (siehe Git-Historie).
