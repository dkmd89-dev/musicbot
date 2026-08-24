# ARCH-007 — P-2: Telegram-Entkopplung von `services/` (Design-/Entscheidungsanalyse)

Reine Analyse, keine Codeänderung. Aufbauend auf ARCH-006 (Abschnitt 2:
die zwei einzigen Telegram-Kopplungsstellen in `services/`). Ziel:
`services/` besitzt danach keinerlei Telegram-Abhängigkeit mehr,
`klassen/download_handler.py` übernimmt jeden tatsächlichen Versand.
`api/navidrome_api.py` ist ausdrücklich **nicht** Teil dieser Analyse —
bleibt separate, spätere Entscheidung.

---

## 0. Wichtigster Zusatzbefund

Die beiden betroffenen Module unterscheiden sich fundamental im
tatsächlichen Risiko:

- **`download_result_reporter.py`**: der Telegram-Versand-Pfad ist **aktiv
  genutzt** — `klassen/download_handler.py` ruft `send_final_summary()`
  und `send_playlist_direct_summary()` nachweislich bei jedem
  erfolgreichen Download/jeder erfolgreichen Playlist auf.
- **`progress_tracker.py`**: der Telegram-Versand-Pfad ist im
  Produktionscode bereits **funktional tot**. `update_progress()` — die
  einzige Methode, die `update.message.reply_text(...)` aufruft — hat
  **0 Aufrufer** im gesamten Repo außerhalb von Tests (verifiziert per
  Grep; das ist bereits im Docstring von `tests/test_progress_tracker.py`
  dokumentiert). `klassen/download_handler.py` konstruiert
  `ProgressTracker` zwar und synchronisiert dessen `status_message`-
  Attribut an drei Stellen (Zeilen 317/674/806), ruft aber nie
  `update_progress()` oder `set_current_item()` auf — die tatsächliche
  Fortschrittskommunikation läuft stattdessen komplett über die
  eigenständige `DownloadHandler._update_status()`-Methode, die bereits
  jetzt in `klassen/` liegt und selbst sendet. `set_current_item()`,
  `progress_hook()`, `track_performance()` (Modulfunktionen) haben
  ebenfalls 0 Aufrufer.

**Konsequenz für die Risikobewertung:** eine Entkopplung von
`progress_tracker.py` kann das laufende Verhalten des Bots nicht
verändern — der einzige sendende Code-Pfad wird ohnehin nie erreicht.
Bei `download_result_reporter.py` ist echte Sorgfalt nötig
(Verhaltensgleichheit des tatsächlich gesendeten Texts).

---

## 1. `download_result_reporter.py`

### 1.1 Aktuelle Verantwortlichkeiten

1. Genre-/Stats-Aufbereitung aus Download-Ergebnis-Dicts (`extract_genres_from_data`,
   `collect_playlist_genres`, `extract_stats_from_result`) — reine
   Datentransformation, **keine** Telegram-Berührung, bleibt in allen
   Varianten unverändert.
2. Nachrichtentext-Formatierung: `build_duplicate_message()` (**bereits
   eine reine Funktion** — nimmt `DuplicateEntry` + `dup_type`, gibt
   `str` zurück, kein Telegram-Import nötig außer der Typannotation),
   sowie die Text-Bausteine innerhalb von `send_playlist_direct_summary()`
   und `send_final_summary()`.
3. Telegram-Versand: `send_playlist_direct_summary()` und
   `send_final_summary()` senden den gebauten Text selbst
   (`status_msg.edit_text(...)` mit Fallback `update.message.reply_text(...)`),
   fangen `TelegramError`.

### 1.2 Zu entfernende Telegram-Abhängigkeiten

- `from telegram.error import TelegramError`
- Die Parameter `update`, `status_msg` aus `send_playlist_direct_summary()`
  und `send_final_summary()`
- Der `try/except TelegramError`-Block innerhalb dieser beiden Methoden

### 1.3 Rückgabewerte statt Versand

`send_playlist_direct_summary()` → `build_playlist_summary_message()`,
`send_final_summary()` → `build_final_summary_message()`. Beide geben
`str` zurück statt zu senden. Da keine Telegram-API mehr aufgerufen wird,
können beide **synchron** werden (kein `await` mehr nötig) — siehe
Abschnitt 1.6 für die Konsequenz dieser Signaturänderung.

