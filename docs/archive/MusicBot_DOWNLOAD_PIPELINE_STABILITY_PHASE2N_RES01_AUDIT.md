# MusicBot — Download Pipeline Stability Phase — PHASE 2N: RES-01

> Analyse- und Entscheidungs-Dokumentation für RES-01. Basis:
> `docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md` (Finding
> erstmals identifiziert). Im Gegensatz zu den vorangegangenen PHASE-2-
> Dokumenten enthält diese Phase **keinen Code-Fix** — das Ergebnis ist
> eine bewusste, dokumentierte Design-Entscheidung.

**Status: RES-01 — ANALYSIERT, BEWUSST NICHT BEHOBEN (akzeptiert)**

---

## 1. Finding (aus PHASE 0)

**ID:** RES-01 — P2 — `is_duplicate`-Flag ist prozesslebensdauer-gebunden
(Singleton `processed_titles`), nicht session-/batch-begrenzt.

**Datei/Funktion:**
`services/metadata/enhanced_metadata_processor.py::EnhancedMetadataProcessor`.

**Root Cause:** `EnhancedMetadataProcessor` ist ein `SingletonMixin`,
`self.processed_titles: set = set()` wird in `_do_init()` (Zeile 142)
angelegt — da `_do_init()` durch den Singleton-Mechanismus nachweislich nur
einmal ausgeführt wird, existiert genau eine `processed_titles`-Menge für
die gesamte Prozesslaufzeit des Bots. `process_single_track()` (Zeile
506-511) prüft `title_key = f"{artist}|{title}".lower()` gegen diese Menge,
setzt `is_duplicate` entsprechend und fügt den Schlüssel **immer** hinzu —
über alle Nutzer, Chats und unabhängigen Downloads hinweg, nie
zurückgesetzt. `reset_statistics()` (Zeile 185-188) würde
`processed_titles.clear()` aufrufen, wird aber nirgends in Produktionscode
tatsächlich aufgerufen (verifiziert per Grep).

---

## 2. Präzisierung der tatsächlichen Auswirkung (wichtige Korrektur)

Eine frühere Zwischenbewertung in dieser Arbeitsphase hatte angenommen,
`is_duplicate` fließe bis in die an den Telegram-Nutzer gesendete
Erfolgsmeldung durch. Das wurde bei der Read-Only-Analyse dieser Phase
**widerlegt** und ausdrücklich richtiggestellt:

- `klassen/download_handler.py::_fmt_result()` (einzige Stelle mit einem
  Nutzer-lesbaren „⚠️ JA"/„✅ nein"-Duplikat-Label) ist **toter Code** —
  repoweit verifiziert, wird nirgends aufgerufen.
- `services/downloader/download/formatters.py::ProgressFormatter.track_result_block()`/
  `stats_table()` (enthalten `is_duplicate`/`duplicate_tracks`) werden
  ausschließlich über `logger.info(...)` ausgegeben — serverseitiges Log,
  nicht Telegram.
- `services/downloader/download_result_reporter.py` — die tatsächliche
  Quelle der an Telegram gesendeten Zusammenfassungsnachrichten
  (`build_final_summary_message()`/`build_playlist_summary_message()`) —
  referenziert `is_duplicate` an keiner Stelle (verifiziert per Grep, null
  Treffer).
- `services/metadata/cache.py:165` persistiert `is_duplicate` als Feld im
  on-disk Metadata-Cache-Eintrag — inspizierbar, aber nirgends aktiv
  ausgewertet oder angezeigt.

**Tatsächliche Auswirkung:** kein Datenverlust, keine übersprungene
Verarbeitung, **kein für den Telegram-Nutzer sichtbarer Effekt** —
ausschließlich ein serverseitiges Log-/Statistik-Artefakt (`bot.log`-Zeile
„🔄 Duplikat: …", `processing_stats.duplicate_tracks`-Zähler, `is_duplicate`-
Feld im Metadata-Cache-Eintrag).

---

## 3. Bestehende Testabdeckung

`is_duplicate` wird in mehreren Tests als Einzelaufruf-Feld geprüft
(`test_metadata_processor_happy_path.py`, `test_metadata_result_translator.py`,
`test_download_utils_metadata_translation.py`, `test_formatters.py`,
`test_download_handler_process_single_download_result.py`,
`test_download_handler_playlist_duplicate_registration.py`) — kein Test
prüft das eigentliche RES-01-Szenario (zwei unabhängige, aufeinander-
folgende Aufrufe auf derselben Singleton-Instanz). Testlücke bestätigt,
aber angesichts der Entscheidung in Abschnitt 4 nicht zu schließen.

---

## 4. Entscheidung

**Option A — bewusst belassen.** `processed_titles` bleibt wie bisher
prozessweit persistent, ohne automatischen Reset. Von zwei erwogenen
Optionen (A: belassen: B: Reset pro Playlist-/Batch-Lauf) wurde A gewählt,
nachdem Abschnitt 2 gezeigt hat, dass keine Korrektheits- oder
Nutzer-Sichtbarkeitsgefahr besteht — der Aufwand für einen Reset-Mechanismus
(Option B) stünde in keinem Verhältnis zum rein internen Nutzen des
Signals.

**Begründung:**
- Kein Datenverlust, keine übersprungene Verarbeitung.
- Kein für den Endnutzer sichtbarer Effekt (Abschnitt 2).
- Einzige Konsequenz: `processing_stats.duplicate_tracks` zählt „Duplikate"
  prozessweit statt pro Download-Lauf — eine Ungenauigkeit in einer rein
  internen Debug-/Log-Statistik, kein funktionaler Fehler.
- Ein dritter, ursprünglich erwogener Ansatz (TTL-/zeitbasierter Reset)
  wurde als unverhältnismäßig komplex für den tatsächlichen Nutzen
  verworfen.

**Keine Codeänderung.** `EnhancedMetadataProcessor`, `processed_titles`,
`reset_statistics()` bleiben unverändert.

---

## 5. Abschluss

RES-01 gilt hiermit als **analysiert und bewusst als akzeptiertes
Verhalten dokumentiert** — kein offener P2-Fix-Kandidat mehr, ähnlich der
Einstufung von DL-04 (bewusste Alt-Entscheidung) und DUP-05 (akzeptiertes
Risiko). Sollte sich die tatsächliche Auswirkung künftig ändern (z. B. durch
eine neue Funktion, die `is_duplicate` doch nutzerseitig sichtbar macht),
ist diese Entscheidung neu zu bewerten. Der Gesamtstatus der übergeordneten
`docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md` bleibt **PLANNED**.
