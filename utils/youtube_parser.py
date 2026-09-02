# -*- coding: utf-8 -*-
"""
Modul zum Parsen von YouTube-Titeln.

Dieses Skript stellt eine Funktion zur Verfügung, um rohe YouTube-Titel
in strukturierte Daten (Künstler, Songtitel) zu zerlegen und von
typischen Zusätzen wie "(Official Video)" zu bereinigen.

CHANGELOG:
  ✅ NEU: all_artists Feld – extrahiert ALLE Künstler aus dem Titel
  ✅ NEU: Split von Multi-Artists mit Komma, "x", "&", "+" und "und"
  ✅ NEU: Feature-Erkennung mit "feat.", "ft.", "with", "pres."
  ✅ NEU: Konfidenzwert für Parsing-Qualität
  ✅ NEU: Erweiterte Bereinigung von Produzenten-Angaben
  🔥 NEU: Erkennung von "Artist1 feat. Artist2" OHNE Trennzeichen
  🆕 NEU: _clean_title_suffixes für (prod...), (feat...), (ft...) Bereinigung
  🔧 FIX: Unterstützung für Schrägstriche "/" in Artist-Namen
  🔧 FIX: Bessere Erkennung von Remix-Informationen
  🔧 FIX: "Zukunft Pink" bleibt erhalten (kein Entfernen von "Pink")
  🔧 FIX: Feature-Erkennung funktioniert auch mit Remix im Titel
"""

import re
import unicodedata
from typing import Dict, List, Optional, Callable, Tuple, Any
from dataclasses import dataclass, field


@dataclass
class ParsedTitle:
    """Strukturiertes Ergebnis des YouTube-Titel-Parsings"""

    artist: Optional[str] = None  # Primärer/Erster Artist (für Kompatibilität)
    all_artists: List[str] = field(default_factory=list)  # Alle gefundenen Artists
    song_title: Optional[str] = None
    original_title: str = ""
    featuring: List[str] = field(default_factory=list)  # Feature-Artists
    confidence: float = 1.0  # Konfidenzwert (0.0-1.0)
    raw_artist_string: Optional[str] = None  # Ungeparster Artist-String


def _normalize_string(text: str) -> str:
    """Führt eine grundlegende Normalisierung durch (Unicode, Whitespace, etc.)."""
    if not text:
        return ""
    text = text.strip()
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _clean_bracket_content(text: str, preserve_remix: bool = True) -> str:
    """
    Entfernt bekannte, störende Inhalte in Klammern und eckigen Klammern.

    Args:
        text: Zu reinigender Text
        preserve_remix: Wenn True, werden Remix-Informationen erhalten
    """
    patterns = [
        # Bestehende Patterns
        r"\(official music video\)",
        r"\(official video\)",
        r"\(official audio\)",
        r"\(official lyric video\)",
        r"\(official visualizer\)",
        r"\(Official 4K Video\)",
        r"\(visualizer\)",
        r"\(lyric video\)",
        r"\(lyric\)",
        r"\(official\)",
        r"\[4k\]",
        r"\[hd\]",
        r"\(live\)",
        r"\(live bei[^)]+\)",
        r"\(live in[^)]+\)",
        r"\(live from[^)]+\)",
        r"\(unplugged[^)]*\)",
        r"\(acoustic[^)]*\)",
        r"\(audio\)",
        r"\(lyrics\)",
        r"\(vevo\)",
        r"\(extended mix\)",
        r"\(radio edit\)",
        r"\(club mix\)",
        r"\(original mix\)",
        r"\(full version\)",
        r"\(short version\)",
        r"\(explicit\)",
        r"\(clean\)",
        r"\(\s*prod\.?\s+by\s+[^)]+\)",
        r"\(\s*produced\s+by\s+[^)]+\)",
        r"\(prod[^)]*\)",
        # KEIN (feat...) / (ft...) hier – das macht _extract_features danach!
        r"\[.*?\]",
    ]

    # 🔧 FIX: Remix-Pattern nur entfernen wenn nicht preserve_remix
    if not preserve_remix:
        patterns.append(r"\(.*?remix.*?\)")

    cleaned_text = text
    for pattern in patterns:
        cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE).strip()

    # Entferne leere Klammern
    cleaned_text = re.sub(r"\(\s*\)", "", cleaned_text)
    cleaned_text = re.sub(r"\[\s*\]", "", cleaned_text)

    # 🔧 FIX: Entferne doppelte Leerzeichen, aber behalte einzelne Wörter
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()

    return cleaned_text


