# POST-ARCH-009 — P-1 Phase 1: Architektur-/Verantwortlichkeitsanalyse `bot_restart_handler.py`

**Stand:** 2026-08-24
**Status:** Analyse abgeschlossen, keine Umsetzung
**Bezug:** `docs/archive/post-arch/MusicBot_POST-ARCH-009_Audit.md`, Abschnitt 5 (P-1)

---

## 1. Was macht `_trigger_restart()` tatsächlich?

`handlers/admin/bot_restart_handler.py:157-195`:

```python
def _trigger_restart(self) -> None:
    result = subprocess.run(
        ["sudo", "systemctl", "restart", self.service_name],
        check=True, timeout=15, capture_output=True, text=True,
    )
    ...
```

- Synchrone Methode, kein `async def`. Sie liest ausschließlich `self.service_name`
  (String, in `__init__` gesetzt) und schreibt ausschließlich ins `self.logger`.
- Kein `update`, `context`, `query` oder sonstiges Telegram-Objekt wird
  referenziert. Kein Zugriff auf `self.config` außer indirekt über den beim
  Konstruktor übergebenen `service_name`.
- Aufruf erfolgt nicht direkt/awaited, sondern über
  `asyncio.get_event_loop().call_later(_PRE_RESTART_DELAY, self._trigger_restart)`
  in `execute_restart()` (Zeile 134) — die Methode läuft damit **synchron im
  Event-Loop-Thread**, nicht in einem Executor (anders als
  `utils/navidrome_scan_trigger.py`, das `asyncio.create_subprocess_shell` +
  `await` nutzt). Das blockiert den Event-Loop für die Dauer von
  `systemctl restart` (bis zu 15s Timeout) — praktisch folgenlos, da der
  Prozess ohnehin durch den Restart beendet wird, aber ein struktureller
  Unterschied zum Navidrome-Präzedenzfall, der bei einer Extraktion beachtet
  werden sollte.
- Fehlerbehandlung: `CalledProcessError`, `FileNotFoundError` (sudo/systemctl
  fehlt), generische `Exception` — jeweils nur geloggt, kein Re-Raise (die
  Methode hat ohnehin keinen Aufrufer, der auf einen Rückgabewert wartet).
- **Fazit:** reine, telegramfreie lokale Prozesssteuerung — kapselt exakt
  einen OS-Aufruf (`systemctl restart <service>`) mit Timeout- und
  Fehlerbehandlung.

## 2. Consumer

Repo-weiter Grep auf `BotRestartHandler`:

| Ort | Art |
|---|---|
| `handlers/menu/rich_menu_handler.py:43,103,271-275,481-485` | Import, Instanziierung (`BotRestartHandler(self.config, self.logger_factory)`), Weiterreichung an `RichMenuSystem.set_restart_handler()` |
| `handlers/menu/rich_menu_system.py:161,216-222,911-922,1742-1780` | Hält `self.restart_handler`, routet `restart:show`/`restart:confirm`/`restart:cancel` an die drei öffentlichen Methoden |
| `tests/test_bot_restart_handler.py` | 5 Testklassen (`TestIsAdmin`, `TestShowRestartConfirm`, `TestExecuteRestart`, `TestCancelRestart`, `TestTriggerRestart`), `subprocess.run` wird in `TestTriggerRestart` per `patch("subprocess.run", ...)` (globaler Modulpfad, nicht auf `handlers.admin.bot_restart_handler` gescopt) gemockt |

**Genau ein Produktions-Consumer** (`RichMenuHandler` → `RichMenuSystem`), keine weiteren Instanziierungen im Repo.

## 3. Ist der Restart ausschließlich Telegram/Admin-spezifisch?

Nein — differenziert zu betrachten:

- Die drei öffentlichen Methoden (`show_restart_confirm`, `execute_restart`,
  `cancel_restart`) **sind** genuin Telegram/Admin-spezifisch: sie nehmen
  `Update`/`ContextTypes`, prüfen `_is_admin()`, senden/editieren Nachrichten.
  Das gehört zu Recht in `handlers/`.
- `_trigger_restart()` selbst ist **nicht** Telegram-spezifisch. Sie kennt
  weder Telegram noch „Admin" als Konzept — sie ruft einen benannten
  systemd-Service neu. Der einzige Bot-Bezug ist der Service-Name als
  Konstruktor-Parameter. Die Methode wäre unverändert aus einem CLI-Tool,
  einem Cron-Job oder einer anderen Admin-Oberfläche aufrufbar.

