"""Patient schemas and validation rules. The single source of truth.

The REST API and the voice agent's tools both validate through these models,
so the two paths cannot disagree. Error messages are written to be spoken:
the tool layer turns "date_of_birth: can't be in the future" into
"the date of birth can't be in the future".

Validators are also lenient about *format* (spoken input arrives in many shapes)
and strict about *meaning*: "(555) 234-5678", "555.234.5678" and "+1 555 234 5678"
all normalise to "5552345678", but a 9-digit number is rejected.
"""
import re
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Optional
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    model_validator,
)

# ---------------------------------------------------------------- reference data

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia", "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands",
    "AS": "American Samoa", "MP": "Northern Mariana Islands",
}
_STATE_BY_NAME = {name.lower(): code for code, name in US_STATES.items()}
_STATE_BY_NAME.update({"washington dc": "DC", "washington d.c.": "DC", "virgin islands": "VI"})


class Sex(str, Enum):
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"
    DECLINE = "Decline to Answer"


_SEX_SYNONYMS = {
    "male": Sex.MALE, "m": Sex.MALE, "man": Sex.MALE,
    "female": Sex.FEMALE, "f": Sex.FEMALE, "woman": Sex.FEMALE,
    "other": Sex.OTHER, "non-binary": Sex.OTHER, "nonbinary": Sex.OTHER,
    "decline to answer": Sex.DECLINE, "decline": Sex.DECLINE, "prefer not to say": Sex.DECLINE,
    "prefer not to answer": Sex.DECLINE, "declined": Sex.DECLINE,
}

MIN_DOB = date(1900, 1, 1)

