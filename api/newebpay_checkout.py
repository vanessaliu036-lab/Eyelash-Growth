"""POST /api/newebpay_checkout — create an unpaid order + signed NewebPay MPG form.

Body (JSON): name, phone, address, postal, country (KH/MY/SG/VN/ID/OTHER),
countryName (only for OTHER), quantity, quote {rate, ts, sig}.

Prices are recomputed here; nothing money-related from the browser is trusted
except the signed exchange-rate quote.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from _lib import (
    ORDERS_TABLE, airtable_create, airtable_list, find_or_create_customer,
    gen_order_id, now_utc_iso, env, formula_str,
)
from _newebpay import (
    COUNTRIES, MAX_QTY, encrypt_trade_info, gateway_url, shipping_usd,
    to_merchant_order_no, total_usd, trade_sha, usd_to_twd, verify_quote,
)


class BadRequest(Exception):
    pass


class TooMany(Exception):
    pass


# Abuse guard (stateless: counts recent unpaid card orders in Airtable).
MAX_UNPAID_PER_PHONE = 3      # per phone number within the window
MAX_UNPAID_GLOBAL = 30        # all card orders within the window
WINDOW_MINUTES = 15


def _recent_unpaid_filter(extra: str = "") -> str:
    base = (
        'AND({付款狀態}="未付款",FIND("[CARD",{地址}),'
        f"IS_AFTER({{下單日期}},DATEADD(NOW(),-{WINDOW_MINUTES},'minutes'))"
    )
    return base + (("," + extra) if extra else "") + ")"


def check_abuse(phone: str) -> None:
    by_phone = airtable_list(
        ORDERS_TABLE,
        formula=_recent_unpaid_filter(f"{{電話}}={formula_str(phone)}"),
        max_records=MAX_UNPAID_PER_PHONE,
    )
    if len(by_phone) >= MAX_UNPAID_PER_PHONE:
        raise TooMany("too many unpaid attempts, please finish your payment or try again later")
    overall = airtable_list(
        ORDERS_TABLE, formula=_recent_unpaid_filter(), max_records=MAX_UNPAID_GLOBAL,
    )
    if len(overall) >= MAX_UNPAID_GLOBAL:
        raise TooMany("service is busy, please try again in a few minutes")


def _clean(v, limit):
    return str(v or "").strip()[:limit]


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

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 8192:
                raise BadRequest("request too large")
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            body = json.loads(raw) if raw else {}

            # Honeypot: real visitors never fill this hidden field.
            if _clean(body.get("website"), 50):
                raise BadRequest("invalid request")

            name = _clean(body.get("name"), 120)
            phone = _clean(body.get("phone"), 40)
            address = _clean(body.get("address"), 500)
            postal = _clean(body.get("postal"), 20)
            code = _clean(body.get("country"), 10)
            country_name = _clean(body.get("countryName"), 80)
            try:
                qty = int(body.get("quantity"))
            except Exception:
                raise BadRequest("invalid quantity")

            if code not in COUNTRIES or COUNTRIES[code]["method"] != "card":
                raise BadRequest("credit card is not available for this country")
            if not (name and phone and address and postal):
                raise BadRequest("missing required fields")
            if code == "OTHER" and not country_name:
                raise BadRequest("please enter your country")
            if not (1 <= qty <= MAX_QTY):
                raise BadRequest("invalid quantity")

            try:
                rate = verify_quote(body.get("quote") or {})
            except ValueError as e:
                raise BadRequest(str(e))

            usd = total_usd(code, qty)
            twd = usd_to_twd(usd, rate)
            ship = shipping_usd(code, qty)
            country_label = country_name if code == "OTHER" else COUNTRIES[code]["name"]

            check_abuse(phone)

            # --- Airtable: customer + unpaid order -------------------------
            full_address = f"{address}, {postal}, {country_label}"
            customer_id = find_or_create_customer(name, phone, full_address)
            order_id = f"{gen_order_id()}-{random.randint(100, 999)}"
            airtable_create(ORDERS_TABLE, {
                "訂單編號": order_id,
                "下單日期": now_utc_iso(),
                "客戶": [customer_id],
                "電話": phone,
                # The [CARD NT$…] tag lets the notify webhook verify the amount.
                "地址": f"[CARD NT${twd}] {full_address}",
                "訂購數量": qty,
                "金額": usd,
                "付款狀態": "未付款",
                "出貨狀態": "待出貨",
            })

            # --- NewebPay MPG form ----------------------------------------
            host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or ""
            base = f"https://{host}"
            params = {
                "MerchantID": env("NEWEBPAY_MERCHANT_ID"),
                "RespondType": "JSON",
                "TimeStamp": int(time.time()),
                "Version": "2.0",
                "MerchantOrderNo": to_merchant_order_no(order_id),
                "Amt": twd,
                "ItemDesc": f"LA SHAUNNIE Lash Serum x{qty}",
                "ReturnURL": f"{base}/api/newebpay_return",
                "NotifyURL": f"{base}/api/newebpay_notify",
                "ClientBackURL": f"{base}/order.html",
                "LoginType": 0,
                "CREDIT": 1,
            }
            trade_info = encrypt_trade_info(params)
            self._send(200, {
                "action": gateway_url(),
                "fields": {
                    "MerchantID": params["MerchantID"],
                    "TradeInfo": trade_info,
                    "TradeSha": trade_sha(trade_info),
                    "Version": "2.0",
                },
                "orderId": order_id,
                "usd": usd,
                "shippingUsd": ship,
                "twd": twd,
            })
        except BadRequest as e:
            self._send(400, {"error": str(e)})
        except TooMany as e:
            self._send(429, {"error": str(e)})
        except Exception as e:
            print(f"[newebpay_checkout] ERROR: {e}", file=sys.stderr)
            self._send(500, {"error": "could not start payment, please try again"})
