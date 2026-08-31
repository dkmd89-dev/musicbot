#!/usr/bin/env python3
# scripts/reprocess_artist_metadata.py
# -*- coding: utf-8 -*-
"""
Offizielles MusicBot-Reprocessing-Tool fuer bestehende Artist-Verzeichnisse
in der isolierten Testumgebung.

Ziel: bestehende, bereits vorhandene Audiodateien eines Artists erneut durch
die aktuelle Metadata-Pipeline laufen lassen (Tags/Cover/Lyrics
aktualisieren, fehlende MusicBrainz-IDs ergaenzen, eindeutig fehlerhafte
Dateinamen innerhalb ihres bestehenden Verzeichnisses korrigieren) - KEIN
Download, KEINE Aenderung der Library-/Verzeichnisstruktur, KEINE
Audio-Neucodierung.

Technische Referenz und vollstaendig durchgefuehrter erster Validierungslauf:
docs/archive/METADATA_REPROCESSING_TEST_CHAPO102.md
Allgemeine Dokumentation (Sicherheitsmodell, CLI, Workflow):
docs/METADATA_REPROCESSING.md

Nutzt ausschliesslich config_test.Config (isolierte Testumgebung) und die
echten Produktions-Subprozessoren von EnhancedMetadataProcessor
(ArtistNormalizer, TitleCleaner, GenreProcessor, LyricsProcessor,
CoverProcessor, TagWriter) - ruft aber bewusst NICHT
process_single_track()/move_to_library() auf:

  - move_to_library() wuerde das Zielverzeichnis aus dem frisch bestimmten
    Artist-Namen neu berechnen (Risiko fuer Verzeichnis-Struktur-Bruch,
    siehe utils/filenamefixer.py::build_final_path()).
  - Die volle Pipeline ruft unconditional AudioEnhancer.normalize_loudness()
    auf (verlustbehaftete FFmpeg-Neucodierung). Fuer dieses Tool
    ausdruecklich ausgeschlossen - AudioEnhancer wird an keiner Stelle
    importiert oder aufgerufen. Fehlendes ReplayGain/Loudness wird
    stattdessen als UNRESOLVED dokumentiert (siehe _check_unresolved()).

Album/Jahr werden NICHT ueber AlbumProcessor.determine_album_info() neu
bestimmt (diese Methode ist fuer Download-Zeit-Metadaten aus
Playlist/yt-dlp gebaut und wuerde bei fehlenden Kandidaten auf das
aktuelle Kalenderjahr zurueckfallen) - stattdessen werden die bereits
vorhandenen Album-/Jahr-Tags als Vertrauensbasis uebernommen ("bestehende
bessere Werte nicht unnoetig verschlechtern", CLAUDE.md Abschnitt 9).
"""

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_test import Config  # isolierte Testkonfiguration - NIEMALS config.Config
from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
from services.metadata.models import split_main_and_featuring
from services.clients.musicbrainz_client import MusicBrainzClient
from services.clients.lastfm_client import LastFMClient
from utils.helpers import sanitize_filename
from utils.regex import ILLEGAL_CHARS_PATTERN
from mutagen.mp4 import MP4

MB_ID_ATOM_MAP = {
    "recording_id": "----:com.apple.iTunes:MusicBrainz Recording Id",
    "artist_id": "----:com.apple.iTunes:MusicBrainz Artist Id",
    "release_id": "----:com.apple.iTunes:MusicBrainz Release Id",
    "release_group_id": "----:com.apple.iTunes:MusicBrainz Release Group Id",
    "isrc": "----:com.apple.iTunes:ISRC",
}

# Erlaubte Wurzel fuer JEDEN Schreibzugriff dieses Tools. Nichts ausserhalb
# davon darf jemals angefasst werden - siehe validate_input_path().
ALLOWED_ROOT = Path("/tmp/musicbot_test")
DEFAULT_METADATEN_ROOT = ALLOWED_ROOT / "metadaten"
DEFAULT_PRODUCTION_ROOT = Path("/mnt/4tb/library")


class PathSafetyError(Exception):
    """Wird bei jeder Verletzung der Path-Safety-Guards ausgeloest."""


# ─────────────────────────────────────────────────────────────────────────
# Path-Safety
# ─────────────────────────────────────────────────────────────────────────


def validate_input_path(input_path: Path, metadaten_root: Path) -> Path:
    """
    Harte Path-Safety-Guards (Abschnitt 4 des Auftrags). Loest bei jeder
    Verletzung PathSafetyError aus - der Aufrufer darf danach KEINE Datei
    anfassen. Symlinks werden durch .resolve(strict=True) vollstaendig
    aufgeloest, bevor irgendeine Grenzpruefung stattfindet.
    """
    try:
        resolved = input_path.resolve(strict=True)
    except FileNotFoundError:
        raise PathSafetyError(f"Input existiert nicht: {input_path}")
    except OSError as e:
        raise PathSafetyError(f"Input nicht aufloesbar: {input_path} ({e})")

    if not resolved.is_dir():
        raise PathSafetyError(f"Input ist kein Verzeichnis: {resolved}")

    # Produktions-Guard zuerst und unabhaengig von den uebrigen
    # Grenzpruefungen: ein Treffer hier ist immer ein harter Stopp, egal
    # welche metadaten_root/ALLOWED_ROOT-Konstellation sonst vorliegt.
    # Selbst wenn ein Symlink INNERHALB von metadaten/ sekundaer auf die
    # Produktions-Library zeigen wuerde, faengt bereits das .resolve() oben
    # das ab (resolved landet dann ausserhalb der erlaubten Testumgebung) -
    # dieser Check ist zusaetzliche Defense-in-Depth mit einer eindeutigen,
    # eigenen Fehlermeldung.
    for prod_candidate in (DEFAULT_PRODUCTION_ROOT,):
        try:
            prod_resolved = prod_candidate.resolve()
        except OSError:
            continue
        if resolved == prod_resolved or prod_resolved in resolved.parents:
            raise PathSafetyError(
                f"Input zeigt auf eine Produktionsbibliothek: {resolved}"
            )

    metadaten_root_resolved = metadaten_root.resolve()
    if resolved == metadaten_root_resolved:
        raise PathSafetyError(
            f"Input darf nicht die Wurzel {metadaten_root_resolved} selbst sein "
            f"- ein konkretes Artist-Verzeichnis angeben"
        )
    if metadaten_root_resolved not in resolved.parents:
        raise PathSafetyError(
            f"Input liegt nicht unterhalb von {metadaten_root_resolved}: {resolved}"
        )

    allowed_root_resolved = ALLOWED_ROOT.resolve()
    if allowed_root_resolved not in resolved.parents and resolved != allowed_root_resolved:
        raise PathSafetyError(
            f"Input liegt ausserhalb der erlaubten Testumgebung {allowed_root_resolved}: {resolved}"
        )

    return resolved


