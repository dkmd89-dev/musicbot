# services/metadata/auto_learn.py
# -*- coding: utf-8 -*-

import asyncio
import re
import time
import yaml
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Dict, List, Any, Optional, Set, Tuple, TYPE_CHECKING
from logger import get_module_logger

if TYPE_CHECKING:
    from utils.artist_map import ArtistNormalizer
    from utils.genre_map import GenreMapper


class _InlineListDumper(yaml.SafeDumper):
    """YAML-Dumper mit Inline-Listen (flow_style) fuer 'secondary' - vorher
    ein lokales Duplikat innerhalb von learn_genre(), jetzt einmalig auf
    Modulebene, da von _write_yaml_atomic() fuer alle drei Schreibpfade
    gemeinsam genutzt."""

    def represent_list(self, data):
        return self.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


_InlineListDumper.add_representer(list, _InlineListDumper.represent_list)


class AutoLearnManager:
    """
    Verwaltet das automatische Lernen von Artist- und Genre-Informationen.

    Schreibt ausschließlich in:
      - auto_learned_artists.yaml  (Artist-Aliase)
      - auto_learned_genre.yaml    (Genre-Zuordnungen)
      - known_artists.yaml         (bestaetigte Identitaets-Mappings)

    Liest NIEMALS aus artist_overrides.yaml oder artist_genre.yaml heraus,
    aber prüft diese als Duplikat-Schutz.

    INV-01/INV-02 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md, Abschnitt 27):
    Alle drei Schreibpfade liefen frueher synchron (open(mode="w")) direkt
    im Event-Loop-Thread, ohne asyncio.to_thread() und ohne Lock. Die
    Read-Modify-Write-Sequenz enthielt keinen await-Punkt, wodurch
    asyncios kooperatives Scheduling zufaellig eine Serialisierung
    zwischen gleichzeitig laufenden Tracks (MAX_CONCURRENT_DOWNLOADS=3)
    herstellte. Ein naiver asyncio.to_thread()-Fix ohne Lock haette diese
    zufaellige Sicherheit aufgehoben und eine echte Lost-Update-Race
    zwischen zwei parallelen Worker-Threads eingefuehrt. Der Fix
    kombiniert daher beides: asyncio.to_thread() fuer INV-01 (Event-Loop
    bleibt frei) PLUS ein threading.Lock (self._write_lock, Vorbild
    utils/artist_map.py::_write_lock) fuer die Serialisierung ueber echte
    OS-Threads hinweg, PLUS atomares Schreiben (tmp-Datei + Path.replace)
    fuer INV-02 (Vorbild utils/metadata_cache.py::store()).
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
        # INV-01/INV-02: ein gemeinsames Lock fuer alle drei Schreibpfade
        # (auto_learned_genre.yaml, known_artists.yaml,
        # auto_learned_artists.yaml) - bewusst EIN Lock statt drei
        # dateispezifischen Locks, da Schreibfrequenz niedrig ist und ein
        # einzelnes Lock die Komplexitaet/Deadlock-Flaeche minimiert
        # (CLAUDE.md §18: kleinste sinnvolle Aenderung).
        self._write_lock = Lock()

    # ─────────────────────────────────────────────────────────────────────────
    # Gemeinsame atomare Schreib-Hilfsmethode (INV-02)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _write_yaml_atomic(path: Path, data: dict, inline_lists: bool = False) -> None:
        """
        Schreibt YAML atomar (write-tmp -> rename), analog zu
        MetadataCache.store() (utils/metadata_cache.py). Muss unter
        self._write_lock aufgerufen werden.
        """
        import yaml

        tmp_path = path.with_suffix(f".tmp_{int(time.time() * 1000)}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    data,
                    f,
                    Dumper=_InlineListDumper if inline_lists else yaml.SafeDumper,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=True,
                )
            tmp_path.replace(path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

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

        # Sekundäre Genres bestimmen (reine In-Memory-Berechnung, kein I/O)
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

        entry = {
            "primary": genre_result.primary,
            "secondary": secondary_genres if secondary_genres else [],
            "description": "Auto-learned via Last.fm (rule)",
        }

        try:
            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            auto_genre_path = mapping_dir / "auto_learned_genre.yaml"

            written = await asyncio.to_thread(
                self._write_genre_entry_sync,
                auto_genre_path,
                canonical_name.strip(),
                entry,
            )

            if not written:
                self.logger.debug(
                    f"🧠 [AUTO-LEARN] Genre für '{canonical_name}' bereits in YAML "
                    f"vorhanden (Race-Schutz beim Schreiben erkannt)"
                )
                return False

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

    def _write_genre_entry_sync(
        self, auto_genre_path: Path, key_yaml: str, entry: dict
    ) -> bool:
        """
        Liest, prueft (Double-Check gegen Race) und schreibt einen einzelnen
        Genre-Eintrag atomar. Laeuft in einem Worker-Thread (asyncio.to_thread)
        - self._write_lock serialisiert konkurrierende Aufrufe ueber echte
        OS-Threads hinweg (INV-01+INV-02 kombiniert, siehe Klassen-Docstring).
        """
        with self._write_lock:
            data: dict = {}
            if auto_genre_path.exists():
                with open(auto_genre_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}

            genre_map = data.get("ARTIST_GENRE_MAP", {})
            if key_yaml in genre_map:
                # Double-Check: ein anderer Thread hat den Eintrag zwischen
                # dem async-seitigen Vorab-Check und dem Erwerb des Locks
                # bereits geschrieben.
                return False

            genre_map[key_yaml] = entry
            data["ARTIST_GENRE_MAP"] = genre_map

            self._write_yaml_atomic(auto_genre_path, data, inline_lists=True)
            return True

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
            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            known_file = mapping_dir / "known_artists.yaml"

            written = await asyncio.to_thread(
                self._write_known_artist_sync, known_file, artist_name
            )
            if written:
                self.logger.info(
                    f"🧠 [AUTO-LEARN] ✅ Bekannter Künstler gespeichert: '{artist_name}'"
                )
            return written

        except Exception as e:
            self.logger.warning(
                f"⚠️ [AUTO-LEARN] known_artists.yaml fehlgeschlagen: {e}"
            )
        return False

    def _write_known_artist_sync(self, known_file: Path, artist_name: str) -> bool:
        """Sync-Kern von _save_known_artist() - siehe Klassen-Docstring INV-01/INV-02."""
        with self._write_lock:
            data = {"known_artists": []}
            if known_file.exists():
                with open(known_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {"known_artists": []}

            known_artists = set(a.lower() for a in data.get("known_artists", []))
            if artist_name.lower() in known_artists:
                return False

            data.setdefault("known_artists", []).append(artist_name)
            data["known_artists"] = sorted(set(data["known_artists"]))

            self._write_yaml_atomic(known_file, data)
            return True

    async def _save_alias(self, raw_name: str, canonical_name: str) -> bool:
        """Speichert einen Alias in auto_learned_artists.yaml"""
        try:
            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            alias_file = mapping_dir / "auto_learned_artists.yaml"

            written = await asyncio.to_thread(
                self._write_alias_sync, alias_file, raw_name, canonical_name
            )
            if written:
                self.logger.info(
                    f"🧠 [AUTO-LEARN] ✅ Alias gelernt: '{raw_name}' → '{canonical_name}'"
                )
            else:
                self.logger.debug(
                    f"🧠 [AUTO-LEARN] Alias '{raw_name}' bereits vorhanden"
                )
            return written

        except Exception as e:
            self.logger.warning(
                f"⚠️ [AUTO-LEARN] auto_learned_artists.yaml fehlgeschlagen: {e}"
            )
        return False

    def _write_alias_sync(
        self, alias_file: Path, raw_name: str, canonical_name: str
    ) -> bool:
        """Sync-Kern von _save_alias() - siehe Klassen-Docstring INV-01/INV-02."""
        with self._write_lock:
            data = {"auto_learned": {}}
            if alias_file.exists():
                with open(alias_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {"auto_learned": {}}

            auto_learned = data.get("auto_learned", {})
            if raw_name.casefold() in (k.casefold() for k in auto_learned.keys()):
                return False

            data["auto_learned"][raw_name] = canonical_name
            self._write_yaml_atomic(alias_file, data)
            return True

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
            r"channel$",
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

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            auto_file = mapping_dir / "auto_learned_artists.yaml"
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

            mapping_dir = Path(getattr(self.config, "GENRE_MAPPING_DIR", "mapping"))
            auto_file = mapping_dir / "auto_learned_genre.yaml"
            if not auto_file.exists():
                return {}

            with open(auto_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            return data.get("ARTIST_GENRE_MAP", {})
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Fehler beim Laden der auto_learned_genres: {e}")
            return {}
