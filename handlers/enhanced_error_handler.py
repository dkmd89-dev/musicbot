# handlers/enhanced_error_handler.py
# -*- coding: utf-8 -*-
"""
🚨 ERWEITERTE ERROR HANDLER
Umfassendes Error Handling für alle Arten von Exceptions mit detailliertem Logging,
Monitoring und Recovery-Mechanismen. Erweitert um DEBUG-Information und transparente
Step-by-Step Nachverfolgung mit Emojis.
"""

import traceback
import sys
import asyncio
import inspect
import threading
from typing import Dict, Any, Optional, Callable, List, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from collections import defaultdict, deque

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore
from telegram.error import TelegramError, NetworkError, TimedOut, BadRequest  # type: ignore

from config import Config
from logger import get_module_logger


class ExceptionMonitor:
    """
    🔍 EXCEPTION MONITORING SYSTEM
    Überwacht und kategorisiert alle Exceptions im System
    """

    def __init__(self, max_history: int = 1000):
        self.logger = get_module_logger("ExceptionMonitor")
        self.max_history = max_history

        # Exception Historie
        self.exception_history = deque(maxlen=max_history)

        # Kategorisierung
        self.categories = {
            "telegram": [TelegramError, NetworkError, TimedOut, BadRequest],
            "file_system": [FileNotFoundError, PermissionError, OSError, IOError],
            "network": [ConnectionError, TimeoutError, OSError],
            "parsing": [ValueError, KeyError, TypeError, AttributeError],
            "memory": [MemoryError, OverflowError],
            "runtime": [RuntimeError, SystemError],
            "import": [ImportError, ModuleNotFoundError],
            "authentication": [PermissionError],
            "data": [ValueError, KeyError, IndexError],
            "async": [asyncio.TimeoutError, asyncio.CancelledError],
        }

        # Statistiken
        self.stats = {
            "total_exceptions": 0,
            "by_category": defaultdict(int),
            "by_type": defaultdict(int),
            "by_module": defaultdict(int),
            "by_severity": defaultdict(int),
            "hourly_counts": defaultdict(int),
            "patterns": defaultdict(int),
        }

        # Thread-Lock für Thread-Safe Operations
        self._lock = threading.Lock()

        self.logger.info("🔍 Exception Monitor initialisiert")

    def categorize_exception(self, exception: Exception) -> str:
        """Kategorisiert eine Exception"""
        exc_type = type(exception)

        for category, types in self.categories.items():
            if any(issubclass(exc_type, t) for t in types):
                return category

        return "unknown"

    def determine_severity(self, exception: Exception, context: Dict[str, Any]) -> str:
        """Bestimmt die Schwere einer Exception"""
        exc_type = type(exception)

        # Kritische Exceptions
        critical_types = [MemoryError, SystemError, KeyboardInterrupt]
        if any(issubclass(exc_type, t) for t in critical_types):
            return "critical"

        # Error-Level
        error_types = [
            FileNotFoundError,
            PermissionError,
            ConnectionError,
            ImportError,
            RuntimeError,
        ]
        if any(issubclass(exc_type, t) for t in error_types):
            return "error"

        # Warning-Level
        warning_types = [
            TimeoutError,
            ValueError,
            KeyError,
            AttributeError,
            TimedOut,
            NetworkError,
        ]
        if any(issubclass(exc_type, t) for t in warning_types):
            return "warning"

        # Info-Level für bekannte, handhabbare Exceptions
        info_types = [BadRequest]
        if any(issubclass(exc_type, t) for t in info_types):
            return "info"

        return "error"  # Default

    def record_exception(
        self,
        exception: Exception,
        context: Dict[str, Any],
        stack_trace: List[str] = None,
    ) -> str:
        """Zeichnet eine Exception auf und gibt eine ID zurück"""
        with self._lock:
            timestamp = datetime.now()
            exc_id = f"EXC_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}"

            category = self.categorize_exception(exception)
            severity = self.determine_severity(exception, context)
            exc_type = type(exception).__name__

            # Exception-Record
            record = {
                "id": exc_id,
                "timestamp": timestamp.isoformat(),
                "type": exc_type,
                "category": category,
                "severity": severity,
                "message": str(exception),
                "context": context,
                "stack_trace": stack_trace or traceback.format_exc().split("\n"),
                "thread_id": threading.current_thread().ident,
                "thread_name": threading.current_thread().name,
            }

            # Zur Historie hinzufügen
            self.exception_history.append(record)

            # Statistiken aktualisieren
            self.stats["total_exceptions"] += 1
            self.stats["by_category"][category] += 1
            self.stats["by_type"][exc_type] += 1
            self.stats["by_severity"][severity] += 1
            self.stats["hourly_counts"][timestamp.strftime("%H")] += 1

            if "module" in context:
                self.stats["by_module"][context["module"]] += 1

            # Pattern-Erkennung
            pattern = f"{exc_type}:{category}"
            self.stats["patterns"][pattern] += 1

            return exc_id

    def get_recent_exceptions(self, count: int = 10) -> List[Dict[str, Any]]:
        """Gibt die letzten N Exceptions zurück"""
        with self._lock:
            return list(self.exception_history)[-count:]

    def get_statistics(self) -> Dict[str, Any]:
        """Gibt umfassende Statistiken zurück"""
        with self._lock:
            return dict(self.stats)


class DebugTracker:
    """
    🐛 DEBUG INFORMATION TRACKER
    Sammelt und verwaltet Debug-Informationen mit Step-by-Step Verfolgung
    """

    def __init__(self, max_sessions: int = 100):
        self.logger = get_module_logger("DebugTracker")
        self.max_sessions = max_sessions

        # Debug-Sessions
        self.sessions = {}
        self.session_history = deque(maxlen=max_sessions)

        # Step-Counter
        self.global_step_counter = 0

        self.logger.info("🐛 Debug Tracker initialisiert")

    def start_session(self, session_id: str, context: Dict[str, Any]) -> None:
        """Startet eine neue Debug-Session"""
        session = {
            "id": session_id,
            "start_time": datetime.now(),
            "context": context,
            "steps": [],
            "status": "active",
            "metadata": {},
        }

        self.sessions[session_id] = session
        self.logger.debug(f"🎯 Debug-Session gestartet: {session_id}")

    def log_step(
        self,
        session_id: str,
        step_name: str,
        details: Dict[str, Any] = None,
        emoji: str = "📝",
    ) -> int:
        """Loggt einen Debug-Step"""
        if session_id not in self.sessions:
            self.start_session(session_id, {"auto_created": True})

        session = self.sessions[session_id]
        self.global_step_counter += 1

        step = {
            "step_id": self.global_step_counter,
            "timestamp": datetime.now().isoformat(),
            "name": step_name,
            "details": details or {},
            "emoji": emoji,
        }

        session["steps"].append(step)

        # Log ausgeben
        detail_str = f" | {details}" if details else ""
        self.logger.debug(
            f"🔸 Step {self.global_step_counter}: {emoji} {step_name}{detail_str}"
        )

        return self.global_step_counter

    def end_session(self, session_id: str, status: str = "completed") -> None:
        """Beendet eine Debug-Session"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session["status"] = status
            session["end_time"] = datetime.now()
            session["duration"] = (
                session["end_time"] - session["start_time"]
            ).total_seconds()

            # Zur Historie hinzufügen
            self.session_history.append(session.copy())

            # Aus aktiven Sessions entfernen
            del self.sessions[session_id]

            self.logger.debug(
                f"✅ Debug-Session beendet: {session_id} "
                f"({len(session['steps'])} Steps, {session['duration']:.2f}s)"
            )

    def get_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Gibt eine Zusammenfassung einer Session zurück"""
        session = self.sessions.get(session_id)
        if not session:
            # Suche in Historie
            for hist_session in self.session_history:
                if hist_session["id"] == session_id:
                    session = hist_session
                    break

        if not session:
            return None

        return {
            "id": session["id"],
            "status": session["status"],
            "step_count": len(session["steps"]),
            "start_time": session["start_time"],
            "duration": session.get(
                "duration", (datetime.now() - session["start_time"]).total_seconds()
            ),
            "recent_steps": session["steps"][-5:] if session["steps"] else [],
        }


