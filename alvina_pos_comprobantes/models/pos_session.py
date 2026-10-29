from datetime import timedelta

from odoo import fields, models, _
from odoo.exceptions import AccessError, UserError

from .identity import validate_identity


class PosSession(models.Model):
    _inherit = "pos.session"

    def _alvina_check_customer_access(self):
        self.ensure_one()
        self.check_access("write")
        if (not self.env.user.has_group("point_of_sale.group_pos_user")
                or self.company_id not in self.env.companies
                or (self.user_id != self.env.user
                    and not self.env.user.has_group("point_of_sale.group_pos_manager"))):
            raise AccessError(_("No tiene acceso a esta caja."))
        if self.state != "opened" or self.company_id.country_id.code != "PE":
            raise UserError(_("Se requiere una sesión POS abierta de una compañía peruana."))

    def alvina_lookup_customer(self, kind, number):
        self._alvina_check_customer_access()
        try:
            validate_identity(kind, number)
        except ValueError as exc:
            raise UserError(str(exc)) from None
        company = self.company_id.sudo()
        partner = company._alvina_partner(kind, number)
        data = ({"name": partner.name, "street": partner.street or ""} if partner
                else company._alvina_lookup_external(kind, number))
        if not data.get("name") or (kind == "factura" and not data.get("street")):
            raise UserError(_("Faltan el nombre o la dirección fiscal del cliente."))
        preview = self.env["alvina.pos.identity"].sudo().create({
            "session_id": self.id, "requested_by": self.env.uid, "kind": kind, "number": number,
            "name": data["name"], "street": data.get("street", ""), "partner_id": partner.id,
            "ubigeo": data.get("ubigeo_sunat", ""),
        })
        return {"identity_id": preview.id, "name": preview.name, "street": preview.street or "",
                "number": number, "kind": kind}

    def alvina_confirm_customer(self, identity_id):
        self._alvina_check_customer_access()
        if not isinstance(identity_id, int) or isinstance(identity_id, bool):
            raise UserError(_("Consulte primero el DNI/RUC."))
        preview = self.env["alvina.pos.identity"].sudo().browse(identity_id).exists()
        if (not preview or preview.session_id != self or preview.requested_by != self.env.user
                or preview.create_date < fields.Datetime.now() - timedelta(hours=1)):
            raise UserError(_("La consulta venció o no corresponde a esta caja. Consulte nuevamente."))
        self.company_id.sudo()._alvina_get_edi_format(self.config_id.invoice_journal_id)
        partner = self.company_id.sudo()._alvina_confirm_identity(preview)
        return {"partner_id": partner.id, "kind": preview.kind}
