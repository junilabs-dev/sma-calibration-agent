"""
run_agent.py -- drive the calibration agent through TrueForge's API, and handle
the approval gate from the terminal.

The chat UI does all of this too. Doing it over the API instead makes the
human-in-the-loop step legible: when the agent reaches commit_calibration the
harness emits `tool.approval_required` and stops, and nothing proceeds until a
`user.tool_approval` item is posted back. That pause is the whole safety claim
of this project, so it is worth being able to see it happen rather than
trusting that a UI button did the right thing.

    python run_agent.py                  # run, and ask before the commit
    python run_agent.py --auto-approve   # unattended (CI, recorded demo)
    python run_agent.py --deny           # prove the gate actually blocks

Requires .\\start.ps1 and a model registered via configure_trueforge.py.

How the gate is wired: `require_approval_for_tools` on the agent's MCP server
entry defaults to ["@write", "@destructive"], and commit_calibration is
annotated destructiveHint in server.py, so it matches @destructive. The
selector is set explicitly below anyway -- a default that silently changes is
not something a safety gate should depend on.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("TRUEFORGE_URL", "http://localhost:8790")
API = f"{BASE}/api/v1"

AGENT_NAME = "sma-calibrator"
MCP_NAME = "sma-calibration"
SKILL_NAME = "sma-material-calibration"

INSTRUCTIONS = """\
You calibrate a 7-parameter superelastic shape-memory-alloy constitutive model
against a single noisy tensile test, using the sma-calibration tools.

Call get_experimental_data once and keep the trace in context. Then minimise
rmse_pct_of_peak with evaluate_model, treating it as coordinate descent: change
one or two parameters at a time, keep the direction that improves the residual,
reverse and shorten the step when it worsens. Do not guess randomly, and read
the reason string when a call comes back invalid -- it names the parameter to
fix.

