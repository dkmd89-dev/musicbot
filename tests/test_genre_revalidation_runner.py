# tests/test_genre_revalidation_runner.py
# -*- coding: utf-8 -*-
"""
services/library_repair/genre_revalidation_runner.py — Subprozess-
Orchestrierung fuer scripts/revalidate_genre.py (Chat-Charakterisierung
2026-09-15). Testmuster identisch zu tests/test_duplicate_runner.py: ein
simulierter, aber realistischer Subprozess schreibt die JSON-Ergebnisdatei,
der eigentliche Subprozess wird nie wirklich gestartet.
"""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

import services.library_repair.genre_revalidation_runner as runner_module

SAMPLE_RESULT_JSON = json.dumps({
    "artist": "Bausa", "outcome": "OVERTURN_ALLOWED", "reason": "ok",
    "manual_mapping_protected": False, "current_primary": "Rock",
    "current_secondary": [], "candidate_primary": "Pop", "candidate_secondary": [],
    "candidate_source": "lastfm", "learning_status": "CONFIRMED",
    "locked_primary": "Pop", "observation_count": 9, "mutated": False,
    "error_message": None,
})


def _fake_subprocess_writing_json(json_text: str, returncode: int = 0):
    async def fake_create_subprocess_exec(*cmd, **kwargs):
        runner_module._json_path().parent.mkdir(parents=True, exist_ok=True)
        runner_module._json_path().write_text(json_text, encoding="utf-8")
        fake_proc = Mock()
        fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        fake_proc.returncode = returncode
        return fake_proc
    return fake_create_subprocess_exec


class TestRunGenreRevalidationSubprocessCommand:
    @pytest.mark.asyncio
    async def test_command_includes_artist_and_json(self, tmp_path):
        captured = {}

        async def fake_exec(*cmd, **kwargs):
            captured["cmd"] = cmd
            runner_module._json_path().parent.mkdir(parents=True, exist_ok=True)
            runner_module._json_path().write_text(SAMPLE_RESULT_JSON, encoding="utf-8")
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch.object(runner_module.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=fake_exec):
            await runner_module.run_genre_revalidation_subprocess("Bausa", apply=False)

        cmd = captured["cmd"]
        assert "--artist" in cmd and "Bausa" in cmd
        assert "--json" in cmd
        assert "--apply" not in cmd

    @pytest.mark.asyncio
    async def test_apply_true_adds_apply_flag(self, tmp_path):
        captured = {}

        async def fake_exec(*cmd, **kwargs):
            captured["cmd"] = cmd
            runner_module._json_path().parent.mkdir(parents=True, exist_ok=True)
            runner_module._json_path().write_text(SAMPLE_RESULT_JSON, encoding="utf-8")
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch.object(runner_module.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=fake_exec):
            await runner_module.run_genre_revalidation_subprocess("Bausa", apply=True)

        assert "--apply" in captured["cmd"]


class TestRunGenreRevalidationSubprocessSimulatedSuccess:
    @pytest.mark.asyncio
    async def test_parses_json_result(self, tmp_path):
        with patch.object(runner_module.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec",
                   new=_fake_subprocess_writing_json(SAMPLE_RESULT_JSON)):
            result = await runner_module.run_genre_revalidation_subprocess("Bausa", apply=False)

        assert result.success
        assert result.outcome == "OVERTURN_ALLOWED"
        assert result.mutated is False
        assert result.data["candidate_primary"] == "Pop"

    @pytest.mark.asyncio
    async def test_exit_code_1_with_error_message_still_parses(self, tmp_path):
        error_json = json.dumps({**json.loads(SAMPLE_RESULT_JSON), "error_message": "lastfm down"})
        with patch.object(runner_module.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec",
                   new=_fake_subprocess_writing_json(error_json, returncode=1)):
            result = await runner_module.run_genre_revalidation_subprocess("Bausa", apply=False)

        assert result.success  # exit_code 1 zaehlt als "hat Ergebnis geliefert"
        assert result.data["error_message"] == "lastfm down"

    @pytest.mark.asyncio
    async def test_unexpected_exit_code_is_not_success(self, tmp_path):
        fake_proc = Mock()
        fake_proc.communicate = AsyncMock(return_value=(b"", b"boom"))
        fake_proc.returncode = 3

        with patch.object(runner_module.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            result = await runner_module.run_genre_revalidation_subprocess("Bausa", apply=False)

        assert not result.success
        assert result.data is None

    @pytest.mark.asyncio
    async def test_corrupt_json_does_not_raise(self, tmp_path):
        with patch.object(runner_module.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec",
                   new=_fake_subprocess_writing_json("{not valid json")):
            result = await runner_module.run_genre_revalidation_subprocess("Bausa", apply=False)

        assert result.data is None
        assert not result.success


class TestRunGenreRevalidationSubprocessMockedFailures:
    @pytest.mark.asyncio
    async def test_subprocess_start_failure(self, tmp_path):
        with patch.object(runner_module.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec",
                   new=AsyncMock(side_effect=OSError("no such file"))):
            result = await runner_module.run_genre_revalidation_subprocess("Bausa", apply=False)

        assert result.exit_code is None
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_lock_released_after_run(self, tmp_path):
        with patch.object(runner_module.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec",
                   new=_fake_subprocess_writing_json(SAMPLE_RESULT_JSON)):
            await runner_module.run_genre_revalidation_subprocess("Bausa", apply=False)

        from services.library_repair.run_tracking import is_repair_running
        with patch.object(runner_module.Config, "DATA_DIR", tmp_path):
            assert is_repair_running() is False

    @pytest.mark.asyncio
    async def test_lock_released_even_on_failure(self, tmp_path):
        fake_proc = Mock()
        fake_proc.communicate = AsyncMock(return_value=(b"", b"boom"))
        fake_proc.returncode = 3

        with patch.object(runner_module.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            await runner_module.run_genre_revalidation_subprocess("Bausa", apply=False)

        from services.library_repair.run_tracking import is_repair_running
        with patch.object(runner_module.Config, "DATA_DIR", tmp_path):
            assert is_repair_running() is False
