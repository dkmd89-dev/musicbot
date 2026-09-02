# tests/unit/test_rich_menu_system.py
# -*- coding: utf-8 -*-
"""
🧪 Unit Tests für RichMenuSystem

Testet alle Kern-Funktionen des Menu-Systems:
- MenuItem Creation & Hierarchy
- Access Control
- Session Management
- Navigation
- Handler Integration
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

from handlers.menu.rich_menu_system import (
    RichMenuSystem,
    MenuItem,
    MenuState,
    AccessLevel,
    MenuSession,
)

# ==================== FIXTURES ====================


@pytest.fixture
def config():
    """Mock Config"""

    class MockConfig:
        OWNER_USER_ID = 12345
        ADMIN_USER_IDS = [12345, 67890]
        SESSION_TIMEOUT = 300
        MAX_CONCURRENT_SESSIONS = 100

    return MockConfig()


@pytest.fixture
def menu_system(config):
    """RichMenuSystem Instanz"""
    system = RichMenuSystem(config)
    system.initialize_menu_structure()
    return system


@pytest.fixture
def mock_update():
    """Mock Telegram Update"""
    update = Mock()
    update.effective_user.id = 12345
    update.callback_query = Mock()
    update.callback_query.data = "menu:test"
    update.callback_query.message.message_id = 1
    return update


@pytest.fixture
def mock_context():
    """Mock Context"""
    context = Mock()
    context.bot = AsyncMock()
    return context


# ==================== MENUITEM TESTS ====================


class TestMenuItem:
    """Tests für MenuItem Klasse"""

    def test_create_basic_item(self):
        """Test: Basis MenuItem Erstellung"""
        item = MenuItem(id="test", title="Test Item", emoji="🧪")

        assert item.id == "test"
        assert item.title == "Test Item"
        assert item.emoji == "🧪"
        assert item.callback_data == "menu:test"
        assert not item.has_children()
        assert item.is_active

    def test_custom_callback_data(self):
        """Test: Benutzerdefinierte Callback-Data"""
        item = MenuItem(id="custom", title="Custom", callback_data="custom:action")

        assert item.callback_data == "custom:action"

    def test_add_child(self):
        """Test: Kind-Menüpunkt hinzufügen"""
        parent = MenuItem(id="parent", title="Parent")
        child = MenuItem(id="child", title="Child")

        parent.add_child(child)

        assert child.parent == parent
        assert parent.has_children()
        assert len(parent.children) == 1
        assert child in parent.children

    def test_breadcrumb_generation(self):
        """Test: Breadcrumb-Navigation"""
        root = MenuItem(id="root", title="Root")
        level1 = MenuItem(id="level1", title="Level 1")
        level2 = MenuItem(id="level2", title="Level 2")

        root.add_child(level1)
        level1.add_child(level2)

        breadcrumb = level2.get_breadcrumb()

        assert breadcrumb == ["Root", "Level 1", "Level 2"]

    def test_access_control(self):
        """Test: Zugriffskontrolle"""
        public_item = MenuItem(
            id="public", title="Public", access_level=AccessLevel.PUBLIC
        )
        admin_item = MenuItem(id="admin", title="Admin", access_level=AccessLevel.ADMIN)

        # Public für alle zugänglich
        assert public_item.is_accessible(AccessLevel.PUBLIC)
        assert public_item.is_accessible(AccessLevel.USER)
        assert public_item.is_accessible(AccessLevel.ADMIN)

        # Admin nur für Admin+
        assert not admin_item.is_accessible(AccessLevel.USER)
        assert admin_item.is_accessible(AccessLevel.ADMIN)
        assert admin_item.is_accessible(AccessLevel.OWNER)


# ==================== SESSION TESTS ====================


class TestMenuSession:
    """Tests für MenuSession Klasse"""

    def test_create_session(self):
        """Test: Session Erstellung"""
        session = MenuSession(user_id=12345)

        assert session.user_id == 12345
        assert session.state == MenuState.IDLE
        assert session.current_menu is None
        assert len(session.history) == 0

    def test_session_expiry(self):
        """Test: Session-Ablauf"""
        session = MenuSession(user_id=12345)

        # Neu erstellt - nicht abgelaufen
        assert not session.is_expired(timeout=300)

        # Ältere Aktivität simulieren
        session.last_activity = datetime.now() - timedelta(seconds=400)
        assert session.is_expired(timeout=300)

    def test_navigate_to(self):
        """Test: Navigation zu neuem Menü"""
        session = MenuSession(user_id=12345)
        menu1 = MenuItem(id="menu1", title="Menu 1")
        menu2 = MenuItem(id="menu2", title="Menu 2")

        session.navigate_to(menu1)
        assert session.current_menu == menu1
        assert len(session.history) == 0

        session.navigate_to(menu2)
        assert session.current_menu == menu2
        assert len(session.history) == 1
        assert session.history[0] == "menu1"

    def test_go_back(self):
        """Test: Zurück-Navigation"""
        session = MenuSession(user_id=12345)
        menu1 = MenuItem(id="menu1", title="Menu 1")
        menu2 = MenuItem(id="menu2", title="Menu 2")

        session.navigate_to(menu1)
        session.navigate_to(menu2)

        previous_id = session.go_back()

        assert previous_id == "menu1"
        assert len(session.history) == 0

    def test_session_data_storage(self):
        """Test: Session-Daten Speicherung"""
        session = MenuSession(user_id=12345)

        session.data["download_type"] = "single"
        session.data["url"] = "https://youtube.com/watch?v=test"

        assert session.data["download_type"] == "single"
        assert session.data["url"] == "https://youtube.com/watch?v=test"


# ==================== RICHMENU SYSTEM TESTS ====================


class TestRichMenuSystem:
    """Tests für RichMenuSystem Klasse"""

    def test_initialization(self, config):
        """Test: System-Initialisierung"""
        system = RichMenuSystem(config)

        assert system.root_menu is None
        assert len(system.menu_registry) == 0
        assert len(system.sessions) == 0

    def test_menu_structure_creation(self, menu_system):
        """Test: Menü-Struktur Erstellung"""
        assert menu_system.root_menu is not None
        assert menu_system.root_menu.id == "main"
        assert len(menu_system.menu_registry) > 0

        # Prüfe Untermenüs
        assert "download" in menu_system.menu_registry
        assert "stats" in menu_system.menu_registry
        assert "admin" in menu_system.menu_registry

    def test_registry_building(self, menu_system):
        """Test: Registry-Aufbau"""
        # Alle Items sollten in Registry sein
        root = menu_system.root_menu

        def count_items(item):
            count = 1
            for child in item.children:
                count += count_items(child)
            return count

        total_items = count_items(root)
        assert len(menu_system.menu_registry) == total_items

    def test_get_session(self, menu_system):
        """Test: Session abrufen"""
        user_id = 12345

        # Erste Session erstellen
        session1 = menu_system.get_session(user_id)
        assert session1.user_id == user_id

        # Gleiche Session sollte zurückgegeben werden
        session2 = menu_system.get_session(user_id)
        assert session1 is session2

    def test_session_renewal(self, menu_system):
        """Test: Session-Erneuerung bei Ablauf"""
        user_id = 12345

        session = menu_system.get_session(user_id)
        old_created_at = session.created_at

        # Session ablaufen lassen
        session.last_activity = datetime.now() - timedelta(seconds=400)

        # Neue Session sollte erstellt werden
        new_session = menu_system.get_session(user_id)
        assert new_session.created_at > old_created_at

    def test_render_menu(self, menu_system):
        """Test: Menü-Rendering"""
        menu = menu_system.menu_registry["main"]
        keyboard = menu_system.render_menu(menu, AccessLevel.USER)

        assert keyboard is not None
        assert len(keyboard.inline_keyboard) > 0

        # Letzter Button sollte "Schließen" sein
        last_row = keyboard.inline_keyboard[-1]
        assert any("Schließen" in btn.text for btn in last_row)

    def test_access_level_filtering(self, menu_system):
        """Test: Zugriffslevel-Filterung"""
        admin_menu = menu_system.menu_registry["admin"]

        # User-Level: Admin-Items nicht sichtbar
        user_keyboard = menu_system.render_menu(menu_system.root_menu, AccessLevel.USER)
        user_buttons = [
            btn.text for row in user_keyboard.inline_keyboard for btn in row
        ]
        assert not any("Admin" in text for text in user_buttons)

        # Admin-Level: Admin-Items sichtbar
        admin_keyboard = menu_system.render_menu(
            menu_system.root_menu, AccessLevel.ADMIN
        )
        admin_buttons = [
            btn.text for row in admin_keyboard.inline_keyboard for btn in row
        ]
        assert any("Admin" in text for text in admin_buttons)

    def test_cleanup_expired_sessions(self, menu_system):
        """Test: Bereinigung abgelaufener Sessions"""
        # Erstelle mehrere Sessions
        for i in range(5):
            menu_system.get_session(i)

        assert len(menu_system.sessions) == 5

        # Lasse 3 Sessions ablaufen
        for i in range(3):
            menu_system.sessions[i].last_activity = datetime.now() - timedelta(
                seconds=400
            )

        # Cleanup durchführen
        cleaned = menu_system.cleanup_expired_sessions()

        assert cleaned == 3
        assert len(menu_system.sessions) == 2

    def test_handler_registration(self, menu_system):
        """Test: Handler-Registrierung"""

        async def test_handler(update, context):
            pass

        menu_system.register_handler("download_single", test_handler)

        item = menu_system.menu_registry["download_single"]
        assert item.handler == test_handler

    @pytest.mark.asyncio
    async def test_show_menu(self, menu_system, mock_update, mock_context):
        """Test: Menü anzeigen"""
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()

        await menu_system.show_menu(mock_update, mock_context, "main")

        mock_update.callback_query.answer.assert_called_once()
        mock_update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_callback_close(self, menu_system, mock_update, mock_context):
        """Test: Schließen-Callback"""
        user_id = mock_update.effective_user.id
        menu_system.get_session(user_id)  # Session erstellen

        mock_update.callback_query.data = "menu:close"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.message.delete = AsyncMock()

        await menu_system.handle_callback(mock_update, mock_context)

        assert user_id not in menu_system.sessions

    @pytest.mark.asyncio
    async def test_handle_callback_back(self, menu_system, mock_update, mock_context):
        """Test: Zurück-Callback"""
        user_id = mock_update.effective_user.id
        session = menu_system.get_session(user_id)

        # Navigation simulieren
        menu1 = menu_system.menu_registry["main"]
        menu2 = menu_system.menu_registry["download"]
        session.navigate_to(menu1)
        session.navigate_to(menu2)

        mock_update.callback_query.data = "menu:back"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()

        await menu_system.handle_callback(mock_update, mock_context)

        assert session.current_menu.id == "main"


# ==================== INTEGRATION TESTS ====================


class TestMenuIntegration:
    """Integrationstests für das gesamte System"""

    @pytest.mark.asyncio
    async def test_full_navigation_flow(self, menu_system, mock_update, mock_context):
        """Test: Kompletter Navigationsablauf"""
        user_id = mock_update.effective_user.id

        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()

        # 1. Hauptmenü öffnen
        await menu_system.show_menu(mock_update, mock_context, "main")
        session = menu_system.get_session(user_id)
        assert session.current_menu.id == "main"

        # 2. Zu Download navigieren
        # Download-Control-Center 2026-09-02 (Nutzer-Vorgabe): "download"
        # hat jetzt einen eigenen handler= (wie dup:/backup_/status_) und
        # rendert seine Tastatur komplett selbst (_render_download_menu()),
        # statt ueber die generische show_menu()-Navigation zu laufen -
        # session.current_menu bleibt dadurch bewusst unveraendert auf
        # "main" (analog zu allen anderen Aktions-Menuepunkten).
        mock_update.callback_query.data = "menu:download"
        await menu_system.handle_callback(mock_update, mock_context)
        assert session.current_menu.id == "main"
        sent_text = mock_update.callback_query.edit_message_text.call_args.args[0]
        assert "Downloads" in sent_text

        # 3. Zurück navigieren
        mock_update.callback_query.data = "menu:back"
        await menu_system.handle_callback(mock_update, mock_context)
        assert session.current_menu.id == "main"

        # 4. Schließen
        mock_update.callback_query.data = "menu:close"
        await menu_system.handle_callback(mock_update, mock_context)
        assert user_id not in menu_system.sessions

    def test_menu_hierarchy_integrity(self, menu_system):
        """Test: Menü-Hierarchie Integrität"""
        # Alle Items außer Root sollten Parent haben
        for item_id, item in menu_system.menu_registry.items():
            if item_id != "main":
                assert item.parent is not None, f"{item_id} hat keinen Parent"

        # Root sollte keinen Parent haben
        assert menu_system.root_menu.parent is None

    def test_callback_data_uniqueness(self, menu_system):
        """
        Test: Callback-Data Einzigartigkeit.

        Reine Link-Items (handler=None, is_action=False) sind bewusste
        Navigations-Shortcuts, die absichtlich dieselbe callback_data wie
        ihr Ziel-Menuepunkt tragen (z.B. "nav_link_stats" verweist bewusst
        auf dieselbe callback_data "menu:stats" wie der echte "stats"-
        Menuepunkt, um von einem Untermenue aus direkt dorthin zu
        springen). Nur echte, eigenstaendige Menuepunkte muessen
        eindeutige callback_data haben.
        """
        callback_datas = [
            item.callback_data
            for item in menu_system.menu_registry.values()
            if item.handler is not None or item.is_action
        ]

        # Alle Callback-Datas eigenstaendiger Menuepunkte sollten einzigartig sein
        assert len(callback_datas) == len(set(callback_datas))


# ==================== PERFORMANCE TESTS ====================


class TestPerformance:
    """Performance-Tests"""

    def test_large_session_cleanup(self, menu_system):
        """Test: Cleanup mit vielen Sessions"""
        import time

        # 100 Sessions erstellen
        for i in range(100):
            menu_system.get_session(i)

        # 50 ablaufen lassen
        for i in range(50):
            menu_system.sessions[i].last_activity = datetime.now() - timedelta(
                seconds=400
            )

        # Cleanup messen
        start = time.time()
        cleaned = menu_system.cleanup_expired_sessions()
        duration = time.time() - start

        assert cleaned == 50
        assert duration < 1.0  # Sollte unter 1 Sekunde sein

    def test_registry_lookup_performance(self, menu_system):
        """Test: Registry-Lookup Performance"""
        import time

        # 1000 Lookups
        start = time.time()
        for _ in range(1000):
            _ = menu_system.menu_registry.get("download")
        duration = time.time() - start

        assert duration < 0.1  # Sollte sehr schnell sein


# ==================== PYTEST CONFIGURATION ====================


def pytest_configure(config):
    """Pytest Konfiguration"""
    config.addinivalue_line("markers", "asyncio: mark test as async")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=handlers.menu", "--cov-report=html"])
