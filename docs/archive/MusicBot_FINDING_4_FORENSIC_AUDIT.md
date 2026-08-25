# FINDING-4 — Forensic Deep Audit

## 1. Finding Summary

FINDING-4 (Phase 4, HIGH) beschreibt zwei zunächst getrennt wirkende
Symptome irreführender Telegram-Fehlerberichterstattung:

- **Variante A (Single-Track)**: erschöpft der Retry-Loop alle Versuche,
  erhält der Nutzer **keine** Fehlermeldung — die Telegram-Statusnachricht
  bleibt stehen.
- **Variante B (Playlist)**: scheitern in einer Playlist alle Tracks
  einzeln, zeigt der Bot trotzdem "✅ Playlist erfolgreich
  heruntergeladen!".

Dieses Dokument weist nach: **beide Symptome haben dieselbe Grundursache**
— `handle_youtube_links()` und seine Erfolgsmeldungs-Helfer prüfen an der
entscheidenden Stelle nur ein *unzuverlässiges* Top-Level-`success`-Flag,
statt die bereits vorhandenen, korrekten Detail-Daten (`error`,
`successful_tracks`/`total_tracks`) auszuwerten. Die beiden Varianten sehen
unterschiedlich aus, weil Single-Track- und Playlist-Fehler auf zwei
strukturell verschiedene Arten (Exception vs. Rückgabewert) signalisiert
werden — nicht, weil zwei unabhängige Bugs vorliegen.

## 2. Baseline / Repository State

```text
git status                → clean (vor Audit-Beginn)
git branch --show-current → main
git rev-parse HEAD        → 2d0808450972026a9b1311f1144c16c0c4471266
git log --oneline -3:
  2d08084 docs: complete Phase 4 failure-path audit
  eea8cd8 Merge pull request #53 from dkmd89-dev/baseline-v3-freeze
  e4e2815 docs: Baseline v3 einfrieren, neue Findings gehen ab jetzt in v4

python3 -m pytest tests/ -q
  → 1063 passed, 0 failed, 19 subtests passed, ~72s
```

Repository entspricht dem in Phase 4 auditierten Zustand
(`docs/MusicBot_PHASE4_FAILURE_PATH_AUDIT.md` wurde zwischenzeitlich vom
Nutzer committet, keine Code-Änderung). Kein Reinterpretations-Bedarf,
Audit wird fortgesetzt.

## 3. Original Evidence

Aus `docs/MusicBot_PHASE4_FAILURE_PATH_AUDIT.md`, Abschnitt 9/19: beide
Pfade erreichbar, 0 direkte Testabdeckung für
`handle_youtube_links()`/`handle_playlist_success()`/
`handle_single_track_success()`, Exception-Propagation und
Track-Isolation ansonsten korrekt verifiziert. Dieses Audit vertieft
genau diese beiden Symptome, ohne bereits geschlossene Findings
(FINDING-1/2/3 sowie alle CLOSED/HISTORICAL-Punkte) erneut zu öffnen.

## 4. Complete Single-Track Call-Chain Reconstruction

| # | Function | File:Line | Caller | Input | Output | Exception-Verhalten | Return-Verhalten |
|---|---|---|---|---|---|---|---|
| 1 | `handle_url()` | `klassen/download_handler.py:514` | Telegram-Dispatcher (außerhalb Scope) | `Update`, `Context` | — | Keine eigenen Exceptions | Nach URL-Gate: `async with semaphore: await handle_youtube_links(...)` |
| 2 | `handle_youtube_links()` | `klassen/download_handler.py:543` | `handle_url()` | `Update`, `Context` | — (sendet Telegram-Nachrichten als Seiteneffekt) | Äußeres `except Exception as e:` (Zeile 660) → `handle_download_failure(str(e))` | `return` an mehreren Stellen (Zeile 586 nach `raise`, 630, 645); kein Rückgabewert an Aufrufer |
| 3 | `self.downloader.download_audio(url)` | `services/downloader/downloader.py:37` | `handle_youtube_links()` Zeile 582 | `url: str` | `Dict[str, Any]` | `except Exception as e: ...raise` (Zeile 115-119) — reine Weiterleitung | Bei Erfolg: reich befülltes Dict; bei `success:False`: `{"success": False, "error": error_message}` (Zeile 57-60, **2 Keys, kein Rückgriff auf `raise`**) |
| 4 | `enhanced_download_with_retry()` | `services/downloader/download_utils.py:224` | `download_audio()` Zeile 47 | `url, chat_id, update_id, logger_factory` (kein `status_callback`!) | `Dict[str, Any]` | Fängt intern `DownloadError`/`Exception` im Retry-Loop, wirft **nie** über die eigene Funktionsgrenze hinaus (verifiziert, Zeile 283-387) | Erschöpfte Retries: `{"success": False, "error": "Download nach {max_retries} Versuchen fehlgeschlagen: {last_error}"}` (Zeile 365-368) oder `{"success": False, "error": "Unerwarteter Fehler: {last_error}"}` (Zeile 380-381) |
| 5 | `_process_single_download()` | `download_utils.py:762` | `enhanced_download_with_retry()` Zeile 338 | `url, video_info, ydl_opts, ...` | `Dict[str, Any]` (Erfolg) oder **wirft** `DownloadError` | `except Exception as e: raise DownloadError(f"Single-Download fehlgeschlagen: {e}")` (Zeile 906-908) — **jeder** interne Fehlschlag (Download UND Metadaten, Zeile 850-854 raist ebenfalls `DownloadError` bei `enhanced_result.success == False`) wird zur Exception | Nur bei vollem Erfolg: `build_single_track_result(...)`-Dict |
| 6 | `handle_download_failure()` | `klassen/download_handler.py:670` | `handle_youtube_links()` Zeile 664 (nur im `except`-Block) | `error_message: str` | — | Fängt `TelegramError` beim Versand (Zeile 689) | Editiert `self.status_msg` mit Fehlertext, kein Rückgabewert |

## 5. Single-Track Failure — Proof

Exakte Objekt-Rekonstruktion für den Fall "erschöpfte Retries wegen
`DownloadError`" (der häufigste, "normale" Fehlschlagsgrund — z. B. Video
nicht mehr verfügbar):

