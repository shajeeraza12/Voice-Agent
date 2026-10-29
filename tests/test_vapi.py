import json

from app.core.calls import Call
from app.db.session import SessionLocal
from app.settings import settings


def tool_message(name, args, call_id="vapi-call-1", as_string=False):
    return {"message": {
        "type": "tool-calls",
        "call": {"id": call_id, "customer": {"number": "+14155550142"}},
        "toolCallList": [{"id": "tc_1", "type": "function",
                          "function": {"name": name, "arguments": json.dumps(args) if as_string else args}}],
    }}


def test_tool_call_round_trip(client, valid_patient):
    r = client.post("/channels/vapi/webhook", json=tool_message("create_patient", {**valid_patient, "caller_confirmed": True}))
    assert r.status_code == 200
    result = r.json()["results"][0]
    assert result["toolCallId"] == "tc_1" and result["result"].startswith("SAVED")


def test_string_arguments_and_legacy_shape(client):
    body = {"message": {
        "type": "tool-calls", "call": {"id": "c2"},
        "toolWithToolCallList": [{"type": "function", "function": {"name": "validate_patient_details"},
                                  "toolCall": {"id": "tc_9", "function": {"name": "validate_patient_details",
                                                                           "arguments": json.dumps({"phone_number": "555"})}}}],
    }}
    r = client.post("/channels/vapi/webhook", json=body)
    assert r.json()["results"][0]["result"].startswith("INVALID_FIELDS")


def test_secret_enforced(client, monkeypatch):
    monkeypatch.setattr(settings, "vapi_webhook_secret", "s3cret")
    msg = tool_message("validate_patient_details", {"state": "CA"})
    assert client.post("/channels/vapi/webhook", json=msg).status_code == 401
    assert client.post("/channels/vapi/webhook", json=msg, headers={"X-Vapi-Secret": "wrong"}).status_code == 401
    assert client.post("/channels/vapi/webhook", json=msg, headers={"X-Vapi-Secret": "s3cret"}).status_code == 200
    assert client.post("/channels/vapi/webhook", json=msg, headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_call_lifecycle_without_save(client):
    client.post("/channels/vapi/webhook", json={"message": {"type": "status-update", "status": "in-progress",
                                                            "call": {"id": "hangup-call"}}})
    client.post("/channels/vapi/webhook", json={"message": {
        "type": "end-of-call-report", "endedReason": "customer-ended-call", "call": {"id": "hangup-call"},
        "artifact": {"transcript": "AI: Hi\nUser: bye"}, "analysis": {"summary": "Caller hung up early."}}})
    with SessionLocal() as s:
        call = s.get(Call, "hangup-call")
        assert call.status == "ended_without_save" and call.transcript.startswith("AI:")


def test_end_of_call_keeps_saved_status_and_links_patient(client, valid_patient):
    client.post("/channels/vapi/webhook", json=tool_message("create_patient", {**valid_patient, "caller_confirmed": True}))
    client.post("/channels/vapi/webhook", json={"message": {
        "type": "end-of-call-report", "endedReason": "assistant-ended-call", "call": {"id": "vapi-call-1"},
        "artifact": {"transcript": "full transcript"}, "analysis": {"summary": "Registered Jane Doe."}}})
    pid = client.get("/patients").json()["data"][0]["patient_id"]
    calls = client.get(f"/patients/{pid}/calls").json()["data"]
    assert calls[0]["status"] == "saved" and calls[0]["summary"] == "Registered Jane Doe."
    assert client.get("/calls").json()["data"][0]["final_payload"]["first_name"] == "Jane"


def test_other_messages_ignored(client):
    assert client.post("/channels/vapi/webhook", json={"message": {"type": "speech-update"}}).json() == {}


def test_either_header_is_enough(client, monkeypatch):
    monkeypatch.setattr(settings, "vapi_webhook_secret", "s3cret")
    msg = {"message": {"type": "speech-update"}}
    # A wrong Authorization header must not hide a correct X-Vapi-Secret, and vice versa.
    assert client.post("/channels/vapi/webhook", json=msg,
                       headers={"Authorization": "Bearer other", "X-Vapi-Secret": "s3cret"}).status_code == 200
    assert client.post("/channels/vapi/webhook", json=msg,
                       headers={"Authorization": "Bearer s3cret", "X-Vapi-Secret": "other"}).status_code == 200
    assert client.post("/channels/vapi/webhook", json=msg,
                       headers={"Authorization": "Bearer other", "X-Vapi-Secret": "other"}).status_code == 401


def test_custom_webhook_token_header(client, monkeypatch):
    # Vapi's end-of-call report arrives with an empty X-Vapi-Secret and no Authorization header;
    # the secret comes through the X-Webhook-Token header set in the assistant's server.headers.
    monkeypatch.setattr(settings, "vapi_webhook_secret", "s3cret")
    msg = {"message": {"type": "end-of-call-report", "call": {"id": "c-token"}, "endedReason": "customer-ended-call"}}
    assert client.post("/channels/vapi/webhook", json=msg, headers={"X-Vapi-Secret": ""}).status_code == 401
    assert client.post("/channels/vapi/webhook", json=msg,
                       headers={"X-Vapi-Secret": "", "X-Webhook-Token": "s3cret"}).status_code == 200


def test_summary_written_when_vapi_sends_none(client):
    client.post("/channels/vapi/webhook", json={"message": {
        "type": "end-of-call-report", "endedReason": "customer-ended-call", "call": {"id": "no-summary"},
        "artifact": {"transcript": "AI: Hi\nUser: Andrew\nAI: Spell it?\nUser: bye"}, "analysis": {"summary": ""}}})
    with SessionLocal() as s:
        call = s.get(Call, "no-summary")
        assert call.summary == "Ended without saving a record after 2 caller turns (customer-ended-call)."
