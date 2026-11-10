import base64
import json
from datetime import UTC, datetime, timedelta, tzinfo
from types import ModuleType

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app.auth import get_current_user_id, get_current_user_role
from api.app.core.config import Settings
from api.app.core.db import Base, get_db
from api.app.main import app
from api.app.models import AuditLog, LabSession
from api.app.services import (
    build_connection_token,
    encrypt_guac_token,
    require_private_ip,
)


def _freeze_route_clock(
    monkeypatch: pytest.MonkeyPatch,
    routes_module: ModuleType,
    now: datetime,
) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(routes_module, "datetime", FrozenDateTime)


@pytest.fixture
def test_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield test_session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(test_session_factory):
    def override_db():
        with test_session() as db:
            yield db

    test_session = test_session_factory
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user_id] = lambda: "test-learner"
    app.dependency_overrides[get_current_user_role] = lambda: "admin"
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_manual_completion_is_idempotent_and_progress_is_persisted(client: TestClient) -> None:
    first = client.post("/api/labs/foundry-lab-01/complete")
    second = client.post("/api/labs/foundry-lab-01/complete")

    assert first.status_code == 200
    assert first.json()["method"] == "manual"
    assert second.json()["completed"] is True
    progress = client.get("/api/me/progress").json()["courses"][0]
    assert (progress["completed"], progress["total"], progress["percent"]) == (1, 5, 20)


def test_progress_percent_is_zero_then_one_hundred(client: TestClient) -> None:
    initial = client.get("/api/me/progress").json()["courses"][0]
    assert (initial["completed"], initial["total"], initial["percent"]) == (0, 5, 0)

    for lab_number in range(1, 6):
        response = client.post(f"/api/labs/foundry-lab-{lab_number:02d}/complete")
        assert response.status_code == 200

    completed = client.get("/api/me/progress").json()["courses"][0]
    assert (completed["completed"], completed["total"], completed["percent"]) == (5, 5, 100)


def test_task_progress_rejects_task_outside_guide(client: TestClient) -> None:
    response = client.put(
        "/api/labs/foundry-lab-01/tasks/100",
        json={"completed": True},
    )

    assert response.status_code == 404


def test_course_guide_has_paginated_content_and_tasks(client: TestClient) -> None:
    response = client.get("/api/labs/foundry-lab-01/guide")

    assert response.status_code == 200
    assert "---page---" in response.json()["content"]
    assert response.json()["lab"]["title"] == "Prepare your Foundry development environment"


def test_course_detail_includes_learner_and_progress(client: TestClient) -> None:
    response = client.get("/api/courses/foundry")

    assert response.status_code == 200
    assert response.json()["learnerName"] == "test-learner"
    assert (response.json()["completed"], response.json()["percent"]) == (0, 0)


def test_local_demo_session_launch_is_idempotent(client: TestClient) -> None:
    first = client.post("/api/sessions", json={"labId": "foundry-lab-01"})
    second = client.post("/api/sessions", json={"labId": "foundry-lab-01"})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "ready"
    assert client.get(f"/api/sessions/{first.json()['id']}").status_code == 200
    ended = client.post(f"/api/sessions/{first.json()['id']}/end")
    assert ended.status_code == 202
    assert ended.json()["status"] == "ended"


