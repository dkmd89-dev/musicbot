# POST-SERVICES / PROJECT-WIDE ARCHITECTURE AUDIT

## Status

**Audit abgeschlossen. Kein Code geändert, kein Refactoring, kein
Commit, kein PR.** Entscheidungsgate am Ende, wartet auf Freigabe.

---

## A. Ausgangsstand

- **Branch:** `main`
- **Commit:** `6cdab12` (Merge PR #40 — ARCH-016 Phase 2 vollständig integriert)
- **Working Tree:** sauber bis auf 12 unversionierte, dem Nutzer gehörende
  Löschungen in `import/downloads/*.info.json` sowie eine unversionierte
  Änderung an `mapping/artist_overrides.json` — beide unberührt seit
  Sitzungsbeginn, nicht Teil dieses Audits.
- **Offene PRs:** keine (`gh pr list --state open` → leer).
- **ARCH-010 bis ARCH-016 im aktuellen Stand enthalten:** bestätigt
  (`klassen/download_handler.py` importiert `services/downloader/*`
  gemäß ARCH-010; `services/downloader/download/` gemäß ARCH-011;
  `genre_aliases.yaml` enthält die ARCH-013/014/015/016-Self-Alias-Einträge,
  u. a. `"ndw": "NDW"`).
- **Test-Baseline (selbst ermittelt, nicht aus Dokumentation übernommen):**
  `pytest tests/ -q` → **1114 passed, 15 bekannte Vorbestandsfehler**,
  0 neue Fehlschläge. Identisch zur zuletzt bestätigten Baseline
  (POST-ARCH-016-Audit).

Kein Abweichen vom erwarteten Ausgangsstand — Analyse wie geplant fortgesetzt.

**Wichtiger Hinweis zur Quellenlage:** Es existiert bereits ein sehr
aktueller, vollständiger Services-Audit —
`docs/MusicBot_POST-DUPLICATEENTRY_Services_Architecture_Audit.md`
(Stand desselben Tages wie dieser Audit, nach der letzten
`services/`-relevanten Migration). Dieser Audit deckt `services/`
selbst bereits erschöpfend ab (Dependency-Graph, Boundary-Prüfung,
Verantwortlichkeiten, bekannte Folgepunkte, Priorisierung,
Entscheidungsgate: **kein sofortiger Kandidat**). Gemäß Aufgabenstellung
("zuletzt bestätigte Architekturentscheidungen vor alten
Dokumentationen") wird dieser Stand hier als **Baseline für `services/`
übernommen und nicht redundant neu durchgeführt** — dieser Audit
konzentriert sich auf den ausdrücklich angeforderten Zusatzscope:
**außerhalb** von `services/` (`handlers/`, `klassen/`, `utils/`,
`helfer/`, `mapping/`, `tests/`, Top-Level-Struktur, Dokumentations-
konsistenz). `services/`-Befunde werden nur referenziert und auf
Aktualität geprüft, nicht neu hergeleitet.

---

## B. Rekonstruierte Zielarchitektur

Ausschließlich aus CLAUDE.md §4, ARCH-009/010/011 und dem
POST-DUPLICATEENTRY-Audit abgeleitet — keine neuen Regeln erfunden.

| Bereich | Beschlossene Regel | Aktueller Zustand | Status |
|---|---|---|---|
| `services/` | Fachliche/technische Orchestrierung | wie beschlossen, s. POST-DUPLICATEENTRY-Audit | ✅ |
| `services/clients/` | Reine externe Integrationsadapter, keine Fachlogik, keine Präsentation | `lastfm_client.py`/`musicbrainz_client.py` treffen selbst Genre-Entscheidungen (bekannt, POST-DUPLICATEENTRY 5.2) | ⚠️ (bekannt, nicht neu) |
| `services/downloader/` | Download-Pipeline-Orchestrierung | sauber, ARCH-010/011 bestätigt | ✅ |
| `services/metadata/` | Metadaten-Pipeline, `enhanced_metadata_processor.py` als einzige Facade | sauber, 0 externe Direktimporte der Unterprozessoren | ✅ |
| `services/statistik/` | Fokussierte Klassen hinter `statistik_service.py`-Fassade | sauber, ARCH-003/P-6 | ✅ |
| `utils/` | Wiederverwendbare technische Helfer + lokale Subprocess-/Shell-Wrapper **ohne** externe Netzwerkkommunikation | **`audio_enhancer.py` widerspricht das explizit — echte HTTP-Aufrufe an MusicBrainz/Cover Art Archive** (neuer Befund, G.1) | ❌ |
| `handlers/` | Benutzerinteraktion / Telegram-Präsentation, keine P0-Kernfachlogik | `duplicate_handler.py` enthält die vollständige Duplicate-Detection-Algorithmus- und Cache-Klasse, nicht nur Präsentation (neuer Befund, G.2) | ⚠️ |
| `services → handlers` | verboten | 0 Treffer (bestätigt, POST-DUPLICATEENTRY 3.6) | ✅ |
| `services → klassen` | verboten | 0 Treffer (bestätigt) | ✅ |
| `klassen/download_handler.py → handlers/*` | erlaubt (Orchestrator-Sonderrolle, CLAUDE.md-Architekturdiagramm) | 1 Treffer (`handlers.duplicate_handler`), bereits im POST-DUPLICATEENTRY-Audit als erwartete Rolle bewertet | ✅ (keine neue Bewertung nötig) |
| Downloader → Metadata | Zielrichtung, ARCH-010 bestätigt | eingehalten, 1 bewusste Reverse-Edge (ARCH-005) | ✅ |
| Metadata → Clients | normale Richtung | eingehalten | ✅ |

---

## C. Dependency-Audit

AST-basierter Scan über `services/`, `handlers/`, `klassen/`, `utils/`,
`helfer/`, `mapping/`, `tests/` (Cross-Top-Level-Kanten):

```text
handlers  -> helfer     (3x, markdown_helfer — erwartet, Telegram-Formatierung)
handlers  -> klassen    (1x, rich_menu_handler.py -> download_handler.py — erwartet)
handlers  -> services   (5x — erwartet)
handlers  -> utils      (5x — erwartet)
klassen   -> handlers   (1x, download_handler.py -> duplicate_handler.py — bereits bewertet, s. B)
klassen   -> services   (7x — erwartet, ARCH-010)
klassen   -> utils      (2x — erwartet)
mapping   -> utils      (1x, nur der verwaiste mapping/test_genre_map.py, s. G.3)
services  -> utils      (31x — erwartet, u. a. genre_map.py)
tests     -> *          (Testdateien, erwartet)
```

**services → handlers: 0. services → klassen: 0.** Keine Importzyklen
gefunden (AST-DFS über alle `services/`-Module, wie im POST-DUPLICATEENTRY-
Audit bereits bestätigt — hier zusätzlich repo-weit über alle Top-Level-
Bereiche wiederholt, gleiches Ergebnis: 0 Zyklen).

**Keine neue Reverse-Edge außerhalb der bereits bekannten** (ARCH-005;
`klassen → handlers`, bereits bewertet).

---

## D. Boundary-Audit

### D.1 Telegram-Kopplung außerhalb der Präsentationsschicht

Repo-weiter Scan nach `from telegram`/`import telegram` außerhalb
`handlers/` und `klassen/download_handler.py` (dessen Orchestrator-
Sonderrolle bereits etabliert ist): **nur `helfer/telegram_escaper.py`**
— dessen gesamter Zweck ist Telegram-MarkdownV2-Escaping, ausschließlich
von `handlers/`-Modulen konsumiert. Keine Grenzverletzung — im Gegenteil,
konsistent mit CLAUDE.md §4 ("Telegram-spezifische Formatierung...
gehören ausschließlich in handlers/"), auch wenn das Verzeichnis
`helfer/` (statt z. B. `handlers/formatting/`) benannt ist (s. H.2).

### D.2 Externe API-Aufrufe außerhalb geeigneter Adapter

`utils/audio_enhancer.py` — siehe G.1. Einziger gefundener Fall.

### D.3 Business-Logik in Handlern

`handlers/duplicate_handler.py` — siehe G.2. Einziger substanzieller
Fall.

### D.4 `services/*` selbst

Keine erneute Untersuchung — vollständig durch den POST-DUPLICATEENTRY-
Audit abgedeckt, dessen einziger unveränderter substanzieller Befund
(Genre-Logik in `lastfm_client.py`/`musicbrainz_client.py`, dortiger
Abschnitt 5.2) hier als bekannt referenziert, nicht neu hergeleitet wird.

---

## E. Verantwortlichkeits-Audit

| Datei | Vermischte Rollen | Bewertung |
|---|---|---|
| `handlers/duplicate_handler.py` (834 Zeilen) | Cache-Persistenz (`DuplicateCache`) + P0-Duplicate-Detection-Algorithmus (`EnhancedDuplicateHandler.check_for_duplicates/check_library_duplicate/_normalize_artist_for_comparison/...`) + Telegram-Presentation (`show_statistics_menu`, `execute_clear_cache`) — alle drei Rollen in einer Datei/teilweise einer Klasse | P1, neuer Befund (G.2) |
| `utils/audio_enhancer.py` | technische Bildverarbeitung (PIL/mutagen) + externe API-Kommunikation (MusicBrainz/Cover Art Archive via `requests.Session`) | P1, neuer Befund (G.1) |
| `klassen/download_handler.py` (978 Zeilen) | Orchestrierung + Telegram-I/O + Service-Aufrufe | **keine neue Bewertung** — laut CLAUDE.md §19 bekannter, bewusst nicht automatisch zu zerlegender großer Orchestrator; POST-DUPLICATEENTRY-Audit 3.6 bestätigt dies erneut als erwartete Rolle |
| `handlers/menu/rich_menu_handler.py` (1298 Zeilen), `handlers/menu/rich_menu_system.py` (1957 Zeilen) | Menü-Orchestrierung + Präsentation | **keine neue Bewertung** — beide in CLAUDE.md §19 explizit als bekannte große Klassen benannt, kein neuer Befund |

Keine künstlich neuen P0-Befunde erzeugt — beide neuen Funde (G.1/G.2)
sind konkret belegt (Codezeilen, Importe, tatsächliche Netzwerk-
Aufrufe), keine spekulativen "könnte theoretisch" Aussagen.

---

## F. Bekannte Folgepunkte — Revalidierung

| Punkt | Status | Quelle |
|---|---|---|
| ARCH-005 Reverse-Edge | unverändert, 1 Aufrufstelle | POST-DUPLICATEENTRY 5.1, hier bestätigt |
| Genre-Logik-Duplikation (Clients) | unverändert bestehend, architektonisch wichtigster `services/`-Befund, bewusst als eigener Auftrag zurückgestellt | POST-DUPLICATEENTRY 5.2 |
| Last.fm-Duplikation `cover_processor.py` | unverändert, erfordert echte neue Client-Fähigkeit statt reiner Verschiebung | POST-DUPLICATEENTRY 5.3 |
| DI-Inkonsistenz `album_processor.py` | unverändert, seit Präzisierung nur noch Stilfrage ohne Ressourcenfolgen | POST-DUPLICATEENTRY 5.4 |
| `spotify_downloader.py` direkte HTTP-Aufrufe | unverändert, kein Bypass, kein Kandidat | POST-DUPLICATEENTRY 5.5 |
| tote Imports (`requests`, `subprocess`) | unverändert vorhanden | POST-DUPLICATEENTRY 5.6, hier erneut bestätigt |
| `GenreMapper`-Akronymliste (`EDM`/`R&B`/`UK`/`US`/`DJ`/`MC`) | unverändert unvollständig, wie in ARCH-016 dokumentiert; kein aktueller Bedarf (NDW bereits über Self-Alias gelöst) | ARCH-016 Phase 2, nur revalidiert |
| Genre-Normalisierung ARCH-013–016 | vollständig stabil: 115/115 kanonische Werte idempotent, 57 Spezifitäts-Paare weiterhin korrekt aufgelöst, keine Regression | selbst erneut verifiziert (s. I) |

Keine neue Genre-Optimierung begonnen, wie gefordert.

---

## G. Neue Befunde

### G.1 `utils/audio_enhancer.py` widerspricht CLAUDE.md §4 faktisch — echte externe Netzwerkkommunikation in `utils/`

CLAUDE.md §4 nennt `audio_enhancer.py` explizit als Beispiel für
`utils/`-Module "ohne externe Netzwerkkommunikation". Tatsächlich:

```python
# utils/audio_enhancer.py
import requests
...
self.session = requests.Session()
...
response = self.session.get(url, params=params, timeout=10)       # Zeile 287
img_response = self.session.get(image_url, timeout=15)            # Zeile 296
response = self.session.get(mb_url, params=params, timeout=10)    # Zeile 312 — MusicBrainz
caa_response = self.session.get(caa_url, timeout=10)              # Zeile 321 — Cover Art Archive
```

`AudioEnhancer` wird produktiv von
`services/metadata/enhanced_metadata_processor.py` verwendet (kein
totes Modul). Es handelt sich um echte HTTP-Aufrufe an MusicBrainz und
Cover Art Archive innerhalb eines als "netzwerkfrei" dokumentierten
`utils/`-Moduls — ein direkter Widerspruch zwischen Dokumentation und
Code, UND eine Verletzung der eigenen Schichtregel
("Ein Modul, das externe Netzwerk-/API-Kommunikation durchführt, gehört
nach `services/clients/`"). Zusätzlich potenzielle, hier nicht weiter
untersuchte Überschneidung mit der bereits über `cover_processor.py`
(POST-DUPLICATEENTRY, Dependency-Graph Abschnitt 4) abgedeckten
Cover-Art-Beschaffung aus u. a. Cover Art Archive — ob echte Duplikation
oder unterschiedliche Zwecke vorliegt, wurde nicht abschließend
geklärt (außerhalb des Analyseumfangs dieses Audits).

**Bewertung:** P1 — konkrete Architektur- und Dokumentationsabweichung,
touched den P0-geschützten Bereich Audio/Cover, aber kein akuter Bug
(die Aufrufe funktionieren, nur am falschen Ort).

### G.2 `handlers/duplicate_handler.py` vermischt P0-Duplicate-Detection-Logik mit Telegram-Präsentation

Frühere Audits (ARCH-006/007, POST-ARCH-010/011,
POST-DUPLICATEENTRY) untersuchten ausschließlich die `DuplicateEntry`-
Dataclass und deren Import-Kante — diese wurde bereits erfolgreich nach
`services/downloader/models.py` migriert (PR #23). **Nicht untersucht
wurde bisher, ob die eigentliche Duplicate-Detection-Logik selbst am
richtigen Ort liegt.**

Tatsächlicher Inhalt von `handlers/duplicate_handler.py` (834 Zeilen):

- `DuplicateCache` (Zeilen 28–274): reine Cache-/Persistenzlogik (Laden/
  Speichern von URL-/Content-Hashes, Cleanup) — keine Telegram-Berührung.
- `EnhancedDuplicateHandler` (Zeilen 275–834), darin:
  - **Business-Logik ohne jeden Telegram-Bezug:**
    `check_for_duplicates()`, `check_library_duplicate()`,
    `register_download()`, `_normalize_artist_for_comparison()`,
    `_clean_title_for_comparison()`, `_create_metadata_hash()`,
    `_create_file_hash()`, `get_statistics()`, `cleanup_cache()`,
    `invalidate_entry()` — exakt der in CLAUDE.md §5 beschriebene P0-Flow
    (URL → Normalisierung → URL-Duplikat → Artist/Titel → Parser →
    Library-Fallback).
  - **Telegram-Presentation:** `show_statistics_menu()`,
    `show_clear_cache_confirm()`, `execute_clear_cache()` (alle
    `async`, mit `Update`/`ContextTypes`-Parametern).

Nach CLAUDE.md §4 ("handlers/ → Benutzerinteraktion / Telegram-
Präsentation" vs. "services/ → Fachliche... Orchestrierung") gehört die
P0-Kernlogik der Duplikaterkennung strukturell eher nach `services/`,
nicht nach `handlers/` — dieselbe Kategorie von Befund wie die bereits
bekannte Genre-Logik-Duplikation (5.2 im POST-DUPLICATEENTRY-Audit),
nur in umgekehrter Richtung (Fachlogik in der Präsentationsschicht statt
im Adapter) und in einer anderen P0-Domäne (Duplicate Detection statt
Genre).

**Bewertung:** P1 — strukturell relevant, betrifft eine ausdrücklich
P0-geschützte Domäne (CLAUDE.md §3/§15: "Keine einzelne Ebene als
alleinige Wahrheit betrachten, ohne den bestehenden Codefluss zu
prüfen"), aber wie bei der Genre-Logik zu groß/riskant für einen
unmittelbaren "kleinen nächsten Schritt" — eine Verschiebung würde
aktiven, hochsensiblen Duplicate-Detection-Code berühren und erfordert
laut CLAUDE.md §6 vorherige Characterization-Tests, keine sofortige
Umsetzung.

### G.3 `mapping/test_genre_map.py` — verwaiste, größtenteils fehlschlagende Testdatei außerhalb der Regression

```text
mapping/test_genre_map.py: 8 Tests, 7 failed, 1 passed
```

Diese Datei liegt außerhalb von `tests/` und wird von **keinem** in
diesem Projekt verwendeten Regressionsaufruf (`pytest tests/ -q`, wie
in jeder ARCH-Phase dieser Session verwendet) erfasst — sie ist seit
unbekannter Zeit vollständig unsichtbar für die reguläre Test-Baseline.

Root Cause (nur charakterisiert, nicht behoben): die Datei erwartet von
`GenreMapper.determine_genre()` einen **einfachen String** als
Rückgabewert (`assert genre == "Deutschrap"`), während die aktuelle
API — durchgängig in `services/metadata/genre_processor.py` und allen
aktuellen `tests/test_genre_*.py`-Dateien verifiziert — ein strukturiertes
`GenreResult`/`GenreMapping`-Objekt zurückgibt. Der Datei-Kopfkommentar
(`# yt_music_bot/utils/mapping/test_genre_map.py`) referenziert zudem
eine nicht mehr existierende Projektstruktur — eindeutiges Indiz für
einen nie migrierten Alttest aus einer früheren API-Version, keine
Anzeige eines aktuellen Produktionsfehlers (die Genre-Domäne selbst ist
durch `tests/test_genre_*.py` — 5 Dateien, umfassend in ARCH-012–016
verifiziert — weiterhin nachweislich korrekt und vollständig getestet).

**Bewertung:** P2 — keine Architekturverletzung im engeren Sinne, aber
ein Test-Hygiene-Befund mit Relevanz für CLAUDE.md §7/§8 (Testpyramide,
echte Produktionslogik testen): die Datei suggeriert Testabdeckung, die
faktisch nicht existiert und nicht (mehr) geprüft wird.

### G.4 `handlers/adapters/` — leeres, totes Scaffold-Verzeichnis

`handlers/adapters/` enthält ausschließlich eine leere `__init__.py`
(0 Bytes, Datum September 2025 — älter als die meisten anderen Dateien
im Projekt). Kein Consumer, kein Inhalt. Vermutlich ein nie befüllter
Platzhalter aus einer früheren Planungsphase.

**Bewertung:** P3 — kosmetisch, kein funktionaler Effekt.

### G.5 README.md behauptet Client-Reinheit, die der Code nicht (mehr) einhält

`README.md` Zeile 56: *"`services/clients/` | Reine externe
Integrationsadapter (keine Telegram-Präsentation, **keine Fachlogik**)"*
— das widerspricht direkt dem am selben Tag bestätigten Befund im
POST-DUPLICATEENTRY-Audit (Abschnitt 5.2): `lastfm_client.py` und
`musicbrainz_client.py` enthalten nachweislich Fachlogik
(`GenreMapper.determine_genre()`-Aufrufe). Kategorie "tatsächlich
falsch", nicht "historisch korrekt" oder "veraltet aber bewusst
erhalten" — die Aussage war zum Zeitpunkt ihres Entstehens vermutlich
korrekt, ist es aber gegenüber dem aktuellen, selbst dokumentierten
Codezustand nicht mehr.

**Bewertung:** P3 — reine Dokumentationsungenauigkeit, keine
Architekturverletzung an sich (der zugrunde liegende Code-Befund ist
bereits unter G.1-analog/5.2 bekannt und priorisiert).

---

## H. Dokumentations-/Struktur-Audit

### H.1 README.md vs. aktueller Code

- Zeile 56 (Client-Reinheit): **tatsächlich falsch**, s. G.5.
- Übrige Architekturzeilen (53–58: `klassen/`, `services/downloader/`,
  `services/metadata/`, `services/clients/`-Dateiliste,
  `services/statistik/`, `handlers/`) stimmen mit der tatsächlichen
  Repository-Struktur überein — **historisch korrekt und weiterhin
  aktuell**.
- `helfer/` wird in der README-Architekturtabelle **nicht erwähnt** —
  unvollständig, aber nicht falsch (Auslassung, kein Widerspruch).

### H.2 Namensfrage: `utils/` vs. `helfer/`

Zwei parallele, funktional getrennte, aber ähnlich benannte
"Helfer"-Verzeichnisse auf Top-Level: `utils/` (englisch, technisch)
und `helfer/` (deutsch, Telegram-Formatierung). Inhaltlich sauber
getrennt (kein Widerspruch, s. D.1), aber die Namensdopplung
("Utils" = "Helfer" wörtlich) kann bei neuen Beiträgen zu Verwechslung
führen, welches Verzeichnis für eine neue Datei zuständig ist. Nicht in
CLAUDE.md dokumentiert (§4 erwähnt `helfer/` gar nicht als eigene
Schicht).

**Bewertung:** P3 — kosmetisch/Namensfrage, kein funktionaler Konflikt,
ähnlich der bereits bekannten `metadata/cache.py` vs.
`utils/metadata_cache.py`-Namensnähe (POST-DUPLICATEENTRY 5.6).

### H.3 Alte ARCH-Dokumente

Keine Änderung an historischen ARCH-Dokumenten vorgenommen oder
vorgeschlagen — sie bleiben als "historisch korrekt" für ihren
jeweiligen Zeitpunkt stehen, wie von der Aufgabenstellung gefordert.

### H.4 `PROJEKTSTAND_KOMPLETT.md`

Nicht als Quelle verwendet, wie in der Aufgabenstellung ausdrücklich
gefordert — nicht auf Existenz/Inhalt geprüft.

---

## I. Test-/Regressionsergebnis

Selbst ermittelt, nicht aus Dokumentation übernommen:

```text
pytest tests/ -q
→ 1114 passed, 15 bekannte Vorbestandsfehler, 0 neue Fehlschläge
```

Identisch zur zuletzt bestätigten Baseline (POST-ARCH-016-Audit) — kein
Delta, da in diesem Audit keine Testdateien verändert wurden.

Zusätzlich gezielt ausgeführt und dokumentiert (nicht in der
Standard-Baseline enthalten, s. G.3):

```text
pytest mapping/test_genre_map.py -q
→ 7 failed, 1 passed
```

Genre-Normalisierung (ARCH-013–016) erneut direkt gegen den Code
verifiziert: 115/115 kanonische Werte idempotent, 57 Spezifitäts-Paare
weiterhin korrekt aufgelöst, `New York Drill`/`Aggro Deutschrap`/`NDW`
alle stabil — keine Regression.

**Kein STOPP-auslösender neuer Fehler** in der Standard-Baseline. Der
Fund in G.3 ist eine bereits seit unbekannter Zeit bestehende,
außerhalb der Baseline liegende Situation, keine durch dieses Audit
verursachte oder neu eingetretene Regression.

---

## J. Priorisierung

| Kandidat | Kategorie | Priorität | Risiko | Architekturgewinn | Empfohlene nächste Phase |
|---|---|---:|---|---|---|
| `utils/audio_enhancer.py` → `services/clients/` (G.1) | Boundary-Verletzung + Doku-Widerspruch | P1 | mittel (P0-Bereich Audio/Cover, aktive Netzwerklogik) | mittel — schafft Konsistenz mit der bestehenden Client-Konvention, klärt mögliche Cover-Art-Duplikation | eigene Characterization-Phase (Consumer-Analyse + Überschneidung mit `cover_processor.py` klären) |
| `handlers/duplicate_handler.py` Entflechtung (G.2) | Business-Logik in Präsentationsschicht | P1 | mittel-hoch (P0-Duplicate-Detection, aktiver Cache-Zustand) | hoch — analog zur bereits erkannten Genre-Logik-Duplikation, schließt die letzte bekannte P0-Domäne mit Schichtvermischung | eigene, dedizierte Characterization-/Decision-Phase, nicht isolierter Schritt |
| `mapping/test_genre_map.py` (G.3) | Test-Hygiene / tote Struktur | P2 | sehr gering (kein Produktionscode betroffen) | gering-mittel (stellt echte vs. suggerierte Testabdeckung richtig) | kleine, risikoarme Aufräum-Phase (verschieben/aktualisieren oder bewusst entfernen) — **kein Architekturauftrag** |

Zusätzlich referenziert (aus `services/`, POST-DUPLICATEENTRY-Audit,
hier nicht erneut priorisiert, nur zur Vollständigkeit): Genre-Logik-
Duplikation in `lastfm_client.py`/`musicbrainz_client.py` (P1, bereits
als eigener Folgeauftrag empfohlen), Last.fm-Duplikation
`cover_processor.py` (P2), DI-Inkonsistenz `album_processor.py` (P3).

---

## K. Empfohlener nächster Schritt

**Kein einzelner Kandidat wird für eine sofortige Umsetzung
vorgeschlagen.**

Begründung: die beiden substanziellsten neuen Befunde dieses Audits
(G.1, G.2) sind in Risiko- und Aufwandscharakter dem bereits bekannten,
bewusst zurückgestellten P1-Kandidaten aus dem POST-DUPLICATEENTRY-
Audit (Genre-Logik-Duplikation) strukturell ebenbürtig — beide berühren
aktiven Code in P0-geschützten Domänen (Audio/Cover bzw. Duplicate
Detection) und erfordern laut CLAUDE.md §6 vorherige
Characterization-Tests, bevor überhaupt etwas verschoben wird. Keiner
von beiden ist eine reine, risikofreie mechanische Verschiebung wie die
bereits umgesetzte `DuplicateEntry`-Migration.

Es gibt damit aktuell **drei** vergleichbar gewichtige P1-Kandidaten
(Genre-Logik-Duplikation aus dem `services/`-Audit, plus G.1 und G.2 aus
diesem Audit) — eine willkürliche Auswahl unter ihnen würde dem
Prinzip "keine künstliche Priorisierung" widersprechen. Die
Aufgabenstellung erlaubt ausdrücklich, in dieser Situation **keinen**
Kandidaten zu benennen.

**Wenn dennoch ein Schritt gewünscht ist:** von den drei P1-Kandidaten
betrifft `handlers/duplicate_handler.py` (G.2) die am wenigsten extern
vernetzte, am klarsten abgegrenzte Domäne (kein externer API-Client
involviert, anders als G.1 und die bekannte Genre-Duplikation) — bei
gewünschter Priorisierung wäre das der naheliegendste erste Kandidat
für eine eigene Characterization-Phase. Dies ist eine Beobachtung,
keine verbindliche Empfehlung.

---

## L. Bewusst zurückgestellt

- Genre-Logik-Duplikation in `lastfm_client.py`/`musicbrainz_client.py`
  — unverändert, eigener Auftrag (POST-DUPLICATEENTRY 5.2/8).
- `utils/audio_enhancer.py` → `services/clients/` (G.1) — Characterization
  vor jeder Verschiebung nötig.
- `handlers/duplicate_handler.py`-Entflechtung (G.2) — Characterization
  vor jeder Verschiebung nötig.
- `mapping/test_genre_map.py` (G.3) — kleine Aufräum-Phase, kein
  Architekturauftrag.
- Last.fm-Duplikation `cover_processor.py`, DI-Inkonsistenz
  `album_processor.py`, tote Imports, `GenreMapper`-Akronymliste,
  `handlers/adapters/`-Leerverzeichnis (G.4), `utils/`/`helfer/`-
  Namensfrage (H.2), README-Ungenauigkeit (G.5) — alle P2/P3, keine
  eigene Phase wert.

---

## M. Entscheidungsgate

**POST-SERVICES / PROJECT-WIDE ARCHITECTURE AUDIT — ENTSCHEIDUNGSGATE
ERREICHT.**

Keine Produktionsänderungen vorgenommen.

**Ergebnis B** — relevante strukturelle Befunde außerhalb von
`services/` gefunden (G.1, G.2), die jeweils eine eigene
Characterization-Phase rechtfertigen würden, aber **keiner** von ihnen
ist ein "klarer nächster Schritt" im Sinne einer risikofreien,
sofortigen Umsetzung (Ergebnis A). `services/` selbst bleibt gemäß dem
tagesaktuellen POST-DUPLICATEENTRY-Audit strukturell stabil ohne neuen
Kandidaten. Die Genre-Normalisierungs-Architektur (ARCH-013–016) ist
vollständig stabil und regressionsfrei bestätigt.

**STOPP.**

Keine Folgephase automatisch gestartet.
