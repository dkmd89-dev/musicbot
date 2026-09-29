# Mapping-UI im Control Center — Plan (Phase 5)

**Stand:** 2026-09-30 · **Status:** PLAN (Freigabe erteilt, kein Code in diesem Dokument)
**Vorgänger:** `docs/audits/MAPPING_ADMIN_CHARACTERIZATION_AND_PROPOSAL_2026-09-29.md`
**Bezug:** `docs/CONTROL_CENTER_UI_STANDARD.md`

---

## Ziel

Eine Control-Center-Seite, auf der die fünf in M1–M5 implementierten Mapping-Typen
verwaltet werden können. Der Nutzer bleibt auf einer Seite; Bearbeiten öffnet einen
Offcanvas.


/admin/mappings
│
├── Seite mit fünf Karten (ein Typ pro Karte)
│     ├── channel-genre
│     ├── genre-aliases
│     ├── genre-overrides
│     ├── genre-filters
│     └── special-channels
│
└── Offcanvas-Editor pro Typ

---

## Interaktionsfluss (identisch für alle fünf Typen)

Karte "Bearbeiten" klicken
→ Offcanvas öffnet
→ GET Liste (JSON) → in Editor-State
→ Nutzer ändert lokal (Draft)
→ "Vorschau" → POST .../preview
→ Diff-Bereich (analog L4 renderMetadataEditPreview: + / − / ~)
→ comment_warning als Warn-Banner, falls vorhanden
→ "Übernehmen"-Button aktiv
→ "Übernehmen" → ccConfirm (Alt → Neu)
→ PUT mit Etag
→ 200: Toast "Gespeichert — wirkt für neue Downloads nach Bot-Neustart"
Liste neu laden
→ 409: Modal "Andere Änderung erkannt" → Nutzer wählt:
neu laden + verwerfen | abbrechen
→ 422: Feldmarkierung aus Antwort
→ 503: Fehlerzustand im Editor

**Draft-Modus:** Änderungen werden lokal gesammelt. Nur ein PUT pro "Übernehmen".

---

## Fünf Editor-Formulare

| Typ | Formular |
|---|---|
| channel-genre | Tabelle aller Einträge + Formular: `key`, `primary`, `secondary` (Chip-Liste), `description` |
| genre-alias | Liste (key → canonical) + Formular: `alias`, `canonical` |
| genre-override | Liste (key → override) + Formular: `key`, `override`; Hinweis "case-sensitiv, Reihenfolge irrelevant" |
| genre-filter | Eine große Chip-Liste; Add/Remove; ein "Übernehmen" |
| special-channels | Kategorien als Karten mit Kanal-Listen; Kategorie + Kanal Add/Remove; Prioritäts-Reihenfolge sichtbar (Pfeile ↑/↓) |

---

## Nutzung des bestehenden UI-Standards

- **Shell, Seitenkopf, Karten** (`card card-sm` + `card-actions`) nach §5/§6
- **Listen:** kurze Listen als `list-group list-group-flush`, lange als `table card-table`
- **Offcanvas** für den Editor wie L4 (`offcanvas offcanvas-end`)
- **Diff:** `md-diff` mit `+ / − / ~` (wie L4)
- **Lade-/Leer-/Fehlerzustand** pro Karte via `ccState`
- **Requests** über `ccApi`
- **Bestätigung** über `ccConfirm` vor jedem PUT
- **Rückmeldung** über `ccToast`
- **420 px** responsive, Grid stapelt
- **Kein Inline-JS** — alles in `static/pages/mappings.js`
- **Icons** aus dem Sprite (`i-tag`, `i-edit`, `i-history`, `i-refresh`)

---

## Ehrliche Semantik (unverhandelbar)

- `bot_reload_required` aus der API wird im Save-Toast **wörtlich** übernommen.
- `comment_warning` erscheint als Warn-Banner vor dem Speichern.
- Bei `special-channels`: Hinweis "Runtime merged weiterhin mit
  `Config.SPECIAL_CHANNELS` — hier wird nur die YAML-Quelle verwaltet."
- Kein Fake-Success, kein Fake-Reload.

---

## Aufteilung in Schritte

| Schritt | Inhalt | Sichtbarer Nutzen |
|---|---|---|
| **5.1** | Seite + Sidebar-Eintrag + 5 Karten mit Anzahl (read-only) | Seite existiert, Bestand sichtbar |
| **5.2** | Offcanvas-Editor + Draft-Modus für M1/M2/M3 (key-basiert) | erste Bearbeitung möglich |
| **5.3** | Editor für M4 (Liste) + M5 (Kategorien) | alle fünf Typen bearbeitbar |
| **5.4** | Vollständige Tests (Node-Harness) + UI-Standard-DoD + Browser-Durchlauf | produktionsreif |

Nach 5.1 ist die Seite sofort nutzbar (read-only). Nach 5.2/5.3 kommen die
Schreibfunktionen. Nach 5.4 ist Phase 5 abgeschlossen.

---

## Entscheidungen (F1–F4, 2026-09-30)

| # | Frage | Entscheidung |
|---|---|---|
| F1 | Draft-Modus oder sofort-PUT? | **Draft** — Änderungen gesammelt, ein PUT pro "Übernehmen" |
| F2 | Karten-Anzahl live oder statisch? | **Live** — pro Karte ein GET auf die Liste |
| F3 | special-channels: Drag&Drop? | **Nein** — Pfeile ↑/↓ für Kategorie-Reihenfolge |
| F4 | Tests: Node-Harness oder HTTP? | **Node-Harness** wie L4 (HTTP-API durch M1–M5-Tests abgedeckt) |

---

## Was nicht in Phase 5

- Kein neuer Service, kein neuer Endpunkt.
- Keine Änderung an M1–M5-Verträgen.
- Keine Runtime-Änderung an GenreMapper/GenreProcessor/filenamefixer.
- Kein Drag&Drop, keine Live-Editierung (weiterhin "Vorschau → Übernehmen").
- Keine Hierarchie-/Regex-Validierung (M6/M7 sind eigene Backend-Schritte).
