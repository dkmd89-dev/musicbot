# services/web_auth.py
# -*- coding: utf-8 -*-
"""
Control-Center-Login mit Navidrome-Benutzer (Web-Paritäts-Backlog 9,
Nutzerentscheidung 3, 2026-09-28) - Fachlogik ohne FastAPI-/Telegram-
Bezug, genutzt von control_center/routers/auth.py.

Entscheidungen (Nutzer):
- Freischaltung nur durch einen Admin: ein Navidrome-Konto darf sich nur
  anmelden, wenn es in data/user_data.json genau EINEM Benutzer zugeordnet
  ist - entweder einem Telegram-Benutzer (positive ID, dieselbe Identität
  wie beim Telegram-Login) oder einem Web-Benutzer ohne Telegram (negative
  ID, services/user_admin.py::create_web_user()).
- Höchste Rolle über Navidrome-Login: ADMIN (OWNER nur über Telegram) -
  cap_access_level().
- Prüfung der Zugangsdaten über Navidromes POST /auth/login
  (services/clients/navidrome_api.py::verify_navidrome_credentials()).

Security (CLAUDE.md §12): Das Passwort wird hier nur an den Verifier
durchgereicht, nie gespeichert oder geloggt. Einheitliches Ergebnis
"invalid" für falsches Passwort UND nicht freigeschaltetes Konto (keine
Rückschlüsse auf existierende Konten); die Navidrome-Prüfung läuft immer
zuerst. Rate-Limit pro Benutzername und pro IP gegen Durchprobieren.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Iterable, Optional

from services.access_control import AccessLevel
from services.clients.navidrome_api import (
    CREDENTIALS_INVALID,
    CREDENTIALS_OK,
    verify_navidrome_credentials,
)

AUTH_METHOD_TELEGRAM = "telegram"
AUTH_METHOD_NAVIDROME = "navidrome"

LOGIN_OK = "ok"
LOGIN_INVALID = "invalid"
LOGIN_UNAVAILABLE = "unavailable"

MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 15 * 60
MAX_USERNAME_LENGTH = 128
MAX_PASSWORD_LENGTH = 1024
MAX_TRACKED_KEYS = 10_000


@dataclass(frozen=True)
class LoginResult:
    status: str  # LOGIN_OK / LOGIN_INVALID / LOGIN_UNAVAILABLE
    user_id: Optional[int] = None


def cap_access_level(level: AccessLevel, auth_method: str) -> AccessLevel:
    """Navidrome-Logins höchstens ADMIN (Nutzerentscheidung) - OWNER nur
    über den Telegram-Login."""
    if auth_method == AUTH_METHOD_NAVIDROME and level.value > AccessLevel.ADMIN.value:
        return AccessLevel.ADMIN
    return level


def resolve_user_id_for_navidrome_user(user_data: dict, navidrome_user: str) -> Optional[int]:
    """ID des (einzigen) Benutzers, dem dieser Navidrome-Benutzer zugeordnet
    ist - Vergleich ohne Groß-/Kleinschreibung. Kein Treffer oder mehrere
    Treffer (mehrdeutig) -> None (nicht freigeschaltet)."""
    wanted = (navidrome_user or "").strip().casefold()
    if not wanted:
        return None
    matches = []
    for key, entry in user_data.items():
        existing = ((entry or {}).get("navidrome_user") or "").strip().casefold()
        if existing and existing == wanted:
            try:
                matches.append(int(key))
            except (TypeError, ValueError):
                continue
    return matches[0] if len(matches) == 1 else None


def authenticate_navidrome_login(
    user_data: dict,
    username: str,
    password: str,
    *,
    verifier: Callable[[str, str], str] = verify_navidrome_credentials,
) -> LoginResult:
    """Prüft zuerst die Zugangsdaten bei Navidrome, dann die Freischaltung.
    Nicht freigeschaltete Konten liefern dasselbe LOGIN_INVALID wie ein
    falsches Passwort."""
    username = (username or "").strip()
    if (
        not username
        or not password
        or len(username) > MAX_USERNAME_LENGTH
        or len(password) > MAX_PASSWORD_LENGTH
    ):
        return LoginResult(LOGIN_INVALID)
    outcome = verifier(username, password)
    if outcome == CREDENTIALS_INVALID:
        return LoginResult(LOGIN_INVALID)
    if outcome != CREDENTIALS_OK:
        return LoginResult(LOGIN_UNAVAILABLE)
    user_id = resolve_user_id_for_navidrome_user(user_data, username)
    if user_id is None:
        return LoginResult(LOGIN_INVALID)
    return LoginResult(LOGIN_OK, user_id)


class LoginRateLimiter:
    """Fehlversuche pro Schlüssel (z. B. "user:alice", "ip:1.2.3.4") in
    einem gleitenden Fenster. Prozesslokal, In-Memory (nur der CC-Prozess
    nimmt Logins an) - thread-sicher, da FastAPI sync-Routen im Threadpool
    laufen."""

    def __init__(
        self,
        max_failures: int = MAX_FAILURES,
        window_seconds: float = FAILURE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._clock = clock
        self._failures: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> Deque[float]:
        entries = self._failures.setdefault(key, deque())
        while entries and now - entries[0] > self._window:
            entries.popleft()
        return entries

    def retry_after(self, keys: Iterable[str]) -> Optional[int]:
        """Sekunden bis zum nächsten erlaubten Versuch, falls einer der
        Schlüssel gesperrt ist - sonst None."""
        now = self._clock()
        wait = 0.0
        with self._lock:
            for key in keys:
                entries = self._prune(key, now)
                if not entries:
                    # Leere Einträge sofort entfernen - sonst wächst das Dict
                    # mit jedem je versuchten Namen/jeder IP unbegrenzt.
                    del self._failures[key]
                    continue
                if len(entries) >= self._max:
                    wait = max(wait, self._window - (now - entries[0]))
        return int(wait) + 1 if wait > 0 else None

    def tracked_keys(self) -> int:
        """Anzahl aktuell gehaltener Schlüssel (Diagnose/Tests)."""
        with self._lock:
            return len(self._failures)

    def register_failure(self, keys: Iterable[str]) -> None:
        now = self._clock()
        with self._lock:
            for key in keys:
                self._prune(key, now).append(now)
            if len(self._failures) > MAX_TRACKED_KEYS:
                # Obergrenze gegen Speicherwachstum (viele einmalige
                # Namen/IPs): abgelaufene Einträge komplett entfernen.
                for key in list(self._failures):
                    if not self._prune(key, now):
                        del self._failures[key]

    def reset(self, keys: Iterable[str]) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)
