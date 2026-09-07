# tests/test_rich_menu_doctor.py
# -*- coding: utf-8 -*-
"""
MusicBot-Doctor-Menüpunkt (Phase 3, P1.3: "🩺 MusicBot Doctor",
doctor:scan/doctor:apply_safe/doctor:apply_safe_confirm) - Menü-/
Callback-Dispatch-Logik in RichMenuSystem (Admin-Gating + Routing an den
echten LibraryDoctorHandler).

Deckt NUR die Dispatch-/Gating-Ebene ab (RichMenuSystem) - die eigentliche
Handler-Logik hat eigene Tests in tests/test_library_doctor_handler.py,
die Subprozess-Orchestrierung eigene Tests in tests/test_doctor_runner.py.
Testmuster analog zu tests/test_rich_menu_reprocessing.py - Unterschied:
Doctor ist ADMIN-Level, nicht OWNER-only (SAFE_AUTOMATIC ist verlustfrei,
kein Netzwerk, siehe docs/LIBRARY_REPAIR.md §3).
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.library_doctor_handler import LibraryDoctorHandler
from handlers.menu.rich_menu_system import RichMenuSystem


class FakeConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100


OWNER_ID = 12345
ADMIN_ID = 67890
OTHER_ID = 999


@pytest.fixture
def doctor_handler():
    return LibraryDoctorHandler(FakeConfig(), logger_factory=lambda name: Mock())


@pytest.fixture
def menu_system(doctor_handler):
    system = RichMenuSystem(FakeConfig())
    system.initialize_menu_structure()
    system.set_doctor_handler(doctor_handler)
    return system


def _mock_update(user_id):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message = Mock()
    update.callback_query.message.edit_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    context = Mock()
    context.bot = AsyncMock()
    return context


def run_async(coro):
    return asyncio.run(coro)


def last_text(update):
    return update.callback_query.edit_message_text.call_args.args[0]


class TestMenuItemRegistration:
    def test_admin_library_doctor_is_child_of_admin_menu(self, menu_system):
        item = menu_system.menu_registry["admin_library_doctor"]
        admin_menu = menu_system.menu_registry["admin"]

        assert item in admin_menu.children
        assert item.callback_data == "doctor:scan"


class TestDoctorScanGating:
    def test_owner_triggers_scan(self, menu_system, doctor_handler, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "doctor:scan"

        with patch.object(
            doctor_handler, "handle_scan", new=AsyncMock()
        ) as mocked_scan:
            run_async(menu_system.handle_callback(update, mock_context))

        mocked_scan.assert_awaited_once_with(update, mock_context)

    def test_admin_but_not_owner_also_triggers_scan(
        self, menu_system, doctor_handler, mock_context
    ):
        """Unterschied zu Reprocessing (dort nur Owner): Doctor-Scan ist
        Admin-Level ausreichend."""
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "doctor:scan"

        with patch.object(
            doctor_handler, "handle_scan", new=AsyncMock()
        ) as mocked_scan:
            run_async(menu_system.handle_callback(update, mock_context))

        mocked_scan.assert_awaited_once()

    def test_other_user_is_rejected(self, menu_system, doctor_handler, mock_context):
        update = _mock_update(OTHER_ID)
        update.callback_query.data = "doctor:scan"

        with patch.object(
            doctor_handler, "handle_scan", new=AsyncMock()
        ) as mocked_scan:
            run_async(menu_system.handle_callback(update, mock_context))

        mocked_scan.assert_not_awaited()
        update.callback_query.answer.assert_awaited_once()
        assert update.callback_query.answer.call_args.kwargs.get("show_alert") is True


class TestDoctorApplySafeRouting:
    def test_apply_safe_routes_to_confirm_prompt(
        self, menu_system, doctor_handler, mock_context
    ):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "doctor:apply_safe"

        with patch.object(
            doctor_handler, "handle_apply_safe_confirm_prompt", new=AsyncMock()
        ) as mocked:
            run_async(menu_system.handle_callback(update, mock_context))

        mocked.assert_awaited_once_with(update, mock_context)

    def test_apply_safe_confirm_routes_to_confirmed_handler(
        self, menu_system, doctor_handler, mock_context
    ):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "doctor:apply_safe_confirm"

        with patch.object(
            doctor_handler, "handle_apply_safe_confirmed", new=AsyncMock()
        ) as mocked:
            run_async(menu_system.handle_callback(update, mock_context))

        mocked.assert_awaited_once_with(update, mock_context)

    def test_other_user_cannot_reach_apply_safe_confirm(
        self, menu_system, doctor_handler, mock_context
    ):
        update = _mock_update(OTHER_ID)
        update.callback_query.data = "doctor:apply_safe_confirm"

        with patch.object(
            doctor_handler, "handle_apply_safe_confirmed", new=AsyncMock()
        ) as mocked:
            run_async(menu_system.handle_callback(update, mock_context))

        mocked.assert_not_awaited()

    def test_unknown_doctor_callback_is_reported(
        self, menu_system, doctor_handler, mock_context
    ):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "doctor:something_unexpected"

        run_async(menu_system.handle_callback(update, mock_context))

        update.callback_query.answer.assert_awaited_once_with(
            "⚠️ Unbekannter Doctor-Callback"
        )


class TestDoctorHandlerNotAvailable:
    def test_scan_without_doctor_handler_reports_unavailable(self, mock_context):
        system = RichMenuSystem(FakeConfig())
        system.initialize_menu_structure()
        # set_doctor_handler() bewusst NICHT aufgerufen.
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "doctor:scan"

        run_async(system.handle_callback(update, mock_context))

        update.callback_query.answer.assert_awaited_once_with(
            "⚠️ Doctor-Handler nicht verfügbar", show_alert=True
        )
