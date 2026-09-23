# -*- coding: utf-8 -*-
"""
CC-LOGGER-L2 (Logger Read API, Phase L2) — Telegram-freier
Application-Layer für Log-Administration.

Deckt **ausschließlich Klasse A** (shared-filesystem-basierte,
prozessübergreifend gültige Read-Daten) aus der L1-Analyse ab:

    Class A — API-fähig      (dieses Modul)
      • Log-Dateiliste
      • Log-Datei-Inhalt (Tail, gefiltert)
      • Log-Datei-Statistiken (Größe, mtime, Aggregat)

    Class B — DEFERRED (LOGGER-RUNTIME-CONTROL, siehe
    docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md)
      • Modul-Level setzen
      • Modul aktivieren/deaktivieren
      • Globales Level ändern
      • File-/Console-Handler manipulieren
      • Handler-Reload
      • Process-lokale Logger-/Handler-Statusabfragen
      Diese Funktionen benötigen Runtime-Zugriff auf den *Bot*-Prozess
      (_module_loggers, logging.Logger.manager.loggerDict, Logger.handlers,
      Logger.disabled) — aus dem CC-Prozess nicht erreichbar. Kein IPC in
      L2; L1-Analyse hat ergeben, dass kein Inbound-Kanal existiert.

    Class C — nicht implementiert
      • Add Handler / Remove Handler / Add Module / Log-File-Download
        (in `handlers/enhanced_logger_menu_handler.py` selbst nur
        Platzhalter ohne Funktion).

Keine Telegram-Abhängigkeit, keine FastAPI-Abhängigkeit — reine
Funktionen auf einem übergebenen `log_dir: Path`, identischer Stil wie
services/logs/reader.py. `get_log_file()` ruft ausschließlich
`reader.py::read_logs()` auf und baut keinen zweiten Parser.

Persistente Konfigurationsdatei (`data/module_logger_config.json`) wird
in L2 **bewusst NICHT exponiert** — L1-Analyse ergab: sie ist keine
verlässliche Runtime-Quelle (ModuleLoggerManager._load_module_configs()
wendet sie beim Bot-Start nicht auf die tatsächlichen Logger an); ein
Read-Endpoint würde eine Genauigkeit vortäuschen, die die Datenquelle
nicht hat. Siehe Audit-Doc für die vollständige Begründung.

Bekannter Kompromiss (nicht Teil dieses Slices): reader.py liest die
Logdatei via read_text() vollständig in den Speicher, bevor der
`limit`-Tail gebildet wird. Für die realen Dateigrößen (bot.log
typisch wenige MB) unkritisch; ein streaming-Tail wäre eine Änderung an
reader.py mit Auswirkung auf das bestehende `/api/v1/logs` und ist
daher explizit NICHT in L2 enthalten.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from services.logs.reader import list_log_sources, read_logs
from services.backup_admin import human_size

# Server-seitige Limit-Grenzen. Die HTTP-Schicht (FastAPI
# Query(ge=1, le=2000) im Router) erzwingt dieselben Werte — diese
# Konstanten existieren zusätzlich, damit die App-Layer-Funktion auch
# bei direkten Aufrufen (Tests, Skripte, künftige Consumer ohne
# HTTP-Durchlauf) nicht stillschweigend ein übergroßes Limit akzeptiert.
DEFAULT_LIMIT = 200
MIN_LIMIT = 1
MAX_LIMIT = 2000


def _validate_limit(limit: int) -> int:
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise InvalidLimitError(
            f"limit muss zwischen {MIN_LIMIT} und {MAX_LIMIT} liegen, "
            f"erhalten: {limit}"
        )
    return limit


class LoggerAdminError(Exception):
    """Basisklasse für Validierungsfehler dieses Moduls."""


class InvalidLogFilenameError(LoggerAdminError):
    """Der angeforderte Dateiname entspricht keinem Eintrag in log_dir
    (Whitelist-Abgleich fehlgeschlagen, identisch zur
    reader.py-Logik — hier im App-Layer zusätzlich als eigener Fehler
    typisiert, damit der Router 404 statt eines leeren 200 liefern kann)."""


class InvalidLimitError(LoggerAdminError):
    """Ein `limit` außerhalb [MIN_LIMIT, MAX_LIMIT] wurde übergeben.
    Bewusst ein *Fehler* statt eines stillen Clamps auf die Grenze —
    ein stillschweigend abgesenktes Limit würde dem Aufrufer eine
    unvollständige Antwort als vollständig präsentieren."""


@dataclass(frozen=True)
class LogFileMeta:
    """Reine Filesystem-Metadaten einer Logdatei — keine
    Runtime-/Prozess-Interpretation (Class A)."""

    name: str
    size_bytes: int
    modified_at: datetime


@dataclass(frozen=True)
class LogFileStats:
    """Aggregat über alle Logdateien in log_dir — nur aus
    Filesystem-Metadaten abgeleitet, nichts prozesslokales.

    `oldest_file`/`oldest_age_days` beziehen sich auf die **älteste
    Datei nach Dateisystem-mtime**, NICHT auf „die älteste Logmeldung"
    — die Logzeilen selbst enthalten im Root-Format (bot.log) kein
    Datum (siehe services/logs/reader.py-Docstring), eine Aussage über
    den ältesten Log-Eintrag ist aus den Daten nicht verlässlich
    ableitbar. Die Grenze ist bewusst nur die Datei-Ebene."""

    total_files: int
    total_size_bytes: int
    largest_file: Optional[str]
    largest_size_bytes: int
    oldest_file: Optional[str]
    oldest_age_days: int


def _is_within(path: Path, root: Path) -> bool:
    """Positiver Containment-Check, identisch zum bereits etablierten
    Muster in services/backup_admin.py::resolve_backup_path() und
    services/library_repair/maintenance_service.py::_resolve_within().
    Zweite Verteidigungslinie zusätzlich zum Whitelist-Abgleich gegen
    list_log_sources() (identisch zur reader.py-Konvention)."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _require_safe_name(log_dir: Path, name: str) -> None:
    """Wirft InvalidLogFilenameError, wenn `name` nicht in der
    tatsächlichen Logdatei-Whitelist steht. Zusätzlich Containment-Check
    als zweite Verteidigungslinie (Symlink-Erosion, absolute Pfade,
    `../`-Varianten)."""
    if not name or name not in list_log_sources(log_dir):
        raise InvalidLogFilenameError(f"Logdatei nicht gefunden: {name}")
    if not _is_within(log_dir / name, log_dir):
        raise InvalidLogFilenameError(f"Pfad außerhalb von {log_dir}: {name}")


