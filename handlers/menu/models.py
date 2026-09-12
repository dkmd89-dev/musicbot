# handlers/menu/models.py
# -*- coding: utf-8 -*-
"""
Menü-Datenmodelle des RichMenuSystem.

ARCH-021/P-2 (Models Extraction): MenuState/AccessLevel/MenuItem/
MenuSession wurden unverändert aus handlers/menu/rich_menu_system.py
hierher verschoben (reine Move-Operation, siehe P-1-Abschlussbericht
Abschnitt 4/13 - diese vier Modelle sind Telegram-unabhängige
Datenmodelle ohne Abhängigkeit auf RichMenuSystem/RichMenuHandler).

Dieses Modul darf keine Abhängigkeit auf rich_menu_system.py,
rich_menu_handler.py oder Telegram-Infrastruktur haben.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from datetime import datetime


class MenuState(Enum):
    """Menü-Zustände für State Machine"""

    IDLE = "idle"
    MAIN_MENU = "main_menu"
    DOWNLOAD_MENU = "download_menu"
    STATS_MENU = "stats_menu"
    ADMIN_MENU = "admin_menu"
    SETTINGS_MENU = "settings_menu"
    LOGGER_MENU = "logger_menu"
    PROCESSING = "processing"
    WAITING_INPUT = "waiting_input"
    ERROR = "error"


class AccessLevel(Enum):
    """Zugriffsebenen für Menüpunkte"""

    PUBLIC = 0
    USER = 1
    MODERATOR = 2
    ADMIN = 3
    OWNER = 4


@dataclass
class MenuItem:
    """Einzelner Menüpunkt mit allen Eigenschaften"""

    id: str
    title: str
    emoji: str = "📋"
    callback_data: Optional[str] = None
    handler: Optional[Callable] = None
    children: List["MenuItem"] = field(default_factory=list)
    parent: Optional["MenuItem"] = None
    access_level: AccessLevel = AccessLevel.USER
    description: Optional[str] = None
    is_active: bool = True
    is_action: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Automatische Callback-Data Generierung"""
        if not self.callback_data:
            self.callback_data = f"menu:{self.id}"

    def has_children(self) -> bool:
        """Prüft ob Menüpunkt Untermenüs hat"""
        return len(self.children) > 0

    def is_accessible(self, user_level: AccessLevel) -> bool:
        """Prüft Zugriffsberechtigung"""
        return user_level.value >= self.access_level.value

    def add_child(self, child: "MenuItem") -> None:
        """Fügt Untermenü hinzu"""
        child.parent = self
        self.children.append(child)

    def get_breadcrumb(self) -> List[str]:
        """Erstellt Brotkrumen-Navigation"""
        path = []
        current = self
        while current:
            path.insert(0, current.title)
            current = current.parent
        return path


@dataclass
class MenuSession:
    """Benutzer-Session für Menü-Interaktionen"""

    user_id: int
    current_menu: Optional[MenuItem] = None
    state: MenuState = MenuState.IDLE
    history: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    message_id: Optional[int] = None

    def is_expired(self, timeout: int = 300) -> bool:
        """Prüft ob Session abgelaufen ist"""
        return (datetime.now() - self.last_activity).seconds > timeout

    def update_activity(self) -> None:
        """Aktualisiert letzte Aktivität"""
        self.last_activity = datetime.now()

    def navigate_to(self, menu_item: MenuItem) -> None:
        """Navigiert zu neuem Menüpunkt"""
        if self.current_menu:
            self.history.append(self.current_menu.id)
        self.current_menu = menu_item
        self.update_activity()

    def go_back(self) -> Optional[str]:
        """Navigiert zurück"""
        if self.history:
            return self.history.pop()
        return None
