# -*- coding: utf-8 -*-
# yt_music_bot/utils/genre_map.py
"""
🎵 GenreMapper Pro – Erweiterte Normalisierung und Anreicherung von Musik-Genres

Features:
- 🚀 Statische Mappings in separaten YAML-Dateien
- 🔍 Fuzzy-Matching mit rapidfuzz für robuste Erkennung
- 📊 Hierarchische Genre-Struktur (Subgenres → Hauptgenres)
- 🧠 Regex-Regeln für automatische Genre-Extraktion
- 💾 LRU-Caching für schnelle wiederholte Anfragen
- 🎯 Spezialkanal-Erkennung mit Prioritätssteuerung
- 📝 Vollständige Logging-Integration mit get_module_logger

Verwendung:
    >>> mapper = get_genre_mapper()
    >>> result = mapper.determine_genre(
    ...     raw_genre="Hip Hop",
    ...     artist_name="Eminem",
    ...     channel_name="VEVO"
    ... )
    >>> print(result['primary'])
"""

import re
import yaml
from typing import Dict, List, Tuple, Optional, Union, Set, Any
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from threading import Lock

# 🔥 KORRIGIERT: Verwende get_module_logger ohne logger_factory!
from logger import get_module_logger
from utils.singleton import SingletonMixin

# Logger für dieses Modul
logger = get_module_logger("genre_map")

try:
    from rapidfuzz import process, fuzz
except ImportError:
    logger.critical(
        "❌ Required dependency 'rapidfuzz' not found. "
        "Please install with: pip install rapidfuzz"
    )
    raise


# =============================================================================
# DATENKLASSEN
# =============================================================================


@dataclass(frozen=True)
class GenreMapping:
    """Container für Genre-Informationen mit Primär- und Sekundärgenres"""

    primary: str
    secondary: List[str] = field(default_factory=list)
    description: Optional[str] = None

    def __post_init__(self):
        """Stellt sicher, dass secondary immer eine Liste ist"""
        if self.secondary is None:
            object.__setattr__(self, "secondary", [])

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "description": self.description,
        }


@dataclass
class GenreResult:
    primary: str
    secondary: List[str] = field(default_factory=list)
    source: str = "unknown"
    confidence: float = 1.0
    matched_key: Optional[str] = None
    matched_score: Optional[float] = None
    raw_tags: List[str] = field(default_factory=list)

    # Neu
    mb_ids: Optional[Dict[str, Any]] = None
    auto_learn_disabled: bool = False


# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================


