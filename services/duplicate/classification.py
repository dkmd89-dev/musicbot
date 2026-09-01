# services/duplicate/classification.py
# -*- coding: utf-8 -*-
r"""
Duplicate Resolution Phase 1 — Domain-Modelle + Album/Single-Klassifikation.

Basis: docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md, Abschnitt 18
(Implementation Boundary), Schritt 1. POST-DOWNLOAD/LIBRARY-Resolution -
komplett getrennt von services/duplicate/detector.py (PRE-DOWNLOAD
Prevention, siehe dortiger Modul-Docstring). detector.py/cache.py werden
hier NICHT importiert, NICHT verändert, NICHT erweitert.

Reine Domain-Logik: keine Telegram-Abhängigkeit, keine FFmpeg-Abhängigkeit,
kein Dateisystem-Scan innerhalb der Klassifikationsfunktion selbst, keine
globale mutable State.

## Album/Single-Klassifikation (Architecture Audit Abschnitt 6.4)

Primär über die Pfadstruktur, NICHT über den "©alb"-Tag-Inhalt (der reale
Badchieff-Testfall - siehe tests/test_duplicate_classification.py - belegt,
warum der Tag allein irreführend wäre: "GUT AUS" als Albumname ist dort nur
ein Selbsttitel-Platzhalter, inhaltlich nicht von einem echten Albumnamen
unterscheidbar). Die Pfadkonvention selbst ist keine neue Erfindung, sondern
bereits die Autorität, die utils/filenamefixer.py::build_final_path() beim
Schreiben der Library-Struktur verwendet (dort NICHT verändert, nur als
Erkennungssignal in Rückrichtung wiederverwendet).

## Duplicate Identity (Architecture Audit Abschnitt 5/7)

normalize_artist_for_identity()/normalize_title_for_identity() spiegeln
bewusst denselben Normalisierungs-VERTRAG wie
DuplicateDetector._normalize_artist_for_comparison()/
_clean_title_for_comparison() (services/duplicate/detector.py) - identischer
Input muss identischen Output ergeben wie im bestehenden Pre-Download-Pfad.
Keine Wiederverwendung durch direkten Aufruf möglich, da beide Methoden in
detector.py als Instanzmethoden an "self" (self.artist_normalizer,
self.logger) gebunden sind und detector.py laut Implementation Boundary
NICHT verändert werden darf (kein Extrahieren in freie Funktionen erlaubt).
_clean_title_for_comparison() selbst griff im Original nie auf "self" zu
(reine Funktion, nur als Instanzmethode deklariert) - hier bewusst als
eigenständige, dokumentierte Kapselung nachgebildet, NICHT neu erfunden:
exakt dieselbe patterns_to_remove-Liste, in derselben Reihenfolge.

WICHTIG (DUP-03, docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2J_DUP03_AUDIT.md):
die historisch entfernten, zu breiten Muster r"\(.*?Version\)", r"\(Live.*?\)",
r"\(Remix\)" werden hier bewusst NICHT wieder eingeführt - "Hello" und
"Hello (Live at Glastonbury 2016)" bleiben unterschiedliche normalisierte
Titel (konservativ: eher False Negative als ein wiederholter False Positive).

## Phase 2 — Safety-Gate-Evidenz (Real Findings Audit, Phase 1.1)

Phase 1.1 (reiner Audit, docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md
war zu diesem Zeitpunkt noch nicht um Phase 2 ergänzt) hat anhand der
echten Testbibliothek konkret belegt, dass "Artist+Titel identisch +
eindeutige Pfadklassifikation" allein NICHT ausreicht, um einen
automatischen REMOVE-Vorschlag zu rechtfertigen (realer Fund: makko -
"Nachts wach", zwei Tracks eines Remix-EPs mit identischem, aber
unbeschriftetem Titel, echte Duration-Abweichung 0.441s, echte
ReplayGain-Abweichung 2.36 dB, keine MusicBrainz Recording ID).

Die folgenden Funktionen liefern reine Evidenz-PRIMITIVEN (Vergleich von
je zwei bereits vollständig befüllten Candidate-Objekten) für die
eigentliche Safety-Gate-ENTSCHEIDUNG, die in resolution.py getroffen
wird (Trennung Evidenz-Extraktion vs. Entscheidungslogik, analog zur
bereits bestehenden Trennung Klassifikation vs. Resolution).

Bewusst NICHT als Blocking-Signal aufgenommen (Auftrag Abschnitt 6
erlaubt nur Artist+Title/Pfad/Duration/MusicBrainz-ID/Album-Kontext als
PFLICHTsignale, alles andere ist optional):

  - ReplayGain: kann sich bei DERSELBEN Aufnahme legitim ändern (siehe
    scripts/normalize_test_library_loudness.py, das LUFS/ReplayGain
    absichtlich neu berechnet) - ungeeignet als alleiniges
    Blocking-Signal, siehe tests/test_duplicate_resolution.py
    (Adversarial-Test J).
  - Audio-Stream-Parameter (Sample-Rate/Codec): der reale Badchieff-Fall
    beweist das Gegenteil einer Blocking-Eignung - zwei Kopien
    DERSELBEN Aufnahme (identische ISRC + MusicBrainz Recording ID)
    unterscheiden sich real in der Sample-Rate (48000 Hz vs. 44100 Hz,
    ein Resample fand irgendwann statt). Ein Sample-Rate-Vergleich als
    Blocking-Gate hätte hier fälschlich blockiert.
  - Cover-Hash: wird als rein INFORMATIVE unterstützende Evidenz geführt
    (Candidate.cover_sha256, Auftrag Abschnitt 11 Test K/L) - fließt
    NICHT in die Safety-Gate-Entscheidung ein, ein abweichendes Cover
    darf allein niemals eine automatische Auflösung verhindern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping, Optional


# ─────────────────────────────────────────────────────────────────────────
# Kategoriale Werte (Architecture Audit Abschnitt 4/14 - keine numerischen
# Scores, nur die dort definierten kategorialen Stufen)
# ─────────────────────────────────────────────────────────────────────────


class Classification(str, Enum):
    """Album/Single-Kategorie eines einzelnen Kandidaten (Pfad-basiert)."""

    ALBUM_LIKE = "ALBUM_LIKE"  # inkl. EP/Compilation, siehe Modul-Docstring
    SINGLE = "SINGLE"
    AMBIGUOUS = "AMBIGUOUS"


class Confidence(str, Enum):
    """
    Kategoriale Konfidenz der Identitäts-/Klassifikationsentscheidung
    (Architecture Audit Abschnitt 14). Keine numerischen Schwellenwerte.

    LOW ist in dieser Phase strukturell UNREACHABLE: LOW ist laut Audit nur
    dann zutreffend, wenn eine sekundäre/zusätzliche Normalisierung nötig
    war, um zwei Kandidaten überhaupt als identisch zu erkennen - diese
    Phase nutzt genau EINEN Normalisierungspfad (kein Fallback-Kaskade wie
    DuplicateDetector.check_for_duplicates()), daher gibt es keine
    "sekundäre" Normalisierungsstufe, die je erreicht würde. Der Wert
    bleibt Teil des Enums (vom Auftrag explizit als kategoriale Stufe
    verlangt), wird aber von keiner Funktion in diesem Modul je
    zurückgegeben - bewusst dokumentiert, nicht stillschweigend weggelassen.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────
