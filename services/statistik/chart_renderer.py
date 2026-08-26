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
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Union

import matplotlib

# Backend fest auf "Agg" pinnen, BEVOR pyplot importiert wird: ohne dieses
# Pinning waehlt matplotlib das Backend anhand der Laufzeitumgebung (z.B.
# TkAgg, falls DISPLAY gesetzt ist). Ein GUI-Backend wie TkAgg ist nicht fuer
# den Aufruf aus einem Nicht-Haupt-Thread ausgelegt - bereits ein einzelner
# to_thread()-Aufruf fuehrt dort zu einem Prozessabsturz (SIGABRT, Tcl-Fehler
# "main thread is not in main loop"), empirisch nachgewiesen im Rahmen des
# AE-10-Audits. "Agg" ist der matplotlib-Standardweg fuer nicht-interaktives,
# thread-faehiges Rendering und aendert nichts am PNG-Output.
matplotlib.use("Agg")

import matplotlib.pyplot as plt

from logger import get_module_logger


class ChartRenderer:
    """Rendert Statistik-Dicts (aus StatisticsCalculator) als PNG-Balkendiagramme."""

    # Modul-/prozessweiter Lock: matplotlib.pyplot fuehrt die "aktuelle
    # Figure" als globalen, geteilten Zustand (nicht pro ChartRenderer-
    # Instanz). plt.tight_layout()/plt.savefig() unten operieren implizit
    # auf dieser globalen "aktuellen Figure" (plt.gcf()), nicht auf einer
    # explizit uebergebenen Figure-Referenz. Ohne diesen Lock koennen zwei
    # gleichzeitig laufende create_chart()-Aufrufe (z.B. aus zwei parallelen
    # asyncio.to_thread()-Worker-Threads) sich gegenseitig die "aktuelle
    # Figure" ueberschreiben - empirisch nachgewiesen im Rahmen des
    # AE-10-Audits: Thread A hat dabei das Diagramm von Thread B gespeichert.
    # Ein Lock pro Instanz wuerde NICHT ausreichen, da der geschuetzte
    # Zustand (pyplot) prozessweit und nicht instanzgebunden ist.
    _render_lock = threading.Lock()

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

        # Ab hier wird der globale pyplot-Zustand (aktuelle Figure, rcParams)
        # beruehrt - siehe Erklaerung bei _render_lock oben.
        with self._render_lock:
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
                self.charts_dir
                / f"top_{chart_type}_{stats['period']}_{safe_username}.png"
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
