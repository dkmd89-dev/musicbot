# services/downloader/models.py
# -*- coding: utf-8 -*-
"""
Neutrale Downloader-Datenmodelle, die nicht spezifisch für einen einzelnen
Consumer sind.

`DuplicateEntry` lebte zuvor in `handlers/duplicate_handler.py` und wurde
von dort auch von `services/downloader/download_result_reporter.py`
importiert - eine services/->handlers/-Schichtverletzung (POST-ARCH-010/011
Services-Audit, siehe docs/MusicBot_POST-ARCH-010_011_DuplicateEntry_Analyse.md).
Reine Datenstruktur ohne Telegram-Bezug, daher hierher verschoben.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class DuplicateEntry:
    """Repräsentiert einen Duplikat-Eintrag im Cache"""

    artist: str
    title: str
    url: str
    file_path: Optional[Path]
    download_date: datetime
    file_hash: Optional[str] = None
    metadata_hash: str = None
    duplicate_count: int = 1
