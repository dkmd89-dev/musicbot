"""
DUP-05 (docs/FINDINGS_INDEX.md, urspruenglich docs/archive/
MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md): Check-then-
Register-Race ohne Lock. Zwischen einem "kein Duplikat"-Ergebnis von
check_for_duplicates() und der tatsaechlichen Registrierung via
register_download() liegt die komplette Download+Verarbeitungsdauer
(Sekunden bis Minuten) - ein zweiter, paralleler Request fuer dieselbe
URL/denselben Content sah in dieser Zeit ebenfalls "kein Duplikat".

Fix: In-Memory-"in Bearbeitung"-Markierung (URL-Hash und Content-Hash),
TTL-basiert selbstheilend (kein zwingendes try/finally an der
Aufrufstelle noetig), sofort freigegeben bei tatsaechlichem
register_download()-Erfolg.

Nutzt dieselbe FakeConfig-Struktur wie test_duplicate_handler.py (inkl.
isolierter GENRE_MAPPING_DIR-Kopie, siehe P1-Audit fuer die Begruendung).
"""

from pathlib import Path
import shutil

import pytest

from services.duplicate.detector import DuplicateDetector


class FakeConfig:
    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")
        mapping_dest = tmp_path / "mapping"
        if not mapping_dest.exists():
            shutil.copytree(
                Path(__file__).resolve().parent.parent / "mapping", mapping_dest
            )
        self.GENRE_MAPPING_DIR = mapping_dest


@pytest.fixture
def handler(tmp_path):
    return DuplicateDetector(FakeConfig(tmp_path))


class TestInFlightUrlRace:
    def test_second_check_for_same_url_is_detected_as_in_flight(self, handler):
        """Simuliert zwei nahezu gleichzeitige Requests fuer dieselbe URL:
        der erste Check findet kein Duplikat (Download wuerde jetzt
        beginnen), der zweite - noch vor register_download() - muss
        jetzt als in_flight erkannt werden statt ebenfalls durchzulaufen."""
        url = "https://www.youtube.com/watch?v=RACE001"

        is_dup_1, entry_1, reason_1 = handler.check_for_duplicates(url)
        assert is_dup_1 is False
        assert reason_1 == "none"

        is_dup_2, entry_2, reason_2 = handler.check_for_duplicates(url)
        assert is_dup_2 is True
        assert reason_2 == "in_flight"
        assert entry_2 is None

    def test_completed_download_switches_from_in_flight_to_permanent_url_duplicate(
        self, handler
    ):
        """Nach erfolgreichem register_download() muss ein weiterer Check
        weiterhin als Duplikat erkannt werden - jetzt ueber die
        permanente url-Ebene, nicht mehr ueber in_flight."""
        url = "https://www.youtube.com/watch?v=RACE002"

        handler.check_for_duplicates(url)
        handler.register_download(url, "Some Artist", "Some Song")

        is_dup, entry, reason = handler.check_for_duplicates(url)
        assert is_dup is True
        assert reason == "url"
        assert entry is not None

    def test_in_flight_claim_is_released_after_register_download(self, handler):
        """Direkter Beleg, dass register_download() den In-Flight-Claim
        aufraeumt (Hygiene, siehe Kommentar in register_download())."""
        url = "https://www.youtube.com/watch?v=RACE003"

        handler.check_for_duplicates(url)
        url_hash = handler.duplicate_cache.get_url_hash(url)
        assert url_hash in handler._in_flight

        handler.register_download(url, "Some Artist", "Some Song")
        assert url_hash not in handler._in_flight


class TestInFlightContentRace:
    def test_second_check_for_same_artist_title_different_url_is_in_flight(
        self, handler
    ):
        """Zwei verschiedene URLs (z.B. Reupload unter neuer Video-ID),
        aber derselbe Artist/Titel - die Content-Ebene des In-Flight-
        Checks muss das zweite gleichzeitige Request-Paar erkennen."""
        is_dup_1, _, reason_1 = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=RACE004",
            raw_artist="Some Artist",
            raw_title="Some Song",
        )
        assert is_dup_1 is False
        assert reason_1 == "none"

        is_dup_2, entry_2, reason_2 = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=RACE005",
            raw_artist="Some Artist",
            raw_title="Some Song",
        )
        assert is_dup_2 is True
        assert reason_2 == "in_flight"
        assert entry_2 is None


class TestInFlightTtlSelfHealing:
    def test_stale_in_flight_entry_expires_and_does_not_block_forever(
        self, handler
    ):
        """Ein verwaister In-Flight-Eintrag (z.B. durch Absturz/Exception
        waehrend eines Downloads ohne register_download()) darf einen
        spaeteren, echten Download-Versuch nicht dauerhaft blockieren -
        nach Ablauf der TTL muss der Check wieder normal durchlaufen."""
        url = "https://www.youtube.com/watch?v=RACE006"

        handler.check_for_duplicates(url)
        url_hash = handler.duplicate_cache.get_url_hash(url)
        assert url_hash in handler._in_flight

        # TTL kuenstlich in die Vergangenheit verschieben, statt in einem
        # Test tatsaechlich zu warten.
        handler._in_flight[url_hash] -= handler._in_flight_ttl_seconds + 1

        is_dup, entry, reason = handler.check_for_duplicates(url)
        assert is_dup is False
        assert reason == "none"
        # Abgelaufener Eintrag wurde beim Pruefen entfernt, nicht nur
        # ignoriert - und durch den erneuten "kein Duplikat"-Durchlauf
        # sofort neu geclaimt (aktueller Zeitstempel).
        assert url_hash in handler._in_flight
        assert handler._in_flight[url_hash] > handler._in_flight_ttl_seconds

    def test_in_flight_ttl_is_configurable_via_config(self, tmp_path):
        class FakeConfigWithTtl(FakeConfig):
            def __init__(self, tmp_path):
                super().__init__(tmp_path)
                self.DUPLICATE_IN_FLIGHT_TTL_SECONDS = 5

        handler = DuplicateDetector(FakeConfigWithTtl(tmp_path))
        assert handler._in_flight_ttl_seconds == 5


class TestInFlightDoesNotAffectUnrelatedChecks:
    def test_different_url_and_content_is_not_affected(self, handler):
        """Gegenprobe: ein In-Flight-Claim fuer URL/Content A darf einen
        unabhaengigen Check fuer URL/Content B nicht beeinflussen."""
        handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=RACE007",
            raw_artist="Artist A",
            raw_title="Song A",
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=RACE008",
            raw_artist="Artist B",
            raw_title="Song B",
        )
        assert is_dup is False
        assert reason == "none"