# Album/Single-Klassifikation (Architecture Audit Abschnitt 6.4)
# ─────────────────────────────────────────────────────────────────────────

_ALBUM_LIKE_FOLDER_PATTERN = re.compile(r"^\d{4}\s*-\s*.+$")


def classify_by_path(path: Path) -> Classification:
    """
    Reine Funktion: Elternordner-Name -> Classification. Kein Dateisystem-
    Zugriff (kein .exists()/.stat()/.iterdir()) - operiert ausschließlich
    auf dem übergebenen Path-Objekt selbst, funktioniert daher identisch
    für real existierende UND rein synthetische (Test-)Pfade.

    Regel (Architecture Audit Abschnitt 6.4, wortgleich aus dem Auftrag):
        Elternordner == "Singles" (case-insensitive)          -> SINGLE
        Elternordner matcht ^\\d{4}\\s*-\\s*.+$ (Jahr-Bindestrich) -> ALBUM_LIKE
        alles andere                                            -> AMBIGUOUS
    """
    parent_name = path.parent.name
    if parent_name.strip().lower() == "singles":
        return Classification.SINGLE
    if _ALBUM_LIKE_FOLDER_PATTERN.match(parent_name.strip()):
        return Classification.ALBUM_LIKE
    return Classification.AMBIGUOUS


