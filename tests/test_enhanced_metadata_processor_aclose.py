"""
Unit-Tests für EnhancedMetadataProcessor.aclose()
(services/downloader/utils/enhanced_metadata_processor.py).

Im Zuge der ARCH-001-Nacharbeit (Kapselungsverletzungen) aus bot.py
extrahiert: _async_cleanup_components() griff vorher direkt auf
rich_menu_handler.metadata_processor.genius_client durch, um es
asynchron zu schliessen - identische Logik lebt jetzt hier als oeffentliche
aclose()-Methode, bot.py ruft nur noch proc.aclose() auf.

Konstruiert die Klasse bewusst NICHT ueber EnhancedMetadataProcessor(config)
(SingletonMixin, _do_init() haette echte Seiteneffekte: Verzeichnisse
anlegen, externe Clients initialisieren) - object.__new__() umgeht
__init__/_do_init komplett und setzt nur die zwei von aclose() tatsaechlich
genutzten Attribute (genius_client, logger).
"""

from unittest.mock import AsyncMock, Mock

import pytest

from services.downloader.utils.enhanced_metadata_processor import (
    EnhancedMetadataProcessor,
)


def make_processor(genius_client=None):
    proc = object.__new__(EnhancedMetadataProcessor)
    proc.logger = Mock()
    if genius_client is not None:
        proc.genius_client = genius_client
    return proc


class TestAcloseNoGeniusClient:
    def test_missing_genius_client_attribute_does_nothing(self):
        proc = make_processor()  # kein genius_client gesetzt

        import asyncio
        asyncio.run(proc.aclose())  # darf nicht crashen

    def test_none_genius_client_does_nothing(self):
        proc = make_processor(genius_client=None)

        import asyncio
        asyncio.run(proc.aclose())


class TestAcloseWithAsyncClose:
    def test_prefers_async_close_when_available(self):
        genius = Mock()
        genius.async_close = AsyncMock()
        proc = make_processor(genius_client=genius)

        import asyncio
        asyncio.run(proc.aclose())

        genius.async_close.assert_called_once()

    def test_sync_close_is_still_called_after_async_close(self):
        """
        Charakterisiert das bestehende (aus bot.py uebernommene) Verhalten:
        close() wird IMMER zusaetzlich aufgerufen, auch wenn async_close()
        bereits erfolgreich war - kein exklusives Entweder-Oder.
        """
        genius = Mock()
        genius.async_close = AsyncMock()
        proc = make_processor(genius_client=genius)

        import asyncio
        asyncio.run(proc.aclose())

        genius.close.assert_called_once()


class TestAcloseFallbackToSession:
    def test_closes_raw_session_when_no_async_close(self):
        genius = Mock(spec=["_session", "close"])
        session = Mock()
        session.closed = False
        session.close = AsyncMock()
        genius._session = session

        proc = make_processor(genius_client=genius)

        import asyncio
        asyncio.run(proc.aclose())

        session.close.assert_called_once()
        genius.close.assert_called_once()

    def test_already_closed_session_is_not_closed_again(self):
        genius = Mock(spec=["_session", "close"])
        session = Mock()
        session.closed = True
        session.close = AsyncMock()
        genius._session = session

        proc = make_processor(genius_client=genius)

        import asyncio
        asyncio.run(proc.aclose())

        session.close.assert_not_called()


class TestAcloseErrorHandling:
    def test_exception_during_close_is_logged_not_raised(self):
        genius = Mock()
        genius.async_close = AsyncMock(side_effect=RuntimeError("boom"))
        proc = make_processor(genius_client=genius)

        import asyncio
        asyncio.run(proc.aclose())  # darf nicht crashen

        proc.logger.debug.assert_called_once()
