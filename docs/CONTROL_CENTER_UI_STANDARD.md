# Control Center — UI-Standard

**Status:** CURRENT (gemeinsam festgelegt 2026-09-28, abgeleitet aus Entwurf D)
**Referenz-Mockup:** `docs/designs/control-center-ui/layout-d-mischung.html`
**Ausgangslage:** `docs/audits/CONTROL_CENTER_UI_INVENTORY_2026-09-28.md` (Befunde U1–U18)

Verbindlich für jede Änderung an `control_center/templates/` und
`control_center/static/`. Ziel: alle Seiten auf einen gemeinsamen
Production-Stand bringen — **keine neue Architektur**.

---

## 1. Grundregeln

1. **Tabler 1.5.1 (lokal vendored) + Vanilla JS + Jinja2.** Keine neuen
   Frameworks, keine Build-Schritte, keine zusätzlichen CDNs.
2. **Nur bestehende API.** Die UI zeigt nur, was ein vorhandener Endpunkt
   liefert. Neue Anzeigen, die neue Backend-Felder brauchen, sind eigene
   Feature-Entscheidungen, kein Polieren.
3. **Tabler-Klassen zuerst.** Eigenes CSS nur, wenn Tabler es nicht kann;
   dann in `static/common.css` mit Präfix `cc-` und Kommentar warum.
4. **Kein Inline-`style="…"`** in neuem Code. Ausnahme: dynamische Breite
   von Fortschrittsbalken (`style="width: 62%"`).
5. **Rückwärtskompatibel migrieren.** Alte `common.css`-Klassen und
   `common.js`-Funktionen bleiben, bis keine Seite sie mehr nutzt; Entfernen
   erst nach Aufrufer-Prüfung (CLAUDE.md §20).
6. **Sicherheit bleibt:** jeder freie Text durch `_escapeHtml()`, jede
   URL durch `apiUrl()` (Subpath-Betrieb), keine Secrets in der UI oder
   im Browser-Log.

## 2. Theme & Farben

| Punkt | Festlegung |
|---|---|
| Standard-Theme | **dunkel** (`<html data-bs-theme="dark">`) |
| Umschalter | Header rechts, Icon Sonne/Mond; Wahl pro Browser in `localStorage["cc-theme"]` (`"light"`/`"dark"`), Zugriff immer in `try/catch`; wird vor dem ersten Rendern im `<head>` gesetzt (kein Aufblitzen) |
| Akzentfarbe | **Türkis** `#0ca678` — einmalig als `--tblr-primary` in `common.css` gesetzt; im Code nur `btn-primary`, `bg-teal`, `bg-teal-lt`, `text-teal` |
| Sidebar | immer dunkel (`data-bs-theme="dark"` auf `<aside>`), unabhängig vom Seiten-Theme |

### Status-Farben (ersetzt U9 — einziges Mapping)

| Bedeutung | Tabler-Farbe | Badge | Punkt |
|---|---|---|---|
| ok / fertig / erfolgreich | `green` | `bg-green-lt` | `status-dot status-green` |
| läuft / aktiv | `teal` | `bg-teal-lt` | `status-dot status-dot-animated status-teal` |
| Warnung / prüfen / unvollständig | `yellow` | `bg-yellow-lt` | `status-dot status-yellow` |
| Fehler / fehlgeschlagen / kritisch | `red` | `bg-red-lt` | `status-dot status-red` |
| Metadaten-/Verarbeitungsschritt | `purple` | `bg-purple-lt` | – |
| neutral / Duplikat / abgebrochen / wartend | `secondary` | `bg-secondary-lt` | `status-dot status-secondary` |

Zuordnung vorhandener Werte:

