# services/downloader/download/formatters.py
# -*- coding: utf-8 -*-
"""
ASCII-Formatierungen für Logging und Fortschrittsanzeige.

Verwendet nur ASCII-Zeichen (#, ., -) für maximale Kompatibilität.
"""

from typing import Dict, Any, List, Optional


class ProgressFormatter:
    """Statische Methoden für ASCII-Formatierung (keine Unicode-Zeichen)."""
    
    @staticmethod
    def bar(current: int, total: int, width: int = 12) -> str:
        """
        Liefert ASCII-Fortschrittsbalken: ########.... 8/12
        
        Verwendet nur ASCII-Zeichen: # für gefüllt, . für leer
        """
        filled = round(width * current / max(total, 1))
        bar_str = "#" * filled + "." * (width - filled)
        return f"{bar_str} {current}/{total}"
    
    @staticmethod
    def track_header(idx: int, total: int, title: str, artist: str = "") -> str:
        """Formatiert Track-Header für Playlist-Loop-Logs (ASCII only)."""
        bar = ProgressFormatter.bar(idx, total)
        label = f"'{artist} - {title}'" if artist else f"'{title}'"
        return (
            f"\n[TRACK {idx:02d}/{total:02d} {bar}]\n"
            f"  {label}\n"
            f"{'-' * 60}"
        )
    
    @staticmethod
    def track_result_block(idx: int, result: Dict[str, Any]) -> str:
        """Kompakter Ergebnis-Block nach Track-Verarbeitung (ASCII only)."""
        ok = "[OK]" if result.get("success") else "[FAIL]"
        flags = []
        if result.get("lyrics_available"):
            flags.append("LYRICS")
        if result.get("cover_embedded"):
            flags.append("COVER")
        if result.get("from_cache"):
            flags.append("CACHE")
        if result.get("is_duplicate"):
            flags.append("DUP")
        if result.get("artist_source") == "artist_map_fallback":
            flags.append("ARTIST-MAP")
        if result.get("artist_source") == "youtube_parsed":
            flags.append("YT-PARSER")
        
        flags_str = f" | Flags: {','.join(flags)}" if flags else ""
        
        return (
            f"  {ok} Track {idx:02d}: {result.get('artist','?')} - {result.get('title','?')}\n"
            f"     Artist-Src: {result.get('artist_source','?')}\n"
            f"     Genre-Src : {result.get('genre_source','?')}\n"
            f"     Library   : {result.get('library_path','?')}{flags_str}"
        )
    
    @staticmethod
    def stats_table(session: Dict, final: Dict, cache_hits: int, total: int) -> str:
        """Formatiert Abschluss-Statistik-Tabelle (ASCII only)."""
        ok = session.get("successful_downloads", 0)
        err = session.get("failed_downloads", 0)
        return f"""
[STATS] ========================================
  Total tracks      : {total}
  Successful        : {ok}
  Failed            : {err}
  Cache hits        : {cache_hits}
  Lyrics found      : {session.get('lyrics_found', 0)}
  Duplicates        : {final.get('duplicate_tracks', 0)}
  YT-Parser used    : {final.get('youtube_parser_used', 0)}
  ArtistMap fallback: {session.get('artist_map_fallbacks', 0)}
  Normalizations    : {final.get('successful_normalizations', 0)}
  Genre mappings    : {final.get('successful_genre_mappings', 0)}
================================================"""
    
    @staticmethod
    def playlist_start(playlist_info: Dict[str, Any]) -> str:
        """Playlist-Start Header."""
        return f"""
{'='*60}
PLAYLIST-PIPELINE START
  Title    : {playlist_info.get('title', '?')}
  Uploader : {playlist_info.get('uploader', '?')}
  Tracks   : {len(playlist_info.get('entries', []))}
{'='*60}"""
    
    @staticmethod
    def single_track_header(title: str, artist: str, video_id: str) -> str:
        """Single-Track Header."""
        return f"""
{'-'*60}
SINGLE-TRACK-PIPELINE
  Title    : {title}
  Artist   : {artist}
  Video-ID : {video_id}
{'-'*60}"""
