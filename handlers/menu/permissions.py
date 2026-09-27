# handlers/menu/permissions.py
# -*- coding: utf-8 -*-
"""
Gemeinsame Permission-/Rollenauflösung für RichMenuHandler und
RichMenuSystem (ARCH-021/P-3, Permissions-Characterization +
Vereinheitlichung).

Die eigentliche Implementierung (AccessLevel, is_admin_or_owner(),
get_user_access_level()) liegt seit Backlog-Punkt "AccessLevel/
permissions nach services/ verschieben" (docs/audits/
WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md §2.3 D / §5 Nr. 8) in
services/access_control.py — unverändert verschoben, nicht neu
geschrieben (siehe dortiger Docstring für die volle Historie/Begründung:
is_admin_or_owner() ersetzt(e) RichMenuHandler._is_admin() UND
RichMenuSystem._is_admin_check(); get_user_access_level() kam unverändert
aus RichMenuSystem._get_user_access_level()). Dieses Modul bleibt als
Re-Export bestehen, damit die 14+ bestehenden handlers/-Importstellen
(`from handlers.menu.permissions import is_admin_or_owner`) unverändert
funktionieren; control_center/ importiert seit demselben Schritt direkt
aus services/access_control.py.

Bewusst NICHT vereinheitlicht (siehe P-1-Abschlussbericht Abschnitt 10
und der Modul-Docstring von tests/test_menu_permissions_characterization.py):
RichMenuHandler._get_user_role() liefert eine String-Rolle für
Begrüßungstext/Feature-Liste und hängt an
RichMenuHandler._get_user_info()/_load_user_data() (JSON-Datei-Fallback,
State-Belang) - das ist kein reiner Permission-Belang. RichMenuHandler
behält diese Methodennamen als dünne Delegatoren; die Implementierung
liegt seit ARCH-025 in handlers/menu/content/user_context.py (reine
Verschiebung, unverändertes Verhalten).

Dieses Modul darf keine Abhängigkeit auf rich_menu_system.py,
rich_menu_handler.py oder Telegram-Infrastruktur haben.
"""

from services.access_control import AccessLevel, get_user_access_level, is_admin_or_owner

__all__ = ["AccessLevel", "get_user_access_level", "is_admin_or_owner"]
