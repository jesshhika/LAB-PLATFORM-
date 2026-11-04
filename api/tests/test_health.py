from fastapi.testclient import TestClient

from api.app.main import app


def test_health_endpoint_reports_api_healthy() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "api"}
