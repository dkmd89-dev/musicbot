# services/downloader/download_utils.py
# -*- coding: utf-8 -*-
"""
download_utils.py v5.0 – Orchestrierung der Download-Pipeline

Architektur-Übersicht (nach Refactoring Phase 1–7):
  enhanced_download_with_retry()          → Haupt-Einstiegspunkt mit Retry
    ├── _process_playlist_download()      → Playlist-Pipeline (Orchestrierung)
    │     ├── ChannelRouter               → Artist/Channel-Routing (P1–P5)
    │     ├── YearResolver                → Jahr-Bestimmung aus 4 Quellen
    │     ├── CacheManager                → 2-stufiger Cache-Lookup
    │     ├── DownloadExecutor            → yt-dlp Audio-Download
    │     ├── _process_track_metadata()   → Metadaten-Orchestrierung
    │     └── ProgressFormatter           → Logging-Formatierung
    └── _process_single_download()        → Single-Track-Pipeline

Diese Datei enthält NUR noch Orchestrierung:
  - `EnhancedDownloadProcessor` initialisiert & injiziert alle Komponenten
  - `enhanced_download_with_retry()` koordiniert den Haupt-Retry-Flow
  - `_process_playlist_download()` / `_process_single_download()` /
    `_process_track_metadata()` rufen die spezialisierten Module auf

Ausgelagerte Module (services/downloader/download/):
  models.py            – DownloadResult, PlaylistResult
  interfaces.py        – CacheProvider, MetadataEnricher, DownloadCoordinator
  cache_manager.py     – CacheManager (2-stufiger Cache-Lookup)
  year_resolver.py     – YearResolver (Jahr-Bestimmung)
  channel_router.py    – ChannelRouter (5-Pfad Artist/Channel-Routing)
  download_executor.py – DownloadExecutor (yt-dlp Wrapper)
  formatters.py        – ProgressFormatter (ASCII-Logging)

Log-Konventionen (unverändert über alle Phasen):
  [RETRY X/N]    – Download-Versuch
  [PL-ANALYSE]   – Playlist-Metadaten-Analyse
  [CHANNEL]      – Artist/Channel-Routing-Entscheidung (P1–P5)
  [YEAR]         – Jahr-Bestimmung
  [TRACK XX/NN]  – Einzel-Track innerhalb Playlist
  [CACHE]        – Cache-Lookup-Entscheidung (Stufe 1/2)
  [DL]           – yt-dlp Download
  [META]         – Metadaten-Verarbeitung
  [STATS]        – Abschluss-Statistiken
"""

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from yt_dlp.utils import GeoRestrictedError, UnsupportedError, YoutubeDLError

from config import Config
from utils.singleton import SingletonMixin
from logger import get_module_logger
from services.metadata.enhanced_metadata_processor import (
    EnhancedMetadataProcessor as MetadataProcessorCore,
)
from services.metadata.models import MetadataResult
from .download_artifact_cleanup import cleanup_single_download_artifact
from .errors import (
    DownloadCancelledError,
    DownloadError,
    FormatNotAvailableError,
    InvalidURLError,
    MetadataError,
    PermissionError as DownloadPermissionError,
)
from .metadata_result_translator import (
    build_playlist_track_result,
    build_single_track_result,
    call_process_single_track,
)
from .progress_tracker import ProgressTracker
from services.downloader.playlist_processor import PlaylistProcessor
from utils.artist_map import ArtistConfig, ArtistNormalizer
from utils.filenamefixer import FilenameFixerTool
from utils.metadata_cache import MetadataCache

# ── Ausgelagerte Orchestrierungs-Module (Phase 1–6) ──────────────────────────
from services.downloader.download.models import DownloadResult, PlaylistResult
from services.downloader.download.interfaces import CacheProvider, MetadataEnricher
from services.downloader.download.cache_manager import CacheManager
from services.downloader.download.year_resolver import YearResolver
from services.downloader.download.channel_router import ChannelRouter
from services.downloader.download.download_executor import DownloadExecutor
from services.downloader.download.formatters import ProgressFormatter


# ═══════════════════════════════════════════════════════════════════════════════
# URL-ERKENNUNG: YouTube-Mix-/Radio-Pseudo-Playlists
# ═══════════════════════════════════════════════════════════════════════════════

# DUP-06 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md): yt-dlp
# behandelt jede URL mit list=... (echte Playlist "PL..." UND automatisch
# generierte Mix-/Radio-Liste "RD...") ueber denselben Playlist-faehigen
# Extractor (YoutubeTabIE) - ohne noplaylist=True entsteht in beiden Faellen
# ein entries-tragendes Ergebnis (verifiziert gegen den installierten
# yt-dlp-Quellcode: extractor/youtube/_base.py::_PLAYLIST_ID_RE listet "RD"
# als eigenes, von "PL" unterschiedenes Praefix; extractor/common.py::
# _yes_playlist() liest genau den noplaylist-Parameter). Gemeinsam genutzt
# von enhanced_download_with_retry() (dieses Modul) und
# klassen/download_handler.py::_probe_artist_title_for_duplicate_check() -
# eine einzige Erkennungsfunktion, damit beide Stellen niemals auseinanderlaufen.
_YOUTUBE_MIX_LIST_ID_PREFIX = "RD"


def is_youtube_mix_url(url: str) -> bool:
    """True, wenn die URL einen list=-Query-Parameter besitzt, dessen Wert
    mit "RD" beginnt (yt-dlps Praefix fuer automatisch generierte Mix-/
    Radio-Listen). Bewusst case-sensitiv, wie yt-dlps eigene Konvention.
    Echte Playlists ("list=PL...") liefern bewusst False."""
    try:
        list_values = parse_qs(urlparse(url.strip()).query).get("list", [])
    except Exception:
        return False
    return bool(list_values) and list_values[0].startswith(_YOUTUBE_MIX_LIST_ID_PREFIX)


# ═══════════════════════════════════════════════════════════════════════════════
# DL-03/DL-05 (docs/audits/DL_RETRY_CLASSIFICATION_2026-09-01.md): Fehler-
# klassifikation fuer Retry-Entscheidungen
# ═══════════════════════════════════════════════════════════════════════════════
#
# Vorher wurden ALLE Fehler in enhanced_download_with_retry() identisch
# behandelt (DownloadError/Exception -> immer bis zu max_retries-mal erneut
# versucht, inkl. komplettem Neu-Download von YouTube) - auch fuer Fehler,
# die garantiert bei jedem weiteren Versuch identisch wieder auftreten
# (privates/geloeschtes/altersbeschraenktes Video, nicht unterstuetzte URL,
# ein deterministischer Bug in der Metadaten-Pipeline). Das war reine
# Ressourcenverschwendung ohne Aussicht auf Erfolg (DL-03/DL-05).
#
# _NON_RETRYABLE_ERROR_TYPES listet die bereits bestehenden
# services/downloader/errors.py-Klassen, die laut ihrer eigenen Semantik
# permanente, nicht durch Wiederholung behebbare Fehler beschreiben.
# NetworkError (transient) und die unklassifizierte Basisklasse
# DownloadError (unbekannt) sind bewusst NICHT enthalten - fuer beide bleibt
# das bisherige, konservative Verhalten (Retry) unveraendert. FileProcessing-
# Error ist ebenfalls bewusst NICHT enthalten: die Klasse wird aktuell
# nirgends in der Download-Pipeline geworfen, ihre tatsaechlichen
# Fehlerursachen (z.B. voruebergehend volle Disk vs. dauerhafter
# Rechtefehler) sind ohne konkrete Call-Site nicht seriös klassifizierbar
# (Abschnitt 6/10 der Aufgabenstellung: keine Klassifikation ohne
# tatsaechlichen Fehlerfluss).
_NON_RETRYABLE_ERROR_TYPES = (
    InvalidURLError,
    FormatNotAvailableError,
    DownloadPermissionError,
    MetadataError,
    # Download-Control-Center 2026-09-02: ein Nutzer-Abbruch (❌-Button)
    # darf niemals automatisch erneut versucht werden.
    DownloadCancelledError,
)


