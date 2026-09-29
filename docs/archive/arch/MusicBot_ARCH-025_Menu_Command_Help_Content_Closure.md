# MusicBot ARCH-025 — Content Separation & Phase Closure

> **Status: ARCH-025 STATUS: COMPLETE**
>
> Diese Datei ist ein eigenständiges, neues Protokoll und ergänzt
> (nicht ersetzt) `docs/MusicBot_ARCH-025_Command_Help_Content_Decomposition.md`
> (erste ARCH-025-Iteration, PR #206, gemergt). Sie dokumentiert die
> hier durchgeführte **Content-Separation-Closure**: die letzte
> verbleibende statische UI-Text-Vermischung in
> `handlers/menu/content/greeting.py`/`help.py` wird in ein neues
> Modul `handlers/menu/content/messages.py` ausgelagert. Kein neuer
> ARCH-Phasen-Umfang, keine Verhaltensänderung — reiner Abschluss.

---

## 1. Ausgangslage

Nach der ersten ARCH-025-Iteration (PR #206) lag die Command-/Help-Logik
bereits in `handlers/menu/content/{user_context,greeting,help}.py`,
strukturell sauber von `RichMenuHandler`/`RichMenuSystem`/`actions/`
getrennt. Innerhalb dieser drei Dateien blieb jedoch eine offene
Vermischung bestehen: `greeting.py` und `help.py` enthielten sowohl
die Orchestrierungslogik (Kontext laden, Rollen/Features ermitteln,
Nachricht zusammensetzen und senden) **als auch** die eigentlichen
statischen, user-facing Texte (Begrüßungsformulierungen, Hilfetexte,
Button-Labels) direkt eingebettet als Literal-Strings.

Diese Vermischung erschwerte:

- das Auffinden aller user-facing Texte an einer Stelle (z. B. für
  spätere Lokalisierung oder Textänderungen ohne Berührung der
  Orchestrierungslogik),
- die klare Trennung „Was kann/sieht der User?" (`user_context.py`)
  von „Was sagen wir dem User?" (fehlte bisher als eigene Schicht).

`user_context.py` (133 Zeilen, `FEATURES`-Katalog + 5 Kontext-Funktionen)
war von dieser Vermischung nicht betroffen — dort handelt es sich um
strukturierte Feature-Metadaten (ID, Emoji, Titel, Beschreibung,
Commands, `min_role`, `menu_id`), nicht um Fließtext, und wurde daher
bewusst nicht angefasst.

**Phase-1-Verifikation** (kurzer Abgleich, keine erneute Vollanalyse):
`git log`/`git status` bestätigten HEAD unverändert bei `e2a8b02`
(Merge PR #206), sauberer Arbeitsbaum. `wc -l` bestätigte
`greeting.py`=122, `help.py`=232, `user_context.py`=133 Zeilen — exakt
der aus der vorherigen ARCH-025-Iteration bekannte Stand. Kein
Abweichungsbefund → direkter Übergang zur Implementierung.

---

## 2. Durchgeführte Änderungen

### 2.1 Neues Modul: `handlers/menu/content/messages.py`

Enthält ausschließlich reine String-Konstanten, 1:1 aus `greeting.py`/
`help.py` verschoben (keine Textänderung — gleiche Formulierungen/
Emojis/Markdown/Reihenfolge, per Zeichen-für-Zeichen-Vergleich
verifiziert, siehe Abschnitt 5):

- **Greeting-Konstanten** (12): `GREETING_WELCOME_NEW`,
  `GREETING_WELCOME_NEW_LINE_2`, `GREETING_WELCOME_NEW_LINE_3`,
  `GREETING_WELCOME_BACK`, `GREETING_WELCOME_BACK_LINE_2`,
  `GREETING_ROLE_LINE`, `GREETING_FEATURES_HEADER`,
  `GREETING_QUICKSTART_HEADER`, `GREETING_QUICKSTART_MENU`,
  `GREETING_QUICKSTART_HELP`, `GREETING_HINT_DOWNLOAD`,
  `GREETING_HINT_SEARCH`.
- **Help-Konstanten** (14): `HELP_INTRO_TITLE`, `HELP_INTRO_SUBTITLE`,
  `HELP_GENERAL_COMMANDS_HEADER`, `HELP_CMD_START`, `HELP_CMD_MENU`,
  `HELP_CMD_HELP`, `HELP_CMD_CANCEL`, `HELP_SUPPORT_HEADER`,
  `HELP_SUPPORT_TEXT`, `HELP_MAIN_MENU_TEXT`, sowie die 4 vormals in
  `help.py` als Funktionsrückgabewerte liegenden statischen Hilfetexte
  `HELP_DOWNLOAD`, `HELP_STATS`, `HELP_NAVIDROME`, `HELP_ADMIN`.
- **Button-Labels** (6, alle mehrfach verwendet):
  `BTN_MAIN_MENU` (🏠 Hauptmenü, ×4), `BTN_CLOSE` (❌ Schließen, ×3),
  `BTN_HELP_DOWNLOAD` (📥 Downloads, ×2), `BTN_HELP_STATS`
  (📊 Statistiken, ×2), `BTN_HELP_NAVIDROME` (🎵 Navidrome, ×2),
  `BTN_HELP_ADMIN` (⚙️ Admin-Hilfe, ×2).
- **Fehlertext** (1): `ERROR_GENERIC` ("❌ Ein Fehler ist aufgetreten.").

`messages.py` hat **keine** Imports außer dem eigenen Modul-Docstring —
insbesondere keine Abhängigkeit auf `RichMenuHandler`, `RichMenuSystem`,
`actions/` oder Telegram-Objekte (verifiziert per `grep -n "^import\|^from"`,
kein Treffer).

Bewusst **nicht** zentralisiert (einmalige Verwendung, keine
Duplizierung, siehe Master-Prompt-Regel gegen erzwungene
Zentralisierung): `"⬅️ Zurück zur Hilfe"` (help.py, ×1), `"❓ Hilfe"`
(greeting.py, ×1). Ebenfalls bewusst nicht zentralisiert: die
dynamischen Pro-Feature-Zeilen in `greeting.py`/`help.py`
(`f"{feature['emoji']} **{feature['title']}**"` usw.) — das sind
Renderings über Laufzeitdaten aus `user_context.FEATURES`, kein
statischer Text.

### 2.2 `greeting.py` — nur Orchestrierung

`send_start_message()` bleibt vollständig zuständig für: Nutzerkontext
laden, Neuling-/Rollen-/Feature-Ermittlung, dynamische Werte einsetzen,
Keyboard aufbauen, Telegram-Nachricht senden. Literale Strings wurden
durch `messages.*`-Referenzen ersetzt, z. B.:

```python
messages.GREETING_WELCOME_NEW.format(username=username)
messages.GREETING_ROLE_LINE.format(role_emoji=role_emoji, role_title=user_role.capitalize())
InlineKeyboardButton(messages.BTN_MAIN_MENU, callback_data="menu:main")
```

Die Rollen-Emoji-Zuordnung (`{"moderator": "🛡️", "admin": "⚙️", "owner": "👑"}`)
wurde als modulprivate Konstanten `_ROLE_EMOJI`/`_ROLE_EMOJI_DEFAULT` in
`greeting.py` belassen (Lookup-Struktur der Orchestrierung, kein
reiner UI-Text) statt nach `messages.py` verschoben — bewusste
Abgrenzung, damit `messages.py` strikt auf String-Konstanten begrenzt
bleibt.

### 2.3 `help.py` — dünne Wrapper + Orchestrierung

`get_download_help()`/`get_stats_help()`/`get_navidrome_help()`/
`get_admin_help()` sind jetzt Ein-Zeiler-Wrapper:

```python
def get_download_help() -> str:
    return messages.HELP_DOWNLOAD
```

`send_help_message()`/`send_help_callback_response()` bleiben für
Themenauswahl, Keyboard-Aufbau und Telegram-Versand zuständig; alle
zutreffenden Literale wurden durch `messages.*`-Referenzen ersetzt.

### 2.4 `user_context.py` — unverändert

Keine Änderung (per `git diff --stat` bestätigt: kein Diff). `FEATURES`
bleibt strukturierte Metadaten, keine Textzentralisierung erforderlich.

---

## 3. Final Architecture

```text
handlers/menu/content/
├── greeting.py     Greeting-Orchestrierung: Kontext laden, Neuling-/
│                   Rollen-/Feature-Ermittlung, dynamische Werte
│                   einsetzen, Keyboard aufbauen, Nachricht senden.
│                   Statische Texte kommen aus messages.py.
├── help.py         Help-Orchestrierung: Themenauswahl, Keyboard-
│                   Aufbau, Telegram-Versand. get_*_help()-Funktionen
│                   sind dünne Wrapper um messages.HELP_*.
├── user_context.py Nutzer-/Feature-Kontext ("Was kann/sieht der
│                   User?"): FEATURES-Katalog (strukturierte
│                   Metadaten, kein Text) + get_user_role()/
│                   get_available_features()/is_new_user()/
│                   get_user_info()/load_user_data(). Unverändert.
└── messages.py     Statischer UI-Content ("Was sagen wir dem
                    User?"): 33 reine String-Konstanten
                    (Begrüßung/Hilfe/Buttons/Fehlertext). Keine
                    Projekt-Logik-Abhängigkeiten.
```

### Architekturentscheidung

Statische UI-Texte werden zentral in Python-Content-Modulen gehalten.
Ein externes JSON/YAML/i18n/CMS-System ist für die aktuelle
Projektgröße und den aktuellen Anwendungsfall nicht erforderlich.

Dynamische Werte (Feature-Listen, Nutzerrollen, Usernamen) werden
weiterhin zur Aufrufzeit in `greeting.py`/`help.py` per `.format()`/
f-string in die in `messages.py` definierten Templates eingesetzt —
`messages.py` bleibt reiner Text-Speicher ohne eigene Logik.

### Dependency Direction

```text
RichMenuHandler
  → content/greeting.py   → content/messages.py
  → content/help.py       → content/messages.py
  → content/user_context.py
```

`messages.py` hat keine Abhängigkeit auf `RichMenuHandler`,
`RichMenuSystem` oder `actions/` — verifiziert durch Inspektion aller
Import-Zeilen (keine vorhanden). Keine Rückreferenz, keine
Zirkularität.

---

## 4. Behavior

Die Zentralisierung verändert nicht das beabsichtigte User-facing
Verhalten.

Alle Textinhalte, Emojis, Markdown-Formatierungen, Button-Beschriftungen,
Callback-Daten, Befehle und die Reihenfolge der zusammengesetzten
Nachrichten sind identisch zum Stand vor dieser Änderung. Die einzige
Änderung ist die **Position** des statischen Contents (jetzt in
`messages.py` statt inline in `greeting.py`/`help.py`).

Die in der vorherigen ARCH-025-Iteration charakterisierte Asymmetrie
zwischen `send_help_message()`s und `send_help_callback_response()`s
Exception-Handling (erstere ruft bei vorhandenem `error_handler` dessen
`handle_command_error()` auf, letztere loggt nur) bleibt unverändert
bestehen — nicht Teil dieses Scopes.

---

## 5. Static Audit (kein Testlauf, keine `compileall`-Ausführung)

| Kategorie | Ergebnis | Nachweis |
|---|---|---|
| Content Separation | **PASS** | `grep -n '"'` auf `greeting.py`/`help.py` bestätigt: keine verbleibenden mehrzeiligen/statischen UI-Text-Literale außer den bewusst inline belassenen Einzel-Verwendungen (`"⬅️ Zurück zur Hilfe"`, `"❓ Hilfe"`) und dynamischen f-strings über Laufzeitdaten. |
| Responsibility Separation | **PASS** | `user_context.py` = Kontext (unverändert), `messages.py` = Text (neu, reine Konstanten), `greeting.py`/`help.py` = Orchestrierung (Funktionskörper unverändert in Struktur, nur Literale ersetzt). |
| Dependency Direction | **PASS** | `messages.py`: keine Imports. `greeting.py`/`help.py`: importieren `messages` + `user_context`, keine Rückreferenz auf `RichMenuHandler`/`RichMenuSystem`/`actions/`. |
| Circular Dependencies | **PASS** | Keine Zyklen möglich, da `messages.py` blattseitig ist (keine eigenen Imports). |
| Behavior Preservation | **PASS** | Alle 33 `messages.py`-Konstanten per Python-Skript Zeichen-für-Zeichen gegen die ursprünglichen Literale verglichen (inkl. `.format()`-Ergebnisse mit Testwerten) — 100 % Übereinstimmung, keine Abweichung. |
| Scope Discipline | **PASS** | `git status --short`/`git diff --stat` bestätigen: nur `handlers/menu/content/greeting.py` (M), `handlers/menu/content/help.py` (M), `handlers/menu/content/messages.py` (neu) sowie die in Abschnitt 6 gelisteten Dokumentations-Dateien betroffen. Keine Änderung an Download-Pipeline, Permission-System, Router, Error-Handler, Library Health/Repair, Navidrome, Duplicate-System, Reprocessing, Backup oder Logger. |

Zusätzliche Verifikation: `ast.parse()` auf allen 3 geänderten/neuen
Python-Dateien lief fehlerfrei (Syntax-Validierung ohne `compileall`,
wie vom Master-Prompt gefordert).

---

## 6. Technical Debt (Re-Verifikation ARCH-024/025, keine neue Änderung)

Die 3 in der vorherigen ARCH-025-Iteration (PR #206) behobenen
"Remaining Technical Debt"-Punkte aus ARCH-024 wurden erneut per
`grep`-Audit geprüft und als weiterhin behoben bestätigt — **keine
erneute Änderung notwendig**:

1. **Stale Kommentar** zu `_handle_download_new()`/
   `_handle_download_history()` in `rich_menu_system.py`: kein Treffer
   mehr (Kommentar zeigt korrekt auf `actions/download.py`).
2. **6 tote Importe** (`Any`, `MenuState`, `Path`, `json`, `timedelta`,
   `CallbackQueryHandler`) in `rich_menu_system.py`: keiner mehr
   vorhanden.
3. **5 tote `_handle_stats_*`-Methoden** (`rich_menu_system.py`) und
   **5 tote `_system`-Funktionen** (`actions/stats.py`): keine
   verbleibenden Treffer (einzige verbleibende `_handle_stats_*`-Methode
   ist die weiterhin live gebundene `_handle_stats_library_overview`).

Keine neuen offenen Technical-Debt-Punkte durch diese Closure-Phase
identifiziert.

---

## 7. Closure

Definition of Done:

```text
[x] Greeting-Content zentralisiert
[x] Help-Content zentralisiert
[x] relevante Button-Labels zentralisiert (≥2 Verwendungen)
[x] user_context.py sinnvoll unverändert belassen
[x] messages.py hat keine Menü-/Handler-Abhängigkeiten
[x] keine neuen zirkulären Abhängigkeiten
[x] bestehendes Verhalten erhalten (Zeichen-für-Zeichen verifiziert)
[x] ARCH-024/025 Technical Debt erneut geprüft (bereits behoben)
[x] keine sachfremden Änderungen
[x] Dokumentation aktualisiert (dieses Dokument + TELEGRAM_MENU_SYSTEM.md
    + ENGINEERING_BASELINE_v10.md DRAFT + INDEX.md)
[x] finaler Architektur-Audit durchgeführt (Abschnitt 5)
[x] keine Tests durch den Implementierungsprozess ausgeführt
[x] kein compileall durch den Implementierungsprozess ausgeführt
[x] Vollsuite vom Nutzer bestätigt: 3460 passed, 1 skipped, 11 subtests
    passed, 0 failed (244,26 s) — exakt der prognostizierte Wert
    (3461 - 1 aus PR #206 + 0 aus dieser Closure-Phase), 0 Regressionen
```

**ARCH-025 STATUS: COMPLETE**
