# ARCH-009 Phase 5 — Verbleibende Präsentations-/Telegram-Verantwortlichkeiten: Analyse

Reine Analysephase gemäß `docs/archive/arch/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md`
Phase 5. Keine Codeänderung, keine vorsorgliche Umstrukturierung. Prüft,
welche Telegram-spezifischen Verantwortlichkeiten in `api/navidrome_api.py`
nach ARCH-009 Phase 2 (tote Methoden entfernt) und Phase 4
(Subprocess-Extraktion) tatsächlich noch bestehen — gemäß dem in der
Roadmap festgelegten Grundsatz für den späteren Navidrome-Client:

> Ein späterer Navidrome-Client darf:
> - keine `telegram.*`-Abhängigkeiten besitzen
> - keine Telegram-Objekte speichern
> - keine Telegram-Nachrichten direkt versenden
> - keine Telegram-spezifische Markdown-Formatierung enthalten

---

## 1. Methoden-Audit gegen den Grundsatz

`api/navidrome_api.py` enthält nach Phase 2/4 noch sieben öffentliche
Methoden plus die interne `_build_url()`. Jede einzeln gegen die vier
Grundsatz-Punkte geprüft:

| Methode | `telegram.*`-Import genutzt? | speichert Telegram-Objekte? | sendet Telegram-Nachrichten? | enthält Telegram-Markdown-Formatierung? | Befund |
|---|---|---|---|---|---|
| `_build_url()` | nein | nein | nein | nein | sauber |
| `make_request()` | nein | nein | nein | nein | sauber |
| `check_connection()` | nein | nein | nein | nein | sauber (gibt `bool` zurück) |
| `get_artists()` | nein | nein | nein | nein | sauber (gibt `List[Dict]` zurück) |
| `get_now_playing()` | nein | nein | nein | nein | sauber (gibt `List[Dict]` zurück) |
| `search()` | nein | nein | nein | nein | sauber (gibt `Dict` zurück) |
| **`execute_scan()`** | **nein** (kein Telegram-Objekt-Import genutzt) | nein | nein (baut nur String, Versand liegt beim Handler) | **ja — in allen vier Ausgängen** | **einzige verbleibende Verletzung** |

**Ergebnis: Von sieben verbleibenden öffentlichen Methoden verletzt genau
eine (`execute_scan()`) den Grundsatz** — und zwar ausschließlich beim
vierten Kriterium (Telegram-spezifische Markdown-Formatierung), nicht bei
den ersten drei. Das bestätigt exakt die in
`docs/archive/arch/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md` (Abschnitt 3)
dokumentierte Vermischung und zeigt, dass Phase 4 diese bewusst
unverändert gelassen hat (wie vorgegeben).

---

## 2. `execute_scan()` im Detail — vier Fundstellen

Repo-weit per Grep verifiziert (`grep -n "escape_md_v2\|EMOJI\[" api/navidrome_api.py`):
alle vier Treffer liegen ausschließlich in `execute_scan()`
(Zeilen 156, 159, 164, 172):

```python
# Erfolg
message = f"{EMOJI['scan']} Scan erfolgreich: \n```{escape_md_v2(result.stdout)}```"

# Fehlschlag (returncode != 0)
message = f"{EMOJI['error']} Scan fehlgeschlagen: \n```{escape_md_v2(result.stderr)}```"

# Timeout
f"{EMOJI['warning']} Scan dauert länger als {e.timeout_seconds} Sekunden \\– bitte im Log prüfen\\."

# generische Exception
f"{EMOJI['error']} Unerwarteter Fehler: `{escape_md_v2(str(e))}`"
```

Keine weiteren Fundstellen in der Datei — `format_full_status_message()`,
`format_rescan_status_message()`, `format_web_interface_url_message()`
(die ursprünglichen Haupt-Formatierungsmethoden) wurden bereits in Phase 2
vollständig entfernt.

### Consumer-Auswirkung

Der einzige Consumer, `handlers/menu/rich_menu_handler.py::_handle_navidrome_scan()`
(Zeile 727), verwendet die von `execute_scan()` gelieferte `message`
**unverändert** direkt in `query.edit_message_text(message, parse_mode="MarkdownV2")`
— er trifft selbst keine Formatierungsentscheidung, sondern verlässt sich
vollständig auf die fertige Nachricht. Eine Verschiebung der Formatierung
in den Handler würde also nicht nur `execute_scan()`, sondern auch diesen
einen Aufrufer aktiv verändern (anders als Phase 4, wo der Consumer dank
Bridge-Musters unverändert bleiben konnte).

