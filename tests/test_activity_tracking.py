"""
BotStatusTracker-Funktionslücke (docs/audits/HANDLER_METHOD_LEVEL_SWEEP_2026-09-03.md):
Tests für den gemeinsamen Aktivitäts-Aufzeichnungs-Helfer
handlers/menu/activity_tracking.py::record_activity(), isoliert von
RichMenuHandler/RichMenuSystem.
"""

from unittest.mock import Mock

from handlers.menu.activity_tracking import record_activity


def make_update(user_id):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    return update


class TestRecordActivity:
    def test_records_on_real_status_handler(self):
        status_handler = Mock()
        update = make_update(999)

        record_activity(update, status_handler, "command:start")

        status_handler.bot_tracker.record_user_activity.assert_called_once_with(
            999, "command:start"
        )

    def test_missing_status_handler_is_noop(self):
        update = make_update(999)

        # Darf nicht raisen.
        record_activity(update, None, "command:start")

    def test_missing_bot_tracker_attribute_is_noop(self):
        status_handler = Mock(spec=[])  # kein bot_tracker-Attribut
        update = make_update(999)

        record_activity(update, status_handler, "command:start")

    def test_missing_effective_user_is_noop(self):
        status_handler = Mock()
        update = Mock()
        update.effective_user = None

        record_activity(update, status_handler, "command:start")

        status_handler.bot_tracker.record_user_activity.assert_not_called()

    def test_exception_in_tracker_is_swallowed(self):
        status_handler = Mock()
        status_handler.bot_tracker.record_user_activity.side_effect = RuntimeError(
            "boom"
        )
        update = make_update(999)

        # Darf nicht raisen - reine Diagnosefunktion.
        record_activity(update, status_handler, "command:start")
