#!/usr/bin/env python3
# scripts/resolve_duplicates.py
# -*- coding: utf-8 -*-
"""
Duplicate Resolution — Dry-Run/Execute-CLI für die isolierte Testbibliothek.

Basis: docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md, Abschnitt 18,
Schritt 5. Nutzt AUSSCHLIESSLICH die reine Domain-Logik aus
services/duplicate/classification.py, services/duplicate/resolution.py und
(ab Phase 3) services/duplicate/execution.py (keine eigene Klassifikations-/
Entscheidungslogik in diesem Script - siehe Architecture Audit Abschnitt
12/Auftrag "Das Script darf ausschließlich die zentrale Duplicate-Domain
aufrufen").

Ohne `--execute` VOLLSTÄNDIG READ-ONLY, unverändert seit Phase 1 (Auftrag
Phase 3 Abschnitt 2): kein unlink()/remove()/rename()/move()/replace()
irgendwo im Dry-Run-Pfad, keine Metadatenänderung, kein Cover-Schreiben,
kein Cache-Schreiben (der einzige Schreibzugriff im Dry-Run ist der
JSON-Report unter /tmp/musicbot_test, siehe REPORT_JSON_PATH).
--apply/--delete existieren weiterhin bewusst NICHT - werden mit derselben
klaren Fehlermeldung und Exit-Code != 0 abgelehnt wie zuvor `--execute`.

## Phase 3 (Execute)

`--execute` ist jetzt real (Auftrag Phase 3 Abschnitt 3): NUR mit diesem
expliziten Flag werden REMOVE-Kandidaten tatsächlich gelöscht - kein
implizites/automatisches Löschen nach einem "erfolgreichen" Dry-Run, kein
Environment-Variable-Ersatz. Zweistufiges Sicherheitsmodell (Manifest +
Pre-Delete-Revalidierung inkl. TOCTOU-Schutz) vollständig in
services/duplicate/execution.py implementiert (siehe dortiger
Modul-Docstring) - dieses Script liefert nur die I/O-Wiring-Funktionen
(`build_single_candidate()`, `validate_file_within_root()`), keine eigene
Sicherheits- oder Entscheidungslogik. MANUAL_REVIEW/AMBIGUOUS/UNKNOWN
werden strukturell NIE Teil des Execution Plan (siehe
execution.py::build_execution_plan()) - `--execute` kann sie daher nicht
löschen, unabhängig von allen anderen Prüfungen.

Sicherheitsmodell: identisches ALLOWED_ROOT/FORBIDDEN_ROOTS-Muster wie
scripts/reprocess_artist_metadata.py und
scripts/normalize_test_library_loudness.py (Denylist zuerst geprüft,
Symlink-Auflösung, Containment-Check). ALLOWED_ROOT ist laut Auftrag
Abschnitt 3 ausschließlich /tmp/musicbot_test/library - NICHT
/tmp/musicbot_test/metadaten (das ist der Sandbox-Root von
reprocess_artist_metadata.py, ein anderes Tool).

Der bestehende DuplicateDetector/DuplicateCache (services/duplicate/
detector.py, cache.py) wird an KEINER Stelle importiert oder aufgerufen -
diese Domäne ist PRE-DOWNLOAD Prevention, dieses Tool ist POST-DOWNLOAD/
LIBRARY Resolution (siehe Architecture Audit Abschnitt 10).

Unterstützte Formate: .m4a/.mp4 (vollständig, über die produktiv
etablierten MP4-Tag-Namen aus services/metadata/tag_writer.py) und .mp3
(best-effort über dieselben ID3-Tag-Namen, die tag_writer.py für MP3
schreibt - MusicBrainz-IDs/ISRC werden für MP3 von tag_writer.py
nachweislich nie geschrieben, fehlen daher dort strukturell, keine
fehlerhafte Leseannahme).

## Phase 2 (Safety Gate)

Zusätzlich zu Bitrate wird pro Datei die tatsächliche Audio-Duration
(ffprobe format=duration, NICHT aus Dateiname/Tag) sowie - rein
informativ, siehe classification.py-Docstring - ein SHA-256 des
eingebetteten Covers gelesen. Beides bleibt vollständig read-only
(ffprobe/mutagen-Lesezugriff), keine neue Schreiboperation, kein neues
CLI-Flag. Die eigentliche Safety-Gate-Entscheidung liegt ausschließlich
in services/duplicate/resolution.py (dieses Script liefert nur Rohdaten,
siehe Architecture Audit Abschnitt 12).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.duplicate.classification import (  # noqa: E402
    Candidate,
    METADATA_COMPLETENESS_FIELDS,
    build_candidate,
    group_candidates_by_identity,
)
from services.duplicate.resolution import GroupAction, resolve_group  # noqa: E402
from services.duplicate.execution import (  # noqa: E402
    FileDeleteStatus,
    build_execution_plan,
    execute_group,
)

# ─────────────────────────────────────────────────────────────────────────
# Sicherheitsmodell (identisches Muster wie die beiden bestehenden Tools)
# ─────────────────────────────────────────────────────────────────────────

ALLOWED_ROOT = Path("/tmp/musicbot_test/library")

# Read-Only-Produktions-Roots (Auftrag "Freigabe Schritt 3" - Production
# Read-Only Dry-Run Enablement): AUSSCHLIESSLICH Dry-Run-Scan erlaubt.
# --execute gegen einen dieser Pfade wird in validate_scan_root()
# unbedingt und vor jeder anderen Prüfung abgelehnt (siehe dort) - es
# gibt keinen Codepfad, der Mutation gegen einen ALLOWED_READONLY_ROOTS-
# Eintrag zulässt. config.py::Config.LIBRARY_DIR zeigt seit dem
# 2026-09-01-Commit "Konfiguration: library/ Verzeichnis in config.py
# angepasst" auf /mnt/musik_bilder/library (vormals /mnt/4tb/library).
ALLOWED_READONLY_ROOTS = [
    Path("/mnt/musik_bilder/library"),
]

FORBIDDEN_ROOTS = [
    Path("/mnt/4tb/library"),
    Path("/mnt/128ssd"),
    Path("/mnt/musik_bilder"),
    Path("/mnt/media"),
]

SUPPORTED_EXTENSIONS = {".m4a", ".mp4", ".mp3"}
REPORT_JSON_PATH = Path("/tmp/musicbot_test/duplicate_resolution_report.json")
EXECUTION_PLAN_JSON_PATH = Path("/tmp/musicbot_test/duplicate_execution_plan.json")
EXECUTION_REPORT_JSON_PATH = Path("/tmp/musicbot_test/duplicate_execution_report.json")
AUDIT_LOG_JSONL_PATH = Path("/tmp/musicbot_test/duplicate_execution_audit_log.jsonl")


class PathSafetyError(Exception):
    pass


def validate_scan_root(
    path: Path, allow_execute: bool = True, production_execute_confirmed: bool = False
) -> Path:
    """Denylist zuerst (Defense-in-Depth), dann Containment-Check.

    `allow_execute` MUSS von main() exakt auf `args.execute` gesetzt
    werden. Liegt der Pfad in ALLOWED_READONLY_ROOTS UND allow_execute
    ist True, gilt zusätzliche, mehrstufige Reibung ("Freigabe Schritt
    3" - gezielter Execute-Pilot, explizit nach Manual Review):

      1. Ohne `production_execute_confirmed=True` (CLI: separates,
         eigenes Flag `--confirm-production-execute`, NICHT durch
         `--execute` allein auslösbar) wird UNBEDINGT und vor jeder
         anderen Prüfung abgelehnt - kein implizites Production-Execute,
         exakt wie das bestehende Prinzip "kein implizites --execute"
         auf die nächste Sicherheitsstufe angewendet.
      2. Selbst mit Bestätigung wird der READONLY-ROOT SELBST (unskaliert,
         z. B. bare `/mnt/musik_bilder/library`) für Execute abgelehnt -
         nur ein NAMENTLICH eingegrenztes Unterverzeichnis (z. B. per
         `--artist`/`--path .../EinArtist`) ist zulässig. Verhindert
         einen versehentlichen Full-Library-Execute gegen Produktion in
         einem einzigen Aufruf (Gruppenweise-statt-Batch-Prinzip auf
         Scan-Root-Ebene).

    ALLOWED_ROOT (Testbibliothek) behält vollen, uneingeschränkten
    Zugriff (Dry-Run + Execute) wie bisher.
    """
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as e:
        raise PathSafetyError(f"Pfad existiert nicht: {path}") from e

    allowed_resolved = ALLOWED_ROOT.resolve()
    if resolved == allowed_resolved or resolved.is_relative_to(allowed_resolved):
        return resolved  # Testbibliothek: unverändertes Verhalten

    for readonly_root in ALLOWED_READONLY_ROOTS:
        try:
            readonly_resolved = readonly_root.resolve(strict=True)
        except OSError:
            continue
        if resolved == readonly_resolved or resolved.is_relative_to(readonly_resolved):
            if allow_execute:
                if not production_execute_confirmed:
                    raise PathSafetyError(
                        f"--execute gegen Read-Only-Produktions-Root ({readonly_root}) "
                        f"erfordert zusätzlich --confirm-production-execute: {resolved}"
                    )
                if resolved == readonly_resolved:
                    raise PathSafetyError(
                        f"--execute gegen den GESAMTEN Produktions-Root ({readonly_root}) "
                        f"ist auch mit --confirm-production-execute nicht erlaubt - "
                        f"auf ein konkretes Unterverzeichnis eingrenzen (z. B. --artist): {resolved}"
                    )
            return resolved

    for forbidden in FORBIDDEN_ROOTS:
        try:
            forbidden_resolved = forbidden.resolve()
        except OSError:
            continue
        if resolved == forbidden_resolved or resolved.is_relative_to(forbidden_resolved):
            raise PathSafetyError(
                f"Pfad zeigt auf einen verbotenen Bereich ({forbidden}): {resolved}"
            )

    raise PathSafetyError(
        f"Pfad liegt außerhalb des erlaubten Roots ({ALLOWED_ROOT}) und "
        f"außerhalb der erlaubten Read-Only-Roots ({ALLOWED_READONLY_ROOTS}): {resolved}"
    )


def permitted_root_for(resolved_scan_root: Path) -> Path:
    """Reiner Lookup (keine Sicherheitsentscheidung - die trifft
    ausschließlich validate_scan_root()) - bestimmt, welcher der
    erlaubten Roots einen BEREITS erfolgreich validierten scan_root
    enthält. Wird von main() genutzt, um build_candidates() den
    korrekten `permitted_root` für die Per-Datei-Prüfung zu übergeben."""
    allowed_resolved = ALLOWED_ROOT.resolve()
    if resolved_scan_root == allowed_resolved or resolved_scan_root.is_relative_to(allowed_resolved):
        return allowed_resolved
    for readonly_root in ALLOWED_READONLY_ROOTS:
        try:
            readonly_resolved = readonly_root.resolve(strict=True)
        except OSError:
            continue
        if resolved_scan_root == readonly_resolved or resolved_scan_root.is_relative_to(readonly_resolved):
            return readonly_resolved
    # Sollte durch validate_scan_root() bereits ausgeschlossen sein -
    # konservativer Fallback statt eines stillen Fehlverhaltens.
    return allowed_resolved


def validate_file_within_root(file_path: Path, root: Path) -> bool:
    """Per-Datei-Symlink-Schutz - gibt False zurück statt zu werfen, damit
    eine einzelne verdächtige Datei übersprungen werden kann, ohne den
    gesamten Lauf abzubrechen.

    Reihenfolge bewusst geändert (Read-Only-Produktions-Root-Nachtrag):
    Root-Zugehörigkeit wird ZUERST geprüft und ist bei Erfolg autoritativ
    - `root` wurde vom Aufrufer bereits über validate_scan_root()/
    permitted_root_for() als sicher bestätigt (ALLOWED_ROOT ODER ein
    ALLOWED_READONLY_ROOTS-Eintrag). FORBIDDEN_ROOTS greift nur noch als
    Verteidigung für Pfade AUSSERHALB von `root` (z. B. Symlink-
    Eskalation). Die ursprüngliche Reihenfolge (Denylist zuerst) hätte
    hier fälschlich JEDE Datei abgelehnt, da /mnt/musik_bilder/library
    (ALLOWED_READONLY_ROOTS) als Unterpfad des weiterhin verbotenen
    /mnt/musik_bilder (FORBIDDEN_ROOTS) liegt - beide Roots überlappen
    hier bewusst, im Gegensatz zur ursprünglichen, überlappungsfreien
    ALLOWED_ROOT-/FORBIDDEN_ROOTS-Konstellation."""
    try:
        resolved = file_path.resolve(strict=True)
    except OSError:
        return False
    if resolved.is_relative_to(root):
        return True
    for forbidden in FORBIDDEN_ROOTS:
        try:
            forbidden_resolved = forbidden.resolve()
        except OSError:
            continue
        if resolved.is_relative_to(forbidden_resolved):
            return False
    return False


# ─────────────────────────────────────────────────────────────────────────
# Tag-Lesen (I/O-Schicht - hier, NICHT in classification.py/resolution.py)
# ─────────────────────────────────────────────────────────────────────────


def _freeform_str(values) -> Optional[str]:
    if not values:
        return None
    v = values[0]
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


def read_tags(path: Path) -> dict:
    """
    Liest die für METADATA_COMPLETENESS_FIELDS relevanten Tags plus
    artist/title für die Identitätsbildung. Gibt bei Lesefehlern ein
    Mapping mit ausschließlich fehlenden (None/leeren) Werten zurück -
    wirft nicht, damit eine einzelne kaputte Datei den gesamten Scan
    nicht abbricht (Auftrag: robuste Behandlung, keine Vermutung).
    """
    ext = path.suffix.lower()
    result = {
        "artist": None,
        "title": None,
        "album": None,
        "album_artist": None,
        "year": None,
        "genre": None,
        "track_number": None,
        "mb_recording_id": None,
        "mb_artist_id": None,
        "mb_release_id": None,
        "isrc": None,
        "lyrics_present": False,
        "cover_present": False,
        "cover_sha256": None,
    }
    try:
        if ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4

            audio = MP4(path)
            tags = audio.tags or {}
            result["artist"] = _freeform_str(tags.get("©ART"))
            result["title"] = _freeform_str(tags.get("©nam"))
            result["album"] = _freeform_str(tags.get("©alb"))
            result["album_artist"] = _freeform_str(tags.get("aART"))
            result["year"] = _freeform_str(tags.get("©day"))
            result["genre"] = _freeform_str(tags.get("©gen"))
            trkn = tags.get("trkn")
            result["track_number"] = trkn[0][0] if trkn else None
            result["mb_recording_id"] = _freeform_str(
                tags.get("----:com.apple.iTunes:MusicBrainz Recording Id")
            )
            result["mb_artist_id"] = _freeform_str(
                tags.get("----:com.apple.iTunes:MusicBrainz Artist Id")
            )
            result["mb_release_id"] = _freeform_str(
                tags.get("----:com.apple.iTunes:MusicBrainz Release Id")
            )
            result["isrc"] = _freeform_str(tags.get("----:com.apple.iTunes:ISRC"))
            result["lyrics_present"] = bool(tags.get("©lyr"))
            covr = tags.get("covr")
            result["cover_present"] = bool(covr)
            if covr:
                try:
                    result["cover_sha256"] = hashlib.sha256(bytes(covr[0])).hexdigest()
                except Exception:
                    pass
        elif ext == ".mp3":
            from mutagen.id3 import ID3

            tags = ID3(path)
            result["artist"] = str(tags["TPE1"].text[0]) if "TPE1" in tags else None
            result["title"] = str(tags["TIT2"].text[0]) if "TIT2" in tags else None
            result["album"] = str(tags["TALB"].text[0]) if "TALB" in tags else None
            result["album_artist"] = str(tags["TPE2"].text[0]) if "TPE2" in tags else None
            result["year"] = str(tags["TDRC"].text[0]) if "TDRC" in tags else None
            result["genre"] = str(tags["TCON"].text[0]) if "TCON" in tags else None
            if "TRCK" in tags:
                raw = str(tags["TRCK"].text[0]).split("/")[0]
                result["track_number"] = int(raw) if raw.isdigit() else None
            result["lyrics_present"] = any(k.startswith("USLT") for k in tags.keys())
            apic_key = next((k for k in tags.keys() if k.startswith("APIC")), None)
            result["cover_present"] = apic_key is not None
            if apic_key:
                try:
                    result["cover_sha256"] = hashlib.sha256(tags[apic_key].data).hexdigest()
                except Exception:
                    pass
            # tag_writer.py schreibt für MP3 keine MusicBrainz-IDs/ISRC -
            # bleiben strukturell None, keine falsche Leseannahme.
    except Exception:
        pass  # bereits mit den Default-None/False-Werten initialisiert
    return result


def measure_audio_stream(path: Path) -> dict:
    """ffprobe-Bitrate + tatsächliche Audio-Duration (Auftrag Phase 2
    Abschnitt 3: Duration muss aus der Audiodatei stammen, nicht aus
    Dateiname/Tag) - EIN Aufruf für beide Werte (stream=bit_rate +
    format=duration), analog scripts/normalize_test_library_loudness.py
    ::ffprobe_stream_info(). None bei jedem Fehler für beide Werte - der
    Tie-Breaker/das Safety Gate überspringen die jeweilige Stufe dann
    korrekt, bevorzugen/blockieren niemals künstlich."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=bit_rate:format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True, timeout=15,
        )
        if result.returncode != 0:
            return {"bitrate": None, "duration_seconds": None}
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        streams = data.get("streams") or []
        bit_rate = streams[0].get("bit_rate") if streams else None
        duration = (data.get("format") or {}).get("duration")
        return {
            "bitrate": int(bit_rate) if bit_rate is not None else None,
            "duration_seconds": float(duration) if duration is not None else None,
        }
    except Exception:
        return {"bitrate": None, "duration_seconds": None}


