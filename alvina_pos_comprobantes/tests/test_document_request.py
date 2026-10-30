"""Requires a real Odoo 19 test database. No live provider calls or SUNAT calls."""
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user
from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged("post_install", "-at_install", "alvina")
class TestAlvinaDocumentRequest(CommonPosTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.country_id = cls.env.ref("base.pe")
        cls.company.account_fiscal_country_id = cls.env.ref("base.pe")
        cls.edi_format = cls.env["account.edi.format"].create({"name": "EDI de prueba ALVIÑA", "code": "alvina_test_edi"})
        cls.config = cls.pos_config_usd
        cls.session = cls.env["pos.session"].create({"config_id": cls.config.id, "user_id": cls.env.uid})
        cls.dni_partner = cls.env["res.partner"].create({
            "name": "Cliente prueba ALVIÑA", "vat": "12345678", "country_id": cls.env.ref("base.pe").id,
            "l10n_latam_identification_type_id": cls.env.ref("l10n_pe.it_DNI").id,
        })
        cls.cashier = new_test_user(cls.env, login="alvina_cashier_test", groups="point_of_sale.group_pos_user")

    def setUp(self):
        super().setUp()
        patcher = patch.object(type(self.company), "_alvina_get_edi_format", return_value=self.edi_format)
        patcher.start()
        self.addCleanup(patcher.stop)

    def submit_unposted(self, order, preview=None):
        with patch.object(type(self.env["alvina.pos.document.request"]), "_process_pending", lambda req: req._status_payload()):
            return order.alvina_submit_document(preview or self.preview(order))

    def make_order(self):
        fiscal = self.env["account.fiscal.position"].with_company(self.company)._get_fiscal_position(self.dni_partner)
        return self.env["pos.order"].create({
            "session_id": self.session.id, "company_id": self.company.id, "state": "paid",
            "amount_total": 118, "amount_tax": 18, "amount_paid": 118, "amount_return": 0,
            "fiscal_position_id": fiscal.id,
        })

    def preview(self, order):
        return order.alvina_lookup_identity("boleta", self.dni_partner.vat)["identity_id"]

    def test_local_partner_does_not_call_provider(self):
        order = self.make_order()
        with patch.object(type(self.company), "_alvina_lookup_external", side_effect=AssertionError("No network expected")):
            result = order.alvina_lookup_identity("boleta", self.dni_partner.vat)
        self.assertEqual(result["name"], self.dni_partner.name)
        self.assertNotIn("token", result)

    def test_duplicate_submit_keeps_original_order_and_no_new_payments(self):
        order = self.make_order()
        preview = self.preview(order)
        before_orders = self.env["pos.order"].search_count([])
        before_payments = self.env["pos.payment"].search_count([])
        first = self.submit_unposted(order, preview)
        second = self.submit_unposted(order, preview)
        self.assertEqual(first, second)
        self.assertEqual(first["state"], "pending")
        self.assertEqual(order.partner_id, self.dni_partner)
        self.assertFalse(order.account_move)
        self.assertEqual(self.env["pos.order"].search_count([]), before_orders)
        self.assertEqual(self.env["pos.payment"].search_count([]), before_payments)
        self.assertEqual(self.env["alvina.pos.document.request"].search_count([("order_id", "=", order.id)]), 1)

    def test_foreign_order_preview_is_rejected(self):
        order, other = self.make_order(), self.make_order()
        preview = self.preview(order)
        with self.assertRaises(UserError):
            other.alvina_submit_document(preview)

    def test_expired_preview(self):
        from datetime import timedelta
        order = self.make_order()
        preview = self.env["alvina.pos.identity"].sudo().browse(self.preview(order))
        preview.flush_recordset()
        self.env.cr.execute("UPDATE alvina_pos_identity SET create_date = %s WHERE id = %s",
                            [fields.Datetime.now() - timedelta(hours=2), preview.id])
        preview.invalidate_recordset(["create_date"])
        with self.assertRaises(UserError):
            order.alvina_submit_document(preview.id)

    def test_invalid_document(self):
        with self.assertRaises(UserError):
            self.make_order().alvina_lookup_identity("factura", "20100070971")

    def test_other_session_user_is_denied(self):
        order = self.make_order()
        with self.assertRaises(AccessError):
            order.with_user(self.cashier).alvina_lookup_identity("boleta", "12345678")

    def test_request_is_not_writable_by_cashier(self):
        order = self.make_order()
        self.submit_unposted(order)
        request = order._alvina_request()
        with self.assertRaises(AccessError):
            request.with_user(self.cashier).write({"state": "processed"})

    def test_processing_failure_is_persistent_and_not_retried_silently(self):
        order = self.make_order()
        self.submit_unposted(order)
        request = order._alvina_request()
        with patch.object(type(request), "_validate_for_invoice", side_effect=UserError("Diario de prueba inválido")):
            request._process_pending()
        self.assertEqual(request.state, "failed")
        self.assertIn("Diario", request.error_message)
        self.assertEqual(request.attempts, 1)
        self.assertFalse(order.account_move)
        request._process_pending()
        self.assertEqual(request.attempts, 1)

    def test_pending_cannot_print(self):
        order = self.make_order()
        self.submit_unposted(order)
        with self.assertRaises(UserError):
            order.alvina_print_document()

    def test_official_invoice_values_use_type_03(self):
        order = self.make_order()
        order.config_id.invoice_journal_id.l10n_latam_use_documents = True
        self.submit_unposted(order)
        values = order._prepare_invoice_vals()
        self.assertEqual(values["l10n_latam_document_type_id"], self.env.ref("l10n_pe.document_type02").id)
        self.assertEqual(values["journal_id"], order.config_id.invoice_journal_id.id)
        self.assertEqual(values["pos_order_ids"], order.ids)

    def test_official_invoice_values_use_type_01(self):
        order = self.make_order()
        order.config_id.invoice_journal_id.l10n_latam_use_documents = True
        self.env["res.partner"].create({
            "name": "Empresa prueba", "vat": "20100070970", "street": "Dirección fiscal de prueba",
            "country_id": self.env.ref("base.pe").id,
            "l10n_latam_identification_type_id": self.env.ref("l10n_pe.it_RUC").id,
        })
        preview = order.alvina_lookup_identity("factura", "20100070970")["identity_id"]
        self.submit_unposted(order, preview)
        values = order._prepare_invoice_vals()
        self.assertEqual(values["l10n_latam_document_type_id"], self.env.ref("l10n_pe.document_type01").id)

    def test_failed_invoice_attempt_rolls_back_its_changes(self):
        order = self.make_order()
        self.submit_unposted(order)
        request = order._alvina_request()
        before_name = order.name

        def fail_after_write(records):
            records.write({"name": "Must be rolled back"})
            raise UserError("Simulated posting failure")

        with patch.object(type(request), "_validate_for_invoice", return_value=self.env.ref("l10n_pe.document_type02")), \
             patch.object(type(order), "action_pos_order_invoice", fail_after_write):
            request._process_pending()
        self.assertEqual(order.name, before_name)
        self.assertFalse(order.account_move)
        self.assertEqual(request.state, "failed")

    def test_quick_customer_is_internal_and_reused(self):
        self.session.state = "opened"
        with patch.object(type(self.company), "_alvina_lookup_external", return_value={"name": "IDENTIDAD FISCAL", "street": ""}):
            preview = self.session.alvina_lookup_customer("boleta", "87654321")
        result = self.session.alvina_confirm_customer(preview["identity_id"])
        partner = self.env["res.partner"].browse(result["partner_id"])
        self.assertFalse(partner.active)
        self.assertTrue(partner.alvina_pos_fiscal_identity)
        self.assertFalse(self.env["res.partner"].search([("vat", "=", "87654321")]))
        again = self.session.alvina_lookup_customer("boleta", "87654321")
        self.assertEqual(self.session.alvina_confirm_customer(again["identity_id"])["partner_id"], partner.id)

    def test_existing_contact_not_archived_or_duplicated(self):
        self.session.state = "opened"
        before = self.env["res.partner"].with_context(active_test=False).search_count([])
        preview = self.session.alvina_lookup_customer("boleta", self.dni_partner.vat)
        result = self.session.alvina_confirm_customer(preview["identity_id"])
        self.assertEqual(result["partner_id"], self.dni_partner.id)
        self.assertTrue(self.dni_partner.active)
        self.assertEqual(self.env["res.partner"].with_context(active_test=False).search_count([]), before)

    def test_kind_selected_before_payment_reaches_official_invoice(self):
        order = self.make_order()
        order.write({"partner_id": self.dni_partner.id, "alvina_document_kind": "boleta"})
        values = order._prepare_invoice_vals()
        self.assertEqual(values["l10n_latam_document_type_id"], self.env.ref("l10n_pe.document_type02").id)

    def test_receipt_lookup_preserves_ubigeo_for_internal_fiscal_identity(self):
        order = self.make_order()
        with patch.object(type(self.company), "_alvina_lookup_external", return_value={
            "name": "NUEVO CLIENTE", "street": "DIRECCIÓN", "ubigeo_sunat": "150101",
        }):
            result = order.alvina_lookup_identity("boleta", "87654321")
        preview = self.env["alvina.pos.identity"].browse(result["identity_id"])
        self.assertEqual(preview.ubigeo, "150101")