# ─────────────────────────────────────────────────────────────────────────
# Duplicate Identity - Normalisierung (Architecture Audit Abschnitt 5/7)
# ─────────────────────────────────────────────────────────────────────────

# Exakt dieselbe Liste, dieselbe Reihenfolge wie
# DuplicateDetector._clean_title_for_comparison() (services/duplicate/
# detector.py) - siehe Modul-Docstring fuer die Begruendung der Kapselung
# statt direkter Wiederverwendung.
_TITLE_STRIP_PATTERNS = [
    r"\(Official.*?\)",
    r"\[.*?\]",
    r"\(feat(?:\.\s*|uring\s*|\s+).*?\)",
    r"\(ft(?:\.\s*|\s+).*?\)",
]

_ARTIST_SUFFIXES_TO_STRIP = [" - Topic", " VEVO", " Official"]

# Phase 2.2 (False-Negative-Fix, Real Findings Audit Phase 2.1): reale
# Bibliothek zeigt inkonsistent gesetzte, den GESAMTEN Titel umschließende
# Anführungszeichen zwischen zwei Kopien derselben Aufnahme (Single-Tag
# '"Bequem"' vs. Album-Tag 'Bequem', beide mit identischer MusicBrainz
# Recording ID bestätigt) - ohne Fix bilden diese nie eine gemeinsame
# Duplicate-Gruppe (False Negative, kein Safety-Risiko, aber eine
# Vollständigkeitslücke).
#
# NUR ein vollständig umschließendes, zusammenpassendes Anführungszeichen-
# PAAR wird entfernt (erstes UND letztes Zeichen müssen matchen) - bewusst
# KEIN Entfernen einzelner/unpaariger Anführungszeichen oder interner
# Apostrophe (z. B. "Rock 'n' Roll" bleibt unverändert, da weder erstes
# noch letztes Zeichen ein Anführungszeichen ist). Bestehende Live/Remix/
# Version-Regeln (DUP-03) werden dadurch nicht berührt - diese Funktion
# läuft als letzter, unabhängiger Schritt NACH den bestehenden
# _TITLE_STRIP_PATTERNS.
# Explizite \uXXXX-Escapes statt Literalzeichen im Quellcode - vermeidet
# jede Mehrdeutigkeit zwischen visuell ähnlichen Anführungszeichen-
# Codepoints (z. B. U+201C vs. U+201D vs. U+201E).
_TITLE_QUOTE_PAIRS = (
    ("\u0022", "\u0022"),  # straight double quote, U+0022
    ("'", "'"),  # '...'  (straight single, U+0027)
    ("„", "“"),  # „...“  (deutsche Konvention: U+201E ... U+201C)
    ("“", "”"),  # "..."  (englische Konvention: U+201C ... U+201D)
    ("‘", "’"),  # '...'  (englische Konvention: U+2018 ... U+2019)
)


def _strip_wrapping_quote_pair(text: str) -> str:
    """Entfernt GENAU EIN äußeres, vollständig umschließendes und
    zusammenpassendes Anführungszeichen-Paar (Auftrag Phase 2.2
    Abschnitt 3). Bleibt bei fehlendem/unpaarigem Quote-Zeichen sowie bei
    einem nach dem Strip leeren Ergebnis unverändert (defensiv - ein
    Titel, der NUR aus Anführungszeichen besteht, ist kein plausibler
    Anwendungsfall dieser Regel)."""
    if len(text) < 2:
        return text
    for open_q, close_q in _TITLE_QUOTE_PAIRS:
        if text[0] == open_q and text[-1] == close_q:
            inner = text[1:-1].strip()
            return inner if inner else text
    return text


