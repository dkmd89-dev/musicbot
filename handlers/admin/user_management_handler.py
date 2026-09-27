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

from logger import get_module_logger
from services import user_admin
from services.user_data import get_navidrome_user as _shared_get_navidrome_user
from services.user_data import load_user_data as _shared_load_user_data
from services.user_data import save_user_data as _shared_save_user_data
from services.user_data import update_user_data as _shared_update_user_data

# PARSE-MODE-AUDIT 2026-09-13, Hotfix 1: navidrome_user ist admin-
# eingegebener Freitext, der unescaped in parse_mode="Markdown"-Texte
# eingebettet wurde - ein Unterstrich im Namen (z.B. "john_doe") ließ
# Telegram mit "Can't parse entities: can't find end of the entity..."
# ablehnen (dieselbe Fehlerklasse wie NAV-F13/F14/STATUS-MENU-CLOSURE).
# Wiederverwendung des bestehenden Legacy-Markdown-v1-Escapers statt
# einer dritten unabhängigen Neu-Definition (Audit-Empfehlung 1).
from handlers.enhanced_status_handler import _escape_markdown

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
        """Lädt User-Daten aus JSON.

        Dünner Delegator auf services/user_data.py::load_user_data()
        (Master-Prompt Regel 51 "Common Core" — dieselbe Logik wird jetzt
        auch von control_center/ genutzt) — unverändertes Verhalten
        inkl. Fehlerlog."""
        return _shared_load_user_data(self.user_data_file, logger=self.logger)

    def _save_users(self, users: Dict[str, Any]) -> bool:
        """
        Speichert User-Daten und aktualisiert Cache.

        CC-AC-10G (Client Consolidation Phase A, A.3/A.9 "Single Write
        Path"): duenner Delegator auf services/user_data.py::save_user_data()
        (dieselbe atomare write-tmp+rename-Implementierung, die zuvor hier
        dupliziert war, siehe INV-02/docs/MusicBot_ARCHITECTURE_EVOLUTION.md
        Abschnitt 27, P0-C). Cache wird weiterhin nur bei Erfolg aktualisiert
        - unveraendertes Verhalten fuer tests/test_user_management_atomic_persistence.py.
        """
        ok = _shared_save_user_data(users, self.user_data_file, logger=self.logger)
        if ok:
            self.user_data_cache = users
        return ok

    def _update_users(self, mutator):
        """
        Fuehrt einen Read-Modify-Write-Zyklus prozessuebergreifend gesperrt
        aus (A.7 "Cross-Process-Persistenzstrategie", CC-AC-10G) - duenner
        Delegator auf services/user_data.py::update_user_data().

        `mutator(users)` mutiert das geladene Dict in-place und darf eine
        services.user_admin.UserAdminError-Subklasse werfen, um den Zyklus
        ohne Schreiben abzubrechen (propagiert an den Aufrufer). Cache wird
        wie bei _save_users() nur bei Erfolg aktualisiert.
        """
        result, users, saved = _shared_update_user_data(
            mutator, self.user_data_file, logger=self.logger
        )
        if saved:
            self.user_data_cache = users
        return result, saved

    # ==================== NEU: NAVIDROME-USER MANAGEMENT ====================

    def get_navidrome_user(self, telegram_id: int) -> Optional[str]:
        """
        Holt Navidrome-Username für Telegram-ID

        Dünner Delegator auf services/user_data.py::get_navidrome_user()
        (siehe _load_users()-Docstring). Unverändertes Verhalten.

        Returns:
            str: Navidrome-Username oder None
        """
        return _shared_get_navidrome_user(self.user_data_cache, telegram_id)

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
**🎵 Navidrome-User:** {_escape_markdown(nav_user)}

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

            # CC-AC-10G: Anlage zentral ueber services/user_admin.py::create_user()
            # (identische Feldbelegung wie zuvor hier). UserAlreadyExistsError
            # kann hier nur bei einer Race zwischen Schritt 1 und Schritt 2
            # auftreten (Existenz wurde in process_new_user_id() bereits
            # geprueft) - bewusst kein stilles Ueberschreiben mehr. A.7:
            # Zyklus gesperrt via _update_users().
            def _mutate(users):
                user_admin.create_user(users, pending_user_id, navidrome_username)

            try:
                _, saved = self._update_users(_mutate)
            except user_admin.UserAdminError as e:
                self.logger.error(
                    f"Fehler beim Anlegen von User {pending_user_id}: {e}"
                )
                await update.message.reply_text(
                    "❌ **Fehler**\n\nBenutzer konnte nicht gespeichert werden."
                )
                return

            if saved:
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

            # CC-AC-10G: Aktualisierung zentral ueber
            # services/user_admin.py::update_navidrome_user() (identische
            # Fachlogik wie zuvor hier). A.7: Zyklus gesperrt via
            # _update_users().
            def _mutate(users):
                old_nav_user = users.get(target_user_id, {}).get(
                    "navidrome_user", "Nicht gesetzt"
                )
                user_admin.update_navidrome_user(
                    users, target_user_id, navidrome_username
                )
                return old_nav_user

            try:
                old_nav_user, saved = self._update_users(_mutate)
            except user_admin.UserNotFoundError:
                await update.message.reply_text(
                    f"❌ **Fehler**\n\nBenutzer {target_user_id} nicht gefunden."
                )
                return

            if saved:
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
                text += f"• **{user_id}**: {role} | 🎵 {_escape_markdown(nav_user)}\n"
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

        # CC-AC-10G: Rollen-Whitelist, SEC-005-Owner-Guard und
        # Rolle->Standard-Berechtigungen laufen jetzt zentral ueber
        # services/user_admin.py::set_user_role() (identische Fachlogik
        # wie zuvor hier, siehe dortiger Docstring) - Telegram liefert nur
        # noch die Aktion und uebersetzt die Fehlerfaelle in Nutzertexte.
        # A.7: der komplette Load->Aendern->Save-Zyklus laeuft prozess-
        # uebergreifend gesperrt ueber _update_users().
        acting_user_id = update.effective_user.id
        owner_id = getattr(self.config, "OWNER_USER_ID", None)

        def _mutate(users):
            old_role = users.get(user_id, {}).get("role", "user")
            user_admin.set_user_role(
                users,
                user_id,
                new_role,
                acting_user_id=acting_user_id,
                owner_user_id=owner_id,
            )
            return old_role

        try:
            old_role, saved = self._update_users(_mutate)
        except user_admin.InvalidRoleError:
            await query.answer("❌ Unbekannte Rolle")
            return
        except user_admin.OwnerPromotionDeniedError:
            self.logger.warning(
                f"🚫 Nicht-Owner {acting_user_id} versuchte, User {user_id} "
                f"zum Owner zu befördern - abgelehnt"
            )
            await query.answer("❌ Nur der Owner darf die Owner-Rolle vergeben")
            return
        except user_admin.UserNotFoundError:
            await query.answer("❌ Benutzer nicht gefunden")
            return

        if saved:
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

        # CC-AC-10G: Toggle-Validierung/-Semantik zentral in
        # services/user_admin.py::toggle_user_permission() (identische
        # Fachlogik wie zuvor hier). A.7: Zyklus gesperrt via _update_users().
        def _mutate(users):
            return user_admin.toggle_user_permission(users, user_id, permission)

        try:
            updated_permissions, saved = self._update_users(_mutate)
        except user_admin.UserNotFoundError:
            await query.answer("❌ Benutzer nicht gefunden")
            return
        except user_admin.InvalidPermissionError:
            await query.answer("❌ Unbekannte Berechtigung")
            return

        if saved:
            self.logger.info(
                f"Berechtigungen für {user_id} aktualisiert: {updated_permissions}"
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

        # CC-AC-10G: Loeschen zentral ueber services/user_admin.py::delete_user()
        # (identische Fachlogik wie zuvor hier — kein zusaetzlicher
        # Owner-Schutz, bewusste Paritaet, siehe dortiger Docstring). A.7:
        # Zyklus gesperrt via _update_users().
        def _mutate(users):
            return user_admin.delete_user(users, user_id)

        try:
            user_data, saved = self._update_users(_mutate)
        except user_admin.UserNotFoundError:
            await query.answer("❌ Benutzer nicht gefunden")
            return

        if saved:
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
