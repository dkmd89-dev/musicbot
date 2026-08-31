# MusicBot — TAG-01: Multi-Artist-Tag wurde nicht als separate Werte geschrieben

> Entdeckt vom Nutzer durch einen echten Abgleich mit Navidrome/Symfonium
> am 2026-08-31, im Anschluss an den „Clueso feat. Chapo102"-Testdownload
> (Multi-Artist-Verifikation dieser Session).

**Status: TAG-01 — ABGESCHLOSSEN (committed).**

---

## 1. Finding

**ID:** TAG-01 — P0 (Metadata/Tags) — `TagWriter.write_tags()` schrieb das
Multi-Artist-Feld „ARTISTS" als einen mit „; " zusammengefügten String
statt als mehrere separate Werte — Navidrome konnte den Track dadurch
nicht unter dem Feature-Artist finden.

**Nutzer-Beobachtung (real, Symfonium):** bei „Clueso feat. Chapo102"
wurde nur „Clueso" korrekt als Interpret erkannt. Unter „Zusätzlicher
Interpret" erschien „Clueso; CHAPO102" als **ein** zusammengefügter
String statt als zwei getrennte Einträge. Der Track war unter dem Artist
„CHAPO102" nicht auffindbar.

**Root Cause (direkt via `mutagen` an der real erzeugten Testdatei
verifiziert):**

```
©ART (Standard-Artist-Atom)              -> ['Clueso', 'CHAPO102']   ✅ bereits korrekt (2 separate Werte)
----:com.apple.iTunes:ARTISTS (Picard-   -> [MP4FreeForm(b'Clueso; CHAPO102')]  ❌ EIN zusammengefügter String
  Konvention, von Navidrome für Multi-
  Artist-Splitting gelesen)
```

Der Standard-Artist-Tag war also bereits richtig (mehrere Werte), aber
das speziell für Multi-Artist-Splitting vorgesehene Feld
(`----:com.apple.iTunes:ARTISTS`, MusicBrainz-Picard-Konvention, von
Navidrome ausgewertet) enthielt nur einen einzigen, zusammengefügten
String — Navidrome kann diesen nicht in einzelne Interpreten aufsplitten.

**Zusätzlicher Nebenbefund:** `audio["ARTISTS"] = [artists_semicolon]`
(ohne `----:com.apple.iTunes:`-Präfix) ist gar kein gültiger 4-Byte-MP4-
Atom-Schlüssel — `mutagen` kappte/interpretierte ihn zu einem
bedeutungslosen `ARTI`-Atom (direkt verifiziert:
`audio['ARTI'] -> ['Clueso; CHAPO102']`), das von keiner bekannten
Software gelesen wird. Reiner Datenmüll.

Für MP3 galt strukturell dasselbe: `TXXX(desc="ARTISTS",
text=artists_semicolon)` übergab `text` als einzelnen String statt als
Liste separater Werte (ID3v2.4-TXXX-Frames unterstützen native
Multi-Value-Listen).

---

## 2. Vor-Fix-Diskriminierung

`tests/test_tag_writer_multi_value_artists_tag.py` gegen den ungefixten
Code: **4 failed, 1 passed**. Fehlgeschlagen (diskriminierend): beide
Kernfälle (MP3-TXXX, M4A-Freeform), der Drei-Künstler-Fall, der
„kein-ARTI-Atom"-Nebenbefund-Test. Bereits vorher grün: der Regressions-
Test, dass das Standard-`©ART`-Atom bereits korrekt multi-valued war
(unverändert korrekt).

---

## 3. Fix

**`services/metadata/tag_writer.py`** — M4A-Zweig:

```diff
 if feat_artists:
-    audio["ARTISTS"] = [artists_semicolon]
-    audio["----:com.apple.iTunes:ARTISTS"] = [
-        artists_semicolon.encode("utf-8")
-    ]
+    audio["----:com.apple.iTunes:ARTISTS"] = [
+        MP4FreeForm(a.encode("utf-8")) for a in all_artists
+    ]
```

