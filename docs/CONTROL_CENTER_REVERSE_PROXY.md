# Control Center — Betrieb hinter nginx (Subpath `/controlcenter/`)

**Status:** CURRENT
**Scope:** `control_center/` (FastAPI), Betrieb sowohl direkt unter
`http://127.0.0.1:8420/` als auch über nginx unter
`https://<domain>/controlcenter/`.

## 1. Prinzip

nginx **entfernt** den Prefix (`proxy_pass http://127.0.0.1:8420/;` mit
Schrägstrich am Ende) und meldet ihn per `X-Forwarded-Prefix`. Die App
routet weiterhin auf Root-Pfaden und kennt den Prefix nur zur Erzeugung von
URLs:

```text
X-Forwarded-Prefix ──► ForwardedPrefixMiddleware (control_center/root_path.py)
                        ──► scope["root_path"]
                              ├─► Starlette: request.url, url_for(), Slash-Redirects
                              ├─► routers/ui.py::_render  ──►  base_path (Template)
                              │       ├─► <meta name="cc-base">  ──►  common.js: apiUrl()
                              │       └─► href/src in Templates
                              └─► routers/auth.py: Cookie-Path
```

Ohne Header (Direktbetrieb) ist `root_path == ""` und alles verhält sich wie
vorher.

## 2. nginx-Konfiguration (getestet mit nginx 1.24)

Im bestehenden `server { … }`-Block der Domain (neben den vorhandenen
Locations für Immich `/`, Navidrome, Hardware Deals):

```nginx
absolute_redirect off;   # falls noch nicht gesetzt: Redirects portunabhängig

location = /controlcenter { return 301 /controlcenter/; }

location /controlcenter/ {
    proxy_pass http://127.0.0.1:8420/;          # Schrägstrich am Ende = Prefix wird entfernt
    proxy_set_header Host $http_host;           # inkl. Port, für den Origin-Check
    proxy_set_header X-Forwarded-Proto $scheme; # https -> scope["scheme"]
    proxy_set_header X-Forwarded-Prefix /controlcenter;
}
```

`absolute_redirect off;` wirkt serverweit — falls andere Locations auf
absolute Redirects angewiesen sind, stattdessen nur
`return 301 https://$host/controlcenter/;` verwenden.

Pflicht-Header und Grund:

| Header | Wozu | Fehlt er … |
|---|---|---|
| `X-Forwarded-Prefix` | setzt `root_path` (Links, Redirects, Cookie-Path) | Seiten laden, aber alle Links/API-Calls zeigen auf `/` (= Immich) |
| `Host $http_host` | `verify_same_origin` vergleicht `Origin` mit `scheme://Host` | alle schreibenden Endpunkte → 403 `ORIGIN_CHECK_FAILED` |
| `X-Forwarded-Proto` | uvicorn (`--proxy-headers`, Default, vertraut `127.0.0.1`) setzt das Schema | Origin `https://…` ≠ `http://…` → 403 bei schreibenden Endpunkten |

nginx überschreibt einen vom Client mitgeschickten `X-Forwarded-Prefix`
(`proxy_set_header` ersetzt den Wert) — getestet.

## 3. uvicorn

Unverändert (nur Loopback, Prozess neben `bot.py`):

```bash
uvicorn control_center.app:app --host 127.0.0.1 --port 8420
```

`--forwarded-allow-ips` bleibt beim Default (`127.0.0.1`). **Nie**
`0.0.0.0` binden — der Prefix-Header wird nur validiert (`/seg/seg`,
URL-sichere Zeichen, sonst ignoriert), aber nicht nach Herkunft geprüft; die
Vertrauensgrenze ist die Loopback-Bindung.

## 4. Telegram-Login

- Bei BotFather `/setdomain` auf die **Domain** setzen (`romajagijo.zapto.org`).
  Der Pfad spielt keine Rolle.
- Das Widget nutzt `data-onauth` (JS-Callback), keine Redirect-URL.
- `BOT_USERNAME` muss serverseitig gesetzt sein, sonst zeigt die Login-Ansicht
  nur den Konfigurationshinweis.
- Das Session-Cookie `cc_session` (`HttpOnly; Secure; SameSite=strict`) wird
  hinter nginx mit `Path=/controlcenter` gesetzt — es wird nicht an Immich,
  Navidrome oder Hardware Deals gesendet. Direktbetrieb: `Path=/`.
- `Secure` gilt auch im Direktbetrieb: Chrome/Firefox akzeptieren es auf
  `http://127.0.0.1`, Safari nicht. Für lokale Entwicklung deshalb
  `CONTROL_CENTER_DEV_AUTH_BYPASS=true` (kein Cookie nötig), siehe README.

## 5. Regeln für neue UI-Seiten

Guard-Tests (`tests/test_control_center_subpath_ui.py`) erzwingen:

- kein `href="/…"` / `src="/…"` in Templates — immer `{{ base_path }}/…`
- kein `fetch()` ohne `apiUrl(...)`; `_loadInto(id, "/api/…", fn)` wendet
  `apiUrl` intern an
- Redirects nie mit hart kodiertem `/…` bauen (`RedirectResponse`
  vermeiden oder `request.scope["root_path"]` voranstellen)

## 6. Verifikation (Stand 2026-09-20)

Belegt: echter nginx 1.24 + uvicorn 0.23.2 + FastAPI 0.103.2/Starlette 0.27.0

- `root_path == "/controlcenter"`, Routing weiter auf Root-Pfaden
- `/controlcenter/downloads/` → `307 https://<domain>/controlcenter/downloads`
- `/controlcenter` → `301 /controlcenter/`
- alle 12 Seiten: kein root-absolutes `href`/`src` ohne Prefix
- Static (`common.css`/`common.js`) 200 unter dem Prefix
- POST mit passendem `Origin` → durch; falscher Origin / `http://` → 403
- Login-Callback setzt `Path=/controlcenter`
- `common.js` in Node ausgeführt: alle API-URLs tragen den Prefix

**Nicht** belegt (siehe `docs/FINDINGS_INDEX.md`): echter Browser-Durchlauf
und Telegram-Widget-Login über HTTPS auf der Produktionsdomain.

## 7. Tests

`tests/test_control_center_root_path.py` (Middleware, Redirects),
`tests/test_control_center_subpath_ui.py` (Templates/JS),
`tests/test_control_center_cookie_path.py` (Cookie-Path).