### 1.4 Neue Schnittstelle

```python
class DownloadResultReporter:
    def __init__(self, logger=None): ...

    # unveraendert
    def extract_genres_from_data(self, genres_data) -> List[str]: ...
    def collect_playlist_genres(self, tracks) -> List[str]: ...
    def extract_stats_from_result(self, result, tracks) -> dict: ...
    def build_duplicate_message(self, entry, dup_type) -> str: ...

    # umbenannt, synchron, kein update/status_msg-Parameter mehr
    def build_playlist_summary_message(self, results, successful) -> str: ...
    def build_final_summary_message(self, result, processing_stats, duplicate_stats) -> str: ...
```

### 1.5 Auswirkungen auf Consumer

Einziger Consumer: `klassen/download_handler.py`.

- `_handle_duplicate_found()` (Zeile 351-361): **unverändert** — ruft
  bereits `build_duplicate_message()` auf und sendet selbst. Dient als
  lebendes Vorbild für die Zielform der anderen beiden Aufrufstellen.
- `handle_single_track_success()` (Zeile 587-591):
  ```python
  # vorher
  await self.result_reporter.send_final_summary(self.update, self.status_msg, result, stats, dup_stats)
  # nachher
  msg = self.result_reporter.build_final_summary_message(result, stats, dup_stats)
  try:
      if self.status_msg:
          await self.status_msg.edit_text(msg)
      else:
          await self.update.message.reply_text(msg)
  except TelegramError as e:
      self.logger.error(f"❌ [SUMMARY] Fehler beim Senden: {e}")
  ```
- `handle_playlist_success()` (Zeile 609-611): analoge Umstellung für
  `build_playlist_summary_message()`.

### 1.6 Auswirkungen auf Tests/Mocks

- `tests/test_download_result_reporter.py`, Klassen
  `TestSendPlaylistDirectSummary`/`TestSendFinalSummary`: Tests werden
  **einfacher** — kein `Mock()`-`update`/`status_msg`-Objekt mehr nötig,
  stattdessen direkte String-Assertions auf den Rückgabewert. Kein
  `asyncio.run(...)` mehr nötig (synchrone Methoden).
- Die beiden `TelegramError`-Fallback-Tests (Senden schlägt fehl, wird
  geloggt) wandern als neue Tests zur `download_handler`-Testsuite —
  dort ist jetzt der Versand-Code.
- `tests/test_download_handler_process_single_download_result.py` (bzw.
  eine neue/erweiterte Testdatei für `handle_single_track_success`/
  `handle_playlist_success`) bekommt entsprechend neue Fälle.

### 1.7 Mögliche Verhaltensänderungen

- **Gesendeter Text:** keine Änderung — identischer Text, identischer
  `status_msg`/`update`-Fallback-Mechanismus, identischer
  `TelegramError`-Fang (nur an anderer Stelle im Code).
- **API-Form:** `build_*`-Methoden werden synchron statt `async` — reine
  Signaturänderung, kein Verhaltensrisiko, aber alle Aufrufer (aktuell:
  nur die zwei genannten Stellen) müssen angepasst werden.

### 1.8 Risiko und Migrationsschritte

**Risiko: niedrig.** Ein Consument, klarer Datenfluss (Ergebnis-Dict →
Text), keine Business-Logic-Änderung, nur Verantwortungsverschiebung.

1. `build_playlist_summary_message()`/`build_final_summary_message()` in
   `download_result_reporter.py` einführen — Kern-Logik identisch zu
   `send_*`, aber ohne Versand/Telegram-Import.
2. Bestehende Regressionstests (`tests/test_download_result_reporter.py`)
   gegen die neuen `build_*`-Methoden umschreiben — Text-Assertions
   bleiben inhaltlich identisch, nur ohne Mock-Update-Objekt.
3. `klassen/download_handler.py`: `handle_single_track_success()`/
   `handle_playlist_success()` auf `build_*` + eigenen Versand
   umstellen (Muster von `_handle_duplicate_found()` übernehmen).
4. Alte `send_*`-Methoden entfernen, `telegram.error.TelegramError`-Import
   aus `download_result_reporter.py` entfernen.
5. Neue Tests für den jetzt in `download_handler.py` liegenden
   Versand-Code (inkl. `TelegramError`-Fallback).
6. Voller Regressionslauf.

---

