"""
Characterization-Tests fuer handlers/admin/user_management_handler.py
(UserManagementHandler) - 769 Zeilen, vorher 0 dedizierte Tests (nur
indirekt ueber tests/test_rich_menu_access_control.py auf Dispatcher-Ebene
abgedeckt).

WICHTIG: UserManagementHandler.__init__() liest/schreibt
"data/user_data.json" ueber einen HARTCODIERTEN Path (nicht ueber config
injizierbar). Diese Datei enthaelt echte, laufende Bot-Nutzerdaten (u.a.
den echten Owner). _make_handler() patcht Path() waehrend der Konstruktion
auf ein tmp_path-Verzeichnis, damit KEIN Test jemals die reale Datei liest
oder ueberschreibt - analog zur ArtistNormalizer-Inzidenz aus einer
frueheren Session (siehe tests/test_artist_normalizer.py).

SEC-005 (docs/archive/MusicBot_ENGINEERING_BASELINE.md): set_user_role() hatte
zwei Luecken:
1. new_role wurde nicht gegen self.ROLES validiert (im Gegensatz zur
   Schwester-Methode toggle_user_permission(), die das fuer Permissions
   bereits tat).
2. WICHTIGER: RichMenuSystem._is_admin_check() (SEC-003-Fix) behandelt
   "ist Owner" und "ist in ADMIN_USER_IDS" als gleichwertig fuer den
   Zugriff auf alle usermgmt_-Callbacks. ADMIN_USER_IDS ist in config.py
   aber explizit als eigene, vom Owner GETRENNTE Liste vorgesehen. Ohne
   zusaetzliche Sperre konnte JEDER konfigurierte Admin (nicht nur der
   Owner) sich selbst oder andere per "usermgmt_set_role_<id>_owner" zum
   Owner befoerdern - "Owner" ist aber die hoechste, eigentlich einmalig
   vergebene Autoritaet (permissions=["all"]). Fix: Owner-Rolle darf nur
   vom aktuellen Owner (Config.OWNER_USER_ID) vergeben werden.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.admin.user_management_handler import UserManagementHandler


class FakeConfig:
    OWNER_USER_ID = 111
    ADMIN_USER_IDS = [111, 222]


def _make_handler(tmp_path, config=None):
    user_data_file = tmp_path / "user_data.json"

    def _fake_path(p, *args, **kwargs):
        if p == "data/user_data.json":
            return user_data_file
        return Path(p, *args, **kwargs)

    with patch(
        "handlers.admin.user_management_handler.Path", side_effect=_fake_path
    ):
        handler = UserManagementHandler(config or FakeConfig())
    return handler, user_data_file


def make_update(user_id: int):
    update = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def make_context():
    context = Mock()
    context.user_data = {}
    return context


def _seed_users(handler, users: dict):
    handler._save_users(users)


class TestUserDataFileIsolation:
    def test_constructing_handler_does_not_touch_real_data_file(self, tmp_path):
        """Sanity-Check der Test-Infrastruktur selbst: stellt sicher, dass
        _make_handler() wirklich nicht die reale data/user_data.json
        beruehrt."""
        real_file = Path("data/user_data.json")
        real_mtime_before = (
            real_file.stat().st_mtime if real_file.exists() else None
        )

        handler, tmp_file = _make_handler(tmp_path)
        _seed_users(handler, {"999": {"role": "admin"}})

        assert tmp_file.exists()
        real_mtime_after = (
            real_file.stat().st_mtime if real_file.exists() else None
        )
        assert real_mtime_before == real_mtime_after


class TestSetUserRoleSec005OwnerEscalation:
    def test_non_owner_admin_cannot_promote_to_owner(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "admin"}})

        update = make_update(222)  # 222 ist Admin, aber NICHT Owner (111)
        context = make_context()

        asyncio.run(handler.set_user_role(update, context, "222", "owner"))

        update.callback_query.answer.assert_called_once()
        message = update.callback_query.answer.call_args[0][0]
        assert "Owner" in message

        users_after = handler._load_users()
        assert users_after["222"]["role"] == "admin"  # unveraendert

    def test_admin_cannot_promote_someone_else_to_owner(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "admin"}, "333": {"role": "user"}})

        update = make_update(222)
        context = make_context()

        asyncio.run(handler.set_user_role(update, context, "333", "owner"))

        users_after = handler._load_users()
        assert users_after["333"]["role"] == "user"

    def test_actual_owner_can_promote_to_owner(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "admin"}})

        update = make_update(111)  # 111 ist der echte Owner
        context = make_context()

        asyncio.run(handler.set_user_role(update, context, "222", "owner"))

        users_after = handler._load_users()
        assert users_after["222"]["role"] == "owner"
        assert users_after["222"]["permissions"] == ["all"]

    def test_admin_can_still_grant_non_owner_roles(self, tmp_path):
        """Der Fix darf normale Rollenvergabe durch Admins nicht blockieren,
        nur die Owner-Vergabe."""
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"333": {"role": "user"}})

        update = make_update(222)  # Admin, nicht Owner
        context = make_context()

        asyncio.run(handler.set_user_role(update, context, "333", "moderator"))

        users_after = handler._load_users()
        assert users_after["333"]["role"] == "moderator"


class TestSetUserRoleValidation:
    def test_unknown_role_string_is_rejected(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "user"}})

        update = make_update(111)
        context = make_context()

        asyncio.run(
            handler.set_user_role(update, context, "222", "superadmin_hack")
        )

        update.callback_query.answer.assert_called_once()
        message = update.callback_query.answer.call_args[0][0]
        assert "Rolle" in message

        users_after = handler._load_users()
        assert users_after["222"]["role"] == "user"

    @pytest.mark.parametrize("role", ["user", "moderator", "admin"])
    def test_valid_non_owner_roles_are_accepted(self, tmp_path, role):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "user"}})

        update = make_update(111)
        context = make_context()

        asyncio.run(handler.set_user_role(update, context, "222", role))

        users_after = handler._load_users()
        assert users_after["222"]["role"] == role

    def test_unknown_user_id_is_rejected(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {})

        update = make_update(111)
        context = make_context()

        asyncio.run(handler.set_user_role(update, context, "does-not-exist", "admin"))

        update.callback_query.answer.assert_called_once_with("❌ Benutzer nicht gefunden")


class TestTogglePermission:
    def test_toggle_unknown_permission_is_rejected(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "user", "permissions": []}})

        update = make_update(111)
        context = make_context()

        asyncio.run(handler.toggle_user_permission(update, context, "222", "root"))

        update.callback_query.answer.assert_called_once_with("❌ Unbekannte Berechtigung")

    def test_setting_all_clears_other_permissions(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(
            handler, {"222": {"role": "user", "permissions": ["download", "stats"]}}
        )

        update = make_update(111)
        context = make_context()

        asyncio.run(handler.toggle_user_permission(update, context, "222", "all"))

        users_after = handler._load_users()
        assert users_after["222"]["permissions"] == ["all"]

    def test_toggling_specific_permission_clears_all_flag(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "user", "permissions": ["all"]}})

        update = make_update(111)
        context = make_context()

        asyncio.run(handler.toggle_user_permission(update, context, "222", "stats"))

        users_after = handler._load_users()
        assert "all" not in users_after["222"]["permissions"]
        assert "stats" in users_after["222"]["permissions"]

    def test_toggling_active_permission_removes_it(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "user", "permissions": ["download"]}})

        update = make_update(111)
        context = make_context()

        asyncio.run(handler.toggle_user_permission(update, context, "222", "download"))

        users_after = handler._load_users()
        assert "download" not in users_after["222"]["permissions"]


class TestDeleteUser:
    def test_delete_existing_user_removes_from_storage(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "user"}, "333": {"role": "admin"}})

        update = make_update(111)
        context = make_context()

        asyncio.run(handler.delete_user(update, context, "222"))

        users_after = handler._load_users()
        assert "222" not in users_after
        assert "333" in users_after

    def test_delete_unknown_user_is_rejected(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {})

        update = make_update(111)
        context = make_context()

        asyncio.run(handler.delete_user(update, context, "does-not-exist"))

        update.callback_query.answer.assert_called_once_with("❌ Benutzer nicht gefunden")


class TestNavidromeUserWorkflow:
    def test_get_navidrome_user_returns_none_when_unset(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "user"}})

        assert handler.get_navidrome_user(222) is None

    def test_get_navidrome_user_returns_none_for_blank_string(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "user", "navidrome_user": "   "}})

        assert handler.get_navidrome_user(222) is None

    def test_get_navidrome_user_returns_configured_value(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "user", "navidrome_user": "robin"}})

        assert handler.get_navidrome_user(222) == "robin"

    def test_process_new_user_id_rejects_existing_user(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {"222": {"role": "user"}})

        update = Mock()
        update.effective_user.id = 111
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        context = make_context()

        asyncio.run(handler.process_new_user_id(update, context, "222"))

        message = update.message.reply_text.call_args[0][0]
        assert "existiert bereits" in message

    def test_process_new_user_id_rejects_non_numeric_input(self, tmp_path):
        handler, _ = _make_handler(tmp_path)

        update = Mock()
        update.effective_user.id = 111
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        context = make_context()

        asyncio.run(handler.process_new_user_id(update, context, "not-a-number"))

        message = update.message.reply_text.call_args[0][0]
        assert "Ungültige Eingabe" in message

    def test_process_new_user_id_stores_pending_state(self, tmp_path):
        handler, _ = _make_handler(tmp_path)

        update = Mock()
        update.effective_user.id = 111
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        context = make_context()

        asyncio.run(handler.process_new_user_id(update, context, "444"))

        assert context.user_data["pending_user_id"] == "444"
        assert context.user_data["workflow"] == "add_user_navidrome"

    def test_process_new_navidrome_user_creates_user_with_navidrome_name(
        self, tmp_path
    ):
        handler, _ = _make_handler(tmp_path)

        update = Mock()
        update.effective_user.id = 111
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        context = make_context()
        context.user_data["pending_user_id"] = "444"

        asyncio.run(handler.process_new_navidrome_user(update, context, "robin"))

        users_after = handler._load_users()
        assert users_after["444"]["navidrome_user"] == "robin"
        assert users_after["444"]["role"] == "user"
        assert "pending_user_id" not in context.user_data

    def test_process_new_navidrome_user_rejects_blank_name(self, tmp_path):
        handler, _ = _make_handler(tmp_path)

        update = Mock()
        update.effective_user.id = 111
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        context = make_context()
        context.user_data["pending_user_id"] = "444"

        asyncio.run(handler.process_new_navidrome_user(update, context, "   "))

        users_after = handler._load_users()
        assert "444" not in users_after

    def test_process_new_navidrome_user_without_pending_id_fails_gracefully(
        self, tmp_path
    ):
        handler, _ = _make_handler(tmp_path)

        update = Mock()
        update.effective_user.id = 111
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        context = make_context()

        asyncio.run(handler.process_new_navidrome_user(update, context, "robin"))

        message = update.message.reply_text.call_args[0][0]
        assert "Keine User-ID gefunden" in message


class TestUserManagementMenuPagination:
    def test_pagination_splits_users_into_pages_of_five(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        users = {str(i): {"role": "user"} for i in range(12)}
        _seed_users(handler, users)

        update = make_update(111)
        context = make_context()

        asyncio.run(handler.show_user_management_menu(update, context, page=0))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Seite 1/3" in text

    def test_empty_user_list_shows_placeholder_text(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        _seed_users(handler, {})

        update = make_update(111)
        context = make_context()

        asyncio.run(handler.show_user_management_menu(update, context, page=0))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Keine Benutzer registriert" in text
