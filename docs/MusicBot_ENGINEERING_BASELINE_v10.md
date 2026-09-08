# MusicBot Engineering Baseline v10

> **Status: DRAFT / IN PROGRESS — NICHT eingefroren.**
>
> Dieses Dokument ist der **laufende Zwischenstand** seit dem v9-Freeze
> (2026-09-07). Es wird pro ARCH-Phase / PR mit *ARCH Status*, *Recent Major
> Changes* und *Testzahlen* aktualisiert (CLAUDE.md §30) und erst zu einem
> ausdrücklichen Freeze-Zeitpunkt (nach 🟢-APPROVED-Freeze-Gate-Audit) zum
> eingefrorenen Referenzpunkt gemacht — dann werden die Platzhalter-
> Abschnitte 4–6 befüllt.
>
> **Bis zum v10-Freeze gilt:**
> - Eingefrorener technischer Referenzpunkt = `docs/MusicBot_ENGINEERING_BASELINE_v9.md`.
> - Aktueller Stand aller offenen/zurückgestellten Findings = `docs/FINDINGS_INDEX.md`.
> - Dieses Dokument dupliziert **keine** Findings — es listet nur die
>   Änderungshistorie seit v9 und die rollende Testzahl.

---

## 1. Metadaten

| Feld | Wert |
|---|---|
| Baseline | v10 (DRAFT) |
| Vorgänger | `docs/MusicBot_ENGINEERING_BASELINE_v9.md` (Freeze 2026-09-07, 2580 passed / 1 skipped / 0 failed) |
| Aktuelle Testzahl | **2920 passed, 1 skipped, 0 failed, 19 subtests passed** (Stand 2026-09-08) |
| Zuwachs seit v9-Freeze | +340 passed |
| Freeze-Status | offen — kein Freeze-Gate-Audit durchgeführt |

---

## 2. ARCH Status seit v9-Freeze

| ARCH-Änderung | PR | Ergebnis |
|---|---|---|
| **Artist Identity Resolution & Mapping Separation** (Phase A–F) — dedizierte `ArtistIdentityResolver`-Komponente als alleinige Identitäts-Auflösung; `ArtistNormalizer.normalize()` wird reine String-Normalisierung; `known`-Flag steuert AutoLearn; Library→`artist_overrides.json`-Persistenz entfernt. F-01…F-06 CLOSED, F-07/F-08 DEFERRED. Vollständiges Protokoll: `docs/audits/ARTIST_IDENTITY_RESOLUTION_MIGRATION_2026-09-08.md`. | #176 | 2920 passed / 1 skipped / 0 Regressionen |

---

## 3. Recent Major Changes (seit v9-Freeze)

| Datum | Änderung | PR | Testzahl danach |
|---|---|---|---|
| 2026-09-08 | Artist-Identity-Resolution-Migration (Phase A–F): `services/metadata/artist_identity_resolver.py` neu; Priorität `artist_override > known_artist > auto_learned_alias > library_identity > musicbrainz_mbid > parser`; `MetadataResult.artist_known`; `EnhancedMetadataProcessor`/`AutoLearnManager`/`DuplicateDetector`/`utils/artist_map.py` umgestellt; toter Alias-Code entfernt. `mapping/`-Dateien inhaltlich unverändert. | #176 | 2920 passed |
| 2026-09-08 | Testinfra: `handlers/test_menu_handler.py::TestMenuHandler.__test__ = False` (pytest-Collection-Sperre, beseitigt 3 Collection-Warnings). | #176 | 2920 passed |

---

## 4. Technical Debt — Snapshot

> Platzhalter — wird beim v10-Freeze als Schnappschuss befüllt (Vergleichswert
> zum v9-Stand, CLAUDE.md §30). **Bis dahin maßgeblich:**
> [`docs/FINDINGS_INDEX.md`](FINDINGS_INDEX.md).
>
> Seit v9 neu zurückgestellt: **F-07** (MusicBrainz-Artist-MBID nicht als
> Identitätssignal, P3), **F-08** (deprecated Artist-Code, P3) — beide in
> `FINDINGS_INDEX.md`.

---

## 5. Security-Baseline

> Platzhalter — wird beim v10-Freeze befüllt. Keine sicherheitsrelevante
> Änderung seit v9 im Rahmen der bisher gelisteten PRs.

---

## 6. Architecture Freeze

> Platzhalter — Freeze-Entscheidung (GO/NO-GO mit Evidenz) ist ein
> ausdrücklicher, eigenständiger Prüfschritt (CLAUDE.md §30) und noch nicht
> erfolgt.

---

## Freeze-Checkliste (beim v10-Freeze abzuarbeiten)

- [ ] Freeze-Gate-Audit → 🟢 APPROVED (alle Kriterien PASS, kein offener P0/P1)
- [ ] Abschnitte 4–6 als Schnappschuss befüllen
- [ ] „Baseline Frozen (JJJJ-MM-TT)"-Footer setzen, DRAFT-Kopf entfernen
- [ ] Referenzen umstellen: `README.md`, `docs/INDEX.md`, `CLAUDE.md` §30
- [ ] `docs/MusicBot_ENGINEERING_BASELINE_v9.md` → `docs/archive/`
