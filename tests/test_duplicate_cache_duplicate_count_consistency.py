"""
Charakterisierung + Fix: duplicate_count-Inkonsistenz zwischen URL- und
Content-Pfad (2026-09-03, Nutzer-Auftrag "duplicate_count sauber
charakterisieren und entscheiden").

Untersuchung (Schritte 1-4 des Auftrags) ergab: duplicate_count wird
repoweit NIRGENDWO ausserhalb von services/duplicate/cache.py gelesen/
angezeigt/ausgewertet (kein Reporting, keine Statistik, keine Business-
Entscheidung haengt davon ab) - es ist reine Persistenz-Telemetrie ("wie
oft wurde dieser Eintrag als Duplikat erkannt"). Kein bestehender Test
deckte das Feld ab.

Gefundene Asymmetrie:
- DuplicateCache.check_url_duplicate() erhoehte duplicate_count bei JEDEM
  Lese-Treffer (auch reine Checks, unabhaengig davon ob der Download
  danach tatsaechlich abgebrochen wird) - aber OHNE anschliessendes
  _save_caches(), also nicht zuverlaessig persistiert.
- DuplicateCache.check_content_duplicate() mutierte NIE bei einem reinen
  Check - nur add_entry() erhoehte den Zaehler, was bei einem erkannten
  Content-Duplikat aber gerade NICHT aufgerufen wird (der Download bricht
  ab, es wird kein neuer Eintrag registriert).

Live an echten Testdaten belegt (/tmp/musicbot_test/cache/duplicate_cache/):
"Zartmann - wie du manchmal fehlst" hatte in url_duplicates.json zwei
Eintraege mit duplicate_count 2 und 12 (mehrfach angefragte URL-Varianten),
aber in content_duplicates.json nur einen Eintrag mit duplicate_count 2 -
der Content-Zaehler blieb praktisch immer bei 1-2, unabhaengig davon wie
oft der Track tatsaechlich als Duplikat erkannt wurde.

Nutzer-Entscheidung (nach vorgelegten Trade-off-Optionen): "Konsistent
zaehlen" - beide Pfade zaehlen gleich (jeder erkannte Treffer erhoeht den
Zaehler, auch reine Checks) und werden zuverlaessig persistiert.

Fix: check_content_duplicate() erhoeht duplicate_count jetzt genauso wie
check_url_duplicate() bei einem Treffer; beide rufen anschliessend
_save_caches() auf.
"""

from datetime import datetime

import pytest

from services.downloader.models import DuplicateEntry
from services.duplicate.cache import DuplicateCache


@pytest.fixture
def cache(tmp_path):
    return DuplicateCache(cache_dir=str(tmp_path / "duplicate_cache"))


def _entry(artist="Some Artist", title="Some Song", url="https://youtu.be/ABC123"):
    return DuplicateEntry(
        artist=artist,
        title=title,
        url=url,
        file_path=None,
        download_date=datetime.now(),
    )


class TestCheckUrlDuplicateIncrementsAndPersists:
    """Charakterisiert das bereits vorhandene, korrekte Teilverhalten des
    URL-Pfads - Referenzverhalten fuer den Content-Pfad-Fix unten."""

    def test_hit_increments_counter(self, cache):
        cache.add_entry(_entry(url="https://youtu.be/ABC123"))
        result = cache.check_url_duplicate("https://youtu.be/ABC123")
        assert result.duplicate_count == 2

    def test_hit_is_persisted_to_disk(self, cache):
        cache.add_entry(_entry(url="https://youtu.be/ABC123"))
        cache.check_url_duplicate("https://youtu.be/ABC123")

        # Frisch von Platte laden - Instanz-State darf nicht der einzige
        # Ort sein, an dem der erhoehte Zaehler existiert.
        reloaded = DuplicateCache(cache_dir=str(cache.cache_path))
        entry = reloaded.check_url_duplicate("https://youtu.be/ABC123")
        assert entry.duplicate_count == 3, (
            "der Zaehlerstand nach dem ersten check_url_duplicate()-Treffer "
            "(2) muss persistiert worden sein, bevor der dritte Treffer "
            "(dieser reload-Check) ihn erneut erhoeht"
        )

    def test_no_hit_does_not_increment_or_error(self, cache):
        result = cache.check_url_duplicate("https://youtu.be/NOTHING")
        assert result is None


