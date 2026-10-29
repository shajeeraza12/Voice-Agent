"""Create or update the Vapi assistant from app/domains/us_patient/assistant.json + prompt.md.

Keeps the live assistant reproducible from the repo: edit the files, run this, call the number.
Uses only the standard library (no extra dependency for one HTTP call).

Usage:
  python scripts/push_assistant.py            # create (first time) or update if VAPI_ASSISTANT_ID is set
  python scripts/push_assistant.py --dry-run  # print the final JSON without sending it (secret masked)
  python scripts/push_assistant.py --check    # show what Vapi actually has stored (never prints the secret)

Needs in .env or the environment: VAPI_API_KEY, PUBLIC_BASE_URL, VAPI_WEBHOOK_SECRET (same value as on the server),
VAPI_CREDENTIAL_ID, and optional VAPI_ASSISTANT_ID.
"""
from __future__ import annotations  # allows "dict | None" hints on Python 3.8 and 3.9

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


HEADERS_BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    # Vapi sits behind Cloudflare, which rejects Python's default "Python-urllib" user agent
    # with error 1010, so send an explicit one.
    "User-Agent": "voice-agent-push/1.0 (+https://github.com/shajeeraza12/Voice-Agent)",
}


def vapi(method: str, path: str, payload: dict | None = None) -> dict:
    key = os.environ.get("VAPI_API_KEY") or sys.exit("VAPI_API_KEY is not set.")
    req = urllib.request.Request(
        f"https://api.vapi.ai{path}", method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={**HEADERS_BASE, "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"Vapi returned {exc.code}: {exc.read().decode(errors='replace')}")


def summarise(a: dict) -> None:
    """Print what Vapi actually stored, without ever printing the secret."""
    secret = os.environ.get("VAPI_WEBHOOK_SECRET", "")

    def server_line(label: str, srv: dict | None) -> None:
        srv = srv or {}
        token = (srv.get("headers") or {}).get("X-Webhook-Token")
        token_state = "missing" if not token else ("matches .env" if token == secret else "SET BUT DIFFERENT from .env")
        print(f"  {label}: url={srv.get('url')} credential={'set' if srv.get('credentialId') else 'none'} X-Webhook-Token={token_state}")

    print(f"assistant {a.get('id')}  name={a.get('name')!r}  updatedAt={a.get('updatedAt')}")
    print(f"  model={(a.get('model') or {}).get('provider')}/{(a.get('model') or {}).get('model')}"
          f"  voice={(a.get('voice') or {}).get('provider')}/{(a.get('voice') or {}).get('voiceId')}"
          f"  transcriber={(a.get('transcriber') or {}).get('provider')}/{(a.get('transcriber') or {}).get('model')}")
    print(f"  serverMessages={a.get('serverMessages')}")
    server_line("assistant server", a.get("server"))
    for tool in (a.get("model") or {}).get("tools") or []:
        name = (tool.get("function") or {}).get("name") or tool.get("type")
        if tool.get("server"):
            server_line(f"tool {name}", tool.get("server"))
    prompt = ((a.get("model") or {}).get("messages") or [{}])[0].get("content", "")
    print(f"  prompt: {len(prompt)} chars, starts {prompt[:60]!r}")


def main() -> None:
    load_env()
    assistant_id = os.environ.get("VAPI_ASSISTANT_ID")
    if "--check" in sys.argv:
        if not assistant_id:
            sys.exit("VAPI_ASSISTANT_ID is not set.")
        summarise(vapi("GET", f"/assistant/{assistant_id}"))
        return
    dry_run = "--dry-run" in sys.argv
    config = build(mask_secret=dry_run)
    if dry_run:
        print(json.dumps(config, indent=2))
        return
    if assistant_id:
        body = vapi("PATCH", f"/assistant/{assistant_id}", config)
        print(f"Updated assistant {body.get('id')}. Vapi now reports:")
    else:
        body = vapi("POST", "/assistant", config)
        print(f"Created assistant {body.get('id')}. Add it to .env as VAPI_ASSISTANT_ID and attach it to your number.")
    summarise(body)


if __name__ == "__main__":
    main()
