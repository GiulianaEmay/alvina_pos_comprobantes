# ALVIÑA POS — Boleta/Factura para Odoo 19

**Versión 19.0.2.0.2.** Captura rápida de DNI/RUC, consulta JSON.PE y uso de la
facturación electrónica peruana que ya está configurada en Odoo. No requiere un
proceso nocturno. El addon está dentro de `alvina_pos_comprobantes/`.

## Flujo de caja

ALVIÑA confirmó que los tickets **ya se facturan electrónicamente al cobrar**.
Por eso la identidad se captura antes de esa emisión:

1. En **Pago**, pulse el único botón **Boleta/Factura** (reemplaza la opción
   estándar de facturación). Elija Boleta o Factura e ingrese DNI o RUC.
2. Al completar 8 u 11 dígitos se consulta automáticamente el cliente. Se reutiliza
   una identidad local válida; si no existe, el backend consulta JSON.PE.
3. Revise nombre/razón social y dirección y confirme. Se asigna el cliente y el
   tipo 03/01 al pedido aún editable. Si el pago está completo se continúa con la
   validación oficial del POS; de lo contrario termine de ingresar el pago.
4. Odoo emite usando su diario, serie, impuestos y proveedor SUNAT/OSE existentes.
5. En la pantalla de recibo, **Boleta/Factura** recupera el comprobante del pedido.
   Puede descargar/imprimir el PDF localizado desde esa ventana. Si su documento
   EDI está preparado pero pendiente de envío, **Enviar e imprimir** procesa ese
   mismo comprobante y abre su PDF cuando Odoo registra el envío satisfactorio.

No se pide abrir Contactos ni rellenar su formulario. Si el cliente no existe,
Odoo necesita una referencia `res.partner` para la factura: se crea **archivada**,
marcada como identidad fiscal interna, fuera de las búsquedas normales de
Contactos y clientes del POS. Se reutiliza en consultas posteriores. Los contactos
existentes se mantienen activos, sin archivarlos ni duplicarlos. No se prometen
facturas sin registro fiscal interno: ese registro es necesario para la contabilidad.

**Un comprobante electrónico ya emitido no se convierte a otro DNI/RUC ni de
boleta a factura desde el recibo.** Ese botón lo recupera para imprimir, sin crear
una segunda factura. Para nuevos comprobantes, introduzca los datos antes de
cobrar. Las correcciones de documentos emitidos requieren el procedimiento fiscal
correspondiente, fuera del alcance de este botón.

Si un ticket todavía no tenía comprobante, el diálogo del recibo conserva la
captura DNI/RUC y permite emitir inmediatamente contra **ese mismo pedido**.

## Instalación y actualización

Requisitos: Odoo 19, `point_of_sale`, `l10n_pe`, `account_edi`, `requests` y una
integración electrónica peruana configurada en el diario de facturación del POS.
`account_edi` es el motor oficial; no proporciona por sí solo certificados ni un
proveedor SUNAT. Se detecta automáticamente el formato registrado por
`l10n_pe_edi` cuando está habilitado en el diario. Otro proveedor compatible con
`account_edi` puede seleccionarse en **Compañías → ALVIÑA POS → Formato electrónico
SUNAT/OSE**. No se inventan métodos de módulos privados ni se implementa un emisor
SUNAT alternativo.

1. El partner copia la carpeta del addon a su `addons_path` o descarga este commit.
2. Reinicia Odoo y **actualiza el módulo** desde Aplicaciones (o con `-u
   alvina_pos_comprobantes` en su procedimiento de despliegue). Reiniciar por sí
   solo no crea los nuevos campos ni actualiza las vistas y assets.
3. Recarga completamente el POS. Valida primero en una base de prueba.

No hay que activar un modo nocturno. El selector antiguo de modo se conserva
solo como compatibilidad de base de datos y ya no dirige la emisión del botón.
No se crean diarios, series, certificados ni claves de proveedor de demostración.
Si el emisor existente no utiliza `account_edi`, se requiere conectar su API real;
el addon se detiene con un mensaje de configuración en vez de fingir el envío.

### Compatibilidad con el repositorio de ALVIÑA

