"""NewebPay (藍新金流) MPG helpers + shared pricing rules + live USD->TWD quote.

All secrets come from os.environ (NEWEBPAY_MERCHANT_ID / NEWEBPAY_HASH_KEY /
NEWEBPAY_HASH_IV). Set NEWEBPAY_ENV=test to use the sandbox gateway; any other
value (or unset) uses the production gateway.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from _lib import env

# --- Pricing (single source of truth on the server) -------------------------

UNIT_PRICE_USD = 40
MAX_QTY = 99

# method: "aba" (QR + Telegram) or "card" (NewebPay). free_from: bottles needed
# for free shipping (None = never free). Shipping is charged once per order.
COUNTRIES = {
    "KH": {"name": "Cambodia", "method": "aba", "fee": 6, "free_from": 2},
    "MY": {"name": "Malaysia", "method": "card", "fee": 6, "free_from": 2},
    "SG": {"name": "Singapore", "method": "card", "fee": 6, "free_from": 2},
    "VN": {"name": "Vietnam", "method": "card", "fee": 6, "free_from": 2},
    "ID": {"name": "Indonesia", "method": "card", "fee": 6, "free_from": 2},
    "OTHER": {"name": "Other country", "method": "card", "fee": 10, "free_from": None},
}


def shipping_usd(country_code: str, qty: int) -> int:
    cfg = COUNTRIES[country_code]
    if cfg["free_from"] is not None and qty >= cfg["free_from"]:
        return 0
    return cfg["fee"]


def total_usd(country_code: str, qty: int) -> int:
    return UNIT_PRICE_USD * qty + shipping_usd(country_code, qty)


def usd_to_twd(usd_amount: int, rate: float) -> int:
    """Round UP to a whole NT$ (NewebPay Amt must be an integer)."""
    return int(math.ceil(Decimal(str(usd_amount)) * Decimal(str(rate))))


# --- Live exchange rate + signed quote ---------------------------------------

RATE_SOURCES = (
    ("https://open.er-api.com/v6/latest/USD", lambda d: d["rates"]["TWD"]),
    ("https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
     lambda d: d["usd"]["twd"]),
)

QUOTE_MAX_AGE = 15 * 60  # seconds the displayed rate stays valid


def fetch_usd_twd() -> float:
    last_err: Optional[Exception] = None
    for url, pick in RATE_SOURCES:
        try:
            req = Request(url, headers={"User-Agent": "la-shaunnie-checkout"})
            with urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            rate = float(pick(data))
            if 20 < rate < 50:  # sanity range for USD/TWD
                return round(rate, 4)
            last_err = RuntimeError(f"rate out of range: {rate}")
        except Exception as e:  # try next source
            last_err = e
    raise RuntimeError(f"exchange rate unavailable: {last_err}")


def _quote_sig(rate: float, ts: int) -> str:
    msg = f"{rate:.4f}|{ts}".encode()
    return hmac.new(env("NEWEBPAY_HASH_KEY").encode(), msg, hashlib.sha256).hexdigest()


def make_quote() -> dict:
    rate = fetch_usd_twd()
    ts = int(time.time())
    return {"rate": rate, "ts": ts, "sig": _quote_sig(rate, ts)}


def verify_quote(q: dict) -> float:
    """Return the rate if the quote is authentic and fresh, else raise ValueError."""
    try:
        rate = float(q["rate"])
        ts = int(q["ts"])
        sig = str(q["sig"])
    except Exception:
        raise ValueError("invalid exchange-rate quote")
    if not hmac.compare_digest(sig, _quote_sig(rate, ts)):
        raise ValueError("invalid exchange-rate quote")
    if time.time() - ts > QUOTE_MAX_AGE:
        raise ValueError("exchange rate expired, please refresh")
    return rate


# --- NewebPay encryption ------------------------------------------------------

def gateway_url() -> str:
    if os.environ.get("NEWEBPAY_ENV", "").strip().lower() == "test":
        return "https://ccore.newebpay.com/MPG/mpg_gateway"
    return "https://core.newebpay.com/MPG/mpg_gateway"


def _key_iv():
    return env("NEWEBPAY_HASH_KEY").encode("utf-8"), env("NEWEBPAY_HASH_IV").encode("utf-8")


def encrypt_trade_info(params: dict) -> str:
    key, iv = _key_iv()
    raw = urlencode(params).encode("utf-8")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(pad(raw, 32)).hex()


def decrypt_trade_info(trade_info_hex: str) -> str:
    key, iv = _key_iv()
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plain = cipher.decrypt(bytes.fromhex(trade_info_hex))
    return unpad(plain, 32).decode("utf-8")


def trade_sha(trade_info_hex: str) -> str:
    key, iv = _key_iv()
    s = f"HashKey={key.decode()}&{trade_info_hex}&HashIV={iv.decode()}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest().upper()


def verify_trade_sha(trade_info_hex: str, received_sha: str) -> bool:
    return hmac.compare_digest(trade_sha(trade_info_hex), (received_sha or "").upper())


# --- Order number mapping ------------------------------------------------------
# Airtable keeps "ORD-20261123-143000-123"; NewebPay only allows [A-Za-z0-9_].

def to_merchant_order_no(order_id: str) -> str:
    return order_id.replace("-", "_")


def from_merchant_order_no(merchant_order_no: str) -> str:
    return merchant_order_no.replace("_", "-")
