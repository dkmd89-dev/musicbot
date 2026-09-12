# tests/test_menu_definitions.py
# -*- coding: utf-8 -*-
"""
Characterization/Regressionstests für handlers/menu/definitions.py
(ARCH-024/P-3, Definitions Extraction) - 1:1 verschoben aus
RichMenuSystem.initialize_menu_structure()/_build_registry().

Deckt Struktur-Invarianten ab, die vorher nur implizit über
tests/test_rich_menu_system.py/test_suite.py mitgeprüft wurden: Anzahl
der Top-Level-Menüs, Registry-Vollständigkeit, korrekte Handler-Bindung
an die (jetzt in ARCH-024/P-2 extrahierten) dünnen Delegatoren.
"""

from unittest.mock import Mock

from handlers.menu import definitions
from handlers.menu.models import AccessLevel, MenuItem


class _FakeSystem:
    """Minimaler Stellvertreter für RichMenuSystem - build_menu_tree()
    liest ausschließlich die _handle_*-Attribute (bound methods), siehe
    definitions.py-Docstring."""

    def __init__(self):
        for name in [
            "_handle_download_menu", "_handle_download_single", "_handle_download_playlist",
            "_handle_stats_monthly", "_handle_stats_yearly", "_handle_stats_top_songs",
            "_handle_stats_top_artists", "_handle_stats_timeline", "_handle_stats_library_overview",
            "_handle_family_stats_top_songs", "_handle_family_stats_top_artists",
            "_handle_family_stats_member", "_handle_family_stats_champion",
            "_handle_family_stats_listening_times", "_handle_family_stats_monthly_trend",
            "_handle_family_chat_send", "_handle_family_chat_recent", "_handle_family_chat_notifications",
            "_handle_family_challenge_today", "_handle_family_challenge_answer",
            "_handle_family_challenge_leaderboard",
            "_handle_status_menu", "_handle_backup_main", "_handle_backup_bot_confirm",
            "_handle_backup_lib_confirm", "_handle_backup_list_bot", "_handle_backup_list_lib",
            "_handle_restart_show", "_handle_maintenance_show", "_handle_reprocessing_show",
            "_handle_doctor_scan", "_handle_review_start", "_handle_repair_start",
            "_handle_navidrome_browse_artists", "_handle_navidrome_browse_albums",
            "_handle_navidrome_browse_genres", "_handle_navidrome_browse_playlists",
            "_handle_navidrome_search_all", "_handle_navidrome_search_artists",
            "_handle_navidrome_search_albums", "_handle_navidrome_search_songs",
            "_handle_navidrome_my_playlists", "_handle_navidrome_favorites",
            "_handle_navidrome_recent",
        ]:
            setattr(self, name, Mock(name=name))


def test_build_menu_tree_root_has_seven_top_level_children():
    system = _FakeSystem()
    root = definitions.build_menu_tree(system)
    assert [c.id for c in root.children] == [
        "download", "stats", "family_chat", "family_challenge", "admin", "tests", "navidrome"
    ]


def test_build_menu_tree_admin_groups_present():
    system = _FakeSystem()
    root = definitions.build_menu_tree(system)
    registry = {}
    definitions.populate_registry(registry, root)
    admin = registry["admin"]
    assert [c.id for c in admin.children] == [
        "admin_group_library", "admin_group_operations", "admin_group_diagnostics",
        "admin_duplicates", "admin_users",
    ]


def test_build_menu_tree_download_handler_bound_to_system_method():
    system = _FakeSystem()
    root = definitions.build_menu_tree(system)
    registry = {}
    definitions.populate_registry(registry, root)
    assert registry["download"].handler is system._handle_download_menu


def test_build_menu_tree_admin_menu_has_admin_access_level():
    system = _FakeSystem()
    root = definitions.build_menu_tree(system)
    registry = {}
    definitions.populate_registry(registry, root)
    assert registry["admin"].access_level == AccessLevel.ADMIN
    assert registry["navidrome"].access_level == AccessLevel.USER


def test_populate_registry_mutates_in_place_and_recurses():
    parent = MenuItem(id="p", title="P")
    child = MenuItem(id="c", title="C")
    parent.add_child(child)
    registry = {}
    result = definitions.populate_registry(registry, parent)
    assert result is None  # mutiert in place, kein Rückgabewert
    assert set(registry.keys()) == {"p", "c"}
    assert registry["c"] is child


def test_admin_navidrome_not_in_static_tree():
    """admin_navidrome wird ausschließlich dynamisch von
    RichMenuHandler._register_system_handlers() ergänzt (siehe
    docs/MusicBot_ARCH-024_Menu_File_Decomposition.md Abschnitt 1.6) -
    build_menu_tree() allein darf es nicht enthalten."""
    system = _FakeSystem()
    root = definitions.build_menu_tree(system)
    registry = {}
    definitions.populate_registry(registry, root)
    assert "admin_navidrome" not in registry
