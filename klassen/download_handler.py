# services/downloader/download_handler.py
# -*- coding: utf-8 -*-
"""
DownloadHandler v3.0 – Vollständig transparenter Download-Pipeline-Orchestrator

Architektur:
  handle_url()           → Einstiegspunkt (YouTube-URL-Validierung)
  handle_youtube_links() → YouTube-Pipeline
  _process_single_download_result() → Metadaten-Anreicherung via EnhancedMetadataProcessor

Pipeline-Schritte (vollständig nachvollziehbar):
  1 URL-Prüfung → 2 Duplikat-Check → 3 YT-Download →
  4 Metadaten → 5 Bibliothek → 6 Zusammenfassung

CHANGELOG v3.0:
  ✅ Vollständige Transparenz – jeder Mikro-Schritt geloggt
  ✅ Granulare Telegram-Status-Updates mit Fortschrittsbalken
  ✅ Strukturierte Step-Marker in Logs: [STEP X/N] für jede Phase
  ✅ Entscheidungs-Logging: Artist-Quelle, Genre-Quelle, Cache-Entscheidung
  ✅ Fehlerkontext mit vollständigem Stack bei kritischen Fehlern
  ✅ Stats-Aggregation aus 3 unabhängigen Quellen (robust)
  ✅ Duplikat-Handling mit detaillierter Begründung
  ✅ Cover-Art-Transparenz (YouTube-Thumbnail → kein Cover)
  ✅ Konsistentes Emoji-Schema für schnelle Log-Orientierung

Spotify-Unterstützung wurde entfernt (siehe
docs/MusicBot_ARCH-020_Download_Pipeline_Characterization.md, Abschnitt
"Spotify-Entfernung") - Spotify wurde im produktiven Betrieb nicht genutzt.
"""

import asyncio
import re
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from mutagen.mp4 import MP4
from telegram import Message, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from config import Config
from cookie_handler import CookieHandler
from services.duplicate.detector import DuplicateDetector
from services.downloader.models import DuplicateEntry
from logger import get_module_logger
from services.downloader.downloader import YoutubeDownloader
from services.metadata.enhanced_metadata_processor import (
    EnhancedMetadataProcessor,
)
from services.downloader.download_result_reporter import DownloadResultReporter
from services.downloader.progress_tracker import ProgressTracker
from utils.filenamefixer import FilenameFixerTool


# ═══════════════════════════════════════════════════════════════════════════════
# URL-VALIDIERUNG (SEC: Domain-Allowlist vor yt-dlp)
# ═══════════════════════════════════════════════════════════════════════════════

# handle_url() leitete frueher JEDE nicht-Spotify http(s)://-URL ungeprueft
# an yt-dlp weiter. yt-dlp unterstuetzt hunderte Extractors und macht
# serverseitige HTTP-Requests - ohne Domain-Allowlist kann jeder Telegram-
# Nutzer, der den Bot anschreiben kann, den Server beliebige URLs abrufen
# lassen (SSRF-artiges Risiko). Nur tatsaechlich unterstuetzte YouTube-
# Domains werden akzeptiert; alles andere bekommt eine normale
# Fehlermeldung statt stillschweigend verarbeitet zu werden.
_SUPPORTED_YOUTUBE_DOMAINS = re.compile(
    r"(?:^|\.)(?:youtube\.com|youtu\.be|music\.youtube\.com)(?:/|$)",
    re.IGNORECASE,
)


def _is_supported_download_url(url: str) -> bool:
    """Prüft, ob eine URL von einer unterstützten YouTube-Domain stammt."""
    try:
        from urllib.parse import urlparse

        netloc = urlparse(url.strip()).netloc.lower()
    except Exception:
        return False
    return bool(_SUPPORTED_YOUTUBE_DOMAINS.search(netloc))


# ═══════════════════════════════════════════════════════════════════════════════
# CONCURRENCY-LIMIT (Ressourcen-Schutz)
# ═══════════════════════════════════════════════════════════════════════════════