def test_cloud_launch_refusal_returns_capacity_reason_and_audits(
    client: TestClient,
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.app import routes

    settings = Settings(
        app_env="staging",
        azure_resource_group="rg-labforge-labvms",
        max_concurrent_vms=1,
        daily_vm_hours_cap=8,
    )
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(
        routes.default_queue,
        "enqueue",
        lambda *args, **kwargs: pytest.fail("A refused launch must not be queued."),
    )
    now = datetime.now(UTC)
    with test_session_factory() as db:
        db.add(
            LabSession(
                id="active-cap-session",
                user_id="another-learner",
                lab_id="foundry-lab-01",
                status="ending",
                expires_at=now + timedelta(minutes=30),
                resource_group="rg-labforge-labvms",
                started_at=now - timedelta(minutes=10),
            )
        )
        db.commit()

    response = client.post("/api/sessions", json={"labId": "foundry-lab-01"})

    assert response.status_code == 429
    assert response.json() == {"reason": "capacity"}
    with test_session_factory() as db:
        audit = db.query(AuditLog).filter_by(action="session.launch.refused").one()
        details = json.loads(audit.details)
        assert details["reason"] == "capacity"
        assert details["active_vms"] == 1
        assert db.query(LabSession).count() == 1


def test_cloud_launch_daily_budget_includes_ended_hours(
    client: TestClient,
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.app import routes

    settings = Settings(
        app_env="staging",
        azure_resource_group="rg-labforge-labvms",
        max_concurrent_vms=2,
        daily_vm_hours_cap=8,
    )
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(
        routes.default_queue,
        "enqueue",
        lambda *args, **kwargs: pytest.fail("A refused launch must not be queued."),
    )
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    _freeze_route_clock(monkeypatch, routes, now)
    with test_session_factory() as db:
        db.add(
            LabSession(
                id="daily-budget-session",
                user_id="another-learner",
                lab_id="foundry-lab-01",
                status="ended",
                expires_at=now,
                resource_group="rg-labforge-labvms",
                started_at=now - timedelta(hours=8),
                ended_at=now,
            )
        )
        db.commit()

    response = client.post("/api/sessions", json={"labId": "foundry-lab-01"})

    assert response.status_code == 429
    assert response.json() == {"reason": "daily_budget"}
    with test_session_factory() as db:
        audit = db.query(AuditLog).filter_by(action="session.launch.refused").one()
        assert json.loads(audit.details)["daily_vm_hours"] == pytest.approx(8.0, abs=0.01)


def test_cloud_launch_reserves_daily_hours_for_existing_and_new_sessions(
    client: TestClient,
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.app import routes

    settings = Settings(
        app_env="staging",
        azure_resource_group="rg-labforge-labvms",
        max_concurrent_vms=2,
        daily_vm_hours_cap=3,
        session_max_minutes=120,
    )
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(
        routes.default_queue,
        "enqueue",
        lambda *args, **kwargs: pytest.fail("A refused launch must not be queued."),
    )
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    _freeze_route_clock(monkeypatch, routes, now)
    with test_session_factory() as db:
        db.add(
            LabSession(
                id="active-reservation-session",
                user_id="another-learner",
                lab_id="foundry-lab-01",
                status="ready",
                expires_at=now + timedelta(minutes=60),
                started_at=now - timedelta(hours=1),
                max_expires_at=now + timedelta(hours=1),
                resource_group="rg-labforge-labvms",
            )
        )
        db.commit()

    response = client.post("/api/sessions", json={"labId": "foundry-lab-01"})

    assert response.status_code == 429
    assert response.json() == {"reason": "daily_budget"}
    with test_session_factory() as db:
        audit = db.query(AuditLog).filter_by(action="session.launch.refused").one()
        details = json.loads(audit.details)
        assert details["daily_vm_hours"] == pytest.approx(1.0, abs=0.01)
        assert details["daily_vm_hours_committed"] == pytest.approx(2.0, abs=0.01)
        assert details["requested_vm_hours_reservation"] == pytest.approx(2.0, abs=0.01)


def test_cloud_launch_fails_closed_when_guardrail_query_fails(
    client: TestClient,
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from api.app import routes

    settings = Settings(app_env="staging")
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(
        routes,
        "guardrail_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("query failed")),
    )
    monkeypatch.setattr(
        routes.default_queue,
        "enqueue",
        lambda *args, **kwargs: pytest.fail("A launch with unknown capacity must not be queued."),
    )

    response = client.post("/api/sessions", json={"labId": "foundry-lab-01"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Lab capacity could not be verified; launch was refused."
    with test_session_factory() as db:
        assert db.query(LabSession).count() == 0
        assert db.query(AuditLog).filter_by(action="session.launch.guardrail_error").count() == 1


def test_extensions_are_limited_and_respect_total_session_lifetime(
    client: TestClient,
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.app import routes

    settings = Settings(
        session_max_minutes=120,
        max_extensions=1,
        session_extension_minutes=15,
    )
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    started_at = datetime.now(UTC) - timedelta(minutes=100)
    with test_session_factory() as db:
        db.add(
            LabSession(
                id="extension-session",
                user_id="test-learner",
                lab_id="foundry-lab-01",
                status="ready",
                started_at=started_at,
                expires_at=started_at + timedelta(minutes=105),
                max_expires_at=started_at + timedelta(minutes=120),
                resource_group="local-demo",
                extension_count=0,
            )
        )
        db.commit()

    first = client.post("/api/sessions/extension-session/extend")
    second = client.post("/api/sessions/extension-session/extend")

    assert first.status_code == 200
    assert datetime.fromisoformat(first.json()["expiresAt"]) == started_at + timedelta(minutes=120)
    assert second.status_code == 409
    with test_session_factory() as db:
        session = db.get(LabSession, "extension-session")
        assert session is not None and session.extension_count == 1


def test_guac_token_uses_documented_base64_json_envelope() -> None:
    key = "12345678901234567890123456789012"
    payload = {"connection": {"type": "rdp", "settings": {"hostname": "10.1.2.3"}}}

    encoded = encrypt_guac_token(payload, key)
    envelope = json.loads(base64.b64decode(encoded))
    decryptor = Cipher(
        algorithms.AES(key.encode()),
        modes.CBC(base64.b64decode(envelope["iv"])),
    ).decryptor()
    padded = decryptor.update(base64.b64decode(envelope["value"])) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    decoded = json.loads(unpadder.update(padded) + unpadder.finalize())

    assert decoded == payload


def test_guac_token_rejects_non_32_byte_keys() -> None:
    with pytest.raises(ValueError, match="32 UTF-8 bytes"):
        encrypt_guac_token({"connection": {}}, "short")


def test_connection_token_includes_session_id_and_enforced_expiration() -> None:
    key = "12345678901234567890123456789012"
    now = datetime(2026, 1, 1, tzinfo=UTC)
    token, expires_at = build_connection_token(
        session_id="session-123",
        host="10.50.16.4",
        username="learner",
        password="not-a-real-password",
        key=key,
        now=now,
    )

    envelope = json.loads(base64.b64decode(token))
    decryptor = Cipher(
        algorithms.AES(key.encode()),
        modes.CBC(base64.b64decode(envelope["iv"])),
    ).decryptor()
    padded = decryptor.update(base64.b64decode(envelope["value"])) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    decoded = json.loads(unpadder.update(padded) + unpadder.finalize())

    assert decoded["session_id"] == "session-123"
    assert decoded["expiration"] == int(expires_at.timestamp() * 1000)
    assert expires_at == now + timedelta(minutes=2)


@pytest.mark.parametrize("host", ["8.8.8.8", "127.0.0.1", "169.254.1.1", "100.64.0.1"])
def test_remote_desktop_rejects_non_rfc1918_ip(host: str) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        require_private_ip(host)

    assert error.value.status_code == 409


def test_remote_desktop_accepts_rfc1918_ip() -> None:
    assert require_private_ip("10.50.16.4") == "10.50.16.4"


def test_admin_course_and_learner_management(client: TestClient) -> None:
    course = client.post("/api/admin/courses", json={
        "title": "Azure Sandbox Test",
        "slug": "sandbox-test",
        "vmSize": "Standard_B2s",
        "sessionMinutes": 60,
        "poolSize": 0,
        "needsAzureSandbox": True,
    })
    assert course.status_code == 201

    learner = client.post("/api/admin/learners", json={
        "email": "learner@example.com",
        "name": "Test Learner",
        "courseSlug": "sandbox-test",
    })
    assert learner.status_code == 201
    assert client.get("/api/admin/learners").status_code == 200


def test_admin_live_sessions_and_csv_report(client: TestClient) -> None:
    client.post("/api/sessions", json={"labId": "foundry-lab-01"})
    live = client.get("/api/admin/sessions")
    assert live.status_code == 200
    assert len(live.json()["sessions"]) == 1

    report = client.get("/api/admin/reports/foundry.csv")
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/csv")
