# services/downloader/download/channel_router.py
# -*- coding: utf-8 -*-
"""
ChannelRouter – Artist/Channel-Routing für Playlists.

Verantwortlichkeit (Single Responsibility):
  - Bestimmt den "dominant_artist" einer Playlist über einen
    5-stufigen Entscheidungsbaum (P1–P5).
  - KEIN Download, KEIN Caching, KEINE Jahr-Bestimmung.

Dependency Injection:
  - `artist_normalizer` (für Channel-Normalisierung & YouTube-Titel-Parsing)
  - `config` (für Spezialkanal-YAML via `load_special_channels_merged`)
  - Eigene Logger-Instanz via `get_module_logger`.

Entscheidungspfade:
  P1 – PlaylistProcessor hat Artist erkannt → direkt verwenden
  P2 – Playlist-Channel ist Spezialkanal   → kanonischen Namen verwenden
  P3 – Track-Level-Uploader ist Spezialkanal (user-gespeicherte Podcasts)
  P4 – Normaler Channel → normalisierten Channel-Namen als Fallback
  P5 – Kein Artist erkennbar → Compilations-Modus (dominant_artist = None)

Log-Marker bleiben unverändert: [CHANNEL], [CHANNEL-P3], Pfad P1–P5.
"""

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from logger import get_module_logger
from utils.filenamefixer import (
    get_special_category,
    get_special_channel_info,
    load_special_channels_merged,
)


