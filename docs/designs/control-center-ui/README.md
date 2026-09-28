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
| Nutzer 1 | _offen_ | |
| Nutzer 2 | _offen_ | |

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
