# services/metadata/models.py
# -*- coding: utf-8 -*-

import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════════
# Feature-Artist-Split Hilfsfunktion (Modul-Ebene)
# ═══════════════════════════════════════════════════════════════════════════════


def split_main_and_featuring(artist_string: str) -> Tuple[str, List[str]]:
    """
    Splittet einen Artist-String in Hauptartist und Feature-Artists.

    Beispiele:
        "1986zig feat. GReeeN"       → ("1986zig", ["GReeeN"])
        "1986zig ft. GReeeN & Sido"  → ("1986zig", ["GReeeN", "Sido"])
        "1986zig, Greeen"            → ("1986zig", ["Greeen"])
        "1986zig"                    → ("1986zig", [])
        ""                          → ("", [])

    Returns:
        Tuple[str, List[str]]: (main_artist, [feature_artists])
    """
    if not artist_string or not artist_string.strip():
        return "", []

    artist_string = artist_string.strip()

    # Schritt 1: feat./ft./featuring Keyword suchen
    # ARTISTNORM-002: \b-Wortgrenzen verhindern Fehltreffer in Woertern, die
    # "ft"/"feat" nur als Teilstring enthalten (z.B. "trifft" -> vorher
    # faelschlich als "tri" + Feature-Artist "ft Jemand" gesplittet, siehe
    # docs/archive/MusicBot_ENGINEERING_BASELINE.md, ARTISTNORM-001/002).
    feat_pattern = re.compile(
        r"\s*\b(?:feat\b\.?|ft\b\.?|featuring\b|with\b)\s+(.+)$",
        re.IGNORECASE,
    )
    m = feat_pattern.search(artist_string)
    if m:
        main = artist_string[: m.start()].strip()
        feat_raw = m.group(1).strip()
        feat_artists = [
            a.strip()
            for a in re.split(r"\s*[,&]\s*|\s+(?:und|and)\s+", feat_raw)
            if a.strip()
        ]
        return main, feat_artists

    # Schritt 2: Kein feat-Keyword → Komma oder & als Trennzeichen
    parts = re.split(r"\s*[,&]\s*", artist_string)
    if len(parts) > 1:
        main = parts[0].strip()
        feat_artists = [p.strip() for p in parts[1:] if p.strip()]
        return main, feat_artists

    return artist_string, []


# ═══════════════════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class EnhancedProcessingStats:
    """Detaillierte Statistiken für Enhanced Processing"""

    successful_normalizations: int = 0
    successful_genre_mappings: int = 0
    dominant_artist_used: int = 0
    youtube_parser_used: int = 0
    lyrics_found: int = 0
    cover_art_found: int = 0
    duplicate_tracks: int = 0
    total_processed: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    title_cleaned_by_artist_map: int = 0
    artist_map_parsing_fallback: int = 0