# Letters (including accented ones), hyphens and apostrophes, per the spec.
# Deliberate extension: single internal spaces are allowed ("Mary Ann", "De La Cruz"),
# because rejecting real names on a phone call is worse than a slightly looser rule.
_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*'?$")
_CITY_RE = re.compile(r"^[^\W\d_]+(?:[ .'\-]+[^\W\d_]+)*\.?$")
_ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
_MEMBER_ID_RE = re.compile(r"^[A-Z0-9]{3,30}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

# ---------------------------------------------------------------- normalisers (before) and checks (after)


def _clean_text(v):
    """Basic sanitisation for every free-text field: trim, collapse spaces, refuse control characters."""
    if v is None:
        return v
    if not isinstance(v, str):
        v = str(v)
    if _CONTROL_CHARS.search(v):
        raise ValueError("contains characters that aren't allowed")
    v = re.sub(r"\s+", " ", v).strip()
    return v


def _blank_to_none(v):
    v = _clean_text(v)
    return v or None


def _check_name(v: str) -> str:
    v = v.replace("’", "'")
    if not 1 <= len(v) <= 50:
        raise ValueError("must be between 1 and 50 characters")
    if not _NAME_RE.match(v):
        raise ValueError("can only contain letters, hyphens and apostrophes")
    return v


def _check_full_name(v: str) -> str:
    v = v.replace("’", "'")
    if not 1 <= len(v) <= 100:
        raise ValueError("must be between 1 and 100 characters")
    if not _NAME_RE.match(v):
        raise ValueError("can only contain letters, spaces, hyphens and apostrophes")
    return v


def normalize_phone(v):
    if v is None:
        return v
    digits = re.sub(r"\D", "", str(v))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def _check_phone(v: str) -> str:
    if len(v) != 10:
        raise ValueError(f"needs to be 10 digits, and I got {len(v)}")
    # North American Numbering Plan: area code and exchange cannot start with 0 or 1.
    if v[0] in "01":
        raise ValueError("doesn't look like a valid US number, because the area code can't start with 0 or 1")
    if v[3] in "01":
        raise ValueError("doesn't look like a valid US number, because the middle three digits can't start with 0 or 1")
    return v


def parse_date(v):
    """Accepts a date, MM/DD/YYYY (the spec's format), or ISO YYYY-MM-DD."""
    if v is None or isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError("isn't a real date. Please give it as month, day and year")


def _check_dob(v: date) -> date:
    if v > date.today():
        raise ValueError("can't be in the future")
    if v < MIN_DOB:
        raise ValueError("can't be before 1900")
    return v


def _normalize_sex(v):
    if v is None or isinstance(v, Sex):
        return v
    key = _clean_text(v).lower()
    if key in _SEX_SYNONYMS:
        return _SEX_SYNONYMS[key]
    raise ValueError("must be male, female, other, or decline to answer")


def _normalize_state(v):
    v = _clean_text(v)
    if not v:
        return v
    if len(v) == 2:
        return v.upper()
    return _STATE_BY_NAME.get(v.lower(), v)


def _check_state(v: str) -> str:
    if v not in US_STATES:
        raise ValueError("must be a valid two-letter US state, like CA or NY")
    return v


def _normalize_zip(v):
    v = _clean_text(v)
    if v is None:
        return v
    digits = re.sub(r"\D", "", v)
    if len(digits) == 9:
        return f"{digits[:5]}-{digits[5:]}"
    if len(digits) == 5 and len(v) <= 7:
        return digits
    return v


def _check_zip(v: str) -> str:
    if not _ZIP_RE.match(v):
        raise ValueError("must be five digits, or five plus four")
    return v


def _check_city(v: str) -> str:
    if not 1 <= len(v) <= 100:
        raise ValueError("must be between 1 and 100 characters")
    if not _CITY_RE.match(v):
        raise ValueError("can only contain letters, spaces, periods, hyphens and apostrophes")
    return v


def _check_address(v: str) -> str:
    if not 1 <= len(v) <= 100:
        raise ValueError("must be between 1 and 100 characters")
    if not re.search(r"[A-Za-z0-9]", v):
        raise ValueError("doesn't look like a street address")
    return v


def _check_line2(v: str) -> str:
    if len(v) > 100:
        raise ValueError("must be 100 characters or fewer")
    return v


def _normalize_member_id(v):
    v = _blank_to_none(v)
    if v is None:
        return v
    return re.sub(r"[\s\-]", "", v).upper()


def _check_member_id(v: str) -> str:
    if not _MEMBER_ID_RE.match(v):
        raise ValueError("must be 3 to 30 letters and numbers")
    return v


def _check_short_text(limit: int):
    def check(v: str) -> str:
        if not 1 <= len(v) <= limit:
            raise ValueError(f"must be between 1 and {limit} characters")
        return v
    return check


def _check_language(v: str) -> str:
    if not 1 <= len(v) <= 50 or not re.match(r"^[^\W\d_]+(?: [^\W\d_]+)*$", v):
        raise ValueError("must be a language name, like English or Spanish")
    return v.title()


def _lower(v):
    return v.lower() if isinstance(v, str) else v


# ---------------------------------------------------------------- reusable field types

def _optional(check):
    """Optional fields: blank or missing becomes None, anything else must pass the check."""
    def run(v):
        return None if v is None else check(v)
    return run


# Required field types
Name = Annotated[str, BeforeValidator(_clean_text), AfterValidator(_check_name)]
Phone = Annotated[str, BeforeValidator(normalize_phone), AfterValidator(_check_phone)]
DateOfBirth = Annotated[date, BeforeValidator(parse_date), AfterValidator(_check_dob)]
SexField = Annotated[Sex, BeforeValidator(_normalize_sex)]
Address1 = Annotated[str, BeforeValidator(_clean_text), AfterValidator(_check_address)]
City = Annotated[str, BeforeValidator(_clean_text), AfterValidator(_check_city)]
State = Annotated[str, BeforeValidator(_normalize_state), AfterValidator(_check_state)]
Zip = Annotated[str, BeforeValidator(_normalize_zip), AfterValidator(_check_zip)]

# Optional field types: the blank-to-None step wraps the whole Optional so "" means "not provided"
OptEmail = Annotated[Optional[EmailStr], BeforeValidator(_blank_to_none), AfterValidator(_optional(_lower))]
OptAddress2 = Annotated[Optional[str], BeforeValidator(_blank_to_none), AfterValidator(_optional(_check_line2))]
OptInsuranceProvider = Annotated[Optional[str], BeforeValidator(_blank_to_none),
                                 AfterValidator(_optional(_check_short_text(100)))]
OptMemberId = Annotated[Optional[str], BeforeValidator(_normalize_member_id), AfterValidator(_optional(_check_member_id))]
OptLanguage = Annotated[Optional[str], BeforeValidator(_blank_to_none), AfterValidator(_optional(_check_language))]
OptFullName = Annotated[Optional[str], BeforeValidator(_blank_to_none), AfterValidator(_optional(_check_full_name))]
OptPhone = Annotated[Optional[str], BeforeValidator(lambda v: normalize_phone(_blank_to_none(v))),
                     AfterValidator(_optional(_check_phone))]

REQUIRED_FIELDS = (
    "first_name", "last_name", "date_of_birth", "sex", "phone_number",
    "address_line_1", "city", "state", "zip_code",
)
OPTIONAL_FIELDS = (
    "email", "address_line_2", "insurance_provider", "insurance_member_id",
    "preferred_language", "emergency_contact_name", "emergency_contact_phone",
)


class _Strict(BaseModel):
    # Unknown fields are rejected so typos in API calls fail loudly instead of being silently dropped.
    model_config = ConfigDict(extra="forbid")


class PatientCreate(_Strict):
    first_name: Name
    last_name: Name
    date_of_birth: DateOfBirth
    sex: SexField
    phone_number: Phone
    email: OptEmail = None
    address_line_1: Address1
    address_line_2: OptAddress2 = None
    city: City
    state: State
    zip_code: Zip
    insurance_provider: OptInsuranceProvider = None
    insurance_member_id: OptMemberId = None
    preferred_language: OptLanguage = Field(default="English")
    emergency_contact_name: OptFullName = None
    emergency_contact_phone: OptPhone = None

    @model_validator(mode="after")
    def _defaults(self):
        if self.preferred_language is None:
            self.preferred_language = "English"
        return self


class PatientUpdate(_Strict):
    """Partial update. Omitted fields are untouched. Required fields can't be set to null;
    optional ones can (to clear them)."""

    first_name: Optional[Name] = None
    last_name: Optional[Name] = None
    date_of_birth: Optional[DateOfBirth] = None
    sex: Optional[SexField] = None
    phone_number: Optional[Phone] = None
    email: OptEmail = None
    address_line_1: Optional[Address1] = None
    address_line_2: OptAddress2 = None
    city: Optional[City] = None
    state: Optional[State] = None
    zip_code: Optional[Zip] = None
    insurance_provider: OptInsuranceProvider = None
    insurance_member_id: OptMemberId = None
    preferred_language: OptLanguage = None
    emergency_contact_name: OptFullName = None
    emergency_contact_phone: OptPhone = None

    @model_validator(mode="after")
    def _required_not_null(self):
        nulled = [f for f in REQUIRED_FIELDS if f in self.model_fields_set and getattr(self, f) is None]
        if nulled:
            raise ValueError(f"{', '.join(nulled)} can't be removed because it is required")
        return self

    def changes(self) -> dict:
        return self.model_dump(exclude_unset=True)


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: UUID
    first_name: str
    last_name: str
    date_of_birth: date
    sex: Sex
    phone_number: str
    email: Optional[str] = None
    address_line_1: str
    address_line_2: Optional[str] = None
    city: str
    state: str
    zip_code: str
    insurance_provider: Optional[str] = None
    insurance_member_id: Optional[str] = None
    preferred_language: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


class PatientFilters(BaseModel):
    """Query parameters for GET /patients, validated with the same rules."""

    last_name: Optional[str] = None
    date_of_birth: Optional[Annotated[date, BeforeValidator(parse_date)]] = None
    phone_number: Optional[Phone] = None

    @model_validator(mode="before")
    @classmethod
    def _blank_params(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v not in (None, "")}
        return data
