# Voice AI Patient Registration Agent

Call a US phone number, talk to an AI intake coordinator, and get registered as a new patient. The agent collects standard US patient demographics in a natural conversation, reads everything back for confirmation, saves it to Postgres through a validated service layer, and the same data is available through a REST API.

## Live demo

| | |
|---|---|
| Phone number | +1 (858) 399-4010 |
| API base URL | https://voice-agent-mvx9.onrender.com |
| API docs (Swagger) | `<API base URL>/docs` |
| Dashboard | `<API base URL>/` (read-only list of patients and recent calls) |
| Credentials | None needed. The API is open for review (see Security). |

Two seed patients exist for testing: Jane Doe (phone 415-555-0142) and Carlos Ramirez (212-555-0199). Calling and giving one of those numbers triggers the returning-patient flow.

## What it does

- Answers the phone as "Riley", discloses that it is an AI, and registers a new patient conversationally: name (with spelling), date of birth, sex, phone, address, optional email, then offers insurance, emergency contact and preferred language as an opt-in group.
- Accepts answers out of order, handles corrections at any time (spelled letters always win), handles interruptions, and can start over.
- Validates as it goes: an invalid date of birth or phone number is caught right away and only that field is asked again.
- Reads everything back in two short parts and saves only after a clear yes. The save tool itself refuses to write without `caller_confirmed=true`.
- Ends with "You're all set, [first name]." and hangs up.
- Recognises returning callers by phone number and offers to update their record instead, after verifying their date of birth.
- If the database is down, the agent says so out loud and asks the caller to call back. The collected payload is still logged.
- Stores a transcript, summary and final payload for every call, linked to the patient record.

## Architecture

```
Caller (PSTN)
   |
Vapi: phone number, speech-to-text (Deepgram), LLM turns (GPT-4.1 mini), text-to-speech
   |  HTTPS webhook: tool calls, call status, end-of-call report (Bearer secret)
   v
FastAPI service
   channels/vapi      verifies the secret, parses Vapi messages, formats replies
   core               tool dispatcher (always returns speakable text), error-to-speech,
                      call log, JSON logging, response envelope
   domains/us_patient models (all validation), tools, service, REST routes, prompt, assistant config
   db                 SQLAlchemy + Alembic, Postgres in production
   ^
REST API /patients ---- same service layer as the agent, so behaviour can't diverge
```

Key decisions:

- **Validation lives in one place.** Pydantic models in `app/domains/us_patient/models.py` are the only source of validation rules. The REST API and the agent's tools both go through them. The prompt never restates rules; it only says when to call `validate_patient_details` and how to react to the result.
- **The agent never touches the database.** It calls tools; tools call the service layer; the service layer is the only code that queries the `patients` table. The REST API calls the same service.
- **Confirmation is enforced in code, not just in the prompt.** `create_patient` and `update_patient` refuse to write unless `caller_confirmed` is true.
- **Saves are idempotent per call.** The Vapi call ID is stored on the patient (`source_call_id`, unique). A retried or repeated save in the same call updates that row instead of creating a duplicate.
- **Tool results start with a status word** (`VALID`, `INVALID_FIELDS`, `MATCH`, `NO_MATCH`, `SAVED`, `NOT_SAVED`, `ERROR`) followed by a plain sentence. The prompt keys its behaviour off the status word, which makes the agent's reactions predictable.
- **No exception reaches Vapi.** The dispatcher catches validation errors, database errors and crashes and turns each into a speakable message, because a failed webhook means dead air on the phone.
- **Domains and channels are pluggable.** `core/`, `channels/` and `db/` never import a specific domain (a test enforces this). A new use case is a new folder under `app/domains/`; a new voice platform is a new adapter under `app/channels/`.

## Tech stack and why

| Layer | Choice | Why |
|---|---|---|
| Telephony and voice | Vapi | Handles the number, STT, TTS, turn-taking and barge-in, so the effort goes into the prompt, tools and backend. Free US number for inbound calls. |
| LLM | OpenAI GPT-4.1 mini (via Vapi) | Fast enough for natural turn-taking, reliable at tool calling with many arguments. Large models add latency that callers notice. |
| STT / TTS | Deepgram Nova-3, Vapi voice | Low latency defaults on Vapi. |
| Backend | Python, FastAPI, Pydantic v2 | Typed validation that is shared by the API and the agent, automatic OpenAPI docs. |
| Database | Postgres (SQLAlchemy 2, Alembic) | Survives restarts and redeploys. SQLite works for local development only, because many hosts wipe local disk. |
| Hosting | Render (app) + Neon (Postgres) | Render deploys the Dockerfile straight from GitHub. Neon is managed Postgres that persists across restarts and redeploys and resumes from idle in a few hundred milliseconds. Railway was the first choice, but it had paused new signups after a security incident, so this was the fastest reliable alternative. |

