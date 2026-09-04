# services/library_health/file_analysis.py
# -*- coding: utf-8 -*-
"""
Per-Datei-Analyse (Prompt Abschnitt 8-16 / Phase 1B).

Reine Funktion: (FileRecord, TagData, StreamData, ArtworkData) -> FileHealth.
Kein Dateisystem-/Netzwerk-/Tag-Zugriff — die I/O passiert vorher in
tag_reader.py. Dadurch vollstaendig deterministisch und ohne Fixtures
unit-testbar (Prompt Abschnitt 31).

Die Genre-Validierung wird als Callable injiziert (`genre_validator`), damit
dieses Modul GenreMapper nicht importieren muss (Import-Graph-Sauberkeit /
Read-only-Safety). scanner.py verdrahtet den echten GenreMapper.

Grundhaltung (Prompt Abschnitt 22): Observation != Defect. Fehlende
optionale Felder sind INFO, nicht ERROR. Der Scanner diagnostiziert, er
entscheidet nicht, was "richtig" sein muss.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Callable, Optional

from .models import AnalysisState, FileHealth, FileRecord, Severity
from .issues import make_issue
from .tag_reader import ArtworkData, StreamData, TagData

# ─────────────────────────────────────────────────────────────────────────
# Schwellenwerte — zentral, dokumentiert (Prompt Abschnitt 23: keine
# versteckten/dynamischen Werte).
# ─────────────────────────────────────────────────────────────────────────

# Empfohlene Mindestkantenlaenge fuer eingebettetes Cover. Kalibriert am
# realen Bestand (Phase-1-Finalaudit 2026-09-04): 450–500 px Cover wirken
# in Playern noch akzeptabel, unter 400 px wird es sichtbar grob. 500 px
# hatte 450x446-/496x500-Cover faelschlich mitgemeldet.
ARTWORK_MIN_EDGE_PX = 400

# Toleranz fuer "praktisch quadratisch" (Phase-1-Finalaudit): der reale
# Bestand enthaelt viele Cover mit minimalem Encoder-/Resize-Rundungs-
# Delta (z. B. 1416x1407 = 0,6 %, 3600x3601 = 0,03 %). Erst ab 5 %
# Kantenabweichung ist das Seitenverhaeltnis sichtbar "falsch" (echte
# Faelle im Bestand: 602x542 = 10 %, 16:9-Videostills = 44 %).
ARTWORK_SQUARE_TOLERANCE = 0.05

# Untergrenze fuer verlustbehaftete Audio-Bitrate. config.Config.AUDIO_QUALITY
# ist "192" (kbps Zielwert der Download-Pipeline) — alles klar darunter
# deutet auf eine schlechtere Quelle / aeltere Datei hin.
AUDIO_MIN_BITRATE_BPS = 128_000

# Unter dieser Dauer ist ein Track auffaellig kurz. Kalibriert am realen
# Bestand (Phase-1-Finalaudit): 30 s meldete legitime Intro-Tracks wie
# Clueso "Take Off" (23,7 s). Skits/Intros mit eindeutigem Titel-Hinweis
# (_SKIT_TITLE_PATTERN) werden zusaetzlich ganz unterdrueckt.
AUDIO_VERY_SHORT_SECONDS = 20.0
_SKIT_TITLE_PATTERN = re.compile(
    r"\b(intro|outro|skit|interlude|prelude|reprise|snippet|prologue|epilogue)\b",
    re.IGNORECASE,
)

YEAR_MIN = 1900

_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')
_GAIN_DB_PATTERN = re.compile(r"^-?\d+(?:\.\d+)?\s*(?:dB)?$", re.IGNORECASE)
_LYRICS_JUNK_PATTERN = re.compile(
    r"^\s*(lyrics? not (found|available)|no lyrics|not found|n/?a|error)\s*$",
    re.IGNORECASE,
)
_GENRE_SEPARATORS = ("; ", " / ", ";", "/", ",")
# Trennt einen fuehrenden Struktur-Praefix vom Dateinamen ab:
#   "03 - Titel"        -> "Titel"
#   "2021 - Titel"      -> "Titel"
#   "Artist - Titel"    -> "Titel"
_FILENAME_PREFIX_PATTERN = re.compile(r"^(?:\d{2,4}|.+?)\s+-\s+", re.IGNORECASE)


def _blank(value: Optional[str]) -> bool:
    return value is None or not str(value).strip()


def _normalize_for_compare(text: str) -> str:
    text = _ILLEGAL_FILENAME_CHARS.sub("", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _split_genres(genre: str) -> list[str]:
    for sep in _GENRE_SEPARATORS:
        if sep in genre:
            return [p.strip() for p in genre.split(sep) if p.strip()]
    return [genre.strip()] if genre.strip() else []


# ─────────────────────────────────────────────────────────────────────────
# Haupteinstieg
# ─────────────────────────────────────────────────────────────────────────


def analyze_file(
    record: FileRecord,
    tags: TagData,
    stream: StreamData,
    artwork: ArtworkData,
    *,
    genre_validator: Optional[Callable[[str], bool]] = None,
    expected_extension: Optional[str] = None,
    now_year: Optional[int] = None,
) -> FileHealth:
    now_year = now_year or _dt.date.today().year
    fh = FileHealth(record=record)
    p = record.relative_path

    _carry_raw_values(fh, tags, stream, artwork)

    fh.states["metadata"] = _analyze_metadata(fh, record, tags, now_year, p)
    fh.states["genre"] = _analyze_genre(fh, tags, genre_validator, p)
    _analyze_multi_artist(fh, record, tags, p)
    fh.states["artwork"] = _analyze_artwork(fh, artwork, p)
    fh.states["lyrics"] = _analyze_lyrics(fh, tags, p)
    fh.states["audio"] = _analyze_audio(fh, stream, p)
    fh.states["loudness"] = _analyze_loudness(fh, tags, p)
    _analyze_structure_and_filename(fh, record, tags, expected_extension, p)

    fh.issues.sort(key=lambda i: i.sort_key())
    return fh


def _carry_raw_values(
    fh: FileHealth, tags: TagData, stream: StreamData, artwork: ArtworkData
) -> None:
    fh.artist = tags.artist
    fh.album_artist = tags.album_artist
    fh.title = tags.title
    fh.album = tags.album
    fh.year = tags.year
    fh.genre = tags.genre
    fh.track_number = tags.track_number
    fh.disc_number = tags.disc_number
    fh.mb_recording_id = tags.mb_recording_id
    fh.mb_release_id = tags.mb_release_id
    fh.isrc = tags.isrc
    fh.cover_sha256 = artwork.sha256
    fh.cover_width = artwork.width
    fh.cover_height = artwork.height
    fh.duration_seconds = stream.duration_seconds
    fh.bitrate = stream.bitrate


# ─────────────────────────────────────────────────────────────────────────
# Metadata
# ─────────────────────────────────────────────────────────────────────────


def _analyze_metadata(
    fh: FileHealth, record: FileRecord, tags: TagData, now_year: int, p: str
) -> AnalysisState:
    if tags.state == AnalysisState.NOT_ANALYZABLE:
        fh.issues.append(make_issue(
            "META_NOT_ANALYZABLE", path=p,
            message=f"Tag-Container nicht lesbar: {tags.error}",
            details={"error": tags.error},
        ))
        return AnalysisState.NOT_ANALYZABLE

    artist_ctx = tags.artist
    title_ctx = tags.title

    missing_core = 0
    present_core = 0
    _ctx = {"path": p, "artist": artist_ctx, "title": title_ctx}

    # Bewusst ausgeschrieben (kein code-per-Variable-Helfer): jeder
    # Issue-Code steht als Literal im Quelltext — tests/test_library_health_
    # issues.py verifiziert die Registrierung ueber genau dieses Muster.
    if _blank(tags.artist):
        missing_core += 1
        fh.issues.append(make_issue("META_ARTIST_MISSING", **_ctx))
    else:
        present_core += 1
    if _blank(tags.title):
        missing_core += 1
        fh.issues.append(make_issue("META_TITLE_MISSING", **_ctx))
    else:
        present_core += 1
    if _blank(tags.album):
        missing_core += 1
        fh.issues.append(make_issue("META_ALBUM_MISSING", **_ctx))
    else:
        present_core += 1
    if _blank(tags.album_artist):
        missing_core += 1
        fh.issues.append(make_issue("META_ALBUM_ARTIST_MISSING", **_ctx))
    else:
        present_core += 1
    if _blank(tags.year):
        missing_core += 1
        fh.issues.append(make_issue("META_YEAR_MISSING", **_ctx))
    else:
        present_core += 1

    if not _blank(tags.year):
        y = re.sub(r"[^\d]", "", tags.year)[:4]
        if not (y.isdigit() and YEAR_MIN <= int(y) <= now_year + 1):
            fh.issues.append(make_issue(
                "META_YEAR_INVALID", path=p, artist=artist_ctx, title=title_ctx,
                message=f"Jahr-Tag {tags.year!r} ist keine plausible Jahreszahl "
                        f"({YEAR_MIN}–{now_year + 1})",
                details={"value": tags.year},
            ))

    # Tracknummer: im Album-Kontext ein echter Mangel, bei einer Single nur
    # Beobachtung (Prompt Abschnitt 22).
    if tags.track_number is None:
        album_context = (
            record.path_classification == "ALBUM_LIKE"
            or record.album_directory is not None
        )
        fh.issues.append(make_issue(
            "META_TRACK_NUMBER_MISSING", path=p, artist=artist_ctx, title=title_ctx,
            severity=Severity.WARNING if album_context else Severity.INFO,
            details={"album_context": album_context},
        ))

    if _blank(tags.mb_recording_id):
        fh.issues.append(make_issue("META_MB_RECORDING_MISSING", path=p,
                                    artist=artist_ctx, title=title_ctx))
    if _blank(tags.mb_release_id):
        fh.issues.append(make_issue("META_MB_RELEASE_MISSING", path=p,
                                    artist=artist_ctx, title=title_ctx))
    if _blank(tags.isrc):
        fh.issues.append(make_issue("META_ISRC_MISSING", path=p,
                                    artist=artist_ctx, title=title_ctx))

    if present_core == 0:
        return AnalysisState.MISSING
    if missing_core == 0:
        return AnalysisState.PRESENT
    return AnalysisState.PARTIAL


# ─────────────────────────────────────────────────────────────────────────
# Genre
# ─────────────────────────────────────────────────────────────────────────


def _analyze_genre(
    fh: FileHealth, tags: TagData,
    genre_validator: Optional[Callable[[str], bool]], p: str,
) -> AnalysisState:
    if tags.state == AnalysisState.NOT_ANALYZABLE:
        return AnalysisState.NOT_ANALYZABLE
    if tags.genre is None:
        fh.issues.append(make_issue("META_GENRE_MISSING", path=p,
                                    artist=tags.artist, title=tags.title))
        return AnalysisState.MISSING

    parts = _split_genres(tags.genre)
    if not parts:
        fh.issues.append(make_issue("GENRE_EMPTY", path=p, artist=tags.artist,
                                    title=tags.title,
                                    details={"raw": tags.genre}))
        return AnalysisState.INVALID

    # Separator-Konvention: aktuell "; " (tag_writer.py). " / " ist Altbestand.
    if " / " in tags.genre and "; " not in tags.genre:
        fh.issues.append(make_issue(
            "GENRE_DELIMITER_INCONSISTENT", path=p, artist=tags.artist, title=tags.title,
            message="Mehrfach-Genre nutzt ' / ' statt der aktuellen Konvention '; '",
            details={"raw": tags.genre},
        ))

    state = AnalysisState.PRESENT
    if genre_validator is not None:
        invalid = []
        for part in parts:
            try:
                ok = genre_validator(part)
            except Exception:  # noqa: BLE001 — Validator darf Analyse nicht kippen
                ok = True
            if not ok:
                invalid.append(part)
        if invalid:
            fh.issues.append(make_issue(
                "GENRE_INVALID", path=p, artist=tags.artist, title=tags.title,
                message=f"Genre-Wert(e) vom GenreMapper nicht erkannt: {invalid}",
                details={"invalid": invalid, "raw": tags.genre},
            ))
            state = AnalysisState.PARTIAL if len(invalid) < len(parts) else AnalysisState.INVALID
    return state


# ─────────────────────────────────────────────────────────────────────────
# Multi-Artist
# ─────────────────────────────────────────────────────────────────────────

_FEAT_IN_ARTIST = re.compile(r"\b(feat\.?|ft\.?|featuring)\b", re.IGNORECASE)


def _analyze_multi_artist(fh: FileHealth, record: FileRecord, tags: TagData, p: str) -> None:
    if tags.state == AnalysisState.NOT_ANALYZABLE or _blank(tags.artist):
        return

    primary_values = tags.artists_primary_tag or ([tags.artist] if tags.artist else [])
    freeform = tags.artists_freeform

    # (a) unsaubere Konkatenation in EINEM ©ART-Wert
    for value in primary_values:
        if ";" in value:
            fh.issues.append(make_issue(
                "MULTI_ARTIST_SUSPICIOUS", path=p, artist=tags.artist, title=tags.title,
                message=f"Artist-Einzelwert enthaelt ';': {value!r}",
                details={"value": value},
            ))
            break

    # (b) feat. im ©ART statt separater ARTISTS-Werte
    if len(primary_values) == 1 and _FEAT_IN_ARTIST.search(primary_values[0]) and not freeform:
        fh.issues.append(make_issue(
            "MULTI_ARTIST_SUSPICIOUS", path=p, artist=tags.artist, title=tags.title,
            message=f"'feat.'/'ft.' steht im ©ART-Tag statt in separaten "
                    f"ARTISTS-Werten: {primary_values[0]!r}",
            details={"value": primary_values[0]},
        ))

    # (c) Derselbe Artist-Name mehrfach INNERHALB eines Feldes.
    # NICHT ueber ©ART + ARTISTS-Freeform hinweg pruefen: tag_writer.py
    # schreibt dieselbe Artist-Liste bewusst in BEIDE Felder (©ART und das
    # ----:com.apple.iTunes:ARTISTS-Atom) — die Ueberlappung ist der
    # Normalfall, kein Duplikat (Live-Fund gegen die echte Library:
    # 54 False Positives bei Solo-Artists wie "01099").
    combined = [a.strip() for a in list(primary_values) + list(freeform) if a.strip()]

    def _internal_dupes(values: list[str]) -> set[str]:
        seen: set[str] = set()
        dupes: set[str] = set()
        for a in values:
            k = a.strip().lower()
            if not k:
                continue
            if k in seen:
                dupes.add(a.strip())
            seen.add(k)
        return dupes

    dupes = _internal_dupes(primary_values) | _internal_dupes(freeform)
    if dupes:
        fh.issues.append(make_issue(
            "MULTI_ARTIST_DUPLICATE", path=p, artist=tags.artist, title=tags.title,
            message=f"Artist-Name(n) mehrfach im selben Multi-Artist-Feld: {sorted(dupes)}",
            details={"duplicates": sorted(dupes)},
        ))

    # (d) ©ART vs. ARTISTS-Freeform widersprechen sich
    if freeform and {a.lower() for a in freeform} != {a.lower() for a in primary_values}:
        fh.issues.append(make_issue(
            "MULTI_ARTIST_INCONSISTENT", path=p, artist=tags.artist, title=tags.title,
            message="©ART und ARTISTS-Freeform stimmen nicht ueberein",
            details={"primary": primary_values, "freeform": freeform},
        ))

    # (e) Album-Artist gehoert nicht zur Artist-Menge — nur im normalen
    # Musikpfad relevant. Bei Compilation/Playlist/Feature ist das legitim
    # (Prompt Abschnitt 22), daher dort NICHT gemeldet.
    if (
        record.library_section.value == "music"
        and not _blank(tags.album_artist)
        and primary_values
        and tags.album_artist.lower() not in {a.lower() for a in combined}
    ):
        fh.issues.append(make_issue(
            "MULTI_ARTIST_INCONSISTENT", path=p, artist=tags.artist, title=tags.title,
            message=f"Album-Artist {tags.album_artist!r} kommt in der Artist-Liste "
                    f"nicht vor",
            details={"album_artist": tags.album_artist, "artists": combined},
        ))


# ─────────────────────────────────────────────────────────────────────────
# Artwork
# ─────────────────────────────────────────────────────────────────────────


def _analyze_artwork(fh: FileHealth, artwork: ArtworkData, p: str) -> AnalysisState:
    if artwork.state == AnalysisState.NOT_ANALYZABLE:
        return AnalysisState.NOT_ANALYZABLE
    if artwork.state == AnalysisState.MISSING or not artwork.present:
        fh.issues.append(make_issue("ARTWORK_MISSING", path=p))
        return AnalysisState.MISSING
    if artwork.state == AnalysisState.INVALID:
        fh.issues.append(make_issue(
            "ARTWORK_INVALID", path=p,
            message=f"Eingebettetes Cover nicht als Bild dekodierbar: {artwork.error}",
            details={"error": artwork.error, "size_bytes": artwork.size_bytes},
        ))
        return AnalysisState.INVALID

    if artwork.width and artwork.height:
        w, h = artwork.width, artwork.height
        if min(w, h) < ARTWORK_MIN_EDGE_PX:
            fh.issues.append(make_issue(
                "ARTWORK_LOW_RESOLUTION", path=p,
                message=f"Cover {w}x{h} unter {ARTWORK_MIN_EDGE_PX}px Mindestkante",
                details={"width": w, "height": h},
            ))
        aspect_off = abs(w - h) / max(w, h)
        if aspect_off > ARTWORK_SQUARE_TOLERANCE:
            fh.issues.append(make_issue(
                "ARTWORK_NON_SQUARE", path=p,
                message=f"Cover-Seitenverhaeltnis weicht {aspect_off:.1%} von 1:1 ab "
                        f"({w}x{h})",
                details={"width": w, "height": h, "aspect_off": round(aspect_off, 4)},
            ))
    return AnalysisState.PRESENT


# ─────────────────────────────────────────────────────────────────────────
# Lyrics
# ─────────────────────────────────────────────────────────────────────────


def _analyze_lyrics(fh: FileHealth, tags: TagData, p: str) -> AnalysisState:
    if tags.state == AnalysisState.NOT_ANALYZABLE:
        return AnalysisState.NOT_ANALYZABLE
    if tags.lyrics is None:
        fh.issues.append(make_issue("LYRICS_MISSING", path=p,
                                    artist=tags.artist, title=tags.title))
        return AnalysisState.MISSING
    if not tags.lyrics.strip():
        fh.issues.append(make_issue("LYRICS_EMPTY", path=p,
                                    artist=tags.artist, title=tags.title))
        return AnalysisState.INVALID
    if _LYRICS_JUNK_PATTERN.match(tags.lyrics.strip()):
        fh.issues.append(make_issue(
            "LYRICS_INVALID", path=p, artist=tags.artist, title=tags.title,
            message=f"Lyrics-Inhalt sieht nach Platzhalter/Fehlermeldung aus: "
                    f"{tags.lyrics.strip()[:60]!r}",
        ))
        return AnalysisState.INVALID
    return AnalysisState.PRESENT


# ─────────────────────────────────────────────────────────────────────────
# Audio
# ─────────────────────────────────────────────────────────────────────────


def _analyze_audio(fh: FileHealth, stream: StreamData, p: str) -> AnalysisState:
    if stream.corrupt or stream.state == AnalysisState.INVALID:
        fh.issues.append(make_issue(
            "AUDIO_CORRUPT", path=p,
            message=f"ffprobe meldet Container-/Decode-Fehler: {stream.error}",
            details={"error": stream.error},
        ))
        return AnalysisState.INVALID
    if stream.state == AnalysisState.NOT_ANALYZABLE:
        fh.issues.append(make_issue(
            "AUDIO_NOT_ANALYZABLE", path=p,
            message=f"ffprobe-Analyse fehlgeschlagen: {stream.error}",
            details={"error": stream.error},
        ))
        return AnalysisState.NOT_ANALYZABLE
    if not stream.has_audio_stream:
        fh.issues.append(make_issue("AUDIO_NO_STREAM", path=p))
        return AnalysisState.INVALID

    if stream.bitrate is not None and stream.bitrate < AUDIO_MIN_BITRATE_BPS:
        fh.issues.append(make_issue(
            "AUDIO_LOW_BITRATE", path=p,
            message=f"Bitrate {stream.bitrate} bps unter {AUDIO_MIN_BITRATE_BPS} bps",
            details={"bitrate": stream.bitrate, "codec": stream.codec},
        ))
    if stream.duration_seconds is not None and stream.duration_seconds < AUDIO_VERY_SHORT_SECONDS:
        stem_and_title = f"{fh.record.filename_stem} {fh.title or ''}"
        if not _SKIT_TITLE_PATTERN.search(stem_and_title):
            fh.issues.append(make_issue(
                "AUDIO_VERY_SHORT", path=p,
                message=f"Audio-Dauer {stream.duration_seconds:.1f}s unter "
                        f"{AUDIO_VERY_SHORT_SECONDS:.0f}s — Skit/Intro oder "
                        f"abgeschnitten?",
                details={"duration_seconds": stream.duration_seconds},
            ))
    return AnalysisState.PRESENT


# ─────────────────────────────────────────────────────────────────────────
# Loudness / ReplayGain — nur Tag-Diagnose, NIE Messung/Berechnung
# (Prompt Abschnitt 16).
# ─────────────────────────────────────────────────────────────────────────


def _analyze_loudness(fh: FileHealth, tags: TagData, p: str) -> AnalysisState:
    if tags.state == AnalysisState.NOT_ANALYZABLE:
        return AnalysisState.NOT_ANALYZABLE
    rg = tags.replaygain
    if not rg:
        fh.issues.append(make_issue("LOUDNESS_TAG_MISSING", path=p,
                                    artist=tags.artist, title=tags.title))
        return AnalysisState.MISSING

    track_gain = rg.get("replaygain_track_gain")
    if track_gain is not None and not _GAIN_DB_PATTERN.match(str(track_gain).strip()):
        fh.issues.append(make_issue(
            "LOUDNESS_TAG_INVALID", path=p, artist=tags.artist, title=tags.title,
            message=f"replaygain_track_gain {track_gain!r} nicht als dB-Wert parsebar",
            details={"value": track_gain},
        ))
        return AnalysisState.INVALID

    if "replaygain_track_gain" in rg and "replaygain_track_peak" not in rg:
        fh.issues.append(make_issue(
            "LOUDNESS_TAG_PARTIAL", path=p, artist=tags.artist, title=tags.title,
            message="replaygain_track_gain ohne zugehoeriges replaygain_track_peak",
            details={"present": sorted(rg)},
        ))
        return AnalysisState.PARTIAL
    return AnalysisState.PRESENT


# ─────────────────────────────────────────────────────────────────────────
# Struktur / Dateiname
# ─────────────────────────────────────────────────────────────────────────


def _analyze_structure_and_filename(
    fh: FileHealth, record: FileRecord, tags: TagData,
    expected_extension: Optional[str], p: str,
) -> None:
    section = record.library_section.value

    if section == "unknown":
        fh.issues.append(make_issue(
            "STRUCTURE_INVALID_PATH", path=p,
            message="Datei liegt ausserhalb jeder bekannten Library-Struktur "
                    "(erwartet: <Artist>/(Singles|Jahr - Album)/ bzw. "
                    "Compilations/ bzw. Playlist/)",
        ))
    elif (
        section == "music"
        and not record.is_singles
        and record.album_directory is None
        and record.artist_directory is not None
    ):
        fh.issues.append(make_issue(
            "STRUCTURE_FILE_OUTSIDE_HIERARCHY", path=p,
            message=f"Audio-Datei direkt im Artist-Ordner {record.artist_directory!r} "
                    f"(erwartet: Singles/ oder <Jahr - Album>/ Unterordner)",
        ))

    if expected_extension and record.extension != expected_extension.lower():
        fh.issues.append(make_issue(
            "FILENAME_EXTENSION_UNEXPECTED", path=p,
            message=f"Dateiendung {record.extension} weicht vom konfigurierten "
                    f"Format {expected_extension} ab",
            details={"extension": record.extension, "expected": expected_extension},
        ))

    stem = record.filename_stem
    if "  " in stem or stem != stem.strip() or _ILLEGAL_FILENAME_CHARS.search(stem):
        fh.issues.append(make_issue(
            "FILENAME_SUSPICIOUS", path=p,
            message=f"Dateiname-Stamm auffaellig: {stem!r}",
            details={"stem": stem},
        ))

    # Titel-Abgleich nur, wenn ein Titel-Tag existiert.
    if not _blank(tags.title):
        remainder = _FILENAME_PREFIX_PATTERN.sub("", stem, count=1)
        if _normalize_for_compare(remainder) != _normalize_for_compare(tags.title):
            fh.issues.append(make_issue(
                "FILENAME_TITLE_MISMATCH", path=p, artist=tags.artist, title=tags.title,
                message=f"Dateiname-Stamm {stem!r} passt nicht zum Titel-Tag "
                        f"{tags.title!r}",
                details={"stem": stem, "title": tags.title, "compared": remainder},
            ))
