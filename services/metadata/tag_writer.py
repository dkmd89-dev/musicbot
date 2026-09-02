# services/metadata/tag_writer.py
# -*- coding: utf-8 -*-

import shutil
import time
from typing import List, Optional, Tuple

from logger import get_module_logger


class TagWriter:
    """
    Verantwortlich für das Schreiben von Metadaten-Tags (Titel, Artist, Album,
    Jahr, Tracknummer, Genre, Lyrics, Cover, MusicBrainz-IDs) in MP4/M4A- und
    MP3-Dateien via mutagen.
    """

    def __init__(self, logger=None, artist_normalizer=None):
        self.logger = logger or get_module_logger("TagWriter")
        self.artist_normalizer = artist_normalizer

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ─────────────────────────────────────────────────────────────────────────

    def write_tags(
        self,
        target_path,
        artist: str,
        title: str,
        album_info,
        track_number,
        genres_result,
        lyrics=None,
        cover_art=None,
        feat_artists=None,
        mb_ids: Optional[dict] = None,
    ) -> None:
        if not target_path.exists():
            self.logger.error(f"❌ Datei nicht gefunden: {target_path}")
            return

        if feat_artists and self.artist_normalizer is not None:
            feat_artists = [
                self.artist_normalizer.normalize(a) or a for a in feat_artists
            ]

        feat_artists = feat_artists or []

        # Live-Fund 2026-09-02 (Nutzer-Report, Nachfolge des Miksu & Macloud-
        # Mapping-Fixes): ein Feature-Artist kann nach der Normalisierung
        # oben auf denselben kanonischen String abbilden wie `artist` selbst
        # (z.B. roher Eintrag "Miksu" -> Override -> "Miksu & Macloud",
        # identisch zum bereits finalen Haupt-Artist "Miksu & Macloud") -
        # ohne Dedup landete der Duo-Name doppelt im ARTISTS-Tag
        # ("Miksu & Macloud; Miksu & Macloud; MACLOUD; makko"). Case-
        # insensitiv dedupen, `artist` behaelt immer den ersten Slot,
        # Reihenfolge der uebrigen feat_artists bleibt erhalten.
        seen = {artist.strip().lower()}
        deduped_feat_artists = []
        for fa in feat_artists:
            key = fa.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            deduped_feat_artists.append(fa)
        feat_artists = deduped_feat_artists

        all_artists = [artist] + feat_artists
        artists_semicolon = "; ".join(all_artists)

        ext = target_path.suffix.lower()
        if ext not in (".m4a", ".mp4", ".m4v", ".mp3"):
            self.logger.warning(f"⚠️ Unbekanntes Format: {ext}")
            return

        # AE-11 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md): mutagen schreibt
        # via audio.save() in-place in die bereits ausgelieferte Library-Datei
        # (rb+, chunk-basiertes Byte-Shifting, kein Tempfile/Rename - direkt
        # im installierten mutagen-Quellcode verifiziert). Ein Fehler oder
        # Prozessabbruch waehrend dieses Vorgangs konnte die zuvor gueltige
        # Datei beschaedigen (empirisch reproduziert: mutagen/ffprobe meldeten
        # die beschaedigte Datei faelschlich als gesund, ein echter
        # ffmpeg-Decode-Pass deckte die Korruption auf). Fix: wie bereits in
        # utils/filenamefixer.py::move_to_library() etabliert - auf einer
        # temporaeren Sibling-Kopie (garantiert selbes Verzeichnis/Dateisystem)
        # taggen, erst bei Erfolg atomar per Path.replace() uebernehmen.
        # target_path bleibt bei jedem Fehler byteidentisch zum Ausgangszustand.
        #
        # Bewusst OHNE fsync(): auf demselben Filesystem wie LIBRARY_DIR
        # gemessen kostet fsync() 77-500ms je nach Dateigroesse (vs. <20ms
        # fuer den reinen Copy+Tag-Vorgang). Schuetzt gezielt gegen
        # Exception/Prozessabbruch waehrend des Schreibens (der bestaetigte,
        # reproduzierte AE-11-Befund) - ein Maschinenabsturz/Stromausfall
        # bleibt ein bereits im gesamten bestehenden Schreibpfad (auch
        # move_to_library()) akzeptiertes Restrisiko, keine neue,
        # inkonsistente Ausnahme nur fuer diese eine Datei.
        #
        # Korrektur (AE-12, docs/MusicBot_ARCHITECTURE_EVOLUTION.md
        # Abschnitt 29): write_tags() lief zum Zeitpunkt der AE-11-
        # Entscheidung noch synchron direkt im Event-Loop-Thread, dort war
        # die INV-01-Vermeidung ein zusaetzliches Argument gegen fsync().
        # Seit AE-12 ruft enhanced_metadata_processor.py write_tags() ueber
        # await asyncio.to_thread(...) auf - dieses spezielle Argument
        # entfaellt damit, die Entscheidung selbst (kein fsync()) bleibt aus
        # den oben genannten, unveraenderten Gruenden weiterhin sinnvoll.
        tmp_path = target_path.with_name(
            f".{target_path.name}.tmp_{int(time.time() * 1000)}"
        )

        try:
            shutil.copy2(target_path, tmp_path)

            if ext in (".m4a", ".mp4", ".m4v"):
                from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

                audio = MP4(tmp_path)
                audio["©nam"] = [title]
                audio["©ART"] = all_artists
                if album_info.get("album"):
                    audio["©alb"] = [album_info["album"]]
                if album_info.get("album_artist"):
                    audio["aART"] = [album_info["album_artist"]]
                if album_info.get("year"):
                    audio["©day"] = [str(album_info["year"])]
                if track_number:
                    audio["trkn"] = [(track_number, 0)]

                self._write_genres_m4a(audio, genres_result)

                if lyrics:
                    audio["©lyr"] = [lyrics.strip()]
                if cover_art:
                    audio["covr"] = [
                        MP4Cover(cover_art, imageformat=MP4Cover.FORMAT_JPEG)
                    ]
                if feat_artists:
                    # TAG-01: Navidrome liest dieses Feld fuer "Zusaetzlicher
                    # Interpret"/Multi-Artist-Splitting (MusicBrainz-Picard-
                    # Konvention) - dafuer muss es mehrere SEPARATE Werte
                    # enthalten, kein mit "; " zusammengefuegter String
                    # (sonst wird der Track unter den Feature-Artists nicht
                    # auffindbar, real via Navidrome/Symfonium bestaetigt).
                    # Das vorherige "ARTISTS"-Atom (ohne "----:"-Praefix) war
                    # ausserdem gar kein gueltiges 4-Byte-MP4-Atom - mutagen
                    # kappte es zu einem bedeutungslosen "ARTI"-Atom, das
                    # keine Software liest. Entfernt.
                    audio["----:com.apple.iTunes:ARTISTS"] = [
                        MP4FreeForm(a.encode("utf-8")) for a in all_artists
                    ]

                if mb_ids:
                    _mb_tag_map = {
                        "recording_id": "----:com.apple.iTunes:MusicBrainz Recording Id",
                        "artist_id": "----:com.apple.iTunes:MusicBrainz Artist Id",
                        "release_id": "----:com.apple.iTunes:MusicBrainz Release Id",
                        "release_group_id": "----:com.apple.iTunes:MusicBrainz Release Group Id",
                        "isrc": "----:com.apple.iTunes:ISRC",
                    }
                    for key, tag_name in _mb_tag_map.items():
                        value = mb_ids.get(key)
                        if value:
                            audio[tag_name] = [MP4FreeForm(str(value).encode("utf-8"))]

                audio.save()

            elif ext == ".mp3":
                from mutagen.id3 import (
                    ID3,
                    TIT2,
                    TPE1,
                    TALB,
                    TPE2,
                    TDRC,
                    TRCK,
                    TCON,
                    USLT,
                    APIC,
                    TXXX,
                )

                try:
                    audio = ID3(tmp_path)
                except Exception:
                    audio = ID3()
                    audio.save(tmp_path)
                    audio = ID3(tmp_path)

                audio.add(TIT2(encoding=3, text=title))
                audio.add(TPE1(encoding=3, text=all_artists))
                if album_info.get("album"):
                    audio.add(TALB(encoding=3, text=album_info["album"]))
                if album_info.get("album_artist"):
                    audio.add(TPE2(encoding=3, text=album_info["album_artist"]))
                if album_info.get("year"):
                    audio.add(TDRC(encoding=3, text=str(album_info["year"])))
                if track_number:
                    audio.add(TRCK(encoding=3, text=str(track_number)))

                self._write_genres_mp3(audio, genres_result, TCON, TXXX)

                if lyrics:
                    audio.add(
                        USLT(encoding=3, lang="deu", desc="", text=lyrics.strip())
                    )
                if cover_art:
                    audio.add(
                        APIC(
                            encoding=3,
                            mime="image/jpeg",
                            type=3,
                            desc="Cover",
                            data=cover_art,
                        )
                    )
                if feat_artists:
                    # TAG-01: mehrere separate Werte statt eines
                    # zusammengefuegten Strings - siehe Kommentar im
                    # MP4-Zweig oben.
                    audio.add(TXXX(encoding=3, desc="ARTISTS", text=all_artists))

                audio.save()

            tmp_path.replace(target_path)

            log_msg = f"📝 Metadaten für '{title}' geschrieben"
            if lyrics:
                log_msg += " (📜 Lyrics)"
            if cover_art:
                log_msg += " (🖼️ Cover)"
            if feat_artists:
                log_msg += f" (🔀 ARTISTS: {artists_semicolon})"
            self.logger.info(log_msg)

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Schreiben: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError as cleanup_err:
                self.logger.error(
                    f"❌ Konnte temporäre Datei nicht entfernen: {cleanup_err}"
                )
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # Interne Helfer
    # ─────────────────────────────────────────────────────────────────────────

    def _write_genres_m4a(self, audio, genres_result) -> None:
        """Schreibt Genre-Tags in eine M4A-Datei."""
        if not genres_result:
            return
        primary, secondary = self._extract_genre_parts(genres_result)
        if primary and secondary:
            combined = [primary] + secondary[:3]
            # "; " statt " / " als Genre-Separator (2026-09, auf
            # ausdruecklichen Wunsch) - zunaechst kontrolliert nur ueber
            # das isolierte Reprocessing-Script validiert
            # (scripts/reprocess_artist_metadata.py), Phase 2: hier direkt
            # uebernommen.
            genre_string = "; ".join(combined)
            audio["©gen"] = [genre_string]
            audio["----:com.apple.iTunes:GENRE"] = [", ".join(combined).encode("utf-8")]
            self.logger.info(f"🏷️ Genres (M4A): '{genre_string}'")
        elif primary:
            audio["©gen"] = [primary]
            self.logger.info(f"🏷️ Genre (M4A): '{primary}'")

    def _write_genres_mp3(self, audio, genres_result, TCON, TXXX) -> None:
        """Schreibt Genre-Tags in eine MP3-Datei."""
        if not genres_result:
            return
        primary, secondary = self._extract_genre_parts(genres_result)
        if primary and secondary:
            combined = [primary] + secondary[:3]
            # "; " statt " / " als Separator - siehe Kommentar in
            # _write_genres_m4a() oben.
            genre_string = "; ".join(combined)
            audio.add(TCON(encoding=3, text=genre_string))
            audio.add(TXXX(encoding=3, desc="GENRE", text=", ".join(combined)))
            audio.add(TXXX(encoding=3, desc="MULTI_GENRE", text=", ".join(combined)))
            self.logger.info(f"🏷️ Genres (MP3): '{genre_string}'")
        elif primary:
            audio.add(TCON(encoding=3, text=primary))
            self.logger.info(f"🏷️ Genre (MP3): '{primary}'")

    def _extract_genre_parts(self, genres_result) -> Tuple[Optional[str], List[str]]:
        """Extrahiert primary und secondary aus einem GenreResult-Objekt oder Dict."""
        if hasattr(genres_result, "primary"):
            return genres_result.primary, getattr(genres_result, "secondary", []) or []
        if isinstance(genres_result, dict):
            return (
                genres_result.get("primary"),
                genres_result.get("secondary", []) or [],
            )
        return None, []
