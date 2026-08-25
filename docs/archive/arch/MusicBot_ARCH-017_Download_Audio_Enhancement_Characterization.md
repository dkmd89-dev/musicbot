# MusicBot ARCH-017 — Download-/Audio-Enhancement-Characterization

**Status:** Phase 1 (Characterization) abgeschlossen. Keine
Produktionsänderung. Keine YAML-Änderung. Keine Umsetzung. Wartet auf
ausdrückliche Freigabe für eine mögliche Phase 2.

---

## 1. Ausgangsbefund

Der POST-SERVICES-Audit (`docs/POST-SERVICES_PROJECT-WIDE_ARCHITECTURE_AUDIT.md`,
Abschnitt G.1) hatte festgestellt, dass `utils/audio_enhancer.py` echte
HTTP-Aufrufe an MusicBrainz und Cover Art Archive enthält, obwohl
CLAUDE.md §4 das Modul als Beispiel für netzwerkfreie `utils/`-Module
nennt. Dieser Befund wurde dort bewusst **nicht** als abschließend
bewertet, sondern als klärungsbedürftig markiert.

**Zentrales Ergebnis dieser Phase:** Der scheinbare Netzwerk-Befund ist
**nicht das eigentliche Problem**. Die tatsächlich entscheidende
Erkenntnis ist eine andere: Von den ca. 13 Methoden in
`utils/audio_enhancer.py` wird in der **gesamten** produktiven Pipeline
(und auch in keinem Test) nur **eine einzige** tatsächlich aufgerufen —
die statische Methode `normalize_loudness()` (plus die triviale
`get_target_lufs()`-Konstantenabfrage). Die gesamte Netzwerk-/
ReplayGain-/Künstlerbild-/MusicBrainz-ID-Logik (~340 der ~520 Zeilen der
Datei) ist **toter Code** — nie instanziiert, nie aufgerufen,
nie getestet. Die im vorherigen Audit vermutete "Architekturverletzung
durch Netzwerkzugriff" existiert im **laufenden Betrieb nicht real**.

Belegt durch:

```bash
grep -rn "AudioEnhancer(" --include="*.py" .    # → 0 Treffer (nie instanziiert)
grep -rn "\.enhance_downloaded_file(\|\.calculate_replaygain(\|\.fetch_artist_image(\|\.fetch_musicbrainz_data(" --include="*.py" .
# → 0 Treffer außerhalb der Definition in utils/audio_enhancer.py selbst
```

---

## 2. Tatsächlicher Download-Datenfluss

Rekonstruiert aus `services/metadata/enhanced_metadata_processor.py`
(numerierte Log-Schritte, direkt im Code):

```text
1️⃣  Start Track-Metadatenverarbeitung
...
9️⃣/9️⃣b  Genre-Bestimmung inkl. EINMALIGEM MusicBrainz-Aufruf
        (services/clients/musicbrainz_client.py, via genre_processor.py)
        → mb_ids (recording_id, artist_id, release_id, release_group_id, isrc)
        werden im Ergebnisobjekt (GenreResult.mb_ids) gespeichert
🔟  Lyrics
1️⃣1️⃣b  Cover-Art laden (services/metadata/cover_processor.py)
        → verwendet die BEREITS VORHANDENEN mb_ids (release_id,
          release_group_id, artist_id) aus Schritt 9 — KEIN zweiter
          MusicBrainz-Aufruf
1️⃣2️⃣  Album & Jahr bestimmen (services/metadata/album_processor.py)
1️⃣5️⃣b  Loudness-Normalisierung — AudioEnhancer.normalize_loudness()
        (utils/audio_enhancer.py, statische Methode, reiner
        ffmpeg-Subprocess-Aufruf, KEIN Netzwerk)
1️⃣6️⃣  Datei in Bibliothek verschieben
1️⃣7️⃣  Metadaten-Tags schreiben (services/metadata/tag_writer.py)
```

Dieser Ablauf deckt sich **exakt** mit dem vom Nutzer bereitgestellten
realen Download-Log (Zeile für Zeile identische Log-Texte im Code
gefunden, s. Abschnitt 12).

---

## 3. Aufrufgraph

