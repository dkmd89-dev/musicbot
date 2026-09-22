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

import subprocess
from dataclasses import dataclass
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


def get_host_resources(disk_path: str) -> HostResources:
    """Sammelt Host-weite Ressourcenmetriken — identische psutil-Aufrufe
    wie SystemMonitor.get_system_metrics(), aber ohne dessen
    prozessinterne Historie/Zähler (siehe Modul-Docstring)."""
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(disk_path)

    return HostResources(
        cpu_percent=cpu_percent,
        cpu_count=psutil.cpu_count() or 0,
        memory_percent=memory.percent,
        memory_used_mb=memory.used / (1024 * 1024),
        memory_total_mb=memory.total / (1024 * 1024),
        disk_percent=disk.percent,
        disk_used_gb=disk.used / (1024**3),
        disk_total_gb=disk.total / (1024**3),
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
