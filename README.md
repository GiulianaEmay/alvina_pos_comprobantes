# ALVIÑA POS — Boleta / Factura para Odoo 19

Addon independiente: `alvina_pos_comprobantes/`. Añade **Boleta / Factura** debajo de
los botones de impresión completa/básica de la pantalla de pago exitoso del POS.
El recibo básico sigue dependiendo de la opción oficial `basic_receipt` del POS.
No contiene Odoo ni el módulo nocturno privado de ALVIÑA. No se ha conectado a producción.

## Alcance y estado

Implementado en código:

- Herencia OWL de `ReceiptScreen`, diálogo con tipo, DNI/RUC, consulta y datos de
  identidad de solo lectura antes de «Confirmar y emitir».
- DNI de 8 dígitos ASCII; RUC de 11, prefijo y dígito verificador. La validez de
  longitud de un DNI no acredita por sí sola su existencia.
- Búsqueda previa por documento en `res.partner`, en contactos compartidos o de
  la compañía del pedido. Contactos duplicados, archivados o con país/tipo
  incorrecto bloquean la solicitud para revisión, sin crear otro silenciosamente.
- Consulta externa exclusivamente desde el backend, desactivada por defecto.
  Vista previa temporal vinculada al usuario y pedido, con vencimiento de una hora.
  El frontend nunca suministra el nombre que se usará al emitir.
- Una solicitud persistente por pedido original con estados `pending`,
  `processed` y `failed`; bloqueo de fila, restricción SQL y respuesta idempotente.
- Asociación del contacto al pedido original. No se duplican pedidos ni registros
  de pago POS. La conciliación/asientos necesarios se delegan a Odoo.
- Procesamiento individual mediante `pos.order.action_pos_order_invoice()` y
  selección de documentos peruanos **03** (boleta) y **01** (factura) en
  `_prepare_invoice_vals()`. Conserva el diario configurado en el POS y las
  secuencias, impuestos y conciliaciones de Odoo/localización instalada.
- Actualización del pedido local con el cargador relacional oficial del POS tras
  solicitar. Consulta de estado, reintento autorizado y descarga del PDF mediante
  `account.move.action_invoice_download_pdf()` cuando el documento está contabilizado.

**No validado todavía en una instalación real de Odoo 19.** Se ejecutaron pruebas
unitarias puras y comprobaciones de estructura/sintaxis; no se ejecutaron la
instalación, las pruebas ORM, OWL en navegador, generación real de PDF ni emisión EDI.
El código y su estructura están preparados para instalar y validar en una base de prueba.

Pendiente de conectar y probar con ALVIÑA:

- Prueba de conexión real a JSON.PE desde el servidor de Odoo, con credenciales
  configuradas por el administrador. El contrato DNI/RUC ya está implementado
  según los dos documentos OpenAPI suministrados; no se ha consumido la API real.
- Localización electrónica/EDI efectivamente usada, certificados, OSE/SUNAT,
  diarios y series de ALVIÑA. `l10n_pe` aporta la base contable peruana; por sí
  solo este addon **no implementa el envío electrónico ni acredita aceptación SUNAT**.
- Adaptador del proceso nocturno privado. **No existe cron activado por defecto**.

`processed` significa **factura/boleta contabilizada en Odoo**, no aceptada por
SUNAT/OSE. La interfaz lo indica. El PDF oficial descargado puede ser una
representación contable de respaldo; no certifica aceptación fiscal. El estado
EDI/CDR debe consultarse en la localización instalada o añadirse mediante el
punto de extensión descrito abajo. No se alteran estados EDI desde este addon.

## Instalación en desarrollo

Requisitos: Odoo **19.0**, su Python/dependencias oficiales (incluido `requests`),
PostgreSQL, `point_of_sale`, `l10n_pe` y una compañía peruana con plan contable y
POS configurados. Use una base de prueba y el código oficial de su distribución
(Community/Enterprise según su integración EDI).

1. Añada la **raíz del repositorio** a `addons_path`; el addon es la subcarpeta
   `alvina_pos_comprobantes`. Mantenga también los addons oficiales y Enterprise,
   si corresponde. No añada la subcarpeta del addon directamente a `addons_path`.
2. Instale en una base de desarrollo ya configurada, por ejemplo:

   ```bash
   /ruta/odoo/odoo-bin -c /ruta/odoo-dev.conf -d alvina_dev \
     -i alvina_pos_comprobantes --stop-after-init
   ```

3. Reinicie Odoo normalmente y abra una sesión POS nueva o recargue sus assets.
   No instale/actualice el módulo con sesiones reales en curso sin su procedimiento
   operativo de despliegue. Este repositorio no ejecuta despliegues.
