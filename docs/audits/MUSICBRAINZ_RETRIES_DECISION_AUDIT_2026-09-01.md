# MUSICBRAINZ_RETRIES — Fachentscheidungs-Audit

Reines Audit-Dokument. Keine Code-, Config- oder Teständerungen wurden
im Rahmen der eigentlichen Audit-Phase vorgenommen — siehe Abschnitt 15.

**Status-Update:** Der Nutzer hat die Empfehlung REMOVE (Abschnitt 12)
freigegeben. Die in Abschnitt 13 beschriebene Folgeimplementierung
(1-Zeilen-Entfernung in `config.py`) wurde daraufhin als separater,
eigenständiger Schritt umgesetzt: `MUSICBRAINZ_RETRIES = 4`
(vormals `config.py:414`) entfernt. Wie in Abschnitt 13 vorhergesagt,
waren keine Testanpassungen nötig; volle Suite grün, siehe
Commit-Historie. Dieses Dokument selbst wurde nachträglich nicht
weiter verändert (bleibt als Entscheidungs-Audit zum Zeitpunkt der
Analyse bestehen).

## 1. Executive Summary

`MUSICBRAINZ_RETRIES = 4` ist in `config.py:414` definiert, wird aber
im gesamten Repository an keiner einzigen Stelle außerhalb dieser
Definitionszeile gelesen, referenziert oder weitergereicht — repoweit
über zwei unabhängige Suchmethoden verifiziert (Abschnitt 4). Für
MusicBrainz-Anfragen existiert **an keiner Ebene** (weder Client-intern
noch Service noch Downloader-/Metadata-Pipeline noch ein generischer
Retry-Wrapper) irgendeine Retry-Logik — jede Exception in
`musicbrainz_client.py` wird beim ersten Auftreten abgefangen, geloggt
und als leeres Ergebnis (`{}`/`None`) zurückgegeben (Abschnitt 5). Der
Wert existiert unverändert seit dem allerersten getrackten Commit
dieses Repositories (Abschnitt 9) und wurde bereits in
`docs/MusicBot_ARCHITECTURE_EVOLUTION.md` (AE-04) als offene, noch zu
treffende Fachentscheidung dokumentiert. Diese Phase löst genau diese
Entscheidung auf.

**RECOMMENDATION: REMOVE** (Details und Begründung: Abschnitt 13).

## 2. Baseline

| Feld | Wert |
|---|---|
| Branch | `main` |
| HEAD | `198e6f0531bdc09d7c18bba1efb2d9e162895331` |
| Working Tree | sauber (`git status --short` leer) |
| Testbaseline | `python3 -m pytest tests/ -q` → **1673 passed, 1 skipped, 0 failed** |

Repository-Zustand während der gesamten Audit-Phase unverändert
(reine Lese-/Analyse-Operationen: `grep`, `find`, `git log`, `Read`).

## 3. Config Definition

**Datei:** `config.py:414`

```python
MUSICBRAINZ_HOSTNAME = "dkmd"
MUSICBRAINZ_TIMEOUT = 30
MUSICBRAINZ_ENABLED = True
MUSICBRAINZ_RETRIES = 4
MUSICBRAINZ_TITLE_WEIGHT = 0.5
MUSICBRAINZ_ARTIST_WEIGHT = 0.5
MUSICBRAINZ_MIN_SIMILARITY = 0.7
```

- **Default-Wert:** `4` (Python-`int`-Literal)
- **Typ:** `int`, Klassenattribut auf `Config` (keine Umgebungsvariable,
  kein `.env`-Bezug — siehe Abschnitt 4)
- **Beschreibung/Kommentar:** **keiner** — im Gegensatz zu
  `MUSICBRAINZ_MIN_ARTIST_SIMILARITY` (4 Zeilen weiter unten), das einen
  ausführlichen, konkreten Erklärkommentar mit Verweis auf
  `musicbrainz_client.py`/einen Test trägt, hat `MUSICBRAINZ_RETRIES`
  keinerlei Dokumentation im Code selbst.
