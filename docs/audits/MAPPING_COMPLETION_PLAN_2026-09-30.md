# Mapping-Administration — Abschlussplan bis zur Freigabe

**Stand:** 2026-09-30 · **Status:** PLAN (zur Freigabe, kein Code in diesem Dokument)
**Ersetzt:** `MAPPING_UI_PLAN_2026-09-30.md` (bewusst gelöscht; dessen Entscheidungen F1–F4
und der Interaktionsfluss sind unten übernommen)
**Vorgänger:** `MAPPING_ADMIN_CHARACTERIZATION_AND_PROPOSAL_2026-09-29.md`
**Bezug:** `docs/CONTROL_CENTER_UI_STANDARD.md` (Designautorität Nr. 1), Skill `musicbot-control-center-ui`,
`docs/designs/control-center-ui/`, `docs/GENRE_SYSTEM.md` §3.1, `docs/FINDINGS_INDEX.md` (Zeile „Mapping-Dateien“)

---

## 1. Ausgangslage (verifiziert 2026-09-30)

| Bereich | Stand |
|---|---|
| Backend/API M1–M5 | fertig: `channel-genre`, `genre-aliases`, `genre-overrides`, `genre-filters`, `special-channels` (`services/mapping_admin.py`, `/api/v1/admin/mappings/{mapping_id}`); 137 Tests grün |
| Runtime-Parität | geprüft gegen echte Dateien; ein Fund (Kategorie-Priorität zufällig) mit PR #379 behoben und als CLOSED geführt |
| Kommentar-Regeln | nach `docs/GENRE_SYSTEM.md` §3.1 übernommen; `comment_warning` wird von M2–M5 geliefert und getestet |
| **UI** | **fehlt vollständig** (keine Seite, kein Sidebar-Eintrag, kein `static/pages/mappings.js`) |
| Übrige Mapping-Dateien | nicht abgedeckt (siehe §6) |

**Ziel dieses Plans:** Die fünf vorhandenen Mapping-Typen sind im Control Center bedienbar,
dokumentiert und vom Nutzer abgenommen. Danach gilt die Mapping-Funktion für den vereinbarten
Umfang (§6) als abgeschlossen.

---

## 2. Entscheidungen (übernommen und neu)

| # | Frage | Entscheidung |
|---|---|---|
| F1 | Draft oder sofort-PUT? | **Draft** — lokal sammeln, ein PUT pro „Übernehmen“ |
| F2 | Karten-Anzahl live? | **Live** — je Karte ein GET auf die Liste |
| F3 | Reihenfolge special-channels | **Pfeile ↑/↓**, kein Drag&Drop |
| F4 | UI-Tests | **Node-Harness** wie Library L4; HTTP-API ist durch M1–M5-Tests abgedeckt |
| F5 (neu, Vorschlag) | Navigation | **Eigener Sidebar-Eintrag „Mappings“** in der Gruppe **Maintenance** (nach Health; die Sidebar kennt Music / Maintenance / System, „Administration“ steht abgesetzt unten), Icon `i-tag`, Route `GET /admin/mappings`, `page_id = 'mappings'`. Begründung: Administration hat bereits viele Karten; Mappings sind Fachlogik-Pflege, keine Systemverwaltung |
| F6 (neu, Vorschlag) | Backup vor Schreiben | **Nein in Phase 5.** Vor dem ersten produktiven Speichern kopiert der Nutzer die fünf Dateien manuell (siehe §5, Gate G3). Ein automatisches `.bak` wäre eine Backend-Erweiterung und ist optional in §6 geführt |

F5/F6 sind Vorschläge und brauchen deine Bestätigung.

---

## 3. Interaktionsfluss (identisch für alle fünf Typen)