class TestCheckContentDuplicateIncrementsAndPersists:
    """Der eigentliche Fix: Content-Pfad muss sich jetzt identisch zum
    URL-Pfad verhalten (Nutzer-Entscheidung 'Konsistent zaehlen')."""

    def test_hit_increments_counter(self, cache):
        cache.add_entry(_entry(artist="Some Artist", title="Some Song"))
        result = cache.check_content_duplicate("Some Artist", "Some Song")
        assert result.duplicate_count == 2, (
            "check_content_duplicate() muss den Zaehler bei einem Treffer "
            "genauso erhoehen wie check_url_duplicate()"
        )

    def test_hit_is_persisted_to_disk(self, cache):
        cache.add_entry(_entry(artist="Some Artist", title="Some Song"))
        cache.check_content_duplicate("Some Artist", "Some Song")

        reloaded = DuplicateCache(cache_dir=str(cache.cache_path))
        entry = reloaded.check_content_duplicate("Some Artist", "Some Song")
        assert entry.duplicate_count == 3

    def test_no_hit_does_not_increment_or_error(self, cache):
        result = cache.check_content_duplicate("Nobody", "Nothing")
        assert result is None

    def test_multiple_hits_accumulate(self, cache):
        cache.add_entry(_entry(artist="Some Artist", title="Some Song"))
        for _ in range(4):
            cache.check_content_duplicate("Some Artist", "Some Song")
        result = cache.check_content_duplicate("Some Artist", "Some Song")
        assert result.duplicate_count == 6


class TestUrlAndContentPathsCountSymmetrically:
    """Kernanliegen der Nutzer-Entscheidung: bei derselben Anzahl Treffer
    muessen beide Pfade denselben ZUWACHS zeigen.

    Nebenfund waehrend der Testentwicklung: add_entry() legt bei einer
    Erstanlage DIESELBE DuplicateEntry-Objektreferenz sowohl in url_cache
    als auch in content_cache ab (kein Kopieren) - ein Inkrement ueber
    EINEN Pfad wirkt sich dadurch automatisch auch auf den anderen Pfad
    aus, solange beide (noch) auf dasselbe Objekt zeigen (Normalfall: nur
    ein add_entry()-Aufruf fuer diesen Track bisher). Um trotzdem die
    Pfade UNABHAENGIG voneinander zu pruefen (nicht nur zufaellig gleich,
    weil es dasselbe Objekt ist), verwendet dieser Test zwei komplett
    getrennte Cache-Instanzen - eine nur ueber den URL-Pfad, eine nur
    ueber den Content-Pfad angefragt - und vergleicht den ZUWACHS
    (delta), nicht den absoluten Endwert."""

    def test_same_number_of_hits_yields_same_delta(self, tmp_path):
        url_only_cache = DuplicateCache(cache_dir=str(tmp_path / "url_only"))
        content_only_cache = DuplicateCache(cache_dir=str(tmp_path / "content_only"))

        url_only_cache.add_entry(_entry(url="https://youtu.be/SYM001"))
        content_only_cache.add_entry(_entry(url="https://youtu.be/SYM001"))

        before_url = url_only_cache.check_url_duplicate(
            "https://youtu.be/SYM001"
        ).duplicate_count
        before_content = content_only_cache.check_content_duplicate(
            "Some Artist", "Some Song"
        ).duplicate_count

        for _ in range(3):
            after_url = url_only_cache.check_url_duplicate(
                "https://youtu.be/SYM001"
            ).duplicate_count
            after_content = content_only_cache.check_content_duplicate(
                "Some Artist", "Some Song"
            ).duplicate_count

        assert (after_url - before_url) == (after_content - before_content) == 3
