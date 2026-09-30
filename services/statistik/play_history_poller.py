# services/statistik/play_history_poller.py
# -*- coding: utf-8 -*-
"""
PlayHistoryPoller – Polling gegen Navidrome, das die serverseitige
playCount-Zählung als einzige Quelle der Wahrheit nutzt.

Architektur (2026-09-30, saubere Neuimplementierung):
  - Navidrome zählt Plays serverseitig selbst (playCount pro Song+User),
    egal welcher Subsonic-Client (Symfonium, DSub, etc.) scrobbelt.
  - Der Poller fragt zyklisch getNowPlaying ab, um aktuell laufende
    Songs zu identifizieren, und liest für jeden getrackten Song
    getSong(id).playCount.
  - Eine State-Datei pro User hält den zuletzt gesehenen playCount
    jedes Songs. Steigt der Wert, wird die Differenz als neue History-
    Einträge angelegt.
  - Kein Raten, kein Heuristik-Fenster: Navidromes Zähler ist die
    einzige Wahrheit. Repeat, Ersthörung, mehrfacher Songstart –
    alles wird zuverlässig erfasst.

Warum nicht mehr über getNowPlaying-Snapshots?
  Navidrome entfernt einen Song aus getNowPlaying, sobald seine Dauer
  abgelaufen ist und der Player nicht neu pingt. Clients wie Symfonium
  pingen bei Repeat NICHT erneut, wodurch der Song aus der Liste fällt
  und die alte Poller-Logik Repeats verpasste. Der playCount bleibt
  davon unberührt und ist damit die einzige verlässliche Quelle.
"""

import asyncio
import hashlib
import json
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import get_config
from logger import get_module_logger

from services.statistik.play_history_repository import PlayHistoryRepository


def _extract_genre_names(song_info: Dict[str, Any]) -> List[str]:
    """Extrahiert Genre-Namen aus dem strukturierten Subsonic-`genres`-
    Feld (bevorzugte NAV-F8-Quelle: `[{"name": "Hip Hop"}, ...]`).
    Dedupliziert, behält Reihenfolge, ignoriert fehlerhafte Einträge
    defensiv."""
    raw = song_info.get("genres") or []
    if not isinstance(raw, list):
        return []
    names = [
        g.get("name")
        for g in raw
        if isinstance(g, dict) and isinstance(g.get("name"), str) and g.get("name").strip()
    ]
    return list(dict.fromkeys(names))


class _NavidromeSubsonicClient:
    """Minimaler, direkter Subsonic-Client für getSong()-Abfragen.
    Bewusst unabhängig vom bestehenden NavidromeAPI-Client, damit wir
    unabhängig von dessen vorhandenem Methodensatz arbeiten können."""

    def __init__(self, url: str, user: str, password: str, logger):
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self.logger = logger

    def _call(self, method: str, **extra) -> Optional[Dict[str, Any]]:
        salt = secrets.token_hex(6)
        token = hashlib.md5((self.password + salt).encode()).hexdigest()
        params = {
            "u": self.user, "t": token, "s": salt,
            "v": "1.16.1", "c": "MusicBot", "f": "json",
            **extra,
        }
        try:
            url = f"{self.url}/rest/{method}?" + urllib.parse.urlencode(params)
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("subsonic-response", {})
        except Exception as e:
            self.logger.warning(f"Subsonic-Call {method} fehlgeschlagen: {e}")
            return None

    def get_song(self, song_id: str) -> Optional[Dict[str, Any]]:
        resp = self._call("getSong", id=song_id)
        if not resp or resp.get("status") != "ok":
            return None
        return resp.get("song")


