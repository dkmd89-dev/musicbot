# handlers/enhanced_status_handler.py
# -*- coding: utf-8 -*-
"""
📊 ENHANCED STATUS HANDLER
Umfassende System-Status-Überwachung und -Anzeige für den Telegram Musik-Bot
Zeigt Echtzeit-Metriken, Performance-Daten und System-Gesundheit
"""

import psutil
import asyncio
import platform
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from collections import defaultdict, deque
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from config import Config
from logger import get_module_logger, get_logging_stats, _module_loggers
from services.clients.navidrome_api import NavidromeAPI


# ==================== TELEGRAM-RENDERING-ROBUSTHEIT ====================
# STATUS-MENU-CLOSURE: Dieses Modul rendert dynamische Systemwerte
# (platform.machine()="x86_64", Bibliothekspfade wie
# "/mnt/musik_bilder/library" usw.) direkt in mit parse_mode="Markdown"
# gesendeten Text. Telegrams Legacy-"Markdown"-Modus (NICHT "MarkdownV2")
# kennt nur 4 reservierte Sonderzeichen (_ * ` [) - ein einzelnes,
# unpaariges Vorkommen in dynamischen Daten (z.B. der Unterstrich in
# "x86_64" oder "musik_bilder") lässt Telegram mit "Can't parse entities:
# can't find end of the entity ..." ablehnen. Siehe
# docs/MusicBot_STATUS_MENU_CLOSURE.md für die vollständige Analyse.
_MARKDOWN_V1_SPECIAL_CHARS = ("_", "*", "`", "[")


def _escape_markdown(value: Any) -> str:
    """
    Escaped Telegrams Legacy-Markdown-Sonderzeichen (_ * ` [) in einem
    dynamischen Wert, BEVOR er in mit parse_mode="Markdown" gerenderten
    Text eingebettet wird. Nur für dynamische Werte verwenden - niemals
    für die statischen "**Überschrift**"-Markdown-Tokens selbst (die
    müssen unverändert funktionieren).

    Bewusst NICHT helfer/markdown_helfer.py::escape_md_v2() wiederverwendet:
    das ist für parse_mode="MarkdownV2" und escaped dort u. a. auch "."
    und "-" - unter dem hier verwendeten Legacy-"Markdown"-Modus wären
    diese zusätzlichen Escapes falsch und würden sichtbare Backslashes in
    Versions-/Pfadangaben erzeugen (z. B. "7\\.0\\.0" statt "7.0.0").
    """
    text = str(value)
    for char in _MARKDOWN_V1_SPECIAL_CHARS:
        text = text.replace(char, f"\\{char}")
    return text


def _is_message_not_modified_error(exc: Exception) -> bool:
    """
    Erkennt Telegrams Idempotenz-Fall: edit_message_text() wird mit
    exakt demselben Text/Keyboard erneut aufgerufen (z. B. "🔄
    Aktualisieren" ohne zwischenzeitliche Änderung der Werte). Das ist
    kein echter Fehler, siehe docs/MusicBot_STATUS_MENU_CLOSURE.md,
    Abschnitt "Message is not modified".
    """
    return isinstance(exc, TelegramError) and "message is not modified" in str(exc).lower()


def _find_partition_for_path(path: Path) -> Optional[Any]:
    """
    Ermittelt die psutil-Partition (Mountpoint/Dateisystemtyp), auf der
    `path` tatsächlich liegt - längster passender Mountpoint-Präfix
    (Standardtechnik, analog zu `df <pfad>`). Reine Read-Only-Abfrage
    von bereits vom Betriebssystem bereitgestellten Informationen, keine
    neue Datenquelle.
    """
    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = str(path)

    best_match = None
    best_len = -1
    for part in psutil.disk_partitions(all=False):
        if resolved.startswith(part.mountpoint) and len(part.mountpoint) > best_len:
            best_match = part
            best_len = len(part.mountpoint)
    return best_match


# STATUS-MENU-CLOSURE: nur Navidrome besitzt aktuell eine tatsächliche,
# read-only Konnektivitätsprüfung (NavidromeAPI.check_connection()).
# Fuer "download"/"statistics"/"logger" existiert keine analoge externe
# Health-Check-Funktion (es sind In-Prozess-Subsysteme ohne eigenen
# "erreichbar/nicht erreichbar"-Zustand) - bewusst nicht simuliert, um
# keine Fake-Daten zu erzeugen (siehe status_services_check/_detail in
# docs/MusicBot_STATUS_MENU_CLOSURE.md).
_SERVICES_WITH_AUTOMATED_CHECK = frozenset({"navidrome"})


