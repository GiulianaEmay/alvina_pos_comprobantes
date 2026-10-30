# ALVIÑA POS — Boleta/Factura para Odoo 19

**Versión 19.0.3.0.1.** Ticket de atención primero y emisión fiscal al final del
cobro. El addon instalable está dentro de `alvina_pos_comprobantes/`.

## Flujo de caja

1. La caja cobra normalmente y Odoo genera/imprime el **ticket de atención**.
   No se solicita DNI/RUC para facturar en la pantalla de pago.
2. En **Pago exitoso**, debajo de **Imprimir recibo completo** y **Imprimir recibo
   básico**, se pulsa el único botón **Boleta/Factura**.
3. Dentro de esa ventana se elige **Boleta (03)** y DNI de 8 dígitos, o **Factura
   (01)** y RUC de 11. Al completar el número se consultan automáticamente los
   datos. Se busca primero en Odoo; si no existe, el backend consulta JSON.PE.
4. Se revisan el nombre/razón social y la dirección y se pulsa **Confirmar y emitir**.
   Se factura el mismo pedido ya pagado, se envía su documento electrónico con el
   proveedor configurado en Odoo y se abre el PDF cuando Odoo confirma el envío.
   Estos pasos se encadenan desde esa única confirmación.
5. El **ticket de atención** y la **boleta/factura fiscal** son dos documentos de
   una sola venta. No se registra otro pedido ni se vuelve a cobrar. Una nueva
   apertura de Boleta/Factura muestra ese mismo comprobante y permite reimprimirlo.

No se abre Contactos ni se rellena su formulario. Si el cliente no existe, Odoo
necesita una referencia `res.partner` para la factura: se crea **archivada**, marcada
como identidad fiscal interna, fuera de las búsquedas habituales de Contactos y
clientes del POS. Se reutiliza posteriormente. Los contactos ya existentes se
reutilizan sin archivarlos. El registro contable interno sigue siendo necesario.

Si el ticket **ya tenía una boleta/factura**, el diálogo recupera el documento
existente; no cambia su DNI/RUC ni crea otro. Los pedidos anteriores a esta versión
que ya fueron facturados requieren su revisión contable si se desea corregirlos.
El nuevo flujo evita generar el comprobante fiscal durante el cobro: primero se
confirma la identidad en la pantalla del recibo.

## Instalación y actualización

Requisitos: Odoo 19, `point_of_sale`, `l10n_pe`, `account_edi`, `requests` y la
integración electrónica peruana configurada en los diarios de facturación del POS.
`account_edi` es el motor oficial; no proporciona por sí solo certificados ni un
proveedor SUNAT. Se detecta el formato de `l10n_pe_edi` habilitado en el diario.
Otro proveedor compatible puede seleccionarse en **Compañías → ALVIÑA POS → Formato
electrónico SUNAT/OSE**. No se implementa un emisor SUNAT alternativo.

1. Reemplazar la carpeta completa del addon en el `addons_path`.
2. Reiniciar Odoo y **actualizar el módulo** en Aplicaciones (o con `-u
   alvina_pos_comprobantes` en el procedimiento del partner).
3. Recargar completamente el POS. Verificar primero con una base de prueba.

No basta con reiniciar: esta versión añade `pos.order.alvina_receipt_first` y cambia
los assets. Se retiran el botón fiscal y el diálogo de la pantalla de pago. El
botón Boleta/Factura se encuentra únicamente al final, en la pantalla del recibo.
Las devoluciones y las compañías no peruanas mantienen su validación nativa.
En ventas positivas peruanas se conserva el cobro y la impresión nativos, pero se
aplaza la creación inmediata de la factura fiscal hasta la pantalla del recibo. El
marcador se asigna al sincronizar nuevas ventas pagadas, sin modificar ventas ya
facturadas. La validación normal y el pago rápido usan el mismo hook oficial
`OrderPaymentValidation`. Se mantiene visible ReceiptScreen aunque esté activado
saltar esa pantalla, para ofrecer el botón al final del cobro.

Si el proveedor no utiliza `account_edi`, debe conectarse su API real; el addon
muestra un error de configuración. El modo nocturno anterior se conserva como
campo de compatibilidad y no dirige la emisión desde el botón.

### Integración con el repositorio aportado de ALVIÑA

`alvinha_point_of_sale` hereda `PaymentScreenButtons`: se conserva el árbol nativo
para sus selectores de herencia. Se oculta su opción de facturación en ventas
positivas peruanas y el botón fiscal se ofrece únicamente en ReceiptScreen.

Ese módulo selecciona diarios con `pos.config._get_journal(partner,
refunded_order_id)`. Se utiliza ese selector real cuando está disponible, incluido
el diario de boletas. Sin ese módulo se utiliza `invoice_journal_id`. La preparación,
el formato EDI y la comprobación del resultado deben usar el mismo diario; la
versión anterior comprobaba siempre el de facturas.