def load_yaml_data(file_path: Union[str, Path]) -> Union[Dict, List]:
    """
    Lädt Daten aus einer YAML-Datei.

    Args:
        file_path: Pfad zur YAML-Datei

    Returns:
        Geladene Daten oder leeres Dict bei Fehler
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            logger.debug(f"✅ YAML geladen: {file_path}")
            return data if data is not None else {}
    except FileNotFoundError:
        logger.error(f"❌ YAML-Datei nicht gefunden: {file_path}")
        return {}
    except yaml.YAMLError as e:
        logger.error(f"❌ YAML-Fehler in {file_path}: {e}")
        return {}
    except Exception as e:
        logger.error(f"❌ Unerwarteter Fehler beim Laden von {file_path}: {e}")
        return {}


# =============================================================================
# HAUPTKLASSE
# =============================================================================


class GenreMapper(SingletonMixin):
    """
    🎵 GenreMapper – Zentrale Klasse für Genre-Normalisierung und -Anreicherung

    Features:
        - Lädt Mappings aus YAML-Dateien im mapping/-Verzeichnis
        - Bietet Fuzzy-Matching für Künstler- und Channel-Namen
        - Wendet Regex-Regeln zur Genre-Extraktion an
        - Nutzt Genre-Hierarchie für Subgenre → Hauptgenre Mapping
        - Caching für performante wiederholte Anfragen
    """

    def _do_init(self, mapping_dir: str = "mapping"):
        """
        Wird NUR beim ersten GenreMapper()-Aufruf ausgeführt.
        Alle weiteren Aufrufe geben sofort die existierende Instanz zurück.
        """
        logger.info("🎵 [GENRE_MAP] Initialisiere GenreMapper...")

        # Thread-Sicherheit
        self._lock = Lock()
        self._cache_lock = Lock()

        # Datenstrukturen (immer initialisieren, auch bei Fehlern)
        self.channel_map: Dict[str, GenreMapping] = {}
        self.artist_map: Dict[str, GenreMapping] = {}
        self.hierarchy: Dict[str, str] = {}
        self.overrides: Dict[str, str] = {}
        self.rules: List[Tuple[re.Pattern, str]] = []
        self.genre_aliases: Dict[str, str] = {}

        # Statistiken
        self._stats = {
            "queries": 0,
            "cache_hits": 0,
            "fuzzy_matches": 0,
            "rule_matches": 0,
        }

        # Mapping-Verzeichnis finden
        mapping_path = self._find_mapping_dir(mapping_dir)
        if not mapping_path:
            logger.critical(
                f"❌ [GENRE_MAP] Mapping-Verzeichnis nicht gefunden: {mapping_dir}"
            )
            return

        logger.info(f"📂 [GENRE_MAP] Mapping-Verzeichnis: {mapping_path}")

        # YAML-Dateien laden
        self._load_all_mappings(mapping_path)

        # Cache für Fuzzy-Matches
        self._fuzzy_cache: Dict[str, Optional[GenreMapping]] = {}
        self._fuzzy_cache_ttl: Dict[str, float] = {}

        # Statistiken loggen
        self._log_statistics()

        logger.info("✅ [GENRE_MAP] GenreMapper erfolgreich initialisiert")

    def _find_mapping_dir(self, mapping_dir: str) -> Optional[Path]:
        """
        Findet das Mapping-Verzeichnis an verschiedenen möglichen Pfaden.

        Args:
            mapping_dir: Relativer Pfad zum Mapping-Verzeichnis

        Returns:
            Absoluter Pfad oder None
        """
        possible_paths = [
            Path(mapping_dir),
            Path(__file__).resolve().parent / mapping_dir,
            Path(__file__).resolve().parent.parent / mapping_dir,
            Path.cwd() / mapping_dir,
        ]

        for path in possible_paths:
            if path.exists() and path.is_dir():
                return path.resolve()

        logger.warning(f"⚠️ Mapping-Verzeichnis nicht gefunden in: {possible_paths}")
        return None

    def _load_all_mappings(self, mapping_path: Path) -> None:
        """
        Lädt alle YAML-Mapping-Dateien.

        Args:
            mapping_path: Absoluter Pfad zum Mapping-Verzeichnis
        """
        # 1. Channel-Mappings
        channel_data = load_yaml_data(mapping_path / "channel_genre.yaml")
        self.channel_map = self._parse_genre_mappings(
            channel_data.get("CHANNEL_GENRE_MAP", channel_data)
        )
        logger.info(f"   📺 {len(self.channel_map)} Channel-Mappings geladen")

        # 2. Artist-Mappings (manuell)
        artist_data = load_yaml_data(mapping_path / "artist_genre.yaml")
        self.artist_map = self._parse_genre_mappings(
            artist_data.get("ARTIST_GENRE_MAP", artist_data)
        )
        logger.info(f"   🎤 {len(self.artist_map)} Artist-Mappings geladen (manuell)")

        # 2b. Auto-learned Artist-Mappings (werden nie überschrieben von manuellen)
        auto_learned_path = mapping_path / "auto_learned_genre.yaml"
        if auto_learned_path.exists():
            auto_data = load_yaml_data(auto_learned_path)
            auto_map = self._parse_genre_mappings(
                auto_data.get("ARTIST_GENRE_MAP", auto_data)
            )
            # FIX: Nur Einträge hinzufügen, die NICHT manuell gepflegt sind
            # (manual hat immer Vorrang!)
            added = 0
            for key, mapping in auto_map.items():
                if key not in self.artist_map:
                    self.artist_map[key] = mapping
                    added += 1
            logger.info(
                f"   🧠 {added} Auto-Learned Artist-Mappings hinzugefügt "
                f"({len(auto_map)} gesamt in auto_learned_genre.yaml)"
            )
        else:
            logger.debug(
                "   🧠 auto_learned_genre.yaml noch nicht vorhanden "
                "(wird beim ersten Auto-Learn erstellt)"
            )

        # 3. Genre-Hierarchie
        hierarchy_data = load_yaml_data(mapping_path / "genre_hierarchy.yaml")
        self.hierarchy = hierarchy_data.get("GENRE_HIERARCHY", hierarchy_data) or {}
        logger.info(f"   📊 {len(self.hierarchy)} Hierarchie-Einträge geladen")

        # 4. Genre-Overrides
        overrides_data = load_yaml_data(mapping_path / "genre_overrides.yaml")
        self.overrides = overrides_data.get("GENRE_OVERRIDES", overrides_data) or {}
        logger.info(f"   🔧 {len(self.overrides)} Overrides geladen")

        # 5. Genre-Aliases
        aliases_data = load_yaml_data(mapping_path / "genre_aliases.yaml")
        self.genre_aliases = aliases_data.get("GENRE_ALIASES", aliases_data) or {}
        logger.info(f"   🔄 {len(self.genre_aliases)} Aliases geladen")

        # 6. Regex-Regeln
        rules_data = load_yaml_data(mapping_path / "genre_rules.yaml")
        self.rules = self._compile_rules(rules_data.get("GENRE_RULES", []))
        logger.info(f"   📏 {len(self.rules)} Regex-Regeln kompiliert")

    def _parse_genre_mappings(self, data: Dict) -> Dict[str, GenreMapping]:
        """
        Parst Genre-Mappings aus YAML-Daten.

        Args:
            data: Rohdaten aus YAML

        Returns:
            Dictionary mit lowercase Keys → GenreMapping
        """
        if not data:
            return {}

        mappings = {}
        for key, value in data.items():
            try:
                if isinstance(value, dict):
                    mapping = GenreMapping(
                        primary=value.get("primary", ""),
                        secondary=value.get("secondary", []),
                        description=value.get("description"),
                    )
                elif isinstance(value, str):
                    # Einfaches Format: key → primary
                    mapping = GenreMapping(primary=value)
                else:
                    logger.warning(
                        f"⚠️ Unbekanntes Format für Key '{key}': {type(value)}"
                    )
                    continue

                if mapping.primary:
                    mappings[key.lower().strip()] = mapping
                else:
                    logger.warning(f"⚠️ Kein Primary-Genre für Key '{key}'")

            except Exception as e:
                logger.error(f"❌ Fehler beim Parsen von '{key}': {e}")

        return mappings

    def _compile_rules(self, rules_data: List) -> List[Tuple[re.Pattern, str]]:
        """
        Kompiliert Regex-Regeln.

        Args:
            rules_data: Liste von Regel-Dictionaries

        Returns:
            Liste von (Pattern, Replacement) Tupeln
        """
        compiled = []
        for item in rules_data:
            try:
                pattern = re.compile(item["pattern"], re.IGNORECASE)
                replacement = item["replacement"]
                compiled.append((pattern, replacement))
                logger.debug(f"   📏 Regel kompiliert: {item['pattern'][:50]}...")
            except re.error as e:
                logger.error(f"❌ Regex-Fehler in Regel '{item}': {e}")
            except KeyError as e:
                logger.error(f"❌ Fehlender Key in Regel: {e}")

        return compiled

    def _log_statistics(self) -> None:
        """Loggt Initialisierungs-Statistiken"""
        total_mappings = len(self.artist_map) + len(self.channel_map)
        total_rules = len(self.rules)

        logger.info(
            f"📊 GenreMapper Statistiken:\n"
            f"   • {len(self.artist_map)} Künstler-Mappings\n"
            f"   • {len(self.channel_map)} Channel-Mappings\n"
            f"   • {len(self.hierarchy)} Hierarchie-Einträge\n"
            f"   • {total_rules} Regex-Regeln\n"
            f"   • {len(self.genre_aliases)} Aliases\n"
            f"   • {len(self.overrides)} Overrides"
        )

    # =========================================================================
    # CORE-FUNKTIONALITÄT
    # =========================================================================

    @lru_cache(maxsize=1024)
    def get_main_genre(self, sub_genre: str) -> str:
        """
        Gibt das Hauptgenre für ein Subgenre zurück (aus der Hierarchie).

        Args:
            sub_genre: Subgenre-Name

        Returns:
            Hauptgenre oder das ursprüngliche Genre
        """
        if not sub_genre:
            return ""

        key = sub_genre.lower().strip()
        return self.hierarchy.get(key, sub_genre)

    @lru_cache(maxsize=2048)
    def normalize_genre_name(self, genre_name: str) -> str:
        """
        Normalisiert Genre-Namen durch Anwendung von Aliases und Title-Case.

        Args:
            genre_name: Roher Genre-Name

        Returns:
            Normalisierter Genre-Name
        """
        if not genre_name:
            return ""

        genre_lower = genre_name.strip().lower()

        # 1. Overrides anwenden (höchste Priorität)
        if genre_lower in self.overrides:
            normalized = self.overrides[genre_lower]
            logger.debug(f"🔧 Override: '{genre_name}' → '{normalized}'")
            return normalized

        # 2. Aliases auflösen
        if genre_lower in self.genre_aliases:
            normalized = self.genre_aliases[genre_lower]
            logger.debug(f"🔄 Alias: '{genre_name}' → '{normalized}'")
            return normalized

        # 3. Title-Case für unbekannte Genres
        # Spezielle Behandlung für bekannte Abkürzungen
        words = genre_name.split()
        normalized_words = []

        for word in words:
            # Bekannte Abkürzungen beibehalten
            if word.upper() in ("EDM", "R&B", "UK", "US", "DJ", "MC"):
                normalized_words.append(word.upper())
            elif "-" in word:
                # Bindestrich-Wörter
                parts = word.split("-")
                parts = [p.capitalize() for p in parts if p]
                normalized_words.append("-".join(parts))
            else:
                normalized_words.append(word.capitalize())

        return " ".join(normalized_words)

    def get_artist_entry(self, artist_name: str) -> Optional[GenreMapping]:
        """
        Gibt das Genre-Mapping für einen Künstler zurück.

        Args:
            artist_name: Künstlername

        Returns:
            GenreMapping oder None
        """
        if not artist_name:
            return None

        key = artist_name.strip().lower()
        return self.artist_map.get(key)

    def get_channel_entry(self, channel_name: str) -> Optional[GenreMapping]:
        """
        Gibt das Genre-Mapping für einen Channel zurück.

        Args:
            channel_name: Channel-Name

        Returns:
            GenreMapping oder None
        """
        if not channel_name:
            return None

        key = channel_name.strip().lower()
        return self.channel_map.get(key)

    def get_all_primary_genres(self) -> Set[str]:
        """
        Gibt alle eindeutigen Primärgenres zurück.

        Returns:
            Set aller Primärgenres
        """
        primary_genres = set()

        for mapping in self.artist_map.values():
            primary_genres.add(mapping.primary)

        for mapping in self.channel_map.values():
            primary_genres.add(mapping.primary)

        for main_genre in self.hierarchy.values():
            primary_genres.add(main_genre)

        return primary_genres

    def get_subgenres(self, primary_genre: str) -> List[str]:
        """
        Gibt alle Subgenres für ein Hauptgenre zurück.

        Args:
            primary_genre: Hauptgenre

        Returns:
            Liste von Subgenres
        """
        if not primary_genre:
            return []

        primary_lower = primary_genre.lower()
        return [
            sub for sub, main in self.hierarchy.items() if main.lower() == primary_lower
        ]

    # =========================================================================
    # FUZZY-MATCHING
    # =========================================================================

    def _find_best_match(
        self,
        query: str,
        choices: Dict[str, GenreMapping],
        threshold: int = 80,
        context: str = "generic",
    ) -> Optional[GenreMapping]:
        """
        Fuzzy-Matching mit rapidfuzz und Caching.

        Args:
            query: Suchbegriff
            choices: Auswahl-Möglichkeiten
            threshold: Mindest-Score (0-100)
            context: Kontext für Logging ("artist", "channel")

        Returns:
            Bestes GenreMapping oder None
        """
        if not query or not choices:
            logger.debug(f"🔍 Kein {context}-Match: leere Query oder Choices")
            return None

        # Cache-Key
        cache_key = f"{context}:{query.lower()}:{threshold}"

        with self._cache_lock:
            # Cache-Check
            if cache_key in self._fuzzy_cache:
                self._stats["cache_hits"] += 1
                return self._fuzzy_cache[cache_key]

        try:
            # Fuzzy-Matching durchführen
            results = process.extract(
                query, choices.keys(), scorer=fuzz.WRatio, limit=3
            )

            if not results:
                logger.debug(f"🔍 Keine {context}-Matches für '{query}'")
                self._fuzzy_cache[cache_key] = None
                return None

            best_match, score, _ = results[0]

            if score >= threshold:
                self._stats["fuzzy_matches"] += 1
                mapping = choices[best_match]
                logger.info(
                    f"✅ {context.upper()}-Match: '{query}' → '{best_match}' "
                    f"(Score: {score:.1f}%, Primary: {mapping.primary})"
                )
                self._fuzzy_cache[cache_key] = mapping
                return mapping
            else:
                logger.debug(
                    f"⚠️ {context}-Match unter Threshold: '{query}' → "
                    f"'{best_match}' ({score:.1f}% < {threshold}%)"
                )
                self._fuzzy_cache[cache_key] = None
                return None

        except Exception as e:
            logger.error(f"❌ {context}-Matching fehlgeschlagen für '{query}': {e}")
            return None

    # =========================================================================
    # REGEL-ANWENDUNG
    # =========================================================================

    def _apply_rules(self, raw_genre: str) -> Optional[str]:
        """
        Wendet Regex-Regeln auf das Genre an.

        Args:
            raw_genre: Roher Genre-String

        Returns:
            Ersetztes Genre oder None
        """
        if not raw_genre:
            return None

        clean_genre = raw_genre.lower().strip()

        for pattern, replacement in self.rules:
            if pattern.search(clean_genre):
                self._stats["rule_matches"] += 1
                logger.debug(
                    f"📏 Regel-Match: '{raw_genre}' → '{replacement}' "
                    f"(Pattern: {pattern.pattern[:50]}...)"
                )
                return replacement

        return None

    # =========================================================================
    # HAUPTMETHODE: GENRE-BESTIMMUNG
    # =========================================================================

    def determine_genre(
        self,
        raw_genre: Optional[str] = None,
        artist_name: Optional[str] = None,
        channel_name: Optional[str] = None,
        is_special_channel: bool = False,
    ) -> Optional[GenreResult]:
        """
        Bestimmt das Genre basierend auf verfügbaren Informationen.

        Prioritätsreihenfolge:
            1. Spezialkanal: Channel-Mapping (wenn is_special_channel=True)
            2. Artist-Mapping (exakt, dann fuzzy)
            3. Channel-Mapping (exakt, dann fuzzy)
            4. Regex-Regeln auf raw_genre
            5. Normalisierung + Hierarchie von raw_genre

        Args:
            raw_genre: Roher Genre-String (z.B. aus YouTube-Beschreibung)
            artist_name: Künstlername für Mapping-Lookup
            channel_name: Channel-Name für Mapping-Lookup
            is_special_channel: Wenn True, hat Channel Vorrang vor Artist

        Returns:
            GenreResult oder None
        """
        self._stats["queries"] += 1

        logger.debug(
            f"🔍 determine_genre: raw='{raw_genre}', artist='{artist_name}', "
            f"channel='{channel_name}', special={is_special_channel}"
        )

        # ─────────────────────────────────────────────────────────────────────
        # 1. SPEZIALKANAL: Channel hat höchste Priorität
        # ─────────────────────────────────────────────────────────────────────
        if is_special_channel and channel_name:
            channel_clean = channel_name.strip().lower()

            # Exakter Match
            if channel_clean in self.channel_map:
                mapping = self.channel_map[channel_clean]
                logger.info(
                    f"⭐ Spezialkanal (exakt): {channel_name} → {mapping.primary}"
                )
                return GenreResult(
                    primary=mapping.primary,
                    secondary=mapping.secondary,
                    source="channel_exact",
                    confidence=1.0,
                    matched_key=channel_name,
                )

            # Fuzzy-Match
            if fuzzy_match := self._find_best_match(
                channel_clean, self.channel_map, 75, "channel"
            ):
                logger.info(
                    f"⭐ Spezialkanal (fuzzy): {channel_name} → {fuzzy_match.primary}"
                )
                return GenreResult(
                    primary=fuzzy_match.primary,
                    secondary=fuzzy_match.secondary,
                    source="channel_fuzzy",
                    confidence=0.8,
                    matched_key=channel_name,
                )

        # ─────────────────────────────────────────────────────────────────────
        # 2. ARTIST-MAPPING
        # ─────────────────────────────────────────────────────────────────────
        if artist_name:
            artist_clean = artist_name.strip().lower()

            # Exakter Match
            if artist_clean in self.artist_map:
                mapping = self.artist_map[artist_clean]
                logger.info(
                    f"🎤 Artist-Match (exakt): {artist_name} → {mapping.primary}"
                )
                return GenreResult(
                    primary=mapping.primary,
                    secondary=mapping.secondary,
                    source="artist_exact",
                    confidence=1.0,
                    matched_key=artist_name,
                )

            # Fuzzy-Match
            if fuzzy_match := self._find_best_match(
                artist_clean, self.artist_map, 85, "artist"
            ):
                logger.info(
                    f"🎤 Artist-Match (fuzzy): {artist_name} → {fuzzy_match.primary}"
                )
                return GenreResult(
                    primary=fuzzy_match.primary,
                    secondary=fuzzy_match.secondary,
                    source="artist_fuzzy",
                    confidence=0.85,
                    matched_key=artist_name,
                )

        # ─────────────────────────────────────────────────────────────────────
        # 3. CHANNEL-MAPPING (normal)
        # ─────────────────────────────────────────────────────────────────────
        if channel_name and not is_special_channel:
            channel_clean = channel_name.strip().lower()

            # Exakter Match
            if channel_clean in self.channel_map:
                mapping = self.channel_map[channel_clean]
                logger.info(
                    f"📺 Channel-Match (exakt): {channel_name} → {mapping.primary}"
                )
                return GenreResult(
                    primary=mapping.primary,
                    secondary=mapping.secondary,
                    source="channel_exact",
                    confidence=1.0,
                    matched_key=channel_name,
                )

            # Fuzzy-Match
            if fuzzy_match := self._find_best_match(
                channel_clean, self.channel_map, 75, "channel"
            ):
                logger.info(
                    f"📺 Channel-Match (fuzzy): {channel_name} → {fuzzy_match.primary}"
                )
                return GenreResult(
                    primary=fuzzy_match.primary,
                    secondary=fuzzy_match.secondary,
                    source="channel_fuzzy",
                    confidence=0.75,
                    matched_key=channel_name,
                )

        # ─────────────────────────────────────────────────────────────────────
        # 4. REGEX-REGELN AUF RAW_GENRE
        # ─────────────────────────────────────────────────────────────────────
        if raw_genre:
            rule_result = self._apply_rules(raw_genre)
            if rule_result:
                logger.info(f"📏 Regel-Match: '{raw_genre}' → '{rule_result}'")
                return GenreResult(
                    primary=rule_result,
                    secondary=[],
                    source="rule",
                    confidence=0.9,
                )

        # ─────────────────────────────────────────────────────────────────────
        # 5. NORMALISIERUNG + HIERARCHIE
        # ─────────────────────────────────────────────────────────────────────
        if raw_genre:
            normalized = self.normalize_genre_name(raw_genre)
            main_genre = self.get_main_genre(normalized)

            if main_genre != normalized:
                logger.info(
                    f"📊 Hierarchie: '{raw_genre}' → '{normalized}' → '{main_genre}'"
                )
            else:
                logger.info(f"📝 Normalisiert: '{raw_genre}' → '{normalized}'")

            return GenreResult(
                primary=main_genre,
                secondary=[],
                source="hierarchy" if main_genre != normalized else "normalized",
                confidence=0.6 if main_genre != normalized else 0.4,
            )

        # ─────────────────────────────────────────────────────────────────────
        # KEIN TREFFER
        # ─────────────────────────────────────────────────────────────────────
        logger.warning(
            f"⚠️ Kein Genre bestimmt für: raw='{raw_genre}', "
            f"artist='{artist_name}', channel='{channel_name}'"
        )
        return None

    # =========================================================================
    # ERWEITERTE FUNKTIONEN
    # =========================================================================

    def enrich_genre_info(self, primary_genre: str) -> Dict[str, Any]:
        """
        Bereichert Genre-Informationen mit verwandten Genres und Metadaten.

        Args:
            primary_genre: Primärgenre

        Returns:
            Dictionary mit angereicherten Informationen
        """
        if not primary_genre:
            return {"primary": "", "secondary": [], "subgenres": [], "related": []}

        result = {
            "primary": primary_genre,
            "secondary": [],
            "subgenres": self.get_subgenres(primary_genre),
            "related": [],
            "mappings": {
                "artists": [],
                "channels": [],
            },
        }

        primary_lower = primary_genre.lower()

        # Sekundäre Genres aus Mappings sammeln
        for mapping in self.artist_map.values():
            if mapping.primary.lower() == primary_lower:
                result["secondary"].extend(mapping.secondary)

        for mapping in self.channel_map.values():
            if mapping.primary.lower() == primary_lower:
                result["secondary"].extend(mapping.secondary)

        # Künstler mit diesem Genre finden
        for artist, mapping in self.artist_map.items():
            if mapping.primary.lower() == primary_lower:
                result["mappings"]["artists"].append(artist)

        # Channels mit diesem Genre finden
        for channel, mapping in self.channel_map.items():
            if mapping.primary.lower() == primary_lower:
                result["mappings"]["channels"].append(channel)

        # Duplikate entfernen und begrenzen
        result["secondary"] = list(set(result["secondary"]))
        result["mappings"]["artists"] = result["mappings"]["artists"][:10]
        result["mappings"]["channels"] = result["mappings"]["channels"][:10]

        return result

    def validate_genre(self, genre_name: str) -> bool:
        """
        Validiert, ob ein Genre in der Hierarchie oder Mappings existiert.

        Args:
            genre_name: Zu prüfender Genre-Name

        Returns:
            True wenn Genre bekannt ist
        """
        if not genre_name:
            return False

        genre_normalized = self.normalize_genre_name(genre_name)
        genre_lower = genre_normalized.lower()

        # Prüfe in Hierarchie
        if genre_lower in self.hierarchy or genre_lower in self.hierarchy.values():
            return True

        # Prüfe in Artist-Mappings
        for mapping in self.artist_map.values():
            if mapping.primary.lower() == genre_lower:
                return True

        # Prüfe in Channel-Mappings
        for mapping in self.channel_map.values():
            if mapping.primary.lower() == genre_lower:
                return True

        return False

    def suggest_genre(self, partial_name: str, limit: int = 5) -> List[str]:
        """
        Schlägt Genres basierend auf Teilstring vor.

        Args:
            partial_name: Teil des Genre-Namens
            limit: Maximale Anzahl Vorschläge

        Returns:
            Liste von Genre-Vorschlägen
        """
        if not partial_name:
            return []

        partial_lower = partial_name.lower()
        suggestions = set()

        # Aus Hierarchie
        for genre in self.hierarchy.keys():
            if partial_lower in genre.lower():
                suggestions.add(genre)

        for genre in self.hierarchy.values():
            if partial_lower in genre.lower():
                suggestions.add(genre)

        # Aus Mappings
        for mapping in self.artist_map.values():
            if partial_lower in mapping.primary.lower():
                suggestions.add(mapping.primary)

        for mapping in self.channel_map.values():
            if partial_lower in mapping.primary.lower():
                suggestions.add(mapping.primary)

        return sorted(list(suggestions))[:limit]

    def get_statistics(self) -> Dict[str, Any]:
        """
        Gibt detaillierte Statistiken zurück.

        Returns:
            Dictionary mit Statistiken
        """
        return {
            "queries": self._stats["queries"],
            "cache_hits": self._stats["cache_hits"],
            "fuzzy_matches": self._stats["fuzzy_matches"],
            "rule_matches": self._stats["rule_matches"],
            "cache_hit_rate": (
                self._stats["cache_hits"] / max(self._stats["queries"], 1)
            ),
            "mappings": {
                "artists": len(self.artist_map),
                "channels": len(self.channel_map),
                "hierarchy": len(self.hierarchy),
                "rules": len(self.rules),
                "aliases": len(self.genre_aliases),
                "overrides": len(self.overrides),
            },
            "unique_primary_genres": len(self.get_all_primary_genres()),
        }

    def clear_caches(self) -> None:
        """Leert alle Caches"""
        with self._cache_lock:
            self._fuzzy_cache.clear()
            self._fuzzy_cache_ttl.clear()

        self.get_main_genre.cache_clear()
        self.normalize_genre_name.cache_clear()

        logger.info("🧹 Caches geleert")

    def reload(self) -> None:
        """Lädt alle Mappings neu"""
        logger.info("🔄 Lade GenreMapper neu...")

        # Mapping-Verzeichnis finden
        mapping_path = self._find_mapping_dir("mapping")
        if not mapping_path:
            logger.error("❌ Mapping-Verzeichnis nicht gefunden")
            return

        # Caches leeren
        self.clear_caches()

        # Datenstrukturen zurücksetzen
        self.channel_map.clear()
        self.artist_map.clear()
        self.hierarchy.clear()
        self.overrides.clear()
        self.rules.clear()
        self.genre_aliases.clear()

        # Neu laden
        self._load_all_mappings(mapping_path)

        logger.info("✅ GenreMapper erfolgreich neu geladen")


# =============================================================================
# SINGLETON-INSTANZ
# =============================================================================

_genre_mapper_instance: Optional[GenreMapper] = None
_instance_lock = Lock()


def get_genre_mapper(mapping_dir: str = "mapping") -> GenreMapper:
    """
    Gibt eine globale GenreMapper-Instanz zurück (Singleton-Pattern).

    Args:
        mapping_dir: Verzeichnis mit Mapping-Dateien

    Returns:
        GenreMapper-Instanz
    """
    global _genre_mapper_instance

    with _instance_lock:
        if _genre_mapper_instance is None:
            logger.info("🎵 Erstelle globale GenreMapper-Instanz...")
            _genre_mapper_instance = GenreMapper(mapping_dir)

    return _genre_mapper_instance


def reset_genre_mapper() -> None:
    """Setzt die globale GenreMapper-Instanz zurück (für Tests)."""
    global _genre_mapper_instance

    with _instance_lock:
        if _genre_mapper_instance:
            _genre_mapper_instance.clear_caches()
        _genre_mapper_instance = None

    logger.info("🔄 Globale GenreMapper-Instanz zurückgesetzt")


# =============================================================================
# KONVENIENZ-FUNKTIONEN
# =============================================================================


def determine_genre(
    raw_genre: Optional[str] = None,
    artist_name: Optional[str] = None,
    channel_name: Optional[str] = None,
    is_special_channel: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Konvenienz-Funktion zur Genre-Bestimmung.

    Args:
        raw_genre: Roher Genre-String
        artist_name: Künstlername
        channel_name: Channel-Name
        is_special_channel: Spezialkanal-Flag

    Returns:
        Dictionary mit 'primary' und 'secondary' oder None
    """
    mapper = get_genre_mapper()
    result = mapper.determine_genre(
        raw_genre=raw_genre,
        artist_name=artist_name,
        channel_name=channel_name,
        is_special_channel=is_special_channel,
    )

    if result:
        return {"primary": result.primary, "secondary": result.secondary}
    return None


