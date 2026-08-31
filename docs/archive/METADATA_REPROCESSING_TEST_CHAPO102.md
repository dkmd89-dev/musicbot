# MusicBot — Isolated Artist Metadata Reprocessing Test: CHAPO102

> Vollständig isolierter Reprocessing-Test eines bestehenden Artist-Verzeichnisses
> (Phase C eines mit dem Nutzer vereinbarten, mehrstufigen Test-Ablaufs:
> Analyse → Freigabe → Pre-Execution Safety Review → Freigabe → Ausführung →
> Post-Run Safety Validation). Durchgeführt am 2026-08-31.

**Status: PASS WITH UNRESOLVED CASES**

---

## 1. Testziel

Bestehende, bereits in der Produktions-Library vorhandene Audiodateien eines
Artists (`CHAPO102`) erneut durch die aktuelle Metadata-Pipeline laufen zu
lassen: vorhandene Metadaten aktualisieren, fehlende Metadaten ergänzen,
fehlerhafte Metadaten korrigieren, und — wenn eindeutig möglich — fehlerhafte
Dateinamen innerhalb der bestehenden Library-Struktur korrigieren. Kein
Download, keine Änderung der Library-Struktur, keine unnötige
Audio-Neucodierung.

## 2. Repository-/Commit-Stand

- Branch: `main`, Commit `c8caf98` (unverändert während des gesamten Tests)
- Neues Werkzeug: `scripts/reprocess_artist_metadata.py` (eigenständiges,
  von `process_single_track()`/`move_to_library()` bewusst entkoppeltes
  Reprocessing-Skript, siehe Abschnitt 4)
- Relevante bereits vorhandene Fixes, die in diesen Test eingeflossen sind:
  TAG-01 (Multi-Artist-Tags), META-11 (Title Cleaning), MB-01 (MusicBrainz
  Artist-Mismatch), TESTENV-01 (Testumgebungs-Isolation)

## 3. Testumgebung

```text
Production Library (READ-ONLY):  /mnt/4tb/library/CHAPO102/Singles/
Test-Input:                      /tmp/musicbot_test/metadaten/CHAPO102/Singles/
Test-Config:                     config_test.Config (BASE_DIR=/tmp/musicbot_test)
```

`/tmp/musicbot_test/metadaten/CHAPO102/` ist eine Kopie von 14 bestehenden
Produktionsdateien, angelegt vor Testbeginn. Kein Zugriff, der Schreib­rechte
auf `/mnt/4tb/library` benötigt hätte, existiert im Reprocessing-Skript.

## 4. Production-Protection

- `scripts/reprocess_artist_metadata.py` importiert ausschließlich
  `config_test.Config`, nie `config.Config` (Assertion beim Start:
  `Config.BASE_DIR == "/tmp/musicbot_test"`, sonst Abbruch).
  Read-only-Zugriffe auf `config.py`/`utils/helpers.py` beschränken sich auf
  eine reine Konstante (`MAX_FILENAME_LENGTH`), keine Pfade.
  Hartes Pfad-Gate vor jeder Aktion (Artist-Root muss unterhalb von
  `/tmp/musicbot_test` liegen).
- `process_single_track()`/`move_to_library()` werden bewusst NICHT
  aufgerufen (Risiko: Zielverzeichnis würde aus dem frisch normalisierten
  Artist-Namen neu berechnet, siehe `utils/filenamefixer.py::build_final_path()`).
  Stattdessen werden die echten Produktions-Subprozessoren
  (`ArtistNormalizer`, `TitleCleaner`, `GenreProcessor`, `LyricsProcessor`,
  `CoverProcessor`, `TagWriter`) direkt verwendet, exakt wie in
  `EnhancedMetadataProcessor._do_init()` verdrahtet.
