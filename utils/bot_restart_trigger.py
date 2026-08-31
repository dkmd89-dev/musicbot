# utils/bot_restart_trigger.py
# -*- coding: utf-8 -*-
"""
POST-ARCH-009 P-1: Kapselt die lokale systemd-Prozesssteuerung fuer den
Bot-Neustart, getrennt von der Telegram-Praesentation in
handlers/admin/bot_restart_handler.py (siehe
docs/archive/post-arch/MusicBot_POST-ARCH-009_P1_BotRestart_Analyse.md).

1:1 aus BotRestartHandler._trigger_restart() ausgelagert, Verhalten
unveraendert: weiterhin synchroner subprocess.run()-Aufruf (kein Wechsel auf
asyncio.create_subprocess_exec - das waere eine Verhaltensaenderung und war
nicht Teil dieser Extraktion).
"""

import subprocess

from logger import get_module_logger

logger = get_module_logger("BotRestartHandler")


class BotRestartTrigger:
    """
    Fuehrt einen `sudo systemctl restart <service>`-Neustart als lokalen
    Subprocess aus.

    Reine Prozessverantwortung - keine Telegram-Praesentation, keine
    Berechtigungspruefung (liegt beim Aufrufer in handlers/).
    """

    @staticmethod
    def trigger_restart(service_name: str) -> None:
        """
        Ruft `sudo systemctl restart <service_name>` auf.

        Voraussetzung: Der Bot-User hat NOPASSWD-Recht fuer dieses Kommando:
            robin ALL=(ALL) NOPASSWD: /bin/systemctl restart bot
        """
        try:
            logger.warning("🔄 Starte: sudo systemctl restart %s", service_name)
            result = subprocess.run(
                ["sudo", "systemctl", "restart", service_name],
                check=True,
                timeout=15,
                capture_output=True,
                text=True,
            )
            # Hierhin gelangt der Code nur, wenn systemctl nicht den eigenen Prozess
            # beendet (z. B. bei einem anderen Service). Im Normalfall wird der
            # Prozess durch den restart beendet, bevor diese Zeile erreicht wird.
            logger.info("✅ systemctl restart abgeschlossen: %s", result.stdout)
        except subprocess.CalledProcessError as e:
            logger.error(
                "❌ systemctl restart fehlgeschlagen (RC=%s): %s",
                e.returncode,
                e.stderr,
            )
        except FileNotFoundError:
            logger.error(
                "❌ 'sudo' oder 'systemctl' nicht gefunden. "
                "Prüfe ob systemd verfügbar ist."
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(
                "❌ Unerwarteter Fehler beim Neustart: %s", e, exc_info=True
            )
