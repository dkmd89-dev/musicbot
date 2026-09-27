# services/access_control.py
# -*- coding: utf-8 -*-
"""
Zugriffsebenen-Modell und Permission-Auflösung: AccessLevel,
is_admin_or_owner(), get_user_access_level().

Backlog-Punkt "AccessLevel/permissions aus handlers/menu/ nach services/
verschieben" (docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md
§2.3 D / §5 Nr. 8) — reiner Move + Re-Export, keine Verhaltensänderung.

Ursprünglich in handlers/menu/models.py (AccessLevel, ARCH-021/P-2) bzw.
handlers/menu/permissions.py (is_admin_or_owner()/get_user_access_level(),
ARCH-021/P-3). Beide waren bereits vollständig Telegram-frei, lagen aber
strukturell im "falschen" Paket: control_center/ (17 Router-/
Dependency-Module) importierte damit Fachlogik aus handlers/, obwohl
CLAUDE.md §4 dafür eigentlich services/ vorsieht. handlers/menu/models.py
und handlers/menu/permissions.py re-exportieren ab hier unverändert, damit
die 14+ bestehenden handlers/-Importstellen (Telegram-seitige Konsumenten,
außerhalb des Scopes dieses Schritts) unverändert funktionieren; die
control_center/-Importstellen wurden direkt auf dieses Modul umgestellt.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class AccessLevel(Enum):
    """Zugriffsebenen für Menüpunkte"""

    PUBLIC = 0
    USER = 1
    MODERATOR = 2
    ADMIN = 3
    OWNER = 4


def is_admin_or_owner(user_id: int, config: Any) -> bool:
    """
    Prüft Admin- oder Owner-Rechte anhand der Config.

    Gibt True zurück für Owner (config.OWNER_USER_ID) und alle in
    config.ADMIN_USER_IDS konfigurierten Admins. getattr(..., None)/
    getattr(..., []) statt direktem Attributzugriff, damit eine Config
    ohne diese Attribute nicht mit AttributeError abbricht, sondern
    korrekt "kein Admin" liefert (die echte config.Config definiert
    beide Attribute immer - dieser Fall betrifft nur minimalistische
    Test-/Fake-Configs, siehe
    tests/test_menu_permissions_characterization.py::TestIsAdminOrOwnerEdgeCase).
    """
    if user_id == getattr(config, "OWNER_USER_ID", None):
        return True
    return user_id in getattr(config, "ADMIN_USER_IDS", [])


def get_user_access_level(
    user_id: int, config: Any, user_mgmt_handler: Optional[Any]
) -> AccessLevel:
    """Ermittelt Zugriffsebene des Users (Button-Rendering, siehe
    MenuItem.is_accessible()). Unverändert aus
    RichMenuSystem._get_user_access_level() verschoben."""
    if user_id == config.OWNER_USER_ID:
        return AccessLevel.OWNER

    if user_mgmt_handler and hasattr(user_mgmt_handler, "user_data_cache"):
        user_data = user_mgmt_handler.user_data_cache.get(str(user_id))
        if user_data:
            role_str = user_data.get("role", "user").upper()
            if role_str == "ADMIN":
                return AccessLevel.ADMIN
            if role_str == "MODERATOR":
                return AccessLevel.MODERATOR
            if role_str == "USER":
                return AccessLevel.USER

    if user_id in getattr(config, "ADMIN_USER_IDS", []):
        return AccessLevel.ADMIN

    return AccessLevel.USER