- **Herkunft:** reiner Python-Literal-Default in `config.py`, keine
  Env-Var (`.env` enthält keinen MusicBrainz-Eintrag, es existiert kein
  `.env.example` im Repository).
- **Erwartete Semantik laut Name:** legt nahe, dass MusicBrainz-Anfragen
  bei Fehlschlag bis zu `4`-mal wiederholt werden — semantisch am
  ehesten „maximale Gesamtzahl der Versuche" oder „Anzahl zusätzlicher
  Wiederholungen", ohne dass der Code selbst diese Frage beantwortet
  (siehe Abschnitt 8 — die Semantik ist irrelevant, da der Wert nirgends
  gelesen wird).

## 4. Alle References (repoweit)

Zwei unabhängige, sich gegenseitig bestätigende Suchmethoden:

```bash
find /mnt/128ssd/musicbot -name "*.py" -not -path "*/__pycache__/*" \
  -not -path "*/.git/*" -print0 | xargs -0 grep -ln "MUSICBRAINZ_RETRIES"
# → /mnt/128ssd/musicbot/config.py   (einziger Treffer)

grep -rni "musicbrainz_retries" .   # case-insensitiv, alle Dateitypen
# → ausschließlich Treffer in docs/ (Audit-/Architekturdokumente,
#   allesamt bereits bekannte Findings referenzierend, keine neuen
#   Fundstellen)
```

| Fundstelle | Symbol | Zweck | Datenfluss | Runtime-relevant? |
|---|---|---|---|---|
| `config.py:414` | `Config.MUSICBRAINZ_RETRIES` | Definition | Quelle (Sackgasse) | **Nein** — nirgends gelesen |
| `docs/MusicBot_ARCHITECTURE_EVOLUTION.md:310,315,350,439,454,589` | Dokumentation | AE-04-Finding, bereits als offene Fachentscheidung dokumentiert | n/a | Nein (Doku) |
| `docs/archive/MusicBot_PHASE5_PERFORMANCE_BASELINE.md:217` | Dokumentation | Performance-Vergleichstabelle, bestätigt „ungenutzt" | n/a | Nein (Doku) |
| `docs/audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md:38,299,592,761` | Dokumentation | eigenes, früheres Audit dieser Session, bestätigt „CONFIRMED DEAD" | n/a | Nein (Doku) |
| `docs/audits/TECHNICAL_DEBT_CLEANUP_2026-09-01.md:108,129` | Dokumentation | listet als offenes, zurückgestelltes Finding | n/a | Nein (Doku) |
| `docs/audits/DL_RETRY_CLASSIFICATION_2026-09-01.md:275` | Dokumentation | „nicht angefasst" (Out-of-Scope-Vermerk) | n/a | Nein (Doku) |
| `docs/audits/ENHANCED_METADATA_PROCESSOR_PROCESS_SINGLE_TRACK_2026-09-01.md:477` | Dokumentation | Out-of-Scope-Vermerk | n/a | Nein (Doku) |
| `docs/audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md:285` | Dokumentation | Out-of-Scope-Vermerk | n/a | Nein (Doku) |

Keine Umgebungsvariable, kein Alias (`MB_RETRIES` o. Ä.), kein
`.env`/`.env.example`-Eintrag, kein `os.getenv`/`os.environ`-Zugriff im
MusicBrainz-Kontext gefunden (gezielt geprüft).

**Fazit Abschnitt 4:** Jede einzelne Referenz außerhalb von `config.py`
selbst ist reine Dokumentation vorheriger Audits dieser Session — keine
davon ist Runtime-Code.

## 5. Tatsächlicher MusicBrainz Runtime-Pfad

### 5.1 Client-Erzeugung

Zwei unabhängige Lazy-Init-Stellen (separate Instanzen, kein geteilter
Singleton):

- `services/metadata/enhanced_metadata_processor.py:1148` — in
  `_determine_genre_with_stats()`: `if self._mb_client is None: ...
  self._mb_client = MusicBrainzClient()`
- `services/metadata/album_processor.py:142` — in
  `fetch_album_from_musicbrainz()`: `if self._mb_client is None: ...
  self._mb_client = MusicBrainzClient()`

