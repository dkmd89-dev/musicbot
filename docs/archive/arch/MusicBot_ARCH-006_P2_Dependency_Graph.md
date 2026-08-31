# ARCH-006 — Vollständiger Import-/Dependency-Graph `services/` (P-2-Vorbereitung)

Reine Analyse, keine Codeänderung. Grundlage für die P-2-Entscheidung
("Telegram-Kopplung in `services/` entfernen") sowie zur Abgrenzung
verwandter, aber unabhängiger Architekturfragen.

---

## 1. Methode

Alle 39 Python-Dateien unter `services/` per Grep auf `import`/`from`
durchsucht (Top-Level und lazy/in-function Imports), Ziele kategorisiert:
neutrale Basis-Schicht (`config`, `logger`, `utils.*`, `cookie_handler`,
stdlib, third-party) vs. potenzielle Layer-Verletzung (`klassen.*`,
`handlers.*`, `telegram.*`, `bot.py`) vs. Struktur-Inkonsistenz
(`api.*` — externe Adapter außerhalb der `services/clients/`-Konvention).

---

## 2. Layer-Verletzungen — services/ → höhere Schichten

### 2.1 `services/downloader/utils/download_result_reporter.py`

```python
from telegram.error import TelegramError
from handlers.duplicate_handler import DuplicateEntry
```

Nicht nur oberflächliche Imports — funktional tief gekoppelt:
`update.message.reply_text(...)` wird direkt in der Klasse aufgerufen
(zweimal, Zeilen 169 und 319), `DuplicateEntry` als Typannotation für
`build_duplicate_message()`. Der Telegram-Versand ist die Kernaufgabe der
Klasse, nicht eine Randabhängigkeit.

**Konsument:** ausschließlich `klassen/download_handler.py`.

### 2.2 `services/downloader/utils/progress_tracker.py`

```python
from telegram import Update
```

Konstruktor nimmt ein `Update`-Objekt entgegen (`self.update = update`),
ruft ebenfalls selbst `self.update.message.reply_text(message)` auf
(Zeile 76) — Fortschrittsanzeige während des Downloads.

**Konsumenten:** `services/downloader/utils/download_utils.py`
(services-intern) und `klassen/download_handler.py`.

**Damit ist der P-2-Scope vollständig kartiert:** keine weiteren
`telegram.*`/`handlers.*`-Importe in der gesamten `services/`-Baumstruktur
(explizit geprüft — auch der Kern-Downloader-Pfad `download_utils.py`,
`enhanced_metadata_processor.py`, alle `download/*.py` und
`metadata/*.py`, alle `clients/*.py`, alle `statistik/*.py` sind frei
davon).

---

## 3. Struktur-Inkonsistenz — verwandt, aber keine Telegram-Kopplung

### 3.1 `services/statistik_service.py`

```python
from api.navidrome_api import NavidromeAPI
```

Externer API-Adapter (Navidrome-REST-API), aber `api/navidrome_api.py`
liegt außerhalb der durch P-11 etablierten Konvention
(`services/clients/` = ausschließlich externe Integrationsadapter). Keine
Telegram-/Handler-Kopplung — reine Platzierungsfrage, strukturell
identisch zum ursprünglichen P-11-Fund, nur für `api/` statt `klassen/`.

**Bewertung:** eigener, unabhängiger Kandidat für eine spätere
Architekturentscheidung (analog P-11). **Nicht Teil von P-2.**

---

## 4. Zyklische Abhängigkeiten

Vollständige Kantenliste (services-interne Importe, neutrale Basis-Schicht
ausgeklammert) durchgegangen — kein Zyklus gefunden. Insbesondere:

- `download_utils.py` → `enhanced_metadata_processor.py` → (`services/clients/*`,
  `metadata/*`, `download_artifact_cleanup.py`) — keiner dieser Zielknoten
  importiert zurück zu `download_utils.py`.
- `download/interfaces.py` → `utils/metadata/models.py` — reines
  Dataclass-Modul ohne Rückimporte.
- `metadata_result_translator.py` → `download/models.py` +
  `utils/metadata/models.py` — beide ohne Rückimporte.

Bestätigt den bereits in `docs/archive/arch/MusicBot_ARCH-003_Services_Phase1_Analyse.md`
(Abschnitt 2) dokumentierten Befund — weiterhin gültig nach P-1, P-11,
ARCH-005 und P-14.

---

## 5. Legacy-Imports

Keine gefunden. Alle Importe sind konsistent voll qualifiziert
(`services.X.Y`-Stil bzw. paket-lokale relative Importe wie
`from .models import ...` innerhalb desselben Unterpakets — Standard-Praxis,
kein Problem). P-11 hat die letzten verbliebenen `klassen.*`-Importe aus
`services/` bereits bereinigt: aktuell **0 Treffer** für
`from klassen`/`import klassen` in der gesamten `services/`-Baumstruktur.

---

## 6. `services/` → `klassen/` (direkt)

**0 Treffer.** Die einzige Kopplungsrichtung nach oben verläuft über
`handlers/`+`telegram` direkt (Abschnitt 2), nicht über `klassen/`. Das
deckt sich mit der erwarteten Architektur: `klassen/download_handler.py`
ist der Orchestrator, der `services/` aufruft — nicht umgekehrt. Das
eigentliche Problem ist, dass zwei `services/`-Module selbst Telegram
ansprechen, statt nur Daten zurückzugeben und die Telegram-Kommunikation
vollständig `klassen/download_handler.py` zu überlassen.

---

## 7. Bewertung: P-2-relevant vs. unabhängige Folgearbeit

**P-2-relevant** (kompletter Scope, keine weiteren versteckten Stellen):
- `download_result_reporter.py` (Abschnitt 2.1)
- `progress_tracker.py` (Abschnitt 2.2)

**Unabhängig, spätere Architekturarbeit** (kein Teil von P-2):
- `api/navidrome_api.py`-Platzierung (Abschnitt 3.1) — eigener Kandidat,
  keine Telegram-Kopplung, sollte nicht mit P-2 vermischt werden.

Keine Codeänderung in diesem Schritt. Die eigentliche P-2-Umsetzung
(Telegram-Entkopplung der beiden genannten Module) erfordert eine
separate Nutzerentscheidung — insbesondere zur Frage, ob `klassen/download_handler.py`
künftig die Telegram-Kommunikation vollständig übernimmt (die beiden
Module würden dann nur noch Daten/Nachrichtentexte zurückgeben) oder ob
ein anderer Schnitt gewählt wird.
