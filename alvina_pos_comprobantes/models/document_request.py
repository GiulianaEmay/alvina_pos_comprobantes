import logging

from psycopg2 import OperationalError

from odoo import fields, models, _
from odoo.exceptions import LockError, UserError
from odoo.tools import html2plaintext

from .identity import validate_identity

_logger = logging.getLogger(__name__)


class AlvinaPosIdentity(models.TransientModel):
    _name = "alvina.pos.identity"
    _description = "Consulta temporal de identidad ALVIÑA"
    _transient_max_hours = 1

    order_id = fields.Many2one("pos.order", ondelete="cascade")
    session_id = fields.Many2one("pos.session", ondelete="cascade")
    requested_by = fields.Many2one("res.users", required=True)
    kind = fields.Selection([("boleta", "Boleta"), ("factura", "Factura")], required=True)
    number = fields.Char(required=True)
    name = fields.Char(required=True)
    street = fields.Char()
    ubigeo = fields.Char()
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
    edi_format_id = fields.Many2one("account.edi.format", ondelete="restrict", readonly=True)
    attempts = fields.Integer(readonly=True)
    send_attempts = fields.Integer(readonly=True)
    send_uncertain = fields.Boolean(readonly=True)
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
        fiscal = order._alvina_fiscal_position(partner)
        if fiscal != order.fiscal_position_id:
            raise UserError(_("La posición fiscal cambió. Revisión contable necesaria."))
        if order.state not in ("paid", "done", "invoiced") or order.amount_total <= 0:
            raise UserError(_("El pedido no es una venta pagada válida."))
        journal = order._alvina_invoice_journal()
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
                or invoice.journal_id != self.order_id._alvina_invoice_journal()
                or invoice.pos_order_ids != self.order_id
                or invoice.currency_id != self.order_id.currency_id
                or not self.order_id.currency_id.is_zero(invoice.amount_total - self.order_id.amount_total)):
            raise UserError(_("El comprobante existente no coincide con la solicitud. Revisión manual necesaria."))

    def _process_pending(self):
        """First RPC: post/reconcile the original order before any EDI web call.

        Kept under its original name for compatibility. The POS immediately follows
        with alvina_send_document in a SECOND RPC, after this invoice has committed.
        A provider timeout must never roll back the invoice and allocate a new number.
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
                if not self.edi_format_id:
                    self.edi_format_id = self.company_id._alvina_get_edi_format(order._alvina_invoice_journal())
                if not order.account_move:
                    order.with_context(
                        generate_pdf=False, skip_account_edi_cron_trigger=True,
                    ).action_pos_order_invoice()
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

    def _edi_document(self):
        self.ensure_one()
        invoice = self.order_id.account_move
        if not invoice or invoice != self.invoice_id or invoice.state != "posted":
            return self.env["account.edi.document"]
        return invoice.edi_document_ids.filtered(lambda doc: doc.edi_format_id == self.edi_format_id)

    def _send_now(self, retry=False):
        """Second RPC: send this invoice's registered EDI document synchronously."""
        self.ensure_one()
        self.order_id._alvina_lock()
        self.invalidate_recordset()
        documents = self._edi_document()
        if len(documents) != 1:
            raise UserError(_("El comprobante no tiene un documento electrónico compatible. Revíselo en Contabilidad."))
        try:
            # Same lock order as the official EDI engine. Resolve contention
            # before entering the block in which a provider may be contacted.
            documents.lock_for_update()
            self.invoice_id.lock_for_update()
            documents.attachment_id.filtered(lambda attachment: not attachment.res_model and not attachment.res_id).lock_for_update()
        except LockError:
            raise UserError(_("Otro proceso está enviando este comprobante. Actualice su estado antes de volver a intentarlo.")) from None
        documents.invalidate_recordset(["state", "error", "blocking_level"])
        if documents.state == "sent":
            return self._status_payload()
        if documents.state != "to_send":
            raise UserError(_("El comprobante está anulado o en proceso de anulación. No se volverá a emitir."))
        if self.send_uncertain:
            raise UserError(_(
                "El resultado del envío anterior no está confirmado. Verifique ese mismo "
                "número en Contabilidad/SUNAT antes de autorizar otro envío. No cree otro comprobante."
            ))
        if documents.error and not retry:
            return self._status_payload()
        edi_format = documents.edi_format_id
        applicability = edi_format._get_move_applicability(self.invoice_id)
        # Odoo's generic EDI engine treats a missing callback as a successful
        # no-op. A fiscal receipt must have an actual web-service sender.
        if (edi_format not in self.invoice_id.journal_id.edi_format_ids
                or not edi_format._needs_web_services()
                or not isinstance(applicability, dict) or not callable(applicability.get("post"))):
            message = _(
                "El formato electrónico del comprobante no tiene un envío web válido habilitado en su diario. "
                "Revise la configuración del proveedor en Contabilidad. Esta operación no realizó el envío; el comprobante conserva su número."
            )
            # Persist a known configuration failure, including the official cron
            # exclusion. Raising here would roll that protection back in the RPC.
            documents.write({"blocking_level": "error", "error": message})
            self.error_message = message
            return self._status_payload()
        if retry:
            # Official retry reset; never delete/recreate the fiscal document.
            self.invoice_id._retry_edi_documents_error()
        self.send_attempts += 1
        self.error_message = False
        try:
            with self.env.cr.savepoint():
                # Verified Odoo 19 API. Restrict processing to the selected format
                # and do not allow it to commit unrelated work.
                documents.with_context(skip_pe_pos_immediate_send=False)._process_documents_web_services(with_commit=False)
        except OperationalError:
            raise
        except Exception:
            _logger.error("ALVIÑA: unconfirmed EDI result for request id=%s", self.id)
            message = _(
                "No se confirmó la respuesta del proveedor electrónico. El comprobante conserva "
                "su número; actualice el estado o revíselo en Contabilidad antes de reenviar."
            )
            self.write({"send_uncertain": True, "error_message": message})
            # The official cron does not inspect our request model. Its own
            # blocking flag must also prevent an automatic ambiguous resend.
            documents.write({"blocking_level": "error", "error": message})
        return self._status_payload()

    def _status_payload(self):
        self.ensure_one()
        invoice = self.order_id.account_move
        documents = self._edi_document()
        state = self.state
        message = self.error_message or _("El comprobante todavía no está preparado.")
        can_send = False
        if self.state == "processed":
            if len(documents) != 1:
                state, message = "edi_error", _("Falta el documento electrónico del proveedor. Revise el comprobante en Contabilidad.")
            elif documents.state in ("cancelled", "to_cancel"):
                state, message = "cancelled", _("Comprobante anulado o pendiente de anulación.")
            elif documents.state == "sent" and not documents.error:
                state, message = "sent", _("Comprobante electrónico enviado según el estado del proveedor registrado en Odoo.")
            elif self.send_uncertain:
                state = "unknown"
            elif documents.error:
                state, message = "edi_error", html2plaintext(documents.error)[:2000]
            else:
                state, message = "to_send", _("Comprobante preparado. Pendiente de respuesta del proveedor electrónico.")
                can_send = True
        can_print = state == "sent"
        return {
            "state": state, "kind": self.kind, "number": self.number,
            "customer_name": self.partner_id.name, "invoice_name": invoice.name if invoice else "",
            "message": message, "can_send": can_send,
            "can_prepare": not invoice and self.state in ("pending", "failed"),
            "can_retry_edi": state == "edi_error" and bool(documents) and documents.state == "to_send",
            "can_print": bool(can_print),
        }
