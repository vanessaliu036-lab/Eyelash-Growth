"""Offline validation of price, free shipping, Taiwan Post and signed payment callbacks.

Run: python -m unittest discover -s tests -p 'test_newebpay.py'
No real card/merchant credential is used in tests.
"""
import json
import os
import unittest
from unittest.mock import patch
from api import newebpay as payment


class QuoteTests(unittest.TestCase):
    def test_45_usd_per_bottle_and_local_shipping(self):
        with patch.dict(os.environ, {}, clear=True):
            one = payment.quote("KH", 1)
            two = payment.quote("KH", 2)
        self.assertEqual(one["unitPriceUsd"], "45.00")
        self.assertEqual(one["subtotalUsd"], "45.00")
        self.assertEqual(one["totalUsd"], "48.00")
        self.assertFalse(one["enabled"])
        self.assertEqual(two["subtotalUsd"], "90.00")
        self.assertEqual(two["shippingUsd"], "0.00")
        self.assertEqual(two["totalUsd"], "90.00")
        self.assertTrue(two["freeShipping"])

    def test_two_bottles_shipping_free_in_all_destinations(self):
        with patch.dict(os.environ, {}, clear=True):
            for country in ("VN", "SG", "MY", "ID", "HK", "KH", "TW"):
                q = payment.quote(country, 2)
                self.assertEqual(q["shippingUsd"], "0.00", country)
                self.assertEqual(q["totalUsd"], "90.00", country)
                self.assertEqual(q["shippingTwd"], 0, country)

    def test_post_asia_rate_by_packed_weight(self):
        with patch.dict(os.environ, {"LA_PACKED_WEIGHT_GRAMS": "200", "LA_TWD_PER_USD": "30"}, clear=True):
            for country in ("VN", "SG", "MY", "ID", "HK"):
                q = payment.quote(country, 1)
                self.assertEqual(q["shippingTwd"], 120)
                self.assertEqual(q["shippingUsd"], "4.00")
                self.assertEqual(q["totalUsd"], "49.00")
                self.assertEqual(q["amountTwd"], 1470)
                self.assertIn("Chunghwa Post", q["shippingCarrier"])
                self.assertFalse(q["enabled"])
        with patch.dict(os.environ, {"LA_PACKED_WEIGHT_GRAMS": "350", "LA_TWD_PER_USD": "30"}, clear=True):
            self.assertEqual(payment.quote("MY", 1)["shippingTwd"], 160)

    def test_post_price_is_visible_without_exchange_rate(self):
        with patch.dict(os.environ, {}, clear=True):
            q = payment.quote("SG", 1)
        self.assertEqual(q["subtotalUsd"], "45.00")
        self.assertEqual(q["shippingTwd"], 120)
        self.assertIsNone(q["totalUsd"])
        self.assertIsNone(q["amountTwd"])

    def test_sf_only_if_verified_and_cheaper(self):
        env = {
            "LA_PACKED_WEIGHT_GRAMS": "200",
            "LA_TWD_PER_USD": "30",
            "LA_SF_QUOTE_TWD_VN": "80",
            "LA_SF_QUOTE_VALID_THROUGH": "2099-01-01",
        }
        with patch.dict(os.environ, env, clear=True):
            q = payment.quote("VN", 1)
        self.assertEqual(q["shippingTwd"], 80)
        self.assertIn("SF Express", q["shippingCarrier"])
        env["LA_SF_QUOTE_VALID_THROUGH"] = "2020-01-01"
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(payment.quote("VN", 1)["shippingTwd"], 120)

    def test_invalid_quantity_and_weight(self):
        for n in (0, 11, -1):
            with self.assertRaises(ValueError):
                payment.quote("KH", n)
        with patch.dict(os.environ, {"LA_PACKED_WEIGHT_GRAMS": "0"}, clear=True):
            with self.assertRaises(ValueError):
                payment.quote("SG", 1)


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
            "Amt": "1470", "TradeNo": "T12345"}}).encode()
        padder = padding.PKCS7(128).padder()
        padded = padder.update(payload) + padder.finalize()
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(self.iv)).encryptor()
        cipher_hex = (cipher.update(padded) + cipher.finalize()).hex()
        form = {
            "TradeInfo": cipher_hex,
            "TradeSha": payment.trade_sha(cipher_hex, self.key, self.iv),
            "MerchantID": self.merchant, "Status": "SUCCESS",
        }
        self.assertEqual(payment.decode_reply(form, self.merchant, self.key, self.iv)["Result"]["Amt"], "1470")
        form["TradeSha"] = "A" * 64
        with self.assertRaises(ValueError):
            payment.decode_reply(form, self.merchant, self.key, self.iv)

    def test_paid_order_amount_check(self):
        number = "LA" + "A" * 22
        record = {"id": "rec123", "fields": {
            "付款狀態": "未付款", "備註": "LA_CARD_AMOUNT_TWD=1470\nLA_CARD_COUNTRY=VN",
        }}
        reply = {"Status": "SUCCESS", "Result": {
            "MerchantOrderNo": number, "Amt": "1470", "TradeNo": "TRADE0001",
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