def validate_file_within_root(file_path: Path, root: Path) -> bool:
    """Symlink-Schutz auf Dateiebene: eine innerhalb des Artist-Verzeichnisses
    gefundene Datei koennte selbst ein Symlink sein, der nach aussen zeigt.
    Gibt False zurueck (statt zu werfen), damit main() einzelne verdaechtige
    Dateien ueberspringen und protokollieren kann, ohne den gesamten Lauf
    abzubrechen."""
    try:
        resolved_file = file_path.resolve(strict=True)
        resolved_root = root.resolve()
    except OSError:
        return False
    return resolved_root == resolved_file or resolved_root in resolved_file.parents


# ─────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────


class ReprocessLogger:
    """Schreibt strukturierte, live nachvollziehbare Log-Eintraege (tail -f-faehig,
    jede Zeile wird sofort geflusht)."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = open(path, "a", encoding="utf-8")

    def line(self, text: str = ""):
        self._fh.write(text + "\n")
        self._fh.flush()

    def section(self, title: str, emoji: str = "─"):
        self.line("")
        self.line(f"{emoji} {title} " + "─" * max(0, 60 - len(title)))

    def kv(self, key: str, value, indent: int = 1):
        self.line(f"{'   ' * indent}{key}: {value}")

    def close(self):
        self._fh.close()


# ─────────────────────────────────────────────────────────────────────────
# Snapshot / Audio-Essenz
# ─────────────────────────────────────────────────────────────────────────


def _freeform_str(values):
    out = []
    for v in values or []:
        try:
            out.append(bytes(v).decode("utf-8", errors="replace"))
        except Exception:
            out.append(str(v))
    return out


def _sha256(data):
    if not data:
        return None
    return hashlib.sha256(data).hexdigest()


def _ffprobe_stream_info(path: Path) -> dict:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            capture_output=True, text=True, timeout=30, check=True,
        )
        data = json.loads(result.stdout)
        audio_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
            {},
        )
        fmt = data.get("format", {})
        return {
            "codec": audio_stream.get("codec_name"),
            "sample_rate": audio_stream.get("sample_rate"),
            "channels": audio_stream.get("channels"),
            "duration": fmt.get("duration"),
            "bitrate": fmt.get("bit_rate"),
        }
    except Exception as e:
        return {"error": str(e)}


def audio_essence_md5(path: Path) -> str:
    """Dekodiert NUR den Audio-Stream (kein Container/Tags) und hasht das
    rohe PCM - der verbindliche, container-unabhaengige Beweis dafuer, dass
    Metadaten-Schreibvorgaenge die Audio-Essenz nicht veraendert haben.
    Gibt bei Fehlern einen eindeutig erkennbaren Fehlerstring zurueck statt
    zu werfen (Snapshot-Erzeugung darf nicht am Audio-Hash scheitern)."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-f", "md5", "-"],
            capture_output=True, text=True, timeout=60, check=True,
        )
        return result.stdout.strip() or result.stderr.strip()
    except Exception as e:
        return f"ERROR: {e}"


def snapshot(path: Path, artist_root: Path, with_audio_essence: bool = True) -> dict:
    """Liest den aktuellen, tatsaechlich gespeicherten Zustand direkt von der
    Platte (frisches mutagen.mp4.MP4(path) - kein In-Memory-Objekt)."""
    audio = MP4(path)
    tags = audio.tags or {}

    def _t(key):
        v = tags.get(key)
        return list(v) if v else []

    cover = tags.get("covr")
    cover_bytes = bytes(cover[0]) if cover else None

    mb_ids = {}
    for key, atom in MB_ID_ATOM_MAP.items():
        v = _freeform_str(tags.get(atom))
        mb_ids[key] = v[0] if v else None

    trkn = tags.get("trkn")
    track_number = trkn[0][0] if trkn else None

    return {
        "relative_path": str(path.relative_to(artist_root.parent)),
        "filename": path.name,
        "parent_dirname": path.parent.name,
        "track_number": track_number,
        "artist": _t("©ART"),
        "artists_freeform": _freeform_str(tags.get("----:com.apple.iTunes:ARTISTS")),
        "album_artist": _t("aART"),
        "title": _t("©nam"),
        "album": _t("©alb"),
        "year": _t("©day"),
        "genre_tag": _t("©gen"),
        "genre_freeform": _freeform_str(tags.get("----:com.apple.iTunes:GENRE")),
        "mb_ids": mb_ids,
        "lyrics_present": bool(tags.get("©lyr")),
        "cover_present": bool(cover),
        "cover_sha256": _sha256(cover_bytes),
        "replaygain_track_gain": _freeform_str(
            tags.get("----:com.apple.iTunes:replaygain_track_gain")
        ),
        "loudness_normalized": _freeform_str(
            tags.get("----:com.apple.iTunes:loudness_normalized")
        ),
        "stream_info": _ffprobe_stream_info(path),
        "audio_essence_md5": audio_essence_md5(path) if with_audio_essence else None,
    }


def diff_snapshots(before: dict, after: dict) -> dict:
    changes = {}
    for key in before:
        if key in ("stream_info", "audio_essence_md5"):
            continue
        if before.get(key) != after.get(key):
            changes[key] = {"before": before.get(key), "after": after.get(key)}
    return changes


# ─────────────────────────────────────────────────────────────────────────
# Multi-Artist (ausschliesslich bestehende Produktionslogik)
# ─────────────────────────────────────────────────────────────────────────