| Quelle | Werte → Farbe |
|---|---|
| `JobStatus` | `PENDING`→secondary, `RUNNING`→teal, `SUCCEEDED`→green, `FAILED`→red, `CANCELLED`→secondary |
| Download-Verlauf `status` | `success`→green, `failed`→red, `cancelled`→secondary; Duplikat→secondary |
| Finding-Schwere | `CRITICAL`/`ERROR`→red, `WARNING`/`SUSPECTED`→yellow, `INFO`→secondary |
| Health-Score | `EXCELLENT`/`GOOD`→green, `FAIR`→yellow, `POOR`/`CRITICAL`→red |
| Repair-Ergebnis | `SUCCESS`→green, `UNRESOLVED`/`SKIPPED`→yellow, `FAILED`→red |

Badges enthalten immer **Icon + Text** — Farbe allein trägt nie die Information.

## 3. Icons (ersetzt Emojis, U11)

- **Tabler Icons (outline)** als Inline-SVG-Sprite in `_base.html`
  (`<symbol id="i-…">`), Verwendung `<svg class="icon"><use href="#i-download"/></svg>`.
- Keine Emojis in Navigation, Seiten-/Kartentiteln, Buttons oder Badges.
  Emojis, die aus **Daten** kommen (z. B. Log-Zeilen `🧩 [JOB …]`), bleiben unverändert.
- Icon-Buttons ohne Text brauchen `title` **und** `aria-label`.

Feste Zuordnung (Auszug, erweiterbar im Sprite):

| Zweck | Icon-ID | | Zweck | Icon-ID |
|---|---|---|---|---|
| Overview | `i-home` | | Abbrechen/Schließen | `i-x` |
| Downloads | `i-download` | | Erneut versuchen | `i-refresh` |
| Library | `i-books` | | Erfolg | `i-check` |
| Statistics | `i-chart` | | Fehler/Warnung | `i-alert` |
| Navidrome | `i-headphones` | | Suche | `i-search` |
| Health | `i-health` | | URL | `i-link` |
| Logs/Logger | `i-logs` | | Metadaten | `i-tag` |
| Administration | `i-settings` | | Duplikat | `i-copy` |
| Abmelden | `i-logout` | | Verlauf | `i-history` |
| Leerzustand | `i-inbox` | | Theme | `i-sun` / `i-moon` |

## 4. Shell (`_base.html`)

- `navbar-vertical` links, dunkel, Marke „MusicBot“ mit `i-music`-Avatar.
- Navigationspunkte mit Icon + Titel. **Zähler** (`badge badge-sm position-static ms-auto`)
  sind vorerst **nicht** Teil der Shell (Entscheidung CC-UI-1, 2026-09-28): sie
  bräuchten auf jeder Seite zusätzliche API-Abfragen. Eine Seite darf sie später
  nur ergänzen, wenn der Wert bereits aus einer vorhandenen API kommt.
- Administration unten abgesetzt (`mt-3`).
- Header (auf dem Handy einzeilig: Menü, Theme, Abmelden; Titel und Benutzer erst ab `md`/`sm`): links Kontext „Control Center“, rechts Theme-Umschalter,
  Benutzer (Avatar + Name + Rollen-Badge `bg-purple-lt`), Abmelden
  (`btn-ghost-secondary` + `i-logout`).
- Views `loading-view` / `login-view` / `error-view` bleiben (Verhalten unverändert).

## 5. Seitenaufbau

```html
<div class="page-header d-print-none">
  <div class="container-xl"><div class="row g-2 align-items-center">
    <div class="col-12 col-md">
      <div class="page-pretitle">Bereich</div>
      <h2 class="page-title"><svg class="icon me-2 text-teal"><use href="#i-…"/></svg>Titel</h2>
    </div>
    <div class="col-12 col-md-auto ms-md-auto"><div class="btn-list"><!-- Seitenaktionen --></div></div>
  </div></div>
</div>
<div class="page-body"><div class="container-xl"> … </div></div>
```

- `page-pretitle` = Gruppe (Musik, System, Verwaltung); Titel = Name im Menü.
- Abschnittsüberschriften außerhalb von Karten:
  `<h3 class="text-uppercase text-secondary fs-5 mb-2">`.
- Raster: `row row-cards`; Karten-Gruppen stapeln auf dem Handy.

## 6. Komponenten

