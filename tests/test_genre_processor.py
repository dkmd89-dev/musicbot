#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field

# =========================================================
# Mocks
# =========================================================

class MockLogger:
    def debug(self, msg, *args, **kwargs): pass
    def info(self, msg, *args, **kwargs): pass
    def warning(self, msg, *args, **kwargs): pass
    def error(self, msg, *args, **kwargs): pass
    def isEnabledFor(self, level): return False

def get_module_logger(name):
    return MockLogger()

sys.modules['logger'] = type(sys)('logger')
sys.modules['logger'].get_module_logger = get_module_logger
sys.modules['utils'] = type(sys)('utils')
sys.modules['utils.genre_map'] = type(sys)('utils.genre_map')

@dataclass
class GenreResult:
    primary: str = ""
    secondary: List[str] = field(default_factory=list)
    source: str = ""
    confidence: float = 0.0
    raw_tags: List[str] = field(default_factory=list)
    mb_ids: Dict[str, str] = field(default_factory=dict)

# =========================================================
# GenreProcessor
# =========================================================

class GenreProcessor:
    def __init__(self, mapping_dir: Path):
        self.mapping_dir = mapping_dir
        self.logger = MockLogger()
        self.GENRE_NORMALIZATION = self._load_genre_normalization()
        self.IGNORE_SECONDARY = self._load_ignore_secondary()
        self.GENRE_PRIORITY = self._calculate_genre_priority_from_hierarchy()
        print(f"✅ GenreProcessor initialisiert:")
        print(f"   - {len(self.GENRE_NORMALIZATION)} Normalisierungen")
        print(f"   - {len(self.IGNORE_SECONDARY)} ignorierte Tags")
        print(f"   - {len(self.GENRE_PRIORITY)} priorisierte Genres")

    def _load_genre_normalization(self) -> Dict[str, str]:
        aliases_file = self.mapping_dir / "genre_aliases.yaml"
        if not aliases_file.exists():
            return {}
        with open(aliases_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        aliases = data.get("GENRE_ALIASES", {})
        return {alias.lower(): canonical for alias, canonical in aliases.items()}

    def _load_ignore_secondary(self) -> Set[str]:
        filter_file = self.mapping_dir / "genre_filters.yaml"
        if not filter_file.exists():
            return set()
        with open(filter_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return set(data.get("IGNORE_SECONDARY", []))

    def _calculate_genre_priority_from_hierarchy(self) -> Dict[str, int]:
        hierarchy_file = self.mapping_dir / "genre_hierarchy.yaml"
        if not hierarchy_file.exists():
            return {}
        with open(hierarchy_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        hierarchy = data.get("GENRE_HIERARCHY", {})
        genre_depth: Dict[str, int] = {}
        children_map: Dict[str, List[str]] = {}
        for child, parent in hierarchy.items():
            if parent is None:
                continue
            if parent not in children_map:
                children_map[parent] = []
            children_map[parent].append(child)
        
        def calculate_depth(genre: str, current_depth: int = 0, visited: set = None):
            if visited is None:
                visited = set()
            if genre in visited:
                return
            visited.add(genre)
            if genre not in genre_depth or current_depth < genre_depth[genre]:
                genre_depth[genre] = current_depth
            if genre in children_map:
                for child in children_map[genre]:
                    calculate_depth(child, current_depth + 1, visited)
        
        top_level = [g for g, p in hierarchy.items() if p is None]
        for top in top_level:
            calculate_depth(top, 0)
        for genre in hierarchy.keys():
            if genre not in genre_depth:
                parent = hierarchy.get(genre)
                if parent and parent in genre_depth:
                    genre_depth[genre] = genre_depth[parent] + 1
                else:
                    genre_depth[genre] = 0
        return {genre.lower(): depth for genre, depth in genre_depth.items()}

    def normalize_genre_name(self, genre: str) -> str:
        if not genre:
            return "Unknown"
        genre_lower = genre.lower().strip()
        if genre_lower in self.GENRE_NORMALIZATION:
            return self.GENRE_NORMALIZATION[genre_lower]
        for key, value in self.GENRE_NORMALIZATION.items():
            if key in genre_lower:
                return value
        words = genre.split()
        return " ".join(w.capitalize() for w in words)

    def prioritize_genres(self, tags: List[str], artist_name: Optional[str] = None) -> Tuple[str, List[str]]:
        if not tags:
            return "Unknown", []
        
        def normalize_for_matching(text: str) -> str:
            t = text.lower().strip()
            replacements = {"hip-hop": "hip hop", "r&b": "rnb", "r'n'b": "rnb"}
            return replacements.get(t, t)
        
        valid_tags = []
        for tag in tags:
            if not tag:
                continue
            tag_lower = tag.lower().strip()
            if tag_lower in self.IGNORE_SECONDARY:
                continue
            if artist_name and tag_lower == artist_name.lower():
                continue
            valid_tags.append(normalize_for_matching(tag_lower))
        
        if not valid_tags:
            return "Unknown", []
        
        tag_priorities = []
        for tag in valid_tags:
            normalized_tag = self.normalize_genre_name(tag).lower()
            priority = self.GENRE_PRIORITY.get(normalized_tag)
            if priority is None:
                priority = self.GENRE_PRIORITY.get(tag)
            if priority is not None:
                tag_priorities.append((normalized_tag, priority))
        
        if not tag_priorities:
            primary = self.normalize_genre_name(valid_tags[0])
            secondary = [self.normalize_genre_name(t) for t in valid_tags[1:6] if self.normalize_genre_name(t) != primary]
            return primary, secondary
        
        tag_priorities.sort(key=lambda x: (-x[1], x[0]))
        best_normalized = tag_priorities[0][0]
        
        correction_map = {
            "ruhrpott rap": "Ruhrpott Rap",
            "hamburger schule": "Hamburger Rap",
            "berliner rap": "Berliner Rap",
            "kölsch rap": "Kölsch Rap",
        }
        primary = correction_map.get(best_normalized, best_normalized.title())
        
        secondary = []
        seen = {primary.lower()}
        for norm_tag, _ in tag_priorities[1:]:
            if norm_tag not in seen:
                seen.add(norm_tag)
                secondary.append(correction_map.get(norm_tag, norm_tag.title()))
            if len(secondary) >= 5:
                break
        
        return primary, secondary


# =========================================================
# TESTS
# =========================================================

class TestGenreProcessor:
    def __init__(self):
        mapping_dir = Path(__file__).parent.parent.parent / "mapping"
        if not mapping_dir.exists():
            mapping_dir = Path("mapping")
        print(f"📁 Mapping-Verzeichnis: {mapping_dir}")
        self.processor = GenreProcessor(mapping_dir)

    def run_all_tests(self):
        print("=" * 70)
        print("🧪 GENRE PROCESSOR TESTS")
        print("=" * 70)
        
        tests = [
            ("Normalisierung Deutschrap", self.test_normalize_deutschrap),
            ("Normalisierung Hip Hop", self.test_normalize_hip_hop),
            ("Normalisierung Pop", self.test_normalize_pop),
            ("Normalisierung Electronic", self.test_normalize_electronic),
            ("Priorität Deutschrap > Hip Hop", self.test_priority_deutschrap_over_hip_hop),
            ("Priorität Subgenre > Hauptgenre", self.test_priority_subgenre_over_main_genre),
            ("Priorität Deutschrap Subgenres", self.test_priority_deutschrap_subgenres),
            ("Priorität ignorierte Tags", self.test_priority_ignore_secondary),
            ("Priorität Artist-Name Filter", self.test_priority_artist_name_filter),
            ("Sekundär-Genres max 5", self.test_secondary_max_five),
            ("Sekundär-Genres keine Duplikate", self.test_secondary_no_duplicates),
            ("Leere Tags", self.test_empty_tags),
            ("Groß-/Kleinschreibung", self.test_case_insensitive),
            ("Deutschrap vs German Hip Hop", self.test_german_vs_us_rap),
            ("Regionale Deutschrap-Subgenres", self.test_regional_subgenres),
        ]
        
        passed, failed = 0, 0
        for name, test_func in tests:
            try:
                test_func()
                print(f"  ✅ {name}")
                passed += 1
            except AssertionError as e:
                print(f"  ❌ {name}: {e}")
                failed += 1
            except Exception as e:
                print(f"  💥 {name}: {e}")
                failed += 1
        
        print("\n" + "=" * 70)
        print(f"📊 Ergebnis: {passed} bestanden, {failed} fehlgeschlagen")
        print("=" * 70)
        return failed == 0

    def test_normalize_deutschrap(self):
        test_cases = [
            ("deutschrap", "Deutschrap"),
            ("german hip hop", "Deutschrap"),
            ("ruhrpott rap", "Ruhrpott Rap"),
            ("berliner rap", "Berliner Rap"),
            ("hamburger schule", "Hamburger Rap"),
        ]
        for inp, exp in test_cases:
            result = self.processor.normalize_genre_name(inp)
            assert result == exp, f"'{inp}' → '{result}', erwartet '{exp}'"

    def test_normalize_hip_hop(self):
        assert self.processor.normalize_genre_name("hip hop") == "Hip Hop"
        assert self.processor.normalize_genre_name("rap") == "Hip Hop"

    def test_normalize_pop(self):
        assert self.processor.normalize_genre_name("pop") == "Pop"

    def test_normalize_electronic(self):
        assert self.processor.normalize_genre_name("edm") == "Electronic"

    def test_priority_deutschrap_over_hip_hop(self):
        primary, _ = self.processor.prioritize_genres(["deutschrap", "hip hop"])
        assert primary == "Deutschrap"

    def test_priority_subgenre_over_main_genre(self):
        primary, _ = self.processor.prioritize_genres(["ruhrpott rap", "deutschrap"])
        assert primary == "Ruhrpott Rap", f"Erwartet 'Ruhrpott Rap', bekam '{primary}'"

    def test_priority_deutschrap_subgenres(self):
        test_cases = [
            (["hamburger schule", "deutschrap"], "Hamburger Rap"),
            (["berliner rap", "deutschrap"], "Berliner Rap"),
        ]
        for tags, expected in test_cases:
            primary, _ = self.processor.prioritize_genres(tags)
            assert primary == expected, f"{tags} → {primary}, erwartet {expected}"

    def test_priority_ignore_secondary(self):
        primary, secondary = self.processor.prioritize_genres(["deutschrap", "seen live"])
        assert primary == "Deutschrap"
        assert len(secondary) == 0

    def test_priority_artist_name_filter(self):
        primary, _ = self.processor.prioritize_genres(["deutschrap", "kollegah"], artist_name="kollegah")
        assert primary == "Deutschrap"

    def test_secondary_max_five(self):
        _, secondary = self.processor.prioritize_genres(["deutschrap", "a", "b", "c", "d", "e", "f", "g"])
        assert len(secondary) <= 5

    def test_secondary_no_duplicates(self):
        _, secondary = self.processor.prioritize_genres(["deutschrap", "hip hop", "hip hop", "rap"])
        assert len(secondary) == len(set(secondary))

    def test_empty_tags(self):
        primary, secondary = self.processor.prioritize_genres([])
        assert primary == "Unknown"
        assert secondary == []

    def test_case_insensitive(self):
        assert self.processor.normalize_genre_name("DEUTSCHRAP") == "Deutschrap"

    def test_german_vs_us_rap(self):
        primary, _ = self.processor.prioritize_genres(["german hip hop", "hip hop"])
        assert primary == "Deutschrap"

    def test_regional_subgenres(self):
        test_cases = [
            ("berliner rap", "Berliner Rap"),
            ("hamburger schule", "Hamburger Rap"),
            ("ruhrpott rap", "Ruhrpott Rap"),
        ]
        for tag, expected in test_cases:
            result = self.processor.normalize_genre_name(tag)
            assert result == expected


if __name__ == "__main__":
    mapping_dir = Path(__file__).parent.parent.parent / "mapping"
    if not mapping_dir.exists():
        mapping_dir = Path("mapping")
    print(f"\n📁 Prüfe Mapping-Dateien in: {mapping_dir}")
    required = ["genre_aliases.yaml", "genre_hierarchy.yaml"]
    missing = [f for f in required if not (mapping_dir / f).exists()]
    if missing:
        print(f"⚠️ Fehlende Dateien: {missing}")
        sys.exit(1)
    print("✅ Alle benötigten Dateien gefunden.\n")
    
    tester = TestGenreProcessor()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)
