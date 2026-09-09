# -*- coding: utf-8 -*-
"""
ARCH — Artist Identity Resolution & Mapping Separation
=====================================================

PHASE B — Schritt 10 (AutoLearn-Gate am known-Flag) + Schritt 12
              (Self-Registration-Fallback entfernt)

Prüft am echten EnhancedMetadataProcessor:
  * known=True  (Identität aus known_artists.yaml / Override / Library) →
    KEIN Aufruf von AutoLearnManager.learn_artist()
  * known=False (nur Parser-Kandidat) + uploader ähnelt dem Artist →
    learn_artist() wird mit source=_candidate_source aufgerufen
  * known=False + uploader = Repost-Kanal (ähnelt NICHT) →
    KEIN learn_artist()-Aufruf, KEINE Self-Registrierung in known_artists.yaml
    (Finding F-04 – der uncommittete Fallback ist entfernt)
"""

import asyncio
from types import SimpleNamespace

import pytest

from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
from utils.audio_enhancer import AudioEnhancer
from utils.filenamefixer import FilenameFixerTool


def _cfg(tmp_path, mapping_dir):
    return SimpleNamespace(
        LIBRARY_DIR=tmp_path / "library",
        DOWNLOAD_DIR=tmp_path / "downloads",
        FAIL_DIR=tmp_path / "fail",
        PROCESSED_DIR=tmp_path / "processed",
        TEMP_DIR=tmp_path / "temp",
        LOG_DIR=tmp_path / "logs",
        GENRE_MAPPING_DIR=mapping_dir,
        ARTIST_OVERRIDE_FILE=tmp_path / "artist_overrides.json",
        METADATA_CACHE_DIR=tmp_path / "metadata_cache",
        DUPLICATE_CACHE_DIR=tmp_path / "duplicate_cache",
        FANART_API_KEY=None,
    )


@pytest.fixture
def processor(tmp_path, mapping_dir_copy, monkeypatch):
    monkeypatch.setattr(
        "services.metadata.loudness_replaygain.apply_replaygain_tags",
        lambda *a, **kw: (True, -5.0),
    )
    proc = EnhancedMetadataProcessor(_cfg(tmp_path, mapping_dir_copy))

    class _FakeExternal:
        async def fetch_metadata(self, *a, **kw):
            return {}

    proc._mb_client = _FakeExternal()
    proc._lfm_client = _FakeExternal()

    async def _no_lyrics(*a, **kw):
        return None, None

    async def _no_album(*a, **kw):
        return None

    monkeypatch.setattr(
        proc.lyrics_processor, "fetch_lyrics_with_fallback", _no_lyrics
    )
    monkeypatch.setattr(
        proc.album_processor, "fetch_album_from_musicbrainz", _no_album
    )

    # learn_artist-Aufrufe aufzeichnen statt ausführen
    calls = []

    async def _record_learn_artist(**kwargs):
        calls.append(kwargs)
        return False

    monkeypatch.setattr(proc.auto_learn_manager, "learn_artist", _record_learn_artist)
    proc._learn_artist_calls = calls
    return proc


@pytest.fixture
def filename_fixer(tmp_path, mapping_dir_copy):
    return FilenameFixerTool(_cfg(tmp_path, mapping_dir_copy))


def _run(proc, filename_fixer, tmp_path, *, title, artist, uploader, vid):
    src = tmp_path / f"{vid}.mp3"
    src.write_bytes(b"fake-audio-bytes-not-real-mp3-data")
    return asyncio.run(
        proc.process_single_track(
            track_metadata={
                "title": title,
                "artist": artist,
                "uploader": uploader,
                "channel": uploader,
                "id": vid,
                "filepath": str(src),
                "cover_art": b"fake-cover-bytes",
                "genre": "Pop",
            },
            filename_fixer=filename_fixer,
        )
    )


def test_known_identity_skips_artist_autolearn(processor, filename_fixer, tmp_path):
    known = processor.artist_identity_resolver._mapping_dir / "known_artists.yaml"
    base = known.read_text(encoding="utf-8") if known.exists() else "known_artists:\n"
    known.write_text(base + "- Testkuenstler Bekannt\n", encoding="utf-8")
    processor.artist_identity_resolver.refresh()

    result = _run(
        processor,
        filename_fixer,
        tmp_path,
        title="Testkuenstler Bekannt - Ein Lied (Official Video)",
        artist="Testkuenstler Bekannt",
        uploader="Testkuenstler Bekannt",
        vid="KNOWN001",
    )

    assert result.artist_known is True
    assert result.artist_source == "known_artist"
    assert processor._learn_artist_calls == []


def test_unknown_identity_with_matching_uploader_learns_alias(
    processor, filename_fixer, tmp_path
):
    result = _run(
        processor,
        filename_fixer,
        tmp_path,
        title="NeuerKuenstlerXY - Song (Official Video)",
        artist="NeuerKuenstlerXY",
        uploader="NeuerKuenstlerXY",
        vid="UNK001",
    )

    assert result.artist_known is False
    assert result.artist_source == "parser"
    assert len(processor._learn_artist_calls) == 1
    call = processor._learn_artist_calls[0]
    assert call["canonical_name"] == result.artist
    assert call["source"] == "youtube_parsed"


def test_unknown_identity_repost_channel_does_not_learn_or_self_register(
    processor, filename_fixer, tmp_path
):
    known = processor.artist_identity_resolver._mapping_dir / "known_artists.yaml"
    before = known.read_text(encoding="utf-8") if known.exists() else ""

    result = _run(
        processor,
        filename_fixer,
        tmp_path,
        title="Irgendein Act - Irgendein Song (Official Video)",
        artist="ICH FIND SCHLAGER TOLL",
        uploader="ICH FIND SCHLAGER TOLL",
        vid="REPOST01",
    )

    assert result.artist == "Irgendein Act"
    assert result.artist_known is False
    # kein learn_artist()-Aufruf (raw_name_for_learning liefert "")
    assert processor._learn_artist_calls == []
    # F-04: keine Self-Registrierung in known_artists.yaml
    after = known.read_text(encoding="utf-8") if known.exists() else ""
    assert "Irgendein Act" not in after
    assert after == before
