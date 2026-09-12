# tests/test_menu_router_characterization.py
# -*- coding: utf-8 -*-
"""
ARCH-023/P-3 Phase 1: Characterization-Tests fuer die im ARCH-023/P-2-
Bericht identifizierten, bisher ungetesteten oder nur unvollstaendig
getesteten Permission-Pfade rund um RichMenuSystem.handle_callback()
und die "menu:"-Fallback-Items - VOR jeder Aenderung an der Router-/
Permission-Logik geschrieben.

Zweck: das aktuelle Ist-Verhalten als Baseline einfrieren, damit die
anschliessende Haertung (Menu-Fallback-Gate, doctor/review/repair-
Konsolidierung) nachweislich verhaltensgleich bleibt.

Testgruppen (siehe docs-Bericht ARCH-023/P-2):
  Test 1  admin_users   - Ablehnungsverhalten (bisher 0 Tests)
  Test 2  admin_logs    - Ablehnungsverhalten (bisher 0 Tests)
  Test 3  admin_navidrome - echte, vollstaendig initialisierte Registry
                            + End-to-End ueber handle_callback()
  Test 4  show_alert-Diskrepanz RichMenuHandler-Items vs. TestMenuHandler-
          Items bewusst eingefroren
  Test 5  erradmin: - Owner-/ADMIN_USER_IDS-Verhalten dokumentiert, NICHT
          korrigiert
  Test 6  doctor:/review:/repair: - Aequivalenz der Inline-Pruefung zu
          RichMenuSystem._is_admin_check()

Keine Produktionslogik in dieser Datei geaendert - reine Charakterisierung.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.menu.rich_menu_handler import RichMenuHandler
from handlers.menu.rich_menu_system import RichMenuSystem
from handlers.menu.models import AccessLevel
from handlers.enhanced_error_handler import ErrorHandlerAdminInterface


class MockConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [12345, 67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100


OWNER_ID = 12345
ADMIN_ID = 67890
OTHER_ID = 999


def _make_bare_handler(config) -> RichMenuHandler:
    """RichMenuHandler.__init__() hat einen schweren Konstruktor - fuer
    die hier getesteten Ablehnungspfade wird ausschliesslich self.config
    (ueber _is_admin()) gelesen, object.__new__() umgeht die restliche
    Konstruktion bewusst. Etabliertes Muster, siehe
    tests/test_menu_permissions_characterization.py::_make_bare_handler."""
    handler = object.__new__(RichMenuHandler)
    handler.config = config
    handler.logger = Mock()
    return handler


def _make_update(user_id):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    context = Mock()
    context.bot = AsyncMock()
    return context


def run_async(coro):
    import asyncio

    return asyncio.run(coro)


# ============================================================
# Test 1 - admin_users
# ============================================================


class TestAdminUsersRejection:
    """Bisher (repoweit verifiziert im ARCH-023/P-2-Audit) existierte
    KEIN Test, der RichMenuHandler._handle_user_management_wrapper()
    ueberhaupt aufruft."""

    def test_non_admin_direct_call_is_rejected_with_exact_message(self):
        handler = _make_bare_handler(MockConfig())
        update = _make_update(OTHER_ID)
        context = Mock()

        run_async(handler._handle_user_management_wrapper(update, context))

        update.callback_query.answer.assert_awaited_once()
        args, kwargs = update.callback_query.answer.call_args
        assert args[0] == "⛔ Keine Berechtigung"
        # Charakterisiert: KEIN show_alert=True (Unterschied zu
        # TestMenuHandler-Items, siehe Test 4 unten).
        assert "show_alert" not in kwargs

    def test_non_admin_never_reaches_user_management_handler(self):
        handler = _make_bare_handler(MockConfig())
        handler.user_mgmt_handler = Mock()
        handler.user_mgmt_handler.show_user_management_menu = AsyncMock()
        update = _make_update(OTHER_ID)
        context = Mock()

        run_async(handler._handle_user_management_wrapper(update, context))

        handler.user_mgmt_handler.show_user_management_menu.assert_not_awaited()

    def test_admin_is_not_rejected_and_reaches_handler(self):
        handler = _make_bare_handler(MockConfig())
        handler.user_mgmt_handler = Mock()
        handler.user_mgmt_handler.show_user_management_menu = AsyncMock()
        update = _make_update(ADMIN_ID)
        context = Mock()

        run_async(handler._handle_user_management_wrapper(update, context))

        handler.user_mgmt_handler.show_user_management_menu.assert_awaited_once()

    def test_non_admin_is_rejected_via_real_dispatch_path(self):
        """Produktiver Dispatch-Weg: echte RichMenuSystem-Registry,
        Handler ueber register_handler() verdrahtet (wie RichMenuHandler
        das produktiv tut), Callback laeuft ueber handle_callback().

        ARCH-023/P-3 Phase 2 (Menu-Fallback-Gate): die zentrale
        Router-Pruefung (show_alert=True, siehe handle_callback())
        greift jetzt VOR dem individuellen Handler - dessen eigener,
        schwaecherer Check (kein show_alert, siehe
        test_non_admin_direct_call_is_rejected_with_exact_message oben)
        wird auf diesem Weg nicht mehr erreicht. Bewusste, dokumentierte
        UX-Aenderung (siehe ARCH-023/P-3-Abschlussbericht Abschnitt 8),
        keine stillschweigende Entscheidung."""
        handler = _make_bare_handler(MockConfig())
        system = RichMenuSystem(MockConfig())
        system.initialize_menu_structure()
        system.register_handler(
            "admin_users", handler._handle_user_management_wrapper
        )

        update = _make_update(OTHER_ID)
        update.callback_query.data = "menu:admin_users"
        context = Mock()

        run_async(system.handle_callback(update, context))

        args, kwargs = update.callback_query.answer.call_args
        assert args[0] == "⛔ Keine Berechtigung"
        assert kwargs.get("show_alert") is True


# ============================================================
# Test 2 - admin_logs
# ============================================================


class TestAdminLogsRejection:
    """Bisher (repoweit verifiziert) ebenfalls KEIN Test, der
    RichMenuHandler._handle_view_logs() ueberhaupt aufruft."""

    def test_non_admin_direct_call_is_rejected_with_exact_message(self):
        handler = _make_bare_handler(MockConfig())
        update = _make_update(OTHER_ID)
        context = Mock()

        run_async(handler._handle_view_logs(update, context))

        update.callback_query.answer.assert_awaited_once()
        args, kwargs = update.callback_query.answer.call_args
        assert args[0] == "⛔ Keine Berechtigung"
        assert "show_alert" not in kwargs

    def test_non_admin_never_reads_log_file(self, tmp_path):
        log_file = tmp_path / "bot.log"
        log_file.write_text("sensitive log content\n")
        config = MockConfig()
        config.LOG_FILE = str(log_file)
        handler = _make_bare_handler(config)
        update = _make_update(OTHER_ID)
        context = Mock()

        run_async(handler._handle_view_logs(update, context))

        # Ablehnung erfolgt VOR jedem Dateizugriff - edit_message_text
        # (das die Log-Zeilen ausgeben wuerde) wird nie aufgerufen.
        update.callback_query.edit_message_text.assert_not_awaited()

    def test_non_admin_is_rejected_via_real_dispatch_path(self):
        """ARCH-023/P-3 Phase 2 (Menu-Fallback-Gate): symmetrisch zu
        admin_users/admin_navidrome - die zentrale Router-Pruefung
        (show_alert=True) greift jetzt VOR _handle_view_logs()'s
        eigenem, schwaecherem Check."""
        handler = _make_bare_handler(MockConfig())
        system = RichMenuSystem(MockConfig())
        system.initialize_menu_structure()
        system.register_handler("admin_logs", handler._handle_view_logs)

        update = _make_update(OTHER_ID)
        update.callback_query.data = "menu:admin_logs"
        context = Mock()

        run_async(system.handle_callback(update, context))

        args, kwargs = update.callback_query.answer.call_args
        assert args[0] == "⛔ Keine Berechtigung"
        assert kwargs.get("show_alert") is True

    def test_admin_is_not_rejected_via_real_dispatch_path(self):
        handler = _make_bare_handler(MockConfig())
        handler.config.LOG_FILE = "logs/does_not_matter_for_this_test.log"
        system = RichMenuSystem(MockConfig())
        system.initialize_menu_structure()
        system.register_handler("admin_logs", handler._handle_view_logs)

        update = _make_update(ADMIN_ID)
        update.callback_query.data = "menu:admin_logs"
        context = Mock()

        run_async(system.handle_callback(update, context))

        # Admin wird NICHT mit der Berechtigungsmeldung abgewiesen und
        # erreicht edit_message_text() (Log-Ausgabe bzw. "Log-Datei
        # nicht gefunden" - beweist, dass die Permission-Pruefung
        # passiert wurde). Charakterisiert nebenbei einen bestehenden
        # Doppel-Aufruf: der generische "menu:"-Fallback in
        # handle_callback() ruft bereits VOR dem Handler-Aufruf
        # query.answer() auf, _handle_view_logs() ruft es auf dem
        # Erfolgspfad ein zweites Mal (ohne Text) - beide Male ohne
        # Ablehnungstext, daher fuer diese Charakterisierung unschaedlich.
        assert update.callback_query.answer.await_count == 2
        for call in update.callback_query.answer.await_args_list:
            assert call.args != ("⛔ Keine Berechtigung",)
        update.callback_query.edit_message_text.assert_awaited_once()


# ============================================================
# Test 3 - admin_navidrome (besonders sorgfaeltig, siehe P-2-Bericht)
# ============================================================


class TestAdminNavidromeRealRegistry:
    """Nutzt eine ECHTE, vollstaendig initialisierte RichMenuHandler-
    Instanz (RichMenuHandler(config).initialize()) - nicht die leichte
    object.__new__()-Variante -, um die reale Produktions-Registry zu
    befragen. Mehrere Sub-Handler-Konstruktionen schlagen mit dieser
    minimalen MockConfig erwartungsgemaess fehl (z.B. BackupHandler,
    NavidromeMenuHandler) - das ist unschaedlich fuer diesen Test, da
    initialize() jeden Konstruktionsschritt einzeln try/except behandelt
    und die fuer admin_navidrome relevanten Schritte
    (initialize_menu_structure() + _register_system_handlers()) am Ende
    unabhaengig davon durchlaufen."""

    @staticmethod
    def _make_initialized_handler(tmp_path):
        from pathlib import Path

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

    def test_admin_navidrome_exists_in_the_real_registry(self, tmp_path):
        handler = self._make_initialized_handler(tmp_path)
        assert "admin_navidrome" in handler.menu_system.menu_registry

    def test_admin_navidrome_menu_item_shape(self, tmp_path):
        """Haelt Punkt fuer Punkt fest, was die ECHTE Produktions-Registry
        fuer admin_navidrome traegt - Grundlage fuer die TGPERM-001-
        Fixture-Luecken-Entscheidung in Phase 2."""
        handler = self._make_initialized_handler(tmp_path)
        item = handler.menu_system.menu_registry["admin_navidrome"]

        assert item.access_level == AccessLevel.ADMIN
        # ARCH-023/P-4 Phase 1: die in P-2/P-3 dokumentierte
        # Modellierungsinkonsistenz (is_action=False trotz gesetztem
        # handler=) wurde korrigiert - admin_navidrome traegt jetzt wie
        # jede andere echte Aktion im Menuebaum is_action=True.
        assert item.is_action is True
        assert item.callback_data == "menu:admin_navidrome"
        assert item.handler is not None
        assert item.handler.__func__ is RichMenuHandler._handle_navidrome_scan

    def test_non_admin_is_rejected_end_to_end_via_handle_callback(self, tmp_path):
        """End-to-End ueber den echten Dispatch-Weg: handle_callback()
        auf der echten, initialisierten RichMenuSystem-Instanz, mit dem
        echten callback_data-String, den ein Telegram-Client fuer diesen
        Button tatsaechlich senden wuerde.

        ARCH-023/P-3 Phase 2 (Menu-Fallback-Gate): wie bei admin_users
        greift jetzt die zentrale Router-Pruefung (show_alert=True) VOR
        _handle_navidrome_scan()'s eigenem, schwaecherem Check - bewusste,
        dokumentierte UX-Aenderung."""
        handler = self._make_initialized_handler(tmp_path)
        update = _make_update(OTHER_ID)
        update.callback_query.data = "menu:admin_navidrome"
        context = Mock()

        with patch(
            "handlers.menu.rich_menu_handler.NavidromeScanTrigger.run_scan",
            new=AsyncMock(),
        ) as mock_scan:
            run_async(handler.menu_system.handle_callback(update, context))

        mock_scan.assert_not_awaited()
        args, kwargs = update.callback_query.answer.call_args
        assert args[0] == "⛔ Keine Berechtigung"
        assert kwargs.get("show_alert") is True

    def test_admin_reaches_the_real_handler_end_to_end(self, tmp_path):
        handler = self._make_initialized_handler(tmp_path)
        update = _make_update(ADMIN_ID)
        update.callback_query.data = "menu:admin_navidrome"
        context = Mock()

        with patch(
            "handlers.menu.rich_menu_handler.NavidromeScanTrigger.run_scan",
            new=AsyncMock(),
        ) as mock_scan:
            run_async(handler.menu_system.handle_callback(update, context))

        mock_scan.assert_awaited_once()

    def test_tgperm001_fixture_does_not_contain_admin_navidrome(self):
        """Dokumentiert exakt die im P-2-Bericht beschriebene Luecke:
        die von TestPrivilegedMenuItemsAreGatedTGPERM001 verwendete
        Fixture (nur initialize_menu_structure(), keine volle
        RichMenuHandler.initialize()-Kette) enthaelt admin_navidrome gar
        nicht - der Eintrag in _KNOWN_INTERNALLY_GATED_MENU_IDS wird von
        dieser Fixture also nie tatsaechlich prueft."""
        system = RichMenuSystem(MockConfig())
        system.initialize_menu_structure()

        assert "admin_navidrome" not in system.menu_registry


# ============================================================
# Test 4 - show_alert-Charakterisierung
# ============================================================


class TestShowAlertDiscrepancyIsFrozen:
    """Haelt die im P-2-Bericht gefundene UX-Diskrepanz explizit fest,
    RichMenuHandler-Items (admin_users/admin_logs/admin_navidrome) vs.
    TestMenuHandler-Items (test_unit/test_integration/test_performance) -
    damit eine spaetere Vereinheitlichung (Phase 2 dieses P-3-Schritts)
    das bewusst und nicht versehentlich entscheidet."""

    @pytest.mark.parametrize(
        "call",
        [
            lambda h, u, c: h._handle_user_management_wrapper(u, c),
            lambda h, u, c: h._handle_view_logs(u, c),
        ],
    )
    def test_richmenuhandler_items_reject_without_show_alert(self, call):
        handler = _make_bare_handler(MockConfig())
        update = _make_update(OTHER_ID)
        context = Mock()

        run_async(call(handler, update, context))

        _, kwargs = update.callback_query.answer.call_args
        assert kwargs.get("show_alert") is not True

    def test_testmenuhandler_items_reject_with_show_alert_true(self):
        """Gegenstueck zu oben, ueber TestMenuHandler._execute_test_run()
        (dieselbe Methode, die bereits von
        tests/test_test_menu_handler.py::
        TestExecuteTestRunAdminPermissionTGPERM001 abgedeckt wird - hier
        nur zur direkten Gegenueberstellung neben Test 1/2/3
        wiederholt, keine neue Produktionslogik)."""
        from handlers.test_menu_handler import TestMenuHandler

        class _FakeConfig:
            OWNER_USER_ID = OWNER_ID
            ADMIN_USER_IDS = [OWNER_ID, ADMIN_ID]

        handler = TestMenuHandler(_FakeConfig(), logger_factory=lambda name: Mock())
        update = _make_update(OTHER_ID)

        run_async(handler._execute_test_run(update, "unit", timeout=600))

        _, kwargs = update.callback_query.answer.call_args
        assert kwargs.get("show_alert") is True


# ============================================================
# Test 5 - erradmin: Charakterisierung (NICHT korrigieren)
# ============================================================


class TestErradminCharacterization:
    """ARCH-023/P-2 charakterisierte, ARCH-023/P-5 behoben:
    ErrorHandlerAdminInterface.is_admin() nutzte vormals ausschliesslich
    `user_id in self.admin_user_ids` - der Owner hatte dadurch NUR
    Zugriff auf erradmin:, wenn seine ID zusaetzlich in ADMIN_USER_IDS
    stand, anders als bei jedem anderen Admin-Praefix (dup:/backup_/
    status_/logger_/usermgmt_/restart:/maint:/doctor:/review:/repair:),
    die alle explizit OWNER_USER_ID ODER ADMIN_USER_IDS pruefen. Seit
    P-5 delegiert is_admin() an permissions.is_admin_or_owner() - diese
    Klasse verifiziert jetzt das NEUE, konsistente Verhalten."""

    def _make_system(self, admin_user_ids, owner_id=OWNER_ID):
        system = RichMenuSystem(MockConfig())
        system.initialize_menu_structure()
        if admin_user_ids:
            fake_config = Mock()
            fake_config.OWNER_USER_ID = owner_id
            fake_config.ADMIN_USER_IDS = admin_user_ids
            system.set_error_admin_interface(
                ErrorHandlerAdminInterface(Mock(), admin_user_ids, fake_config)
            )
        # admin_user_ids leer/None => error_admin_interface bleibt None,
        # exakt wie bot.py:151-155 (`if ... and self.config.ADMIN_USER_IDS`)
        # es real verdrahtet.
        return system

    def test_owner_is_accepted_even_when_not_in_admin_user_ids(self, mock_context):
        """ARCH-023/P-5-Fix: der Owner ist jetzt IMMER zugelassen, auch
        wenn seine ID nicht zusaetzlich in ADMIN_USER_IDS steht - konsistent
        mit jedem anderen Admin-Praefix. Vor dem Fix war dies der
        Nachweis der Luecke (siehe Klassen-Docstring); jetzt der
        Nachweis der Behebung."""
        system = self._make_system(admin_user_ids=[ADMIN_ID])  # Owner NICHT enthalten
        update = _make_update(OWNER_ID)

        with patch.object(
            system.error_admin_interface,
            "handle_error_stats_command",
            new=AsyncMock(),
        ) as mocked_target:
            run_async(
                system._handle_error_admin_callback(
                    update, mock_context, "erradmin:show_stats"
                )
            )

        mocked_target.assert_awaited_once()
        update.callback_query.answer.assert_not_awaited()

    def test_owner_in_admin_user_ids_is_accepted(self, mock_context):
        system = self._make_system(admin_user_ids=[OWNER_ID, ADMIN_ID])
        update = _make_update(OWNER_ID)

        with patch.object(
            system.error_admin_interface,
            "handle_error_stats_command",
            new=AsyncMock(),
        ) as mocked_target:
            run_async(
                system._handle_error_admin_callback(
                    update, mock_context, "erradmin:show_stats"
                )
            )

        # Nicht abgelehnt: das Routing-Ziel wird tatsaechlich erreicht
        # (query.answer() wird auf diesem Pfad ueberhaupt nicht
        # aufgerufen, siehe _handle_error_admin_callback()).
        mocked_target.assert_awaited_once()
        update.callback_query.answer.assert_not_awaited()

    def test_configured_admin_is_accepted(self, mock_context):
        system = self._make_system(admin_user_ids=[ADMIN_ID])
        update = _make_update(ADMIN_ID)

        with patch.object(
            system.error_admin_interface,
            "handle_error_stats_command",
            new=AsyncMock(),
        ) as mocked_target:
            run_async(
                system._handle_error_admin_callback(
                    update, mock_context, "erradmin:show_stats"
                )
            )

        mocked_target.assert_awaited_once()
        update.callback_query.answer.assert_not_awaited()

    def test_normal_user_is_rejected(self, mock_context):
        """ARCH-023/P-5 Phase 3: bisher fehlende, fuer die vollstaendige
        Zugriffsmatrix benoetigte Konstellation - weder Owner noch in
        ADMIN_USER_IDS."""
        system = self._make_system(admin_user_ids=[OWNER_ID, ADMIN_ID])
        update = _make_update(OTHER_ID)

        with patch.object(
            system.error_admin_interface,
            "handle_error_stats_command",
            new=AsyncMock(),
        ) as mocked_target:
            run_async(
                system._handle_error_admin_callback(
                    update, mock_context, "erradmin:show_stats"
                )
            )

        mocked_target.assert_not_awaited()
        args, _ = update.callback_query.answer.call_args
        assert args[0] == "⛔ Keine Berechtigung"

    def test_empty_admin_user_ids_makes_erradmin_unreachable_for_everyone(
        self, mock_context
    ):
        """Charakterisiert: ist ADMIN_USER_IDS leer, wird
        error_admin_interface (produktiv, siehe bot.py:151-155) gar
        nicht erst konstruiert - erradmin: ist dann fuer NIEMANDEN
        erreichbar, auch nicht fuer den Owner (fail-closed, kein
        Sicherheitsrisiko, aber eine bisher unbekannte
        Verhaltensabweichung)."""
        system = self._make_system(admin_user_ids=None)
        update = _make_update(OWNER_ID)

        run_async(
            system._handle_error_admin_callback(
                update, mock_context, "erradmin:show_stats"
            )
        )

        args, _ = update.callback_query.answer.call_args
        assert args[0] == "⚠️ Error Admin Interface nicht verfügbar"


# ============================================================
# Test 6 - doctor:/review:/repair: Aequivalenz zu _is_admin_check()
# ============================================================


class TestDoctorReviewRepairEquivalentToIsAdminCheck:
    """Belegt: die Inline-Pruefung `user_id == OWNER_USER_ID or user_id in
    ADMIN_USER_IDS` in _handle_doctor_callback/_handle_review_callback/
    _handle_repair_callback liefert fuer die relevanten
    USER/ADMIN/OWNER-Konstellationen dasselbe Ergebnis wie
    RichMenuSystem._is_admin_check() - Voraussetzung fuer die
    Konsolidierung in Phase 3."""

    @pytest.mark.parametrize("user_id", [OWNER_ID, ADMIN_ID, OTHER_ID, -1, 0])
    def test_is_admin_check_matches_inline_logic_truth_table(self, user_id):
        config = MockConfig()
        expected = user_id == config.OWNER_USER_ID or user_id in config.ADMIN_USER_IDS

        system = RichMenuSystem(config)
        assert system._is_admin_check(user_id) == expected

    @pytest.mark.parametrize(
        "prefix,callback_data,handler_attr,handler_method",
        [
            ("doctor:", "doctor:scan", "doctor_handler", "handle_scan"),
            ("review:", "review:start", "review_handler", "handle_start"),
            ("repair:", "repair:start", "repair_handler", "handle_start"),
        ],
    )
    @pytest.mark.parametrize("user_id", [OWNER_ID, ADMIN_ID, OTHER_ID])
    def test_dispatch_outcome_matches_is_admin_check(
        self, prefix, callback_data, handler_attr, handler_method, user_id, mock_context
    ):
        config = MockConfig()
        system = RichMenuSystem(config)
        system.initialize_menu_structure()
        fake_handler = Mock()
        setattr(fake_handler, handler_method, AsyncMock())
        getattr(system, f"set_{handler_attr}")(fake_handler)

        update = _make_update(user_id)
        update.callback_query.data = callback_data

        run_async(system.handle_callback(update, mock_context))

        expected_allowed = system._is_admin_check(user_id)
        target_mock = getattr(fake_handler, handler_method)
        if expected_allowed:
            target_mock.assert_awaited_once()
        else:
            target_mock.assert_not_awaited()
            args, kwargs = update.callback_query.answer.call_args
            assert args[0] == "⛔ Keine Berechtigung"
            assert kwargs.get("show_alert") is True
