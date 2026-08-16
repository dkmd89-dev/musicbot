# -*- coding: utf-8 -*-
"""
ERWEITERTE LOGGER MENUE-HANDLER
Modul-spezifische Logger-Verwaltung mit individueller Handler-Kontrolle
Erweiterte Funktionen fuer granulare Logger-Steuerung
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import TelegramError
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Callable
from collections import Counter, defaultdict
from datetime import datetime
import json

from config import Config
from logger import (
    get_module_logger,
    setup_module_logging,
    get_logging_stats,
    enable_module_debug,
    _module_loggers,
    MODULE_EMOJIS,
    LOG_LEVEL_EMOJIS,
)


class ModuleLoggerManager:
    """Verwaltet modul-spezifische Logger und deren Einstellungen"""

    def __init__(self, config: Config):
        self.config = config
        self.module_configs = {}
        self.active_modules = set()
        self.config_file = Path("data/module_logger_config.json")
        self._load_module_configs()

    def _load_module_configs(self):
        """Laedt modul-spezifische Logger-Konfigurationen"""
        try:
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    self.module_configs = json.load(f)
            else:
                # Standard-Konfiguration fuer bekannte Module
                self.module_configs = {
                    "CommandIntegration": {
                        "enabled": True,
                        "level": "INFO",
                        "file_handler": True,
                        "console_handler": True,
                        "custom_format": None,
                    },
                    "MenuSystem": {
                        "enabled": True,
                        "level": "INFO",
                        "file_handler": True,
                        "console_handler": True,
                        "custom_format": None,
                    },
                    "NavidromeHandler": {
                        "enabled": True,
                        "level": "DEBUG",
                        "file_handler": True,
                        "console_handler": True,
                        "custom_format": None,
                    },
                    "DownloadHandler": {
                        "enabled": True,
                        "level": "INFO",
                        "file_handler": True,
                        "console_handler": True,
                        "custom_format": None,
                    },
                    "StartHandler": {
                        "enabled": True,
                        "level": "INFO",
                        "file_handler": False,
                        "console_handler": True,
                        "custom_format": None,
                    },
                    "HelpHandler": {
                        "enabled": True,
                        "level": "INFO",
                        "file_handler": False,
                        "console_handler": True,
                        "custom_format": None,
                    },
                }
                self._save_module_configs()
        except Exception as e:
            print(f"Fehler beim Laden der Modul-Konfigurationen: {e}")

    def _save_module_configs(self):
        """Speichert modul-spezifische Logger-Konfigurationen"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.module_configs, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Fehler beim Speichern der Modul-Konfigurationen: {e}")

    def get_module_config(self, module_name: str) -> Dict[str, Any]:
        """Gibt die Konfiguration für ein Modul zurück"""
        return self.module_configs.get(
            module_name,
            {
                "enabled": True,
                "level": "INFO",
                "file_handler": True,
                "console_handler": True,
                "custom_format": None,
            },
        )

    def set_module_config(self, module_name: str, config: Dict[str, Any]):
        """Setzt die Konfiguration für ein Modul"""
        self.module_configs[module_name] = config
        self._save_module_configs()
        self._apply_module_config(module_name)

    def _apply_module_config(self, module_name: str):
        """Wendet die Konfiguration auf einen Logger an"""
        try:
            config = self.get_module_config(module_name)
            logger = logging.getLogger(module_name)

            # Logger aktivieren/deaktivieren
            if config.get("enabled", True):
                level = getattr(logging, config.get("level", "INFO"), logging.INFO)
                logger.setLevel(level)
                logger.disabled = False
            else:
                logger.disabled = True
                return

            # Ziel-Logverzeichnis bestimmen
            log_dir = Path(getattr(self.config, "LOG_DIR", None) or "logs")
            log_dir.mkdir(parents=True, exist_ok=True)

            # Prüfen, welche Handler existieren
            has_file_handler = any(
                isinstance(h, logging.FileHandler) for h in logger.handlers
            )
            has_console_handler = any(
                isinstance(h, logging.StreamHandler)
                and not isinstance(h, logging.FileHandler)
                for h in logger.handlers
            )

            # FileHandler hinzufügen/entfernen
            if config.get("file_handler", True) and not has_file_handler:
                file_path = log_dir / f"{module_name.lower()}.log"
                fh = logging.FileHandler(file_path, encoding="utf-8")
                fh.setLevel(logging.DEBUG)  # immer detailliert in Datei
                if not fh.formatter:
                    fh.setFormatter(
                        logging.Formatter(
                            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                        )
                    )
                logger.addHandler(fh)
            elif not config.get("file_handler", True):
                # vorhandene FileHandler entfernen
                for h in logger.handlers[:]:
                    if isinstance(h, logging.FileHandler):
                        logger.removeHandler(h)

            # ConsoleHandler hinzufügen/entfernen
            if config.get("console_handler", True) and not has_console_handler:
                ch = logging.StreamHandler()
                ch.setLevel(max(logger.level, logging.INFO))
                if not ch.formatter:
                    ch.setFormatter(
                        logging.Formatter("%(levelname)s %(name)s: %(message)s")
                    )
                logger.addHandler(ch)
            elif not config.get("console_handler", True):
                for h in logger.handlers[:]:
                    if isinstance(h, logging.StreamHandler) and not isinstance(
                        h, logging.FileHandler
                    ):
                        logger.removeHandler(h)

        except Exception as e:
            print(
                f"❌ Fehler beim Anwenden der Modul-Konfiguration für {module_name}: {e}"
            )

    def get_active_modules(self) -> Set[str]:
        """Gibt alle aktiven Module zurück"""
        active_modules = set()

        # Durchsuche alle Logger
        for name in logging.Logger.manager.loggerDict:
            logger = logging.getLogger(name)
            if logger.handlers and not logger.disabled:
                active_modules.add(name)

        # Füge konfigurierte Module hinzu
        for module_name in self.module_configs:
            if self.module_configs[module_name].get("enabled", True):
                active_modules.add(module_name)

        return active_modules

    def get_module_log_file(self, module_name: str) -> Optional[Path]:
        """Gibt den Log-Datei-Pfad fuer ein Modul zurueck"""
        log_dir = Path(getattr(self.config, "LOG_DIR", "logs"))

        # Suche nach modulspezifischen Log-Dateien
        possible_files = [
            log_dir / f"{module_name.lower()}.log",
            log_dir / f"{module_name}.log",
            log_dir / f"bot_{module_name.lower()}.log",
        ]

        for file_path in possible_files:
            if file_path.exists():
                return file_path

        # Fallback zur Haupt-Log-Datei
        main_log = log_dir / "bot.log"
        return main_log if main_log.exists() else None