Only once the fit is comfortably under the pass threshold, call
commit_calibration with a justification that states the final RMSE and anything
still visibly off. That call is irreversible and a human has to approve it, so
the justification is what they will judge it on.
"""

TASK = ("Calibrate the SMA model against the experimental data, then commit the "
        "result once you are confident in it.")


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:500]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"cannot reach TrueForge at {BASE} ({e.reason}). Run .\\start.ps1")


def pick_model() -> str:
    models = call("GET", "/models").get("data", [])
    if not models:
        raise SystemExit(
            "No model registered. Get a free Gemini key at https://aistudio.google.com then:\n"
            "  python configure_trueforge.py --model-key <key>")
    return models[0]["name"]


def ensure_agent(model_fqn: str, use_skill: bool) -> str:
    mcp_entry = {
        "name": MCP_NAME,
        "enable_tools": ["@all"],
        "require_approval_for_tools": ["@destructive"],
    }
    spec = {
        "model": {"name": model_fqn},
        "instructions": INSTRUCTIONS,
        "mcp_servers": [mcp_entry],
    }
    if use_skill:
        # Skills are fetched into the sandbox, so one cannot be attached without it.
        spec["skills"] = [{"name": SKILL_NAME}]
        spec["config"] = {"sandbox": {"enabled": True}}

    # Sessions reference an agent by name, but the agent endpoints are keyed by
    # id, so an update has to look the id up first.
    existing = {a.get("name"): a.get("id") for a in call("GET", "/agents").get("data", [])}
    if AGENT_NAME in existing:
        call("PUT", f"/agents/{existing[AGENT_NAME]}", {"manifest": spec})
    else:
        call("POST", "/agents", {"name": AGENT_NAME, "manifest": spec})
    return AGENT_NAME


def unwrap(frame: dict) -> dict:
    """SSE frames arrive as {"turn_id": ..., "event": {...}}. Flatten to the event
    with turn_id folded in, so callers can just read ["type"]. Frames are not
    always wrapped, so handle both."""
    inner = frame.get("event")
    if not isinstance(inner, dict):
        return frame
    ev = dict(inner)
    ev.setdefault("turn_id", frame.get("turn_id"))
    return ev


def stream_turn(session_id: str, items: list[dict], previous_turn_id: str | None):
    """Yield decoded SSE events from one turn."""
    body = {"input": items, "stream": True}
    if previous_turn_id:
        body["previous_turn_id"] = previous_turn_id
    req = urllib.request.Request(
        f"{API}/sessions/{session_id}/turns",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    yield unwrap(json.loads(payload))
                except json.JSONDecodeError:
                    continue
    except urllib.error.HTTPError as e:
        raise SystemExit(f"turn failed -> HTTP {e.code}: {e.read().decode()[:500]}")


def describe(ev: dict) -> str | None:
    """Print anything worth watching. Returns an error message if the turn failed,
    which otherwise ends the run in silence -- an invalid model key surfaces only
    here, as turn.done carrying state.status == 'error'."""
    kind = ev.get("type", "")
    if kind == "tool.call":
        print(f"  -> {ev.get('name', '?')}")
    elif kind == "model.message":
        text = (ev.get("content") or "").strip()
        if text:
            print(f"  {text[:300]}")
    elif kind == "turn.done":
        state = ev.get("state") or {}
        if state.get("status") == "error":
            return state.get("message") or "turn failed"
    elif kind == "error":
        return json.dumps(ev)[:300]
    return None


def decide(ev: dict, args) -> dict:
    calls = ev.get("tool_calls", [])
    print("\n" + "=" * 66)
    print("  APPROVAL REQUIRED -- the agent has stopped and is waiting")
    print(f"  thread   {ev.get('thread_id')}")
    for c in calls:
        print(f"  call id  {c.get('id')}")
    print("=" * 66)

    if args.auto_approve:
        print("  --auto-approve: allowing\n")
        return {"status": "allow"}
    if args.deny:
        print("  --deny: refusing\n")
        return {"status": "deny", "reason": "Denied by run_agent.py --deny"}

    while True:
        answer = input("  allow this irreversible commit? [y/N] ").strip().lower()
        if answer in ("y", "yes"):
            return {"status": "allow"}
        if answer in ("", "n", "no"):
            reason = input("  reason for the agent (optional): ").strip()
            return {"status": "deny", "reason": reason or "Rejected by the human reviewer."}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto-approve", action="store_true", help="approve without prompting")
    ap.add_argument("--deny", action="store_true", help="always deny, to prove the gate blocks")
    ap.add_argument("--with-skill", action="store_true",
                    help="attach SKILL.md; needs a sandbox provider and a pushed repo")
    ap.add_argument("--task", default=TASK)
    args = ap.parse_args()

    if args.auto_approve and args.deny:
        raise SystemExit("--auto-approve and --deny are mutually exclusive")

    model = pick_model()
    print(f"model    {model}")
    ensure_agent(model, args.with_skill)
    print(f"agent    {AGENT_NAME}")

    session = call("POST", "/sessions", {"agent": {"name": AGENT_NAME}})["data"]
    session_id = session["id"]
    print(f"session  {session_id}\n")

    items: list[dict] = [{"type": "user.message", "content": args.task}]
    previous_turn_id = None
    approvals = 0

    # Each approval resumes the run as a new turn chained to the last one, so the
    # loop continues until a turn completes without asking for anything.
    while True:
        pending = None
        turn_id = None
        failure = None
        for ev in stream_turn(session_id, items, previous_turn_id):
            if ev.get("type") == "tool.approval_required":
                pending = ev
            turn_id = ev.get("turn_id") or turn_id
            failure = describe(ev) or failure

        if failure:
            print(f"\nturn failed: {failure}")
            if "API key" in failure:
                print("Register a working key:  python configure_trueforge.py --model-key <key>")
                print("Free Gemini key: https://aistudio.google.com")
            return 1

        if not pending:
            break

        approvals += 1
        decision = decide(pending, args)
        previous_turn_id = pending.get("turn_id") or turn_id
        items = [{
            "type": "user.tool_approval",
            "thread_id": pending["thread_id"],
            "tool_call_id": pending["tool_calls"][0]["id"],
            "approval": decision,
        }]

    print(f"\ndone -- {approvals} approval prompt(s)")
    print("dashboard: http://localhost:8001")
    return 0


if __name__ == "__main__":
    sys.exit(main())
