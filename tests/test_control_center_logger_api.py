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


# =====================================================================
# CC-LOGGER-L4 Stufe 1 — persistente Logger-Konfiguration
# =====================================================================
#
# Nutzt dieselben Fixtures wie die L2-Tests (isolated_logs, dev_auth).
# Zusätzlich patchen wir Config.DATA_DIR, damit die echte
# data/module_logger_config.json nicht berührt wird.

import json as _json
from pathlib import Path as _RealPath
from config import Config as _Config


@pytest.fixture
def isolated_data_dir(tmp_path: _RealPath, monkeypatch: pytest.MonkeyPatch) -> _RealPath:
    """Isoliertes DATA_DIR mit einer vorbefüllten module_logger_config.json,
    damit read/update nicht auf die echte Repo-Datei gehen."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "module_logger_config.json").write_text(
        _json.dumps(
            {
                "ModA": {
                    "enabled": True,
                    "level": "INFO",
                    "file_handler": True,
                    "console_handler": True,
                    "custom_format": None,
                },
                "ModB": {
                    "enabled": True,
                    "level": "DEBUG",
                    "file_handler": False,
                    "console_handler": True,
                    "custom_format": None,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_Config, "DATA_DIR", data_dir)
    return data_dir


def _read_repo_config(data_dir: _RealPath) -> dict:
    return _json.loads(
        (data_dir / "module_logger_config.json").read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------
# GET /config
# ---------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_config_returns_modules(
    isolated_logs: _RealPath, isolated_data_dir: _RealPath, dev_auth: None
) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/config")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert set(body["modules"].keys()) == {"ModA", "ModB"}
    assert body["modules"]["ModA"]["level"] == "INFO"
    assert body["modules"]["ModB"]["level"] == "DEBUG"


@pytest.mark.anyio
async def test_get_config_does_not_apply_runtime(
    isolated_logs: _RealPath, isolated_data_dir: _RealPath, dev_auth: None
) -> None:
    """GET liefert nur den persistenten Inhalt. Es werden keine Logger
    angefasst — der Vertrag ist 'Zustand der Datei'."""
    import logging

    logger_before = logging.getLogger("ModA").level
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/config")
    assert r.status_code == 200
    assert logging.getLogger("ModA").level == logger_before


# ---------------------------------------------------------------------
# PATCH /config
# ---------------------------------------------------------------------

@pytest.mark.anyio
async def test_patch_config_merges_and_persists(
    isolated_logs: _RealPath, isolated_data_dir: _RealPath, dev_auth: None
) -> None:
    async with await _client() as c:
        r = await c.patch(
            "/api/v1/admin/logger/config",
            json={"modules": {"ModA": {"level": "DEBUG"}}},
            headers={"Origin": "http://test"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["modules_updated"] == ["ModA"]
    assert "naechsten Bot-Start" in body["message"]
    assert "NICHT veraendert" in body["message"]

    after = _read_repo_config(isolated_data_dir)
    assert after["ModA"]["level"] == "DEBUG"
    assert after["ModA"]["file_handler"] is True  # unverändert
    assert after["ModB"]["level"] == "DEBUG"      # unverändert


@pytest.mark.anyio
async def test_patch_config_rejects_unknown_module(
    isolated_logs: _RealPath, isolated_data_dir: _RealPath, dev_auth: None
) -> None:
    async with await _client() as c:
        r = await c.patch(
            "/api/v1/admin/logger/config",
            json={"modules": {"Nope": {"level": "DEBUG"}}},
            headers={"Origin": "http://test"},
        )
    assert r.status_code == 422
    assert _error_code(r) == "LOGGER_CONFIG_UNKNOWN_MODULE"


@pytest.mark.anyio
async def test_patch_config_rejects_invalid_level(
    isolated_logs: _RealPath, isolated_data_dir: _RealPath, dev_auth: None
) -> None:
    async with await _client() as c:
        r = await c.patch(
            "/api/v1/admin/logger/config",
            json={"modules": {"ModA": {"level": "NOT_A_LEVEL"}}},
            headers={"Origin": "http://test"},
        )
    assert r.status_code == 422
    assert _error_code(r) == "LOGGER_CONFIG_INVALID_LEVEL"


@pytest.mark.anyio
async def test_patch_config_rejects_unknown_field(
    isolated_logs: _RealPath, isolated_data_dir: _RealPath, dev_auth: None
) -> None:
    async with await _client() as c:
        r = await c.patch(
            "/api/v1/admin/logger/config",
            json={"modules": {"ModA": {"nope": True}}},
            headers={"Origin": "http://test"},
        )
    assert r.status_code == 422
    assert _error_code(r) == "LOGGER_CONFIG_UNKNOWN_FIELD"


@pytest.mark.anyio
async def test_patch_config_rejects_extra_top_level_key(
    isolated_logs: _RealPath, isolated_data_dir: _RealPath, dev_auth: None
) -> None:
    """Top-Level-Feld strikt: nur `modules` erlaubt (Pydantic extra=forbid)."""
    async with await _client() as c:
        r = await c.patch(
            "/api/v1/admin/logger/config",
            json={"modules": {"ModA": {"level": "DEBUG"}}, "extra": 1},
            headers={"Origin": "http://test"},
        )
    assert r.status_code == 422


@pytest.mark.anyio
async def test_patch_config_requires_csrf_origin(
    isolated_logs: _RealPath, isolated_data_dir: _RealPath, dev_auth: None
) -> None:
    """Ohne Origin-Header kein CSRF-Schutz → 403."""
    async with await _client() as c:
        r = await c.patch(
            "/api/v1/admin/logger/config",
            json={"modules": {"ModA": {"level": "DEBUG"}}},
        )
    assert r.status_code == 403


@pytest.mark.anyio
async def test_patch_config_missing_file_returns_409(
    isolated_logs: _RealPath, tmp_path: _RealPath, dev_auth: None
) -> None:
    """Fehlende Config-Datei → 409 LOGGER_CONFIG_MISSING statt irreführendem 422."""
    from config import Config as _Cfg

    empty_data_dir = tmp_path / "empty_data"
    empty_data_dir.mkdir()
    import pytest as _pytest
    mp = _pytest.MonkeyPatch()
    mp.setattr(_Cfg, "DATA_DIR", empty_data_dir)
    try:
        async with await _client() as c:
            r = await c.patch(
                "/api/v1/admin/logger/config",
                json={"modules": {"ModA": {"level": "DEBUG"}}},
                headers={"Origin": "http://test"},
            )
        assert r.status_code == 409
        assert _error_code(r) == "LOGGER_CONFIG_MISSING"
    finally:
        mp.undo()


@pytest.mark.anyio
async def test_patch_config_file_unchanged_on_invalid_request(
    isolated_logs: _RealPath, isolated_data_dir: _RealPath, dev_auth: None
) -> None:
    """Kernvertrag: bei invaliden PATCH-Anfragen bleibt die Datei unverändert."""
    import hashlib

    path = isolated_data_dir / "module_logger_config.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    async with await _client() as c:
        r = await c.patch(
            "/api/v1/admin/logger/config",
            json={"modules": {"ModA": {"level": "BAD"}}},
            headers={"Origin": "http://test"},
        )
    assert r.status_code == 422

    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert before == after


@pytest.mark.anyio
async def test_patch_config_does_not_apply_runtime(
    isolated_logs: _RealPath, isolated_data_dir: _RealPath, dev_auth: None
) -> None:
    """Kernvertrag: PATCH schreibt nur die Datei. Der reale Logger-Zustand
    im laufenden Prozess darf sich NICHT ändern."""
    import logging

    logger = logging.getLogger("ModA")
    level_before = logger.level
    async with await _client() as c:
        r = await c.patch(
            "/api/v1/admin/logger/config",
            json={"modules": {"ModA": {"level": "CRITICAL"}}},
            headers={"Origin": "http://test"},
        )
    assert r.status_code == 200
    assert logger.level == level_before  # unverändert


# =====================================================================
# Hilfsfunktion: Fehler-Code robust aus Response extrahieren
# =====================================================================
#
# Das Control Center nutzt einen globalen Exception-Handler
# (`control_center/app.py`, `schemas/errors.py::ErrorDetail`), der
# HTTPException-Details in ein `{"error": {"code": ..., "message": ...}}`
# umwandelt. Daneben gibt es FastAPI-Defaults (`{"detail": ...}`), die
# z.B. bei Pydantic-Validation-Fehlern auftreten. Diese Funktion kennt
# beide Formen, damit die Tests nicht vom konkreten Wrapper abhängen.


def _error_code(response) -> str:
    """Zieht den Fehler-Code robust aus dem Response-Body."""
    body = response.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        return detail.get("code", "")
    error = body.get("error")
    if isinstance(error, dict):
        return error.get("code", "")
    # Pydantic-Validation-Fehler liefern `detail` als Liste — kein Code.
    return ""


def _error_message(response) -> str:
    """Zieht die Fehler-Message robust aus dem Response-Body (leer, wenn
    das Format nicht erkannt wird)."""
    body = response.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        return detail.get("message", "")
    if isinstance(detail, str):
        return detail
    error = body.get("error")
    if isinstance(error, dict):
        return error.get("message", "")
    return ""


# =====================================================================
# CC-LOGGER-L5.1 — Runtime-Status
# =====================================================================

import json as _json_l5
from config import Config as _ConfigL5


@pytest.fixture
def isolated_runtime_snapshot(tmp_path: _RealPath, monkeypatch: pytest.MonkeyPatch) -> _RealPath:
    """Isoliertes DATA_DIR für Runtime-Snapshot-Tests. Startet mit
    NICHT existierendem Snapshot (status="missing")."""
    data_dir = tmp_path / "data_l5"
    data_dir.mkdir()
    monkeypatch.setattr(_ConfigL5, "DATA_DIR", data_dir)
    return data_dir


@pytest.mark.anyio
async def test_runtime_status_missing(
    isolated_logs: _RealPath, isolated_runtime_snapshot: _RealPath, dev_auth: None
) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/runtime-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "missing"
    assert body["state_semantics"] == "state_after_last_successful_bot_start"
    assert body["snapshot"] is None


@pytest.mark.anyio
async def test_runtime_status_available(
    isolated_logs: _RealPath, isolated_runtime_snapshot: _RealPath, dev_auth: None
) -> None:
    payload = {
        "schema_version": 1,
        "startup_id": "abc123",
        "runtime_applied_at": "2026-09-23T12:00:00+00:00",
        "root_level": "INFO",
        "effective_levels": {"CoverProcessor": "DEBUG"},
        "handlers": {"CoverProcessor": ["FileHandler"]},
        "disabled": [],
    }
    (isolated_runtime_snapshot / "logger_runtime_snapshot.json").write_text(
        _json_l5.dumps(payload), encoding="utf-8"
    )
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/runtime-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "available"
    assert body["snapshot"]["startup_id"] == "abc123"
    assert body["snapshot"]["effective_levels"]["CoverProcessor"] == "DEBUG"


@pytest.mark.anyio
async def test_runtime_status_corrupt(
    isolated_logs: _RealPath, isolated_runtime_snapshot: _RealPath, dev_auth: None
) -> None:
    (isolated_runtime_snapshot / "logger_runtime_snapshot.json").write_text(
        "{ not valid", encoding="utf-8"
    )
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/runtime-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "corrupt"
    assert body["snapshot"] is None
    assert "message" in body


@pytest.mark.anyio
async def test_runtime_status_incomplete_snapshot_is_corrupt(
    isolated_logs: _RealPath, isolated_runtime_snapshot: _RealPath, dev_auth: None
) -> None:
    (isolated_runtime_snapshot / "logger_runtime_snapshot.json").write_text(
        _json_l5.dumps({"root_level": "INFO"}), encoding="utf-8"
    )
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/runtime-status")
    assert r.status_code == 200
    assert r.json()["status"] == "corrupt"


@pytest.mark.anyio
async def test_runtime_status_is_not_live_state(
    isolated_logs: _RealPath, isolated_runtime_snapshot: _RealPath, dev_auth: None
) -> None:
    """Kernvertrag: die Response-Aussage ist 'state_after_last_successful_bot_start',
    nicht 'live_state'. Wir pinnen das explizit."""
    async with await _client() as c:
        r = await c.get("/api/v1/admin/logger/runtime-status")
    body = r.json()
    assert body["state_semantics"] == "state_after_last_successful_bot_start"
    # Kein Feld, das auf Live hindeutet
    assert "live" not in body
    assert "current" not in body


# =====================================================================
# CC-LOGGER-L5.3 — Apply / Restart
# =====================================================================
#
# WICHTIG: der echte BotRestartTrigger wird pro Test gemockt — Tests
# duerfen niemals einen echten `sudo systemctl restart bot` ausloesen.
# Wir setzen _PRE_RESTART_DELAY_SECONDS auf 0.0 und verifizieren den
# Trigger-Aufruf ueber einen Zaehler.

import json as _json_apply
from pathlib import Path as _RealPathApply
from config import Config as _ConfigApply


@pytest.fixture
def isolated_apply_env(
    tmp_path: _RealPathApply, monkeypatch: pytest.MonkeyPatch
) -> dict:
    """Isoliertes DATA_DIR mit vollstaendiger Config. `is_repair_running`
    ist standardmaessig False; jeder Test kann das ueberschreiben."""
    data_dir = tmp_path / "data_apply"
    data_dir.mkdir()
    (data_dir / "module_logger_config.json").write_text(
        _json_apply.dumps(
            {
                "ModA": {
                    "enabled": True,
                    "level": "INFO",
                    "file_handler": True,
                    "console_handler": True,
                    "custom_format": None,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_ConfigApply, "DATA_DIR", data_dir)

    # is_repair_running auf False (Default) — Tests koennen das patchen.
    from services.library_repair import run_tracking
    monkeypatch.setattr(run_tracking, "is_repair_running", lambda: False)

    # Restart-Trigger mocken — KEINE echten systemctl-Aufrufe.
    from utils import bot_restart_trigger
    calls: list[str] = []

    def _fake_trigger(service_name: str) -> None:
        calls.append(service_name)

    monkeypatch.setattr(
        bot_restart_trigger.BotRestartTrigger, "trigger_restart",
        staticmethod(_fake_trigger),
    )

    # Delay auf 0.0, damit der Timer im Test schnell feuert.
    from control_center.routers import logger as cc_logger_router
    monkeypatch.setattr(cc_logger_router, "_PRE_RESTART_DELAY_SECONDS", 0.0)

    return {"data_dir": data_dir, "calls": calls}


async def _post_apply(client):
    return await client.post(
        "/api/v1/admin/logger/apply",
        headers={"Origin": "http://test"},
    )


# ---------------------------------------------------------------------
# Happy Path (unverified)
# ---------------------------------------------------------------------

@pytest.mark.anyio
async def test_apply_unverified_succeeds_with_preflight_payload(
    isolated_logs: _RealPathApply, isolated_apply_env: dict, dev_auth: None
) -> None:
    async with await _client() as c:
        r = await _post_apply(c)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "applied"
    assert body["preflight"]["status"] == "unverified"
    assert "downloads" in body["preflight"]["unverified"]
    assert "backups" in body["preflight"]["unverified"]
    assert body["preflight"]["checked"]["repair_lock"] is True


@pytest.mark.anyio
async def test_apply_schedules_restart_trigger(
    isolated_logs: _RealPathApply, isolated_apply_env: dict, dev_auth: None
) -> None:
    """Bei erfolgreichem Apply muss der Restart-Trigger geplant werden.
    Delay=0.0 (Fixture), also feuert call_later sofort nach dem Response."""
    import asyncio

    async with await _client() as c:
        r = await _post_apply(c)
        assert r.status_code == 200
        # Event-Loop kurz drehen lassen, damit call_later feuert.
        await asyncio.sleep(0.05)

    assert isolated_apply_env["calls"] == ["bot"]


# ---------------------------------------------------------------------
# blocked
# ---------------------------------------------------------------------

@pytest.mark.anyio
async def test_apply_blocked_when_repair_running(
    isolated_logs: _RealPathApply, isolated_apply_env: dict, dev_auth: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.library_repair import run_tracking
    monkeypatch.setattr(run_tracking, "is_repair_running", lambda: True)

    async with await _client() as c:
        r = await _post_apply(c)
    assert r.status_code == 409
    body = r.json()
    # Nachrichtenformat wird vom ErrorDetail-Wrapper transportiert.
    detail = body.get("detail") or body.get("error") or {}
    if isinstance(detail, dict):
        assert detail.get("code") == "LOGGER_APPLY_BLOCKED" or "blocked" in str(detail).lower()
    assert isolated_apply_env["calls"] == []  # kein Restart


@pytest.mark.anyio
async def test_apply_blocked_does_not_mutate_config(
    isolated_logs: _RealPathApply, isolated_apply_env: dict, dev_auth: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    from services.library_repair import run_tracking
    monkeypatch.setattr(run_tracking, "is_repair_running", lambda: True)

    cfg_path = isolated_apply_env["data_dir"] / "module_logger_config.json"
    before = hashlib.sha256(cfg_path.read_bytes()).hexdigest()

    async with await _client() as c:
        r = await _post_apply(c)
    assert r.status_code == 409
    after = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
    assert before == after


# ---------------------------------------------------------------------
# Config fehlt
# ---------------------------------------------------------------------

@pytest.mark.anyio
async def test_apply_missing_config_returns_409(
    isolated_logs: _RealPathApply, tmp_path: _RealPathApply, dev_auth: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = tmp_path / "empty_data_apply"
    empty.mkdir()
    monkeypatch.setattr(_ConfigApply, "DATA_DIR", empty)

    from services.library_repair import run_tracking
    monkeypatch.setattr(run_tracking, "is_repair_running", lambda: False)

    from utils import bot_restart_trigger
    calls: list[str] = []
    monkeypatch.setattr(
        bot_restart_trigger.BotRestartTrigger, "trigger_restart",
        staticmethod(lambda svc: calls.append(svc)),
    )

    async with await _client() as c:
        r = await _post_apply(c)
    assert r.status_code == 409
    assert calls == []


# ---------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------

@pytest.mark.anyio
async def test_apply_requires_csrf_origin(
    isolated_logs: _RealPathApply, isolated_apply_env: dict, dev_auth: None
) -> None:
    async with await _client() as c:
        r = await c.post("/api/v1/admin/logger/apply")
    assert r.status_code == 403
    assert isolated_apply_env["calls"] == []


# ---------------------------------------------------------------------
# Rate-Limit
# ---------------------------------------------------------------------

@pytest.mark.anyio
async def test_apply_rate_limit_second_call_429(
    isolated_logs: _RealPathApply, isolated_apply_env: dict, dev_auth: None
) -> None:
    async with await _client() as c:
        r1 = await _post_apply(c)
        r2 = await _post_apply(c)
    assert r1.status_code == 200
    assert r2.status_code == 429
    body = r2.json()
    detail = body.get("detail") or body.get("error") or {}
    if isinstance(detail, dict):
        assert detail.get("code") == "LOGGER_APPLY_RATE_LIMITED"
    assert r2.headers.get("retry-after") is not None
