# MusicBot — MB-01: MusicBrainz Artist-Mismatch durch Titel-dominierte Gewichtung

> Live entdeckt bei einem vom Nutzer initiierten Test-Download (isolierte
> Testumgebung) am 2026-08-26, direkt im Anschluss an TESTENV-01.

**Status: MB-01 — ABGESCHLOSSEN (committed).**

---

## 1. Finding

**ID:** MB-01 — P0 (Metadata, MusicBrainz-Integration, Cover-Art) —
`MusicBrainzClient._get_best_match()` kann einen Track fälschlich einem
komplett anderen Künstler zuordnen, wenn nur der Titel zufällig
übereinstimmt.

**Live reproduziert:** YouTube-Titel „Yearboox - Graceland (Club Edit)"
(echter Künstler „Yearboox") wurde MusicBrainz-Aufnahme
„sweetbox – Graceland" zugeordnet — ein völlig unverwandter Künstler, der
zufällig ebenfalls einen Song „Graceland" hat:

```
similarity("Graceland", "Graceland")  = 1.0   (title_sim)
similarity("Yearboox", "sweetbox")    = 0.5   (artist_sim, rein zufällige
                                                "box"-Endungs-Übereinstimmung)
score (alt) = 1.0*0.7 + 0.5*0.3 = 0.85  ≥ 0.70-Schwelle → fälschlich akzeptiert
```

**Konsequenz im echten Testlauf:** Die vier MusicBrainz-IDs
(recording/release/release_group/artist), die dem Track final
angehängt wurden, gehörten **alle zu sweetbox**, nicht zu Yearboox. Die
darüber aufgelöste Cover-Art (Quelle: `coverartarchive`, via sweetbox-
`release_group_id`) und das Jahr wurden dadurch mit hoher
Wahrscheinlichkeit falsch zugeordnet. Artist-/Title-Tag blieben davon
unberührt (kommen aus dem YouTube-Titel-Parser, nicht aus MusicBrainz).

**Root Cause:** `_get_best_match()` gewichtete `score = title_sim*0.7 +
artist_sim*0.3` — bei einem exakten Titeltreffer (`title_sim=1.0`) liefert
allein der Titel-Anteil bereits `0.7`, **exakt** die
`Config.MUSICBRAINZ_MIN_SIMILARITY`-Schwelle (0.7). Ein völlig falscher
Künstler konnte die Schwelle dadurch mit praktisch **jedem** `artist_sim
> 0` überwinden — es gab keine eigenständige Mindestanforderung an die
Artist-Ähnlichkeit.

**Zusätzlicher Nebenbefund (gleiche Datei):** `Config.MUSICBRAINZ_TITLE_WEIGHT`
und `Config.MUSICBRAINZ_ARTIST_WEIGHT` (beide `0.5`) existieren bereits in
`config.py`, wurden aber nirgends gelesen — `_get_best_match()` hatte die
Gewichtung `0.7`/`0.3` hartcodiert. Gleiche Kategorie wie bereits mehrfach
in dieser Session gefundene tote Config (z.B. Filename-Templates,
`MAX_DURATION`-Key).

---

## 2. Vor-Fix-Diskriminierung

`tests/test_musicbrainz_client_artist_mismatch.py` gegen den ungefixten
Code: **1 failed, 7 passed**. Fehlgeschlagen (diskriminierend): der reale
Yearboox/sweetbox-Fall. Bereits vorher grün: alle Überkorrektur-Schutz-
Fälle (Featuring-Credit-Abweichung, Kollaborations-Credit, Case/Spacing-
Varianten, normalisierter Exakt-Treffer, bestehender dokumentierter
Hochscore-Fall) sowie der Zahlen-Beleg (`similarity()`-Werte selbst).

---

## 3. Fix

**`config.py`:** neue Konstante `MUSICBRAINZ_MIN_ARTIST_SIMILARITY = 0.55`
— kalibriert gegen reale Kollaborations-/Schreibweisen-Fälle, die
weiterhin durchgelassen werden müssen:

```
"Travis Scott" vs. "Travis Scott feat. Drake"  -> 0.667  (muss durchgehen)
"Peter Fox" vs. "Peter Fox, Inez"              -> 0.750  (muss durchgehen)
"Yearboox" vs. "sweetbox"                      -> 0.500  (muss abgelehnt werden)
```

**`services/clients/musicbrainz_client.py::_get_best_match()`:**

```diff
+            normalized_artist_match = False
+            if hasattr(self, "artist_normalizer"):
+                normalized_rec_artist = self.artist_normalizer.normalize(rec_artist_phrase)
+                normalized_clean_artist = self.artist_normalizer.normalize(clean_artist)
+                normalized_artist_match = (
+                    normalized_rec_artist == normalized_clean_artist
+                    and normalized_rec_artist != "Unknown"
+                )
+
+            if artist_sim < min_artist_similarity and not normalized_artist_match:
+                continue
+
-            score = (title_sim * 0.7) + (artist_sim * 0.3)
+            score = (
+                title_sim * Config.MUSICBRAINZ_TITLE_WEIGHT
+                + artist_sim * Config.MUSICBRAINZ_ARTIST_WEIGHT
+            )
             if clean_artist.lower() == rec_artist_phrase.lower():
                 score += 0.1
-            if hasattr(self, "artist_normalizer"):
-                normalized_rec_artist = self.artist_normalizer.normalize(rec_artist_phrase)
-                normalized_clean_artist = self.artist_normalizer.normalize(clean_artist)
-                if (
-                    normalized_rec_artist == normalized_clean_artist
-                    and normalized_rec_artist != "Unknown"
-                ):
-                    score += 0.05
+            if normalized_artist_match:
+                score += 0.05
```

Kandidaten mit `artist_sim` unterhalb der neuen Mindestschwelle werden
verworfen — **außer** die kanonisierten (ArtistNormalizer-normalisierten)
Namen stimmen exakt überein (stärkeres Signal als reine Rohstring-
Ähnlichkeit, deckt z.B. stark abweichende Schreibweisen ab, die dieselbe
kanonische Form ergeben). Die Normalizer-Prüfung wurde dafür einmalig
vorgezogen (vorher nur als Bonus-Berechnung weiter unten) und für Gate
und Bonus gemeinsam genutzt. Zusätzlich: die hartcodierte 0.7/0.3-
Gewichtung durch die bereits existierenden, bisher toten Config-
Konstanten ersetzt (jetzt 0.5/0.5, wirksam).

**Geänderte Dateien:** `config.py` (eine neue Konstante),
`services/clients/musicbrainz_client.py` (`_get_best_match()`).

**Neue Tests:** `tests/test_musicbrainz_client_artist_mismatch.py` — 8
Tests: 3 Kernfälle (Yearboox/sweetbox abgelehnt, Zahlen-Beleg, korrekter
Kandidat gewinnt weiterhin gegen falschen), 5 Überkorrektur-Schutz-Tests
(Featuring-Credit, Kollaborations-Credit, Case/Spacing, normalisierter
Exakt-Treffer trotz niedriger Rohähnlichkeit, bestehender dokumentierter
Fall).

---

## 4. Testergebnisse

```
STUFE 1 (gezielt):
tests/test_musicbrainz_client_artist_mismatch.py:  8 passed

STUFE 2 (direkte Regression):
tests/test_musicbrainz_client.py:                 28 passed

STUFE 3 (thematische Suite):
238 passed, 11 subtests passed

STUFE 4 (vollständige Suite, am Ende der Arbeitsphase):
1258 passed, 1 warning (vorbestehend, unabhängig), 19 subtests passed
(Baseline vor diesem Fix: 1250 passed → +8 neue Tests, 0 Regressionen)
```

---

## 5. Scope-Bestätigung

Geänderte Dateien: `config.py` (eine neue Konstante, zwei vorhandene
Konstanten erstmals genutzt), `services/clients/musicbrainz_client.py`
(ausschließlich `_get_best_match()`). Keine Änderung an `fetch_metadata()`,
`_build_metadata()`, `parse_search_terms()` oder anderen Metadata-Modulen.

---

## 6. Abschluss

MB-01 gilt hiermit als **abgeschlossen**. Root Cause vollständig
identifiziert und mit den exakten, real beobachteten Ähnlichkeitswerten
belegt, Vor-Fix-Diskriminierung erfolgreich, Fix minimal und gegen reale
Kollaborations-/Schreibweisen-Fälle kalibriert, vollständige Suite grün
(1258 passed, 0 failed, 0 errors). Dritter unabhängiger Fund aus der vom
Nutzer initiierten Test-Download-Serie (nach META-11 und TESTENV-01) —
weiterer Beleg für den Wert dieser Vorgehensweise. Commit/Push/PR/Merge
auf explizite Nutzerfreigabe hin durchgeführt (siehe Git-Historie).