def flatten_existing_artists(raw_artist_values: list) -> list:
    """Splittet ggf. noch zusammengeklebte Artist-Strings (TAG-01-Altlast,
    z.B. 'CHAPO102; Gustav' als EIN Listenelement) in einzelne Namen -
    ausschliesslich ueber die bestehende split_main_and_featuring()-Logik
    (services/metadata/models.py, identisch zur Produktionslogik in
    EnhancedMetadataProcessor). ';' wird vorher zu ',' normalisiert
    (MusicBots eigenes historisches Join-Zeichen, siehe
    TagWriter.artists_semicolon) - keine neue heuristische Split-Logik."""
    flat = []
    for raw in raw_artist_values or []:
        normalized_sep = raw.replace(";", ",")
        main, feats = split_main_and_featuring(normalized_sep)
        if main:
            flat.append(main)
        flat.extend(f for f in feats if f)
    seen = set()
    deduped = []
    for a in flat:
        key = a.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(a.strip())
    return deduped


# ─────────────────────────────────────────────────────────────────────────
# UNRESOLVED-Erkennung (Abschnitt 22 des Auftrags: bewusst nicht geaenderte
# Faelle sind NICHT automatisch UNCHANGED)
# ─────────────────────────────────────────────────────────────────────────


def check_unresolved(before: dict, after: dict, clean_title: str) -> list:
    reasons = []

    if not after["replaygain_track_gain"] and not after["loudness_normalized"]:
        reasons.append(
            "ReplayGain/Loudness fehlt. Aktuelle Nachruestung wuerde "
            "verlustbehaftetes Audio-Re-Encoding erfordern "
            "(AudioEnhancer.normalize_loudness() ist die einzige im Repository "
            "vorhandene Implementierung). Ausserhalb des sicheren "
            "Reprocessing-Scopes ('keine unnoetige Audio-Neucodierung'). "
            "Keine Audioaenderung durchgefuehrt."
        )

    # BUGFIX (waehrend des Final-Audits entdeckt): sanitize_filename()
    # veraendert einen String aus ZWEI verschiedenen Gruenden, die vorher
    # faelschlich gleich behandelt wurden:
    #   (a) echte dateinamens-illegale Zeichen (ILLEGAL_CHARS_PATTERN,
    #       z.B. "*") - eine echte, nicht sicher automatisch aufloesbare
    #       Ambiguitaet.
    #   (b) harmlose, bereits von der Produktions-Pipeline vorgesehene
    #       Reformatierung, insbesondere FEAT_NOTATION_PATTERN
    #       ("(feat. X)" -> "feat. X") - real bei "Verlaufen (feat. SIDO)"
    #       ausgeloest, faelschlich als UNRESOLVED gemeldet, obwohl die
    #       Umformatierung sicher und beabsichtigt ist.
    # Nur (a) ist ein echter UNRESOLVED-Grund - dafuer wird ausschliesslich
    # das schmalere, tatsaechlich fuer "illegal" zustaendige Regex direkt
    # geprueft, nicht die volle sanitize_filename()-Transformation.
    if ILLEGAL_CHARS_PATTERN.search(clean_title):
        sanitized_title = sanitize_filename(clean_title)
        reasons.append(
            f"Title-Tag ({clean_title!r}) enthaelt Zeichen, die in Dateinamen "
            f"nicht darstellbar sind (sanitisiert: {sanitized_title!r}). Nicht "
            f"eindeutig feststellbar, ob dies beabsichtigte Stilisierung ist "
            f"oder eine spaetere, vom Dateinamen abweichende Tag-Aenderung. "
            f"Keine automatische Korrektur - manuelle Pruefung empfohlen."
        )

    return reasons


# ─────────────────────────────────────────────────────────────────────────
# Pro-Datei-Verarbeitung
# ─────────────────────────────────────────────────────────────────────────


