# control_center/routers/jobs.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/jobs (+ /{job_id}), POST /demo, POST /repair-safe-automatic,
POST /{job_id}/cancel — Jobs-Grundgerüst + erster echter Job-Typ.

Reine Orchestrierung um services/jobs/job_registry.py::JobRegistry.
Registry liegt in app.state.job_registry (control_center/app.py) — EINE
Instanz pro Prozess, per Dependency injiziert statt Modul-Level-Global,
damit jeder Testlauf (der create_app() frisch aufruft, wie alle
bestehenden control_center-Tests bereits tun) automatisch eine isolierte
Registry bekommt, ohne einen eigenen Reset-Mechanismus zu brauchen.

Phase 1 (Grundgerüst): "demo_progress" (POST /demo) — läuft fünf Sekunden
lang und zählt Fortschritt hoch, führt keine reale Operation aus (Master-
Prompt Regel 39: keine Fake-Implementierung, die wie eine fertige
Funktion aussieht). Beweist die Infrastruktur (Erstellen/Abfragen/
Auflisten/Abbrechen).

Phase 2 (dieser Nachtrag): "repair_safe_automatic" (POST
/repair-safe-automatic) — der erste echte, destruktive Job-Typ. Bildet
GENAU das bereits produktive "🩺 MusicBot Doctor"-Verhalten aus Telegram
nach (handlers/library_doctor_handler.py::handle_apply_safe_confirmed()):
Health-Scan + SAFE_AUTOMATIC-Apply über
services/library_repair/doctor_runner.py::run_health_scan()/
run_safe_automatic_repair() (Subprozesse, bereits mit Backup/Rollback/
Journal abgesichert) — keine neue Ausführungslogik, nur eine neue Tür
(Web statt Telegram) zu einer bestehenden, bereits sicheren Fähigkeit.
Bewusst NUR dieser eine Level (kein Netzwerk, kein Re-Encode, kein
externer Aufruf) — EXTERNAL_METADATA/COVER/
LOUDNESS/DUPLICATE bleiben über diesen Weg unerreichbar, identische
Sicherheitsgrenze wie doctor_runner.py selbst.

"Preview" für diesen Job ist bewusst kein neuer Mechanismus — GET
/api/v1/library/repair-plan (bereits vorhanden) zeigt schon vorher, wie
viele SAFE_AUTOMATIC-Kandidaten existieren, bevor der Job gestartet wird.

Kooperatives Abbrechen ist NUR zwischen Scan und Repair wirksam (Aufruf
von is_cancel_requested() nach dem Scan, vor dem Start des Repair-
Subprozesses) — ein bereits laufender doctor_runner.py-Subprozess selbst
kann von hier aus nicht abgebrochen werden (dessen _run_subprocess()
kapselt den Prozess-Handle vollständig, kein Kill-Zugriff von aussen).
Das ist eine bewusste, dokumentierte Einschränkung, keine verschleierte
Lücke (Master-Prompt Regel 39).

Phase 3 (dieser Nachtrag): "repair_level3" (POST /repair-level3) —
Pendant zu ARCH-033 §12 (Telegram Level-3-Reparatur, Pro-Artist,
`docs/LIBRARY_REPAIR.md`). Der frühere Job-Typ "repair_level2"
(METADATA_REPROCESSING) wurde in CC-LIB-FINAL ersatzlos entfernt: er
hätte manuelle Metadaten-Änderungen durch eine Neuableitung
überschreiben können. Bildet den bestehenden `l23rep:*`-Telegram-Subflow
nach (handlers/repair_musicbot_handler.py::_run_l23_execute_and_report()):
ruft ausschließlich services/library_repair/repair_service.py::
execute_level3_repair() auf — dieselbe
Orchestrierung (Health-Scan + Stale-Plan-Schutz + Subprozess über
doctor_runner.run_level3_repair() + Verification-
Rescan + Run-History-Eintrag), inkl. desselben prozessübergreifenden
Locks wie Telegram/CLI (services/library_repair/run_tracking.py::
acquire_repair_lock() — ein bereits laufender Telegram- oder CLI-Lauf
lässt den Job kontrolliert als FAILED enden, kein stiller Konflikt).

**Bewusst KEIN globaler Batch-Button wie SAFE_AUTOMATIC** — L3 ist
nur pro Artist ausführbar (ADR-0003, identische Begründung wie Telegram:
L3 macht MusicBrainz-/Netzwerkfehler je Datei sichtbar statt sie still
zu überspringen). Die
Artist-Auswahl selbst kommt aus GET /api/v1/library/repair-plan/by-artist
(routers/repair.py).

**Kooperatives Abbrechen ist für diesen Job-Typ NICHT wirksam**
(anders als repair_safe_automatic oben): execute_level3_repair()
ist ein einzelner atomarer Aufruf ohne
Zwischenpunkt, an dem is_cancel_requested() sinnvoll geprüft werden
könnte (Scan, Subprozess und Verification laufen komplett innerhalb
dieses einen awaits). POST /{job_id}/cancel bleibt zwar technisch
erreichbar (generischer Endpunkt für alle Job-Typen), hat für diesen
Kind aber keine Wirkung — bewusst nicht verschleiert (Master-
Prompt Regel 39), sondern hier UND im UI-Folgeschritt explizit
dokumentiert statt eine funktionierende Abbrechen-Fähigkeit vorzutäuschen.

