# MusicBot — Download Pipeline Stability Phase — PHASE 2I: Test-Environment Diagnostic & Confirmation

> Diagnose- und Bestätigungsphase, ausgelöst durch die im
> PHASE-2H-Abschlussbericht offen gelassene Beobachtung, dass ein
> Downloadlauf sich in der separaten Testumgebung (`run_test_bot.py`)
> zunächst nicht reproduzieren ließ, obwohl der Produktionslauf (`bot.py`)
> und alle DL-06-Regressionstests bereits erfolgreich waren.

**Status: PHASE 2I — ABGESCHLOSSEN**

---

## 1. Root Cause

**Kein Code-Bug in der Download-Pipeline.** Test- und Produktionsumgebung
verwenden zwei vollständig eigenständige Telegram-Bot-Accounts:

```
.env: BOT_TOKEN=<Produktions-Token>            → Produktions-Bot
.env: TEST_TELEGRAM_TOKEN=<Test-Token>         → @dkmd_test_bot
```

Beide Tokens wurden verifiziert unterschiedlich (unterschiedliche Länge-
/Präfix-Struktur, unterschiedliche Bot-IDs). Telegram routet eingehende
Nachrichten strikt pro Bot-Account — eine Nachricht an den gewohnten
Produktions-Bot erreicht den auf `TEST_TELEGRAM_TOKEN` pollenden
Testbot-Prozess grundsätzlich nie, unabhängig von der Korrektheit des
Codes. Vollständige Kontrollfluss-Analyse (Handler-Registrierung,
Config-Swap via `sys.modules['config']`, `get_config()`-Auflösung,
URL-Dispatch-Regex, Duplicate-/Download-Handler-Erzeugung) ergab an keiner
Stelle eine strukturelle Divergenz zwischen Test- und Produktionspfad.

---

## 2. Fix

**Datei:** `run_test_bot.py` (mit expliziter Nutzerfreigabe für diese
eine, sonst als extern/unangetastet behandelte Datei).

Beim Start ruft das Skript jetzt zusätzlich `getMe()` der Telegram Bot API
ab und gibt den tatsächlichen `@username` des Bot-Accounts aus, mit dem
die Testumgebung läuft:

```
🚀 Starte Test-Bot mit isolierter Konfiguration...
   Library: /tmp/musicbot_test/library
   Token:   xxxxxxxxxx... (gekürzt)
   Bot:     @dkmd_test_bot  ← DIESEN Bot-Account in Telegram anschreiben!
```

Live gegen die echte Telegram Bot API verifiziert (`getMe()` erfolgreich,
`ok: True`, `username: dkmd_test_bot`) — rein diagnostisch, keine
funktionale Änderung an der Download-Pipeline.

---

## 3. Live-Bestätigung — Single-Track

Nach Anschreiben von `@dkmd_test_bot` (statt des Produktions-Bots) lief
ein realer Single-Track-Download vollständig durch:

```
10:03:54 /start von User 490171109 (Dkmd89)
10:05:02 Verarbeite YouTube-URL: https://youtu.be/tJUfGL8XNHY...
10:05:07 Kein Duplikat — Download wird fortgesetzt
10:05:20 [DL] Single-Download erfolgreich
10:06:12 [META] Single-Track erfolgreich verarbeitet
10:06:12 [SUCCESS] Single-Track abgeschlossen: 'Ski Aggu - ÜBERRASCHUNG'
10:06:12 [SUCCESS] Im Duplikat-Cache registriert
```

Vollständige Kette bestätigt: Telegram → DownloadHandler → Duplikatprüfung
→ yt-dlp → Postprocessing → MusicBrainz → Lyrics → Cover → Loudness →
`move_to_library()` → TagWriter → DuplicateCache → Telegram-Erfolgsmeldung.
Dieser Lauf durchlief `_process_single_download()` (DL-02/DL-01-Codepfad),
nicht `download_single_track()` (DL-06) — dafür siehe Abschnitt 4.

---

## 4. Live-Bestätigung — Playlist (DL-06 Erfolgspfad)

Anschließender Playlist-Download über `@dkmd_test_bot`:

