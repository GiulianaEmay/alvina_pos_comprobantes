from datetime import timedelta

from odoo import fields, models, _
from odoo.exceptions import AccessError, UserError

from .identity import validate_identity


class PosOrder(models.Model):
    _inherit = "pos.order"

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
        identification = self.env.ref("l10n_pe.it_DNI" if kind == "boleta" else "l10n_pe.it_RUC")
        partners = self.env["res.partner"].sudo().with_context(active_test=False).search([
            ("vat", "=", number),
            ("company_id", "in", [False, self.company_id.id]),
        ], limit=2)
        if len(partners) > 1:
            raise UserError(_("Existen contactos duplicados con este documento. Corríjalos antes de emitir."))
        if partners and (not partners.active or partners.country_id.code != "PE"
                         or partners.l10n_latam_identification_type_id != identification):
            raise UserError(_("El documento ya existe en un contacto archivado o con país/tipo incorrecto. Revíselo en Contactos."))
        return partners

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
            return {"state": "existing", "message": _("Este pedido ya tiene un comprobante. Revíselo en Odoo."),
                    "invoice_name": self.account_move.sudo().name, "can_print": False}
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
            return request._status_payload()
        if self.account_move:
            raise UserError(_("El pedido ya tiene un comprobante. No se creará otro."))
        # Serialize partner creation across different orders requesting the same identity.
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["alvina:" + preview.number])
        partner = self._alvina_partner(preview.kind, preview.number)
        if partner and (partner.name != preview.name or (partner.street or "") != (preview.street or "")):
            raise UserError(_("El contacto cambió desde la consulta. Consulte nuevamente."))
        if not partner:
            partner = self.env["res.partner"].sudo().with_company(self.company_id).create({
                "name": preview.name, "street": preview.street,
                "vat": preview.number, "country_id": self.env.ref("base.pe").id,
                "company_id": self.company_id.id,
                "is_company": preview.kind == "factura",
                "l10n_latam_identification_type_id": self.env.ref(
                    "l10n_pe.it_DNI" if preview.kind == "boleta" else "l10n_pe.it_RUC").id,
            })
        # Do not recalculate prices, taxes or fiscal positions on a completed sale.
        # Reject a partner whose fiscal position would require changing this sale.
        fiscal = self.env["account.fiscal.position"].sudo().with_company(self.company_id)._get_fiscal_position(partner)
        if fiscal != self.fiscal_position_id:
            raise UserError(_("La posición fiscal del cliente no coincide con la venta. Revisión contable necesaria."))
        request = self.env["alvina.pos.document.request"].sudo().create({
            "order_id": self.id, "requested_by": self.env.uid, "kind": preview.kind,
            "number": preview.number, "partner_id": partner.id,
        })
        self.write({"partner_id": partner.id})
        if self.company_id.sudo().alvina_emission_mode == "immediate":
            request._process_pending()
        return request._status_payload()

    def alvina_print_document(self):
        self._alvina_check_access()
        request = self._alvina_request()
        if not request or not request._status_payload()["can_print"]:
            raise UserError(_("No existe un comprobante contabilizado listo para imprimir."))
        # Same download API used by Odoo 19's account_move POS service.
        # The official download controller retains the caller's access checks.
        return self.account_move.action_invoice_download_pdf()

    def alvina_retry_document(self):
        self._alvina_check_access()
        if not self.env.user.has_group("point_of_sale.group_pos_manager"):
            raise AccessError(_("Solo un administrador POS puede reintentar."))
        self._alvina_lock()
        request = self._alvina_request()
        if not request or request.state != "failed":
            raise UserError(_("No hay solicitud fallida para reintentar."))
        request.write({"state": "pending", "error_message": False})
        if self.company_id.sudo().alvina_emission_mode == "immediate":
            request._process_pending()
        return request._status_payload()

    def _prepare_invoice_vals(self):
        if len(self) != 1:
            if self.env["alvina.pos.document.request"].sudo().search_count([("order_id", "in", self.ids)]):
                raise UserError(_("Procese las solicitudes ALVIÑA individualmente, sin agrupar pedidos."))
            return super()._prepare_invoice_vals()
        values = super()._prepare_invoice_vals()
        request = self._alvina_request()
        if request:
            document = request._validate_for_invoice()
            values["l10n_latam_document_type_id"] = document.id
        return values
