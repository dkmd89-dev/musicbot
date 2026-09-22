# tests/test_user_admin_service.py
# -*- coding: utf-8 -*-
"""
CC-AC-10B: gezielte Tests für services/user_admin.py — den neuen,
Telegram-freien Application-Layer für User-Management-Schreiboperationen.

Spiegelt die SEC-005-Owner-Guard-/Rollen-/Berechtigungs-Whitelist-
Charakterisierung aus tests/test_user_management_handler.py (dort gegen
die Telegram-Seite, hier gegen dieselbe Fachlogik im neuen
Application-Layer) — beide Implementierungen müssen bei denselben Eingaben
dasselbe Ergebnis liefern.
"""

from __future__ import annotations

import pytest

from handlers.admin.user_management_handler import UserManagementHandler
from services import user_admin


def test_roles_and_permissions_match_telegram_handler():
    """Drift-Wächter: der neue Application-Layer und die bestehende
    Telegram-Seite müssen dieselben Whitelists verwenden, sonst
    divergiert das Verhalten zwischen Telegram und Control Center."""
    assert user_admin.ROLES == UserManagementHandler.ROLES
    assert user_admin.PERMISSIONS == UserManagementHandler.PERMISSIONS


class TestCreateUser:
    def test_creates_user_with_defaults(self):
        users = {}
        entry = user_admin.create_user(users, "444", "robin")

        assert entry["role"] == "user"
        assert entry["permissions"] == ["all"]
        assert entry["navidrome_user"] == "robin"
        assert "created_at" in entry
        assert users["444"] == entry

    def test_rejects_existing_user(self):
        users = {"444": {"role": "user"}}
        with pytest.raises(user_admin.UserAlreadyExistsError):
            user_admin.create_user(users, "444", "robin")

    def test_rejects_blank_navidrome_user(self):
        with pytest.raises(user_admin.UserAdminError):
            user_admin.create_user({}, "444", "   ")


class TestUpdateNavidromeUser:
    def test_updates_existing_user(self):
        users = {"444": {"role": "user", "navidrome_user": "old"}}
        entry = user_admin.update_navidrome_user(users, "444", "new")

        assert entry["navidrome_user"] == "new"
        assert users["444"]["navidrome_user"] == "new"

    def test_rejects_unknown_user(self):
        with pytest.raises(user_admin.UserNotFoundError):
            user_admin.update_navidrome_user({}, "444", "robin")

    def test_rejects_blank_name(self):
        users = {"444": {"role": "user"}}
        with pytest.raises(user_admin.UserAdminError):
            user_admin.update_navidrome_user(users, "444", "   ")


class TestSetUserRoleSec005OwnerGuard:
    def test_non_owner_admin_cannot_promote_to_owner(self):
        users = {"222": {"role": "admin"}}
        with pytest.raises(user_admin.OwnerPromotionDeniedError):
            user_admin.set_user_role(
                users, "222", "owner", acting_user_id=222, owner_user_id=111
            )
        assert users["222"]["role"] == "admin"

    def test_admin_cannot_promote_someone_else_to_owner(self):
        users = {"222": {"role": "admin"}, "333": {"role": "user"}}
        with pytest.raises(user_admin.OwnerPromotionDeniedError):
            user_admin.set_user_role(
                users, "333", "owner", acting_user_id=222, owner_user_id=111
            )
        assert users["333"]["role"] == "user"

    def test_actual_owner_can_promote_to_owner(self):
        users = {"222": {"role": "admin"}}
        entry = user_admin.set_user_role(
            users, "222", "owner", acting_user_id=111, owner_user_id=111
        )
        assert entry["role"] == "owner"
        assert entry["permissions"] == ["all"]

    def test_admin_can_still_grant_non_owner_roles(self):
        users = {"333": {"role": "user"}}
        entry = user_admin.set_user_role(
            users, "333", "moderator", acting_user_id=222, owner_user_id=111
        )
        assert entry["role"] == "moderator"


class TestSetUserRoleValidation:
    def test_unknown_role_is_rejected(self):
        users = {"222": {"role": "user"}}
        with pytest.raises(user_admin.InvalidRoleError):
            user_admin.set_user_role(
                users, "222", "superadmin_hack", acting_user_id=111, owner_user_id=111
            )
        assert users["222"]["role"] == "user"

    @pytest.mark.parametrize("role", ["user", "moderator", "admin"])
    def test_valid_non_owner_roles_are_accepted(self, role):
        users = {"222": {"role": "user"}}
        entry = user_admin.set_user_role(
            users, "222", role, acting_user_id=111, owner_user_id=111
        )
        assert entry["role"] == role

    def test_unknown_user_is_rejected(self):
        with pytest.raises(user_admin.UserNotFoundError):
            user_admin.set_user_role(
                {}, "does-not-exist", "admin", acting_user_id=111, owner_user_id=111
            )


class TestSetUserPermissions:
    def test_sets_permission_list(self):
        users = {"222": {"role": "user", "permissions": []}}
        entry = user_admin.set_user_permissions(users, "222", ["download", "stats"])
        assert entry["permissions"] == ["download", "stats"]

    def test_all_supersedes_other_permissions(self):
        users = {"222": {"role": "user", "permissions": []}}
        entry = user_admin.set_user_permissions(users, "222", ["download", "all"])
        assert entry["permissions"] == ["all"]

    def test_rejects_unknown_permission(self):
        users = {"222": {"role": "user", "permissions": []}}
        with pytest.raises(user_admin.InvalidPermissionError):
            user_admin.set_user_permissions(users, "222", ["root"])
        assert users["222"]["permissions"] == []

    def test_rejects_unknown_user(self):
        with pytest.raises(user_admin.UserNotFoundError):
            user_admin.set_user_permissions({}, "does-not-exist", ["download"])


class TestDeleteUser:
    def test_deletes_existing_user_and_returns_entry(self):
        users = {"222": {"role": "admin"}, "333": {"role": "user"}}
        removed = user_admin.delete_user(users, "222")

        assert removed == {"role": "admin"}
        assert "222" not in users
        assert "333" in users

    def test_rejects_unknown_user(self):
        with pytest.raises(user_admin.UserNotFoundError):
            user_admin.delete_user({}, "does-not-exist")
