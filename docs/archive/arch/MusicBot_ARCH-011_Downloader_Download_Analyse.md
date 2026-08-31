# ARCH-011 — Architektur-Audit `services/downloader/download/`

## Status

**ARCH-011 Phase 1: ANALYSE ABGESCHLOSSEN (2026-08-24).** Reine Analyse-/
Entscheidungsphase — keine Codeänderung, keine Migration. Wartet auf
explizite Freigabe für eine etwaige Phase 2.

---

## 1. Ausgangslage

ARCH-010 (`docs/archive/arch/MusicBot_ARCH-010_Downloader_Utils_Migration.md`) hat die
alte `services/downloader/utils/`-Struktur vollständig in `services/downloader/`
und `services/metadata/` aufgelöst und ist abgeschlossen. Als nächster
Schritt der schrittweisen Zielarchitektur-Bereinigung wird nun geprüft, ob
das bestehende Unterpaket

```text
services/downloader/download/
```

architektonisch gerechtfertigt ist oder ob es sich — wie die vormalige
`utils/`-Struktur — um eine historisch gewachsene Gruppierung handelt, die
aufgelöst bzw. neu zugeordnet werden sollte.

**Wichtiger Unterschied zu ARCH-010 vorab:** `services/downloader/utils/`
vermischte zwei fachliche Domänen (Downloader- und Metadata-Logik) unter
einem gemeinsamen Pfad und hatte breiten externen Konsum. `download/`
hingegen ist laut eigenem Docstring in `download_utils.py` explizit als
*„Ausgelagerte Module (services/downloader/download/)"* der Datei
`download_utils.py` selbst beschrieben — das ist ein anderer Ausgangsbefund,
der eine andere Bewertung nahelegt (siehe Abschnitt 8).

Ein historischer Präzedenzfall existiert bereits: **ARCH-003 Phase 1**
(`docs/archive/arch/MusicBot_ARCH-003_Services_Phase1_Analyse.md`, Abschnitt 4) schlug
testweise einen Rename `services/downloader/download/` →
`services/downloader/youtube/` vor. Dieser Vorschlag wurde nie umgesetzt
(kein Folge-Commit, keine spätere ADR) und wird hier nicht ungeprüft
übernommen, sondern als ein Datenpunkt unter mehreren behandelt (siehe
Abschnitt 7).

---

## 2. Bestandsaufnahme

`services/downloader/download/` enthält 7 Python-Module + `__init__.py`,
insgesamt 1.578 Zeilen:

| Datei | LOC | Klassen/Funktionen |
|---|---|---|
| `models.py` | 160 | `DownloadResult`, `PlaylistResult` (Dataclasses), `StatusCallback`/`ProgressCallback` (Type-Aliases) |
| `interfaces.py` | 162 | `DownloadCoordinator`, `CacheProvider`, `MetadataEnricher`, `TrackResultCollector` (`Protocol`) |
| `cache_manager.py` | 236 | `CacheManager` (2-stufiger Cache-Lookup: Playlist + Single) |
| `channel_router.py` | 329 | `ChannelRouter` (5-stufiger Artist/Channel-Entscheidungsbaum P1–P5) |
| `download_executor.py` | 345 | `DownloadExecutor` (yt-dlp-Optionen, Info-Extraktion, Einzel-Track-Download, Datei-Suche) |
| `year_resolver.py` | 233 | `YearResolver` (Jahr-Bestimmung aus 4 Quellen) |
| `formatters.py` | 103 | `ProgressFormatter` (statische ASCII-Formatierungs-Methoden) |
| `__init__.py` | 10 | Re-Export aller Modelle/Protocols |

### 2.1 Konsumenten je Datei (repo-weit, produktiv + Tests)

