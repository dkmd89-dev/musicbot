# Control Center — UI-Inventur (CC-UI-0)

**Datum:** 2026-09-28
**Stand:** `main` @ `3d1f063` (nach Baseline-v11-Freeze)
**Art:** reine Analyse, keine Code-Änderung
**Folgeschritt:** gemeinsame Festlegung des UI-Standards (CC-UI-Standard) anhand
der Layout-Entwürfe unter `docs/designs/control-center-ui/`, danach
seitenweises Polieren (je Seite ein PR).

Rahmen (Nutzervorgabe): **Tabler + Vanilla JS + bestehende API, keine neuen
Frameworks.** Keine neue Architektur — die vorhandenen Seiten werden auf
einen gemeinsamen Production-Stand gebracht.

---

## 1. Rahmen & Shell

| Element | Ist-Zustand |
|---|---|
| CSS/JS-Basis | Tabler **v1.5.1** lokal vendored (`control_center/static/vendor/tabler/`), kein CDN, kein Build-Schritt |
| Eigene Styles | `static/common.css` (1300 Zeilen, ~150 eigene Klassen) |
| Gemeinsames JS | `static/common.js` (348 Zeilen): `apiUrl`, `showOnly`, `showError`, `_escapeHtml`, `_loadInto`, `_retryButtonHtml`, `checkAuth`, `onNavidromeLogin`, `onLogout`, `onTelegramAuth`, `_initSidebarToggle`, `_sparklineSvg`, `_issueIcon`/`_issueSeverityTier` |
| Shell (`_base.html`) | Tabler `navbar-vertical` (helle Sidebar) + Top-Header (Benutzer, Abmelden) + `container-xl`; drei Views `loading-view` / `login-view` / `error-view` + Seiteninhalt |
| Navigation | 9 Punkte: Overview, Downloads, Library, Statistics, Navidrome, Health, Logs, Logger, Administration (unten fixiert) |
| Dark Mode | nicht vorhanden (kein `data-bs-theme`) |
| Icons | Sidebar: Inline-SVG (Tabler-Icons-Stil); Seiten-/Karten-Titel: Emojis |

## 2. Seiten-Matrix

Gezählt in Template + Seiten-JS (`grep`, Stand oben).

| Seite | Template | JS | JS-Ort | `row-list` / `empty-note` (Altstil) | Tabellen | Modals | `confirm()` | Polling |
|---|---|---|---|---|---|---|---|---|
| Overview | 244 | 517 | `pages/overview.js` | 0 / 1 | 0 | – | – | – |
| Downloads | 187 | 598 | `pages/downloads.js` | 2 / 14 | 0 | – | – | ja (Jobs) |
| Library | 720 | 463 | **inline im Template** | 3 / 11 | 2 | – | – | – |
| Artist-Detail | 2287 | 1702 | **inline im Template** | 4 / 43 | 0 | 2 | 10 | ja (Jobs) |
| Statistics | 197 | 464 | `pages/statistics.js` | 0 / 14 | 0 | – | – | – |
| Navidrome | 225 | 946 | `pages/navidrome.js` | 0 / 0 | 6 | ja (Tabler) | 1 | – |
| Health | 194 | 1003 | `pages/health.js` | 0 / 10 | 0 | – | 5 | ja (Jobs) |
| Logs | 175 | – | inline | 1 / 3 | 0 | – | – | – |
| Logger | 142 | 1077 | `pages/logger.js` | 0 / 4 | 0 | – | 1 | ja (Apply) |
| Administration | 276 | 784 | `pages/admin.js` | 2 / 7 | 4 | – | 3 | ja |
| Metadata (`/metadata`) | 49 | – | – | 0 / 0 | 0 | – | – | – |

## 3. Uneinheitlichkeiten (Befunde)

| # | Bereich | Befund | Betroffen |
|---|---|---|---|
| U1 | JS-Ort | Library und Artist-Detail tragen ihr JS inline im Template (zusammen ~2170 Zeilen) — alle anderen Seiten nutzen `static/pages/*.js` | `library.html`, `library_artist_detail.html` |
| U2 | Listen | Zwei Listen-Stile parallel: eigener `row-list`/`row-item`/`row-count` vs. Tabler `table`/`list-group` | Downloads, Library, Artist-Detail, Logs, Admin (Nutzerliste) |
| U3 | Leerzustand | Eigener `<span class="empty-note">` (~100 Stellen) statt Tabler-`empty`-Komponente; kein einheitlicher Text | alle außer Navidrome |
| U4 | Ladezustand | Text „Lädt…“ (47×), „Wird geladen…“/„Wird geladen …“ (3×), vereinzelt Tabler-`placeholder`/`spinner` | alle |
| U5 | Fehlerzustand | `_loadInto()` liefert einheitliche 401/403/404/5xx-Behandlung, aber als nackte `<span>` ohne Tabler-`alert`; Seiten mit eigenem `fetch()` (~40 Aufrufe) haben eigene Fehlertexte | alle |
| U6 | API-Zugriff | Kein gemeinsamer Helfer für schreibende Aufrufe (POST/PATCH/DELETE, JSON, Fehlerformat `{"error":{...}}`) — jede Seite baut `fetch()` selbst | Admin, Health, Logger, Downloads, Artist-Detail |
| U7 | Bestätigung | Browser-`confirm()` (20×) neben Tabler-Modals (Navidrome, Artist-Detail) | Admin, Health, Logger, Navidrome, Artist-Detail |
| U8 | Rückmeldung | Keine Toasts; Erfolg/Fehler nach Aktionen je Seite unterschiedlich (Inline-Text, `alert`, Badge) | alle schreibenden Seiten |
| U9 | Status-Farben | Mehrere Systeme: `.dot-ok/-warn/-error`, `.badge-status-*`, `.badge-CRITICAL/ERROR/WARNING/INFO/SUSPECTED`, `.status-EXCELLENT/CRITICAL`, `.attention-badge--*`, Tabler `bg-*-lt` | Health, Overview, Artist-Detail, Logger |
| U10 | KPI-Kacheln | Drei eigene Varianten: `kpi-card`/`kpi-grid` (Overview/Library), `tile`/`tiles` (Statistics), `card-compact` (Overview) | Overview, Library, Statistics |
| U11 | Seitentitel | `page-header` überall, aber Titel mal mit Emoji, mal ohne; `pretitle` und Aktionsbereich nicht einheitlich | alle |
| U12 | Detailansicht | Eigenes Drawer-System (`track-drawer`, `drawer-overlay`) statt Tabler-`offcanvas` | Artist-Detail |
| U13 | Inline-Styles | `style="…"` in JS-Render-Code (Navidrome 14×, sonst vereinzelt) | Navidrome, Downloads, Health, Statistics, Library |
| U14 | Buttons | `_retryButtonHtml()` erzeugt `<button class="small">` (kein Tabler-`btn`) | alle `_loadInto`-Aufrufer mit Retry |
| U15 | Navigation | Logs und Logger als zwei getrennte Menüpunkte für ein Thema | Logs, Logger |
| U16 | Toter Einstieg | `/metadata` existiert (Route + Stub mit Hinweis „Genre-Verwaltung liegt im Artist-Kontext“), ist aber nicht in der Navigation; keine dokumentierte Entscheidung | `routers/ui.py`, `metadata.html` |
| U17 | Responsiv | `.row-count` läuft bei 420 px in der Tag-Vorschau über (bereits in `FINDINGS_INDEX.md`, OPEN DEFER P3) | Artist-Detail |
| U18 | Theme | Kein Dark Mode | Shell |

