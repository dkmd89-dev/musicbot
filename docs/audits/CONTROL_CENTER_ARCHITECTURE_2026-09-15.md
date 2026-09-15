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
