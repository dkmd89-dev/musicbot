# MusicBot — Metadata Quality Phase — PHASE 3: META-04

> Analyse-, Fix- und Abschluss-Dokumentation für META-04 (Teil: "makko").
> Basis: `docs/MusicBot_METADATA_QUALITY_PHASE0_AUDIT.md` (Finding
> erstmals identifiziert). Freigabe zur Tiefenanalyse und Nutzer-
> Bestätigung der korrekten Schreibweise für "makko" am 2026-08-26 erhalten.

**Status: META-04 — VOLLSTÄNDIG ABGESCHLOSSEN (committed).**

---

## 1. Finding (aus PHASE 0)

**ID:** META-04 — P1 — Artist — Case-sensitive Artist-Ordner-Duplikate mit
echter Diskografie-Aufspaltung (`makko/` vs. `Makko/`, `t-Low/` vs.
`T-Low/`, real in der Library gefunden).

---

## 2. Root Cause (Tiefenanalyse)

**Kein Bug im `ArtistNormalizer`-Mechanismus.** `utils/artist_map.py::
_standard_normalization()`/`_normalize_rest()` fällt für unbekannte, nicht
in `case_preserve.yaml` oder `artist_overrides.json` geschützte Namen
bewusst auf Title-Case (`.capitalize()`) zurück — bereits charakterisiert
und getestet in
`tests/test_artist_normalizer.py::test_plain_lowercase_name_falls_back_to_title_case`.
Dieses Verhalten ist unabhängig von der im Quelltext (YouTube-Titel/
Kanalname) vorkommenden Groß-/Kleinschreibung, da `_check_overrides()`
sowohl den exakten als auch den über `_normalize_key()` case-insensitiv
normalisierten Override-Lookup durchführt (verifiziert: `normalize("makko")`,
`normalize("Makko")`, `normalize("MAKKO")` liefern vor dem Fix alle
identisch `"Makko"`).

**Tatsächliche Ursache:** `mapping/artist_overrides.json` enthielt einen
expliziten, aktiven Eintrag `"makko": "Makko"` — dieser überschreibt für
**jeden** Download den eigentlich vorgesehenen Case-Preserve-Mechanismus
und erzwingt konsistent Großschreibung, obwohl „makko" laut
Nutzerbestätigung sein tatsächlicher, bewusst kleingeschriebener
Künstlername ist. Die 7 „Makko"-Alben in der Library entsprechen dem
aktuellen (fehlerhaften) Override-Verhalten; das 1 „makko"-Album ist
vermutlich vor Einführung dieses Overrides entstanden (Altlast).

Analog dazu enthielt dieselbe Datei `"t-low": "t-Low"` — erklärt
strukturell identisch die gefundene Aufspaltung „t-Low" (7 Alben, damals
aktuell) vs. „T-Low" (1 Datei, Altlast). Nutzer hat bestätigt: die
tatsächliche Eigenschreibweise ist „t-low" (durchgehend klein) — auch
„t-Low" war also bereits falsch. Fix siehe Abschnitt 4b.

---

## 3. Vor-Fix-Charakterisierung

Gegen die echten Mapping-Dateien (`utils/artist_map.py::ArtistNormalizer`
mit `mapping_dir="mapping"`) ausgeführt:

```
normalize("makko") -> "Makko"
normalize("Makko") -> "Makko"
normalize("MAKKO") -> "Makko"
```

`tests/test_artist_overrides_makko_case_preserve.py` gegen den
ungefixten Stand: **1 failed, 3 passed**. Fehlgeschlagen (diskriminierend):
der Daten-Integritätstest gegen die reale `artist_overrides.json`. Bereits
vorher grün: der isolierte Mechanismus-Test (belegt, dass der Case-
Preserve-Mechanismus selbst korrekt funktioniert, sobald der Override-Wert
stimmt).

---

## 4. Fix

```diff
-  "makko": "Makko",
+  "makko": "makko",
```

