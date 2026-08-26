# MusicBot — Download Pipeline Stability Phase — PHASE 2D: DL-01 Audit

> Strikt read-only Analyse gemäß Auftrag PHASE 2D. Basis:
> `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md`,
> `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE1_PLAN.md`,
> `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2C_DL02_AUDIT.md`.
> Aufbauend auf Commit `dc09e42` (DL-02, working tree sauber verifiziert).
> **Keine Codeänderungen in dieser Phase.**

---

## 1. Executive Summary

DL-01 ist bestätigt: In der gesamten Kette (`enhanced_metadata_processor.py`,
`download_utils.py`, `download_executor.py`, `klassen/download_handler.py`)
existiert kein `except asyncio.CancelledError`/`except BaseException` — nur
`except Exception`, das seit Python 3.8 `CancelledError` (jetzt
`BaseException`-Subklasse) nicht abfängt. Cancellation propagiert daher
unverändert durch die gesamte Pipeline, OHNE dass irgendein Cleanup läuft.

**Wichtige Verfeinerung gegenüber Phase 0/1:** Die tatsächliche Codeanalyse
zeigt, dass das reale Risiko enger und präziser gefasst werden muss als
ursprünglich angenommen:

- `move_to_library()` (`utils/filenamefixer.py`) UND `TagWriter.write_tags()`
  (`services/metadata/tag_writer.py`) verwenden **beide** bereits ein
  Copy-in-Zielverzeichnis + atomares `Path.replace()`-Muster (FINDING-6 bzw.
  AE-11). Eine **Korruption** der Zieldatei durch Cancellation ist dadurch
  strukturell **ausgeschlossen** — die Zieldatei ist zu jedem Zeitpunkt
  entweder der alte, vollständige Zustand oder der neue, vollständige
  Zustand, nie ein Byte-Gemisch.
- Der von Phase 0 angenommene Fall „Cancellation NACH `move_to_library()`,
  aber VOR Tag-Write" und „WÄHREND/nach Tag-Write" sind bei genauer
  Betrachtung des Kontrollflusses **derselbe einzige Await-Punkt**
  (`await asyncio.to_thread(self.tag_writer.write_tags, ...)`) — dazwischen
  gibt es keinen weiteren `await`, an dem eine Cancellation überhaupt
  einhaken könnte (Python unterbricht synchronen Code nicht).
- Das reale Risiko ist damit nicht „Korruption", sondern: (a) eine
  **dauerhaft ungetaggte, aber valide/abspielbare** Datei bleibt in der
  Library liegen (falls der Hintergrund-Thread nach der Cancellation
  fehlschlägt oder schlicht noch läuft), oder (b) eine **vollständig
  korrekt getaggte, aber nirgends registrierte** Datei (falls der
  Hintergrund-Thread nach der Cancellation trotzdem noch erfolgreich
  fertig wird — der Thread läuft nachweislich unbeaufsichtigt weiter, siehe
  Abschnitt 6).
