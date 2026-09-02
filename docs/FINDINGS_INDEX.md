# Findings-Index

Lebendes, fortlaufend gepflegtes Register aller aktuell **offenen/
zurückgestellten** Findings — die einzige Stelle, die man befragen muss,
um zu wissen „ist Finding X offen oder geschlossen, und wo steht die
Begründung", ohne durch mehrere Baseline-Dokumente blättern zu müssen.

**Geltungsbereich:** nur offene/zurückgestellte Punkte (bewusste
Design-Entscheidung, siehe Diskussion 2026-09-02 — kein rückwirkendes
Backfill der kompletten Projekthistorie). Ein Fund kommt hierher, sobald
er entdeckt und zurückgestellt wird; er wird hier auf `CLOSED`
umgestellt (nicht gelöscht) und mit Schließungs-Referenz versehen, sobald
er behoben wird — für die volle historische Begründung bleibt die
verlinkte Quelle (Baseline-Abschnitt, Audit-Dokument, PR) maßgeblich,
dieser Index selbst bleibt bewusst kurz.

**Pflegeregel (Definition of Done, CLAUDE.md Abschnitt 22):** jede
Änderung, die einen hier gelisteten Punkt schließt, einen neuen offenen
Punkt erzeugt, oder eine bestehende Priorität/Einschätzung ändert,
aktualisiert die entsprechende Zeile in diesem Dokument im selben PR.
Die Tech-Debt-Tabelle in jeder `MusicBot_ENGINEERING_BASELINE_vN.md`
bleibt davon unberührt ein eingefrorener Schnappschuss zum jeweiligen
Freeze-Zeitpunkt (wird nach dem Freeze nicht mehr editiert) — dieser
Index ist ab sofort die einzige Stelle für den *aktuellen* Stand.

Stand: 2026-09-02 (Baseline v8).

---

| ID | Status | Prio | Kurzfassung | Quelle |
|---|---|---|---|---|
| INV-01 (`duplicate/cache.py`) | OPEN (DEFER) | P2 | Synchrone Filesystem-Persistenz im Event-Loop-Thread; 3 Lösungsoptionen bewertet, „mass conversion to async" bleibt laut Architecture-Evolution-Gate verboten. | `docs/MusicBot_ENGINEERING_BASELINE_v8.md` §6/8; Vollanalyse: `docs/audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md` §22 |
| — (`download_executor.py`) | OPEN (DEFER) | P2 | Verwaiste Teildatei bei Task-Cancellation in `download_single_track()`; kein akutes Risiko, wird vom 24h-Start-Sweep erfasst. | `docs/MusicBot_ENGINEERING_BASELINE_v8.md` §6/8 |
| — (`mugge_statistik_handler.py`) | OPEN | — | Kein `error_handler` integriert — struktureller UX-Konflikt, eigene Design-Entscheidung nötig. | `docs/MusicBot_ENGINEERING_BASELINE_v8.md` §6/8 |
| — (`YoutubeDownloader.download_audio`) | OPEN | P3 | `AttributeError` statt sauberem Fehler-Dict bei `download_result=None`; charakterisiert, aber `enhanced_download_with_retry()` liefert laut eigenem Vertrag nie `None` — kein akutes Risiko. | `docs/MusicBot_ENGINEERING_BASELINE_v8.md` §6/8 |
| — (Downloader-Fehlertaxonomie) | OPEN | — | `FormatNotAvailableError`/`PermissionError` korrekt als „nicht retry-würdig" verdrahtet, aber aktuell von keiner Stelle geworfen (Infrastruktur bereit, ungenutzt). | `docs/MusicBot_ENGINEERING_BASELINE_v8.md` §6/8 |
| — (`FileProcessingError`) | OPEN | — | Nicht in die Non-Retryable-Menge aufgenommen — wird nirgends geworfen, keine Klassifikation ohne Beleg. | `docs/MusicBot_ENGINEERING_BASELINE_v8.md` §6/8 |
| — (14 Delegate-Methoden, `EnhancedMetadataProcessor`) | OPEN | P3 | 0 Aufrufer repoweit, dokumentierte Kompatibilitätsschicht — nicht ohne dedizierten Auftrag entfernt (CLAUDE.md Abschnitt 20). War 15, `_find_known_artist_from_list()` in P0-G entfernt. | `docs/MusicBot_ENGINEERING_BASELINE_v8.md` §6/8; Fund: `docs/audits/ENHANCED_METADATA_PROCESSOR_PROCESS_SINGLE_TRACK_2026-09-01.md` |
| MIG-04 | OPEN | P3 | `CoverProcessor`/`DownloadExecutor` liegen außerhalb `services/clients/` — Konventions-Inkonsistenz, rein strukturell, keine Funktionsänderung. | `docs/audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md` |
| MIG-06 | OPEN | P3 | Keine automatisierten Layer-Boundary-Tests — Grenze aktuell sauber (verifiziert), aber ungeschützt gegen künftige Regression. | `docs/audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md` |
| DUP-05 | OPEN (akzeptiert) | P1 (akzeptiert) | Check-then-Register-Race ohne Lock — bewusst akzeptiertes Risiko. | `docs/MusicBot_ENGINEERING_BASELINE_v8.md` §6/8 |
| — (`DuplicateCache.duplicate_count`) | OPEN | P3 | Asymmetrie: `check_url_duplicate()` erhöht ohne `_save_caches()`, `check_content_duplicate()` erhöht gar nicht. Kein Korrektheitsrisiko — Wert wird nirgends gelesen/angezeigt (verifiziert). | `docs/audits/P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md` |
| — (`DuplicateCache._normalize_url_for_cache`) | OPEN | P3 | `/embed/<id>`, `/live/<id>` nicht auf dieselbe Video-ID normalisiert wie `/watch?v=<id>` (analog zum P0-F-Shorts-Fix). Keine Evidenz für reale Nutzung als manuell geteilter Link. | `docs/audits/P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md` |
| — (`ArtistConfig`/`ArtistNormalizer`-Verdrahtung, `DuplicateDetector`) | CLOSED (P1, PR #102) | — | War offen seit P0-E — durch P1 vollständig behoben, `DuplicateDetector` nutzt jetzt denselben `ArtistProcessor`-Pfad wie die Metadaten-Pipeline. Zeile bewusst als Beispiel für den CLOSED-Zustand stehen gelassen (siehe Geltungsbereich oben). | `docs/audits/P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md` |

---

## Format einer Zeile

- **ID**: formale ID falls vorhanden (INV-xx, AE-xx, DUP-xx, DL-xx, MIG-xx, …), sonst „—" mit dem betroffenen Modul/der Methode in Klammern als informeller Bezug.
- **Status**: `OPEN`, `OPEN (DEFER)` (bewusst zurückgestellt, aktiv re-evaluiert), `OPEN (akzeptiert)` (dauerhaft akzeptiertes Risiko, keine erneute Prüfung geplant), `CLOSED (…)` mit Schließungs-Referenz.
- **Prio**: P0–P3 nach CLAUDE.md Abschnitt 23, „—" wenn keine formale Priorität vergeben wurde.
- **Kurzfassung**: ein bis zwei Sätze, genug um die Tragweite einzuschätzen, nicht die volle Begründung.
- **Quelle**: das Dokument mit der vollständigen Analyse/Begründung.
