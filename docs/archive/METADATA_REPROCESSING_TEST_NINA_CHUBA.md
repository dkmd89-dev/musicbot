# MusicBot — Zweiter Validierungslauf des offiziellen Reprocessing-Tools: Nina Chuba

> Zweiter, unabhängiger Validierungslauf von `scripts/reprocess_artist_metadata.py`
> (nach dem ersten, in [`docs/archive/METADATA_REPROCESSING_TEST_CHAPO102.md`](METADATA_REPROCESSING_TEST_CHAPO102.md)
> dokumentierten CHAPO102-Lauf), diesmal gegen eine deutlich größere, reale
> Mehr-Album-Discographie (39 Dateien, 6 Alben/EPs + Singles-Ordner) statt
> einer reinen Singles-Sammlung. Durchgeführt am 2026-08-31.

**Status: PASS WITH UNRESOLVED CASES**

---

## 1. Testziel

Das mit CHAPO102 validierte, offizielle Reprocessing-Tool an einem
strukturell komplexeren, realen Artist-Bestand erneut prüfen — insbesondere
an Album-/EP-Verzeichnissen (Track-Nummer-basierte Dateinamen, mehrere
Genre-/MusicBrainz-/Cover-Zustände) statt nur Singles.

## 2. Input

```text
/tmp/musicbot_test/metadaten/Nina Chuba/
├── 2020 - Power EP/            (6 Dateien)
├── 2022 - Wildberry Lillet (Remix EP)/  (2 Dateien)
├── 2023 - Glas/                (16 Dateien)
├── 2024 - Farbenblind EP/      (7 Dateien)
└── Singles/                    (7 Dateien, inkl. eines echten Duplikat-Paars
                                  "Ende.m4a" / "Ende (1).m4a" mit
                                  unterschiedlicher Dateigröße)
```

39 Dateien gesamt, vom Nutzer manuell aus der Produktions-Library kopiert
(nach expliziter Rückfrage, siehe Session-Verlauf — kein eigenmächtiges
Kopieren durch Claude).

## 3. Waehrend dieses Laufs entdeckte und behobene Fehler im Tool selbst

Der erste Dry-Run gegen diesen strukturell neuen Bestand deckte zwei reale,
zuvor durch CHAPO102 (reine Singles) nicht abgedeckte Lücken auf, sowie ein
weiterer, erst im anschließenden Live-Lauf sichtbarer Fund — alle vor dem
finalen Live-Lauf bzw. sofort danach behoben:

### 3.1 Album- vs. Singles-Dateinamenskonvention (vor dem ersten Live-Versuch)

Die ursprüngliche Implementierung wandte die Singles-Konvention
(`"{Jahr} - {Titel}.ext"`) blind auf **jede** Datei an. CHAPO102 bestand
ausschließlich aus Singles und deckte das nie ab — bei Nina Chuba hätte das
jeden Album-Track (Dateiname `"{Tracknummer} - {Titel}"`, z. B.
`"01 - Lips Shut.m4a"`) fälschlich in die Jahres-Konvention umbenannt.
**Fix:** Unterscheidung anhand des tatsächlichen Parent-Ordnernamens
(`"Singles"`) bzw. des tatsächlich vorhandenen `trkn`-Tags — kein Raten,
kein Rename-Versuch bei fehlender Tracknummer.

### 3.2 ARTISTS-Freeform-Feld enthielt vollständigere Information als ©ART

Real bei `"Verlaufen feat. SIDO.m4a"` entdeckt: `©ART` enthielt nur
`['Nina Chuba']`, das `----:com.apple.iTunes:ARTISTS`-Freeform-Feld aber
`['Nina Chuba; SIDO']` (ein zusammengeklebter Wert, TAG-01-Altlast — SIDO
fehlte im Standard-Tag komplett). **Fix:** beide Quellen werden jetzt
gemeinsam an die bestehende `flatten_existing_artists()`-Logik übergeben.

### 3.3 Dry-Run zeigte keine vorhergesagten Änderungen

