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
            # ARCH-025: stats_monthly/_yearly/_top_songs/_top_artists/_timeline
            # brauchen seit dem Debt-Fix kein handler=-Attribut mehr (s.
            # definitions.py) - nur stats_library_overview bleibt live gebunden.
            "_handle_stats_library_overview",
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


def test_root_menu_has_no_static_welcome_description():
    """Telegram Start/Help/Menu UX Finalization v2: root_menu.description
    wurde entfernt, da /start bereits einen eigenen, personalisierten
    Begruessungstext liefert (header_text vor demselben Hauptmenue,
    siehe content/greeting.py) - ein zusaetzliches statisches
    "Willkommen..." hier waere eine Doppelinformation bei jedem
    /menu-Aufruf, nicht nur beim ersten Einstieg."""
    system = _FakeSystem()
    root = definitions.build_menu_tree(system)

    assert root.description is None


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


def test_build_menu_tree_dead_stats_items_have_no_handler_but_stay_actions():
    """ARCH-025-Debt-Fix: stats_monthly/_yearly/_top_songs/_top_artists/
    _timeline/_weekly hatten (bzw. haben für _weekly von Anfang an)
    kein von RichMenuHandler._register_stats_handlers() ohnehin unbedingt
    überschriebenes handler=. definitions.py setzt bewusst kein handler=
    - is_action=True bleibt erhalten (Registrierung erfolgt weiterhin per
    register_handler() zur Laufzeit). stats_library_overview bleibt die
    einzige direkt gebundene Ausnahme."""
    system = _FakeSystem()
    root = definitions.build_menu_tree(system)
    registry = {}
    definitions.populate_registry(registry, root)

    for dead_id in [
        "stats_weekly", "stats_monthly", "stats_yearly", "stats_top_songs",
        "stats_top_artists", "stats_timeline",
    ]:
        assert registry[dead_id].handler is None
        assert registry[dead_id].is_action is True

    assert registry["stats_library_overview"].handler is system._handle_stats_library_overview


class TestStatsMenuStructure:
    """Statistics Menu UX & Architecture Optimization: neue
    Navigations-Container 'Rückblicke'/'Rankings' unter 'stats' -
    reine Untermenüs ohne eigenen Handler (wie family_stats selbst),
    bestehende Callback-IDs bleiben erhalten, nur ihre Position im Baum
    und ihr sichtbarer Titel ändern sich."""

    def _registry(self):
        system = _FakeSystem()
        root = definitions.build_menu_tree(system)
        registry = {}
        definitions.populate_registry(registry, root)
        return registry

    def test_stats_top_level_children_are_reviews_rankings_timeline_library_family(self):
        registry = self._registry()
        assert [c.id for c in registry["stats"].children] == [
            "stats_reviews", "stats_rankings", "stats_timeline",
            "stats_library_overview", "family_stats",
        ]

    def test_stats_reviews_is_pure_navigation_container(self):
        registry = self._registry()
        reviews = registry["stats_reviews"]
        assert reviews.handler is None
        assert reviews.is_action is False
        assert [c.id for c in reviews.children] == [
            "stats_weekly", "stats_monthly", "stats_yearly",
        ]

    def test_stats_rankings_is_pure_navigation_container(self):
        registry = self._registry()
        rankings = registry["stats_rankings"]
        assert rankings.handler is None
        assert rankings.is_action is False
        assert [c.id for c in rankings.children] == [
            "stats_top_songs", "stats_top_artists",
        ]

    def test_button_titles_match_target_ux(self):
        registry = self._registry()
        assert registry["stats_weekly"].title == "Diese Woche"
        assert registry["stats_monthly"].title == "Dieser Monat"
        assert registry["stats_yearly"].title == "Dieses Jahr"
        assert registry["stats_top_songs"].title == "Top Songs"
        assert registry["stats_top_artists"].title == "Top Künstler"
        assert registry["stats_timeline"].title == "Music Timeline"
        assert registry["stats_library_overview"].title == "Meine Library"

    def test_no_duplicate_callback_ids_in_stats_subtree(self):
        registry = self._registry()
        stats_ids = [
            "stats", "stats_reviews", "stats_weekly", "stats_monthly",
            "stats_yearly", "stats_rankings", "stats_top_songs",
            "stats_top_artists", "stats_timeline", "stats_library_overview",
        ]
        callback_data_values = [registry[i].callback_data for i in stats_ids]
        assert len(callback_data_values) == len(set(callback_data_values))


class TestFamilyStatisticsUnchanged:
    """Master-Prompt: Familien-Statistik ist explizit OUT OF SCOPE dieser
    Phase - dieser Test pinnt die bestehende Struktur/Handler-Bindung
    als Regressionsschutz gegen versehentliche Änderungen."""

    def test_family_stats_is_still_a_child_of_stats(self):
        system = _FakeSystem()
        root = definitions.build_menu_tree(system)
        registry = {}
        definitions.populate_registry(registry, root)
        assert "family_stats" in [c.id for c in registry["stats"].children]

    def test_family_stats_children_and_handlers_unchanged(self):
        system = _FakeSystem()
        root = definitions.build_menu_tree(system)
        registry = {}
        definitions.populate_registry(registry, root)

        expected_handlers = {
            "family_stats_top_songs": system._handle_family_stats_top_songs,
            "family_stats_top_artists": system._handle_family_stats_top_artists,
            "family_stats_member": system._handle_family_stats_member,
            "family_stats_champion": system._handle_family_stats_champion,
            "family_stats_listening_times": system._handle_family_stats_listening_times,
            "family_stats_monthly_trend": system._handle_family_stats_monthly_trend,
        }
        family_stats = registry["family_stats"]
        assert [c.id for c in family_stats.children] == list(expected_handlers.keys())
        for child_id, expected_handler in expected_handlers.items():
            assert registry[child_id].handler is expected_handler
            assert registry[child_id].is_action is True

    def test_family_stats_title_and_emoji_unchanged(self):
        system = _FakeSystem()
        root = definitions.build_menu_tree(system)
        registry = {}
        definitions.populate_registry(registry, root)
        family_stats = registry["family_stats"]
        assert family_stats.title == "Familien-Statistik"
        assert family_stats.emoji == "👨‍👩‍👧‍👦"


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
