"""REST API for patients. Thin: parse, call the service, wrap in the envelope.

Status codes:
  200 read/update/delete ok, 201 created, 400 malformed request (bad JSON, bad UUID, empty update),
  404 not found or already deleted, 422 field validation failed, 500 unexpected server error.
"""
import uuid

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import require_api_key
from app.core.calls import calls_for_record
from app.core.envelope import ok
from app.core.errors import AppError
from app.db.session import get_session
from app.domains.us_patient import service
from app.domains.us_patient.models import PatientCreate, PatientFilters, PatientOut, PatientUpdate

router = APIRouter(prefix="/patients", tags=["patients"], dependencies=[Depends(require_api_key)])


def _parse_id(patient_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(patient_id)
    except ValueError:
        raise AppError("patient_id must be a valid UUID.")


def _out(patient) -> dict:
    return PatientOut.model_validate(patient).model_dump(mode="json")


@router.get("")
def list_patients(
    last_name: str | None = Query(default=None, max_length=50),
    date_of_birth: str | None = Query(default=None, description="MM/DD/YYYY or YYYY-MM-DD"),
    phone_number: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    filters = PatientFilters.model_validate(
        {"last_name": last_name, "date_of_birth": date_of_birth, "phone_number": phone_number}
    )
    return ok([_out(p) for p in service.list_patients(session, filters)])


@router.get("/{patient_id}")
def get_patient(patient_id: str, session: Session = Depends(get_session)):
    return ok(_out(service.get_patient(session, _parse_id(patient_id))))


@router.get("/{patient_id}/calls")
def get_patient_calls(patient_id: str, session: Session = Depends(get_session)):
    """Bonus: transcripts and summaries of the calls that created or updated this patient."""
    pid = _parse_id(patient_id)
    service.get_patient(session, pid)
    calls = calls_for_record(session, str(pid))
    return ok([
        {
            "call_id": c.call_id, "status": c.status, "summary": c.summary, "transcript": c.transcript,
            "ended_reason": c.ended_reason, "created_at": c.created_at,
        }
        for c in calls
    ])


@router.post("", status_code=201)
def create_patient(payload: dict = Body(...), session: Session = Depends(get_session)):
    data = PatientCreate.model_validate(payload)
    patient, _ = service.create_patient(session, data)
    session.commit()
    return ok(_out(patient), status_code=201)


@router.put("/{patient_id}")
def update_patient(patient_id: str, payload: dict = Body(...), session: Session = Depends(get_session)):
    pid = _parse_id(patient_id)
    if not payload:
        raise AppError("Send at least one field to update.")
    data = PatientUpdate.model_validate(payload)
    patient = service.update_patient(session, pid, data)
    session.commit()
    return ok(_out(patient))


@router.delete("/{patient_id}")
def delete_patient(patient_id: str, session: Session = Depends(get_session)):
    patient = service.soft_delete_patient(session, _parse_id(patient_id))
    session.commit()
    return ok(_out(patient))
