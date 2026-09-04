#!/usr/bin/env python3
# scripts/reprocess_artist_metadata.py
# -*- coding: utf-8 -*-
"""
Offizielles MusicBot-Reprocessing-Tool fuer bestehende Artist-Verzeichnisse
in der isolierten Testumgebung.

Ziel: bestehende, bereits vorhandene Audiodateien eines Artists erneut durch
die aktuelle Metadata-Pipeline laufen lassen (Tags/Cover/Lyrics
aktualisieren, fehlende MusicBrainz-IDs ergaenzen, eindeutig fehlerhafte
Dateinamen innerhalb ihres bestehenden Verzeichnisses korrigieren) - KEIN
Download, KEINE Aenderung der Library-/Verzeichnisstruktur, KEINE
Audio-Neucodierung.

Technische Referenz und vollstaendig durchgefuehrter erster Validierungslauf:
docs/archive/METADATA_REPROCESSING_TEST_CHAPO102.md
Allgemeine Dokumentation (Sicherheitsmodell, CLI, Workflow):
docs/METADATA_REPROCESSING.md

Nutzt ausschliesslich config_test.Config (isolierte Testumgebung) und die
echten Produktions-Subprozessoren von EnhancedMetadataProcessor
(ArtistNormalizer, TitleCleaner, GenreProcessor, LyricsProcessor,
CoverProcessor, TagWriter) - ruft aber bewusst NICHT
process_single_track()/move_to_library() auf:

  - move_to_library() wuerde das Zielverzeichnis aus dem frisch bestimmten
    Artist-Namen neu berechnen (Risiko fuer Verzeichnis-Struktur-Bruch,
    siehe utils/filenamefixer.py::build_final_path()).
  - Die volle Pipeline ruft unconditional AudioEnhancer.normalize_loudness()
    auf (verlustbehaftete FFmpeg-Neucodierung). Fuer dieses Tool
    ausdruecklich ausgeschlossen - AudioEnhancer wird an keiner Stelle
    importiert oder aufgerufen. Fehlendes ReplayGain/Loudness wird
    stattdessen als UNRESOLVED dokumentiert (siehe _check_unresolved()).

Album/Jahr werden NICHT ueber AlbumProcessor.determine_album_info() neu
bestimmt (diese Methode ist fuer Download-Zeit-Metadaten aus
Playlist/yt-dlp gebaut und wuerde bei fehlenden Kandidaten auf das
aktuelle Kalenderjahr zurueckfallen) - stattdessen werden die bereits
vorhandenen Album-/Jahr-Tags als Vertrauensbasis uebernommen ("bestehende
bessere Werte nicht unnoetig verschlechtern", CLAUDE.md Abschnitt 9).
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_test import Config  # isolierte Testkonfiguration - NIEMALS config.Config
from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
from services.clients.musicbrainz_client import MusicBrainzClient
from services.clients.lastfm_client import LastFMClient
from utils.singleton import SingletonMixin
from utils.artist_map import ArtistNormalizer
from utils.genre_map import GenreMapper

# Kern der Pro-Datei-Pipeline (frueher hier vollstaendig definiert) liegt
# jetzt in services/metadata/track_reprocessor.py — dieselbe Logik,
# unveraendert, damit auch services/library_repair/executor.py::apply_level2()
# sie nutzen kann (Nutzer-Entscheidung 2026-09-04, „Option 2a").
# Re-Import in den Modul-Namespace, damit die bestehenden Tests
# (importlib-Ladepfad, `rpam.<name>`) unveraendert weiterlaufen — sie sind
# damit die Charakterisierung, dass die Auslagerung verhaltensgleich ist.
from services.metadata.track_reprocessor import (  # noqa: F401
    audio_essence_md5,
    check_unresolved,
    diff_snapshots,
    flatten_existing_artists,
    process_file,
    snapshot,
    strip_producer_credit,
    strip_remix_suffix,
)

# Erlaubte Wurzel fuer JEDEN Schreibzugriff dieses Tools. Nichts ausserhalb
# davon darf jemals angefasst werden - siehe validate_input_path().
ALLOWED_ROOT = Path("/tmp/musicbot_test")
DEFAULT_METADATEN_ROOT = ALLOWED_ROOT / "metadaten"
DEFAULT_PRODUCTION_ROOT = Path("/mnt/musik_bilder/library")


class PathSafetyError(Exception):
    """Wird bei jeder Verletzung der Path-Safety-Guards ausgeloest."""


class SingletonSafetyError(Exception):
    """Wird ausgeloest, wenn EnhancedMetadataProcessor/ArtistNormalizer/
    GenreMapper in diesem Python-Prozess bereits konstruiert wurden, BEVOR
    dieses Skript sie mit config_test.Config konstruieren will."""


class ReprocessingPostRunCheckError(Exception):
    """Wird ausgeloest, wenn der Datei-Lauf selbst abgeschlossen wurde, der
    nachgelagerte Struktur-/Production-Safety-Check aber crasht - siehe
    assert_processor_singletons_are_fresh()-Kommentar fuer den Hintergrund
    dieser Haertung (docs/FINDINGS_INDEX.md, Audit vor Telegram-Integration)."""


def assert_processor_singletons_are_fresh() -> None:
    """Verhindert das stillschweigende Wiederverwenden einer bereits in
    diesem Prozess konstruierten Singleton-Instanz von
    EnhancedMetadataProcessor/ArtistNormalizer/GenreMapper.

    Hintergrund (Audit vor geplanter Telegram-Menue-Integration,
    docs/FINDINGS_INDEX.md): alle drei Klassen sind SingletonMixin
    (utils/singleton.py) - "First Mover gewinnt", jede spaetere
    Konstruktion mit anderen Args wird bei bereits vorhandener Instanz
    STILLSCHWEIGEND ignoriert (kein Fehler, kein Log). Als eigenstaendiger
    CLI-Subprozess ist das harmlos, da jeder Lauf einen frischen
    Python-Prozess bekommt. Wuerde main() aber jemals in-process aus einem
    bereits laufenden Bot heraus aufgerufen (statt als Subprozess), haette
    der Bot EnhancedMetadataProcessor laengst mit der ECHTEN config.Config
    konstruiert - dieses Skript wuerde trotz importiertem config_test.Config
    unbemerkt die produktive Instanz zurueckbekommen und ueber
    auto_learn_manager.learn_genre()/observe_featured_artists() direkt in
    die echten mapping/auto_learned_*.json schreiben. processor.aclose()/
    processor.cleanup() am Ende von main() wuerden zusaetzlich Ressourcen
    (genius_client-Session, Metadata-Cache) der noch laufenden
    Produktivinstanz abreissen. Exakt dieses Singleton-Bleeding-Muster hat
    in diesem Repo bereits real mapping/case_preserve.yaml und
    mapping/artist_overrides.json verunreinigt (siehe
    tests/conftest.py::reset_singletons()-Docstring) - nur bisher ueber
    einen anderen Ausloeser (Tests) statt dieses Skripts.

    Muss VOR jeder EnhancedMetadataProcessor(config=Config)-Konstruktion in
    main() aufgerufen werden. Wirft SingletonSafetyError, sobald IRGENDEINE
    der drei Klassen bereits eine initialisierte Instanz im
    prozessweiten SingletonMixin._instances-Cache hat - unabhaengig davon,
    mit welcher Config diese urspruenglich konstruiert wurde, da geteilte
    Nutzung durch zwei unabhaengige Aufrufer (Bot + dieses Skript) auch bei
    zufaellig identischer Config riskant waere (z.B. gleichzeitiges
    aclose()/cleanup()).
    """
    for cls in (EnhancedMetadataProcessor, ArtistNormalizer, GenreMapper):
        existing = SingletonMixin._instances.get(cls)
        if existing is not None and getattr(existing, "_initialized", False):
            raise SingletonSafetyError(
                f"{cls.__name__} wurde in diesem Prozess bereits konstruiert "
                f"(vermutlich durch einen parallel laufenden Bot-Prozess). "
                f"reprocess_artist_metadata.py darf NICHT in-process in einem "
                f"bereits laufenden Bot aufgerufen werden - nur als "
                f"eigenstaendiger Subprozess (siehe docs/METADATA_REPROCESSING.md)."
            )


# ─────────────────────────────────────────────────────────────────────────
# Path-Safety
# ─────────────────────────────────────────────────────────────────────────


def validate_input_path(input_path: Path, metadaten_root: Path) -> Path:
    """
    Harte Path-Safety-Guards (Abschnitt 4 des Auftrags). Loest bei jeder
    Verletzung PathSafetyError aus - der Aufrufer darf danach KEINE Datei
    anfassen. Symlinks werden durch .resolve(strict=True) vollstaendig
    aufgeloest, bevor irgendeine Grenzpruefung stattfindet.
    """
    try:
        resolved = input_path.resolve(strict=True)
    except FileNotFoundError:
        raise PathSafetyError(f"Input existiert nicht: {input_path}")
    except OSError as e:
        raise PathSafetyError(f"Input nicht aufloesbar: {input_path} ({e})")

    if not resolved.is_dir():
        raise PathSafetyError(f"Input ist kein Verzeichnis: {resolved}")

    # Produktions-Guard zuerst und unabhaengig von den uebrigen
    # Grenzpruefungen: ein Treffer hier ist immer ein harter Stopp, egal
    # welche metadaten_root/ALLOWED_ROOT-Konstellation sonst vorliegt.
    # Selbst wenn ein Symlink INNERHALB von metadaten/ sekundaer auf die
    # Produktions-Library zeigen wuerde, faengt bereits das .resolve() oben
    # das ab (resolved landet dann ausserhalb der erlaubten Testumgebung) -
    # dieser Check ist zusaetzliche Defense-in-Depth mit einer eindeutigen,
    # eigenen Fehlermeldung.
    for prod_candidate in (DEFAULT_PRODUCTION_ROOT,):
        try:
            prod_resolved = prod_candidate.resolve()
        except OSError:
            continue
        if resolved == prod_resolved or prod_resolved in resolved.parents:
            raise PathSafetyError(
                f"Input zeigt auf eine Produktionsbibliothek: {resolved}"
            )

    metadaten_root_resolved = metadaten_root.resolve()
    if resolved == metadaten_root_resolved:
        raise PathSafetyError(
            f"Input darf nicht die Wurzel {metadaten_root_resolved} selbst sein "
            f"- ein konkretes Artist-Verzeichnis angeben"
        )
    if metadaten_root_resolved not in resolved.parents:
        raise PathSafetyError(
            f"Input liegt nicht unterhalb von {metadaten_root_resolved}: {resolved}"
        )

    allowed_root_resolved = ALLOWED_ROOT.resolve()
    if allowed_root_resolved not in resolved.parents and resolved != allowed_root_resolved:
        raise PathSafetyError(
            f"Input liegt ausserhalb der erlaubten Testumgebung {allowed_root_resolved}: {resolved}"
        )

    return resolved


def validate_file_within_root(file_path: Path, root: Path) -> bool:
    """Symlink-Schutz auf Dateiebene: eine innerhalb des Artist-Verzeichnisses
    gefundene Datei koennte selbst ein Symlink sein, der nach aussen zeigt.
    Gibt False zurueck (statt zu werfen), damit main() einzelne verdaechtige
    Dateien ueberspringen und protokollieren kann, ohne den gesamten Lauf
    abzubrechen."""
    try:
        resolved_file = file_path.resolve(strict=True)
        resolved_root = root.resolve()
    except OSError:
        return False
    return resolved_root == resolved_file or resolved_root in resolved_file.parents


# ─────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────


class ReprocessLogger:
    """Schreibt strukturierte, live nachvollziehbare Log-Eintraege (tail -f-faehig,
    jede Zeile wird sofort geflusht)."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = open(path, "a", encoding="utf-8")

    def line(self, text: str = ""):
        self._fh.write(text + "\n")
        self._fh.flush()

    def section(self, title: str, emoji: str = "─"):
        self.line("")
        self.line(f"{emoji} {title} " + "─" * max(0, 60 - len(title)))

    def kv(self, key: str, value, indent: int = 1):
        self.line(f"{'   ' * indent}{key}: {value}")

    def close(self):
        self._fh.close()


