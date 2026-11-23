"""GET /api/rate -> live USD->TWD rate as a signed quote.

The checkout page shows this rate; /api/newebpay_checkout only accepts a quote
that carries a valid signature (and is <15 min old), so the NT$ amount charged
is exactly the one the customer saw.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _newebpay import make_quote


class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            self._send(200, make_quote())
        except Exception as e:
            print(f"[rate] ERROR: {e}", file=sys.stderr)
            self._send(503, {"error": "exchange rate unavailable"})
