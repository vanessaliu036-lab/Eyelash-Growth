"""Airtable webhook handler.

Receives notifications when records in the 訂單 table change. When
出貨狀態 flips to "已出貨", push a Telegram message to the customer
using their stored TG 用戶 ID.

Configured in Airtable:
  Automation: "When record updated in 訂單 (出貨狀態 changed to 已出貨)"
  -> Webhook POST to https://<domain>/api/webhook_airtable
"""
from http.server import BaseHTTPRequestHandler
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from _lib import airtable_headers, airtable_update, tg_send, ORDERS_TABLE, BASE_ID
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def fetch_order(record_id: str) -> "dict | None":
    url = f"https://api.airtable.com/v0/{BASE_ID}/{ORDERS_TABLE}/{record_id}"
    try:
        req = Request(url, headers=airtable_headers())
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[webhook_airtable] fetch failed {e.code}: {body[:200]}", file=sys.stderr)
        return None


def mark_notified(record_id: str) -> None:
    """Write 備註 to record so we know we already pushed the TG message,
    preventing duplicate notifications if Airtable re-fires the webhook."""
    try:
        airtable_update(ORDERS_TABLE, record_id, {
            "備註": (f"出貨通知已 TG 推播 {__import__('datetime').datetime.utcnow().isoformat()}Z")
        })
    except Exception as e:
        print(f"[webhook_airtable] mark_notified failed: {e}", file=sys.stderr)


def has_been_notified(record: dict) -> bool:
    note = (record.get("fields", {}).get("備註") or "")
    return "出貨通知已 TG 推播" in note


class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw else {}

            # Airtable webhook format: { "base": {...}, "webhook": {...},
            # "actionMetadata": {...}, "records": [...] }
            records = payload.get("records") or []
            for rec in records:
                self._handle_record(rec)
            return self._ok()
        except Exception as e:
            print(f"[webhook_airtable] ERROR: {e}", file=sys.stderr)
            return self._ok()  # 200 to prevent Airtable retry storm

    def _handle_record(self, rec: dict):
        fields = rec.get("fields", {})
        order_id = fields.get("訂單編號", "(unknown)")
        ship_status = fields.get("出貨狀態", "")
        tg_user_id = fields.get("TG 用戶 ID")

        if ship_status != "已出貨":
            return
        if not tg_user_id:
            print(f"[webhook_airtable] {order_id}: no TG 用戶 ID, skipping", file=sys.stderr)
            return

        # Re-fetch the record to get the latest 備註 (Airtable webhook payload
        # can be stale on notes).
        latest = fetch_order(rec.get("id"))
        if not latest:
            return
        if has_been_notified(latest):
            print(f"[webhook_airtable] {order_id}: already notified, skipping",
                  file=sys.stderr)
            return

        qty = fields.get("訂購數量", "")
        msg = (
            f"📦 <b>Your LA SHAUNNIE order has shipped</b>\n\n"
            f"Order ID: <code>{order_id}</code>\n"
            f"Quantity: {qty}\n\n"
            f"Thank you for your order! Our team will message you again once "
            f"delivery is confirmed. Reach out any time via this chat."
        )
        try:
            tg_send(int(tg_user_id), msg)
        except Exception as e:
            print(f"[webhook_airtable] TG send failed for {order_id}: {e}",
                  file=sys.stderr)
            return

        mark_notified(rec.get("id"))
        print(f"[webhook_airtable] {order_id}: notified TG user {tg_user_id}",
              file=sys.stderr)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"webhook_airtable ok")

    def _ok(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")