async def process_file(
    path: Path,
    artist_root: Path,
    processor: EnhancedMetadataProcessor,
    mb_client: MusicBrainzClient,
    lfm_client: LastFMClient,
    log: ReprocessLogger,
    dry_run: bool = False,
) -> dict:
    rel = path.relative_to(artist_root.parent)
    log.section(f"🎵 FILE START: {rel}", emoji="🎵")
    log.kv("📂 Input", path)
    if dry_run:
        log.kv("🔒 Modus", "DRY-RUN - keine Datei wird veraendert")

    before = snapshot(path, artist_root)
    log.line("📋 BEFORE SNAPSHOT")
    for k, v in before.items():
        log.kv(k, v)

    result = {
        "file": str(rel),
        "status": "unchanged",
        "unresolved": [],
        "error": None,
        "changes": {},
        "audio_stream_changed": False,
        "audio_essence_changed": False,
        "dry_run": dry_run,
        "auto_learn": {"featured_artists": [], "genre": None},
    }

    try:
        log.line("🔄 METADATA PIPELINE")

        # ── ArtistNormalizer + Multi-Artist-Split ────────────────────────
        existing_artist_values = before["artist"] or before["album_artist"]
        # TAG-01-Altlast (real bei Nina Chuba "Verlaufen feat. SIDO"
        # entdeckt): das Freeform-Feld "ARTISTS" kann VOLLSTAENDIGERE
        # Informationen enthalten als das Standard-©ART-Tag - hier war
        # ©ART nur ['Nina Chuba'], das Freeform-Feld aber
        # ['Nina Chuba; SIDO'] (ein zusammengeklebter Wert, SIDO fehlte im
        # Standard-Tag komplett). Beide Quellen werden deshalb gemeinsam an
        # flatten_existing_artists() uebergeben - dieselbe bestehende
        # Split-/Dedupe-Logik, nur auf eine vollstaendigere Eingabemenge
        # angewendet, keine neue Heuristik.
        combined_artist_sources = list(existing_artist_values) + [
            v for v in before["artists_freeform"] if v not in existing_artist_values
        ]
        flat_artists = flatten_existing_artists(combined_artist_sources)
        if not flat_artists:
            raise ValueError("Kein Artist-Tag vorhanden - kann nicht verarbeitet werden")

        normalized_artists = [
            processor.artist_normalizer.normalize(a) or a for a in flat_artists
        ]
        final_artist = normalized_artists[0]
        feat_artists = normalized_artists[1:]

        log.line("👤 ArtistNormalizer")
        log.kv("→ input (©ART/aART)", existing_artist_values, indent=2)
        log.kv("→ input (+ARTISTS-Freeform)", combined_artist_sources, indent=2)
        log.kv("→ flattened", flat_artists, indent=2)
        log.kv("→ output", normalized_artists, indent=2)
        if len(flat_artists) > 1 or any(";" in (v or "") for v in combined_artist_sources):
            log.line("🎤 Multi-Artist")
            log.kv("→ input", combined_artist_sources, indent=2)
            log.kv("→ main", final_artist, indent=2)
            log.kv("→ feat", feat_artists, indent=2)

        # ── TitleCleaner ──────────────────────────────────────────────────
        existing_title = before["title"][0] if before["title"] else path.stem
        clean_title = processor.title_cleaner.light_title_cleanup(
            existing_title, final_artist
        )
        search_title = processor.title_cleaner.build_search_title(
            parsed_title=None, original_title=clean_title, final_artist=final_artist
        )
        log.line("🧹 TitleCleaner")
        log.kv("→ input", existing_title, indent=2)
        log.kv("→ output", clean_title, indent=2)

        # ── GenreProcessor + MusicBrainz-IDs (echte Produktions-Pipeline) ──
        genre_hint = before["genre_tag"][0] if before["genre_tag"] else None
        track_metadata = {"genre": genre_hint}
        genres_result = await processor.genre_processor.determine_genre_with_fallbacks(
            track_metadata=track_metadata,
            artist_name=final_artist,
            channel_name="",
            canonical_channel_name=None,
            is_special_channel=False,
            feat_artists=feat_artists,
            clean_title=search_title,
            mb_client=mb_client,
            lfm_client=lfm_client,
        )
        fresh_mb_ids = (getattr(genres_result, "mb_ids", None) or {}) if genres_result else {}
        final_mb_ids = {}
        for key in MB_ID_ATOM_MAP:
            final_mb_ids[key] = before["mb_ids"].get(key) or fresh_mb_ids.get(key)

        log.line("🎼 GenreProcessor")
        log.kv(
            "→ source",
            getattr(genres_result, "source", None) if genres_result else None,
            indent=2,
        )
        log.kv(
            "→ result",
            f"primary={getattr(genres_result, 'primary', None)!r} "
            f"secondary={getattr(genres_result, 'secondary', None)!r}"
            if genres_result else None,
            indent=2,
        )
        log.line("🧬 MusicBrainz")
        log.kv("→ IDs vorhanden (Tag)", before["mb_ids"], indent=2)
        log.kv("→ IDs neu ermittelt", fresh_mb_ids, indent=2)
        log.kv("→ IDs final", final_mb_ids, indent=2)

        # ── Auto-Learn: Feature-Artist-Beobachtung + Genre-Aggregation ─────
        # Primary-/Feature-Trennung kommt bereits fertig aus dem
        # ArtistNormalizer-Schritt oben (final_artist/feat_artists) - hier
        # keine eigene Parsing-Logik. Im Dry-Run werden ausschliesslich die
        # reinen preview_*()-Methoden verwendet (kein Schreibzugriff auf
        # mapping/auto_learned_*.yaml); im Live-Lauf zusaetzlich die
        # echten learn_genre()/observe_featured_artists()-Schreibpfade der
        # bereits produktiv genutzten AutoLearnManager-Instanz
        # (processor.auto_learn_manager - dieselbe Instanz, die auch der
        # echte Bot-Download-Pfad verwendet).
        log.line("🧠 AUTO-LEARN")
        feat_decisions = []
        genre_decision = None
        if feat_artists:
            track_context = f"{final_artist} - {clean_title}"
            if dry_run:
                feat_decisions = processor.auto_learn_manager.preview_featured_artists(
                    primary_artist=final_artist,
                    feat_artists=feat_artists,
                    track_context=track_context,
                )
            else:
                feat_decisions = await processor.auto_learn_manager.observe_featured_artists(
                    primary_artist=final_artist,
                    feat_artists=feat_artists,
                    track_context=track_context,
                )
            for d in feat_decisions:
                log.kv("→ Feature-Artist", d["canonical"] or d["raw"], indent=2)
                log.kv("  Role", d["role"], indent=2)
                log.kv("  Current mapping", "FOUND" if d["existing"] else "NOT FOUND", indent=2)
                log.kv("  Observation", track_context, indent=2)
                log.kv("  Decision", d["decision"], indent=2)
                if d["decision"] in ("WOULD_LEARN", "WOULD_UPDATE", "LEARNED", "UPDATED"):
                    log.kv("  Observations", d["predicted_observations"], indent=2)
                    log.kv("  Confidence", d["predicted_confidence"], indent=2)
                elif d.get("reason"):
                    log.kv("  Reason", d["reason"], indent=2)
                log.kv(
                    "  Action",
                    "NO FILE WRITE" if dry_run else (
                        "FILE WRITE" if d["decision"] in ("LEARNED", "UPDATED") else "NO FILE WRITE"
                    ),
                    indent=2,
                )
        else:
            log.kv("→ Feature-Artists", "keine", indent=2)

        log.line("🎼 GENRE AUTO-LEARN")
        genre_source = getattr(genres_result, "source", None) if genres_result else None
        if genres_result and genres_result.primary and genre_source not in ("none", "unknown", None):
            genre_decision = processor.auto_learn_manager.preview_genre_learning(
                final_artist, genres_result
            )
            genre_action_will_write = (
                not dry_run and genre_decision["decision"] in ("WOULD_LEARN", "WOULD_UPDATE")
            )
            if genre_action_will_write:
                await processor.auto_learn_manager.learn_genre(
                    canonical_name=final_artist, genre_result=genres_result
                )
            log.kv("→ Artist", final_artist, indent=2)
            log.kv(
                "  Observed",
                f"{genre_decision['observed_primary']} / "
                f"{', '.join(genre_decision['observed_secondary'])}"
                if genre_decision["observed_secondary"]
                else genre_decision["observed_primary"],
                indent=2,
            )
            if genre_decision["existing"]:
                log.kv(
                    "  Existing learned",
                    f"{genre_decision['existing'].get('primary')} / "
                    f"{', '.join(genre_decision['existing'].get('secondary') or [])}",
                    indent=2,
                )
            log.kv("  Decision", genre_decision["decision"], indent=2)
            if genre_decision["decision"] in ("WOULD_LEARN", "WOULD_UPDATE"):
                log.kv("  Predicted primary", genre_decision["predicted_primary"], indent=2)
                log.kv("  Predicted observations", genre_decision["predicted_observations"], indent=2)
                log.kv("  Predicted confidence", genre_decision["predicted_confidence"], indent=2)
            log.kv("  Action", "NO FILE WRITE" if not genre_action_will_write else "FILE WRITE", indent=2)
        else:
            log.kv("→ Genre-Auto-Learn", "uebersprungen (kein verwertbares Genre)", indent=2)

        # ── LyricsProcessor (immer neu, bestehende Fallback-Logik) ─────────
        lyrics, lyrics_source = await processor.lyrics_processor.fetch_lyrics_with_fallback(
            artist=final_artist, title=clean_title, fallback_artists=feat_artists,
        )
        log.line("📝 LyricsProcessor")
        log.kv("→ lookup", "genius (+ feat.-Fallback)", indent=2)
        log.kv(
            "→ result",
            "found" if lyrics else "unavailable",
            indent=2,
        )

        # ── CoverProcessor (IMMER neu pruefen, auch bei vorhandenem Cover) ─
        cover_bytes, cover_source = await asyncio.to_thread(
            processor.cover_processor.get_cover_art,
            video_id=None,
            release_id=final_mb_ids.get("release_id"),
            release_group_mbid=final_mb_ids.get("release_group_id"),
            artist_mbid=final_mb_ids.get("artist_id"),
            artist_name=final_artist,
            track_title=clean_title,
            recording_id=final_mb_ids.get("recording_id"),
            isrc=final_mb_ids.get("isrc"),
        )
        cover_action = "UNAVAILABLE"
        if cover_bytes:
            new_hash = _sha256(cover_bytes)
            if not before["cover_present"]:
                cover_action = "ADD"
            elif new_hash != before["cover_sha256"]:
                cover_action = "REPLACE"
            else:
                cover_action = "KEEP"
        log.line("🖼️ CoverProcessor")
        log.kv("→ existing cover", "YES" if before["cover_present"] else "NO", indent=2)
        log.kv("→ search executed", "YES", indent=2)
        log.kv("→ candidate source", cover_source, indent=2)
        log.kv("→ action", cover_action, indent=2)

        # ── Album/Jahr: bestehende Werte als Vertrauensbasis uebernehmen ───
        existing_album = before["album"][0] if before["album"] else None
        existing_year_raw = before["year"][0] if before["year"] else None
        try:
            existing_year = int(existing_year_raw) if existing_year_raw else None
        except (TypeError, ValueError):
            existing_year = None
        album_info = {
            "album": existing_album or clean_title,
            "album_artist": final_artist,
            "year": existing_year,
        }

        # ── Dateiname planen (nur innerhalb desselben Parent-Verzeichnisses)
        # Zwei Namenskonventionen, exakt wie utils/filenamefixer.py::
        # build_final_path() sie fuer Singles bzw. Album-Tracks verwendet:
        #   Singles-Ordner:  "{Jahr} - {Titel}.{ext}"
        #   Album-Ordner:    "{Tracknummer:02d} - {Titel}.{ext}"
        # Die Unterscheidung erfolgt NICHT geraten, sondern anhand des
        # tatsaechlichen Parent-Ordnernamens ("Singles") bzw. des
        # tatsaechlich vorhandenen trkn-Tags. Fehlt bei einem Album-Track
        # die Tracknummer, wird KEIN Rename versucht (kein "00 -"-Raten -
        # "nicht raten" gilt auch fuer Dateinamenskonventionen).
        # Stem und Endung werden GETRENNT sanitisiert: sanitize_filename()
        # ersetzt illegale Zeichen durch ein Leerzeichen und trimmt nur die
        # AEUSSEREN Raender des uebergebenen Strings. Wuerde die Endung
        # mitsanitisiert (z.B. "...GESEHEN?.m4a"), bliebe ein durch "?"
        # erzeugtes Leerzeichen VOR der Endung stehen (waehrend Phase C real
        # aufgetreten und korrigiert, siehe docs/archive/METADATA_REPROCESSING_TEST_CHAPO102.md).
        is_singles = before["parent_dirname"] == "Singles"
        existing_track_number = before["track_number"]
        rename_planned = False
        rename_target = None
        rename_blocked_reason = None
        expected_filename = path.name

        if is_singles:
            year_str = existing_year_raw or "####"
            expected_stem = sanitize_filename(f"{year_str} - {clean_title}")
            expected_filename = f"{expected_stem}{path.suffix}"
            rename_planned = expected_filename != path.name
        elif existing_track_number:
            expected_stem = sanitize_filename(
                f"{int(existing_track_number):02d} - {clean_title}"
            )
            expected_filename = f"{expected_stem}{path.suffix}"
            rename_planned = expected_filename != path.name
        else:
            log.kv(
                "→ filename",
                "kein Rename-Versuch (Album-Track ohne trkn-Tag, "
                "Konvention nicht sicher bestimmbar)",
                indent=2,
            )

        if rename_planned:
            rename_target = path.with_name(expected_filename)
            if rename_target.parent != path.parent:
                rename_blocked_reason = (
                    f"Parent-Verzeichnis wuerde sich aendern "
                    f"({path.parent} -> {rename_target.parent})"
                )
            elif rename_target.exists() and rename_target != path:
                rename_blocked_reason = f"Zieldatei existiert bereits ({rename_target.name})"
            elif ILLEGAL_CHARS_PATTERN.search(clean_title):
                # BUGFIX (waehrend Nina-Chuba-Validierungslauf entdeckt,
                # siehe docs/archive/METADATA_REPROCESSING_TEST_NINA_CHUBA.md):
                # check_unresolved() erkennt diesen Fall bereits und meldet
                # ihn als UNRESOLVED, verhinderte den Rename bisher aber
                # NICHT - real aufgetreten bei "F*cked Up" -> sanitisiert zu
                # "F cked Up" (Leerzeichen an Stelle des "*", schlechter als
                # der urspruengliche Dateiname "Fcked Up", der das Zeichen
                # ersatzlos wegliess). Ein Titel mit dateinamens-illegalen
                # Zeichen ist per Definition nicht eindeutig sicher
                # umzubenennen ("nicht raten") - der Rename wird deshalb
                # hier zusaetzlich zur UNRESOLVED-Meldung aktiv blockiert.
                # Prueft NUR echte illegale Zeichen (ILLEGAL_CHARS_PATTERN),
                # NICHT die volle sanitize_filename()-Transformation - siehe
                # check_unresolved() fuer die Begruendung (Final-Audit-Fund:
                # harmlose FEAT_NOTATION_PATTERN-Umformatierung darf den
                # Rename nicht blockieren).
                rename_blocked_reason = (
                    f"Titel enthaelt dateinamens-illegale Zeichen "
                    f"({clean_title!r} -> sanitisiert {sanitize_filename(clean_title)!r}) "
                    f"- kein automatischer Rename"
                )

        if not dry_run:
            # ── TagWriter (echter Produktions-TagWriter, atomar) ───────────
            log.line("🏷️ TagWriter")
            log.kv("→ writing tags", "...", indent=2)
            await asyncio.to_thread(
                processor.tag_writer.write_tags,
                target_path=path,
                artist=final_artist,
                title=clean_title,
                album_info=album_info,
                track_number=None,
                genres_result=genres_result,
                lyrics=lyrics,
                cover_art=cover_bytes,
                feat_artists=feat_artists,
                mb_ids=final_mb_ids,
            )
            log.kv("→ write_tags", "OK", indent=2)

            final_path = path
            if rename_planned and not rename_blocked_reason:
                path.rename(rename_target)
                final_path = rename_target
                log.line(f"✏️ FILENAME CHANGE: {path.name} -> {rename_target.name}")
                result["status"] = "changed"
            elif rename_planned and rename_blocked_reason:
                result["unresolved"].append(f"Rename abgelehnt: {rename_blocked_reason}")
                log.line(f"⚪ FILENAME NO CHANGE (⚠️ UNRESOLVED: {rename_blocked_reason})")
            else:
                log.line(f"⚪ FILENAME NO CHANGE: {path.name}")

            # ── AFTER SNAPSHOT: frisch von der tatsaechlich gespeicherten
            # Datei lesen (Datei erneut von Disk geoeffnet, kein In-Memory-
            # Objekt wiederverwendet) ───────────────────────────────────────
            after = snapshot(final_path, artist_root)
        else:
            log.line("🔒 DRY-RUN: TagWriter NICHT aufgerufen, kein Rename durchgefuehrt")
            if rename_planned:
                note = rename_blocked_reason or "wuerde durchgefuehrt (dry-run)"
                log.kv("→ geplanter Rename", f"{path.name} -> {expected_filename} ({note})", indent=2)
            final_path = path
            # In DRY-RUN wird NICHTS geschrieben - "after" ist deshalb eine
            # VORHERSAGE, konstruiert aus denselben Werten, die TagWriter
            # geschrieben HAETTE, unter Nachbildung von dessen tatsaechlichem
            # bedingtem Schreibverhalten (z.B. Cover/Lyrics/Genre-Freeform
            # werden nur bei einem echten Treffer ueberschrieben, sonst
            # bleibt der bestehende Wert unveraendert - siehe
            # services/metadata/tag_writer.py). Audio-Stream/ReplayGain
            # werden von diesem Tool nie beruehrt, bleiben also immer gleich
            # BEFORE. Klar als Vorhersage gekennzeichnet, kein echter Read.
            all_artists_planned = [final_artist] + feat_artists
            primary = getattr(genres_result, "primary", None) if genres_result else None
            secondary = getattr(genres_result, "secondary", None) if genres_result else None
            if primary and secondary:
                combined = [primary] + list(secondary)[:3]
                genre_tag_planned = [" / ".join(combined)]
                genre_freeform_planned = [", ".join(combined)]
            elif primary:
                genre_tag_planned = [primary]
                genre_freeform_planned = before["genre_freeform"]
            else:
                genre_tag_planned = before["genre_tag"]
                genre_freeform_planned = before["genre_freeform"]

            after = dict(before)
            after["filename"] = expected_filename
            after["artist"] = all_artists_planned
            after["artists_freeform"] = all_artists_planned if feat_artists else before["artists_freeform"]
            after["album_artist"] = [album_info["album_artist"]]
            after["title"] = [clean_title]
            after["album"] = [album_info["album"]] if album_info.get("album") else before["album"]
            after["year"] = [str(album_info["year"])] if album_info.get("year") else before["year"]
            after["genre_tag"] = genre_tag_planned
            after["genre_freeform"] = genre_freeform_planned
            after["mb_ids"] = final_mb_ids
            after["lyrics_present"] = bool(lyrics) or before["lyrics_present"]
            if cover_bytes:
                after["cover_present"] = True
                after["cover_sha256"] = _sha256(cover_bytes)
            # audio_essence_md5/stream_info/replaygain/loudness bleiben wie
            # in before (bereits per dict(before) uebernommen) - dieses Tool
            # beruehrt den Audio-Stream in keinem Modus.
            log.line("🔮 DRY-RUN VORHERSAGE (kein echter Read, keine Datei geschrieben)")

        log.line("🔍 AFTER SNAPSHOT" if not dry_run else "🔍 AFTER SNAPSHOT (Vorhersage, dry-run)")
        for k, v in after.items():
            log.kv(k, v)

        changes = diff_snapshots(before, after)
        result["changes"] = changes
        if changes and result["status"] != "changed":
            result["status"] = "changed"
        elif not changes and result["status"] != "changed":
            result["status"] = "unchanged"

        # ── Audiointegritaet: Stream-Parameter + Audio-Essenz ───────────────
        # "bitrate" ist bewusst AUSGENOMMEN: ffprobe berechnet dieses Feld im
        # "format"-Block als dateigroesse*8/duration - reine Tag-/Cover-
        # Groessenaenderungen verschieben diesen Wert unabhaengig von der
        # Audio-Essenz. codec/sample_rate/channels/duration UND der
        # dekodierte Audio-Essenz-Hash sind die verbindlichen Marker.
        AUDIO_INTEGRITY_KEYS = ("codec", "sample_rate", "channels", "duration")
        stream_before = before["stream_info"]
        stream_after = after["stream_info"]
        stream_essence_before = {k: stream_before.get(k) for k in AUDIO_INTEGRITY_KEYS}
        stream_essence_after = {k: stream_after.get(k) for k in AUDIO_INTEGRITY_KEYS}
        if stream_essence_before != stream_essence_after:
            result["audio_stream_changed"] = True
            result["unresolved"].append(
                f"AUDIO STREAM ABWEICHUNG (codec/sample_rate/channels/duration): "
                f"before={stream_essence_before} after={stream_essence_after}"
            )
        if before["audio_essence_md5"] != after["audio_essence_md5"]:
            result["audio_essence_changed"] = True
            result["unresolved"].append(
                f"AUDIO ESSENCE ABWEICHUNG: before={before['audio_essence_md5']} "
                f"after={after['audio_essence_md5']}"
            )

        # ── UNRESOLVED-Erkennung (bewusst nicht geaenderte Faelle) ──────────
        for reason in check_unresolved(before, after, clean_title):
            if reason not in result["unresolved"]:
                result["unresolved"].append(reason)

        log.line("📊 CHANGES")
        if changes:
            for k, v in changes.items():
                log.kv(f"✏️ {k}", f"{v['before']!r} -> {v['after']!r}")
        else:
            log.line("   ⚪ (keine)")

        if result["unresolved"]:
            log.line("⚠️ UNRESOLVED")
            for u in result["unresolved"]:
                log.line(f"   - {u}")

        result["auto_learn"] = {
            "featured_artists": [
                {
                    "canonical": d["canonical"],
                    "decision": d["decision"],
                    "observations": d.get("predicted_observations"),
                    "confidence": d.get("predicted_confidence"),
                }
                for d in feat_decisions
            ],
            "genre": (
                {
                    "artist": final_artist,
                    "decision": genre_decision["decision"],
                    "predicted_primary": genre_decision.get("predicted_primary"),
                    "observations": genre_decision.get("predicted_observations"),
                    "confidence": genre_decision.get("predicted_confidence"),
                }
                if genre_decision
                else None
            ),
        }

        status_emoji = {"changed": "✏️", "unchanged": "⚪", "error": "❌"}.get(
            result["status"], "❓"
        )
        log.line(f"{status_emoji} FINAL RESULT: {result['status'].upper()}")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        log.line("❌ ERROR")
        log.kv("exception", repr(e))
        log.line("❌ FINAL RESULT: ERROR")

    return result


