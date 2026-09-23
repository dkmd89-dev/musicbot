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

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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


# =====================================================================
# CC-LOGGER-L4 Stufe 1 — Persistente Logger-Konfiguration
# =====================================================================
#
# Dies ist ausschliesslich die *persistente* Konfiguration
# (data/module_logger_config.json). Sie ist keine Runtime-Wahrheit fuer
# den laufenden Bot-Prozess: Aenderungen werden erst beim naechsten
# Bot-Start wirksam (siehe docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_
# ARCHITECTURE_DECISION_2026-09-23.md). Der Application Layer bestaetigt
# nach einem Write ausdruecklich NICHT die Anwendung im laufenden
# Prozess.
#
# Bewusst NICHT Teil dieser API:
# - Globales Root-Log-Level (Config.LOG_LEVEL). Es existiert nur als
#   Config-Eigenschaft und wird von setup_enhanced_logging() direkt auf
#   den Root-Logger angewendet; es gibt keine Modul-Repraesentation in
#   der JSON. Eine globale Level-Aenderung waere eine Schemaerweiterung
#   (z.B. {"global": {...}, "modules": {...}}) — nicht Teil von L4.
# - `custom_format`: wird in der bestehenden Config zwar mitgeschrieben,
#   aber nirgends ausgewertet; aus dem Patch-Schema ausgeschlossen.

# Erlaubte Felder im PATCH-Body. Bewusst NICHT `custom_format`.
ALLOWED_PATCHABLE_FIELDS = frozenset(
    {"enabled", "level", "file_handler", "console_handler"}
)

# Gueltige Log-Level (identisch zur Whitelist in
# EnhancedLoggerMenuHandler.log_levels).
ALLOWED_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

# Pfad-Konvention: ueber Config.DATA_DIR (identisch zu services/
# user_data.py), NICHT relativ zum CWD. Der bestehende
# ModuleLoggerManager nutzt weiterhin seinen relativen Pfad — die
# Divergenz ist bewusst und im Audit-Dokument dokumentiert.
CONFIG_FILE_NAME = "module_logger_config.json"


class LoggerConfigError(LoggerAdminError):
    """Fehler aus der persistenten Logger-Konfiguration.

    Traegt einen stabilen `code`-String, den der Router auf HTTP-Codes
    mappt (`LOGGER_CONFIG_CORRUPT` -> 500, alle anderen -> 422).
    """

    code = "LOGGER_CONFIG_ERROR"

    def __init__(self, message: str, *, code: Optional[str] = None):
        super().__init__(message)
        if code is not None:
            self.code = code


def _resolve_config_path(config: Any) -> Path:
    """Fester, serverseitig aufgeloester Pfad zur Logger-Konfiguration.
    Kein Nutzer-Input fliesst ein — Path Traversal ist damit strukturell
    ausgeschlossen."""
    return Path(config.DATA_DIR) / CONFIG_FILE_NAME


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Atomares Schreiben ueber temp-Sibling + os.replace, identisches
    Muster wie services/backup_admin.py und services/logger_admin.py
    selbst fuer die (nicht-atomare) Modul-Config — hier explizit
    atomar, damit ein abgebrochener Write die Datei nicht halbfertig
    hinterlaesst."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(path)
    except OSError:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def read_logger_config(config: Any) -> Dict[str, Dict[str, Any]]:
    """Liest die persistente Logger-Konfiguration.

    Rueckgabe: dict {module_name: {enabled, level, file_handler,
    console_handler, custom_format}}. Fehlende Datei -> leeres dict
    (kein Fehler — die API meldet ehrlich „noch keine Konfiguration").
    Korruptes JSON oder Nicht-Objekt -> LoggerConfigError mit
    `code="LOGGER_CONFIG_CORRUPT"`.
    """
    path = _resolve_config_path(config)
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise LoggerConfigError(
            f"Logger-Konfiguration nicht lesbar: {e}",
            code="LOGGER_CONFIG_UNREADABLE",
        ) from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise LoggerConfigError(
            f"Logger-Konfiguration ist korruptes JSON: {e}",
            code="LOGGER_CONFIG_CORRUPT",
        ) from e
    if not isinstance(data, dict):
        raise LoggerConfigError(
            "Logger-Konfiguration ist kein JSON-Objekt.",
            code="LOGGER_CONFIG_CORRUPT",
        )
    return data


