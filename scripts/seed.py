"""Insert two demo patients if they are not there yet. Safe to run more than once.

Usage: python scripts/seed.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import session_scope  # noqa: E402
from app.domains.us_patient import service  # noqa: E402
from app.domains.us_patient.models import PatientCreate  # noqa: E402

SEED = [
    {
        "first_name": "Jane", "last_name": "Doe", "date_of_birth": "04/12/1988", "sex": "Female",
        "phone_number": "415-555-0142", "email": "jane.doe@example.com",
        "address_line_1": "742 Evergreen Terrace", "city": "Springfield", "state": "IL", "zip_code": "62704",
        "insurance_provider": "Blue Cross Blue Shield", "insurance_member_id": "XYZ123456789",
    },
    {
        "first_name": "Carlos", "last_name": "Ramirez", "date_of_birth": "11/03/1975", "sex": "Male",
        "phone_number": "(212) 555-0199", "address_line_1": "15 W 47th St", "address_line_2": "Apt 4B",
        "city": "New York", "state": "NY", "zip_code": "10036-1234", "preferred_language": "Spanish",
        "emergency_contact_name": "Maria Ramirez", "emergency_contact_phone": "212-555-0123",
    },
]


def main() -> None:
    with session_scope() as session:
        for raw in SEED:
            data = PatientCreate.model_validate(raw)
            key = f"seed-{data.first_name.lower()}-{data.last_name.lower()}"
            patient, created = service.create_patient(session, data, source_call_id=key)
            print(("created " if created else "already present ") + f"{patient.first_name} {patient.last_name} {patient.patient_id}")


if __name__ == "__main__":
    main()
