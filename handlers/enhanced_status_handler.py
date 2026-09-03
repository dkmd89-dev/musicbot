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

    def update_service_status(self, service_name: str, status: str):
        """Aktualisiert Status eines Services"""
        if service_name in self.services:
            self.services[service_name] = {
                "status": status,
                "last_check": datetime.now().isoformat(),
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
                    [InlineKeyboardButton("🔙 Zurück", callback_data="menu:admin")],
                ]
            )

            await query.edit_message_text(
                menu_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📊 Status-Menü angezeigt")

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Anzeigen des Status-Menüs: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "status_menu", e
                )

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
            system_info = f"""💻 **System-Status**

**Platform:**
• OS: {platform.system()} {platform.release()}
• Python: {platform.python_version()}
• Architektur: {platform.machine()}

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
            self.logger.error(f"❌ Fehler beim System-Status: {e}")
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
            logger_stats = get_logging_stats()
            active_modules = len(_module_loggers)

            bot_info = f"""🤖 **Bot-Status**

**Handler:**
• Gesamt: {handler_overview['total_handlers']}
• Aktiv: {handler_overview['active_handlers']}

**Services:**
• Gesund: {service_overview['healthy_services']}/{service_overview['total_services']}

**Logging:**
• Aktive Module: {active_modules}
• Gesamt-Logs: {logger_stats.get('total_logs', 0):,}

**User-Aktivität:**
• Aktive Users: {user_activity['active_users']}
• Letzte Aktivitäten: {user_activity['total_recorded_activities']}

**Version:** {self.config.VERSION}"""

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
            self.logger.error(f"❌ Fehler beim Bot-Status: {e}")
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

                services_text += f"{icon} **{service_name.capitalize()}**\n"
                services_text += f"   Status: {status}\n"
                if check_time:
                    services_text += f"   Geprüft: {check_time}\n"
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
            self.logger.error(f"❌ Fehler beim Service-Status: {e}")
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

            for op_type, count in top_ops:
                perf_text += f"\n• {op_type}: {count:,}"

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📈 Verlauf", callback_data="status_performance_history"
                        ),
                        InlineKeyboardButton(
                            "🔄 Reset", callback_data="status_performance_reset"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="status_performance"
                        ),
                        InlineKeyboardButton("🔙 Zurück", callback_data="status_menu"),
                    ],
                ]
            )

            await query.edit_message_text(
                perf_text, reply_markup=keyboard, parse_mode="Markdown"
            )

            self.logger.info("📊 Performance-Status angezeigt")

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Performance-Status: {e}")
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

                    storage_text += f"📦 **{name}:**\n"
                    storage_text += f"   {size_gb:.2f} GB\n"
                    storage_text += f"   {path}\n\n"
                else:
                    storage_text += f"❌ **{name}:** Nicht gefunden\n\n"
            except Exception:
                storage_text += f"⚠️ **{name}:** Fehler beim Lesen\n\n"

        storage_text += f"**Gesamt verwendet:** {total_used / (1024**3):.2f} GB"
        return storage_text

    # ==================== UTILITY FUNCTIONS ====================

    async def _show_error_message(self, update: Update, error_message: str):
        """Zeigt Fehlermeldung"""
        try:
            query = update.callback_query

            error_text = (
                f"❌ **Fehler**\n\n{error_message}\n\nBitte versuche es erneut."
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Erneut versuchen", callback_data="status_menu"
                        ),
                        InlineKeyboardButton("🔙 Zurück", callback_data="menu:admin"),
                    ]
                ]
            )

            await query.edit_message_text(
                error_text, reply_markup=keyboard, parse_mode="Markdown"
            )
        except:
            pass

    def format_bytes(self, bytes_value: int) -> str:
        """Formatiert Byte-Werte lesbar"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_value < 1024.0:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.2f} PB"

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


def integrate_status_handler(
    menu_system, status_handler: EnhancedStatusHandler
) -> bool:
    """
    🔗 Integriert Status Handler in Menu System
    """
    try:
        # Setze Status Handler im Menu System
        if hasattr(menu_system, "set_status_handler"):
            menu_system.set_status_handler(status_handler)

        print("✅ Enhanced Status Handler erfolgreich integriert")
        return True

    except Exception as e:
        print(f"❌ Fehler bei Integration des Status Handlers: {e}")
        return False


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
✅ Vollständige Menu-Integration

🎨 MENU-STRUKTUR:

Status-Hauptmenü
├── 💻 System Status
│   ├── Detaillierte Ansicht
│   └── Verlaufs-Diagramm
├── 🤖 Bot Status
│   ├── Handler-Übersicht
│   ├── Service-Details
│   └── Log-Statistiken
├── 📦 Services
│   ├── Health-Checks
│   └── Service-Details
├── 👥 User-Aktivität
├── 📊 Performance
│   ├── Operations-Breakdown
│   └── Error-Analyse
├── 📁 Storage
│   ├── Verzeichnis-Übersicht
│   └── Cleanup-Optionen
└── 📈 Trends
"""
