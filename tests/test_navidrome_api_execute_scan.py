"""
Charakterisierungstests fuer den api/navidrome_api.py-Rest (ARCH-009
Phase 8).

Der reine Navidrome-API-Adapter wurde nach services/clients/navidrome_api.py
verschoben (siehe tests/test_navidrome_api_characterization.py, Option B
in docs/MusicBot_ARCH-009_Phase8_Zielverschiebung_ServicesClients_Analyse.md).
execute_scan() ist bewusst NICHT Teil dieser Verschiebung - delegiert an
NavidromeScanTrigger (lokale Docker-/Subprocess-Steuerung, keine echte
Subsonic-API-Kommunikation, siehe ARCH-009 Phase 3/6) und bleibt als
eigenstaendige Rest-Klasse api.navidrome_api.NavidromeAPI erhalten.

Diese Tests sind unveraendert aus der vorherigen
TestExecuteScan-Testklasse in tests/test_navidrome_api_characterization.py
uebernommen (nur der Speicherort hat sich geaendert) - verifizieren
weiterhin den seit ARCH-009 Phase 5 geltenden Pass-Through-Vertrag: gibt
execute_scan() unveraendert das ScanRunResult von
NavidromeScanTrigger.run_scan() zurueck bzw. reicht es dessen Exceptions
(ScanTimeoutError, AttributeError, ...) unveraendert durch?
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from api.navidrome_api import NavidromeAPI
from api.navidrome_scan_trigger import NavidromeScanTrigger, ScanRunResult, ScanTimeoutError


class TestExecuteScan:
    """
    ARCH-009 Phase 5: execute_scan() ist ein reiner Pass-Through zu
    NavidromeScanTrigger.run_scan() - keine eigene Formatierung, kein
    eigenes Exception-Handling mehr.
    """

    def test_returns_run_scan_result_unchanged_on_success(self):
        expected = ScanRunResult(
            success=True, returncode=0, stdout="Scan complete", stderr=""
        )
        with patch.object(
            NavidromeScanTrigger, "run_scan", new=AsyncMock(return_value=expected)
        ):
            result = asyncio.run(NavidromeAPI.execute_scan())

        assert result is expected

    def test_returns_run_scan_result_unchanged_on_failure(self):
        expected = ScanRunResult(
            success=False, returncode=1, stdout="", stderr="boom"
        )
        with patch.object(
            NavidromeScanTrigger, "run_scan", new=AsyncMock(return_value=expected)
        ):
            result = asyncio.run(NavidromeAPI.execute_scan())

        assert result is expected

    def test_scan_timeout_error_propagates_unchanged(self):
        with patch.object(
            NavidromeScanTrigger,
            "run_scan",
            new=AsyncMock(side_effect=ScanTimeoutError(45)),
        ):
            with pytest.raises(ScanTimeoutError) as exc_info:
                asyncio.run(NavidromeAPI.execute_scan())

        assert exc_info.value.timeout_seconds == 45

    def test_missing_scan_command_attribute_error_propagates_unchanged(self):
        with patch.object(
            NavidromeScanTrigger,
            "run_scan",
            new=AsyncMock(
                side_effect=AttributeError(
                    "NAVIDROME_SCAN_COMMAND ist nicht in Config definiert oder leer."
                )
            ),
        ):
            with pytest.raises(AttributeError):
                asyncio.run(NavidromeAPI.execute_scan())
