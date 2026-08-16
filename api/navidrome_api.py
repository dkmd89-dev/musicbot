# api/navidrome_api.py

import re
import asyncio
import logging
from typing import Any, Dict, List
from urllib.parse import quote
import subprocess
from datetime import datetime
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

    @classmethod
    def format_full_status_message(cls, stats: dict) -> str:
        """
        Erzeugt eine vollständig MarkdownV2-maskierte Statusmeldung des Navidrome-Servers.
        """
        from config import Config
        from emoji import EMOJI
        from helfer.markdown_helfer import escape_md_v2

        last_scan_str = stats.get("last_scan")
        scanning = stats.get("scanning", False)

        last_scan_formatted = "Nicht verfügbar"
        if last_scan_str:
            try:
                dt_object = datetime.fromisoformat(last_scan_str.rstrip("Z"))
                # Normale Formatierung des Datums, ohne Escape-Sequenzen
                last_scan_formatted = dt_object.strftime("%d.%m.%Y, %H:%M:%S")
            except (ValueError, TypeError):
                last_scan_formatted = last_scan_str

        status_emoji = EMOJI["sync"] if scanning else EMOJI["success"]
        status_text = "Läuft noch..." if scanning else "Abgeschlossen"

        version_escaped = escape_md_v2(stats.get("server_version", "Unbekannt"))
        status_text_escaped = escape_md_v2(status_text)
        artist_count_escaped = escape_md_v2(str(stats.get("artist_count", 0)))
        song_count_escaped = escape_md_v2(str(stats.get("song_count", 0)))
        genre_count_escaped = escape_md_v2(str(stats.get("genre_count", 0)))

        # Die Nachricht mit den korrekt maskierten Variablen zusammenstellen
        message = (
            f"{status_emoji} \\*Navidrome Server Status\\*\n\n"
            f"ℹ️ Version\\: {version_escaped}\n"
            f"📊 Gesamtstatus\\: {status_text_escaped}\n"
            # Hier wird der gesamte formatierte String maskiert
            f"📅 Letzter Scan\\: {escape_md_v2(last_scan_formatted)}\n\n"
            f"📊 \\*Bibliotheks\\-Statistiken\\*\n"
            f"\\- 🎤 Künstler\\: {artist_count_escaped}\n"
            f"\\- 🎵 Songs\\: {song_count_escaped}\n"
            f"\\- 🎶 Genres\\: {genre_count_escaped}\n\n"
            f"🔗 \\*Webinterface\\:\\*\n"
            f"[Hier klicken]({_get_navidrome_config().NAVIDROME_URL})"
        )

        return message

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
    def count_songs_recursive(cls, directory_id: str) -> int:
        """
        Zählt rekursiv alle Songs in einem Verzeichnis anhand der API.
        """
        song_count = 0
        try:
            data = cls.make_request("getMusicDirectory", {"id": directory_id})
            directory = data.get("subsonic-response", {}).get("directory", {})
            children = directory.get("child", [])

            for item in children:
                if item.get("isDir", False):
                    song_count += cls.count_songs_recursive(item["id"])
                else:
                    song_count += 1
        except Exception as e:
            log_handler_error(
                e, context="NavidromeAPI (rekursiver Song-Zähler)", exc_info=True
            )
        return song_count

    @classmethod
    async def get_scan_status(cls) -> Dict[str, Any]:
        """Ruft den aktuellen Scan-Status von Navidrome ab."""
        log_handler_info("Abrufen des Navidrome Scan-Status...", context="NavidromeAPI")
        try:
            response = await asyncio.to_thread(cls.make_request, "getScanStatus")
            scan_status = response.get("subsonic-response", {}).get("scanStatus", {})
            log_handler_info(
                f"Scan-Status erhalten: {scan_status}", context="NavidromeAPI"
            )
            return scan_status
        except Exception as e:
            log_handler_error(
                e,
                context="NavidromeAPI (Fehler beim Abrufen des Scan-Status)",
                exc_info=True,
            )
            return {}

    @classmethod
    async def get_full_server_info(cls):
        """
        Ruft umfassende Serverinformationen von Navidrome ab.
        """
        server_info = {
            "server_version": "Unbekannt",
            "artist_count": 0,
            "song_count": 0,
            "genre_count": 0,
            "last_scan": None,
            "scanning": False,
        }
        log_handler_info(
            "Rufe vollständige Serverinformationen ab.", context="NavidromeAPI"
        )

        try:
            log_handler_debug("Frage Scan-Status ab.", context="NavidromeAPI")
            scan_status_data = await asyncio.to_thread(
                cls.make_request, "getScanStatus"
            )
            if scan_status_data.get("subsonic-response", {}).get("status") == "ok":
                scan_status = scan_status_data["subsonic-response"].get(
                    "scanStatus", {}
                )
                server_info["last_scan"] = scan_status.get("lastScan")
                server_info["scanning"] = scan_status.get("scanning", False)
                log_handler_info(
                    f"Scan-Status Antwort: {scan_status}", context="NavidromeAPI"
                )
            else:
                log_handler_warning(
                    "getScanStatus Antwort nicht ok oder 'scanStatus' nicht gefunden.",
                    context="NavidromeAPI",
                )

            log_handler_debug("Frage Künstler ab (getArtists).", context="NavidromeAPI")
            artists_data = await asyncio.to_thread(cls.make_request, "getArtists")
            if artists_data.get("subsonic-response", {}).get("status") == "ok":
                indexes = (
                    artists_data["subsonic-response"]
                    .get("artists", {})
                    .get("index", [])
                )
                total_artists = sum(len(index.get("artist", [])) for index in indexes)
                server_info["artist_count"] = total_artists
                log_handler_info(
                    f"Künstleranzahl: {total_artists}", context="NavidromeAPI"
                )
            else:
                log_handler_warning(
                    "getArtists Antwort nicht ok oder 'artists' nicht gefunden.",
                    context="NavidromeAPI",
                )

            log_handler_debug(
                "Frage Albumliste ab (getAlbumList2).", context="NavidromeAPI"
            )
            album_data = await asyncio.to_thread(
                cls.make_request,
                "getAlbumList2",
                {"type": "alphabeticalByArtist", "size": "10000"},
            )
            albums = (
                album_data.get("subsonic-response", {})
                .get("albumList2", {})
                .get("album", [])
            )
            song_count = sum(album.get("songCount", 0) for album in albums)
            server_info["song_count"] = song_count
            log_handler_info(
                f"Song-Anzahl über Albums: {song_count}", context="NavidromeAPI"
            )

            log_handler_debug("Frage Genres ab.", context="NavidromeAPI")
            genres_data = await asyncio.to_thread(cls.make_request, "getGenres")
            if genres_data.get("subsonic-response", {}).get("status") == "ok":
                genres = (
                    genres_data["subsonic-response"].get("genres", {}).get("genre", [])
                )
                server_info["genre_count"] = len(genres)
                log_handler_info(f"Genre-Anzahl: {len(genres)}", context="NavidromeAPI")
            else:
                log_handler_warning(
                    "getGenres Antwort nicht ok oder 'genres' nicht gefunden.",
                    context="NavidromeAPI",
                )

            log_handler_debug(
                "Frage Ping für Server-Version ab.", context="NavidromeAPI"
            )
            ping_data = await asyncio.to_thread(cls.make_request, "ping")
            if ping_data.get("subsonic-response", {}).get("status") == "ok":
                server_info["server_version"] = ping_data.get(
                    "subsonic-response", {}
                ).get("version", cls._auth_params["v"])
                log_handler_info(
                    f"Ping erfolgreich, Server-Version: {server_info['server_version']}.",
                    context="NavidromeAPI",
                )
            else:
                log_handler_warning("Ping Antwort nicht ok.", context="NavidromeAPI")

        except (HTTPError, ConnectionError) as e:
            log_handler_error(
                e,
                context="NavidromeAPI (Fehler beim Abrufen der vollständigen Serverinformationen)",
                exc_info=True,
            )
        except Exception as e:
            log_handler_error(
                e,
                context="NavidromeAPI (unerwarteter Fehler beim Abrufen der Serverinformationen)",
                exc_info=True,
            )

        log_handler_info(
            f"Vollständige Serverinformationen abgerufen: {server_info}",
            context="NavidromeAPI",
        )
        return server_info

    @classmethod
    def format_rescan_status_message(cls, stats: dict) -> str:
        """
        Erzeugt eine formatierte Statusmeldung für den Bibliotheks-Rescan,
        ohne die MarkdownV2-Maskierung.
        """
        from config import Config

        scan_start = stats.get("scan_start")
        scan_end = stats.get("last_scan")
        scanning = stats.get("scanning", False)

        duration = "Unbekannt"
        if scan_start and scan_end:
            try:
                from datetime import datetime

                fmt = "%Y-%m-%dT%H:%M:%S.%f%z"
                start_dt = datetime.strptime(scan_start, fmt)
                end_dt = datetime.strptime(scan_end, fmt)
                diff = end_dt - start_dt
                duration = str(diff).split(".")[0]
            except Exception:
                pass

        text = (
            f"🔄 *Bibliotheks-Rescan Übersicht*\n\n"
            f"⏳ Scanstatus: {'Läuft noch...' if scanning else 'Abgeschlossen'}\n"
            f"🕒 Dauer: {duration}\n"
            f"📅 Letzter Scan: {scan_end if scan_end else 'Nicht verfügbar'}\n\n"
            f"🎼 *Musikbibliothek*\n"
            f"• 🎤 Künstler: {stats.get('artist_count', 0)}\n"
            f"• 🎵 Songs: {stats.get('song_count', 0)}\n"
            f"• 🎶 Genres: {stats.get('genre_count', 0)}\n\n"
            f"💾 Lokale Dateien: {stats.get('local_file_count', 'Unbekannt')}\n"
            f"🔗 [Navidrome Webinterface]({_get_navidrome_config().NAVIDROME_URL})"
        )
        return text

    @classmethod
    async def test_api(cls) -> str:
        log_handler_info(
            "Teste API-Erreichbarkeit und Funktionalität.", context="NavidromeAPI"
        )
        try:
            server_version = "unbekannt"
            log_handler_debug(
                "Versuche Server-Version über getAlbumList2 zu erhalten.",
                context="NavidromeAPI",
            )
            albums_response = await asyncio.to_thread(
                cls.make_request, "getAlbumList2", {"type": "newest", "size": 1}
            )
            if (
                albums_response
                and albums_response.get("subsonic-response", {}).get("status") == "ok"
            ):
                server_version = albums_response.get("subsonic-response", {}).get(
                    "version", "unbekannt"
                )
                log_handler_debug(
                    f"Server-Version von getAlbumList2: {server_version}",
                    context="NavidromeAPI",
                )
            else:
                log_handler_debug(
                    "getAlbumList2 liefert keine Version, versuche Ping.",
                    context="NavidromeAPI",
                )
                ping_result = await asyncio.to_thread(cls.make_request, "ping")
                if (
                    ping_result
                    and ping_result.get("subsonic-response", {}).get("status") == "ok"
                ):
                    server_version = ping_result.get("subsonic-response", {}).get(
                        "version", "unbekannt"
                    )
                    log_handler_debug(
                        f"Server-Version von Ping: {server_version}",
                        context="NavidromeAPI",
                    )

            log_handler_debug(
                "Rufe aktuell spielende Titel ab.", context="NavidromeAPI"
            )
            # KORREKTUR: get_now_playing() gibt jetzt eine Liste zurück
            now_playing_list = await cls.get_now_playing()

            if not now_playing_list:
                msg = f"{EMOJI['warning']} API erreichbar \\(v{escape_md_v2(server_version)}\\) aber keine aktiven Plays\\."
                log_handler_info(
                    f"API erreichbar, aber keine aktiven Wiedergaben. Version: {server_version}",
                    context="NavidromeAPI",
                )
                return msg

            # Nimm den ersten Eintrag für die Test-API-Nachricht
            now_playing = now_playing_list[0]
            msg = (
                f"{EMOJI['success']} API voll funktionsfähig \\(v{escape_md_v2(server_version)}\\)\\n"
                f"{EMOJI['playing']} Aktueller Song: {escape_md_v2(now_playing['song']['title'])} von {escape_md_v2(now_playing['song']['artist'])} \\(Nutzer: {escape_md_v2(now_playing['user'])}\\)"
            )
            log_handler_info(
                f"API voll funktionsfähig. Aktueller Song: '{now_playing['song']['title']}' von '{now_playing['song']['artist']}'.",
                context="NavidromeAPI",
            )
            return msg
        except Exception as e:
            log_handler_error(
                e, context="NavidromeAPI (Fehler bei test_api)", exc_info=True
            )
            return f"{EMOJI['error']} API nicht erreichbar: `{escape_md_v2(str(e))}`"

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

    @classmethod
    async def get_genres(cls) -> Dict[str, Any]:
        """Ruft alle Genres ab (statische Version)."""
        log_handler_info("Rufe alle Genres ab.", context="NavidromeAPI")
        response = await asyncio.to_thread(cls.make_request, "getGenres")
        genres = {}
        if (
            "subsonic-response" in response
            and "genres" in response["subsonic-response"]
            and "genre" in response["subsonic-response"]["genres"]
        ):
            genres = response["subsonic-response"]["genres"]["genre"]
        log_handler_info(f"{len(genres)} Genres gefunden.", context="NavidromeAPI")
        return genres

    @classmethod
    async def get_indexes(cls) -> List[Dict[str, Any]]:
        """Ruft alle Indexe ab (z.B. A, B, C...)."""
        log_handler_info("Rufe alle Indexe ab.", context="NavidromeAPI")
        response = await asyncio.to_thread(cls.make_request, "getIndexes")
        indexes = (
            response.get("subsonic-response", {}).get("indexes", {}).get("index", [])
        )
        log_handler_info(f"{len(indexes)} Indexe gefunden.", context="NavidromeAPI")
        return indexes

    @classmethod
    async def get_album_list(
        cls, type: str = "newest", size: int = 100
    ) -> List[Dict[str, Any]]:
        """Ruft eine Liste von Alben basierend auf Typ (z.B. newest, frequent, random) ab."""
        log_handler_info(
            f"Rufe {size} Alben vom Typ '{type}' ab.", context="NavidromeAPI"
        )
        params = {"type": type, "size": size}
        response = await asyncio.to_thread(
            cls.make_request, "getAlbumList", params=params
        )
        albums = (
            response.get("subsonic-response", {}).get("albumList", {}).get("album", [])
        )
        log_handler_info(f"{len(albums)} Alben gefunden.", context="NavidromeAPI")
        return albums

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
    async def get_last_played(cls, count: int = 10) -> List[Dict[str, Any]]:
        """Ruft die letzten 'count' gespielten Titel ab (Nutzt getRecentSongs)."""
        log_handler_info(
            f"Rufe die letzten {count} gespielten Titel ab.", context="NavidromeAPI"
        )
        params = {"count": count}
        response = await asyncio.to_thread(
            cls.make_request, "getRecentSongs", params=params
        )
        songs = (
            response.get("subsonic-response", {}).get("recentSongs", {}).get("song", [])
        )
        log_handler_info(f"{len(songs)} letzte Titel gefunden.", context="NavidromeAPI")
        return songs

    @classmethod
    async def get_top_songs(
        cls, count: int = 10, period: str = "allTime"
    ) -> List[Dict[str, Any]]:
        """Ruft Top-Songs ab. Period kann 'allTime', 'year', 'month', 'week' sein."""
        log_handler_info(
            f"Rufe die Top {count} Songs für den Zeitraum '{period}' ab.",
            context="NavidromeAPI",
        )
        params = {"count": count, "timePeriod": period}
        response = await asyncio.to_thread(
            cls.make_request, "getTopSongs", params=params
        )
        songs = (
            response.get("subsonic-response", {}).get("topSongs", {}).get("song", [])
        )
        log_handler_info(f"{len(songs)} Top-Songs gefunden.", context="NavidromeAPI")
        return songs

    @classmethod
    async def get_top_artists(
        cls, count: int = 10, period: str = "allTime"
    ) -> List[Dict[str, Any]]:
        """Ruft Top-Künstler ab. Period kann 'allTime', 'year', 'month', 'week' sein."""
        log_handler_info(
            f"Rufe die Top {count} Künstler für den Zeitraum '{period}' ab.",
            context="NavidromeAPI",
        )
        params = {"count": count, "timePeriod": period}
        response = await asyncio.to_thread(
            cls.make_request, "getTopArtists", params=params
        )
        artists = (
            response.get("subsonic-response", {})
            .get("topArtists", {})
            .get("artist", [])
        )
        log_handler_info(
            f"{len(artists)} Top-Künstler gefunden.", context="NavidromeAPI"
        )
        return artists

    @classmethod
    async def get_period_review_data(
        cls, period: str, username: str = None
    ) -> Dict[str, Any]:
        """
        Ruft aggregierte Wiedergabedaten für einen bestimmten Zeitraum ab.
        """
        log_handler_info(
            f"Abrufen von Periodenrückblick-Daten für '{period}'. Benutzer: {username if username else 'Alle'}",
            context="NavidromeAPI",
        )

        top_songs_count = getattr(Config, "NAVIDROME_REVIEW_TOP_COUNT", 5)
        top_songs = await cls.get_top_songs(count=top_songs_count, period=period)
        top_artists = await cls.get_top_artists(count=top_songs_count, period=period)

        total_plays = sum(song.get("playCount", 0) for song in top_songs)

        review_data = {
            "period": period,
            "totalPlays": total_plays,
            "topSongs": top_songs,
            "topArtists": top_artists,
            "username": username,
        }
        log_handler_info(
            f"Periodenrückblick-Daten für '{period}' erfolgreich abgerufen. Gesamt-Wiedergaben: {total_plays}.",
            context="NavidromeAPI",
        )
        return review_data

    @classmethod
    async def search(cls, query: str) -> Dict[str, Any]:
        """Führt eine Suche durch (statische Version)."""
        log_handler_info(f"Suche nach: {query}", context="NavidromeAPI")
        params = {"query": query}
        response = await asyncio.to_thread(cls.make_request, "search3", params)
        return response.get("subsonic-response", {}).get("searchResult3", {})

    @classmethod
    def format_web_interface_url_message(cls) -> str:
        """
        Erzeugt eine MarkdownV2-formatierte Nachricht mit dem Link zum
        Navidrome Webinterface.
        """
        from helfer.markdown_helfer import escape_md_v2
        from config import Config
        from emoji import EMOJI

        escaped_url = escape_md_v2(_get_navidrome_config().NAVIDROME_URL)

        message = (
            f"{EMOJI['navidrome']} \\*Dein Navidrome Webinterface\\*\n"
            f"[Hier klicken]({_get_navidrome_config().NAVIDROME_URL})"
        )

        return message
