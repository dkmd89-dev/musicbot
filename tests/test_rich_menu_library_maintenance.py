# tests/test_rich_menu_library_maintenance.py
# -*- coding: utf-8 -*-
"""
Library-Wartung-Menüpunkt ("🧹 Library-Wartung",
libmaint:start/artists/pick/action/confirm/execute) - Menü-/Callback-
Dispatch-Logik in RichMenuSystem (Admin-Gating + Routing an den echten
LibraryMaintenanceHandler, ARCH-032 Phase 4).

Deckt NUR die Dispatch-/Gating-Ebene ab - die eigentliche Handler-Logik
hat eigene Tests in tests/test_library_maintenance_handler.py. Testmuster
analog zu tests/test_rich_menu_repair.py.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.library_maintenance_handler import LibraryMaintenanceHandler
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
def maintenance_handler():
    return LibraryMaintenanceHandler(FakeConfig(), logger_factory=lambda name: Mock())


@pytest.fixture
def menu_system(maintenance_handler):
    system = RichMenuSystem(FakeConfig())
    system.initialize_menu_structure()
    system.set_library_maintenance_handler(maintenance_handler)
    return system


def _mock_update(user_id):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.data = None
    return update


@pytest.fixture
def mock_context():
    context = Mock()
    context.bot = AsyncMock()
    return context


def run_async(coro):
    return asyncio.run(coro)


class TestMenuItemRegistration:
    def test_admin_library_maintenance_is_child_of_library_group(self, menu_system):
        item = menu_system.menu_registry["admin_library_maintenance"]
        library_group = menu_system.menu_registry["admin_group_library"]
        assert item in library_group.children
        assert item.callback_data == "libmaint:start"

    def test_does_not_collide_with_bot_maintenance_mode_prefix(self, menu_system):
        """libmaint: (Library-Wartung) und maint: (Bot-Wartungsmodus) sind
        bewusst unterschiedliche Praefixe - Kollisionsschutz."""
        item = menu_system.menu_registry["admin_library_maintenance"]
        assert not item.callback_data.startswith("maint:")
        assert item.callback_data.startswith("libmaint:")


class TestLibraryMaintenanceDispatchGating:
    @pytest.mark.parametrize(
        "callback_data",
        [
            "libmaint:start", "libmaint:artists", "libmaint:pick:0",
            "libmaint:action:artist-casing:0", "libmaint:confirm:artist-casing:0",
            "libmaint:execute:artist-casing:0",
        ],
    )
    def test_non_admin_rejected_on_every_subaction(
        self, menu_system, mock_context, callback_data
    ):
        update = _mock_update(OTHER_ID)
        update.callback_query.data = callback_data
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_called_with(
            "⛔ Keine Berechtigung", show_alert=True
        )

    def test_owner_can_open_start(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:start"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.edit_message_text.assert_called()

    def test_admin_can_open_start(self, menu_system, mock_context):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "libmaint:start"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.edit_message_text.assert_called()

    def test_missing_maintenance_handler_shows_not_available(self, mock_context):
        system = RichMenuSystem(FakeConfig())
        system.initialize_menu_structure()
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:start"
        run_async(system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_called_with(
            "⚠️ Library-Wartung-Handler nicht verfügbar", show_alert=True
        )

    def test_unknown_subaction_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:totally_unknown"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Unbekannter Library-Wartung-Callback")

    def test_malformed_pick_index_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:pick:not-a-number"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Ungültiger Callback", show_alert=True)

    def test_unknown_action_in_preview_callback_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:action:totally-unknown-action:0"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Unbekannte Aktion", show_alert=True)

    def test_crafted_set_genre_action_callback_answers_gracefully_not_keyerror(
        self, menu_system, mock_context
    ):
        """Regressionstest fuer den in Library Genre Management v2
        behobenen KeyError: set-genre ist seit der Umstellung auf den
        gs:*-Flow bewusst aus _MAINTENANCE_ACTIONS ausgeschlossen (siehe
        handlers/menu/actions/library.py) - ein von Hand konstruiertes
        "libmaint:action:set-genre:0" (SEC-003: callback_data ist frei
        sendbar) darf nur eine "Unbekannte Aktion"-Meldung ausloesen,
        nie einen unbehandelten KeyError."""
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:action:set-genre:0"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Unbekannte Aktion", show_alert=True)


# ── 🎭 Genre-Verwaltung: Dispatch-Routing (Library Genre Management v2) ──
# Deckt NUR ab, dass jedes neue libmaint:*-Callback-Muster admin-gated ist
# und an die richtige Handler-Methode geroutet wird - die eigentliche
# Handler-Logik hat eigene Tests in
# tests/test_library_maintenance_genre_management.py.


class TestGenreManagementDispatchRouting:
    @pytest.mark.parametrize(
        "callback_data",
        [
            "libmaint:genremenu:0",
            "libmaint:missing",
            "libmaint:missingpick:0",
            "libmaint:gs:src",
            "libmaint:gs:mapping",
            "libmaint:gs:manual",
            "libmaint:gs:mode:overwrite",
            "libmaint:gs:save:yes",
            "libmaint:gs:confirm",
            "libmaint:gs:execute",
            "libmaint:gr:preview",
            "libmaint:gr:confirm",
            "libmaint:gr:execute",
        ],
    )
    def test_non_admin_rejected(self, menu_system, mock_context, callback_data):
        update = _mock_update(OTHER_ID)
        update.callback_query.data = callback_data
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_called_with(
            "⛔ Keine Berechtigung", show_alert=True
        )

    @pytest.mark.parametrize(
        "callback_data, method_name, expected_args",
        [
            ("libmaint:genremenu:3", "handle_genre_menu", (3,)),
            ("libmaint:missing", "handle_missing_genre_start", ()),
            ("libmaint:missingpick:2", "handle_missing_genre_pick", (2,)),
            ("libmaint:gs:src", "handle_gs_src", ()),
            ("libmaint:gs:mapping", "handle_gs_mapping", ()),
            ("libmaint:gs:manual", "handle_gs_manual", ()),
            ("libmaint:gs:confirm", "handle_gs_confirm", ()),
            ("libmaint:gs:execute", "handle_gs_execute", ()),
            ("libmaint:gr:preview", "handle_gr_preview", ()),
            ("libmaint:gr:confirm", "handle_gr_confirm", ()),
            ("libmaint:gr:execute", "handle_gr_execute", ()),
        ],
    )
    def test_routes_to_correct_handler_method(
        self, menu_system, maintenance_handler, mock_context,
        callback_data, method_name, expected_args,
    ):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = callback_data
        with patch.object(maintenance_handler, method_name, AsyncMock()) as mocked:
            run_async(menu_system.handle_callback(update, mock_context))
        mocked.assert_called_once_with(update, mock_context, *expected_args)

    @pytest.mark.parametrize(
        "callback_data, mode",
        [("libmaint:gs:mode:overwrite", "overwrite"), ("libmaint:gs:mode:onlymissing", "onlymissing")],
    )
    def test_routes_gs_mode_with_mode_argument(
        self, menu_system, maintenance_handler, mock_context, callback_data, mode
    ):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = callback_data
        with patch.object(maintenance_handler, "handle_gs_mode", AsyncMock()) as mocked:
            run_async(menu_system.handle_callback(update, mock_context))
        mocked.assert_called_once_with(update, mock_context, mode)

    @pytest.mark.parametrize(
        "callback_data, save",
        [("libmaint:gs:save:yes", True), ("libmaint:gs:save:no", False)],
    )
    def test_routes_gs_save_with_bool_argument(
        self, menu_system, maintenance_handler, mock_context, callback_data, save
    ):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = callback_data
        with patch.object(maintenance_handler, "handle_gs_save", AsyncMock()) as mocked:
            run_async(menu_system.handle_callback(update, mock_context))
        mocked.assert_called_once_with(update, mock_context, save)

    def test_invalid_genremenu_index_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:genremenu:not-a-number"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Ungültiger Callback", show_alert=True)

    def test_invalid_missingpick_index_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:missingpick:not-a-number"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Ungültiger Callback", show_alert=True)

    def test_unknown_gs_subaction_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:gs:totally-unknown"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Unbekannter Genre-Setzen-Callback")

    def test_unknown_gr_subaction_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:gr:totally-unknown"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call(
            "⚠️ Unbekannter Genre-Revalidierung-Callback"
        )


# ── 📝 Metadaten bearbeiten: Dispatch-Routing (Manual Metadata Editing v1) ─
# Deckt NUR ab, dass jedes neue libmaint:meta:*-Callback-Muster admin-gated
# ist und an die richtige Handler-Methode geroutet wird - die eigentliche
# Handler-Logik hat eigene Tests in
# tests/test_library_maintenance_metadata_edit.py.


class TestMetadataEditDispatchRouting:
    @pytest.mark.parametrize(
        "callback_data",
        [
            "libmaint:meta:0",
            "libmaint:meta:artist:0",
            "libmaint:meta:artist:confirm",
            "libmaint:meta:artist:execute",
            "libmaint:meta:title:0",
            "libmaint:meta:title:pick:0:1",
            "libmaint:meta:title:confirm",
            "libmaint:meta:title:execute",
        ],
    )
    def test_non_admin_rejected(self, menu_system, mock_context, callback_data):
        update = _mock_update(OTHER_ID)
        update.callback_query.data = callback_data
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_called_with(
            "⛔ Keine Berechtigung", show_alert=True
        )

    @pytest.mark.parametrize(
        "callback_data, method_name, expected_args",
        [
            ("libmaint:meta:3", "handle_meta_menu", (3,)),
            ("libmaint:meta:artist:3", "handle_meta_artist_start", (3,)),
            ("libmaint:meta:artist:confirm", "handle_meta_artist_confirm", ()),
            ("libmaint:meta:artist:execute", "handle_meta_artist_execute", ()),
            ("libmaint:meta:title:3", "handle_meta_title_start", (3,)),
            ("libmaint:meta:title:confirm", "handle_meta_title_confirm", ()),
            ("libmaint:meta:title:execute", "handle_meta_title_execute", ()),
        ],
    )
    def test_routes_to_correct_handler_method(
        self, menu_system, maintenance_handler, mock_context,
        callback_data, method_name, expected_args,
    ):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = callback_data
        with patch.object(maintenance_handler, method_name, AsyncMock()) as mocked:
            run_async(menu_system.handle_callback(update, mock_context))
        mocked.assert_called_once_with(update, mock_context, *expected_args)

    def test_routes_title_pick_with_both_indices(self, menu_system, maintenance_handler, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:meta:title:pick:2:7"
        with patch.object(maintenance_handler, "handle_meta_title_pick", AsyncMock()) as mocked:
            run_async(menu_system.handle_callback(update, mock_context))
        mocked.assert_called_once_with(update, mock_context, 2, 7)

    def test_invalid_meta_index_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:meta:not-a-number"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Ungültiger Callback", show_alert=True)

    def test_invalid_artist_start_index_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:meta:artist:not-a-number"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Ungültiger Callback", show_alert=True)

    def test_invalid_title_pick_indices_answer_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:meta:title:pick:0:not-a-number"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Ungültiger Callback", show_alert=True)

    def test_unknown_meta_subaction_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:meta:title:pick:0:1:extra"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Unbekannter Metadaten-Callback")