- Ein bereits vorhandenes, 1:1 wiederverwendbares Cleanup-Idiom
  (`enhanced_metadata_processor.py:909-919`, der `tag_err`-Except-Block)
  deckt exakt diesen Fall bereits für reguläre `Exception`s ab — der
  minimale DL-01-Fix repliziert dieses bereits geprüfte Muster für
  `CancelledError`, statt eine neue Cleanup-Funktion zu bauen (Korrektur
  gegenüber der in PHASE 1 offen gelassenen Möglichkeit „ggf. neue
  LIBRARY_DIR-fähige Cleanup-Funktion").

**Kein `asyncio.shield()` erforderlich** (Begründung Abschnitt 8) — die
zugrundeliegenden `to_thread`-Worker-Threads sind ohnehin nicht durch
Cancellation unterbrechbar, ein `shield()` würde daran nichts ändern und nur
unnötig Komplexität sowie eine Verzögerung der Cancellation-Propagation
einführen.

---

## 2. Exakte Root Cause

`process_single_track()` (`services/metadata/enhanced_metadata_processor.py:231-1074`)
umschließt den gesamten Verarbeitungsablauf in einem einzigen
`try: ... except Exception as e: ...`-Block (Zeilen 256/1055). `asyncio.CancelledError`
ist seit Python 3.8 eine `BaseException`-Subklasse (nicht `Exception`) —
`except Exception as e` fängt sie nachweislich nicht ab (verifiziert: kein
einziges `except BaseException`/`except asyncio.CancelledError` in der
gesamten Produktionskette, siehe Grep-Ergebnis Abschnitt 5). Cancellation
propagiert daher komplett unbehandelt durch `process_single_track()` und alle
aufrufenden Schichten (`download_utils.py`, `klassen/download_handler.py`)
bis zum PTB-Framework, das den entsprechenden Update-Handler-Task erzeugt und
bei Bot-Shutdown/Neustart abbricht (`Application.stop()`/Task-Cancellation,
Standardverhalten von `python-telegram-bot`, nicht MusicBot-eigen — kein
`asyncio.create_task()`/`ensure_future()` für `handle_url()` im eigenen Code
gefunden, siehe Abschnitt 5).

---

## 3. Vollständiger aktueller Datenfluss (mit exakten Await-Punkten)

```text
process_single_track()  [try-Block startet Zeile 256]
    │
    │  original_path: Optional[Path] = None   (Zeile 254, VOR try - bewusst
    │  vorab gebunden, damit der aeussere except-Block ihn immer sicher
    │  referenzieren kann, auch wenn der Fehler VOR Schritt 14 auftrat)
    │
    ├─ Schritt 2-13 (Cache-Check, Artist/Titel-Parsing, Genre, Lyrics,
    │  MB-Prefetch #1, Cover, MB-Prefetch #2)
    │      await-Punkte: Zeile 510 (Genre), 571 (Lyrics), 602 (MB #1),
    │      704 (Cover), 774 (MB #2)
    │      → original_path ist hier NOCH NICHT gesetzt (wird erst Schritt 14
    │        zugewiesen) — bereits HEUTE, UNABHAENGIG von Cancellation, ein
    │        bestehender Cleanup-Bindungsluecken-Fall fuer reguläre
    │        Exceptions in diesem Fenster (siehe Abschnitt 9, "Verwandte,
    │        nicht neue Beobachtung")
    │
    ├─ Schritt 14: original_path = Path(track_metadata["filepath"])  (Zeile 739)
    │      rein synchron, kein await
    │
    ├─ Schritt 15b: await asyncio.to_thread(AudioEnhancer.normalize_loudness, ...)
    │      (Zeile 818) — LETZTER Await-Punkt VOR move_to_library()
    │      original_path ist gesetzt, Datei liegt noch in DOWNLOAD_DIR
    │
    ├─ Schritt 16: library_path, renamed_due_to_conflict =
    │      filename_fixer.move_to_library(source_path=original_path, ...)
    │      (Zeile 844) — REIN SYNCHRON, KEIN internes await. Kann durch
    │      Cancellation NICHT mitten in der Ausfuehrung unterbrochen werden
    │      (Python praeemptiert synchronen Code nicht). Intern:
    │      copy2() in Zielverzeichnis-Tempdatei → Path.replace() (atomar)
    │      → Path.unlink() der Quelle (DOWNLOAD_DIR, best-effort, Zeile 364-372)
    │      → bei Erfolg: original_path existiert i.d.R. NICHT mehr,
    │        library_path existiert VOLLSTAENDIG (nie halb-geschrieben)
    │
    ├─ Schritt 17: await asyncio.to_thread(self.tag_writer.write_tags, ...)
    │      (Zeile 870) — EINZIGER Await-Punkt ZWISCHEN move_to_library()
    │      und Cache-Store. Kein separater "waehrend Tag-Write" vs. "danach,
    │      vor Cache-Store"-Await vorhanden - es gibt nur DIESEN einen.
    │      Intern (tag_writer.py): copy2() auf .tmp-Sibling im selben
    │      Verzeichnis → taggen (mutagen) → tmp_path.replace(target_path)
    │      (atomar) NUR bei Erfolg. target_path (= library_path) bleibt bei
    │      JEDEM Fehler/Abbruch byteidentisch zum Zustand nach Schritt 16.
    │      Innerer except (Zeile 891-920) faengt reguläre Exception ab,
    │      loescht library_path gezielt, reicht Fehler weiter (raise).
    │
    ├─ Schritt 18: MetadataResult(...) bauen (Zeile 923) — rein synchron
    │
    ├─ Schritt 19: self.cache_handler.store(result, ...) (Zeile 978)
    │      — rein synchron, KEIN await. Ab hier: MetadataCache-Eintrag
    │      existiert bereits, unabhaengig davon ob die Funktion je
    │      zurueckkehrt.
    │
    ├─ Schritt 19b: Auto-Learning (bedingt)
    │      await-Punkte: Zeile 997 (learn_genre), 1035 (learn_artist)
    │      — NACH Cache-Store. Datei UND MetadataCache-Eintrag bereits
    │      vollstaendig/konsistent. Nur die Rueckgabe des MetadataResult an
    │      den Aufrufer (und damit die downstream DuplicateCache-
    │      Registrierung in klassen/download_handler.py) fehlt noch.
    │
    └─ Schritt 20: return result

except Exception as e:  (Zeile 1055)
    cleanup_single_download_artifact(original_path, DOWNLOAD_DIR, logger)
    return MetadataResult(success=False, ...)
    → faengt CancelledError NICHT (BaseException-Subklasse)
```

**Aufrufer-Kette nach `process_single_track()`s Rueckgabe (bzw. bei
Cancellation: nach ihrer Propagation):**
`download_utils.py::_process_single_download()`/`_process_track_metadata()`
→ `enhanced_download_with_retry()` → `klassen/download_handler.py::handle_youtube_links()`
→ `handle_single_track_success()`/`handle_playlist_success()` (registriert im
`DuplicateDetector`, siehe DUP-01/DUP-02/DUP-08) → PTB-Handler-Task. Kein
`except Exception` in dieser Kette (siehe Grep, Abschnitt 5) verwandelt
`CancelledError` in etwas anderes — sie propagiert bis zum PTB-Framework
unveraendert durch.

---

## 4. Cancellation-Datenfluss

Da Cancellation in `asyncio` ausschliesslich an einem `await`-Punkt
eingehaengt werden kann (bzw. am naechsten erreichten `await`, falls der
Task gerade in einem rein synchronen Codeabschnitt laeuft), reduzieren sich
die praktisch moeglichen Cancellation-Zeitpunkte auf die in Abschnitt 3
gelisteten `await`-Zeilen. Das ergibt folgende Faelle:

### Fall A — Cancellation VOR `move_to_library()`

Trifft an einem der `await`-Punkte in Zeile 510/571/602/704/774/818.
`original_path` ist entweder noch `None` (Zeilen 510-704, vor Schritt 14)
oder bereits gesetzt und zeigt auf eine Datei in `DOWNLOAD_DIR` (Zeile 818,
nach Schritt 14). `move_to_library()` wurde nicht erreicht. Die
Downloaddatei bleibt in `DOWNLOAD_DIR` liegen.

- **Bleibt eine Datei zurueck?** Ja, in `DOWNLOAD_DIR` (ausser bei
  Cancellation vor Schritt 14, wo `original_path` selbst noch `None` ist —
  aber die physische Datei existiert bereits, unabhaengig vom lokalen
  Variablenstand dieser Funktion).
- **Welche Cleanup-Logik greift?** Keine sofortige — aber der bereits
  etablierte 24h-Start-Sweep (`cleanup_download_artifacts()`,
  `bot.py:446`, vor `start_polling()` verankert) erfasst sie beim naechsten
  Bot-Neustart (genau der Trigger, der Cancellation in der Praxis
  ueberhaupt auslöst).
- **Welche Exception verlaesst die Funktion?** `asyncio.CancelledError`,
  unveraendert.
- **Wird der Zustand korrekt weitergegeben?** Ja — Cancellation propagiert
  sauber, kein Verschlucken, kein falscher Erfolgszustand.

### Fall B — Cancellation NACH `move_to_library()`, waehrend `write_tags()` (deckt beide vom Auftrag genannten Faelle B und C ab)

Trifft am einzigen `await`-Punkt zwischen Schritt 16 und Schritt 19
(Zeile 870). `library_path` existiert bereits (von `move_to_library()`
atomar erzeugt), `original_path`/DOWNLOAD_DIR-Datei existiert in aller Regel
NICHT mehr (von `move_to_library()` bereits geloescht, best-effort). Der
`write_tags()`-Hintergrund-Thread laeuft nach der Cancellation UNBEAUFSICHTIGT
weiter (siehe Abschnitt 6/8) und endet in einem von zwei Zustaenden,
unabhaengig vom Zeitpunkt, an dem `process_single_track()` selbst bereits
mit `CancelledError` verlassen wurde:

- **B1 (Thread scheitert oder wurde noch nicht fertig):** `library_path`
  bleibt in genau dem Zustand, den `move_to_library()` hinterlassen hat —
  eine valide, abspielbare, aber **ungetaggte** (nur die rohen
  Download-Tags, kein Artist/Album/Genre/Lyrics/Cover von MusicBot) Datei.
  **Das ist der eigentliche DL-01-Kernfall.**
- **B2 (Thread wird trotz Cancellation noch erfolgreich fertig):**
  `tmp_path.replace(target_path)` laeuft im Hintergrund noch durch —
  `library_path` wird nachtraeglich vollstaendig korrekt getaggt, OHNE dass
  irgendjemand das noch mitbekommt (die Funktion hat bereits mit
  `CancelledError` verlassen). Datei ist vollstaendig korrekt, aber weder in
  `MetadataCache` noch in `DuplicateCache` registriert.
- **Bleibt eine Datei zurueck?** Ja, in `LIBRARY_DIR` — in B1 ungetaggt,
  in B2 vollstaendig getaggt.
- **Welche Cleanup-Logik greift?** Aktuell KEINE (das ist DL-01).
- **Welche Exception verlaesst die Funktion?** `CancelledError`, unveraendert.
- **Wird der Zustand korrekt weitergegeben?** Die Cancellation selbst: ja.
  Der Dateizustand: nein — weder Cache noch DuplicateDetector erfahren von
  der Datei.

### Fall C — Cancellation NACH Cache-Store (Schritt 19), waehrend Auto-Learning

Trifft an Zeile 997/1035. Datei ist vollstaendig korrekt getaggt,
`MetadataCache` hat bereits einen Eintrag (ein spaeterer identischer Request
wuerde ueber den Cache-Hit-Pfad, Zeile 261-267, sofort treffen — dieser Fall
ist bereits teilweise selbstheilend fuer den MetadataCache-Pfad). Nur die
`DuplicateCache`-Registrierung (die erst nach Rueckgabe des `MetadataResult`
in `klassen/download_handler.py` erfolgt) bleibt aus. Nicht explizit vom
Auftrag als eigener Fall benannt, aber vom empfohlenen Fix (Abschnitt 7,
Wrapping bis Funktionsende) automatisch mit abgedeckt, ohne zusaetzlichen
Aufwand.

### Fall D — normale Exception (Referenzverhalten, unveraendert)

Bereits vorhanden und korrekt (siehe FINDING-2/`tag_err`-Except-Block,
Zeilen 891-920, sowie der aeussere `except Exception`, Zeilen 1055-1074):
Tag-Write-Fehler nach erfolgreichem Move loescht `library_path` gezielt und
gibt `MetadataResult(success=False, ...)` zurueck. Kein Datenverlust, kein
Silent-Failure. **Bleibt durch den DL-01-Fix vollstaendig unangetastet** (der
neue `except asyncio.CancelledError`-Zweig ist eine eigene, separate
`except`-Klausel, beruehrt die bestehende `except Exception`-Klausel nicht).

### Fall E — normaler Erfolg (Referenzverhalten, unveraendert)

Datei vollstaendig getaggt, `MetadataResult(success=True, ...)` wird
zurueckgegeben, `DuplicateCache`-Registrierung erfolgt normal downstream.
Unveraendert durch den Fix (keine neue Codepfad-Beruehrung im Erfolgsfall).

---

## 5. Repository-weite Suche (Ergebnisse)

```
asyncio.CancelledError:
  bot.py (3x, PTB-Polling-Loop-Ebene)
  services/statistik/play_history_poller.py (1x, unabhaengiger Poller)
  handlers/enhanced_error_handler.py (1x, nur als Eintrag in einer
    Fehlerklassifikations-Liste fuer ANDERE Fehlerpfade, keine
    Cancellation-Behandlung der Download-Pipeline)
  → KEIN Treffer in enhanced_metadata_processor.py, download_utils.py,
    download_executor.py, klassen/download_handler.py

except Exception / except BaseException:
  Zahlreiche Treffer in der Download-/Metadata-Kette (siehe Grep-Rohdaten),
  ausnahmslos `except Exception` — kein einziges `except BaseException`
  in der gesamten betrachteten Kette.

move_to_library / write_tags / cleanup_single_download_artifact / cleanup / task.cancel():
  Bestaetigt wie in Abschnitt 3 beschrieben. `task.cancel()` wird
  ausschliesslich fuer INTERNE MusicBot-eigene Hintergrund-Tasks verwendet
  (bot.py: `_cleanup_task`; play_history_poller.py: `_polling_task`) - fuer
  KEINEN Download-/Metadata-Task im eigenen Code. Das bestaetigt: die
  Cancellation von `process_single_track()` wird nicht von MusicBot selbst
  ausgeloest, sondern ausschliesslich vom PTB-Framework beim
  Handler-Task-Abbruch (Bot-Shutdown/Neustart) — konsistent mit Phase 0s
  Einschaetzung "praktisch ausgeloest z. B. durch Bot-Shutdown/Neustart
  waehrend eines laufenden Downloads".
```

---

## 6. Bestehende Cleanup-Infrastruktur (wiederverwendbar)

- **`enhanced_metadata_processor.py:909-919` (`tag_err`-Except-Block,
  FINDING-2):** bereits geprueftes, produktiv laufendes Idiom fuer exakt
  denselben Fall (Datei liegt bereits unter `library_path`, muss geloescht
  werden, Fehler beim Loeschen selbst wird nur geloggt, nie weitergereicht).
  **Direkt wiederverwendbar als Vorlage** fuer den neuen
  `CancelledError`-Zweig — keine neue Abstraktion, keine neue Datei, keine
  neue Funktion in `download_artifact_cleanup.py` noetig (Korrektur
  gegenueber der in PHASE 1 noch offen gelassenen Option).
- **`cleanup_single_download_artifact()`** ist fuer diesen Fall bewusst
  NICHT geeignet — sie ist über `_is_within_directory(download_dir)`
  strukturell an `Config.DOWNLOAD_DIR` gebunden; `library_path` liegt aber
  in `Config.LIBRARY_DIR` und wuerde von dieser Pruefung korrekt, aber
  ungewollt uebersprungen. Der bereits vorhandene `tag_err`-Block umgeht das
  bewusst durch einen direkten `Path.exists()`/`Path.unlink()`-Aufruf ohne
  Verzeichnis-Bindung — dasselbe Muster ist fuer `CancelledError`
  anzuwenden.
- **Hintergrund-Thread-Verhalten (verifiziert, konsistent mit der bereits
  in PHASE 2C/DL-02 fuer yt-dlp/FFmpeg etablierten Erkenntnis):**
  `asyncio.to_thread()` kapselt `loop.run_in_executor(None, func)` auf einem
  `ThreadPoolExecutor`. Ein bereits laufendes Worker-Item kann durch
  `Future.cancel()` NICHT abgebrochen werden (nur ein noch nicht gestartetes
  Item waere abbrechbar) — `asyncio`s Task-Cancellation wirkt ausschliesslich
  auf der Koroutinen-Seite (das `await` wirft `CancelledError`), der
  zugrundeliegende OS-Thread (`self.tag_writer.write_tags(...)`, komplett
  synchroner mutagen/shutil-Code) laeuft unbeeinflusst bis zum natuerlichen
  Ende weiter. Das ist identisch zum bereits fuer DL-02 am yt-dlp/FFmpeg-Fall
  verifizierten Verhalten, hier nun fuer `write_tags()` bestaetigt.

---

## 7. Minimaler Fix-Vorschlag (NICHT umgesetzt, nur zur Freigabe vorgeschlagen)

```python
# services/metadata/enhanced_metadata_processor.py, process_single_track()

# Zeile 254 (bestehend), ergänzt:
original_path: Optional[Path] = None
library_path: Optional[Path] = None          # NEU — analog original_path,
                                               # damit der neue except-Zweig
                                               # sie immer sicher referenzieren
                                               # kann, auch wenn Cancellation
                                               # vor move_to_library() traf.

try:
    ...                                        # unveraendert
    library_path, renamed_due_to_conflict = filename_fixer.move_to_library(...)
    ...                                        # unveraendert (Schritt 17-20)

except asyncio.CancelledError:
    # Spiegelt exakt das bereits geprüfte Muster aus dem tag_err-Block
    # (Zeile 909-920) - keine neue Cleanup-Architektur.
    if library_path is not None:
        self.logger.warning(
            f"⚠️ Cancellation nach Bibliotheks-Move erkannt — entferne "
            f"unvollständige/nicht registrierte Datei: {library_path}"
        )
        try:
            if Path(library_path).exists():
                Path(library_path).unlink()
                self.logger.info(
                    f"🧹 Datei nach Cancellation entfernt: {library_path}"
                )
        except OSError as cleanup_err:
            self.logger.error(
                f"❌ Konnte Datei nach Cancellation nicht entfernen: "
                f"{cleanup_err}"
            )
    raise                                       # NIEMALS verschlucken

except Exception as e:
    ...                                          # unveraendert, wie bisher
```

**Platzierung:** als zusaetzliche `except`-Klausel am bereits bestehenden
`try` (Zeile 256), VOR der bestehenden `except Exception as e:`-Klausel
(Reihenfolge dient nur der Lesbarkeit — da `CancelledError` keine
`Exception`-Subklasse ist, wuerde die bestehende Klausel sie ohnehin nie
faelschlich abfangen, unabhaengig von der Reihenfolge).

**Warum kein `finally`:** identische Begruendung wie beim bereits
umgesetzten DL-02-Fix — ein `finally` wuerde unterschiedslos auch im
Erfolgsfall laufen; dort existiert `library_path` typischerweise, ist aber
laengst korrekt fertig und darf nicht geloescht werden. Der Cleanup gehoert
ausschliesslich in den `CancelledError`-Zweig.

**Warum `raise` statt `raise e` / kein neues Exception-Objekt:** erhaelt die
urspruengliche `CancelledError`-Instanz inkl. Traceback und (ab Python 3.9)
`cancel()`-Message unveraendert — semantisch korrektes Weiterreichen einer
Cancellation.

---

## 8. Begruendung der Cancellation-Semantik (inkl. `asyncio.shield()`-Abwaegung)

**Kein Verschlucken:** die neue Klausel endet zwingend mit `raise` (bare, um
die Originalexception 1:1 durchzureichen) — kein `return`, kein Ersetzen
durch `DownloadError`/`MetadataResult(success=False, ...)`, kein stiller
Uebergang in einen Erfolgszustand. Der aufrufende Task bleibt fuer die
gesamte asyncio-Infrastruktur (inkl. PTB) korrekt als "cancelled" erkennbar.

**Kein globaler/geteilter Zustand:** `library_path` ist eine
funktionslokale Variable (wie `original_path` bereits etabliert) — kein
Modul-/Klassen-Level-State, keine Interferenz zwischen parallelen
`process_single_track()`-Aufrufen (mehrere Downloads laufen ueber das
bestehende `_download_semaphore` ohnehin nur begrenzt parallel, aber selbst
ohne diese Begrenzung waere die Variable durch den Funktionsscope isoliert).

**Warum `asyncio.shield()` HIER NICHT eingesetzt wird (explizit begruendet,
nicht nur pauschal vermieden):**

`asyncio.shield()` schuetzt eine innere Koroutine davor, durch die
Cancellation des AEUSSEREN Awaiters selbst abgebrochen zu werden — der
aeussere `await asyncio.shield(...)`-Aufruf wirft aber trotzdem sofort
`CancelledError`, sobald der aeussere Task gecancelt wird (es sei denn, man
faengt das explizit ab und wartet die geschuetzte Koroutine gezielt noch
einmal separat aus). Zwei Gruende, warum das hier NICHT sinnvoll waere:

1. **Es aendert nichts an der eigentlichen Ursache.** Der
   `to_thread()`-Worker-Thread ist bereits *heute*, ganz ohne `shield()`,
   nicht durch Cancellation unterbrechbar (Abschnitt 6) — er laeuft so oder
   so bis zum Ende durch. `shield()` wuerde daran nichts aendern, es wuerde
   nur zusaetzliche Komplexitaet einfuehren, ohne das zugrunde liegende
   Verhalten zu beeinflussen.
2. **Die einzige Art, wie `shield()` hier tatsaechlich etwas bewirken
   koennte,** waere eine explizite "warte auf das wirkliche Ergebnis des
   Threads, bevor die Cancellation propagiert wird"-Logik (Future separat
   speichern, nach dem Abfangen der Cancellation nochmal awaiten, erst
   danach `raise`). Das wuerde den in Abschnitt 4/Fall B beschriebenen
   Restrisiko-Fall B2 zwar vollstaendig eliminieren (kein "Datei taucht
   nachtraeglich unbeaufsichtigt wieder auf")  — aber um den Preis einer
   GEWOLLTEN VERZOEGERUNG der Cancellation-Propagation um die volle
   `write_tags()`-Laufzeit (laut AE-12-Audit bis zu ~1,6s bei grossen
   Dateien). Das widerspricht dem Zweck von Cancellation (soll den Task
   MOEGLICHST ZEITNAH beenden) und ist fuer ein Risiko, das (a) keinen
   Datenverlust, (b) keine Korruption und (c) bereits einen bekannten,
   akzeptierten Praezedenzfall im selben Projekt hat (DUP-05: "Race, kein
   Datenverlust, durch bestehende Mechanismen abgefedert, bewusst als
   akzeptiertes Risiko eingestuft"), unverhaeltnismaessig.

**Ergebnis:** `shield()` wird bewusst NICHT eingesetzt. Das verbleibende
Restrisiko aus Fall B2 (Datei wird nach der Cancellation vom
unbeaufsichtigten Hintergrund-Thread doch noch vollstaendig fertig und damit
"wiederhergestellt", aber ohne Cache-/DuplicateCache-Eintrag) wird als
akzeptiertes Restrisiko dokumentiert (Abschnitt 9), analog zu DUP-05.

---

## 9. Risiken

- **Restrisiko Fall B2 (dokumentiert, akzeptiert, s. Abschnitt 8):**
  seltenes Zeitfenster (Cancellation muss exakt waehrend der laufenden
  `write_tags()`-Threadausfuehrung eintreffen, typische Laufzeit laut
  AE-12-Audit im Bereich weniger ms bis ~1,6s bei sehr grossen Dateien),
  kein Datenverlust, keine Korruption — nur ein spaeter unbeaufsichtigt
  fertiggestelltes, korrektes, aber nicht-registriertes Artefakt. Gleiche
  Risikoklasse wie das bereits akzeptierte DUP-05.
- **Verwandte, NICHT neue Beobachtung (kein DL-01-Scope, hier nur
  transparent gemacht statt uebersehen):** fuer reguläre `Exception`s
  (nicht Cancellation!), die VOR Schritt 14 (Zeile 739, vor der Zuweisung
  von `original_path`) auftreten — also waehrend Genre-/Lyrics-/Cover-/
  MB-Prefetch (Await-Punkte Zeile 510-704) — ist `original_path` in der
  aeusseren `except Exception`-Klausel noch `None`, wodurch
  `cleanup_single_download_artifact(None, ...)` bereits HEUTE, unabhaengig
  von DL-01, ein No-op ist. Das ist eine bereits bestehende, nicht durch
  diese Phase verursachte Charakteristik der Pipeline (betrifft alle
  Exceptions gleichermassen, nicht speziell Cancellation) — wird hier
  dokumentiert, aber bewusst NICHT im Rahmen von DL-01 mitgefixt (waere ein
  eigener, kleinerer, unabhaengiger Fund, keine Cancellation-Frage).
- **Fall A (Cancellation vor `move_to_library()`) bleibt bewusst
  unbehandelt** — identisch zur bereits in PHASE 1 getroffenen
  Scope-Entscheidung: durch den 24h-Start-Sweep abgedeckt, kein akutes
  Risiko, Fix bewusst klein gehalten.
- **Kein neues Nebenlaeufigkeits-Risiko:** `library_path` ist
  funktionslokal, kein geteilter Zustand zwischen parallelen Downloads
  (Semaphore begrenzt ohnehin auf `MAX_CONCURRENT_DOWNLOADS`).
- **Kein Einfluss auf DL-02:** DL-02 betrifft ausschliesslich Fehler
  INNERHALB des yt-dlp-/FFmpeg-Aufrufs in `download_utils.py`, vollstaendig
  getrennter Code, getrennte Datei, getrennter Fehlerpfad (`Exception`, kein
  `CancelledError`-Bezug). Keine Ueberschneidung.
- **Kein Einfluss auf DUP-01/DUP-02/DUP-08:** diese betreffen
  `klassen/download_handler.py`/`services/duplicate/detector.py`, komplett
  andere Dateien/Funktionen. Der DL-01-Fix aendert nichts an
  Registrierungslogik, nur an dem, was VOR einer erfolgreichen Rueckgabe des
  `MetadataResult` bei Cancellation aufgeraeumt wird.

---

## 10. Regressionstest-Plan (NICHT umgesetzt)

Alle Tests nutzen echte Dateien (`tmp_path`), echte `task.cancel()`-basierte
Cancellation (kein `asyncio.sleep`-Racing), und pruefen den tatsaechlichen
Dateisystemzustand — kein reiner Mock-Assertion-Beweis, konsistent mit dem
in dieser Session etablierten Standard.

| # | Szenario | Prueft | Reproduziert Fehler vor Fix? |
|---|---|---|---|
| 1 | Cancellation VOR `move_to_library()` (Task waehrend eines gemockten, kuenstlich verzoegerten Loudness-Normalisierungsschritts abgebrochen) | `CancelledError` propagiert bis zum Aufrufer; `original_path`-Datei bleibt bewusst unangetastet (Fall A, kein Cleanup erwartet); kein `library_path` wurde je erzeugt | Nein — dieses Verhalten ist bereits heute korrekt (kein Fund), dient als Referenz-/Nicht-Regressions-Test |
| 2 | Cancellation WAEHREND `write_tags()` (Task abgebrochen, waehrend ein gemocktes, kuenstlich verzoegertes `write_tags()` noch laeuft; `move_to_library()` lief vorher echt durch, reale Datei liegt unter `library_path`) | `CancelledError` propagiert; `library_path`-Datei existiert NACH dem Abbruch NICHT mehr (sofortiger Cleanup) | **Ja** — vor dem Fix bleibt die Datei liegen, da `except Exception` nicht greift |
| 3 | Wie Test 2, aber `Path.unlink()` wird gezielt zum Scheitern gebracht (`OSError` simuliert) | Cleanup-Fehler wird nur geloggt, `CancelledError` propagiert trotzdem unveraendert (kein Verschlucken durch einen sekundaeren Fehler) | Ja (fuer den "kein Verschlucken trotz Cleanup-Fehler"-Teil; vor Fix existiert der Zweig gar nicht) |
| 4 | Cancellation NACH Cache-Store, waehrend Auto-Learning (Fall C) | `CancelledError` propagiert; `library_path`-Datei wird ebenfalls entfernt (derselbe `except`-Zweig deckt auch dieses spaetere Fenster ab, da er bis Funktionsende reicht) | Ja |
| 5 | `CancelledError` wird tatsaechlich weitergereicht (kein Verschlucken) | expliziter `pytest.raises(asyncio.CancelledError)` um den `task.cancel()`-Aufruf/`await task` | Ja (fehlt heute als expliziter Vertrags-Test, auch wenn das Verhalten schon vorher "zufaellig" korrekt war, da nichts es abfaengt) |
| 6 | Kein unbeteiligtes Artefakt wird geloescht | zweite, unabhaengige Datei in `LIBRARY_DIR` bleibt nach Cancellation unangetastet | Ja (Sicherheits-Regressionstest, analog zum DL-02-Muster `TestUnrelatedArtifactIsProtected`) |
| 7 | Normaler Erfolg bleibt unveraendert | kompletter Erfolgsdurchlauf ohne Cancellation — `MetadataResult(success=True, ...)`, Datei bleibt bestehen, kein Cleanup-Aufruf | Ja (Erfolgs-Regressionsschutz) |
| 8 | Normale Exception bleibt unveraendert | bestehender `tag_err`-Fall (Test-Analogon zu `tests/test_metadata_processor_happy_path.py::test_tag_write_failure_after_successful_move_cleans_up`, falls vorhanden, sonst neu) laeuft weiterhin identisch, `except Exception`-Zweig unberuehrt vom neuen `CancelledError`-Zweig | Nein — reiner Nicht-Regressions-Nachweis |
| 9 | Zwei parallele `process_single_track()`-Aufrufe, einer wird gecancelt, der andere laeuft normal durch (`asyncio.gather`, analog zum DL-02-Muster `TestClosureIsolationAcrossConcurrentDownloads`) | nur die Datei des gecancelten Aufrufs wird entfernt, die des erfolgreichen bleibt bestehen — keine Zustandsvermischung zwischen parallelen Tasks | Ja (fuer den Isolations-Nachweis) |

**Technische Umsetzung des `task.cancel()`-Timings:** analog zum bereits in
dieser Session etablierten Muster aus den AE-10/AE-11/AE-12-Event-Loop-
Blocking-Tests (`hb_task.cancel()`) — ein gemocktes `write_tags()`
(`monkeypatch.setattr(processor.tag_writer.__class__, "write_tags", ...)`)
mit einem kurzen `time.sleep()` (laeuft im echten Thread via
`asyncio.to_thread`, blockiert den Test-Event-Loop nicht), waehrenddessen
der Haupt-Task via `asyncio.create_task(process_single_track(...))` +
`task.cancel()` nach einem kurzen `await asyncio.sleep(0)` gezielt
abgebrochen wird — deterministisch, kein Race auf echte Timing-Fenster.

---

## 11. Betroffene Dateien/Funktionen (fuer einen kuenftigen Fix, NICHT umgesetzt)

- `services/metadata/enhanced_metadata_processor.py` — `process_single_track()`:
  neue `library_path: Optional[Path] = None`-Vorabdeklaration (Zeile ~255),
  neue `except asyncio.CancelledError:`-Klausel (nach Zeile 1054, vor der
  bestehenden `except Exception as e:`).
- **Keine weitere Datei betroffen** — insbesondere KEINE Aenderung an
  `services/downloader/download_artifact_cleanup.py` noetig (Korrektur
  gegenueber der in PHASE 1 noch offen gelassenen Option einer neuen
  LIBRARY_DIR-Cleanup-Funktion — das bereits vorhandene inline
  `tag_err`-Idiom reicht aus und wird 1:1 repliziert).

---

## 12. Scope-Verifikation

```
DL-01: JA

DUP-01: NEIN
DUP-02: NEIN
DUP-03: NEIN
DUP-05: NEIN
DUP-08: NEIN
DL-02: NEIN
P2: NEIN
P3: NEIN
Metadata-Qualitaet: NEIN
Artist-/Titel-Erkennung: NEIN
Genre: NEIN
Cover: NEIN
Lyrics: NEIN
Architektur-Refactoring: NEIN
allgemeine Optimierungen: NEIN
```

---

## 13. PHASE-2E-Implementierungsempfehlung

DL-01 zur Implementierung freigeben, mit dem in Abschnitt 7 skizzierten Fix:

1. `library_path: Optional[Path] = None` vor dem bestehenden `try`
   vordeklarieren (analog `original_path`).
2. Neue `except asyncio.CancelledError:`-Klausel ergaenzen, die exakt das
   bereits geprüfte `tag_err`-Loesch-Idiom (Zeile 909-920) auf `library_path`
   anwendet und zwingend mit `raise` (bare) endet.
3. Kein `finally`, kein `asyncio.shield()`, keine neue Cleanup-Funktion,
   keine Aenderung an DOWNLOAD_DIR-seitigem Cleanup (bleibt beim
   bestehenden `cleanup_single_download_artifact()`-Aufruf im
   `except Exception`-Zweig, unveraendert).
4. Regressionstests gemaess Abschnitt 10 (mindestens Tests 2, 3, 5, 6, 9
   sind diskriminierend/pflicht; Tests 1, 4, 7, 8 sind wichtige
   Nicht-Regressions-Absicherungen).
5. Git-Stash-Diskriminierung fuer jeden neuen Test gegen den Vor-Fix-Stand,
   wie in dieser Session etabliert.
6. Vollstaendige Testsuite (Referenz: 1141 passed / 0 failed nach DL-02)
   muss danach weiterhin gruen sein.
7. Manuelle Code-Review vor Commit (gleiches Format wie bei DL-02), danach
   `COMMIT-FREIGABE` abwarten wie bei allen vorherigen Fixes dieser Phase.

Nach DL-01 sind alle 4 als "PHASE 2 SHOULD IMPLEMENT" vorgesehenen P1-Fixes
mit Cleanup-/Registrierungsbezug abgeschlossen (DUP-02, DUP-01+DUP-08,
DL-02, DL-01) — offen bliebe danach nur noch DUP-03 (Live/Version-
False-Positive, unabhaengig, kleinster verbleibender P1-Fund).

---

## Explicit Non-Actions (PHASE 2D, Audit-Teil)

```
[x] Kein Produktionscode geändert
[x] Kein Testcode geändert
[x] Kein Refactoring
[x] Kein Commit
[x] Kein Push
[x] Kein PR
[x] DUP-03/DUP-05 nicht behandelt
[x] weitere P2/P3 nicht behandelt
[x] Metadata-Qualität/Artist/Titel/Genre/Cover/Lyrics nicht behandelt
[x] Architektur-Refactoring nicht behandelt
[x] Test-Bot NICHT gestartet, kein manueller End-to-End-Test
```

**Status:** PHASE 2D (Audit) abgeschlossen. Wartet auf manuelle Freigabe für
PHASE 2E (DL-01-Implementierung) gemäß
`docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md`.
