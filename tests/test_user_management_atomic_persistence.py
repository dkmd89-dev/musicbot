"""
P0-C (docs/MusicBot_ARCHITECTURE_EVOLUTION.md, Abschnitt 27):
handlers/admin/user_management_handler.py::_save_users() schrieb
data/user_data.json (Rollen/Berechtigungen, sicherheitsrelevant) vorher per
direktem open(mode="w") + json.dump() - ein Prozessabbruch waehrend des
Schreibens konnte die Datei leeren oder korrumpieren, mit dem Risiko eines
Admin-/Owner-Lockouts (hoechste Einzelkritikalitaet im gesamten INV-02-Sweep,
siehe Architecture-Evolution-Audit).

Fix: write-tmp + atomarer rename, analog zu MetadataCache.store()
(utils/metadata_cache.py). INV-01 ist fuer diese Komponente nicht betroffen -
_save_users() bleibt eine kleine, synchrone Methode ohne meaningful
Blockierungskosten (siehe Architecture-Evolution-Audit, INV-01-Tabelle -
user_management_handler.py wurde dort NICHT gelistet).

Nutzt dieselbe _make_handler()-Fixture wie tests/test_user_management_handler.py
(Path()-Patch waehrend der Konstruktion), damit KEIN Test jemals die reale
data/user_data.json beruehrt - siehe dortiger Modul-Docstring.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from handlers.admin.user_management_handler import UserManagementHandler


class FakeConfig:
    OWNER_USER_ID = 111
    ADMIN_USER_IDS = [111, 222]


def _make_handler(tmp_path, config=None):
    user_data_file = tmp_path / "user_data.json"

    def _fake_path(p, *args, **kwargs):
        if p == "data/user_data.json":
            return user_data_file
        return Path(p, *args, **kwargs)

    with patch(
        "handlers.admin.user_management_handler.Path", side_effect=_fake_path
    ):
        handler = UserManagementHandler(config or FakeConfig())
    return handler, user_data_file


class TestSaveUsersAtomicWrite:
    def test_interrupted_write_leaves_previous_valid_data_untouched(
        self, tmp_path, monkeypatch
    ):
        handler, user_data_file = _make_handler(tmp_path)

        # Erster, erfolgreicher Schreibvorgang - reale Datei auf Platte.
        ok = handler._save_users({"111": {"role": "owner", "permissions": ["all"]}})
        assert ok is True
        original_content = user_data_file.read_text(encoding="utf-8")

        # Zweiter Schreibvorgang wird simuliert unterbrochen (Absturz waehrend
        # json.dump() - z.B. ein Rollenwechsel, der den Owner versehentlich
        # entfernt).
        monkeypatch.setattr(
            "handlers.admin.user_management_handler.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        result = handler._save_users({})  # wuerde den Owner "entfernen"

        assert result is False  # Fehler wird korrekt gemeldet, kein stiller Erfolg

        # Die Datei muss weiterhin ihren letzten GUELTIGEN Zustand haben -
        # der Owner-Eintrag darf NICHT verloren gehen (Lockout-Risiko).
        assert user_data_file.read_text(encoding="utf-8") == original_content

    def test_interrupted_write_leaves_no_leftover_tmp_file(
        self, tmp_path, monkeypatch
    ):
        handler, user_data_file = _make_handler(tmp_path)
        monkeypatch.setattr(
            "handlers.admin.user_management_handler.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        handler._save_users({"111": {"role": "owner"}})

        leftover = list(tmp_path.glob("*.tmp_*"))
        assert leftover == []

    def test_interrupted_write_does_not_update_in_memory_cache(
        self, tmp_path, monkeypatch
    ):
        """
        Stellt sicher, dass bei fehlgeschlagenem Schreiben auch der
        In-Memory-Cache (self.user_data_cache) NICHT auf den (nicht
        persistierten) neuen Stand gesetzt wird - sonst wuerde der laufende
        Bot-Prozess einen Owner-Verlust glauben, obwohl die Datei auf Platte
        noch den alten, gueltigen Stand hat (stiller Widerspruch zwischen
        RAM und Disk).
        """
        handler, _ = _make_handler(tmp_path)
        handler._save_users({"111": {"role": "owner"}})

        monkeypatch.setattr(
            "handlers.admin.user_management_handler.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        handler._save_users({})

        assert "111" in handler.user_data_cache

    def test_successful_write_updates_file_and_cache(self, tmp_path):
        handler, user_data_file = _make_handler(tmp_path)
        ok = handler._save_users({"222": {"role": "admin"}})

        assert ok is True
        assert "222" in handler.user_data_cache
        reloaded = handler._load_users()
        assert reloaded == {"222": {"role": "admin"}}