# ─────────────────────────────────────────────────────────────────────────
# Post-Run Safety Check
# ─────────────────────────────────────────────────────────────────────────


def snapshot_directory_tree(root: Path) -> dict:
    """Rein lesendes Inventar (relative Pfade, Groessen) fuer den
    Struktur-Invariante-Vergleich vor/nach dem Lauf."""
    files = {}
    dirs = set()
    for p in root.rglob("*"):
        if p.is_dir():
            dirs.add(str(p.relative_to(root)))
        elif p.is_file():
            files[str(p.relative_to(root))] = p.stat().st_size
    return {"dirs": dirs, "files": files}


def snapshot_production_files(production_root: Path, artist_name: str, relative_paths: list) -> dict:
    """Rein lesende Momentaufnahme (mtime, Groesse, SHA256) der zu den
    Testdateien korrespondierenden Produktionsdateien - fuer den
    automatischen Production-Protection-Check. Liefert pro Datei None,
    wenn keine korrespondierende Produktionsdatei existiert (kein Fehler -
    der Testbestand kann bereits umbenannte/entfernte Namen enthalten)."""
    out = {}
    artist_root = production_root / artist_name
    for rel in relative_paths:
        # rel ist z.B. "CHAPO102/Singles/2024 - OMG.m4a" -> Pfad relativ
        # zum Artist-Verzeichnis selbst ableiten
        try:
            rel_within_artist = Path(rel).relative_to(artist_name)
        except ValueError:
            out[rel] = None
            continue
        prod_file = artist_root / rel_within_artist
        if not prod_file.exists() or not prod_file.is_file():
            out[rel] = None
            continue
        st = prod_file.stat()
        with open(prod_file, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        out[rel] = {"mtime": st.st_mtime, "size": st.st_size, "sha256": digest}
    return out


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True,
        help="Vollstaendiger Pfad zum bestehenden Artist-Testverzeichnis, "
             "z.B. /tmp/musicbot_test/metadaten/ARTIST",
    )
    parser.add_argument(
        "--metadaten-root", default=str(DEFAULT_METADATEN_ROOT),
        help=f"Erlaubte Wurzel fuer --input (Standard: {DEFAULT_METADATEN_ROOT})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Nur analysieren - keine Datei aendern, kein Tag schreiben, "
             "kein Cover schreiben, kein Rename, keine Audioverarbeitung",
    )
    parser.add_argument(
        "--production-root", default=str(DEFAULT_PRODUCTION_ROOT),
        help=f"Nur-lesend verwendete Produktions-Library fuer den "
             f"automatischen Post-Run-Safety-Check (Standard: {DEFAULT_PRODUCTION_ROOT})",
    )
    parser.add_argument(
        "--no-production-check", action="store_true",
        help="Production-Protection-Vergleich gegen --production-root auslassen",
    )
    args = parser.parse_args()

    metadaten_root = Path(args.metadaten_root)

    try:
        resolved_input = validate_input_path(Path(args.input), metadaten_root)
    except PathSafetyError as e:
        print(f"❌ PATH SAFETY: {e}")
        sys.exit(1)

    assert str(Config.BASE_DIR) == "/tmp/musicbot_test", (
        f"❌ config_test.Config.BASE_DIR ist nicht isoliert: {Config.BASE_DIR}"
    )

    artist_name = resolved_input.name
    candidate_files = sorted(resolved_input.rglob("*.m4a"))
    files = []
    skipped_unsafe = []
    for f in candidate_files:
        if validate_file_within_root(f, resolved_input):
            files.append(f)
        else:
            skipped_unsafe.append(f)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(
        f"/tmp/musicbot_test/metadata_reprocessing_{artist_name}_{timestamp}.log"
    )
    log = ReprocessLogger(log_path)

    log.line(f"🚀 MusicBot Metadata Reprocessing Tool - {artist_name}")
    log.kv("📦 Repository", "dkmd89-dev/musicbot", indent=0)
    log.kv("🧪 Test Environment", str(Config.BASE_DIR), indent=0)
    log.kv("🎵 Artist", artist_name, indent=0)
    log.kv("📁 Input", str(resolved_input), indent=0)
    log.kv("🔒 Modus", "DRY-RUN" if args.dry_run else "LIVE", indent=0)
    log.kv("📄 Dateien gefunden", len(files), indent=0)
    for f in files:
        log.kv("  -", f.relative_to(resolved_input), indent=0)
    if skipped_unsafe:
        log.line("⚠️ UEBERSPRUNGEN (ausserhalb der erlaubten Wurzel, Symlink-Verdacht):")
        for f in skipped_unsafe:
            log.kv("  -", f, indent=0)

    # ── Struktur-/Production-Snapshot VOR dem Lauf ──────────────────────────
    dir_snapshot_before = snapshot_directory_tree(resolved_input)
    production_root = Path(args.production_root)
    production_check_enabled = not args.no_production_check and production_root.exists()
    relative_paths = [str(f.relative_to(resolved_input.parent)) for f in files]
    prod_snapshot_before = (
        snapshot_production_files(production_root, artist_name, relative_paths)
        if production_check_enabled else {}
    )

    processor = EnhancedMetadataProcessor(config=Config)
    mb_client = MusicBrainzClient()
    lfm_client = LastFMClient()

    results = []
    try:
        for f in files:
            r = await process_file(
                f, resolved_input, processor, mb_client, lfm_client, log,
                dry_run=args.dry_run,
            )
            results.append(r)
    finally:
        try:
            await processor.aclose()
        except Exception:
            pass
        processor.cleanup()

    # ── Struktur-/Production-Snapshot NACH dem Lauf ─────────────────────────
    dir_snapshot_after = snapshot_directory_tree(resolved_input)
    prod_snapshot_after = (
        snapshot_production_files(production_root, artist_name, relative_paths)
        if production_check_enabled else {}
    )

    dirs_changed = dir_snapshot_before["dirs"] != dir_snapshot_after["dirs"]
    files_before = set(dir_snapshot_before["files"])
    files_after = set(dir_snapshot_after["files"])
    files_created = files_after - files_before
    files_deleted = files_before - files_after

    # Ein erlaubter Rename (Title-Cleaning-Korrektur, siehe Abschnitt 9 der
    # Doku) erscheint in einem rohen Verzeichnis-Snapshot-Diff zwangslaeufig
    # als ein Create+Delete-Paar - das ist erwuenscht, solange beide
    # Ereignisse im SELBEN Verzeichnis stattfinden (die Rename-Logik selbst
    # garantiert bereits parent-Gleichheit, siehe rename_blocked_reason
    # oben). Nur ein Ungleichgewicht PRO VERZEICHNIS zwischen Creates und
    # Deletes waere ein echtes Struktur-Problem (Datei tatsaechlich
    # verschoben/verschwunden statt nur umbenannt).
    from collections import Counter

    created_dirs = Counter(str(Path(f).parent) for f in files_created)
    deleted_dirs = Counter(str(Path(f).parent) for f in files_deleted)
    unexplained_file_changes = created_dirs != deleted_dirs

    production_changed = []
    for rel, before_info in prod_snapshot_before.items():
        after_info = prod_snapshot_after.get(rel)
        if before_info is not None and before_info != after_info:
            production_changed.append(rel)

    # ── Abschlussbericht ─────────────────────────────────────────────────
    changed = [r for r in results if r["status"] == "changed"]
    unchanged = [r for r in results if r["status"] == "unchanged"]
    unresolved = [r for r in results if r["unresolved"]]
    errors = [r for r in results if r["status"] == "error"]
    audio_stream_changed = [r for r in results if r["audio_stream_changed"]]
    audio_essence_changed = [r for r in results if r["audio_essence_changed"]]

    _feat_learned_decisions = {"LEARNED", "UPDATED", "WOULD_LEARN", "WOULD_UPDATE"}
    auto_learn_artists = {
        d["canonical"]
        for r in results
        for d in r.get("auto_learn", {}).get("featured_artists", [])
        if d["decision"] in _feat_learned_decisions
    }
    auto_learn_genres = {
        r["auto_learn"]["genre"]["artist"]
        for r in results
        if r.get("auto_learn", {}).get("genre")
        and r["auto_learn"]["genre"]["decision"] in _feat_learned_decisions
    }

    log.section("FINAL SUMMARY", emoji="🏁")
    log.kv("Files processed", len(results), indent=0)
    log.kv("Changed", len(changed), indent=0)
    log.kv("Unchanged", len(unchanged), indent=0)
    log.kv("Unresolved", len(unresolved), indent=0)
    log.kv("Errors", len(errors), indent=0)
    log.kv("Auto-Learn Artists (Feature-Artists)", len(auto_learn_artists), indent=0)
    if auto_learn_artists:
        log.kv("  Artists", sorted(auto_learn_artists), indent=0)
    log.kv("Auto-Learn Genres", len(auto_learn_genres), indent=0)
    if auto_learn_genres:
        log.kv("  Artists", sorted(auto_learn_genres), indent=0)

    log.section("POST-RUN SAFETY CHECK", emoji="🔎")
    log.kv("Production files changed", f"{len(production_changed)}/{len(prod_snapshot_before)}", indent=0)
    if production_changed:
        for rel in production_changed:
            log.kv("  !!! GEAENDERT", rel, indent=0)
    log.kv("Production check enabled", production_check_enabled, indent=0)
    log.kv("Directory structure changes", int(dirs_changed), indent=0)
    log.kv("Files created", len(files_created), indent=0)
    log.kv("Files deleted", len(files_deleted), indent=0)
    log.kv(
        "  davon durch Rename im selben Verzeichnis erklaerbar",
        not unexplained_file_changes,
        indent=0,
    )
    log.kv("Audio essence changes", f"{len(audio_essence_changed)}/{len(results)}", indent=0)
    log.kv("Audio stream (codec/rate/channels/duration) changes", len(audio_stream_changed), indent=0)

    overall_pass = (
        not production_changed
        and not dirs_changed
        and not unexplained_file_changes
        and not audio_essence_changed
        and not audio_stream_changed
        and not errors
    )
    overall = "PASS" if overall_pass and not unresolved else (
        "PASS WITH UNRESOLVED CASES" if overall_pass else "FAIL"
    )
    log.kv("Overall", overall, indent=0)
    log.close()

    summary = {
        "artist": artist_name,
        "dry_run": args.dry_run,
        "files_processed": len(results),
        "changed": len(changed),
        "unchanged": len(unchanged),
        "unresolved": len(unresolved),
        "errors": len(errors),
        "audio_stream_changes": len(audio_stream_changed),
        "audio_essence_changes": len(audio_essence_changed),
        "directory_structure_changes": int(dirs_changed),
        "production_file_changes": len(production_changed),
        "files_created": len(files_created),
        "files_deleted": len(files_deleted),
        "auto_learn_artists": sorted(auto_learn_artists),
        "auto_learn_genres": sorted(auto_learn_genres),
        "overall": overall,
        "log": str(log_path),
        "results": results,
    }
    print(f"Log: {log_path}")
    print(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    asyncio.run(main())
