# tests/test_control_center_findings_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/findings (+ /summary) — Vertical Slice "Health/
Dashboard", Step 2 (read-only Findings-Anzeige, Scope laut Freigabe
2026-09-15: "nur Findings anzeigen", keine Accept/Unaccept-Endpoints).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router ruft services/library_health/findings.py::FindingsRegistry/
group_open_findings_by_category()/get_review_summary() unveraendert auf.
Die Registry-Fixtures werden ausschliesslich ueber die echte
FindingsRegistry-API aufgebaut (merge_scan_issues()/review_finding()/
save()) statt die JSON-Datei direkt zu schreiben — identisches Prinzip
wie tests/test_library_health_findings.py.

Kein ffmpeg noetig (anders als test_control_center_health_api.py) - diese
Route liest nur die Findings-Registry-JSON-Datei, kein Scan.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.library_health.findings import FindingsRegistry


def _issue(code, severity="WARNING", scope="file", **kwargs):
    base = {
        "issue_code": code,
        "severity": severity,
        "scope": scope,
        "path": None,
        "artist": None,
        "album": None,
        "title": None,
        "message": f"Testmeldung fuer {code}",
        "confidence": None,
    }
    base.update(kwargs)
    return base


@pytest.fixture
def registry_path(tmp_path):
    return tmp_path / "data" / "library_health_findings.json"


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_get_findings_empty_when_no_registry_file(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)

    response = await client.get("/api/v1/library/findings")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_findings_summary_empty_when_no_registry_file(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)

    response = await client.get("/api/v1/library/findings/summary")

    assert response.status_code == 200
    assert response.json() == {
        "open": 0, "repaired": 0, "accepted": 0,
        "accepted_stale": 0, "resolved_by_scan": 0, "total": 0,
    }


@pytest.mark.asyncio
async def test_get_findings_groups_open_findings_by_category(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)

    registry = FindingsRegistry(registry_path)
    issues = [
        _issue("ARTWORK_MISSING", "WARNING", scope="file", path="a.m4a"),
        _issue("ARTWORK_MISSING", "WARNING", scope="file", path="b.m4a"),
        _issue("AUDIO_NO_STREAM", "CRITICAL", scope="file", path="c.m4a"),
    ]
    registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00+00:00")
    registry.save()

    response = await client.get("/api/v1/library/findings")

    assert response.status_code == 200
    body = response.json()
    assert [g["code"] for g in body] == ["AUDIO_NO_STREAM", "ARTWORK_MISSING"]  # CRITICAL vor WARNING
    critical_group = body[0]
    assert critical_group["tier"] == "CRITICAL"
    assert critical_group["open_count"] == 1
    warning_group = body[1]
    assert warning_group["open_count"] == 2
    assert {f["path"] for f in warning_group["findings"]} == {"a.m4a", "b.m4a"}


@pytest.mark.asyncio
async def test_get_findings_excludes_accepted_and_resolved(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)

    registry = FindingsRegistry(registry_path)
    issues = [
        _issue("ARTWORK_MISSING", path="open.m4a"),
        _issue("ARTWORK_MISSING", path="accepted.m4a"),
        _issue("ARTWORK_MISSING", path="resolved.m4a"),
    ]
    registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00+00:00")
    from services.library_health.findings import generate_finding_id

    accepted_id = generate_finding_id(_issue("ARTWORK_MISSING", path="accepted.m4a"))
    resolved_id = generate_finding_id(_issue("ARTWORK_MISSING", path="resolved.m4a"))
    registry.review_finding(accepted_id, "FALSE_POSITIVE", note="bewusst akzeptiert")
    registry.review_finding(resolved_id, "RESOLVED")
    registry.save()

    body = (await client.get("/api/v1/library/findings")).json()

    assert len(body) == 1
    paths = {f["path"] for f in body[0]["findings"]}
    assert paths == {"open.m4a"}


@pytest.mark.asyncio
async def test_get_findings_summary_counts_tri_state(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)

    registry = FindingsRegistry(registry_path)
    issues = [
        _issue("ARTWORK_MISSING", path="open.m4a"),
        _issue("ARTWORK_MISSING", path="accepted.m4a"),
        _issue("ARTWORK_MISSING", path="resolved.m4a"),
    ]
    registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00+00:00")
    from services.library_health.findings import generate_finding_id

    registry.review_finding(
        generate_finding_id(_issue("ARTWORK_MISSING", path="accepted.m4a")),
        "FALSE_POSITIVE", note="ok",
    )
    registry.review_finding(
        generate_finding_id(_issue("ARTWORK_MISSING", path="resolved.m4a")),
        "RESOLVED",
    )
    registry.save()

    body = (await client.get("/api/v1/library/findings/summary")).json()

    assert body == {
        "open": 1, "repaired": 1, "accepted": 1,
        "accepted_stale": 0, "resolved_by_scan": 0, "total": 3,
    }


@pytest.mark.asyncio
async def test_get_findings_response_omits_review_metadata(client, registry_path, monkeypatch):
    """Master-Prompt Regel 9/Abschnitt 12: Review-Historie (reviewed_by,
    history, resolved_at, ...) ist nicht Teil dieser noch unauthentifizierten
    Anzeige-Response."""
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)

    registry = FindingsRegistry(registry_path)
    registry.merge_scan_issues(
        [_issue("ARTWORK_MISSING", path="a.m4a")], scanned_at="2026-01-01T00:00:00+00:00"
    )
    registry.save()

    body = (await client.get("/api/v1/library/findings")).json()

    finding = body[0]["findings"][0]
    assert set(finding.keys()) == {
        "finding_id", "code", "scope", "status", "artist", "album", "title",
        "path", "message", "severity", "confidence", "occurrences",
        "first_seen", "last_seen",
    }
    assert "reviewed_by" not in finding
    assert "history" not in finding


@pytest.mark.asyncio
async def test_get_findings_500_on_corrupt_registry(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text("{not valid json", encoding="utf-8")

    response = await client.get("/api/v1/library/findings")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "FINDINGS_REGISTRY_INVALID"
