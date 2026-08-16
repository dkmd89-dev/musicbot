# yt_music_bot/services/downloader/interfaces.py
from abc import ABC, abstractmethod
from typing import Union, List, Dict, Any


class IDownloaderConfig(ABC):
    """Abstrakte Konfigurations-Schnittstelle für den Downloader."""

    @property
    @abstractmethod
    def AUDIO_FORMAT(self) -> str:
        pass

    @property
    @abstractmethod
    def AUDIO_FORMAT_STRING(self) -> str:
        pass

    @property
    @abstractmethod
    def AUDIO_QUALITY(self) -> int:
        pass

    @property
    @abstractmethod
    def DOWNLOAD_DIR(self) -> str:
        pass

    @property
    @abstractmethod
    def PROCESSED_DIR(self) -> str:
        pass

    @property
    @abstractmethod
    def MAX_DURATION(self) -> int:
        pass

    @property
    @abstractmethod
    def MAX_PLAYLIST_ITEMS(self) -> int:
        pass

    @property
    @abstractmethod
    def DEFAULT_ALBUM_NAME(self) -> str:
        pass

    @property
    @abstractmethod
    def UNKNOWN_PLAYLIST(self) -> str:
        pass

    @property
    @abstractmethod
    def MAX_CONCURRENT_DOWNLOADS(self) -> int:
        pass

    @property
    @abstractmethod
    def METADATA_DEFAULTS(self) -> Dict[str, Any]:
        pass

    @property
    @abstractmethod
    def LIBRARY_DIR(self) -> str:
        pass


class IDownloader(ABC):
    """Abstrakte Downloader-Schnittstelle."""

    @abstractmethod
    async def download_audio(self, url: str) -> Union[str, List[str]]:
        """Abstrakte Methode für Audio-Downloads."""
        pass