El cron aportado `cron_generate_auto_invoices()` selecciona pedidos con
`to_invoice=True` y sin factura. Se conserva esa preferencia cuando ya estaba
marcada o cuando el método de pago define `auto_invoice`: se desactiva únicamente
durante el procesamiento inicial que imprimirá el ticket, y se restaura para su
proceso automático posterior. El frontend no intenta descargar una factura que
todavía no existe. El botón del recibo puede emitir inmediatamente, sin esperar
al cron. `_generate_pos_order_invoice` utiliza un bloqueo y recupera el documento
existente para que el botón y el proceso posterior no creen dos facturas.
Si el lote ya facturó el ticket, el botón muestra ese documento; no le cambia el
cliente ni lo sustituye. No se desactiva el proceso nocturno del partner.

El código aportado también utiliza `skip_pe_pos_immediate_send` durante la creación
de facturas. La emisión solicitada en el recibo procesa después el documento EDI
en otro RPC. La compatibilidad integral con Enterprise/proveedor y el cron real
requiere validación en la instalación del partner.

## JSON.PE

En **Ajustes → Usuarios y compañías → Compañías → su compañía → ALVIÑA POS**:
seleccione **JSON.PE — DNI y RUC**, guarde el token sin `Bearer` y active las consultas.
No necesita ingresar URL ni rutas JSON en ese perfil.

| Consulta | Solicitud | Respuesta utilizada |
| --- | --- | --- |
| DNI / Boleta | POST `https://api.json.pe/api/dni`, JSON con clave `dni` | `data.numero`, `data.nombre_completo` |
| RUC / Factura | POST `https://api.json.pe/api/ruc`, JSON con clave `ruc` | `data.ruc`, `data.nombre_o_razon_social` |

Se envía `Authorization: Bearer <token>` solo desde el servidor. Se exige HTTP 200,
`success: true`, número coincidente y nombre no vacío. La dirección se obtiene de
`direccion_completa`, con respaldo en `direccion`; factura exige dirección fiscal.
Si se proporciona un `ubigeo_sunat` válido, se asigna el distrito peruano registrado
en Odoo y su ciudad/departamento. DNI valida longitud; RUC valida además prefijo y
checksum. La consulta no sustituye las validaciones fiscales del emisor.

