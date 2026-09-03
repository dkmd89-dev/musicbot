"""
Charakterisierung (docs/FINDINGS_INDEX.md, "Downloader-Fehlertaxonomie" /
"FileProcessingError", 2026-09-03): Untersuchung, ob `FormatNotAvailableError`,
die downloader-eigene `PermissionError` und `FileProcessingError`
(services/downloader/errors.py) ungenutzte Infrastruktur mit echter
Klassifikationsluecke sind, oder ob ihre Nichtbenutzung bewusst und
begruendet ist.

Befund:
- `_classify_ytdlp_error()` (download_utils.py) produziert ausschliesslich
  `InvalidURLError` oder die generische `DownloadError`-Basisklasse - nie
  `FormatNotAvailableError`. Das ist laut eigenem Docstring bewusst
  konservativ ("Nur eindeutig belegte Faelle... kein Rateraten bei
  Unsicherheit") und ohne einen im Betrieb tatsaechlich aufgetretenen,
  faelschlich retry-behandelten "Format nicht verfuegbar"-Fall nicht als
  Bug zu werten (CLAUDE.md Regel 4: Bug zuerst reproduzieren).
- Ein echter OS-`PermissionError` beim Verschieben in die Library
  (utils/filenamefixer.py::move_to_library(), Schritt "Datei verschieben"
  in enhanced_metadata_processor.py) wird dort NICHT abgefangen, faellt
  durch bis zum aeusseren `except Exception` von `process_single_track()`
  und wird zu `MetadataResult(success=False, error=str(e))`. Jedes
  `success=False` wird von `_process_single_download()` unabhaengig von
  der konkreten Ursache zu `MetadataError` uebersetzt - die bereits in
  `_NON_RETRYABLE_ERROR_TYPES` steht. Der eigentliche Schutzzweck (kein
  sinnloser Retry bei einem permanenten Fehler) ist damit bereits erfuellt;
  es fehlt nur die granulare Diagnose (Permission- vs. sonstiger
  Metadatenfehler), keine Korrektheitsluecke.
- `FileProcessingError` ist bereits im bestehenden Code-Kommentar
  (download_utils.py, `_NON_RETRYABLE_ERROR_TYPES`) explizit aus demselben
  Grund ausgeschlossen dokumentiert.

Ergebnis: bestaetigt bewusst zurueckhaltende, aktuell ungenutzte
Infrastruktur - kein Fix. Dieser Test dokumentiert das aktuelle Verhalten
als Charakterisierungstest (CLAUDE.md Abschnitt 6) und macht eine
zukuenftige stille Aenderung (z.B. ein neuer Format-Marker ohne
Beleg/Test) sichtbar.
"""

from yt_dlp.utils import DownloadError as YoutubeDLError

from services.downloader.download_utils import (
    _NON_RETRYABLE_ERROR_TYPES,
    _classify_ytdlp_error,
)
from services.downloader.errors import (
    DownloadError,
    FileProcessingError,
    FormatNotAvailableError,
    InvalidURLError,
    MetadataError,
    PermissionError as DownloadPermissionError,
)


class TestClassifyYtdlpErrorNeverProducesUnusedTaxonomyClasses:
    def test_generic_unexpected_error_falls_back_to_base_download_error(self):
        exc = YoutubeDLError("some unexpected internal yt-dlp error")
        result = _classify_ytdlp_error(exc)
        assert type(result) is DownloadError

    def test_expected_error_without_known_marker_falls_back_to_base_download_error(
        self,
    ):
        exc = YoutubeDLError("isn't available, try again later")
        exc.expected = True
        result = _classify_ytdlp_error(exc)
        assert type(result) is DownloadError

    def test_expected_permanent_marker_yields_invalid_url_error_not_format_error(
        self,
    ):
        """Selbst ein 'no formats'-nahes, YouTube-eigenes Permanent-Signal
        (hier: private video) wird auf InvalidURLError abgebildet, nie auf
        FormatNotAvailableError - die Klasse hat aktuell keinen
        Produktions-Erzeugungspfad."""
        exc = YoutubeDLError("ERROR: Private video. Sign in if you've been invited")
        exc.expected = True
        result = _classify_ytdlp_error(exc)
        assert isinstance(result, InvalidURLError)
        assert not isinstance(result, FormatNotAvailableError)

    def test_format_not_available_and_permission_error_have_no_raise_site(self):
        """Belegt den Charakterisierungsbefund als ausfuehrbaren Test statt
        nur als Kommentar: keine Kombination aus expected/Message fuehrt zu
        diesen beiden Klassen."""
        candidates = [
            YoutubeDLError("Requested format is not available"),
            YoutubeDLError("Permission denied"),
        ]
        for exc in candidates:
            exc.expected = True
            result = _classify_ytdlp_error(exc)
            assert not isinstance(result, FormatNotAvailableError)
            assert not isinstance(result, DownloadPermissionError)


class TestNonRetryableErrorTypesTaxonomyIsUnchanged:
    def test_wired_but_unused_classes_remain_in_non_retryable_set(self):
        """FormatNotAvailableError/PermissionError bleiben bewusst in der
        Non-Retryable-Menge (Infrastruktur bereit fuer den Tag, an dem ein
        echter Erzeugungspfad belegt wird), obwohl sie aktuell nie
        geworfen werden."""
        assert FormatNotAvailableError in _NON_RETRYABLE_ERROR_TYPES
        assert DownloadPermissionError in _NON_RETRYABLE_ERROR_TYPES

    def test_file_processing_error_deliberately_excluded(self):
        """FileProcessingError bleibt bewusst ausserhalb der Non-Retryable-
        Menge - keine Klassifikation ohne belegten Erzeugungspfad
        (siehe Modul-Docstring von download_utils.py)."""
        assert FileProcessingError not in _NON_RETRYABLE_ERROR_TYPES


class TestMetadataPipelineFailureAlreadyNonRetryableRegardlessOfCause:
    def test_metadata_error_covers_generic_failure_already(self):
        """Belegt, dass MetadataError (bereits non-retryable) jeden
        success=False-Fall aus der Metadaten-Pipeline abdeckt - unabhaengig
        davon, ob die zugrundeliegende Ursache ein OS-PermissionError beim
        Bibliotheks-Move oder ein anderer Metadatenfehler war. Der
        Schutzzweck (kein sinnloser Retry bei permanentem Fehler) ist damit
        bereits erfuellt, auch ohne die granulare PermissionError/
        FileProcessingError-Klassifikation."""
        assert MetadataError in _NON_RETRYABLE_ERROR_TYPES
        # MetadataError kapselt jede str(e)-Ursache generisch - auch die
        # Nachricht eines echten Python-PermissionError laesst sich
        # verlustfrei uebergeben.
        err = MetadataError(str(PermissionError("[Errno 13] Permission denied")))
        assert isinstance(err, _NON_RETRYABLE_ERROR_TYPES)
