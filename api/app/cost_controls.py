from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta
from threading import RLock
from typing import Iterator
from zoneinfo import ZoneInfo

from sqlalchemy import case, extract, func, select, text
from sqlalchemy.orm import Session

from api.app.models import LabSession

IST = ZoneInfo("Asia/Kolkata")
ACTIVE_VM_STATUSES = ("queued", "provisioning", "ready", "ending")
_LAUNCH_LOCK_KEY = 5_495_040_886_561_442_119
_SQLITE_LAUNCH_LOCK = RLock()


def ist_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    local_now = now.astimezone(IST)
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=IST)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


@contextmanager
def session_launch_lock(db: Session) -> Iterator[None]:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _LAUNCH_LOCK_KEY},
        )
        yield
        return
    if dialect == "sqlite":
        with _SQLITE_LAUNCH_LOCK:
            yield
        return
    raise RuntimeError(f"Session launch locking is not supported for {dialect}.")


def count_active_vms(db: Session, resource_group: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(LabSession)
            .where(
                LabSession.resource_group == resource_group,
                LabSession.status.in_(ACTIVE_VM_STATUSES),
            )
        )
        or 0
    )


def daily_vm_hours(db: Session, resource_group: str, now: datetime) -> float:
    day_start, day_end = ist_day_bounds(now)
    session_end = case(
        (LabSession.ended_at.is_(None), now),
        else_=LabSession.ended_at,
    )
    overlap_start = case(
        (LabSession.started_at < day_start, day_start),
        else_=LabSession.started_at,
    )
    overlap_end = case(
        (session_end > day_end, day_end),
        else_=session_end,
    )
    overlap = (
        select(
            LabSession.started_at,
            LabSession.ended_at,
            overlap_start.label("overlap_start"),
            overlap_end.label("overlap_end"),
        )
        .where(
            LabSession.resource_group == resource_group,
            LabSession.started_at.is_not(None),
            LabSession.started_at < day_end,
            session_end > day_start,
        )
        .subquery()
    )

    if db.get_bind().dialect.name == "postgresql":
        hours = extract("epoch", overlap.c.overlap_end - overlap.c.overlap_start) / 3600.0
    else:
        hours = (
            func.julianday(overlap.c.overlap_end)
            - func.julianday(overlap.c.overlap_start)
        ) * 24.0

    return float(
        db.scalar(select(func.coalesce(func.sum(hours), 0.0)).select_from(overlap))
        or 0.0
    )


def daily_vm_hours_reserved(db: Session, resource_group: str, now: datetime) -> float:
    committed_hours = daily_vm_hours(db, resource_group, now)
    _, day_end = ist_day_bounds(now)
    active_sessions = db.execute(
        select(LabSession.max_expires_at, LabSession.expires_at).where(
            LabSession.resource_group == resource_group,
            LabSession.status.in_(ACTIVE_VM_STATUSES),
        )
    )
    for max_expires_at, expires_at in active_sessions:
        reservation_end = max_expires_at or expires_at
        if reservation_end is None:
            continue
        if reservation_end.tzinfo is None:
            reservation_end = reservation_end.replace(tzinfo=UTC)
        else:
            reservation_end = reservation_end.astimezone(UTC)
        reserved_until = min(reservation_end, day_end)
        if reserved_until > now:
            committed_hours += (reserved_until - now).total_seconds() / 3600.0
    return committed_hours


def guardrail_snapshot(
    db: Session,
    resource_group: str,
    now: datetime,
) -> tuple[int, float]:
    return (
        count_active_vms(db, resource_group),
        daily_vm_hours(db, resource_group, now),
    )


def refusal_day_start(now: datetime) -> datetime:
    return ist_day_bounds(now)[0]


def initial_session_minutes(
    course_minutes: int,
    session_max_minutes: int,
    extension_minutes: int,
    max_extensions: int,
) -> int:
    initial_limit = max(
        1,
        session_max_minutes - extension_minutes * max_extensions,
    )
    return min(max(1, course_minutes), initial_limit)
