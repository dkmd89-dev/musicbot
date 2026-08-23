from pathlib import Path
from typing import Union, Tuple, Optional, Any, Callable
import time
import unicodedata
import re

from config import Config
from utils.singleton import SingletonMixin
from services.downloader.utils.errors import FileProcessingError

# Regex-Patterns für die Dateinamenbereinigung
ILLEGAL_CHARS_PATTERN = re.compile(r'[<>:"/\\|?*]')
FEAT_NOTATION_PATTERN = re.compile(r"\s+ft\.?\s+([^,]+)", re.IGNORECASE)
EXTRA_SPACES_PATTERN = re.compile(r"\s+")


class FileUtils(SingletonMixin):
    """Datei-Utilities für die Music Library"""

    def _do_init(
        self,
        library_dir: Union[str, Path] = "/mnt/musik_bilder/library",  # ← KORRIGIERT
        logger_factory: Callable = None,
    ):
        """
        Wird NUR beim ersten FileUtils()-Aufruf ausgeführt.
        """
        self.library_dir = Path(library_dir)
        self.logger = (
            logger_factory("file_utils")
            if logger_factory
            else self._get_default_logger()
        )
        self.logger.info(
            f"📁 FileUtils initialisiert mit Library-Verzeichnis: {self.library_dir}"
        )

    def _get_default_logger(self):
        """Fallback-Logger falls keine Factory übergeben wurde"""
        import logging

        logger = logging.getLogger("file_utils")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    async def verify_file(self, path: Union[str, Path]) -> Tuple[bool, str]:
        """
        Überprüft, ob eine Datei existiert und > 0 Bytes ist.
        Gibt (is_valid, grund) zurück.
        """
        self.logger.debug(f"🔍 Verifiziere Datei: {path}")
        path = Path(path)

        if not path.exists():
            msg = f"❌ Datei existiert nicht: {path}"
            self.logger.warning(msg)
            return False, "Datei existiert nicht"

        size = path.stat().st_size
        self.logger.debug(f"📊 Dateigröße: {size} Bytes")

        if size == 0:
            msg = f"⚠️ Leere Datei gefunden (0 Bytes), wird gelöscht: {path}"
            self.logger.warning(msg)
            try:
                path.unlink(missing_ok=True)
                self.logger.info(f"🗑️ Leere Datei erfolgreich gelöscht: {path}")
            except Exception as e:
                error_msg = f"❌ Fehler beim Löschen der leeren Datei {path}: {e}"
                self.logger.error(error_msg, exc_info=True)
            return False, "Dateigröße 0"

        success_msg = f"✅ Datei erfolgreich validiert (Größe: {size} Bytes): {path}"
        self.logger.info(success_msg)
        return True, "OK"

    async def safe_rename(self, src: Union[str, Path], dest: Union[str, Path]) -> None:
        """Verschiebt Datei sicher und erstellt Zielverzeichnisse."""
        self.logger.info(f"📦 Starte sichere Umbenennung: '{src}' → '{dest}'")

        src_path = Path(src)
        dest_path = Path(dest)

        self.logger.debug(f"🔍 Prüfe Quelldatei: {src_path}")

        if not src_path.exists():
            error_msg = f"❌ Quelldatei existiert nicht: {src}"
            self.logger.error(error_msg)
            raise FileNotFoundError(f"Quelldatei existiert nicht: {src}")

        self.logger.debug(f"📁 Erstelle Zielverzeichnis: {dest_path.parent}")
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if dest_path.exists():
            warning_msg = (
                f"♻️ Zieldatei bereits vorhanden – wird überschrieben: {dest_path}"
            )
            self.logger.warning(warning_msg)
            try:
                dest_path.unlink()
                self.logger.debug(f"🗑️ Vorhandene Zieldatei gelöscht: {dest_path}")
            except Exception as e:
                error_msg = (
                    f"❌ Fehler beim Löschen der vorhandenen Zieldatei {dest_path}: {e}"
                )
                self.logger.error(error_msg, exc_info=True)
                raise

        try:
            self.logger.debug(f"🔄 Führe Umbenennung durch...")
            src_path.rename(dest_path)
            success_msg = f"✅ Datei erfolgreich verschoben: {src_path} → {dest_path}"
            self.logger.info(success_msg)
        except Exception as e:
            error_msg = f"❌ Fehler beim Verschieben der Datei: {e}"
            self.logger.error(error_msg, exc_info=True)
            raise

    async def clean_temp_files(self, directory: Union[str, Path] = None):
        """Löscht alte Dateien im temporären Download-Verzeichnis (> 1 Stunde alt)."""
        directory = Path(directory or Config.DOWNLOAD_DIR)
        self.logger.info(f"🧹 Starte Bereinigung temporärer Dateien in: {directory}")

        now = time.time()
        cleanup_count = 0

        try:
            self.logger.debug(f"🔍 Scanne Verzeichnis nach Dateien...")
            files = list(directory.glob("*"))
            self.logger.debug(f"📋 Gefundene Dateien: {len(files)}")

            for f in files:
                file_age = now - f.stat().st_mtime
                self.logger.debug(f"⏰ Datei: {f.name}, Alter: {file_age:.1f} Sekunden")

                if file_age > 3600:  # älter als 1 Stunde
                    if f.is_file():
                        try:
                            f.unlink()
                            self.logger.info(
                                f"🗑️ Temp-Datei gelöscht ({file_age:.1f}s alt): {f}"
                            )
                            cleanup_count += 1
                        except Exception as e:
                            error_msg = f"⚠️ Konnte Temp-Datei nicht löschen {f}: {e}"
                            self.logger.warning(error_msg)

        except Exception as e:
            error_msg = f"⚠️ Bereinigung fehlgeschlagen für {directory}: {e}"
            self.logger.warning(error_msg, exc_info=True)

        if cleanup_count > 0:
            success_msg = f"✅ {cleanup_count} temporäre Dateien erfolgreich bereinigt."
            self.logger.info(success_msg)
        else:
            self.logger.info("ℹ️ Keine alten temporären Dateien gefunden.")

    def create_dir(
        self, path: Union[str, Path], base_path: Optional[Union[str, Path]] = None
    ) -> Path:
        """
        Erstellt ein Verzeichnis.
        Wenn base_path angegeben ist, wird path daran angehängt.
        """
        if base_path:
            full_path = Path(base_path) / path
        else:
            full_path = Path(path)

        self.logger.info(f"📁 Prüfe/Erstelle Verzeichnis: {full_path}")

        try:
            if not full_path.exists():
                self.logger.debug(
                    f"🆕 Verzeichnis existiert nicht, erstelle: {full_path}"
                )
                full_path.mkdir(parents=True, exist_ok=True)
                success_msg = f"✅ Neues Verzeichnis erfolgreich erstellt: {full_path}"
                self.logger.info(success_msg)
            else:
                self.logger.debug(f"📁 Verzeichnis existiert bereits: {full_path}")
        except Exception as e:
            error_msg = f"❌ Fehler beim Erstellen des Verzeichnisses {full_path}: {e}"
            self.logger.error(error_msg, exc_info=True)
            raise FileProcessingError(
                f"Fehler beim Erstellen des Verzeichnisses {full_path}"
            )

        return full_path

    def sanitize_filename(self, filename: Optional[Any]) -> str:
        """Bereinigt Dateinamen mit Unicode-Normalisierung und Ersetzung unerwünschter Zeichen."""
        self.logger.debug(f"✨ Starte Dateinamen-Bereinigung: '{filename}'")

        try:
            if filename is None:
                self.logger.warning(
                    "⚠️ None als Dateiname erhalten, verwende leeren String"
                )
                return ""

            original_filename = str(filename)
            self.logger.debug(f"📝 Originaler Dateiname: '{original_filename}'")

            # Längenprüfung
            if len(original_filename) > Config.MAX_FILENAME_LENGTH:
                truncated = original_filename[: Config.MAX_FILENAME_LENGTH]
                self.logger.warning(
                    f"📏 Dateiname zu lang ({len(original_filename)} > {Config.MAX_FILENAME_LENGTH}), kürze auf: '{truncated}'"
                )
                filename = truncated
            else:
                filename = original_filename

            # Unicode-Normalisierung
            normalized = unicodedata.normalize("NFC", filename)
            self.logger.debug(f"🔤 Unicode-normalisiert: '{normalized}'")

            # Ungültige Zeichen ersetzen
            without_illegal_chars = ILLEGAL_CHARS_PATTERN.sub(" ", normalized)
            if without_illegal_chars != normalized:
                self.logger.debug(
                    f"🚫 Ungültige Zeichen ersetzt: '{without_illegal_chars}'"
                )

            # "ft." zu "feat." normalisieren
            with_feat_notation = FEAT_NOTATION_PATTERN.sub(
                " feat. \\1", without_illegal_chars
            )
            if with_feat_notation != without_illegal_chars:
                self.logger.debug(
                    f"🎵 'ft.' zu 'feat.' normalisiert: '{with_feat_notation}'"
                )

            # Überflüssige Leerzeichen entfernen
            final_filename = EXTRA_SPACES_PATTERN.sub(" ", with_feat_notation).strip()
            if final_filename != with_feat_notation:
                self.logger.debug(f"🧹 Leerzeichen bereinigt: '{final_filename}'")

            self.logger.info(
                f"✅ Dateiname erfolgreich bereinigt: '{original_filename}' → '{final_filename}'"
            )
            return final_filename

        except Exception as e:
            error_msg = f"❌ Dateinamen-Bereinigung fehlgeschlagen: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return "ungueltiger_dateiname"
