# utils/podcast_rss_manager.py
# -*- coding: utf-8 -*-
"""
Verwaltet RSS-Feeds für Spotify-Podcasts

Ermöglicht den direkten Download von Podcast-Episoden über öffentliche
RSS-Feeds - KEIN Spotify Premium erforderlich!
"""

# =============================================================================
# IMPORTS - Welche externen Bibliotheken und Module werden benötigt?
# =============================================================================

# YAML wird zum Lesen und Schreiben der Konfigurationsdatei verwendet.
# Es erlaubt eine menschenlesbare Struktur für die Podcast-Daten.
import yaml

# Reguläre Ausdrücke (hier importiert, aber aktuell nicht direkt verwendet,
# könnte für zukünftige Validierung von Feed-URLs nützlich sein).
import re

# Path aus pathlib erlaubt eine einfache und betriebssystemunabhängige
# Handhabung von Dateipfaden.
from pathlib import Path

# Typ-Annotationen für bessere Code-Qualität und IDE-Unterstützung.
# Optional: Ein Wert kann der angegebene Typ oder None sein.
# Dict, Any, List: Für komplexere Typ-Hinweise.
from typing import Optional, Dict, Any, List

# Dataclasses und field werden verwendet, um einfache Datencontainer zu erstellen,
# die automatisch Methoden wie __init__ und __repr__ erhalten.
from dataclasses import dataclass, field

# Importiert einen Logger, der speziell für dieses Modul konfiguriert ist.
# Dies ermöglicht es, alle Aktionen und Fehler in einer Logdatei oder Konsole zu verfolgen.
from logger import get_module_logger


# =============================================================================
# DATENKLASSE: PodcastRSSFeed
# Zweck: Dient als strukturierter Container für alle Informationen, die wir
#        über einen einzelnen Podcast-RSS-Feed speichern wollen.
# =============================================================================
@dataclass
class PodcastRSSFeed:
    """Container für Podcast RSS-Feed Informationen"""

    # Eindeutige ID des Podcasts auf Spotify (z.B. aus der URL: open.spotify.com/show/<ID>)
    spotify_show_id: str
    # Der Name des Podcasts (z.B. "Fest & Flauschig")
    name: str
    # Die vollständige URL zum RSS-Feed (z.B. https://example.com/feed.xml)
    rss_feed: str
    # Ist dieser Feed für die Nutzung im Programm aktiviert? (Standard: True)
    enabled: bool = True
    # Priorität, falls mehrere Feeds für dieselbe Show existieren (Standard: 1)
    priority: int = 1
    # Woher stammt diese Feed-Information? (z.B. "manual", "podcastindex", "config")
    source: str = "unknown"
    # Optionale Beschreibung des Podcasts
    description: Optional[str] = None

    def is_valid(self) -> bool:
        """
        Prüft, ob der Feed in einem gültigen Zustand ist.
        Ein Feed ist gültig, wenn er explizit aktiviert ist UND eine RSS-URL hat.
        """
        # Schritt 1: Prüfe das 'enabled' Flag.
        # Schritt 2: Prüfe, ob der 'rss_feed' String nicht leer ist (truthy).
        is_valid_feed = self.enabled and bool(self.rss_feed)
        # Gibt True zurück, wenn beide Bedingungen erfüllt sind.
        return is_valid_feed

    def get_display_name(self) -> str:
        """
        Gibt einen "schönen" Namen für den Podcast zurück.
        Falls kein 'name' gesetzt ist, wird als Fallback die Spotify-ID verwendet.
        """
        # Schritt 1: Prüfe, ob 'self.name' einen Wert hat (truthy).
        # Schritt 2: Wenn ja, gib 'self.name' zurück.
        # Schritt 3: Wenn nein, gib 'self.spotify_show_id' zurück.
        return self.name or self.spotify_show_id


