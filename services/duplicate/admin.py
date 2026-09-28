# services/duplicate/admin.py
# -*- coding: utf-8 -*-
"""
Duplikat-Cache-Verwaltung (Web-Paritäts-Backlog 4b, 2026-09-28): Statistik
und "Cache leeren" ohne Telegram-Bezug - gemeinsam genutzt von
handlers/duplicate_handler.py::EnhancedDuplicateHandler (Telegram) und
control_center/routers/admin_duplicates.py (Web).

Vorher lag die Lösch-Logik (Dateien entfernen, Speicher zurücksetzen)
direkt im Telegram-Handler und lief ohne den D.13-Lock. Jetzt läuft sie
über DuplicateCache.clear() unter DuplicateCache.transaction().

Bewusst NICHT hier: die Sitzungszähler des DuplicateDetector
(total_checks, url_duplicates_found, ...). Sie leben nur im Speicher des
jeweiligen Prozesses und kommen mit dem Bot-Snapshot (Entscheidung 1 / E1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from .cache import DuplicateCache


@dataclass(frozen=True)
class DuplicateCacheStats:
    url_entries: int
    content_entries: int
    oldest_entry: Optional[str]  # ISO-8601 (download_date), None bei leerem Cache
    newest_entry: Optional[str]


@dataclass(frozen=True)
class DuplicateCacheClearResult:
    url_entries_removed: int
    content_entries_removed: int
    deleted_files: List[str] = field(default_factory=list)


def cache_for_config(config: Any) -> DuplicateCache:
    """Frische DuplicateCache-Instanz auf Config.DUPLICATE_CACHE_DIR -
    identischer Pfad wie services/duplicate/detector.py::DuplicateDetector."""
    return DuplicateCache(cache_dir=getattr(config, "DUPLICATE_CACHE_DIR", "duplicate_cache"))


def get_duplicate_cache_stats(cache: DuplicateCache) -> DuplicateCacheStats:
    url_count, content_count, oldest, newest = cache.entry_stats()
    return DuplicateCacheStats(
        url_entries=url_count,
        content_entries=content_count,
        oldest_entry=oldest.isoformat() if oldest else None,
        newest_entry=newest.isoformat() if newest else None,
    )


def clear_duplicate_cache(cache: DuplicateCache) -> DuplicateCacheClearResult:
    url_count, content_count, deleted_files = cache.clear()
    return DuplicateCacheClearResult(
        url_entries_removed=url_count,
        content_entries_removed=content_count,
        deleted_files=deleted_files,
    )
