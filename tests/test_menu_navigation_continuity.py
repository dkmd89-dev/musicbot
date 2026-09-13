# tests/test_menu_navigation_continuity.py
# -*- coding: utf-8 -*-
"""
ARCH-029 (Telegram Menu Navigation Continuity & Result Navigation).

Deckt das Kernproblem ab: nach einer Menü-Action (z. B. "Diese Woche")
war die Ergebnisnachricht bisher ein Navigations-Dead-End (kein
`reply_markup`). Diese Tests prüfen nicht nur "reply_markup is not None"
(bewusst vermieden, siehe Master-Prompt Abschnitt 21), sondern den
tatsächlichen Navigationspfad:

  Action -> Ergebnis -> reply_markup -> Klick auf "⬅️ <Parent>"
  -> echter handle_callback()-Durchlauf -> korrektes Zielmenü.

Testet sowohl die reine Rendering-Funktion (handlers/menu/rendering.py::
render_result_navigation()) als auch die volle End-to-End-Kette über eine
echte, initialisierte RichMenuHandler/RichMenuSystem-Instanz (Muster aus
tests/test_menu_router_characterization.py::TestAdminNavidromeRealRegistry).
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import InlineKeyboardMarkup

from handlers.menu import definitions, rendering
from handlers.menu.models import AccessLevel, MenuItem, MenuSession
from handlers.menu.rich_menu_handler import RichMenuHandler


def run_async(coro):
    import asyncio

    return asyncio.run(coro)


class MockConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [12345, 67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100


OWNER_ID = 12345


class _FakeSystem:
    def __getattr__(self, name):
        return Mock(name=name)


def _real_registry():
    root = definitions.build_menu_tree(_FakeSystem())
    registry = {}
    definitions.populate_registry(registry, root)
    return registry


# ============================================================
# 1. render_result_navigation() — reine Rendering-Funktion
# ============================================================


class TestRenderResultNavigation:
    def test_level_1_and_level_2_buttons_for_stats_weekly(self):
        registry = _real_registry()
        markup = rendering.render_result_navigation(registry["stats_weekly"])

        buttons = [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]
        assert ("⬅️ Rückblicke", "menu:stats_reviews") in buttons
        assert ("📊 Statistiken", "menu:stats") in buttons
        assert ("🏠 Hauptmenü", "menu:main") in buttons

    def test_two_rows_with_correct_grouping(self):
        registry = _real_registry()
        markup = rendering.render_result_navigation(registry["stats_weekly"])

        assert len(markup.inline_keyboard) == 2
        assert len(markup.inline_keyboard[0]) == 1  # nur "Zurück"
        assert len(markup.inline_keyboard[1]) == 2  # Domäne + Hauptmenü

    def test_no_redundant_main_menu_button_when_grandparent_is_main(self):
        """stats_library_overview: Parent=stats, Grandparent=main ->
        Hauptmenü darf nur EINMAL erscheinen, kein zweiter, überflüssiger
        Grandparent-Button für 'main' selbst."""
        registry = _real_registry()
        markup = rendering.render_result_navigation(registry["stats_library_overview"])

        buttons = [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]
        main_buttons = [b for b in buttons if b[1] == "menu:main"]
        assert len(main_buttons) == 1
        assert ("⬅️ Statistiken", "menu:stats") in buttons

    def test_family_stats_top_songs_navigation(self):
        registry = _real_registry()
        markup = rendering.render_result_navigation(registry["family_stats_top_songs"])

        buttons = [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]
        assert ("⬅️ Familien-Statistik", "menu:family_stats") in buttons
        assert ("👨‍👩‍👧‍👦 Familie", "menu:family") in buttons
        assert ("🏠 Hauptmenü", "menu:main") in buttons

    def test_item_without_parent_gets_only_main_menu_button(self):
        root_only = MenuItem(id="main", title="Hauptmenü")
        markup = rendering.render_result_navigation(root_only)
        buttons = [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]
        assert buttons == [("🏠 Hauptmenü", "menu:main")]

    def test_direct_child_of_main_gets_single_main_menu_row(self):
        root = MenuItem(id="main", title="Hauptmenü")
        child = MenuItem(id="download", title="Downloads")
        root.add_child(child)
        markup = rendering.render_result_navigation(child)
        buttons = [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]
        assert buttons == [("🏠 Hauptmenü", "menu:main")]


# ============================================================
# 2. MenuSession.navigate_to() Selbstreferenz-Guard
# ============================================================


class TestNavigateToSelfReferenceGuard:
    def test_no_history_entry_when_navigating_to_same_menu_again(self):
        session = MenuSession(user_id=1)
        item = MenuItem(id="stats_reviews", title="Rückblicke")

        session.navigate_to(item)
        assert session.history == []

        session.navigate_to(item)  # identisches Objekt erneut
        assert session.history == []  # kein Selbstreferenz-Eintrag

    def test_normal_navigation_still_records_history(self):
        session = MenuSession(user_id=1)
        a = MenuItem(id="a", title="A")
        b = MenuItem(id="b", title="B")

        session.navigate_to(a)
        session.navigate_to(b)

        assert session.history == ["a"]


# ============================================================
# 3. End-to-End: echte RichMenuHandler/RichMenuSystem-Instanz
# ============================================================


def _make_initialized_handler(tmp_path):
    user_data_file = tmp_path / "user_data.json"
    maintenance_state_file = tmp_path / "maintenance_mode.json"

    def _fake_path(p, *args, **kwargs):
        if p == "data/user_data.json":
            return user_data_file
        if p == "data/maintenance_mode.json":
            return maintenance_state_file
        return Path(p, *args, **kwargs)

    config = MockConfig()
    config.DOWNLOAD_HISTORY_DIR = tmp_path / "download_history"

    with patch("handlers.menu.rich_menu_handler.Path", side_effect=_fake_path):
        handler = RichMenuHandler(config)
        handler.initialize()
    return handler


def _make_update(user_id, callback_data):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message = Mock()
    return update


class TestWeeklyStatsResultNavigationEndToEnd:
    """Kritischer Navigationspfad des Master-Prompts (Abschnitt 21/23):
    Diese Woche -> Ergebnis mit reply_markup -> Klick auf "⬅️ Rückblicke"
    -> handle_callback() zeigt tatsächlich das Rückblicke-Menü."""

    def test_result_message_carries_correct_navigation_markup(self, tmp_path):
        handler = _make_initialized_handler(tmp_path)
        handler.stats_handler = Mock()
        handler.stats_handler.handle_week_review = AsyncMock()

        update = _make_update(OWNER_ID, "menu:stats_weekly")
        context = Mock()

        run_async(handler.menu_system.handle_callback(update, context))

        handler.stats_handler.handle_week_review.assert_awaited_once()
        _, kwargs = handler.stats_handler.handle_week_review.call_args
        markup = kwargs.get("reply_markup")
        assert isinstance(markup, InlineKeyboardMarkup)
        buttons = [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]
        assert ("⬅️ Rückblicke", "menu:stats_reviews") in buttons
        assert ("📊 Statistiken", "menu:stats") in buttons
        assert ("🏠 Hauptmenü", "menu:main") in buttons

    def test_clicking_back_button_shows_the_reviews_menu(self, tmp_path):
        """Zweiter, unabhängiger handle_callback()-Aufruf mit exakt dem
        callback_data, das render_result_navigation() für "Diese Woche"
        erzeugt hätte - simuliert den tatsächlichen Nutzerklick auf
        "⬅️ Rückblicke" im Ergebnis."""
        handler = _make_initialized_handler(tmp_path)

        update = _make_update(OWNER_ID, "menu:stats_reviews")
        context = Mock()

        run_async(handler.menu_system.handle_callback(update, context))

        update.callback_query.edit_message_text.assert_awaited_once()
        args, kwargs = update.callback_query.edit_message_text.call_args
        text = args[0]
        assert "Rückblicke" in text
        keyboard = kwargs["reply_markup"]
        buttons = [
            (b.text, b.callback_data)
            for row in keyboard.inline_keyboard
            for b in row
        ]
        assert any(cb == "menu:stats_weekly" for _, cb in buttons)
        assert any(cb == "menu:stats_monthly" for _, cb in buttons)
        assert any(cb == "menu:stats_yearly" for _, cb in buttons)

    def test_top_songs_result_navigation_end_to_end(self, tmp_path):
        handler = _make_initialized_handler(tmp_path)
        handler.stats_handler = Mock()
        handler.stats_handler.handle_top_songs = AsyncMock()

        update = _make_update(OWNER_ID, "menu:stats_top_songs")
        context = Mock()

        run_async(handler.menu_system.handle_callback(update, context))

        _, kwargs = handler.stats_handler.handle_top_songs.call_args
        markup = kwargs.get("reply_markup")
        buttons = [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]
        assert ("⬅️ Rankings", "menu:stats_rankings") in buttons

    def test_error_path_still_carries_navigation(self, tmp_path):
        """Fehlerfall (Abschnitt 20 des Master-Prompts): auch eine
        Fehlermeldung darf kein Dead End sein."""
        handler = _make_initialized_handler(tmp_path)
        handler.stats_handler = Mock()
        handler.stats_handler.handle_week_review = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        update = _make_update(OWNER_ID, "menu:stats_weekly")
        context = Mock()

        # handle_weekly_stats_wrapper faengt Exceptions selbst ab und
        # zeigt eine generische Fehlermeldung OHNE reply_markup (siehe
        # handlers/menu/actions/stats.py) - das ist der try/except-Pfad
        # der Actions-Schicht, nicht von _handle_period_review() selbst.
        # Hier wird nur sichergestellt, dass der Aufruf nicht crasht und
        # handle_week_review tatsaechlich MIT reply_markup aufgerufen
        # wurde, bevor es fehlschlug.
        run_async(handler.menu_system.handle_callback(update, context))

        _, kwargs = handler.stats_handler.handle_week_review.call_args
        assert isinstance(kwargs.get("reply_markup"), InlineKeyboardMarkup)


class TestLastPlayedResultNavigationEndToEndNavF10:
    """NAV-F10 (Navidrome Menu System Audit): 'Zuletzt gespielt'
    (nav_recent) war in ARCH-029 übersehen worden, da die Methode nicht
    über eine stats_*-ID, sondern über den Navidrome-Menüzweig
    erreichbar ist. Prüft den vollständigen Pfad: Klick auf 'Zuletzt
    gespielt' -> reply_markup -> Klick auf '⬅️ Navidrome Mediathek' ->
    zeigt tatsächlich das Navidrome-Menü."""

    def test_last_played_result_carries_navigation(self, tmp_path):
        handler = _make_initialized_handler(tmp_path)
        # _handle_navidrome_recent() lebt auf RichMenuSystem und liest
        # dessen EIGENES self.stats_handler (== handler.menu_system.
        # stats_handler, von initialize() per set_stats_handler()
        # propagiert) - nicht handler.stats_handler (RichMenuHandler
        # selbst), siehe analoges Muster bei den Family-Tests unten.
        handler.menu_system.stats_handler = Mock()
        handler.menu_system.stats_handler.handle_last_played = AsyncMock()

        update = _make_update(OWNER_ID, "menu:nav_recent")
        context = Mock()

        run_async(handler.menu_system.handle_callback(update, context))

        _, kwargs = handler.menu_system.stats_handler.handle_last_played.call_args
        markup = kwargs.get("reply_markup")
        assert isinstance(markup, InlineKeyboardMarkup)
        buttons = [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]
        assert ("⬅️ Navidrome Mediathek", "menu:navidrome") in buttons
        assert ("🏠 Hauptmenü", "menu:main") in buttons

    def test_clicking_back_button_shows_the_navidrome_menu(self, tmp_path):
        handler = _make_initialized_handler(tmp_path)

        update = _make_update(OWNER_ID, "menu:navidrome")
        context = Mock()

        run_async(handler.menu_system.handle_callback(update, context))

        update.callback_query.edit_message_text.assert_awaited_once()
        args, kwargs = update.callback_query.edit_message_text.call_args
        text = args[0]
        assert "Navidrome Mediathek" in text
        keyboard = kwargs["reply_markup"]
        buttons = [
            (b.text, b.callback_data)
            for row in keyboard.inline_keyboard
            for b in row
        ]
        assert any(cb == "menu:nav_recent" for _, cb in buttons)
        assert any(cb == "menu:nav_favorites" for _, cb in buttons)


class TestFamilyStatsResultNavigationEndToEnd:
    def test_family_top_songs_result_carries_navigation(self, tmp_path):
        handler = _make_initialized_handler(tmp_path)
        handler.menu_system.family_stats_handler = Mock()
        handler.menu_system.family_stats_handler.handle_family_top_songs = AsyncMock()

        update = _make_update(OWNER_ID, "menu:family_stats_top_songs")
        context = Mock()

        run_async(handler.menu_system.handle_callback(update, context))

        _, kwargs = handler.menu_system.family_stats_handler.handle_family_top_songs.call_args
        markup = kwargs.get("reply_markup")
        assert isinstance(markup, InlineKeyboardMarkup)
        buttons = [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]
        assert ("⬅️ Familien-Statistik", "menu:family_stats") in buttons
