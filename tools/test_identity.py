"""Offline tests of production validation code; does not import or simulate Odoo."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "alvina_pos_comprobantes/models/identity.py"
spec = importlib.util.spec_from_file_location("alvina_identity", path)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


class TestIdentity(unittest.TestCase):
    def test_dni(self):
        self.assertEqual(identity.validate_identity("boleta", "01234567"), "01234567")

    def test_ruc(self):
        self.assertEqual(identity.validate_identity("factura", "20100070970"), "20100070970")

    def test_ruc_checksum(self):
        with self.assertRaisesRegex(ValueError, "verificador"):
            identity.validate_identity("factura", "20100070971")

    def test_ruc_prefix(self):
        with self.assertRaisesRegex(ValueError, "Prefijo"):
            identity.validate_identity("factura", "99100070970")

    def test_invalid_kind(self):
        for kind in (None, "ticket", "03"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                identity.validate_identity(kind, "12345678")

    def test_invalid_dni(self):
        for number in (None, 12345678, "", "1234567", "123456789", "１２３４５６７８", "1234 678", "12345678\n"):
            with self.subTest(number=number), self.assertRaises(ValueError):
                identity.validate_identity("boleta", number)

    def test_invalid_ruc(self):
        for number in (None, "2010007097", "201000709700", "PE20100070970", " 20100070970"):
            with self.subTest(number=number), self.assertRaises(ValueError):
                identity.validate_identity("factura", number)

    def test_nested_json_mapping(self):
        self.assertEqual(identity.json_path({"data": {"name": " ALVIÑA "}}, "data.name"), "ALVIÑA")

    def test_missing_json_mapping(self):
        with self.assertRaises(ValueError):
            identity.json_path({"data": {}}, "data.name")

    def test_untrusted_json_values(self):
        for value in (None, "", "   ", 12345678, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                identity.json_path({"value": value}, "value")


if __name__ == "__main__":
    unittest.main()