def _clean_title_suffixes(title: str) -> str:
    """
    Entfernt Produzenten- und Feature-Angaben aus dem Titel.
    Wird NACH der Feature-Extraktion aufgerufen, um verbleibende
    (prod...), (feat...), (ft...) Reste zu bereinigen.
    """
    if not title:
        return title

    # Entferne (prod...), (feat...), (ft...) - aber nur wenn sie übrig sind
    title = re.sub(r"\(prod[^)]*\)", "", title, flags=re.I)
    title = re.sub(r"\(feat\.[^)]*\)", "", title, flags=re.I)
    title = re.sub(r"\(ft\.[^)]*\)", "", title, flags=re.I)

    # Entferne auch ohne Klammern am Ende
    title = re.sub(r"\s*[-–—]\s*prod[^)]*$", "", title, flags=re.I)

    # Entferne leere Klammern
    title = re.sub(r"\(\s*\)", "", title)

    return title.strip()


def _split_multi_artists(artist_string: str) -> List[str]:
    """
    Splittet einen Artist-String in einzelne Künstler.
    """
    if not artist_string:
        return []

    # Normalisiere alle Trennzeichen zu Komma
    normalized = artist_string
    separators = [
        (r"\s+[xX]\s+", ","),
        (r"\s+&\s+", ","),
        (r"\s+\+\s+", ","),
        (r"\s+und\s+", ","),
        (r"\s+and\s+", ","),
        (r"\s*/\s*", ","),
        (r"\s*;\s*", ","),
    ]

    for pattern, replacement in separators:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)

    # Splitte und bereinige
    artists = [a.strip() for a in normalized.split(",") if a.strip()]

    # 🔧 FIX: Entferne Duplikate (z.B. "Zartmann - Zartmann")
    unique_artists = []
    seen = set()
    for a in artists:
        # Normalisiere für Duplikatserkennung
        a_norm = a.lower()
        if a_norm not in seen:
            seen.add(a_norm)
            unique_artists.append(a)
        else:
            # Logge Duplikat-Entfernung
            import logging

            logging.getLogger("yt_utils").debug(f"  Entferne Duplikat: '{a}'")

    return unique_artists