| Datei | Produktions-Consumer | Test-Consumer |
|---|---|---|
| `models.py` (`DownloadResult`, `PlaylistResult`) | `services/downloader/download_utils.py`, `services/downloader/metadata_result_translator.py` | keine eigene Testdatei (indirekt über Consumer-Tests) |
| `interfaces.py` (`CacheProvider`, `MetadataEnricher`) | `services/downloader/download_utils.py` (Typ-Annotationen) | keine eigene Testdatei |
| `interfaces.py` (`DownloadCoordinator`) | **0** — nur in Kommentaren/Docstrings erwähnt, nirgends als Typ verwendet | keine |
| `interfaces.py` (`TrackResultCollector`) | **0** — komplett unbenutzt, auch keine `.collect()`-Aufrufe repo-weit | keine |
| `cache_manager.py` | `services/downloader/download_utils.py` | `tests/test_cache_manager.py` |
| `channel_router.py` | `services/downloader/download_utils.py` | `tests/test_channel_router.py` |
| `download_executor.py` | `services/downloader/download_utils.py` | `tests/test_download_executor.py` |
| `year_resolver.py` | `services/downloader/download_utils.py` | `tests/test_year_resolver.py` |
| `formatters.py` | `services/downloader/download_utils.py` | `tests/test_formatters.py` |
| `__init__.py`-Re-Exports (`from services.downloader.download import X`) | **0** — kein einziger Consumer nutzt den Paket-Level-Import, alle importieren aus den Submodulen direkt | **0** |

**Kernbefund:** Mit Ausnahme von `models.py` (2 Konsumenten innerhalb von
`services/downloader/`) hat **jede** Datei in `download/` genau **einen**
einzigen Konsumenten: `services/downloader/download_utils.py`. Keine Datei
wird von außerhalb `services/downloader/` importiert (kein `handlers/`,
kein `klassen/`, kein `services/metadata/`). Der `__init__.py`-Re-Export
ist toter Code — niemand nutzt den Paket-Level-Import.

### 2.2 Dependencies je Datei

| Datei | `services/downloader/` | `services/metadata/` | `services/clients/` | `utils/` | `handlers/`/`klassen/` | externe Bibliotheken |
|---|---|---|---|---|---|---|
| `models.py` | — | — (Docstring verweist korrekt darauf, keine Duplizierung) | — | — | — | stdlib (`dataclasses`) |
| `interfaces.py` | — | **✓** `services.metadata.models.MetadataResult` | — | — | — | stdlib (`typing`) |
| `cache_manager.py` | — | — | — | `utils.metadata_cache.MetadataCache` | — | stdlib |
| `channel_router.py` | — | — | — | `utils.filenamefixer` (3 Funktionen) | — | stdlib |
| `download_executor.py` | — | — | — | `utils.filenamefixer` (inline, für Podcast-Dauer-Ausnahme) | — | `yt_dlp`, `asyncio` |
| `year_resolver.py` | — | — | — | — | — | stdlib (`re`, `collections`) |
| `formatters.py` | — | — | — | — | — | stdlib |

Keine Datei importiert `config.py` direkt — Konfiguration wird konsequent
per Dependency Injection übergeben (`config`-Parameter). Keine Datei
importiert aus `handlers/` oder `klassen/`. Keine Reverse-Edge: nichts in
`services/metadata/` importiert aus `download/`.

`interfaces.py` ist die **einzige** Datei im Paket mit einer
`services/metadata/`-Abhängigkeit — und diese zeigt in die laut ARCH-010
etablierte Zielrichtung (`Downloader → Metadata`), keine Verletzung.

### 2.3 `mock.patch`, dynamische Imports, String-Referenzen

- **`mock.patch`-Ziele:** keine gefunden, die auf `download/`-Module
  zeigen (repo-weite Suche in allen Testdateien).
- **Dynamische Imports (`importlib`):** keine gefunden.
- **`TYPE_CHECKING`-Blöcke:** keine referenzieren `download/`-Module.
- **String-/Pfad-Referenzen** (Docstrings/Kommentare, kein Code): 5 Dateien
  im Paket selbst (Header-Kommentare `# services/downloader/download/X.py`),
  `download_utils.py` (Architektur-Übersicht im Modul-Docstring), 5
  Testdateien (Modul-Docstrings mit Pfadangabe). Alle sind aktuell korrekt
  — keine Widersprüche zum tatsächlichen Pfad gefunden.
