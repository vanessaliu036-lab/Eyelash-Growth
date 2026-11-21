"""Offline tests: no merchant token, real charge, or Airtable access required."""
import json
import os
import unittest
from unittest.mock import patch
from api import newebpay as payment

class QuoteTests(unittest.TestCase):
    def test_local_price_and_free_shipping(self):
        with patch.dict(os.environ, {}, clear=True):
            one = payment.quote("KH", 1)
            two = payment.quote("KH", 2)
        self.assertEqual(one["totalUsd"], "43.00")
        self.assertEqual(two["totalUsd"], "80.00")
        self.assertFalse(one["enabled"])

    def test_overseas_shipping_is_not_assumed_free(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(payment.quote("VN", 2)["totalUsd"])
            self.assertIsNone(payment.quote("SG", 1)["shippingUsd"])

    def test_overseas_configured_quote(self):
        with patch.dict(os.environ, {"LA_SHIPPING_USD_VN": "8.00", "LA_TWD_PER_USD": "30"}, clear=True):
            q = payment.quote("VN", 1)
        self.assertEqual(q["totalUsd"], "48.00")
        self.assertEqual(q["amountTwd"], 1440)
        self.assertFalse(q["enabled"])

    def test_invalid_quantities_rejected(self):
        for n in (0, 11, -1):
            with self.assertRaises(ValueError):
                payment.quote("KH", n)

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.merchant = "TESTMERCHANT"
        self.key = b"12345678901234567890123456789012"
        self.iv = b"1234567890123456"

    def test_signed_reply_and_tamper_rejection(self):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding
        payload = json.dumps({"Status": "SUCCESS", "Result": {
            "MerchantID": self.merchant, "MerchantOrderNo": "LA" + "A" * 22,
            "Amt": "1290", "TradeNo": "T12345"}}).encode()
        padder = padding.PKCS7(128).padder()
        padded = padder.update(payload) + padder.finalize()
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(self.iv)).encryptor()
        cipher_hex = (cipher.update(padded) + cipher.finalize()).hex()
        form = {
            "TradeInfo": cipher_hex,
            "TradeSha": payment.trade_sha(cipher_hex, self.key, self.iv),
            "MerchantID": self.merchant, "Status": "SUCCESS",
        }
        self.assertEqual(payment.decode_reply(form, self.merchant, self.key, self.iv)["Result"]["Amt"], "1290")
        form["TradeSha"] = "A" * 64
        with self.assertRaises(ValueError):
            payment.decode_reply(form, self.merchant, self.key, self.iv)

    def test_payment_marking_checks_amount(self):
        number = "LA" + "A" * 22
        record = {"id": "rec123", "fields": {
            "付款狀態": "未付款", "備註": "LA_CARD_AMOUNT_TWD=1290\nLA_CARD_COUNTRY=KH",
        }}
        reply = {"Status": "SUCCESS", "Result": {
            "MerchantOrderNo": number, "Amt": "1290", "TradeNo": "TRADE0001",
        }}
        with patch.object(payment, "lookup_order", return_value=record), patch.object(payment, "airtable_update") as update:
            payment.confirm_payment(reply)
            update.assert_called_once()
            self.assertEqual(update.call_args.args[2]["付款狀態"], "已付款")
        reply["Result"]["Amt"] = "1"
        with patch.object(payment, "lookup_order", return_value=record), patch.object(payment, "airtable_update") as update:
            with self.assertRaises(ValueError):
                payment.confirm_payment(reply)
            update.assert_not_called()

if __name__ == "__main__":
    unittest.main()
