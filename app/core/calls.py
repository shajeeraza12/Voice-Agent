"""Call log: one row per phone call, for every domain.

Stores the final collected payload (written the moment a save tool runs, so
nothing is lost even if the save itself fails), the end-of-call transcript and
summary, and the id of the record the call created or updated.
"""
import logging
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.logging import log_event
from app.db.base import Base, utcnow
from app.db.session import session_scope


class CallStatus:
    IN_PROGRESS = "in_progress"
    SAVED = "saved"
    SAVE_FAILED = "save_failed"
    ENDED_WITHOUT_SAVE = "ended_without_save"


class Call(Base):
    __tablename__ = "calls"

    call_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    domain: Mapped[str | None] = mapped_column(String(50))
    caller_number: Mapped[str | None] = mapped_column(String(30))
    record_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default=CallStatus.IN_PROGRESS, nullable=False)
    final_payload: Mapped[dict | None] = mapped_column(JSON)
    transcript: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    ended_reason: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


def upsert_call(session: Session, call_id: str, **fields) -> Call:
    call = session.get(Call, call_id)
    if call is None:
        call = Call(call_id=call_id)
        session.add(call)
    for key, value in fields.items():
        if value is not None:
            setattr(call, key, value)
    return call


def record_call_safely(call_id: str | None, **fields) -> None:
    """Best effort. The call log must never break a live call, so database errors are logged and swallowed."""
    if not call_id:
        return
    try:
        with session_scope() as session:
            upsert_call(session, call_id, **fields)
    except Exception as exc:
        log_event("call_log_write_failed", level=logging.ERROR, call_id=call_id, error=repr(exc))


def finish_call(call_id: str, **fields) -> None:
    """Called on Vapi's end-of-call report. Keeps 'saved' status if a save happened."""
    try:
        with session_scope() as session:
            call = upsert_call(session, call_id, **fields)
            if call.status in (CallStatus.IN_PROGRESS, None):
                call.status = CallStatus.ENDED_WITHOUT_SAVE
    except Exception as exc:
        log_event("call_log_write_failed", level=logging.ERROR, call_id=call_id, error=repr(exc))


def calls_for_record(session: Session, record_id: str) -> list[Call]:
    return list(session.scalars(select(Call).where(Call.record_id == record_id).order_by(Call.created_at)))
