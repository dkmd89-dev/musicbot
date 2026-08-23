# services/statistik/chart_renderer.py
# -*- coding: utf-8 -*-
"""
ChartRenderer – rendert Top-Artists/Songs-Statistiken als PNG-Balkendiagramm.

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich matplotlib-Rendering vorbereiteter Statistik-Dicts.
  - KEINE Statistik-Berechnung, KEIN Datei-Zugriff auf Rohdaten.

Einziger Ort im Repository mit einer matplotlib-Abhängigkeit.

Extrahiert aus services/statistik_service.py (ARCH-003, P-6) - 1:1
übernommene Logik, keine Verhaltensänderung.
"""

import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

import matplotlib.pyplot as plt

from logger import get_module_logger


class ChartRenderer:
    """Rendert Statistik-Dicts (aus StatisticsCalculator) als PNG-Balkendiagramme."""

    def __init__(self, charts_dir: Union[str, Path], logger=None):
        self.charts_dir = Path(charts_dir)
        self.logger = logger or get_module_logger("ChartRenderer")

    def _sanitize_username(self, username: str) -> str:
        return re.sub(r"[^\w\-_\. ]", "_", username)

    def create_chart(
        self, stats: Dict[str, Any], chart_type: str = "songs"
    ) -> Optional[Path]:
        """Erstellt ein horizontales Balkendiagramm aus den übergebenen `stats`."""
        username = stats.get("navidrome_username", "allgemein")
        safe_username = self._sanitize_username(username)

        self.logger.debug(
            f"🎨 Starte Diagramm-Erstellung für: {chart_type} ({stats['period']}) für '{username}'"
        )

        data_key = f"top_{chart_type}"
        if chart_type == "artists":
            data_key = "top_artists"
        elif chart_type == "songs":
            data_key = "top_songs"

        data = stats.get(data_key, [])
        if not data:
            self.logger.warning(
                f"⚠️ Keine Daten für Diagramm-Typ '{chart_type}' (key: {data_key}) verfügbar."
            )
            return None

        labels = [item[0] for item in data][::-1]
        values = [item[1] for item in data][::-1]

        plt.style.use("dark_background")
        fig, ax = plt.subplots(figsize=(10, 7))

        color = "skyblue" if chart_type == "songs" else "lightgreen"
        bars = ax.barh(labels, values, color=color)

        for bar in bars:
            ax.text(
                bar.get_width() + 0.1,
                bar.get_y() + bar.get_height() / 2,
                f"{bar.get_width()}",
                va="center",
                color="white",
                fontsize=9,
            )

        ax.set_xlabel("Wiedergaben", color="white")
        title_type = "Künstler" if chart_type == "artists" else "Songs"
        ax.set_title(
            f"Top {len(labels)} {title_type} ({stats['period'].capitalize()}) - {username}",
            color="white",
        )

        plt.setp(ax.get_yticklabels(), color="white", rotation=0)
        ax.set_xlim(right=max(values) * 1.1)

        filepath = (
            self.charts_dir / f"top_{chart_type}_{stats['period']}_{safe_username}.png"
        )
        plt.tight_layout()

        try:
            plt.savefig(filepath, dpi=100)
            self.logger.info(f"✅ Diagramm erfolgreich erstellt: {filepath}")
            return filepath

        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Speichern des Diagramms: {e}", exc_info=True
            )
            return None

        finally:
            plt.close(fig)
