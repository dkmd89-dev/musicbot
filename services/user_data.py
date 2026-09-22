# services/user_data.py
# -*- coding: utf-8 -*-
"""
Telegram-freie Kernlogik für `data/user_data.json` (Rollen-/Navidrome-
Zuordnung pro Telegram-User-ID) — extrahiert aus
handlers/admin/user_management_handler.py::UserManagementHandler
(Master-Prompt Regel 51 "Common Core"), damit sowohl der Telegram-Bot
als auch control_center/ dieselbe Datenquelle lesen können, ohne dass
control_center/ die schwerere, Telegram-gekoppelte
UserManagementHandler-Klasse importieren muss.

UserManagementHandler._load_users()/get_navidrome_user() delegieren seit
dieser Extraktion hierher (dünne Wrapper, unverändertes Verhalten) —
siehe dortige Docstrings. Schreiben (Rollenverwaltung, Telegram-Admin-UI)
bleibt vollständig in UserManagementHandler, hier bewusst NICHT
dupliziert (reine Lesefunktionen).

control_center/ nutzt load_user_data() zusätzlich, um denselben
Auth-Kern wie der Bot per Duck-Typing wiederzuverwenden: ein Objekt mit
`.user_data_cache`-Attribut reicht bereits als `user_mgmt_handler`-
Argument für handlers/menu/permissions.py::get_user_access_level()
(dort bereits so geschrieben, siehe dortiger hasattr()-Check) —
control_center/dependencies.py baut daher nur ein minimales
Adapter-Objekt, ohne permissions.py selbst zu ändern.

CC-AC-10B (Control Center Admin API, User Management Write-Parität):
save_user_data() ist die Schreib-Entsprechung für den neuen
Application-Layer (services/user_admin.py), der von
control_center/routers/admin.py genutzt wird. Bewusst NICHT identisch
mit UserManagementHandler._save_users() (Telegram-Seite) — jener bleibt
unverändert, weil tests/test_user_management_atomic_persistence.py den
Crash-Fall über einen Monkeypatch auf den exakten Modulpfad
"handlers.admin.user_management_handler.json.dump" simuliert; ein
Umleiten dieses Schreibpfads hierher würde diesen Regressionstest
unbemerkt wirkungslos machen. Beide Implementierungen teilen denselben
atomaren write-tmp+rename-Kern (analog zu MetadataCache.store()) —
bewusste, kleine Duplikation statt eines riskanten Eingriffs in einen
sicherheitskritischen, bereits getesteten Pfad (CC-AC-10G migriert die
Telegram-Seite bei Bedarf später bewusst auf diese gemeinsame Funktion).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

DEFAULT_USER_DATA_FILE = Path("data/user_data.json")


def load_user_data(path: "str | Path" = DEFAULT_USER_DATA_FILE, *, logger: Any = None) -> dict:
    """Lädt `data/user_data.json`. Liefert `{}` bei fehlender oder
    kaputter Datei — identisches Verhalten wie das ursprüngliche
    UserManagementHandler._load_users() (kein Absturz z. B. bei
    Erstinstallation ohne bisherige User-Daten)."""
    path = Path(path)
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    except Exception as e:  # noqa: BLE001
        if logger:
            logger.error(f"❌ Fehler beim Laden der User-Daten: {e}")
        return {}


def get_navidrome_user(user_data: dict, telegram_id: int) -> Optional[str]:
    """Navidrome-Username für eine Telegram-ID, oder None — identische
    Logik wie das ursprüngliche UserManagementHandler.get_navidrome_user()."""
    entry = user_data.get(str(telegram_id))
    if entry:
        nav_user = entry.get("navidrome_user")
        if nav_user and nav_user.strip():
            return nav_user
    return None


def get_user_role(user_data: dict, telegram_id: int) -> Optional[str]:
    """Rolle ("user"/"moderator"/"admin"/"owner") für eine Telegram-ID,
    oder None, wenn kein Eintrag existiert."""
    entry = user_data.get(str(telegram_id))
    if entry:
        return entry.get("role")
    return None


def save_user_data(
    users: dict, path: "str | Path" = DEFAULT_USER_DATA_FILE, *, logger: Any = None
) -> bool:
    """Schreibt `data/user_data.json` atomar (write-tmp + rename) — siehe
    Modul-Docstring, warum dies eine eigene Implementierung ist statt
    einer Delegation an UserManagementHandler._save_users()."""
    path = Path(path)
    tmp_path = path.with_suffix(f".tmp_{int(time.time() * 1000)}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
        tmp_path.replace(path)
        return True
    except Exception as e:  # noqa: BLE001
        if logger:
            logger.error(f"❌ Fehler beim Speichern der User-Daten: {e}")
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