`MusicBrainzClient.__init__()` (`services/clients/musicbrainz_client.py:102`)
setzt lediglich `musicbrainzngs.set_useragent(...)` und lädt den
`ArtistNormalizer` — **keine** Retry-relevante Initialisierung.

### 5.2 Wo wird eine Anfrage ausgelöst?

Genau zwei Aufrufer von `MusicBrainzClient.fetch_metadata()`:

- `services/metadata/genre_processor.py:604` (Genre-Bestimmung)
- `services/metadata/album_processor.py:145` (Album/Jahr-Bestimmung)

### 5.3 Methoden mit tatsächlichen externen Requests

| Methode | Externer Aufruf |
|---|---|
| `cached_musicbrainz_search()` (Modulfunktion, Zeile 50) | `musicbrainzngs.search_recordings`/`search_releases` (via `asyncio.to_thread`) |
| `_fetch_release_group_id()` (Zeile 121) | `musicbrainzngs.get_release_by_id` |
| `_extract_recordings_from_releases()` (Zeile 291) | `musicbrainzngs.get_release_by_id` (bis zu 3× pro Aufruf, Fallback-Pfad, s. u.) |
| `_build_metadata()` (Zeile 388) | `musicbrainzngs.get_recording_by_id` |

### 5.4 Mögliche Exceptions & tatsächliche Behandlung

| Ort | Fängt | Verhalten |
|---|---|---|
| `cached_musicbrainz_search()` | `musicbrainzngs.NetworkError`, dann generisch `Exception` | geloggt, `return {}` — **kein Retry, ein einziger Versuch** |
| `fetch_metadata()` (äußerer Rahmen, plus `async_timeout.timeout(Config.MUSICBRAINZ_TIMEOUT)`) | `Exception` | geloggt, `return {}` |
| `_fetch_release_group_id()` | `Exception` | geloggt, `return None` |
| `_extract_recordings_from_releases()` | `Exception` (pro Release in der Schleife) | geloggt, `continue` (überspringt nur DIESEN Release, kein erneuter Versuch desselben) |
| `_build_metadata()` | `Exception` (um `get_recording_by_id`) | geloggt, `recording_detail = {}` (Degradation, kein Retry) |

**Keine einzige dieser Stellen enthält eine Retry-Schleife, einen
Decorator, einen Backoff-Mechanismus oder einen zweiten Versuch
desselben Requests.** Jeder Fehlerpfad führt zu einer sofortigen,
einmaligen Rückgabe eines leeren/degradierten Ergebnisses.

### 5.5 Gibt es bereits Retry-Logik? (Frage 5/6 der Aufgabenstellung)

**Nein.** Damit entfallen die Unterfragen „wie viele Versuche/welcher
Backoff/welche Fehler werden wiederholt" — es gibt keine Instanz davon
zu beschreiben.

### 5.6 Wird `MUSICBRAINZ_RETRIES` tatsächlich gelesen?

