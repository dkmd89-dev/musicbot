# tests/test_statistics_calculator_export_atomic_write.py
# -*- coding: utf-8 -*-
"""
Baseline v5/v6 Technical Debt (P3, One-Shot-Artefakt, geringes Risiko):
StatisticsCalculator.export_stats_to_json() schrieb die Export-Datei
bisher per direktem open(export_file, "w") + json.dump() - ein
Prozessabbruch/Fehler waehrend des Schreibens konnte eine unvollstaendige/
korrupte Export-Datei hinterlassen. Der Dateiname enthaelt bereits einen
Sekunden-Zeitstempel, ueberschreibt also nie einen vorherigen Export -
das Risiko betraf nur die eine, gerade erst erzeugte Datei selbst.

Zusaetzlicher Kontext (verifiziert per repo-weitem Grep): export_stats_
to_json() hat aktuell keinen Aufrufer in handlers/ - ueber Telegram
derzeit nicht erreichbar. Trotzdem fuer Konsistenz mit dem etablierten
Muster (RES-02, AE-03, DuplicateCache._write_json_atomic()) behoben.

Fix: write-tmp + atomarer os.replace(), identisches Muster.

Nutzt denselben Testaufbau wie tests/test_statistics_calculator.py
(make_calculator()-Helper mit echtem PlayHistoryRepository auf tmp_path).
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

from services.statistik.play_history_repository import PlayHistoryRepository
from services.statistik.statistics_calculator import StatisticsCalculator


def make_calculator(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    repo = PlayHistoryRepository(history_dir, logger=Mock())
    calc = StatisticsCalculator(repo, tmp_path / "exports", logger=Mock())
    return calc, repo


def _entry(artist: str, title: str, album: str = "Album", days_ago: int = 0):
    timestamp = (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {
        "timestamp": timestamp,
        "tracks": [{"title": title, "artist": artist, "album": album, "id": "1"}],
    }


class TestExportStatsToJsonAtomicWrite:
    def test_successful_export_writes_valid_file(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        repo.save([_entry("Bausa", "Song A", days_ago=1)], "alice")

        export_path = calc.export_stats_to_json(navidrome_username="alice")

        assert export_path is not None
        assert export_path.exists()

    def test_interrupted_write_leaves_no_partial_export_file(
        self, tmp_path, monkeypatch
    ):
        """
        Am ungefixten Code haette ein Fehler waehrend json.dump() eine
        unvollstaendige Datei direkt am finalen export_file-Pfad
        hinterlassen. Nach dem Fix darf am finalen Pfad ueberhaupt keine
        Datei entstehen, wenn os.replace() (der atomare Uebernahme-Schritt)
        fehlschlaegt - weder eine unvollstaendige noch eine leere.
        """
        calc, repo = make_calculator(tmp_path)
        repo.save([_entry("Bausa", "Song A", days_ago=1)], "alice")

        monkeypatch.setattr(
            "services.statistik.statistics_calculator.os.replace",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )

        export_path = calc.export_stats_to_json(navidrome_username="alice")

        assert export_path is None
        export_files = list((tmp_path / "exports").glob("statistics_*.json"))
        assert export_files == [], (
            "Am finalen Export-Pfad ist trotz fehlgeschlagenem os.replace() "
            "eine Datei entstanden - der atomare Uebernahme-Schritt schuetzt "
            "nicht wie erwartet."
        )

    def test_interrupted_write_leaves_no_leftover_tmp_files(
        self, tmp_path, monkeypatch
    ):
        calc, repo = make_calculator(tmp_path)
        repo.save([_entry("Bausa", "Song A", days_ago=1)], "alice")

        monkeypatch.setattr(
            "services.statistik.statistics_calculator.os.replace",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )

        calc.export_stats_to_json(navidrome_username="alice")

        leftover = [
            p for p in Path(tmp_path / "exports").iterdir() if ".tmp_" in p.name
        ]
        assert leftover == []
