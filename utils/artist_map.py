# -*- coding: utf-8 -*-
# bot/utils/artist_map.py
"""
🎵 ArtistNormalizer Pro – High-Performance Künstlernamen-Normalisierung für YouTube & Library

Features:
- 🚀 Extrem schnelles Matching durch optimierte Datenstrukturen
- 🧠 Self-Learning System mit automatischen Overrides
- 🔍 Präzise YouTube-Titel-Parsing mit KI-ähnlicher Mustererkennung
- 📊 Performance-Monitoring & Caching
- 🛡️ Thread-safe Design für parallele Verarbeitung
- 💾 Persistente Lernfähigkeit
- ✨ Erhaltung von All-Caps Künstlernamen (SDP, RAF, UFO361, etc.)
"""

import re
import json
import time
import hashlib
from functools import lru_cache, wraps
from pathlib import Path
from typing import Dict, Set, List, Tuple, Optional, Pattern, Any
from dataclasses import dataclass, field
from collections import defaultdict
import logging
import unicodedata
import string
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from utils.singleton import SingletonMixin

from logger import get_module_logger

# =============================================================================
# KONFIGURATION & DATENKLASSEN
# =============================================================================


@dataclass(frozen=True)
class ArtistConfig:
    """🔧 Optimierte Konfiguration für Artist Normalisierung"""

    library_dir: Path
    override_file: Path
    collab_separators: frozenset = field(
        default_factory=lambda: frozenset(
            {" x ", " & ", ", ", " with ", " feat. ", " ft. ", " vs. "}
        )
    )
    cache_size: int = 2048
    max_workers: int = 4
    enable_performance_monitoring: bool = True
    auto_learn_threshold: float = 0.85  # Ähnlichkeitsschwelle für Auto-Learning
    mapping_dir: Optional[Path] = None  # Verzeichnis für Mapping-Dateien (YAML)


@dataclass
class ParseResult:
    """📦 Strukturiertes Ergebnis des YouTube-Titel-Parsings"""

    original_title: str
    artists: List[str]
    featuring: List[str]
    main_artist: Optional[str]
    title: str
    artist_string: Optional[str]
    confidence: float = 1.0  # Konfidenzwert für das Parsing-Ergebnis
    processing_time_ms: float = 0.0


# =============================================================================
# PERFORMANCE-DEKORATOREN
# =============================================================================


class PerformanceMonitor:
    """📊 Performance-Monitoring mit detaillierten Metriken"""

    def __init__(self):
        self.metrics = defaultdict(list)
        self._lock = Lock()

    def track(self, func_name: str):
        """Dekorator zur Messung der Ausführungszeit"""

        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                    return result
                finally:
                    duration = (time.perf_counter() - start) * 1000  # in ms
                    with self._lock:
                        self.metrics[func_name].append(duration)
                        # Nur letzte 100 Messungen behalten
                        if len(self.metrics[func_name]) > 100:
                            self.metrics[func_name].pop(0)

            return wrapper

        return decorator

    def get_stats(self, func_name: str) -> Dict[str, float]:
        """Gibt Statistiken für eine Funktion zurück"""
        with self._lock:
            measurements = self.metrics.get(func_name, [])
            if not measurements:
                return {}
            return {
                "avg": sum(measurements) / len(measurements),
                "min": min(measurements),
                "max": max(measurements),
                "count": len(measurements),
            }


# =============================================================================
# CACHE-MANAGER
# =============================================================================


class LRUCache:
    """🚀 Optimierter LRU-Cache mit TTL"""

    def __init__(self, maxsize: int = 1024, ttl: int = 3600):
        self.maxsize = maxsize
        self.ttl = ttl
        self.cache = {}
        self.access_times = {}
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self.cache:
                # Prüfe TTL
                if time.time() - self.access_times[key] < self.ttl:
                    self.access_times[key] = time.time()
                    return self.cache[key]
                else:
                    # Abgelaufen -> entfernen
                    del self.cache[key]
                    del self.access_times[key]
            return None

    def set(self, key: str, value: Any):
        with self._lock:
            # Cache-Größe begrenzen
            if len(self.cache) >= self.maxsize:
                # Entferne ältesten Eintrag
                oldest = min(self.access_times.items(), key=lambda x: x[1])
                del self.cache[oldest[0]]
                del self.access_times[oldest[0]]

            self.cache[key] = value
            self.access_times[key] = time.time()

    def clear(self):
        with self._lock:
            self.cache.clear()
            self.access_times.clear()


# =============================================================================
# HAUPTSKLASSE - OPTIMIERTE VERSION
# =============================================================================


