# tests/test_control_center_findings_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/findings (+ /summary) sowie POST .../accept und
.../unaccept — Findings-Anzeige (read-only) + erster schreibender
Control-Center-Endpunkt (Nachtrag 2026-09-17, siehe
docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router ruft services/library_health/findings.py::FindingsRegistry/
group_open_findings_by_category()/get_review_summary()/accept_finding()/
unaccept_finding() unveraendert auf. Die Registry-Fixtures werden
ausschliesslich ueber die echte FindingsRegistry-API aufgebaut
(merge_scan_issues()/review_finding()/save()) statt die JSON-Datei
direkt zu schreiben — identisches Prinzip wie
tests/test_library_health_findings.py.

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


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    """Dieses Testfile prüft den Findings-Endpoint selbst, nicht die seit
    Schritt 3 davorliegende Authentifizierung (dafür: tests/test_control_center_auth.py)
    — Dev-Auth-Bypass steht dafür genau bereit (control_center/dependencies.py)."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


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


# ─────────────────────────────────────────────────────────────────────────
# POST .../accept + POST .../unaccept — erster schreibender Endpunkt
# ─────────────────────────────────────────────────────────────────────────

_SAME_ORIGIN = {"Origin": "http://testserver"}


async def _seed_open_finding(registry_path, *, path="a.m4a", code="ARTWORK_MISSING"):
    from services.library_health.findings import FindingsRegistry, generate_finding_id

    registry = FindingsRegistry(registry_path)
    issue = _issue(code, path=path)
    registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00+00:00")
    registry.save()
    return generate_finding_id(issue)


@pytest.mark.asyncio
async def test_accept_finding_marks_as_accepted_and_removes_from_open_list(
    client, registry_path, monkeypatch
):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 42))
    finding_id = await _seed_open_finding(registry_path)

    response = await client.post(
        f"/api/v1/library/findings/{finding_id}/accept",
        json={"reason": "Bewusst so gewollt"},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["finding_id"] == finding_id
    assert body["status"] == "FALSE_POSITIVE"
    assert body["reviewed_by"] == "42"  # Dev-Bypass -> config.OWNER_USER_ID, als str im Audit-Trail
    assert body["review_note"] == "Bewusst so gewollt"

    open_findings = (await client.get("/api/v1/library/findings")).json()
    assert open_findings == []


@pytest.mark.asyncio
async def test_accept_finding_requires_non_empty_reason(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    finding_id = await _seed_open_finding(registry_path)

    response = await client.post(
        f"/api/v1/library/findings/{finding_id}/accept",
        json={"reason": "   "},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REASON_REQUIRED"


@pytest.mark.asyncio
async def test_accept_finding_404_for_unknown_id(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)

    response = await client.post(
        "/api/v1/library/findings/does-not-exist/accept",
        json={"reason": "egal"},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FINDING_NOT_FOUND"


@pytest.mark.asyncio
async def test_accept_finding_rejected_without_origin_header(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    finding_id = await _seed_open_finding(registry_path)

    response = await client.post(
        f"/api/v1/library/findings/{finding_id}/accept", json={"reason": "x"}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"


@pytest.mark.asyncio
async def test_accept_finding_rejected_with_mismatched_origin_header(
    client, registry_path, monkeypatch
):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    finding_id = await _seed_open_finding(registry_path)

    response = await client.post(
        f"/api/v1/library/findings/{finding_id}/accept",
        json={"reason": "x"},
        headers={"Origin": "http://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"


@pytest.mark.asyncio
async def test_review_finding_resolved_marks_as_resolved(client, registry_path, monkeypatch):
    """Generischer Review-Endpunkt (Nachtrag api_health.md Abschnitt 7) —
    additiv neben accept/unaccept, deckt hier den manuellen RESOLVED-Review
    ab, den accept_finding() (fest FALSE_POSITIVE) nicht kann."""
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 42))
    finding_id = await _seed_open_finding(registry_path)

    response = await client.post(
        f"/api/v1/library/findings/{finding_id}/review",
        json={"status": "RESOLVED", "note": "Manuell behoben"},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["finding_id"] == finding_id
    assert body["status"] == "RESOLVED"
    assert body["reviewed_by"] == "42"
    assert body["review_note"] == "Manuell behoben"

    open_findings = (await client.get("/api/v1/library/findings")).json()
    assert open_findings == []


@pytest.mark.asyncio
async def test_review_finding_false_positive_behaves_like_accept(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    finding_id = await _seed_open_finding(registry_path)

    response = await client.post(
        f"/api/v1/library/findings/{finding_id}/review",
        json={"status": "FALSE_POSITIVE", "note": "Bewusst so gewollt"},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "FALSE_POSITIVE"


@pytest.mark.asyncio
async def test_review_finding_false_positive_requires_non_empty_note(
    client, registry_path, monkeypatch
):
    """Identische Pflicht-Grund-Regel wie accept_finding() (Auftrag §15) —
    dieser generische Endpunkt darf dieselbe Zielaktion nicht laxer machen."""
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    finding_id = await _seed_open_finding(registry_path)

    response = await client.post(
        f"/api/v1/library/findings/{finding_id}/review",
        json={"status": "FALSE_POSITIVE", "note": "   "},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REASON_REQUIRED"


@pytest.mark.asyncio
async def test_review_finding_rejects_invalid_status(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    finding_id = await _seed_open_finding(registry_path)

    response = await client.post(
        f"/api/v1/library/findings/{finding_id}/review",
        json={"status": "OPEN"},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REVIEW_STATUS"


@pytest.mark.asyncio
async def test_review_finding_404_for_unknown_id(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)

    response = await client.post(
        "/api/v1/library/findings/does-not-exist/review",
        json={"status": "RESOLVED"},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FINDING_NOT_FOUND"


@pytest.mark.asyncio
async def test_review_finding_rejected_without_origin_header(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    finding_id = await _seed_open_finding(registry_path)

    response = await client.post(
        f"/api/v1/library/findings/{finding_id}/review", json={"status": "RESOLVED"}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"


@pytest.mark.asyncio
async def test_unaccept_finding_reopens_and_reappears_in_open_list(
    client, registry_path, monkeypatch
):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    finding_id = await _seed_open_finding(registry_path)
    await client.post(
        f"/api/v1/library/findings/{finding_id}/accept",
        json={"reason": "x"},
        headers=_SAME_ORIGIN,
    )

    response = await client.post(
        f"/api/v1/library/findings/{finding_id}/unaccept",
        json={"note": "Doch nicht akzeptiert"},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "OPEN"

    open_findings = (await client.get("/api/v1/library/findings")).json()
    assert len(open_findings) == 1


@pytest.mark.asyncio
async def test_unaccept_finding_409_when_already_open(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    finding_id = await _seed_open_finding(registry_path)

    response = await client.post(
        f"/api/v1/library/findings/{finding_id}/unaccept",
        json={},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ALREADY_OPEN"


@pytest.mark.asyncio
async def test_unaccept_finding_404_for_unknown_id(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)

    response = await client.post(
        "/api/v1/library/findings/does-not-exist/unaccept",
        json={},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FINDING_NOT_FOUND"


# ─────────────────────────────────────────────────────────────────────────
# GET .../findings/accepted — Nachtrag zu Accept/Unaccept
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_accepted_findings_empty_when_none_accepted(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    await _seed_open_finding(registry_path)

    response = await client.get("/api/v1/library/findings/accepted")

    assert response.status_code == 200
    assert response.json() == {"findings": [], "total": 0}


@pytest.mark.asyncio
async def test_get_accepted_findings_shows_accepted_with_review_metadata(
    client, registry_path, monkeypatch
):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 42))
    finding_id = await _seed_open_finding(registry_path)
    await client.post(
        f"/api/v1/library/findings/{finding_id}/accept",
        json={"reason": "Bewusst so gewollt"},
        headers=_SAME_ORIGIN,
    )

    response = await client.get("/api/v1/library/findings/accepted")

    assert response.status_code == 200
    body = response.json()
    assert len(body["findings"]) == 1
    accepted = body["findings"][0]
    assert accepted["finding_id"] == finding_id
    assert accepted["review_note"] == "Bewusst so gewollt"
    assert accepted["reviewed_by"] == "42"
    assert accepted["present_in_latest_scan"] is True


@pytest.mark.asyncio
async def test_get_accepted_findings_excludes_still_open_findings(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    await _seed_open_finding(registry_path)  # bleibt offen, wird nicht akzeptiert

    body = (await client.get("/api/v1/library/findings/accepted")).json()

    assert body["findings"] == []


@pytest.mark.asyncio
async def test_unaccept_finding_removes_from_accepted_list(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    finding_id = await _seed_open_finding(registry_path)
    await client.post(
        f"/api/v1/library/findings/{finding_id}/accept",
        json={"reason": "x"},
        headers=_SAME_ORIGIN,
    )

    await client.post(
        f"/api/v1/library/findings/{finding_id}/unaccept",
        json={},
        headers=_SAME_ORIGIN,
    )

    body = (await client.get("/api/v1/library/findings/accepted")).json()
    assert body["findings"] == []


@pytest.mark.asyncio
async def test_get_accepted_findings_respects_limit_and_reports_total(
    client, registry_path, monkeypatch
):
    """Nachtrag: Smoke-Test gegen die echte Produktions-Registry zeigte
    1173 akzeptierte Findings — ungekuerzt gerendert waere das dieselbe
    Falle wie beim Repair-Plan (1114 Kandidaten)."""
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)
    from services.library_health.findings import FindingsRegistry, generate_finding_id

    registry = FindingsRegistry(registry_path)
    issues = [_issue("ARTWORK_MISSING", path=f"f{i}.m4a") for i in range(5)]
    registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00+00:00")
    for issue in issues:
        registry.review_finding(generate_finding_id(issue), "FALSE_POSITIVE", note="x")
    registry.save()

    response = await client.get(
        "/api/v1/library/findings/accepted", params={"limit": 2}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["findings"]) == 2
    assert body["total"] == 5


@pytest.mark.asyncio
async def test_get_accepted_findings_rejects_invalid_limit(client, registry_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", registry_path.parent)

    response = await client.get(
        "/api/v1/library/findings/accepted", params={"limit": 0}
    )

    assert response.status_code == 422
