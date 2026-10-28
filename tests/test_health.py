from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_database():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None
    assert body["data"]["database"] == "ok"
