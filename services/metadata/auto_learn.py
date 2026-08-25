# services/metadata/auto_learn.py
# -*- coding: utf-8 -*-

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Any, Optional, Set, Tuple, TYPE_CHECKING
from logger import get_module_logger

if TYPE_CHECKING:
    from utils.artist_map import ArtistNormalizer
    from utils.genre_map import GenreMapper


class AutoLearnManager:
    """
    Verwaltet das automatische Lernen von Artist- und Genre-Informationen.

    Schreibt ausschließlich in:
      - auto_learned_artists.yaml  (Artist-Aliase)
      - auto_learned_genre.yaml    (Genre-Zuordnungen)

    Liest NIEMALS aus artist_overrides.yaml oder artist_genre.yaml heraus,
    aber prüft diese als Duplikat-Schutz.
    """

    ALLOWED_ARTIST_SOURCES = {"youtube_parsed", "first_artist_from_title"}

    def __init__(
        self,
        config,
        artist_normalizer: "ArtistNormalizer",
        genre_mapper: "GenreMapper",
        logger=None,
    ):
        self.config = config
        self.artist_normalizer = artist_normalizer
        self.genre_mapper = genre_mapper
        self.logger = logger or get_module_logger("AutoLearnManager")

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ─────────────────────────────────────────────────────────────────────────

    async def learn_genre(
        self,
        canonical_name: str,
        genre_result,
        raw_name: str = "",
    ) -> bool:
        """
        Schreibt Genre-Informationen in auto_learned_genre.yaml.
        Gibt True zurück wenn ein neuer Eintrag geschrieben wurde, sonst False.

        Wird NICHT geschrieben wenn:
          - Genre bereits in artist_genre.yaml oder auto_learned_genre.yaml vorhanden
          - Artist in artist_overrides.json existiert
          - genre_result ist None oder hat kein primary-Genre
        """
        if not genre_result or not genre_result.primary:
            return False

        if self._is_genre_already_learned(canonical_name):
            self.logger.debug(
                f"🧠 [AUTO-LEARN] Genre für '{canonical_name}' bereits vorhanden (überspringe)"
            )
            return False

        # Prüfe ob Artist in artist_overrides.json existiert
        overrides_normalized = getattr(
            self.artist_normalizer, "overrides_normalized", {}
        )
        for override_key, override_val in overrides_normalized.items():
            if (
                override_val.lower() == canonical_name.lower()
                or override_key.lower() == canonical_name.lower()
            ):
                self.logger.info(
                    f"🧠 [AUTO-LEARN] '{canonical_name}' in artist_overrides.json gefunden → kein Auto-Learning"
                )
                return False

        self.logger.info(
            f"🧠 [AUTO-LEARN] Verarbeite Genre für '{canonical_name}': "
            f"'{genre_result.primary}' (Quelle: {getattr(genre_result, 'source', 'unknown')})"
        )

        try:
            import yaml

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            auto_genre_path = mapping_dir / "auto_learned_genre.yaml"

            data: dict = {}
            if auto_genre_path.exists():
                with open(auto_genre_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}

            genre_map = data.get("ARTIST_GENRE_MAP", {})
            key_yaml = canonical_name.strip()

            if key_yaml in genre_map:
                self.logger.debug(
                    f"🧠 [AUTO-LEARN] Genre für '{canonical_name}' bereits in YAML vorhanden"
                )
                return False

            # Sekundäre Genres bestimmen
            secondary_genres = []
            if hasattr(genre_result, "secondary") and genre_result.secondary:
                secondary_genres = list(genre_result.secondary[:5])
            elif hasattr(genre_result, "raw_tags") and genre_result.raw_tags:
                tag_list = [
                    t
                    for t in genre_result.raw_tags
                    if t.lower() != genre_result.primary.lower()
                ]
                secondary_genres = tag_list[:5]

            genre_map[key_yaml] = {
                "primary": genre_result.primary,
                "secondary": secondary_genres if secondary_genres else [],
                "description": "Auto-learned via Last.fm (rule)",
            }
            data["ARTIST_GENRE_MAP"] = genre_map

            # YAML mit Inline-Listen für secondary
            class InlineListDumper(yaml.SafeDumper):
                def represent_list(self, data):
                    return self.represent_sequence(
                        "tag:yaml.org,2002:seq", data, flow_style=True
                    )

            InlineListDumper.add_representer(list, InlineListDumper.represent_list)

            with open(auto_genre_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    data,
                    f,
                    Dumper=InlineListDumper,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=True,
                )

            self.logger.info(
                f"🧠 [AUTO-LEARN] ✅ Genre gelernt: '{canonical_name}' → "
                f"primary='{genre_result.primary}', "
                f"secondary={secondary_genres[:3] if secondary_genres else 'keine'}"
            )

            if hasattr(self.genre_mapper, "clear_caches"):
                self.genre_mapper.clear_caches()

            return True

        except Exception as e:
            self.logger.warning(f"⚠️ [AUTO-LEARN] Genre-YAML fehlgeschlagen: {e}")
            return False

    async def learn_artist(
        self,
        raw_name: str,
        canonical_name: str,
        source: str = "unknown",
        channel_name: str = "",
    ) -> bool:
        """
        Schreibt NUR Aliase in auto_learned_artists.yaml.
        Identitäts-Mappings (raw == canonical) gehen nach known_artists.yaml.
        """
        if source not in self.ALLOWED_ARTIST_SOURCES:
            self.logger.debug(f"🧠 [AUTO-LEARN] Überspringe Quelle '{source}'")
            return False

        if not raw_name or not canonical_name:
            return False

        raw_key = raw_name.strip()
        canonical_value = canonical_name.strip()

        # 1. Prüfe ob bereits bekannt
        if self._is_artist_known(canonical_value):
            self.logger.debug(f"🧠 [AUTO-LEARN] '{canonical_value}' bereits bekannt")
            return False

        # 2. Identitäts-Mapping (kein Alias) → known_artists.yaml
        if raw_key.casefold() == canonical_value.casefold():
            return await self._save_known_artist(canonical_value)

        # 3. Echter Alias → auto_learned_artists.yaml
        return await self._save_alias(raw_key, canonical_value)

    async def _save_known_artist(self, artist_name: str) -> bool:
        """Speichert einen bekannten Künstler in known_artists.yaml"""
        try:
            import yaml

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            known_file = mapping_dir / "known_artists.yaml"

            data = {"known_artists": []}
            if known_file.exists():
                with open(known_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {"known_artists": []}

            known_artists = set(a.lower() for a in data.get("known_artists", []))

            if artist_name.lower() not in known_artists:
                data.setdefault("known_artists", []).append(artist_name)
                # Sortieren für bessere Lesbarkeit
                data["known_artists"] = sorted(set(data["known_artists"]))

                with open(known_file, "w", encoding="utf-8") as f:
                    yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

                self.logger.info(
                    f"🧠 [AUTO-LEARN] ✅ Bekannter Künstler gespeichert: '{artist_name}'"
                )
                return True

        except Exception as e:
            self.logger.warning(
                f"⚠️ [AUTO-LEARN] known_artists.yaml fehlgeschlagen: {e}"
            )
        return False

    async def _save_alias(self, raw_name: str, canonical_name: str) -> bool:
        """Speichert einen Alias in auto_learned_artists.yaml"""
        try:
            import yaml

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            alias_file = mapping_dir / "auto_learned_artists.yaml"

            data = {"auto_learned": {}}
            if alias_file.exists():
                with open(alias_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {"auto_learned": {}}

            auto_learned = data.get("auto_learned", {})

            # Prüfe ob Alias bereits existiert
            if raw_name.casefold() in (k.casefold() for k in auto_learned.keys()):
                self.logger.debug(
                    f"🧠 [AUTO-LEARN] Alias '{raw_name}' bereits vorhanden"
                )
                return False

            data["auto_learned"][raw_name] = canonical_name

            with open(alias_file, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

            self.logger.info(
                f"🧠 [AUTO-LEARN] ✅ Alias gelernt: '{raw_name}' → '{canonical_name}'"
            )
            return True

        except Exception as e:
            self.logger.warning(
                f"⚠️ [AUTO-LEARN] auto_learned_artists.yaml fehlgeschlagen: {e}"
            )
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # Hilfsmethoden
    # ─────────────────────────────────────────────────────────────────────────

    def _is_genre_already_learned(self, artist_name: str) -> bool:
        """
        Prüft ob Genre bereits in artist_genre.yaml oder auto_learned_genre.yaml
        existiert (case-insensitive).
        """
        try:
            import yaml

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))

            def search_in_map(genre_map: dict, search_name: str) -> bool:
                if not genre_map:
                    return False
                search_lower = search_name.lower()
                if search_name in genre_map:
                    return True
                for key in genre_map.keys():
                    if key.lower() == search_lower:
                        return True
                return False

            # Prüfe artist_genre.yaml (manuell)
            manual_file = mapping_dir / "artist_genre.yaml"
            if manual_file.exists():
                with open(manual_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                genre_map = data.get("ARTIST_GENRE_MAP", {})
                if search_in_map(genre_map, artist_name):
                    self.logger.debug(
                        f"🧠 [AUTO-LEARN] '{artist_name}' in artist_genre.yaml gefunden → überspringe"
                    )
                    return True

            # Prüfe auto_learned_genre.yaml
            auto_file = mapping_dir / "auto_learned_genre.yaml"
            if auto_file.exists():
                with open(auto_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                genre_map = data.get("ARTIST_GENRE_MAP", {})
                if search_in_map(genre_map, artist_name):
                    self.logger.debug(
                        f"🧠 [AUTO-LEARN] '{artist_name}' in auto_learned_genre.yaml gefunden → überspringe"
                    )
                    return True

        except Exception as e:
            self.logger.debug(f"Fehler in _is_genre_already_learned: {e}")
        return False

    def _is_artist_known(self, artist_name: str) -> bool:
        """Prüft ob Artist bekannt ist (Library, Overrides, known_artists.yaml, auto_learned_artists.yaml)"""
        if not artist_name:
            return False

        artist_key = artist_name.strip().casefold()

        # 1. Library Artists
        if hasattr(self.artist_normalizer, "library_artists"):
            for lib_artist in self.artist_normalizer.library_artists:
                if str(lib_artist).casefold() == artist_key:
                    return True

        # 2. Overrides
        if hasattr(self.artist_normalizer, "overrides_normalized"):
            for (
                override_key,
                override_val,
            ) in self.artist_normalizer.overrides_normalized.items():
                if (
                    str(override_key).casefold() == artist_key
                    or str(override_val).casefold() == artist_key
                ):
                    return True

        # 3. known_artists.yaml (neu)
        try:
            import yaml

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            known_file = mapping_dir / "known_artists.yaml"
            if known_file.exists():
                with open(known_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                known_artists = data.get("known_artists", [])
                if artist_name in known_artists or any(
                    a.casefold() == artist_key for a in known_artists
                ):
                    return True
        except Exception:
            pass

        # 4. auto_learned_artists.yaml (Alias-Quellen und -Ziele)
        try:
            import yaml

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            alias_file = mapping_dir / "auto_learned_artists.yaml"
            if alias_file.exists():
                with open(alias_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                auto_learned = data.get("auto_learned", {})
                for raw_alias, canonical in auto_learned.items():
                    if (
                        str(raw_alias).casefold() == artist_key
                        or str(canonical).casefold() == artist_key
                    ):
                        return True
        except Exception:
            pass

        return False

    def _is_non_artist_channel(self, channel: str) -> bool:
        """
        Prüft ob ein Channel-Name auf einen Nicht-Artist-Channel hindeutet
        (Label, Compilation, Playlist, etc.).
        """
        if not channel:
            return False
        channel_lower = channel.strip().lower()
        non_artist_patterns = [
            r" - topic$",
            r"topic$",
            r"vevo$",
            r"music$",
            r"official$",
            r"records$",
            r"entertainment$",
            r"^various artists",
            r"compilation",
            r"playlist",
            r"mix$",
            r"hd$",
            r"lyrics$",
            r"beatz$",
            r"type beat",
        ]
        for pattern in non_artist_patterns:
            if re.search(pattern, channel_lower, re.IGNORECASE):
                self.logger.debug(f"🧠 [AUTO-LEARN] Non-Artist-Channel: '{channel}'")
                return True
        return False

    def create_genre_info_from_result(
        self, genres_result, raw_tags=None
    ) -> SimpleNamespace:
        """
        Konvertiert ein GenreResult-Objekt in ein serialisierbares SimpleNamespace.
        Nützlich für Auto-Learning wenn das Original-Objekt nicht direkt verwendbar ist.
        """
        return SimpleNamespace(
            primary=genres_result.primary,
            secondary=list(getattr(genres_result, "secondary", [])),
            source=getattr(genres_result, "source", "unknown"),
            raw_tags=list(raw_tags or getattr(genres_result, "raw_tags", [])),
        )

    def _load_auto_learned_artists(self) -> Dict[str, str]:
        """Lädt auto_learned_artists.yaml"""
        try:
            import yaml

            auto_file = self.mapping_dir / "auto_learned_artists.yaml"
            if not auto_file.exists():
                return {}

            with open(auto_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            return data.get("auto_learned", {})
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Fehler beim Laden der auto_learned_artists: {e}")
            return {}

    def _load_auto_learned_genres(self) -> Dict[str, Any]:
        """Lädt auto_learned_genre.yaml"""
        try:
            import yaml

            auto_file = self.mapping_dir / "auto_learned_genre.yaml"
            if not auto_file.exists():
                return {}

            with open(auto_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            return data.get("ARTIST_GENRE_MAP", {})
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Fehler beim Laden der auto_learned_genres: {e}")
            return {}