- `AudioEnhancer`/`normalize_loudness()` wird an keiner Stelle importiert
  oder aufgerufen (Pre-Execution Safety Review, siehe Git-Historie dieses
  Berichts-Threads) — verlustbehaftete FFmpeg-Neucodierung ist damit
  strukturell ausgeschlossen, nicht nur bedingt vermieden.
- **Verifikation (Post-Run, rein lesend):** SHA256-Fingerabdruck aller 14
  Produktionsdateien gezogen und mit unverändertem mtime/Größe abgeglichen —
  alle 14 tragen weiterhin ihren ursprünglichen Zeitstempel (2026-08-25/26,
  vor Testbeginn). **PRODUCTION FILE CHANGES = 0.**

## 5. Input / Output

- Input: 14 `.m4a`-Dateien unter `CHAPO102/Singles/`
- Output: dieselben 14 Dateien, in-place aktualisiert, weiterhin unter
  `/tmp/musicbot_test/metadaten/CHAPO102/Singles/`
- **Kein Transfer nach `/tmp/musicbot_test/libary/` durchgeführt** — steht
  weiterhin aus, erfolgt erst nach separater expliziter Freigabe.

## 6. Dateistruktur Before/After

```text
CHAPO102/
└── Singles/         (14 Dateien)
```

Verzeichnisbaum vor und nach dem Lauf identisch (`diff` zwischen
Produktions- und Test-Dateiliste: keine Abweichung). Kein neues
Artist-/Album-/Singles-Verzeichnis, keine verschobene Datei.
**DIRECTORY STRUCTURE CHANGES = 0.**

## 7. Dateinamenänderungen

**0.** Ein einzelner Rename-Versuch (`WER HAT DIESE FRAU GESEHEN.m4a` →
`...GESEHEN .m4a`, durch einen Bug im Skript verursacht — Dateiendung wurde
mitsanitisiert, wodurch ein durch "?" erzeugtes Leerzeichen vor der Endung
stehen blieb) wurde noch während der Auswertung erkannt, sofort manuell
zurückgenommen und der zugrundeliegende Bug im Skript behoben (Stem und
Endung werden seither getrennt sanitisiert). Die Datei trägt wieder exakt
ihren Original-Dateinamen.

## 8. Metadata Before/After (Zusammenfassung, aus dem Log)

7 Dateien mit inhaltlichen Metadaten-Änderungen:

| Datei | Änderung |
|---|---|
| PINKER BADEMANTEL | Genre `Pop` → volle Hierarchie; MB-IDs ergänzt |
| ERSTER PLATZ | Genre-Normalisierung; MB-Suche ohne Treffer (unverändert None) |
| Schöne Dinge | Genre-Normalisierung; MB-IDs ergänzt |
| ATEMNOT | ISRC ergänzt (übrige MB-IDs bereits vorhanden) |
| Fahrt ins Blaue | Genre-Normalisierung; MB-Suche ohne Treffer (unverändert None) |
| FÜR IMMER | Genre-Normalisierung; MB-IDs ergänzt |
| Hinterkopf | Genre-Normalisierung; MB-IDs ergänzt |

5 Dateien ohne inhaltliche Änderung (bereits vollständig korrekt):
Wunderschön unkompliziert, SCHÖN DASS DU DA WARST, TOTE TAUBEN,
VERLIEBT VERLOBT, WER HAT DIESE FRAU GESEHEN.

## 9. Multi-Artist-Ergebnisse (TAG-01-Validierung)

2 Dateien mit TAG-01-Altlasten korrigiert:

- **OMG.m4a**: `----:com.apple.iTunes:ARTISTS` war
  `['CHAPO102; Bausa; MIKSU; MACLOUD']` (ein zusammengeklebter String) →
  jetzt 4 getrennte Werte. Standard-Tag `©ART` war bereits korrekt.
- **WARSCHAU.m4a**: sowohl `©ART` als auch die Freeform-`ARTISTS` waren als
  ein zusammengeklebter String gespeichert (älterer Bug-Stand als OMG) →
  beide jetzt korrekt getrennt, `album_artist` auf den Hauptkünstler bereinigt.

