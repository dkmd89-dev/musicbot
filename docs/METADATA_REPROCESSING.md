# MusicBot — Metadata Reprocessing Tool

`scripts/reprocess_artist_metadata.py` ist das offizielle, wiederverwendbare
Werkzeug, um bestehende, bereits in der Produktions-Library vorhandene
Audiodateien eines Artists erneut durch die aktuelle MusicBot-Metadata-
Pipeline laufen zu lassen — vollständig isoliert von der Produktion.

Technische Referenz und erster, vollständig durchgeführter Validierungslauf:
[`docs/archive/METADATA_REPROCESSING_TEST_CHAPO102.md`](archive/METADATA_REPROCESSING_TEST_CHAPO102.md).

---

## 1. Zweck

Bestehende Library-Dateien altern: Genre-Mapping-Regeln, Cover-Quellen,
MusicBrainz-Daten und die Tag-Schreiblogik selbst entwickeln sich weiter
(siehe TAG-01, META-11, MB-01). Dieses Tool erlaubt es, bereits
heruntergeladene Tracks gezielt gegen den *aktuellen* Stand dieser Pipeline
zu validieren und zu aktualisieren, ohne sie neu herunterzuladen und ohne
die Produktions-Library direkt anzufassen.

## 2. Sicherheitsmodell

```text
Produktions-Library (/mnt/4tb/library)   → READ-ONLY, niemals beschrieben
Test-Input   (/tmp/musicbot_test/metadaten/<ARTIST>) → einzig erlaubter Input
Test-Output  (dieselbe Stelle, in-place aktualisiert) → einzig erlaubter Output
Test-Ziel nach manueller Pruefung (/tmp/musicbot_test/libary/<ARTIST>)
    → NIEMALS automatisch, ausschliesslich manueller Transfer nach Freigabe
```

Erzwungen durch `validate_input_path()`:

- Input muss existieren, ein Verzeichnis sein und real (`.resolve(strict=True)`,
  loest Symlinks vollstaendig auf) unterhalb von `--metadaten-root`
  (Standard `/tmp/musicbot_test/metadaten`) liegen.
- Input darf nicht die Wurzel selbst sein (ein konkretes Artist-Verzeichnis
  ist Pflicht).
- Ein expliziter, eigener Guard verweigert jeden Pfad, der (auch über einen
  Symlink) auf die Produktionsbibliothek zeigt.
- Path Traversal (`..`) wird durch `.resolve()` aufgeloest und faellt damit
  automatisch unter die obigen Grenzpruefungen.
- Jede einzelne gefundene Datei wird zusaetzlich per
  `validate_file_within_root()` erneut geprueft (Symlink-Schutz auf
  Dateiebene) — eine verdaechtige Datei wird uebersprungen und protokolliert,
  bricht aber nicht den gesamten Lauf ab.

Das Tool importiert ausschliesslich `config_test.Config` (isolierte
Testkonfiguration, siehe TESTENV-01), niemals `config.Config`. Ein Assert
beim Start verifiziert `Config.BASE_DIR == "/tmp/musicbot_test"`.

## 3. CLI

```bash
python scripts/reprocess_artist_metadata.py --input /tmp/musicbot_test/metadaten/ARTIST
```

Optionen:

| Flag | Bedeutung | Standard |
|---|---|---|
| `--input` (Pflicht) | Vollstaendiger Pfad zum Artist-Testverzeichnis | — |
| `--dry-run` | Nur analysieren, keine Datei veraendern | aus |
| `--metadaten-root` | Erlaubte Wurzel fuer `--input` | `/tmp/musicbot_test/metadaten` |
| `--production-root` | Nur-lesend fuer den automatischen Post-Run-Safety-Check | `/mnt/4tb/library` |
| `--no-production-check` | Production-Protection-Vergleich auslassen | aus |

## 4. Dry-Run

```bash
python scripts/reprocess_artist_metadata.py --input .../ARTIST --dry-run
```

