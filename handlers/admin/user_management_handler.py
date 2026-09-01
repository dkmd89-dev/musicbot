# handlers/admin/user_management_handler.py
# -*- coding: utf-8 -*-
"""
👥 Erweiterte Benutzerverwaltung mit Navidrome-Integration
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, TYPE_CHECKING
import json
import time

from logger import get_module_logger

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler


class UserManagementHandler:
    """Verwaltet Benutzer und deren Berechtigungen inkl. Navidrome-Mapping"""

    ROLES = ["user", "moderator", "admin", "owner"]
    PERMISSIONS = ["download", "stats", "navidrome", "admin", "all"]

    def __init__(self, config, logger_factory=None):
        self.config = config
        self.logger = (logger_factory or get_module_logger)("UserManagement")
        self.user_data_file = Path("data/user_data.json")
        self.pending_users: Dict[int, Dict] = {}

        # NEU: Cache für schnellen Zugriff
        self.user_data_cache = self._load_users()

        # Wird von RichMenuHandler nach der Konstruktion zugewiesen
        # (self.user_mgmt_handler.error_handler = self.error_handler)
        self.error_handler: "Optional[EnhancedErrorHandler]" = None

        self.logger.info(
            f"✅ UserManagement initialisiert ({len(self.user_data_cache)} Benutzer)"
        )

    def _load_users(self) -> Dict[str, Any]:
        """Lädt User-Daten aus JSON"""
        try:
            if self.user_data_file.exists():
                with open(self.user_data_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der User-Daten: {e}")
            return {}

    def _save_users(self, users: Dict[str, Any]) -> bool:
        """
        Speichert User-Daten und aktualisiert Cache.

        INV-02 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md, Abschnitt 27, P0-C):
        vorher direktes open(mode="w") - ein Prozessabbruch waehrend
        json.dump() konnte data/user_data.json (Rollen/Berechtigungen,
        sicherheitsrelevant) leeren oder korrumpieren, mit dem Risiko eines
        Admin-/Owner-Lockouts. Jetzt: write-tmp + atomarer rename, analog zu
        MetadataCache.store() (utils/metadata_cache.py).
        """
        tmp_path = self.user_data_file.with_suffix(f".tmp_{int(time.time() * 1000)}")
        try:
            self.user_data_file.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(users, f, indent=2, ensure_ascii=False)
            tmp_path.replace(self.user_data_file)

            # Cache aktualisieren
            self.user_data_cache = users
            return True
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Speichern der User-Daten: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    # ==================== NEU: NAVIDROME-USER MANAGEMENT ====================

    def get_navidrome_user(self, telegram_id: int) -> Optional[str]:
        """
        Holt Navidrome-Username für Telegram-ID

        Returns:
            str: Navidrome-Username oder None
        """
        user_data = self.user_data_cache.get(str(telegram_id))
        if user_data:
            nav_user = user_data.get("navidrome_user")
            if nav_user and nav_user.strip():
                return nav_user
        return None

    async def show_user_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str
    ):
        """Zeigt Details und Optionen für einen Benutzer (ERWEITERT)"""
        query = update.callback_query
        users = self._load_users()

        user_data = users.get(user_id)
        if not user_data:
            await query.answer("❌ Benutzer nicht gefunden")
            return

        role = user_data.get("role", "user")
        created = user_data.get("created_at", "Unbekannt")
        permissions = user_data.get("permissions", [])

        # NEU: Navidrome-User anzeigen
        nav_user = user_data.get("navidrome_user", "❌ Nicht zugeordnet")

        text = f"""👤 **Benutzer-Details**

**User ID:** {user_id}
**Rolle:** {role}
**Registriert:** {created[:19] if created != 'Unbekannt' else 'Unbekannt'}
**Berechtigungen:** {', '.join(permissions) if permissions else 'Standard'}
**🎵 Navidrome-User:** {nav_user}

