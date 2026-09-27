# services/statistik/play_history_repository.py
# -*- coding: utf-8 -*-
"""
PlayHistoryRepository – Persistenz des Wiedergabeverlaufs pro Navidrome-Benutzer.

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich Lesen/Schreiben/Bereinigen der JSON-Verlaufsdateien.
  - KEINE Business-Statistik-Berechnung, KEIN externer API-Zugriff,
    KEIN Chart-Rendering.

Extrahiert aus services/statistik_service.py (ARCH-003, P-6) - 1:1
übernommene Logik, keine Verhaltensänderung.
"""

import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from logger import get_module_logger


class PlayHistoryRepository:
    """Liest/schreibt/bereinigt die Wiedergabeverlauf-JSON-Dateien pro Benutzer."""

    def __init__(self, history_dir: Union[str, Path], logger=None):
        self.history_dir = Path(history_dir)
        self.logger = logger or get_module_logger("PlayHistoryRepository")

    def sanitize_username(self, username: str) -> str:
        """Bereinigt einen Benutzernamen für die Verwendung als Dateiname."""
        return re.sub(r"[^\w\-_\. ]", "_", username)

    def history_file_for_user(self, navidrome_username: str) -> Path:
        """Gibt den Pfad zur Verlaufsdatei für einen bestimmten Navidrome-Benutzer zurück."""
        safe_username = self.sanitize_username(navidrome_username)
        return self.history_dir / f"play_history_{safe_username}.json"

    def load(self, navidrome_username: str) -> List[Dict[str, Any]]:
        """Lädt den Wiedergabeverlauf für einen bestimmten Benutzer."""
        history_file = self.history_file_for_user(navidrome_username)

        if not history_file.exists():
            self.logger.debug(
                f"📄 Verlaufsdatei für '{navidrome_username}' existiert noch nicht."
            )
            return []

        try:
            if history_file.stat().st_size == 0:
                self.logger.debug(
                    f"📖 Verlaufsdatei für '{navidrome_username}' ist leer."
                )
                return []

            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
                self.logger.debug(
                    f"📖 Verlauf für '{navidrome_username}' geladen: {len(history)} Einträge"
                )
                return history

        except (json.JSONDecodeError, IOError, FileNotFoundError) as e:
            self.logger.error(
                f"❌ Konnte Verlaufsdatei ({history_file}) nicht laden: {e}",
                exc_info=True,
            )
            try:
                corrupt_file = history_file.with_suffix(
                    f".json.corrupt.{datetime.now().isoformat().replace(':', '-')}"
                )
                history_file.rename(corrupt_file)
                self.logger.warning(
                    f"Datei {history_file} war korrupt und wurde nach {corrupt_file} verschoben."
                )
            except Exception as move_e:
                self.logger.error(f"Konnte korrupte Datei nicht verschieben: {move_e}")
            return []

    def save(self, history: List[Dict[str, Any]], navidrome_username: str) -> None:
        """Speichert den Wiedergabeverlauf für einen bestimmten Benutzer."""
        history_file = self.history_file_for_user(navidrome_username)

        try:
            self._write_json_atomic(history_file, history)
            self.logger.debug(
                f"💾 Verlauf für '{navidrome_username}' gespeichert: {len(history)} Einträge"
            )

        except IOError as e:
            self.logger.error(
                f"❌ Konnte Verlaufsdatei ({history_file}) nicht speichern: {e}",
                exc_info=True,
            )

    @staticmethod
    def _write_json_atomic(path: Path, data: List[Dict[str, Any]]) -> None:
        """write-tmp + os.replace() (INV-02, Finding #17), analog zu
        DownloadHistory._write_json_atomic(). Ein Abbruch/Fehler während
        des Schreibens lässt die bisherige Verlaufsdatei unverändert; die
        Corrupt-Recovery in load() bleibt als zweite Verteidigungslinie
        bestehen. Der versteckte Temp-Name matcht nicht
        "play_history_*.json". Fehler werden nach Aufräumen der
        Temp-Datei weitergereicht (save() behandelt OSError wie bisher)."""
        tmp_path = path.with_name(f".{path.name}.tmp_{uuid.uuid4().hex}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path.replace(path)
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def cleanup_old_entries(
        self, navidrome_username: str, retention_days: Optional[int] = None
    ) -> None:
        """
        Entfernt alte Einträge für einen bestimmten Benutzer.

        `retention_days=None` liest `Config.PLAY_HISTORY_RETENTION_DAYS` zum
        Aufrufzeitpunkt (nicht beim Konstruieren) - identisch zum
        Ursprungsverhalten in statistik_service.py, damit z.B. ein
        nachträgliches `monkeypatch.setattr(Config, "PLAY_HISTORY_RETENTION_DAYS", ...)`
        weiterhin wirkt.
        """
        history = self.load(navidrome_username)
        if not history:
            return

        if retention_days is None:
            from config import Config

            retention_days = Config.PLAY_HISTORY_RETENTION_DAYS

        cutoff = datetime.now() - timedelta(days=retention_days)

        cleaned_history = [
            entry
            for entry in history
            if datetime.fromisoformat(entry.get("timestamp", "1970-01-01T00:00:00"))
            >= cutoff
        ]

        removed_count = len(history) - len(cleaned_history)
        if removed_count > 0:
            self.save(cleaned_history, navidrome_username)
            self.logger.info(
                f"🗑️ {removed_count} alte Einträge für '{navidrome_username}' entfernt "
                f"(älter als {retention_days} Tage)."
            )
