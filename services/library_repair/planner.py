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
  EXTERNAL_METADATA     -> services/clients/musicbrainz_client.py::MusicBrainzClient
  COVER                 -> services/metadata/cover_processor.py::CoverProcessor
  LOUDNESS              -> services/library_repair/replaygain_repairs.py
                          (verlustfreier ReplayGain-Tag, kein Re-Encode)
  DUPLICATE             -> scripts/resolve_duplicates.py (+ services/duplicate/*)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
#
# CC-LIB-FINAL: Die frueher hier registrierte Stufe METADATA_REPROCESSING
# (L2, volle Pipeline erneut auf Bestandsdateien via track_reprocessor.
# process_file) wurde ersatzlos entfernt — sie haette manuell gesetzte
# Artist-/Titel-/Album-/Genre-Tags durch eine Neuableitung ueberschreiben
# koennen. Sieben der zehn davon betroffenen Issue-Codes (META_ARTIST/
# TITLE/ALBUM/GENRE_MISSING, META_TITLE_NOT_CLEAN, GENRE_EMPTY/INVALID)
# sind jetzt MANUAL_REVIEW: sie bleiben als Findings sichtbar und werden
# ueber die kontextbezogenen Edit-Aktionen des Control Centers
# (services/library_repair/maintenance_service.py) behoben. Die restlichen
# drei (LYRICS_MISSING/EMPTY/INVALID) sind NOT_REPAIRABLE, nicht
# MANUAL_REVIEW (Nutzer-Entscheidung 2026-09-27, Web-Parity-Audit §7/8):
# MANUAL_REVIEW darf nur vergeben werden, wenn es im Control Center eine
# konkrete Behebungs-Aktion gibt — der Metadata-Workspace (CC-LIB-FINAL
# Polish, #324) hat Tabs fuer Artist/Titel/Album/Albuminterpret/Genre,
# aber keinen Lyrics-Editor. Bleibt so, bis ein Lyrics-Editor als eigene
# Funktion beschlossen wird.
# ─────────────────────────────────────────────────────────────────────────

_SPECS: tuple[RepairSpec, ...] = (
    # ── Metadata ────────────────────────────────────────────────────────
    _spec("META_NOT_ANALYZABLE", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW,
          "-", approval=True, change="Tag-Container defekt — manuell pruefen / neu laden"),
    _spec("META_ARTIST_MISSING", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Artist-Tag fehlt — im Control Center ueber 'Artist bearbeiten' setzen"),
    _spec("META_TITLE_MISSING", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Titel-Tag fehlt — im Control Center ueber 'Titel bearbeiten' setzen"),
    _spec("META_TITLE_NOT_CLEAN", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Titel enthaelt Anfuehrungszeichen/prod.-Credit/Marketing-Suffix — "
                 "im Control Center ueber 'Titel bearbeiten' bereinigen"),
    _spec("META_ALBUM_MISSING", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Album-Tag fehlt — im Control Center ueber 'Album bearbeiten' setzen"),
    _spec("META_ALBUM_ARTIST_MISSING", _A.MULTI_ARTIST_SPLIT, _L.SAFE_AUTOMATIC,
          "TagWriter", approval=False,
          change="Album-Artist = Haupt-Artist des Tracks (deterministisch)"),
    # Production-Audit 2026-09-08: hier stand vorher EXTERNAL_METADATA /
    # "MusicBrainzClient" — es existiert aber in keinem Modul ein
    # Jahr-Fetch (die Pipeline uebernahm "year" nachweislich nur als
    # Passthrough des bereits vorhandenen Tags, rief dafuer nie
    # MusicBrainz auf). Der Planner
    # kuendigte damit eine Reparatur an, die kein Executor je ausfuehren
    # konnte (0 reale Kandidaten seit Einfuehrung). MANUAL_REVIEW ist
    # ausserdem konsistent zum direkten Nachbarn META_YEAR_INVALID.
    _spec("META_YEAR_MISSING", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Jahr fehlt — keine Fetch-Implementierung vorhanden, manuell nachtragen"),
    _spec("META_YEAR_INVALID", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Jahr-Tag ist unplausibel — manuell korrigieren"),
    # Production-Audit 2026-09-08: von EXTERNAL_METADATA verschoben (kein
    # Executor dafuer, external_metadata.py deckt nur MusicBrainz-ID-/ISRC-
    # Codes ab). CC-LIB-FINAL: jetzt MANUAL_REVIEW (siehe Registry-Kommentar).
    _spec("META_GENRE_MISSING", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Genre fehlt — im Control Center ueber Genre-Mapping / "
                 "'Genre setzen' des Artists nachtragen"),
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
    # CC-LIB-FINAL: kein automatischer Lyrics-Fetch mehr (fruehere L2-
    # Neuverarbeitung entfernt); Lyrics werden beim Download gesetzt.
    # NOT_REPAIRABLE statt MANUAL_REVIEW (Nutzer-Entscheidung 2026-09-27):
    # der Metadata-Workspace hat keinen Lyrics-Editor, also gibt es aktuell
    # keine Aktion, die der Nutzer im Control Center ausfuehren koennte.
    # Kein Lyrics-UI/-Fachlogik-Aufbau im Rahmen dieser Entscheidung — nur
    # falls ein eigener Lyrics-Editor kuenftig beschlossen wird, aendert
    # sich das wieder.
    _spec("LYRICS_MISSING", _A.NONE, _L.NOT_REPAIRABLE, "-", approval=False,
          change="Lyrics fehlen — kein automatischer Nachtrag, kein Lyrics-Editor im Control Center"),
    _spec("LYRICS_EMPTY", _A.NONE, _L.NOT_REPAIRABLE, "-", approval=False,
          change="Lyrics-Tag leer — kein automatischer Nachtrag, kein Lyrics-Editor im Control Center"),
    _spec("LYRICS_INVALID", _A.NONE, _L.NOT_REPAIRABLE, "-", approval=False,
          change="Lyrics-Tag ungueltig — kein automatischer Nachtrag, kein Lyrics-Editor im Control Center"),

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
    # Production-Audit 2026-09-08: expected_change praezisiert — real >85%
    # Skip-Rate, weil rename_repairs.py bewusst NUR rein additive
    # Abweichungen (Klammerzusatz/prod.-Credit) sicher umbenennt. Der Plan
    # ist weiterhin korrekt SAFE_AUTOMATIC (kein Risiko fuer Audio/Library
    # bei Ausfuehrung), aber "actionable" bedeutete bisher irrefuehrend
    # "wird ausgefuehrt" statt "wird sicher geprueft, ggf. SKIPPED".
    _spec("FILENAME_TITLE_MISMATCH", _A.FILENAME_RENAME_IN_PLACE, _L.SAFE_AUTOMATIC,
          "rename_repairs.repair_filename_title_mismatch()", approval=False,
          change="Dateiname aus Titel-Tag neu bilden (nur im selben Verzeichnis) — "
                 "wird NUR bei rein additiven Abweichungen (Klammerzusatz/prod.-Credit) "
                 "tatsaechlich umbenannt; bei abweichendem Titeltext bleibt es "
                 "sicherheitshalber bei SKIPPED (kein sicherer neuer Name)"),
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
    # Dieselbe Einstufung wie META_GENRE_MISSING oben (CC-LIB-FINAL).
    _spec("GENRE_EMPTY", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Genre-Tag leer — im Control Center ueber Genre-Mapping / "
                 "'Genre setzen' des Artists nachtragen"),
    _spec("GENRE_INVALID", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="Genre ausserhalb der Konvention — im Control Center ueber "
                 "Genre-Mapping / 'Genre setzen' des Artists korrigieren"),
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
    # Production-Audit 2026-09-08: hier stand vorher EXTERNAL_METADATA. Anders
    # als bei den MB_*_MISSING-Codes stehen hier bereits MEHRERE, jeweils
    # NICHT-leere Release-IDs im Album (kein Fall von "Feld ist leer,
    # ergaenze es"). external_metadata.py::plan_id_writes() hat als
    # Grundregel bewusst "kein blindes Ueberschreiben, nur fehlende Felder" —
    # eine album-weite Vereinheitlichung muesste dagegen bereits vorhandene
    # Werte GEZIELT ueberschreiben und selbst entscheiden, welche der N
    # vorhandenen IDs die kanonische ist. Das ist keine kleine Erweiterung
    # der bestehenden Fill-Logik, sondern eine neue Entscheidungsregel mit
    # eigenem Sicherheitsmodell — analog zu den bereits MANUAL_REVIEW
    # eingestuften Nachbarn ALBUM_YEAR_INCONSISTENT/ALBUM_NAME_INCONSISTENT
    # (identisches Muster: "welcher von mehreren bereits vorhandenen Werten
    # ist korrekt?" ist nicht sicher automatisierbar).
    _spec("ALBUM_RELEASE_ID_INCONSISTENT", _A.MANUAL_REVIEW, _L.MANUAL_REVIEW, "-",
          change="mehrere Release-IDs im Album — welche kanonisch ist, manuell entscheiden"),
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


# ─────────────────────────────────────────────────────────────────────────
# Disposition (Library-Closure-Phase, Auftrag Abschnitt 4/5): die sieben
# internen RepairLevel-Stufen rollen auf genau EINE von drei Grob-
# Dispositionen hoch. Der Planner bleibt die Single Source of Truth — die
# Disposition wird ausschliesslich aus dem bereits vorhandenen
# RepairSpec.level abgeleitet, nicht separat gepflegt.
#
#   AUTO_REPAIR   — es existiert ein Executor (verlustfrei ODER extern/
#                   destruktiv mit Freigabe). Ob der Weg ueber Telegram
#                   erreichbar ist, sagt erst filter_plan(level=...)/
#                   get_safe_automatic_candidates() — nicht die Disposition.
#   MANUAL_REVIEW  — kein sicherer automatischer Pfad, Nutzer entscheidet.
#   UNREPAIRABLE   — legitime Beobachtung, es gibt bewusst nichts zu tun.
# ─────────────────────────────────────────────────────────────────────────

DISPOSITION_AUTO_REPAIR = "AUTO_REPAIR"
DISPOSITION_MANUAL_REVIEW = "MANUAL_REVIEW"
DISPOSITION_UNREPAIRABLE = "UNREPAIRABLE"

_LEVEL_DISPOSITION: dict[RepairLevel, str] = {
    RepairLevel.SAFE_AUTOMATIC: DISPOSITION_AUTO_REPAIR,
    RepairLevel.EXTERNAL_METADATA: DISPOSITION_AUTO_REPAIR,
    RepairLevel.COVER: DISPOSITION_AUTO_REPAIR,
    RepairLevel.LOUDNESS: DISPOSITION_AUTO_REPAIR,
    RepairLevel.DUPLICATE: DISPOSITION_AUTO_REPAIR,
    RepairLevel.MANUAL_REVIEW: DISPOSITION_MANUAL_REVIEW,
    RepairLevel.NOT_REPAIRABLE: DISPOSITION_UNREPAIRABLE,
}


def disposition_for_level(level: RepairLevel) -> str:
    """RepairLevel -> Grob-Disposition. Wirft KeyError bei einem neuen,
    hier nicht eingeordneten Level (bewusst kein stiller Default — ein
    neues Level muss hier explizit klassifiziert werden)."""
    return _LEVEL_DISPOSITION[level]


def disposition_for_code(issue_code: str) -> str | None:
    """Health-Issue-Code -> Grob-Disposition, oder None fuer einen Code
    ohne Registry-Eintrag (den es laut registry_covers_all_health_codes()
    nicht geben darf)."""
    spec = REGISTRY.get(issue_code)
    return disposition_for_level(spec.level) if spec is not None else None


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


# ─────────────────────────────────────────────────────────────────────────
# Artist-Gruppierung fuer die Telegram-Pro-Artist-Auswahl (ARCH-033,
# ADR-0003) — reine Funktion, kein I/O. Bildet einen bereits vorhandenen
# RepairPlan auf "welcher Artist hat wie viele L3-Kandidaten" ab, fuer
# die Artist-Liste im Telegram-/Web-Sub-Flow (services/library_repair/
# level_summary.py wurde bewusst NICHT als eigenes Modul angelegt - die
# Funktion ist klein genug, um hier neben der Registry zu leben, die sie
# konsumiert).
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class ArtistCandidateSummary:
    """Aggregierte L3-Kandidaten-Anzahl (EXTERNAL_METADATA) fuer genau
    einen Artist. (Frueher zusaetzlich l2_count — L2 wurde in CC-LIB-FINAL
    entfernt.)"""

    artist: str
    l3_count: int = 0

    @property
    def total(self) -> int:
        return self.l3_count


def _candidate_artist(candidate: RepairCandidate) -> Optional[str]:
    """Liefert den Artist-Scope eines Kandidaten: bevorzugt das bereits
    vom Health-Scanner gesetzte `artist`-Feld, sonst das erste
    Pfadsegment (identische Fallback-Konvention wie
    executor.py::_directory_artist() und filter_plan()s eigener
    Pfad-Praefix-Abgleich oben)."""
    if candidate.artist:
        return candidate.artist
    if candidate.path:
        parts = Path(candidate.path).parts
        if len(parts) >= 2:
            return parts[0]
    return None


_ARTIST_GROUPING_LEVELS: tuple[RepairLevel, ...] = (
    RepairLevel.EXTERNAL_METADATA,
)


def group_candidates_by_artist(
    plan: RepairPlan,
    levels: tuple[RepairLevel, ...] = _ARTIST_GROUPING_LEVELS,
) -> dict[str, ArtistCandidateSummary]:
    """Gruppiert die Plan-Kandidaten der gegebenen Level (Default: L3)
    nach Artist, fuer die Telegram-/Web-Artist-Auswahl (ARCH-033).

    Deterministisch sortiert: absteigend nach Gesamt-Kandidaten-Anzahl,
    bei Gleichstand alphabetisch (case-insensitive) — Python-Dicts
    behalten Einfuegereihenfolge, das zurueckgegebene Dict ist daher
    bereits in Anzeige-Reihenfolge."""
    counts: dict[str, ArtistCandidateSummary] = {}
    for c in plan.candidates:
        if c.level not in levels:
            continue
        artist = _candidate_artist(c)
        if not artist:
            continue
        summary = counts.setdefault(artist, ArtistCandidateSummary(artist=artist))
        if c.level == RepairLevel.EXTERNAL_METADATA:
            summary.l3_count += 1

    ordered = sorted(counts.values(), key=lambda s: (-s.total, s.artist.lower()))
    return {s.artist: s for s in ordered}
