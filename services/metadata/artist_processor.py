# services/metadata/artist_processor.py
# -*- coding: utf-8 -*-

import re
from typing import List, Optional, Tuple

from logger import get_module_logger
from .models import split_main_and_featuring


class ArtistProcessor:
    """
    Verantwortlich für Artist-Bestimmung, -Bereinigung und -Normalisierung.
    Kapselt die gesamte Logik zur Ermittlung des korrekten Künstlernamens
    aus verschiedenen Quellen (YouTube-Parser, Raw-Metadaten, Dominant-Artist,
    Channel-Name).
    """

    def __init__(self, artist_normalizer, logger=None):
        self.artist_normalizer = artist_normalizer
        self.logger = logger or get_module_logger("ArtistProcessor")

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ─────────────────────────────────────────────────────────────────────────

    def determine_best_artist(
        self,
        raw_artist: str,
        parsed_artist: str,
        dominant_artist: str,
        channel_name: str,
    ) -> Tuple[str, str, List[str]]:
        """
        Bestimmt den besten Künstlernamen aus den verfügbaren Quellen.
        Gibt (artist_name, source, feat_artists) zurück.

        Priorität: dominant_artist > parsed_artist > raw_artist > channel_name

        ARTIST-001-Fix: Haupt-/Feature-Artist werden VOR der Normalisierung
        getrennt (split_main_and_featuring), nicht danach. Vorher lief der
        komplette, unaufgeteilte Collaboration-String (z.B. "GReeeN & 1986zig
        feat. Bausa") durch ArtistNormalizer.normalize(), das jede
        Collaboration zu einer gleichrangigen Komma-Liste abflacht - ein
        nachgelagerter Re-Split in enhanced_metadata_processor.py konnte
        einen urspruenglich zusammengesetzten Hauptartist (hier "GReeeN &
        1986zig") dann nicht mehr von echten Features unterscheiden und
        degradierte z.B. "1986zig" faelschlich zum Feature.

        P0-G-Cleanup (docs/audits/P0_ARTIST_PROCESSOR_AUDIT_2026-09-02.md,
        Abschnitt 1a): die Zweige raw_metadata/channel_fallback enthielten
        bis hierher zusaetzlich einen Vergleich gegen bereits verworfene
        hoeherpriore Kandidaten (z.B. "norm_raw != norm_parsed"). Live und
        strukturell bewiesen tot: jeder erfolgreiche Zweig gibt sofort
        zurueck, ein spaeterer Zweig wird also nur erreicht, wenn die
        vorherigen Kandidaten bereits gescheitert (=None) sind - ein
        Vergleich gegen None ist bei einem gueltigen neuen Kandidaten immer
        wahr. Entfernt, keine Verhaltensaenderung (siehe Regressionstest
        test_priority_chain_duplicate_guards_never_block_a_lower_priority_
        fallback in tests/test_metadata_modules.py).
        """
        self.logger.debug("🎤 Artist-Bestimmung:")
        self.logger.debug(f"   Raw Artist: '{raw_artist}'")
        self.logger.debug(f"   Parsed Artist: '{parsed_artist}'")
        self.logger.debug(f"   Dominant Artist: '{dominant_artist}'")
        self.logger.debug(f"   Channel Name: '{channel_name}'")

        def _clean_and_normalize(
            artist_str: str,
        ) -> Tuple[Optional[str], str, List[str]]:
            if not artist_str:
                return None, "none", []
            cleaned = self.clean_artist_before_normalization(artist_str)
            if not cleaned or len(cleaned) < 2:
                return None, "cleaned_invalid", []
            main_part, feat_parts = split_main_and_featuring(cleaned)
            main_part = main_part or cleaned
            normalized = self.artist_normalizer.normalize(main_part)
            if normalized and normalized.lower() != "unknown":
                return normalized, "normalized", feat_parts
            return main_part, "cleaned_raw_fallback", feat_parts

        if dominant_artist:
            norm_dom, src_dom, feat_dom = _clean_and_normalize(dominant_artist)
            if src_dom in ["normalized", "cleaned_raw_fallback"]:
                self.logger.debug(f"🎤 Artist aus Dominant/Playlist: '{norm_dom}'")
                return norm_dom, "playlist_dominant", feat_dom

        norm_parsed, src_parsed, feat_parsed = _clean_and_normalize(parsed_artist)
        if src_parsed in ["normalized", "cleaned_raw_fallback"]:
            self.logger.debug(f"🎤 Artist aus YouTube-Parser: '{norm_parsed}'")
            return norm_parsed, "youtube_parsed", feat_parsed

        norm_raw, src_raw, feat_raw = _clean_and_normalize(raw_artist)
        if src_raw in ["normalized", "cleaned_raw_fallback"]:
            self.logger.debug(f"🎤 Artist aus Raw-Metadaten: '{norm_raw}'")
            return norm_raw, "raw_metadata", feat_raw

        channel_primary = self.clean_artist_before_normalization(channel_name)
        norm_channel, src_channel, feat_channel = _clean_and_normalize(
            channel_primary
        )

        if src_channel in ["normalized", "cleaned_raw_fallback"]:
            self.logger.warning(
                f"🎤 Artist-Fallback auf Channel-Name: '{norm_channel}'"
            )
            return norm_channel, "channel_fallback", feat_channel

        self.logger.warning(
            "🎤❌ Keine gültigen Artist-Kandidaten gefunden, verwende Fallback"
        )
        return "Unbekannter Künstler", "fallback", []

    def raw_name_for_learning(
        self, track_metadata: dict, canonical_name: str
    ) -> str:
        """
        Bestimmt den 'rohen' Namen fuer AutoLearnManager.learn_artist()
        (2026-09-03, Live-Fund: Repost-/Compilation-Kanal 'GermanHype'
        lernte faelschlich Aliase 'GermanHype' -> 'Peter Maffay'/'Calvin
        Harris' in auto_learned_artist_aliases.json, obwohl der
        Titel-Parser den jeweiligen Kuenstler korrekt AUS DEM TITEL erkannt
        hatte - der Kanalname war an der eigentlichen Artist-Bestimmung gar
        nicht beteiligt, artist_source war 'youtube_parsed').

        track_metadata['uploader'] (der Kanalname) bleibt bewusst ein
        zulaessiger Kandidat: im Normalfall (eigener Kuenstler-Kanal) IST
        der Kanalname die authentische, rohe Schreibweise des
        Kuenstlernamens (z.B. Kanal 'MAKKO' waehrend der normalisierte Name
        'Makko' lautet) - das automatische Lernen von Schreibvarianten
        funktioniert nur deshalb.

        WICHTIG (per Live-Debug-Log bewiesen, 2026-09-03, siehe
        tests/test_artist_processor_raw_name_for_learning.py):
        track_metadata['artist'] ist KEINE von uploader unabhaengige Quelle.
        services/downloader/download_utils.py setzt es bereits BEIM
        DOWNLOAD-SCHRITT auf 'video_info.get("artist") or
        video_info.get("uploader")' (Single-Track- UND Playlist-Pfad) - bei
        Videos ohne echtes yt-dlp-Artist-Tag (Normalfall bei Repost-
        Kanaelen) ist es daher schlicht IDENTISCH mit dem Kanalnamen. Ein
        erster Fix-Versuch pruefte nur uploader gegen canonical_name und
        liess artist_field danach UNGEPRUEFT als Fallback durch - der
        Kanalname kam dadurch ueber diesen Umweg trotzdem durch (live
        reproduziert: Fall Calvin Harris/GermanHype).

        Deshalb werden JETZT BEIDE Kandidaten (uploader und
        track_metadata['artist']) gleichermassen gegen den bereits
        bestimmten canonical_name geprueft - nur ein Kandidat, der ihm
        tatsaechlich aehnelt (identisch oder Teilstring in eine der beiden
        Richtungen, case-insensitiv), wird als roher Name geliefert. Deckt
        weiterhin alle Normalfaelle ab ('MAKKO' vs. 'Makko', 'Miksu' vs.
        'Miksu & Macloud', 'Makko - Topic' vs. 'Makko'), verwirft aber
        beide Kandidaten, wenn keiner aehnelt (GermanHype vs. Peter
        Maffay/Calvin Harris/Oimara - unabhaengig davon, dass artist_field
        denselben kontaminierten Wert wie uploader trug). Fehlt
        canonical_name (kein bereits bestimmter Artist zum Vergleichen),
        wird konservativ das bisherige Verhalten beibehalten (uploader
        bevorzugt) - kein Overreach in einen nicht beobachteten Fall.
        """
        uploader = (track_metadata.get("uploader") or "").strip()
        artist_field = (track_metadata.get("artist") or "").strip()

        if not canonical_name:
            return uploader or artist_field

        canonical_lower = canonical_name.strip().lower()

        def _resembles(candidate: str) -> bool:
            if not candidate:
                return False
            candidate_lower = candidate.lower()
            return (
                candidate_lower == canonical_lower
                or candidate_lower in canonical_lower
                or canonical_lower in candidate_lower
            )

        if _resembles(uploader):
            return uploader
        if _resembles(artist_field):
            return artist_field
        return ""

    def clean_artist_before_normalization(self, artist: str) -> str:
        """
        Bereinigt einen Roh-Artist-String vor der Normalisierung.
        Entfernt Channel-Suffixe (VEVO, Topic, Official usw.), Episodennummern
        und extrahiert den primären Teil aus zusammengesetzten Channel-Namen.
        """
        if not artist:
            return ""

        def _channel_primary_part(name: Optional[str]) -> Optional[str]:
            if not name:
                return None
            # Nur Separatoren MIT Leerzeichen – bare "-", "|", ":" würden
            # Künstlernamen wie "t-low", "K-Fly", "will.i.am" zerstören.
            for sep in [" - ", " | ", " – ", " — "]:
                if sep in name:
                    return name.split(sep)[0].strip()
            return name.strip()

        cleaned = _channel_primary_part(artist)

        if ", " in cleaned:
            main_artist = cleaned.split(", ")[0].strip()
            if len(main_artist) > 2:
                cleaned = main_artist
                self.logger.debug(
                    f"🎤 Multi-Artist bereinigt: '{artist}' -> '{cleaned}'"
                )

        cleanup_patterns = [
            r"\s*-\s*Topic$",
            r"\s*VEVO$",
            r"\s*Official$",
            r"\s*Music$",
            r"\s*Records$",
            r"^\s*Various\s*Artists?\s*$",
        ]

        for pattern in cleanup_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        if re.match(r"^\d{1,4}/\d{4}$", cleaned):
            self.logger.info(
                f"🎙️ Podcast-Episodennummer als Künstler erkannt: '{cleaned}' "
                f"→ wird ignoriert, Channel-Name wird als Fallback verwendet"
            )
            return ""

        return cleaned

    def split_feature_artists(self, artist_string: str) -> Tuple[str, List[str]]:
        """
        Splitet einen Artist-String in Hauptartist und Feature-Artists.
        Delegiert an split_main_and_featuring aus models.
        """
        return split_main_and_featuring(artist_string)
