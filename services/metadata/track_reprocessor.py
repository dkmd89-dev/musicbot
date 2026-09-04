# services/metadata/track_reprocessor.py
# -*- coding: utf-8 -*-
"""
Kern der Pro-Datei-Metadaten-Neuverarbeitung — die eigentliche Pipeline-
Orchestrierung, die frueher komplett in scripts/reprocess_artist_metadata.py
lag.

Ausgelagert (2026-09-04, Nutzer-Entscheidung „Option 2a"), damit BEIDE
Aufrufer denselben, unveraenderten Kern nutzen:

  * scripts/reprocess_artist_metadata.py  — das isolierte Test-CLI (behaelt
    seine ALLOWED_ROOT=/tmp/musicbot_test-Path-Safety, seinen
    ReprocessLogger und die Post-Run-Snapshots; importiert nur noch diesen
    Kern statt ihn zu definieren). Das Telegram-Menue ruft dieses Skript
    weiterhin ausschliesslich als Subprozess auf — unveraendert.

  * services/library_repair/executor.py::apply_level2() — die Library-
    Reparatur, die den Kern in-process mit der ECHTEN config.Config +
    dem library_repair-Sicherheitsmodell (Backup ausserhalb der Library,
    Journal, Audio-Essenz-MD5 before==after, Verification-Scan) verwendet.

Dieses Modul bindet KEINE Config (weder config.py noch config_test) — der
`processor` (EnhancedMetadataProcessor) und die Clients werden vom Aufrufer
konstruiert und hereingereicht. Es beruehrt den Audio-Stream in keinem
Modus (keine Neucodierung — utils.audio_enhancer wird nie importiert).

Der `log`-Parameter von process_file() ist strukturell dieselbe API wie der
ReprocessLogger des Skripts (`.section()/.kv()/.line()`); Aufrufer ohne
Log-Bedarf reichen `NullReprocessLog()` herein.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from services.metadata.models import split_main_and_featuring
from utils.helpers import sanitize_filename
from utils.regex import ILLEGAL_CHARS_PATTERN
from mutagen.mp4 import MP4

if TYPE_CHECKING:  # nur fuer Typannotationen — kein Laufzeit-Import
    from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
    from services.clients.musicbrainz_client import MusicBrainzClient
    from services.clients.lastfm_client import LastFMClient


class ReprocessLog(Protocol):
    """Strukturell identisch zum ReprocessLogger des CLI — die einzige
    Log-Oberflaeche, die process_file() nutzt."""

    def line(self, text: str = "") -> None: ...
    def section(self, title: str, emoji: str = "─") -> None: ...
    def kv(self, key: str, value, indent: int = 1) -> None: ...


class NullReprocessLog:
    """No-op-Log fuer programmatische Aufrufer (z. B. apply_level2), die die
    strukturierte Live-Logdatei des CLI nicht brauchen."""

    def line(self, text: str = "") -> None:
        pass

    def section(self, title: str, emoji: str = "─") -> None:
        pass

    def kv(self, key: str, value, indent: int = 1) -> None:
        pass


MB_ID_ATOM_MAP = {
    "recording_id": "----:com.apple.iTunes:MusicBrainz Recording Id",
    "artist_id": "----:com.apple.iTunes:MusicBrainz Artist Id",
    "release_id": "----:com.apple.iTunes:MusicBrainz Release Id",
    "release_group_id": "----:com.apple.iTunes:MusicBrainz Release Group Id",
    "isrc": "----:com.apple.iTunes:ISRC",
}



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
# Genre-Downgrade-Schutz (Phase 1, 2026-09-02)
# ─────────────────────────────────────────────────────────────────────────


def count_existing_genre_entries(genre_tag_values: list) -> int:
    """Zaehlt, wie viele einzelne Genre-Werte im bestehenden ©gen-Tag
    stecken - unabhaengig davon, ob mit dem aktuellen '; '-Separator
    (seit 2026-09, siehe services/metadata/tag_writer.py) oder dem
    aelteren ' / '-Separator geschrieben wurde (reale Bestandsdateien der
    Produktions-Library koennen beides enthalten, je nachdem wann sie
    zuletzt getaggt wurden). Ein einzelner, unsepariert er String zaehlt
    als 1 Eintrag."""
    if not genre_tag_values or not genre_tag_values[0]:
        return 0
    value = genre_tag_values[0]
    for sep in ("; ", " / "):
        if sep in value:
            return len([p for p in value.split(sep) if p.strip()])
    return 1


def genre_would_downgrade(before_genre_tag: list, genres_result) -> bool:
    """Analog zur bereits bestehenden MB-IDs-Regel ('keine vorhandenen
    korrekten IDs unnoetig ueberschreiben', siehe process_file()): eine
    frische determine_genre_with_fallbacks()-Antwort ist normales
    Antwortverhalten externer Quellen und kann - ohne dass irgendetwas
    fehlerhaft ist - diesmal WENIGER Genre-Werte liefern als bereits im
    Tag stehen (z.B. aus einem frueheren, reichhaltigeren Lauf). Ein
    bereits reichhaltigerer bestehender Tag soll dadurch nicht ERSETZT
    werden - siehe process_file() fuer die Verwendung (UNRESOLVED statt
    stillem Downgrade, 'nicht raten')."""
    if not genres_result or not getattr(genres_result, "primary", None):
        return False
    fresh_count = 1 + len(getattr(genres_result, "secondary", None) or [])
    existing_count = count_existing_genre_entries(before_genre_tag)
    return existing_count > fresh_count


# ─────────────────────────────────────────────────────────────────────────
# Produzenten-Credit-Bereinigung (Phase 1, 2026-09-02, Nutzer-Fund)
# ─────────────────────────────────────────────────────────────────────────

# Geklammerte Form ("(prod. by X)", "(prod X)") - deckungsgleich zur
# Produktions-Regel in utils/youtube_parser.py::_clean_title_suffixes().
_PRODUCER_CREDIT_PAREN_PATTERN = re.compile(
    r"\s*\(\s*prod\.?\s*(?:by\s+)?[^)]*\)", re.IGNORECASE
)
# Klammerlose, trennerlose Form am Titelende ("'ADLIBS' prod. Safecall777")
# - Live-Fund 2026-09-02 (Nutzer-Report, Track "makko - \"ADLIBS\" prod.
# Safecall777"): WEDER die geklammerte Form oben NOCH die in
# _clean_title_suffixes() zusaetzlich vorhandene Bindestrich-Form
# ("- prod...") erkennen dieses Muster - per echtem
# utils.youtube_parser.parse_youtube_title()-Aufruf verifiziert, dass
# selbst die volle Download-Pipeline diesen Titel unveraendert liesse
# (kein Klammer-/Bindestrich-Trenner vor "prod." vorhanden). Eigenstaendiger
# Fund, nicht in dieser Phase in der Produktionslogik behoben (siehe
# docs/FINDINGS_INDEX.md) - hier nur fuer das Reprocessing-Tool selbst
# ergaenzt. \bprod\b mit zwingendem "."/Whitespace danach verhindert
# Fehltreffer in Woertern wie "Producer"/"Production".
_PRODUCER_CREDIT_BARE_PATTERN = re.compile(
    r"\s*[-–—]?\s*\bprod\.?\s+(?:by\s+)?\S.*$", re.IGNORECASE
)


def strip_producer_credit(title: str) -> str:
    """Entfernt einen abschliessenden Produzenten-Credit aus dem TITEL
    selbst - '\"ADLIBS\" prod. Safecall777' -> '\"ADLIBS\"'.
    Deckt sowohl die geklammerte als auch die klammerlose/trennerlose Form
    ab. Bleibt am Ende nichts Sinnvolles uebrig, wird der Original-Titel
    unveraendert zurueckgegeben - kein leerer Titel."""
    cleaned = _PRODUCER_CREDIT_PAREN_PATTERN.sub("", title)
    cleaned = _PRODUCER_CREDIT_BARE_PATTERN.sub("", cleaned).strip()
    return cleaned or title


# ─────────────────────────────────────────────────────────────────────────
# Remix-Zusatz-Bereinigung (Phase 1, 2026-09-02, erweitert 2026-09-03)
# ─────────────────────────────────────────────────────────────────────────

_REMIX_SUFFIX_PATTERN = re.compile(r"\s*\([^()]*\bremix\b[^()]*\)\s*$", re.IGNORECASE)


def strip_remix_suffix(title: str) -> str:
    """Leitet aus einem Titel wie 'Blauer Tag (Robin Schulz Remix)' den
    Basis-Song-Namen 'Blauer Tag' ab. Entfernt ausschliesslich ein
    abschliessendes '(...Remix...)'-Klammerpaar, keine sonstige
    Bereinigung. Bleibt am Ende nichts Sinnvolles uebrig (z.B. Titel
    bestand nur aus der Klammer), wird der Original-Titel unveraendert
    zurueckgegeben - kein leerer Titel/leeres Album raten.

    Ursprünglich (2026-09-02, Live-Testlauf Artist 'Möwe') nur fuer den
    Album-FALLBACK gedacht (der TITEL-Tag sollte laut damaliger
    Nutzer-Entscheidung unveraendert mit Remix-Hinweis bleiben - 'album:
    [Blauer Tag (Robin Schulz Remix)]' identisch zu title war der
    urspruengliche Fund).

    Nutzer-Entscheidung 2026-09-03 (Rueckfrage zum selben Fund, diesmal
    ueber die neue Telegram-Integration reproduziert): diese Entscheidung
    wird bewusst umgekehrt - der TITEL soll jetzt dieselbe Logik wie die
    echte Download-Pipeline verwenden. Verifiziert in
    utils/youtube_parser.py::parse_youtube_title() Schritt 7:
    _clean_bracket_content(song_title, preserve_remix=False) entfernt den
    Remix-Zusatz dort ebenfalls aus dem finalen Titel (nur die
    Artist-/Titel-SPLITTING-Stufe in Schritt 1 behaelt ihn bewusst, um
    Klammerinhalte nicht als Trenner misszuinterpretieren). Diese Funktion
    bleibt eine eigene, lokale Nachbildung statt eines direkten Imports
    von _clean_bracket_content() (private Funktion, arbeitet dort auf
    rohen YouTube-Titeln vor dem Parsing - dieses Skript arbeitet auf
    bereits vorhandenen Tag-Werten, ein anderer Eingabebereich), analog
    zum bereits etablierten Muster von strip_producer_credit() oben
    (eigene, dokumentiert deckungsgleiche Regel statt Cross-Import)."""
    stripped = _REMIX_SUFFIX_PATTERN.sub("", title).strip()
    return stripped or title


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
    log: ReprocessLog,
    dry_run: bool = False,
) -> dict:
    rel = path.relative_to(artist_root.parent)
    log.section(f"🎵 FILE START: {rel}", emoji="🎵")
    log.kv("📂 Input", path)
    if dry_run:
        log.kv("🔒 Modus", "DRY-RUN - keine Datei wird veraendert")

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

    # Phase 1 (2026-09-02, Fehlerisolierung): der BEFORE-Snapshot (inkl.
    # mutagen.mp4.MP4(path)) lief bisher VOR dem folgenden try/except-Block
    # - eine echte, unlesbare/beschaedigte .m4a-Datei liess mutagen dabei
    # eine Exception werfen, die ungefangen aus process_file() propagierte
    # und in main() die gesamte for-Schleife ueber alle Dateien des Artists
    # abbrach, statt nur diese eine Datei als "error" zu protokollieren und
    # mit den uebrigen fortzufahren ("ein fehlerhafter Track darf nicht
    # automatisch den gesamten Artist-Lauf zerstoeren"). Eigener,
    # dedizierter try/except mit identischer result-Struktur wie der
    # bestehende Haupt-except-Block unten, damit main()s Aggregation
    # (status=="error"-Zaehlung) fuer beide Fehlerklassen gleich funktioniert.
    try:
        before = snapshot(path, artist_root)
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"BEFORE-Snapshot fehlgeschlagen: {e}"
        log.line("❌ ERROR (BEFORE SNAPSHOT)")
        log.kv("exception", repr(e))
        log.line("❌ FINAL RESULT: ERROR")
        return result

    log.line("📋 BEFORE SNAPSHOT")
    for k, v in before.items():
        log.kv(k, v)

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
        clean_title = strip_producer_credit(clean_title)
        # Nutzer-Entscheidung 2026-09-03: Titel folgt jetzt derselben Regel
        # wie die echte Download-Pipeline (siehe strip_remix_suffix()-
        # Docstring) - betrifft dadurch automatisch auch den Dateinamen
        # (unten, expected_stem) und den Album-Fallback (unten, kein
        # zusaetzlicher Strip-Aufruf mehr noetig, da clean_title bereits
        # remix-frei ist).
        clean_title = strip_remix_suffix(clean_title)
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

        # Genre-Downgrade-Schutz (Phase 1, siehe genre_would_downgrade()):
        # analog zur MB-IDs-Regel oben - ein bereits reichhaltigerer
        # bestehender Genre-Tag wird nicht durch ein schwaecheres frisches
        # Ergebnis ersetzt. genres_result_for_write ist ausschliesslich fuer
        # den TagWriter-Aufruf/die Dry-Run-Vorhersage relevant - Logging und
        # Auto-Learn unten verwenden weiterhin das echte, ungefilterte
        # genres_result (die frische Bestimmung selbst ist nicht falsch,
        # nur fuer DIESEN Tag-Schreibvorgang nicht die bessere Wahl).
        genre_downgrade = genre_would_downgrade(before["genre_tag"], genres_result)
        genres_result_for_write = None if genre_downgrade else genres_result

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
        if genre_downgrade:
            log.kv(
                "→ ⚠️ Downgrade-Schutz",
                f"bestehender Tag ({before['genre_tag']}) reichhaltiger als "
                f"frisches Ergebnis - Genre-Tag wird NICHT ueberschrieben",
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
        # Vorgezogen (war urspruenglich erst weiter unten bei der
        # Dateinamensplanung berechnet) - wird jetzt bereits hier fuer die
        # Album-Bestimmung gebraucht, siehe Nutzer-Entscheidung 2026-09-03
        # unten.
        is_singles = before["parent_dirname"] == "Singles"

        existing_album = before["album"][0] if before["album"] else None
        # Nutzer-Fund (2026-09-02, echter Testlauf Artist "makko" ueber
        # main, VOR diesem Branch): das bisherige "existing_album or ..."
        # nahm ein vorhandenes Album-Tag IMMER unveraendert - real
        # heruntergeladene Bestandsdateien haben aber so gut wie immer
        # bereits ein Album-Tag (meist eine 1:1-Kopie des urspruenglich
        # dirty Titels), wodurch der Album-Fallback unten in der Praxis
        # kaum je griff. '"Bequem"'/'"Zickzack"'/'"ADLIBS" prod.
        # Safecall777' blieben als Album-Wert unveraendert stehen, obwohl
        # der Titel zur selben Zeit korrekt bereinigt wurde. Nutzer-
        # Entscheidung bei Rueckfrage: ein VORHANDENES Album-Tag wird jetzt
        # denselben Bereinigungsregeln unterzogen wie der Titel
        # (light_title_cleanup(), inkl. dessen Produzenten-Credit-/
        # Anfuehrungszeichen-Fixes) - keine zweite, abweichende
        # Bereinigungslogik, dieselbe bereits produktiv laufende Regelmenge.
        # Bewusst OHNE Artist-Praefix-Entfernung (leerer Artist-Parameter) -
        # ein Album-Wert hat kein Artist-Praefix-Muster wie ein Titel.
        if existing_album:
            existing_album = processor.title_cleaner.light_title_cleanup(
                existing_album, ""
            )
        existing_year_raw = before["year"][0] if before["year"] else None
        try:
            existing_year = int(existing_year_raw) if existing_year_raw else None
        except (TypeError, ValueError):
            existing_year = None

        # Nutzer-Fund/-Entscheidung 2026-09-03: light_title_cleanup() ist
        # bewusst konservativ (siehe dessen eigener Docstring) und entfernt
        # KEINEN Remix-Zusatz - ein bereits vorhandenes Album-Tag wie
        # 'Blauer Tag (Robin Schulz Remix)' blieb dadurch trotz obiger
        # Bereinigung mit Remix-Zusatz stehen, waehrend der TITEL zur
        # selben Zeit bereits korrekt zu 'Blauer Tag' bereinigt wurde
        # (strip_remix_suffix() oben im TitleCleaner-Schritt) - Titel und
        # Album liefen dadurch auseinander. Nutzer-Regel: bei einer Single
        # (Track liegt im Singles-Ordner, nicht in einem Album-Ordner mit
        # Tracknummer) ist das Album per Definition IMMER identisch zum
        # Titel - ein eigenstaendiger, davon abweichender Album-Name ergibt
        # bei einer Einzelveroeffentlichung fachlich keinen Sinn. Fuer
        # Singles wird das (ggf. bestehende, aber ggf. veraltete)
        # Album-Tag deshalb bewusst NICHT als Wahrheit uebernommen, sondern
        # immer durch den bereits bereinigten clean_title ersetzt. Fuer
        # Album-Tracks (eigener Ordner mit Tracknummer) bleibt ein
        # vorhandener, eigenstaendiger Album-Name weiterhin massgeblich -
        # dort ist ein vom Titel abweichender Album-Name die Regel, nicht
        # die Ausnahme.
        if is_singles:
            album_value = clean_title
        else:
            album_value = existing_album or clean_title

        album_info = {
            "album": album_value,
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
                genres_result=genres_result_for_write,
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
            primary = (
                getattr(genres_result_for_write, "primary", None)
                if genres_result_for_write else None
            )
            secondary = (
                getattr(genres_result_for_write, "secondary", None)
                if genres_result_for_write else None
            )
            if primary and secondary:
                combined = [primary] + list(secondary)[:3]
                genre_tag_planned = ["; ".join(combined)]
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
        if genre_downgrade:
            result["unresolved"].append(
                f"Genre-Downgrade-Schutz: bestehender Genre-Tag "
                f"({before['genre_tag']}) enthaelt mehr Werte als das "
                f"frische Ergebnis (primary={getattr(genres_result, 'primary', None)!r} "
                f"secondary={getattr(genres_result, 'secondary', None)!r}). "
                f"Kein automatisches Ersetzen - manuelle Pruefung empfohlen."
            )

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