def _extract_features(song_title: str, logger) -> Tuple[str, List[str]]:
    """
    Extrahiert Feature-Artists aus dem Song-Titel.
    🔧 FIX: Unterstützt (feat. Artist) UND feat. Artist (ohne Klammern)
    """
    if not song_title:
        return song_title, []

    # META-01 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2N_RES01_AUDIT.md-
    # Nachfolgephase, Metadata-Quality-Read-Only-Audit vom 2026-08-26): "feat"/
    # "ft" verlangten bisher nach dem optionalen Punkt zwingend ein Leerzeichen
    # (\s+) - "feat.Artist"/"ft.Artist" (ohne Leerzeichen) wurde dadurch NICHT
    # als Featuring erkannt. Alternation analog zu DUP-04
    # (services/duplicate/detector.py): nach "feat"/"ft" entweder (a) Punkt +
    # optionaler Whitespace, oder (b) mindestens ein Leerzeichen (ohne Punkt) -
    # verhindert weiterhin Fehltreffer wie "Featherweight" (weder Punkt noch
    # Leerzeichen folgt dort direkt auf "Feat").
    feature_patterns = [
        # In runden Klammern (höchste Priorität)
        (
            r"\(\s*(?:feat(?:\.\s*|\s+)|ft(?:\.\s*|\s+)|featuring\s+|with\s+|pres(?:\.\s*|\s+))(.+?)\s*\)",
            "()",
        ),
        # In eckigen Klammern
        (
            r"\[\s*(?:feat(?:\.\s*|\s+)|ft(?:\.\s*|\s+)|featuring\s+)(.+?)\s*\]",
            "[]",
        ),
        # Ohne Klammern (niedrigste Priorität) - NUR am Ende des Titels
        (
            r"\s+(?:feat(?:\.\s*|\s+)|ft(?:\.\s*|\s+)|featuring\s+|with\s+|pres(?:\.\s*|\s+))(.+?)$",
            "plain",
        ),
    ]

    features_found = []
    cleaned_title = song_title

    for pattern, _ in feature_patterns:
        match = re.search(pattern, cleaned_title, flags=re.IGNORECASE)
        if match:
            feat_raw = match.group(1).strip()
            # Bereinige feat_raw von Klammern und anderen Tags
            feat_raw = re.sub(r"[\(\)\[\]]", "", feat_raw).strip()

            # Extrahiere Feature-Artists
            feat_artists = _split_multi_artists(feat_raw)
            features_found.extend(feat_artists)

            # Entferne das Feature-Pattern aus dem Titel
            cleaned_title = re.sub(
                pattern, "", cleaned_title, flags=re.IGNORECASE
            ).strip()

            logger.debug(f"  Feature extrahiert: {features_found} aus '{feat_raw}'")
            break  # Nur das erste Feature-Pattern verarbeiten

    # Entferne leere Klammern
    cleaned_title = re.sub(r"\(\s*\)", "", cleaned_title)
    cleaned_title = cleaned_title.strip()

    return cleaned_title, features_found