## Data model

`patients`: `patient_id` (UUID, primary key), `first_name`, `last_name` (1 to 50 chars), `date_of_birth` (date, not in the future, not before 1900), `sex` (enum: Male, Female, Other, Decline to Answer), `phone_number` (10 digits, NANP rules), `email`, `address_line_1`, `address_line_2`, `city` (1 to 100), `state` (valid 2-letter code incl. DC and territories), `zip_code` (5 digits or ZIP+4), `insurance_provider`, `insurance_member_id` (alphanumeric), `preferred_language` (default English), `emergency_contact_name`, `emergency_contact_phone`, `source_call_id` (unique, idempotency key), `created_at`, `updated_at`, `deleted_at` (soft delete). All timestamps are UTC.

Constraints are enforced twice: in the Pydantic models (with friendly messages) and in the database (length and format CHECK constraints, NOT NULL, enum type, unique call ID, indexes on last name, phone and date of birth). On Postgres the migration also adds regex CHECKs for phone, ZIP, state and member ID.

`calls`: one row per phone call with status (`in_progress`, `saved`, `save_failed`, `ended_without_save`), caller number, final payload, transcript, summary, ended reason and the linked `record_id`.

## REST API

All responses use the envelope `{"data": ..., "error": null}` or `{"data": null, "error": {"code", "message", "fields"?}}`.

| Method | Path | Notes |
|---|---|---|
| GET | `/patients` | Optional filters `last_name` (case-insensitive), `date_of_birth` (MM/DD/YYYY or YYYY-MM-DD), `phone_number` (any format). Excludes soft-deleted. |
| GET | `/patients/{id}` | 404 if missing or deleted, 400 if not a UUID. |
| POST | `/patients` | 201 with the created record. 422 with per-field errors. |
| PUT | `/patients/{id}` | Partial update. Required fields can't be set to null. 400 on empty body. |
| DELETE | `/patients/{id}` | Soft delete: sets `deleted_at`, row is kept. |
| GET | `/patients/{id}/calls` | Transcripts and summaries of calls linked to the patient. |
| GET | `/calls`, `/calls/{call_id}` | Call log with final payloads. |
| GET | `/health` | Checks the database connection. |

Status codes: 200, 201, 400 (malformed JSON, bad UUID, empty update), 404, 422 (validation), 500 (unexpected, logged).

Example:

```bash
curl -s -X POST $API/patients -H 'Content-Type: application/json' -d '{
  "first_name": "Ana", "last_name": "Lopez", "date_of_birth": "07/04/1990", "sex": "Female",
  "phone_number": "(512) 555-0187", "address_line_1": "100 Congress Ave", "city": "Austin",
  "state": "TX", "zip_code": "78701"}'
curl -s "$API/patients?last_name=lopez"
```