Fuehrt die komplette Analyse durch (Artist-Normalisierung, Title-Cleaning,
Genre-/MusicBrainz-Anreicherung, Lyrics-Suche, Cover-Suche, geplanter
Rename) und protokolliert das Ergebnis — schreibt aber **keinen** Tag,
**kein** Cover, benennt **keine** Datei um und ruft **keine**
Audioverarbeitung auf. Nach einem Dry-Run ist die Datei byteidentisch zum
Ausgangszustand (mtime, Audio-Essenz-Hash unveraendert).

## 5. Metadata-Pipeline

Fuer jede vorhandene `.m4a`-Datei wird ausschliesslich bestehende
Produktionslogik wiederverwendet — dieselben Klassen, die
`EnhancedMetadataProcessor._do_init()` fuer den Download-Workflow
verdrahtet:

```text
Bestehende Datei
    ↓ mutagen (Read)
BEFORE SNAPSHOT
    ↓
ArtistNormalizer.normalize()           (Artist/Feature-Artists)
TitleCleaner.light_title_cleanup()     (Titel-Idempotenz-Check)
GenreProcessor.determine_genre_with_fallbacks()  (Genre + MusicBrainz-IDs)
LyricsProcessor.fetch_lyrics_with_fallback()     (Lyrics, immer neu)
CoverProcessor.get_cover_art()                   (Cover, immer neu)
    ↓
TagWriter.write_tags()                 (echter, atomarer Produktions-Writer)
    ↓ mutagen (Read, neu von Platte)
AFTER SNAPSHOT
```

**Bewusst NICHT verwendet:**
`EnhancedMetadataProcessor.process_single_track()` bzw.
`FilenameFixerTool.move_to_library()` — beide sind untrennbar mit dem
Download-Workflow verzahnt (Zielpfad-Neuberechnung aus dem frisch
normalisierten Artist-Namen, unconditional
`AudioEnhancer.normalize_loudness()`-Aufruf). Beides ist fuer Reprocessing
bestehender, bereits korrekt einsortierter Dateien nicht sicher, siehe
Abschnitt 7.

Album/Jahr werden **nicht** ueber `AlbumProcessor.determine_album_info()`
neu bestimmt (diese Methode ist fuer Download-Zeit-Metadaten aus
Playlist/yt-dlp gebaut und faellt bei fehlenden Kandidaten auf das aktuelle
Kalenderjahr zurueck) — die bereits vorhandenen Album-/Jahr-Tags werden als
Vertrauensbasis uebernommen.

## 6. Cover-Reprocessing

Die Cover-Suche laeuft fuer **jede** Datei, auch wenn bereits ein Cover
eingebettet ist — es gibt keinen Skip-Pfad. Ergebnis wird als eine von vier
Aktionen protokolliert:

- `ADD` — vorher kein Cover, jetzt eines gefunden
- `REPLACE` — vorhandenes Cover durch ein anderes ersetzt (Ranking lieferte
  einen abweichenden Treffer)
- `KEEP` — Suche lief, identisches Ergebnis wie zuvor zurückerhalten
- `UNAVAILABLE` — keine Quelle lieferte ein Cover

Es wird ausschliesslich die bestehende `CoverProcessor`-Ranking-Logik
verwendet, keine neue Vergleichslogik "altes vs. neues Cover" (die
Produktions-Pipeline kennt dieses Konzept nicht — auch beim normalen
Download wird schlicht das beste gefundene Ergebnis verwendet).

## 7. Audio-Sicherheit (absolut)

`AudioEnhancer` / `normalize_loudness()` wird an keiner Stelle importiert
oder aufgerufen — verifiziert per Test
(`tests/test_reprocess_artist_metadata.py::TestProcessFileEndToEnd::test_no_audio_reencoding_module_never_imports_audio_enhancer`).
Der Audio-Stream wird ausschliesslich lesend behandelt.

Fehlt ReplayGain/Loudness, wird das als `UNRESOLVED` dokumentiert statt
nachcodiert:

```text
ReplayGain/Loudness fehlt. Aktuelle Nachruestung wuerde verlustbehaftetes
Audio-Re-Encoding erfordern (AudioEnhancer.normalize_loudness() ist die
einzige im Repository vorhandene Implementierung). Ausserhalb des sicheren
Reprocessing-Scopes. Keine Audioaenderung durchgefuehrt.
```

