# services/logs/reader.py
# -*- coding: utf-8 -*-
"""
Liest und filtert Zeilen aus den bereits bestehenden Logdateien in
Config.LOG_DIR (logger.py::setup_enhanced_logging()/
setup_module_logging(), inkl. Rotation via
logging.handlers.RotatingFileHandler) — Master-Prompt Abschnitt 12
"LOGS & DIAGNOSTICS" / ui_prompt.txt Abschnitt 23. Reine Lesefunktion,
KEINE neue Logging-Infrastruktur, kein Log-Format geändert.

**Charakterisierung des Ist-Zustands (vor dieser Erweiterung geprüft):**
es existiert bereits eine Telegram-seitige Log-Verwaltung
(`handlers/enhanced_logger_menu_handler.py`, `EnhancedLoggerMenuHandler`)
— Datei-Übersicht + 5-Zeilen-Vorschau + naive Level-Zählung
(`if level in line`), **kein** strukturierter, nach Level/Component
filterbarer Zeilen-Browser. Diese Erweiterung baut daher keine
Parallelimplementierung eines bereits gelösten Problems, sondern liefert
eine dort noch nicht vorhandene Fähigkeit. Die Datei-Discovery
(`log_dir.glob("*.log*")`) sowie der Path-Traversal-Schutz per
`resolve()`/`is_relative_to()` übernehmen bewusst denselben, bereits in
`EnhancedLoggerMenuHandler.show_log_file_detail()` etablierten und
sicherheitsrelevant gefixten Ansatz (SEC-003, siehe
`tests/test_logger_menu_path_traversal.py`) — keine zweite, abweichende
Sicherheitslösung für dasselbe Problem.

**Mehrere Zeilenformate im Repository** — `logger.py::
ColoredFormatter` (Root-Logger/`bot.log`, KEIN Datum, nur `HH:MM:SS`,
mit ANSI-Farbcodes) ist das einzige Format, das hier strukturiert
geparst wird (Level/Component/Message). Andere Module nutzen eigene,
teils abweichende Formatter (z. B. `AutoLearnManager` mit vollem Datum)
— deren Zeilen werden nicht verworfen, sondern als unstrukturierter
Eintrag (level=None, component=None, message=ganze Zeile) zurückgegeben:
weiterhin durchsuchbar (Search), nur nicht nach Level/Component
filterbar. Keine Vortäuschung einer repoweiten Formatvereinheitlichung,
die nicht existiert (Master-Prompt Regel 38).

Bewusste Einschränkungen (Master-Prompt Regel 38 "keine Fake-
Implementierung" — lieber ehrlich weglassen als eine nicht wirklich
vorhandene Genauigkeit vortäuschen):

- **Kein "Zeitraum"-Filter mit echter Datumsgrenze.** Für das
  Root-Format (`bot.log` + Rotation, der praktisch wichtigste Fall) gibt
  es keine verlässliche Datumsinformation innerhalb der Zeile — nur die
  Datei-Auswahl selbst grenzt grob ein.
- **Kein "Job"/"User"-Filter.** Keiner der bestehenden `log*()`-Aufrufe
  im gesamten Repository korreliert Log-Zeilen strukturiert mit einer
  Job-/User-ID (kein einheitliches `extra={"job_id": ...}"`-Feld o. Ä.)
  — das flächendeckend nachzurüsten wäre ein großer, hier nicht
  beauftragter Eingriff in sehr viele bestehende log-Aufrufe.

Security (Master-Prompt Abschnitt 23/31, CLAUDE.md Abschnitt 12 P0
"keine Secrets loggen"): zusätzliche, defensive Redaktion
offensichtlicher Secret-Muster VOR der Rückgabe — ergänzt die
bestehende P0-Regel (die Log-Zeilen sollten ohnehin keine Secrets
enthalten), ersetzt sie aber nicht. ANSI-Farbcodes (die reale
`bot.log` enthält sie, da `setup_enhanced_logging()` denselben
`ColoredFormatter` für Konsole UND Datei verwendet, `use_colors=True`)
werden vor der Auslieferung entfernt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from logger import LOG_LEVEL_EMOJIS

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_LINE_RE = re.compile(
    r"^(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<level_token>\S+)\s+"
    r"(?:(?P<module_emoji>\S+)\s+)?"
    r"\[(?P<component>[A-Z0-9_]+)\]\s*"
    r"(?P<message>.*)$"
)
_LEVEL_EMOJI_TO_NAME = {v: k for k, v in LOG_LEVEL_EMOJIS.items()}
_KNOWN_LEVEL_NAMES = frozenset(LOG_LEVEL_EMOJIS.keys())

# Defensive Zusatz-Redaktion (siehe Modul-Docstring) - Muster fuer
# gaengige Secret-Zuweisungen/Header, unabhaengig vom konkreten Wert.
_SECRET_PATTERNS = [
    re.compile(r"(?i)(token|password|passwd|secret|api[_-]?key)\s*[=:]\s*\S+"),
    re.compile(r"(?i)authorization:\s*bearer\s+\S+"),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),  # Telegram-Bot-Token-Form
]


def _strip_ansi(line: str) -> str:
    return _ANSI_RE.sub("", line)


def _redact_secrets(line: str) -> str:
    for pattern in _SECRET_PATTERNS:
        line = pattern.sub("[REDACTED]", line)
    return line


@dataclass
class LogEntry:
    time: str
    level: Optional[str]
    component: Optional[str]
    message: str


def _parse_line(raw_line: str) -> LogEntry:
    """Parst eine einzelne, bereits ANSI-bereinigte Log-Zeile. Zeilen,
    die nicht dem erwarteten "HH:MM:SS [MODUL] Nachricht"-Format
    entsprechen (z. B. Exception-Tracebacks, die logger.py mehrzeilig
    anhaengt), werden als eigener Eintrag ohne level/component
    zurueckgegeben - weiterhin durchsuchbar (Search), nur nicht nach
    Level/Component filterbar."""
    match = _LINE_RE.match(raw_line)
    if not match:
        return LogEntry(time="", level=None, component=None, message=raw_line)

    level_token = match.group("level_token")
    level = _LEVEL_EMOJI_TO_NAME.get(level_token)
    if level is None and level_token in _KNOWN_LEVEL_NAMES:
        level = level_token  # use_emojis=False -> Klartext-Levelname statt Emoji

    return LogEntry(
        time=match.group("time"),
        level=level,
        component=match.group("component"),
        message=match.group("message"),
    )


def list_log_sources(log_dir: Path) -> list[str]:
    """Alle tatsaechlich vorhandenen Logdateien im Log-Verzeichnis,
    alphabetisch sortiert — `*.log*` deckt sowohl die aktuelle Datei
    als auch rotierte Backups ab (`bot.log`, `bot.log.1`, ...) UND die
    separaten Modul-Dateien (z. B. `autolearnmanager.log`), identisch
    zur bereits etablierten Discovery in
    `EnhancedLoggerMenuHandler` (`log_dir.glob("*.log*")`)."""
    if not log_dir.is_dir():
        return []
    return sorted(p.name for p in log_dir.glob("*.log*") if p.is_file())


def read_logs(
    log_dir: Path,
    *,
    default_source: str = "bot.log",
    source: Optional[str] = None,
    level: Optional[str] = None,
    component: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 200,
) -> dict:
    """Liest genau EINE Log-Datei aus `log_dir` (per `source` gewaehlt,
    sonst `default_source` falls vorhanden, sonst die erste verfuegbare),
    wendet Filter an und liefert die zuletzt geschriebenen `limit`
    passenden Zeilen (neueste zuerst).

    Doppelter Pfad-Traversal-Schutz: `source` muss (a) einer der von
    list_log_sources() gelieferten Namen sein (Whitelist-Abgleich) UND
    (b) nach `resolve()` tatsaechlich innerhalb von `log_dir` liegen
    (identischer Ansatz wie der bereits gefixte SEC-003-Bug in
    `EnhancedLoggerMenuHandler.show_log_file_detail()`, siehe
    Modul-Docstring) — kein Rohpfad wird ungeprueft uebernommen."""
    available = list_log_sources(log_dir)
    if source:
        chosen = source
    elif default_source in available:
        chosen = default_source
    else:
        chosen = available[0] if available else None

    if chosen is None or chosen not in available:
        return {
            "source": chosen or "",
            "available_sources": available,
            "total_matched": 0,
            "limit": limit,
            "entries": [],
        }

    resolved_dir = log_dir.resolve()
    path = (log_dir / chosen).resolve()
    if not path.is_relative_to(resolved_dir):
        return {
            "source": "",
            "available_sources": available,
            "total_matched": 0,
            "limit": limit,
            "entries": [],
        }

    try:
        raw_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {
            "source": chosen,
            "available_sources": available,
            "total_matched": 0,
            "limit": limit,
            "entries": [],
        }

    search_lower = search.lower() if search else None
    matched: list[LogEntry] = []
    for raw_line in reversed(raw_text.splitlines()):
        line = _redact_secrets(_strip_ansi(raw_line))
        if not line.strip():
            continue
        entry = _parse_line(line)
        if level and (entry.level or "").upper() != level.upper():
            continue
        if component and (entry.component or "").upper() != component.upper():
            continue
        if search_lower and search_lower not in line.lower():
            continue
        matched.append(entry)

    return {
        "source": chosen,
        "available_sources": available,
        "total_matched": len(matched),
        "limit": limit,
        "entries": matched[:limit],
    }
