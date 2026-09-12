"""
Phase F2 (Family Hub) - Tests für handlers/family_stats_handler.py.

Fokus:
  1. Zugriffsverweigerung für Nicht-Familienmitglieder (Datenschutzregel
     aus dem Master-Prompt: "Ein normaler Bot-Benutzer darf niemals
     Familienstatistiken sehen").
  2. Korrekte Formatierung/Weiterleitung an FamilyStatsService bei
     berechtigtem Zugriff.

Mock-Strategie identisch zu tests/test_mugge_statistik_handler.py:
FamilyService/FamilyStatsService werden als Mocks injiziert (keine echten
Dateien/Navidrome-Zugriffe).
"""

import asyncio
from unittest.mock import AsyncMock, Mock

from handlers.family_stats_handler import FamilyStatsHandler


def make_update(user_id: int = 111, has_callback_query=False):
    update = Mock()
    update.effective_user.id = user_id
    if has_callback_query:
        update.callback_query = AsyncMock()
        update.callback_query.message = Mock()
        update.callback_query.message.reply_text = AsyncMock()
        update.message = None
    else:
        update.callback_query = None
        update.message = Mock()
        update.message.reply_text = AsyncMock()
    return update


def _make_handler(is_member=True):
    family_service = Mock()
    family_service.is_active_family_member.return_value = is_member
    family_service.get_family_id_for_telegram_user.return_value = "main" if is_member else None
    family_stats_service = Mock()
    handler = FamilyStatsHandler(
        family_service=family_service, family_stats_service=family_stats_service
    )
    return handler, family_service, family_stats_service


class TestAccessControl:
    def test_non_member_is_denied_for_top_songs(self):
        handler, family_service, family_stats_service = _make_handler(is_member=False)
        update = make_update(999)

        asyncio.run(handler.handle_family_top_songs(update, Mock()))

        family_stats_service.generate_family_stats.assert_not_called()
        update.message.reply_text.assert_called_once()
        assert "Familienmitglieder" in update.message.reply_text.call_args[0][0]

    def test_non_member_is_denied_for_champion(self):
        handler, _, family_stats_service = _make_handler(is_member=False)
        update = make_update(999)

        asyncio.run(handler.handle_family_champion(update, Mock()))

        family_stats_service.get_champion.assert_not_called()

    def test_non_member_callback_query_gets_alert_answer(self):
        handler, _, family_stats_service = _make_handler(is_member=False)
        update = make_update(999, has_callback_query=True)

        asyncio.run(handler.handle_family_member_stats(update, Mock()))

        update.callback_query.answer.assert_called_once()
        assert update.callback_query.answer.call_args.kwargs["show_alert"] is True
        family_stats_service.generate_family_stats.assert_not_called()

    def test_member_is_not_denied_for_top_songs(self):
        handler, _, family_stats_service = _make_handler(is_member=True)
        family_stats_service.generate_family_stats.return_value = {
            "top_songs": [("Song A", 3)],
            "total_plays": 3,
        }
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_top_songs(update, Mock()))

        family_stats_service.generate_family_stats.assert_called_once_with("main", "month")


class TestHandleFamilyTopSongs:
    def test_no_data_shows_warning(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_family_stats.return_value = None
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_top_songs(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Keine Wiedergaben" in sent_text

    def test_songs_are_formatted_with_rank_and_plays(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_family_stats.return_value = {
            "top_songs": [("Song A", 10), ("Song B", 5)],
            "total_plays": 15,
        }
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_top_songs(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Song A" in sent_text and "Song B" in sent_text
        assert "15" in sent_text


class TestHandleFamilyMemberStats:
    def test_members_are_ranked_by_plays_descending(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_family_stats.return_value = {
            "per_member": {
                "111": {"display_name": "Papa", "plays": 2},
                "222": {"display_name": "Mama", "plays": 9},
            }
        }
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_member_stats(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert sent_text.index("Mama") < sent_text.index("Papa")


class TestHandleFamilyChampion:
    def test_champion_name_and_plays_in_response(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.get_champion.return_value = ("222", "Mama", 9)
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_champion(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Mama" in sent_text and "9" in sent_text

    def test_no_champion_shows_warning(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.get_champion.return_value = None
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_champion(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Keine Wiedergaben" in sent_text


class TestHandleFamilyMonthlyTrend:
    def test_months_listed_in_order(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_monthly_trend.return_value = {
            "months": ["2026-08", "2026-09"],
            "plays_by_month": {"2026-08": 5, "2026-09": 10},
        }
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_monthly_trend(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert sent_text.index("2026-08") < sent_text.index("2026-09")
