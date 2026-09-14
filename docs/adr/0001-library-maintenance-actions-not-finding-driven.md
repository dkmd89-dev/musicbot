---
status: PROPOSED (Nutzerentscheidung 2026-09-14, noch nicht implementiert)
---

# ADR-0001: Library-Maintenance-Actions als eigener, nicht Finding-getriebener Flow

## Kontext

Drei neue, eigenstaendige Scripts (`scripts/fix_artist_casing.py`,
`scripts/remove_legacy_genre_atom.py`, `scripts/set_genre.py`, Commit
`6037abf`) decken Metadaten-Korrekturen ab, fuer die es in
`services/library_health/issues.py` **keinen** Issue-Code gibt:

- `fix_artist_casing.py` — Casing von `©ART`/`ARTISTS` gegen
  `mapping/artist_overrides.json` / `case_preserve.yaml` normalisieren.
- `remove_legacy_genre_atom.py` — Legacy-Freeform-Atom
  `----:com.apple.iTunes:GENRE` entfernen, wenn `©gen` bereits existiert.
- `set_genre.py` — `©gen` gezielt setzen (manuell oder aus
  `mapping/artist_genre.yaml`); **kein Defekt-Erkennungsmuster**, sondern
  eine gezielte Nutzeraktion ("setze Genre X fuer Artist Y").

Der bestehende Repair-Flow (`docs/LIBRARY_REPAIR.md` §10) ist durchgehend
Finding-getrieben:

```text
Health-Scan -> Issue -> planner.py::REGISTRY -> RepairCandidate -> Preview
-> Confirm -> Execute -> Verification-Rescan -> Finding RESOLVED
```

Diese drei Operationen in dieses Modell zu zwingen, wuerde fuer die ersten
zwei neue Health-Issue-Codes (`ARTIST_CASING_INCONSISTENT`,
`GENRE_LEGACY_ATOM_PRESENT`) und eine Detection-Erweiterung in
`services/library_health/file_analysis.py` erfordern — eine
Scope-Erweiterung der P0-geschuetzten, bewusst reinen Health-Scanner-Schicht
(CLAUDE.md §3/§4). Fuer `set_genre.py` passt das Modell strukturell gar
nicht: "setze Genre X" ist keine Reparatur eines erkannten Defekts, sondern
eine explizite Anwender-Entscheidung — vergleichbar mit einem manuellen
Tag-Editor, nicht mit einem Health-Finding.

## Entscheidung

Die drei Operationen werden als eigene Kategorie **"Library-Maintenance-
Actions"** modelliert — Telegram-/CLI-Kommandos, die **ohne** Bezug zu
einem Health-Finding direkt ausgefuehrt werden:

```text
Telegram (LibraryMaintenanceHandler, NEU)
   |
maintenance_service.py (services/library_repair/, NEU)
   |
artist.py / genre.py (services/library_repair/, NEU, reine Funktionen)
   |
executor.py (bestehende Safety-/Backup-/Verify-Pipeline, um
             apply_artist_casing() / apply_legacy_genre_cleanup() /
             apply_set_genre() erweitert)
```

`services/library_health/` bleibt **vollstaendig unveraendert** — kein
neuer Issue-Code, keine Detection-Erweiterung, keine Beruehrung der P0-
read-only-Garantie. `planner.py::REGISTRY` bleibt unveraendert.

Die Korrektheit einer Maintenance-Action wird **ausschliesslich per Datei**
verifiziert (Ziel-Atom(e) + Audio-Essenz-MD5 + Tag-Fingerprint aller
uebrigen Atome — das bereits in den drei Scripts vorhandene Muster), nicht
durch einen zweiten Health-Scan. Es gibt daher **kein** Aequivalent zu
"Finding automatisch RESOLVED nach Verification-Rescan" — Erfolg wird pro
Datei im selben Journal-Lauf sichtbar.

## Konsequenzen

- **Vorteil:** P0-Schicht `services/library_health/` bleibt unangetastet,
  kein zusaetzliches ARCH-Vorprojekt fuer neue Issue-Codes noetig.
- **Vorteil:** `set_genre.py` (manuelle Aktion) und die beiden
  defekt-erkennenden Scripts teilen sich dieselbe Ziel-Architektur —
  konsistente Behandlung statt Sonderfall.
- **Vorteil:** dedupliziert `safety_check()`/`essence_md5()`/
  `tags_fingerprint()`/Backup-Logik (aktuell 3x fast identisch in den
  Scripts UND teilweise bereits in `executor.py` vorhanden) auf eine
  einzige Stelle in `executor.py`.
- **Nachteil / bewusst in Kauf genommen:** diese drei Operationen tauchen
  **nicht** im Health-Score, nicht in der Findings-Registry und nicht in
  "Offene Reparaturen" auf — ein Admin muss sie aktiv ueber das neue
  "🧹 Library-Wartung"-Menue anstossen, sie werden nie automatisch als
  Teil eines Health-Scans vorgeschlagen. Das ist so gewollt (gezielte
  Aktion, keine Defekt-Behebung), sollte aber in `docs/LIBRARY_REPAIR.md`
  explizit als zweiter, paralleler Flow dokumentiert werden, damit er
  nicht mit dem Finding-Lifecycle verwechselt wird.
- **Journal-Konsequenz:** die neuen `apply_*()`-Funktionen schreiben in
  dieselbe Produktions-Journal-Datei (`<DATA_DIR>/library_repair_journal.jsonl`)
  wie L1/L2/L3 — das behebt die aktuelle Inkonsistenz, dass die drei
  Scripts eigene, temporaere `/tmp/musicbot_test/*.jsonl`-Journale
  schreiben, die nicht Teil der Repair-Historie/-Statistik sind (siehe
  Migrationsplan, `docs/designs/library-repair-telegram-integration-overview.md`).

## Alternativen (verworfen)

1. **Neue Health-Issue-Codes** (ARTIST_CASING_INCONSISTENT,
   GENRE_LEGACY_ATOM_PRESENT) + volle Finding-Integration — verworfen:
   groesserer Scope, beruehrt P0-Schicht, passt nicht fuer `set_genre.py`.
2. **Andock-Pfad wie DUPLICATE** (`--allow-delete` -> Subprozess-Aufruf von
   `resolve_duplicates.py`) — verworfen (Nutzerentscheidung): dort bleibt
   die Logik in einem separaten CLI-Skript, das nur angedockt wird: fuer
   drei Operationen, die langfristig genauso gehaertet/getestet werden
   sollen wie L1, ist eine echte In-Process-Integration in
   `services/library_repair/` konsistenter als drei weitere Subprozess-
   Andockstellen.