- **Dokumentation:** `README.md` (Projektstruktur-Tabelle, aktuell korrekt
  seit ARCH-010 Phase 3G), `docs/archive/arch/MusicBot_ARCH-003_Services_Phase1_Analyse.md`
  (historische Analyse, Rename-Vorschlag nie umgesetzt),
  `docs/archive/arch/MusicBot_ARCH-004_P3_Orchestrierungs_Analyse.md` (historische
  Analyse, 1 Pfadverweis), `docs/archive/MusicBot_ENGINEERING_BASELINE.md`,
  `docs/archive/MusicBot_SERVICES_Zielarchitektur_Audit.md` (aktuelle
  Zielarchitektur-Bestandsaufnahme, POST-ARCH-009).

---

## 3. Dependency-Graph

```text
services/downloader/download_utils.py
    │
    ├──► services/downloader/download/models.py            (DownloadResult, PlaylistResult)
    ├──► services/downloader/download/interfaces.py         (CacheProvider, MetadataEnricher)
    │        └──► services/metadata/models.py                (MetadataResult)
    ├──► services/downloader/download/cache_manager.py       ──► utils/metadata_cache.py
    ├──► services/downloader/download/channel_router.py      ──► utils/filenamefixer.py
    ├──► services/downloader/download/download_executor.py   ──► utils/filenamefixer.py (inline)
    ├──► services/downloader/download/year_resolver.py        (keine Cross-Deps)
    └──► services/downloader/download/formatters.py           (keine Cross-Deps)

services/downloader/metadata_result_translator.py
    └──► services/downloader/download/models.py             (nur DownloadResult)
```

Keine Gegenrichtung gefunden: nichts unterhalb `services/downloader/download/`
importiert aus `services/metadata/` außer `interfaces.py` (korrekte
Zielrichtung), nichts importiert aus `handlers/`/`klassen/`, nichts wird
von dort re-importiert.

**Vergleich mit ARCH-010-Zielrichtung** (`downloader → metadata`,
`metadata → downloader` nur ARCH-005-Reverse-Edge):

`download/` unterstützt diese Richtung vollständig und erzeugt **keine**
zusätzlichen Architekturprobleme. Der einzige Cross-Boundary-Import
(`interfaces.py → services.metadata.models`) ist unverdächtig — er entspricht
exakt der etablierten Zielrichtung und ist nicht Teil des ARCH-005-Sonderfalls
(der liegt zwischen `enhanced_metadata_processor.py` und
`download_artifact_cleanup.py`, beide außerhalb von `download/`).

---

## 4. Datei-für-Datei-Klassifikation

| Datei | Verantwortung | Consumer | Zielposition | Begründung | Risiko |
|---|---|---|---|---|---|
| `models.py` | Reine Datenstrukturen (`DownloadResult`, `PlaylistResult`) für die gesamte Downloader-Ebene | 2 Dateien in `services/downloader/` (`download_utils.py`, `metadata_result_translator.py`) | `services/downloader/models.py` (flach, analog zu `services/metadata/models.py` nach ARCH-010) | Einziger Kandidat mit mehr als einem Konsumenten *innerhalb* von `services/downloader/` — kein `download_utils.py`-internes Implementierungsdetail mehr, sondern eine paketweite Downloader-Datenstruktur | niedrig |
| `interfaces.py` | Protocol-Verträge (`CacheProvider`, `MetadataEnricher` aktiv genutzt; `DownloadCoordinator` nur dokumentarisch; `TrackResultCollector` tot) | 1 Datei (`download_utils.py`) für 2 von 4 Protocols | unverändert in `download/`, ODER `services/downloader/interfaces.py` (flach) — beides vertretbar | Einziger Single-Consumer-Kandidat mit echtem Cross-Boundary-Import (`services.metadata.models`); enthält zusätzlich toten Code (`TrackResultCollector`), der unabhängig von der Platzierung zu dokumentieren ist | niedrig |
| `cache_manager.py` | `CacheManager` — 2-stufiger Cache-Lookup, reines Downloader-Implementierungsdetail | 1 Datei (`download_utils.py`) | unverändert in `download/` | Exklusiv für `download_utils.py` ausgelagert, keine externe Fan-out, kein Boundary-Mehrwert durch Verschieben | niedrig |
| `channel_router.py` | `ChannelRouter` — Artist/Channel-Routing (P1–P5) | 1 Datei (`download_utils.py`) | unverändert in `download/` | s. o. | niedrig |
| `download_executor.py` | `DownloadExecutor` — yt-dlp-Wrapper (einziger echter externer Netzwerk-/Bibliotheks-Adapter im Paket) | 1 Datei (`download_utils.py`) | unverändert in `download/` (**nicht** `services/clients/`) | `services/clients/` ist laut CLAUDE.md für reine API-/HTTP-Adapter ohne Fachlogik reserviert (`genius_client.py` u. a.); `DownloadExecutor` enthält Downloader-Fachlogik (Retry, Track-Nummerierung, Datei-Templates, Podcast-Dauer-Ausnahme) und hat als direktes Vorbild `spotify_downloader.py`/`downloader.py`, die trotz echter externer Aufrufe ebenfalls in `services/downloader/` verbleiben | niedrig |
| `year_resolver.py` | `YearResolver` — Jahr-Bestimmung, komplett deps-frei | 1 Datei (`download_utils.py`) | unverändert in `download/` | s. o., zusätzlich der am stärksten entkoppelte Kandidat im Paket | niedrig |
| `formatters.py` | `ProgressFormatter` — ASCII-Logformatierung (keine Telegram-/MarkdownV2-Kopplung) | 1 Datei (`download_utils.py`) | unverändert in `download/` | Bewusst *keine* Telegram-Präsentationslogik (kein `Update`/`ParseMode`) → gehört nicht nach `handlers/`; reines internes Log-Formatting bleibt Downloader-intern | niedrig |
| `__init__.py` | Paket-Level-Re-Export aller Modelle/Protocols | **0** Konsumenten | unverändert (oder inhaltlich bereinigen, falls `models.py`/`interfaces.py` verschoben werden) | Toter Re-Export-Layer, aber ungefährlich (kein Aufwand, kein Risiko durch Bestehenlassen) | — |

