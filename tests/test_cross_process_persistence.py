# tests/test_cross_process_persistence.py
# -*- coding: utf-8 -*-
"""
D.13 — prozessübergreifend sicheres Schreiben für DownloadHistoryStore und
DuplicateCache.

Ausgangsbefund (reproduziert 2026-09-28): beide Klassen laden ihre Datei
nur im Konstruktor und schreiben bei jeder Änderung den kompletten
In-Memory-Stand zurück. Der Bot hält EINE langlebige Instanz, das Control
Center erzeugt pro Job eine neue - dadurch überschreibt jeder Telegram-
Download die Einträge aller Web-Downloads seit dem Bot-Start (Lost Update,
ohne dass echte Gleichzeitigkeit nötig ist). Zwei Instanzen auf demselben
Verzeichnis bilden hier genau diese beiden Prozesse nach; die
multiprocessing-Tests prüfen zusätzlich echte Parallelität. Bewusst
"spawn" statt "fork": ein geforkter Kindprozess erbt den kompletten
Zustand der laufenden pytest-Sitzung (inkl. Aufräum-Finalizer anderer
Tests) - beobachtet als sporadischer Seiteneffekt auf
tests/test_resolve_duplicates.py im grossen Lauf.
"""

from __future__ import annotations

import json
import multiprocessing
from datetime import datetime
from pathlib import Path

from services.downloader.download_history import DownloadHistoryStore
from services.downloader.models import DuplicateEntry
from services.duplicate.cache import DuplicateCache


def _entry(video_id: str, artist: str, title: str) -> DuplicateEntry:
    return DuplicateEntry(
        artist=artist,
        title=title,
        url=f"https://www.youtube.com/watch?v={video_id}",
        file_path=None,
        download_date=datetime.now(),
    )


def _history_titles(cache_dir: Path, chat_id: int = 77):
    data = json.loads((cache_dir / "download_history.json").read_text(encoding="utf-8"))
    return [e["title"] for e in data.get(str(chat_id), [])]


def _url_titles(cache_dir: Path):
    data = json.loads((cache_dir / "url_duplicates.json").read_text(encoding="utf-8"))
    return sorted(v["title"] for v in data.values())


def _content_titles(cache_dir: Path):
    data = json.loads((cache_dir / "content_duplicates.json").read_text(encoding="utf-8"))
    return sorted(v["title"] for v in data.values())


# ─────────────────────────────────────────────────────────────────────────
# DownloadHistoryStore
# ─────────────────────────────────────────────────────────────────────────


def test_history_long_lived_instance_does_not_overwrite_other_writer(tmp_path):
    bot = DownloadHistoryStore(cache_dir=str(tmp_path))  # langlebig (Bot)
    cc = DownloadHistoryStore(cache_dir=str(tmp_path))  # pro Job (CC)

    cc.add_entry(77, url="u-web", title="Web", artist="A", status="success")
    bot.add_entry(77, url="u-tg", title="Telegram", artist="B", status="success")

    assert _history_titles(tmp_path) == ["Web", "Telegram"]


def test_history_long_lived_instance_sees_entries_of_other_writer(tmp_path):
    bot = DownloadHistoryStore(cache_dir=str(tmp_path))
    DownloadHistoryStore(cache_dir=str(tmp_path)).add_entry(
        77, url="u-web", title="Web", artist="A", status="success"
    )

    assert [e.title for e in bot.get_recent(77)] == ["Web"]
    assert [e.title for _cid, e in bot.get_all_recent()] == ["Web"]


def test_history_corrupt_file_on_reload_keeps_in_memory_state(tmp_path):
    store = DownloadHistoryStore(cache_dir=str(tmp_path))
    store.add_entry(77, url="u1", title="Eins", artist="A", status="success")
    (tmp_path / "download_history.json").write_text("{kaputt", encoding="utf-8")

    assert [e.title for e in store.get_recent(77)] == ["Eins"]


def _history_worker(cache_dir: str, chat_id: int, count: int, barrier) -> None:
    store = DownloadHistoryStore(cache_dir=cache_dir)
    barrier.wait(10)  # beide Prozesse haben geladen -> echte Überschneidung
    for i in range(count):
        store.add_entry(chat_id, url=f"u{chat_id}-{i}", title=f"{chat_id}-{i}", artist="A", status="success")