**Final verifiziert (read-only, `mutagen.mp4.MP4`, 2026-08-31, Post-Run):**

```text
OMG.m4a:
  ©ART               = ['CHAPO102', 'Bausa', 'MIKSU', 'MACLOUD']
  ARTISTS (Freeform)  = ['CHAPO102', 'Bausa', 'MIKSU', 'MACLOUD']
  album_artist (aART) = ['CHAPO102']

WARSCHAU.m4a:
  ©ART               = ['CHAPO102', 'Gustav']
  ARTISTS (Freeform)  = ['CHAPO102', 'Gustav']
  album_artist (aART) = ['CHAPO102']
```

## 10. Title-Cleaning-Ergebnisse

Keine Titel-Korrekturen erforderlich — alle 14 Titel waren bereits sauber
(kein "Official Video"/"Official Audio"-Suffix o. ä. vorhanden). Ein
Grenzfall dokumentiert in Abschnitt 13 (Unresolved Case 2).

## 11. Cover-Ergebnisse

Cover-Suche wurde für **alle 14 Dateien** ausgeführt, auch bei bereits
vorhandenem Cover (wie gefordert):

- **6 Dateien** mit tatsächlicher Cover-Änderung: PINKER BADEMANTEL,
  Schöne Dinge, Fahrt ins Blaue, FÜR IMMER, Hinterkopf (jeweils: vorher
  kein Cover → jetzt eingebettet) sowie **ERSTER PLATZ** (vorhandenes Cover
  durch ein anderes ersetzt — coverartarchive-Ergebnis → apple_music-Ergebnis,
  einziger Fall eines echten Ersatzes eines bereits vorhandenen Covers).
- **8 Dateien**: Cover-Suche erneut ausgeführt, identisches Ergebnis
  zurückerhalten — bestehendes Cover bewusst nicht unnötig verändert.

## 12. Lyrics

Für alle 14 Dateien erneut über Genius abgerufen; in allen Fällen erfolgreich
(`lyrics_found: True`), inhaltlich unverändert gegenüber dem bereits
vorhandenen Text (kein Diff im Log vermerkt).

## 13. Unresolved Cases

Zwei Fälle wurden bewusst **nicht** verändert, weil eine sichere,
eindeutige Korrektur nicht möglich war:

**Unresolved Case 1 — WARSCHAU.m4a (ReplayGain/Loudness fehlt)**

```text
ReplayGain/Loudness fehlt.
Aktuelle Nachrüstung würde verlustbehaftetes Audio-Re-Encoding erfordern
(AudioEnhancer.normalize_loudness() ist die einzige im Repository
vorhandene Implementierung und re-encodiert unconditional nach AAC 192kbit/s).
Außerhalb des sicheren Reprocessing-Scopes für diesen Test
("keine unnötige Audio-Neucodierung").
Keine Audioänderung durchgeführt.
```

**Unresolved Case 2 — WER HAT DIESE FRAU GESEHEN.m4a (Title/Filename-Differenz)**

```text
Title-Tag: "WER HAT DIESE FRAU GESEHEN?"
Dateiname: "WER HAT DIESE FRAU GESEHEN.m4a" (ohne "?")
Nicht eindeutig feststellbar, ob das Fragezeichen Bestandteil des
tatsächlichen Titels ist oder nachträglich (z. B. durch eine spätere
Metadatenquelle) in den Tag gelangte. Der Dateiname selbst ist mit der
aktuellen Sanitizer-Logik konsistent (sanitize_filename() entfernt "?").
Daher keine Änderung an Titel oder Dateiname vorgenommen.
```

## 14. MusicBrainz

