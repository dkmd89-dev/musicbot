# services/system_status.py
# -*- coding: utf-8 -*-
"""
CC-AC-10D (Diagnostics & Monitoring) — System-Status für das Control
Center.

**Bewusst NICHT** ein Port von handlers/enhanced_status_handler.py::
SystemMonitor. Grund: Control Center läuft als eigener Prozess neben
bot.py (CLAUDE.md §4). SystemMonitor mischt zwei fundamental
unterschiedliche Datenarten:

1. Host-weite Metriken (CPU/RAM/Disk über psutil) — prozessunabhängig,
   aus JEDEM Prozess auf derselben Maschine identisch messbar.
2. Prozessinterne Zähler (operation_counts, cpu_history,
   process.cpu_percent() für den EIGENEN Prozess, Uptime seit
   SystemMonitor-Konstruktion) — nur im Bot-Prozess sinnvoll, für einen
   in Control Center instanzierten SystemMonitor wären das die
   *eigenen* Werte des Control-Center-Prozesses, fälschlich als
   Bot-Status dargestellt.

Dieses Modul liefert daher ausschließlich Kategorie 1 (echte Werte,
unabhängig davon wer sie misst) plus einen echten, nicht simulierten
"läuft der Bot-Service" -Check über systemd (subprocess, identisches
Prinzip wie utils/bot_restart_trigger.py — reine Abfrage, kein
Seiteneffekt). Kategorie 2 (Bot-eigene Laufzeit-Zähler) bleibt bewusst
außen vor — Nutzer-Entscheidung 2026-09-22 (siehe docs/FINDINGS_INDEX.md):
Logger-Konfiguration UND Error-Administration wurden aus demselben Grund
komplett aus CC-AC-10D zurückgestellt, dieses Modul vermeidet denselben
Fehler von vornherein statt ihn erst zu bauen und dann zu entdecken.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import psutil

from logger import get_module_logger

_logger = get_module_logger("SystemStatus")

_SYSTEMCTL_TIMEOUT_SECONDS = 5


@dataclass
class HostResources:
    cpu_percent: float
    cpu_count: int
    memory_percent: float
    memory_used_mb: float
    memory_total_mb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    # control_center_overview Phase 5B: Load Average + Swap
    load_avg_1: Optional[float] = None
    load_avg_5: Optional[float] = None
    load_avg_15: Optional[float] = None
    swap_percent: Optional[float] = None
    swap_used_gb: Optional[float] = None
    swap_total_gb: Optional[float] = None


def get_host_resources(disk_path: str) -> HostResources:
    """Sammelt Host-weite Ressourcenmetriken — identische psutil-Aufrufe
    wie SystemMonitor.get_system_metrics(), aber ohne dessen
    prozessinterne Historie/Zähler (siehe Modul-Docstring)."""
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(disk_path)

    # Load Average (nur Linux/Unix; auf Windows nicht verfügbar → None)
    load_avg_1 = load_avg_5 = load_avg_15 = None
    try:
        la = psutil.getloadavg()
        load_avg_1, load_avg_5, load_avg_15 = la
    except (AttributeError, OSError):
        pass

    # Swap (kann auf Systemen ohne Swap 0 sein — das ist ok)
    swap = psutil.swap_memory()

    return HostResources(
        cpu_percent=cpu_percent,
        cpu_count=psutil.cpu_count() or 0,
        memory_percent=memory.percent,
        memory_used_mb=memory.used / (1024 * 1024),
        memory_total_mb=memory.total / (1024 * 1024),
        disk_percent=disk.percent,
        disk_used_gb=disk.used / (1024**3),
        disk_total_gb=disk.total / (1024**3),
        load_avg_1=load_avg_1,
        load_avg_5=load_avg_5,
        load_avg_15=load_avg_15,
        swap_percent=swap.percent,
        swap_used_gb=swap.used / (1024**3),
        swap_total_gb=swap.total / (1024**3),
    )


def get_bot_service_active(service_name: str) -> Optional[bool]:
    """Echter, nicht simulierter `systemctl is-active <service>`-Check —
    True/False bei eindeutigem Ergebnis, None wenn systemctl selbst nicht
    verfügbar/aufrufbar ist (z. B. Nicht-systemd-Umgebung, Entwicklungs-
    Container) statt eines irreführenden False. Kein Seiteneffekt
    (reiner Status-Read, anders als
    utils/bot_restart_trigger.py::trigger_restart())."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True, text=True, timeout=_SYSTEMCTL_TIMEOUT_SECONDS,
        )
        return result.stdout.strip() == "active"
    except FileNotFoundError:
        _logger.debug("systemctl nicht verfügbar — Bot-Service-Status unbekannt")
        return None
    except subprocess.TimeoutExpired:
        _logger.warning(f"systemctl is-active {service_name} Timeout")
        return None
    except Exception as e:  # noqa: BLE001
        _logger.warning(f"Fehler beim Prüfen des Bot-Service-Status: {e!r}")
        return None