## 2. `progress_tracker.py`

### 2.1 Aktuelle Verantwortlichkeiten

1. Fortschritts-Zählung (`processed_items`/`total_items`), Zeitstempel,
   Drossel-Logik (sendet höchstens alle 5s, immer beim letzten Item).
2. ETA-Berechnung + Nachrichtentext-Format.
3. Telegram-Versand (`update.message.reply_text`) in `update_progress()`
   — **0 Aufrufer im Produktionscode** (siehe Abschnitt 0).
4. `set_current_item()` — 0 Aufrufer.
5. Modulfunktionen `progress_hook()`/`track_performance()` — 0 Aufrufer.

### 2.2 Zu entfernende Telegram-Abhängigkeiten

- `from telegram import Update` (Typannotation des `update`-Konstruktor-
  Parameters)
- Das `self.update`-Attribut und der `await self.update.message.reply_text(message)`-
  Aufruf in `update_progress()`

### 2.3 Rückgabewerte statt Versand

`update_progress()` → `compute_progress_message()`: berechnet weiterhin
Zähler/ETA/Drossel-Logik, gibt den Nachrichtentext zurück (`Optional[str]`
— `None`, wenn das Drossel-Intervall noch nicht erreicht ist, entspricht
dem bisherigen "schweigt einfach"-Verhalten).

### 2.4 Neue Schnittstelle

```python
class ProgressTracker:
    def __init__(self, total_items: int = 1, logger_factory=None):
        # KEIN update-, KEIN status_message-Parameter mehr
        ...

    def compute_progress_message(self, message: str = None) -> Optional[str]:
        """Wie bisher update_progress(), gibt den Text zurueck statt zu
        senden. None, wenn das Drossel-Intervall (5s) noch nicht erreicht
        ist - Aufrufer sendet nur, wenn nicht None."""
        ...

    def set_current_item(self, item_name: str) -> None: ...  # unveraendert
    def cleanup(self) -> None: ...  # unveraendert (bereits No-Op)
```

`progress_hook()`/`track_performance()` (Modulfunktionen) sind bereits
frei von Telegram-Bezug — unverändert.

### 2.5 Auswirkungen auf Consumer

- `klassen/download_handler.py`: Konstruktor-Aufruf
  `ProgressTracker(update, status_message=self.status_msg, logger_factory=...)`
  → `ProgressTracker(total_items=..., logger_factory=...)`. Die drei
  `self.progress_tracker.status_message = self.status_msg`-Zuweisungen
  (Zeilen 317/674/806) entfallen ersatzlos — es gibt kein
  `status_message`-Attribut mehr, das synchronisiert werden müsste.
  Da `update_progress()`/`compute_progress_message()` ohnehin nie
  aufgerufen wird, gibt es **keine weitere Anpassung** an einer echten
  Aufrufstelle nötig.
- `services/downloader/utils/download_utils.py::EnhancedDownloadProcessor.init_tracker()`
  (Zeile 175): Signatur `init_tracker(self, update_object, total_items)`
  müsste ebenfalls den `update_object`-Parameter verlieren, um konsistent
  zu bleiben. Hat laut BUG-009 (ENGINEERING_BASELINE) 0 Aufrufer — kann im
  selben Zug bereinigt oder als eigener, risikofreier Trivial-Schritt
  behandelt werden.

### 2.6 Auswirkungen auf Tests/Mocks

- `tests/test_progress_tracker.py`: alle Tests, die ein `update`-Mock
  konstruieren und `update.message.reply_text.assert_called_once()`
  prüfen, werden auf Rückgabewert-Assertions umgestellt
  (`assert tracker.compute_progress_message() == "..."` bzw. `is None`
  bei gedrosseltem Intervall). Deutlich einfacher — kein Telegram-Mock
  mehr nötig.
- `tests/test_download_handler_process_single_download_result.py` /
  `test_playlist_processor.py`: prüfen, ob dort `ProgressTracker`-
  Konstruktion mit `update`-Argument vorkommt (aktuell nur indirekt über
  `object.__new__(DownloadHandler)`-Fixtures, die `progress_tracker`
  gar nicht setzen — voraussichtlich unbetroffen, wird in der
  Umsetzungsphase verifiziert).

### 2.7 Mögliche Verhaltensänderungen