# ─────────────────────────────────────────────────────────────────────────
# Post-Run Safety Check
# ─────────────────────────────────────────────────────────────────────────


def snapshot_directory_tree(root: Path) -> dict:
    """Rein lesendes Inventar (relative Pfade, Groessen) fuer den
    Struktur-Invariante-Vergleich vor/nach dem Lauf."""
    files = {}
    dirs = set()
    for p in root.rglob("*"):
        if p.is_dir():
            dirs.add(str(p.relative_to(root)))
        elif p.is_file():
            files[str(p.relative_to(root))] = p.stat().st_size
    return {"dirs": dirs, "files": files}


def snapshot_production_files(production_root: Path, artist_name: str, relative_paths: list) -> dict:
    """Rein lesende Momentaufnahme (mtime, Groesse, SHA256) der zu den
    Testdateien korrespondierenden Produktionsdateien - fuer den
    automatischen Production-Protection-Check. Liefert pro Datei None,
    wenn keine korrespondierende Produktionsdatei existiert (kein Fehler -
    der Testbestand kann bereits umbenannte/entfernte Namen enthalten)."""
    out = {}
    artist_root = production_root / artist_name
    for rel in relative_paths:
        # rel ist z.B. "CHAPO102/Singles/2024 - OMG.m4a" -> Pfad relativ
        # zum Artist-Verzeichnis selbst ableiten
        try:
            rel_within_artist = Path(rel).relative_to(artist_name)
        except ValueError:
            out[rel] = None
            continue
        prod_file = artist_root / rel_within_artist
        if not prod_file.exists() or not prod_file.is_file():
            out[rel] = None
            continue
        st = prod_file.stat()
        with open(prod_file, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        out[rel] = {"mtime": st.st_mtime, "size": st.st_size, "sha256": digest}
    return out


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True,
        help="Vollstaendiger Pfad zum bestehenden Artist-Testverzeichnis, "
             "z.B. /tmp/musicbot_test/metadaten/ARTIST",
    )
    parser.add_argument(
        "--metadaten-root", default=str(DEFAULT_METADATEN_ROOT),
        help=f"Erlaubte Wurzel fuer --input (Standard: {DEFAULT_METADATEN_ROOT})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Nur analysieren - keine Datei aendern, kein Tag schreiben, "
             "kein Cover schreiben, kein Rename, keine Audioverarbeitung",
    )
    parser.add_argument(
        "--production-root", default=str(DEFAULT_PRODUCTION_ROOT),
        help=f"Nur-lesend verwendete Produktions-Library fuer den "
             f"automatischen Post-Run-Safety-Check (Standard: {DEFAULT_PRODUCTION_ROOT})",
    )
    parser.add_argument(
        "--no-production-check", action="store_true",
        help="Production-Protection-Vergleich gegen --production-root auslassen",
    )
    args = parser.parse_args()

    metadaten_root = Path(args.metadaten_root)

    # Bug-Fix (Audit vor Telegram-Integration, docs/FINDINGS_INDEX.md):
    # sys.exit(1) wirft SystemExit (erbt von BaseException, nicht Exception)
    # - wuerde main() jemals in-process statt per CLI aufgerufen, koennte
    # das den gesamten aufrufenden Prozess beenden. PathSafetyError
    # propagiert stattdessen normal an den Aufrufer; der CLI-Entry-Point
    # (unten, if __name__ == "__main__") faengt sie weiterhin ab und
    # verhaelt sich fuer die Kommandozeile exakt wie bisher (Fehlermeldung
    # + Exit-Code 1).
    resolved_input = validate_input_path(Path(args.input), metadaten_root)

    assert str(Config.BASE_DIR) == "/tmp/musicbot_test", (
        f"❌ config_test.Config.BASE_DIR ist nicht isoliert: {Config.BASE_DIR}"
    )

    artist_name = resolved_input.name
    candidate_files = sorted(resolved_input.rglob("*.m4a"))
    files = []
    skipped_unsafe = []
    for f in candidate_files:
        if validate_file_within_root(f, resolved_input):
            files.append(f)
        else:
            skipped_unsafe.append(f)

    # Nutzer-Wunsch (2026-09-02): feste Log-Datei (Config.LOG_DIR/script.log)
    # wieder zurueckgenommen - zurueck zu einer eigenen, zeit-gestempelten
    # Datei pro Lauf.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(
        f"/tmp/musicbot_test/metadata_reprocessing_{artist_name}_{timestamp}.log"
    )
    log = ReprocessLogger(log_path)

    log.line(f"🚀 MusicBot Metadata Reprocessing Tool - {artist_name}")
    log.kv("📦 Repository", "dkmd89-dev/musicbot", indent=0)
    log.kv("🧪 Test Environment", str(Config.BASE_DIR), indent=0)
    log.kv("🎵 Artist", artist_name, indent=0)
    log.kv("📁 Input", str(resolved_input), indent=0)
    log.kv("🔒 Modus", "DRY-RUN" if args.dry_run else "LIVE", indent=0)
    log.kv("📄 Dateien gefunden", len(files), indent=0)
    for f in files:
        log.kv("  -", f.relative_to(resolved_input), indent=0)
    if skipped_unsafe:
        log.line("⚠️ UEBERSPRUNGEN (ausserhalb der erlaubten Wurzel, Symlink-Verdacht):")
        for f in skipped_unsafe:
            log.kv("  -", f, indent=0)

    # ── Struktur-/Production-Snapshot VOR dem Lauf ──────────────────────────
    dir_snapshot_before = snapshot_directory_tree(resolved_input)
    production_root = Path(args.production_root)
    production_check_enabled = not args.no_production_check and production_root.exists()
    relative_paths = [str(f.relative_to(resolved_input.parent)) for f in files]
    prod_snapshot_before = (
        snapshot_production_files(production_root, artist_name, relative_paths)
        if production_check_enabled else {}
    )

    assert_processor_singletons_are_fresh()
    processor = EnhancedMetadataProcessor(config=Config)
    mb_client = MusicBrainzClient()
    lfm_client = LastFMClient()

    results = []
    try:
        for f in files:
            r = await process_file(
                f, resolved_input, processor, mb_client, lfm_client, log,
                dry_run=args.dry_run,
            )
            results.append(r)
    finally:
        try:
            await processor.aclose()
        except Exception:
            pass
        processor.cleanup()

    # ── Struktur-/Production-Snapshot NACH dem Lauf ─────────────────────────
    try:
        dir_snapshot_after = snapshot_directory_tree(resolved_input)
        prod_snapshot_after = (
            snapshot_production_files(production_root, artist_name, relative_paths)
            if production_check_enabled else {}
        )

        dirs_changed = dir_snapshot_before["dirs"] != dir_snapshot_after["dirs"]
        files_before = set(dir_snapshot_before["files"])
        files_after = set(dir_snapshot_after["files"])
        files_created = files_after - files_before
        files_deleted = files_before - files_after

        # Ein erlaubter Rename (Title-Cleaning-Korrektur, siehe Abschnitt 9 der
        # Doku) erscheint in einem rohen Verzeichnis-Snapshot-Diff zwangslaeufig
        # als ein Create+Delete-Paar - das ist erwuenscht, solange beide
        # Ereignisse im SELBEN Verzeichnis stattfinden (die Rename-Logik selbst
        # garantiert bereits parent-Gleichheit, siehe rename_blocked_reason
        # oben). Nur ein Ungleichgewicht PRO VERZEICHNIS zwischen Creates und
        # Deletes waere ein echtes Struktur-Problem (Datei tatsaechlich
        # verschoben/verschwunden statt nur umbenannt).
        from collections import Counter

        created_dirs = Counter(str(Path(f).parent) for f in files_created)
        deleted_dirs = Counter(str(Path(f).parent) for f in files_deleted)
        unexplained_file_changes = created_dirs != deleted_dirs

        production_changed = []
        for rel, before_info in prod_snapshot_before.items():
            after_info = prod_snapshot_after.get(rel)
            if before_info is not None and before_info != after_info:
                production_changed.append(rel)

        # ── Abschlussbericht ─────────────────────────────────────────────────
        changed = [r for r in results if r["status"] == "changed"]
        unchanged = [r for r in results if r["status"] == "unchanged"]
        unresolved = [r for r in results if r["unresolved"]]
        errors = [r for r in results if r["status"] == "error"]
        audio_stream_changed = [r for r in results if r["audio_stream_changed"]]
        audio_essence_changed = [r for r in results if r["audio_essence_changed"]]

        _feat_learned_decisions = {"LEARNED", "UPDATED", "WOULD_LEARN", "WOULD_UPDATE"}
        auto_learn_artists = {
            d["canonical"]
            for r in results
            for d in r.get("auto_learn", {}).get("featured_artists", [])
            if d["decision"] in _feat_learned_decisions
        }
        auto_learn_genres = {
            r["auto_learn"]["genre"]["artist"]
            for r in results
            if r.get("auto_learn", {}).get("genre")
            and r["auto_learn"]["genre"]["decision"] in _feat_learned_decisions
        }

        log.section("FINAL SUMMARY", emoji="🏁")
        log.kv("Files processed", len(results), indent=0)
        log.kv("Changed", len(changed), indent=0)
        log.kv("Unchanged", len(unchanged), indent=0)
        log.kv("Unresolved", len(unresolved), indent=0)
        log.kv("Errors", len(errors), indent=0)
        log.kv("Auto-Learn Artists (Feature-Artists)", len(auto_learn_artists), indent=0)
        if auto_learn_artists:
            log.kv("  Artists", sorted(auto_learn_artists), indent=0)
        log.kv("Auto-Learn Genres", len(auto_learn_genres), indent=0)
        if auto_learn_genres:
            log.kv("  Artists", sorted(auto_learn_genres), indent=0)

        log.section("POST-RUN SAFETY CHECK", emoji="🔎")
        log.kv("Production files changed", f"{len(production_changed)}/{len(prod_snapshot_before)}", indent=0)
        if production_changed:
            for rel in production_changed:
                log.kv("  !!! GEAENDERT", rel, indent=0)
        log.kv("Production check enabled", production_check_enabled, indent=0)
        log.kv("Directory structure changes", int(dirs_changed), indent=0)
        log.kv("Files created", len(files_created), indent=0)
        log.kv("Files deleted", len(files_deleted), indent=0)
        log.kv(
            "  davon durch Rename im selben Verzeichnis erklaerbar",
            not unexplained_file_changes,
            indent=0,
        )
        log.kv("Audio essence changes", f"{len(audio_essence_changed)}/{len(results)}", indent=0)
        log.kv("Audio stream (codec/rate/channels/duration) changes", len(audio_stream_changed), indent=0)

        overall_pass = (
            not production_changed
            and not dirs_changed
            and not unexplained_file_changes
            and not audio_essence_changed
            and not audio_stream_changed
            and not errors
        )
        overall = "PASS" if overall_pass and not unresolved else (
            "PASS WITH UNRESOLVED CASES" if overall_pass else "FAIL"
        )
        log.kv("Overall", overall, indent=0)
        log.close()
    except Exception:
        log.line("❌ POST-RUN SAFETY CHECK abgebrochen (siehe Traceback im Aufrufer) - der eigentliche Datei-Lauf oben ist bereits abgeschlossen")
        log.close()
        raise

    summary = {
        "artist": artist_name,
        "dry_run": args.dry_run,
        "files_processed": len(results),
        "changed": len(changed),
        "unchanged": len(unchanged),
        "unresolved": len(unresolved),
        "errors": len(errors),
        "audio_stream_changes": len(audio_stream_changed),
        "audio_essence_changes": len(audio_essence_changed),
        "directory_structure_changes": int(dirs_changed),
        "production_file_changes": len(production_changed),
        "files_created": len(files_created),
        "files_deleted": len(files_deleted),
        "auto_learn_artists": sorted(auto_learn_artists),
        "auto_learn_genres": sorted(auto_learn_genres),
        "overall": overall,
        "log": str(log_path),
        "results": results,
    }
    print(f"Log: {log_path}")
    print(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except PathSafetyError as e:
        print(f"❌ PATH SAFETY: {e}")
        sys.exit(1)
    except SingletonSafetyError as e:
        print(f"❌ SINGLETON SAFETY: {e}")
        sys.exit(1)