class EnhancedErrorHandler:
    """
    🚨 ERWEITERTE ERROR HANDLER
    Umfassendes Error Handling mit transparentem Step-by-Step Logging
    """

    async def handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """
        🔄 Kompatibilitäts-Wrapper für alte Schnittstellen.
        Leitet direkt an handle_telegram_error weiter.
        """
        await self.handle_telegram_error(update, context)

    def __init__(self, config: Config, logger_factory: Callable = None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("EnhancedErrorHandler")
        ...

    def __init__(self, config: Config, logger_factory: Callable = None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("EnhancedErrorHandler")

        # Sub-Systeme
        self.exception_monitor = ExceptionMonitor()
        self.debug_tracker = DebugTracker()

        # Konfiguration
        self.debug_mode = getattr(config, "DEBUG_MODE", True)
        self.log_all_exceptions = getattr(config, "LOG_ALL_EXCEPTIONS", True)
        self.detailed_stack_traces = getattr(config, "DETAILED_STACK_TRACES", True)
        self.max_recovery_attempts = getattr(config, "MAX_RECOVERY_ATTEMPTS", 3)

        # Recovery-System
        self.recovery_attempts = defaultdict(int)
        self.recovery_strategies = {}
        self._register_recovery_strategies()

        # Error-Templates erweitert
        self.error_messages = {
            "generic": "⚠️ Es ist ein unerwarteter Fehler aufgetreten. Bitte versuche es erneut.",
            "network": "🌐 Netzwerkproblem erkannt. Überprüfe deine Verbindung.",
            "timeout": "⏱️ Zeitüberschreitung. Der Vorgang dauerte zu lange.",
            "parsing": "📄 Datenformat-Fehler. Eingabe konnte nicht verarbeitet werden.",
            "bad_request": "❌ Ungültige Anfrage. Überprüfe deine Eingabe.",
            "rate_limit": "⏳ Zu viele Anfragen. Warte einen Moment.",
            "file_error": "📁 Dateifehler. Datei nicht gefunden oder nicht lesbar.",
            "permission_error": "🔒 Keine Berechtigung für diese Aktion.",
            "memory_error": "💾 Speicherfehler. System überlastet.",
            "runtime_error": "⚙️ Laufzeitfehler im System.",
            "import_error": "📦 Modul-Ladefehler. Abhängigkeit fehlt.",
            "data_error": "📊 Daten-Verarbeitungsfehler.",
            "async_error": "🔄 Asynchroner Verarbeitungsfehler.",
            "unknown": "❓ Unbekannter Fehlertyp. Administrator informiert.",
        }

        # Performance-Tracking
        self.performance_stats = {
            "total_handled": 0,
            "avg_processing_time": 0,
            "recovery_success_rate": 0,
            "last_reset": datetime.now(),
        }

        self.logger.info("🚨 Erweiterte Error Handler initialisiert")
        if self.debug_mode:
            self.logger.info("🐛 DEBUG-Modus aktiviert - Detailliertes Logging aktiv")

    def _register_recovery_strategies(self):
        """Registriert Recovery-Strategien für verschiedene Exception-Typen"""
        self.recovery_strategies = {
            "network": self._recover_network_error,
            "timeout": self._recover_timeout_error,
            "parsing": self._recover_parsing_error,
            "file_system": self._recover_file_error,
            "telegram": self._recover_telegram_error,
        }
        self.logger.debug("🔧 Recovery-Strategien registriert")

    async def handle_exception(
        self,
        exception: Exception,
        context: Optional[Dict[str, Any]] = None,
        update: Optional[Update] = None,
        telegram_context: Optional[ContextTypes.DEFAULT_TYPE] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        🎯 HAUPT-EXCEPTION-HANDLER
        Behandelt jede Art von Exception mit vollständigem Logging
        """
        start_time = datetime.now()

        # Session für Debug-Tracking
        if not session_id:
            session_id = f"EXC_{start_time.strftime('%H%M%S_%f')}"

        self.debug_tracker.start_session(
            session_id,
            {
                "exception_type": type(exception).__name__,
                "has_update": update is not None,
                "context_keys": list(context.keys()) if context else [],
            },
        )

        try:
            # 🎯 Step 1: Exception aufzeichnen
            self.debug_tracker.log_step(
                session_id,
                "Exception aufgetreten",
                {"type": type(exception).__name__, "message": str(exception)},
                "🚨",
            )

            # Kontext erweitern
            full_context = self._build_full_context(exception, context, update)

            # 📊 Step 2: Exception im Monitor registrieren
            exc_id = self.exception_monitor.record_exception(
                exception, full_context, traceback.format_exc().split("\n")
            )
            self.debug_tracker.log_step(
                session_id, "Exception registriert", {"exception_id": exc_id}, "📊"
            )

            # 🏷️ Step 3: Exception kategorisieren
            category = self.exception_monitor.categorize_exception(exception)
            severity = self.exception_monitor.determine_severity(
                exception, full_context
            )

            self.debug_tracker.log_step(
                session_id,
                "Exception kategorisiert",
                {"category": category, "severity": severity},
                "🏷️",
            )

            # 📝 Step 4: Detailliertes Logging
            await self._log_exception_details(
                exception, full_context, exc_id, session_id
            )

            # 🔧 Step 5: Recovery versuchen (falls Telegram-Update vorhanden)
            recovery_success = False
            if update and telegram_context:
                recovery_success = await self._attempt_recovery(
                    exception, category, update, telegram_context, session_id
                )

            # 📱 Step 6: Benutzer benachrichtigen (falls möglich)
            if update:
                await self._notify_user_enhanced(
                    update, category, exception, recovery_success, session_id
                )

            # 📈 Step 7: Performance-Statistiken aktualisieren
            processing_time = (datetime.now() - start_time).total_seconds()
            self._update_performance_stats(processing_time, recovery_success)

            self.debug_tracker.log_step(
                session_id,
                "Verarbeitung abgeschlossen",
                {
                    "processing_time": processing_time,
                    "recovery_success": recovery_success,
                },
                "✅",
            )

            return exc_id

        except Exception as handler_exception:
            # Meta-Error: Error im Error-Handler
            self.logger.critical(
                f"💥 KRITISCH: Fehler im Error-Handler selbst: {handler_exception}"
            )
            self.debug_tracker.log_step(
                session_id,
                "Meta-Error aufgetreten",
                {"meta_error": str(handler_exception)},
                "💥",
            )
            return "HANDLER_ERROR"

        finally:
            self.debug_tracker.end_session(session_id)
            self.performance_stats["total_handled"] += 1

    def _build_full_context(
        self,
        exception: Exception,
        context: Optional[Dict[str, Any]],
        update: Optional[Update],
    ) -> Dict[str, Any]:
        """Baut vollständigen Kontext für Exception-Analyse auf"""
        full_context = {
            "timestamp": datetime.now().isoformat(),
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
            "python_version": sys.version,
            "thread_info": {
                "thread_id": threading.current_thread().ident,
                "thread_name": threading.current_thread().name,
                "is_main_thread": threading.current_thread() == threading.main_thread(),
            },
        }

        # Übergebenen Kontext hinzufügen
        if context:
            full_context.update(context)

        # Frame-Information sammeln
        frame_info = []
        frame = inspect.currentframe()
        try:
            while frame and len(frame_info) < 10:  # Max 10 Frames
                frame_data = {
                    "filename": frame.f_code.co_filename,
                    "function": frame.f_code.co_name,
                    "line": frame.f_lineno,
                    "locals_keys": list(frame.f_locals.keys()),
                }
                frame_info.append(frame_data)
                frame = frame.f_back
        finally:
            del frame

        full_context["frame_info"] = frame_info

        # Update-spezifische Informationen
        if update:
            update_info = self._extract_update_info(update)
            full_context["telegram_update"] = update_info

        return full_context

    def _extract_update_info(self, update: Update) -> Dict[str, Any]:
        """Extrahiert Informationen aus Telegram Update"""
        info = {"update_type": type(update).__name__}

        try:
            if update.effective_user:
                info["user"] = {
                    "id": update.effective_user.id,
                    "username": update.effective_user.username,
                    "first_name": update.effective_user.first_name,
                    "language_code": update.effective_user.language_code,
                }

            if update.effective_chat:
                info["chat"] = {
                    "id": update.effective_chat.id,
                    "type": update.effective_chat.type,
                    "title": update.effective_chat.title,
                }

            if update.message:
                info["message"] = {
                    "message_id": update.message.message_id,
                    "date": (
                        update.message.date.isoformat() if update.message.date else None
                    ),
                    "text_preview": (
                        update.message.text[:100] if update.message.text else None
                    ),
                    "has_media": bool(
                        update.message.photo
                        or update.message.video
                        or update.message.audio
                        or update.message.document
                    ),
                }

            if update.callback_query:
                info["callback_query"] = {
                    "id": update.callback_query.id,
                    "data": update.callback_query.data,
                    "message_id": (
                        update.callback_query.message.message_id
                        if update.callback_query.message
                        else None
                    ),
                }

        except Exception as e:
            info["extraction_error"] = str(e)

        return info

    async def _log_exception_details(
        self,
        exception: Exception,
        context: Dict[str, Any],
        exc_id: str,
        session_id: str,
    ):
        """Loggt detaillierte Exception-Informationen"""

        self.debug_tracker.log_step(
            session_id, "Detailliertes Logging startet", {"exception_id": exc_id}, "📝"
        )

        # Basis-Logging
        exc_type = type(exception).__name__
        exc_msg = str(exception)

        # Severity-basiertes Logging
        severity = self.exception_monitor.determine_severity(exception, context)

        if severity == "critical":
            log_method = self.logger.critical
            emoji = "🚨"
        elif severity == "error":
            log_method = self.logger.error
            emoji = "❌"
        elif severity == "warning":
            log_method = self.logger.warning
            emoji = "⚠️"
        else:
            log_method = self.logger.info
            emoji = "ℹ️"

        # Header
        log_method("=" * 80)
        log_method(f"{emoji} EXCEPTION DETECTED [{exc_id}]")
        log_method("=" * 80)

        # Exception-Details
        log_method(f"🏷️  Type: {exc_type}")
        log_method(f"📨 Message: {exc_msg}")
        log_method(
            f"📊 Category: {self.exception_monitor.categorize_exception(exception)}"
        )
        log_method(f"⚡ Severity: {severity}")
        log_method(f"🕒 Timestamp: {context.get('timestamp', 'Unknown')}")

        # Thread-Information
        thread_info = context.get("thread_info", {})
        if thread_info:
            log_method(
                f"🧵 Thread: {thread_info.get('thread_name')} (ID: {thread_info.get('thread_id')})"
            )

        # Telegram-spezifische Infos
        if "telegram_update" in context:
            tg_info = context["telegram_update"]
            log_method("📱 TELEGRAM CONTEXT:")

            if "user" in tg_info:
                user = tg_info["user"]
                log_method(
                    f"   👤 User: {user.get('first_name')} (@{user.get('username')}) [{user.get('id')}]"
                )

            if "message" in tg_info:
                msg = tg_info["message"]
                log_method(
                    f"   💬 Message: ID {msg.get('message_id')} | Preview: {msg.get('text_preview', 'No text')}"
                )

            if "callback_query" in tg_info:
                cb = tg_info["callback_query"]
                log_method(
                    f"   🎯 Callback: {cb.get('data')} | Message ID: {cb.get('message_id')}"
                )

        # Frame-Information (wenn DEBUG)
        if self.debug_mode and "frame_info" in context:
            log_method("🔍 CALL STACK:")
            for i, frame in enumerate(context["frame_info"][:5]):  # Top 5 Frames
                filename = Path(frame["filename"]).name
                log_method(
                    f"   {i+1}. {filename}:{frame['line']} in {frame['function']}()"
                )

        # Stack Trace (wenn aktiviert)
        if self.detailed_stack_traces:
            log_method("📋 FULL STACK TRACE:")
            stack_trace = traceback.format_exception(
                type(exception), exception, exception.__traceback__
            )
            for line in stack_trace:
                for sub_line in line.strip().split("\n"):
                    if sub_line.strip():
                        log_method(f"   {sub_line}")

        # Zusätzliche Kontext-Daten
        if context.get("module"):
            log_method(f"🎯 Module: {context['module']}")

        if context.get("function"):
            log_method(f"⚙️ Function: {context['function']}")

        if context.get("operation"):
            log_method(f"🔄 Operation: {context['operation']}")

        # Footer
        log_method("=" * 80)

        self.debug_tracker.log_step(
            session_id, "Detailliertes Logging abgeschlossen", emoji="✅"
        )

    async def _attempt_recovery(
        self,
        exception: Exception,
        category: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session_id: str,
    ) -> bool:
        """Versucht Recovery basierend auf Exception-Kategorie"""

        self.debug_tracker.log_step(
            session_id, "Recovery-Versuch startet", {"category": category}, "🔧"
        )

        # Recovery-Key für Tracking
        user_id = update.effective_user.id if update.effective_user else "unknown"
        recovery_key = f"{user_id}_{category}"

        # Prüfe Recovery-Limit
        if self.recovery_attempts[recovery_key] >= self.max_recovery_attempts:
            self.debug_tracker.log_step(
                session_id,
                "Recovery-Limit erreicht",
                {"attempts": self.recovery_attempts[recovery_key]},
                "⛔",
            )
            return False

        self.recovery_attempts[recovery_key] += 1

        # Suche passende Recovery-Strategie
        if category in self.recovery_strategies:
            try:
                strategy = self.recovery_strategies[category]
                success = await strategy(exception, update, context, session_id)

                self.debug_tracker.log_step(
                    session_id,
                    "Recovery-Strategie ausgeführt",
                    {"strategy": category, "success": success},
                    "✅" if success else "❌",
                )

                return success

            except Exception as recovery_error:
                self.debug_tracker.log_step(
                    session_id, "Recovery-Fehler", {"error": str(recovery_error)}, "💥"
                )
                self.logger.error(
                    f"🔧 Recovery-Strategie fehlgeschlagen: {recovery_error}"
                )
                return False
        else:
            self.debug_tracker.log_step(
                session_id,
                "Keine Recovery-Strategie gefunden",
                {"category": category},
                "❓",
            )
            return False

    async def _recover_network_error(
        self,
        exception: Exception,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session_id: str,
    ) -> bool:
        """Recovery für Netzwerk-Fehler"""
        self.debug_tracker.log_step(
            session_id, "Netzwerk-Recovery gestartet", emoji="🌐"
        )

        try:
            # Kurze Wartezeit
            await asyncio.sleep(2)

            recovery_msg = (
                "🌐 Netzwerkproblem erkannt!\n\n"
                "🔄 Verbindung wird wiederhergestellt...\n"
                "⏳ Bitte versuche es in einem Moment erneut."
            )

            if update.callback_query:
                await update.callback_query.answer(
                    "🌐 Netzwerkfehler - Wiederherstellung..."
                )
                await update.callback_query.edit_message_text(recovery_msg)
            else:
                await update.effective_message.reply_text(recovery_msg)

            self.debug_tracker.log_step(
                session_id, "Netzwerk-Recovery erfolgreich", emoji="✅"
            )
            return True

        except Exception as e:
            self.debug_tracker.log_step(
                session_id, "Netzwerk-Recovery fehlgeschlagen", {"error": str(e)}, "❌"
            )
            return False

    async def _recover_timeout_error(
        self,
        exception: Exception,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session_id: str,
    ) -> bool:
        """Recovery für Timeout-Fehler"""
        self.debug_tracker.log_step(
            session_id, "Timeout-Recovery gestartet", emoji="⏱️"
        )

        try:
            recovery_msg = (
                "⏱️ Zeitüberschreitung!\n\n"
                "Der Vorgang dauerte länger als erwartet.\n"
                "🔄 Verwende einfachere Befehle oder versuche es später erneut."
            )

            if update.callback_query:
                await update.callback_query.answer("⏱️ Timeout - Vereinfache Anfrage")
                await update.callback_query.edit_message_text(recovery_msg)
            else:
                await update.effective_message.reply_text(recovery_msg)

            self.debug_tracker.log_step(
                session_id, "Timeout-Recovery erfolgreich", emoji="✅"
            )
            return True

        except Exception as e:
            self.debug_tracker.log_step(
                session_id, "Timeout-Recovery fehlgeschlagen", {"error": str(e)}, "❌"
            )
            return False

    async def _recover_parsing_error(
        self,
        exception: Exception,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session_id: str,
    ) -> bool:
        """Recovery für Parsing-Fehler"""
        self.debug_tracker.log_step(
            session_id, "Parsing-Recovery gestartet", emoji="📄"
        )

        try:
            recovery_msg = (
                "📄 Datenformat-Fehler!\n\n"
                "Die Eingabe konnte nicht richtig verarbeitet werden.\n"
                "💡 Tipps:\n"
                "• Verwende die Buttons statt Texteingabe\n"
                "• Überprüfe Links und Formatierung\n"
                "• Versuche es mit /menu für Navigation"
            )

            if update.callback_query:
                await update.callback_query.answer("📄 Format-Fehler")
                await update.callback_query.edit_message_text(recovery_msg)
            else:
                await update.effective_message.reply_text(recovery_msg)

            self.debug_tracker.log_step(
                session_id, "Parsing-Recovery erfolgreich", emoji="✅"
            )
            return True

        except Exception as e:
            self.debug_tracker.log_step(
                session_id, "Parsing-Recovery fehlgeschlagen", {"error": str(e)}, "❌"
            )
            return False

    async def _recover_file_error(
        self,
        exception: Exception,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session_id: str,
    ) -> bool:
        """Recovery für Dateisystem-Fehler"""
        self.debug_tracker.log_step(
            session_id, "Dateisystem-Recovery gestartet", emoji="📁"
        )

        try:
            if isinstance(exception, PermissionError):
                recovery_msg = (
                    "🔒 Berechtigungsfehler!\n\n"
                    "Keine Berechtigung für diese Aktion.\n"
                    "👤 Bitte wende dich an einen Administrator."
                )
            elif isinstance(exception, FileNotFoundError):
                recovery_msg = (
                    "📁 Datei nicht gefunden!\n\n"
                    "Die angeforderte Datei existiert nicht mehr.\n"
                    "🔄 Versuche es mit einer anderen Datei oder aktualisiere die Liste."
                )
            else:
                recovery_msg = (
                    "💾 Dateisystem-Fehler!\n\n"
                    "Problem beim Zugriff auf Dateien.\n"
                    "⏳ Versuche es in einem Moment erneut."
                )

            if update.callback_query:
                await update.callback_query.answer("📁 Dateifehler")
                await update.callback_query.edit_message_text(recovery_msg)
            else:
                await update.effective_message.reply_text(recovery_msg)

            self.debug_tracker.log_step(
                session_id, "Dateisystem-Recovery erfolgreich", emoji="✅"
            )
            return True

        except Exception as e:
            self.debug_tracker.log_step(
                session_id,
                "Dateisystem-Recovery fehlgeschlagen",
                {"error": str(e)},
                "❌",
            )
            return False

    async def _recover_telegram_error(
        self,
        exception: Exception,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session_id: str,
    ) -> bool:
        """Recovery für Telegram-spezifische Fehler"""
        self.debug_tracker.log_step(
            session_id, "Telegram-Recovery gestartet", emoji="📱"
        )

        try:
            if isinstance(exception, BadRequest):
                if "message is not modified" in str(exception).lower():
                    # Stille Behandlung - keine Benutzerbenachrichtigung nötig
                    if update.callback_query:
                        await update.callback_query.answer("🔄 Keine Änderungen")
                    return True
                elif "message to edit not found" in str(exception).lower():
                    recovery_msg = (
                        "📱 Nachricht nicht mehr verfügbar!\n\n"
                        "Die Nachricht wurde bereits gelöscht oder ist nicht mehr bearbeitbar.\n"
                        "🔄 Starte eine neue Aktion mit /menu"
                    )
                else:
                    recovery_msg = (
                        "📱 Telegram-Anfragefehler!\n\n"
                        "Die Anfrage konnte nicht verarbeitet werden.\n"
                        "💡 Versuche es erneut oder verwende /menu"
                    )
            elif isinstance(exception, TimedOut):
                recovery_msg = (
                    "⏰ Telegram-Zeitüberschreitung!\n\n"
                    "Die Verbindung zu Telegram war zu langsam.\n"
                    "🔄 Versuche es in einem Moment erneut."
                )
            elif isinstance(exception, NetworkError):
                recovery_msg = (
                    "📡 Telegram-Verbindungsfehler!\n\n"
                    "Probleme mit der Telegram-Verbindung.\n"
                    "🌐 Überprüfe deine Internetverbindung."
                )
            else:
                recovery_msg = (
                    "🤖 Telegram-Fehler!\n\n"
                    "Unerwarteter Telegram-API Fehler.\n"
                    "⏳ Versuche es in einem Moment erneut."
                )

            # Versuche Nachricht zu senden (falls möglich)
            try:
                if (
                    update.callback_query
                    and "message is not modified" not in str(exception).lower()
                ):
                    await update.callback_query.answer("📱 Telegram-Fehler")
                    await update.callback_query.edit_message_text(recovery_msg)
                elif update.effective_message:
                    await update.effective_message.reply_text(recovery_msg)
            except:
                # Fallback: Versuche nur Callback-Answer
                if update.callback_query:
                    try:
                        await update.callback_query.answer("Fehler aufgetreten")
                    except:
                        pass

            self.debug_tracker.log_step(
                session_id, "Telegram-Recovery erfolgreich", emoji="✅"
            )
            return True

        except Exception as e:
            self.debug_tracker.log_step(
                session_id, "Telegram-Recovery fehlgeschlagen", {"error": str(e)}, "❌"
            )
            return False

    async def _notify_user_enhanced(
        self,
        update: Update,
        category: str,
        exception: Exception,
        recovery_success: bool,
        session_id: str,
    ):
        """Erweiterte Benutzerbenachrichtigung"""

        self.debug_tracker.log_step(
            session_id,
            "Benutzerbenachrichtigung startet",
            {"category": category, "recovery_success": recovery_success},
            "📱",
        )

        if recovery_success:
            # Recovery war erfolgreich - keine zusätzliche Benachrichtigung nötig
            self.debug_tracker.log_step(
                session_id,
                "Recovery erfolgreich - keine weitere Benachrichtigung",
                emoji="✅",
            )
            return

        # Bestimme passende Nachricht
        exc_type = type(exception).__name__
        category_msg = self.error_messages.get(category, self.error_messages["generic"])

        # Erweiterte Nachricht mit Debug-Info (falls Debug-Modus)
        if self.debug_mode:
            debug_info = f"\n\n🐛 Debug-Info: {exc_type} | Session: {session_id[-8:]}"
            error_msg = category_msg + debug_info
        else:
            error_msg = category_msg

        # Zusätzliche Hilfe je nach Kategorie
        help_text = ""
        if category == "parsing":
            help_text = "\n\n💡 Tipp: Verwende die Buttons für Navigation."
        elif category == "network":
            help_text = "\n\n🌐 Überprüfe deine Internetverbindung."
        elif category == "file_system":
            help_text = "\n\n📁 Überprüfe Dateipfade und Berechtigungen."
        elif category == "memory":
            help_text = "\n\n💾 System könnte überlastet sein. Versuche es später."

        final_message = error_msg + help_text

        try:
            if update.callback_query:
                await update.callback_query.answer(f"❌ {exc_type}")
                try:
                    await update.callback_query.edit_message_text(final_message)
                except TelegramError:
                    # Fallback: Neue Nachricht senden
                    await update.effective_message.reply_text(final_message)
            else:
                await update.effective_message.reply_text(final_message)

            self.debug_tracker.log_step(
                session_id, "Benutzerbenachrichtigung erfolgreich", emoji="✅"
            )

        except Exception as notification_error:
            self.debug_tracker.log_step(
                session_id,
                "Benutzerbenachrichtigung fehlgeschlagen",
                {"error": str(notification_error)},
                "❌",
            )
            self.logger.error(
                f"📱 Konnte Benutzer nicht benachrichtigen: {notification_error}"
            )

    def _update_performance_stats(self, processing_time: float, recovery_success: bool):
        """Aktualisiert Performance-Statistiken"""
        stats = self.performance_stats

        # Durchschnittliche Verarbeitungszeit aktualisieren
        total = stats["total_handled"]
        current_avg = stats["avg_processing_time"]
        stats["avg_processing_time"] = ((current_avg * total) + processing_time) / (
            total + 1
        )

        # Recovery-Erfolgsrate aktualisieren
        if recovery_success:
            # Vereinfachte Berechnung - könnte erweitert werden
            stats["recovery_success_rate"] = min(
                stats["recovery_success_rate"] + 0.1, 1.0
            )
        else:
            stats["recovery_success_rate"] = max(
                stats["recovery_success_rate"] - 0.05, 0.0
            )

    # ========================================
    # DECORATOR FUNCTIONS FÜR AUTOMATISCHES ERROR HANDLING
    # ========================================

    def handle_async_exceptions(self, module_name: str = None, operation: str = None):
        """
        🎯 DECORATOR: Automatisches Exception Handling für async Funktionen

        Verwendung:
        @error_handler.handle_async_exceptions("MyModule", "download_operation")
        async def my_function():
            pass
        """

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                session_id = f"{func.__name__}_{datetime.now().strftime('%H%M%S_%f')}"

                try:
                    self.debug_tracker.start_session(
                        session_id,
                        {
                            "function": func.__name__,
                            "module": module_name or func.__module__,
                            "operation": operation,
                            "args_count": len(args),
                            "kwargs_keys": list(kwargs.keys()),
                        },
                    )

                    self.debug_tracker.log_step(
                        session_id,
                        f"Funktion gestartet: {func.__name__}",
                        {"module": module_name},
                        "🎯",
                    )

                    result = await func(*args, **kwargs)

                    self.debug_tracker.log_step(
                        session_id, f"Funktion erfolgreich: {func.__name__}", emoji="✅"
                    )

                    return result

                except Exception as e:
                    context = {
                        "module": module_name or func.__module__,
                        "function": func.__name__,
                        "operation": operation,
                        "args": [
                            str(arg)[:100] for arg in args[:3]
                        ],  # Erste 3 Args, gekürzt
                        "kwargs": {
                            k: str(v)[:100] for k, v in list(kwargs.items())[:3]
                        },
                    }

                    # Suche nach Update-Objekt in den Argumenten
                    update_obj = None
                    telegram_context = None

                    for arg in args:
                        if isinstance(arg, Update):
                            update_obj = arg
                        elif (
                            hasattr(arg, "args")
                            and len(arg.args) > 0
                            and isinstance(arg.args[0], Update)
                        ):
                            update_obj = arg.args[0]
                        elif str(type(arg)).endswith("ContextTypes.DEFAULT_TYPE'>"):
                            telegram_context = arg

                    # Exception behandeln
                    await self.handle_exception(
                        e, context, update_obj, telegram_context, session_id
                    )

                    # Exception weiterwerfen (oder suppression je nach Konfiguration)
                    if self.config.get("SUPPRESS_HANDLED_EXCEPTIONS", False):
                        self.logger.warning(
                            f"🔇 Exception unterdrückt in {func.__name__}: {e}"
                        )
                        return None
                    else:
                        raise

                finally:
                    self.debug_tracker.end_session(session_id)

            return wrapper

        return decorator

    def handle_sync_exceptions(self, module_name: str = None, operation: str = None):
        """
        🎯 DECORATOR: Automatisches Exception Handling für synchrone Funktionen
        """

        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                session_id = f"{func.__name__}_{datetime.now().strftime('%H%M%S_%f')}"

                try:
                    self.debug_tracker.start_session(
                        session_id,
                        {
                            "function": func.__name__,
                            "module": module_name or func.__module__,
                            "operation": operation,
                            "sync_function": True,
                        },
                    )

                    self.debug_tracker.log_step(
                        session_id,
                        f"Sync-Funktion gestartet: {func.__name__}",
                        {"module": module_name},
                        "⚙️",
                    )

                    result = func(*args, **kwargs)

                    self.debug_tracker.log_step(
                        session_id,
                        f"Sync-Funktion erfolgreich: {func.__name__}",
                        emoji="✅",
                    )

                    return result

                except Exception as e:
                    context = {
                        "module": module_name or func.__module__,
                        "function": func.__name__,
                        "operation": operation,
                        "sync_function": True,
                    }

                    # Synchrone Exception-Behandlung (ohne await)
                    asyncio.create_task(
                        self.handle_exception(e, context, session_id=session_id)
                    )

                    if self.config.get("SUPPRESS_HANDLED_EXCEPTIONS", False):
                        self.logger.warning(
                            f"🔇 Sync-Exception unterdrückt in {func.__name__}: {e}"
                        )
                        return None
                    else:
                        raise

                finally:
                    self.debug_tracker.end_session(session_id)

            return wrapper

        return decorator

    # ========================================
    # MONITORING UND STATISTIKEN
    # ========================================

    def get_comprehensive_statistics(self) -> Dict[str, Any]:
        """Gibt umfassende Statistiken zurück"""
        return {
            "exception_monitor": self.exception_monitor.get_statistics(),
            "performance": self.performance_stats.copy(),
            "debug_tracker": {
                "active_sessions": len(self.debug_tracker.sessions),
                "total_sessions_completed": len(self.debug_tracker.session_history),
                "global_steps": self.debug_tracker.global_step_counter,
            },
            "recovery": {
                "total_attempts": sum(self.recovery_attempts.values()),
                "active_recovery_keys": list(self.recovery_attempts.keys()),
                "available_strategies": list(self.recovery_strategies.keys()),
            },
            "configuration": {
                "debug_mode": self.debug_mode,
                "log_all_exceptions": self.log_all_exceptions,
                "detailed_stack_traces": self.detailed_stack_traces,
                "max_recovery_attempts": self.max_recovery_attempts,
            },
        }

    def get_recent_exceptions_summary(self, count: int = 10) -> List[Dict[str, Any]]:
        """Gibt Zusammenfassung der letzten Exceptions"""
        recent = self.exception_monitor.get_recent_exceptions(count)

        summary = []
        for exc in recent:
            summary.append(
                {
                    "id": exc["id"],
                    "timestamp": exc["timestamp"],
                    "type": exc["type"],
                    "category": exc["category"],
                    "severity": exc["severity"],
                    "message_preview": (
                        exc["message"][:100] + "..."
                        if len(exc["message"]) > 100
                        else exc["message"]
                    ),
                    "has_telegram_context": "telegram_update" in exc.get("context", {}),
                }
            )

        return summary

    def export_debug_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Exportiert eine Debug-Session für Analyse"""
        return self.debug_tracker.get_session_summary(session_id)

    async def create_health_report(self) -> str:
        """Erstellt einen Gesundheitsbericht des Error-Handling-Systems"""
        stats = self.get_comprehensive_statistics()

        report = [
            "🏥 ERROR HANDLER GESUNDHEITSBERICHT",
            "=" * 50,
            f"📊 Gesamt-Exceptions: {stats['exception_monitor']['total_exceptions']}",
            f"⚡ Durchschnittliche Verarbeitungszeit: {stats['performance']['avg_processing_time']:.3f}s",
            f"🔧 Recovery-Erfolgsrate: {stats['performance']['recovery_success_rate']:.1%}",
            f"🐛 Aktive Debug-Sessions: {stats['debug_tracker']['active_sessions']}",
            "",
            "📈 TOP EXCEPTION-KATEGORIEN:",
        ]

        # Top 5 Kategorien
        categories = stats["exception_monitor"]["by_category"]
        top_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[
            :5
        ]

        for category, count in top_categories:
            percentage = (
                count / max(stats["exception_monitor"]["total_exceptions"], 1)
            ) * 100
            report.append(f"   • {category}: {count} ({percentage:.1f}%)")

        report.extend(
            [
                "",
                "🕐 STÜNDLICHE VERTEILUNG:",
            ]
        )

        # Stündliche Verteilung
        hourly = stats["exception_monitor"]["hourly_counts"]
        for hour in sorted(hourly.keys())[:6]:  # Zeige nur die ersten 6 Stunden
            count = hourly[hour]
            report.append(f"   • {hour}:00 Uhr: {count} Exceptions")

        return "\n".join(report)

    def reset_statistics(self):
        """Setzt alle Statistiken zurück"""
        self.exception_monitor.stats = {
            "total_exceptions": 0,
            "by_category": defaultdict(int),
            "by_type": defaultdict(int),
            "by_module": defaultdict(int),
            "by_severity": defaultdict(int),
            "hourly_counts": defaultdict(int),
            "patterns": defaultdict(int),
        }

        self.performance_stats = {
            "total_handled": 0,
            "avg_processing_time": 0,
            "recovery_success_rate": 0,
            "last_reset": datetime.now(),
        }

        self.recovery_attempts.clear()

        self.logger.info("📊 Alle Error-Handler Statistiken zurückgesetzt")

    def cleanup_old_data(self, max_age_hours: int = 24):
        """Bereinigt alte Debug- und Exception-Daten"""
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

        # Alte Debug-Sessions bereinigen
        old_sessions = [
            s
            for s in self.debug_tracker.session_history
            if datetime.fromisoformat(
                s.get("start_time", "1970-01-01")
                .replace("Z", "+00:00")
                .replace("+00:00", "")
            )
            < cutoff_time
        ]

        for session in old_sessions:
            self.debug_tracker.session_history.remove(session)

        if len(old_sessions) > 0:  # Nur loggen, wenn wirklich etwas entfernt wurde
            self.logger.info(f"🧹 {len(old_sessions)} alte Debug-Sessions bereinigt")

    # ========================================
    # TELEGRAM-SPEZIFISCHE ERROR-BEHANDLUNG
    # ========================================

    async def handle_telegram_error(
        self, update: object, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        🤖 TELEGRAM-SPEZIFISCHER ERROR-HANDLER
        Wird automatisch von python-telegram-bot bei Fehlern aufgerufen
        """
        error = context.error

        # Session für Telegram-Error
        session_id = f"TG_{datetime.now().strftime('%H%M%S_%f')}"

        self.debug_tracker.start_session(
            session_id,
            {
                "telegram_error": True,
                "error_type": type(error).__name__,
                "has_update": update is not None,
                "update_type": type(update).__name__ if update else None,
            },
        )

        self.debug_tracker.log_step(
            session_id,
            "Telegram-Error empfangen",
            {"error_type": type(error).__name__},
            "🤖",
        )

        # Erweiterten Context für Telegram-Errors bauen
        telegram_context = {
            "telegram_error": True,
            "handler_source": "telegram_bot_framework",
            "error_in_handler": True,
        }

        # Behandle mit dem Hauptsystem
        await self.handle_exception(
            error,
            context=telegram_context,
            update=update,
            telegram_context=context,
            session_id=session_id,
        )

    async def handle_command_error(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        command_name: str,
        original_exception: Exception,
    ) -> None:
        """
        ⚡ COMMAND-SPEZIFISCHER ERROR-HANDLER
        Für Fehler in Command-Handlern mit zusätzlichen Kontext-Informationen
        """
        session_id = f"CMD_{command_name}_{datetime.now().strftime('%H%M%S_%f')}"

        self.debug_tracker.start_session(
            session_id,
            {
                "command_error": True,
                "command_name": command_name,
                "user_id": update.effective_user.id if update.effective_user else None,
            },
        )

        self.debug_tracker.log_step(
            session_id,
            f"Command-Error in /{command_name}",
            {"command": command_name},
            "⚡",
        )

        command_context = {
            "command_error": True,
            "command_name": command_name,
            "handler_type": "command_handler",
            "user_initiated": True,
        }

        await self.handle_exception(
            original_exception,
            context=command_context,
            update=update,
            telegram_context=context,
            session_id=session_id,
        )

    async def handle_callback_error(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
        original_exception: Exception,
    ) -> None:
        """
        🎯 CALLBACK-SPEZIFISCHER ERROR-HANDLER
        Für Fehler in Callback-Query-Handlern
        """
        session_id = f"CB_{datetime.now().strftime('%H%M%S_%f')}"

        self.debug_tracker.start_session(
            session_id,
            {
                "callback_error": True,
                "callback_data": callback_data,
                "user_id": update.effective_user.id if update.effective_user else None,
            },
        )

        self.debug_tracker.log_step(
            session_id, f"Callback-Error", {"callback_data": callback_data[:50]}, "🎯"
        )

        callback_context = {
            "callback_error": True,
            "callback_data": callback_data,
            "handler_type": "callback_handler",
            "inline_operation": True,
        }

        await self.handle_exception(
            original_exception,
            context=callback_context,
            update=update,
            telegram_context=context,
            session_id=session_id,
        )

    async def handle_menu_system_error(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        menu_action: str,
        original_exception: Exception,
    ) -> None:
        """
        📋 MENU-SYSTEM-SPEZIFISCHER ERROR-HANDLER
        Für Fehler im Menu-System mit Navigation-Kontext
        """
        session_id = f"MENU_{datetime.now().strftime('%H%M%S_%f')}"

        self.debug_tracker.start_session(
            session_id,
            {
                "menu_error": True,
                "menu_action": menu_action,
                "user_id": update.effective_user.id if update.effective_user else None,
            },
        )

        self.debug_tracker.log_step(
            session_id, f"Menu-System-Error", {"action": menu_action}, "📋"
        )

        menu_context = {
            "menu_error": True,
            "menu_action": menu_action,
            "handler_type": "menu_handler",
            "navigation_error": True,
        }

        # Erweiterte Recovery für Menu-Errors
        try:
            await self.handle_exception(
                original_exception,
                context=menu_context,
                update=update,
                telegram_context=context,
                session_id=session_id,
            )
        except Exception:
            # Fallback: Zurück zum Hauptmenü
            await self._menu_fallback_recovery(update, session_id)

    async def _menu_fallback_recovery(self, update: Update, session_id: str):
        """Fallback-Recovery für Menu-System Errors"""
        self.debug_tracker.log_step(session_id, "Menu-Fallback-Recovery", emoji="🔄")

        try:
            fallback_msg = (
                "📋 Menü-Navigationsfehler!\n\n"
                "🔄 Kehre zum Hauptmenü zurück...\n"
                "Verwende /menu für eine neue Navigation."
            )

            if update.callback_query:
                await update.callback_query.answer(
                    "📋 Menü-Fehler - Zurück zum Hauptmenü"
                )
                await update.callback_query.edit_message_text(fallback_msg)
            else:
                await update.effective_message.reply_text(fallback_msg)

            self.debug_tracker.log_step(
                session_id, "Menu-Fallback erfolgreich", emoji="✅"
            )

        except Exception as fallback_error:
            self.debug_tracker.log_step(
                session_id,
                "Menu-Fallback fehlgeschlagen",
                {"error": str(fallback_error)},
                "❌",
            )
            self.logger.error(f"📋 Menu-Fallback fehlgeschlagen: {fallback_error}")


# ========================================
# ERWEITERTE INTEGRATION HELPERS
# ========================================


class ErrorHandlerIntegration:
    """
    🔗 INTEGRATION HELPER
    Vereinfacht die Integration des Enhanced Error Handlers in bestehende Systeme
    """

    def __init__(self, error_handler: EnhancedErrorHandler):
        self.error_handler = error_handler
        self.logger = get_module_logger("ErrorHandlerIntegration")

    def wrap_command_handler(self, command_name: str):
        """
        📦 WRAPPER: Command-Handler mit automatischer Error-Behandlung

        Verwendung:
        @integration.wrap_command_handler("download")
        async def download_command(update, context):
            pass
        """

        def decorator(func):
            @wraps(func)
            async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
                try:
                    return await func(update, context)
                except Exception as e:
                    await self.error_handler.handle_command_error(
                        update, context, command_name, e
                    )

            wrapper._original_func = func  # Für Debugging
            wrapper._command_name = command_name
            return wrapper

        return decorator

    def wrap_callback_handler(self, pattern: str = None):
        """
        🎯 WRAPPER: Callback-Handler mit automatischer Error-Behandlung
        """

        def decorator(func):
            @wraps(func)
            async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
                callback_data = (
                    update.callback_query.data if update.callback_query else "unknown"
                )
                try:
                    return await func(update, context)
                except Exception as e:
                    await self.error_handler.handle_callback_error(
                        update, context, callback_data, e
                    )

            wrapper._original_func = func
            wrapper._callback_pattern = pattern
            return wrapper

        return decorator

    def wrap_menu_handler(self, menu_action: str):
        """
        📋 WRAPPER: Menu-Handler mit automatischer Error-Behandlung
        """

        def decorator(func):
            @wraps(func)
            async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
                try:
                    return await func(update, context)
                except Exception as e:
                    await self.error_handler.handle_menu_system_error(
                        update, context, menu_action, e
                    )

            wrapper._original_func = func
            wrapper._menu_action = menu_action
            return wrapper

        return decorator

    def integrate_with_command_integration(self, command_integration):
        """
        🏗️ Integriert Error Handler mit CommandIntegration
        """
        try:
            # Error Handler setzen
            command_integration.error_handler = self.error_handler

            # Wrapper für alle Handler anwenden (falls möglich)
            if hasattr(command_integration, "handlers"):
                wrapped_handlers = {}
                for name, handler in command_integration.handlers.items():
                    if asyncio.iscoroutinefunction(handler):
                        wrapped_handlers[name] = self._auto_wrap_handler(handler, name)
                    else:
                        wrapped_handlers[name] = handler

                command_integration.handlers = wrapped_handlers

            self.logger.info(
                "🔗 Error Handler erfolgreich mit CommandIntegration integriert"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"❌ Integration mit CommandIntegration fehlgeschlagen: {e}"
            )
            return False

    def _auto_wrap_handler(self, handler_func, handler_name: str):
        """Automatisches Wrapping für Handler"""

        @wraps(handler_func)
        async def wrapped_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                return await handler_func(update, context)
            except Exception as e:
                # Bestimme Handler-Typ basierend auf Namen
                if "command" in handler_name.lower():
                    await self.error_handler.handle_command_error(
                        update, context, handler_name, e
                    )
                elif (
                    "callback" in handler_name.lower()
                    or "button" in handler_name.lower()
                ):
                    callback_data = (
                        update.callback_query.data
                        if update.callback_query
                        else handler_name
                    )
                    await self.error_handler.handle_callback_error(
                        update, context, callback_data, e
                    )
                elif "menu" in handler_name.lower():
                    await self.error_handler.handle_menu_system_error(
                        update, context, handler_name, e
                    )
                else:
                    # Generische Behandlung
                    await self.error_handler.handle_exception(
                        e,
                        context={"handler_name": handler_name, "auto_wrapped": True},
                        update=update,
                        telegram_context=context,
                    )

        return wrapped_handler


def setup_enhanced_error_handling(
    application,
    config: Config,
    logger_factory: Callable = None,
    command_integration=None,
) -> Tuple[EnhancedErrorHandler, ErrorHandlerIntegration]:
    """
    🚀 SETUP: Komplette Error-Handling-Einrichtung

    Returns:
        Tuple[EnhancedErrorHandler, ErrorHandlerIntegration]
    """

    print("🚨 Richte erweiterte Error-Behandlung ein...")

    # 1. Enhanced Error Handler erstellen
    error_handler = create_enhanced_error_handler(config, logger_factory)
    print("✅ Enhanced Error Handler erstellt")

    # 2. Integration Helper erstellen
    integration = ErrorHandlerIntegration(error_handler)
    print("✅ Integration Helper erstellt")

    # 3. Mit Telegram Application integrieren
    application.add_error_handler(error_handler.handle_telegram_error)
    print("✅ Telegram Error Handler registriert")

    # 4. Mit Command Integration integrieren (falls vorhanden)
    if command_integration:
        success = integration.integrate_with_command_integration(command_integration)
        if success:
            print("✅ Command Integration verknüpft")
        else:
            print("⚠️ Command Integration Verknüpfung teilweise fehlgeschlagen")

    # 5. Globalen Handler installieren (optional)
    if getattr(config, "INSTALL_GLOBAL_EXCEPTION_HANDLER", False):
        install_global_exception_handler(error_handler)
        print("✅ Globaler Exception Handler installiert")

    # 6. Cleanup-Task starten (optional)
    if getattr(config, "AUTO_CLEANUP_ENABLED", True):

        async def cleanup_task():
            while True:
                await asyncio.sleep(3600)  # Jede Stunde
                error_handler.cleanup_old_data(max_age_hours=24)

        asyncio.create_task(cleanup_task())
        print("✅ Automatische Bereinigung aktiviert")

    print("🎉 Erweiterte Error-Behandlung vollständig eingerichtet!")

    return error_handler, integration


# ========================================
# ADMIN-INTERFACE FÜR ERROR-MONITORING
# ========================================


class ErrorHandlerAdminInterface:
    """
    👨‍💼 ADMIN-INTERFACE
    Telegram-basierte Admin-Oberfläche für Error-Monitoring
    """

    def __init__(self, error_handler: EnhancedErrorHandler, admin_user_ids: List[int]):
        self.error_handler = error_handler
        self.admin_user_ids = admin_user_ids
        self.logger = get_module_logger("ErrorHandlerAdmin")

    def is_admin(self, user_id: int) -> bool:
        """Prüft Admin-Berechtigung"""
        return user_id in self.admin_user_ids

    async def _reply_or_edit(
        self,
        update: Update,
        text: str,
        reply_markup: InlineKeyboardMarkup = None,
        parse_mode: str = "Markdown",
    ):
        """
        Antwortet robust, egal ob per Befehl (reply) oder Button (edit).
        """
        query = update.callback_query

        try:
            if query:
                # Per Button aufgerufen
                await query.answer()  # Callback bestätigen
                await query.edit_message_text(
                    text=text, reply_markup=reply_markup, parse_mode=parse_mode
                )
            elif update.message:
                # Per Befehl aufgerufen
                await update.message.reply_text(
                    text=text, reply_markup=reply_markup, parse_mode=parse_mode
                )
            elif update.effective_chat:
                # Fallback, wenn message-Objekt fehlt
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            else:
                self.logger.error(
                    "Konnte Antwortmethode in _reply_or_edit nicht bestimmen."
                )
        except TelegramError as e:
            if "message is not modified" in str(e):
                pass  # Ignorieren, wenn Nachricht identisch ist
            else:
                self.logger.warning(
                    f"Fehler in _reply_or_edit (Fallback): {e}", exc_info=True
                )
                # Fallback: Neue Nachricht senden, wenn Edit fehlschlägt
                if update.effective_chat:
                    await update.effective_chat.send_message(
                        text=text, reply_markup=reply_markup, parse_mode=parse_mode
                    )

    async def handle_error_stats_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Admin-Befehl/Button: Error-Statistiken anzeigen (Robust)"""
        if not self.is_admin(update.effective_user.id):
            await self._reply_or_edit(
                update, "🔒 Keine Berechtigung für Admin-Befehle."
            )
            return

        query = update.callback_query

        try:
            stats = self.error_handler.get_comprehensive_statistics()

            response = [
                "📊 **ERROR HANDLER STATISTIKEN**",
                "=" * 30,
                f"🚨 Gesamt Exceptions: {stats['exception_monitor']['total_exceptions']}",
                f"⚡ Verarbeitungszeit: {stats['performance']['avg_processing_time']:.3f}s",
                f"🔧 Recovery-Rate: {stats['performance']['recovery_success_rate']:.1%}",
                f"🐛 Aktive Sessions: {stats['debug_tracker']['active_sessions']}",
                "",
                "🏷️ **TOP KATEGORIEN:**",
            ]

            categories = stats["exception_monitor"]["by_category"]
            for category, count in sorted(
                categories.items(), key=lambda x: x[1], reverse=True
            )[:5]:
                response.append(f"  • {category}: {count}")

            keyboard = None
            if query:
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔄 Aktualisieren", callback_data="erradmin:show_stats"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "⬅️ Zurück", callback_data="menu:admin_errors"
                            )
                        ],
                    ]
                )

            await self._reply_or_edit(
                update,
                "\n".join(response),
                reply_markup=keyboard,
                parse_mode="Markdown",
            )

        except Exception as e:
            self.logger.error(
                f"Fehler in handle_error_stats_command: {e}", exc_info=True
            )
            error_msg = f"❌ Fehler beim Abrufen der Statistiken: {e}"
            await self._reply_or_edit(update, error_msg)

    async def handle_error_report_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Admin-Befehl/Button: Gesundheitsbericht (Robust)"""
        if not self.is_admin(update.effective_user.id):
            await self._reply_or_edit(
                update, "🔒 Keine Berechtigung für Admin-Befehle."
            )
            return

        query = update.callback_query

        try:
            report = await self.error_handler.create_health_report()

            keyboard = None
            if query:
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔄 Aktualisieren", callback_data="erradmin:show_report"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "⬅️ Zurück", callback_data="menu:admin_errors"
                            )
                        ],
                    ]
                )

            await self._reply_or_edit(
                update,
                f"```\n{report}\n```",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

        except Exception as e:
            self.logger.error(
                f"Fehler in handle_error_report_command: {e}", exc_info=True
            )
            error_msg = f"❌ Fehler beim Erstellen des Berichts: {e}"
            await self._reply_or_edit(update, error_msg)

    async def handle_recent_errors_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Admin-Befehl/Button: Letzte Errors anzeigen (Robust)"""
        if not self.is_admin(update.effective_user.id):
            await self._reply_or_edit(
                update, "🔒 Keine Berechtigung für Admin-Befehle."
            )
            return

        query = update.callback_query

        try:
            count = 5
            # Prüft nur context.args, wenn es kein Callback ist (verhindert Fehler)
            if not query and context.args and context.args[0].isdigit():
                count = min(int(context.args[0]), 20)  # Max 20

            recent = self.error_handler.get_recent_exceptions_summary(count)

            if not recent:
                # FIX: Verwendet _reply_or_edit statt update.message.reply_text
                await self._reply_or_edit(update, "✅ Keine aktuellen Exceptions!")
                return

            response = [f"🕐 **LETZTE {len(recent)} EXCEPTIONS:**", ""]

            for i, exc in enumerate(recent, 1):
                time_str = exc["timestamp"][:19].replace("T", " ")
                response.append(
                    f"{i}. 🕒 {time_str}\n"
                    f"   🏷️ {exc['type']} ({exc['category']})\n"
                    f"   📝 {exc['message_preview']}\n"
                )

            keyboard = None
            if query:
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔄 Aktualisieren", callback_data="erradmin:show_recent"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "⬅️ Zurück", callback_data="menu:admin_errors"
                            )
                        ],
                    ]
                )

            await self._reply_or_edit(
                update,
                "\n".join(response),
                reply_markup=keyboard,
                parse_mode="Markdown",
            )

        except Exception as e:
            # Der 'NoneType' error sollte jetzt nicht mehr hier auftreten,
            # aber andere Fehler werden korrekt behandelt.
            self.logger.error(
                f"Fehler in handle_recent_errors_command: {e}", exc_info=True
            )
            error_msg = f"❌ Fehler beim Abrufen aktueller Errors: {e}"
            await self._reply_or_edit(update, error_msg)

    async def show_reset_stats_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt Bestätigungs-Button für Reset (Robust)"""
        if not self.is_admin(update.effective_user.id):
            await self._reply_or_edit(update, "🔒 Keine Berechtigung.")
            return

        text = "⚠️ **Error-Statistiken zurücksetzen?**\n\nBist du sicher? Alle Zähler werden auf 0 gesetzt. Diese Aktion kann nicht rückgängig gemacht werden."

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Ja, jetzt zurücksetzen",
                        callback_data="erradmin:reset_execute",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Abbrechen", callback_data="menu:admin_errors"
                    )
                ],
            ]
        )

        await self._reply_or_edit(
            update, text, reply_markup=keyboard, parse_mode="Markdown"
        )

    async def execute_reset_stats(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Admin-Befehl/Button: Statistiken zurücksetzen (führt die Aktion aus) (Robust)"""
        if not self.is_admin(update.effective_user.id):
            await self._reply_or_edit(update, "🔒 Keine Berechtigung.")
            return

        query = update.callback_query

        try:
            self.error_handler.reset_statistics()
            text = "🔄 Error Handler Statistiken wurden zurückgesetzt!"

            keyboard = None
            if query:
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "⬅️ Zurück", callback_data="menu:admin_errors"
                            )
                        ]
                    ]
                )

            await self._reply_or_edit(update, text, reply_markup=keyboard)

        except Exception as e:
            self.logger.error(f"Fehler in execute_reset_stats: {e}", exc_info=True)
            error_msg = f"❌ Fehler beim Zurücksetzen: {e}"
            await self._reply_or_edit(update, error_msg)

    def register_admin_commands(self, application):
        """Registriert Admin-Befehle in der Application"""
        from telegram.ext import CommandHandler

        application.add_handler(
            CommandHandler("error_stats", self.handle_error_stats_command)
        )
        application.add_handler(
            CommandHandler("error_report", self.handle_error_report_command)
        )
        application.add_handler(
            CommandHandler("recent_errors", self.handle_recent_errors_command)
        )
        # HINWEIS: /reset_error_stats ruft jetzt die Bestätigung auf
        application.add_handler(
            CommandHandler("reset_error_stats", self.show_reset_stats_confirm)
        )

        self.logger.info(
            "👨‍💼 Admin-Befehle für Error Handler registriert (Callback-fähig)"
        )


