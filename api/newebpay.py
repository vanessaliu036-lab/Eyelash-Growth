"""LA SHAUNNIE NewebPay hosted-card checkout (no card data touches this server).

Credentials are read only from environment variables. This endpoint stays
disabled until the owner configures and approves the LA merchant account.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlencode, urlparse

from api._lib import (
    ORDERS_TABLE, airtable_create, airtable_list, airtable_update,
    find_or_create_customer, now_utc_iso,
)

UNIT_CENTS = 4000  # Preserve the currently published US$40 LA order-page price.
COUNTRIES = {"KH": "Cambodia", "VN": "Vietnam", "SG": "Singapore",
             "MY": "Malaysia", "ID": "Indonesia", "TW": "Taiwan", "HK": "Hong Kong"}
ORDER_RE = re.compile(r"^LA[0-9A-F]{22}$")
GATEWAY_URLS = {
    "test": "https://ccore.newebpay.com/MPG/mpg_gateway",
    "live": "https://core.newebpay.com/MPG/mpg_gateway",
}


def usd_cents(value: str) -> int:
    try:
        cents = Decimal(value) * 100
        if not cents.is_finite() or cents != cents.to_integral_value() or cents < 0:
            raise ValueError("Invalid shipping fee")
        return int(cents)
    except (InvalidOperation, TypeError):
        raise ValueError("Invalid shipping fee")


def quote(country: str, quantity: int) -> dict:
    if country not in COUNTRIES or not isinstance(quantity, int) or not 1 <= quantity <= 10:
        raise ValueError("Invalid destination or quantity")
    shipping_cents = 0 if quantity >= 2 else 300 if country == "KH" else None
    if country != "KH":
        shipping_env = os.environ.get("LA_SHIPPING_USD_" + country, "").strip()
        if shipping_env:
            shipping_cents = usd_cents(shipping_env)
    subtotal_cents = UNIT_CENTS * quantity
    total_cents = subtotal_cents + shipping_cents if shipping_cents is not None else None
    rate_text = os.environ.get("LA_TWD_PER_USD", "").strip()
    try:
        rate = Decimal(rate_text)
        if not rate.is_finite() or rate <= 0 or rate > 1000:
            rate = None
    except (InvalidOperation, TypeError):
        rate = None
    twd = int((Decimal(total_cents) * rate / 100).quantize(Decimal("1"))) if total_cents is not None and rate else None
    configured = (
        os.environ.get("LA_CARD_ENABLED") == "true"
        and os.environ.get("LA_NEWEBPAY_APPROVED_STORE") == "true"
        and bool(os.environ.get("LA_PUBLIC_URL"))
        and bool(os.environ.get("LA_NEWEBPAY_MERCHANT_ID"))
        and len(os.environ.get("LA_NEWEBPAY_HASH_KEY", "").encode()) == 32
        and len(os.environ.get("LA_NEWEBPAY_HASH_IV", "").encode()) == 16
        and rate is not None
    )
    return {
        "country": country, "quantity": quantity,
        "subtotalUsd": f"{subtotal_cents / 100:.2f}",
        "shippingUsd": None if shipping_cents is None else f"{shipping_cents / 100:.2f}",
        "totalUsd": None if total_cents is None else f"{total_cents / 100:.2f}",
        "amountTwd": twd, "currency": "TWD",
        "rate": str(rate) if rate else None,
        "enabled": bool(configured and twd and twd > 0),
    }


def credentials() -> tuple[str, bytes, bytes]:
    merchant = os.environ.get("LA_NEWEBPAY_MERCHANT_ID", "")
    key = os.environ.get("LA_NEWEBPAY_HASH_KEY", "").encode()
    iv = os.environ.get("LA_NEWEBPAY_HASH_IV", "").encode()
    if not re.fullmatch(r"[A-Za-z0-9]{8,20}", merchant) or len(key) != 32 or len(iv) != 16:
        raise ValueError("LA merchant credentials are not configured")
    return merchant, key, iv


def encrypt_trade(params: dict, key: bytes, iv: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    data = urlencode(params).encode("utf-8")
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return (encryptor.update(padded) + encryptor.finalize()).hex()


def trade_sha(hex_value: str, key: bytes, iv: bytes) -> str:
    return hashlib.sha256(b"HashKey=" + key + b"&" + hex_value.encode("ascii") + b"&HashIV=" + iv).hexdigest().upper()


def decode_reply(form: dict, merchant: str, key: bytes, iv: bytes) -> dict:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    hexd = str(form.get("TradeInfo", ""))
    signature = str(form.get("TradeSha", "")).upper()
    if len(hexd) < 32 or len(hexd) % 32 or not re.fullmatch(r"[A-Fa-f0-9]+", hexd):
        raise ValueError("Invalid payment reply")
    if not re.fullmatch(r"[0-9A-F]{64}", signature) or not hmac.compare_digest(trade_sha(hexd, key, iv), signature):
        raise ValueError("Invalid payment signature")
    if form.get("MerchantID") and form["MerchantID"] != merchant:
        raise ValueError("Merchant mismatch")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(bytes.fromhex(hexd)) + decryptor.finalize()
    pad = padded[-1]
    if pad < 1 or pad > 16 or padded[-pad:] != bytes([pad]) * pad:
        raise ValueError("Invalid payment padding")
    reply = json.loads(padded[:-pad].decode("utf-8"))
    result = reply.get("Result")
    if not isinstance(result, dict) or result.get("MerchantID") != merchant:
        raise ValueError("Payment merchant mismatch")
    if form.get("Status") and form["Status"] != reply.get("Status"):
        raise ValueError("Payment status mismatch")
    return reply


def lookup_order(number: str) -> dict | None:
    if not ORDER_RE.fullmatch(number):
        return None
    records = airtable_list(ORDERS_TABLE, formula='{訂單編號}="' + number + '"', max_records=2)
    return records[0] if len(records) == 1 else None


def confirm_payment(reply: dict) -> None:
    if reply.get("Status") != "SUCCESS":
        return
    result = reply["Result"]
    number = str(result.get("MerchantOrderNo", ""))
    trade_no = str(result.get("TradeNo", ""))
    amount = str(result.get("Amt", ""))
    if not ORDER_RE.fullmatch(number) or not re.fullmatch(r"[A-Za-z0-9-]{1,40}", trade_no) or not amount.isdigit():
        raise ValueError("Invalid order details")
    record = lookup_order(number)
    if not record:
        raise ValueError("Order not found")
    fields = record.get("fields", {})
    notes = str(fields.get("備註", ""))
    expected = re.search(r"(?m)^LA_CARD_AMOUNT_TWD=(\d+)$", notes)
    if not expected or int(expected.group(1)) != int(amount):
        raise ValueError("Payment amount mismatch")
    if fields.get("付款狀態") == "已付款":
        if "LA_CARD_TRADE_NO=" + trade_no not in notes:
            raise ValueError("Conflicting payment confirmation")
        return
    if fields.get("付款狀態") != "未付款":
        raise ValueError("Order cannot be confirmed")
    airtable_update(ORDERS_TABLE, record["id"], {
        "付款狀態": "已付款",
        "備註": notes + "\nLA_CARD_TRADE_NO=" + trade_no + "\nLA_CARD_PAID_AT=" + now_utc_iso(),
    })


class handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, query: dict):
        url = "/order.html?" + urlencode(query)
        self.send_response(303)
        self.send_header("Location", url)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        action = (q.get("action") or [""])[0]
        if action == "quote":
            try:
                c = (q.get("country") or ["KH"])[0]
                n = int((q.get("quantity") or ["1"])[0])
                return self.send_json(200, quote(c, n))
            except (ValueError, OverflowError):
                return self.send_json(400, {"error": "Invalid quote"})
        if action == "status":
            number = (q.get("order") or [""])[0]
            if not ORDER_RE.fullmatch(number):
                return self.send_json(400, {"status": "unknown"})
            try:
                record = lookup_order(number)
                value = "unknown" if not record else "paid" if record["fields"].get("付款狀態") == "已付款" else "pending"
                return self.send_json(200, {"status": value})
            except Exception:
                return self.send_json(503, {"status": "unavailable"})
        return self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        action = (parse_qs(urlparse(self.path).query).get("action") or [""])[0]
        if action == "create":
            return self.create_checkout()
        if action in ("notify", "return"):
            return self.payment_callback(action)
        return self.send_json(404, {"error": "Not found"})

    def create_checkout(self):
        host = self.headers.get("X-Forwarded-Host", self.headers.get("Host", ""))
        origin = self.headers.get("Origin", "")
        if origin and urlparse(origin).netloc != host:
            return self.send_json(403, {"error": "Invalid origin"})
        if "application/json" not in self.headers.get("Content-Type", ""):
            return self.send_json(415, {"error": "JSON required"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                return self.send_json(413, {"error": "Invalid request"})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Invalid body")
            name = str(body.get("name", "")).strip()[:100]
            email = str(body.get("email", "")).strip()[:150]
            phone = str(body.get("phone", "")).strip()[:60]
            address = str(body.get("address", "")).strip()[:300]
            country = str(body.get("country", ""))
            quantity = int(body.get("quantity", 0))
            if not name or not phone or len(address) < 5 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                return self.send_json(400, {"error": "Valid contact and delivery details required"})
            pricing = quote(country, quantity)
            if not pricing["enabled"]:
                return self.send_json(503, {"error": "Card payment is not ready for this destination"})
            merchant, key, iv = credentials()
            root = os.environ["LA_PUBLIC_URL"].rstrip("/")
            if not root.startswith("https://") or urlparse(root).path not in ("", "/"):
                raise ValueError("Invalid public site URL")
            customer = find_or_create_customer(name, phone, f"{COUNTRIES[country]} — {address}")
            order_no = "LA" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + secrets.token_hex(4).upper()
            charge_twd = pricing["amountTwd"]
            order = airtable_create(ORDERS_TABLE, {
                "訂單編號": order_no, "下單日期": now_utc_iso(),
                "客戶": [customer], "電話": phone,
                "地址": f"{COUNTRIES[country]} — {address}",
                "訂購數量": quantity, "金額": float(pricing["totalUsd"]),
                "付款狀態": "未付款", "出貨狀態": "待出貨",
                "備註": f"LA_CARD_AMOUNT_TWD={charge_twd}\nLA_CARD_COUNTRY={country}\nLA_CARD_EMAIL={email}\nLA_CARD_USD={pricing['totalUsd']}",
            })
            if not order.get("id"):
                raise ValueError("Failed to save order")
            fields = {
                "MerchantID": merchant, "RespondType": "JSON",
                "TimeStamp": str(int(datetime.now(timezone.utc).timestamp())),
                "Version": "2.0", "MerchantOrderNo": order_no,
                "Amt": str(charge_twd), "ItemDesc": "LA SHAUNNIE Lash Serum",
                "Email": email, "LangType": "en", "CREDIT": "1", "TradeLimit": "900",
                "NotifyURL": root + "/api/newebpay?action=notify",
                "ReturnURL": root + "/api/newebpay?action=return",
                "ClientBackURL": root + "/order.html",
            }
            encrypted = encrypt_trade(fields, key, iv)
            mode = "live" if os.environ.get("LA_NEWEBPAY_MODE") == "live" else "test"
            self.send_json(200, {
                "action": GATEWAY_URLS[mode],
                "fields": {"MerchantID": merchant, "TradeInfo": encrypted, "TradeSha": trade_sha(encrypted, key, iv), "Version": "2.0"},
                "orderNo": order_no, "amountTwd": charge_twd, "currency": "TWD",
            })
        except (ValueError, InvalidOperation):
            self.send_json(400, {"error": "Please check your order details"})
        except Exception as error:
            print("[LA card/create] error:", type(error).__name__)
            self.send_json(503, {"error": "Card checkout is unavailable. Please try again later."})

    def payment_callback(self, action: str):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16000:
                raise ValueError("Invalid callback length")
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8")).items()}
            merchant, key, iv = credentials()
            reply = decode_reply(form, merchant, key, iv)
            if action == "notify":
                confirm_payment(reply)
                return self.send_plain(200, "SUCCESS")
            # A browser return is not proof of payment; only verified server notification changes status.
            order_no = str(reply.get("Result", {}).get("MerchantOrderNo", ""))
            return self.redirect({"payment": "checking", "order": order_no} if ORDER_RE.fullmatch(order_no) else {"payment": "checking"})
        except Exception as error:
            print("[LA card/callback] error:", type(error).__name__)
            if action == "return":
                return self.redirect({"payment": "checking"})
            return self.send_plain(400, "FAIL")

    def send_plain(self, status: int, content: str):
        body = content.encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
