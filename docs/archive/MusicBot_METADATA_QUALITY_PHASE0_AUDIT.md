# MusicBot — Metadata Quality — PHASE 0: Read-Only Audit

> Nachfolgephase zu `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md`
> (dort ausdrücklich als „Out of Scope – Metadata Quality" markiert, siehe
> dortiger Abschnitt 3). Durchgeführt am 2026-08-26 als reine Read-Only-
> Analyse (kein Code, keine Tests, keine Config, keine Library verändert).

**Status: PHASE 0 — ABGESCHLOSSEN**

---

## 1. Executive Summary

Die Metadata-Pipeline (Artist/Title/Album/Genre/Filename) ist strukturell
solide und größtenteils getestet (Genre besonders gut: 6 dedizierte
Testdateien). Gefunden wurden zwei konkrete, real reproduzierte,
**aktuelle** Bugs in der Artist/Title-Extraktion (META-01, META-02) —
strukturell identisch zu DUP-04 (PHASE 2L dieser Session, dort aber nur in
der Duplicate-Detection gefixt, nicht in der eigentlichen Metadaten-
Pipeline). Die Library-Stichprobe (151 Artist-Ordner, 2277 Dateien) zeigt
überwiegend saubere Struktur; die meisten Auffälligkeiten konnten nach
Code-Analyse als Altlast (Vor-Version) klassifiziert werden.

---

## 2. Analysierte Architektur

```
Cache-Check → Basis-Daten → YouTube-Titel-Parser (utils/youtube_parser.py)
 → Artist-Map-Fallback (utils/artist_map.py::parse_youtube_title, nur bekannte Artists)
 → Artist-Bestimmung (services/metadata/artist_processor.py)
 → Titel-Bereinigung (services/metadata/title_cleaner.py)
 → Duplikat-Marker (in-memory processed_titles-Set)
 → Genre (services/metadata/genre_processor.py + utils/genre_map.py)
 → Lyrics → Cover → Album/Jahr (services/metadata/album_processor.py)
 → Loudness (utils/audio_enhancer.py) → move_to_library (utils/filenamefixer.py)
 → Tags schreiben (services/metadata/tag_writer.py)
```

---

## 3. Findings mit Priorität

| ID | Prio | Bereich | Kategorie | Kurzbeschreibung |
|---|---|---|---|---|
| META-01 | P0 | Artist | **A** | feat./ft. ohne Leerzeichen nach Punkt wird in `utils/youtube_parser.py` nicht erkannt → landet im Artist-Feld statt Feature |
| META-02 | P0 | Title | **A** | Gleiches Muster in `services/metadata/title_cleaner.py::apply_title_cleanup_rules()` — Feature-Credit bleibt im Titel-Tag |
| META-03 | P0 | Title | **A** | Nicht gelistete Marketing-Suffixe (z.B. "Official Visual") erzeugen kaputten Titel mit hängender Klammer — real in Library bestätigt (`Bebe Rexha/Singles/2026 - Sad Girls (Official Visual).m4a`) |
| META-05 | P1 | Album/Jahr | **B** | Fehlendes Jahr → aktuelles Jahr statt Platzhalter (`album_processor.py:79-81`, bereits durch `test_year_out_of_range_is_ignored_and_defaults_to_current_year` charakterisiert/getestet, fachliche Konsequenz aber ungeklärt) |
| META-06 | P2 | Filename/Config | **B/D** | `SINGLE_FILENAME_TEMPLATE`/`ALBUM_FILENAME_TEMPLATE`/`PLAYLIST_FILENAME_TEMPLATE`/`ARTIST_DIR_TEMPLATE`/`ALBUM_DIR_TEMPLATE`/`SINGLE_DIR_TEMPLATE`/`DEFAULT_ALBUM_NAME` in config.py werden nirgends gelesen (grep-verifiziert) — `utils/filenamefixer.py::build_final_path()` hartcodiert eigene, bei PLAYLIST_FILENAME_TEMPLATE abweichende Muster |
| META-04 | P1 | Artist | **C** | Case-sensitive Artist-Ordner-Duplikate (makko/Makko, t-Low/T-Low) mit echter Diskografie-Aufspaltung — Root Cause in `utils/artist_map.py` noch nicht verifiziert |
| META-07 | P2 | File/Library | **D** | Verwaiste Loudness-Normalisierungs-Artefakte in Library (temp_loudnorm_*.m4a, *_backup.m4a, Report-JSONs) — nach Code-Analyse (`utils/audio_enhancer.py`, aktueller `finally`-Cleanup + Pre-Move-Ausführung) mit hoher Wahrscheinlichkeit Altlast, kein aktueller Bug |
| META-08 | P2 | Duplicate | **D** | "(1)"-Kollisionsdateien real vorhanden — bestätigt Relevanz der bereits behandelten DUP-Serie dieser Session, kein neuer Fund, keine Zuordnung vor/nach Fix möglich |
| META-09 | P3 | Filename | **D** | Album-Ordner ohne "YYYY - "-Präfix (~15% der Stichprobe) — aktueller Code erzeugt diesen Präfix immer, also Altlast |
| META-10 | P3 | Title | Potenzielles Problem | Einzelfall leerer Title-Tag + YouTube-ID im Dateinamen (`DD Osama/.../10 - Track_10_pWzPPL_tYo8.m4a`) — nicht reproduzierbar ohne Original-Titel |

Vollständige Herleitung, Code-Belege und Library-Beispiele: siehe
Chat-Protokoll der PHASE-0-Analyse vom 2026-08-26 (Read-Only-Audit,
18-Abschnitte-Bericht).

---

## 4. Kategorie A/B/C/D

- **Kategorie A** (klarer Bug, kleiner Scope): META-01, META-02, META-03
- **Kategorie B** (Produktentscheidung nötig): META-05, META-06
- **Kategorie C** (tiefere Analyse nötig): META-04
- **Kategorie D** (Altlast/kosmetisch/bereits akzeptiert): META-07, META-08, META-09, META-10

---

## 5. Empfohlener nächster Controlled Fix

**META-01 + META-02** (gebündelt, identische Wurzelursache: fehlende
Behandlung von "feat."/"ft." ohne Leerzeichen nach dem Punkt) — umgesetzt
in PHASE 1, siehe
`docs/archive/MusicBot_METADATA_QUALITY_PHASE1_META01_META02_AUDIT.md`.

META-03 bleibt offener Kategorie-A-Kandidat für einen Folge-Fix (andere
Regex-Struktur, höheres Regressionsrisiko in derselben, vielfach
getesteten Funktion — bewusst nicht im selben Schritt behandelt).

---

## 6. Offene fachliche Entscheidungen

- **META-05**: Downloadjahr-Fallback vs. neutraler Platzhalter bei
  fehlendem Jahr?
- **META-06**: Tote Templates in config.py entfernen/dokumentieren, oder
  `build_final_path()` darauf umstellen (größerer Scope)?
- **META-04**: Freigabe für dedizierte Tiefenanalyse von
  `utils/artist_map.py` (Case-Konsistenz) nötig.
- **META-07/META-09**: Manuelle Bereinigung der Altlasten in der realen
  Library (keine Automatik ohne explizite Freigabe).
