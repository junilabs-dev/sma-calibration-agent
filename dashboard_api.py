"""
dashboard_api.py -- serves the dashboard and its data feed on one port.

Deliberately stdlib-only (no Flask/FastAPI) so it's one more thing that
can't break under time pressure. Two routes:

    /            -> dashboard.html
    /progress    -> progress_state.json, written by server.py on every
                    evaluate_model / commit_calibration call

Serving both from one origin means the page fetches /progress same-origin,
so there is no second port to start and no CORS or file:// fetch problem to
debug during a demo. CORS is still sent, so opening dashboard.html straight
off disk keeps working.

Threaded on purpose: the page polls once a second, and a single-threaded
HTTPServer blocks every other request behind one slow client -- which looks
exactly like "the dashboard is down".

This is NOT part of the MCP protocol and the agent never talks to it -- it
only exists so a human-facing dashboard can watch what the agent is doing
from the outside.

Run alongside server.py (which must be running first, in a separate
terminal):
    python dashboard_api.py
Serves http://localhost:8001
"""

import json
import subprocess
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8001
HERE = Path(__file__).parent
PROGRESS_PATH = HERE / "progress_state.json"
DASHBOARD_PATH = HERE / "dashboard.html"
TRUEFORGE = "http://localhost:8790"

# Handshake files run_agent.py uses when it has no terminal to ask at: it writes
# the pending tool call, then waits for a decision written here.
PENDING_PATH = HERE / "approval_pending.json"
DECISION_PATH = HERE / "approval_decision.json"

# The one process POST /run is allowed to start, if it isn't already running.
_agent: "subprocess.Popen | None" = None


def _tf(path: str):
    """GET one TrueForge endpoint, or None. Best-effort throughout: the dashboard
    stays usable when the harness is down, so an unreachable harness is a state
    to display, not an error to raise."""
    try:
        with urllib.request.urlopen(f"{TRUEFORGE}/api/v1{path}", timeout=3) as r:
            return json.loads(r.read()).get("data")
    except Exception:
        return None


def _meta() -> dict:
    """What the dashboard shows about the harness driving the run.

    The agent, the session, the tool registration and the approval gate all
    belong to TrueForge; this dashboard only watches. Reading these back from
    the harness rather than restating them locally means the panel goes blank
    when the harness is actually gone, instead of asserting a state it cannot
    see."""
    out = {
        "version": "0.1.0",
        "model": None,
        "agent_running": _agent is not None and _agent.poll() is None,
        "harness": {"reachable": False, "agent": None, "session": None, "tools": [], "sessions": 0},
    }

    models = _tf("/models")
    if models:
        out["model"] = models[0].get("name")

    caps = _tf("/capabilities")
    h = out["harness"]
    if caps is not None:
        h["reachable"] = True
        h["sandbox"] = bool(caps.get("sandbox", {}).get("enabled"))
        h["skills"] = bool(caps.get("skill", {}).get("enabled"))

    agents = _tf("/agents")
    if agents:
        h["agent"] = agents[0].get("name")

    sessions = _tf("/sessions")
    if sessions:
        h["sessions"] = len(sessions)
        h["session"] = sessions[0].get("id")

    tools = _tf("/mcp-servers/sma-calibration/tools")
    if tools:
        h["tools"] = [t.get("name") for t in tools if t.get("name")]

    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body=b"", content_type="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        route = self.path.split("?")[0]

        if route == "/progress":
            if PROGRESS_PATH.exists():
                body = PROGRESS_PATH.read_bytes()
            else:
                body = json.dumps({"experimental": None, "history": []}).encode()
            self._send(200, body, "application/json")

        elif route in ("/", "/dashboard.html"):
            if not DASHBOARD_PATH.exists():
                self._send(404, b"dashboard.html not found next to dashboard_api.py")
                return
            self._send(200, DASHBOARD_PATH.read_bytes(), "text/html; charset=utf-8")

        elif route == "/health":
            self._send(200, json.dumps({
                "ok": True,
                "has_progress": PROGRESS_PATH.exists(),
            }).encode(), "application/json")

        elif route == "/meta":
            self._send(200, json.dumps(_meta()).encode(), "application/json")

        elif route == "/pending":
            body = PENDING_PATH.read_bytes() if PENDING_PATH.exists() else b"{}"
            self._send(200, body, "application/json")

        else:
            self._send(404, b"not found -- try / or /progress")

    def do_POST(self):
        global _agent
        route = self.path.split("?")[0]

        if route == "/decide":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                want = json.loads(self.rfile.read(n) or b"{}").get("status")
            except json.JSONDecodeError:
                want = None
            if want not in ("allow", "deny"):
                self._send(400, json.dumps({"error": "status must be allow or deny"}).encode(), "application/json")
                return
            DECISION_PATH.write_text(json.dumps({"status": want}))
            self._send(200, json.dumps({"recorded": want}).encode(), "application/json")
            return

        if route != "/run":
            self._send(404, b"not found")
            return

        # Bound to 127.0.0.1, takes nothing from the request, and runs one fixed
        # argv -- the button is a convenience, not an arbitrary exec surface.
        # Deliberately no --auto-approve: started this way the agent still stops
        # at commit_calibration and waits for a decision posted to /decide, so
        # the button cannot push anything through the gate.
        if _agent is not None and _agent.poll() is None:
            self._send(409, json.dumps({"error": "already running"}).encode(), "application/json")
            return
        PENDING_PATH.unlink(missing_ok=True)
        DECISION_PATH.unlink(missing_ok=True)
        try:
            _agent = subprocess.Popen(
                [sys.executable, str(HERE / "run_agent.py")],
                cwd=str(HERE),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            self._send(500, json.dumps({"error": str(e)[:120]}).encode(), "application/json")
            return
        self._send(202, json.dumps({"started": True, "pid": _agent.pid}).encode(), "application/json")

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet during a live demo


if __name__ == "__main__":
    print(f"dashboard  ->  http://localhost:{PORT}")
    print(f"data feed  ->  http://localhost:{PORT}/progress")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