4. Como administrador técnico, abra **Ajustes → Compañías → su compañía → ALVIÑA POS**.
   Los campos de proveedor y modo están restringidos a `base.group_system`.
5. Configure el diario de facturación del POS: compañía correcta, tipo venta,
   documentos latinoamericanos habilitados y series definidas por la localización
   electrónica instalada. No se crean diarios ni secuencias de demostración.

No hay archivo `.env` ni claves de ejemplo incrustadas. No se requieren paquetes
JavaScript externos: los imports pertenecen a los bundles oficiales de Odoo.
No se necesitan controladores nuevos; se usa el RPC autenticado de modelos de Odoo.

## Modos y uso

**Pendiente: integración nocturna** es el modo inicial. Confirmar guarda la
solicitud y el cliente, sin crear un comprobante ni marcar la venta `to_invoice`.
Si falta el adaptador, permanecerá pendiente. La interfaz lo comunica.

**Procesar con Odoo** intenta facturar en la misma transacción de confirmación
usando la API oficial. Antes de activarlo debe validar el flujo con la localización
y el proceso nocturno de ALVIÑA para que ambos respeten la misma coordinación.
No se envían correos ni se fuerza el generador de PDF durante esta operación
(`generate_pdf=False`); la descarga posterior utiliza la API estándar.
El envío electrónico y sus tareas se rigen por la localización instalada.

Flujo: venta pagada/sincronizada → botón → Boleta/DNI o Factura/RUC →
«Consultar cliente» → revisar nombre/dirección → «Confirmar y emitir» → estado.
Factura exige dirección fiscal (`street`); no se permite confirmar datos vacíos.
Si se requieren ubigeo u otros campos, la localización debe validarlos o el
adaptador debe incorporarlos antes de habilitar la emisión real.

Se admiten ventas positivas pagadas, incluso con sesión ya cerrada si la API
estándar de Odoo puede tratarlas. No se implementan notas de crédito, anulaciones,
correcciones de documento ni cambio de cliente después de solicitar. Los pedidos
ya facturados no se vuelven a emitir. Si el contacto tiene un hijo de tipo dirección
de factura, se bloquea para revisión; no se cambia silenciosamente el destinatario.
Una posición fiscal diferente de la venta también exige revisión contable: no se
recalculan retroactivamente precios ni impuestos del pedido.

Solo el responsable Odoo de la sesión o un administrador POS de una compañía
permitida puede consultar/solicitar/imprimir. En POS con empleados, ese usuario
Odoo sigue siendo la identidad RPC; no se inventa autorización por PIN de empleado.
Las solicitudes son de solo lectura para usuarios POS; su creación y transición
se realizan mediante métodos controlados. Las vistas previas no tienen ACL RPC
directa. Solo un administrador POS puede autorizar un reintento fallido.

## Configurar JSON.PE sin exponer claves

**Versión 19.0.1.1.0:** incorpora el contrato documentado para DNI y RUC. Después
de que el partner descargue este código al servidor, reinicie Odoo y **actualice
el módulo** desde Aplicaciones. Reiniciar sin actualizar no crea el nuevo campo
de perfil ni actualiza la vista de configuración.

1. Abra **Ajustes → Usuarios y compañías → Compañías → su compañía → ALVIÑA POS**.
2. Mantenga el perfil **JSON.PE — DNI y RUC** (predeterminado también al actualizar).
3. Introduzca el **Token de JSON.PE** sin la palabra `Bearer` y marque
   **Activar consultas JSON.PE**. Guarde y recargue el POS.
4. Pruebe con un cliente autorizado que no exista en Contactos, ya que un contacto
   local válido se reutiliza sin llamar a JSON.PE. Revise los datos antes de confirmar.

En este perfil **no es necesario completar URL, parámetro ni rutas JSON**. La
configuración avanzada anterior se conserva para uso personalizado pero no se
utiliza en el perfil oficial. No se sobrescribe el token que ya estuviera guardado
ni se activa automáticamente el proveedor al actualizar.

| Consulta | URL y cuerpo JSON de POST | Número devuelto | Nombre |
| --- | --- | --- | --- |
| DNI / boleta | `https://api.json.pe/api/dni`, `{"dni": "DOCUMENTO_DE_8_DIGITOS"}` | `data.numero` | `data.nombre_completo` |
| RUC / factura | `https://api.json.pe/api/ruc`, `{"ruc": "DOCUMENTO_DE_11_DIGITOS"}` | `data.ruc` | `data.nombre_o_razon_social` |