```text
Karte „Bearbeiten“ → Offcanvas (offcanvas-end)
→ GET Liste → Editor-State (Draft)
→ Nutzer ändert lokal
→ „Vorschau“ → POST …/preview → Diff (+ / − / ~, wie L4 renderMetadataEditPreview)
→ comment_warning als Warn-Banner, warnings[] als Hinweisliste
→ „Übernehmen“ erst nach erfolgreicher Vorschau aktiv
→ ccConfirm (Alt → Neu, Zusammenfassung added/removed)
→ PUT mit etag
   200: ccToast, Text wörtlich aus `message`; bot_reload_required sichtbar; Liste neu laden
   409: Modal „Andere Änderung erkannt“ → neu laden + Draft verwerfen | abbrechen
   422: Meldung aus {"error":{"message"}} am Editor, Draft bleibt
   503: Fehlerzustand im Editor (ccState.error), kein Retry-Loop
   403: ccState.denied
```

Vorschau muss nach **jeder** Draft-Änderung neu laufen; ein veralteter Preview-Stand darf nie
„Übernehmen“ freischalten (Sequenz-Guard wie `_isCurrentPreview` in `library_artist.js`).

### Editor je Typ

| Typ | Formular | Besonderheit |
|---|---|---|
| channel-genre | Tabelle + Formular `key`, `primary`, `secondary` (Chips, max. 20), `description` | key-basiert: `POST/PUT ?key=` pro Eintrag |
| genre-aliases | Liste + `alias` → `canonical` | key-basiert, Key case-insensitiv |
| genre-overrides | Liste + `key` → `override` | Hinweis „case-sensitiv, Reihenfolge irrelevant“; `Hip-Hop`/`hip-hop` getrennt anzeigen |
| genre-filters | eine Chip-Liste, Add/Remove | Body `{values}`; Hinweis „wird kleingeschrieben“; Datei-Duplikate → `cleanup` sichtbar erklären |
| special-channels | Kategorien als Karten mit Kanal-Listen, ↑/↓ für Kategorie-Reihenfolge | Hinweis: Reihenfolge = Priorität; Runtime merged weiterhin mit `Config.SPECIAL_CHANNELS` |

**Kein Löschen bei M1–M3:** Die API kennt für key-basierte Typen nur Anlegen/Ändern (`PUT ?key=`), keinen DELETE-Endpunkt. Die UI zeigt deshalb **keine** Löschen-Schaltfläche (Skill: keine Steuerelemente ohne Backend-Vertrag). Entfernen ist nur bei M4 (Wert aus Liste) und M5 (Kanal/Kategorie aus Struktur) möglich, weil dort die ganze Liste ersetzt wird. Fehlender Löschpfad wird als eigener P3-Punkt in `FINDINGS_INDEX` geführt (Backend-Erweiterung, nicht Phase 5).

**Key-basierte Typen (M1–M3):** Draft-Modus heißt hier „mehrere Einträge lokal sammeln“, aber
die API speichert je Eintrag (`PUT ?key=`). Ein „Übernehmen“ löst deshalb **mehrere PUTs
nacheinander** aus, jeder mit dem Etag des vorherigen Ergebnisses (`new_etag`). Bricht einer
ab (409/422), stoppt die Kette; bereits gespeicherte Einträge werden angezeigt, der Rest bleibt
im Draft. → Klärungspunkt K1 (siehe §7), vor 5.2 zu entscheiden.

---

## 4. Umsetzungsschritte (jeder Schritt = eigener PR, einzeln gemergt)

