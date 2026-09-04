# services/library_health/discovery.py
# -*- coding: utf-8 -*-
"""
Library Discovery (Prompt Abschnitt 7 / Phase 1A).

Rekursives, rein lesendes Auffinden aller unterstuetzten Audio-Dateien in
der konfigurierten Music-Library. Erzeugt pro Datei einen FileRecord mit
den Pfad-/Struktur-Fakten — noch KEINE Tag-Analyse.

Konventionsquelle (nicht neu erfunden):
  - Unterstuetzte Formate: config.Config.SUPPORTED_FORMATS
    (Default-Parameter hier spiegelt diesen Wert, damit discovery.py ohne
    config-Import testbar bleibt).
  - Verzeichnis-Schema: utils/filenamefixer.py::build_final_path()
      LIBRARY_DIR/<Artist>/Singles/<Jahr> - <Titel>.<ext>
      LIBRARY_DIR/<Artist>/<Jahr> - <Album>/<NN> - <Titel>.<ext>
      LIBRARY_DIR/Compilations/<Kanal>/<Artist> - <Titel>.<ext>
      LIBRARY_DIR/Playlist/<Name>/<Artist> - <Titel>.<ext>
    (Podcasts liegen ausserhalb LIBRARY_DIR und sind damit nicht Teil
    dieses Scans — Prompt Abschnitt 30.)
  - Single/Album-Erkennung am Pfad: services/duplicate/classification.py
    ::classify_by_path() (dort bereits als Autoritaet etabliert, hier nur
    wiederverwendet).

Read-only: nur Path.rglob / Path.stat / Path.is_file / Path.is_symlink.
Kein open(), kein mutagen, kein subprocess.
"""

from __future__ import annotations

from pathlib import Path

from services.duplicate.classification import classify_by_path

from .models import FileRecord, LibrarySection

# Spiegelt config.Config.SUPPORTED_FORMATS (2026-09). Wird von scanner.py
# explizit mit dem echten Config-Wert ueberschrieben — der Default hier
# haelt discovery.py nur fuer Unit-Tests eigenstaendig.
DEFAULT_SUPPORTED_EXTENSIONS: tuple[str, ...] = (".mp3", ".m4a", ".ogg", ".opus")

_SPECIAL_SECTION_DIRS = {
    "compilations": LibrarySection.COMPILATIONS,
    "playlist": LibrarySection.PLAYLIST,
}


def _classify_section_and_dirs(
    rel_parts: tuple[str, ...],
) -> tuple[LibrarySection, str | None, str | None, bool]:
    """rel_parts = Pfad der Datei relativ zur Library-Wurzel, inkl.
    Dateiname als letztem Element.

    Rueckgabe: (section, artist_directory, album_directory, is_singles)
    """
    # rel_parts[-1] ist der Dateiname; die Verzeichnisse sind rel_parts[:-1]
    dir_parts = rel_parts[:-1]

    if not dir_parts:
        # Datei liegt direkt in LIBRARY_DIR
        return LibrarySection.UNKNOWN, None, None, False

    top = dir_parts[0].strip().lower()
    if top in _SPECIAL_SECTION_DIRS:
        section = _SPECIAL_SECTION_DIRS[top]
        # Compilations/<Kanal>/... bzw. Playlist/<Name>/...
        sub = dir_parts[1] if len(dir_parts) >= 2 else None
        return section, None, sub, False

    # Standard-Musikpfad: erstes Segment = Artist-Verzeichnis
    artist_directory = dir_parts[0]

    if len(dir_parts) == 1:
        # LIBRARY_DIR/<Artist>/<datei> — Datei direkt im Artist-Ordner,
        # ausserhalb der erwarteten Singles-/Album-Unterebene.
        return LibrarySection.MUSIC, artist_directory, None, False

    middle = dir_parts[1]
    is_singles = middle.strip().lower() == "singles"
    album_directory = None if is_singles else middle
    return LibrarySection.MUSIC, artist_directory, album_directory, is_singles


def build_file_record(absolute_path: Path, library_root: Path) -> FileRecord:
    """Baut EINEN FileRecord fuer eine bereits als Audio-Datei erkannte,
    existierende Datei. `library_root` muss ein Vorfahre von
    `absolute_path` sein (Aufrufer stellt das sicher)."""
    rel = absolute_path.relative_to(library_root)
    rel_parts = rel.parts

    try:
        size = absolute_path.stat().st_size
    except OSError:
        size = -1

    section, artist_dir, album_dir, is_singles = _classify_section_and_dirs(rel_parts)

    return FileRecord(
        absolute_path=absolute_path,
        relative_path=str(rel),
        filename=absolute_path.name,
        filename_stem=absolute_path.stem,
        extension=absolute_path.suffix.lower(),
        file_size=size,
        parent_directory=absolute_path.parent.name,
        artist_directory=artist_dir,
        album_directory=album_dir,
        is_singles=is_singles,
        library_section=section,
        path_classification=classify_by_path(absolute_path).value,
    )


def discover_files(
    library_root: Path,
    supported_extensions: tuple[str, ...] = DEFAULT_SUPPORTED_EXTENSIONS,
) -> list[FileRecord]:
    """Rekursiver, deterministisch sortierter Scan. Symlinks (Datei ODER
    Zwischenverzeichnis) werden bewusst NICHT verfolgt — ein Health-Report
    soll den realen, physisch in der Library liegenden Bestand beschreiben,
    keine ueber Symlinks eingehaengten Fremdbaeume (und kein Risiko, den
    Scan aus der Library heraus zu fuehren).

    Nicht-lesbare Verzeichnisse werden uebersprungen (kein Abbruch des
    gesamten Scans — Prompt Abschnitt 34).
    """
    root = Path(library_root)
    exts = {e.lower() for e in supported_extensions}
    records: list[FileRecord] = []

    if not root.is_dir():
        return records

    for path in sorted(root.rglob("*")):
        try:
            if path.is_symlink():
                continue
            if not path.is_file():
                continue
            if path.suffix.lower() not in exts:
                continue
            # Symlink-Zwischenverzeichnis: relative_to schlaegt nicht fehl,
            # aber ein aufgeloester Pfad ausserhalb des Roots wird verworfen.
            if root.resolve() not in path.resolve().parents:
                continue
        except OSError:
            continue
        records.append(build_file_record(path, root))

    return records