class ChannelRouter:
    """
    Bestimmt den kanonischen `dominant_artist` einer Playlist über einen
    5-stufigen Entscheidungsbaum (P1–P5).
    """

    def __init__(self, artist_normalizer, config, logger=None, logger_factory=None):
        self.artist_normalizer = artist_normalizer
        self.config = config
        self.logger = logger or (logger_factory or get_module_logger)("ChannelRouter")

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ─────────────────────────────────────────────────────────────────────────

    def resolve_dominant_artist(
        self,
        dominant_artist: Optional[str],
        playlist_info: Dict[str, Any],
        entries: List[Dict[str, Any]],
    ) -> Tuple[str, Optional[str]]:
        """
        Bestimmt den kanonischen dominant_artist über einen 5-stufigen
        Entscheidungsbaum.

        Gibt zurück: (_channel_raw, dominant_artist)
        """
        self.logger.info("🗺️  [CHANNEL] Starte Channel-Routing-Entscheidungsbaum...")

        # Roh-Channel aus Playlist oder erstem Eintrag
        _channel_raw = (
            playlist_info.get("uploader")
            or playlist_info.get("channel")
            or (entries[0].get("uploader") if entries else None)
            or (entries[0].get("channel") if entries else None)
            or ""
        )

        self.logger.info(
            f"   Playlist-Channel (roh) : '{_channel_raw}'\n"
            f"   dominant_artist bisher : '{dominant_artist or 'nicht gesetzt'}'"
        )

        # ── P1: PlaylistProcessor hat bereits einen Artist erkannt ────────────
        p1_artist = self._path_playlist_processor_artist(dominant_artist)
        if p1_artist is not None:
            return _channel_raw, p1_artist

        # Ab hier: dominant_artist ist None → Fallback-Logik
        if not _channel_raw:
            self._path_compilation_mode(
                reason="Kein Channel-Name verfügbar", path_label="P5"
            )
            return _channel_raw, None

        # Channel normalisieren
        try:
            _channel_normalized = self.artist_normalizer.normalize(_channel_raw)
            if not _channel_normalized or _channel_normalized.lower() in (
                "unknown",
                "unbekannt",
                "",
            ):
                _channel_normalized = _channel_raw
        except Exception as norm_err:
            self.logger.debug(
                f"   Channel-Normalisierung fehlgeschlagen (harmlos): {norm_err}"
            )
            _channel_normalized = _channel_raw

        self.logger.info(
            f"   Channel normalisiert   : '{_channel_normalized}'\n"
            f"   → Prüfe Spezialkanal-Status..."
        )

        # ── P2: Playlist-Channel ist Spezialkanal ──────────────────────────────
        p2_artist = self._path_playlist_channel_special(
            channel_raw=_channel_raw, channel_normalized=_channel_normalized
        )
        if p2_artist is not None:
            return _channel_raw, p2_artist

        # ── P3: Track-Level-Uploader könnte Spezialkanal sein ─────────────────
        self.logger.info(
            f"   Playlist-Channel '{_channel_raw}' ist kein Spezialkanal\n"
            f"   → Prüfe Track-Level-Uploader (für user-gespeicherte Podcasts)..."
        )
        p3_artist = self._path_track_level_special(entries)
        if p3_artist is not None:
            self.logger.info(
                f"🎙️ [CHANNEL] Pfad P3: Track-Level-Spezialkanal gefunden!\n"
                f"   Playlist-Uploader : '{_channel_raw}' (kein Spezialkanal)\n"
                f"   Track-Spezialkanal: '{p3_artist}'\n"
                f"   → dominant_artist = '{p3_artist}'"
            )
            return _channel_raw, p3_artist

        # ── P4: Normaler Channel als Fallback ─────────────────────────────────
        p4_artist = self._path_normalized_channel_fallback(_channel_raw)
        if p4_artist is not None:
            return _channel_raw, p4_artist

        # ── P5: Compilations-Modus ─────────────────────────────────────────────
        self._path_compilation_mode(
            reason="Kein Artist ermittelbar", path_label="P5"
        )
        return _channel_raw, None

    def find_dominant_special_channel_from_entries(
        self, entries: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Prüft ob der häufigste Track-Level-Uploader ein Spezialkanal ist.

        Anwendungsfall:
          yt-dlp liefert bei user-gespeicherten Playlists:
            playlist_info["uploader"] = "DkmD89"          ← User (kein Spezialkanal)
            entries[i]["uploader"]    = "Sky Sport Formel 1"  ← echter Podcast-Kanal

        Vorgehen:
          1. Counter über alle entries["uploader"] / entries["channel"]
          2. Für den häufigsten Channel: normalisieren + Spezialkanal-Check
          3. Bei Treffer: kanonischen Namen zurückgeben
        """
        if not entries:
            return None

        special_cfg = load_special_channels_merged(self.config)
        channel_counts: Counter = Counter()

        for entry in entries:
            ch = (entry.get("uploader") or entry.get("channel") or "").strip()
            if ch:
                channel_counts[ch] += 1

        if not channel_counts:
            self.logger.debug("   [CHANNEL-P3] Keine Uploader in Track-Einträgen")
            return None

        self.logger.debug(
            f"   [CHANNEL-P3] Track-Uploader (Top 3): "
            f"{channel_counts.most_common(3)}"
        )

        for track_channel, count in channel_counts.most_common():
            try:
                norm = self.artist_normalizer.normalize(track_channel)
            except Exception:
                norm = track_channel

            ch_info = get_special_channel_info(
                norm, special_cfg
            ) or get_special_channel_info(track_channel, special_cfg)

            if ch_info:
                category, canonical = ch_info
                self.logger.info(
                    f"🎙️ [CHANNEL-P3] Spezialkanal auf Track-Ebene:\n"
                    f"   Roh       : '{track_channel}'\n"
                    f"   Norm.     : '{norm}'\n"
                    f"   Kategorie : {category}\n"
                    f"   Kanonisch : {canonical}\n"
                    f"   Häufigkeit: {count}/{len(entries)} Tracks"
                )
                return canonical

        self.logger.debug("   [CHANNEL-P3] Kein Spezialkanal in Track-Uploadern gefunden")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Entscheidungspfade P1–P5
    # ─────────────────────────────────────────────────────────────────────────

    def _path_playlist_processor_artist(
        self, dominant_artist: Optional[str]
    ) -> Optional[str]:
        """
        P1 – PlaylistProcessor hat bereits einen Artist erkannt.

        Gibt `dominant_artist` unverändert zurück, wenn gesetzt, sonst None.
        """
        if dominant_artist:
            self.logger.info(
                f"✅ [CHANNEL] Pfad P1: PlaylistProcessor hat Artist erkannt → "
                f"'{dominant_artist}' (keine Änderung)"
            )
            return dominant_artist
        return None

    def _path_playlist_channel_special(
        self, channel_raw: str, channel_normalized: str
    ) -> Optional[str]:
        """
        P2 – Playlist-Channel ist ein Spezialkanal.

        Prüft sowohl den normalisierten als auch den rohen Channel-Namen.
        Gibt den kanonischen Namen zurück (oder den normalisierten Namen
        als Fallback, falls kein kanonischer Eintrag existiert), sonst None.
        """
        channel_is_special = self._is_special_channel(
            channel_normalized
        ) or self._is_special_channel(channel_raw)

        if not channel_is_special:
            return None

        special_cfg = load_special_channels_merged(self.config)
        channel_info = get_special_channel_info(
            channel_normalized, special_cfg
        ) or get_special_channel_info(channel_raw, special_cfg)

        if channel_info:
            category, canonical = channel_info
            self.logger.info(
                f"⭐ [CHANNEL] Pfad P2: Playlist-Channel '{channel_raw}' ist Spezialkanal!\n"
                f"   Kategorie  : {category}\n"
                f"   Kanonisch  : {canonical}\n"
                f"   → dominant_artist = '{canonical}'"
            )
            return canonical
        else:
            self.logger.info(
                f"⭐ [CHANNEL] Pfad P2b: Spezialkanal erkannt, aber kein kanonischer Name → "
                f"'{channel_normalized}'"
            )
            return channel_normalized

    def _path_track_level_special(
        self, entries: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        P3 – Track-Level-Uploader ist ein Spezialkanal.

        Delegiert an `find_dominant_special_channel_from_entries()`.
        Das eigentliche Log für "Pfad P3 gefunden" erfolgt in
        `resolve_dominant_artist()`, da dort auch der Playlist-Channel
        für die Log-Nachricht benötigt wird.
        """
        return self.find_dominant_special_channel_from_entries(entries)

    def _path_normalized_channel_fallback(self, channel_raw: str) -> Optional[str]:
        """
        P4 – Normaler Channel als Artist-Fallback.

        Normalisiert `channel_raw` und gibt das Ergebnis zurück, wenn es
        sich um einen gültigen (nicht "unknown"/"unbekannt"/leeren) Namen
        handelt, sonst None.
        """
        try:
            channel_final = self.artist_normalizer.normalize(channel_raw)
            if channel_final and channel_final.lower() not in (
                "unknown",
                "unbekannt",
                "",
            ):
                self.logger.info(
                    f"🎙️ [CHANNEL] Pfad P4: Normaler Channel als Artist-Fallback:\n"
                    f"   Roh          : '{channel_raw}'\n"
                    f"   Normalisiert : '{channel_final}'\n"
                    f"   → dominant_artist = '{channel_final}'"
                )
                return channel_final
        except Exception as e:
            self.logger.warning(f"⚠️ [CHANNEL] Channel-Normalisierung fehlgeschlagen: {e}")

        return None

    def _path_compilation_mode(self, reason: str, path_label: str = "P5") -> None:
        """
        P5 – Compilations-Modus.

        Loggt den Grund, warum kein Artist ermittelt werden konnte.
        `dominant_artist` bleibt None — einzelne Track-Künstler werden
        beibehalten.
        """
        self.logger.info(
            f"🎭 [CHANNEL] Pfad {path_label}: {reason} → Compilations-Modus\n"
            f"   (dominant_artist = None — einzelne Track-Künstler werden beibehalten)"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Private Hilfsmethoden
    # ─────────────────────────────────────────────────────────────────────────

    def _is_special_channel(self, channel_name: str) -> bool:
        """
        Prüft ob `channel_name` ein bekannter Spezialkanal ist.
        Nutzt YAML-Config (bevorzugt) oder Config.SPECIAL_CHANNELS (Fallback).
        Substring-Matching: 'by HighOnTracks' wird korrekt erkannt.
        """
        if not channel_name:
            return False
        special_cfg = load_special_channels_merged(self.config)
        return bool(get_special_category(channel_name, special_cfg))