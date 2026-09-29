# -*- coding: utf-8 -*-
"""D.12b.1: Im CC-Prozess (Rolle "control_center") legt
EnhancedMetadataProcessor keinen eigenen FileHandler auf
enhanced_metadata_processor.log an und propagiert stattdessen zum
Root-Logger (-> control_center.log). Verhindert das Zwei-Prozess-
Rotieren derselben Datei.

Bot-Rolle bleibt unveraendert: Config-gesteuerter FileHandler +
propagate=False (Bestandsverhalten).

Hinweis zum Test-Design: `_do_init()` setzt den Logger VOR allen
Sub-Prozessoren (ArtistNormalizer, ...). Die Test-Config ist bewusst
minimal; nachgelagerte Komponenten koennen an fehlenden Feldern
scheitern. Das ist fuer diesen Test unerheblich - geprueft wird der
Logger-Zustand, der zu diesem Zeitpunkt bereits final ist. Siehe
_construct() unten.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from logger import set_process_role
from services.metadata.enhanced_metadata_processor import (
    EnhancedMetadataProcessor,
)


@pytest.fixture(autouse=True)
def _reset_singleton_and_role():
    # SingletonMixin haelt _instances als Klassen-Dict - Reset vor UND
    # nach jedem Test, damit die Reihenfolge unabhaengig ist.
    EnhancedMetadataProcessor._instances.clear()
    set_process_role("bot")
    yield
    EnhancedMetadataProcessor._instances.clear()
    set_process_role("bot")


def _cfg(tmp_path: Path):
    class C:
        LOG_DIR = tmp_path / "logs"
        DOWNLOAD_HISTORY_DIR = tmp_path / "hist"
        CACHE_DIR = tmp_path / "cache"
        MAPPING_DIR = tmp_path / "map"
        LIBRARY_PATH = tmp_path / "lib"
        # ArtistNormalizer braucht library_dir als Path - siehe
        # utils/artist_map.py::_load_library_artists(). Wir setzen es,
        # auch wenn hier nicht alle Folge-Felder vollstaendig sind.
        library_dir = tmp_path / "lib"

    return C()


def _construct(tmp_path):
    """Konstruiert den Processor so weit wie noetig. Der Logger wird
    in _do_init() VOR allen Sub-Prozessoren konfiguriert - spaetere
    Fehler (unvollstaendige Test-Config) duerfen den Test nicht
    umwerfen, weil sie nichts mit der Logger-Konfiguration zu tun
    haben, die hier geprueft wird."""
    try:
        EnhancedMetadataProcessor(_cfg(tmp_path))
    except Exception:
        # Logger-Zustand steht bereits - wir greifen ihn unten ab.
        pass


def test_cc_role_disables_file_handler_and_enables_propagation(tmp_path):
    set_process_role("control_center")
    _construct(tmp_path)
    lg = logging.getLogger("EnhancedMetadataProcessor")

    assert lg.propagate is True
    assert not any(
        isinstance(h, logging.FileHandler) for h in lg.handlers
    ), "CC darf keinen FileHandler auf enhanced_metadata_processor.log haben"


def test_bot_role_keeps_legacy_file_handler_and_no_propagation(tmp_path):
    # Rolle ist bereits "bot" (Fixture) - Default-Verhalten
    _construct(tmp_path)
    lg = logging.getLogger("EnhancedMetadataProcessor")

    assert lg.propagate is False
    assert any(
        isinstance(h, logging.FileHandler) for h in lg.handlers
    ), "Bot muss seinen FileHandler behalten"