**Geänderte Datei:** ausschließlich `mapping/artist_overrides.json` (ein
Eintrag). Keine Code-Änderung — der Mechanismus selbst war bereits
korrekt.

**Neue Tests:** `tests/test_artist_overrides_makko_case_preserve.py` — 4
Tests: 3 isolierte Mechanismus-Tests (case-insensitiver Input, alle
resultieren im kleingeschriebenen Override-Wert — nutzt dieselbe
`tmp_path`-Isolationsstruktur wie `tests/test_artist_normalizer.py`, echtes
`mapping/`-Verzeichnis bleibt unberührt), 1 Daten-Integritätstest direkt
gegen die reale `mapping/artist_overrides.json` (schützt gezielt gegen
ein versehentliches Zurücksetzen dieser Korrektur).

---

## 4b. Fix — „t-low" (Nachtrag, nach Nutzerbestätigung)

```diff
-  "t-low": "t-Low",
+  "t-low": "t-low",
```

Vor-Fix-Charakterisierung: `normalize("t-low"/"t-Low"/"T-Low"/"T-LOW")`
lieferte einheitlich `"t-Low"`. `tests/test_artist_overrides_t_low_case_preserve.py`
gegen den ungefixten Stand: **1 failed, 3 passed** (identisches Muster wie
beim makko-Fix).

**Neue Tests:** `tests/test_artist_overrides_t_low_case_preserve.py` — 4
Tests, identischer Aufbau wie beim makko-Fix.

---

## 5. Testergebnisse

```
STUFE 1 (gezielt):
tests/test_artist_overrides_makko_case_preserve.py:    4 passed
tests/test_artist_overrides_t_low_case_preserve.py:    4 passed

STUFE 2 (direkte Regression):
tests/test_artist_normalizer.py:                      17 passed
tests/test_metadata_modules.py:                  15 passed (11 subtests)

STUFE 3 (thematische Suite — Metadata + Artist + Genre + Duplicate):
352 passed, 11 subtests passed

STUFE 4 (vollständige Suite, am Ende der Arbeitsphase):
1238 passed, 1 warning (vorbestehend, unabhängig), 19 subtests passed
(Baseline vor beiden Fixes: 1230 passed → +8 neue Tests, 0 Regressionen)
```

---

## 6. „Max Giesinger" — geklärt, kein MusicBot-Problem

Nutzer-Rückmeldung: die ursprüngliche Sorge betraf wiederkehrende
Tippfehler bei den Buchstaben x/y/z (klassische QWERTZ/QWERTY-
Verwechslung), keine fehlerhafte Normalisierung durch MusicBot. Bei
Prüfung in Symfonium (Navidrome-Client) ist „Max Giesinger" bereits
korrekt geschrieben. Kein Finding, keine Mapping-Änderung nötig.

**Library-Konsolidierung**: die bestehenden, durch die Altlast entstandenen
Ordner „makko/" (1 Album) und „T-Low/" (1 Datei, jeweils bereits auch
unter „Makko/" bzw. „t-Low/" vorhanden) wurden **nicht** angefasst — das
wäre eine Schreiboperation auf der realen Library und erfordert nach
CLAUDE.md explizite gesonderte Freigabe.

---

## 7. Abschluss

META-04 gilt für die Teilaspekte „makko" und „t-low" hiermit als
**abgeschlossen**. Root Cause vollständig identifiziert (Mapping-
Datenfehler, kein Code-Bug), Vor-Fix-Charakterisierung für beide Fälle
erfolgreich, Fix jeweils minimal (ein JSON-Wert), vollständige Suite grün
(1238 passed, 0 failed, 0 errors). „Max Giesinger" wurde als Fehlalarm
(Tippfehler, kein MusicBot-Problem) geklärt. Die Library-Konsolidierung
(bestehende „makko"/„T-Low"-Altlast-Ordner) bleibt eine separate,
noch nicht freigegebene Library-Schreiboperation. Commit/Push/PR/Merge
auf explizite Nutzerfreigabe hin durchgeführt (siehe Git-Historie).