# ─────────────────────────────────────────────────────────────────────────
# Read-Only-Garantie (Auftrag Abschnitt 21)
# ─────────────────────────────────────────────────────────────────────────


def snapshot_tree(root: Path) -> dict:
    """(Pfad -> (Größe, mtime))-Snapshot aller unterstützten Dateien -
    Vergleichsbasis für die technische Read-Only-Prüfung."""
    snap = {}
    for file_path in sorted(root.rglob("*")):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            try:
                stat = file_path.stat()
                snap[str(file_path)] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue
    return snap


# ─────────────────────────────────────────────────────────────────────────
# Kandidaten-Aufbau
# ─────────────────────────────────────────────────────────────────────────


def build_candidates(root: Path, log, permitted_root: Path = ALLOWED_ROOT) -> list[Candidate]:
    """`permitted_root` ist der von validate_scan_root() tatsächlich
    validierte Root (ALLOWED_ROOT ODER ein ALLOWED_READONLY_ROOTS-
    Eintrag) - der Default (ALLOWED_ROOT) erhält das bisherige Verhalten
    für alle bestehenden Aufrufer/Tests unverändert."""
    candidates: list[Candidate] = []
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if not validate_file_within_root(file_path, permitted_root):
            log(f"⚠️  SAFETY: übersprungen (außerhalb erlaubtem Root/Symlink): {file_path}")
            continue
        fields = read_tags(file_path)
        stream_info = measure_audio_stream(file_path)
        candidate = build_candidate(
            path=file_path,
            artist=fields.get("artist"),
            title=fields.get("title"),
            fields=fields,
            artist_normalizer=None,  # Phase 1: kein ArtistNormalizer-Import,
            # siehe classification.py-Docstring - Fallback-Normalisierung
            # (Suffix-Strip) genügt für die Identitätsbildung in dieser
            # Phase; identisch zu DuplicateDetector's eigenem Verhalten,
            # wenn kein artist_config konfiguriert ist.
            bitrate=stream_info["bitrate"],
            duration_seconds=stream_info["duration_seconds"],
            cover_sha256=fields.get("cover_sha256"),
        )
        candidates.append(candidate)
    return candidates


