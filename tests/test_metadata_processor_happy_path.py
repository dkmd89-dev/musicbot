"""
E2E-001: Reproduzierbarer Happy Path durch die Metadata-Pipeline.

Verkettet echte Produktionsklassen end-to-end:
    DuplicateDetector.check_for_duplicates (kein Duplikat)
        -> EnhancedMetadataProcessor.process_single_track
        -> FilenameFixerTool.move_to_library (intern aufgerufen)
        -> DuplicateDetector.register_download + erneuter Check (jetzt Duplikat)

Gefakt werden ausschliesslich externe Dienste (MusicBrainz, Last.fm,
Genius/Lyrics, Cover-Art-Netzwerk-Lookup, FFmpeg-Subprocess) - siehe
Regel 7 ("Externe Services in Unit-Tests mocken/faken"). Alle
Sub-Prozessoren (ArtistProcessor, TitleCleaner, GenreProcessor,
AlbumProcessor, GenreMapper, ArtistNormalizer, FilenameFixerTool) laufen
echt, inklusive echter YAML-Genre-/Artist-Regeln aus einer tmp-Kopie von
mapping/ (siehe conftest.py: mapping_dir_copy) - damit AutoLearnManager
niemals die echten Mapping-Dateien im Repo veraendert.

Kein echtes, dekodierbares Audio noetig: AudioEnhancer.normalize_loudness
ist gefakt (FFmpeg ist eine Umgebungsabhaengigkeit, kein fuer diesen Test
relevanter Kern-Pfad - ein Fehlschlag dort ist laut Code ohnehin nicht
kritisch), move_to_library macht ein reines Dateisystem-Move, und der
MP3-Tag-Schreibpfad in _write_metadata_to_file_with_lyrics faengt ein
ungueltiges ID3-Header ab und schreibt stattdessen einen leeren
ID3()-Tag - funktioniert nachweislich auch auf einer Dummy-Datei.
"""

import asyncio
from pathlib import Path

import pytest

from services.duplicate.detector import DuplicateDetector
from services.metadata.enhanced_metadata_processor import (
    EnhancedMetadataProcessor,
)
from utils.audio_enhancer import AudioEnhancer
from utils.filenamefixer import FilenameFixerTool


class HappyPathConfig:
    """Config-Attribute, die EnhancedMetadataProcessor._do_init,
    FilenameFixerTool._do_init und DuplicateDetector tatsaechlich
    lesen - alle Verzeichnisse zeigen auf tmp_path, GENRE_MAPPING_DIR auf
    eine tmp-Kopie des echten mapping/-Verzeichnisses (siehe Modul-Docstring)."""

    def __init__(self, tmp_path: Path, mapping_dir: Path):
        self.LIBRARY_DIR = tmp_path / "library"
        self.DOWNLOAD_DIR = tmp_path / "downloads"
        self.FAIL_DIR = tmp_path / "fail"
        self.PROCESSED_DIR = tmp_path / "processed"
        self.TEMP_DIR = tmp_path / "temp"
        self.LOG_DIR = tmp_path / "logs"
        self.GENRE_MAPPING_DIR = mapping_dir
        self.ARTIST_OVERRIDE_FILE = tmp_path / "artist_overrides.json"
        self.METADATA_CACHE_DIR = tmp_path / "metadata_cache"
        self.DUPLICATE_CACHE_DIR = tmp_path / "duplicate_cache"
        self.FANART_API_KEY = None


class FakeExternalClient:
    """Faked MusicBrainz-/Last.fm-Client: liefert 'kein Treffer'."""

    async def fetch_metadata(self, *args, **kwargs):
        return {}


class CountingFakeExternalClient(FakeExternalClient):
    """Wie FakeExternalClient, zaehlt aber Aufrufe - fuer den TEST-003-Beweis,
    dass ein Cache-Hit externe Service-Aufrufe tatsaechlich ueberspringt."""

    def __init__(self):
        self.call_count = 0

    async def fetch_metadata(self, *args, **kwargs):
        self.call_count += 1
        return await super().fetch_metadata(*args, **kwargs)


@pytest.fixture
def happy_path_config(tmp_path, mapping_dir_copy):
    return HappyPathConfig(tmp_path, mapping_dir_copy)


