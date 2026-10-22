import logging

from psycopg2 import OperationalError

from odoo import fields, models, _
from odoo.exceptions import UserError

from .identity import validate_identity

_logger = logging.getLogger(__name__)


class AlvinaPosIdentity(models.TransientModel):
    _name = "alvina.pos.identity"
    _description = "Consulta temporal de identidad ALVIÑA"
    _transient_max_hours = 1

    order_id = fields.Many2one("pos.order", required=True, ondelete="cascade")
    requested_by = fields.Many2one("res.users", required=True)
    kind = fields.Selection([("boleta", "Boleta"), ("factura", "Factura")], required=True)
    number = fields.Char(required=True)
    name = fields.Char(required=True)
    street = fields.Char()
    partner_id = fields.Many2one("res.partner", ondelete="set null")


class AlvinaPosDocumentRequest(models.Model):
    _name = "alvina.pos.document.request"
    _description = "Solicitud de comprobante ALVIÑA POS"
    _order = "id desc"
    _rec_name = "order_id"

    _order_unique = models.Constraint("UNIQUE(order_id)", "Solo se permite una solicitud por pedido POS.")

    order_id = fields.Many2one("pos.order", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one(related="order_id.company_id", store=True, index=True)
    requested_by = fields.Many2one("res.users", required=True, ondelete="restrict")
    kind = fields.Selection([("boleta", "Boleta 03"), ("factura", "Factura 01")], required=True)
    number = fields.Char(required=True)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict")
    state = fields.Selection(
        [("pending", "Pendiente"), ("processed", "Procesado en Odoo"), ("failed", "Fallido")],
        required=True, default="pending", index=True,
    )
    invoice_id = fields.Many2one("account.move", readonly=True, ondelete="restrict")
    attempts = fields.Integer(readonly=True)
    processed_at = fields.Datetime(readonly=True)
    error_message = fields.Text(readonly=True)

    def _validate_for_invoice(self):
        self.ensure_one()
        order = self.order_id
        try:
            validate_identity(self.kind, self.number)
        except ValueError as exc:
            raise UserError(str(exc)) from None
        if self.state == "failed":
            raise UserError(_("La solicitud falló. Un administrador POS debe autorizar el reintento."))
        partner = self.partner_id
        expected_id = self.env.ref("l10n_pe.it_DNI" if self.kind == "boleta" else "l10n_pe.it_RUC")
        if (partner != order.partner_id or partner.vat != self.number
                or partner.l10n_latam_identification_type_id != expected_id
                or (partner.company_id and partner.company_id != order.company_id)
                or not partner.name or partner.country_id.code != "PE"
                or (self.kind == "factura" and not partner.street)):
            raise UserError(_("La identidad o dirección fiscal del cliente ya no es válida."))
        if partner.address_get(["invoice"])["invoice"] != partner.id:
            raise UserError(_("El contacto tiene otra dirección de facturación. Revisión contable necesaria."))
        fiscal = self.env["account.fiscal.position"].with_company(order.company_id)._get_fiscal_position(partner)
        if fiscal != order.fiscal_position_id:
            raise UserError(_("La posición fiscal cambió. Revisión contable necesaria."))
        if order.state not in ("paid", "done", "invoiced") or order.amount_total <= 0:
            raise UserError(_("El pedido no es una venta pagada válida."))
        journal = order.config_id.invoice_journal_id
        if (not journal or journal.company_id != order.company_id or journal.type != "sale"
                or not journal.l10n_latam_use_documents or order.company_id.country_id.code != "PE"):
            raise UserError(_("Configure un diario de ventas peruano con documentos en el POS."))
        document = self.env["l10n_latam.document.type"].search([
            ("country_id.code", "=", "PE"), ("code", "=", "03" if self.kind == "boleta" else "01"),
            ("internal_type", "=", "invoice"),
        ], limit=1)
        if not document:
            raise UserError(_("Falta el tipo de documento peruano 01/03 de la localización."))
        return document

    def _validate_existing_invoice(self, invoice):
        document = self._validate_for_invoice()
        if (invoice.state != "posted" or invoice.move_type != "out_invoice"
                or invoice.company_id != self.company_id or invoice.partner_id != self.partner_id
                or invoice.l10n_latam_document_type_id != document
                or invoice.journal_id != self.order_id.config_id.invoice_journal_id
                or invoice.pos_order_ids != self.order_id
                or invoice.currency_id != self.order_id.currency_id
                or not self.order_id.currency_id.is_zero(invoice.amount_total - self.order_id.amount_total)):
            raise UserError(_("El comprobante existente no coincide con la solicitud. Revisión manual necesaria."))

    def _process_pending(self):
        """Private batch integration hook. Same transaction and lock as POS issuance.

        Trusted adapter must call this on each pending request (prefer one job/transaction
        per order); never create another sale/payment/invoice in the adapter.
        Processed means posted in Odoo, never acceptance by SUNAT/OSE.
        """
        self.ensure_one()
        self.order_id._alvina_lock()
        self.invalidate_recordset()
        if self.state != "pending":
            return self._status_payload()
        self.attempts += 1
        try:
            with self.env.cr.savepoint():
                self._validate_for_invoice()
                order = self.order_id.with_company(self.company_id)
                if not order.account_move:
                    order.with_context(generate_pdf=False).action_pos_order_invoice()
                self._validate_existing_invoice(order.account_move)
                self.write({"state": "processed", "invoice_id": order.account_move.id,
                            "processed_at": fields.Datetime.now(), "error_message": False})
        except OperationalError:
            # Let Odoo retry serialization failures/deadlocks at transaction level.
            raise
        except UserError as exc:
            self.write({"state": "failed", "error_message": str(exc)[:2000]})
        except Exception:
            # Unexpected exceptions remain failures, never falsely successful results.
            _logger.exception("ALVIÑA: error processing request id=%s", self.id)
            self.write({"state": "failed", "error_message": _("Error interno. Consulte el registro del servidor.")})
        return self._status_payload()

    def _status_payload(self):
        self.ensure_one()
        invoice = self.order_id.account_move
        can_print = (self.state == "processed" and invoice == self.invoice_id and invoice.state == "posted")
        return {
            "state": self.state, "kind": self.kind, "number": self.number,
            "customer_name": self.partner_id.name, "invoice_name": invoice.name if invoice else "",
            "message": self.error_message or ("Pendiente de procesamiento. No emitido aún." if self.state == "pending"
                                              else "Procesado en Odoo; verifique el estado EDI/SUNAT."),
            "can_print": bool(can_print),
        }