def normalize_artist_for_identity(
    artist: Optional[str], artist_normalizer: Optional[object] = None
) -> str:
    """
    Spiegelt DuplicateDetector._normalize_artist_for_comparison() (siehe
    Modul-Docstring). `artist_normalizer` ist optional injizierbar (z. B.
    eine echte utils.artist_map.ArtistNormalizer-Instanz) - ohne
    Normalizer greift derselbe simple Suffix-Strip-Fallback wie im
    Original.
    """
    if not artist:
        return "Unknown"
    if artist_normalizer is not None:
        try:
            normalized = artist_normalizer.normalize(artist)
            if normalized and normalized.lower() != "unknown":
                return normalized
        except Exception:
            pass
    cleaned = artist.strip()
    for suffix in _ARTIST_SUFFIXES_TO_STRIP:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
    return cleaned if cleaned else "Unknown"


def normalize_title_for_identity(title: Optional[str], artist: Optional[str] = None) -> str:
    """Spiegelt DuplicateDetector._clean_title_for_comparison() (siehe
    Modul-Docstring) - inklusive des DUP-03-Fixes (keine Live/Version/
    Remix-Entfernung). Phase 2.2: letzter, unabhängiger Schritt entfernt
    ein umschließendes Anführungszeichen-Paar (siehe
    _strip_wrapping_quote_pair()) - False-Negative-Fix aus dem Real
    Findings Audit Phase 2.1, berührt DUP-03 nicht."""
    if not title:
        return "Unknown"
    cleaned = title.strip()
    if artist and artist.lower() in cleaned.lower():
        for pattern in [f"{artist} - ", f"{artist} – ", f"{artist}: ", f"{artist} | "]:
            if cleaned.lower().startswith(pattern.lower()):
                cleaned = cleaned[len(pattern):].strip()
                break
    for pattern in _TITLE_STRIP_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _strip_wrapping_quote_pair(cleaned)
    return cleaned if cleaned else "Unknown"


# ─────────────────────────────────────────────────────────────────────────
# Metadata-Vollständigkeit (Architecture Audit / Auftrag Abschnitt 10)
# Festes, dokumentiertes Feldset - KEIN dynamisches Zählen beliebiger Tags.
# ─────────────────────────────────────────────────────────────────────────

METADATA_COMPLETENESS_FIELDS = (
    "artist",
    "title",
    "album",
    "album_artist",
    "year",
    "genre",
    "track_number",
    "mb_recording_id",
    "mb_artist_id",
    "mb_release_id",
    "isrc",
    "lyrics_present",
    "cover_present",
)


def compute_metadata_completeness(fields: Mapping[str, object]) -> int:
    """Zählt, wie viele der METADATA_COMPLETENESS_FIELDS in `fields`
    einen "wahren"/nicht-leeren Wert haben. `fields` ist ein bereits vom
    Aufrufer (I/O-Schicht, z. B. scripts/resolve_duplicates.py) gelesenes
    Mapping - diese Funktion selbst liest keine Datei."""
    count = 0
    for key in METADATA_COMPLETENESS_FIELDS:
        value = fields.get(key)
        if isinstance(value, bool):
            if value:
                count += 1
        elif value not in (None, "", 0):
            count += 1
    return count


# ─────────────────────────────────────────────────────────────────────────
# Collision-Suffix-Erkennung (Architecture Audit Abschnitt 7.1 Stufe 3 /
# Auftrag Abschnitt 12) - utils/filenamefixer.py::move_to_library() haengt
# " (N)" an den Dateinamen-Stamm an, NICHT an die Endung. Nur die bereits
# bestehende Konvention erkannt, keine neue erfunden.
# ─────────────────────────────────────────────────────────────────────────

_COLLISION_SUFFIX_PATTERN = re.compile(r" \(\d+\)$")


def has_collision_suffix(path: Path) -> bool:
    """Pure Funktion: prüft nur den Dateinamen-Stamm auf das " (N)"-Muster,
    kein Dateisystem-Zugriff."""
    return bool(_COLLISION_SUFFIX_PATTERN.search(path.stem))


# ─────────────────────────────────────────────────────────────────────────
# Safety-Gate-Evidenz-Primitiven (Phase 2, siehe Modul-Docstring)
# ─────────────────────────────────────────────────────────────────────────

