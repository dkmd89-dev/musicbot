---
status: PROPOSED (Nutzerentscheidung 2026-09-14, noch nicht implementiert)
---

# ADR-0003: Level 2/Level 3 über Telegram — Pro-Artist-Bestätigung

## Kontext

`docs/LIBRARY_REPAIR.md` §9/§10 legt aktuell **bewusst** fest, dass nur
`SAFE_AUTOMATIC` (Level 1) ueber Telegram ausfuehrbar ist:

> "Alle externen/destruktiven Level (COVER/EXTERNAL_METADATA/
> METADATA_REPROCESSING/LOUDNESS/DUPLICATE) bleiben CLI-only, exakt
> dieselbe Grenze wie beim Default-`--apply` auf der Kommandozeile."

`doctor_runner.run_safe_automatic_repair()` ruft den Subprozess mit fest
verdrahtetem `--level SAFE_AUTOMATIC` auf; `repair_musicbot_handler.py`
importiert ausschliesslich `execute_safe_automatic_repair()`.

Level 2 (`METADATA_REPROCESSING`, `track_reprocessor.process_file()`) und
Level 3 (`EXTERNAL_METADATA`, `MusicBrainzClient`) unterscheiden sich von
Level 1 in genau den Eigenschaften, die diese Grenze urspruenglich
begruendeten:

- **Netzwerk:** MusicBrainz-/Genius-/Last.fm-Aufrufe, rate-limited.
- **Laufzeit:** laut `LIBRARY_REPAIR.md` §6a "Minuten" pro Artist-Batch.
- **Nebeneffekt:** Level 2 aktualisiert `mapping/auto_learned_*` (Auto-Learn)
  als Seiteneffekt der vollen Pipeline — eine Mapping-Datei-Aenderung
  (CLAUDE.md §10: "Mapping-Aenderungen wie Codeaenderungen behandeln").
- **Cover-Nebeneffekt:** Level 2 kann `ALBUM_COVER_INCONSISTENT` als
  Folgeeffekt erzeugen (dokumentiertes bekanntes Verhalten, §6a).

Der Nutzerauftrag verlangt trotzdem explizit "Level 1 bis Level 3" ueber
Telegram — die Frage ist nur, mit welcher Freigabe-Granularitaet.

## Entscheidung

Level 2 und Level 3 werden ueber Telegram **pro Artist** freigegeben, nicht
als ein einziger Blanket-Confirm ueber alle offenen Kandidaten:

```text
Reparaturvorschläge
   -> "Level 2 anzeigen" -> Liste nach Artist gruppiert (NEU)
   -> Artist waehlen -> Preview (nur dieser Artist, read-only)
   -> explizite Bestaetigung "JA, FUER <Artist> REPARIEREN"
   -> execute_level2_repair(artist=<Artist>, triggered_by=...) (NEU)
   -> Verification-Scan NUR im Scope dieses Artists
   -> Ergebnis
```

Identisch fuer Level 3 (`execute_level3_repair(artist=...)`, NEU).

`repair_service.py` erhaelt zwei neue Funktionen, die
`execute_safe_automatic_repair()` strukturell spiegeln (gleicher Lock,
gleiche Journal-Fenster-Lesung, gleiche Regressionserkennung), aber:
- den Plan vor Ausfuehrung mit `filter_plan(plan, artist=..., level=...)`
  einschraenken,
- vor der Bestaetigung den Netzwerk-/Laufzeit-/Auto-Learn-Warnhinweis aus
  `LIBRARY_REPAIR.md` §6a in der Telegram-Preview anzeigen (Transparenz,
  CLAUDE.md §17 "Fallbacks/Fehler beruecksichtigen"),
- den Verification-Rescan-Scope auf den betroffenen Artist begrenzen
  (Kostenreduktion — ein Vollscan nach jedem Artist waere unnoetig teuer).

`COVER`/`LOUDNESS`/`DUPLICATE` bleiben unveraendert CLI-only — sie waren
nicht Teil des Nutzerauftrags ("Level 1 bis Level 3") und aendern die
Sicherheitsgrenze fuer die noch riskanteren/destruktiven Level nicht.

## Konsequenzen

- **Vorteil:** Blast-Radius pro Telegram-Tap bleibt auf einen Artist
  begrenzt — konsistent mit der bisherigen CLI-Nutzung
  (`library_repair.py --artist <X> --level METADATA_REPROCESSING`), die
  laut `LIBRARY_REPAIR.md` bereits das etablierte Nutzungsmuster ist (alle
  bisherigen Level-2/3-Produktionslaeufe liefen `--artist`-skaliert, nie
  library-weit).
- **Vorteil:** ein einzelner haengender/fehlschlagender Level-2-Lauf (z.B.
  MusicBrainz-Timeout) blockiert nicht die Freigabe fuer andere Artists.
- **Nachteil:** mehr Taps bei vielen betroffenen Artists — akzeptiert, da
  Level 2/3 in der Praxis selten sehr viele Artists gleichzeitig betreffen
  (reale Produktionslaeufe bisher: 1 Artist pro Lauf).
- **Concurrency:** dieselbe `library_repair.lock`-Datei wie
  `execute_safe_automatic_repair()` wird verwendet — ein Level-2-Lauf fuer
  Artist A und ein SAFE_AUTOMATIC-Lauf koennen sich weiterhin nicht
  ueberlappen (Absicht: die Executor-Pipeline schreibt in dieselbe
  Library, ein artist-scope-Lock allein waere nicht ausreichend, da
  `apply_level1()` z.B. auch albumweite Codes wie
  `ALBUM_ARTIST_INCONSISTENT` behandelt).
- Neuer Testbedarf: `tests/test_repair_service.py` um
  `execute_level2_repair()`/`execute_level3_repair()` erweitert (Artist-
  Filter-Korrektheit, Scoped-Verification, Lock-Sharing mit
  SAFE_AUTOMATIC), `tests/test_repair_musicbot_handler.py` um die neue
  Artist-Auswahl-/Preview-/Confirm-Kette je Level.
