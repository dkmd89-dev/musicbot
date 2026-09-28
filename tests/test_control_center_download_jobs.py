# tests/test_control_center_download_jobs.py
# -*- coding: utf-8 -*-
"""
POST /api/v1/jobs/download (+ GET/{job_id}/cancel) — Client Consolidation
Phase D/E, erster CC-eigener Download-Weg (docs/FINDINGS_INDEX.md
"Downloads nicht aus dem Control Center startbar").

Nur die externen Grenzen sind ersetzt (YoutubeDownloader, DuplicateDetector,
CookieHandler, DownloadHistoryStore werden im Router-Modul gepatcht - kein
echter yt-dlp-Aufruf, keine echte Duplikat-Cache-Datei); JobRegistry, Auth,
CSRF, URL-Validierung und die Sequenzierung/Ergebnis-Abbildung sind echt
(identisches Test-Prinzip wie tests/test_control_center_genre_revalidation_jobs.py).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time

import httpx
import pytest
import pytest_asyncio

from config import Config

_SAME_ORIGIN = {"Origin": "https://testserver"}
TEST_BOT_TOKEN = "123456:TEST-BOT-TOKEN-not-a-real-secret"


def _signed_telegram_payload(user_id: int, *, bot_token: str = TEST_BOT_TOKEN) -> dict:
    """Minimaler, lokal duplizierter Helfer (analog
    tests/test_control_center_auth.py::_signed_telegram_payload) - erzeugt
    einen echten, signierten Login-Payload für eine bestimmte Telegram-ID,
    für Tests, die zwei unterschiedliche, echte Sessions brauchen (dev-
    bypass liefert immer dieselbe OWNER-Identität)."""
    data = {"id": user_id, "first_name": "Test", "auth_date": int(time.time())}
    check_fields = {k: v for k, v in data.items() if v is not None}
    data_check_string = "\n".join(f"{k}={check_fields[k]}" for k in sorted(check_fields))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    data["hash"] = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return data


@pytest.fixture(autouse=True)
def _dev_bypass_as_owner(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 77))


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    c = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="https://testserver"
    )
    try:
        yield c
    finally:
        await c.aclose()


def _patch_dependencies(monkeypatch, *, downloader_factory, duplicate_detector=None):
    """Ersetzt nur die beiden Abhängigkeiten, die für diese Tests
    tatsächlich Fremdverhalten hätten (yt-dlp-Aufruf via YoutubeDownloader,
    Duplicate-Cache-Fachlogik via DuplicateDetector) - CookieHandler
    (reine Pfadauflösung) und DownloadHistoryStore (reale, per tmp_path
    isolierte Datei) bleiben echt, identisches Prinzip wie
    tests/test_download_handler_history_recording.py."""
    import control_center.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "YoutubeDownloader", downloader_factory)
    monkeypatch.setattr(
        jobs_router, "DuplicateDetector", lambda config: duplicate_detector or _FakeDetector()
    )


class _FakeDetector:
    """Reale register_download()/check_for_duplicates()-Signaturen, aber
    ohne Datei-I/O - reicht für die Sequenzierungs-/Ergebnis-Tests hier
    (die eigentliche Duplicate-Detection-Fachlogik wird bereits in
    tests/test_download_pipeline_core.py und den bestehenden
    DuplicateDetector-Tests geprüft, nicht hier erneut)."""

    def __init__(self):
        self.registered = []
        self._dup = (False, None, "none")

    def check_for_duplicates(self, *, url, raw_artist, raw_title):
        return self._dup

    def register_download(self, **kwargs):
        self.registered.append(kwargs)

    def get_statistics(self):
        return {}


class _FakeDownloader:
    """Fake für YoutubeDownloader - nimmt dieselben Konstruktor-Keywords
    entgegen, `download_audio()` liefert ein vorbereitetes Ergebnis statt
    echtem yt-dlp-Aufruf."""

    def __init__(self, result):
        self._result = result
        self.enhanced_download_processor = None

    @classmethod
    def factory(cls, result):
        def _make(**kwargs):
            return cls(result)

        return _make

    async def download_audio(self, url):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


async def _start(client, url="https://youtube.com/watch?v=abc", headers=_SAME_ORIGIN):
    return await client.post("/api/v1/jobs/download", headers=headers, json={"url": url})


async def _finished(client, job_id, *, path="/api/v1/jobs"):
    for _ in range(200):
        body = (await client.get(f"{path}/{job_id}")).json()
        if body["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("Job nicht beendet")


SINGLE_SUCCESS_RESULT = {
    "success": True,
    "title": "Ein Song",
    "artist": "Ein Artist",
    "original_url": "https://youtube.com/watch?v=abc",
    "library_path": "/lib/Ein Artist/Ein Song.m4a",
    "genres": ["Pop"],
}


@pytest.mark.asyncio
async def test_successful_single_download_succeeds_and_records_history(client, monkeypatch, tmp_path):
    detector = _FakeDetector()
    _patch_dependencies(
        monkeypatch,
        downloader_factory=_FakeDownloader.factory(dict(SINGLE_SUCCESS_RESULT)),
        duplicate_detector=detector,
    )
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", property(lambda self: tmp_path))

    r = await _start(client)
    assert r.status_code == 200
    job = await _finished(client, r.json()["job_id"], path="/api/v1/jobs/download")

    assert job["status"] == "SUCCEEDED"
    assert job["result"]["outcome"] == "success"
    assert detector.registered and detector.registered[0]["artist"] == "Ein Artist"

    from services.downloader.download_history import DownloadHistoryStore

    store = DownloadHistoryStore(cache_dir=str(tmp_path))
    entries = store.get_recent(77)  # OWNER_USER_ID via dev bypass
    assert len(entries) == 1 and entries[0].status == "success"


@pytest.mark.asyncio
async def test_download_job_exposes_step_events(client, monkeypatch, tmp_path):
    """D.12b: GET /api/v1/jobs/download/{id} liefert den Schritt-Verlauf
    (additives Feld `events`, älteste zuerst)."""
    _patch_dependencies(
        monkeypatch,
        downloader_factory=_FakeDownloader.factory(dict(SINGLE_SUCCESS_RESULT)),
        duplicate_detector=_FakeDetector(),
    )
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", property(lambda self: tmp_path))

    r = await _start(client)
    assert r.json()["events"] == []
    job = await _finished(client, r.json()["job_id"], path="/api/v1/jobs/download")

    messages = [e["message"] for e in job["events"]]
    assert messages[0] == "Gestartet"
    assert "Duplikat-Prüfung…" in messages
    assert "Metadaten werden verarbeitet…" in messages
    assert messages[-1] == "Abgeschlossen"
    assert all(set(e) == {"at", "message", "progress"} for e in job["events"])


class _StepReportingDownloader(_FakeDownloader):
    """Wie _FakeDownloader, meldet aber - wie EnhancedMetadataProcessor
    innerhalb von download_audio() - Schritte über report_step()."""

    async def download_audio(self, url):
        from services.jobs.step_context import report_step

        report_step("Cover laden…")
        report_step("Tags schreiben…")
        return await super().download_audio(url)


@pytest.mark.asyncio
async def test_single_download_job_contains_metadata_steps(client, monkeypatch, tmp_path):
    """D.12c: bei Single-Downloads landen die feinen Metadaten-Schritte
    (report_step()) mit Präfix "Metadaten: " im Job-Verlauf."""
    _patch_dependencies(
        monkeypatch,
        downloader_factory=_StepReportingDownloader.factory(dict(SINGLE_SUCCESS_RESULT)),
        duplicate_detector=_FakeDetector(),
    )
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", property(lambda self: tmp_path))

    r = await _start(client)
    job = await _finished(client, r.json()["job_id"], path="/api/v1/jobs/download")

    messages = [e["message"] for e in job["events"]]
    i_dl = messages.index("Download läuft…")
    assert messages[i_dl + 1 : i_dl + 3] == ["Metadaten: Cover laden…", "Metadaten: Tags schreiben…"]
    assert messages[-1] == "Abgeschlossen"


@pytest.mark.asyncio
async def test_playlist_download_job_has_no_metadata_steps(client, monkeypatch, tmp_path):
    """D.12c: bei Playlists bewusst KEINE feinen Schritte (würden die
    MAX_JOB_EVENTS-Grenze sprengen)."""
    _patch_dependencies(
        monkeypatch,
        downloader_factory=_StepReportingDownloader.factory({"success": False, "error": "x"}),
        duplicate_detector=_FakeDetector(),
    )
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", property(lambda self: tmp_path))

    r = await _start(client, url="https://youtube.com/playlist?list=PL123")
    job = await _finished(client, r.json()["job_id"], path="/api/v1/jobs/download")

    assert job["context"]["download_type"] == "playlist"
    assert not [e for e in job["events"] if e["message"].startswith("Metadaten:")]


@pytest.mark.asyncio
async def test_duplicate_found_succeeds_without_history_entry(client, monkeypatch, tmp_path):
    from pathlib import Path
    from services.downloader.models import DuplicateEntry
    from datetime import datetime

    detector = _FakeDetector()
    detector._dup = (
        True,
        DuplicateEntry(
            title="Alter Song", artist="Alter Artist",
            file_path=Path("/lib/x.m4a"), download_date=datetime.now(), url="https://youtube.com/watch?v=abc",
        ),
        "url",
    )
    _patch_dependencies(
        monkeypatch,
        downloader_factory=_FakeDownloader.factory({"success": True}),
        duplicate_detector=detector,
    )
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", property(lambda self: tmp_path))

    r = await _start(client)
    job = await _finished(client, r.json()["job_id"], path="/api/v1/jobs/download")

    assert job["status"] == "SUCCEEDED"
    assert job["result"]["outcome"] == "duplicate"
    assert "Alter Song" in job["result"]["message"]
    assert not detector.registered

    from services.downloader.download_history import DownloadHistoryStore

    store = DownloadHistoryStore(cache_dir=str(tmp_path))
    assert store.get_recent(77) == []


@pytest.mark.asyncio
async def test_failed_download_result_fails_the_job_and_records_history(client, monkeypatch, tmp_path):
    _patch_dependencies(
        monkeypatch,
        downloader_factory=_FakeDownloader.factory({"success": False, "error": "Video nicht verfügbar"}),
    )
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", property(lambda self: tmp_path))

    r = await _start(client)
    job = await _finished(client, r.json()["job_id"], path="/api/v1/jobs/download")

    assert job["status"] == "FAILED"
    assert job["error"] == "Video nicht verfügbar"

    from services.downloader.download_history import DownloadHistoryStore

    store = DownloadHistoryStore(cache_dir=str(tmp_path))
    assert store.get_recent(77)[0].status == "failed"


@pytest.mark.asyncio
async def test_cancelled_before_any_track_cancels_the_job_and_records_history(client, monkeypatch, tmp_path):
    _patch_dependencies(
        monkeypatch,
        downloader_factory=_FakeDownloader.factory({"success": False, "cancelled": True}),
    )
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", property(lambda self: tmp_path))

    r = await _start(client)
    job = await _finished(client, r.json()["job_id"], path="/api/v1/jobs/download")

    assert job["status"] == "CANCELLED"

    from services.downloader.download_history import DownloadHistoryStore

    store = DownloadHistoryStore(cache_dir=str(tmp_path))
    assert store.get_recent(77)[0].status == "cancelled"


@pytest.mark.asyncio
async def test_empty_download_result_fails_the_job(client, monkeypatch, tmp_path):
    _patch_dependencies(monkeypatch, downloader_factory=_FakeDownloader.factory(None))
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", property(lambda self: tmp_path))

    r = await _start(client)
    job = await _finished(client, r.json()["job_id"], path="/api/v1/jobs/download")

    assert job["status"] == "FAILED"


@pytest.mark.asyncio
async def test_unsupported_url_is_rejected_before_any_job_is_created(client, monkeypatch):
    async def fail_factory(**kwargs):
        raise AssertionError("Downloader darf nicht konstruiert werden")

    _patch_dependencies(monkeypatch, downloader_factory=fail_factory)

    r = await _start(client, url="https://example.com/video.mp4")
    assert r.status_code == 422
    assert (await client.get("/api/v1/jobs")).json()["jobs"] == []


@pytest.mark.asyncio
async def test_endpoint_requires_same_origin_and_authentication(client, monkeypatch):
    assert (await _start(client, headers={})).status_code == 403
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: False))
    assert (await _start(client)).status_code == 401


@pytest.mark.asyncio
async def test_plain_user_session_is_sufficient_no_admin_required(client, monkeypatch):
    """Parität zu Telegram (Nutzerentscheidung, Client Consolidation
    Phase D/E): AccessLevel.USER reicht - kein ADMIN wie beim Rest des
    jobs-Routers nötig."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: False))
    monkeypatch.setattr(Config, "BOT_TOKEN", property(lambda self: TEST_BOT_TOKEN))
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999)
    )

    async def fail_factory(**kwargs):
        raise AssertionError("nicht relevant fuer diesen Test")

    _patch_dependencies(monkeypatch, downloader_factory=fail_factory)

    # Absichtlich eine ungueltige URL - 422 statt 401/403 beweist, dass
    # die Anfrage die Auth-Schwelle passiert hat (identisches
    # Beweismuster wie test_control_center_auth.py).
    r = await _start(client, url="https://example.com/x")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_user_cannot_see_or_cancel_another_users_download_job(monkeypatch, tmp_path):
    from control_center.app import create_app

    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: False))
    monkeypatch.setattr(Config, "BOT_TOKEN", property(lambda self: TEST_BOT_TOKEN))
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", property(lambda self: tmp_path))
    _patch_dependencies(monkeypatch, downloader_factory=_FakeDownloader.factory(dict(SINGLE_SUCCESS_RESULT)))

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    client_a = httpx.AsyncClient(transport=transport, base_url="https://testserver")
    client_b = httpx.AsyncClient(transport=transport, base_url="https://testserver")
    try:
        await client_a.post(
            "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=111)
        )
        job_id = (await _start(client_a)).json()["job_id"]
        await _finished(client_a, job_id, path="/api/v1/jobs/download")

        await client_b.post(
            "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=222)
        )
        get_r = await client_b.get(f"/api/v1/jobs/download/{job_id}")
        cancel_r = await client_b.post(
            f"/api/v1/jobs/download/{job_id}/cancel", headers=_SAME_ORIGIN
        )
    finally:
        await client_a.aclose()
        await client_b.aclose()

    assert get_r.status_code == 404
    assert cancel_r.status_code == 404