Phase 4 (dieser Nachtrag, api_health.md Abschnitt 5): "library_health_scan"
(POST /health-scan) — deckt den in api_health.md Abschnitt 5 geforderten
asynchronen Health-Scan-Start ab ("Wenn der Scan länger läuft: als Job
ausführen"). Ruft ausschließlich services/library_repair/doctor_runner.py::
run_health_scan() auf — denselben Subprozess-Aufruf wie die erste Phase
von _run_safe_automatic_repair_job() oben, nur ohne die anschließende
Reparatur. Bewusst NICHT die leichtgewichtige, rein synchrone
control_center/_library_scan.py::run_library_scan() (Konsument: GET
/health, GET /repair-plan) — jene führt nur einen In-Memory-Scan für genau
EINE HTTP-Response aus, schreibt weder den persistenten Report noch die
Score-History noch mergt sie die Findings-Registry (siehe deren
Modul-Docstring). run_health_scan() dagegen startet
scripts/library_health_check.py als Subprozess, der genau diese drei
Seiteneffekte auslöst (Report-Datei, services/library_health/
score_history.py::append_score_history(), FindingsRegistry.
merge_scan_issues()) — identischer Pfad wie ein Telegram-"🩺 MusicBot
Doctor"-Scan. GET /health und GET /repair-plan bleiben davon unberührt
(Auftrag §43-Hard-Stop-Geist, CLAUDE.md Abschnitt 20): kein bestehender
Endpunkt wird umgestellt, nur additiv ein neuer Job-Typ ergänzt.

POST /demo, POST /repair-safe-automatic,
POST /repair-level3, POST /health-scan und POST /{job_id}/cancel sind
schreibend — alle über verify_same_origin() CSRF-geschützt, identisches
Muster wie Findings Accept/Unaccept.

Authentifiziert mit mindestens AccessLevel.ADMIN.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from config import Config
from cookie_handler import CookieHandler
from services.access_control import AccessLevel
from logger import get_module_logger
from services.downloader import download_pipeline_core as pipeline_core
from services.jobs.job_context import bind_job
from services.downloader.active_downloads import ActiveDownload
from services.downloader.download_concurrency import download_slot
from services.downloader.download_history import DownloadHistoryStore
from services.downloader.download_result_reporter import DownloadResultReporter
from services.downloader.downloader import YoutubeDownloader
from services.duplicate.detector import DuplicateDetector
from services.jobs.job_registry import JobRegistry
from services.jobs.step_context import step_reporter
from services.library_repair.doctor_runner import run_health_scan, run_safe_automatic_repair
from services.library_repair.duplicate_runner import run_duplicate_scan
from services.library_repair.genre_revalidation_runner import run_genre_revalidation_subprocess
from services.library_repair.repair_service import (
    RepairAlreadyRunningError,
    execute_level3_repair,
)

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.errors import ErrorDetail
from ..schemas.jobs import (
    ArtistLevelRepairRequest,
    DownloadJobRequest,
    JobListResponse,
    JobSchema,
    job_to_schema,
    jobs_to_response,
)

router = APIRouter(
    prefix="/api/v1/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.jobs")

_DEMO_JOB_STEPS = 5
_DEMO_JOB_STEP_SECONDS = 1


def get_job_registry(request: Request) -> JobRegistry:
    return request.app.state.job_registry


def _get_job_or_404(registry: JobRegistry, job_id: str):
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(code="JOB_NOT_FOUND", message="Unbekannte Job-ID.").model_dump(),
        )
    return job


async def _run_demo_job(registry: JobRegistry, job_id: str) -> None:
    """Reine Test-/Demo-Fähigkeit — führt nichts Reales aus (siehe
    Modul-Docstring). Kooperatives Abbrechen: prüft is_cancel_requested()
    zwischen jedem Schritt, identisches Prinzip wie
    services/downloader/active_downloads.py::ActiveDownload.is_cancel_requested()."""
    registry.mark_running(job_id)
    try:
        for step in range(1, _DEMO_JOB_STEPS + 1):
            if registry.is_cancel_requested(job_id):
                registry.mark_cancelled(job_id)
                return
            await asyncio.sleep(_DEMO_JOB_STEP_SECONDS)
            registry.update_progress(
                job_id, (step / _DEMO_JOB_STEPS) * 100, f"Demo-Schritt {step}/{_DEMO_JOB_STEPS}"
            )
        registry.mark_succeeded(job_id, result={"steps_completed": _DEMO_JOB_STEPS})
    except Exception as e:  # noqa: BLE001
        _logger.error(f"Demo-Job {job_id} fehlgeschlagen: {e!r}")
        registry.mark_failed(job_id, "Interner Fehler im Demo-Job.")


@router.get("", response_model=JobListResponse)
def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobListResponse:
    return jobs_to_response(registry.list(limit=limit))


@router.get("/{job_id}", response_model=JobSchema)
def get_job(job_id: str, registry: JobRegistry = Depends(get_job_registry)) -> JobSchema:
    job = _get_job_or_404(registry, job_id)
    return job_to_schema(job)


