"""JSON.PE contract from the supplied DNI/RUC OpenAPI documentation.

No credentials, network calls or Odoo dependencies in this module.
"""
from .identity import json_path, validate_identity


def request_spec(kind, number):
    validate_identity(kind, number)
    key = "dni" if kind == "boleta" else "ruc"
    return f"https://api.json.pe/api/{key}", {key: number}


def parse_response(kind, number, payload):
    validate_identity(kind, number)
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("JSON.PE no confirmó una consulta exitosa.")
    number_path = "data.numero" if kind == "boleta" else "data.ruc"
    name_path = "data.nombre_completo" if kind == "boleta" else "data.nombre_o_razon_social"
    if json_path(payload, number_path) != number:
        raise ValueError("El documento devuelto no coincide con el consultado.")
    name = json_path(payload, name_path)
    # DNI documentation permits absent/empty address. RUC needs a fiscal address.
    data = payload["data"]
    street = ""
    for key in ("direccion_completa", "direccion"):
        value = data.get(key)
        if isinstance(value, str) and value.strip() and value.strip() != "-":
            street = value.strip()
            break
    if kind == "factura" and not street:
        raise ValueError("JSON.PE no devolvió una dirección fiscal válida.")
    return {"name": name, "street": street}
