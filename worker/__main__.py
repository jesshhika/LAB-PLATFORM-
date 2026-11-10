import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from rq import Retry, Worker
from sqlalchemy import select

from api.app.core.config import get_settings
from api.app.core.db import SessionLocal
from api.app.core.queue import default_queue, redis_connection
from api.app.models import LabSession
from worker.jobs import (
    cleanup_lab_session,
    maintain_warm_pool,
    reap_orphaned_lab_resources,
)

logger = logging.getLogger(__name__)


def _session_safety_loop() -> None:
    while True:
        time.sleep(60)
        maintain_warm_pool()
        with SessionLocal() as db:
            expired = db.scalars(
                select(LabSession).where(
                    LabSession.status.in_(["queued", "ready", "provisioning"]),
                    LabSession.expires_at <= datetime.now(UTC),
                )
            )
            for session in expired:
                if session.resource_group == "local-demo":
                    session.status = "ended"
                    session.ended_at = datetime.now(UTC)
                    db.commit()
                    continue
                session.status = "ending"
                db.commit()
                try:
                    default_queue.enqueue(
                        cleanup_lab_session,
                        session.id,
                        job_timeout=900,
                        retry=Retry(max=3, interval=[30, 60, 120]),
                    )
                except Exception:
                    logger.exception("Could not queue expired session cleanup for %s.", session.id)
                    session.status = "ready"
                    db.commit()
            idle_sessions = db.scalars(
                select(LabSession).where(LabSession.status == "ready")
            )
            settings = get_settings()
            for session in idle_sessions:
                if session.resource_group == "local-demo":
                    continue
                last_activity = session.last_activity_at or session.started_at
                if last_activity is None:
                    logger.error(
                        "Skipping idle timeout for session %s without an activity or start time.",
                        session.id,
                    )
                    continue
                if last_activity.tzinfo is None:
                    last_activity = last_activity.replace(tzinfo=UTC)
                if datetime.now(UTC) - last_activity.astimezone(UTC) < timedelta(
                    minutes=settings.idle_timeout_minutes
                ):
                    continue
                session.status = "ending"
                db.commit()
                try:
                    default_queue.enqueue(
                        cleanup_lab_session,
                        session.id,
                        job_timeout=900,
                        retry=Retry(max=3, interval=[30, 60, 120]),
                    )
                except Exception:
                    logger.exception("Could not queue idle session cleanup for %s.", session.id)
                    session.status = "ready"
                    db.commit()


def _reaper_loop() -> None:
    while True:
        time.sleep(600)
        try:
            reap_orphaned_lab_resources()
        except Exception:
            logger.exception("The worker VM reaper failed.")


if __name__ == "__main__":
    threading.Thread(target=_session_safety_loop, daemon=True).start()
    threading.Thread(target=_reaper_loop, daemon=True).start()
    Worker([default_queue], connection=redis_connection).work()
