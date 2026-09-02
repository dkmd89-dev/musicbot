# services/clients/musicbrainz_client.py
# -*- coding: utf-8 -*-
"""
MusicBrainzClient – liefert Metadaten (Genre, IDs, Album, Jahr) via MusicBrainz API.

ÄNDERUNGEN v2:
  - GenreMapper und ArtistNormalizer werden nicht mehr selbst instanziiert.
    Stattdessen werden die Singleton-Getter get_genre_mapper() und
    get_artist_normalizer() verwendet → kein doppeltes Laden von YAMLs/Library.
  - parse_search_terms(): ParseResult ist ein Dataclass-Objekt, kein Dict.
    Zugriff auf .artist_string und .title jetzt als Attribute (war vorher
    .get("artist_string") → AttributeError bei jedem " - "-Titel).
  - fetch_metadata() gibt jetzt immer recording_id, artist_id, release_id,
    release_group_id und isrc zurück (waren schon drin, bleiben unverändert).
    GenreProcessor liest diese Felder und hängt sie an GenreResult.mb_ids,
    damit enhanced_metadata_processor den zweiten MB-Aufruf überspringen kann.

ARCH-012 Phase 3B: die client-seitige Genre-Verdichtung per
GenreMapper.determine_genre() wurde entfernt (Phase 3A hatte belegt, dass
sie bei Multi-Tag-Ergebnissen keinen sauberen Einzelgenre-Namen liefert,
sondern den kompletten, title-gecasten Tag-String). fetch_metadata()
liefert seither nur noch die rohen release-group-Tags ("tags") - die
fachliche Priorisierung liegt jetzt ausschließlich in
services/metadata/genre_processor.py::_fetch_genre_from_musicbrainz()
über die bestehende prioritize_genres()-Logik (analog zum Last.fm-Pfad).
Siehe docs/archive/arch/MusicBot_ARCH-012_Genre_Logic_Characterization.md, Abschnitt
"Phase 3B".
"""

import asyncio
import musicbrainzngs
from cachetools import TTLCache
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional, Dict, Any

from config import Config
import async_timeout
from logger import get_module_logger

metadata_logger = get_module_logger("metadata")

_musicbrainz_result_cache = TTLCache(maxsize=200, ttl=3600)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


async def cached_musicbrainz_search(query: str, search_type: str) -> dict:
    context_str = f"MusicBrainzCache:{search_type}"
    if query in _musicbrainz_result_cache:
        metadata_logger.debug(f"[{context_str}] 🎯 [Cache Hit] MusicBrainz: '{query}'")
        return _musicbrainz_result_cache[query]

    try:
        metadata_logger.debug(f"[{context_str}] 🌐 [API Request] MusicBrainz: '{query}'")
        if search_type == "recording":
            result = await asyncio.to_thread(
                musicbrainzngs.search_recordings, query=query, limit=10
            )
        elif search_type == "release":
            result = await asyncio.to_thread(
                musicbrainzngs.search_releases, query=query, limit=10
            )
        else:
            metadata_logger.error(f"[{context_str}] ❌ Ungültiger Suchtyp: {search_type}")
            return {}

        _musicbrainz_result_cache[query] = result
        return result
    except musicbrainzngs.NetworkError as e:
        metadata_logger.error(f"[{context_str}] 📡 MusicBrainz network error: {e}", exc_info=True)
        return {}
    except Exception as e:
        metadata_logger.error(f"[{context_str}] ❌ MusicBrainz cache/API error: {e}", exc_info=True)
        return {}


def _get_artist_normalizer():
    """
    Lazy-Getter für den ArtistNormalizer.

    Verwendet get_artist_normalizer() aus utils.artist_map wenn vorhanden
    (Singleton-Pattern analog zu get_genre_mapper). Fällt andernfalls auf
    eine eigene Instanz zurück, damit der Client auch standalone funktioniert.
    """
    try:
        from utils.artist_map import get_artist_normalizer
        return get_artist_normalizer()
    except (ImportError, AttributeError):
        # Fallback: eigene Instanz (wie bisher) wenn kein Singleton exportiert
        from utils.artist_map import ArtistNormalizer, ArtistConfig
        _cfg = ArtistConfig(
            library_dir=Path(Config.LIBRARY_DIR),
            override_file=Path(Config.ARTIST_OVERRIDE_FILE),
        )
        return ArtistNormalizer(_cfg)


