# ARCH-005 — Temp-Cleanup: Analyse, Strategie, Umsetzung

Folgeentscheidung aus ARCH-003/P-1 (`FileUtils` entfernt, siehe
`docs/archive/arch/MusicBot_ARCH-003_Services_Phase1_Analyse.md`): `clean_temp_files()`
lief nie, unbegrenztes Wachstum von `Config.DOWNLOAD_DIR` war ein
dokumentiertes, unbehobenes operationelles Risiko. Diese Analyse klärt das
Problem konkret und legt die Umsetzung fest.

---

## 1. Klärungsfragen

**Was sollte `clean_temp_files()` ursprünglich löschen?**
Laut der jetzt entfernten Implementierung (`services/downloader/utils/file_utils.py`,
siehe ARCH-003): alle Dateien älter als 1 Stunde in einem übergebenen
Verzeichnis (Default `Config.DOWNLOAD_DIR`), unabhängig von Dateityp oder
Namen — ein reiner, ungefilterter Alters-Sweep.

**Welches Verzeichnis ist betroffen?**
`Config.DOWNLOAD_DIR`. `Config.TEMP_DIR` existiert zwar als Config-Wert,
hat aber repo-weit (per Grep verifiziert) keine einzige echte
Datei-Operation — wird daher bewusst **nicht** mitbereinigt.

**Welche Dateien und Altersgrenzen waren vorgesehen?**
Alle Dateitypen, 1 Stunde — siehe oben. Diese Grenze wird in ARCH-005
**nicht** übernommen (siehe Abschnitt 3).

**Wird während Downloads parallel in dieses Verzeichnis geschrieben?**
Ja. `DOWNLOAD_DIR` wird von allen drei Pipelines (YouTube-Playlist,
YouTube-Single, Spotify) gemeinsam genutzt — verifiziert über
`spotify_downloader.py:108`, wo ein bereits vorhandener Kommentar aus
einer früheren Session (BUG-004-Fix) explizit bestätigt: `Config.SPOTIFY_DOWNLOAD_DIR`
existiert, wird aber nie verwendet; Spotify lädt real in dasselbe
`DOWNLOAD_DIR` wie YouTube. Bei mehreren gleichzeitigen Downloads
(`MAX_CONCURRENT_DOWNLOADS`) können somit mehrere Downloads gleichzeitig in
dasselbe Verzeichnis schreiben.

**Könnte ein laufender Download durch Cleanup gelöscht werden?**
Bei einem reinen Alters-Sweep während des laufenden Betriebs: ja,
theoretisch (ein sehr langsamer Download könnte eine `.part`-Datei über
der Altersgrenze erzeugen). Deshalb: keine periodische Hintergrundbereinigung
(Option B) in diesem Schritt, und die Start-Variante läuft nur, wenn
garantiert kein Download aktiv ist (siehe Abschnitt 3).

**Wer sollte den Cleanup auslösen?**
Zwei Auslöser, siehe Abschnitt 3: primär die konkrete Fehlerstelle
(Strategie C), als Fallback der Bot-Start (Strategie A). Explizit
**nicht** in diesem Schritt: periodisch während des Betriebs (Option B) —
das eigentliche Sicherheitsproblem eines Alters-Sweeps neben aktiven
Downloads bleibt so von vornherein ausgeschlossen, statt es über
Zeitfenster-Heuristiken zu entschärfen.

**Welche Dateien/Verzeichnisse dürfen niemals gelöscht werden?**
- `.part`/`.ytdl`-Dateien (yt-dlp-Teildateien laufender Downloads) — in
  keiner der beiden Strategien Ziel eines Löschvorgangs, unabhängig vom
  Alter.
- Alles außerhalb `Config.DOWNLOAD_DIR` (Pfad-Guard in beiden Strategien).
- Unterverzeichnisse (nicht rekursiv).
- Dateien mit unbekannter Endung (Whitelist-Ansatz in Strategie A).

---

## 2. Sicherheitsbewertung der ursprünglichen Implementierung

Die alte `clean_temp_files()`-Logik hatte drei Schwächen, die eine direkte
Reaktivierung ausschlossen:

1. **Kein Dateityp-Filter** — jede Datei im Verzeichnis war Ziel, auch
   fremde/unbekannte.
2. **1h-Grenze ohne Bezug zur tatsächlichen Downloaddauer** — willkürlich
   gewählt, nicht aus dem realen Pipeline-Verhalten abgeleitet.
