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
    FindingsRegistryError,
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


class TestIsAdminDirect:
    """ARCH-023/P-7: direkte Charakterisierung von _is_admin() selbst
    (bisher nur indirekt ueber die 11 Aufrufstellen getestet) - Baseline
    vor der Umstellung auf permissions.is_admin_or_owner()."""

    def test_owner_is_admin(self, handler):
        assert handler._is_admin(OWNER_ID) is True

    def test_configured_admin_is_admin(self, handler):
        assert handler._is_admin(ADMIN_ID) is True

    def test_other_user_is_not_admin(self, handler):
        assert handler._is_admin(OTHER_ID) is False


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

    def test_corrupt_registry_is_reported_to_injected_error_handler(
        self, handler, registry_path, context
    ):
        """ARCH-027/F6: der injizierte error_handler wurde vorher nie
        aufgerufen. _load_registry() ist bewusst synchron (11 Aufrufer) -
        die Meldung erfolgt per asyncio.create_task() (fire-and-forget),
        daher wird hier auf den synchronen Aufruf (assert_called_once())
        geprueft statt auf assert_awaited_once() (timing-unabhaengig,
        siehe Kommentar in library_health_review_handler.py)."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text("{not valid json", encoding="utf-8")
        handler.error_handler = Mock()
        handler.error_handler.handle_exception = AsyncMock()

        update = _mock_update(ADMIN_ID)
        run(handler.handle_start(update, context))

        handler.error_handler.handle_exception.assert_called_once()
        call_args = handler.error_handler.handle_exception.call_args
        assert isinstance(call_args.args[0], FindingsRegistryError)
        assert call_args.kwargs["context"]["module"] == "LibraryHealthReviewHandler"
        assert call_args.kwargs["context"]["operation"] == "load_registry"

    def test_corrupt_registry_without_error_handler_still_works(
        self, handler, registry_path, context
    ):
        """Rueckwaertskompatibilitaet: handler.error_handler bleibt bei
        Standalone-Konstruktion None."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text("{not valid json", encoding="utf-8")
        assert handler.error_handler is None

        update = _mock_update(ADMIN_ID)
        run(handler.handle_start(update, context))

        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "ungültig" in text


# ─────────────────────────────────────────────────────────────────────────
# Akzeptierte Findings + Unaccept (Library-Closure-Phase)
# ─────────────────────────────────────────────────────────────────────────

from services.library_health.findings import (  # noqa: E402
    accept_finding,
    get_accepted_findings,
)


class TestAcceptedFindings:
    def _seed_with_accepted(self, registry_path):
        a = _issue("ARTWORK_MISSING", scope="file", path="A/Alb/01.m4a")
        b = _issue("LYRICS_MISSING", scope="file", path="A/Alb/02.m4a")
        c = _issue("ALBUM_TRACK_GAP", scope="album", artist="X", album="Y")
        registry = _seed(registry_path, [a, b, c])
        accept_finding(registry, generate_finding_id(a), reason="kein Cover verfügbar")
        accept_finding(registry, generate_finding_id(c), reason="kuratierte Auswahl")
        registry.save()
        return registry, generate_finding_id(a), generate_finding_id(b), generate_finding_id(c)

    def test_overview_shows_accepted_entry_point(self, handler, registry_path, context):
        self._seed_with_accepted(registry_path)
        update = _mock_update(ADMIN_ID)
        run(handler.handle_start(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        assert "Akzeptiert (2)" in text
        cbs = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "review:accepted" in cbs

    def test_overview_hides_accepted_entry_point_when_none(
        self, handler, registry_path, context
    ):
        _seed(registry_path, [_issue("ARTWORK_MISSING", scope="file", path="a.m4a")])
        update = _mock_update(ADMIN_ID)
        run(handler.handle_start(update, context))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        cbs = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "review:accepted" not in cbs

    def test_accepted_list_groups_by_code(self, handler, registry_path, context):
        self._seed_with_accepted(registry_path)
        update = _mock_update(ADMIN_ID)
        run(handler.handle_accepted_list(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        assert "2 gesamt · 2 Kategorie(n)" in text
        cbs = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "review:acccode:ARTWORK_MISSING" in cbs
        assert "review:acccode:ALBUM_TRACK_GAP" in cbs

    def test_accepted_list_empty(self, handler, registry_path, context):
        _seed(registry_path, [_issue("ARTWORK_MISSING", scope="file", path="a.m4a")])
        update = _mock_update(ADMIN_ID)
        run(handler.handle_accepted_list(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Keine akzeptierten Befunde" in text

    def test_accepted_category_lists_findings_with_show_callback(
        self, handler, registry_path, context
    ):
        _, fid_a, _, _ = self._seed_with_accepted(registry_path)
        update = _mock_update(ADMIN_ID)
        run(handler.handle_accepted_category(update, context, "ARTWORK_MISSING"))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        cbs = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert f"review:accshow:{fid_a}" in cbs

    def test_accepted_show_has_unaccept_button_and_reason(
        self, handler, registry_path, context
    ):
        _, fid_a, _, _ = self._seed_with_accepted(registry_path)
        update = _mock_update(ADMIN_ID)
        run(handler.handle_accepted_show(update, context, fid_a))
        text = update.callback_query.edit_message_text.call_args.args[0]
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        assert "kein Cover verfügbar" in text
        cbs = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert f"review:unaccept:{fid_a}" in cbs

    def test_show_rejects_non_accepted_finding(self, handler, registry_path, context):
        _, _, fid_b, _ = self._seed_with_accepted(registry_path)  # b ist OPEN
        update = _mock_update(ADMIN_ID)
        run(handler.handle_accepted_show(update, context, fid_b))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "nicht mehr akzeptiert" in text

    def test_unaccept_reactivates_and_persists(self, handler, registry_path, context):
        _, fid_a, _, _ = self._seed_with_accepted(registry_path)
        update = _mock_update(ADMIN_ID)
        run(handler.handle_unaccept(update, context, fid_a))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "reaktiviert" in text
        assert FindingsRegistry(registry_path).get(fid_a).status == STATUS_OPEN

    def test_unaccept_stale_finding_is_a_noop(self, handler, registry_path, context):
        _, _, fid_b, _ = self._seed_with_accepted(registry_path)  # b ist OPEN, nie akzeptiert
        update = _mock_update(ADMIN_ID)
        run(handler.handle_unaccept(update, context, fid_b))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "nicht mehr akzeptiert" in text
        assert FindingsRegistry(registry_path).get(fid_b).status == STATUS_OPEN

    def test_all_accepted_endpoints_reject_non_admin(self, handler, registry_path, context):
        _, fid_a, _, _ = self._seed_with_accepted(registry_path)
        for coro in (
            handler.handle_accepted_list(_mock_update(OTHER_ID), context),
            handler.handle_accepted_category(_mock_update(OTHER_ID), context, "ARTWORK_MISSING"),
            handler.handle_accepted_show(_mock_update(OTHER_ID), context, fid_a),
            handler.handle_unaccept(_mock_update(OTHER_ID), context, fid_a),
        ):
            u = _mock_update(OTHER_ID)
            run(coro)
        # der akzeptierte Befund bleibt akzeptiert
        assert FindingsRegistry(registry_path).get(fid_a).status == STATUS_FALSE_POSITIVE

    def test_stale_accepted_finding_marked_in_category_list(
        self, handler, registry_path, context
    ):
        a = _issue("ARTWORK_MISSING", scope="file", path="A/Alb/01.m4a")
        registry = _seed(registry_path, [a])
        accept_finding(registry, generate_finding_id(a), reason="x")
        registry.save()
        # naechster Scan sieht das Issue nicht mehr -> present_in_latest_scan=False
        registry.merge_scan_issues([], scanned_at="2026-02-01T00:00:00Z")
        registry.save()

        update = _mock_update(ADMIN_ID)
        run(handler.handle_accepted_category(update, context, "ARTWORK_MISSING"))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        labels = [b.text for row in keyboard.inline_keyboard for b in row]
        assert any("⚠️" in lbl for lbl in labels)
