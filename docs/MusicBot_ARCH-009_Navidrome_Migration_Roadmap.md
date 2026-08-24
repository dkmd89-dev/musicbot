Klar — hier ist der Inhalt für **`docs/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md`** zum Copy/Paste:

````md
# MusicBot ARCH-009 — Navidrome Migration Roadmap

## Zweck

Diese Roadmap dokumentiert die schrittweise Entflechtung der aktuellen
`api/navidrome_api.py` und die spätere Entscheidung über die endgültige
Architektur des verbleibenden Navidrome-Integrationskerns.

Die Roadmap ist ein **Architektur-Fahrplan**, kein Gesamtauftrag zur
automatischen Umsetzung aller Phasen.

Jede Phase wird separat analysiert bzw. umgesetzt, getestet, reviewed und
erst danach wird über den nächsten Schritt entschieden.

---

# Ausgangslage

Die Analyse aus ARCH-008 und ARCH-009 hat ergeben, dass die ursprüngliche
`api/navidrome_api.py` mehrere unterschiedliche Verantwortlichkeiten
vermischt:

1. externe Navidrome/Subsonic-API-Kommunikation
2. Telegram-spezifische Präsentations-/Formatierungslogik
3. lokale Subprocess-/Shell-Ausführung für Navidrome-Scans
4. teilweise Diagnose-/Statusfunktionen

Eine direkte 1:1-Verschiebung nach:

```text
services/clients/
````

wäre daher architektonisch nicht korrekt.

Die bestehende Regel bleibt:

```text
services/clients/
    = ausschließlich externe Integrationsadapter
```

Telegram-Präsentationslogik darf dort nicht landen.

Lokale Shell-/Subprocess-Steuerung wird nicht ungeprüft als Teil eines
externen API-Clients behandelt.

---

# Bereits abgeschlossen

## ARCH-008 — Analyse `api/navidrome_api.py`

Abgeschlossen.

Ergebnis:

* `NavidromeAPI` ist kein reiner Integrationsadapter.
* Die Datei vermischte API-Kommunikation, Telegram-Formatierung und
  Subprocess-Steuerung.
* Mehrheit der Consumer liegt in `handlers/`.
* Der einzige bekannte `services/`-Consumer ist bereits über Dependency
  Injection entkoppelbar.
* Eine direkte Verschiebung nach `services/clients/` wurde verworfen.

---

## ARCH-009 Phase 1 — Bestandsaufnahme ungenutzter Methoden

Abgeschlossen.

Sieben ungenutzte Methoden wurden einzeln untersucht.

Entscheidung:

### Entfernen

* `format_full_status_message()`
* `format_rescan_status_message()`
* `format_web_interface_url_message()`
* `get_full_server_info()`
* `get_scan_status()`
* `test_api()`

### Behalten

* `check_connection()`

`check_connection()` bleibt erhalten, da ein dokumentierter zukünftiger
Einsatz aus BUG-007 besteht.

---

## ARCH-009 Phase 2 — Entfernung toter Navidrome-Methoden

Abgeschlossen.

Die sechs freigegebenen ungenutzten Methoden wurden entfernt.

Nicht Bestandteil dieser Phase:

* keine Verschiebung von `api/navidrome_api.py`
* keine DI-Umstellung
* keine Änderung an `check_connection()`
* keine Änderung an `execute_scan()`
* keine Architekturmigration nach `services/clients/`

---

## ARCH-009 Phase 3 — `execute_scan()` / Subprocess-Verantwortung analysieren

Abgeschlossen.

Ergebnis: `execute_scan()` vermischte Konfigurationsvalidierung,
Docker-Subprocess-/Timeout-Steuerung und Telegram-MarkdownV2-Formatierung.
Vier Zielarchitektur-Varianten (A-D) bewertet, empfohlen wurde eine
gestufte Umsetzung (zuerst Subprocess-Extraktion, Telegram-Trennung als
separater, späterer Schritt). Details:
`docs/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md`.

---

## ARCH-009 Phase 4 — Subprocess-Verantwortung extrahieren

Abgeschlossen.

Die Docker-/Subprocess-/Timeout-Steuerung wurde 1:1 nach
`api/navidrome_scan_trigger.py` (`NavidromeScanTrigger`) ausgelagert.
`NavidromeAPI.execute_scan()` bleibt als öffentliche Schnittstelle
unverändert bestehen und fungiert als Bridge; kein Consumer musste
angepasst werden. Telegram-Formatierung, `check_connection()` und die
Zielposition `services/clients/` blieben bewusst unangetastet. Details:
`docs/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md` (Abschnitt „Phase 4
— Umsetzung“).

---

# Nächste Phasen

Phase 3 und Phase 4 sind abgeschlossen (siehe oben unter „Bereits
abgeschlossen“).

## Phase 5 — Verbleibende Präsentations-/Telegram-Verantwortlichkeiten prüfen

### Ziel

Nach der Klärung von `execute_scan()` prüfen, ob im verbleibenden
Navidrome-Code noch Telegram-spezifische Verantwortlichkeiten vorhanden
sind.

### Zielarchitektur

```text
Integrationsadapter
        ↓
strukturierte Daten / Ergebnisse
        ↓
Anwendungslogik / Consumer
        ↓
Handler
        ↓
