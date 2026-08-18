import os
import shutil
import asyncio
from pathlib import Path
from typing import Union
import logging

logger = logging.getLogger(__name__)

# Semaphore für begrenzte parallele IO-Operationen
IO_SEMAPHORE = asyncio.Semaphore(5)  # z.B. max. 5 parallele Umbenennungen


async def atomic_rename(src: Union[str, Path], dest: Union[str, Path]) -> bool:
    """
    Führt ein atomisches Umbenennen durch, falls vom Betriebssystem unterstützt.
    """
    src_path = Path(src)
    dest_path = Path(dest)

    # Sicherstellen, dass das Zielverzeichnis existiert
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if os.name == "posix":
            # Auf POSIX-Systemen ist os.rename atomar
            os.rename(str(src_path), str(dest_path))
        else:
            # Auf Windows versuchen wir es mit shutil.move
            shutil.move(str(src_path), str(dest_path))
        return True
    except Exception as e:
        logger.error(f"Atomisches Umbenennen fehlgeschlagen: {e}")
        return False
