"""
MIG-06 (docs/FINDINGS_INDEX.md, urspruenglich docs/audits/
SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md Abschnitt 16): kein
automatisierter Test sicherte die in CLAUDE.md Abschnitt 4 dokumentierte
Schichtgrenze ab - `services/` darf nie `handlers/`/`klassen/` importieren
(Praesentationsschicht bzw. deren historisch gewachsene Ausnahme) und nie
Telegram-Objekte/-Typen direkt referenzieren (`telegram`-Package). Der
Architektur-Audit bestaetigte zum damaligen Zeitpunkt 0 Verletzungen nur
durch manuelle Pruefung - ein kuenftiger Import haette unbemerkt
eingefuehrt werden koennen.

Dieser Test macht genau diese beiden Regeln dauerhaft, automatisiert
pruefbar. AST-basiert (nicht Text-Grep), damit ein "handlers"/"klassen"/
"telegram" in einem Kommentar oder String keinen falschen Treffer
erzeugt.

services/clients/ (externe Integrationsadapter) und services/duplicate/
-> services/metadata/ (P1, horizontale services/-interne Abhaengigkeit,
kein Grenzuebertritt) sind explizit erlaubt - die Grenze betrifft nur
handlers/klassen/telegram, keine services/-internen Importe.
"""

import ast
from pathlib import Path

import pytest

SERVICES_ROOT = Path(__file__).resolve().parent.parent / "services"
FORBIDDEN_TOP_LEVEL_MODULES = {"handlers", "klassen", "telegram"}


def _iter_service_py_files():
    return sorted(SERVICES_ROOT.rglob("*.py"))


def _imported_top_level_modules(py_file: Path) -> set:
    """Extrahiert alle top-level Modulnamen aus 'import x'/'from x import y'
    -Statements einer Datei via AST (robust gegen Kommentare/Strings, die
    zufaellig 'handlers'/'klassen'/'telegram' enthalten)."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # node.level > 0 = relativer Import (z.B. "from .models import X")
            # - kann per Definition nicht auf handlers/klassen/telegram
            # zeigen (bleibt innerhalb von services/), ausgenommen.
            if node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return modules


@pytest.fixture(params=_iter_service_py_files(), ids=lambda p: str(p.relative_to(SERVICES_ROOT)))
def service_py_file(request):
    return request.param


class TestServicesLayerBoundary:
    def test_service_module_does_not_import_forbidden_layers(self, service_py_file):
        imported = _imported_top_level_modules(service_py_file)
        violations = imported & FORBIDDEN_TOP_LEVEL_MODULES
        assert not violations, (
            f"{service_py_file.relative_to(SERVICES_ROOT.parent)} importiert "
            f"{violations} - services/ darf laut CLAUDE.md Abschnitt 4 nie "
            f"handlers/klassen/telegram importieren."
        )


class TestBoundaryTestItselfCatchesViolations:
    """Gegenprobe fuer den Boundary-Test selbst: bestaetigt, dass die
    AST-basierte Erkennung tatsaechlich einen Verstoss findet, statt nur
    zufaellig immer gruen zu sein (z.B. weil FORBIDDEN_TOP_LEVEL_MODULES
    nie greift)."""

    def test_detects_import_of_forbidden_module(self, tmp_path):
        offending_file = tmp_path / "fake_service.py"
        offending_file.write_text("import handlers\n", encoding="utf-8")

        modules = _imported_top_level_modules(offending_file)
        assert "handlers" in modules

    def test_detects_from_import_of_forbidden_module(self, tmp_path):
        offending_file = tmp_path / "fake_service.py"
        offending_file.write_text(
            "from telegram import Update, ParseMode\n", encoding="utf-8"
        )

        modules = _imported_top_level_modules(offending_file)
        assert "telegram" in modules

    def test_relative_import_is_not_flagged(self, tmp_path):
        """Relative Importe (z.B. innerhalb von services/metadata/) zeigen
        per Definition nie auf handlers/klassen/telegram - keine
        falschen Positiv-Treffer."""
        offending_file = tmp_path / "fake_service.py"
        offending_file.write_text("from .models import Something\n", encoding="utf-8")

        modules = _imported_top_level_modules(offending_file)
        assert not (modules & FORBIDDEN_TOP_LEVEL_MODULES)

    def test_string_mentioning_forbidden_module_is_not_flagged(self, tmp_path):
        """Ein 'handlers'/'telegram' in einem Kommentar oder String darf
        keinen falschen Treffer erzeugen (AST- statt Text-basiert)."""
        offending_file = tmp_path / "fake_service.py"
        offending_file.write_text(
            '# TODO: nicht wie in handlers/ machen\n'
            'MESSAGE = "wird nie an telegram gesendet"\n',
            encoding="utf-8",
        )

        modules = _imported_top_level_modules(offending_file)
        assert not (modules & FORBIDDEN_TOP_LEVEL_MODULES)


def test_at_least_one_services_file_was_actually_checked():
    """Schuetzt gegen ein stillschweigend leeres Parametrize (z.B. falscher
    SERVICES_ROOT-Pfad wuerde 0 Testfaelle in TestServicesLayerBoundary
    erzeugen - ein 'immer gruen, weil nichts geprueft wird'-Risiko)."""
    files = _iter_service_py_files()
    assert len(files) > 30, (
        f"Nur {len(files)} Dateien unter {SERVICES_ROOT} gefunden - "
        "SERVICES_ROOT-Pfad vermutlich falsch."
    )
