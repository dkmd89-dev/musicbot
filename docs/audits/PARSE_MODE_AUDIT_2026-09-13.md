# Parse-Mode-Audit — MusicBot

**Datum:** 2026-09-13
**Scope:** `handlers/`, `services/` (nur nachrichtenbauende Stellen), `helfer/`, `utils/`
**Methode:** Statische Analyse (grep/Codelesen) auf dem geklonten Repo
(`dkmd89-dev/musicbot`, `main`, Commit `60229de`). Keine Code-Änderung,
kein Branch, keine Ausführung der Testsuite.
**Anlass:** NAV-F13 (`(` in Genre-Detail), NAV-F14 (`+` in
Playlist-Overflow) — wiederkehrende `Can't parse entities`-Fehlerklasse.

> **Update (2026-09-14) — Live-Verifikation + Hotfixes umgesetzt.**
>
> 1. **Top-Risiko 3 (`**Bold**` in MarkdownV2, Abschnitt 4) — entkräftet.**
>    Gegen `logs/bot.log` geprüft: `navidrome_renderer.render_album_detail()`
>    sendet das beanstandete `**Album: ...**`-Muster über
>    `navidrome_menu_handler.py` mehrfach erfolgreich (kein einziger
>    zugehöriger `❌ Fehler beim Laden der Album-Details`-Log-Eintrag).
>    Telegram akzeptiert Doppel-Sternchen unter MarkdownV2 in der
>    Praxis. Kein Fix nötig, Empfehlung 3 geschlossen.
> 2. **Gegenprobe `enhanced_status_handler.py`** (im Audit als „sauberste
>    Legacy-Markdown-Implementierung" eingestuft): die im Log gefundenen
>    `byte offset 108/67`-Fehler datieren nachweislich VOR den bereits
>    vorhandenen Fix-Commits `01d923b`/`599abea`
>    (`docs/MusicBot_STATUS_MENU_CLOSURE.md`) — nach deren Deploy trat
>    der Fehler im verbleibenden Log nicht mehr auf. Audit-Einschätzung
>    bestätigt, kein neuer Bug.
> 3. **Hotfix 1 + 2 umgesetzt** (Details: `docs/FINDINGS_INDEX.md`,
>    Einträge `PMA-F1`/`PMA-F2`). Dabei zwei Korrekturen gegenüber
>    Abschnitt 5/7 dieses Dokuments:
>    - `process_new_navidrome_user()`/`process_edit_navidrome_user()`
>      waren entgegen der ursprünglichen Einschätzung NICHT tatsächlich
>      gefährdet — beide senden über `update.message.reply_text(...)`
>      **ohne** `parse_mode`-Argument (kein `Defaults(parse_mode=...)`
>      auf der `Application` konfiguriert), laufen also bereits als
>      Plain-Text. Real betroffen war stattdessen zusätzlich
>      `show_user_management_menu()` (Listenansicht, `parse_mode="Markdown"`
>      + unescaptes `nav_user`) — im Audit nicht benannt, beim
>      Implementieren gefunden.
>    - Zusatzfund in `enhanced_error_handler.py::handle_recent_errors_command()`:
>      `message_preview` (echter Exception-Text) wurde trotz explizitem
>      `parse_mode="Markdown"` unescaped eingebettet — dieselbe
>      Fehlerklasse wie der im Audit benannte `error_msg`-Fallback, hier
>      aber im Erfolgspfad. Mitgefixt.

---

## 1. Executive Summary

- **3 aktive Parse-Modi** im Projekt, nicht nur die im Auftrag genannten
  zwei: **MarkdownV2** (17 Sende-Stellen, überwiegend
  `navidrome_menu_handler.py`), **Legacy-`Markdown` (v1)** (57
  Sende-Stellen, breit verteilt über 10 Dateien), **HTML** (45
  Sende-Stellen, konzentriert in 6 neueren Handlern). Legacy-Markdown
  ist damit der **meistgenutzte** Modus im Projekt — im Auftrag nicht
  erwähnt, aber sicherheitsrelevant, da er eine eigene,
  undokumentierte Eskalationsklasse mit MarkdownV2 teilt (`Can't parse
  entities`), aber eine andere Escape-Regel hat (nur `_ * \` [`).
- **11 Escape-/Format-Helper** identifiziert, davon **4 aktiv genutzte
  Escape-Funktionen** (`escape_md_v2` + 2 Legacy-Aliase davon,
  `_escape_markdown` ×2 [Legacy v1], `_escape_text` [No-Op],
  `_md_escape`/`_md_code` [GFM, nicht Telegram]) und **8 nie extern
  aufgerufene Formatierungs-Helfer** (`md_bold`, `md_code`,
  `md_italic`, `md_underline`, `md_strikethrough`, `md_spoiler`,
  `md_code_block`, `md_link` — toter Code).
- **0 bestätigte Kreuzverwendungen** (kein MarkdownV2-Helper in
  HTML-Nachricht oder umgekehrt gefunden) — das Projekt trennt die
  Escape-Verantwortung sauber pro Modul. Aber: **2 real ungesicherte
  dynamische Werte** identifiziert, die zur selben Fehlerklasse wie
  NAV-F13/F14 führen können (siehe unten), plus **1 unverifizierter,
  potenziell projektweiter struktureller Verdachtsfund** (`**Bold**`
  statt `*Bold*`).
- **Ungesicherte dynamische Werte:** mindestens 2 konkrete Fundorte
  (Navidrome-Benutzername, Exception-Text) über insgesamt 6+
  Code-Stellen in 4 Dateien — alle im **Legacy-Markdown-Modus**, nicht
  im MarkdownV2-Bereich (der ist nach NAV-F13/F14 vorbildlich mit
  `escape_md_v2()` abgesichert).
- **Top-3-Risikostellen:**
  1. **`handlers/admin/user_management_handler.py`** — Navidrome-Username
     (freier Text, admin-eingegeben) unescaped in `parse_mode="Markdown"`
     eingebettet (`show_user_detail`, `process_new_navidrome_user`,
     `process_edit_navidrome_user`). Ein Unterstrich im Usernamen
     (z. B. „john_doe", sehr plausibel) crasht die Ansicht.
  2. **`handlers/enhanced_error_handler.py`** — rohe Exception-Texte
     (`f"...: {e}"`) in `parse_mode="Markdown"`-Nachrichten (Default der
     `_reply_or_edit()`-Helper-Methode). Jede Exception mit `_`, `` ` ``
     oder `[` im Text (z. B. Dateipfade) crasht die Fehleranzeige selbst.
  3. **`handlers/navidrome_renderer.py`** — durchgängig `**Bold**`
     (Doppel-Sternchen, CommonMark-Stil) in MarkdownV2-Kontext statt
     Telegrams Einzel-Sternchen-Syntax `*Bold*`. Unklar, ob Telegram das
     als leere, valide oder fehlerhafte Bold-Entity interpretiert —
     **nicht live verifiziert** (siehe Abschnitt 4). Falls fehlerhaft:
     betrifft *jede* Album-/Song-/Playlist-/Genre-/Artist-Detailansicht.

---

## 2. Übersichtstabelle `parse_mode`

Aggregiert (Einzelzeilen bei Bedarf im Repo unter den genannten
Dateien/Zeilenbereichen; aus Platzgründen hier pro Datei
zusammengefasst statt einer 130-Zeilen-Tabelle):

| Datei | Anzahl Stellen | Modus | Kommentar |
|---|---|---|---|
| `handlers/navidrome_menu_handler.py` | 15 | MarkdownV2 | Sendet Text aus `navidrome_renderer.py`; alle dynamischen Werte laufen dort durch `escape_md_v2()`. |
| `handlers/menu/actions/admin_operations.py` | 2 | MarkdownV2 | Navidrome-Scan-Ergebnis (`escape_md_v2()` korrekt genutzt); **dieselbe Datei nutzt zusätzlich HTML** (1×, Wartungsmodus) — Mixed-Mode-Datei, aber getrennte Funktionen, kein Konflikt gefunden. |
| `handlers/admin/backup_handler.py` | 14 | Legacy `Markdown` | Kein Escape-Helper importiert/definiert. Enthält primär statische Texte + Zahlen/Zeitstempel; keine erkennbaren Freitext-Injektionen gefunden (aber nicht abschließend Zeile für Zeile geprüft, siehe Empfehlung). |
| `handlers/admin/user_management_handler.py` | 9 | Legacy `Markdown` | **Kein Escape-Helper.** Navidrome-Username (Freitext) unescaped eingebettet — siehe Top-Risiko 1. |
| `handlers/duplicate_handler.py` | 4 | Legacy `Markdown` | Kein Escape-Helper; Inhalte überwiegend numerische Statistiken (Duplikat-Rate, Cache-Größen) — geringes Risiko. |
| `handlers/enhanced_status_handler.py` | 17 | Legacy `Markdown` | Eigener Helper `_escape_markdown()` (Legacy-v1-Zeichensatz `_ * \` [`), bewusst **nicht** `escape_md_v2()` (dokumentiert, korrekt begründet). Sauberste Legacy-Markdown-Implementierung im Projekt. |
| `handlers/enhanced_error_handler.py` | 4 (+ Default-Parameter) | Legacy `Markdown` | **Kein Escape-Helper.** Rohe Exception-Texte eingebettet — siehe Top-Risiko 2. `_reply_or_edit()` hat `parse_mode: str = "Markdown"` als Default, d. h. auch Aufrufer ohne explizites `parse_mode` landen hier. |
| `handlers/menu/rendering.py` | 2 | Legacy `Markdown` | Zentraler Menü-Renderer; `header_text` kommt teils aus `greeting.py` (dort bereits mit passendem `_escape_markdown()` vorbehandelt) — funktionierende, aber unsichtbare Kopplung zwischen zwei Dateien (siehe Abschnitt 7, mittelfristig). |
| `handlers/menu/actions/admin_diagnostics.py` | 1 | Legacy `Markdown` | Nicht im Detail geprüft (außerhalb Kernrisiko-Fokus). |
| `handlers/menu/actions/usermgmt.py` | 2 | Legacy `Markdown` | Nicht im Detail geprüft. |
| `handlers/menu/content/help.py` | 3 | Legacy `Markdown` | Überwiegend statische Hilfetexte — geringes Risiko. |
| `handlers/menu/content/greeting.py` | 0 direkt / 1 indirekt via `rendering.py` | Legacy `Markdown` | Eigener `_escape_markdown()` (Legacy-v1), korrekt auf den tatsächlich verwendeten Modus abgestimmt. |
| `handlers/admin/bot_restart_handler.py` | 3 | HTML | Kein `html.escape()` importiert — aber alle dynamischen Stellen sind ein statischer Service-Name (`_SERVICE_NAME = "bot"`), kein Nutzer-/API-Text. Geringes Risiko, aber fragil bei künftigen Änderungen. |
| `handlers/library_doctor_handler.py` | 3 | HTML | Konsequent `html.escape()` auf allen dynamischen Werten — **positives Referenzbeispiel**. |
| `handlers/menu/reprocessing_menu_handler.py` | 4 | HTML | `html.escape()` importiert und mehrfach genutzt (8×) — konsistent. |
| `handlers/repair_musicbot_handler.py` | 9 | HTML | `html.escape()` konsistent genutzt (16×). |
| `handlers/library_health_review_handler.py` | 24 | HTML | `html.escape()` konsistent genutzt (20×) — größte HTML-Oberfläche im Projekt, sauber. |
| `handlers/mugge_statistik_handler.py` | 1 (`ParseMode.HTML`-Enum) | HTML | Einzige Stelle mit `from telegram.constants import ParseMode`; `html.escape()` (aliasiert als `html_escape`) korrekt genutzt; explizit dokumentiert, warum `_escape_text()` (No-Op) hier *nicht* ausreicht. Restliche Klasse arbeitet bewusst Plain-Text. |
| `handlers/navidrome_renderer.py` | 0 (baut nur Text, sendet nicht selbst) | — | Reiner Text-/Keyboard-Builder für MarkdownV2 (siehe Moduldocstring); tatsächlicher Versand erfolgt in `navidrome_menu_handler.py`. |
| `handlers/menu/actions/download.py` | 0 (bewusst) | Plain-Text | **Explizit dokumentiert**: dynamische YouTube-Titel/Artist-/Albumnamen können `_`/`*` enthalten → bewusst kein `parse_mode` in der gesamten `dl:`-Sektion statt selektivem Escapen. Vorbildliche Risikoentscheidung. |
| `handlers/family_stats_handler.py`, `family_chat_handler.py`, `family_challenge_handler.py`, `test_menu_handler.py`, `enhanced_logger_menu_handler.py`, `menu/actions/{stats,family,navidrome,_common}.py`, `menu/text_workflow_dispatcher.py`, `menu/rich_menu_handler.py`, `menu/maintenance_gate.py` | 0 | Plain-Text (vermutlich) | Keine `parse_mode`-Vorkommen im Grep gefunden. `family_stats_handler.py` dokumentiert dies explizit im Kopfkommentar ("Plain-Text-Antworten ohne parse_mode"). Für die übrigen Dateien nicht einzeln zeilenweise verifiziert, ob es sich um bewusste Entscheidung oder Lücke handelt (siehe Empfehlung Abschnitt 7). |
| `services/**` | 0 | — | Bestätigt: keine `parse_mode`-Verwendung in `services/` — konsistent mit der dokumentierten "Telegram-frei"-Architektur. |

**Explizit nicht gefunden:** `ParseMode`-Enum-Import (`from
telegram.constants import ParseMode`) außer in genau einer Datei
(`mugge_statistik_handler.py`) — der Rest des Projekts verwendet
durchgängig String-Literale (`"MarkdownV2"`, `"Markdown"`, `"HTML"`)
statt des Enums.

---

## 3. Übersichtstabelle Escape-Helper

| Helper | Datei | Zeile | Ziel-Modus | Aufrufer (extern) |
|---|---|---|---|---|
| `escape_md_v2` | `helfer/markdown_helfer.py` | 11 | MarkdownV2 (volles 18-Zeichen-Set + zusätzlich `, : ;`) | `navidrome_renderer.py` (20×), `navidrome_menu_handler.py` (6×), `menu/actions/admin_operations.py` (3×), intern in `helfer/markdown_helfer.py` selbst (`md_link`, `create_progress_bar`, `format_file_size`, `format_duration`, `format_as_markdown_v2`) |
| `safe_escape_for_telegram` | `helfer/markdown_helfer.py` | 58 | MarkdownV2 (Alias von `escape_md_v2`) | Keine externen Aufrufer gefunden — nur „für Kompatibilität" vorgehalten. |
| `escape_markdown_v2` | `helfer/markdown_helfer.py` | 323 | MarkdownV2 (Legacy-Alias von `escape_md_v2`) | Keine externen Aufrufer gefunden. |
| `markdown_escape` | `helfer/markdown_helfer.py` | 328 | MarkdownV2 (Legacy-Alias von `escape_md_v2`) | Keine externen Aufrufer gefunden. |
| `remove_unwanted_backslashes` | `helfer/markdown_helfer.py` | 65 | MarkdownV2 (Cleanup, kein Escaper) | Keine externen Aufrufer gefunden. |
| `md_bold` / `md_code` / `md_italic` / `md_underline` / `md_strikethrough` / `md_spoiler` / `md_code_block` / `md_link` | `helfer/markdown_helfer.py` | 119–191 | MarkdownV2 | **0 externe Aufrufer** — vollständig toter Code. |
| `format_as_markdown_v2` / `create_progress_bar` / `format_file_size` / `format_duration` / `validate_markdown_v2` | `helfer/markdown_helfer.py` | 194–319 | MarkdownV2 | **0 externe Aufrufer** — toter Code (Modul wird nur wegen `escape_md_v2` importiert, nicht wegen dieser Formatierungs-Utilities). |
| `_escape_markdown` | `handlers/enhanced_status_handler.py` | 40 | Legacy `Markdown` (v1: nur `_ * \` [`) | 20× innerhalb derselben Datei (modulprivat); seit PARSE-MODE-AUDIT-Hotfix zusätzlich importiert von `handlers/admin/user_management_handler.py` und `handlers/enhanced_error_handler.py` (siehe Update oben). |
| `_escape_markdown` | `handlers/menu/content/greeting.py` | 56 | Legacy `Markdown` (v1: nur `_ * \` [`) | 2× innerhalb derselben Datei; Ergebnis fließt via `show_menu()` in `handlers/menu/rendering.py` (dort `parse_mode="Markdown"`). |
| `_escape_text` | `handlers/mugge_statistik_handler.py` | 178 | **Kein Escaping** (No-Op — Docstring: „Hilfsfunktion zum Escapen", tut aber nichts außer `str()`) | 32× innerhalb derselben Datei — ausschließlich für die (dokumentiert) Plain-Text-Pfade dieser Klasse; für die eine HTML-Stelle wird korrekt `html_escape` statt `_escape_text` verwendet. |
| `_md_escape` | `services/library_health/report.py` | 321 | **GFM-artiges Markdown** (`\ * _ \` [ ] \|`) — für CLI-/Datei-Report, **nicht** Telegram | 11× innerhalb `report.py`, konsumiert nur von `scripts/library_health_check.py` (CLI). Kein aktueller Telegram-Bezug, aber `findings.py` nennt explizit einen künftigen Telegram-Handler als möglichen Konsumenten (siehe Abschnitt 7). |
| `_md_code` | `services/library_health/report.py` | 333 | Wie `_md_escape` | 6× innerhalb `report.py`. |

---

## 4. Kreuzverwendungen

| Helper | Verwender | Erwarteter Modus | Tatsächlicher Modus | Risiko |
|---|---|---|---|---|
| — | — | — | — | **Keine harte Kreuzverwendung gefunden** (kein MarkdownV2-Helfer in HTML-Nachricht, kein HTML-Escaper in MarkdownV2-Nachricht, kein Escape-Helfer sichtbar in reinem Plain-Text verwendet). |
| `_md_escape`/`_md_code` (GFM) | derzeit nur `report.py`/CLI | — | — | **Strukturelles Zukunftsrisiko, kein aktueller Bug:** `services/library_health/findings.py` (Zeile 23) benennt einen „(künftig) Telegram-Handler" als möglichen Konsumenten von `render_summary_markdown()`. Der GFM-Escaper passt **weder** zu MarkdownV2 (escaped z. B. `.`, `-`, `(`, `)`, `!` nicht) **noch** zu Legacy-`Markdown` (escaped zusätzlich `]` und `\|`, die dort nicht reserviert sind) **noch** zu HTML (kein `html.escape()`). Würde dieser Report unverändert an einen Telegram-Handler mit einem der drei Modi angehängt, entstünde eine neue Instanz derselben Fehlerklasse wie NAV-F13/F14. |
| `**Bold**` (Doppel-Sternchen) | `navidrome_renderer.py` (durchgängig, MarkdownV2), sowie **alle** Legacy-`Markdown`-Dateien (`user_management_handler.py`, `backup_handler.py`, `duplicate_handler.py`, `enhanced_error_handler.py`, `help.py`, `rendering.py`) | Telegram-Bold: **Einzel-Sternchen** `*Text*` | **Doppel-Sternchen** `**Text**` (CommonMark-Stil) durchgängig verwendet | **Live gegen `logs/bot.log` verifiziert (Update oben): unkritisch.** Mehrfache erfolgreiche `render_album_detail()`-Sendungen mit exakt diesem Muster, keine zugehörigen Parse-Fehler. Kein Fix nötig. |

---

## 5. Ungesicherte dynamische Werte in MarkdownV2

Ergebnis für den MarkdownV2-Bereich (`navidrome_renderer.py` +
`navidrome_menu_handler.py` + `admin_operations.py`): **alle
identifizierten dynamischen Werte laufen durch `escape_md_v2()`**
(Artist-/Album-/Song-/Genre-/Playlist-Namen, Dauer, Songcount,
Jahr, Scan-Output, Exception-Text). Keine ungesicherte Stelle
gefunden — dieser Bereich ist nach den NAV-Fxx-Fixes sauber.

**Aber:** Der Auftrag fragt explizit nach MarkdownV2; die tatsächlich
ungesicherten dynamischen Werte liegen im **Legacy-`Markdown`-Bereich**
(vom Auftrag nicht explizit benannt, aber dieselbe Fehlerklasse):

| Datei | Zeile(n) | Wert-Typ | Risiko | Status |
|---|---|---|---|---|
| `handlers/admin/user_management_handler.py` | ~119 (`show_user_detail`), ~391 (`show_user_management_menu`, beim Implementieren zusätzlich gefunden) | `nav_user`/`navidrome_username` — freier, admin-eingegebener Text | **Crash** bei `_`, `` ` ``, `[` oder unpaarigem `*` im Namen (z. B. „john_doe"). | **Gefixt** (`PMA-F1`, siehe `docs/FINDINGS_INDEX.md`) |
| `handlers/admin/user_management_handler.py` | 272, 342 (`process_new_navidrome_user`/`process_edit_navidrome_user`) | `navidrome_username` | Ursprünglich hier vermutet — **Korrektur:** diese Stellen senden ohne `parse_mode` (bereits Plain-Text), kein tatsächliches Risiko. | Keine Aktion nötig (Fehleinschätzung korrigiert) |
| `handlers/admin/user_management_handler.py` | 337 (Log-Zeile, nicht Telegram) | `old_nav_user` | Kein Telegram-Risiko (nur Log). | Unverändert |
| `handlers/enhanced_error_handler.py` | 1729, 1775, 1843, 1906 (`error_msg = f"...: {e}"`, dann `_reply_or_edit()` mit Default `parse_mode="Markdown"`) | Exception-Text (beliebiger Inhalt, häufig Dateipfade) | **Crash** bei `_`/`` ` ``/`[` im Exception-Text — betrifft die Fehleranzeige selbst, die ausgerechnet dann greifen soll, wenn etwas schiefgeht. | **Gefixt** (`PMA-F2`, Default-`parse_mode` jetzt `None`) |
| `handlers/enhanced_error_handler.py` | 1828 (`handle_recent_errors_command`, `message_preview`, explizites `parse_mode="Markdown"`) | Exception-Text-Preview — beim Implementieren zusätzlich gefunden | Gleiche Fehlerklasse, aber im Erfolgspfad (nicht vom Default-Fix allein abgedeckt). | **Gefixt** (`PMA-F2`) |
| `handlers/duplicate_handler.py` | ~118 (Exception-Handler-Zweig ohne `error_handler`) | `{e}` (Exception-Text) | Hier **ohne** `parse_mode` gesendet (Plain-Text-Fallback) → kein Crash-Risiko an dieser Stelle, aber inkonsistent zum Rest der Datei. | Unverändert (kein akutes Risiko) |

---

## 6. Statische Literale mit reservierten Zeichen

| Datei | Zeile | Literal | Status |
|---|---|---|---|
| `handlers/navidrome_renderer.py` (`render_genre_detail`) | 539 | `\(erste 10 angezeigt\)` | **Gefixt** (NAV-F13) — Klammern korrekt escaped. |
| `handlers/navidrome_renderer.py` (`render_playlist_detail`) | 223 | `_{N} weitere Songs nicht angezeigt_` (kein `+` mehr) | **Gefixt** (NAV-F15) — `+` entfernt statt escaped. |
| `handlers/navidrome_renderer.py` (`render_album_detail`) | 112 | `_{N} weitere Songs nicht angezeigt_` (kein `+` mehr) | **Gefixt** (NAV-F16) — analog. |
| `handlers/navidrome_renderer.py` (`render_browse_genres`) | 469 | `Die Zahlen in Klammern zeigen die Anzahl der Songs pro Genre\.` | Punkt korrekt escaped; Text „Klammern" ist nur Beschreibung, keine echten Klammerzeichen im Literal. Kein offener Fund. |
| `handlers/navidrome_renderer.py` (`render_genre_detail`, `render_artist_detail`) | 504, 576 | `➕ {N} weitere anzeigen` / `➕ {N} weitere Alben` | Enthält kein reserviertes `+`-Zeichen mehr (Emoji statt Pluszeichen) und ist zudem **Button-Text** (InlineKeyboardButton), der nicht durch den Nachrichten-Parser läuft — kein Risiko. |
| `handlers/navidrome_renderer.py` (überall, `**...**`) | mehrfach | Doppel-Sternchen als Bold-Marker | **Live verifiziert, unkritisch** — siehe Abschnitt 4/Update. |
| Legacy-`Markdown`-Dateien (`user_management_handler.py`, `backup_handler.py`, `duplicate_handler.py`, `enhanced_error_handler.py`, `help.py`, `rendering.py`) | durchgängig | `**Überschrift**` | Gleiches Muster wie oben, im toleranteren Legacy-Modus ebenfalls unkritisch. **Nicht einzeln aufgelistet** (>50 Fundstellen) — bei Bedarf gezielt nachlieferbar. |

---

## 7. Empfehlungen

**Kurzfristig (Hotfix-Kandidaten):**
1. `user_management_handler.py`: `nav_user`/`navidrome_username` vor
   Einbettung in `parse_mode="Markdown"`-Texte durch einen
   Legacy-v1-Escaper leiten (z. B. das bereits existierende Muster aus
   `enhanced_status_handler.py`/`greeting.py` wiederverwenden statt
   ein drittes Mal neu zu definieren). **Umgesetzt, `PMA-F1`.**
2. `enhanced_error_handler.py`: Exception-Text vor Einbettung in
   `_reply_or_edit()` escapen oder `_reply_or_edit()` standardmäßig
   ohne `parse_mode` senden (analog zur bewussten Entscheidung in
   `menu/actions/download.py`) — Fehleranzeigen sollten nie selbst an
   Formatierungsfehlern scheitern können. **Umgesetzt (zweite Variante),
   `PMA-F2`.**
3. Live gegen die Telegram Bot API verifizieren, ob `**Bold**`
   (Doppel-Sternchen) unter `MarkdownV2` tatsächlich einen Fehler wirft
   oder toleriert wird. **Erledigt via Produktionslogs (Update oben) —
   toleriert, kein Fix nötig.**

**Mittelfristig (Struktur, weiterhin offen):**
4. Die jetzt **drei** identischen, aber unabhängig definierten
   `_escape_markdown()`-Aufrufer (`enhanced_status_handler.py` als
   kanonische Quelle, importiert von `user_management_handler.py` und
   `enhanced_error_handler.py`) in einen gemeinsamen, klar benannten
   Legacy-Markdown-Helfer in `helfer/markdown_helfer.py` (z. B.
   `escape_md_v1()`) überführen, analog zum bestehenden
   MarkdownV2-Helfer — verhindert eine weitere Ad-hoc-Kopplung zwischen
   Handler-Modulen. Bewusst NICHT im Rahmen der Hotfixes gemacht
   (Minimal-Diff-Prinzip, Wiederverwendung statt Neubau).
5. Vor einer etwaigen künftigen Telegram-Anbindung von
   `services/library_health/report.py::render_summary_markdown()`
   (laut `findings.py` als Möglichkeit genannt) den GFM-Escaper
   `_md_escape`/`_md_code` explizit gegen den dann gewählten
   `parse_mode` abgleichen — sonst entsteht dieselbe Fehlerklasse ein
   drittes Mal.
6. Die 8 toten Formatierungs-Helfer in `helfer/markdown_helfer.py`
   (`md_bold` u. a.) entweder tatsächlich einführen (Konsistenz-Gewinn)
   oder als bewusst unbenutzt markieren/entfernen — aktuell unklar, ob
   „geplant, aber nie verdrahtet" oder „Altlast".

**Langfristig (Konvention/Helfer):**
7. Ein projektweites, eindeutiges Namensschema für Escape-Helfer
   einführen, das den Ziel-Modus im Namen trägt (z. B.
   `escape_markdown_v2`, `escape_markdown_v1`, `escape_html`,
   `escape_none`) statt der aktuellen Mischung aus `_escape_markdown`,
   `_escape_text`, `_md_escape`, `escape_md_v2` — reduziert das Risiko,
   dass ein Helfer im falschen Modul für den falschen Modus
   wiederverwendet wird, sobald das Projekt wächst.
8. Erwägen, für neue Handler standardmäßig HTML statt MarkdownV2/Legacy-
   Markdown zu verwenden (wie bereits in `bot_restart_handler.py`
   dokumentiert entschieden: „Verwende HTML anstelle von MarkdownV2, um
   Escape-Probleme zu vermeiden") — HTML mit `html.escape()` hat sich in
   6 von 6 geprüften Dateien als konsistent und robust erwiesen,
   während Legacy-Markdown in 4 von 10 Dateien Lücken aufweist.

---

## 8. Explizit nicht gefunden

- Keine Verwendung des `ParseMode`-Enums außerhalb genau einer Datei
  (`mugge_statistik_handler.py`) — der Rest nutzt String-Literale.
- Keine Datei, die gleichzeitig denselben dynamischen Wert über zwei
  unterschiedliche Escape-Helfer für zwei unterschiedliche Modi schickt
  (kein „echter" Kreuzverwendungs-Crash gefunden).
- Kein Fund eines HTML-Escapers (`html.escape`) in einer MarkdownV2-
  oder Legacy-Markdown-Nachricht oder umgekehrt.
- Keine Verwendung von `parse_mode="MarkdownV2"` außerhalb von
  `navidrome_menu_handler.py`/`admin_operations.py` (die einzige
  Erwähnung in `enhanced_status_handler.py` ist ein Docstring-Verweis,
  kein tatsächlicher Aufruf).
- `services/` sendet keine Telegram-Nachrichten und enthält daher
  keine `parse_mode`-Verwendungen — konsistent mit der dokumentierten
  Architektur-Trennung.

---

## Werkzeug-Nutzung (Abschnitt 8 des Auftrags)

Reine Bash-Werkzeuge auf dem lokal geklonten Repo: `grep -rn`
(Mustersuche), `sed -n` (Zeilenbereiche lesen), `view` (Volltext
kleinerer Dateien), sowie eine einzelne `python3 -c`-Ausführung, um
den projekteigenen `validate_markdown_v2()`-Validator gegen ein
Beispiel-Literal laufen zu lassen (keine Schreibaktion, keine
Testsuite, keine Netzwerk-Aufrufe gegen Telegram). Keine
Code-Änderung, kein Commit, kein Branch.

Die Live-Verifikation im Update oben (2026-09-14) erfolgte zusätzlich
gegen `logs/bot.log` (reines Log-Lesen, keine Testsuite, kein Netzwerk-
Aufruf gegen Telegram) sowie `git log`/`git show` zur zeitlichen
Einordnung der bestehenden `enhanced_status_handler.py`-Fix-Commits.