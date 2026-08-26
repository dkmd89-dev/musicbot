# MusicBot — Metadata Quality Phase — PHASE 1: META-01 + META-02

> Analyse-, Fix- und Abschluss-Dokumentation für META-01 und META-02.
> Basis: `docs/MusicBot_METADATA_QUALITY_PHASE0_AUDIT.md` (Findings
> erstmals identifiziert). Gebündelt behandelt, da identische
> Wurzelursache und identisches, bereits durch DUP-04 bewährtes Fix-Muster.

**Status: META-01 + META-02 — ABGESCHLOSSEN (committed)**

---

## 1. Findings (aus PHASE 0)

**META-01 — P0 — Artist — `utils/youtube_parser.py`**

Betroffene Stellen:
- `_extract_features()` — alle drei Varianten (Klammern, eckige Klammern,
  plain).
- `_parse_artist_and_title()` — `feat_in_artist_pattern`.

**Root Cause:** „feat"/„ft" verlangten nach dem optionalen Punkt zwingend
mindestens ein Leerzeichen (`\s+`). „feat.Artist"/„ft.Artist" (ohne
Leerzeichen nach dem Punkt) matchte dadurch nicht — der Featuring-Credit
landete unaufgeteilt im Artist-Feld statt in `featuring`.

Real reproduziert (vor dem Fix):

```
'Peter Fox feat. Inez - Zukunft Pink'  → artist='Peter Fox',           all_artists=['Peter Fox','Inez']    ✅
'Peter Fox feat.Inez - Zukunft Pink'   → artist='Peter Fox feat.Inez',  all_artists=['Peter Fox feat.Inez']  ❌
'Travis Scott ft.Drake - SICKO MODE'   → artist='Travis Scott ft.Drake', all_artists=['Travis Scott ft.Drake'] ❌
```

**META-02 — P0 — Title — `services/metadata/title_cleaner.py`**

Betroffene Stelle: `apply_title_cleanup_rules()`, feat/ft-Cleanup-Pattern
(direkt neben dem ARTISTNORM-002-Wortgrenzen-Kommentar).

**Root Cause:** identisch zu META-01, anderer Ort — `"(feat.Someone)"`
blieb im finalen, getaggten Titel stehen statt entfernt zu werden;
`"(feat. Someone)"` (mit Leerzeichen) funktionierte bereits korrekt.

Direktes Pendant zu DUP-04 (`services/duplicate/detector.py`, PHASE 2L
dieser Session) — dort betraf es nur den Duplicate-Vergleich, hier die
tatsächliche Artist/Title-Extraktion, die in Tag und Dateiname landet.

---

## 2. Vor-Fix-Diskriminierung

`tests/test_youtube_parser_feat_ft_no_space.py` gegen den ungefixten Code:
**7 failed, 3 passed**. Fehlgeschlagen (diskriminierend): alle vier
`_extract_features`-Kernfälle, beide `feat_in_artist_pattern`-Kernfälle,
der "nach Trennzeichen"-Fall. Bereits vorher grün: Überkorrektur-Schutz
("Featherweight") und die bereits funktionierende Leerzeichen-Variante.

`tests/test_title_cleaner_feat_ft_no_space.py` gegen den ungefixten Code:
**3 failed, 3 passed**. Fehlgeschlagen (diskriminierend): die drei
Kernfälle ("(feat.Someone)", "(ft.Someone)", "feat.Someone" ohne
Klammern). Bereits vorher grün: Überkorrektur-Schutz (Featherweight,
Kraftklub-Wortgrenze) und die Leerzeichen-Variante.

---

## 3. Fix

**`utils/youtube_parser.py`** — `_extract_features()`:

```diff
-        (r"\(\s*(?:feat\.?|ft\.?|featuring|with|pres\.?)\s+(.+?)\s*\)", "()"),
-        (r"\[\s*(?:feat\.?|ft\.?|featuring)\s+(.+?)\s*\]", "[]"),
-        (r"\s+(?:feat\.?|ft\.?|featuring|with|pres\.?)\s+(.+?)$", "plain"),
+        (r"\(\s*(?:feat(?:\.\s*|\s+)|ft(?:\.\s*|\s+)|featuring\s+|with\s+|pres(?:\.\s*|\s+))(.+?)\s*\)", "()"),
+        (r"\[\s*(?:feat(?:\.\s*|\s+)|ft(?:\.\s*|\s+)|featuring\s+)(.+?)\s*\]", "[]"),
+        (r"\s+(?:feat(?:\.\s*|\s+)|ft(?:\.\s*|\s+)|featuring\s+|with\s+|pres(?:\.\s*|\s+))(.+?)$", "plain"),
```

