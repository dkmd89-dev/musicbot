# services/downloader/download_pipeline_core.py
# -*- coding: utf-8 -*-
"""
Telegram-freie Download-Pipeline-Bausteine (Client Consolidation Phase
D/E, Nachtrag docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md
Abschnitt 11).

Reiner Move aus `klassen/download_handler.py::DownloadHandler` — KEINE
Verhaltensänderung. Diese Funktionen waren dort bereits Telegram-frei
(kein Zugriff auf `self.update`/`self.status_msg`/Telegram-Objekte),
lagen aber als private Instanzmethoden vor und waren dadurch nicht ohne
eine zweite, parallele Implementierung vom Control-Center wiederverwendbar
(Nutzervorgabe: "keine parallele Business-Logik", "keine zweite
Download-Implementierung").

`klassen/download_handler.py` bleibt der alleinige Aufrufer für den
Telegram-Pfad — seine gleichnamigen privaten Methoden delegieren jetzt
hierhin (dünne Wrapper, identische Signaturen, damit bestehende Tests,
die diese Methoden direkt aufrufen oder per `unittest.mock` patchen,
unverändert funktionieren). Ein künftiger Control-Center-Download-Job
(JobRegistry-Muster, siehe `docs/FINDINGS_INDEX.md` "Downloads nicht aus
dem Control Center startbar") ruft dieselben Funktionen hier direkt auf.

Enthält u. a. die Findings DUP-01/DUP-05/DUP-06/DUP-08 und FINDING-4
(siehe docs/archive/ bzw. docs/FINDINGS_INDEX.md) - diese Fachregeln
gelten hier unverändert weiter, jetzt an einer einzigen, Telegram-freien
Stelle statt in `klassen/download_handler.py` eingebettet.
"""

from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from services.downloader.download_history import DownloadHistoryStore
from services.downloader.download_utils import is_youtube_mix_url
from services.downloader.models import DuplicateEntry
from services.duplicate.detector import DuplicateDetector


async def process_single_download_result(
    result: Dict[str, Any], logger
) -> Dict[str, Any]:
    """Guard/Pass-Through für bereits verarbeitete YouTube-Download-Ergebnisse
    (Move aus `DownloadHandler._process_single_download_result()`). Die
    eigentliche Metadaten-Anreicherung geschieht für YouTube bereits
    vollständig innerhalb von `services/downloader/download_utils.py`,
    bevor ein Ergebnis hier ankommt.

    Durchläuft folgende Prüfungen mit explizitem Logging:
      A) Playlist-Wrapper-Schutz
      B) Doppelverarbeitungs-Schutz (already processed)
      C) filepath-Fallback-Suche
      F) Cover-Art-Transparenz
    """
    title = result.get("title", "Unbekannt")
    logger.info(f"🚀 [PROCESS] ═══ Starte Metadaten-Anreicherung für '{title}' ═══")

    try:
        # ── A: Playlist-Wrapper-Schutz ────────────────────────────────────
        if result.get("type") == "playlist":
            logger.info(
                f"📋 [PROCESS-A] Playlist-Wrapper erkannt → "
                "MetadataProcessor wird übersprungen, Rohdaten direkt weitergegeben"
            )
            return result

        # ── B: Doppelverarbeitungs-Schutz ─────────────────────────────────
        already_processed = result.get("library_path") and not result.get("filepath")
        if already_processed:
            logger.debug(
                f"✅ [PROCESS-B] '{title}' bereits fertig verarbeitet "
                f"(library_path='{result.get('library_path')}') — überspringe"
            )
            return result

        # ── C: filepath-Fallback ──────────────────────────────────────────
        if not result.get("filepath"):
            logger.debug("📂 [PROCESS-C] 'filepath' fehlt — suche Fallback...")
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
                        logger.debug(
                            f"📂 [PROCESS-C] filepath via requested_downloads gefunden: {fallback}"
                        )
            if not fallback and result.get("library_path"):
                fallback = str(result["library_path"])
                logger.debug(
                    f"📂 [PROCESS-C] filepath via library_path gesetzt: {fallback}"
                )
            if fallback:
                result["filepath"] = str(fallback)
            else:
                logger.warning(
                    f"⚠️ [PROCESS-C] Kein filepath gefunden für '{title}' — "
                    "Verarbeitung wird trotzdem versucht"
                )

        # ── Titel-Fallback (verhindert 'Playlist' als Titel) ──────────────
        if result.get("title") in ("Playlist", None, ""):
            echter = result.get("fulltitle") or result.get("track")
            if echter:
                logger.debug(
                    f"🎵 [PROCESS-C] Titel '{result.get('title')}' → '{echter}' (fulltitle)"
                )
                result["title"] = echter
                title = echter

        # ── F: Cover-Art-Transparenz ───────────────────────────────────────
        cover_bytes = result.get("cover_art")
        if cover_bytes:
            logger.info(
                f"🖼️ [PROCESS-F] Cover-Art bereits im Ergebnis vorhanden "
                f"({len(cover_bytes):,} Bytes)"
            )
        else:
            logger.debug("🖼️ [PROCESS-F] Kein eingebettetes Cover im Ergebnis")

        return result

    except Exception as e:  # noqa: BLE001
        logger.error(
            f"❌ [PROCESS] Unerwarteter Fehler bei '{title}': {e}", exc_info=True
        )
        return result


