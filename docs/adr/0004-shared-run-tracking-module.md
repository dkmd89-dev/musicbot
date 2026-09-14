---
status: DECIDED (ARCH-031, 2026-09-14, noch nicht implementiert)
---

# ADR-0004: Gemeinsames `run_tracking.py` statt Duplikat oder Vermischung

## Kontext

`repair_service.py` (520 Zeilen) enthält aktuell — alles modul-privat
(führendes `_`) — Lock (`acquire_repair_lock()`/`release_repair_lock()`/
`is_repair_running()`), Journal-Fenster-Lesung (`_read_journal_window()`),
Run-Index (`_load_runs_index()`/`_append_run_record()`/
`_write_json_atomic()`), Historie (`load_repair_history()`) und Statistik
(`compute_repair_statistics()`). Diese Mechanik ist **nicht**
Finding-spezifisch — sie kennt weder `FindingsRegistry` noch
`generate_finding_id()`, sondern arbeitet ausschließlich mit der
Journal-Datei und dem Run-Index.

Für die neuen Library-Maintenance-Actions (ADR-0001) wird exakt dieselbe
Mechanik benötigt: derselbe Lock (verhindert Überlappung mit dem
Finding-Flow), dasselbe Journal, derselbe Run-Index (damit
"Reparaturhistorie"/"Repair-Statistik" künftig auch Maintenance-Läufe
zeigen können).

## Entscheidung

Drei Varianten wurden bewertet (ARCH-031 §12):

- **Variante A** (eigener `maintenance_service.py`, komplett unabhängig):
  würde Lock/Journal-Fenster/Run-Index **duplizieren** — genau die Art
  Duplikat, die ADR-0002 gerade beseitigt.
- **Variante B** (alles in `repair_service.py`): vermischt zwei
  unterschiedliche Semantiken (Finding-getrieben vs. Command-getrieben)
  in einer Datei, deren Docstring/Struktur durchgehend Finding-Flow-
  spezifisch ist — schlechte Trennschärfe für zukünftige Erweiterungen.
- **Variante C — gewählt:** die geteilte Low-Level-Mechanik wird nach
  `services/library_repair/run_tracking.py` extrahiert (reiner Refactor,
  keine Verhaltensänderung: gleiche Funktionen, gleiche Dateipfade,
  gleiche Locking-Semantik). `repair_service.py` (Finding-Flow) und das
  neue `maintenance_service.py` (Command-Flow) importieren beide daraus.

```text
services/library_repair/run_tracking.py   (NEU, aus repair_service.py extrahiert)
    acquire_repair_lock() / release_repair_lock() / is_repair_running()
    read_journal_window()
    load_runs_index() / append_run_record() / write_json_atomic()
    load_repair_history() / compute_repair_statistics()
              ▲                                  ▲
              │                                  │
      repair_service.py                  maintenance_service.py (NEU)
      (Finding-Flow, unveraendert                (Command-Flow, ADR-0001)
       in Verhalten/Public-API)
```

`repair_musicbot_handler.py`s bestehende Importe aus `repair_service`
(`build_repair_plan`, `execute_safe_automatic_repair`,
`load_repair_history`, `compute_repair_statistics`, …) bleiben
**unverändert funktionsfähig** — `repair_service.py` re-exportiert die
verschobenen Namen (`from .run_tracking import load_repair_history, ...`),
kein Breaking Change für bestehende Aufrufer.

## Konsequenzen

- Run-Records erhalten ein neues Feld `"kind": "repair" | "maintenance"`
  (additiv, Default fehlt bei alten Einträgen → als `"repair"`
  interpretiert für Rückwärtskompatibilität), damit Historie/Statistik
  künftig zwischen beiden Flow-Typen unterscheiden können (ARCH-031 §13).
- **Ein** gemeinsamer Lock für beide Flows (keine Feingranularität pro
  Artist) — ein Maintenance-Lauf für Artist A und ein Finding-Repair-Lauf
  blockieren sich gegenseitig, auch wenn ihre Datei-Scopes sich nicht
  überschneiden. Bewusste Vereinfachung (bestehendes Verhalten für den
  Finding-Flow bleibt exakt erhalten, kein neues Nebenläufigkeitsrisiko).
- Reiner Extraktions-Refactor: bestehende `tests/test_repair_service.py`
  (29 Tests) müssen nach der Extraktion unverändert grün bleiben (gleiche
  Modul-Pfade der Konstanten ggf. per Test-Anpassung, aber gleiches
  Verhalten) — Teil der Testmatrix in ARCH-031 §21/D.
