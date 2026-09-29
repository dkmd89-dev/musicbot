# Mapping-UI im Control Center — Plan v2 (Phase 5)

**Stand:** 2026-09-30 · **Status:** PLAN (Freigabe für Plan erteilt, kein Code)
**Ersetzt:** Plan v1 (gleicher Dateiname, gelöscht). Grund: v1 passte nicht zum
tatsächlichen API-Vertrag (siehe „Korrekturen ggü. v1").
**Vorgänger:** `docs/audits/MAPPING_ADMIN_CHARACTERIZATION_AND_PROPOSAL_2026-09-29.md`
**Bezug:** `docs/CONTROL_CENTER_UI_STANDARD.md`, Skill `musicbot-control-center-ui`

---

## 1. Ist-Analyse (am Code belegt)

### API (M1–M5, fertig, kein Backend-Schritt nötig)

`control_center/routers/mapping_admin.py`, Prefix `/api/v1/admin/mappings`,
Router-weit `require_min_access_level(ADMIN)`; `POST`/`PUT` zusätzlich `verify_same_origin`.

| mapping_id | Datei | Größe (Ist) | Modell | Liste | Einzeleintrag | Preview / PUT |
|---|---|---|---|---|---|---|
| `channel-genre` | channel_genre.yaml | ~150 Einträge | **pro Key** | ohne etag | `GET /entry?key=` → etag | `?key=` + Body + etag |
| `genre-aliases` | genre_aliases.yaml | ~390 Einträge | pro Key | ohne etag | ja | wie oben |
| `genre-overrides` | genre_overrides.yaml | ~170 Einträge | pro Key (exact-first) | ohne etag | ja | wie oben |
| `genre-filters` | genre_filters.yaml | ~650 Werte | **ganze Liste** | mit etag | 404 (nicht vorgesehen) | Body `values` + etag |
| `special-channels` | special_channel.yaml | wenige Kategorien | **ganze Liste**, Reihenfolge = Priorität | mit etag | 404 | Body `categories` + etag |

Weitere Fakten:
- Etag = Hash der **gesamten** Mapping-Struktur (`_channel_genre_etag(mapping)` …). Jede
  Fremdänderung, auch an anderem Key, ergibt beim Speichern 409.
- Antworten liefern `bot_reload_required`, `message`, `warnings`, teils `comment_warning`
  (YAML-Rewrite verliert Kommentare).
- **Kein DELETE** für Einträge in M1–M3 (im Router und `services/mapping_admin.py`
  nicht vorhanden). In M4/M5 entsteht Löschen durch Ersetzen der Liste.

### UI (Standard + Code)

- Shell/Komponenten: `docs/CONTROL_CENTER_UI_STANDARD.md` §4–§8, §12; Helfer
  `ccApi`, `ccState`, `ccConfirm`, `ccToast`, `ccIcon`, `ccStatusBadge` in `static/common.js`.
- Seiten-JS je Seite in `static/pages/<seite>.js`; Offcanvas-Editor-Vorbild: L4 in
  `library_artist.js` (`#md-editor`, Vorschau, Diff).
- Sidebar (`_base.html`): Einträge unconditional sichtbar; Zugriffsschutz liegt
  ausschließlich in der API (403 → `ccState.denied`). `/admin` folgt demselben Muster.
- Tests: `tests/test_control_center_ui_shell.py` führt `ALL_PAGES`; neue Seite muss dort rein.

### Nicht über die Admin-API erreichbar (kein UI, keine Attrappen)

`artist_genre.yaml` (~1285 Zeilen; Artist-Detail hat eigenen Genre-Mapping-Pfad),
`artist_overrides.json`, `known_artists.yaml`, `case_preserve.yaml`,
`genre_hierarchy.yaml`, `genre_rules.yaml`, `auto_learned_*.json`.
Das sind eigene Backend-Schritte (M6+), nicht Teil von Phase 5.

---

## 2. Korrekturen ggü. Plan v1 (besser durch Gegenprüfung)

| # | v1 | Problem | v2 |
|---|---|---|---|
| K1 | Fünf Karten, je ein Typ | Skill/Standard: Listen = Tabelle; 150–650 Einträge passen nicht in Karten | **Eine Seite, Reiter je Typ**, je Reiter Suche + Tabelle + Paginierung |
| K2 | Draft-Modus + ein PUT für alle | M1–M3 sind **pro Key** mit Einzel-Preview/PUT; Draft dort gar nicht abbildbar | Draft nur für M4/M5 (ganze Liste); M1–M3 **Einzeleintrag-Editor** |
| K3 | Fünf Live-GETs beim Öffnen | unnötige Last, ein Fehler blockiert Seite | **Lazy**: nur aktiver Reiter lädt; Anzahl am Reiter erst nach Laden |
| K4 | Löschen implizit vorgesehen | Backend kann in M1–M3 nicht löschen | Kein Löschen-Button in M1–M3; als Lücke dokumentiert (Abschnitt 5) |
| K5 | Route `/admin/mappings` | Sie wollten eigenen Sidebar-Eintrag | Route **`/mappings`**, eigener Eintrag, Gruppe „Verwaltung" |
| K6 | 409 → „neu laden + verwerfen" | etag ist file-weit; Verwerfen ist für den Nutzer oft zu hart | 409-Dialog: „Neu laden" (Entwurf bleibt sichtbar als Vergleich) oder „Abbrechen" |

---

## 3. Zielbild

```
Sidebar: [Mapping]  →  /mappings   (page-pretitle "Verwaltung", i-tag)

Reiter:  Channel-Genre | Aliases | Overrides | Filter | Spezialkanäle
         └ Tabelle (Suche, 50/Seite)  ── Zeile bearbeiten / "Neu" ──► Offcanvas
Fußbereich (Text, keine Controls): "Weitere Mapping-Dateien sind noch nicht verwaltbar" + Liste
```

### Editor je Typ

| Typ | Tabelle | Editor (Offcanvas) | Flow |
|---|---|---|---|
| channel-genre | key · primary · secondary (Badges) · description | primary, secondary (Chip-Eingabe), description | `GET entry` → Formular → **Vorschau** (`POST preview?key`) → Diff (primary geändert, +/− secondary) → `ccConfirm` → `PUT?key` |
| genre-aliases | alias → canonical | canonical; Hinweis `comment_warning` | wie oben |
| genre-overrides | key → override | override; Hinweis „exakt (case-sensitiv), zuerst geprüft" | wie oben |
| genre-filters | ein Wert je Zeile, Suche | Draft: Wert hinzufügen/entfernen | Draft → **Vorschau** (+/−) → `ccConfirm` → `PUT values+etag` |
| special-channels | Kategorie · Kanalanzahl · Rang | Draft: Kategorie/Kanal add/remove, ↑/↓ Reihenfolge | Draft → Vorschau → `ccConfirm` → `PUT categories+etag` |

Neuer Eintrag in M1–M3: „Neu"-Button → Offcanvas mit Key-Feld; `GET entry` liefert
`exists:false` → Preview zeigt `change=create`.

### Ehrliche Semantik (unverhandelbar)

- Erfolg erst nach 200; `written=false/unchanged` zeigt „Bereits identisch — nichts geschrieben."
- `bot_reload_required` und `message` aus der API werden **wörtlich** angezeigt
  (Wirkung erst nach Bot-Neustart).
- `warnings`/`comment_warning` als `alert alert-warning` **vor** dem Bestätigen.
- Special-Channels-Hinweis: „Runtime merged weiterhin mit `Config.SPECIAL_CHANNELS` —
  hier wird nur die YAML-Quelle verwaltet."
- 401 → Login-View, 403 → `ccState.denied`, 5xx/503 → `ccState.error` mit „Erneut versuchen",
  422 → Meldung aus `{"error":{"message"}}` im Editor.
- Kein Roh-YAML, kein Löschen wo Backend es nicht kann, keine Attrappen.

### UI-Standard-Umsetzung

Shell + Seitenkopf §5, `nav nav-tabs card-header-tabs` §6, `table card-table table-vcenter`
in `table-responsive` (Spalten auf 420 px per `d-none d-md-table-cell` reduziert),
`input-icon`-Suche, Offcanvas `offcanvas-end`, Zustände §7, `ccConfirm`/`ccToast` §8,
alle URLs über `apiUrl()`, Seiten-JS **nur** `static/pages/mapping.js` (IIFE,
`data-action`-Delegation, kein Inline-JS/-Style), Icons aus Sprite (`i-tag`, `i-edit`,
`i-plus`, `i-refresh`, ggf. Ergänzung im Sprite nur wenn Icon fehlt).

---

## 4. Schritte (jeder einzeln, Freigabe nach jedem Schritt)

| Schritt | Inhalt | Nutzen |
|---|---|---|
| **5.1** | Route `/mappings` (`ui.py`), `mapping.html`, Sidebar-Eintrag, `mapping.js`: Reiter, Lazy-Laden, Suche, Paginierung, alle Zustände — **read-only** für alle fünf Typen; `ALL_PAGES` + Shell-/Subpath-Tests | Bestand sichtbar |
| **5.2** | Offcanvas-Einzeleintrag-Editor M1–M3 (Preview, Diff, Confirm, PUT, 409/422) | erste Bearbeitung |
| **5.3** | Draft-Editoren M4 (Filter) und M5 (Kategorien, ↑/↓) | alle fünf bearbeitbar |
| **5.4** | Node-Harness-Tests, UI-Standard §14-DoD, Browser-Durchlauf (hell/dunkel, 1400/420 px), Doku (`CONTROL_CENTER_UI_STANDARD.md` §15, `FINDINGS_INDEX.md`, `INDEX.md`) | abgeschlossen |

Tests je Schritt nach CLAUDE.md §8.A: gezielt → `tests/test_control_center_ui*.py`,
Mapping-API-Tests als Regression → thematisch. **Volle Suite nur durch den Nutzer.**

---

## 5. Offene Lücken (bewusst außerhalb Phase 5, eigene Entscheidung)

1. **DELETE für M1–M3:** braucht einen Backend-Vertrag (Service + Endpoint + Tests).
   Ohne ihn kein Löschen in diesen Reitern (M4/M5 können durch Listenersetzung entfernen).
2. **Weitere Manual-Dateien** (Artist-Genre, Hierarchy, Rules, Known Artists, Case-Preserve,
   Artist-Overrides): je ein Backend-Schritt, danach ein weiterer Reiter.
3. **Auto-Learned (read-only):** braucht lesende Endpunkte; erst danach eine Sektion.
4. **Server-seitige Paginierung:** aktuell nicht nötig (max. ~650 Werte, clientseitig).

## 6. Nicht in Phase 5

Keine Änderung an M1–M5-Verträgen, keine neuen Endpunkte, keine Runtime-Änderung an
GenreMapper/GenreProcessor/filenamefixer, kein Drag&Drop, kein Live-Editieren, kein Roh-YAML.
