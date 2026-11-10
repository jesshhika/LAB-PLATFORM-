import csv
import io
import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.compute.models import RunCommandInput
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from rq import Retry
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.app.auth import get_current_user_id, get_current_user_role
from api.app.catalog import get_course, get_guide_path, get_lab, load_courses
from api.app.core.config import get_settings
from api.app.core.db import get_db
from api.app.core.queue import default_queue
from api.app.cost_controls import (
    daily_vm_hours_reserved,
    guardrail_snapshot,
    initial_session_minutes,
    refusal_day_start,
    session_launch_lock,
)
from api.app.models import (
    AuditLog,
    Course,
    Enrollment,
    LabProgress,
    LabSession,
    LabUser,
    TaskProgress,
)
from api.app.services import build_connection_token, read_key_vault_secret
from worker.jobs import cleanup_lab_session

router = APIRouter(prefix="/api")
TASK_PATTERN = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+", re.MULTILINE)
logger = logging.getLogger(__name__)


class TaskUpdate(BaseModel):
    completed: bool


class SessionCreate(BaseModel):
    labId: str


def _session_for_user(
    db: Session,
    session_id: str,
    user_id: str,
    *,
    for_update: bool = False,
) -> LabSession:
    statement = select(LabSession).where(
        LabSession.id == session_id,
        LabSession.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    session = db.scalar(statement)
    if session is None:
        raise HTTPException(status_code=404, detail="Lab session not found.")
    return session


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _session_initial_minutes(course: dict[str, Any]) -> int:
    settings = get_settings()
    return initial_session_minutes(
        int(course.get("session_minutes", settings.session_max_minutes)),
        settings.session_max_minutes,
        settings.session_extension_minutes,
        settings.max_extensions,
    )


def _extend_ready_session(session: LabSession) -> datetime:
    now = datetime.now(UTC)
    if session.status != "ready" or _as_utc(session.expires_at) <= now:
        raise HTTPException(status_code=409, detail="Only an active session can be extended.")
    settings = get_settings()
    if session.extension_count >= settings.max_extensions:
        raise HTTPException(
            status_code=409,
            detail="The maximum session extension count has been reached.",
        )
    if session.started_at is None:
        raise HTTPException(
            status_code=409,
            detail="The session start time is unavailable; it cannot be extended safely.",
        )
    maximum_expiry = _as_utc(session.started_at) + timedelta(
        minutes=settings.session_max_minutes
    )
    if session.max_expires_at is not None:
        maximum_expiry = min(maximum_expiry, _as_utc(session.max_expires_at))
    new_expiry = min(
        _as_utc(session.expires_at) + timedelta(minutes=settings.session_extension_minutes),
        maximum_expiry,
    )
    if new_expiry <= _as_utc(session.expires_at):
        raise HTTPException(status_code=409, detail="The maximum session lifetime has been reached.")
    session.expires_at = new_expiry
    session.extension_count += 1
    return new_expiry


def _serialize_course(course: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": course["id"],
        "title": course["title"],
        "description": course.get("description", ""),
        "image": course.get("image", {}),
        "labs": [
            {
                "id": lab["id"],
                "number": lab["number"],
                "title": lab["title"],
            }
            for lab in course["labs"]
        ],
    }


def _progress_row(
    db: Session,
    user_id: str,
    lab_id: str,
) -> LabProgress | None:
    return db.scalar(
        select(LabProgress).where(
            LabProgress.user_id == user_id,
            LabProgress.lab_id == lab_id,
        )
    )


def _mark_complete(db: Session, user_id: str, lab_id: str, method: str) -> LabProgress:
    progress = _progress_row(db, user_id, lab_id)
    if progress is None:
        progress = LabProgress(user_id=user_id, lab_id=lab_id, completed=True, method=method)
        db.add(progress)
    elif not progress.completed:
        progress.completed = True
        progress.method = method
    progress.completed_at = progress.completed_at or datetime.now(UTC)
    db.commit()
    db.refresh(progress)
    return progress


def _read_validation_output(message: str) -> dict[str, Any]:
    marker = "[stdout]"
    output = message.split(marker, maxsplit=1)[-1]
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            result, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict) and isinstance(result.get("checks"), list):
            return result
    raise HTTPException(status_code=502, detail="The VM validation script returned invalid JSON.")


