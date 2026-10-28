# CLAUDE.md (voice-agent repository)

Coding agents read this at the start of every session.

## What this repo is

A voice AI agent platform. A caller phones a number, an LLM-driven voice agent (Vapi) talks to them, and our FastAPI server handles tool calls, validation, storage and a REST API. The first domain is US patient registration. Other domains (different businesses, different fields, other languages) are added as new folders under `app/domains/` without changing the core. Design notes: docs/ARCHITECTURE.md.

## Commands

- Run locally: `uvicorn app.main:app --reload`
- Tests: `pytest -q`
- Migrations: `alembic upgrade head`; new migration: `alembic revision --autogenerate -m "<msg>"`
- Seed: `python scripts/seed.py`
- Push the assistant to Vapi: `python scripts/push_assistant.py` (`--dry-run` to preview)
- Expose locally for Vapi: `ngrok http 8000`

## Rules for every change

1. **Working beats clever.** A simple system that works end to end beats an elegant one that breaks on the first call. No new dependency without a one-line reason.
2. **Keep the layers clean.** `core/`, `channels/` and `db/` never import from a specific domain (tests/test_architecture.py checks this). Domain code lives in `app/domains/<name>/`.
3. **Validation lives only in the domain's Pydantic models.** The API and the tools both use them. Never duplicate validation rules in the prompt or in route handlers.
4. **The agent only acts through tools.** Tools call services; services touch the database. No SQL in tools or routes.
5. **Every tool returns something speakable**, starting with a status word (VALID, INVALID_FIELDS, MATCH, NO_MATCH, SAVED, NOT_SAVED, ERROR). Never let an exception escape to the voice platform.
6. **Save only after confirmation.** Save tools require `caller_confirmed: true`.
7. **Responses use the envelope** `{ "data": ..., "error": null }` with correct status codes (200, 201, 400, 404, 422, 500).
8. **Soft delete only.** Set `deleted_at`, and exclude deleted rows from queries.
9. **No secrets in code.** Use environment variables, and keep `.env.example` complete.
10. **Log every call** as structured JSON to stdout, including the final collected payload.
11. **Tests with every endpoint and validator.** Run `pytest` before every commit.
12. **Prompts are code.** Edit `prompt.md` with comments that explain why each instruction exists.
13. **Docs:** never use em dashes. Keep the README accurate as you go, not at the end.

## Before saying something is done

- Tests pass.
- The endpoint or tool was actually exercised (curl, or a real call for agent behaviour).
- The README reflects the change.