# Toleranz für "Duration praktisch identisch" (Auftrag Phase 2 Abschnitt 3).
#
# Herleitung (keine willkürliche Wahl):
#   - AAC-Frame-Größe: 1024 Samples / 44100 Hz ≈ 23 ms. Encoder-Priming/
#     -Padding-Differenzen zwischen zwei Encodes DERSELBEN Aufnahme liegen
#     typischerweise im Bereich weniger Frames (~2-4, also ~50-90 ms),
#     auch über unterschiedliche Sample-Raten hinweg (siehe Badchieff-
#     Fund unten).
#   - Bereits im Repository etabliertes Vorbild: DURATION_WARN_SECONDS =
#     2.0 (scripts/normalize_test_library_loudness.py) - dieser Wert ist
#     jedoch für einen ANDEREN Zweck kalibriert (Re-Encode DERSELBEN
#     Datei an Ort und Stelle, großzügige Warn-Schwelle) und wäre hier
#     ungeeignet: 2.0s hätte den realen Nachts-wach-Fund (0.441s
#     Abweichung) NICHT erkannt.
#   - Empirisch bestätigt an den drei real vorgefundenen Duplicate-
#     Gruppen der Testbibliothek (Phase 1.1 Real Findings Audit):
#       * makko / Dein Lügner (Album vs. Single): Δ ≈ 0.000s  -> PASS
#       * makko / Pueblo       (Album vs. Single): Δ ≈ 0.000s  -> PASS
#       * Badchieff / GUT AUS  (Single-Kopie, andere Sample-Rate
#         44100->48000, dieselbe ISRC/MB-Recording-ID): Δ ≈ 0.06s -> PASS
#       * makko / Nachts wach  (zwei Remix-EP-Tracks, TATSÄCHLICH
#         unterschiedliche Aufnahmen): Δ = 0.441179s -> FAIL (> 4x diese
#         Toleranz)
#   0.1s liegt damit sicher über dem beobachteten Encoding-Rauschen
#   (inkl. Sample-Rate-Wechsel) und sicher unter dem einzigen real
#   beobachteten echten Abweichungsfall.
DURATION_CONSISTENT_TOLERANCE_SECONDS = 0.1

# Risk-Signal (Auftrag Phase 2 Abschnitt 5) - KEIN Blocking-Kriterium für
# sich allein, siehe resolution.py. \b-Wortgrenzen, damit z. B. "Mix" nicht
# innerhalb von "Mixtape" fälschlich matcht.
_ALBUM_CONTEXT_RISK_PATTERN = re.compile(
    r"\b(remix|live|version|edit|acoustic|bootleg|mix|extended|instrumental)\b",
    re.IGNORECASE,
)


def has_album_context_risk(album: Optional[str]) -> bool:
    """True, wenn der Albumname auf einen Remix-/Live-/Versions-Kontext
    hindeutet (Auftrag Phase 2 Abschnitt 5) - reines Risk-Signal, erhöht
    NICHT automatisch eine Konfidenzstufe und verhindert für sich allein
    NICHT die Auflösung, siehe resolution.py::_evaluate_safety_gate()."""
    if not album:
        return False
    return bool(_ALBUM_CONTEXT_RISK_PATTERN.search(album))


def compare_recording_identity_ids(a: "Candidate", b: "Candidate") -> Optional[bool]:
    """MusicBrainz-Recording-ID-Vergleich (Auftrag Phase 2 Abschnitt 4).

    True  - beide IDs vorhanden UND identisch (starke Bestätigung)
    False - beide IDs vorhanden UND unterschiedlich (Widerspruch)
    None  - mindestens eine ID fehlt (kein MB-Signal, kein Beweis in
            irgendeine Richtung - Gruppe "Pueblo" MUSS trotzdem ohne
            MB-ID auflösbar bleiben, Auftrag Abschnitt 4)
    """
    if a.mb_recording_id and b.mb_recording_id:
        return a.mb_recording_id == b.mb_recording_id
    return None


