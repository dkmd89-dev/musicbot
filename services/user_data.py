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
save_user_data() ist die Schreib-Entsprechung für den Application-Layer
(services/user_admin.py), der von control_center/routers/admin.py
genutzt wird.

CC-AC-10G (Client Consolidation Phase A, A.3/A.9 "Single Write Path"):
UserManagementHandler._save_users() (Telegram-Seite) delegiert seit
dieser Migration ebenfalls hierher (dünner Wrapper, analog zu
_load_users()) — der zuvor bewusst duplizierte atomare
write-tmp+rename-Kern existiert jetzt nur noch an dieser Stelle.
tests/test_user_management_atomic_persistence.py patcht weiterhin
"handlers.admin.user_management_handler.json.dump", was den Crash-Fall
trotz der Delegation weiterhin korrekt simuliert: `import json` bindet
in beiden Modulen an dasselbe `sys.modules["json"]`-Objekt, ein
Monkeypatch auf das Attribut "json.dump" über einen beliebigen
Modulnamen wirkt daher global auf alle `json.dump(...)`-Aufrufe,
unabhängig davon, aus welcher Datei sie erfolgen (verifiziert durch
denselben Testlauf nach dieser Migration).

CC-AC-10G (A.7 "Cross-Process-Persistenzstrategie"): bot.service und
control-center.service laufen als unabhängige, dauerhaft laufende
Prozesse, die beide `data/user_data.json` lesen und schreiben. Der
bisherige atomare write-tmp+rename-Schutz (save_user_data()) verhindert
Korruption bei einem Absturz während des Schreibens, aber NICHT ein
klassisches Lost-Update-Race: laden beide Prozesse denselben Stand,
bevor einer speichert, überschreibt der zweite Save den ersten still.
update_user_data() schließt diese Lücke, indem sie den kompletten
Read-Modify-Write-Zyklus (load → mutator(users) → save) hinter einem
prozessübergreifenden `fcntl.flock` auf einer dedizierten `.lock`-Datei
serialisiert. Beide Clients (UserManagementHandler._update_users(),
control_center/routers/admin.py) nutzen ausschließlich diesen Zyklus für
mutierende Operationen — reine Lesezugriffe (Menü-/Listen-Rendering)
bleiben unlocked, da os.replace() ohnehin nie einen teilweise
geschriebenen Zustand sichtbar macht.
"""

from __future__ import annotations

import fcntl
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

DEFAULT_USER_DATA_FILE = Path("data/user_data.json")

_T = TypeVar("_T")


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
    """Schreibt `data/user_data.json` atomar (write-tmp + rename) — die
    einzige Schreibimplementierung, an die sowohl UserManagementHandler
    (Telegram) als auch control_center/routers/admin.py delegieren (siehe
    Modul-Docstring). Schützt nur vor Korruption durch einen Absturz
    während des Schreibens, NICHT vor einem Lost-Update-Race zwischen den
    beiden Prozessen — dafür update_user_data() verwenden, wenn zuvor im
    selben Zyklus geladen wurde."""
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


@contextmanager
def _cross_process_lock(path: Path):
    """Hält einen exklusiven `fcntl.flock` auf einer `<path>.lock`-Datei,
    solange der `with`-Block läuft — serialisiert den Read-Modify-Write-
    Zyklus zwischen bot.service und control-center.service (A.7). Die
    Lock-Datei selbst trägt keine Nutzdaten, nur ihr Dateideskriptor dient
    als Lock-Handle (Standardmuster für `fcntl.flock` unter Linux)."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def update_user_data(
    mutator: "Callable[[dict], _T]",
    path: "str | Path" = DEFAULT_USER_DATA_FILE,
    *,
    logger: Any = None,
) -> "tuple[_T, dict, bool]":
    """Atomarer, prozessübergreifend gesperrter Read-Modify-Write-Zyklus
    (A.7) — schließt das Lost-Update-Race, das load_user_data() +
    save_user_data() als getrennte Aufrufe offen lassen.

    `mutator(users)` mutiert das geladene Dict in-place (dasselbe Muster
    wie die Funktionen in services/user_admin.py) und darf eine
    `UserAdminError`-Subklasse werfen, um den Zyklus OHNE Schreiben
    abzubrechen — die Exception propagiert unverändert nach oben, der
    Lock wird trotzdem freigegeben (kontrolliert über `finally` in
    `_cross_process_lock()`).

    Gibt `(mutator-Ergebnis, geladenes/mutiertes users-Dict, saved)`
    zurück. `saved=False` bedeutet einen Schreibfehler (siehe
    save_user_data()) — das Mutator-Ergebnis bleibt trotzdem gültig, falls
    der Aufrufer es für eine Fehlermeldung braucht."""
    path = Path(path)
    with _cross_process_lock(path):
        users = load_user_data(path, logger=logger)
        result = mutator(users)
        saved = save_user_data(users, path, logger=logger)
    return result, users, saved