class PlayHistoryPoller:
    """Pollt Navidrome über die Subsonic-API und schreibt neue Plays
    basierend auf Navidromes playCount-Zähler in den Verlauf."""

    # TTL für Songs im Tracker: Nach dieser Zeit ohne Sichtung in
    # getNowPlaying wird der Song noch einmal geprüft und dann entfernt.
    TRACKER_TTL_MINUTES = 30

    def __init__(self, navidrome_api, repository: PlayHistoryRepository, logger=None):
        self.api = navidrome_api
        self.repository = repository
        self.logger = logger or get_module_logger("PlayHistoryPoller")
        self._polling_task: Optional[asyncio.Task] = None

        # Direkter Subsonic-Client aus Config
        self._subsonic = _NavidromeSubsonicClient(
            url=str(get_config().NAVIDROME_URL),
            user=str(get_config().NAVIDROME_USER),
            password=str(get_config().NAVIDROME_PASS),
            logger=self.logger,
        )

        # State-Verzeichnis für Tracker. PLAY_HISTORY_FILE ist eine
        # JSON-Datei (kein Verzeichnis) – wir legen unser State-Verzeichnis
        # als Unterordner daneben an.
        _history_path = Path(get_config().PLAY_HISTORY_FILE)
        self._state_dir = _history_path.parent / "play_count_states"
        self._state_dir.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────

    def start_polling(self):
        if self._polling_task and not self._polling_task.done():
            self.logger.warning("Polling-Task läuft bereits.")
            return
        self.logger.info("Starte Hintergrund-Task für History-Updates...")
        self._polling_task = asyncio.create_task(self._run_history_updater())
        self._polling_task.add_done_callback(self._on_polling_task_done)

    def _on_polling_task_done(self, task: "asyncio.Task") -> None:
        """Ein unerwartet beendeter Hintergrund-Task darf nicht still
        sterben: ohne diesen Callback bleibt die Exception unbemerkt, solange
        self._polling_task die Referenz hält, und die History wird nie mehr
        aktualisiert."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self.logger.error(
                f"❌ History-Polling-Task unerwartet beendet: {exc!r}",
                exc_info=exc,
            )

    async def stop_polling(self):
        if self._polling_task and not self._polling_task.done():
            self.logger.info("Stoppe Hintergrund-Task...")
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                self.logger.info("Hintergrund-Task erfolgreich gestoppt.")
        self._polling_task = None

    async def update_play_history(self) -> bool:
        """
        Ein Poll-Zyklus:
          1. getNowPlaying → aktuell laufende Songs.
          2. Alle bekannten Tracker-Songs (die letzten 30 Min gesehen)
             + aktuell laufende Songs: getSong → playCount.
          3. Delta zum letzten bekannten playCount → neue Einträge.
          4. Tracker-State speichern.
        """
        try:
            self.logger.debug("🔄 Starte playCount-basiertes Update...")

            now_playing = await self.api.get_now_playing()

            # 1. Aktuell laufende Songs pro User
            current_songs_by_user: Dict[str, List[Dict[str, Any]]] = {}
            for play_data in now_playing or []:
                song_info = play_data.get("song")
                username = play_data.get("user")
                if not song_info or not username or username == "Unbekannter Nutzer":
                    continue
                current_songs_by_user.setdefault(username, []).append({
                    "song_id": song_info.get("id"),
                    "player": play_data.get("player", "N/A"),
                    "song_info": song_info,
                })

            # Wenn aktuell nichts läuft: trotzdem alle bekannten Tracker
            # abarbeiten (z. B. Repeat, das zwischen zwei Polls endete).
            new_entries_added = False

            # 2. Alle User aus dem State prüfen
            state_files = list(self._state_dir.glob("play_count_state_*.json"))
            users = {
                f.stem.replace("play_count_state_", "")
                for f in state_files
            } | set(current_songs_by_user.keys())

            for username in users:
                if await self._process_user(username, current_songs_by_user.get(username, [])):
                    new_entries_added = True

            return new_entries_added

        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Aktualisieren des Wiedergabeverlaufs: {e}",
                exc_info=True,
            )
            return False

    # ─────────────────────────────────────────────────────────────────
    # Interne Verarbeitung
    # ─────────────────────────────────────────────────────────────────

    def _state_path(self, username: str) -> Path:
        safe = self.repository.sanitize_username(username)
        return self._state_dir / f"play_count_state_{safe}.json"

    def _load_state(self, username: str) -> Dict[str, Any]:
        path = self._state_path(username)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            self.logger.warning(f"State für '{username}' unlesbar: {e}")
            return {}

    def _save_state(self, username: str, state: Dict[str, Any]) -> None:
        path = self._state_path(username)
        tmp = path.with_name(f".{path.name}.tmp")
        try:
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError as e:
            self.logger.error(f"State für '{username}' nicht speicherbar: {e}")

    async def _process_user(
        self,
        username: str,
        current_songs: List[Dict[str, Any]],
    ) -> bool:
        """
        Verarbeitet einen User:
          - Aktualisiert Tracker-State für aktuell laufende Songs.
          - Prüft playCount für alle Tracker-Einträge (aktiv + kürzlich gesehen).
          - Legt History-Einträge für erhöhte playCounts an.
        """
        state = self._load_state(username)
        tracker: Dict[str, Any] = state.get("tracker", {})

        # Alle Song-IDs, die wir jetzt prüfen müssen
        song_ids_to_check: Dict[str, Dict[str, Any]] = {}

        # 1. Aktuell laufende Songs
        current_ids = set()
        for entry in current_songs:
            song_id = entry.get("song_id")
            if not song_id:
                continue
            current_ids.add(song_id)
            song_ids_to_check[song_id] = entry

        # 2. Bereits bekannte Tracker-Songs (noch nicht TTL-abgelaufen)
        now = datetime.now()
        ttl = timedelta(minutes=self.TRACKER_TTL_MINUTES)
        expired_ids = []
        for song_id, info in tracker.items():
            last_seen = info.get("last_seen")
            if not last_seen:
                expired_ids.append(song_id)
                continue
            try:
                seen_at = datetime.fromisoformat(last_seen)
            except (ValueError, TypeError):
                expired_ids.append(song_id)
                continue
            if now - seen_at > ttl:
                expired_ids.append(song_id)
                continue
            if song_id not in song_ids_to_check:
                song_ids_to_check[song_id] = {"song_id": song_id, "song_info": info.get("track")}

        # 3. playCount für alle prüfen und Deltas anwenden
        new_entries_added = False
        for song_id, entry in song_ids_to_check.items():
            playcount_data = self._subsonic.get_song(song_id)
            if not playcount_data:
                continue
            current_playcount = playcount_data.get("playCount")
            if current_playcount is None:
                # Navidrome zählt für diesen Song/User nicht
                continue

            prev = tracker.get(song_id, {})
            last_known = prev.get("last_playcount", 0)

            # Erste Sichtung: kein Delta anlegen, nur State initialisieren
            if song_id not in tracker:
                tracker[song_id] = {
                    "last_playcount": current_playcount,
                    "last_seen": now.isoformat(),
                    "track": self._build_track_dict(playcount_data, entry),
                }
                continue

            delta = current_playcount - last_known
            if delta > 0:
                # delta neue Einträge anlegen
                track = self._build_track_dict(playcount_data, entry)
                for _ in range(delta):
                    self._append_history_entry(username, track)
                new_entries_added = True
                self.logger.info(
                    f"✅ {delta} neue(r) Play(s) für '{track.get('title')}' "
                    f"(playCount {last_known} -> {current_playcount}) bei '{username}'."
                )

            tracker[song_id] = {
                "last_playcount": current_playcount,
                "last_seen": now.isoformat(),
                "track": self._build_track_dict(playcount_data, entry),
            }

        # 4. TTL-abgelaufene Einträge entfernen
        for song_id in expired_ids:
            tracker.pop(song_id, None)

        # 5. State speichern
        self._save_state(username, {"tracker": tracker})

        return new_entries_added

    def _build_track_dict(
        self,
        playcount_data: Dict[str, Any],
        entry: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Baut das Track-Dict für den History-Eintrag aus getSong-Antwort
        + ggf. getNowPlaying-Zusatzinfos (player)."""
        song_info = entry.get("song_info") or {}
        # Bevorzugt getSong-Felder (immer aktuell), fallback auf getNowPlaying
        return {
            "title": playcount_data.get("title") or song_info.get("title") or "N/A",
            "artist": playcount_data.get("artist") or song_info.get("artist") or "N/A",
            "album": playcount_data.get("album") or song_info.get("album") or "N/A",
            "genre": playcount_data.get("genre") or song_info.get("genre") or "",
            "genres": _extract_genre_names(playcount_data) or _extract_genre_names(song_info),
            "id": playcount_data.get("id") or song_info.get("id") or "N/A",
            "duration": playcount_data.get("duration") or song_info.get("duration"),
            "player": entry.get("player") or "N/A",
        }

    def _append_history_entry(self, username: str, track: Dict[str, Any]) -> None:
        """Hängt einen neuen History-Eintrag an und speichert."""
        history = self.repository.load(username)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "tracks": [{**track, "username": username}],
        }
        history.append(entry)
        self.repository.save(history, username)
        self.repository.cleanup_old_entries(username)

    async def _run_history_updater(self):

        interval_seconds = get_config().PLAY_HISTORY_AUTOSAVE_INTERVAL_MIN * 60
        if interval_seconds < 60:
            self.logger.warning(
                f"Polling-Intervall ({interval_seconds}s) zu kurz – setze auf 60s."
            )
            interval_seconds = 60

        self.logger.info(
            f"🔄 History Updater gestartet (playCount-Diff). Intervall: {interval_seconds}s."
        )

        await asyncio.sleep(10)

        while True:
            try:
                await self.update_play_history()
            except Exception as e:
                self.logger.error(f"❌ Fehler im History Updater: {e}", exc_info=True)
            await asyncio.sleep(interval_seconds)