| Zweck | Standard | Ersetzt |
|---|---|---|
| Kennzahlen | `card card-sm` mit `subheader` + Wert, optional `avatar` mit Icon | `kpi-card`, `tile`, `card-compact` (U10) |
| Listen / Verläufe / Übersichten | `table card-table table-vcenter` in `table-responsive`; Titel + Unterzeile (`text-secondary small`) in einer Zelle | `row-list`/`row-item`/`row-count` (U2) |
| Kurze Listen ohne Spalten | `list-group list-group-flush` | `row-list` |
| Schlüssel/Wert-Details | `datagrid` | eigene Grids |
| Mehrere Ansichten einer Karte | `nav nav-tabs card-header-tabs` | – |
| Detailansicht / Formular am Rand | `offcanvas offcanvas-end` | `track-drawer`/`drawer-overlay` (U12) |
| Filter/Suche über Tabellen | `input-icon` + `form-select form-select-sm` im `card-actions`, clientseitig | – |
| Primäraktion je Karte/Seite | genau **ein** `btn btn-primary` | – |
| Zeilenaktionen | `btn btn-sm btn-icon btn-ghost-*` mit Icon | Text-Buttons `small` (U14) |
| Destruktive Aktionen | `btn-ghost-danger` / `btn-danger` + Bestätigungsdialog | – |

Tabellen auf dem Handy: weniger wichtige Spalten mit `d-none d-md-table-cell` ausblenden statt horizontal zu scrollen.

## 7. Zustände (U3/U4/U5)

Jeder Datenbereich hat genau diese drei Zustände:

| Zustand | Markup |
|---|---|
| Laden | `placeholder-glow` mit 2–3 `placeholder`-Zeilen; kurzer Inline-Fall: `spinner-border spinner-border-sm` + „Lädt …“ |
| Leer | `<div class="empty">` mit `empty-icon` (`i-inbox` o. passend), `empty-title`, `empty-subtitle`, optional `empty-action` |
| Fehler | Karte mit `card-status-start bg-danger`, Titel mit `i-alert`, Detail (`HTTP 503` / Meldung aus `{"error":{"message"}}`), Button „Erneut versuchen“ (`i-refresh`) — nur bei 5xx/Netzwerk |
| Keine Berechtigung (403) | `alert alert-warning` „Keine Berechtigung (Rolle reicht nicht).“, kein Retry |
| Nicht angemeldet (401) | wie heute: Wechsel auf `login-view` |

Texte einheitlich: „Lädt …“, „Noch keine …“, „… nicht erreichbar“, „Erneut versuchen“.
Die Status-Semantik von `_loadInto()` (401/403/404/5xx) bleibt; nur die Darstellung wird angeglichen.

## 8. Rückmeldung & Bestätigung (U7/U8)

- **Bestätigung:** kein `confirm()`/`prompt()` in neuem Code (Eingaben über `ccPrompt`). Gemeinsamer Tabler-Dialog
  (`modal modal-blur`, `modal-sm`, `modal-status bg-danger` bei destruktiv):
  Frage als Titel, Folge in einem Satz, Buttons „Zurück“ + Aktion.
- **Rückmeldung nach Aktionen:** Tabler-Toast unten rechts
  (`toast-container position-fixed bottom-0 end-0 p-3`), Icon + Kurztitel +
  optional ein Satz; Erfolg `i-check` teal, Fehler `i-alert` red; Fehler-Toasts
  bleiben stehen, Erfolg verschwindet nach ~4 s.
- Fehler, die einen **Bereich** betreffen, zeigt der Bereich selbst (Abschnitt 7), nicht ein Toast.

## 9. Jobs & Pipeline

Gilt für alle Job-Anzeigen (Downloads, Health/Repair, Library-Aktionen, Logger-Apply).

- **Aktive Jobs als Karte:** Titel + Unterzeile (Typ · Job-ID kurz · Startzeit),
  Status-Badge rechts (Farbe nach Abschnitt 2), Fortschrittsbalken
  `progress progress-sm` + `progress-bar bg-teal`, darüber `message` links und Prozent rechts.
