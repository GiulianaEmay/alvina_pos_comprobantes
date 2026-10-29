from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .identity import validate_identity


class PosOrder(models.Model):
    _inherit = "pos.order"

    alvina_document_kind = fields.Selection([("boleta", "Boleta"), ("factura", "Factura")], copy=False)

    @api.model
    def _load_pos_data_fields(self, config):
        names = super()._load_pos_data_fields(config)
        # Empty means ALL model fields in the official loader, not no fields.
        return names + ["alvina_document_kind"] if names else names

    def _alvina_check_access(self):
        self.ensure_one()
        if not self.exists() or not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("Se requiere acceso al Punto de Venta."))
        self.check_access("write")
        if self.company_id not in self.env.companies:
            raise AccessError(_("Compañía no autorizada."))
        if (self.session_id.user_id != self.env.user
                and not self.env.user.has_group("point_of_sale.group_pos_manager")):
            raise AccessError(_("Solo el responsable de la sesión o un administrador POS puede emitir."))
        if self.company_id.country_id.code != "PE":
            raise UserError(_("Este flujo requiere una compañía peruana."))
        if self.state not in ("paid", "done", "invoiced") or self.amount_total <= 0:
            raise UserError(_("Se requiere una venta pagada y sincronizada, de importe positivo."))

    def _alvina_lock(self):
        # Every addon entry point and the documented batch adapter lock in this order.
        self.env.cr.execute("SELECT id FROM pos_order WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset()

    def _alvina_request(self):
        return self.env["alvina.pos.document.request"].sudo().search([("order_id", "=", self.id)], limit=1)

    def _alvina_partner(self, kind, number):
        return self.company_id.sudo()._alvina_partner(kind, number)

    def _alvina_existing_values(self):
        self.ensure_one()
        invoice = self.account_move.sudo()
        if (invoice.state != "posted" or invoice.company_id != self.company_id
                or invoice.pos_order_ids != self or invoice.l10n_latam_document_type_id.code not in ("01", "03")):
            raise UserError(_("El comprobante existente requiere revisión en Contabilidad. No se emitirá otro."))
        edi_format = self.company_id.sudo()._alvina_get_edi_format(invoice.journal_id)
        return {"order_id": self.id, "requested_by": self.env.uid, "partner_id": invoice.partner_id.id,
                "kind": "factura" if invoice.l10n_latam_document_type_id.code == "01" else "boleta",
                "number": invoice.partner_id.vat or invoice.name, "state": "processed",
                "invoice_id": invoice.id, "edi_format_id": edi_format.id}

    def alvina_lookup_identity(self, kind, number):
        self._alvina_check_access()
        try:
            validate_identity(kind, number)
        except ValueError as exc:
            raise UserError(str(exc)) from None
        partner = self._alvina_partner(kind, number)
        data = ({"name": partner.name, "street": partner.street or ""} if partner
                else self.company_id.sudo()._alvina_lookup_external(kind, number))
        if not data.get("name") or (kind == "factura" and not data.get("street")):
            raise UserError(_("Se requieren nombres o razón social y, para factura, dirección fiscal."))
        preview = self.env["alvina.pos.identity"].sudo().create({
            "order_id": self.id, "requested_by": self.env.uid, "kind": kind, "number": number,
            "name": data["name"], "street": data.get("street", ""), "partner_id": partner.id,
        })
        return {"identity_id": preview.id, "name": preview.name,
                "street": preview.street or "", "number": number, "kind": kind}

    def alvina_document_status(self):
        self._alvina_check_access()
        request = self._alvina_request()
        if request:
            return request._status_payload()
        if self.account_move:
            # Read-only snapshot: reopening a ticket never creates/emits another invoice.
            return self.env["alvina.pos.document.request"].sudo().new(self._alvina_existing_values())._status_payload()
        return {"state": "none", "can_print": False}

    def alvina_submit_document(self, identity_id):
        self._alvina_check_access()
        self._alvina_lock()
        self._alvina_check_access()
        if not isinstance(identity_id, int) or isinstance(identity_id, bool):
            raise UserError(_("Consulte primero la identidad del cliente."))
        preview = self.env["alvina.pos.identity"].sudo().browse(identity_id).exists()
        if (not preview or preview.order_id != self or preview.requested_by != self.env.user
                or preview.create_date < fields.Datetime.now() - timedelta(hours=1)):
            raise UserError(_("La consulta venció o no pertenece a este pedido. Consulte de nuevo."))
        request = self._alvina_request()
        if request:
            if (request.kind, request.number) != (preview.kind, preview.number):
                raise UserError(_("El pedido ya tiene una solicitud para otro documento."))
            if request.state == "pending":
                request._process_pending()
            return request._status_payload()
        if self.account_move:
            raise UserError(_("El pedido ya tiene un comprobante. No se creará otro."))
        partner = self.company_id.sudo()._alvina_confirm_identity(preview)
        # Do not recalculate prices, taxes or fiscal positions on a completed sale.
        # Reject a partner whose fiscal position would require changing this sale.
        fiscal = self.env["account.fiscal.position"].sudo().with_company(self.company_id)._get_fiscal_position(partner)
        if fiscal != self.fiscal_position_id:
            raise UserError(_("La posición fiscal del cliente no coincide con la venta. Revisión contable necesaria."))
        edi_format = self.company_id.sudo()._alvina_get_edi_format(self.config_id.invoice_journal_id)
        request = self.env["alvina.pos.document.request"].sudo().create({
            "order_id": self.id, "requested_by": self.env.uid, "kind": preview.kind,
            "number": preview.number, "partner_id": partner.id, "edi_format_id": edi_format.id,
        })
        self.write({"partner_id": partner.id})
        request._process_pending()
        return request._status_payload()

    def alvina_send_document(self):
        self._alvina_check_access()
        self._alvina_lock()
        request = self._alvina_request()
        if not request and self.account_move:
            request = self.env["alvina.pos.document.request"].sudo().create(self._alvina_existing_values())
        if not request or request.state != "processed":
            raise UserError(_("Prepare primero el comprobante del pedido."))
        return request._send_now()

    def alvina_retry_edi(self):
        self._alvina_check_access()
        if not self.env.user.has_group("point_of_sale.group_pos_manager"):
            raise AccessError(_("Solo un administrador POS puede autorizar el reenvío electrónico."))
        request = self._alvina_request()
        if not request or request.state != "processed":
            raise UserError(_("No existe un comprobante para reenviar."))
        return request._send_now(retry=True)

    def alvina_print_document(self):
        self._alvina_check_access()
        if not self.alvina_document_status().get("can_print"):
            raise UserError(_("El proveedor electrónico todavía no confirmó el envío de este comprobante."))
        invoice = self.account_move.sudo().with_company(self.company_id)
        if not invoice.invoice_pdf_report_id:
            # Generate the localized invoice PDF (with its electronic data), not
            # the POS ticket or a proforma. No unsolicited customer email.
            self.env["account.move.send"].sudo().with_company(self.company_id)._generate_and_send_invoices(
                invoice, sending_methods=[], allow_raising=False, allow_fallback_pdf=False,
            )
        if not invoice.invoice_pdf_report_id:
            raise UserError(_("El comprobante fue enviado, pero no se pudo generar su PDF. Revíselo en Contabilidad; no vuelva a emitir."))
        # Same download API used by Odoo 19's account_move POS service.
        # The official download controller retains the caller's access checks.
        return self.account_move.action_invoice_download_pdf()

    def alvina_retry_document(self):
        self._alvina_check_access()
        self._alvina_lock()
        request = self._alvina_request()
        if not request or request.state not in ("pending", "failed"):
            raise UserError(_("No hay un comprobante pendiente de preparar."))
        if request.state == "failed" and not self.env.user.has_group("point_of_sale.group_pos_manager"):
            raise AccessError(_("Solo un administrador POS puede reintentar una preparación fallida."))
        request.write({"state": "pending", "error_message": False})
        request._process_pending()
        return request._status_payload()

    def _prepare_invoice_vals(self):
        if len(self) != 1:
            if self.filtered("alvina_document_kind") or self.env["alvina.pos.document.request"].sudo().search_count([("order_id", "in", self.ids)]):
                raise UserError(_("Procese las solicitudes ALVIÑA individualmente, sin agrupar pedidos."))
            return super()._prepare_invoice_vals()
        values = super()._prepare_invoice_vals()
        request = self._alvina_request()
        if request:
            document = request._validate_for_invoice()
            values["l10n_latam_document_type_id"] = document.id
        elif self.alvina_document_kind:
            kind, partner = self.alvina_document_kind, self.partner_id
            try:
                validate_identity(kind, partner.vat)
            except ValueError as exc:
                raise UserError(str(exc)) from None
            identification = self.env.ref("l10n_pe.it_DNI" if kind == "boleta" else "l10n_pe.it_RUC")
            if (partner.l10n_latam_identification_type_id != identification or partner.country_id.code != "PE"
                    or (kind == "factura" and not partner.street)
                    or values["partner_id"] != partner.id):
                raise UserError(_("Los datos fiscales del cliente no coinciden con el comprobante seleccionado."))
            self.company_id.sudo()._alvina_get_edi_format(self.config_id.invoice_journal_id)
            document = self.env["l10n_latam.document.type"].search([
                ("country_id.code", "=", "PE"), ("code", "=", "03" if kind == "boleta" else "01"),
                ("internal_type", "=", "invoice"),
            ], limit=1)
            if not document:
                raise UserError(_("Falta el tipo de comprobante peruano seleccionado."))
            values["l10n_latam_document_type_id"] = document.id
        return values
