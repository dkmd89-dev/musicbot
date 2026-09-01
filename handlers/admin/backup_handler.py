# handlers/admin/backup_handler.py
# -*- coding: utf-8 -*-
"""
💾 BackupHandler – Sicherung von Bot-Verzeichnis und Musikbibliothek
Integriert in das RichMenuSystem als Admin-Untermenü.
"""

import os
import shutil
import tarfile
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from logger import get_module_logger

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler


class BackupHandler:
    """
    Erstellt und verwaltet tar.gz-Sicherungen für:
      • Bot-Verzeichnis   (config.BACKUP_BOT_SOURCE_DIR)
      • Musikbibliothek   (config.BACKUP_LIBRARY_SOURCE_DIR)

    Backups werden in config.BACKUP_DEST_DIR abgelegt.
    Es werden maximal config.BACKUP_MAX_KEEP Sicherungen je Typ
    aufbewahrt; ältere werden automatisch gelöscht.
    """

    # Callback-Präfix – muss mit dem Routing in rich_menu_system.py übereinstimmen
    CB = "backup_"

    def __init__(self, config, logger_factory=None):
        self.config = config
        self.logger = (logger_factory or get_module_logger)("BackupHandler")

        # Quellpfade
        self.bot_source: Path = Path(
            getattr(config, "BACKUP_BOT_SOURCE_DIR", "/mnt/900gb/entwickeln/rich")
        )
        self.lib_source: Path = Path(
            getattr(
                config,
                "BACKUP_LIBRARY_SOURCE_DIR",
                "/mnt/900gb/entwickeln/rich/library",
            )
        )

        # Zielverzeichnis für Backups
        self.dest_dir: Path = Path(
            getattr(config, "BACKUP_DEST_DIR", "/mnt/250gb/Musikserver")
        )
        self.dest_dir.mkdir(parents=True, exist_ok=True)

        # Aufbewahrungsanzahl
        self.max_keep: int = int(getattr(config, "BACKUP_MAX_KEEP", 5))

        # Ausgeschlossene Pfad-Fragmente beim Bot-Backup
        self.exclude_patterns: List[str] = getattr(
            config,
            "BACKUP_EXCLUDE_PATTERNS",
            [
                "library",  # Musikbibliothek separat sichern
                "__pycache__",
                ".git",
                "*.pyc",
                "import/downloads",
                "import/temp",
                "cache",
            ],
        )

        # Wird von RichMenuHandler nach der Konstruktion zugewiesen
        # (self.backup_handler.error_handler = self.error_handler)
        self.error_handler: "Optional[EnhancedErrorHandler]" = None

        self.logger.info(
            f"💾 BackupHandler initialisiert | "
            f"Bot: {self.bot_source} | "
            f"Library: {self.lib_source} | "
            f"Ziel: {self.dest_dir} | "
            f"Max-Keep: {self.max_keep}"
        )

    # ──────────────────────────────────────────────
    # Öffentliche Menü-Methoden (aufgerufen vom Dispatcher)
    # ──────────────────────────────────────────────

    async def show_main_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Zeigt das Backup-Hauptmenü."""
        query = update.callback_query

        bot_backups = self._list_backups("bot")
        lib_backups = self._list_backups("library")

        # INV-01 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md, Abschnitt 27, P1):
        # _dir_size() traversiert das komplette Quellverzeichnis (rglob+stat) -
        # real gemessen 9,46s fuer die Library dieser Umgebung. Ohne
        # run_in_executor() blockierte das den gesamten Event-Loop, obwohl der
        # Kommentar "nicht-blockierend schaetzen" das Gegenteil suggerierte.
        # Gleiches Muster wie bereits fuer _create_archive() (Zeile 207/259).
        loop = asyncio.get_event_loop()
        bot_size = self._human_size(
            await loop.run_in_executor(None, self._dir_size, self.bot_source)
        )
        lib_size = self._human_size(
            await loop.run_in_executor(None, self._dir_size, self.lib_source)
        )

        text = (
            "💾 **Backup-Verwaltung**\n\n"
            f"🤖 **Bot-Verzeichnis**\n"
            f"   Pfad: `{self.bot_source}`\n"
            f"   Größe: {bot_size}\n"
            f"   Gespeicherte Backups: {len(bot_backups)}/{self.max_keep}\n\n"
            f"🎵 **Musikbibliothek**\n"
            f"   Pfad: `{self.lib_source}`\n"
            f"   Größe: {lib_size}\n"
            f"   Gespeicherte Backups: {len(lib_backups)}/{self.max_keep}\n\n"
            f"📁 **Backup-Ziel:** `{self.dest_dir}`"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "🤖 Bot sichern", callback_data="backup_bot_confirm"
                ),
                InlineKeyboardButton(
                    "🎵 Library sichern", callback_data="backup_lib_confirm"
                ),
            ],
            [
                InlineKeyboardButton("🤖 Bot-Backups", callback_data="backup_list_bot"),
                InlineKeyboardButton(
                    "🎵 Library-Backups", callback_data="backup_list_lib"
                ),
            ],
            [InlineKeyboardButton("🔙 Zurück", callback_data="menu:admin")],
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    # ── Bestätigungs-Dialoge ──────────────────────

    async def confirm_bot_backup(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Sicherheitsabfrage vor Bot-Backup."""
        query = update.callback_query
        # INV-01 (siehe show_main_menu weiter oben): _dir_size() via
        # run_in_executor(), damit der Event-Loop nicht blockiert.
        bot_size = self._human_size(
            await asyncio.get_event_loop().run_in_executor(
                None, self._dir_size, self.bot_source
            )
        )

        text = (
            "⚠️ **Bot-Verzeichnis sichern**\n\n"
            f"Quelle: `{self.bot_source}`\n"
            f"Größe: ~{bot_size}\n"
            f"Ziel: `{self.dest_dir}`\n\n"
            "Die Bibliothek, Cache und temporäre Dateien werden "
            "**ausgeschlossen**.\n\n"
            "Backup jetzt starten?"
        )
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Ja, sichern", callback_data="backup_bot_start"
                ),
                InlineKeyboardButton("❌ Abbrechen", callback_data="backup_main"),
            ]
        ]
        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

    async def confirm_lib_backup(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Sicherheitsabfrage vor Library-Backup."""
        query = update.callback_query
        # INV-01 (siehe show_main_menu weiter oben): _dir_size() via
        # run_in_executor(), damit der Event-Loop nicht blockiert.
        lib_size = self._human_size(
            await asyncio.get_event_loop().run_in_executor(
                None, self._dir_size, self.lib_source
            )
        )

        text = (
            "⚠️ **Musikbibliothek sichern**\n\n"
            f"Quelle: `{self.lib_source}`\n"
            f"Größe: ~{lib_size}\n"
            f"Ziel: `{self.dest_dir}`\n\n"
            "⏳ Bei großen Bibliotheken kann das mehrere Minuten dauern.\n\n"
            "Backup jetzt starten?"
        )
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Ja, sichern", callback_data="backup_lib_start"
                ),
                InlineKeyboardButton("❌ Abbrechen", callback_data="backup_main"),
            ]
        ]
        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

    # ── Start-Methoden (laufen im Hintergrund) ────

    async def start_bot_backup(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Startet das Bot-Backup asynchron."""
        query = update.callback_query
        await query.edit_message_text(
            "⏳ **Bot-Backup läuft...**\n\nBitte warten.",
            parse_mode="Markdown",
        )
        try:
            archive_path = await asyncio.get_event_loop().run_in_executor(
                None,
                self._create_archive,
                self.bot_source,
                "bot",
                self.exclude_patterns,
            )
            self._rotate_backups("bot")
            size = self._human_size(archive_path.stat().st_size)
            await query.edit_message_text(
                f"✅ **Bot-Backup abgeschlossen**\n\n"
                f"📦 Datei: `{archive_path.name}`\n"
                f"💾 Größe: {size}\n"
                f"📁 Speicherort: `{self.dest_dir}`",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔙 Backup-Menü", callback_data="backup_main"
                            )
                        ]
                    ]
                ),
                parse_mode="Markdown",
            )
            self.logger.info(f"✅ Bot-Backup erstellt: {archive_path}")
        except Exception as e:
            self.logger.error(f"❌ Bot-Backup fehlgeschlagen: {e}", exc_info=True)
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "backup_bot_start", e
                )
            else:
                await query.edit_message_text(
                    f"❌ **Backup fehlgeschlagen**\n\n`{e}`",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "🔙 Backup-Menü", callback_data="backup_main"
                                )
                            ]
                        ]
                    ),
                    parse_mode="Markdown",
                )

    async def start_lib_backup(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Startet das Library-Backup asynchron."""
        query = update.callback_query
        await query.edit_message_text(
            "⏳ **Library-Backup läuft...**\n\nBei großen Bibliotheken kann das einige Minuten dauern.",
            parse_mode="Markdown",
        )
        try:
            archive_path = await asyncio.get_event_loop().run_in_executor(
                None,
                self._create_archive,
                self.lib_source,
                "library",
                [],  # Keine Ausschlüsse bei der Library
            )
            self._rotate_backups("library")
            size = self._human_size(archive_path.stat().st_size)
            await query.edit_message_text(
                f"✅ **Library-Backup abgeschlossen**\n\n"
                f"📦 Datei: `{archive_path.name}`\n"
                f"💾 Größe: {size}\n"
                f"📁 Speicherort: `{self.dest_dir}`",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔙 Backup-Menü", callback_data="backup_main"
                            )
                        ]
                    ]
                ),
                parse_mode="Markdown",
            )
            self.logger.info(f"✅ Library-Backup erstellt: {archive_path}")
        except Exception as e:
            self.logger.error(f"❌ Library-Backup fehlgeschlagen: {e}", exc_info=True)
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "backup_lib_start", e
                )
            else:
                await query.edit_message_text(
                    f"❌ **Backup fehlgeschlagen**\n\n`{e}`",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "🔙 Backup-Menü", callback_data="backup_main"
                                )
                            ]
                        ]
                    ),
                    parse_mode="Markdown",
                )

    # ── Auflistung und Löschung ───────────────────

    async def show_list_bot(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Zeigt vorhandene Bot-Backups."""
        await self._show_backup_list(update, context, "bot")

    async def show_list_lib(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Zeigt vorhandene Library-Backups."""
        await self._show_backup_list(update, context, "library")

    async def _show_backup_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        backup_type: str,
    ) -> None:
        query = update.callback_query
        backups = self._list_backups(backup_type)
        emoji = "🤖" if backup_type == "bot" else "🎵"
        label = "Bot" if backup_type == "bot" else "Library"

        if not backups:
            await query.edit_message_text(
                f"{emoji} **{label}-Backups**\n\nKeine Backups vorhanden.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Zurück", callback_data="backup_main")]]
                ),
                parse_mode="Markdown",
            )
            return

        text = f"{emoji} **{label}-Backups** ({len(backups)}/{self.max_keep})\n\n"
        keyboard = []
        for bp in backups:
            size = self._human_size(bp["size"])
            date_str = bp["date"].strftime("%d.%m.%Y %H:%M")
            text += f"📦 `{bp['name']}`\n   🗓 {date_str}  💾 {size}\n\n"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"🗑️ {bp['name'][:30]}",
                        callback_data=f"backup_delete_confirm_{bp['name']}",
                    )
                ]
            )

        keyboard.append(
            [InlineKeyboardButton("🔙 Zurück", callback_data="backup_main")]
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    def _resolve_backup_path(self, filename: str) -> Optional[Path]:
        """
        Löst `filename` sicher relativ zu `dest_dir` auf.

        SEC-006: filename kommt unvalidiert aus callback_data
        (backup_delete_<filename> / backup_delete_confirm_<filename>).
        Ohne diese Prüfung würde ".."-Traversal oder ein absoluter Pfad
        (Path.__truediv__ verwirft bei absoluten rechten Operanden den
        linken Teil komplett - dest_dir / "/etc/passwd" == "/etc/passwd")
        beliebige, vom Bot-Prozess beschreibbare Dateien löschbar machen,
        nicht nur Backups. Gibt None zurück, wenn der aufgelöste Pfad
        außerhalb von dest_dir liegt.
        """
        candidate = (self.dest_dir / filename).resolve()
        if not candidate.is_relative_to(self.dest_dir.resolve()):
            self.logger.warning(
                f"🚨 [SECURITY] Backup-Anfrage außerhalb von {self.dest_dir}: {filename}"
            )
            return None
        return candidate

    async def confirm_delete(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        filename: str,
    ) -> None:
        """Bestätigungs-Dialog für Backup-Löschung."""
        query = update.callback_query
        filepath = self._resolve_backup_path(filename)
        if filepath is None:
            await query.edit_message_text("❌ Ungültiger Dateiname")
            return
        size = self._human_size(filepath.stat().st_size) if filepath.exists() else "?"

        await query.edit_message_text(
            f"⚠️ **Backup löschen?**\n\n"
            f"Datei: `{filename}`\n"
            f"Größe: {size}\n\n"
            "Diese Aktion kann nicht rückgängig gemacht werden!",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Ja, löschen",
                            callback_data=f"backup_delete_{filename}",
                        ),
                        InlineKeyboardButton(
                            "❌ Abbrechen", callback_data="backup_main"
                        ),
                    ]
                ]
            ),
            parse_mode="Markdown",
        )

    async def delete_backup(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        filename: str,
    ) -> None:
        """Löscht eine Backup-Datei."""
        query = update.callback_query
        filepath = self._resolve_backup_path(filename)
        if filepath is None:
            await query.edit_message_text(
                "❌ Ungültiger Dateiname",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Backup-Menü", callback_data="backup_main")]]
                ),
                parse_mode="Markdown",
            )
            return

        try:
            if filepath.exists():
                filepath.unlink()
                self.logger.info(f"🗑️ Backup gelöscht: {filepath}")
                msg = f"✅ **Backup gelöscht**\n\n`{filename}`"
            else:
                msg = f"⚠️ Datei nicht gefunden: `{filename}`"
        except Exception as e:
            self.logger.error(f"❌ Löschen fehlgeschlagen: {e}", exc_info=True)
            msg = f"❌ **Fehler beim Löschen**\n\n`{e}`"

        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Backup-Menü", callback_data="backup_main")]]
            ),
            parse_mode="Markdown",
        )

    # ──────────────────────────────────────────────
    # Interne Hilfsmethoden
    # ──────────────────────────────────────────────

    def _create_archive(
        self,
        source: Path,
        backup_type: str,
        exclude: List[str],
    ) -> Path:
        """
        Erstellt ein tar.gz-Archiv von `source`.
        Gibt den Pfad zur fertigen Archivdatei zurück.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"{backup_type}_backup_{timestamp}.tar.gz"
        archive_path = self.dest_dir / archive_name

        def _filter(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
            for pattern in exclude:
                if pattern.startswith("*."):
                    # Dateiendung-Match
                    if tarinfo.name.endswith(pattern[1:]):
                        return None
                elif pattern in tarinfo.name:
                    return None
            return tarinfo

        self.logger.info(f"📦 Erstelle Archiv: {archive_path} | Quelle: {source}")
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(str(source), arcname=source.name, filter=_filter)

        return archive_path

    def _list_backups(self, backup_type: str) -> List[Dict[str, Any]]:
        """Listet vorhandene Backups eines Typs, sortiert nach Datum (neueste zuerst)."""
        prefix = f"{backup_type}_backup_"
        backups = []
        for f in self.dest_dir.glob(f"{prefix}*.tar.gz"):
            try:
                stat = f.stat()
                backups.append(
                    {
                        "name": f.name,
                        "path": f,
                        "size": stat.st_size,
                        "date": datetime.fromtimestamp(stat.st_mtime),
                    }
                )
            except Exception:
                pass
        return sorted(backups, key=lambda x: x["date"], reverse=True)

    def _rotate_backups(self, backup_type: str) -> None:
        """Entfernt älteste Backups wenn max_keep überschritten."""
        backups = self._list_backups(backup_type)
        while len(backups) > self.max_keep:
            oldest = backups.pop()
            try:
                oldest["path"].unlink()
                self.logger.info(
                    f"♻️ Altes Backup gelöscht (Rotation): {oldest['name']}"
                )
            except Exception as e:
                self.logger.warning(f"⚠️ Konnte {oldest['name']} nicht löschen: {e}")

    @staticmethod
    def _dir_size(path: Path) -> int:
        """Berechnet die Gesamtgröße eines Verzeichnisses in Bytes."""
        total = 0
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    try:
                        total += f.stat().st_size
                    except Exception:
                        pass
        except Exception:
            pass
        return total

    @staticmethod
    def _human_size(size_bytes: int) -> str:
        """Gibt eine lesbare Größenangabe zurück."""
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"
