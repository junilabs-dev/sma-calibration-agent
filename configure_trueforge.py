"""
configure_trueforge.py -- wire this project into TrueForge through its HTTP API.

Everything the harness needs -- the MCP tool source, the model provider, the
skill, the sandbox -- is registered here rather than clicked together in the
UI, so a fresh checkout reaches a working agent in one command and the setup
is reviewable in git like the rest of the project.

    python configure_trueforge.py                      # register the MCP server
    python configure_trueforge.py --status             # just report what is configured
    python configure_trueforge.py --model-key sk-...   # + connect a model
    python configure_trueforge.py --skill-repo https://github.com/you/repo
    python configure_trueforge.py --daytona-key dtn_...

Credentials are read from the environment when the flags are omitted:
ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY, and DAYTONA_API_KEY.
Nothing is written to disk by this script -- keys go straight to the local
harness, which stores them in .trueforge-local/.

Two ordering facts worth knowing, both enforced by TrueForge and both
surfaced by --status:
  * Skills execute inside a sandbox, so skills stay disabled until a sandbox
    provider is configured.
  * A skill is fetched from a git remote (the manifest takes a GitHub/GitLab
    URL, a ref and a path) -- it is not read off the local disk, so SKILL.md
    has to be pushed before it can be registered.

Three things that cost other people time, worth knowing before you start:
  * A Daytona key needs BOTH `Sandboxes: Read+Write` AND `Snapshots:
    Read+Write`. On save, TrueForge immediately POSTs to Daytona's snapshots
    endpoint to register its sandbox image; without Snapshots:Write that 403
    is reported as "Daytona rejected the API key -- check the credentials",
    which sends you off checking a key that was fine all along.
  * A model provider manifest must list at least one model. Registering only
    an api_key is a 400.
  * Every response is wrapped in {"data": ...}.
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

MCP_NAME = "sma-calibration"
MCP_URL = os.environ.get("SMA_MCP_URL", "http://localhost:8000/mcp")
SKILL_NAME = "sma-material-calibration"

# manifest type, env var, default upstream model id, local name.
# A provider manifest must list at least one model (`models`, minItems 1) -- a
# provider registered with only an api_key is rejected with a 400.
MODEL_PROVIDERS = {
    # gemini-2.5-flash is on Google's free tier, which is the only one of these
    # three that needs no billing set up. 2.0-flash is not on that list.
    "gemini": ("google-gemini", "GEMINI_API_KEY", "gemini-2.5-flash", "gemini-2.5-flash"),
    "anthropic": ("anthropic", "ANTHROPIC_API_KEY", "claude-sonnet-4-5-20250929", "claude-sonnet-4-5"),
    "openai": ("openai", "OPENAI_API_KEY", "gpt-4o", "gpt-4o"),
}


class ApiError(RuntimeError):
    pass


def call(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        raise ApiError(f"{method} {path} -> HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"cannot reach TrueForge at {BASE} ({e.reason}). Start it with .\\start.ps1") from None


def upsert(kind: str, name: str, manifest: dict) -> str:
    """POST to create, PUT to update if it already exists. Returns what happened."""
    existing = {r.get("name") for r in call("GET", f"/settings/{kind}").get("data", [])}
    if name in existing:
        call("PUT", f"/settings/{kind}", {"manifest": manifest})
        return "updated"
    call("POST", f"/settings/{kind}", {"manifest": manifest})
    return "created"


def capabilities() -> dict:
    return call("GET", "/capabilities").get("data", {})


def report() -> None:
    caps = capabilities()
    print(f"TrueForge  {BASE}")
    for area in ("settings", "sandbox", "skill"):
        c = caps.get(area, {})
        state = "enabled" if c.get("enabled") else "disabled"
        reason = f"  -- {c['reason']}" if c.get("reason") else ""
        print(f"  {area:<9} {state}{reason}")

    for kind, label in (("mcp-servers", "mcp"), ("model-providers", "models"), ("skills", "skills")):
        try:
            rows = call("GET", f"/settings/{kind}").get("data", [])
            names = ", ".join(r.get("name", "?") for r in rows) or "none"
        except ApiError as e:
            names = f"({e})"
        print(f"  {label:<9} {names}")

    # Tools only resolve once the harness has actually reached the MCP server,
    # so this doubles as a connectivity check on server.py.
    try:
        tools = call("GET", f"/mcp-servers/{MCP_NAME}/tools").get("data", [])
        print(f"  tools     {', '.join(t.get('name', '?') for t in tools) or 'none'}")
    except ApiError:
        print("  tools     (not reachable -- is server.py running on :8000?)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="report configuration and exit")
    ap.add_argument("--model", choices=sorted(MODEL_PROVIDERS), default="gemini")
    ap.add_argument("--model-key", help="model provider API key (else read from env)")
    ap.add_argument("--model-id", help="override the upstream model id, e.g. gemini-2.5-pro")
    ap.add_argument("--model-name", help="override the local name the agent refers to")
    ap.add_argument("--skill-repo", help="https://github.com/<owner>/<repo> holding SKILL.md")
    ap.add_argument("--skill-ref", default="main")
    ap.add_argument("--skill-path", help="directory within the repo, if not the root")
    ap.add_argument("--daytona-key", help="Daytona API key (else DAYTONA_API_KEY)")
    args = ap.parse_args()

    try:
        if args.status:
            report()
            return 0

        print(f"configuring {BASE}\n")

        what = upsert("mcp-servers", MCP_NAME, {
            "type": "remote",
            "name": MCP_NAME,
            "url": MCP_URL,
            "description": "SMA constitutive-model calibration: experimental trace, model "
                           "evaluation, and the irreversible commit of a material card.",
        })
        print(f"  mcp server    {what}  ({MCP_URL})")

        provider_type, env_var, default_id, default_name = MODEL_PROVIDERS[args.model]
        key = args.model_key or os.environ.get(env_var)
        if not key and args.model_id:
            # Swapping models on an already-configured provider shouldn't demand
            # the key again. Responses redact it, and PUTting a redacted value
            # keeps the stored one -- so the switch works without handling the
            # secret at all.
            stored = {p.get("name"): p for p in call("GET", "/settings/model-providers").get("data", [])}
            if provider_type in stored:
                key = stored[provider_type]["manifest"]["auth"]["api_key"]
                print(f"  (reusing the stored {provider_type} key)")
        if key:
            model_id = args.model_id or default_id
            what = upsert("model-providers", provider_type, {
                "type": provider_type,
                "auth": {"api_key": key},
                "models": [{
                    "model_id": model_id,
                    "name": args.model_name or default_name,
                    "properties": {},
                }],
            })
            print(f"  model         {what}  ({provider_type} / {model_id})")
        else:
            print(f"  model         skipped  (no --model-key and ${env_var} unset)")

        daytona = args.daytona_key or os.environ.get("DAYTONA_API_KEY")
        if daytona:
            call("PUT", "/settings/sandbox-providers", {"manifest": {
                "type": "daytona",
                "auth": {"api_key": daytona},
                "exec_timeout_ms": 60000,
                "auto_stop_interval_in_minutes": 5,
                "auto_archive_interval_in_minutes": 60,
                "auto_delete_interval_in_minutes": 7200,
            }})
            print("  sandbox       configured  (daytona)")
        else:
            print("  sandbox       skipped  (no --daytona-key and $DAYTONA_API_KEY unset)")

        if args.skill_repo:
            manifest = {
                "type": "git",
                "name": SKILL_NAME,
                "url": args.skill_repo.rstrip("/"),
                "ref": args.skill_ref,
                "description": "How to inverse-identify the 7 parameters of a superelastic SMA "
                               "constitutive model against a noisy tensile-test trace.",
            }
            if args.skill_path:
                manifest["path"] = args.skill_path
            what = upsert("skills", SKILL_NAME, manifest)
            print(f"  skill         {what}  ({args.skill_repo} @ {args.skill_ref})")
        else:
            print("  skill         skipped  (no --skill-repo; skills load from git, not local disk)")

        print()
        report()
        return 0

    except ApiError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