class SystemMonitor:
    """
    🔍 SYSTEM MONITORING
    Überwacht System-Ressourcen und sammelt Performance-Metriken
    """

    def __init__(self, config: Config):
        self.config = config
        self.logger = get_module_logger("SystemMonitor")

        # Metriken-Geschichte (letzte 60 Messungen)
        self.cpu_history = deque(maxlen=60)
        self.memory_history = deque(maxlen=60)
        self.disk_history = deque(maxlen=60)

        # Start-Zeit für Uptime
        self.start_time = datetime.now()

        # Performance-Zähler
        self.operation_counts = defaultdict(int)
        self.error_counts = defaultdict(int)
        self.last_reset = datetime.now()

        self.logger.info("🔍 System Monitor initialisiert")

    def get_system_metrics(self) -> Dict[str, Any]:
        """Sammelt aktuelle System-Metriken"""
        try:
            # CPU-Nutzung
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count()
            cpu_freq = psutil.cpu_freq()

            self.cpu_history.append(cpu_percent)

            # Speicher-Nutzung
            memory = psutil.virtual_memory()
            self.memory_history.append(memory.percent)

            # Disk-Nutzung (für Base-Dir)
            disk = psutil.disk_usage(str(self.config.BASE_DIR))
            self.disk_history.append(disk.percent)

            # Netzwerk-IO
            net_io = psutil.net_io_counters()

            # Prozess-Informationen
            process = psutil.Process()
            process_memory = process.memory_info()
            process_cpu = process.cpu_percent(interval=0.1)

            return {
                "cpu": {
                    "current": cpu_percent,
                    "count": cpu_count,
                    "frequency": cpu_freq.current if cpu_freq else 0,
                    "max_frequency": cpu_freq.max if cpu_freq else 0,
                    "average": (
                        sum(self.cpu_history) / len(self.cpu_history)
                        if self.cpu_history
                        else 0
                    ),
                    "history": list(self.cpu_history),
                },
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "used": memory.used,
                    "percent": memory.percent,
                    "average": (
                        sum(self.memory_history) / len(self.memory_history)
                        if self.memory_history
                        else 0
                    ),
                    "history": list(self.memory_history),
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": disk.percent,
                    "average": (
                        sum(self.disk_history) / len(self.disk_history)
                        if self.disk_history
                        else 0
                    ),
                    "history": list(self.disk_history),
                },
                "network": {
                    "bytes_sent": net_io.bytes_sent,
                    "bytes_recv": net_io.bytes_recv,
                    "packets_sent": net_io.packets_sent,
                    "packets_recv": net_io.packets_recv,
                },
                "process": {
                    "memory_mb": process_memory.rss / (1024 * 1024),
                    "cpu_percent": process_cpu,
                    "threads": process.num_threads(),
                    "open_files": (
                        len(process.open_files())
                        if hasattr(process, "open_files")
                        else 0
                    ),
                },
            }
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Sammeln der System-Metriken: {e}")
            return {}

    def get_uptime(self) -> Dict[str, Any]:
        """Berechnet System-Uptime"""
        uptime = datetime.now() - self.start_time

        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        return {
            "total_seconds": uptime.total_seconds(),
            "days": days,
            "hours": hours,
            "minutes": minutes,
            "seconds": seconds,
            "formatted": f"{days}d {hours}h {minutes}m {seconds}s",
            "start_time": self.start_time.isoformat(),
        }

    def get_extended_system_info(self) -> Dict[str, Any]:
        """
        STATUS-MENU-CLOSURE (status_system_detail): zusätzliche, über
        das bereits verwendete psutil hinaus abrufbare Systemwerte, die
        get_system_metrics() bisher nicht exponiert - keine neue
        Datenquelle, nur zusätzliche Felder derselben Bibliothek.
        """
        try:
            swap = psutil.swap_memory()
            try:
                load_avg = psutil.getloadavg()
            except (AttributeError, OSError):
                # getloadavg() ist auf manchen Plattformen (u.a. Windows)
                # nicht verfügbar - kein Crash, nur leeres Ergebnis.
                load_avg = None

            return {
                "load_average": load_avg,
                "swap": {
                    "total": swap.total,
                    "used": swap.used,
                    "percent": swap.percent,
                },
                "cpu_per_core": psutil.cpu_percent(interval=0.1, percpu=True),
                "boot_time": datetime.fromtimestamp(psutil.boot_time()),
            }
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Sammeln der erweiterten System-Infos: {e}")
            return {}

    def get_history_summary(self) -> Dict[str, Any]:
        """
        STATUS-MENU-CLOSURE (status_trends): kompakte Trend-Zusammenfassung
        (aktuell/Durchschnitt/Min/Max) über die bereits gesammelten,
        prozessweiten CPU/RAM/Disk-Verlaufsdaten (letzte 60 Messungen seit
        Bot-Start, siehe cpu_history/memory_history/disk_history) - keine
        neue Persistenz, nur eine Auswertung der bereits vorhandenen,
        laufzeitgebundenen deques.
        """

        def _summary(history: deque) -> Dict[str, float]:
            values = list(history)
            if not values:
                return {"current": 0.0, "average": 0.0, "min": 0.0, "max": 0.0}
            return {
                "current": values[-1],
                "average": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
            }

        return {
            "cpu": _summary(self.cpu_history),
            "memory": _summary(self.memory_history),
            "disk": _summary(self.disk_history),
            "sample_count": len(self.cpu_history),
        }

    def record_operation(self, operation_type: str):
        """Zeichnet eine Operation auf"""
        self.operation_counts[operation_type] += 1

    def record_error(self, error_type: str):
        """Zeichnet einen Fehler auf"""
        self.error_counts[error_type] += 1

    def get_performance_stats(self) -> Dict[str, Any]:
        """Gibt Performance-Statistiken zurück"""
        runtime = (datetime.now() - self.last_reset).total_seconds()

        total_operations = sum(self.operation_counts.values())
        total_errors = sum(self.error_counts.values())

        return {
            "runtime_seconds": runtime,
            "total_operations": total_operations,
            "total_errors": total_errors,
            "operations_per_second": total_operations / max(runtime, 1),
            "error_rate": (total_errors / max(total_operations, 1)) * 100,
            "operation_breakdown": dict(self.operation_counts),
            "error_breakdown": dict(self.error_counts),
            "last_reset": self.last_reset.isoformat(),
        }

    def reset_statistics(self):
        """Setzt Performance-Statistiken zurück"""
        self.operation_counts.clear()
        self.error_counts.clear()
        self.last_reset = datetime.now()
        self.logger.info("📊 Performance-Statistiken zurückgesetzt")


class BotStatusTracker:
    """
    🤖 BOT STATUS TRACKING
    Überwacht Bot-spezifische Metriken und Zustände
    """

    def __init__(self, config: Config):
        self.config = config
        self.logger = get_module_logger("BotStatusTracker")

        # Handler-Status
        self.handler_status = {}
        self.active_sessions = {}

        # Service-Status
        self.services = {
            "download": {"status": "unknown", "last_check": None},
            "navidrome": {"status": "unknown", "last_check": None},
            "statistics": {"status": "unknown", "last_check": None},
            "logger": {"status": "unknown", "last_check": None},
        }

        # User-Aktivität
        self.active_users = set()
        self.user_activity_history = deque(maxlen=100)

        self.logger.info("🤖 Bot Status Tracker initialisiert")

    def update_handler_status(self, handler_name: str, status: str):
        """Aktualisiert Status eines Handlers"""
        self.handler_status[handler_name] = {
            "status": status,
            "last_update": datetime.now().isoformat(),
        }

    def update_service_status(
        self, service_name: str, status: str, reason: Optional[str] = None
    ):
        """
        Aktualisiert Status eines Services.

        `reason` (STATUS-MENU-CLOSURE Final Correction): optionaler,
        fachlicher Grund für den Status - insbesondere für "unknown",
        wenn kein automatisierter Health-Check existiert (z. B. "Kein
        automatisierter Health-Check verfügbar"). Wird bei jedem Aufruf
        vollständig neu gesetzt (kein Nachziehen eines veralteten Grundes
        aus einem früheren, unabhängigen Aufruf).
        """
        if service_name in self.services:
            self.services[service_name] = {
                "status": status,
                "last_check": datetime.now().isoformat(),
                "reason": reason,
            }

    def record_user_activity(self, user_id: int, activity_type: str):
        """Zeichnet User-Aktivität auf"""
        self.active_users.add(user_id)
        self.user_activity_history.append(
            {
                "user_id": user_id,
                "activity": activity_type,
                "timestamp": datetime.now().isoformat(),
            }
        )

    def get_handler_overview(self) -> Dict[str, Any]:
        """Gibt Handler-Übersicht zurück"""
        return {
            "total_handlers": len(self.handler_status),
            "active_handlers": sum(
                1 for h in self.handler_status.values() if h["status"] == "active"
            ),
            "handlers": self.handler_status,
        }

    def get_service_overview(self) -> Dict[str, Any]:
        """Gibt Service-Übersicht zurück"""
        return {
            "services": self.services,
            "healthy_services": sum(
                1 for s in self.services.values() if s["status"] == "healthy"
            ),
            "total_services": len(self.services),
        }

    def get_user_activity(self) -> Dict[str, Any]:
        """Gibt User-Aktivitäts-Statistiken zurück"""
        recent_activities = list(self.user_activity_history)[-20:]

        return {
            "active_users": len(self.active_users),
            "recent_activities": recent_activities,
            "total_recorded_activities": len(self.user_activity_history),
        }


