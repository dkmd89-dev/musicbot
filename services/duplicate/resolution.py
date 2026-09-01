# services/duplicate/resolution.py
# -*- coding: utf-8 -*-
"""
Duplicate Resolution Phase 1 — Resolution Engine.

Basis: docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md, Abschnitt 18,
Schritt 2. Erhält bereits erkannte Kandidaten-Gruppen (siehe
classification.py::group_candidates_by_identity()) und entscheidet
ausschließlich anhand der im Architecture Audit (Abschnitt 7/8/9/10/15)
festgelegten Decision Matrix. Keine Dateilöschung, keine Filesystem-
Mutation, keine Telegram-Logik, keine Cache-Änderung - reine Funktionen
auf bereits im Speicher vorhandenen Candidate-Objekten.

## Decision Matrix (Architecture Audit Abschnitt 9, wortgleich aus dem
Auftrag übernommen)

    ALBUM_LIKE + SINGLE      -> KEEP ALBUM,  REMOVE SINGLE als Vorschlag
    ALBUM_LIKE + ALBUM_LIKE  -> Tie-Breaker
    SINGLE + SINGLE          -> Tie-Breaker
    ALBUM_LIKE + AMBIGUOUS   -> ALBUM bevorzugen, AMBIGUOUS NICHT
                                 automatisch löschen, MANUAL REVIEW
    SINGLE + AMBIGUOUS       -> SINGLE bevorzugen, AMBIGUOUS NICHT
                                 automatisch löschen, MANUAL REVIEW
    AMBIGUOUS + AMBIGUOUS    -> KEEP_BOTH, MANUAL REVIEW

## N-Wege-Verallgemeinerung (E4-Entscheidung dieser Implementierung)

Die Mission-Matrix ist paarweise formuliert. Eine Gruppe kann aber mehr
als zwei Kandidaten enthalten (der reale Badchieff-Fall hat genau drei:
zwei SINGLE + ein ALBUM_LIKE). Verallgemeinerung, konservativ im Sinne
von "Safety > Cleanup Completeness" (Abschnitt 15 des Audits):

  - Enthält die Gruppe AUCH NUR EINEN AMBIGUOUS-Kandidaten, wird die
    GESAMTE Gruppe MANUAL_REVIEW (bzw. KEEP_BOTH, wenn ALLE Kandidaten
    AMBIGUOUS sind) - kein automatischer REMOVE-Vorschlag für irgendeinen
    Kandidaten dieser Gruppe, auch nicht für die eindeutig
    klassifizierten. Das ist die direkte, sicherheitsmaximierende
    Fortsetzung der paarweisen Regeln "X + AMBIGUOUS -> MANUAL REVIEW".
  - Sind ALLE Kandidaten eindeutig (SINGLE/ALBUM_LIKE, keine AMBIGUOUS):
    ist mindestens ein ALBUM_LIKE-Kandidat vorhanden, gewinnt dessen
    Kategorie (INV-D02); sonst gewinnt die SINGLE-Kategorie. Der
    Tie-Breaker (Abschnitt 7.1) bestimmt den EINEN Keep-Kandidaten
    innerhalb der Gewinner-Kategorie; alle anderen Kandidaten der Gruppe
    (auch Kandidaten der unterlegenen Kategorie) werden REMOVE-Vorschlag.

## Safety Gate (Architecture Audit Abschnitt 15 / Phase 2 Real Findings
## Audit)

Nur Kandidaten mit Confidence.HIGH dürfen je Teil eines REMOVE-Vorschlags
werden. Da classification.candidate_confidence() für AMBIGUOUS bereits
MEDIUM liefert, ist dieser Teil des Safety Gate durch die obige
Verallgemeinerung strukturell bereits erzwungen - es gibt keinen
Codepfad, der einen MEDIUM/UNKNOWN-Kandidaten in remove_proposals
aufnimmt.

## Phase 2 — Evidence Safety Gate (Real Findings Audit)

Confidence.HIGH ("Artist+Titel identisch + eindeutige Pfadklassifikation")
ist eine notwendige, aber laut dem realen "Nachts wach"-Fund (Phase 1.1
Real Findings Audit) NICHT hinreichende Bedingung für einen automatischen
REMOVE-Vorschlag. _evaluate_safety_gate() prüft für jeden tentativen
REMOVE-Kandidaten gegen den tentativen KEEP-Kandidaten zusätzlich vier
unabhängige Regeln (jede für sich blockierend, Auftrag Phase 2 Abschnitt
7 - wortgleich; Regel 2b ergänzt in Phase 2.3):

    Duration deutlich unterschiedlich (> DURATION_CONSISTENT_TOLERANCE_
    SECONDS, siehe classification.py) + keine starke Identitätsbestätigung
    (weder MusicBrainz Recording ID noch ISRC stimmen überein)
        -> BLOCKED

    unterschiedliche MusicBrainz Recording IDs (beide vorhanden, aber
    verschieden) - unbedingt, unabhängig von allen anderen Signalen
        -> BLOCKED

    unterschiedliche ISRC (beide vorhanden, aber verschieden) - unbedingt,
    unabhängig von allen anderen Signalen (Phase 2.3, Identity &
    Classification Robustness Audit: ISRC ist laut
    has_strong_identity_confirmation() ein zur MusicBrainz Recording ID
    GLEICHWERTIGES Identitätssignal - ein Widerspruch muss daher
    symmetrisch behandelt werden. Vor diesem Fix konnte ein reiner
    ISRC-Mismatch bei sonst konsistenter Duration und ohne Album-Risk-
    Kontext einen automatischen REMOVE-Vorschlag NICHT verhindern -
    nachgewiesener False-Positive-Vektor, siehe
    tests/test_duplicate_isrc_mismatch_safety_gate.py)
        -> BLOCKED

    Album-Name deutet auf Remix-/Live-/Versions-Kontext hin + keine
    starke Identitätsbestätigung
        -> BLOCKED

Blockiert IRGENDEIN Kandidat der Gruppe, wird die GESAMTE Gruppe
MANUAL_REVIEW (dieselbe konservative N-Wege-Philosophie wie beim
bestehenden AMBIGUOUS-Handling oben - "Safety > Cleanup Completeness").
Fehlende Evidenz (Duration/MB-ID/ISRC auf einer oder beiden Seiten nicht
verfügbar) blockiert NICHT von sich aus - sonst wäre der reale
"Pueblo"-Fall (kein MB-ID vorhanden) nicht mehr auflösbar, obwohl er ein
korrektes Duplikat ist (Auftrag Phase 2 Abschnitt 4/10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import cmp_to_key
from typing import List, Optional

from services.duplicate.classification import (
    Candidate,
    Classification,
    Confidence,
    candidate_confidence,
    compare_isrc_identity,
    compare_recording_identity_ids,
    has_album_context_risk,
    has_strong_identity_confirmation,
    is_duration_consistent,
)


class GroupAction(str, Enum):
    NO_DUPLICATE = "NO_DUPLICATE"
    RESOLVED = "RESOLVED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    KEEP_BOTH = "KEEP_BOTH"


@dataclass
class CandidateEvidence:
    """Safety-Gate-Evidenz für EIN (keep, remove-Kandidat)-Paar (Phase 2,
    Auftrag Abschnitt 6/13). Rein informativ + Grundlage der
    blocked-Entscheidung - keine Mutation, keine I/O."""

    candidate: Candidate
    artist_title_match: bool
    duration_consistent: Optional[bool]
    duration_delta_seconds: Optional[float]
    musicbrainz_match: Optional[bool]
    isrc_match: Optional[bool]
    album_context_risk: bool
    strong_identity_confirmed: bool
    blocked: bool
    block_reasons: List[str]


@dataclass
class ResolutionDecision:
    normalized_artist: str
    normalized_title: str
    candidates: List[Candidate]
    keep: Optional[Candidate]
    remove_proposals: List[Candidate]
    action: GroupAction
    reason: str
    evidence: List[CandidateEvidence] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────
# Tie-Breaker (Architecture Audit Abschnitt 7.1 / Auftrag Abschnitt 10-12)
#
#   1. vollständigere Metadaten (METADATA_COMPLETENESS_FIELDS-Zähler)
#   2. höhere Audioqualität (Bitrate) - NUR wenn beide Kandidaten eine
#      bekannte Bitrate haben; ist bei einem/beiden None, wird dieser
#      Vergleich übersprungen (kein künstliches Bevorzugen), Auftrag
#      Abschnitt 11
#   3. kein "(N)"-Collision-Suffix
#   4. lexikographisch kleinster vollständiger POSIX-Pfad (finaler,
#      immer eindeutiger Tie-Breaker - zwei verschiedene Dateien haben
#      nie denselben Pfad-String)
#
# Als Comparator (nicht als einzelner Sort-Key) implementiert, weil Stufe
# 2 bei unbekannter Bitrate übersprungen werden MUSS statt einen
# Platzhalterwert einzusetzen - ein einzelner Tupel-Sort-Key könnte
# "unbekannt" nicht von "schlechtester bekannter Wert" unterscheiden.
# min() mit cmp_to_key() ist unabhängig von der Eingabereihenfolge
# (INV-D03/Auftrag Abschnitt 13) - das Ergebnis hängt ausschließlich von
# den Candidate-Daten ab, nie von Scan-/Dict-/Thread-Reihenfolge.
# ─────────────────────────────────────────────────────────────────────────


def _compare_candidates(a: Candidate, b: Candidate) -> int:
    """Gibt -1 zurück, wenn a besser ist (gewinnt), 1 wenn b besser ist,
    0 nur bei vollständiger Gleichheit (in der Praxis durch Stufe 4 nie
    erreicht, da zwei unterschiedliche Dateien nie denselben Pfad-String
    haben)."""
    # Stufe 1: Metadaten-Vollständigkeit (höher gewinnt)
    if a.metadata_completeness != b.metadata_completeness:
        return -1 if a.metadata_completeness > b.metadata_completeness else 1

    # Stufe 2: Bitrate (höher gewinnt) - nur wenn beide bekannt
    if a.bitrate is not None and b.bitrate is not None and a.bitrate != b.bitrate:
        return -1 if a.bitrate > b.bitrate else 1

    # Stufe 3: kein Collision-Suffix gewinnt
    if a.collision_suffix != b.collision_suffix:
        return -1 if not a.collision_suffix else 1

    # Stufe 4: lexikographisch kleinster vollständiger POSIX-Pfad
    a_path = a.path.as_posix()
    b_path = b.path.as_posix()
    if a_path != b_path:
        return -1 if a_path < b_path else 1
    return 0


def _pick_winner(candidates: List[Candidate]) -> Candidate:
    """Deterministisch, reihenfolge-unabhängig (min() über einen
    vollständigen, per _compare_candidates definierten Comparator)."""
    return min(candidates, key=cmp_to_key(_compare_candidates))


# ─────────────────────────────────────────────────────────────────────────
# Phase 2 — Evidence Safety Gate (siehe Modul-Docstring)
# ─────────────────────────────────────────────────────────────────────────


def _evaluate_safety_gate(keep: Candidate, candidate: Candidate) -> CandidateEvidence:
    """Wertet die drei Blocking-Regeln (Modul-Docstring) für EIN
    (keep, candidate)-Paar aus. Reine Funktion, keine Mutation."""
    duration_consistent = is_duration_consistent(keep, candidate)
    duration_delta_seconds = (
        abs(keep.duration_seconds - candidate.duration_seconds)
        if keep.duration_seconds is not None and candidate.duration_seconds is not None
        else None
    )
    musicbrainz_match = compare_recording_identity_ids(keep, candidate)
    isrc_match = compare_isrc_identity(keep, candidate)
    album_context_risk = has_album_context_risk(keep.album) or has_album_context_risk(
        candidate.album
    )
    strong_identity_confirmed = has_strong_identity_confirmation(keep, candidate)

    block_reasons: List[str] = []
    if duration_consistent is False and not strong_identity_confirmed:
        block_reasons.append(
            "Duration-Abweichung ohne starke Identitätsbestätigung "
            f"(Δ{duration_delta_seconds:.6f}s)"
        )
    if musicbrainz_match is False:
        block_reasons.append("unterschiedliche MusicBrainz Recording IDs")
    if isrc_match is False:
        # Phase 2.3 (Identity & Classification Robustness Audit): ISRC ist
        # laut Modul-Docstring/classification.py::has_strong_identity_
        # confirmation() ein zur MusicBrainz Recording ID GLEICHWERTIGES
        # Industriestandard-Identitätssignal - ein Widerspruch muss daher
        # symmetrisch zur MB-ID-Regel unbedingt blockieren, unabhängig von
        # allen anderen Signalen. Vor diesem Fix konnte ein reiner
        # ISRC-Mismatch (bei sonst konsistenter Duration, ohne Album-Risk-
        # Kontext) einen automatischen REMOVE-Vorschlag NICHT verhindern -
        # nachgewiesener, reproduzierbarer False-Positive-Vektor (Audit
        # Case E), siehe tests/test_duplicate_isrc_mismatch_safety_gate.py.
        block_reasons.append("unterschiedliche ISRC")
    if album_context_risk and not strong_identity_confirmed:
        block_reasons.append(
            "Remix/Live/Version-Album-Kontext ohne starke Identitätsbestätigung"
        )

    return CandidateEvidence(
        candidate=candidate,
        artist_title_match=True,  # Gruppe ist bereits per Identität gruppiert
        duration_consistent=duration_consistent,
        duration_delta_seconds=duration_delta_seconds,
        musicbrainz_match=musicbrainz_match,
        isrc_match=isrc_match,
        album_context_risk=album_context_risk,
        strong_identity_confirmed=strong_identity_confirmed,
        blocked=bool(block_reasons),
        block_reasons=block_reasons,
    )


# ─────────────────────────────────────────────────────────────────────────
# Resolution Engine
# ─────────────────────────────────────────────────────────────────────────


def resolve_group(candidates: List[Candidate]) -> ResolutionDecision:
    """
    Entscheidet über eine bereits nach Identität gruppierte Kandidaten-
    Liste (siehe classification.group_candidates_by_identity()).

    Erwartet, dass alle candidates dieselbe (normalized_artist,
    normalized_title)-Identität teilen (Aufrufer-Verantwortung - wird
    hier nicht erneut geprüft, da group_candidates_by_identity() das
    bereits garantiert).
    """
    if len(candidates) < 2:
        # INV-D01-Äquivalent (Architecture Audit) / Auftrag Abschnitt 16:
        # niemals eine Aktion bei einer Gruppe mit nur einem Kandidaten.
        na = candidates[0].normalized_artist if candidates else ""
        nt = candidates[0].normalized_title if candidates else ""
        return ResolutionDecision(
            normalized_artist=na,
            normalized_title=nt,
            candidates=list(candidates),
            keep=None,
            remove_proposals=[],
            action=GroupAction.NO_DUPLICATE,
            reason="nur ein Kandidat - kein Duplicate-Fall",
        )

    normalized_artist = candidates[0].normalized_artist
    normalized_title = candidates[0].normalized_title

    high_conf = [c for c in candidates if candidate_confidence(c) == Confidence.HIGH]
    non_high = [c for c in candidates if candidate_confidence(c) != Confidence.HIGH]

    if not high_conf:
        # Alle Kandidaten AMBIGUOUS (oder UNKNOWN - sollte durch
        # group_candidates_by_identity() bereits ausgeschlossen sein,
        # hier defensiv trotzdem korrekt behandelt).
        return ResolutionDecision(
            normalized_artist=normalized_artist,
            normalized_title=normalized_title,
            candidates=list(candidates),
            keep=None,
            remove_proposals=[],
            action=GroupAction.KEEP_BOTH,
            reason="alle Kandidaten AMBIGUOUS - keine automatische Entscheidung möglich",
        )

    if non_high:
        # Gemischt: mindestens ein eindeutiger + mindestens ein
        # AMBIGUOUS-Kandidat. Safety Gate (Abschnitt 15): kein
        # REMOVE-Vorschlag für die gesamte Gruppe.
        album_likes = [c for c in high_conf if c.classification == Classification.ALBUM_LIKE]
        preferred_category = "ALBUM_LIKE" if album_likes else "SINGLE"
        return ResolutionDecision(
            normalized_artist=normalized_artist,
            normalized_title=normalized_title,
            candidates=list(candidates),
            keep=None,
            remove_proposals=[],
            action=GroupAction.MANUAL_REVIEW,
            reason=(
                f"{preferred_category} würde bevorzugt, aber Gruppe enthält "
                f"{len(non_high)} AMBIGUOUS-Kandidat(en) - keine automatische Aktion"
            ),
        )

    # Alle Kandidaten HIGH-Confidence (SINGLE/ALBUM_LIKE, keine AMBIGUOUS).
    album_likes = [c for c in high_conf if c.classification == Classification.ALBUM_LIKE]
    singles = [c for c in high_conf if c.classification == Classification.SINGLE]

    if album_likes:
        winner_pool = album_likes
        reason = (
            "ALBUM_LIKE > SINGLE"
            if singles
            else "ALBUM_LIKE Tie-Breaker (mehrere Album-Kandidaten)"
        )
    else:
        winner_pool = singles
        reason = "SINGLE Tie-Breaker (mehrere Single-Kandidaten)"

    keep = _pick_winner(winner_pool)
    tentative_remove = [c for c in high_conf if c is not keep]

    # Phase 2 Safety Gate (Modul-Docstring): jeder tentative REMOVE-
    # Kandidat wird einzeln gegen keep geprüft. Blockiert IRGENDEINER,
    # wird die GESAMTE Gruppe MANUAL_REVIEW - kein automatischer
    # REMOVE-Vorschlag für irgendeinen Kandidaten dieser Gruppe.
    evidence = [_evaluate_safety_gate(keep, c) for c in tentative_remove]
    blocked_evidence = [e for e in evidence if e.blocked]

    if blocked_evidence:
        all_reasons = []
        for e in blocked_evidence:
            for r in e.block_reasons:
                if r not in all_reasons:
                    all_reasons.append(r)
        return ResolutionDecision(
            normalized_artist=normalized_artist,
            normalized_title=normalized_title,
            candidates=list(candidates),
            keep=None,
            remove_proposals=[],
            action=GroupAction.MANUAL_REVIEW,
            reason="Safety Gate BLOCKED: " + "; ".join(all_reasons),
            evidence=evidence,
        )

    return ResolutionDecision(
        normalized_artist=normalized_artist,
        normalized_title=normalized_title,
        candidates=list(candidates),
        keep=keep,
        remove_proposals=tentative_remove,
        action=GroupAction.RESOLVED,
        reason=reason,
        evidence=evidence,
    )
