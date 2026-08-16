"""
Regressionstest für einen Path-Traversal-Fund in Phase 2: sanitize_filename()
(utils/helpers.py) entfernte Schrägstriche und andere Illegal-Zeichen, aber
keine literalen Punkte. Ein Wert wie ".." überstand die Bereinigung
unverändert und konnte als Pfadsegment (z.B. Artist-Tag) das Zielverzeichnis
in FilenameFixerTool.build_final_path() verlassen (siehe
tests/test_filenamefixer.py für den End-to-End-Nachweis dieses Effekts).
"""

from utils.helpers import sanitize_filename


class TestSanitizeFilenamePathTraversal:
    def test_double_dot_is_neutralized(self):
        assert sanitize_filename("..") != ".."

    def test_single_dot_is_neutralized(self):
        assert sanitize_filename(".") != "."

    def test_multiple_dots_are_neutralized(self):
        assert sanitize_filename("...") != "..."

    def test_double_dot_with_whitespace_is_neutralized(self):
        # ILLEGAL_CHARS_PATTERN/EXTRA_SPACES_PATTERN reduzieren " .. " -> "..".
        assert sanitize_filename(" .. ") != ".."

    def test_legitimate_dots_within_text_are_preserved(self):
        # Nur ein Ergebnis, das AUSSCHLIESSLICH aus Punkten besteht, ist ein
        # Traversal-Token - normale Namen mit Punkten bleiben unangetastet.
        assert sanitize_filename("Dr. Dre") == "Dr. Dre"
        assert sanitize_filename("Vol. 2") == "Vol. 2"
        assert sanitize_filename("Track... Reprise") == "Track... Reprise"


class TestSanitizeFilenameExistingBehavior:
    def test_none_returns_empty_string(self):
        assert sanitize_filename(None) == ""

    def test_illegal_path_characters_are_stripped(self):
        result = sanitize_filename('Artist: "Weird"/Name')
        assert "/" not in result
        assert '"' not in result
        assert ":" not in result
