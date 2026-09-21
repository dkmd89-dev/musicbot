# tests/test_control_center_admin_maintenance_api.py
# -*- coding: utf-8 -*-
"""
GET/POST /api/v1/admin/maintenance/{action}/preview|execute — Master-
Prompt Abschnitt 22 "ADMINISTRATION" (Maintenance).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router ruft services/library_repair/maintenance_service.py::preview_*()/
execute_*() unverändert auf — identischer Aufrufpfad wie die bestehende
Telegram-"🧹 Library-Wartung"-Fähigkeit (ARCH-032). Gegen echte,
isolierte m4a-Testdateien (nie die Produktionsbibliothek), identisches
Muster wie tests/test_library_repair_maintenance_service.py und
tests/test_control_center_metadata_actions_api.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from mutagen.mp4 import MP4, MP4FreeForm

import services.library_repair.run_tracking as rt
from config import Config

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")

_SAME_ORIGIN = {"Origin": "http://testserver"}


def _m4a(path: Path, *, genre=None, artist=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error"],
        check=True,
    )
    a = MP4(path)
    a["\xa9nam"] = ["T"]
    if genre:
        a["\xa9gen"] = [genre]
    if artist:
        a["\xa9ART"] = artist if isinstance(artist, list) else [artist]
    a.save()


def _set_legacy_genre(path: Path, value: str) -> None:
    a = MP4(path)
    a["----:com.apple.iTunes:GENRE"] = [MP4FreeForm(value.encode("utf-8"))]
    a.save()


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Isoliert Lock/Journal/Run-History - niemals die echten
    Produktionsdateien beruehren."""
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")


@pytest.fixture
def lib(tmp_path, monkeypatch):
    d = tmp_path / "library"
    monkeypatch.setattr(Config, "LIBRARY_DIR", d)
    return d


@pytest.fixture
def mapping_dir(tmp_path, monkeypatch):
    d = tmp_path / "mapping"
    d.mkdir()
    monkeypatch.setattr(Config, "GENRE_MAPPING_DIR", d)
    return d


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