def compare_isrc_identity(a: "Candidate", b: "Candidate") -> Optional[bool]:
    """Analog compare_recording_identity_ids(), für ISRC (Auftrag Phase 2
    Abschnitt 6 - optionales, aber bereits zuverlässig auslesbares
    Signal; im Real Findings Audit sogar die stärkste beobachtete
    Evidenz im Badchieff-Fall)."""
    if a.isrc and b.isrc:
        return a.isrc == b.isrc
    return None


def has_strong_identity_confirmation(a: "Candidate", b: "Candidate") -> bool:
    """Starke Identitätsbestätigung (Auftrag Phase 2 Abschnitt 7):
    mindestens einer der beiden Industriestandard-Identifikatoren
    (MusicBrainz Recording ID, ISRC) ist auf BEIDEN Kandidaten vorhanden
    UND identisch. Ein MB-ID-MISMATCH selbst wird NICHT hier, sondern
    separat als eigener, unbedingter Widerspruch behandelt (siehe
    resolution.py, Regel 2)."""
    if compare_recording_identity_ids(a, b) is True:
        return True
    if compare_isrc_identity(a, b) is True:
        return True
    return False


def is_duration_consistent(a: "Candidate", b: "Candidate") -> Optional[bool]:
    """True/False nur, wenn BEIDE Kandidaten eine gemessene Duration
    besitzen; sonst None (kein Duration-Signal verfügbar - blockiert die
    Safety Gate dadurch NICHT allein, siehe resolution.py). Toleranz
    siehe DURATION_CONSISTENT_TOLERANCE_SECONDS oben."""
    if a.duration_seconds is None or b.duration_seconds is None:
        return None
    return abs(a.duration_seconds - b.duration_seconds) <= DURATION_CONSISTENT_TOLERANCE_SECONDS


# ─────────────────────────────────────────────────────────────────────────
# Datenmodell (Architecture Audit / Auftrag Abschnitt 6)
# ─────────────────────────────────────────────────────────────────────────


@dataclass(eq=False)
class Candidate:
    """
    Repräsentiert eine einzelne Audiodatei als Duplicate-Resolution-
    Kandidat. Wird von der I/O-Schicht (scripts/resolve_duplicates.py)
    vollständig befüllt - dieses Modul selbst liest keine Datei.

    Per Konvention nach der Konstruktion nicht mehr mutiert (kein
    `frozen=True`, um den Aufbau in der I/O-Schicht - erst Tags lesen,
    dann klassifizieren, dann ffprobe - nicht unnötig zu verkomplizieren).

    `eq=False` (Objekt-Identität statt Feldvergleich für `==`/`hash()`):
    zwei Candidate-Instanzen mit zufällig identischen Feldwerten sind
    trotzdem zwei unterschiedliche Beobachtungen (z. B. zwei verschiedene
    Dateien mit identischem Titel-Tag, siehe der reale "Nachts wach"-Fund
    in der Testbibliothek) - Wert-basierte Gleichheit wäre hier fachlich
    falsch. Macht Candidate außerdem hashbar (Standard-`object`-Hash),
    was resolution.py's `c is not keep`-Filterung und Set-Operationen in
    Tests benötigen.

    Phase 2 (Safety Gate) fügt vier zusätzliche, optionale Felder hinzu
    (Default None/False - bestehende Aufrufer/Tests, die diese Felder
    nicht setzen, verhalten sich unverändert, siehe resolution.py):
    duration_seconds/mb_recording_id/isrc als Evidenz-Grundlage,
    cover_sha256 als rein informative, nicht blockierende Evidenz.
    """

    path: Path
    artist: str
    title: str
    normalized_artist: str
    normalized_title: str
    classification: Classification
    album: Optional[str] = None
    track_number: Optional[int] = None
    metadata_completeness: int = 0
    bitrate: Optional[int] = None
    collision_suffix: bool = False
    raw_fields: dict = field(default_factory=dict)
    duration_seconds: Optional[float] = None
    mb_recording_id: Optional[str] = None
    isrc: Optional[str] = None
    cover_sha256: Optional[str] = None

    def identity_key(self) -> tuple:
        return (self.normalized_artist, self.normalized_title)