- **Pipeline-Schritte** nur, wenn die Schritte aus vorhandenen Daten
  ableitbar sind (Download: D.12c-Schritte in `message`/`events`):
  `steps steps-counter steps-teal d-none d-md-flex`; auf dem Handy stattdessen
  „Schritt n von m · Name“.
- **Verlauf eines Jobs** (`Job.events`) im Offcanvas als `timeline timeline-simple`.
- Karten-Fuß: links „Verlauf“ (`i-history`), rechts „Abbrechen“ (`btn-ghost-danger`, mit Bestätigung) — nur solange der Job läuft.
- Abgeschlossene Jobs wandern in die Verlaufstabelle der Seite.
- Polling-Intervall und -Logik der Seiten bleiben unverändert.

## 10. Logs im Terminal-Stil

Nur für Logs/Logger: Karte mit Kopf (Dateiname, `i-logs`, optional
Live-Status), Körper `cc-terminal` (Monospace, dunkler Hintergrund auch im
hellen Theme), Zeit grau, Level farbig (INFO teal, OK/SUCCESS green,
WARNING yellow, ERROR/CRITICAL red). Inhalt weiterhin redigiert
(`services/logs/reader.py::redact_secrets()`), frei escaped.

## 11. Responsiv & Barrierefreiheit

- Muss bei **420 px** ohne horizontales Seiten-Scrollen funktionieren (nur Tabellen dürfen intern scrollen).
- Formulare: Eingabe + Button stapeln auf dem Handy (`col-12 col-sm-auto`).
- Jede Eingabe hat `label` oder `aria-label`; Toasts `role="status"`.
- Fokus bleibt in Dialogen/Offcanvas (Tabler/Bootstrap-Standard).

## 12. JavaScript-Konventionen

**Umgesetzt in CC-UI-1 (2026-09-28):** Sprite `templates/_icons.html`, Theme
(dunkel + Umschalter + Türkis), Shell in `_base.html`, Helfer unten in
`static/common.js`, `.cc-terminal` in `static/common.css`. Tests:
`tests/test_control_center_ui_shell.py`.

- Seiten-JS **nur** in `static/pages/<seite>.js` — kein Inline-`<script>`-Block mit Logik im Template (U1).
- Gemeinsame Helfer in `static/common.js`. **CC-UI-1** ergänzt additiv
  (Namen verbindlich, Umsetzung folgt):

  | Helfer | Zweck |
  |---|---|
  | `ccState.loading(el)`, `ccState.empty(el, title, subtitle, actionHtml?)`, `ccState.error(el, message, retryFn?)` | Zustände nach Abschnitt 7 |
  | `ccApi(method, path, body?)` | `fetch` über `apiUrl()`, `credentials: "same-origin"`, JSON, bei schreibenden Requests `X-Requested-With: XMLHttpRequest`, wirft bei Fehler mit Meldung aus `{"error":{"message"}}`; 401 → `login-view` |
  | `ccConfirm({title, text, confirmLabel, danger}) → Promise<boolean>` | Bestätigungsdialog nach Abschnitt 8 |
  | `ccPrompt({title, text, label, required, confirmLabel, danger}) → Promise<string\|null>` | Bestätigung mit Eingabefeld statt `prompt()` + `confirm()` (ergänzt CC-UI Health); `null` bei Abbruch |
  | `ccToast(kind, title, text?)` | Rückmeldung nach Abschnitt 8 |
  | `ccStatusBadge(kind, label)` | Badge nach Abschnitt 2 (Icon + Text, escaped) |
  | `ccIcon(id, extraClass?)` | SVG-`<use>` für den Sprite |
  | `ccStatusKind(value)` | vorhandener API-Wert → Status-Art nach Abschnitt 2 |
  | `ccState.denied(el)` | Zustand „Keine Berechtigung“ |
  | `ccSetTheme("dark"\|"light")` | Theme setzen + speichern |

  `_loadInto()`, `_escapeHtml()`, `apiUrl()`, `showOnly()`, `showError()` bleiben unverändert; `_loadInto()` darf intern auf `ccState` umgestellt werden, ohne die Signatur zu ändern.
