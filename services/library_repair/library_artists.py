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


# ─────────────────────────────────────────────────────────────────────────
# Album-Auswahl (Manual Metadata Editing v2) — identisches Index-Picker-
# Muster wie die Artist-Auswahl oben, eine Ebene tiefer.
# ─────────────────────────────────────────────────────────────────────────


def list_artist_albums(artist: str, *, library_root: Optional[Path] = None) -> List[str]:
    """Sortierte Liste der Album-Verzeichnisnamen direkt unterhalb eines
    Artist-Verzeichnisses — identische Klassifikation wie
    services/library_health/discovery.py::_classify_section_and_dirs()
    (LIBRARY_DIR/<Artist>/<Jahr> - <Album>/...): jedes direkte
    Unterverzeichnis AUSSER "Singles" (case-insensitiv) ist ein
    Album-Kontext. Album-Scope ist damit verzeichnisbasiert, nicht
    ©alb-tag-basiert (Auftrag §7/§22/§23 — zwei Ordner mit demselben
    sichtbaren Albumnamen bleiben unabhängige Kontexte). "Singles" wird
    bewusst ausgeschlossen (Auftrag §24 — keine globale Änderung aller
    Singles eines Artists als "ein Album"). Nur echte Verzeichnisse
    (keine Symlinks, keine versteckten Einträge) — identische Vorsicht
    wie list_library_artist_dirs()."""
    root = Path(library_root) if library_root is not None else Path(Config.LIBRARY_DIR)
    artist_dir = root / artist
    if not artist_dir.is_dir():
        return []
    return sorted(
        p.name
        for p in artist_dir.iterdir()
        if p.is_dir()
        and not p.is_symlink()
        and not p.name.startswith(".")
        and p.name.strip().lower() != "singles"
    )


def resolve_album_by_index(
    artist: str, idx: int, *, library_root: Optional[Path] = None
) -> Optional[str]:
    """Löst einen Button-Index gegen eine frisch ermittelte Album-Liste
    dieses Artists auf — identisches Anti-Injection-Prinzip wie
    resolve_artist_by_index() (kein Rohpfad/Albumname aus
    Telegram-`callback_data`)."""
    albums = list_artist_albums(artist, library_root=library_root)
    if 0 <= idx < len(albums):
        return albums[idx]
    return None