# DownloadHandler wird pro Telegram-Update NEU instanziiert (siehe
# RichMenuHandler._create_download_handler: "Erstellt eine neue
# DownloadHandler-Instanz"). Ein Semaphore als Instanzattribut wuerde also
# NICHT prozessweit begrenzen - jede neue Instanz haette ihr eigenes,
# volles Kontingent. Config.MAX_CONCURRENT_DOWNLOADS war zwar definiert,
# wurde aber nirgends gelesen/durchgesetzt. Der Semaphore lebt daher auf
# Modul-Ebene, geteilt über alle DownloadHandler-Instanzen hinweg.
_download_semaphore: Optional[asyncio.Semaphore] = None


def _get_download_semaphore(config) -> asyncio.Semaphore:
    global _download_semaphore
    if _download_semaphore is None:
        max_concurrent = getattr(config, "MAX_CONCURRENT_DOWNLOADS", 3) or 3
        _download_semaphore = asyncio.Semaphore(max_concurrent)
    return _download_semaphore


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE-KONSTANTEN
# ═══════════════════════════════════════════════════════════════════════════════

class _YT:
    """YouTube-Pipeline Schritt-Definitionen"""
    TOTAL = 6
    URL_CHECK    = (1, "URL & Format prüfen")
    DUPE_CHECK   = (2, "Duplikat-Check")
    DOWNLOAD     = (3, "Audio-Download")
    METADATA     = (4, "Metadaten anreichern")
    LIBRARY      = (5, "Bibliothek organisieren")
    SUMMARY      = (6, "Zusammenfassung")


# Emojis pro Modul für schnelle visuelle Orientierung in Logs
_MOD_EMOJI = {
    "DownloadHandler":          "📤",
    "YoutubeDownloader":        "⬇️",
    "EnhancedMetadataProcessor":"🚀",
    "DuplicateHandler":         "🔍",
    "FilenameFixerTool":        "🛠️",
    "ArtistNormalizer":         "👤",
    "GenreMapper":              "🏷️",
    "GeniusClient":             "📜",
}

# Schritt-Emojis 1–10
_STEP_EMOJI = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]


# ═══════════════════════════════════════════════════════════════════════════════
# HILFS-FUNKTION: LOG-FORMATIERUNG
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_result(result: Dict[str, Any]) -> str:
    """Formatiert Download-Ergebnis kompakt für den Log."""
    lines = [
        "┌─ Download-Ergebnis ──────────────────────",
        f"│  Erfolg      : {result.get('success')}",
        f"│  Titel       : {result.get('title', '?')}",
        f"│  Künstler    : {result.get('artist', '?')}",
        f"│  Album       : {result.get('album', '?')}",
        f"│  Jahr        : {result.get('year', '?')}",
        f"│  Library-Pfad: {result.get('library_path', result.get('final_path', '?'))}",
        f"│  Cover       : {'✅' if result.get('cover_embedded') else '❌'}",
        f"│  Lyrics      : {'✅' if result.get('lyrics_available') else '❌'}",
        f"│  Duplikat    : {'⚠️ JA' if result.get('is_duplicate') else '✅ nein'}",
        f"│  Artist-Src  : {result.get('artist_source', '?')}",
        f"│  Genre-Src   : {result.get('genre_source', '?')}",
        "└──────────────────────────────────────────",
    ]
    return "\n".join(lines)


def _progress_bar(current: int, total: int, width: int = 10) -> str:
    """Erzeugt einen ASCII-Fortschrittsbalken: ████░░░░░░ 3/6"""
    filled = round(width * current / max(total, 1))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {current}/{total}"


# ═══════════════════════════════════════════════════════════════════════════════
# HAUPT-KLASSE
# ═══════════════════════════════════════════════════════════════════════════════

