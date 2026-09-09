"""
Live-Fund 2026-09-09 (End-to-End-Testdownload über den echten Test-Bot,
docs/FINDINGS_INDEX.md): der YouTube-Titel
"Leony - Remedy @ Deluxe Music Session 2022" ergab den Songtitel
"Remedy @ Deluxe Music Session" (in Titel-Tag, Album-Tag und Dateiname).

YouTube-Uploads von TV-/Radio-/Live-Session-Auftritten hängen den Session-
bzw. Sendungsnamen mit " @ " an den eigentlichen Songtitel an
("@ Deluxe Music Session", "@ MTV Unplugged", "@ Rock am Ring"). Das ist
nicht Teil des Songnamens.

Fix in utils/youtube_parser.py::_clean_title_suffixes() (Erfolgspfad nach
Artist/Titel-Split, analog zum bereits dort behandelten Upload-Jahr-Suffix
"Die Eine 2005" → "Die Eine"): ein am Titelende stehendes " @ <Rest>"
(Leerzeichen auf beiden Seiten des @) wird abgeschnitten. Läuft vor der
Jahres-Regel, damit ein nachgestelltes Jahr gleich mitgeht.

Bewusst NICHT in einer allgemein genutzten Titel-Bereinigung
(title_cleaner.light_title_cleanup) - dieselbe Regel könnte dort einen
legitimen, anderweitig gebrauchten " @ " treffen; im Erfolgspfad dieser
Funktion ist der Kontext (bereits als Artist/Titel erkannt) enger.
"""

import pytest

from utils.youtube_parser import parse_youtube_title


class TestLiveSessionSuffixIsStripped:
    @pytest.mark.parametrize(
        "raw_title, expected_song",
        [
            ("Leony - Remedy @ Deluxe Music Session 2022", "Remedy"),
            ("Leony - Remedy @ Deluxe Music Session", "Remedy"),
            ("Peter Fox - Haus am See @ MTV Unplugged", "Haus am See"),
            ("Nina Chuba - Wildberry Lillet @ 1LIVE Session", "Wildberry Lillet"),
            ("Apache 207 - Roller @ Radio Session 2019", "Roller"),
        ],
    )
    def test_session_marker_removed(self, raw_title, expected_song):
        result = parse_youtube_title(raw_title)
        assert result["song_title"] == expected_song


class TestNormalTitlesUnaffected:
    """Regressions-Guard: Titel ohne freistehendes ' @ ' bleiben
    unverändert - der Fix ist eng auf die Session-Suffix-Form begrenzt."""

    @pytest.mark.parametrize(
        "raw_title, expected_song",
        [
            ("Sido - Bilder im Kopf", "Bilder im Kopf"),
            ("Cro - Easy", "Easy"),
            ("AnnenMayKantereit - Oft gefragt (Live)", "Oft gefragt"),
            ("Peter Fox - Haus am See", "Haus am See"),
            ("Kontra K - Erfolg ist kein Glück", "Erfolg ist kein Glück"),
        ],
    )
    def test_title_without_at_marker_is_unchanged(self, raw_title, expected_song):
        result = parse_youtube_title(raw_title)
        assert result["song_title"] == expected_song
