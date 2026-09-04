# services/library_health/issues.py
# -*- coding: utf-8 -*-
"""
Stabiles, dokumentiertes Issue-Code-Register (Prompt Abschnitt 20).

Jeder Code ist:
  - stabil   : der String aendert sich nach Einfuehrung nicht mehr
  - eindeutig : genau eine Bedeutung
  - dokumentiert : Default-Severity + Scope + Kurzbeschreibung hier zentral
  - testbar   : tests/test_library_health_issues.py prueft Vollstaendigkeit
                und dass jeder von file_analysis.py erzeugte Code hier
                registriert ist.

Die Default-Severity ist bewusst konservativ (Prompt Abschnitt 21/22:
"Nicht jede erkannte Abweichung darf automatisch ERROR werden"). Der
Analyzer darf die Severity in einem klar begruendeten Kontext hochstufen
(z. B. META_TRACK_NUMBER_MISSING ist INFO fuer eine Single, aber WARNING
fuer einen Album-Track) — dann wird das an der Aufrufstelle kommentiert.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Issue, Scope, Severity


@dataclass(frozen=True)
class IssueSpec:
    code: str
    default_severity: Severity
    scope: Scope
    description: str


# ─────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────

_SPECS: tuple[IssueSpec, ...] = (
    # ── Metadata ────────────────────────────────────────────────────────
    IssueSpec("META_NOT_ANALYZABLE", Severity.ERROR, Scope.FILE,
              "Tag-Container konnte nicht gelesen werden (mutagen-Fehler / kein Tag-Block)."),
    IssueSpec("META_ARTIST_MISSING", Severity.ERROR, Scope.FILE,
              "Kein Artist-Tag (©ART / TPE1)."),
    IssueSpec("META_TITLE_MISSING", Severity.ERROR, Scope.FILE,
              "Kein Titel-Tag (©nam / TIT2)."),
    IssueSpec("META_TITLE_NOT_CLEAN", Severity.WARNING, Scope.FILE,
              "Titel-Tag enthaelt Parsing-/Formatierungsreste, die die reale "
              "Download-Pipeline entfernt haette (umschliessende Anfuehrungs"
              "zeichen, 'prod.'-Credit, haengende Klammer, Marketing-Suffix, "
              "Artist-Praefix). Ermittelt read-only ueber "
              "TitleCleaner.light_title_cleanup() — verlustfrei per L2 "
              "(METADATA_REPROCESSING) behebbar; blockiert bis dahin u. a. "
              "externe MusicBrainz-Zuordnung (META_MB_*)."),
    IssueSpec("META_ALBUM_MISSING", Severity.WARNING, Scope.FILE,
              "Kein Album-Tag (©alb / TALB)."),
    IssueSpec("META_ALBUM_ARTIST_MISSING", Severity.WARNING, Scope.FILE,
              "Kein Album-Artist-Tag (aART / TPE2)."),
    IssueSpec("META_YEAR_MISSING", Severity.WARNING, Scope.FILE,
              "Kein Jahr-Tag (©day / TDRC)."),
    IssueSpec("META_YEAR_INVALID", Severity.WARNING, Scope.FILE,
              "Jahr-Tag vorhanden, aber keine plausible Jahreszahl."),
    IssueSpec("META_GENRE_MISSING", Severity.WARNING, Scope.FILE,
              "Kein Genre-Tag (©gen / TCON)."),
    IssueSpec("META_TRACK_NUMBER_MISSING", Severity.INFO, Scope.FILE,
              "Keine Tracknummer (trkn / TRCK). WARNING im Album-Kontext."),
    IssueSpec("META_MB_RECORDING_MISSING", Severity.INFO, Scope.FILE,
              "Keine MusicBrainz Recording ID."),
    IssueSpec("META_MB_RELEASE_MISSING", Severity.INFO, Scope.FILE,
              "Keine MusicBrainz Release ID."),
    IssueSpec("META_ISRC_MISSING", Severity.INFO, Scope.FILE,
              "Kein ISRC."),

    # ── Artwork ─────────────────────────────────────────────────────────
    IssueSpec("ARTWORK_MISSING", Severity.WARNING, Scope.FILE,
              "Kein eingebettetes Cover."),
    IssueSpec("ARTWORK_INVALID", Severity.ERROR, Scope.FILE,
              "Eingebettetes Cover vorhanden, aber nicht als Bild dekodierbar."),
    IssueSpec("ARTWORK_LOW_RESOLUTION", Severity.INFO, Scope.FILE,
              "Eingebettetes Cover unter der empfohlenen Mindestkantenlaenge "
              "(zeigt sich in Playern noch, reiner Qualitaets-Verbesserungskandidat)."),
    IssueSpec("ARTWORK_NON_SQUARE", Severity.INFO, Scope.FILE,
              "Eingebettetes Cover weicht sichtbar vom Seitenverhaeltnis 1:1 ab "
              "(> ARTWORK_SQUARE_TOLERANCE)."),

    # ── Lyrics ──────────────────────────────────────────────────────────
    IssueSpec("LYRICS_MISSING", Severity.INFO, Scope.FILE,
              "Kein Lyrics-Tag (©lyr / USLT)."),
    IssueSpec("LYRICS_EMPTY", Severity.WARNING, Scope.FILE,
              "Lyrics-Tag vorhanden, aber leer / nur Whitespace."),
    IssueSpec("LYRICS_INVALID", Severity.WARNING, Scope.FILE,
              "Lyrics-Tag-Inhalt ist offensichtlich kein Liedtext (z. B. Fehlermeldung)."),

    # ── Audio ───────────────────────────────────────────────────────────
    IssueSpec("AUDIO_NOT_ANALYZABLE", Severity.ERROR, Scope.FILE,
              "ffprobe konnte die Datei nicht analysieren (nicht: fehlend)."),
    IssueSpec("AUDIO_NO_STREAM", Severity.CRITICAL, Scope.FILE,
              "Datei enthaelt keinen Audio-Stream."),
    IssueSpec("AUDIO_CORRUPT", Severity.CRITICAL, Scope.FILE,
              "ffprobe meldet einen beschaedigten Container / Decode-Fehler."),
    IssueSpec("AUDIO_LOW_BITRATE", Severity.WARNING, Scope.FILE,
              "Audio-Bitrate unter der erwarteten Mindestqualitaet."),
    IssueSpec("AUDIO_VERY_SHORT", Severity.INFO, Scope.FILE,
              "Audio-Dauer sehr kurz — moeglicherweise Skit/Intro/Interlude, "
              "moeglicherweise abgeschnitten. Manuelle Pruefung (keine "
              "automatische Aktion)."),

    # ── Loudness / ReplayGain ──────────────────────────────────────────
    # Die AKTUELLE Pipeline (tag_writer.py / enhanced_metadata_processor.py)
    # schreibt KEINE replaygain_track_gain/loudness_normalized-Tags — sie
    # normalisiert die Lautheit vor dem Taggen per FFmpeg-loudnorm, ohne
    # einen Nachweis-Tag zu hinterlassen (siehe
    # scripts/normalize_test_library_loudness.py Docstring). Ein fehlender
    # Loudness-Tag ist daher der Normalfall und AUSDRUECKLICH nur INFO —
    # kein Defect (Prompt Abschnitt 16/22).
    IssueSpec("LOUDNESS_TAG_MISSING", Severity.INFO, Scope.FILE,
              "Kein ReplayGain-/Loudness-Tag (bei aktueller Pipeline normal)."),
    IssueSpec("LOUDNESS_TAG_INVALID", Severity.WARNING, Scope.FILE,
              "ReplayGain-/Loudness-Tag vorhanden, aber nicht als dB-Wert parsebar."),
    IssueSpec("LOUDNESS_TAG_PARTIAL", Severity.INFO, Scope.FILE,
              "Nur ein Teil der ReplayGain-Tag-Familie vorhanden (z. B. gain ohne peak)."),

    # ── Struktur / Dateiname ───────────────────────────────────────────
    IssueSpec("STRUCTURE_INVALID_PATH", Severity.WARNING, Scope.FILE,
              "Datei liegt nicht in der erwarteten <Artist>/<Singles|Jahr - Album>/-Hierarchie."),
    IssueSpec("STRUCTURE_FILE_OUTSIDE_HIERARCHY", Severity.WARNING, Scope.FILE,
              "Audio-Datei direkt in einem uebergeordneten Verzeichnis (z. B. direkt unter LIBRARY_DIR)."),
    IssueSpec("FILENAME_TITLE_MISMATCH", Severity.INFO, Scope.FILE,
              "Dateiname-Stamm passt nicht zum Titel-Tag (nach Beruecksichtigung der Namenskonvention)."),
    IssueSpec("FILENAME_SUSPICIOUS", Severity.INFO, Scope.FILE,
              "Dateiname enthaelt doppelte Leerzeichen / dateinamens-illegale Zeichen / Randwhitespace."),
    IssueSpec("FILENAME_EXTENSION_UNEXPECTED", Severity.INFO, Scope.FILE,
              "Dateiendung weicht vom konfigurierten AUDIO_FORMAT ab (aber unterstuetzt)."),

    # ── Multi-Artist ───────────────────────────────────────────────────
    IssueSpec("MULTI_ARTIST_SUSPICIOUS", Severity.WARNING, Scope.FILE,
              "Artist-Tag sieht nach unsauberer String-Konkatenation aus (z. B. ';' im Einzelwert, 'feat.' im ©ART statt separatem ARTISTS-Wert)."),
    IssueSpec("MULTI_ARTIST_INCONSISTENT", Severity.INFO, Scope.FILE,
              "©ART / ARTISTS-Freeform / Album-Artist widersprechen sich."),
    IssueSpec("MULTI_ARTIST_DUPLICATE", Severity.INFO, Scope.FILE,
              "Derselbe Artist-Name mehrfach im Multi-Artist-Feld."),

    # ── Genre ──────────────────────────────────────────────────────────
    IssueSpec("GENRE_EMPTY", Severity.WARNING, Scope.FILE,
              "Genre-Tag vorhanden, aber leer / nur Trennzeichen."),
    IssueSpec("GENRE_INVALID", Severity.INFO, Scope.FILE,
              "Genre-Wert liegt (auch nach GenreMapper.normalize_genre_name) "
              "ausserhalb der Genre-Konvention des Projekts — Tag-Hygiene, kein "
              "Qualitaetsdefekt (Genre zeigt sich im Player weiterhin)."),
    IssueSpec("GENRE_DELIMITER_INCONSISTENT", Severity.INFO, Scope.FILE,
              "Mehrfach-Genre nutzt einen anderen Separator als die aktuelle Konvention '; '."),

    # ── Album-Konsistenz (Prompt Abschnitt 18) ─────────────────────────
    IssueSpec("ALBUM_TRACK_GAP", Severity.WARNING, Scope.ALBUM,
              "Luecke in der Tracknummern-Folge eines Albums (z. B. 1, 2, 4). "
              "Nur INFO bei Compilation-/Best-Of-Ordnern (dort ist eine "
              "kuratierte Auswahl der Normalfall)."),
    IssueSpec("ALBUM_DUPLICATE_TRACK_NUMBER", Severity.ERROR, Scope.ALBUM,
              "Zwei Dateien eines Albums (gleiche Disc) tragen dieselbe Tracknummer."),
    IssueSpec("ALBUM_NAME_INCONSISTENT", Severity.WARNING, Scope.ALBUM,
              "Tracks desselben Album-Ordners haben unterschiedliche Album-Tags."),
    IssueSpec("ALBUM_ARTIST_INCONSISTENT", Severity.WARNING, Scope.ALBUM,
              "Tracks desselben Albums haben unterschiedliche Album-Artist-Tags "
              "(bei einem regulaeren Artist-Album; Compilations sind ausgenommen)."),
    IssueSpec("ALBUM_YEAR_INCONSISTENT", Severity.INFO, Scope.ALBUM,
              "Tracks desselben Albums haben unterschiedliche Jahr-Tags."),
    IssueSpec("ALBUM_GENRE_INCONSISTENT", Severity.INFO, Scope.ALBUM,
              "Tracks desselben Albums haben unterschiedliche Genre-Tags "
              "(kann legitim sein — reine Beobachtung, Prompt Abschnitt 22)."),
    IssueSpec("ALBUM_RELEASE_ID_INCONSISTENT", Severity.INFO, Scope.ALBUM,
              "Tracks desselben Studio-Albums verweisen auf unterschiedliche "
              "MusicBrainz Release IDs (bei Compilation-/Best-Of-Ordnern NICHT "
              "gemeldet — dort ist eine Release-ID pro Track erwartbar)."),
    IssueSpec("ALBUM_COVER_INCONSISTENT", Severity.INFO, Scope.ALBUM,
              "Tracks desselben Albums haben Cover mit unterschiedlichen "
              "Abmessungen (starkes Signal fuer eine andere Quell-Bilddatei; "
              "reine Hash-Unterschiede bei identischer Groesse zaehlen nicht)."),

    # ── Artist-Konsistenz (Prompt Abschnitt 19) ────────────────────────
    IssueSpec("ARTIST_DIR_TAG_MISMATCH", Severity.INFO, Scope.ARTIST,
              "Artist-Verzeichnisname weicht deutlich vom Artist-Tag der darin "
              "liegenden Dateien ab."),
    IssueSpec("ARTIST_NAME_VARIANTS", Severity.INFO, Scope.ARTIST,
              "Mehrere Artist-Verzeichnisse normalisieren auf denselben Namen "
              "(wahrscheinlich Schreibvarianten desselben Artists)."),

    # ── Duplicate-Analyse (Prompt Abschnitt 17) ────────────────────────
    # Der Scanner ERKENNT Kandidaten und loest sie NIE auf.
    IssueSpec("DUPLICATE_EXACT", Severity.WARNING, Scope.LIBRARY,
              "Byte-identische Dateien (gleicher SHA-256)."),
    IssueSpec("DUPLICATE_RECORDING", Severity.WARNING, Scope.LIBRARY,
              "Dateien mit identischer MusicBrainz Recording ID bzw. identischem ISRC."),
    IssueSpec("DUPLICATE_SUSPECTED", Severity.INFO, Scope.LIBRARY,
              "Dateien mit identischem normalisiertem Artist+Titel (Remix/Live/"
              "Version bleiben getrennt — reine Beobachtung, kein Auflösungs-Vorschlag)."),
)

REGISTRY: dict[str, IssueSpec] = {spec.code: spec for spec in _SPECS}

ALL_CODES: frozenset[str] = frozenset(REGISTRY)


def make_issue(
    code: str,
    *,
    message: str | None = None,
    severity: Severity | None = None,
    path: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    title: str | None = None,
    details: dict | None = None,
    confidence: str | None = None,
    related_files: list[str] | None = None,
) -> Issue:
    """Erzeugt ein Issue aus dem Register. `severity` uebersteuert die
    Default-Severity nur, wenn der Aufrufer einen begruendeten Kontext hat
    (dann dort kommentiert). Ein unbekannter Code ist ein Programmierfehler
    und wirft sofort (kein stiller Fallback)."""
    spec = REGISTRY.get(code)
    if spec is None:
        raise KeyError(f"Unbekannter Issue-Code: {code!r} — in issues.REGISTRY aufnehmen")
    return Issue(
        code=code,
        severity=severity or spec.default_severity,
        scope=spec.scope,
        message=message or spec.description,
        path=path,
        artist=artist,
        album=album,
        title=title,
        details=details or {},
        confidence=confidence,
        related_files=related_files or [],
    )
