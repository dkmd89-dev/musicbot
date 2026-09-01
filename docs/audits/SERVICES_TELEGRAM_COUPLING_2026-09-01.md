# Services – Telegram-Kopplung: Audit & minimale Entkopplung

Untersucht die direkte Telegram-Kopplung innerhalb von `services/`
vollständig und entscheidet pro Fundstelle zwischen `KEEP`/`DECOUPLE`/
`DEFER`. Charakterisierung zuerst, Refactor nur wenn eindeutig
gerechtfertigt (Audit-only ist ein gültiges Ergebnis).

## Baseline

| Feld | Wert |
|---|---|
| HEAD (Start) | `7c5bfede4bf72388338829a9cfc73f665793bcb1` (main, nach PR #95) |
| Branch | `audit/services-telegram-coupling` |
| Teststatus (Start) | 1664 passed, 1 skipped, 0 failed |

Bereits getroffene, hier respektierte Vorentscheidungen: die vorherige
Phase (`EnhancedMetadataProcessor.process_single_track()`) gilt als
stabile Baseline und wurde nicht erneut untersucht.

**Wichtiger Befund vorab (Divergenz zur Auftragsbeschreibung):** Der im
Auftrag zitierte P-2-Fund „Telegram coupling in `progress_tracker.py`,
`download_result_reporter.py`, `error_handler.py` part B and
`downloader.py` constructor" stammt nicht aus
`docs/audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md` (dort nicht
enthalten), sondern entspricht inhaltlich einem **veralteten** Fund aus
dem archivierten `docs/archive/MusicBot_SERVICES_Zielarchitektur_Audit.md`
(dort allerdings mit anderen Pfaden: `services/downloader/utils/
progress_tracker.py`, `services/downloader/utils/download_result_reporter.py`,
und primär bezogen auf `spotify_downloader.py`/`cover_processor.py`).
Verifiziert gegen den aktuellen Code:

- `services/error_handler.py` **existiert nicht** — Error-Handling liegt
  bereits korrekt in `handlers/error_handler.py` und
  `handlers/enhanced_error_handler.py`. Kein Fund in `services/`.
- `services/downloader/spotify_downloader.py` **existiert nicht mehr** —
  bewusst entfernt am 2026-08-25 (Commit `9c1af4a`, dokumentierter
  Folgeauftrag „Spotify-Entfernung", siehe
  `docs/archive/arch/MusicBot_ARCH-020_Download_Pipeline_Characterization.md`,
  Abschnitt „Spotify-Entfernung"). Repoweit verifiziert: 0 verbleibende
  Referenzen auf `spotify_downloader`/`SpotifyDownloader`, keine toten
  Imports, keine Spotify-Config-Reste.
- `progress_tracker.py` und `download_result_reporter.py` sind **bereits
  vollständig Telegram-frei** — beide tragen im Code selbst den
  Kommentar „ARCH-007/P-2: services/ hat keine Telegram-Abhängigkeit
  mehr", ein früherer Fix hat die Telegram-Kopplung dort bereits entfernt.

Die einzige tatsächlich noch bestehende, im aktuellen Code verifizierte
Telegram-Kopplung in `services/` war `services/downloader/downloader.py`
(`YoutubeDownloader.__init__`) — siehe Findings.

## Untersuchte Dateien

Repoweiter Grep in `services/` (45 Python-Dateien) nach: `telegram`,
`aiogram`, `Telegram`, `Message`, `Bot`, `CallbackQuery`,
`InlineKeyboard`, `edit_text`, `send_message`, `reply`, `answer`,
`callback`, `chat_id`, `update_id`, `effective_chat`, `effective_user`,
`context.bot`, `status_msg`, `ParseMode` sowie expliziten Imports aus
`telegram`/`aiogram`/`handlers/`. Vertieft gelesen:

- `services/downloader/progress_tracker.py` (146 Zeilen)
- `services/downloader/download_result_reporter.py` (297 Zeilen)
- `services/downloader/downloader.py` (132 Zeilen, vor Fix)
- `services/downloader/download_utils.py` (Referenz für das etablierte
  `chat_id`/`update_id`/`status_callback`-Muster)
- `services/downloader/download/interfaces.py` (`DownloadCoordinator`-
  Protocol, bereits bestehende Abstraktion)
- `services/duplicate/*`, `services/metadata/*`, `services/clients/*`,
  `services/statistik*` — per Grep durchsucht, keine echten Treffer
  (siehe Dependency Map)

## Dependency Map

| Service | direkte Telegram-Abhängigkeit? | konkreter Typ/API | warum (vermeintlich) benötigt? | wer ruft auf? | bestehende Abstraktion vorhanden? | Kandidat? |
|---|---|---|---|---|---|---|
| `progress_tracker.py` | **Nein** (bereits entfernt, ARCH-007/P-2) | — | — | `download_utils.py` (Playlist-Pfad) | n/a — bereits sauber | — |
| `download_result_reporter.py` | **Nein** (bereits entfernt, ARCH-007/P-2) | — | — | `klassen/download_handler.py` | n/a — bereits sauber | — |
| `downloader.py::YoutubeDownloader` | **Ja (vor Fix)** | rohes `telegram.Update`-Objekt (`self.update`, ungetypt aber laufzeit-eindeutig via `.effective_chat.id`/`.update_id`) | nur um 2 einfache Werte (`chat_id`, `update_id`) an `enhanced_download_with_retry()` weiterzureichen | `klassen/download_handler.py:215` (1 Aufrufer) | **Ja** — `enhanced_download_with_retry()` (`download_utils.py`) und das `DownloadCoordinator`-Protocol (`download/interfaces.py`) nehmen `chat_id: Optional[int]`/`update_id: int` bereits als einfache Werte entgegen | **DECOUPLE (umgesetzt)** |
| `error_handler.py` | n/a | — | — | — | — | Datei existiert nicht in `services/` |
| `services/duplicate/*` | Nein | — | — | — | — | bereits im Services-Audit als Telegram-frei bestätigt |
| `services/metadata/*` | Nein | — | — | — | — | bereits im Services-Audit als Telegram-frei bestätigt |
| `services/clients/*` | Nein | — | — | — | — | bereits im Services-Audit als Telegram-frei bestätigt |

**Klassifikation nach Phase-2-Schema:**

- **A. Echter Boundary-Verstoß:** `downloader.py::YoutubeDownloader` (vor
  Fix) — der Service hielt ein Telegram-Objekt, obwohl er nur zwei
  einfache Werte benötigt, die eine Schicht höher bereits verfügbar
  sind.
- **B. Legitimer Callback/Port:** `status_callback: Optional[Callable]`
  in `download_utils.py`/`download/interfaces.py::DownloadCoordinator`
  — bereits vorhanden, bereits generisch (kein Telegram-Typ in der
  Signatur), nicht verändert.
- **C. Historische Kopplung ohne unmittelbaren Nutzen:** keine gefunden.
- **D. Bewusst akzeptable Kopplung:** keine im aktuellen Code gefunden
  (die einzige gefundene Kopplung war Kategorie A, nicht D).

## Call-Site-Analyse

### `YoutubeDownloader` (vor Fix)

- **Konstruktor-Aufrufe:** genau 1, `klassen/download_handler.py:215-219`
  (`YoutubeDownloader(update=update, config=self.config,
  cookie_handler=self.cookie_handler)`), innerhalb von
  `DownloadHandler.__init__(self, update: Update, ...)` — `update` ist
  dort explizit als `telegram.Update` typisiert (`from telegram import
  ..., Update` in `klassen/download_handler.py:39`).
- **Methoden-Aufrufe:** `self.downloader.download_audio(url)` an genau 1
  Stelle (`klassen/download_handler.py:727`); zusätzlich
  `self.downloader.enhanced_download_processor.download_executor` an 1
  Stelle (Zeile 299, unabhängig von `update`/`chat_id`, nicht
  betroffen).
- **`self.update`-Nutzung innerhalb von `downloader.py`:** genau 2
  Lesezugriffe (`self.update.effective_chat.id`,
  `self.update.update_id`), beide ausschließlich in
  `download_audio()`, sonst nirgends in der Klasse verwendet.
- **Bestehender Callback/Protocol:** `enhanced_download_with_retry()`
  (`download_utils.py:353-354`) und `DownloadCoordinator`-Protocol
  (`download/interfaces.py:53-55`) nehmen `chat_id`/`update_id` bereits
  als einfache Parameter entgegen — `YoutubeDownloader` war die einzige
  Ausnahme in dieser Modulfamilie, die stattdessen ein ganzes
  Telegram-Objekt hielt.
- **Tests vor diesem Audit:** **0** — weder `YoutubeDownloader` noch
  `downloader.py` noch `DownloadHandler` (dessen Konstruktor
  `YoutubeDownloader` aufruft) werden in irgendeinem bestehenden Test
  konstruiert (repoweit per Grep verifiziert).

## Responsibility Analysis

`YoutubeDownloader.download_audio()` benötigt `chat_id`/`update_id`
ausschließlich zur Weiterreichung an `enhanced_download_with_retry()`
(dort primär für Logging/Kontext, siehe `download_utils.py:379-380`) —
keine eigene Telegram-Logik (kein Senden, kein Editieren, kein
Callback-Handling). Der Service übernahm damit keine echte
Telegram-Aufgabe, sondern hielt lediglich ein zu großes Objekt für zwei
benötigte Werte — ein reiner Boundary-Formfehler, keine fehlplatzierte
Verantwortlichkeit.

## Risikoanalyse

| Aspekt | Bewertung |
|---|---|
| **Verhalten** | Keine funktionale Änderung — `update.effective_chat.id`/`update.update_id` sind exakt dieselben Werte, die vorher gelesen wurden; sie werden jetzt lediglich vom Aufrufer statt vom Service selbst extrahiert. |
| **API** | `YoutubeDownloader.__init__()`: Parameter `update` → `chat_id: int, update_id: int`. **1** öffentlicher Call-Site betroffen (`klassen/download_handler.py`), angepasst. |
| **Tests** | 0 bestehende Tests betroffen (keine existierten). 9 neue Characterization-/Regressionstests hinzugefügt. |
| **Runtime — Progress Updates** | Unberührt — `progress_tracker.py` bereits vollständig unabhängig von `chat_id`/`update_id`/`update`. |
| **Runtime — Fehleranzeigen** | Unberührt — Fehlerpfad in `download_audio()` nutzt `update` nicht. |
| **Runtime — Download-Abbruch** | Unberührt — keine Cancellation-Logik in `downloader.py`. |
| **Runtime — Message Editing** | Unberührt — `YoutubeDownloader` editiert nie selbst eine Telegram-Nachricht. |
| **Runtime — Telegram Rate Limits** | Unberührt — kein Telegram-Versand in `services/`. |
| **Runtime — Async-Verhalten** | Unberührt — keine `await`-Punkte verändert. |
| **Runtime — Cancellation** | Unberührt. |
| **Migration** | Einstufig möglich — Blast-Radius exakt 1 Datei (Definition) + 1 Datei (Aufrufer), keine schrittweise Migration nötig. |

## Entscheidungstabelle

| Fundstelle | Kopplung | Problem | Bestehende Abstraktion | Änderung nötig? | Risiko |
|---|---|---|---|---|---|
| `services/downloader/progress_tracker.py` | keine (bereits entfernt) | keins | n/a | Nein | n/a |
| `services/downloader/download_result_reporter.py` | keine (bereits entfernt) | keins | n/a | Nein | n/a |
| `services/downloader/downloader.py::YoutubeDownloader.__init__` | rohes `Update`-Objekt gehalten | Boundary-Verstoß (Kategorie A) | Ja — `chat_id`/`update_id`-Muster bereits etabliert in derselben Modulfamilie | **Ja** | niedrig |
| `services/error_handler.py` | — | Datei existiert nicht in `services/` | n/a | Nein | n/a |
| `services/downloader/spotify_downloader.py` | — | Datei existiert nicht mehr (bewusst entfernt, dokumentiert) | n/a | Nein | n/a |

### Kategorisierung

- **DECOUPLE:** `downloader.py::YoutubeDownloader.__init__` — umgesetzt.
- **KEEP:** `status_callback`-Callback-Muster in
  `download_utils.py`/`download/interfaces.py` (bereits Kategorie B,
  generisch, kein Telegram-Typ in der Signatur) — unverändert korrekt.
- **DEFER:** keine — es gab keinen Fund, der zwar problematisch, aber
  (noch) nicht risikoarm entkoppelbar wäre. Die einzige echte Kopplung
  erfüllte alle 5 Entscheidungsregel-Kriterien und wurde direkt
  umgesetzt.

## Characterization Tests

Vor dem Fix existierten **0** Tests für `YoutubeDownloader`/
`downloader.py`. Neue Datei
`tests/test_youtube_downloader_telegram_decoupling.py` (9 Tests):

- Konstruktion mit einfachen `chat_id`/`update_id`-Werten (Kernbeweis
  der Entkopplung, inkl. `assert not hasattr(downloader, "update")`)
- `chat_id`/`update_id` werden unverändert an
  `enhanced_download_with_retry()` weitergereicht
- Erfolgs-Ergebnis-Transformation für Single-Track (inkl.
  `cover_embedded`/`cover_found`-Fallback)
- Erfolgs-Ergebnis-Transformation für Playlist (inkl.
  `playlist_title`-Default)
- Fehlerpfad (`success: False` im Rückgabewert)
- Exception-Pfad (Exception aus `enhanced_download_with_retry()`
  propagiert unverändert)
- Charakterisierung eines dabei entdeckten, **vorbestehenden,
  unabhängigen Bugs** (siehe „Remaining")

**Pre-Fix-Diskriminierung:** alle 9 Tests gegen den ungefixten
Konstruktor ausgeführt — alle schlugen mit `TypeError:
YoutubeDownloader.__init__() got an unexpected keyword argument
'chat_id'` fehl (der geänderte Konstruktor-Vertrag selbst ist der
Beweis; ein `git stash` ist hier nicht zusätzlich aussagekräftiger, da
die Tests bewusst gegen die NEUE Signatur geschrieben sind). Nach dem
Fix: alle 9 grün.

## Findings

| Finding | Klassifikation |
|---|---|
| `YoutubeDownloader.__init__` hielt volles `Update`-Objekt für 2 benötigte Werte | **A — Echter Boundary-Verstoß**, behoben |
| `progress_tracker.py`/`download_result_reporter.py` bereits Telegram-frei | bereits erledigt (ARCH-007/P-2), kein neuer Fund |
| `status_callback`-Callback-Muster | **B — Legitimer Port**, unverändert korrekt |
| `services/error_handler.py` referenziert im Auftrag | existiert nicht — Divergenz zur Auftragsbeschreibung, siehe Baseline-Abschnitt |
| `spotify_downloader.py` referenziert im Auftrag | existiert nicht mehr — bewusst entfernt, dokumentiert, Divergenz zur Auftragsbeschreibung |
| `download_audio()`: `download_result=None` löst `AttributeError` statt sauberem Fehler-Dict aus | **vorbestehender, unabhängiger Bug** — charakterisiert, nicht behoben (außerhalb des Scopes) |

## KEEP / DECOUPLE / DEFER

- **KEEP:** `status_callback`-Muster (`download_utils.py`,
  `download/interfaces.py::DownloadCoordinator`) — bereits die korrekte,
  generische Abstraktion, keine Änderung nötig.
- **DECOUPLE (umgesetzt):** `services/downloader/downloader.py::
  YoutubeDownloader.__init__` — `update` → `chat_id: int, update_id:
  int`.
- **DEFER:** keine.

## Implementierte Änderungen

1. **`services/downloader/downloader.py`**: `YoutubeDownloader.__init__`
   nimmt jetzt `chat_id: int, update_id: int` statt `update` entgegen;
   `download_audio()` liest `self.chat_id`/`self.update_id` statt
   `self.update.effective_chat.id`/`self.update.update_id`. Docstring
   ergänzt, der die bewusste Architekturentscheidung dokumentiert.
2. **`klassen/download_handler.py`**: einziger Konstruktions-Aufruf
   angepasst — `update=update` → `chat_id=update.effective_chat.id,
   update_id=update.update_id`. `DownloadHandler` selbst behält `update:
   Update` (korrekt, `klassen/` liegt oberhalb der `services/`-Schicht).
3. **`tests/test_youtube_downloader_telegram_decoupling.py`** (neu, 9
   Tests).

Keine neue Abstraktionsschicht, kein neues Protocol, kein neuer
Adapter, kein Event-Bus, kein `ServiceContext`/`TelegramManager`/
`NotificationCoordinator` — reine Wiederverwendung des bereits im
Modul etablierten `chat_id`/`update_id`-Musters.

## Tests

### Targeted

```
python3 -m pytest tests/test_youtube_downloader_telegram_decoupling.py -q
9 passed
```

### Thematisch

```
python3 -m pytest tests/ -q -k "download_handler"
30 passed, 1644 deselected

python3 -m pytest tests/ -q -k "download or downloader"
193 passed, 1481 deselected
```

### Full Suite

```
python3 -m pytest tests/ -q
1673 passed, 1 skipped, 0 failed  (Baseline: 1664 passed, 1 skipped → +9 neue Tests)
```

Keine Regression.

## Verbleibende technische Schulden

- `download_audio()`: `download_result=None` → `AttributeError` statt
  sauberem Fehler-Dict (siehe Findings) — kein akutes Risiko, da
  `enhanced_download_with_retry()` laut eigenem Vertrag nie `None`
  zurückgibt (`docs/audits/DL_RETRY_CLASSIFICATION_2026-09-01.md`),
  aber ein latenter Defensive-Code-Bug. Eigene, kleine künftige
  Entscheidung, nicht Teil dieser Phase.
- Keine weiteren offenen Telegram-Kopplungsfunde in `services/`.

## Explizite Out-of-Scope-Punkte

- `services/error_handler.py` — existiert nicht, kein Auftrag ausführbar.
- `spotify_downloader.py` — existiert nicht mehr, kein Auftrag ausführbar.
- `services/duplicate/cache.py` INV-01, `MUSICBRAINZ_RETRIES`,
  Cancellation-Cleanup, allgemeine Async-Architektur, Handler-Layer,
  Clients-Architektur, Dependency-Injection-Architektur,
  Downloader-Retry-Semantik, Metadata-Verhalten — laut Auftrag nicht
  angefasst.
- Der neu gefundene `download_audio(None)`-Bug — dokumentiert, nicht
  gefixt (siehe „Verbleibende technische Schulden").
