# tests/test_title_cleanup_pure.py
# -*- coding: utf-8 -*-
"""
utils/title_cleanup.py — reine, aus TitleCleaner ausgelagerte
light_title_cleanup-Logik.

Kern-Anliegen: (1) das Verhalten ist unveraendert gegenueber der frueheren
Methode (die bestehenden tests/test_title_cleaner_*.py bleiben die
eigentliche Charakterisierung), (2) TitleCleaner.light_title_cleanup
delegiert byte-genau hierher, (3) der Import zieht keine services/metadata-
Schreib-Module mit (Grund der Auslagerung: read-only Health-Scanner).
"""

import sys

import pytest

from utils.title_cleanup import light_title_cleanup


@pytest.mark.parametrize("raw,artist,expected", [
    ('"Ausreden"', "makko", "Ausreden"),
    ('"ADLIBS" prod. Safecall777', "makko", "ADLIBS"),
    ('"WEIN" prod. @clipz_500 @xarbeats', "makko", "WEIN"),
    ("Jänner", "makko", "Jänner"),
    ("LOLLAPALOOZA 2026", "makko", "LOLLAPALOOZA 2026"),
    ("fr fr (feat. Boloboys, toobrokeforfiji, beslik)", "makko",
     "fr fr (feat. Boloboys, toobrokeforfiji, beslik)"),
    ("Song (Official Video)", "X", "Song"),
    ("MAKKO 7er STOCK (Dir.", "makko", "MAKKO 7er STOCK"),
    ("makko - Titel", "makko", "Titel"),
    ("It Ain't Me", "X", "It Ain't Me"),   # Apostroph MITTEN im Titel bleibt
    ("", "X", ""),
])
def test_known_cases(raw, artist, expected):
    assert light_title_cleanup(raw, artist) == expected


def test_titlecleaner_method_delegates_identically():
    from services.metadata.title_cleaner import TitleCleaner

    tc = TitleCleaner()
    samples = [
        ('"Peoplepleasing"', "makko"),
        ('"ADLIBS" prod. Safecall777', "makko"),
        ("Track (Official Audio)", "Band"),
        ("Ganz normaler Titel", "Band"),
        ("Artist - Song", "Artist"),
    ]
    for raw, artist in samples:
        assert tc.light_title_cleanup(raw, artist) == light_title_cleanup(raw, artist)


def test_import_pulls_no_metadata_writer_modules():
    """utils.title_cleanup muss ohne services.metadata (TagWriter/
    EnhancedMetadataProcessor im __init__) importierbar sein — sonst ist der
    Zweck der Auslagerung (read-only Health-Scanner) verfehlt."""
    import subprocess

    code = (
        "import sys; import utils.title_cleanup; "
        "bad=[m for m in ('services.metadata','services.metadata.tag_writer',"
        "'services.metadata.enhanced_metadata_processor') if m in sys.modules]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"Schreib-Module mitgezogen: {result.stdout.strip()}"