# ========================================
# FINAL FACTORY UND INTEGRATION
# ========================================


def create_complete_error_handling_system(
    application,
    config: Config,
    logger_factory: Callable = None,
    command_integration=None,
    admin_user_ids: List[int] = None,
) -> Dict[str, Any]:
    """
    🏭 COMPLETE FACTORY: Erstellt komplettes Error-Handling-System

    Returns:
        Dict mit allen Komponenten: error_handler, integration, admin_interface
    """

    print("🚀 Erstelle komplettes Error-Handling-System...")

    # 1. Basis-Setup
    error_handler, integration = setup_enhanced_error_handling(
        application, config, logger_factory, command_integration
    )

    # 2. Admin-Interface (falls Admin-User konfiguriert)
    admin_interface = None
    if admin_user_ids:
        admin_interface = ErrorHandlerAdminInterface(error_handler, admin_user_ids)
        admin_interface.register_admin_commands(application)
        print("✅ Admin-Interface eingerichtet")

    # 3. Performance-Monitoring (erweitert)
    if getattr(config, "PERFORMANCE_MONITORING", True):

        async def performance_monitor():
            while True:
                await asyncio.sleep(300)  # Alle 5 Minuten
                stats = error_handler.get_comprehensive_statistics()

                # Warne bei hoher Error-Rate
                total_errors = stats["exception_monitor"]["total_exceptions"]
                if total_errors > 100:  # Mehr als 100 Errors
                    error_handler.logger.warning(
                        f"⚠️ Hohe Error-Rate erkannt: {total_errors} Exceptions"
                    )

                # Warne bei niedriger Recovery-Rate
                recovery_rate = stats["performance"]["recovery_success_rate"]
                if recovery_rate < 0.5:  # Unter 50%
                    error_handler.logger.warning(
                        f"⚠️ Niedrige Recovery-Rate: {recovery_rate:.1%}"
                    )

        asyncio.create_task(performance_monitor())
        print("✅ Performance-Monitoring aktiviert")

    components = {
        "error_handler": error_handler,
        "integration": integration,
        "admin_interface": admin_interface,
        "setup_complete": True,
    }

    print("🎉 Komplettes Error-Handling-System bereit!")

    return components