Telegram-Präsentation
```

### Grundsatz

Ein späterer Navidrome-Client darf:

* keine `telegram.*`-Abhängigkeiten besitzen
* keine Telegram-Objekte speichern
* keine Telegram-Nachrichten direkt versenden
* keine Telegram-spezifische Markdown-Formatierung enthalten

### Entscheidungsgate

Vor einer Umsetzung prüfen, welche konkreten Verantwortlichkeiten nach
Phase 4 überhaupt noch betroffen sind.

Keine vorsorgliche Umstrukturierung.

---

## Phase 6 — Verbleibenden Navidrome-API-Kern analysieren

### Ziel

Nach Abschluss der vorherigen Entflechtung den tatsächlich verbleibenden
Navidrome-Integrationskern neu bewerten.

Zu prüfen:

* welche Methoden verbleiben
* welche davon echte externe API-Kommunikation darstellen
* welche Consumer existieren
* welche Konfiguration benötigt wird
* welche Zustände aktuell als Klassenattribute gehalten werden
* ob `check_connection()` Teil des Integrationskerns ist
* ob noch vermischte Verantwortlichkeiten vorhanden sind

### Ergebnis

Entscheidungsvorlage:

* Ist der verbleibende Kern jetzt ein reiner Integrationsadapter?
* Ist `services/clients/` der richtige Zielort?
* Welche Klasse bzw. welches Modul soll entstehen?
* Welche bestehende API kann intern beibehalten werden?
* Welche Migration wäre risikoarm?

---

## Phase 7 — Zielstruktur des Navidrome-Clients entscheiden

### Voraussetzung

Phase 6 bestätigt, dass der verbleibende Code ein reiner externer
Integrationsadapter ist.

### Zu entscheiden

Ob beispielsweise eine Struktur wie folgt sinnvoll ist:

```text
services/
└── clients/
    └── navidrome_client.py
```

Der konkrete Dateiname und die konkrete Klassenstruktur werden erst nach
der Analyse entschieden.

### Grundsatz

Keine 1:1-Verschiebung einer Reststruktur nur aufgrund des Namens.

Die Zielstruktur muss sich aus den tatsächlichen Verantwortlichkeiten
ergeben.

---

## Phase 8 — DI und Consumer-Migration entscheiden und umsetzen

### Ausgangslage

Die bisherigen `NavidromeAPI`-Consumer verwenden überwiegend statische
Methoden.

Eine vollständige Umstellung auf eine Instanz mit Dependency Injection
hat daher einen größeren Blast Radius als P-11.

### Zu analysieren und entscheiden

* Kann eine statische Struktur sinnvoll erhalten bleiben?
* Ist eine instanziierbare Client-Klasse architektonisch sinnvoll?
* Welche Consumer müssen angepasst werden?
* Können Migration Bridges den Übergang absichern?
* Welche Test- und Mock-Pfade ändern sich?
* Kann die Umstellung schrittweise erfolgen?

### Umsetzung

Erst nach einer eigenen Nutzerentscheidung.

Keine automatische DI-Umstellung allein aus Konsistenzgründen.

---

## Phase 9 — Finaler Navidrome-Migrationsabschluss

Nach Abschluss aller entschiedenen Migrationsschritte:

### Prüfen

* keine Telegram-Abhängigkeiten im Integrationsadapter
* keine Präsentationslogik im Client
* keine ungeklärte Subprocess-Verantwortung
* keine Legacy-Importe auf alte Navidrome-Strukturen
* keine unnötigen Migration Bridges
* keine zyklischen Abhängigkeiten
* Consumer verwenden die entschiedene Zielstruktur
* Tests und Mock-Pfade sind konsistent

### Abschlussarbeiten

1. vollständiger Regressionstest
2. Import-Smoke-Test
3. Dependency-/Import-Audit
4. Architektur-Dokumentation aktualisieren
5. PR-Review
6. Merge

---

# Übergeordnete Zielarchitektur

Langfristig gilt:

```text
services/clients/
    │
    ├── externe Systeme ansprechen
    ├── HTTP/API-Kommunikation
    ├── Authentifizierung
    └── strukturierte API-Ergebnisse
```

```text
services/
    │
    ├── Anwendungs- und Fachlogik
    ├── Orchestrierung
    └── Verarbeitung strukturierter Daten
```

```text
handlers/
    │
    ├── Telegram-Interaktion
    ├── User-Input
    ├── Nachrichtenversand
    └── Telegram-spezifische Präsentation
```

Lokale Infrastruktur-, Shell- oder Subprocess-Verantwortlichkeiten werden
separat nach ihrer tatsächlichen Aufgabe bewertet und nicht automatisch
einem API-Client zugeordnet.

---

# Arbeitsprinzip

Die Phasen dieser Roadmap werden ausdrücklich **nicht automatisch
nacheinander implementiert**.

Für jede Phase gilt:

```text
Analyse
   ↓
Entscheidung
   ↓
separater Umsetzungsauftrag
   ↓
eigener Branch
   ↓
Tests
   ↓
Review / PR
   ↓
Merge
   ↓
nächste Phase
```

Eine spätere Phase darf nicht vorweggenommen werden, solange die dafür
notwendige Architekturentscheidung noch offen ist.

Die Roadmap dient der Orientierung und Nachvollziehbarkeit. Die konkreten
Arbeitsaufträge werden weiterhin schrittweise und einzeln erteilt.

```

Ich würde diese Roadmap **erst auf `main` dokumentieren, nachdem Phase 2 gemerged wurde**. Die nächsten Phasen selbst bleiben dann bewusst offen, bis jeweils die vorherige Analyse abgeschlossen und entschieden ist.
```