@pytest.fixture
def processor(happy_path_config, monkeypatch):
    # Schritt 15b ruft seit der Pipeline-Optimierung 2026-09-09
    # services.metadata.loudness_replaygain.apply_replaygain_tags (ReplayGain-
    # Tag statt Re-Encode) - hier gefakt (kein rsgain/ffmpeg im Unit-Test).
    monkeypatch.setattr(
        "services.metadata.loudness_replaygain.apply_replaygain_tags",
        lambda *a, **kw: (True, -5.0),
    )

    proc = EnhancedMetadataProcessor(happy_path_config)

    proc._mb_client = FakeExternalClient()
    proc._lfm_client = FakeExternalClient()

    async def fake_fetch_lyrics(*args, **kwargs):
        return None, None

    async def fake_fetch_album_from_musicbrainz(*args, **kwargs):
        return None

    monkeypatch.setattr(
        proc.lyrics_processor, "fetch_lyrics_with_fallback", fake_fetch_lyrics
    )
    monkeypatch.setattr(
        proc.album_processor,
        "fetch_album_from_musicbrainz",
        fake_fetch_album_from_musicbrainz,
    )

    return proc


@pytest.fixture
def filename_fixer(happy_path_config):
    return FilenameFixerTool(happy_path_config)


@pytest.fixture
def duplicate_handler(happy_path_config):
    return DuplicateDetector(happy_path_config)


def test_happy_path_end_to_end(
    processor, filename_fixer, duplicate_handler, happy_path_config, tmp_path
):
    url = "https://www.youtube.com/watch?v=HAPPY123"
    source = tmp_path / "downloaded.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    track_metadata = {
        "title": "Happy Artist - Happy Song (Official Video)",
        "artist": "Happy Artist",
        "uploader": "Happy Artist",
        "channel": "Happy Artist",
        "id": "HAPPY123",
        "filepath": str(source),
        "cover_art": b"fake-cover-bytes",
        "genre": "Hip Hop",
    }

    # Schritt 1: Duplicate-Check vor dem ersten Download - kein Duplikat.
    is_dup, _entry, reason = duplicate_handler.check_for_duplicates(
        url, raw_artist="Happy Artist", raw_title="Happy Song"
    )
    assert is_dup is False
    assert reason == "none"

    # Schritt 2: Volle Metadata-Pipeline.
    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is True
    assert result.error is None
    assert result.from_cache is False
    assert result.is_duplicate is False
    assert result.artist == "Happy Artist"
    assert result.title

    assert result.library_path is not None
    library_path = Path(result.library_path)
    assert library_path.exists()
    assert library_path.is_relative_to(happy_path_config.LIBRARY_DIR)

    # Schritt 3: Nach erfolgreichem Download registrieren - ein zweiter
    # Versuch derselben URL muss jetzt als Duplikat erkannt werden.
    duplicate_handler.register_download(
        url, result.artist, result.title, file_path=library_path
    )
    is_dup_again, entry, reason_again = duplicate_handler.check_for_duplicates(url)
    assert is_dup_again is True
    assert reason_again == "url"
    assert entry.artist == result.artist


def test_happy_path_artist_with_ft_substring_and_genuine_feat_is_not_mangled(
    processor, filename_fixer, tmp_path
):
    """
    Regressions-Tripwire fuer die Klasse von Fehlern hinter ARTISTNORM-001/
    ARTISTNORM-002 (siehe tests/test_split_main_and_featuring.py::
    TestArtistnorm002WordBoundaryFix und die Doku in
    tests/test_autolearn_special_channel_gate.py): ein Artist-String, der
    "ft" nur als Teilstring UND zusaetzlich ein echtes "feat."-Keyword
    enthaelt, muss durch die volle Pipeline (process_single_track() ->
    ArtistProcessor.determine_best_artist() -> split_main_and_featuring())
    unbeschaedigt als Hauptartist "Kraftklub" hervorgehen - nicht als
    "Kraft" (faelschliches Auftrennen am Teilstring "ft" in "Kraftklub")
    und nicht als der komplette, ungetrennte String inkl. "feat. Marteria".

    test_happy_path_end_to_end() oben deckt diesen Pfad nicht ab (Fixture-
    Artist "Happy Artist" enthaelt kein "ft"/"feat") - dieser Test schliesst
    genau diese Luecke, damit ein kuenftiges Wiederauftreten der ARTISTNORM-
    001/002-Fehlerklasse sofort im Happy-Path auffaellt statt nur in den
    dedizierten Unit-Tests von split_main_and_featuring().
    """
    source = tmp_path / "kraftklub.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    track_metadata = {
        "title": "Kraftklub feat. Marteria - Test Song (Official Video)",
        "artist": "Kraftklub feat. Marteria",
        "uploader": "Kraftklub feat. Marteria",
        "channel": "Kraftklub feat. Marteria",
        "id": "FTSUBSTR1",
        "filepath": str(source),
        "cover_art": b"fake-cover-bytes",
        "genre": "Hip Hop",
    }

    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is True
    assert result.artist == "Kraftklub"


