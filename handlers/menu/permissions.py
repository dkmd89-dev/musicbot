# handlers/menu/permissions.py
# -*- coding: utf-8 -*-
"""
Gemeinsame Permission-/Rollenauflösung für RichMenuHandler und
RichMenuSystem (ARCH-021/P-3, Permissions-Characterization +
Vereinheitlichung).

Vereinheitlicht:
  - is_admin_or_owner()     ersetzt RichMenuHandler._is_admin() UND
                             RichMenuSystem._is_admin_check() (bisher
                             zwei unabhängige, aber - siehe
                             tests/test_menu_permissions_characterization.py
                             - für jede reale Config bereits äquivalente
                             Implementierungen).
  - get_user_access_level() unverändert aus
                             RichMenuSystem._get_user_access_level()
                             hierher verschoben (reine Funktion von
                             user_id/config/user_mgmt_handler, kein
                             Datei-I/O).

Bewusst NICHT vereinheitlicht (siehe P-1-Abschlussbericht Abschnitt 10
und der Modul-Docstring von tests/test_menu_permissions_characterization.py):
RichMenuHandler._get_user_role() liefert eine String-Rolle für
Begrüßungstext/Feature-Liste und hängt an
RichMenuHandler._get_user_info()/_load_user_data() (JSON-Datei-Fallback,
State-Belang) - das ist kein reiner Permission-Belang und bleibt
unverändert in rich_menu_handler.py.

Dieses Modul darf keine Abhängigkeit auf rich_menu_system.py,
rich_menu_handler.py oder Telegram-Infrastruktur haben.
"""

from typing import Any, Optional

from handlers.menu.models import AccessLevel


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
