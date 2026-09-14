# MusicBot Engineering Baseline v11

> **Status: 🟡 DRAFT (noch nicht eingefroren).**
>
> Laufender Zwischenstand seit dem v10-Freeze (2026-09-14). Hier werden
> pro ARCH-Phase/PR „ARCH Status", „Recent Major Changes" und Testzahlen
> mitgeschrieben (CLAUDE.md „Baseline-Pflege"). Die Abschnitte 4–6
> (Technical Debt / Security-Baseline / Architecture Freeze) bleiben
> Platzhalter bis zum v11-Freeze — bis dahin ist
> `docs/MusicBot_ENGINEERING_BASELINE_v10.md` der zitierbare eingefrorene
> Referenzpunkt, `docs/FINDINGS_INDEX.md` die laufend gepflegte
> Findings-Quelle.

---

## 1. Metadaten

| Feld | Wert |
|---|---|
| Baseline | v11 (DRAFT) |
| Vorgänger | `docs/MusicBot_ENGINEERING_BASELINE_v10.md` (Freeze 2026-09-14, 4250 passed / 1 skipped / 0 failed / 11 subtests passed) |
| Letzte vom Nutzer gemeldete Full-Suite-Zahl (aktuell, nach ARCH-033 „Telegram Level-2/Level-3 Repair (Pro-Artist)") | **4310 passed, 1 skipped, 11 subtests passed, 0 failed** (272,15 s), 2026-09-14. +60 gegenüber der v10-Freeze-Zahl (4250) — exakt deckungsgleich mit den 60 neuen ARCH-033-Tests: `tests/test_repair_service_level23.py` (+19, neu), `tests/test_doctor_runner.py` (+7, erweitert), `tests/test_library_repair_planner.py` (+6, erweitert), `tests/test_repair_handler_level23.py` (+28, neu). 0 Regressionen, unverändertes Skip-/Subtest-Muster (1/11) seit v9 durchgehend. |
| Zuwachs seit v10-Freeze | +60 passed (4250 → 4310), 0 failed |

---

## 2. ARCH Status seit v10-Freeze

| ARCH-Änderung | Commits | Ergebnis |
|---|---|---|
| **ARCH-033 „Telegram Level-2/Level-3 Repair (Pro-Artist)"** — letzte in ARCH-031 beschlossene, bis v10 noch offene Phase. Macht `METADATA_REPROCESSING` (L2) und `EXTERNAL_METADATA` (L3) über Telegram ausführbar, bewusst NUR pro Artist mit eigener Vorschau/Bestätigung (ADR-0003), nie als globaler Batch. Vier Phasen: (1) Service-Layer `execute_level2_repair()`/`execute_level3_repair()` in `repair_service.py` + Subprozess-Runner `run_level2_repair()`/`run_level3_repair()` in `doctor_runner.py`; (2) `group_candidates_by_artist()`/`ArtistCandidateSummary` in `planner.py`; (3) Telegram-Sub-Flow `l23rep:*` in `repair_musicbot_handler.py` inkl. Dispatcher-Verdrahtung; (4) dokumentierter, inaktiver Erweiterungspunkt für künftige COVER/LOUDNESS/DUPLICATE-Phasen (ARCH-034/035). Details: `docs/LIBRARY_REPAIR.md` §12, `docs/adr/0003` (IMPLEMENTED). | `64a7321`, `d4b1841`, `4e55801`, `d9436ba`, `f01ac9f` | 60 neue Tests, thematische Suite (`-k "repair or maintenance or menu or level or library_repair"`, 1305 Tests) grün, 0 Regressionen |

**Bewusste, nutzerbestätigte Abweichung von der ursprünglichen
Implementierungsvorgabe:** `execute_level2_repair()`/
`execute_level3_repair()` rufen `apply_level2()`/
`apply_external_metadata()` NICHT in-process über `asyncio.to_thread()`
auf (wie ursprünglich spezifiziert), sondern als eigenen Subprozess —
identisch zu `execute_safe_automatic_repair()`. Grund: `Enhanced-
MetadataProcessor` (`SingletonMixin`) wird bereits beim Bot-Start für
die Live-Download-Pipeline konstruiert; ein `asyncio.to_thread()`-Aufruf
hätte denselben Singleton potenziell gleichzeitig aus einem separaten
Thread heraus verwendet, während der Bot-Event-Loop weiterläuft — exakt
das Risiko, das den bestehenden Subprozess-Pfad von
`reprocessing_runner.py` ursprünglich begründet. Per `AskUserQuestion`
geklärt, Nutzer bestätigte „Subprozess statt in-process". Details:
`docs/adr/0003-telegram-level2-level3-per-artist-confirmation.md`,
Abschnitt „Implementierung".

---

## 3. Recent Major Changes (seit v10-Freeze)

- **ARCH-033 Phase 1 (Service-Layer):** `LevelRepairResult`-Dataclass,
  `_execute_level_repair()` (gemeinsame Implementierung für L2/L3,
  Stale-Plan-Schutz identisch zu `execute_safe_automatic_repair()`,
  Verification-Scan nur bei mind. 1 Erfolg, Finding-Resolution nur für
  tatsächlich verifiziert behobene Findings). Während der Umsetzung ein
  echter Architektur-Konflikt entdeckt und per Rückfrage geklärt (siehe
  oben). Dabei zusätzlich ein Late-Binding-Bug gefunden und behoben: ein
  beim Import gebautes `{"l2": run_level2_repair, ...}`-Dict hätte
  `patch.object()` in Tests ignoriert und einen echten Subprozess gegen
  die Produktionslibrary gestartet (in einem Testlauf tatsächlich
  passiert, verifiziert folgenlos — kein Treffer, da der Test-Artist
  nicht real existierte — und sofort gefixt: Namens-Lookup über
  `globals()[...]` zur Aufrufzeit statt eines früh gebundenen Dicts).
  Dasselbe Prinzip wurde in Phase 3 für den Telegram-Handler
  übernommen.
- **ARCH-033 Phase 2 (Artist-Gruppierung):** `group_candidates_by_artist()`
  gruppiert einen `RepairPlan` nach Artist mit getrennten L2-/L3-Zählern,
  sortiert nach Gesamtzahl absteigend, dann alphabetisch, deterministisch.
- **ARCH-033 Phase 3 (Telegram-Flow):** neuer `l23rep:*`-Sub-Flow auf
  `RepairMusicBotHandler` (kein neuer Handler — L2/L3 sind wie
  SAFE_AUTOMATIC Findings-getrieben, ADR-0001): Artist-Liste
  (index-basiert, paginiert, pro Telegram-Session in `context.user_data`
  gecacht, um nicht bei jedem Button-Tap einen vollen Health-Scan
  auszulösen) → Aktionsauswahl → read-only Preview mit
  levelspezifischem Warnhinweis → explizite Bestätigung → Ausführung →
  Ergebnis. Neuer Button „🛠️ L2/L3-Reparaturen (nach Artist)" in den
  bestehenden Reparaturvorschlägen, sichtbar sobald L2/L3-Kandidaten
  vorhanden sind.
- **ARCH-033 Phase 4 (Registry-Vorbereitung):** rein dokumentarischer,
  inaktiver Erweiterungspunkt neben den `_L23REP_*`-Dicts in
  `repair_musicbot_handler.py` — zeigt, wie eine künftige ARCH-034/035
  COVER/LOUDNESS/DUPLICATE an denselben generischen Flow anschließen
  würde, ohne neuen Callback-Namensraum. Kein aktiver Code.
- Dokumentation: `docs/LIBRARY_REPAIR.md` §12 (neu), `docs/adr/0003`
  PROPOSED → IMPLEMENTED (inkl. der zwei dokumentierten Abweichungen —
  Subprozess statt in-process, sowie Verification-Scan library-weit statt
  artist-gescoped, da kein artist-gescopter Scan-Modus existiert und
  ADR-0004 einen zweiten Scan-Mechanismus ausschließt), `docs/FINDINGS_INDEX.md`
  (ARCH-033 CLOSED, neuer OPEN-Eintrag für ARCH-034/035, P3), `docs/INDEX.md`.

---

## 4. Technical Debt — Snapshot

*(Platzhalter — wird beim v11-Freeze befüllt. Laufender Stand aller
offenen/zurückgestellten Punkte: `docs/FINDINGS_INDEX.md`.)*

---

## 5. Security-Baseline

*(Platzhalter — wird beim v11-Freeze befüllt.)*

---

## 6. Architecture Freeze

*(Platzhalter — Freeze-Gate-Audit noch nicht durchgeführt, kein
GO/NO-GO-Verdikt für v11.)*