@router.get("/courses")
def courses(user_id: str = Depends(get_current_user_id)) -> dict[str, list[dict[str, Any]]]:
    del user_id
    return {"courses": [_serialize_course(course) for course in load_courses()]}


@router.get("/courses/{course_id}")
def course_detail(
    course_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    course = get_course(course_id)
    progress = {
        row.lab_id: row.completed
        for row in db.scalars(select(LabProgress).where(LabProgress.user_id == user_id))
    }
    data = _serialize_course(course)
    data["learnerName"] = user_id
    completed = sum(progress.get(lab["id"], False) for lab in course["labs"])
    data["completed"] = completed
    data["total"] = len(course["labs"])
    data["percent"] = round(completed / len(course["labs"]) * 100) if course["labs"] else 0
    data["labs"] = [
        {**lab, "completed": progress.get(lab["id"], False)} for lab in data["labs"]
    ]
    lab_ids = [lab["id"] for lab in course["labs"]]
    sessions = db.scalars(
        select(LabSession).where(
            LabSession.user_id == user_id,
            LabSession.lab_id.in_(lab_ids),
            LabSession.status.in_(["provisioning", "ready"]),
        )
        .order_by(LabSession.expires_at.desc())
    )
    data["sessions"] = [
        {
            "id": session.id,
            "labId": session.lab_id,
            "status": session.status,
            "expiresAt": _as_utc(session.expires_at).isoformat(),
        }
        for session in sessions
        if _as_utc(session.expires_at) > datetime.now(UTC)
    ]
    return data


@router.post("/sessions", status_code=201, response_model=None)
def create_session(
    request: SessionCreate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any] | JSONResponse:
    lab = get_lab(request.labId)
    settings = get_settings()
    now = datetime.now(UTC)

    if settings.app_env != "development":
        course = get_course(lab["course_id"])
        duration = _session_initial_minutes(course)
        try:
            with session_launch_lock(db):
                active = db.scalar(
                    select(LabSession)
                    .where(
                        LabSession.user_id == user_id,
                        LabSession.lab_id == lab["id"],
                        LabSession.status.in_(["queued", "provisioning", "ready"]),
                        LabSession.expires_at > now,
                    )
                    .order_by(LabSession.expires_at.desc())
                    .limit(1)
                )
                if active is not None:
                    return {
                        "id": active.id,
                        "labId": active.lab_id,
                        "status": active.status,
                        "expiresAt": _as_utc(active.expires_at).isoformat(),
                    }

                active_count, daily_hours = guardrail_snapshot(
                    db,
                    settings.azure_resource_group,
                    now,
                )
                committed_hours = daily_vm_hours_reserved(
                    db,
                    settings.azure_resource_group,
                    now,
                )
                next_session_end = min(
                    now + timedelta(minutes=settings.session_max_minutes),
                    refusal_day_start(now) + timedelta(days=1),
                )
                requested_reservation = max(
                    0.0,
                    (next_session_end - now).total_seconds() / 3600.0,
                )
                reason = (
                    "capacity"
                    if active_count >= settings.max_concurrent_vms
                    else "daily_budget"
                    if committed_hours + requested_reservation > settings.daily_vm_hours_cap
                    else None
                )
                if reason is not None:
                    details = {
                        "reason": reason,
                        "active_vms": active_count,
                        "daily_vm_hours": round(daily_hours, 4),
                        "daily_vm_hours_committed": round(committed_hours, 4),
                        "requested_vm_hours_reservation": round(requested_reservation, 4),
                        "max_concurrent_vms": settings.max_concurrent_vms,
                        "daily_vm_hours_cap": settings.daily_vm_hours_cap,
                        "timestamp": now.isoformat(),
                    }
                    db.add(
                        AuditLog(
                            user_id=user_id,
                            action="session.launch.refused",
                            details=json.dumps(details, sort_keys=True),
                            created_at=now,
                        )
                    )
                    db.commit()
                    return JSONResponse(status_code=429, content={"reason": reason})

                expires_at = now + timedelta(minutes=duration)
                session = LabSession(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    lab_id=lab["id"],
                    status="queued",
                    expires_at=expires_at,
                    max_expires_at=now + timedelta(minutes=settings.session_max_minutes),
                    resource_group=settings.azure_resource_group,
                    last_activity_at=now,
                    extension_count=0,
                )
                db.add(session)
                db.commit()
                db.refresh(session)
        except (SQLAlchemyError, RuntimeError) as exc:
            db.rollback()
            logger.exception("Session launch guardrail check failed; refusing launch.")
            try:
                db.add(
                    AuditLog(
                        user_id=user_id,
                        action="session.launch.guardrail_error",
                        details=json.dumps(
                            {"error": type(exc).__name__, "timestamp": now.isoformat()},
                            sort_keys=True,
                        ),
                        created_at=now,
                    )
                )
                db.commit()
            except SQLAlchemyError:
                db.rollback()
                logger.exception("Could not persist session launch guardrail error audit.")
            raise HTTPException(
                status_code=503,
                detail="Lab capacity could not be verified; launch was refused.",
            ) from exc

        try:
            default_queue.enqueue(
                "worker.jobs.provision_lab_session",
                session.id,
                job_timeout=900,
                retry=Retry(max=1, interval=[60]),
            )
        except Exception as exc:
            session.status = "failed"
            session.ended_at = datetime.now(UTC)
            db.commit()
            raise HTTPException(status_code=503, detail="Could not queue VM provisioning.") from exc
        return {
            "id": session.id,
            "labId": session.lab_id,
            "status": session.status,
            "expiresAt": _as_utc(session.expires_at).isoformat(),
        }

    active = db.scalar(
        select(LabSession)
        .where(
            LabSession.user_id == user_id,
            LabSession.lab_id == lab["id"],
            LabSession.status == "ready",
            LabSession.resource_group == "local-demo",
        )
        .order_by(LabSession.expires_at.desc())
        .limit(1)
    )
    if active is not None and _as_utc(active.expires_at) > now:
        return {
            "id": active.id,
            "labId": active.lab_id,
            "status": active.status,
            "expiresAt": _as_utc(active.expires_at).isoformat(),
        }

    session = LabSession(
        id=str(uuid.uuid4()),
        user_id=user_id,
        lab_id=lab["id"],
        status="ready",
        started_at=now,
        expires_at=now + timedelta(minutes=_session_initial_minutes(
            get_course(lab["course_id"])
        )),
        max_expires_at=now + timedelta(minutes=settings.session_max_minutes),
        last_activity_at=now,
        resource_group="local-demo",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "id": session.id,
        "labId": session.lab_id,
        "status": session.status,
        "expiresAt": _as_utc(session.expires_at).isoformat(),
    }


@router.get("/labs/{lab_id}/guide")
def lab_guide(
    lab_id: str,
    session_id: str | None = None,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    lab = get_lab(lab_id)
    content = get_guide_path(lab).read_text(encoding="utf-8")
    task_states: dict[int, bool] = {}
    if session_id:
        session = _session_for_user(db, session_id, user_id)
        if session.lab_id != lab_id:
            raise HTTPException(status_code=404, detail="Lab session not found.")
        if session.status in {"ending", "ended"} or _as_utc(session.expires_at) <= datetime.now(UTC):
            raise HTTPException(status_code=410, detail="The lab session has ended or expired.")
        resources = _session_resources(session)
        for key, value in resources.items():
            if value is not None:
                content = content.replace("{{" + key + "}}", str(value))
        task_states = {
            row.task_index: row.completed
            for row in db.scalars(
                select(TaskProgress).where(
                    TaskProgress.user_id == user_id,
                    TaskProgress.lab_id == lab_id,
                )
            )
        }
    else:
        task_states = {
            row.task_index: row.completed
            for row in db.scalars(
                select(TaskProgress).where(
                    TaskProgress.user_id == user_id,
                    TaskProgress.lab_id == lab_id,
                )
            )
        }
    return {
        "lab": {
            "id": lab["id"],
            "number": lab["number"],
            "title": lab["title"],
            "courseId": lab["course_id"],
            "courseTitle": lab["course_title"],
        },
        "content": content,
        "taskProgress": task_states,
        "completed": bool(
            (progress := _progress_row(db, user_id, lab_id)) and progress.completed
        ),
    }


@router.put("/labs/{lab_id}/tasks/{task_index}")
def update_task(
    lab_id: str,
    task_index: int,
    update: TaskUpdate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    lab = get_lab(lab_id)
    task_count = len(TASK_PATTERN.findall(get_guide_path(lab).read_text(encoding="utf-8")))
    if task_index < 0 or task_index >= task_count:
        raise HTTPException(status_code=404, detail="Lab task not found.")

    row = db.scalar(
        select(TaskProgress).where(
            TaskProgress.user_id == user_id,
            TaskProgress.lab_id == lab_id,
            TaskProgress.task_index == task_index,
        )
    )
    if row is None:
        row = TaskProgress(
            user_id=user_id,
            lab_id=lab_id,
            task_index=task_index,
            completed=update.completed,
            updated_at=datetime.now(UTC),
        )
        db.add(row)
    else:
        row.completed = update.completed
        row.updated_at = datetime.now(UTC)
    db.commit()
    return {"taskIndex": task_index, "completed": row.completed}


@router.post("/labs/{lab_id}/complete")
def complete_lab(
    lab_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    get_lab(lab_id)
    progress = _mark_complete(db, user_id, lab_id, "manual")
    return {"labId": lab_id, "completed": progress.completed, "method": progress.method}


@router.post("/labs/{lab_id}/validate")
def validate_lab(
    lab_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    lab = get_lab(lab_id)
    validation = lab.get("validation")
    if not validation or validation.get("type") != "vm":
        raise HTTPException(status_code=409, detail="This lab has no VM validation configured.")

    session = _session_for_user(db, session_id, user_id)
    if session.lab_id != lab_id or session.status != "ready":
        raise HTTPException(status_code=409, detail="A ready session for this lab is required.")
    if _as_utc(session.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=410, detail="The lab session has expired.")
    if not session.vm_name or not session.resource_group:
        raise HTTPException(status_code=409, detail="The session VM is not configured.")

    root = Path(lab["course_dir"]).resolve()
    script_path = (root / str(validation["script"])).resolve()
    if root not in script_path.parents or not script_path.is_file():
        raise HTTPException(status_code=500, detail="The lab validation script is missing.")
    settings = get_settings()
    if not settings.azure_subscription_id:
        raise HTTPException(status_code=503, detail="Azure validation is not configured.")

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    try:
        compute = ComputeManagementClient(credential, settings.azure_subscription_id)
        try:
            poller = compute.virtual_machines.begin_run_command(
                session.resource_group,
                session.vm_name,
                RunCommandInput(
                    command_id="RunPowerShellScript",
                    script=[script_path.read_text(encoding="utf-8")],
                ),
            )
            command_result = poller.result(timeout=600)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="The Azure VM validation command could not complete.",
            ) from exc
    finally:
        credential.close()

    message = "\n".join(item.message or "" for item in (command_result.value or []))
    result = _read_validation_output(message)
    checks = result["checks"]
    passed = (
        bool(result.get("passed"))
        and bool(checks)
        and all(isinstance(check, dict) and check.get("passed") is True for check in checks)
    )
    if passed:
        _mark_complete(db, user_id, lab_id, "validated")
    return {"labId": lab_id, "passed": passed, "checks": result["checks"]}


@router.get("/me/progress")
def my_progress(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    rows = {
        row.lab_id: row.completed
        for row in db.scalars(select(LabProgress).where(LabProgress.user_id == user_id))
    }
    courses = []
    for course in load_courses():
        completed = sum(rows.get(lab["id"], False) for lab in course["labs"])
        total = len(course["labs"])
        courses.append(
            {
                "courseId": course["id"],
                "courseTitle": course["title"],
                "completed": completed,
                "total": total,
                "percent": round(completed / total * 100) if total else 0,
            }
        )
    return {"courses": courses}


def _session_resources(session: LabSession) -> dict[str, str | None]:
    return {
        "vm.username": session.vm_username,
        "vm.password": (
            read_key_vault_secret(session.vm_password_secret_name)
            if session.vm_password_secret_name
            else None
        ),
        "azure.username": (
            read_key_vault_secret(session.azure_username_secret_name)
            if session.azure_username_secret_name
            else None
        ),
        "azure.password": (
            read_key_vault_secret(session.azure_password_secret_name)
            if session.azure_password_secret_name
            else None
        ),
        "azure.resourceGroup": session.azure_resource_group,
    }


@router.get("/sessions/{session_id}")
def session_detail(
    session_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    session = _session_for_user(db, session_id, user_id)
    lab = get_lab(session.lab_id)
    return {
        "id": session.id,
        "labId": session.lab_id,
        "labTitle": lab["title"],
        "courseId": lab["course_id"],
        "courseTitle": lab["course_title"],
        "status": session.status,
        "expiresAt": _as_utc(session.expires_at).isoformat(),
    }


@router.get("/sessions/{session_id}/resources")
def session_resources(
    session_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    session = _session_for_user(db, session_id, user_id)
    if session.status in {"ending", "ended"}:
        raise HTTPException(status_code=410, detail="The lab session has ended.")
    if _as_utc(session.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=410, detail="The lab session has expired.")
    resources = _session_resources(session)
    return {
        "vm": {"username": resources["vm.username"], "password": resources["vm.password"]},
        "azure": {
            "username": resources["azure.username"],
            "password": resources["azure.password"],
            "subscriptionId": session.azure_subscription_id,
            "resourceGroup": session.azure_resource_group,
        },
    }


@router.post("/sessions/{session_id}/connection-token")
def connection_token(
    session_id: str,
    read_only: bool = False,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
    role: str = Depends(get_current_user_role),
) -> dict[str, str]:
    if read_only:
        if role not in {"admin", "instructor"}:
            raise HTTPException(status_code=403, detail="Read-only shadow access is restricted.")
        session = db.scalar(select(LabSession).where(LabSession.id == session_id))
        if session is None:
            raise HTTPException(status_code=404, detail="Lab session not found.")
    else:
        session = _session_for_user(db, session_id, user_id)
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="The lab VM is not ready.")
    if _as_utc(session.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=410, detail="The lab session has expired.")
    if not session.vm_private_ip or not session.vm_username:
        raise HTTPException(status_code=409, detail="The lab VM connection is not configured.")

    settings = get_settings()
    if not settings.guac_crypt_key:
        raise HTTPException(status_code=503, detail="The remote desktop proxy is not configured.")
    password = read_key_vault_secret(session.vm_password_secret_name)
    session.last_activity_at = datetime.now(UTC)
    db.commit()
    token, expires_at = build_connection_token(
        session_id=session.id,
        host=session.vm_private_ip,
        username=session.vm_username,
        password=password,
        key=settings.guac_crypt_key,
        read_only=read_only,
    )
    return {
        "token": token,
        "wsUrl": settings.guac_ws_url,
        "expiresAt": expires_at.isoformat(),
    }


@router.post("/sessions/{session_id}/activity", status_code=204)
def record_session_activity(
    session_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> None:
    session = _session_for_user(db, session_id, user_id)
    if session.status == "ready":
        session.last_activity_at = datetime.now(UTC)
        db.commit()


@router.post("/sessions/{session_id}/extend")
def extend_session(
    session_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, str]:
    session = _session_for_user(db, session_id, user_id, for_update=True)
    now = datetime.now(UTC)
    if session.status != "ready" or _as_utc(session.expires_at) <= now:
        raise HTTPException(status_code=409, detail="Only an active session can be extended.")
    new_expiry = _extend_ready_session(session)
    db.commit()
    return {"expiresAt": new_expiry.isoformat()}


@router.post("/sessions/{session_id}/end", status_code=202)
def end_session(
    session_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, str]:
    session = _session_for_user(db, session_id, user_id)
    if session.status == "ended":
        return {"sessionId": session.id, "status": "ended"}
    if session.status == "ending":
        return {"sessionId": session.id, "status": "ending"}
    if session.resource_group == "local-demo":
        session.status = "ended"
        session.ended_at = datetime.now(UTC)
        db.commit()
        return {"sessionId": session.id, "status": "ended"}
    if not session.resource_group:
        raise HTTPException(status_code=409, detail="Session resource group is not configured.")
    session.status = "ending"
    db.commit()
    try:
        default_queue.enqueue(
            cleanup_lab_session,
            session.id,
            job_timeout=900,
            retry=Retry(max=3, interval=[30, 60, 120]),
        )
    except Exception as exc:
        session.status = "ready"
        db.commit()
        raise HTTPException(status_code=503, detail="Could not queue session cleanup.") from exc
    return {"sessionId": session.id, "status": "ending"}


class CourseUpdate(BaseModel):
    title: str
    slug: str | None = None
    description: str = ""
    imageDefinition: str | None = None
    imageVersion: str | None = None
    vmSize: str = "Standard_B2s"
    sessionMinutes: int = 180
    poolSize: int = 0
    needsAzureSandbox: bool = False


class LearnerCreate(BaseModel):
    email: str
    name: str
    role: str = "learner"
    courseSlug: str | None = None
    expiresAt: datetime | None = None


def _require_admin_or_instructor(role: str) -> None:
        if role not in {"admin", "instructor"}:
            raise HTTPException(status_code=403, detail="Instructor or admin access is required.")


def _audit(db: Session, user_id: str, action: str, details: dict[str, Any]) -> None:
        db.add(AuditLog(user_id=user_id, action=action, details=json.dumps(details)))
        db.commit()


@router.get("/admin/courses")
def admin_courses(
        db: Session = Depends(get_db),
        role: str = Depends(get_current_user_role),
) -> dict[str, Any]:
        _require_admin_or_instructor(role)
        rows = db.scalars(select(Course).order_by(Course.title)).all()
        return {
            "courses": [
                {
                    "id": row.id,
                    "slug": row.slug,
                    "title": row.title,
                    "description": row.description,
                    "imageDefinition": row.image_definition,
                    "imageVersion": row.image_version,
                    "vmSize": row.vm_size,
                    "sessionMinutes": row.session_minutes,
                    "poolSize": row.pool_size,
                    "needsAzureSandbox": row.needs_azure_sandbox,
                }
                for row in rows
            ]
        }


@router.post("/admin/courses", status_code=201)
def admin_create_course(
        update: CourseUpdate,
        db: Session = Depends(get_db),
        user_id: str = Depends(get_current_user_id),
        role: str = Depends(get_current_user_role),
) -> dict[str, Any]:
        _require_admin_or_instructor(role)
        slug = update.slug or re.sub(r"[^a-z0-9]+", "-", update.title.lower()).strip("-")
        existing = db.scalar(select(Course).where(Course.slug == slug))
        if existing:
            raise HTTPException(status_code=409, detail="A course with that slug already exists.")
        course = Course(
            id=str(uuid.uuid4()),
            slug=slug,
            title=update.title,
            description=update.description,
            image_definition=update.imageDefinition,
            image_version=update.imageVersion,
            vm_size=update.vmSize,
            session_minutes=max(15, update.sessionMinutes),
            pool_size=max(0, update.poolSize),
            needs_azure_sandbox=update.needsAzureSandbox,
        )
        db.add(course)
        db.commit()
        db.refresh(course)
        _audit(db, user_id, "course.create", {"course_id": course.id, "slug": course.slug})
        return {"id": course.id, "slug": course.slug, "title": course.title}


@router.patch("/admin/courses/{course_id}")
def admin_update_course(
        course_id: str,
        update: CourseUpdate,
        db: Session = Depends(get_db),
        user_id: str = Depends(get_current_user_id),
        role: str = Depends(get_current_user_role),
) -> dict[str, Any]:
        _require_admin_or_instructor(role)
        course = db.scalar(select(Course).where(Course.id == course_id))
        if course is None:
            raise HTTPException(status_code=404, detail="Course not found.")
        course.title = update.title
        course.slug = update.slug or course.slug
        course.description = update.description
        course.image_definition = update.imageDefinition
        course.image_version = update.imageVersion
        course.vm_size = update.vmSize
        course.session_minutes = max(15, update.sessionMinutes)
        course.pool_size = max(0, update.poolSize)
        course.needs_azure_sandbox = update.needsAzureSandbox
        db.commit()
        _audit(db, user_id, "course.update", {"course_id": course.id})
        return {"id": course.id, "slug": course.slug, "title": course.title}


@router.get("/admin/learners")
def admin_learners(
        db: Session = Depends(get_db),
        role: str = Depends(get_current_user_role),
) -> dict[str, Any]:
        _require_admin_or_instructor(role)
        rows = db.scalars(select(LabUser).order_by(LabUser.created_at.desc())).all()
        return {
            "learners": [
                {"id": row.id, "email": row.email, "name": row.name, "role": row.role}
                for row in rows
            ]
        }


@router.post("/admin/learners", status_code=201)
def admin_add_learner(
        learner: LearnerCreate,
        db: Session = Depends(get_db),
        user_id: str = Depends(get_current_user_id),
        role: str = Depends(get_current_user_role),
) -> dict[str, Any]:
        _require_admin_or_instructor(role)
        if learner.role not in {"learner", "instructor", "admin"}:
            raise HTTPException(status_code=422, detail="Invalid role.")
        existing = db.scalar(select(LabUser).where(LabUser.email == learner.email))
        if existing:
            raise HTTPException(status_code=409, detail="A learner with that email already exists.")
        row = LabUser(id=str(uuid.uuid4()), email=learner.email, name=learner.name, role=learner.role)
        db.add(row)
        db.flush()
        if learner.courseSlug:
            course = db.scalar(select(Course).where(Course.slug == learner.courseSlug))
            if course is None:
                raise HTTPException(status_code=404, detail="Course not found.")
            db.add(Enrollment(
                user_id=row.id,
                course_id=course.id,
                expires_at=learner.expiresAt,
            ))
        db.commit()
        _audit(db, user_id, "learner.create", {"learner_id": row.id, "email": row.email})
        return {"id": row.id, "email": row.email, "name": row.name, "role": row.role}


@router.post("/admin/learners/import")
async def admin_import_learners(
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        user_id: str = Depends(get_current_user_id),
        role: str = Depends(get_current_user_role),
) -> dict[str, Any]:
        _require_admin_or_instructor(role)
        content = (await file.read()).decode("utf-8-sig")
        imported = 0
        for row in csv.DictReader(io.StringIO(content)):
            email = (row.get("email") or "").strip()
            name = (row.get("name") or "").strip()
            course_slug = (row.get("course_slug") or "").strip()
            if not email:
                continue
            existing = db.scalar(select(LabUser).where(LabUser.email == email))
            if existing is None:
                learner = LabUser(id=str(uuid.uuid4()), email=email, name=name or email, role="learner")
                db.add(learner)
                db.flush()
                imported += 1
            else:
                learner = existing
            if course_slug:
                course = db.scalar(select(Course).where(Course.slug == course_slug))
                if course is not None:
                    enrollment = db.scalar(select(Enrollment).where(
                        Enrollment.user_id == learner.id,
                        Enrollment.course_id == course.id,
                    ))
                    if enrollment is None:
                        db.add(Enrollment(user_id=learner.id, course_id=course.id))
        db.commit()
        _audit(db, user_id, "learner.import", {"imported": imported, "filename": file.filename})
        return {"imported": imported}


@router.get("/admin/sessions")
def admin_live_sessions(
        db: Session = Depends(get_db),
        role: str = Depends(get_current_user_role),
) -> dict[str, Any]:
        _require_admin_or_instructor(role)
        now = datetime.now(UTC)
        rows = db.scalars(
            select(LabSession)
            .where(LabSession.status.in_(["queued", "provisioning", "ready", "ending"]))
            .order_by(LabSession.expires_at.asc())
        ).all()
        sessions = []
        for row in rows:
            lab = get_lab(row.lab_id)
            seconds = max(0, int((_as_utc(row.expires_at) - now).total_seconds()))
            sessions.append({
                "id": row.id,
                "userId": row.user_id,
                "courseId": lab["course_id"],
                "labId": row.lab_id,
                "labTitle": lab["title"],
                "status": row.status,
                "timeLeftSeconds": seconds,
            })
        return {"sessions": sessions}


@router.get("/admin/guardrails")
def admin_guardrail_metrics(
    db: Session = Depends(get_db),
    role: str = Depends(get_current_user_role),
) -> dict[str, Any]:
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    settings = get_settings()
    now = datetime.now(UTC)
    day_start = refusal_day_start(now)
    try:
        active_count, daily_hours = guardrail_snapshot(
            db,
            settings.azure_resource_group,
            now,
        )
        committed_hours = daily_vm_hours_reserved(
            db,
            settings.azure_resource_group,
            now,
        )
        refusal_count = int(
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "session.launch.refused",
                    AuditLog.created_at >= day_start,
                    AuditLog.created_at < day_start + timedelta(days=1),
                )
            )
            or 0
        )
    except SQLAlchemyError as exc:
        logger.exception("Could not load staging guardrail metrics.")
        raise HTTPException(
            status_code=503,
            detail="Guardrail metrics are temporarily unavailable.",
        ) from exc
    return {
        "dailyVmHoursUsed": round(daily_hours, 4),
        "dailyVmHoursCommitted": round(committed_hours, 4),
        "dailyVmHoursCap": settings.daily_vm_hours_cap,
        "activeVms": active_count,
        "maxConcurrentVms": settings.max_concurrent_vms,
        "refusedLaunchesToday": refusal_count,
        "values": {
            "sessionMaxMinutes": settings.session_max_minutes,
            "maxExtensions": settings.max_extensions,
            "idleTimeoutMinutes": settings.idle_timeout_minutes,
            "allowedVmSizes": sorted(settings.allowed_vm_size_set),
            "warmPoolSize": settings.warm_pool_size,
            "vmAutoshutdownTime": settings.vm_autoshutdown_time,
            "vmAutoshutdownTimezone": settings.vm_autoshutdown_tz,
        },
    }


@router.post("/admin/sessions/{session_id}/extend")
def admin_extend_session(
        session_id: str,
        db: Session = Depends(get_db),
        user_id: str = Depends(get_current_user_id),
        role: str = Depends(get_current_user_role),
) -> dict[str, Any]:
        _require_admin_or_instructor(role)
        session = db.scalar(
            select(LabSession)
            .where(LabSession.id == session_id)
            .with_for_update()
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        new_expiry = _extend_ready_session(session)
        db.commit()
        _audit(db, user_id, "session.extend", {"session_id": session.id})
        return {"expiresAt": new_expiry.isoformat()}


@router.post("/admin/sessions/{session_id}/end", status_code=202)
def admin_end_session(
        session_id: str,
        db: Session = Depends(get_db),
        user_id: str = Depends(get_current_user_id),
        role: str = Depends(get_current_user_role),
) -> dict[str, Any]:
        _require_admin_or_instructor(role)
        session = db.scalar(select(LabSession).where(LabSession.id == session_id))
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        if session.status in {"ended", "ending"}:
            return {"sessionId": session_id, "status": session.status}
        session.status = "ending"
        db.commit()
        try:
            default_queue.enqueue(cleanup_lab_session, session.id, job_timeout=900, retry=Retry(max=3, interval=[30, 60, 120]))
        except Exception as exc:
            session.status = "ready"
            db.commit()
            raise HTTPException(status_code=503, detail="Could not queue session cleanup.") from exc
        _audit(db, user_id, "session.end", {"session_id": session.id})
        return {"sessionId": session.id, "status": "ending"}


@router.get("/admin/reports/{course_id}.csv")
def admin_course_report_csv(
    course_id: str,
    db: Session = Depends(get_db),
    role: str = Depends(get_current_user_role),
) -> Response:
    _require_admin_or_instructor(role)
    course = get_course(course_id)
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["learner_id"] + [lab["title"] for lab in course["labs"]] + ["percent"]
    writer.writerow(headers)
    learner_ids = sorted({
        row.user_id
        for row in db.scalars(select(LabProgress).where(
            LabProgress.lab_id.in_([lab["id"] for lab in course["labs"]])
        ))
    })
    for learner_id in learner_ids:
        completed = {
            row.lab_id
            for row in db.scalars(select(LabProgress).where(
                LabProgress.user_id == learner_id,
                LabProgress.completed.is_(True),
            ))
        }
        ticks = ["completed" if lab["id"] in completed else "" for lab in course["labs"]]
        percent = round(
            len([lab for lab in course["labs"] if lab["id"] in completed])
            / len(course["labs"])
            * 100
        ) if course["labs"] else 0
        writer.writerow([learner_id, *ticks, percent])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{course_id}-progress.csv"'},
    )
