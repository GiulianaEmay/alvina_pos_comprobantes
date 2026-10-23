import json
import os
from unittest.mock import MagicMock, patch

import requests

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models import res_company


@tagged("post_install", "-at_install", "alvina")
class TestJsonPeTransport(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company.sudo()
        self.company.write({"alvina_jsonpe_profile": "official", "alvina_jsonpe_enabled": True,
                            "alvina_jsonpe_token": "unit-test-placeholder"})
        self.env_token = patch.dict(os.environ, {"ALVINA_JSONPE_TOKEN": ""})
        self.env_token.start()
        self.addCleanup(self.env_token.stop)

    def response(self, payload, status=200):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = status
        response.iter_content.return_value = [json.dumps(payload).encode()]
        return response

    def test_dni_transport_and_empty_address(self):
        response = self.response({"success": True, "data": {"numero": "12345678", "nombre_completo": "PRUEBA"}})
        with patch.object(res_company.requests, "request", return_value=response) as call:
            result = self.company._alvina_lookup_external("boleta", "12345678")
        self.assertEqual(result, {"name": "PRUEBA", "street": ""})
        self.assertEqual(call.call_args.args, ("POST", "https://api.json.pe/api/dni"))
        self.assertEqual(call.call_args.kwargs["json"], {"dni": "12345678"})
        self.assertEqual(call.call_args.kwargs["headers"]["Authorization"], "Bearer unit-test-placeholder")
        self.assertFalse(call.call_args.kwargs["allow_redirects"])
        self.assertNotIn("verify", call.call_args.kwargs)  # requests TLS verification remains enabled.

    def test_ruc_transport(self):
        response = self.response({"success": True, "data": {"ruc": "20100070970",
                                 "nombre_o_razon_social": "EMPRESA", "direccion": "DOMICILIO"}})
        with patch.object(res_company.requests, "request", return_value=response) as call:
            result = self.company._alvina_lookup_external("factura", "20100070970")
        self.assertEqual(call.call_args.args, ("POST", "https://api.json.pe/api/ruc"))
        self.assertEqual(call.call_args.kwargs["json"], {"ruc": "20100070970"})
        self.assertEqual(result["street"], "DOMICILIO")

    def test_disabled_does_not_call_provider(self):
        self.company.alvina_jsonpe_enabled = False
        with patch.object(res_company.requests, "request") as call, self.assertRaises(UserError):
            self.company._alvina_lookup_external("boleta", "12345678")
        call.assert_not_called()

    def test_provider_failures(self):
        for status, payload in ((404, {"success": False}), (200, {"success": False}),
                                (200, {"success": True, "data": {"numero": "87654321", "nombre_completo": "PRUEBA"}})):
            with self.subTest(status=status, payload=payload):
                with patch.object(res_company.requests, "request", return_value=self.response(payload, status)), self.assertRaises(UserError):
                    self.company._alvina_lookup_external("boleta", "12345678")

    def test_timeout(self):
        with patch.object(res_company.requests, "request", side_effect=requests.Timeout), self.assertRaises(UserError):
            self.company._alvina_lookup_external("boleta", "12345678")

    def test_response_size_limit(self):
        response = self.response({})
        response.iter_content.return_value = [b"x" * 65537]
        with patch.object(res_company.requests, "request", return_value=response), self.assertRaises(UserError):
            self.company._alvina_lookup_external("boleta", "12345678")
