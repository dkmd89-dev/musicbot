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