Aktionen:"""

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 Rolle ändern", callback_data=f"usermgmt_change_role_{user_id}"
                ),
                InlineKeyboardButton(
                    "🔐 Berechtigungen", callback_data=f"usermgmt_permissions_{user_id}"
                ),
            ],
            [
                # NEU: Button zum Setzen des Navidrome-Users
                InlineKeyboardButton(
                    "🎵 Navidrome-User setzen",
                    callback_data=f"usermgmt_set_navidrome_{user_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🚫 Benutzer sperren", callback_data=f"usermgmt_ban_{user_id}"
                ),
                InlineKeyboardButton(
                    "🗑️ Löschen", callback_data=f"usermgmt_delete_confirm_{user_id}"
                ),
            ],
            [InlineKeyboardButton("🔙 Zurück", callback_data="usermgmt_list_0")],
        ]

        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

    async def process_new_user_id(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id_text: str
    ):
        """
        Verarbeitet die vom Admin gesendete User-ID (SCHRITT 1/2)
        """
        admin_user_id = update.effective_user.id

        try:
            new_user_id = int(user_id_text.strip())
            new_user_id_str = str(new_user_id)

            self.logger.info(
                f"Admin {admin_user_id} fügt User {new_user_id_str} hinzu (Schritt 1/2)"
            )

            users = self._load_users()

            # Prüfen, ob User bereits existiert
            if new_user_id_str in users:
                await update.message.reply_text(
                    f"⚠️ **Benutzer existiert bereits**\n\n"
                    f"User-ID: {new_user_id_str}\n"
                    f"Rolle: {users[new_user_id_str].get('role', 'unbekannt')}"
                )
                return

            # NEU: User wird NOCH NICHT gespeichert!
            # Stattdessen wird nach dem Navidrome-User gefragt.

            # Session-State für den 2. Schritt setzen
            # (RichMenuHandler.handle_text_message muss dies abfangen)

            # Zugriff auf menu_system über context (falls verfügbar)
            # HINWEIS: Dies ist eine vereinfachte Variante.
            # In der Praxis sollte menu_system zentral zugänglich sein.

            await update.message.reply_text(
                f"📋 **Neuen Benutzer hinzufügen (Schritt 2/2)**\n\n"
                f"User-ID: `{new_user_id_str}`\n\n"
                f"Bitte sende mir jetzt den **Navidrome-Benutzernamen** für diesen Benutzer.\n\n"
                f"*(Du kannst /cancel eingeben, um abzubrechen)*",
                parse_mode="Markdown",
            )

            # WICHTIG: Speichere die User-ID temporär im Kontext
            context.user_data["pending_user_id"] = new_user_id_str
            context.user_data["workflow"] = "add_user_navidrome"

        except ValueError:
            self.logger.warning(f"Ungültige User-ID Eingabe: {user_id_text}")
            await update.message.reply_text(
                f"❌ **Ungültige Eingabe**\n\n"
                f"'{user_id_text}' ist keine gültige Telegram User-ID."
            )
        except Exception as e:
            self.logger.error(f"Fehler beim Hinzufügen von User: {e}", exc_info=True)
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "usermgmt_add_user_step1", e
                )
            else:
                await update.message.reply_text(
                    f"❌ **Fehler**\n\nEin interner Fehler ist aufgetreten: {e}"
                )

    async def process_new_navidrome_user(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        navidrome_username: str,
    ):
        """
        Verarbeitet den Navidrome-Benutzernamen (SCHRITT 2/2)
        """
        admin_user_id = update.effective_user.id

        # Hole die User-ID aus dem Kontext
        pending_user_id = context.user_data.get("pending_user_id")

        if not pending_user_id:
            await update.message.reply_text(
                "❌ **Fehler**\n\nKeine User-ID gefunden. Bitte starte den Vorgang neu."
            )
            return

        try:
            navidrome_username = navidrome_username.strip()

            if not navidrome_username:
                await update.message.reply_text(
                    "❌ **Ungültige Eingabe**\n\nNavidrome-Benutzername darf nicht leer sein."
                )
                return

            users = self._load_users()

            # Neuen Benutzer erstellen
            users[pending_user_id] = {
                "role": "user",
                "permissions": ["all"],
                "navidrome_user": navidrome_username,  # NEU!
                "created_at": datetime.now().isoformat(),
            }

            if self._save_users(users):
                self.logger.info(
                    f"✅ User {pending_user_id} mit Navidrome-User '{navidrome_username}' hinzugefügt."
                )
                await update.message.reply_text(
                    f"✅ **Benutzer hinzugefügt**\n\n"
                    f"User-ID: {pending_user_id}\n"
                    f"Navidrome-User: {navidrome_username}\n"
                    f"Rolle: user"
                )

                # Cleanup
                context.user_data.pop("pending_user_id", None)
                context.user_data.pop("workflow", None)
            else:
                await update.message.reply_text(
                    "❌ **Fehler**\n\nBenutzer konnte nicht gespeichert werden."
                )

        except Exception as e:
            self.logger.error(
                f"Fehler beim Speichern des Navidrome-Users: {e}", exc_info=True
            )
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "usermgmt_add_user_step2", e
                )
            else:
                await update.message.reply_text(f"❌ **Fehler**\n\n{e}")

    async def process_edit_navidrome_user(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        navidrome_username: str,
    ):
        """
        Bearbeitet den Navidrome-User für einen existierenden Benutzer
        """
        admin_user_id = update.effective_user.id

        # Hole die User-ID aus dem Kontext
        target_user_id = context.user_data.get("target_user_id")

        if not target_user_id:
            await update.message.reply_text("❌ **Fehler**\n\nKeine User-ID gefunden.")
            return

        try:
            navidrome_username = navidrome_username.strip()

            if not navidrome_username:
                await update.message.reply_text(
                    "❌ **Ungültige Eingabe**\n\nNavidrome-Benutzername darf nicht leer sein."
                )
                return

            users = self._load_users()

            if target_user_id not in users:
                await update.message.reply_text(
                    f"❌ **Fehler**\n\nBenutzer {target_user_id} nicht gefunden."
                )
                return

            # Navidrome-User aktualisieren
            old_nav_user = users[target_user_id].get("navidrome_user", "Nicht gesetzt")
            users[target_user_id]["navidrome_user"] = navidrome_username

            if self._save_users(users):
                self.logger.info(
                    f"✅ Navidrome-User für {target_user_id} aktualisiert: "
                    f"'{old_nav_user}' → '{navidrome_username}'"
                )
                await update.message.reply_text(
                    f"✅ **Navidrome-User aktualisiert**\n\n"
                    f"User-ID: {target_user_id}\n"
                    f"Alt: {old_nav_user}\n"
                    f"Neu: {navidrome_username}"
                )

                # Cleanup
                context.user_data.pop("target_user_id", None)
                context.user_data.pop("workflow", None)
            else:
                await update.message.reply_text(
                    "❌ **Fehler**\n\nÄnderungen konnten nicht gespeichert werden."
                )

        except Exception as e:
            self.logger.error(
                f"Fehler beim Bearbeiten des Navidrome-Users: {e}", exc_info=True
            )
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "usermgmt_edit_navidrome_user", e
                )
            else:
                await update.message.reply_text(f"❌ **Fehler**\n\n{e}")

    # ==================== BESTEHENDE METHODEN (unverändert) ====================

    async def show_user_management_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0
    ):
        """Zeigt Benutzerverwaltungs-Menü mit Paginierung"""
        query = update.callback_query
        users = self._load_users()

        users_per_page = 5
        user_items = list(users.items())
        total_pages = (len(user_items) + users_per_page - 1) // users_per_page
        start_idx = page * users_per_page
        end_idx = start_idx + users_per_page
        page_users = user_items[start_idx:end_idx]

        text = f"👥 **Benutzerverwaltung** (Seite {page + 1}/{max(total_pages, 1)})\n\n"

        if not users:
            text += "Keine Benutzer registriert."
        else:
            text += "Registrierte Benutzer:\n"
            for user_id, data in page_users:
                role = data.get("role", "user")
                created = data.get("created_at", "Unbekannt")
                nav_user = data.get("navidrome_user", "❌")
                text += f"• **{user_id}**: {role} | 🎵 {nav_user}\n"
                text += f"  Registriert: {created[:10] if created != 'Unbekannt' else 'Unbekannt'}\n"

            text += f"\nGesamt: {len(users)} Benutzer"

        keyboard = []

        # User-Buttons
        for user_id, data in page_users:
            role_emoji = {
                "user": "👤",
                "moderator": "🛡️",
                "admin": "⚙️",
                "owner": "👑",
            }.get(data.get("role", "user"), "👤")

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{role_emoji} {user_id}",
                        callback_data=f"usermgmt_detail_{user_id}",
                    )
                ]
            )

        # Pagination
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    "⬅️ Zurück", callback_data=f"usermgmt_list_{page-1}"
                )
            )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    "➡️ Weiter", callback_data=f"usermgmt_list_{page+1}"
                )
            )
        if nav_buttons:
            keyboard.append(nav_buttons)

        # Action Buttons
        keyboard.extend(
            [
                [
                    InlineKeyboardButton(
                        "➕ Benutzer hinzufügen", callback_data="usermgmt_add_user"
                    ),
                    InlineKeyboardButton("🔍 Suchen", callback_data="usermgmt_search"),
                ],
                [
                    InlineKeyboardButton(
                        "📊 Statistiken", callback_data="usermgmt_stats"
                    ),
                    InlineKeyboardButton(
                        "🗑️ Aufräumen", callback_data="usermgmt_cleanup"
                    ),
                ],
                [InlineKeyboardButton("🔙 Zurück", callback_data="menu:admin")],
            ]
        )

        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

    async def show_role_change_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str
    ):
        """Zeigt Menü zum Ändern der Benutzerrolle"""
        query = update.callback_query
        users = self._load_users()

        user_data = users.get(user_id)
        if not user_data:
            await query.answer("❌ Benutzer nicht gefunden")
            return

        current_role = user_data.get("role", "user")

        text = f"""🔄 **Rolle ändern**

