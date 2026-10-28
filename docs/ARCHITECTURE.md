# Architecture notes

The README has the overview. This file explains how to extend the platform.

## Four ideas

1. **A domain is a folder.** Everything specific to a use case (fields, validation, prompt, tools, API routes, assistant config) lives in `app/domains/<name>/` and is exposed as a `DOMAIN` object.
2. **A channel is an adapter.** The voice platform talks to the server through webhooks. `app/channels/vapi/` translates Vapi messages into calls to the core. Another platform (Retell, Twilio, a chat channel) is another adapter with the same core.
3. **Validation lives in one place.** The domain's Pydantic models are used by both the REST API and the tools.
4. **The agent never touches the database.** Tools call the service layer; the REST API calls the same service layer.

## Adding a domain

1. Create `app/domains/<name>/` with `models.py`, `orm.py`, `service.py`, `api.py`, `tools.py`, `prompt.md`, `assistant.json` and an `__init__.py` exposing `DOMAIN`.
2. Import its ORM module in `migrations/env.py` and create a migration.
3. Register it in `app/main.py` with `register_domain(app, <name>.DOMAIN)`.
4. Push a new assistant that points at the same webhook URL.

No change to `core/`, `channels/` or `db/` should be needed. If one is, fix the core properly rather than special-casing a domain.

## Request flow for a tool call

1. Vapi POSTs `{"message": {"type": "tool-calls", ...}}` to `/channels/vapi/webhook` with the shared secret.
2. The adapter checks the secret and extracts each tool call (name, arguments, call ID, caller number).
3. `core.tools.dispatch` runs the domain tool. Any validation error, database error or crash becomes a short message starting with a status word.
4. Save tools record the final payload in the `calls` table and log it to stdout.
5. The adapter returns `{"results": [{"toolCallId", "result"}]}` with HTTP 200.
6. At hang-up, Vapi sends `end-of-call-report`; the transcript and summary are stored on the call row.
