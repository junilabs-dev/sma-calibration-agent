"""
dashboard_api.py -- tiny read-only HTTP endpoint for a browser dashboard.

Deliberately stdlib-only (no Flask/FastAPI) so it's one more thing that
can't break under time pressure. Serves progress_state.json (written by
server.py on every evaluate_model / commit_calibration call) as JSON with
CORS enabled, so a plain HTML/JS dashboard on a different port (or opened
as a local file) can poll it.

This is NOT part of the MCP protocol and the agent never talks to it -- it
only exists so a human-facing dashboard can watch what the agent is doing
from the outside.

Run alongside server.py (which must be running first, in a separate
terminal):
    python dashboard_api.py
Serves http://localhost:8001/progress
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = 8001
PROGRESS_PATH = Path(__file__).parent / "progress_state.json"


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path != "/progress":
            self.send_response(404)
            self._cors()
            self.end_headers()
            return

        if PROGRESS_PATH.exists():
            body = PROGRESS_PATH.read_text()
        else:
            body = json.dumps({"experimental": None, "history": []})

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet during a live demo


if __name__ == "__main__":
    print(f"dashboard_api serving http://localhost:{PORT}/progress")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