def test_history_parallel_processes_lose_no_entries(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    procs = [
        ctx.Process(target=_history_worker, args=(str(tmp_path), cid, 10, barrier))
        for cid in (1, 2)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
        assert p.exitcode == 0

    assert len(_history_titles(tmp_path, 1)) == 10
    assert len(_history_titles(tmp_path, 2)) == 10


# ─────────────────────────────────────────────────────────────────────────
# DuplicateCache
# ─────────────────────────────────────────────────────────────────────────


def test_duplicate_cache_long_lived_instance_does_not_overwrite_other_writer(tmp_path):
    bot = DuplicateCache(cache_dir=str(tmp_path))
    cc = DuplicateCache(cache_dir=str(tmp_path))

    cc.add_entry(_entry("WEB1", "A", "Web"))
    bot.add_entry(_entry("TG1", "B", "Telegram"))

    assert _url_titles(tmp_path) == ["Telegram", "Web"]
    assert _content_titles(tmp_path) == ["Telegram", "Web"]


def test_duplicate_cache_long_lived_instance_detects_entry_of_other_writer(tmp_path):
    bot = DuplicateCache(cache_dir=str(tmp_path))
    DuplicateCache(cache_dir=str(tmp_path)).add_entry(_entry("WEB1", "A", "Web"))

    assert bot.check_url_duplicate("https://youtu.be/WEB1") is not None
    assert bot.check_content_duplicate("A", "Web") is not None


def test_duplicate_cache_read_hit_does_not_drop_foreign_entries(tmp_path):
    """check_*_duplicate() speichert bei einem Treffer (duplicate_count) -
    auch dieser Schreibpfad darf fremde Einträge nicht überschreiben."""
    bot = DuplicateCache(cache_dir=str(tmp_path))
    bot.add_entry(_entry("TG1", "B", "Telegram"))
    DuplicateCache(cache_dir=str(tmp_path)).add_entry(_entry("WEB1", "A", "Web"))

    hit = bot.check_url_duplicate("https://www.youtube.com/watch?v=TG1")

    assert hit is not None
    assert _url_titles(tmp_path) == ["Telegram", "Web"]


def test_duplicate_cache_deleted_files_are_not_resurrected(tmp_path):
    """Telegram "Cache leeren" löscht die Dateien - eine andere Instanz
    darf die alten Einträge beim nächsten Schreiben nicht zurückholen."""
    bot = DuplicateCache(cache_dir=str(tmp_path))
    bot.add_entry(_entry("OLD1", "A", "Alt"))
    other = DuplicateCache(cache_dir=str(tmp_path))
    (tmp_path / "url_duplicates.json").unlink()
    (tmp_path / "content_duplicates.json").unlink()

    other.add_entry(_entry("NEW1", "B", "Neu"))

    assert _url_titles(tmp_path) == ["Neu"]
    assert bot.check_url_duplicate("https://www.youtube.com/watch?v=OLD1") is None


def test_duplicate_cache_corrupt_file_on_reload_keeps_in_memory_state(tmp_path):
    cache = DuplicateCache(cache_dir=str(tmp_path))
    cache.add_entry(_entry("KEEP1", "A", "Bleibt"))
    (tmp_path / "url_duplicates.json").write_text("{kaputt", encoding="utf-8")

    assert cache.check_url_duplicate("https://www.youtube.com/watch?v=KEEP1") is not None


def _duplicate_worker(cache_dir: str, prefix: str, count: int, barrier) -> None:
    cache = DuplicateCache(cache_dir=cache_dir)
    barrier.wait(10)  # beide Prozesse haben geladen -> echte Überschneidung
    for i in range(count):
        cache.add_entry(_entry(f"{prefix}{i}", prefix, f"{prefix}-{i}"))


def test_duplicate_cache_parallel_processes_lose_no_entries(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    procs = [
        ctx.Process(target=_duplicate_worker, args=(str(tmp_path), p, 15, barrier))
        for p in ("A", "B")
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
        assert p.exitcode == 0

    assert len(_url_titles(tmp_path)) == 30
    assert len(_content_titles(tmp_path)) == 30
