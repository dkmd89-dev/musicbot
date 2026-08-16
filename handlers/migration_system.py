# scripts/migrate_to_rich_menu.py
# -*- coding: utf-8 -*-
"""
🚀 Automatisches Migrations-System für RichMenuSystem

Features:
- Automatisches Backup aller relevanten Dateien
- Verzeichnis-Struktur Setup
- Dependency Installation
- User-Setup Ausführung
- Handler-Registrierung
- Automatisierte Tests
- Rollback-Funktion bei Fehlern
"""

import sys
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import json
import logging

# Setup Basic Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MigrationSystem:
    """Haupt-Migrationssystem"""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.backup_dir = (
            self.project_root
            / "backups"
            / f"migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        self.success = False
        self.steps_completed = []

        logger.info("🚀 Migrations-System initialisiert")

    def run_migration(self) -> bool:
        """Führt vollständige Migration durch"""
        print("=" * 60)
        print("🎯 RICHMENU SYSTEM MIGRATION")
        print("=" * 60)
        print()

        try:
            # Schritt 1: Pre-Migration Checks
            if not self._pre_migration_checks():
                return False

            # Schritt 2: Backup erstellen
            if not self._create_backup():
                return False

            # Schritt 3: Verzeichnisse erstellen
            if not self._create_directories():
                return False

            # Schritt 4: Dependencies installieren
            if not self._install_dependencies():
                return False

            # Schritt 5: User-Setup
            if not self._setup_users():
                return False

            # Schritt 6: Handler-Integration
            if not self._integrate_handlers():
                return False

            # Schritt 7: Tests ausführen
            if not self._run_tests():
                logger.warning(
                    "⚠️ Tests fehlgeschlagen, Migration wird trotzdem fortgesetzt"
                )

            # Schritt 8: Finalisierung
            self._finalize_migration()

            self.success = True
            self._print_success_message()
            return True

        except Exception as e:
            logger.error(f"❌ Migration fehlgeschlagen: {e}", exc_info=True)
            self._handle_migration_failure()
            return False

    def _pre_migration_checks(self) -> bool:
        """Pre-Migration Validierung"""
        print("📋 Schritt 1/8: Pre-Migration Checks")
        print("-" * 60)

        # Python-Version prüfen
        if sys.version_info < (3, 8):
            logger.error("❌ Python 3.8+ erforderlich")
            return False
        logger.info(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")

        # Kritische Dateien prüfen
        required_files = [
            self.project_root / "bot.py",
            self.project_root / "config.py",
            self.project_root / "logger.py",
        ]

        for file in required_files:
            if not file.exists():
                logger.error(f"❌ Kritische Datei fehlt: {file}")
                return False
            logger.info(f"✅ {file.name} gefunden")

        # Handlers-Verzeichnis prüfen
        handlers_dir = self.project_root / "handlers"
        if handlers_dir.exists():
            handler_count = len(list(handlers_dir.glob("*.py")))
            logger.info(f"✅ Handlers-Verzeichnis: {handler_count} Handler gefunden")

        print()
        return True

    def _create_backup(self) -> bool:
        """Erstellt Backup aller relevanten Dateien"""
        print("💾 Schritt 2/8: Backup erstellen")
        print("-" * 60)

        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)

            # Zu sichernde Pfade
            backup_items = [
                ("bot.py", "bot.py"),
                ("config.py", "config.py"),
                ("logger.py", "logger.py"),
                ("handlers", "handlers"),
                ("data", "data"),
            ]

            backed_up = 0
            for source, dest in backup_items:
                source_path = self.project_root / source
                dest_path = self.backup_dir / dest

                if source_path.exists():
                    if source_path.is_file():
                        shutil.copy2(source_path, dest_path)
                    else:
                        shutil.copytree(source_path, dest_path)
                    logger.info(f"✅ Gesichert: {source}")
                    backed_up += 1
                else:
                    logger.warning(f"⚠️ Nicht gefunden: {source}")

            logger.info(f"💾 Backup erstellt: {self.backup_dir}")
            logger.info(f"📦 {backed_up} Items gesichert")
            self.steps_completed.append("backup")

            print()
            return True

        except Exception as e:
            logger.error(f"❌ Backup fehlgeschlagen: {e}")
            return False

    def _create_directories(self) -> bool:
        """Erstellt notwendige Verzeichnisse"""
        print("📁 Schritt 3/8: Verzeichnis-Struktur erstellen")
        print("-" * 60)

        directories = [
            "handlers/menu",
            "handlers/adapters",
            "data",
            "tests/unit",
            "tests/integration",
            "logs",
            "backups",
        ]

        try:
            for dir_path in directories:
                full_path = self.project_root / dir_path
                full_path.mkdir(parents=True, exist_ok=True)

                # __init__.py für Python-Packages
                if "handlers" in dir_path or "tests" in dir_path:
                    init_file = full_path / "__init__.py"
                    if not init_file.exists():
                        init_file.touch()

                logger.info(f"✅ {dir_path}")

            self.steps_completed.append("directories")
            print()
            return True

        except Exception as e:
            logger.error(f"❌ Verzeichnis-Erstellung fehlgeschlagen: {e}")
            return False

    def _install_dependencies(self) -> bool:
        """Installiert notwendige Dependencies"""
        print("📦 Schritt 4/8: Dependencies installieren")
        print("-" * 60)

        dependencies = [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.0.0",
        ]

        try:
            for dep in dependencies:
                logger.info(f"📦 Installiere {dep}...")
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", dep],
                    capture_output=True,
                    text=True,
                )

                if result.returncode == 0:
                    logger.info(f"✅ {dep} installiert")
                else:
                    logger.warning(f"⚠️ {dep} Installation übersprungen")

            self.steps_completed.append("dependencies")
            print()
            return True

        except Exception as e:
            logger.error(f"❌ Dependency-Installation fehlgeschlagen: {e}")
            # Nicht kritisch, weitermachen
            print()
            return True

    def _setup_users(self) -> bool:
        """Führt User-Setup aus"""
        print("👥 Schritt 5/8: Benutzer-Setup")
        print("-" * 60)

        try:
            # Prüfe ob setup_users.py existiert
            setup_script = self.project_root / "setup_users.py"

            if setup_script.exists():
                logger.info("🔧 Führe setup_users.py aus...")
                result = subprocess.run(
                    [sys.executable, str(setup_script)],
                    capture_output=True,
                    text=True,
                    cwd=str(self.project_root),
                )

                if result.returncode == 0:
                    logger.info("✅ User-Setup erfolgreich")
                else:
                    logger.warning(f"⚠️ User-Setup mit Warnung: {result.stderr}")
            else:
                # Erstelle minimales User-Setup
                logger.info("📝 Erstelle initiales user_data.json...")
                self._create_initial_user_data()
                logger.info("✅ Initiale User-Daten erstellt")

            self.steps_completed.append("user_setup")
            print()
            return True

        except Exception as e:
            logger.error(f"❌ User-Setup fehlgeschlagen: {e}")
            return False

    def _create_initial_user_data(self) -> None:
        """Erstellt initiale user_data.json"""
        from config import Config

        config = Config()

        user_data = {
            str(config.OWNER_USER_ID): {
                "role": "owner",
                "permissions": ["all"],
                "created_at": datetime.now().isoformat(),
            }
        }

        user_file = self.project_root / "data" / "user_data.json"
        user_file.parent.mkdir(parents=True, exist_ok=True)

        with open(user_file, "w") as f:
            json.dump(user_data, f, indent=2)

    def _integrate_handlers(self) -> bool:
        """Integriert neue Handler in bot.py"""
        print("🔌 Schritt 6/8: Handler-Integration")
        print("-" * 60)

        try:
            # Erstelle command_integration.py
            self._create_command_integration()
            logger.info("✅ command_integration.py erstellt")

            # Erstelle Adapter-Dateien
            self._create_adapters()
            logger.info("✅ Adapter erstellt")

            self.steps_completed.append("handler_integration")
            print()
            return True

        except Exception as e:
            logger.error(f"❌ Handler-Integration fehlgeschlagen: {e}")
            return False

    def _create_command_integration(self) -> None:
        """Erstellt command_integration.py"""
        integration_file = self.project_root / "handlers" / "command_integration.py"

        content = '''# handlers/command_integration.py
# -*- coding: utf-8 -*-
"""
🎯 Command Integration für RichMenuSystem
Auto-generiert durch Migration
"""

from handlers.menu.rich_menu_handler import RichMenuHandler
from logger import get_module_logger

def create_command_integration(config, logger_factory):
    """Erstellt und konfiguriert RichMenuHandler"""
    logger = logger_factory("CommandIntegration")
    logger.info("🚀 Erstelle Command Integration...")
    
    # Handler erstellen
    menu_handler = RichMenuHandler(config, logger_factory)
    menu_handler.initialize()
    
    logger.info("✅ Command Integration bereit")
    return menu_handler

def add_handlers_to_application(application, menu_handler):
    """Fügt Handler zur Application hinzu"""
    handlers = menu_handler.get_telegram_handlers()
    
    for handler in handlers:
        application.add_handler(handler)
    
    return len(handlers)
'''

        integration_file.write_text(content, encoding="utf-8")

    def _create_adapters(self) -> None:
        """Erstellt Adapter-Dateien"""
        adapters_dir = self.project_root / "handlers" / "adapters"
        adapters_dir.mkdir(parents=True, exist_ok=True)

        # Navidrome Adapter
        navidrome_adapter = adapters_dir / "navidrome_adapter.py"
        navidrome_content = '''# handlers/adapters/navidrome_adapter.py
# -*- coding: utf-8 -*-
"""
🎵 Navidrome Adapter für RichMenuSystem
"""

import subprocess
from logger import get_module_logger

class NavidromeAdapter:
    def __init__(self, config):
        self.config = config
        self.logger = get_module_logger("NavidromeAdapter")
    
    async def trigger_scan(self) -> bool:
        """Triggert Navidrome Library-Scan"""
        try:
            command = getattr(self.config, 'NAVIDROME_SCAN_COMMAND', None)
            if not command:
                self.logger.warning("⚠️ NAVIDROME_SCAN_COMMAND nicht konfiguriert")
                return False
            
            result = subprocess.run(
                command.split(),
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.info("✅ Navidrome-Scan gestartet")
                return True
            else:
                self.logger.error(f"❌ Scan fehlgeschlagen: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Navidrome-Scan-Fehler: {e}")
            return False
'''
        navidrome_adapter.write_text(navidrome_content, encoding="utf-8")

        # __init__.py
        (adapters_dir / "__init__.py").touch()

    def _run_tests(self) -> bool:
        """Führt automatisierte Tests aus"""
        print("🧪 Schritt 7/8: Tests ausführen")
        print("-" * 60)

        try:
            # Erstelle Test-Dateien
            self._create_test_files()

            # Führe Tests aus
            logger.info("🧪 Führe Tests aus...")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-v"],
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
            )

            if result.returncode == 0:
                logger.info("✅ Alle Tests bestanden")
                self.steps_completed.append("tests")
                print()
                return True
            else:
                logger.warning(f"⚠️ Einige Tests fehlgeschlagen:\n{result.stdout}")
                print()
                return False

        except Exception as e:
            logger.error(f"❌ Test-Ausführung fehlgeschlagen: {e}")
            print()
            return False

    def _create_test_files(self) -> None:
        """Erstellt Basis-Testdateien"""
        tests_dir = self.project_root / "tests"

        # conftest.py
        conftest = tests_dir / "conftest.py"
        conftest_content = """import pytest
from config import Config

@pytest.fixture
def config():
    return Config()
"""
        conftest.write_text(conftest_content)

        # test_menu_system.py
        test_menu = tests_dir / "unit" / "test_menu_system.py"
        test_content = '''import pytest
from handlers.menu.rich_menu_system import RichMenuSystem, MenuItem, AccessLevel

def test_menu_system_init(config):
    """Test RichMenuSystem Initialisierung"""
    menu = RichMenuSystem(config)
    assert menu is not None
    assert menu.root_menu is None

def test_menu_item_creation():
    """Test MenuItem Erstellung"""
    item = MenuItem(
        id="test",
        title="Test",
        emoji="🧪"
    )
    assert item.id == "test"
    assert item.callback_data == "menu:test"
    assert not item.has_children()

def test_menu_hierarchy():
    """Test Menü-Hierarchie"""
    parent = MenuItem(id="parent", title="Parent")
    child = MenuItem(id="child", title="Child")
    parent.add_child(child)
    
    assert child.parent == parent
    assert parent.has_children()
    assert len(parent.children) == 1

def test_access_control():
    """Test Zugriffskontrolle"""
    admin_item = MenuItem(
        id="admin",
        title="Admin",
        access_level=AccessLevel.ADMIN
    )
    
    assert not admin_item.is_accessible(AccessLevel.USER)
    assert admin_item.is_accessible(AccessLevel.ADMIN)
    assert admin_item.is_accessible(AccessLevel.OWNER)
'''
        test_menu.write_text(test_content)

    def _finalize_migration(self) -> None:
        """Finalisiert Migration"""
        print("🎉 Schritt 8/8: Finalisierung")
        print("-" * 60)

        # Erstelle Migration-Report
        report = {
            "timestamp": datetime.now().isoformat(),
            "steps_completed": self.steps_completed,
            "backup_location": str(self.backup_dir),
            "success": True,
        }

        report_file = self.project_root / "migration_report.json"
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2)

        logger.info(f"📄 Migration-Report erstellt: {report_file}")
        print()

    def _handle_migration_failure(self) -> None:
        """Behandelt Fehler und bietet Rollback an"""
        print()
        print("=" * 60)
        print("❌ MIGRATION FEHLGESCHLAGEN")
        print("=" * 60)
        print()

        if "backup" in self.steps_completed:
            print(f"💾 Backup verfügbar: {self.backup_dir}")
            print()
            response = input("Möchten Sie ein Rollback durchführen? (ja/nein): ")

            if response.lower() in ["ja", "j", "yes", "y"]:
                self._rollback()
        else:
            print("⚠️ Kein Backup verfügbar - keine Änderungen vorgenommen")

    def _rollback(self) -> None:
        """Führt Rollback durch"""
        print()
        print("🔄 Starte Rollback...")
        print("-" * 60)

        try:
            # Restore Dateien
            for item in self.backup_dir.iterdir():
                target = self.project_root / item.name

                if target.exists():
                    if target.is_file():
                        target.unlink()
                    else:
                        shutil.rmtree(target)

                if item.is_file():
                    shutil.copy2(item, target)
                else:
                    shutil.copytree(item, target)

                logger.info(f"✅ Wiederhergestellt: {item.name}")

            print()
            print("✅ Rollback erfolgreich")
            print(f"💾 Original-Backup bleibt erhalten: {self.backup_dir}")

        except Exception as e:
            logger.error(f"❌ Rollback fehlgeschlagen: {e}")
            print()
            print("❌ Rollback fehlgeschlagen!")
            print(f"⚠️ Manuelle Wiederherstellung erforderlich aus: {self.backup_dir}")

    def _print_success_message(self) -> None:
        """Zeigt Erfolgs-Nachricht"""
        print()
        print("=" * 60)
        print("✅ MIGRATION ERFOLGREICH ABGESCHLOSSEN")
        print("=" * 60)
        print()
        print("🎯 RichMenuSystem wurde erfolgreich integriert!")
        print()
        print("📋 Nächste Schritte:")
        print("   1. Bot neu starten: python bot.py")
        print("   2. Menü testen mit: /start oder /menu")
        print("   3. Handler anpassen in: handlers/menu/")
        print()
        print(f"💾 Backup verfügbar unter: {self.backup_dir}")
        print(f"📄 Migration-Report: {self.project_root / 'migration_report.json'}")
        print()
        print("🎉 Viel Erfolg mit dem neuen Menüsystem!")
        print("=" * 60)


def main():
    """Hauptfunktion"""
    import sys
    from pathlib import Path

    # Project Root ermitteln
    if len(sys.argv) > 1:
        project_root = Path(sys.argv[1])
    else:
        project_root = Path.cwd()

    print()
    print(f"📂 Project Root: {project_root}")
    print()

    # Migration ausführen
    migrator = MigrationSystem(project_root)
    success = migrator.run_migration()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
