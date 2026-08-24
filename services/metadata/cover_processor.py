# services/metadata/cover_processor.py
# -*- coding: utf-8 -*-
"""
Moderner Multi-Source Cover Processor mit:
  - Score-basiertem Ranking (optimierte Gewichtung)
  - Nutzung aller verfügbaren MB-IDs
  - Paralleler Download mit Early Exit
  - Lokaler Cache mit Metadaten und Duplikaterkennung
  - Intelligenter Qualitätsbewertung
  - Apple Music 5000x5000 Support
  - Cover Art Archive Originale
  - Fanart.tv mit Priorisierung
  - AUSFÜHRLICHE DEBUG-LOGS
  - NEU: 6-Schritt Pipeline-Logging für vollständige Nachvollziehbarkeit
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from enum import IntEnum

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from logger import get_module_logger

try:
    from PIL import Image as PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Konstanten
# ─────────────────────────────────────────────────────────────────────────────

class ScoreThreshold(IntEnum):
    EXCELLENT = 115   # Score-Schwelle für "gutes Cover" (weiter suchen nach Besserem)
    GOOD = 100        # Score-Schwelle für Niedrigprio-Quellen überspringen
    # Score UND Mindestauflösung erforderlich für sofortigen Abbruch.
    # BUG-003-Fix: _calculate_score() deckelt den Score auf max. 150
    # (min(150, ...)) - der vorherige Wert 170 war strukturell unerreichbar,
    # die Early-Exit-Optimierung griff dadurch nie. 140 wird von den vier
    # zuverlässigsten Quellen (coverartarchive/fanart_album/apple_music/
    # deezer) bereits bei der ohnehin geforderten Mindestauflösung
    # (≥1400px, quadratisch) erreicht, von schwächeren Quellen
    # (fanart_artist/lastfm/youtube) nur bei deutlich höherer Auflösung.
    EARLY_EXIT = 140

# Mindestauflösung für den Early Exit (kürzere Seite muss ≥ diesen Wert haben)
_EARLY_EXIT_MIN_DIM = 1400

_BASE_SCORES = {
    "coverartarchive": 120,
    "fanart_album": 118,
    "apple_music": 105,
    "deezer": 100,
    "fanart_artist": 90,
    "lastfm": 80,
    "youtube_max": 55,
    "youtube_sd": 45,
    "youtube_hq": 35,
    "youtube_mq": 25,
}

_FANART_IMAGE_TYPES = ["albumcover", "hdmusiclogo", "cdart", "musicbanner", "artistthumb"]
_YT_VARIANTS = [
    ("maxresdefault", 1280, 720),
    ("sddefault", 640, 480),
    ("hqdefault", 480, 360),
    ("mqdefault", 320, 180),
]
_APPLE_RESOLUTIONS = ["5000x5000bb", "3000x3000bb", "1500x1500bb", "100x100bb"]

_FANART_BASE = "https://webservice.fanart.tv/v3/music"
_CAA_BASE = "https://coverartarchive.org/release"
_APPLE_SEARCH = "https://itunes.apple.com/search"
_DEEZER_SEARCH = "https://api.deezer.com/search"
_LASTFM_BASE = "http://ws.audioscrobbler.com/2.0/"

_MIN_IMAGE_BYTES = 5000
_MAX_WORKERS = 6
_TARGET_SIZE = 1200
_CACHE_DIR = os.path.join("cache", "covers")
_IMAGE_HASH_CACHE = {}

_SEPARATOR = "─" * 65


# ─────────────────────────────────────────────────────────────────────────────
# Datenklassen
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CoverCandidate:
    source: str
    data: bytes
    width: int = 0
    height: int = 0
    file_size_kb: int = 0
    resolution_score: int = 0
    size_score: int = 0
    quality_score: int = 0
    jpeg_quality: int = 0
    color_count: int = 0
    sharpness: float = 0.0
    is_square: bool = False
    total_score: int = 0
    image_hash: str = ""

    @property
    def resolution_label(self) -> str:
        if self.width and self.height:
            return f"{self.width}×{self.height}"
        return f"{self.file_size_kb} KB"

    @property
    def size_label(self) -> str:
        return f"{self.file_size_kb} KB"


# ─────────────────────────────────────────────────────────────────────────────
# Haupt-Klasse
# ─────────────────────────────────────────────────────────────────────────────

class CoverProcessor:
    def __init__(
        self,
        fanart_api_key: Optional[str] = None,
        lastfm_api_key: Optional[str] = None,
        logger=None,
        cache_enabled: bool = True,
    ):
        self.fanart_api_key = fanart_api_key
        self.lastfm_api_key = lastfm_api_key
        self.logger = logger or get_module_logger("CoverProcessor")
        self.cache_enabled = cache_enabled
        self.session = self._build_session()

        if self.cache_enabled:
            os.makedirs(_CACHE_DIR, exist_ok=True)

        self.logger.info("🖼️ [COVER] ✅ Multi-Source Cover Processor initialisiert (Pipeline-Logging aktiv)")

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ─────────────────────────────────────────────────────────────────────────

    def get_cover_art(
        self,
        video_id: Optional[str] = None,
        release_id: Optional[str] = None,
        release_group_mbid: Optional[str] = None,
        artist_mbid: Optional[str] = None,
        artist_name: Optional[str] = None,
        track_title: Optional[str] = None,
        recording_id: Optional[str] = None,
        isrc: Optional[str] = None,
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Hauptmethode: Sucht das beste Cover über alle verfügbaren Quellen.
        Gibt (cover_bytes, source_name) zurück, oder (None, None) bei Misserfolg.

        NEU: Strukturiertes 6-Schritt Pipeline-Logging:
          📥 Schritt 1: Eingabeparameter
          🔍 Schritt 2: Quellen-Suche (einzeln mit Erfolg/Fehler)
          📊 Schritt 3: Score-Berechnung je Quelle
          🏆 Schritt 4: Ranking aller Treffer
          🖼️ Schritt 5: Gewinner-Auswahl mit Begründung
          💾 Schritt 6: Einbettungsbestätigung
        """

        # ── Schritt 1: Eingabeparameter ────────────────────────────────────
        self._log_step_1_inputs(
            video_id=video_id,
            release_id=release_id,
            release_group_mbid=release_group_mbid,
            artist_mbid=artist_mbid,
            artist_name=artist_name,
            track_title=track_title,
            recording_id=recording_id,
            isrc=isrc,
        )

        # ── Task-Liste aufbauen ────────────────────────────────────────────
        tasks = self._build_priority_task_list(
            video_id, release_id, release_group_mbid, artist_mbid,
            artist_name, track_title
        )
        tasks.sort(key=lambda x: x[2], reverse=True)
        self.logger.debug(
            f"🖼️ [COVER] 📋 {len(tasks)} Tasks erstellt "
            f"(Prioritäten: {[t[2] for t in tasks]})"
        )

        # ── Schritt 2 & 3: Quellen-Suche mit Score-Logging ────────────────
        candidates: List[CoverCandidate] = []
        source_results: List[Dict[str, Any]] = []  # NEU: für Pipeline-Log
        best_score = 0

        self.logger.info(
            f"\n🖼️ [COVER] 🔍 SCHRITT 2: Quellen-Suche ({len(tasks)} Quellen)\n"
            f"{_SEPARATOR}"
        )

        for fn, label, priority in tasks:
            # Early Exit: Score ≥ 170 UND beide Seiten ≥ 1400 px
            # (verhindert, dass ein kleines 599×533 die Suche nach 3000×3000 abwürgt)
            if candidates:
                _best_so_far = max(candidates, key=lambda c: c.total_score)
                _early_ok = (
                    _best_so_far.total_score >= ScoreThreshold.EARLY_EXIT
                    and _best_so_far.width >= _EARLY_EXIT_MIN_DIM
                    and _best_so_far.height >= _EARLY_EXIT_MIN_DIM
                )
                if _early_ok:
                    self.logger.info(
                        f"🖼️ [COVER] ⏹️ Early Exit – Score {_best_so_far.total_score} "
                        f"bei {_best_so_far.width}×{_best_so_far.height} px "
                        f"(Schwelle: ≥{ScoreThreshold.EARLY_EXIT} Score & ≥{_EARLY_EXIT_MIN_DIM} px) "
                        f"– Überspringe verbleibende Quellen"
                    )
                    for _, remaining_label, _ in tasks[tasks.index((fn, label, priority)):]:
                        source_results.append({
                            "label": remaining_label,
                            "status": "skipped_early_exit",
                            "score": None,
                        })
                    break

            # Bei gutem Cover nur noch Quellen mit höherer Priorität als 50 prüfen
            if best_score >= ScoreThreshold.GOOD and priority < 50:
                self.logger.info(
                    f"🖼️ [COVER] ⏸️  [{label:<22}] ÜBERSPRUNGEN "
                    f"(gutes Cover vorhanden, Priorität {priority} < 50)"
                )
                source_results.append({
                    "label": label,
                    "status": "skipped_good_enough",
                    "score": None,
                })
                continue

            self.logger.info(f"🖼️ [COVER] 🔍 [{label:<22}] Suche läuft... (Priorität {priority})")

            try:
                candidate = fn()
                if candidate:
                    candidates.append(candidate)
                    if candidate.total_score > best_score:
                        best_score = candidate.total_score

                    # ── Schritt 3: Score-Berechnung dieser Quelle ─────────
                    self._log_step_3_score(label, candidate)

                    source_results.append({
                        "label": label,
                        "status": "success",
                        "score": candidate.total_score,
                        "resolution": candidate.resolution_label,
                        "size_kb": candidate.file_size_kb,
                    })
                else:
                    self.logger.info(f"🖼️ [COVER] ❌ [{label:<22}] Kein Bild gefunden")
                    source_results.append({
                        "label": label,
                        "status": "no_result",
                        "score": None,
                    })
            except Exception as exc:
                self.logger.info(f"🖼️ [COVER] ❌ [{label:<22}] Fehler: {exc}")
                source_results.append({
                    "label": label,
                    "status": "error",
                    "error": str(exc),
                    "score": None,
                })

        # ── Schritt 4: Ranking ─────────────────────────────────────────────
        self._log_step_4_ranking(candidates)

        if not candidates:
            self.logger.warning(
                f"\n🖼️ [COVER] ❌ SCHRITT 5: KEIN COVER GEFUNDEN\n"
                f"{_SEPARATOR}\n"
                f"   Getestete Quellen: {len(source_results)}\n"
                f"   Erfolgreiche: 0\n"
                f"   → Einbettung nicht möglich\n"
                f"{_SEPARATOR}"
            )
            return None, None

        # ── Schritt 5: Gewinner auswählen ──────────────────────────────────
        best = max(candidates, key=lambda c: c.total_score)
        self._log_step_5_winner(best, candidates)

        if self.cache_enabled and artist_name and track_title:
            self._cache_best_cover(artist_name, track_title, best)

        # ── Schritt 6: Einbettungsbestätigung ─────────────────────────────
        self._log_step_6_embed(best)

        return best.data, best.source

    # ─────────────────────────────────────────────────────────────────────────
    # NEU: Pipeline-Logging Methoden (Schritte 1–6)
    # ─────────────────────────────────────────────────────────────────────────

    def _log_step_1_inputs(
        self,
        video_id: Optional[str],
        release_id: Optional[str],
        release_group_mbid: Optional[str],
        artist_mbid: Optional[str],
        artist_name: Optional[str],
        track_title: Optional[str],
        recording_id: Optional[str],
        isrc: Optional[str],
    ) -> None:
        """📥 Schritt 1: Alle Eingabeparameter strukturiert ausgeben."""
        lines = [
            f"\n🖼️ [COVER] 📥 SCHRITT 1: Eingabeparameter",
            _SEPARATOR,
            f"   🎤 Artist         : {artist_name or '—'}",
            f"   🎵 Track-Titel    : {track_title or '—'}",
            "",
            f"   🆔 MusicBrainz IDs:",
            f"      recording_id   : {recording_id or '—'}",
            f"      release_id     : {release_id or '—'}",
            f"      release_group  : {release_group_mbid or '—'}",
            f"      artist_mbid    : {artist_mbid or '—'}",
            f"      isrc           : {isrc or '—'}",
            "",
            f"   🎬 YouTube video_id: {video_id or '—'}",
        ]

        # Verfügbarkeits-Zusammenfassung
        available_ids = sum([
            bool(recording_id), bool(release_id),
            bool(release_group_mbid), bool(artist_mbid), bool(isrc),
        ])
        lines.append(f"   📊 MB-IDs verfügbar: {available_ids}/5")

        if available_ids == 0:
            lines.append("   ⚠️  Keine MusicBrainz-IDs → nur YouTube/API-Suche möglich")
        elif available_ids >= 3:
            lines.append(
                f"   ✅ Gute ID-Abdeckung → hochwertige Quellen verfügbar "
                f"(Early Exit erst ab Score ≥{ScoreThreshold.EARLY_EXIT} & ≥{_EARLY_EXIT_MIN_DIM}px)"
            )

        lines.append(_SEPARATOR)
        self.logger.info("\n".join(lines))

    def _log_step_3_score(self, label: str, candidate: CoverCandidate) -> None:
        """📊 Schritt 3: Score-Berechnung für eine einzelne Quelle ausgeben."""
        base_score = _BASE_SCORES.get(candidate.source, 50)

        # Aufschlüsselung berechnen
        max_dim = max(candidate.width, candidate.height) if candidate.width and candidate.height else 0
        res_bonus = 0
        if max_dim >= 5000: res_bonus = 55
        elif max_dim >= 4000: res_bonus = 50
        elif max_dim >= 3000: res_bonus = 45
        elif max_dim >= 2000: res_bonus = 35
        elif max_dim >= 1400: res_bonus = 25
        elif max_dim >= 1000: res_bonus = 15
        elif max_dim >= 500: res_bonus = 5

        size_kb = candidate.file_size_kb
        size_bonus = 0
        if size_kb > 1000: size_bonus = 25
        elif size_kb > 500: size_bonus = 20
        elif size_kb > 250: size_bonus = 15
        elif size_kb > 100: size_bonus = 10
        elif size_kb > 50: size_bonus = 5

        quality_bonus = 0
        if candidate.jpeg_quality >= 95: quality_bonus = 15
        elif candidate.jpeg_quality >= 85: quality_bonus = 10
        elif candidate.jpeg_quality >= 75: quality_bonus = 5

        square_bonus = 15 if candidate.is_square else 0
        yt_penalty = -10 if "youtube" in candidate.source else 0

        lines = [
            f"🖼️ [COVER] 📊 SCHRITT 3: Score-Berechnung [{label}]",
            f"   Basis-Score      : {base_score:>4}  (Quelle: {candidate.source})",
            f"   Auflösung-Bonus  : {res_bonus:>+4}  ({candidate.resolution_label})",
            f"   Dateigröße-Bonus : {size_bonus:>+4}  ({size_kb} KB)",
            f"   Qualitäts-Bonus  : {quality_bonus:>+4}  (JPEG ~{candidate.jpeg_quality}%)",
            f"   Quadrat-Bonus    : {square_bonus:>+4}  ({'ja' if candidate.is_square else 'nein'})",
            f"   YT-Abzug         : {yt_penalty:>+4}",
            f"   {'─' * 36}",
            f"   Gesamt-Score     : {candidate.total_score:>4}",
        ]
        self.logger.debug("\n".join(lines))

    def _log_step_4_ranking(self, candidates: List[CoverCandidate]) -> None:
        """🏆 Schritt 4: Ranking aller gefundenen Cover ausgeben."""
        if not candidates:
            self.logger.info(
                f"\n🖼️ [COVER] 🏆 SCHRITT 4: Ranking\n"
                f"{_SEPARATOR}\n"
                f"   Keine Kandidaten gefunden\n"
                f"{_SEPARATOR}"
            )
            return

        sorted_candidates = sorted(candidates, key=lambda c: c.total_score, reverse=True)
        lines = [
            f"\n🖼️ [COVER] 🏆 SCHRITT 4: Ranking ({len(sorted_candidates)} Kandidaten)",
            _SEPARATOR,
            f"  {'#':<3} {'Quelle':<22} {'Auflösung':<14} {'Größe':<10} {'Score':>6}",
            f"  {'─'*3} {'─'*22} {'─'*14} {'─'*10} {'─'*6}",
        ]
        for i, c in enumerate(sorted_candidates, 1):
            winner_marker = "🏆" if i == 1 else "  "
            lines.append(
                f"  {winner_marker} {i:<2} {c.source:<22} {c.resolution_label:<14} "
                f"{c.size_label:<10} {c.total_score:>6}"
            )
        lines.append(_SEPARATOR)
        self.logger.info("\n".join(lines))

    def _log_step_5_winner(
        self, best: CoverCandidate, all_candidates: List[CoverCandidate]
    ) -> None:
        """🖼️ Schritt 5: Gewinner-Auswahl mit Begründung."""
        runner_up = sorted(all_candidates, key=lambda c: c.total_score, reverse=True)

        lines = [
            f"\n🖼️ [COVER] 🖼️  SCHRITT 5: Gewinner-Auswahl",
            _SEPARATOR,
            f"   🏆 Gewählt        : {best.source}",
            f"   📐 Auflösung      : {best.resolution_label}",
            f"   📦 Dateigröße     : {best.file_size_kb} KB ({len(best.data):,} bytes)",
            f"   🔢 Gesamt-Score   : {best.total_score}",
            f"   🟦 Quadratisch    : {'ja' if best.is_square else 'nein'}",
            f"   🖌️  JPEG-Qualität  : ~{best.jpeg_quality}%",
            f"   🎨 Farben         : {best.color_count}",
            f"   🔍 Schärfe        : {best.sharpness:.3f}",
        ]

        # Begründung
        early_exit_reached = (
            best.total_score >= ScoreThreshold.EARLY_EXIT
            and best.width >= _EARLY_EXIT_MIN_DIM
            and best.height >= _EARLY_EXIT_MIN_DIM
        )
        if early_exit_reached:
            lines.append(
                f"   ✅ Begründung     : Early-Exit-Qualität "
                f"(Score ≥ {ScoreThreshold.EARLY_EXIT} & {best.width}×{best.height} ≥ {_EARLY_EXIT_MIN_DIM}px)"
            )
        elif best.total_score >= ScoreThreshold.EXCELLENT:
            lines.append(
                f"   ✅ Begründung     : Exzellente Qualität (Score ≥ {ScoreThreshold.EXCELLENT}) "
                f"– alle Quellen durchsucht"
            )
        elif best.total_score >= ScoreThreshold.GOOD:
            lines.append(f"   ✅ Begründung     : Gute Qualität (Score ≥ {ScoreThreshold.GOOD})")
        else:
            lines.append(f"   ⚠️  Begründung     : Bestes verfügbares Cover (Score {best.total_score})")

        if len(runner_up) > 1:
            second = runner_up[1]
            diff = best.total_score - second.total_score
            lines.append(
                f"   📊 Vorsprung      : +{diff} vor '{second.source}' (Score {second.total_score})"
            )

        lines.append(_SEPARATOR)
        self.logger.info("\n".join(lines))

    def _log_step_6_embed(self, best: CoverCandidate) -> None:
        """💾 Schritt 6: Einbettungsbestätigung."""
        lines = [
            f"\n🖼️ [COVER] 💾 SCHRITT 6: Einbettung",
            _SEPARATOR,
            f"   Quelle           : {best.source}",
            f"   Datengröße       : {len(best.data):,} bytes ({best.file_size_kb} KB)",
            f"   Auflösung        : {best.resolution_label}",
            f"   Image-Hash (MD5) : {best.image_hash[:16]}...",
            f"   ✅ Cover-Art bereit zur Einbettung in Audio-Datei",
            _SEPARATOR,
        ]
        self.logger.info("\n".join(lines))

    # ─────────────────────────────────────────────────────────────────────────
    # Task-Liste mit Prioritäten
    # ─────────────────────────────────────────────────────────────────────────

    def _build_priority_task_list(self, video_id, release_id, release_group_mbid,
                                   artist_mbid, artist_name, track_title) -> list:
        tasks = []

        # 1. Cover Art Archive (benötigt release_id)
        if release_id:
            self.logger.debug(f"🖼️ [COVER] ✅ Aktiviere CAA (release_id={release_id})")
            tasks.append((lambda rid=release_id: self._fetch_coverartarchive(rid), "Cover Art Archive", 100))
        else:
            self.logger.debug("🖼️ [COVER] ⚠️ CAA übersprungen: keine release_id")

        # 2. Fanart.tv Album (benötigt release_group_mbid + API-Key)
        if self.fanart_api_key and release_group_mbid:
            self.logger.debug(f"🖼️ [COVER] ✅ Aktiviere Fanart.tv Album (release_group_mbid={release_group_mbid})")
            tasks.append((lambda rg=release_group_mbid: self._fetch_fanart_album(rg), "Fanart.tv Album", 99))
        else:
            reason = "kein API-Key" if not self.fanart_api_key else "keine release_group_mbid"
            self.logger.debug(f"🖼️ [COVER] ⚠️ Fanart.tv Album übersprungen: {reason}")

        # 3. Apple Music (benötigt artist_name + track_title)
        if artist_name and track_title:
            self.logger.debug(f"🖼️ [COVER] ✅ Aktiviere Apple Music (artist={artist_name}, title={track_title})")
            tasks.append((lambda a=artist_name, t=track_title: self._fetch_apple_music(a, t), "Apple Music", 90))
        else:
            self.logger.debug(f"🖼️ [COVER] ⚠️ Apple Music übersprungen: fehlende artist/title")

        # 4. Deezer (benötigt artist_name + track_title)
        if artist_name and track_title:
            self.logger.debug(f"🖼️ [COVER] ✅ Aktiviere Deezer")
            tasks.append((lambda a=artist_name, t=track_title: self._fetch_deezer(a, t), "Deezer", 85))
        else:
            self.logger.debug("🖼️ [COVER] ⚠️ Deezer übersprungen: fehlende artist/title")

        # 5. Fanart.tv Artist (benötigt artist_mbid + API-Key)
        if self.fanart_api_key and artist_mbid:
            self.logger.debug(f"🖼️ [COVER] ✅ Aktiviere Fanart.tv Artist (artist_mbid={artist_mbid})")
            tasks.append((lambda am=artist_mbid: self._fetch_fanart_artist(am), "Fanart.tv Artist", 80))
        else:
            reason = "kein API-Key" if not self.fanart_api_key else "keine artist_mbid"
            self.logger.debug(f"🖼️ [COVER] ⚠️ Fanart.tv Artist übersprungen: {reason}")

        # 6. Last.fm (benötigt artist_name + API-Key)
        if self.lastfm_api_key and artist_name:
            self.logger.debug(f"🖼️ [COVER] ✅ Aktiviere Last.fm (artist={artist_name})")
            tasks.append((lambda a=artist_name: self._fetch_lastfm(a), "Last.fm", 70))
        else:
            reason = "kein API-Key" if not self.lastfm_api_key else "keine artist_name"
            self.logger.debug(f"🖼️ [COVER] ⚠️ Last.fm übersprungen: {reason}")

        # 7. YouTube (niedrigste Priorität, aber immer verfügbar, wenn video_id existiert)
        if video_id:
            self.logger.debug(f"🖼️ [COVER] ✅ Aktiviere YouTube Fallback (video_id={video_id})")
            for variant, w, h in _YT_VARIANTS:
                tasks.append((lambda vid=video_id, var=variant: self._fetch_youtube(vid, var), f"YouTube {variant}", 30))
        else:
            self.logger.debug("🖼️ [COVER] ⚠️ YouTube übersprungen: keine video_id")

        return tasks

    # ─────────────────────────────────────────────────────────────────────────
    # Scoring System
    # ─────────────────────────────────────────────────────────────────────────

    def _calculate_score(self, source: str, width: int, height: int, file_size: int,
                         jpeg_quality: int = 0, color_count: int = 0,
                         sharpness: float = 0.0, is_square: bool = True) -> int:
        score = _BASE_SCORES.get(source, 50)
        max_dim = max(width, height)
        if max_dim >= 5000: score += 55
        elif max_dim >= 4000: score += 50
        elif max_dim >= 3000: score += 45
        elif max_dim >= 2000: score += 35
        elif max_dim >= 1400: score += 25
        elif max_dim >= 1000: score += 15
        elif max_dim >= 500: score += 5

        size_kb = file_size / 1024
        if size_kb > 1000: score += 25
        elif size_kb > 500: score += 20
        elif size_kb > 250: score += 15
        elif size_kb > 100: score += 10
        elif size_kb > 50: score += 5

        if jpeg_quality >= 95: score += 15
        elif jpeg_quality >= 85: score += 10
        elif jpeg_quality >= 75: score += 5

        if color_count > 100000: score += 10
        elif color_count > 50000: score += 5
        if sharpness > 0.5: score += 5
        if is_square: score += 15
        if "youtube" in source: score -= 10

        return min(150, max(0, score))

    def _analyze_image_quality(self, data: bytes):
        width, height, sharpness, jpeg_quality, color_count = 0, 0, 0.0, 0, 0
        if _PIL_AVAILABLE:
            try:
                img = PILImage.open(io.BytesIO(data))
                width, height = img.size
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                colors = img.getcolors(maxcolors=256)
                color_count = len(colors) if colors else 256
                import numpy as np
                img_array = np.array(img)
                gray = np.dot(img_array[..., :3], [0.2989, 0.5870, 0.1140])
                laplacian = np.abs(np.gradient(np.gradient(gray)))
                sharpness = float(np.mean(laplacian))
                pixels = width * height
                if pixels > 0:
                    bytes_per_pixel = len(data) / pixels
                    if bytes_per_pixel > 0.5: jpeg_quality = 95
                    elif bytes_per_pixel > 0.3: jpeg_quality = 85
                    elif bytes_per_pixel > 0.15: jpeg_quality = 75
                    else: jpeg_quality = 60
            except Exception as e:
                self.logger.debug(f"🖼️ [QUALITY] Analyse fehlgeschlagen: {e}")
        return width, height, sharpness, jpeg_quality, color_count

    def _validate_and_score(self, source: str, data: bytes) -> Optional[CoverCandidate]:
        if len(data) < _MIN_IMAGE_BYTES:
            self.logger.debug(f"🖼️ [SCORE] {source} zu klein ({len(data)} bytes) – ignoriert")
            return None
        w, h, sharp, jpeg, colors = self._analyze_image_quality(data)
        # _analyze_image_quality() faengt Parse-Fehler ab und liefert dann
        # w=h=0 zurueck. Die alte Bedingung "w > 0 and (...)" ignorierte
        # diesen Fall komplett, statt ihn abzulehnen - ein Nicht-Bild-Blob
        # >= _MIN_IMAGE_BYTES (z.B. eine mit HTTP 200 zurueckgegebene
        # HTML-Fehlerseite) rutschte so durch und konnte als Cover-Art in
        # die Audiodatei eingebettet werden.
        if w <= 0 or h <= 0:
            self.logger.debug(
                f"🖼️ [SCORE] {source} kein gültiges Bild (Analyse fehlgeschlagen) – ignoriert"
            )
            return None
        if w < 100 or h < 100:
            self.logger.debug(f"🖼️ [SCORE] {source} zu kleine Auflösung ({w}×{h}) – ignoriert")
            return None
        is_square = w > 0 and h > 0 and abs(w - h) < (max(w, h) * 0.1)
        file_size_kb = len(data) // 1024
        image_hash = hashlib.md5(data).hexdigest()
        total_score = self._calculate_score(source, w, h, len(data), jpeg, colors, sharp, is_square)
        self.logger.debug(f"🖼️ [SCORE] {source}: {w}×{h}, {file_size_kb}KB, Score {total_score}")
        return CoverCandidate(
            source=source, data=data, width=w, height=h, file_size_kb=file_size_kb,
            total_score=total_score, is_square=is_square, jpeg_quality=jpeg,
            color_count=colors, sharpness=sharp, image_hash=image_hash,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Quellen-Implementierungen (mit Debug-Logs)
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_coverartarchive(self, release_id: str) -> Optional[CoverCandidate]:
        self.logger.debug(f"🖼️ [CAA] Anfrage für release_id={release_id}")
        cache_key = f"caa_{release_id}"
        cached = self._cache_get(cache_key)
        if cached:
            self.logger.debug(f"🖼️ [CAA] Cache-Treffer, Größe={len(cached)} bytes")
            return self._validate_and_score("coverartarchive", cached)

        url = f"{_CAA_BASE}/{release_id}/front"
        try:
            resp = self._get(url)
            if resp and resp.status_code == 200 and resp.content:
                self.logger.debug(f"🖼️ [CAA] Erfolg: {len(resp.content)} bytes")
                self._cache_set(cache_key, resp.content)
                return self._validate_and_score("coverartarchive", resp.content)
            else:
                status = resp.status_code if resp else "None"
                self.logger.debug(f"🖼️ [CAA] Fehlgeschlagen, HTTP {status}")
        except Exception as e:
            self.logger.debug(f"🖼️ [CAA] Exception: {e}")
        return None

    def _fetch_fanart_album(self, release_group_mbid: str) -> Optional[CoverCandidate]:
        self.logger.debug(f"🖼️ [FANART] Album-Anfrage: release_group_mbid={release_group_mbid}")
        if not self.fanart_api_key:
            self.logger.debug("🖼️ [FANART] Kein API-Key – überspringe")
            return None
        cache_key = f"fanart_album_{release_group_mbid}"
        cached = self._cache_get(cache_key)
        if cached:
            self.logger.debug(f"🖼️ [FANART] Cache-Treffer, Größe={len(cached)} bytes")
            return self._validate_and_score("fanart_album", cached)

        url = f"{_FANART_BASE}/albums/{release_group_mbid}"
        try:
            resp = self._get(url, params={"api_key": self.fanart_api_key})
            if not resp or resp.status_code != 200:
                self.logger.debug(f"🖼️ [FANART] Kein Album-Cover (HTTP {resp.status_code if resp else 'None'})")
                return None
            data = resp.json()
            for img_type in _FANART_IMAGE_TYPES:
                images = data.get(img_type, [])
                if images:
                    best_img = max(images, key=lambda x: x.get("url", "").count("fans") if "url" in x else 0)
                    img_url = best_img.get("url")
                    if img_url:
                        self.logger.debug(f"🖼️ [FANART] Bild gefunden: {img_type} → {img_url}")
                        img_data = self._fetch_raw(img_url)
                        if img_data:
                            self._cache_set(cache_key, img_data)
                            return self._validate_and_score("fanart_album", img_data)
            self.logger.debug(f"🖼️ [FANART] Keine passenden Bildtypen in Antwort")
        except Exception as e:
            self.logger.debug(f"🖼️ [FANART] Exception: {e}")
        return None

    def _fetch_fanart_artist(self, artist_mbid: str) -> Optional[CoverCandidate]:
        self.logger.debug(f"🖼️ [FANART] Artist-Anfrage: artist_mbid={artist_mbid}")
        if not self.fanart_api_key:
            return None
        cache_key = f"fanart_artist_{artist_mbid}"
        cached = self._cache_get(cache_key)
        if cached:
            return self._validate_and_score("fanart_artist", cached)
        url = f"{_FANART_BASE}/{artist_mbid}"
        try:
            resp = self._get(url, params={"api_key": self.fanart_api_key})
            if not resp or resp.status_code != 200:
                self.logger.debug(f"🖼️ [FANART] Kein Artist-Bild (HTTP {resp.status_code if resp else 'None'})")
                return None
            data = resp.json()
            for img_type in ("artistthumb", "artistbackground", "hdmusiclogo"):
                images = data.get(img_type, [])
                if images:
                    img_url = images[0].get("url")
                    if img_url:
                        img_data = self._fetch_raw(img_url)
                        if img_data:
                            self._cache_set(cache_key, img_data)
                            return self._validate_and_score("fanart_artist", img_data)
        except Exception as e:
            self.logger.debug(f"🖼️ [FANART] Artist Exception: {e}")
        return None

    def _fetch_apple_music(self, artist: str, title: str) -> Optional[CoverCandidate]:
        self.logger.debug(f"🖼️ [APPLE] Suche: {artist} - {title}")
        cache_key = f"apple_{hashlib.md5(f'{artist}|{title}'.encode()).hexdigest()}"
        cached = self._cache_get(cache_key)
        if cached:
            return self._validate_and_score("apple_music", cached)
        try:
            resp = self._get(_APPLE_SEARCH, params={"term": f"{artist} {title}", "media": "music", "limit": 1})
            if not resp or resp.status_code != 200:
                self.logger.debug(f"🖼️ [APPLE] Keine Ergebnisse, HTTP {resp.status_code if resp else 'None'}")
                return None
            results = resp.json().get("results", [])
            if not results:
                self.logger.debug("🖼️ [APPLE] Keine Ergebnisse in JSON")
                return None
            artwork_url = results[0].get("artworkUrl100", "")
            if not artwork_url:
                self.logger.debug("🖼️ [APPLE] Keine artworkUrl100")
                return None
            for resolution in _APPLE_RESOLUTIONS:
                test_url = artwork_url.replace("100x100bb", resolution)
                img_data = self._fetch_raw(test_url)
                if img_data and len(img_data) > _MIN_IMAGE_BYTES:
                    self.logger.debug(f"🖼️ [APPLE] Erfolg: Auflösung {resolution}, {len(img_data)} bytes")
                    self._cache_set(cache_key, img_data)
                    return self._validate_and_score("apple_music", img_data)
            self.logger.debug("🖼️ [APPLE] Keine ausreichend große Auflösung gefunden")
        except Exception as e:
            self.logger.debug(f"🖼️ [APPLE] Exception: {e}")
        return None

    def _fetch_deezer(self, artist: str, title: str) -> Optional[CoverCandidate]:
        self.logger.debug(f"🖼️ [DEEZER] Suche: {artist} - {title}")
        cache_key = f"deezer_{hashlib.md5(f'{artist}|{title}'.encode()).hexdigest()}"
        cached = self._cache_get(cache_key)
        if cached:
            return self._validate_and_score("deezer", cached)
        try:
            resp = self._get(_DEEZER_SEARCH, params={"q": f'artist:"{artist}" track:"{title}"', "limit": 1})
            if not resp or resp.status_code != 200:
                self.logger.debug(f"🖼️ [DEEZER] Keine Ergebnisse, HTTP {resp.status_code if resp else 'None'}")
                return None
            items = resp.json().get("data", [])
            if not items:
                self.logger.debug("🖼️ [DEEZER] Keine Daten")
                return None
            album = items[0].get("album", {})
            cover_url = album.get("cover_xl") or album.get("cover_big") or album.get("cover")
            if not cover_url:
                self.logger.debug("🖼️ [DEEZER] Keine Cover-URL")
                return None
            img_data = self._fetch_raw(cover_url)
            if img_data:
                self.logger.debug(f"🖼️ [DEEZER] Erfolg: {len(img_data)} bytes")
                self._cache_set(cache_key, img_data)
                return self._validate_and_score("deezer", img_data)
        except Exception as e:
            self.logger.debug(f"🖼️ [DEEZER] Exception: {e}")
        return None

    def _fetch_lastfm(self, artist: str) -> Optional[CoverCandidate]:
        self.logger.debug(f"🖼️ [LASTFM] Suche: {artist}")
        if not self.lastfm_api_key:
            return None
        cache_key = f"lastfm_{hashlib.md5(artist.encode()).hexdigest()}"
        cached = self._cache_get(cache_key)
        if cached:
            return self._validate_and_score("lastfm", cached)
        try:
            params = {
                "method": "artist.getinfo",
                "artist": artist,
                "api_key": self.lastfm_api_key,
                "format": "json"
            }
            resp = self._get(_LASTFM_BASE, params=params)
            if not resp or resp.status_code != 200:
                self.logger.debug(f"🖼️ [LASTFM] Keine Antwort, HTTP {resp.status_code if resp else 'None'}")
                return None
            data = resp.json()
            images = data.get("artist", {}).get("image", [])
            if images:
                img_url = images[-1].get("#text")
                if img_url:
                    img_data = self._fetch_raw(img_url)
                    if img_data:
                        self.logger.debug(f"🖼️ [LASTFM] Erfolg: {len(img_data)} bytes")
                        self._cache_set(cache_key, img_data)
                        return self._validate_and_score("lastfm", img_data)
            self.logger.debug("🖼️ [LASTFM] Kein Bild gefunden")
        except Exception as e:
            self.logger.debug(f"🖼️ [LASTFM] Exception: {e}")
        return None

    def _fetch_youtube(self, video_id: str, variant: str) -> Optional[CoverCandidate]:
        self.logger.debug(f"🖼️ [YT] Versuche {variant} für {video_id}")
        cache_key = f"yt_{video_id}_{variant}"
        cached = self._cache_get(cache_key)
        if cached:
            return self._validate_and_score(f"youtube_{variant[:3]}", cached)

        url = f"https://img.youtube.com/vi/{video_id}/{variant}.jpg"
        try:
            resp = self._get(url)
            if resp and resp.status_code == 200 and resp.content:
                size = len(resp.content)
                if variant == "maxresdefault" and size < 10000:
                    self.logger.debug(f"🖼️ [YT] {variant} zu klein ({size} bytes) – Placeholder")
                    return None
                if size < 5000:
                    self.logger.debug(f"🖼️ [YT] {variant} zu klein ({size} bytes)")
                    return None
                self.logger.debug(f"🖼️ [YT] {variant} erfolgreich: {size} bytes")
                self._cache_set(cache_key, resp.content)
                source = f"youtube_{variant[:3] if variant != 'maxresdefault' else 'max'}"
                return self._validate_and_score(source, resp.content)
        except Exception as e:
            self.logger.debug(f"🖼️ [YT] {variant} Exception: {e}")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Cache, HTTP, Logging (Hilfsmethoden)
    # ─────────────────────────────────────────────────────────────────────────

    def _cache_path(self, key: str, ext: str = "jpg") -> str:
        safe_key = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(_CACHE_DIR, f"{safe_key}.{ext}")

    def _meta_path(self, key: str) -> str:
        safe_key = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(_CACHE_DIR, f"{safe_key}.json")

    def _cache_get(self, key: str) -> Optional[bytes]:
        if not self.cache_enabled:
            return None
        path = self._cache_path(key)
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    return f.read()
            except Exception:
                pass
        return None

    def _cache_set(self, key: str, data: bytes) -> None:
        if not self.cache_enabled:
            return
        path = self._cache_path(key)
        try:
            with open(path, "wb") as f:
                f.write(data)
        except Exception as e:
            self.logger.debug(f"🖼️ [CACHE] Schreiben fehlgeschlagen: {e}")

    def _cache_best_cover(self, artist: str, title: str, best: CoverCandidate) -> None:
        cache_key = f"best_{hashlib.md5(f'{artist}|{title}'.encode()).hexdigest()}"
        meta = {
            "source": best.source, "resolution": f"{best.width}×{best.height}",
            "bytes": len(best.data), "size_kb": best.file_size_kb, "score": best.total_score,
            "artist": artist, "title": title, "image_hash": best.image_hash,
            "jpeg_quality": best.jpeg_quality, "color_count": best.color_count,
            "sharpness": best.sharpness, "timestamp": datetime.now().isoformat(),
        }
        meta_path = self._meta_path(cache_key)
        try:
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            self.logger.debug(f"🖼️ [CACHE] Metadaten speichern fehlgeschlagen: {e}")

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({"User-Agent": "MusicLibraryBot/2.0"})
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _get(self, url: str, params: Optional[dict] = None) -> Optional[requests.Response]:
        try:
            return self.session.get(url, params=params, timeout=8, allow_redirects=True)
        except requests.RequestException as e:
            self.logger.debug(f"🖼️ [HTTP] ❌ {url[:50]}: {e}")
            return None

    def _fetch_raw(self, url: str) -> Optional[bytes]:
        resp = self._get(url)
        if resp and resp.status_code == 200 and resp.content:
            return resp.content
        return None

    # NEU: _log_available_ids und _log_ranking bleiben als Hilfsmethoden erhalten
    # (werden intern von den neuen Schritt-Methoden aufgerufen oder für Rückwärtskompatibilität)

    def _log_available_ids(self, release_id, release_group_mbid, artist_mbid, recording_id, isrc):
        """Legacy-Hilfsmethode – Funktionalität jetzt in _log_step_1_inputs."""
        ids = []
        if release_id:
            ids.append(f"release={release_id[:8]}...")
        if release_group_mbid:
            ids.append(f"release_group={release_group_mbid[:8]}...")
        if artist_mbid:
            ids.append(f"artist={artist_mbid[:8]}...")
        if recording_id:
            ids.append(f"recording={recording_id[:8]}...")
        if isrc:
            ids.append(f"isrc={isrc}")
        if ids:
            self.logger.debug(f"🖼️ [COVER] Verfügbare IDs: {', '.join(ids)}")

    def _log_ranking(self, candidates: List[CoverCandidate]):
        """Legacy-Hilfsmethode – Funktionalität jetzt in _log_step_4_ranking."""
        self._log_step_4_ranking(candidates)
