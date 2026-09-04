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

import hashlib
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .discovery import DEFAULT_SUPPORTED_EXTENSIONS, discover_files
from .file_analysis import analyze_file
from .group_analysis import analyze_groups
from .models import AnalysisState, FileHealth
from .report import build_report_dict
from .scoring import build_health_section
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


def _build_title_cleaner(logger) -> Optional[Callable[[str, str], str]]:
    """Reine, read-only Titel-Bereinigung fuer den META_TITLE_NOT_CLEAN-Check.
    `utils.title_cleanup.light_title_cleanup` ist zustandslos (nur Regex,
    kein I/O, kein Logger, keine Config) und exakt der Pfad, den die reale
    Download-Pipeline fuer den finalen Titel-Tag verwendet
    (enhanced_metadata_processor.py Schritt 7 → TitleCleaner.light_title_cleanup
    → dieselbe Funktion). Bewusst NICHT ueber services.metadata importiert —
    dessen __init__ zieht TagWriter/EnhancedMetadataProcessor eager mit."""
    try:
        from utils.title_cleanup import light_title_cleanup
    except Exception as e:  # noqa: BLE001
        if logger:
            logger.warning(f"title_cleanup nicht verfuegbar, META_TITLE_NOT_CLEAN uebersprungen: {e}")
        return None

    return light_title_cleanup


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _hash_size_collisions(file_healths: list[FileHealth]) -> dict[str, str]:
    """SHA-256 nur fuer Dateien mit identischer Groesse berechnen (Prompt
    Abschnitt 27: Hashes nur, wenn fuer Duplicate Detection tatsaechlich
    benoetigt). Byte-identische Dateien haben zwingend dieselbe Groesse —
    der Groessen-Vorfilter ist vollstaendig und billig."""
    by_size: dict[int, list[FileHealth]] = defaultdict(list)
    for fh in file_healths:
        if fh.record.file_size >= 0:
            by_size[fh.record.file_size].append(fh)
    hashes: dict[str, str] = {}
    for size, members in by_size.items():
        if len(members) < 2:
            continue
        for fh in members:
            digest = _sha256_file(fh.record.absolute_path)
            if digest:
                hashes[fh.record.relative_path] = digest
    return hashes


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
    title_cleaner = _build_title_cleaner(logger)

    file_healths: list[FileHealth] = []
    for idx, record in enumerate(records, start=1):
        tags, stream, artwork = _read_all(record.absolute_path)
        fh = analyze_file(
            record, tags, stream, artwork,
            genre_validator=genre_validator,
            title_cleaner=title_cleaner,
            expected_extension=expected_extension,
        )
        file_healths.append(fh)
        if verbose and logger:
            worst = max((i.severity.value for i in fh.issues), default="OK")
            logger.debug(f"FILE ANALYZED [{idx}/{len(records)}] {record.relative_path} → {worst}")
        elif logger and idx % 500 == 0:
            logger.info(f"… {idx}/{len(records)} analysiert")

    if logger:
        logger.info("GROUP ANALYSIS: Album-/Artist-Konsistenz + Duplicate-Gruppen")
    file_hashes = _hash_size_collisions(file_healths)
    group_issues = analyze_groups(file_healths, file_sha256=file_hashes)
    health_section = build_health_section(file_healths, group_issues)

    completed = datetime.now(timezone.utc)
    report = build_report_dict(
        library_root=str(root),
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        duration_seconds=time.monotonic() - t0,
        file_healths=file_healths,
        group_issues=group_issues,
        health_section=health_section,
    )

    if logger:
        s = report["statistics"]
        logger.info(
            f"SCAN COMPLETE: Health {report['health']['score']} "
            f"({report['health']['status']}) — {s['total_files']} Dateien, "
            f"{s['files_with_errors']} mit Fehlern, "
            f"{s['files_with_warnings']} mit Warnungen, "
            f"{len(report['issues'])} Issues gesamt"
        )
    return report
