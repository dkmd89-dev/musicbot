"""
Statistik-Laufzeitdiagnose: warum wurde nach einem Bot-Neustart nichts mehr
in die Wiedergabe-History geschrieben?

Die Tests sind bewusst architekturneutral zum Poller (Snapshot- ODER
playCount-basiert): sie prüfen nur Lifecycle-Eigenschaften, die für JEDE
Poller-Implementierung gelten müssen, und Persistenz-Eigenschaften des
PlayHistoryRepository. Externe Dienste (Navidrome) sind gefakt.

Nachgewiesene Wirkkette (siehe Root-Cause-Bericht):
  bot.py ruft StatistikService.start_polling() -> PlayHistoryPoller.
  start_polling() -> asyncio.create_task(_run_history_updater()). Stirbt
  dieser Task sofort (Exception in der ersten Zeile), bleibt das ohne
  Log-Spur: self._polling_task hält die Referenz (kein "Task exception was
  never retrieved"), bot.py loggt "erfolgreich gestartet" direkt nach
  create_task() und der Poller hat keinen Done-Callback.
"""

import asyncio
import json
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

import config as config_module
from services.statistik import play_history_poller as poller_module
from services.statistik.play_history_poller import PlayHistoryPoller
from services.statistik.play_history_repository import PlayHistoryRepository
from services.statistik.statistics_calculator import StatisticsCalculator


class FakeApi:
    def __init__(self, fail_first=0):
        self.calls = 0
        self._fail_first = fail_first

    async def get_now_playing(self):
        self.calls += 1
        if self.calls <= self._fail_first:
            raise RuntimeError("Navidrome nicht erreichbar")
        return []


@pytest.fixture
def poller_env(tmp_path, monkeypatch):
    """Poller mit gefakter Config/Navidrome, alle Pfade unter tmp_path."""
    history_dir = tmp_path / "user_histories"
    history_dir.mkdir()
    fake_cfg = types.SimpleNamespace(
        NAVIDROME_URL="http://navidrome.invalid",
        NAVIDROME_USER="u",
        NAVIDROME_PASS="p",
        PLAY_HISTORY_FILE=history_dir,
        PLAY_HISTORY_AUTOSAVE_INTERVAL_MIN=1,
    )
    monkeypatch.setattr(config_module, "get_config", lambda: fake_cfg)
    # poller_module.get_config nur umbiegen, WENN es existiert: ein neu
    # angelegtes Modul-Attribut würde einen fehlenden Modul-Import im Poller
    # maskieren (genau der ursprüngliche NameError).
    if hasattr(poller_module, "get_config"):
        monkeypatch.setattr(poller_module, "get_config", lambda: fake_cfg)
    monkeypatch.setattr(
        config_module.Config, "PLAY_HISTORY_AUTOSAVE_INTERVAL_MIN", 1, raising=False
    )

    api = FakeApi()
    repo = PlayHistoryRepository(history_dir, logger=Mock())
    poller = PlayHistoryPoller(api, repo, logger=Mock())
    return poller, api, repo, history_dir


def _speed_up_sleep(monkeypatch):
    """Ersetzt asyncio.sleep im Poller durch ein sofortiges Yield und gibt
    das echte sleep für die Testschleife zurück."""
    real_sleep = asyncio.sleep

    async def fast_sleep(_delay, *a, **kw):
        await real_sleep(0)

    monkeypatch.setattr(poller_module.asyncio, "sleep", fast_sleep)
    return real_sleep


async def _wait_for(predicate, real_sleep, max_ticks=500):
    for _ in range(max_ticks):
        if predicate():
            return True
        await real_sleep(0)
    return predicate()


# ── Test A/E: Poller-Task startet, läuft weiter, ist neu startbar ──────────


