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

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.jobs.job_registry import JobRegistry
from services.library_repair.doctor_runner import run_health_scan, run_safe_automatic_repair
from services.library_repair.genre_revalidation_runner import run_genre_revalidation_subprocess
from services.library_repair.repair_service import (
    RepairAlreadyRunningError,
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