# ========================================
# FACTORY FUNCTIONS UND INTEGRATION
# ========================================


def create_enhanced_error_handler(
    config: Config, logger_factory: Callable = None
) -> EnhancedErrorHandler:
    """
    🏭 FACTORY: Erstellt Enhanced Error Handler

    Features:
    - Umfassendes Exception Monitoring
    - Step-by-Step Debug Tracking mit Emojis
    - Automatische Recovery-Strategien
    - Performance-Monitoring
    - Telegram-Integration
    - Export- und Analysefunktionen
    """
    return EnhancedErrorHandler(config, logger_factory)


def integrate_enhanced_error_handler(
    application, config: Config, logger_factory: Callable = None
):
    """
    🔗 INTEGRATION: Integriert Enhanced Error Handler in python-telegram-bot Application
    """
    enhanced_handler = create_enhanced_error_handler(config, logger_factory)

    # Haupt-Error-Handler registrieren
    application.add_error_handler(enhanced_handler.handle_telegram_error)

    # Globalen Exception-Handler installieren (optional)
    if getattr(config, "INSTALL_GLOBAL_EXCEPTION_HANDLER", False):
        install_global_exception_handler(enhanced_handler)

    return enhanced_handler


def install_global_exception_handler(error_handler: EnhancedErrorHandler):
    """
    🌍 Installiert globalen Exception-Handler für alle unbehandelten Exceptions
    """

    def global_exception_handler(exc_type, exc_value, exc_traceback):
        """Globaler Exception-Handler für sys.excepthook"""
        if issubclass(exc_type, KeyboardInterrupt):
            # Lasse KeyboardInterrupt durch
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        # Andere Exceptions durch Enhanced Handler behandeln
        context = {
            "global_handler": True,
            "exception_type": exc_type.__name__,
            "main_thread": threading.current_thread() == threading.main_thread(),
        }

        # Async Exception Handling in Event Loop (falls möglich)
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(error_handler.handle_exception(exc_value, context))
        except RuntimeError:
            # Kein Event Loop - verwende Sync-Logging
            error_handler.logger.critical(
                f"🌍 GLOBALE EXCEPTION: {exc_type.__name__}: {exc_value}"
            )
            error_handler.exception_monitor.record_exception(exc_value, context)

    # Exception-Handler installieren
    sys.excepthook = global_exception_handler
    error_handler.logger.info("🌍 Globaler Exception-Handler installiert")