3. **Kein Unterschied zwischen "abgeschlossen, aber verwaist" und
   "gerade aktiv"** — ein reiner Alters-Sweep kann strukturell nicht
   zwischen einer hängenden `.part`-Datei und einem echten Best liegen
   gebliebenen Rest unterscheiden.

Der Name `clean_temp_files()` war zusätzlich irreführend (suggeriert
`TEMP_DIR`, betraf aber `DOWNLOAD_DIR`) — neuer Name:
**`cleanup_download_artifacts()`** (Strategie A) bzw.
**`cleanup_single_download_artifact()`** (Strategie C), in neuem Modul
`services/downloader/utils/download_artifact_cleanup.py`.

---

## 3. Gewählte Strategie

### Strategie C (primär) — Cleanup im Fehlerpfad

**Zentraler Befund:** alle drei Aufrufer (YT-Playlist, YT-Single, Spotify)
laufen durch **eine einzige** Methode:
`EnhancedMetadataProcessor.process_single_track()`
(`services/downloader/utils/enhanced_metadata_processor.py`). Verifiziert:
der gesamte Verarbeitungskörper liegt in einem `try`-Block mit einem
äußeren `except Exception` — keine "weichen"
`return MetadataResult(success=False)`-Stellen dazwischen, nur zwei
`raise`-Statements (fehlender `filepath`-Key, Quelldatei nicht gefunden),
die beide dort landen. Das ist der einzige Ort, an dem garantiert jeder
Fehlerfall ankommt — ein zentraler Hook deckt somit alle drei Pipelines ab.

**Umsetzung:**
- `original_path` (vorher erst bei Schritt 14 gebunden) wird jetzt vor dem
  `try`-Block mit `None` vorinitialisiert.
- Im `except`-Block: `cleanup_single_download_artifact(original_path, DOWNLOAD_DIR, logger)`.

**Sicherheitsregeln (`cleanup_single_download_artifact`):**
- No-op, wenn `original_path` oder `download_dir` `None` ist.
- No-op, wenn `original_path` nicht mehr existiert — deckt automatisch den
  Fall ab, dass `move_to_library()` vor dem Fehler bereits gelaufen ist
  (Datei existiert am alten Pfad dann nicht mehr, kein zusätzlicher Schutz
  nötig).
- No-op, wenn `original_path` außerhalb `download_dir` liegt (Pfad-Guard
  via `resolve().relative_to(...)`).
- Zugehörige `.info.json` (yt-dlp `writeinfojson`) wird mit entfernt, falls
  vorhanden.
- Der Cleanup selbst hat ein eigenes inneres `try/except` — ein
  Cleanup-Fehler darf die eigentliche Fehlermeldung des Aufrufers nie
  verdecken, wird nur als Warning geloggt.

**Bewusst nicht durch Strategie C abgedeckt:** ein Fehlschlag, bevor
`process_single_track()` überhaupt aufgerufen wird (der yt-dlp-Download
selbst scheitert, z. B. Netzwerkfehler) — dort existiert noch keine
Zuordnung `track_metadata["filepath"]`. Dafür ist Strategie A da.

### Strategie A (Fallback) — Start-Cleanup

**Zeitpunkt:** `bot.py`, nach Config-Laden, vor `bot_runner.initialize()`
— zu diesem Zeitpunkt kann laut Codefluss kein Download aktiv sein (der
Bot verarbeitet erst nach `start_polling()` Telegram-Updates).

**Sicherheitsregeln (`cleanup_download_artifacts`):**
- Nur direkte Kinder von `Config.DOWNLOAD_DIR`, nicht rekursiv,
  Unterverzeichnisse werden übersprungen.
- Dateityp-Whitelist statt Namens-Pattern (Single-Downloads haben freie
  Videotitel, kein zuverlässiges Namensschema — die Endung ist der
  verlässliche Filter): `.m4a .mp3 .webm .opus .info.json .jpg .webp`.
- **`.part`/`.ytdl`-Dateien werden nie gelöscht**, unabhängig vom Alter —
  explizite Nutzeranforderung. Das Kernrisiko (fertige, aber nie
  verschobene Dateien) ist bereits über die Endungs-Whitelist abgedeckt;
  der Zusatznutzen eines `.part`-Cleanups wäre gering, das Risiko unnötig.