Jeder Lauf beweist Audio-Unveraendertheit auf zwei Arten:

1. Container-Stream-Parameter (`ffprobe`): Codec/Sample-Rate/Channels/
   Duration vor/nach identisch (die zusaetzlich gelieferte "format bitrate"
   wird bewusst NICHT als Indikator verwendet — sie verschiebt sich bei
   jeder Cover-/Tag-Groessenaenderung, unabhaengig vom Audio-Stream selbst).
2. Audio-Essenz (`ffmpeg -map 0:a -f md5`, dekodiertes PCM gehasht) vor UND
   nach jedem Tag-Write — vollstaendig im Tool selbst enthalten, keine
   externe Referenzdatei noetig.

## 8. Multi-Artist

Ausschliesslich bestehende Logik: `split_main_and_featuring()`
(`services/metadata/models.py`, identisch zur Produktionslogik in
`EnhancedMetadataProcessor`) trennt zusammengeklebte Legacy-Artist-Strings
(z. B. `"CHAPO102; Gustav"` als ein Tag-Wert, TAG-01-Altlast) in einzelne
Namen auf. Nach dem Schreiben wird `©ART`, das
`----:com.apple.iTunes:ARTISTS`-Freeform-Feld und `album_artist` erneut
direkt von der Platte gelesen und validiert.

## 9. Title Cleaning / Dateinamen-Sicherheit

Ein Rename findet **ausschliesslich** innerhalb desselben
Parent-Verzeichnisses statt (`path.with_name(...)` — aendert das
Verzeichnis strukturell nie). Vor jedem Rename:

- Ziel existiert bereits und ist eine andere Datei? → **kein Rename**,
  `UNRESOLVED`
- Endung unveraendert? (immer, Endung wird nie neu bestimmt)
- Parent-Verzeichnis unveraendert? (strukturell garantiert, zusaetzlich per
  Assertion abgesichert)

Stem und Endung werden **getrennt** sanitisiert (`sanitize_filename()` nur
auf den Stem angewendet) — eine fruehere Version dieses Tools sanitisierte
Stem+Endung zusammen, wodurch ein durch ein illegales Zeichen (z. B. `?`)
erzeugtes Leerzeichen vor der Endung stehenblieb (`"...GESEHEN .m4a"`,
real aufgetreten und korrigiert, siehe
`docs/archive/METADATA_REPROCESSING_TEST_CHAPO102.md`).

**UNRESOLVED statt automatischer Korrektur:** enthaelt der Title-Tag
Zeichen, die `sanitize_filename()` aus dem Dateinamen entfernen wuerde
(z. B. `?`), wird dies unabhaengig vom tatsaechlichen Rename-Ergebnis als
`UNRESOLVED` protokolliert — die Diskrepanz zwischen Tag-Inhalt und
Dateiname soll einem Menschen auffallen, nicht automatisch "geloest"
werden.

## 10. Logging

Live nachvollziehbar (`tail -f`), jede Zeile wird sofort geflusht:

```text
/tmp/musicbot_test/metadata_reprocessing_<ARTIST>_<TIMESTAMP>.log
```

Struktur pro Datei: `FILE START` → `BEFORE SNAPSHOT` → `METADATA PIPELINE`
(ArtistNormalizer/TitleCleaner/GenreProcessor/MusicBrainz/Multi-Artist/
LyricsProcessor/CoverProcessor) → `TagWriter` → `AFTER SNAPSHOT` →
`CHANGES` → `UNRESOLVED` → `FINAL RESULT`. Emojis dienen ausschliesslich
der Lesbarkeit, alle technischen Werte bleiben eindeutig als Klartext
vorhanden. Es werden nie API-Keys, Tokens, Cookies, Passwoerter oder
Authorization-Header geloggt.

## 11. Unresolved-Klassifizierung

Ein bewusst nicht geaenderter Fall ist **nicht** automatisch `UNCHANGED`.
Wird eine Korrektur unterlassen, weil sie nicht sicher/eindeutig moeglich
ist, zaehlt der Fall als `UNRESOLVED` — unabhaengig davon, ob sonst noch
etwas an der Datei geaendert wurde. Aktuell zwei automatisch erkannte
Faelle (`check_unresolved()`):

