"""
ARCH-021/P-4: Characterization-/Unit-Tests fuer die Session-Verwaltung
von RichMenuSystem (handlers/menu/), nach der Extraktion nach
handlers/menu/session.py::SessionManager geschrieben.

Zweck:
  1. Belegt die zentrale Kompatibilitaets-Annahme, auf der die gesamte
     Move-Extraktion beruht: menu_system.sessions ist DASSELBE Dict-
     Objekt wie menu_system.session_manager.sessions (keine Kopie) -
     nur dadurch funktionieren bestehende direkte Zugriffe wie
     menu_system.sessions[user_id]/user_id in menu_system.sessions/
     del self.sessions[user_id] (siehe _handle_close()) unveraendert
     weiter.
  2. Isolierter Unit-Test fuer SessionManager direkt, ohne RichMenuSystem
     zu konstruieren - dokumentiert dessen Ist-Verhalten unabhaengig von
     RichMenuSystem als Aufrufer.

Bewusst NICHT Gegenstand dieser Tests (siehe ARCH-021/P-4-Audit,
Abschnitt 2.3/2.4/3.4 - unveraendert gebliebener/toter Zustand):
  - max_sessions wird weiterhin nirgends durchgesetzt.
  - MenuSession.state/.data/.message_id/created_at bleiben unberuehrt.
  - RichMenuHandler.user_states ist ein eigenstaendiger, hier nicht
    betroffener State-Mechanismus.
"""

from datetime import datetime, timedelta

import pytest

from handlers.menu.models import MenuSession
from handlers.menu.rich_menu_system import RichMenuSystem
from handlers.menu.session import SessionManager


class MockConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [12345, 67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100


class _FakeLogger:
    """Minimaler Logger-Stellvertreter - SessionManager ruft nur
    debug()/info() auf, siehe Modul-Docstring von session.py."""

    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass


class TestSessionsDictIdentity:
    """Zentrale Kompatibilitaets-Annahme der P-4-Extraktion: die
    sessions-Property auf RichMenuSystem liefert dasselbe Dict-Objekt
    wie session_manager.sessions - keine Kopie."""

    def test_sessions_property_is_same_object_as_session_manager_dict(self):
        system = RichMenuSystem(MockConfig())
        assert system.sessions is system.session_manager.sessions

    def test_mutation_via_property_is_visible_on_session_manager(self):
        system = RichMenuSystem(MockConfig())
        system.get_session(42)

        assert 42 in system.session_manager.sessions

        del system.sessions[42]

        assert 42 not in system.session_manager.sessions

    def test_mutation_via_session_manager_is_visible_via_property(self):
        system = RichMenuSystem(MockConfig())
        system.session_manager.get_session(99)

        assert 99 in system.sessions


class TestSessionManagerIsolatedUnit:
    """Ist-Verhalten von SessionManager, konstruiert ohne RichMenuSystem -
    identisch zum vormaligen RichMenuSystem.get_session()/
    cleanup_expired_sessions()-Verhalten (siehe ARCH-021/P-4-Audit
    Abschnitt 2.1/2.2)."""

    def _make_manager(self, session_timeout=300, max_sessions=100):
        return SessionManager(
            session_timeout=session_timeout,
            max_sessions=max_sessions,
            logger=_FakeLogger(),
        )

    def test_creates_new_session_for_unknown_user(self):
        manager = self._make_manager()
        session = manager.get_session(42)
        assert session.user_id == 42
        assert 42 in manager.sessions

    def test_returns_same_session_on_repeated_calls(self):
        manager = self._make_manager()
        session1 = manager.get_session(42)
        session2 = manager.get_session(42)
        assert session1 is session2

    def test_get_session_updates_activity_timestamp(self):
        manager = self._make_manager()
        session = manager.get_session(42)
        session.last_activity = datetime.now() - timedelta(seconds=100)
        manager.get_session(42)
        assert session.is_expired(timeout=300) is False

    def test_expired_session_is_replaced_with_fresh_one(self):
        manager = self._make_manager()
        session1 = manager.get_session(42)
        session1.current_menu = None  # Ausgangszustand explizit machen
        session1.last_activity = datetime.now() - timedelta(seconds=999)

        session2 = manager.get_session(42)

        assert session2 is not session1
        assert session2.current_menu is None

    def test_removes_only_expired_sessions(self):
        manager = self._make_manager()
        manager.get_session(1)
        expired = manager.get_session(2)
        expired.last_activity = datetime.now() - timedelta(seconds=999)

        removed_count = manager.cleanup_expired_sessions()

        assert removed_count == 1
        assert 1 in manager.sessions
        assert 2 not in manager.sessions

    def test_cleanup_return_value_matches_removed_count(self):
        manager = self._make_manager()
        for i in range(5):
            manager.get_session(i)
        for i in range(3):
            manager.sessions[i].last_activity = datetime.now() - timedelta(
                seconds=400
            )

        cleaned = manager.cleanup_expired_sessions()

        assert cleaned == 3
        assert len(manager.sessions) == 2

    def test_max_sessions_is_stored_but_not_enforced(self):
        """Charakterisiert den bestehenden, unveraenderten Zustand:
        max_sessions wird gehalten, aber nirgends geprueft - siehe
        ARCH-021/P-4-Audit Abschnitt 2.3. Kein Fix in diesem Schritt."""
        manager = self._make_manager(max_sessions=1)
        manager.get_session(1)
        manager.get_session(2)
        manager.get_session(3)

        assert len(manager.sessions) == 3
        assert manager.max_sessions == 1


class TestSessionConfigWiring:
    """Belegt, dass RichMenuSystem die Session-Konfiguration weiterhin
    korrekt aus der Config an SessionManager durchreicht (ARCH-021/P-4:
    Config-Auswertung ist unveraendert, nur der Ort ist neu)."""

    def test_session_timeout_from_config_reaches_session_manager(self):
        system = RichMenuSystem(MockConfig())
        assert system.session_manager.session_timeout == MockConfig.SESSION_TIMEOUT

    def test_max_sessions_from_config_reaches_session_manager(self):
        system = RichMenuSystem(MockConfig())
        assert (
            system.session_manager.max_sessions
            == MockConfig.MAX_CONCURRENT_SESSIONS
        )

    def test_missing_config_attributes_fall_back_to_defaults(self):
        class _BareConfig:
            OWNER_USER_ID = 1

        system = RichMenuSystem(_BareConfig())
        assert system.session_manager.session_timeout == 300
        assert system.session_manager.max_sessions == 100
