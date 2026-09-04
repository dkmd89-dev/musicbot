# services/library_repair/planner.py
# -*- coding: utf-8 -*-
"""
Repair Planner (Phase 2, Prompt Abschnitt 5/6/12/22).

Reine Funktion: Health-Report (dict) -> RepairPlan. **Kein** Dateisystem-
Zugriff, **keine** Ausfuehrung, **keine** externen Aufrufe. Bildet jeden
Health-Issue-Code auf genau eine bestehende Reparatur-Faehigkeit ab
(Registry unten) und bestimmt Sicherheitsstufe / Freigabebedarf.

    SCAN -> CLASSIFY (hier) -> PLAN -> APPROVE -> REPAIR -> VERIFY

Grundsatz (Prompt Abschnitt 22): NICHT "alle Issues automatisch reparieren".
Unsichere Faelle -> MANUAL_REVIEW.

Jeder Registry-Eintrag benennt die BESTEHENDE Komponente, die die
Reparatur spaeter ausfuehrt (Prompt Abschnitt 21 — keine Duplizierung):
  SAFE_AUTOMATIC        -> services/metadata/tag_writer.py::TagWriter (atomar)
                          + utils/artist_map.py::split_main_and_featuring
  METADATA_REPROCESSING -> services/metadata/track_reprocessor.py::process_file
  EXTERNAL_METADATA     -> services/metadata/* (GenreProcessor / MusicBrainzClient)
  COVER                 -> services/metadata/cover_processor.py::CoverProcessor
  LOUDNESS              -> services/library_repair/replaygain_repairs.py
                          (verlustfreier ReplayGain-Tag, kein Re-Encode)
  DUPLICATE             -> scripts/resolve_duplicates.py (+ services/duplicate/*)
"""

from __future__ import annotations

from services.library_health.issues import ALL_CODES as _HEALTH_CODES

from .models import RepairAction, RepairCandidate, RepairLevel, RepairPlan, RepairSpec

_A = RepairAction
_L = RepairLevel


def _spec(code, action, level, component, *, approval=True, external=False,
          destructive=False, change="") -> RepairSpec:
    return RepairSpec(
        issue_code=code, action=action, level=level, reuses_component=component,
        requires_approval=approval, requires_external=external,
        is_destructive=destructive, expected_change=change,
    )


# ─────────────────────────────────────────────────────────────────────────
# Registry — genau ein Eintrag pro Health-Issue-Code.
# tests/test_library_repair_planner.py verifiziert die Vollstaendigkeit
# gegen services.library_health.issues.ALL_CODES.
# ─────────────────────────────────────────────────────────────────────────

