"""Pure validation; no Odoo or network dependencies."""
import re


def validate_identity(kind, number):
    if kind not in ("boleta", "factura"):
        raise ValueError("Seleccione Boleta o Factura.")
    length = 8 if kind == "boleta" else 11
    if not isinstance(number, str) or not re.fullmatch(r"[0-9]{%d}" % length, number):
        raise ValueError("El documento debe tener %s dígitos ASCII." % length)
    if kind == "factura":
        if number[:2] not in ("10", "15", "16", "17", "20"):
            raise ValueError("Prefijo de RUC inválido.")
        weights = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
        digit = (11 - sum(int(n) * w for n, w in zip(number[:10], weights)) % 11) % 10
        if digit != int(number[-1]):
            raise ValueError("Dígito verificador de RUC inválido.")
    return number


def json_path(payload, path):
    for key in path.split("."):
        if not isinstance(payload, dict) or key not in payload:
            raise ValueError("La respuesta no contiene los campos configurados.")
        payload = payload[key]
    if not isinstance(payload, str) or not payload.strip():
        raise ValueError("La API no devolvió un texto válido.")
    return payload.strip()
