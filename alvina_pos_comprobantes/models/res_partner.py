from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    alvina_pos_fiscal_identity = fields.Boolean(
        string="Referencia fiscal interna del POS", copy=False, index=True,
        groups="base.group_system",
        help="Ficha archivada creada automáticamente para emitir desde el POS; "
             "no aparece en las listas habituales de Contactos/clientes del POS.",
    )
    alvina_pos_is_internal = fields.Boolean(compute="_compute_alvina_pos_is_internal", compute_sudo=True)

    @api.depends("alvina_pos_fiscal_identity")
    def _compute_alvina_pos_is_internal(self):
        for partner in self:
            partner.alvina_pos_is_internal = partner.alvina_pos_fiscal_identity

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ["alvina_pos_is_internal"]
