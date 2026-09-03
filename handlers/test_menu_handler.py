# handlers/test_menu_handler.py
# -*- coding: utf-8 -*-
"""
🧪 TEST-SYSTEM MENÜ-HANDLER
Unit-Tests, Integration-Tests und Code-Coverage über Telegram (Plain-Text-Version)
"""

import asyncio
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, TYPE_CHECKING
import json
import os

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from config import Config
from logger import get_module_logger, EnhancedLogger

# Die Markdown-Helfer werden nicht mehr benötigt

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler


class TestMenuHandler:
    """Handler für Test-System im Menü"""

    def __init__(self, config: Config, logger_factory=None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("TestMenuHandler")

        # Emoji für alle Log-Ausgaben dieses Moduls
        self.module_emoji = "🧪"

        # Test-Pfade
        self.project_root = Path(
            config.BASE_DIR if hasattr(config, "BASE_DIR") else "."
        )
        self.tests_dir = self.project_root / "tests"
        self.unit_tests_dir = self.tests_dir / "unit"
        self.integration_tests_dir = self.tests_dir / "integration"
        self.performance_tests_dir = self.tests_dir / "performance"

        # Test-Ergebnisse Cache
        self.test_results_cache: Dict[str, Any] = {}
        self.running_tests: Dict[int, str] = {}  # user_id -> test_type

        # Wird von RichMenuHandler nach der Konstruktion zugewiesen
        # (self.test_handler.error_handler = self.error_handler)
        self.error_handler: "Optional[EnhancedErrorHandler]" = None

        self.logger.info(f"{self.module_emoji} Test-Menu-Handler initialisiert.")

    async def run_unit_tests(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Führt Unit Tests aus"""
        await self._execute_test_run(update, "unit", timeout=600, context=context)

    async def run_integration_tests(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Führt Integration Tests aus"""
        await self._execute_test_run(
            update, "integration", timeout=600, context=context
        )

    async def run_performance_tests(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Führt Performance Tests aus"""
        await self._execute_test_run(
            update, "performance", timeout=900, context=context
        )

    async def _execute_test_run(
        self,
        update: Update,
        test_type: str,
        timeout: int,
        context: Optional[ContextTypes.DEFAULT_TYPE] = None,
    ):
        """Zentrale Methode zur Ausführung von Tests

        context ist optional (Default None) fuer Abwaertskompatibilitaet zu
        bestehenden direkten Aufrufen/Tests dieser internen Methode ohne
        Context-Objekt; ohne context kann der error_handler nicht sinnvoll
        benachrichtigen (siehe EnhancedErrorHandler.handle_exception - ohne
        telegram_context wird die Nutzerbenachrichtigung uebersprungen),
        deshalb greift in diesem Fall stets der lokale Fallback.
        """
        user_id = update.effective_user.id
        self.logger.info(
            f"{self.module_emoji} [{test_type}_tests] Anfrage von User {user_id} erhalten."
        )

        if user_id in self.running_tests:
            self.logger.warning(
                f"{self.module_emoji} [{test_type}_tests] User {user_id} hat bereits laufende Tests: {self.running_tests[user_id]}"
            )
            await update.callback_query.edit_message_text(
                f"⏳ Tests laufen bereits: {self.running_tests[user_id]}"
            )
            return

        self.running_tests[user_id] = test_type

        type_dirs = {
            "unit": self.unit_tests_dir,
            "integration": self.integration_tests_dir,
            "performance": self.performance_tests_dir,
        }
        test_dir = type_dirs[test_type]

        try:
            await update.callback_query.edit_message_text(
                f"⏳ Starte {test_type.title()}-Tests..."
            )

            # Prüfen, ob Testverzeichnis existiert
            if not test_dir.exists() or not any(test_dir.glob("test_*.py")):
                self.logger.warning(
                    f"{self.module_emoji} [{test_type}_tests] Keine Testdateien in {test_dir} gefunden."
                )
                await update.callback_query.edit_message_text(
                    f"📁 Keine {test_type.title()}-Tests gefunden.\nErwartet in: {test_dir}"
                )
                return

            # Test-Command erstellen
            cmd = [
                sys.executable,
                "-m",
                "pytest",
                str(test_dir),
                "-v",
                "--tb=short",
                "--no-header",
                f"--rootdir={self.project_root}",
            ]

            if test_type == "integration":
                cmd.append("-x")  # Stop bei erstem Fehler
            elif test_type == "performance":
                cmd.extend(["-m", "performance"])

            if test_type == "unit":
                try:
                    # INV-01: subprocess.run() blockiert synchron - ohne
                    # asyncio.to_thread() wuerde bereits dieser kurze
                    # Verfuegbarkeits-Check den Event-Loop fuer alle
                    # Telegram-Nutzer einfrieren (etabliertes Muster, siehe
                    # z.B. enhanced_metadata_processor.py::normalize_loudness()-
                    # Aufruf, FINDING-7).
                    await asyncio.to_thread(
                        subprocess.run,
                        [sys.executable, "-m", "coverage", "--version"],
                        capture_output=True,
                        timeout=5,
                        check=True,
                    )
                    cmd.extend(["--cov=.", "--cov-report=term-missing"])
                    self.logger.info(
                        f"{self.module_emoji} [{test_type}_tests] Code-Coverage wird miterfasst."
                    )
                except (subprocess.SubprocessError, FileNotFoundError):
                    pass  # Coverage nicht verfügbar

            await update.callback_query.edit_message_text(
                f"⏳ {test_type.title()}-Tests laufen...\nBitte warten (Timeout: {timeout}s)"
            )
            self.logger.debug(
                f"{self.module_emoji} [{test_type}_tests] Führe Kommando aus: {' '.join(cmd)}"
            )

            start_time = datetime.now()
            # INV-01: der eigentliche pytest-Lauf blockiert bis zu `timeout`
            # Sekunden (900s bei Performance-Tests) - ohne asyncio.to_thread()
            # friert das den gesamten Event-Loop fuer ALLE Telegram-Nutzer
            # ein, nicht nur fuer den anfragenden Admin.
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.project_root,
            )
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            self.logger.info(
                f"{self.module_emoji} [{test_type}_tests] Ausführung beendet in {duration:.2f}s mit Return-Code {result.returncode}."
            )

            test_results = self._parse_pytest_output(result.stdout, result.stderr)
            test_results.update(
                {
                    "duration": duration,
                    "timestamp": end_time.isoformat(),
                    "type": test_type,
                    "returncode": result.returncode,
                }
            )

            self.test_results_cache[test_type] = test_results
            await self._show_test_results(update, test_results, test_type, context=context)

        except subprocess.TimeoutExpired:
            self.logger.error(
                f"{self.module_emoji} [{test_type}_tests] Timeout ({timeout}s) überschritten."
            )
            await update.callback_query.edit_message_text(
                f"⏰ {test_type.title()}-Tests haben das Zeitlimit überschritten ({timeout}s). Abgebrochen."
            )
        except Exception as e:
            self.logger.error(
                f"{self.module_emoji} [_{test_type}_tests] Unerwarteter Fehler: {e}",
                exc_info=True,
            )
            if self.error_handler and context is not None:
                await self.error_handler.handle_callback_error(
                    update, context, f"test_run_{test_type}", e
                )
            else:
                await update.callback_query.edit_message_text(
                    f"❌ Fehler bei der Ausführung der {test_type.title()}-Tests:\n{str(e)}"
                )
        finally:
            if user_id in self.running_tests:
                del self.running_tests[user_id]
                self.logger.info(
                    f"{self.module_emoji} [{test_type}_tests] Test-Lock für User {user_id} entfernt."
                )

    def _parse_pytest_output(self, stdout: str, stderr: str) -> Dict[str, Any]:
        """Parse pytest output für Ergebnisse"""
        self.logger.debug(
            f"{self.module_emoji} [_parse_pytest_output] Starte Parsing der Test-Ausgabe."
        )
        results = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "stdout": stdout,
            "stderr": stderr,
            "failed_tests": [],
            "coverage": None,
        }

        try:
            lines = stdout.split("\n")
            for line in lines:
                stripped_line = line.strip()
                if (
                    (
                        "passed" in stripped_line
                        or "failed" in stripped_line
                        or "skipped" in stripped_line
                    )
                    and " in " in stripped_line
                    and stripped_line.startswith("=")
                ):
                    parts = stripped_line.replace("=", "").strip().split(",")
                    for part in parts:
                        part = part.strip()
                        num_str, *label_parts = part.split()
                        if num_str.isdigit():
                            num = int(num_str)
                            label = label_parts[0] if label_parts else ""
                            if "passed" in label:
                                results["passed"] = num
                            elif "failed" in label:
                                results["failed"] = num
                            elif "skipped" in label:
                                results["skipped"] = num
                            elif "error" in label:
                                results["errors"] = num

                if "TOTAL" in stripped_line and "%" in stripped_line:
                    parts = stripped_line.split()
                    if parts[-1].endswith("%"):
                        results["coverage"] = int(parts[-1].replace("%", ""))

                if "FAILED" in stripped_line and "::" in stripped_line:
                    results["failed_tests"].append(
                        stripped_line.split("FAILED", 1)[1].strip()
                    )

            results["total"] = (
                results["passed"]
                + results["failed"]
                + results["skipped"]
                + results["errors"]
            )
            self.logger.debug(
                f"{self.module_emoji} [_parse_pytest_output] Parsing erfolgreich: {results['total']} Tests gefunden."
            )
        except Exception as e:
            self.logger.warning(
                f"{self.module_emoji} [_parse_pytest_output] Fehler beim Parsen der Test-Ausgabe: {e}"
            )

        return results

    async def _show_test_results(
        self,
        update: Update,
        results: Dict[str, Any],
        test_type: str,
        context: Optional[ContextTypes.DEFAULT_TYPE] = None,
    ):
        """Zeigt Test-Ergebnisse formatiert als reinen Text an"""
        self.logger.info(
            f"{self.module_emoji} [_show_test_results] Zeige Ergebnisse für '{test_type}'-Tests an."
        )
        try:
            passed = results.get("passed", 0)
            failed = results.get("failed", 0)
            total = results.get("total", 0)
            status_emoji = (
                "✅" if failed == 0 and results.get("errors", 0) == 0 else "❌"
            )

            type_emojis = {"unit": "🧪", "integration": "🔗", "performance": "⚡"}
            type_emoji = type_emojis.get(test_type, "?")
            type_name = test_type.title()

            success_rate = (passed / max(total, 1)) * 100

            result_text = [
                f"{status_emoji} {type_emoji} {type_name} Test-Ergebnisse",
                "",
                "Übersicht:",
                f"• Gesamt: {total} Tests",
                f"• ✅ Erfolgreich: {passed} ({success_rate:.1f}%)",
                f"• ❌ Fehlgeschlagen: {results.get('failed', 0)}",
                f"• ⏭️ Übersprungen: {results.get('skipped', 0)}",
                f"• 💥 Fehler: {results.get('errors', 0)}",
                "",
                "Performance:",
                f"• ⏱️ Dauer: {results.get('duration', 0):.2f}s",
            ]

            if results.get("coverage") is not None:
                result_text.append(f"• 📈 Code Coverage: {results['coverage']}%")

            if results.get("failed_tests"):
                result_text.append("\nFehlgeschlagene Tests:")
                for test in results["failed_tests"][:5]:
                    result_text.append(f"• {test[:60]}")
                if len(results["failed_tests"]) > 5:
                    result_text.append(
                        f"• ... und {len(results['failed_tests']) - 5} weitere"
                    )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "📊 Details anzeigen", callback_data=f"test_details_{test_type}"
                    ),
                    InlineKeyboardButton(
                        "🔄 Wiederholen", callback_data=f"action_run_{test_type}_tests"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "📈 Coverage Report", callback_data="action_test_coverage"
                    ),
                    InlineKeyboardButton("🔙 Zurück", callback_data="menu_tests"),
                ],
            ]

            await update.callback_query.edit_message_text(
                text="\n".join(result_text), reply_markup=InlineKeyboardMarkup(keyboard)
            )

        except Exception as e:
            self.logger.error(
                f"{self.module_emoji} [_show_test_results] Fehler beim Anzeigen der Ergebnisse: {e}",
                exc_info=True,
            )
            if self.error_handler and context is not None:
                await self.error_handler.handle_callback_error(
                    update, context, "test_show_results", e
                )
            else:
                await update.callback_query.edit_message_text(
                    f"❌ Fehler beim Formatieren der Test-Ergebnisse:\n{str(e)}"
                )

    async def show_test_details(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, test_type: str
    ):
        """Zeigt detaillierte Test-Ergebnisse als reinen Text"""
        self.logger.info(
            f"{self.module_emoji} [show_test_details] Details für '{test_type}' angefordert."
        )
        if test_type not in self.test_results_cache:
            await update.callback_query.edit_message_text(
                f"❌ Keine {test_type}-Ergebnisse verfügbar."
            )
            return

        try:
            results = self.test_results_cache[test_type]
            stdout = results.get("stdout", "")
            stderr = results.get("stderr", "")

            output = []
            if stdout:
                lines = stdout.split("\n")
                relevant_lines = [
                    line
                    for line in lines
                    if any(
                        k in line.lower()
                        for k in ["passed", "failed", "error", "warning", "test_", "::"]
                    )
                ]
                output.extend(relevant_lines[-20:])  # Letzte 20 relevante Zeilen

            if stderr:
                output.append("\n--- FEHLER ---")
                output.append(stderr[-500:])

            details_text = "\n".join(output)
            if len(details_text) > 3800:
                details_text = "..." + details_text[-3800:]

            final_text = f"📋 {test_type.title()} Test Details:\n\n--- LOG AUSGABE ---\n{details_text}\n--- ENDE DER AUSGABE ---"

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📊 Zusammenfassung",
                            callback_data=f"test_results_{test_type}",
                        )
                    ],
                    [InlineKeyboardButton("🔙 Zurück", callback_data="menu_tests")],
                ]
            )

            await update.callback_query.edit_message_text(
                text=final_text, reply_markup=keyboard
            )

        except Exception as e:
            self.logger.error(
                f"{self.module_emoji} [show_test_details] Fehler: {e}", exc_info=True
            )
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "test_show_details", e
                )
            else:
                await update.callback_query.edit_message_text(
                    f"❌ Fehler beim Laden der Details:\n{str(e)}"
                )

    async def show_coverage_report(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Generiert und zeigt Code Coverage Report als reinen Text"""
        self.logger.info(
            f"{self.module_emoji} [show_coverage_report] Anfrage für Coverage-Report."
        )
        try:
            await update.callback_query.edit_message_text(
                "📈 Generiere Coverage Report..."
            )

            cmd_run = [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "-m",
                "pytest",
                str(self.unit_tests_dir),
            ]
            # INV-01: beide subprocess.run()-Aufrufe blockieren synchron
            # (bis zu 120s+30s) - asyncio.to_thread() wie im Testlauf oben.
            await asyncio.to_thread(
                subprocess.run,
                cmd_run,
                cwd=self.project_root,
                timeout=120,
                capture_output=True,
            )

            cmd_report = [
                sys.executable,
                "-m",
                "coverage",
                "report",
                "--show-missing",
                "--skip-covered",
            ]
            result = await asyncio.to_thread(
                subprocess.run,
                cmd_report,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.project_root,
            )

            if result.returncode != 0:
                raise RuntimeError(f"Coverage-Fehler: {result.stderr}")

            lines = result.stdout.split("\n")
            total_coverage = "Unbekannt"
            for line in reversed(lines):
                if "TOTAL" in line and "%" in line:
                    total_coverage = line.split()[-1]
                    break

            report_header = "📈 Code Coverage Report"
            report_total = f"Gesamt-Coverage: {total_coverage}"

            report_body = "--- Details (nicht abgedeckte Zeilen) ---\n"
            relevant_lines = [
                line
                for line in lines
                if line.strip()
                and not line.startswith("-")
                and "TOTAL" not in line
                and "Name" not in line
            ]
            report_body += "\n".join(relevant_lines[:20])

            final_text = f"{report_header}\n\n{report_total}\n\n{report_body}"

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Aktualisieren", callback_data="action_test_coverage"
                        )
                    ],
                    [InlineKeyboardButton("🔙 Zurück", callback_data="menu_tests")],
                ]
            )

            await update.callback_query.edit_message_text(
                text=final_text, reply_markup=keyboard
            )

        except subprocess.TimeoutExpired:
            self.logger.error(
                f"{self.module_emoji} [show_coverage_report] Timeout bei der Generierung."
            )
            await update.callback_query.edit_message_text(
                "⏰ Zeitlimit bei der Erstellung des Coverage Reports überschritten."
            )
        except Exception as e:
            self.logger.error(
                f"{self.module_emoji} [show_coverage_report] Fehler: {e}", exc_info=True
            )
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "test_coverage_report", e
                )
            else:
                await update.callback_query.edit_message_text(
                    f"❌ Fehler beim Generieren des Reports:\n{str(e)}"
                )

    async def show_all_test_results(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt Übersicht aller Test-Ergebnisse als reinen Text"""
        self.logger.info(
            f"{self.module_emoji} [show_all_test_results] Anfrage für Ergebnisübersicht."
        )
        if not self.test_results_cache:
            await update.callback_query.edit_message_text(
                "📊 Keine Test-Ergebnisse verfügbar."
            )
            return

        try:
            overview_parts = ["📊 Test-Ergebnisse Übersicht", ""]
            total_tests, total_passed, total_failed = 0, 0, 0

            type_emojis = {"unit": "🧪", "integration": "🔗", "performance": "⚡"}

            for test_type, results in self.test_results_cache.items():
                passed = results.get("passed", 0)
                failed = results.get("failed", 0)
                total = results.get("total", 0)
                status = "✅" if failed == 0 else "❌"

                overview_parts.append(
                    f"{type_emojis.get(test_type, '?')} {test_type.title()} Tests {status}"
                )
                overview_parts.append(f"   • Tests: {total} ({passed} ✅, {failed} ❌)")
                overview_parts.append(f"   • Dauer: {results.get('duration', 0):.2f}s")
                overview_parts.append("")

                total_tests += total
                total_passed += passed
                total_failed += failed

            if total_tests > 0:
                overall_success = (total_passed / total_tests) * 100
                overview_parts.append("📈 Gesamtstatistiken:")
                overview_parts.append(f"• Gesamt: {total_tests} Tests")
                overview_parts.append(
                    f"• Erfolgreich: {total_passed} ({overall_success:.1f}%)"
                )
                overview_parts.append(f"• Fehlgeschlagen: {total_failed}")

            keyboard = [
                [
                    InlineKeyboardButton(
                        "🔄 Alle Tests neu starten", callback_data="test_run_all"
                    )
                ],
                [InlineKeyboardButton("🔙 Zurück", callback_data="menu_tests")],
            ]

            await update.callback_query.edit_message_text(
                text="\n".join(overview_parts),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        except Exception as e:
            self.logger.error(
                f"{self.module_emoji} [show_all_test_results] Fehler: {e}",
                exc_info=True,
            )
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "test_all_results", e
                )
            else:
                await update.callback_query.edit_message_text(
                    f"❌ Fehler beim Laden der Übersicht:\n{str(e)}"
                )

    async def run_all_tests(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Führt alle verfügbaren Test-Typen nacheinander aus"""
        user_id = update.effective_user.id
        self.logger.info(
            f"{self.module_emoji} [run_all_tests] Komplette Test-Suite von User {user_id} angefordert."
        )

        if user_id in self.running_tests:
            await update.callback_query.edit_message_text(
                f"⏳ Tests laufen bereits: {self.running_tests[user_id]}"
            )
            return

        self.running_tests[user_id] = "all"

        try:
            await update.callback_query.edit_message_text(
                "🚀 Starte komplette Test-Suite..."
            )

            test_types = ["unit", "integration", "performance"]
            for i, test_type in enumerate(test_types):
                self.logger.info(
                    f"{self.module_emoji} [run_all_tests] Starte Teil {i+1}/{len(test_types)}: {test_type}-Tests."
                )
                await update.callback_query.edit_message_text(
                    f"⏳ {i+1}/{len(test_types)}: Führe {test_type}-Tests aus..."
                )

                # Interne Ausführung ohne UI-Feedback, da _execute_test_run für Callbacks gedacht ist.
                # Wir rufen hier eine vereinfachte, interne Version auf.
                await self._run_test_type(test_type)

            self.logger.info(
                f"{self.module_emoji} [run_all_tests] Alle Tests abgeschlossen. Zeige Übersicht."
            )
            await self.show_all_test_results(update, context)

        except Exception as e:
            self.logger.error(
                f"{self.module_emoji} [run_all_tests] Fehler in der Test-Suite: {e}",
                exc_info=True,
            )
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "test_run_all", e
                )
            else:
                await update.callback_query.edit_message_text(
                    f"❌ Fehler bei der Ausführung der Test-Suite:\n{str(e)}"
                )
        finally:
            if user_id in self.running_tests:
                del self.running_tests[user_id]
                self.logger.info(
                    f"{self.module_emoji} [run_all_tests] Lock für User {user_id} entfernt."
                )

    async def _run_test_type(self, test_type: str):
        """Hilfsmethode zum internen Ausführen eines Test-Typs ohne UI-Update"""
        # Diese Methode ist für `run_all_tests` gedacht und führt einen Testlauf durch,
        # speichert die Ergebnisse aber nur im Cache, ohne eine Telegram-Nachricht zu senden.

        type_dirs = {
            "unit": self.unit_tests_dir,
            "integration": self.integration_tests_dir,
            "performance": self.performance_tests_dir,
        }
        test_dir = type_dirs.get(test_type)
        if not test_dir or not test_dir.exists():
            self.logger.warning(
                f"{self.module_emoji} [_run_test_type] Testverzeichnis für '{test_type}' nicht gefunden, überspringe."
            )
            return

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            str(test_dir),
            "-v",
            "--tb=short",
            "--no-header",
            f"--rootdir={self.project_root}",
        ]
        if test_type == "performance":
            cmd.extend(["-m", "performance"])
        if test_type == "integration":
            cmd.append("-x")

        start_time = datetime.now()
        # INV-01: analog zu _execute_test_run() oben - asyncio.to_thread(),
        # damit run_all_tests() (das diese Methode dreimal nacheinander
        # aufruft) den Event-Loop nicht insgesamt bis zu 900s blockiert.
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=self.project_root,
        )
        end_time = datetime.now()

        test_results = self._parse_pytest_output(result.stdout, result.stderr)
        test_results.update(
            {
                "duration": (end_time - start_time).total_seconds(),
                "timestamp": end_time.isoformat(),
                "type": test_type,
                "returncode": result.returncode,
            }
        )
        self.test_results_cache[test_type] = test_results
        self.logger.info(
            f"{self.module_emoji} [_run_test_type] '{test_type}'-Tests abgeschlossen und gecached."
        )