def test_second_call_with_same_video_id_is_a_cache_hit(
    processor, filename_fixer, tmp_path
):
    """
    TEST-003-Beweis: process_single_track() zweimal mit identischer
    track_metadata["id"] aufrufen. Der zweite Aufruf muss ein echter
    Cache-Hit sein (from_cache=True) UND die externen Service-Clients duerfen
    NICHT erneut aufgerufen werden - das ist der eigentliche Zweck des Fixes
    (vorher lief bei jedem Aufruf immer die volle Pipeline).

    Die urspruengliche Quelldatei existiert beim zweiten Aufruf bereits
    nicht mehr (move_to_library() hat sie beim ersten Durchlauf real in die
    Library verschoben) - ein Cache-Hit kehrt in process_single_track()
    aber schon in Schritt 2 (von 20) zurueck, lange vor dem erneuten
    Dateisystem-Zugriff in Schritt 14. Dass der zweite Aufruf trotzdem
    erfolgreich ist, beweist, dass die volle Pipeline tatsaechlich
    uebersprungen wurde.
    """
    source = tmp_path / "cache_test.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    track_metadata = {
        "title": "Cache Artist - Cache Song (Official Video)",
        "artist": "Cache Artist",
        "uploader": "Cache Artist",
        "channel": "Cache Artist",
        "id": "CACHEHIT123",
        "filepath": str(source),
        "cover_art": b"fake-cover-bytes",
        "genre": "Hip Hop",
    }

    mb_client = CountingFakeExternalClient()
    processor._mb_client = mb_client

    first_result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )
    assert first_result.success is True
    assert first_result.from_cache is False
    assert mb_client.call_count >= 1
    calls_after_first_run = mb_client.call_count

    assert not source.exists()  # von move_to_library() bereits verschoben

    second_result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert second_result.success is True
    assert second_result.from_cache is True
    assert second_result.title == first_result.title
    assert second_result.artist == first_result.artist
    assert mb_client.call_count == calls_after_first_run


