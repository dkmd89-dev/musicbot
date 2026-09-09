# Library Closure Phase — Audit & Final Report

**Typ:** Umsetzungs-Audit (Read-only-Analyse → 7 PRs → Verifikation)
**Datum:** 2026-09-09
**Auftrag:** „MASTER PHASE — COMPLETE LIBRARY REPAIR, REVIEW & TELEGRAM-READY CLOSURE"
**Branch:** `feat/library-closure-cp1`

---

## 1. Ausgangslage (Read-only-Analyse)

Das Library-System war zu Beginn **weitgehend fertig** (Phase 1 „Health Scanner"
PR #145–#147, Phase 2 „Smart Library Repair" PR #146/#148–#156, Phase-3-
Telegram-Integration PR #157–#164, P1–P3 Production-Audit PR #172–#178 —
alle als 🟢 APPROVED geschlossen).

Vollständig vorhanden und unverändert übernommen:

- `services/library_health/` — Diagnose, read-only technisch bewiesen
- `services/library_health/findings.py` — `FindingsRegistry`, stabile
  `generate_finding_id()`, Lifecycle `OPEN/RESOLVED/FALSE_POSITIVE/RESOLVED_BY_SCAN`,
  atomare Persistenz, `FindingsRegistryError` bei Korruption
- `services/library_repair/planner.py` — `REGISTRY`: genau 1 Mapping pro
  Health-Code; `registry_covers_all_health_codes()` + Test
- `services/library_repair/executor.py` — alle 8 Executoren, Safety/Backup/
  Journal/Audio-Essenz-Verifikation/Rollback, gegen Produktion gelaufen
- `services/library_repair/repair_service.py` — Telegram-Core-API
  (`build_repair_plan` / `execute_safe_automatic_repair` / Lock / History /
  Statistik / Regressionserkennung)
- Telegram: `library_doctor_handler.py`, `library_health_review_handler.py`,
  `repair_musicbot_handler.py` — alle Admin-gated, Hintergrund-Tasks
- ReplayGain statt Loudnorm: `replaygain_repairs.py`; Download-Pipeline
  Schritt 15b seit PR #188 ebenfalls RG-Tag — **kein aktiver
  Loudnorm-Re-Encode-Pfad mehr** (repoweit verifiziert)

**7 echte Lücken** identifiziert (Details Abschnitt 3).

---

## 2. Entscheidungen (Nutzer, 2026-09-09)

| Frage | Entscheidung |
|---|---|
| `ACCEPTED`-Semantik | **`FALSE_POSITIVE` umdeuten** (minimal, keine Schema-Migration) |
| Review-CLI | **ID-Flags additiv**, interaktiver Modus bleibt Default |
| Telegram Accepted/Unaccept | **nur Core-API + Result-Modelle + Doku** (UI später) |
| Per-Repair-Verification (PR E) | **einschließen** |
| Volle Testsuite | **Nutzer** (Auftrag §31 / CLAUDE.md §8.A) |

---

## 3. Die 7 Lücken → wie geschlossen

| # | Lücke | PR | Umsetzung |
|---|---|---|---|
| G1 | Review-CLI kein ID-basiertes Bedienmodell | C | `--accept` / `--unaccept` / `--accepted` / `--show` / `--summary` additiv in `scripts/library_health_review.py` |
| G2 | keine Reaktivierung | B | `unaccept_finding()` — Status zurück auf `OPEN`, History-Eintrag; vom Scan-Merge getrennt |
| G3 | stale accepted findings nicht sichtbar | B | `get_accepted_findings()` markiert `present_in_latest_scan == False`; `ReviewSummary.accepted_stale` |
| G4 | Core-API unvollständig | B | `accept_finding` / `unaccept_finding` / `get_accepted_findings` / `get_review_summary` + `ReviewSummary`-Dataclass in `findings.py` |
| G5 | keine Tri-State-Summary | C+D | CLI `--summary`; `report.py` Labels 🟢 Repariert / ⚪ Akzeptiert + Summary-Block |
| G6 | Test-Lücken (§34/§35/§41) | F | Lifecycle-Tests, Idempotenz-Tests, End-to-End-Closure-Test |
| G7 | Telegram Accepted/Unaccept | (bewusst zurückgestellt) | Core-API + Result-Modelle vorhanden & dokumentiert (`LIBRARY_HEALTH.md` §1a); UI = spätere Phase (Auftrag §29 erlaubt das) |

Zusätzlich **PR A** (Coverage-Matrix): `disposition_for_level()` /
`disposition_for_code()` in `planner.py` (reiner Roll-up der 8 RepairLevel
auf `AUTO_REPAIR` / `MANUAL_REVIEW` / `UNREPAIRABLE`),
`docs/audits/LIBRARY_CLOSURE_COVERAGE_MATRIX_2026-09-09.md`,
`tests/test_library_repair_disposition_matrix.py` (11 Tests).