def _parse_artist_and_title(
    title: str, logger
) -> Tuple[Optional[str], Optional[str], float]:
    """
    Parst Artist und Songtitel.
    🔧 FIX: "Zartmann - Zartmann x Ski Aggu" -> "Zartmann, Ski Aggu"
    """

    # 🔥 Spezialfall: "Artist1 - Artist1 x Artist2 - Title" (Zartmann - Zartmann x Ski Aggu)
    duplicate_artist_pattern = re.compile(
        r"^(.+?)\s*[-–—]\s*\1\s+[xX]\s+(.+?)\s*[-–—]\s*(.+)$",
        re.IGNORECASE,
    )
    match = duplicate_artist_pattern.match(title)
    if match:
        artist1 = match.group(1).strip()
        artist2 = match.group(2).strip()
        song = match.group(3).strip()
        logger.debug(
            f"🔥 Duplicate-Artist erkannt: Artist1='{artist1}', Artist2='{artist2}', Song='{song}'"
        )
        combined_artist = f"{artist1}, {artist2}"
        return combined_artist, song, 0.95

    # 🔥 "Artist1 feat. Artist2 - Title" Format
    # META-01: gleiche Alternation wie in _extract_features() oben - siehe
    # dortiger Kommentar.
    feat_in_artist_pattern = re.compile(
        r"^(.+?)\s+(?:feat(?:\.\s*|\s+)|ft(?:\.\s*|\s+)|featuring\s+|with\s+)(.+?)\s*[-–—|:]\s*(.+)$",
        re.IGNORECASE,
    )
    match = feat_in_artist_pattern.match(title)
    if match:
        artist1 = match.group(1).strip()
        artist2 = match.group(2).strip()
        song = match.group(3).strip()
        logger.debug(
            f"🔥 feat.-im-Artist erkannt: Artist1='{artist1}', Artist2='{artist2}', Song='{song}'"
        )
        combined_artist = f"{artist1}, {artist2}"
        return combined_artist, song, 0.95

    # "Artist1 x Artist2/Artist3 - Title"
    slash_x_pattern = re.compile(
        r"^(.+?)\s+[xX]\s+(.+?)\s*[-–—|:]\s*(.+)$",
        re.IGNORECASE,
    )
    match = slash_x_pattern.match(title)
    if match:
        artist1 = match.group(1).strip()
        artist2_raw = match.group(2).strip()
        song = match.group(3).strip()

        if "/" in artist2_raw:
            artists = _split_multi_artists(f"{artist1}, {artist2_raw}")
            combined_artist = ", ".join(artists)
            logger.debug(
                f"🔥 x-mit-Schrägstrich erkannt: Artists={artists}, Song='{song}'"
            )
            return combined_artist, song, 0.95
        else:
            logger.debug(
                f"🔥 x-Format erkannt: Artist1='{artist1}', Artist2='{artist2_raw}', Song='{song}'"
            )
            return f"{artist1}, {artist2_raw}", song, 0.95

    # Standard-Trennzeichen
    # YTPARSE-01: Bindestrich-Trenner verlangt zwingend Leerzeichen auf
    # beiden Seiten (\s+ statt \s*) - sonst matcht re.split() den erstbesten
    # BAREN Bindestrich in einem Kuenstlernamen wie "t-low"/"K-Fly" statt des
    # eigentlichen Artist/Titel-Trenners (Live-Fund 2026-09-02: "Miksu/
    # Macloud, makko, t-low - Ich will" wurde faelschlich bei "t-low"
    # gesplittet -> Artist "t" + Titel-Leak "low - Ich will"). Analog zum
    # bereits bestehenden Schutz in
    # artist_processor.py::clean_artist_before_normalization() ("Nur
    # Separatoren MIT Leerzeichen"). En-/Em-Dash (–/—) sind davon mit
    # betroffen, auch wenn sie in echten Kuenstlernamen selten bare
    # vorkommen - fuer Konsistenz gleich mitgefixt.
    separator_patterns = [
        (r"\s+[-–—]\s+", "artist_first", 1.0),
        (r"\s*\|\s*", "artist_first", 0.9),
        (r"\s*•\s*", "artist_first", 0.9),
        (r"\s*:\s*", "artist_first", 0.85),
        (r"\s+by\s+", "title_first", 0.8),
        (r"\s+–\s+", "artist_first", 0.95),
    ]

    for pattern, direction, base_confidence in separator_patterns:
        parts = re.split(pattern, title, maxsplit=1)
        if len(parts) == 2:
            left = _normalize_string(parts[0])
            right = _normalize_string(parts[1])

            if direction == "artist_first":
                artist_part = left
                title_part = right
            else:
                artist_part = right
                title_part = left

            # Entferne einen abschließenden Klammer-/Eckklammer-Zusatz vom
            # Artist-Teil (z.B. "TOOBROKEFORFIJI (2b4F)" -> "TOOBROKEFORFIJI").
            # Analog zur Bereinigung, die der Songtitel bereits erhält.
            artist_part = re.sub(
                r"\s*[\(\[][^\)\]]*[\)\]]\s*$", "", artist_part
            ).strip()

            if len(artist_part) > 1 and len(title_part) > 1:
                return artist_part, title_part, base_confidence

    logger.warning("❓ Kein klares Artist-Song-Trennzeichen gefunden. Fallback.")
    return None, _normalize_string(title), 0.3