Keine Datei rechtfertigt eine Zielposition außerhalb von `services/downloader/`
(weder `services/metadata/`, noch `services/clients/`, noch `utils/`, noch
eine neue Top-Level-Struktur).

---

## 5. Besondere Prüfung: Namens-/Verantwortungsüberschneidungen mit `services/metadata/`

Explizit geprüft, da ARCH-010 `services/metadata/cache.py` bereits als
Namenskollisions-Risiko dokumentiert hat (Abschnitt 42.7 der ARCH-010-Doku):

- `services/downloader/download/cache_manager.py::CacheManager` vs.
  `services/metadata/cache.py::MetadataCacheHandler` — **unterschiedliche
  Klassennamen**, unterschiedliche Verantwortung (Downloader-Cache-Lookup
  vs. Metadaten-Cache-Handling). Kein Konflikt, aber thematische Nähe, die
  bei künftiger Umbenennung von `services/metadata/cache.py` (bereits als
  Folgepunkt in ARCH-010 dokumentiert) mitgedacht werden sollte.
- `download/models.py` vs. `services/metadata/models.py` — beide heißen
  `models.py`, liegen aber in unterschiedlichen Paketen und werden nirgends
  gemeinsam mit ambivalentem Import-Pfad referenziert (kein `from .models
  import` funktioniert paketübergreifend falsch, da beide relative Importe
  innerhalb ihres jeweiligen Pakets bleiben). Kein akutes Risiko, aber bei
  einer etwaigen Verschiebung von `download/models.py` nach
  `services/downloader/models.py` entstünde eine 1:1-Namensparallele zu
  `services/metadata/models.py` — bewusst in Abschnitt 8 als Nebenpunkt
  vermerkt, kein Blocker.

Keine weiteren Namens-/Verantwortungsüberschneidungen gefunden.

---

## 6. Test- und Migrationsrisiko

