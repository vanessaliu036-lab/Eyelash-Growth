"""Telegram webhook handler.

Receives messages sent to @Eyelash_Web_report_bot, looks for the order.html
deep-link payload (Name/Phone/Address/Quantity/Total), and creates an
Airtable 訂單 record linked to the 客戶 record (matched by phone).

Configured via:
  - TG: setWebhook -> https://<domain>/api/webhook_telegram
  - Vercel env: TELEGRAM_BOT_TOKEN, AIRTABLE_TOKEN
"""
from http.server import BaseHTTPRequestHandler
import json
import sys
import os
import time

# Make _lib importable
sys.path.insert(0, os.path.dirname(__file__))
from _lib import (
    parse_order_message, find_or_create_customer, create_order_record,
    find_latest_order_by_tg_user, tg_get_file_url, airtable_upload_attachment_from_url,
    ORDERS_TABLE,
    tg_send, tg_call,
)


class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # silence default access log
        return

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            update = json.loads(raw) if raw else {}

            # 1. Handle /start — send a quick welcome
            message = update.get("message") or update.get("edited_message")
            if not message:
                return self._ok()

            text = (message.get("text") or "").strip()
            chat_id = message.get("chat", {}).get("id")
            from_user = message.get("from", {})
            tg_user_id = from_user.get("id")
            tg_username = from_user.get("username")

            if text.startswith("/start"):
                tg_send(chat_id,
                        "Hi 👋 I'm the LA SHAUNNIE order bot.\n\n"
                        "Place an order on the website and tap "
                        "<b>“I've Paid · Contact Customer Service”</b>. "
                        "Your order details will arrive here, and we'll "
                        "confirm once payment is verified.\n\n"
                        "Send <code>/help</code> for assistance.")
                return self._ok()

            if text.startswith("/help"):
                tg_send(chat_id,
                        "<b>Commands</b>\n"
                        "/start — welcome\n"
                        "/status — latest order status\n"
                        "/help — this message\n\n"
                        "To place an order, go to the website and tap "
                        "“Contact Customer Service”. Your order will be "
                        "auto-logged here.")
                return self._ok()

            if text.startswith("/status"):
                tg_send(chat_id,
                        "Order status is updated by our team and pushed "
                        "to you automatically when shipped. Hold tight 🙏")
                return self._ok()

            # 2. Look for the order.html payload
            order = parse_order_message(text)
            if not order or not chat_id or not tg_user_id:
                # Not a parseable order — try to be helpful based on what we got
                photos = message.get("photo") or []
                caption = (message.get("caption") or "").strip()
                if photos:
                    try:
                        # Pick the largest photo (last in the array)
                        largest = photos[-1]
                        file_id = largest.get("file_id")
                        file_url = tg_get_file_url(file_id)
                        ext = file_url.rsplit(".", 1)[-1].lower()
                        if ext not in ("jpg", "jpeg", "png", "webp"):
                            ext = "jpg"
                        filename = f"payment_{tg_user_id or 'anon'}_{int(time.time())}.{ext}"

                        # Find this user's most recent order
                        latest = find_latest_order_by_tg_user(tg_user_id) if tg_user_id else None
                        order_id_text = ""
                        if latest:
                            rec_id = latest["id"]
                            fields = latest.get("fields", {})
                            order_id = fields.get("訂單編號", "(no id)")
                            order_id_text = f"\nOrder: <code>{order_id}</code>"
                            try:
                                airtable_upload_attachment_from_url(
                                    ORDERS_TABLE, rec_id, "付款截圖", file_url, filename
                                )
                            except Exception as up_err:
                                # Attachment failed — still acknowledge the message
                                print(f"[webhook_telegram] upload err: {up_err}", file=sys.stderr)
                                tg_send(chat_id,
                                        "🧾 Got the screenshot, but I couldn't attach it to "
                                        "your order record. Our team will follow up manually 🙏")
                                return self._ok()
                        else:
                            # No prior order from this TG user — store on its own
                            tg_send(chat_id,
                                    "🧾 Got your screenshot. We don't see a recent order from "
                                    "this account — our team will follow up to link it 🙏")
                            return self._ok()

                        tg_send(chat_id,
                                f"✅ <b>Payment screenshot received</b>{order_id_text}\n\n"
                                f"Thanks — our team will verify it and confirm your order shortly. "
                                f"Hang tight 🙏")
                    except Exception as photo_err:
                        print(f"[webhook_telegram] photo err: {photo_err}", file=sys.stderr)
                        tg_send(chat_id,
                                "🧾 Got your screenshot, but something went wrong saving it. "
                                "Our team will follow up manually 🙏")
                    return self._ok()
                elif caption:
                    tg_send(chat_id,
                            "Got it ✉️ If you're placing an order, please use "
                            "the website's “Contact Customer Service” button "
                            "so I can capture your details automatically.")
                elif text and not text.startswith("/"):
                    tg_send(chat_id,
                            "Got it ✉️ If you're placing an order, please use "
                            "the website's “Contact Customer Service” button "
                            "so I can capture your details automatically.")
                return self._ok()

            # 3. Build the records
            customer_id = find_or_create_customer(
                order["name"], order["phone"], order["address"]
            )
            record = create_order_record(customer_id, order, tg_user_id, tg_username)

            order_id = record["fields"].get("訂單編號", "(unknown)")

            tg_send(chat_id,
                    f"✅ <b>Order received</b>\n\n"
                    f"Order ID: <code>{order_id}</code>\n"
                    f"Quantity: {order['quantity']}\n"
                    f"Total: ${order['total']:.2f}\n\n"
                    f"Our team will verify your payment and confirm shortly. "
                    f"You'll get a Telegram message here when your order ships. "
                    f"Send your payment screenshot if you haven't already 🙏")

            return self._ok()

        except Exception as e:
            # Log to stderr for Vercel function logs
            print(f"[webhook_telegram] ERROR: {e}", file=sys.stderr)
            # Best-effort: notify the customer something went wrong
            try:
                if "update" in dir() or "update" in locals():
                    chat_id = update.get("message", {}).get("chat", {}).get("id")
                    if chat_id:
                        tg_send(chat_id,
                                "Sorry — I couldn't log your order automatically. "
                                "Please resend via the website button and we'll "
                                "pick it up manually.")
            except Exception:
                pass
            return self._ok()  # Always 200 — TG retries on non-2xx

    def do_GET(self):
        # Lightweight health check
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"webhook_telegram ok")

    def _ok(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")