def build_single_candidate(path: Path) -> Candidate:
    """Baut einen frischen Candidate für GENAU eine bereits bekannte
    Datei - identische Tag-/ffprobe-Lesepipeline wie build_candidates(),
    aber ohne Verzeichnis-Scan. Wird von
    services/duplicate/execution.py::revalidate_group() injiziert
    (Auftrag Phase 3 Abschnitt 6/7 - semantische Neuentscheidung
    unmittelbar vor dem Delete, auf Basis der AKTUELLEN Datei, nicht des
    alten, im Speicher gehaltenen Candidate-Objekts)."""
    fields = read_tags(path)
    stream_info = measure_audio_stream(path)
    return build_candidate(
        path=path,
        artist=fields.get("artist"),
        title=fields.get("title"),
        fields=fields,
        artist_normalizer=None,
        bitrate=stream_info["bitrate"],
        duration_seconds=stream_info["duration_seconds"],
        cover_sha256=fields.get("cover_sha256"),
    )


def _make_file_validator(permitted_root: Path):
    """Erzeugt einen 1-Parameter-Adapter auf validate_file_within_root()
    für die Dependency Injection in services/duplicate/execution.py
    (dessen Callable-Signatur nimmt nur den Pfad). `permitted_root` MUSS
    der von validate_scan_root()/permitted_root_for() für DIESEN Lauf
    tatsächlich bestätigte Root sein (ALLOWED_ROOT bei der Testbibliothek,
    ODER ein ALLOWED_READONLY_ROOTS-Eintrag beim bestätigten Production-
    Execute-Piloten) - niemals fest auf ALLOWED_ROOT verdrahtet, sonst
    würde jede Datei eines Production-Execute-Laufs fälschlich als
    "außerhalb erlaubtem Root" abgelehnt."""
    def _validator(path: Path) -> bool:
        return validate_file_within_root(path, permitted_root)
    return _validator