`--dry-run` setzte `after` bisher als reine Kopie von `before` — die
`CHANGES`-Sektion war dadurch in jedem Dry-Run leer, unabhängig davon, was
die Pipeline tatsächlich ermittelt hätte (verletzt die Anforderung
"geplante Metadata-Änderungen analysieren, soweit möglich"). **Fix:** ein
`after`-Dict wird jetzt aus den tatsächlich ermittelten Pipeline-Ergebnissen
vorhergesagt (unter Nachbildung von TagWriters bedingtem Schreibverhalten),
klar als Vorhersage gekennzeichnet, ohne dass etwas geschrieben wird.

### 3.4 Rename trotz UNRESOLVED-Titel-Zeichen-Konflikt durchgeführt (im Live-Lauf aufgetreten)

Trotz Punkt 3.3 wurde im anschließenden **Live-Lauf** ein Rename real
ausgeführt, obwohl der Titel `"F*cked Up"` bereits als `UNRESOLVED`
("Zeichen nicht dateinamens-darstellbar") erkannt wurde — Ergebnis:
`"2025 - Fcked Up.m4a"` (Original, "*" einfach weggelassen) wurde zu
`"2025 - F cked Up.m4a"` (Leerzeichen statt "*", **schlechter** als das
Original). Sofort nach Entdeckung manuell zurückbenannt (Audio-Essenz per
`ffmpeg -map 0:a -f md5` gegen das unveränderte Original verifiziert:
identisch) und im Tool behoben: ein Titel mit dateinamens-illegalen
Zeichen blockiert den Rename jetzt aktiv, nicht nur die UNRESOLVED-Meldung.

### 3.5 „Overall: FAIL" durch legitime Same-Directory-Renames

Der automatische Post-Run-Safety-Check zählte jeden Rename (Create+Delete-
Paar im rohen Verzeichnis-Snapshot-Diff) unconditional als Strukturbruch,
auch wenn beide Ereignisse im selben Verzeichnis stattfanden (die
Rename-Logik selbst garantiert bereits Parent-Gleichheit). Der erste
Live-Lauf meldete deshalb fälschlich `Overall: FAIL` trotz nachweislich
unveränderter Verzeichnisstruktur. **Fix:** Creates/Deletes werden jetzt
pro Verzeichnis gruppiert (`Counter`) verglichen — nur ein tatsächliches
Ungleichgewicht pro Verzeichnis gilt als Strukturbruch.

Für alle vier Funde wurden Regressionstests ergänzt
(`tests/test_reprocess_artist_metadata.py`, u. a.
`TestAlbumVsSinglesFilenameConvention`,
`test_freeform_artists_field_merged_when_more_complete_than_standard_tag`,
`test_dry_run_predicts_changes_without_writing`,
`test_rename_blocked_when_title_has_filename_illegal_characters`).

## 4. Dry-Run (nach den Fixes 3.1–3.3)

38/39 mit vorhergesagten Änderungen (überwiegend MusicBrainz-ID-Ergänzung
und Cover-Aktualisierung), 1/39 bereits vollständig aktuell. Alle 39
korrekt als `UNRESOLVED` (fehlendes ReplayGain) markiert. Der
"Ende"/"Ende (1)"-Kollisionsfall korrekt als geplant-aber-blockiert
erkannt. Keine Datei verändert (verifiziert: mtime + Audio-Essenz-Hash vor
und nach dem Dry-Run identisch).

## 5. Live-Lauf — Ergebnis

```text
Files processed: 39
Changed: 38
Unchanged: 1
Unresolved: 39
Errors: 0
```

**Multi-Artist (TAG-01-Validierung):** `"Verlaufen feat. SIDO.m4a"` —
final verifiziert (read-only, nach dem Lauf):
`©ART=['Nina Chuba','Sido']`, `ARTISTS-Freeform=['Nina Chuba','Sido']`,
`album_artist=['Nina Chuba']`. (ArtistNormalizer korrigierte dabei die
Schreibweise "SIDO" → "Sido" — Produktionslogik, keine neue Regel.)