class EnhancedStatusHandler:
    """
    📊 ENHANCED STATUS HANDLER
    Hauptklasse für Status-Anzeige und -Verwaltung
    """

    def __init__(self, config: Config, logger_factory=None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("EnhancedStatusHandler")

        # Sub-Systeme
        self.system_monitor = SystemMonitor(config)
        self.bot_tracker = BotStatusTracker(config)

        # Cache für UI-Performance
        self.status_cache = {}
        self.cache_ttl = 5  # 5 Sekunden Cache
        self.last_cache_update = None

        # Error Handler Referenz (wird extern gesetzt)
        self.error_handler = None

        self.logger.info("📊 Enhanced Status Handler initialisiert")

    # ==================== HAUPT-MENÜ ====================

    async def show_status_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        📊 Zeigt das Status-Hauptmenü
        """
        try:
            query = update.callback_query
            await query.answer()

            # Sammle Basis-Status-Informationen
            uptime = self.system_monitor.get_uptime()
            system_metrics = self.system_monitor.get_system_metrics()

            menu_text = f"""📊 **System Status**

⏱️ **Uptime:** {uptime['formatted']}
💻 **CPU:** {system_metrics['cpu']['current']:.1f}%
🧠 **RAM:** {system_metrics['memory']['percent']:.1f}%
💾 **Disk:** {system_metrics['disk']['percent']:.1f}%

📋 Wähle eine Kategorie für Details:"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💻 System", callback_data="status_system"
                        ),
                        InlineKeyboardButton("🤖 Bot", callback_data="status_bot"),
                    ],
                    [
                        InlineKeyboardButton(
                            "📦 Services", callback_data="status_services"
                        ),
                        InlineKeyboardButton("👥 Users", callback_data="status_users"),
                    ],
                    [
                        InlineKeyboardButton(
                            "📊 Performance", callback_data="status_performance"
                        ),
                        InlineKeyboardButton(
                            "📁 Storage", callback_data="status_storage"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_refresh"
                        ),
                        InlineKeyboardButton(
                            "📈 Trends", callback_data="status_trends"
                        ),
                    ],
                    [InlineKeyboardButton("🔙 Zurück", callback_data="menu:admin_group_diagnostics")],
                ]
            )

            await query.edit_message_text(
                menu_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📊 Status-Menü angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                # Identischer Refresh - kein echter Fehler (Telegram-
                # Idempotenz), siehe _is_message_not_modified_error().
                return
            self.logger.error(f"❌ Fehler beim Anzeigen des Status-Menüs: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "status_menu", e
                )

    async def show_users_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        👥 STATUS-MENU-CLOSURE (status_users): nutzt die bereits
        vorhandene, echte BotStatusTracker.get_user_activity() (befüllt
        über handlers/menu/activity_tracking.py::record_activity() bei
        jeder durchgelassenen Nutzer-Interaktion). Zeigt AUSSCHLIESSLICH
        aggregierte Zählwerte - explizit KEINE Telegram-User-IDs,
        Chat-IDs, Nachrichteninhalte oder sonstige PII (Master-Prompt
        Phase 7: "keine PII-Leaks, nicht anzeigen: Chat IDs, Telegram
        User IDs, Nachrichteninhalte, private Daten").
        """
        try:
            query = update.callback_query
            await query.answer("👥 Lade User-Aktivität...")

            activity = self.bot_tracker.get_user_activity()

            users_text = f"""👥 **User-Aktivität**

**Aktive User (seit Bot-Start):** {activity['active_users']}
**Aufgezeichnete Aktivitäten:** {activity['total_recorded_activities']}

_Nur aggregierte Zählwerte - keine User-IDs oder Nachrichteninhalte._"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_users"
                        ),
                        InlineKeyboardButton("🔙 Zurück", callback_data="status_menu"),
                    ],
                ]
            )

            await query.edit_message_text(
                users_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("👥 User-Aktivität angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler bei der User-Aktivität: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    async def show_trends(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        📈 STATUS-MENU-CLOSURE (status_trends): kompakte Trend-
        Zusammenfassung (aktuell/Durchschnitt/Min/Max) über
        SystemMonitor.get_history_summary() - dieselben bereits
        gesammelten CPU/RAM/Disk-Verlaufsdaten wie status_system_history,
        hier als abgeleitete Kennzahlen statt Rohwert-Sequenz. Bewusst
        System-Trends (CPU/RAM/Disk), nicht Musik-/Play-Trends - passend
        zu den übrigen Geschwister-Buttons im Status-Hauptmenü (System/
        Bot/Services/Performance/Storage sind ebenfalls System-Metriken,
        keine Navidrome-/Library-Domäne).
        """
        try:
            query = update.callback_query
            await query.answer("📈 Lade Trends...")

            summary = self.system_monitor.get_history_summary()

            def _line(label: str, data: dict) -> str:
                return (
                    f"**{label}:** {data['current']:.1f}% "
                    f"(Ø {data['average']:.1f}%, min {data['min']:.1f}%, max {data['max']:.1f}%)"
                )

            trends_text = f"""📈 **System-Trends**

{_line('CPU', summary['cpu'])}
{_line('RAM', summary['memory'])}
{_line('Disk', summary['disk'])}

_Basis: letzte {summary['sample_count']} Messungen seit Bot-Start._"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_trends"
                        ),
                        InlineKeyboardButton("🔙 Zurück", callback_data="status_menu"),
                    ],
                ]
            )

            await query.edit_message_text(
                trends_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📈 Trends angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler bei den Trends: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    # ==================== SYSTEM STATUS ====================

    async def show_system_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """💻 Zeigt detaillierten System-Status"""
        try:
            query = update.callback_query
            await query.answer("📊 Lade System-Status...")

            metrics = self.system_monitor.get_system_metrics()
            uptime = self.system_monitor.get_uptime()

            # System-Info
            # STATUS-MENU-CLOSURE: platform.machine() liefert auf x86_64-
            # Systemen woertlich "x86_64" - der darin enthaltene
            # Unterstrich brach bisher das Legacy-Markdown-Parsing
            # ("Can't parse entities: can't find end of the entity
            # starting at byte offset 108"). platform.release() (z.B.
            # Kernel-Build-Suffixe) ist ebenfalls extern/variabel - beide
            # sowie system()/python_version() werden defensiv escaped.
            os_name = _escape_markdown(platform.system())
            os_release = _escape_markdown(platform.release())
            python_version = _escape_markdown(platform.python_version())
            architecture = _escape_markdown(platform.machine())

            system_info = f"""💻 **System-Status**

**Platform:**
• OS: {os_name} {os_release}
• Python: {python_version}
• Architektur: {architecture}

**Uptime:**
• {uptime['formatted']}
• Gestartet: {datetime.fromisoformat(uptime['start_time']).strftime('%d.%m.%Y %H:%M:%S')}

**CPU:**
• Auslastung: {metrics['cpu']['current']:.1f}%
• Durchschnitt: {metrics['cpu']['average']:.1f}%
• Kerne: {metrics['cpu']['count']}
• Frequenz: {metrics['cpu']['frequency']:.0f} MHz

**Speicher:**
• Verwendet: {metrics['memory']['used'] / (1024**3):.1f} GB / {metrics['memory']['total'] / (1024**3):.1f} GB
• Auslastung: {metrics['memory']['percent']:.1f}%
• Verfügbar: {metrics['memory']['available'] / (1024**3):.1f} GB

**Festplatte:**
• Verwendet: {metrics['disk']['used'] / (1024**3):.1f} GB / {metrics['disk']['total'] / (1024**3):.1f} GB
• Auslastung: {metrics['disk']['percent']:.1f}%
• Frei: {metrics['disk']['free'] / (1024**3):.1f} GB

**Prozess:**
• RAM-Nutzung: {metrics['process']['memory_mb']:.1f} MB
• CPU: {metrics['process']['cpu_percent']:.1f}%
• Threads: {metrics['process']['threads']}"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📊 Detailliert", callback_data="status_system_detail"
                        ),
                        InlineKeyboardButton(
                            "📈 Verlauf", callback_data="status_system_history"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_system"
                        ),
                        InlineKeyboardButton("🔙 Zurück", callback_data="status_menu"),
                    ],
                ]
            )

            await query.edit_message_text(
                system_info, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("💻 System-Status angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler beim System-Status: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    async def show_system_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        📊 STATUS-MENU-CLOSURE (status_system_detail): zusätzliche
        Systemwerte über die bereits in show_system_status() gezeigten
        hinaus - Load Average, Swap, Pro-Kern-CPU-Auslastung, Boot-Zeit.
        Alle Werte kommen aus SystemMonitor.get_extended_system_info()
        (bereits importiertes psutil, keine neue Datenquelle).
        """
        try:
            query = update.callback_query
            await query.answer("📊 Lade Detail-Daten...")

            info = self.system_monitor.get_extended_system_info()

            load_avg = info.get("load_average")
            if load_avg:
                load_line = f"{load_avg[0]:.2f} / {load_avg[1]:.2f} / {load_avg[2]:.2f} (1/5/15 min)"
            else:
                load_line = "nicht verfügbar auf dieser Plattform"

            swap = info.get("swap", {})
            cpu_per_core = info.get("cpu_per_core", [])
            core_lines = "\n".join(
                f"  Kern {i}: {pct:.1f}%" for i, pct in enumerate(cpu_per_core)
            ) or "  nicht verfügbar"
            boot_time = info.get("boot_time")
            boot_line = (
                boot_time.strftime("%d.%m.%Y %H:%M:%S") if boot_time else "unbekannt"
            )

            detail_text = f"""📊 **System-Status — Detail**

**Load Average:**
• {load_line}

**Swap:**
• Verwendet: {swap.get('used', 0) / (1024**3):.1f} GB / {swap.get('total', 0) / (1024**3):.1f} GB
• Auslastung: {swap.get('percent', 0):.1f}%

**CPU pro Kern:**
{core_lines}

**System-Boot:**
• {boot_line}"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_system_detail"
                        ),
                        InlineKeyboardButton(
                            "🔙 Zurück", callback_data="status_system"
                        ),
                    ],
                ]
            )

            await query.edit_message_text(
                detail_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📊 System-Detail angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler beim System-Detail: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    async def show_system_history(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        📈 STATUS-MENU-CLOSURE Final Correction (status_system_history):
        rohe, zeitlich geordnete Folge der letzten aufgezeichneten
        CPU/RAM/Disk-Messungen (SystemMonitor.cpu_history/memory_history/
        disk_history - dieselbe Datenquelle wie status_trends, hier aber
        als Rohwerte statt als Min/Avg/Max-Zusammenfassung). Ausdrücklich
        "seit Bot-Start" (In-Memory, max. 60 Messwerte) - KEINE über
        Neustarts hinweg persistierte Historie, um keine
        Fake-Langzeit-History vorzutäuschen.

        WICHTIG (SAMPLING vs. HISTORY VIEW): diese Methode liest die
        bereits vorhandenen history-Deques DIREKT und ruft NICHT
        get_system_metrics() auf - jener ist die SAMPLING-Funktion, die
        als Seiteneffekt eine neue Messung an cpu_history/memory_history/
        disk_history anhängt. Würde diese Ansicht sie aufrufen, würde
        allein das Öffnen des Verlaufs künstlich eine neue Messung
        erzeugen (und eine leere Historie wäre nie wirklich leer). Ein
        reiner Anzeige-Vorgang darf keine neue Messung erzeugen.
        """
        try:
            query = update.callback_query
            await query.answer("📈 Lade Verlauf...")

            cpu_history = list(self.system_monitor.cpu_history)
            memory_history = list(self.system_monitor.memory_history)
            disk_history = list(self.system_monitor.disk_history)

            def _recent(values: list, count: int = 10) -> str:
                recent_values = values[-count:]
                if not recent_values:
                    return "  (noch keine Messungen)"
                return "  " + " → ".join(f"{v:.0f}%" for v in recent_values)

            if not cpu_history and not memory_history and not disk_history:
                history_text = """📈 **System-Verlauf**

Noch keine Messungen seit Bot-Start.

_Nur In-Memory seit Bot-Start (max. 60 Messungen), kein Langzeit-Archiv._"""
            else:
                history_text = f"""📈 **System-Verlauf** (letzte Messungen seit Bot-Start)

**CPU:**
{_recent(cpu_history)}

**RAM:**
{_recent(memory_history)}

**Festplatte:**
{_recent(disk_history)}

_Nur In-Memory seit Bot-Start (max. 60 Messungen), kein Langzeit-Archiv._"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_system_history"
                        ),
                        InlineKeyboardButton(
                            "🔙 Zurück", callback_data="status_system"
                        ),
                    ],
                ]
            )

            await query.edit_message_text(
                history_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📈 System-Verlauf angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler beim System-Verlauf: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    # ==================== BOT STATUS ====================

    async def show_bot_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """🤖 Zeigt Bot-Status"""
        try:
            query = update.callback_query
            await query.answer("🤖 Lade Bot-Status...")

            # Handler-Status
            handler_overview = self.bot_tracker.get_handler_overview()
            service_overview = self.bot_tracker.get_service_overview()
            user_activity = self.bot_tracker.get_user_activity()

            # Logger-Status
            # STATUS-MENU-CLOSURE (Deferred Finding aus der letzten Phase,
            # jetzt behoben): get_logging_stats() (ohne module-Argument)
            # liefert NIE einen Top-Level-Schluessel "total_logs" - nur
            # "total_modules"/"modules" (siehe logger.py::get_logging_stats()).
            # "Gesamt-Logs" zeigte dadurch strukturell immer 0. Fix: echte
            # Aggregation ueber die pro Modul bereits vorhandenen
            # get_stats()["total_logs"]-Werte (reine Zaehler, kein
            # Log-Inhalt, keine PII).
            logger_stats = get_logging_stats()
            active_modules = len(_module_loggers)
            total_logs = sum(
                module_stats.get("total_logs", 0)
                for module_stats in logger_stats.get("modules", {}).values()
            )

            bot_info = f"""🤖 **Bot-Status**

**Handler:**
• Gesamt: {handler_overview['total_handlers']}
• Aktiv: {handler_overview['active_handlers']}

**Services:**
• Gesund: {service_overview['healthy_services']}/{service_overview['total_services']}

**Logging:**
• Aktive Module: {active_modules}
• Gesamt-Logs: {total_logs:,}

**User-Aktivität:**
• Aktive Users: {user_activity['active_users']}
• Letzte Aktivitäten: {user_activity['total_recorded_activities']}

**Version:** {_escape_markdown(self.config.VERSION)}"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📦 Handler", callback_data="status_bot_handlers"
                        ),
                        InlineKeyboardButton(
                            "🔧 Services", callback_data="status_services"
                        ),
                    ],
                    [
                        InlineKeyboardButton("👥 Users", callback_data="status_users"),
                        InlineKeyboardButton(
                            "📝 Logs", callback_data="status_bot_logs"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_bot"
                        ),
                        InlineKeyboardButton("🔙 Zurück", callback_data="status_menu"),
                    ],
                ]
            )

            await query.edit_message_text(
                bot_info, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("🤖 Bot-Status angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler beim Bot-Status: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    async def show_bot_handlers(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        📦 STATUS-MENU-CLOSURE (status_bot_handlers): echte, bereits
        aufgezeichnete Handler-Konstruktionsstatus aus
        BotStatusTracker.get_handler_overview() - befüllt von
        RichMenuHandler._record_initial_handler_statuses() ("active" bei
        erfolgreicher Konstruktion, "error" wenn der jeweilige
        try/except-Block in initialize() fehlschlug). Keine erfundene
        Handler-Liste - real ca. 17 benannte Handler, daher keine
        "riesige Liste".
        """
        try:
            query = update.callback_query
            await query.answer("📦 Lade Handler-Übersicht...")

            overview = self.bot_tracker.get_handler_overview()
            handlers = overview.get("handlers", {})

            if not handlers:
                lines = "_Noch keine Handler-Status aufgezeichnet._"
            else:
                lines = "\n".join(
                    f"{'✅' if data['status'] == 'active' else '❌'} "
                    f"{_escape_markdown(name)}"
                    for name, data in sorted(handlers.items())
                )

            handlers_text = f"""📦 **Handler-Übersicht**

**Gesamt:** {overview['total_handlers']}  ·  **Aktiv:** {overview['active_handlers']}

{lines}"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_bot_handlers"
                        ),
                        InlineKeyboardButton("🔙 Zurück", callback_data="status_bot"),
                    ],
                ]
            )

            await query.edit_message_text(
                handlers_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📦 Handler-Übersicht angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler bei der Handler-Übersicht: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    async def show_bot_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        📝 STATUS-MENU-CLOSURE (status_bot_logs): reine Log-ZÄHLER pro
        Modul (debug/info/warning/error/critical), NICHT der Loginhalt
        selbst - siehe logger.py::ModuleLogger.get_stats(). Bewusst keine
        Logzeilen/-nachrichten (könnten Pfade/Nutzereingaben enthalten,
        siehe Master-Prompt: "keine vollständigen Logfiles ausgeben,
        keine Secrets/Tokens/Credentials/PII"). Top 5 Module nach
        Fehler-Anzahl (die für einen Admin relevanteste Sortierung).
        """
        try:
            query = update.callback_query
            await query.answer("📝 Lade Log-Statistiken...")

            logger_stats = get_logging_stats()
            modules = logger_stats.get("modules", {})

            total_logs = sum(m.get("total_logs", 0) for m in modules.values())
            total_errors = sum(
                m.get("error_count", 0) + m.get("critical_count", 0)
                for m in modules.values()
            )

            top_by_errors = sorted(
                modules.items(),
                key=lambda item: item[1].get("error_count", 0)
                + item[1].get("critical_count", 0),
                reverse=True,
            )[:5]

            top_lines = "\n".join(
                f"• {_escape_markdown(name)}: {data.get('error_count', 0)} ❌ / "
                f"{data.get('critical_count', 0)} 🚨"
                for name, data in top_by_errors
                if data.get("error_count", 0) + data.get("critical_count", 0) > 0
            ) or "_Keine Fehler/Kritisch-Einträge in einem der Module._"

            logs_text = f"""📝 **Log-Statistiken**

**Module:** {logger_stats.get('total_modules', 0)}
**Gesamt-Logs:** {total_logs:,}
**Fehler gesamt:** {total_errors:,}

**Top-Module nach Fehlern:**
{top_lines}"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_bot_logs"
                        ),
                        InlineKeyboardButton("🔙 Zurück", callback_data="status_bot"),
                    ],
                ]
            )

            await query.edit_message_text(
                logs_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📝 Log-Statistiken angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler bei den Log-Statistiken: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    # ==================== SERVICES STATUS ====================

    async def show_services_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """📦 Zeigt Service-Status"""
        try:
            query = update.callback_query
            await query.answer("📦 Lade Service-Status...")

            service_overview = self.bot_tracker.get_service_overview()

            services_text = "📦 **Service-Status**\n\n"

            for service_name, service_data in service_overview["services"].items():
                status = service_data["status"]

                # Status-Icon
                if status == "healthy":
                    icon = "✅"
                elif status == "warning":
                    icon = "⚠️"
                elif status == "error":
                    icon = "❌"
                else:
                    icon = "❓"

                last_check = service_data.get("last_check")
                check_time = ""
                if last_check:
                    check_dt = datetime.fromisoformat(last_check)
                    check_time = check_dt.strftime("%H:%M:%S")

                services_text += f"{icon} **{_escape_markdown(service_name.capitalize())}**\n"
                services_text += f"   Status: {_escape_markdown(status)}\n"
                if check_time:
                    services_text += f"   Geprüft: {check_time}\n"
                # STATUS-MENU-CLOSURE Final Correction: "reason" erklärt
                # ehrlich, WARUM ein Service "unknown" bleibt (z. B. kein
                # automatisierter Health-Check verfügbar) - siehe
                # show_services_check(). Nur angezeigt, wenn tatsächlich
                # gesetzt.
                reason = service_data.get("reason")
                if reason:
                    services_text += f"   Grund: {_escape_markdown(reason)}\n"
                services_text += "\n"

            services_text += f"**Zusammenfassung:**\n"
            services_text += f"• Gesund: {service_overview['healthy_services']}\n"
            services_text += f"• Gesamt: {service_overview['total_services']}"

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Services prüfen", callback_data="status_services_check"
                        ),
                        InlineKeyboardButton(
                            "📊 Details", callback_data="status_services_detail"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_services"
                        ),
                        InlineKeyboardButton("🔙 Zurück", callback_data="status_menu"),
                    ],
                ]
            )

            await query.edit_message_text(
                services_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📦 Service-Status angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler beim Service-Status: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    async def show_services_check(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        🔄 STATUS-MENU-CLOSURE Final Correction (status_services_check):
        tatsächlicher, read-only Verbindungstest - NICHT nur ein erneutes
        Rendern. Alle vier bekannten Services (download/navidrome/
        statistics/logger) werden hier explizit berücksichtigt - aber
        NICHT pauschal auf "healthy" gesetzt (keine Fake Health Checks:
        kein erfolgreicher Import, keine reine Konfigurationspräsenz und
        keine künstliche Dummy-Operation zählen hier als "gesund").

        Ausschließlich Navidrome besitzt aktuell einen echten,
        deterministischen Health-Check (NavidromeAPI.check_connection(),
        ein einzelner "ping"-Request, keine Mutation). Für "download"/
        "statistics"/"logger" existiert in der bestehenden Architektur
        kein analoger automatisierter Health-/Readiness-Check - sie
        bleiben deshalb ehrlich auf "unknown", mit einem konkreten,
        nachvollziehbaren Grund statt eines erfundenen Status.

        Fehlerisolation: jeder Service wird in einem eigenen try/except
        verarbeitet. Ein Fehler bei einem Service (z. B. Navidrome nicht
        erreichbar) verhindert nicht, dass die übrigen drei Services
        weiterhin verarbeitet werden.
        """
        _NO_AUTOMATED_CHECK_REASON = "Kein automatisierter Health-Check verfügbar"

        try:
            # Kein eigener query.answer() hier - show_services_status()
            # unten uebernimmt das (vermeidet einen doppelten
            # answerCallbackQuery()-Aufruf fuer denselben Callback).
            try:
                navidrome_ok = await NavidromeAPI().check_connection()
                self.bot_tracker.update_service_status(
                    "navidrome", "healthy" if navidrome_ok else "error"
                )
            except Exception as check_error:
                self.logger.warning(
                    f"⚠️ Navidrome-Check fehlgeschlagen: {check_error}"
                )
                self.bot_tracker.update_service_status("navidrome", "error")

            # download/statistics/logger: In-Prozess-Subsysteme ohne
            # externe Health-Check-Funktion. Jeder Service wird dennoch
            # explizit "betrachtet" (nicht stillschweigend ausgelassen) -
            # der Status bleibt aber ehrlich "unknown" mit Grund, statt
            # eines erfundenen "healthy".
            for service_name in ("download", "statistics", "logger"):
                try:
                    self.bot_tracker.update_service_status(
                        service_name, "unknown", reason=_NO_AUTOMATED_CHECK_REASON
                    )
                except Exception as service_error:
                    self.logger.warning(
                        f"⚠️ Service-Check für '{service_name}' fehlgeschlagen: "
                        f"{service_error}"
                    )

            # Nach dem Check dieselbe Darstellung wie show_services_status()
            # erneut rendern - kein Duplikat der Rendering-Logik.
            await self.show_services_status(update, context)

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler beim Service-Check: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    async def show_services_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        📊 STATUS-MENU-CLOSURE (status_services_detail): zeigt zusätzlich
        zum Status selbst, für welche Services überhaupt ein
        automatisierter Check existiert - echte, im Code verifizierbare
        Information (_SERVICES_WITH_AUTOMATED_CHECK), keine erfundene
        Zusatzansicht ohne neuen Informationsgehalt.
        """
        try:
            query = update.callback_query
            await query.answer("📊 Lade Service-Details...")

            service_overview = self.bot_tracker.get_service_overview()

            lines = []
            for service_name, service_data in service_overview["services"].items():
                has_check = service_name in _SERVICES_WITH_AUTOMATED_CHECK
                check_note = (
                    "automatisierter Check verfügbar"
                    if has_check
                    else "kein automatisierter Check definiert"
                )
                lines.append(
                    f"**{_escape_markdown(service_name.capitalize())}**\n"
                    f"   Status: {_escape_markdown(service_data['status'])}\n"
                    f"   {check_note}"
                )

            detail_text = "📊 **Service-Details**\n\n" + "\n\n".join(lines)

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Services prüfen", callback_data="status_services_check"
                        ),
                        InlineKeyboardButton(
                            "🔙 Zurück", callback_data="status_services"
                        ),
                    ],
                ]
            )

            await query.edit_message_text(
                detail_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📊 Service-Details angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler bei den Service-Details: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    # ==================== PERFORMANCE STATUS ====================

    async def show_performance_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """📊 Zeigt Performance-Status"""
        try:
            query = update.callback_query
            await query.answer("📊 Lade Performance-Daten...")

            perf_stats = self.system_monitor.get_performance_stats()

            runtime_hours = perf_stats["runtime_seconds"] / 3600

            perf_text = f"""📊 **Performance-Statistiken**

**Laufzeit:**
• {runtime_hours:.1f} Stunden
• Seit: {datetime.fromisoformat(perf_stats['last_reset']).strftime('%d.%m %H:%M:%S')}

**Operationen:**
• Gesamt: {perf_stats['total_operations']:,}
• Pro Sekunde: {perf_stats['operations_per_second']:.2f}

**Fehler:**
• Gesamt: {perf_stats['total_errors']:,}
• Fehlerrate: {perf_stats['error_rate']:.2f}%

**Top Operationen:**"""

            # Top 5 Operationen
            top_ops = sorted(
                perf_stats["operation_breakdown"].items(),
                key=lambda x: x[1],
                reverse=True,
            )[:5]

            if not top_ops:
                perf_text += "\n_Noch keine aufgezeichneten Operationen._"
            for op_type, count in top_ops:
                # op_type stammt aus record_operation()-Aufrufen - seit
                # STATUS-MENU-CLOSURE minimal instrumentiert in
                # handle_status_callback() (jeder status_*-Callback zaehlt
                # als eine Operation, siehe admin_diagnostics.py). Bewusst
                # escaped, da der Wert grundsaetzlich frei waehlbar ist
                # (Aufrufer koennten beliebige Strings uebergeben).
                perf_text += f"\n• {_escape_markdown(op_type)}: {count:,}"

            # STATUS-MENU-CLOSURE: "📈 Verlauf" (status_performance_history)
            # entfernt - es existiert keine über einzelne Resets/Neustarts
            # hinweg gespeicherte Performance-Historie (operation_counts/
            # error_counts sind reine seit-last_reset-Zähler ohne
            # Snapshot-Persistenz). Eine "Verlauf"-Ansicht hätte hier
            # zwangsläufig Fake-Daten zeigen müssen - Button daher bewusst
            # aus dem UI entfernt statt als Platzhalter geführt (siehe
            # docs/MusicBot_STATUS_MENU_CLOSURE.md, status_performance_history:
            # REMOVED).
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Reset", callback_data="status_performance_reset"
                        ),
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_performance"
                        ),
                    ],
                    [
                        InlineKeyboardButton("🔙 Zurück", callback_data="status_menu"),
                    ],
                ]
            )

            await query.edit_message_text(
                perf_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📊 Performance-Status angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler beim Performance-Status: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    async def show_performance_reset(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        🔄 STATUS-MENU-CLOSURE (status_performance_reset): nutzt die
        bereits vorhandene SystemMonitor.reset_statistics() (setzt
        operation_counts/error_counts/last_reset zurück - reine
        In-Memory-Zähler seit dem letzten Reset bzw. Bot-Start, keine
        permanenten/persistenten Daten). Bewusst OHNE separaten
        Bestätigungsschritt: der Callback ist bereits über
        RichMenuSystem._ADMIN_ONLY_PREFIXES ("status_") Admin-gated, und
        der Vorgang betrifft ausschließlich ephemere Analytics-Zähler
        (kein Datenverlust vergleichbar mit Library-/Backup-Löschungen -
        ein Bot-Neustart hätte denselben Effekt). Kein neuer
        Confirm-Callback/keine neue Architektur.
        """
        try:
            self.system_monitor.reset_statistics()
            self.logger.info("🔄 Performance-Statistiken auf Nutzeranfrage zurückgesetzt")

            # Nach dem Reset dieselbe Darstellung wie show_performance_status()
            # erneut rendern (zeigt jetzt die genullten Werte).
            await self.show_performance_status(update, context)

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler beim Performance-Reset: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    # ==================== STORAGE STATUS ====================

    async def show_storage_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """📁 Zeigt Storage-Status"""
        try:
            query = update.callback_query
            await query.answer("📁 Lade Storage-Status...")

            # Verzeichnis-Größen berechnen
            directories = {
                "Library": self.config.LIBRARY_DIR,
                "Downloads": self.config.DOWNLOAD_DIR,
                "Cache": self.config.DATA_DIR,
                "Logs": self.config.LOG_DIR,
            }

            # INV-01 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md, Abschnitt 27,
            # P1): rglob()+stat() ueber 5 Verzeichnisse inkl. LIBRARY_DIR -
            # real gemessen 9,46s allein fuer die Library dieser Umgebung.
            # Ohne run_in_executor() blockierte das den gesamten Event-Loop
            # fuer alle Telegram-Nutzer. Gleiches Muster wie
            # handlers/admin/backup_handler.py::_dir_size().
            storage_text = await asyncio.get_event_loop().run_in_executor(
                None, self._build_storage_report, directories
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🗑️ Cleanup", callback_data="status_storage_cleanup"
                        ),
                        InlineKeyboardButton(
                            "📊 Details", callback_data="status_storage_detail"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_storage"
                        ),
                        InlineKeyboardButton("🔙 Zurück", callback_data="status_menu"),
                    ],
                ]
            )

            await query.edit_message_text(
                storage_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📁 Storage-Status angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler beim Storage-Status: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    @staticmethod
    def _build_storage_report(directories: dict) -> str:
        """
        Sync-Kern von show_storage_status() - traversiert die uebergebenen
        Verzeichnisse (rglob+stat) und baut den fertigen Report-Text. Laeuft
        via run_in_executor() in einem Worker-Thread (INV-01, siehe Aufrufer).
        """
        storage_text = "📁 **Storage-Status**\n\n"
        total_used = 0

        for name, path in directories.items():
            try:
                if path.exists():
                    size = sum(
                        f.stat().st_size for f in path.rglob("*") if f.is_file()
                    )
                    size_gb = size / (1024**3)
                    total_used += size

                    # STATUS-MENU-CLOSURE: path ist ein realer Server-
                    # Dateisystempfad (Config.LIBRARY_DIR etc., z.B.
                    # "/mnt/musik_bilder/library") - der Unterstrich darin
                    # brach bisher das Legacy-Markdown-Parsing ("Can't
                    # parse entities ... byte offset 67"). name ist
                    # dagegen ein fixer, hier hartkodierter Schluessel
                    # ("Library"/"Downloads"/"Cache"/"Logs") und braucht
                    # kein Escaping.
                    storage_text += f"📦 **{name}:**\n"
                    storage_text += f"   {size_gb:.2f} GB\n"
                    storage_text += f"   {_escape_markdown(path)}\n\n"
                else:
                    storage_text += f"❌ **{name}:** Nicht gefunden\n\n"
            except Exception:
                storage_text += f"⚠️ **{name}:** Fehler beim Lesen\n\n"

        storage_text += f"**Gesamt verwendet:** {total_used / (1024**3):.2f} GB"
        return storage_text

    async def show_storage_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        📊 STATUS-MENU-CLOSURE (status_storage_detail): zusätzliche,
        reale Dateisystem-Informationen für das Library-Verzeichnis -
        Mountpoint, Dateisystemtyp, Gesamt-/freie Kapazität via bereits
        importiertem psutil (disk_partitions()/disk_usage()) - dieselbe
        Bibliothek, die SystemMonitor bereits für die Disk-Metriken
        verwendet, keine neue Datenquelle.
        """
        try:
            query = update.callback_query
            await query.answer("📊 Lade Storage-Details...")

            library_dir = self.config.LIBRARY_DIR
            partition = await asyncio.get_event_loop().run_in_executor(
                None, _find_partition_for_path, library_dir
            )

            if partition:
                usage = psutil.disk_usage(partition.mountpoint)
                detail_text = f"""📊 **Storage-Details — Library**

**Pfad:** {_escape_markdown(str(library_dir))}
**Mountpoint:** {_escape_markdown(partition.mountpoint)}
**Dateisystem:** {_escape_markdown(partition.fstype)}

**Kapazität:**
• Gesamt: {usage.total / (1024**3):.1f} GB
• Verwendet: {usage.used / (1024**3):.1f} GB ({usage.percent:.1f}%)
• Frei: {usage.free / (1024**3):.1f} GB"""
            else:
                detail_text = (
                    "📊 **Storage-Details — Library**\n\n"
                    f"**Pfad:** {_escape_markdown(str(library_dir))}\n\n"
                    "_Mountpoint konnte nicht ermittelt werden._"
                )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_storage_detail"
                        ),
                        InlineKeyboardButton(
                            "🔙 Zurück", callback_data="status_storage"
                        ),
                    ],
                ]
            )

            await query.edit_message_text(
                detail_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📊 Storage-Details angezeigt")

        except Exception as e:
            if _is_message_not_modified_error(e):
                return
            self.logger.error(f"❌ Fehler bei den Storage-Details: {e}")
            await self._show_error_message(update, f"Fehler beim Laden: {str(e)}")

    # ==================== UTILITY FUNCTIONS ====================

    async def _show_error_message(self, update: Update, error_message: str):
        """Zeigt Fehlermeldung"""
        try:
            query = update.callback_query

            # STATUS-MENU-CLOSURE: error_message enthaelt str(exception) -
            # beliebiger, nicht kontrollierbarer Text (z.B. Pfade in
            # OSError-Meldungen) - wird escaped, damit ein zufaelliges
            # Sonderzeichen in der Fehlermeldung nicht seinerseits das
            # Markdown-Parsing der Fehleranzeige selbst bricht.
            error_text = (
                f"❌ **Fehler**\n\n{_escape_markdown(error_message)}\n\nBitte versuche es erneut."
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Erneut versuchen", callback_data="status_menu"
                        ),
                        InlineKeyboardButton("🔙 Zurück", callback_data="menu:admin_group_diagnostics"),
                    ]
                ]
            )

            await query.edit_message_text(
                error_text, reply_markup=keyboard, parse_mode="Markdown"
            )
        except:
            pass

    async def cleanup(self):
        """Cleanup beim Beenden"""
        self.logger.info("🧹 Enhanced Status Handler Cleanup durchgeführt")