Ambas consultas envían `Authorization: Bearer <token>` exclusivamente desde el
backend. Deben responder HTTP 200 y `success: true` (booleano), con el número de
documento coincidente. El nombre no puede estar vacío. Se usa `direccion_completa`
y, si falta o está vacía, `direccion`. DNI permite dirección ausente; factura exige
dirección fiscal. La identidad devuelta no sustituye los controles fiscales de
Odoo ni certifica por sí misma que una empresa esté habilitada para emitir.

La documentación utilizada son los textos OpenAPI **DNI — POST /dni** y
**RUC — POST /ruc** proporcionados por el usuario, cuyo índice es
[docs.json.pe/llms.txt](https://docs.json.pe/llms.txt). No se han guardado respuestas
reales de personas ni se ha usado el token compartido en el chat para las pruebas.
Las pruebas offline contienen datos ficticios y documentos de referencia públicos.

El servidor debe permitir HTTPS a **api.json.pe**. El transporte conserva TLS,
timeouts de conexión/lectura, límite de respuesta de 64 KiB y rechazo de
redirecciones. No registra el cuerpo de respuesta ni las claves. Los errores HTTP,
credenciales inválidas, respuestas malformadas, `success: false` o número distinto
bloquean la consulta y no crean un cliente o solicitud a partir de esa respuesta.

Como alternativa al campo de Odoo, puede usar `ALVINA_JSONPE_TOKEN` en el entorno
del servidor. Tiene prioridad y se comparte entre compañías del proceso; para
credenciales distintas use el campo por compañía o un gestor de secretos en un
adaptador. El campo está restringido a administradores y **no cifra el valor en la
base de datos**: limite acceso administrativo y proteja respaldos. No exportar claves
al POS ni añadirlas al repositorio. No introducirlas en el chat.

El perfil **Personalizado (avanzado)** conserva las opciones anteriores (GET/POST,
URL, parámetro, rutas y cabecera), con mapeo compartido entre DNI/RUC. Para JSON.PE
use el perfil oficial, que diferencia ambos esquemas. Para contratos adicionales
puede heredar el método backend `_alvina_lookup_external(self, kind, number)` y
devolver `{"name": texto_no_vacío, "street": dirección_o_texto_vacío}`. Nunca aceptar
nombres o credenciales provenientes del navegador. Esta extensión no altera el
contrato del proceso nocturno.

## Contrato de integración nocturna (pendiente)

El modelo **propio de este addon** es `alvina.pos.document.request`. Campos
principales: `order_id` único, `company_id`, `requested_by`, `kind`, `number`,
`partner_id`, `state`, `invoice_id`, `attempts`, `processed_at`, `error_message`.
Los nombres no pretenden describir el módulo privado desconocido.

El adaptador confiable debe:

1. Seleccionar solicitudes `pending` dentro de la compañía correcta. Configurar
   explícitamente usuario de servicio y compañías permitidas. Los métodos privados
   se llaman desde código Python de confianza; no están expuestos como RPC.
2. Ejecutar **una solicitud por trabajo/transacción**, llamando
   `request.sudo()._process_pending()`. No agruparlas en una sola factura ni crear
   ventas, pagos o comprobantes alternativos. No hacer `commit()` dentro de este
   método; el framework de trabajos o cron administra la transacción.
3. Excluir estos pedidos de cualquier ruta de facturación paralela del módulo
   nocturno. Si su proceso ya genera un comprobante, adoptar explícitamente la
   coordinación: bloquear el pedido primero, respetar la solicitud y llamar al
   procesador para verificar y registrar el comprobante existente, sin emitir otro.
4. Verificar el resultado: el procesador devuelve y persiste `failed` ante errores
   funcionales, sin dejarlos pasar como éxito del lote. No reintentar en bucle.
   `alvina_retry_document()` requiere administrador POS; restituye `pending` y
   procesa inmediatamente solo si ese es el modo configurado.
5. Incorporar lectura de estados reales EDI/OSE/CDR mediante herencia de
   `_status_payload()` y ampliar el diálogo si necesita más estados. No equiparar
   `processed` con envío, aceptación SUNAT o disponibilidad de CDR.

Bloqueo: siempre **pedido POS primero** (`_alvina_lock()`), luego solicitud. La
restricción SQL impide dos solicitudes por pedido; la revisión de `account_move`
evita volver a crear una factura. La creación de contactos se serializa por
documento con bloqueo advisory de transacción. Los errores de serialización o
deadlock se propagan a Odoo para su reintento transaccional estándar.

La emisión usa un savepoint: si contabilizar/conciliar falla, sus cambios se
revierten y se conserva la solicitud como fallida. Un comprobante preexistente
se acepta solo si está contabilizado y coinciden pedido único, cliente, compañía,
tipo 01/03, diario, moneda e importe. No se cancelan o recrean comprobantes.
Los fallos con efectos externos de un proveedor requieren revisión de su estado
remoto antes de reintentar; una transacción SQL no revierte un envío externo.

No hay garantía de coordinación con un proceso privado que no respete este
contrato. **Esta integración no está terminada hasta revisar su implementación
real y probar concurrencia, cierres de sesión y conciliación en staging.**

## Pruebas

Comandos ejecutables sin Odoo, desde la raíz del repositorio:

```bash
python tools/test_identity.py -v
python tools/test_jsonpe.py -v
python tools/check_addon.py
python -m compileall -q alvina_pos_comprobantes tools
```

Resultados en este entorno: **24 pruebas unitarias puras aprobadas** (10 de identidad y 14 del contrato JSON.PE). Se verificó
sintaxis Python, XML y JavaScript con Node, archivos de datos/assets declarados y
dependencias del manifiesto. No se importó el addon en un registro ORM real.

Suite ORM incluida, **sin ejecutar aquí** (no existe instalación de Odoo 19 ni
servidor PostgreSQL configurado). En una base de prueba desechable con Odoo 19 y
sus dependencias, ejecute por ejemplo:

```bash
/ruta/odoo/odoo-bin -c /ruta/odoo-test.conf -d alvina_test \
  -i alvina_pos_comprobantes --test-enable \
  --test-tags /alvina_pos_comprobantes --stop-after-init
```

`alvina_pos_comprobantes/tests/` cubre contacto local sin proveedor, doble solicitud,
vista previa de otro pedido/vencida, documento inválido, permisos y ACL, estados
fallidos, bloqueo de impresión pendiente, preparación de tipos 03/01 y rollback
ante una falla inyectada de facturación. Se incluye una suite de transporte JSON.PE
con HTTP simulado (DNI/RUC, Bearer, timeouts, fallo del proveedor y límite de respuesta),
también pendiente de ejecutar en Odoo. Estas pruebas usan fixtures oficiales
POS y mocks explícitos para fallos; **no acreditan emisión real ni integración EDI**.

Validación de staging aún necesaria: instalación limpia y actualización; render
OWL de ambos botones de impresión; boleta y factura con líneas/impuestos/pagos
reales; diario/serie correctos; PDF con usuario cajero; sesión abierta/cerrada;
multicompañía; doble clic y dos transacciones concurrentes; conexión real JSON.PE;
timeout/respuesta inválida; proceso nocturno y aceptación/rechazo EDI/CDR.

## APIs oficiales consultadas

Se contrastaron fuentes oficiales de la rama **19.0** (referencia consultada:
`e5a4af13360c0fb54ea5ae3301804cccb09668cd`):

- [ReceiptScreen JS](https://github.com/odoo/odoo/blob/19.0/addons/point_of_sale/static/src/app/screens/receipt_screen/receipt_screen.js)
  (`currentOrder`, `orderUuid`, `dialog`) y su
  [plantilla](https://github.com/odoo/odoo/blob/19.0/addons/point_of_sale/static/src/app/screens/receipt_screen/receipt_screen.xml).
- [POS DataService](https://github.com/odoo/odoo/blob/19.0/addons/point_of_sale/static/src/app/services/data_service.js)
  (`call`, `callRelated`) y
  [pos.order](https://github.com/odoo/odoo/blob/19.0/addons/point_of_sale/models/pos_order.py)
  (`read_pos_orders`, `_prepare_invoice_vals`, `action_pos_order_invoice`,
  `_generate_pos_order_invoice`, conciliación y sesiones cerradas).
- [Localización peruana](https://github.com/odoo/odoo/blob/19.0/addons/l10n_pe/models/account_move.py),
  [tipos de documento](https://github.com/odoo/odoo/blob/19.0/addons/l10n_pe/data/l10n_latam_document_type_data.xml)
  y [tipos de identidad](https://github.com/odoo/odoo/blob/19.0/addons/l10n_pe/data/l10n_latam_identification_type_data.xml).
  Atención: el XML ID oficial de **Boleta 03** es `l10n_pe.document_type02`;
  no deducir el código fiscal a partir del nombre del XML ID.
- [account.move](https://github.com/odoo/odoo/blob/19.0/addons/account/models/account_move.py)
  (`action_invoice_download_pdf`) y
  [controlador de descarga](https://github.com/odoo/odoo/blob/19.0/addons/account/controllers/download_docs.py)
  (permisos de lectura y PDF de respaldo).

Consultar fuentes no equivale a aprobar una instalación ni una prueba de integración.
Licencia del addon: LGPL-3.0-or-later.
