"""
DUP-01 + DUP-08 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md /
docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE1_PLAN.md):

DUP-01: klassen/download_handler.py::handle_playlist_success() rief bisher
ausschliesslich handle_single_track_success() mit dem Playlist-Wrapper auf.
Dessen "artist" ist strukturell immer "?" (kein eigenes Artist-Feld auf dem
Wrapper) - die bestehende Guard-Bedingung in handle_single_track_success()
unterdrueckte die Registrierung dadurch fuer JEDEN Playlist-Track. Ein
bereits heruntergeladener Track konnte dadurch bei erneuter Anfrage (Single
oder andere Playlist) unbegrenzt oft erneut heruntergeladen werden.

DUP-08: das bereits pro Track vorhandene renamed_due_to_conflict-Signal
(seit dem Finding-2-Fix in Baseline v4/v5 korrekt in jedem Track-Dict
gesetzt) wurde im Playlist-Erfolgspfad nie ausgewertet, da nur der
Wrapper selbst (der das Feld nie traegt) geprueft wurde.

Fix: klassen/download_handler.py::_register_playlist_track_duplicates()
iteriert die tatsaechlichen Track-Dicts (tracks[i]) statt den Wrapper zu
verwenden, registriert jeden erfolgreichen Track mit seiner EIGENEN
Identitaet und behandelt renamed_due_to_conflict pro Track, ohne die
Verarbeitung der uebrigen Tracks zu unterbrechen.

Nutzt eine REALE DuplicateDetector-Instanz (wie tests/test_duplicate_handler.py)
statt Mocks, um echten Cache-Zustand statt nur Funktionsaufrufe zu pruefen.
DownloadHandler hat einen schweren Konstruktor - object.__new__() umgeht ihn
bewusst (etabliertes Muster dieser Session).
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from klassen.download_handler import DownloadHandler
from services.downloader.download_result_reporter import DownloadResultReporter
from services.duplicate.detector import DuplicateDetector


def run_async(coro):
    return asyncio.run(coro)


class FakeConfig:
    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")


def make_handler(tmp_path):
    handler = object.__new__(DownloadHandler)
    handler.logger = Mock()
    handler.duplicate_detector = DuplicateDetector(FakeConfig(tmp_path))
    handler.result_reporter = DownloadResultReporter(logger=Mock())

    status_msg = Mock()
    status_msg.edit_text = AsyncMock()
    handler.status_msg = status_msg
    handler.update = Mock()
    handler.update.message = Mock()
    handler.update.message.reply_text = AsyncMock(return_value=status_msg)

    return handler


def make_track(
    tmp_path,
    artist,
    title,
    url,
    filename,
    success=True,
    renamed_due_to_conflict=False,
    create_file=True,
):
    library_path = tmp_path / "library" / filename
    if create_file:
        library_path.parent.mkdir(parents=True, exist_ok=True)
        library_path.write_bytes(b"fake-audio-bytes")
    return {
        "success": success,
        "title": title,
        "artist": artist,
        "album": "Some Album",
        "album_artist": artist,
        "year": 2024,
        "genres": None,
        "genre_source": None,
        "library_path": str(library_path),
        "url": url,
        "artist_source": "uploader",
        "title_cleaned": False,
        "playlist_album": "Some Album",
        "track_number": 1,
        "lyrics_available": False,
        "lyrics_source": None,
        "cover_embedded": False,
        "is_duplicate": False,
        "from_cache": False,
        "renamed_due_to_conflict": renamed_due_to_conflict,
        "error": None,
    }


def make_playlist_results(tracks):
    return [
        {
            "success": True,
            "type": "playlist",
            "title": "Playlist",
            "tracks": tracks,
            "processing_stats": {},
        }
    ]


class TestPlaylistTrackRegistration:
    def test_successful_playlist_track_is_registered_with_its_own_identity(
        self, tmp_path
    ):
        """Test A + B: der registrierte Eintrag muss die TATSAECHLICHE
        Track-Identitaet tragen, nicht die Playlist-Wrapper-Werte ("?")."""
        handler = make_handler(tmp_path)
        track = make_track(
            tmp_path,
            "Real Artist",
            "Real Song",
            "https://www.youtube.com/watch?v=REAL111",
            "Real Song.mp3",
        )

        run_async(handler.handle_playlist_success(make_playlist_results([track])))

        is_dup, entry, reason = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=REAL111"
        )
        assert is_dup is True
        assert reason == "url"
        assert entry.artist == "Real Artist"
        assert entry.artist != "?"

    def test_playlist_track_duplicate_is_detected_on_later_single_download(
        self, tmp_path
    ):
        """Test D (wichtigster End-to-End-Fall): Playlist-Track erfolgreich
        verarbeitet -> Registrierung -> ein spaeterer EINZEL-Download-Check
        (andere URL, gleicher Content) muss als Duplikat erkannt werden."""
        handler = make_handler(tmp_path)
        track = make_track(
            tmp_path,
            "Reupload Artist",
            "Reupload Song",
            "https://www.youtube.com/watch?v=ORIG222",
            "Reupload Song.mp3",
        )

        run_async(handler.handle_playlist_success(make_playlist_results([track])))

        # Anderer Video-Upload (andere URL) desselben Songs, wie er beim
        # Duplicate-Pre-Check (Finding 1, Baseline v5) fuer einen neuen
        # Einzel-Download ankaeme.
        is_dup, entry, reason = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=REUP333",
            raw_artist="Reupload Artist",
            raw_title="Reupload Song",
        )
        assert is_dup is True
        assert reason == "content"

    def test_multiple_playlist_tracks_are_registered_independently(self, tmp_path):
        """Test C: mindestens 3 Tracks, alle erfolgreich -> jeder erhaelt
        einen eigenen Cache-Eintrag."""
        handler = make_handler(tmp_path)
        tracks = [
            make_track(
                tmp_path, "Artist A", "Song A",
                "https://www.youtube.com/watch?v=AAA001", "Song A.mp3",
            ),
            make_track(
                tmp_path, "Artist B", "Song B",
                "https://www.youtube.com/watch?v=BBB002", "Song B.mp3",
            ),
            make_track(
                tmp_path, "Artist C", "Song C",
                "https://www.youtube.com/watch?v=CCC003", "Song C.mp3",
            ),
        ]

        run_async(handler.handle_playlist_success(make_playlist_results(tracks)))

        for url, artist in [
            ("https://www.youtube.com/watch?v=AAA001", "Artist A"),
            ("https://www.youtube.com/watch?v=BBB002", "Artist B"),
            ("https://www.youtube.com/watch?v=CCC003", "Artist C"),
        ]:
            is_dup, entry, reason = handler.duplicate_detector.check_for_duplicates(url)
            assert is_dup is True, f"Track fuer {url} wurde nicht registriert"
            assert entry.artist == artist

    def test_one_failed_track_does_not_prevent_registration_of_others(self, tmp_path):
        """Track B schlaegt fehl (success=False) - A und C muessen trotzdem
        registriert werden."""
        handler = make_handler(tmp_path)
        track_a = make_track(
            tmp_path, "Artist A", "Song A",
            "https://www.youtube.com/watch?v=FAA001", "Song A.mp3",
        )
        track_b = make_track(
            tmp_path, "Artist B", "Song B",
            "https://www.youtube.com/watch?v=FBB002", "Song B.mp3",
            success=False,
        )
        track_c = make_track(
            tmp_path, "Artist C", "Song C",
            "https://www.youtube.com/watch?v=FCC003", "Song C.mp3",
        )

        run_async(
            handler.handle_playlist_success(
                make_playlist_results([track_a, track_b, track_c])
            )
        )

        is_dup_a, _, _ = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=FAA001"
        )
        is_dup_c, _, _ = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=FCC003"
        )
        is_dup_b, _, _ = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=FBB002"
        )
        assert is_dup_a is True
        assert is_dup_c is True
        assert is_dup_b is False  # nie registriert, war nicht erfolgreich


class TestPlaylistTrackCollisionSignal:
    def test_track_with_collision_is_cleaned_up_and_not_registered(self, tmp_path):
        """Test E: ein Track mit renamed_due_to_conflict=True wird bereinigt
        (Datei geloescht) statt als neuer Eintrag registriert zu werden."""
        handler = make_handler(tmp_path)
        track = make_track(
            tmp_path,
            "Collided Artist",
            "Collided Song",
            "https://www.youtube.com/watch?v=COLL001",
            "Collided Song (1).mp3",
            renamed_due_to_conflict=True,
        )
        library_file = Path(track["library_path"])
        assert library_file.exists()

        run_async(handler.handle_playlist_success(make_playlist_results([track])))

        assert not library_file.exists(), "Kollidierte Datei wurde nicht geloescht"
        is_dup, entry, reason = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=COLL001"
        )
        assert is_dup is False, "Kollidierter Track darf nicht als eigener Eintrag registriert werden"

    def test_mixed_playlist_collision_only_affects_the_colliding_track(self, tmp_path):
        """Test F: A normal, B kollidiert, C normal - nur B ist betroffen,
        A und C werden unveraendert registriert."""
        handler = make_handler(tmp_path)
        track_a = make_track(
            tmp_path, "Artist A", "Song A",
            "https://www.youtube.com/watch?v=MAA001", "Song A.mp3",
        )
        track_b = make_track(
            tmp_path, "Artist B", "Song B",
            "https://www.youtube.com/watch?v=MBB002", "Song B (1).mp3",
            renamed_due_to_conflict=True,
        )
        track_c = make_track(
            tmp_path, "Artist C", "Song C",
            "https://www.youtube.com/watch?v=MCC003", "Song C.mp3",
        )
        library_file_b = Path(track_b["library_path"])

        run_async(
            handler.handle_playlist_success(
                make_playlist_results([track_a, track_b, track_c])
            )
        )

        is_dup_a, entry_a, _ = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=MAA001"
        )
        is_dup_c, entry_c, _ = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=MCC003"
        )
        is_dup_b, _, _ = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=MBB002"
        )

        assert is_dup_a is True
        assert entry_a.artist == "Artist A"
        assert is_dup_c is True
        assert entry_c.artist == "Artist C"
        assert is_dup_b is False
        assert not library_file_b.exists()

    def test_collision_does_not_falsely_propagate_to_sibling_tracks(self, tmp_path):
        """Test G: Track B kollidiert - Track A/C duerfen NICHT ebenfalls als
        renamed_due_to_conflict behandelt werden (ihre Dateien bleiben
        bestehen, sie werden ganz normal registriert)."""
        handler = make_handler(tmp_path)
        track_a = make_track(
            tmp_path, "Artist A", "Song A",
            "https://www.youtube.com/watch?v=GAA001", "Song A.mp3",
        )
        track_b = make_track(
            tmp_path, "Artist B", "Song B",
            "https://www.youtube.com/watch?v=GBB002", "Song B (1).mp3",
            renamed_due_to_conflict=True,
        )
        track_c = make_track(
            tmp_path, "Artist C", "Song C",
            "https://www.youtube.com/watch?v=GCC003", "Song C.mp3",
        )
        library_file_a = Path(track_a["library_path"])
        library_file_c = Path(track_c["library_path"])

        run_async(
            handler.handle_playlist_success(
                make_playlist_results([track_a, track_b, track_c])
            )
        )

        assert library_file_a.exists(), "Track A darf nicht faelschlich bereinigt werden"
        assert library_file_c.exists(), "Track C darf nicht faelschlich bereinigt werden"