def test_cache_hit_after_redundant_redownload_cleans_up_orphaned_raw_file(
    processor, filename_fixer, happy_path_config, tmp_path
):
    """
    Live-Fund (docs/FINDINGS_INDEX.md, 'Metadata-Cache-Hit + Duplicate-Cache
    leer'): werden die Duplicate-Caches (url_duplicates.json/
    content_duplicates.json) fuer einen Track geleert, dessen Library-Datei
    aber noch existiert UND dessen metadata_cache-Eintrag noch vorhanden
    ist, verhindert nichts mehr einen erneuten Download derselben
    YouTube-ID - die Duplicate-Detection-Ebene wurde ja gerade geleert.
    process_single_track() liefert dann trotzdem einen Cache-Hit (Schritt 2
    von 20, lange vor move_to_library() in Schritt 16). Die frisch
    heruntergeladene zweite Rohdatei (track_metadata['filepath']) wurde
    dadurch nie beruehrt - weder verschoben noch aufgeraeumt - und blieb
    bisher bis zum naechsten 24h-Start-Sweep
    (download_artifact_cleanup.cleanup_download_artifacts) verwaist in
    Config.DOWNLOAD_DIR liegen, obwohl der Nutzer sofort "Download
    erfolgreich" mit dem (alten, weiterhin korrekten) Library-Pfad gemeldet
    bekommt.

    Reproduziert das Szenario direkt: zwei Aufrufe mit identischer
    track_metadata['id'], aber je einer eigenen physischen Rohdatei (wie
    bei zwei echten, unabhaengigen Downloads derselben URL). Der zweite
    Aufruf muss weiterhin ein Cache-Hit sein (Verhalten bleibt erhalten,
    siehe test_second_call_with_same_video_id_is_a_cache_hit), die zweite
    Rohdatei darf danach aber nicht mehr in DOWNLOAD_DIR liegen bleiben.
    """
    download_dir = happy_path_config.DOWNLOAD_DIR
    download_dir.mkdir(parents=True, exist_ok=True)

    source1 = download_dir / "erster_download.mp3"
    source1.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    track_metadata_1 = {
        "title": "Redundant Artist - Redundant Song (Official Video)",
        "artist": "Redundant Artist",
        "uploader": "Redundant Artist",
        "channel": "Redundant Artist",
        "id": "REDUNDANT123",
        "filepath": str(source1),
        "cover_art": b"fake-cover-bytes",
        "genre": "Hip Hop",
    }

    first_result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata_1,
            filename_fixer=filename_fixer,
        )
    )
    assert first_result.success is True
    assert first_result.from_cache is False
    assert Path(first_result.library_path).exists()

    # Simuliert den erneuten, redundanten Download derselben YouTube-ID
    # (Duplicate-Caches wurden zwischenzeitlich geleert) - eigene, zweite
    # physische Rohdatei in DOWNLOAD_DIR, wie es ein echter yt-dlp-Lauf
    # erzeugen wuerde.
    source2 = download_dir / "zweiter_redundanter_download.mp3"
    source2.write_bytes(b"fake-audio-bytes-not-real-mp3-data-zweiter-lauf")
    track_metadata_2 = dict(track_metadata_1, filepath=str(source2))

    second_result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata_2,
            filename_fixer=filename_fixer,
        )
    )

    assert second_result.success is True
    assert second_result.from_cache is True
    assert not source2.exists(), (
        "Verwaiste, redundante Rohdatei nach Cache-Hit wurde nicht "
        "aufgeraeumt - liegt bis zum naechsten 24h-Start-Sweep unnoetig "
        "in DOWNLOAD_DIR."
    )
    # Die urspruengliche Library-Datei aus dem ersten Durchlauf bleibt
    # unangetastet - der Cleanup darf nur die redundante Rohdatei treffen.
    assert Path(first_result.library_path).exists()


def test_missing_filepath_returns_graceful_failure(processor, filename_fixer):
    """
    Charakterisiert das globale try/except in process_single_track: ein
    fehlender 'filepath'-Schluessel loest intern ein ValueError aus, das
    NICHT nach aussen dringt, sondern als MetadataResult(success=False)
    zurueckkommt - wichtige Sicherheitsnetz-Eigenschaft der Pipeline.
    """
    track_metadata = {
        "title": "Some Artist - Some Song",
        "artist": "Some Artist",
        "uploader": "Some Artist",
        "channel": "Some Artist",
        "id": "NOFILE1",
    }

    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is False


def test_error_after_move_to_library_cleans_up_orphaned_source_file(
    processor, filename_fixer, happy_path_config, tmp_path, monkeypatch
):
    """
    Temp-Cleanup Strategie C (primaer, siehe
    services/downloader/download_artifact_cleanup.py): schlaegt
    move_to_library() fehl, nachdem original_path (Schritt 14) bereits
    gebunden wurde, muss der aeussere except-Block die verwaiste
    Quelldatei in DOWNLOAD_DIR gezielt aufraeumen - vorher gab es dafuer
    keinen einzigen Cleanup-Aufruf in der gesamten Pipeline.
    """
    download_dir = happy_path_config.DOWNLOAD_DIR
    download_dir.mkdir(parents=True, exist_ok=True)
    source = download_dir / "orphan_candidate.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    def _boom(self, *args, **kwargs):
        raise RuntimeError("simulierter move_to_library-Fehler")

    monkeypatch.setattr(filename_fixer.__class__, "move_to_library", _boom)

    track_metadata = {
        "title": "Orphan Artist - Orphan Song (Official Video)",
        "artist": "Orphan Artist",
        "uploader": "Orphan Artist",
        "channel": "Orphan Artist",
        "id": "ORPHAN1",
        "filepath": str(source),
        "genre": "Hip Hop",
    }

    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is False
    assert not source.exists()  # Strategie C hat die verwaiste Datei entfernt