class ArtistNormalizer(SingletonMixin):
    """
    🎵 Hauptklasse für Künstlernamen-Normalisierung mit optimierter Performance

    Singleton: Nur EINE Instanz im gesamten Bot-Lebenszyklus.
    Alle Aufrufer teilen sich Caches, Overrides und Library-Daten.
    """

    # 🔧 Kompilierte Patterns als Klassenattribute (shared across instances)
    _compiled_patterns = None
    _pattern_lock = Lock()

    def _do_init(self, config: ArtistConfig):
        """
        Wird NUR beim ersten ArtistNormalizer()-Aufruf ausgeführt.
        Alle weiteren Aufrufe ignorieren die übergebene Config.
        """
        self.config = config
        self.logger = get_module_logger("artist_map")

        # 🔒 Thread-Sicherheit
        self._lock = Lock()
        self._write_lock = Lock()

        # 🚀 Performance-Monitoring
        self.perf_monitor = (
            PerformanceMonitor() if config.enable_performance_monitoring else None
        )

        # 💾 Mehrstufiges Caching
        self._normalize_cache = LRUCache(maxsize=config.cache_size, ttl=3600)
        self._parse_cache = LRUCache(maxsize=config.cache_size // 2, ttl=1800)

        # 📚 Datenstrukturen
        self.overrides: Dict[str, str] = {}           # NUR manuell (artist_overrides.json)
        self.auto_learned: Dict[str, str] = {}        # Automatisch gelernt (auto_learned_artist_aliases.yaml)
        self.overrides_normalized: Dict[str, str] = {}
        self.library_artists: Set[str] = set()
        self.artist_trie: Dict = {}
        self.artist_patterns: List[Tuple[str, str, float]] = []

        # ✨ Case-Preserve Mapping (für All-Caps Künstlernamen)
        self.case_preserve: Dict[str, str] = {}

        # 🎯 Initialisierung
        self._initialize()

    def _initialize(self):
        """🚀 Optimierte Initialisierung mit parallelem Laden"""
        start_time = time.perf_counter()

        # Paralleles Laden der Ressourcen
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            library_future = executor.submit(self._load_library_artists)
            overrides_future = executor.submit(self._load_overrides)
            auto_learned_future = executor.submit(self._load_auto_learned)
            case_preserve_future = executor.submit(self._load_case_preserve)

            self.library_artists = library_future.result()
            self.overrides = overrides_future.result()
            self.auto_learned = auto_learned_future.result()
            self.case_preserve = case_preserve_future.result()

        # Normalisierte Override-Lookup-Tabelle aufbauen (für case-insensitiven Lookup)
        self.overrides_normalized = {
            self._normalize_key(k): v for k, v in self.overrides.items()
        }

        # Kompilierte Patterns (einmalig für alle Instanzen)
        with ArtistNormalizer._pattern_lock:
            if ArtistNormalizer._compiled_patterns is None:
                ArtistNormalizer._compiled_patterns = self._compile_patterns()

        # Optimierte Datenstrukturen aufbauen
        self._build_artist_trie()
        self._build_weighted_patterns()

        # Overrides aktualisieren (asynchron)
        self._update_overrides_from_library_async()

        duration = (time.perf_counter() - start_time) * 1000
        self.logger.info(
            f"✅ ArtistNormalizer Pro initialisiert in {duration:.1f}ms\n"
            f"   📚 {len(self.library_artists)} Library-Künstler\n"
            f"   📝 {len(self.overrides)} manuelle Overrides\n"
            f"   🧠 {len(self.auto_learned)} auto-gelernte Aliase\n"
            f"   ✨ {len(self.case_preserve)} Case-Preserve Einträge\n"
            f"   🔍 {len(self.artist_patterns)} gewichtete Patterns\n"
            f"   💾 Cache-Größe: {self.config.cache_size}"
        )

    # =========================================================================
    # CASE-PRESERVE LOADING
    # =========================================================================

    def _load_case_preserve(self) -> Dict[str, str]:
        """
        Lädt Case-Preserve Mapping aus case_preserve.yaml
        
        Returns:
            Dict mit lowercase -> preserved_case Mappings
        """
        try:
            import yaml
            
            mapping_dir = self.config.mapping_dir or Path("mapping")
            case_file = mapping_dir / "case_preserve.yaml"
            
            if not case_file.exists():
                self.logger.debug(f"📂 Keine case_preserve.yaml gefunden: {case_file}")
                return {}
            
            with open(case_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                case_preserve = data.get("case_preserve", {})
                
            self.logger.info(f"✨ {len(case_preserve)} Case-Preserve Einträge geladen")
            return case_preserve
            
        except ImportError:
            self.logger.debug("⚠️ PyYAML nicht installiert, Case-Preserve deaktiviert")
            return {}
        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Laden von case_preserve.yaml: {e}")
            return {}

    def _save_case_preserve_entry(self, raw_name: str, preserved: str) -> bool:
        """💾 Speichert einen Case-Preserve Eintrag"""
        try:
            import yaml
            
            mapping_dir = self.config.mapping_dir or Path("mapping")
            case_file = mapping_dir / "case_preserve.yaml"
            case_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Bestehende Daten laden
            data = {"case_preserve": {}}
            if case_file.exists():
                with open(case_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {"case_preserve": {}}
            
            # Neuen Eintrag hinzufügen
            data["case_preserve"][raw_name.lower()] = preserved
            
            # Speichern
            with open(case_file, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=True)
            
            # In-Memory Cache aktualisieren
            self.case_preserve[raw_name.lower()] = preserved
            
            self.logger.debug(f"✨ Case-Preserve gespeichert: '{raw_name.lower()}' → '{preserved}'")
            return True
            
        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Speichern von case_preserve.yaml: {e}")
            return False

    # =========================================================================
    # AUTO-LEARNED ALIASES LOADING
    # =========================================================================

    def _load_auto_learned(self) -> Dict[str, str]:
        """
        Lädt automatisch gelernte Aliase aus auto_learned_artist_aliases.yaml

        ARCH-022: vorher auto_learned_artists.yaml, umbenannt zur
        Namespace-Trennung von AutoLearnManager.observe_featured_artists()'
        "featured_artists"-Schluessel, der diese Klasse nie betrifft.

        Returns:
            Dict mit raw_name -> canonical_name Mappings
        """
        try:
            import yaml

            # Mapping-Verzeichnis bestimmen
            mapping_dir = self.config.mapping_dir or Path("mapping")
            auto_file = mapping_dir / "auto_learned_artist_aliases.yaml"

            if not auto_file.exists():
                self.logger.debug(f"📂 Keine auto_learned_artist_aliases.yaml gefunden: {auto_file}")
                return {}

            with open(auto_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                auto_learned = data.get("auto_learned", {})

            self.logger.info(f"🧠 {len(auto_learned)} auto-gelernte Aliase geladen")
            return auto_learned

        except ImportError:
            self.logger.warning("⚠️ PyYAML nicht installiert, Auto-Learning deaktiviert")
            return {}
        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Laden von auto_learned_artist_aliases.yaml: {e}")
            return {}

    def reload_auto_learned(self) -> bool:
        """
        Lädt die auto_learned_artist_aliases.yaml neu (für Runtime-Updates)

        Returns:
            True bei Erfolg, False bei Fehler
        """
        try:
            new_auto_learned = self._load_auto_learned()
            with self._lock:
                self.auto_learned = new_auto_learned
            self.logger.info(f"🔄 Auto-learned Aliase neu geladen: {len(self.auto_learned)} Einträge")
            return True
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Neuladen der auto-learned Aliase: {e}")
            return False

    # =========================================================================
    # OPTIMIERTE DATENSTRUKTUREN
    # =========================================================================

    def _build_artist_trie(self):
        """🌳 Baut einen Trie für schnelles Prefix-Matching"""
        self.artist_trie = {}

        for artist in self.library_artists:
            self._add_to_trie(artist.lower(), artist)

        for key, canonical in self.overrides.items():
            self._add_to_trie(key.lower(), canonical)
            self._add_to_trie(canonical.lower(), canonical)
        
        # Auch auto-gelernte Aliase in den Trie aufnehmen
        for raw_name, canonical in self.auto_learned.items():
            self._add_to_trie(raw_name.lower(), canonical)
            self._add_to_trie(canonical.lower(), canonical)

    def _add_to_trie(self, key: str, value: str):
        """➕ Fügt einen Eintrag zum Trie hinzu"""
        node = self.artist_trie
        for char in key:
            if char not in node:
                node[char] = {}
            node = node[char]
        node["$"] = value  # '$' markiert Ende eines Wortes

    def _build_weighted_patterns(self):
        """⚖️ Erstellt gewichtete Patterns für intelligentes Matching"""
        patterns = []

        # Library-Artists mit Gewichtung (höher für längere Namen)
        for artist in self.library_artists:
            weight = len(artist) * 1.5  # Längere Namen = höhere Gewichtung
            patterns.append((artist.lower(), artist, weight))

        # Manuelle Overrides mit höchster Gewichtung
        for key, canonical in self.overrides.items():
            patterns.append((key.lower(), canonical, 100.0))  # Overrides haben Priorität
            patterns.append((canonical.lower(), canonical, 90.0))
        
        # Auto-gelernte Aliase mit mittlerer Gewichtung
        for raw_name, canonical in self.auto_learned.items():
            patterns.append((raw_name.lower(), canonical, 80.0))
            patterns.append((canonical.lower(), canonical, 85.0))

        # Sortieren nach Gewichtung (höchste zuerst)
        self.artist_patterns = sorted(
            list(set(patterns)), key=lambda x: x[2], reverse=True  # Duplikate entfernen
        )

    # =========================================================================
    # PATTERN-KOMPILIERUNG (OPTIMIERT)
    # =========================================================================

    def _compile_patterns(self) -> List[Tuple[Pattern, str]]:
        """🔧 Kompiliert alle Patterns mit optimierten Regex"""
        self.logger.debug("🔧 Kompiliere optimierte Patterns...")

        # Performance: Pre-kompilierte Patterns als Tupel speichern
        rule_defs = [
            # Basis-Reinigung
            (r'[^\w\s\-–—\'"&,.]', "", "Sonderzeichen entfernen"),
            # YouTube-spezifische Markierungen (optimiert)
            (
                r"\s*\((?:Official|Offizielles?|Music|Lyric|Audio|Video|HD|4K|VEVO|Explicit|Clean|Live|Remix|Extended|Version|Remastered)[^)]*\)\s*",
                "",
                re.IGNORECASE,
                "YouTube-Klammern",
            ),
            (
                r"\s*\[(?:Official|Music|Lyric|Audio|Video|HD|4K|VEVO)[^\]]*\]\s*",
                "",
                re.IGNORECASE,
                "YouTube-eckige",
            ),
            (
                r"\s*-\s*(?:Official|Music|Lyric|Audio|Video|HD|4K).*$",
                "",
                re.IGNORECASE,
                "YouTube-Trenner",
            ),
            # Produzenten-Angaben
            (
                r"\s*(?:prod\.?|produced|beatz?)\s*by\s*[^,]+",
                "",
                re.IGNORECASE,
                "Producer",
            ),
            # Kollaborations-Normalisierung (optimiert)
            # ARTISTNORM-001: \b-Wortgrenzen verhindern Fehltreffer in Woertern,
            # die "ft"/"feat" nur als Teilstring enthalten (z.B. "trifft",
            # "Kraftklub", "Draft" - wurden vorher zu "trif, ", "Kra, klub",
            # "Dra, " verstuemmelt). \b nach "feat"/"ft" statt nach dem
            # optionalen Punkt, da zwischen "." und einem folgenden Leerzeichen
            # (beides Nicht-Wortzeichen) keine Wortgrenze existiert.
            (r"\s*\b(?:feat|ft)\b\.?\s*", ", ", re.IGNORECASE, "Featuring"),
            #(r"\s*x\s*(?=[A-Za-z])", ", ", re.IGNORECASE, "x-Kollaboration"),
            (r"\s*&\s*", ", ", re.IGNORECASE, "&-Kollaboration"),
            (r"\s*vs\.?\s*", ", ", re.IGNORECASE, "vs-Kollaboration"),
            (r"\s*/\s*", ", ", "Slash-Kollaboration"),
            (r"\s*;\s*", ", ", "Semikolon-Kollaboration"),
            # Whitespace-Optimierung
            (r"\s+", " ", "Mehrfach-Whitespace"),
            (r"^\s+|\s+$", "", "Trimmen"),
            (r",\s*,+", ",", "Doppelte Kommata"),
            (r"^\s*,\s*|\s*,\s*$", "", "Rand-Kommata"),
            # Spezifische Korrekturen (höchste Priorität)
            (r"\bBausashaus\b", "Bausa", re.IGNORECASE, "Bausa-Korrektur"),
            (r"\bBonez Mc\b", "Bonez MC", re.IGNORECASE, "Bonez-Korrektur"),
        ]

        compiled = []
        for rule in rule_defs:
            try:
                pattern, replacement = rule[0], rule[1]
                flags = rule[2] if len(rule) > 2 and isinstance(rule[2], int) else 0

                compiled_pattern = (
                    re.compile(pattern, flags) if flags else re.compile(pattern)
                )
                compiled.append((compiled_pattern, replacement))

            except re.error as e:
                self.logger.error(f"❌ Regex-Fehler: {e} in Regel: {rule}")

        self.logger.info(f"🔧 {len(compiled)} optimierte Patterns kompiliert")
        return compiled

    # =========================================================================
    # CORE-FUNKTIONALITÄT (OPTIMIERT)
    # =========================================================================

    @lru_cache(maxsize=1024)
    def _normalize_key(self, key: str) -> str:
        """🔑 Optimierte Key-Normalisierung mit Caching"""
        normalized = key.lower().strip()
        normalized = unicodedata.normalize("NFKD", normalized)
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))
        return normalized

    def normalize(self, raw_name: str) -> str:
        """🎵 Optimierte Normalisierung mit mehrstufigem Caching"""
        if not raw_name or not isinstance(raw_name, str):
            return "Unknown"

        # Cache-Check
        cache_key = self._normalize_key(raw_name)
        cached = self._normalize_cache.get(cache_key)
        if cached:
            return cached

        # Normalisierung durchführen
        result = self._normalize_internal(raw_name.strip())

        # Cache setzen
        self._normalize_cache.set(cache_key, result)

        return result

    def _normalize_internal(self, name: str) -> str:
	    """🔧 Interne Normalisierungslogik"""
	    self.logger.debug(f"🔍 [DEBUG] Input: '{name}'")
	    
	    # 1. Override-Check (schnellster Pfad)
	    override = self._check_overrides(name)
	    if override:
	        self.logger.debug(f"🔍 [DEBUG] Override: '{override}'")
	        return override
	
	    # 2. Patterns anwenden
	    current = name
	    for i, (pattern, repl) in enumerate(ArtistNormalizer._compiled_patterns):
	        old = current
	        current = pattern.sub(repl, current)
	        if old != current:
	            self.logger.debug(f"🔍 [DEBUG] Pattern {i}: '{old}' → '{current}'")
	    
	    self.logger.debug(f"🔍 [DEBUG] Nach Patterns: '{current}'")
	
	    # 3. Kollaborations-Check
	    if self._is_collaboration(current):
	        self.logger.debug(f"🔍 [DEBUG] Kollaboration erkannt: '{current}'")
	        result = self._normalize_collaboration(current)
	        self.logger.debug(f"🔍 [DEBUG] Nach Kollab: '{result}'")
	        return result
	
	    # 4. Standard-Normalisierung
	    result = self._standard_normalization(current)
	    self.logger.debug(f"🔍 [DEBUG] Final: '{result}'")
	    return result

    def _check_overrides(self, name: str) -> Optional[str]:
        """
        📋 Optimierter Override-Check mit mehrstufiger Priorität:
        1. Manuelle Overrides (höchste Priorität)
        2. Automatisch gelernte Aliase (niedrigere Priorität)
        """
        # 1. Manuelle Overrides (schnellster Pfad)
        if name in self.overrides:
            return self.overrides[name]

        # Normalisierter Match gegen vorberechnete normalized-Lookup-Tabelle
        key = self._normalize_key(name)
        if key in self.overrides_normalized:
            return self.overrides_normalized[key]

        # 2. Automatisch gelernte Aliase (niedrigere Priorität)
        if name in self.auto_learned:
            self.logger.debug(f"🧠 Auto-learned Match: '{name}' → '{self.auto_learned[name]}'")
            return self.auto_learned[name]
        
        # Case-insensitiver Check für auto_learned
        if key in {self._normalize_key(k) for k in self.auto_learned.keys()}:
            for raw, canonical in self.auto_learned.items():
                if self._normalize_key(raw) == key:
                    self.logger.debug(f"🧠 Auto-learned Match (normalized): '{name}' → '{canonical}'")
                    return canonical

        return None

    def _is_collaboration(self, name: str) -> bool:
	    """🤝 Schneller Kollaborations-Check"""
	    # 🔥 Künstler, die fälschlicherweise als Kollaboration erkannt werden
	    FALSE_POSITIVES = {"alex warren", "alex warren topic"}
	    if name.lower() in FALSE_POSITIVES:
	        return False
	    
	    if "," in name:
	        return True
	
	    name_lower = name.lower()
	    for sep in self.config.collab_separators:
	        if sep in name_lower:
	            return True
	
	    return False

    def _normalize_collaboration(self, artist_string: str) -> str:
        """🤝 Optimierte Kollaborations-Normalisierung"""
        # Einheits-Separator
        # ARTISTNORM-001: \b um feat/ft, gleicher Grund wie im Featuring-Pattern
        # in _compile_patterns() oben (verhindert Fehltreffer in Woertern wie
        # "trifft"/"Kraftklub").
        unified = re.sub(
            r"\s*(?:\bfeat\b\.?|\bft\b\.?|x|&|vs\.?|/|;)\s*",
            ",",
            artist_string,
            flags=re.IGNORECASE,
        )

        # Splitten und normalisieren
        parts = [p.strip() for p in unified.split(",") if p.strip()]
        normalized = []

        for part in parts:
            norm = self.normalize(part)
            if norm and norm != "Unknown" and norm not in normalized:
                normalized.append(norm)

        if not normalized:
            return "Unknown"

        return ", ".join(normalized)

    def _standard_normalization(self, name: str) -> str:
        """
        ✨ Optimierte Standard-Normalisierung mit Erhaltung von:
           - All-Caps Akronymen (SDP, RAF, SSIO, UFO361)
           - Präfixen (DJ, MC)
           - Bekannten Künstlernamen aus Case-Preserve
        """
        if not name:
            return name

        original_name = name.strip()
        name_lower = original_name.lower()

        # 🔥 RULE 1: Prüfe gegen gelernte Case-Preserve
        if name_lower in self.case_preserve:
            preserved = self.case_preserve[name_lower]
            self.logger.debug(f"✨ Case-Preserve: '{original_name}' → '{preserved}'")
            return preserved

        # 🔥 RULE 2: Kompletter Artist ist ALL CAPS (max 8 Zeichen, kein Leerzeichen)
        if (
            original_name.isupper()
            and len(original_name) <= 8
            and " " not in original_name
        ):
            self.logger.debug(f"✨ Erhalte All-Caps Künstlernamen: '{original_name}'")
            # Optional: Automatisch zu Case-Preserve hinzufügen für Zukunft
            if original_name.lower() not in self.case_preserve:
                self._save_case_preserve_entry(original_name, original_name)
            return original_name

        # 🔥 RULE 3: Künstler mit ALL-CAPS Präfix (DJ Stylewarz → DJ Stylewarz)
        words = original_name.split()
        if len(words) >= 2 and words[0].isupper() and len(words[0]) <= 3:
            # Präfixe wie DJ, MC, RAF, KMN erhalten
            prefix = words[0].upper()
            rest = " ".join(words[1:])
            # Rest normalisieren
            rest_normalized = self._normalize_rest(rest)
            result = f"{prefix} {rest_normalized}"
            
            # Optional: Gesamten Namen zu Case-Preserve hinzufügen
            full_lower = original_name.lower()
            if full_lower not in self.case_preserve:
                self._save_case_preserve_entry(original_name, result)
            
            self.logger.debug(f"✨ Erhalte Präfix: '{original_name}' → '{result}'")
            return result

        # 🔥 RULE 4: Normalisierung für alles andere
        return self._normalize_rest(original_name)

    def _normalize_rest(self, name: str) -> str:
        """
        Normalisiert den Rest des Künstlernamens (nicht All-Caps)
        """
        if not name:
            return name

        words = name.split()
        capitalized = []

        for word in words:
            # Prüfe auf bekannte Case-Preserve für einzelne Wörter
            word_lower = word.lower()
            if word_lower in self.case_preserve:
                capitalized.append(self.case_preserve[word_lower])
                continue

            # Kurze All-Caps Wörter erhalten (max 3 Zeichen)
            if word.isupper() and len(word) <= 3:
                capitalized.append(word)
                continue

            # Bindestrich-Wörter korrekt kapitalisieren
            if "-" in word:
                parts = word.split("-")
                parts = [p.capitalize() if p and not p.isupper() else p for p in parts]
                capitalized.append("-".join(parts))
            else:
                capitalized.append(word.capitalize())

        return " ".join(capitalized)

    # =========================================================================
    # YOUTUBE-TITLE-PARSING (OPTIMIERT)
    # =========================================================================

    def parse_youtube_title(self, youtube_title: str) -> ParseResult:
        """📺 Optimiertes YouTube-Title-Parsing mit Konfidenzwert"""
        start_time = time.perf_counter()

        # Validierung
        if not youtube_title or not isinstance(youtube_title, str):
            return ParseResult(
                original_title=youtube_title or "",
                artists=[],
                featuring=[],
                main_artist=None,
                title=youtube_title or "Unknown",
                artist_string=None,
                processing_time_ms=0,
            )

        # Cache-Check
        cache_key = hashlib.md5(youtube_title.encode()).hexdigest()
        cached = self._parse_cache.get(cache_key)
        if cached:
            return cached

        # Parsing durchführen
        result = self._parse_youtube_title_internal(youtube_title)

        # Konfidenzwert berechnen
        result.confidence = self._calculate_confidence(result)
        result.processing_time_ms = (time.perf_counter() - start_time) * 1000

        # Cache setzen
        self._parse_cache.set(cache_key, result)

        # Logging (nur bei niedriger Konfidenz)
        if result.confidence < 0.7:
            self.logger.warning(
                f"⚠️ Niedrige Konfidenz ({result.confidence:.2f}) für: {youtube_title[:50]}..."
            )

        return result

    def _parse_youtube_title_internal(self, title: str) -> ParseResult:
        """🔍 Interne Parsing-Logik"""
        # 1. Titel aufbereiten
        cleaned = self._preprocess_title(title)

        # 2. Artist-Block und Titel trennen
        artist_block, title_part = self._split_artist_title(cleaned)

        # 3. Artists extrahieren (optimiert mit Trie)
        found_artists = self._extract_artists_fast(artist_block)

        # 4. Titel bereinigen
        final_title = self._clean_title(title_part, found_artists)

        # 5. Ergebnis strukturieren
        artists = list(
            dict.fromkeys(found_artists)
        )  # Deduplizieren, Reihenfolge erhalten
        main_artist = artists[0] if artists else None
        featuring = artists[1:] if len(artists) > 1 else []

        return ParseResult(
            original_title=title,
            artists=artists,
            featuring=featuring,
            main_artist=main_artist,
            title=final_title or title,
            artist_string=", ".join(artists) if artists else None,
        )

    def _preprocess_title(self, title: str) -> str:
        """🧹 Optimierte Vorverarbeitung"""
        # Unicode normalisieren
        title = unicodedata.normalize("NFKC", title)

        # Druckbare Zeichen
        title = "".join(c for c in title if c in string.printable)

        return title.strip()

    # Podcast-Episodennummern wie "40/2025", "123/2024", "5/2023"
    _PODCAST_EPISODE_RE = re.compile(r"^\d{1,4}/\d{4}$")

    def _split_artist_title(self, title: str) -> Tuple[str, str]:
        """✂️ Optimierte Trennung von Artist und Titel"""
        # Suche nach Trennzeichen
        separators = [" - ", " – ", " — ", " | ", " :: "]

        for sep in separators:
            if sep in title:
                artist, rest = title.split(sep, 1)
                artist = artist.strip()
                rest = rest.strip()

                # 🎙️ Podcast-Episodennummern-Erkennung:
                # Muster wie "40/2025 - Vasseur grüßt aus der Küche"
                # → kein Künstler im Titel, Fallback auf Channel-Name
                if self._PODCAST_EPISODE_RE.match(artist):
                    return "", rest

                return artist, rest

        # Kein Trennzeichen gefunden
        return title, ""

    def _extract_artists_fast(self, text: str) -> List[str]:
        """⚡ Superschnelle Artist-Extraktion mit Trie"""
        if not text:
            return []

        found = []
        text_lower = text.lower()

        # 1. Trie-basiertes Matching (O(n) statt O(n*m))
        i = 0
        while i < len(text_lower):
            node = self.artist_trie
            j = i
            last_match = None
            last_match_pos = i

            while j < len(text_lower) and text_lower[j] in node:
                node = node[text_lower[j]]
                j += 1

                if "$" in node:
                    last_match = node["$"]
                    last_match_pos = j

            if last_match:
                # Prüfe Wortgrenzen
                if self._is_word_boundary(text_lower, i, last_match_pos):
                    found.append(last_match)
                i = last_match_pos
            else:
                i += 1

        # 2. Fallback: Gewichtete Patterns
        if not found:
            for pattern, canonical, weight in self.artist_patterns:
                if pattern in text_lower:
                    # Prüfe Position
                    pos = text_lower.find(pattern)
                    if self._is_word_boundary(text_lower, pos, pos + len(pattern)):
                        found.append(canonical)
                        break  # Nimm den ersten Match mit höchster Gewichtung

        return found

    def _is_word_boundary(self, text: str, start: int, end: int) -> bool:
        """🎯 Optimierte Wortgrenzen-Prüfung"""
        boundaries = " .,-;:'\"!?()[]{}"

        before_ok = start == 0 or text[start - 1] in boundaries
        after_ok = end >= len(text) or text[end] in boundaries

        return before_ok and after_ok

    def _clean_title(self, title: str, artists: List[str]) -> str:
        """🧹 Optimierte Titelbereinigung"""
        if not title:
            return ""

        cleaned = title

        # Entferne gefundene Artists
        for artist in sorted(artists, key=len, reverse=True):
            pattern = rf"(?i)\s*{re.escape(artist)}\s*[,&\sx-]?\s*"
            cleaned = re.sub(pattern, " ", cleaned)

        # Patterns anwenden
        for pattern, repl in ArtistNormalizer._compiled_patterns:
            cleaned = pattern.sub(repl, cleaned)

        # Finales Trimmen
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = cleaned.strip(" -–—|")

        return cleaned

    def _calculate_confidence(self, result: ParseResult) -> float:
        """📊 Berechnet Konfidenzwert für Parsing-Ergebnis"""
        confidence = 1.0

        # Abzüge für Probleme
        if not result.artists:
            confidence -= 0.5

        if not result.title or result.title == result.original_title:
            confidence -= 0.3

        if len(result.title) < 3:
            confidence -= 0.2

        if result.artist_string and len(result.artist_string) > 100:
            confidence -= 0.1

        return max(0.0, min(1.0, confidence))

    # =========================================================================
    # LIBRARY & OVERRIDES (OPTIMIERT)
    # =========================================================================

    def _load_library_artists(self) -> Set[str]:
        """📂 Optimiertes Laden der Library-Artists"""
        if not self.config.library_dir.exists():
            self.logger.warning(f"❌ Library nicht gefunden: {self.config.library_dir}")
            return set()

        artists = set()
        try:
            for d in self.config.library_dir.iterdir():
                if d.is_dir() and not d.name.startswith("."):
                    artists.add(d.name.strip())
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Library: {e}")

        return artists

    def _load_overrides(self) -> Dict[str, str]:
        """📝 Optimiertes Laden der Overrides"""
        if not self.config.override_file.exists():
            return {}

        try:
            with open(self.config.override_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {k.strip(): v.strip() for k, v in data.items()}
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Overrides: {e}")
            return {}

    def _update_overrides_from_library_async(self):
        """🔄 Asynchrones Update der Overrides"""
        with self._write_lock:
            new_entries = {}

            for artist in self.library_artists:
                key = self._normalize_key(artist)
                if key not in self.overrides:
                    new_entries[key] = artist

            if new_entries:
                self.overrides.update(new_entries)
                self._save_overrides()
                self.logger.info(f"➕ {len(new_entries)} neue Artists gelernt")

    def _save_overrides(self):
        """💾 Optimiertes Speichern der Overrides"""
        try:
            self.config.override_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config.override_file, "w", encoding="utf-8") as f:
                json.dump(
                    dict(sorted(self.overrides.items())),
                    f,
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            # Normalisierte Lookup-Tabelle synchron halten
            self.overrides_normalized = {
                self._normalize_key(k): v for k, v in self.overrides.items()
            }
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Speichern der Overrides: {e}")

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """📊 Gibt detaillierte Statistiken zurück"""
        stats = {
            "library_artists": len(self.library_artists),
            "overrides": len(self.overrides),
            "auto_learned": len(self.auto_learned),
            "case_preserve": len(self.case_preserve),
            "patterns": len(self.artist_patterns),
            "cache": {
                "normalize": len(self._normalize_cache.cache),
                "parse": len(self._parse_cache.cache),
            },
        }

        if self.perf_monitor:
            stats["performance"] = {
                name: self.perf_monitor.get_stats(name)
                for name in ["_initialize", "normalize", "parse_youtube_title"]
            }

        return stats

    def learn_from_feedback(self, original: str, corrected: Dict):
        """🧠 Lernt aus manuellen Korrekturen (schreibt in auto_learned_artist_aliases.yaml)"""
        with self._write_lock:
            # Nur in auto_learned speichern, NICHT in overrides!
            if corrected.get("main_artist"):
                raw_name = original.strip()
                canonical_name = corrected["main_artist"].strip()
                
                if raw_name.lower() != canonical_name.lower():
                    self.auto_learned[raw_name] = canonical_name
                    self._save_auto_learned_entry(raw_name, canonical_name)
                    self.logger.info(f"🧠 Gelernt aus Feedback: '{raw_name}' → '{canonical_name}'")

    def _save_auto_learned_entry(self, raw_name: str, canonical_name: str):
        """💾 Speichert einen einzelnen Auto-Learned Eintrag.

        ARCH-022: schreibt jetzt atomar (write-tmp -> rename), analog zu
        services/metadata/auto_learn.py::AutoLearnManager._write_yaml_atomic() -
        vorher direktes open(mode="w"), das bei einem Absturz mitten im
        Schreiben eine korrupte/halb geschriebene Datei haette hinterlassen
        koennen. Ausserdem jetzt eigene Datei auto_learned_artist_aliases.yaml
        statt des vorherigen "auto_learned"-Schluessels in der gemeinsam mit
        AutoLearnManager.observe_featured_artists() genutzten
        auto_learned_artists.yaml (Namespace-Trennung, siehe dortiger
        "featured_artists"-Schluessel, der von dieser Klasse nie gelesen
        wird).

        WICHTIG: kein eigenes self._write_lock hier - beide Aufrufer
        (learn_from_feedback(), add_auto_learned_alias()) halten den Lock
        bereits, bevor sie diese Methode aufrufen (Lock ist ein
        threading.Lock, nicht reentrant - ein zusaetzliches Lock hier
        wuerde deadlocken)."""
        try:
            import yaml

            mapping_dir = self.config.mapping_dir or Path("mapping")
            auto_file = mapping_dir / "auto_learned_artist_aliases.yaml"
            auto_file.parent.mkdir(parents=True, exist_ok=True)

            # Bestehende Daten laden
            data = {"auto_learned": {}}
            if auto_file.exists():
                with open(auto_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {"auto_learned": {}}

            # Neuen Eintrag hinzufügen
            data["auto_learned"][raw_name] = canonical_name

            # Atomar speichern (write-tmp -> rename)
            tmp_path = auto_file.with_suffix(f".tmp_{int(time.time() * 1000)}")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    yaml.dump(
                        data,
                        f,
                        allow_unicode=True,
                        default_flow_style=False,
                        sort_keys=True,
                    )
                tmp_path.replace(auto_file)
            except Exception:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise

        except ImportError:
            self.logger.warning("⚠️ PyYAML nicht installiert, kann nicht speichern")
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Speichern des Auto-Learned Eintrags: {e}")

    def add_auto_learned_alias(self, raw_name: str, canonical_name: str) -> bool:
        """
        Fügt manuell einen Auto-Learned Alias hinzu (für externe Aufrufe)
        
        Args:
            raw_name: Der rohe Künstlername (z.B. "bausashaus")
            canonical_name: Der kanonische Name (z.B. "Bausa")
            
        Returns:
            True bei Erfolg, False bei Fehler
        """
        if not raw_name or not canonical_name:
            return False
            
        with self._write_lock:
            if raw_name.strip().lower() == canonical_name.strip().lower():
                return False
                
            self.auto_learned[raw_name.strip()] = canonical_name.strip()
            self._save_auto_learned_entry(raw_name.strip(), canonical_name.strip())
            
            # Datenstrukturen aktualisieren
            self._add_to_trie(raw_name.strip().lower(), canonical_name.strip())
            self._build_weighted_patterns()
            
            self.logger.info(f"🧠 Manueller Auto-Learned Alias: '{raw_name}' → '{canonical_name}'")
            return True

    def add_case_preserve(self, raw_name: str, preserved: str) -> bool:
        """
        Fügt einen Case-Preserve Eintrag hinzu (erhält Großschreibung)
        
        Args:
            raw_name: Der rohe Name (z.B. "sdp")
            preserved: Die zu erhaltende Schreibweise (z.B. "SDP")
            
        Returns:
            True bei Erfolg, False bei Fehler
        """
        if not raw_name or not preserved:
            return False
            
        with self._write_lock:
            key = raw_name.strip().lower()
            self.case_preserve[key] = preserved.strip()
            self._save_case_preserve_entry(raw_name, preserved)
            
            self.logger.info(f"✨ Case-Preserve hinzugefügt: '{key}' → '{preserved}'")
            return True

    def clear_cache(self):
        """🧹 Leert alle Caches"""
        self._normalize_cache.clear()
        self._parse_cache.clear()
        self.logger.info("🧹 Caches geleert")


# =============================================================================
# FACTORY FUNKTION
# =============================================================================


def create_artist_normalizer(
    library_path: str, override_path: str, mapping_dir: Optional[str] = None, **kwargs
) -> ArtistNormalizer:
    """🏭 Factory-Funktion für einfache Erstellung"""
    config = ArtistConfig(
        library_dir=Path(library_path),
        override_file=Path(override_path),
        mapping_dir=Path(mapping_dir) if mapping_dir else Path("mapping"),
        **kwargs
    )
    return ArtistNormalizer(config)


# =============================================================================
# MAIN (TEST)
# =============================================================================

if __name__ == "__main__":
    # Logger für Test initialisieren
    from logger import setup_enhanced_logging

    setup_enhanced_logging(level="DEBUG")

    # 🔧 Test-Konfiguration
    test_config = ArtistConfig(
        library_dir=Path("./test_library"),
        override_file=Path("./test_overrides.json"),
        mapping_dir=Path("./mapping"),
        enable_performance_monitoring=True,
    )

    # 🎵 Normalizer erstellen
    normalizer = ArtistNormalizer(test_config)

    # 📺 Test-Titel
    test_titles = [
        "Bausa - Was du Liebe nennst (Official Video)",
        "Apache 207 & Ufo361 feat. Bausa - Roller (prod. by Lucry)",
        "Shirin David x Bausa - 90-60-111 [Official Video]",
    ]

    # 🔍 Tests durchführen
    print("\n" + "=" * 60)
    print("🔍 YOUTUBE-TITLE-PARSING TEST")
    print("=" * 60)

    for title in test_titles:
        result = normalizer.parse_youtube_title(title)
        print(f"\n📺 Original: {title}")
        print(f"🎤 Hauptartist: {result.main_artist}")
        print(f"🤝 Features: {result.featuring}")
        print(f"📝 Titel: {result.title}")
        print(f"🎯 Konfidenz: {result.confidence:.2f}")
        print(f"⚡ Zeit: {result.processing_time_ms:.1f}ms")

    # 📊 Statistiken anzeigen
    print("\n" + "=" * 60)
    print("📊 PERFORMANCE-STATISTIK")
    print("=" * 60)
    stats = normalizer.get_stats()

    if "performance" in stats:
        for func, data in stats["performance"].items():
            if data:
                print(f"\n⚡ {func}:")
                print(f"   ⏱️  Avg: {data['avg']:.2f}ms")
                print(f"   ⏱️  Min: {data['min']:.2f}ms")
                print(f"   ⏱️  Max: {data['max']:.2f}ms")
                print(f"   📊 Count: {data['count']}")
    
    # 🧠 Auto-Learning Test
    print("\n" + "=" * 60)
    print("🧠 AUTO-LEARNING TEST")
    print("=" * 60)
    
    # Test: Alias hinzufügen
    normalizer.add_auto_learned_alias("bausashaus", "Bausa")
    
    # Test: Case-Preserve hinzufügen
    normalizer.add_case_preserve("sdp", "SDP")
    normalizer.add_case_preserve("raf", "RAF")
    
    # Test: Normalisierung mit gelerntem Alias
    test_aliases = ["bausashaus", "BAUSASHAUS", "Bausashaus", "Apache207", "sdp", "SDP", "raf", "RAF Camora"]
    for alias in test_aliases:
        normalized = normalizer.normalize(alias)
        print(f"📝 '{alias}' → '{normalized}'")
    
    # Statistiken nach Auto-Learning
    print(f"\n📊 Final Stats: {normalizer.get_stats()}")