```python
# enhanced_download_with_retry(), Zeile 365-368, letzter Versuch:
{
    "success": False,
    "error": "Download nach 3 Versuchen fehlgeschlagen: Download-Fehler [GENERIC]: <yt-dlp-Meldung>"
}
```

Dies ist das **vollständige** Objekt — genau zwei Schlüssel, keine
`type`, `title`, `track_info` oder andere Felder (verifiziert durch
direkte Code-Lektüre, nicht angenommen).

```python
# download_audio(), Zeile 57-60:
if not download_result or not download_result.get("success"):
    error_message = download_result.get("error", "Unbekannter Fehler.")
    self.logger.error(f"❌ Download fehlgeschlagen: {error_message}")
    return {"success": False, "error": error_message}
```

`download_audio()` gibt **denselben zweischlüssigen Shape** unverändert
zurück — **keine Exception** wird geworfen.

```python
# handle_youtube_links(), Zeile 582-586:
download_result = await self.downloader.download_audio(url)
if not download_result:
    ...
    raise ValueError(...)          # NICHT erreicht: download_result ist ein
                                    # nicht-leeres Dict ({"success": False, "error": ...}),
                                    # `not download_result` ist False.
```

```python
# Zeile 592-607:
results_list = [download_result]   # da kein list-Typ
for idx, res in enumerate(results_list, 1):
    if not (isinstance(res, dict) and res.get("success")):
        self.logger.warning(...)   # NUR Log, keine Telegram-Aktion
        continue                   # processed_results bleibt LEER
```

```python
# Zeile 636-645:
await self._update_status(*_YT.LIBRARY, "FilenameFixerTool")   # Telegram: "5/6 Bibliothek organisieren"
await self._update_status(*_YT.SUMMARY, "DownloadHandler")     # Telegram: "6/6 Zusammenfassung"
if not processed_results:
    self.logger.warning("🤷 [YT-PIPELINE] Keine erfolgreichen Ergebnisse")
    return                                                      # STILLE Rückkehr
```

**Präzisierung gegenüber Phase 4**: die Telegram-Statusnachricht bleibt
nicht bei einem *Zwischen*-Schritt stehen, sondern erreicht **exakt** den
Endzustand `"6️⃣ ██████████ 6/6 │ Zusammenfassung\n⚙️ [DownloadHandler]"`
(volle Fortschrittsleiste) und wird danach **nie wieder verändert** — dies
wirkt aus Nutzersicht sogar wie ein abgeschlossener, nicht wie ein
hängender Vorgang, was die Irreführung eher verstärkt als Phase 4 zunächst
andeutete.

`handle_download_failure()` (Zeile 670) wird **ausschließlich** vom
äußeren `except Exception as e:`-Block (Zeile 660-664) erreicht — dieser
greift hier nicht, da keine Exception geworfen wurde.

## 6. Result Contract Analysis

Producer/Consumer-Matrix, aus tatsächlichem Code rekonstruiert (repo-weite
Suche nach `success`, `DownloadResult`, `handle_download_failure`,
`handle_youtube_links`, Playlist-Aggregation):

| Producer | Result Shape | Success-Bedeutung | Failure-Bedeutung | Consumer(s) |
|---|---|---|---|---|
| `enhanced_download_with_retry()` — Single, Erfolg | `{"success": True, "type": "single", "track_info": {...}, "processor_instance": obj}` | Top-Level `True` korrekt | — | `download_audio()` |
| `enhanced_download_with_retry()` — Retry erschöpft | `{"success": False, "error": str}` | — | Top-Level `False`, **flacher String**, kein strukturiertes Detail | `download_audio()` |
| `enhanced_download_with_retry()` — Playlist, **JEDER Ausgang inkl. 0/N** | `{"success": True, "type": "playlist", "tracks": [...], "processor_instance": obj, "total_tracks": int, "successful_tracks": int}` | Top-Level `True` ist **unconditional** — spiegelt NICHT den tatsächlichen Track-Erfolg wider (Zeile 320-329) | Fehlschlag ausschließlich in `tracks[i]["success"]` und `successful_tracks` kodiert, **nie** im Top-Level-Flag sichtbar | `download_audio()` |
| `_process_playlist_download()` — pro Track | `DownloadResult(success=False, title=str, error=str).to_dict()` | — | Pro-Track-Flag, isoliert | Wird von der eigenen Funktion in `tracks`-Liste gesammelt; **niemals einzeln** von `handle_youtube_links()` inspiziert |
| `download_audio()` — Weiterleitung | siehe oben, plus für Playlists: `final_result["title"] = "Playlist"` (Default, da `playlist_title` nie gesetzt wird), keine `artist`-Angabe | identisch zur Quelle | identisch zur Quelle | `handle_youtube_links()` |
| `handle_youtube_links()`-Schleife | prüft **ausschließlich** `res.get("success")` auf der obersten Ebene | — | Alles mit `success != True` wird per `continue` verworfen — **inklusive** des ganzen `{"success": False, "error": ...}`-Downloadfehlschlags | `processed_results` |

**Klassifikation des Ergebnisvertrags**: **implizit und auf zwei
verschiedene, sich widersprechende Arten interpretiert.** Es gibt keine
zentrale Vertragsdefinition (kein Typ, kein Schema, keine Validierung) —
jeder Producer entscheidet für sich, was `success` bedeutet. Für Singles
ist das Top-Level-Flag **akkurat** (weil `_process_single_download()`
jeden Fehlschlag zur Exception macht, die der Retry-Loop selbst wieder in
ein akkurates `success:False` übersetzt) — das Problem liegt hier
ausschließlich beim **Konsumenten** (`handle_youtube_links()` wertet das
akkurate `False` nicht in eine Nutzer-Meldung um). Für Playlists ist das
Top-Level-Flag selbst **irreführend** (immer `True`), während die
akkuraten Daten (`successful_tracks`) tiefer verschachtelt vorliegen und
vom Konsumenten ignoriert werden.

**Es handelt sich nicht um mehrere redundante Repräsentationen, die
vereinheitlicht werden müssten** — jede Form (`return {"success": False}`,
`DownloadResult(success=False, ...)`, `raise DownloadError`) hat einen
klaren, jeweils sinnvollen Zweck an ihrer Entstehungsstelle. Das
tatsächliche Problem ist ausschließlich, dass die **Konsumenten-Seite**
(`handle_youtube_links()`/`handle_playlist_success()`/
`handle_single_track_success()`) diese bereits vorhandene Information
nicht vollständig auswertet.

