"""
Phase F2 (Family Hub) - Tests für handlers/family_stats_handler.py.

Fokus:
  1. Zugriffsverweigerung für Nicht-Familienmitglieder (Datenschutzregel
     aus dem Master-Prompt: "Ein normaler Bot-Benutzer darf niemals
     Familienstatistiken sehen").
  2. Korrekte Formatierung/Weiterleitung an FamilyStatsService bei
     berechtigtem Zugriff.

MASTER PHASE B (Family Statistics Attribution, Identity & UX
Optimization): Mock-Rückgabewerte von FamilyStatsService wurden auf die
neue, strukturierte Form (top_songs/top_artists als Dict-Listen mit
Member-Attribution, period_start/period_end) umgestellt; neue Tests für
Medaillen/Pluralisierung/Gesamtzeile-nur-bei-mehreren-Mitgliedern.

Mock-Strategie identisch zu tests/test_mugge_statistik_handler.py:
FamilyService/FamilyStatsService werden als Mocks injiziert (keine echten
Dateien/Navidrome-Zugriffe).
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock

from handlers.family_stats_handler import FamilyStatsHandler

PERIOD_START = datetime(2026, 9, 1)
PERIOD_END = datetime(2026, 10, 1)


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


def _stats(top_songs=None, top_artists=None, per_member=None, total_plays=0):
    return {
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
        "total_plays": total_plays,
        "top_songs": top_songs or [],
        "top_artists": top_artists or [],
        "per_member": per_member or {},
        "listening_seconds": 0,
        "listening_seconds_reliable": False,
    }


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
        family_stats_service.generate_family_stats.return_value = _stats(
            top_songs=[{"title": "Song A", "artists": "Artist", "total_plays": 3,
                        "members": [{"display_name": "Papa", "plays": 3}]}],
            total_plays=3,
        )
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
        family_stats_service.generate_family_stats.return_value = _stats(
            top_songs=[
                {"title": "Song A", "artists": "Artist X", "total_plays": 10,
                 "members": [{"display_name": "Papa", "plays": 10}]},
                {"title": "Song B", "artists": "Artist Y", "total_plays": 5,
                 "members": [{"display_name": "Mama", "plays": 5}]},
            ],
            total_plays=15,
        )
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_top_songs(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Song A" in sent_text and "Song B" in sent_text
        assert "15 Plays" in sent_text
        assert "🥇" in sent_text and "🥈" in sent_text

    def test_single_member_song_has_no_redundant_total_line(self):
        """Abschnitt 14: kein '📊 Gesamt · N Plays' bei genau einem
        Hörer - nur die Familien-Gesamtzeile am Ende bleibt."""
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_family_stats.return_value = _stats(
            top_songs=[
                {"title": "Song A", "artists": "Artist X", "total_plays": 10,
                 "members": [{"display_name": "Papa", "plays": 10}]},
            ],
            total_plays=10,
        )
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_top_songs(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        # keine pro-Song-Gesamtzeile, nur die Familien-Gesamtzeile am Ende
        assert "📊 Gesamt ·" not in sent_text
        assert "📊 Familie gesamt ·" in sent_text

    def test_multi_member_song_has_per_song_total_line(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_family_stats.return_value = _stats(
            top_songs=[
                {"title": "Song A", "artists": "Artist X", "total_plays": 20,
                 "members": [
                     {"display_name": "Papa", "plays": 15},
                     {"display_name": "Mama", "plays": 5},
                 ]},
            ],
            total_plays=20,
        )
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_top_songs(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        # eine pro-Song-Gesamtzeile UND die Familien-Gesamtzeile
        assert "📊 Gesamt ·" in sent_text
        assert "📊 Familie gesamt ·" in sent_text
        assert "Papa" in sent_text and "Mama" in sent_text
        assert "15 Plays" in sent_text and "5 Plays" in sent_text

    def test_single_play_is_singular(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_family_stats.return_value = _stats(
            top_songs=[
                {"title": "Song A", "artists": "Artist X", "total_plays": 1,
                 "members": [{"display_name": "Papa", "plays": 1}]},
            ],
            total_plays=1,
        )
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_top_songs(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "1 Play" in sent_text
        assert "1 Plays" not in sent_text


class TestHandleFamilyTopArtists:
    def test_no_data_shows_warning(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_family_stats.return_value = None
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_top_artists(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Keine Wiedergaben" in sent_text

    def test_artists_are_formatted_with_rank_and_member_attribution(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_family_stats.return_value = _stats(
            top_artists=[
                {"artist": "Clueso", "total_plays": 25,
                 "members": [
                     {"display_name": "Papa", "plays": 18},
                     {"display_name": "Mama", "plays": 7},
                 ]},
            ],
            total_plays=25,
        )
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_top_artists(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "🥇 Clueso" in sent_text
        assert "18 Plays" in sent_text and "7 Plays" in sent_text


class TestHandleFamilyMemberStats:
    def test_members_are_ranked_by_plays_descending(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_family_stats.return_value = _stats(
            per_member={
                "111": {"display_name": "Papa", "plays": 2},
                "222": {"display_name": "Mama", "plays": 9},
            },
            total_plays=11,
        )
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_member_stats(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert sent_text.index("Mama") < sent_text.index("Papa")

    def test_percentages_computed_from_total_plays(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_family_stats.return_value = _stats(
            per_member={
                "111": {"display_name": "Papa", "plays": 120},
                "222": {"display_name": "Mama", "plays": 73},
            },
            total_plays=193,
        )
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_member_stats(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "62,2 %" in sent_text
        assert "37,8 %" in sent_text

    def test_medals_used_for_top_three(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_family_stats.return_value = _stats(
            per_member={
                "1": {"display_name": "A", "plays": 3},
                "2": {"display_name": "B", "plays": 2},
                "3": {"display_name": "C", "plays": 1},
            },
            total_plays=6,
        )
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_member_stats(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "🥇" in sent_text and "🥈" in sent_text and "🥉" in sent_text


class TestHandleFamilyChampion:
    def test_champion_name_and_plays_in_response(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.get_champion.return_value = ("222", "Mama", 9)
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_champion(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Mama" in sent_text and "9 Plays" in sent_text

    def test_no_champion_shows_warning(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.get_champion.return_value = None
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_champion(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Keine Wiedergaben" in sent_text


class TestHandleFamilyListeningTimes:
    def test_activity_label_used_not_misleading_duration_wording(self):
        """Abschnitt 20: 'Hör-Aktivität' statt irreführendem 'Hörzeit' -
        duration ist unzuverlässig, nur Play-Zeitpunkte werden analysiert."""
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_listening_times.return_value = {
            "period_start": PERIOD_START,
            "period_end": PERIOD_END,
            "total_plays": 5,
            "by_hour": {h: (3 if h == 20 else 0) for h in range(24)},
            "by_weekday": {d: (5 if d == 2 else 0) for d in range(7)},
        }
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_listening_times(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Hör-Aktivität" in sent_text
        assert "Hörzeit" not in sent_text

    def test_no_data_shows_warning(self):
        handler, _, family_stats_service = _make_handler()
        family_stats_service.generate_listening_times.return_value = None
        update = make_update(111)
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        asyncio.run(handler.handle_family_listening_times(update, Mock()))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Keine Wiedergaben" in sent_text


class TestHandleFamilyMonthlyTrend:
    def test_months_listed_in_order_with_german_names(self):
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
        assert "August" in sent_text and "September" in sent_text
        assert sent_text.index("August") < sent_text.index("September")
        assert "10 Plays" in sent_text and "5 Plays" in sent_text
