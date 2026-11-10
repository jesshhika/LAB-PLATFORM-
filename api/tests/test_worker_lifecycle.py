from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app.core.config import Settings
from api.app.core.db import Base
from api.app.models import LabSession
from worker import __main__ as worker_main
from worker.jobs import cleanup_lab_session


def test_idle_timeout_marks_session_ending_and_queues_normal_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    now = datetime.now(UTC)
    with factory() as db:
        db.add(
            LabSession(
                id="idle-session",
                user_id="learner",
                lab_id="foundry-lab-01",
                status="ready",
                started_at=now - timedelta(minutes=45),
                last_activity_at=now - timedelta(minutes=21),
                expires_at=now + timedelta(minutes=60),
                max_expires_at=now + timedelta(minutes=120),
                resource_group="rg-labforge-labvms",
            )
        )
        db.commit()

    enqueued: list[tuple[object, str]] = []
    sleep_calls = 0

    class StopLoop(Exception):
        pass

    def stop_after_one_iteration(_: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 2:
            raise StopLoop

    monkeypatch.setattr(worker_main, "SessionLocal", factory)
    monkeypatch.setattr(
        worker_main,
        "get_settings",
        lambda: Settings(idle_timeout_minutes=20),
    )
    monkeypatch.setattr(worker_main, "maintain_warm_pool", lambda: 0)
    monkeypatch.setattr(worker_main.time, "sleep", stop_after_one_iteration)
    monkeypatch.setattr(
        worker_main.default_queue,
        "enqueue",
        lambda job, session_id, **kwargs: enqueued.append((job, session_id)),
    )

    try:
        with pytest.raises(StopLoop):
            worker_main._session_safety_loop()
        with factory() as db:
            session = db.scalar(
                select(LabSession).where(LabSession.id == "idle-session")
            )
            assert session is not None
            assert session.status == "ending"
        assert enqueued == [(cleanup_lab_session, "idle-session")]
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