Dates are accepted as MM/DD/YYYY (the spec's format) or ISO, and returned as ISO `YYYY-MM-DD`, the JSON convention. Phone numbers are accepted in any common format and stored and returned as 10 digits.

## The voice agent

- Prompt: `app/domains/us_patient/prompt.md`. It is commented throughout with the reason for each instruction. The comments are stripped before the prompt is sent to the model.
- Assistant config: `app/domains/us_patient/assistant.json` (model, voice, transcriber, tools, server URL), pushed with `scripts/push_assistant.py` so the live assistant is reproducible from the repo.
- Tools: `validate_patient_details` (check any subset of fields without saving), `lookup_patient_by_phone`, `create_patient`, `update_patient`, and Vapi's built-in end call tool.

Prompt design notes:

- Short turns, one question at a time, no lists or formatting, numbers spoken in groups, names and emails spelled back letter by letter.
- The phone number is collected early and offered from caller ID, so the returning-patient check happens before the caller spends time on an address.
- Date of birth and phone are validated the moment they are given, so the caller is re-asked immediately instead of at the end.
- The read-back is split into two parts (identity and contact, then address and extras) so each chunk is short enough to follow by ear.
- Updates to an existing record require the caller's date of birth. This stops someone with another person's phone from changing their record, and it is enforced by the tool, not just the prompt.

## Edge cases handled

| Case | Behaviour |
|---|---|
| Future or impossible date of birth | `INVALID_FIELDS`, agent explains and re-asks only the date |
| 3-digit or otherwise invalid phone | Same, with the reason ("needs to be 10 digits") |
| Spelling correction | Spelled letters override; agent confirms only the corrected item |
| Out-of-order answers | Agent keeps everything given and asks only for what's missing |
| Interruptions | Vapi barge-in stops speech; prompt says respond to what was said |
| "Start over" | Agent discards collected data and restarts from the name |
| Caller hangs up mid-call | Nothing is saved before confirmation, so no partial record. Call is logged as `ended_without_save` |
| Repeated or retried save in one call | Idempotent by call ID, no duplicate |
| Database down during save | Agent apologises out loud and says nothing was saved; payload logged to stdout; call marked `save_failed` |
| Returning caller | Lookup by phone, offer to update, verify date of birth first |
| Family sharing a phone | Phone is not unique; the agent asks which person if several match |

## Setup

Requirements: Python 3.11+, a Vapi account, and Postgres for production (SQLite works locally).

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # then fill it in
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --reload
pytest -q
```

To talk to the agent against a local server, expose it with `ngrok http 8000`, set `PUBLIC_BASE_URL` to the ngrok URL and run `python scripts/push_assistant.py`.

Deploying (Render and Neon):

1. Create a Neon project and copy its direct (non-pooled) connection string.
2. On Render, create a Web Service from this repo (Docker runtime), with environment variables `DATABASE_URL` (the Neon string) and `VAPI_WEBHOOK_SECRET`, and health check path `/health`.
3. The Dockerfile runs migrations and the seed on boot. `/health` should report `"database": "ok", "dialect": "postgresql"`.
4. In Vapi, create a Bearer Token credential with the same secret, put its ID in `.env` as `VAPI_CREDENTIAL_ID`, set `PUBLIC_BASE_URL` to the Render URL, and run `python scripts/push_assistant.py`.
5. Attach the assistant to the phone number in the Vapi dashboard.

Any host that runs a Dockerfile and any Postgres works the same way; nothing in the code is Render- or Neon-specific.

## Environment variables

| Variable | Used by | Purpose |
|---|---|---|
| `DATABASE_URL` | server | Postgres in production, SQLite locally |
| `VAPI_WEBHOOK_SECRET` | server, push script | Shared secret checked on every webhook (`Authorization: Bearer`, `X-Webhook-Token` or `X-Vapi-Secret`) |
| `API_KEY` | server | Optional. If set, the REST API requires header `X-API-Key` |
| `LOG_LEVEL` | server | Default `INFO` |
| `VAPI_API_KEY` | push script | Vapi private key |
| `VAPI_CREDENTIAL_ID` | push script | Vapi credential holding the webhook secret |
| `VAPI_ASSISTANT_ID` | push script | Set after the first push so later pushes update instead of create |
| `PUBLIC_BASE_URL` | push script | Public HTTPS URL of the server |

## Observability

Every event is one JSON line on stdout: `call_started`, `tool_call` (with arguments), `tool_result`, `final_payload` (the confirmed data, logged even if the database write fails), `call_ended` (with summary), and errors. The same information is queryable through `/calls`.

## Security

- No secrets in code; all keys come from environment variables.
- Webhooks are rejected without the shared secret (constant-time comparison). Vapi attaches the Bearer credential to tool calls but not to assistant-level messages (call status, end-of-call report), which arrive with an empty `X-Vapi-Secret` header. The push script therefore also sets the secret as a custom `X-Webhook-Token` header on the assistant's server config. Rejected requests are logged with header names and token lengths, never values.
- All input is validated server-side: length limits, character sets, control characters rejected, unknown fields rejected, parameterised queries only.
- The REST API and dashboard are deliberately open so reviewers can query them. Setting `API_KEY` locks the API. This is test data only; it is not a HIPAA-compliant system.

## Known limitations and trade-offs

- Names allow single internal spaces ("Mary Ann", "De La Cruz") in addition to letters, hyphens and apostrophes, because rejecting real names on a call is worse than a slightly looser rule.
- Phone numbers follow NANP rules (area code and exchange can't start with 0 or 1), so made-up numbers like 555-123-4567 are rejected with an explanation.
- "Date of birth not in the future" is enforced in the application, not as a database CHECK, because CURRENT_DATE is not allowed in a CHECK constraint.
- Phone is not unique, by design (families share numbers). Duplicate detection is a prompt-driven lookup, not a hard constraint.
- Speech recognition of spelled letters and emails over a phone line is the weakest link; the agent always spells back to catch errors.
- Identity verification for updates is date of birth only.
- The dashboard has no authentication.

## Next steps

- Spanish: switch transcriber to multilingual and use a bilingual voice when the caller says "Hablo español".
- Appointment scheduling after registration with mock availability.
- Automated end-to-end call tests using Vapi's test suites.
- Authentication for the API and dashboard; audit log of record changes.
