# services/downloader/utils/metadata/genre_processor.py
# -*- coding: utf-8 -*-
"""
GenreProcessor v2.1 – Vereinheitlichte Genre-Pipeline

Änderungen gegenüber v2.0:
  ✅ Alle Rückgabepfade liefern ausschließlich GenreResult (nie GenreMapping)
  ✅ Kein object.__setattr__() mehr auf Singleton-GenreMapping-Objekten
  ✅ _mapping_to_result() konvertiert GenreMapping sauber zu GenreResult
  ✅ mb_ids, auto_learn_disabled als echte Felder in GenreResult (kein dynamisches Draufpappen)
  ✅ Kein Risiko mehr, den globalen GenreMapper-Cache durch Mutation zu beschädigen

Genre-Pipeline (determine_genre_with_fallbacks):
  1. Manuelles Genre  – artist_genre.yaml (exakter Key-Match, höchste Priorität)
  2. Lokales Genre    – channel_map / auto_learned / fuzzy / raw_genre / Hierarchie
  3. MusicBrainz      – IMMER aufgerufen für MB-IDs
  4. Last.fm          – nur wenn noch kein Genre
  5. Feature-Inference – Genre aus bekannten Feature-Artists ableiten

Priorisierung basiert auf genre_hierarchy.yaml:
  - Je höher die Tiefe (1, 2, 3...), desto spezifischer das Genre
  - Subgenres werden ihren Eltern vorgezogen
"""

import re
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple, TYPE_CHECKING

from logger import get_module_logger

if TYPE_CHECKING:
    from utils.genre_map import GenreMapper


