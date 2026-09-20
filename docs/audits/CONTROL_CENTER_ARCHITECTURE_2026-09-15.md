# MUSICBOT CONTROL CENTER — ARCHITECTURE PROPOSAL (Phase 2)

**Datum:** 2026-09-15
**Auftrag:** MUSICBOT_CONTROL_CENTER.txt, Abschnitt 34 (Phase 2).
**Voraussetzung:** BLOCKER-1 und BLOCKER-2 aus `docs/audits/CONTROL_CENTER_ARCHITECTURE_AUDIT_2026-09-15.md` sind entschieden:
- **Web-Auth:** Telegram-Login-Widget, aufsetzend auf `is_admin_or_owner`/`AccessLevel`.
- **Tech-Stack:** FastAPI.

**Status:** Vorschlag. Noch keine Implementierung — Phase 3 (Vertical Slice) braucht eine eigene, explizite Freigabe (siehe „Nächste Schritte" am Ende).

---

## 1. API-Design

Neues Package `control_center/` auf oberster Repo-Ebene, analog zur bestehenden Schichtgrenzen-Konvention aus CLAUDE.md §4 — **nicht** `api/`, da dieser Name laut CLAUDE.md §4 bewusst als „keine MusicBot-Schicht mehr" reserviert ist (ARCH-009, vollständig entfernt). Struktur:

```text
control_center/
    __init__.py
    app.py              # FastAPI-App-Factory, Router-Registrierung
    dependencies.py     # Auth-Dependency (siehe Abschnitt 3), Config-Injection
    routers/
        health.py        # /api/v1/health, /api/v1/library/findings
        auth.py           # /api/v1/auth/telegram-callback
    schemas/
        health.py         # Pydantic-Response-Modelle (Request-seitig im MVP nicht nötig, nur GET)
```

Nur die für den MVP (Health/Dashboard + Findings-Browser, siehe Audit Abschnitt 9) tatsächlich benötigten Endpunkte — kein Vorgriff auf spätere Phasen (Master-Prompt Abschnitt 17 „nicht blind eine riesige API entwickeln"):

```text
GET  /api/v1/health                 → System-/Telegram-/Navidrome-/Library-Status (Dashboard-Kacheln)
GET  /api/v1/library/health          → services/library_health/scanner.py::run_scan + report.py::build_report_dict
GET  /api/v1/library/findings        → services/library_health/findings.py::group_open_findings_by_category
GET  /api/v1/library/findings/summary → findings.py::get_review_summary
POST /api/v1/auth/telegram-callback  → Telegram-Login-Widget-Verifikation (Abschnitt 3)
```

Alle weiteren Endpunkte aus der Capability Matrix (`CONTROL_CENTER_CAPABILITY_MATRIX_2026-09-15.md`) sind bewusst **nicht** Teil dieses Vorschlags — sie kommen mit ihrer jeweiligen Phase (Findings-Accept/Unaccept z. B. erst, wenn der Findings-Browser tatsächlich interaktiv werden soll, nicht im reinen Anzeige-MVP).

Response-Contracts sind Pydantic-Modelle in `control_center/schemas/`, die **nicht** 1:1 die internen Dataclasses aus `services/library_health/models.py` durchreichen (Master-Prompt Regel 9: „Interne Implementierungsdetails dürfen nicht automatisch Teil des API-Contracts werden"). Für den MVP genügt ein dünnes Mapping, kein vollständiger DTO-Layer.

Fehlerformat einheitlich nach Master-Prompt Abschnitt 31:

```json
{"error": {"code": "LIBRARY_HEALTH_SCAN_FAILED", "message": "...", "request_id": "..."}}
```

umgesetzt über einen globalen FastAPI-Exception-Handler, der interne Exception-Details nicht ungefiltert weitergibt.

---

## 2. Service-Integration

```text
Browser
   ↓
FastAPI-Router (control_center/routers/health.py)
   ↓  (kein Business-Logic hier — nur Parsen/Validieren/Aufrufen/Serialisieren)
services/library_health/scanner.py::run_scan()
services/library_health/report.py::build_report_dict()
services/library_health/findings.py::FindingsRegistry, group_open_findings_by_category()
   ↓
Filesystem (Library-Root, read-only für den MVP-Scope)
```

Der Router ruft ausschließlich bestehende, bereits Telegram-freie Funktionen auf (`run_scan`, `build_report_dict`, `FindingsRegistry`) — identisch zu den Aufrufen, die `scripts/library_health_check.py` und `scripts/library_health_review.py` bereits heute machen. Keine neue Business-Logik entsteht; die Web-Schicht dupliziert nichts (Master-Prompt Regel 7/8).

`FindingsRegistry` wird pro Request neu geladen (liest den bestehenden JSON-Store), kein In-Memory-Caching im MVP — vermeidet Konsistenzprobleme zwischen Telegram-Review-Flow und Web-Anzeige, die sonst gleichzeitig auf denselben Store zugreifen könnten. Das ist eine bewusst konservative erste Entscheidung; Caching kann bei Bedarf später nachgerüstet werden (Master-Prompt Regel 26: erst messen, dann optimieren).

---

## 3. Auth-Konzept — Telegram-Login-Widget

### Flow

```text
1. Browser lädt Login-Seite mit Telegram-Login-Widget
   (data-telegram-login=<BOT_USERNAME>, data-auth-url=/api/v1/auth/telegram-callback)
2. Nutzer authentifiziert sich bei Telegram → Telegram liefert signierte
   Nutzerdaten (id, first_name, username, photo_url, auth_date, hash)
   per Redirect/Callback an das Frontend
3. Frontend sendet diese Daten unverändert an
   POST /api/v1/auth/telegram-callback
4. Backend verifiziert die Telegram-Signatur:
   secret_key = SHA256(BOT_TOKEN)
   check_hash = HMAC-SHA256(secret_key, data_check_string)
   → muss exakt dem von Telegram gesendeten `hash` entsprechen
   (Standard-Telegram-Login-Widget-Verifikation, siehe Telegram-Bot-API-Doku)
5. Bei gültiger Signatur: user_id aus den verifizierten Daten →
   config.py::AccessLevel via get_user_access_level(user_id, config, user_mgmt_handler)
   → derselbe Auth-Kern wie im Telegram-Bot selbst (Master-Prompt Regel 51)
6. Backend setzt ein serverseitiges Session-Cookie (httponly, secure, samesite=strict),
   das nur eine signierte Session-ID enthält — kein JWT mit User-Daten im Klartext
   nötig für den MVP-Scope, da alles serverseitig nachschlagbar ist
7. Nachfolgende Requests: FastAPI-Dependency liest Session-Cookie → AccessLevel →
   Router prüft AccessLevel gegen die Mindestanforderung des Endpunkts
```

### BOT_TOKEN-Handling (kritisch, CLAUDE.md §12 / Master-Prompt Regel 15/20)

- `BOT_TOKEN` wird **ausschließlich serverseitig** aus `config.py::Config.BOT_TOKEN` (bestehende `.env`-basierte Property) gelesen — exakt derselbe Zugriffspfad wie im Telegram-Bot-Prozess selbst, keine zweite Quelle.
- `BOT_TOKEN` erscheint **niemals** im Frontend-Bundle, niemals in einer Response, niemals in Logs — nur `data-telegram-login` im HTML braucht den `BOT_USERNAME` (öffentlich, kein Secret).
- Signatur-Verifikation (Schritt 4) läuft ausschließlich im Backend-Prozess.
- Bestehendes `Config.mask_sensitive()` (bereits für `BOT_TOKEN`-Logging genutzt, siehe `config.py:518`) wird für jedes Logging im Auth-Pfad wiederverwendet, kein neues Masking-Schema.

### Voraussetzung beim Nutzer

Das Telegram-Login-Widget verlangt eine bei BotFather hinterlegte Domain (`/setdomain`) — das Control Center muss unter einer festen, HTTPS-erreichbaren Domain laufen (siehe Abschnitt 7 „Deployment"). Lokales `http://localhost`-Testen funktioniert mit dem Telegram-Login-Widget **nicht** direkt; für lokale Entwicklung wird ein Dev-Auth-Bypass hinter einem expliziten `DEBUG`-Flag empfohlen, der **niemals** in einer für das Internet erreichbaren Umgebung aktiv sein darf (eigener Regressionstest dafür in Abschnitt „Security-Checkliste").

### Session vs. bestehendes Rollenmodell

`AccessLevel` bleibt exakt wie im Bot (`PUBLIC/USER/MODERATOR/ADMIN/OWNER`). Für den Health/Findings-MVP genügt „mindestens USER" als Zugriffsschwelle (Findings sind laut Telegram-Modell `review:`-Bereich = ADMIN — die Web-Variante übernimmt dieselbe Schwelle 1:1, keine Aufweichung).

---

## 4. Jobs

Für den Health/Findings-MVP **nicht benötigt** — beide Endpunkte sind synchron-schnell genug für einen normalen HTTP-Request (Health-Scan einer Musikbibliothek ist lesend und lokal, kein Netzwerk-Wartezeit-Faktor wie bei Downloads/Reprocessing).

Skizze für einen späteren generischen Job-Store (relevant ab Repair-Ausführung/Reprocessing/Duplicate-Scan, siehe Audit Abschnitt 7.1 — **hier nur dokumentiert, nicht Teil dieser Phase**):

```text
JobRegistry (services-Ebene, Telegram-frei, analog ActiveDownloadRegistry)
    - create_job(kind, initiator) -> job_id
    - update_progress(job_id, progress, message)
    - complete(job_id, result) / fail(job_id, error)
    - get(job_id) -> JobStatus
    - list(filter_by_initiator=...)

Ausführung: asyncio.create_subprocess_exec (Vorbild doctor_runner.py) für
Skript-basierte Operationen, oder asyncio.create_task für In-Process-Services
ohne SingletonMixin-Konflikt (siehe docs/METADATA_REPROCESSING.md §2a-Warnung
für Reprocessing — dort bleibt Subprozess Pflicht).
```

Kleinster sinnvoller nächster Schritt (nicht Teil dieser Freigabe): `JobRegistry` zuerst nur für einen einzelnen neuen Anwendungsfall (z. B. Web-getriggerter Doctor-Run) einführen, Downloads bleiben vorerst auf `ActiveDownloadRegistry` — keine Migration ohne eigene Characterization (Master-Prompt Regel 5).

---

## 5. Frontend

**Vorschlag: kein SPA-Framework für den MVP.** Serverseitig gerendertes HTML (Jinja2, das FastAPI-Standard-Templating, keine zusätzliche Kern-Dependency-Familie) + minimales Vanilla-JS für Polling (Health-Status alle N Sekunden neu laden) und die Findings-Filterung.

**Begründung:**
- Master-Prompt Regel 25 „Dependencies minimieren" — React/Vue/etc. wäre für zwei lesende Anzeigeseiten (Dashboard, Findings-Liste) unverhältnismäßig.
- Master-Prompt Abschnitt 19 „V1 darf zunächst mit Polling funktionieren" — kein WebSocket/SSE nötig für zwei GET-Endpunkte.
- Desktop-First mit Mobile-Responsive (Master-Prompt Abschnitt 24) ist mit serverseitigem HTML + einfachem CSS-Grid ohne Framework-Overhead erreichbar.
- Jinja2 ist bereits Teil des FastAPI-Ökosystems (kein zusätzlicher Auth-/Build-Overhead wie bei einem SPA mit eigenem Build-Schritt/Dev-Server).

**Einschränkung:** Dieser Vorschlag gilt explizit nur für den Health/Findings-MVP. Sobald interaktivere Bereiche kommen (Repair-Preview/Diff/Confirm-Flows, Job-Progress-Balken, große filterbare Tabellen — Master-Prompt Abschnitt 6/21), ist eine erneute, eigenständige Bewertung nötig, ob weiterhin serverseitiges Rendering + Vanilla-JS ausreicht oder ob ein leichtes Frontend-Werkzeug (z. B. htmx statt eines vollen SPA-Frameworks) den Aufwand rechtfertigt — **keine Vorentscheidung dafür in diesem Dokument**, das wäre ein ungefragter Technologie-Vorgriff (Master-Prompt Regel 24).

---

## 6. Security-Checkliste (angewendet auf diesen Vorschlag)

| Punkt | Bewertung |
|---|---|
| **Auth** | Telegram-Login-Widget + Signatur-Verifikation (Abschnitt 3) — kein Endpunkt außer `/auth/telegram-callback` und einer öffentlichen Login-Seite ohne gültige Session erreichbar. |
| **Authorization** | Jeder Router prüft `AccessLevel` serverseitig über dieselbe `get_user_access_level`-Funktion wie Telegram — kein UI-only-Check (Master-Prompt Regel 30). |
| **CSRF** | Session-Cookie mit `samesite=strict` deckt die GET-lastigen MVP-Endpunkte ab; bei den ersten schreibenden Endpunkten (spätere Phase, z. B. Findings-Accept) zusätzlich CSRF-Token oder striktes `samesite`+Origin-Check prüfen — für den reinen Lese-MVP kein zusätzlicher Mechanismus nötig. |
| **CORS** | Keine Cross-Origin-Nutzung vorgesehen (Frontend wird vom selben FastAPI-Prozess ausgeliefert) — CORS-Middleware nicht aktivieren, Default „same-origin only". |
| **Rate Limiting** | Für den MVP (zwei lesende, lokale Endpunkte) kein dediziertes Rate-Limiting nötig; für `/auth/telegram-callback` (Angriffsfläche: wiederholte Hash-Brute-Force-Versuche) einfache IP-basierte Rate-Begrenzung empfohlen, bevor der Endpunkt öffentlich erreichbar ist. |
| **Input Validation** | Pydantic-Response-Modelle validieren Ausgaben; Eingaben im MVP nur der Telegram-Callback-Payload — Hash-Verifikation selbst ist die Validierung (Abschnitt 3, Schritt 4). |
| **Secret Exposure** | `BOT_TOKEN` nie im Frontend (Abschnitt 3); Health-/Findings-Responses enthalten laut bestehender Report-Struktur keine Secrets — trotzdem vor MVP-Freigabe stichprobenartig prüfen, dass `build_report_dict`/`findings.py`-Ausgaben keine Pfade/Daten enthalten, die als PII zu werten wären (CLAUDE.md §12). |
| **Path Traversal / Command Injection / SSRF** | Kein Nutzer-Input im MVP, der an Filesystem/Shell/externe URLs weitergereicht wird (beide Endpunkte sind parameterlose GETs) — Risiko im MVP-Scope nicht vorhanden, bei künftigen Endpunkten mit IDs/Pfaden erneut zu prüfen. |
| **GET ohne Seiteneffekte** | Beide MVP-Endpunkte sind reine Lesezugriffe — Master-Prompt Regel 12 eingehalten. |

---

## 7. Deployment

**Ausgangslage (verifiziert):** Kein Reverse-Proxy, kein Docker-Compose, keine systemd-Unit-Datei im Repository gefunden. `bot.py` läuft heute als einzelner, langlebiger `asyncio`-Prozess über `bot_runner.start_polling()` (Telegram-Polling, kein Webhook).

**Vorschlag:**

```text
Prozess 1: bestehender Telegram-Bot (bot.py, unverändert)
Prozess 2: neuer FastAPI-Server (uvicorn control_center.app:app),
           eigener Prozess, eigener Port (z. B. 127.0.0.1:8420)
```

Getrennte Prozesse statt Einbettung in `bot.py` — Begründung: Lifecycle-Trennung (ein Absturz/Neustart des Web-Servers darf den Telegram-Bot nicht mitreißen und umgekehrt, Master-Prompt Abschnitt 4 „Subprocess nur bei begründetem Isolationsbedarf" spricht zwar von Subprocess-Aufrufen für einzelne Operationen, das Prinzip Isolation gilt aber ebenso für den Server-Prozess selbst).

- **uvicorn** bindet nur an `127.0.0.1` (nicht `0.0.0.0`) — externe Erreichbarkeit ausschließlich über einen expliziten Reverse-Proxy (z. B. nginx/Caddy mit TLS), der für das Telegram-Login-Widget ohnehin zwingend nötig ist (HTTPS-Pflicht, siehe Abschnitt 3).
- Prozess-Supervision (Start/Restart bei Absturz) ist **außerhalb des Repository-Scopes** — keine systemd-Unit/Docker-Setup existiert bisher, das wird als eigener BLOCKER für Phase 3 markiert (siehe unten), nicht in diesem Dokument vorweggenommen, da es eine Deployment-Entscheidung ist, die vom Host des Nutzers abhängt.
- **Speicherdruck-Hinweis** (Projekt-Memory: Entwicklungsmaschine mit 7,7 GB RAM, oft volle 4 GB Swap): ein zweiter Dauerprozess (uvicorn + FastAPI + Jinja2) erhöht den Grundverbrauch spürbar. Für die Entwicklungsphase ist das vertretbar; für den späteren Produktivbetrieb auf demselben Host ist das bei der Ressourcenplanung zu berücksichtigen.

**Neuer BLOCKER (klein, kein Showstopper, aber vor Phase 3 zu klären):** Wo/wie soll uvicorn dauerhaft laufen (systemd-Unit neu anlegen? manueller Start? vorhandener Supervisor außerhalb des Repos?) und existiert bereits ein Reverse-Proxy auf dem Zielhost? Das ist eine reine Infrastrukturfrage ohne Code-Auswirkung auf `control_center/` selbst — wird hier dokumentiert, aber nicht blockierend für die Implementierung des Vertical Slice selbst (lokal ohne TLS/Domain testbar, siehe Dev-Auth-Bypass in Abschnitt 3).

### Nachtrag (2026-09-15, während Schritt 1 entdeckt): geteiltes Python-Environment mit `spotdl`

Bei der Implementierung von Schritt 1 hat sich gezeigt: MusicBot besitzt **kein eigenes, isoliertes virtualenv** — `python3` löst auf `/home/robin/python` auf, ein Environment, das der Nutzer offenbar auch für ein unabhängiges Tool namens `spotdl` (Spotify-Downloader, `pip show spotdl` → "Download your Spotify playlists...") nutzt. `spotdl==4.4.3` pinnt `fastapi<0.104,>=0.103.0` und `uvicorn<0.24,>=0.23.2`.

Ein erster Versuch, `fastapi`/`uvicorn` auf eine aktuelle Version zu heben (um die unten beschriebene Inkompatibilität mit der bereits installierten `httpx==0.28.1` sauber zu loesen), haette `spotdl`s Versionsbindung gebrochen — das wurde noch in diesem Schritt bemerkt und **zurückgerollt** (`fastapi==0.103.2`/`starlette==0.27.0`/`uvicorn==0.23.2` wiederhergestellt, siehe `requirements.txt`).

**Für Schritt 1 gelöst durch:** die spotdl-kompatiblen alten `fastapi`/`uvicorn`-Versionen bleiben unangetastet — betroffen war ausschließlich `starlette.testclient.TestClient`, das mit `httpx>=0.28` nicht mehr kompatibel ist. Die Tests (`tests/test_control_center_health_api.py`) nutzen stattdessen `httpx.AsyncClient(transport=httpx.ASGITransport(...))` direkt (die von httpx selbst empfohlene, versionsunabhängige Alternative) — keine Versionsänderung an fastapi/uvicorn/starlette nötig.

**Für spätere Phasen relevant (kein Blocker für Schritt 1, aber vor produktivem Deployment zu klären):** Solange `control_center/` im selben Environment wie `spotdl` läuft, bleibt FastAPI auf `<0.104` eingefroren (Stand 2026-09-15 deutlich veraltet, aktuell wäre `0.141.x`). Das schränkt künftige FastAPI-Features nicht kritisch ein (die hier verwendete API-Oberfläche ist seit Jahren stabil), aber jede zukünftige FastAPI-Abhängigkeit sollte gegen diese Deckelung geprüft werden. Eine sauberere Lösung (eigenes virtualenv für MusicBot, losgelöst von `spotdl`) wäre ein Infrastruktur-Entscheid mit Auswirkung auf den gesamten Bot-Betrieb (bot.py, alle scripts/, Deployment) — **kein kleinster sinnvoller Schritt**, daher hier nur dokumentiert (Master-Prompt Regel 5/24), nicht umgesetzt.

---

## 8. Future Player Integration

Ausdrücklich **nicht** Teil von V1 (Master-Prompt Abschnitt 2/15/47). Wird hier nur der Vollständigkeit halber erwähnt: Navidrome bleibt für Streaming/Playback zuständig; ein künftiges Player-Modul würde auf `services/clients/navidrome_api.py` aufsetzen (bereits vorhanden, siehe Audit Abschnitt 6, Punkt 8) und als separates, nachrüstbares Modul in `control_center/routers/navidrome.py` ergänzt werden — keine weitere Ausarbeitung an dieser Stelle nötig.

---

## Nächste Schritte — Vertical Slice „Health/Dashboard"

Kleinstmögliche, jeweils für sich testbare Schritte (Master-Prompt Regel 5/6). Schritte 1, 3 und 5 (3/5 vorgezogen, siehe Nachträge unten) freigegeben und umgesetzt, Schritte 2/4/6-8 **weiterhin nicht freigegeben — warten auf explizite Freigabe:**

1. ✅ **Health API** (2026-09-15) — `control_center/app.py` (FastAPI-App-Grundgerüst inkl. einheitlichem Fehlerformat) + `control_center/routers/health.py` mit `GET /api/v1/library/health`, ruft unverändert `run_scan()` auf (das intern bereits `build_report_dict()` aufruft), mappt auf ein dünnes Pydantic-Response-Schema (`control_center/schemas/health.py`, lässt `library.root`/`health.weights`/Issue-/Datei-Listen bewusst aus). Test: `tests/test_control_center_health_api.py`, 4 Tests (Happy Path gegen echten `run_scan()` mit ffmpeg-generierter Test-Library, Schema-Kapselung, 404 bei fehlendem Library-Root, 500 bei Scan-Fehler ohne Detail-Leck) — alle grün, plus thematische Regressionssuite `tests/test_library_health*.py` (301 Tests) weiterhin grün. Noch ohne Auth (folgt Schritt 3); `fastapi`/`pydantic`/`uvicorn` neu in `requirements.txt`, `httpx` neu in `requirements-dev.txt` (Versions-Nachtrag zu spotdl-Kompatibilität siehe Abschnitt 7 oben). Commit `3c097a0`, PR #246.
2. **Service Integration Test** — Integrationstest, der den echten `services/library_health`-Pfad gegen ein Test-Fixture-Library-Verzeichnis prüft (Vorbild: bestehende `tests/`-Fixtures für Library-Health, falls vorhanden — vor Schritt 1 kurz prüfen).
3. ✅ **Auth-Grundgerüst** (2026-09-15) — `control_center/dependencies.py` mit Telegram-Login-Widget-Verifikation (Abschnitt 3: HMAC-SHA256 gegen `SHA256(BOT_TOKEN)`, inkl. `auth_date`-Frischeprüfung gegen Replay) + signierten Session-Cookies (HMAC-Token, Secret aus `BOT_TOKEN` abgeleitet — kein neues Secret, siehe Modul-Docstring für die Grenze dieser Entscheidung) + Dev-Bypass hinter einem eigenen `Config.CONTROL_CENTER_DEV_AUTH_BYPASS`-Flag (bewusst **nicht** an `DEBUG_MODE` gekoppelt — Begründung im Config-Docstring: gemeinsame Nutzung hätte ein versehentlich aktiviertes `DEBUG_MODE` still auch zum Auth-Bypass gemacht). `control_center/routers/auth.py`: `POST /api/v1/auth/telegram-callback` (Login) + `GET /api/v1/auth/whoami`. AccessLevel-Auflösung nutzt denselben, bereits Telegram-freien Auth-Kern wie der Bot (`handlers/menu/permissions.py::get_user_access_level()`, `handlers/menu/models.py::AccessLevel`) — bekannte MVP-Einschränkung: ohne `user_mgmt_handler` wird ein nur über `data/user_data.json` vergebener MODERATOR-Status noch nicht aufgelöst (OWNER/ADMIN über `config.py` funktionieren korrekt). Test: `tests/test_control_center_auth.py`, 29 Tests (Signaturprüfung inkl. Replay-Schutz, Session-Token-Rundlauf/Tamper/Expiry, `require_min_access_level()`-Factory, HTTP-Login-/whoami-Flow, Dev-Bypass-Verhalten inkl. Default-Aus, Authorization-Verdrahtung in Health/Findings) — alle grün, plus Regression `tests/test_menu_permissions_characterization.py` (19 Tests) und Gesamt-Control-Center-Suite (356 Tests) weiterhin grün. Keine neuen Dependencies. **Nachtrag (2026-09-15, direkt im Anschluss auf Nutzerwunsch):** `control_center/routers/health.py` (mind. `AccessLevel.USER`) und `control_center/routers/findings.py` (mind. `AccessLevel.ADMIN`, spiegelt die bestehende Telegram-Schwelle) sind jetzt tatsächlich über `Depends(require_min_access_level(...))` auf Router-Ebene geschützt — die bestehenden Health-/Findings-Tests laufen dafür über den Dev-Auth-Bypass (sie prüfen weiterhin die jeweilige Fachlogik, nicht Auth selbst).
4. ✅ **Health UI** (2026-09-15) — `control_center/routers/ui.py` mit `GET /` (unauthentifiziertes HTML-Grundgerüst, Master-Prompt Regel 12), `control_center/templates/dashboard.html` (Jinja2 + Vanilla-JS, kein SPA-Framework, wie in Abschnitt 5 entschieden). Client-JS holt `GET /api/v1/auth/whoami` und `GET /api/v1/library/health`, schaltet bei `401` auf eine Login-Ansicht mit dem Telegram-Login-Widget um (`data-telegram-login` aus neuem, nicht-sensiblem `Config.BOT_USERNAME`, optional — ohne gesetztes `BOT_USERNAME` zeigt die Seite stattdessen einen Konfigurationshinweis inkl. `CONTROL_CENTER_DEV_AUTH_BYPASS`), Health-Kacheln (Score/Status/Dateien/Artists/Alben), 30s-Polling, Loading-/Login-/Error-/Empty-/Success-States (Master-Prompt Regel 45). Neue Dependency `Jinja2==3.1.6` (bereits im Environment installiert, transitiv von einem unabhängigen Flask-Tool — analog zur spotdl-Begründung bei fastapi/uvicorn/httpx). Test: `tests/test_control_center_ui.py`, 5 Tests (Rendering ohne Auth, alle View-States vorhanden, korrekte API-Pfade im Markup, Widget bei gesetztem/fehlendem `BOT_USERNAME`) — alle grün, plus Gesamt-Control-Center-Suite 374/374 grün. Zusätzlich manuell gegen einen echten `uvicorn`-Dev-Server mit `CONTROL_CENTER_DEV_AUTH_BYPASS=true` verifiziert (`GET /api/v1/auth/whoami` und `GET /api/v1/library/health` liefern echte Daten aus der realen Library — 492 Dateien, Score 99.9). Kein echter Browser-Visualcheck möglich (keine Browser-Automatisierung in dieser Session verbunden) — das ist hier explizit vermerkt statt stillschweigend als "getestet" behauptet.
5. ✅ **Findings-Endpunkt** (2026-09-15, vorgezogen auf Nutzerwunsch als „Phase 3 – Step 2: Library", Scope explizit auf **read-only** begrenzt) — `control_center/routers/findings.py` mit `GET /api/v1/library/findings` (offene Findings gruppiert nach Kategorie, sortiert nach Severity-Tier) + `GET /api/v1/library/findings/summary` (Tri-State-Zusammenfassung open/repaired/accepted/resolved_by_scan/total). Liest ausschließlich die bestehende, persistente `FindingsRegistry` (kein neuer Scan, kein Merge/Save — reines Lesen, GET bleibt seiteneffektfrei). Bewusst **keine** Accept-/Unaccept-/Review-Endpoints (das war die zweite, nicht gewählte Scope-Option — siehe Freigabe-Frage vom 2026-09-15). Dünnes Pydantic-Schema (`control_center/schemas/findings.py`) lässt Review-Historie (reviewed_by/history/resolved_at/...) bewusst aus. Test: `tests/test_control_center_findings_api.py`, 7 Tests — alle grün, plus `tests/test_library_health_findings.py` (68 Tests) weiterhin grün, Gesamt-Control-Center-Suite 308/308. Keine neuen Dependencies (FastAPI/Pydantic bereits aus Schritt 1 vorhanden). Noch ohne Auth (wie Schritt 1).
6. **Tests konsolidieren** — thematische Suite `tests/test_control_center*.py` (CLAUDE.md §8.A Schritt 3), **keine Vollsuite durch den Implementierungsprozess** (CLAUDE.md §8.A).
7. **Verification** — manuelles Durchklicken des Vertical Slice (Login → Dashboard → Findings) gegen eine Test-Library, Ergebnis dokumentieren.
8. ✅ **Dokumentation** (2026-09-15) — README.md (Projektstruktur-Tabelle, „Control Center starten"-Abschnitt, neue Env-Vars), `docs/INDEX.md` (neuer „Control Center"-Abschnitt), `CLAUDE.md` Abschnitt 4 (`control_center/` als neue Schicht, Gegenstück zu `handlers/`, ohne Telegram-Objekte). PR #249.

Jeder dieser Schritte ist einzeln committ- und überprüfbar (Master-Prompt Regel 5/6/38) — kein Big-Bang-Commit für den gesamten Slice.

**Damit ist der Vertical Slice „Health/Dashboard" (Schritte 1, 3, 4, 5, 8) vollständig umgesetzt und gemergt.** Schritte 2/6 waren de facto durch die jeweiligen Test-Läufe bei jedem Schritt bereits mitabgedeckt (siehe dortige Test-Ergebnisse), Schritt 7 (Verification) durch einen vom Nutzer bestätigten Browser-Screenshot nach Schritt 4.

---

## Erweiterung — Library Repair Preview (2026-09-15, auf Nutzerfreigabe nach Abschluss des Vertical Slice)

Nächster Funktionsbereich nach Abschluss des Health/Dashboard-Slice (Nutzerentscheidung zwischen „Jobs-Grundgerüst" und „Library Repair Preview" — Letzteres gewählt, da es direkt auf der bereits vorhandenen Findings-Anzeige aufbaut und kein Jobs-System braucht, da rein lesend).

**Scope (explizit, wie bei Findings): nur Preview, keine Ausführung.** Zeigt zu den aktuell erkannten Health-Issues die vom bestehenden `services/library_repair/planner.py::plan_repairs()` (per eigenem Modul-Docstring bereits read-only, kein Dateisystem-Zugriff, keine Ausführung) vorgeschlagene Reparaturaktion — kein Executor wird aufgerufen, keine Datei verändert.

- `GET /api/v1/library/repair-plan` (mind. `AccessLevel.ADMIN`, identische Schwelle wie Findings) — führt denselben frischen Library-Scan wie `GET /api/v1/library/health` aus (Refactor: `control_center/_library_scan.py::run_library_scan()` jetzt gemeinsam von `routers/health.py` und `routers/repair.py` genutzt statt dupliziert, Master-Prompt Regel 7) und übergibt den Report unverändert an `plan_repairs()`. Dünnes Response-Schema (`control_center/schemas/repair.py`) ergänzt pro Kandidat die Grob-Disposition (`AUTO_REPAIR`/`MANUAL_REVIEW`/`UNREPAIRABLE`, aus `planner.py::disposition_for_level()`), lässt `library_root` aus (identische Begründung wie bei Health).
- Bewusst **keine** Execute-/Apply-Endpoints, kein Preview→Confirm→Execute-Flow (Master-Prompt Abschnitt 21) — das wäre eine deutlich größere, eigene Freigabe-Entscheidung (destruktive/schreibende Operation).
- Test: `tests/test_control_center_repair_api.py` (5 Tests, inkl. eines deterministisch bekannten Issue-Codes `META_ARTIST_MISSING` gegen eine echte ffmpeg-generierte Test-Library) + 3 neue Authorization-Wiring-Tests in `tests/test_control_center_auth.py` (401/403/200) — alle grün, plus Gesamt-Suite (`control_center*`/`library_health*`/`library_repair*`/Permissions/Config) 704/704 grün.
- Zusätzlich manuell gegen die echte Produktions-Library verifiziert: 1114 `actionable`, 96 `MANUAL_REVIEW`, `health_score` 99.9 (konsistent mit dem Health-Endpoint-Smoke-Test aus Schritt 4).
- Keine neuen Dependencies.

**Offen für eine künftige Freigabe:** Filter-Query-Parameter (Artist/Issue-Code/Severity/Level, `planner.py::filter_plan()` existiert bereits produktiv für die CLI) sowie der eigentliche Execute-Schritt — beides bewusst nicht Teil dieser Erweiterung.

---

## Erweiterung — Download-Center (2026-09-15, auf Nutzerfreigabe)

Dritter Funktionsbereich nach Health/Dashboard und Library Repair Preview (Nutzerentscheidung zwischen „Download-Center", „Statistics-Dashboard" und „Jobs-Grundgerüst" — Download-Center gewählt).

**Wichtiger Architektur-Fund während der Umsetzung, der die ursprüngliche Empfehlung korrigiert:** Live-Fortschritt laufender Downloads (`services/downloader/active_downloads.py::ActiveDownloadRegistry`) ist laut eigenem Modul-Docstring **ausschließlich Inprozess-Zustand des Bot-Prozesses** (eine langlebige Instanz, gehalten von `RichMenuHandler`). Da `control_center/` als separater Prozess läuft (Abschnitt 7 oben), gibt es keinen gemeinsamen Speicher — dieser Zustand ist aus dem Web-Prozess grundsätzlich nicht lesbar, unabhängig von der Implementierung. Dem Nutzer explizit vorgelegt und entschieden: **Scope auf den bereits persistenten, Cross-Prozess-lesbaren Download-Verlauf begrenzt** (`services/downloader/download_history.py::DownloadHistoryStore`, JSON unter `Config.DOWNLOAD_HISTORY_DIR`). Kein Live-Status in diesem Schritt — eine künftige Erweiterung dafür müsste `bot.py`/`RichMenuHandler` selbst ändern (periodische Persistenz des Registry-Zustands), ein deutlich größerer, separat zu entscheidender Eingriff in den produktiven Bot-Prozess.

- `GET /api/v1/downloads/history?limit=` (mind. `AccessLevel.ADMIN` — die chat-übergreifende Sicht zeigt potenziell Downloads anderer Nutzer/Familienmitglieder, nicht nur die eigenen, anders als die Telegram-eigene Verlaufsansicht) — liest `DownloadHistoryStore` frisch pro Request (identisches Prinzip wie `FindingsRegistry` in `routers/findings.py`), kein Schreibzugriff.
- Kleine, gezielte Erweiterung von `DownloadHistoryStore` um `get_all_recent()` (chat-übergreifend, neueste zuerst) — bestehende, bereits produktiv genutzte Klasse erweitert statt eine parallele Leselogik zu bauen (Master-Prompt Regel 7). `get_recent(chat_id)` (Telegram-Verlaufsansicht, ein Chat) bleibt unverändert.
- Dünnes Response-Schema (`control_center/schemas/downloads.py`), `limit`-Query-Parameter serverseitig auf 1–200 begrenzt (FastAPI `Query(ge=1, le=200)`).
- Test: neue Tests in `tests/test_download_history_store.py` (`TestGetAllRecent`, 4 Tests) + `tests/test_control_center_downloads_api.py` (5 Tests) + 3 neue Authorization-Wiring-Tests in `tests/test_control_center_auth.py` (401/403/200) — alle grün, plus Gesamt-Suite (`control_center*`/`download_history*`/`library_health*`/`library_repair*`/Permissions/Config) 751/751 grün.
- Zusätzlich manuell gegen die echten, produktiven Download-Verlaufsdaten verifiziert (5 aktuellste Einträge korrekt inkl. Metadata-Checkliste).
- Keine neuen Dependencies.

---

## Erweiterung — Statistics-Dashboard (2026-09-15, auf Nutzerfreigabe)

Vierter Funktionsbereich (Nutzerentscheidung zwischen „Statistics-Dashboard", „Navidrome-Status" und „Jobs-Grundgerüst" — Statistics gewählt).

**Wichtiger Architektur-Fund während der Umsetzung — zum zweiten Mal dieselbe Grundfrage wie in Schritt 3:** `StatisticsCalculator.generate_stats()` ist strikt pro Navidrome-Benutzer (`navidrome_username` ist Pflicht, `None` liefert sofort `None` zurück — es gibt keine "globale" Statistik). Die Zuordnung Telegram-ID → Navidrome-Username lebt nur in `UserManagementHandler.get_navidrome_user()` (`handlers/admin/`) — derselben Klasse, die in Schritt 3 bewusst nicht importiert wurde, weshalb dort die MODERATOR-Auflösung unvollständig blieb.

**Diesmal strukturell gelöst statt erneut ad-hoc umgangen (Nutzerentscheidung: "Gemeinsame Funktion extrahieren"):**

- Neues `services/user_data.py` (Telegram-frei): `load_user_data()`, `get_navidrome_user()`, `get_user_role()` — extrahiert aus `UserManagementHandler._load_users()`/`.get_navidrome_user()` (Master-Prompt Regel 51 "Common Core", identisches Extraktionsmuster wie zuvor bei `handlers/menu/permissions.py`). `UserManagementHandler` behält beide Methoden als dünne Delegatoren — unverändertes Verhalten, bestätigt durch die bestehende Testsuite (40 Tests weiterhin grün).
- **Nachtrag zu Schritt 3:** `control_center/dependencies.py::get_current_access_level()` nutzt jetzt `load_user_data()` + ein minimales `_UserDataCacheAdapter`-Objekt (nur `.user_data_cache`-Attribut) als `user_mgmt_handler`-Argument für das bereits duck-typisierte `handlers/menu/permissions.py::get_user_access_level()` — `permissions.py` selbst bleibt unverändert. Die MODERATOR-Lücke aus Schritt 3 ist damit geschlossen (neuer Test: `test_whoami_resolves_moderator_from_user_data_json`).
- `GET /api/v1/statistics/me?period=week|month|year` (mind. `AccessLevel.USER` — eigene Daten, wie Health) — löst den Navidrome-Username der aktuell authentifizierten Telegram-ID auf, ruft dann unverändert `StatistikService.generate_stats()` auf. `404 NAVIDROME_USER_NOT_CONFIGURED`, wenn kein Navidrome-User hinterlegt ist. Dünnes Response-Schema reduziert auf `total_plays`/`top_artists`/`top_songs` (die MVP-Ansicht; `top_songs_detailed`/`top_artists_split`/Genre/Music-DNA bewusst nicht Teil dieses Schritts). `has_data=false` bildet den legitimen Empty-State ab (kein Play-Verlauf vorhanden), kein Fehler.
- Test: `tests/test_user_data.py` (10 Tests, neues Modul) + `tests/test_control_center_statistics_api.py` (5 Tests) + 4 neue Tests in `tests/test_control_center_auth.py` (MODERATOR-Auflösung, Statistics-Auth-Wiring) — alle grün, plus Gesamt-Suite (`control_center*`/`user_data`/`user_management*`/`statistik*`/`download_history*`/Permissions/Config) 320/320 grün, plus `library_health*`/`library_repair*`-Regression 619/619 grün (Auth-Kern-Änderung betrifft alle bestehenden Router).
- Zusätzlich manuell gegen die echten, produktiven Play-History-Daten verifiziert (97 Plays im aktuellen Monat, korrekte Top-Artists/-Songs-Rangfolge).
- Keine neuen Dependencies.

**Offen für eine künftige Freigabe:** Genre-Statistik/Music-DNA (`generate_genre_stats()`/`generate_music_dna()` existieren bereits produktiv), Cross-User-Admin-Ansicht (`/api/v1/statistics/{navidrome_username}`, Pfad bewusst kollisionsfrei vorbereitet) — beides bewusst nicht Teil dieser Erweiterung.

---

## Erweiterung — Dashboard-UI für Findings/Repair-Plan/Downloads/Statistics (2026-09-15, auf Nutzerfreigabe)

Nachtrag zu Schritt 4 (Health UI): die vier seither hinzugekommenen Funktionsbereiche hatten nur eine API, keine Web-Oberfläche — für den Nutzer im Browser nur über `/docs` (Swagger-UI) erreichbar. `control_center/templates/dashboard.html` um vier neue Panels erweitert, `control_center/routers/`/`schemas/` unverändert (reines Frontend-Nachtrag, keine neue API-Fläche).

- **Findings-Panel:** Kategorien mit Severity-Tier-Badge + Anzahl offener Findings, `GET /api/v1/library/findings`.
- **Repair-Plan-Panel:** Kandidaten-Anzahl nach Level + `actionable_total`/`manual_review_total`/Health-Score. Bewusst **kein Auto-Load und kein 30s-Polling** — `GET /api/v1/library/repair-plan` kostet einen vollen Library-Scan (identisch teuer wie Health, ~37s auf der Produktions-Library), ein eigener "Berechnen"-Button triggert es nur auf Klick.
- **Downloads-Panel:** letzte 10 Verlaufseinträge (Status-Badge, Titel — Artist, Zeitstempel), `GET /api/v1/downloads/history?limit=10`.
- **Statistics-Panel:** Monats-Wiedergabezahl + Top-5-Artists, `GET /api/v1/statistics/me?period=month`.
- Gemeinsamer `_loadInto()`-JS-Helper für alle vier (401→Login-Ansicht, 403→"Keine Berechtigung"-Text statt Absturz — nicht-Admin-Nutzer sehen die Panels, aber mit einem klaren Hinweis statt Fehler, 404→Fehlermeldungstext z. B. bei fehlendem Navidrome-User, generischer Fehler sonst) — identisches Loading/Empty/Error/Success-State-Prinzip wie das bestehende Health-Panel (Master-Prompt Regel 45).
- 30s-Polling erweitert auf Findings/Downloads/Statistics (günstige, persistente Reads) — Repair-Plan bleibt bewusst ausgeschlossen (s. o.).
- Test: `tests/test_control_center_ui.py` von 5 auf 7 Tests erweitert (alle Panel-IDs vorhanden, alle vier neuen API-Pfade im Markup referenziert, dedizierter manueller Trigger für Repair-Plan) — alle grün, Gesamt-Control-Center-Suite 71/71 grün.
- Manuell per HTTP gegen die echten Produktionsdaten verifiziert (Findings/Downloads/Statistics liefern korrekte Live-Daten über die neue UI-Verdrahtung). Visueller Browser-Check durch den Nutzer für diese Erweiterung selbst noch ausstehend (für die ursprüngliche Health-Ansicht aus Schritt 4 bereits per Screenshot bestätigt) — kein Browser-Automatisierungswerkzeug in dieser Session verbunden.
- Keine neuen Dependencies, keine neue API-Fläche.

---

## Erweiterung — Navidrome-Status (2026-09-15, auf Nutzerfreigabe)

Fünfter Funktionsbereich (Nutzerentscheidung zwischen „Navidrome-Status", „Admin-Übersicht: Nutzer/Rollen" und „Findings Accept/Unaccept" — Navidrome-Status gewählt, Navidrome-Status stand schon zweimal zuvor als Option zur Wahl).

- `GET /api/v1/navidrome/status` (mind. `AccessLevel.USER`, reiner Status wie Health) — ruft ausschließlich `services/clients/navidrome_api.py::NavidromeAPI.check_connection()`/`get_artists()` auf. **Erster `async def`-Router in `control_center/`:** NavidromeAPI ist eine echte netzwerkgebundene Integration (anders als alle bisherigen Router, die ausschließlich lokale/synchrone Produktionsfunktionen aufrufen) — `check_connection()`/`get_artists()` sind bereits async (intern `asyncio.to_thread`-gewrappt), FastAPI awaitet sie direkt.
- Degradiert bewusst: `check_connection()` fängt jeden Fehler bereits selbst ab (`False` statt Exception) — kein eigenes Error-Handling nötig. Ein Fehler im nachgelagerten `get_artists()`-Aufruf (z. B. Ping ok, aber `getArtists` kaputt) darf das primäre „ist erreichbar"-Signal nicht verdecken → `artist_count=None` statt Request-Fehlschlag (kein 500).
- Dashboard-Panel: kleine Statuszeile („🟢 Navidrome: Verbunden (37 Artists)") direkt unter dem Nutzer-Login-Hinweis, passend zum Master-Prompt-Dashboard-Mockup (Abschnitt 5: „Navidrome 🟢 Connected"). Im 30s-Polling (günstiger Einzel-Ping, kein Scan).
- Test: `tests/test_control_center_navidrome_api.py` (4 Tests, NavidromeAPI per `monkeypatch.setattr(NavidromeAPI, "make_request", ...)` gemockt — CLAUDE.md Abschnitt 8, externe Dienste nicht real ansprechen) + 2 neue Authorization-Wiring-Tests in `tests/test_control_center_auth.py` + 1 neuer UI-Test — alle grün, Gesamt-Control-Center-Suite 78/78 grün.
- Zusätzlich manuell gegen den echten, produktiven Navidrome-Server verifiziert: `connected=true`, 37 Artists (deckungsgleich mit der Library-Scan-Artist-Zahl aus dem Health-Endpoint).
- Keine neuen Dependencies.

---

## Erweiterung — Admin-Übersicht: Nutzer/Rollen (2026-09-15, auf Nutzerfreigabe)

Sechster Funktionsbereich (Nutzerentscheidung zwischen „Admin-Übersicht", „Findings Accept/Unaccept" und „Pause" — Admin-Übersicht gewählt, rundet die read-only-Phase des Control Centers ab).

- `GET /api/v1/admin/users` (mind. `AccessLevel.ADMIN`) — liest `data/user_data.json` über `services/user_data.py::load_user_data()` (dieselbe Common-Core-Extraktion aus der Statistics-Erweiterung), kein Schreibzugriff. Dünnes Schema (`telegram_id`/`role`/`navidrome_user`/`created_at`) — `permissions` bewusst nicht durchgereicht (kein 1:1-Dict-Leak). Explizit **nur Anzeige** — Rollenverwaltung (Ändern/Hinzufügen/Entfernen) bleibt vollständig der Telegram-Admin-UI vorbehalten, kein schreibender Endpunkt in diesem Schritt.
- Enthält bewusst nicht `pending_users` (wartende Neuanmeldungen) — identisches Cross-Prozess-Problem wie bei `ActiveDownloadRegistry`: das ist In-Memory-Zustand von `UserManagementHandler` im Bot-Prozess, aus `control_center/` nicht lesbar.
- **Korrektur während der Umsetzung:** Der erste Docstring-Entwurf behauptete, der Owner tauche „nie" in `user_data.json` auf. Der Smoke-Test gegen die echte Produktionsdatei widerlegte das sofort (dort steht tatsächlich ein `role="owner"`-Eintrag) — Docstring korrigiert, bevor der Code committet wurde: die Route zeigt unverändert, was in der Datei steht; maßgeblich für die AccessLevel-Auflösung bleibt ausschließlich `config.OWNER_USER_ID`, nie ein hier angezeigter `role`-Wert.
- Test: `tests/test_control_center_admin_api.py` (5 Tests) + 3 neue Authorization-Wiring-Tests in `tests/test_control_center_auth.py` — alle grün, Gesamt-Control-Center-Suite 132/132 grün.
- Manuell gegen die echten, produktiven Nutzerdaten verifiziert (2 registrierte Nutzer, Rollen `owner`/`user` korrekt gelesen — Zahl absichtlich nicht im Detail geloggt, PII-Zurückhaltung).
- Keine neuen Dependencies, keine neue UI (bewusst nur API — bisher noch kein "Admin"-Panel im Dashboard, analog zur ursprünglichen Health-only-UI vor dem Dashboard-Nachtrag).

---

## Erweiterung — Findings Accept/Unaccept: erster schreibender Endpunkt (2026-09-17, auf Nutzerfreigabe)

Nach Abschluss der read-only-Phase (Nutzerentscheidung zwischen "erst alle read-only-Bereiche" und "nächster größerer Schritt" — Letzteres gewählt): erster schreibender Control-Center-Endpunkt überhaupt.

**Risikoeinordnung (bewusst kein volles Preview→Diff→Confirm→Execute-Schwergewicht à la Master-Prompt Abschnitt 21):** `accept_finding()`/`unaccept_finding()` verändern ausschließlich den Review-Status in der Findings-Registry (Metadaten außerhalb der Library) — niemals eine Library-Datei, vollständig reversibel (`unaccept_finding()` existiert exakt für die Rücknahme). Kein Executor wird aufgerufen. Damit deutlich risikoärmer als eine künftige Repair-Execution — ein leichtgewichtiger Client-seitiger Bestätigungsdialog reicht, kein serverseitiger Mehrstufen-Flow.

- `POST /api/v1/library/findings/{finding_id}/accept` (Body: `{"reason": str}`, Pflichtfeld — leer/nur Whitespace → `422 REASON_REQUIRED`) und `POST .../unaccept` (Body optional: `{"note": str}`) — beide mind. `AccessLevel.ADMIN`, dünne Wrapper um die bestehenden, produktiv genutzten `services/library_health/findings.py::accept_finding()`/`unaccept_finding()` (identischer Kern wie `scripts/library_health_review.py`).
- **CSRF-Schutz (Nachtrag zum offenen Punkt aus der ursprünglichen Security-Checkliste, Abschnitt 6):** neue `control_center/dependencies.py::verify_same_origin()`-Dependency, nur auf den beiden schreibenden Routen. Primärer Schutz bleibt das bereits `samesite=strict`-Session-Cookie aus Schritt 3; der Origin-Header-Check ist eine zusätzliche, günstige Verteidigungsebene, kein volles CSRF-Token-System (unverhältnismäßig für den aktuellen, kleinen Satz an Admin-Aktionen).
- **Audit-Spur:** `reviewed_by` wird auf die authentifizierte Telegram-ID gesetzt (als String) — nutzt das bereits vorhandene `Finding.history`-Feld, kein neues Audit-System (Master-Prompt Regel 31 „Who/What/When/Result").
- Fehler-Mapping: unbekannte `finding_id` → `404 FINDING_NOT_FOUND`, leerer Grund → `422 REASON_REQUIRED`, Unaccept auf bereits offenes Finding → `409 ALREADY_OPEN` (Idempotenz-Konflikt sauber kommuniziert statt stillschweigend erfolgreich, Master-Prompt Regel 29).
- Test: 10 neue Tests in `tests/test_control_center_findings_api.py` (Accept/Unaccept-Happy-Path inkl. Verschwinden/Wiedererscheinen in der offenen Liste, leerer Grund, unbekannte ID, fehlender/falscher Origin-Header) + 2 neue Authorization-Wiring-Tests in `tests/test_control_center_auth.py` — alle grün, Gesamt-Control-Center-Suite 164/164 grün.
- Manuell verifiziert: Lesezugriff gegen die echte Produktions-Findings-Registry funktioniert unverändert (5 Kategorien); der CSRF-Check wurde mit einem absichtlich falschen Origin-Header UND einer nicht-existenten Finding-ID getestet (sicher, keine reale Mutation möglich) — echtes Accept/Unaccept gegen produktive Findings-Daten bewusst NICHT als Smoke-Test ausgeführt (reale Zustandsänderung, nicht ohne gesonderte Nutzerfreigabe).
- Keine UI in diesem Schritt (bewusst API-only, analog zur Admin-Übersicht) — Accept/Unaccept-Buttons im Findings-Panel wären ein eigener, noch nicht freigegebener Folgeschritt.
- Keine neuen Dependencies.

---

## Erweiterung — Findings-Accept-UI (2026-09-17, auf Nutzerfreigabe „nächster Schritt, den du empfehlst")

Empfehlung nach Abschluss des ersten schreibenden Endpunkts: den bereits gebauten Accept-Endpunkt tatsächlich nutzbar machen, statt einen neuen Funktionsbereich zu beginnen. **Unaccept bewusst nicht mit umgesetzt** — dafür fehlt weiterhin ein Lese-Endpunkt für akzeptierte Findings (`get_accepted_findings()` existiert produktiv, aber `control_center/` exponiert ihn noch nicht), eigener Folgeschritt.

- `control_center/templates/dashboard.html`: Findings-Panel zeigt jetzt pro Kategorie die einzelnen offenen Findings (Pfad/Artist/Album/Titel als Label, volle Meldung als Tooltip) mit einem "Akzeptieren"-Button. Klick → `window.prompt()` für den Pflicht-Grund → `window.confirm()` als leichte Bestätigung (kein volles Preview/Diff, proportional zum bereits in der API-Erweiterung begründeten Risiko: nur Registry-Status, nie eine Library-Datei) → `POST .../accept` mit `credentials: "same-origin"` (Cookie-Auth) → bei Erfolg wird die Findings-Liste neu geladen (akzeptiertes Finding verschwindet sichtbar aus der offenen Liste).
- **Sicherheitsnachtrag beim Anfassen derselben Stelle entdeckt und mitbehoben:** die vier `render*()`-Funktionen (Findings/Downloads/Statistics, neu seit dem Dashboard-Nachtrag) betteten Titel/Artist/Pfad/Message-Felder aus Library-/Download-Metadaten (z. B. YouTube-Videotitel) bislang ungefiltert per `innerHTML` ein — ein präparierter Titel hätte Skript-Inhalt einschleusen können (XSS). Neuer `_escapeHtml()`-Helper, konsequent auf allen betroffenen Feldern angewendet (auch rückwirkend in Downloads/Statistics, nicht nur im neuen Findings-Code). Interne, bereits enum-artige Werte (Status-Codes, Severity-Tiers, Zahlen) blieben unverändert, da dort kein Risiko besteht.
- Test: `tests/test_control_center_ui.py` von 8 auf 10 Tests erweitert (Accept-Verdrahtung im Markup vorhanden, `_escapeHtml()`-Helper existiert und wird tatsächlich verwendet, nicht nur definiert) — alle grün, Gesamt-Control-Center-Suite 98/98 grün.
- Manuell verifiziert: Dashboard-Shell rendert weiterhin korrekt gegen die echte Produktionsumgebung (Accept-Buttons entstehen client-seitig nach dem Findings-Fetch, daher serverseitig 0 im initialen HTML — erwartet). Kein echter Accept-Klick gegen produktive Findings-Daten ausgeführt (identische Zurückhaltung wie beim API-Schritt).
- Keine neuen Dependencies.

---

## Erweiterung — Accepted Findings + Unaccept-Fertigstellung (2026-09-17, auf Nutzerfreigabe)

Schließt den in den beiden vorangegangenen Schritten bewusst offen gelassenen Review-Kreislauf: akzeptierte Findings sind jetzt im Web sichtbar und über einen "Reaktivieren"-Button zurücknehmbar (`unaccept_finding()` war bereits seit dem ersten schreibenden Schritt produktiv, nur ohne Lese-Endpunkt/UI dafür).

- `GET /api/v1/library/findings/accepted?limit=` (mind. `AccessLevel.ADMIN`, identisch zur bestehenden Findings-Schwelle) — dünner Wrapper um `services/library_health/findings.py::get_accepted_findings()`. Anders als `FindingSchema` (offene Findings) zeigt `AcceptedFindingSchema` bewusst die Review-Metadaten (`reviewed_at`/`reviewed_by`/`review_note`/`present_in_latest_scan`) — das IST hier der Anzeigezweck (Auditierbarkeit, Master-Prompt Regel 31).
- Dashboard: neuer Toggle "Akzeptierte Findings anzeigen" im Findings-Panel — **lazy geladen**, nicht Teil des 30s-Polling/Auto-Loads (bewusste Entscheidung, siehe Korrektur unten). Jeder Eintrag mit "Reaktivieren"-Button (leichter `confirm()`-Dialog, identisches Risikoprofil wie Accept — nur Registry-Status, reversibel).
- **Korrektur vor dem Commit (Smoke-Test-Fund):** Der erste Entwurf sendete/renderte die komplette akzeptierte Liste ungekürzt. Der Smoke-Test gegen die echte Produktions-Registry zeigte **1173 akzeptierte Findings** (historisch über Telegram/CLI akzeptiert) — dieselbe, im Repair-Plan-Schritt bereits bewusst vermiedene Falle (dort: 1114 Kandidaten), hier zunächst übersehen. Noch vor dem Commit korrigiert: `limit`-Query-Parameter (Default 50, max 500, wie bei Downloads), `total` im Response-Schema ergänzt, UI zeigt bei Kürzung „Zeige X von Y" an.
- Test: `tests/test_control_center_findings_api.py` von 19 auf 21 erweitert (inkl. des Limit/Total-Nachtrags) + `tests/test_control_center_ui.py` von 10 auf 11 — alle grün, Gesamt-Control-Center-Suite 105/105 grün.
- Manuell gegen die echte Produktions-Registry verifiziert: `limit=50` liefert korrekt 50 von 1173 — der Fix wurde nicht nur getestet, sondern auch gegen die tatsächlichen Daten bestätigt, die das Problem ursprünglich aufgedeckt hatten.
- Keine neuen Dependencies.

---

## Erweiterung — Admin-Übersicht-UI (2026-09-17, auf Nutzerfreigabe)

Letzter bisher API-only-Bereich bekommt eine Dashboard-Ansicht (reines Frontend, `routers/`/`schemas/admin.py` unverändert) — rundet das "jeder Bereich hat eine Oberfläche"-Bild ab, bevor der nächste große Schritt (Jobs-Grundgerüst/Repair-Execution) beginnt.

- Neues Panel "Admin: Nutzer & Rollen" zeigt Telegram-ID, Rolle (farbcodiertes Badge, wiederverwendet die bereits vorhandenen Severity-Tier-CSS-Klassen: owner→CRITICAL, admin→ERROR, moderator→WARNING, user→INFO), Navidrome-Zuordnung, Registrierungsdatum.
- Im normalen 30s-Polling/Auto-Load/Refresh-Button (wie Findings/Downloads/Statistics/Navidrome-Status) — anders als Repair-Plan (voller Scan) oder Accepted-Findings (potenziell sehr groß) ist `GET /api/v1/admin/users` ein kleiner, günstiger Read ohne Skalierungsrisiko (aktuell 2 Einträge in Produktion).
- Für nicht-Admin-Rollen greift der bereits bestehende 403-„Keine Berechtigung"-Pfad von `_loadInto()` — kein separater Code nötig.
- Test: `tests/test_control_center_ui.py` von 11 auf 12 Tests erweitert — alle grün, Gesamt-Control-Center-Suite 106/106 grün.
- Manuell gegen die echten Produktionsdaten verifiziert (Panel rendert, 2 Nutzer korrekt geladen).
- Keine neuen Dependencies, keine Backend-Änderung.

---

## Erweiterung — Jobs-Grundgerüst, Phase 1 (2026-09-17, auf Nutzerfreigabe)

Erster Teilschritt des größeren, vom Nutzer freigegebenen Vorhabens "Jobs-Grundgerüst Richtung Repair-Execution" — bewusst in zwei Teilschritte aufgeteilt (Nutzerentscheidung auf Nachfrage): **Phase 1 = nur Infrastruktur, noch keine echte Ausführung.** Repair-Execution als erster echter Job-Typ ist ein eigener, separat freizugebender Folgeschritt.

- Neues `services/jobs/` (Telegram-frei, analog zu `services/library_health/`/`services/library_repair/`): `models.py` (`Job`-Dataclass, `JobStatus`-Enum: PENDING/RUNNING/SUCCEEDED/FAILED/CANCELLED) + `job_registry.py::JobRegistry` — Zustandsmuster identisch zu `services/downloader/active_downloads.py::ActiveDownloadRegistry` (EINE Instanz pro Prozess, `threading.Lock` statt `asyncio.Lock`, weil sowohl async Tasks als auch sync Route-Handler zugreifen; kooperatives Abbrechen über `threading.Event`, identisch zu `ActiveDownload.request_cancel()`).
- **Architekturentscheidung, die sich von den bisherigen Registries unterscheidet:** die JobRegistry liegt NICHT als Modul-Level-Singleton (wie ursprünglich naheliegend), sondern in `app.state.job_registry` (`control_center/app.py`), per FastAPI-Dependency injiziert. Grund: anders als `FindingsRegistry`/`DownloadHistoryStore` (dateibasiert, "frisch pro Request" teilt sich automatisch über die Datei) ist die JobRegistry rein In-Memory — ein Modul-Level-Global hätte sich unkontrolliert über alle Tests hinweg geteilt. `app.state` sorgt dafür, dass jeder `create_app()`-Aufruf (wie ihn bereits jeder bestehende Test macht) automatisch eine isolierte Registry bekommt, ohne einen eigenen Reset-Mechanismus zu brauchen.
- `GET /api/v1/jobs?limit=` + `GET /api/v1/jobs/{job_id}` (Lesen) + `POST /api/v1/jobs/demo` + `POST /api/v1/jobs/{job_id}/cancel` (schreibend, `verify_same_origin()`-CSRF-geschützt wie Findings Accept/Unaccept) — alle mind. `AccessLevel.ADMIN`.
- **Nur ein einziger, ausdrücklich als Test-/Demo-Fähigkeit gekennzeichneter Job-Typ** (`demo_progress`, Pfad `/demo` statt eines allgemein klingenden Namens) — läuft 5 Schritte à 1 Sekunde hoch, führt keine reale Operation aus (Master-Prompt Regel 39: keine Fake-Implementierung, die wie eine fertige Funktion aussieht — der Name macht unmissverständlich klar, dass hier nichts Echtes passiert).
- Test: `tests/test_job_registry.py` (17 Tests, reine Registry-Logik ohne FastAPI) + `tests/test_control_center_jobs_api.py` (12 Tests, inkl. Demo-Job-Lebenszyklus PENDING→RUNNING→SUCCEEDED, Abbruch vor Fertigstellung, CSRF, Limit) + 3 neue Authorization-Wiring-Tests in `tests/test_control_center_auth.py` — alle grün, Gesamt-Control-Center-Suite 138/138 grün.
- Manuell gegen einen echten laufenden `uvicorn`-Prozess verifiziert (nicht nur den In-Process-Testclient): kompletter Lebenszyklus PENDING→RUNNING→SUCCEEDED über mehrere echte HTTP-Requests hinweg, exakt nach 5 Sekunden abgeschlossen — ungefährlich, da der Demo-Job keinerlei reale Seiteneffekte hat.
- Keine UI in diesem Schritt (eine Job-UI wäre erst mit einem echten Job-Typ sinnvoll, nicht für eine reine Demo-Fähigkeit).
- Keine neuen Dependencies.

**Offen für den separat freizugebenden Folgeschritt (Phase 2):** Repair-Execution als erster echter Job-Typ (`scripts/library_repair.py` als Subprozess, analog zum bestehenden `doctor_runner.py`-Muster für SAFE_AUTOMATIC-Reparaturen) + zugehörige UI.

---

## Erweiterung — Jobs-Grundgerüst, Phase 2: Repair-Execution als erster echter Job-Typ (2026-09-17, auf Nutzerfreigabe)

Zweiter Teilschritt des größeren Vorhabens — erste genuin destruktive, dateiverändernde Fähigkeit im Control Center überhaupt. Nutzerentscheidung auf Nachfrage (drei Optionen: welche Reparaturstufe, Subprozess-Wiederverwendung, Einzel-Finding vs. Bulk): **die bestehende "🩺 MusicBot Doctor"-Telegram-Fähigkeit 1:1 nachbilden**, keine neue Granularität erfinden.

- Neuer Job-Typ `repair_safe_automatic` (`POST /api/v1/jobs/repair-safe-automatic`) bildet `handlers/library_doctor_handler.py::handle_apply_safe_confirmed()` exakt nach: Health-Scan + `SAFE_AUTOMATIC`-Apply über die bereits produktiven `services/library_repair/doctor_runner.py::run_health_scan()`/`run_safe_automatic_repair()`-Subprozess-Funktionen (Backup/Rollback/Journal bereits dort abgesichert) — **keine neue Ausführungslogik**, nur eine neue Tür (Web statt Telegram) zu einer bestehenden Fähigkeit. Bewusst nur dieser eine Level (kein Netzwerk, kein Re-Encode) — identische Sicherheitsgrenze wie `doctor_runner.py` selbst.
- **"Preview" ist bewusst kein neuer Mechanismus** — das bereits vorhandene `GET /api/v1/library/repair-plan` zeigt schon vorher die Anzahl `SAFE_AUTOMATIC`-Kandidaten, bevor der Job gestartet wird.
- **Kooperatives Abbrechen nur zwischen Scan und Repair** (Prüfung von `is_cancel_requested()` nach dem Scan, vor dem Start des Repair-Subprozesses) — explizit dokumentierte Grenze, kein Kill eines bereits laufenden Subprozesses möglich (`doctor_runner.py::_run_subprocess()` kapselt den Prozess-Handle vollständig). Keine verschleierte Lücke (Master-Prompt Regel 39), sondern eine bewusst benannte Einschränkung.
- `JobRegistry.mark_failed()` um ein optionales `result`-Feld erweitert, damit ein fehlgeschlagener Job trotzdem Diagnosedaten (z. B. Subprozess-stdout bei Exit-Code ≠ 0) mitliefern kann.
- Test: `tests/test_control_center_jobs_api.py` von 12 auf 19 Tests erweitert (Erfolg, Scan-Fehler verhindert Repair-Start, Timeout, nicht-null Exit-Code mit Diagnosedaten, Abbruch zwischen Scan und Repair, CSRF, Initiator-Aufzeichnung) + 1 neuer Test in `tests/test_job_registry.py` — alle grün, Gesamt-Control-Center-Suite 146/146 grün, plus Regression `tests/test_doctor_runner.py`/`test_library_doctor_handler.py`/`test_rich_menu_doctor.py` (73 Tests) weiterhin grün (Telegram-Pfad unverändert).
- **Kein Live-Smoke-Test gegen die echte Library** — anders als der Demo-Job würde ein echter Aufruf sofort `--level SAFE_AUTOMATIC --apply` gegen die Produktionsbibliothek auslösen (Dateien umbenennen, Tags schreiben). Stattdessen gegen einen echten laufenden Prozess nur sicher verifiziert: Route existiert (`GET /api/v1/jobs`) und CSRF-Check greift (falscher Origin lässt den Job nie anlaufen) — echte Ausführung wurde nie ausgelöst.
- **Keine UI in diesem Schritt** — bei der ersten echten, dateiverändernden Fähigkeit soll das UX (Start-Button, Fortschrittsanzeige, Bestätigungstext) als eigener, separat zu besprechender Schritt entstehen, nicht stillschweigend mitgeliefert werden.
- Keine neuen Dependencies.

---

## Erweiterung — Repair-Job-UI (2026-09-20, auf Nutzerfreigabe des vorab abgestimmten UX-Vorschlags)

UX für die erste dateiverändernde Fähigkeit — vorab mit dem Nutzer abgestimmt (Vorschlag vorgelegt, bestätigt), nicht stillschweigend mitgeliefert.

- Start-Button **im bestehenden Repair-Plan-Panel** (keine neue Sektion) — bleibt `disabled`, bis mindestens einmal ein Repair-Plan geladen wurde (`renderRepairPlan()` schaltet ihn frei und trägt die aktuelle `SAFE_AUTOMATIC`-Kandidatenzahl in den Button-Text ein). Kein Rätselraten über die Anzahl im Bestätigungsdialog.
- `window.confirm()` vor dem Start nennt explizit die Kandidatenzahl, den Backup-/Rollback-Hinweis und dass tatsächlich Dateien verändert werden (Master-Prompt Regel 11: Bestätigung muss verständlich machen, was passiert, nicht nur "Sicher?").
- Nach dem Start: 1s-Polling über `GET /api/v1/jobs/{job_id}` (nutzt die bestehende Jobs-Infrastruktur unverändert) — zeigt Status/Fortschritt/Nachricht während `PENDING`/`RUNNING`, bei Abschluss Erfolg (inkl. `stdout_tail`) oder Fehler (inkl. Diagnose-Ausgabe aus `Job.result`) an. Kein separates neues Panel.
- **Abbrechen-Button** erscheint nur während `PENDING`/`RUNNING`, ruft `POST /{job_id}/cancel` (bestehender Endpunkt). UI-Kommentar macht explizit klar, dass der Abbruch nur zwischen Scan und Repair wirkt, kein sofortiger Kill (identische, bereits im Router dokumentierte Einschränkung, nicht verschleiert).
- Test: `tests/test_control_center_ui.py` von 12 auf 15 Tests erweitert (Start-Button initial disabled, komplette JS-Verdrahtung vorhanden, Bestätigungsdialog erwähnt Backup + Dateien) — alle grün, Gesamt-Control-Center-Suite 131/131 grün.
- **Weiterhin kein Live-Smoke-Test gegen die echte Library** — nur sicher verifiziert, dass der Start-Button im initialen HTML tatsächlich `disabled` ist (keine versehentliche Ausführung durch einen Rendering-Fehler möglich).
- Keine neuen Dependencies, keine neue API-Fläche (reine Frontend-Verdrahtung auf bereits vorhandenen Endpunkten).

**Nachtrag (2026-09-20, Live-Smoke-Test durch den Nutzer vor Merge):** erster echter End-to-End-Klick auf "SAFE_AUTOMATIC reparieren" gegen die Produktionsbibliothek — Job lief PENDING→RUNNING→SUCCEEDED sauber durch, aber 0 Kandidaten ausgeführt (Screenshot-Beleg: Panel zeigte vorher bereits korrekt "SAFE_AUTOMATIC reparieren (0)"). **Kein Bug**, sondern korrekte Konsequenz der bestehenden `services/library_repair/planner.py`-Kategorisierung: `actionable_total` (hier 1114) summiert **alle** `DISPOSITION_AUTO_REPAIR`-Level (`SAFE_AUTOMATIC` + `METADATA_REPROCESSING` + `EXTERNAL_METADATA` + `COVER` + `LOUDNESS` + `DUPLICATE`), während der Job bewusst nur `RepairLevel.SAFE_AUTOMATIC` ausführt (identische enge Grenze wie der bestehende Telegram-Doctor, siehe Phase-2-Eintrag oben). Bei diesem Bibliotheksstand lagen alle 1114 aktuell offenen Kandidaten in COVER/EXTERNAL_METADATA/METADATA_REPROCESSING — Level, die laut `doctor_runner.py` bewusst nur auf ausdrückliche `--level`/`--issue`-Anforderung laufen, nicht über SAFE_AUTOMATIC.

Als kleine UX-Klarstellung (gleicher Branch, vor Merge, Nutzerfreigabe): der Vorschau-Text im Repair-Plan-Panel benennt jetzt explizit, dass `actionable_total` alle Level zusammenfasst und wie viele davon tatsächlich `SAFE_AUTOMATIC` (= per Button ausführbar) sind, statt nur die Gesamtzahl direkt über dem SAFE_AUTOMATIC-Button zu zeigen. `tests/test_control_center_ui.py` von 15 auf 16 Tests erweitert — alle grün, Regression `test_control_center_repair_api.py` (12) + `test_control_center_jobs_api.py` (12) weiterhin grün.

---

## Erweiterung — Level-2/Level-3-Reparatur, Pro-Artist API (2026-09-20, auf Nutzerfreigabe)

Erste API-Ebene für die zweite Klasse dateiverändernder Fähigkeiten —
Pendant zur bereits produktiven Telegram-Fähigkeit `l23rep:*`
(`docs/LIBRARY_REPAIR.md` §12, ARCH-033). **Cover bleibt bewusst
außen vor**, identisch zur ARCH-033-eigenen Scope-Entscheidung ("COVER/
LOUDNESS/DUPLICATE bleiben CLI-only") — auf Nachfrage vom Nutzer
ausdrücklich bestätigt, keine neue, in Telegram nirgends existierende
Fähigkeit einzuführen.

- **`GET /api/v1/library/repair-plan/by-artist`** (`control_center/routers/repair.py`) —
  eigener, frischer Scan (wie `GET /repair-plan`), gruppiert per
  `services/library_repair/planner.py::group_candidates_by_artist()`
  (bereits vorhandene, reine Funktion, Default-Filter: nur L2/
  METADATA_REPROCESSING + L3/EXTERNAL_METADATA) — identische
  Gruppierungslogik wie die Telegram-Artist-Liste, keine eigene
  Aggregation im Router.
- **`POST /api/v1/jobs/repair-level2` / `POST /api/v1/jobs/repair-level3`**
  (`control_center/routers/jobs.py`, Body: `{"artist": "..."}`, analog
  `AcceptFindingRequest`) — neue Job-Kinds `repair_level2`/
  `repair_level3`. Rufen **nicht** wie `repair_safe_automatic` die
  rohen `doctor_runner.py`-Subprozessfunktionen auf, sondern
  `services/library_repair/repair_service.py::execute_level2_repair()`/
  `execute_level3_repair()` — dieselbe höhere Orchestrierungsebene, die
  auch der Telegram-`l23rep:*`-Subflow nutzt (Health-Scan +
  Stale-Plan-Schutz + Subprozess + Verification-Rescan +
  Run-History-Eintrag, inkl. desselben prozessübergreifenden
  `acquire_repair_lock()`/`release_repair_lock()` wie Telegram/CLI).
  **Bewusste Abweichung vom SAFE_AUTOMATIC-Präzedenzfall**, weil beide
  Telegram-Pfade selbst unterschiedliche Ebenen nutzen (Doctor ruft
  `doctor_runner.py` direkt auf, `l23rep:*` ruft `repair_service.py`
  auf) — hier wurde jeweils exakt der bestehende Pfad gespiegelt, nicht
  vereinheitlicht.
- **`RepairAlreadyRunningError`** (gemeinsamer Lock mit Telegram/CLI)
  wird abgefangen und der Job kontrolliert als `FAILED` mit
  verständlicher Fehlermeldung beendet, statt eines rohen 500ers oder
  eines unbemerkt hängenden Jobs.
- **Bewusst kein globaler Batch-Button** — identisch zu ARCH-033/
  ADR-0003: L2/L3 sind ausschließlich pro Artist ausführbar, die
  Artist-Auswahl kommt aus dem neuen `by-artist`-Endpoint.
- **Kooperatives Abbrechen ist für diese beiden Job-Typen NICHT
  wirksam** — `execute_level2_repair()`/`execute_level3_repair()` sind
  ein einzelner atomarer `await` ohne Zwischen-Checkpoint (anders als
  `repair_safe_automatic`, das Scan und Repair als zwei getrennte
  Aufrufe mit einer `is_cancel_requested()`-Prüfung dazwischen hat).
  Der generische `POST /{job_id}/cancel`-Endpunkt bleibt technisch
  erreichbar, hat für `repair_level2`/`repair_level3` aber keine
  Wirkung — im Router-Docstring explizit dokumentiert (Master-Prompt
  Regel 39: keine vorgetäuschte Fähigkeit). Der UI-Folgeschritt zeigt
  für diese Job-Typen konsequenterweise keinen Abbrechen-Button.
- Test: `tests/test_control_center_repair_api.py` um 4 Tests erweitert
  (by-artist-Gruppierung gegen eine echte, per ffmpeg erzeugte
  Testdatei charakterisiert — L2/L3-Zahlen aus tatsächlichem
  Scan-Ergebnis übernommen, nicht angenommen), `tests/test_control_center_jobs_api.py`
  um 11 Tests erweitert (Erfolg, 0-Kandidaten-SKIPPED zählt als
  Job-Erfolg, Fehlschlag mit Diagnosedaten, Lock-Konflikt, leerer
  Artist-Name, CSRF, Initiator-Aufzeichnung — jeweils für L2 und L3
  parametrisiert) — alle grün, Gesamt-Control-Center-Suite 176/176
  grün. Regression: `tests/test_repair_service_level23.py` +
  `tests/test_library_repair_planner.py` + `tests/test_repair_handler_level23.py`
  + `tests/test_doctor_runner.py` (91 Tests, Telegram-/CLI-Pfad
  unverändert) weiterhin grün.
- **Kein Live-Smoke-Test gegen die echte Library** — ein echter Aufruf
  würde sofort `--artist X --level METADATA_REPROCESSING/EXTERNAL_METADATA
  --apply` gegen die Produktionsbibliothek auslösen. Nur gegen einen
  echten laufenden Prozess sicher verifiziert: beide Routen sind
  erreichbar, CSRF-Check greift.
- **Kein UI in diesem Schritt** — Artist-Auswahl + L2/L3-Aktionswahl +
  Bestätigung ist ein eigener, separat zu besprechender Folgeschritt
  (analog zum SAFE_AUTOMATIC-Präzedenzfall: erst API, dann UI).
- Keine neuen Dependencies.

---

## Erweiterung — Level-2/Level-3-Reparatur, Pro-Artist UI (2026-09-20, auf Nutzerfreigabe)

UI-Folgeschritt zum vorherigen Eintrag — eigenes neues Panel „L2/L3-
Reparaturen (nach Artist)" direkt unter dem bestehenden Repair-Plan-Panel.

- **Eigener manueller Trigger** (`#level23-plan-btn`, kein Auto-Load) —
  identisches Prinzip wie das Repair-Plan-Panel: `GET .../repair-plan/by-artist`
  ist ein voller Library-Scan, bewusst nicht Teil des 30s-Pollings.
- Pro Artist-Zeile ein oder zwei Buttons (`L2 (n)`/`L3 (m)`), nur
  gerendert, wenn die jeweilige Kandidatenzahl > 0 ist — kein globaler
  Batch-Button (ADR-0003, identisch zu Telegram).
- `window.confirm()` vor dem Start nennt Artist, Level-Klartext
  (L2 = volle Metadaten-Pipeline erneut, L3 = MusicBrainz/Netzwerk, kann
  pro Datei fehlschlagen), Kandidatenzahl aus der zuletzt geladenen
  Vorschau und den Backup-/Dateiänderungs-Hinweis — bei L3 zusätzlich
  einen expliziten Netzwerk-/Rate-Limit-Warnhinweis (Master-Prompt
  Regel 11).
- Nach dem Start: 1s-Polling über das bereits vorhandene
  `GET /api/v1/jobs/{job_id}` — Ergebnis-Anzeige nutzt die im
  Job-`result` mitgelieferten Zähler (`success`/`skipped`/`failed`/
  `resolved_count`/`affected_files`) statt nur eines rohen Exit-Codes,
  da `execute_level2_repair()`/`execute_level3_repair()` (anders als
  `run_safe_automatic_repair()`) diese bereits strukturiert liefern.
- **Bewusst KEIN Abbrechen-Button** — anders als beim SAFE_AUTOMATIC-Panel.
  `execute_level2_repair()`/`execute_level3_repair()` sind ein einzelner
  atomarer `await` ohne Zwischen-Checkpoint (bereits im API-Schritt
  dokumentiert); ein Abbrechen-Button hier hätte keine Wirkung gehabt —
  bewusst nicht gebaut statt einer vorgetäuschten Fähigkeit (Master-Prompt
  Regel 39). Alle `.level23-btn`-Buttons werden während eines laufenden
  Jobs deaktiviert (verhindert parallele Starts), reaktiviert bei
  Abschluss/Fehlschlag.
- Test: `tests/test_control_center_ui.py` von 16 auf 20 Tests erweitert
  (Panel-Präsenz, JS-Verdrahtung, Abwesenheit eines Cancel-Buttons als
  expliziter Test, Bestätigungsdialog erwähnt Backup/Dateien/MusicBrainz)
  — alle grün, Gesamt-Control-Center-Suite 181/181 grün. JS-Syntax mit
  `node --check` gegen den extrahierten `<script>`-Block verifiziert.
- **Kein Live-Smoke-Test gegen die echte Library** — identische
  Begründung wie beim API-Schritt (ein echter Klick würde sofort
  `--apply` gegen die Produktionsbibliothek auslösen). Nur sicher
  verifiziert: Panel/Verdrahtung im initialen HTML vorhanden, kein
  Cancel-Button vorhanden.
- Keine neuen Dependencies, keine neue API-Fläche (reine
  Frontend-Verdrahtung auf den im vorherigen Schritt hinzugefügten
  Endpunkten).

---

## Erweiterung — Statistics Cross-User-Admin-Ansicht (2026-09-20, auf Nutzerfreigabe)

Schließt einen der beiden seit dem Statistics-Schritt offenen Punkte
(„Offen für eine künftige Freigabe" oben). Reine Lesefunktion, kein
Risiko — natürliche Ergänzung zur bereits vorhandenen Admin-
Nutzerübersicht (`routers/admin.py` liefert `navidrome_user` bereits pro
Zeile mit).

- **`GET /api/v1/statistics/{navidrome_username}`** (`control_center/routers/statistics.py`) —
  ruft wie `/me` ausschließlich `StatistikService.generate_stats()` auf,
  diesmal mit dem Navidrome-Username direkt aus dem Pfad statt über die
  eigene Telegram-ID→Navidrome-Zuordnung aufgelöst. Kein neuer
  Endpunkt zur Namensauflösung nötig — die Admin-Nutzerübersicht liefert
  den Namen bereits.
- **Schwelle bewusst höher als der Rest des Routers:** Router-Level bleibt
  `AccessLevel.USER` (für `/me`), diese eine Route bekommt zusätzlich
  `dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))]`
  auf Route-Ebene — erster Präzedenzfall im Control Center für eine
  Route-spezifische, strengere Schwelle innerhalb eines sonst
  niedrigschwelligeren Routers (Standard-FastAPI-Mechanismus, additive
  Dependency neben der Router-Level-Dependency).
- **Pfadkollisionsfreiheit bereits im Statistics-Schritt vorbereitet**
  (`/me` als literaler Pfad zuerst registriert, gewinnt gegen
  `/{navidrome_username}`) — keine Änderung an `/me` nötig.
- Unbekannter `navidrome_username` liefert `has_data=false` (identisches
  Verhalten wie bei `/me` ohne Historie) statt eines Fehlers — kein
  Informationsleck über Existenz eines Nutzers, da die Antwortform
  identisch zu "kein Verlauf" ist.
- Test: `tests/test_control_center_statistics_api.py` um 4 Tests erweitert,
  `tests/test_control_center_auth.py` um 2 Tests (ADMIN-Schwelle:
  403 für USER, 200 für ADMIN) — alle grün, Gesamt-Control-Center-Suite
  187/187 grün.
- **Kein UI in diesem Schritt** (bewusst API-only, analog zum
  Admin-Übersicht-Präzedenzfall) — eine Anzeige (z. B. anklickbarer
  `navidrome_user` im Admin-Nutzer-Panel) wäre ein eigener,
  separat zu besprechender Folgeschritt.
- Keine neuen Dependencies.

---

## Erweiterung — Genre-Statistik & Music DNA (2026-09-20, auf Nutzerfreigabe)

Schließt den zweiten der beiden seit dem Statistics-Schritt offenen
Punkte. Reines Mapping über bereits produktive `StatistikService`-Methoden.

- **`GET /api/v1/statistics/me/genres`** — mappt
  `generate_genre_stats()` (All-Time, `top_n`-Query-Param, Default 10).
- **`GET /api/v1/statistics/me/music-dna`** — mappt `generate_music_dna()`
  (All-Time-Hörprofil: Genre-/Artist-Anteile, Tageszeit-Verteilung,
  Repeat-Rate; `top_n`-Query-Param, Default 5).
- Beide bewusst nur **„/me"** in diesem Schritt (kein Cross-User-Pendant)
  — kleinster sinnvoller Schritt, analog dazu, dass die reguläre
  Cross-User-Statistik ebenfalls ein separat freigegebener Folgeschritt
  war (siehe vorheriger Eintrag). Zwei Pfadsegmente kollidieren nicht mit
  dem einsegmentigen `/{navidrome_username}` (Starlette prüft die
  Segmentzahl beim Pfad-Matching).
- Telegram-ID→Navidrome-Username-Auflösung (404 bei fehlender
  Konfiguration) in `_resolve_own_navidrome_username()` aus
  `get_my_statistics()` extrahiert und von allen drei „/me"-Endpunkten
  gemeinsam genutzt — reiner Refactor ohne Verhaltensänderung (bestehender
  `/me`-Test bleibt unverändert grün).
- `has_data=False` bildet „keinerlei Verlaufsdaten" ab (identische
  Semantik zu `/me`); ein vorhandener Verlauf ohne auswertbare
  Genre-Angaben liefert `has_data=True` mit leeren Listen (Quell-Semantik
  von `generate_genre_stats()` unverändert übernommen).
- Test: `tests/test_control_center_statistics_api.py` um 10 Tests
  erweitert (404/leer/Zählung/`top_n` je Endpunkt) — alle grün,
  Regression `tests/test_control_center_auth.py` + `tests/test_statistik_service.py`
  (71 Tests) sowie Gesamt-Control-Center-Suite (195/195) grün.
- **Kein UI in diesem Schritt** (analog zum vorherigen Statistics-Schritt).
- Keine neuen Dependencies.