| Kandidat | Betroffene Prod.-Dateien | Betroffene Testdateien | `mock.patch` | Sonstiges | Risiko |
|---|---|---|---|---|---|
| `models.py` → `services/downloader/models.py` | 3 (`download_utils.py`, `metadata_result_translator.py`, `download/__init__.py`) | 0 (keine eigene Testdatei; Consumer-Tests unverändert, da nur der Import-Pfad in Produktionscode wechselt) | keine | `download/interfaces.py`-Docstring erwähnt `MetadataResult`-Nicht-Duplizierung, kein Bezug zu `download/models.py` selbst | niedrig |
| `interfaces.py` → `services/downloader/interfaces.py` | 2 (`download_utils.py`, `download/__init__.py`) | 0 | keine | Cross-Boundary-Import zu `services.metadata.models` bliebe unverändert (nur der eigene Pfad ändert sich) | niedrig |
| `cache_manager.py` hochziehen | 2 (`download_utils.py`, `download/__init__.py` — falls dort gelistet, aktuell nicht) | 1 (`tests/test_cache_manager.py`) | keine | — | niedrig |
| `channel_router.py` hochziehen | 2 | 1 (`tests/test_channel_router.py`) | keine | — | niedrig |
| `download_executor.py` hochziehen | 2 | 1 (`tests/test_download_executor.py`) | keine | — | niedrig |
| `year_resolver.py` hochziehen | 2 | 1 (`tests/test_year_resolver.py`) | keine | — | niedrig |
| `formatters.py` hochziehen | 2 | 1 (`tests/test_formatters.py`) | keine | — | niedrig |
| **Gesamtes Paket flach auflösen** (alle 7 Dateien) | ~4 Produktionsdateien insgesamt | 5 Testdateien | keine | Import-Zyklus-Risiko: keins (alle Ziel-Importe blieben absolut, keine neuen zirkulären Referenzen erkennbar) | niedrig–mittel (nicht wegen technischem Risiko, sondern wegen Umfang/Nutzen-Abwägung, s. Abschnitt 8) |

Keine der Optionen hat ein technisch hohes Risiko — jede Datei hat exakt
einen bis zwei bekannte Konsumenten, keine `mock.patch`-Fallen, keine
dynamischen Imports, keine Importzyklen. Das eigentliche Risiko dieser
Phase ist **kein technisches**, sondern die Abwägung "Aufwand vs. echter
architektonischer Nutzen" (siehe Abschnitt 8).

---

## 7. Vergleich mit ARCH-010

| ARCH-010-Erkenntnis | Übertragbar auf `download/`? | Anmerkung |
|---|---|---|
| Fachliche Verantwortlichkeit vor historischem Pfad | Ja, angewendet (Abschnitt 4) | Führt hier aber zu einem anderen Ergebnis als bei `utils/`, da `download/` bereits fachlich korrekt (reine Downloader-Domäne) einsortiert ist — es gibt keine Domänen-Vermischung aufzulösen |
| Keine neue Zwischenarchitektur ohne konkreten Bedarf | Ja | Bestätigt: keine neue Top-Level-Struktur wird hier vorgeschlagen |
| Consumer-basierte Zuordnung | Ja, angewendet (Abschnitt 2.1) | Führt zum zentralen Unterschied: ARCH-010-Dateien hatten multiple externe Konsumenten über mehrere Pakete hinweg; `download/`-Dateien haben (bis auf `models.py`) exakt einen Konsumenten *innerhalb desselben Pakets* — das ist strukturell kein vergleichbarer Fall |
| Downloader → Metadata als Zielrichtung | Ja | Bestätigt eingehalten (Abschnitt 3) |
| Bestehende `services/clients/`-Boundary | Ja, geprüft (Abschnitt 4, `download_executor.py`) | Bestätigt: kein Kandidat für `services/clients/` |
| Keine unnötigen Umbenennungen | Ja | Der ARCH-003-Rename-Vorschlag (`download/` → `youtube/`) wird explizit **nicht** übernommen — kein neuer konkreter Bedarf identifiziert, reine Umbenennung ohne Konsumenten-Nutzen |
| Kleine, isolierbare Migrationen | Ja, für den Fall dass Phase 2 beschlossen wird | Jeder Datei-Umzug wäre für sich isolierbar (Abschnitt 6) |
| Entscheidung vor Umsetzung | Ja | Dieses Dokument ist genau dieser Schritt |