# ─────────────────────────────────────────────────────────────────────────
# artist-casing
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_casing_preview_and_execute(client, lib, mapping_dir):
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p, artist="bausa")
    (mapping_dir / "artist_overrides.json").write_text(
        json.dumps({"bausa": "Bausa"}), encoding="utf-8",
    )

    preview = await client.get(
        "/api/v1/admin/maintenance/artist-casing/preview", params={"artist": "Bausa"},
    )
    assert preview.status_code == 200
    assert preview.json()["changed_count"] == 1
    assert MP4(p).tags["\xa9ART"] == ["bausa"]  # Preview veraendert nichts

    response = await client.post(
        "/api/v1/admin/maintenance/artist-casing/execute",
        params={"artist": "Bausa"}, headers=_SAME_ORIGIN,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert MP4(p).tags["\xa9ART"] == ["Bausa"]
    assert rt.is_repair_running() is False


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_casing_execute_rejected_without_origin_header(client, lib, mapping_dir):
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p, artist="bausa")
    (mapping_dir / "artist_overrides.json").write_text(
        json.dumps({"bausa": "Bausa"}), encoding="utf-8",
    )

    response = await client.post(
        "/api/v1/admin/maintenance/artist-casing/execute", params={"artist": "Bausa"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"
    assert MP4(p).tags["\xa9ART"] == ["bausa"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_casing_execute_rejects_path_traversal_artist_value(client, lib, mapping_dir):
    """Security-Regression (CC-AC-6, P1-Fund aus CC-AC-3 Runde 3): vor
    diesem Fix traf `artist="."` ueber artist_targets() die GESAMTE
    Library (bestaetigter destruktiver Live-Schreibzugriff, siehe
    docs/FINDINGS_INDEX.md) - `POST .../legacy-genre-cleanup/execute?
    artist=.` entfernte das Legacy-Genre-Atom bei ALLEN Artists einer
    Testbibliothek. Dieselbe Schwaeche galt fuer artist-casing/
    artist-rename/title-edit, da alle vier artist_targets() teilen."""
    own = lib / "A" / "Singles" / "a.m4a"
    _m4a(own, artist="a")
    other = lib / "Other" / "Singles" / "b.m4a"
    _m4a(other, artist="other")
    (mapping_dir / "artist_overrides.json").write_text(
        json.dumps({"a": "A", "other": "Other"}), encoding="utf-8",
    )

    for traversal_artist in (".", "..", "", "/etc", "a/../../b"):
        response = await client.post(
            "/api/v1/admin/maintenance/artist-casing/execute",
            params={"artist": traversal_artist}, headers=_SAME_ORIGIN,
        )
        assert response.status_code == 200, traversal_artist
        assert response.json()["success_count"] == 0, traversal_artist

    assert MP4(own).tags["\xa9ART"] == ["a"]
    assert MP4(other).tags["\xa9ART"] == ["other"]


# ─────────────────────────────────────────────────────────────────────────
# legacy-genre-cleanup
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_legacy_genre_cleanup_preview_and_execute(client, lib):
    p = lib / "Filow" / "Singles" / "a.m4a"
    _m4a(p, genre="Pop")
    _set_legacy_genre(p, "Pop")

    preview = await client.get(
        "/api/v1/admin/maintenance/legacy-genre-cleanup/preview", params={"artist": "Filow"},
    )
    assert preview.status_code == 200
    assert preview.json()["changed_count"] == 1

    response = await client.post(
        "/api/v1/admin/maintenance/legacy-genre-cleanup/execute",
        params={"artist": "Filow"}, headers=_SAME_ORIGIN,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert MP4(p).tags.get("----:com.apple.iTunes:GENRE") is None


@requires_ffmpeg
@pytest.mark.asyncio
async def test_legacy_genre_cleanup_execute_rejects_path_traversal_artist_value(client, lib):
    """Security-Regression (CC-AC-6) — siehe
    test_artist_casing_execute_rejects_path_traversal_artist_value().
    Dies ist der konkret reproduzierte Vektor aus
    docs/FINDINGS_INDEX.md: `artist="."` entfernte vor diesem Fix das
    Legacy-Genre-Atom bei ALLEN Artists statt nur beim gewaehlten."""
    own = lib / "Filow" / "Singles" / "a.m4a"
    _m4a(own, genre="Pop")
    _set_legacy_genre(own, "Pop")
    other = lib / "Other" / "Singles" / "b.m4a"
    _m4a(other, genre="Rock")
    _set_legacy_genre(other, "Rock")

    for traversal_artist in (".", "..", "", "/etc", "a/../../b"):
        response = await client.post(
            "/api/v1/admin/maintenance/legacy-genre-cleanup/execute",
            params={"artist": traversal_artist}, headers=_SAME_ORIGIN,
        )
        assert response.status_code == 200, traversal_artist
        assert response.json()["success_count"] == 0, traversal_artist

    assert MP4(own).tags.get("----:com.apple.iTunes:GENRE") is not None
    assert MP4(other).tags.get("----:com.apple.iTunes:GENRE") is not None


# ─────────────────────────────────────────────────────────────────────────
# artist-rename (manueller Zielwert)
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_rename_preview_and_execute(client, lib):
    p = lib / "Macloud" / "Singles" / "a.m4a"
    _m4a(p, artist="Macloud")

    preview = await client.get(
        "/api/v1/admin/maintenance/artist-rename/preview",
        params={"artist": "Macloud", "new_artist": "Miksu & Macloud"},
    )
    assert preview.status_code == 200
    assert preview.json()["changed_count"] == 1
    assert MP4(p).tags["\xa9ART"] == ["Macloud"]

    response = await client.post(
        "/api/v1/admin/maintenance/artist-rename/execute",
        json={"artist": "Macloud", "new_artist": "Miksu & Macloud"},
        headers=_SAME_ORIGIN,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert MP4(p).tags["\xa9ART"] == ["Miksu & Macloud"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_rename_rejects_empty_new_value(client, lib):
    p = lib / "Macloud" / "Singles" / "a.m4a"
    _m4a(p, artist="Macloud")

    response = await client.post(
        "/api/v1/admin/maintenance/artist-rename/execute",
        json={"artist": "Macloud", "new_artist": "   "},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MAINTENANCE_VALIDATION_ERROR"
    assert MP4(p).tags["\xa9ART"] == ["Macloud"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_rename_execute_409_when_lock_already_held(client, lib):
    p = lib / "Macloud" / "Singles" / "a.m4a"
    _m4a(p, artist="Macloud")
    rt.acquire_repair_lock()
    try:
        response = await client.post(
            "/api/v1/admin/maintenance/artist-rename/execute",
            json={"artist": "Macloud", "new_artist": "Miksu & Macloud"},
            headers=_SAME_ORIGIN,
        )
    finally:
        rt.release_repair_lock()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REPAIR_ALREADY_RUNNING"


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_rename_execute_rejects_path_traversal_artist_value(client, lib):
    """Security-Regression (CC-AC-6) — siehe
    test_artist_casing_execute_rejects_path_traversal_artist_value()."""
    own = lib / "Macloud" / "Singles" / "a.m4a"
    _m4a(own, artist="Macloud")
    other = lib / "Other" / "Singles" / "b.m4a"
    _m4a(other, artist="Other")

    for traversal_artist in (".", "..", "", "/etc", "a/../../b"):
        response = await client.post(
            "/api/v1/admin/maintenance/artist-rename/execute",
            json={"artist": traversal_artist, "new_artist": "Pwned"},
            headers=_SAME_ORIGIN,
        )
        assert response.status_code == 200, traversal_artist
        assert response.json()["success_count"] == 0, traversal_artist

    assert MP4(own).tags["\xa9ART"] == ["Macloud"]
    assert MP4(other).tags["\xa9ART"] == ["Other"]


# ─────────────────────────────────────────────────────────────────────────
# title-edit (manueller Zielwert, genau ein Track)
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_title_edit_preview_and_execute(client, lib):
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p)

    preview = await client.get(
        "/api/v1/admin/maintenance/title-edit/preview",
        params={"artist": "Bausa", "rel_path": "Bausa/Singles/a.m4a", "new_title": "Neuer Titel"},
    )
    assert preview.status_code == 200
    assert preview.json()["changed_count"] == 1
    assert MP4(p).tags["\xa9nam"] == ["T"]

    response = await client.post(
        "/api/v1/admin/maintenance/title-edit/execute",
        json={"artist": "Bausa", "rel_path": "Bausa/Singles/a.m4a", "new_title": "Neuer Titel"},
        headers=_SAME_ORIGIN,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert MP4(p).tags["\xa9nam"] == ["Neuer Titel"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_title_edit_no_automatic_title_cleanup(client, lib):
    """Master-Prompt/ARCH-Vorgabe: kein automatischer TitleCleaner auf
    den manuellen Zielwert."""
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p)

    response = await client.post(
        "/api/v1/admin/maintenance/title-edit/execute",
        json={"artist": "Bausa", "rel_path": "Bausa/Singles/a.m4a", "new_title": '"Titel" prod. XY'},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 200
    assert MP4(p).tags["\xa9nam"] == ['"Titel" prod. XY']


@requires_ffmpeg
@pytest.mark.asyncio
async def test_title_edit_execute_rejected_without_origin_header(client, lib):
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p)

    response = await client.post(
        "/api/v1/admin/maintenance/title-edit/execute",
        json={"artist": "Bausa", "rel_path": "Bausa/Singles/a.m4a", "new_title": "Neuer Titel"},
    )

    assert response.status_code == 403
    assert MP4(p).tags["\xa9nam"] == ["T"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_title_edit_execute_rejects_path_traversal_artist_value(client, lib):
    """Security-Regression (CC-AC-6) — siehe
    test_artist_casing_execute_rejects_path_traversal_artist_value()."""
    own = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(own)
    other = lib / "Other" / "Singles" / "b.m4a"
    _m4a(other)

    for traversal_artist in (".", "..", "", "/etc", "a/../../b"):
        response = await client.post(
            "/api/v1/admin/maintenance/title-edit/execute",
            json={
                "artist": traversal_artist,
                "rel_path": "Bausa/Singles/a.m4a",
                "new_title": "Pwned",
            },
            headers=_SAME_ORIGIN,
        )
        assert response.status_code == 200, traversal_artist
        assert response.json()["success_count"] == 0, traversal_artist

    assert MP4(own).tags["\xa9nam"] == ["T"]
    assert MP4(other).tags["\xa9nam"] == ["T"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_title_edit_execute_rejects_rel_path_from_foreign_artist(client, lib):
    """Security-Regression (CC-AC-6, P1-Fund aus CC-AC-3 Runde 3,
    docs/FINDINGS_INDEX.md, konkret reproduziert): `artist="A"` +
    `rel_path="AndererArtist/Album/01.m4a"` schrieb vor diesem Fix
    erfolgreich bei einem fremden Artist - `rel_path` hatte KEINE
    Bindung an den gewaehlten `artist`."""
    own = lib / "A" / "Singles" / "a.m4a"
    _m4a(own)
    foreign = lib / "AndererArtist" / "Album" / "01.m4a"
    _m4a(foreign)

    response = await client.post(
        "/api/v1/admin/maintenance/title-edit/execute",
        json={
            "artist": "A",
            "rel_path": "AndererArtist/Album/01.m4a",
            "new_title": "Pwned",
        },
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 200
    assert response.json()["success_count"] == 0
    assert MP4(foreign).tags["\xa9nam"] == ["T"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_title_edit_execute_rejects_rel_path_outside_library(client, lib, tmp_path):
    """Security-Regression (CC-AC-6) — `rel_path` darf die Library-Wurzel
    nicht verlassen, auch nicht relativ ueber `..`."""
    own = lib / "A" / "Singles" / "a.m4a"
    _m4a(own)
    outside = tmp_path / "outside" / "evil.m4a"
    outside.parent.mkdir(parents=True)
    _m4a(outside)

    for traversal_rel_path in ("../outside/evil.m4a", str(outside)):
        response = await client.post(
            "/api/v1/admin/maintenance/title-edit/execute",
            json={"artist": "A", "rel_path": traversal_rel_path, "new_title": "Pwned"},
            headers=_SAME_ORIGIN,
        )
        assert response.status_code == 200, traversal_rel_path
        assert response.json()["success_count"] == 0, traversal_rel_path

    assert MP4(outside).tags["\xa9nam"] == ["T"]


# ─────────────────────────────────────────────────────────────────────────
# album-edit (manueller Zielwert, ©alb) — Manual Metadata Editing v2,
# CC-AC-3 (library_artist_centric_UX.txt §13/§15)
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_album_edit_preview_and_execute(client, lib):
    p = lib / "Bausa" / "2020 - Old Album" / "01 - a.m4a"
    _m4a(p)
    a = MP4(p)
    a["\xa9alb"] = ["Old Album"]
    a.save()

    preview = await client.get(
        "/api/v1/admin/maintenance/album-edit/preview",
        params={"artist": "Bausa", "album": "2020 - Old Album", "new_album": "New Album"},
    )
    assert preview.status_code == 200
    assert preview.json()["changed_count"] == 1
    assert MP4(p).tags["\xa9alb"] == ["Old Album"]  # Preview veraendert nichts

    response = await client.post(
        "/api/v1/admin/maintenance/album-edit/execute",
        json={"artist": "Bausa", "album": "2020 - Old Album", "new_album": "New Album"},
        headers=_SAME_ORIGIN,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert MP4(p).tags["\xa9alb"] == ["New Album"]
    # Artist-/Titel-Tag bleiben unangetastet (Auftrag §15)
    assert MP4(p).tags["\xa9nam"] == ["T"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_album_edit_works_for_single_track_scope(client, lib):
    """Regression Auftrag §16: Singles-Scope (`"<Singles-Ordner>/<Datei>"`,
    identisch zu list_artist_albums()) muss ebenfalls ein gueltiger
    Album-Kontext sein — nicht nur Mehr-Track-Alben."""
    p = lib / "1986zig" / "Singles" / "a.m4a"
    _m4a(p)
    a = MP4(p)
    a["\xa9alb"] = ["Old Single Album"]
    a.save()

    response = await client.post(
        "/api/v1/admin/maintenance/album-edit/execute",
        json={"artist": "1986zig", "album": "Singles/a.m4a", "new_album": "New Single Album"},
        headers=_SAME_ORIGIN,
    )
    assert response.status_code == 200
    assert response.json()["success_count"] == 1
    assert MP4(p).tags["\xa9alb"] == ["New Single Album"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_album_edit_execute_rejected_without_origin_header(client, lib):
    p = lib / "Bausa" / "2020 - Old Album" / "01 - a.m4a"
    _m4a(p)

    response = await client.post(
        "/api/v1/admin/maintenance/album-edit/execute",
        json={"artist": "Bausa", "album": "2020 - Old Album", "new_album": "New Album"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"
    assert MP4(p).tags.get("\xa9alb") is None


@requires_ffmpeg
@pytest.mark.asyncio
async def test_album_edit_execute_409_when_lock_already_held(client, lib):
    p = lib / "Bausa" / "2020 - Old Album" / "01 - a.m4a"
    _m4a(p)
    rt.acquire_repair_lock()
    try:
        response = await client.post(
            "/api/v1/admin/maintenance/album-edit/execute",
            json={"artist": "Bausa", "album": "2020 - Old Album", "new_album": "New Album"},
            headers=_SAME_ORIGIN,
        )
    finally:
        rt.release_repair_lock()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REPAIR_ALREADY_RUNNING"


@requires_ffmpeg
@pytest.mark.asyncio
async def test_album_edit_rejects_path_traversal_album_value(client, lib):
    """Security-Regression (Adversarial-Review-Fund 2026-09-21, Runde 2):
    `album` ist seit CC-AC-3 erstmals per HTTP frei waehlbar (nicht mehr
    ausschliesslich ueber die Telegram-seitige server-validierte
    resolve_album_by_index()) — kein Wert darf den Artist-Scope
    verlassen. Runde-1-Fix (Blacklist auf ".." /absolut) wurde in Runde 2
    per "." umgangen (`root/artist/"."` kollabiert zu `root/artist` =
    voller Own-Discography-Scope statt nur des gewaehlten Albums) — die
    Dot-Varianten unten decken genau das ab, nicht nur die Runde-1-Fälle."""
    own_a = lib / "A" / "2020 - Own Album" / "01 - a.m4a"
    _m4a(own_a)
    own_b = lib / "A" / "2021 - Other Own Album" / "01 - c.m4a"
    _m4a(own_b)
    other = lib / "B" / "2021 - Other Album" / "01 - b.m4a"
    _m4a(other)

    for traversal_album in (
        "..", "../B/2021 - Other Album", "/etc",
        ".", "./", ".//.", "Singles/../..",
    ):
        response = await client.post(
            "/api/v1/admin/maintenance/album-edit/execute",
            json={"artist": "A", "album": traversal_album, "new_album": "Pwned"},
            headers=_SAME_ORIGIN,
        )
        assert response.status_code == 200, traversal_album
        assert response.json()["success_count"] == 0, traversal_album

    assert MP4(own_a).tags.get("\xa9alb") is None
    assert MP4(own_b).tags.get("\xa9alb") is None
    assert MP4(other).tags.get("\xa9alb") is None


@requires_ffmpeg
@pytest.mark.asyncio
async def test_album_edit_rejects_path_traversal_artist_value(client, lib):
    """Security-Regression (Adversarial-Review-Fund 2026-09-21, Runde 2):
    `artist` ist auf diesen beiden neuen Endpunkten ebenfalls erstmals
    per HTTP frei waehlbar — `artist="."`/`""`/`".."` mit einem
    passenden `album`-Wert darf nicht die gesamte Library treffen (die
    vier bereits bestehenden, von diesem PR nicht beruehrten Endpunkte
    artist-casing/legacy-genre-cleanup/artist-rename/title-edit teilen
    dieselbe Schwaeche in artist_targets() - das bleibt ein separater,
    bewusst zurueckgestellter Befund, siehe docs/FINDINGS_INDEX.md)."""
    own = lib / "A" / "2020 - Own Album" / "01 - a.m4a"
    _m4a(own)
    other = lib / "B" / "2021 - Other Album" / "01 - b.m4a"
    _m4a(other)

    for traversal_artist in (".", "", ".."):
        response = await client.post(
            "/api/v1/admin/maintenance/album-edit/execute",
            json={"artist": traversal_artist, "album": "2021 - Other Album", "new_album": "Pwned"},
            headers=_SAME_ORIGIN,
        )
        assert response.status_code == 200, traversal_artist
        assert response.json()["success_count"] == 0, traversal_artist

    assert MP4(own).tags.get("\xa9alb") is None
    assert MP4(other).tags.get("\xa9alb") is None


@requires_ffmpeg
@pytest.mark.asyncio
async def test_album_edit_preview_rejects_path_traversal_album_value(client, lib):
    other = lib / "B" / "2021 - Other Album" / "01 - b.m4a"
    _m4a(other)

    for traversal_album in ("../B/2021 - Other Album", "."):
        preview = await client.get(
            "/api/v1/admin/maintenance/album-edit/preview",
            params={"artist": "A", "album": traversal_album, "new_album": "Pwned"},
        )
        assert preview.status_code == 200, traversal_album
        assert preview.json()["target_count"] == 0, traversal_album


# ─────────────────────────────────────────────────────────────────────────
# albumartist-edit (manueller Zielwert, aART) — Manual Metadata Editing
# v2, CC-AC-3 (library_artist_centric_UX.txt §13/§15)
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_albumartist_edit_preview_and_execute(client, lib):
    p = lib / "Bausa" / "2020 - Album X" / "01 - a.m4a"
    _m4a(p, artist="Bausa")

    preview = await client.get(
        "/api/v1/admin/maintenance/albumartist-edit/preview",
        params={"artist": "Bausa", "album": "2020 - Album X", "new_album_artist": "Various Artists"},
    )
    assert preview.status_code == 200
    assert preview.json()["changed_count"] == 1
    assert MP4(p).tags.get("aART") is None  # Preview veraendert nichts

    response = await client.post(
        "/api/v1/admin/maintenance/albumartist-edit/execute",
        json={"artist": "Bausa", "album": "2020 - Album X", "new_album_artist": "Various Artists"},
        headers=_SAME_ORIGIN,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert MP4(p).tags["aART"] == ["Various Artists"]
    # Artist-Tag (©ART) bleibt unangetastet (Auftrag §15)
    assert MP4(p).tags["\xa9ART"] == ["Bausa"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_albumartist_edit_execute_rejected_without_origin_header(client, lib):
    p = lib / "Bausa" / "2020 - Album X" / "01 - a.m4a"
    _m4a(p, artist="Bausa")

    response = await client.post(
        "/api/v1/admin/maintenance/albumartist-edit/execute",
        json={"artist": "Bausa", "album": "2020 - Album X", "new_album_artist": "Various Artists"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"
    assert MP4(p).tags.get("aART") is None


@requires_ffmpeg
@pytest.mark.asyncio
async def test_albumartist_edit_execute_409_when_lock_already_held(client, lib):
    p = lib / "Bausa" / "2020 - Album X" / "01 - a.m4a"
    _m4a(p, artist="Bausa")
    rt.acquire_repair_lock()
    try:
        response = await client.post(
            "/api/v1/admin/maintenance/albumartist-edit/execute",
            json={"artist": "Bausa", "album": "2020 - Album X", "new_album_artist": "Various Artists"},
            headers=_SAME_ORIGIN,
        )
    finally:
        rt.release_repair_lock()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REPAIR_ALREADY_RUNNING"


@requires_ffmpeg
@pytest.mark.asyncio
async def test_albumartist_edit_rejects_path_traversal_album_value(client, lib):
    """Security-Regression (Adversarial-Review-Fund 2026-09-21, Runde 2)
    — siehe test_album_edit_rejects_path_traversal_album_value()."""
    own = lib / "A" / "2020 - Own Album" / "01 - a.m4a"
    _m4a(own, artist="A")
    other = lib / "B" / "2021 - Other Album" / "01 - b.m4a"
    _m4a(other, artist="B")

    for traversal_album in ("../B/2021 - Other Album", "."):
        response = await client.post(
            "/api/v1/admin/maintenance/albumartist-edit/execute",
            json={"artist": "A", "album": traversal_album, "new_album_artist": "Pwned"},
            headers=_SAME_ORIGIN,
        )
        assert response.status_code == 200, traversal_album
        assert response.json()["success_count"] == 0, traversal_album

    assert MP4(own).tags.get("aART") is None
    assert MP4(other).tags.get("aART") is None


@requires_ffmpeg
@pytest.mark.asyncio
async def test_albumartist_edit_rejects_path_traversal_artist_value(client, lib):
    """Security-Regression (Adversarial-Review-Fund 2026-09-21, Runde 2)
    — siehe test_album_edit_rejects_path_traversal_artist_value()."""
    other = lib / "B" / "2021 - Other Album" / "01 - b.m4a"
    _m4a(other, artist="B")

    response = await client.post(
        "/api/v1/admin/maintenance/albumartist-edit/execute",
        json={"artist": ".", "album": "2021 - Other Album", "new_album_artist": "Pwned"},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 200
    assert response.json()["success_count"] == 0
    assert MP4(other).tags.get("aART") is None