# ─────────────────────────────────────────────────────────────────────────
# Ausgabe (Auftrag Abschnitt 19)
# ─────────────────────────────────────────────────────────────────────────


def log(text: str = "") -> None:
    print(text, flush=True)


def print_decision(decision) -> None:
    log()
    log("─" * 40)
    log()
    log("DUPLICATE FOUND")
    log()
    log("Artist:")
    log(f"  {decision.normalized_artist}")
    log()
    log("Title:")
    log(f"  {decision.normalized_title}")
    log()
    for idx, candidate in enumerate(decision.candidates):
        label = chr(ord("A") + idx) if idx < 26 else str(idx)
        log(f"Candidate {label}:")
        log(f"  path: {candidate.path}")
        log(f"  classification: {candidate.classification.value}")
        from services.duplicate.classification import candidate_confidence

        log(f"  confidence: {candidate_confidence(candidate).value}")
        log()

    for ev in decision.evidence:
        log("EVIDENCE:")
        log(f"  vs. candidate: {ev.candidate.path}")
        log(f"  artist_title_match: {'YES' if ev.artist_title_match else 'NO'}")
        log(
            "  duration_consistent: "
            + (
                "UNKNOWN"
                if ev.duration_consistent is None
                else ("YES" if ev.duration_consistent else "NO")
            )
        )
        if ev.duration_delta_seconds is not None:
            log(f"  duration_delta: {ev.duration_delta_seconds:.6f}s")
        log(
            "  musicbrainz_match: "
            + (
                "UNKNOWN"
                if ev.musicbrainz_match is None
                else ("YES" if ev.musicbrainz_match else "NO")
            )
        )
        log(
            "  isrc_match: "
            + ("UNKNOWN" if ev.isrc_match is None else ("YES" if ev.isrc_match else "NO"))
        )
        log(f"  album_context_risk: {'HIGH' if ev.album_context_risk else 'LOW'}")
        log()
        log("SAFETY GATE:")
        log(f"  {'BLOCKED' if ev.blocked else 'PASSED'}")
        log()

    if decision.action == GroupAction.RESOLVED:
        log("KEEP:")
        log(f"  {decision.keep.path}")
        log()
        log("REMOVE PROPOSAL:")
        for candidate in decision.remove_proposals:
            log(f"  {candidate.path}")
        log()
        log("Reason:")
        log(f"  {decision.reason}")
        log()
        log("ACTION:")
        log("  DRY_RUN_ONLY")
    else:
        log("Reason:")
        log(f"  {decision.reason}")
        log()
        log("ACTION:")
        log(f"  {decision.action.value}")
        log()
        log("NO FILE WILL BE REMOVED")


