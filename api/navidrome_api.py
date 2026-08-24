# api/navidrome_api.py

import re
import asyncio
import logging
from typing import Any, Dict, List
from urllib.parse import quote
import subprocess
from pathlib import Path
import requests
from telegram.constants import ParseMode
from requests.exceptions import HTTPError, ConnectionError
from config import Config
from logger import (
    log_handler_error,
    log_handler_info,
    log_handler_debug,
    log_handler_warning,
    get_module_logger,
)
from emoji import EMOJI
from helfer.markdown_helfer import escape_md_v2

from config import get_config
from functools import lru_cache

# ===== LOGGER AUF ERROR SETZEN (nur Fehler protokollieren) =====
_navidrome_logger = get_module_logger("NavidromeAPI")
_navidrome_logger.logger.setLevel(logging.ERROR)


@lru_cache(maxsize=1)
def _get_navidrome_config():
    """Cached Config-Instanz für Navidrome-Zugriffe"""
    return get_config()


class NavidromeAPI:
    """
    Eine Klasse zur Kapselung aller Interaktionen mit der Subsonic-API von Navidrome.
    Sie verwaltet die Authentifizierung, das Erstellen von URLs und die Durchführung
    von asynchronen API-Anfragen.
    """

    # Authentifizierungsparameter und API-Basis-URL
    _auth_params = {
        "u": _get_navidrome_config().NAVIDROME_USER,
        "p": _get_navidrome_config().NAVIDROME_PASS,
        "v": "1.16.1",
        "c": "telegram-bot",
        "f": "json",
    }

    @staticmethod
    def _build_url(endpoint: str) -> str:
        log_handler_debug(
            f"Erstelle URL für Endpunkt: {endpoint}", context="NavidromeAPI"
        )
        from config import Config

        config = Config()
        url = config.NAVIDROME_URL
        if not url:
            raise ValueError("NAVIDROME_URL ist nicht konfiguriert!")
        return f"{url.rstrip('/')}/rest/{quote(endpoint)}.view"

    @classmethod
    def make_request(cls, endpoint, params=None):
        """Führt eine HTTP-Anfrage an die Navidrome API aus."""
        url = cls._build_url(endpoint)
        full_params = {**cls._auth_params, **(params or {})}

        safe_params = {
            **full_params,
            "u": Config.mask_sensitive(full_params.get("u", "")),
            "p": Config.mask_sensitive(full_params.get("p", "")),
        }
        log_handler_info(
            f"Sende Anfrage an URL: {url}, mit Params: {safe_params}",
            context="NavidromeAPI",
        )

        try:
            response = requests.get(
                url,
                params=full_params,
                timeout=getattr(Config, "NAVIDROME_REQUEST_TIMEOUT", 15),
            )
            response.raise_for_status()

            log_handler_debug(
                f"Antwort erhalten, Status: {response.status_code}, Inhalt (gekürzt): {str(response.json())[:200]}...",
                context="NavidromeAPI",
            )
            return response.json()
        except HTTPError as http_err:
            log_handler_error(
                f"Fehler bei HTTP-Anfrage an Navidrome API ({endpoint}): {http_err} für URL: {url}",
                context="NavidromeAPI",
            )
            raise
        except ConnectionError as conn_err:
            log_handler_error(
                f"Verbindungsfehler zur Navidrome API ({endpoint}): {conn_err}",
                context="NavidromeAPI",
            )
            raise
        except Exception as err:
            log_handler_error(
                err,
                context=f"NavidromeAPI (unerwarteter Fehler bei Anfrage an {endpoint})",
                exc_info=True,
            )
            raise

    @classmethod
    async def check_connection(cls) -> bool:
        """Überprüft, ob die Navidrome API erreichbar ist."""
        log_handler_info(
            "Überprüfe Verbindung zur Navidrome API.", context="NavidromeAPI"
        )
        try:
            response = await asyncio.to_thread(cls.make_request, "ping")
            is_ok = response.get("subsonic-response", {}).get("status") == "ok"
            log_handler_info(f"Verbindung 'ok': {is_ok}", context="NavidromeAPI")
            return is_ok
        except Exception as e:
            log_handler_error(
                e,
                context="NavidromeAPI (Verbindungstest fehlgeschlagen)",
                exc_info=True,
            )
            return False

    @classmethod
    async def execute_scan(cls) -> tuple[bool, str]:
        """Führt einen Navidrome-Scan aus."""
        log_handler_info("Starte Navidrome Scan-Prozess.", context="NavidromeAPI")
        try:
            if (
                not hasattr(Config, "NAVIDROME_SCAN_COMMAND")
                or not _get_navidrome_config().NAVIDROME_SCAN_COMMAND
            ):
                err_msg = (
                    "NAVIDROME_SCAN_COMMAND ist nicht in Config definiert oder leer. "
                    "Bitte definieren Sie es, um die Scan-Funktionalität zu aktivieren."
                )
                log_handler_error(
                    f"Konfigurationsfehler: {err_msg}", context="NavidromeAPI"
                )
                raise AttributeError(err_msg)

            command_to_execute = _get_navidrome_config().NAVIDROME_SCAN_COMMAND
            timeout = getattr(Config, "NAVIDROME_SCAN_TIMEOUT", 300)

            if isinstance(command_to_execute, list):
                command_to_execute = " ".join(command_to_execute)
                log_handler_info(
                    "NAVIDROME_SCAN_COMMAND war eine Liste, wurde für subprocess_shell in String umgewandelt.",
                    context="NavidromeAPI",
                )

            if not isinstance(command_to_execute, str):
                err_msg = "NAVIDROME_SCAN_COMMAND muss ein String sein, auch nach der Konvertierung."
                log_handler_error(f"Typfehler: {err_msg}", context="NavidromeAPI")
                raise TypeError(err_msg)

            log_handler_info(
                f"Starte Navidrome Scan mit Befehl: '{command_to_execute}' und Timeout: {timeout}s",
                context="NavidromeAPI",
            )

            process = await asyncio.create_subprocess_shell(
                command_to_execute,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            log_handler_debug(
                f"Unterprozess gestartet (PID: {process.pid}), warte auf Beendigung.",
                context="NavidromeAPI",
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )

            stdout_decoded = stdout.decode("utf-8", errors="ignore").strip()
            stderr_decoded = stderr.decode("utf-8", errors="ignore").strip()

            if process.returncode == 0:
                message = f"{EMOJI['scan']} Scan erfolgreich: \n```{escape_md_v2(stdout_decoded)}```"
                log_handler_info(
                    f"Navidrome Scan erfolgreich. Stdout: {stdout_decoded}",
                    context="NavidromeAPI",
                )
                return True, message
            else:
                message = f"{EMOJI['error']} Scan fehlgeschlagen: \n```{escape_md_v2(stderr_decoded)}```"
                log_handler_error(
                    f"Navidrome Scan fehlgeschlagen. Return Code: {process.returncode}, Stderr: {stderr_decoded}",
                    context="NavidromeAPI",
                )
                return False, message
        except asyncio.TimeoutError:
            log_handler_error(
                f"Navidrome Scan-Timeout ({timeout} Sekunden) erreicht.",
                context="NavidromeAPI",
            )
            return (
                False,
                f"{EMOJI['warning']} Scan dauert länger als {timeout} Sekunden \\– bitte im Log prüfen\\.",
            )
        except Exception as e:
            log_handler_error(
                e, context="NavidromeAPI (unerwarteter Fehler beim Scan)", exc_info=True
            )
            return (
                False,
                f"{EMOJI['error']} Unerwarteter Fehler: `{escape_md_v2(str(e))}`",
            )

    @classmethod
    async def get_artists(cls) -> List[Dict[str, Any]]:
        """Ruft eine Liste aller Künstler ab."""
        log_handler_info("Rufe alle Künstler ab.", context="NavidromeAPI")
        response = await asyncio.to_thread(cls.make_request, "getArtists")
        artists = []
        if (
            "subsonic-response" in response
            and "artists" in response["subsonic-response"]
            and "index" in response["subsonic-response"]["artists"]
        ):
            for index_entry in response["subsonic-response"]["artists"]["index"]:
                if "artist" in index_entry:
                    artists.extend(index_entry["artist"])
        log_handler_info(f"{len(artists)} Künstler gefunden.", context="NavidromeAPI")
        return artists

    # ======================================================================
    # KORREKTUR: get_now_playing gibt jetzt eine LISTE aller aktiven
    # Wiedergaben zurück, nicht nur die erste.
    # KEINE INFO-LOGS MEHR – NUR FEHLER WERDEN PROTOKOLLIERT
    # ======================================================================
    @classmethod
    async def get_now_playing(cls) -> List[Dict[str, Any]]:
        """
        Ruft ALLE aktuell spielenden Titel und die zugehörigen Nutzer ab.
        Gibt eine Liste von Wiedergabe-Wörterbüchern zurück.
        """
        # KEINE log_handler_info mehr – still, wenn keine aktiven Plays
        response = await asyncio.to_thread(cls.make_request, "getNowPlaying")

        all_playing_data = []

        if (
            "subsonic-response" in response
            and "nowPlaying" in response["subsonic-response"]
        ):
            entries = response["subsonic-response"]["nowPlaying"].get("entry", [])

            # Subsonic gibt bei nur einem Eintrag ein Objekt statt einer Liste zurück
            if not isinstance(entries, list):
                entries = [entries]

            for entry in entries:
                song_info = entry.get("song", entry)
                user = entry.get("username", "Unbekannter Nutzer")

                if isinstance(song_info, dict):
                    now_playing_data = {
                        "song": {
                            "title": song_info.get("title", "N/A"),
                            "artist": song_info.get("artist", "N/A"),
                            "album": song_info.get("album", "N/A"),
                            "id": song_info.get("id", "N/A"),
                        },
                        "user": user,
                        "player": entry.get("playerName", "N/A"),
                    }
                    all_playing_data.append(now_playing_data)

        # Auch hier KEINE Meldung mehr, wenn keine Daten vorhanden
        return all_playing_data

    @classmethod
    async def search(cls, query: str) -> Dict[str, Any]:
        """Führt eine Suche durch (statische Version)."""
        log_handler_info(f"Suche nach: {query}", context="NavidromeAPI")
        params = {"query": query}
        response = await asyncio.to_thread(cls.make_request, "search3", params)
        return response.get("subsonic-response", {}).get("searchResult3", {})