**`utils/youtube_parser.py`** — `_parse_artist_and_title()`,
`feat_in_artist_pattern`:

```diff
-        r"^(.+?)\s+(?:feat\.?|ft\.?|featuring|with)\s+(.+?)\s*[-–—|:]\s*(.+)$",
+        r"^(.+?)\s+(?:feat(?:\.\s*|\s+)|ft(?:\.\s*|\s+)|featuring\s+|with\s+)(.+?)\s*[-–—|:]\s*(.+)$",
```

**`services/metadata/title_cleaner.py`** — `apply_title_cleanup_rules()`:

```diff
-            (r"\s*[-–—]?\s*\b(?:feat\b\.?|ft\b\.?|featuring\b)\s+[^(\[\n]+", ""),
+            (r"\s*[-–—]?\s*\b(?:feat(?:\.\s*|\s+)|ft(?:\.\s*|\s+)|featuring\s+)[^(\[\n]+", ""),
```

Alle drei Änderungen folgen exakt dem bei DUP-04 bewährten Muster: nach
„feat"/„ft" entweder (a) ein Punkt gefolgt von optionalem Whitespace, oder
(b) mindestens ein Leerzeichen (ohne Punkt) — jede Alternative konsumiert
mindestens ein echtes, unterscheidendes Zeichen. Bewusst **kein** `\s*`
statt `\s+`, um zu verhindern, dass „Featherweight" fälschlich als
Featuring-Credit interpretiert wird. „featuring"/„with"/„pres" behalten
ihre bisherige Pflicht-Leerzeichen-Logik (kein nachgewiesener Bug dort).

**Geänderte Dateien:** `utils/youtube_parser.py` (zwei Stellen),
`services/metadata/title_cleaner.py` (eine Stelle). Keine weiteren
Produktionsdateien angefasst.

**Neue Tests:**
- `tests/test_youtube_parser_feat_ft_no_space.py` — 10 Tests (4×
  `_extract_features` Kernfälle, 2× Überkorrektur-/Regressionsschutz, 3×
  `parse_youtube_title`-Kernfälle vor/nach Trennzeichen, 1×
  Überkorrektur-Schutz auf Gesamt-Parsing-Ebene).
- `tests/test_title_cleaner_feat_ft_no_space.py` — 6 Tests (3 Kernfälle,
  1 Regressionsschutz Leerzeichen-Variante, 2 Überkorrektur-/
  ARTISTNORM-002-Regressionsschutz).

---

## 4. Testergebnisse

```
STUFE 1 (gezielt):
tests/test_youtube_parser_feat_ft_no_space.py:      10 passed
tests/test_title_cleaner_feat_ft_no_space.py:         6 passed

STUFE 2 (direkte Regression):
tests/test_youtube_parser.py:                        43 passed
tests/test_metadata_modules.py:                 15 passed (11 subtests)

STUFE 3 (thematische Suite — Metadata + Genre + Duplicate-Pendant):
306 passed, 11 subtests passed

STUFE 4 (vollständige Suite, am Ende der Arbeitsphase):
1221 passed, 1 warning (vorbestehend, unabhängig), 19 subtests passed
(Baseline vor diesem Fix: 1205 passed → +16 neue Tests, 0 Regressionen)
```

---

## 5. Scope-Bestätigung

Einzige Produktionscode-Änderungen: `utils/youtube_parser.py`,
`services/metadata/title_cleaner.py`. Keine Änderung an
`services/duplicate/detector.py` (DUP-Serie), Download-Pipeline-Dateien,
Config oder Mapping-Dateien.

---

## 6. Abschluss

META-01 und META-02 gelten hiermit als **abgeschlossen**. Vor-Fix-
Diskriminierung erfolgreich nachgewiesen, Fix minimal und auf das exakt
gleiche, bereits bewährte DUP-04-Muster gestützt, vollständige Suite grün
(1221 passed, 0 failed, 0 errors), Regressionsschutz (Featherweight,
Kraftklub-Wortgrenze, bereits funktionierende Leerzeichen-Varianten)
bestätigt. Commit/Push/PR/Merge auf explizite Nutzerfreigabe hin
durchgeführt (siehe Git-Historie).
