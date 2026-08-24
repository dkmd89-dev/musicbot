# services/downloader/metadata_result_translator.py
# -*- coding: utf-8 -*-
"""
Gemeinsame Integrationsschicht: ruft EnhancedMetadataProcessor
.process_single_track() auf und übersetzt das MetadataResult zurück in das
vom jeweiligen Aufrufer erwartete Ergebnisformat.

ARCH-004, P-3, Option B — extrahiert aus drei unabhängig gewachsenen
Implementierungen (siehe docs/MusicBot_ARCH-004_P3_Orchestrierungs_Analyse.md,
Abschnitt 6, für die vollständige Feld-für-Feld-Charakterisierung):
  - download_utils.py::_process_track_metadata()          (YT-Playlist)
  - download_utils.py::_process_single_download()          (YT-Single)
  - klassen/download_handler.py::_process_single_download_result() (Spotify)

WICHTIG: Die drei bestehenden Aufrufstellen unterschieden sich bereits
UNTEREINANDER (nicht nur YouTube vs. Spotify) in mehreren Feldern - u. a.
ob `year`/`track_number`/`playlist_album` aus dem MetadataResult übernommen
oder überschrieben/weggelassen werden. Diese Funktionen reproduzieren die
bisherigen Verhaltensweisen bewusst EXAKT (durch Regressionstests
abgesichert, siehe tests/test_download_utils_metadata_translation.py und
tests/test_download_handler_process_single_download_result.py).

Ausnahme - zwei am 2026-08-23 bewusst gefixte Inkonsistenzen (ARCH-004
Section 7, Entscheidung FIX NOW):
  - `is_duplicate` wird jetzt auch im YT-Single-Pfad aus dem echten
    MetadataResult übernommen (vorher immer False - täuschte im Telegram-
    Report ein "kein Duplikat" vor).
  - `library_path` wird im YT-Playlist-Pfad jetzt bedingt stringifiziert
    (vorher wurde `None` zum truthy-String `"None"` - konnte den
    Already-Processed-Vertrag fälschlich auslösen und in cache_manager.py
    einen ungültigen `Path("None")` erzeugen).
Alle anderen dokumentierten Inkonsistenzen bleiben bewusst zurückgestellt
(siehe Dokument, Abschnitt 7).

`EnhancedMetadataProcessor` selbst wird durch diese Extraktion NICHT
verändert.
"""

from typing import Any, Dict, Optional

from services.downloader.download.models import DownloadResult
from services.metadata.models import MetadataResult


async def call_process_single_track(
    enhanced_metadata_processor,
    track_metadata: Dict[str, Any],
    filename_fixer,
    playlist_metadata: Optional[Dict[str, Any]] = None,
    dominant_artist: Optional[str] = None,
) -> Optional[MetadataResult]:
    """
    Der Teil, der an allen drei bisherigen Aufrufstellen 1:1 identisch war:
    der `process_single_track()`-Aufruf selbst.
    """
    return await enhanced_metadata_processor.process_single_track(
        track_metadata=track_metadata,
        filename_fixer=filename_fixer,
        playlist_metadata=playlist_metadata,
        dominant_artist=dominant_artist,
    )


def build_playlist_track_result(
    metadata_result: MetadataResult,
    *,
    playlist_year: Optional[int],
    album_name: str,
    track_idx: int,
    enhanced_processor_ref: Any,
) -> Dict[str, Any]:
    """
    Reproduziert exakt `_process_track_metadata()`s (YT-Playlist) bisherige
    Übersetzung eines erfolgreichen MetadataResult in ein
    `DownloadResult.to_dict()`.

    Bewusst erhaltene Eigenheiten (NICHT Bugs, die hier gefixt würden):
      - `year` kommt aus `playlist_year`, nicht aus `metadata_result.year`
        (Playlist hat ein einheitliches Jahr).
      - `track_number` kommt aus dem Schleifen-Index `track_idx`, nicht aus
        `metadata_result.track_number`.

    Gefixt (2026-08-23, ARCH-004 Section 7, FIX NOW):
      - `library_path` wird jetzt bedingt stringifiziert wie im Single-Pfad
        - bei `None` bleibt es `None` statt zum truthy-String `"None"` zu
        werden.
    """
    dl_result = DownloadResult(
        success=True,
        title=metadata_result.title,
        artist=metadata_result.artist,
        album=metadata_result.album,
        album_artist=metadata_result.album_artist,
        year=playlist_year,
        genres=metadata_result.genres,
        genre_source=metadata_result.genre_source,
        library_path=(
            str(metadata_result.library_path) if metadata_result.library_path else None
        ),
        artist_source=metadata_result.artist_source,
        title_cleaned=metadata_result.title_cleaned,
        playlist_album=album_name,
        track_number=track_idx,
        lyrics_available=bool(metadata_result.lyrics),
        lyrics_source=metadata_result.lyrics_source,
        cover_embedded=metadata_result.cover_embedded,
        is_duplicate=metadata_result.is_duplicate,
        from_cache=metadata_result.from_cache,
        enhanced_processor_ref=enhanced_processor_ref,
    )
    return dl_result.to_dict()