# ─────────────────────────────────────────────────────────────────────────
# Platform-Info + Bot-Service-Uptime (control_center_overview Phase 2)
# ─────────────────────────────────────────────────────────────────────────


def get_platform_info() -> dict:
    """Host-weite Platform-Informationen — prozessunabhängig, identisch
    aus jedem Prozess auf derselben Maschine messbar (Kategorie 1, siehe
    Modul-Docstring)."""
    return {
        "platform_os": platform.system(),
        "platform_release": platform.release(),
        "platform_python": platform.python_version(),
        "platform_arch": platform.machine(),
    }


def _format_uptime(seconds: int) -> str:
    """Kompakte Uptime-Darstellung „Xd Yh Zm" (Sekunden weggelassen, weil
    im Dashboard ständig wechselnd und ohne Kontextnutzen)."""
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    return f"{days}d {hours}h {minutes}m"


def get_bot_service_started_at(service_name: str) -> Optional[str]:
    """Liest ActiveEnterTimestamp aus systemctl — die Startzeit des
    BOT-SERVICES (systemd-Sicht), NICHT die Host-Bootzeit.

    Begründung: psutil.boot_time() wäre die Linux-Host-Laufzeit (z. B.
    „47d"), nicht die des MusicBots (z. B. „8h"). Der systemd-Wert ist
    semantisch korrekt und nutzt denselben Kanal wie
    get_bot_service_active().

    Rückgabe: ISO-String (lokale Systemzeit) oder None, wenn systemctl
    nicht verfügbar oder der Service nie gestartet wurde."""
    try:
        result = subprocess.run(
            [
                "systemctl", "show", service_name,
                "--property=ActiveEnterTimestamp", "--value",
            ],
            capture_output=True, text=True,
            timeout=_SYSTEMCTL_TIMEOUT_SECONDS,
        )
        value = result.stdout.strip()
        if not value:
            # Service existiert, wurde aber nie aktiviert (z. B.
            # "n/a" oder leer).
            return None
        # Format: "Thu 2026-09-22 15:32:56 CEST"
        # Wir nehmen nur Datum + Uhrzeit (Index 1 und 2), Zeitzone
        # wird ignoriert — lokale Server-Zeit ist die eine Wahrheit,
        # konsistent mit enhanced_status_handler.get_uptime().
        parts = value.split()
        if len(parts) < 3:
            _logger.debug(f"Unerwartetes ActiveEnterTimestamp-Format: {value!r}")
            return None
        dt = datetime.strptime(f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M:%S")
        return dt.isoformat()
    except FileNotFoundError:
        _logger.debug("systemctl nicht verfügbar — Bot-Service-Startzeit unbekannt")
        return None
    except subprocess.TimeoutExpired:
        _logger.warning(f"systemctl show {service_name} Timeout")
        return None
    except (ValueError, IndexError) as e:
        _logger.warning(f"ActiveEnterTimestamp nicht parsebar: {e!r}")
        return None
    except Exception as e:  # noqa: BLE001
        _logger.warning(f"Fehler beim Lesen der Bot-Service-Startzeit: {e!r}")
        return None


def get_bot_service_uptime(service_name: str) -> dict:
    """Kombiniert Startzeit + abgeleitete Uptime. Rückgabe-Dict enthält
    immer alle drei Schlüssel (Werte können None sein)."""
    started_at = get_bot_service_started_at(service_name)
    if not started_at:
        return {
            "bot_started_at": None,
            "bot_uptime_seconds": None,
            "bot_uptime_formatted": None,
        }
    try:
        start_dt = datetime.fromisoformat(started_at)
        delta = datetime.now() - start_dt
        seconds = max(0, int(delta.total_seconds()))
        return {
            "bot_started_at": started_at,
            "bot_uptime_seconds": seconds,
            "bot_uptime_formatted": _format_uptime(seconds),
        }
    except (ValueError, TypeError) as e:
        _logger.warning(f"Uptime-Berechnung fehlgeschlagen: {e!r}")
        return {
            "bot_started_at": started_at,
            "bot_uptime_seconds": None,
            "bot_uptime_formatted": None,
        }
