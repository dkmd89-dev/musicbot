# services/library_health/scanner.py
# -*- coding: utf-8 -*-
"""
Scanner-Orchestrierung (Prompt Abschnitt 1 Pipeline / Phase 1).

    DISCOVERY -> (pro Datei) TAG/AUDIO/ARTWORK READ -> FILE ANALYSIS
              -> REPORT

Group-Analyse (Album/Artist/Duplicate) und Health-Scoring folgen in
spaeteren PRs dieses Zweigs (report.PENDING_ANALYSES).

Read-only: dieses Modul ruft ausschliesslich discovery/tag_reader/
file_analysis/report auf. Der einzige Zusatz-Import mit potenziellem
Zustand ist utils.genre_map.GenreMapper — nur dessen reine Lese-Methode
validate_genre() wird verwendet, kein auto_learn. Als eigenstaendiger
CLI-Subprozess ist das SingletonMixin-Verhalten unkritisch (First Mover,
frischer Prozess) — identisch zur etablierten Begruendung in
scripts/reprocess_artist_metadata.py Abschnitt 2a.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .discovery import DEFAULT_SUPPORTED_EXTENSIONS, discover_files
from .file_analysis import analyze_file
from .models import AnalysisState, FileHealth
from .report import build_report_dict
from .tag_reader import ArtworkData, StreamData, TagData, probe_stream, read_artwork, read_tags


def _build_genre_validator(
    genre_mapping_dir: Optional[str | Path], logger
) -> Optional[Callable[[str], bool]]:
    if genre_mapping_dir is None:
        return None
    try:
        from utils.genre_map import GenreMapper

        mapper = GenreMapper(str(genre_mapping_dir))
    except Exception as e:  # noqa: BLE001
        if logger:
            logger.warning(f"GenreMapper nicht verfuegbar, GENRE_INVALID uebersprungen: {e}")
        return None

    def _validate(name: str) -> bool:
        try:
            return bool(mapper.validate_genre(name))
        except Exception:  # noqa: BLE001
            return True  # im Zweifel nicht als ungueltig melden

    return _validate


def _read_all(path: Path) -> tuple[TagData, StreamData, ArtworkData]:
    """Alle drei read-only Lesevorgaenge fuer eine Datei — jeder faengt
    seine eigenen Fehler ab und liefert einen NOT_ANALYZABLE-Container,
    nie eine Exception (Prompt Abschnitt 34)."""
    try:
        tags = read_tags(path)
    except Exception as e:  # noqa: BLE001
        tags = TagData(state=AnalysisState.NOT_ANALYZABLE, error=repr(e))
    try:
        stream = probe_stream(path)
    except Exception as e:  # noqa: BLE001
        stream = StreamData(state=AnalysisState.NOT_ANALYZABLE, error=repr(e))
    try:
        artwork = read_artwork(path)
    except Exception as e:  # noqa: BLE001
        artwork = ArtworkData(state=AnalysisState.NOT_ANALYZABLE, error=repr(e))
    return tags, stream, artwork


def run_scan(
    library_root: str | Path,
    *,
    supported_extensions: tuple[str, ...] = DEFAULT_SUPPORTED_EXTENSIONS,
    expected_extension: Optional[str] = None,
    genre_mapping_dir: Optional[str | Path] = None,
    logger=None,
    verbose: bool = False,
) -> dict:
    root = Path(library_root)
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()

    if logger:
        logger.info(f"SCAN START: {root}")

    records = discover_files(root, supported_extensions)
    if logger:
        logger.info(f"FILE DISCOVERY: {len(records)} Audio-Dateien")

    genre_validator = _build_genre_validator(genre_mapping_dir, logger)

    file_healths: list[FileHealth] = []
    for idx, record in enumerate(records, start=1):
        tags, stream, artwork = _read_all(record.absolute_path)
        fh = analyze_file(
            record, tags, stream, artwork,
            genre_validator=genre_validator,
            expected_extension=expected_extension,
        )
        file_healths.append(fh)
        if verbose and logger:
            worst = max((i.severity.value for i in fh.issues), default="OK")
            logger.debug(f"FILE ANALYZED [{idx}/{len(records)}] {record.relative_path} → {worst}")
        elif logger and idx % 500 == 0:
            logger.info(f"… {idx}/{len(records)} analysiert")

    completed = datetime.now(timezone.utc)
    report = build_report_dict(
        library_root=str(root),
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        duration_seconds=time.monotonic() - t0,
        file_healths=file_healths,
    )

    if logger:
        s = report["statistics"]
        logger.info(
            f"SCAN COMPLETE: {s['total_files']} Dateien, "
            f"{s['files_with_errors']} mit Fehlern, "
            f"{s['files_with_warnings']} mit Warnungen, "
            f"{len(report['issues'])} Issues gesamt"
        )
    return report
