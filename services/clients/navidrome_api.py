# services/clients/navidrome_api.py

import re
import asyncio
import logging
from typing import Any, Dict, List
from urllib.parse import quote
import subprocess
from pathlib import Path
import requests
from requests.exceptions import HTTPError, ConnectionError
from config import Config
from logger import (
    log_handler_error,
    log_handler_info,
    log_handler_debug,
    log_handler_warning,
    get_module_logger,
)

from config import get_config
from functools import lru_cache

# ===== LOGGER AUF ERROR SETZEN (nur Fehler protokollieren) =====
_navidrome_logger = get_module_logger("NavidromeAPI")
_navidrome_logger.logger.setLevel(logging.ERROR)


@lru_cache(maxsize=1)
def _get_navidrome_config():
    """Cached Config-Instanz für Navidrome-Zugriffe"""
    return get_config()


_CREDENTIAL_QUERY_PARAM_RE = re.compile(r"([?&][up]=)[^&\s]*")


def _scrub_credentials(text: str) -> str:
    """
    Entfernt u=/p=-Query-Parameter (Subsonic-Auth) aus einem String.

    requests.Response.raise_for_status() sowie die von requests/urllib3
    ausgeloesten Connection-/Request-Exceptions formatieren ihre
    Fehlermeldung u.a. als "... for url: <response.url>" bzw. betten die
    vollstaendige Request-URL in ihre eigene str()-Repraesentation ein.
    Da full_params (u/p im Klartext) als params= an requests.get()
    uebergeben wird, landet das Navidrome-Passwort dadurch unmaskiert im
    Exception-String - unabhaengig von der bereits vorhandenen
    Maskierung der Erfolgsfall-Logzeile weiter oben.
    """
    if not text:
        return text
    return _CREDENTIAL_QUERY_PARAM_RE.sub(r"\1***", text)


