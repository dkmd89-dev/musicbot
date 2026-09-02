# Security-Sweep: Secrets in Logs

**Datum:** 2026-09-02
**Scope:** systematischer Sweep über alle Secret-tragenden Config-Werte
(`BOT_TOKEN`, `GENIUS_ACCESS_TOKEN`, `LASTFM_API_KEY`/`LASTFM_API_SECRET`,
`FANART_API_KEY`, `NAVIDROME_PASS`) — CLAUDE.md Abschnitt 12 (P0: „Keine
Secrets loggen"). Erster systematischer Durchgang dieser Session; bisher
nur ein einzelner, zufällig gefundener Fund (`pylast`-Repr-Leak, PR #86).

## Methodik

Für jedes Secret: (1) alle Verwendungsstellen im Code finden, (2) prüfen,
ob es in eine URL/einen Log-Aufruf/eine Exception-Message gelangen kann,
(3) bei jeder externen HTTP-Integration konkret prüfen, *wie* das Secret
übertragen wird (Header vs. URL-Query-Param vs. POST-Body) — das
entscheidet, ob `requests`/`httpx`-Exceptions es unmaskiert in ihre
`str()`-Repräsentation einbetten können (bekanntes Verhalten: die
Request-**URL** landet regelmäßig in Connection-/Timeout-Fehlermeldungen,
der Request-**Body** i. d. R. nicht).

## Ergebnis je Secret

| Secret | Übertragungsweg | Befund |
|---|---|---|
| `NAVIDROME_PASS` | URL-Query-Param (`u=`/`p=`, Subsonic-API) | **Bereits gefixt** (SEC-001 + Post-Baseline-Triage FINDING-3): `services/clients/navidrome_api.py::_scrub_credentials()` maskiert `u=`/`p=` in jeder Exception-Message, `make_request()` reicht nie das rohe Exception-Objekt weiter (`raise RuntimeError(safe_msg) from None`). Regressionstests: `tests/test_navidrome_api_logging.py` (4 Tests, decken Erfolgsfall + HTTPError + ConnectionError + generische Exception ab). |
| `LASTFM_API_KEY`/`LASTFM_API_SECRET` | **POST-Body** (`pylast`/`httpx`: `client.post(url, data=self.params)`, Key/Secret/Signature als Form-Daten, nicht in der URL) | Kein Fund. Live im `pylast`-Quellcode verifiziert (`_download_response()`): die URL enthält nur `host_subdir` + optional `?username=`, keine Auth-Parameter. `requests`/`httpx`-Exceptions betten typischerweise die URL, nicht den Body, in ihre Meldung ein — der bereits gefixte `pylast.LastFMNetwork.__repr__()`-Leak (PR #86, Objekt-Repräsentation) war der eigentlich relevante Vektor für diese Bibliothek und ist bereits geschlossen. |
| `GENIUS_ACCESS_TOKEN` | Authorization-Header (über die `genius`/`lyricsgenius`-Bibliothek) | Kein Fund. Header-basierte Auth wird von `requests`/`aiohttp`-Exceptions nicht in die Fehlermeldung eingebettet (nur die URL). Der einzige direkte HTTP-Aufruf in `genius_client.py` selbst (`_scrape_genius_lyrics_html()`) trägt nur einen `User-Agent`-Header, kein Secret. |
| `FANART_API_KEY` | wird an `CoverProcessor` durchgereicht | Nicht vertieft geprüft in diesem Sweep (P3, kein akuter Hinweis) — Kandidat für einen Folgeblick, falls `CoverProcessor`s eigene Fanart-Aufrufe URL-Query-Param-basiert sind (analog zum Navidrome-Muster). Nicht Teil dieses Fixes. |
| `BOT_TOKEN` | **URL-Pfad-Segment** (Telegram-Bot-API: `.../bot<TOKEN>/<method>` — kein Header) | **Konkreter Fund, gefixt** (siehe unten). |

## Fund: `run_test_bot.py` — `BOT_TOKEN` unmaskiert in Exception-Message

`run_test_bot.py:65` (vor dem Fix) baute die Telegram-Bot-API-URL mit dem
vollständigen, unmaskierten `Config.BOT_TOKEN` und übergab sie an
`requests.get(...)`. Bei einem Verbindungsfehler (Timeout, DNS-Fehler,
Connection Refused — nicht unrealistisch für dieses reine
Diagnose-Feature) hängt `requests` die vollständige Request-URL inklusive
Token in die Exception-Message ein; der bisherige
`except Exception as _e: print(f"...{_e}")` hätte den kompletten Token
ins Terminal (bzw. eine mitgeschnittene Log-Datei) geschrieben. Exakt
dieselbe Fehlerklasse wie der bereits gefixte Navidrome-Fund (SEC-001 +
FINDING-3), nur mit URL-Pfad-Auth statt URL-Query-Param-Auth.

Repoweit verifiziert: `run_test_bot.py` ist die **einzige** Stelle, die
manuell eine `api.telegram.org/bot<TOKEN>/...`-URL baut — die
Produktions-`bot.py` nutzt ausschließlich die `.token()`-Builder-Methode
der `python-telegram-bot`-Bibliothek (deren interne HTTP-Fehlerbehandlung
außerhalb dieses Scopes liegt).

### Fix

- `_mask_token_in_message(message, token, masked)` als reine, von
  `Config`/Modulzustand entkoppelte Funktion ergänzt — ersetzt jedes
  Vorkommen des Tokens in einer Nachricht durch den bereits maskierten
  Wert (`Config.mask_sensitive()`, dieselbe bereits etablierte
  Maskierungsfunktion wie in `config.py`s eigenen Startup-Prints).
- **Nebenfund, mitbehoben:** `run_test_bot.py` hatte **keinen**
  `if __name__ == "__main__":`-Guard — der komplette Skriptkörper lief
  unconditional beim Import. Dadurch war die Datei nicht sicher
  importierbar/testbar (ein Import hätte `argparse.parse_args()`, einen
  echten `.env`-Load, `sys.modules`-Manipulation und einen echten
  Netzwerk-Request ausgelöst). Guard ergänzt, analog zum bereits
  etablierten Muster in `scripts/reprocess_artist_metadata.py`
  (`tests/test_reprocess_artist_metadata.py` lädt jenes Skript exakt so).
  `_mask_token_in_message()` bewusst außerhalb des Guards am Modulkopf
  platziert — sicher importierbar, ohne die Ausführungslogik anzustoßen.
  Reine Strukturänderung, kein Verhaltensunterschied beim direkten
  Skriptaufruf (`python3 run_test_bot.py ...`).

### Pre-Fix-Diskriminierung

`git stash` auf `run_test_bot.py`: der Testlauf gegen den ungefixten Code
brachte nicht nur einen Testfehlschlag, sondern einen
**pytest-`INTERNALERROR`** — `argparse.parse_args()` versuchte, pytests
eigene Kommandozeilen-Argumente zu parsen, scheiterte und löste
`SystemExit(2)` aus, das pytest selbst zum Absturz brachte. Eindrücklicher
Beleg dafür, dass die Datei vorher grundsätzlich nicht sicher
importierbar war — nicht nur, dass der Masking-Fix fehlte.

## Tests

- Neu: `tests/test_run_test_bot_token_masking.py` (5 Tests: Import ohne
  Seiteneffekte, Token-Ersetzung, unveränderte Nachricht ohne
  Token-Vorkommen, Leer-Token-Randfall, realistisches
  `ConnectTimeout`-Nachrichtenformat).
- Direkte Regression: `tests/test_config_test_isolation.py`,
  `tests/test_title_cleaner_german_compound_video_suffix.py`,
  `tests/test_artist_config_mapping_dir_isolation.py`,
  `tests/test_navidrome_api_logging.py`,
  `tests/test_config_import_side_effects.py` — alle grün (diese Dateien
  erwähnen `run_test_bot.py` nur dokumentarisch bzw. testen verwandte
  Isolationsmechanismen, keine echten Imports).
- Vollständige Suite: siehe PR-Beschreibung (Ergebnis zum Zeitpunkt des
  Commits).

## Nicht vertieft (bewusst außerhalb dieses Sweeps)

- `FANART_API_KEY`-Übertragungsweg in `CoverProcessor` — kein akuter
  Hinweis, aber auch nicht aktiv verifiziert wie die anderen fünf
  Secrets. Kandidat für einen gezielten Folge-Blick.
- Allgemeine `except Exception`-Blöcke ohne Secret-Bezug — nicht Teil
  dieses Scopes (CLAUDE.md Abschnitt 25: nicht jeden Unterschied zu einem
  Finding machen).
