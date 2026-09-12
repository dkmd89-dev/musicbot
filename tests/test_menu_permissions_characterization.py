"""
ARCH-021/P-3: Characterization-Tests fuer die Permission-Logik von
RichMenuHandler und RichMenuSystem (handlers/menu/), VOR der
Vereinheitlichung in handlers/menu/permissions.py geschrieben.

Zweck: belegen, dass RichMenuHandler._is_admin() und
RichMenuSystem._is_admin_check() fuer jede in der Praxis vorkommende
Config (d.h. mit gesetztem OWNER_USER_ID) bereits identisches Verhalten
zeigen - das ist die Voraussetzung dafuer, beide durch eine gemeinsame
Funktion (permissions.is_admin_or_owner()) zu ersetzen, ohne Verhalten
zu aendern.

Zusaetzlich dokumentiert (nicht gefixt, siehe ARCH-021/P-1-Bericht
Abschnitt 10 und die bereits bestehenden Befunde in
tests/test_rich_menu_system.py::TestGetUserAccessLevel /
tests/test_rich_menu_handler.py-Modul-Docstring "TEST-011"):

- Vor der Vereinheitlichung unterscheiden sich _is_admin() (direkter
  Attributzugriff self.config.OWNER_USER_ID, wirft AttributeError bei
  fehlendem Attribut) und _is_admin_check() (getattr(..., None), faellt
  bei fehlendem Attribut auf False/ADMIN_USER_IDS-Check zurueck) in genau
  diesem einen, in der Produktion nie erreichbaren Randfall (die echte
  config.Config definiert OWNER_USER_ID immer). Die Vereinheitlichung
  uebernimmt die defensivere getattr-Variante - siehe
  TestIsAdminOrOwnerEdgeCase unten.
- _get_user_role() (RichMenuHandler, String-Rollen) und
  _get_user_access_level() (RichMenuSystem, AccessLevel-Enum) werden in
  P-3 bewusst NICHT zusammengefuehrt: sie haben unterschiedliche
  Rueckgabetypen, unterschiedliche Konsumenten (Begruessungstext/
  Feature-Liste vs. MenuItem-Rendering) und _get_user_role() haengt an
  RichMenuHandler._get_user_info()/_load_user_data() (JSON-Datei-
  Fallback, State-Belang statt reiner Permission-Logik). Nur
  _get_user_access_level() wandert nach permissions.py (reine
  Funktion von user_id/config/user_mgmt_handler, kein Datei-I/O).
"""

from unittest.mock import Mock

import pytest

from handlers.menu.models import AccessLevel
from handlers.menu.rich_menu_handler import RichMenuHandler
from handlers.menu.rich_menu_system import RichMenuSystem


class MockConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [12345, 67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100


def _make_bare_handler(config) -> RichMenuHandler:
    """RichMenuHandler.__init__() hat einen schweren Konstruktor (baut
    ActiveDownloadRegistry/DownloadHistoryStore/MaintenanceModeStore mit
    echten Dateipfaden) - object.__new__() umgeht ihn bewusst, da
    _is_admin() ausschliesslich self.config liest. Etabliertes Muster,
    siehe z.B. tests/test_download_handler_*.py."""
    handler = object.__new__(RichMenuHandler)
    handler.config = config
    return handler


@pytest.mark.parametrize("user_id", [12345, 67890, 99999, -1, 0])
class TestIsAdminEquivalence:
    """Belegt: RichMenuHandler._is_admin() und
    RichMenuSystem._is_admin_check() liefern fuer jede realistische
    Config (OWNER_USER_ID gesetzt) identische Ergebnisse - Owner-ID,
    konfigurierter Admin, unbekannter User, sowie zwei Randwerte."""

    def test_is_admin_and_is_admin_check_agree(self, user_id):
        handler = _make_bare_handler(MockConfig())
        system = RichMenuSystem(MockConfig())

        assert handler._is_admin(user_id) == system._is_admin_check(user_id)


class TestIsAdminCurrentBehavior:
    def test_owner_is_admin(self):
        handler = _make_bare_handler(MockConfig())
        assert handler._is_admin(MockConfig.OWNER_USER_ID) is True

    def test_configured_admin_is_admin(self):
        handler = _make_bare_handler(MockConfig())
        assert handler._is_admin(67890) is True

    def test_unknown_user_is_not_admin(self):
        handler = _make_bare_handler(MockConfig())
        assert handler._is_admin(99999) is False


class TestIsAdminCheckCurrentBehavior:
    def test_owner_is_admin(self):
        system = RichMenuSystem(MockConfig())
        assert system._is_admin_check(MockConfig.OWNER_USER_ID) is True

    def test_configured_admin_is_admin(self):
        system = RichMenuSystem(MockConfig())
        assert system._is_admin_check(67890) is True

    def test_unknown_user_is_not_admin(self):
        system = RichMenuSystem(MockConfig())
        assert system._is_admin_check(99999) is False


class TestIsAdminOrOwnerEdgeCase:
    """Dokumentiert die EINZIGE bewusste Verhaltensaenderung von
    ARCH-021/P-3: vor der Vereinheitlichung unterschieden sich
    RichMenuHandler._is_admin() (direkter Attributzugriff
    self.config.OWNER_USER_ID, wirft AttributeError bei fehlendem
    Attribut) und RichMenuSystem._is_admin_check() (getattr(..., None),
    faellt defensiv auf False/ADMIN_USER_IDS zurueck) fuer eine Config
    OHNE OWNER_USER_ID-Attribut (die echte config.Config definiert es
    immer - dieser Fall ist in Produktion nie erreichbar).

    Seit der Vereinheitlichung auf permissions.is_admin_or_owner()
    (getattr-Variante) zeigen BEIDE Methoden das defensive Verhalten:
    _is_admin() wirft in diesem Randfall nicht mehr AttributeError,
    sondern liefert korrekt False/prueft ADMIN_USER_IDS - identisch zu
    _is_admin_check()'s bisherigem Verhalten. Betrifft ausschliesslich
    Configs ohne OWNER_USER_ID, die in der Produktion nicht vorkommen."""

    class _ConfigWithoutOwnerId:
        ADMIN_USER_IDS = [67890]

    def test_is_admin_no_longer_raises_without_owner_user_id_attribute(self):
        handler = _make_bare_handler(self._ConfigWithoutOwnerId())
        assert handler._is_admin(1) is False
        assert handler._is_admin(67890) is True

    def test_is_admin_check_does_not_raise_without_owner_user_id_attribute(self):
        system = RichMenuSystem(self._ConfigWithoutOwnerId())
        assert system._is_admin_check(1) is False
        assert system._is_admin_check(67890) is True

    def test_is_admin_and_is_admin_check_now_agree_on_this_edge_case_too(self):
        handler = _make_bare_handler(self._ConfigWithoutOwnerId())
        system = RichMenuSystem(self._ConfigWithoutOwnerId())
        for user_id in (1, 67890):
            assert handler._is_admin(user_id) == system._is_admin_check(user_id)


class TestGetUserAccessLevelCurrentBehavior:
    """Ist-Zustand von RichMenuSystem._get_user_access_level() - Vorlage
    fuer die unveraenderte Verschiebung nach permissions.py. Deckt sich
    mit tests/test_rich_menu_system.py::TestGetUserAccessLevel (dort
    ueber die Klassenmethode getestet, hier zusaetzlich als Beleg fuer
    die 1:1-Aequivalenz zur verschobenen Funktion nach P-3)."""

    def test_owner_from_config_gets_owner_level(self):
        system = RichMenuSystem(MockConfig())
        assert (
            system._get_user_access_level(MockConfig.OWNER_USER_ID)
            == AccessLevel.OWNER
        )

    def test_admin_from_config_gets_admin_level(self):
        system = RichMenuSystem(MockConfig())
        assert system._get_user_access_level(67890) == AccessLevel.ADMIN

    def test_unknown_user_gets_user_level(self):
        system = RichMenuSystem(MockConfig())
        assert system._get_user_access_level(99999) == AccessLevel.USER

    def test_role_from_user_mgmt_cache_is_used_when_available(self):
        system = RichMenuSystem(MockConfig())
        fake_user_mgmt = Mock()
        fake_user_mgmt.user_data_cache = {"55555": {"role": "moderator"}}
        system.set_user_mgmt_handler(fake_user_mgmt)

        assert system._get_user_access_level(55555) == AccessLevel.MODERATOR

    def test_data_role_owner_is_not_recognized_as_owner_level(self):
        """Bestehende, bewusst nicht gefixte Inkonsistenz (siehe
        tests/test_rich_menu_system.py::TestGetUserAccessLevel::
        test_data_role_owner_is_not_recognized_as_owner_level) - bleibt
        nach der Verschiebung nach permissions.py identisch bestehen."""
        system = RichMenuSystem(MockConfig())
        fake_user_mgmt = Mock()
        fake_user_mgmt.user_data_cache = {"55555": {"role": "owner"}}
        system.set_user_mgmt_handler(fake_user_mgmt)

        assert system._get_user_access_level(55555) == AccessLevel.USER