**Dateinamenänderung:** genau eine, `"2024 - Fata Morgana.m4a"` →
`"2025 - Fata Morgana.m4a"` (Jahres-Tag war 2025, Dateiname noch 2024 —
korrekt über die Singles-Konvention erkannt und behoben).

**Kollisionsschutz:** `"Ende (1).m4a"` (2.944.258 Bytes) und `"Ende.m4a"`
(2.944.127 Bytes) — echte, unterschiedliche Dateien, kein Rename versucht
(beide würden auf denselben Zieldateinamen abbilden), beide unverändert
unter ihrem ursprünglichen Namen erhalten geblieben, kein Datenverlust.

**Unresolved:** alle 39 Dateien — ReplayGain/Loudness fehlt in der
gesamten Nina-Chuba-Discographie (vordatiert diese Funktion), keine
Nachrüstung durchgeführt (verlustbehaftetes Re-Encoding wäre nötig,
außerhalb des Scopes).

## 6. Post-Run Safety Check (nach Fix 3.5, unabhängig nachverifiziert)

```text
Production files changed: 0/39   (SHA256 + mtime, rein lesend)
Directory structure changes: 0
Files created: 1 / Files deleted: 1 (Fata-Morgana-Rename, selbes Verzeichnis)
Audio essence changes: 0/39      (ffmpeg -map 0:a -f md5 gegen unveraenderte
                                   Produktionsoriginale, alle 39 identisch)
Audio stream (codec/rate/channels/duration) changes: 0
```

## 7. Tests

`tests/test_reprocess_artist_metadata.py`: 39 passed (von zuvor 34 auf 39
erweitert um die vier neuen Regressionsfälle aus Abschnitt 3). Direkte
Regression (TagWriter/Config-Isolation): 37 passed. Vollständige Suite:
1306 passed, 8 failed — die 8 Fehlschläge sind ein bereits vor dieser
Arbeit bestehender, unabhängiger Syntaxfehler in einem uncommitted lokalen
Edit von `mapping/artist_genre.yaml` (Zeile 111), nicht durch dieses Tool
verursacht (siehe `docs/archive/METADATA_REPROCESSING_TEST_CHAPO102.md` bzw.
Session-Historie — nicht behoben, außerhalb des Scopes).

## 8. Finale Bewertung

```text
PASS WITH UNRESOLVED CASES
```

Begründung: keine Produktionsänderungen, keine Verzeichnisstruktur-
Änderungen, keine Audio-Stream-/Essenz-Änderungen, Metadata-Pipeline über
eine strukturell deutlich komplexere reale Discographie erfolgreich
validiert, vier real entdeckte Tool-Fehler noch während dieses Laufs
gefunden, behoben und regressionsgetestet, 39 Dateien bewusst wegen
fehlendem ReplayGain als UNRESOLVED dokumentiert statt verlustbehaftet
nachcodiert.

---

## 9. Nachtrag — Final Audit: Genre-Konsistenz und UNRESOLVED-Praezisierung

Im Rahmen eines abschließenden Audits (nach dem Mapping-Audit-Commit
`f7cdf59`) wurden zwei weitere reale Funde gemacht und behoben, dann durch
einen DRITTEN Lauf gegen denselben Nina-Chuba-Bestand verifiziert.

### 9.1 UNRESOLVED faelschlich bei harmloser Feat-Notation-Reformatierung

`check_unresolved()` verglich `sanitize_filename(clean_title) != clean_title`
generisch - das erfasste nicht nur echte illegale Zeichen
(`ILLEGAL_CHARS_PATTERN`), sondern auch die davon unabhaengige, bereits in
der Produktions-Pipeline vorgesehene `FEAT_NOTATION_PATTERN`-Umformatierung
(`"(feat. X)"` → `"feat. X"`). Real bei `"Verlaufen (feat. SIDO)"`
ausgeloest: faelschlich als UNRESOLVED gemeldet, obwohl die Umformatierung
sicher und beabsichtigt ist. **Fix:** beide Pruefungen (UNRESOLVED-Meldung
und Rename-Block) verwenden jetzt ausschließlich `ILLEGAL_CHARS_PATTERN`
direkt statt der vollen `sanitize_filename()`-Transformation. Zwei neue
Tests (`test_feat_notation_parens_not_flagged`,
`test_rename_proceeds_for_harmless_feat_notation_reformatting`).

