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

### Nachtrag (2026-09-20): Reverse-Proxy-Subpath

Betrieb hinter nginx unter `/controlcenter/` ist umgesetzt (`X-Forwarded-Prefix` → `scope["root_path"]`, `base_path`/`apiUrl()`, Cookie-Path). Konfiguration, Pflicht-Header und Verifikationsumfang: [`docs/CONTROL_CENTER_REVERSE_PROXY.md`](../CONTROL_CENTER_REVERSE_PROXY.md).

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

---

## Erweiterung — Genre-Statistik & Music DNA UI (2026-09-20, auf Nutzerfreigabe)

UI-Folgeschritt zum vorherigen Eintrag — erweitert das bestehende
Statistics-Panel (kein neues Panel) um zwei zusätzliche Content-Bereiche.

- `#genre-stats-content` (Top-5-Genres, Play-Zahl) und
  `#music-dna-content` (Plays/eindeutige Songs/Wiederholungsrate,
  Tageszeit-Verteilung, Top-5-Genre-/Artist-Anteile in %) direkt unter
  dem bestehenden `#statistics-content` im selben Panel.
- `loadGenreStats()`/`loadMusicDna()` nutzen den bereits vorhandenen
  `_loadInto()`-Helper (identisches Lade-/Fehlerbehandlungs-Muster wie
  `loadStatistics()`) — keine neue Fetch-Logik.
- In `checkAuthAndLoad()`, dem `refresh-btn`-Handler und dem 30s-Polling
  ergänzt — beide Endpunkte sind reine, günstige JSON-Reads (identische
  Kategorie wie `/me`, anders als der volle Library-Scan des
  Repair-Plans).
- Test: `tests/test_control_center_ui.py` von 20 auf 21 Tests erweitert
  (Panel-Präsenz, JS-Verdrahtung) — alle grün, Gesamt-Control-Center-Suite
  196/196 grün. JS-Syntax mit `node --check` verifiziert.
- Kein Live-Smoke-Test gegen die echte Library nötig (reine Lesefunktion,
  kein Risiko) — dennoch nicht durchgeführt, da kein Browser verfügbar;
  Wiring per HTTP-Test verifiziert.
- Keine neuen Dependencies, keine neue API-Fläche (reine
  Frontend-Verdrahtung auf den im vorherigen Schritt hinzugefügten
  Endpunkten).

---

## Erweiterung — Cross-User-Statistik in der Admin-Übersicht (2026-09-20, auf Nutzerfreigabe)

Letzter der drei seit dem ursprünglichen Statistics-Schritt offenen
Punkte — macht den bereits fertigen `GET /api/v1/statistics/{navidrome_username}`-
Endpunkt (Admin-only) tatsächlich im Web nutzbar, statt nur über
Swagger/`curl` erreichbar zu sein.

- Pro Admin-Nutzer-Zeile ein `Statistik`-Button, nur gerendert, wenn
  `navidrome_user` gesetzt ist (kein Button ohne verknüpften
  Navidrome-Account — der Endpunkt bräuchte sonst ohnehin einen leeren
  Platzhalter-Namen).
- **Bewusste Wiederverwendung von `renderStatistics()`** (der bereits
  bestehenden Render-Funktion für das eigene `/me`-Panel) statt einer
  neuen Render-Funktion — `GET /{navidrome_username}` liefert exakt
  dasselbe `StatisticsResponse`-Schema wie `/me`, keine Duplikation
  nötig.
- Ergebnis erscheint in einem eigenen, initial verborgenen Bereich
  (`#admin-user-stats-content`) unterhalb der Admin-Nutzerliste, nicht
  in einem Modal/Overlay — konsistent mit dem übrigen, modal-freien
  Dashboard-Stil.
- Test: `tests/test_control_center_ui.py` von 21 auf 22 Tests erweitert
  (Button-Präsenz, JS-Verdrahtung) — alle grün, Gesamt-Control-Center-Suite
  197/197 grün. JS-Syntax mit `node --check` verifiziert.
- Keine neuen Dependencies, keine neue API-Fläche.

---

## Erweiterung — Metadata Management, erster Schritt: Tracks/Artists/Albums (2026-09-20, auf Nutzerfreigabe)