def normalize_genre(genre_name: str) -> str:
    """
    Konvenienz-Funktion zur Genre-Normalisierung.

    Args:
        genre_name: Roher Genre-Name

    Returns:
        Normalisierter Genre-Name
    """
    mapper = get_genre_mapper()
    return mapper.normalize_genre_name(genre_name)


# =============================================================================
# TEST (bei direkter Ausführung)
# =============================================================================

if __name__ == "__main__":
    # Logger initialisieren
    from logger import setup_enhanced_logging

    setup_enhanced_logging(level="DEBUG")

    print("\n" + "=" * 60)
    print("🎵 GENRE MAPPER TEST")
    print("=" * 60)

    # Mapper erstellen
    mapper = get_genre_mapper()

    # Testfälle
    test_cases = [
        {"raw_genre": "Hip Hop", "artist_name": "Eminem"},
        {"raw_genre": "Elektronische Musik", "channel_name": "VEVO"},
        {"raw_genre": "Pop", "artist_name": "Taylor Swift"},
        {"artist_name": "Bausa", "channel_name": "BausaVEVO"},
    ]

    for i, test in enumerate(test_cases, 1):
        print(f"\n📋 Test {i}:")
        print(f"   Input: {test}")

        result = mapper.determine_genre(**test)

        if result:
            print(f"   ✅ Primary: {result.primary}")
            print(f"   ✅ Secondary: {result.secondary}")
            print(f"   ✅ Source: {result.source}")
            print(f"   ✅ Confidence: {result.confidence:.2f}")
        else:
            print("   ❌ Kein Ergebnis")

    # Statistiken
    print("\n" + "=" * 60)
    print("📊 STATISTIKEN")
    print("=" * 60)

    stats = mapper.get_statistics()
    for key, value in stats.items():
        if isinstance(value, dict):
            print(f"\n{key}:")
            for k, v in value.items():
                print(f"   • {k}: {v}")
        else:
            print(f"• {key}: {value}")