```text
klassen/download_handler.py
    → services/downloader/* (Download-Pipeline, ARCH-010)
        → services/metadata/enhanced_metadata_processor.py  (Facade)
            → services/metadata/genre_processor.py
                → services/clients/musicbrainz_client.py   [EINZIGER MB-Aufruf]
                → services/clients/lastfm_client.py
            → services/metadata/cover_processor.py
                → Cover Art Archive, Fanart.tv, Apple Music, Deezer,
                  eigene Last.fm-Session (bereits bekannt, POST-
                  DUPLICATEENTRY 5.3 — hier nicht neu bewertet)
            → services/metadata/album_processor.py
                → services/clients/musicbrainz_client.py (optional,
                  Lazy-Fallback, bereits bekannt, POST-DUPLICATEENTRY 5.4)
            → utils/audio_enhancer.py :: AudioEnhancer.normalize_loudness()
                [STATISCH, kein Objekt, kein Netzwerk — reiner
                 subprocess.run(["ffmpeg", ...])]
            → services/metadata/tag_writer.py
```

**`utils/audio_enhancer.py` wird ausschließlich über zwei
Klassenebene-Aufrufe erreicht** (`AudioEnhancer.get_target_lufs(...)`,
`AudioEnhancer.normalize_loudness(...)`), beide in einem lokalen
`try/except ImportError` (Zeilen 792–819) — die Datei ist damit sogar
**optional**: fehlt sie, wird die Loudness-Normalisierung übersprungen,
der Rest der Pipeline läuft unverändert weiter (`nicht kritisch`,
Log-Zeile bei Fehler).

Kein weiterer Aufrufer im gesamten Repository (`handlers/`, `klassen/`,
`services/`, `tests/`) ruft `AudioEnhancer` oder eine ihrer Methoden
auf, außer den zwei oben genannten Stellen.

---

## 4. Verantwortlichkeiten von `audio_enhancer.py`

| Verantwortung | Funktion(en) | Tatsächlich aufgerufen? | Aufrufer | Zuständiger anderer Service existiert bereits? |
|---|---|---|---|---|
| Loudness-Normalisierung (ffmpeg `loudnorm`, destruktiv, überschreibt Datei) | `normalize_loudness()` (staticmethod) | **JA** — einziger live genutzter Teil | `enhanced_metadata_processor.py:801` | nein, einzige Implementierung |
| LUFS-Zielwert-Konstanten | `get_target_lufs()` (classmethod) | **JA** | `enhanced_metadata_processor.py:799` | nein, einzige Implementierung |
| ReplayGain-Berechnung (ffmpeg `ebur128`, nicht-destruktiv, nur Tag) | `calculate_replaygain()` | **NEIN** — tot | — | nein bekannt, aber unbenutzt |
| ReplayGain-Tags schreiben | `write_replaygain_tags()` | **NEIN** — tot (nur intern von `enhance_downloaded_file()` aufgerufen, die selbst tot ist) | — | `services/metadata/tag_writer.py` schreibt bereits Tags — unklar, ob ReplayGain dort abgedeckt ist, außerhalb Scope |
| Künstlerbild via Last.fm | `fetch_artist_image()` → `_fetch_lastfm_image()` | **NEIN** — tot | — | **ja** — `cover_processor.py` fetcht bereits Last.fm-Bilder (identisches JSON-Muster `data.get('artist',{}).get('image',[])`, s. Abschnitt 9) |
| Künstlerbild via MusicBrainz + Cover Art Archive | `_fetch_musicbrainz_image()` | **NEIN** — tot | — | **ja** — `cover_processor.py` nutzt Cover Art Archive bereits aktiv |
| Bildverarbeitung/-skalierung | `_save_image()` | **NEIN** — tot (nur von toten Methoden aufgerufen) | — | unklar, außerhalb Scope |
| MusicBrainz-Recording/Artist/Release-IDs + ISRC | `fetch_musicbrainz_data()` | **NEIN** — tot | — | **ja** — `services/clients/musicbrainz_client.py`, bereits aktiv über `genre_processor.py` genutzt (liefert dieselben Felder: `recording_id`, `artist_id`, `release_id`, `isrc`) |
| MusicBrainz-Tags schreiben | `write_musicbrainz_tags()` | **NEIN** — tot | — | `tag_writer.py` schreibt bereits `mb_ids` aus dem Genre-Pfad (s. Abschnitt 2) — vermutlich bereits abgedeckt, nicht abschließend verifiziert (außerhalb Scope) |
| Orchestrierende Hauptmethode ("verbessert Datei nach Download") | `enhance_downloaded_file()` | **NEIN** — tot | — | funktional durch die numerierte Pipeline in `enhanced_metadata_processor.py` ersetzt |
| Batch-Verarbeitung eines Verzeichnisses | `enhance_batch()` | **NEIN** — tot | — | kein Äquivalent gefunden, evtl. CLI-/Wartungswerkzeug-Rest |