**MP3-Zweig:**

```diff
 if feat_artists:
-    audio.add(TXXX(encoding=3, desc="ARTISTS", text=artists_semicolon))
+    audio.add(TXXX(encoding=3, desc="ARTISTS", text=all_artists))
```

Beide Zweige schreiben jetzt eine Liste separater Werte (ein Eintrag je
Künstler) statt eines zusammengefügten Strings — Standard-Konvention für
Multi-Value-ID3v2.4-TXXX-Frames bzw. MP4-Freeform-Atome (Picard-
kompatibel), die Navidrome für das Splitten in einzelne Interpreten
benötigt. Der ungültige `audio["ARTISTS"]`-Schlüssel (→ bedeutungsloses
`ARTI`-Atom) wurde ersatzlos entfernt. `artists_semicolon` bleibt als
Variable erhalten (weiterhin für die Log-Ausgabe verwendet).

**Geänderte Datei:** ausschließlich `services/metadata/tag_writer.py`.

**Neue Tests:** `tests/test_tag_writer_multi_value_artists_tag.py` — 5
Tests (MP3: Zwei-/Drei-Künstler-Fall; M4A: Kernfall über echte
ffmpeg-erzeugte Datei, Regressionsschutz für `©ART`, Nebenbefund-
Regressionsschutz gegen das `ARTI`-Atom). Zusätzlich bestehender Test
`tests/test_tag_writer.py::test_feat_artists_are_added_as_secondary_artist_txxx`
aktualisiert (kodierte vorher das alte, fehlerhafte Verhalten als
erwartetes Ergebnis).

---

## 4. Testergebnisse

```
STUFE 1 (gezielt):
tests/test_tag_writer_multi_value_artists_tag.py:   5 passed

STUFE 2 (direkte Regression):
tests/test_tag_writer.py, test_tag_writer_atomic_replace.py,
test_tag_writer_write_tags_concurrent_safety.py:    29 passed

STUFE 3 (thematische Suite):
82 passed, 11 subtests passed

STUFE 4 (vollständige Suite, am Ende der Arbeitsphase):
1275 passed, 1 warning (vorbestehend, unabhängig), 19 subtests passed
(Baseline vor diesem Fix: 1270 passed → +5 neue Tests, 0 Regressionen)
```

---

## 5. Offene Live-Verifikation

Der Fix wurde über eine echte, per `ffmpeg` erzeugte M4A-Datei getestet
(direkte `mutagen`-Prüfung der Atome). Eine vollständige End-to-End-
Bestätigung über den tatsächlichen Navidrome-Scan + Symfonium-Anzeige
(wie ursprünglich vom Nutzer beobachtet) steht noch aus, da dies Zugriff
auf die reale Navidrome-Instanz des Nutzers erfordert. Empfehlung: nach
einem frischen Test-Download den Track in Navidrome scannen lassen und
in Symfonium prüfen, ob „CHAPO102" jetzt als eigener, separater Interpret
erscheint und der Track dort auffindbar ist.

---

## 6. Abschluss

TAG-01 gilt hiermit als **abgeschlossen** (Code-seitig, unit-getestet).
Root Cause vollständig identifiziert und direkt an der real vom Nutzer
beobachteten Testdatei nachvollzogen, Vor-Fix-Diskriminierung erfolgreich,
Fix minimal (zwei Zeilen je Format), vollständige Suite grün (1275
passed, 0 failed, 0 errors). Fünfter unabhängiger Fund aus der vom
Nutzer initiierten Test-Download-Serie (nach META-11, TESTENV-01, MB-01,
META-11-Nachtrag) — diesmal durch einen Abgleich mit der echten
Downstream-Software (Navidrome/Symfonium) entdeckt, nicht nur durch
Log-Beobachtung. Commit/Push/PR/Merge auf explizite Nutzerfreigabe hin
durchgeführt (siehe Git-Historie).
