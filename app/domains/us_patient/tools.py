"""What the voice agent is allowed to do for this domain.

Each tool validates through the same Pydantic models as the REST API and calls the
same service layer. Results start with a status word the prompt relies on:
  VALID / INVALID_FIELDS   from validate_patient_details
  MATCH / NO_MATCH         from lookup_patient_by_phone
  SAVED / NOT_SAVED        from create_patient and update_patient
  ERROR                    system problem (added by the core dispatcher)
"""
import uuid

from pydantic import BaseModel

from app.core.errors import AppError
from app.core.tools import ToolContext, ToolResult
from app.db.session import session_scope
from app.domains.us_patient import service
from app.domains.us_patient.models import (
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    DateOfBirth,
    PatientCreate,
    PatientUpdate,
    Phone,
    US_STATES,
)

PATIENT_FIELDS = set(REQUIRED_FIELDS) | set(OPTIONAL_FIELDS)


class _PhoneOnly(BaseModel):
    phone_number: Phone


class _DobOnly(BaseModel):
    date_of_birth: DateOfBirth


def _fields(args: dict) -> dict:
    """Keep only patient fields the LLM actually filled. LLMs often send nulls or empty
    strings for things the caller never mentioned; treat those as 'not provided'."""
    return {k: v for k, v in args.items() if k in PATIENT_FIELDS and v not in (None, "")}


def _confirmed(args: dict) -> bool:
    return _flag(args, "caller_confirmed")


def _flag(args: dict, key: str) -> bool:
    value = args.get(key)
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _existing_patients(session, phone: str, ctx: ToolContext) -> list:
    """Active patients with this phone, excluding one created earlier in this same call."""
    return [p for p in service.find_by_phone(session, phone) if not (ctx.call_id and p.source_call_id == ctx.call_id)]


def _match_message(matches: list) -> str:
    p = matches[0]
    others = ""
    if len(matches) > 1:
        names = ", ".join(f"{m.first_name} {m.last_name}" for m in matches[1:])
        others = f" Other patients also share this number: {names}. Ask which person is calling if unclear."
    return (
        f"MATCH: patient_id={p.patient_id}; name={p.first_name} {p.last_name}.{others} "
        f"Before collecting anything else, ask: 'It looks like we already have a record for {p.first_name} {p.last_name}. "
        "Would you like to update your information instead?' "
        "If yes, ask for their date of birth to verify before changing anything. "
        "If they say that record is someone else (for example a family member sharing the phone), continue the new "
        "registration and pass confirmed_new_patient=true to create_patient. Do not read out any other stored details."
    )


def _readable(values: dict) -> str:
    """Normalised values in a form that is easy to read back on the phone."""
    out = []
    for key, value in values.items():
        if value is None:
            continue
        if key == "date_of_birth":
            value = f"{value:%B} {value.day}, {value.year}"
        elif key in ("phone_number", "emergency_contact_phone"):
            value = f"{value[:3]}-{value[3:6]}-{value[6:]}"
        elif key == "state":
            value = f"{value} ({US_STATES[value]})"
        elif hasattr(value, "value"):
            value = value.value
        out.append(f"{key}={value}")
    return "; ".join(out)


def validate_patient_details(args: dict, ctx: ToolContext) -> ToolResult:
    """Check any subset of fields without saving. Lets the agent re-ask for a bad field
    immediately instead of discovering it only at the final save."""
    fields = _fields(args)
    if not fields:
        return ToolResult("VALID: no fields were provided to check.")
    data = PatientUpdate.model_validate(fields)  # partial: validates only what was given
    result = f"VALID: {_readable(data.changes())}"
    # The returning-patient check runs here too, deterministically, whenever a valid phone number is checked.
    # In live testing the model often skipped a separate lookup when the caller gave their number early.
    if data.phone_number:
        with session_scope() as session:
            matches = _existing_patients(session, data.phone_number, ctx)
            if matches:
                return ToolResult(f"{result}. {_match_message(matches)}", extra={"patient_id": str(matches[0].patient_id)})
    return ToolResult(result)