1. Fehlendes ReplayGain/Loudness (Abschnitt 7)
2. Title-Tag enthaelt fuer Dateinamen illegale Zeichen (Abschnitt 9)

Weitere `UNRESOLVED`-Gruende koennen situativ waehrend der
Rename-Pruefung entstehen (Kollision, Parent-Mismatch) oder aus einer
Audiointegritaets-Abweichung (sollte nie auftreten, siehe Abschnitt 7 —
ein Treffer hier ist ein hartes Warnsignal, kein normaler Betriebsfall).

## 12. Automatischer Post-Run Safety Check

Nach jedem Lauf (auch Dry-Run) wird automatisch protokolliert:

```text
Production files changed / Production check enabled
Directory structure changes
Files created / deleted
Audio essence changes
Audio stream (codec/rate/channels/duration) changes
Overall: PASS / PASS WITH UNRESOLVED CASES / FAIL
```

Der Production-Vergleich (`--production-root`, Standard `/mnt/4tb/library`)
liest die zum verarbeiteten relativen Pfad korrespondierende
Produktionsdatei rein lesend vor UND nach dem Lauf (mtime, Groesse, SHA256)
und meldet `FAIL`, sobald sich irgendetwas daran aendert. Mit
`--no-production-check` auslassbar (z. B. wenn `--production-root` nicht
gemountet ist).

## 12a. Bekannte Betriebs-Falle: stale isolierte Mapping-Kopie

`config_test.py::_prepare_isolated_mapping_dir()` kopiert `mapping/`
**nur einmalig** nach `Config.GENRE_MAPPING_DIR`
(`/tmp/musicbot_test/mapping`) - existiert das Zielverzeichnis bereits,
wird nichts erneut synchronisiert. Wird die echte `mapping/`-Quelle
NACH diesem ersten Kopiervorgang geändert (z. B. durch einen
Mapping-Audit-Commit), sieht dieses Tool weiterhin den alten Stand, bis
entweder `run_test_bot.py --clean` läuft (löscht die isolierte Kopie, der
nächste Start kopiert frisch) oder die betroffene(n) Datei(en) manuell
nachsynchronisiert werden. Symptom: Genre-/Artist-Normalisierung wirkt
inkonsistent oder ignoriert ein eigentlich vorhandenes Mapping, obwohl
`mapping/` selbst korrekt ist - real aufgetreten und dokumentiert in
`docs/archive/METADATA_REPROCESSING_TEST_NINA_CHUBA.md`, Abschnitt 9.2.

## 13. Workflow

```text
Produktions-Library (READ-ONLY)
        │  manuell kopieren
        ▼
/tmp/musicbot_test/metadaten/ARTIST
        │  reprocess_artist_metadata.py [--dry-run]
        ▼
Metadaten/Cover korrigiert, Safety Check PASS
        │  manuelle Pruefung + separate Freigabe
        ▼
/tmp/musicbot_test/libary/ARTIST   (manueller Transfer, NICHT automatisch)
```

Das Kopieren aus der Produktions-Library UND der finale Transfer nach
`libary/` sind bewusst manuelle, separat freizugebende Schritte — das Tool
fuehrt keinen der beiden automatisch aus.

## 14. Testverfahren

`tests/test_reprocess_artist_metadata.py` deckt ab: gueltiger Input,
Produktionspfad-Ablehnung, Path-Traversal-Ablehnung, Symlink-Sicherheit
(Verzeichnis- und Dateiebene), Dry-Run, keine Audioverarbeitung,
Dateinamens-Parent-Invariante, Kollisionsschutz, Endungs-Invariante,
Multi-Artist-Validierung (echter `TagWriter`), Before/After-Snapshot,
tatsaechliches erneutes Lesen von der Platte, Unresolved-Erkennung,
Verzeichnis-Invariante. Externe Adapter (Genre/Lyrics/Cover-API-Aufrufe)
sind gemockt; `TagWriter` und alle Path-Safety-/Snapshot-/Multi-Artist-
Funktionen sind die echten Produktionsimplementierungen.

```bash
python3 -m pytest tests/test_reprocess_artist_metadata.py -q
```
