# tests/test_control_center_logging_startup.py
# -*- coding: utf-8 -*-
"""
D.12a — Logging-Initialisierung des Control-Center-Prozesses.

Vorher: der CC-Prozess (uvicorn control_center.app:app) rief nirgends
setup_enhanced_logging() auf - der Root-Logger hatte keinen Handler, INFO
von YoutubeDownloader/pipeline_core/JobRegistry ging verloren.

Geprüft wird:
- Startup-Event richtet einen Datei-Handler auf LOG_DIR/control_center.log
  ein (NICHT bot.log - kein Zwei-Prozess-Rotieren derselben Datei).
- INFO eines get_module_logger()-Loggers landet in dieser Datei.
- Ohne Startup-Event (httpx.ASGITransport, wie in allen CC-API-Tests)
  bleibt der Root-Logger unverändert.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

import control_center.app as cc_app
from logger import get_module_logger


class _FakeConfig:
    def __init__(self, log_dir: Path):
        self.LOG_DIR = log_dir
        self.LOG_LEVEL = "INFO"


@pytest.fixture
def restore_root_logger():
    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    yield root
    for h in root.handlers[:]:
        if h not in handlers:
            h.close()
        root.removeHandler(h)
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level)


def _file_handlers(root: logging.Logger):
    return [h for h in root.handlers if isinstance(h, logging.FileHandler)]


def test_setup_writes_to_control_center_log_not_bot_log(tmp_path, restore_root_logger):
    cc_app.setup_control_center_logging(_FakeConfig(tmp_path))

    files = [Path(h.baseFilename) for h in _file_handlers(restore_root_logger)]
    assert files == [(tmp_path / "control_center.log").resolve()]
    assert all(f.name != "bot.log" for f in files)


def test_module_logger_info_lands_in_control_center_log(tmp_path, restore_root_logger):
    cc_app.setup_control_center_logging(_FakeConfig(tmp_path))

    get_module_logger("YoutubeDownloader").info("D12A-MARKER download gestartet")
    for h in restore_root_logger.handlers:
        h.flush()

    content = (tmp_path / "control_center.log").read_text(encoding="utf-8")
    assert "D12A-MARKER download gestartet" in content
    assert "[YOUTUBEDOWNLOADER]" in content


@pytest.mark.asyncio
async def test_startup_event_configures_logging(tmp_path, monkeypatch, restore_root_logger):
    monkeypatch.setattr(cc_app, "Config", lambda: _FakeConfig(tmp_path))
    app = cc_app.create_app()

    await app.router.startup()

    files = [Path(h.baseFilename) for h in _file_handlers(restore_root_logger)]
    assert (tmp_path / "control_center.log").resolve() in files


@pytest.mark.asyncio
async def test_asgi_transport_without_lifespan_leaves_root_logger_untouched(
    tmp_path, monkeypatch, restore_root_logger
):
    monkeypatch.setattr(cc_app, "Config", lambda: _FakeConfig(tmp_path))
    before = restore_root_logger.handlers[:]

    transport = httpx.ASGITransport(app=cc_app.create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        await c.get("/api/v1/health")

    assert restore_root_logger.handlers == before
    assert not (tmp_path / "control_center.log").exists()