Erste Erweiterung eines im Master-Prompt (Abschnitt 7 "METADATA
MANAGEMENT") skizzierten, bis dahin komplett unbearbeiteten
Funktionsbereichs — ausgelöst durch eine vollständige Gap-Analyse des
2538-zeiligen Master-Prompts gegen den Ist-Stand (per Fork-Subagent),
die zeigte: von 11 im Prompt skizzierten V1-Funktionsbereichen waren 5
vollständig bearbeitet; Metadata Management und Logs/Diagnostics fehlten
komplett, Admin Center nur zu einem kleinen Teil.

Bewusst kleinster sinnvoller erster Schritt: **nur "Tracks anzeigen /
Artists anzeigen / Albums anzeigen"** aus der zwölfteiligen
Anforderungsliste des Prompts (Abschnitt 7) — Metadata bearbeiten,
Reprocessing starten, Mapping anzeigen, Cover verwalten, der
Preview→Diff→Confirmation→Execution→Verification-Zyklus sind eigene,
separat freizugebende Folgeschritte (der Prompt selbst listet alle
Punkte als "perspektivisch", nicht als einen einzelnen Auftrag).

- **`GET /api/v1/library/tracks`**, **`GET /api/v1/library/artists`**,
  **`GET /api/v1/library/albums`** (neues `control_center/routers/metadata.py`) —
  identischer Aufrufpfad wie `routers/health.py`/`repair.py` über
  `control_center/_library_scan.py::run_library_scan()` (ein frischer
  Library-Health-Scan) — **keine neue Scan- oder Aggregationslogik**.
  `report["files"]` (`services/library_health/models.py::FileHealth.to_dict()`)
  und `report["artists"]`/`report["albums"]`
  (`services/library_health/scoring.py::build_health_section()`) lieferten
  bereits alle benötigten Felder (Artist/Title/Album/Genre/Jahr/
  MusicBrainz-IDs/ISRC je Track; Datei-/Album-Anzahl + Health-Score je
  Artist/Album) — bei der Recherche entdeckt, nicht neu gebaut.
- **Pagination (`limit`/`offset`/`total`) von Anfang an** — diesmal
  bewusst vorab eingeplant statt erst nach einem Live-Smoke-Test
  nachgezogen (Lehre aus den beiden vorherigen Fällen: 1114
  Reparatur-Kandidaten, 1173 akzeptierte Findings).
- Bewusst NICHT durchgereicht: `states` (interner Analyse-Zustand pro
  Dimension) und `path_classification` (interne Duplicate-Detection-
  Klassifikation) — Implementierungsdetail ohne Nutzen für eine
  Browser-Ansicht (Master-Prompt Regel 9, identisches Prinzip wie das
  Weglassen von `library_root`).
- Authentifiziert mit mindestens `AccessLevel.ADMIN` (identische
  Schwelle wie Findings/Repair-Plan — granulare Pro-Datei-Daten inkl.
  Pfaden, nicht nur aggregierte Kennzahlen wie `health.py`).
- Test: neues `tests/test_control_center_metadata_api.py` (10 Tests:
  Metadata-Korrektheit, Pagination je Endpunkt, 404 bei fehlendem
  Library-Root, leere Library, Ungültiger-`limit`-422, Ausschluss
  interner Felder) — alle grün, Regression `test_control_center_health_api.py`
  + `test_control_center_repair_api.py` (13 Tests) sowie
  `tests/test_library_health*.py` (297 Tests) weiterhin grün, Gesamt-
  Control-Center-Suite 207/207 grün.
- **Kein UI in diesem Schritt** (analog zu allen bisherigen API-first-
  Schritten) — eine Browser-Ansicht (Track-/Artist-/Album-Liste mit
  Paginierung, evtl. Suchfeld) wäre ein eigener, separat zu
  besprechender Folgeschritt.
- Keine neuen Dependencies.

**Nachtrag (2026-09-20, noch vor Merge, auf Nutzerwunsch direkt im
Anschluss):** UI doch im selben Schritt ergänzt, damit die Funktion vor
dem Merge vollständig im Browser geprüft werden kann, statt nur über
Swagger/`curl`.

- Neues Panel „Library-Metadata" mit drei Buttons (Tracks/Artists/Albums)
  — jeder Klick lädt genau eine Seite (`limit=50`) über den bereits
  vorhandenen `_loadInto()`-Helper.
- **Bewusst KEINE Weiter/Zurück-Pagination-Buttons**, obwohl die API
  `limit`/`offset` unterstützt: jede Anfrage löst einen vollen
  Library-Scan aus (identisch zu Repair-Plan/L2-L3) — wiederholtes
  Blättern würde wiederholt neu scannen. Stattdessen dasselbe Muster wie
  beim Accepted-Findings-Panel: erste Seite laden, Trunkierungshinweis
  ("Zeige X von Y") bei mehr Ergebnissen, kein Auto-Rendern großer
  Listen — bewusste, dokumentierte Einschränkung statt einer teuren
  Scroll-/Blätter-Illusion.
- Test: `tests/test_control_center_ui.py` von 22 auf 25 Tests erweitert
  (Panel-Präsenz, JS-Verdrahtung, bewusste Abwesenheit von
  Pagination-Buttons) — alle grün, Gesamt-Control-Center-Suite 210/210
  grün. JS-Syntax mit `node --check` verifiziert.
- Keine neuen Dependencies, keine neue API-Fläche.

---

## Erweiterung — Metadata Management, Schritt 2: Fehlende Metadata finden (2026-09-20, auf Nutzerfreigabe)

Zweiter Schritt der Metadata-Management-Phase (Master-Prompt Abschnitt
7, Punkt "fehlende Metadata finden") — auf Nutzerwunsch **ohne
Merge-Wartepause zwischen den Schritten** umgesetzt: Implementierung →
Test → Commit → Push → PR direkt hintereinander für die gesamte Phase;
Prüfung/Merge der einzelnen PRs erfolgt gesammelt durch den Nutzer nach
Abschluss der Phase (Abweichung vom bisherigen Ein-Schritt-pro-Merge-
Vorgehen, explizit so entschieden). Getestet weiterhin nur gezielt/
Regression/thematisch (CLAUDE.md §8.A) — die volle Suite führt wie immer
der Nutzer selbst aus.

- **`GET /api/v1/library/tracks?issue_code=...`** — filtert die bereits
  vorhandene `issue_codes`-Liste je Track. **Keine neue Domänenlogik**,
  reine Filterung bereits berechneter Daten (identisches Prinzip wie
  `services/library_repair/planner.py::filter_plan(issue_code=...)` beim
  Repair-Plan). Unbekannter Code liefert eine leere Liste statt eines
  Fehlers (identisches Verhalten wie `filter_plan()`).
- UI: Dropdown „Fehlende Metadata" im bestehenden Library-Metadata-Panel
  mit den 13 bekannten `*_MISSING`-Issue-Codes aus der
  `services/library_health/issues.py`-Registry (Artist/Album/Album-Artist/
  Titel/Genre/Jahr/Tracknummer/ISRC/MusicBrainz Recording/Release/Cover/
  Lyrics/Loudness-Tag) — gilt bewusst nur für den Tracks-Modus (Artists/
  Albums ignorieren die Auswahl, kein wirkungsloser Query-Parameter).
- Test: `tests/test_control_center_metadata_api.py` von 10 auf 13 Tests
  erweitert (Filterung, kein Filter → alle, unbekannter Code → leer),
  `tests/test_control_center_ui.py` von 25 auf 26 Tests — alle grün,
  Regression `test_control_center_health_api.py`/`test_control_center_repair_api.py`
  sowie `tests/test_library_health*.py` (297 Tests) weiterhin grün,
  Gesamt-Control-Center-Suite 214/214 grün. JS-Syntax mit `node --check`
  verifiziert.
- Keine neuen Dependencies.

---

## Erweiterung — Metadata Management, Schritt 3: Mapping anzeigen (2026-09-20, auf Nutzerfreigabe)

Dritter Schritt der Metadata-Management-Phase (Master-Prompt Abschnitt
7, Punkt "Mapping anzeigen") — wie Schritt 2 **ohne Merge-Wartepause**
direkt im Anschluss implementiert (auf demselben main-Stand wie Schritt
1 verzweigt, nicht auf Schritt 2 gestapelt); Prüfung/Merge aller
Schritte gesammelt durch den Nutzer am Ende der Phase.

- **`GET /api/v1/library/mapping-summary`** (neu in
  `control_center/routers/metadata.py`) — reine Übersicht (Anzahl
  Einträge je Mapping-Kategorie: Artists/Channels/Hierarchy/Rules/
  Aliases/Overrides, plus Anzahl eindeutiger primärer Genres). Mappt
  `utils.genre_map.GenreMapper.get_statistics()["mappings"]`
  unverändert — **keine eigene YAML-/JSON-Parsing-Logik**, keine neue
  Bearbeitungsfläche (reine Lesefunktion, kein Editor).
- Laufzeit-Cache-/Query-Statistiken (`queries`/`cache_hits`/
  `fuzzy_matches`/`rule_matches`/`cache_hit_rate`) bewusst NICHT
  durchgereicht — für eine frische Anfrage nicht aussagekräftig
  (Prozess-Lebenszeit-Artefakt, kein Mapping-Inhalt).
- `GenreMapper` ist `SingletonMixin`-basiert — identischer, bereits
  etablierter Aufrufpfad wie `services/library_health/scanner.py`
  (nutzt `GenreMapper` für `validate_genre()` in einem frischen
  Prozess). Test-Isolation läuft bereits global über
  `tests/conftest.py` (`SingletonMixin._instances` wird vor/nach jedem
  Test geleert) — kein Zusatzaufwand in diesem Schritt nötig.
- **Tests laufen bewusst gegen die ECHTEN Mapping-Dateien** in
  `mapping/` statt gegen eine isolierte Kopie — identisches Prinzip wie
  `tests/test_genre_processor.py`, das denselben `GenreMapper` bereits
  so gegen `Config.GENRE_MAPPING_DIR` charakterisiert (CLAUDE.md
  Abschnitt 10: Mapping-Dateien sind Fachlogik; `GenreMapper` verändert
  beim Lesen nichts). Exakte Zahlen werden bewusst NICHT geprüft
  (Mapping-Daten ändern sich im echten Projekt) — nur strukturelle
  Eigenschaften (alle Felder int ≥ 0, Artists/Primäre-Genres > 0 gegen
  die echte, nicht-leere Produktions-Registry).
- UI: eigener „Mapping"-Button im Library-Metadata-Panel — **kein
  voller Library-Scan** (anders als Tracks/Artists/Albums), eigener,
  schneller Ladepfad ohne den „Scan läuft…"-Zwischenzustand.
- Test: `tests/test_control_center_metadata_api.py` um 2 Tests
  erweitert (Struktur/Nicht-Leer-Check gegen echte Mapping-Daten,
  Ausschluss der Laufzeit-Cache-Felder), `tests/test_control_center_ui.py`
  um 1 Test — alle grün, Regression `tests/test_genre_processor.py`
  (42 Tests) sowie `tests/test_auto_learn*.py`/`tests/test_genre_canonical*.py`
  (116 Tests) weiterhin grün, Gesamt-Control-Center-Suite 213/213 grün.
  JS-Syntax mit `node --check` verifiziert.
- Keine neuen Dependencies.

---

## Erweiterung — Metadata Management, Schritt 4: Metadata bearbeiten (Genre setzen) (2026-09-20, auf Nutzerfreigabe)

Vierter Schritt der Metadata-Management-Phase (Master-Prompt Abschnitt
7, "Metadata bearbeiten") — **erste schreibende Fähigkeit** in diesem
Funktionsbereich. Wie Schritt 2/3 ohne Merge-Wartepause direkt im
Anschluss implementiert, auf demselben main-Stand wie Schritt 1
verzweigt.

- **`GET /api/v1/library/artists/{artist}/genre-preview`** +
  **`POST /api/v1/library/artists/{artist}/set-genre`** (neues
  `control_center/routers/metadata_actions.py`) — spiegelt die
  bestehende, bereits produktive Telegram-/CLI-Fähigkeit „✏️ Genre
  setzen" (ARCH-032, `docs/LIBRARY_REPAIR.md` §11.3/§14.1). Rufen
  ausschließlich `services/library_repair/maintenance_service.py::
  preview_set_genre()`/`execute_set_genre()` auf, die wiederum
  `executor.py::apply_set_genre()` nutzen (Backup + SHA-256- +
  Audio-Essenz-Verifikation + Rollback + Journal, bereits produktiv,
  unverändert übernommen). **Keine neue Ausführungslogik.**
- **Preview→Diff→Confirmation→Execution→Verification** (Master-Prompt
  Abschnitt 7) vollständig abgebildet: Preview liefert das komplette
  Vorher/Nachher je Datei (`before`/`after`), Confirmation ist
  Frontend-Verantwortung (`window.confirm()`, identisches Muster wie
  SAFE_AUTOMATIC/L2-L3), Verification läuft bereits innerhalb von
  `apply_set_genre()` selbst (Tag-Rücklesen + Audio-Essenz-Vergleich vor
  dem endgültigen Datei-Replace) — kein separater Verifikationsschritt
  nötig, da schon im wiederverwendeten Executor enthalten.
- **Bewusst NUR `from_mapping=True`** (kein Freitext-Genre-Eingabefeld)
  — identische Einschränkung wie die bestehende Telegram-Fähigkeit,
  keine neue, in Telegram nirgends existierende Fähigkeit (identisches
  Prinzip wie die Cover-Scope-Entscheidung bei ARCH-033/L2-L3).
- `RepairAlreadyRunningError` (gemeinsamer Lock mit Telegram/CLI/Repair/
  L2-L3) wird als `409` gemeldet, `MaintenanceServiceError` (Artist
  nicht in `artist_genre.yaml`) als `404`.
- **Bewusst synchron, kein Job/Polling** — `apply_set_genre()` schreibt
  direkt in-process per Mutagen (kein Subprozess, kein Netzwerk), für
  die Dateien eines einzelnen Artists ausreichend schnell für eine
  normale Request/Response-Antwort.
- UI: neues Panel „Metadata bearbeiten: Genre setzen" — Artist-Name-
  Eingabefeld (Freitext für den Ordnernamen, NICHT für den Genre-Wert
  selbst), Vorschau-Button lädt den Diff, „Genre setzen"-Button bleibt
  `disabled`, bis eine Vorschau mit tatsächlichen Änderungen geladen
  wurde. Nach Ausführung automatischer Re-Preview (Verifikation, dass
  der Diff jetzt leer ist).
- Test: neues `tests/test_control_center_metadata_actions_api.py` (6
  Tests: Preview zeigt Diff ohne Dateiänderung, 404 bei unbekanntem
  Artist, Execute schreibt Tag + Run-History-Eintrag, 404/409/CSRF-
  Ablehnung) — **gegen echte, isolierte m4a-Testdateien** (ffmpeg), nie
  die Produktionsbibliothek, identisches Muster wie
  `tests/test_library_repair_maintenance_service.py`. `tests/test_control_center_ui.py`
  um 2 Tests erweitert. Alle grün, Regression
  `tests/test_library_repair_maintenance_service.py` +
  `tests/test_library_maintenance_genre_management.py` (73 Tests),
  thematische Suite `tests/test_library_repair*.py` (322 Tests)
  weiterhin grün, Gesamt-Control-Center-Suite 218/218 grün. JS-Syntax
  mit `node --check` verifiziert.
- **Kein Live-Smoke-Test gegen die echte Library** — ein echter Aufruf
  würde sofort Dateien in der Produktionsbibliothek verändern. Nur
  gegen isolierte Testdaten verifiziert (siehe oben).
- Keine neuen Dependencies.

---

## UI Structure Redesign — Phase 1 (2026-09-20, auf Nutzerfreigabe, `ui_prompt.txt`)

**Zwischen-Schritt außerhalb des Master-Prompt-Backlogs** — auf
Nutzerwunsch ein separates, priorisiertes Redesign-Dokument
(`ui_prompt.txt`, "MUSICBOT CONTROL CENTER UI STRUCTURE REDESIGN")
eingeschoben, bevor die Metadata-Management-Phase (bzw. der
Gesamt-Master-Prompt) fortgesetzt wird — identisches Muster wie
`ui_prompt.txt` selbst in Abschnitt 4 vorsieht ("konkretes UI-/
Architekturproblem erkannt → begrenzter Verbesserungs-Schritt →
Verification → Masterplan fortsetzen"). Das Problem war laut Auftrag
explizit **Informationsarchitektur/Navigation**, nicht fehlende
Funktionen — entsprechend wurde ausschließlich reorganisiert, keine
Fachlogik verändert.

### Ausgangslage

Das bisherige Control Center bestand aus einer einzigen Seite
(`dashboard.html`, ~1100 Zeilen), auf der alle Panels (Statistics,
Findings, Repair-Plan, L2/L3, Library-Metadata, Genre setzen, Downloads,
Admin) untereinander lagen — funktional vollständig, aber ohne
Navigationsstruktur.

### Neue Struktur

12 Seiten mit gemeinsamer Sidebar/Header-Navigation, exakt wie
`ui_prompt.txt` Abschnitt 8/11/50 vorgegeben:

```
Overview · Downloads · Library · Metadata · Statistics · Findings ·
Repairs · Jobs · Health · Navidrome · Logs · Administration
```

**Zuordnung bestehender Panels** (unverändert verschoben, keine
inhaltliche Neuerstellung — `ui_prompt.txt` Abschnitt 6/49 verbietet
das ausdrücklich für Phase 1):

| Seite | Inhalt (Herkunft) |
|---|---|
| Overview | NEU, kompakt: Health-/Navidrome-Status, KPIs (Active Jobs/Open Findings, aus bereits bestehenden Endpunkten `GET /api/v1/jobs`/`GET /api/v1/library/findings/summary`), Attention-Summary, Active-Jobs-Summary, Recent Activity (Downloads-Verlauf), Quick Actions |
| Downloads | bisheriges „Downloads (Verlauf)"-Panel |
| Library | bisheriges „Library-Metadata"-Panel (Tracks/Artists/Albums/Mapping/Missing-Metadata-Filter) |
| Metadata | bisheriges „Genre setzen"-Panel |
| Statistics | bisheriges Statistics-/Genre-Stats-/Music-DNA-Panel |
| Findings | bisheriges Findings-Panel (+ Accepted-Findings-Toggle) |
| Repairs | bisherige Repair-Plan- + L2/L3-Panels |
| **Jobs** | **NEU** — erste dedizierte Job-Listen-Ansicht; nutzt die bereits bestehende `GET /api/v1/jobs`, die bisher nur implizit über die "aktueller Job"-Anzeige bei Repair-Plan/L2-L3 sichtbar war. Keine neue Backend-Logik. |
| Health | bisherige Health-Kacheln + Navidrome-Status |
| Navidrome | bisherige Navidrome-Status-Zeile |
| **Logs** | **Platzhalter** — kein Backend vorhanden (Master-Prompt Abschnitt 12 "LOGS & DIAGNOSTICS", bisher nicht umgesetzt). Zeigt ehrlich „Noch nicht implementiert" statt eine nicht vorhandene Funktion vorzutäuschen (Master-Prompt Regel 38 / `ui_prompt.txt` Abschnitt 38). |
| Administration | bisheriges Admin-Nutzer-Panel (+ Cross-User-Statistik) |

### Technische Umsetzung

- **`control_center/templates/_base.html`** (neu) — gemeinsames Layout
  (Sidebar mit allen 12 Einträgen inkl. Active-State, Header, View-
  State-Container `loading-view`/`login-view`/`error-view`/
  `dashboard-view`), Jinja2-Vererbung (`{% block content %}`/
  `{% block scripts %}`) für jede Seite. `dashboard.html` entfernt
  (vollständig durch die 12 neuen Seiten-Templates + `_base.html`
  ersetzt).
- **`control_center/static/common.css`** + **`common.js`** (neu) —
  gemeinsame Styles/JS-Helfer (`_escapeHtml`, `_loadInto`, `checkAuth`,
  `onTelegramAuth`, Sidebar-Drawer-Toggle), unverändert aus dem
  vorherigen Einzel-Dashboard extrahiert, um Duplikation über jetzt 12
  Seiten hinweg zu vermeiden. **Bewusste, notwendige technische
  Ergänzung** (FastAPI `StaticFiles`-Mount in `app.py`) — kein
  Framework-Wechsel, weiterhin Vanilla JS/CSS ohne Build-Schritt
  (Master-Prompt Abschnitt 7 bzw. `ui_prompt.txt` identisch).
- **`control_center/routers/ui.py`** — von einer Route (`GET /`) auf 12
  Routen erweitert, jede rendert ihr eigenes Template über einen
  gemeinsamen `_render()`-Helper (übergibt `page_id` für die
  Sidebar-Active-Markierung). Weiterhin bewusst unauthentifiziert (reines
  HTML-Grundgerüst, echte Daten holt jede Seite client-seitig über die
  bereits geschützten API-Endpunkte).
- **Mobile Navigation** (`ui_prompt.txt` Abschnitt 12): Sidebar wird per
  CSS + minimalem JS-Klassen-Toggle zum Drawer (`body.sidebar-open`),
  kein horizontales Scrollen.
- **Keine einzige API-Route, kein Schema, kein Service geändert** — reine
  Frontend-Reorganisation, `git diff` betrifft ausschließlich
  `control_center/templates/`, `control_center/static/` (neu),
  `control_center/routers/ui.py`, `control_center/app.py`
  (StaticFiles-Mount) und die UI-Testdatei.
- Test: `tests/test_control_center_ui.py` komplett neu geschrieben (85
  Tests, vorher 27) — jeder vorherige Test auf seine neue Seite
  verschoben, plus neue Tests für gemeinsames Layout (Sidebar auf jeder
  Seite vollständig, Active-State korrekt, View-States, Static-Assets
  erreichbar), das neue Jobs-Panel und die ehrliche „Noch nicht
  implementiert"-Kennzeichnung von Logs. Alle grün, Gesamt-Control-
  Center-Suite 281/281 grün (keine Backend-Datei geändert, daher keine
  gesonderte Backend-Regression nötig). JS-Syntax mit `node --check` für
  `common.js` und jeden Seiten-Script-Block einzeln verifiziert (`node`
  akzeptiert alle 12 extrahierten Blöcke fehlerfrei). Alle 12 Seiten +
  beide statischen Assets per HTTP-Smoke-Test gegen den echten
  ASGI-Stack abgerufen (200 OK, plausible Content-Länge) — kein
  Live-Browser verfügbar, daher dieser Ersatz (identisches Vorgehen wie
  bei allen vorherigen UI-Schritten dieser Session).
- Verification-Checkliste aus `ui_prompt.txt` Abschnitt 51 vollständig
  erfüllt (Dashboard/Sidebar/Navigation funktionsfähig, keine API-
  Funktion verloren, keine Business-Logik ins Frontend verschoben,
  responsive Grundstruktur, Loading/Empty/Error-States, relevante Tests,
  `node --check`, Git Diff geprüft).
- Keine neuen Dependencies (FastAPI `StaticFiles` ist Teil des bereits
  installierten FastAPI-Pakets).

**Zwischen-Schritt abgeschlossen** — Fortsetzung des Master-Plans
(Metadata Management: Reprocessing/Cover verwalten, danach Logs &
Diagnostics, siehe frühere Gap-Analyse) folgt gemäß `ui_prompt.txt`
Abschnitt 52 als eigene, separat freizugebende Entscheidung.

---

## Logs & Diagnostics (2026-09-20, auf Nutzerfreigabe)

Master-Prompt Abschnitt 12 "LOGS & DIAGNOSTICS" — laut Gap-Analyse einer
der bis dahin komplett unbearbeiteten V1-Funktionsbereiche.

**Wichtiger Charakterisierungsbefund vor der Implementierung:** es
existiert bereits eine umfangreiche Telegram-seitige Log-Verwaltung
(`handlers/enhanced_logger_menu_handler.py::EnhancedLoggerMenuHandler`,
1711 Zeilen, inkl. eines bereits gefixten Path-Traversal-Bugs SEC-003,
siehe `tests/test_logger_menu_path_traversal.py`) — Datei-Übersicht +
5-Zeilen-Vorschau + naive Level-Zählung (`if level in line`), aber
**kein** strukturierter, nach Level/Component filterbarer
Zeilen-Browser. Diese Erweiterung dupliziert daher keine bereits
gelöste Funktion, liefert aber eine dort fehlende Fähigkeit — und
übernimmt bewusst zwei dort bereits etablierte, bewährte Muster statt
sie neu zu erfinden: die Datei-Discovery (`log_dir.glob("*.log*")`) und
den Path-Traversal-Schutz (`resolve()` + `is_relative_to()`).

- **Neues `services/logs/reader.py`** (Telegram-frei) — `list_log_sources()`
  (alle `*.log*`-Dateien in `Config.LOG_DIR`, alphabetisch) +
  `read_logs()` (liest genau eine gewählte Datei, filtert nach
  Level/Component/Search, liefert die neuesten `limit` Treffer plus
  `total_matched`).
- **Zwei real vorkommende Zeilenformate entdeckt** (per Live-Smoke-Test
  gegen die echten 42 Logdateien in `logs/` charakterisiert): das
  Root-/`bot.log`-Format (`logger.py::ColoredFormatter`, `HH:MM:SS`
  ohne Datum, mit ANSI-Farbcodes, da `setup_enhanced_logging()`
  denselben Formatter für Konsole UND Datei verwendet) wird
  strukturiert geparst (Time/Level/Component/Message). Modul-eigene
  Dateien (z. B. `autolearnmanager.log`, `propagate=False`, eigener
  Formatter mit vollem Datum) entsprechen NICHT demselben Muster —
  ihre Zeilen werden nicht verworfen oder falsch geparst, sondern
  ehrlich als unstrukturierter Eintrag (`level=None`, `component=None`,
  `message`=ganze Zeile) zurückgegeben: weiterhin durchsuchbar, nur
  nicht nach Level/Component filterbar. Keine Vortäuschung einer
  repoweiten Formatvereinheitlichung, die nicht existiert (Master-Prompt
  Regel 38).
- **Bewusst KEIN Zeitraum-Filter** — das Root-Format enthält kein Datum
  in der Zeile selbst; die Datei-Auswahl (`source`) ist die einzige
  verlässliche grobe zeitliche Eingrenzung.
- **Bewusst KEIN Job-/User-Filter** — keiner der bestehenden `log*()`-
  Aufrufe im gesamten Repository korreliert Log-Zeilen strukturiert mit
  einer Job-/User-ID; das flächendeckend nachzurüsten wäre ein großer,
  hier nicht beauftragter Eingriff in sehr viele bestehende log-Aufrufe.
- **Security:** zusätzliche, defensive Redaktion offensichtlicher
  Secret-Muster (`token=`/`password=`/`api_key=`-Zuweisungen,
  `Authorization: Bearer`-Header, Telegram-Bot-Token-Form) VOR der
  Auslieferung — ergänzt die bestehende P0-Regel "keine Secrets loggen"
  (CLAUDE.md Abschnitt 12), ersetzt sie nicht (im Live-Smoke-Test gegen
  die echten Produktions-Logs bestätigt: 0 Treffer für
  `token=`/`password=`/`api_key=`/`Authorization: Bearer` — die P0-Regel
  wird bereits eingehalten). ANSI-Farbcodes werden vor der Auslieferung
  entfernt.
- **`GET /api/v1/logs`** (neues `control_center/routers/logs.py`, Query:
  `source`/`level`/`component`/`search`/`limit`) — reine Orchestrierung,
  ruft ausschließlich `read_logs()` auf. Mindestens `AccessLevel.ADMIN`
  (identische Schwelle wie Findings/Repair-Plan/Metadata — Logzeilen
  können interne Pfade/Fehlermeldungen enthalten).
- UI: `/logs`-Seite (ersetzt den zuvor als „Noch nicht implementiert"
  angelegten Platzhalter aus der UI-Structure-Redesign-Phase) mit
  Datei-/Level-/Component-/Search-Filtern, Trunkierungshinweis bei mehr
  Treffern als geladen (identisches Muster wie Accepted-Findings/
  Library-Metadata).
- Test: `tests/test_logs_reader.py` (28 Tests, inkl. Path-Traversal-
  Regressionstest, der die zweite Verteidigungslinie unabhängig vom
  Whitelist-Abgleich prüft) + `tests/test_control_center_logs_api.py`
  (9 Tests) + 3 neue Auth-Schwellen-Tests in
  `tests/test_control_center_auth.py` + 4 neue UI-Tests — alle grün,
  Regression `tests/test_logger_menu_path_traversal.py` (4 Tests, SEC-003
  weiterhin geschlossen) unverändert grün, Gesamt-Control-Center-Suite
  322/322 grün.
- Live-Smoke-Test gegen die echten Produktions-Logs durchgeführt (reine
  Lesefunktion, unbedenklich) — 42 reale Logdateien korrekt entdeckt,
  `bot.log` strukturiert geparst (1317 Treffer), `autolearnmanager.log`
  korrekt als unstrukturiert erkannt statt falsch geparst.
- Keine neuen Dependencies.

## Administration: Library-Maintenance-Actions (2026-09-20, auf Nutzerfreigabe)

Vierte Administration-Fähigkeit nach Nutzer/Rollen-Übersicht, Cross-User-
Statistik und Logs/Diagnostics — ui_prompt.txt Abschnitt 22
"ADMINISTRATION". Exponiert die bestehenden, bereits produktiven
Telegram-Maintenance-Flows (ARCH-032 „🧹 Library-Wartung" + der neuere,
von einer parallelen Session ergänzte „📝 Metadaten bearbeiten"-Zweig,
`handlers/library_maintenance_handler.py`) im Web — **keine neue
Ausführungslogik**, identisches Prinzip wie „Genre setzen"
(`control_center/routers/metadata_actions.py`, bereits produktiv seit
Metadata-Management-Schritt 4).

- **Sechs Aktionen, jede als eigenes Preview/Execute-Endpunktpaar**
  (bewusst kein generischer `/maintenance/{action}`-Dispatcher — die
  Aktionen unterscheiden sich in ihren Parametern, ein generischer
  Endpunkt würde das verschleiern):
  - `artist-casing` — Groß-/Kleinschreibung eines Artists aus
    `mapping/artist_overrides.json` korrigieren (`artist`).
  - `legacy-genre-cleanup` — entfernt veraltete Freeform-Genre-Atome
    (`artist`).
  - `artist-rename` — manueller Artist-Zielwert, KEIN Casing-Mapping/
    keine Normalisierung — explizite Nutzerentscheidung, identisch zur
    Telegram-Fähigkeit „📝 Metadaten bearbeiten → Artist" (`artist` +
    `new_artist`).
  - `title-edit` — manueller Titel-Zielwert für genau einen Track, KEIN
    automatischer TitleCleaner (`artist` + `rel_path` + `new_title`,
    `rel_path` wird aus der bestehenden Library-Track-Ansicht kopiert —
    kein eigener Track-Picker in diesem Schritt).
  - `album-edit` (nachgezogen CC-AC-3, `library_artist_centric_UX.txt`)
    — manueller Albumname (`©alb`) für den gesamten Album-Scope
    (`artist` + `album` + `new_album`). `album` MUSS ein exakter Wert
    aus `list_artist_albums()`/der artists-overview-Antwort sein — seit
    dieser Aktion sind `artist` UND `album` erstmals per HTTP direkt
    (nicht mehr ausschließlich über die Telegram-seitige
    `resolve_album_by_index()`) erreichbar. `services/library_repair/
    maintenance_service.py::album_targets()` prüft seit dem
    Adversarial-Review-Fund 2026-09-21 (Runde 2, nach einer in Runde 1
    unvollständigen Blacklist — `"."` kollabierte `root/artist/"."` zu
    `root/artist`) beide Segmente über eine positive
    Containment-Prüfung (Artist echt innerhalb der Library, Album echt
    innerhalb des Artist-Verzeichnisses, `Path.resolve()`-basiert wie
    das bestehende `_resolve_within_library()`) — leere Zielmenge statt
    Traversal über den Artist-Scope hinaus, statt unbehandeltem 500 bei
    absoluten Pfaden, und schließt nebenbei einen inkonsistenten
    Symlink-Verzeichnis-Fall.
  - `albumartist-edit` (nachgezogen CC-AC-3) — manueller Albuminterpret
    (`aART`) für denselben Album-Scope wie `album-edit` (`artist` +
    `album` + `new_album_artist`), ändert nicht `©alb`/`©ART`.
  - Alle sechs rufen `services/library_repair/maintenance_service.py::
    preview_*()`/`execute_*()` unverändert auf; Preview und Execute
    nutzen denselben Executor-Pfad (`dry_run=True/False`) — identisches
    Preview→Diff→Confirmation→Execution→Verification-Prinzip wie „Genre
    setzen".
- **Schema-Umbenennung statt Duplikation:** `GenrePreviewResponse`/
  `GenreExecuteResponse`/`genre_preview_to_response`/
  `genre_execute_to_response` aus `schemas/metadata.py` waren bereits rein
  generisch (referenzieren nirgends genre-spezifische Felder) — nach
  `control_center/schemas/maintenance.py` verschoben und in
  `MaintenancePreviewResponse`/`MaintenanceExecuteResponse`/
  `maintenance_preview_to_response`/`maintenance_execute_to_response`
  umbenannt, damit `metadata_actions.py` UND `admin_maintenance.py`
  dieselbe Datenform nutzen, ohne sie viermal zu duplizieren.
- **Fehlerabbildung:** `MaintenanceServiceError` bedeutet hier (anders
  als bei „Genre setzen", wo sie „Artist nicht in artist_genre.yaml"
  bedeutet) i. d. R. eine ungültige manuelle Eingabe (leer/zu lang/
  Zeilenumbruch, `_validate_manual_value()`) — als 422 gemeldet statt
  404. `RepairAlreadyRunningError` (gemeinsamer Lock mit Telegram/CLI/
  Repair/L2-L3/Genre setzen) wird wie überall als 409 gemeldet.
- **`GET/POST /api/v1/admin/maintenance/{action}/preview|execute`**
  (neues `control_center/routers/admin_maintenance.py`, 12 Endpunkte) —
  reine Orchestrierung, mindestens `AccessLevel.ADMIN`, POST über
  `verify_same_origin()` CSRF-geschützt (identisches Muster wie alle
  bisherigen destruktiven Control-Center-Fähigkeiten). Bewusst synchron
  (kein Job/Polling) — reine In-Process-Mutagen-Schreibvorgänge für die
  Dateien eines Artists bzw. eine einzelne Datei, kein Subprozess, kein
  Netzwerk (identische Begründung wie „Genre setzen").
- UI: vier neue Panels auf der bestehenden `/admin`-Seite (kein neuer
  Menüpunkt — Administration-Scope nach ui_prompt.txt), jedes mit
  Eingabefeld(ern) + Vorschau-Button + generischer Vorher/Nachher-Diff-
  Ansicht (`_diffSummary()`, feldunabhängig: iteriert die vom Backend
  gelieferten `before`/`after`-Dicts statt pro Aktion einen eigenen
  Renderer zu benötigen) + `window.confirm()`-Bestätigung + Ausführen-
  Button + Ergebnisanzeige — identisches Interaktionsmuster wie „Genre
  setzen" (`metadata.html`), nur generisch über alle vier Aktionen
  parametrisiert statt viermal dupliziert.
- Test: `tests/test_control_center_admin_maintenance_api.py` (9 Tests,
  Preview-ist-read-only/Execute-schreibt-und-protokolliert/
  Validierungsfehler-422/Lock-Konflikt-409/CSRF-403, gegen echte,
  isolierte ffmpeg-m4a-Dateien) + 3 neue Auth-Schwellen-Tests in
  `tests/test_control_center_auth.py` (401/403/200, repräsentativ für
  `artist-casing/preview`) — alle grün. Regression
  (`tests/test_library_repair_maintenance_service.py`,
  `tests/test_control_center_metadata_actions_api.py`,
  `tests/test_control_center_metadata_api.py`) 56/56 grün. Gesamte
  Control-Center-Suite (`tests/test_control_center*.py`) 278/278 grün.
- Live-Smoke-Test bewusst ausgelassen — alle vier Aktionen schreiben
  echte Library-Dateien, kein read-only Endpunkt wie bei Logs/Health;
  Verifikation ausschließlich gegen isolierte Testdaten.
- Keine neuen Dependencies.

## Library Artist-Centric UX — CC-AC-1 (2026-09-21, auf Nutzerfreigabe)

Erster Schritt aus `library_artist_centric_UX.txt` (Master-Prompt v2,
mehrere Folge-Tasks CC-AC-2..5 geplant, siehe Datei-Kopf). Macht aus der
bisherigen, rein Klick-gesteuerten „Library-Metadata"-Seite eine
Artist-zentrierte Navigation: `/library` zeigt beim Laden automatisch
die Artist-Liste, ein Klick führt auf eine neue Artist-Detailseite
(Overview/Alben/Tracks). **Bewusst READ-ONLY** — keine Maintenance-/
Metadata-Actions (folgen in CC-AC-2/3/4).

**Kernproblem, vor der Umsetzung verifiziert (Auftrag §7a):**
`GET /api/v1/library/artists` (bestehend, `routers/metadata.py`) löst bei
jedem Aufruf einen frischen `run_scan()` aus — auf der Produktionsbibliothek
real gemessen unverändert das aus §7a bekannte Problem. Ein automatischer
Seitenaufruf-Ladepfad darf diesen Scan nicht ungefragt mit auslösen.

**Entscheidung: neuer, additiver Endpunkt statt Änderung des bestehenden.**
Der Auftrag benennt zwar wörtlich `GET /api/v1/library/artists` als die
Stelle, die „read-only bleibt und ausschließlich einen bereits vorhandenen
Report liest" — Konsumenten-Analyse (`grep` über alle Templates) zeigt aber:
der einzige Aufrufer von `/api/v1/library/artists`/`/tracks`/`/albums` ist
die bestehende, bewusst beibehaltene „Library-Metadata"-Sektion
(`library.html`, expliziter Warnhinweis „Führt einen vollständigen Scan
aus … läuft nicht automatisch, nur auf Klick"). Diese drei Endpunkte
unverändert zu lassen und stattdessen `GET /api/v1/library/artists-overview`
+ `GET /api/v1/library/artists-overview/{artist}` (neuer Router
`control_center/routers/library_overview.py`) zu ergänzen, vermeidet ein
Verhaltensänderungsrisiko für einen bereits funktionierenden, bewusst
Klick-gesteuerten Legacy-Pfad (Auftrag §43 Hard-Stop-Geist „bestehende
Funktionen nicht verändern, wenn reine Integration möglich ist") und
respektiert §39 (alte Routen nicht ungeprüft anfassen).
- `control_center/_library_scan.py::load_cached_report(max_age_hours=24)`
  (neu, ergänzt `run_library_scan()`) liest ausschließlich
  `Config.DATA_DIR/library_health_report.json` — denselben, bereits
  bestehenden persistenten Report, den `scripts/library_health_check.py`
  und der Telegram-„🩺 MusicBot Doctor"-Subprozess
  (`services/library_repair/doctor_runner.py::run_health_scan()`, siehe
  `LIBRARY_REPAIR.md` §9 „Report-Persistenz") bereits schreiben. Kein
  Scan-Code dupliziert, keine neue Persistenzschicht.
- Fehlt der Report komplett → `HTTPException(404,
  code="LIBRARY_REPORT_MISSING")`, kein impliziter Scan aus dem GET heraus
  (Auftrag §7a Punkt 2). Das Erzeugen eines fehlenden Reports bleibt
  bewusst außerhalb dieses (READ-ONLY) Schritts — CLI/Telegram bleiben
  unverändert nutzbar; ein Job-Trigger-Button in der neuen UI wurde
  bewusst NICHT gebaut (der dafür naheliegende bestehende Job-Typ
  `POST /api/v1/jobs/repair-safe-automatic` führt nebenbei eine echte
  SAFE_AUTOMATIC-Reparatur aus, keinen reinen Scan — das würde die
  READ-ONLY-Vorgabe dieses Schritts verletzen).
- Report vorhanden, aber älter als 24 h → weiterhin nutzbar
  (`stale: true` im Response, UI zeigt „Stand: …").
- `schemas/metadata.py::ArtistsOverviewResponse`/`ArtistDetailResponse` +
  `artists_overview_to_response()`/`artist_detail_to_response()` (neu) —
  reine Wrapper um die bereits bestehenden `ArtistSummarySchema`/
  `AlbumSummarySchema`/`TrackSchema`/`_artist_to_schema()`/
  `_album_to_schema()`/`_track_to_schema()` (unverändert wiederverwendet,
  keine zweite Feldliste). Artist-Detail filtert Alben/Tracks
  **verzeichnisbasiert** (`entry["artist"]`/`file["artist_directory"]` —
  identische Konvention wie `services/library_repair/library_artists.py`/
  `maintenance_service.py::artist_targets()`, „Artist = stabiler Kontext",
  Auftrag §10), nicht über den rohen `©ART`-Tag-Wert.
- Router-Regel eingehalten (Auftrag §22): `library_overview.py` enthält
  ausschließlich Request-Handling + 404-Mapping, keine Aggregations-/
  Gruppierungslogik — die liegt vollständig in
  `services/library_health/scoring.py` (unverändert, über den bereits
  aggregierten Report).
- UI: `library.html` bekommt eine neue „🎤 Artists"-Sektion oben
  (Auto-Load beim Seitenaufruf, client-seitige Substring-Suche über die
  bereits geladene Liste — keine neue Such-Infrastruktur, Auftrag §9) —
  die bestehende „Library-Metadata"-Sektion bleibt unverändert darunter
  erhalten. Neue Seite `library_artist_detail.html`
  (`GET /library/{artist}`, `control_center/routers/ui.py`) zeigt
  Overview-Kacheln + Alben + Tracks; der Artist-Name wird bewusst
  client-seitig aus `window.location.pathname` gelesen (kein
  Server-Template-Lookup) — ein unbekannter Artist bleibt dadurch ein
  sauberer API-404 statt eines Server-Renderfehlers, die Seite ist
  F5-tauglich. `common.js::_loadInto()` um einen optionalen `retryFn`-
  Parameter erweitert (rückwärtskompatibel, alle bestehenden Aufrufer
  unverändert) für das „[Erneut versuchen]"-Error-State (Auftrag §27).
- **Performance (live gegen die echte Produktionsbibliothek gemessen):**
  `GET /api/v1/library/artists-overview` ~0.02 s (statt ~37 s bei einem
  Scan), `GET /api/v1/library/artists-overview/{artist}` ~0.02 s — weit
  unter dem 2-s-Budget aus Auftrag §32/§43-6.
- Test: `tests/test_control_center_library_overview.py` (11 Tests, echte
  `run_scan()`-erzeugte Reports gegen isolierte ffmpeg-m4a-Testdaten,
  keine echte Library berührt) + 10 neue UI-Tests in
  `tests/test_control_center_ui.py` (Artists-Panel, Artist-Detail-Seite,
  Legacy-Sektion unverändert) + 3 neue Auth-Schwellen-Tests in
  `tests/test_control_center_auth.py`. Gesamte Control-Center-Suite
  394/394 grün, Regression `tests/test_library_repair_maintenance_service.py`/
  `tests/test_library_repair_library_artists.py`/
  `tests/test_library_repair_executor.py`/`tests/test_library_health*.py`
  499/499 grün. `node --check` für `common.js` und beide neuen/geänderten
  Seiten-Skript-Blöcke grün; `tests/test_control_center_subpath_ui.py`
  (führt `common.js` real mit `node` aus) unverändert 60/60 grün.
  Live-Smoke-Test gegen die echte Produktionsbibliothek durchgeführt
  (Library → Artist → Detail → Zurück, 41 Artists, kein Live-Browser
  verfügbar, identischer Ersatz wie bei allen vorherigen UI-Schritten).
- Keine neuen Dependencies.
- **Nicht Teil dieses Schritts** (Folge-Tasks): Manual Metadata Editing
  im Artist-Kontext (CC-AC-2/3), Library-Wartung im Artist-Kontext
  (CC-AC-4), Navigation-Cleanup/Redundanz-Entfernung (CC-AC-5). Die
  bestehende „Library-Metadata"-Sektion (`GET /api/v1/library/artists`/
  `/tracks`/`/albums`, Klick-gesteuert) ist nach dieser Phase teilweise
  redundant zur neuen Artist-Übersicht — bewusst nicht entfernt (Auftrag
  §19/§39), Bewertung „behalten/redundant/späterer Cleanup" folgt in
  CC-AC-5.

## Manual Metadata Editing v1 im Artist-Kontext — CC-AC-2 (2026-09-21, auf Nutzerfreigabe)

Zweiter Schritt aus `library_artist_centric_UX.txt` (Folge-Task zu
CC-AC-1). Ergänzt die READ-ONLY Artist-Detailseite
(`control_center/templates/library_artist_detail.html`, `GET
/library/{artist}`) um ein neues Panel „📝 Metadaten bearbeiten" mit drei
Aktionen: 🎤 Artist bearbeiten, 🎵 Titel bearbeiten, 🎭 Genre-Verwaltung.

**Reine Verdrahtung, keine neue Ausführungslogik** (Auftrag §14):
verwendet ausschließlich die bereits produktiven Endpunkte
- `GET /api/v1/admin/maintenance/artist-rename/preview` +
  `POST .../execute` (`control_center/routers/admin_maintenance.py`,
  unverändert seit dem vorherigen Maintenance-Schritt),
- `GET /api/v1/admin/maintenance/title-edit/preview` +
  `POST .../execute` (derselbe Router),
- `GET /api/v1/library/artists/{artist}/genre-preview` +
  `POST /api/v1/library/artists/{artist}/set-genre`
  (`control_center/routers/metadata_actions.py`).

Kein einziger neuer Router, kein neues Schema, keine neue Executor-/
Backup-/Verification-Logik — identisches Preview→Confirm→Execute-Muster
wie das bestehende generische Formular in `admin.html`
(`window.confirm()` vor jeder schreibenden Aktion, Auftrag §25).

**Unterschied zum generischen `admin.html`-Formular:** Der Artist ist
hier nicht mehr ein Freitextfeld, sondern kommt implizit aus dem bereits
etablierten `currentArtistFromPath()` (Auftrag §12 „Artist-Kontext über
den gesamten Flow" — der Nutzer muss den Artist nicht erneut auswählen).

**Korrektur nach Review (Adversarial Review vor Merge, siehe PR #282):**
Ein erster Implementierungsstand navigierte nach „Artist bearbeiten"
per `window.location.href` auf `/library/{new_artist}`, mit der
(falschen) Begründung, der Artist-Ordner werde umbenannt. Tatsächlich
ist `apply_artist_rename()` (`services/library_repair/executor.py`)
**ausschließlich tag-wert-getrieben** — es schreibt nur die
`©ART`/`ARTISTS`-Freeform-Atome der Dateien, deren aktueller Tag-Wert
(casefold) `old_artist` entspricht; der Artist-**Verzeichnisname**, über
den diese Seite adressiert wird (`artist_directory` aus dem
zwischengespeicherten Health-Report, CC-AC-1), bleibt unverändert. Der
Redirect führte deshalb garantiert auf eine `404 ARTIST_NOT_FOUND` und
riss dabei die gerade angezeigten Erfolgs-/Fehler-Zahlen weg. Alle drei
Aktionen laden nach Erfolg stattdessen ihre eigene Preview neu
(„Artist bearbeiten"/„Titel bearbeiten": `loadArtistEditPreview()`/
`loadTitleEditPreview()`; „Genre-Verwaltung":
`loadGenreManagePreview()`) und zeigen zusätzlich einen Hinweis, dass
die Artist-/Track-Übersicht dieser Seite aus dem zwischengespeicherten
Health-Report stammt und erst nach einem Neuscan (Telegram „🩺 MusicBot
Doctor" oder CLI) den neuen Wert zeigt — konsistent mit der in CC-AC-1
etablierten Read-Pfad-Entscheidung (`load_cached_report()`, kein
impliziter Scan). Ebenfalls aus dem Review: die per-Datei-`reason`
(z. B. „Artist-Tag entspricht nicht dem gewählten Ausgangswert") wird
jetzt auch im No-Op-Fall angezeigt statt verschluckt, und „Titel
bearbeiten" bekam einen clientseitigen UX-Scope-Guard (`rel_path` muss
mit `{artist}/` beginnen — keine Sicherheitsgrenze, `safety_check()`
im Executor bleibt die eigentliche Schranke) sowie eine
Preview→Execute-Kopplung (Eingabefeld-Änderung nach geladener Vorschau
deaktiviert den Ausführen-Button wieder, bis erneut „Vorschau laden"
gedrückt wurde).

**Sichtbarkeitsschranke:** Das gesamte Panel ist standardmäßig
`hidden` und wird nur eingeblendet, wenn `GET /api/v1/auth/whoami`
`access_level` „ADMIN" oder „OWNER" liefert — zusätzlich zur ohnehin
serverseitig auf `AccessLevel.ADMIN` gegateten API (Master-Prompt Regel
30: kein reiner UI-Check als alleiniger Schutz, hier eine zusätzliche
sichtbare UX-Schranke gemäß Task-Scope-Vorgabe).

- Keine Änderung an `admin_maintenance.py`, `metadata_actions.py`,
  `maintenance_service.py` oder den zugehörigen Schemas — reine
  Template-/JS-Ergänzung.
- Test: 14 neue UI-Tests in `tests/test_control_center_ui.py` (Panel
  standardmäßig versteckt, Admin-Gating-Code vorhanden, alle sechs
  Button-IDs vorhanden, Verdrahtung auf die drei bestehenden
  Endpunktpaare, impliziter Artist-Kontext statt Freitextfeld,
  `window.confirm()` vor jeder Aktion, sowie sechs Regressionstests aus
  dem Review: kein `window.location.href` nach Artist-Rename, jede
  Aktion laedt nach Erfolg ihre eigene Vorschau neu, SKIPPED/FAILED-
  Gruende werden angezeigt, Preview↔Execute-Kopplung, Titel-Edit-Scope-
  Guard, kein „Netzwerkfehler"-Text bei unbekanntem Ausgang). Gezielt:
  21/21 grün (`test_control_center_ui.py -k artist_detail`). Regression:
  `test_control_center_admin_maintenance_api.py` (15/15) +
  `test_control_center_metadata_actions_api.py` (15/15) unverändert
  grün — beide Endpunkte selbst wurden nicht angefasst. Thematische
  Suite: gesamte `tests/test_control_center*.py` 408/408 grün.
  `node --check` für den neuen/geänderten Skript-Block der
  Artist-Detailseite grün. Vollständige Projekt-Suite bewusst nicht
  durch den Implementierungsprozess ausgeführt (CLAUDE.md §8.A) — dem
  Nutzer empfohlen.
- Keine neuen Dependencies.
- **Nicht Teil dieses Schritts** (Folge-Tasks): Album/Albuminterpret-
  Editing (CC-AC-3), Library-Wartung wie Artist-Casing/Legacy-Genre-
  Cleanup/Genre-Revalidierung/L2-L3-Reparatur im Artist-Kontext
  (CC-AC-4), Navigation-Cleanup (CC-AC-5). Das generische
  Maintenance-Formular in `admin.html` bleibt unverändert erhalten
  (Auftrag §39) — mit dieser Phase teilweise redundant zu den neuen
  Artist-kontextbezogenen Aktionen, Bewertung folgt in CC-AC-5.

## Navigation Cleanup — Analyse (CC-AC-5) (2026-09-21, auf Nutzerfreigabe)

Fünfter und reiner Analyse-Schritt aus `library_artist_centric_UX.txt`
(Folge-Task zu CC-AC-1..4). **Kein Code geändert** — nur diese
Doku-Notiz, wie im Auftrag als optionaler Output vorgesehen (Auftrag
§19/§39, SCOPE-HINWEIS des Master-Prompts). Sidebar
(`control_center/templates/_base.html`) und die von CC-AC-1..4 direkt
betroffenen Seiten wurden auf Redundanz gegen die neue
Artist-zentrierte Library-/Wartungs-Oberfläche geprüft.

**Ergebnis — drei Kategorien:**

**[behalten]**
- Sidebar-Eintrag „🏷 Metadata" (`/metadata`) als Seite bleibt — enthält
  perspektivisch weitere globale Metadata-Funktionen und ist über die
  Overview-Schnellzugriffe (`overview.html`, „Schnellzugriff"-Kachel
  „Metadata") sowie über Routen-Existenz-/Inhalts-Tests
  (`tests/test_control_center_ui.py:31-32,779-800`) verankert.
- Sidebar-Eintrag „⚙ Administration" (`/admin`) bleibt vollständig —
  Sektion „Nutzer & Rollen" ist genuin global/System (keine
  Artist-Entsprechung) und hat keinen Ersatz im Artist-Kontext.
- Sidebar-Eintrag „🔧 Repairs" (`/repairs`) bleibt vollständig — der
  Panel „Repair-Plan (Vorschau)" (SAFE_AUTOMATIC) ist global, nicht
  artist-spezifisch (SCOPE-HINWEIS des Master-Prompts, explizit
  bestätigt: „L2/L3 globale Buttons bleiben gültig"). Auch der Panel
  „L2/L3-Reparaturen (nach Artist)" ist trotz Pro-Artist-Ausführung
  **keine** reine Redundanz zu Artist-Detail → 🔧 L2/L3 Reparatur: Er
  übernimmt die **Discovery**-Funktion („welche Artists haben
  überhaupt offene L2/L3-Befunde, gruppiert über die ganze Library")
  über `GET /api/v1/library/repair-plan/by-artist`, die es im
  Artist-Kontext nicht gibt (dort ist der Artist bereits bekannt,
  keine Cross-Artist-Übersicht). Beide Einstiege lösen dieselben
  Job-Endpunkte aus (`POST /api/v1/jobs/repair-level2`/`-level3`) —
  komplementär, nicht redundant.
- „🎭 Mapping"-Anzeige im Library-Panel (`GET
  /api/v1/library/mapping-summary`) bleibt unverändert an ihrem
  Platz — explizit durch Auftrag §20 ausgeschlossen von jeder
  Umgruppierung in dieser oder einer künftigen Phase dieses
  Master-Prompts.
- „💿 Alben"/"🎵 Tracks"-Buttons im „Library-Metadata"-Panel
  (`library.html`, `GET /api/v1/library/albums`/`/tracks`) bleiben —
  sie liefern eine **globale**, scan-basierte Sicht mit dem
  Fehlende-Metadata-Filter (`metadata-missing-filter`) über die
  gesamte Library, die im Artist-Detail (nur ein Artist, kein
  Filter) keine Entsprechung hat.

**[redundant]** (nicht gelöscht, siehe Auftrag §19/§39 — Consumer nicht
vollständig geprüft, siehe unten)
- `admin.html` → „Artist Casing korrigieren" — funktional deckungsgleich
  mit Artist-Detail → 🛠 Library-Wartung → 🎤 Artist Casing korrigieren
  (CC-AC-4, identischer Endpunkt `admin/maintenance/artist-casing`),
  jetzt nur noch mit Freitext-Artist-Feld statt implizitem Kontext.
- `admin.html` → „Legacy-Genre-Cleanup" — funktional deckungsgleich mit
  Artist-Detail → 🛠 Library-Wartung → 🧹 Legacy Genre bereinigen
  (CC-AC-4, identischer Endpunkt `admin/maintenance/legacy-genre-cleanup`).
- `admin.html` → „Artist umbenennen" — funktional deckungsgleich mit
  Artist-Detail → 📝 Metadaten bearbeiten → 🎤 Artist bearbeiten
  (CC-AC-2, identischer Endpunkt `admin/maintenance/artist-rename`).
- `admin.html` → „Titel bearbeiten" — funktional deckungsgleich mit
  Artist-Detail → 📝 Metadaten bearbeiten → 🎵 Titel bearbeiten (CC-AC-2,
  identischer Endpunkt `admin/maintenance/title-edit`).
- `metadata.html` → „Genre setzen" — funktional deckungsgleich mit
  Artist-Detail → 📝 Metadaten bearbeiten → 🎭 Genre-Verwaltung (CC-AC-2,
  identische Endpunkte `library/artists/{artist}/genre-preview` +
  `/set-genre`), nur mit Freitext-Artist-Feld statt implizitem Kontext.
  Seitentitel/Beschreibung sollten in einem Cleanup-Task angepasst
  werden (auf globalen Kontext hinweisen bzw. auf Artist-Detail
  verlinken), **nicht** löschen (Auftrag SCOPE-HINWEIS: „NICHT
  löschen").
- `library.html` → „Artists"-Button im „Library-Metadata"-Panel (`GET
  /api/v1/library/artists`, Klick-gesteuerter Voll-Scan, ~37 s) ist
  nach CC-AC-1 funktional durch die neue, automatisch geladene
  „🎤 Artists"-Sektion (`GET /api/v1/library/artists-overview`, ~0.02 s,
  persistenter Report) ersetzt worden — bereits in der CC-AC-1-Notiz
  oben als „teilweise redundant" markiert. Einziger verbleibender
  Unterschied: garantiert taufrische Live-Daten vs. ggf. veralteter
  Report (im UI bereits als „Stand: …"/„nicht mehr aktuell" markiert,
  CC-AC-1). Kein SCOPE-HINWEIS-Kandidat dieses Laufs, aber vom
  gleichen Muster betroffen — wird hier ergänzend aufgeführt.

**[möglicher späterer Cleanup]**
- Eigener Cleanup-Task (Folge-Task, nicht Teil von CC-AC-5): die vier
  `admin.html`-Formulare (Artist Casing, Legacy-Genre-Cleanup, Artist
  umbenennen, Titel bearbeiten) sowie die `metadata.html`-„Genre
  setzen"-Sektion auf einen reinen Verweis auf die jeweilige
  Artist-Detail-Aktion umstellen (oder mit einem Deep-Link
  `/library/{artist}` versehen), statt der Duplikat-Formulare mit
  Freitext-Artist-Feld. Voraussetzung laut Auftrag §39: vollständige
  Consumer-Prüfung (Links, Templates, Tests, Deep Links, evtl. externe
  Bookmarks) — insbesondere die Routen-/Inhalts-Tests in
  `tests/test_control_center_ui.py` (Zeilen 31-32, 779-800, 1057-1067)
  referenzieren `/admin` und `/metadata` direkt und müssten mit
  angepasst werden. Ebenfalls zu prüfen: ob die Freitext-Variante
  (Artist noch nicht per Klick ausgewählt, z. B. bei Bulk-artigen
  Werkzeugen/Skripten) einen eigenständigen Wert behält, der eine
  vollständige Entfernung ohnehin ausschließt — dann bliebe nur die
  Titel-/Beschreibungs-Anpassung aus dem SCOPE-HINWEIS als tatsächliche
  Änderung.
- `library.html` → „Artists"-Button (Live-Scan) könnte in einem
  eigenen Cleanup-Task entweder entfernt oder zu einem expliziten
  „Jetzt neu scannen"-Refresh für den bereits vorhandenen Report
  umgebaut werden — ebenfalls nicht Teil dieses Laufs.

**Zusätzliche Beobachtung (kein CC-AC-5-Scope, nur dokumentiert):** Diese
Architektur-Doku enthält bislang keine eigenen Einträge für CC-AC-3
(Album/Albuminterpret-Editing) und CC-AC-4 (Library-Wartung im
Artist-Kontext) — beide PRs (#283, #286) haben ausschließlich
`library_artist_detail.html` und `tests/test_control_center_ui.py`
geändert, keine Doku-Aktualisierung. Nachtrag wäre ein eigener,
separat freizugebender Schritt (Auftrag §45 „nur relevante
Dokumentation aktualisieren" — kein Teil des CC-AC-5-Scopes).

- Keine Code-/Template-/Router-/Test-Änderung in diesem Schritt (reine
  Analyse, SCOPE-HINWEIS: „REINE ANALYSE, KEIN Code wird geändert").
- **Nicht Teil dieses Schritts:** tatsächliche Löschung oder
  Umbau/Umsortierung der oben als redundant identifizierten Seiten
  (Auftrag §19/§39 — explizit ausgeschlossen für diesen Lauf), Nachtrag
  der fehlenden CC-AC-3/CC-AC-4-Doku-Einträge.

## Navigation Cleanup — Umsetzung (CC-AC-Cleanup) (2026-09-21)

Folge-Task zu CC-AC-5 (`docs/prompts/cc-ac-cleanup.txt`). Consumer-Check
vor Umsetzung zeigte: die im Task-Prompt referenzierten Testzeilen
(`tests/test_control_center_ui.py:31-32,779-800,1057-1067`, siehe
`[möglicher späterer Cleanup]` oben) waren durch zwischenzeitliche
Testdatei-Erweiterungen (CC-AC-2/3/4) bereits veraltet — die
tatsächlichen Fundstellen lagen bei 216-308, 419-793 bzw. 1056-1072.

**Umgesetzt (nach Nutzerfreigabe der Consumer-Check-Ergebnisse):**
- `admin.html`: die vier `[redundant]`-markierten Formulare (Artist
  Casing, Legacy-Genre-Cleanup, Artist umbenennen, Titel bearbeiten)
  durch einen Hinweis-Block mit Deep-Link auf `/library` ersetzt.
  Zugehörige, jetzt tote JS-Logik (`MAINTENANCE_ACTIONS` +
  Preview/Execute-Handler) mit entfernt — sonst hätte
  `document.getElementById(...)` auf den entfernten Elementen beim
  Seitenaufbau eine Exception geworfen und `initPage()`
  (Nutzerliste laden) nie mehr ausgeführt.
- `metadata.html`: die „Genre setzen"-Sektion analog auf einen
  Hinweis-Block mit Deep-Link auf `/library` umgestellt, zugehörige
  JS-Logik (`_genreSetArtist`, Preview/Execute) entfernt.
- Endpunkte (`admin/maintenance/*`, `library/artists/{artist}/set-genre`)
  und `library_artist_detail.html` (kanonische Stelle) unverändert.
- `tests/test_control_center_ui.py`: `test_metadata_page_has_genre_set_panel`
  → `test_metadata_page_has_genre_set_hint_block` (prüft Hinweis-Block +
  Deep-Link statt Formular-Markup); `test_metadata_page_confirm_dialog_mentions_backup_and_files`
  entfernt (prüfte einen jetzt nicht mehr vorhandenen `window.confirm()`-Text);
  neuer Test `test_admin_page_has_library_maintenance_hint_block` (für die
  vier `admin.html`-Formulare existierte zuvor keine dedizierte
  UI-Testabdeckung). Alle bestehenden, nicht direkt betroffenen Tests
  unverändert grün (128 passed, 2 vorbestehende, unabhängige Failures in
  `test_overview_contains_kpi_and_summary_elements`/
  `test_statistics_page_has_all_panels` — reproduziert auch am
  ungeänderten Stand, nicht Teil dieses Cleanups).

**Bewusst NICHT umgesetzt — HARD STOP (§7 des Task-Prompts):**
`library.html` → „Artists"-Button (Live-Scan) wurde **nicht** entfernt.
Drei bestehende Tests (`test_library_page_has_metadata_browser_panel`,
`test_library_page_ui_wiring_present`, insbesondere
`test_library_page_keeps_legacy_metadata_browser_unchanged` mit
Docstring „Auftrag §39: alte, Klick-gesteuerte
Tracks/Artists/Albums/Mapping-Sektion bleibt vollstaendig erreichbar,
unveraendert") verankern einen früheren, expliziten
Architekturentscheid aus CC-AC-1, der der aktuellen
Redundanz-Annahme direkt widerspricht. Der bereits oben (Zeile
1462-1471) dokumentierte verbleibende funktionale Unterschied
(garantiert taufrische Live-Daten vs. ggf. veralteter Report) bestätigt
diesen Konflikt. Nutzer hat auf Rückfrage entschieden: nur
`admin.html`/`metadata.html` umsetzen, `library.html` unangetastet
lassen. Bleibt offen für einen eigenen, gezielten Folge-Task mit
expliziter Entscheidung, ob der frühere CC-AC-1-Entscheid revidiert
werden soll.

## Overview Dashboard v2 — Health-Kachel ohne Full-Scan (2026-09-21, auf Nutzerfreigabe, `docs/prompts/CONTROL_CENTER_OVERVIEW_V2.md`)

Folge-Task zu PR #285/#289 („Overview-Dashboard an Leitfrage
ausgerichtet"). Jene Runde hatte Loading States, isolierte
Fehlerbehandlung pro Kachel und die kombinierte Systemstatus-Logik
bereits hergestellt — offen blieb genau ein Punkt, den dieser Task
gezielt schließt.

**Kernproblem, vor der Umsetzung verifiziert (Auftrag §4/§24):**
`overview.html::loadHealth()` rief bislang `GET /api/v1/library/health`
auf. Call-Path-Analyse: `routers/health.py::get_library_health()` →
`_library_scan.py::run_library_scan()` → `services/library_health/
scanner.py::run_scan()` — ein vollständiger Library-Scan (~37s auf
Produktion, identischer Aufrufpfad wie bei `GET /api/v1/library/artists`
vor CC-AC-1). Jeder Overview-Seitenaufruf löste diesen Scan ungefragt
aus.

**Entscheidung: identisches Muster wie CC-AC-1 (Zeile 1206 oben) —
additiver Endpunkt statt Änderung des bestehenden.** `GET /api/v1/
library/health` hat mit `control_center/templates/health.html` (der
dedizierten Health-Seite) einen zweiten, bewusst weiterhin
Live-Scan-erwartenden Aufrufer; ihn zu ändern wäre eine ungefragte
Verhaltensänderung außerhalb des Auftrags. Stattdessen:

- Neuer Endpoint `GET /api/v1/library/health/cached`
  (`control_center/routers/health.py::get_cached_library_health()`) im
  selben Router, gleiche Auth-Schwelle (`AccessLevel.USER`). Liest
  ausschließlich `_library_scan.py::load_cached_report()` — denselben
  bereits bestehenden persistenten Report
  (`Config.DATA_DIR/library_health_report.json`), den CC-AC-1 bereits
  für `/artists-overview` erschlossen hat. Kein Scan-Code dupliziert,
  keine neue Persistenzschicht.
- Fehlt der Report komplett → `HTTPException(404, code=
  "LIBRARY_REPORT_MISSING")`, identisches Fehlerformat wie
  `library_overview.py::_require_cached_report()` — kein impliziter
  Scan aus dem GET heraus.
- `schemas/health.py::CachedLibraryHealthResponse` (Subklasse von
  `LibraryHealthResponse`, zusätzlich `stale: bool`) statt Erweiterung
  der Basisklasse — `GET /health` bleibt dadurch byte-identisch zu
  vorher, `tests/test_control_center_health_api.py`s strikte
  `set(body.keys())`-Prüfung bricht nicht durch ein dort ungewolltes
  neues Feld. `report_to_cached_health_response()` baut auf der
  bestehenden `report_to_health_response()` auf (kein zweites
  Feld-für-Feld-Mapping).
- `overview.html::loadHealth()` ruft jetzt `/health/cached` auf, zeigt
  bei `stale: true` „⚠️ Report veraltet" statt einer Zeitangabe, sonst
  „geprüft vor X" (neuer lokaler `_timeAgo()`-Helfer, kein neuer
  Eintrag in `common.js`, da nur hier gebraucht). 404 (kein Report)
  wird als eigener, ehrlicher Zustand „Noch kein Report vorhanden"
  angezeigt statt als „Netzwerkfehler" — Kachel blockiert die übrigen
  Panels nicht (bereits bestehendes Isolationsmuster, unverändert).
- Quick Actions von `Library/Metadata/Repairs/Jobs` auf
  `Library/Downloads/Findings/Jobs` umgestellt (Auftrag §14). Metadata
  und Repairs bleiben vollständig über die Sidebar (`_base.html`)
  erreichbar — hier nur Priorisierung der vier global wichtigsten
  Bereiche, keine Funktion entfernt.

**Performance:** `GET /api/v1/library/health/cached` liest nur eine
bereits vorhandene JSON-Datei (kein Scan) — identische Größenordnung
wie das bereits gemessene `/artists-overview` (~0.02s statt ~37s bei
einem Scan). `run_scan()` ist im Overview-Ladepfad nicht mehr
erreichbar (per Code-Analyse UND per Test bewiesen, s. u. — nicht nur
per UI-Beobachtung, Auftrag §24).

Test: `tests/test_control_center_health_cached_api.py` (7 Tests:
frischer Report, veralteter Report mit `stale: true`, fehlender Report
→ 404, korrupter Report → 404, expliziter Beweis per Monkeypatch dass
`run_scan()` bei diesem Endpoint nicht aufgerufen wird, Regressionstest
dass `/health` unverändert bleibt). Regression:
`tests/test_control_center_health_api.py` (4/4),
`tests/test_control_center_library_overview.py` (11/11) unverändert
grün. Gesamte Control-Center-Themensuite (`tests/test_control_center*.py`)
450/452 grün — 2 bereits **vorbestehende, unabhängige** Failures
(`test_every_fetch_goes_through_api_url[overview.html]`,
`test_overview_contains_kpi_and_summary_elements`; Letztere bereits
oben im CC-AC-Cleanup-Abschnitt als vorbestehend dokumentiert), per
`git stash` gegen den ungeänderten Stand reproduziert — nicht Teil
dieses Tasks, nicht angefasst.

**Bewusst NICHT umgesetzt:** P1/P2/P3-Aufschlüsselung der offenen
Findings auf der Overview (Auftrag §10, dort ausdrücklich optional) —
`schemas/findings.py::FindingsSummaryResponse` liefert aktuell keine
Prioritäts-/Kategorie-Verteilung, das anzulegen wäre eine neue
Berechnung, die der Auftrag explizit ausschließt.

Vorher/Nachher-Screenshot: nicht möglich (keine Browser-Automatisierung
in dieser Session verbunden) — stattdessen Code-Pfad-Beweis (Grep +
Call-Path-Nachlese oben) und die o. g. Testabdeckung als Nachweis.

## Library UI Consolidation — CC-AC-7 (2026-09-21, `docs/prompts/cc-ac-7.md`)

**Problem:** `library.html` bündelte Artist-Browser (gecachter Report,
CC-AC-1) und Metadata-Diagnose (Legacy-Live-Scan, Tracks/Artists/Albums/
Mapping) gleichwertig nebeneinander; `library_artist_detail.html`
bündelte Alben/Tracks-Browsing und 9 Preview/Execute-Formulare (CC-AC-2/
CC-AC-3) plus 4 Maintenance-Aktionen (CC-AC-4) dauerhaft sichtbar auf
einer Seite. Ziel: eindeutige Informationsarchitektur Library → Artist →
Album/Track → gezielte Aktion, ohne neue Business-Logik/APIs/Security-
Änderungen (reines UI-/UX-Konsolidierungs-Ticket).

**Pflichtanalyse vor der Umsetzung (verifiziert, nicht angenommen):**
- `/metadata` (`control_center/templates/metadata.html`, 24 Zeilen) ist
  ein reiner Hinweis-Stub, der für Tracks/Artists/Albums/Mapping bereits
  auf `/library` zurückverweist — die vier Legacy-Scan-Funktionen sind
  **ausschließlich** in `library.html` erreichbar. Deep-Link-Verlagerung
  dorthin (wie im Ticket als „möglicher Zielzustand" skizziert) wäre
  daher irreführend; stattdessen Ticket-Option 3 gewählt: Funktion bleibt
  auf der Library-Hauptseite, wandert aber in einen initial eingeklappten
  Block.
- CC-AC-5-Korrektur (`docs/FINDINGS_INDEX.md`, CLOSED 2026-09-21) erneut
  am Code verifiziert: `GET /api/v1/library/artists` (Live-Scan, ~37s)
  und `GET /api/v1/library/artists-overview` (gecachter Report, ~0.02s)
  bleiben zwei unterschiedliche Datenquellen — der „Artists"-Button im
  Legacy-Block bleibt Pflichtfunktion.
- KPI-Datenquelle: `GET /api/v1/library/health/cached`
  (`control_center/routers/health.py`, bereits für das Overview-Dashboard
  eingeführt, s. o.) liefert `body.library.{files,artists,albums}` —
  genau die für die Library-KPI-Zeile benötigten drei Zahlen. Nach der
  Ticket-Vorgabe „falls ein bestehender Endpunkt die KPIs liefert, diesen
  verwenden" wird dieser Endpunkt konsumiert — keine Client-Aggregation,
  keine neue API.
- Artist-Liste ist nicht paginiert (`/artists-overview` liefert immer
  die volle Liste); aktuelle Artist-Anzahl im gecachten Report zum
  Zeitpunkt der Umsetzung: 41 (`data/library_health_report.json`) —
  deutlich unter der 200er-Schwelle des Tickets, client-seitige
  Sortierung ist damit zulässig.
- Kein Accordion-Pattern existierte im Projekt (`grep -rn "<details\|
  <summary" control_center/` → keine Treffer) — nativ mit
  `<details>/<summary>` neu gebaut, kein Framework, keine JS-Nachbildung
  der Tastatursemantik.

**Umgesetzte Änderungen:**
- `library.html`: neue KPI-Kachelreihe (`.tiles`, Wiederverwendung der
  bestehenden Kachel-Klasse aus `library_artist_detail.html`) aus
  `/health/cached`, mit eigenständiger Fehlerisolation (eigener
  try/catch-Fetch statt `_loadInto()`) — ein KPI-Fehler blendet nur die
  Kachelreihe aus und beeinträchtigt Artist-Liste/restliche Seite nicht.
  Neues Sortier-Dropdown (`#artist-sort`: Name/Dateien/Alben/Health) für
  die bereits vollständig geladene Artist-Liste, deterministisch mit
  Artistname (A–Z) als Tie-Breaker bei Gleichstand. Der bestehende
  „Library-Metadata"-Block (4 Scan-Buttons, Missing-Filter, gemeinsamer
  Ergebnis-Container — alle fünf Controls ausschließlich hier erreichbar,
  s. o.) wandert unverändert in ein initial eingeklapptes `<details>` am
  Ende der Seite; keine ID/kein JS-Funktionsname/keine Endpunkt-URL
  geändert.
- `library_artist_detail.html`: Grundreihenfolge (Header → Alben/Tracks →
  Admin-Aktionen) war bereits korrekt. Die beiden admin-only
  `<section>`-Panels („📝 Metadaten bearbeiten", „🛠 Library-Wartung")
  bleiben als äußeres Element mit unverändertem `id`/`hidden`-Attribut
  und unverändertem JS-Gating (`element.hidden = !isAdmin`) bestehen; ihr
  Inhalt wandert in ein verschachteltes `<details>`, initial eingeklappt.
  Keine der 9 Preview/Execute-Formulare bzw. 4 Maintenance-Aktionen
  wurde verändert, verschoben oder umbenannt.
- `common.css`: eine neue Regel (`summary { cursor: pointer; }`, plus
  `summary h2 { display: inline-flex; }` für die Kopfzeilen-Darstellung).
  Kein neuer Breakpoint, kein `outline: none` (Datei setzte dies
  ohnehin nirgends — native Fokus-Ringe für `<details>/<summary>` bleiben
  automatisch erhalten).

**Accessibility:** ausschließlich native `<details>/<summary>`-Semantik
verwendet — kein künstliches `aria-expanded` (nur für JS-gesteuerte
Custom-Accordions nötig, der Browser verwaltet den Expanded-State bei
nativen Elementen selbst), keine JS-Nachbildung von Tastatursteuerung
(Enter/Space öffnen/schließen nativ). Sichtbarer Fokus-Zustand und
vollständige Tastaturbedienbarkeit im Browser-Check verifiziert.

**Bewusst unverändert:** `services/library_repair/maintenance_service.py`
(`_resolve_within()`, `artist_targets()`, `album_targets()`,
`_title_edit_targets()`) und `services/library_repair/executor.py::
safety_check()` (CC-AC-6-Containment) — nicht angefasst, kein
Code-Diff. Das zurückgestellte CC-AC-6-Finding zu `album_targets()`s
totem `is_symlink()`-Check (`docs/FINDINGS_INDEX.md`, OPEN/DEFER, P3)
bleibt unverändert offen — reines UI-Ticket, kein Bezug zu
`services/library_repair/`.

**Tests:** `tests/test_control_center_ui.py` um 5 neue Tests ergänzt
(KPI-Tiles, Sortier-Control, Library-Metadata-`<details>` ohne `open`,
Metadata-Edit-`<details>` ohne `open`, Maintenance-`<details>` ohne
`open`) — bestehende Tests inhaltlich unverändert. Sicherheitsrelevant:
`tests/test_control_center_admin_maintenance_api.py` und
`tests/test_library_repair_maintenance_service.py` unverändert grün
(reine Bestätigung, keine Anpassung nötig).

## Track-Centric Library Actions — CC-AC-9 (2026-09-21, `CC-AC-9.md`, auf Nutzerfreigabe)

**Ausgangsproblem:** Die Track-Zeilen auf `/library/{artist}` (CC-AC-8:
nach Album gruppiert, `<details>`-Akkordeon) waren reine `<div>`-Anzeige
ohne Interaktion. Metadaten-Aktionen (Titel/Artist/Album/Albuminterpret/
Genre bearbeiten) lebten ausschließlich als artistweite Formulare im
separaten „📝 Metadaten bearbeiten"-Panel weiter unten auf derselben
Seite — kein direkter Weg von einem konkreten Track zu einer auf ihn
bezogenen Aktion oder seinem Health-Status.

**Neue Objekt-/Navigationsstruktur:** Track-Zeilen sind jetzt native
`<button class="row-item track-row" data-track-path="…">` (kein
`<div onclick>`-Pseudo-Button, Auftrag §4) und öffnen per Klick/Enter/
Space einen Track Detail Drawer (rechtsseitiges Panel, `#track-drawer-
overlay`/`#track-drawer`) mit den Abschnitten Information/Health/
Aktionen — Library → Artist → Track → Detail/Health/Action, wie im
Auftrag als Zielarchitektur beschrieben. Album bleibt bewusst NICHT
Teil dieses Tickets (Auftrag §13: „vorbereiteter nächster
Evolutionsschritt") — nur die Track-Ebene wurde umgesetzt.

**Track-Detail-Kontext:** Information/Health kommen ausschließlich aus
den bereits über `GET /api/v1/library/artists-overview/{artist}`
geladenen `TrackSchema`-Feldern (`_artistDetailTracksByPath`, keyed nach
`relative_path`) — kein neuer API-Call. Information zeigt Titel, Artist,
Album, Album Artist, Genre, Jahr, Track-/Disc-Nummer, MusicBrainz
Recording-/Release-ID, ISRC (exakt die in Auftrag §8 gelisteten,
bereits unterstützten Felder). Health zeigt `t.issue_codes` (Scope.FILE,
`services/library_health/issues.py::REGISTRY`) über eine reine
Anzeige-Label-Map (`_TRACK_ISSUE_LABELS`, keine neue Diagnoselogik,
Auftrag §7) — bei leerer Liste ein neutraler Hinweis („Keine bekannten
Probleme laut letztem Health-Scan"), nie eine erfundene „Metadata
vollständig"-Behauptung.

**Verwendete bestehende APIs — keine neue Business-Logik:** Die
Drawer-Aktionen führen selbst nichts aus. Sie öffnen/befüllen
ausschließlich die bereits vorhandenen, andernorts getesteten Formulare
im „📝 Metadaten bearbeiten"-Panel (CC-AC-2/3) und rufen deren bereits
bestehende `loadTitleEditPreview()`/`loadGenreManagePreview()` auf bzw.
setzen Fokus auf das passende Eingabefeld (Artist/Album/Albuminterpret —
dort fehlt der Zielwert, daher kein automatischer Preview-Aufruf).
„Album bearbeiten"/„Albuminterpret bearbeiten" werden nur angeboten,
wenn `_trackAlbumValue()` einen Wert liefert — identische `.m4a`-/
Album-Directory-Semantik wie der bestehende Album-Picker
(`_artistAlbumOptions()`) bzw. `maintenance_service.py::album_targets()`
(nur `.m4a`, sonst leere Zielmenge). „🛠 Library-Wartung"-Verknüpfung
öffnet unverändert das bestehende Maintenance-Panel. Kein neuer
Endpunkt, keine neue `fetch()`/`POST`-Ausführung im Drawer-Code
(verifiziert per Test, s. u.).

**Preview/Execute-Erhalt:** Die Drawer-Aktionen springen in die
bestehenden Formulare und lösen höchstens deren `load*Preview()` aus —
der Execute-Button, `window.confirm()`-Bestätigungstext und die
`POST .../execute`-Aufrufe selbst wurden nicht verändert. Preview→
Confirm→Execute bleibt exakt der bestehende, in
`test_control_center_admin_maintenance_api.py`/
`test_library_repair_maintenance_service.py` unverändert grün getestete
Pfad (Auftrag §10).

**Accessibility:** `role="dialog"`/`aria-modal="true"`/
`aria-labelledby="track-drawer-title"` statisch im Markup. Escape
schließt den Drawer, Tab/Shift+Tab kreisen innerhalb des Dialogs
(`_trackDrawerFocusableEls()`), Fokus wandert beim Öffnen auf den
Schließen-Button und beim Schließen zurück auf die auslösende
Track-Zeile (`_trackDrawerTriggerEl`). Sichtbarkeit über das bereits
etablierte native `hidden`-Attribut (identisch zu
`artist-metadata-edit-panel`) — kein zusätzliches `aria-hidden`, kein
künstliches `aria-expanded`. Browser-/Playwright-Verifikation wurde
NICHT durchgeführt (kein Headless-Browser in dieser Umgebung verfügbar)
— siehe „Offene Folgearbeiten".

**Security-Unveränderheit:** `services/library_repair/
maintenance_service.py` (`_resolve_within()`, `artist_targets()`,
`album_targets()`, `_title_edit_targets()`, `safety_check()` in
`executor.py`) wurden nicht angefasst — kein Code-Diff außerhalb von
`control_center/templates/library_artist_detail.html`,
`control_center/static/common.css` und den Tests.
`tests/test_control_center_admin_maintenance_api.py` (61 Tests) und
`tests/test_library_repair_maintenance_service.py` (68 Tests)
unverändert grün.

**Bewusste Nicht-Änderung von CC-AC-6:** Das zurückgestellte Finding zu
`album_targets()`s totem `is_symlink()`-Check
(`docs/FINDINGS_INDEX.md`, OPEN/DEFER, P3) bleibt unverändert offen —
kein Bezug zu diesem UI-Ticket.

**Tests:** `tests/test_control_center_ui.py` um 9 neue Tests ergänzt
(Track-Zeilen interaktiv, Drawer-Markup vorhanden, angezeigte Metadaten-
Felder, Health aus `issue_codes` ohne erfundene Aussage, gebündelte
bestehende Aktionen, Preview/Execute-Erhalt ohne neue `fetch()`/`POST`,
Dialog-Accessibility-Semantik, Admin-Gating, `.m4a`-Scope für Album-
Aktionen) — 148/148 in `tests/test_control_center_ui.py` grün, 129/129
in den beiden Maintenance-/Sicherheits-Suiten unverändert grün, 500/500
in allen `control_center`-Tests (`pytest tests/ -k control_center`)
grün. Volle Suite (`pytest tests/ -q`) bewusst nicht durch den
Implementierungsprozess ausgeführt (§8.A) — dem Nutzer empfohlen.

**Offene Folgearbeiten:**
- Playwright-/Browser-Runtime-Test (Auftrag §20) wurde nicht
  durchgeführt — diese Umgebung hat keinen Headless-Browser verfügbar.
  Manuelle Verifikation (Track anklicken/Tab/Enter/Escape, Drawer-Inhalt,
  Responsive 360/390/412/1280px) steht noch aus.
- Album-Klickbarkeit/eigener Album-Kontext bleibt wie in Auftrag §13
  vorgesehen ein separater, nicht in CC-AC-9 erzwungener Folgeschritt.
- Spätere Umbenennung „Library-Metadata" → „Library Diagnostics"
  (CC-AC-9-Vorschlagsdokument, Abschnitt 8) bleibt wie dort beschrieben
  eine bewusst nicht in diesem Ticket gezogene Folgearbeit.

## Health Center — MusicBot Doctor/Findings/Repair/Jobs-Konsolidierung (2026-09-22, `api_health.md`, auf Nutzerfreigabe)

**Charakterisierungsbefund vor der Implementierung (Auftrag §1):** entgegen
der im Auftrag unterstellten Ausgangslage ("komplett neu integrieren")
existierten Backend UND ein funktionierendes Web-Frontend für MusicBot
Doctor/Library Health Review/Repair MusicBot bereits praktisch vollständig
— nur auf vier getrennten Seiten (`/health`, `/findings`, `/repairs`,
`/jobs`) statt einer. Die Jobs-Seite hing ausschließlich an Repair-Jobs
(`demo_progress`/`repair_safe_automatic`/`repair_level2`/`repair_level3`,
`control_center/routers/jobs.py`) — keine fremde Fähigkeit war betroffen,
was eine Konsolidierung risikoarm machte. Der reale Umbau war damit primär
UI-Konsolidierung + drei echte, additive API-Lücken, kein Neubau. Fünf
Phasen, je ein eigener Commit (CLAUDE.md Abschnitt 8 "kleinste sinnvolle
Schritte"):

**Phase 1 — additive Read-APIs** um bereits vorhandene Service-Funktionen,
kein UI-Umbau:
- `GET /api/v1/library/health/score-history` (`routers/health.py`,
  AccessLevel.USER) — wrappt `services/library_health/score_history.py::
  read_score_history()`, bereits von jedem Scan befüllt, bisher ohne
  Web-API.
- `GET /api/v1/library/repairs/history` + `.../repairs/statistics`
  (`routers/repair.py`, AccessLevel.ADMIN, Auftrag §15 "Repair
  History/Actions" == ADMIN) — wrappen `services/library_repair/
  run_tracking.py::load_repair_history()`/`compute_repair_statistics()`.
  Records aus vier verschiedenen Producern (`repair_service.py` ×2,
  `maintenance_service.py`, `genre_revalidation.py`) haben nicht
  identische Feldmengen (z. B. `artist`/`issue_codes` nur bei manchen) —
  `RepairHistoryEntry` bildet das bewusst mit Optional-Feldern ab statt
  eines für nur einen Producer passenden strikten Schemas.

**Phase 2 — generischer Findings-Review-Endpunkt** (Auftrag §7):
`POST /api/v1/library/findings/{id}/review` (`routers/findings.py`) ruft
direkt `FindingsRegistry.review_finding()` auf. Additiv NEBEN den
bestehenden `.../accept`/`.../unaccept`-Endpunkten, kein Ersatz — diese
bleiben die spezialisierte FALSE_POSITIVE-Aktion mit Pflicht-Grund; der
neue Endpunkt deckt zusätzlich den manuellen RESOLVED-Review ab, den
`accept_finding()` (fest auf FALSE_POSITIVE) nicht ausdrücken kann.
Erzwingt für FALSE_POSITIVE dieselbe Pflicht-Grund-Regel wie
`accept_finding()`, damit dieser Endpunkt keinen laxeren Weg zum selben
Ergebnis öffnet.

**Phase 3 — Health-Scan als Job** (Auftrag §5 "Wenn der Scan länger läuft:
als Job ausführen"): `POST /api/v1/jobs/health-scan` (Job-Kind
`library_health_scan`, `routers/jobs.py`) ruft `services/library_repair/
doctor_runner.py::run_health_scan()` auf — denselben Subprozess-Aufruf wie
die erste Phase von `_run_safe_automatic_repair_job()`. Bewusst NICHT die
leichtgewichtige `control_center/_library_scan.py::run_library_scan()`
(Konsument: `GET /health`, `GET /repair-plan`): jene führt nur einen
In-Memory-Scan für genau eine HTTP-Response aus und schreibt weder den
persistenten Report noch die Score-History noch mergt sie die
Findings-Registry (siehe deren Modul-Docstring) — `run_health_scan()`
dagegen startet `scripts/library_health_check.py` als Subprozess, der
genau diese drei Seiteneffekte auslöst, identisch zu einem Telegram
„🩺 MusicBot Doctor"-Scan. `GET /health` bleibt unverändert (dort bereits
dokumentierte Hard-Stop-Entscheidung, s. o. „Overview Dashboard v2") — nur
additiv ein neuer Job-Typ ergänzt.

**Phase 4 — UI-Konsolidierung:** `control_center/templates/health.html`
wird zum Health Center mit vier Tabler-Cards (🩺 MusicBot Doctor — Score/
Library-Kacheln/Score-Verlauf/Scan-Button; 🔎 Library Health Review —
offene/akzeptierte Findings, neuer Severity-/Kategorie-Filter (Auftrag
§8), neue „Repariert"-Aktion über den Phase-2-Review-Endpunkt; 🛠 Repair
MusicBot — SAFE_AUTOMATIC + L2/L3 unverändert; Repair-History/-Statistik +
kompakte Job-Liste). Sidebar (`_base.html`) hat jetzt genau einen
🩺-Health-Eintrag (Auftrag §3) — `/findings`, `/repairs`, `/jobs` als
eigene Seiten/Templates/Routen entfallen; ihre APIs bleiben unverändert.
Fachlogik lebt komplett in `control_center/static/pages/health.js`
(Auftrag §16 "kein riesiges Inline-JavaScript") statt inline in der
Seite — reine Wiederverwendung der bestehenden `common.js`-Helfer
(`apiUrl()`/`_loadInto()`/`_escapeHtml()`/`showOnly()`/`checkAuth()`),
keine duplizierte Logik. `overview.html`s Quick-Access-Karten/Attention-
Link zeigen jetzt auf `/health` statt getrennt auf `/findings`/`/jobs`.

- Tests: 273 Tests über die betroffenen Testdateien (`test_control_center_
  health_score_history_api.py` neu, `test_control_center_repair_history_
  api.py` neu, `test_control_center_findings_api.py`/`_jobs_api.py`/
  `_ui.py`/`_subpath_ui.py` erweitert) — alle grün, Findings/Repair/Jobs/
  Health-API-Regression (`test_control_center_{findings,repair,jobs,
  health,health_cached}_api.py`, `test_control_center_auth.py`)
  unverändert grün.
- Beim Anpassen der UI-Tests inzidentell mitkorrigiert (drei
  vorbestehende, von dieser Phase unabhängige Test-vs-Markup-Drifts, nur
  weil exakt dieselben Zeilen ohnehin geändert wurden): eine veraltete
  `/repairs`-Quick-Action-Assertion in `test_overview_quick_actions_link_
  to_detail_pages`, eine veraltete `class="panel-link"`-Assertion (die
  Tabler-Migration von `overview.html` hatte sie durch Tabler-
  Button-Klassen ersetzt), und mehrere `nav-link active`-Assertionen, die
  Ein-Zeilen-Attribute annahmen, obwohl `_base.html` `href`/`class` als
  eigene Zeilen rendert. Andere, im selben Testlauf sichtbare, von dieser
  Phase unabhängige Fehlschläge (Library/Metadata/Admin/Artist-Detail-
  Seiten — von dieser Phase nicht berührt) bleiben unangetastet
  (CLAUDE.md Abschnitt 8.A).
- Keine neuen Dependencies.


---

## Erweiterung — Navidrome: Vollständige Telegram-Parität (Branch `control-center-navidrome`, 2026-09-23, auf Nutzerfreigabe)

Erweitert die ursprüngliche Navidrome-Status-Anbindung (2026-09-15, s. o.
„Erweiterung — Navidrome-Status") zur vollständigen REST-Parität mit dem
Telegram-`NavidromeMenuHandler` (`handlers/navidrome_menu_handler.py`).
Keine neue Fachlogik — der bestehende, Telegram-freie Integrationsadapter
`services/clients/navidrome_api.py::NavidromeAPI` wird unverändert
weiterverwendet; ein neuer, dedizierter Reader-Helper `fetch_cover_art()`
ergänzt ihn (Subsonic `getCoverArt` liefert Binaerdaten, nicht JSON —
passte nicht in `make_request()`).

**Umfang (20 Endpunkte statt der bisherigen 2):**

| Kategorie | Endpunkte |
|---|---|
| Status/Scan | `GET /status`, `POST /scan` (unverändert) |
| Browse | `GET /artists` (paginiert), `GET /artists/{id}`, `GET /albums` (paginiert, optional `artist_id`), `GET /albums/{id}`, `GET /genres`, `GET /genres/{name}`, `GET /songs/{id}` |
| Suche/Entdecken | `GET /search?q&type`, `GET /random`, `GET /newest`, `GET /artists/{id}/top`, `GET /favorites` |
| Playlists (CRUD) | `GET /playlists` (paginiert), `GET /playlists/{id}`, `POST /playlists`, `PUT /playlists/{id}`, `DELETE /playlists/{id}` |
| Cover-Proxy | `GET /cover/{id}` (Bytes-Durchreichung, `Cache-Control: max-age=86400`) |

**Architektur-Entscheidungen:**

- **Serverseitige Pagination von Anfang an** (`page`/`page_size`/`total`/
  `has_next` in jedem Listen-Response) — Lehre aus dem 1114-Kandidaten-/
  1173-Accepted-Findings-Präzedenzfall, nicht erst nach einem Live-Fund
  nachgezogen.
- **Gemappte Pydantic-Schemas, kein 1:1-Subsonic-Passthrough** — camelCase-
  Subsonic-Felder (`songCount`, `coverArt`, `artistId`) werden im Router
  auf snake_case Control-Center-Schemas umgesetzt (identisches Prinzip
  wie `schemas/health.py` vs. `services/library_health/models.py`).
- **`async def`-Router mit lokalem `_req()`-Wrapper** für synchrone
  `NavidromeAPI.make_request()`-Aufrufe (`asyncio.to_thread`) —
  identisches Muster wie `handlers/navidrome_menu_handler.py`. Die
  höherstufigen Methoden (`check_connection()`, `get_artists()`,
  `search()`) sind bereits intern `asyncio.to_thread`-gewrappt und werden
  direkt awaited.
- **Cover-Proxy** (`GET /cover/{id}`) — der Browser kann `<img src>` nicht
  direkt auf Navidrome zeigen lassen (Subsonic-Auth erfordert
  Query-Parameter, die das Navidrome-Passwort im Klartext tragen); die
  Bytes werden durch das Control Center geproxied. Der bestehende
  Credential-Scrubbing-Pfad `navidrome_api.py::_scrub_credentials()` bleibt
  unberührt.
- **Schreibende Endpunkte** (Playlist-CRUD) sind USER-gated (identisch
  zur Telegram-Seite, die keine Admin-Rolle für Playlists verlangt) und
  zusätzlich CSRF-geschützt (`verify_same_origin`); `POST /scan` bleibt
  ADMIN-only.
- **Kein gemeinsamer Zustand, keine gemeinsamen Imports** zwischen
  Telegram-Handler und Control-Center-Router — beide Consumer nutzen den
  `NavidromeAPI`-Adapter, sonst nichts (bewusste Grenze, wie durch
  `ARCH-009 Phase 8` etabliert).

**Frontend** (`templates/navidrome.html` + `static/pages/navidrome.js`):

- 7 Tabler-Tabs (Artists/Alben/Genres/Suche/Playlists/Favoriten/
  Entdecken) mit Lazy-Loading pro Tab
- Modal-Stack-Navigation für Detail-Ansichten (`_navView`-Objekt) mit
  Breadcrumb, Back-Button und nativem `×`-Schließen; ESC und
  Klick-außerhalb funktionieren ebenfalls. Behebt einen konkreten
  Navigationsbug, bei dem man aus einem Artist-Detail-Modal nicht mehr
  herauskam (Root-Cause: `d-none` auf dem Back-Button bei Stack-Tiefe 1
  plus unsichtbarer `.btn-close` im Dark-Theme).
- Cover-Art-Cards statt Text-Tabellen für Alben-Liste und Artist-Detail
- Artist-Liste mit Avatar-Icon + Album-Count; Song-Tabellen mit
  Track-Nummer und Dauer
- Suche mit Ergebnis-Sektionen pro Typ

**Bewusst NICHT umgesetzt (Folge-Scope):**

- Kein Player/Streaming (Navidrome bleibt für Playback zuständig, s.
  ursprünglichen Architecture-Proposal §8 „Future Player Integration")
- Kein Live-„Now Playing"-Widget (der zugrunde liegende Zustand
  `get_now_playing()` ist Abfrage-, nicht Push-basiert — ein sinnvolles
  Widget bräuchte Polling-Infrastruktur, die nicht Teil dieses Schritts
  war)
- Kein „Song zu Playlist hinzufügen"-Picker (in Telegram ebenfalls nicht
  vorhanden — bräuchte einen Mehrfachauswahl-Song-Picker, eigener
  Folge-Scope laut ARCH-033/NAV-F18)

**Tests:** Volle Suite auf dem Branch: **5445 passed, 1 skipped, 6
warnings, 11 subtests passed** (322.78 s, 2026-09-23) — die Differenz von
-28 Tests gegenüber dem zuletzt in `MusicBot_ENGINEERING_BASELINE_v11.md`
dokumentierten `main`-Stand (5473 passed, 2026-09-22) ist auf den
Branch-Vorsprung von `main` zurückzuführen (CC-AC-10-Arbeit), nicht auf
diesen Branch — nach dem Merge werden die Tests wieder zusammengeführt.

**Kein Live-Smoke-Test gegen den echten Navidrome-Server für die
schreibenden Endpunkte** (Playlist-CRUD verändert echte Daten) — nur
gegen isolierte Testdaten. Reine Lesefunktionen (Browse, Suche,
Cover-Proxy) wurden manuell gegen den echten Server verifiziert.

**Keine Telegram-Änderung:** `handlers/navidrome_menu_handler.py` bleibt
vollständig unverändert.
---

## Erweiterung — CC-LOGGER-L2: Logger Read API (2026-09-23, auf Nutzerfreigabe)

Erster Schritt aus dem Phasenplan `logge.txt` (L1–L7) — **reine
Read-API** für die Klasse-A-Logger-Funktionen (shared filesystem,
prozessübergreifend gültig). Runtime-Control (Klasse B) ist bewusst
DEFERRED bis L3-Architekturentscheid; siehe Audit-Doc
`docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md`.

### L1-Charakterisierung (aus dem Repo, nicht angenommen)

`handlers/enhanced_logger_menu_handler.py::EnhancedLoggerMenuHandler`
(1711 Zeilen) teilt sich in drei Klassen:

- **A — shared filesystem** (Logdateien, `stat()`-Metadaten,
  Datei-Inhalt): aus CC-Prozess unverändert lesbar.
- **B — process-local** (`_module_loggers`, `loggerDict`,
  `Logger.handlers`, `Logger.disabled`, `ExceptionMonitor`): nur im
  Bot-Prozess. **Kein Inbound-Kanal** (einziger Mechanismus ist
  `systemctl restart`) → DEFERRED.
- **C — nicht implementiert** (`add_handler`/`remove_handler`/
  `add_module`/`download_log_file` sind im Telegram-Handler selbst
  Platzhalter ohne Funktion).

**Kritischer L1-Fund:** `ModuleLoggerManager._load_module_configs()`
liest die JSON beim Bot-Start, ruft aber `_apply_module_config()`
**nicht** auf. Die Datei ist keine Runtime-Wahrheit. Konsequenz: sie
wird in L2 **nicht** exponiert.

### Umfang

Neuer Application-Layer `services/logger_admin.py` (Telegram-frei,
FastAPI-frei) — ruft ausschließlich `services/logs/reader.py` auf
(kein zweiter Parser). Neuer Router
`control_center/routers/logger.py` unter `/api/v1/admin/logger/*`,
ADMIN-gated.

| Route | Response |
|---|---|
| `GET /api/v1/admin/logger/files` | Liste aller Logdateien (nach mtime, neueste zuerst) |
| `GET /api/v1/admin/logger/files/stats` | Aggregat: Anzahl/Gesamtgröße/größte/älteste Datei |
| `GET /api/v1/admin/logger/files/{name}` | Datei-Detail + Inhalt (Filter: `level`/`component`/`search`/`limit`) |

**Route-Reihenfolge** — `/files/stats` **vor** `/files/{name}`
deklariert (Starlette-Matching in Deklarations-Reihenfolge — sonst
wird `stats` als Dateiname interpretiert).

### Architektur

- **Application Layer (`services/logger_admin.py`)** — reine Funktionen
  auf einem übergebenen `log_dir: Path`. Exceptions:
  `LoggerAdminError`/`InvalidLogFilenameError`/`InvalidLimitError`.
  Keine HTTPException, kein Telegram.
- **Kein zweiter Parser** — `get_log_file()` ruft
  `reader.read_logs()` unverändert auf. Redaktion (ANSI/Secrets),
  Filter (Level/Component/Search), Truncation (`total_matched` >
  `limit`) bleiben in der bestehenden Schicht.
- **Security** — Whitelist (`list_log_sources()`) **plus**
  Containment-Check (`resolve().is_relative_to(log_dir)`) als zweite
  Verteidigungslinie. Identisch zum SEC-003-Fix in
  `EnhancedLoggerMenuHandler.show_log_file_detail()`.
- **Limit-Grenzen** — Default 200, Min 1, Max 2000. FastAPI lehnt
  Werte außerhalb mit HTTP 422 ab (kein stilles Clamping);
  `logger_admin.get_log_file()` validiert denselben Bereich defensiv
  ein zweites Mal (`InvalidLimitError`), damit direkte Aufrufer ohne
  HTTP-Durchlauf nicht umgangen werden.
- **`/api/v1/logs` bleibt unverändert** — jene Route ist die
  zeilenorientierte Live-Ansicht; die neue ist die dateiorientierte
  Übersicht. Kein Ersatz, keine Migration.

### Tests

- `tests/test_logger_admin.py` — Application-Layer (ca. 25 Tests):
  Liste/Stats/Detail/Traversal/Symlink/Limit-Grenzen.
- `tests/test_control_center_logger_api.py` — HTTP (ca. 24 Tests):
  Happy Path, Route-Reihenfolge, Traversal (`404`/`422` — nie `200`),
  Limit-Grenzen (`422` bei `0`/`-1`/`2001`/…, `200` bei `1`/`100`/`2000`),
  Auth, Regression `/api/v1/logs`.

Testergebnis: `86 passed` (4 Log-Suiten) + `529 passed` (gesamte
`control_center`-Suite).

### Bewusst NICHT umgesetzt

- Kein Runtime-Control (Klasse B).
- Kein Config-Exposure (`module_logger_config.json` — L1-Fund).
- Keine IPC-Infrastruktur (`logge.txt` §3C/§10).
- Keine UI (Prompt §12: UI ist L7).
- Keine Änderung an `handlers/enhanced_logger_menu_handler.py`
  (Telegram-Pfad unverändert, Prompt §11/§12).

---

## Erweiterung — CC-LOGGER-L3: Runtime-Control Architecture Decision (2026-09-23)

Analyse-Phase, kein Code. Architecture Decision Record für
Logger-Runtime-Control im MusicBot. Vorgänger: L2-Read-API
(`docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md`, gemergt als
PR #300).

**Kernbefund:** Es existiert heute **keine** Cross-Process-Runtime-
Infrastruktur — keine IPC, kein Socket, kein File-Watcher, kein
Reload-Trigger. Der einzige vorhandene Steuerungs-Mechanismus ist
`sudo systemctl restart bot` über `utils/bot_restart_trigger.py` (aus
CC-AC-10C über `POST /api/v1/admin/system/restart` erreichbar).

**Zusätzlicher Architektur-Bug:** `ModuleLoggerManager._load_module_
configs()` liest `data/module_logger_config.json` beim Bot-Start, ruft
aber `_apply_module_config()` nicht auf — die persistente Config ist
damit keine Runtime-Wahrheit.

**Entscheidung:** Inkrementeller Pfad statt Big-Bang-IPC:

| Stufe | Inhalt | Phase |
|---|---|---|
| 0 | Startup-Apply-Bugfix (harte Vorbedingung) | L4 |
| 1 | E2 Persistent Config über CC (Semantik „nächster Start") | L4 |
| 2 | Runtime Snapshot (read-only Observability) | L4 |
| 3 | Kontrollierter Apply/Restart mit Preflight + Rate-Limit | L5 |
| 4 | Unix-Socket Runtime Write | DEFERRED, nur bei belegtem Bedarf |

**Verworfen:** File-Watcher als dauerhafte Runtime-Infrastruktur,
Localhost-HTTP-Control-Server, jeder unnötige neue IPC-Stack.

**Vollständige Begründung, Vergleichsmatrix, Failure Analysis,
Security Threat Model:**
`docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md`.

---

## Erweiterung — CC-LOGGER-L4: Startup Apply + Persistent Logger Configuration (2026-09-23)

Erster Umsetzungsschritt nach der L3-Entscheidung
(`docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md`).

**Stufe 0 — Startup-Apply-Bugfix.** `ModuleLoggerManager._load_module_configs()`
liest die persistente Konfiguration jetzt und wendet sie per
`_apply_module_config()` auf die realen Logger an. Vorher war die
persistierte JSON für den laufenden Prozess wirkungslos; nach jedem
Neustart galten die Code-Defaults aus `logger.py`.

**Stufe 1 — Persistent Config API.** Zwei Endpunkte unter
`/api/v1/admin/logger/config`:

| Route | Auth | Zweck |
|---|---|---|
| `GET /config` | ADMIN | persistierte Konfiguration, read-only |
| `PATCH /config` | ADMIN + CSRF | Merge-by-module + merge-by-field, strikte Validierung |

Application Layer: `services/logger_admin.py` erweitert um
`read_logger_config()`, `validate_logger_config_patch()`,
`update_logger_config()` (atomarer Write), `LoggerConfigError`.

**Ehrliche Semantik:** PATCH bestätigt ausschließlich „gespeichert,
wirksam beim nächsten Bot-Start". Der laufende Bot-Prozess wird nicht
angefasst. Kein Fake-Live.

**Bewusst nicht implementiert:** Stufe 2 (Runtime Snapshot), Stufe 3
(kontrollierter Restart mit Preflight), IPC, Socket, UI,
Telegram-Migration — diese sind L5/L6/L7.

**Verhaltensänderung (quantifiziert):** ab dem ersten Neustart nach
dem Fix legen 40 Module je eine Log-Datei an, 18 davon auf
DEBUG-Level.

**Vollständige Begründung, Validationstabelle, Security-Analyse:
** `docs/audits/CC-LOGGER-L4_STARTUP_CONFIG_API_2026-09-23.md`.
