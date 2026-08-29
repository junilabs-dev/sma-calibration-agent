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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8001
HERE = Path(__file__).parent
PROGRESS_PATH = HERE / "progress_state.json"
DASHBOARD_PATH = HERE / "dashboard.html"


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

        else:
            self._send(404, b"not found -- try / or /progress")

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet during a live demo


if __name__ == "__main__":
    print(f"dashboard  ->  http://localhost:{PORT}")
    print(f"data feed  ->  http://localhost:{PORT}/progress")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