- Altersgrenze: **24 Stunden** (Default-Parameter `max_age_hours=24.0`) —
  deutlich konservativer als die alte 1h-Grenze. Downloads dauern laut
  Codeanalyse Sekunden bis niedrige Minuten; 24h ist ein großzügiger
  Sicherheitsabstand, deckt aber trotzdem langfristig liegen gebliebene
  Reste zuverlässig ab.
- Fehler beim Löschen einzelner Dateien werden nur geloggt, der Sweep läuft
  für die restlichen Dateien weiter.

### Explizit nicht umgesetzt: Option B (periodische Hintergrundbereinigung)

War nie Teil dieses Schritts (Nutzervorgabe). Strategie C deckt den
Hauptfall ab (Metadatenverarbeitung schlägt nach erfolgreichem Download
fehl); Strategie A deckt den Rest beim nächsten Neustart ab. Eine
periodische Bereinigung während des laufenden Betriebs würde das in
Abschnitt 1 beschriebene Risiko (Kollision mit aktiven Downloads) wieder
einführen und wurde bewusst nicht in Betracht gezogen.

---

## 4. Umsetzung

**Neue Datei:** `services/downloader/utils/download_artifact_cleanup.py`
— zwei Funktionen, `cleanup_single_download_artifact()` (Strategie C) und
`cleanup_download_artifacts()` (Strategie A), siehe Abschnitt 3.

**Wiring:**
- `services/downloader/utils/enhanced_metadata_processor.py::process_single_track()`
  — `original_path` vorinitialisiert, Cleanup-Aufruf im äußeren
  `except`-Block. `DOWNLOAD_DIR` wird defensiv über
  `getattr(self.config, "DOWNLOAD_DIR", None)` gelesen (nicht jeder
  Config-Fake in Tests hat dieses Attribut — `cleanup_single_download_artifact`
  behandelt `None` als No-op).
- `bot.py` — `cleanup_download_artifacts(config.DOWNLOAD_DIR, logger)` vor
  `bot_runner.initialize()`, in eigenem `try/except` (ein
  Cleanup-Fehschlag darf den Bot-Start nicht verhindern).

**Tests:**
- `tests/test_download_artifact_cleanup.py` (neu, 18 Tests) — isolierte
  Unit-Tests für beide Funktionen: Sicherheitsguards (`None`-Pfade,
  Pfad-außerhalb-`download_dir`, bereits verschobene Datei),
  `.info.json`-Mitlöschung, `.part`/`.ytdl`-Ausschluss auch bei hohem
  Alter, Endungs-Whitelist, Default-Altersgrenze von 24h, Fehlerbehandlung
  ohne Exception-Propagation.
- `tests/test_metadata_processor_happy_path.py` (erweitert, 2 neue Tests)
  — End-to-End über die echte `EnhancedMetadataProcessor`-Pipeline:
  `test_error_after_move_to_library_cleans_up_orphaned_source_file`
  (erzwingt einen `move_to_library()`-Fehler nach Schritt 14, verifiziert
  dass die verwaiste Quelldatei danach entfernt ist) und
  `test_missing_filepath_error_does_not_crash_cleanup` (Fehler vor Schritt
  14, `original_path` bleibt `None`, Cleanup-Aufruf ist ein sauberer
  No-op). `HappyPathConfig` um `DOWNLOAD_DIR` erweitert (additiv, kein
  bestehender Test betroffen).

**Regressionslauf:** 1005 bestanden (vorher 985 — Differenz von 20
entspricht genau den neuen Tests), unverändert 15 bekannte
Vorbestand-Fehler.

---

## 5. Verbleibende Risiken / bewusst nicht adressiert

- Periodische Hintergrundbereinigung (Option B) — bewusst nicht Teil
  dieses Schritts.
- Ein Fehlschlag *innerhalb* des yt-dlp-Downloads selbst (vor
  `process_single_track()`) hinterlässt ggf. `.part`-Reste, die von
  Strategie C nicht erreicht werden — Strategie A räumt sie beim nächsten
  Bot-Start nicht auf (bewusster Ausschluss von `.part`/`.ytdl`), sondern
  lässt sie liegen, bis eine bewusste, separate Entscheidung dafür fällt.
- Falls der Bot-Prozess während eines aktiven Downloads hart abstürzt
  (SIGKILL, OOM) und beim nächsten Start weniger als 24h vergangen sind,
  bleiben die Reste bis zur nächsten Start-Cleanup-Gelegenheit liegen —
  akzeptiertes Verhalten, da die Alternative (kürzere Grenze) das Risiko
  einer Fehllöschung erhöhen würde.