El repositorio `alvinha-cybe` compartido contiene `alvinha_point_of_sale`, que
también hereda `PaymentScreenButtons` y busca el texto de la opción nativa de
facturación. Desde 19.0.2.0.1 se conserva ese árbol como destino de herencia, sin
renderizarlo, y se muestra únicamente el botón `Boleta/Factura`. Se comprobó la
composición de ambas plantillas en los dos órdenes de carga con el helper oficial
de herencia de Odoo 19 ejecutado de forma aislada. Reemplazar por completo el
botón nativo eliminaba el destino requerido por el otro módulo.

El código compartido también selecciona diarios por cliente y aplaza el envío
electrónico durante `_generate_pos_order_invoice()` mediante el contexto
`skip_pe_pos_immediate_send`. El diálogo del recibo permite enviar el comprobante
existente mediante su documento EDI. No se ha ejecutado una prueba integral de
estos módulos Enterprise ni del cron en la instalación real de ALVIÑA; esta
revisión de código y plantillas no sustituye esa validación.

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
La selección previa se guarda en `pos.order.alvina_document_kind` y se valida en
el backend antes de preparar la factura. Se utilizan los documentos oficiales
peruanos 03 y 01. El XML ID de Boleta 03 es `l10n_pe.document_type02`.

Para tickets sin factura previa, preparar/contabilizar y enviar son **dos RPC
consecutivos**. La factura se guarda primero para que un timeout del proveedor
no elimine su número y produzca otra factura al reintentar. El segundo RPC usa
`account.edi.document._process_documents_web_services(with_commit=False)` sobre
el formato del comprobante. Un resultado ambiguo conserva la factura y bloquea
el reenvío automático; debe verificarse ese mismo número en Contabilidad/proveedor.

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
Las vistas previas son de servidor, pertenecen a usuario/sesión/pedido y vencen
en una hora. El navegador no decide el nombre legal a facturar. Solo un
administrador POS puede autorizar reintentos de fallos de emisión.

## Verificación

Pruebas sin Odoo:

```bash
python -m unittest discover -s tools -p 'test_*.py' -v
python tools/check_addon.py
python -m compileall -q alvina_pos_comprobantes tools
```

Resultado de la verificación local: **24 pruebas puras aprobadas** y **27 pruebas
ORM aprobadas** en Odoo 19.0 Community (19.0-20261015) con PostgreSQL 16, en una
base aislada. Se verificaron instalación y actualización, captura de identidad,
ficha fiscal archivada y reutilizada, tipos 01/03, facturación/conciliación oficial,
envío con proveedor simulado, no duplicación, rechazo, timeout y descarga del
comprobante existente. Ninguna prueba envió documentos a SUNAT real.

El modo de pruebas de Odoo sustituye PDF por HTML; la prueba ORM del informe
verifica los datos fiscales, adjunto y ruta de descarga. Para comprobar el motor
PDF real se ejecutó además una generación fuera del modo de pruebas con un
servidor HTTP local: produjo un PDF nativo de 27 971 bytes con encabezado `%PDF`,
sin proforma de respaldo ni envío externo. El diseño/QR específico de Enterprise
requiere validación con la localización y proveedor de ALVIÑA.

Las 24 pruebas puras de identidad/contrato JSON.PE no realizan llamadas reales.
La suite `alvina_pos_comprobantes/tests/` incluye controles ORM de permisos,
identidades internas, no duplicación, tipos 01/03 y procesamiento electrónico
con proveedor **simulado**. Ejecutar con Odoo 19 y PostgreSQL:

```bash
odoo -d alvina_test -i alvina_pos_comprobantes --test-enable \
  --test-tags /alvina_pos_comprobantes --stop-after-init --max-cron-threads=0
```

Las pruebas locales no acreditan una respuesta de SUNAT ni la compatibilidad con
un proveedor privado cuyo código no se haya inspeccionado. Verificar en staging
la interfaz OWL, las cajas reales, el diario/series, el PDF peruano/QR y los estados
SUNAT/OSE con la localización instalada. Ninguna prueba de este repositorio envía
comprobantes reales ni modifica producción.

Las APIs se contrastaron con el código oficial de Odoo 19: `PaymentScreen`,
`PaymentScreenButtons`, `PosOrder.setPartner/setToInvoice`, `pos.order`, `account_edi`
(`account.move`, `account.edi.document`, `account.edi.format`) y `account.move.send`.
Licencia: LGPL-3.0.
