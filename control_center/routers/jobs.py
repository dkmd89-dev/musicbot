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
externer Aufruf) — METADATA_REPROCESSING/EXTERNAL_METADATA/COVER/
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

Phase 3 (dieser Nachtrag): "repair_level2"/"repair_level3" (POST
/repair-level2, POST /repair-level3) — Pendant zu ARCH-033 §12 (Telegram
Level-2/Level-3-Reparatur, Pro-Artist, `docs/LIBRARY_REPAIR.md`). Bildet
den bestehenden `l23rep:*`-Telegram-Subflow nach
(handlers/repair_musicbot_handler.py::_run_l23_execute_and_report()):
ruft ausschließlich services/library_repair/repair_service.py::
execute_level2_repair()/execute_level3_repair() auf — dieselbe
Orchestrierung (Health-Scan + Stale-Plan-Schutz + Subprozess über
doctor_runner.run_level2_repair()/run_level3_repair() + Verification-
Rescan + Run-History-Eintrag), inkl. desselben prozessübergreifenden
Locks wie Telegram/CLI (services/library_repair/run_tracking.py::
acquire_repair_lock() — ein bereits laufender Telegram- oder CLI-Lauf
lässt den Job kontrolliert als FAILED enden, kein stiller Konflikt).

**Bewusst KEIN globaler Batch-Button wie SAFE_AUTOMATIC** — L2/L3 sind
nur pro Artist ausführbar (ADR-0003, identische Begründung wie Telegram:
L2 durchläuft die volle Metadaten-Pipeline erneut, L3 macht MusicBrainz-/
Netzwerkfehler je Datei sichtbar statt sie still zu überspringen). Die
Artist-Auswahl selbst kommt aus GET /api/v1/library/repair-plan/by-artist
(routers/repair.py).

**Kooperatives Abbrechen ist für diese beiden Job-Typen NICHT wirksam**
(anders als repair_safe_automatic oben): execute_level2_repair()/
execute_level3_repair() sind ein einzelner atomarer Aufruf ohne
Zwischenpunkt, an dem is_cancel_requested() sinnvoll geprüft werden
könnte (Scan, Subprozess und Verification laufen komplett innerhalb
dieses einen awaits). POST /{job_id}/cancel bleibt zwar technisch
erreichbar (generischer Endpunkt für alle Job-Typen), hat für diese
beiden Kinds aber keine Wirkung — bewusst nicht verschleiert (Master-
Prompt Regel 39), sondern hier UND im UI-Folgeschritt explizit
dokumentiert statt eine funktionierende Abbrechen-Fähigkeit vorzutäuschen.

POST /demo, POST /repair-safe-automatic, POST /repair-level2,
POST /repair-level3 und POST /{job_id}/cancel sind schreibend — alle
über verify_same_origin() CSRF-geschützt, identisches Muster wie
Findings Accept/Unaccept.

Authentifiziert mit mindestens AccessLevel.ADMIN.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.jobs.job_registry import JobRegistry
from services.library_repair.doctor_runner import run_health_scan, run_safe_automatic_repair
from services.library_repair.repair_service import (
    RepairAlreadyRunningError,
    execute_level2_repair,
    execute_level3_repair,
)

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.errors import ErrorDetail
from ..schemas.jobs import (
    ArtistLevelRepairRequest,
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


_LEVEL_LABELS = {"l2": "L2 (METADATA_REPROCESSING)", "l3": "L3 (EXTERNAL_METADATA)"}


async def _run_level_repair_job(
    registry: JobRegistry, job_id: str, *, level: str, artist: str, user_id: str
) -> None:
    """Gemeinsame Implementierung für repair_level2/repair_level3 - siehe
    Modul-Docstring (Phase 3). Kein Zwischen-Checkpoint für
    is_cancel_requested() möglich (execute_level2_repair()/
    execute_level3_repair() sind ein einzelner atomarer await)."""
    registry.mark_running(job_id)
    registry.update_progress(
        job_id, 10.0, f"{_LEVEL_LABELS[level]}-Reparatur läuft für {artist}…"
    )
    execute_fn = execute_level2_repair if level == "l2" else execute_level3_repair
    try:
        result = await execute_fn(artist, triggered_by=f"control_center:{user_id}")
    except RepairAlreadyRunningError as e:
        registry.mark_failed(job_id, str(e))
        return
    except Exception as e:  # noqa: BLE001
        _logger.error(f"{level.upper()}-Repair-Job {job_id} fehlgeschlagen: {e!r}")
        registry.mark_failed(job_id, "Interner Fehler im Repair-Job.")
        return

    result_dict = {
        "repair_id": result.repair_id,
        "artist": result.artist,
        "level": result.level,
        "status": result.status,
        "total": result.total,
        "success": result.success,
        "failed": result.failed,
        "skipped": result.skipped,
        "resolved_count": result.resolved_count,
        "affected_files": result.affected_files,
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
    "/repair-level2",
    response_model=JobSchema,
    dependencies=[Depends(verify_same_origin)],
)
async def start_level2_repair_job(
    payload: ArtistLevelRepairRequest,
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobSchema:
    artist = _require_artist(payload)
    job = registry.create(kind="repair_level2", initiator=str(user_id))
    asyncio.create_task(
        _run_level_repair_job(registry, job.job_id, level="l2", artist=artist, user_id=str(user_id))
    )
    return job_to_schema(job)


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