class DownloadHandler:
    """
    Orchestriert den vollständigen Download-Prozess für YouTube.

    Jeder Schritt wird sowohl im Python-Log (detailliert) als auch als
    Telegram-Statusnachricht (kompakt) sichtbar gemacht.
    """

    def __init__(
        self,
        update: Update,
        config: Config,
        duplicate_detector: DuplicateDetector,
        metadata_processor: EnhancedMetadataProcessor,
        logger_factory: Optional[Callable] = None,
    ):
        self.update = update
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("DownloadHandler")

        # ── Abhängigkeiten ────────────────────────────────────────────────────
        self.logger.info("🔌 [INIT] Lade Abhängigkeiten...")

        self.cookie_handler = CookieHandler()
        self.filename_fixer = FilenameFixerTool(
            self.config, logger_factory=self.logger_factory
        )
        self.enhanced_metadata_processor = metadata_processor
        self.duplicate_detector = duplicate_detector
        self.result_reporter = DownloadResultReporter(
            logger=self.logger_factory("DownloadResultReporter")
        )

        self.logger.info("✅ [INIT] Duplikat-Handler (geteilt) verbunden")

        # ── Status / Progress ─────────────────────────────────────────────────
        self.status_msg: Optional[Message] = None
        self.progress_tracker = ProgressTracker(
            logger_factory=self.logger_factory
        )
        self.downloader = YoutubeDownloader(
            update=update,
            config=self.config,
            cookie_handler=self.cookie_handler,
        )

        self.logger.info(
            f"🚀 [INIT] DownloadHandler bereit — update_id={update.update_id}"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # STATUS-UPDATE
    # ──────────────────────────────────────────────────────────────────────────

    async def _update_status(
        self,
        step: int,
        total: int,
        text: str,
        module: str = "DownloadHandler",
        detail: str = "",
    ) -> None:
        """
        Aktualisiert Telegram-Statusnachricht und schreibt Python-Log.

        Format Telegram:
            1️⃣  ████░░░░░░ 1/6  │ URL & Format prüfen
            ⚙️  [DownloadHandler]
            detail (optional)
        """
        step_emoji = _STEP_EMOJI[step - 1] if 0 < step <= len(_STEP_EMOJI) else "➡️"
        mod_emoji  = _MOD_EMOJI.get(module, "⚙️")
        bar        = _progress_bar(step, total)

        # Python-Log
        log_line = f"[STEP {step}/{total}] {text}"
        if detail:
            log_line += f" — {detail}"
        self.logger.info(f"{mod_emoji} {log_line}")

        if not self.status_msg:
            return

        # Telegram-Nachricht
        lines = [
            f"{step_emoji}  {bar}  │ {text}",
            f"{mod_emoji}  [{module}]",
        ]
        if detail:
            lines.append(f"ℹ️  {detail}")

        try:
            await self.status_msg.edit_text("\n".join(lines))
        except TelegramError as e:
            if "Message is not modified" not in str(e):
                self.logger.warning(f"⚠️ Telegram-Status konnte nicht aktualisiert werden: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # DUPLIKAT-HANDLING
    # ──────────────────────────────────────────────────────────────────────────

    async def _check_duplicates_before_download(
        self, url: str
    ) -> Tuple[bool, Optional[DuplicateEntry], str]:
        """
        Prüft URL-basiert auf Duplikate im Cache.
        Gibt (is_duplicate, entry, type) zurück.
        """
        self.logger.info(f"🔍 [DUPE] Starte Duplikat-Prüfung für URL: {url[:80]}...")

        is_dup, entry, dup_type = self.duplicate_detector.check_for_duplicates(url=url)

        if is_dup and entry:
            self.logger.warning(
                f"🔍 [DUPE] ⚠️ DUPLIKAT GEFUNDEN:\n"
                f"   Typ       : {dup_type}\n"
                f"   Titel     : {entry.title}\n"
                f"   Künstler  : {entry.artist}\n"
                f"   Datum     : {entry.download_date.strftime('%d.%m.%Y %H:%M')}\n"
                f"   Pfad      : {entry.file_path}"
            )
        else:
            self.logger.info("🔍 [DUPE] ✅ Kein Duplikat — Download wird fortgesetzt")

        return is_dup, entry, dup_type

    async def _send_report_message(
        self, msg: str, error_log_msg: str, success_log_msg: Optional[str] = None
    ) -> None:
        """
        Sendet eine vorformatierte Nachricht über status_msg (mit Fallback
        auf update.message), fängt TelegramError. Gemeinsames Send-Muster
        für Duplikat-/Abschluss-Meldungen (ARCH-007/P-2: der eigentliche
        Telegram-Versand liegt jetzt vollständig hier statt in services/ -
        DownloadResultReporter liefert nur noch fertigen Text).
        """
        try:
            if self.status_msg:
                await self.status_msg.edit_text(msg)
            else:
                await self.update.message.reply_text(msg)
            if success_log_msg:
                self.logger.info(success_log_msg)
        except TelegramError as e:
            self.logger.error(f"{error_log_msg}{e}")

    async def _handle_duplicate_found(self, entry: DuplicateEntry, dup_type: str) -> None:
        """Baut Duplikat-Nachricht und sendet sie an den Benutzer."""
        self.logger.info(f"🔍 [DUPE] Sende Duplikat-Meldung (Typ: {dup_type})")
        msg = self.result_reporter.build_duplicate_message(entry, dup_type)
        await self._send_report_message(
            msg, "❌ [DUPE] Fehler beim Senden der Duplikat-Meldung: "
        )

    # ──────────────────────────────────────────────────────────────────────────
    # KERNMETHODE: METADATEN-ANREICHERUNG
    # ──────────────────────────────────────────────────────────────────────────

    async def _process_single_download_result(
        self, result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Guard/Pass-Through für bereits verarbeitete YouTube-Download-Ergebnisse.

        Die eigentliche Metadaten-Anreicherung geschieht für YouTube bereits
        vollständig innerhalb von services/downloader/download_utils.py,
        bevor ein Ergebnis hier ankommt (siehe
        docs/MusicBot_ARCH-020_Download_Pipeline_Characterization.md). Diese
        Methode diente historisch zusätzlich als einzige reale
        Metadaten-Verarbeitungsstelle für Spotify-Ergebnisse (entfernt) -
        die dafür nötigen Schritte D/E/G wurden mit der Spotify-Entfernung
        mitentfernt.

        Durchläuft folgende Prüfungen mit explizitem Logging:
          A) Playlist-Wrapper-Schutz
          B) Doppelverarbeitungs-Schutz (already processed)
          C) filepath-Fallback-Suche
          F) Cover-Art-Transparenz
        """
        title = result.get("title", "Unbekannt")
        self.logger.info(
            f"🚀 [PROCESS] ═══ Starte Metadaten-Anreicherung für '{title}' ═══"
        )

        try:
            # ── A: Playlist-Wrapper-Schutz ────────────────────────────────────
            if result.get("type") == "playlist":
                self.logger.info(
                    f"📋 [PROCESS-A] Playlist-Wrapper erkannt → "
                    "MetadataProcessor wird übersprungen, Rohdaten direkt weitergegeben"
                )
                return result

            # ── B: Doppelverarbeitungs-Schutz ─────────────────────────────────
            already_processed = result.get("library_path") and not result.get("filepath")
            if already_processed:
                self.logger.debug(
                    f"✅ [PROCESS-B] '{title}' bereits fertig verarbeitet "
                    f"(library_path='{result.get('library_path')}') — überspringe"
                )
                return result

            # ── C: filepath-Fallback ──────────────────────────────────────────
            if not result.get("filepath"):
                self.logger.debug(f"📂 [PROCESS-C] 'filepath' fehlt — suche Fallback...")
                fallback = (
                    result.get("filename")
                    or result.get("file_path")
                    or result.get("_filename")
                )
                if not fallback and isinstance(result.get("requested_downloads"), list):
                    entries = result["requested_downloads"]
                    if entries:
                        fallback = entries[0].get("filepath")
                        if fallback:
                            self.logger.debug(
                                f"📂 [PROCESS-C] filepath via requested_downloads gefunden: {fallback}"
                            )
                if not fallback and result.get("library_path"):
                    fallback = str(result["library_path"])
                    self.logger.debug(
                        f"📂 [PROCESS-C] filepath via library_path gesetzt: {fallback}"
                    )
                if fallback:
                    result["filepath"] = str(fallback)
                else:
                    self.logger.warning(
                        f"⚠️ [PROCESS-C] Kein filepath gefunden für '{title}' — "
                        "Verarbeitung wird trotzdem versucht"
                    )

            # ── Titel-Fallback (verhindert 'Playlist' als Titel) ──────────────
            if result.get("title") in ("Playlist", None, ""):
                echter = result.get("fulltitle") or result.get("track")
                if echter:
                    self.logger.debug(
                        f"🎵 [PROCESS-C] Titel '{result.get('title')}' → '{echter}' (fulltitle)"
                    )
                    result["title"] = echter
                    title = echter

            # ── F: Cover-Art-Transparenz ───────────────────────────────────────
            cover_bytes = result.get("cover_art")
            if cover_bytes:
                self.logger.info(
                    f"🖼️ [PROCESS-F] Cover-Art bereits im Ergebnis vorhanden "
                    f"({len(cover_bytes):,} Bytes)"
                )
            else:
                self.logger.debug(
                    "🖼️ [PROCESS-F] Kein eingebettetes Cover im Ergebnis"
                )

            return result

        except Exception as e:
            self.logger.error(
                f"❌ [PROCESS] Unerwarteter Fehler bei '{title}': {e}",
                exc_info=True,
            )
            return result

    # ──────────────────────────────────────────────────────────────────────────
    def _has_lyrics(self, file_path: Path) -> bool:
        """Prüft ob eine M4A-Datei einen Lyrics-Tag enthält."""
        try:
            if not file_path or not file_path.exists():
                return False
            return "©lyr" in MP4(file_path)
        except Exception as e:
            self.logger.debug(f"⚠️ Lyrics-Prüfung fehlgeschlagen: {e}")
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # DUPLIKAT-REGISTRIERUNG & SUCCESS-HANDLING
    # ──────────────────────────────────────────────────────────────────────────

    async def handle_single_track_success(self, result: Dict[str, Any]) -> None:
        """Registriert Download im Duplikat-Cache und sendet Abschluss-Zusammenfassung."""
        title  = result.get("title", "?")
        artist = result.get("artist", "?")
        self.logger.info(
            f"🏁 [SUCCESS] ── Single-Track abgeschlossen: '{artist} - {title}' ──"
        )

        # Duplikat-Registrierung
        try:
            url   = result.get("original_url") or result.get("url") or ""
            path  = result.get("library_path") or result.get("filepath") or ""
            if artist and title and artist not in ("?", "Unbekannt", "Unknown Artist"):
                self.duplicate_detector.register_download(
                    url=url,
                    artist=artist,
                    title=title,
                    file_path=Path(path) if path else None,
                    metadata={"artist": artist, "title": title, "album": result.get("album"), "year": result.get("year")},
                )
                self.logger.info(
                    f"📝 [SUCCESS] Im Duplikat-Cache registriert: '{artist} - {title}'"
                )
            else:
                self.logger.warning(
                    f"⚠️ [SUCCESS] Duplikat-Registrierung übersprungen "
                    f"(artist='{artist}', title='{title}')"
                )
        except Exception as e:
            self.logger.error(f"❌ [SUCCESS] Duplikat-Registrierung fehlgeschlagen: {e}", exc_info=True)

        stats     = self.result_reporter.extract_stats_from_result(result, [])
        dup_stats = getattr(self.duplicate_detector, "get_statistics", lambda: {})()
        msg = self.result_reporter.build_final_summary_message(result, stats, dup_stats)
        await self._send_report_message(
            msg,
            "❌ [SUMMARY] Fehler beim Senden: ",
            success_log_msg="✅ [SUMMARY] Abschluss-Zusammenfassung gesendet",
        )

    async def handle_playlist_success(self, results: List[dict]) -> None:
        """Abschluss-Meldung für Playlists oder Playlist-Wrapper."""
        if results and results[0].get("type") == "playlist":
            await self.handle_single_track_success(results[0])
            return

        successful = [r for r in results if r.get("success")]
        if not successful:
            self.logger.warning("🤷 [SUCCESS] Keine erfolgreichen Tracks — keine Zusammenfassung")
            return

        self.logger.info(
            f"🏁 [SUCCESS] ── Playlist abgeschlossen: "
            f"{len(successful)}/{len(results)} Tracks ──"
        )

        msg = self.result_reporter.build_playlist_summary_message(results, successful)
        await self._send_report_message(msg, "❌ Playlist-Zusammenfassung nicht gesendet: ")

    # ═══════════════════════════════════════════════════════════════════════════
    # UNIFIED URL-DISPATCHER
    # ═══════════════════════════════════════════════════════════════════════════

    async def handle_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Einstiegspunkt.
        Prüft die URL gegen die unterstützten YouTube-Domains und startet
        die YouTube-Pipeline.
        """
        url = update.message.text.strip()
        self.logger.info(
            f"📤 [DISPATCH] Neue URL empfangen: {url[:100]}"
        )

        if not _is_supported_download_url(url):
            self.logger.warning(
                f"🚫 [DISPATCH] Nicht unterstützte URL abgelehnt: {url[:100]}"
            )
            await update.message.reply_text(
                "⚠️ Diese URL wird nicht unterstützt. Bitte einen YouTube-Link senden."
            )
            return

        semaphore = _get_download_semaphore(self.config)
        async with semaphore:
            self.logger.info("📤 [DISPATCH] → YouTube-URL erkannt → YT-Pipeline")
            await self.handle_youtube_links(update, context)

    # ═══════════════════════════════════════════════════════════════════════════
    # YOUTUBE-PIPELINE
    # ═══════════════════════════════════════════════════════════════════════════

    async def handle_youtube_links(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        YouTube Download-Pipeline mit vollständigen Step-Logs.

        Schritte: URL-Prüfung → Duplikat → Download → Metadaten → Bibliothek → Zusammenfassung
        """
        self.update = update
        url = update.message.text.strip()

        self.logger.info(
            f"\n{'═'*60}\n"
            f"📤 YOUTUBE-PIPELINE GESTARTET\n"
            f"   URL      : {url}\n"
            f"   Chat-ID  : {update.effective_chat.id}\n"
            f"   Update-ID: {update.update_id}\n"
            f"{'═'*60}"
        )

        self.status_msg = await update.message.reply_text("▶️ Anfrage wird gestartet...")
        TOTAL = _YT.TOTAL

        try:
            # ── SCHRITT 1: URL-Prüfung ─────────────────────────────────────
            step, label = _YT.URL_CHECK
            await self._update_status(step, TOTAL, label, "DownloadHandler", url[:60])

            # ── SCHRITT 2: Duplikat-Check ──────────────────────────────────
            step, label = _YT.DUPE_CHECK
            await self._update_status(step, TOTAL, label, "DuplicateHandler")
            is_dup, entry, dup_type = await self._check_duplicates_before_download(url)
            if is_dup and entry:
                await self._handle_duplicate_found(entry, dup_type)
                return

            # ── SCHRITT 3: YT-Download ─────────────────────────────────────
            step, label = _YT.DOWNLOAD
            await self._update_status(step, TOTAL, label, "YoutubeDownloader")
            download_result = await self.downloader.download_audio(url)

            if not download_result:
                self.logger.error("❌ [YT-PIPELINE] download_audio() lieferte leeres Ergebnis")
                raise ValueError("Download-Ergebnis war leer oder ungültig")

            # ── SCHRITT 4: Metadaten anreichern ────────────────────────────
            step, label = _YT.METADATA
            await self._update_status(step, TOTAL, label, "EnhancedMetadataProcessor")

            results_list = download_result if isinstance(download_result, list) else [download_result]
            self.logger.info(
                f"🔢 [YT-PIPELINE] {len(results_list)} Ergebnis(se) zur Verarbeitung"
            )

            processed_results = []
            for idx, res in enumerate(results_list, 1):
                self.logger.info(
                    f"🔄 [YT-PIPELINE] Verarbeite Ergebnis {idx}/{len(results_list)}: "
                    f"'{res.get('title', '?')}'"
                )
                if not (isinstance(res, dict) and res.get("success")):
                    self.logger.warning(
                        f"⚠️ [YT-PIPELINE] Ergebnis {idx} ist fehlerhaft — übersprungen"
                    )
                    continue

                # Dateikonflikt → Duplikat
                if res.get("renamed_due_to_conflict"):
                    final_path = res.get("library_path")
                    self.logger.warning(
                        f"📄 [YT-PIPELINE] Dateikonflikt erkannt — lösche: {final_path}"
                    )
                    try:
                        if final_path and Path(final_path).exists():
                            os.remove(final_path)
                            self.logger.info(f"✅ [YT-PIPELINE] Duplikat-Datei gelöscht: {final_path}")
                    except OSError as oe:
                        self.logger.error(f"❌ [YT-PIPELINE] Löschen fehlgeschlagen: {oe}")

                    conflict_entry = DuplicateEntry(
                        title=res.get("title", "Unbekannt"),
                        artist=res.get("artist", "Unbekannt"),
                        file_path=Path(str(final_path).replace(" (1)", "")),
                        download_date=datetime.now(),
                        url=url,
                    )
                    await self._handle_duplicate_found(conflict_entry, "file_conflict")
                    return

                res["original_url"] = url
                processed = await self._process_single_download_result(res)
                processed_results.append(processed)

            # ── SCHRITT 5 & 6: Bibliothek + Zusammenfassung ────────────────
            step, label = _YT.LIBRARY
            await self._update_status(step, TOTAL, label, "FilenameFixerTool")

            step, label = _YT.SUMMARY
            await self._update_status(step, TOTAL, label, "DownloadHandler")

            if not processed_results:
                self.logger.warning("🤷 [YT-PIPELINE] Keine erfolgreichen Ergebnisse")
                return

            if len(processed_results) == 1 and processed_results[0].get("type") == "playlist":
                await self.handle_playlist_success(processed_results)
            elif len(processed_results) == 1:
                await self.handle_single_track_success(processed_results[0])
            else:
                await self.handle_playlist_success(processed_results)

            self.logger.info(
                f"{'═'*60}\n"
                f"✅ YOUTUBE-PIPELINE ABGESCHLOSSEN — {len(processed_results)} Track(s)\n"
                f"{'═'*60}"
            )

        except Exception as e:
            self.logger.error(
                f"💥 [YT-PIPELINE] Unerwarteter Fehler: {e}", exc_info=True
            )
            await self.handle_download_failure(str(e))

    # ──────────────────────────────────────────────────────────────────────────
    # FEHLER-HANDLING
    # ──────────────────────────────────────────────────────────────────────────

    async def handle_download_failure(self, error_message: str) -> None:
        """Loggt den Fehler und sendet eine verständliche Fehlermeldung an den User."""
        self.logger.error(
            f"❌ [FAILURE] Download fehlgeschlagen:\n"
            f"   Fehler: {error_message}"
        )
        text = (
            "❌ Download fehlgeschlagen\n\n"
            f"Fehler: {error_message}\n\n"
            "Mögliche Ursachen:\n"
            "• URL nicht erreichbar oder privat\n"
            "• Netzwerkproblem\n"
            "• Dateiformat nicht unterstützt"
        )
        try:
            if self.status_msg:
                await self.status_msg.edit_text(text)
            else:
                await self.update.message.reply_text(text)
        except TelegramError as te:
            self.logger.error(f"❌ Fehler beim Senden der Fehlermeldung: {te}")
