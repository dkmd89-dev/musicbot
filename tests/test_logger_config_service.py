# -*- coding: utf-8 -*-
"""
CC-LOGGER-L4 Stufe 1 — Tests für die persistenten Logger-Config-
Funktionen in services/logger_admin.py.

Reine App-Layer-Tests gegen ein isoliertes tmp-Verzeichnis (kein
FastAPI, kein Telegram). Der Pfad wird über ein FakeConfig-Objekt mit
`DATA_DIR` aufgelöst — identisch zu services/user_data.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.logger_admin import (
    ALLOWED_LOG_LEVELS,
    ALLOWED_PATCHABLE_FIELDS,
    CONFIG_FILE_NAME,
    LoggerConfigError,
    read_logger_config,
    update_logger_config,
    validate_logger_config_patch,
)


class FakeConfig:
    def __init__(self, data_dir: Path):
        self.DATA_DIR = str(data_dir)


@pytest.fixture
def cfg(tmp_path: Path) -> FakeConfig:
    return FakeConfig(tmp_path)


def _seed(cfg: FakeConfig, data: dict) -> Path:
    path = Path(cfg.DATA_DIR) / CONFIG_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _default_module(**overrides) -> dict:
    base = {
        "enabled": True,
        "level": "INFO",
        "file_handler": True,
        "console_handler": True,
        "custom_format": None,
    }
    base.update(overrides)
    return base


# =====================================================================
# read_logger_config
# =====================================================================

class TestRead:
    def test_missing_file_returns_empty_dict(self, cfg: FakeConfig) -> None:
        assert read_logger_config(cfg) == {}

    def test_reads_valid_config(self, cfg: FakeConfig) -> None:
        _seed(cfg, {"ModA": _default_module(level="DEBUG")})
        data = read_logger_config(cfg)
        assert data == {"ModA": _default_module(level="DEBUG")}

    def test_corrupt_json_raises(self, cfg: FakeConfig) -> None:
        path = Path(cfg.DATA_DIR) / CONFIG_FILE_NAME
        path.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(LoggerConfigError) as ei:
            read_logger_config(cfg)
        assert ei.value.code == "LOGGER_CONFIG_CORRUPT"

    def test_non_object_json_raises(self, cfg: FakeConfig) -> None:
        path = Path(cfg.DATA_DIR) / CONFIG_FILE_NAME
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(LoggerConfigError) as ei:
            read_logger_config(cfg)
        assert ei.value.code == "LOGGER_CONFIG_CORRUPT"


# =====================================================================
# validate_logger_config_patch
# =====================================================================

class TestValidate:
    def test_accepts_valid_patch(self) -> None:
        validate_logger_config_patch(
            {"ModA": {"level": "DEBUG"}},
            existing_modules={"ModA"},
        )

    def test_unknown_module_rejected(self) -> None:
        with pytest.raises(LoggerConfigError) as ei:
            validate_logger_config_patch(
                {"Nope": {"level": "DEBUG"}},
                existing_modules={"ModA"},
            )
        assert ei.value.code == "LOGGER_CONFIG_UNKNOWN_MODULE"

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(LoggerConfigError) as ei:
            validate_logger_config_patch(
                {"ModA": {"nope": True}},
                existing_modules={"ModA"},
            )
        assert ei.value.code == "LOGGER_CONFIG_UNKNOWN_FIELD"

    def test_custom_format_not_patchable(self) -> None:
        """Explizit: `custom_format` ist bewusst NICHT patchbar."""
        with pytest.raises(LoggerConfigError) as ei:
            validate_logger_config_patch(
                {"ModA": {"custom_format": "anything"}},
                existing_modules={"ModA"},
            )
        assert ei.value.code == "LOGGER_CONFIG_UNKNOWN_FIELD"

    @pytest.mark.parametrize("bad_level", ["debug", "TRACE", "", 123])
    def test_invalid_level_rejected(self, bad_level) -> None:
        with pytest.raises(LoggerConfigError) as ei:
            validate_logger_config_patch(
                {"ModA": {"level": bad_level}},
                existing_modules={"ModA"},
            )
        assert ei.value.code == "LOGGER_CONFIG_INVALID_LEVEL"

    @pytest.mark.parametrize("good_level", sorted(ALLOWED_LOG_LEVELS))
    def test_all_whitelisted_levels_accepted(self, good_level: str) -> None:
        validate_logger_config_patch(
            {"ModA": {"level": good_level}},
            existing_modules={"ModA"},
        )

    @pytest.mark.parametrize("bad_value", ["true", 1, None, [], {}])
    def test_non_bool_for_handler_fields_rejected(self, bad_value) -> None:
        with pytest.raises(LoggerConfigError) as ei:
            validate_logger_config_patch(
                {"ModA": {"enabled": bad_value}},
                existing_modules={"ModA"},
            )
        assert ei.value.code == "LOGGER_CONFIG_INVALID_TYPE"

    def test_empty_module_body_rejected(self) -> None:
        with pytest.raises(LoggerConfigError) as ei:
            validate_logger_config_patch(
                {"ModA": {}},
                existing_modules={"ModA"},
            )
        assert ei.value.code == "LOGGER_CONFIG_PATCH_INVALID"

    def test_non_dict_patch_rejected(self) -> None:
        with pytest.raises(LoggerConfigError) as ei:
            validate_logger_config_patch(
                "not a dict",  # type: ignore[arg-type]
                existing_modules={"ModA"},
            )
        assert ei.value.code == "LOGGER_CONFIG_PATCH_INVALID"

    def test_all_allowed_fields_pass(self) -> None:
        validate_logger_config_patch(
            {
                "ModA": {
                    "enabled": True,
                    "level": "WARNING",
                    "file_handler": False,
                    "console_handler": False,
                }
            },
            existing_modules={"ModA"},
        )


# =====================================================================
# update_logger_config
# =====================================================================

class TestUpdate:
    def test_patch_without_file_raises_missing(self, cfg: FakeConfig) -> None:
        with pytest.raises(LoggerConfigError) as ei:
            update_logger_config(cfg, {"ModA": {"level": "DEBUG"}})
        assert ei.value.code == "LOGGER_CONFIG_MISSING"

    def test_single_field_patch_merges_into_existing_module(
        self, cfg: FakeConfig
    ) -> None:
        _seed(cfg, {"ModA": _default_module(level="INFO")})
        result = update_logger_config(cfg, {"ModA": {"level": "DEBUG"}})
        assert result["ModA"]["level"] == "DEBUG"
        # Unveraenderte Felder bleiben erhalten.
        assert result["ModA"]["enabled"] is True
        assert result["ModA"]["file_handler"] is True
        assert result["ModA"]["console_handler"] is True

    def test_multiple_modules_patched(self, cfg: FakeConfig) -> None:
        _seed(
            cfg,
            {
                "ModA": _default_module(level="INFO"),
                "ModB": _default_module(level="INFO"),
            },
        )
        result = update_logger_config(
            cfg,
            {
                "ModA": {"level": "DEBUG"},
                "ModB": {"file_handler": False},
            },
        )
        assert result["ModA"]["level"] == "DEBUG"
        assert result["ModB"]["file_handler"] is False
        assert result["ModB"]["level"] == "INFO"  # unveraendert

    def test_other_modules_are_untouched(self, cfg: FakeConfig) -> None:
        _seed(
            cfg,
            {
                "ModA": _default_module(level="INFO"),
                "ModB": _default_module(level="DEBUG"),
            },
        )
        update_logger_config(cfg, {"ModA": {"level": "ERROR"}})
        after = read_logger_config(cfg)
        assert after["ModB"]["level"] == "DEBUG"

    def test_write_is_atomic_leaves_no_tmp(self, cfg: FakeConfig) -> None:
        _seed(cfg, {"ModA": _default_module()})
        update_logger_config(cfg, {"ModA": {"level": "DEBUG"}})
        tmp = Path(cfg.DATA_DIR) / (CONFIG_FILE_NAME + ".tmp")
        assert not tmp.exists()

    def test_write_is_persisted(self, cfg: FakeConfig) -> None:
        _seed(cfg, {"ModA": _default_module(level="INFO")})
        update_logger_config(cfg, {"ModA": {"level": "CRITICAL"}})
        after = read_logger_config(cfg)
        assert after["ModA"]["level"] == "CRITICAL"

    def test_invalid_patch_leaves_file_unchanged(self, cfg: FakeConfig) -> None:
        """Kernvertrag: bei einem invaliden PATCH darf die Datei NICHT
        verändert werden. Wir pinnen den sha256 der Datei vor und nach
        dem fehlgeschlagenen Update."""
        import hashlib

        path = _seed(cfg, {"ModA": _default_module(level="INFO")})
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with pytest.raises(LoggerConfigError):
            update_logger_config(cfg, {"ModA": {"level": "NOT_A_LEVEL"}})
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        assert before == after

    def test_unknown_module_leaves_file_unchanged(self, cfg: FakeConfig) -> None:
        import hashlib

        path = _seed(cfg, {"ModA": _default_module()})
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with pytest.raises(LoggerConfigError) as ei:
            update_logger_config(cfg, {"Nope": {"level": "DEBUG"}})
        assert ei.value.code == "LOGGER_CONFIG_UNKNOWN_MODULE"
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        assert before == after
