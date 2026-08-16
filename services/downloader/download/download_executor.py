# services/downloader/download/download_executor.py
# -*- coding: utf-8 -*-
"""
DownloadExecutor – reine yt-dlp-Download-Logik.

Verantwortlichkeit (Single Responsibility):
  - yt-dlp-Optionen zusammenstellen (`build_ydl_opts`)
  - Metadaten-Extraktion (mit/ohne Download) via yt-dlp (`extract_info`)
  - Einzel-Track-Download innerhalb einer Playlist mit einfacher
    Retry-Logik (`download_single_track`)
  - Datei-Suche nach Download (`find_downloaded_file`)

NICHT Verantwortlich für:
  - Haupt-Retry-Logik (bleibt in `enhanced_download_with_retry()`)
  - Metadaten-Anreicherung, Caching, Channel-Routing, Jahr-Bestimmung

Dependency Injection:
  - Keine externen Abhängigkeiten außer `yt_dlp`.
  - Eigene Logger-Instanz via `get_module_logger`.

Log-Marker bleiben unverändert: [YDL-OPTS], [DL], [FILE].
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

import yt_dlp

from logger import get_module_logger


class DownloadExecutor:
    """
    Kapselt alle direkten yt-dlp-Aufrufe: Optionen-Aufbau, Info-Extraktion,
    Einzel-Track-Download (mit einfacher Retry-Logik) und Datei-Suche.
    """

    def __init__(self, logger=None, logger_factory=None):
        self.logger = logger or (logger_factory or get_module_logger)("DownloadExecutor")

    # ─────────────────────────────────────────────────────────────────────────
    # yt-dlp OPTIONEN
    # ─────────────────────────────────────────────────────────────────────────

    def build_ydl_opts(self, config) -> Dict[str, Any]:
        """
        Baut yt-dlp-Optionen zusammen und loggt jede relevante Einstellung.
        """
        opts = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": str(
                getattr(config, "DOWNLOAD_DIR", Path("/tmp")) / "%(title)s.%(ext)s"
            ),
            "writeinfojson": True,
            "writethumbnail": False,
            "embedsubtitles": False,
            "writesubtitles": False,
            "ignoreerrors": False,
            "source_address": "0.0.0.0",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": getattr(config, "AUDIO_FORMAT", "m4a"),
                    "preferredquality": str(getattr(config, "AUDIO_QUALITY", "192")),
                }
            ],
            "postprocessor_args": ["-threads", "4"],
        }

        max_duration = getattr(config, "MAX_DURATION", None)
        if max_duration:
            opts["match_filter"] = self._build_duration_match_filter(
                config, max_duration
            )
            self.logger.debug(
                f"⏱️ [YDL-OPTS] Dauer-Filter aktiv: max. {max_duration}s "
                f"(Podcast-Kanäle ausgenommen)"
            )

        cookie_file = Path("cookies.txt")
        if cookie_file.exists():
            opts["cookiefile"] = str(cookie_file)
            self.logger.info(f"🍪 [YDL-OPTS] Cookie-Datei gefunden: {cookie_file}")
        else:
            self.logger.debug("🍪 [YDL-OPTS] Keine cookies.txt – Download ohne Cookies")

        self.logger.info(
            f"⚙️ [YDL-OPTS] yt-dlp Konfiguration:\n"
            f"   Format   : {opts['format']}\n"
            f"   Codec    : {opts['postprocessors'][0]['preferredcodec']}\n"
            f"   Qualität : {opts['postprocessors'][0]['preferredquality']}kbps\n"
            f"   Ausgabe  : {opts['outtmpl']}\n"
            f"   Cookies  : {'✅ ' + str(cookie_file) if 'cookiefile' in opts else '❌ keine'}"
        )
        return opts

    def _build_duration_match_filter(self, config, max_duration: int):
        """
        Baut einen yt-dlp `match_filter`-Callback, der Videos über
        `max_duration` Sekunden ablehnt - AUSSER der Kanal ist als Podcast
        im Spezialkanal-Mapping hinterlegt (Podcasts sind typischerweise
        deutlich länger als Musik-Tracks und sollen nicht limitiert werden).

        Vorher wurde `Config.MAX_DURATION` nur in der ungenutzten
        `Config.YTDL_BASE_OPTIONS`-Property unter dem Key "max_duration"
        gesetzt - das ist kein echter yt-dlp-Options-Key UND
        `YTDL_BASE_OPTIONS` selbst hat keinerlei Aufrufer im Repo. Die
        tatsächlich verwendeten Optionen kommen ausschließlich aus dieser
        Methode (`build_ydl_opts`), die `max_duration` bisher gar nicht
        kannte - das Limit war also komplett wirkungslos.

        Podcast-Erkennung nutzt dieselbe Quelle wie FilenameFixerTool
        (`load_special_channels_merged`/`get_special_channel_info`), damit
        das Verhalten konsistent mit der restlichen Pipeline bleibt.
        """
        from utils.filenamefixer import (
            get_special_channel_info,
            load_special_channels_merged,
        )

        special_channels = load_special_channels_merged(config)

        def _duration_filter(info_dict, *, incomplete=False):
            duration = info_dict.get("duration")
            if not duration or duration <= max_duration:
                return None

            channel_name = info_dict.get("uploader") or info_dict.get("channel") or ""
            channel_info = get_special_channel_info(channel_name, special_channels)
            if channel_info and channel_info[0].lower() == "podcast":
                return None

            return (
                f"Video zu lang ({duration}s > {max_duration}s MAX_DURATION) "
                f"und kein erkannter Podcast-Kanal"
            )

        return _duration_filter

    # ─────────────────────────────────────────────────────────────────────────
    # INFO-EXTRAKTION (für Haupt-Retry-Loop & Single-Download)
    # ─────────────────────────────────────────────────────────────────────────

    def extract_info(
        self, url: str, ydl_opts: Dict[str, Any], download: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Führt `yt_dlp.YoutubeDL(...).extract_info(url, download=...)` aus.

        Wirft Exceptions unverändert weiter – die Haupt-Retry-Logik
        (inkl. Backoff & Fehlerklassifikation) bleibt in
        `enhanced_download_with_retry()`.

        ACHTUNG: Diese Methode ist synchron/blockierend (yt-dlp macht
        eigene, blockierende Netzwerk-Calls). Aus async-Kontext IMMER
        `extract_info_async()` verwenden, niemals diese Methode direkt
        aufrufen - siehe dort.
        """
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=download)

    async def extract_info_async(
        self, url: str, ydl_opts: Dict[str, Any], download: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Async-Wrapper um extract_info(): fuehrt den blockierenden yt-dlp-
        Aufruf in einem Executor-Thread aus (asyncio.run_in_executor),
        damit der asyncio-Event-Loop waehrend Metadaten-Extraktion/Download
        NICHT blockiert wird.

        Vorher wurde extract_info() direkt aus async-Funktionen aufgerufen -
        das blockierte den kompletten Event-Loop fuer die gesamte Dauer
        jedes Downloads, wodurch der Bot fuer ALLE Nutzer (nicht nur den
        gerade downloadenden) unresponsive wurde, bis der Aufruf fertig war.
        Mirrort das bereits korrekte Muster aus spotify_downloader.py.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.extract_info(url, ydl_opts, download)
        )

    # ─────────────────────────────────────────────────────────────────────────
    # EINZEL-TRACK-DOWNLOAD (Playlist-Kontext, mit einfacher Retry-Logik)
    # ─────────────────────────────────────────────────────────────────────────

    async def download_single_track(
        self,
        track_info: Dict[str, Any],
        ydl_opts: Dict[str, Any],
        track_idx: int,
        download_dir: Path,
        max_retries: int = 1,
        retry_backoff_seconds: float = 2.0,
    ) -> Optional[str]:
        """
        Lädt einen einzelnen Track via yt-dlp herunter.

        Einfache (nicht-Haupt-)Retry-Logik: bei `max_retries > 1` wird
        der Download bis zu `max_retries`-mal versucht, mit linearem
        Backoff (`retry_backoff_seconds * versuch`). Standardmäßig
        (`max_retries=1`) entspricht das Verhalten exakt der bisherigen
        Implementierung (kein Retry).

        Loggt: URL, Ziel-Template, Versuch, Ergebnis-Pfad.
        Gibt den Dateipfad zurück oder None bei endgültigem Fehlschlag.
        """
        track_url = track_info.get("webpage_url") or track_info.get("url")
        if not track_url:
            self.logger.warning(
                f"⚠️ [DL] Track {track_idx:02d}: Keine URL gefunden\n"
                f"   track_info-Keys: {list(track_info.keys())}"
            )
            return None

        track_ydl_opts = ydl_opts.copy()
        outtmpl = str(
            download_dir / f"Track_{track_idx:02d}_{track_info.get('id', 'temp')}.%(ext)s"
        )
        track_ydl_opts["outtmpl"] = outtmpl

        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            attempt_label = (
                f" (Versuch {attempt}/{max_retries})" if max_retries > 1 else ""
            )
            self.logger.info(
                f"⬇️  [DL] Track {track_idx:02d}: Starte Download{attempt_label}\n"
                f"   URL      : {track_url[:80]}\n"
                f"   Template : {outtmpl}"
            )

            try:
                def _do_download() -> Optional[Dict[str, Any]]:
                    with yt_dlp.YoutubeDL(track_ydl_opts) as ydl:
                        return ydl.extract_info(track_url, download=True)

                # run_in_executor statt direktem Aufruf - blockiert sonst
                # den Event-Loop fuer die gesamte Download-Dauer (siehe
                # extract_info_async()-Docstring).
                download_info = await asyncio.get_running_loop().run_in_executor(
                    None, _do_download
                )

                downloaded_file = self.find_downloaded_file(download_info, track_ydl_opts)

                if not downloaded_file or not Path(downloaded_file).exists():
                    raise FileNotFoundError(
                        f"Datei nach Download nicht auffindbar (Track {track_idx:02d})"
                    )

                size_kb = Path(downloaded_file).stat().st_size // 1024
                self.logger.info(
                    f"✅ [DL] Track {track_idx:02d}: Download erfolgreich\n"
                    f"   Datei : {Path(downloaded_file).name}\n"
                    f"   Größe : {size_kb} KB"
                )
                return downloaded_file

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    wait = retry_backoff_seconds * attempt
                    self.logger.warning(
                        f"⚠️ [DL] Track {track_idx:02d}: Download-Fehler (Versuch {attempt}/{max_retries})\n"
                        f"   Typ    : {type(e).__name__}\n"
                        f"   Fehler : {e}\n"
                        f"   → Warte {wait:.0f}s, dann erneuter Versuch"
                    )
                    await asyncio.sleep(wait)
                else:
                    self.logger.error(
                        f"💥 [DL] Track {track_idx:02d}: Download-Fehler\n"
                        f"   Typ    : {type(e).__name__}\n"
                        f"   Fehler : {e}"
                    )

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # DATEI-SUCHE NACH DOWNLOAD
    # ─────────────────────────────────────────────────────────────────────────

    def find_downloaded_file(
        self,
        download_info: Dict[str, Any],
        ydl_opts: Dict[str, Any],
    ) -> Optional[str]:
        """
        Findet die heruntergeladene Datei über 2 Strategien:
          1. download_info["requested_downloads"][0]["filepath"]  (direkter yt-dlp-Pfad)
          2. Template-Rekonstruktion aus ydl_opts["outtmpl"]

        Loggt welche Strategie erfolgreich war.
        """
        # Strategie 1: requested_downloads
        try:
            filepath = download_info.get("requested_downloads", [{}])[0].get("filepath")
            if filepath and Path(filepath).exists():
                self.logger.debug(
                    f"📂 [FILE] Strategie 1 erfolgreich (requested_downloads):\n"
                    f"   {filepath}"
                )
                return filepath
            elif filepath:
                self.logger.debug(
                    f"📂 [FILE] Strategie 1: Pfad gefunden, aber Datei fehlt: {filepath}"
                )
        except (IndexError, AttributeError):
            pass

        # Strategie 2: Template-Rekonstruktion
        outtmpl = ydl_opts.get("outtmpl", "")
        if outtmpl:
            potential = (
                outtmpl.replace("%(ext)s", download_info.get("ext", "m4a"))
                .replace("%(id)s", download_info.get("id", ""))
                .replace("%(title)s", download_info.get("title", ""))
            )
            if Path(potential).exists():
                self.logger.debug(
                    f"📂 [FILE] Strategie 2 erfolgreich (Template-Rekonstruktion):\n"
                    f"   {potential}"
                )
                return potential
            else:
                self.logger.debug(
                    f"📂 [FILE] Strategie 2: Rekonstruierter Pfad existiert nicht:\n"
                    f"   Template  : {outtmpl}\n"
                    f"   Ergebnis  : {potential}"
                )

        self.logger.warning(
            f"⚠️ [FILE] Datei nicht gefunden – beide Strategien fehlgeschlagen\n"
            f"   Titel   : {download_info.get('title', '?')}\n"
            f"   ext     : {download_info.get('ext', '?')}\n"
            f"   id      : {download_info.get('id', '?')}"
        )
        return None