**Keine für den laufenden Bot** — der sendende Pfad wird aktuell nie
erreicht, jede Änderung daran ist für die Produktion unsichtbar. Einzige
relevante Konsequenz: sollte `init_tracker()`/`update_progress()` künftig
doch verdrahtet werden (der ursprüngliche BUG-009-Kontext), sendet der
Aufrufer dann selbst statt automatisch durch die Klasse — das ist im
Sinne der Entkopplung explizit gewollt.

### 2.8 Risiko und Migrationsschritte

**Risiko: sehr niedrig** (niedriger als bei `download_result_reporter.py`)
— der sendende Pfad ist bereits tot, keine Produktionsauswirkung möglich.

1. `compute_progress_message()` statt `update_progress()` einführen,
   `update`-Parameter aus Konstruktor entfernen.
2. `klassen/download_handler.py`: Konstruktor-Aufruf anpassen, die drei
   `status_message`-Zuweisungen entfernen.
3. `download_utils.py::init_tracker()` analog anpassen (oder separat
   zurückstellen — kein Risiko in beiden Fällen).
4. Tests umschreiben.
5. Voller Regressionslauf.

---

## 3. Alternative Variante: Callback-Injektion statt Rückgabewert

Statt Text zurückzugeben und den Versand komplett nach `klassen/` zu
verschieben, könnte `klassen/download_handler.py` beim Konstruieren einen
Callback injizieren:

```python
class DownloadResultReporter:
    def __init__(self, send_callback: Callable[[str], Awaitable[None]], logger=None):
        self._send = send_callback

    async def send_final_summary(self, result, processing_stats, duplicate_stats) -> None:
        msg = self._build_final_summary_message(result, processing_stats, duplicate_stats)
        await self._send(msg)
```

```python
# klassen/download_handler.py
async def _send(msg: str) -> None:
    try:
        if self.status_msg:
            await self.status_msg.edit_text(msg)
        else:
            await self.update.message.reply_text(msg)
    except TelegramError as e:
        self.logger.error(f"...: {e}")

self.result_reporter = DownloadResultReporter(send_callback=_send, logger=...)
```

Analog für `ProgressTracker`: ein `send_callback` würde bei jedem
(theoretischen) `update_progress()`-Aufruf durchgereicht.

**Vorteile:** API-Form bleibt näher am Original (`send_*`-Methoden bleiben
`async`, Call-Sites in `handle_single_track_success`/
`handle_playlist_success` ändern sich kaum — nur die Konstruktion).

**Nachteile:**
- `services/` bekommt weiterhin eine send-artige Verantwortlichkeit, nur
  über eine Indirektion (Dependency Inversion statt vollständiger
  Entkopplung) — entspricht dem Ziel "keinerlei Telegram-Abhängigkeit"
  nur in der Form (kein `telegram`-Import mehr im Modul selbst), nicht im
  Geist (die Klasse "weiß" konzeptionell weiterhin, dass sie sendet).
- Schwerer zu testen als reine Funktionen — ein Callback-Mock ist nötig,
  ähnlich aufwendig wie die bisherigen `update`/`status_msg`-Mocks.
- Bei `ProgressTracker` unnötige Komplexität für einen aktuell toten Pfad.

**Empfehlung: Hauptvariante (Abschnitt 1+2, reine Rückgabewerte).**
Begründung:
- Entspricht dem Prinzip expliziter Datenflüsse ohne versteckte
  Seiteneffekte in `services/`.
- Einfacher zu testen (reine Funktionen statt Callback-Mocks).
- `build_duplicate_message()` ist bereits so gebaut und funktioniert
  nachweislich gut — dient als Vorbild statt Neuerfindung.
- Konsistent mit dem bereits etablierten Muster dieser Session (z. B.
  `metadata_result_translator.py` — reine Übersetzungsfunktionen ohne
  Seiteneffekte, ARCH-004).

---

## 4. Offener Detailpunkt: `handlers.duplicate_handler.DuplicateEntry`

`build_duplicate_message()` importiert `DuplicateEntry` aus `handlers/`
— das ist **keine Telegram-Abhängigkeit**, sondern eine Abhängigkeit zu
einer anderen höheren Schicht (`handlers/`), separat vom expliziten
P-2-Auftrag ("Telegram-Abhängigkeit"). Bleibt in beiden Varianten oben
unverändert bestehen, sofern nicht ausdrücklich eine weitergehende
Entscheidung getroffen wird (z. B. eigenes DTO in `services/` statt des
`handlers`-Typs). Wird hier nur benannt, nicht bewertet — eigener,
möglicher Folgepunkt, kein Teil dieser P-2-Entscheidung.

