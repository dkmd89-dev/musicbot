# services/status_service.py

import psutil
import platform
import asyncio
from datetime import datetime

# --- Globale Statusvariablen ---
_start_time = datetime.now()
_commands_processed = 0
# Ein Set ist ideal, um User über einen Zeitraum einzigartig zu zählen
_active_users_set = set()


# --- Funktionen zur Aktualisierung der Zähler ---
# Diese werden vom status_handler aufgerufen


def increment_commands_processed():
    """Erhöht den Zähler für verarbeitete Befehle."""
    global _commands_processed
    _commands_processed += 1


def add_active_user(user_id: int):
    """Fügt einen User zur Liste der aktiven User für diese Sitzung hinzu."""
    global _active_users_set
    _active_users_set.add(user_id)


# --- Hauptfunktion zum Sammeln der Statusdaten ---


async def get_status():
    """
    Sammelt und gibt einen detaillierten Bot-Status als Dictionary zurück.
    """
    global _start_time, _commands_processed

    # Uptime berechnen
    uptime = datetime.now() - _start_time
    uptime_str = str(uptime).split(".")[0]

    # Systeminformationen mit psutil sammeln
    memory_info = psutil.virtual_memory()
    cpu_usage = psutil.cpu_percent(interval=None)

    # Korrekte Festplattennutzung für das Root-Verzeichnis
    try:
        disk_info = psutil.disk_usage("/")
        disk_usage_str = (
            f"{disk_info.percent}% ({disk_info.free / (1024**3):.2f} GB frei)"
        )
    except FileNotFoundError:
        disk_usage_str = "N/A"

    # Alle Daten in einem Dictionary für die Handler zusammenstellen
    status_data = {
        "active_users": len(_active_users_set),
        "uptime": uptime_str,
        "commands_processed": _commands_processed,
        "memory_usage": f"{memory_info.percent}% ({memory_info.used / (1024**3):.2f} GB)",
        "cpu_usage": f"{cpu_usage}",
        "disk_usage": disk_usage_str,
        "python_version": platform.python_version(),
        "server_name": platform.node(),
        "last_restart": _start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.2.0",  # Du kannst deine Bot-Version hier festlegen
        # Weitere Platzhalter für detaillierte Berichte
        "bot_id": "N/A",
        "dependency_count": "N/A",
        "api_calls_today": "N/A",
        "errors_24h": "N/A",
        "auto_restart": True,
        "avg_response_time": "N/A",
    }

    return status_data


# --- Optionaler Hintergrund-Task (bereinigt) ---


async def status_update_task():
    """Ein Hintergrund-Task, der regelmäßig Status-Logs ausgibt."""
    while True:
        # Alle 5 Minuten (300 Sekunden) warten
        await asyncio.sleep(300)

        # In dieser Version gibt der Task keine Logs mehr aus.
        # Er wartet nur noch und kann später für andere Zwecke genutzt werden.
