# -*- coding: utf-8 -*-
"""GET /api/v1/library/findings/{finding_id}/details — Belege zu einem Finding.

Testet den echten Produktionspfad: Router -> services/library_health/
finding_explain.py::explain_finding() -> file_analysis.compare_filename_to_title().
Nur das Tag-Lesen (mutagen, braucht echte Audiodateien) wird ersetzt.
"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.library_health.findings import FindingsRegistry, generate_finding_id
from services.library_health.models import AnalysisState
from services.library_health.tag_reader import TagData


def _issue(code, path, **kw):
    base = {"issue_code": code, "severity": "INFO", "scope": "file", "path": path, "artist": "Artist",
            "album": None, "title": "Titel beim Scan", "message": f"Meldung {code}", "confidence": None}
    base.update(kw)
    return base


@pytest.fixture
def env(tmp_path, monkeypatch):
    data, lib = tmp_path / "data", tmp_path / "library"
    data.mkdir()
    lib.mkdir()
    monkeypatch.setattr(Config, "DATA_DIR", data)
    monkeypatch.setattr(Config, "LIBRARY_DIR", lib)
    return {"data": data, "lib": lib, "registry": data / "library_health_findings.json"}


@pytest.fixture
def authenticated(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


def _register(env, *issues):
    reg = FindingsRegistry(env["registry"])
    reg.merge_scan_issues(list(issues), scanned_at="2026-09-27T00:00:00+00:00")
    reg.save()
    return [generate_finding_id(i) for i in issues]


def _file(env, rel):
    p = env["lib"] / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def _fake_tags(monkeypatch, title):
    import services.library_health.finding_explain as fe

    monkeypatch.setattr(fe, "read_tags", lambda p: TagData(state=AnalysisState.PRESENT, title=title))


REL = "01099/2019 - Skyr/01 - Intro feat. Mioso.m4a"


@pytest.mark.asyncio
async def test_details_returns_evidence_for_filename_title_mismatch(client, env, authenticated, monkeypatch):
    _file(env, REL)
    (fid,) = _register(env, _issue("FILENAME_TITLE_MISMATCH", REL))
    _fake_tags(monkeypatch, "Intro (Mioso)")

    r = await client.get(f"/api/v1/library/findings/{fid}/details")

    assert r.status_code == 200
    body = r.json()
    assert body["finding_id"] == fid and body["code"] == "FILENAME_TITLE_MISMATCH"
    assert body["supported"] is True and body["file_status"] == "ok"
    assert body["evidence_kind"] == "filename_title"
    ev = body["evidence"]
    assert ev["stem"] == "01 - Intro feat. Mioso" and ev["prefix"] == "01 - "
    assert ev["title"] == "Intro (Mioso)" and ev["title_at_scan"] == "Titel beim Scan"
    assert ev["normalized_remainder"] == "intro feat. mioso" and ev["normalized_title"] == "intro mioso"
    assert ev["matches"] is False
    assert {"op", "a", "b"} == set(ev["segments"][0])


@pytest.mark.asyncio
async def test_details_unsupported_code_is_200_not_an_error(client, env, authenticated):
    (fid,) = _register(env, _issue("META_ISRC_MISSING", "a/b.m4a"))
    body = (await client.get(f"/api/v1/library/findings/{fid}/details")).json()
    assert body["supported"] is False and body["file_status"] == "not_applicable"
    assert body["evidence"] is None and body["evidence_kind"] is None


@pytest.mark.asyncio
async def test_details_missing_file_is_reported_as_data(client, env, authenticated):
    (fid,) = _register(env, _issue("FILENAME_TITLE_MISMATCH", "Artist/gone.m4a"))
    r = await client.get(f"/api/v1/library/findings/{fid}/details")
    assert r.status_code == 200
    assert r.json()["file_status"] == "missing" and r.json()["evidence"] is None


@pytest.mark.asyncio
async def test_details_path_traversal_in_registry_path_is_blocked(client, env, authenticated, monkeypatch):
    (env["lib"].parent / "outside.m4a").write_bytes(b"x")
    (fid,) = _register(env, _issue("FILENAME_TITLE_MISMATCH", "../outside.m4a"))
    calls = []
    import services.library_health.finding_explain as fe

    monkeypatch.setattr(fe, "read_tags", lambda p: calls.append(p) or TagData(state=AnalysisState.PRESENT, title="x"))
    body = (await client.get(f"/api/v1/library/findings/{fid}/details")).json()
    assert body["file_status"] == "outside_library" and calls == []


@pytest.mark.asyncio
async def test_details_unknown_finding_is_404(client, env, authenticated):
    r = await client.get("/api/v1/library/findings/doesnotexist/details")
    assert r.status_code == 404
    assert "FINDING_NOT_FOUND" in r.text


@pytest.mark.asyncio
async def test_details_without_registry_file_is_404(client, env, authenticated):
    assert (await client.get("/api/v1/library/findings/abc/details")).status_code == 404


@pytest.mark.asyncio
async def test_details_requires_authentication(client, env):
    (fid,) = _register(env, _issue("FILENAME_TITLE_MISMATCH", REL))
    r = await client.get(f"/api/v1/library/findings/{fid}/details")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_details_is_strictly_read_only(client, env, authenticated, monkeypatch):
    p = _file(env, REL)
    (fid,) = _register(env, _issue("FILENAME_TITLE_MISMATCH", REL))
    _fake_tags(monkeypatch, "Anders")
    before = (env["registry"].read_bytes(), p.read_bytes(), p.stat().st_mtime_ns)

    assert (await client.get(f"/api/v1/library/findings/{fid}/details")).status_code == 200

    assert (env["registry"].read_bytes(), p.read_bytes(), p.stat().st_mtime_ns) == before
    assert sorted(x.name for x in env["data"].iterdir()) == ["library_health_findings.json"]


@pytest.mark.asyncio
async def test_details_route_does_not_shadow_summary_and_accepted(client, env, authenticated):
    assert (await client.get("/api/v1/library/findings/summary")).status_code == 200
    assert (await client.get("/api/v1/library/findings/accepted")).status_code == 200


@pytest.mark.asyncio
async def test_details_reports_stale_finding_when_file_was_fixed(client, env, authenticated, monkeypatch):
    _file(env, "Artist/Singles/2021 - Song.m4a")
    (fid,) = _register(env, _issue("FILENAME_TITLE_MISMATCH", "Artist/Singles/2021 - Song.m4a"))
    _fake_tags(monkeypatch, "Song")
    ev = (await client.get(f"/api/v1/library/findings/{fid}/details")).json()["evidence"]
    assert ev["matches"] is True


# ── Ende-zu-Ende mit echter Audiodatei (echtes read_tags, kein Fake) ────────

import shutil
import subprocess

requires_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg nicht auf PATH")


def _real_m4a(path, title):
    from mutagen.mp4 import MP4

    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", "-y", str(path)],
        capture_output=True, check=True, timeout=60,
    )
    audio = MP4(path)
    audio["\xa9nam"] = [title]
    audio.save()


@requires_ffmpeg
@pytest.mark.asyncio
async def test_details_end_to_end_with_real_m4a_and_real_tag_reader(client, env, authenticated):
    rel = "Artist/Singles/2021 - More Love feat. Okfella.m4a"
    _real_m4a(env["lib"] / rel, "More Love (Okfella)")
    (fid,) = _register(env, _issue("FILENAME_TITLE_MISMATCH", rel))

    body = (await client.get(f"/api/v1/library/findings/{fid}/details")).json()

    assert body["file_status"] == "ok"
    ev = body["evidence"]
    assert ev["stem"] == "2021 - More Love feat. Okfella"
    assert ev["title"] == "More Love (Okfella)"
    assert ev["normalized_remainder"] == "more love feat. okfella"
    assert ev["normalized_title"] == "more love okfella"
    assert ev["matches"] is False
    assert any(s["op"] != "equal" for s in ev["segments"])


@requires_ffmpeg
@pytest.mark.asyncio
async def test_details_end_to_end_reflects_a_fix_made_after_the_scan(client, env, authenticated):
    rel = "Artist/Singles/2021 - Song.m4a"
    _real_m4a(env["lib"] / rel, "Falsch")
    (fid,) = _register(env, _issue("FILENAME_TITLE_MISMATCH", rel))
    assert (await client.get(f"/api/v1/library/findings/{fid}/details")).json()["evidence"]["matches"] is False

    from mutagen.mp4 import MP4

    audio = MP4(env["lib"] / rel)
    audio["\xa9nam"] = ["Song"]
    audio.save()

    assert (await client.get(f"/api/v1/library/findings/{fid}/details")).json()["evidence"]["matches"] is True
