"""
Unit-Tests für BotRestartTrigger (utils/bot_restart_trigger.py).

POST-ARCH-009 P-1: 1:1 aus BotRestartHandler._trigger_restart() extrahiert
(vorher tests/test_bot_restart_handler.py::TestTriggerRestart), siehe
docs/archive/post-arch/MusicBot_POST-ARCH-009_P1_BotRestart_Analyse.md.

WICHTIG (Regel 7): trigger_restart() ruft echtes subprocess.run(["sudo",
"systemctl", "restart", ...]) auf, das den laufenden Produktions-Bot
tatsaechlich neu starten wuerde. subprocess.run wird in JEDEM Test dieser
Datei gemockt - niemals echt ausgefuehrt.
"""

import subprocess
from unittest.mock import patch

from utils.bot_restart_trigger import BotRestartTrigger


class TestTriggerRestart:
    def test_success_logs_info_without_raising(self):
        completed = subprocess.CompletedProcess(
            args=["sudo", "systemctl", "restart", "bot"], returncode=0, stdout="ok", stderr=""
        )
        with patch("subprocess.run", return_value=completed) as mock_run, patch(
            "utils.bot_restart_trigger.logger"
        ) as mock_logger:
            BotRestartTrigger.trigger_restart("bot")

        mock_run.assert_called_once_with(
            ["sudo", "systemctl", "restart", "bot"],
            check=True,
            timeout=15,
            capture_output=True,
            text=True,
        )
        mock_logger.info.assert_called_once_with(
            "✅ systemctl restart abgeschlossen: %s", "ok"
        )

    def test_called_process_error_is_caught_and_logged(self):
        error = subprocess.CalledProcessError(
            returncode=1, cmd="systemctl", stderr="permission denied"
        )
        with patch("subprocess.run", side_effect=error), patch(
            "utils.bot_restart_trigger.logger"
        ) as mock_logger:
            BotRestartTrigger.trigger_restart("bot")  # darf nicht raisen

        mock_logger.error.assert_called_once()

    def test_missing_sudo_binary_is_caught_and_logged(self):
        with patch(
            "subprocess.run", side_effect=FileNotFoundError("sudo not found")
        ), patch("utils.bot_restart_trigger.logger") as mock_logger:
            BotRestartTrigger.trigger_restart("bot")

        mock_logger.error.assert_called_once()

    def test_unexpected_exception_is_caught_and_logged(self):
        with patch("subprocess.run", side_effect=RuntimeError("boom")), patch(
            "utils.bot_restart_trigger.logger"
        ) as mock_logger:
            BotRestartTrigger.trigger_restart("bot")

        mock_logger.error.assert_called_once()

    def test_uses_given_service_name(self):
        completed = subprocess.CompletedProcess(
            args=["sudo", "systemctl", "restart", "custom-service"],
            returncode=0,
            stdout="",
            stderr="",
        )
        with patch("subprocess.run", return_value=completed) as mock_run, patch(
            "utils.bot_restart_trigger.logger"
        ):
            BotRestartTrigger.trigger_restart("custom-service")

        mock_run.assert_called_once_with(
            ["sudo", "systemctl", "restart", "custom-service"],
            check=True,
            timeout=15,
            capture_output=True,
            text=True,
        )