## 7. Exception vs. Return-Value Semantics

```text
FAILURE
   │
   ├── Exception (aus _process_single_download(), Zeile 906-908 sowie
   │   jedem sonstigen unerwarteten Fehler zwischen Extraktion und
   │   Rueckgabe)
   │      ↓
   │   Retry-Loop faengt (Zeile 357/371), erschoepft Versuche,
   │   uebersetzt zurueck in {"success": False, "error": ...}
   │      ↓
   │   download_audio() reicht Dict unveraendert durch (KEINE Exception
   │   mehr an dieser Stelle)
   │      ↓
   │   handle_youtube_links(): res.get("success") == False → continue
   │   → STILLE Rueckkehr (kein handle_download_failure()-Aufruf)
   │
   └── Return-Value (aus _process_playlist_download(): pro-Track
       DownloadResult(success=False, ...), NIE als Exception nach oben
       gereicht)
          ↓
       In `tracks`-Liste gesammelt, Playlist-Wrapper meldet TROTZDEM
       {"success": True, ...}
          ↓
       download_audio() / handle_youtube_links() nehmen das Top-Level
       True als bare Muenze
          ↓
       handle_playlist_success() → handle_single_track_success() →
       "✅ Playlist erfolgreich heruntergeladen!" trotz 0/N
```

**Beweis der impliziten Regel**: Es existiert **keine geschriebene Regel**
"Exceptions = nutzersichtbare Fehler, Rückgabewerte = normaler
Kontrollfluss" — dieses Verhalten ist eine **Nebenwirkung** der jeweils
lokal getroffenen Design-Entscheidung an zwei verschiedenen Stellen
(`_process_single_download()` wirft, `_process_playlist_download()` sammelt
Rückgabewerte), kombiniert mit der Tatsache, dass
`handle_youtube_links()`s äußerer `except`-Block der EINZIGE Aufrufer von
`handle_download_failure()` ist. **Diese Kopplung ist nicht
dokumentiert, nicht getestet und — wie die beiden Symptome zeigen —
unvollständig**, damit **akzidentell**, nicht bewusst als Vertrag
entworfen.

## 8. `handle_youtube_links()`-Analyse

Rolle als Orchestrierungsgrenze:

- **Besitzt nutzersichtbares Reporting?** Teilweise — ruft
  `handle_download_failure()`/`handle_playlist_success()`/
  `handle_single_track_success()`/`_handle_duplicate_found()` auf, aber
  nur entlang bestimmter Pfade (siehe Exit-Pfad-Baum unten).
- **Besitzt Erfolg/Fehlschlag-Aggregation?** Teilweise — filtert
  `results_list` nach `res.get("success")`, aber verlässt sich dabei
  vollständig auf das (für Playlists irreführende) Top-Level-Flag.
- **Reines Dispatching?** Nein — enthält eigene Entscheidungslogik
  (Zeile 603-607, 610-630, 643-652).
- **Nimmt an, Exceptions = Fehlschlag?** Ja, implizit — der einzige
  garantiert korrekte Fehlerpfad ist der äußere `except`-Block.
- **Inspiziert `result.success`?** Ja, aber nur auf oberster Ebene, nie
  `successful_tracks`/`total_tracks`.
- **Aggregiert Playlist-Ergebnisse?** Nein — reicht das bereits
  aggregierte `tracks`/`successful_tracks` unverändert an
  `handle_playlist_success()` durch, ohne selbst nachzurechnen.
- **Unterscheidet 0/N, Partial, Complete?** **Nein — an keiner Stelle.**

Exit-Pfad-Baum (verifiziert, Zeilen in Klammern):

```text
INPUT (URL)
  │
  ├─ Nicht unterstützte URL → Telegram-Hinweis, return (handle_url, 529-532)
  │
  └─ handle_youtube_links()
      │
      ├─ Duplikat erkannt → _handle_duplicate_found(), return (577)
      │
      ├─ SINGLE
      │   ├─ SUCCESS → processed_results=[1], Zeile 649 → handle_single_track_success() [KORREKT]
      │   ├─ FAILURE (success:False-Rueckgabe) → processed_results=[], Zeile 645 → STILLE return [FINDING-4a]
      │   └─ EXCEPTION (irgendwo in try-Block) → aeusserer except (660) → handle_download_failure() [KORREKT]
      │
      └─ PLAYLIST
          ├─ ALL SUCCESS (N/N) → handle_playlist_success() → Redirect → handle_single_track_success() → "erfolgreich", Tracks: N/N [KORREKT]
          ├─ PARTIAL SUCCESS (1..N-1 / N) → identisch: "erfolgreich", Tracks: k/N [Akzeptiertes Verhalten, siehe §9]
          ├─ ALL FAILURE (0/N) → identisch: "erfolgreich", Tracks: 0/N [FINDING-4b — WIDERSPRUCH]
          └─ EXCEPTION vor/waehrend Playlist-Verarbeitung (z. B. PlaylistProcessor wirft) → aeusserer except (660) → handle_download_failure() [KORREKT]
```

## 9. Playlist Aggregation Analysis

Konkrete Ausführung für 3 Tracks, alle fehlschlagend, Schritt für Schritt
(kein Code verändert — reine Nachvollziehung):

```python
# _process_playlist_download(), Zeile 489-601, pro Track (idx=1,2,3):
#   Download schlaegt fehl (Zeile 545) ODER Exception im Verarbeitungsblock
#   (Zeile 587-601) → jeweils:
results.append(
    DownloadResult(success=False, title=track_title, error="...").to_dict()
)
# Nach der Schleife: results = [
#   {"success": False, "title": "Track 1", "error": "...", ...Default-Felder...},
#   {"success": False, "title": "Track 2", "error": "...", ...},
#   {"success": False, "title": "Track 3", "error": "...", ...},
# ]
```

```python
# enhanced_download_with_retry(), Zeile 307-329:
tracks = results   # (die obige 3-elementige Liste, via _process_playlist_download() zurückgegeben)
return {
    "success": True,                 # UNCONDITIONAL
    "type": "playlist",
    "tracks": tracks,                # 3x success:False
    "processor_instance": enhanced_processor,
    "total_tracks": 3,
    "successful_tracks": 0,          # korrekt berechnet — aber ungenutzt in der Aufrufkette
}
```

