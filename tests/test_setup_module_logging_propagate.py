# -*- coding: utf-8 -*-
"""D.12b.1: Regression fuer den neuen `propagate`-Parameter in
logger.py::setup_module_logging(). Default False = alte Semantik,
explizites propagate=True schaltet die Weitergabe zum Root ein.

Bewusst eigene Datei, damit tests/test_setup_module_logging.py
unveraendert bleibt (reine Addition, kein Diff im bestehenden Test).
"""
from __future__ import annotations

import logging
from pathlib import Path

from logger import setup_module_logging


def _mk(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def test_propagate_default_is_false(tmp_path):
    setup_module_logging("PropTest_Default", _mk(tmp_path / "a.log"), level="INFO")
    assert logging.getLogger("PropTest_Default").propagate is False


def test_propagate_true_is_honoured(tmp_path):
    setup_module_logging(
        "PropTest_True", _mk(tmp_path / "b.log"), level="INFO", propagate=True
    )
    assert logging.getLogger("PropTest_True").propagate is True


def test_propagate_can_be_reset_back_to_false(tmp_path):
    setup_module_logging(
        "PropTest_Reset", _mk(tmp_path / "c.log"), level="INFO", propagate=True
    )
    assert logging.getLogger("PropTest_Reset").propagate is True

    setup_module_logging(
        "PropTest_Reset", _mk(tmp_path / "c.log"), level="INFO", propagate=False
    )
    assert logging.getLogger("PropTest_Reset").propagate is False
