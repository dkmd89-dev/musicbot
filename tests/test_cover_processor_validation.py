"""
Regressionstest fuer eine in Phase 3 gefundene Validierungsluecke in
CoverProcessor._validate_and_score() (services/downloader/utils/metadata/
cover_processor.py), siehe docs/MusicBot_ENGINEERING_BASELINE.md.

_analyze_image_quality() faengt PIL-Parse-Fehler ab und liefert dann
width=0, height=0 zurueck (kein Crash). Die alte Bedingung
"if w > 0 and (w < 100 or h < 100): ignorieren" ueberprang den
Aufloesungs-Check komplett, wenn w == 0 war - ein Nicht-Bild-Blob
(z.B. eine mit HTTP 200 zurueckgegebene HTML-Fehlerseite oder sonstiger
Muell), der nur die Mindestgroesse (_MIN_IMAGE_BYTES = 5000 Bytes) erfuellt,
rutschte dadurch durch und konnte als "Cover Art" in die Audiodatei
eingebettet werden.
"""

import io

from PIL import Image

from services.downloader.utils.metadata.cover_processor import (
    CoverProcessor,
    _MIN_IMAGE_BYTES,
)


def make_jpeg_bytes(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    data = buf.getvalue()
    if len(data) < _MIN_IMAGE_BYTES:
        data += b"\x00" * (_MIN_IMAGE_BYTES - len(data) + 100)
    return data


def make_processor():
    return CoverProcessor(cache_enabled=False)


class TestNonImageBlobIsRejected:
    def test_html_error_page_is_rejected_despite_meeting_size_minimum(self):
        processor = make_processor()
        # Groesser als _MIN_IMAGE_BYTES, aber kein gueltiges Bild.
        fake_html_error_page = b"<html><body>Not Found</body></html>" + b" " * _MIN_IMAGE_BYTES

        result = processor._validate_and_score("test_source", fake_html_error_page)

        assert result is None

    def test_random_bytes_above_size_minimum_are_rejected(self):
        processor = make_processor()
        garbage = b"\x00\x01\x02\x03" * (_MIN_IMAGE_BYTES // 2)

        result = processor._validate_and_score("test_source", garbage)

        assert result is None


class TestValidImageStillPasses:
    def test_real_image_above_min_resolution_is_accepted(self):
        processor = make_processor()
        data = make_jpeg_bytes(200, 200)

        result = processor._validate_and_score("test_source", data)

        assert result is not None
        assert result.width == 200
        assert result.height == 200

    def test_real_image_below_min_resolution_is_rejected(self):
        processor = make_processor()
        data = make_jpeg_bytes(50, 50)

        result = processor._validate_and_score("test_source", data)

        assert result is None