```python
# download_audio(), Zeile 74-107:
final_result = {
    "success": True,
    "type": "playlist",
    "processing_stats": {...},
    "tracks": [3x success:False],
    "title": "Playlist",             # Default, da playlist_title nie gesetzt wird
}
```

```python
# handle_youtube_links(): results_list = [final_result]
# res.get("success") == True → passiert den Filter
# _process_single_download_result(res): Punkt A (type == "playlist") → return result unveraendert
# processed_results = [final_result]
# len==1 and type=="playlist" → handle_playlist_success([final_result])
```

```python
# handle_playlist_success(), Zeile 491-495:
if results and results[0].get("type") == "playlist":
    await self.handle_single_track_success(results[0])   # REDIRECT
    return
```

```python
# handle_single_track_success(final_result), Zeile 451-489:
title = "Playlist"; artist = "?"
# Duplikat-Registrierung: artist == "?" → Bedingung false → uebersprungen (korrekt, kein Muell-Eintrag)
msg = self.result_reporter.build_final_summary_message(final_result, stats, dup_stats)
```

```python
# build_final_summary_message(), download_result_reporter.py:246-255:
is_pl = True
ok = sum(1 for t in tracks if t.get("success"))   # = 0
header = "✅ Playlist erfolgreich heruntergeladen!"   # UNCONDITIONAL — kein Bezug zu `ok`
meta = [..., f"🎵 Tracks   : {ok}/{len(tracks)}", ...]  # "Tracks   : 0/3"
```

**Finale, an Telegram gesendete Nachricht** (via `_send_report_message()`,
editiert `self.status_msg`):

```text
✅ Playlist erfolgreich heruntergeladen!

🎤 Künstler : Unbekannt
💿 Album    : Unbekannt
📅 Jahr     : N/A
🎵 Tracks   : 0/3
📡 Quelle   : 📺 YouTube
...
```

Wiederholung der Analyse für die übrigen Fälle (nur Ergebnis, Mechanik
identisch):

| Fall | `ok` | Header | Konsistent? |
|---|---|---|---|
| 3/3 Erfolg | 3 | "✅ Playlist erfolgreich heruntergeladen!" | Ja |
| 1/3 Erfolg | 1 | "✅ Playlist erfolgreich heruntergeladen!" | **Fragwürdig, aber vom bestehenden Test `test_playlist_type_uses_playlist_header_and_track_counts` bereits als akzeptiertes Verhalten charakterisiert — siehe §10** |
| 0/3 Erfolg | 0 | "✅ Playlist erfolgreich heruntergeladen!" | **Nein — direkter Widerspruch zwischen Header und Zahlen (FINDING-4b)** |

## 10. 0/N, Partial, und Full-Success Semantics

Es existiert **keine schriftlich dokumentierte Produkt-Spezifikation**
dafür, was eine "erfolgreiche Playlist-Verarbeitung" bedeutet — weder in
`CLAUDE.md` noch in `README.md` noch in Docstrings von
`build_final_summary_message()`/`handle_playlist_success()`. Die
Semantik muss aus dem Code und dem bestehenden, akzeptierten Test
hergeleitet werden.

**Hergeleitete, implizite Ist-Semantik**: "Playlist erfolgreich" bedeutet
aktuell "die Playlist-Verarbeitung ist ohne Absturz durchgelaufen" —
**nicht** "mindestens ein Track wurde geliefert". Der bestehende Test
`test_playlist_type_uses_playlist_header_and_track_counts` (2/3 Erfolg)
bestätigt genau diese Lesart als **bewusst akzeptiertes Verhalten** — der
Header wird absichtlich unabhängig von der genauen Erfolgsquote verwendet,
die "Tracks: k/N"-Zeile liefert die eigentliche Information nach.

**Wo diese Semantik zusammenbricht**: bei `ok == 0` gibt es **nichts
Erfolgreiches mehr, worüber der Header noch sinnvoll "erfolgreich"
behaupten könnte** — der Bruch ist nicht die grundsätzliche Design-
Entscheidung ("Header ist unabhängig von der Quote"), sondern der fehlende
Sonderfall an der einzigen Stelle, an der die Quote buchstäblich Null ist.