# ========================================
# VERWENDUNGSBEISPIELE UND DOKUMENTATION
# ========================================

"""
🎯 VERWENDUNGSBEISPIELE:

1. BASIS-INTEGRATION:
```python
from handlers.enhanced_error_handler import create_enhanced_error_handler

# Error Handler erstellen
error_handler = create_enhanced_error_handler(config)

# In Command Integration verwenden
command_integration.error_handler = error_handler
```

2. DECORATOR-VERWENDUNG:
```python
@error_handler.handle_async_exceptions("DownloadHandler", "youtube_download")
async def download_youtube_video(update, context):
    # Automatische Exception-Behandlung
    pass

@error_handler.handle_sync_exceptions("FileUtils", "file_operation")
def process_file(filepath):
    # Automatische Exception-Behandlung
    pass
```

3. MANUELLE EXCEPTION-BEHANDLUNG:
```python
try:
    result = await risky_operation()
except Exception as e:
    exc_id = await error_handler.handle_exception(
        e,
        context={"module": "MyModule", "operation": "risky_op"},
        update=update,
        telegram_context=context
    )
    logger.info(f"Exception behandelt: {exc_id}")
```

4. MONITORING UND STATISTIKEN:
```python
# Statistiken abrufen
stats = error_handler.get_comprehensive_statistics()
print(f"Total Exceptions: {stats['exception_monitor']['total_exceptions']}")

# Gesundheitsbericht erstellen
report = await error_handler.create_health_report()
print(report)

# Letzte Exceptions anzeigen
recent = error_handler.get_recent_exceptions_summary(5)
for exc in recent:
    print(f"{exc['timestamp']}: {exc['type']} - {exc['message_preview']}")
```

5. DEBUG-SESSION-TRACKING:
```python
session_id = "my_operation_123"
error_handler.debug_tracker.start_session(session_id, {"user": "test"})
error_handler.debug_tracker.log_step(session_id, "Step 1", {"data": "value"}, "🔄")
error_handler.debug_tracker.log_step(session_id, "Step 2", emoji="✅")
error_handler.debug_tracker.end_session(session_id)

# Session-Zusammenfassung abrufen
summary = error_handler.export_debug_session(session_id)
```

🏆 FEATURES:

✅ Umfassendes Exception-Monitoring mit Kategorisierung
✅ Step-by-Step Debug-Tracking mit Emojis
✅ Automatische Recovery-Strategien für verschiedene Error-Typen
✅ Performance-Monitoring und Statistiken
✅ Thread-Safe Operations
✅ Telegram-Integration mit benutzerfreundlichen Nachrichten
✅ Decorator-Pattern für automatisches Error-Handling
✅ Export-Funktionen für Analyse
✅ Konfigurierbare Logging-Level und Modi
✅ Globaler Exception-Handler (optional)
✅ Cleanup-Funktionen für alte Daten

🎨 EMOJI-SYSTEM:

🚨 Exception aufgetreten        🔍 Monitoring aktiv
📊 Statistiken aktualisiert    🏷️ Kategorisierung
📝 Detailliertes Logging       🔧 Recovery-Versuch
✅ Erfolgreiche Operation       ❌ Fehlgeschlagene Operation
🐛 Debug-Information           📱 Telegram-Benachrichtigung
🌐 Netzwerk-Operation          ⏱️ Timeout-Behandlung
📄 Parsing-Operation           📁 Dateisystem-Operation
💾 Memory-Operation            🔄 Async-Operation
🎯 Funktions-Start             ⚙️ Sync-Operation
🧹 Cleanup-Operation           📈 Performance-Tracking

"""