### 9.2 Isolierte Test-Mapping-Kopie war stale (Root Cause der Genre-Inkonsistenz)

Der ELF-vermeintliche "Genre-Inkonsistenz"-Befund (`Pop; Hip Hop;
Deutschpop` / `Hip Hop / Deutschrap / Pop Rap / R&B` / `Hip Hop` / `Pop,
Hip Hop, Deutschpop` - vier verschiedene Formate ueber 39 Dateien) war
**kein Fehler im Reprocessing-Tool oder in GenreProcessor/GenreMapper**,
sondern eine stale isolierte Test-Mapping-Kopie: `config_test.py::
_prepare_isolated_mapping_dir()` kopiert `mapping/` nur EINMALIG nach
`/tmp/musicbot_test/mapping` (bei bereits existierendem Zielverzeichnis
sofortiger Return, siehe Docstring: "der naechste Start kopiert dann
automatisch wieder frisch" - nur nach `run_test_bot.py --clean`). Die
isolierte Kopie enthielt dadurch noch die VOR dem Mapping-Audit-Commit
kaputte `artist_genre.yaml` - `get_artist_entry("nina chuba")` lieferte
`None`, jeder Track fiel auf einen inkonsistenten Fallback-Pfad
(MusicBrainz pro Recording / unveraenderter Alt-Wert) zurueck, statt
einheitlich die manuelle Nina-Chuba-Zuordnung zu erhalten.

**Fix (Testumgebung, kein Code-Fix):** `mapping/artist_genre.yaml` und
`mapping/case_preserve.yaml` (die beiden durch den Mapping-Audit
geaenderten Dateien) manuell in die isolierte Kopie synchronisiert.
`known_artists.yaml`/`auto_learned_genre.yaml` bewusst NICHT ueberschrieben
(enthalten echte, waehrend der Testlaeufe entstandene Auto-Learn-Daten,
nicht Teil des Mapping-Audits).

**Verifiziert (dritter Lauf, echt, Datei erneut von Platte gelesen):**

```text
BEFORE (4 verschiedene Formate ueber 39 Dateien):
  33x  'Pop; Hip Hop; Deutschpop'
   2x  'Hip Hop / Deutschrap / Pop Rap / R&B'
   3x  'Hip Hop'
   1x  'Pop, Hip Hop, Deutschpop'

GenreProcessor-Quelle (alle 39 Dateien, echter Lauf):
  source: artist_exact_manual
  result: primary='Hip Hop' secondary=['Deutschrap','Pop Rap','R&B','Alternative Pop']

AFTER (re-read von Platte, alle 39 Dateien):
  39x  'Hip Hop / Deutschrap / Pop Rap / R&B'
```

**Post-Run Safety Check (dritter Lauf):** Production files changed: 0/39,
Directory structure changes: 0, Audio essence changes: 0/39 (unabhaengig
per `ffmpeg -map 0:a -f md5` gegen die unveraenderten Produktionsoriginale
verifiziert), TAG-01 (SIDO) weiterhin korrekt getrennt
(`©ART=['Nina Chuba','Sido']`). Volle Testsuite: 1316 passed, 0 failed
(2 neue Tests aus 9.1).

**Ergebnis:** Der Fund bestaetigt genau das, was das Reprocessing-Tool
demonstrieren soll - ein bestehender, inkonsistent getaggter Artist-
Bestand wird durch die bestehende, unveraenderte
GenreProcessor-/GenreMapper-Logik (kein neuer Code, keine parallele
Genre-Implementierung) konsistent auf das kanonische Artist-Genre-Mapping
normalisiert, sobald diesem Mapping ein gueltiger, aktueller Zustand
zugrunde liegt.
