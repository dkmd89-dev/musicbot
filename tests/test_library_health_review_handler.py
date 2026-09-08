# tests/test_library_health_review_handler.py
# -*- coding: utf-8 -*-
"""
handlers/library_health_review_handler.py — echte Handler-/Renderlogik
(Severity-Auswahl, Kategorie-Auswahl, Einzelreview, Batch-False-Positive,
Stale-Callback-Absicherung). Verwendet dieselbe zentrale
FindingsRegistry-API wie scripts/library_health_review.py (siehe
tests/test_library_health_review_cli.py für die CLI-Variante).
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.library_health_review_handler import LibraryHealthReviewHandler
from services.library_health.findings import (
    DEFAULT_FILENAME,
    STATUS_FALSE_POSITIVE,
    STATUS_OPEN,
    STATUS_RESOLVED,
    FindingsRegistry,
    generate_finding_id,
)


class FakeConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [67890]


OWNER_ID = 12345
ADMIN_ID = 67890
OTHER_ID = 999


def _issue(code, severity="WARNING", scope="album", **kwargs):
    base = {
        "issue_code": code, "severity": severity, "scope": scope, "path": None,
        "artist": None, "album": None, "title": None, "message": f"msg {code}",
        "details": {}, "confidence": None, "related_files": [],
    }
    base.update(kwargs)
    return base


@pytest.fixture
def config(tmp_path):
    cfg = FakeConfig()
    cfg.DATA_DIR = str(tmp_path)
    return cfg


@pytest.fixture
def handler(config):
    return LibraryHealthReviewHandler(config, logger_factory=lambda name: Mock())


@pytest.fixture
def registry_path(config):
    return Path(config.DATA_DIR) / DEFAULT_FILENAME


def _mock_update(user_id):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


@pytest.fixture
def context():
    ctx = Mock()
    ctx.user_data = {}
    return ctx


def run(coro):
    return asyncio.run(coro)


def _seed(registry_path, issues, scanned_at="2026-01-01T00:00:00Z"):
    registry = FindingsRegistry(registry_path)
    registry.merge_scan_issues(issues, scanned_at=scanned_at)
    registry.save()
    return registry


class TestHandleStart:
    def test_no_status_change_on_open(self, handler, registry_path, context):
        issue = _issue("ARTWORK_MISSING", scope="file", path="a.m4a")
        _seed(registry_path, [issue])
        before = registry_path.read_text(encoding="utf-8")

        update = _mock_update(ADMIN_ID)
        run(handler.handle_start(update, context))

        assert registry_path.read_text(encoding="utf-8") == before

    def test_shows_dynamic_open_count_and_severity_distribution(
        self, handler, registry_path, context
    ):
        issues = [
            _issue("AUDIO_NO_STREAM", "CRITICAL", scope="file", path="c.m4a"),
            _issue("ARTWORK_MISSING", "WARNING", scope="file", path="w.m4a"),
            _issue("ARTWORK_MISSING", "WARNING", scope="file", path="w2.m4a"),
        ]
        _seed(registry_path, issues)

        update = _mock_update(ADMIN_ID)
        run(handler.handle_start(update, context))

        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Offene Befunde: 3" in text
        assert "Kategorien: 2" in text
        assert "CRITICAL (1)" in text
        assert "WARNING (2)" in text

    def test_non_admin_rejected(self, handler, registry_path, context):
        _seed(registry_path, [_issue("ARTWORK_MISSING", scope="file", path="a.m4a")])
        update = _mock_update(OTHER_ID)
        run(handler.handle_start(update, context))
        update.callback_query.answer.assert_called_with(
            "⛔ Nur Admins dürfen Findings prüfen", show_alert=True
        )
        update.callback_query.edit_message_text.assert_not_called()

    def test_empty_registry_shows_all_clear(self, handler, registry_path, context):
        FindingsRegistry(registry_path).save()
        update = _mock_update(ADMIN_ID)
        run(handler.handle_start(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Keine offenen Befunde" in text

    def test_severities_without_open_findings_get_no_button(
        self, handler, registry_path, context
    ):
        _seed(registry_path, [_issue("ARTWORK_MISSING", "WARNING", scope="file", path="w.m4a")])
        update = _mock_update(ADMIN_ID)
        run(handler.handle_start(update, context))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "review:severity:WARNING" in callback_datas
        assert "review:severity:CRITICAL" not in callback_datas
        assert "review:severity:INFO" not in callback_datas


class TestHandleSeverityAndCategory:
    def test_severity_lists_categories_with_dynamic_counts(
        self, handler, registry_path, context
    ):
        issues = [
            _issue("ARTWORK_MISSING", "WARNING", scope="file", path=f"w{i}.m4a")
            for i in range(4)
        ] + [_issue("LYRICS_EMPTY", "WARNING", scope="file", path="l.m4a")]
        _seed(registry_path, issues)

        update = _mock_update(ADMIN_ID)
        run(handler.handle_severity(update, context, "WARNING"))

        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        labels = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert "ARTWORK_MISSING · 4" in labels
        assert "LYRICS_EMPTY · 1" in labels

    def test_fully_handled_category_disappears_from_severity_list(
        self, handler, registry_path, context
    ):
        issue = _issue("ARTWORK_MISSING", "WARNING", scope="file", path="w.m4a")
        registry = _seed(registry_path, [issue])
        registry.review_finding(generate_finding_id(issue), STATUS_RESOLVED)
        registry.save()

        update = _mock_update(ADMIN_ID)
        run(handler.handle_severity(update, context, "WARNING"))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Keine offenen Kategorien" in text

    def test_category_actions_shown(self, handler, registry_path, context):
        _seed(registry_path, [
            _issue("ARTWORK_MISSING", "WARNING", scope="file", path="w.m4a")
        ])
        update = _mock_update(ADMIN_ID)
        run(handler.handle_category(update, context, "ARTWORK_MISSING"))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "review:edit:ARTWORK_MISSING" in callback_datas
        assert "review:batchconfirm:ARTWORK_MISSING" in callback_datas

    def test_category_gone_shows_refresh_prompt(self, handler, registry_path, context):
        issue = _issue("ARTWORK_MISSING", "WARNING", scope="file", path="w.m4a")
        registry = _seed(registry_path, [issue])
        registry.review_finding(generate_finding_id(issue), STATUS_FALSE_POSITIVE)
        registry.save()

        update = _mock_update(ADMIN_ID)
        run(handler.handle_category(update, context, "ARTWORK_MISSING"))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "keine offenen Befunde mehr" in text


class TestSingleReview:
    def test_edit_start_shows_first_finding(self, handler, registry_path, context):
        issue = _issue(
            "ALBUM_TRACK_GAP", "WARNING", artist="2Pac", album="Test Album",
        )
        _seed(registry_path, [issue])

        update = _mock_update(ADMIN_ID)
        run(handler.handle_edit_start(update, context, "ALBUM_TRACK_GAP"))

        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "2Pac / Test Album" in text
        assert "Befund 1/1" in text
        assert context.user_data["health_review"] == {"code": "ALBUM_TRACK_GAP", "position": 0}

    def test_resolve_action_persists_and_advances(self, handler, registry_path, context):
        issues = [
            _issue("ARTWORK_MISSING", "WARNING", scope="file", path="a.m4a"),
            _issue("ARTWORK_MISSING", "WARNING", scope="file", path="b.m4a"),
        ]
        _seed(registry_path, issues)
        update = _mock_update(ADMIN_ID)
        run(handler.handle_edit_start(update, context, "ARTWORK_MISSING"))

        fid_first = generate_finding_id(issues[0])
        run(handler.handle_single_action(update, context, "resolve", fid_first))

        registry = FindingsRegistry(registry_path)
        assert registry.get(fid_first).status == STATUS_RESOLVED
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Befund 1/1" in text  # zweites Finding rueckt nach

    def test_false_positive_action_persists(self, handler, registry_path, context):
        issue = _issue("ARTWORK_MISSING", "WARNING", scope="file", path="a.m4a")
        _seed(registry_path, [issue])
        update = _mock_update(ADMIN_ID)
        run(handler.handle_edit_start(update, context, "ARTWORK_MISSING"))

        fid = generate_finding_id(issue)
        run(handler.handle_single_action(update, context, "fp", fid))

        registry = FindingsRegistry(registry_path)
        assert registry.get(fid).status == STATUS_FALSE_POSITIVE
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "abgeschlossen" in text

    def test_skip_action_does_not_change_status(self, handler, registry_path, context):
        issues = [
            _issue("ARTWORK_MISSING", "WARNING", scope="file", path="a.m4a"),
            _issue("ARTWORK_MISSING", "WARNING", scope="file", path="b.m4a"),
        ]
        _seed(registry_path, issues)
        update = _mock_update(ADMIN_ID)
        run(handler.handle_edit_start(update, context, "ARTWORK_MISSING"))

        fid_first = generate_finding_id(issues[0])
        run(handler.handle_single_action(update, context, "skip", fid_first))

        registry = FindingsRegistry(registry_path)
        assert registry.get(fid_first).status == STATUS_OPEN
        assert registry.get(generate_finding_id(issues[1])).status == STATUS_OPEN

    def test_quit_action_ends_session_without_changes(self, handler, registry_path, context):
        issue = _issue("ARTWORK_MISSING", "WARNING", scope="file", path="a.m4a")
        _seed(registry_path, [issue])
        update = _mock_update(ADMIN_ID)
        run(handler.handle_edit_start(update, context, "ARTWORK_MISSING"))

        fid = generate_finding_id(issue)
        run(handler.handle_single_action(update, context, "quit", fid))

        assert "health_review" not in context.user_data
        registry = FindingsRegistry(registry_path)
        assert registry.get(fid).status == STATUS_OPEN
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "beendet" in text

    def test_stale_finding_id_rejected(self, handler, registry_path, context):
        """Abschnitt 24: ein Finding, das zwischenzeitlich bereits
        bewertet wurde (z.B. durch einen zweiten Admin), darf durch einen
        veralteten Button nicht erneut geaendert werden."""
        issue = _issue("ARTWORK_MISSING", "WARNING", scope="file", path="a.m4a")
        _seed(registry_path, [issue])
        update = _mock_update(ADMIN_ID)
        run(handler.handle_edit_start(update, context, "ARTWORK_MISSING"))

        fid = generate_finding_id(issue)
        # Simuliert eine zwischenzeitliche Aenderung durch einen anderen Prozess.
        registry = FindingsRegistry(registry_path)
        registry.review_finding(fid, STATUS_RESOLVED)
        registry.save()

        run(handler.handle_single_action(update, context, "fp", fid))

        # Status bleibt RESOLVED - der stale Callback (fp) darf ihn NICHT
        # auf FALSE_POSITIVE zurückgesetzt haben.
        reloaded = FindingsRegistry(registry_path)
        assert reloaded.get(fid).status == STATUS_RESOLVED
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "nicht mehr verfügbar" in text

    def test_stale_finding_not_found_rejected(self, handler, registry_path, context):
        issue = _issue("ARTWORK_MISSING", "WARNING", scope="file", path="a.m4a")
        _seed(registry_path, [issue])
        update = _mock_update(ADMIN_ID)
        run(handler.handle_edit_start(update, context, "ARTWORK_MISSING"))

        run(handler.handle_single_action(update, context, "resolve", "does-not-exist"))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "nicht mehr verfügbar" in text

    def test_non_admin_rejected_on_single_action(self, handler, registry_path, context):
        issue = _issue("ARTWORK_MISSING", "WARNING", scope="file", path="a.m4a")
        _seed(registry_path, [issue])
        update = _mock_update(OTHER_ID)
        fid = generate_finding_id(issue)
        run(handler.handle_single_action(update, context, "resolve", fid))
        registry = FindingsRegistry(registry_path)
        assert registry.get(fid).status == STATUS_OPEN


class TestBatchFalsePositive:
    def test_confirm_prompt_shows_count_and_requires_explicit_confirmation(
        self, handler, registry_path, context
    ):
        issues = [
            _issue("META_ISRC_MISSING", "INFO", scope="file", path=f"f{i}.m4a")
            for i in range(288)
        ]
        _seed(registry_path, issues)

        update = _mock_update(ADMIN_ID)
        run(handler.handle_batch_confirm_prompt(update, context, "META_ISRC_MISSING"))

        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "288" in text
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "review:batchyes:META_ISRC_MISSING" in callback_datas

        # Reines Anzeigen der Bestaetigung aendert noch nichts.
        registry = FindingsRegistry(registry_path)
        assert len(registry.get_open_findings()) == 288

    def test_confirmed_batch_marks_all_open_as_false_positive(
        self, handler, registry_path, context
    ):
        issues = [
            _issue("META_ISRC_MISSING", "INFO", scope="file", path=f"f{i}.m4a")
            for i in range(288)
        ]
        _seed(registry_path, issues)

        update = _mock_update(ADMIN_ID)
        run(handler.handle_batch_confirmed(update, context, "META_ISRC_MISSING"))

        registry = FindingsRegistry(registry_path)
        for issue in issues:
            assert registry.get(generate_finding_id(issue)).status == STATUS_FALSE_POSITIVE
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "288 Findings als FALSE_POSITIVE markiert" in text

    def test_batch_does_not_affect_other_categories(self, handler, registry_path, context):
        artwork_issue = _issue("ARTWORK_MISSING", "WARNING", scope="file", path="a.m4a")
        isrc_issue = _issue("META_ISRC_MISSING", "INFO", scope="file", path="b.m4a")
        _seed(registry_path, [artwork_issue, isrc_issue])

        update = _mock_update(ADMIN_ID)
        run(handler.handle_batch_confirmed(update, context, "META_ISRC_MISSING"))

        registry = FindingsRegistry(registry_path)
        assert registry.get(generate_finding_id(artwork_issue)).status == STATUS_OPEN

    def test_batch_on_already_gone_category_shows_refresh(
        self, handler, registry_path, context
    ):
        issue = _issue("ARTWORK_MISSING", "WARNING", scope="file", path="a.m4a")
        registry = _seed(registry_path, [issue])
        registry.review_finding(generate_finding_id(issue), STATUS_RESOLVED)
        registry.save()

        update = _mock_update(ADMIN_ID)
        run(handler.handle_batch_confirmed(update, context, "ARTWORK_MISSING"))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "keine offenen Befunde mehr" in text

    def test_non_admin_rejected_on_batch_confirmed(self, handler, registry_path, context):
        issue = _issue("ARTWORK_MISSING", "WARNING", scope="file", path="a.m4a")
        _seed(registry_path, [issue])
        update = _mock_update(OTHER_ID)
        run(handler.handle_batch_confirmed(update, context, "ARTWORK_MISSING"))
        registry = FindingsRegistry(registry_path)
        assert registry.get(generate_finding_id(issue)).status == STATUS_OPEN


class TestCorruptRegistry:
    def test_corrupt_registry_shows_error_and_is_not_overwritten(
        self, handler, registry_path, context
    ):
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text("{not valid json", encoding="utf-8")

        update = _mock_update(ADMIN_ID)
        run(handler.handle_start(update, context))

        assert registry_path.read_text(encoding="utf-8") == "{not valid json"
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "ungültig" in text
