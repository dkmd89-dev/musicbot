# tests/test_download_concurrency.py
# -*- coding: utf-8 -*-
"""
services/downloader/download_concurrency.py — Charakterisierungs-/
Regressionstests für den Cross-Process-Slot-Mechanismus (Client
Consolidation Phase D/E, Architekturentscheidung "Option B", siehe
docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md Abschnitt 11).
Testaufbau (isolierter Config.DATA_DIR) analog zu
tests/test_library_repair_run_tracking.py.
"""

import asyncio

import pytest

import services.downloader.download_concurrency as dc


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dc.Config, "DATA_DIR", tmp_path)
    yield tmp_path


class TestPaths:
    def test_slots_dir_under_data_dir(self, isolated_data_dir):
        assert dc.slots_dir() == isolated_data_dir / dc.SLOTS_DIRNAME

    def test_slot_path_under_slots_dir(self, isolated_data_dir):
        assert dc.slot_path(2) == dc.slots_dir() / "slot_2.lock"


class TestTryAcquireSlot:
    def test_first_acquire_creates_file(self, isolated_data_dir):
        dc.slots_dir().mkdir(parents=True, exist_ok=True)
        assert dc._try_acquire_slot(0) is True
        assert dc.slot_path(0).exists()

    def test_second_acquire_of_same_slot_fails(self, isolated_data_dir):
        dc.slots_dir().mkdir(parents=True, exist_ok=True)
        assert dc._try_acquire_slot(0) is True
        assert dc._try_acquire_slot(0) is False

    def test_acquire_after_release_succeeds_again(self, isolated_data_dir):
        dc.slots_dir().mkdir(parents=True, exist_ok=True)
        dc._try_acquire_slot(0)
        dc.release_download_slot(0)
        assert dc._try_acquire_slot(0) is True

    def test_release_without_prior_acquire_is_noop(self, isolated_data_dir):
        dc.release_download_slot(0)  # darf nicht werfen


class TestSlotInfo:
    def test_contains_pid_and_timestamp(self, isolated_data_dir):
        dc.slots_dir().mkdir(parents=True, exist_ok=True)
        dc._try_acquire_slot(0)
        info = dc.read_slot_info(0)
        assert info is not None
        assert info.pid > 0
        assert info.since  # nicht leer

    def test_none_when_slot_free(self, isolated_data_dir):
        assert dc.read_slot_info(0) is None


class TestAcquireDownloadSlotAsync:
    @pytest.mark.asyncio
    async def test_acquires_first_free_slot(self, isolated_data_dir):
        index = await dc.acquire_download_slot(3, poll_interval=0.01)
        assert index == 0
        dc.release_download_slot(index)

    @pytest.mark.asyncio
    async def test_second_call_gets_different_slot(self, isolated_data_dir):
        first = await dc.acquire_download_slot(3, poll_interval=0.01)
        second = await dc.acquire_download_slot(3, poll_interval=0.01)
        assert first != second
        dc.release_download_slot(first)
        dc.release_download_slot(second)

    @pytest.mark.asyncio
    async def test_waits_instead_of_failing_when_all_slots_busy(self, isolated_data_dir):
        """Charakterisiert das bewusst übernommene Warteverhalten des
        bisherigen asyncio.Semaphore (Modul-Docstring, Regel 2) - kein
        Fail-Fast wie beim Repair-Lock."""
        held = await dc.acquire_download_slot(1, poll_interval=0.01)

        async def release_after_delay():
            await asyncio.sleep(0.05)
            dc.release_download_slot(held)

        release_task = asyncio.create_task(release_after_delay())
        acquired = await asyncio.wait_for(
            dc.acquire_download_slot(1, poll_interval=0.01), timeout=2.0
        )
        await release_task
        assert acquired == 0
        dc.release_download_slot(acquired)

    @pytest.mark.asyncio
    async def test_download_slot_context_manager_releases_on_exception(self, isolated_data_dir):
        with pytest.raises(RuntimeError):
            async with dc.download_slot(2, poll_interval=0.01) as index:
                assert dc.slot_path(index).exists()
                raise RuntimeError("boom")
        # Slot muss trotz Exception wieder frei sein (finally-Release).
        assert dc.read_slot_info(0) is None
        assert dc.read_slot_info(1) is None

    @pytest.mark.asyncio
    async def test_download_slot_context_manager_releases_on_success(self, isolated_data_dir):
        async with dc.download_slot(2, poll_interval=0.01) as index:
            assert dc.read_slot_info(index) is not None
        assert dc.read_slot_info(index) is None
