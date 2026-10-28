"""patients table. Typed columns plus database-level constraints as a second line of defence
behind the Pydantic models (they protect the data even if someone writes SQL by hand).

Constraints here are portable (they run on Postgres and on SQLite for local dev).
The migration adds stricter regex checks on Postgres only. "Date of birth not in
the future" can't be a CHECK constraint because CURRENT_DATE is not immutable,
so it is enforced in the model layer.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.domains.us_patient.models import Sex


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    sex: Mapped[Sex] = mapped_column(
        Enum(Sex, name="sex", values_callable=lambda e: [m.value for m in e], validate_strings=True),
        nullable=False,
    )
    phone_number: Mapped[str] = mapped_column(String(10), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254))
    address_line_1: Mapped[str] = mapped_column(String(100), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False)
    insurance_provider: Mapped[str | None] = mapped_column(String(100))
    insurance_member_id: Mapped[str | None] = mapped_column(String(30))
    preferred_language: Mapped[str | None] = mapped_column(String(50), default="English")
    emergency_contact_name: Mapped[str | None] = mapped_column(String(100))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(10))
    # Idempotency key: the voice call that created this record. A retried or repeated
    # save in the same call updates this row instead of creating a duplicate.
    source_call_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("length(first_name) BETWEEN 1 AND 50", name="ck_patients_first_name_len"),
        CheckConstraint("length(last_name) BETWEEN 1 AND 50", name="ck_patients_last_name_len"),
        CheckConstraint("length(phone_number) = 10", name="ck_patients_phone_len"),
        CheckConstraint("emergency_contact_phone IS NULL OR length(emergency_contact_phone) = 10",
                        name="ck_patients_ec_phone_len"),
        CheckConstraint("length(city) BETWEEN 1 AND 100", name="ck_patients_city_len"),
        CheckConstraint("length(state) = 2", name="ck_patients_state_len"),
        CheckConstraint("length(zip_code) IN (5, 10)", name="ck_patients_zip_len"),
        CheckConstraint("date_of_birth >= '1900-01-01'", name="ck_patients_dob_min"),
        Index("ix_patients_last_name", "last_name"),
        Index("ix_patients_phone_number", "phone_number"),
        Index("ix_patients_date_of_birth", "date_of_birth"),
    )
