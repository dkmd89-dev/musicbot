# utils/title_cleanup.py
# -*- coding: utf-8 -*-
"""
Reine, zustandslose Titel-Bereinigung (nur Regex, kein I/O, kein Logger,
keine Config).

Ausgelagert aus `services/metadata/title_cleaner.py::TitleCleaner.
light_title_cleanup()` — die Methode dort delegiert jetzt hierher, ihr
Verhalten und ihre Tests (`tests/test_title_cleaner_*.py`) sind unveraendert.

Grund der Auslagerung: der read-only Library-Health-Scanner
(`services/library_health/`) braucht exakt dieselbe Bereinigung wie die
reale Download-Pipeline, um „nicht saubere" Titel-Tags zu erkennen
(`META_TITLE_NOT_CLEAN`), darf aber `services/metadata/` nicht in seinen
Import-Graph ziehen (dessen `__init__.py` importiert eager `TagWriter`,
`EnhancedMetadataProcessor`, `CoverProcessor` — Schreib-Pfade). Diese
Datei hat keine solchen Abhaengigkeiten.
"""

from __future__ import annotations

import re

# Umschliessende Anfuehrungszeichen-Paare (gerade + gaengige typografische
# Varianten deutsch/franzoesisch/englisch).
_QUOTE_PAIRS = (
    ('"', '"'), ("'", "'"), ("„", "“"), ("«", "»"),
    ("‹", "›"), ("‘", "’"), ("“", "”"),
)


