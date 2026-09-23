# -*- coding: utf-8 -*-
"""
CC-LOGGER-L5.2/L5.3 — Tests für Preflight + Rate-Limiter
(services/logger_admin.py).

Deckt die dreistufige Preflight-Semantik ab (clear/blocked/unverified)
und den Rate-Limiter inkl. Single-Flight-Verhalten.

`is_repair_running()` wird pro Testfall gemockt — keine echte Lock-Datei
im Repo wird angefasst.
"""
from __future__ import annotations

import threading
import time

import pytest

from services.logger_admin import (
    PREFLIGHT_STATUS_BLOCKED,
    PREFLIGHT_STATUS_CLEAR,
    PREFLIGHT_STATUS_UNVERIFIED,
    UNVERIFIABLE_ACTIVITY_CATEGORIES,
    LoggerApplyRateLimiter,
    evaluate_apply_preflight,
)


# =====================================================================
# Preflight
# =====================================================================

class TestPreflight:
    def test_repair_lock_active_returns_blocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.library_repair import run_tracking

        monkeypatch.setattr(run_tracking, "is_repair_running", lambda: True)
        result = evaluate_apply_preflight()
        assert result["status"] == PREFLIGHT_STATUS_BLOCKED
        assert result["checked"] == {"repair_lock": True}
        assert result["active"] == {"repair": True}
        assert result["unverified"] == []

    def test_repair_lock_free_returns_unverified_while_categories_exist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.library_repair import run_tracking

        monkeypatch.setattr(run_tracking, "is_repair_running", lambda: False)
        result = evaluate_apply_preflight()
        assert result["status"] == PREFLIGHT_STATUS_UNVERIFIED
        assert result["checked"] == {"repair_lock": True}
        assert result["active"] == {"repair": False}
        assert result["unverified"] == list(UNVERIFIABLE_ACTIVITY_CATEGORIES)

    def test_repair_lock_check_failure_returns_blocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-safe: wenn der Lock-Check eine Exception wirft, wird
        konservativ 'blocked' zurueckgegeben — NIEMALS 'clear'."""
        from services.library_repair import run_tracking

        def _boom() -> bool:
            raise OSError("simulated lock read failure")

        monkeypatch.setattr(run_tracking, "is_repair_running", _boom)
        result = evaluate_apply_preflight()
        assert result["status"] == PREFLIGHT_STATUS_BLOCKED
        assert result["checked"] == {"repair_lock": False}

    def test_unverified_never_equals_clear(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Kernvertrag aus L5.txt §B.7/B.10: 'unverified' darf nie als
        'clear' durchgehen, solange unverifizierbare Kategorien
        existieren."""
        from services.library_repair import run_tracking

        monkeypatch.setattr(run_tracking, "is_repair_running", lambda: False)
        result = evaluate_apply_preflight()
        assert result["status"] != PREFLIGHT_STATUS_CLEAR
        assert result["unverified"]  # nicht leer

    def test_clear_only_reachable_without_unverifiable_categories(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Wenn es keine unverifizierbaren Kategorien mehr gaebe, waere
        'clear' erreichbar. Wir simulieren das durch Patchen der
        Modul-Konstante, um die Semantik zu pinnen."""
        import services.logger_admin as la
        from services.library_repair import run_tracking

        monkeypatch.setattr(run_tracking, "is_repair_running", lambda: False)
        monkeypatch.setattr(la, "UNVERIFIABLE_ACTIVITY_CATEGORIES", ())
        result = la.evaluate_apply_preflight()
        assert result["status"] == PREFLIGHT_STATUS_CLEAR
        assert result["unverified"] == []


# =====================================================================
# Rate-Limiter
# =====================================================================

class TestRateLimiter:
    def test_first_acquire_succeeds(self) -> None:
        rl = LoggerApplyRateLimiter(min_interval_seconds=10.0)
        allowed, retry_after = rl.try_acquire()
        assert allowed is True
        assert retry_after == 0.0

    def test_second_acquire_within_window_rejected(self) -> None:
        rl = LoggerApplyRateLimiter(min_interval_seconds=10.0)
        rl.try_acquire()
        allowed, retry_after = rl.try_acquire()
        assert allowed is False
        assert 0 < retry_after <= 10.0

    def test_acquire_after_window_succeeds(self) -> None:
        rl = LoggerApplyRateLimiter(min_interval_seconds=0.05)
        rl.try_acquire()
        time.sleep(0.06)
        allowed, _ = rl.try_acquire()
        assert allowed is True

    def test_reset_clears_window(self) -> None:
        rl = LoggerApplyRateLimiter(min_interval_seconds=60.0)
        rl.try_acquire()
        rl.reset()
        allowed, _ = rl.try_acquire()
        assert allowed is True

    def test_concurrent_acquire_only_one_passes(self) -> None:
        """Single-Flight-Kernvertrag: von zwei gleichzeitig eintreffenden
        Acquire-Aufrufen darf nur einer passieren."""
        rl = LoggerApplyRateLimiter(min_interval_seconds=60.0)
        results: list[bool] = []
        lock = threading.Lock()

        def worker() -> None:
            allowed, _ = rl.try_acquire()
            with lock:
                results.append(allowed)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1
        assert results.count(False) == 19
