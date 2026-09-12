# ARCH-024 — Menu-Datei-Dekomposition (Actions/Definitions/Rendering)

**Status:** REGISTERED — noch nicht begonnen.
**Scope:** `handlers/menu/rich_menu_system.py` (3117 Zeilen),
`handlers/menu/rich_menu_handler.py` (1608 Zeilen).

---

## Herkunft

`ARCH-021/P-1` (Menu-Architekturaudit, 2026-09-12) empfahl folgende
Phasenreihenfolge für die Zerlegung des Menüsystems:

```text
P-2 Models → P-3 Permissions → P-4 Session/State → P-5 Router-Härtung
    → P-6 Actions (domänenweise) → P-7 Definitions → P-8 Rendering
    → P-9 optional Onboarding-Extraktion
```

P-2/P-3/P-4 wurden als `ARCH-021/P-2`–`P-4` umgesetzt (Models/Permissions/
Session-Extraktion, PR #203, gemergt). P-5 „Router-Härtung" wuchs zu einem
eigenständigen, sicherheitsfokussierten Mini-Projekt mit eigener
Phasenzählung und wurde unter `ARCH-023` (P-1–P-7, COMPLETE) fortgeführt —
siehe `docs/MusicBot_ARCH-023_Menu_Router_Permission_Hardening.md`.

**Die ursprünglichen „P-6 Actions"/„P-7 Definitions"/„P-8 Rendering"/
„P-9 Onboarding" wurden dadurch nie umgesetzt** — `ARCH-023` belegte diese
Nummern bereits für inhaltlich andere Arbeit (Permission-Architektur-Audit
bzw. Handler-Level-Konsolidierung). Um diese Kollision nicht zu wiederholen,
läuft die Datei-Dekomposition ab jetzt unter der nächsten freien
ARCH-Nummer, **`ARCH-024`**, mit eigener, bei P-1 neu beginnender Zählung.

---

## Geplanter Phasenplan (Vorschlag, noch nicht freigegeben)

| Phase | Inhalt (ehemals) |
|---|---|
| ARCH-024/P-1 | Audit/Characterization: Ist-Stand der Actions-Gruppierung (Download, Stats/Family, Admin-Diagnostics, Admin-Operations, Library, Navidrome/Usermgmt), Abhängigkeiten, Testabdeckung |
| ARCH-024/P-2 | Actions-Extraktion (domänenweise, gemäß der im `ARCH-021/P-1`-Audit vorgeschlagenen fachlichen Gruppierung — orientiert an Kohäsion, nicht an Zeilenzahl) |
| ARCH-024/P-3 | Definitions-Extraktion (`initialize_menu_structure()`) |
| ARCH-024/P-4 | Rendering-Extraktion (`render_menu()`/`get_menu_text()`/`show_menu()`) |
| ARCH-024/P-5 | optional: Onboarding-Extraktion (`start`/`help` aus `RichMenuHandler`) |

Dieser Plan ist ein Vorschlag aus der ursprünglichen `ARCH-021/P-1`-Analyse
und muss vor Beginn erneut gegen den aktuellen Code-Stand verifiziert
werden (insbesondere: `RichMenuSystem`/`RichMenuHandler` haben sich durch
`ARCH-021/P-2`–`P-4` und `ARCH-023/P-1`–`P-7` seit dem ursprünglichen Audit
verändert — Router-Logik, Permission-Aufrufe und Modellzugriffe sind jetzt
anders verdrahtet als zum Auditzeitpunkt).

---

## Voraussetzung

`ARCH-023` (P-1–P-7) sollte vor Beginn von `ARCH-024` committed, gepusht
und gemergt sein — saubere Baseline, keine zwei große Umbauten gleichzeitig
im Working Tree.

**Keine automatische Umsetzung. Wartet auf explizite Freigabe für P-1.**