def try_catch_decorator(
    error_handler_instance: "EnhancedErrorHandler",  # Muss die Instanz des Handlers übergeben
    module: str,
    operation: str,
    start_message: Optional[str] = None,
    success_message: Optional[str] = None,
    log_success: bool = True,
) -> Callable:
    """
    ✨ DECORATOR: Umschließt eine asynchrone Funktion mit zentralem Error Handling und Debug Tracking.

    Wird benötigt, um Redundanz von try...except Blöcken in Handler-Funktionen zu vermeiden.

    Args:
        error_handler_instance: Die Instanz des EnhancedErrorHandler (muss in der
                                Factory-Funktion von CommandIntegration zugewiesen werden!)
        module (str): Name des Moduls (z.B. 'MenuSystem').
        operation (str): Name der Operation (z.B. 'handle_callback').
        ... (weitere optionale Parameter)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            update: Optional[Update] = kwargs.get("update") or (
                args[1] if len(args) > 1 and isinstance(args[1], Update) else None
            )
            context: Optional[ContextTypes.DEFAULT_TYPE] = kwargs.get("context") or (
                args[2]
                if len(args) > 2 and isinstance(args[2], ContextTypes.DEFAULT_TYPE)
                else None
            )

            # --- Setup Debug Session ---
            session_id = f"{operation}_{datetime.now().timestamp()}"
            context_data = {
                "user_id": (
                    update.effective_user.id
                    if update and update.effective_user
                    else "N/A"
                ),
                "chat_id": (
                    update.effective_chat.id
                    if update and update.effective_chat
                    else "N/A"
                ),
                "module": module,
                "operation": operation,
            }
            error_handler_instance.debug_tracker.start_session(session_id, context_data)
            context.user_data["session_id"] = (
                session_id  # Speichern für manuelle Schritte
            )

            if start_message:
                error_handler_instance.debug_tracker.log_step(
                    session_id, start_message, emoji="🎯"
                )

            try:
                # --- Execute original function ---
                result = await func(*args, **kwargs)

                # --- Log Success ---
                if log_success and success_message:
                    error_handler_instance.debug_tracker.log_step(
                        session_id, success_message, emoji="✅"
                    )

                return result

            except Exception as e:
                # --- Handle Exception centrally ---
                error_handler_instance.debug_tracker.log_step(
                    session_id,
                    f"Fehler '{e.__class__.__name__}' aufgetreten",
                    emoji="❌",
                )
                await error_handler_instance.handle_exception(
                    exception=e,
                    update=update,
                    context=context,
                    context_data={
                        "module": module,
                        "operation": operation,
                        "session_id": session_id,
                    },
                )
            finally:
                # --- Cleanup Debug Session ---
                error_handler_instance.debug_tracker.end_session(session_id)

        return wrapper

    return decorator
