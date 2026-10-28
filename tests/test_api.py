import uuid


def test_create_returns_201_envelope(client, valid_patient):
    r = client.post("/patients", json=valid_patient)
    assert r.status_code == 201
    body = r.json()
    assert body["error"] is None
    data = body["data"]
    uuid.UUID(data["patient_id"])
    assert data["phone_number"] == "4155550142"
    assert data["date_of_birth"] == "1988-04-12"
    assert data["deleted_at"] is None and data["created_at"] and data["updated_at"]


def test_validation_error_is_422_with_fields(client, valid_patient):
    r = client.post("/patients", json={**valid_patient, "phone_number": "555", "state": "XX"})
    assert r.status_code == 422
    body = r.json()
    assert body["data"] is None
    assert {f["field"] for f in body["error"]["fields"]} == {"phone_number", "state"}


def test_malformed_json_is_400(client):
    r = client.post("/patients", content="{nope", headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_get_and_filters(client, valid_patient):
    pid = client.post("/patients", json=valid_patient).json()["data"]["patient_id"]
    client.post("/patients", json={**valid_patient, "first_name": "John", "last_name": "Smith",
                                   "phone_number": "312-555-0100", "date_of_birth": "1970-01-01"})
    assert client.get(f"/patients/{pid}").json()["data"]["first_name"] == "Jane"
    assert len(client.get("/patients").json()["data"]) == 2
    assert [p["last_name"] for p in client.get("/patients?last_name=DOE").json()["data"]] == ["Doe"]
    assert len(client.get("/patients?date_of_birth=04/12/1988").json()["data"]) == 1
    assert len(client.get("/patients?date_of_birth=1988-04-12").json()["data"]) == 1
    assert len(client.get("/patients?phone_number=(415) 555-0142").json()["data"]) == 1


def test_bad_filter_is_422(client):
    assert client.get("/patients?phone_number=123").status_code == 422
    assert client.get("/patients?date_of_birth=notadate").status_code == 422


def test_not_found_and_bad_id(client):
    assert client.get(f"/patients/{uuid.uuid4()}").status_code == 404
    assert client.get("/patients/abc").status_code == 400


def test_partial_update(client, valid_patient):
    created = client.post("/patients", json=valid_patient).json()["data"]
    r = client.put(f"/patients/{created['patient_id']}", json={"city": "Chicago", "zip_code": "60601"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["city"] == "Chicago" and data["first_name"] == "Jane"
    assert data["updated_at"] >= created["updated_at"]


def test_update_errors(client, valid_patient):
    pid = client.post("/patients", json=valid_patient).json()["data"]["patient_id"]
    assert client.put(f"/patients/{pid}", json={}).status_code == 400
    assert client.put(f"/patients/{pid}", json={"date_of_birth": "01/01/2999"}).status_code == 422
    assert client.put(f"/patients/{pid}", json={"last_name": None}).status_code == 422
    assert client.put(f"/patients/{uuid.uuid4()}", json={"city": "Chicago"}).status_code == 404


def test_soft_delete(client, valid_patient):
    pid = client.post("/patients", json=valid_patient).json()["data"]["patient_id"]
    r = client.delete(f"/patients/{pid}")
    assert r.status_code == 200 and r.json()["data"]["deleted_at"] is not None
    assert client.get(f"/patients/{pid}").status_code == 404
    assert client.get("/patients").json()["data"] == []
    assert client.delete(f"/patients/{pid}").status_code == 404
    # The row is still in the database.
    from app.db.session import SessionLocal
    from app.domains.us_patient.orm import Patient
    with SessionLocal() as s:
        assert s.get(Patient, uuid.UUID(pid)) is not None


def test_unknown_route_uses_envelope(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.json()["data"] is None


def test_health_and_dashboard(client):
    assert client.get("/health").json()["data"]["database"] == "ok"
    assert "Patient Registry" in client.get("/").text
