import json
import os
from urllib.parse import urlsplit

import requests

from odoo import fields, models, _
from odoo.exceptions import UserError

from .identity import json_path
from .jsonpe import parse_response, request_spec


class ResCompany(models.Model):
    _inherit = "res.company"

    alvina_emission_mode = fields.Selection(
        [("pending", "Pendiente: integración nocturna"), ("immediate", "Procesar con Odoo")],
        default="pending", required=True, groups="base.group_system", string="Modo de procesamiento",
    )
    alvina_jsonpe_enabled = fields.Boolean(string="Activar consultas JSON.PE", groups="base.group_system")
    alvina_jsonpe_profile = fields.Selection(
        [("official", "JSON.PE — DNI y RUC"), ("custom", "Personalizado (avanzado)")],
        default="official", required=True, groups="base.group_system", string="Perfil de consulta",
    )
    alvina_jsonpe_dni_url = fields.Char(string="URL de consulta DNI", groups="base.group_system")
    alvina_jsonpe_ruc_url = fields.Char(string="URL de consulta RUC", groups="base.group_system")
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
    alvina_jsonpe_token = fields.Char(string="Token de JSON.PE", copy=False, groups="base.group_system")

    def _alvina_lookup_external(self, kind, number):
        """Backend-only transport with the documented JSON.PE contract by default.

        Override privately for provider-specific schemas, OAuth or normalization.
        Called with elevated access only after checking the caller's POS order.
        """
        self.ensure_one()
        if not self.alvina_jsonpe_enabled:
            raise UserError(_("Cliente no encontrado. Configure JSON.PE en la compañía."))
        try:
            default_url, official_data = request_spec(kind, number)
        except ValueError as exc:
            raise UserError(str(exc)) from None
        official = self.alvina_jsonpe_profile == "official"
        url = default_url if official else (
            (self.alvina_jsonpe_dni_url if kind == "boleta" else self.alvina_jsonpe_ruc_url) or ""
        )
        try:
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            valid_url = (parsed.scheme == "https" and (host == "json.pe" or host.endswith(".json.pe"))
                         and not parsed.username and not parsed.password and parsed.port in (None, 443)
                         and not parsed.query and not parsed.fragment)
        except ValueError:
            valid_url = False
        if not valid_url:
            raise UserError(_("Configure una URL HTTPS de JSON.PE sin credenciales ni query string."))
        token = os.environ.get("ALVINA_JSONPE_TOKEN") or self.alvina_jsonpe_token
        if not token or (not official and not all((self.alvina_jsonpe_parameter, self.alvina_jsonpe_name_path,
                                                   self.alvina_jsonpe_number_path, self.alvina_jsonpe_auth_header))):
            raise UserError(_("Faltan credenciales o mapeos del contrato JSON.PE en el servidor."))
        prefix = "Bearer" if official else self.alvina_jsonpe_auth_prefix
        auth_header = "Authorization" if official else self.alvina_jsonpe_auth_header
        value = " ".join(filter(None, (prefix, token)))
        headers = {auth_header: value, "Accept": "application/json"}
        data = official_data if official else {self.alvina_jsonpe_parameter: number}
        method = "POST" if official else self.alvina_jsonpe_method
        try:
            with requests.request(
                method, url, headers=headers,
                params=data if method == "GET" else None,
                json=data if method == "POST" else None,
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
                payload = json.loads(b"".join(chunks))
            if official:
                return parse_response(kind, number, payload)
            if not isinstance(payload, dict) or payload.get("success") is not True:
                raise ValueError("Unsuccessful provider response")
            if json_path(payload, self.alvina_jsonpe_number_path) != number:
                raise ValueError("Document mismatch")
            return {
                "name": json_path(payload, self.alvina_jsonpe_name_path),
                "street": json_path(payload, self.alvina_jsonpe_street_path)
                if self.alvina_jsonpe_street_path else "",
            }
        except (requests.RequestException, ValueError, TypeError):
            raise UserError(_("No se pudo validar la identidad con JSON.PE. Revise la configuración o reintente.")) from None