| Schritt | Inhalt | Nutzen | Gezielte Tests |
|---|---|---|---|
| **5.0** ✅ 2026-09-30 | Vorbereitung: Sprite um `i-arrow-up` und `i-arrow-down` ergänzen (`i-tag`, `i-edit`, `i-plus`, `i-minus`, `i-trash`, `i-filter`, `i-search`, `i-history`, `i-refresh` sind vorhanden; Pfeile fehlen), Route `GET /admin/mappings` in `routers/ui.py`, Sidebar-Eintrag in `_base.html`, leere Seite `mappings.html` mit Seitenkopf nach §5 des Standards (Pretitle, Titel, Kurzbeschreibung), **UI-Standard §4/§15 um die neue Seite ergänzen** | Seite erreichbar, 403 für Nicht-Admins | `test_control_center_ui.py`, `test_control_center_subpath_ui.py`, `test_control_center_ui_shell.py` |
| **5.1** ✅ 2026-09-30 | `static/pages/mappings.js`: fünf Karten mit Live-Anzahl (F2), Zustände Laden/Leer/Fehler/403 via `ccState`, `warnings` der Liste sichtbar (z. B. „15 casefold-Duplikate“ bei Filtern) | Bestand sichtbar, read-only | neuer Node-Harness-Test `tests/test_control_center_mappings_ui.py` |
| **5.1b** (K5) | Statisches Mockup `docs/designs/control-center-ui/mappings-editor.html` (Offcanvas, Diff, 409-Modal, Chip-Liste, ↑/↓) zur Abnahme vor dem Bau | Layout abgenommen, kein Umbau nach 5.2 | – (nur Sichtprüfung) |
| **5.2** | Offcanvas-Editor + Draft für M1/M2/M3 (key-basiert), Vorschau/Diff, Confirm, Speichern je Eintrag bzw. Save-Kette (nach K1), 409/422/503 | erste Bearbeitung | Harness: Draft, Preview-Sequenz-Guard, 409-Modal, Etag-Kette, Escaping |
| **5.3** | Editor für M4 (Chip-Liste) und M5 (Kategorien, ↑/↓) | alle fünf Typen bearbeitbar | Harness: Reihenfolge-Änderung erzeugt Diff, Cleanup-Hinweis, Kanal-Kollisions-Warnung |
| **5.4** | UI-Standard-DoD (§14), `git diff --check`, **Browser-Verifikation** (Desktop + 420 px, hell/dunkel, Subpath) per Headless-Lauf, kein Inline-JS/-Style/`confirm()`; Doku- und Findings-Abschluss (§5 Gate G5) | produktionsreif | UI-Testdateien + `test_mapping_admin*` + `test_control_center_mapping_admin*` |

Nach jedem Schritt: gezielte Tests → direkte Regressionstests → thematische Suite
(`-k "control_center or mapping"`). **Vollsuite nur durch den Nutzer** (CLAUDE.md §8.A).

### UI-Regeln (verbindlich, aus dem UI-Standard und dem Skill)

- Aufbau: `static/pages/mappings.js` als IIFE, Aktionen über `data-action` + delegierte Listener, keine `onclick=`-Attribute
- Kein Backend-Wissen im JS: Validierung, Normalisierung (lower/strip/casefold), Etag-Berechnung und `change`-Bewertung kommen ausschließlich aus der API; das JS zeigt nur an
- Seitenspezifisches CSS nur mit Präfix `cc-mapping-…` in `common.css`, mit Kommentar warum; keine globalen Tabler-Überschreibungen
- Tabler 1.5.1, Vanilla JS, Jinja2; Seiten-JS nur in `static/pages/mappings.js`, kein Inline-Skript
- Requests über `ccApi`, URLs über `apiUrl()`, freier Text durch `_escapeHtml()`
- Bestätigung `ccConfirm`, Rückmeldung `ccToast`, keine `confirm()`/`prompt()`
- Status-Farben nach §2 des Standards; Badges immer Icon + Text
- 420 px ohne horizontales Scrollen; Icon-Buttons mit `title` und `aria-label`
- Ehrliche Semantik: `bot_reload_required` und `message` aus der API wörtlich, kein Fake-Success

---

## 5. Freigabe-Gates

| Gate | Kriterium | Prüfer |
|---|---|---|
| **G1** Backend | 137 Mapping-Tests grün; Runtime-Paritätstest (siehe K2) vorhanden | Claude |
| **G2** UI | 5.0–5.4 gemergt, UI-DoD (§14 Standard) erfüllt, Harness-Tests grün | Claude |
| **G3** Produktion | Nutzer sichert die 5 Dateien (`cp mapping/{channel_genre,genre_aliases,genre_overrides,genre_filters,special_channel}.yaml`), speichert je Typ **eine** reale Änderung im Browser, prüft `git diff mapping/` und die Bot-Wirkung nach Neustart | Nutzer |
| **G4** Browser | manueller Durchlauf hell/dunkel, Desktop + Handy, Subpath (`CONTROL_CENTER_REVERSE_PROXY.md`) | Nutzer |
| **G5** Doku | `FINDINGS_INDEX` Zeile „Mapping-Dateien“ auf Umfang §6 CLOSED (bzw. Rest als eigene DEFER-Zeilen), `docs/INDEX.md`/`GENRE_SYSTEM.md` verweisen auf Admin-UI, DRAFT-`ENGINEERING_BASELINE_v13.md` angelegt (§30 CLAUDE.md) | Claude |
| **G6** Vollsuite | `python3 -m pytest tests/ -q` durch den Nutzer; Fehler nach §8.A unterscheiden (verursacht / vorbestehend / unabhängig) | Nutzer |