# ==================== FACTORY & INTEGRATION ====================


def create_enhanced_status_handler(
    config: Config, logger_factory=None
) -> EnhancedStatusHandler:
    """
    🏭 Factory-Funktion für Enhanced Status Handler
    """
    return EnhancedStatusHandler(config, logger_factory)


"""
📚 VERWENDUNGSBEISPIELE:

1. INITIALISIERUNG:
```python
from handlers.enhanced_status_handler import create_enhanced_status_handler

# Status Handler erstellen
status_handler = create_enhanced_status_handler(config)

# In RichMenuHandler integrieren
rich_menu_handler.set_status_handler(status_handler)
```

2. MANUELLE STATUS-UPDATES:
```python
# Service-Status aktualisieren
status_handler.bot_tracker.update_service_status("download", "healthy")

# Operation aufzeichnen
status_handler.system_monitor.record_operation("download_completed")

# Fehler aufzeichnen
status_handler.system_monitor.record_error("network_timeout")
```

3. METRIKEN ABRUFEN:
```python
# System-Metriken
metrics = status_handler.system_monitor.get_system_metrics()
print(f"CPU: {metrics['cpu']['current']}%")

# Performance-Stats
perf = status_handler.system_monitor.get_performance_stats()
print(f"Operations/s: {perf['operations_per_second']}")
```

✨ FEATURES:

✅ Echtzeit System-Monitoring (CPU, RAM, Disk, Network)
✅ Bot-Status-Tracking (Handler, Services, Users)
✅ Performance-Metriken und Statistiken
✅ Storage-Überwachung
✅ Service-Health-Checks
✅ User-Aktivitäts-Tracking
✅ Historische Daten (letzte 60 Messungen)
✅ Uptime-Tracking
✅ Error-Rate-Monitoring
✅ Integration mit Error Handler
✅ Cache für Performance
✅ Vollständige Menu-Integration (siehe docs/MusicBot_STATUS_MENU_CLOSURE.md
   für die vollständige Callback-Matrix - alle Callbacks IMPLEMENTED,
   REMOVED oder UNAVAILABLE_BY_DESIGN, keine unklaren/erreichbaren
   Zustände)

🎨 MENU-STRUKTUR (STATUS-MENU-CLOSURE):

Status-Hauptmenü
├── 💻 System Status                       [aktiv]
│   ├── Detaillierte Ansicht (Load/Swap/Kerne)  [aktiv]
│   └── Verlauf (letzte Messungen)              [aktiv]
├── 🤖 Bot Status                          [aktiv]
│   ├── Handler-Übersicht                       [aktiv]
│   ├── Service-Details → 📦 Services           [aktiv, selber Screen]
│   └── Log-Statistiken                         [aktiv]
├── 📦 Services                            [aktiv]
│   ├── Services prüfen (Navidrome-Ping)         [aktiv]
│   └── Service-Details (Check-Verfügbarkeit)    [aktiv]
├── 👥 User-Aktivität                      [aktiv]
├── 📊 Performance                         [aktiv]
│   └── Reset                                    [aktiv]
│   (kein "Verlauf"-Button mehr - keine über Neustarts hinweg
│    gespeicherte Performance-Historie vorhanden, siehe Closure-Doku)
├── 📁 Storage                             [aktiv]
│   ├── Details (Mountpoint/Dateisystem/Kapazität) [aktiv]
│   └── Cleanup                             [UNAVAILABLE_BY_DESIGN -
│                                             destruktive Aktion ohne
│                                             definierten Contract,
│                                             bewusst nicht implementiert]
└── 📈 Trends (CPU/RAM/Disk Min/Avg/Max)   [aktiv]

Alle [aktiv]-Einträge nutzen ausschließlich bereits vorhandene
Datenquellen (SystemMonitor/BotStatusTracker/get_logging_stats()/
NavidromeAPI.check_connection()/psutil) - keine Fake-Daten, keine
Fake-History, keine Fake-Trends. Vollständige Fall-Entscheidung je
Callback in docs/MusicBot_STATUS_MENU_CLOSURE.md.
"""