class EnhancedLoggerMenuHandler:
    """
    Erweiterte Logger-Menü-Verwaltung angepasst an das neue logger.py System
    """

    def __init__(self, config: Config, logger_factory: Callable = None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger

        # Setup separates Logging für dieses Modul
        log_path = (
            Path(getattr(self.config, "LOG_DIR", "logs"))
            / "enhanced_logger_handler.log"
        )
        self.logger = setup_module_logging(
            "EnhancedLoggerHandler",
            str(log_path),
            "DEBUG",
            use_colors=True,
            use_emojis=True,
        )

        self.logger.info("🚀 Enhanced Logger Menu Handler initialisiert")

        # Module Manager für dynamische Logger-Verwaltung
        self.module_manager = ModuleLoggerManager(config)

        # Statistics Tracker
        # self.stats_tracker = LoggerStatsTracker() # Auskommentiert, da nicht verwendet

        # Cache für UI-Performance
        self.ui_cache = {}
        self.cache_ttl = 30  # 30 Sekunden Cache

        # Log-Levels für die Validierung
        self.log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        self.ITEMS_PER_PAGE = 10  # Hinzugefügt für Paginierung

    async def _safe_edit_message(
        self, update: Update, text: str, reply_markup: InlineKeyboardMarkup = None
    ):
        """Bearbeitet die Nachricht sicher und ignoriert 'Message is not modified'."""
        try:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
            )
        except TelegramError as e:
            if "Message is not modified" in str(e):
                try:
                    await update.callback_query.answer("🔄 Keine Änderungen")
                except TelegramError:
                    pass
            else:
                raise

    # === HAUPT-MENÜ FUNKTIONEN ===

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """📊 Zeigt das Logger-Hauptmenü"""
        try:
            # Aktuelle Statistiken sammeln
            global_stats = get_logging_stats()
            module_count = global_stats.get("total_modules", 0)

            # Globales Log-Level ermitteln
            root_logger = logging.getLogger()
            current_level = logging.getLevelName(root_logger.level)

            menu_text = f"""📊 Enhanced Logger Verwaltung

🌐 Globales Level: {current_level}
📦 Aktive Module: {module_count}
📁 Log-Verzeichnis: {getattr(self.config, 'LOG_DIR', 'logs')}

📋 Verfügbare Aktionen:"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🌍 Globales Level", callback_data="logger_global_level"
                        ),
                        InlineKeyboardButton(
                            "📦 Module verwalten", callback_data="logger_modules_list"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "📁 Log-Dateien", callback_data="logger_files_list"
                        ),
                        InlineKeyboardButton(
                            "📈 Statistiken", callback_data="logger_global_stats"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "⚡ Handler-Verwaltung",
                            callback_data="logger_handlers_list",
                        ),
                        InlineKeyboardButton(
                            "🧹 Bereinigung", callback_data="logger_cleanup_menu"
                        ),
                    ],
                    [InlineKeyboardButton("🔙 Zurück", callback_data="menu:admin")],
                ]
            )

            await update.callback_query.edit_message_text(
                menu_text, reply_markup=keyboard
            )

        except TelegramError as e:
            self.logger.error(f"❌ Fehler beim Anzeigen des Logger-Hauptmenüs: {e}")

    # === MODUL-VERWALTUNG ===

    async def show_modules_list(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0
    ):
        """📦 Zeigt Liste aller aktiven Module (mit Paginierung)"""
        try:
            if not _module_loggers:
                menu_text = "📦 Keine aktiven Module gefunden"
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔙 Zurück", callback_data="logger_main_menu"
                            )
                        ]
                    ]
                )
                await update.callback_query.edit_message_text(
                    menu_text, reply_markup=keyboard
                )
                return

            # --- PAGINIERUNG LOGIK START ---
            all_modules = sorted(list(_module_loggers.items()))
            total_modules = len(all_modules)
            total_pages = (
                total_modules + self.ITEMS_PER_PAGE - 1
            ) // self.ITEMS_PER_PAGE

            # Stelle sicher, dass die Seite gültig ist
            page = max(0, min(page, total_pages - 1))

            start_index = page * self.ITEMS_PER_PAGE
            end_index = start_index + self.ITEMS_PER_PAGE
            modules_to_display = all_modules[start_index:end_index]

            menu_text = f"📦 Aktive Module ({page + 1}/{total_pages}) - Gesamt: {total_modules}\n\n"
            # --- PAGINIERUNG LOGIK ENDE ---

            module_buttons = []

            for module_name, enhanced_logger in modules_to_display:  # Geändert
                emoji = MODULE_EMOJIS.get(module_name, "📝")

                # Modul-Statistiken
                stats = enhanced_logger.get_stats()
                total_logs = stats.get("total_logs", 0)

                # --- LOG-LEVEL ANZEIGE START ---
                current_level_name = logging.getLevelName(enhanced_logger.logger.level)
                level_emoji = LOG_LEVEL_EMOJIS.get(current_level_name, "❔")
                # --- LOG-LEVEL ANZEIGE ENDE ---

                button_text = f"{emoji} {module_name} ({level_emoji} {current_level_name}) ({total_logs} Logs)"  # Geändert

                module_buttons.append(
                    [
                        InlineKeyboardButton(
                            button_text,
                            callback_data=f"logger_module_detail_{module_name}",
                        )
                    ]
                )

            # Control Buttons
            control_buttons = [
                [
                    InlineKeyboardButton(
                        "🟢 Alle aktivieren", callback_data="logger_enable_all"
                    ),
                    InlineKeyboardButton(
                        "🔴 Alle deaktivieren", callback_data="logger_disable_all"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "➕ Modul hinzufügen", callback_data="logger_add_module"
                    )
                ],
                [InlineKeyboardButton("🔙 Zurück", callback_data="logger_main_menu")],
            ]

            # --- PAGINIERUNG BUTTONS START ---
            pagination_row = []
            if page > 0:
                pagination_row.append(
                    InlineKeyboardButton(
                        "⬅️ Zurück", callback_data=f"logger_modules_page_{page - 1}"
                    )
                )

            pagination_row.append(
                InlineKeyboardButton(
                    f"ℹ️ {page + 1}/{total_pages}", callback_data="logger_modules_info"
                )
            )

            if (page + 1) < total_pages:
                pagination_row.append(
                    InlineKeyboardButton(
                        "Vor ➡️", callback_data=f"logger_modules_page_{page + 1}"
                    )
                )

            if pagination_row:
                # Füge Paginierung über den Control-Buttons ein
                module_buttons.extend([pagination_row])
            # --- PAGINIERUNG BUTTONS ENDE ---

            module_buttons.extend(control_buttons)
            keyboard = InlineKeyboardMarkup(module_buttons)

            await update.callback_query.edit_message_text(
                menu_text, reply_markup=keyboard
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Anzeigen der Module-Liste: {e}")

    async def show_module_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, module_name: str
    ):
        """📝 Zeigt Details für ein spezifisches Modul"""
        try:
            if module_name not in _module_loggers:
                await update.callback_query.answer("❌ Modul nicht gefunden")
                return

            enhanced_logger = _module_loggers[module_name]
            stats = enhanced_logger.get_stats()

            # Modul-Info zusammenstellen
            emoji = MODULE_EMOJIS.get(module_name, "📝")
            current_level = logging.getLevelName(enhanced_logger.logger.level)

            runtime_hours = stats.get("runtime_seconds", 0) / 3600
            logs_per_minute = stats.get("logs_per_second", 0) * 60

            detail_text = f"""{emoji} Modul: {module_name}