class MusicBrainzClient:
    def __init__(self, logger: Optional[Any] = None):
        """
        Initialisiert den MusicBrainzClient.

        Args:
            logger: Optionale Logger-Instanz. Wird keine übergeben, wird eine
                    neue Instanz über `get_module_logger` erstellt.
        """
        self.logger = logger or get_module_logger("MusicBrainzClient")

        musicbrainzngs.set_useragent("yt_music_bot", "1.0", "support@example.com")

        # Singleton-Referenz statt eigener Instanz
        self.artist_normalizer = _get_artist_normalizer()

        self.logger.info(
            "✨ MusicBrainzClient initialisiert (ArtistNormalizer via Singleton)."
        )

    async def _fetch_release_group_id(self, release_id: str) -> Optional[str]:
        """Holt die Release-Group ID über eine separate API-Abfrage"""
        try:
            if not release_id:
                return None

            self.logger.debug(f"🔍 Hole Release-Group ID für Release: {release_id[:8]}...")
            release_data = await asyncio.to_thread(
                musicbrainzngs.get_release_by_id,
                release_id,
                includes=["release-groups"]
            )

            if "release" in release_data and "release-group" in release_data["release"]:
                release_group_id = release_data["release"]["release-group"]["id"]
                self.logger.info(f"🎨 Release-Group ID gefunden: {release_group_id[:8]}...")
                return release_group_id
        except Exception as e:
            self.logger.debug(f"⚠️ Fehler beim Holen der Release-Group ID: {e}")
        return None

    def _extract_release_group_id(self, recording_data: dict) -> Optional[str]:
        """Extrahiert die Release-Group ID aus Recording-Daten"""
        try:
            if "releases" in recording_data and recording_data["releases"]:
                for release in recording_data["releases"]:
                    if "release-group" in release and "id" in release["release-group"]:
                        release_group_id = release["release-group"]["id"]
                        self.logger.debug(f"🎵 Release-Group ID gefunden: {release_group_id}")
                        return release_group_id
        except Exception as e:
            self.logger.debug(f"⚠️ Fehler beim Extrahieren der Release-Group ID: {e}")
        return None

    def _extract_track_number(self, match: dict, release_list: list) -> Optional[int]:
        """
        Ermittelt die echte Position dieses Recordings innerhalb seines Mediums.

        BUG-001-Fix: vorher wurde faelschlich first_release["medium-track-count"]
        verwendet - laut musicbrainzngs-Quellcode (mbxml.py) ist das die
        GESAMTANZAHL der Tracks auf dem Medium, nicht die Position des
        gefundenen Recordings. Jeder Track desselben Albums haette denselben
        falschen Wert erhalten.

        _source_track_number kommt aus _extract_recordings_from_releases()
        (Release-Fallback-Pfad, dort bereits aus dem echten Track-Objekt
        bekannt, first_release wird dort durch _source_release ohne
        medium-list ersetzt). Fuer den regulaeren Recording-Such-Pfad wird
        release_list durchsucht - MusicBrainz liefert dort pro Release nur
        den Medium-/Track-Eintrag, der zu GENAU diesem Recording gehoert.
        """
        raw = match.get("_source_track_number")
        if raw is None:
            for release in release_list:
                for medium in release.get("medium-list", []):
                    for track in medium.get("track-list", []):
                        raw = track.get("number") or track.get("position")
                        if raw:
                            break
                    if raw:
                        break
                if raw:
                    break
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def parse_search_terms(self, title: str, artist: str) -> tuple[str, str]:
        """
        Optimiert Suchtitel und -artist für MusicBrainz.

        BUG FIX: parse_youtube_title() gibt ein ParseResult-Objekt zurück,
        kein Dict. Zugriff war vorher über .get("artist_string") / .get("title")
        → AttributeError. Jetzt: Attributzugriff auf ParseResult.artist_string
        und ParseResult.title.
        """
        context_str = f"MusicBrainzParser:{artist} - {title}"
        if " - " in title:
            self.logger.debug(
                f"[{context_str}] 🔍 Prüfe ob Titel YouTube-Format hat: '{title}'"
            )
            parsed_result = self.artist_normalizer.parse_youtube_title(title)
            # ParseResult ist ein Dataclass → Attributzugriff, kein Dict
            artist_string = getattr(parsed_result, "artist_string", None)
            parsed_title = getattr(parsed_result, "title", None)
            if artist_string and parsed_title:
                self.logger.info(
                    f"[{context_str}] 🎯 YouTube-Titel umgeparst: '{title}' "
                    f"→ Artist: '{artist_string}', Title: '{parsed_title}'"
                )
                return parsed_title, artist_string

        normalized_artist = self.artist_normalizer.normalize(artist)
        if normalized_artist != artist and normalized_artist != "Unknown":
            self.logger.debug(
                f"[{context_str}] 🧹 Artist normalisiert: '{artist}' → '{normalized_artist}'"
            )
            return title, normalized_artist
        return title, artist

    async def fetch_metadata(self, title: str, artist: str) -> dict:
        original_context = f"MusicBrainzClient:{artist} - {title}"
        self.logger.debug(
            f"[{original_context}] 📥 fetch_metadata(): artist='{artist}', title='{title}'"
        )
        try:
            async with async_timeout.timeout(Config.MUSICBRAINZ_TIMEOUT):
                clean_title, clean_artist = self.parse_search_terms(title, artist)
                context_str = f"MusicBrainzClient:{clean_artist} - {clean_title}"
                if clean_title != title or clean_artist != artist:
                    self.logger.info(
                        f"[{context_str}] 🔄 Suchbegriffe optimiert: "
                        f"'{artist}' - '{title}' → '{clean_artist}' - '{clean_title}'"
                    )

                query_combined = f'recording:"{clean_title}" AND artist:"{clean_artist}"'
                result_combined = await cached_musicbrainz_search(query_combined, "recording")
                recordings = result_combined.get("recording-list", [])

                if not recordings:
                    self.logger.debug(
                        f"[{context_str}] ❓ Keine Ergebnisse, Fallback auf Titelsuche."
                    )
                    query_title = f'recording:"{clean_title}"'
                    result_title = await cached_musicbrainz_search(query_title, "recording")
                    recordings = result_title.get("recording-list", [])

                    if not recordings:
                        self.logger.debug(
                            f"[{context_str}] ❓ Keine Aufnahme-Ergebnisse, "
                            "Fallback auf Release-Suche."
                        )
                        query_release = (
                            f'release:"{clean_title}" AND artist:"{clean_artist}"'
                        )
                        result_release = await cached_musicbrainz_search(
                            query_release, "release"
                        )
                        releases = result_release.get("release-list", [])
                        if releases:
                            self.logger.debug(
                                f"[{context_str}] 🔁 {len(releases)} Releases gefunden."
                            )
                            recordings = await self._extract_recordings_from_releases(
                                releases, clean_title, clean_artist
                            )

                if recordings:
                    best = self._get_best_match(recordings, clean_title, clean_artist)
                    if best:
                        self.logger.info(
                            f"[{context_str}] ✅ MusicBrainz Match: "
                            f"'{best.get('artist-credit-phrase')}' - '{best.get('title')}'"
                        )
                        return await self._build_metadata(best, artist)

                self.logger.warning(
                    f"[{context_str}] ⚠️ Kein Ergebnis für '{clean_artist}' – '{clean_title}'"
                )
                return {}

        except Exception as e:
            self.logger.error(
                f"[{original_context}] 💥 Unerwarteter Fehler: {e}", exc_info=True
            )
        return {}

    async def _extract_recordings_from_releases(
        self, releases: list, target_title: str, target_artist: str
    ) -> list:
        context_str = "MusicBrainzReleaseExtraction"
        recordings = []
        top_releases = releases[:3]
        for release in top_releases:
            release_id = release.get("id")
            if not release_id:
                continue
            try:
                self.logger.debug(
                    f"[{context_str}] 🔍 Untersuche Release: "
                    f"'{release.get('title')}' (ID: {release_id})"
                )
                release_data = await asyncio.to_thread(
                    musicbrainzngs.get_release_by_id,
                    release_id,
                    includes=["recordings", "artist-credits"],
                )
                release_info = release_data.get("release", {})
                medium_list = release_info.get("medium-list", [])
                for medium in medium_list:
                    track_list = medium.get("track-list", [])
                    for track in track_list:
                        recording = track.get("recording", {})
                        if recording:
                            recording["_source_release"] = {
                                "id": release_id,
                                "title": release.get("title"),
                                "artist-credit-phrase": release.get("artist-credit-phrase"),
                            }
                            recording["_source_track_number"] = track.get(
                                "number"
                            ) or track.get("position")
                            recordings.append(recording)
            except Exception as e:
                self.logger.warning(
                    f"[{context_str}] ⚠️ Fehler bei Release {release_id}: {e}"
                )
                continue
        self.logger.info(
            f"[{context_str}] 📊 {len(recordings)} Recordings aus "
            f"{len(top_releases)} Releases extrahiert"
        )
        return recordings

    def _get_best_match(self, recordings, clean_title: str, clean_artist: str):
        best_score = 0
        best_match = None
        min_score_threshold = Config.MUSICBRAINZ_MIN_SIMILARITY
        min_artist_similarity = Config.MUSICBRAINZ_MIN_ARTIST_SIMILARITY
        for r in recordings:
            rec_title = r.get("title", "")
            rec_artist_phrase = r.get("artist-credit-phrase", "")
            title_sim = similarity(clean_title, rec_title)
            artist_sim = similarity(clean_artist, rec_artist_phrase)

            normalized_artist_match = False
            if hasattr(self, "artist_normalizer"):
                normalized_rec_artist = self.artist_normalizer.normalize(rec_artist_phrase)
                normalized_clean_artist = self.artist_normalizer.normalize(clean_artist)
                normalized_artist_match = (
                    normalized_rec_artist == normalized_clean_artist
                    and normalized_rec_artist != "Unknown"
                )

            # MB-01: ein (nahezu) perfekter Titeltreffer allein konnte die
            # Gesamtschwelle bisher im Alleingang ueberwinden, selbst bei
            # einem komplett unverwandten Kuenstler (real reproduziert:
            # "Yearboox" vs. "sweetbox" - siehe Config.MUSICBRAINZ_MIN_ARTIST_SIMILARITY-
            # Kommentar). Kandidaten mit zu geringer Artist-Aehnlichkeit
            # werden verworfen, AUSSER die kanonisierten Namen stimmen
            # exakt ueberein (staerkeres Signal als reine Rohstring-
            # Aehnlichkeit, z.B. bei stark abweichenden Schreibweisen).
            if artist_sim < min_artist_similarity and not normalized_artist_match:
                continue

            score = (
                title_sim * Config.MUSICBRAINZ_TITLE_WEIGHT
                + artist_sim * Config.MUSICBRAINZ_ARTIST_WEIGHT
            )
            if clean_artist.lower() == rec_artist_phrase.lower():
                score += 0.1
            if normalized_artist_match:
                score += 0.05
            if score > best_score:
                best_score = score
                best_match = r
        if best_match and best_score >= min_score_threshold:
            # Characterization fuer eine moegliche kuenftige Artist-Korrektur
            # bei hochsicheren Matches (siehe docs/FINDINGS_INDEX.md/Diskussion
            # 2026-09-02, Live-Fund "makko & The Chainsmokers" vs. "The
            # Chainsmokers"): reine Log-Erweiterung, KEINE Verhaltensaenderung.
            # clean_artist/pipeline_artist ist der bereits von der Pipeline
            # bestimmte final_artist (Suchparameter dieser Methode) - bisher
            # ging der eigentliche artist-credit-phrase der Aufnahme nach der
            # Score-Berechnung verloren (_build_metadata() gibt "artist" als
            # blossen Echo von original_artist zurueck, nie den MB-eigenen
            # Wert). Damit lassen sich reale Diskrepanz-Faelle + Scores
            # sammeln, bevor eine Korrektur-Schwelle kalibriert wird.
            best_artist_phrase = best_match.get("artist-credit-phrase", "")
            artist_match_note = (
                "identisch"
                if best_artist_phrase.strip().lower() == clean_artist.strip().lower()
                else f"WEICHT AB von Pipeline-Artist '{clean_artist}'"
            )
            self.logger.info(
                f"[MusicBrainzMatch] ✅ Bestes Match mit Score {best_score:.2f} "
                f"(über Schwelle {min_score_threshold:.2f}) — "
                f"MB-Artist-Credit: '{best_artist_phrase}' ({artist_match_note})"
            )
            return best_match
        return None

    async def _build_metadata(self, match: dict, original_artist: str) -> dict:
        context_str = f"MusicBrainzBuild:{original_artist} - {match.get('title')}"
        recording_mbid = match.get("id")
        recording_detail = {}
        if recording_mbid:
            try:
                self.logger.debug(
                    f"[{context_str}] 🔍 Lade Recording-Details: {recording_mbid}"
                )
                recording_detail = await asyncio.to_thread(
                    musicbrainzngs.get_recording_by_id,
                    recording_mbid,
                    includes=["artists", "releases", "isrcs"],
                )
            except Exception as e:
                self.logger.warning(
                    f"[{context_str}] ⚠️ Konnte Recording-Details nicht laden: {e}"
                )

        recording_info = recording_detail.get("recording", match)

        isrc = None
        isrc_list = recording_info.get("isrc-list", [])
        if isrc_list:
            isrc = isrc_list[0]

        # BUG-002-Fix: get_recording_by_id() unterstuetzt fuer die Entity
        # "recording" keinen "release-groups"-Include (MusicBrainz-API-
        # Limitierung, siehe VALID_INCLUDES['recording'] in musicbrainzngs) -
        # sein release-list enthaelt daher NIE release-group-Daten (Titel/Tags).
        # match's release-list (aus search_recordings) hat diese Daten bereits
        # vorliegen. Vorher wurde sie hier durch die aermere Detail-Antwort
        # ueberschrieben -> mb_tags war dadurch in der Praxis IMMER leer, der
        # komplette "MusicBrainz-Tags -> Genre"-Pfad faktisch tot.
        release_list = match.get("release-list") or recording_info.get(
            "release-list", []
        )
        first_release = release_list[0] if release_list else {}

        source_release = match.get("_source_release")
        if source_release:
            first_release = {
                "id": source_release.get("id"),
                "title": source_release.get("title"),
                "artist-credit-phrase": source_release.get("artist-credit-phrase"),
            }

        release_id = first_release.get("id")
        release_group = first_release.get("release-group", {})
        release_group_id = release_group.get("id") if release_group else None
        if not release_group_id and release_id:
            release_group_id = await self._fetch_release_group_id(release_id)

        release_date = (
            match.get("first-release-date")
            or recording_info.get("first-release-date")
            or release_group.get("first-release-date")
        )
        release_year = (
            release_date[:4] if release_date and len(release_date) >= 4 else None
        )

        mb_tags = [t["name"] for t in release_group.get("tags", [])]

        artist_id = None
        artist_credits = recording_info.get(
            "artist-credit", match.get("artist-credit", [])
        )
        for credit in artist_credits:
            if isinstance(credit, dict) and "artist" in credit:
                artist_id = credit["artist"].get("id")
                break

        album_artist = first_release.get("artist-credit-phrase")

        # ARCH-012 Phase 3B: keine Client-seitige Genre-Verdichtung mehr -
        # "tags" (mb_tags, s.u.) sind die rohen release-group-Tags und die
        # alleinige Grundlage fuer die Genre-Priorisierung in
        # genre_processor.py::_fetch_genre_from_musicbrainz(). "genre"
        # bleibt als Schluessel erhalten (unveraenderte Rueckgabestruktur),
        # liefert aber nur noch den Platzhalter, der zuvor bereits der
        # Fallback-Wert bei fehlenden Tags war.
        genre_value = "unknown"

        self.logger.info(
            f"[{context_str}] 🔖 MB-IDs: "
            f"recording={recording_mbid}, "
            f"artist={artist_id}, "
            f"release={release_id}, "
            f"release_group={release_group_id}, "
            f"isrc={isrc}"
        )

        return {
            "title":          match.get("title"),
            "artist":         original_artist,
            "album":          release_group.get("title") or first_release.get("title"),
            "track_number":   self._extract_track_number(match, release_list),
            "release_date":   release_date,
            "year":           release_year,
            "album_artist":   album_artist,
            "tags":           mb_tags,
            "genre":          genre_value,
            # MBIDs – werden von GenreProcessor in GenreResult.mb_ids geschrieben
            # und von enhanced_metadata_processor in track_metadata übernommen
            "mbid":               recording_mbid,
            "recording_id":       recording_mbid,
            "artist_id":          artist_id,
            "release_id":         release_id,
            "release_group_id":   release_group_id,
            "isrc":               isrc,
        }