def test_tag_write_failure_after_move_removes_inconsistent_library_file(
    processor, filename_fixer, happy_path_config, tmp_path, monkeypatch
):
    """
    FINDING-2 (Post-Baseline-Triage, PARTIAL-FAILURE-LIBRARY): schlaegt
    write_tags() (Schritt 17) fehl, NACHDEM move_to_library() (Schritt 16)
    bereits erfolgreich war, darf die unvollstaendig/falsch getaggte Datei
    NICHT dauerhaft in der Library liegen bleiben - vorher gab es dafuer
    keinen Cleanup (cleanup_single_download_artifact() im aeusseren
    except-Block ist fuer original_path zustaendig, das an dieser Stelle
    bereits nicht mehr existiert - siehe dortiger Kommentar in
    enhanced_metadata_processor.py). Gegenstueck zu
    test_error_after_move_to_library_cleans_up_orphaned_source_file (dort
    schlaegt move_to_library() selbst fehl, hier gelingt der Move und erst
    der nachfolgende Tag-Schreibvorgang scheitert).
    """
    source = tmp_path / "downloaded.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    def _boom(self, *args, **kwargs):
        raise RuntimeError("simulierter write_tags-Fehler")

    monkeypatch.setattr(processor.tag_writer.__class__, "write_tags", _boom)

    track_metadata = {
        "title": "Tagfail Artist - Tagfail Song (Official Video)",
        "artist": "Tagfail Artist",
        "uploader": "Tagfail Artist",
        "channel": "Tagfail Artist",
        "id": "TAGFAIL1",
        "filepath": str(source),
        "genre": "Hip Hop",
    }

    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is False
    # Die gesamte Library darf keine von move_to_library() erzeugte, aber
    # nie fertig getaggte Datei enthalten - unabhaengig vom genauen Pfad
    # (Artist-/Album-Unterordner werden von FilenameFixerTool bestimmt).
    leftover_files = list(happy_path_config.LIBRARY_DIR.rglob("*.mp3"))
    assert leftover_files == [], (
        f"Inkonsistente, unvollstaendig getaggte Datei(en) in der Library "
        f"zurueckgeblieben: {leftover_files}"
    )


def test_missing_filepath_error_does_not_crash_cleanup(processor, filename_fixer):
    """
    Gegenstueck zu test_missing_filepath_returns_graceful_failure: der
    Fehler tritt VOR Schritt 14 auf, original_path ist zu diesem Zeitpunkt
    noch None. Der Cleanup-Aufruf im except-Block muss das als No-op
    behandeln, ohne selbst eine Exception zu werfen.
    """
    track_metadata = {
        "title": "Some Artist - Some Song",
        "artist": "Some Artist",
        "uploader": "Some Artist",
        "channel": "Some Artist",
        "id": "NOFILE2",
    }

    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is False
    assert result.error


def _capture_tag_write(processor):
    """Ersetzt tag_writer.write_tags durch einen Spion, der die
    tatsaechlich uebergebenen kwargs festhaelt (das ist der einzige Ort,
    an dem feat_artists die EnhancedMetadataProcessor-Pipeline verlaesst -
    MetadataResult hat kein feat_artists-Feld)."""
    captured = {}
    original = processor.tag_writer.write_tags

    def _spy(**kwargs):
        captured.update(kwargs)
        return original(**kwargs)

    processor.tag_writer.write_tags = _spy
    return captured


def test_feat_from_title_reaches_feat_artists_in_tag_write(
    processor, filename_fixer, tmp_path
):
    """Finding A (Download-Pipeline-Testlauf 2026-09-09): ein
    Feature-Artist, der NUR ueber ein "feat."/"ft." IM TITEL erscheint
    ("Akon - Smack That ft. Eminem"), landet vom YouTube-Parser korrekt in
    youtube_parsed["featuring"] - diese Liste wurde im
    EnhancedMetadataProcessor bisher NIE gelesen. Foglich fiel Eminem
    komplett aus den Tags (©ART = ['Akon'], ARTISTS-Freeform leer).

    Kontrast: Co-Primary-Artists ueber "x"/"&"/"," ("Mia Julia x DJ Mico -
    Song") landen ueber den all_artists-Rest-Zweig korrekt in feat_artists
    - siehe test_cofeat_from_artist_part_still_reaches_feat_artists unten.
    """
    captured = _capture_tag_write(processor)
    source = tmp_path / "smackthat.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    track_metadata = {
        "title": "Akon - Smack That (Official Music Video) ft. Eminem",
        "artist": "Akon",
        "uploader": "AkonVEVO",
        "channel": "AkonVEVO",
        "id": "SMACKTH1",
        "filepath": str(source),
        "cover_art": b"fake-cover-bytes",
        "genre": "Hip Hop",
    }

    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is True
    assert result.artist == "Akon"
    feat = captured.get("feat_artists") or []
    assert any(
        f.lower() == "eminem" for f in feat
    ), f"Feature-Artist 'Eminem' aus dem Titel-feat. fehlt in feat_artists: {feat!r}"