def list_log_files(log_dir: Path) -> List[LogFileMeta]:
    """Alle tatsächlich vorhandenen Logdateien in log_dir, sortiert
    nach mtime (neueste zuerst) — identische Discovery wie
    services/logs/reader.py::list_log_sources() (glob `*.log*`, deckt
    aktuelle + rotierte + Modul-Dateien ab), hier zusätzlich mit
    stat()-Metadaten angereichert."""
    names = list_log_sources(log_dir)
    entries: List[LogFileMeta] = []
    for name in names:
        try:
            st = (log_dir / name).stat()
        except OSError:
            # Race mit Rotation zwischen glob() und stat() — Datei
            # weg, aber das darf die Liste nicht sprengen.
            continue
        entries.append(
            LogFileMeta(
                name=name,
                size_bytes=st.st_size,
                modified_at=datetime.fromtimestamp(st.st_mtime),
            )
        )
    entries.sort(key=lambda e: e.modified_at, reverse=True)
    return entries


def get_log_file_stats(log_dir: Path) -> LogFileStats:
    """Aggregat über alle Logdateien: Anzahl, Gesamtgröße, größte
    Datei, älteste Datei (nach mtime). Leere/fehlende log_dir liefert
    Nullwerte statt Fehler (identisches Prinzip wie reader.py)."""
    files = list_log_files(log_dir)
    if not files:
        return LogFileStats(
            total_files=0,
            total_size_bytes=0,
            largest_file=None,
            largest_size_bytes=0,
            oldest_file=None,
            oldest_age_days=0,
        )

    largest = max(files, key=lambda e: e.size_bytes)
    oldest = min(files, key=lambda e: e.modified_at)
    now = datetime.now()
    # tz-naive Zeitstempel (wie datetime.fromtimestamp() sie liefert) —
    # Differenz ohne tz-Bewusstsein, konsistent mit dem bestehenden
    # backup_admin.py- und enhanced_logger_menu_handler-Muster.
    age_days = max(0, int((now - oldest.modified_at).total_seconds() // 86400))

    return LogFileStats(
        total_files=len(files),
        total_size_bytes=sum(f.size_bytes for f in files),
        largest_file=largest.name,
        largest_size_bytes=largest.size_bytes,
        oldest_file=oldest.name,
        oldest_age_days=age_days,
    )


def get_log_file(
    log_dir: Path,
    *,
    name: str,
    default_source: str = "bot.log",
    level: Optional[str] = None,
    component: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Liest genau eine Logdatei (Whitelist-erzwungen) und liefert das
    bereits von services/logs/reader.py::read_logs() produzierte dict
    unverändert weiter — **kein zweiter Parser**, keine zweite
    Level-Filter-Logik, keine zweite Redaktionslogik.

    Der einzige Zusatz gegenüber reader.py: ein expliziter
    InvalidLogFilenameError statt eines stillen leeren Ergebnisses.
    """
    _validate_limit(limit)
    _require_safe_name(log_dir, name)
    return read_logs(
        log_dir,
        default_source=default_source,
        source=name,
        level=level,
        component=component,
        search=search,
        limit=limit,
    )


def human_size_str(size_bytes: int) -> str:
    """Thin wrapper — existiert, damit das Schema-Mapping an einer
    Stelle greift (statt backup_admin direkt in schemas/ zu importieren,
    was die Schichtentrennung schemas→services kippen würde)."""
    return human_size(size_bytes)
