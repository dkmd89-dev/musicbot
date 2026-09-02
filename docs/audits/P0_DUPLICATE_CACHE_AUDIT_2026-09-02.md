# P0-F: Duplicate Cache (`services/duplicate/cache.py`)

**Datum:** 2026-09-02
**Phase:** P0-F der laufenden P0-Metadata/Genre/Artist-Mapping/Duplicate-Detection-Reihe
(Branch `audit/p0-metadata-duplicate-detection`) — letzter fachlicher
Schritt vor dem abschließenden Gesamt-Audit.
**Scope:** `services/duplicate/cache.py` (`DuplicateCache`, 301 Zeilen,
vollständig gelesen).

## Zusammenfassung

Konkreter, bewiesener Bug gefunden und gefixt: `_normalize_url_for_cache()`
erkannte `youtube.com/shorts/<id>` nicht als dieselbe Video-ID wie
`watch?v=<id>`/`youtu.be/<id>` — genau der eingangs im P0-Plan vermutete
Punkt. `_save_caches()`/`add_entry()`/`get_content_hash()`/
`cleanup_old_entries()` verhalten sich wie dokumentiert, keine weiteren
P0-relevanten Funde.

## 1. Bestätigter Fund: `/shorts/<id>` nicht als YouTube-Video-URL erkannt

`_normalize_url_for_cache()` erkannte vor dem Fix drei URL-Formen explizit
als dieselbe Video-ID (`youtube_video:<id>`): `youtube.com/watch?v=<id>`,
`youtu.be/<id>`, sowie implizit über einfaches Teilstring-Matching auch
`m.youtube.com/watch?v=<id>` und `music.youtube.com/watch?v=<id>` (beide
enthalten den Teilstring `"youtube.com/watch"` und wurden dadurch bereits
vor dem Fix korrekt erfasst — kein eigener Fund nötig).

`youtube.com/shorts/<id>` fiel dagegen in den generischen
`netloc+path`-Zweig und ergab einen komplett anderen, nicht mit der
watch-Form vergleichbaren Schlüssel. Live verifiziert (vor dem Fix):

| URL | normalisierter Schlüssel |
|---|---|
| `youtube.com/watch?v=dQw4w9WgXcQ` | `youtube_video:dQw4w9WgXcQ` |
| `youtube.com/shorts/dQw4w9WgXcQ` | `www.youtube.com/shorts/dQw4w9WgXcQ` |

Praktische Konsequenz: ein als Short erneut hochgeladener/geteilter Song,
der bereits unter seiner regulären `watch?v=`-URL registriert war, wurde
von der URL-Ebene der Duplicate-Detection **nicht** erkannt (die
Content-Hash-Ebene als zweite Schutzschicht hätte je nach Artist/Titel-
Übereinstimmung ggf. noch gegriffen — aber die erste, günstigste Ebene
versagte). Shorts sind ein inzwischen sehr verbreitetes YouTube-Format,
daher eine reale, nicht nur theoretische Lücke.

### Fix (umgesetzt)

Neuer `elif`-Zweig für `"youtube.com/shorts/" in url`, analog zu den
bestehenden `watch`/`youtu.be`-Zweigen: Video-ID ist der Pfad-Abschnitt
nach `/shorts/`, ein eventueller Query-String (z. B. `?feature=share`)
spielt dabei keine Rolle (von `urlparse()` bereits von `path` getrennt).

```python
elif "youtube.com/shorts/" in url:
    video_id = parsed_url.path.rsplit("/shorts/", 1)[-1].strip("/")
    return f"youtube_video:{video_id}" if video_id else f"youtube_video:{url}"
```

Live nach dem Fix verifiziert: `shorts/<id>` und `watch?v=<id>` ergeben
jetzt identische Schlüssel; ein Query-String am Short-Link stört nicht.

