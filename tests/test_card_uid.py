import unittest

from app.card_uid import normalize_uid, uid_hmac


class CardUidTests(unittest.TestCase):
    def test_equivalent_formats_have_same_hmac(self):
        key = bytes(range(32))
        variants = ["04AABBCCDD", "04:AA:BB:CC:DD", "04 aa bb cc dd"]
        self.assertEqual(
            {uid_hmac(uid, key) for uid in variants},
            {uid_hmac("04AABBCCDD", key)},
        )

    def test_rejects_invalid_uid(self):
        for raw in ("", "AABBCC", "04AABBCCD", "04:GG:BB:CC:DD", "0x04AABBCC"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    normalize_uid(raw)

    def test_requires_key_and_keeps_leading_zeroes(self):
        with self.assertRaises(ValueError):
            uid_hmac("04AABBCCDD", b"short")

        self.assertEqual(normalize_uid("00:AA:BB:CC"), "00AABBCC")
        self.assertNotEqual(
            uid_hmac("00AABBCC", bytes(range(32))),
            uid_hmac("AABBCC00", bytes(range(32))),
        )