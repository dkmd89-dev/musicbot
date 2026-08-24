# ARCH-009 Phase 1 — Bestandsaufnahme der sieben ungenutzten `NavidromeAPI`-Methoden

Reine Entscheidungs-/Bestandsaufnahme, keine Codeänderung. Fortsetzung von
ARCH-009 (Migrationsplanung). Für jede der sieben Methoden: aktueller
Zweck, Produktions-Consumer, Tests, Einschätzung „geplantes Feature?“,
Empfehlung.

Testabdeckung wurde gegenüber ARCH-009 präzisiert: ein zunächst per Grep
gefundener `test_api`-Treffer in `tests/test_play_history_poller.py`
erwies sich als reiner Namens-Zufallstreffer
(`test_api_exception_is_caught_and_returns_false`, testet
`PlayHistoryPoller`/`get_now_playing`, nicht `NavidromeAPI.test_api()`).
Ebenso der `check_connection`-Treffer in
`tests/test_navidrome_menu_handler.py` — testet die separate,
Handler-eigene `_check_connection()`, nicht `NavidromeAPI.check_connection()`.

---

## Gruppe A: Telegram-Formatierung (3 Methoden)

### `format_full_status_message(stats: dict) -> str`

- **Zweck:** baut eine vollständig MarkdownV2-maskierte Telegram-Nachricht
  mit Server-Version, Scan-Status, Bibliotheks-Statistiken
  (Artist/Song/Genre-Counts) und Webinterface-Link aus einem `stats`-Dict.
- **Produktions-Consumer:** keiner.
- **Tests:** keine (0 Treffer, weder Charakterisierung noch sonstwo).
- **Geplantes Feature?** Kein direkter Beleg (kein Menü-Button, kein
  Command, kein TODO-Kommentar) — aber die durchdachte, vollständige
  Formatierung (Emoji, Struktur, Escaping) deutet auf ein einmal
  angedachtes Admin-Status-Feature hin, das nie verdrahtet wurde. Reine
  Vermutung, kein Beweis.
- **Empfehlung: ENTFERNEN.** Kein Beleg für aktive Planung, reines totes
  Gewicht (analog `FileUtils`, P-1). Bei Bedarf jederzeit aus der
  Git-Historie wiederherstellbar.

### `format_rescan_status_message(stats: dict) -> str`

- **Zweck:** formatiert ein Rescan-Ergebnis (Dauer, Bibliotheks-Counts)
  — laut eigenem Docstring explizit **ohne** MarkdownV2-Maskierung
  (Gegenstück zu `format_full_status_message`).
- **Produktions-Consumer:** keiner.
- **Tests:** keine.
- **Geplantes Feature?** Naheliegende Vermutung: als Ergänzung zu
  `execute_scan()` gedacht. Aber `execute_scan()` baut bereits selbst
  eine fertige Erfolgs-/Fehler-Nachricht (`message`-Rückgabewert) und
  wird genau so vom einzigen Consumer (`rich_menu_handler.py:727`)
  verwendet — `format_rescan_status_message()` wäre eine zweite,
  nie genutzte Formatierung für denselben Anwendungsfall.
- **Empfehlung: ENTFERNEN.** Redundant zum bereits aktiv genutzten
  Formatierungsweg in `execute_scan()` selbst.

### `format_web_interface_url_message() -> str`

- **Zweck:** baut eine einfache Nachricht mit Link zum Navidrome-
  Webinterface.
- **Produktions-Consumer:** keiner.
- **Tests:** keine.
- **Geplantes Feature?** Kein Beleg (kein „Webinterface öffnen“-Button in
  `handlers/navidrome_menu_handler.py`/`rich_menu_handler.py` gefunden,
  der das nutzen würde).
- **Empfehlung: ENTFERNEN.**

---

## Gruppe B: Server-Info/Diagnose (3 Methoden, mit interner Besonderheit)

### `get_full_server_info() -> dict`

- **Zweck:** aggregiert Server-Version, Scan-Status, Artist-/Song-/
  Genre-Counts in einem Dict — alleinige Datenquelle für
  `format_full_status_message()`.
- **Produktions-Consumer:** keiner.
- **Tests:** 2 Charakterisierungstests
  (`tests/test_navidrome_api_characterization.py`:
  `test_happy_path_aggregates_all_fields`,
  `test_exception_mid_way_leaves_remaining_fields_at_defaults`).
- **Zusatzbefund:** ruft für den Scan-Status-Teil **nicht**
  `get_scan_status()` auf, sondern dupliziert dessen Logik inline über
  einen eigenen `make_request("getScanStatus")`-Call — die beiden
  Methoden sind trotz überlappender Funktionalität nicht einmal intern
  verbunden.
- **Geplantes Feature?** Ausschließlich als Datenquelle für die bereits
  als „entfernen“ eingestufte `format_full_status_message()` relevant —
  ohne diese hat das Dict keinen Abnehmer.