**Pre-Fix-Diskriminierung:** die 3 neuen Tests in
`tests/test_duplicate_handler.py::TestShortsUrlNormalization` liefen vor
dem Fix nachweislich fehl (3 failed), mit dem Fix alle grün.

### Bewusst außerhalb des Scopes: `/embed/<id>`, `/live/<id>`

Beide bleiben unverändert im generischen `netloc+path`-Zweig. Für einen
manuell in Telegram eingefügten Link sind `/embed/`-URLs (typischerweise
nur in eingebetteten Playern verwendet, nicht zum Teilen) und
`/live/`-URLs (Livestreams, nicht sinnvoll als abgeschlossener Song-
Download) deutlich unwahrscheinlicher als Nutzereingabe als `/shorts/`
— keine Evidenz für reale Auswirkung, daher nicht mitgefixt (Regel 9:
keine Änderung ohne konkreten Anlass; kann bei Bedarf als eigener,
separat begründeter Mini-Fix nachgezogen werden).

## 2. Sonstige geprüfte Bereiche — keine weiteren Funde

- `_save_caches()`/`_write_json_atomic()`: atomarer Schreibvorgang
  (write-tmp + rename) bereits durch INV-02 abgesichert, Kommentar im Code
  erklärt bewusst offen gelassene Event-Loop-Blockierung — nachvollziehbar
  begründet, kein neuer Fund.
- `get_content_hash()`: einfache, deterministische Lowercase-Verkettung —
  verhält sich wie von P0-E's Fix vorausgesetzt (siehe dortiger Fix, der
  sich auf konsistentes Lowercasing verlässt).
- `cleanup_old_entries()`: entfernt Einträge in beiden Caches unabhängig
  nach `download_date`, speichert nur bei tatsächlichen Änderungen — keine
  Auffälligkeit.

## 3. Beobachtungen ohne Fix (Statistik-Genauigkeit, kein Korrektheits-Risiko)

Zwei kleinere Inkonsistenzen bei `duplicate_count`, **nicht** vertieft
(betreffen nur die Genauigkeit einer Statistik-Zahl, nicht die
Korrektheit der eigentlichen Duplikat-Erkennung — kein P0-Kriterium
verletzt):

- `check_url_duplicate()` erhöht `duplicate_count` bei jedem Treffer direkt
  im Speicher, ruft danach aber **kein** `_save_caches()` auf — der
  erhöhte Zähler wird erst persistiert, wenn ohnehin ein anderer Pfad
  (`add_entry()`/`cleanup_old_entries()`/`invalidate_entry()`) als
  Nächstes speichert. Bei einem Prozess-Neustart dazwischen geht die
  Erhöhung verloren.
- `check_content_duplicate()` erhöht `duplicate_count` bei einem Treffer
  überhaupt **nicht** (Asymmetrie zu `check_url_duplicate()`).

Beide könnten in einem späteren, eigenen Mini-Fix vereinheitlicht werden,
falls die `duplicate_count`-Statistik für den Nutzer sichtbar/relevant
genug ist, um das zu rechtfertigen — hier bewusst nicht mitgemacht, um den
Scope dieses P0-F-Schritts nicht unkontrolliert zu erweitern.

## Tests

- Neu: `tests/test_duplicate_handler.py::TestShortsUrlNormalization`
  (3 Tests). Pre-Fix-Diskriminierung: 3 failed vor dem Fix, 3 passed
  danach.
- Gezielt: `tests/test_duplicate_handler.py` — 17 passed.
- Direkte Regression: + `tests/test_duplicate_detector_hash_consistency.py`
  + `tests/test_artist_normalization_duplicate_detector_comparison.py` —
  zusammen 31 passed.
- Thematisch: `pytest tests/ -q -k duplicate` — 301 passed (298 + 3 neu),
  1 skipped (umgebungsbedingt, vorbestehend), keine Regression.
- Produktionscode-Änderung: `services/duplicate/cache.py::
  _normalize_url_for_cache()` (siehe Abschnitt 1).