def build_single_track_result(
    metadata_result: MetadataResult,
    *,
    enhanced_processor_ref: Any,
) -> Dict[str, Any]:
    """
    Reproduziert exakt `_process_single_download()`s (YT-Single) bisherige
    Übersetzung eines erfolgreichen MetadataResult in ein
    `DownloadResult.to_dict()`.

    Bewusst erhaltene Eigenheiten (NICHT Bugs, die hier gefixt würden):
      - `year` kommt hier (anders als im Playlist-Fall) direkt aus
        `metadata_result.year`.
      - `track_number`/`playlist_album` werden NIE explizit gesetzt -
        bleiben bei den `DownloadResult`-Dataclass-Defaults (`None`/`None`),
        auch wenn `metadata_result` echte Werte trägt.
      - `library_path` wird bedingt stringifiziert - bei `None` bleibt es
        `None`.

    Gefixt (2026-08-23, ARCH-004 Section 7, FIX NOW):
      - `is_duplicate` wird jetzt aus `metadata_result.is_duplicate`
        übernommen statt immer beim Dataclass-Default `False` zu bleiben -
        vorher zeigte der Telegram-Report bei jedem YT-Einzeldownload
        fälschlich "kein Duplikat" an, selbst wenn eins erkannt wurde.
    """
    dl_result = DownloadResult(
        success=True,
        title=metadata_result.title,
        artist=metadata_result.artist,
        album=metadata_result.album,
        album_artist=metadata_result.album_artist,
        year=metadata_result.year,
        genres=metadata_result.genres,
        genre_source=metadata_result.genre_source,
        library_path=(
            str(metadata_result.library_path) if metadata_result.library_path else None
        ),
        artist_source=metadata_result.artist_source,
        title_cleaned=metadata_result.title_cleaned,
        lyrics_available=bool(metadata_result.lyrics),
        lyrics_source=metadata_result.lyrics_source,
        cover_embedded=metadata_result.cover_embedded,
        is_duplicate=metadata_result.is_duplicate,
        from_cache=metadata_result.from_cache,
        enhanced_processor_ref=enhanced_processor_ref,
    )
    return dl_result.to_dict()


def merge_metadata_result_into_dict(
    original: Dict[str, Any], metadata_result: MetadataResult
) -> Dict[str, Any]:
    """
    Reproduziert exakt `_process_single_download_result()`s (Spotify)
    bisherige Übersetzung eines erfolgreichen MetadataResult in ein freies
    `{**original, ...}`-Dict.

    Bewusst erhaltene Eigenheiten (NICHT Bugs, die hier gefixt würden):
      - kein `enhanced_processor_ref`, kein `is_duplicate`-Schlüssel (waren
        vorher auch nicht Teil dieses Ergebnis-Dicts).
      - `lyrics` (Rohtext) UND `filepath` bleiben erhalten - anders als bei
        den beiden `DownloadResult`-basierten Varianten oben, die diese
        Felder gar nicht kennen.
      - `album`/`year`/`genres` fallen auf den jeweiligen Wert aus
        `original` zurück, falls `metadata_result` sie nicht liefert.
    """
    return {
        **original,
        "title": metadata_result.title,
        "artist": metadata_result.artist,
        "album": metadata_result.album or original.get("album"),
        "album_artist": metadata_result.album_artist,
        "year": metadata_result.year or original.get("year"),
        "track_number": metadata_result.track_number,
        "genres": metadata_result.genres or original.get("genres"),
        "lyrics": metadata_result.lyrics,
        "lyrics_available": bool(metadata_result.lyrics),
        "lyrics_source": metadata_result.lyrics_source,
        "cover_embedded": metadata_result.cover_embedded,
        "filepath": (
            str(metadata_result.filepath)
            if metadata_result.filepath
            else original.get("filepath")
        ),
        "library_path": (
            str(metadata_result.library_path)
            if metadata_result.library_path
            else original.get("library_path")
        ),
        "artist_source": metadata_result.artist_source,
        "genre_source": metadata_result.genre_source,
        "title_cleaned": metadata_result.title_cleaned,
        "from_cache": metadata_result.from_cache,
    }