```
10:22:35 [DOWNLOAD_UTILS] Playlist erkannt
[TRACK 01/05] ... [TRACK 05/05]
10:27:36 [DOWNLOAD_UTILS] ✅ [RETRY 1] Playlist fertig: 5/5 Tracks
```

Alle 5 Tracks (Intro, Magnum, vor der Polizei, SKYR, Outro) erfolgreich
verarbeitet und einzeln im DuplicateCache registriert
(`[PLAYLIST] Im Duplikat-Cache registriert: ...` je Track — bestätigt die
DUP-01/DUP-08-Fix-Logik `_register_playlist_track_duplicates()` live).

Damit hat dieser Lauf real `DownloadExecutor.download_single_track()`
durchlaufen — genau den von DL-06 abgesicherten Codepfad. Da alle 5
Tracks erfolgreich waren, wurde der DL-06-Cleanup-Zweig dabei nicht
ausgelöst; das bestätigt den **Erfolgspfad** live (kein `.exists()`-
verwaistes Artefakt, korrekte Rückgabewerte, keine Regression).

**Beobachtete, unkritische Nebenbefunde (kein DL-06-Bezug, nicht
untersucht/behoben):**
- 2 von 5 Tracks erhielten einen `MusicBrainz TimeoutError`
  (`async_timeout`, `Config.MUSICBRAINZ_TIMEOUT`) — bereits etabliertes,
  fehlertolerantes Verhalten (MusicBrainz ist optionaler Metadaten-
  Schritt, Out-of-Scope für diese Phase); betroffene Tracks liefen über
  Fallback-Quellen trotzdem erfolgreich durch.
- Die Zeile `⚠️ Duplikat-Registrierung übersprungen (artist='?',
  title='Playlist')` ist **kein Bug**, sondern der bereits bestehende,
  harmlose No-op-Aufruf auf dem Playlist-Wrapper selbst (erscheint nach
  allen 5 erfolgreichen Einzel-Registrierungen).

---

## 5. Absicherung des Fehler-/Cleanup-Pfads

Der Playlist-Testlauf war ein vollständiger Erfolgsfall — der
DL-06-Cleanup-Pfad (Reaktion auf einen tatsächlich fehlschlagenden
yt-dlp-/FFmpeg-Aufruf) wurde dadurch **nicht live ausgelöst**. Das ist
**kein Freigabehindernis** und wurde in dieser Phase bewusst **nicht**
künstlich provoziert (kein absichtliches Herbeiführen eines Downloadfehlers
in der Live-Umgebung). Dieser Pfad ist bereits vollständig und gezielt
durch die 7 dedizierten Regressionstests aus PHASE 2G abgesichert
(`tests/test_download_executor_playlist_track_cleanup.py`), inklusive
Vor-Fix-Diskriminierung (5 von 7 Tests schlagen nachweislich am
ungefixten Code fehl) und unabhängig reproduzierter Verifikation in
PHASE 2H.

---

## 6. Zusammenfassung

| Bereich | Status |
|---|---|
| Root Cause Testumgebung | Identifiziert: separater Bot-Account, kein Code-Bug |
| Fix (`run_test_bot.py`) | Umgesetzt, live verifiziert |
| Single-Track-E2E (Testumgebung) | Erfolgreich |
| Playlist-E2E / DL-06-Erfolgspfad (Testumgebung) | Erfolgreich |
| DL-06-Fehler-/Cleanup-Pfad | Bereits durch 7 Regressionstests abgesichert (PHASE 2G/2H), in dieser Phase nicht künstlich provoziert |

---

## Explicit Non-Actions (PHASE 2I)

```
[x] Keine weiteren Codeänderungen (außer dem freigegebenen run_test_bot.py-Fix)
[x] Keine künstliche Fehlerprovokation
[x] Kein Refactoring
[x] Keine Änderung an bereits abgeschlossenen DL-06-Dateien (außer Dokumentation)
[x] Kein Commit
[x] Kein Push
[x] Keine PR
```

**Status:** PHASE 2I abgeschlossen. DL-06 bleibt **TECHNISCH FREIGEGEBEN /
ABGESCHLOSSEN** (siehe
`docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2G_DL06_AUDIT.md`,
Abschnitt 5), jetzt zusätzlich durch reale Erfolgspfad-Bestätigung in
Produktion UND Testumgebung untermauert.