- **Empfehlung: ENTFERNEN**, gekoppelt an `format_full_status_message()`.

### `get_scan_status() -> dict`

- **Zweck:** ruft den aktuellen Navidrome-Scan-Status (läuft gerade ein
  Scan, Zeitpunkt des letzten Scans) ab.
- **Produktions-Consumer:** keiner — **auch nicht intern** von
  `get_full_server_info()` (siehe Zusatzbefund oben, dort liegt eine
  eigene, parallele Implementierung).
- **Tests:** 2 Charakterisierungstests
  (`test_returns_scan_status_dict_on_success`,
  `test_returns_empty_dict_instead_of_raising_on_failure`).
- **Geplantes Feature?** Kein Beleg — vollständig eigenständig unbenutzt,
  auch nicht als interner Baustein.
- **Empfehlung: ENTFERNEN.**

### `test_api() -> str`

- **Zweck:** kombinierter Diagnose-Check — testet Server-Erreichbarkeit
  (Version ermitteln) und aktuell laufende Wiedergaben, baut daraus eine
  formatierte Telegram-Nachricht.
- **Produktions-Consumer:** keiner (der zunächst per Grep gefundene
  Treffer in `test_play_history_poller.py` war ein Namens-Zufallstreffer,
  siehe oben).
- **Tests:** keine echten (0 Treffer).
- **Geplantes Feature?** Naheliegend als Admin-Debug-/Diagnose-Command
  gedacht, aber kein Beleg für tatsächliche Planung (kein Command, kein
  Menü-Eintrag).
- **Empfehlung: ENTFERNEN.**

---

## Gruppe C: Verbindungstest (1 Methode, dokumentierte Ausnahme)

### `check_connection() -> bool`

- **Zweck:** einfacher asynchroner Ping-Check gegen die Navidrome-API
  (`make_request("ping")`, prüft `status == "ok"`).
- **Produktions-Consumer:** keiner direkt — `handlers/navidrome_menu_handler.py::_check_connection()`
  ist eine **separate**, bewusst einfachere synchrone Methode
  (`self.connection_status and NavidromeAPI is not None`), kein Aufruf
  der echten API-Methode.
- **Tests:** 3 Charakterisierungstests
  (`test_returns_true_when_ping_status_ok`,
  `test_returns_false_when_ping_status_not_ok`,
  `test_returns_false_instead_of_raising_when_make_request_fails`).
- **Geplantes Feature? — Ja, mit dokumentiertem Beleg.**
  `handlers/navidrome_menu_handler.py::_initialize_api()` enthält einen
  bereits aus einer früheren Session stammenden Kommentar (BUG-007-Fix):
  > „Ein voller Verbindungstest (`NavidromeAPI.check_connection()`) wäre
  > ein größerer, async-basierter Umbau — hier zunächst der kleinere,
  > eindeutig richtige Fix.“
  Das ist ein expliziter, schriftlicher Beleg dafür, dass
  `check_connection()` **bewusst zurückgestellt**, nicht vergessen wurde
  — die einzige der sieben Methoden mit einem solchen Beleg.
- **Empfehlung: BEHALTEN.** Einzige Methode dieser Bestandsaufnahme mit
  klarer Dokumentation einer zukünftig geplanten Nutzung. Löschen würde
  eine bereits als Folgeschritt angekündigte Verbesserung
  (asynchroner Verbindungstest statt reinem Config-Wert-Check)
  vorwegnehmend zunichtemachen.

---

## Zusammenfassung

| Methode | Consumer | Tests | Geplantes Feature? | Empfehlung |
|---|---|---|---|---|
| `format_full_status_message()` | 0 | 0 | kein Beleg | **ENTFERNEN** |
| `format_rescan_status_message()` | 0 | 0 | kein Beleg, redundant | **ENTFERNEN** |
| `format_web_interface_url_message()` | 0 | 0 | kein Beleg | **ENTFERNEN** |
| `get_full_server_info()` | 0 | 2 | nur als tote Datenquelle | **ENTFERNEN** |
| `get_scan_status()` | 0 (auch nicht intern) | 2 | kein Beleg | **ENTFERNEN** |
| `test_api()` | 0 | 0 | kein Beleg | **ENTFERNEN** |
| `check_connection()` | 0 direkt | 3 | **ja, dokumentiert (BUG-007)** | **BEHALTEN** |

6 von 7 Methoden zur Entfernung empfohlen, 1 zum Behalten. Keine Löschung,
keine Verschiebung, keine DI-Umstellung in diesem Schritt — Entscheidung
liegt beim Nutzer, insbesondere ob die Empfehlungen für Gruppe A/B
(6 Methoden) so bestätigt werden oder einzelne Methoden abweichend
behandelt werden sollen.
