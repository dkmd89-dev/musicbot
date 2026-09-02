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
| — (`mugge_statistik_handler.py`) | CLOSED (won't-fix, 2026-09-02) | — | Kein `error_handler` integriert. Nutzer-Entscheidung final bestätigt: jeder `except`-Block editiert die separat gesendete Zwischennachricht, nicht die `callback_query`-Nachricht — mechanisches Verdrahten würde die falsche Nachricht treffen. Bestehende lokale `except`-Blöcke sind bereits funktional äquivalent. Dokumentiert direkt im Code (Klassen-Docstring). | `handlers/mugge_statistik_handler.py` (Docstring); Historie: `docs/archive/MusicBot_ENGINEERING_BASELINE_v6.md` §8 |
| — (`YoutubeDownloader.download_audio`) | CLOSED (2026-09-02) | war P3 | `AttributeError` bei `download_result=None` behoben — sauberer Guard liefert jetzt `{"success": False, "error": ...}` statt zu crashen. Pre-Fix-Diskriminierung via `git stash` bestätigt. | `tests/test_youtube_downloader_telegram_decoupling.py::test_empty_result_returns_clean_error_dict` |
| — (Downloader-Fehlertaxonomie) | OPEN | — | `FormatNotAvailableError`/`PermissionError` korrekt als „nicht retry-würdig" verdrahtet, aber aktuell von keiner Stelle geworfen (Infrastruktur bereit, ungenutzt). | `docs/MusicBot_ENGINEERING_BASELINE_v8.md` §6/8 |
| — (`FileProcessingError`) | OPEN | — | Nicht in die Non-Retryable-Menge aufgenommen — wird nirgends geworfen, keine Klassifikation ohne Beleg. | `docs/MusicBot_ENGINEERING_BASELINE_v8.md` §6/8 |
| — (14 Delegate-Methoden, `EnhancedMetadataProcessor`) | CLOSED (2026-09-02) | war P3 | Alle 14 entfernt — 0 externe Aufrufer UND 0 interne Selbstaufrufe repoweit erneut verifiziert (Beweispflicht vor Löschung, CLAUDE.md Abschnitt 20), 0 Testreferenzen. `_fetch_album_info_from_musicbrainz()` (ebenfalls 0 Aufrufer, aber außerhalb des benannten Blocks) bewusst nicht mitentfernt — separater, nicht angefragter Fund. | `services/metadata/enhanced_metadata_processor.py` |
| MIG-04 | CLOSED (nicht umgesetzt, 2026-09-02) | war P3 | Vertiefte Prüfung statt Verschiebung: `CoverProcessor` orchestriert 5 externe Quellen + eigenes Scoring/Caching — kein „reiner Client" laut CLAUDE.md-Definition, an seinem jetzigen Ort (`services/metadata/`) korrekt einsortiert; Verschiebung nach `services/clients/` wäre Fehlklassifizierung. `DownloadExecutor` würde strukturell passen (ein externes Tool), aber Verschiebung hätte 0 Funktionsnutzen bei ~6 Importpfad-Änderungen — nicht gerechtfertigt. | `docs/FINDINGS_INDEX.md` (diese Zeile); ursprünglich `docs/audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md` |
| MIG-06 | CLOSED (2026-09-02) | war P3 | Automatisierter Layer-Boundary-Test ergänzt (AST-basiert, `services/` darf nie `handlers`/`klassen`/`telegram` importieren) — Grenze war bereits sauber, ist jetzt dauerhaft gegen Regression abgesichert. | `tests/test_services_layer_boundary.py` |
| DUP-05 | CLOSED (2026-09-02) | war P1 (akzeptiert) | Check-then-Register-Race ohne Lock — behoben durch In-Memory-„in Bearbeitung"-Markierung (URL-/Content-Hash, TTL-basiert selbstheilend). Kein reiner UX-Feinschliff: schließt eine reale Race-Bedingung. | `docs/audits/DUP05_IN_FLIGHT_RACE_FIX_2026-09-02.md` |
| — (`DuplicateCache.duplicate_count`) | OPEN | P3 | Asymmetrie: `check_url_duplicate()` erhöht ohne `_save_caches()`, `check_content_duplicate()` erhöht gar nicht. Kein Korrektheitsrisiko — Wert wird nirgends gelesen/angezeigt (verifiziert). | `docs/audits/P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md` |
| — (`DuplicateCache._normalize_url_for_cache`) | OPEN | P3 | `/embed/<id>`, `/live/<id>` nicht auf dieselbe Video-ID normalisiert wie `/watch?v=<id>` (analog zum P0-F-Shorts-Fix). Keine Evidenz für reale Nutzung als manuell geteilter Link. | `docs/audits/P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md` |
| — (`ArtistConfig`/`ArtistNormalizer`-Verdrahtung, `DuplicateDetector`) | CLOSED (P1, PR #102) | — | War offen seit P0-E — durch P1 vollständig behoben, `DuplicateDetector` nutzt jetzt denselben `ArtistProcessor`-Pfad wie die Metadaten-Pipeline. Zeile bewusst als Beispiel für den CLOSED-Zustand stehen gelassen (siehe Geltungsbereich oben). | `docs/audits/P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md` |
| — (`run_test_bot.py` BOT_TOKEN-Leak) | CLOSED (2026-09-02) | P0 | Security-Sweep (erster systematischer Secrets-in-Logs-Durchgang): `BOT_TOKEN` (URL-Pfad-Auth der Telegram-Bot-API) landete bei Verbindungsfehlern unmaskiert in der Exception-Message. Gefixt (Maskierung + `__main__`-Guard, der die Datei erst sicher testbar machte). Alle anderen geprüften Secrets (`NAVIDROME_PASS` bereits gefixt, `LASTFM_API_KEY`/`_SECRET`/`GENIUS_ACCESS_TOKEN` strukturell nicht betroffen — Header/POST-Body statt URL) unauffällig. | `docs/audits/SECURITY_SECRETS_IN_LOGS_SWEEP_2026-09-02.md` |
| YTPARSE-01 | CLOSED (2026-09-02) | P0 | Live-Fund beim End-to-End-Testdownload über den echten Test-Bot: `_parse_artist_and_title()` in `utils/youtube_parser.py` splittete den generischen Bindestrich-Trenner (`\s*[-–—]\s*`, kein Whitespace zwingend) am erstbesten BAREN Bindestrich — bei „Miksu/Macloud, makko, t-low - Ich will" traf das den Bindestrich in „t-low" selbst statt des echten Artist/Titel-Trenners: Artist-Liste enthielt fälschlich isoliertes „t", Titel begann mit Leak „low - Ich will". Analog zum bereits bestehenden, aber hier fehlenden Schutz in `artist_processor.py::clean_artist_before_normalization()`. Gefixt: Regex verlangt jetzt `\s+` (zwingend Leerzeichen) auf beiden Seiten. Pre-Fix-Diskriminierung via `git stash` bestätigt (Test schlägt ungefixt fehl). | `tests/test_youtube_parser.py::TestParseYoutubeTitleDocumentedExamples::test_t_low_comma_separated_no_x_keyword_is_not_split_on_bare_hyphen` |
| — (`mapping/artist_overrides.json`, Duo „Miksu & Macloud") | CLOSED (2026-09-02) | P1 | Selber Live-Testdownload: der Schrägstrich in „Miksu/Macloud" wird überall bewusst als Kollaborations-Trenner behandelt (korrektes Verhalten für andere Titel), zerlegte hier aber den echten Duo-Namen — YT-Parser lieferte `parsed_artist="Miksu"` (nur `all_artists[0]`), das gewann laut Prioritätskette gegen den korrekten, unzerlegten `raw_artist`/`channel_name` „Miksu / Macloud" → finaler Artist „MIKSU" (Macloud komplett verloren). Bereits vorhandene Overrides deckten nur die „&"-Schreibweisen ab. Fix: 4 neue Override-Einträge (bare „miksu", „miksu / macloud", „miksu/macloud", „miksu x macloud" → „Miksu & Macloud"), Nutzer-Entscheidung für Mapping-Override statt Code-Änderung an der generischen Slash-Behandlung. Verifiziert mit echten Produktionsklassen (`ArtistProcessor.determine_best_artist()`), Pre-Fix-Diskriminierung via `git stash` bestätigt. | `tests/test_artist_overrides_miksu_macloud_duo.py` |
| — (`filenamefixer.py::extract_main_artist()`, Library-Ordner „Miksu & Macloud") | CLOSED (2026-09-02) | P1 | Nutzer-Fund nach obigem Mapping-Fix: der Tag zeigte korrekt „Miksu & Macloud", der Library-ORDNER blieb aber „Miksu" — `extract_main_artist()` splittet jeden Artist-String an „,"/„&"/„feat."/„ft."/„ x " fürs Ordner-Grouping (sinnvoll für echte Ad-hoc-Kollaborationen), zerlegte aber den bereits als atomaren Duo-Namen normalisierten Override-Wert zurück in „Miksu". Nebenwirkung: `check_library_duplicate()` (`services/duplicate/detector.py`) fand den vorhandenen Ordner dadurch auch nicht mehr (dessen `ArtistNormalizer` liefert seit dem Override-Fix ebenfalls „Miksu & Macloud"). Fix: Artist-Strings, die exakt einem Zielwert aus `artist_overrides.json` entsprechen, gelten als bereits kanonisch/atomar und werden nicht mehr gesplittet — Ad-hoc-Kollaborationen ohne eigenen Override-Eintrag unverändert. Pre-Fix-Diskriminierung via `git stash` bestätigt. | `tests/test_filenamefixer.py::TestBuildFinalPathKnownGroupNames` |
| — (Metadata-Cache-Hit + Duplicate-Cache leer) | OPEN | P2 | Beim gezielten Testen der Library-Fallback-Ebene entdeckt (nicht der ursprünglich gemeldete Fund): wird `url_duplicates.json`/`content_duplicates.json` für einen Track geleert, dessen Library-Datei aber noch existiert UND dessen `metadata_cache`-Eintrag noch vorhanden ist, lädt die Pipeline die Audiodatei komplett neu von YouTube (Netzwerk-Verschwendung), der Metadata-Cache-Hit in `process_single_track()` (`enhanced_metadata_processor.py:283-287`) gibt aber sofort das alte `MetadataResult` zurück — `move_to_library()` (Schritt 16) wird dadurch nie aufgerufen. Die frisch heruntergeladene Datei bleibt unverschoben/verwaist im `DOWNLOAD_DIR` liegen, UND der Nutzer bekommt trotzdem „✅ Download erfolgreich!" mit dem (alten) Library-Pfad gemeldet — irreführend, da nichts Neues geschrieben wurde. Noch nicht untersucht: ob ein bestehender Cleanup (siehe INV `download_executor.py`-Zeile oben, „24h-Start-Sweep") solche verwaisten Dateien erfasst. Zurückgestellt, da eigenständiger, komplexerer Fund außerhalb des ursprünglich angefragten Scopes. | Live-Testdownload 2026-09-02, `/tmp/musicbot_test/downloads/Miksu⧸Macloud x makko - Nachts wach (Official Video).m4a` |

---

## Format einer Zeile

- **ID**: formale ID falls vorhanden (INV-xx, AE-xx, DUP-xx, DL-xx, MIG-xx, …), sonst „—" mit dem betroffenen Modul/der Methode in Klammern als informeller Bezug.
- **Status**: `OPEN`, `OPEN (DEFER)` (bewusst zurückgestellt, aktiv re-evaluiert), `OPEN (akzeptiert)` (dauerhaft akzeptiertes Risiko, keine erneute Prüfung geplant), `CLOSED (…)` mit Schließungs-Referenz.
- **Prio**: P0–P3 nach CLAUDE.md Abschnitt 23, „—" wenn keine formale Priorität vergeben wurde.
- **Kurzfassung**: ein bis zwei Sätze, genug um die Tragweite einzuschätzen, nicht die volle Begründung.
- **Quelle**: das Dokument mit der vollständigen Analyse/Begründung.