**Nicht übertragbar:** Die zentrale ARCH-010-Prämisse — *„eine Struktur mit
breitem externen Konsum über mehrere Domänen hinweg muss nach fachlicher
Zugehörigkeit aufgeteilt werden"* — trifft auf `download/` nicht zu, weil
weder eine Domänen-Vermischung noch ein breiter externer Konsum vorliegt.
`download/` ist strukturell näher an einer **internen Modul-Zerlegung einer
einzelnen großen Datei** (`download_utils.py`, vgl. CLAUDE.md Abschnitt 19
„Große Klassen") als an einer eigenständigen Service-Schicht wie
`services/metadata/`.

---

## 8. Ist `services/downloader/download/` eine echte fachliche Unterdomäne?

**Nein — mit einer kleinen Einschränkung für `models.py`.**

- **6 von 7 Dateien** (`interfaces.py`, `cache_manager.py`,
  `channel_router.py`, `download_executor.py`, `year_resolver.py`,
  `formatters.py`) sind ausschließlich für `download_utils.py` ausgelagerte
  Implementierungsdetails — exakt wie der Docstring von `download_utils.py`
  es selbst beschreibt ("Ausgelagerte Module"). Sie haben keinen externen
  Konsumenten außerhalb dieser einen Datei und bilden keine gemeinsame
  fachliche Unterdomäne mit eigenem Vertrag nach außen — der `__init__.py`-
  Re-Export, der genau diesen Vertrag abbilden würde, wird von niemandem
  genutzt.
- **`models.py`** ist der einzige Ausreißer: mit zwei Konsumenten
  *innerhalb* von `services/downloader/` (nicht nur `download_utils.py`,
  sondern auch `metadata_result_translator.py`) ist es de facto bereits
  eine paketweite Downloader-Datenstruktur, keine `download_utils.py`-
  exklusive.
- Es gibt **keine erkennbaren weiteren Subdomains** innerhalb von
  `download/` — alle 6 „Kern"-Dateien sind gleichrangige, voneinander
  unabhängige Helfer ohne interne Hierarchie.
- Es gibt **keine öffentliche Facade/Entry-Point**-Datei innerhalb von
  `download/` selbst — `download_utils.py` (außerhalb des Pakets) ist die
  eigentliche Facade, die alle Bausteine zusammensetzt.
- Es gibt **keine unnötigen Abstraktionen oder historischen Bridges** im
  Sinne von Kompatibilitätsschichten — `interfaces.py` enthält jedoch mit
  `TrackResultCollector` einen nie genutzten Protocol-Kandidaten und mit
  `DownloadCoordinator` einen nur dokumentarisch verwendeten (charakterisiert,
  nicht zu entfernen ohne separate Entscheidung, siehe Regel 20 CLAUDE.md).

`download/` ist damit primär eine **historische Gruppierung mit
Lesbarkeits-Nutzen** (verhindert eine 16-Datei-flache `services/downloader/`-
Ebene), keine fachliche Boundary mit eigenem externem Konsumentenkreis.

---

## 9. Zielarchitektur — Variantenvergleich

**A — `download/` vollständig beibehalten**
Kein Konsument profitiert von einer Verschiebung; das Paket bündelt
sinnvoll 6 reine Implementierungsdetails von `download_utils.py` und hält
`services/downloader/` bei aktuell 9 Dateien statt potenziell 15–16.
*Aufwand: keiner. Nutzen: Statuserhalt, keine Regression möglich.*

**B — einzelne Dateien nach `services/downloader/` hochziehen**
Nur für `models.py` (und optional `interfaces.py`) sachlich begründbar,
da `models.py` bereits mehr als einen Konsumenten im Paket hat. Für die
übrigen 5 Dateien liefert diese Variante keinen Konsumenten- oder
Klarheits-Gewinn, nur Umfang (5 Dateien mehr in `services/downloader/`).
*Aufwand: gering pro Datei. Nutzen: nur für `models.py` klar positiv.*

**C — mehrere fachliche Teilbereiche neu ordnen**
Nicht gerechtfertigt: es gibt innerhalb von `download/` keine erkennbaren
Subdomains, die eine Neuordnung in mehrere Teilbereiche rechtfertigen
würden (Abschnitt 8). Diese Variante würde Struktur erzeugen, die durch
keinen Konsumenten und keine Domänen-Trennung gestützt ist — genau das,
wovor die Aufgabenstellung ausdrücklich warnt.

**D — andere bestehende Boundary nutzen** (`services/metadata/`,
`services/clients/`, `utils/`)
Für keine der 7 Dateien sachlich begründbar (Abschnitt 4). Der einzige
Kandidat mit externem Netzwerkbezug (`download_executor.py`) hat mit
`spotify_downloader.py`/`downloader.py` ein eindeutiges Vorbild, das trotz
echter externer Aufrufe in `services/downloader/` verbleibt, nicht in
`services/clients/`.

### Empfehlung

**Variante A, mit optionalem, niedrig priorisiertem Teilaspekt aus
Variante B für `models.py` allein.**

Eine neue Top-Level-Schicht (Variante C) ist nicht gerechtfertigt. Eine
vollständige Auflösung des Pakets (Variante B für alle 7 Dateien) hätte
zwar niedriges technisches Risiko, aber keinen belegbaren architektonischen
Nutzen — sie würde `services/downloader/` von 9 auf 15–16 flache Dateien
vergrößern, ohne dass ein einziger Konsument davon profitiert. Das
widerspricht CLAUDE.md Abschnitt 18 ("Kein großer Refactor als erste
Reaktion auf ein Problem") und Abschnitt 19 ("Nicht automatisch
zerlegen") — hier in der Umkehrung: nicht automatisch zusammenlegen, nur
weil es auf den ersten Blick möglich wäre.

---

## 10. Priorisierung möglicher Folgekandidaten

**P0 — zwingender Architekturfehler:** keiner gefunden. Keine
Schichtgrenzen-Verletzung, keine Reverse-Edge, keine Namenskollision mit
echtem Konfliktpotenzial.

**P1 — kleiner, klar isolierbarer Kandidat:** keiner mit ausreichendem
Nutzen identifiziert (s. Empfehlung Abschnitt 9).

**P2 — sinnvoller Folgepunkt (nicht jetzt, aber dokumentiert):**

1. *`models.py` → `services/downloader/models.py`.*
   Problem: einzige Datei mit paketweitem statt `download_utils.py`-
   exklusivem Konsum. Zielposition: `services/downloader/models.py`.
   Consumer: `download_utils.py`, `metadata_result_translator.py`.
   Abhängigkeiten: keine. Risiko: niedrig. Erwarteter Nutzen: gering
   (kosmetisch treffendere Einordnung, kein funktionaler Gewinn). Warum
   jetzt nicht: kein Konsument ist aktuell beeinträchtigt; besser im
   Rahmen einer größeren, mehrfach begründeten Migration statt isoliert.

2. *`interfaces.py`: `TrackResultCollector` (totes Protocol) und
   `DownloadCoordinator` (nur dokumentarisch verwendet) klären.*
   Problem: unbenutzter/kaum benutzter Code, nicht ARCH-011-Scope (Regel 20
   CLAUDE.md: nicht ohne Beweis/Entscheidung entfernen). Zielposition:
   unverändert, nur Entscheidung nötig (behalten/entfernen). Risiko:
   niedrig. Warum jetzt nicht: eigenständige Legacy-Code-Frage, kein
   Struktur-Thema.

3. *`services/metadata/cache.py`-Umbenennung* (bereits in ARCH-010,
   Abschnitt 42.7 dokumentiert) — bei Umsetzung zusätzlich gegen
   `download/cache_manager.py::CacheManager` abgleichen, um keine neue
   Verwechslungsgefahr zu erzeugen (Abschnitt 5).

**P3 — derzeit nicht anfassen:**

- `cache_manager.py`, `channel_router.py`, `download_executor.py`,
  `year_resolver.py`, `formatters.py` — jeweils einzeln hochziehen. Kein
  Konsument profitiert, reiner Umfang-Zuwachs in `services/downloader/`
  ohne Gegenwert.
- Vollständige Auflösung des Pakets in einem Zug.
- ARCH-003-Rename (`download/` → `youtube/`) — kein neuer Bedarf seit
  2026, keine Reaktivierung ohne konkreten Auslöser.

---

## 11. Risikoanalyse (Zusammenfassung)

Technisches Migrationsrisiko ist für **jeden** einzelnen Kandidaten
**niedrig** (Abschnitt 6): wenige, bekannte, nicht-zyklische Konsumenten,
keine `mock.patch`-Fallen, keine dynamischen Imports. Das eigentliche
Risiko dieser Phase liegt nicht im Technischen, sondern darin, eine
Struktur zu verändern, für die kein Konsument einen Nutzen hat — das wäre
Aufwand ohne Sicherheitsnetz-Gewinn, im Widerspruch zu CLAUDE.md Regel 1
("Kein größerer Refactor ohne Sicherheitsnetz [das hier keinen zusätzlichen
Zweck erfüllen würde]").

---

## 12. ARCH-011 Phase 1 — Entscheidungsgate

**1. Ist `services/downloader/download/` architektonisch gerechtfertigt?**
Als Lesbarkeits-Gruppierung ja, als eigenständige fachliche Unterdomäne mit
externem Konsumentenkreis nein (Abschnitt 8). Es ist im Kern die interne
Zerlegung einer einzelnen großen Datei (`download_utils.py`).

**2. Welche Dateien bleiben dort?**
Empfehlung: alle 7, inkl. `models.py` (P2-Kandidat, nicht jetzt).

**3. Welche Dateien sollten verschoben werden?**
Keine mit ausreichendem Nutzen für eine sofortige Umsetzung. `models.py`
ist der einzige mit einer plausiblen, aber niedrig priorisierten
Begründung.

**4. Welche Zielposition wird für jede verschobene Datei empfohlen?**
Falls `models.py` künftig verschoben wird: `services/downloader/models.py`
(flach, analog zum ARCH-010-Muster bei `services/metadata/models.py`).

**5. Welche Dependency-Richtung soll gelten?**
Unverändert: `services/downloader/ → services/metadata/`. `download/`
folgt dieser Richtung bereits vollständig (Abschnitt 3).

**6. Gibt es Reverse-Edges?**
Nein, keine gefunden innerhalb von `download/`. Der bekannte ARCH-005-
Sonderfall liegt vollständig außerhalb dieses Pakets und bleibt unberührt.

**7. Welche bekannten Architekturentscheidungen müssen erhalten bleiben?**
- `services/clients/`-Boundary bleibt für reine API-/HTTP-Adapter
  reserviert; `download_executor.py` bleibt bewusst davon ausgenommen.
- ARCH-005-Reverse-Edge (`enhanced_metadata_processor.py` ↔
  `download_artifact_cleanup.py`) bleibt unverändert und unresolved.
- Keine Telegram-Präsentationslogik in `services/` (bestätigt: `formatters.py`
  ist reines internes ASCII-Logging, keine MarkdownV2/Telegram-Kopplung).

**8. Welche Folgeprobleme werden ausdrücklich NICHT in ARCH-011 gelöst?**
- `TrackResultCollector`/`DownloadCoordinator` (toter/kaum genutzter Code
  in `interfaces.py`) — eigenständige Legacy-Entscheidung, nicht Teil
  dieses Struktur-Audits.
- `services/metadata/cache.py`-Namenskollisions-Frage (bereits aus
  ARCH-010 bekannt, hier nur zusätzlich gegen `cache_manager.py` geprüft).
- `download_result_reporter.py`'s `DuplicateEntry`-Import aus `handlers/`
  (P-1 aus `docs/archive/MusicBot_SERVICES_Zielarchitektur_Audit.md`) — liegt
  außerhalb von `download/`, nicht Teil dieses Scopes.
- Last.fm-Duplizierung in `cover_processor.py` (P-2, ebenda) — betrifft
  `services/metadata/`, nicht `download/`.

**9. Welcher Kandidat sollte als Phase 2 zuerst umgesetzt werden?**
Empfehlung: **keiner sofort.** Falls dennoch gewünscht, wäre `models.py` →
`services/downloader/models.py` der einzige mit belastbarer, wenn auch
schwacher Begründung (P2, Abschnitt 10).

**10. Sollte die Migration in einem PR oder mehreren kleinen PRs erfolgen?**
Falls Phase 2 überhaupt stattfindet: ein einzelner, kleiner PR für
`models.py` allein würde genügen (2 Produktionsdateien, kein Testaufwand)
— eine Aufteilung in mehrere PRs wäre für diesen einen Kandidaten
überdimensioniert.

---

## 13. Entscheidung

**Warten auf explizite Freigabe durch den Nutzer.** Kein automatischer
Übergang in eine Umsetzungsphase. Kein ARCH-012-Vorschlag als Teil dieses
Auftrags.