Aktuelles Level: {current_level}
Laufzeit: {runtime_hours:.1f}h
Logs pro Minute: {logs_per_minute:.1f}

Statistiken:
• Debug: {stats.get('debug_count', 0)}
• Info: {stats.get('info_count', 0)}  
• Warning: {stats.get('warning_count', 0)}
• Error: {stats.get('error_count', 0)}
• Critical: {stats.get('critical_count', 0)}

Gesamt: {stats.get('total_logs', 0)} Logs"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🎯 Level ändern",
                            callback_data=f"logger_module_level_{module_name}",
                        ),
                        InlineKeyboardButton(
                            "🔄 Toggle Debug",
                            callback_data=f"logger_module_toggle_{module_name}",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "📊 Performance",
                            callback_data=f"logger_module_perf_{module_name}",
                        ),
                        InlineKeyboardButton(
                            "🧹 Reset Stats",
                            callback_data=f"logger_module_reset_{module_name}",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "🔙 Module-Liste", callback_data="logger_modules_list"
                        )
                    ],
                ]
            )

            await update.callback_query.edit_message_text(
                detail_text, reply_markup=keyboard
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Anzeigen der Modul-Details: {e}")

    async def show_comprehensive_statistics(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """📈 Zeigt umfassende Logger-Statistiken"""
        try:
            # Sammle alle verfügbaren Statistiken
            stats = await self._collect_comprehensive_stats()

            stats_text = (
                "📊 Umfassende Logger-Statistiken\n\n"
                "System-Übersicht:\n"
                f"• Aktive Module: {stats['active_modules']}\n"
                f"• Gesamte Handler: {stats['total_handlers']}\n"
                f"• Log-Dateien: {stats['log_files_count']}\n"
                f"• Gesamt-Speicher: {stats['total_log_size_mb']:.1f} MB\n\n"
                "Top 5 aktivste Module:\n"
            )

            for i, (module, count) in enumerate(stats["top_modules"], 1):
                stats_text += f"{i}. {module}: {count:,} Logs\n"

            stats_text += (
                "\nLog-Level Verteilung (Gesamt):\n"
                f"• 🔍 Debug: {stats['level_distribution'].get('DEBUG', 0):,}\n"
                f"• ℹ️ Info: {stats['level_distribution'].get('INFO', 0):,}\n"
                f"• ⚠️ Warning: {stats['level_distribution'].get('WARNING', 0):,}\n"
                f"• ❌ Error: {stats['level_distribution'].get('ERROR', 0):,}\n"
                f"• 💥 Critical: {stats['level_distribution'].get('CRITICAL', 0):,}\n\n"
                "Performance-Metriken:\n"
                f"• Logs/Sekunde (Durchschnitt): {stats['avg_logs_per_second']:.2f}\n"
                f"• Größte Log-Datei: {stats['largest_log_file']} ({stats['largest_log_size_mb']:.1f} MB)\n"
                f"• Älteste Log-Datei: {stats['oldest_log_file']} ({stats['oldest_log_age_days']} Tage)"
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "Modul-Details", callback_data="logger_stats_modules"
                    ),
                    InlineKeyboardButton(
                        "Datei-Statistiken", callback_data="logger_stats_files"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "Performance", callback_data="logger_stats_performance"
                    ),
                    InlineKeyboardButton("Trends", callback_data="logger_stats_trends"),
                ],
                [
                    InlineKeyboardButton(
                        "Aktualisieren", callback_data="logger_global_stats"
                    ),
                    InlineKeyboardButton("Zurück", callback_data="logger_main_menu"),
                ],
            ]

            self.logger.info("📊 Umfassende Statistiken angezeigt")
            await self._safe_edit_message(
                update, stats_text.strip(), InlineKeyboardMarkup(keyboard)
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Sammeln der Statistiken: {e}")
            await self._show_error_message(
                update, f"Fehler beim Laden der Statistiken: {str(e)}"
            )

    async def toggle_module(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, module_name: str
    ):
        """Schaltet ein Modul ein/aus"""
        try:
            config = self.module_manager.get_module_config(module_name)
            current_state = config.get("enabled", True)
            new_state = not current_state

            # Konfiguration aktualisieren
            config["enabled"] = new_state
            self.module_manager.set_module_config(module_name, config)

            action = "aktiviert" if new_state else "deaktiviert"
            self.logger.info(f"🔧 Modul {module_name} wurde {action}")

            # Erfolgs-Nachricht
            status_icon = "✅" if new_state else "❌"
            success_text = (
                f"{status_icon} Modul {action}!\n\n"
                f"Modul: {module_name}\n"
                f"Neuer Status: {'Aktiv' if new_state else 'Inaktiv'}\n"
                f"Zeitpunkt: {datetime.now().strftime('%H:%M:%S')}\n\n"
                f"Die Änderung ist sofort wirksam!"
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Modul-Details",
                            callback_data=f"logger_module_detail_{module_name}",
                        ),
                        InlineKeyboardButton(
                            "Zurück", callback_data="logger_modules_list"
                        ),
                    ]
                ]
            )

            self.logger.info(f"🔁 Modul-Zustand geändert: {module_name} -> {action}")
            await self._safe_edit_message(update, success_text.strip(), keyboard)

        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Umschalten des Moduls {module_name}: {e}"
            )
            await self._show_error_message(update, f"Fehler beim Umschalten: {str(e)}")

    async def show_module_level_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, module_name: str
    ):
        """Zeigt Log-Level-Auswahlmenü für ein Modul"""
        try:
            config = self.module_manager.get_module_config(module_name)
            current_level = config.get("level", "INFO")

            menu_text = (
                f"📊 Log-Level für {module_name}\n\n"
                f"Aktuelles Level: {current_level}\n\n"
                f"Wähle ein neues Level:"
            )

            keyboard = []
            for level_name in self.log_levels:
                prefix = "✅ " if level_name == current_level else "⚪ "
                icon = self._get_level_icon(level_name)
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"{prefix}{icon} {level_name}",
                            callback_data=f"logger_set_module_level_{module_name}_{level_name}",
                        )
                    ]
                )

            keyboard.append(
                [
                    InlineKeyboardButton(
                        "Zurück", callback_data=f"logger_module_detail_{module_name}"
                    )
                ]
            )

            self.logger.info(f"📊 Level-Menü angezeigt: {module_name}")
            await self._safe_edit_message(
                update, menu_text.strip(), InlineKeyboardMarkup(keyboard)
            )

        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Laden des Level-Menüs für {module_name}: {e}"
            )
            await self._show_error_message(
                update, f"Fehler beim Laden des Level-Menüs: {str(e)}"
            )

    async def set_module_level(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        module_name: str,
        level_name: str,
    ):
        """Setzt das Log-Level für ein spezifisches Modul"""
        try:
            if level_name not in self.log_levels:
                await self._show_error_message(
                    update, f"Ungültiges Log-Level: {level_name}"
                )
                return

            # Konfiguration aktualisieren
            config = self.module_manager.get_module_config(module_name)
            old_level = config.get("level", "INFO")
            config["level"] = level_name
            self.module_manager.set_module_config(module_name, config)

            self.logger.info(
                f"📊 Log-Level für {module_name} geändert: {old_level} → {level_name}"
            )

            # Erfolgs-Nachricht
            level_icon = self._get_level_icon(level_name)
            success_text = (
                "✅ Log-Level erfolgreich geändert!\n\n"
                f"Modul: {module_name}\n"
                f"Altes Level: {self._get_level_icon(old_level)} {old_level}\n"
                f"Neues Level: {level_icon} {level_name}\n"
                f"Zeitpunkt: {datetime.now().strftime('%H:%M:%S')}\n\n"
                "Die Änderung ist sofort aktiv!"
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Anderes Level",
                            callback_data=f"logger_module_level_{module_name}",
                        ),
                        InlineKeyboardButton(
                            "Modul-Details",
                            callback_data=f"logger_module_detail_{module_name}",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "Zurück", callback_data="logger_modules_list"
                        )
                    ],
                ]
            )

            self.logger.info(f"📝 Log-Level gesetzt: {module_name} -> {level_name}")
            await self._safe_edit_message(update, success_text.strip(), keyboard)

        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Setzen des Log-Levels für {module_name}: {e}"
            )
            await self._show_error_message(
                update, f"Fehler beim Setzen des Log-Levels: {str(e)}"
            )

    # === LOG-DATEIEN VERWALTUNG ===

    async def show_log_files_list(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt Liste aller Log-Dateien"""
        try:
            log_dir = Path(getattr(self.config, "LOG_DIR", "logs"))

            if not log_dir.exists():
                await update.callback_query.edit_message_text(
                    f"📁 Log-Verzeichnis nicht gefunden: {log_dir}"
                )
                return

            # Sammle alle Log-Dateien
            log_files = list(log_dir.glob("*.log"))

            if not log_files:
                await update.callback_query.edit_message_text(
                    "📁 Keine Log-Dateien gefunden."
                )
                return

            files_text = "📁 Verfügbare Log-Dateien:\n\n"
            keyboard = []

            # Sortiere Dateien nach Größe
            sorted_files = sorted(
                log_files, key=lambda f: f.stat().st_size, reverse=True
            )

            total_size = 0
            for i, file_path in enumerate(sorted_files, 1):
                try:
                    stat = file_path.stat()
                    size_mb = stat.st_size / (1024 * 1024)
                    total_size += stat.st_size
                    mod_time = datetime.fromtimestamp(stat.st_mtime).strftime(
                        "%d.%m %H:%M"
                    )

                    files_text += f"{i}. {file_path.name}\n"
                    files_text += f"   {size_mb:.1f} MB • {mod_time}\n\n"

                    # Button für jede Datei
                    display_name = file_path.name
                    if len(display_name) > 25:
                        display_name = display_name[:22] + "..."

                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"Datei: {display_name}",
                                callback_data=f"logger_file_detail_{file_path.name}",
                            )
                        ]
                    )

                except Exception as e:
                    self.logger.warning(
                        f"⚠️ Fehler beim Lesen der Datei {file_path}: {e}"
                    )

            # Zusammenfassung
            total_size_mb = total_size / (1024 * 1024)
            files_text += f"Gesamt: {len(sorted_files)} Dateien, {total_size_mb:.1f} MB"

            # Navigation
            keyboard.extend(
                [
                    [
                        InlineKeyboardButton(
                            "Alle bereinigen",
                            callback_data="logger_cleanup_all_files",
                        ),
                        InlineKeyboardButton(
                            "Datei-Statistiken", callback_data="logger_files_stats"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "Aktualisieren", callback_data="logger_files_list"
                        ),
                        InlineKeyboardButton(
                            "Zurück", callback_data="logger_main_menu"
                        ),
                    ],
                ]
            )

            self.logger.info("📁 Log-Dateiliste angezeigt")
            await self._safe_edit_message(
                update, files_text.strip(), InlineKeyboardMarkup(keyboard)
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Log-Dateien: {e}")
            await self._show_error_message(
                update, f"Fehler beim Laden der Log-Dateien: {str(e)}"
            )

    async def show_log_file_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, filename: str
    ):
        """Zeigt Details zu einer spezifischen Log-Datei"""
        try:
            log_dir = Path(getattr(self.config, "LOG_DIR", "logs"))
            file_path = log_dir / filename

            if not file_path.exists():
                await update.callback_query.edit_message_text(
                    f"❌ Log-Datei nicht gefunden: {filename}"
                )
                return

            # Datei-Statistiken
            stat = file_path.stat()
            size_mb = stat.st_size / (1024 * 1024)
            mod_time = datetime.fromtimestamp(stat.st_mtime).strftime(
                "%d.%m.%Y %H:%M:%S"
            )

            # Lese letzte Zeilen für Vorschau
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()

                total_lines = len(lines)
                preview_lines = lines[-5:] if len(lines) > 5 else lines

                # Analysiere Log-Level Verteilung
                level_counts = Counter()
                for line in lines:
                    for level in self.log_levels:
                        if level in line:
                            level_counts[level] += 1
                            break

            except Exception as e:
                self.logger.warning(f"⚠️ Fehler beim Lesen der Datei {filename}: {e}")
                total_lines = 0
                preview_lines = []
                level_counts = Counter()

            # Formatiere Details
            detail_text = (
                f"📄 Log-Datei: {filename}\n\n"
                f"Datei-Informationen:\n"
                f"• Größe: {size_mb:.2f} MB\n"
                f"• Zeilen: {total_lines:,}\n"
                f"• Letzte Änderung: {mod_time}\n\n"
                f"Log-Level Verteilung:\n"
            )

            for level in self.log_levels:
                count = level_counts.get(level, 0)
                percentage = (count / max(sum(level_counts.values()), 1)) * 100
                icon = self._get_level_icon(level)
                detail_text += f"• {icon} {level}: {count:,} ({percentage:.1f}%)\n"

            # Vorschau der letzten Zeilen
            if preview_lines:
                detail_text += "\nLetzte Einträge:\n"
                for line in preview_lines:
                    clean_line = line.strip()[:100]
                    detail_text += f"{clean_line}\n"

            keyboard = [
                [
                    InlineKeyboardButton(
                        "Vollständig anzeigen",
                        callback_data=f"logger_file_show_{filename}",
                    ),
                    InlineKeyboardButton(
                        "Download", callback_data=f"logger_file_download_{filename}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "Filtern", callback_data=f"logger_file_filter_{filename}"
                    ),
                    InlineKeyboardButton(
                        "Datei löschen",
                        callback_data=f"logger_file_delete_{filename}",
                    ),
                ],
                [InlineKeyboardButton("Zurück", callback_data="logger_files_list")],
            ]

            self.logger.info(f"📄 Log-Datei-Details angezeigt: {filename}")
            await self._safe_edit_message(
                update, detail_text.strip(), InlineKeyboardMarkup(keyboard)
            )

        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Laden der Datei-Details für {filename}: {e}"
            )
            await self._show_error_message(
                update, f"Fehler beim Laden der Datei-Details: {str(e)}"
            )

    # === ERWEITERTE STATISTIKEN ===

    async def _collect_comprehensive_stats(self) -> Dict[str, Any]:
        """Sammelt umfassende Statistiken vom gesamten Logger-System"""
        try:
            active_modules = self.module_manager.get_active_modules()
            log_dir = Path(getattr(self.config, "LOG_DIR", "logs"))

            # Basis-Statistiken
            stats = {
                "active_modules": len(active_modules),
                "total_handlers": 0,
                "log_files_count": 0,
                "total_log_size_mb": 0,
                "level_distribution": Counter(),
                "top_modules": [],
                "avg_logs_per_second": 0,
                "largest_log_file": "Keine",
                "largest_log_size_mb": 0,
                "oldest_log_file": "Keine",
                "oldest_log_age_days": 0,
            }

            # Handler-Statistiken sammeln
            module_log_counts = Counter()
            for module_name in active_modules:
                logger = logging.getLogger(module_name)
                stats["total_handlers"] += len(logger.handlers)

                # Versuche Log-Counts aus Enhanced Logger zu bekommen
                enhanced_stats = get_logging_stats()
                if enhanced_stats and "modules" in enhanced_stats:
                    module_stats = enhanced_stats["modules"].get(module_name, {})
                    module_log_counts[module_name] = module_stats.get("total_logs", 0)

            stats["top_modules"] = module_log_counts.most_common(5)

            # Log-Dateien analysieren
            if log_dir.exists():
                log_files = list(log_dir.glob("*.log"))
                stats["log_files_count"] = len(log_files)

                largest_size = 0
                oldest_time = float("inf")
                total_size = 0

                for file_path in log_files:
                    try:
                        file_stat = file_path.stat()
                        file_size = file_stat.st_size
                        file_time = file_stat.st_mtime

                        total_size += file_size

                        if file_size > largest_size:
                            largest_size = file_size
                            stats["largest_log_file"] = file_path.name
                            stats["largest_log_size_mb"] = file_size / (1024 * 1024)

                        if file_time < oldest_time:
                            oldest_time = file_time
                            stats["oldest_log_file"] = file_path.name
                            age_seconds = datetime.now().timestamp() - file_time
                            stats["oldest_log_age_days"] = int(age_seconds // 86400)

                        # Analysiere Log-Level in der Datei (Sample)
                        await self._analyze_log_file_levels(
                            file_path, stats["level_distribution"]
                        )

                    except Exception as e:
                        self.logger.warning(
                            f"⚠️ Fehler beim Analysieren der Datei {file_path}: {e}"
                        )

                stats["total_log_size_mb"] = total_size / (1024 * 1024)

            # Performance-Metriken berechnen
            total_logs = sum(stats["level_distribution"].values())
            if total_logs > 0 and stats["oldest_log_age_days"] > 0:
                stats["avg_logs_per_second"] = total_logs / (
                    stats["oldest_log_age_days"] * 86400
                )

            return stats

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Sammeln der Statistiken: {e}")
            return {"error": str(e)}

    async def _analyze_log_file_levels(
        self, file_path: Path, level_counter: Counter, max_lines: int = 1000
    ):
        """Analysiert Log-Level in einer Datei (Sample)"""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines_analyzed = 0
                for line in f:
                    if lines_analyzed >= max_lines:
                        break

                    # Suche nach Log-Level patterns
                    for level in self.log_levels:
                        if f" {level} " in line or f"[{level}]" in line:
                            level_counter[level] += 1
                            break

                    lines_analyzed += 1

        except Exception as e:
            self.logger.debug(f"🔍 Fehler beim Analysieren von {file_path}: {e}")

    # === CLEANUP-FUNKTIONEN ===

    async def show_cleanup_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt Cleanup-Optionen"""
        try:
            log_dir = Path(
                getattr(self.config, "LOG_DIR", "/mnt/media/musiccenter/logs")
            )

            # Sammle Cleanup-Statistiken
            cleanup_stats = await self._get_cleanup_statistics(log_dir)

            cleanup_text = (
                "🧹 Logger-Bereinigung\n\n"
                "Aktuelle Situation:\n"
                f"• Log-Dateien: {cleanup_stats['total_files']}\n"
                f"• Gesamt-Größe: {cleanup_stats['total_size_mb']:.1f} MB\n"
                f"• Älteste Datei: {cleanup_stats['oldest_days']} Tage alt\n"
                f"• Größte Datei: {cleanup_stats['largest_size_mb']:.1f} MB\n\n"
                "Bereinigungsoptionen:"
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "Alte Logs (>30 Tage)", callback_data="logger_cleanup_old"
                    ),
                    InlineKeyboardButton(
                        "Große Dateien (>10MB)", callback_data="logger_cleanup_large"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "Leere Dateien", callback_data="logger_cleanup_empty"
                    ),
                    InlineKeyboardButton(
                        "Rotierte Logs", callback_data="logger_cleanup_rotated"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "Alle bereinigen", callback_data="logger_cleanup_all_confirm"
                    ),
                    InlineKeyboardButton(
                        "Archivieren", callback_data="logger_cleanup_archive"
                    ),
                ],
                [InlineKeyboardButton("Zurück", callback_data="logger_main_menu")],
            ]

            self.logger.info("🧹 Cleanup-Menü angezeigt")
            await self._safe_edit_message(
                update, cleanup_text.strip(), InlineKeyboardMarkup(keyboard)
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden des Cleanup-Menüs: {e}")
            await self._show_error_message(
                update, f"Fehler beim Laden des Cleanup-Menüs: {str(e)}"
            )

    async def _get_cleanup_statistics(self, log_dir: Path) -> Dict[str, Any]:
        """Sammelt Cleanup-relevante Statistiken"""
        try:
            if not log_dir.exists():
                return {
                    "total_files": 0,
                    "total_size_mb": 0,
                    "oldest_days": 0,
                    "largest_size_mb": 0,
                }

            log_files = list(log_dir.glob("*.log*"))  # Inkludiert rotierte Logs

            if not log_files:
                return {
                    "total_files": 0,
                    "total_size_mb": 0,
                    "oldest_days": 0,
                    "largest_size_mb": 0,
                }

            total_size = 0
            oldest_time = float("inf")
            largest_size = 0

            for file_path in log_files:
                try:
                    stat = file_path.stat()
                    total_size += stat.st_size

                    if stat.st_mtime < oldest_time:
                        oldest_time = stat.st_mtime

                    if stat.st_size > largest_size:
                        largest_size = stat.st_size

                except Exception as e:
                    self.logger.debug(f"🔍 Fehler beim Stat von {file_path}: {e}")

            # Berechne Alter der ältesten Datei
            oldest_days = 0
            if oldest_time != float("inf"):
                age_seconds = datetime.now().timestamp() - oldest_time
                oldest_days = int(age_seconds // 86400)

            return {
                "total_files": len(log_files),
                "total_size_mb": total_size / (1024 * 1024),
                "oldest_days": oldest_days,
                "largest_size_mb": largest_size / (1024 * 1024),
            }

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Sammeln der Cleanup-Statistiken: {e}")
            return {
                "total_files": 0,
                "total_size_mb": 0,
                "oldest_days": 0,
                "largest_size_mb": 0,
            }

    # === UTILITY FUNCTIONS ===

    def _get_level_icon(self, level: str) -> str:
        """Gibt Icon für Log-Level zurück"""
        icons = {
            "DEBUG": "🔍",
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "ERROR": "❌",
            "CRITICAL": "💥",
        }
        return icons.get(level, "📝")

    # === ZUSÄTZLICHE HILFSMETHODEN FÜR FEHLENDE CALLBACKS (PLAIN TEXT) ===

    async def add_module(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Platzhalter zum Hinzufügen eines Moduls (ohne interaktive Eingabe)."""
        self.logger.info("➕ Anfrage: Neues Modul hinzufügen")
        text = (
            "➕ Neues Modul\n\n"
            "Diese Funktion erfordert eine Benennung des Moduls.\n"
            "Bitte erweitere die Anwendung um einen Eingabedialog oder konfiguriere data/module_logger_config.json manuell."
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Zurück", callback_data="logger_modules_list")]]
        )
        await self._safe_edit_message(update, text, keyboard)

    async def enable_all_modules(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Aktiviert alle bekannten Module."""
        self.logger.info("✅ Alle Module aktivieren")
        for name in list(self.module_manager.module_configs.keys()):
            cfg = self.module_manager.get_module_config(name)
            cfg["enabled"] = True
            self.module_manager.set_module_config(name, cfg)
        await update.callback_query.edit_message_text(
            text="✅ Alle Module wurden aktiviert.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Zurück", callback_data="logger_modules_list")]]
            ),
        )

    async def disable_all_modules(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Deaktiviert alle bekannten Module."""
        self.logger.info("⛔ Alle Module deaktivieren")
        for name in list(self.module_manager.module_configs.keys()):
            cfg = self.module_manager.get_module_config(name)
            cfg["enabled"] = False
            self.module_manager.set_module_config(name, cfg)
        await update.callback_query.edit_message_text(
            text="⛔ Alle Module wurden deaktiviert.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Zurück", callback_data="logger_modules_list")]]
            ),
        )

    async def show_log_files_stats(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt einfache Statistik zu Log-Dateien."""
        self.logger.info("📁 Datei-Statistiken anzeigen")
        log_dir = Path(getattr(self.config, "LOG_DIR", "logs"))
        if not log_dir.exists():
            await update.callback_query.edit_message_text(
                text=f"📁 Log-Verzeichnis nicht gefunden: {log_dir}",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Zurück", callback_data="logger_main_menu")]]
                ),
            )
            return
        log_files = list(log_dir.glob("*.log*"))
        total = len(log_files)
        total_size = sum((f.stat().st_size for f in log_files), 0) / (1024 * 1024)
        text = (
            "📊 Datei-Statistiken\n\n"
            f"Anzahl Dateien: {total}\n"
            f"Gesamtgröße: {total_size:.1f} MB"
        )
        await self._safe_edit_message(
            update,
            text,
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("Zurück", callback_data="logger_files_list")]]
            ),
        )

    async def download_log_file(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, filename: str
    ):
        """Platzhalter für Download einer Log-Datei (nicht implementiert)."""
        self.logger.info(f"⬇️ Download angefragt für Datei: {filename}")
        await self._safe_edit_message(
            update,
            (
                "⬇️ Download\n\n"
                "Der Datei-Download wird aktuell nicht unterstützt. Bitte lade die Datei direkt vom Server."
            ),
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Zurück", callback_data="logger_file_detail_" + filename
                        )
                    ]
                ]
            ),
        )

    # === FEINGRANULARE HANDLER-UNTERMENÜS (Plain Text) ===
    async def configure_handlers(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt Hinweise zur Handler-Konfiguration und aktuelle Übersicht."""
        self.logger.info("🛠️ Handler konfigurieren geöffnet")
        root_logger = logging.getLogger()
        all_loggers = [
            logging.getLogger(name) for name in logging.Logger.manager.loggerDict
        ]
        text = (
            "🛠️ Handler konfigurieren\n\n"
            f"Root-Level: {logging.getLevelName(root_logger.getEffectiveLevel())}\n"
            f"Anzahl bekannter Logger: {len(all_loggers) + 1}\n\n"
            "Hinweis: Das Hinzufügen/Entfernen von Handlern erfolgt in der logger-Initialisierung.\n"
            "Nutze 'Handler-Details' für eine Übersicht der aktuellen Handler."
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Handler-Details", callback_data="logger_handler_details"
                    ),
                    InlineKeyboardButton(
                        "Zurück", callback_data="logger_handlers_list"
                    ),
                ]
            ]
        )
        await update.callback_query.edit_message_text(text=text, reply_markup=keyboard)

    async def handler_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Listet Logger mit Handler-Typen auf (Top 15)."""
        self.logger.info("📊 Handler-Details anzeigen")
        root_logger = logging.getLogger()
        all_loggers = [("<root>", root_logger)] + [
            (name, logging.getLogger(name))
            for name in logging.Logger.manager.loggerDict
        ]
        lines = ["📊 Handler-Details (Top 15):\n"]
        count = 0
        for name, logger in all_loggers:
            if count >= 15:
                break
            if logger.handlers:
                handler_types = [type(h).__name__ for h in logger.handlers]
                lines.append(f"• {name}: {', '.join(handler_types)}")
                count += 1
        if count == 0:
            lines.append("• Keine Logger mit Handlern gefunden")
        text = "\n".join(lines)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Zurück", callback_data="logger_handlers_list")]]
        )
        await update.callback_query.edit_message_text(text=text, reply_markup=keyboard)

    async def add_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Platzhalter zum Hinzufügen eines Handlers."""
        self.logger.info("➕ Handler hinzufügen (Platzhalter)")
        text = (
            "➕ Handler hinzufügen\n\n"
            "Das dynamische Hinzufügen von Handlern wird hier nicht unterstützt.\n"
            "Bitte passe die Logger-Initialisierung (logger.setup) im Projektcode an."
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Zurück", callback_data="logger_handlers_list")]]
        )
        await update.callback_query.edit_message_text(text=text, reply_markup=keyboard)

    async def remove_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Platzhalter zum Entfernen eines Handlers."""
        self.logger.info("🗑️ Handler entfernen (Platzhalter)")
        text = (
            "🗑️ Handler entfernen\n\n"
            "Das dynamische Entfernen von Handlern wird hier nicht unterstützt.\n"
            "Bitte passe die Logger-Initialisierung (logger.setup) im Projektcode an."
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Zurück", callback_data="logger_handlers_list")]]
        )
        await self._safe_edit_message(update, text, keyboard)

    async def reload_handlers(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Versucht, Modul-Konfigurationen erneut anzuwenden (Soft-Reload)."""
        self.logger.info("🔄 Handler neuladen")
        # Re-Applikation bekannter Modulkonfigurationen
        for module_name in list(self.module_manager.module_configs.keys()):
            try:
                self.module_manager._apply_module_config(module_name)
            except Exception as e:
                self.logger.debug(f"Fehler bei Neuladung von {module_name}: {e}")

        await self._safe_edit_message(
            update,
            "🔄 Handler wurden neu angewendet.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("Zurück", callback_data="logger_handlers_list")]]
            ),
        )

    async def _show_error_message(self, update: Update, error_message: str):
        """Zeigt eine formatierte Fehlermeldung"""
        try:
            error_text = (
                "❌ Fehler aufgetreten\n\n"
                f"{error_message}\n\n"
                "Bitte versuche es erneut oder wende dich an den Administrator."
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Erneut versuchen", callback_data="logger_main_menu"
                        ),
                        InlineKeyboardButton("Zurück", callback_data="menu:admin"),
                    ]
                ]
            )

            await update.callback_query.edit_message_text(
                text=error_text.strip(), reply_markup=keyboard
            )
        except Exception as e:
            # Fallback
            await update.callback_query.edit_message_text(
                f"❌ Fehler: {error_message}\n\nBitte erneut versuchen."
            )

    # === ERWEITERTE HANDLER-FUNKTIONEN ===

    async def manage_handlers_advanced(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Erweiterte Handler-Verwaltung"""
        try:
            root_logger = logging.getLogger()
            all_loggers = [
                logging.getLogger(name) for name in logging.Logger.manager.loggerDict
            ]

            # Sammle Handler-Statistiken
            handler_stats = defaultdict(int)
            formatter_stats = defaultdict(int)

            for logger in [root_logger] + all_loggers:
                for handler in logger.handlers:
                    handler_type = type(handler).__name__
                    handler_stats[handler_type] += 1

                    if handler.formatter:
                        formatter_type = type(handler.formatter).__name__
                        formatter_stats[formatter_type] += 1

            handlers_text = (
                "⚡ Erweiterte Handler-Verwaltung\n\nHandler-Typen Übersicht:\n"
            )

            for handler_type, count in handler_stats.items():
                handlers_text += f"• {handler_type}: {count}\n"

            handlers_text += "\nFormatter-Typen:\n"

            for formatter_type, count in formatter_stats.items():
                handlers_text += f"• {formatter_type}: {count}\n"

            handlers_text += (
                "\nGesamt:\n"
                f"• Logger: {len(all_loggers) + 1}\n"
                f"• Handler: {sum(handler_stats.values())}\n"
                f"• Formatter: {sum(formatter_stats.values())}"
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "Handler konfigurieren",
                        callback_data="logger_configure_handlers",
                    ),
                    InlineKeyboardButton(
                        "Handler-Details", callback_data="logger_handler_details"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "Handler hinzufügen", callback_data="logger_add_handler"
                    ),
                    InlineKeyboardButton(
                        "Handler entfernen", callback_data="logger_remove_handler"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "Handler neuladen", callback_data="logger_reload_handlers"
                    ),
                    InlineKeyboardButton("Zurück", callback_data="logger_main_menu"),
                ],
            ]

            self.logger.info("⚙️ Erweiterte Handler-Verwaltung angezeigt")
            await self._safe_edit_message(
                update, handlers_text.strip(), InlineKeyboardMarkup(keyboard)
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler bei erweiterter Handler-Verwaltung: {e}")
            await self._show_error_message(
                update, f"Fehler bei Handler-Verwaltung: {str(e)}"
            )

    # === LEGACY-KOMPATIBILITÄT ===

    async def handle_log_level_change(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Legacy-Funktion für globale Log-Level Änderung"""
        return await self.show_global_level_menu(update, context)

    async def show_global_level_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """🌍 Zeigt Menü für globales Log-Level"""
        try:
            root_logger = logging.getLogger()
            current_level = logging.getLevelName(root_logger.level)

            menu_text = f"""🌍 Globales Log-Level

Aktuelles Level: {current_level}

Verfügbare Level:
• DEBUG - Alle Details (sehr verbose)
• INFO - Normale Informationen
• WARNING - Nur Warnungen und Fehler  
• ERROR - Nur Fehler und kritische Meldungen
• CRITICAL - Nur kritische Fehler"""

            # Log-Level Buttons mit Emojis
            level_buttons = []
            for level_name in self.log_levels:
                emoji = LOG_LEVEL_EMOJIS.get(level_name, "📝")
                is_current = level_name == current_level
                button_text = f"{emoji} {level_name}" + (" ✅" if is_current else "")

                level_buttons.append(
                    [
                        InlineKeyboardButton(
                            button_text,
                            callback_data=f"logger_set_global_level_{level_name}",
                        )
                    ]
                )

            level_buttons.append(
                [InlineKeyboardButton("🔙 Zurück", callback_data="logger_main_menu")]
            )

            keyboard = InlineKeyboardMarkup(level_buttons)

            await update.callback_query.edit_message_text(
                menu_text, reply_markup=keyboard
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Global-Level-Menü: {e}")

    async def set_global_log_level(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, level_name: str
    ):
        """🎯 Setzt das globale Log-Level"""
        try:
            # Validiere Level
            if level_name not in self.log_levels:
                await update.callback_query.answer("❌ Ungültiges Log-Level")
                return

            # Setze globales Level
            root_logger = logging.getLogger()
            old_level = logging.getLevelName(root_logger.level)

            root_logger.setLevel(getattr(logging, level_name))

            self.logger.info(
                f"🌍 Globales Log-Level geändert: {old_level} → {level_name}"
            )

            # Update alle Module-Logger
            for module_name, enhanced_logger in _module_loggers.items():
                enhanced_logger.logger.setLevel(getattr(logging, level_name))

            success_text = f"""✅ Globales Log-Level geändert

Vorher: {old_level}
Jetzt: {level_name}

Betroffen: Alle {len(_module_loggers)} aktiven Module

Die Änderung ist sofort aktiv!"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Andere Level", callback_data="logger_global_level"
                        ),
                        InlineKeyboardButton(
                            "📊 Hauptmenü", callback_data="logger_main_menu"
                        ),
                    ]
                ]
            )

            await update.callback_query.edit_message_text(
                success_text, reply_markup=keyboard
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Setzen des globalen Levels: {e}")
            await update.callback_query.answer("❌ Fehler beim Setzen des Log-Levels")


class LoggerModuleManager:
    """Verwaltet Logger-Module dynamisch (ausgelagert aus der Hauptklasse für Klarheit)"""

    def __init__(self, config: Config, logger_factory: Callable):
        self.config = config
        self.logger_factory = logger_factory
        self.logger = get_module_logger("LoggerModuleManager")

    def create_module_logger(self, module_name: str, log_level: str = "INFO") -> bool:
        """Erstellt einen neuen Logger für ein Modul"""
        try:
            if module_name in _module_loggers:
                self.logger.warning(f"⚠️ Modul {module_name} existiert bereits")
                return False

            # Separates Log-File für das Modul
            log_path = (
                Path(getattr(self.config, "LOG_DIR", "logs"))
                / f"{module_name.lower()}.log"
            )

            setup_module_logging(
                module_name, str(log_path), log_level, use_colors=True, use_emojis=True
            )

            self.logger.info(f"✅ Neuer Logger erstellt: {module_name}")
            return True

        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Erstellen des Loggers {module_name}: {e}"
            )
            return False