---

## 3. Fund: toter `telegram.*`-Import

```python
from telegram.constants import ParseMode
```

(`api/navidrome_api.py:11`) wird **an keiner Stelle der Datei verwendet**
(verifiziert per Grep — 0 Treffer für `ParseMode` außerhalb der
Import-Zeile). Das ist eine eigenständige, vom obigen Formatierungs-Befund
unabhängige Angelegenheit:

- Funktional wirkungslos (totes Gewicht, kein Verhaltenseinfluss).
- Formal aber genau die Art von `telegram.*`-Abhängigkeit, die der
  Grundsatz für den späteren Client ausschließt — auch wenn sie nicht
  aktiv „schuld“ an der Vermischung in `execute_scan()` ist.
- War bereits in ARCH-009 Phase 2 als vorbestehender toter Import notiert
  und dort bewusst **nicht** entfernt („außerhalb des engen Auftrags
  dieses Schritts“ — analog `re`, `subprocess`, `Path`). Phase 5 ist der
  erste Schritt in dieser Roadmap, dessen erklärtes Ziel direkt
  „Telegram-spezifische Verantwortlichkeiten prüfen“ ist — daher wird der
  Fund hier erneut aufgeführt, nicht automatisch entfernt.

---

## 4. Was Phase 5 an neuen Erkenntnissen gegenüber Phase 3 liefert

Phase 3 (Analyse von `execute_scan()`) hatte die Telegram-Vermischung
bereits identifiziert und als „Variante D“ (Telegram-Trennung, separater
Schritt) vorgeschlagen. Phase 5 bestätigt und **schließt** diese Analyse
ab zwei Punkten:

1. **Vollständigkeitsnachweis**: Es gibt außer `execute_scan()` **keine**
   weitere Methode mit Telegram-Bezug im verbleibenden `NavidromeAPI`-Code
   — Phase 4 hat also keine neue Vermischung eingeführt, und es gibt
   keinen „versteckten“ zweiten Fund, der eine größere Migration nötig
   machen würde. Der Umfang einer Telegram-Trennung ist exakt auf
   `execute_scan()` begrenzt.
2. **Zusatzfund toter Import** (`ParseMode`), der in der Phase-3-Analyse
   nicht gesondert erwähnt wurde, weil dort der Fokus auf
   `execute_scan()` selbst lag, nicht auf der gesamten Datei.

---

## 5. Optionen für eine Umsetzung (falls gewünscht — keine Empfehlung zur sofortigen Umsetzung)

### Option 1 — Nichts tun (Status quo)

`execute_scan()` bleibt wie in Phase 4 belassen: dünne Bridge zu
`NavidromeScanTrigger`, aber weiterhin mit eingebauter
MarkdownV2-Formatierung. Kein Risiko, aber der Grundsatz „kein
Telegram-Code im späteren Client“ bleibt für diese eine Methode
unerfüllt.

### Option 2 — Telegram-Formatierung in den Handler verschieben (= Variante D aus Phase 3)

`execute_scan()` gibt ein strukturiertes Ergebnis zurück (z. B.
`ScanRunResult`/eine neue kleine Ergebnisstruktur mit `timeout_seconds`
bei Timeout, `error`-Text bei genereller Exception statt bereits fertiger
MarkdownV2-Nachricht). `_handle_navidrome_scan()`
(`handlers/menu/rich_menu_handler.py`) übernimmt `EMOJI`/`escape_md_v2`
und baut die vier Nachrichtenvarianten selbst. Einziger betroffener
Consumer, daher überschaubarer, aber echter Änderungsumfang (im
Unterschied zu Phase 4 kann hier **nicht** rein intern gebridged werden,
da die Formatierung selbst der zu verschiebende Teil ist).

### Option 3 — Toten `ParseMode`-Import separat entfernen, Formatierungsfrage (Option 1/2) getrennt entscheiden

Der tote Import ist unabhängig von der Formatierungsfrage in
`execute_scan()` — könnte als eigener, minimaler Cleanup-Schritt
behandelt werden, unabhängig davon, ob/wann Option 2 umgesetzt wird.

Diese drei Optionen sind **keine Empfehlung**, sondern die aus dem
tatsächlichen Codebestand abgeleiteten Handlungsalternativen für das
Entscheidungsgate.

---

## 6. Entscheidungsgate

Diese Analyse ist abgeschlossen. **Keine Codeänderung wurde vorgenommen.**

Offene Entscheidungen für einen möglichen nächsten Schritt:

