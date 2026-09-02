# DUP-05: Check-then-Register-Race ohne Lock — Fix

**Datum:** 2026-09-02
**Ursprung:** `docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md`,
Abschnitt „DUP-05 — P1 — Check-then-Register-Race ohne Lock (parallele
Downloads)" — seit dem ursprünglichen Fund (Phase 0, vor Baseline v6) als
bewusst akzeptiertes Risiko zurückgestellt, zuletzt in
`docs/MusicBot_ENGINEERING_BASELINE_v8.md` §6/8 bestätigt.

## Ursprünglicher Befund

Zwischen einem „kein Duplikat"-Ergebnis von `DuplicateDetector.
check_for_duplicates()` und der tatsächlichen Registrierung via
`register_download()` liegt die komplette Download+Verarbeitungsdauer
(Sekunden bis Minuten). In dieser Zeit konnte ein zweiter, paralleler
Request (begrenzt durch `_download_semaphore`, Default 3) für denselben
Content ebenfalls „kein Duplikat" sehen und einen redundanten Download
starten. Auswirkung laut ursprünglichem Audit: Ressourcenverschwendung
(doppelter Download), keine Korruption — die bereits vorhandene
`renamed_due_to_conflict`-Logik fängt das Dateikonflikt-Resultat sauber
ab. Ursprünglich als P1 eingestuft, aber wie ein akzeptiertes Risiko
behandelt (keine Lock-Analyse als Teil des „kleinsten sinnvollen Fixes"
der damaligen Phase).

## Umgesetzter Fix

Minimal-invasiv, exakt der im ursprünglichen Audit vorgeschlagene Ansatz
(„In-Memory-Set aktuell in Bearbeitung befindlicher Content-Hashes in
`DuplicateDetector`, geprüft zusätzlich zum Cache"):

- `DuplicateDetector` hält jetzt `self._in_flight: Dict[str, float]`
  (Hash → Claim-Zeitstempel) für URL-Hashes und Content-Hashes.
- `check_for_duplicates()` prüft nach dem bestehenden persistenten
  URL-/Content-Check zusätzlich, ob der URL-Hash bzw. Content-Hash
  bereits „in Bearbeitung" ist (`reason="in_flight"`), und claimt beide
  Hashes unconditional, sobald kein Duplikat gefunden wurde (unmittelbar
  vor dem finalen `return False, None, "none"`).
- **TTL-basierte Selbstheilung** statt zwingendem `try`/`finally` an der
  Aufrufstelle: ein Claim verfällt nach `DUPLICATE_IN_FLIGHT_TTL_SECONDS`
  (Default 900s/15min, über Config überschreibbar). Das hält den Fix
  bewusst auf `DuplicateDetector` selbst beschränkt — `klassen/
  download_handler.py`s bereits komplexer Kontrollfluss
  (`handle_youtube_links()`) wird nicht angefasst. Ein verwaister Claim
  (Absturz/Exception während des Downloads, ohne dass `register_download()`
  je aufgerufen wird) blockiert dadurch einen erneuten Versuch derselben
  URL/desselben Contents nur befristet, nicht dauerhaft.
- `register_download()` gibt den Claim zusätzlich sofort bei
  tatsächlichem Erfolg frei (reine Hygiene — der permanente Cache-Eintrag
  deckt den Fall ab diesem Zeitpunkt ohnehin bereits ab, ein späterer
  Check würde also auch ohne explizite Freigabe korrekt über die
  `url`/`content`-Ebene erkannt, nicht über `in_flight`).
- Bewusst **nicht** abgedeckt: der `parsed_content`-Fallback-Pfad und der
  Library-Fallback-Pfad — beide sind selbst bereits Fallbacks eines
  Fallbacks, zusätzlicher Nutzen einer In-Flight-Absicherung dort wäre
  marginal gegenüber dem Mehraufwand.

## Verifikation

Live nachvollzogen (nicht nur aus dem Code abgeleitet): zwei
`check_for_duplicates()`-Aufrufe für dieselbe URL kurz hintereinander
(simuliert „paralleler Request, bevor der erste registriert hat") —
der zweite liefert jetzt `is_dup=True, reason="in_flight"` statt
`False`. Nach `register_download()` liefert ein dritter Check korrekt
`reason="url"` (permanente Ebene übernimmt). Ein künstlich abgelaufener
Claim (TTL in die Vergangenheit verschoben) blockiert einen späteren
Check nicht mehr — Selbstheilung bestätigt.

## Pre-Fix-Diskriminierung

`git stash` auf `services/duplicate/detector.py` (Testdatei blieb
bestehen): 5 von 7 neuen Tests schlugen am ungefixten Code nachweislich
fehl (die übrigen 2 sind bewusste Gegenproben, die unabhängig vom Fix
gelten müssen — permanente Duplikat-Erkennung nach Registrierung war
bereits vorher korrekt, ein unabhängiger zweiter Content ist erwartungsgemäß
nie betroffen). Fix wiederhergestellt: alle 7 grün.

## Tests

- Neu: `tests/test_duplicate_detector_in_flight_race.py` (7 Tests:
  URL-Race, Content-Race, Übergang zu permanenter Duplikat-Erkennung nach
  Registrierung, explizite Freigabe durch `register_download()`,
  TTL-Selbstheilung, konfigurierbare TTL, Gegenprobe unabhängiger
  URL/Content).
- Direkte Regression: `tests/test_duplicate_handler.py`,
  `tests/test_duplicate_detector_hash_consistency.py`,
  `tests/test_artist_normalization_duplicate_detector_comparison.py`,
  `tests/test_duplicate_detector_feat_ft_normalization.py`,
  `tests/test_duplicate_detector_live_version_false_positive.py`,
  `tests/test_duplicate_title_quote_normalization.py`,
  `tests/test_download_handler_playlist_duplicate_registration.py`,
  `tests/test_download_utils_playlist_cancellation.py`,
  `tests/test_metadata_processor_happy_path.py` — alle grün.
- Thematisch: `pytest tests/ -q -k duplicate` — 310 passed (303 + 7 neu),
  1 skipped, keine Regression. `mapping/` nachweislich unverändert.
- Vollständige Suite: **1705 passed, 0 failed, 1 skipped, 19 subtests**
  (1698 + 7 neu gegenüber dem Stand nach der Baseline-v8-/Findings-Index-PR),
  keine Regression.

## Ergebnis

DUP-05 ist damit vollständig geschlossen (nicht mehr nur akzeptiertes
Risiko) — siehe `docs/FINDINGS_INDEX.md`.