class TestPollerLifecycle:
    def test_started_task_keeps_running_after_start(self, poller_env, monkeypatch):
        """Direkt nach start_polling() darf der Task nicht beendet sein.
        Ein sofort sterbender Task (Exception in der ersten Zeile von
        _run_history_updater) bleibt ohne Log-Spur, die History wird nie
        mehr aktualisiert."""
        poller, _api, _repo, _ = poller_env
        real_sleep = _speed_up_sleep(monkeypatch)

        async def scenario():
            poller.start_polling()
            task = poller._polling_task
            for _ in range(20):
                await real_sleep(0)
            died_with = task.exception() if task.done() and not task.cancelled() else None
            still_running = not task.done()
            await poller.stop_polling()
            return still_running, died_with

        still_running, died_with = asyncio.run(scenario())
        assert still_running, f"Poller-Task ist sofort beendet worden: {died_with!r}"

    def test_poller_executes_repeated_update_cycles(self, poller_env, monkeypatch):
        poller, api, _repo, _ = poller_env
        real_sleep = _speed_up_sleep(monkeypatch)

        async def scenario():
            poller.start_polling()
            reached = await _wait_for(lambda: api.calls >= 3, real_sleep)
            await poller.stop_polling()
            return reached

        assert asyncio.run(scenario()), (
            f"Poller hat nur {api.calls} Update-Zyklus/-Zyklen ausgeführt "
            "(erwartet >= 3)"
        )

    def test_restart_after_stop_runs_again(self, poller_env, monkeypatch):
        poller, api, _repo, _ = poller_env
        real_sleep = _speed_up_sleep(monkeypatch)

        async def scenario():
            poller.start_polling()
            first = await _wait_for(lambda: api.calls >= 1, real_sleep)
            await poller.stop_polling()
            calls_after_stop = api.calls
            poller.start_polling()
            second = await _wait_for(lambda: api.calls > calls_after_stop, real_sleep)
            await poller.stop_polling()
            return first, second

        first, second = asyncio.run(scenario())
        assert first, "erster Start hat nie einen Zyklus ausgeführt"
        assert second, "Neustart nach stop_polling() hat nie einen Zyklus ausgeführt"

    def test_double_start_keeps_a_single_task(self, poller_env, monkeypatch):
        poller, _api, _repo, _ = poller_env
        real_sleep = _speed_up_sleep(monkeypatch)

        async def scenario():
            poller.start_polling()
            first = poller._polling_task
            await real_sleep(0)
            poller.start_polling()
            same = poller._polling_task is first
            await poller.stop_polling()
            return same

        assert asyncio.run(scenario())


class TestPollerDeathIsNotSilent:
    def test_unexpected_task_exit_is_logged_as_error(self, poller_env, monkeypatch):
        """Stirbt der Hintergrund-Task, muss das im Log sichtbar sein."""
        poller, _api, _repo, _ = poller_env

        async def boom():
            raise RuntimeError("kaputt")

        monkeypatch.setattr(poller, "_run_history_updater", boom)

        async def scenario():
            poller.start_polling()
            task = poller._polling_task
            for _ in range(5):
                await asyncio.sleep(0)
            assert task.done()

        asyncio.run(scenario())
        errors = [c.args[0] for c in poller.logger.error.call_args_list]
        assert any("unerwartet beendet" in m and "kaputt" in m for m in errors)

    def test_clean_cancel_via_stop_polling_is_not_logged_as_error(
        self, poller_env, monkeypatch
    ):
        poller, api, _repo, _ = poller_env
        real_sleep = _speed_up_sleep(monkeypatch)

        async def scenario():
            poller.start_polling()
            await _wait_for(lambda: api.calls >= 1, real_sleep)
            await poller.stop_polling()

        asyncio.run(scenario())
        poller.logger.error.assert_not_called()


