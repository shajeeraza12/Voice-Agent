"""Composition root: builds the FastAPI app, wires channels and registers domains.

This is the only place that names specific domains. Adding a domain means one
import and one register_domain call here.
"""
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.channels.vapi.router import router as vapi_router
from app.core.auth import require_api_key
from app.core.calls import Call
from app.core.envelope import ok, register_exception_handlers
from app.core.errors import NotFoundError
from app.core.logging import configure_logging
from app.core.registry import domains, register_domain
from app.db.session import engine, get_session
from app.domains import us_patient

configure_logging()

app = FastAPI(
    title="Voice Agent Platform: US Patient Registration",
    description="REST API behind a phone-based patient registration agent. Responses use {data, error}.",
    version="1.0.0",
)
register_exception_handlers(app)
app.include_router(vapi_router)
register_domain(app, us_patient.DOMAIN)


@app.get("/health", tags=["ops"])
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db = "ok"
    except Exception as exc:  # report, never crash the health check
        db = f"error: {type(exc).__name__}"
    return ok({"status": "ok", "database": db, "dialect": engine.dialect.name, "domains": domains()})


@app.get("/calls", tags=["calls"], dependencies=[Depends(require_api_key)])
def list_calls(limit: int = 50, session: Session = Depends(get_session)):
    """Call log: status, final payload, summary and transcript for recent calls."""
    rows = session.scalars(select(Call).order_by(Call.created_at.desc()).limit(min(max(limit, 1), 200)))
    return ok([_call_out(c) for c in rows])


@app.get("/calls/{call_id}", tags=["calls"], dependencies=[Depends(require_api_key)])
def get_call(call_id: str, session: Session = Depends(get_session)):
    call = session.get(Call, call_id)
    if call is None:
        raise NotFoundError("Call not found.")
    return ok(_call_out(call))


def _call_out(c: Call) -> dict:
    return {
        "call_id": c.call_id, "domain": c.domain, "caller_number": c.caller_number, "record_id": c.record_id,
        "status": c.status, "final_payload": c.final_payload, "summary": c.summary, "transcript": c.transcript,
        "ended_reason": c.ended_reason, "created_at": c.created_at, "updated_at": c.updated_at,
    }


_DASHBOARD = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    """Bonus: a read-only page listing registered patients and recent calls."""
    return _DASHBOARD
