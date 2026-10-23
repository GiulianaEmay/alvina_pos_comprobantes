"""Offline tests of the documented JSON.PE contract, without Odoo or live calls."""
import importlib
from pathlib import Path
import sys
import types
import unittest

package = types.ModuleType("alvina_contract_tests")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "alvina_pos_comprobantes/models")]
sys.modules[package.__name__] = package
jsonpe = importlib.import_module("alvina_contract_tests.jsonpe")


class TestJsonPe(unittest.TestCase):
    def dni(self, **overrides):
        return {"success": True, "data": {"numero": "12345678", "nombre_completo": "PERSONA DE PRUEBA", **overrides}}

    def ruc(self, **overrides):
        return {"success": True, "data": {"ruc": "20100070970", "nombre_o_razon_social": "EMPRESA DE PRUEBA",
                                          "direccion_completa": "DOMICILIO DE PRUEBA", **overrides}}

    def test_dni_request(self):
        self.assertEqual(jsonpe.request_spec("boleta", "12345678"),
                         ("https://api.json.pe/api/dni", {"dni": "12345678"}))

    def test_ruc_request(self):
        self.assertEqual(jsonpe.request_spec("factura", "20100070970"),
                         ("https://api.json.pe/api/ruc", {"ruc": "20100070970"}))

    def test_invalid_request_never_builds_body(self):
        for kind, number in (("ticket", "12345678"), ("boleta", "123"), ("factura", "20100070971")):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                jsonpe.request_spec(kind, number)

    def test_dni_without_address_is_valid(self):
        result = jsonpe.parse_response("boleta", "12345678", self.dni())
        self.assertEqual(result, {"name": "PERSONA DE PRUEBA", "street": ""})

    def test_dni_empty_optional_address_is_valid(self):
        result = jsonpe.parse_response("boleta", "12345678", self.dni(direccion="", direccion_completa=None))
        self.assertEqual(result["street"], "")

    def test_ruc_uses_company_name(self):
        result = jsonpe.parse_response("factura", "20100070970", self.ruc())
        self.assertEqual(result, {"name": "EMPRESA DE PRUEBA", "street": "DOMICILIO DE PRUEBA"})

    def test_address_fallback(self):
        result = jsonpe.parse_response("factura", "20100070970", self.ruc(direccion_completa="", direccion="OTRO DOMICILIO"))
        self.assertEqual(result["street"], "OTRO DOMICILIO")

    def test_ruc_requires_address(self):
        for street in (None, "", "   ", "-", 123, []):
            with self.subTest(street=street), self.assertRaises(ValueError):
                jsonpe.parse_response("factura", "20100070970", self.ruc(direccion_completa=street))

    def test_requires_boolean_success(self):
        for success in (False, "true", 1, None):
            payload = self.dni()
            payload["success"] = success
            with self.subTest(success=success), self.assertRaises(ValueError):
                jsonpe.parse_response("boleta", "12345678", payload)

    def test_wrong_identity_is_rejected(self):
        for kind, number, payload in (("boleta", "12345678", self.dni(numero="87654321")),
                                      ("factura", "20100070970", self.ruc(ruc="20552103816"))):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                jsonpe.parse_response(kind, number, payload)

    def test_name_is_required(self):
        for name in (None, "", " ", {}, 123):
            with self.subTest(name=name), self.assertRaises(ValueError):
                jsonpe.parse_response("boleta", "12345678", self.dni(nombre_completo=name))

    def test_malformed_payload(self):
        for payload in (None, [], {}, {"success": True}, {"success": True, "data": []}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                jsonpe.parse_response("boleta", "12345678", payload)

    def test_number_must_be_a_string(self):
        with self.assertRaises(ValueError):
            jsonpe.parse_response("boleta", "12345678", self.dni(numero=12345678))

    def test_shared_generic_mapping_cannot_parse_ruc_as_dni(self):
        with self.assertRaises(ValueError):
            jsonpe.parse_response("boleta", "12345678", self.ruc())


if __name__ == "__main__":
    unittest.main()
