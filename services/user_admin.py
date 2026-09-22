# services/user_admin.py
# -*- coding: utf-8 -*-
"""
CC-AC-10B (Control Center Admin API, User Management) — Telegram-freier
Application-Layer für die schreibenden User-Management-Operationen.

Bildet exakt dieselbe Fachlogik/Validierung ab, die
handlers/admin/user_management_handler.py::UserManagementHandler bereits
für den Telegram-Bot implementiert (Rollen-/Berechtigungs-Whitelist,
SEC-005-Owner-Guard, Rolle→Standard-Berechtigungen), als reine, Update/
Message-freie Funktionen auf einem bereits geladenen `users`-Dict
(services/user_data.py::load_user_data()) — dasselbe Muster wie die dort
bereits vorhandenen reinen Lesefunktionen.

CC-AC-10.md §20 sieht die Migration der Telegram-Seite selbst bewusst
erst in CC-AC-10G vor ("Telegram Migration") — dieser Slice (10B) baut
nur die Application-Layer-Funktionen + die API, die UserManagementHandler
zukünftig nutzen KÖNNTE. UserManagementHandler bleibt in diesem Slice
unverändert (kein Risiko für seine bestehenden Characterization-Tests);
ROLES/PERMISSIONS hier sind bewusst dieselben Werte wie dort (siehe
tests/test_user_admin_service.py::test_roles_and_permissions_match_telegram_handler
als Drift-Wächter).

Persistenz bleibt Aufgabe des Aufrufers (load_user_data()/save_user_data()
in services/user_data.py) — diese Funktionen mutieren nur das übergebene
Dict und geben den betroffenen Eintrag zurück, analog zu
UserManagementHandler's eigenen Methoden.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

ROLES = ["user", "moderator", "admin", "owner"]
PERMISSIONS = ["download", "stats", "navidrome", "admin", "all"]

# Rolle -> Standard-Berechtigungen bei Rollenwechsel, 1:1 aus
# UserManagementHandler.set_user_role().
_ROLE_DEFAULT_PERMISSIONS = {
    "owner": ["all"],
    "admin": ["admin", "moderate", "download"],
    "moderator": ["moderate", "download"],
    "user": ["download"],
}


class UserAdminError(Exception):
    """Basisklasse für alle Validierungsfehler dieses Moduls."""


class UserAlreadyExistsError(UserAdminError):
    pass


class UserNotFoundError(UserAdminError):
    pass


class InvalidRoleError(UserAdminError):
    pass


class InvalidPermissionError(UserAdminError):
    pass


class OwnerPromotionDeniedError(UserAdminError):
    pass


def create_user(users: dict, telegram_id: str, navidrome_user: str) -> dict:
    """Legt einen neuen Benutzer an — identische Feldbelegung wie
    UserManagementHandler.process_new_navidrome_user() (role="user",
    permissions=["all"], created_at=jetzt)."""
    if telegram_id in users:
        raise UserAlreadyExistsError(f"Benutzer {telegram_id} existiert bereits.")

    navidrome_user = (navidrome_user or "").strip()
    if not navidrome_user:
        raise UserAdminError("Navidrome-Benutzername darf nicht leer sein.")

    entry = {
        "role": "user",
        "permissions": ["all"],
        "navidrome_user": navidrome_user,
        "created_at": datetime.now().isoformat(),
    }
    users[telegram_id] = entry
    return entry


def update_navidrome_user(users: dict, telegram_id: str, navidrome_user: str) -> dict:
    """Aktualisiert den Navidrome-User eines bestehenden Benutzers —
    identisch zu UserManagementHandler.process_edit_navidrome_user()."""
    if telegram_id not in users:
        raise UserNotFoundError(f"Benutzer {telegram_id} nicht gefunden.")

    navidrome_user = (navidrome_user or "").strip()
    if not navidrome_user:
        raise UserAdminError("Navidrome-Benutzername darf nicht leer sein.")

    users[telegram_id]["navidrome_user"] = navidrome_user
    return users[telegram_id]


def set_user_role(
    users: dict,
    telegram_id: str,
    new_role: str,
    *,
    acting_user_id: int,
    owner_user_id: Optional[int],
) -> dict:
    """Setzt die Rolle eines Benutzers inkl. SEC-005-Owner-Guard — 1:1
    dieselbe Validierungsreihenfolge wie
    UserManagementHandler.set_user_role(): erst Rollen-Whitelist, dann
    Owner-Guard, dann Existenzprüfung (identisch zur Telegram-Seite, wo
    der Owner-Guard ebenfalls vor dem Laden von users[user_id] geprüft
    wird)."""
    if new_role not in ROLES:
        raise InvalidRoleError(f"Unbekannte Rolle: {new_role}")

    if new_role == "owner" and acting_user_id != owner_user_id:
        raise OwnerPromotionDeniedError(
            "Nur der Owner darf die Owner-Rolle vergeben."
        )

    if telegram_id not in users:
        raise UserNotFoundError(f"Benutzer {telegram_id} nicht gefunden.")

    users[telegram_id]["role"] = new_role
    users[telegram_id]["permissions"] = list(_ROLE_DEFAULT_PERMISSIONS[new_role])
    return users[telegram_id]


def set_user_permissions(users: dict, telegram_id: str, permissions: list[str]) -> dict:
    """Setzt die Berechtigungsliste eines Benutzers (REST-PATCH-Semantik:
    voller Ersatz, nicht Toggle wie im Telegram-Flow). Validiert gegen
    dieselbe Whitelist wie UserManagementHandler.toggle_user_permission().
    "all" dominiert wie dort — enthält die übergebene Liste "all", wird
    ausschließlich "all" gespeichert (identische Normalisierung wie beim
    Telegram-Toggle, der "all" beim Hinzufügen ebenfalls exklusiv setzt)."""
    if telegram_id not in users:
        raise UserNotFoundError(f"Benutzer {telegram_id} nicht gefunden.")

    unknown = [p for p in permissions if p not in PERMISSIONS]
    if unknown:
        raise InvalidPermissionError(f"Unbekannte Berechtigung(en): {', '.join(unknown)}")

    if "all" in permissions:
        resolved = ["all"]
    else:
        # Reihenfolge stabil, Duplikate entfernt.
        resolved = list(dict.fromkeys(permissions))

    users[telegram_id]["permissions"] = resolved
    return users[telegram_id]


def delete_user(users: dict, telegram_id: str) -> dict:
    """Löscht einen Benutzer und gibt den entfernten Eintrag zurück —
    identisch zu UserManagementHandler.delete_user(). Keine zusätzliche
    Owner-Schutzregel gegenüber der Telegram-Seite (dort existiert
    ebenfalls keine) — bewusste Paritätsentscheidung, keine strengere
    Regel als das bestehende Verhalten."""
    if telegram_id not in users:
        raise UserNotFoundError(f"Benutzer {telegram_id} nicht gefunden.")
    return users.pop(telegram_id)