Die Autorisierungs-/Bestätigungslogik ist zu Recht an Telegram gebunden
(privilegierte Aktion, muss vor Ausführung gegated werden); der eigentliche
Restart-Mechanismus ist generische Infrastruktur.

## 4. Weitere Restart-/Shutdown-/Process-Control-Logik im Repo?

Repo-weiter Grep auf `systemctl`, `os.kill`, `signal.SIG*`, `sys.exit`,
`shutdown`:

| Fund | Bewertung |
|---|---|
| `bot.py` (Zeilen 13, 58, 193-411): `signal.signal(SIGINT/SIGTERM, ...)`, `self._shutdown_event`, `await self.application.shutdown()` | **Separater, nicht überlappender Mechanismus.** OS-Signal-getriggertes, geordnetes In-Prozess-Herunterfahren (kein `subprocess`, kein `systemctl`) — reagiert auf externe Stop-Signale (z. B. `systemctl stop`/Ctrl+C), beendet den Prozess sauber. Löst **keinen** Neustart aus; ob der Prozess danach neu startet, hängt allein von einer außerhalb des Repos liegenden systemd-`Restart=`-Policy ab. Keine Code-Berührung mit `_trigger_restart()`. |
| `handlers/admin/backup_handler.py` (`shutil`, `tarfile`) | Kein Process-Control, aber strukturell verwandtes Muster: lokale Infrastruktur-Operationen (Archivierung) direkt in einem `handlers/admin/`-Handler, vermischt mit Telegram-Präsentation. Nicht Gegenstand dieser Analyse (siehe Abschnitt 7). |
| `emoji.py` | Falsch-Positiv (nur der Dict-Key `"shutdown"` für ein Emoji). |

Keine weitere Stelle im Repo ruft `systemctl`, `kill` oder einen
vergleichbaren Prozess-Neustart-Befehl auf. `_trigger_restart()` ist der
einzige Ort mit echter Prozess-Neustart-Logik.

## 5. Passender Service-/Utility-Präzedenzfall

Zwei bestehende `utils/`-Module als Vergleich:

| | `utils/navidrome_scan_trigger.py` | `utils/audio_enhancer.py` |
|---|---|---|
| Subprocess-Art | `asyncio.create_subprocess_shell` + `await` (nicht-blockierend) | `subprocess.run()` (synchron, wie `_trigger_restart()`) |
| Externe Netzwerkkommunikation | keine | **ja** — `requests.Session` gegen Last.fm/MusicBrainz/Cover Art Archive (Künstlerbilder, MusicBrainz-IDs) |
| Ergebnistyp | `@dataclass ScanRunResult` (`success`-Flag) | `@dataclass EnhancementResult` (`success`-Flag) |
| Telegram-Kopplung | keine | keine |
| Custom Exception | `ScanTimeoutError` | keine (nur bool/None-Rückgaben) |

**Wichtige Präzisierung gegenüber der ARCH-009-Folgeanalyse:** `audio_enhancer.py`
ist kein rein lokaler Subprocess-Wrapper — es kombiniert `ffmpeg`-Subprocess-
Aufrufe mit echten externen HTTP-Aufrufen (Last.fm/MusicBrainz/Cover Art
Archive) in derselben Klasse. Als Präzedenzfall für „reine lokale
Prozesssteuerung ohne Netzwerk" ist `navidrome_scan_trigger.py` daher das
präzisere Vorbild; `audio_enhancer.py` bestätigt lediglich zusätzlich, dass
`utils/` bereits synchrone `subprocess.run()`-Aufrufe (wie in
`_trigger_restart()`) verträgt.

`_trigger_restart()` selbst hat **keine** externe Netzwerkkommunikation —
strukturell also sogar reiner als beide Vorbilder.

## 6. `utils/` vs. `services/` vs. `services/admin/`