Benutzer: {user_id}
Aktuelle Rolle: **{current_role}**

Wähle neue Rolle:"""

        keyboard = []
        for role in self.ROLES:
            emoji = {"user": "👤", "moderator": "🛡️", "admin": "⚙️", "owner": "👑"}.get(
                role, "👤"
            )

            prefix = "✅ " if role == current_role else ""
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{prefix}{emoji} {role.capitalize()}",
                        callback_data=f"usermgmt_set_role_{user_id}_{role}",
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "🔙 Zurück", callback_data=f"usermgmt_detail_{user_id}"
                )
            ]
        )

        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

    async def set_user_role(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: str,
        new_role: str,
    ):
        """Setzt die Rolle eines Benutzers"""
        query = update.callback_query
        users = self._load_users()

        # SEC-005-Fix: new_role kommt aus callback_data (clientseitig frei
        # sendbar, siehe SEC-003) - ohne Validierung gegen self.ROLES koennte
        # ein beliebiger String als Rolle gesetzt werden. toggle_user_permission()
        # validiert bereits analog gegen self.PERMISSIONS.
        if new_role not in self.ROLES:
            await query.answer("❌ Unbekannte Rolle")
            return

        # SEC-005-Fix: der Aufrufer muss laut RichMenuSystem._is_admin_check()
        # nur "Owner ODER in ADMIN_USER_IDS" sein - ADMIN_USER_IDS ist in
        # config.py explizit als eigene, vom Owner getrennte Liste vorgesehen.
        # Ohne diese Sperre koennte JEDER konfigurierte Admin sich selbst oder
        # andere zum Owner befoerdern, obwohl "Owner" die hoechste, eigentlich
        # nur einmalig vergebene Autoritaet darstellt (permissions=["all"]).
        if new_role == "owner":
            acting_user_id = update.effective_user.id
            owner_id = getattr(self.config, "OWNER_USER_ID", None)
            if acting_user_id != owner_id:
                self.logger.warning(
                    f"🚫 Nicht-Owner {acting_user_id} versuchte, User {user_id} "
                    f"zum Owner zu befördern - abgelehnt"
                )
                await query.answer("❌ Nur der Owner darf die Owner-Rolle vergeben")
                return

        if user_id not in users:
            await query.answer("❌ Benutzer nicht gefunden")
            return

        old_role = users[user_id].get("role", "user")
        users[user_id]["role"] = new_role

        if new_role == "owner":
            users[user_id]["permissions"] = ["all"]
        elif new_role == "admin":
            users[user_id]["permissions"] = ["admin", "moderate", "download"]
        elif new_role == "moderator":
            users[user_id]["permissions"] = ["moderate", "download"]
        else:
            users[user_id]["permissions"] = ["download"]

        if self._save_users(users):
            self.logger.info(
                f"✅ Rolle geändert: User {user_id}: {old_role} → {new_role}"
            )

            text = f"""✅ **Rolle erfolgreich geändert**