@router.post("/demo", response_model=JobSchema, dependencies=[Depends(verify_same_origin)])
async def start_demo_job(
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobSchema:
    job = registry.create(kind="demo_progress", initiator=str(user_id))
    asyncio.create_task(_run_demo_job(registry, job.job_id))
    return job_to_schema(job)


async def _run_health_scan_job(registry: JobRegistry, job_id: str) -> None:
    """Reiner Health-Scan als Job (siehe Modul-Docstring, Phase 4) — der
    Scan-Teil von _run_safe_automatic_repair_job() unten, isoliert ohne
    anschliessende Reparatur. Kein Zwischen-Checkpoint fuer
    is_cancel_requested() (der Subprozess selbst kann von hier aus nicht
    unterbrochen werden, identische Einschraenkung wie beim Scan-Schritt
    unten)."""
    registry.mark_running(job_id)
    try:
        registry.update_progress(job_id, 10.0, "Health-Scan läuft…")
        scan_result = await run_health_scan()
        if not scan_result.success:
            registry.mark_failed(
                job_id,
                "Health-Scan fehlgeschlagen.",
                result={
                    "exit_code": scan_result.exit_code,
                    "stderr_tail": scan_result.stderr_tail,
                },
            )
            return

        report = scan_result.report or {}
        registry.mark_succeeded(
            job_id,
            result={
                "health": report.get("health", {}),
                "library": report.get("library", {}),
                "stdout_tail": scan_result.stdout_tail,
            },
        )
    except Exception as e:  # noqa: BLE001
        _logger.error(f"Health-Scan-Job {job_id} fehlgeschlagen: {e!r}")
        registry.mark_failed(job_id, "Interner Fehler im Health-Scan-Job.")


@router.post(
    "/health-scan",
    response_model=JobSchema,
    dependencies=[Depends(verify_same_origin)],
)
async def start_health_scan_job(
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobSchema:
    job = registry.create(kind="library_health_scan", initiator=str(user_id))
    asyncio.create_task(_run_health_scan_job(registry, job.job_id))
    return job_to_schema(job)


async def _run_safe_automatic_repair_job(registry: JobRegistry, job_id: str) -> None:
    """Bildet handlers/library_doctor_handler.py::handle_apply_safe_confirmed()
    nach (siehe Modul-Docstring) — ruft ausschliesslich die bestehenden,
    bereits produktiven doctor_runner.py-Subprozess-Funktionen auf, keine
    eigene Ausführungslogik."""
    registry.mark_running(job_id)
    try:
        registry.update_progress(job_id, 10.0, "Health-Scan läuft…")
        scan_result = await run_health_scan()
        if not scan_result.success:
            registry.mark_failed(
                job_id,
                "Health-Scan fehlgeschlagen — Reparatur wurde nicht gestartet.",
                result={
                    "phase": "scan",
                    "exit_code": scan_result.exit_code,
                    "stderr_tail": scan_result.stderr_tail,
                },
            )
            return

        if registry.is_cancel_requested(job_id):
            # Nur zwischen Scan und Repair wirksam (Modul-Docstring) - ein
            # bereits laufender Repair-Subprozess selbst liesse sich von
            # hier aus nicht mehr abbrechen.
            registry.mark_cancelled(job_id)
            return

        registry.update_progress(job_id, 50.0, "SAFE_AUTOMATIC-Reparatur läuft…")
        repair_result = await run_safe_automatic_repair()

        if repair_result.timed_out or repair_result.error_message:
            registry.mark_failed(
                job_id, repair_result.error_message or "Timeout beim Repair-Lauf.",
            )
            return

        result = {
            "phase": "repair",
            "exit_code": repair_result.exit_code,
            "stdout_tail": repair_result.stdout_tail,
        }
        if repair_result.success:
            registry.mark_succeeded(job_id, result=result)
        else:
            registry.mark_failed(
                job_id, f"Repair-Lauf beendet mit Exit-Code {repair_result.exit_code}.",
                result=result,
            )
    except Exception as e:  # noqa: BLE001
        _logger.error(f"SAFE_AUTOMATIC-Repair-Job {job_id} fehlgeschlagen: {e!r}")
        registry.mark_failed(job_id, "Interner Fehler im Repair-Job.")


@router.post(
    "/repair-safe-automatic",
    response_model=JobSchema,
    dependencies=[Depends(verify_same_origin)],
)
async def start_safe_automatic_repair_job(
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobSchema:
    job = registry.create(kind="repair_safe_automatic", initiator=str(user_id))
    asyncio.create_task(_run_safe_automatic_repair_job(registry, job.job_id))
    return job_to_schema(job)


_LEVEL_LABELS = {"l3": "L3 (EXTERNAL_METADATA)"}


async def _run_level_repair_job(
    registry: JobRegistry, job_id: str, *, level: str, artist: str, user_id: str
) -> None:
    """Implementierung für repair_level3 - siehe Modul-Docstring
    (Phase 3). Kein Zwischen-Checkpoint für is_cancel_requested()
    möglich (execute_level3_repair() ist ein einzelner atomarer await)."""
    registry.mark_running(job_id)
    registry.update_progress(
        job_id, 10.0, f"{_LEVEL_LABELS[level]}-Reparatur läuft für {artist}…"
    )
    execute_fn = execute_level3_repair
    try:
        result = await execute_fn(artist, triggered_by=f"control_center:{user_id}")
    except RepairAlreadyRunningError as e:
        registry.mark_failed(job_id, str(e))
        return
    except Exception as e:  # noqa: BLE001
        _logger.error(f"{level.upper()}-Repair-Job {job_id} fehlgeschlagen: {e!r}")
        registry.mark_failed(job_id, "Interner Fehler im Repair-Job.")
        return

    # Finding #6: dieselben Rohdaten wie Telegram (_format_l23_result()) -
    # "geändert" ausschliesslich aus changed_files, unresolved und
    # exit_code explizit. affected_files (berührt, auch SKIPPED) bleibt
    # additiv/kompatibel erhalten, ist aber KEINE "geändert"-Quelle.
    # status UNRESOLVED/SKIPPED gilt als abgeschlossener Job (SUCCEEDED),
    # nur FAILED als fehlgeschlagener Job.
    result_dict = {
        "repair_id": result.repair_id,
        "artist": result.artist,
        "level": result.level,
        "status": result.status,
        "total": result.total,
        "success": result.success,
        "failed": result.failed,
        "skipped": result.skipped,
        "unresolved": result.unresolved,
        "resolved_count": result.resolved_count,
        "affected_files": result.affected_files,
        "changed_files": result.changed_files,
        "exit_code": result.exit_code,
        "rescan_triggered": result.rescan_triggered,
    }
    if result.status == "FAILED":
        registry.mark_failed(
            job_id, result.error_message or "Reparatur fehlgeschlagen.", result=result_dict,
        )
    else:
        registry.mark_succeeded(job_id, result=result_dict)


def _require_artist(payload: ArtistLevelRepairRequest) -> str:
    artist = payload.artist.strip()
    if not artist:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(code="ARTIST_REQUIRED", message="Artist darf nicht leer sein.").model_dump(),
        )
    return artist


@router.post(
    "/repair-level3",
    response_model=JobSchema,
    dependencies=[Depends(verify_same_origin)],
)
async def start_level3_repair_job(
    payload: ArtistLevelRepairRequest,
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobSchema:
    artist = _require_artist(payload)
    job = registry.create(kind="repair_level3", initiator=str(user_id))
    asyncio.create_task(
        _run_level_repair_job(registry, job.job_id, level="l3", artist=artist, user_id=str(user_id))
    )
    return job_to_schema(job)


@router.post(
    "/{job_id}/cancel", response_model=JobSchema, dependencies=[Depends(verify_same_origin)]
)
def cancel_job(job_id: str, registry: JobRegistry = Depends(get_job_registry)) -> JobSchema:
    job = _get_job_or_404(registry, job_id)
    registry.request_cancel(job_id)
    return job_to_schema(job)


# ═══════════════════════════════════════════════════════════════════════════
# DOWNLOAD-JOB (Client Consolidation Phase D/E, "download_track")
# ═══════════════════════════════════════════════════════════════════════════
#
# Erster CC-eigener Download-Weg (docs/FINDINGS_INDEX.md "Downloads nicht
# aus dem Control Center startbar", Architekturentscheidung siehe
# docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md Abschnitt 11):
# CC-lokaler JobRegistry-Job (identisches Muster wie repair_safe_automatic/
# repair_level3 oben), der die bereits Telegram-freien
# services/downloader/downloader.py::YoutubeDownloader +
# services/duplicate/detector.py::DuplicateDetector +
# services/downloader/download_pipeline_core.py (Move aus
# klassen/download_handler.py, siehe dortigen Modul-Docstring) DIREKT
# aufruft - kein Cross-Prozess-Zugriff auf die Telegram-eigene
# ActiveDownloadRegistry (die bleibt bewusst Bot-Prozess-lokal, siehe
# services/downloader/active_downloads.py-Docstring), keine zweite
# Download-Implementierung.
#
# Eigener Router mit AccessLevel.USER (statt des ADMIN-Floors von `router`
# oben) - Parität zu Telegram: jeder authentifizierte Nutzer darf für sich
# selbst einen Download starten, nicht nur Admins. Die generischen
# GET/POST-{job_id}-Endpunkte oben bleiben bewusst ADMIN-only (sie filtern
# nicht nach initiator - ein Repair-/Health-Scan-Job ist admin-only
# Fachlogik). Für USER-Downloads gibt es daher eigene, auf den eigenen
# initiator beschränkte Status-/Cancel-Endpunkte unten
# (_get_own_download_job_or_404()) statt der generischen.
#
# chat_id für ActiveDownload/DownloadHistoryStore/DuplicateDetector.
# register_download() ist die eigene Telegram-ID des eingeloggten Nutzers
# (get_current_user_id() - Telegram-Login-Widget-Auth, siehe
# control_center/dependencies.py) - dieselbe ID, unter der ein Download
# in der Telegram-eigenen "📋 Download-Verlauf"-Ansicht erscheinen würde
# (private Chats: chat_id == user_id), keine synthetische ID.
user_router = APIRouter(
    prefix="/api/v1/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_min_access_level(AccessLevel.USER))],
)

_DOWNLOAD_JOB_KIND = "download_track"


def _get_own_download_job_or_404(registry: JobRegistry, job_id: str, user_id: int):
    """Wie _get_job_or_404(), zusätzlich auf den eigenen Download-Job
    beschränkt (kind + initiator) - ohne diese Prüfung könnte ein Nutzer
    per erratener/hochgezählter job_id den Status oder Cancel-Button eines
    FREMDEN Jobs (auch eines ADMIN-only Repair-Jobs) erreichen."""
    job = registry.get(job_id)
    if job is None or job.kind != _DOWNLOAD_JOB_KIND or job.initiator != str(user_id):
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(code="JOB_NOT_FOUND", message="Unbekannte Job-ID.").model_dump(),
        )
    return job


async def _cancel_bridge(
    registry: JobRegistry, job_id: str, active_download: ActiveDownload, poll_interval: float = 0.5
) -> None:
    """Bridged JobRegistry.request_cancel(job_id) (der generische, auf den
    eigenen Job beschränkte Cancel-Endpunkt unten) zum
    ActiveDownload.cancel_event, das YoutubeDownloader tatsächlich prüft
    (services/downloader/active_downloads.py) - ohne diese Brücke wäre
    Cancel für Download-Jobs nur zwischen den Pipeline-Schritten wirksam
    (analog zur dokumentierten Einschränkung von repair_safe_automatic),
    nicht während eines laufenden yt-dlp-Tracks/einer Playlist. Endet von
    selbst, sobald der Download fertig ist (finally im Aufrufer bricht ab)."""
    try:
        while not active_download.is_cancel_requested():
            if registry.is_cancel_requested(job_id):
                active_download.request_cancel()
                return
            await asyncio.sleep(poll_interval)
    except asyncio.CancelledError:
        pass


async def _run_download_job(
    registry: JobRegistry,
    job_id: str,
    *,
    url: str,
    download_type: str,
    chat_id: int,
    config: Config,
    duplicate_detector: DuplicateDetector,
    cookie_handler: CookieHandler,
    download_history: DownloadHistoryStore,
) -> None:
    """D.12b.2-Huelle: setzt den task-lokalen Job-Kontext und
    delegiert an _run_download_job_impl (unveraenderter Body).
    Der ContextVar wird von asyncio.create_task in die neue Task
    kopiert und ist damit fuer alle Log-Records des Download-
    Call-Trees aktiv."""
    with bind_job(job_id):
        await _run_download_job_impl(
            registry,
            job_id,
            url=url,
            download_type=download_type,
            chat_id=chat_id,
            config=config,
            duplicate_detector=duplicate_detector,
            cookie_handler=cookie_handler,
            download_history=download_history,
        )


async def _run_download_job_impl(
    registry: JobRegistry,
    job_id: str,
    *,
    url: str,
    download_type: str,
    chat_id: int,
    config: Config,
    duplicate_detector: DuplicateDetector,
    cookie_handler: CookieHandler,
    download_history: DownloadHistoryStore,
) -> None:
    """Bildet klassen/download_handler.py::handle_youtube_links() nach
    (Sequenzierung: Duplikat-Check -> Download -> Datei-Konflikt ->
    Metadaten-Pass-Through -> Registrierung/History -> Zusammenfassung),
    ruft dafür aber ausschliesslich die extrahierten, Telegram-freien
    Bausteine aus services/downloader/download_pipeline_core.py sowie
    YoutubeDownloader/DownloadResultReporter direkt auf - siehe
    Sektions-Docstring oben. Die SEQUENZ selbst ist hier (analog zu einem
    eigenen Client) neu geschrieben, weil sie in
    klassen/download_handler.py mit Telegram-Statusnachrichten verzahnt
    ist (siehe dortigen Docstring von handle_youtube_links()) - jede
    einzelne Fachregel darin (Duplikat-Ebenen, Datei-Konflikt-Erkennung,
    Playlist-Wrapper, dreiwertige Metadata-Checkliste) ruft aber exakt
    dieselbe, einzige Implementierung auf wie der Telegram-Pfad.

    logger = get_module_logger() statt self.logger (kein Handler-Objekt
    hier) - _logger (Modul-Ebene) wird verwendet."""
    registry.mark_running(job_id)
    result_reporter = DownloadResultReporter(logger=_logger)
    active_download = ActiveDownload(chat_id=chat_id, url=url, download_type=download_type)
    bridge_task = asyncio.create_task(_cancel_bridge(registry, job_id, active_download))

    async def _status_callback(tracker) -> None:
        total = tracker.total_items or 0
        registry.update_progress(
            job_id,
            30.0,
            f"Download läuft… {tracker.processed_items}/{total}" if total else "Download läuft…",
        )

    def _fail_with_history(message: str) -> None:
        pipeline_core.record_history_entry(
            download_history, chat_id, url=url, title="Unbekannt", artist="Unbekannt",
            status="failed", logger=_logger,
        )
        registry.mark_failed(job_id, message)

    try:
        max_concurrent = getattr(config, "MAX_CONCURRENT_DOWNLOADS", 3) or 3
        async with download_slot(max_concurrent):
            if registry.is_cancel_requested(job_id):
                registry.mark_cancelled(job_id)
                return

            registry.update_progress(job_id, 5.0, "Duplikat-Prüfung…")
            downloader = YoutubeDownloader(
                chat_id=chat_id,
                update_id=0,
                config=config,
                cookie_handler=cookie_handler,
                duplicate_detector=duplicate_detector,
                status_callback=_status_callback,
                active_download=active_download,
            )

            is_dup, entry, dup_type = await pipeline_core.check_duplicates_before_download(
                duplicate_detector, downloader, config, url, _logger
            )
            if is_dup and entry:
                message = result_reporter.build_duplicate_message(entry, dup_type)
                registry.mark_succeeded(
                    job_id,
                    result={"outcome": "duplicate", "message": message, "artist": entry.artist},
                )
                return

            registry.update_progress(job_id, 20.0, "Download läuft…")
            # D.12c: feine Metadaten-Schritte (EnhancedMetadataProcessor ->
            # report_step()) nur bei Single-Downloads in den Job-Verlauf -
            # bei Playlists wuerden ~10 Schritte pro Track die
            # MAX_JOB_EVENTS-Grenze sofort sprengen. Task-lokal
            # (contextvars), daher auch bei parallelen Jobs sauber getrennt.
            if download_type == "single":
                step_scope = step_reporter(
                    lambda step: registry.update_progress(job_id, 20.0, f"Metadaten: {step}")
                )
            else:
                step_scope = contextlib.nullcontext()
            try:
                with step_scope:
                    download_result = await downloader.download_audio(url)
            except asyncio.CancelledError as ce:
                partial_results = getattr(ce, "partial_playlist_results", None)
                if partial_results:
                    pipeline_core.register_playlist_track_duplicates(
                        duplicate_detector, download_history, chat_id, partial_results, _logger
                    )
                raise

            if not download_result:
                _fail_with_history("Download-Ergebnis war leer oder ungültig.")
                return

            if download_result.get("cancelled") and not download_result.get("tracks"):
                pipeline_core.record_history_entry(
                    download_history, chat_id, url=url, title="Unbekannt", artist="Unbekannt",
                    status="cancelled", logger=_logger,
                )
                registry.mark_cancelled(job_id)
                return

            if not download_result.get("success"):
                _fail_with_history(download_result.get("error", "Unbekannter Fehler."))
                return

            registry.update_progress(job_id, 70.0, "Metadaten werden verarbeitet…")
            results_list = download_result if isinstance(download_result, list) else [download_result]
            processed_results = []
            for res in results_list:
                if not (isinstance(res, dict) and res.get("success")):
                    continue
                if res.get("renamed_due_to_conflict"):
                    conflict_entry = pipeline_core.resolve_file_conflict_as_duplicate(res, url, _logger)
                    message = result_reporter.build_duplicate_message(conflict_entry, "file_conflict")
                    registry.mark_succeeded(
                        job_id,
                        result={
                            "outcome": "duplicate",
                            "message": message,
                            "artist": conflict_entry.artist,
                        },
                    )
                    return
                res["original_url"] = url
                processed_results.append(await pipeline_core.process_single_download_result(res, _logger))

            if not processed_results:
                # Charakterisierungsfund (Client Consolidation Phase D/E):
                # der Telegram-Pfad (handle_youtube_links()) bleibt in
                # diesem Fall stumm (nur Log-Warnung, keine Nutzer-
                # Rückmeldung) - für einen Job MUSS ein Terminalstatus
                # gesetzt werden, ein für immer "RUNNING" bleibender Job
                # wäre irreführend. Bewusste, kleine Abweichung: FAILED
                # statt stillem Nichts-Tun.
                registry.mark_failed(job_id, "Keine erfolgreichen Ergebnisse.")
                return

            registry.update_progress(job_id, 90.0, "Zusammenfassung wird erstellt…")
            dup_stats = getattr(duplicate_detector, "get_statistics", lambda: {})()

            if len(processed_results) == 1 and processed_results[0].get("type") == "playlist":
                playlist_result = processed_results[0]
                tracks = playlist_result.get("tracks", [])
                total = len(tracks)
                ok = sum(1 for t in tracks if t.get("success"))
                if total > 0 and ok == 0:
                    _fail_with_history(f"Alle {total} Tracks der Playlist sind fehlgeschlagen.")
                    return
                pipeline_core.register_playlist_track_duplicates(
                    duplicate_detector, download_history, chat_id, tracks, _logger
                )
                stats = result_reporter.extract_stats_from_result(playlist_result, [])
                message = result_reporter.build_final_summary_message(playlist_result, stats, dup_stats)
                registry.mark_succeeded(job_id, result={"outcome": "success", "message": message})
                return

            if len(processed_results) == 1:
                single = processed_results[0]
                title = single.get("title", "?")
                artist = single.get("artist", "?")
                url_for_entry = single.get("original_url") or single.get("url") or ""
                pipeline_core.record_history_entry(
                    download_history, chat_id, url=url_for_entry, title=title, artist=artist,
                    status="success",
                    genre_ok=bool(single.get("genres")),
                    lyrics_ok=bool(single.get("lyrics_available")),
                    cover_ok=bool(single.get("cover_embedded")),
                    mb_ok=bool(single.get("mb_ids_present")),
                    loudness_ok=bool(single.get("loudness_normalized")),
                    logger=_logger,
                )
                pipeline_core.register_single_track_duplicate(
                    duplicate_detector, url=url_for_entry, artist=artist, title=title,
                    path=single.get("library_path") or single.get("filepath") or "",
                    album=single.get("album"), year=single.get("year"), logger=_logger,
                )
                stats = result_reporter.extract_stats_from_result(single, [])
                message = result_reporter.build_final_summary_message(single, stats, dup_stats)
                registry.mark_succeeded(job_id, result={"outcome": "success", "message": message})
                return

            # Mehrere, nicht als Playlist-Wrapper gebündelte Ergebnisse -
            # bewusst identisch zu handle_playlist_success()'s letztem
            # Zweig: KEINE Registrierung/History hier (Charakterisierung
            # aus klassen/download_handler.py, kein eigener Entscheid).
            successful = [r for r in processed_results if r.get("success")]
            if not successful:
                registry.mark_failed(job_id, "Keine erfolgreichen Tracks.")
                return
            message = result_reporter.build_playlist_summary_message(processed_results, successful)
            registry.mark_succeeded(job_id, result={"outcome": "success", "message": message})

    except Exception as e:  # noqa: BLE001
        _logger.error(f"Download-Job {job_id} fehlgeschlagen: {e!r}")
        registry.mark_failed(job_id, "Interner Fehler im Download-Job.")
    finally:
        bridge_task.cancel()


@user_router.post(
    "/download", response_model=JobSchema, dependencies=[Depends(verify_same_origin)]
)
async def start_download_job(
    payload: DownloadJobRequest,
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobSchema:
    url = payload.url.strip()
    if not pipeline_core.is_supported_download_url(url):
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(
                code="URL_NOT_SUPPORTED",
                message="Diese URL wird nicht unterstützt. Nur YouTube-Links.",
            ).model_dump(),
        )

    config = Config()
    # Playlist/Single-Erkennung einmal hier berechnet und sowohl als
    # `context` (fuer eine sofort sichtbare UI-Kennzeichnung, bereits waehrend
    # PENDING/RUNNING) als auch an _run_download_job() weitergereicht - keine
    # zweite Berechnung, identische Regel wie handlers/-seitig.
    download_type = "playlist" if "list=" in url else "single"
    job = registry.create(
        kind=_DOWNLOAD_JOB_KIND,
        initiator=str(user_id),
        context={"url": url, "download_type": download_type},
    )
    asyncio.create_task(
        _run_download_job(
            registry,
            job.job_id,
            url=url,
            download_type=download_type,
            chat_id=user_id,
            config=config,
            duplicate_detector=DuplicateDetector(config),
            cookie_handler=CookieHandler(),
            download_history=DownloadHistoryStore(cache_dir=str(config.DOWNLOAD_HISTORY_DIR)),
        )
    )
    return job_to_schema(job)


@user_router.get("/download/{job_id}", response_model=JobSchema)
def get_own_download_job(
    job_id: str,
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobSchema:
    return job_to_schema(_get_own_download_job_or_404(registry, job_id, user_id))


@user_router.post(
    "/download/{job_id}/cancel",
    response_model=JobSchema,
    dependencies=[Depends(verify_same_origin)],
)
def cancel_own_download_job(
    job_id: str,
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobSchema:
    job = _get_own_download_job_or_404(registry, job_id, user_id)
    registry.request_cancel(job_id)
    return job_to_schema(job)


# ── Genre-Revalidierung (Last.fm erneut abfragen, Overturn-Regel) ──────────
#
# Bildet den bereits produktiven Telegram-Flow nach
# (handlers/library_maintenance_handler.py: gr_preview -> Bestaetigung ->
# gr_apply) ueber dieselbe Service-Funktion
# services/library_repair/genre_revalidation_runner.py::
# run_genre_revalidation_subprocess() — keine eigene Fachlogik, keine zweite
# Overturn-Regel. Zwei Job-Typen statt einem synchronen Request: der Lauf
# ruft Last.fm auf und darf bis zu 60 s dauern (Reverse-Proxy-Timeout-Risiko,
# siehe docs/CONTROL_CENTER_REVERSE_PROXY.md).
#
# WICHTIG (Semantik): eine Revalidierung veraendert KEINE Audio-Datei und NICHT
# artist_genre.yaml. Sie schreibt hoechstens eine Beobachtung in
# mapping/auto_learned_genre.json (gelerntes Genre fuer kuenftige Downloads) und
# ist fuer Artists mit manuellem Mapping IMMER blockiert (BLOCKED_MANUAL).
# Kooperatives Abbrechen ist wirkungslos (ein einzelner atomarer await).

_GENRE_REVALIDATION_STDERR_TAIL = 500


def _require_revalidation_artist(payload: ArtistLevelRepairRequest) -> str:
    artist = _require_artist(payload)
    # Der Name wird als Kommandozeilenargument an scripts/revalidate_genre.py
    # gereicht: ein fuehrendes "-" wuerde dort als Option gelesen.
    if artist.startswith("-") or len(artist) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in artist):
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(
                code="ARTIST_INVALID",
                message="Artist-Name ungültig (führendes '-', Steuerzeichen oder länger als 200 Zeichen).",
            ).model_dump(),
        )
    return artist


async def _run_genre_revalidation_job(
    registry: JobRegistry, job_id: str, *, artist: str, apply: bool, user_id: str,
) -> None:
    registry.mark_running(job_id)
    registry.update_progress(
        job_id, 10.0,
        f"Last.fm wird für {artist} abgefragt…" if not apply
        else f"Genre-Revalidierung wird für {artist} angewendet…",
    )
    try:
        run = await run_genre_revalidation_subprocess(
            artist, apply=apply, triggered_by=f"control_center:{user_id}",
        )
    except RepairAlreadyRunningError as e:
        registry.mark_failed(job_id, str(e))
        return
    except Exception as e:  # noqa: BLE001
        _logger.error(f"Genre-Revalidierungs-Job {job_id} fehlgeschlagen: {e!r}")
        registry.mark_failed(job_id, "Interner Fehler bei der Genre-Revalidierung.")
        return

    if run.timed_out or run.error_message:
        registry.mark_failed(job_id, run.error_message or "Timeout bei der Genre-Revalidierung.")
        return
    if not run.success:
        registry.mark_failed(
            job_id, f"Genre-Revalidierung beendet mit Exit-Code {run.exit_code}.",
            result={
                "mode": "apply" if apply else "preview",
                "exit_code": run.exit_code,
                "stderr_tail": run.stderr_tail[-_GENRE_REVALIDATION_STDERR_TAIL:],
            },
        )
        return

    registry.mark_succeeded(
        job_id,
        result={
            **run.data,
            "mode": "apply" if apply else "preview",
            "exit_code": run.exit_code,
            # gelernte Genres liest der laufende Bot beim Start (GenreMapper)
            "bot_reload_required": bool(run.mutated),
        },
    )


@router.post(
    "/genre-revalidation-preview",
    response_model=JobSchema,
    dependencies=[Depends(verify_same_origin)],
)
async def start_genre_revalidation_preview_job(
    payload: ArtistLevelRepairRequest,
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobSchema:
    """Read-only: fragt Last.fm ab und zeigt, ob die Overturn-Regel eine
    Aenderung zuliesse. Schreibt nichts."""
    artist = _require_revalidation_artist(payload)
    job = registry.create(kind="genre_revalidation_preview", initiator=str(user_id))
    asyncio.create_task(
        _run_genre_revalidation_job(registry, job.job_id, artist=artist, apply=False, user_id=str(user_id))
    )
    return job_to_schema(job)


@router.post(
    "/genre-revalidation-apply",
    response_model=JobSchema,
    dependencies=[Depends(verify_same_origin)],
)
async def start_genre_revalidation_apply_job(
    payload: ArtistLevelRepairRequest,
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobSchema:
    """Fragt Last.fm erneut ab und schreibt die Beobachtung NUR, wenn die
    Overturn-Regel erfuellt ist (sonst keine Mutation). Die Entscheidung
    trifft der Service, nicht dieser Endpunkt."""
    artist = _require_revalidation_artist(payload)
    job = registry.create(kind="genre_revalidation_apply", initiator=str(user_id))
    asyncio.create_task(
        _run_genre_revalidation_job(registry, job.job_id, artist=artist, apply=True, user_id=str(user_id))
    )
    return job_to_schema(job)


# ── Duplikat-Check (read-only Vorschlag, kein Execute/Delete) ──────────────
#
# Backlog-Punkt "Duplikat-Check im CC" (docs/audits/
# WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md §2.3 A / §5 Nr. 4a).
# Bildet den bereits produktiven Telegram-Flow nach
# (handlers/duplicate_check_handler.py) über dieselbe Service-Funktion
# services/library_repair/duplicate_runner.py::run_duplicate_scan() —
# keine eigene Duplikat-Erkennung hier, keine zweite Fachlogik.
#
# Bewusst NUR dieser eine, read-only Job-Typ (kein "-apply"-Gegenstück wie
# bei der Genre-Revalidierung): das tatsächliche Löschen bleibt CLI-only
# (scripts/library_repair.py --allow-delete --artist <Name> --apply, siehe
# duplicate_runner.py-Docstring) — dieselbe bewusste Sicherheitsgrenze wie
# in Telegram, hier nur additiv eine zweite Tür zum bestehenden Preview.
#
# Anders als bei der Genre-Revalidierung wird `artist` hier NICHT als
# eigenständiges CLI-Argument übergeben, sondern von duplicate_runner.py in
# einen Pfad eingebettet (Path(Config.LIBRARY_DIR) / artist, als EIN
# "--path"-Wert) — eine führende "-" im Artist-Namen erzeugt daher keine
# CLI-Flag-Verwechslung (kein zusätzlicher Zeichen-Check wie bei
# _require_revalidation_artist nötig, `_require_artist` wie bei
# repair-level3 reicht). Die eigentliche Pfad-Sicherheit (Traversal)
# liegt ohnehin unabhängig vom Aufrufer in
# scripts/resolve_duplicates.py::validate_scan_root() (Allowlist/
# Denylist, siehe dortiger Docstring) — identisches Verteidigungsprinzip
# wie SEC-006 in services/backup_admin.py, nur eine Schicht tiefer im
# aufgerufenen Skript selbst.
#
# Kooperatives Abbrechen ist wirkungslos (ein einzelner atomarer await,
# identisch zur Genre-Revalidierung).

_DUPLICATE_CHECK_STDERR_TAIL = 500


async def _run_duplicate_check_job(
    registry: JobRegistry, job_id: str, *, artist: str, user_id: str,
) -> None:
    registry.mark_running(job_id)
    registry.update_progress(job_id, 10.0, f"Duplikat-Scan läuft für {artist}…")
    try:
        result = await run_duplicate_scan(artist)
    except RepairAlreadyRunningError as e:
        registry.mark_failed(job_id, str(e))
        return
    except Exception as e:  # noqa: BLE001
        _logger.error(f"Duplikat-Check-Job {job_id} fehlgeschlagen: {e!r}")
        registry.mark_failed(job_id, "Interner Fehler beim Duplikat-Check.")
        return

    if result.report is None:
        message = result.error_message or f"Duplikat-Scan beendet mit Exit-Code {result.exit_code}."
        registry.mark_failed(
            job_id, message,
            result={
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "stderr_tail": result.stderr_tail[-_DUPLICATE_CHECK_STDERR_TAIL:],
            },
        )
        return

    # report enthält ggf. read_only_intact=False (Exit-Code 3, vom Skript
    # SELBST erkannte Safety-Violation) — bewusst trotzdem SUCCEEDED, wie
    # in Telegram: es liegt ein gültiges, auswertbares Ergebnis vor, die
    # UI zeigt dafür die Sicherheitswarnung statt der Vorschlagsliste an.
    registry.mark_succeeded(job_id, result=result.report)


@router.post(
    "/duplicate-check",
    response_model=JobSchema,
    dependencies=[Depends(verify_same_origin)],
)
async def start_duplicate_check_job(
    payload: ArtistLevelRepairRequest,
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobSchema:
    """Read-only Dry-Run-Scan: sucht Duplikate für EINEN Artist und zeigt
    einen Vorschlag, löscht/schreibt nichts."""
    artist = _require_artist(payload)
    job = registry.create(kind="duplicate_check", initiator=str(user_id))
    asyncio.create_task(
        _run_duplicate_check_job(registry, job.job_id, artist=artist, user_id=str(user_id))
    )
    return job_to_schema(job)
