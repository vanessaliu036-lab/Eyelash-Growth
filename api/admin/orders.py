"""Admin orders API.

GET  /api/admin/orders            -> list all orders (most recent first)
GET  /api/admin/orders?stats=1    -> also include stat aggregates
PATCH /api/admin/orders?id=<rec>  -> update payment / shipping status

Auth: caller must include X-Telegram-User-Id header matching
ADMIN_TG_IDS (comma-separated Vercel env var). Returns 401 otherwise.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import sys

# Make _lib importable (need to walk up to api/ root)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _lib import (
    env, airtable_headers, airtable_list, airtable_update,
    http_json, AIRTABLE_API, ORDERS_TABLE, CUSTOMERS_TABLE,
    tg_send,
)
from urllib.parse import urlparse, parse_qs


def _customer_map(customer_ids: list) -> dict:
    """Batch-load customers to enrich order rows."""
    if not customer_ids:
        return {}
    # Airtable formula: OR(RECORD_ID()='x', RECORD_ID()='y', ...)
    parts = ",".join(f"RECORD_ID()='{cid}'" for cid in customer_ids)
    formula = f"OR({parts})"
    rows = airtable_list(CUSTOMERS_TABLE, formula=formula, max_records=50)
    return {r["id"]: r.get("fields", {}) for r in rows}


def _shape_order(rec: dict, customers: dict) -> dict:
    f = rec.get("fields", {})
    cust_ids = f.get("客戶", [])
    cust = customers.get(cust_ids[0], {}) if cust_ids else {}
    name = cust.get("客戶姓名", "")
    cust_phone = cust.get("電話", "")
    cust_address = cust.get("地址", "")
    # Use customer-table phone/address as authoritative; fall back to order's
    phone = cust_phone or f.get("電話", "")
    address = cust_address or f.get("地址", "")
    # Attachment: pick first screenshot's small thumbnail
    shots = f.get("付款截圖") or []
    screenshot_url = ""
    if shots:
        thumbs = shots[0].get("thumbnails", {})
        screenshot_url = thumbs.get("small", {}).get("url", "") or shots[0].get("url", "")
    return {
        "id": rec["id"],
        "order_id": f.get("訂單編號", ""),
        "order_date": f.get("下單日期", ""),
        "customer_name": name,
        "customer_phone": phone,
        "customer_address": address,
        "tg_user_id": f.get("TG 用戶 ID"),
        "account4": f.get("帳號後四碼", ""),
        "quantity": f.get("訂購數量", 0),
        "amount": f.get("金額", 0),
        "payment_status": f.get("付款狀態", ""),
        "shipping_status": f.get("出貨狀態", ""),
        "tracking_number": f.get("物流編號", ""),
        "notes": f.get("備註", ""),
        "screenshot_url": screenshot_url,
        "has_screenshot": bool(shots),
    }


class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send_json(self, code: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Telegram-User-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, PATCH, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def _check_auth(self) -> bool:
        """Return True if requester is in ADMIN_TG_IDS (comma-separated env).

        Compares X-Telegram-User-Id header against the allowlist. If
        ADMIN_TG_IDS is unset or empty, every request is rejected — fail
        closed.
        """
        allowed_raw = os.environ.get("ADMIN_TG_IDS", "").strip()
        if not allowed_raw:
            print("[admin/orders] ADMIN_TG_IDS env not set — rejecting",
                  file=sys.stderr)
            return False
        try:
            allowed = {int(x.strip()) for x in allowed_raw.split(",") if x.strip()}
        except ValueError:
            print(f"[admin/orders] bad ADMIN_TG_IDS value: {allowed_raw!r}",
                  file=sys.stderr)
            return False
        header = self.headers.get("X-Telegram-User-Id", "").strip()
        try:
            return int(header) in allowed
        except ValueError:
            return False

    def do_OPTIONS(self):
        self._send_json(204, {})

    def do_GET(self):
        if not self._check_auth():
            return self._send_json(401, {"error": "unauthorized"})
        try:
            url = urlparse(self.path)
            q = parse_qs(url.query)

            rows = airtable_list(ORDERS_TABLE, max_records=100)
            # Sort by 下單日期 desc, fallback to record id
            rows.sort(key=lambda r: r.get("fields", {}).get("下單日期", ""), reverse=True)
            cust_ids = []
            for r in rows:
                cust_ids.extend(r.get("fields", {}).get("客戶", []))
            customers = _customer_map(list(set(cust_ids)))
            orders = [_shape_order(r, customers) for r in rows]

            out = {"orders": orders}
            if q.get("stats") == ["1"]:
                total = len(orders)
                paid = sum(1 for o in orders if o["payment_status"] == "已付款")
                revenue = sum(o["amount"] for o in orders if o["payment_status"] == "已付款")
                pending = sum(1 for o in orders
                              if o["payment_status"] == "未付款" and o["has_screenshot"])
                out["stats"] = {
                    "total": total,
                    "paid": paid,
                    "pending": pending,
                    "revenue": round(revenue, 2),
                }
            return self._send_json(200, out)
        except Exception as e:
            print(f"[admin/orders] GET err: {e}", file=sys.stderr)
            return self._send_json(500, {"error": str(e)})

    def do_PATCH(self):
        if not self._check_auth():
            return self._send_json(401, {"error": "unauthorized"})
        try:
            url = urlparse(self.path)
            q = parse_qs(url.query)
            rec_id = (q.get("id") or [""])[0]
            if not rec_id:
                return self._send_json(400, {"error": "missing id"})

            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            body = json.loads(raw) if raw else {}

            allowed = {}
            if "payment_status" in body and body["payment_status"] in ("未付款", "已付款"):
                allowed["付款狀態"] = body["payment_status"]
            if "shipping_status" in body and body["shipping_status"] in ("待出貨", "已出貨", "未出貨"):
                allowed["出貨狀態"] = body["shipping_status"]
            if "tracking_number" in body:
                allowed["物流編號"] = str(body["tracking_number"])[:200]
            if "account4" in body:
                allowed["帳號後四碼"] = str(body["account4"])[:4]
            if "notes" in body:
                allowed["備註"] = str(body["notes"])[:2000]

            if not allowed:
                return self._send_json(400, {"error": "nothing to update"})

            updated = airtable_update(ORDERS_TABLE, rec_id, allowed)
            updated_fields = updated.get("fields", {})

            # If a status flipped, push a Telegram message to the customer.
            tg_pushed = None
            try:
                tg_pushed = self._maybe_notify(rec_id, updated_fields, body)
            except Exception as notify_err:
                print(f"[admin/orders] notify err: {notify_err}", file=sys.stderr)

            return self._send_json(200, {
                "ok": True,
                "fields": updated_fields,
                "tg_pushed": tg_pushed,
            })
        except Exception as e:
            print(f"[admin/orders] PATCH err: {e}", file=sys.stderr)
            return self._send_json(500, {"error": str(e)})

    def _maybe_notify(self, rec_id, updated_fields, body):
        """Push TG if payment or shipping just flipped to a milestone."""
        order_id = updated_fields.get("訂單編號", "(unknown)")
        tg_user_id = updated_fields.get("TG 用戶 ID")
        if not tg_user_id:
            return None

        patched_payment = "payment_status" in body
        patched_shipping = "shipping_status" in body
        if not (patched_payment or patched_shipping):
            return None

        if patched_payment and updated_fields.get("付款狀態") == "已付款":
            msg = (
                f"💰 <b>Payment received</b>\n\n"
                f"Order: <code>{order_id}</code>\n\n"
                f"Thanks — our team have confirmed your order already. "
                f"Will arrange the shipping as soon as possible! "
                f"Have a nice day :)"
            )
            tg_send(int(tg_user_id), msg)
            self._append_notify_note(rec_id, "付款通知已 TG 推播")
            return "paid"

        if patched_shipping and updated_fields.get("出貨狀態") == "已出貨":
            tracking = updated_fields.get("物流編號", "")
            track_line = f"\nTracking: <code>{tracking}</code>" if tracking else ""
            qty = updated_fields.get("訂購數量", "")
            msg = (
                f"📦 <b>Your LA SHAUNNIE order is on the way</b>\n\n"
                f"Order: <code>{order_id}</code>\n"
                f"Quantity: {qty}{track_line}\n\n"
                f"Estimated delivery within 1–2 days. Reach out any time "
                f"via this chat if you need anything 🙏"
            )
            tg_send(int(tg_user_id), msg)
            self._append_notify_note(rec_id, "出貨通知已 TG 推播")
            return "shipped"

        return None

    def _append_notify_note(self, rec_id, mark):
        try:
            target = None
            for r in airtable_list(ORDERS_TABLE, max_records=100):
                if r["id"] == rec_id:
                    target = r
                    break
            cur = (target.get("fields", {}).get("備註") if target else "") or ""
            if mark in cur:
                return
            import datetime as _dt
            stamp = _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            new_note = (cur + ("\n" if cur else "") + f"{mark} {stamp}").strip()
            airtable_update(ORDERS_TABLE, rec_id, {"備註": new_note})
        except Exception as e:
            print(f"[admin/orders] append note failed: {e}", file=sys.stderr)