async def probe_artist_title_for_duplicate_check(
    downloader, config, url: str, logger
) -> Tuple[Optional[str], Optional[str]]:
    """Leichtgewichtiger yt-dlp-Vorab-Abruf (download=False), NUR um
    Artist/Titel für check_for_duplicates() zu ermitteln (Move aus
    `DownloadHandler._probe_artist_title_for_duplicate_check()`).

    Schlägt der Abruf fehl oder handelt es sich um eine Playlist-URL
    (kein einzelner Songtitel), wird (None, None) zurückgegeben - die
    URL-Ebene in check_for_duplicates() bleibt davon unberührt, es wird
    nichts blockiert."""
    try:
        download_executor = downloader.enhanced_download_processor.download_executor
        ydl_opts = download_executor.build_ydl_opts(config)
        _is_mix = is_youtube_mix_url(url)
        if _is_mix:
            # DUP-06: verhindert, dass diese Vorab-Probe fuer eine Mix-/
            # Radio-Liste (list=RD...) faelschlich ein entries-Ergebnis
            # erhaelt und dadurch die Content-/Parser-Duplicate-Ebene
            # ueberspringt.
            ydl_opts = {**ydl_opts, "noplaylist": True}
        # H1: für Nicht-Mix-URLs teilt sich diese Probe den yt-dlp-
        # Roundtrip mit dem gleich folgenden Download (use_cache). Bei
        # Mix-URLs weichen die ydl_opts ab (noplaylist) → kein Cache.
        info = await download_executor.extract_info_async(
            url, ydl_opts, download=False, use_cache=not _is_mix
        )
        if not info or info.get("entries"):
            return None, None
        return info.get("uploader") or info.get("channel"), info.get("title")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"⚠️ [DUPE] Vorab-Metadaten-Abruf fehlgeschlagen — nur URL-Ebene aktiv: {e}"
        )
        return None, None


async def check_duplicates_before_download(
    duplicate_detector: DuplicateDetector, downloader, config, url: str, logger
) -> Tuple[bool, Optional[DuplicateEntry], str]:
    """Prüft auf Duplikate: URL-Ebene immer, zusätzlich Artist/Titel/
    Parser/Library-Ebenen sofern der Vorab-Metadaten-Abruf gelang (Move
    aus `DownloadHandler._check_duplicates_before_download()`). Gibt
    (is_duplicate, entry, type) zurück."""
    logger.info(f"🔍 [DUPE] Starte Duplikat-Prüfung für URL: {url[:80]}...")

    raw_artist, raw_title = await probe_artist_title_for_duplicate_check(
        downloader, config, url, logger
    )

    is_dup, entry, dup_type = duplicate_detector.check_for_duplicates(
        url=url, raw_artist=raw_artist, raw_title=raw_title
    )

    if is_dup and entry:
        logger.warning(
            f"🔍 [DUPE] ⚠️ DUPLIKAT GEFUNDEN:\n"
            f"   Typ       : {dup_type}\n"
            f"   Titel     : {entry.title}\n"
            f"   Künstler  : {entry.artist}\n"
            f"   Datum     : {entry.download_date.strftime('%d.%m.%Y %H:%M')}\n"
            f"   Pfad      : {entry.file_path}"
        )
    else:
        logger.info("🔍 [DUPE] ✅ Kein Duplikat — Download wird fortgesetzt")

    return is_dup, entry, dup_type