**Fachlich gehören diese Verantwortlichkeiten NICHT zusammen:**
Loudness-Normalisierung ist reine Audiosignalverarbeitung (ffmpeg,
lokal, keine Fachentscheidung). ReplayGain, Künstlerbild-Beschaffung
und MusicBrainz-ID-Ermittlung sind jeweils eigenständige fachliche
Belange, die an anderer Stelle im Projekt (teilweise) bereits eigene,
aktiv genutzte Heimat haben (`cover_processor.py`,
`musicbrainz_client.py`). Die Datei bündelt sie historisch in einer
Klasse, aktiviert aber im laufenden Betrieb nur den einen Teil, der
fachlich am wenigsten mit den anderen zu tun hat.

---

## 5. Netzwerkzugriffe (vollständige Auflistung)

Alle folgenden Aufrufe befinden sich in **totem Code** (nie erreicht):

| Ziel | Funktion | Zweck | Eingabe | Rückgabe | Timeout | Bereits durch bestehenden Client abgedeckt? |
|---|---|---|---|---|---|---|
| `ws.audioscrobbler.com` (Last.fm) | `_fetch_lastfm_image()` | Künstlerbild | `artist_name`, `lastfm_api_key` | Bild-Bytes | 10s (Suche), 15s (Bild) | ja, funktional durch `cover_processor.py::_fetch_lastfm()` |
| `musicbrainz.org/ws/2/artist/` | `_fetch_musicbrainz_image()` | Artist-ID-Suche für Cover Art Archive | `artist_name` | Artist-ID | 10s | ja, `musicbrainz_client.py` sucht bereits Artists/Recordings |
| `coverartarchive.org/artist/{id}` | `_fetch_musicbrainz_image()` | Künstlerbild | Artist-ID | Bild-URL/Bytes | 10s (Liste), 15s (Bild) | kein anderer Client für Cover-Art-Archive-*Artist*-Bilder gefunden (nur `cover_processor.py` nutzt CAA für *Release*-Cover) |
| `musicbrainz.org/ws/2/recording/` | `fetch_musicbrainz_data()` | Recording-/Artist-/Release-ID, ISRC | `title`, `artist`, optional `duration` | strukturiertes Dict | 10s | ja, `musicbrainz_client.py` liefert dieselben Felder |

**Kein einziger dieser Aufrufe wird durch den vom Nutzer bereitgestellten
Download-Log oder durch reales Laufzeitverhalten ausgelöst.** Es
entsteht dadurch **keine** Duplikation von tatsächlichem
API-Traffic — die Duplikation ist ausschließlich eine im Code
**latent vorhandene, aber inaktive** Redundanz.

---

## 6. Loudness-/FFmpeg-Pipeline im Detail

Zwei **vollständig unabhängige** Mechanismen existieren in derselben
Datei, die leicht verwechselt werden können:

### `normalize_loudness()` (staticmethod) — **die live genutzte Funktion**

- ffmpeg-Filter: `loudnorm` (Zwei-Pass: Analyse mit
  `print_format=json`, dann Anwendung mit den gemessenen Werten;
  Fallback auf Einzeldurchlauf, falls die JSON-Analyse fehlschlägt).
- **Destruktiv:** erzeugt eine temporäre Datei
  (`temp_loudnorm_{name}`), re-encodiert zu AAC (`-c:a aac -b:a 192k`),
  ersetzt danach die Originaldatei (`temp_path.replace(path)`).
- Nur für `.m4a`/`.mp4`/`.mp3` aktiv, andere Formate werden
  übersprungen (`return True` ohne Aktion).