**PR E** (Per-Repair-Verification): `_verify_issue_resolved()` in
`executor.py` — nach jedem echten `SUCCESS` bei `apply_level1` /
`apply_level1_rename` / `apply_cover_repairs` / `apply_external_metadata`
eine frische Einzeldatei-Analyse; Befund weiterhin da → `UNRESOLVED`.
Details: `LIBRARY_REPAIR.md` §5b.

---

## 4. §42 Final Quality Gate

| Kriterium | Status | Beleg |
|---|---|---|
| Jeder `ALL_CODES`-Eintrag klassifiziert | ✅ | `test_library_repair_planner.py` + `test_library_repair_disposition_matrix.py` |
| Keine stale Planner-Codes | ✅ | `test_registry_has_no_stale_codes` |
| Jede AUTO_REPAIR-Aktion besitzt Executor | ✅ | `test_every_auto_repair_code_has_exactly_one_executor` |
| Jede AUTO_REPAIR-Aktion besitzt Verifikation | ✅ | Executor: Atom/Audio-Essenz + Einzeldatei-Recheck (PR E) + aggregierter Scan; L2: `_l2_issue_resolved` |
| Repair idempotent | ✅ | `test_level1_tag_repair_is_idempotent`, `test_level1_rename_is_idempotent`, `test_repair_repair_rescan_is_idempotent` |
| Keine unerwarteten Library-Moves | ✅ | `safety_check`, Rename nur in-place; `test_rename_stays_in_same_directory` |
| Keine unerwarteten Deletes | ✅ | nur `DUPLICATE`-Pfad (`--allow-delete --artist`, Backup-vor-Delete) |
| Kein Loudnorm-Re-Encoding | ✅ | repoweit verifiziert; `normalize_loudness()` nur test-only |
| ReplayGain ist der aktuelle Loudness-Weg | ✅ | `replaygain_repairs.py` + Download-Pipeline Schritt 15b (PR #188) |
| `library_health` bleibt read-only | ✅ | `test_library_health_readonly_safety.py` (unverändert grün) |
| Review-State persistent | ✅ | `FindingsRegistry`, atomar |
| Accepted Findings verschwinden aus Open | ✅ | `test_accepted_finding_disappears_from_open` |
| Accepted Findings bleiben in JSON | ✅ | `test_accepted_finding_survives_reload` |
| Accepted Findings anzeigbar | ✅ | `--accepted` / `--show` / `get_accepted_findings` |
| Accepted Findings reaktivierbar | ✅ | `--unaccept` / `unaccept_finding` |
| Findings unabhängig voneinander | ✅ | `test_two_findings_same_file_handled_independently` |
| Review JSON validiert | ✅ | `FindingsRegistryError` (bestehend) |
| Health → Repair Integration Tests | ✅ | `test_repair_integration.py` (7) |
| Review Tests | ✅ | §34-Tabelle unten |
| ReplayGain Tests | ✅ | `test_library_repair_replaygain_repairs.py`, `test_loudness_replaygain.py` |
| Safety Tests | ✅ | `test_library_health_readonly_safety.py`, `test_review_repair_readonly_safety.py` |
| Telegram-ready Core API | ✅ | `repair_service.py` + `findings.py`-API |
| Telegram Architektur auditiert | ✅ | Abschnitt 1 + `docs/audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md` |
| Telegram Integration vorbereitet | ✅ | Core-API + Modelle vorhanden/dokumentiert; UI spätere Phase |
| Dokumentation aktuell | ✅ | `LIBRARY_HEALTH.md` §1a, `LIBRARY_REPAIR.md` §5b, Coverage-Matrix, dieses Dokument |
| relevante Teiltests grün | ✅ | 674 passed (thematisch), 0 Regressionen |

---

## 5. §34 Review-Szenarien — Verweistabelle

| # | Szenario | Test |
|---|---|---|
| 1 | Finding wird accepted gespeichert | `test_library_health_findings.py::TestAcceptUnaccept::test_accept_sets_false_positive_with_reason` |
| 2 | Accepted verschwindet aus OPEN | `::test_accepted_finding_disappears_from_open` |
| 3 | Accepted bleibt in JSON | `::test_accepted_finding_survives_reload` |
| 4 | `--accepted` findet es wieder | `::test_get_accepted_findings_lists_and_filters_by_code`; `test_library_health_review_cli.py::TestDirectActions::test_accept_then_accepted_and_show` |
| 5 | `--unaccept` reaktiviert | `::test_unaccept_reactivates_to_open`; CLI `::test_unaccept_reactivates` |
| 6 | zwei Findings derselben Datei unabhängig | `::test_two_findings_same_file_handled_independently`; `test_repair_integration.py::…::test_closure_flow_remaining_findings_accept_and_summary` |
| 7 | neues Finding derselben Datei trotz Acceptance sichtbar | `::test_new_finding_same_file_shows_despite_prior_acceptance` |
| 8 | doppelte Acceptance erzeugt keinen Duplikat-Eintrag | `::test_double_accept_without_unaccept_creates_no_duplicate_row` |
| 9 | korrupte Review-JSON sicher behandelt | `::TestFindingsPersistence::test_corrupt_json_raises_and_does_not_overwrite`, `::test_unexpected_schema_raises` |
| 10 | reparierte Findings nicht fälschlich als aktive Accepted | `::TestReviewSummary::test_accepted_stale_counts_findings_no_longer_detected` |

---

## 6. §43 Final Report

```text
LIBRARY PHASE — FINAL REPORT
════════════════════════════════════════════

HEALTH
    Issue Codes:         53
    AUTO_REPAIR:         29   (SAFE_AUTOMATIC 8 · METADATA_REPROCESSING 10 ·
                               EXTERNAL_METADATA 3 · COVER 5 · LOUDNESS 1 · DUPLICATE 2)
    MANUAL_REVIEW:       22
    UNREPAIRABLE:         2   (LOUDNESS_TAG_MISSING, ALBUM_GENRE_INCONSISTENT)

REPAIR
    Executoren:          8 (apply_level1, apply_level1_rename, apply_cover_repairs,
                            apply_album_cover_unify, apply_external_metadata,
                            apply_level2, apply_replaygain, resolve_duplicates.py-Andock)
    Telegram-ausführbar: nur SAFE_AUTOMATIC (unverändert; identische Grenze wie CLI --apply)
    Post-Repair-Verifikation:
        - Atom-/Audio-Essenz-Verifikation vor atomarem replace (bestehend)
        - Einzeldatei-Recheck je file-scope-SUCCESS -> UNRESOLVED statt SUCCESS (neu, PR E)
        - aggregierter Verification-Scan (bestehend)
        - repair_service Rescan-Gate: RESOLVED nur bei tatsächlich nicht mehr erkannt

REVIEW
    Store:               cache/data/library_health_findings.json  (Config.DATA_DIR, außerhalb Library)
    Stabile Finding-ID:  generate_finding_id() (scope-abhängig, NFC/casefold, kein Pfad-only)
    Status:              🔴 OPEN · 🟢 REPARIERT (RESOLVED) · ⚪ AKZEPTIERT (FALSE_POSITIVE)
                         + RESOLVED_BY_SCAN (technisch)
    CLI:                 interaktiv (Default) + --summary/--accepted/--show/--accept/--unaccept
    Core-API:            accept_finding / unaccept_finding / get_accepted_findings /
                         get_review_summary(-> ReviewSummary)

TELEGRAM
    Vorhanden:           MusicBot Doctor (Scan + SAFE_AUTOMATIC), Library Health Review
                         (Kategorie-Review), Repair MusicBot (Plan/Preview/Execute/Historie/Statistik)
    Vorbereitet (Core-API, UI später): Accepted-Findings-Ansicht, Unaccept

TESTS (diese Phase, gezielt/thematisch)
    neu:                 test_library_repair_disposition_matrix.py (11)
    erweitert:           findings (+19), review_cli (+10), report (Labels),
                         executor (+13: Verify +11 / Idempotenz +2),
                         repair_integration (+2)
    thematische Regression: 674 passed / 0 failed / 0 Regressionen
    Vollsuite (auf ausdrückliche Nutzer-Anweisung in 6 Etappen ausgeführt,
      Speicherdruck-Rechner): 3060 passed / 1 skipped / 2 failed.
      Die 2 Failures (`test_artist_overrides_orphan_cleanup.py` — hartkodierte
      Key-Count-Erwartung 21 vs. `mapping/artist_overrides.json` inzwischen 29)
      reproduzieren identisch auf `main` HEAD `7f76c51` (`git stash`-verifiziert)
      → vorbestehend, unabhängig von dieser Phase, 0 Regressionen.
      Nachtrag: nach Nutzer-Freigabe im Folge-PR behoben (die 8 Keys aus
      PR #194 in die Test-Whitelist aufgenommen) → Vollsuite dann
      3081 passed / 1 skipped / 0 failed.

OFFENE RISIKEN / ZURÜCKGESTELLT
    - Telegram-UI für Accepted/Unaccept: in dieser Phase Core-API-only;
      im direkten Folge-PR #200 (0ba9138) doch umgesetzt, nachdem der
      Nutzer die CLI gegen die echte Registry getestet hatte.
    - LOUDNESS_OFF_TARGET & album-scope-Codes: kein Einzeldatei-Recheck
      (bewusst, im Code + Coverage-Matrix begründet) — durch den
      aggregierten --measure-loudness- bzw. Gruppen-Scan abgedeckt.
```

---

## 7. Verdict

```text
🟢 IMPLEMENTIERT — Teilsuiten grün, 0 Regressionen.
```

Alle §42-Kriterien erfüllt oder bewusst/dokumentiert zurückgestellt (G7).
Die vollständige Testsuite wurde auf **ausdrückliche Nutzer-Anweisung**
(abweichend vom Regelfall Auftrag §31) in 6 speicherschonenden Etappen
ausgeführt: **3060 passed / 1 skipped / 2 failed**, wobei die beiden
Failures nachweislich vorbestehend und phasenunabhängig sind (Abschnitt 6).
Testzahl in `MusicBot_ENGINEERING_BASELINE_v10.md` §2/§3 eingetragen.