**Freigabe** = G1–G6 erfüllt. Erst dann wird „Mapping-Funktion abgeschlossen“ gemeldet.

---

## 6. Umfang und Abgrenzung

**Im Umfang:** fünf Typen aus M1–M5 + UI + Doku.

**Nicht im Umfang (Nutzerentscheidung K3 offen):**

| Datei / Thema | Status | Vorschlag |
|---|---|---|
| `genre_hierarchy.yaml` (M6), `genre_rules.yaml` (M7) | eigene Backend-Schritte mit Hierarchie-/Regex-Validierung | eigener Plan **nach** Freigabe |
| `known_artists.yaml`, `case_preserve.yaml`, Auto-Learned-JSON, `artist_overrides.json` | Hybrid-/Auto-Learned-Dateien: NO-GO bis Cross-Process-Write-Race (R1) und Hybrid-Konflikt (R3) fachlich entschieden | als DEFER in `FINDINGS_INDEX` |
| `artist_genre.yaml` | nur pro Artist im Genre-Reiter der Library editierbar | unverändert lassen |
| Automatisches Backup/`.bak`, Reload-IPC | Backend-Erweiterung | optional, nach Freigabe |

Damit wird die Findings-Zeile bei Freigabe **geteilt**: „fünf Typen“ CLOSED, Rest als
DEFER/OPEN mit klarer Begründung — kein stilles Schließen des ursprünglichen Ziels „alle Mappings“.

---

## 7. Klärungspunkte vor Beginn

| # | Frage | Empfehlung |
|---|---|---|
| **K1** | Key-basierte Typen: Save-Kette (mehrere PUTs) **oder** Editor speichert je Eintrag sofort (ein Eintrag = ein Preview/PUT) | **Je Eintrag** (ein Eintrag = ein Draft = ein PUT). Passt zur vorhandenen API, kein Teil-Erfolg-Zustand. F1 gilt dann für M4/M5 als Liste, für M1–M3 als „ein Eintrag“ |
| **K2** ✅ 2026-09-30 | Runtime-Paritätstest (Admin schreibt → echter `GenreProcessor`/`GenreMapper`/`filenamefixer` lädt) als G1-Bedingung | **Ja**, klein, vor 5.2; schützt genau die Fachlogik-Kante (CLAUDE.md §7/§10) |
| **K3** | Umfang „abgeschlossen“: nur §6-Umfang oder inkl. M6/M7 | **Nur §6**, M6/M7 als eigener Plan |
| **K4** | F5/F6 bestätigen (F5 jetzt: Gruppe Maintenance) | siehe §2 |
| **K5** | Statisches Mockup des Editors (Offcanvas, Diff, 409-Modal) vor 5.2, wie bei L4 | **Ja**, kleiner Schritt 5.1b; verhindert Umbau nach dem Bau |

---

## 8. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Kommentarverlust beim ersten Speichern | Warn-Banner im Editor; Regeln in `GENRE_SYSTEM.md` §3.1; manuelle Sicherung (G3) |
| `bot_reload_required`: Wirkung erst nach Neustart (bei `special-channels` teils früher) | API-Text wörtlich anzeigen; Widerspruch bleibt in FINDINGS dokumentiert |
| Veralteter Preview schaltet „Übernehmen“ frei | Sequenz-Guard + Preview-Reset bei jeder Draft-Änderung (Test) |
| Große Listen (600 Filter) im Offcanvas auf dem Handy | Suchfeld + clientseitige Filterung; Chips scrollbar im Container, kein Seiten-Scroll |
| `services/mapping_admin.py` hat ~1490 Zeilen | keine Zerlegung in diesem Plan; vor M6/M7 als eigener Schritt (CLAUDE.md §19) |
| Keine Obergrenze für Listenlängen serverseitig | nur ADMIN; als P3 in FINDINGS aufnehmen, kein Blocker |

