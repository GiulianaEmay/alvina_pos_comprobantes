"""Real Odoo accounting/POS/EDI processing with a simulated provider, never SUNAT."""
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged("post_install", "-at_install", "alvina")
class TestAlvinaImmediateEdi(CommonPosTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({"country_id": cls.env.ref("base.pe").id,
                           "account_fiscal_country_id": cls.env.ref("base.pe").id})
        cls.format = cls.env["account.edi.format"].create({"name": "Proveedor simulado", "code": "alvina_simulated"})
        cls.company.alvina_edi_format_id = cls.format
        cls.config = cls.pos_config_usd
        cls.config.journal_id = cls.env["account.journal"].create({
            "name": "POS asiento de prueba", "code": "PTE", "type": "general", "company_id": cls.company.id,
        })
        cls.config.invoice_journal_id.write({"l10n_latam_use_documents": True,
                                            "edi_format_ids": [Command.set(cls.format.ids)]})
        cls.session = cls.env["pos.session"].create({"config_id": cls.config.id, "user_id": cls.env.uid})
        cls.partner = cls.env["res.partner"].create({
            "name": "CLIENTE FISCAL DE PRUEBA", "vat": "12345678", "active": False,
            "alvina_pos_fiscal_identity": True, "country_id": cls.env.ref("base.pe").id,
            "l10n_latam_identification_type_id": cls.env.ref("l10n_pe.it_DNI").id,
        })
        cls.tax = cls.env["account.tax"].create({"name": "IGV 18 test", "amount": 18,
                                              "type_tax_use": "sale", "company_id": cls.company.id,
                                              "tax_group_id": cls.env["account.tax.group"].create({
                                                  "name": "IGV test", "company_id": cls.company.id,
                                                  "country_id": cls.env.ref("base.pe").id,
                                              }).id,
                                              "country_id": cls.env.ref("base.pe").id})
        cls.product = cls.env["product.product"].create({
            "name": "Servicio de prueba", "type": "service", "list_price": 100,
            "property_account_income_id": cls.company_data["default_account_revenue"].id,
            "taxes_id": [Command.set(cls.tax.ids)],
        })

    def setUp(self):
        super().setUp()
        self.sent = []
        self.provider_error = False
        self.provider_exception = False
        format_type = type(self.format)
        original_needs = format_type._needs_web_services
        original_applicability = format_type._get_move_applicability

        def needs(record):
            return True if record == self.format else original_needs(record)

        def post(moves):
            self.sent.extend(moves.ids)
            if self.provider_exception:
                raise TimeoutError("Simulated provider timeout")
            if self.provider_error:
                return {move: {"error": "Rechazo simulado", "blocking_level": "error"} for move in moves}
            return {move: {"success": True} for move in moves}

        def applicability(record, move):
            return {"post": post} if record == self.format else original_applicability(record, move)

        for method, replacement in (("_needs_web_services", needs), ("_get_move_applicability", applicability)):
            patcher = patch.object(format_type, method, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def invoiced_order(self, kind="boleta", create_invoice=True, state="paid"):
        partner = self.partner
        if kind == "factura":
            partner = self.env["res.partner"].create({
                "name": "EMPRESA FISCAL DE PRUEBA", "vat": "20100070970", "street": "DOMICILIO DE PRUEBA",
                "active": False, "alvina_pos_fiscal_identity": True, "country_id": self.env.ref("base.pe").id,
                "l10n_latam_identification_type_id": self.env.ref("l10n_pe.it_RUC").id,
            })
        fiscal = self.env["account.fiscal.position"].with_company(self.company)._get_fiscal_position(partner)
        order = self.env["pos.order"].create({
            "session_id": self.session.id, "company_id": self.company.id, "state": state,
            "partner_id": partner.id, "alvina_document_kind": kind, "fiscal_position_id": fiscal.id,
            "amount_total": 118, "amount_tax": 18, "amount_paid": 118, "amount_return": 0,
            "lines": [Command.create({"product_id": self.product.id, "qty": 1, "price_unit": 100,
                                      "price_subtotal": 100, "price_subtotal_incl": 118,
                                      "tax_ids": [Command.set(self.tax.ids)]})],
            "payment_ids": [Command.create({"amount": 118, "payment_method_id": self.bank_payment_method.id})],
        })
        if create_invoice:
            order.with_context(generate_pdf=False, skip_account_edi_cron_trigger=True).action_pos_order_invoice()
        return order

    def test_existing_invoice_sends_once_without_new_sale_or_invoice(self):
        order = self.invoiced_order()
        invoice = order.account_move
        before_invoices = self.env["account.move"].search_count([])
        before_payments = self.env["pos.payment"].search_count([])
        self.assertEqual(order.alvina_document_status()["state"], "to_send")
        result = order.alvina_send_document()
        self.assertEqual(result["state"], "sent")
        self.assertTrue(result["can_print"])
        order.alvina_send_document()
        self.assertEqual(self.sent, invoice.ids)
        self.assertEqual(order.account_move, invoice)
        self.assertEqual(invoice.state, "posted")
        self.assertEqual(self.env["account.move"].search_count([]), before_invoices)
        self.assertEqual(self.env["pos.payment"].search_count([]), before_payments)

    def test_rejected_provider_does_not_enable_print(self):
        order = self.invoiced_order()
        self.provider_error = True
        result = order.alvina_send_document()
        self.assertEqual(result["state"], "edi_error")
        self.assertFalse(result["can_print"])
        self.assertEqual(order.account_move.state, "posted")
        self.assertIn("Rechazo", result["message"])

    def test_uncertain_result_preserves_invoice_and_disables_resend(self):
        order = self.invoiced_order()
        invoice = order.account_move
        self.provider_exception = True
        result = order.alvina_send_document()
        self.assertEqual(result["state"], "unknown")
        self.assertFalse(result["can_print"])
        self.assertFalse(result["can_send"])
        self.assertEqual(order.account_move, invoice)
        self.assertEqual(invoice.state, "posted")

    def test_no_pdf_download_before_electronic_send(self):
        from odoo.exceptions import UserError
        order = self.invoiced_order()
        with self.assertRaises(UserError):
            order.alvina_print_document()

    def test_factura_uses_official_report_without_reissuing(self):
        order = self.invoiced_order(kind="factura")
        invoice = order.account_move
        self.assertEqual(invoice.l10n_latam_document_type_id.code, "01")
        order.alvina_send_document()
        # Odoo's test runner substitutes HTML for PDF. Verify the invoice data
        # and download integration here; binary PDF rendering is a separate check.
        action = order.alvina_print_document()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertIn(b"20100070970", invoice.invoice_pdf_report_id.raw)
        self.assertIn(b"EMPRESA FISCAL DE PRUEBA", invoice.invoice_pdf_report_id.raw)
        pdf_id = invoice.invoice_pdf_report_id.id
        order.alvina_print_document()
        self.assertEqual(invoice.invoice_pdf_report_id.id, pdf_id)
        self.assertEqual(self.sent, invoice.ids)

    def test_receipt_without_previous_invoice_posts_once_then_sends(self):
        order = self.invoiced_order(create_invoice=False)
        preview = order.alvina_lookup_identity("boleta", self.partner.vat)["identity_id"]
        result = order.alvina_submit_document(preview)
        self.assertEqual(result["state"], "to_send")
        self.assertFalse(self.sent)
        invoice = order.account_move
        before = self.env["account.move"].search_count([])
        order.alvina_submit_document(preview)
        self.assertEqual(order.account_move, invoice)
        self.assertEqual(self.env["account.move"].search_count([]), before)
        self.assertEqual(invoice.l10n_latam_document_type_id.code, "03")
        self.assertEqual(order.alvina_send_document()["state"], "sent")

    def test_ticket_first_then_receipt_emission_keeps_original_sale_and_payment(self):
        order = self.invoiced_order(create_invoice=False, state="draft")
        order.write({"to_invoice": True, "partner_id": False,
                     "alvina_document_kind": False})
        payments = order.payment_ids
        order._process_saved_order(draft=False)
        self.assertEqual(order.state, "paid")
        self.assertTrue(order.alvina_receipt_first)
        self.assertTrue(order.to_invoice)  # Existing automatic billing stays queued.
        self.assertFalse(order.account_move)
        self.assertEqual(order.payment_ids, payments)
        self.assertFalse(self.sent)
        self.assertEqual(order.alvina_document_status()["state"], "none")

        preview = order.alvina_lookup_identity("boleta", self.partner.vat)["identity_id"]
        self.assertFalse(order.account_move)
        self.assertEqual(order.alvina_submit_document(preview)["state"], "to_send")
        invoice = order.account_move
        self.assertTrue(order.to_invoice)
        self.assertEqual(invoice.l10n_latam_document_type_id.code, "03")
        self.assertEqual(order.alvina_send_document()["state"], "sent")
        self.assertEqual(order.payment_ids, payments)
        self.assertEqual(invoice.pos_order_ids, order)
        self.assertEqual(self.sent, invoice.ids)
        self.assertEqual(order._generate_pos_order_invoice(), invoice)
        self.assertEqual(self.sent, invoice.ids)

    def test_existing_batch_can_invoice_queued_ticket_once(self):
        order = self.invoiced_order(create_invoice=False)
        order.write({"alvina_receipt_first": True, "to_invoice": True})
        order.with_context(generate_pdf=False, skip_account_edi_cron_trigger=True).action_pos_order_invoice()
        invoice = order.account_move
        self.assertEqual(invoice.state, "posted")
        self.assertEqual(order._generate_pos_order_invoice(), invoice)
        self.assertEqual(invoice.pos_order_ids, order)
        self.assertFalse(self.sent)

    def test_fast_payment_auto_invoice_preference_is_preserved_without_early_invoice(self):
        order = self.invoiced_order(create_invoice=False, state="draft")
        order.to_invoice = False  # Frontend already deferred its fiscal request.
        with patch.object(type(self.bank_payment_method), "auto_invoice", True, create=True):
            order._process_saved_order(draft=False)
        self.assertTrue(order.to_invoice)
        self.assertTrue(order.alvina_receipt_first)
        self.assertFalse(order.account_move)
        self.assertFalse(self.sent)

    def test_boleta_uses_partner_journal_selector_and_its_edi_format(self):
        order = self.invoiced_order(create_invoice=False)
        order.alvina_receipt_first = True
        ballot_journal = order.config_id.invoice_journal_id.copy({"name": "Boletas ALVIÑA test", "code": "ABOL"})
        ballot_journal.edi_format_ids = self.format
        order.config_id.invoice_journal_id.edi_format_ids = False
        with patch.object(type(order.config_id), "_get_journal", lambda config, partner, refunded: ballot_journal, create=True):
            preview = order.alvina_lookup_identity("boleta", self.partner.vat)["identity_id"]
            result = order.alvina_submit_document(preview)
            self.assertEqual(result["state"], "to_send", result["message"])
            self.assertEqual(order.account_move.journal_id, ballot_journal)
            self.assertEqual(order.account_move.l10n_latam_document_type_id.code, "03")
            self.assertEqual(order._alvina_request().edi_format_id, self.format)
            self.assertEqual(order.alvina_send_document()["state"], "sent")

    def test_existing_fiscal_document_cannot_start_a_second_identity_lookup(self):
        order = self.invoiced_order()
        invoice = order.account_move
        with self.assertRaises(UserError):
            order.alvina_lookup_identity("boleta", self.partner.vat)
        self.assertEqual(order.account_move, invoice)

    def test_pos_default_fiscal_position_allows_receipt_emission(self):
        order = self.invoiced_order(create_invoice=False)
        default = self.env["account.fiscal.position"].create({"name": "Venta local POS", "company_id": self.company.id})
        order.config_id.default_fiscal_position_id = default
        order.fiscal_position_id = default
        with patch.object(type(self.env["account.fiscal.position"]), "_get_fiscal_position", return_value=self.env["account.fiscal.position"]):
            preview = order.alvina_lookup_identity("boleta", self.partner.vat)["identity_id"]
            result = order.alvina_submit_document(preview)
        self.assertEqual(result["state"], "to_send", result["message"])
        self.assertEqual(order.account_move.fiscal_position_id, default)
        self.assertEqual(order.amount_total, 118)
        self.assertEqual(order.amount_tax, 18)

    def test_equivalent_fiscal_positions_preserve_paid_taxes_and_emit(self):
        order = self.invoiced_order(create_invoice=False)
        previous = self.env["account.fiscal.position"].create({"name": "Ticket atención", "company_id": self.company.id})
        expected = self.env["account.fiscal.position"].create({"name": "Cliente identificado", "company_id": self.company.id})
        order.fiscal_position_id = previous
        order.config_id.tax_regime_selection = True
        order.config_id.fiscal_position_ids |= expected
        self.partner.with_company(self.company).property_account_position_id = expected
        preview = order.alvina_lookup_identity("boleta", self.partner.vat)["identity_id"]
        result = order.alvina_submit_document(preview)
        self.assertEqual(result["state"], "to_send", result["message"])
        self.assertEqual(order.fiscal_position_id, expected)
        self.assertEqual(order.account_move.fiscal_position_id, expected)
        self.assertEqual(order.amount_total, 118)
        self.assertEqual(order.amount_tax, 18)

    def test_different_tax_treatment_cannot_rewrite_a_paid_ticket(self):
        order = self.invoiced_order(create_invoice=False)
        zero = self.tax.copy({"name": "Exonerado test", "amount": 0,
                              "original_tax_ids": [Command.set(self.tax.ids)]})
        expected = self.env["account.fiscal.position"].create({
            "name": "Exoneración incompatible", "company_id": self.company.id,
            "tax_ids": [Command.set(zero.ids)],
        })
        order.config_id.tax_regime_selection = True
        order.config_id.fiscal_position_ids |= expected
        self.partner.with_company(self.company).property_account_position_id = expected
        preview = order.alvina_lookup_identity("boleta", self.partner.vat)["identity_id"]
        with self.assertRaisesRegex(UserError, "impuestos diferentes"):
            order.alvina_submit_document(preview)
        self.assertFalse(order.account_move)
        self.assertEqual(order.amount_total, 118)
        self.assertEqual(order.amount_tax, 18)
        self.assertFalse(self.sent)

    def test_factura_from_paid_ticket_looks_up_ruc_creates_hidden_identity_and_sends(self):
        order = self.invoiced_order(create_invoice=False)
        order.write({"partner_id": False, "alvina_document_kind": False,
                     "alvina_receipt_first": True, "to_invoice": False})
        payments = order.payment_ids
        default = self.env["account.fiscal.position"].create({"name": "POS ventas locales RUC", "company_id": self.company.id})
        order.config_id.default_fiscal_position_id = default
        order.fiscal_position_id = default
        with patch.object(type(self.company), "_alvina_lookup_external", return_value={
            "name": "EMPRESA CONSULTADA DE PRUEBA", "street": "DOMICILIO FISCAL DE PRUEBA",
        }) as lookup:
            preview = order.alvina_lookup_identity("factura", "20100070970")["identity_id"]
        lookup.assert_called_once_with("factura", "20100070970")
        self.assertFalse(order.account_move)
        self.assertEqual(order.alvina_submit_document(preview)["state"], "to_send")
        invoice = order.account_move
        self.assertEqual(invoice.l10n_latam_document_type_id.code, "01")
        self.assertEqual(invoice.partner_id.vat, "20100070970")
        self.assertFalse(invoice.partner_id.active)
        self.assertTrue(invoice.partner_id.alvina_pos_fiscal_identity)
        self.assertFalse(self.env["res.partner"].search([("vat", "=", "20100070970")]))
        self.assertEqual(order.alvina_send_document()["state"], "sent")
        self.assertEqual(order.alvina_print_document()["type"], "ir.actions.act_url")
        self.assertEqual(order.payment_ids, payments)
        self.assertEqual(self.sent, invoice.ids)
        self.assertEqual(invoice.amount_total, 118)
