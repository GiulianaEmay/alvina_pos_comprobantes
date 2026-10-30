# ALVIÑA POS

Primero se cobra y se entrega el ticket de atención habitual. Al final, en la
pantalla de pago exitoso, Boleta/Factura consulta el DNI/RUC y muestra los datos.
Confirmar y emitir genera el comprobante fiscal del mismo pedido, lo envía mediante
la integración SUNAT/OSE de Odoo y abre su PDF cuando se confirma el envío.
Se obtienen dos documentos: el ticket de atención y la boleta o factura fiscal.
No requiere alta manual de contactos ni un proceso nocturno.

Los clientes nuevos quedan como identidades fiscales internas archivadas.
Consulte el README del repositorio para instalación, actualización y pruebas.
Dependencias: point_of_sale, l10n_pe, account_edi, requests.
