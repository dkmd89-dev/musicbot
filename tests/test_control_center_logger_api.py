# -*- coding: utf-8 -*-
"""
CC-LOGGER-L2 — HTTP-Tests für /api/v1/admin/logger/*.

Nutzt den Dev-Auth-Bypass (wie tests/test_control_center_auth.py) und
monkeypatcht Config.LOG_DIR auf ein isoliertes tmp-Verzeichnis, damit
die echten Produktions-Logs nicht berührt werden.

Regression: GET /api/v1/logs muss unverändert funktionieren.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import httpx
from httpx import ASGITransport

from control_center.app import create_app


@pytest.fixture
def isolated_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isoliertes Log-Verzeichnis + Config.LOG_DIR-Patch. Schreibt
    zwei Testdateien mit bekannten Inhalten."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "bot.log").write_text(
        "10:00:00 ℹ️ [COMP] line-1\n10:00:01 ⚠️ [COMP] line-2\n10:00:02 ❌ [COMP] line-3\n",
        encoding="utf-8",
    )
    (log_dir / "modul.log").write_text(
        "10:00:00 ℹ️ [MOD] hello\n",
        encoding="utf-8",
    )

    from config import Config
    monkeypatch.setattr(Config, "LOG_DIR", log_dir)
    # Config.LOG_FILE wird von reader.read_logs nur als Default-Source
    # genutzt; hier explizit mitsetzen, damit default_source "bot.log"
    # auch tatsächlich greift.
    monkeypatch.setattr(Config, "LOG_FILE", log_dir / "bot.log")
    return log_dir


@pytest.fixture
def anyio_backend() -> str:
    """Beschraenkt pytest-anyio auf das asyncio-Backend. Die aktuelle
    trio-Version wirft beim Parametrisieren einen
    `AttributeError: module 'trio' has no attribute 'MultiError'` —
    bekannte Inkompatibilitaet zwischen pytest-anyio und neueren
    trio-Versionen. Das Projekt nutzt ohnehin ausschliesslich asyncio
    (bot.py, control_center/), trio wird nirgends produktiv verwendet."""
    return "asyncio"


@pytest.fixture
def dev_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import Config
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", True)
    monkeypatch.setattr(Config, "OWNER_USER_ID", 1)


async def _client() -> httpx.AsyncClient:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# =====================================================================
# Happy Path
# =====================================================================

@pytest.mark.anyio
async def test_list_files_returns_all_log_files(isolated_logs: Path, dev_auth: None) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/files")
    assert r.status_code == 200
    body = r.json()
    names = {f["name"] for f in body["files"]}
    assert names == {"bot.log", "modul.log"}
    assert body["total"] == 2
    for f in body["files"]:
        assert "size_human" in f
        assert "modified_at" in f


@pytest.mark.anyio
async def test_stats_aggregates_files(isolated_logs: Path, dev_auth: None) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/files/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total_files"] == 2
    assert body["total_size_bytes"] > 0
    assert body["largest_file"] in {"bot.log", "modul.log"}
    assert body["total_size_human"]


@pytest.mark.anyio
async def test_file_detail_returns_metadata_and_entries(isolated_logs: Path, dev_auth: None) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/files/bot.log")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "bot.log"
    assert body["source"] == "bot.log"
    assert body["total_matched"] == 3
    assert len(body["entries"]) == 3
    assert body["size_bytes"] > 0
    assert body["size_human"]
    assert body["modified_at"]


@pytest.mark.anyio
async def test_file_detail_respects_limit(isolated_logs: Path, dev_auth: None) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/files/bot.log?limit=1")
    assert r.status_code == 200
    body = r.json()
    assert body["total_matched"] == 3
    assert len(body["entries"]) == 1


@pytest.mark.anyio
async def test_file_detail_respects_level_filter(isolated_logs: Path, dev_auth: None) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/files/bot.log?level=ERROR")
    assert r.status_code == 200
    body = r.json()
    assert body["total_matched"] == 1
    assert body["entries"][0]["level"] == "ERROR"


# =====================================================================
# Route-Reihenfolge: /files/stats darf NICHT als Dateiname interpretiert werden
# =====================================================================

@pytest.mark.anyio
async def test_stats_route_not_shadowed_by_name_route(isolated_logs: Path, dev_auth: None) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/files/stats")
    assert r.status_code == 200
    body = r.json()
    # Wäre die Route durch /files/{name} überschattet worden, hätte
    # das App-Layer LogFileNotFoundError("stats") geworfen → 404.
    assert "total_files" in body
    assert "name" not in body


# =====================================================================
# Security: Path Traversal
# =====================================================================

@pytest.mark.anyio
@pytest.mark.parametrize(
    "attack",
    [
        "../etc/passwd",
        "../../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",
    ],
)
async def test_traversal_is_rejected(isolated_logs: Path, dev_auth: None, attack: str) -> None:
    """Traversal-Versuche, die tatsaechlich bis zum Router durchkommen
    (httpx sendet sie unveraendert, FastAPI dekodiert URL-Encoding),
    muessen vom App-Layer abgelehnt werden — Whitelist +
    Containment-Check in services/logger_admin.py.

    * 404 — Whitelist-Check schlaegt fehl (Normalfall).
    * 422 — Path-Parameter-Validierung (falls FastAPI den dekodierten
      Wert als ungueltig einstuft).
    """
    async with await _client() as c:
        r = await c.get(f"/api/v1/admin/logger/files/{attack}")
    assert r.status_code in (404, 422), (
        f"attack={attack!r}: erwartet 404/422, bekommen {r.status_code}"
    )
    # Der Body darf unter keinen Umstaenden Inhalt ausserhalb der
    # Log-Whitelist durchreichen.
    assert b"root:" not in r.content


@pytest.mark.anyio
@pytest.mark.parametrize("normalized", [".", "..", ""])
async def test_normalized_paths_never_serve_foreign_content(
    isolated_logs: Path, dev_auth: None, normalized: str
) -> None:
    """Werte wie "."/".."/"" werden von der HTTP-Client-Bibliothek
    (httpx, RFC 3986 Path-Normalisierung) bereits **vor** dem Absenden
    entfernt — der Router sieht dann `/files` (Listen-Route) und
    liefert die Dateiliste, nicht das Detail einer Datei ausserhalb
    der Whitelist. Das ist ein Layer *ueber* unserem Sicherheits-Check
    und kein Problem: der Router wird gar nicht mit einem
    Traversal-Wert aufgerufen.

    Der Test verankert, dass ein 200-Response in diesem Fall
    ausschliesslich die **Dateiliste** ist (`files`/`total_files`),
    niemals ein Datei-Detail (`source`/`entries`).
    """
    async with await _client() as c:
        r = await c.get(
            f"/api/v1/admin/logger/files/{normalized}",
            follow_redirects=False,
        )
    # Akzeptabel: 200 (Dateiliste), 307 (Redirect auf /files),
    # 404/422 (falls Starlette/httpx diesmal nicht normalisiert).
    assert r.status_code in (200, 307, 404, 422), (
        f"normalized={normalized!r}: unerwartet {r.status_code}"
    )
    if r.status_code == 200:
        body = r.json()
        # 200 darf ausschliesslich die Dateiliste sein — nicht der
        # Inhalt einer bestimmten Datei.
        # LogFileListResponse-Schema: {files: [...], total: int}
        assert "files" in body and "total" in body
        assert "entries" not in body
        assert "source" not in body
    # Body darf nie Inhalt einer Datei ausserhalb der Log-Whitelist sein.
    assert b"root:" not in r.content


@pytest.mark.anyio
async def test_unknown_file_is_404(isolated_logs: Path, dev_auth: None) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/files/does-not-exist.log")
    assert r.status_code == 404


# =====================================================================
# Regression: GET /api/v1/logs funktioniert weiter
# =====================================================================

@pytest.mark.anyio
async def test_legacy_logs_endpoint_still_works(isolated_logs: Path, dev_auth: None) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/logs")
    assert r.status_code == 200
    body = r.json()
    assert "source" in body
    assert "entries" in body
    assert body["source"] == "bot.log"


# =====================================================================
# Authorization (siehe tests/test_control_center_auth.py für die
# vollständige 401/403-Matrix; hier nur Stichprobe)
# =====================================================================

@pytest.mark.anyio
async def test_unauthenticated_is_rejected(isolated_logs: Path) -> None:
    # Kein dev_auth-Fixture → 401 (bzw. 403, je nach Config-Default)
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/files")
    assert r.status_code in (401, 403)


# =====================================================================
# Limit-Grenzen (HTTP): Werte außerhalb [1, 2000] müssen 422 liefern,
# kein stilles Clamping.
# =====================================================================

@pytest.mark.anyio
@pytest.mark.parametrize("bad_limit", [0, -1, 2001, 5000, 99999])
async def test_limit_out_of_range_is_422(
    isolated_logs: Path, dev_auth: None, bad_limit: int
) -> None:
    async with await _client() as c:
        r = await c.get(f"/api/v1/admin/logger/files/bot.log?limit={bad_limit}")
    assert r.status_code == 422, (
        f"limit={bad_limit} sollte 422 liefern (Validierungsfehler), "
        f"nicht {r.status_code}"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("good_limit", [1, 100, 2000])
async def test_limit_in_range_is_200(
    isolated_logs: Path, dev_auth: None, good_limit: int
) -> None:
    async with await _client() as c:
        r = await c.get(f"/api/v1/admin/logger/files/bot.log?limit={good_limit}")
    assert r.status_code == 200
    assert r.json()["limit"] == good_limit


@pytest.mark.anyio
async def test_limit_2001_is_not_silently_accepted(
    isolated_logs: Path, dev_auth: None
) -> None:
    """Nutzeranforderung explizit verankern: kein stilles Akzeptieren
    oder Clamping von limit > 2000."""
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/files/bot.log?limit=2001")
    assert r.status_code == 422
    # Zusätzlich: der Fehler ist maschinenlesbar (FastAPI-Standard).
    body = r.json()
    assert "detail" in body
