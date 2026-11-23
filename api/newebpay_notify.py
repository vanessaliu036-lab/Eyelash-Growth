"""POST /api/newebpay_notify — NewebPay server-to-server payment result.

Verifies TradeSha, decrypts TradeInfo, checks the amount against the order's
[CARD NT$…] tag, then flips 付款狀態 to 已付款 in Airtable.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import sys
from urllib.parse import parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from _lib import ORDERS_TABLE, airtable_list, airtable_update
from _newebpay import (
    decrypt_trade_info, from_merchant_order_no, verify_trade_sha,
)


def _result_of(decrypted: str) -> dict:
    data = json.loads(decrypted)
    res = data.get("Result")
    if isinstance(res, str):  # some responses nest Result as a JSON string
        res = json.loads(res)
    return {"status": data.get("Status"), "result": res or {}}


class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _ok(self, text=b"OK"):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(text)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            form = {k: v[0] for k, v in parse_qs(raw).items()}

            trade_info = form.get("TradeInfo", "")
            if not trade_info or not verify_trade_sha(trade_info, form.get("TradeSha", "")):
                print("[newebpay_notify] bad signature", file=sys.stderr)
                return self._ok(b"ignored")

            parsed = _result_of(decrypt_trade_info(trade_info))
            if parsed["status"] != "SUCCESS":
                return self._ok()

            res = parsed["result"]
            order_id = from_merchant_order_no(str(res.get("MerchantOrderNo", "")))
            amt = str(res.get("Amt", ""))
            if not order_id:
                return self._ok()

            safe = order_id.replace('"', "")
            rows = airtable_list(ORDERS_TABLE, formula=f'{{訂單編號}}="{safe}"', max_records=1)
            if not rows:
                print(f"[newebpay_notify] order not found: {order_id}", file=sys.stderr)
                return self._ok()

            rec = rows[0]
            fields = rec.get("fields", {})
            if fields.get("付款狀態") == "已付款":
                return self._ok()
            if f"[CARD NT${amt}]" not in str(fields.get("地址", "")):
                print(f"[newebpay_notify] amount mismatch for {order_id}: {amt}", file=sys.stderr)
                return self._ok()

            airtable_update(ORDERS_TABLE, rec["id"], {"付款狀態": "已付款"})
            return self._ok()
        except Exception as e:
            print(f"[newebpay_notify] ERROR: {e}", file=sys.stderr)
            # Non-2xx makes NewebPay retry the notification.
            self.send_response(500)
            self.end_headers()

    def do_GET(self):
        self._ok(b"newebpay_notify ok")
