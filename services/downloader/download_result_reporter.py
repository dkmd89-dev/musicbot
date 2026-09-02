# services/downloader/download_result_reporter.py
# -*- coding: utf-8 -*-

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from services.downloader.models import DuplicateEntry
from logger import get_module_logger


def _format_duration(seconds) -> str:
    """"⏱️ Dauer"-Zeile: formatiert Sekunden als "M:SS min". Fehlt der Wert
    (z.B. bei einem noch nicht ueberall durchgereichten Aufrufer), wird
    "N/A" statt eines falschen Platzhalters gezeigt."""
    if seconds is None:
        return "N/A"
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "N/A"
    minutes, secs = divmod(max(total, 0), 60)
    return f"{minutes}:{secs:02d} min"


def _example_track_and_short_dir(library_path) -> tuple:
    """
    Nutzer-Wunsch 2026-09-02: "Speicherort" zeigt nur noch "Artist/Album"
    (bzw. "Artist/Singles") statt des vollen Dateisystempfads
    (z.B. "/tmp/musicbot_test/library/..." in der Testumgebung, in Produktion
    "/mnt/musik_bilder/library/..."). Bewusst ueber die letzten zwei
    Pfadsegmente relativ zur Datei bestimmt (Artist-Ordner + Album-/Singles-
    Ordner) statt eine Library-Root-Config zu importieren - funktioniert
    dadurch identisch in Test- und Produktionsumgebung, ohne dass dieses
    reine Formatierungsmodul eine Config-Abhaengigkeit braucht.
    """
    if not library_path:
        return "N/A", "N/A"
    lp = Path(library_path)
    album_dir = lp.parent
    short_dir = f"{album_dir.parent.name}/{album_dir.name}" if album_dir.parent.name else album_dir.name
    return lp.name, short_dir


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

        Nutzer-Redesign 2026-09-02: gleiches Format wie
        build_final_summary_message() (siehe dortiger Docstring) -
        "Lyrics"/"Loudness" kommen bewusst direkt aus `successful`, nicht
        aus einem geteilten, nie zurückgesetzten Processor-Zähler.
        """
        first  = successful[0]
        artist = first.get("artist", "Unbekannt")
        album  = first.get("album", "Unbekannt")
        year   = str(first.get("year", "")) or "N/A"
        genres = self.collect_playlist_genres(successful)
        lib    = successful[-1].get("library_path", "")
        duration = _format_duration(successful[-1].get("duration_seconds"))

        n  = max(len(successful), 1)
        lf = sum(1 for t in successful if t.get("lyrics_available"))
        ln = sum(1 for t in successful if t.get("loudness_normalized"))
        cover_ok = any(t.get("cover_embedded") for t in successful)
        lyrics_ok = lf > 0
        loud_ok = ln > 0

        def stat_pct(count: int, total: int) -> str:
            return f"{int(count / max(total, 1) * 100)}%"

        genre_lines = [f"• {g}" for g in genres] if genres else ["• Keine"]
        genre_str   = "\n".join(genre_lines)

        fname, fdir_short = _example_track_and_short_dir(lib)

        msg = (
            "🎉 Download erfolgreich abgeschlossen!\n\n"
            f"🎤 Künstler : {artist}\n"
            f"💿 Album    : {album}\n"
            f"📅 Jahr     : {year}\n"
            f"🎵 Tracks   : {len(successful)}/{len(results)} erfolgreich\n"
            "📡 Quelle   : 📺 YouTube\n"
            f"⏱️ Dauer    : {duration}\n\n"
            f"🏷️ Genres\n{genre_str}\n\n"
            "✨ Ergebnis\n"
            f"🖼️ Cover    : {'✅ eingebettet' if cover_ok else '❌ fehlt'}\n"
            f"📜 Lyrics   : {'✅ verfügbar' if lyrics_ok else '❌ fehlt'} ({lf}/{n} · {stat_pct(lf, n)})\n"
            f"🔊 Loudness : {'✅ normalisiert' if loud_ok else '❌ fehlt'} ({ln}/{n} · {stat_pct(ln, n)})\n\n"
            "🎵 Beispiel-Track\n"
            f"`{fname}`\n\n"
            "📂 Speicherort\n"
            f"`{fdir_short}`"
        )
        return msg

    def build_final_summary_message(
        self,
        result: Dict[str, Any],
        processing_stats: Dict[str, Any],
        duplicate_stats: Dict[str, Any],
    ) -> str:
        """
        Baut die vollständige Abschluss-Zusammenfassung.

        Nutzer-Redesign 2026-09-02: liest "Lyrics gefunden"/"Loudness
        normalisiert" bewusst NICHT aus `processing_stats` (Parameter, aus
        `EnhancedMetadataProcessor.processing_stats` - ein Instanzattribut,
        das seit Bot-Start akkumuliert und nie zurückgesetzt wird,
        `reset_statistics()` existiert, wird aber nirgends aufgerufen).
        Stattdessen werden beide Werte direkt aus den Tracks/dem Ergebnis
        DIESES Downloads berechnet - dadurch ist die Meldung immer nur für
        den gerade abgeschlossenen Download aktuell, unabhängig vom
        Lebenszyklus des geteilten Processors (der für andere Konsumenten,
        z.B. eine künftige Bot-Statusanzeige, bewusst kumulativ bleiben
        darf).
        """
        self.logger.info("📝 [SUMMARY] Erstelle Abschluss-Zusammenfassung...")

        PLACEHOLDER = {None, "", "Unbekannt", "Unknown", "Unknown Artist", "Playlist"}

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

        # Genres filtern
        raw_genres = self.collect_playlist_genres(tracks) if is_pl and tracks else self.extract_genres_from_data(result.get("genres"))

        # "Verarbeitung"-Zeilen: ausschließlich aus den Tracks/dem Ergebnis
        # DIESES Downloads, siehe Docstring oben.
        if is_pl and tracks:
            n  = len(tracks)
            lf = sum(1 for t in tracks if t.get("lyrics_available"))
            ln = sum(1 for t in tracks if t.get("loudness_normalized"))
        else:
            n  = 1
            lf = 1 if result.get("lyrics_available") else 0
            ln = 1 if result.get("loudness_normalized") else 0

        def stat_pct(count: int, total: int) -> str:
            return f"{int(count / max(total, 1) * 100)}%"

        # Pfad
        # Live-Fund 2026-09-02 (Abbruch-Test): bei einem per ❌ abgebrochenen
        # Playlist-Download ist der LETZTE Eintrag in tracks oft der
        # abgebrochene/fehlgeschlagene Track selbst (kein library_path) -
        # ein simples tracks[-1] zeigte dadurch faelschlich "N/A" als
        # Beispiel-Track, obwohl vorherige Tracks erfolgreich waren. Sucht
        # stattdessen rueckwaerts den letzten Track MIT tatsaechlichem
        # library_path.
        if is_pl:
            lib_path = next(
                (t.get("library_path") for t in reversed(tracks) if t.get("library_path")),
                None,
            )
        else:
            lib_path = result.get("library_path")
        if not lib_path:
            self.logger.warning("⚠️ [SUMMARY] library_path fehlt im Ergebnis")
        fname, fdir_short = _example_track_and_short_dir(lib_path)

        duration = _format_duration(result.get("duration_seconds"))

        # Ergebnis-Flags (mind. ein Track hat's, wie bisher bei "any")
        if is_pl and tracks:
            lyrics_ok = any(t.get("lyrics_available") for t in tracks)
            cover_ok  = any(t.get("cover_embedded") for t in tracks)
            loud_ok   = any(t.get("loudness_normalized") for t in tracks)
        else:
            lyrics_ok = bool(result.get("lyrics_available")) or lf > 0
            cover_ok  = bool(result.get("cover_embedded"))
            loud_ok   = bool(result.get("loudness_normalized"))

        src_label = "📺 YouTube"

        genre_lines = [f"• {g}" for g in raw_genres] if raw_genres else ["• Keine"]

        # Nutzer-Wunsch 2026-09-02: bei Einzeltiteln (n=1) ist der Zaehler/
        # die Prozentangabe hinter Lyrics/Loudness (immer "1/1 · 100%" bzw.
        # "0/1 · 0%") reine Redundanz zum bereits gezeigten ✅/❌-Status -
        # nur bei Playlists (n > 1, echter Anteil) bleibt sie sinnvoll und
        # wird weiterhin angezeigt.
        if is_pl:
            lyrics_line = f"📜 Lyrics   : {'✅ verfügbar' if lyrics_ok else '❌ fehlt'} ({lf}/{n} · {stat_pct(lf, n)})"
            loud_line = f"🔊 Loudness : {'✅ normalisiert' if loud_ok else '❌ fehlt'} ({ln}/{n} · {stat_pct(ln, n)})"
        else:
            lyrics_line = f"📜 Lyrics   : {'✅ verfügbar' if lyrics_ok else '❌ fehlt'}"
            loud_line = f"🔊 Loudness : {'✅ normalisiert' if loud_ok else '❌ fehlt'}"

        # Download-Control-Center 2026-09-02: ein per ❌-Button abgebrochener
        # Playlist-Download hat weiterhin result["success"] == True (die
        # bereits VOR dem Abbruch fertig heruntergeladenen Tracks sind
        # echte Erfolge, siehe _process_playlist_download()) - der Header/
        # die Tracks-Zeile machen die Teil-Fertigstellung trotzdem sichtbar,
        # statt einen vollen Erfolg vorzutaeuschen.
        was_cancelled = bool(result.get("cancelled"))
        header = (
            "🛑 Download abgebrochen"
            if was_cancelled
            else "🎉 Download erfolgreich abgeschlossen!"
        )
        meta = []
        if not is_pl:
            meta.append(f"🎵 Titel    : {title}")
        meta += [
            f"🎤 Künstler : {artist}",
            f"💿 Album    : {album}",
            f"📅 Jahr     : {year}",
        ]
        if is_pl:
            ok = sum(1 for t in tracks if t.get("success"))
            tracks_label = "abgebrochen bei" if was_cancelled else "erfolgreich"
            meta.append(f"🎵 Tracks   : {ok}/{len(tracks)} {tracks_label}")
        meta.append(f"📡 Quelle   : {src_label}")
        meta.append(f"⏱️ Dauer    : {duration}")

        example_label = "🎵 Beispiel-Track" if is_pl else "🎵 Datei"

        lines = (
            [header, ""]
            + meta
            + ["", "🏷️ Genres"]
            + genre_lines
            + [
                "",
                "✨ Ergebnis",
                f"🖼️ Cover    : {'✅ eingebettet' if cover_ok else '❌ fehlt'}",
                lyrics_line,
                loud_line,
                "",
                example_label,
                f"`{fname}`",
                "",
                "📂 Speicherort",
                f"`{fdir_short}`",
            ]
        )

        final_msg = "\n".join(lines)
        self.logger.info(f"📝 [SUMMARY] Zusammenfassung:\n{final_msg}")

        return final_msg