_SPECS: tuple[RepairSpec, ...] = (
    # ── Metadata ────────────────────────────────────────────────────────
    _spec("META_NOT_ANALYZABLE", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW,
          "-", approval=True, change="Tag-Container defekt — manuell pruefen / neu laden"),
    _spec("META_ARTIST_MISSING", _A.METADATA_REPROCESS, _L.METADATA_REPROCESSING,
          "reprocess_artist_metadata.py", external=True,
          change="Artist-Tag aus Pipeline neu bestimmen (Before/After-Diff)"),
    _spec("META_TITLE_MISSING", _A.METADATA_REPROCESS, _L.METADATA_REPROCESSING,
          "reprocess_artist_metadata.py", external=True,
          change="Titel-Tag aus Pipeline neu bestimmen"),
    _spec("META_TITLE_NOT_CLEAN", _A.METADATA_REPROCESS, _L.METADATA_REPROCESSING,
          "reprocess_artist_metadata.py", external=True,
          change="Titel-Tag ueber die reale Pipeline bereinigen "
                 "(Anfuehrungszeichen/prod.-Credit/Marketing-Suffix entfernen; "
                 "Before/After-Diff, Audio unveraendert)"),
    _spec("META_ALBUM_MISSING", _A.METADATA_REPROCESS, _L.METADATA_REPROCESSING,
          "reprocess_artist_metadata.py", external=True,
          change="Album-Tag aus Pipeline neu bestimmen"),
    _spec("META_ALBUM_ARTIST_MISSING", _A.MULTI_ARTIST_SPLIT, _L.SAFE_AUTOMATIC,
          "TagWriter", approval=False,
          change="Album-Artist = Haupt-Artist des Tracks (deterministisch)"),
    _spec("META_YEAR_MISSING", _A.EXTERNAL_ID_LOOKUP, _L.EXTERNAL_METADATA,
          "MusicBrainzClient", external=True,
          change="Jahr per MusicBrainz-Release nachtragen (nur bei eindeutigem Match)"),
    _spec("META_YEAR_INVALID", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Jahr-Tag ist unplausibel — manuell korrigieren"),
    _spec("META_GENRE_MISSING", _A.EXTERNAL_ID_LOOKUP, _L.EXTERNAL_METADATA,
          "GenreProcessor", external=True,
          change="Genre per GenreProcessor-Fallback-Kette bestimmen"),
    _spec("META_TRACK_NUMBER_MISSING", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Tracknummer nicht sicher ableitbar — manuell / aus Album-Kontext"),
    _spec("META_MB_RECORDING_MISSING", _A.EXTERNAL_ID_LOOKUP, _L.EXTERNAL_METADATA,
          "MusicBrainzClient", external=True,
          change="MB Recording ID per eindeutigem Match nachtragen"),
    _spec("META_MB_RELEASE_MISSING", _A.EXTERNAL_ID_LOOKUP, _L.EXTERNAL_METADATA,
          "MusicBrainzClient", external=True,
          change="MB Release ID per eindeutigem Match nachtragen"),
    _spec("META_ISRC_MISSING", _A.EXTERNAL_ID_LOOKUP, _L.EXTERNAL_METADATA,
          "MusicBrainzClient", external=True,
          change="ISRC per eindeutigem Match nachtragen"),

    # ── Artwork ─────────────────────────────────────────────────────────
    _spec("ARTWORK_MISSING", _A.COVER_FETCH, _L.COVER, "CoverProcessor", external=True,
          change="Cover suchen; nur einbetten, wenn eindeutig passend"),
    _spec("ARTWORK_INVALID", _A.COVER_FETCH, _L.COVER, "CoverProcessor", external=True,
          change="Cover neu suchen und ersetzen (nur bei besserem Treffer)"),
    _spec("ARTWORK_LOW_RESOLUTION", _A.COVER_FETCH, _L.COVER, "CoverProcessor", external=True,
          change="hoeher aufloesendes Cover suchen; nur ersetzen wenn deutlich besser"),
    _spec("ARTWORK_NON_SQUARE", _A.COVER_FETCH, _L.COVER, "CoverProcessor", external=True,
          change="quadratisches Cover suchen; nur ersetzen wenn eindeutig passend"),

    # ── Lyrics ──────────────────────────────────────────────────────────
    _spec("LYRICS_MISSING", _A.METADATA_REPROCESS, _L.METADATA_REPROCESSING,
          "reprocess_artist_metadata.py", external=True,
          change="Lyrics ueber LyricsProcessor-Fallback nachtragen"),
    _spec("LYRICS_EMPTY", _A.METADATA_REPROCESS, _L.METADATA_REPROCESSING,
          "reprocess_artist_metadata.py", external=True, change="Lyrics neu holen"),
    _spec("LYRICS_INVALID", _A.METADATA_REPROCESS, _L.METADATA_REPROCESSING,
          "reprocess_artist_metadata.py", external=True, change="Lyrics neu holen"),

    # ── Audio ───────────────────────────────────────────────────────────
    _spec("AUDIO_NOT_ANALYZABLE", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Datei nicht analysierbar — manuell pruefen / neu laden"),
    _spec("AUDIO_NO_STREAM", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="kein Audio-Stream — Track neu herunterladen"),
    _spec("AUDIO_CORRUPT", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="beschaedigte Datei — Track neu herunterladen"),
    _spec("AUDIO_LOW_BITRATE", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="niedrige Bitrate — ggf. in besserer Qualitaet neu laden"),
    _spec("AUDIO_VERY_SHORT", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="sehr kurz — Skit/Intro oder abgeschnitten? manuell pruefen"),

    # ── Loudness ────────────────────────────────────────────────────────
    # LOUDNESS_OFF_TARGET (nur bei --measure-loudness): gemessene LUFS-
    # Abweichung > 2 dB von -16, auch nach einem evtl. vorhandenen RG-Tag.
    # Fix: VERLUSTFREI einen replaygain_track_gain-/_peak-Tag schreiben
    # (Audio byte-identisch) — ein RG-faehiger Player (Navidrome) bringt die
    # Datei damit auf -16. Kein Re-Encode (Nutzer-Entscheidung 2026-09-04:
    # die Download-Pipeline normalisiert frische Downloads bereits per
    # loudnorm; fuer den Altbestand reicht der Tag).
    _spec("LOUDNESS_OFF_TARGET", _A.LOUDNESS_NORMALIZE, _L.LOUDNESS,
          "replaygain_repairs (verlustfreier RG-Tag)", external=True,
          change="replaygain_track_gain-/_peak-Tag schreiben (Ziel -16 LUFS, "
                 "Audio byte-identisch), Backup + Rollback"),
    # Die replaygain_track_*-Freeform-Tags sind Altlast — die AKTUELLE
    # Pipeline schreibt sie nirgends (tag_writer.py). Ein fehlender/kaputter
    # Legacy-Tag ist KEIN Grund fuer ein Audio-Re-Encode.
    _spec("LOUDNESS_TAG_MISSING", _A.MANUAL_REVIEW, _L.NOT_REPAIRABLE,
          "-", change="Legacy-ReplayGain-Tag; aktuelle Pipeline schreibt ihn "
                      "bewusst nicht — nichts zu tun"),
    _spec("LOUDNESS_TAG_INVALID", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW,
          "-", change="kaputter Legacy-ReplayGain-Tag — manuell entfernen/pruefen"),
    _spec("LOUDNESS_TAG_PARTIAL", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW,
          "-", change="unvollstaendige Legacy-ReplayGain-Tag-Familie — manuell pruefen"),

    # ── Struktur / Dateiname ───────────────────────────────────────────
    _spec("STRUCTURE_INVALID_PATH", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="ausserhalb der Library-Struktur — manuell einordnen (kein Auto-Move)"),
    _spec("STRUCTURE_FILE_OUTSIDE_HIERARCHY", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Datei im falschen Ordner — manuell einordnen (kein Auto-Move)"),
    _spec("FILENAME_TITLE_MISMATCH", _A.FILENAME_RENAME_IN_PLACE, _L.SAFE_AUTOMATIC,
          "reprocess_artist_metadata.py (Rename im selben Verzeichnis)", approval=False,
          change="Dateiname aus Titel-Tag + Konvention neu bilden (nur im selben Verzeichnis)"),
    _spec("FILENAME_SUSPICIOUS", _A.FILENAME_RENAME_IN_PLACE, _L.SAFE_AUTOMATIC,
          "utils/helpers.py::sanitize_filename", approval=False,
          change="doppelte Leerzeichen / illegale Zeichen im Dateinamen bereinigen"),
    _spec("FILENAME_EXTENSION_UNEXPECTED", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="abweichendes Format — Konvertierung ist keine sichere Auto-Reparatur"),

    # ── Multi-Artist ───────────────────────────────────────────────────
    _spec("MULTI_ARTIST_SUSPICIOUS", _A.MULTI_ARTIST_SPLIT, _L.SAFE_AUTOMATIC,
          "split_main_and_featuring + TagWriter", approval=False,
          change="zusammengeklebten Artist-String in separate ©ART-/ARTISTS-Werte splitten"),
    _spec("MULTI_ARTIST_INCONSISTENT", _A.MULTI_ARTIST_SPLIT, _L.SAFE_AUTOMATIC,
          "split_main_and_featuring + TagWriter", approval=False,
          change="©ART an die bereits korrekt gesplittete ARTISTS-Freeform-Liste angleichen"),
    _spec("MULTI_ARTIST_DUPLICATE", _A.MULTI_ARTIST_SPLIT, _L.SAFE_AUTOMATIC,
          "TagWriter", approval=False,
          change="doppelten Artist-Namen aus dem Multi-Artist-Feld entfernen"),

    # ── Genre ──────────────────────────────────────────────────────────
    _spec("GENRE_EMPTY", _A.EXTERNAL_ID_LOOKUP, _L.EXTERNAL_METADATA, "GenreProcessor",
          external=True, change="Genre per GenreProcessor bestimmen"),
    _spec("GENRE_INVALID", _A.METADATA_REPROCESS, _L.METADATA_REPROCESSING,
          "reprocess_artist_metadata.py", external=True,
          change="Genre neu bestimmen / durch GenreMapper normalisieren"),
    _spec("GENRE_DELIMITER_INCONSISTENT", _A.GENRE_DELIMITER_NORMALIZE, _L.SAFE_AUTOMATIC,
          "TagWriter", approval=False,
          change="Genre-Separator ' / ' -> '; ' (deterministisch, kein Wertverlust)"),

    # ── Album ──────────────────────────────────────────────────────────
    _spec("ALBUM_TRACK_GAP", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="fehlende Tracks — Nutzer entscheidet, ob nachladen"),
    _spec("ALBUM_DUPLICATE_TRACK_NUMBER", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="doppelte Tracknummer — korrekte Zuordnung ist nicht eindeutig"),
    _spec("ALBUM_NAME_INCONSISTENT", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="uneinheitlicher Album-Name — korrekter Name ist nicht eindeutig"),
    _spec("ALBUM_ARTIST_INCONSISTENT", _A.MULTI_ARTIST_SPLIT, _L.SAFE_AUTOMATIC,
          "TagWriter", approval=False,
          change="Album-Artist aller Tracks auf den Verzeichnis-Artist vereinheitlichen"),
    _spec("ALBUM_YEAR_INCONSISTENT", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="uneinheitliches Jahr — korrektes Jahr ist nicht eindeutig"),
    _spec("ALBUM_GENRE_INCONSISTENT", _A.NONE, _L.NOT_REPAIRABLE, "-", approval=False,
          change="unterschiedliche Genres koennen legitim sein — reine Beobachtung"),
    _spec("ALBUM_RELEASE_ID_INCONSISTENT", _A.EXTERNAL_ID_LOOKUP, _L.EXTERNAL_METADATA,
          "MusicBrainzClient", external=True,
          change="alle Tracks auf DIE eine Release-ID des Studio-Albums mappen (bei eindeutigem Match)"),
    _spec("ALBUM_COVER_INCONSISTENT", _A.COVER_FETCH, _L.COVER, "CoverProcessor",
          external=True, change="ein einheitliches Album-Cover fuer alle Tracks setzen"),

    # ── Artist ─────────────────────────────────────────────────────────
    _spec("ARTIST_DIR_TAG_MISMATCH", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Verzeichnis vs. Tag — Verzeichnis-Umbenennung ist keine sichere Auto-Reparatur"),
    _spec("ARTIST_NAME_VARIANTS", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="mehrere Artist-Ordner desselben Artists — Zusammenfuehren ist eine Struktur-aenderung"),

    # ── Duplicate ──────────────────────────────────────────────────────
    _spec("DUPLICATE_EXACT", _A.DUPLICATE_RESOLVE, _L.DUPLICATE,
          "resolve_duplicates.py", destructive=True,
          change="byte-identische Kopie loeschen — NUR mit --allow-delete + Freigabe"),
    _spec("DUPLICATE_RECORDING", _A.DUPLICATE_RESOLVE, _L.DUPLICATE,
          "resolve_duplicates.py", destructive=True,
          change="Recording-Duplikat via Safety-Gate aufloesen — NUR mit --allow-delete + Freigabe"),
    _spec("DUPLICATE_SUSPECTED", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Verdachtsfall (Remix/Live moeglich) — immer manuelle Pruefung"),
)

REGISTRY: dict[str, RepairSpec] = {s.issue_code: s for s in _SPECS}


def plan_repairs(report: dict) -> RepairPlan:
    """Baut den Reparaturplan aus einem Health-Report-dict (unveraendert)."""
    plan = RepairPlan(
        library_root=report.get("library", {}).get("root", ""),
        health_score=report.get("health", {}).get("score"),
    )
    seen_unmapped: set[str] = set()

    for issue in report.get("issues", []):
        code = issue.get("issue_code")
        spec = REGISTRY.get(code)
        if spec is None:
            if code and code not in seen_unmapped:
                seen_unmapped.add(code)
                plan.unmapped_issue_codes.append(code)
            continue
        plan.candidates.append(RepairCandidate(
            issue_code=code,
            action=spec.action,
            level=spec.level,
            severity=issue.get("severity", ""),
            scope=issue.get("scope", ""),
            path=issue.get("path"),
            artist=issue.get("artist"),
            album=issue.get("album"),
            title=issue.get("title"),
            related_files=list(issue.get("related_files") or []),
            reuses_component=spec.reuses_component,
            requires_approval=spec.requires_approval,
            requires_external=spec.requires_external,
            is_destructive=spec.is_destructive,
            expected_change=spec.expected_change,
            issue_message=issue.get("message", ""),
        ))

    plan.candidates.sort(key=lambda c: c.sort_key())
    return plan


def filter_plan(
    plan: RepairPlan,
    *,
    artist: str | None = None,
    issue_code: str | None = None,
    severity: str | None = None,
    level: str | None = None,
) -> RepairPlan:
    """Gezielte Teilmenge (Prompt Abschnitt 19). Reine Filterung, keine
    Neubewertung."""
    def _keep(c: RepairCandidate) -> bool:
        if artist and (c.artist or "").lower() != artist.lower() \
                and not (c.path or "").lower().startswith(f"{artist.lower()}/"):
            return False
        if issue_code and c.issue_code != issue_code:
            return False
        if severity and c.severity.upper() != severity.upper():
            return False
        if level and c.level.value.upper() != level.upper():
            return False
        return True

    out = RepairPlan(library_root=plan.library_root, health_score=plan.health_score,
                     unmapped_issue_codes=list(plan.unmapped_issue_codes))
    out.candidates = [c for c in plan.candidates if _keep(c)]
    return out


def registry_covers_all_health_codes() -> tuple[bool, set[str]]:
    """Fuer Tests: jeder Health-Issue-Code MUSS eine Repair-Zuordnung haben."""
    missing = set(_HEALTH_CODES) - set(REGISTRY)
    return (not missing, missing)
