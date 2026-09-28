# tests/test_duplicate_admin_service.py
# -*- coding: utf-8 -*-
"""
4b — services/duplicate/admin.py: Duplikat-Cache-Verwaltung (Statistik,
Cache leeren) ohne Telegram-Bezug, gemeinsam genutzt von Telegram
(EnhancedDuplicateHandler) und Control Center.

Kernpunkte: Leeren läuft unter DuplicateCache.transaction() (D.13-Lock) -
eine zweite Instanz (anderer Prozess) darf die gelöschten Einträge danach
nicht zurückschreiben; Statistik liest den aktuellen Dateistand.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from services.downloader.models import DuplicateEntry
from services.duplicate.admin import (
    DuplicateCacheStats,
    clear_duplicate_cache,
    get_duplicate_cache_stats,
)
from services.duplicate.cache import DuplicateCache


def _entry(video_id: str, artist: str, title: str, when: datetime = None) -> DuplicateEntry:
    return DuplicateEntry(
        artist=artist,
        title=title,
        url=f"https://www.youtube.com/watch?v={video_id}",
        file_path=None,
        download_date=when or datetime.now(),
    )


def test_stats_on_empty_cache(tmp_path):
    stats = get_duplicate_cache_stats(DuplicateCache(cache_dir=str(tmp_path)))

    assert stats == DuplicateCacheStats(
        url_entries=0, content_entries=0, oldest_entry=None, newest_entry=None
    )


def test_stats_counts_entries_and_date_range(tmp_path):
    cache = DuplicateCache(cache_dir=str(tmp_path))
    old = datetime(2026, 1, 1, 12, 0, 0)
    new = old + timedelta(days=10)
    cache.add_entry(_entry("AAA1", "A", "Eins", old))
    cache.add_entry(_entry("BBB2", "B", "Zwei", new))

    stats = get_duplicate_cache_stats(cache)

    assert (stats.url_entries, stats.content_entries) == (2, 2)
    assert stats.oldest_entry == old.isoformat()
    assert stats.newest_entry == new.isoformat()


def test_stats_see_entries_written_by_other_instance(tmp_path):
    long_lived = DuplicateCache(cache_dir=str(tmp_path))
    DuplicateCache(cache_dir=str(tmp_path)).add_entry(_entry("WEB1", "A", "Web"))

    assert get_duplicate_cache_stats(long_lived).url_entries == 1


def test_clear_removes_files_and_memory(tmp_path):
    cache = DuplicateCache(cache_dir=str(tmp_path))
    cache.add_entry(_entry("AAA1", "A", "Eins"))
    cache.add_entry(_entry("BBB2", "B", "Zwei"))

    result = clear_duplicate_cache(cache)

    assert (result.url_entries_removed, result.content_entries_removed) == (2, 2)
    assert result.deleted_files == ["url_duplicates.json", "content_duplicates.json"]
    assert not cache.url_cache_file.exists() and not cache.content_cache_file.exists()
    assert cache.url_cache == {} and cache.content_cache == {}


def test_clear_without_files(tmp_path):
    result = clear_duplicate_cache(DuplicateCache(cache_dir=str(tmp_path)))

    assert (result.url_entries_removed, result.content_entries_removed) == (0, 0)
    assert result.deleted_files == []


def test_clear_counts_entries_of_other_instance(tmp_path):
    """Gezählt wird der aktuelle Dateistand (Lock + Neu laden), nicht der
    veraltete Speicherstand der aufrufenden Instanz."""
    long_lived = DuplicateCache(cache_dir=str(tmp_path))
    DuplicateCache(cache_dir=str(tmp_path)).add_entry(_entry("WEB1", "A", "Web"))

    result = clear_duplicate_cache(long_lived)

    assert result.url_entries_removed == 1


def test_other_instance_does_not_resurrect_cleared_entries(tmp_path):
    other = DuplicateCache(cache_dir=str(tmp_path))
    other.add_entry(_entry("OLD1", "A", "Alt"))
    clearer = DuplicateCache(cache_dir=str(tmp_path))

    clear_duplicate_cache(clearer)
    other.add_entry(_entry("NEW1", "B", "Neu"))

    assert get_duplicate_cache_stats(clearer).url_entries == 1
    assert other.check_url_duplicate("https://www.youtube.com/watch?v=OLD1") is None