**Nein** (Abschnitt 4). Damit entfällt auch Frage 8 („beeinflusst der
Wert die Anzahl der Requests, oder wird er nur gespeichert?") — er wird
weder gelesen noch gespeichert noch weitergereicht.

### 5.7 Welche andere Konfiguration steuert das tatsächliche Verhalten?

- `Config.MUSICBRAINZ_TIMEOUT` (`= 30`, Sekunden) — steuert einen
  **Timeout** (`async_timeout.timeout(...)` um den gesamten
  `fetch_metadata()`-Aufruf), keine Retry-Anzahl. Aktiv gelesen
  (`musicbrainz_client.py:230`).
- `_musicbrainz_result_cache = TTLCache(maxsize=200, ttl=3600)`
  (Modul-Konstante, kein Config-Wert) — vermeidet wiederholte
  identische Anfragen innerhalb von 3600s, ist aber ein Cache, kein
  Retry-Mechanismus.
- Kein weiterer Wert steuert die Anzahl der Versuche — es gibt schlicht
  immer genau einen Versuch pro Teilanfrage.

### 5.8 Mehrere Retry-Ebenen?

Geprüft und verneint für alle genannten Ebenen:

- **Client-intern** (`musicbrainz_client.py`): kein Retry (s. o.).
- **Service-Ebene** (`genre_processor.py`/`album_processor.py`): beide
  Aufrufstellen sind einfache `await ...fetch_metadata(...)`-Aufrufe
  ohne umgebende Schleife.
- **Downloader-/Metadata-Pipeline**
  (`enhanced_metadata_processor.py::process_single_track()`,
  charakterisiert in
  `docs/audits/ENHANCED_METADATA_PROCESSOR_PROCESS_SINGLE_TRACK_2026-09-01.md`):
  ein MusicBrainz-Fehlschlag führt zu einem degradierten, aber
  weiterhin `success=True`-Ergebnis (optionaler Service, siehe
  `docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md`,
  Abschnitt 29.3: „Metadata-Failure (optionaler Service) → Wird
  abgefangen, Track läuft mit degradierten Metadaten normal weiter").
  Der äußere Download-Retry (`enhanced_download_with_retry()`,
  `docs/audits/DL_RETRY_CLASSIFICATION_2026-09-01.md`) wird durch
  einen MusicBrainz-Fehlschlag **nicht** ausgelöst — es entsteht keine
  Exception, die dorthin propagiert.
- **Generischer Retry-Wrapper:** repoweit gesucht (`retry`-Dateien,
  `@retry`-Decorators, `class Retry`) — keiner existiert, der
  MusicBrainz betreffen könnte.

### 5.9 Kontrollfluss-Diagramm

```
Config.MUSICBRAINZ_RETRIES = 4   (config.py:414)
        │
        │   ⛔ NIRGENDS GELESEN — Sackgasse, kein Consumer
        ▼
   (kein Datenfluss)


Tatsächlicher Anfrage-Pfad (unabhängig von MUSICBRAINZ_RETRIES):

genre_processor.py / album_processor.py
        │  await mb_client.fetch_metadata(title, artist)
        ▼
MusicBrainzClient.fetch_metadata()
        │  async_timeout.timeout(Config.MUSICBRAINZ_TIMEOUT)   ← EINGRIFFSPUNKT (Timeout, nicht Retry)
        ▼
cached_musicbrainz_search() → musicbrainzngs.search_recordings/-releases
        │
        ├── Erfolg → Ergebnis verarbeiten (Matching, _build_metadata)
        │
        └── Exception (NetworkError | beliebig)
                │
                ▼
        loggen, return {} / None      ← EINZIGER Versuch, KEIN Retry
                │
                ▼
        Aufrufer (genre_processor/album_processor) erhält leeres
        Ergebnis, degradiert graceful (kein Genre/Album aus MB),
        Track-Verarbeitung läuft normal weiter
```

## 6. Alternative Retry-Steuerungen (MusicBrainz-Kontext)

| Kandidat | MusicBrainz-relevant? | Aktiv? | Ebene | Vorrang vs. `MUSICBRAINZ_RETRIES` | Gleichzeitig wirksam? |
|---|---|---|---|---|---|
| `Config.MUSICBRAINZ_TIMEOUT` | Ja (Timeout, nicht Retry) | Ja | Client | n/a (andere Kategorie) | n/a |
| `_musicbrainz_result_cache` (TTLCache) | Ja (Cache, nicht Retry) | Ja | Client-Modul | n/a | n/a |
| `musicbrainzngs`-Bibliothek eigenes Retry | Geprüft: Bibliothek exponiert nur `set_rate_limit`/`do_rate_limit` (Rate-Limiting), **keinen** Retry-Parameter | n/a | n/a | n/a | n/a |
| `tenacity` (wie bei Genius) | Nein — `musicbrainz_client.py` importiert `tenacity` nicht | Nein | — | — | — |
| `urllib3.Retry` (wie bei Cover-Provider) | Nein — `musicbrainz_client.py` nutzt keine `requests`/`urllib3`-Session | Nein | — | — | — |
| Genereller Repo-weiter Retry-Wrapper | Nein — repoweit gesucht, keiner existiert | — | — | — | — |
| Äußerer Download-Retry (`enhanced_download_with_retry`) | Indirekt „berührt", aber greift laut Vertrag nicht bei optionalen Metadata-Fehlern (Abschnitt 5.8) | Ja (für harte Fehler) | Downloader-Pipeline | Kein Bezug zu `MUSICBRAINZ_RETRIES` | Nein |

**Ergebnis:** Es gibt **keine** konkurrierende oder doppelte
Retry-Steuerung für MusicBrainz — es gibt schlicht **keine
Retry-Steuerung**, weder durch `MUSICBRAINZ_RETRIES` noch durch
irgendeinen Ersatzmechanismus. Fall D (doppelte Steuerung) der
Aufgabenstellung trifft nicht zu.

## 7. Config-vs-Runtime-Abgleich

| Frage | Antwort |
|---|---|
| A) Anzahl zusätzlicher Retries? | Nicht feststellbar — Wert wird nie interpretiert |
| B) Maximale Gesamtzahl der Versuche? | Nicht feststellbar — Wert wird nie interpretiert |
| C) Etwas anderes? | Nicht feststellbar — Wert wird nie interpretiert |