- Keine globalen `onclick="…"` für neuen Code; Event-Listener in der Seiten-JS.

## 13. Zuordnung der Inventur-Befunde

| Befund | Regel |
|---|---|
| U1 Inline-JS | §12 |
| U2 Listen | §6 |
| U3/U4/U5 Zustände | §7 |
| U6 API-Zugriff | §12 `ccApi` |
| U7 `confirm()` | §8 |
| U8 Rückmeldung | §8 |
| U9 Status-Farben | §2 |
| U10 KPI-Kacheln | §6 |
| U11 Seitentitel/Emojis | §3, §5 |
| U12 Drawer | §6 Offcanvas |
| U13 Inline-Styles | §1 Regel 4 |
| U14 Buttons | §6 |
| U15 Logs/Logger | entschieden 2026-09-28: zwei Seiten, gemeinsamer Kopf `_logs_header.html` mit Reitern, ein Sidebar-Eintrag „Logs“ (§10 gilt für beide) |
| U16 `/metadata` | offen → Entscheidung im Library-Schritt |
| U17 `.row-count` | §6 Tabellen + §11 |
| U18 Dark Mode | §2 |

## 14. Definition of Done je Seiten-PR

```text
[ ] Seite nutzt Shell, Seitenkopf, Komponenten, Zustände, Farben, Icons nach diesem Standard
[ ] kein neues Inline-JS / Inline-Style / confirm() / Emoji im UI-Rahmen
[ ] nur bestehende Endpunkte, API-Verhalten unverändert
[ ] hell + dunkel geprüft, 1400 px + 420 px ohne horizontales Seiten-Scrollen
[ ] Subpath-Betrieb: alle URLs über apiUrl() / base_path
[ ] Tests: tests/test_control_center_ui.py, tests/test_control_center_subpath_ui.py
    + seitenbezogene UI-Tests grün (angepasst nur, wo Markup-Erwartungen sich bewusst ändern)
[ ] nicht mehr genutzte Alt-Klassen notiert (Entfernen erst, wenn keine Seite sie nutzt)
[ ] FINDINGS_INDEX-Zeile „Control Center: uneinheitliche UI“ fortgeschrieben
```

## 15. Reihenfolge

1. **CC-UI-1:** Sprite, Theme (dunkel + Umschalter + Türkis), Shell in `_base.html`, Helfer aus §12 in `common.js`/`common.css` — additiv.
2. Seiten: ~~Overview~~ (erledigt 2026-09-28) → ~~Downloads~~ (erledigt 2026-09-28) → ~~Administration~~ (erledigt 2026-09-28) → ~~Health~~ (erledigt 2026-09-28) → ~~Logs/Logger~~ (erledigt 2026-09-28) → Statistics → Library + Artist-Detail → Navidrome (zuletzt, Nutzerentscheidung 2026-09-28).

   **Navidrome = eigener Musik-Bereich** (Nutzerentscheidung 2026-09-28): Die Seite wird der
   Musik-Bereich des Nutzers mit eigenem Layout in Anlehnung an Symfonium (Cover-Raster, runde
   Artist-Bilder, Album-Ansichten, Player-Leiste) und folgt dem Standard nur in Shell, Theme,
   Icons, Zuständen und Helfern. Die bereits begonnene Artist-Darstellung (Cover, rund) ist
   Ausgangspunkt, nicht Neubau. **Abspielen im Browser ist eine neue Funktion**, keine
   UI-Umstellung: Heute gibt es keinen Stream-Endpunkt, nötig wäre z. B. ein
   auth-geschützter Stream-/Cover-Proxy auf die Subsonic-API von Navidrome
   (`services/clients/navidrome_api.py`). Dafür gibt es eine eigene Planung → Freigabe →
   Umsetzung, Credentials dürfen nie in URLs, Logs oder im Browser landen (CLAUDE.md §12).
3. Abschluss: manueller Browser-/Subpath-Durchlauf, Alt-Klassen aufräumen.
