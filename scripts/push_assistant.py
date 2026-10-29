"""Create or update the Vapi assistant from app/domains/us_patient/assistant.json + prompt.md.

Keeps the live assistant reproducible from the repo: edit the files, run this, call the number.
Uses only the standard library (no extra dependency for one HTTP call).

Usage:
  python scripts/push_assistant.py            # create (first time) or update if VAPI_ASSISTANT_ID is set
  python scripts/push_assistant.py --dry-run  # print the final JSON without sending it

Needs in .env or the environment: VAPI_API_KEY, PUBLIC_BASE_URL, VAPI_WEBHOOK_SECRET (same value as on the server),
VAPI_CREDENTIAL_ID, and optional VAPI_ASSISTANT_ID.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = ROOT / "app" / "domains" / "us_patient"


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def build(mask_secret: bool = False) -> dict:
    prompt = (DOMAIN / "prompt.md").read_text(encoding="utf-8")
    prompt = re.sub(r"<!--.*?-->\n?", "", prompt, flags=re.S)       # comments are for humans
    prompt = re.sub(r"\n{3,}", "\n\n", prompt).strip()
    raw = (DOMAIN / "assistant.json").read_text(encoding="utf-8")
    base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not base_url.startswith("https://"):
        sys.exit("PUBLIC_BASE_URL must be the public https URL of the deployed server.")
    raw = raw.replace("${PUBLIC_BASE_URL}", base_url)
    config = json.loads(raw)
    config["model"]["messages"][0]["content"] = prompt
    credential = os.environ.get("VAPI_CREDENTIAL_ID", "")
    # Vapi attaches the credential to tool calls but not to assistant-level messages
    # (status-update, end-of-call-report), so the secret also goes in a custom header.
    secret = os.environ.get("VAPI_WEBHOOK_SECRET", "")
    if not secret:
        sys.exit("VAPI_WEBHOOK_SECRET is not set in .env. Copy it from the server's environment (Render).")
    header_value = "***" if mask_secret else secret

    def fix_server(obj):
        if isinstance(obj, dict):
            if obj.get("credentialId") == "${VAPI_CREDENTIAL_ID}":
                if credential:
                    obj["credentialId"] = credential
                else:
                    obj.pop("credentialId")
            if str(obj.get("url", "")).endswith("/channels/vapi/webhook"):
                obj["headers"] = {"X-Webhook-Token": header_value}
            for v in obj.values():
                fix_server(v)
        elif isinstance(obj, list):
            for v in obj:
                fix_server(v)

    fix_server(config)
    if not credential:
        print("warning: VAPI_CREDENTIAL_ID not set; tool calls will rely on the X-Webhook-Token header only", file=sys.stderr)
    return config


def main() -> None:
    load_env()
    dry_run = "--dry-run" in sys.argv
    config = build(mask_secret=dry_run)
    if dry_run:
        print(json.dumps(config, indent=2))
        return
    key = os.environ.get("VAPI_API_KEY") or sys.exit("VAPI_API_KEY is not set.")
    assistant_id = os.environ.get("VAPI_ASSISTANT_ID")
    url = f"https://api.vapi.ai/assistant/{assistant_id}" if assistant_id else "https://api.vapi.ai/assistant"
    req = urllib.request.Request(
        url, data=json.dumps(config).encode(), method="PATCH" if assistant_id else "POST",
        # Vapi sits behind Cloudflare, which rejects Python's default "Python-urllib" user agent
        # with error 1010, so send an explicit one.
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "voice-agent-push/1.0 (+https://github.com/shajeeraza12/Voice-Agent)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"Vapi returned {exc.code}: {exc.read().decode(errors='replace')}")
    print(("Updated" if assistant_id else "Created") + f" assistant {body.get('id')}")
    if not assistant_id:
        print("Add this to .env as VAPI_ASSISTANT_ID, then attach the assistant to your phone number in the Vapi dashboard.")


if __name__ == "__main__":
    main()
