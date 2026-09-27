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
docs/archive/arch/MusicBot_ARCH-020_Download_Pipeline_Characterization.md, Abschnitt
"Spotify-Entfernung") - Spotify wurde im produktiven Betrieb nicht genutzt.
"""

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

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
from services.downloader.active_downloads import ActiveDownloadRegistry
from services.downloader.download_concurrency import download_slot
from services.downloader.download_history import DownloadHistoryStore
from services.downloader import download_pipeline_core as pipeline_core
from services.metadata.enhanced_metadata_processor import (
    EnhancedMetadataProcessor,
)
from services.downloader.download_result_reporter import DownloadResultReporter
from services.downloader.progress_tracker import ProgressTracker
from utils.filenamefixer import FilenameFixerTool

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler

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

# Client Consolidation Phase D/E (Nachtrag
# docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md Abschnitt 11):
# war bis hierhin ein modulglobales asyncio.Semaphore - faktisch nur
# prozessglobal, weil bislang nur der Bot-Prozess Downloads ausführte.
# Mit dem Control-Center als zweitem, eigenständigen Download-Pfad
# (JobRegistry-Job, services/-Aufruf ohne diese Datei) würde ein
# eigenständiges Semaphore MAX_CONCURRENT_DOWNLOADS nicht mehr
# durchsetzen. Ersetzt durch services/downloader/download_concurrency.py::
# download_slot() - denselben, jetzt cross-process wirksamen Mechanismus,
# den ein künftiger Download-Job im Control-Center-Prozess ebenfalls
# aufruft. Verhalten bewusst unverändert: wartend statt Fail-Fast (siehe
# dortiger Modul-Docstring, Regel 2).


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE-KONSTANTEN
# ═══════════════════════════════════════════════════════════════════════════════


class _YT:
    """YouTube-Pipeline Schritt-Definitionen"""

    TOTAL = 6
    URL_CHECK = (1, "URL & Format prüfen")
    DUPE_CHECK = (2, "Duplikat-Check")
    DOWNLOAD = (3, "Audio-Download")
    METADATA = (4, "Metadaten anreichern")
    LIBRARY = (5, "Bibliothek organisieren")
    SUMMARY = (6, "Zusammenfassung")


# Emojis pro Modul für schnelle visuelle Orientierung in Logs
_MOD_EMOJI = {
    "DownloadHandler": "📤",
    "YoutubeDownloader": "⬇️",
    "EnhancedMetadataProcessor": "🚀",
    "DuplicateHandler": "🔍",
    "FilenameFixerTool": "🛠️",
    "ArtistNormalizer": "👤",
    "GenreMapper": "🏷️",
    "GeniusClient": "📜",
}

# Schritt-Emojis 1–10
_STEP_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


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

    # ARCH-027/F4: Klassenattribut-Fallback fuer object.__new__(DownloadHandler)
    # -konstruierte Testinstanzen (10 bestehende Testdateien umgehen
    # __init__() bewusst wegen des schweren Konstruktors, siehe z. B.
    # tests/test_download_handler_active_download_lifecycle.py) - diese
    # Instanzen erhalten error_handler nie ueber __init__(), sollen aber
    # nicht mit AttributeError abbrechen, wenn Code self.error_handler
    # liest.
    error_handler: Optional["EnhancedErrorHandler"] = None

    def __init__(
        self,
        update: Update,
        config: Config,
        duplicate_detector: DuplicateDetector,
        metadata_processor: EnhancedMetadataProcessor,
        logger_factory: Optional[Callable] = None,
        active_downloads: Optional[ActiveDownloadRegistry] = None,
        download_history: Optional[DownloadHistoryStore] = None,
        error_handler: Optional["EnhancedErrorHandler"] = None,
    ):
        self.update = update
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("DownloadHandler")
        # ARCH-027/F4: zentraler, bereits von RichMenuHandler gehaltener
        # EnhancedErrorHandler (dieselbe geteilte Instanz wie ueberall
        # sonst, siehe ARCH-027-Konsolidierung) - siehe
        # handle_youtube_links()/_process_url() fuer die konkrete
        # Verwendung (nur fuer wirklich unerwartete, sonst nirgends
        # abgefangene Fehler, nicht fuer die bereits vorhandene, breite
        # eigene Fehlerbehandlung dieser Klasse).
        self.error_handler = error_handler

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
        self.progress_tracker = ProgressTracker(logger_factory=self.logger_factory)
        # Download-Control-Center 2026-09-02: geteilte, prozessweite
        # Registry (auf RichMenuHandler, langlebig - im Gegensatz zu
        # DownloadHandler selbst, das pro Update neu instanziiert wird,
        # siehe services/downloader/active_downloads.py-Docstring).
        # self.active_download wird erst in handle_youtube_links()
        # gesetzt, sobald die URL bekannt ist - self.downloader (braucht
        # das cancel_event) wird deshalb dort (nicht mehr hier) gebaut.
        self.active_downloads = active_downloads
        self.active_download = None
        self.downloader: Optional[YoutubeDownloader] = None
        # Download-Verlauf (Folgeschritt Download-Control-Center) - analog
        # zu active_downloads: geteilte, langlebige Instanz von aussen
        # injiziert, siehe services/downloader/download_history.py.
        self.download_history = download_history

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
        mod_emoji = _MOD_EMOJI.get(module, "⚙️")
        bar = _progress_bar(step, total)

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
                self.logger.warning(
                    f"⚠️ Telegram-Status konnte nicht aktualisiert werden: {e}"
                )

    async def _on_playlist_progress(self, tracker) -> None:
        """
        Nutzer-Wunsch 2026-09-02 (Playlist-Progress-State): Callback für
        `YoutubeDownloader`/`_process_playlist_download()`
        (services/downloader/ - Telegram-frei). Erhält den `ProgressTracker`
        selbst (reiner Zustand: current_item/completed_items/
        processed_items/total_items, kein vorformatierter Text) und baut
        daraus die reichhaltigere Playlist-Fortschrittsmeldung für Schritt 3
        (Audio-Download):

            3️⃣  █████░░░░░ 3/6  │ Audio-Download

            ⬇️ Aktuell
            03 - Trackname

            ✅ Abgeschlossen
            01 - Track 1
            02 - Track 2

            ⬇️  [YoutubeDownloader]

        Bewusst NICHT über `_update_status()` (dessen einzeiliges
        `detail`-Feld für diese mehrzeilige Darstellung nicht passt) -
        nutzt aber dieselben Modul-Helfer (`_progress_bar`/`_STEP_EMOJI`/
        `_MOD_EMOJI`) für ein konsistentes Erscheinungsbild. Die
        throttling-Entscheidung (max. 1 Update pro `update_interval`,
        siehe `ProgressTracker.compute_progress_message()`) liegt bereits
        beim Aufrufer in services/ - hier wird bei jedem tatsächlichen
        Aufruf direkt gesendet.
        """
        if not self.status_msg:
            return

        step, label = _YT.DOWNLOAD
        step_emoji = _STEP_EMOJI[step - 1]
        mod_emoji = _MOD_EMOJI.get("YoutubeDownloader", "⚙️")
        bar = _progress_bar(step, _YT.TOTAL)

        lines = [f"{step_emoji}  {bar}  │ {label}"]

        if tracker.current_item:
            lines += ["", "⬇️ Aktuell", tracker.current_item]

        if tracker.completed_items:
            # Nur die letzten paar zeigen, damit die Nachricht bei langen
            # Playlists (z.B. 15+ Tracks) uebersichtlich bleibt.
            max_shown = 8
            shown = tracker.completed_items[-max_shown:]
            lines += ["", "✅ Abgeschlossen"]
            if len(tracker.completed_items) > max_shown:
                lines.append(f"… ({len(tracker.completed_items) - max_shown} weitere)")
            lines += shown

        lines += ["", f"{mod_emoji}  [YoutubeDownloader]"]

        self.logger.debug(
            f"{mod_emoji} [STEP {step}/{_YT.TOTAL}] {label} — "
            f"{tracker.processed_items}/{tracker.total_items} "
            f"(aktuell: {tracker.current_item or '-'})"
        )

        try:
            await self.status_msg.edit_text("\n".join(lines))
        except TelegramError as e:
            if "Message is not modified" not in str(e):
                self.logger.warning(
                    f"⚠️ Telegram-Status (Playlist-Fortschritt) konnte nicht "
                    f"aktualisiert werden: {e}"
                )

    # ──────────────────────────────────────────────────────────────────────────
    # DUPLIKAT-HANDLING
    # ──────────────────────────────────────────────────────────────────────────

    async def _probe_artist_title_for_duplicate_check(
        self, url: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Leichtgewichtiger yt-dlp-Vorab-Abruf (download=False), NUR um
        Artist/Titel für check_for_duplicates() zu ermitteln.

        P1-Fund (Post-Baseline-v4 Health & Risk Audit, Finding 1):
        check_for_duplicates() wurde produktiv bisher ausschließlich mit
        url= aufgerufen - die Content-/Parser-/Library-Fallback-Ebenen in
        DuplicateDetector waren dadurch vor dem eigentlichen Download nie
        erreichbar (z.B. dieselbe Aufnahme unter einer anderen Video-ID
        erneut hochgeladen). Kostet einen zusätzlichen yt-dlp-Netzwerk-
        Roundtrip pro Download-Versuch (bewusste, freigegebene
        Kosten/Nutzen-Entscheidung).

        Schlägt der Abruf fehl oder handelt es sich um eine Playlist-URL
        (kein einzelner Songtitel), wird (None, None) zurückgegeben - die
        URL-Ebene in check_for_duplicates() bleibt davon unberührt, es
        wird nichts blockiert.

        Client Consolidation Phase D/E: reine Delegation an
        services/downloader/download_pipeline_core.py (Move, siehe dortigen
        Modul-Docstring) - identische Signatur/Verhalten, damit bestehende
        Tests, die diese Methode direkt aufrufen oder patchen, unveraendert
        funktionieren. `getattr(self, "config", None)` statt `self.config`
        (wie active_downloads/downloader/download_history in dieser Klasse):
        die try/except-Huelle in probe_artist_title_for_duplicate_check()
        faengt ein fehlendes Config-Attribut nur ab, wenn der Zugriff selbst
        INNERHALB dieser Huelle liegt - ein direkter `self.config`-Zugriff
        hier im Aufrufer (vor dem Funktionsaufruf ausgewertet) wuerde bei
        Test-Instanzen ohne echten Konstruktor (object.__new__(), siehe
        tests/test_download_handler_youtube_pipeline_failure_reporting.py)
        stattdessen unkontrolliert durchschlagen - Charakterisierungsfund
        dieser Extraktion, keine beabsichtigte Verhaltensaenderung.
        """
        return await pipeline_core.probe_artist_title_for_duplicate_check(
            self.downloader, getattr(self, "config", None), url, self.logger
        )

    async def _check_duplicates_before_download(
        self, url: str
    ) -> Tuple[bool, Optional[DuplicateEntry], str]:
        """
        Prüft auf Duplikate: URL-Ebene immer, zusätzlich Artist/Titel/
        Parser/Library-Ebenen sofern der Vorab-Metadaten-Abruf gelang.
        Gibt (is_duplicate, entry, type) zurück.

        Client Consolidation Phase D/E: reine Delegation an
        services/downloader/download_pipeline_core.py (Move) - identische
        Signatur/Verhalten. `getattr(self, "config", None)` - siehe
        Begründung in _probe_artist_title_for_duplicate_check() oben.
        """
        return await pipeline_core.check_duplicates_before_download(
            self.duplicate_detector,
            self.downloader,
            getattr(self, "config", None),
            url,
            self.logger,
        )

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

    async def _handle_duplicate_found(
        self, entry: DuplicateEntry, dup_type: str
    ) -> None:
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
        docs/archive/arch/MusicBot_ARCH-020_Download_Pipeline_Characterization.md). Diese
        Methode diente historisch zusätzlich als einzige reale
        Metadaten-Verarbeitungsstelle für Spotify-Ergebnisse (entfernt) -
        die dafür nötigen Schritte D/E/G wurden mit der Spotify-Entfernung
        mitentfernt.

        Durchläuft folgende Prüfungen mit explizitem Logging:
          A) Playlist-Wrapper-Schutz
          B) Doppelverarbeitungs-Schutz (already processed)
          C) filepath-Fallback-Suche
          F) Cover-Art-Transparenz

        Client Consolidation Phase D/E: reine Delegation an
        services/downloader/download_pipeline_core.py (Move) - identische
        Signatur/Verhalten.
        """
        return await pipeline_core.process_single_download_result(result, self.logger)

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

    def _record_history_entry(
        self,
        *,
        url: str,
        title: str,
        artist: str,
        status: str,
        genre_ok: Optional[bool] = None,
        lyrics_ok: Optional[bool] = None,
        cover_ok: Optional[bool] = None,
        mb_ok: Optional[bool] = None,
        loudness_ok: Optional[bool] = None,
    ) -> None:
        """Schreibt einen Download-Verlaufseintrag (Download-Control-Center-
        Folgeschritt "📋 Download-Verlauf"/"🔁 Erneut versuchen", siehe
        services/downloader/download_history.py). getattr()-Zugriff analog
        zu active_downloads: bestehende Tests bypassen __init__() (siehe
        Kommentar in handle_youtube_links()) und setzen dieses Attribut
        nicht - No-op statt AttributeError, wenn kein Store injiziert
        wurde. Fehler beim Schreiben werden geloggt, aber nie propagiert -
        ein defekter Verlaufsspeicher darf niemals einen sonst
        erfolgreichen/fehlgeschlagenen Download zusätzlich zum Absturz
        bringen (gleiches Prinzip wie cleanup_single_download_artifact()).

        Die fünf *_ok-Parameter (Phase 3, P2.2, Metadata-Checkliste) bleiben
        bewusst `None` ("keine Aussage möglich"), wenn der Aufrufer kein
        DownloadResult hat (status 'cancelled'/'failed') - niemals `False`.

        Client Consolidation Phase D/E: reine Delegation an
        services/downloader/download_pipeline_core.py (Move) - identische
        Signatur/Verhalten, chat_id/download_history weiterhin über
        getattr() ermittelt (bestehende Tests bypassen __init__())."""
        download_history = getattr(self, "download_history", None)
        chat_id = getattr(getattr(self.update, "effective_chat", None), "id", None)
        pipeline_core.record_history_entry(
            download_history,
            chat_id,
            url=url,
            title=title,
            artist=artist,
            status=status,
            genre_ok=genre_ok,
            lyrics_ok=lyrics_ok,
            cover_ok=cover_ok,
            mb_ok=mb_ok,
            loudness_ok=loudness_ok,
            logger=self.logger,
        )

    async def handle_single_track_success(self, result: Dict[str, Any]) -> None:
        """Registriert Download im Duplikat-Cache und sendet Abschluss-Zusammenfassung."""
        title = result.get("title", "?")
        artist = result.get("artist", "?")
        self.logger.info(
            f"🏁 [SUCCESS] ── Single-Track abgeschlossen: '{artist} - {title}' ──"
        )

        # Verlaufseintrag NUR fuer echte Einzel-Downloads - der Playlist-
        # Wrapper (type == "playlist") delegiert ebenfalls hierher (siehe
        # handle_playlist_success() unten), besitzt aber selbst kein
        # title/artist-Feld ("?"-Platzhalter waeren sinnlos). Pro-Track-
        # Eintraege fuer Playlists entstehen stattdessen in
        # _register_playlist_track_duplicates().
        if result.get("type") != "playlist":
            self._record_history_entry(
                url=result.get("original_url") or result.get("url") or "",
                title=title,
                artist=artist,
                status="success",
                genre_ok=bool(result.get("genres")),
                lyrics_ok=bool(result.get("lyrics_available")),
                cover_ok=bool(result.get("cover_embedded")),
                mb_ok=bool(result.get("mb_ids_present")),
                loudness_ok=bool(result.get("loudness_normalized")),
            )

        # Duplikat-Registrierung (Client Consolidation Phase D/E: Move nach
        # services/downloader/download_pipeline_core.py::register_single_track_duplicate())
        url = result.get("original_url") or result.get("url") or ""
        path = result.get("library_path") or result.get("filepath") or ""
        pipeline_core.register_single_track_duplicate(
            self.duplicate_detector,
            url=url,
            artist=artist,
            title=title,
            path=path,
            album=result.get("album"),
            year=result.get("year"),
            logger=self.logger,
        )

        stats = self.result_reporter.extract_stats_from_result(result, [])
        dup_stats = getattr(self.duplicate_detector, "get_statistics", lambda: {})()
        msg = self.result_reporter.build_final_summary_message(result, stats, dup_stats)
        await self._send_report_message(
            msg,
            "❌ [SUMMARY] Fehler beim Senden: ",
            success_log_msg="✅ [SUMMARY] Abschluss-Zusammenfassung gesendet",
        )

    def _register_playlist_track_duplicates(self, tracks: List[Dict[str, Any]]) -> None:
        """
        DUP-01 + DUP-08 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md):
        handle_playlist_success() rief bisher ausschließlich
        handle_single_track_success() mit dem Playlist-Wrapper auf. Dessen
        "artist" ist strukturell immer "?" (der Wrapper besitzt kein eigenes
        Artist-Feld) - die bestehende Guard-Bedingung in
        handle_single_track_success() unterdrückte die Registrierung dadurch
        für JEDEN Playlist-Track (DUP-01), und ein pro Track gesetztes
        renamed_due_to_conflict-Signal wurde nie ausgewertet, da nur der
        Wrapper selbst geprüft wurde (DUP-08).

        Verarbeitet hier jeden tatsächlich erfolgreichen Track mit seiner
        EIGENEN Identität (Artist/Titel/URL/Library-Pfad aus `tracks[i]`,
        niemals aus dem Playlist-Wrapper). Ein Kollisions-Fund bei einem
        einzelnen Track betrifft ausschließlich diesen Track - die Schleife
        läuft für alle übrigen Tracks unverändert weiter (kein Abbruch, kein
        Einfluss auf bereits verarbeitete oder noch folgende Tracks).

        Client Consolidation Phase D/E: reine Delegation an
        services/downloader/download_pipeline_core.py (Move) - identische
        Signatur/Verhalten.
        """
        download_history = getattr(self, "download_history", None)
        chat_id = getattr(getattr(self.update, "effective_chat", None), "id", None)
        pipeline_core.register_playlist_track_duplicates(
            self.duplicate_detector, download_history, chat_id, tracks, self.logger
        )

    async def handle_playlist_success(self, results: List[dict]) -> None:
        """Abschluss-Meldung für Playlists oder Playlist-Wrapper."""
        if results and results[0].get("type") == "playlist":
            playlist_result = results[0]
            tracks = playlist_result.get("tracks", [])
            total = len(tracks)
            ok = sum(1 for t in tracks if t.get("success"))
            # FINDING-4 (docs/archive/MusicBot_FINDING_4_FORENSIC_AUDIT.md):
            # enhanced_download_with_retry() meldet für Playlists immer
            # success=True auf oberster Ebene, unabhängig vom tatsächlichen
            # Track-Ergebnis - ohne diese Prüfung zeigte
            # handle_single_track_success() auch bei 0/N erfolgreichen
            # Tracks einen "✅ ... erfolgreich"-Header. Betrifft nur den
            # Grenzfall "alle Tracks fehlgeschlagen"; die bewusst
            # akzeptierte Partial-Success-Anzeige (1..N-1 von N) bleibt
            # unverändert.
            if total > 0 and ok == 0:
                await self.handle_download_failure(
                    f"Alle {total} Tracks der Playlist sind fehlgeschlagen."
                )
                return
            self._register_playlist_track_duplicates(tracks)
            await self.handle_single_track_success(playlist_result)
            return

        successful = [r for r in results if r.get("success")]
        if not successful:
            self.logger.warning(
                "🤷 [SUCCESS] Keine erfolgreichen Tracks — keine Zusammenfassung"
            )
            return

        self.logger.info(
            f"🏁 [SUCCESS] ── Playlist abgeschlossen: "
            f"{len(successful)}/{len(results)} Tracks ──"
        )

        msg = self.result_reporter.build_playlist_summary_message(results, successful)
        await self._send_report_message(
            msg, "❌ Playlist-Zusammenfassung nicht gesendet: "
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # UNIFIED URL-DISPATCHER
    # ═══════════════════════════════════════════════════════════════════════════

    async def handle_url(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Einstiegspunkt.
        Prüft die URL gegen die unterstützten YouTube-Domains und startet
        die YouTube-Pipeline.
        """
        url = update.message.text.strip()
        self.logger.info(f"📤 [DISPATCH] Neue URL empfangen: {url[:100]}")

        if not _is_supported_download_url(url):
            self.logger.warning(
                f"🚫 [DISPATCH] Nicht unterstützte URL abgelehnt: {url[:100]}"
            )
            await update.message.reply_text(
                "⚠️ Diese URL wird nicht unterstützt. Bitte einen YouTube-Link senden."
            )
            return

        max_concurrent = getattr(self.config, "MAX_CONCURRENT_DOWNLOADS", 3) or 3
        async with download_slot(max_concurrent):
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

        self.status_msg = await update.message.reply_text(
            "▶️ Anfrage wird gestartet..."
        )
        TOTAL = _YT.TOTAL

        # Download-Control-Center 2026-09-02: Registrierung VOR dem
        # eigentlichen Download, damit "🔄 Aktive Downloads"/"❌ Abbrechen"
        # ab dem ersten Moment (schon waehrend Schritt 1/2) greifen.
        # download_type ist zunaechst eine grobe URL-Heuristik - sobald
        # yt-dlp den echten Typ kennt, korrigiert enhanced_download_with_retry()
        # ihn (siehe download_utils.py). getattr() mit Default statt
        # self.active_downloads: bestehende Tests bypassen __init__()
        # (object.__new__(), etabliertes Muster dieser Testsuite) und
        # setzen dieses Attribut nicht.
        active_downloads = getattr(self, "active_downloads", None)
        if active_downloads is not None:
            self.active_download = active_downloads.register(
                chat_id=update.effective_chat.id,
                url=url,
                download_type="playlist" if "list=" in url else "single",
            )
        # self.downloader wird nur gebaut, wenn noch keiner injiziert
        # wurde - bestehende Tests setzen handler.downloader = Mock(...)
        # VOR dem Aufruf dieser Methode (ebenfalls object.__new__()-
        # Muster) und erwarten, dass genau dieser Mock verwendet wird.
        if getattr(self, "downloader", None) is None:
            self.downloader = YoutubeDownloader(
                chat_id=update.effective_chat.id,
                update_id=update.update_id,
                config=self.config,
                cookie_handler=self.cookie_handler,
                duplicate_detector=self.duplicate_detector,
                status_callback=self._on_playlist_progress,
                active_download=self.active_download,
            )

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
                self.logger.error(
                    "❌ [YT-PIPELINE] download_audio() lieferte leeres Ergebnis"
                )
                raise ValueError("Download-Ergebnis war leer oder ungültig")

            # Download-Control-Center 2026-09-02: ein per ❌-Button
            # abgebrochener PLAYLIST-Download hat weiterhin
            # download_result["success"] == True (die vor dem Abbruch
            # fertig heruntergeladenen Tracks sind echte Erfolge) - dieser
            # Check MUSS daher vor der success-Prüfung unten laufen, sonst
            # wuerde ein abgebrochener Single-Download (success=False)
            # faelschlich als generischer Fehlschlag gemeldet, UND ein
            # abgebrochener Playlist-Download wuerde die Abbruch-Meldung
            # nie erreichen (success=True faellt sonst einfach durch).
            if download_result.get("cancelled") and not download_result.get("tracks"):
                # Nur der reine Single-/Vor-Playlist-Abbruch (keine Tracks
                # ueberhaupt begonnen) bekommt die eigene, kurze Meldung -
                # ein Playlist-Abbruch MIT bereits fertigen Tracks laeuft
                # bewusst normal weiter (Metadaten/Bibliothek/Zusammenfassung
                # fuer die echten Teilergebnisse, siehe unten - die
                # Zusammenfassung selbst macht den Abbruch dort sichtbar,
                # siehe DownloadResultReporter.build_final_summary_message()).
                await self._handle_download_cancelled()
                return

            # FINDING-4 (docs/archive/MusicBot_FINDING_4_FORENSIC_AUDIT.md): erschöpfte
            # Retries signalisieren Fehlschlag über einen Rückgabewert
            # ({"success": False, "error": ...}), nicht über eine Exception -
            # ohne diese Prüfung lief das direkt in die Ergebnis-Schleife und
            # wurde dort stillschweigend übersprungen (kein Aufruf von
            # handle_download_failure(), keine Telegram-Rückmeldung).
            if not download_result.get("success"):
                await self.handle_download_failure(
                    download_result.get("error", "Unbekannter Fehler.")
                )
                return

            # ── SCHRITT 4: Metadaten anreichern ────────────────────────────
            step, label = _YT.METADATA
            await self._update_status(step, TOTAL, label, "EnhancedMetadataProcessor")

            results_list = (
                download_result
                if isinstance(download_result, list)
                else [download_result]
            )
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

                # Dateikonflikt → Duplikat (Client Consolidation Phase D/E:
                # Move nach services/downloader/download_pipeline_core.py::
                # resolve_file_conflict_as_duplicate())
                if res.get("renamed_due_to_conflict"):
                    conflict_entry = pipeline_core.resolve_file_conflict_as_duplicate(
                        res, url, self.logger
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

            if (
                len(processed_results) == 1
                and processed_results[0].get("type") == "playlist"
            ):
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

        except asyncio.CancelledError as ce:
            # DL-08 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2G_DL06_AUDIT.md,
            # Abschnitt 6): services/downloader/download_utils.py::
            # _process_playlist_download() haengt bei einer Cancellation
            # mitten in der Playlist-Verarbeitung die bereits erfolgreich
            # abgeschlossenen Tracks als partial_playlist_results-Attribut an
            # die CancelledError, statt sie unwiederbringlich zu verlieren.
            # Hier - der einzigen Stelle mit Zugriff auf self.duplicate_detector
            # zwischen Pipeline-Layer und Handler-Layer - werden sie ueber das
            # bereits bestehende, unveraenderte _register_playlist_track_duplicates()
            # registriert. Der aktuell abgebrochene bzw. nicht erfolgreiche Track
            # ist in dieser Liste nie enthalten (siehe download_utils.py).
            # getattr() mit Default schuetzt vor einer "nackten" CancelledError
            # ohne dieses Attribut (Cancellation an anderer Stelle der Pipeline).
            # Cancellation wird NICHT unterdrueckt: re-raise erfolgt in jedem Fall.
            partial_results = getattr(ce, "partial_playlist_results", None)
            if partial_results:
                self._register_playlist_track_duplicates(partial_results)
            raise

        except Exception as e:
            self.logger.error(
                f"💥 [YT-PIPELINE] Unerwarteter Fehler: {e}", exc_info=True
            )
            await self.handle_download_failure(str(e))

        finally:
            # Download-Control-Center 2026-09-02: laeuft bei JEDEM Ausgang
            # dieser Methode (return, Exception, normaler Abschluss) -
            # ohne dieses finally wuerde ein Chat nach einem Fehler/
            # Abbruch faelschlich dauerhaft als "aktiver Download"
            # gelten, "🔄 Aktive Downloads"/"❌ Abbrechen" blieben ohne
            # tatsaechlichen Download sichtbar.
            if active_downloads is not None:
                active_downloads.unregister(update.effective_chat.id)

    # ──────────────────────────────────────────────────────────────────────────
    # FEHLER-HANDLING
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_download_cancelled(self) -> None:
        """
        Download-Control-Center 2026-09-02: Meldung fuer einen per
        ❌-Button abgebrochenen Download OHNE bereits fertige Tracks
        (reiner Single-Abbruch, oder Playlist-Abbruch vor dem ersten
        fertigen Track) - siehe Aufrufstelle in handle_youtube_links()
        fuer den Playlist-mit-Teilergebnissen-Fall (laeuft stattdessen
        normal weiter, die Zusammenfassung selbst macht den Abbruch
        sichtbar).
        """
        self.logger.info("🛑 [YT-PIPELINE] Download abgebrochen (Nutzeranfrage)")
        self._record_history_entry(
            url=(self.update.message.text.strip() if self.update.message else ""),
            title="Unbekannt",
            artist="Unbekannt",
            status="cancelled",
        )
        text = "🛑 Download abgebrochen"
        try:
            if self.status_msg:
                await self.status_msg.edit_text(text)
            else:
                await self.update.message.reply_text(text)
        except TelegramError as te:
            self.logger.error(f"❌ Fehler beim Senden der Abbruch-Meldung: {te}")

    async def handle_download_failure(self, error_message: str) -> None:
        """Loggt den Fehler und sendet eine verständliche Fehlermeldung an den User."""
        self.logger.error(
            f"❌ [FAILURE] Download fehlgeschlagen:\n" f"   Fehler: {error_message}"
        )
        self._record_history_entry(
            url=(self.update.message.text.strip() if self.update.message else ""),
            title="Unbekannt",
            artist="Unbekannt",
            status="failed",
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
