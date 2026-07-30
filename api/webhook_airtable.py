"""Airtable webhook handler.

Receives notifications when records in the 訂單 table change. Pushes
Telegram messages to the customer based on status flips:

  - 付款狀態 -> 已付款   -> "Payment received, will ship soon"
  - 出貨狀態 -> 已出貨   -> "Your order has shipped"

Uses 備註 to mark which notifications have already been pushed so
Airtable re-fires do not double-message the customer.

Configured in Airtable:
  Automation: "When record updated in 訂單"
  -> Webhook POST to https://<domain>/api/webhook_airtable
  Filter: only fire when 付款狀態 OR 出貨狀態 changed
"""
from http.server import BaseHTTPRequestHandler
import json
import sys
import os
import datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
from _lib import airtable_headers, airtable_update, tg_send, ORDERS_TABLE, BASE_ID
from urllib.request import Request, urlopen
from urllib.error import HTTPError


PAID_MARK = "付款通知已 TG 推播"
SHIPPED_MARK = "出貨通知已 TG 推播"


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


def now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def append_note(record_id: str, mark: str) -> None:
    """Append a notification marker to 備註, preserving any prior text."""
    try:
        latest = fetch_order(record_id)
        if not latest:
            return
        existing = latest.get("fields", {}).get("備註") or ""
        if mark in existing:
            return
        new_note = (existing + ("\n" if existing else "") + f"{mark} {now_iso()}").strip()
        airtable_update(ORDERS_TABLE, record_id, {"備註": new_note})
    except Exception as e:
        print(f"[webhook_airtable] mark note failed: {e}", file=sys.stderr)


def get_note(record: dict) -> str:
    return record.get("fields", {}).get("備註") or ""


class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw else {}

            records = payload.get("records") or []
            for rec in records:
                self._handle_record(rec)
            return self._ok()
        except Exception as e:
            print(f"[webhook_airtable] ERROR: {e}", file=sys.stderr)
            return self._ok()

    def _handle_record(self, rec: dict):
        rec_id = rec.get("id")
        if not rec_id:
            return
        latest = fetch_order(rec_id)
        if not latest:
            return
        fields = latest.get("fields", {})
        order_id = fields.get("訂單編號", "(unknown)")
        tg_user_id = fields.get("TG 用戶 ID")
        payment = fields.get("付款狀態", "")
        shipping = fields.get("出貨狀態", "")
        note = get_note(latest)

        if not tg_user_id:
            print(f"[webhook_airtable] {order_id}: no TG 用戶 ID, skipping", file=sys.stderr)
            return

        # Payment received notification
        if payment == "已付款" and PAID_MARK not in note:
            msg = (
                f"💰 <b>Payment received</b>\n\n"
                f"Order: <code>{order_id}</code>\n\n"
                f"Thanks — our team have confirmed your order already. "
                f"Will arrange the shipping as soon as possible! "
                f"Have a nice day :)"
            )
            try:
                tg_send(int(tg_user_id), msg)
                append_note(rec_id, PAID_MARK)
                print(f"[webhook_airtable] {order_id}: paid-notify sent to {tg_user_id}",
                      file=sys.stderr)
            except Exception as e:
                print(f"[webhook_airtable] {order_id} paid-notify failed: {e}",
                      file=sys.stderr)

        # Shipping notification
        if shipping == "已出貨" and SHIPPED_MARK not in note:
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
                append_note(rec_id, SHIPPED_MARK)
                print(f"[webhook_airtable] {order_id}: shipped-notify sent to {tg_user_id}",
                      file=sys.stderr)
            except Exception as e:
                print(f"[webhook_airtable] {order_id} shipped-notify failed: {e}",
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
