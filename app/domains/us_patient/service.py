"""Patient service: the only code that reads or writes the patients table.

Both the REST API and the voice agent's tools call these functions, so business
rules (soft delete, idempotent saves, filters) behave identically on both paths.
"""
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.base import utcnow
from app.domains.us_patient.models import PatientCreate, PatientFilters, PatientUpdate
from app.domains.us_patient.orm import Patient


def _active():
    return select(Patient).where(Patient.deleted_at.is_(None))


def get_patient(session: Session, patient_id: uuid.UUID) -> Patient:
    patient = session.scalar(_active().where(Patient.patient_id == patient_id))
    if patient is None:
        raise NotFoundError("Patient not found.")
    return patient


def list_patients(session: Session, filters: PatientFilters) -> list[Patient]:
    q = _active()
    if filters.last_name:
        q = q.where(func.lower(Patient.last_name) == filters.last_name.strip().lower())
    if filters.date_of_birth:
        q = q.where(Patient.date_of_birth == filters.date_of_birth)
    if filters.phone_number:
        q = q.where(Patient.phone_number == filters.phone_number)
    return list(session.scalars(q.order_by(Patient.created_at.desc())))


def find_by_phone(session: Session, phone_number: str) -> list[Patient]:
    return list(session.scalars(
        _active().where(Patient.phone_number == phone_number).order_by(Patient.updated_at.desc())
    ))


def create_patient(session: Session, data: PatientCreate, source_call_id: str | None = None) -> tuple[Patient, bool]:
    """Returns (patient, created). If this call already saved a patient, update that row instead
    of inserting a second one, so retries and repeated confirmations can't create duplicates."""
    if source_call_id:
        existing = session.scalar(select(Patient).where(Patient.source_call_id == source_call_id))
        if existing is not None:
            for key, value in data.model_dump().items():
                setattr(existing, key, value)
            existing.deleted_at = None
            session.flush()
            return existing, False
    patient = Patient(**data.model_dump(), source_call_id=source_call_id)
    session.add(patient)
    session.flush()
    return patient, True


def update_patient(session: Session, patient_id: uuid.UUID, data: PatientUpdate) -> Patient:
    patient = get_patient(session, patient_id)
    for key, value in data.changes().items():
        setattr(patient, key, value)
    patient.updated_at = utcnow()
    session.flush()
    return patient


def soft_delete_patient(session: Session, patient_id: uuid.UUID) -> Patient:
    patient = get_patient(session, patient_id)
    patient.deleted_at = utcnow()
    session.flush()
    return patient


def dob_matches(patient: Patient, dob: date) -> bool:
    return patient.date_of_birth == dob
