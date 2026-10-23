{
    "name": "ALVIÑA POS — Boleta / Factura",
    "version": "19.0.1.1.0",
    "category": "Sales/Point of Sale",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "l10n_pe"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "security/request_rules.xml",
        "views/res_company_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "alvina_pos_comprobantes/static/src/js/document_dialog.js",
            "alvina_pos_comprobantes/static/src/js/receipt_screen.js",
            "alvina_pos_comprobantes/static/src/xml/receipt_screen.xml",
            "alvina_pos_comprobantes/static/src/xml/document_dialog.xml",
        ],
    },
    "installable": True,
    "application": False,
}
