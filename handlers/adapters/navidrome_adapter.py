# handlers/adapters/navidrome_adapter.py
# -*- coding: utf-8 -*-
"""
🎵 Navidrome Adapter für RichMenuSystem
"""

import subprocess
from logger import get_module_logger


class NavidromeAdapter:
    def __init__(self, config):
        self.config = config
        self.logger = get_module_logger("NavidromeAdapter")

    async def trigger_scan(self) -> bool:
        """Triggert Navidrome Library-Scan"""
        try:
            command = getattr(self.config, "NAVIDROME_SCAN_COMMAND", None)
            if not command:
                self.logger.warning("⚠️ NAVIDROME_SCAN_COMMAND nicht konfiguriert")
                return False

            result = subprocess.run(command.split(), capture_output=True, text=True)

            if result.returncode == 0:
                self.logger.info("✅ Navidrome-Scan gestartet")
                return True
            else:
                self.logger.error(f"❌ Scan fehlgeschlagen: {result.stderr}")
                return False

        except Exception as e:
            self.logger.error(f"❌ Navidrome-Scan-Fehler: {e}")
            return False
