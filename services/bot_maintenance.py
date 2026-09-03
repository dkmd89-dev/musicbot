# services/bot_maintenance.py
# -*- coding: utf-8 -*-
"""
MaintenanceModeStore – JSON-basierter Persistenz-Speicher für den
Bot-Wartungsmodus ("🛠️ Ein-/Ausschalten über Telegram-Inline-Buttons",
Folgeschritt zu handlers/admin/bot_restart_handler.py).

Architektur-Hintergrund (siehe docs/MusicBot_TELEGRAM_MENU_SYSTEM.md):
Ein echtes Stoppen des Bot-Prozesses (systemctl stop) würde ihn für
Telegram unerreichbar machen - es gäbe dann keine Möglichkeit, ihn per
Inline-Button wieder einzuschalten, weil der Prozess, der den Klick
empfangen müsste, gar nicht mehr liefe. Wartungsmodus ist deshalb bewusst
kein echtes An/Aus des Prozesses (der läuft immer weiter, per systemd
`Restart=always` ohnehin dauerhaft am Leben gehalten), sondern ein
persistiertes Feature-Flag: Admins/Owner nutzen den Bot im Wartungsmodus
unveraendert weiter (sonst kein Weg zurueck zum Ausschalten), alle
anderen Nutzer bekommen an jedem Einstiegspunkt eine Wartungsmeldung
statt der eigentlichen Funktion.

Reine Persistenzlogik ohne Telegram-Bezug, struktureller Zwilling zu
services/downloader/download_history.py (atomares Schreiben: write-tmp +
Path.replace(), analog INV-02). Datei unter data/ (nicht cache/) - folgt
derselben, bereits etablierten Konvention wie data/module_logger_config.json
(handlers/enhanced_logger_menu_handler.py) und data/user_data.json
(handlers/menu/rich_menu_handler.py): fester, projektrelativer Pfad ohne
eigenes Config-Attribut, da diese Dateien Anwendungszustand statt Cache
sind.
"""

import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from logger import get_module_logger

_DEFAULT_STATE_FILE = "data/maintenance_mode.json"


@dataclass
class MaintenanceState:
    active: bool = False
    changed_at: Optional[str] = None  # ISO-Format
    changed_by_user_id: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MaintenanceState":
        return cls(
            active=bool(data.get("active", False)),
            changed_at=data.get("changed_at"),
            changed_by_user_id=data.get("changed_by_user_id"),
        )


class MaintenanceModeStore:
    """Verwaltet den persistenten Wartungsmodus-Zustand (ein einzelnes
    JSON-Dokument, kein Verlauf) - Default bei fehlender/korrupter Datei:
    NICHT aktiv (Bot arbeitet normal), damit ein beschaedigter/geloeschter
    Zustand niemals versehentlich alle Nutzer aussperrt."""

    def __init__(self, state_file: str = _DEFAULT_STATE_FILE, logger: Optional[Any] = None):
        self.logger = logger or get_module_logger("MaintenanceModeStore")
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()
        self.logger.info(
            f"🛠️ MaintenanceModeStore initialisiert: {self.state_file} "
            f"(aktiv={self._state.active})"
        )

    def _load(self) -> MaintenanceState:
        try:
            if self.state_file.exists():
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return MaintenanceState.from_dict(data)
        except Exception as e:
            self.logger.warning(
                f"⚠️ Fehler beim Laden des Wartungsmodus-Zustands - "
                f"Fallback auf 'nicht aktiv': {e}"
            )
        return MaintenanceState(active=False)

    def _save(self) -> None:
        try:
            self._write_json_atomic(self.state_file, self._state.to_dict())
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Speichern des Wartungsmodus-Zustands: {e}")

    @staticmethod
    def _write_json_atomic(path: Path, data: dict) -> None:
        """Schreibt JSON atomar (write-tmp -> rename), analog zu
        DownloadHistoryStore/DuplicateCache (INV-02)."""
        tmp_path = path.with_suffix(f".tmp_{int(time.time() * 1000)}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path.replace(path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def is_active(self) -> bool:
        return self._state.active

    def set_active(self, active: bool, changed_by_user_id: Optional[int] = None) -> None:
        self._state = MaintenanceState(
            active=active,
            changed_at=datetime.now().isoformat(),
            changed_by_user_id=changed_by_user_id,
        )
        self._save()
        self.logger.warning(
            f"🛠️ Wartungsmodus {'AKTIVIERT' if active else 'DEAKTIVIERT'} "
            f"von User {changed_by_user_id}"
        )

    def get_state(self) -> MaintenanceState:
        return self._state
