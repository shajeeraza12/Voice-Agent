from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.core.calls import Call
from app.core.tools import ToolContext, dispatch
from app.db.session import SessionLocal
from app.domains.us_patient import service
from app.domains.us_patient.orm import Patient


def count_patients() -> int:
    with SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(Patient))


def ctx(call_id="call-1"):
    return ToolContext(call_id=call_id, caller_number="+14155550142")


def test_create_requires_confirmation(valid_patient):
    r = dispatch("create_patient", valid_patient, ctx())
    assert r.message.startswith("NOT_SAVED") and count_patients() == 0


def test_create_invalid_field_names_the_field(valid_patient):
    r = dispatch("create_patient", {**valid_patient, "date_of_birth": "01/01/2999", "caller_confirmed": True}, ctx())
    assert r.message.startswith("INVALID_FIELDS: date_of_birth")
    assert "can't be in the future" in r.message
    assert count_patients() == 0


def test_create_saves_and_logs_call(valid_patient):
    r = dispatch("create_patient", {**valid_patient, "caller_confirmed": True, "email": None, "address_line_2": ""}, ctx())
    assert r.message.startswith("SAVED") and "You're all set, Jane." in r.message
    with SessionLocal() as s:
        call = s.get(Call, "call-1")
        assert call.status == "saved" and call.record_id == r.record_id
        assert call.final_payload["last_name"] == "Doe"


def test_create_is_idempotent_per_call(valid_patient):
    dispatch("create_patient", {**valid_patient, "caller_confirmed": True}, ctx())
    r = dispatch("create_patient", {**valid_patient, "last_name": "Davis", "caller_confirmed": "true"}, ctx())
    assert r.message.startswith("SAVED") and count_patients() == 1
    with SessionLocal() as s:
        assert s.scalar(select(Patient)).last_name == "Davis"


def test_validate_details_partial():
    assert dispatch("validate_patient_details", {"state": "texas", "zip_code": "75001"}, ctx()).message.startswith("VALID")
    r = dispatch("validate_patient_details", {"phone_number": "555"}, ctx())
    assert r.message.startswith("INVALID_FIELDS: phone_number") and "10 digits" in r.message


def test_lookup(valid_patient):
    assert dispatch("lookup_patient_by_phone", {"phone_number": "4155550142"}, ctx()).message.startswith("NO_MATCH")
    dispatch("create_patient", {**valid_patient, "caller_confirmed": True}, ctx("first-call"))
    r = dispatch("lookup_patient_by_phone", {"phone_number": "(415) 555-0142"}, ctx("second-call"))
    assert r.message.startswith("MATCH") and "Jane Doe" in r.message
    # Falls back to caller ID when the agent passes no number.
    assert dispatch("lookup_patient_by_phone", {}, ctx("third-call")).message.startswith("MATCH")


def test_update_requires_dob_verification(valid_patient):
    pid = dispatch("create_patient", {**valid_patient, "caller_confirmed": True}, ctx("first")).record_id
    base = {"patient_id": pid, "city": "Chicago", "caller_confirmed": True}
    assert "date of birth" in dispatch("update_patient", base, ctx("second")).message
    wrong = dispatch("update_patient", {**base, "verify_date_of_birth": "01/01/1990"}, ctx("second"))
    assert wrong.message.startswith("NOT_SAVED") and "does not match" in wrong.message
    ok = dispatch("update_patient", {**base, "verify_date_of_birth": "04/12/1988"}, ctx("second"))
    assert ok.message.startswith("SAVED")
    with SessionLocal() as s:
        assert s.scalar(select(Patient)).city == "Chicago"


def test_update_same_call_skips_verification(valid_patient):
    pid = dispatch("create_patient", {**valid_patient, "caller_confirmed": True}, ctx("same")).record_id
    r = dispatch("update_patient", {"patient_id": pid, "zip_code": "62701", "caller_confirmed": True}, ctx("same"))
    assert r.message.startswith("SAVED")


def test_database_failure_is_spoken_not_silent(valid_patient, monkeypatch):
    def boom(*a, **k):
        raise OperationalError("INSERT", {}, Exception("connection refused"))
    monkeypatch.setattr(service, "create_patient", boom)
    r = dispatch("create_patient", {**valid_patient, "caller_confirmed": True}, ctx())
    assert r.message.startswith("ERROR") and "Apologise" in r.message
    assert r.payload["first_name"] == "Jane"  # payload kept for the log


def test_unknown_tool():
    assert dispatch("drop_tables", {}, ctx()).message.startswith("ERROR")
