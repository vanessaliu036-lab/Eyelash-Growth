"""Shared helpers for Vercel serverless functions.

All secrets come from os.environ (set in Vercel dashboard, never in code).
"""
from __future__ import annotations

import os
import re
import json
import datetime as dt
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

AIRTABLE_API = "https://api.airtable.com/v0"
TG_API = "https://api.telegram.org/bot{token}/{method}"

# Airtable IDs (public, OK to hard-code — these are not secrets)
BASE_ID = "appOKF4kG5Jf4UGXX"
ORDERS_TABLE = "tblxmyEQSmoZSw2re"
CUSTOMERS_TABLE = "tbldulbkJbvkeYfnB"


def env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"missing env var: {name}")
    return v


def now_utc_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


# --- HTTP helpers ------------------------------------------------------------

def http_json(method: str, url: str, headers: dict, body: Any = None,
              timeout: int = 12) -> dict:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
    req = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} -> {e.code}: {body[:300]}")


def http_download(url: str, timeout: int = 20) -> bytes:
    """Download a URL to raw bytes (used for TG file downloads)."""
    req = Request(url)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def airtable_attach_via_patch(table: str, record_id: str, field: str,
                              file_url: str, filename: str) -> dict:
    """Attach a remote file to an Airtable record by PATCHing the attachment
    field with a [{url, filename}] array. Airtable fetches the URL server-side
    and mirrors the file on its own CDN.

    Why PATCH instead of POST /uploadAttachment? The uploadAttachment endpoint
    does not work with non-ASCII field names (returns NOT_FOUND even when the
    field exists). PATCHing the record with an array works for any field name.
    """
    url = f"{AIRTABLE_API}/{BASE_ID}/{table}/{record_id}"
    return http_json("PATCH", url, airtable_headers(),
                     {"fields": {field: [{"url": file_url, "filename": filename}]}})


# --- Airtable ----------------------------------------------------------------

def airtable_headers() -> dict:
    return {"Authorization": f"Bearer {env('AIRTABLE_TOKEN')}"}


def airtable_list(table: str, formula: Optional[str] = None, max_records: int = 5) -> List[dict]:
    params: dict[str, Any] = {"maxRecords": max_records}
    if formula:
        params["filterByFormula"] = formula
    url = f"{AIRTABLE_API}/{BASE_ID}/{table}?{urlencode(params)}"
    data = http_json("GET", url, airtable_headers())
    return data.get("records", [])


def airtable_create(table: str, fields: dict) -> dict:
    url = f"{AIRTABLE_API}/{BASE_ID}/{table}"
    return http_json("POST", url, airtable_headers(), {"fields": fields})


def airtable_update(table: str, record_id: str, fields: dict) -> dict:
    url = f"{AIRTABLE_API}/{BASE_ID}/{table}/{record_id}"
    return http_json("PATCH", url, airtable_headers(), {"fields": fields})


# --- Telegram ----------------------------------------------------------------

def tg_call(method: str, **params: Any) -> dict:
    token = env("TELEGRAM_BOT_TOKEN")
    url = TG_API.format(token=token, method=method)
    if params:
        url += "?" + urlencode(params)
    return http_json("GET", url, {})


def tg_send(chat_id, text: str, parse_mode: str = "HTML") -> dict:
    return tg_call("sendMessage", chat_id=str(chat_id), text=text,
                   parse_mode=parse_mode, disable_web_page_preview=True)


def tg_get_file_url(file_id: str) -> str:
    """Resolve a TG file_id to a downloadable HTTPS URL (valid ~1h)."""
    info = tg_call("getFile", file_id=file_id)
    path = info.get("result", {}).get("file_path", "")
    if not path:
        raise RuntimeError(f"getFile returned no file_path for {file_id}")
    return f"https://api.telegram.org/file/bot{env('TELEGRAM_BOT_TOKEN')}/{path}"


def find_latest_order_by_tg_user(tg_user_id: int) -> Optional[dict]:
    """Most recent order for this TG user, or None."""
    rows = airtable_list(
        ORDERS_TABLE,
        formula=f"{{TG 用戶 ID}}={int(tg_user_id)}",
        max_records=5,
    )
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("fields", {}).get("下單日期", ""), reverse=True)
    return rows[0]


# --- Order id ---------------------------------------------------------------

def gen_order_id() -> str:
    """ORD-YYYYMMDD-HHMMSS — collision-safe enough for low volume."""
    return "ORD-" + dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")


# --- Order parser (from order.html t.me deep-link) --------------------------

# Format produced by order.html:
#   Hi, I just paid for my LA SHAUNNIE order.
#
#   Name: <name>
#   Phone: <phone>
#   Address: <address>
#   Quantity: <n>
#   Total: $<amount>

ORDER_RE = re.compile(
    r"Name:\s*(?P<name>.+?)\s*\n"
    r"Phone:\s*(?P<phone>.+?)\s*\n"
    r"Address:\s*(?P<address>.+?)\s*\n"
    r"Quantity:\s*(?P<qty>\d+)\s*\n"
    r"Total:\s*\$?(?P<total>[\d.]+)",
    re.IGNORECASE,
)


def parse_order_message(text: str) -> Optional[dict]:
    m = ORDER_RE.search(text)
    if not m:
        return None
    return {
        "name": m.group("name").strip(),
        "phone": m.group("phone").strip(),
        "address": m.group("address").strip(),
        "quantity": int(m.group("qty")),
        "total": float(m.group("total")),
    }


# --- Customer lookup by phone -----------------------------------------------

def find_or_create_customer(name: str, phone: str, address: str) -> str:
    """Return customer record id. Update address if existing record is found."""
    # Escape single quotes in formula
    safe_phone = phone.replace("'", "\\'")
    rows = airtable_list(
        CUSTOMERS_TABLE,
        formula=f"{{電話}}='{safe_phone}'",
        max_records=1,
    )
    if rows:
        rec = rows[0]
        # Update address if changed
        if rec.get("fields", {}).get("地址") != address:
            airtable_update(CUSTOMERS_TABLE, rec["id"], {"地址": address})
        return rec["id"]

    created = airtable_create(CUSTOMERS_TABLE, {
        "客戶姓名": name,
        "電話": phone,
        "地址": address,
    })
    return created["id"]


# --- Order create ------------------------------------------------------------

def create_order_record(customer_id: str, order: dict, tg_user_id: int,
                        tg_username: Optional[str]) -> dict:
    return airtable_create(ORDERS_TABLE, {
        "訂單編號": gen_order_id(),
        "下單日期": now_utc_iso(),
        "客戶": [customer_id],
        "TG 用戶 ID": tg_user_id,
        "電話": order["phone"],
        "地址": order["address"],
        "訂購數量": order["quantity"],
        "金額": order["total"],
        "付款狀態": "已付款",
        "出貨狀態": "待出貨",
    })
