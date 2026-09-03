"""
Characterization-Tests fuer handlers/menu/rich_menu_handler.py
(RichMenuHandler, 1302 Zeilen, zentraler Orchestrator - erstellt/verdrahtet
alle anderen Handler in initialize()), vorher 0 Tests.

WICHTIG: RichMenuHandler.__init__() setzt self.user_data_file =
Path("data/user_data.json") - derselbe hartcodierte, nicht injizierbare
Pfad wie in UserManagementHandler (siehe TEST-009), mit echten laufenden
Bot-Nutzerdaten. _make_handler() patcht Path() waehrend der Konstruktion
auf ein tmp_path-Verzeichnis, analog zu tests/test_user_management_handler.py.

Kein neuer Bug gefunden - _get_user_role() erkennt "owner" hier (im
Gegensatz zu RichMenuSystem._get_user_access_level(), siehe TEST-011)
bereits korrekt.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from utils.navidrome_scan_trigger import ScanRunResult, ScanTimeoutError
from handlers.menu.rich_menu_handler import RichMenuHandler


class MockConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [12345, 67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100


def _make_handler(tmp_path):
    user_data_file = tmp_path / "user_data.json"
    maintenance_state_file = tmp_path / "maintenance_mode.json"

    def _fake_path(p, *args, **kwargs):
        if p == "data/user_data.json":
            return user_data_file
        if p == "data/maintenance_mode.json":
            return maintenance_state_file
        return Path(p, *args, **kwargs)

    config = MockConfig()
    # DownloadHistoryStore (RichMenuHandler.__init__(), Download-Verlauf-
    # Feature) legt sein Cache-Verzeichnis beim Konstruieren tatsaechlich
    # an (mkdir) - ohne dieses Attribut griffe der Default-Fallback in
    # RichMenuHandler ("cache/download_history", relativ) und wuerde ein
    # echtes Verzeichnis im Projekt-Root anlegen statt in tmp_path
    # (TESTENV-01-Analogon, siehe tests/test_config_test_isolation.py).
    config.DOWNLOAD_HISTORY_DIR = tmp_path / "download_history"
    with patch("handlers.menu.rich_menu_handler.Path", side_effect=_fake_path):
        handler = RichMenuHandler(config)
    return handler, user_data_file


def _seed_users(user_data_file, users: dict):
    import json

    user_data_file.parent.mkdir(parents=True, exist_ok=True)
    with open(user_data_file, "w", encoding="utf-8") as f:
        json.dump(users, f)


def make_update(user_id: int, text: str = None):
    update = Mock()
    update.effective_user.id = user_id
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.message = Mock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def make_context():
    context = Mock()
    context.user_data = {}
    return context


class TestIsAdmin:
    def test_owner_is_admin(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        assert handler._is_admin(MockConfig.OWNER_USER_ID) is True

    def test_configured_admin_is_admin(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        assert handler._is_admin(67890) is True

    def test_unknown_user_is_not_admin(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        assert handler._is_admin(99999) is False


class TestUserDataFileIsolation:
    def test_constructing_handler_does_not_touch_real_data_file(self, tmp_path):
        real_file = Path("data/user_data.json")
        real_mtime_before = real_file.stat().st_mtime if real_file.exists() else None

        handler, tmp_file = _make_handler(tmp_path)
        _seed_users(tmp_file, {"999": {"role": "admin"}})
        handler._load_user_data()

        real_mtime_after = real_file.stat().st_mtime if real_file.exists() else None
        assert real_mtime_before == real_mtime_after


class TestGetUserRole:
    def test_config_owner_gets_owner_role(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        assert handler._get_user_role(MockConfig.OWNER_USER_ID) == "owner"

    def test_role_from_stored_user_data_is_used(self, tmp_path):
        handler, user_data_file = _make_handler(tmp_path)
        _seed_users(user_data_file, {"555": {"role": "moderator"}})

        assert handler._get_user_role(555) == "moderator"

    def test_config_admin_without_stored_data_gets_admin_role(self, tmp_path):
        handler, user_data_file = _make_handler(tmp_path)
        _seed_users(user_data_file, {})

        assert handler._get_user_role(67890) == "admin"

    def test_unknown_user_gets_user_role(self, tmp_path):
        handler, user_data_file = _make_handler(tmp_path)
        _seed_users(user_data_file, {})

        assert handler._get_user_role(99999) == "user"

    def test_stored_data_takes_priority_over_config_admin_list(self, tmp_path):
        """
        Charakterisiert bestehende Prioritaet: steht ein Admin (laut
        Config.ADMIN_USER_IDS) auch in user_data.json mit einer anderen
        Rolle, gewinnt die gespeicherte Rolle.
        """
        handler, user_data_file = _make_handler(tmp_path)
        _seed_users(user_data_file, {"67890": {"role": "user"}})

        assert handler._get_user_role(67890) == "user"


class TestIsNewUser:
    def test_unknown_user_is_new(self, tmp_path):
        handler, user_data_file = _make_handler(tmp_path)
        _seed_users(user_data_file, {})

        assert handler._is_new_user(12345) is True

    def test_user_registered_recently_is_new(self, tmp_path):
        from datetime import datetime

        handler, user_data_file = _make_handler(tmp_path)
        _seed_users(
            user_data_file,
            {"555": {"role": "user", "created_at": datetime.now().isoformat()}},
        )

        assert handler._is_new_user(555) is True

    def test_user_registered_long_ago_is_not_new(self, tmp_path):
        from datetime import datetime, timedelta

        handler, user_data_file = _make_handler(tmp_path)
        old_date = (datetime.now() - timedelta(days=30)).isoformat()
        _seed_users(user_data_file, {"555": {"role": "user", "created_at": old_date}})

        assert handler._is_new_user(555) is False


class TestGetAvailableFeatures:
    def test_user_role_only_gets_user_level_features(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        features = handler._get_available_features("user")

        assert "download" in features
        assert "admin" not in features

    def test_admin_role_gets_admin_features_too(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        features = handler._get_available_features("admin")

        assert "download" in features
        assert "admin" in features
        assert "tests" in features

    def test_unknown_role_defaults_to_user_level(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        features = handler._get_available_features("totally_unknown_role")

        assert "download" in features
        assert "admin" not in features


class TestCreateDownloadHandler:
    def test_returns_none_without_duplicate_detector(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        handler.metadata_processor = Mock()
        handler.duplicate_detector = None

        update = make_update(111)
        result = handler._create_download_handler(update)

        assert result is None

    def test_returns_none_without_metadata_processor(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        handler.duplicate_detector = Mock()
        handler.metadata_processor = None

        update = make_update(111)
        result = handler._create_download_handler(update)

        assert result is None

    def test_creates_handler_with_shared_duplicate_detector(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        handler.duplicate_detector = Mock()
        handler.metadata_processor = Mock()

        update = make_update(111)
        with patch(
            "handlers.menu.rich_menu_handler.DownloadHandler"
        ) as mock_download_handler_cls:
            handler._create_download_handler(update)

        _args, kwargs = mock_download_handler_cls.call_args
        assert kwargs["duplicate_detector"] is handler.duplicate_detector

    def test_creates_handler_with_shared_active_downloads_registry(self, tmp_path):
        """Download-Control-Center 2026-09-02: DownloadHandler bekommt
        dieselbe, ueber die gesamte Bot-Laufzeit bestehende
        ActiveDownloadRegistry-Instanz injiziert (RichMenuHandler baut
        sie EINMAL in __init__(), nicht pro Download)."""
        handler, _ = _make_handler(tmp_path)
        handler.duplicate_detector = Mock()
        handler.metadata_processor = Mock()

        update = make_update(111)
        with patch(
            "handlers.menu.rich_menu_handler.DownloadHandler"
        ) as mock_download_handler_cls:
            handler._create_download_handler(update)

        _args, kwargs = mock_download_handler_cls.call_args
        assert kwargs["active_downloads"] is handler.active_downloads


class TestHandleUrlMessage:
    def test_url_processed_immediately_without_active_state(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        handler._process_url = AsyncMock()

        update = make_update(111, text="https://youtube.com/watch?v=abc")
        context = make_context()

        asyncio.run(handler.handle_url_message(update, context))

        handler._process_url.assert_called_once()

    def test_url_processed_when_awaiting_single_url_state(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        handler._process_url = AsyncMock()
        handler.user_states[111] = "awaiting_single_url"

        update = make_update(111, text="https://youtube.com/watch?v=abc")
        context = make_context()

        asyncio.run(handler.handle_url_message(update, context))

        handler._process_url.assert_called_once()
        assert 111 not in handler.user_states  # State wird aufgeraeumt


class TestHandleTextMessageWorkflow:
    def test_active_workflow_dispatches_to_user_mgmt_handler(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        fake_user_mgmt = Mock()
        fake_user_mgmt.process_new_user_id = AsyncMock()
        handler.user_mgmt_handler = fake_user_mgmt

        update = make_update(111, text="123456789")
        context = make_context()
        context.user_data["workflow"] = "add_user_id"

        asyncio.run(handler.handle_text_message(update, context))

        fake_user_mgmt.process_new_user_id.assert_called_once_with(
            update, context, "123456789"
        )

    def test_missing_handler_for_workflow_clears_user_data(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        handler.user_mgmt_handler = None

        update = make_update(111, text="123456789")
        context = make_context()
        context.user_data["workflow"] = "add_user_id"

        asyncio.run(handler.handle_text_message(update, context))

        update.message.reply_text.assert_called_once()
        assert context.user_data == {}

    def test_cancel_command_clears_state(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        handler.user_states[111] = "awaiting_single_url"

        update = make_update(111, text="/cancel")
        context = make_context()

        asyncio.run(handler.handle_text_message(update, context))

        assert context.user_data == {}
        assert 111 not in handler.user_states
        update.message.reply_text.assert_called_once()

    def test_cancel_works_even_with_active_workflow_bug006_regression(self, tmp_path):
        """
        Regressionstest fuer BUG-006 (docs/archive/MusicBot_ENGINEERING_BASELINE.md):
        die Abbruch-Pruefung stand vorher NACH dem Workflow-Dispatch-Block,
        der bei aktivem Workflow immer vorher returnt - "/cancel" wurde
        nie als Abbruch erkannt, solange context.user_data["workflow"]
        gesetzt war, sondern woertlich an den Workflow-Handler
        durchgereicht. Obwohl UserManagementHandler dem Nutzer explizit
        "/cancel" als Ausstiegsweg anbietet.
        """
        handler, _ = _make_handler(tmp_path)
        fake_user_mgmt = Mock()
        fake_user_mgmt.process_new_user_id = AsyncMock()
        handler.user_mgmt_handler = fake_user_mgmt

        update = make_update(111, text="/cancel")
        context = make_context()
        context.user_data["workflow"] = "add_user_id"

        asyncio.run(handler.handle_text_message(update, context))

        fake_user_mgmt.process_new_user_id.assert_not_called()
        assert context.user_data == {}
        message = update.message.reply_text.call_args[0][0]
        assert "abgebrochen" in message

    def test_cancel_also_works_during_navidrome_search(self, tmp_path):
        """BUG-006 betraf auch den Navidrome-Suchpfad, der "/cancel" zuvor
        als woertlichen Suchbegriff an Navidrome weitergereicht haette."""
        handler, _ = _make_handler(tmp_path)
        fake_navidrome = Mock()
        fake_navidrome.browse_states = {111: {"waiting_for_search": True}}
        fake_navidrome.process_search_query = AsyncMock()
        handler.navidrome_handler = fake_navidrome

        update = make_update(111, text="/cancel")
        context = make_context()

        asyncio.run(handler.handle_text_message(update, context))

        fake_navidrome.process_search_query.assert_not_called()
        message = update.message.reply_text.call_args[0][0]
        assert "abgebrochen" in message

    def test_unhandled_text_without_workflow_does_not_crash(self, tmp_path):
        handler, _ = _make_handler(tmp_path)

        update = make_update(111, text="just some random text")
        context = make_context()

        asyncio.run(handler.handle_text_message(update, context))  # Kein Crash

        update.message.reply_text.assert_not_called()


class TestDownloadWrapperSetsUserState:
    def test_single_download_wrapper_sets_awaiting_state(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        update = make_update(111)
        context = make_context()

        asyncio.run(handler._handle_download_single_wrapper(update, context))

        assert handler.user_states[111] == "awaiting_single_url"

    def test_playlist_download_wrapper_sets_awaiting_state(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        update = make_update(111)
        context = make_context()

        asyncio.run(handler._handle_download_playlist_wrapper(update, context))

        assert handler.user_states[111] == "awaiting_playlist_url"


class TestHandleNavidromeScan:
    """
    ARCH-009 Phase 5 (2026-08-24): die Telegram-MarkdownV2-Formatierung
    (Erfolg/Fehlschlag/Timeout/generische Exception) liegt im Handler
    (siehe docs/archive/arch/MusicBot_ARCH-009_Phase5_Telegram_Verantwortlichkeiten_Analyse.md).

    ARCH-009 Phase 9, Umsetzung A (2026-08-24): die zwischenzeitliche
    NavidromeAPI.execute_scan()-Bridge (api/navidrome_api.py) wurde
    vollstaendig entfernt - der Handler ruft jetzt direkt
    NavidromeScanTrigger.run_scan() auf (siehe
    docs/archive/arch/MusicBot_ARCH-009_Phase9_Finaler_Migrationsabschluss_Analyse.md).
    Diese Tests verifizieren weiterhin, dass die vier sichtbaren
    Nachrichtenvarianten inhaltlich unveraendert bleiben, jetzt gemockt auf
    Ebene von NavidromeScanTrigger.run_scan() (ScanRunResult/ScanTimeoutError)
    statt der entfernten Bridge.

    Historischer Kontext: vor einem frueheren Fix rief diese Handler-Methode
    self.navidrome_adapter.trigger_scan() auf, obwohl navidrome_adapter
    nirgends im Repo instanziiert wurde - self.navidrome_adapter war IMMER
    None, jeder Klick zeigte nur "Navidrome-Adapter nicht verfuegbar".
    """

    def test_admin_triggers_scan_via_navidrome_api(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        update = make_update(MockConfig.OWNER_USER_ID)
        context = make_context()

        with patch(
            "handlers.menu.rich_menu_handler.NavidromeScanTrigger.run_scan",
            new=AsyncMock(
                return_value=ScanRunResult(
                    success=True, returncode=0, stdout="Scan complete", stderr=""
                )
            ),
        ) as mock_scan:
            asyncio.run(handler._handle_navidrome_scan(update, context))

        mock_scan.assert_called_once()
        args, kwargs = update.callback_query.edit_message_text.call_args
        assert "Scan complete" in args[0]
        assert "Scan erfolgreich" in args[0]
        assert kwargs["parse_mode"] == "MarkdownV2"

    def test_scan_failure_message_is_still_shown_to_admin(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        update = make_update(MockConfig.OWNER_USER_ID)
        context = make_context()

        with patch(
            "handlers.menu.rich_menu_handler.NavidromeScanTrigger.run_scan",
            new=AsyncMock(
                return_value=ScanRunResult(
                    success=False, returncode=1, stdout="", stderr="boom"
                )
            ),
        ):
            asyncio.run(handler._handle_navidrome_scan(update, context))

        args, kwargs = update.callback_query.edit_message_text.call_args
        assert "boom" in args[0]
        assert "Scan fehlgeschlagen" in args[0]
        assert kwargs["parse_mode"] == "MarkdownV2"

    def test_timeout_shows_timeout_message(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        update = make_update(MockConfig.OWNER_USER_ID)
        context = make_context()

        with patch(
            "handlers.menu.rich_menu_handler.NavidromeScanTrigger.run_scan",
            new=AsyncMock(side_effect=ScanTimeoutError(45)),
        ):
            asyncio.run(handler._handle_navidrome_scan(update, context))

        args, kwargs = update.callback_query.edit_message_text.call_args
        assert "45" in args[0]
        assert "länger" in args[0]
        assert kwargs["parse_mode"] == "MarkdownV2"

    def test_non_admin_is_rejected_without_calling_scan(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        update = make_update(999999)  # nicht in ADMIN_USER_IDS/OWNER_USER_ID
        context = make_context()

        with patch(
            "handlers.menu.rich_menu_handler.NavidromeScanTrigger.run_scan",
            new=AsyncMock(),
        ) as mock_scan:
            asyncio.run(handler._handle_navidrome_scan(update, context))

        mock_scan.assert_not_called()
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung")

    def test_exception_during_scan_is_caught_and_reported(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        update = make_update(MockConfig.OWNER_USER_ID)
        context = make_context()

        with patch(
            "handlers.menu.rich_menu_handler.NavidromeScanTrigger.run_scan",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            asyncio.run(handler._handle_navidrome_scan(update, context))

        args, kwargs = update.callback_query.edit_message_text.call_args
        assert "Unerwarteter Fehler" in args[0]
        assert "boom" in args[0]
        assert kwargs["parse_mode"] == "MarkdownV2"


class TestProcessUrlRunsAsBackgroundTask:
    """
    Live-Fund 2026-09-02 (Nutzer-Report: "sobald Download läuft öffnet
    sich das Menü nicht"): ohne concurrent_updates=True (bot.py) blockiert
    ein direktes `await handler.handle_url(...)` in _process_url() die
    Verarbeitung JEDES weiteren Telegram-Updates fuer die gesamte
    Downloaddauer. Fix: der Download laeuft als asyncio.create_task() -
    _process_url() selbst kehrt sofort zurueck.
    """

    def test_returns_before_handle_url_completes(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        update = make_update(MockConfig.OWNER_USER_ID, text="https://youtu.be/x")
        context = make_context()

        started = asyncio.Event()
        may_finish = asyncio.Event()

        async def slow_handle_url(update, context):
            started.set()
            await may_finish.wait()

        download_handler = Mock()
        download_handler.handle_url = AsyncMock(side_effect=slow_handle_url)

        async def scenario():
            with patch.object(
                handler, "_create_download_handler", return_value=download_handler
            ):
                await handler._process_url(update, context, "https://youtu.be/x")
                # _process_url() ist bereits zurueck, obwohl handle_url()
                # noch auf may_finish wartet - das beweist, dass es NICHT
                # inline awaited wurde.
                assert not may_finish.is_set()
                await asyncio.wait_for(started.wait(), timeout=1)
                may_finish.set()
                await asyncio.sleep(0)  # Hintergrund-Task fertig laufen lassen

        asyncio.run(scenario())
        download_handler.handle_url.assert_awaited_once()

    def test_background_task_exception_is_logged_not_raised(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        handler.logger = Mock()
        update = make_update(MockConfig.OWNER_USER_ID, text="https://youtu.be/x")
        context = make_context()

        download_handler = Mock()
        download_handler.handle_url = AsyncMock(side_effect=RuntimeError("kaputt"))

        async def scenario():
            with patch.object(
                handler, "_create_download_handler", return_value=download_handler
            ):
                await handler._process_url(update, context, "https://youtu.be/x")
                await asyncio.sleep(0.05)  # Hintergrund-Task Zeit geben

        asyncio.run(scenario())  # darf NICHT raisen

        handler.logger.error.assert_called_once()
        logged = handler.logger.error.call_args[0][0]
        assert "kaputt" in logged

    def test_successful_background_task_does_not_log_error(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        handler.logger = Mock()
        update = make_update(MockConfig.OWNER_USER_ID, text="https://youtu.be/x")
        context = make_context()

        download_handler = Mock()
        download_handler.handle_url = AsyncMock(return_value=None)

        async def scenario():
            with patch.object(
                handler, "_create_download_handler", return_value=download_handler
            ):
                await handler._process_url(update, context, "https://youtu.be/x")
                await asyncio.sleep(0.05)

        asyncio.run(scenario())

        handler.logger.error.assert_not_called()

    def test_no_handler_still_replies_synchronously(self, tmp_path):
        """Der 'Download-Dienst nicht verfügbar'-Fall bleibt synchron
        (kein Task noetig, da nichts Langlaufendes passiert)."""
        handler, _ = _make_handler(tmp_path)
        update = make_update(MockConfig.OWNER_USER_ID, text="https://youtu.be/x")
        context = make_context()

        with patch.object(handler, "_create_download_handler", return_value=None):
            asyncio.run(handler._process_url(update, context, "https://youtu.be/x"))

        update.message.reply_text.assert_awaited_once()


class TestGetTelegramHandlersRegistersDlPrefix:
    """
    Live-Fund 2026-09-02 ("Downloads lässt sich öffnen aber die restlichen
    Buttons sind tot außer Hauptmenü"): CallbackQueryHandler werden PTB-
    seitig über feste pattern=-Allowlists geroutet - das interne
    dl:-Präfix-Routing in RichMenuSystem.handle_callback() lief komplett
    ins Leere, solange hier kein eigener Handler für "^dl:" registriert
    war (PTB fand für dl:*-Callback-Daten schlicht keinen passenden
    Handler und tat gar nichts - kein Log, keine Exception). Andere
    Präfixe (dup:/backup_/status_/...) hatten diesen Handler bereits.
    """

    def test_dl_prefixed_callback_query_handler_is_registered(self, tmp_path):
        from telegram.ext import CallbackQueryHandler

        handler, _ = _make_handler(tmp_path)

        handlers = handler.get_telegram_handlers()

        dl_handlers = [
            h
            for h in handlers
            if isinstance(h, CallbackQueryHandler)
            and h.pattern is not None
            and h.pattern.match("dl:active")
        ]
        assert len(dl_handlers) == 1

    def test_dl_handler_targets_menu_system_handle_callback(self, tmp_path):
        from telegram.ext import CallbackQueryHandler

        handler, _ = _make_handler(tmp_path)

        handlers = handler.get_telegram_handlers()
        dl_handler = next(
            h
            for h in handlers
            if isinstance(h, CallbackQueryHandler)
            and h.pattern is not None
            and h.pattern.match("dl:new")
        )

        assert dl_handler.callback == handler.menu_system.handle_callback

    def test_dl_pattern_does_not_accidentally_match_menu_prefix(self, tmp_path):
        """Regressionsschutz: das neue Pattern darf ausschließlich
        dl:-Callbacks abdecken, nicht versehentlich menu:/dup:/etc.
        mit-matchen (Präfix-Kollision)."""
        from telegram.ext import CallbackQueryHandler

        handler, _ = _make_handler(tmp_path)

        handlers = handler.get_telegram_handlers()
        dl_handler = next(
            h
            for h in handlers
            if isinstance(h, CallbackQueryHandler)
            and h.pattern is not None
            and h.pattern.match("dl:new")
        )

        assert not dl_handler.pattern.match("menu:download")
        assert not dl_handler.pattern.match("dup:show_stats")


class TestGetTelegramHandlersRegistersMaintPrefix:
    """
    Live-Fund 2026-09-03 (Nutzer-Report beim ersten Live-Test des
    Wartungsmodus-Features: "bei drücken auf Wartungsmodus passiert
    nichts") - identisches "Bug B"-Muster wie beim dl:-Praefix
    (test_dl_prefixed_callback_query_handler_is_registered oben): das
    interne maint:-Praefix-Routing in RichMenuSystem.handle_callback()
    war bereits korrekt implementiert, aber ohne eigenen
    CallbackQueryHandler(pattern="^maint:") in get_telegram_handlers()
    fand PTB fuer maint:show/maint:toggle schlicht keinen passenden
    Handler und tat gar nichts - weder Log-Eintrag noch Exception.
    """

    def test_maint_prefixed_callback_query_handler_is_registered(self, tmp_path):
        from telegram.ext import CallbackQueryHandler

        handler, _ = _make_handler(tmp_path)

        handlers = handler.get_telegram_handlers()

        maint_handlers = [
            h
            for h in handlers
            if isinstance(h, CallbackQueryHandler)
            and h.pattern is not None
            and h.pattern.match("maint:show")
        ]
        assert len(maint_handlers) == 1

    def test_maint_handler_targets_menu_system_handle_callback(self, tmp_path):
        from telegram.ext import CallbackQueryHandler

        handler, _ = _make_handler(tmp_path)

        handlers = handler.get_telegram_handlers()
        maint_handler = next(
            h
            for h in handlers
            if isinstance(h, CallbackQueryHandler)
            and h.pattern is not None
            and h.pattern.match("maint:toggle")
        )

        assert maint_handler.callback == handler.menu_system.handle_callback

    def test_maint_pattern_does_not_accidentally_match_other_prefixes(self, tmp_path):
        """Regressionsschutz: das neue Pattern darf ausschließlich
        maint:-Callbacks abdecken, nicht versehentlich menu:/dl:/etc.
        mit-matchen (Präfix-Kollision)."""
        from telegram.ext import CallbackQueryHandler

        handler, _ = _make_handler(tmp_path)

        handlers = handler.get_telegram_handlers()
        maint_handler = next(
            h
            for h in handlers
            if isinstance(h, CallbackQueryHandler)
            and h.pattern is not None
            and h.pattern.match("maint:show")
        )

        assert not maint_handler.pattern.match("menu:admin")
        assert not maint_handler.pattern.match("dl:new")
        assert not maint_handler.pattern.match("restart:show")


class TestGetTelegramHandlersRegistersReprocessPrefix:
    """
    Identisches "Bug B"-Muster wie bei dl:/maint: oben (siehe dortige
    Docstrings) - ohne einen eigenen CallbackQueryHandler(pattern=
    "^reprocess:") in get_telegram_handlers() faende PTB fuer
    reprocess:show/reprocess:pick:.../reprocess:live:... schlicht keinen
    passenden Handler und taete gar nichts, obwohl das interne
    reprocess:-Praefix-Routing in RichMenuSystem.handle_callback() bereits
    korrekt implementiert ist.
    """

    def test_reprocess_prefixed_callback_query_handler_is_registered(self, tmp_path):
        from telegram.ext import CallbackQueryHandler

        handler, _ = _make_handler(tmp_path)

        handlers = handler.get_telegram_handlers()

        reprocess_handlers = [
            h
            for h in handlers
            if isinstance(h, CallbackQueryHandler)
            and h.pattern is not None
            and h.pattern.match("reprocess:show")
        ]
        assert len(reprocess_handlers) == 1

    def test_reprocess_handler_targets_menu_system_handle_callback(self, tmp_path):
        from telegram.ext import CallbackQueryHandler

        handler, _ = _make_handler(tmp_path)

        handlers = handler.get_telegram_handlers()
        reprocess_handler = next(
            h
            for h in handlers
            if isinstance(h, CallbackQueryHandler)
            and h.pattern is not None
            and h.pattern.match("reprocess:pick:0")
        )

        assert reprocess_handler.callback == handler.menu_system.handle_callback

    def test_reprocess_pattern_does_not_accidentally_match_other_prefixes(
        self, tmp_path
    ):
        """Regressionsschutz: das neue Pattern darf ausschließlich
        reprocess:-Callbacks abdecken, nicht versehentlich menu:/dl:/
        maint:/etc. mit-matchen (Präfix-Kollision)."""
        from telegram.ext import CallbackQueryHandler

        handler, _ = _make_handler(tmp_path)

        handlers = handler.get_telegram_handlers()
        reprocess_handler = next(
            h
            for h in handlers
            if isinstance(h, CallbackQueryHandler)
            and h.pattern is not None
            and h.pattern.match("reprocess:show")
        )

        assert not reprocess_handler.pattern.match("menu:admin")
        assert not reprocess_handler.pattern.match("dl:new")
        assert not reprocess_handler.pattern.match("maint:show")