1. Soll die Telegram-Formatierung aus `execute_scan()` in den Handler
   verschoben werden (Option 2), oder bleibt der Status quo (Option 1)
   vorerst bestehen?
2. Falls Option 2: soll das zusammen mit oder getrennt von der
   Ergebnis-/Rückgabestruktur-Frage aus
   `docs/archive/arch/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md` (Abschnitt 8,
   Punkt 3) entschieden werden?
3. Soll der tote `ParseMode`-Import (Abschnitt 3) unabhängig davon entfernt
   werden (Option 3), oder weiterhin unangetastet bleiben, bis eine
   größere Bereinigung ansteht?

**Es wird nicht selbstständig mit einer Umsetzung begonnen.** Nächster
Schritt erst nach expliziter Nutzerentscheidung, in einem eigenen Branch,
mit eigenem PR/Review/Merge-Zyklus wie in allen vorherigen
ARCH-009-Schritten.

---

## 7. Umsetzung (2026-08-24, Branch `arch/arch-009-phase5-telegram-presentation-extraction`)

Nutzer-Entscheidung: Option 2 (Telegram-Formatierung aus `execute_scan()`
in den Handler verlagern). Der tote `ParseMode`-Import (Option 3) bleibt
bewusst unangetastet — separate, nicht getroffene Entscheidung.

### Entscheidungsgate während der Umsetzung

Die bisherige Rückgabe `tuple[bool, str]` von `execute_scan()` **war**
bereits die fertige Telegram-MarkdownV2-Nachricht — ohne
Telegram-Formatierung in `NavidromeAPI` konnte diese Bedeutung nicht
erhalten bleiben. Das ist eine öffentliche API-Änderung im Sinne von
Umsetzungsregel 4; vor der Umsetzung wurde daher ein Entscheidungsgate
eingelegt (zwei Varianten zur Wahl gestellt: `execute_scan()` vollständig
entfernen vs. als dünner Pass-Through mit neuem Rückgabetyp behalten).
**Nutzerentscheidung: dünner Pass-Through.**

### `api/navidrome_api.py`

- `execute_scan()` ist jetzt ein reiner Pass-Through:
  ```python
  @classmethod
  async def execute_scan(cls) -> ScanRunResult:
      log_handler_info("Starte Navidrome Scan-Prozess.", context="NavidromeAPI")
      return await NavidromeScanTrigger.run_scan()
  ```
  Kein eigenes Exception-Handling mehr — `ScanTimeoutError`,
  `AttributeError`/`TypeError` (Konfigurationsfehler) und alle sonstigen
  Exceptions aus `NavidromeScanTrigger.run_scan()` werden unverändert an
  den Aufrufer durchgereicht.
- Imports `from emoji import EMOJI` und
  `from helfer.markdown_helfer import escape_md_v2` entfernt (nicht mehr
  benötigt — 0 verbleibende Verwendungen in der Datei, per Grep
  verifiziert).
- `from telegram.constants import ParseMode` **bewusst unverändert**
  belassen (Option 3 — separate, nicht getroffene Entscheidung; war
  bereits vor diesem Schritt toter Import, siehe Abschnitt 3).

### `handlers/menu/rich_menu_handler.py`

- Neue Imports: `from api.navidrome_scan_trigger import ScanTimeoutError`,
  `from emoji import EMOJI`, `from helfer.markdown_helfer import escape_md_v2`.
- `_handle_navidrome_scan()` baut jetzt selbst die vier
  MarkdownV2-Nachrichten — Text/Emojis/Escaping 1:1 aus der vorherigen
  `execute_scan()`-Implementierung übernommen:
  - Erfolg: `f"{EMOJI['scan']} Scan erfolgreich: \n```{escape_md_v2(result.stdout)}```"`
  - Fehlschlag: `f"{EMOJI['error']} Scan fehlgeschlagen: \n```{escape_md_v2(result.stderr)}```"`
  - Timeout (`except ScanTimeoutError as e`): `f"{EMOJI['warning']} Scan dauert länger als {e.timeout_seconds} Sekunden \\– bitte im Log prüfen\\."`
  - generische Exception (`except Exception as e`): `f"{EMOJI['error']} Unerwarteter Fehler: \`{escape_md_v2(str(e))}\`"`
- Struktur bewusst zweistufig (innerer try/except für
  `execute_scan()`+Erfolg/Fehlschlag/Timeout, äußerer try/except als
  Sicherheitsnetz für sonstige Exceptions **und** für einen Fehlschlag
  des `edit_message_text()`-Aufrufs selbst) — entspricht der
  ursprünglichen zweistufigen Absicherung vor Phase 4/5, bei der ein
  Fehlschlag von `edit_message_text()` ebenfalls einen Fallback-Versuch
  auslöste.
