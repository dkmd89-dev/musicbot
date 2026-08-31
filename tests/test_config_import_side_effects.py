"""
Characterization-Tests fuer CFG-001 (docs/archive/MusicBot_ENGINEERING_BASELINE.md):
"import config" hat Seiteneffekte, die beim reinen Import ausgefuehrt
werden (nicht erst bei expliziter Initialisierung) - .env-Datei-Suche
ueber mehrere Pfade, print()-Ausgaben (nicht ueber das logging-Modul),
optionale Abhaengigkeits-Importe mit print()-Fallback-Warnungen.

Da Modul-Level-Code nur beim ERSTEN Import pro Python-Prozess laeuft,
werden diese Tests ueber subprocess in einem frischen Interpreter
ausgefuehrt - sonst wuerde der bereits im Test-Prozess gecachte
sys.modules["config"] die Seiteneffekte verschlucken.

Fund im Rahmen dieser Charakterisierung: env_paths enthielt einen
hartcodierten, maschinenspezifischen Absolutpfad
(Path("/mnt/128ssd/musicbot/.env")) als dritten Fallback - komplett
redundant zum ersten, portablen Pfad (Path(__file__).parent / ".env"),
da config.py selbst in diesem Verzeichnis liegt. Der hartcodierte Pfad
konnte nur dann je greifen, wenn config.py auf GENAU dieser Maschine an
einen anderen Ort verschoben wuerde, .env aber am alten Pfad bliebe - ein
Edge-Case, der eher nach vergessenem Debug-Workaround aussieht als nach
Absicht. Entfernt (siehe CFG-001 in der Baseline). Verhaltensaenderung:
keine - der erste Pfad deckt exakt denselben Fall ab.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_fresh_import(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestEnvFileLoadingAtImportTime:
    def test_importing_config_prints_env_loaded_message(self):
        result = _run_fresh_import("import config")
        assert "✅ .env geladen von:" in result.stdout

    def test_env_file_resolved_via_config_relative_path(self):
        """
        Regressionstest fuer die CFG-001-Bereinigung: die .env wird ueber
        den ersten, portablen Pfad (Path(__file__).parent / ".env")
        gefunden - der entfernte hartcodierte Absolutpfad war nie
        tatsaechlich noetig.
        """
        result = _run_fresh_import("import config")
        assert str(REPO_ROOT / ".env") in result.stdout

    def test_env_vars_actually_available_after_import(self):
        """
        Nicht nur die Print-Meldung pruefen, sondern dass load_dotenv()
        tatsaechlich funktioniert hat - eine bekannte .env-Variable muss
        danach in os.environ verfuegbar sein.
        """
        result = _run_fresh_import(
            "import config, os; "
            "print('BOT_TOKEN_SET=' + str(bool(os.environ.get('BOT_TOKEN'))))"
        )
        assert "BOT_TOKEN_SET=True" in result.stdout


class TestOptionalDependencyFlags:
    def test_genius_available_flag_reflects_real_import(self):
        result = _run_fresh_import(
            "import config; print('GENIUS=' + str(config.GENIUS_AVAILABLE))"
        )
        assert "GENIUS=True" in result.stdout

    def test_musicbrainz_available_flag_reflects_real_import(self):
        result = _run_fresh_import(
            "import config; print('MB=' + str(config.MUSICBRAINZ_AVAILABLE))"
        )
        assert "MB=True" in result.stdout


class TestDeadInitializationMethods:
    """
    LEGACY-004 (siehe Baseline): Config.init(), Config.create_directory_structure()
    und Config.validate_config() haben keinen einzigen Aufrufer im Repo -
    weder bot.py noch irgendein Handler ruft sie auf. Die dort gebuendelte
    Logik (Verzeichnisse anlegen, Genius/MusicBrainz initialisieren,
    Logger-Level fuer Drittanbieter-Bibliotheken reduzieren) laeuft in
    Produktion daher NIE. Bewusst nicht entfernt (Legacy-Regel), nur
    charakterisiert.
    """

    def test_init_exists_but_has_no_callers_in_production_code(self):
        import config

        assert hasattr(config.Config, "init")
        # Bewusst kein Verhaltens-Test des Methodeninhalts - reine
        # Existenz-/Charakterisierungspruefung, siehe Docstring.

    def test_create_directory_structure_exists_but_unused(self):
        import config

        assert hasattr(config.Config, "create_directory_structure")

    def test_validate_config_exists_but_unused(self):
        import config

        assert hasattr(config.Config, "validate_config")