def lookup_patient_by_phone(args: dict, ctx: ToolContext) -> ToolResult:
    raw = args.get("phone_number") or ctx.caller_number
    if not raw:
        return ToolResult("NO_MATCH: no phone number to look up. Continue with a new registration.")
    phone = _PhoneOnly.model_validate({"phone_number": raw}).phone_number
    with session_scope() as session:
        matches = _existing_patients(session, phone, ctx)
        if not matches:
            return ToolResult("NO_MATCH: no existing patient with this phone number. Continue with a new registration.")
        return ToolResult(_match_message(matches), extra={"patient_id": str(matches[0].patient_id)})


def create_patient(args: dict, ctx: ToolContext) -> ToolResult:
    fields = _fields(args)
    if not _confirmed(args):
        return ToolResult(
            "NOT_SAVED: the caller has not confirmed yet. Read back every detail, ask if it is all correct, "
            "and call create_patient again with caller_confirmed=true only after a clear yes.",
            ok=False,
        )
    data = PatientCreate.model_validate(fields)
    with session_scope() as session:
        # Duplicate guard: never silently create a second record for a phone number we already have,
        # unless the caller said the existing record is a different person.
        if not _flag(args, "confirmed_new_patient"):
            matches = _existing_patients(session, data.phone_number, ctx)
            if matches:
                return ToolResult("NOT_SAVED: " + _match_message(matches), ok=False,
                                  extra={"patient_id": str(matches[0].patient_id)})
        patient, created = service.create_patient(session, data, source_call_id=ctx.call_id)
        patient_id = str(patient.patient_id)
    verb = "saved" if created else "updated (same call, no duplicate created)"
    return ToolResult(
        f"SAVED: registration {verb}. patient_id={patient_id}. "
        f"Now say to the caller: \"You're all set, {data.first_name}.\" plus one short warm sentence. "
        "Only after saying it, end the call in a separate step. Do not say goodbye yourself; the system does.",
        payload=data.model_dump(mode="json"),
        record_id=patient_id,
        saved=True,
    )


def update_patient(args: dict, ctx: ToolContext) -> ToolResult:
    if not _confirmed(args):
        return ToolResult(
            "NOT_SAVED: read back the changes, get a clear yes, then call update_patient again with caller_confirmed=true.",
            ok=False,
        )
    try:
        patient_id = uuid.UUID(str(args.get("patient_id", "")))
    except ValueError:
        raise AppError("patient_id is missing or invalid. Use the patient_id from lookup_patient_by_phone.")

    changes = _fields(args)
    if not changes:
        raise AppError("no changes were provided. Ask the caller what they would like to update.")
    data = PatientUpdate.model_validate(changes)

    with session_scope() as session:
        patient = service.get_patient(session, patient_id)
        # A returning caller must prove who they are before we change anything. A record created
        # earlier in this same call is exempt: the caller just gave us all of it.
        if patient.source_call_id != ctx.call_id or ctx.call_id is None:
            raw_dob = args.get("verify_date_of_birth")
            if not raw_dob:
                return ToolResult(
                    "NOT_SAVED: ask the caller for their date of birth to verify their identity, "
                    "then call again with verify_date_of_birth.", ok=False)
            dob = _DobOnly.model_validate({"date_of_birth": raw_dob}).date_of_birth
            if not service.dob_matches(patient, dob):
                return ToolResult(
                    "NOT_SAVED: that date of birth does not match our record, so nothing was changed. "
                    "Apologise, and offer to register them as a new patient instead.", ok=False)
        patient = service.update_patient(session, patient_id, data)
        first_name = patient.first_name

    return ToolResult(
        f"SAVED: updated {', '.join(changes)}. patient_id={patient_id}. "
        f"Now say to the caller: \"You're all set, {first_name}.\" "
        "Only after saying it, end the call in a separate step. Do not say goodbye yourself; the system does.",
        payload={"patient_id": str(patient_id), **data.model_dump(mode="json", exclude_unset=True)},
        record_id=str(patient_id),
        saved=True,
    )


TOOLS = {
    "validate_patient_details": validate_patient_details,
    "lookup_patient_by_phone": lookup_patient_by_phone,
    "create_patient": create_patient,
    "update_patient": update_patient,
}