- Bereits vorhandene `self.logger.error(f"❌ Navidrome-Scan-Fehler: {e}")`-
  Zeile im äußeren `except` **wiederverwendet** (nicht neu eingeführt) —
  war laut ARCH-009-Phase-3-Analyse zuvor totes Sicherheitsnetz, da
  `execute_scan()` bis Phase 4 nie propagierte. Wird durch diesen Schritt
  erstmals aktiv erreichbar. Ergänzt um `exc_info=True`, um den
  vollständigen Traceback zu protokollieren — entspricht der Log-Tiefe,
  die vorher `log_handler_error(e, ..., exc_info=True)` innerhalb von
  `execute_scan()` selbst lieferte (sonst wäre das eine stille
  Verschlechterung der Diagnosefähigkeit gewesen, siehe CLAUDE.md Regel 11
  „Logs als Engineering-Werkzeug“).
- Timeout- und Konfigurationsfehler-Logging bleibt unverändert an seinem
  bisherigen Ort: `NavidromeScanTrigger.run_scan()` loggt
  `ScanTimeoutError`/`AttributeError`/`TypeError` bereits selbst vor dem
  Werfen (unverändert seit Phase 4) — keine doppelte Protokollierung nötig.

### Tests

- `tests/test_navidrome_api_characterization.py::TestExecuteScan` (4 Tests,
  neu geschrieben): verifiziert den Pass-Through-Vertrag —
  `ScanRunResult` wird unverändert (`is`-Identität) zurückgegeben,
  `ScanTimeoutError`/`AttributeError` werden unverändert durchgereicht
  (`pytest.raises`). Ersetzt die vorherigen Bridge-Formatierungstests
  (die Formatierung wird jetzt woanders getestet).
- `tests/test_rich_menu_handler.py::TestHandleNavidromeScan` (5 Tests,
  1 neu): Erfolg, Fehlschlag, **neu:** Timeout, Admin-Check, generische
  Exception — verifiziert für jede der vier sichtbaren Nachrichtenvarianten
  Emoji, Kerntext und `parse_mode="MarkdownV2"` per Substring-Prüfung
  gegen `edit_message_text.call_args`.
- `tests/test_navidrome_scan_trigger.py`: unverändert (Subprocess-Ebene
  von diesem Schritt nicht berührt, Umsetzungsregel 9).

### Regressionslauf

**Gezielt:** 74 Tests grün (vorher 73 — +1 neuer Timeout-Test im Handler).

**Vollständig:** 1009 bestanden (vorher 1008 — Differenz von 1 entspricht
exakt dem neuen Timeout-Test), unverändert 15 bekannte Vorbestand-Fehler,
keine neuen Fehlschläge.

### Import-/Architekturprüfung

- `api/navidrome_api.py`: `EMOJI`/`escape_md_v2` vollständig entfernt (0
  Treffer per Grep, nur noch in einem Docstring-Kommentar erwähnt).
  `ParseMode`-Import bleibt bestehen — bewusst unverändert, siehe oben.
- Kein Zirkelimport: `handlers.menu.rich_menu_handler` →
  `api.navidrome_api` → `api.navidrome_scan_trigger`, keine Rückkante.
- `handlers/menu/rich_menu_handler.py` importiert weiterhin korrekt
  (Import-Smoke-Test erfolgreich).
- `api/navidrome_scan_trigger.py` (`NavidromeScanTrigger`) unverändert —
  weiterhin 0 Telegram-Bezüge (per Grep verifiziert), Umsetzungsregel 9
  eingehalten.
- `check_connection()` unverändert (Umsetzungsregel 8, per `git diff`
  verifiziert — 0 geänderte Zeilen).
- Keine Verschiebung nach `services/clients/` (Umsetzungsregel 7).

### Offen (bewusst nicht Teil dieses Schritts)

- Toter `ParseMode`-Import in `api/navidrome_api.py` (Option 3, separate
  Entscheidung).
- ARCH-009 Phase 6-9 (Zielposition/DI des verbleibenden Adapters).
- Aus `docs/archive/arch/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md` Abschnitt 8:
  Punkte 4-6 (ungetestete Normalisierungszweige waren bereits in Phase 4
  ergänzt, toter Handler-`except`-Pfad ist mit diesem Schritt implizit
  aktiv geworden statt entfernt, 45-Sekunden-Timeout-Beobachtung weiterhin
  unverifiziert).

**ARCH-009 Phase 5 damit abgeschlossen.**