Benutzer: {user_id}
Alte Rolle: {old_role}
Neue Rolle: **{new_role}**
Zeitpunkt: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "👤 Benutzer-Details",
                            callback_data=f"usermgmt_detail_{user_id}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "👥 Benutzerliste", callback_data="usermgmt_list_0"
                        )
                    ],
                ]
            )

            await query.edit_message_text(
                text, reply_markup=keyboard, parse_mode="Markdown"
            )
        else:
            await query.answer("❌ Fehler beim Speichern")

    async def show_permission_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str
    ):
        """Zeigt Menü zum Verwalten der Berechtigungen"""
        query = update.callback_query
        users = self._load_users()

        user_data = users.get(user_id)
        if not user_data:
            await query.answer("❌ Benutzer nicht gefunden")
            return

        current_permissions = set(user_data.get("permissions", []))

        text = f"""🔐 **Berechtigungen verwalten**

Benutzer: {user_id}
Rolle: {user_data.get('role', 'user')}

Wähle Berechtigungen zum Umschalten:"""

        keyboard = []
        for perm in self.PERMISSIONS:
            is_active = perm in current_permissions
            prefix = "✅ " if is_active else "⚪ "

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{prefix} {perm.capitalize()}",
                        callback_data=f"usermgmt_toggle_perm_{user_id}_{perm}",
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "🔙 Zurück", callback_data=f"usermgmt_detail_{user_id}"
                )
            ]
        )

        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

    async def toggle_user_permission(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: str,
        permission: str,
    ):
        """Schaltet eine Berechtigung für einen Benutzer um"""
        query = update.callback_query
        users = self._load_users()

        if user_id not in users:
            await query.answer("❌ Benutzer nicht gefunden")
            return

        if permission not in self.PERMISSIONS:
            await query.answer("❌ Unbekannte Berechtigung")
            return

        current_permissions = set(users[user_id].get("permissions", []))

        if permission == "all":
            if "all" in current_permissions:
                current_permissions.remove("all")
            else:
                current_permissions = {"all"}
        else:
            if "all" in current_permissions:
                current_permissions.remove("all")

            if permission in current_permissions:
                current_permissions.remove(permission)
            else:
                current_permissions.add(permission)

        users[user_id]["permissions"] = list(current_permissions)

        if self._save_users(users):
            self.logger.info(
                f"Berechtigungen für {user_id} aktualisiert: {list(current_permissions)}"
            )
            await query.answer("✅ Berechtigungen aktualisiert")
            await self.show_permission_menu(update, context, user_id)
        else:
            await query.answer("❌ Fehler beim Speichern")

    async def show_statistics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Zeigt Benutzer-Statistiken"""
        query = update.callback_query
        users = self._load_users()

        role_counts = {}
        nav_user_count = 0

        for user_data in users.values():
            role = user_data.get("role", "user")
            role_counts[role] = role_counts.get(role, 0) + 1

            if user_data.get("navidrome_user"):
                nav_user_count += 1

        text = f"""📊 **Benutzer-Statistiken**

