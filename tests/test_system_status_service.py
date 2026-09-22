# tests/test_system_status_service.py
# -*- coding: utf-8 -*-
"""
CC-AC-10D: gezielte Tests für services/system_status.py.

get_host_resources() ruft echtes psutil auf dieser Maschine auf (kein
Mock nötig/sinnvoll — es ist genau die reale Host-Metrik, die geliefert
werden soll, kein externer Dienst im Sinne von CLAUDE.md §8).
get_bot_service_active() wird gegen subprocess.run gemockt (externer
Prozessaufruf).
"""

from __future__ import annotations

import subprocess
from unittest.mock import Mock, patch

from services import system_status


class TestGetHostResources:
    def test_returns_plausible_values(self, tmp_path):
        resources = system_status.get_host_resources(str(tmp_path))

        assert 0 <= resources.cpu_percent <= 100
        assert resources.cpu_count >= 1
        assert 0 <= resources.memory_percent <= 100
        assert resources.memory_total_mb > 0
        assert resources.memory_used_mb <= resources.memory_total_mb + 1  # Rundung
        assert 0 <= resources.disk_percent <= 100
        assert resources.disk_total_gb > 0


class TestGetBotServiceActive:
    def test_returns_true_when_active(self):
        fake_result = Mock(stdout="active\n")
        with patch("subprocess.run", return_value=fake_result) as mock_run:
            result = system_status.get_bot_service_active("bot")

        assert result is True
        mock_run.assert_called_once()
        assert mock_run.call_args.args[0] == ["systemctl", "is-active", "bot"]

    def test_returns_false_when_inactive(self):
        fake_result = Mock(stdout="inactive\n")
        with patch("subprocess.run", return_value=fake_result):
            result = system_status.get_bot_service_active("bot")

        assert result is False

    def test_returns_none_when_systemctl_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = system_status.get_bot_service_active("bot")

        assert result is None

    def test_returns_none_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="systemctl", timeout=5)):
            result = system_status.get_bot_service_active("bot")

        assert result is None