class LoggerStatsTracker:
    """Verfolgt Logger-Statistiken über Zeit"""

    def __init__(self):
        self.history = []
        self.start_time = datetime.now()

    def capture_snapshot(self) -> Dict[str, Any]:
        """Erstellt einen Statistik-Snapshot"""
        timestamp = datetime.now()
        global_stats = get_logging_stats()

        snapshot = {
            "timestamp": timestamp.isoformat(),
            "global_stats": global_stats,
            "runtime_minutes": (timestamp - self.start_time).total_seconds() / 60,
        }

        self.history.append(snapshot)

        # Behalte nur letzte 100 Snapshots
        if len(self.history) > 100:
            self.history = self.history[-100:]

        return snapshot


# === FACTORY FUNCTIONS ===


def create_enhanced_logger_handler(
    config: Config, logger_factory: Callable = None
) -> EnhancedLoggerMenuHandler:
    """Factory-Funktion für Enhanced Logger Handler"""
    return EnhancedLoggerMenuHandler(config, logger_factory)


# === INTEGRATION HELPER ===
def integrate_enhanced_logger_handler(command_integration):
    """
    Integriert den erweiterten Logger-Handler in das bestehende System

    Args:
        command_integration: CommandIntegration Instanz
    """
    try:
        # Ersetze den Standard Logger-Handler
        enhanced_handler = create_enhanced_logger_handler(
            command_integration.config, command_integration.logger_factory
        )

        # Registriere beim Menu-System
        if hasattr(command_integration, "menu_system"):
            command_integration.menu_system.set_handlers(
                logger_handler=enhanced_handler
            )

        # Ersetze in Command Integration
        command_integration.logger_handler = enhanced_handler

        print("✅ Erweiterte Logger-Handler erfolgreich integriert")
        return enhanced_handler

    except Exception as e:
        print(f"❌ Fehler bei Integration des erweiterten Logger-Handlers: {e}")
        return None
