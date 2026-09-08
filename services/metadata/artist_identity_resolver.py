# services/metadata/artist_identity_resolver.py
# -*- coding: utf-8 -*-
"""
ArtistIdentityResolver
======================

ARCH — Artist Identity Resolution & Mapping Separation (Phase B, Schritt 3/4).

Dedizierte Komponente, die die gesamte Artist-**Identitäts**-Entscheidung
bündelt – getrennt von der reinen String-Normalisierung (`ArtistNormalizer`)
und vom Lernen unbekannter Beziehungen (`AutoLearnManager`).

Verantwortungsgrenzen (CLAUDE.md §4):

    ArtistNormalizer          = Text normalisieren
    ArtistIdentityResolver    = Identität bestimmen   ← diese Datei
    AutoLearnManager          = unbekannte Identitäten/Aliase lernen
    artist_overrides.json     = manuelle Autorität

Fachliche Priorität (höchste zuerst) – ein niedriger priorisiertes Signal
darf NIEMALS einen höher priorisierten autoritativen Eintrag überschreiben:

    artist_override  >  known_artist  >  auto_learned_alias
                     >  library_identity  >  musicbrainz_mbid  >  parser

Quellen:
  1. mapping/artist_overrides.json              → source="artist_override"
  2. mapping/known_artists.yaml                 → source="known_artist"
  3. mapping/auto_learned_artist_aliases.json   → source="auto_learned_alias"
     (nur echte raw→canonical-Aliase, KEINE Self-Aliases "X"→"X")
  4. Library-Artist-Ordner                      → source="library_identity"
  5. MusicBrainz-Artist-MBID                    → source="musicbrainz_mbid"
     (Phase F – hier noch NICHT implementiert, siehe _resolve_mbid())
  6. sonst                                      → source="parser", known=False

────────────────────────────────────────────────────────────────────────────
Phase C (Finding F-05, erledigt)
────────────────────────────────────────────────────────────────────────────
`utils/artist_map.py` schreibt Library-Ordnernamen NICHT mehr persistent
nach mapping/artist_overrides.json. Die Datei ist wieder eine reine manuelle
Override-Quelle; Library-Artists werden hier über Stufe 4
(`source="library_identity"`) aus `ArtistNormalizer.library_index`
aufgelöst (per `refresh()` aktualisierbar). Bereits früher automatisch
erzeugte Einträge in artist_overrides.json bleiben unangetastet (Bereinigung
= Phase E) - solche Artists melden weiterhin `source="artist_override"`
(known=True, Gate identisch), bis der jeweilige Alt-Eintrag entfernt wird.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from logger import get_module_logger
from .models import ArtistIdentity


class ArtistIdentityResolver:
    """Löst einen (ggf. bereits string-normalisierten) Artist-Namen gegen die
    bekannten Identitätsquellen auf und liefert eine `ArtistIdentity`."""

    def __init__(self, artist_normalizer, mapping_dir, logger=None):
        """
        artist_normalizer:
            Instanz von ArtistNormalizer. Wird für die reine
            String-Normalisierung (`normalize()`) und – übergangsweise – für
            den Library-Artist-Bestand (`library_artists`) verwendet. Der
            Resolver reimplementiert KEINE Textnormalisierung.
        mapping_dir:
            Verzeichnis mit artist_overrides.json / known_artists.yaml /
            auto_learned_artist_aliases.json.
        """
        self._normalizer = artist_normalizer
        self._mapping_dir = Path(mapping_dir) if mapping_dir else Path("mapping")
        self.logger = logger or get_module_logger("ArtistIdentityResolver")

        # normalisierte Lookup-Tabellen (Aufbau in _load())
        self._override_exact: Dict[str, str] = {}
        self._override_norm: Dict[str, str] = {}
        self._override_values_norm: Dict[str, str] = {}
        self._known_norm: Dict[str, str] = {}
        self._alias_exact: Dict[str, str] = {}
        self._alias_norm: Dict[str, str] = {}
        self._library_norm: Dict[str, str] = {}

        self._load()

    # ─────────────────────────────────────────────────────────────────────────
    # Laden / Aktualisieren
    # ─────────────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Lädt alle Identitätsquellen neu (z.B. nachdem ein Download einen
        neuen Library-Ordner erzeugt oder AutoLearn geschrieben hat).

        Scannt dabei auch das Library-Verzeichnis neu
        (ArtistNormalizer.refresh_library_index()), damit ein in derselben
        Session neu angelegter Kuenstler-Ordner sofort als bekannte
        Identitaet erkannt wird."""
        refresh_lib = getattr(self._normalizer, "refresh_library_index", None)
        if callable(refresh_lib):
            try:
                refresh_lib()
            except Exception as e:
                self.logger.debug(f"refresh_library_index() fehlgeschlagen: {e}")
        self._load()

    def _key(self, value: str) -> str:
        """Normalisierter Vergleichsschlüssel – identisch zu der Logik, mit der
        ArtistNormalizer seine `overrides_normalized`-Tabelle aufbaut
        (case-/akzent-insensitiv)."""
        norm_key = getattr(self._normalizer, "_normalize_key", None)
        if callable(norm_key):
            try:
                return norm_key(value)
            except Exception:
                pass
        return (value or "").strip().casefold()

    def _load(self) -> None:
        self._override_exact, self._override_norm, self._override_values_norm = (
            self._load_overrides()
        )
        self._known_norm = self._load_known_artists()
        self._alias_exact, self._alias_norm = self._load_aliases()
        self._library_norm = self._load_library()

        self.logger.debug(
            "🆔 ArtistIdentityResolver geladen: "
            f"{len(self._override_exact)} Overrides, "
            f"{len(self._known_norm)} known_artists, "
            f"{len(self._alias_exact)} Aliase, "
            f"{len(self._library_norm)} Library-Artists"
        )

    def _override_file(self) -> Path:
        """Pfad zu artist_overrides.json - bevorzugt exakt die Datei, die der
        ArtistNormalizer geladen hat (ArtistConfig.override_file), sonst
        <mapping_dir>/artist_overrides.json. In Produktion identisch
        (Config.ARTIST_OVERRIDE_FILE == Config.GENRE_MAPPING_DIR/artist_overrides.json)."""
        cfg = getattr(self._normalizer, "config", None)
        override_file = getattr(cfg, "override_file", None)
        if override_file:
            return Path(override_file)
        return self._mapping_dir / "artist_overrides.json"

    def _load_overrides(self):
        exact: Dict[str, str] = {}
        norm: Dict[str, str] = {}
        values_norm: Dict[str, str] = {}
        path = self._override_file()
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                for raw_key, canonical in data.items():
                    k = str(raw_key).strip()
                    v = str(canonical).strip()
                    exact[k] = v
                    norm[self._key(k)] = v
                    values_norm.setdefault(self._key(v), v)
        except Exception as e:
            self.logger.warning(f"⚠️ artist_overrides.json nicht lesbar: {e}")
        return exact, norm, values_norm

    def _load_known_artists(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        path = self._mapping_dir / "known_artists.yaml"
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                for name in data.get("known_artists", []) or []:
                    n = str(name).strip()
                    if n:
                        result.setdefault(self._key(n), n)
        except Exception as e:
            self.logger.warning(f"⚠️ known_artists.yaml nicht lesbar: {e}")
        return result

    def _load_aliases(self):
        exact: Dict[str, str] = {}
        norm: Dict[str, str] = {}
        path = self._mapping_dir / "auto_learned_artist_aliases.json"
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                for raw_key, canonical in (data.get("auto_learned", {}) or {}).items():
                    k = str(raw_key).strip()
                    v = str(canonical).strip()
                    # Schritt 11: KEINE Self-Aliases – "X" → "X" ist eine
                    # Identität (gehört nach known_artists.yaml), kein Alias.
                    if not k or not v or k.casefold() == v.casefold():
                        continue
                    exact[k] = v
                    norm[self._key(k)] = v
        except Exception as e:
            self.logger.warning(
                f"⚠️ auto_learned_artist_aliases.json nicht lesbar: {e}"
            )
        return exact, norm

    def _load_library(self) -> Dict[str, str]:
        # ARCH Artist-Identity Phase C: bevorzugt den normalisierten
        # Library-Index des Normalizers (refreshbar). Fallback auf den
        # rohen library_artists-Set fuer aeltere Normalizer-Instanzen/Tests.
        index = getattr(self._normalizer, "library_index", None)
        if isinstance(index, dict) and index:
            return {
                self._key(name): str(name).strip()
                for name in index.values()
                if str(name).strip()
            }
        result: Dict[str, str] = {}
        library_artists = getattr(self._normalizer, "library_artists", None) or set()
        for name in library_artists:
            n = str(name).strip()
            if n:
                result.setdefault(self._key(n), n)
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ─────────────────────────────────────────────────────────────────────────

    def resolve(
        self, name: str, ctx: Optional[Dict[str, Any]] = None
    ) -> ArtistIdentity:
        """Bestimmt die kanonische Artist-Identität für `name`.

        `ctx` darf enthalten: ``artist_mbid``, ``channel``, ``uploader``.
        Aktuell wird nur ``artist_mbid`` (Phase F, noch inaktiv) ausgewertet;
        ``channel``/``uploader`` sind reine Kontextinformationen.
        """
        ctx = ctx or {}
        raw = (name or "").strip()
        if not raw:
            return ArtistIdentity(canonical="", source="parser", known=False)

        canonical = self._string_normalize(raw)

        # Beide Formen (roh + normalisiert) gegen jede Stufe prüfen, Stufen
        # streng nach Priorität. Reihenfolge deterministisch, unabhängig von
        # Dict-/Dateireihenfolge.
        forms = [raw]
        if canonical and canonical != raw:
            forms.append(canonical)

        for form in forms:
            hit = self._resolve_override(form)
            if hit is not None:
                return ArtistIdentity(hit, "artist_override", True)

        for form in forms:
            hit = self._resolve_known(form)
            if hit is not None:
                return ArtistIdentity(hit, "known_artist", True)

        for form in forms:
            hit = self._resolve_alias(form)
            if hit is not None:
                # Alias-Ziel selbst noch gegen die höheren Stufen prüfen,
                # damit das Ergebnis kanonisch bleibt (Alias → known/library).
                return ArtistIdentity(hit, "auto_learned_alias", True)

        for form in forms:
            hit = self._resolve_library(form)
            if hit is not None:
                return ArtistIdentity(hit, "library_identity", True)

        mbid_hit = self._resolve_mbid(canonical or raw, ctx)
        if mbid_hit is not None:
            return ArtistIdentity(mbid_hit, "musicbrainz_mbid", True)

        return ArtistIdentity(
            canonical=canonical or raw, source="parser", known=False
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Stufen
    # ─────────────────────────────────────────────────────────────────────────

    def _string_normalize(self, raw: str) -> str:
        try:
            out = self._normalizer.normalize(raw)
        except Exception as e:
            self.logger.debug(f"normalize() fehlgeschlagen für {raw!r}: {e}")
            return raw
        if not out or str(out).strip().lower() == "unknown":
            return raw
        return str(out).strip()

    def _resolve_override(self, form: str) -> Optional[str]:
        if form in self._override_exact:
            return self._override_exact[form]
        k = self._key(form)
        if k in self._override_norm:
            return self._override_norm[k]
        if k in self._override_values_norm:
            return self._override_values_norm[k]
        return None

    def _resolve_known(self, form: str) -> Optional[str]:
        return self._known_norm.get(self._key(form))

    def _resolve_alias(self, form: str) -> Optional[str]:
        if form in self._alias_exact:
            return self._alias_exact[form]
        return self._alias_norm.get(self._key(form))

    def _resolve_library(self, form: str) -> Optional[str]:
        return self._library_norm.get(self._key(form))

    def _resolve_mbid(
        self, canonical: str, ctx: Dict[str, Any]
    ) -> Optional[str]:
        """Phase F – MusicBrainz-MBID-basierter Identitätsabgleich.

        Bewusst noch NICHT implementiert: Zum Zeitpunkt der Artist-Bestimmung
        (EMP Schritt 6) ist die MBID noch nicht ermittelt – MusicBrainz läuft
        erst in Schritt 8. Ob die MBID minimal-invasiv vorgezogen werden kann
        und fachlich belastbar genug für Identity Resolution ist, wird in
        Phase F (Schritt 9) geprüft. Bis dahin: kein MBID-Tier.
        """
        return None
