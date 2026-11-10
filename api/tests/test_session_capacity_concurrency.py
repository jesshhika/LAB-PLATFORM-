import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from api.app.core.config import Settings
from api.app.core.db import Base
from api.app.models import LabSession
from api.app.routes import SessionCreate, create_session

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="Set TEST_DATABASE_URL to run PostgreSQL advisory-lock concurrency coverage.",
)


def test_parallel_launches_respect_the_last_vm_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL, pool_size=5)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    from api.app import routes

    settings = Settings(
        app_env="staging",
        azure_resource_group="rg-labforge-labvms",
        max_concurrent_vms=1,
        daily_vm_hours_cap=8,
    )
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes.default_queue, "enqueue", lambda *args, **kwargs: None)
    barrier = Barrier(2)

    def launch(user_id: str) -> dict | JSONResponse:
        barrier.wait()
        with factory() as db:
            return create_session(
                SessionCreate(labId="foundry-lab-01"),
                db,
                user_id,
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(launch, ("learner-a", "learner-b")))
        created = [result for result in results if isinstance(result, dict)]
        refused = [result for result in results if isinstance(result, JSONResponse)]

        assert len(created) == 1
        assert len(refused) == 1
        assert refused[0].status_code == 429
        assert refused[0].body == b'{"reason":"capacity"}'
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(LabSession)) == 1
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
