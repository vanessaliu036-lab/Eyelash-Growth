"""POST /api/admin/telegram_webhook — register TELEGRAM_WEBHOOK_SECRET with Telegram.

Admin only (Bearer ADMIN_TOKEN). Keeps the webhook URL Telegram already has
(read via getWebhookInfo) and only adds the secret_token, so Telegram starts
sending the X-Telegram-Bot-Api-Secret-Token header that webhook_telegram.py
verifies. The bot token never leaves the server.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _lib import admin_auth, tg_call


class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send(self, code, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        ok, status = admin_auth(self.headers)
        if not ok:
            return self._send(status, {"error": "unauthorized" if status == 401 else "too many attempts, try later"})
        try:
            secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", secret):
                return self._send(400, {"error": "TELEGRAM_WEBHOOK_SECRET is not set (16+ letters/digits/_/-)"})

            info = tg_call("getWebhookInfo").get("result", {})
            url = info.get("url") or ""
            if not url:
                host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or ""
                url = f"https://{host}/api/webhook_telegram"
            if not url.startswith("https://"):
                return self._send(400, {"error": "webhook URL must be https"})

            res = tg_call("setWebhook", url=url, secret_token=secret,
                          allowed_updates=json.dumps(["message", "edited_message"]))
            return self._send(200, {"ok": bool(res.get("ok")), "url": url,
                                    "description": res.get("description", "")})
        except Exception as e:
            print(f"[admin/telegram_webhook] ERROR: {e}", file=sys.stderr)
            return self._send(500, {"error": "failed to update webhook"})