class GenreProcessor:
    """
    Verantwortlich für Genre-Ermittlung, -Priorisierung und -Normalisierung.
    Kapselt alle YAML-basierten Genre-Konfigurationen sowie externe API-Fallbacks.

    Rückgabe-Invariante:
        determine_genre_with_fallbacks() gibt IMMER Optional[GenreResult] zurück.
        Niemals GenreMapping. Niemals ein mutiertes Singleton-Objekt.
    """

    def __init__(self, config, genre_mapper: "GenreMapper", logger=None):
        self.config = config
        self.genre_mapper = genre_mapper
        self.logger = logger or get_module_logger("GenreProcessor")

        # Hierarchie-basierte Prioritäten (aus genre_hierarchy.yaml berechnet)
        self.GENRE_PRIORITY: Dict[str, int] = self._calculate_genre_priority_from_hierarchy()
        self.IGNORE_SECONDARY: Set[str] = self._load_ignore_secondary_from_yaml()
        self.GENRE_NORMALIZATION: Dict[str, str] = self._load_genre_normalization_from_yaml()

        self.logger.info(
            f"✅ GenreProcessor initialisiert: "
            f"{len(self.GENRE_PRIORITY)} priorisierte Genres (aus Hierarchie), "
            f"{len(self.IGNORE_SECONDARY)} Filter, "
            f"{len(self.GENRE_NORMALIZATION)} Normalisierungen"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ─────────────────────────────────────────────────────────────────────────

    async def determine_genre_with_fallbacks(
        self,
        track_metadata: Dict[str, Any],
        artist_name: str,
        channel_name: str,
        canonical_channel_name: Optional[str] = None,
        is_special_channel: bool = False,
        feat_artists: Optional[List[str]] = None,
        clean_title: Optional[str] = None,
        mb_client=None,
        lfm_client=None,
    ):
        """
        Bestimmt Genre mit Fallback auf MusicBrainz und Last.fm.

        Gibt immer Optional[GenreResult] zurück – nie GenreMapping.
        mb_ids werden in GenreResult.mb_ids gespeichert (kein dynamisches Attribut).
        """
        from utils.genre_map import GenreResult

        try:
            effective_channel = canonical_channel_name or channel_name

            self.logger.info("🏷️ determine_genre_with_fallbacks aufgerufen:")
            self.logger.info(f"   artist_name: {artist_name}")
            self.logger.info(f"   clean_title: {clean_title}")

            search_title = clean_title or track_metadata.get("title", "")
            if search_title:
                search_title = self._prepare_search_title(search_title)
                self.logger.info(f"🏷️ Such-Titel für APIs: '{search_title}'")

            # ── 1. Manuelles Genre (artist_genre.yaml, exakter Match) ─────────
            manual_result: Optional[GenreResult] = None
            raw_manual = self.genre_mapper.get_artist_entry(artist_name.lower())
            if raw_manual and raw_manual.primary:
                self.logger.info(
                    f"🏷️ Manuelles Genre für '{artist_name}': '{raw_manual.primary}'"
                )
                manual_result = self._mapping_to_result(
                    raw_manual,
                    source="artist_exact_manual",
                    auto_learn_disabled=True,
                )

            # ── 2. Lokales Genre (channel/fuzzy/raw/Hierarchie) ───────────────
            local_result: Optional[GenreResult] = None
            if manual_result is None:
                raw_local = self.genre_mapper.determine_genre(
                    raw_genre=track_metadata.get("genre"),
                    artist_name=artist_name,
                    channel_name=effective_channel,
                    is_special_channel=is_special_channel,
                )
                if raw_local and raw_local.primary:
                    self.logger.info(
                        f"🏷️ Lokales Genre: '{raw_local.primary}' "
                        f"(Quelle: {raw_local.source})"
                    )
                    # raw_local ist bereits GenreResult (aus determine_genre)
                    local_result = GenreResult(
                        primary=raw_local.primary,
                        secondary=list(raw_local.secondary or []),
                        source=raw_local.source,
                        confidence=raw_local.confidence,
                        matched_key=raw_local.matched_key,
                        matched_score=raw_local.matched_score,
                        raw_tags=list(getattr(raw_local, "raw_tags", []) or []),
                        auto_learn_disabled=True,
                    )

            # Bekanntes Genre (manuell > lokal)
            known_result: Optional[GenreResult] = manual_result or local_result

            # ── 3. MusicBrainz – IMMER für IDs ───────────────────────────────
            _mb_result: Optional[GenreResult] = None
            if search_title and mb_client is not None:
                _mb_result = await self._fetch_genre_from_musicbrainz(
                    artist_name, search_title, mb_client
                )

            _mb_ids: Optional[Dict[str, Any]] = (
                _mb_result.mb_ids if _mb_result else None
            )
            if _mb_ids:
                self.logger.info(
                    f"🏷️ [MB-IDs] Empfangen: "
                    f"recording={(_mb_ids.get('recording_id') or '')[:8] or '–'}"
                )

            # 3a. Bekanntes Genre + MB-IDs → fertig
            if known_result is not None:
                if _mb_ids:
                    known_result.mb_ids = _mb_ids
                    self.logger.info(
                        f"🏷️ [MB-IDs] An bekanntes Genre '{known_result.primary}' angehängt"
                    )
                return known_result

            # 3b. Kein bekanntes Genre → MB-Genre auswerten
            if _mb_result is not None and _mb_result.primary:
                self.logger.info(f"🏷️✅ Genre via MusicBrainz: '{_mb_result.primary}'")
                return _mb_result

            # MB hat nur IDs geliefert (kein Genre) → als Sentinel merken
            _mb_sentinel: Optional[GenreResult] = _mb_result  # primary == "" oder None

            # ── 4. Last.fm ────────────────────────────────────────────────────
            if search_title:
                self.logger.info(
                    f"🏷️ Kein Genre für '{artist_name}' – versuche Last.fm"
                )
                lfm_result = await self._fetch_genre_from_lastfm(
                    artist_name, search_title, lfm_client
                )
                if lfm_result:
                    if _mb_sentinel is not None and _mb_sentinel.mb_ids:
                        lfm_result.mb_ids = _mb_sentinel.mb_ids
                        self.logger.info("🏷️ [MB-IDs] In Last.fm-Ergebnis übernommen")
                    self.logger.info(f"🏷️✅ Genre via Last.fm: '{lfm_result.primary}'")
                    return lfm_result
                else:
                    # Last.fm hat nichts geliefert – wenigstens MB-IDs zurückgeben
                    if _mb_sentinel is not None and _mb_sentinel.mb_ids:
                        self.logger.info(
                            "🏷️ [MB-IDs] Kein Genre von Last.fm – gebe MB-Sentinel zurück"
                        )
                        return _mb_sentinel

            # ── 5. Feature-Artist Inference ───────────────────────────────────
            if feat_artists:
                inferred = self._infer_genre_from_feat_artists(feat_artists)
                if inferred:
                    return inferred

            return None

        except Exception as e:
            self.logger.warning(f"🏷️❌ Fehler beim Genre-Mapping: {e}", exc_info=True)
            return None

    def prioritize_genres(
        self, tags: List[str], artist_name: Optional[str] = None
    ) -> Tuple[str, List[str]]:
        """
        Bestimmt das Hauptgenre basierend auf Hierarchie-Priorität.

        Priorisierungslogik:
          1. Tags normalisieren und filtern
          2. Priorität aus GENRE_PRIORITY holen (höhere Tiefe = spezifischer)
          3. Absteigend sortieren (höchste Tiefe gewinnt)
          4. Bei Gleichstand alphabetisch
        """
        if not tags:
            return "Unknown", []

        def normalize_for_matching(text: str) -> str:
            t = text.lower().strip()
            replacements = {
                "hip-hop": "hip hop",
                "r&b": "rnb",
                "r'n'b": "rnb",
                "rhythm and blues": "rnb",
                "rhythm & blues": "rnb",
            }
            return replacements.get(t, t)

        # Tags filtern
        valid_tags = []
        for tag in tags:
            if not tag:
                continue
            tag_lower = tag.lower().strip()
            if tag_lower in self.IGNORE_SECONDARY:
                self.logger.debug(f"🏷️ [PRIO] Ignoriere Tag: {tag_lower!r}")
                continue
            if artist_name and tag_lower == artist_name.lower():
                self.logger.debug(
                    f"🏷️ [PRIO] Ignoriere Artist-Name als Tag: {tag_lower!r}"
                )
                continue
            valid_tags.append(normalize_for_matching(tag_lower))

        if not valid_tags:
            self.logger.debug("🏷️ [PRIO] Keine validen Tags nach Filterung")
            return "Unknown", []

        self.logger.debug(f"🏷️ [PRIO] Valide Tags: {valid_tags}")

        # Prioritäten sammeln
        tag_priorities = []
        for tag in valid_tags:
            normalized_tag = self.normalize_genre_name(tag).lower()
            priority = self.GENRE_PRIORITY.get(normalized_tag)
            if priority is None:
                priority = self.GENRE_PRIORITY.get(tag)
            if priority is not None:
                tag_priorities.append((normalized_tag, priority))
                self.logger.debug(
                    f"🏷️ [PRIO] Tag '{tag}' → normalisiert '{normalized_tag}' "
                    f"→ Priorität {priority}"
                )
            else:
                self.logger.debug(
                    f"🏷️ [PRIO] Tag '{tag}' nicht in Hierarchie gefunden"
                )

        if not tag_priorities:
            primary = self.normalize_genre_name(valid_tags[0])
            secondary = [
                self.normalize_genre_name(t)
                for t in valid_tags[1:6]
                if self.normalize_genre_name(t) != primary
            ]
            return primary, secondary

        # Absteigend sortieren (höhere Priorität = spezifischer = gewinnt)
        tag_priorities.sort(key=lambda x: (-x[1], x[0]))

        best_normalized = tag_priorities[0][0]
        self.logger.debug(f"🏷️ [PRIO] Bestes normalisiertes Genre: {best_normalized}")

        # Korrektur-Map für korrekte Großschreibung
        correction_map = {
            "ruhrpott rap": "Ruhrpott Rap",
            "hamburger schule": "Hamburger Rap",
            "hamburger rap": "Hamburger Rap",
            "berliner rap": "Berliner Rap",
            "kölsch rap": "Kölsch Rap",
            "münchner rap": "Münchner Rap",
            "stuttgarter rap": "Stuttgarter Rap",
            "österreichischer rap": "Österreichischer Rap",
            "schweizer rap": "Schweizer Rap",
            "deutscher street rap": "Deutscher Street Rap",
            "deutscher trap": "Deutscher Trap",
            "deutscher drill": "Deutscher Drill",
        }
        primary = correction_map.get(best_normalized, best_normalized.title())

        # Sekundär-Genres
        secondary = []
        seen = {primary.lower()}
        for norm_tag, _ in tag_priorities[1:]:
            if norm_tag not in seen:
                seen.add(norm_tag)
                corrected = correction_map.get(norm_tag, norm_tag.title())
                secondary.append(corrected)
            if len(secondary) >= 5:
                break

        self.logger.debug(
            f"🏷️ [PRIO] Ergebnis: primary={primary!r}, secondary={secondary!r}"
        )
        return primary, secondary

    def normalize_genre_name(self, genre: str) -> str:
        """
        Normalisiert einen Genre-Namen für konsistente Schreibweise.

        Beispiele:
            "rnb"      → "R&B"
            "hip hop"  → "Hip Hop"
            "neo-soul" → "Neo Soul"
        """
        if not genre:
            return "Unknown"

        genre_lower = genre.lower().strip()

        # Direkter Match in Normalisierungsmap
        if genre_lower in self.GENRE_NORMALIZATION:
            return self.GENRE_NORMALIZATION[genre_lower]

        # Teilstring-Match für zusammengesetzte Begriffe
        for key, value in self.GENRE_NORMALIZATION.items():
            if key in genre_lower:
                return value

        # Fallback: Kapitalisierung
        words = genre.split()
        small_words = {"and", "of", "the", "a", "an", "in", "to", "for", "with", "on", "at", "by"}
        capitalized = " ".join(
            w if w.lower() in small_words else w.capitalize()
            for w in words
        )
        return capitalized

    # ─────────────────────────────────────────────────────────────────────────
    # Konvertierungs-Hilfsmethode (neu in v2.1)
    # ─────────────────────────────────────────────────────────────────────────

    def _mapping_to_result(
        self,
        mapping,
        source: str = "unknown",
        confidence: float = 1.0,
        auto_learn_disabled: bool = False,
        mb_ids: Optional[Dict[str, Any]] = None,
    ):
        """
        Konvertiert ein GenreMapping sicher zu einem neuen GenreResult.

        Mutiert das originale mapping-Objekt NICHT – erstellt immer eine Kopie.
        Damit wird verhindert, dass Singleton-Objekte aus dem GenreMapper-Cache
        durch Attributzuweisungen korrumpiert werden.
        """
        from utils.genre_map import GenreResult

        return GenreResult(
            primary=mapping.primary,
            secondary=list(mapping.secondary or []),
            source=source,
            confidence=confidence,
            matched_key=getattr(mapping, "matched_key", None),
            matched_score=getattr(mapping, "matched_score", None),
            raw_tags=[],
            mb_ids=mb_ids,
            auto_learn_disabled=auto_learn_disabled,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Hierarchie-basierte Priorität
    # ─────────────────────────────────────────────────────────────────────────

    def _calculate_genre_priority_from_hierarchy(self) -> Dict[str, int]:
        """
        Berechnet aus genre_hierarchy.yaml eine Prioritäts-Map.

        Prioritätsregeln:
          - Je spezifischer (tiefer in der Hierarchie), desto höher die Priorität
          - Tiefe 0 = Hauptgenres
          - Tiefe 1 = Subgenres
          - Tiefe 2 = Sub-Subgenres
        """
        try:
            import yaml

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            hierarchy_file = mapping_dir / "genre_hierarchy.yaml"

            if not hierarchy_file.exists():
                self.logger.warning(
                    "⚠️ genre_hierarchy.yaml nicht gefunden – verwende Fallback"
                )
                return self._get_fallback_priority()

            with open(hierarchy_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            hierarchy = data.get("GENRE_HIERARCHY", {})
            genre_depth: Dict[str, int] = {}

            # Children-Map aufbauen (Parent → Liste von Children)
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

                if genre not in genre_depth or current_depth < genre_depth.get(genre, 999):
                    genre_depth[genre] = current_depth

                if genre in children_map:
                    for child in children_map[genre]:
                        calculate_depth(child, current_depth + 1, visited)

            # Top-Level: Alle mit parent == None
            top_level = [genre for genre, parent in hierarchy.items() if parent is None]
            if not top_level:
                top_level = ["Deutschrap", "Hip Hop", "Pop", "Rock", "Electronic", "R&B"]

            self.logger.info(
                f"🏷️ {len(top_level)} Top-Level-Genres in Hierarchie gefunden"
            )

            for top in top_level:
                calculate_depth(top, 0)

            # Stelle sicher, dass alle Keys eine Tiefe haben
            for genre in hierarchy.keys():
                if genre not in genre_depth:
                    parent = hierarchy.get(genre)
                    if parent and parent in genre_depth:
                        genre_depth[genre] = genre_depth[parent] + 1
                    else:
                        genre_depth[genre] = 0

            normalized_priority = {
                genre.lower(): depth for genre, depth in genre_depth.items()
            }

            self.logger.info(
                f"🏷️ {len(normalized_priority)} Genre-Prioritäten aus "
                f"genre_hierarchy.yaml berechnet "
                f"(Tiefe 0-{max(normalized_priority.values()) if normalized_priority else 0})"
            )

            return normalized_priority

        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Berechnen der Genre-Prioritäten: {e}")
            return self._get_fallback_priority()

    def _get_fallback_priority(self) -> Dict[str, int]:
        """Fallback-Prioritäten für den Fall, dass keine Hierarchie-Datei existiert."""
        return {
            "deutschrap": 0,
            "hip hop": 0,
            "pop": 0,
            "rock": 0,
            "electronic": 0,
            "ruhrpott rap": 1,
            "berliner rap": 1,
            "hamburger rap": 1,
            "hamburger schule": 1,
            "kölsch rap": 1,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Private Hilfsmethoden
    # ─────────────────────────────────────────────────────────────────────────

    def _prepare_search_title(self, title: str) -> str:
        """Bereinigt einen Titel für externe API-Suchen."""
        search_title = title
        if " - " in search_title:
            search_title = search_title.split(" - ", 1)[1].strip()

        cleanup_patterns = [
            (r"\s*\(official\s+music\s+video\)", ""),
            (r"\s*\(official\s+video\)", ""),
            (r"\s*\(music\s+video\)", ""),
            (r"\s*\(official\)", ""),
            (r"\s*\[official\s+music\s+video\]", ""),
            (r"\s*\[official\s+video\]", ""),
            (r"\s*\[music\s+video\]", ""),
            (r"\s*\(lyric\s+video\)", ""),
            (r"\s*\(audio\)", ""),
            (r"\s*\(visualizer\)", ""),
            (r"\s*\(Live\)", ""),
            (r"\s*\(Remastered\)", ""),
            (r"\s*\(Remaster\)", ""),
            (r"\s*\(HD\)", ""),
            (r"\s*\(4K\)", ""),
            (r"\s*\(Explicit\)", ""),
            (r"\s*\(clean version\)", ""),
            (r"\s*\[.*?\]", ""),
            (r"\s*\(.*?\)$", ""),
        ]
        for pattern, replacement in cleanup_patterns:
            search_title = re.sub(
                pattern, replacement, search_title, flags=re.IGNORECASE
            ).strip()

        return re.sub(r"\s+", " ", search_title).strip()

    async def _fetch_genre_from_musicbrainz(
        self, artist_name: str, search_title: str, mb_client
    ):
        """
        Holt Genre von MusicBrainz.
        Gibt immer GenreResult zurück (nie GenreMapping).
        """
        from utils.genre_map import GenreResult

        if mb_client is None:
            return None
        try:
            self.logger.debug(
                f"🎵 MusicBrainz Suche für: {artist_name} - {search_title}"
            )
            mb_data = await mb_client.fetch_metadata(search_title, artist_name)

            if not mb_data:
                return None

            _mb_ids = {
                "recording_id": (
                    mb_data.get("recording_id")
                    or mb_data.get("musicbrainz_recording_id")
                ),
                "release_id": (
                    mb_data.get("release_id")
                    or mb_data.get("musicbrainz_release_id")
                ),
                "release_group_id": (
                    mb_data.get("release_group_id")
                    or mb_data.get("musicbrainz_release_group_id")
                ),
                "artist_id": (
                    mb_data.get("artist_id")
                    or mb_data.get("musicbrainz_artist_id")
                ),
                "isrc": mb_data.get("isrc"),
            }
            _has_ids = any(_mb_ids.values())

            raw_mb_genre = mb_data.get("genre", "")
            has_genre = bool(raw_mb_genre and raw_mb_genre != "unknown")

            if has_genre:
                self.logger.info(f"🎵 MusicBrainz lieferte Genre: '{raw_mb_genre}'")
                # determine_genre() gibt GenreResult zurück
                mb_genre_result = self.genre_mapper.determine_genre(
                    raw_genre=raw_mb_genre,
                    artist_name=artist_name,
                )
                if mb_genre_result and mb_genre_result.primary:
                    # GenreResult ist ein normaler Dataclass → direkte Zuweisung OK
                    mb_genre_result.raw_tags = mb_data.get("tags", []) or []
                    mb_genre_result.secondary = mb_genre_result.secondary or []
                    if _has_ids:
                        mb_genre_result.mb_ids = _mb_ids
                    return mb_genre_result

            # Nur IDs, kein Genre
            if _has_ids:
                sentinel = GenreResult(
                    primary="",
                    secondary=[],
                    source="musicbrainz_ids_only",
                    confidence=0.0,
                    mb_ids=_mb_ids,
                )
                return sentinel

        except Exception as e:
            self.logger.debug(f"🏷️ MusicBrainz Fehler: {e}")
        return None

    async def _fetch_genre_from_lastfm(
        self, artist_name: str, search_title: str, lfm_client
    ):
        """
        Holt Genre von Last.fm.
        Gibt GenreResult zurück.
        """
        from utils.genre_map import GenreResult

        if lfm_client is None:
            return None
        try:
            self.logger.debug(
                f"🎵 Last.fm Suche für: {artist_name} - {search_title}"
            )
            lfm_data = await lfm_client.fetch_metadata(
                search_title, artist_name, include_genre=True
            )

            if not lfm_data:
                return None

            raw_lfm_genre = lfm_data.get("genre", "")
            tags = lfm_data.get("tags", [])

            if raw_lfm_genre and "," in raw_lfm_genre and not tags:
                tags = [
                    t.strip().lower()
                    for t in raw_lfm_genre.split(",")
                    if t.strip()
                ]

            if not tags:
                return None

            self.logger.info(f"🎵 Last.fm lieferte {len(tags)} Tags: {tags[:5]}...")

            primary_genre, secondary_genres = self.prioritize_genres(
                tags, artist_name=artist_name
            )

            if primary_genre and primary_genre != "Unknown":
                return GenreResult(
                    primary=primary_genre,
                    secondary=secondary_genres[:5],
                    source="lastfm_prioritized",
                    confidence=0.85,
                    raw_tags=tags,
                )

            return None

        except Exception as e:
            self.logger.debug(f"🏷️ Last.fm Fehler: {e}", exc_info=True)
            return None

    def _infer_genre_from_feat_artists(self, feat_artists: List[str]):
        """Inferiert Genre aus Feature-Artists."""
        from collections import Counter
        from utils.genre_map import GenreResult

        feat_genres = []
        for feat in feat_artists:
            feat_entry = self.genre_mapper.get_artist_entry(feat.strip().lower())
            if feat_entry and feat_entry.primary:
                feat_genres.append(feat_entry.primary)

        if not feat_genres:
            return None

        most_common, count = Counter(feat_genres).most_common(1)[0]
        self.logger.info(
            f"🏷️ Genre aus Feature-Artists inferiert: '{most_common}' "
            f"(via {feat_artists}, Votes: {count}/{len(feat_genres)})"
        )

        return GenreResult(
            primary=most_common,
            secondary=[],
            source="feature_inference",
            confidence=0.7,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # YAML-Loader
    # ─────────────────────────────────────────────────────────────────────────

    def _load_ignore_secondary_from_yaml(self) -> Set[str]:
        try:
            import yaml

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            filter_file = mapping_dir / "genre_filters.yaml"

            if not filter_file.exists():
                return self._get_default_ignore_secondary()

            with open(filter_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            ignore_set = set(data.get("IGNORE_SECONDARY", []))
            self.logger.info(
                f"🏷️ {len(ignore_set)} zu ignorierende Sekundär-Genres geladen"
            )
            return ignore_set

        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Laden der Ignore-Liste: {e}")
            return self._get_default_ignore_secondary()

    def _get_default_ignore_secondary(self) -> Set[str]:
        return {
            "electronic", "united states", "seen live", "female vocalists",
            "male vocalists", "indie", "alternative", "pop", "rock",
            "2020s", "2010s", "2000s", "american", "british", "german",
            "english", "instrumental", "acoustic", "cover", "live", "remix",
            "explicit", "clean", "edit", "radio edit", "extended mix",
            "club mix", "dub mix", "instrumental version", "karaoke",
            "soundtrack", "background music", "atmospheric", "chill",
            "relaxing", "calm", "upbeat", "energetic", "catchy",
            "melodic", "rhythmic",
        }

    def _load_genre_normalization_from_yaml(self) -> Dict[str, str]:
        try:
            import yaml

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            aliases_file = mapping_dir / "genre_aliases.yaml"

            if not aliases_file.exists():
                self.logger.warning("⚠️ genre_aliases.yaml nicht gefunden")
                return self._get_fallback_normalization()

            with open(aliases_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            aliases = data.get("GENRE_ALIASES", {})
            normalization = {
                alias.lower(): canonical for alias, canonical in aliases.items()
            }
            self.logger.info(
                f"🏷️ {len(normalization)} Genre-Normalisierungen "
                f"aus genre_aliases.yaml geladen"
            )
            return normalization

        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Laden der Genre-Normalisierung: {e}")
            return self._get_fallback_normalization()

    def _get_fallback_normalization(self) -> Dict[str, str]:
        return {
            "rnb": "R&B",
            "r&b": "R&B",
            "rhythm and blues": "R&B",
            "hip hop": "Hip Hop",
            "deutschrap": "Deutschrap",
            "neo-soul": "Neo Soul",
        }
