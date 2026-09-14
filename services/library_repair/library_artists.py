# services/library_repair/library_artists.py
# -*- coding: utf-8 -*-
"""
Library-Artist-Auswahl (ARCH-032 Phase 3C, ARCH-031 B.8).

Listet die Artist-Verzeichnisse der PRODUKTIONS-Library
(Config.LIBRARY_DIR) für die index-basierte Telegram-Auswahl. Spiegelt
das bereits etablierte, gehärtete Muster aus
services/metadata/reprocessing_runner.py::list_available_artist_dirs()
(dort gegen die Test-Sandbox /tmp/musicbot_test/metadaten) — hier gegen
die echte Library, read-only, keine Mutation.

Das Verzeichnis ist ausschließlich der Datei-Scope-Selektor; die
tatsächliche Tag-Änderung ist bei allen Maintenance-Actions
tag-wert-getrieben (services.library_repair.artist/genre), nicht
verzeichnisname-getrieben — siehe ARCH-031 B.8 für die vollständige
Begründung, warum das kein "directory name == artist name"-Risiko ist.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from config import Config


def list_library_artist_dirs(library_root: Optional[Path] = None) -> List[str]:
    """Sortierte Liste der Artist-Verzeichnisnamen direkt unterhalb der
    Library-Wurzel. Nur echte Verzeichnisse (keine Symlinks — dieselbe
    Vorsicht wie beim Health-Scanner/Executor, Discovery folgt keinem
    Symlink), keine versteckten Einträge (Punkt-Präfix). Leere Liste,
    wenn die Library-Wurzel (noch) nicht existiert."""
    root = Path(library_root) if library_root is not None else Path(Config.LIBRARY_DIR)
    if not root.is_dir():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")
    )


def resolve_artist_by_index(idx: int, *, library_root: Optional[Path] = None) -> Optional[str]:
    """Löst einen Button-Index gegen eine frisch geholte Artist-Liste auf
    — KEIN Rohpfad/String aus Telegram-`callback_data` (ARCH-031 B.8,
    identisches Anti-Injection-Muster wie
    reprocessing_menu_handler.py::_resolve_artist_by_index()). Re-globbt
    bewusst bei jedem Aufruf statt eine Liste über mehrere Schritte im
    Speicher zu halten (kein Session-State nötig, Admin-only-Tool ohne
    nennenswerte gleichzeitige Schreibzugriffe auf die Verzeichnisstruktur
    selbst)."""
    artists = list_library_artist_dirs(library_root=library_root)
    if 0 <= idx < len(artists):
        return artists[idx]
    return None
