# CC-LOGGER-L7.1 — Setup-Module-Logging Config-Respekt

**Datum:** 2026-09-27
**Vorgaenger:** L1-L7 (Logger-Kern-Migration), L6.1/L6.2 (UI-Controls)
**Status:** abgeschlossen.

---

## 1. Ausgangslage

L6.1/L6.2 haben file_handler- und level-Controls in der
Control-Center-UI eingefuehrt. Der manuelle Browser-Test zeigte:
fuer zwei Module (`EnhancedMetadataProcessor`, `EnhancedLoggerHandler`)
wirkten diese Schalter nicht.

**Ursache (in L7.1-Analyse verifiziert):**
`logger.py::setup_module_logging()` hat die uebergebenen Parameter
`level`, `file_handler`, `console_handler` nicht respektiert -
sondern hart `level` gesetzt und IMMER einen `EnhancedRotatingFileHandler`
+ ConsoleHandler angehaengt. Beide Sonderfaelle rufen
`setup_module_logging()` in ihrer `__init__()` auf, und zwar NACH dem
`_load_module_configs()`-Lauf (L4 Stufe 0) fuer `EnhancedMetadataProcessor`
(der erst spaeter, beim ersten Track, als Singleton konstruiert wird).

Ergebnis: der harte FileHandler + das harte DEBUG-Level haben die
Config-Werte ueberschrieben.

---

## 2. Loesung

**Keine Aenderung an Config-Schema, keinen neuen IPC-Kanal, keine
neuen APIs.** Zwei Bausteine:

### `logger.py::setup_module_logging()`

Zwei additive Parameter mit Default `True`:
enable_file_handler: bool = True
enable_console_handler: bool = True

- Default `True`/`True` = bisheriges Verhalten fuer alle anderen
  Aufrufer (nur die zwei Sonderfaelle rufen ueberhaupt auf).
- Bei `False` wird der jeweilige Handler NICHT angehaengt.
- Die bestehende Remove-First-Schleife (`for h in logger.handlers[:]:
  removeHandler(h)`) bleibt unbedingt - dadurch ist die Semantik
  eindeutig: `False` = am Ende kein solcher Handler am Logger.
- Rotation (EnhancedRotatingFileHandler, 2 MB x 3 Backups) bleibt
  unveraendert, wenn `enable_file_handler=True`.

### Beide Aufrufer

Lesen die persistierte Logger-Config selbst (in `services/logger_admin.py::
read_logger_config()`) und uebergeben die konkreten Werte. Fallback-
Werte (`level="DEBUG"`, `enable_file_handler=True`,
`enable_console_handler=True`) sind identisch zum bisherigen harten
Aufruf - greifen nur, wenn das Modul nicht in der Config steht oder die
Config nicht lesbar ist.

Kein Import-Zyklus: `services/logger_admin.py` importiert
`from logger import _module_loggers` - die Aufrufer (in
`handlers/`/`services/metadata/`) duerfen `read_logger_config` importieren,
`logger.py` selbst nicht.

---

## 3. Betroffene Dateien

| Datei | Aenderung |
|---|---|
| `logger.py` | Signatur + 2 additive Flags, bedingte Handler-Konstruktion |
| `handlers/enhanced_logger_menu_handler.py` | `read_logger_config()`-Import + Config-Aufloesung vor `setup_module_logging()` |
| `services/metadata/enhanced_metadata_processor.py` | analog |
| `tests/test_setup_module_logging.py` | neu, 9 Tests |

---

## 4. Verhaltensaenderung

**Ab dem ersten Neustart nach dem Fix:**

- `EnhancedMetadataProcessor` laeuft mit `level=INFO` (statt bisher
  hart `DEBUG`) und ohne eigenen FileHandler (Config: `file_handler=false`).
  Seine Logzeilen gehen ueber den Root-Logger nach `bot.log` statt in
  `logs/enhanced_metadata_processor.log`.
- `EnhancedLoggerHandler` analog: `level=INFO`, kein FileHandler.
  (Er war bereits vor dem Fix durch die spaetere `_apply_module_config()`
  korrekt konfiguriert - der Fix raeumt nur das Zwischenstadium auf,
  in dem kurz ein FileHandler anhing.)

Falls die zwei Dateien erhalten bleiben sollen, muss die Config
entsprechend angepasst werden (`file_handler: true` fuer die zwei
Module in `data/module_logger_config.json`).

**Keine Aenderung fuer:** alle anderen Aufrufer, die Rotation,
Dateinamen, Formatter, `propagate=False`.

---

## 5. Tests

`tests/test_setup_module_logging.py` (9 Tests):

**Basis-Flags:**
- Default unveraendert (FileHandler + ConsoleHandler)
- `enable_file_handler=False` -> kein FileHandler
- `enable_console_handler=False` -> kein ConsoleHandler
- beide `False` -> keine Handler
- Rotation erhalten (EnhancedRotatingFileHandler, kein plain FileHandler)

**Reihenfolge-Unabhaengigkeit:**
- Config-Apply nach setup -> Config gewinnt
- Config-Apply vor setup -> setup respektiert die Werte

**Sonderfaelle:**
- `EnhancedLoggerHandler` mit file=false, level=INFO -> korrekt
- `EnhancedMetadataProcessor` mit file=false, console=false, level=WARNING
  -> korrekt
- Fehlende Config -> Fallback-Werte = bisheriges Verhalten

---

## 6. Scope-Grenzen

Bewusst NICHT in L7.1:

- Keine Aenderung an `data/module_logger_config.json`.
- Kein neuer Endpunkt.
- Keine Aenderung an `_apply_module_config()`.
- Keine Aenderung an den 41 real aktiven, aber nicht in der Config
  gelisteten Modulen (Kategorie-D-Finding aus L7).
- Keine Aenderung an `BotRestartTrigger`, Repair-Lock, IPC,
  Download-System, Backup-System.

---

## 7. Verweise

- L2: docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md
- L3: docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md
- L4: docs/audits/CC-LOGGER-L4_STARTUP_CONFIG_API_2026-09-23.md
- L5: docs/audits/CC-LOGGER-L5_RUNTIME_SNAPSHOT_CONTROLLED_APPLY_2026-09-23.md
- L6: docs/audits/CC-LOGGER-L6_LOGGER_UI_2026-09-23.md
- L6.1: docs/audits/CC-LOGGER-L6.1_FILE_HANDLER_CONTROL_2026-09-27.md
- L6.2: docs/audits/CC-LOGGER-L6.2_LEVEL_CONTROL_2026-09-27.md
- L7: docs/audits/CC-LOGGER-L7_TELEGRAM_MIGRATION_2026-09-26.md