- Zeitpunkt: **nach** Cover-Art/Album/Jahr, **vor** dem
  Verschieben in die Bibliothek und dem Tag-Schreiben (Schritt 15b von
  17) — die Datei wird also physisch verändert, bevor Metadaten-Tags
  geschrieben werden, was unkritisch ist, da `loudnorm` selbst mit
  `mutagen` inkompatible Tags nicht zwangsläufig zerstört (nicht
  weiter verifiziert, außerhalb Scope), aber relevant für die
  Reihenfolge-Frage: **Cover-Art/MB-IDs werden VOR der destruktiven
  Audio-Neucodierung ermittelt, aber ERST NACH ihr in Tags
  geschrieben** (Schritt 17) — kein Datenverlust, da die Werte im
  Python-Objekt zwischengehalten werden, nicht in der Datei selbst.
- Fehlerverhalten: `try/except` mit `Timeout` (60s Analyse, 120s
  Anwendung) und allgemeiner `Exception`, `finally`-Block räumt die
  Temp-Datei auf. Fehler sind laut Aufrufer **nicht kritisch**
  ("Loudness-Normalisierung fehlgeschlagen (nicht kritisch)") — die
  Pipeline läuft in jedem Fall weiter.
- **Idempotenz:** nicht geprüft/erzwungen. Ein zweiter Aufruf auf einer
  bereits normalisierten Datei würde erneut analysieren und erneut
  anwenden — da `loudnorm` deterministisch auf Basis der *aktuellen*
  gemessenen Lautheit arbeitet, sollte ein zweiter Durchlauf den
  Zielwert erneut treffen (kein Kumulationsfehler zu erwarten), aber
  jeder Durchlauf verlustbehaftet neu encodiert (Generationsverlust bei
  AAC). Im aktuellen Pipeline-Aufrufgraphen wird die Funktion pro Track
  nachweislich nur **einmal** aufgerufen (Schritt 15b, einmalig pro
  Verarbeitungsdurchlauf).

### `calculate_replaygain()` (Instanzmethode) — **tot**

- ffmpeg-Filter: `ebur128=peak=true` (EBU R128, nicht `loudnorm`).
- **Nicht-destruktiv:** verändert die Audiodaten nicht, berechnet nur
  einen Gain-/Peak-Wert relativ zu einem festen Ziel von **-16 LUFS**
  (hartkodiert, nicht über `TARGET_LUFS`/`content_type` konfigurierbar
  — anders als `normalize_loudness()`).
- Würde (wäre sie live) über `write_replaygain_tags()` iTunes-Tags
  schreiben (`----:com.apple.iTunes:replaygain_track_gain/_peak`).

**ReplayGain und LUFS-Normalisierung sind im aktuellen Code zwei
unterschiedliche, nicht miteinander verbundene Konzepte:**
`normalize_loudness()` verändert die Audiodatei selbst dauerhaft auf
einen Ziel-LUFS-Wert (destruktiv). `calculate_replaygain()` (tot) würde
stattdessen nur einen Tag-Wert für Player berechnen, die selbst zur
Wiedergabezeit nicht-destruktiv anpassen (ReplayGain-Konzept) — beide
Ansätze verfolgen dasselbe Ziel (konsistente Lautstärke), auf
fachlich unterschiedlichem Weg. Da nur `normalize_loudness()` live ist,
gibt es aktuell **keinen Konflikt** zwischen beiden — die
ReplayGain-Variante ist vollständig inaktiv.

---

## 7. `EnhancedMetadataProcessor`-Rolle

`enhanced_metadata_processor.py` ist die alleinige Facade der
Metadaten-Pipeline (bereits im POST-DUPLICATEENTRY-Audit bestätigt,
hier nicht neu hergeleitet). Für den Download-/Audio-Enhancement-Teil
gilt:

- **Orchestriert:** die gesamte numerierte Schrittfolge (Genre → Lyrics
  → Cover → Album/Jahr → Loudness → Move → Tags).
- **Delegiert:** Genre-Bestimmung an `genre_processor.py`, Cover an
  `cover_processor.py`, Album/Jahr an `album_processor.py`, Tags an
  `tag_writer.py`, Loudness an `utils/audio_enhancer.py`
  (ausschließlich die eine statische Methode).
- **Enthält selbst direkt:** die MB-ID-Wiederverwendungslogik für Cover
  (`_get_mb_id()`, lokale Closure, Zeilen 663–667) — eine kleine, hier
  korrekt platzierte Orchestrierungs-Entscheidung (kein eigener
  Netzwerkaufruf, nur Datenweiterreichung).