def decision_to_dict(decision) -> dict:
    from services.duplicate.classification import candidate_confidence

    def candidate_dict(c: Candidate) -> dict:
        return {
            "path": str(c.path),
            "artist": c.artist,
            "title": c.title,
            "normalized_artist": c.normalized_artist,
            "normalized_title": c.normalized_title,
            "classification": c.classification.value,
            "confidence": candidate_confidence(c).value,
            "metadata_completeness": c.metadata_completeness,
            "bitrate": c.bitrate,
            "collision_suffix": c.collision_suffix,
        }

    def evidence_dict(ev) -> dict:
        return {
            "candidate": str(ev.candidate.path),
            "artist_title_match": ev.artist_title_match,
            "duration_consistent": ev.duration_consistent,
            "duration_delta_seconds": ev.duration_delta_seconds,
            "musicbrainz_match": ev.musicbrainz_match,
            "isrc_match": ev.isrc_match,
            "album_context_risk": ev.album_context_risk,
            "strong_identity_confirmed": ev.strong_identity_confirmed,
            "safety_gate": "BLOCKED" if ev.blocked else "PASSED",
            "block_reasons": ev.block_reasons,
        }

    return {
        "artist": decision.normalized_artist,
        "title": decision.normalized_title,
        "candidates": [candidate_dict(c) for c in decision.candidates],
        "keep": str(decision.keep.path) if decision.keep else None,
        "remove_proposal": [str(c.path) for c in decision.remove_proposals],
        "action": decision.action.value,
        "reason": decision.reason,
        "evidence": [evidence_dict(ev) for ev in decision.evidence],
    }