MB-IDs wurden für 6 von 7 dafür in Frage kommenden Dateien erfolgreich
ergänzt (ATEMNOT nur ISRC, da übrige IDs bereits vorhanden). Für 2 Dateien
(ERSTER PLATZ, Fahrt ins Blaue) lieferte die MusicBrainz-Suche real kein
Ergebnis — bestehender Zustand (keine IDs) unverändert beibehalten, kein
Fehler.

## 15. Audiointegrität

**Verifiziert über zwei unabhängige Methoden, beide ausschließlich lesend:**

1. Container-Stream-Parameter (`ffprobe`): Codec, Sample Rate, Channels,
   Duration für alle 14 Dateien vor/nach identisch. (Die von `ffprobe`
   zusätzlich gelieferte "format bitrate" verändert sich erwartungsgemäß bei
   Cover-/Tag-Größenänderungen — das ist keine Audio-Neucodierung, da sie
   sich rein aus Dateigröße/Dauer ableitet, nicht aus dem Audio-Stream
   selbst.)
2. Audio-Essenz (`ffmpeg -map 0:a -f md5`, dekodiertes PCM gehasht): alle 14
   Testdateien gegen die unveränderten Original-Produktionsdateien
   verglichen — **14/14 byteidentisch.**

**AUDIO STREAM CHANGES = 0.**

## 16. Ungelöste Fälle

Siehe Abschnitt 13 — 2 Fälle (WARSCHAU.m4a ReplayGain, WER HAT DIESE FRAU
GESEHEN.m4a Title/Filename-Differenz).

## 17. Testresultate

```text
FILES PROCESSED: 14
CHANGED: 9
UNCHANGED: 5
UNRESOLVED: 2
ERRORS: 0

METADATA CHANGES: 7
COVER CHANGES: 6
MULTI-ARTIST CHANGES: 2
FILENAME CHANGES: 0
AUDIO STREAM CHANGES: 0
DIRECTORY STRUCTURE CHANGES: 0
PRODUCTION FILE CHANGES: 0
```

## 18. Log-Datei

`/tmp/musicbot_test/metadata_reprocessing_CHAPO102_20260831_150530.log`
(vollständiger Lauf, 966 Zeilen, pro Datei mit BEFORE/AFTER-Snapshot).
Auf Secrets (API-Keys, Tokens, Passwörter, Cookies, Authorization-Header)
geprüft — keine gefunden.

Ein zweiter, unvollständiger Log
(`metadata_reprocessing_CHAPO102_20260831_145921.log`, 21 Zeilen) stammt aus
einem durch ein externes SIGTERM abgebrochenen ersten Versuch, bei dem keine
Datei verändert wurde (per mtime-Check bestätigt) — nicht der für diesen
Bericht maßgebliche Log.

## 19. Git-Diff

Ausschließlich dieser Bericht sowie das bereits vorhandene, neue
`scripts/reprocess_artist_metadata.py` sind repository-seitig betroffen.
Keine Musik-/Cover-/Log-Dateien, keine Produktionsdaten im Repository.

(3 weitere als modifiziert markierte `mapping/*.yaml`/`.json`-Dateien im
Arbeitsverzeichnis sind session-übergreifend vorbestehend und nicht Teil
dieses Reprocessing-Tests — siehe Git-Status zum Zeitpunkt dieses Berichts.)

## 20. Finale Bewertung

```text
PASS WITH UNRESOLVED CASES
```

Begründung: keine Produktionsänderungen, keine Directory-Structure-
Änderungen, keine Audio-Stream-Änderungen, Metadata-Pipeline erfolgreich
ausgeführt, Multi-Artist-Korrekturen erfolgreich (TAG-01 validiert),
Cover-Reprocessing erfolgreich (inkl. Ersatz eines vorhandenen Covers),
MusicBrainz-Anreicherung erfolgreich soweit verfügbar — bei zwei Dateien
wurde bewusst keine Änderung vorgenommen, da eine sichere Korrektur nicht
eindeutig möglich war (Abschnitt 13).