Die Semantik lässt sich **nicht aus dem Code ableiten**, da der Wert
an keiner Stelle konsumiert wird. Jede Interpretation der beabsichtigten
Semantik wäre reine Spekulation aus dem Variablennamen — genau das
verbietet Abschnitt 4 der Aufgabenstellung explizit. Es wird daher
**keine** Aussage über die ursprünglich beabsichtigte Zahlensemantik
getroffen.

## 8. Historische Evidenz

```bash
git log --follow --all -S "MUSICBRAINZ_RETRIES" --oneline -- config.py
# → e6a4910 Agent host session ... - baseline checkpoint
# → f000cc0 Initial commit: MusicBot
```

- Der Wert ist bereits im **allerersten getrackten Commit**
  (`f000cc0`, „Initial commit: MusicBot") vorhanden — es gibt keine
  frühere Version dieses Repositories, gegen die man vergleichen
  könnte. `git blame`/`git log -p` zeigen **keine** Änderung des Werts
  seither (immer `= 4`), **keine** zwischenzeitliche Entfernung und
  keine zwischenzeitliche tatsächliche Verdrahtung.
- `services/clients/musicbrainz_client.py` selbst dokumentiert in
  seinem Docstring mehrere spätere Überarbeitungen („ÄNDERUNGEN v2",
  „ARCH-012 Phase 3B: … wurde entfernt") — der Client wurde also
  mehrfach umgebaut, ohne dass `MUSICBRAINZ_RETRIES` dabei je
  berührt wurde.
- `docs/MusicBot_ARCHITECTURE_EVOLUTION.md` (Abschnitt 12 „External
  Service Architecture") dokumentiert bereits den Vergleich zu den
  anderen drei externen Clients: Genius (3× `tenacity`, exponentiell),
  Cover-Provider (2× `urllib3.Retry`), Last.fm (**kein** Retry, **und
  auch kein Config-Wert dafür** — Last.fm hat nie den Anspruch erhoben,
  Retry zu haben). MusicBrainz ist der **einzige** der vier Clients,
  bei dem ein benannter Config-Wert einen Anspruch suggeriert (Retry),
  den die Implementierung nicht einlöst.
- `docs/MusicBot_ARCHITECTURE_EVOLUTION.md` (Abschnitt 18/19) klassifiziert
  dies bereits explizit als „REQUIRES DECISION" / AE-04 mit dem
  Vermerk „Fachliche, nicht rein technische Entscheidung nötig" —
  diese Phase ist die angeforderte Entscheidung.

**Belegte Schlussfolgerung:** Es gibt keinen Hinweis darauf, dass eine
frühere Retry-Implementierung existierte und „vergessen" entfernt
wurde, während die Config zurückblieb — im Gegenteil, alles deutet
darauf hin, dass der Wert von Anfang an nie mit einer tatsächlichen
Implementierung verbunden war (kein Bibliotheks-Parameter existiert
dafür, kein Retry-Code wurde je gefunden, der ihn je gelesen hätte).
Diese Aussage stützt sich ausschließlich auf die belegte Abwesenheit
von Gegenevidenz — nicht auf eine positive Zusatzquelle.

## 9. Testabdeckung

- **Tests für `MUSICBRAINZ_RETRIES` selbst:** **0** (repoweit per
  `find`+`xargs`+`grep` verifiziert).
- **Tests für tatsächliche Retry-Anzahl bei MusicBrainz:** **0**.
- **Tests für Fehlerklassifikation bei MusicBrainz-Fehlern:** **0**
  (es gibt keine Klassifikation, nur einheitliches
  Catch-all-Verhalten).
- **Tests für Backoff:** **0** (kein Backoff vorhanden).
- **Indirekter, aber aussagekräftiger Beleg:**
  `tests/test_musicbrainz_client.py::TestCachedMusicbrainzSearch::
  test_network_error_is_caught_and_returns_empty_dict_uncached`
  (Zeile 104) mockt `musicbrainzngs.search_recordings` mit **einem
  einzigen** `side_effect=musicbrainzngs.NetworkError("down")` und
  erwartet direkt `result == {}` — kein `call_count`-Assert auf
  mehrere Versuche, keine Retry-Erwartung. Dieser bestehende Test
  charakterisiert bereits implizit das tatsächliche
  Single-Attempt-Verhalten und würde von einer Entfernung der toten
  Config **nicht** berührt.
- **Tests, die durch eine Entfernung angepasst werden müssten:**
  **keine** (0 Tests referenzieren `MUSICBRAINZ_RETRIES`).

## 10. Produktionsauswirkung

### Fall B — tote Konfiguration (zutreffend)

- **Nachweis:** Abschnitt 4 (repoweite Suche, 0 Runtime-Referenzen)
  und Abschnitt 5 (vollständige Runtime-Pfad-Rekonstruktion, keine
  Retry-Logik an irgendeiner Stelle).
- **Warum Entfernen voraussichtlich kein Runtime-Verhalten ändert:**
  Da der Wert an keiner Stelle gelesen wird, kann seine Entfernung per
  Definition keinen Codepfad beeinflussen, der ihn liest — es gibt
  keinen solchen Codepfad.
- **Dokumentations-/Deployment-Auswirkungen:** keine gefunden — kein
  `.env.example`, kein Deployment-Skript, keine README-Erwähnung
  referenziert `MUSICBRAINZ_RETRIES` (nur die bereits gelisteten
  internen Audit-Dokumente dieser Session, die eine Entfernung ohnehin
  bereits als möglichen Ausgang vorgesehen hatten).

### Fall C — irreführende Konfiguration (zusätzlich zutreffend)

Der Name `MUSICBRAINZ_RETRIES` und sein numerischer Wert (`4`)
suggerieren einem Leser/Entwickler, der `config.py` durchsieht, dass
MusicBrainz-Anfragen bei Fehlern automatisch bis zu 4× wiederholt
werden — tatsächlich passiert das nie. **Risiko der Fehlkonfiguration:**
gering bis moderat — kein akutes Betriebsrisiko (da niemand den Wert
je ändert, ohne dass es etwas bewirkt), aber ein reales
Vertrauens-/Wartbarkeitsrisiko: ein Entwickler, der bei künftigen
MusicBrainz-Zuverlässigkeitsproblemen den Wert erhöht („mehr Retries
konfigurieren"), würde fälschlich glauben, das Problem behoben zu
haben, während sich nichts ändert.

### Fall A / Fall D — nicht zutreffend

Fall A (aktive Konfiguration) trifft nicht zu (Abschnitt 5.6). Fall D
(doppelte Steuerung) trifft nicht zu (Abschnitt 6 — es gibt keinen
zweiten Mechanismus, mit dem `MUSICBRAINZ_RETRIES` konkurrieren
könnte).

## 11. Entscheidungsmatrix

| Kriterium | Befund | Evidenz |
|---|---|---|
| Config definiert | **Ja** | `config.py:414` |
| Runtime gelesen | **Nein** | Abschnitt 4 (repoweiter `find`+`grep`, 2 unabhängige Methoden) |
| Runtime-relevant | **Nein** | folgt aus obigem |
| tatsächliche Retry-Logik (MusicBrainz) | **Keine vorhanden** | Abschnitt 5 (vollständige Pfad-Rekonstruktion aller 4 Request-Methoden) |
| alternative Retry-Steuerung | **Keine** | Abschnitt 6 |
| doppelte Steuerung | **Nein** (nichts konkurriert) | Abschnitt 6 |
| Tests vorhanden | **Nein** (für die Config); **implizit ja** für Single-Attempt-Verhalten | Abschnitt 9 |
| historische Intention | **Nicht rekonstruierbar** (seit Initial-Commit unverändert, nie verdrahtet) | Abschnitt 8 |
| Produktionsauswirkung (Entfernen) | **Keine** | Abschnitt 10 |

| Option | Bewertung | Begründung |
|---|---|---|
| **KEEP** | Nicht empfohlen | Wert hat keine Runtime-Wirkung; Beibehaltung verlängert nur die irreführende Signalwirkung (Fall C) |
| **REMOVE** | **Empfohlen** | Beseitigt die Diskrepanz zwischen Name/Erwartung und tatsächlichem Verhalten vollständig; 0 Test-, 0 Runtime-Auswirkung (Abschnitt 9/10); konsistent mit bereits erfolgter Entfernung anderer toter Configs im selben Repository (`DOWNLOAD_TIMEOUT`/`YTDL_BASE_OPTIONS`, AE-05, `docs/audits/TECHNICAL_DEBT_CLEANUP_2026-09-01.md`) |
| **REPURPOSE/REWIRE** | Mögliche, aber eigenständige Feature-Entscheidung | Würde bedeuten, MusicBrainz erstmals mit echter Retry-Logik auszustatten (analog Genius/Cover) — das ist kein Cleanup, sondern eine neue Resilience-Investition mit eigenem Design-Bedarf (Backoff-Strategie, welche Exceptions retry-würdig sind, Kosten durch zusätzliche externe Requests). Nicht als Nebeneffekt dieser Audit-Phase zu entscheiden. |
| **DEFER** | Nicht nötig | Evidenz ist vollständig, eindeutig und widerspruchsfrei — es bestehen keine offenen Fragen, die eine weitere Untersuchung rechtfertigen würden |

## 12. Klare Fachentscheidung

**RECOMMENDATION: REMOVE**

Begründung anhand der gesammelten Evidenz:

1. `MUSICBRAINZ_RETRIES` ist **dead configuration** im engeren Sinn:
   nachweislich 0 Runtime-Referenzen im gesamten Repository (Abschnitt 4),
   verifiziert über zwei unabhängige Suchmethoden.
2. Es ist zusätzlich **misleading configuration**: der Name suggeriert
   eine Resilience-Eigenschaft (automatische Wiederholung bei
   MusicBrainz-Fehlern), die es nachweislich nicht gibt (Abschnitt 5/10,
   Fall C).
3. Es gibt **keine duplicated retry control** — das Risiko einer
   versehentlichen doppelten/mehrfachen Wiederholung besteht nicht,
   da überhaupt kein Retry-Pfad existiert (Abschnitt 6).
4. Die historische Evidenz (Abschnitt 8) stützt die Einschätzung, dass
   der Wert nie mit einer Implementierung verbunden war, statt dass
   eine bestehende Verdrahtung später entfernt und die Config vergessen
   wurde — es gibt keinen Beleg für Letzteres.
5. Eine Entfernung hat **keine Produktions-, Deployment- oder
   Testauswirkung** (Abschnitt 9/10) — der sicherste Fall unter allen
   vier Optionen.
6. Der Precedent-Fall im selben Repository (`DOWNLOAD_TIMEOUT`/
   `YTDL_BASE_OPTIONS`, AE-05) wurde bereits gefahrlos entfernt, ohne
   dass ein Nutzen verlorenging.
7. REPURPOSE/REWIRE bliebe als Option jederzeit später möglich, verlangt
   aber eine eigenständige, bewusste Fachentscheidung „wollen wir
   MusicBrainz-Resilience als neue Eigenschaft einführen" — das ist
   keine Cleanup-Frage mehr, sondern eine Feature-Investitionsfrage
   außerhalb des in dieser Phase geforderten Umfangs.

## 13. Folgeimplementierung (NICHT umgesetzt, nur beschrieben)

Nur falls der Nutzer die Empfehlung REMOVE bestätigt:

1. **Was müsste geändert werden:** Zeile `MUSICBRAINZ_RETRIES = 4` aus
   `config.py` entfernen.
2. **Betroffene Dateien:** ausschließlich `config.py` (1 Zeile).
   Optional: die o. g. Audit-/Architekturdokumente könnten mit einem
   „erledigt"-Vermerk aktualisiert werden (kein Pflichtbestandteil der
   eigentlichen Änderung).
3. **Tests, die ergänzt/geändert werden müssten:** keine (Abschnitt 9).
4. **Abzusichernde Regressionen:** keine funktionalen Regressionen zu
   erwarten (Abschnitt 10); optional könnte ein einzeiliger
   Charakterisierungstest ergänzt werden, der `hasattr(Config,
   "MUSICBRAINZ_RETRIES") is False` bestätigt, um ein versehentliches
   Wiedereinführen zu erkennen — nicht zwingend erforderlich.
5. **Zu erhaltende Runtime-Semantik:** keine — es gibt keine
   Runtime-Semantik, die von dieser Config abhängt.
6. **Änderungsgröße:** trivial (1 Zeile Produktionscode, 0 Zeilen
   Tests).

Alternative Folgeimplementierung, falls stattdessen REPURPOSE/REWIRE
gewünscht wird (nur zur Vollständigkeit skizziert, keine Empfehlung):
`musicbrainz_client.py::cached_musicbrainz_search()` müsste eine
Retry-Schleife um `musicbrainzngs.search_recordings`/`search_releases`
erhalten (analog zum bestehenden `tenacity`-Muster in
`genius_client.py::_fetch_with_retry()`), mit `Config.MUSICBRAINZ_RETRIES`
als `stop_after_attempt`-Parameter — deutlich größerer Change
(neue Fehlerklassifikation nötig: welche Exceptions sind
retry-würdig, welche nicht — vergleichbar mit der Design-Tiefe von
`docs/audits/DL_RETRY_CLASSIFICATION_2026-09-01.md`), eigene
Test-Suite nötig, nicht trivial.

**Diese Änderungen wurden nicht durchgeführt.** Keine Datei wurde
verändert, kein Test wurde verändert, kein Commit wurde erstellt, kein
Branch/PR wurde erstellt.

## 14. Out of Scope / bewusst nicht bearbeitet

Wie in der Aufgabenstellung (Abschnitt 12) vorgegeben, nicht
untersucht oder verändert:

- allgemeine Services-Architektur, Layer Boundaries, Client-Architektur
- Async-General-Refactoring
- `process_single_track()` (bereits eigene Phase,
  `docs/audits/ENHANCED_METADATA_PROCESSOR_PROCESS_SINGLE_TRACK_2026-09-01.md`)
- `services/duplicate/cache.py`
- Cancellation-Cleanup
- Downloader-Retry-Klassifikation (bereits eigene Phase,
  `docs/audits/DL_RETRY_CLASSIFICATION_2026-09-01.md`)
- Spotify (bereits entfernt, siehe frühere Phase)
- Telegram-Kopplung (bereits eigene Phase,
  `docs/audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md`)
- andere tote Config-Werte (z. B. `MUSICBRAINZ_ENABLED`,
  `MUSICBRAINZ_HOSTNAME`, `MUSICBRAINZ_CONFIG` — bei der
  Runtime-Pfad-Rekonstruktion beiläufig als ebenfalls ungenutzt
  aufgefallen, aber **nicht** Teil dieses Audits und hier bewusst nicht
  vertieft)
- allgemeine Config-Cleanup-Arbeiten

Diese Nebenbefunde (insbesondere die weiteren ungenutzten
`MUSICBRAINZ_*`-Werte) werden hier ausdrücklich **nicht** bewertet oder
empfohlen — sie lägen außerhalb des exakt auf `MUSICBRAINZ_RETRIES`
begrenzten Auftrags dieser Phase.
