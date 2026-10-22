import os
from urllib.parse import urlsplit

import requests

from odoo import fields, models, _
from odoo.exceptions import UserError

from .identity import json_path


class ResCompany(models.Model):
    _inherit = "res.company"

    alvina_emission_mode = fields.Selection(
        [("pending", "Pendiente: integración nocturna"), ("immediate", "Procesar con Odoo")],
        default="pending", required=True, groups="base.group_system",
    )
    alvina_jsonpe_enabled = fields.Boolean(groups="base.group_system")
    alvina_jsonpe_dni_url = fields.Char(groups="base.group_system")
    alvina_jsonpe_ruc_url = fields.Char(groups="base.group_system")
    alvina_jsonpe_method = fields.Selection(
        [("GET", "GET (query string)"), ("POST", "POST (JSON)")],
        default="POST", required=True, groups="base.group_system",
    )
    alvina_jsonpe_parameter = fields.Char(default="numero", groups="base.group_system")
    alvina_jsonpe_name_path = fields.Char(groups="base.group_system")
    alvina_jsonpe_number_path = fields.Char(groups="base.group_system")
    alvina_jsonpe_street_path = fields.Char(groups="base.group_system")
    alvina_jsonpe_auth_header = fields.Char(default="Authorization", groups="base.group_system")
    alvina_jsonpe_auth_prefix = fields.Char(default="Bearer", groups="base.group_system")
    alvina_jsonpe_token = fields.Char(copy=False, groups="base.group_system")

    def _alvina_lookup_external(self, kind, number):
        """Configurable transport, NOT an assumed JSON.PE API contract.

        Override privately for provider-specific schemas, OAuth or normalization.
        Called with elevated access only after checking the caller's POS order.
        """
        self.ensure_one()
        if not self.alvina_jsonpe_enabled:
            raise UserError(_("Cliente no encontrado. Configure JSON.PE en la compañía."))
        url = self.alvina_jsonpe_dni_url if kind == "boleta" else self.alvina_jsonpe_ruc_url
        parsed = urlsplit(url or "")
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or not (host == "json.pe" or host.endswith(".json.pe"))
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.query or parsed.fragment):
            raise UserError(_("Configure una URL HTTPS de JSON.PE sin credenciales ni query string."))
        token = os.environ.get("ALVINA_JSONPE_TOKEN") or self.alvina_jsonpe_token
        if not token or not all((self.alvina_jsonpe_parameter, self.alvina_jsonpe_name_path,
                                  self.alvina_jsonpe_number_path, self.alvina_jsonpe_auth_header)):
            raise UserError(_("Faltan credenciales o mapeos del contrato JSON.PE en el servidor."))
        value = " ".join(filter(None, (self.alvina_jsonpe_auth_prefix, token)))
        headers = {self.alvina_jsonpe_auth_header: value, "Accept": "application/json"}
        data = {self.alvina_jsonpe_parameter: number}
        try:
            with requests.request(
                self.alvina_jsonpe_method, url, headers=headers,
                params=data if self.alvina_jsonpe_method == "GET" else None,
                json=data if self.alvina_jsonpe_method == "POST" else None,
                timeout=(3.05, 10), allow_redirects=False, stream=True,
            ) as response:
                if response.status_code != 200:
                    raise ValueError("Unexpected response")
                # Bound response size without logging provider data or credentials.
                chunks, size = [], 0
                for chunk in response.iter_content(8192):
                    size += len(chunk)
                    if size > 65536:
                        raise ValueError("Response too large")
                    chunks.append(chunk)
                import json
                payload = json.loads(b"".join(chunks))
            if json_path(payload, self.alvina_jsonpe_number_path) != number:
                raise ValueError("Document mismatch")
            return {
                "name": json_path(payload, self.alvina_jsonpe_name_path),
                "street": json_path(payload, self.alvina_jsonpe_street_path)
                if self.alvina_jsonpe_street_path else "",
            }
        except (requests.RequestException, ValueError, TypeError):
            raise UserError(_("No se pudo validar la identidad con JSON.PE. Revise la configuración o reintente.")) from None