def build_candidate(
    path: Path,
    artist: Optional[str],
    title: Optional[str],
    fields: Mapping[str, object],
    artist_normalizer: Optional[object] = None,
    bitrate: Optional[int] = None,
    duration_seconds: Optional[float] = None,
    cover_sha256: Optional[str] = None,
) -> Candidate:
    """
    Baut einen vollständigen Candidate aus bereits gelesenen Rohdaten
    (`fields` - Mapping mit den METADATA_COMPLETENESS_FIELDS-Keys plus
    ggf. weiteren). Reine Verdrahtung der obigen pure Functions - kein
    eigener Dateisystem-/Tag-Zugriff.

    `duration_seconds`/`cover_sha256` sind wie `bitrate` separate
    Parameter (keine METADATA_COMPLETENESS_FIELDS-Einträge, sondern
    Audio-Stream-/Datei-Evidenz, siehe resolve_duplicates.py). Für
    mb_recording_id/isrc genügt hingegen ein direktes Auslesen aus
    `fields` - beide sind bereits Teil von METADATA_COMPLETENESS_FIELDS
    und werden vom Aufrufer dort bereits befüllt.
    """
    normalized_artist = normalize_artist_for_identity(artist, artist_normalizer)
    normalized_title = normalize_title_for_identity(title, artist)
    mb_recording_id = fields.get("mb_recording_id")
    isrc = fields.get("isrc")
    return Candidate(
        path=path,
        artist=artist or "",
        title=title or "",
        normalized_artist=normalized_artist,
        normalized_title=normalized_title,
        classification=classify_by_path(path),
        album=fields.get("album") if isinstance(fields.get("album"), str) else None,
        track_number=fields.get("track_number"),
        metadata_completeness=compute_metadata_completeness(fields),
        bitrate=bitrate,
        collision_suffix=has_collision_suffix(path),
        raw_fields=dict(fields),
        duration_seconds=duration_seconds,
        mb_recording_id=mb_recording_id if isinstance(mb_recording_id, str) else None,
        isrc=isrc if isinstance(isrc, str) else None,
        cover_sha256=cover_sha256,
    )


def candidate_confidence(candidate: Candidate) -> Confidence:
    """
    Architecture Audit Abschnitt 14:
      UNKNOWN: Identität nicht zuverlässig bestimmbar (Artist/Titel fehlen)
      HIGH:    Artist+Titel eindeutig + Klassifikation SINGLE/ALBUM_LIKE
      MEDIUM:  Artist+Titel identisch + Klassifikation AMBIGUOUS
      LOW:     in dieser Phase unreachable, siehe Confidence-Docstring
    """
    if candidate.normalized_artist == "Unknown" or candidate.normalized_title == "Unknown":
        return Confidence.UNKNOWN
    if candidate.classification == Classification.AMBIGUOUS:
        return Confidence.MEDIUM
    return Confidence.HIGH


def group_candidates_by_identity(
    candidates: list[Candidate],
) -> dict[tuple, list[Candidate]]:
    """
    Gruppiert Kandidaten nach (normalized_artist, normalized_title).
    Kandidaten mit UNKNOWN-Konfidenz (fehlender Artist/Titel) werden NICHT
    gruppiert - ohne verlässliche Identität darf keine Duplicate-Gruppe
    behauptet werden (sonst würden beliebige "Unknown"/"Unknown"-Dateien
    fälschlich als Duplikate zusammengefasst). Deterministisch: reine
    Dict-Befüllung über eine bereits vorab in stabiler Pfad-Reihenfolge
    sortierte Eingabeliste macht die GRUPPENZUSAMMENSETZUNG unabhängig
    von der Eingabereihenfolge (Mitgliedschaft ist ohnehin nur von der
    Identität abhängig, nie von der Reihenfolge) - die Entscheidung
    INNERHALB einer Gruppe wird zusätzlich in resolution.py nochmals
    reihenfolge-unabhängig getroffen (siehe dortiger Comparator).
    """
    groups: dict[tuple, list[Candidate]] = {}
    for candidate in candidates:
        if candidate_confidence(candidate) == Confidence.UNKNOWN:
            continue
        groups.setdefault(candidate.identity_key(), []).append(candidate)
    return groups