# =============================================================================
# HAUPTKLASSE: PodcastRSSManager
# Zweck: Verwaltet die Sammlung aller PodcastRSSFeed-Objekte.
#        Lädt sie aus einer YAML-Datei, stellt Suchfunktionen bereit und
#        erlaubt das Hinzufügen neuer Feeds.
# =============================================================================
class PodcastRSSManager:
    """
    Verwaltet RSS-Feeds für Spotify-Podcasts

    Lädt Konfiguration aus mapping/podcast_rss_feeds.yaml und stellt
    Methoden zum Abrufen und Prüfen von RSS-Feeds bereit.
    """

    def __init__(self, mapping_dir: str = "mapping", logger_factory=None):
        """
        Initialisiert den Manager.

        Args:
            mapping_dir: Pfad zum Verzeichnis, in dem die YAML-Datei liegt.
            logger_factory: Eine optionale Funktion, um einen Logger zu erstellen.
                            Falls keine angegeben wird, wird ein Standard-Logger verwendet.
        """
        # Schritt 1: Logger einrichten.
        #            Entweder die mitgegebene Factory nutzen oder den Standard-Logger holen.
        if logger_factory:
            self.logger = logger_factory("PodcastRSSManager")
        else:
            self.logger = get_module_logger("PodcastRSSManager")

        # Schritt 2: Pfad zum Mapping-Verzeichnis als Path-Objekt speichern.
        #            Path-Objekte sind robuster als einfache Strings für Dateioperationen.
        self.mapping_dir = Path(mapping_dir)

        # Schritt 3: Ein leeres Dictionary initialisieren, das später die Feed-Objekte
        #            mit der Spotify-ID als Schlüssel speichert.
        self.feeds: Dict[str, PodcastRSSFeed] = {}

        # Schritt 4: Die Methode aufrufen, die die YAML-Datei tatsächlich einliest.
        self._load_feeds()
        self.logger.info("PodcastRSSManager wurde initialisiert.")

    def _load_feeds(self):
        """
        [PRIVATE METHODE] Lädt die RSS-Feeds aus der YAML-Datei.
        Diese Methode wird beim Start und bei einem Reload aufgerufen.
        Sie parst die YAML-Struktur und erstellt für jeden Eintrag ein PodcastRSSFeed-Objekt.
        """
        # Schritt 1: Den vollständigen Pfad zur YAML-Datei konstruieren.
        yaml_file = self.mapping_dir / "podcast_rss_feeds.yaml"
        self.logger.debug(f"Versuche RSS-Feeds zu laden aus: {yaml_file}")

        # Schritt 2: Prüfen, ob die Datei überhaupt existiert.
        if not yaml_file.exists():
            # Wenn die Datei nicht existiert, eine Warnung loggen und Methode beenden.
            self.logger.warning(
                f"⚠️ Keine podcast_rss_feeds.yaml gefunden unter {yaml_file}"
            )
            self.logger.info(f"   Erstelle die Datei unter: {yaml_file}")
            # Hier könnte man in Zukunft eine leere Datei anlegen.
            return

        # Schritt 3: Wenn die Datei existiert, versuche sie zu öffnen und zu parsen.
        try:
            # 'with open(...)' stellt sicher, dass die Datei auch bei Fehlern korrekt geschlossen wird.
            with open(yaml_file, "r", encoding="utf-8") as f:
                # yaml.safe_load parst den Inhalt der Datei in Python-Datenstrukturen (dict, list, etc.).
                # 'safe_load' ist sicherer als 'load', da es keinen beliebigen Python-Code ausführt.
                data = yaml.safe_load(f)

            # Schritt 4: Prüfen, ob die Datei Daten enthält.
            #            yaml.safe_load gibt None zurück, wenn die Datei leer ist.
            if not data:
                self.logger.warning("⚠️ podcast_rss_feeds.yaml ist leer")
                return

            # Schritt 5: Auf die erwartete Struktur zugreifen.
            #            Wir erwarten ein oberstes Dictionary mit einem Schlüssel 'podcasts'.
            podcasts = data.get("podcasts", {})
            if not podcasts:
                self.logger.warning("⚠️ Keine 'podcasts'-Sektion in der YAML-Datei gefunden.")
                return

            loaded_count = 0  # Zähler für erfolgreich geladene Feeds

            # Schritt 6: Über jeden Eintrag in der 'podcasts'-Sektion iterieren.
            #            Schlüssel = Spotify-ID, Wert = Dictionary mit den Feed-Details.
            for spotify_id, config in podcasts.items():
                self.logger.debug(f"   Verarbeite Eintrag für ID: {spotify_id}")

                # Schritt 7: Prüfen, ob der Feed laut Konfiguration aktiviert ist.
                #            Standard ist True, falls 'enabled' nicht angegeben ist.
                is_enabled = config.get("enabled", True)

                if is_enabled:
                    # Schritt 8: Ein neues PodcastRSSFeed-Objekt mit den Daten aus der Konfiguration erstellen.
                    feed = PodcastRSSFeed(
                        spotify_show_id=spotify_id,
                        name=config.get("name", "Unknown Podcast"),
                        rss_feed=config.get("rss_feed", ""),
                        enabled=is_enabled,
                        priority=config.get("priority", 1),
                        source=config.get("source", "unknown"),
                        description=config.get("description"),
                    )

                    # Schritt 9: Die Gültigkeit des erstellten Feeds prüfen.
                    #            (z.B. ob eine RSS-URL vorhanden ist)
                    if feed.is_valid():
                        # Schritt 10: Wenn gültig, zum internen 'feeds'-Dictionary hinzufügen.
                        self.feeds[spotify_id] = feed
                        loaded_count += 1
                        self.logger.debug(f"      ✅ Feed gültig und hinzugefügt: {feed.get_display_name()}")
                    else:
                        # Wenn ungültig, eine Warnung loggen.
                        self.logger.warning(
                            f"⚠️ Ungültiger Feed für {spotify_id}: RSS-URL fehlt oder Feed deaktiviert."
                        )
                else:
                    self.logger.debug(f"   ⏭️ Feed für {spotify_id} ist deaktiviert, wird übersprungen.")

            # Schritt 11: Erfolgsmeldung mit der Anzahl geladener Feeds loggen.
            self.logger.info(f"✅ {loaded_count} gültige Podcast RSS-Feeds erfolgreich geladen.")

            # Schritt 12: (Optional) Im Debug-Modus alle geladenen Feeds ausgeben.
            if self.logger.level <= 10:  # DEBUG level
                self.logger.debug("   Geladene Feeds im Detail:")
                for feed in self.feeds.values():
                    self.logger.debug(f"   📻 {feed.get_display_name()} (Quelle: {feed.source})")

        except yaml.YAMLError as e:
            # Fehlerbehandlung für den Fall, dass die YAML-Datei syntaktisch falsch ist.
            self.logger.error(f"❌ YAML-Fehler in podcast_rss_feeds.yaml: {e}")
        except Exception as e:
            # Allgemeine Fehlerbehandlung für alle anderen unerwarteten Fehler.
            self.logger.error(f"❌ Unerwarteter Fehler beim Laden der RSS-Feeds: {e}")

    def get_feed(self, spotify_show_id: str) -> Optional[PodcastRSSFeed]:
        """
        [ÖFFENTLICHE METHODE] Sucht und gibt den RSS-Feed für eine gegebene Spotify-Show-ID zurück.

        Args:
            spotify_show_id: Die Spotify-Show-ID (z.B. aus der URL extrahiert).

        Returns:
            Das PodcastRSSFeed-Objekt, wenn gefunden, sonst None.
        """
        # Schritt 1: Eingehende ID validieren. Wenn None oder leer, direkt None zurückgeben.
        if not spotify_show_id:
            self.logger.debug("get_feed: Keine ID übergeben.")
            return None

        self.logger.debug(f"get_feed: Suche nach ID '{spotify_show_id}'")

        # Schritt 2: Direkter Match. Prüfen, ob die ID exakt als Schlüssel im Dictionary existiert.
        if spotify_show_id in self.feeds:
            self.logger.debug(f"get_feed: Exakter Treffer für '{spotify_show_id}' gefunden.")
            return self.feeds[spotify_show_id]

        # Schritt 3: Teilstring-Match (Fuzzy-Matching).
        #            Falls kein direkter Treffer, über alle gespeicherten Feeds iterieren.
        self.logger.debug("get_feed: Kein exakter Treffer, versuche Teilstring-Match...")
        for feed_id, feed in self.feeds.items():
            # Prüfen, ob die gesuchte ID in der Feed-ID enthalten ist ODER umgekehrt.
            if spotify_show_id in feed_id or feed_id in spotify_show_id:
                self.logger.info(f"🔍 Teilstring-Match gefunden: '{spotify_show_id}' passt zu '{feed_id}'")
                return feed

        # Schritt 4: Wenn absolut nichts gefunden wurde.
        self.logger.debug(f"get_feed: Kein Feed für '{spotify_show_id}' gefunden.")
        return None

    def get_feed_by_name(self, name: str) -> Optional[PodcastRSSFeed]:
        """
        [ÖFFENTLICHE METHODE] Sucht einen Feed anhand des Podcast-Namens (Fuzzy-Matching).

        Args:
            name: Der Name des Podcasts (oder ein Teil davon).

        Returns:
            Das PodcastRSSFeed-Objekt, wenn gefunden, sonst None.
        """
        # Schritt 1: Eingabe validieren.
        if not name:
            return None

        # Schritt 2: Namen normalisieren: alles klein und Leerzeichen am Anfang/Ende entfernen.
        name_lower = name.lower().strip()
        self.logger.debug(f"get_feed_by_name: Suche nach Name '{name_lower}'")

        # Schritt 3: Versuche exakten Match.
        for feed in self.feeds.values():
            if feed.name.lower() == name_lower:
                self.logger.debug(f"get_feed_by_name: Exakter Name-Treffer für '{feed.name}'")
                return feed

        # Schritt 4: Versuche Teilstring-Match.
        for feed in self.feeds.values():
            feed_name_lower = feed.name.lower()
            if name_lower in feed_name_lower or feed_name_lower in name_lower:
                self.logger.debug(f"get_feed_by_name: Teilstring-Treffer für '{feed.name}' mit Suchbegriff '{name}'")
                return feed

        # Schritt 5: Nichts gefunden.
        self.logger.debug(f"get_feed_by_name: Kein Feed für Name '{name}' gefunden.")
        return None

    def has_feed(self, spotify_show_id: str) -> bool:
        """
        [ÖFFENTLICHE METHODE] Prüft, ob ein RSS-Feed für die gegebene Show-ID existiert.

        Args:
            spotify_show_id: Die Spotify-Show-ID.

        Returns:
            True, wenn ein Feed existiert, sonst False.
        """
        # Delegiert die eigentliche Suche an 'get_feed'.
        # Prüft dann, ob das Ergebnis nicht None ist.
        feed_exists = self.get_feed(spotify_show_id) is not None
        self.logger.debug(f"has_feed für '{spotify_show_id}': {feed_exists}")
        return feed_exists

    def get_feed_url(self, spotify_show_id: str) -> Optional[str]:
        """
        [ÖFFENTLICHE METHODE] Gibt die reine RSS-Feed-URL für eine Show-ID zurück.

        Args:
            spotify_show_id: Die Spotify-Show-ID.

        Returns:
            Die RSS-URL als String, oder None wenn kein Feed existiert.
        """
        # Schritt 1: Hole das Feed-Objekt.
        feed = self.get_feed(spotify_show_id)
        # Schritt 2: Wenn ein Feed gefunden wurde, gib dessen 'rss_feed' Attribut zurück.
        #            Sonst gib None zurück.
        return feed.rss_feed if feed else None

    def get_all_feeds(self) -> Dict[str, PodcastRSSFeed]:
        """
        [ÖFFENTLICHE METHODE] Gibt eine Kopie des internen Dictionaries mit allen Feeds zurück.

        Returns:
            Ein Dictionary mit {spotify_id: PodcastRSSFeed}.
        """
        # .copy() wird verwendet, um zu verhindern, dass der Aufrufer das originale
        # interne Dictionary versehentlich verändern kann.
        return self.feeds.copy()

    def get_enabled_feeds(self) -> List[PodcastRSSFeed]:
        """
        [ÖFFENTLICHE METHODE] Gibt eine Liste aller Feeds zurück, die aktiviert und gültig sind.

        Returns:
            Eine Liste von PodcastRSSFeed-Objekten.
        """
        # List Comprehension: Iteriere über alle Feeds, behalte nur die, wo .is_valid() True ergibt.
        enabled_list = [f for f in self.feeds.values() if f.is_valid()]
        self.logger.debug(f"get_enabled_feeds: {len(enabled_list)} von {len(self.feeds)} Feeds sind aktiviert.")
        return enabled_list

    def get_statistics(self) -> Dict[str, Any]:
        """
        [ÖFFENTLICHE METHODE] Erstellt und gibt eine Übersichts-Statistik über alle Feeds zurück.

        Returns:
            Ein Dictionary mit verschiedenen statistischen Informationen.
        """
        total = len(self.feeds)
        enabled_feeds_list = self.get_enabled_feeds()
        enabled = len(enabled_feeds_list)

        # Zähle, wie viele Feeds aus welcher Quelle ("source") stammen.
        sources = {}
        for feed in self.feeds.values():
            sources[feed.source] = sources.get(feed.source, 0) + 1

        # Baue das Ergebnis-Dictionary zusammen.
        stats = {
            "total_feeds": total,
            "enabled_feeds": enabled,
            "disabled_feeds": total - enabled,
            "sources": sources,
            "feeds": [
                {
                    "id": feed.spotify_show_id,
                    "name": feed.name,
                    "source": feed.source,
                    "enabled": feed.enabled,
                }
                for feed in self.feeds.values()
            ],
        }
        self.logger.debug(f"Statistiken erstellt: {stats['total_feeds']} Feeds insgesamt.")
        return stats

    def reload(self):
        """
        [ÖFFENTLICHE METHODE] Leert den internen Cache und lädt die Feeds neu aus der YAML-Datei.
        Nützlich, wenn die YAML-Datei manuell bearbeitet wurde, während das Programm läuft.
        """
        self.logger.info("🔄 Starte Reload der RSS-Feeds...")
        # Schritt 1: Das interne Dictionary leeren.
        self.feeds.clear()
        # Schritt 2: Die Lade-Methode erneut aufrufen.
        self._load_feeds()
        self.logger.info("🔄 Reload der RSS-Feeds abgeschlossen.")

    def add_feed(
        self,
        spotify_id: str,
        name: str,
        rss_feed: str,
        source: str = "manual",
        enabled: bool = True,
    ) -> bool:
        """
        [ÖFFENTLICHE METHODE] Fügt einen neuen Feed hinzu und speichert ihn dauerhaft in der YAML-Datei.

        Args:
            spotify_id: Die Spotify-Show-ID.
            name: Der Name des Podcasts.
            rss_feed: Die URL zum RSS-Feed.
            source: Quelle der Information (z.B. "manual").
            enabled: Soll der Feed standardmäßig aktiviert sein?

        Returns:
            True, wenn der Feed erfolgreich hinzugefügt und gespeichert wurde, sonst False.
        """
        self.logger.info(f"➕ Versuche neuen Feed hinzuzufügen: '{name}' ({spotify_id})")
        yaml_file = self.mapping_dir / "podcast_rss_feeds.yaml"

        try:
            # Schritt 1: Bestehende YAML-Daten laden (falls Datei existiert).
            if yaml_file.exists():
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            else:
                # Wenn die Datei nicht existiert, mit einem leeren Dictionary starten.
                data = {}

            # Schritt 2: Sicherstellen, dass der 'podcasts'-Schlüssel existiert.
            if "podcasts" not in data:
                data["podcasts"] = {}

            # Schritt 3: Neuen Feed unter dem Spotify-ID-Schlüssel zur Datenstruktur hinzufügen.
            data["podcasts"][spotify_id] = {
                "name": name,
                "rss_feed": rss_feed,
                "enabled": enabled,
                "priority": 1,
                "source": source,
            }
            self.logger.debug(f"   Datenstruktur für YAML vorbereitet: {data['podcasts'][spotify_id]}")

            # Schritt 4: Die aktualisierte Datenstruktur zurück in die YAML-Datei schreiben.
            with open(yaml_file, "w", encoding="utf-8") as f:
                yaml.dump(
                    data,
                    f,
                    allow_unicode=True,      # Erlaubt Umlaute und Sonderzeichen im YAML
                    default_flow_style=False # Schreibt im "Block-Stil", nicht im einzeiligen "Flow-Stil"
                )
            self.logger.debug(f"   YAML-Datei erfolgreich aktualisiert: {yaml_file}")

            # Schritt 5: Den internen Zustand des Managers neu laden, damit der neue Feed sofort verfügbar ist.
            self.reload()

            self.logger.info(f"✅ Neuer RSS-Feed erfolgreich hinzugefügt und gespeichert: {name}")
            return True

        except Exception as e:
            # Schritt 6: Bei jedem Fehler (z.B. Schreibrechte, YAML-Fehler) wird False zurückgegeben.
            self.logger.error(f"❌ Fehler beim Hinzufügen des Feeds '{name}': {e}")
            return False