---

## 9. Nicht Teil dieses Plans

- Kein neuer Service, kein neuer API-Endpunkt, keine Änderung an M1–M5-Verträgen
- Keine Änderung an `GenreMapper`, `GenreProcessor`, `filenamefixer` (außer bereits gemergtem Fix #379)
- Kein Drag&Drop, keine Freitext-Bearbeitung ganzer Dateien
- Kein Commit/Push ohne ausdrückliche Anweisung

---

## 10. Abgleich mit UI-Standard und Skill (2026-09-30)

Geprüft gegen `CONTROL_CENTER_UI_STANDARD.md`, Skill `musicbot-control-center-ui`, `_base.html`,
`_icons.html`, `common.js` und die Mockups. Ergebnis und Festlegungen:

| Punkt | Befund | Festlegung |
|---|---|---|
| Sidebar-Gruppe | Es gibt kein „Verwaltung“; Gruppen sind Music / Maintenance / System. Der Standard (§5) nennt als Pretitle „Musik, System, Verwaltung“ — weicht vom Code ab | Sidebar: Gruppe **Maintenance**. Pretitle der Seite: **„Wartung“** (wie `health.html`; die Sidebar-Gruppe heißt englisch „Maintenance“). Standard-Abweichung wird in 5.0 im Standard korrigiert |
| Icons | Pfeile fehlen im Sprite | in 5.0 `i-arrow-up`, `i-arrow-down` ergänzen (Standard §3 erlaubt Erweiterung) |
| Diff-Renderer | `renderMetadataEditPreview` liegt privat in `library_artist.js` und ist nicht wiederverwendbar | eigener kleiner Renderer in `mappings.js`, keine Umbauten an Library |
| Diff-/Change-Farben | im Plan bisher nicht auf §2 abgebildet | hinzugefügt (grün + `i-plus`), entfernt (rot + `i-minus`), geändert (gelb + `i-edit`); `change`-Badge: `update`/`cleanup` gelb (Warnung/prüfen), `unchanged` secondary. Text immer neben der Farbe |
| Listen | Skill will Suche + Tabelle + Paginierung; die API liefert die komplette Liste ohne Server-Paginierung (386 Aliase, 167 Overrides, 600 Filter) | **clientseitige** Suche und Seitengröße (z. B. 50) in der Tabelle im Offcanvas. Server-Paginierung wäre ein neuer Endpunkt und ist nicht Teil von Phase 5 |
| Löschen | kein DELETE-Endpunkt bei M1–M3 | keine Löschen-Schaltfläche (siehe §3) |
| Auto-Learned-Daten | Skill sieht sie read-only in der Mapping-IA vor; es gibt keinen Lese-Endpunkt | **nicht in Phase 5**; fehlender Backend-Vertrag wird gemeldet (§6) |
| Nicht unterstützte Dateien | Skill listet Artist Genre, Hierarchy, Rules als manuelle Mappings | keine Karten dafür (kein Fake-Steuerelement); Seitenbeschreibung nennt nur die fünf Typen |
| Mockup | Designautorität Nr. 2 ist `docs/designs/control-center-ui/`; für L4 gab es ein Editor-Mockup | Vorschlag K5: statisches Mockup `mappings-editor.html` vor 5.2 (siehe §7) |
| Jobs / Polling | §9 des Standards gilt nur für Jobs | nicht relevant, kein Polling |
| Reihenfolge §15 | Standard führt die Seitenliste als abgeschlossen | 5.0 ergänzt „Mappings“ dort |
| Toast/Confirm | `ccToast`, `ccConfirm` in `common.js` vorhanden; für die 409-Wahl (neu laden / abbrechen) reicht `ccConfirm` mit zwei Buttons nicht ohne Weiteres — Prüfung in 5.2 | Falls nötig: Tabler-Modal in `mappings.html` statt neuem Helfer in `common.js` |
| DoD | Skill verlangt zusätzlich `git diff --check`, Browser-Verifikation, keine fremden Dateien | in 5.4 aufgenommen |
