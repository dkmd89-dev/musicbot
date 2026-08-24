# ARCH-009 Phase 5 — Verbleibende Präsentations-/Telegram-Verantwortlichkeiten: Analyse

Reine Analysephase gemäß `docs/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md`
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
`docs/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md` (Abschnitt 3)
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
   `docs/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md` (Abschnitt 8,
   Punkt 3) entschieden werden?
3. Soll der tote `ParseMode`-Import (Abschnitt 3) unabhängig davon entfernt
   werden (Option 3), oder weiterhin unangetastet bleiben, bis eine
   größere Bereinigung ansteht?

**Es wird nicht selbstständig mit einer Umsetzung begonnen.** Nächster
Schritt erst nach expliziter Nutzerentscheidung, in einem eigenen Branch,
mit eigenem PR/Review/Merge-Zyklus wie in allen vorherigen
ARCH-009-Schritten.