def _write_json_atomic(path: Path, data: dict) -> None:
    """Identisches Muster wie services/duplicate/cache.py::
    _write_json_atomic() - tmp-Datei im selben Verzeichnis, dann
    atomarer Path.replace()."""
    tmp_path = path.with_suffix(f".tmp_{int(time.time() * 1000)}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# ─────────────────────────────────────────────────────────────────────────
# Execute-Serialisierung (Auftrag Phase 3 Abschnitt 5/15/16) - reine
# Dict-/JSON-Konvertierung, keine Entscheidungslogik (die liegt vollständig
# in services/duplicate/execution.py).
# ─────────────────────────────────────────────────────────────────────────


def _fingerprint_dict(fp) -> dict:
    return {"path": str(fp.path), "size": fp.size, "sha256": fp.sha256}


def plan_entry_to_dict(entry) -> dict:
    return {
        "artist": entry.normalized_artist,
        "title": entry.normalized_title,
        "keep": _fingerprint_dict(entry.keep),
        "remove": [_fingerprint_dict(fp) for fp in entry.remove],
        "reason": entry.reason,
        "confidence": entry.confidence,
        "duration_seconds": entry.duration_seconds,
        "mb_recording_id": entry.mb_recording_id,
        "isrc": entry.isrc,
        "safety_gate": entry.safety_gate,
    }


def group_result_to_dict(result) -> dict:
    return {
        "artist": result.entry.normalized_artist,
        "title": result.entry.normalized_title,
        "keep": str(result.entry.keep.path),
        "group_ok": result.group_ok,
        "skip_stage": result.skip_stage,
        "skip_reason": result.skip_reason,
        "keep_intact": result.keep_intact,
        "files": [
            {"path": str(r.path), "status": r.status.value, "error": r.error}
            for r in result.file_results
        ],
    }


def _append_audit_log_entries(path: Path, group_results: list) -> None:
    """Ein JSON-Objekt pro Zeile, EIN Eintrag pro tatsächlich gelöschter
    Datei (Auftrag Phase 3 Abschnitt 16) - Append-Only, keine bestehenden
    Einträge werden je verändert. Enthält AUSSCHLIESSLICH die im Auftrag
    verlangten Felder, keine zusätzlichen sensiblen Informationen."""
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with open(path, "a", encoding="utf-8") as f:
        for result in group_results:
            entry = result.entry
            for file_result in result.file_results:
                if file_result.status != FileDeleteStatus.DELETED:
                    continue
                f.write(
                    json.dumps(
                        {
                            "timestamp": now,
                            "artist": entry.normalized_artist,
                            "title": entry.normalized_title,
                            "keep_path": str(entry.keep.path),
                            "deleted_path": str(file_result.path),
                            "original_size": next(
                                (fp.size for fp in entry.remove if fp.path == file_result.path),
                                None,
                            ),
                            "original_sha256": next(
                                (fp.sha256 for fp in entry.remove if fp.path == file_result.path),
                                None,
                            ),
                            "duration_seconds": entry.duration_seconds,
                            "mb_recording_id": entry.mb_recording_id,
                            "isrc": entry.isrc,
                            "resolution_reason": entry.reason,
                            "safety_gate": entry.safety_gate,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )


# ─────────────────────────────────────────────────────────────────────────
# main()
# ─────────────────────────────────────────────────────────────────────────


def _run_execute_phase(
    scan_root: Path, decisions: list, scan_after_snapshot: dict, permitted_root: Path
) -> int:
    """Auftrag Phase 3 Abschnitt 3/4/15/16/20: baut den Execution Plan,
    revalidiert + löscht gruppenweise, schreibt Manifest/Report/Audit-Log
    und verifiziert danach, dass AUSSCHLIESSLICH die erwarteten Dateien
    verschwunden sind (kein Kollateralschaden an nicht beteiligten
    Dateien - Auftrag Abschnitt 20 "verify unrelated files"). Gibt den
    finalen Exit-Code zurück."""
    plan = build_execution_plan(decisions)

    EXECUTION_PLAN_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(
        EXECUTION_PLAN_JSON_PATH,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "root": str(scan_root),
            "entries": [plan_entry_to_dict(e) for e in plan],
        },
    )

    validate_file = _make_file_validator(permitted_root)
    group_results = [
        execute_group(entry, validate_file, build_single_candidate)
        for entry in plan
    ]

    _append_audit_log_entries(AUDIT_LOG_JSONL_PATH, group_results)

    groups_eligible = len(plan)
    groups_skipped = sum(1 for r in group_results if not r.group_ok and r.skip_reason is not None)
    files_proposed = sum(len(entry.remove) for entry in plan)
    files_deleted = sum(
        1 for r in group_results for fr in r.file_results if fr.status == FileDeleteStatus.DELETED
    )
    files_skipped = sum(
        1
        for r in group_results
        for fr in r.file_results
        if fr.status == FileDeleteStatus.SKIPPED_GROUP_INVALID
    )
    files_failed = sum(
        1 for r in group_results for fr in r.file_results if fr.status == FileDeleteStatus.FAILED
    )
    path_safety_pass = not any(r.skip_stage == "path_safety" for r in group_results)
    hash_verification_pass = not any(r.skip_stage == "fingerprint" for r in group_results)
    revalidation_pass = not any(r.skip_stage is not None for r in group_results)
    keep_files_preserved = all(r.keep_intact for r in group_results)
    errors = files_failed

    log()
    log("=" * 60)
    log("DUPLICATE RESOLUTION EXECUTION")
    log("=" * 60)
    log()
    log("Mode:")
    log("  EXECUTE")
    log()
    log("Groups evaluated:")
    log(f"  {len(decisions)}")
    log()
    log("Groups eligible:")
    log(f"  {groups_eligible}")
    log()
    log("Groups skipped:")
    log(f"  {groups_skipped}")
    log()
    log("Files proposed:")
    log(f"  {files_proposed}")
    log()
    log("Files deleted:")
    log(f"  {files_deleted}")
    log()
    log("Files skipped:")
    log(f"  {files_skipped}")
    log()
    log("Manual review:")
    log(f"  {sum(1 for d in decisions if d.action != GroupAction.RESOLVED)}")
    log()
    log("Revalidation:")
    log(f"  {'PASS' if revalidation_pass else 'FAIL'}")
    log()
    log("Path safety:")
    log(f"  {'PASS' if path_safety_pass else 'FAIL'}")
    log()
    log("Hash verification:")
    log(f"  {'PASS' if hash_verification_pass else 'FAIL'}")
    log()
    log("KEEP files preserved:")
    log(f"  {'PASS' if keep_files_preserved else 'FAIL'}")
    log()
    log("Errors:")
    log(f"  {errors}")
    log()
    log("Library mutation:")
    log(f"  {'YES' if files_deleted > 0 else 'NO'}")
    log()

    for r in group_results:
        if r.skip_reason:
            log(f"⚠️  SKIPPED GROUP ({r.entry.normalized_artist} / {r.entry.normalized_title}): {r.skip_reason}")
        for fr in r.file_results:
            if fr.status == FileDeleteStatus.FAILED:
                log(f"❌ FAILED DELETE: {fr.path} - {fr.error}")

    # Auftrag Abschnitt 20: verify unrelated files unangetastet.
    post_execute_snapshot = snapshot_tree(scan_root)
    expected_deleted_paths = {
        str(fr.path)
        for r in group_results
        for fr in r.file_results
        if fr.status == FileDeleteStatus.DELETED
    }
    actually_removed_paths = set(scan_after_snapshot.keys()) - set(post_execute_snapshot.keys())
    unexpected_removals = actually_removed_paths - expected_deleted_paths
    missing_expected_removals = expected_deleted_paths - actually_removed_paths
    common_paths = set(scan_after_snapshot.keys()) & set(post_execute_snapshot.keys())
    unexpected_changes = {
        p for p in common_paths if scan_after_snapshot[p] != post_execute_snapshot[p]
    }
    unrelated_files_intact = not unexpected_removals and not unexpected_changes and not missing_expected_removals

    log("Unrelated files unaffected:")
    log(f"  {'PASS' if unrelated_files_intact else 'FAIL'}")
    if not unrelated_files_intact:
        if unexpected_removals:
            log(f"  🚨 Unerwartet entfernt: {sorted(unexpected_removals)}")
        if unexpected_changes:
            log(f"  🚨 Unerwartet verändert: {sorted(unexpected_changes)}")
        if missing_expected_removals:
            log(f"  🚨 Als gelöscht erwartet, aber noch vorhanden: {sorted(missing_expected_removals)}")

    all_expected_deletes_succeeded = files_deleted == files_proposed and files_skipped == 0 and errors == 0
    if not unrelated_files_intact:
        execution_result = "ABORTED"
    elif all_expected_deletes_succeeded:
        execution_result = "SUCCESS"
    else:
        execution_result = "PARTIAL"

    log()
    log("Execution result:")
    log(f"  {execution_result}")

    exec_report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "root": str(scan_root),
        "mode": "EXECUTE",
        "groups_evaluated": len(decisions),
        "groups_eligible": groups_eligible,
        "groups_skipped": groups_skipped,
        "files_proposed": files_proposed,
        "files_deleted": files_deleted,
        "files_skipped": files_skipped,
        "files_failed": files_failed,
        "revalidation": "PASS" if revalidation_pass else "FAIL",
        "path_safety": "PASS" if path_safety_pass else "FAIL",
        "hash_verification": "PASS" if hash_verification_pass else "FAIL",
        "keep_files_preserved": "PASS" if keep_files_preserved else "FAIL",
        "unrelated_files_unaffected": "PASS" if unrelated_files_intact else "FAIL",
        "errors": errors,
        "execution_result": execution_result,
        "groups": [group_result_to_dict(r) for r in group_results],
    }
    EXECUTION_REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(EXECUTION_REPORT_JSON_PATH, exec_report)
    log()
    log(f"📄 Execution Plan:   {EXECUTION_PLAN_JSON_PATH}")
    log(f"📄 Execution Report: {EXECUTION_REPORT_JSON_PATH}")
    log(f"📄 Audit Log:        {AUDIT_LOG_JSONL_PATH}")

    if execution_result == "SUCCESS":
        return 0
    if execution_result == "ABORTED":
        return 3
    return 4  # PARTIAL


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Duplicate Resolution - Dry-Run (Default) gegen die isolierte "
            "Testbibliothek. Mit --execute werden ausschließlich revalidierte "
            "REMOVE-Kandidaten tatsächlich gelöscht (Auftrag Phase 3)."
        )
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Explizit (Default-Verhalten ohnehin immer Dry-Run, sofern --execute fehlt).",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help=(
            "Führt nach erneuter Pre-Delete-Revalidierung (Fingerprint + "
            "semantische Neuentscheidung) die tatsächliche Löschung der "
            "aktuell gültigen REMOVE-Kandidaten durch. MANUAL_REVIEW/"
            "AMBIGUOUS/UNKNOWN werden NIE gelöscht."
        ),
    )
    parser.add_argument(
        "--path", type=str, default=None,
        help=(
            f"Teilbereich innerhalb {ALLOWED_ROOT} (Default: gesamter Root). "
            f"Alternativ ein Pfad innerhalb eines Read-Only-Produktions-Roots "
            f"({', '.join(str(r) for r in ALLOWED_READONLY_ROOTS)}) - dort "
            f"nur ohne --execute, es sei denn --confirm-production-execute "
            f"UND ein konkretes Unterverzeichnis (nicht der Root selbst)."
        ),
    )
    parser.add_argument(
        "--artist", type=str, default=None,
        help="Auf einen Artist-Ordner unterhalb des Roots einschränken.",
    )
    parser.add_argument(
        "--confirm-production-execute", action="store_true",
        help=(
            "Zusätzlich zu --execute erforderlich, wenn der Scan-Root "
            "innerhalb eines Read-Only-Produktions-Roots liegt. Muss auf "
            "ein konkretes Unterverzeichnis eingegrenzt sein (z. B. --path "
            ".../EinArtist) - gegen den gesamten Produktions-Root ist "
            "Execute auch damit nicht möglich."
        ),
    )
    for forbidden_flag in ("--apply", "--delete"):
        parser.add_argument(forbidden_flag, action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    if args.apply or args.delete:
        print("ERROR: mutation is not available via --apply/--delete - use --execute", file=sys.stderr)
        return 2

    try:
        if args.path and args.artist:
            print(
                "ERROR: --path und --artist sind nicht gleichzeitig zulässig",
                file=sys.stderr,
            )
            return 2
        if args.artist:
            target = ALLOWED_ROOT / args.artist
        elif args.path:
            target = Path(args.path)
        else:
            target = ALLOWED_ROOT
        scan_root = validate_scan_root(
            target,
            allow_execute=args.execute,
            production_execute_confirmed=args.confirm_production_execute,
        )
    except PathSafetyError as e:
        print(f"❌ PATH SAFETY: {e}", file=sys.stderr)
        return 2

    permitted_root = permitted_root_for(scan_root)

    log(f"🔍 DUPLICATE RESOLUTION — {'EXECUTE' if args.execute else 'DRY RUN'}")
    log()
    log("Library:")
    log(f"  {scan_root}")
    log()

    before_snapshot = snapshot_tree(scan_root)

    candidates = build_candidates(scan_root, log, permitted_root)
    groups = group_candidates_by_identity(candidates)

    decisions = []
    resolved_count = 0
    manual_review_count = 0
    single_candidate_count = 0
    duplicate_group_count = 0

    for key in sorted(groups.keys()):
        group_candidates = groups[key]
        if len(group_candidates) < 2:
            single_candidate_count += 1
            continue
        decision = resolve_group(group_candidates)
        duplicate_group_count += 1
        if decision.action == GroupAction.RESOLVED:
            resolved_count += 1
        else:
            manual_review_count += 1
        decisions.append(decision)

    log(f"Candidates scanned: {len(candidates)}")
    log(f"Duplicate groups: {duplicate_group_count}")

    for decision in decisions:
        print_decision(decision)

    # Diese Momentaufnahme beschreibt AUSSCHLIESSLICH die reine Scan-/
    # Resolve-Phase oberhalb - sie MUSS immer unverändert sein, unabhängig
    # von --execute (Scan/Resolve bleiben immer vollständig read-only,
    # INV-D23). Die eigentliche, gewollte Mutation durch --execute erfolgt
    # erst danach in _run_execute_phase() und wird dort separat verifiziert.
    scan_after_snapshot = snapshot_tree(scan_root)
    scan_read_only_intact = before_snapshot == scan_after_snapshot

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "root": str(scan_root),
        "files_scanned": len(candidates),
        "duplicate_groups": duplicate_group_count,
        "resolved_groups": resolved_count,
        "manual_review_groups": manual_review_count,
        "single_candidate_groups": single_candidate_count,
        "read_only_intact": scan_read_only_intact,
        "decisions": [decision_to_dict(d) for d in decisions],
    }
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(REPORT_JSON_PATH, report)

    log()
    log("─" * 40)
    log()
    log(f"📄 Report: {REPORT_JSON_PATH}")
    log()
    log("=" * 60)
    log("DUPLICATE RESOLUTION SUMMARY")
    log("=" * 60)
    log()
    log(f"Files scanned:      {len(candidates)}")
    log(f"Duplicate groups:   {duplicate_group_count}")
    log(f"Auto-resolvable:    {resolved_count}")
    log(f"Manual review:      {manual_review_count}")
    log(f"Single (no dup):    {single_candidate_count}")
    log(f"Read-only intact:   {'PASS' if scan_read_only_intact else 'FAIL'}")

    if not scan_read_only_intact:
        log()
        log("🚨 SAFETY VIOLATION: Dateisystem-Zustand hat sich während des Scans verändert!")
        return 3

    if args.execute:
        return _run_execute_phase(scan_root, decisions, scan_after_snapshot, permitted_root)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PathSafetyError as e:
        print(f"❌ PATH SAFETY: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"❌ Schwerer Initialisierungsfehler: {e}", file=sys.stderr)
        sys.exit(3)