- **`audio_enhancer.py` besitzt in diesem Zusammenhang ausschließlich
  eine rein technische Hilfsrolle** (ein Subprocess-Aufruf für einen
  einzigen Schritt), **keine eigene fachliche Entscheidungsrolle** —
  die Facade entscheidet Ziel-LUFS anhand von `category`
  (Podcast/Musik), `audio_enhancer.py` führt nur aus.

Verantwortlichkeiten sind für den **live genutzten** Pfad sauber
getrennt. Für den **toten** Code-Anteil (Künstlerbild, ReplayGain,
MB-IDs) ist keine Aussage über "sauber getrennt" möglich, da er nicht
in den orchestrierten Ablauf eingebunden ist — er existiert parallel,
unverbunden, im selben Modul.

---

## 8. CLAUDE.md-vs-Code-Abgleich

CLAUDE.md §4 nennt `audio_enhancer.py` als Beispiel für ein `utils/`-
Modul "ohne externe Netzwerkkommunikation".

**Zutreffende Einordnung: Fall C, mit wichtiger Präzisierung.**

- **Nicht Fall A** ("Dokumentation veraltet/falsch, aktueller Code
  architektonisch beabsichtigt") — denn der tote Netzwerk-Code ist
  nicht "beabsichtigt aktiv", sondern schlicht nie entfernt.
- **Nicht (nur) Fall B** ("Netzwerkzugriff ist unbeabsichtigte
  Verantwortungsverletzung") — denn der Netzwerkzugriff verletzt im
  **laufenden Betrieb** nichts, da er nie ausgeführt wird. Eine reine
  "Verstoß"-Einordnung würde ein aktives Problem suggerieren, das nicht
  vorliegt.
- **Fall C trifft zu** ("Das Modul hat mehrere Verantwortlichkeiten und
  die Dokumentation verdeckt ein echtes Architekturproblem") — **aber
  das eigentliche Problem ist nicht die Netzwerkkommunikation selbst,
  sondern dass die Datei mehrere, fachlich unterschiedliche,
  größtenteils tote Verantwortlichkeiten bündelt**, wovon CLAUDE.md nur
  den heute irrelevantesten Aspekt (Netzwerk) fälschlich ausschließt.
  Die Dokumentation ist damit zufällig "fast richtig" für das *aktive*
  Verhalten, aber komplett falsch für den *tatsächlichen Dateiinhalt*.
- **Fall D trifft anteilig zu** ("Netzwerkzugriffe gehören fachlich in
  einen bestehenden Client, Audio-Enhancement bleibt korrekt dort") —
  dies beschreibt exakt, wohin sich das Modul entwickeln müsste,
  *falls* die toten Netzwerkmethoden jemals reaktiviert werden sollten:
  die MusicBrainz-/Cover-Logik würde dann in
  `services/clients/musicbrainz_client.py`/`services/metadata/cover_processor.py`
  gehören, nicht in `utils/`. Für den **aktuellen, tatsächlichen**
  Zustand (Code ist tot) ist diese Frage aber nicht akut.

**Kurzfassung:** CLAUDE.md beschreibt nicht den Dateiinhalt korrekt,
aber (zufällig) näherungsweise das aktive Laufzeitverhalten. Das
eigentliche Problem ist nicht Netzwerkzugriff, sondern **toter Code mit
mehreren, teils bereits anderswo abgedeckten Verantwortlichkeiten in
einer als "einfaches Utility" dokumentierten Datei**.

---

## 9. Dependency-/Layer-Audit

```text
utils/audio_enhancer.py
    Imports: os, logging, subprocess, pathlib, typing, dataclasses,
             concurrent.futures, functools, requests, mutagen.mp4,
             PIL.Image, io
    → KEINE internen Projekt-Imports (kein services/, kein handlers/,
      kein klassen/) — reines Blatt-Modul.

services/metadata/enhanced_metadata_processor.py
    → utils/audio_enhancer.py   [erwartete Richtung: services → utils]
```

- **Import-Richtung:** korrekt, `services → utils`, keine Reverse-Edge.
- **Keine Zyklen.**
- **Kein unerwarteter Netzwerkzugriff an aktiver Stelle** — der einzige
  live Codepfad (`normalize_loudness`) ist reiner `subprocess`-Aufruf,
  kein Netzwerk.
- **Client-Umgehung:** nur im toten Code vorhanden (s. Abschnitt 5) —
  keine aktive Umgehung von `services/clients/musicbrainz_client.py`.

Die im POST-SERVICES-Audit aufgeworfene Grundsatzfrage ("Ein
Utility-Modul darf nicht allein wegen Netzwerkzugriff als falsch
bewertet werden") stellt sich hier gar nicht mehr in der ursprünglich
angenommenen Schärfe — der Netzwerkzugriff existiert im Code, aber
nicht in der tatsächlichen Abhängigkeits-/Aufrufrichtung des laufenden
Systems.

---

## 10. Duplikationsprüfung

| Befund | Bewertung |
|---|---|
| `fetch_musicbrainz_data()` (tot) vs. `services/clients/musicbrainz_client.py` (aktiv) | **gleiche Funktion doppelt implementiert** (Recording-/Artist-/Release-ID, ISRC) — aber eine Seite ist tot → **potenzieller Aufräum-, kein Duplikations-Laufzeit-Kandidat** |
| `_fetch_lastfm_image()` (tot) vs. `cover_processor.py::_fetch_lastfm()` (aktiv, selbst bereits als Duplikat von `services/clients/lastfm_client.py` bekannt, POST-DUPLICATEENTRY 5.3) | **gleiche Funktion dreifach vorhanden** (identisches JSON-Zugriffsmuster `data.get('artist',{}).get('image',[])`), zwei davon aktiv-duplikativ (bereits bekannt), eine tot | tote Seite: **potenzieller Aufräum-Kandidat**, keine neue Laufzeit-Duplikation |
| `_fetch_musicbrainz_image()` (tot, nutzt Cover Art Archive für *Artist*-Bilder) | kein aktives Gegenstück für *Artist*-Bilder über CAA gefunden (nur `cover_processor.py` für *Release*-Cover) | **bewusst unterschiedliche Funktion** (Artist- vs. Release-Bild) — kein Duplikat, aber auch kein aktiver Nutzen (tot) |
| `normalize_loudness()` (aktiv) vs. `calculate_replaygain()` (tot) | fachlich unterschiedliche Konzepte (destruktive Normalisierung vs. Tag-basiertes ReplayGain), s. Abschnitt 6 | **kein Befund** — bewusst unterschiedliche Funktion, keine Duplikation |
| `write_musicbrainz_tags()` (tot) vs. `tag_writer.py` (aktiv, schreibt bereits `mb_ids` aus dem Genre-Pfad) | wahrscheinlich überlappend, nicht abschließend verifiziert (Tag-Feldnamen-Vergleich außerhalb Scope) | **möglicher, nicht abschließend bestätigter Duplikations-Kandidat** |

**Kein Client-Bypass im aktiven Betrieb.** Alle gefundenen
Duplikationen betreffen ausschließlich toten Code.

---

## 11. Test-/Coverage-Befund

- **Keine dedizierte Testdatei** für `utils/audio_enhancer.py`
  (`find tests -iname "*audio_enhancer*"` → 0 Treffer).
- Zwei Testdateien referenzieren `AudioEnhancer`, aber **beide
  monkeypatchen `normalize_loudness` auf ein No-Op**
  (`staticmethod(lambda *a, **kw: True)`), um echte `ffmpeg`-Aufrufe in
  Tests zu vermeiden:
  - `tests/test_metadata_processor_happy_path.py`
  - `tests/test_autolearn_special_channel_gate.py`
- **Konsequenz:** Der einzige *live* Codepfad (`normalize_loudness`)
  wird in bestehenden Tests **nicht gegen sein reales Verhalten**
  geprüft, sondern durch einen Stub ersetzt — die eigentliche
  `ffmpeg`-Logik (Zwei-Pass-Analyse, Fallback, Temp-Datei-Handling) ist
  **ungetestet**.
- Der gesamte tote Code (ReplayGain, Künstlerbild, MusicBrainz-IDs,
  `enhance_downloaded_file`, `enhance_batch`) ist **vollständig
  ungetestet** — konsistent damit, dass er nie aufgerufen wird.

**Keine Tests verändert oder gelöscht**, wie gefordert.

---

## 12. Abgleich mit dem realen Download-Log

| Log-Zeile | Codefunktion | Modul | Herkunft der Daten |
|---|---|---|---|
| `🔊 1️⃣5️⃣b Normalisiere Lautheit (FFmpeg loudnorm)...` | Log-Statement direkt vor dem Aufruf | `enhanced_metadata_processor.py:790` | — |
| `🔊✅ Loudness normalisiert auf -16.0 LUFS (music)` | f-String mit `_target_lufs`/`_content_type` nach erfolgreichem `AudioEnhancer.normalize_loudness()` | `enhanced_metadata_processor.py:809-812` | `_target_lufs = AudioEnhancer.get_target_lufs("music")` → `-16.0` (aus `TARGET_LUFS`-Dict) |
| `📂 1️⃣6️⃣ Verschiebe Datei in die Bibliothek` | Log-Statement | `enhanced_metadata_processor.py:825` | — |
| `📝 1️⃣7️⃣ Schreibe Metadaten-Tags` | Log-Statement | `enhanced_metadata_processor.py:838` | — |

**Wortlautgenaue Übereinstimmung** zwischen bereitgestelltem Log und
Code bestätigt — kein oberflächlicher Abgleich, sondern Zeilen-
identischer Nachweis im Quellcode. Der Log widerspiegelt exakt den
aktuellen Codefluss, keine Abweichung gefunden.

**"MusicBrainz IDs → kein zweiter MusicBrainz-Aufruf → Cover-Art":**
bestätigt über `_get_mb_id()` (Zeilen 663–667 in
`enhanced_metadata_processor.py`), das die aus dem einmaligen
MusicBrainz-Aufruf während der Genre-Bestimmung (`genre_processor.py`
→ `musicbrainz_client.py`) stammenden IDs aus `track_metadata`/
`_mb_album_prefetch` wiederverwendet, statt erneut abzufragen. Kein
unnötiger Doppelaufruf im aktuellen Codefluss gefunden.

---

## 13. Architekturvarianten

Da ein echter (wenn auch nicht laufzeitkritischer) Befund vorliegt —
tote, mehrfach verantwortliche, teils duplizierte Codeanteile in einem
als einfach dokumentierten Utility-Modul — werden drei Varianten
gebildet:

### Variante A — Toten Code entfernen, `normalize_loudness()`/`get_target_lufs()` bleiben in `utils/`

- **Architekturgewinn:** hoch für Klarheit (Datei schrumpft von ~520
  auf ~100 Zeilen, entspricht dann tatsächlich der CLAUDE.md-Beschreibung
  "netzwerkfrei"). Beseitigt die drei identifizierten latenten
  Duplikationen vollständig.
- **Risiko:** sehr gering für den *aktiven* Pfad (unverändert), aber
  echter Verlust falls die toten Methoden doch irgendwo (z. B. in einem
  nicht gefundenen Skript/Cronjob außerhalb des Python-Repos)
  referenziert werden — laut CLAUDE.md §20 vor Entfernung zu prüfen
  ("Wer benutzt das? Gibt es externe/alte Aufrufer?").
- **Scope:** 1 Datei (`utils/audio_enhancer.py`), keine Aufrufer
  betroffen.
- **Verhaltensänderungsrisiko:** keins für den produktiven Pfad, sofern
  kein externer Aufrufer existiert.
- **Testaufwand:** gering — bestehende 2 Testdateien unverändert
  lauffähig, da sie nur `normalize_loudness` patchen.
- **Abhängigkeiten:** keine.

### Variante B — Datei bleibt unverändert bestehen (Status quo)

- **Architekturgewinn:** keiner.
- **Risiko:** gering, aber **wachsend** — die Duplikation ist eine
  stille Falle: würde jemand künftig `enhance_downloaded_file()` aus
  Unwissenheit aktivieren (z. B. weil sie "vollständiger" aussieht als
  der aktuelle Pfad), entstünde eine echte doppelte MusicBrainz-/
  Last.fm-Anbindung mit doppeltem API-Traffic und potenziell
  widersprüchlichen Ergebnissen.
- **Scope:** keiner.
- **Testaufwand:** keiner.

### Variante C — Aufteilung: Loudness bleibt `utils/`, tote Netzwerk-Methoden vollständig nach `services/clients/`/`services/metadata/` migrieren und reaktivieren

- **Architekturgewinn:** hoch, *falls* die toten Fähigkeiten (z. B.
  ReplayGain-Tags, Artist-Bilder über CAA) tatsächlich fachlich
  gewünscht sind — aber das ist eine **Produktentscheidung**, keine
  reine Architekturfrage.
- **Risiko:** am höchsten — echte Verhaltensänderung (neue Tags, neue
  Bilder, neue API-Calls im Produktivbetrieb), erfordert laut CLAUDE.md
  §6 vollständige Characterization/Tests, bevor irgendetwas aktiviert
  wird.
- **Scope:** groß — neue Consumer-Verdrahtung in
  `enhanced_metadata_processor.py`, möglicherweise neue Client-Methoden,
  Klärung der Tag-Feld-Überschneidung mit `tag_writer.py`.
- **Testaufwand:** hoch.
- **Abhängigkeiten:** würde die bereits bekannte Last.fm-Duplikation
  (POST-DUPLICATEENTRY 5.3) mit adressieren müssen, um nicht eine
  vierte parallele Last.fm-Implementierung zu schaffen.

---

## 14. Risikoanalyse

| Variante | Risiko | Aufwand | Nutzen |
|---|---|---|---|
| A (toten Code entfernen) | sehr gering | gering | hoch (Klarheit, Doku-Korrektheit, Duplikationsbeseitigung) |
| B (nichts tun) | gering, aber latent wachsend | keiner | keiner |
| C (Fähigkeiten reaktivieren + verschieben) | hoch | hoch | abhängig von einer externen Produktentscheidung, nicht rein architektonisch |

---

## 15. Empfehlung

**Empfehlung für eine mögliche ARCH-017 Phase 2 (keine Umsetzung in
dieser Phase):** Variante A (toten Code entfernen, `normalize_loudness`/
`get_target_lufs` bleiben unverändert in `utils/`) ist die einzige
Variante, die einen Architekturgewinn ohne Verhaltensrisiko bietet.
Bevor dies umgesetzt wird, sollte laut CLAUDE.md §20 zunächst verifiziert
werden, dass wirklich **kein** externer/alter Aufrufer existiert (z. B.
Wartungsskripte außerhalb der regulären Pipeline) — im Rahmen dieses
Audits wurde nur der Python-Code des Repositories durchsucht.

Variante C ist **nicht** als nächster Schritt empfohlen — sie ist keine
reine Architekturbereinigung, sondern würde neue, aktuell inaktive
Fachfunktionalität reaktivieren, was eine bewusste Produktentscheidung
außerhalb des Scopes eines Architektur-Audits erfordert.

Dies ist eine **Empfehlung, keine Entscheidung**.

---

## 16. Entscheidungsgate

**ERGEBNIS B** — Relevanter Architektur-/Verantwortungsbefund vorhanden
(tote, mehrfach verantwortliche, teilweise duplizierte Codeanteile in
`utils/audio_enhancer.py`), aber eine Umsetzung erfordert zunächst eine
eigene, ausdrücklich freigegebene Entscheidungsphase — insbesondere die
in CLAUDE.md §20 geforderte Verifikation, dass keine externen Aufrufer
existieren, bevor irgendetwas entfernt wird.

**Nicht ERGEBNIS A:** Es liegt mehr vor als nur ungenaue Dokumentation
— die Datei bündelt tatsächlich mehrere, fachlich nicht
zusammengehörige, größtenteils tote Verantwortlichkeiten, von denen
drei nachweislich bereits anderswo im Projekt aktiv und funktionsfähig
abgedeckt sind.

**Nicht ERGEBNIS C:** Es gibt einen konkreten, belegten Kandidaten
(Variante A) mit sehr geringem Risiko und klarem Nutzen — anders als
in einer reinen "kein Kandidat"-Situation.

---

**ARCH-017 Phase 1 — Characterization abgeschlossen.**
**Keine Produktionsänderung durchgeführt.**
**Keine YAML-Änderung durchgeführt.**
**Keine Entscheidung über eine Umsetzung erzwungen.**
**STOPP.**
**Warte auf ausdrückliche Freigabe für eine mögliche Phase 2.**
