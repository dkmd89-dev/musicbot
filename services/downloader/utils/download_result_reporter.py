# services/downloader/utils/download_result_reporter.py
# -*- coding: utf-8 -*-

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from handlers.duplicate_handler import DuplicateEntry
from logger import get_module_logger


class DownloadResultReporter:
    """
    Verantwortlich für das Formatieren von Download-Abschluss-Nachrichten
    (Duplikat-Meldung, Playlist-Zusammenfassung, finale Zusammenfassung)
    sowie die zugehörige Genre-/Stats-Aufbereitung aus Download-Ergebnis-
    Dicts. Gibt ausschließlich fertigen Text zurück - der tatsächliche
    Telegram-Versand (inkl. status_msg/update-Fallback und TelegramError-
    Behandlung) ist Aufgabe von `DownloadHandler` (ARCH-007/P-2: services/
    hat keine Telegram-Abhängigkeit mehr). Enthält bewusst keine
    Duplikat-Cache- oder sonstige Seiteneffekt-Logik — auch das bleibt
    Aufgabe von `DownloadHandler`.
    """

    def __init__(self, logger=None):
        self.logger = logger or get_module_logger("DownloadResultReporter")

    # ─────────────────────────────────────────────────────────────────────────
    # Genre-/Stats-Aufbereitung
    # ─────────────────────────────────────────────────────────────────────────

    def extract_genres_from_data(self, genres_data) -> List[str]:
        """Normalisiert Genre-Daten aus allen vorkommenden Formaten."""
        result: List[str] = []
        if isinstance(genres_data, dict):
            p = genres_data.get("primary")
            if isinstance(p, str) and p:
                result.append(p)
            sec = genres_data.get("secondary")
            if isinstance(sec, list):
                result.extend(g for g in sec if isinstance(g, str))
        elif isinstance(genres_data, list):
            for item in genres_data:
                if isinstance(item, str):
                    result.append(item)
                elif isinstance(item, dict):
                    p = item.get("primary")
                    if isinstance(p, str) and p:
                        result.append(p)
        elif isinstance(genres_data, str) and genres_data:
            result.append(genres_data)
        seen: set = set()
        return [g for g in result if g not in seen and not seen.add(g)]  # type: ignore

    def collect_playlist_genres(self, tracks: List[dict]) -> List[str]:
        """Sammelt Genres aus allen Tracks, sortiert nach Häufigkeit (max. 4)."""
        counter: Counter = Counter()
        for track in tracks:
            for g in self.extract_genres_from_data(track.get("genres")):
                counter[g] += 1
        return [g for g, _ in counter.most_common(4)]

    def extract_stats_from_result(self, result: dict, tracks: List[dict]) -> dict:
        """
        Stats aus 3 unabhängigen Quellen (Robustheit):
          1. result['processing_stats']
          2. processor_instance.get_processing_statistics()
          3. Aggregation aus Track-Flags
        """
        stats = result.get("processing_stats")
        if stats and isinstance(stats, dict) and any(stats.values()):
            return stats

        proc = result.get("processor_instance") or result.get("_enhanced_processor_ref")
        if proc:
            try:
                mp = getattr(proc, "enhanced_metadata_processor", None) or proc
                raw = mp.get_processing_statistics() if callable(getattr(mp, "get_processing_statistics", None)) else {}
                session = getattr(proc, "session_stats", {})
                merged = {**raw, **{k: v for k, v in session.items() if k not in raw}}
                if any(merged.values()):
                    return merged
            except Exception:
                pass

        if tracks:
            ch = sum(1 for t in tracks if t.get("from_cache"))
            return {
                "successful_normalizations": sum(1 for t in tracks if t.get("artist_source") not in (None, "unknown")),
                "successful_genre_mappings": sum(1 for t in tracks if self.extract_genres_from_data(t.get("genres"))),
                "lyrics_found":              sum(1 for t in tracks if t.get("lyrics_available")),
                "youtube_parser_used":       sum(1 for t in tracks if t.get("artist_source") == "youtube_parsed"),
                "artist_map_parsing_fallback":sum(1 for t in tracks if t.get("artist_source") == "artist_map_fallback"),
                "cache_hits":   ch,
                "cache_misses": len(tracks) - ch,
                "total_processed": len(tracks),
            }
        return {}

    # ─────────────────────────────────────────────────────────────────────────
    # Nachrichten-Formatierung
    # ─────────────────────────────────────────────────────────────────────────

    def build_duplicate_message(self, entry: DuplicateEntry, dup_type: str) -> str:
        type_map = {
            "url":            ("🔗 URL-Treffer",       "📅 Erstmals heruntergeladen:"),
            "content":        ("🎵 Inhalts-Treffer",    "📅 Erstmals heruntergeladen:"),
            "parsed_content": ("🔍 Parser-Treffer",     "📅 Erstmals heruntergeladen:"),
            "file_conflict":  ("📄 Datei-Konflikt",     "🕒 Konflikt erkannt:"),
        }
        label, date_lbl = type_map.get(dup_type, ("🔍 Unbekannt", "📅 Datum:"))
        return (
            "📄 DUPLIKAT ERKANNT – DOWNLOAD ABGEBROCHEN\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Erkennungstyp : {label}\n\n"
            f"🎵 Titel      : {entry.title}\n"
            f"🎤 Künstler   : {entry.artist}\n"
            f"{date_lbl} {entry.download_date.strftime('%d.%m.%Y %H:%M')}\n"
            f"📂 Pfad       : {str(entry.file_path).replace(' (1)', '')}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Nachrichten-Aufbau (kein Versand mehr - siehe Klassen-Docstring)
    # ─────────────────────────────────────────────────────────────────────────

    def build_playlist_summary_message(
        self, results: List[dict], successful: List[dict]
    ) -> str:
        """
        Abschluss-Meldung für eine "echte" Playlist (nicht der Single-Track-
        Wrapper-Fall, der stattdessen über build_final_summary_message läuft).
        """
        first  = successful[0]
        artist = first.get("artist", "Unbekannt")
        album  = first.get("album", "Unbekannt")
        year   = str(first.get("year", "")) or "N/A"
        genres = self.collect_playlist_genres(successful)
        stats  = self.extract_stats_from_result({"tracks": successful}, successful)
        lib    = successful[-1].get("library_path", "")

        n  = max(len(successful), 1)
        an = stats.get("successful_normalizations", 0)
        gm = stats.get("successful_genre_mappings", 0)
        lf = stats.get("lyrics_found", 0)
        ch = stats.get("cache_hits", 0)
        ct = ch + stats.get("cache_misses", 0)

        def pct(p, w): return f"{int(p / max(w,1) * 100)}%"

        genre_str = "\n".join(f"   • {g}" for g in genres) if genres else "   • Keine"
        folder    = str(Path(lib).parent) if lib else "N/A"

        msg = (
            "✅ Playlist erfolgreich heruntergeladen!\n\n"
            f"🎤 Künstler : {artist}\n"
            f"💿 Album    : {album}\n"
            f"📅 Jahr     : {year}\n"
            f"🎵 Tracks   : {len(successful)}/{len(results)}\n\n"
            f"🏷️ Genres:\n{genre_str}\n\n"
            "🚀 Processing-Statistiken:\n"
            f"   ✨ Normalisierungen : {an}/{n} ({pct(an,n)})\n"
            f"   🏷️ Genre-Mappings   : {gm}/{n} ({pct(gm,n)})\n"
            f"   📜 Lyrics gefunden  : {lf}/{n} ({pct(lf,n)})\n"
            f"   💾 Cache-Treffer    : {ch}/{ct} ({pct(ch,ct)})\n\n"
            f"📂 Bibliothek: {folder}"
        )
        return msg

    def build_final_summary_message(
        self,
        result: Dict[str, Any],
        processing_stats: Dict[str, Any],
        duplicate_stats: Dict[str, Any],
    ) -> str:
        """Baut die vollständige Abschluss-Zusammenfassung."""
        self.logger.info("📝 [SUMMARY] Erstelle Abschluss-Zusammenfassung...")

        PLACEHOLDER = {None, "", "Unbekannt", "Unknown", "Unknown Artist", "Playlist"}

        def pct(p, w): return f"{int(p / max(int(w), 1) * 100)}%"

        tracks = result.get("tracks", [])
        is_pl  = result.get("type") == "playlist"

        # Metadaten
        title  = result.get("playlist_title") or result.get("title", "Unbekannter Titel")
        artist = result.get("playlist_artist") or result.get("artist", "Unbekannt")
        album  = result.get("playlist_album") or result.get("album", title)
        year_v = result.get("playlist_year") or result.get("year")

        if is_pl and tracks:
            ft = tracks[0]
            if artist in PLACEHOLDER: artist = ft.get("artist", "Unbekannt")
            if not album or album in PLACEHOLDER: album = ft.get("album", "Unbekannt")
            if not year_v: year_v = ft.get("year")
            if not title or title in PLACEHOLDER: title = album

        year = str(year_v) if year_v else "N/A"

        # Quelle
        source     = result.get("source", "")
        is_spotify = "spotify" in source.lower() if source else False
        is_podcast = result.get("is_podcast", False)

        # Genres filtern
        raw_genres = self.collect_playlist_genres(tracks) if is_pl and tracks else self.extract_genres_from_data(result.get("genres"))
        if is_spotify and is_podcast:
            raw_genres = [g for g in raw_genres if g.lower() not in {"german", "hip-hop", "hip hop", "deutsch"}]

        # Stats
        eff = dict(processing_stats) if processing_stats else {}
        if not any(eff.values()):
            eff = self.extract_stats_from_result(result, tracks)

        n   = len(tracks) if (is_pl and tracks) else max(eff.get("total_processed", 1), 1)
        an  = eff.get("successful_normalizations", 0)
        gm  = eff.get("successful_genre_mappings", 0)
        lf  = eff.get("lyrics_found", 0)
        yp  = eff.get("youtube_parser_used", 0)
        amf = eff.get("artist_map_parsing_fallback", 0)
        ch  = eff.get("cache_hits", 0)
        ct  = ch + eff.get("cache_misses", 0)

        # Sinnvolle Minimal-Stats wenn alles 0
        if an == 0 and gm == 0 and n == 1:
            if artist and artist not in PLACEHOLDER: an = 1
            if raw_genres: gm = 1

        # Pfad
        lib_path = result.get("library_path") if not is_pl else (tracks[-1].get("library_path") if tracks else None)
        if lib_path:
            lp = Path(lib_path)
            fname = lp.name
            fdir  = str(lp.parent)
        else:
            self.logger.warning("⚠️ [SUMMARY] library_path fehlt im Ergebnis")
            fname = "N/A"
            fdir  = "N/A"

        # Lyrics / Cover
        if is_pl and tracks:
            lyrics_ok = any(t.get("lyrics_available") for t in tracks)
            cover_ok  = any(t.get("cover_embedded") for t in tracks)
        else:
            lyrics_ok = result.get("lyrics_available", False) or lf > 0
            cover_ok  = bool(result.get("cover_embedded"))

        # Quelle-Label
        if is_spotify:
            src_label = "🎙️ Spotify Podcast" if is_podcast else "🎵 Spotify"
        else:
            src_label = "📺 YouTube"

        genre_lines = [f"   • {g}" for g in raw_genres] if raw_genres else ["   • Keine"]

        # Nachricht
        if is_pl:
            ok = sum(1 for t in tracks if t.get("success"))
            header = "✅ Playlist erfolgreich heruntergeladen!"
            meta   = [
                f"🎤 Künstler : {artist}",
                f"💿 Album    : {album}",
                f"📅 Jahr     : {year}",
                f"🎵 Tracks   : {ok}/{len(tracks)}",
                f"📡 Quelle   : {src_label}",
            ]
        else:
            header = "✅ Download erfolgreich!"
            meta   = [
                f"🎵 Titel    : {title}",
                f"🎤 Künstler : {artist}",
                f"💿 Album    : {album}",
                f"📅 Jahr     : {year}",
                f"📡 Quelle   : {src_label}",
            ]

        stats_lines = [
            "",
            "🚀 Processing-Statistiken:",
            f"   ✨ Normalisierungen  : {an}/{n} ({pct(an,n)})",
            f"   🏷️ Genre-Mappings    : {gm}/{n} ({pct(gm,n)})",
            f"   📜 Lyrics gefunden   : {lf}/{n} ({pct(lf,n)})",
        ]
        if not is_spotify:
            stats_lines += [
                f"   📺 YouTube-Parser    : {yp}/{n} ({pct(yp,n)})",
                f"   🎯 Artist-Map-Fbk    : {amf}/{n} ({pct(amf,n)})",
            ]
        stats_lines.append(f"   💾 Cache-Trefferquote: {ch}/{ct} ({pct(ch,ct)})")

        lines = (
            [header, ""]
            + meta
            + ["", "🏷️ Genres:"]
            + genre_lines
            + stats_lines
            + [
                "",
                f"🖼️ Cover eingebettet : {'✅ Ja' if cover_ok else '❌ Nein'}",
                f"📜 Lyrics verfügbar  : {'✅ Ja' if lyrics_ok else '❌ Nein'}",
                f"📄 Datei : {fname}",
                f"📍 Pfad  : {fdir}",
            ]
        )

        final_msg = "\n".join(lines)
        self.logger.info(f"📝 [SUMMARY] Zusammenfassung:\n{final_msg}")

        return final_msg
