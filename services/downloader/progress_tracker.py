# services/downloader/progress_tracker.py
import asyncio
from datetime import datetime
from typing import List, Optional, Callable


class ProgressTracker:
    """
    Verfolgt den Fortschritt von langlaufenden Aufgaben und berechnet die
    Fortschritts-Nachricht. Sendet selbst nichts mehr (ARCH-007/P-2:
    services/ hat keine Telegram-Abhängigkeit mehr) - der Aufrufer ist
    dafür verantwortlich, den von compute_progress_message() gelieferten
    Text zu versenden, falls er nicht None ist.

    Nutzer-Wunsch 2026-09-02 (Playlist-Progress-State-Erweiterung, keine
    Neuimplementierung): drei getrennte Verantwortlichkeiten statt einer
    einzigen, blind hochgezählten Zahl:

        set_current_item(name)   → aktuell heruntergeladenes Element setzen
        mark_completed(name)     → Element als abgeschlossen verbuchen
        compute_progress_message() → Text aus dem aktuellen Zustand erzeugen

    `processed_items` zählt ab sofort ausschließlich tatsächlich über
    mark_completed() abgeschlossene Elemente (vorher: wurde bei JEDEM
    compute_progress_message()-Aufruf blind um 1 erhöht, unabhängig davon,
    ob überhaupt ein Element fertig war - zu grob für eine echte
    Playlist-Fortschrittsanzeige mit mehreren Aufrufen pro Track). Die
    bestehende Drosselung (update_interval) und die Abschlussbedingung
    (processed_items == total_items) bleiben unverändert - nur die
    Semantik von processed_items wurde geschärft, nicht die Kontrollogik.

    `completed_items` hält die Namen aller bisher abgeschlossenen Elemente
    in Reihenfolge - reiner Zustand, keine Formatierung. Die konkrete,
    Telegram-spezifische Darstellung (Fortschrittsbalken, Emoji-Sektionen
    wie "⬇️ Aktuell"/"✅ Abgeschlossen") bleibt bewusst Aufgabe der
    aufrufenden Schicht (handlers/klassen) - services/ bleibt dadurch
    weiterhin frei von Telegram-Formatierung.
    """

    def __init__(
        self,
        total_items: int = 1,
        logger_factory: Optional[Callable] = None,
    ):
        self.total_items = total_items
        self.processed_items = 0
        self.last_update_time = datetime.now()
        self.start_time = datetime.now()
        self.update_interval = 5  # Sekunden
        self.current_item = ""
        self.completed_items: List[str] = []

        # ➡️ Custom logger integration mit Dependency Injection
        self.logger = (
            logger_factory("progress_tracker")
            if logger_factory
            else self._get_default_logger()
        )
        self.logger.debug(f"ProgressTracker initialisiert für {total_items} Items.")

    def _get_default_logger(self):
        """Fallback-Logger falls keine Factory übergeben wurde"""
        import logging

        logger = logging.getLogger("progress_tracker")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def compute_progress_message(self, message: str = None) -> Optional[str]:
        """
        Berechnet die Fortschritts-Nachricht, aber nicht zu häufig (Drossel-
        Intervall), um Spam zu vermeiden. Gibt den Text zurück, wenn er
        gesendet werden soll, sonst None (Intervall noch nicht erreicht) -
        der Aufrufer entscheidet selbst, ob/wie er sendet.

        Erhöht `processed_items` NICHT mehr selbst (siehe Klassen-Docstring)
        - das übernimmt jetzt ausschließlich mark_completed(). Ein Aufrufer,
        der pro Element mehrfach compute_progress_message() aufruft (z.B.
        für Zwischen-Status wie "lädt herunter..."), zählt das Element
        dadurch nicht mehrfach.
        """
        now = datetime.now()
        time_diff = (now - self.last_update_time).total_seconds()

        if time_diff > self.update_interval or self.processed_items == self.total_items:
            if not message:
                if self.processed_items > 0:
                    elapsed = (now - self.start_time).total_seconds()
                    eta = (elapsed / self.processed_items) * (
                        self.total_items - self.processed_items
                    )
                    message = (
                        f"⏳ Fortschritt: {self.processed_items}/{self.total_items} "
                        f"({int(self.processed_items / self.total_items * 100)}%) | "
                        f"ETA: {eta:.1f}s"
                    )
                    if self.current_item:
                        message += f" | {self.current_item}"
                else:
                    message = f"⏳ Fortschritt: {self.processed_items}/{self.total_items} (0%)"
                    if self.current_item:
                        message += f" | {self.current_item}"

            # ➡️ Custom logger integration
            self.logger.debug(f"Fortschritts-Update berechnet: {message}")
            self.last_update_time = now
            return message

        return None

    def set_current_item(self, item_name: str) -> None:
        """Setzt den Namen des aktuell verarbeiteten Elements."""
        self.current_item = item_name
        # ➡️ Custom logger integration
        self.logger.debug(f"Aktuelles Item gesetzt: {item_name}")

    def mark_completed(self, item_name: str) -> None:
        """
        Verbucht <item_name> als abgeschlossen: hängt den Namen an
        completed_items an und leitet processed_items daraus ab (Anzahl
        tatsächlich abgeschlossener Elemente, siehe Klassen-Docstring) -
        nicht mehr die Anzahl der compute_progress_message()-Aufrufe.
        """
        self.completed_items.append(item_name)
        self.processed_items = len(self.completed_items)
        # ➡️ Custom logger integration
        self.logger.debug(
            f"Element abgeschlossen: '{item_name}' "
            f"({self.processed_items}/{self.total_items})"
        )

    def cleanup(self) -> None:
        """
        ProgressTracker haelt keine eigenen freizugebenden Ressourcen (nur
        Zaehler/Zeitstempel). Existiert, damit EnhancedDownloadProcessor.cleanup()
        (DownloadCoordinator-Protocol, services/downloader/download_utils.py)
        gefahrlos self.tracker.cleanup() aufrufen kann - vorher fehlte diese
        Methode komplett, ein AttributeError waere die Folge gewesen, sobald
        init_tracker() jemals tatsaechlich aufgerufen wird.
        """
        self.logger.debug("ProgressTracker cleanup (keine eigenen Ressourcen)")


def progress_hook(
    tracker: ProgressTracker, d: dict, logger_factory: Optional[Callable] = None
):
    """Hook für yt-dlp, um den Download-Status zu melden."""
    logger = (
        logger_factory("progress_tracker")
        if logger_factory
        else ProgressTracker._get_default_logger(None)
    )

    if d["status"] == "finished":
        # ➡️ Custom logger integration
        logger.info(f"Download abgeschlossen: {d['filename']}")
    elif d["status"] == "error":
        # ➡️ Custom logger integration
        logger.error(
            f"Download-Fehler im Hook: {d['filename']} - {d.get('error', 'Unbekannt')}"
        )


def track_performance(func, logger_factory: Optional[Callable] = None):
    """
    Ein Dekorator, um die Ausführungszeit einer asynchronen Funktion zu messen.
    """
    logger = (
        logger_factory("progress_tracker")
        if logger_factory
        else ProgressTracker._get_default_logger(None)
    )

    async def wrapper(*args, **kwargs):
        start = asyncio.get_event_loop().time()
        result = await func(*args, **kwargs)
        end = asyncio.get_event_loop().time()

        # ➡️ Custom logger integration
        logger.info(
            f"⏱️ Die Funktion '{func.__name__}' hat {end - start:.2f} Sekunden benötigt."
        )

        return result

    return wrapper
