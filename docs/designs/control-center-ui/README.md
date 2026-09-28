# Control Center — Layout-Entwürfe (CC-UI-0)

Statische Mockups zum Vergleich, **keine Produktionsdateien**. Alle Entwürfe
zeigen dieselbe Beispielseite (Downloads) mit denselben Daten, damit der
Vergleich fair bleibt. Ausgangslage: `docs/audits/CONTROL_CENTER_UI_INVENTORY_2026-09-28.md`.

Öffnen: Datei direkt im Browser. Tabler 1.5.1 wird aus dem Repo geladen
(`control_center/static/vendor/tabler/`), sonst per CDN.

| Entwurf | Datei | Kurzbeschreibung |
|---|---|---|
| A · Klassisch | `layout-a-klassisch.html` | helle vertikale Sidebar (wie heute), Seitenkopf mit Aktionen, Karten mit Kopfzeile, Tabellen, `bg-*-lt`-Badges; am wenigsten Umbau |
| B · Kompakt | `layout-b-kompakt.html` | horizontale Navigation, Emojis bleiben, KPIs als Textzeile, Tabs in einer Karte, dichte Tabellen, Status-Punkte |
| C · Dashboard | `layout-c-dashboard.html` | dunkle Sidebar mit Zählern, Hell/Dunkel-Umschalter, KPI-Karten mit Icon, Pipeline als Schrittfolge, Seitenpanel (`offcanvas`), Toasts |
| Nutzer 1–3 | (Screenshots im Chat, nicht abgelegt) | 1 Karten-Raster, 2 Tabelle, 3 Terminal-Stil — alle dunkel mit Türkis-Akzent |
| **D · Mischung** | `layout-d-mischung.html` | **gemeinsam gewählte Richtung** (siehe unten) |
| L4 · Metadaten-Editor | `l4-metadaten-editor.html` | Entwurf für den Editor auf der Artist-Seite (2026-09-28): Seitenpanel mit Reitern Artist/Titel/Album/Genre/Duplikate, vorbelegte Felder, automatische Vorschau alt → neu, Wartungs-Werkzeuge integriert (Karte „Library-Wartung“ entfällt, L3 nur noch auf Health) — **zur Freigabe** |

Eigene Entwürfe bitte als `layout-<name>.html` hier ablegen (gleiche
Beispielseite erleichtert den Vergleich, ist aber keine Pflicht).

## Vergleichskriterien

Die Entscheidungen aus Inventur Abschnitt 6 fallen direkt aus dem Vergleich:

| Kriterium | A | B | C |
|---|---|---|---|
| Navigation | Sidebar hell | oben horizontal | Sidebar dunkel + Zähler |
| Icons in Titeln | keine | Emojis | keine (Icons in KPI) |
| Dark Mode | nein | nein | ja (Umschalter) |
| Bestätigung | Modal | Modal | Modal |
| Rückmeldung | – | – | Toast |
| Detailansicht | Tabelle in Karte | Datagrid + Liste | Seitenpanel + Timeline |
| Pipeline-Schritte | Tabelle | Liste mit Status-Punkten | Schrittfolge (`steps`) |
| Laden / Leer / Fehler | Platzhalter / `empty` / `alert` | Spinner / Textzeile / `alert` | Platzhalter / `empty` mit Aktion / Karte mit Statusrand |
| Umbauaufwand ggü. heute | gering | mittel (Shell neu) | mittel (Shell + Theme) |

Mischen ist ausdrücklich erlaubt (z. B. Shell aus A, Pipeline und Toasts aus C).
Das Ergebnis wird als `docs/CONTROL_CENTER_UI_STANDARD.md` festgehalten (Schritt CC-UI-Standard).

## Entscheidung 2026-09-28 → Entwurf D

- **Mischung freigegeben:** Shell aus C (dunkle Sidebar mit Zählern), aktive Jobs als Karten (Nutzer 1) mit Pipeline-Schritten (C), Verlauf und alle Listen als Tabelle (Nutzer 2), Logs/Logger im Terminal-Stil (Nutzer 3), Bestätigung per Modal, Rückmeldung per Toast (C), Zustände Laden/Leer/Fehler (A).
- **Dunkel als Standard**, Umschalter auf Hell (Wahl pro Browser), Akzentfarbe Türkis.
- **Tabler-Icons** statt Emojis in Navigation, Titeln und Aktionen.
- **Keine Funktionen ohne bestehende API:** kein Format/Bitrate, kein Pause/Play, keine MB/s/ETA/Größe/Speicherplatz, keine Cover-Vorschau, nur YouTube.
- Handy: Schrittfolge wird zu „Schritt n von 7“, Metadaten-Spalte ausgeblendet.

Abgeleitet: `docs/CONTROL_CENTER_UI_STANDARD.md` (verbindlich). Das Mockup bleibt Referenz, der Standard hat Vorrang.