Gesamt: {len(users)} Benutzer
🎵 Mit Navidrome: {nav_user_count}

**Nach Rolle:**
"""

        for role in self.ROLES:
            count = role_counts.get(role, 0)
            emoji = {"user": "👤", "moderator": "🛡️", "admin": "⚙️", "owner": "👑"}.get(
                role, "👤"
            )
            text += f"• {emoji} {role.capitalize()}: {count}\n"

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Zurück", callback_data="usermgmt_list_0")]]
        )

        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode="Markdown"
        )

    async def delete_user_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str
    ):
        """Bestätigung für Benutzer-Löschung"""
        query = update.callback_query

        text = f"""⚠️ **Benutzer löschen**

Bist du sicher, dass du den Benutzer **{user_id}** löschen möchtest?

Diese Aktion kann nicht rückgängig gemacht werden!"""

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Ja, löschen",
                        callback_data=f"usermgmt_delete_confirmed_{user_id}",
                    ),
                    InlineKeyboardButton(
                        "❌ Abbrechen", callback_data=f"usermgmt_detail_{user_id}"
                    ),
                ]
            ]
        )

        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode="Markdown"
        )

    async def delete_user(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str
    ):
        """Löscht einen Benutzer"""
        query = update.callback_query
        users = self._load_users()

        if user_id not in users:
            await query.answer("❌ Benutzer nicht gefunden")
            return

        user_data = users[user_id]
        del users[user_id]

        if self._save_users(users):
            self.logger.info(
                f"🗑️ Benutzer gelöscht: {user_id} ({user_data.get('role', 'user')})"
            )

            text = f"""✅ **Benutzer erfolgreich gelöscht**

User-ID: {user_id}
Rolle: {user_data.get('role', 'user')}
Zeitpunkt: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"""

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "👥 Benutzerliste", callback_data="usermgmt_list_0"
                        )
                    ]
                ]
            )

            await query.edit_message_text(
                text, reply_markup=keyboard, parse_mode="Markdown"
            )
        else:
            await query.answer("❌ Fehler beim Löschen")

    async def add_new_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Startet den Prozess zum Hinzufügen eines neuen Benutzers"""
        query = update.callback_query

        text = """➕ **Neuen Benutzer hinzufügen**

Um einen neuen Benutzer hinzuzufügen:

1. Der Benutzer muss den Bot starten (/start)
2. Seine User-ID wird automatisch erkannt
3. Dann kann hier die Rolle zugewiesen werden

**Alternativ:** Gib die User-ID direkt ein:
Sende eine Nachricht im Format:
`/adduser USER_ID ROLLE`

Beispiel: `/adduser 123456789 moderator`

Verfügbare Rollen:
• user - Standard-Benutzer
• moderator - Moderator
• admin - Administrator
• owner - Besitzer"""

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📋 Pending-Users", callback_data="usermgmt_pending"
                    )
                ],
                [InlineKeyboardButton("🔙 Zurück", callback_data="usermgmt_list_0")],
            ]
        )

        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode="Markdown"
        )