---

## 5. Zusammenfassung für die Entscheidung

| Modul | Empfohlene Variante | Risiko | Verhaltensänderung |
|---|---|---|---|
| `download_result_reporter.py` | Rückgabewerte (Abschnitt 1) | niedrig | keine (Text/Fallback/Fehlerbehandlung identisch, nur verschoben) |
| `progress_tracker.py` | Rückgabewerte (Abschnitt 2) | sehr niedrig | keine (sendender Pfad bereits tot) |

Alternative (Callback-Injektion, Abschnitt 3) für beide Module verfügbar,
aber nicht empfohlen.

Keine Implementierung in diesem Schritt. Entscheidung nötig: Hauptvariante
bestätigen, Alternative wählen, oder nur eines der beiden Module zuerst
umsetzen.

---

## 6. Umsetzung (2026-08-24, Branch `arch/p2-telegram-decoupling`)

Nutzer-Entscheidung: Hauptvariante (Rückgabewerte), beide Module in einem
Schritt.

- `download_result_reporter.py`: `send_playlist_direct_summary()` →
  `build_playlist_summary_message()`, `send_final_summary()` →
  `build_final_summary_message()` — beide synchron, geben nur noch Text
  zurück, `telegram.error.TelegramError`-Import entfernt.
- `progress_tracker.py`: `update_progress()` → `compute_progress_message()`
  (`Optional[str]`, `None` wenn Drossel-Intervall nicht erreicht),
  `update`-/`status_message`-Parameter aus Konstruktor entfernt,
  `from telegram import Update`-Import entfernt.
- `klassen/download_handler.py`: neue private Hilfsmethode
  `_send_report_message(msg, error_log_msg, success_log_msg=None)` bündelt
  das gemeinsame Send-Muster (status_msg-Fallback auf update.message,
  TelegramError-Fang, optionales Erfolgs-Log) — vorher 3× dupliziert
  (`_handle_duplicate_found` bereits vorhanden, `handle_single_track_success`/
  `handle_playlist_success` neu darauf umgestellt), jetzt an einer Stelle.
  Alle drei ursprünglichen Log-Texte (inkl. der leicht unterschiedlichen
  Fehler-/Erfolgsmeldungen je Aufrufstelle) 1:1 erhalten. Die drei
  `progress_tracker.status_message = ...`-Zuweisungen entfielen ersatzlos
  (kein Attribut mehr, ohnehin nie gelesen — siehe Abschnitt 0).
- `download_utils.py::EnhancedDownloadProcessor.init_tracker()`:
  `update_object`-Parameter entfernt (0 Aufrufer, siehe BUG-009).

**Tests:** `tests/test_download_result_reporter.py` — Versand-/Fallback-/
`TelegramError`-Tests entfernt (nicht mehr zutreffend, kein Versand mehr
im Modul), reine Text-Assertions auf die `build_*`-Rückgabewerte
umgestellt. `tests/test_progress_tracker.py` — auf
`compute_progress_message()`-Rückgabewert-Assertions umgestellt, ein
Test entfernt (`test_exception_during_send_is_caught_not_raised`, nicht
mehr zutreffend). Neue Datei `tests/test_download_handler_send_report_message.py`
(6 Tests) für `_send_report_message()` — deckt status_msg/Fallback,
`TelegramError`-Fang mit korrektem Log-Prefix, optionales Erfolgs-Log ab.

**Regressionslauf:** 1007 bestanden (vorher 1005 — Netto +2, exakt
nachvollziehbar: −3 Tests in `test_download_result_reporter.py`, −1 Test
in `test_progress_tracker.py`, +6 neue Tests), unverändert 15
Vorbestand-Fehler.

**Ergebnis:** `services/` besitzt keine Telegram-Abhängigkeit mehr (kein
`telegram`-Import, kein `handlers`-Import außer weiterhin
`DuplicateEntry` in `download_result_reporter.py`, siehe Abschnitt 4 —
bewusst nicht Teil dieser Entscheidung). `api/navidrome_api.py` nicht
angefasst.

**P-2 damit abgeschlossen.**