def light_title_cleanup(title: str, artist: str) -> str:
    """
    Minimale Titel-Bereinigung für Fälle ohne YouTube-Parser-Ergebnis.
    Entfernt NUR offensichtliche YouTube-Suffixe und Artist-Präfixe.

    Deutlich konservativer als die volle `clean_track_title_enhanced()` —
    verändert den Titel kaum.

    Args:
        title: Originaler Titel
        artist: Künstlername (für Präfix-Entfernung)

    Returns:
        Bereinigter Titel
    """
    if not title:
        return ""

    cleaned = title.strip()

    # META-11 (+ Nachtrag): "video"/"audio" ohne \b davor matchten auch
    # als reiner Teilstring innerhalb eines laengeren Wortes (deutsches
    # Kompositum "Musikvideo"). Ausserdem erkannte das urspruengliche
    # Klammer-Pattern nur die exakten Wortfolgen "(official [music]
    # video)"/"(audio)" - Kombinationen mit weiteren Woertern wie "HD"
    # ("(Official HD Video)", real via Live-Test-Download reproduziert)
    # oder "(Official Audio)"/"(Official Lyric Video)" fuehrten zum
    # selben Muster: nur das letzte Wort ("Video)"/"Audio)") wurde
    # entfernt, der Rest blieb mit haengender Klammer stehen. Fix:
    # geklammerte Form zuerst - jede schliessende Klammer, deren
    # Inhalt "video" oder "audio" als eigenstaendiges Wort enthaelt,
    # wird komplett entfernt, unabhaengig von sonstigen Woertern davor
    # (analog zum bereits bewaehrten Muster in
    # apply_title_cleanup_rules(), META-03). Klammerlose Form bleibt
    # als separates, engeres Pattern bestehen (kein Klammer-Risiko).
    #
    # Live-Fund 2026-09-03 (Nutzer-Report, echter Testdownload
    # 'GROSSSTADT (Offizieller Visualizer)'): "Visualizer" ist ein
    # eigenstaendiges, gaengiges YouTube-Marketing-Suffix (Musikvideo
    # mit statischem/animiertem Hintergrund statt echtem Video-Content)
    # und enthaelt weder "video" noch "audio" als Wort - das
    # urspruengliche Muster erfasste es daher nicht. Die
    # genre_processor.py::_prepare_search_title()-Bereinigung fuer die
    # externe Genre-API-Suche hatte bereits ein eigenes, explizites
    # "(visualizer)"-Pattern - hier bisher gefehlt, obwohl dies der
    # einzige Pfad fuer Title-/Album-Tag und Dateinamen ist.
    cleaned = re.sub(
        r"\s*\([^()]*\b(?:video|audio|visualizer)\b[^()]*\)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    cleaned = re.sub(
        r"\s*\(?\s*offiziell(?:es|er|em|en)?\s*(?:musik\s*)?video\s*\)?\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    cleaned = re.sub(
        r"\s*(?:official\s+)?(?:music\s+)?\b(?:video|audio)\b\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    cleaned = re.sub(
        r"\s*\[(?:official|music|video|audio)\]\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    cleaned = re.sub(
        r"\s*\(?\s*lyric\s*\bvideo\b\s*\)?\s*$", "", cleaned, flags=re.IGNORECASE
    ).strip()

    # Live-Fund 2026-09-02 (Nutzer-Report, echter Testdownload):
    # 'makko - "ADLIBS" prod. Safecall777' behielt den Produzenten-
    # Credit unveraendert im finalen Titel-Tag - light_title_cleanup()
    # ist der einzige tatsaechlich erreichbare Titel-Cleanup-Pfad
    # (enhanced_metadata_processor.py Schritt 7 ruft ausschliesslich
    # diese Methode auf; clean_track_title_enhanced()/
    # apply_title_cleanup_rules() haben keine Produktionsaufrufer) und
    # hatte bisher gar keine "prod."-Regel. Deckt sowohl die
    # geklammerte Form ("(prod. by X)") als auch die klammerlose,
    # trennerlose Form ("Titel prod. X", ohne Bindestrich) ab - Letztere
    # wird auch von utils/youtube_parser.py::_clean_title_suffixes()
    # nicht erkannt (nur geklammert oder Bindestrich-getrennt, siehe
    # docs/FINDINGS_INDEX.md). \bprod\b mit zwingendem "."/Whitespace
    # danach verhindert Fehltreffer in Woertern wie "Producer"/
    # "Production".
    cleaned = re.sub(
        r"\s*\(\s*prod\.?\s*(?:by\s+)?[^)]*\)", "", cleaned, flags=re.IGNORECASE
    ).strip()
    cleaned = re.sub(
        r"\s*[-–—]?\s*\bprod\.?\s+(?:by\s+)?\S.*$", "", cleaned, flags=re.IGNORECASE
    ).strip()

    # Live-Fund 2026-09-02 (Nutzer-Report, Bibliotheks-Scan von
    # /tmp/musicbot_test/metadaten): Artist "makko" stylisiert seine
    # YouTube-Titel systematisch mit umschliessenden Anfuehrungszeichen
    # ('"ADLIBS"', '"Bequem"', '"Grad mal ein Jahr"', ... - 7 von 13
    # gescannten Tracks betroffen). Die Zeichen selbst wurden bisher nie
    # entfernt. Laeuft bewusst NACH der Produzenten-Credit-Bereinigung
    # oben - ein Titel wie '"ADLIBS" prod. Safecall777' ist VOR dieser
    # Entfernung noch nicht vollstaendig umschlossen (Ende ist "777",
    # nicht das schliessende Anfuehrungszeichen); erst danach wird das
    # umschliessende Paar sichtbar. Entfernt NUR ein Anfuehrungszeichen-
    # Paar, das den GESAMTEN (verbleibenden) Titel umschliesst (Start
    # UND Ende) - ein einzelnes Apostroph MITTEN im Titel (z.B. "It
    # Ain't Me", "als ob ich's einfach haette", beides real in der
    # Library bestaetigt) wird NIE angefasst, da es weder am Anfang
    # noch am Ende steht. Deckt gerade Anfuehrungszeichen sowie die
    # gaengigen typografischen Varianten ab (deutsch/franzoesisch/
    # englisch).
    for _open_q, _close_q in _QUOTE_PAIRS:
        if (
            len(cleaned) >= 2
            and cleaned.startswith(_open_q)
            and cleaned.endswith(_close_q)
        ):
            _inner = cleaned[len(_open_q):-len(_close_q)].strip()
            if _inner:
                cleaned = _inner
            break

    # Artist-Präfix entfernen (z.B. "Ariana Grande - ")
    if artist:
        escaped_artist = re.escape(artist)
        cleaned = re.sub(
            rf"^{escaped_artist}\s*[-–—:|]\s*", "", cleaned, flags=re.IGNORECASE
        ).strip()

    # Live-Fund 2026-09-02 (Nutzer-Report): 'MAKKO 7er STOCK (Dir.'
    # blieb mit haengender, nie geschlossener Klammer stehen - z.B.
    # ein abgeschnittener Regie-/Video-Credit ('(Dir. by X)'), dessen
    # schliessende Klammer im YouTube-Titel fehlt oder abgeschnitten
    # wurde. Bisher gab es hierfuer KEINE Regel in light_title_cleanup()
    # - dasselbe Muster existiert bereits als Sicherheitsnetz (letzte
    # Regel ueberhaupt) in apply_title_cleanup_rules(), das aber keine
    # Produktionsaufrufer hat (siehe Kommentar zur Produzenten-Credit-
    # Bereinigung oben). Entfernt eine nie geschlossene Klammer '(' oder
    # '[' bis zum Titelende - bewusst als letzte Regel, faengt auf, was
    # von allen vorherigen, spezifischeren Regeln uebrig bleibt.
    cleaned = re.sub(r"\s*\([^)]*$", "", cleaned).strip()
    cleaned = re.sub(r"\s*\[[^\]]*$", "", cleaned).strip()

    # Mehrfache Leerzeichen normalisieren
    cleaned = re.sub(r"\s+", " ", cleaned)

    return cleaned if cleaned else title