@dataclass
class MetadataResult:
    """Container für verarbeitete Metadaten mit Lyrics"""

    success: bool
    title: str
    artist: str
    album: Optional[str] = None
    album_artist: Optional[str] = None
    year: Optional[int] = None
    track_number: Optional[int] = None
    genres: Optional[List[Dict]] = field(default_factory=list)
    lyrics: Optional[str] = None
    lyrics_source: Optional[str] = None
    cover_art: Optional[bytes] = None
    cover_embedded: bool = False
    # War der FFmpeg-loudnorm-Schritt (Schritt 15b) fuer diesen Track
    # erfolgreich? Vorher nur geloggt, nie strukturiert zurueckgegeben -
    # noetig fuer die "Loudness normalisiert"-Zeile in der Telegram-
    # Abschlussmeldung (download_result_reporter.py).
    loudness_normalized: bool = False

    # Technische Daten
    filepath: Optional[Path] = None
    library_path: Optional[Path] = None
    # DUP-01 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md):
    # eigene Quell-URL des Tracks (aus track_metadata["webpage_url"]) - wird
    # fuer die Duplicate-Cache-Registrierung von Playlist-Tracks benoetigt,
    # da diese (anders als Single-Downloads) keine eigene Registrierung ueber
    # klassen/download_handler.py::handle_single_track_success() erhalten.
    url: Optional[str] = None
    # P1-Fund (Post-Baseline-v4 Health & Risk Audit, Finding 2):
    # True, wenn move_to_library() den Zieldateinamen wegen einer bereits
    # existierenden Datei umbenennen musste ("Titel (1).ext") - ermöglicht
    # dem darauf wartenden Cleanup in klassen/download_handler.py, tatsächlich
    # zu greifen (vorher nie gesetzt, siehe utils/filenamefixer.py).
    renamed_due_to_conflict: bool = False
    original_metadata: Optional[Dict] = field(default_factory=dict)

    # Verarbeitungsdetails
    artist_source: Optional[str] = None
    # ARCH Artist-Identity (Phase B): True, wenn die Artist-Identitaet aus
    # einer autoritativen Quelle bestaetigt wurde (artist_override /
    # known_artist / auto_learned_alias / library_identity / musicbrainz_mbid).
    # False, wenn nur der Parser-Kandidat uebernommen wurde (dann darf
    # AutoLearn eine neue Beziehung lernen). None = nicht aufgeloest
    # (Podcast/Fallback bzw. Alt-Aufrufer, die das Feld nicht setzen).
    artist_known: Optional[bool] = None
    genre_source: Optional[str] = None
    title_cleaned: bool = False
    is_duplicate: bool = False
    error: Optional[str] = None
    from_cache: bool = False

    # MusicBrainz IDs – werden von GenreProcessor befüllt und durchgereicht
    # sodass CoverProcessor & AlbumProcessor nicht nochmal MB aufrufen müssen
    mb_recording_id: Optional[str] = None
    mb_artist_id: Optional[str] = None
    mb_release_id: Optional[str] = None
    mb_release_group_id: Optional[str] = None
    mb_isrc: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Artist-Identity-Auflösung (ARCH — Artist Identity Resolution & Mapping
# Separation, Phase B)
# ═══════════════════════════════════════════════════════════════════════════════

# Erlaubte Herkunftsquellen einer Artist-Identity-Entscheidung, in fachlicher
# Prioritätsreihenfolge (höchste zuerst). Ein niedriger priorisiertes Signal
# darf niemals einen höher priorisierten autoritativen Eintrag überschreiben
# (siehe ArtistIdentityResolver).
ARTIST_IDENTITY_SOURCES: Tuple[str, ...] = (
    "artist_override",     # mapping/artist_overrides.json (manuell, autoritativ)
    "known_artist",        # mapping/known_artists.yaml (bestätigte Identität)
    "auto_learned_alias",  # mapping/auto_learned_artist_aliases.json (Alias→Canonical)
    "library_identity",    # vorhandener Library-Artist-Ordner
    "musicbrainz_mbid",    # MusicBrainz-Artist-MBID-Abgleich (optional, Phase F)
    "parser",              # kein autoritatives Signal – Parser-Kandidat übernommen
)


@dataclass(frozen=True)
class ArtistIdentity:
    """Ergebnis der Artist-Identity-Auflösung.

    canonical:
        Endgültiger kanonischer Artistname.
    source:
        Tatsächliche Herkunft der Identitätsentscheidung – einer der Werte aus
        ARTIST_IDENTITY_SOURCES. Keine anderen (insbesondere keine künstlichen)
        Quellen.
    known:
        True  → die Identität wurde aus einer autoritativen Quelle bestätigt
                (artist_override / known_artist / auto_learned_alias /
                library_identity / musicbrainz_mbid). AutoLearn für den
                Artist wird dann NICHT ausgelöst.
        False → der Resolver übernimmt lediglich den (normalisierten)
                Parser-Kandidaten (source == "parser"). AutoLearn darf
                versuchen, eine neue Beziehung zu lernen.

    Bewusst frozen: eine einmal getroffene Identitätsentscheidung wird
    weitergereicht, nicht nachträglich mutiert.
    """

    canonical: str
    source: str
    known: bool

    def __post_init__(self) -> None:
        if self.source not in ARTIST_IDENTITY_SOURCES:
            raise ValueError(
                f"Ungültige ArtistIdentity.source: {self.source!r} "
                f"(erlaubt: {', '.join(ARTIST_IDENTITY_SOURCES)})"
            )
        if self.source == "parser" and self.known:
            raise ValueError(
                "ArtistIdentity(source='parser', known=True) ist unzulässig – "
                "der Parser-Kandidat ist per Definition keine bestätigte Identität."
            )