def validate_logger_config_patch(
    patch: Dict[str, Dict[str, Any]],
    *,
    existing_modules: set,
) -> None:
    """Validiert einen PATCH-Body gegen die bestehende Konfiguration.

    Regeln:
    - Patch muss ein Objekt sein.
    - Unbekannte Module -> Fehler (kein stilles Anlegen).
    - Unbekannte Felder -> Fehler (Whitelist, kein `custom_format`).
    - `level` muss in ALLOWED_LOG_LEVELS sein.
    - `enabled`/`file_handler`/`console_handler` muessen bool sein.
    """
    if not isinstance(patch, dict):
        raise LoggerConfigError(
            "Patch muss ein Objekt sein.", code="LOGGER_CONFIG_PATCH_INVALID"
        )
    for module_name, fields in patch.items():
        if not isinstance(module_name, str) or not module_name:
            raise LoggerConfigError(
                f"Modulname muss ein nicht-leerer String sein: {module_name!r}",
                code="LOGGER_CONFIG_PATCH_INVALID",
            )
        if module_name not in existing_modules:
            raise LoggerConfigError(
                f"Unbekanntes Modul im Patch: {module_name!r}. "
                "Neue Module koennen ueber diese API nicht angelegt werden.",
                code="LOGGER_CONFIG_UNKNOWN_MODULE",
            )
        if not isinstance(fields, dict):
            raise LoggerConfigError(
                f"Modul {module_name!r}: Wert muss ein Objekt sein.",
                code="LOGGER_CONFIG_PATCH_INVALID",
            )
        if not fields:
            raise LoggerConfigError(
                f"Modul {module_name!r}: keine Felder im Patch angegeben.",
                code="LOGGER_CONFIG_PATCH_INVALID",
            )
        for field, value in fields.items():
            if field not in ALLOWED_PATCHABLE_FIELDS:
                raise LoggerConfigError(
                    f"Modul {module_name!r}: unbekanntes Feld {field!r}. "
                    f"Erlaubt: {sorted(ALLOWED_PATCHABLE_FIELDS)}.",
                    code="LOGGER_CONFIG_UNKNOWN_FIELD",
                )
            if field == "level":
                if not isinstance(value, str) or value not in ALLOWED_LOG_LEVELS:
                    raise LoggerConfigError(
                        f"Modul {module_name!r}: ungueltiger Level {value!r}. "
                        f"Erlaubt: {sorted(ALLOWED_LOG_LEVELS)}.",
                        code="LOGGER_CONFIG_INVALID_LEVEL",
                    )
            else:  # enabled, file_handler, console_handler
                if not isinstance(value, bool):
                    raise LoggerConfigError(
                        f"Modul {module_name!r}: Feld {field!r} muss bool sein.",
                        code="LOGGER_CONFIG_INVALID_TYPE",
                    )


def update_logger_config(
    config: Any, patch: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Wendet einen validierten PATCH auf die persistente Konfiguration
    an und schreibt sie atomar.

    Semantik (identisch zur L3-Entscheidung):
    - **Merge-by-module, merge-by-field**: nur die im Patch genannten
      Module werden angefasst; innerhalb eines Moduls nur die im Patch
      genannten Felder. Andere Felder des Moduls bleiben unveraendert.
    - Kein Anlegen neuer Module (siehe validate_logger_config_patch).
    - Kein Runtime-Control: die Funktion liest und schreibt nur die
      Datei. Der laufende Bot-Prozess wird NICHT beeinflusst.

    Rueckgabe: die vollstaendige, aktualisierte Konfiguration (fuer den
    Response-Body).
    """
    path = _resolve_config_path(config)

    # 1. Bestehende Konfiguration lesen.
    # PATCH ist nur sinnvoll, wenn bereits eine persistente Konfiguration
    # existiert (die der Bot beim ersten Start generiert). Ohne sie gaebe
    # es keine "bekannten Module", gegen die der Patch validiert werden
    # koennte — ein 422 UNKNOWN_MODULE waere hier irrefuehrend.
    if not path.exists():
        raise LoggerConfigError(
            "Keine persistente Logger-Konfiguration vorhanden. "
            "Der Bot muss mindestens einmal gestartet worden sein, damit "
            "die Default-Konfiguration generiert wird.",
            code="LOGGER_CONFIG_MISSING",
        )
    current = read_logger_config(config)

    # 2. Validieren (gegen die tatsaechlich vorhandenen Module).
    validate_logger_config_patch(patch, existing_modules=set(current.keys()))

    # 3. Mergen.
    for module_name, fields in patch.items():
        # Modul existiert bereits (durch Validation garantiert).
        current[module_name].update(fields)

    # 4. Atomar schreiben.
    try:
        _atomic_write_json(path, current)
    except OSError as e:
        raise LoggerConfigError(
            f"Logger-Konfiguration konnte nicht geschrieben werden: {e}",
            code="LOGGER_CONFIG_WRITE_FAILED",
        ) from e

    return current
