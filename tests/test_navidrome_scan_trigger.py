"""
Charakterisierungstests fuer utils/navidrome_scan_trigger.py.

ARCH-009 Phase 4: die Docker-/Subprocess-/Timeout-Steuerung wurde 1:1 aus
NavidromeAPI.execute_scan() in NavidromeScanTrigger.run_scan() ausgelagert
(siehe docs/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md). Diese Tests
sind die direkte Fortsetzung der vorher in
tests/test_navidrome_api_characterization.py::TestExecuteScan enthaltenen
Subprocess-Charakterisierung. Die Telegram-Formatierung liegt seit
ARCH-009 Phase 9 (Umsetzung A) direkt im Handler
(handlers/menu/rich_menu_handler.py), nicht mehr in einer eigenen
execute_scan()-Bridge.

ARCH-009-Folgeumsetzung (2026-08-24): NavidromeScanTrigger wurde von
api/navidrome_scan_trigger.py nach utils/navidrome_scan_trigger.py
verschoben (siehe
docs/MusicBot_ARCH-009_NavidromeScanTrigger_Zielort_Analyse.md) - Import
und alle Patch-Ziele entsprechend auf utils.navidrome_scan_trigger
umgestellt. api/ existiert seitdem nicht mehr.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from utils.navidrome_scan_trigger import NavidromeScanTrigger, ScanTimeoutError


class TestRunScan:
    def test_success_returns_result_with_decoded_stdout(self):
        fake_process = AsyncMock()
        fake_process.communicate.return_value = (b"Scan complete", b"")
        fake_process.returncode = 0
        fake_process.pid = 1234

        with patch(
            "utils.navidrome_scan_trigger.asyncio.create_subprocess_shell",
            return_value=fake_process,
        ):
            result = asyncio.run(NavidromeScanTrigger.run_scan())

        assert result.success is True
        assert result.returncode == 0
        assert result.stdout == "Scan complete"
        assert result.stderr == ""

    def test_nonzero_returncode_returns_failed_result_with_stderr(self):
        fake_process = AsyncMock()
        fake_process.communicate.return_value = (b"", b"boom")
        fake_process.returncode = 1
        fake_process.pid = 1234

        with patch(
            "utils.navidrome_scan_trigger.asyncio.create_subprocess_shell",
            return_value=fake_process,
        ):
            result = asyncio.run(NavidromeScanTrigger.run_scan())

        assert result.success is False
        assert result.returncode == 1
        assert result.stderr == "boom"

    def test_timeout_raises_scan_timeout_error_with_configured_seconds(self):
        async def never_completes(*args, **kwargs):
            await asyncio.sleep(9999)

        fake_process = AsyncMock()
        fake_process.communicate.side_effect = never_completes
        fake_process.pid = 1234

        with patch(
            "utils.navidrome_scan_trigger.asyncio.create_subprocess_shell",
            return_value=fake_process,
        ), patch(
            "utils.navidrome_scan_trigger._get_scan_config"
        ) as mock_cfg, patch(
            "utils.navidrome_scan_trigger.Config"
        ) as mock_config_cls:
            mock_cfg.return_value.NAVIDROME_SCAN_COMMAND = "echo test"
            mock_config_cls.NAVIDROME_SCAN_COMMAND = "echo test"
            mock_config_cls.NAVIDROME_SCAN_TIMEOUT = 0.01

            with pytest.raises(ScanTimeoutError) as exc_info:
                asyncio.run(NavidromeScanTrigger.run_scan())

        assert exc_info.value.timeout_seconds == 0.01

    def test_missing_scan_command_raises_attribute_error(self):
        with patch("utils.navidrome_scan_trigger._get_scan_config") as mock_cfg:
            mock_cfg.return_value.NAVIDROME_SCAN_COMMAND = ""

            with pytest.raises(AttributeError):
                asyncio.run(NavidromeScanTrigger.run_scan())

    def test_list_command_is_joined_into_string(self):
        fake_process = AsyncMock()
        fake_process.communicate.return_value = (b"ok", b"")
        fake_process.returncode = 0
        fake_process.pid = 1234

        with patch(
            "utils.navidrome_scan_trigger.asyncio.create_subprocess_shell",
            return_value=fake_process,
        ) as mock_shell, patch(
            "utils.navidrome_scan_trigger._get_scan_config"
        ) as mock_cfg:
            mock_cfg.return_value.NAVIDROME_SCAN_COMMAND = [
                "docker",
                "exec",
                "navidrome",
                "scan",
            ]
            result = asyncio.run(NavidromeScanTrigger.run_scan())

        assert result.success is True
        mock_shell.assert_called_once_with(
            "docker exec navidrome scan",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