class TestPollerSurvivesApiErrors:
    """Test D: get_now_playing() wirft -> der Poller läuft danach weiter."""

    def test_poller_continues_after_get_now_playing_exception(
        self, tmp_path, monkeypatch
    ):
        history_dir = tmp_path / "user_histories"
        history_dir.mkdir()
        fake_cfg = types.SimpleNamespace(
            NAVIDROME_URL="http://navidrome.invalid",
            NAVIDROME_USER="u",
            NAVIDROME_PASS="p",
            PLAY_HISTORY_FILE=history_dir,
            PLAY_HISTORY_AUTOSAVE_INTERVAL_MIN=1,
        )
        monkeypatch.setattr(config_module, "get_config", lambda: fake_cfg)
        if hasattr(poller_module, "get_config"):
            monkeypatch.setattr(poller_module, "get_config", lambda: fake_cfg)
        api = FakeApi(fail_first=2)
        poller = PlayHistoryPoller(
            api, PlayHistoryRepository(history_dir, logger=Mock()), logger=Mock()
        )
        real_sleep = _speed_up_sleep(monkeypatch)

        async def scenario():
            poller.start_polling()
            reached = await _wait_for(lambda: api.calls >= 4, real_sleep)
            alive = not poller._polling_task.done()
            await poller.stop_polling()
            return reached, alive

        reached, alive = asyncio.run(scenario())
        assert reached and alive, (
            f"Poller hat nach Navidrome-Fehlern nur {api.calls} Zyklen ausgeführt "
            f"(alive={alive})"
        )


# ── Test B/C: Lesen (Telegram/Control Center) verändert die History nicht ──


def _entry(ts, song_id="s1"):
    return {
        "timestamp": ts,
        "tracks": [
            {
                "title": "T",
                "artist": "A",
                "album": "Al",
                "genre": "",
                "genres": [],
                "id": song_id,
                "duration": 200,
                "player": "p",
                "username": "dkmd",
            }
        ],
    }


class TestReadersDoNotTouchHistory:
    def test_repeated_statistics_calls_leave_history_byte_identical(self, tmp_path):
        repo = PlayHistoryRepository(tmp_path, logger=Mock())
        repo.save([_entry("2026-09-30T10:00:00"), _entry("2026-09-30T10:05:00")], "dkmd")
        path = repo.history_file_for_user("dkmd")
        before = path.read_bytes()

        saves = []
        real_save = repo.save
        repo.save = lambda *a, **kw: (saves.append(a), real_save(*a, **kw))[1]

        fixed_now = datetime(2026, 9, 30, 12, 0, 0)
        calc = StatisticsCalculator(repo, tmp_path / "charts", logger=Mock())
        (tmp_path / "charts").mkdir()
        for _ in range(3):
            stats = calc.generate_stats("month", "dkmd", now=fixed_now)
            timeline = calc.generate_timeline_stats("dkmd", now=fixed_now)
            assert stats is not None and timeline is not None

        assert saves == [], "Statistik-Lesepfad hat die History geschrieben"
        assert path.read_bytes() == before

    def test_long_lived_reader_sees_later_writes_no_stale_snapshot(self, tmp_path):
        """Kein In-Memory-Snapshot im Repository: eine langlebige Instanz
        (z. B. im Bot) liest bei jedem load() den aktuellen Plattenstand -
        anders als DownloadHistoryStore/DuplicateCache vor D.13."""
        reader_repo = PlayHistoryRepository(tmp_path, logger=Mock())
        writer_repo = PlayHistoryRepository(tmp_path, logger=Mock())
        assert reader_repo.load("dkmd") == []

        writer_repo.save([_entry("2026-09-30T10:00:00")], "dkmd")
        assert len(reader_repo.load("dkmd")) == 1

        h = writer_repo.load("dkmd")
        h.append(_entry("2026-09-30T10:03:00", "s2"))
        writer_repo.save(h, "dkmd")
        assert len(reader_repo.load("dkmd")) == 2

    def test_save_is_atomic_and_leaves_no_partial_file(self, tmp_path):
        repo = PlayHistoryRepository(tmp_path, logger=Mock())
        repo.save([_entry("2026-09-30T10:00:00")], "dkmd")
        data = json.loads(repo.history_file_for_user("dkmd").read_text(encoding="utf-8"))
        assert len(data) == 1
        leftovers = [p for p in Path(tmp_path).iterdir() if p.name.startswith(".")]
        assert leftovers == []