## 4. Bereits gute, wiederverwendbare Bausteine

- `_loadInto()` — einheitliche 401/403/404/5xx-Semantik inkl. Retry (nur Darstellung angleichen, U5/U14).
- `_escapeHtml()` — konsequent genutzt (XSS-Schutz), Pflicht für jeden neuen Render-Code.
- `apiUrl()` + `cc-base`-Meta — Subpath-Betrieb hinter nginx; jeder neue Helfer muss darüber laufen.
- Navidrome-Seite — nutzt bereits Tabler-Tabs/-Modals/-Tabellen ohne Altstil (Referenz für U2/U3/U7).
- Job-Muster Start → Polling → Render (Health, Downloads, Artist-Detail) inkl. `Job.events`-Verlauf (D.12b).

## 5. Seitenbezogene Polier-Kandidaten (Nutzerliste)

| Seite | Ziel laut Nutzer | Hauptarbeit laut Inventur |
|---|---|---|
| Overview | finalisieren | U10, U11 |
| Downloads | Job-/Pipeline-UI optimieren | U2, U3, U8; Pipeline-Schritte (D.12c) sichtbar als Schrittfolge |
| Library + Artist/Track-Detail | perfektionieren | U1 (JS auslagern, reine Verschiebung mit Characterization vorher), U2, U3, U7, U12, U17 |
| Health | neue Struktur, Repair/Findings | U7, U9, U3 |
| Statistics | weitgehend fertig | U3, U10 |
| Navidrome | sauber darstellen | U13 |
| Logs/Logger | konsolidieren | U15 (nur UI, Endpunkte bleiben) |
| Administration | Nutzer, Runtime, Duplikate, Backup | U2 (Nutzerliste), U7, U8 |
| Login / Logout | fertig | nur Shell-Angleichung |

## 6. Offene Entscheidungen für den CC-UI-Standard

1. **Layout-Grundform** — Auswahl aus den Entwürfen `docs/designs/control-center-ui/`
   (Claude: A/B/C, Nutzer: eigene Entwürfe).
2. **Icons** — Emojis beibehalten, oder Tabler-Icons (Inline-SVG) in Titeln?
3. **Dark Mode** — ja/nein; wenn ja: Umschalter im Header, Wahl pro Browser (`localStorage`).
4. **Bestätigungen** — `confirm()` ersetzen durch ein gemeinsames Tabler-Modal?
5. **Rückmeldung** — Tabler-Toasts für Aktionsergebnisse?
6. **Status-Farben** — ein einziges Mapping (z. B. ok→`success`, warn→`warning`, error→`danger`, info→`info`, neutral→`secondary`) für U9.
7. **`/metadata`** — behalten, auf `/library` umleiten oder (nach Aufrufer-Prüfung) entfernen (U16).
8. **Logs/Logger** — ein Menüpunkt mit Tabs, oder zwei Seiten mit gemeinsamem Kopf (U15).

## 7. Vorgeschlagene Reihenfolge nach dem Standard

1. CC-UI-1: gemeinsame Helfer additiv in `common.js`/`common.css` (Zustände, API-Helfer, Modal, Toast) — bestehende Aufrufer unverändert.
2. Seiten: Overview → Downloads → Administration → Health → Logs/Logger → Navidrome → Statistics → Library + Artist-Detail (zuletzt, wegen U1).
3. Abschluss: manueller Browser-/Subpath-Durchlauf (deckt zugleich die FINDINGS-Zeile „Subpath-Betrieb: echter Browser-/Telegram-Login-Test“ ab).

Testbasis für jeden Seiten-PR: `tests/test_control_center_ui.py`,
`tests/test_control_center_subpath_ui.py` und die seitenbezogenen UI-Tests
(`tests/test_artist_*_ui.py` u. a.).
