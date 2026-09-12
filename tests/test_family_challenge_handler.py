"""
Phase F4 (Family Hub) - Tests für handlers/family_challenge_handler.py.

Mock-Strategie identisch zu tests/test_family_chat_handler.py:
FamilyService/FamilyChallengeService werden als Mocks injiziert.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

from handlers.family_challenge_handler import FamilyChallengeHandler


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
    challenge_service = Mock()
    handler = FamilyChallengeHandler(
        family_service=family_service, challenge_service=challenge_service
    )
    return handler, family_service, challenge_service


SAMPLE_CHALLENGE = {"id": 1, "question": "Wer war heute Top-Artist?"}


class TestHandleTodaysChallenge:
    def test_denied_for_non_member(self):
        handler, _, challenge_service = _make_handler(is_member=False)
        update = make_update(999)

        asyncio.run(handler.handle_todays_challenge(update, Mock()))

        challenge_service.get_or_create_todays_challenge.assert_not_called()
        assert "Familienmitglieder" in update.message.reply_text.call_args[0][0]

    def test_shows_question_and_prompts_to_answer_when_not_yet_answered(self):
        handler, _, challenge_service = _make_handler()
        challenge_service.get_or_create_todays_challenge.return_value = (SAMPLE_CHALLENGE, True)
        challenge_service.has_user_answered.return_value = False
        update = make_update(111)

        asyncio.run(handler.handle_todays_challenge(update, Mock()))

        sent_text = update.message.reply_text.call_args[0][0]
        assert "Wer war heute Top-Artist?" in sent_text
        assert "Antworten" in sent_text

    def test_shows_already_answered_hint(self):
        handler, _, challenge_service = _make_handler()
        challenge_service.get_or_create_todays_challenge.return_value = (SAMPLE_CHALLENGE, False)
        challenge_service.has_user_answered.return_value = True
        update = make_update(111)

        asyncio.run(handler.handle_todays_challenge(update, Mock()))

        sent_text = update.message.reply_text.call_args[0][0]
        assert "schon geantwortet" in sent_text


class TestHandleAnswerPrompt:
    def test_denied_for_non_member(self):
        handler, _, challenge_service = _make_handler(is_member=False)
        update = make_update(999)

        asyncio.run(handler.handle_answer_prompt(update, Mock()))

        assert 999 not in handler.pending_answers
        challenge_service.get_or_create_todays_challenge.assert_not_called()

    def test_already_answered_blocks_new_prompt(self):
        handler, _, challenge_service = _make_handler()
        challenge_service.get_or_create_todays_challenge.return_value = (SAMPLE_CHALLENGE, False)
        challenge_service.has_user_answered.return_value = True
        update = make_update(111)

        asyncio.run(handler.handle_answer_prompt(update, Mock()))

        assert 111 not in handler.pending_answers
        sent_text = update.message.reply_text.call_args[0][0]
        assert "schon geantwortet" in sent_text

    def test_sets_pending_answer_with_challenge_id(self):
        handler, _, challenge_service = _make_handler()
        challenge_service.get_or_create_todays_challenge.return_value = (SAMPLE_CHALLENGE, True)
        challenge_service.has_user_answered.return_value = False
        update = make_update(111)

        asyncio.run(handler.handle_answer_prompt(update, Mock()))

        assert handler.pending_answers[111] == 1


class TestProcessPendingAnswer:
    def test_removes_pending_state_regardless_of_outcome(self):
        handler, _, challenge_service = _make_handler()
        challenge_service.submit_answer.return_value = {"status": "not_found"}
        handler.pending_answers[111] = 1
        update = make_update(111)

        asyncio.run(handler.process_pending_answer(update, Mock(), "Clueso"))

        assert 111 not in handler.pending_answers

    def test_noop_when_no_pending_challenge_id(self):
        handler, _, challenge_service = _make_handler()
        update = make_update(111)

        asyncio.run(handler.process_pending_answer(update, Mock(), "Clueso"))

        challenge_service.submit_answer.assert_not_called()
        update.message.reply_text.assert_not_called()

    def test_correct_answer_reports_points(self):
        handler, _, challenge_service = _make_handler()
        challenge_service.submit_answer.return_value = {
            "status": "ok", "correct": True, "points": 1, "revealed_answer": "Clueso",
        }
        handler.pending_answers[111] = 1
        update = make_update(111)

        asyncio.run(handler.process_pending_answer(update, Mock(), "Clueso"))

        sent_text = update.message.reply_text.call_args[0][0]
        assert "Richtig" in sent_text
        assert "1 Punkt" in sent_text

    def test_wrong_answer_reveals_correct_one(self):
        handler, _, challenge_service = _make_handler()
        challenge_service.submit_answer.return_value = {
            "status": "ok", "correct": False, "points": 0, "revealed_answer": "Clueso",
        }
        handler.pending_answers[111] = 1
        update = make_update(111)

        asyncio.run(handler.process_pending_answer(update, Mock(), "Falsch"))

        sent_text = update.message.reply_text.call_args[0][0]
        assert "falsch" in sent_text.lower()
        assert "Clueso" in sent_text

    def test_already_answered_status_shows_hint(self):
        handler, _, challenge_service = _make_handler()
        challenge_service.submit_answer.return_value = {"status": "already_answered"}
        handler.pending_answers[111] = 1
        update = make_update(111)

        asyncio.run(handler.process_pending_answer(update, Mock(), "Clueso"))

        sent_text = update.message.reply_text.call_args[0][0]
        assert "schon geantwortet" in sent_text


class TestHandleLeaderboard:
    def test_denied_for_non_member(self):
        handler, _, challenge_service = _make_handler(is_member=False)
        update = make_update(999)

        asyncio.run(handler.handle_leaderboard(update, Mock()))

        challenge_service.get_leaderboard.assert_not_called()

    def test_formats_ranked_leaderboard(self):
        handler, _, challenge_service = _make_handler()
        challenge_service.get_leaderboard.return_value = [
            ("222", "Mama", 3),
            ("111", "Papa", 1),
        ]
        update = make_update(111)

        asyncio.run(handler.handle_leaderboard(update, Mock()))

        sent_text = update.message.reply_text.call_args[0][0]
        assert sent_text.index("Mama") < sent_text.index("Papa")
        assert "3 Punkte" in sent_text