| Variante | Bewertung |
|---|---|
| `services/clients/` | Nicht zutreffend — keine externe API-/Netzwerkkommunikation, die Konvention ist explizit auf externe Integrationsadapter beschränkt (siehe `CLAUDE.md` Abschnitt 4/17). |
| `services/` (übrige) | Steht laut etablierter Schichtgrenze für fachliche/technische **Orchestrierung**. `_trigger_restart()` orchestriert nichts — es ist ein einzelner, in sich abgeschlossener OS-Aufruf ohne Teilschritte, die koordiniert werden müssten. |
| neue Schicht `services/admin/` | Existiert nicht, wäre eine **neue Konvention einzig für diese eine ~40-Zeilen-Methode**. Kein zweiter Kandidat im Repo würde sie aktuell füllen (Abschnitt 4: `backup_handler.py` wäre ein möglicher zweiter Bewohner, aber das ist eine eigene, hier nicht getroffene Entscheidung). Würde CLAUDE.md Regel 18 („kein größerer Refactor/keine neue Abstraktion ohne konkreten Treiber") und dem in der Folgeanalyse zu `NavidromeScanTrigger` etablierten Grundsatz widersprechen, keine neue Schicht zu erfinden, wenn ein bestehender Präzedenzfall passt. |
| `utils/` | Entspricht 1:1 dem bereits zweifach bestätigten Muster (`navidrome_scan_trigger.py`, `audio_enhancer.py`): lokaler technischer Runner, kein Netzwerk zwingend, kein Telegram, `@dataclass`-Ergebnis. Einzige Variante ohne neue Konvention. |

**Einordnung (Analysebefund, keine Entscheidung):** `utils/` ist die
strukturell konsistenteste Zielposition — exakt die gleiche Begründung, die
in der ARCH-009-Folgeanalyse zur Variante D für `NavidromeScanTrigger`
führte.

## 7. Sollte `handlers/admin/` ausschließlich Presentation bleiben?

Aktueller Ist-Zustand in `handlers/admin/` (3 Dateien):

| Datei | Telegram-Präsentation | Zusätzliche Infrastruktur-Logik direkt im Handler |
|---|---|---|
| `bot_restart_handler.py` | ja | `subprocess.run(["sudo", "systemctl", ...])` (Prozesssteuerung) |
| `backup_handler.py` | ja | `shutil`/`tarfile`-Operationen (Archivierung) |
| `user_management_handler.py` | ja | JSON-Datei-Lesen/Schreiben (eigener Persistenzzustand) |

`handlers/admin/` ist **aktuell nicht** ausschließlich Presentation. Ob es
das grundsätzlich sein *sollte*, lässt sich nicht pauschal beantworten:

- Reine Selbstzustands-Persistenz (`user_management_handler.py`s JSON-I/O)
  ist ein deutlich schwächerer Fall als echte Prozess-/Systemsteuerung oder
  Archivierung — viele Handler persistieren legitim ihren eigenen Zustand,
  ohne dass das zwingend eine eigene Service-Schicht braucht.
- Echte lokale Infrastruktur-Operationen (Prozesssteuerung wie in
  `bot_restart_handler.py`, Archivierung wie in `backup_handler.py`) folgen
  demselben Muster, das ARCH-009 für Navidrome bereits als Architekturbruch
  identifiziert und aufgelöst hat: technische Ausführung vermischt mit
  Telegram-Präsentation in derselben Klasse.

**Für `bot_restart_handler.py` konkret:** Ja — die Trennung ist hier sinnvoll
und mit minimalem Aufwand möglich (eine private Methode, ein exakter
Präzedenzfall). `backup_handler.py` zeigt dasselbe Muster, ist aber **nicht**
Teil dieser Analyse und wird hier bewusst nicht mitbewertet — eigener,
separat zu entscheidender Kandidat für eine spätere Post-ARCH-009-Runde.

---

## Entscheidungsgate

Diese Analyse trifft **keine** Umsetzungsentscheidung. Befund zusammengefasst:

- `_trigger_restart()` ist ein isolierter, telegramfreier, rein lokaler
  Infrastruktur-Aufruf mit genau einem Produktions-Consumer und bereits
  vorhandener Testabdeckung.
- Kein Überschneidung mit dem separaten Shutdown-Signal-Mechanismus in
  `bot.py`.
- `utils/` ist die einzige Zielposition ohne neue Architektur-Konvention;
  `services/admin/` wäre eine unbegründete Neuerfindung für einen einzelnen
  kleinen Fund.
- `audio_enhancer.py` ist als Präzedenzfall nur eingeschränkt „rein" (mischt
  selbst Subprocess + externe HTTP-Aufrufe) — `navidrome_scan_trigger.py`
  bleibt das genauere Vorbild.
- `backup_handler.py` zeigt ein verwandtes, aber eigenständiges Muster und
  ist ausdrücklich nicht Teil dieser Entscheidung.

Offene Fragen für einen möglichen nächsten Schritt (P-1 Phase 2 —
Umsetzungsanalyse, falls freigegeben): genaue Zielmodul-/Klassenbenennung,
ob der Subprocess-Aufruf synchron (wie bisher) oder auf `await
asyncio.create_subprocess_exec` umgestellt werden soll (Verhaltensfrage,
keine reine Verschiebung), Umgang mit `asyncio.get_event_loop()` (in Python
3.12 deprecated) und Migration der Testdatei/Patch-Ziele.

**Nächster Schritt wird separat entschieden.**