def _make_cancel_check_hook(cancel_event):
    """
    Baut einen yt-dlp progress_hooks-Callback, der bei jedem Aufruf
    (mehrfach pro Sekunde waehrend eines laufenden Downloads) prueft, ob
    ein Abbruch angefordert wurde (ActiveDownload.cancel_event, siehe
    services/downloader/active_downloads.py) - falls ja, wirft er
    DownloadCancelledError. yt-dlp bricht den Download sofort ab, sobald
    ein Hook eine Exception wirft (dokumentiertes yt-dlp-Verhalten) -
    das ist der Hard-Cancel-Mechanismus fuer den gerade laufenden Track/
    Single-Download, nicht nur fuer "naechster Track startet nicht mehr".

    cancel_event ist ein threading.Event - dieser Hook laeuft im
    Executor-Thread (run_in_executor), Abfrage ist dort sicher.
    """

    def _check(status):
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelledError()

    return _check

# Bekannte, aus dem echten yt-dlp-Quellcode belegte Marker fuer permanente
# (nicht-transiente) Fehlermeldungen. Quelle: yt_dlp/extractor/youtube/
# _video.py (Auswertung von player_response["playabilityStatus"], von
# YouTube selbst gelieferter "reason"-Text) sowie
# yt_dlp/extractor/common.py::raise_login_required()/raise_no_formats() -
# beide setzen expected=True fuer genau diese Klasse von Meldungen. Bewusst
# NICHT enthalten: "isn't available, try again later" (yt-dlps eigener
# Rate-Limit-Hinweis, siehe _video.py - das ist ausdruecklich transient,
# Retry ist hier sinnvoll und bleibt unveraendert erhalten).
_YTDLP_PERMANENT_MESSAGE_MARKERS = (
    "private video",
    "video unavailable",
    "video has been removed",
    "video is no longer available",
    "account associated with this video has been terminated",
    "sign in to confirm your age",
    "age-restricted",
    "this video is not available",
    "copyright",
)