class NavidromeAPI:
    """
    Kapselt alle Interaktionen mit der Subsonic-API von Navidrome:
    Authentifizierung, URL-Erstellung, asynchrone API-Anfragen.

    ARCH-009 Phase 8: reiner externer Integrationsadapter, verschoben nach
    services/clients/ (aus api/navidrome_api.py, 1:1 übernommen). Enthält
    ausschließlich echte Navidrome-Subsonic-API-Kommunikation - keine
    Telegram-Präsentation (seit ARCH-009 Phase 5), keine fachliche
    Orchestrierung (liegt in den Consumern), keine lokale Subprocess-/
    Docker-Steuerung. `execute_scan()` ist bewusst NICHT Teil dieser
    Klasse - bleibt als eigenständiger Rest in `api/navidrome_api.py`
    (delegiert an `NavidromeScanTrigger`, keine echte API-Kommunikation,
    siehe docs/MusicBot_ARCH-009_Phase8_Zielverschiebung_ServicesClients_Analyse.md).

    ARCH-009 Phase 7: instanziierbar mit injizierbarer Config (DI) statt
    einer rein statischen Klasse. `NavidromeAPI()` ohne Argumente verhält
    sich unverändert wie zuvor (nutzt dieselbe globale Config-Singleton-
    Instanz über `_get_navidrome_config()`). `_auth_params` wird in
    `__init__()` gebaut (pro Instanz) statt beim Modul-Import als
    Klassenattribut - die zurückgegebenen Werte sind identisch, da
    `NAVIDROME_USER`/`NAVIDROME_PASS` `@property`s auf `Config` sind, die
    live aus der Umgebung lesen.

    `NAVIDROME_REQUEST_TIMEOUT` und `Config.mask_sensitive()` bleiben
    bewusst an die globale `Config`-Klasse gebunden (nicht an
    `self.config`) - unverändert seit vor der Phase-7-Migration, da für
    die DI-Umstellung nur `_auth_params`/`NAVIDROME_URL` tatsächlich
    instanzspezifisch werden mussten.
    """

    def __init__(self, config=None):
        self.config = config or _get_navidrome_config()
        self._auth_params = {
            "u": self.config.NAVIDROME_USER,
            "p": self.config.NAVIDROME_PASS,
            "v": "1.16.1",
            "c": "telegram-bot",
            "f": "json",
        }

    def _build_url(self, endpoint: str) -> str:
        log_handler_debug(
            f"Erstelle URL für Endpunkt: {endpoint}", context="NavidromeAPI"
        )
        url = self.config.NAVIDROME_URL
        if not url:
            raise ValueError("NAVIDROME_URL ist nicht konfiguriert!")
        return f"{url.rstrip('/')}/rest/{quote(endpoint)}.view"

    def make_request(self, endpoint, params=None):
        """Führt eine HTTP-Anfrage an die Navidrome API aus."""
        url = self._build_url(endpoint)
        full_params = {**self._auth_params, **(params or {})}

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
            safe_msg = _scrub_credentials(str(http_err))
            log_handler_error(
                f"Fehler bei HTTP-Anfrage an Navidrome API ({endpoint}): "
                f"{safe_msg} für URL: {url}",
                context="NavidromeAPI",
            )
            # Weder das Original-Objekt weiterreichen (raise http_err) noch
            # exc_info=True/`from http_err` verwenden: requests haengt die
            # vollstaendige Request-URL (inkl. Klartext-Passwort aus
            # full_params) sowohl in die Exception-Message als auch in jede
            # daraus formatierte Traceback-/Chaining-Ausgabe ein - `from
            # None` verhindert, dass ein spaeteres exc_info=True beim
            # Aufrufer das Original-Objekt (und damit das Passwort) doch
            # noch ausgibt. Kein Aufrufer unterscheidet nach Exception-Typ
            # (repo-weit geprueft), daher ist RuntimeError unkritisch.
            raise RuntimeError(safe_msg) from None
        except ConnectionError as conn_err:
            safe_msg = _scrub_credentials(str(conn_err))
            log_handler_error(
                f"Verbindungsfehler zur Navidrome API ({endpoint}): {safe_msg}",
                context="NavidromeAPI",
            )
            raise RuntimeError(safe_msg) from None
        except Exception as err:
            safe_msg = _scrub_credentials(str(err))
            log_handler_error(
                safe_msg,
                context=f"NavidromeAPI (unerwarteter Fehler bei Anfrage an {endpoint})",
            )
            # exc_info=True bewusst entfernt: haette hier denselben Effekt
            # wie oben beschrieben (Traceback des Original-`err` haengt
            # dessen unmaskierte str()-Repraesentation an, auch wenn die
            # geloggte `msg` selbst bereits sicher ist).
            raise RuntimeError(safe_msg) from None

    async def check_connection(self) -> bool:
        """Überprüft, ob die Navidrome API erreichbar ist."""
        log_handler_info(
            "Überprüfe Verbindung zur Navidrome API.", context="NavidromeAPI"
        )
        try:
            response = await asyncio.to_thread(self.make_request, "ping")
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

    async def get_artists(self) -> List[Dict[str, Any]]:
        """Ruft eine Liste aller Künstler ab."""
        log_handler_info("Rufe alle Künstler ab.", context="NavidromeAPI")
        response = await asyncio.to_thread(self.make_request, "getArtists")
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
    async def get_now_playing(self) -> List[Dict[str, Any]]:
        """
        Ruft ALLE aktuell spielenden Titel und die zugehörigen Nutzer ab.
        Gibt eine Liste von Wiedergabe-Wörterbüchern zurück.
        """
        # KEINE log_handler_info mehr – still, wenn keine aktiven Plays
        response = await asyncio.to_thread(self.make_request, "getNowPlaying")

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

    async def search(self, query: str) -> Dict[str, Any]:
        """Führt eine Suche durch."""
        log_handler_info(f"Suche nach: {query}", context="NavidromeAPI")
        params = {"query": query}
        response = await asyncio.to_thread(self.make_request, "search3", params)
        return response.get("subsonic-response", {}).get("searchResult3", {})
