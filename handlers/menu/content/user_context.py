# handlers/menu/content/user_context.py
# -*- coding: utf-8 -*-
"""
Nutzer-Kontext-Auflösung für die Onboarding-Oberfläche (/start, /help,
Help-Callback): Feature-Katalog, Rollen-/Neuling-Ermittlung.

ARCH-025 (Command/Help Decomposition): 1:1 aus
handlers/menu/rich_menu_handler.py verschoben (FEATURES-Katalog,
_load_user_data()/_get_user_info()/_is_new_user()/_get_user_role()/
_get_available_features()). RichMenuHandler behält alle fünf Methoden
als dünne Delegatoren (weiterhin von Bestandstests direkt aufgerufen,
siehe tests/test_rich_menu_handler.py::TestGetUserRole/TestIsNewUser/
TestGetAvailableFeatures/TestUserDataFileIsolation).

Bewusst kein reiner Permission-Belang (siehe handlers/menu/permissions.py-
Docstring) - get_user_role() liefert eine String-Rolle für Begrüßungs-/
Hilfetext, nicht die AccessLevel-Enum aus permissions.get_user_access_level().
Beide bleiben getrennt (unterschiedliche Rückgabetypen/Konsumenten,
ARCH-021/P-3-Entscheidung).
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional


FEATURES: Dict[str, Dict] = {
    "download": {
        "emoji": "📥",
        "title": "Downloads",
        "description": "Lade Musik von YouTube herunter",
        "commands": ["/download"],
        "min_role": "user",
        "menu_id": "download",
    },
    "stats": {
        "emoji": "📊",
        "title": "Statistiken",
        "description": "Zeige deine Hörstatistiken",
        "commands": ["/stats", "/month", "/year"],
        "min_role": "user",
        "menu_id": "stats",
    },
    "navidrome": {
        "emoji": "🎵",
        "title": "Navidrome",
        "description": "Durchsuche deine Musikbibliothek",
        "commands": ["/navidrome", "/search"],
        "min_role": "user",
        "menu_id": "navidrome",
    },
    "admin": {
        "emoji": "⚙️",
        "title": "Administration",
        "description": "Systemverwaltung und User-Management",
        "commands": ["/admin", "/users"],
        "min_role": "admin",
        "menu_id": "admin",
    },
    "tests": {
        "emoji": "🧪",
        "title": "Test-System",
        "description": "Unit-, Integrations- und Performance-Tests",
        "commands": ["/tests"],
        "min_role": "admin",
        "menu_id": "tests",
    },
}


def load_user_data(user_data_file, logger, user_mgmt_handler=None) -> Dict[str, Any]:
    """Lädt User-Daten aus JSON."""
    try:
        if user_data_file.exists():
            with open(user_data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if user_mgmt_handler:
                    user_mgmt_handler.user_data_cache = data
                return data
        return {}
    except Exception as e:
        logger.error(f"❌ Fehler beim Laden der User-Daten: {e}")
        return {}


def get_user_info(
    user_id: int, user_data_file, logger, user_mgmt_handler=None
) -> Optional[Dict[str, Any]]:
    """Holt User-Informationen."""
    if user_mgmt_handler and user_mgmt_handler.user_data_cache:
        return user_mgmt_handler.user_data_cache.get(str(user_id))
    users = load_user_data(user_data_file, logger, user_mgmt_handler)
    return users.get(str(user_id))


def is_new_user(user_id: int, user_data_file, logger, user_mgmt_handler=None) -> bool:
    """Prüft ob User neu ist (< 24h registriert)."""
    user_info = get_user_info(user_id, user_data_file, logger, user_mgmt_handler)
    if not user_info:
        return True
    created_at = user_info.get("created_at")
    if created_at:
        try:
            created_time = datetime.fromisoformat(created_at)
            return (datetime.now() - created_time).total_seconds() < 86400
        except Exception:
            pass
    return False


def get_user_role(
    user_id: int, config, user_data_file, logger, user_mgmt_handler=None
) -> str:
    """Ermittelt User-Rolle (owner > admin > moderator > user)."""
    if user_id == config.OWNER_USER_ID:
        return "owner"
    user_info = get_user_info(user_id, user_data_file, logger, user_mgmt_handler)
    if user_info:
        return user_info.get("role", "user")
    if user_id in getattr(config, "ADMIN_USER_IDS", []):
        return "admin"
    return "user"


def get_available_features(user_role: str) -> Dict[str, Dict]:
    """Gibt verfügbare Features basierend auf Rolle zurück."""
    role_hierarchy = {"user": 0, "moderator": 1, "admin": 2, "owner": 3}
    user_level = role_hierarchy.get(user_role, 0)
    return {
        fid: fdata
        for fid, fdata in FEATURES.items()
        if user_level >= role_hierarchy.get(fdata.get("min_role", "user"), 0)
    }