def _classify_ytdlp_error(exc: YoutubeDLError) -> DownloadError:
    """
    Uebersetzt eine rohe yt-dlp-Exception an der Boundary in die bestehende
    MusicBot-Fehlertaxonomie (services/downloader/errors.py).

    Nur eindeutig belegte Faelle werden klassifiziert:
      - GeoRestrictedError / UnsupportedError: yt-dlp-eigene, dedizierte
        Exception-Typen fuer Geo-Sperre bzw. nicht unterstuetzte/ungueltige
        URL - typsicher, keine String-Heuristik noetig.
      - ExtractorError (bzw. YoutubeDLError allgemein) mit expected=True
        UND einer Nachricht, die einen der bekannten, aus dem yt-dlp-
        Quellcode belegten Permanent-Marker enthaelt.

    Alles andere (insbesondere echte Netzwerkfehler, Timeouts, unerwartete
    yt-dlp-interne Fehler mit expected=False) wird bewusst NICHT
    klassifiziert und faellt auf die generische DownloadError-Basisklasse
    zurueck - identisch zum bisherigen, konservativen Verhalten (Retry).
    Kein Rateraten bei Unsicherheit (Abschnitt 10 der Aufgabenstellung).
    """
    if isinstance(exc, UnsupportedError):
        return InvalidURLError(str(exc), url=getattr(exc, "url", ""))
    if isinstance(exc, GeoRestrictedError):
        return InvalidURLError(str(exc))

    message = str(exc).lower()
    if getattr(exc, "expected", False) and any(
        marker in message for marker in _YTDLP_PERMANENT_MESSAGE_MARKERS
    ):
        return InvalidURLError(str(exc))

    return DownloadError(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# EnhancedDownloadProcessor – zentraler Prozessor
# ═══════════════════════════════════════════════════════════════════════════════


class EnhancedDownloadProcessor(SingletonMixin):
    """
    Zentraler Prozessor: initialisiert & injiziert alle spezialisierten
    Komponenten (Dependency Injection, keine versteckten Abhängigkeiten)
    und aggregiert Session-Statistiken.
    """

    def _do_init(
        self,
        config=None,
        logger_factory: Optional[Callable] = None,
        playlist_logger=None,
        cache_logger=None,
    ):
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("EnhancedDownloadProcessor")
        self.playlist_logger = playlist_logger or self.logger_factory(
            "PlaylistProcessor"
        )
        self.cache_logger = cache_logger or self.logger_factory("MetadataCache")

        self.logger.info("🚀 [INIT] Initialisiere EnhancedDownloadProcessor...")

        self.tracker = None
        self.config = config or self._get_default_config()

        self.logger.info(
            f"   📁 LIBRARY_DIR      : {getattr(self.config, 'LIBRARY_DIR', '?')}\n"
            f"   📁 DOWNLOAD_DIR     : {getattr(self.config, 'DOWNLOAD_DIR', '?')}\n"
            f"   💾 METADATA_CACHE   : {getattr(self.config, 'METADATA_CACHE_DIR', '?')}\n"
            f"   🎵 AUDIO_FORMAT     : {getattr(self.config, 'AUDIO_FORMAT', '?')}"
        )

        # ── Basis-Komponenten (alle Singleton – werden nur 1× initialisiert!) ──
        self.filename_fixer = FilenameFixerTool(
            self.config, logger_factory=self.logger_factory
        )
        self.playlist_processor = PlaylistProcessor(logger_factory=self.logger_factory)

        # MetadataEnricher-Protocol: process_single_track() / get_processing_statistics()
        self.enhanced_metadata_processor: MetadataEnricher = MetadataProcessorCore(
            self.config, logger_factory=self.logger_factory
        )

        # CacheProvider-Protocol: get() / store() / invalidate()
        self.metadata_cache: CacheProvider = MetadataCache(
            cache_dir=getattr(self.config, "METADATA_CACHE_DIR", "metadata_cache"),
            logger_factory=self.logger_factory,
        )

        artist_cfg = ArtistConfig(
            library_dir=getattr(self.config, "LIBRARY_DIR", "/music/library"),
            override_file=getattr(
                self.config, "ARTIST_OVERRIDE_FILE", "./artist_overrides.json"
            ),
        )
        self.artist_normalizer = ArtistNormalizer(artist_cfg)

        # ── Spezialisierte Orchestrierungs-Komponenten (Phase 2–6) ──────────────
        # Kein Singleton, reine Dependency Injection.
        self.cache_manager = CacheManager(
            metadata_cache=self.metadata_cache,
            artist_normalizer=self.artist_normalizer,
            logger_factory=self.logger_factory,
        )
        self.year_resolver = YearResolver(logger_factory=self.logger_factory)
        self.channel_router = ChannelRouter(
            artist_normalizer=self.artist_normalizer,
            config=self.config,
            logger_factory=self.logger_factory,
        )
        self.download_executor = DownloadExecutor(logger_factory=self.logger_factory)

        self.session_stats = {
            "total_processed": 0,
            "successful_downloads": 0,
            "failed_downloads": 0,
            "cache_hits": 0,
            "lyrics_found": 0,
            "dominant_artists_detected": 0,
            "artist_map_fallbacks": 0,
            "title_cleanups": 0,
        }

        self.logger.info("✅ [INIT] EnhancedDownloadProcessor bereit")

    # ── Hilfsmethoden ──────────────────────────────────────────────────────────

    def parse_track_title(self, track_title: str) -> dict:
        from utils.youtube_parser import parse_youtube_title

        return parse_youtube_title(track_title, logger_factory=self.logger_factory)

    def init_tracker(self, total_items: int):
        self.tracker = ProgressTracker(
            total_items=total_items,
            logger_factory=self.logger_factory,
        )
        self.logger.info(
            f"✅ [INIT] ProgressTracker initialisiert ({total_items} Items)"
        )

    def get_processing_statistics(self) -> Dict[str, Any]:
        return self.enhanced_metadata_processor.get_processing_statistics()

    def get_stats(self) -> Dict[str, Any]:
        """DownloadCoordinator-Protocol: aggregierte Session-Statistiken."""
        return self.session_stats

    def _get_default_config(self):
        try:
            return Config()
        except ImportError:
            self.logger.warning(
                "⚠️ [INIT] Config-Import fehlgeschlagen – Fallback aktiv"
            )

            class _Fallback:
                LIBRARY_DIR = Path("./music_library")
                ARTIST_OVERRIDE_FILE = Path("./artist_overrides.json")
                METADATA_CACHE_DIR = "metadata_cache"
                ENHANCED_METADATA_PROCESSING = True

            return _Fallback()

    def cleanup(self):
        """DownloadCoordinator-Protocol: Ressourcen freigeben."""
        self.logger.info("🧹 [CLEANUP] Starte Cleanup...")
        if hasattr(self, "metadata_cache"):
            self.metadata_cache.cleanup()
            self.logger.info("   💾 MetadataCache: bereinigt")
        if hasattr(self, "tracker") and self.tracker:
            self.tracker.cleanup()
            self.logger.info("   ⏳ ProgressTracker: bereinigt")
        self.logger.info("✅ [CLEANUP] EnhancedDownloadProcessor cleanup abgeschlossen")


# ═══════════════════════════════════════════════════════════════════════════════
# HAUPT-EINSTIEGSPUNKT: enhanced_download_with_retry
# ═══════════════════════════════════════════════════════════════════════════════


async def enhanced_download_with_retry(
    url: str,
    chat_id: int,
    update_id: int,
    status_callback: Optional[Callable] = None,
    max_retries: int = 3,
    logger=None,
    processor_logger=None,
    playlist_logger=None,
    cache_logger=None,
    logger_factory: Optional[Callable] = None,
    duplicate_detector=None,
    active_download=None,
) -> Dict[str, Any]:
    """
    Haupt-Einstiegspunkt für Downloads mit Retry-Logik.

    Ablauf:
      1. Komponenten initialisieren (EnhancedDownloadProcessor + Sub-Komponenten)
      2. yt-dlp Optionen via DownloadExecutor zusammenstellen
      3. Retry-Loop: Info extrahieren → Playlist oder Single weiterleiten
      4. Rückgabe: { success, type, tracks/track_info, processor_instance }

    Download-Control-Center 2026-09-02: active_download (optional, ein
    services.downloader.active_downloads.ActiveDownload) liefert - falls
    übergeben - den geteilten ProgressTracker (für "🔄 Aktive Downloads")
    sowie das cancel_event für den ❌-Abbrechen-Button. Ohne
    active_download (z.B. isolierte Tests, oder Aufrufer die (noch) keine
    ActiveDownloadRegistry haben) verhält sich diese Funktion unverändert
    wie bisher - kein Cancel-Hook, lokaler ProgressTracker in
    _process_playlist_download().
    """
    actual_lf = logger_factory or get_module_logger
    logger = logger or actual_lf("download_utils")

    # Nutzer-Wunsch (Abschlussmeldung "⏱️ Dauer"): Gesamtlaufzeit dieses
    # Downloads (inkl. aller Retry-Versuche) - misst ab hier bis zum
    # jeweiligen Erfolgs-Return unten, nicht nur den reinen yt-dlp-Anteil.
    _dl_start = time.monotonic()

    logger.info(
        f"\n{'═'*60}\n"
        f"⬇️  DOWNLOAD GESTARTET\n"
        f"   URL       : {url}\n"
        f"   Chat-ID   : {chat_id}\n"
        f"   Update-ID : {update_id}\n"
        f"   Max-Retr. : {max_retries}\n"
        f"{'═'*60}"
    )

    # ── 1. Komponenten ────────────────────────────────────────────────────────
    logger.info("🔧 [INIT] Baue Processor-Komponenten auf...")
    try:
        config = Config()
    except Exception:
        config = None

    enhanced_processor = EnhancedDownloadProcessor(
        config,
        logger_factory=actual_lf,
        playlist_logger=playlist_logger or actual_lf("PlaylistProcessor"),
        cache_logger=cache_logger or actual_lf("MetadataCache"),
    )
    if config is None:
        config = enhanced_processor.config

    filename_fixer = enhanced_processor.filename_fixer
    logger.info("✅ [INIT] Alle Komponenten bereit")

    # ── 2. yt-dlp Optionen ────────────────────────────────────────────────────
    ydl_opts = enhanced_processor.download_executor.build_ydl_opts(config)
    if active_download is not None:
        # Hard-Cancel-Hook: wird an JEDEM nachfolgenden yt-dlp-Aufruf
        # (Single-Download UND jeder einzelne Playlist-Track, siehe
        # download_executor.py::download_single_track()) automatisch
        # mitgezogen, da beide Stellen ydl_opts["progress_hooks"]
        # erweitern statt ersetzen.
        ydl_opts = {
            **ydl_opts,
            "progress_hooks": [
                *ydl_opts.get("progress_hooks", []),
                _make_cancel_check_hook(active_download.cancel_event),
            ],
        }
    if is_youtube_mix_url(url):
        # DUP-06: verhindert, dass yt-dlp fuer eine automatisch generierte
        # Mix-/Radio-Liste (list=RD...) ueberhaupt ein entries-tragendes
        # Playlist-Ergebnis erzeugt - die bestehende entries-Verzweigung
        # weiter unten bleibt dadurch unveraendert, sie sieht fuer diese
        # URLs schlicht kein entries mehr.
        ydl_opts = {**ydl_opts, "noplaylist": True}
        logger.info(
            "🎯 [DL] list=RD…-URL erkannt (Mix/Radio) — noplaylist=True gesetzt"
        )

    # ── 3. Retry-Loop ─────────────────────────────────────────────────────────
    last_error: Optional[str] = None

    for attempt in range(max_retries):
        if active_download is not None and active_download.is_cancel_requested():
            logger.warning(
                f"🛑 [RETRY {attempt + 1}] Abbruch bereits vor Versuchsstart angefordert"
            )
            active_download.cancelled = True
            return {"success": False, "error": "Download abgebrochen", "cancelled": True}

        logger.info(
            f"\n🔄 [RETRY {attempt + 1}/{max_retries}] Starte Download-Versuch..."
        )

        try:
            logger.info("🔍 [DL] yt-dlp: Extrahiere Metadaten (download=False)...")
            info = await enhanced_processor.download_executor.extract_info_async(
                url, ydl_opts, download=False
            )

            if not info:
                raise DownloadError("yt-dlp lieferte kein Ergebnis (info=None)")

            entries = info.get("entries")
            if entries:
                n_entries = len(entries)
                logger.info(
                    f"📋 [DL] Playlist erkannt:\n"
                    f"   Titel      : {info.get('title', '?')}\n"
                    f"   Uploader   : {info.get('uploader', '?')}\n"
                    f"   Einträge   : {n_entries}\n"
                    f"   Playlist-ID: {info.get('id', '?')}"
                )
                if active_download is not None:
                    active_download.title = (
                        f"{info.get('uploader', '?')} – {info.get('title', '?')}"
                    )
                tracks = await _process_playlist_download(
                    playlist_info=info,
                    ydl_opts=ydl_opts,
                    enhanced_processor=enhanced_processor,
                    filename_fixer=filename_fixer,
                    chat_id=chat_id,
                    status_callback=status_callback,
                    logger=logger,
                    duplicate_detector=duplicate_detector,
                    active_download=active_download,
                )
                logger.info(
                    f"✅ [RETRY {attempt+1}] Playlist fertig: "
                    f"{len([t for t in tracks if t.get('success')])}/{len(tracks)} Tracks"
                )
                # Download-Control-Center: _process_playlist_download()
                # bricht bei Abbruch die Schleife ab und liefert die
                # bisherigen Ergebnisse zurueck (success:True waere hier
                # sonst irrefuehrend - Playlist NICHT vollstaendig
                # verarbeitet, sondern abgebrochen).
                was_cancelled = (
                    active_download is not None
                    and active_download.is_cancel_requested()
                )
                if was_cancelled and active_download is not None:
                    active_download.cancelled = True
                return {
                    "success": True,
                    "type": "playlist",
                    "tracks": tracks,
                    "processor_instance": enhanced_processor,
                    "total_tracks": len(tracks),
                    "successful_tracks": len(
                        [t for t in tracks if t.get("success")]
                    ),
                    "duration_seconds": time.monotonic() - _dl_start,
                    "cancelled": was_cancelled,
                }
            else:
                logger.info(
                    f"🎵 [DL] Einzelner Track erkannt:\n"
                    f"   Titel    : {info.get('title', '?')}\n"
                    f"   Uploader : {info.get('uploader', '?')}\n"
                    f"   Dauer    : {info.get('duration', '?')}s\n"
                    f"   Video-ID : {info.get('id', '?')}"
                )
                if active_download is not None:
                    active_download.title = (
                        f"{info.get('uploader', '?')} – {info.get('title', '?')}"
                    )
                    active_download.tracker.set_current_item(active_download.title)
                single = await _process_single_download(
                    url=url,
                    video_info=info,
                    ydl_opts=ydl_opts,
                    enhanced_processor=enhanced_processor,
                    filename_fixer=filename_fixer,
                    logger=logger,
                )
                logger.info(
                    f"✅ [RETRY {attempt+1}] Single-Track fertig: "
                    f"'{single.get('artist','?')} – {single.get('title','?')}'"
                )
                return {
                    "success": True,
                    "type": "single",
                    "track_info": single,
                    "processor_instance": enhanced_processor,
                    "duration_seconds": time.monotonic() - _dl_start,
                    "cancelled": False,
                }

        except (YoutubeDLError, DownloadError) as e:
            # DL-03/DL-05: rohe yt-dlp-Fehler (z.B. aus extract_info_async()
            # oben, bevor ueberhaupt zwischen Playlist/Single unterschieden
            # wird) werden zuerst an der Boundary klassifiziert; bereits
            # klassifizierte DownloadError-Subtypen (z.B. MetadataError aus
            # _process_single_download()) werden unveraendert uebernommen.
            last_error = str(e)
            classified = e if isinstance(e, DownloadError) else _classify_ytdlp_error(e)

            if isinstance(classified, _NON_RETRYABLE_ERROR_TYPES):
                is_cancel = isinstance(classified, DownloadCancelledError)
                if is_cancel:
                    if active_download is not None:
                        active_download.cancelled = True
                    logger.warning(
                        f"🛑 [RETRY {attempt+1}] Download abgebrochen (Nutzeranfrage)"
                    )
                else:
                    logger.error(
                        f"⛔ [RETRY {attempt+1}] Permanenter Fehler erkannt — "
                        f"kein weiterer Versuch (DL-03/DL-05):\n"
                        f"   Typ    : {type(classified).__name__}\n"
                        f"   Fehler : {last_error}"
                    )
                return {
                    "success": False,
                    "error": (
                        "Download abgebrochen"
                        if is_cancel
                        else f"Download dauerhaft fehlgeschlagen (kein Retry sinnvoll): {last_error}"
                    ),
                    "cancelled": is_cancel,
                }

            logger.error(
                f"❌ [RETRY {attempt+1}] DownloadError:\n"
                f"   Fehler : {last_error}\n"
                f"   {'→ Letzter Versuch – breche ab' if attempt == max_retries - 1 else f'→ Warte {2**attempt}s, dann Versuch {attempt+2}'}"
            )
            if attempt == max_retries - 1:
                return {
                    "success": False,
                    "error": f"Download nach {max_retries} Versuchen fehlgeschlagen: {last_error}",
                }
            await asyncio.sleep(2**attempt)

        except Exception as e:
            last_error = str(e)
            logger.error(
                f"💥 [RETRY {attempt+1}] Unerwarteter Fehler:\n"
                f"   Typ    : {type(e).__name__}\n"
                f"   Fehler : {last_error}\n"
                f"   {'→ Letzter Versuch – breche ab' if attempt == max_retries - 1 else f'→ Warte {2**attempt}s, dann Versuch {attempt+2}'}",
                exc_info=True,
            )
            if attempt == max_retries - 1:
                return {"success": False, "error": f"Unerwarteter Fehler: {last_error}"}
            await asyncio.sleep(2**attempt)

    return {
        "success": False,
        "error": f"Maximale Versuche ({max_retries}) erreicht. Letzter Fehler: {last_error}",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PLAYLIST-PIPELINE (Orchestrierung)
# ═══════════════════════════════════════════════════════════════════════════════


async def _process_playlist_download(
    playlist_info: Dict[str, Any],
    ydl_opts: dict,
    enhanced_processor: EnhancedDownloadProcessor,
    filename_fixer: FilenameFixerTool,
    chat_id: Optional[int] = None,
    status_callback: Optional[Callable] = None,
    logger=None,
    duplicate_detector=None,
    active_download=None,
) -> List[Dict[str, Any]]:
    """
    Playlist-Pipeline (reine Orchestrierung).

    Phasen:
      [PL-ANALYSE]    PlaylistProcessor.process_playlist_metadata()
      [CHANNEL]       ChannelRouter.resolve_dominant_artist() (P1–P5)
      [YEAR]          YearResolver.resolve_playlist_year()
      [TRACK XX/NN]   Singles-Konflikt → CacheManager → Duplicate-Check → DownloadExecutor → _process_track_metadata
      [STATS]         ProgressFormatter.stats_table()

    Live-Fund 2026-09-02 (Nutzer-Report): _probe_artist_title_for_duplicate_check()
    (klassen/download_handler.py) liefert fuer Playlist-URLs bewusst (None,
    None) zurueck - check_for_duplicates() prueft fuer Playlists bisher NUR
    die URL-Ebene der Playlist selbst, nie Artist/Titel der einzelnen darin
    enthaltenen Tracks. Ein Track, der bereits als Single existiert (z.B.
    "Zartmann - schoenhauser" unter Zartmann/Singles/), wurde beim Download
    derselben Playlist erneut heruntergeladen UND der alte Duplicate-Cache-
    Eintrag durch den neuen (gleicher Content-Hash) stillschweigend
    ueberschrieben. duplicate_detector ist optional (None fuer Aufrufer, die
    keinen haben, z.B. isolierte Tests) - ohne ihn faellt dieser Schritt
    bewusst aus, exakt das bisherige Verhalten.

    Playlist-Prioritaet (Nutzer-Wunsch 2026-09-02, Folge-Fund desselben
    Reports): der obige Duplikat-Check allein loeste das Problem nicht
    vollstaendig - er UEBERSPRINGT den Track nur, das Album blieb weiter
    unvollstaendig. Zusaetzlich griff bereits VOR diesem Check der
    Metadata-Cache-Kurzschluss (CacheManager.lookup_playlist_track()), der
    einen Treffer als "Erfolg" meldet, ohne die Datei in den Album-Ordner
    zu verschieben - live beobachtet fuer "wie du manchmal fehlst" (fehlte
    im Album "dafuer bin ich frei EP", obwohl bereits als Single
    vorhanden). Fix: DuplicateDetector.resolve_playlist_single_conflict()
    laeuft jetzt VOR dem Cache-Check und loescht eine vorhandene
    Singles-Datei physisch (inkl. Duplicate-Cache-Invalidierung), sodass
    der Track danach normal (neu) heruntergeladen und korrekt im
    Album-Ordner einsortiert wird - das Playlist-/Album-Ergebnis hat damit
    bewusst Prioritaet vor der aelteren Einzel-Datei.

    Playlist-Progress-State (Nutzer-Wunsch 2026-09-02, Folgeschritt zur
    ProgressTracker-Erweiterung): status_callback (falls uebergeben) wird
    jetzt pro Track mit dem ProgressTracker selbst aufgerufen (reiner
    Zustand: current_item/completed_items/processed_items/total_items,
    KEIN vorformatierter Text) - throttled ueber
    tracker.compute_progress_message() (bestehende update_interval-
    Drosselung, 5s). Die Telegram-spezifische Darstellung (Fortschritts-
    balken, "⬇️ Aktuell"/"✅ Abgeschlossen"-Sektionen) bleibt bewusst
    Aufgabe des Aufrufers (klassen/download_handler.py) - dieses Modul
    importiert dafuer nichts Telegram-Spezifisches. Ersetzt die vorherige,
    nie tatsaechlich verdrahtete status_callback-Signatur
    (chat_id, step, total, message, module) - hatte 0 echte Aufrufer.

    Download-Control-Center 2026-09-02: active_download (optional, siehe
    services.downloader.active_downloads.ActiveDownload) liefert - falls
    uebergeben - den GETEILTEN ProgressTracker (damit "🔄 Aktive
    Downloads" denselben Fortschritt sieht, den auch status_callback
    bekommt) statt eines rein lokalen. Vor jedem Track wird zusaetzlich
    active_download.is_cancel_requested() geprueft - bei Abbruch werden
    KEINE weiteren Tracks mehr gestartet (Soft-Cancel zwischen Tracks).
    Ein Abbruch WAEHREND eines laufenden Tracks (Hard-Cancel, ueber den
    in ydl_opts["progress_hooks"] injizierten Hook, siehe
    enhanced_download_with_retry()) wirft DownloadCancelledError - wird
    hier separat (nicht als generischer Fehler) behandelt: die Schleife
    bricht sofort ab, statt zum naechsten Track weiterzugehen.
    """
    logger = logger or get_module_logger("download_utils")

    entries = playlist_info.get("entries", [])
    if not entries:
        raise DownloadError("Playlist ist leer oder konnte nicht geladen werden")

    # Ressourcen-Limit durchsetzen: MAX_PLAYLIST_ITEMS war in config.py
    # definiert, wurde aber nirgends in der Pipeline gelesen - eine Playlist
    # mit tausenden Eintraegen wurde bisher komplett unbegrenzt verarbeitet
    # (unbegrenzter Speicher-/Bandbreiten-/Zeitverbrauch pro Anfrage).
    max_playlist_items = getattr(enhanced_processor.config, "MAX_PLAYLIST_ITEMS", None)
    if max_playlist_items and len(entries) > max_playlist_items:
        logger.warning(
            f"⚠️ [PL] Playlist hat {len(entries)} Einträge, "
            f"kürze auf MAX_PLAYLIST_ITEMS={max_playlist_items}"
        )
        entries = entries[:max_playlist_items]

    logger.info(
        f"\n{'═'*60}\n"
        f"📋 PLAYLIST-PIPELINE START\n"
        f"   Titel    : {playlist_info.get('title', '?')}\n"
        f"   Uploader : {playlist_info.get('uploader', '?')}\n"
        f"   Tracks   : {len(entries)}\n"
        f"{'═'*60}"
    )

    # ── PHASE 1: Playlist-Analyse ─────────────────────────────────────────────
    logger.info(
        "🎯 [PL-ANALYSE] Starte PlaylistProcessor.process_playlist_metadata()..."
    )
    processed_playlist = (
        enhanced_processor.playlist_processor.process_playlist_metadata(
            entries, playlist_info
        )
    )

    dominant_artist = processed_playlist.get("dominant_artist")
    album_name = processed_playlist.get("album", "Playlist")

    logger.info(
        f"✅ [PL-ANALYSE] Ergebnis:\n"
        f"   Album            : {album_name}\n"
        f"   Dominanter Artist: {dominant_artist or '❌ nicht erkannt'}\n"
        f"   Track-Count      : {len(processed_playlist.get('tracks', []))}"
    )

    # ── PHASE 2: Channel-Routing ──────────────────────────────────────────────
    _channel_raw, dominant_artist = enhanced_processor.channel_router.resolve_dominant_artist(
        dominant_artist=dominant_artist,
        playlist_info=playlist_info,
        entries=entries,
    )

    # ── PHASE 3: Dominantes Jahr ──────────────────────────────────────────────
    playlist_year = enhanced_processor.year_resolver.resolve_playlist_year(
        entries=entries,
        processed_playlist=processed_playlist,
        playlist_info=playlist_info,
    )

    if dominant_artist:
        enhanced_processor.session_stats["dominant_artists_detected"] += 1

    logger.info(
        f"\n{'─'*60}\n"
        f"📊 [PL-ANALYSE] FINALES PLAYLIST-KONTEXT:\n"
        f"   Album             : {album_name}\n"
        f"   Dominanter Artist : {dominant_artist or '❌ Compilations-Modus'}\n"
        f"   Playlist-Jahr     : {playlist_year}\n"
        f"   Playlist-Channel  : {_channel_raw or '?'}\n"
        f"{'─'*60}"
    )

    # ── PHASE 4: Track-by-Track-Verarbeitung ──────────────────────────────────
    results: List[Dict[str, Any]] = []
    processed_tracks = processed_playlist["tracks"]
    cache_hits = 0
    total = len(processed_tracks)
    if active_download is not None:
        tracker = active_download.tracker
        tracker.total_items = total
    else:
        tracker = ProgressTracker(total_items=total)

    for idx, track_info in enumerate(processed_tracks, 1):
        if active_download is not None and active_download.is_cancel_requested():
            logger.warning(
                f"🛑 [PL] Abbruch angefordert — starte keine weiteren Tracks "
                f"({idx}/{total} nicht mehr versucht)"
            )
            break

        track_title = track_info.get("title", "?")
        track_artist = track_info.get("artist", "?")
        display_name = f"{idx:02d} - {track_title}"

        logger.info(ProgressFormatter.track_header(idx, total, track_title, track_artist))

        tracker.set_current_item(display_name)
        if status_callback and tracker.compute_progress_message() is not None:
            await status_callback(tracker)

        try:
            enhanced_processor.session_stats["total_processed"] += 1

            # ── SINGLES-KONFLIKT AUFLOESEN (Playlist-Prioritaet) ────────────────
            # Nutzer-Wunsch 2026-09-02: siehe Docstring von
            # DuplicateDetector.resolve_playlist_single_conflict() - MUSS vor
            # dem CACHE-CHECK laufen, da genau dieser Cache-Kurzschritt bisher
            # eine bereits als Single vorhandene Datei als "Erfolg" meldete,
            # ohne sie in den Album-Ordner zu verschieben (Album blieb
            # unvollstaendig). Nach dem Loeschen sieht sowohl der Cache- als
            # auch der nachfolgende Duplikat-Check die Datei korrekt als
            # nicht mehr vorhanden und laesst den Track normal herunterladen.
            if (
                duplicate_detector is not None
                and track_artist
                and track_artist != "?"
                and track_title
                and track_title != "?"
            ):
                duplicate_detector.resolve_playlist_single_conflict(
                    track_artist, track_title
                )

            # ── CACHE-CHECK ───────────────────────────────────────────────────
            cache_result = enhanced_processor.cache_manager.lookup_playlist_track(
                track_info=track_info,
                dominant_artist=dominant_artist,
                album_name=album_name,
                playlist_year=playlist_year,
                track_idx=idx,
            )

            if cache_result:
                dl_result = DownloadResult(**cache_result)
                dl_result.enhanced_processor_ref = enhanced_processor

                cache_hits += 1
                enhanced_processor.session_stats["cache_hits"] += 1
                result_dict = dl_result.to_dict()
                results.append(result_dict)
                logger.info(
                    f"💾 [CACHE] HIT für Track {idx:02d}: "
                    f"'{result_dict['artist']} – {result_dict['title']}' "
                    f"→ überspringe Download"
                )
                continue

            # ── DUPLIKAT-CHECK (Artist/Titel) ────────────────────────────────
            # Live-Fund 2026-09-02: siehe Docstring oben. Nur wenn ein
            # duplicate_detector uebergeben wurde UND Artist/Titel dieses
            # Tracks bekannt sind (kein Platzhalter "?") - fehlende Werte
            # blockieren nichts, exakt wie beim bereits bestehenden
            # URL-Ebenen-Verhalten fuer Playlists.
            if (
                duplicate_detector is not None
                and track_artist
                and track_artist != "?"
                and track_title
                and track_title != "?"
            ):
                track_url = track_info.get("webpage_url") or track_info.get("url") or ""
                is_dup, dup_entry, dup_type = duplicate_detector.check_for_duplicates(
                    url=track_url,
                    raw_artist=track_artist,
                    raw_title=track_title,
                )
                if is_dup and dup_entry:
                    logger.warning(
                        f"🔍 [DUPE] Track {idx:02d} '{track_artist} - {track_title}' "
                        f"bereits vorhanden (Typ: {dup_type}, Pfad: {dup_entry.file_path}) "
                        f"— überspringe"
                    )
                    results.append(
                        DownloadResult(
                            success=False,
                            title=track_title,
                            artist=track_artist,
                            is_duplicate=True,
                            error=f"Duplikat — bereits vorhanden: {dup_entry.file_path}",
                        ).to_dict()
                    )
                    continue

            # ── DOWNLOAD ──────────────────────────────────────────────────────
            # PL-01 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md):
            # download_single_track() besitzt eine echte Retry-Schleife, der
            # Funktions-Default max_retries=1 (kein Retry) griff hier bisher
            # mangels Uebergabe fuer jeden Playlist-Track - waehrend Single-
            # Downloads bereits 3 Versuche ueber enhanced_download_with_retry()
            # erhalten. Explizit freigegebene fachliche Entscheidung: Playlist-
            # Tracks erhalten denselben festen Wert wie der Single-Pfad.
            downloaded_file = await enhanced_processor.download_executor.download_single_track(
                track_info=track_info,
                ydl_opts=ydl_opts,
                track_idx=idx,
                download_dir=enhanced_processor.config.DOWNLOAD_DIR,
                max_retries=3,
            )

            if not downloaded_file:
                enhanced_processor.session_stats["failed_downloads"] += 1
                logger.error(
                    f"❌ [DL] Track {idx:02d} Download fehlgeschlagen — überspringe"
                )
                results.append(
                    DownloadResult(
                        success=False,
                        title=track_title,
                        error="Download fehlgeschlagen",
                    ).to_dict()
                )
                continue

            # ── METADATEN ─────────────────────────────────────────────────────
            track_result = await _process_track_metadata(
                track_info=track_info,
                downloaded_file=downloaded_file,
                enhanced_processor=enhanced_processor,
                filename_fixer=filename_fixer,
                album_name=album_name,
                dominant_artist=dominant_artist,
                playlist_year=playlist_year,
                track_idx=idx,
                playlist_channel=_channel_raw or None,
                logger=logger,
            )

            results.append(track_result)

            # Session-Stats aktualisieren
            if track_result.get("success"):
                enhanced_processor.session_stats["successful_downloads"] += 1
                if track_result.get("lyrics_available"):
                    enhanced_processor.session_stats["lyrics_found"] += 1
                if track_result.get("artist_source") == "artist_map_fallback":
                    enhanced_processor.session_stats["artist_map_fallbacks"] += 1
                if track_result.get("title_cleaned"):
                    enhanced_processor.session_stats["title_cleanups"] += 1

            logger.info(ProgressFormatter.track_result_block(idx, track_result))

        except asyncio.CancelledError as ce:
            # DL-08 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2G_DL06_AUDIT.md,
            # Abschnitt 6): CancelledError erbt seit Python 3.8 von BaseException,
            # nicht von Exception - wuerde ohne diesen Zweig die Funktion sofort
            # verlassen und die bereits fuer vorherige Tracks gesammelten `results`
            # unwiederbringlich verlieren, bevor sie
            # klassen/download_handler.py::_register_playlist_track_duplicates()
            # erreichen. Bereits erfolgreiche Tracks liegen zu diesem Zeitpunkt
            # real in der Library - ohne diese Weitergabe wuerde ein spaeterer
            # erneuter Download desselben Tracks nicht als Duplikat erkannt.
            # Das Attribut ist der einzige Weg, die Teilergebnisse ueber die
            # Exception-Propagation hinweg an handle_youtube_links() (Aufrufer
            # mehrere Ebenen hoeher) weiterzureichen, ohne Rueckgabevertraege
            # von enhanced_download_with_retry()/download_audio() zu aendern -
            # beide fangen CancelledError bereits jetzt nicht ab und lassen sie
            # samt Attribut unveraendert durch. Cancellation wird NICHT
            # unterdrueckt: die Exception wird unveraendert erneut geworfen.
            ce.partial_playlist_results = results
            raise

        except DownloadCancelledError:
            # Download-Control-Center 2026-09-02: Hard-Cancel WAEHREND
            # dieses Tracks (progress_hooks-Hook hat ausgeloest, siehe
            # enhanced_download_with_retry()). Anders als ein generischer
            # Fehler wird hier NICHT zum naechsten Track weitergegangen -
            # die Schleife bricht komplett ab (der Nutzer hat den GANZEN
            # Download abgebrochen, nicht nur diesen einen Track).
            logger.warning(
                f"🛑 [TRACK {idx:02d}] Abgebrochen (Nutzeranfrage) — "
                f"verbleibende Tracks werden nicht mehr gestartet"
            )
            if active_download is not None:
                active_download.cancelled = True
            results.append(
                DownloadResult(
                    success=False,
                    title=track_info.get("title"),
                    error="Download abgebrochen",
                ).to_dict()
            )
            break

        except Exception as e:
            enhanced_processor.session_stats["failed_downloads"] += 1
            logger.error(
                f"💥 [TRACK {idx:02d}] Unerwarteter Fehler:\n"
                f"   Typ    : {type(e).__name__}\n"
                f"   Fehler : {e}",
                exc_info=True,
            )
            results.append(
                DownloadResult(
                    success=False,
                    title=track_info.get("title"),
                    error=str(e),
                ).to_dict()
            )

        finally:
            # Laeuft bei JEDEM Ausgang der Schleifen-Iteration (continue,
            # normaler Durchlauf, Exception-Zweig) - siehe Docstring oben.
            # CancelledError propagiert unveraendert weiter, finally laeuft
            # trotzdem vorher (harmloses Bookkeeping, beeinflusst die
            # Exception-Weitergabe nicht).
            tracker.mark_completed(display_name)
            if status_callback and tracker.compute_progress_message() is not None:
                await status_callback(tracker)

    # ── PHASE 5: Finale Statistiken ───────────────────────────────────────────
    final_stats = (
        enhanced_processor.enhanced_metadata_processor.get_processing_statistics()
    )
    session_stats = enhanced_processor.session_stats

    logger.info(ProgressFormatter.stats_table(session_stats, final_stats, cache_hits, total))

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# TRACK-METADATEN-VERARBEITUNG (Playlist-Kontext, Orchestrierung)
# ═══════════════════════════════════════════════════════════════════════════════


async def _process_track_metadata(
    track_info: Dict,
    downloaded_file: str,
    enhanced_processor: EnhancedDownloadProcessor,
    filename_fixer: FilenameFixerTool,
    album_name: str,
    dominant_artist: Optional[str],
    playlist_year: Optional[int],
    track_idx: int,
    playlist_channel: Optional[str] = None,
    logger=None,
) -> Dict[str, Any]:
    """
    Bereitet track_metadata für EnhancedMetadataProcessor auf, ruft
    `process_single_track()` auf und übersetzt das `MetadataResult`
    in ein `DownloadResult`-Dict.

    Schlüssel-Entscheidungen die hier geloggt werden:
      - original_youtube_title vs bereinigter Titel (Artist-Parsing-Qualität)
      - playlist_channel vs track-level uploader (Compilation-Channel-Fix)
      - dominant_artist Übergabe (Processor entscheidet intern über Spezialkanäle)
    """
    logger = logger or get_module_logger("download_utils")

    # Original-Titel bevorzugen (vor PlaylistProcessor-Bereinigung)
    original_title = track_info.get("original_youtube_title") or track_info.get("title")

    if track_info.get("original_youtube_title") and track_info.get(
        "original_youtube_title"
    ) != track_info.get("title"):
        logger.debug(
            f"🎵 [META] Original-Titel für YouTube-Parser:\n"
            f"   Original  : '{track_info['original_youtube_title']}'\n"
            f"   Bereinigt : '{track_info.get('title')}'\n"
            f"   → Verwende Original für bessere Artist-Erkennung"
        )

    if playlist_channel and playlist_channel != (track_info.get("uploader") or ""):
        logger.debug(
            f"⭐ [META] Compilation-Channel-Fix aktiv:\n"
            f"   playlist_channel (Spezialkanal)  : '{playlist_channel}'\n"
            f"   track uploader (echter Künstler) : '{track_info.get('uploader','?')}'\n"
            f"   → playlist_channel für Spezialkanal-Routing, uploader für Artist-Tag"
        )

    track_metadata = {
        "filepath": downloaded_file,
        "title": original_title,
        "artist": track_info.get("uploader") or track_info.get("artist"),
        "album": album_name,
        "album_artist": dominant_artist
        or track_info.get("uploader")
        or "Various Artists",
        "track_number": track_idx,
        "year": playlist_year,
        "id": track_info.get("id"),
        "uploader": track_info.get("uploader"),
        "channel": track_info.get("channel") or track_info.get("uploader"),
        "upload_date": track_info.get("upload_date"),
        # DUP-01 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md):
        # eigene Video-URL des Tracks - dieselbe Quelle, die
        # download_executor.py::download_single_track() bereits fuer den
        # eigentlichen Download verwendet (track_info["webpage_url"]/["url"]).
        # Wird fuer die spaetere Duplicate-Cache-Registrierung benoetigt -
        # vorher ging dieses Feld beim Uebergang zu MetadataResult verloren.
        "webpage_url": track_info.get("webpage_url") or track_info.get("url"),
        "playlist_album": album_name,
        "playlist_channel": playlist_channel or "",
        "playlist_name": album_name,
    }

    playlist_context = {
        "album": album_name,
        "album_artist": dominant_artist or "Various Artists",
        "track_number": track_idx,
        "year": playlist_year,
        "is_playlist": True,
        "playlist_channel": playlist_channel or "",
    }

    logger.debug(
        f"🚀 [META] Starte EnhancedMetadataProcessor für Track {track_idx:02d}:\n"
        f"   Titel          : {original_title}\n"
        f"   Artist (raw)   : {track_metadata['artist']}\n"
        f"   Dominant-Artist: {dominant_artist or '❌ none (Compilations-Modus)'}\n"
        f"   playlist_channel: {playlist_channel or '–'}"
    )

    try:
        enhanced_result: MetadataResult = await call_process_single_track(
            enhanced_processor.enhanced_metadata_processor,
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
            playlist_metadata=playlist_context,
            dominant_artist=dominant_artist,
        )

        # AUTOLEARN-001: externer, redundanter Auto-Learning-Aufruf entfernt.
        # process_single_track() ruft auto_learn_manager.learn_artist() intern
        # bereits fuer jeden Track auf (Schritt 19b) - inkl. derselben breiten
        # Sonderkanal-Pruefung, die hier vorher zusaetzlich (mit teils
        # abweichenden Bedingungen) dupliziert wurde. Siehe
        # docs/archive/MusicBot_ENGINEERING_BASELINE.md.

        if enhanced_result.success:
            logger.info(
                f"✅ [META] Track {track_idx:02d} Metadaten erfolgreich:\n"
                f"   Artist      : '{enhanced_result.artist}' (Src: {enhanced_result.artist_source})\n"
                f"   Titel       : '{enhanced_result.title}'\n"
                f"   Album       : '{enhanced_result.album}'\n"
                f"   Jahr        : {enhanced_result.year}\n"
                f"   Genre-Src   : {enhanced_result.genre_source}\n"
                f"   Library     : {enhanced_result.library_path}"
            )
            # ARCH-004/P-3: gemeinsame Integrationsschicht statt inline
            # dupliziertem DownloadResult(...)-Aufbau - siehe
            # services/downloader/metadata_result_translator.py
            return build_playlist_track_result(
                enhanced_result,
                playlist_year=playlist_year,
                album_name=album_name,
                track_idx=track_idx,
                enhanced_processor_ref=enhanced_processor,
            )
        else:
            err = enhanced_result.error or "Metadatenverarbeitung fehlgeschlagen"
            logger.error(
                f"❌ [META] Track {track_idx:02d} fehlgeschlagen:\n" f"   Fehler: {err}"
            )
            return DownloadResult(
                success=False, title=track_info.get("title"), error=err
            ).to_dict()

    except Exception as e:
        logger.error(
            f"💥 [META] Track {track_idx:02d} unerwarteter Fehler:\n"
            f"   Typ    : {type(e).__name__}\n"
            f"   Fehler : {e}",
            exc_info=True,
        )
        return DownloadResult(
            success=False, title=track_info.get("title"), error=str(e)
        ).to_dict()


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLE-TRACK-PIPELINE (Orchestrierung)
# ═══════════════════════════════════════════════════════════════════════════════


async def _process_single_download(
    url: str,
    video_info: Dict[str, Any],
    ydl_opts: dict,
    enhanced_processor: EnhancedDownloadProcessor,
    filename_fixer: FilenameFixerTool,
    logger=None,
) -> Dict[str, Any]:
    """
    Single-Track-Pipeline (reine Orchestrierung):
      [CACHE-CHECK] → [DOWNLOAD] → [META] → [ERGEBNIS]
    """
    logger = logger or get_module_logger("download_utils")

    title = video_info.get("title", "Unknown")
    artist = video_info.get("artist") or video_info.get("uploader", "Unknown")

    logger.info(
        f"\n{'─'*60}\n"
        f"🎵 SINGLE-TRACK-PIPELINE\n"
        f"   Titel    : {title}\n"
        f"   Artist   : {artist}\n"
        f"   Video-ID : {video_info.get('id', '?')}\n"
        f"{'─'*60}"
    )

    enhanced_processor.session_stats["total_processed"] += 1

    # ── Cache-Check ───────────────────────────────────────────────────────────
    cached_result = enhanced_processor.cache_manager.lookup_single_track(artist, title)
    if cached_result:
        enhanced_processor.session_stats["cache_hits"] += 1
        dl_result = DownloadResult(**cached_result)
        dl_result.enhanced_processor_ref = enhanced_processor
        return dl_result.to_dict()

    # ── Download ──────────────────────────────────────────────────────────────
    logger.info(f"⬇️  [DL] Starte Single-Download: {url[:80]}")

    # DL-02 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2C_DL02_AUDIT.md):
    # schlaegt yt-dlp/FFmpeg WAEHREND extract_info_async() fehl (z.B.
    # FFmpeg-Postprocessing-Fehler), wird download_info unten nie zugewiesen -
    # beide Strategien von find_downloaded_file() benoetigen dieses Dict und
    # sind in diesem Fehlerfall grundsaetzlich nicht anwendbar. Ein
    # progress_hooks-Callback liefert den tatsaechlichen Rohdatei-Pfad bereits
    # VOR dem Postprocessing-Schritt (yt_dlp/downloader/common.py,
    # status='finished') - unabhaengig davon, ob dieser Schritt spaeter
    # erfolgreich ist. Nur dieser eine, fuer DIESEN Aufruf spezifische Pfad
    # (lokale Closure, kein globaler Zustand) wird im Fehlerfall bereinigt.
    raw_downloaded_path: Optional[str] = None

    def _capture_raw_downloaded_path(status: Dict[str, Any]) -> None:
        nonlocal raw_downloaded_path
        if status.get("status") == "finished" and status.get("filename"):
            raw_downloaded_path = status["filename"]

    hooked_ydl_opts = {
        **ydl_opts,
        "progress_hooks": [
            *ydl_opts.get("progress_hooks", []),
            _capture_raw_downloaded_path,
        ],
    }

    try:
        download_info = await enhanced_processor.download_executor.extract_info_async(
            url, hooked_ydl_opts, download=True
        )

        downloaded_file = enhanced_processor.download_executor.find_downloaded_file(
            download_info, ydl_opts
        )
        if not downloaded_file or not Path(downloaded_file).exists():
            raise DownloadError("Heruntergeladene Datei nach Download nicht gefunden")

        size_kb = Path(downloaded_file).stat().st_size // 1024
        logger.info(
            f"✅ [DL] Single-Download erfolgreich:\n"
            f"   Datei : {Path(downloaded_file).name}\n"
            f"   Größe : {size_kb} KB"
        )

        # ── Metadaten ─────────────────────────────────────────────────────────
        track_metadata = {
            "filepath": downloaded_file,
            "title": video_info.get("title"),
            "artist": video_info.get("artist") or video_info.get("uploader"),
            "id": video_info.get("id"),
            "uploader": video_info.get("uploader"),
            "channel": video_info.get("channel") or video_info.get("uploader"),
            "upload_date": video_info.get("upload_date"),
            "release_year": video_info.get("release_year"),
        }
        logger.info(
            f"🚀 [META] Starte Single-Metadatenverarbeitung:\n"
            f"   Titel    : {track_metadata['title']}\n"
            f"   Artist   : {track_metadata['artist']}\n"
            f"   Uploader : {track_metadata['uploader']}\n"
            f"   Jahr     : {track_metadata.get('release_year', '?')}"
        )

        enhanced_result: MetadataResult = await call_process_single_track(
            enhanced_processor.enhanced_metadata_processor,
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
            playlist_metadata=None,
            dominant_artist=None,
        )

        if enhanced_result is None:
            logger.error("❌ [META] enhanced_result ist None")
            raise DownloadError("Processing failed: enhanced_result is None")

        if not enhanced_result.success:
            logger.error(
                f"❌ [META] Enhanced Processing fehlgeschlagen: {enhanced_result.error}"
            )
            # DL-05: process_single_track() faengt intern bereits ALLE
            # Fehler der eigentlichen Metadaten-Pipeline per except Exception
            # ab (services/metadata/enhanced_metadata_processor.py) - ein
            # hier ankommendes success=False ist damit ein deterministischer
            # Fehler in bereits abgeschlossenen, lokalen Verarbeitungs-
            # schritten (Tag-Schreiben, Bibliotheks-Move, Pipeline-Logik),
            # NICHT ein voruebergehender externer Fehler (optionale externe
            # Dienste wie Genius/MusicBrainz/Last.fm degradieren dort bereits
            # graceful statt success=False auszuloesen, siehe
            # docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md
            # Abschnitt 29.3). Ein erneuter kompletter YouTube-Download
            # aendert an diesem deterministischen Fehler nichts - vorher
            # wurde trotzdem bis zu 3x der komplette Track erneut
            # heruntergeladen (DL-05).
            raise MetadataError(f"Processing failed: {enhanced_result.error}")

        # AUTOLEARN-001: externer, redundanter Auto-Learning-Aufruf entfernt.
        # process_single_track() ruft auto_learn_manager.learn_artist() intern
        # bereits fuer jeden Track auf (Schritt 19b) - inkl. derselben breiten
        # Sonderkanal-Pruefung, die hier vorher zusaetzlich (mit teils
        # abweichenden Bedingungen) dupliziert wurde. Siehe
        # docs/archive/MusicBot_ENGINEERING_BASELINE.md.

        # Flags für Log
        flags = " ".join(
            filter(
                None,
                [
                    "📜" if enhanced_result.lyrics else "",
                    "🖼️" if enhanced_result.cover_embedded else "",
                    "💾" if enhanced_result.from_cache else "",
                    (
                        "🎯"
                        if getattr(enhanced_result, "artist_source", "")
                        == "artist_map_fallback"
                        else ""
                    ),
                    (
                        "📺"
                        if getattr(enhanced_result, "artist_source", "")
                        == "youtube_parsed"
                        else ""
                    ),
                ],
            )
        )

        logger.info(
            f"✅ [META] Single-Track erfolgreich verarbeitet:\n"
            f"   Artist     : '{enhanced_result.artist}' (Src: {enhanced_result.artist_source})\n"
            f"   Titel      : '{enhanced_result.title}'\n"
            f"   Album      : '{enhanced_result.album}'\n"
            f"   Jahr       : {enhanced_result.year}\n"
            f"   Genre-Src  : {enhanced_result.genre_source}\n"
            f"   Library    : {enhanced_result.library_path}\n"
            f"   Flags      : {flags or '–'}"
        )

        # ARCH-004/P-3: gemeinsame Integrationsschicht statt inline
        # dupliziertem DownloadResult(...)-Aufbau - siehe
        # services/downloader/metadata_result_translator.py
        return build_single_track_result(
            enhanced_result,
            enhanced_processor_ref=enhanced_processor,
        )

    except DownloadError:
        # DL-03/DL-05: bereits klassifiziert (z.B. MetadataError oben) -
        # Klassifikation unveraendert an enhanced_download_with_retry()
        # weiterreichen, NICHT erneut in ein generisches DownloadError
        # verpacken (das wuerde die Retry-Entscheidung dort wieder auf
        # "unbekannt" zuruecksetzen und die Klassifikation wirkungslos
        # machen).
        enhanced_processor.session_stats["failed_downloads"] += 1
        if raw_downloaded_path:
            cleanup_single_download_artifact(
                Path(raw_downloaded_path),
                getattr(enhanced_processor.config, "DOWNLOAD_DIR", None),
                logger,
            )
        raise

    except YoutubeDLError as e:
        # DL-03: roher yt-dlp-Fehler aus extract_info_async(download=True)
        # oben - an der Boundary klassifizieren (siehe _classify_ytdlp_error()),
        # bevor er enhanced_download_with_retry() erreicht.
        enhanced_processor.session_stats["failed_downloads"] += 1
        if raw_downloaded_path:
            cleanup_single_download_artifact(
                Path(raw_downloaded_path),
                getattr(enhanced_processor.config, "DOWNLOAD_DIR", None),
                logger,
            )
        raise _classify_ytdlp_error(e) from e

    except Exception as e:
        enhanced_processor.session_stats["failed_downloads"] += 1
        if raw_downloaded_path:
            cleanup_single_download_artifact(
                Path(raw_downloaded_path),
                getattr(enhanced_processor.config, "DOWNLOAD_DIR", None),
                logger,
            )
        raise DownloadError(f"Single-Download fehlgeschlagen: {e}")