def parse_youtube_title(
    title: str, logger_factory: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Erweiterte YouTube-Titel-Parsing-Funktion.

    all_artists: Nur die Künstler aus dem Artist-Teil (vor dem Trennzeichen)
    featuring: Alle Feature-Artists (explizit als feat./ft. markiert)
    """
    logger = logger_factory("yt_utils") if logger_factory else _get_default_logger()

    if not title:
        return {
            "artist": None,
            "all_artists": [],
            "song_title": title,
            "original_title": title,
            "featuring": [],
            "confidence": 0.0,
            "raw_artist_string": None,
        }

    logger.info(f"📺 Starte Parsing für Titel: '{title}'")

    # Schritt 1: Grundlegende Bereinigung (behalte Remix-Info)
    cleaned_title = _clean_bracket_content(title, preserve_remix=True)
    logger.debug(f"   Nach Bereinigung: '{cleaned_title}'")

    # Schritt 2: Artist und Titel trennen
    artist, song_title, confidence = _parse_artist_and_title(cleaned_title, logger)

    # Schritt 3: Fallback
    if not artist:
        logger.warning(f"🔄 Fallback: Kein Artist gefunden.")
        final_song_title = _clean_bracket_content(title, preserve_remix=False)
        return {
            "artist": None,
            "all_artists": [],
            "song_title": final_song_title,
            "original_title": title,
            "featuring": [],
            "confidence": 0.0,
            "raw_artist_string": None,
        }

    # Schritt 4: Features extrahieren (aus dem Song-Titel)
    song_title, features_from_title = _extract_features(song_title, logger)
    if features_from_title:
        logger.info(f"🤝 Features in Titel gefunden: {features_from_title}")

    # Schritt 5: Multi-Artist-Splitting für den Künstlerteil
    main_artists = _split_multi_artists(artist)
    logger.debug(f"   Multi-Artist-Split: {artist} → {main_artists}")

    # ─────────────────────────────────────────────────────────────────────
    # 🔧 WICHTIG: KORREKTE SEMANTIK
    # ─────────────────────────────────────────────────────────────────────
    # all_artists = NUR die Künstler aus dem Artist-Teil (vor dem Trennzeichen)
    # featuring = ALLE Feature-Artists (explizit als feat./ft. markiert)
    #
    # Das bedeutet:
    # - "t-low x Miksu/Macloud - Title" → all_artists = [t-low, Miksu, Macloud], featuring = []
    # - "Peter Fox - Title feat. Inéz"  → all_artists = [Peter Fox], featuring = [Inéz]
    # - "Ski Aggu, Sido - Title"        → all_artists = [Ski Aggu, Sido], featuring = []
    # ─────────────────────────────────────────────────────────────────────

    all_artists = main_artists.copy()
    featuring = features_from_title  # Features sind NICHT in all_artists enthalten!

    # Schritt 6: Primärer Artist (erster für Kompatibilität)
    primary_artist = all_artists[0] if all_artists else None

    # Schritt 7: Finale Titel-Bereinigung
    song_title = _clean_bracket_content(song_title, preserve_remix=False)
    song_title = _clean_title_suffixes(song_title)

    # Entferne "feat. Artist" Reste die noch im Titel sein könnten
    song_title = re.sub(r"\s+feat\..*$", "", song_title, flags=re.I).strip()
    song_title = re.sub(r"\s+ft\..*$", "", song_title, flags=re.I).strip()

    if not song_title or len(song_title) < 2:
        song_title = None
        confidence *= 0.5

    # Schritt 8: Konfidenz
    if not primary_artist:
        confidence *= 0.3
    elif len(all_artists) > 1:
        confidence = min(1.0, confidence + 0.05)

    if song_title and len(song_title) > 3:
        confidence = min(1.0, confidence + 0.1)

    logger.info(
        f"✅ Parsing abgeschlossen: Artist='{primary_artist}', "
        f"All Artists={all_artists}, Titel='{song_title}', "
        f"Features={featuring}, Konfidenz={confidence:.2f}"
    )

    return {
        "artist": primary_artist,
        "all_artists": all_artists,
        "song_title": song_title,
        "original_title": title,
        "featuring": featuring,
        "confidence": confidence,
        "raw_artist_string": artist,
    }


def _get_default_logger():
    import logging

    logger = logging.getLogger("yt_utils")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def quick_parse(title: str) -> Tuple[Optional[str], Optional[str]]:
    result = parse_youtube_title(title)
    return result.get("artist"), result.get("song_title")


if __name__ == "__main__":
    print("=" * 70)
    print("🧪 YOUTUBE-TITLE-PARSER – KORRIGIERTE TESTS")
    print("=" * 70)

    test_titles = [
        # t-low mit Schrägstrich (Feature = Miksu, Macloud sind gleichberechtigte Künstler, keine expliziten Features)
        (
            "t-low x Miksu/Macloud - Nur ein Trost (Official Video)",
            ["t-low", "Miksu", "Macloud"],  # all_artists
            "Nur ein Trost",  # song_title
            [],  # featuring (keine expliziten feat.)
        ),
        # Peter Fox mit Remix (Inéz ist explizites Feature)
        (
            "Peter Fox - Zukunft Pink (NoooN Remix) feat. Inéz",
            ["Peter Fox"],  # all_artists
            "Zukunft Pink",  # song_title
            ["Inéz"],  # featuring
        ),
        # Peter Fox mit feat. in Klammern (Inéz ist explizites Feature)
        (
            "Peter Fox - Zukunft Pink (feat. Inéz)",
            ["Peter Fox"],  # all_artists
            "Zukunft Pink",  # song_title
            ["Inéz"],  # featuring
        ),
        # Zartmann Duplikat (Ski Aggu ist gleichberechtigter Künstler, kein explizites Feature)
        (
            "Zartmann - Zartmann x Ski Aggu - wie du manchmal fehlst (prod. by Dauner)",
            ["Zartmann", "Ski Aggu"],  # all_artists
            "wie du manchmal fehlst",  # song_title
            [],  # featuring
        ),
        # Ski Aggu, Sido (beide gleichberechtigt)
        (
            "Ski Aggu, Sido - Mein Block (Official Video) [4K]",
            ["Ski Aggu", "Sido"],  # all_artists
            "Mein Block",  # song_title
            [],  # featuring
        ),
        # CIVO x Esther Graf (beide gleichberechtigt)
        (
            "CIVO x Esther Graf - Gute Kinder (Prod. by Maxe)",
            ["CIVO", "Esther Graf"],  # all_artists
            "Gute Kinder",  # song_title
            [],  # featuring
        ),
        # Travis Scott ft. Drake (Drake ist explizites Feature)
        (
            "Travis Scott - SICKO MODE (Audio) ft. Drake",
            ["Travis Scott"],  # all_artists
            "SICKO MODE",  # song_title
            ["Drake"],  # featuring
        ),
    ]

    for i, (
        test_title,
        expected_artists,
        expected_title,
        expected_features,
    ) in enumerate(test_titles):
        result = parse_youtube_title(test_title)

        print(f"\n{'─'*70}")
        print(f"📋 Test {i+1}:")
        print(f"   Original:   {result['original_title']}")
        print(f"   Artist(s):  {result['all_artists']}")
        print(f"   Primary:    {result['artist']}")
        print(f"   Song:       {result['song_title']}")
        print(f"   Features:   {result['featuring']}")
        print(f"   Konfidenz:  {result['confidence']:.2f}")

        artists_ok = result["all_artists"] == expected_artists
        title_ok = result["song_title"] == expected_title
        features_ok = result["featuring"] == expected_features

        if artists_ok and title_ok and features_ok:
            print("   ✅ TEST BESTANDEN")
        else:
            print("   ❌ TEST FEHLGESCHLAGEN")
            if not artists_ok:
                print(f"      Erwartete Artists: {expected_artists}")
                print(f"      Erhaltene Artists: {result['all_artists']}")
            if not title_ok:
                print(f"      Erwarteter Titel: {expected_title}")
                print(f"      Erhaltener Titel: {result['song_title']}")
            if not features_ok:
                print(f"      Erwartete Features: {expected_features}")
                print(f"      Erhaltene Features: {result['featuring']}")

    print("\n" + "=" * 70)
    print("✅ Tests abgeschlossen")
    print("=" * 70)
