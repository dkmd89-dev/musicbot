# api/navidrome_scan_trigger.py

"""
ARCH-009 Phase 4: Kapselt die lokale Docker-/Subprocess-/Timeout-Steuerung
fuer Navidrome-Scans, getrennt von der Subsonic-API-Kommunikation in
api/navidrome_api.py (siehe docs/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md,
Abschnitt 3: execute_scan() vermischte bislang Konfigurationsvalidierung,
Subprocess-Steuerung und Telegram-Formatierung).

1:1 aus NavidromeAPI.execute_scan() ausgelagert, Verhalten unveraendert.
Bewusst NICHT Teil dieser Auslagerung: die Telegram-MarkdownV2-Formatierung
bleibt in NavidromeAPI.execute_scan() (eigener, separat zu entscheidender
Schritt, siehe ARCH-009 Phase 3 Variante D).

Log-Kontext bewusst weiterhin "NavidromeAPI" (nicht "NavidromeScanTrigger"):
api/navidrome_api.py setzt den Logger dieses Kontexts beim Modul-Import auf
ERROR-Level (nur Fehler werden protokolliert). Ein neuer Kontextname wuerde
einen neuen, nicht level-eingeschraenkten Logger erzeugen und damit
zusaetzliche INFO-/DEBUG-Log-Ausgabe verursachen - eine Verhaltensaenderung,
die dieser Schritt ausdruecklich vermeidet.
"""

import asyncio
from dataclasses import dataclass
from functools import lru_cache

from config import Config, get_config
from logger import log_handler_debug, log_handler_error, log_handler_info


@lru_cache(maxsize=1)
def _get_scan_config():
    """Cached Config-Instanz fuer Scan-Zugriffe.

    Bewusst kein Import von api.navidrome_api._get_navidrome_config(), um
    keinen Zyklus mit api.navidrome_api (das diese Klasse importiert) zu
    erzeugen - get_config() selbst ist bereits ein globaler Singleton
    (siehe config.py), daher liefern beide Caches dieselbe Config-Instanz.
    """
    return get_config()


class ScanTimeoutError(Exception):
    """Der konfigurierte Navidrome-Scan-Timeout wurde ueberschritten."""

    def __init__(self, timeout_seconds):
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Navidrome-Scan-Timeout ({timeout_seconds}s) erreicht.")


@dataclass
class ScanRunResult:
    """Rohes Ergebnis eines Scan-Subprozesslaufs, ohne Telegram-Formatierung."""

    success: bool
    returncode: int
    stdout: str
    stderr: str


class NavidromeScanTrigger:
    """
    Fuehrt den konfigurierten Navidrome-Scan-Befehl als lokalen Subprocess aus.

    Reine Prozess-/Konfigurationsverantwortung - keine Subsonic-API-
    Kommunikation, keine Telegram-Formatierung.
    """

    @classmethod
    async def run_scan(cls) -> ScanRunResult:
        if (
            not hasattr(Config, "NAVIDROME_SCAN_COMMAND")
            or not _get_scan_config().NAVIDROME_SCAN_COMMAND
        ):
            err_msg = (
                "NAVIDROME_SCAN_COMMAND ist nicht in Config definiert oder leer. "
                "Bitte definieren Sie es, um die Scan-Funktionalität zu aktivieren."
            )
            log_handler_error(
                f"Konfigurationsfehler: {err_msg}", context="NavidromeAPI"
            )
            raise AttributeError(err_msg)

        command_to_execute = _get_scan_config().NAVIDROME_SCAN_COMMAND
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

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            log_handler_error(
                f"Navidrome Scan-Timeout ({timeout} Sekunden) erreicht.",
                context="NavidromeAPI",
            )
            raise ScanTimeoutError(timeout) from None

        stdout_decoded = stdout.decode("utf-8", errors="ignore").strip()
        stderr_decoded = stderr.decode("utf-8", errors="ignore").strip()

        if process.returncode == 0:
            log_handler_info(
                f"Navidrome Scan erfolgreich. Stdout: {stdout_decoded}",
                context="NavidromeAPI",
            )
        else:
            log_handler_error(
                f"Navidrome Scan fehlgeschlagen. Return Code: {process.returncode}, Stderr: {stderr_decoded}",
                context="NavidromeAPI",
            )

        return ScanRunResult(
            success=process.returncode == 0,
            returncode=process.returncode,
            stdout=stdout_decoded,
            stderr=stderr_decoded,
        )