def record_history_entry(
    download_history: Optional[DownloadHistoryStore],
    chat_id: Optional[int],
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
    logger,
) -> None:
    """Schreibt einen Download-Verlaufseintrag (Move aus
    `DownloadHandler._record_history_entry()`). No-op ohne `download_history`
    oder ohne `chat_id` - Fehler beim Schreiben werden geloggt, aber nie
    propagiert (ein defekter Verlaufsspeicher darf niemals einen sonst
    erfolgreichen/fehlgeschlagenen Download zusätzlich zum Absturz bringen).

    Die fünf *_ok-Parameter bleiben bewusst `None` ("keine Aussage
    möglich"), wenn der Aufrufer kein DownloadResult hat (status
    'cancelled'/'failed') - niemals `False`."""
    if download_history is None or chat_id is None:
        return
    try:
        download_history.add_entry(
            chat_id,
            url=url or "",
            title=title or "Unbekannt",
            artist=artist or "Unbekannt",
            status=status,
            genre_ok=genre_ok,
            lyrics_ok=lyrics_ok,
            cover_ok=cover_ok,
            mb_ok=mb_ok,
            loudness_ok=loudness_ok,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ [HISTORY] Verlaufseintrag fehlgeschlagen: {e}")


def register_single_track_duplicate(
    duplicate_detector: DuplicateDetector,
    *,
    url: str,
    artist: str,
    title: str,
    path: Optional[str],
    album: Optional[str],
    year: Optional[Any],
    logger,
) -> None:
    """Registriert einen erfolgreichen Single-Track im Duplikat-Cache
    (Move aus dem entsprechenden Ausschnitt von
    `DownloadHandler.handle_single_track_success()`). Übersprungen bei
    fehlendem/Platzhalter-Artist oder -Titel (identischer Guard wie
    zuvor)."""
    if not (artist and title and artist not in ("?", "Unbekannt", "Unknown Artist")):
        logger.warning(
            f"⚠️ [SUCCESS] Duplikat-Registrierung übersprungen "
            f"(artist='{artist}', title='{title}')"
        )
        return
    try:
        duplicate_detector.register_download(
            url=url,
            artist=artist,
            title=title,
            file_path=Path(path) if path else None,
            metadata={"artist": artist, "title": title, "album": album, "year": year},
        )
        logger.info(f"📝 [SUCCESS] Im Duplikat-Cache registriert: '{artist} - {title}'")
    except Exception as e:  # noqa: BLE001
        logger.error(
            f"❌ [SUCCESS] Duplikat-Registrierung fehlgeschlagen: {e}", exc_info=True
        )


def register_playlist_track_duplicates(
    duplicate_detector: DuplicateDetector,
    download_history: Optional[DownloadHistoryStore],
    chat_id: Optional[int],
    tracks: List[Dict[str, Any]],
    logger,
) -> None:
    """DUP-01 + DUP-08: verarbeitet jeden tatsächlich erfolgreichen
    Playlist-Track mit seiner EIGENEN Identität (Move aus
    `DownloadHandler._register_playlist_track_duplicates()`). Ein
    Kollisions-Fund bei einem einzelnen Track betrifft ausschließlich
    diesen Track - die Schleife läuft für alle übrigen Tracks unverändert
    weiter."""
    for track in tracks:
        if not (isinstance(track, dict) and track.get("success")):
            continue

        artist = track.get("artist", "?")
        title = track.get("title", "?")
        library_path = track.get("library_path")

        if track.get("renamed_due_to_conflict"):
            logger.warning(
                f"📄 [PLAYLIST] Dateikonflikt erkannt (Track '{artist} - {title}') "
                f"— lösche: {library_path}"
            )
            try:
                if library_path and Path(library_path).exists():
                    os.remove(library_path)
                    logger.info(f"✅ [PLAYLIST] Duplikat-Datei gelöscht: {library_path}")
            except OSError as oe:
                logger.error(f"❌ [PLAYLIST] Löschen fehlgeschlagen: {oe}")
            # Die kollidierte Kopie repräsentiert denselben Content wie der
            # bereits vorhandene Cache-Eintrag - keine eigene Registrierung
            # nötig, andere Tracks bleiben unberührt.
            continue

        if not (
            artist and title and artist not in ("?", "Unbekannt", "Unknown Artist")
        ):
            logger.warning(
                f"⚠️ [PLAYLIST] Duplikat-Registrierung übersprungen "
                f"(artist='{artist}', title='{title}')"
            )
            continue

        try:
            duplicate_detector.register_download(
                url=track.get("url") or "",
                artist=artist,
                title=title,
                file_path=Path(library_path) if library_path else None,
                metadata={
                    "artist": artist,
                    "title": title,
                    "album": track.get("album"),
                    "year": track.get("year"),
                },
            )
            logger.info(f"📝 [PLAYLIST] Im Duplikat-Cache registriert: '{artist} - {title}'")
        except Exception as e:  # noqa: BLE001
            logger.error(
                f"❌ [PLAYLIST] Duplikat-Registrierung fehlgeschlagen "
                f"('{artist} - {title}'): {e}",
                exc_info=True,
            )

        record_history_entry(
            download_history,
            chat_id,
            url=track.get("url") or "",
            title=title,
            artist=artist,
            status="success",
            genre_ok=bool(track.get("genres")),
            lyrics_ok=bool(track.get("lyrics_available")),
            cover_ok=bool(track.get("cover_embedded")),
            mb_ok=bool(track.get("mb_ids_present")),
            loudness_ok=bool(track.get("loudness_normalized")),
            logger=logger,
        )


def resolve_file_conflict_as_duplicate(
    res: Dict[str, Any], url: str, logger
) -> DuplicateEntry:
    """Löscht die kollidierte Kopie (falls vorhanden) und baut den
    passenden `DuplicateEntry` (Move aus dem entsprechenden Ausschnitt von
    `DownloadHandler.handle_youtube_links()`, Schritt 4)."""
    final_path = res.get("library_path")
    logger.warning(f"📄 [YT-PIPELINE] Dateikonflikt erkannt — lösche: {final_path}")
    try:
        if final_path and Path(final_path).exists():
            os.remove(final_path)
            logger.info(f"✅ [YT-PIPELINE] Duplikat-Datei gelöscht: {final_path}")
    except OSError as oe:
        logger.error(f"❌ [YT-PIPELINE] Löschen fehlgeschlagen: {oe}")

    return DuplicateEntry(
        title=res.get("title", "Unbekannt"),
        artist=res.get("artist", "Unbekannt"),
        file_path=Path(str(final_path).replace(" (1)", "")),
        download_date=datetime.now(),
        url=url,
    )
