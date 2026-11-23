"""POST /api/newebpay_return — where the customer's browser lands after paying.

NewebPay POSTs the result to ReturnURL, which a static page cannot receive, so
this endpoint just redirects to order.html with a status flag. It never marks
an order paid (only the signed server-to-server notify does that).
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import sys
from urllib.parse import parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from _newebpay import decrypt_trade_info, verify_trade_sha


class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _redirect(self, state):
        self.send_response(303)
        self.send_header("Location", f"/order.html?payment={state}")
        self.end_headers()

    def do_POST(self):
        state = "failed"
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            form = {k: v[0] for k, v in parse_qs(raw).items()}
            trade_info = form.get("TradeInfo", "")
            if trade_info and verify_trade_sha(trade_info, form.get("TradeSha", "")):
                data = json.loads(decrypt_trade_info(trade_info))
                if data.get("Status") == "SUCCESS":
                    state = "success"
        except Exception as e:
            print(f"[newebpay_return] ERROR: {e}", file=sys.stderr)
        self._redirect(state)

    def do_GET(self):
        self._redirect("failed")
