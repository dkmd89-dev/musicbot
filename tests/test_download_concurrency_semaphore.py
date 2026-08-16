"""
Regressionstest fuer: Config.MAX_CONCURRENT_DOWNLOADS war definiert, wurde
aber nirgends durchgesetzt - beliebig viele gleichzeitige Downloads waren
moeglich.

Wichtiger Design-Fund dieser Session: DownloadHandler wird pro Telegram-
Update NEU instanziiert (RichMenuHandler._create_download_handler). Ein
Semaphore als Instanzattribut waere daher wirkungslos gewesen - jede neue
Instanz haette ihr eigenes, volles Kontingent gehabt. _get_download_semaphore()
haelt den Semaphore deshalb bewusst auf Modul-Ebene (globaler Singleton),
geteilt ueber alle DownloadHandler-Instanzen hinweg.
"""

import asyncio

import pytest

import klassen.download_handler as download_handler_module
from klassen.download_handler import _get_download_semaphore


@pytest.fixture(autouse=True)
def reset_module_level_semaphore():
    """
    Der Semaphore ist ein Modul-Singleton - zwischen Tests zuruecksetzen,
    damit ein Test mit MAX_CONCURRENT_DOWNLOADS=2 nicht versehentlich den
    Semaphore eines vorherigen Tests mit einem anderen Limit wiederverwendet.
    """
    download_handler_module._download_semaphore = None
    yield
    download_handler_module._download_semaphore = None


class FakeConfig:
    def __init__(self, max_concurrent):
        self.MAX_CONCURRENT_DOWNLOADS = max_concurrent


class TestSemaphoreIsAModuleLevelSingleton:
    def test_same_semaphore_instance_returned_across_calls(self):
        config = FakeConfig(max_concurrent=3)
        sem1 = _get_download_semaphore(config)
        sem2 = _get_download_semaphore(config)
        assert sem1 is sem2

    def test_semaphore_shared_across_different_config_objects(self):
        """
        Simuliert zwei verschiedene DownloadHandler-Instanzen (wie sie pro
        Telegram-Update real entstehen) - beide muessen sich denselben
        Semaphore teilen, nicht je einen eigenen bekommen.
        """
        config_a = FakeConfig(max_concurrent=2)
        config_b = FakeConfig(max_concurrent=2)
        sem_a = _get_download_semaphore(config_a)
        sem_b = _get_download_semaphore(config_b)
        assert sem_a is sem_b

    def test_semaphore_uses_max_concurrent_downloads_from_first_call(self):
        config = FakeConfig(max_concurrent=5)
        sem = _get_download_semaphore(config)
        assert sem._value == 5

    def test_missing_config_attribute_falls_back_to_default_of_3(self):
        class ConfigWithoutLimit:
            pass

        sem = _get_download_semaphore(ConfigWithoutLimit())
        assert sem._value == 3


class TestSemaphoreActuallyLimitsConcurrency:
    def test_only_n_tasks_run_concurrently(self):
        config = FakeConfig(max_concurrent=2)
        semaphore = _get_download_semaphore(config)

        concurrent_count = 0
        max_observed_concurrent = 0

        async def fake_download():
            nonlocal concurrent_count, max_observed_concurrent
            async with semaphore:
                concurrent_count += 1
                max_observed_concurrent = max(max_observed_concurrent, concurrent_count)
                await asyncio.sleep(0.05)
                concurrent_count -= 1

        async def main():
            await asyncio.gather(*(fake_download() for _ in range(6)))

        asyncio.run(main())
        assert max_observed_concurrent == 2