def test_cofeat_from_artist_part_still_reaches_feat_artists(
    processor, filename_fixer, tmp_path
):
    """Regressions-Guard fuer den bereits funktionierenden Pfad: ein
    zweiter Artist im ARTIST-Teil des Titels (vor dem Trennzeichen) muss
    weiterhin ueber den all_artists-Rest-Zweig als feat_artist erscheinen -
    der Fix fuer Finding A darf diesen Zweig nicht verdraengen."""
    captured = _capture_tag_write(processor)
    source = tmp_path / "cofeat.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    track_metadata = {
        "title": "Mia Julia x DJ Mico - Party Song (Official Video)",
        "artist": "Mia Julia",
        "uploader": "Summerfield Records",
        "channel": "Summerfield Records",
        "id": "COFEAT01",
        "filepath": str(source),
        "cover_art": b"fake-cover-bytes",
        "genre": "Dance",
    }

    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is True
    feat = captured.get("feat_artists") or []
    assert any(
        "mico" in f.lower() for f in feat
    ), f"Co-Artist 'DJ Mico' fehlt in feat_artists: {feat!r}"


# ─────────────────────────────────────────────────────────────────────────
# PERF/M1: ArtistIdentityResolver.refresh() nur noch bei tatsächlicher
# Änderung an den Identitätsquellen (neuer Ordner ODER AutoLearn-Write),
# nicht mehr pauschal bei jedem known=False-Track.
# ─────────────────────────────────────────────────────────────────────────
def _track(source, vid, title, artist, uploader):
    return {
        "title": title,
        "artist": artist,
        "uploader": uploader,
        "channel": uploader,
        "id": vid,
        "filepath": str(source),
        "cover_art": b"fake-cover-bytes",
        "genre": "Hip Hop",
    }


def test_new_artist_folder_triggers_resolver_refresh(
    processor, filename_fixer, tmp_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        processor.artist_identity_resolver,
        "refresh",
        lambda: calls.append(1),
    )
    src = tmp_path / "a.mp3"
    src.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    result = asyncio.run(
        processor.process_single_track(
            track_metadata=_track(
                src,
                "NEWART01",
                "Brandneu Artist - Song",
                "Brandneu Artist",
                "Brandneu Artist",
            ),
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is True
    assert result.artist_known is False
    assert calls, "refresh() lief nicht, obwohl ein neuer Artist-Ordner entstand"


def test_no_refresh_when_folder_preexists_and_nothing_learned(
    processor, filename_fixer, tmp_path, happy_path_config, monkeypatch
):
    """PERF/M1 diskriminierend: known=False, aber der Artist-Ordner
    existierte schon (nach der Processor-Konstruktion angelegt, also NICHT
    im Resolver-Index) UND es wurde nichts Neues gelernt (Repost-Kanal,
    uploader ähnelt dem Artist nicht → kein Alias-Learning). Der frühere
    Code frischte den Resolver hier pauschal auf (Disk-Walk + 3 YAML-
    Reloads); jetzt: übersprungen."""
    (happy_path_config.LIBRARY_DIR / "Reposted Artist").mkdir(parents=True)

    calls = []
    monkeypatch.setattr(
        processor.artist_identity_resolver, "refresh", lambda: calls.append(1)
    )
    src = tmp_path / "r.mp3"
    src.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    md = _track(
        src,
        "REPOST01",
        "Reposted Artist - Some Song",
        "Music Reupload Hub",  # weder artist-Feld …
        "Music Reupload Hub",  # … noch uploader ähneln 'Reposted Artist'
    )
    result = asyncio.run(
        processor.process_single_track(
            track_metadata=md,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is True
    assert result.artist_known is False
    assert not calls, f"refresh() lief trotz unveränderter Identitätsquellen ({calls})"
