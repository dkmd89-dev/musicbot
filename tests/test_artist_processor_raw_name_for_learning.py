"""
Live-Fund 2026-09-03 (Nutzer-Report, echter Testdownload): der Repost-/
Compilation-Kanal "GermanHype" lernte faelschlich einen Alias
'GermanHype' -> 'Peter Maffay' in auto_learned_artist_aliases.json, obwohl
der Titel-Parser 'Peter Maffay' korrekt AUS DEM TITEL erkannt hatte
(artist_source='youtube_parsed', NICHT 'channel_fallback' - der Kanalname
war an der eigentlichen Artist-Bestimmung gar nicht beteiligt).

Root Cause: enhanced_metadata_processor.py verwendete
track_metadata.get("uploader") IMMER PRIORITAER als raw_name fuer
AutoLearnManager.learn_artist() - unabhaengig von der artist_source. Im
Normalfall (eigener Kuenstler-Kanal) ist das korrekt und sogar
erwuenscht: der Kanalname IST dort meist die authentische, rohe
Schreibweise des Kuenstlernamens (z.B. Kanal 'MAKKO' waehrend der
normalisierte Name 'Makko' lautet) - das Lernen von Schreibvarianten
funktioniert nur deshalb. Bei Repost-/Compilation-Kanaelen weicht der
Kanalname aber komplett vom tatsaechlich erkannten Kuenstler ab.

Verworfener erster Loesungsansatz: raw_name pauschal auf
track_metadata.get("artist") umstellen (statt uploader) - waere ZU BREIT
gewesen, da dieses Feld bei den meisten YouTube-Downloads (gerade bei
artist_source='youtube_parsed', wo der Artist ja WEIL kein strukturiertes
artist-Feld vorhanden aus dem Titel geparst werden musste) leer ist -
haette das gesamte automatische Alias-Learning fuer die haeufigste Quelle
faktisch stillgelegt.

Fix: ArtistProcessor.raw_name_for_learning() - eine reine, gezielte
Aehnlichkeitspruefung. Der Kanalname (uploader) wird nur dann als roher
Name fuer das Lernen verwendet, wenn er dem bereits bestimmten
canonical_name tatsaechlich aehnelt (identisch oder Teilstring in eine
der beiden Richtungen, case-insensitiv) - andernfalls wird KEIN roher
Name geliefert (kein Alias-Learning fuer offensichtlich unterschiedliche
Kanal-/Kuenstler-Namen-Paare).
"""

from services.metadata.artist_processor import ArtistProcessor


def _processor():
    return ArtistProcessor(artist_normalizer=None)


class TestRawNameForLearningNormalCase:
    """Der haeufigste, unveraenderte Fall: eigener Kuenstler-Kanal, uploader
    aehnelt dem canonical_name - Kanalname wird weiterhin gelernt."""

    def test_exact_match_uses_uploader(self):
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "Makko"}, canonical_name="Makko"
        )
        assert result == "Makko"

    def test_case_variant_uses_uploader(self):
        """Der eigentliche Lern-Zweck: Kanal 'MAKKO' (roh) -> normalisiert
        'Makko' - genau das muss weiterhin funktionieren."""
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "MAKKO"}, canonical_name="Makko"
        )
        assert result == "MAKKO"

    def test_uploader_is_substring_of_canonical(self):
        """z.B. Kanal 'Miksu' fuer Duo 'Miksu & Macloud'."""
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "Miksu"}, canonical_name="Miksu & Macloud"
        )
        assert result == "Miksu"

    def test_canonical_is_substring_of_uploader(self):
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "Makko - Topic"}, canonical_name="Makko"
        )
        assert result == "Makko - Topic"


class TestRawNameForLearningRepostChannel:
    """Live-Fund: Repost-/Compilation-Kanal, Kanalname hat nichts mit dem
    tatsaechlich erkannten Kuenstler zu tun - darf NICHT gelernt werden."""

    def test_germanhype_peter_maffay_case_returns_empty(self):
        """Der real reproduzierte Bug-Fall."""
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "GermanHype"}, canonical_name="Peter Maffay"
        )
        assert result == ""

    def test_germanhype_oimara_case_returns_empty(self):
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "GermanHype"}, canonical_name="Oimara"
        )
        assert result == ""

    def test_falls_back_to_artist_field_when_present(self):
        """Verwirft der Kanalname wegen Unaehnlichkeit, faellt aber auf
        ein tatsaechlich vorhandenes track_metadata['artist']-Feld zurueck,
        falls dieses (selten) gesetzt ist."""
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "GermanHype", "artist": "Peter Maffay"},
            canonical_name="Peter Maffay",
        )
        assert result == "Peter Maffay"


class TestRawNameForLearningEdgeCases:
    def test_no_uploader_falls_back_to_artist_field(self):
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"artist": "Some Artist"}, canonical_name="Some Artist"
        )
        assert result == "Some Artist"

    def test_nothing_available_returns_empty(self):
        processor = _processor()
        result = processor.raw_name_for_learning({}, canonical_name="Artist")
        assert result == ""

    def test_no_canonical_name_still_uses_uploader(self):
        """Ohne canonical_name kann keine Aehnlichkeit geprueft werden -
        konservativ das bisherige Verhalten (uploader bevorzugt)
        beibehalten, kein Overreach in einen nicht beobachteten Fall."""
        processor = _processor()
        result = processor.raw_name_for_learning(
            {"uploader": "SomeChannel"}, canonical_name=""
        )
        assert result == "SomeChannel"
