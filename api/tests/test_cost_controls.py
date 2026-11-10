from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from api.app.core.config import Settings
from api.app.core.db import Base
from api.app.cost_controls import (
    count_active_vms,
    daily_vm_hours,
    daily_vm_hours_reserved,
    initial_session_minutes,
    ist_day_bounds,
)
from api.app.models import LabSession


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def _session(
    *,
    session_id: str,
    status: str,
    resource_group: str = "rg-labforge-labvms",
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> LabSession:
    return LabSession(
        id=session_id,
        user_id=f"user-{session_id}",
        lab_id="foundry-lab-01",
        status=status,
        expires_at=datetime(2026, 1, 2, tzinfo=UTC),
        resource_group=resource_group,
        started_at=started_at,
        ended_at=ended_at,
    )


def test_daily_vm_hours_counts_running_sessions_across_ist_midnight(db_session: Session) -> None:
    now = datetime(2026, 1, 1, 2, 0, tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(UTC)
    db_session.add_all(
        [
            _session(
                session_id="running",
                status="ready",
                started_at=datetime(2025, 12, 31, 17, 30, tzinfo=UTC),
            ),
            _session(
                session_id="ended",
                status="ended",
                started_at=datetime(2025, 12, 31, 19, 0, tzinfo=UTC),
                ended_at=datetime(2025, 12, 31, 19, 30, tzinfo=UTC),
            ),
            _session(
                session_id="wrong-group",
                status="ended",
                resource_group="local-demo",
                started_at=datetime(2025, 12, 31, 19, 0, tzinfo=UTC),
                ended_at=datetime(2025, 12, 31, 20, 0, tzinfo=UTC),
            ),
        ]
    )
    db_session.commit()

    assert daily_vm_hours(db_session, "rg-labforge-labvms", now) == pytest.approx(2.5)


def test_ist_day_bounds_are_midnight_to_midnight() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    start, end = ist_day_bounds(now)

    assert start == datetime(2025, 12, 31, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 1, 1, 18, 30, tzinfo=UTC)


def test_daily_vm_hours_reserved_includes_active_and_queued_session_maximums(
    db_session: Session,
) -> None:
    now = datetime(2026, 1, 1, 2, 0, tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(UTC)
    db_session.add_all(
        [
            LabSession(
                id="active-reservation",
                user_id="active-user",
                lab_id="foundry-lab-01",
                status="ready",
                expires_at=now + timedelta(minutes=45),
                started_at=now - timedelta(minutes=30),
                max_expires_at=now + timedelta(minutes=90),
                resource_group="rg-labforge-labvms",
            ),
            LabSession(
                id="queued-reservation",
                user_id="queued-user",
                lab_id="foundry-lab-01",
                status="queued",
                expires_at=now + timedelta(minutes=45),
                max_expires_at=now + timedelta(minutes=60),
                resource_group="rg-labforge-labvms",
            ),
        ]
    )
    db_session.commit()

    assert daily_vm_hours_reserved(
        db_session,
        "rg-labforge-labvms",
        now,
    ) == pytest.approx(3.0)


def test_active_vm_count_includes_ending_sessions_only_for_vm_resource_group(
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            _session(session_id="ending", status="ending"),
            _session(session_id="failed", status="failed"),
            _session(session_id="local", status="ready", resource_group="local-demo"),
        ]
    )
    db_session.commit()

    assert count_active_vms(db_session, "rg-labforge-labvms") == 1


@pytest.mark.parametrize(
    ("course_minutes", "max_extensions", "expected"),
    [(180, 1, 105), (60, 1, 60), (180, 0, 120)],
)
def test_initial_session_reserves_extension_time(
    course_minutes: int,
    max_extensions: int,
    expected: int,
) -> None:
    assert initial_session_minutes(course_minutes, 120, 15, max_extensions) == expected


def test_settings_reject_invalid_guardrail_values() -> None:
    with pytest.raises(ValueError):
        Settings(allowed_vm_sizes="Standard_B2s,,Standard_D2s_v5")
    with pytest.raises(ValueError):
        Settings(max_concurrent_vms=0)
    with pytest.raises(ValueError):
        Settings(vm_autoshutdown_time="2460")