**Antwort auf die geforderte Frage** ("welche Nachricht SOLLTE der Nutzer
für 0/N, 1/N, N/N erhalten"):

- **N/N**: bestehendes Verhalten korrekt, keine Änderung nötig.
- **1/N (bis N-1/N)**: bestehendes Verhalten ist ein **bereits
  charakterisiertes, akzeptiertes** Design (siehe Test) — dieses Audit
  bewertet es NICHT als Finding, da es nicht dem "Widerspruch zwischen
  Zustand und Meldung" entspricht, den Auftrags-Abschnitt 11 als
  Kernkriterium nennt (der Header behauptet nicht "alles" erfolgreich,
  die Zahlen daneben relativieren korrekt).
- **0/N**: einzige echte Grenze, an der Header und Fakten sich
  widersprechen — sollte denselben Fehlschlags-Mechanismus wie
  Variante A nutzen (`handle_download_failure()`), nicht eine dritte,
  neu zu erfindende Nachrichtenform.

Dies ist **kein Fall von "0/N wurde absichtlich als Erfolg behandelt"**
— es gibt keinerlei Code-Kommentar, Docstring oder Test, der diese
Entscheidung begründet. Es ist die **fehlende untere Grenze** einer sonst
bewusst gewählten, toleranten Playlist-Semantik.

## 11. Telegram State Lifecycle

Reale Zustände (aus Code, nicht angenommen):

```text
START            → update.message.reply_text("▶️ Anfrage wird gestartet...") → self.status_msg gesetzt
DOWNLOADING (1-6) → self.status_msg.edit_text(...) via _update_status(), pro Schritt
SUCCESS           → self.status_msg.edit_text(<Erfolgs-Zusammenfassung>) via _send_report_message()
FAILURE           → self.status_msg.edit_text(<Fehlermeldung>) via _send_report_message() (in handle_download_failure())
```

Beobachtete Ausgänge und ihr exakter Codepfad:

| Ausgang | Endzustand der Telegram-Nachricht | Codepfad |
|---|---|---|
| Erfolgreicher Single-Download | Erfolgs-Zusammenfassung | `handle_single_track_success()` → `_send_report_message()` |
| Erfolgreiche Playlist (auch Partial) | Erfolgs-Zusammenfassung (ggf. mit niedriger Quote in den Metadaten) | `handle_playlist_success()` → Redirect → `handle_single_track_success()` |
| Duplikat erkannt | Duplikat-Meldung | `_handle_duplicate_found()` |
| Datei-Konflikt (spätes Duplikat) | Duplikat-Meldung (Typ "file_conflict") | Zeile 610-630 |
| Interne Exception (irgendwo im try-Block) | Fehlermeldung | `handle_download_failure()` |
| **Single-Track: alle Retries erschöpft** | **Letzter Fortschrittsschritt "6/6 Zusammenfassung" — für immer** | **Zeile 643-645, KEIN weiterer Edit** |
| **Playlist: alle Tracks fehlgeschlagen (0/N)** | **Erfolgs-Zusammenfassung mit "Tracks: 0/N"** | **`handle_single_track_success()`, Header unconditional** |

**Stale UI ist demonstriert möglich** (Variante A) — nicht nur theoretisch,
sondern der einzige mögliche Endzustand bei erschöpften Retries ohne
begleitende Exception.

## 12. Reporting Authority

Autoritativ für **User-Facing-Text** ist ausschließlich
`klassen/download_handler.py` (`handle_download_failure()`,
`handle_playlist_success()`, `handle_single_track_success()`,
`_handle_duplicate_found()`, jeweils via `_send_report_message()`) —
`services/downloader/download_result_reporter.py` liefert seit ARCH-007/P-2
nur noch **Text**, sendet selbst nichts (bereits historisch etabliert,
hier bestätigt). Es gibt **keine konkurrierenden, unabhängigen
Entscheidungspunkte**, die sich widersprechen könnten — die Autorität ist
sauber an einer Stelle gebündelt.

**Autoritativ für Erfolg/Fehlschlag-Feststellung** ist dagegen verteilt
und **nicht konsistent**:

1. `enhanced_download_with_retry()` entscheidet für Singles akkurat, für
   Playlists strukturell unvollständig (Top-Level immer `True`).
2. `handle_youtube_links()`s Filter-Schleife entscheidet ein zweites Mal,
   nur anhand des (für Playlists bereits unzuverlässigen) Top-Level-Flags.
3. `build_final_summary_message()` entscheidet ein drittes Mal, welcher
   Header gewählt wird — wieder ohne Rückgriff auf `ok`/`successful_tracks`
   für die Header-Wahl (nur für die Zahlen-Anzeige).

Diese drei Entscheidungspunkte **können nicht widersprüchlich im Sinne von
"einer sagt Erfolg, ein anderer Fehlschlag"** auseinanderlaufen (da sie
sequenziell denselben, bereits feststehenden Wert weiterreichen) — das
eigentliche Problem ist, dass **keiner von ihnen** an der Stelle, wo es
zählt (0/N), die bereits korrekt berechnete `successful_tracks`-Information
nutzt, um seine eigene Entscheidung zu korrigieren.

## 13. Failure Reason Preservation

Für Variante A (Single-Track, Retry erschöpft):

```text
last_error (str, aus urspruenglicher Exception, download_utils.py:358/372)
   ↓ PRESERVED
{"success": False, "error": f"Download nach {max_retries} Versuchen fehlgeschlagen: {last_error}"}
   ↓ PRESERVED (download_audio() reicht error_message unveraendert durch)
{"success": False, "error": error_message}
   ↓ VERWORFEN — handle_youtube_links() liest `res.get("error")` an dieser
     Stelle NIRGENDS aus (nur `res.get("success")` und `res.get("title")`)
```

Die Fehlerursache **ist im Objekt vorhanden**, bis zu dem Punkt, an dem sie
gebraucht würde (`if not processed_results: return`) — sie geht nicht durch
technische Transformation verloren, sondern durch **schlichtes
Nicht-Auslesen** an der letzten Stelle. Ein Fix müsste diesen bereits
vorhandenen `error`-Wert lediglich an `handle_download_failure()`
weiterreichen — keine neue Datenquelle nötig.

## 14. Retry Semantics

- **Retryable Failure**: `DownloadError` (spezifisch behandelt, Zeile 357)
  und jede generische `Exception` (Zeile 371) — beide lösen bei
  Nicht-letztem Versuch `await asyncio.sleep(2**attempt)` aus.
- **Nach letztem Versuch**: strukturierte `{"success": False, "error": ...}`-Rückgabe,
  **kein Unterschied im Objekt-Shape** zwischen einem Fehlschlag beim
  ersten und beim letzten Versuch — beide liefern denselben zweischlüssigen
  Dict-Typ (nur der Text unterscheidet sich).
- **Fehlerursache erhalten?** Ja, in `last_error`/`error`-Feld (siehe §13).
- **Besitzt der Retry-Layer Nutzer-Benachrichtigung?** **Nein — und das ist
  korrekt so.** `enhanced_download_with_retry()` erhält zwar einen
  `status_callback`-Parameter (Signatur, Zeile 228), dieser wird jedoch vom
  einzigen produktiven Aufrufer (`downloader.py:47-52`) **nie übergeben**
  (verifiziert — kein `status_callback=`-Argument im Aufruf). Der Retry-Layer
  manipuliert nirgends direkt Telegram-UI. Diese saubere Trennung ist
  bereits etabliert und sollte **nicht** aufgebrochen werden (Auftrags-
  Hinweis in Abschnitt 14 des Prompts bestätigt sich als bereits erfüllt).

## 15. Test Coverage

Repo-weite Suche (nicht nur Docstring-Erwähnungen) bestätigt Phase 4:

```text
grep -rln "handle_youtube_links\(" tests/*.py     → 0 Treffer
grep -rln "handle_playlist_success\(" tests/*.py  → 0 Treffer (nur Docstring-Erwaehnung in
                                                       test_download_handler_send_report_message.py)
grep -rln "handle_single_track_success\(" tests/*.py → 0 Treffer (dito)
```

**Indirekte Abdeckung vorhanden für**:
- `enhanced_download_with_retry()`s Rückgabewert-Kontrakt selbst — 10
  dedizierte Tests in `tests/test_download_utils_retry.py` (RETRY-COVERAGE,
  bereits CLOSED) — decken exakt die in §5 zitierten `{"success": False,
  "error": ...}`-Formen ab, **aber nur bis zur Rückgabe von
  `enhanced_download_with_retry()` selbst**, nicht die Weiterverarbeitung
  in `download_audio()`/`handle_youtube_links()`.
- `build_final_summary_message()` — `test_download_result_reporter.py`
  deckt den 2/3-Fall ab (siehe §9), **keinen 0/3-Fall**.
- `_process_single_download_result()` (Punkt A/B/C/F) — eigene Testdatei
  vorhanden, deckt aber nur diese Guard-Logik, nicht den umgebenden
  Aufrufkontext in `handle_youtube_links()`.

**Fazit**: **direkte Coverage 0, indirekte Coverage deckt jeweils nur
Bausteine ab, nie die END-TO-END-Verkettung**, die genau an der
Verkettungsstelle bricht. Dies ist keine allgemeine Lücke, sondern deckt
sich exakt mit den beiden nachgewiesenen Fehlerpfaden.

## 16. Root Cause

**Eine gemeinsame Grundursache, zwei Erscheinungsformen:**

`handle_youtube_links()` (und die von ihm aufgerufenen
Erfolgsmeldungs-Helfer) behandeln das Top-Level-`success`-Flag des von
`download_audio()` gelieferten Ergebnisses als **hinreichend** für die
Entscheidung "war es erfolgreich genug, um dem Nutzer eine
Erfolgsmeldung zu zeigen" — obwohl dieses Flag für zwei unterschiedliche
Szenarien zwei unterschiedliche Verlässlichkeiten hat:

1. Für **Singles** ist es akkurat, wird aber bei `False` nicht in eine
   Nutzer-Meldung übersetzt (der einzige Übersetzungsmechanismus,
   `handle_download_failure()`, ist nur an den Exception-Pfad gekoppelt).
2. Für **Playlists** ist es strukturell **immer `True`**, unabhängig vom
   tatsächlichen Track-Ergebnis — die akkurate Information
   (`successful_tracks`) existiert, wird aber an der
   Header-Entscheidungsstelle nicht konsultiert.

Beide Symptome sind **keine unabhängigen Bugs**, sondern zwei
Manifestationen derselben fehlenden Prüfung: *"Wurde dem Nutzer tatsächlich
etwas geliefert, bevor eine Erfolgsmeldung gezeigt wird — und falls nicht,
wird garantiert `handle_download_failure()` (oder ein äquivalenter,
konsistenter Fehlschlags-Pfad) erreicht?"*

## 17. Severity Validation

Ausgangsklassifikation Phase 4: **HIGH**. Neubewertung mit vertiefter
Evidenz:

- **Nutzersichtbare Auswirkung**: hoch — betrifft direkt das
  Kernversprechen des Produkts (verlässliches Download-Feedback).
- **Silent Failure**: demonstriert (Variante A, E3).
- **False Success**: demonstriert (Variante B, E3, exakter End-to-End-Beweis
  inkl. finaler Telegram-Nachricht in §9).
- **Operative Auswirkung**: unnötige Wiederholungsversuche durch Nutzer
  (Variante A), fälschliches Vertrauen in ein leeres Ergebnis (Variante B).
- **Datenintegrität**: **keine** Auswirkung — kein Dateisystem-/Cache-Zustand
  ist betroffen, ausschließlich die Nutzer-Kommunikation.
- **Häufigkeit**: Variante A tritt bei **jedem** dauerhaft fehlschlagenden
  Single-Download auf (kein Randfall — jedes gelöschte/privatisierte
  YouTube-Video, jeder anhaltende Netzwerkfehler). Variante B erfordert,
  dass ALLE Tracks einer Playlist fehlschlagen (selteneres, aber reales
  Szenario, z. B. eine komplett private/gelöschte Playlist).
- **Exploitability**: nicht sicherheitsrelevant, kein Angriffsvektor.
- **Scope**: begrenzt auf den Reporting-Layer, keine Kaskadierung in
  andere Subsysteme.

**Ergebnis: HIGH bleibt gerechtfertigt** — begründet durch die hohe
Eintrittswahrscheinlichkeit von Variante A (kein Randfall) kombiniert mit
dem direkten, nutzersichtbaren Vertrauensbruch beider Varianten. Die
Abwesenheit von Datenintegritäts-/Security-Impact verhindert eine
Hochstufung zu CRITICAL, rechtfertigt aber keine Abstufung unter HIGH,
da "User-visible correctness" laut Auftrags-Priorisierung (Phase 4,
Abschnitt 20) über "Production reliability"/"Operational impact" rangiert
und hier direkt verletzt ist.

## 18. Candidate Fixes

| Option | Beschreibung | Bewertung |
|---|---|---|
| **A** — Retry-Loop wirft nach letztem Versuch eine Exception statt zurückzugeben | Würde Variante A automatisch über den bereits korrekten `except`-Pfad lösen | **Verworfen**: `enhanced_download_with_retry()` hat 10 dedizierte, bereits als RETRY-COVERAGE geschlossene Regressionstests (`tests/test_download_utils_retry.py`), die exakt den Rückgabewert-Vertrag prüfen — würde alle invalidieren. Ändert zudem einen bereits gut verstandenen, getesteten Baustein für ein Problem, das nachweislich beim Konsumenten liegt. Löst außerdem Variante B nicht (Playlist-Wrapper wirft nie). |
| **B** — Retry-Loop bleibt unverändert (Rückgabewert), Aufrufer (`handle_youtube_links()`) interpretiert das Ergebnis explizit | Direkter Fix am Ort der tatsächlichen Lücke | **Empfohlen für Variante A** — kein bestehender Test betroffen (0 direkte Coverage der Aufrufstelle), nutzt die bereits vorhandene, korrekte `error`-Information (§13) |
| **C** — `handle_youtube_links()`/`handle_playlist_success()` prüfen explizit `successful_tracks`/`ok` vor Header-Wahl | Direkter Fix für Variante B | **Empfohlen für Variante B** — betrifft nur den 0/N-Grenzfall, lässt die bewusst akzeptierte Partial-Success-Semantik (§10) unverändert |
| **D** — Neuer/erweiterter typisierter `DownloadResult`-Vertrag für alle Producer/Consumer | Würde den Vertrag formal vereinheitlichen | **Verworfen als Fix-Scope für dieses Finding**: Auftrag §17/18 fordert kleinste korrekte Intervention; die Analyse in §6 zeigt, dass die verschiedenen Shapes an ihren jeweiligen Entstehungsorten sinnvoll sind — das Problem ist Auswertung, nicht Struktur. Eine Vertragsvereinheitlichung wäre ein Refactoring mit hohem Streuungsradius (betrifft alle in §6 gelisteten Producer), unverhältnismäßig zum eigentlichen Fix. |
| **E** — Zentralisierung des User-Facing-Reportings | Reporting ist laut §12 bereits zentralisiert (`handle_download_failure()`/`_send_report_message()`) | **Nicht zutreffend** — die Lücke ist nicht mangelnde Zentralisierung, sondern fehlendes Routing zu der bereits zentralen Stelle für zwei konkrete Fälle. |

## 19. Recommended Minimal Fix

**WHERE:**
1. `klassen/download_handler.py::handle_youtube_links()`, unmittelbar nach
   Zeile 582 (`download_result = await self.downloader.download_audio(url)`),
   vor der bestehenden `if not download_result:`-Prüfung (Zeile 584).
2. `klassen/download_handler.py::handle_playlist_success()`, in der bereits
   vorhandenen Weiche `if results and results[0].get("type") == "playlist":`
   (Zeile 493), vor dem Redirect zu `handle_single_track_success()`.

**WHAT:**
1. Ergänzung einer expliziten Prüfung `if not download_result.get("success"):
   await self.handle_download_failure(download_result.get("error", "Unbekannter Fehler.")); return`
   — spiegelt exakt das bestehende Muster der `renamed_due_to_conflict`-Behandlung
   (früher Return mit korrektem User-Facing-Call) und nutzt den bereits
   vorhandenen, unveränderten `error`-Wert aus §13.
2. Vor dem Redirect: Berechnung von `ok = sum(1 for t in results[0].get("tracks", []) if t.get("success"))`
   und `total = results[0].get("total_tracks", len(results[0].get("tracks", [])))`;
   bei `total > 0 and ok == 0`: Aufruf von
   `self.handle_download_failure(f"Alle {total} Tracks der Playlist sind fehlgeschlagen.")`
   statt `handle_single_track_success()`.

**WHAT MUST REMAIN UNCHANGED:**
- `enhanced_download_with_retry()`s Rückgabewert-Vertrag (Shape, Feldnamen,
  Retry-/Backoff-Verhalten) — vollständig unangetastet, schützt die 10
  RETRY-COVERAGE-Tests.
- `_process_playlist_download()`s Pro-Track-Isolation und
  `DownloadResult`-Aggregation — unverändert, bereits korrekt (Phase 4, §20
  Non-Finding).
- Die bewusst akzeptierte Partial-Success-Semantik (1/N bis N-1/N zeigt
  weiterhin den Erfolgs-Header mit korrekter Quote) — nicht Teil dieses
  Fixes, kein Finding.
- `build_final_summary_message()`s generelle Formatierungslogik für
  `ok > 0`-Fälle — unverändert.
- `status_callback`-Trennung zwischen Retry-Layer und Telegram-UI (§14) —
  nicht aufgebrochen, Fix bleibt vollständig in `klassen/download_handler.py`.

**WHY this ownership boundary:** `klassen/download_handler.py` ist bereits
die alleinige Autorität für User-Facing-Text (§12) und besitzt bereits den
korrekten Ziel-Mechanismus (`handle_download_failure()`). Der Fix fügt
keine neue Verantwortlichkeit hinzu, sondern schließt zwei Lücken im
bereits vorhandenen Entscheidungsbaum (§8) an exakt den Stellen, an denen
die Entscheidung heute unvollständig ist.

**HOW verification:**
- **Single-Track:** Test mit gemocktem `self.downloader.download_audio`,
  das `{"success": False, "error": "X"}` zurückgibt → assert
  `handle_download_failure` wurde mit `"X"` aufgerufen (bzw. beobachtbar:
  `_send_report_message`/`status_msg.edit_text` erhielt einen Fehlertext,
  nicht Beobachtung des internen Funktionsaufrufs allein — Auftrag §24
  fordert Verhalten, nicht Implementierungsdetails).
- **Playlist 0/N:** Test mit `results[0] = {"type": "playlist", "tracks": [3x success:False], "successful_tracks": 0, "total_tracks": 3}`
  → assert die gesendete Nachricht enthält KEINEN Erfolgs-Header, sondern
  einen Fehlschlags-Text.
- **Partial Success:** bestehender Test
  `test_playlist_type_uses_playlist_header_and_track_counts` (2/3) muss
  unverändert grün bleiben — beweist, dass der Fix diesen Fall nicht
  berührt.
- **Bestehendes Erfolgsverhalten:** vollständige Regressionssuite (1063
  Tests) muss unverändert grün bleiben, insbesondere alle 10
  `test_download_utils_retry.py`-Tests unangetastet.

## 20. Regression Risk

Repo-weit alle Aufrufer/Abhängigkeiten geprüft:

- **`enhanced_download_with_retry()`**: genau 1 produktiver Aufrufer
  (`downloader.py`), 10 Tests — **von diesem Fix nicht berührt** (Option B/C
  ändern nur den Konsumenten in `klassen/download_handler.py`).
- **`download_audio()`**: genau 1 produktiver Aufrufer
  (`handle_youtube_links()`) — Rückgabewert-Shape bleibt identisch, nur
  dessen Auswertung beim Aufrufer wird erweitert.
- **`handle_playlist_success()`**: genau 1 produktiver Aufrufer
  (`handle_youtube_links()`, zusätzlich potenziell für Mehrfach-URL-Batches,
  Zeile 652) — **0 Tests**, daher kein Risiko bestehender Testfälle;
  funktionale Änderung ausschließlich für den neu geprüften `ok==0`-Fall,
  alle anderen Fälle (inkl. Multi-Result-Listen mit `len>1`, die NICHT über
  den `results[0].get("type")=="playlist"`-Zweig laufen) bleiben
  unverändert.
- **`handle_single_track_success()`**: wird für den 0/N-Fall künftig NICHT
  mehr aufgerufen (durch `handle_playlist_success()`s neue Weiche
  abgefangen) — für alle anderen Fälle (Single-Erfolg, Playlist mit
  `ok > 0`) unverändert weiterhin aufgerufen.
- **Kein Caller verlässt sich auf das aktuelle (fehlerhafte) Verhalten** —
  es gibt keinen Test und keine Dokumentation, die das Fehlen der
  Fehlermeldung (Variante A) oder den unconditional-Erfolgs-Header bei 0/N
  (Variante B) als gewünschtes Verhalten festschreibt.

**Kein Caller identifiziert, der bei diesem Fix brechen würde.**

## 21. Explicit Non-Findings

- **`_process_single_download_result()`s Guard-Logik (Punkte A/B/C/F)** ist
  für den `{"success": False}`-Fall **nie erreicht** (wird vorher durch die
  `continue`-Prüfung in Zeile 603-607 herausgefiltert) — verifiziert, keine
  Rolle in diesem Finding.
- **`_process_playlist_download()`s Pro-Track-Fehlerisolation** ist korrekt
  (Phase 4, hier erneut bestätigt) — kein Teil des Root Cause.
- **Retry-Layer manipuliert nie direkt Telegram-UI** — bereits sauber
  getrennt (§14), keine Änderung an dieser Trennung nötig oder empfohlen.
- **Partial-Success-Semantik (1/N bis N-1/N)** ist ein bewusst akzeptiertes,
  bereits getestetes Verhalten — **kein Finding**, nicht Teil des
  empfohlenen Fixes.
- **Fehlerursache geht nicht durch Transformation verloren** — sie liegt
  bis zur letzten Auswertungsstelle unverändert vor (§13); kein neuer
  Datenfluss nötig, nur eine zusätzliche Leseoperation.
- **Kein Vertrags-Redesign nötig** — die verschiedenen Result-Shapes sind
  an ihren Entstehungsorten jeweils sinnvoll (§6/§18-D).

## 22. Verification Plan

Nach Freigabe und Implementierung (nicht Teil dieses Audits):

1. **Erforderliche neue Tests** (Prinzip: Verhalten, nicht
   Implementierungsdetails prüfen):
   - `handle_youtube_links()` bei `download_audio()`-Rückgabe
     `{"success": False, "error": "X"}` → beobachtbares Ergebnis: gesendete/editierte
     Nachricht enthält "X" bzw. den Fehlschlags-Text, nicht den
     Fortschrittsbalken-Endzustand.
   - `handle_playlist_success()`/`handle_single_track_success()` bei
     `successful_tracks=0, total_tracks=N>0` → beobachtbares Ergebnis:
     gesendete Nachricht enthält keinen "erfolgreich"-Header.
   - `handle_playlist_success()`/`handle_single_track_success()` bei
     `successful_tracks=k>0` → beobachtbares Ergebnis: bestehendes
     Erfolgsverhalten unverändert (Regressionsschutz für §10s akzeptierte
     Semantik).
   - `enhanced_download_with_retry()`-Rückgabewert-Kontrakt: bereits
     vollständig abgedeckt (RETRY-COVERAGE) — keine neuen Tests nötig,
     nur Bestätigung, dass diese 10 Tests nach dem Fix weiterhin grün sind.
2. **Volle Regressionssuite** (aktuell 1063 Tests) muss nach Implementierung
   unverändert grün bleiben (0 neue Fehlschläge), plus die oben genannten
   neuen Tests.
3. **Kein neues `BASELINE_v4.md`** vor Abschluss von FIX → REGRESSION →
   VERIFICATION für dieses Finding (und ggf. weitere aus Phase 4).

---

## Nachtrag (2026-08-25): Fix implementiert, verifiziert

Freigabe erteilt, Implementierung exakt nach dem in §19 spezifizierten
minimalen Fix umgesetzt — beide Änderungen ausschließlich in
`klassen/download_handler.py`:

1. **`handle_youtube_links()`**, nach dem bestehenden
   `if not download_result:`-Guard: neue Prüfung
   `if not download_result.get("success"): await self.handle_download_failure(...); return`.
   Platzierung bewusst NACH statt VOR dem bestehenden Leer-Guard (kleine
   Präzisierung gegenüber §19s Wortlaut „unmittelbar nach Zeile 582" —
   `download_result.get(...)` auf einem potenziell `None`-Wert wäre sonst
   selbst abgestürzt; funktional identisches Ergebnis, da der Leer-Guard
   bei jedem produktiven Aufruf ohnehin vor Erreichen des neuen Codes
   greift oder durchläuft).
2. **`handle_playlist_success()`**: `ok`/`total` werden direkt aus der
   `tracks`-Liste berechnet (nicht aus `successful_tracks`/`total_tracks`,
   die im an dieser Stelle vorliegenden Dict nicht existieren — verifiziert
   beim Implementieren: `download_audio()` kopiert diese beiden Felder
   nicht in `final_result`, nur `tracks` selbst überlebt bis hierher).
   Bei `total > 0 and ok == 0` wird `handle_download_failure()` aufgerufen
   statt `handle_single_track_success()`.

**Test:** neue Datei
`tests/test_download_handler_youtube_pipeline_failure_reporting.py` (5
Tests, erste direkte Testabdeckung für `handle_youtube_links()`/
`handle_playlist_success()` überhaupt) — prüft beobachtbares Verhalten
(gesendeter/editierter Telegram-Text), nicht Implementierungsdetails.
Nutzt das etablierte `object.__new__(DownloadHandler)`-Testmuster. Per
`git stash` gegen den Vor-Fix-Stand verifiziert: 3 der 5 Tests schlagen
exakt wie in §5/§9 vorhergesagt fehl (Single-Track-Stille, 0/N-Erfolgs-
Header), die 2 Regressionsschutz-Tests (Partial/Full-Success) sind bereits
am Vor-Fix-Stand grün — bestätigt, dass der Fix ausschließlich die
tatsächlich defekten Pfade ändert.

**Vollregression:** 1068 passed, 0 failed (+5 gegenüber vorherigem Stand,
keine neue Regression — insbesondere alle 10
`test_download_utils_retry.py`-Tests unverändert grün, wie in §20
prognostiziert).

FINDING-4 gilt damit als **FIXED**.
