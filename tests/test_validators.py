from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.core.errors import field_errors, speakable
from app.domains.us_patient.models import PatientCreate, PatientUpdate


def make(valid_patient, **overrides):
    return PatientCreate.model_validate({**valid_patient, **overrides})


def error_for(valid_patient, **overrides) -> dict:
    with pytest.raises(ValidationError) as exc:
        make(valid_patient, **overrides)
    return {e["field"]: e["message"] for e in field_errors(exc.value)}


@pytest.mark.parametrize("name", ["O'Brien", "Mary-Jane", "De La Cruz", "Zoë", "Davis"])
def test_valid_names(valid_patient, name):
    assert make(valid_patient, last_name=name).last_name == name


@pytest.mark.parametrize("name", ["J0hn", "Smith!", "", "A" * 51])
def test_invalid_names(valid_patient, name):
    assert "last_name" in error_for(valid_patient, last_name=name)


def test_dob_formats(valid_patient):
    assert make(valid_patient, date_of_birth="04/12/1988").date_of_birth == date(1988, 4, 12)
    assert make(valid_patient, date_of_birth="1988-04-12").date_of_birth == date(1988, 4, 12)


def test_dob_future_rejected_with_speakable_message(valid_patient):
    tomorrow = (date.today() + timedelta(days=1)).strftime("%m/%d/%Y")
    errors = error_for(valid_patient, date_of_birth=tomorrow)
    assert errors == {"date_of_birth": "can't be in the future"}
    assert speakable([{"field": "date_of_birth", "message": errors["date_of_birth"]}]) == \
        "the date of birth can't be in the future"


@pytest.mark.parametrize("dob", ["02/30/1990", "13/01/1990", "1899-12-31", "yesterday"])
def test_dob_invalid(valid_patient, dob):
    assert "date_of_birth" in error_for(valid_patient, date_of_birth=dob)


@pytest.mark.parametrize("raw", ["(415) 555-0142", "415.555.0142", "+1 415 555 0142", "14155550142"])
def test_phone_normalised(valid_patient, raw):
    assert make(valid_patient, phone_number=raw).phone_number == "4155550142"


@pytest.mark.parametrize("raw,fragment", [("555", "10 digits"), ("0155550142", "area code"), ("4151550142", "middle")])
def test_phone_invalid(valid_patient, raw, fragment):
    assert fragment in error_for(valid_patient, phone_number=raw)["phone_number"]


@pytest.mark.parametrize("raw,expected", [("ca", "CA"), ("California", "CA"), ("new york", "NY"), ("DC", "DC")])
def test_state_normalised(valid_patient, raw, expected):
    assert make(valid_patient, state=raw).state == expected


def test_state_invalid(valid_patient):
    assert "state" in error_for(valid_patient, state="XX")


@pytest.mark.parametrize("raw,expected", [("62704", "62704"), ("62704-1234", "62704-1234"), ("627041234", "62704-1234")])
def test_zip(valid_patient, raw, expected):
    assert make(valid_patient, zip_code=raw).zip_code == expected


@pytest.mark.parametrize("raw", ["1234", "ABCDE", "123456"])
def test_zip_invalid(valid_patient, raw):
    assert "zip_code" in error_for(valid_patient, zip_code=raw)


@pytest.mark.parametrize("raw,expected", [("male", "Male"), ("F", "Female"), ("prefer not to say", "Decline to Answer"),
                                          ("Other", "Other")])
def test_sex(valid_patient, raw, expected):
    assert make(valid_patient, sex=raw).sex.value == expected


def test_optional_fields(valid_patient):
    p = make(valid_patient, email="Jane.Doe@Example.com", insurance_member_id="xyz-123 456",
             emergency_contact_phone="212 555 0123", address_line_2="")
    assert p.email == "jane.doe@example.com"
    assert p.insurance_member_id == "XYZ123456"
    assert p.emergency_contact_phone == "2125550123"
    assert p.address_line_2 is None
    assert p.preferred_language == "English"


def test_invalid_email(valid_patient):
    assert "email" in error_for(valid_patient, email="jane@")


def test_unknown_field_rejected(valid_patient):
    assert "favourite_colour" in error_for(valid_patient, favourite_colour="blue")


def test_control_characters_rejected(valid_patient):
    assert "city" in error_for(valid_patient, city="Spring\x00field")


def test_update_is_partial_but_cannot_null_required():
    assert PatientUpdate.model_validate({"city": "Chicago"}).changes() == {"city": "Chicago"}
    assert PatientUpdate.model_validate({"email": None}).changes() == {"email": None}
    with pytest.raises(ValidationError):
        PatientUpdate.model_validate({"last_name": None})