El contrato proviene de los documentos OpenAPI DNI/RUC compartidos por el usuario,
cuyo índice es [docs.json.pe/llms.txt](https://docs.json.pe/llms.txt). No se ha usado
el token del chat para realizar llamadas ni se guarda en el repositorio.

También se admite `ALVINA_JSONPE_TOKEN` en el entorno del servidor (tiene prioridad
sobre el campo de compañía). El campo de respaldo está restringido a administradores,
pero no cifra el valor en la base de datos. Proteja respaldos y acceso administrativo.
Se conserva TLS, timeout, límite de respuesta y rechazo de redirecciones. Permita
HTTPS a `api.json.pe` desde el servidor. El perfil avanzado conserva los parámetros
manuales anteriores para contratos adicionales.

## Emisión, estados e impresión

Se reutiliza `pos.order.action_pos_order_invoice()` y `_prepare_invoice_vals()`.
La identidad y el tipo elegidos al final se guardan en una solicitud única por
pedido y se validan en el backend antes de preparar la factura. Se utilizan los documentos oficiales
peruanos 03 y 01. El XML ID de Boleta 03 es `l10n_pe.document_type02`.

Se aplica la selección fiscal del POS de Odoo 19: posición del preset cuando
corresponde, posición del cliente si está habilitada en la caja, o posición por
defecto del POS. Comparar solamente la posición automática del contacto provocaba
el bloqueo «La posición fiscal del cliente no coincide con la venta» incluso
cuando el ticket utilizaba correctamente la posición por defecto de la caja.
Si dos posiciones distintas aplican exactamente los mismos impuestos a las líneas,
se permite identificar al cliente sin cambiar precios ni lo cobrado. Si cambia
el tratamiento tributario, se detiene la emisión y se explica la diferencia.

Para tickets sin factura previa, preparar/contabilizar y enviar son **dos RPC
consecutivos**. La factura se guarda primero para que un timeout del proveedor
no elimine su número y produzca otra factura al reintentar. El segundo RPC usa
`account.edi.document._process_documents_web_services(with_commit=False)` sobre
el formato del comprobante. Un resultado ambiguo conserva la factura y bloquea
el reenvío automático; debe verificarse ese mismo número en Contabilidad/proveedor.

El envío exige que el formato esté habilitado en el diario, utilice servicios web
y exponga un callback `post` válido. Se evita que el motor genérico de EDI
considere enviado un formato sin función de envío. El segundo RPC desactiva
explícitamente el contexto `skip_pe_pos_immediate_send` que el módulo del partner
utiliza durante la creación. La recarga visual del ticket se realiza después del
envío/descarga: si falla, muestra una advertencia y conserva el estado de emisión.
La contención de un bloqueo de otro proceso se detecta antes de contactar al
proveedor. Si una excepción deja incierto el resultado del envío, se conserva la
factura y se bloquea también su documento EDI para que el cron oficial no lo
reenvíe automáticamente. Contabilidad debe verificar ese mismo número antes de
autorizar el reintento mediante el procedimiento oficial de Odoo.

El diálogo distingue preparación, pendiente de envío, enviado, error electrónico,
resultado desconocido y anulación. Nunca equipara una factura meramente
contabilizada a un envío exitoso. **Enviado** refleja `account.edi.document.state
= sent` y ausencia de error del proveedor en Odoo; no se inventa una aceptación
SUNAT/CDR ni se convierte un entorno de pruebas del proveedor en producción.

Se imprime únicamente con estado electrónico enviado. El PDF se genera con el
servicio oficial `account.move.send`, sin correo automático y **sin proforma de
respaldo**. Si falla el PDF, se mantiene el comprobante y se puede volver a imprimir
sin emitir otro. El botón descarga el PDF y puede imprimirse con el visor del
navegador; no se fuerza una impresora fiscal o térmica concreta.

Se mantienen el bloqueo del pedido, la solicitud única por pedido y la revisión
del comprobante existente. No se duplican ventas ni pagos POS. Los asientos y
conciliaciones necesarios los realiza Odoo. Las devoluciones, cambios de documento
ya emitido y notas de crédito requieren su flujo oficial.

Los RPC verifican permisos POS, compañía y responsable de sesión/administrador.
Las vistas previas son de servidor, pertenecen a usuario/pedido y vencen
en una hora. El navegador no decide el nombre legal a facturar. Solo un
administrador POS puede autorizar reintentos de fallos de emisión.

## Verificación

Pruebas sin Odoo:

```bash
python -m unittest discover -s tools -p 'test_*.py' -v
node --test tools/test_document_dialog.mjs
python tools/check_addon.py
python -m compileall -q alvina_pos_comprobantes tools
```

Verificación local de 19.0.3.0.1: **40 pruebas ORM aprobadas** en Odoo
19.0-20261015 con PostgreSQL 16 en una red de contenedores aislada, y **24 pruebas
puras aprobadas**. La suite Node ejecuta **7 pruebas de la ventana de emisión**,
incluido el fallo de recarga visual después de emitir. También se comprobaron seis escenarios de lógica del frontend
con servicios simulados y el helper oficial `patch`, y la herencia de las
plantillas de pago con el XML del partner en ambos órdenes de carga. Esas
comprobaciones aisladas no equivalen a una prueba visual en navegador.

Las pruebas de esta versión cubren el ticket pagado sin factura, consulta posterior,
referencias fiscales internas, tipos 01/03, diario seleccionado por el módulo del
partner, aplazamiento de la factura inicial, conservación de la cola existente, emisión EDI simulada,
reimpresión y ausencia de duplicados. Ninguna prueba envía comprobantes reales a
SUNAT ni consulta JSON.PE con el token del usuario.

Las regresiones adicionales exigen un emisor ejecutable (sin marcar como enviado
un formato sin callback), comprueban que el contexto de creación no omita la
llamada interactiva y que el cron oficial no reenvíe un resultado incierto. Un
bloqueo por otro proceso no se confunde con un envío de resultado desconocido.

La suite ORM requiere Odoo 19 y PostgreSQL:

```bash
odoo -d alvina_test -i alvina_pos_comprobantes --test-enable \
  --test-tags /alvina_pos_comprobantes --stop-after-init --max-cron-threads=0
```

El modo de pruebas de Odoo sustituye el PDF por HTML: las pruebas ORM comprueban
sus datos y la ruta de descarga. Una verificación anterior fuera del modo de
pruebas generó un PDF nativo de 27 971 bytes sin emisión externa. No acredita el
QR ni la aceptación SUNAT del proveedor instalado. Comprobar en la base de prueba
del partner el recorrido de caja, impresión física, diarios/series y proveedor.

Las APIs se contrastaron con el código oficial de Odoo 19: `OrderPaymentValidation`, `PaymentScreen`,
`PaymentScreenButtons`, `PosOrder.setPartner/setToInvoice`, `pos.order`, `account_edi`
(`account.move`, `account.edi.document`, `account.edi.format`) y `account.move.send`.
Licencia: LGPL-3.0.
