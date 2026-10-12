---
title: Esfer@ para agentes y desarrollo de Cosecre
reviewed_on: 2026-10-12
code_baseline: 90d2d1b7a4ef6016e3d1010dab665138f36eea0a
scope: secretaria economica administrativa y academica
status: referencia de integracion y propuesta de desarrollo
---

# Esfer@ para agentes y desarrollo de Cosecre

Cosecre debe preparar y transferir a Esfer@ los registros de secretaría que
correspondan al centro, conservar su correspondencia con los originales y
comprobar que quedaron incorporados. Actualmente importa partidas desde un
Excel de Esfer@ y gestiona documentación, conciliación e imputaciones locales.
El trabajo local del escritorio añade acceso, consultas y un ensayo conectado
de facturas ficticias en formación, sin verificación remota en esta revisión;
**todavía no existe un exportador productivo hacia Esfer@**.

El nombre oficial es **Esfer@**. `esfera`, `sfera`, `SFERA` y `cosecre-sfera`
son nombres usados en el código; las variantes Sfer@, sphera o spfer@ de una
petición deben resolverse al mismo sistema. No renombrar contratos por esta
diferencia.

## Índice

1. [Reglas para agentes](#reglas-para-agentes)
2. [Estado de la integración](#estado-de-la-integración)
3. [Cobertura de secretaría](#cobertura-de-secretaría)
4. [Procesos económicos](#procesos-económicos)
5. [Procesos administrativos y académicos](#procesos-administrativos-y-académicos)
6. [Uso de la integración local](#uso-de-la-integración-local)
7. [Datos y contratos que necesita el backend](#datos-y-contratos-que-necesita-el-backend)
8. [Protocolo propuesto de exportación](#protocolo-propuesto-de-exportación)
9. [Casuísticas de aceptación](#casuísticas-de-aceptación)
10. [Plan de desarrollo](#plan-de-desarrollo)
11. [Fuentes y actualización](#fuentes-y-actualización)

## Reglas para agentes

1. Distinguir **importar a Cosecre**, **consultar Esfer@**, **registrar en Esfer@**
   y **pagar o cobrar**. Son operaciones independientes. Un ZIP de justificantes
   o un dossier PDF tampoco es un fichero importable por Esfer@.
2. Comprobar entorno, centro real de la sesión, presupuesto, ejercicio, permisos
   y catálogo antes de preparar una operación. La etiqueta de centro en ajustes
   no selecciona el centro en el portal. El curso académico y el ejercicio
   económico son dimensiones diferentes.
3. No convertir cada movimiento bancario en factura ni decidir el circuito por
   el signo del importe. Puede ser un pago agrupado, un abono, un traspaso, una
   devolución, una retención o un movimiento extrapresupuestario.
4. No completar hechos contables con inferencias del modelo. Las sugerencias de
   Jev ayudan a clasificar; los datos fiscales, destinatario, vencimientos,
   proveedor y distribución de importes deben tener origen y revisión.
5. `validat`, conciliación confirmada y partida confirmada son estados locales.
   No significan registro, validación, pago o cierre en Esfer@.
6. Operar con la autorización de la tarea. Una autorización puede cubrir un lote
   y sus acciones definidas; conservar su alcance y no volver a pedirla para la
   misma operación. Preparar un resultado concreto antes de solicitar cualquier
   autorización adicional necesaria. Esta guía no autoriza escrituras, pagos,
   firmas ni cierres reales.
7. Ante resultado incierto de una escritura, **releer y conciliar antes de
   reintentar**. La ausencia de respuesta no demuestra que no se haya registrado.
8. No publicar contraseñas, cookies, cabeceras, perfiles, datos de alumnos ni
   respuestas reales del portal en Git. Redactar también parámetros de URLs,
   nombres, NIF, IBAN y adjuntos en evidencias compartidas. Usar datos sintéticos.
9. Confirmar capacidades en el código actual. Las secciones de diseño de esta
   guía son propuestas; no son endpoints o herramientas disponibles.

## Estado de la integración

La base versionada revisada es `90d2d1b7a4ef6016e3d1010dab665138f36eea0a`.
La siguiente distinción evita dar por desplegado código presente solo en una
copia de trabajo. Este cambio documental no incorpora el trabajo local
preexistente. El checkout recibió adiciones concurrentes durante la revisión;
la tabla incluye el ensayo conectado presente al finalizar. Comprobar el estado
actual de esos archivos antes de operar.

| Nivel de evidencia | Capacidad | Referencia y límite |
| --- | --- | --- |
| Versionado en la base | Importación de **Dades del pressupost**, partidas y subpartidas | `hub/src/cosecre_hub/api/partides/esfera.py`, `models.py`, `routes.py`; dirección Esfer@ → Cosecre |
| Versionado en la base | Documentos, solicitudes, extractos, conciliación y propuestas de partidas | `hub/src/cosecre_hub/models.py`, `api/documents/`, `api/requests.py`, `api/reconciliation.py`, `api/statements/`, `api/partides/` |
| Trabajo local observado | Navegador, credenciales personales y consultas de presupuestos, proveedores y facturas | `desktop/src/main/browser/`, `desktop/src/main/sfera/explorer.ts`, `frontend/src/modules/sfera/`, `frontend/src/browser/`, `frontend/src/sfera/contract.ts`; ausentes de la base |
| Trabajo local observado | Restricción de ajustes compartidos y trazabilidad adicional de decisiones de partidas | `hub/src/cosecre_hub/api/sfera_settings.py`, cambios en `api/app_settings.py`, `api/partides/precedents.py` y `PartidaDecision`; no asumir despliegue |
| Observación anterior declarada por documentación local | Detalle de factura, formularios y endpoints internos de validación y guardado | `desktop/SFERA.md`; los PUT no se ejecutaron en la exploración que describe |
| Simulación local | `frontend/src/sfera/invoice-poc.ts` | Catálogos ficticios y transporte sintético; `/services/factura/poc/creades` es del simulador. No prueba escritura remota |
| Ensayo conectado local observado, sin verificación remota en esta revisión | Catálogo, preparación y alta por ID de plan en formación | `desktop/src/main/sfera/invoices.ts`, `portal.ts`, `frontend/src/sfera/invoice-bridge.ts`, `frontend/src/modules/sfera/InvoicePocView.vue`; WIP concurrente que contiene PUT reales, no exportador productivo |
| Trabajo local, probado con fixtures (2026-10-12) | Planes de exportación de facturas de proveedor en el Hub y runner de escritorio | `hub/src/cosecre_hub/api/sfera/` (preflight, plan, aprobación por hash, claim, resultado, recuperación y conciliación), `desktop/src/main/sfera/export-runner.ts`; tests `hub/tests/test_sfera_export.py` y `scripts/check-sfera.mjs`. Ensayo real el 2026-10-12 en formación con un Hub local: una factura de prueba exportada, bloqueo de reexportación y conciliación de una factura manual sin escribir |
| Trabajo local (2026-10-12) | Pantalla **Esfer@ → Plans d'exportació** y diagnóstico de solo lectura | `frontend/src/modules/sfera/ExportPlansView.vue`, `desktop/src/main/sfera/diagnostics.ts`; plan creado desde la prueba de extractos |
| Pendiente | Generar planes desde el registro, mapeo de maestros, pagos, ingresos y datos académicos/administrativos | Sin resolución de proveedor, partida o banco desde `Document` |

### Importación de partidas versionada

El fichero esperado se obtiene en Esfer@ por **Informes i extraccions → Consulta
les dades del pressupost → Exporta XLS**. El parser lee cabecera de centro, NIF,
código, ejercicio y fecha, y la tabla con `Tipus`, `Codi partida`, `Codi
finalista`, `Nom partida` e `Import Pressupost`. Reconoce ingresos y gastos; la
sangría o extensión del código identifica subpartidas.

`POST /api/v1/partides/import` recibe `file` y `dry_run` como formulario y exige
administrador. `dry_run=true` anticipa el resultado sin aplicarlo. La clave de
partida es `(exercici, codi)`; reimportar actualiza sin destruir asignaciones y
contexto. Las partidas desaparecidas con asignaciones se conservan como
retiradas; las demás pueden eliminarse. El contexto de ejercicios anteriores
puede heredarse por código. Confirmar que conserva sentido contable.

**Límites para exportación:** `Pressupost` tiene como clave solo el ejercicio;
las partidas no distinguen centro ni presupuesto General/Menjador.
`nif_matches` informa de discrepancia, pero la importación no la bloquea. El
parser omite códigos duplicados y puede convertir un importe ilegible en cero;
no contrasta todas las sumas. Guarda metadatos del fichero, no su original ni
hash/historial completo. No es un validador oficial ni resuelve IDs internos del
portal. `fund_family()` agrupa visualmente finalistas; conservar el código exacto.

### Imputación y conciliación versionadas

`MovementPartida` asigna movimientos a partidas. Un movimiento puede repartirse;
cuando faltan importes explícitos, el cálculo local puede distribuirlos por
igual. La asignación no garantiza por sí sola ejercicio, sentido y elegibilidad
de una partida retirada. Si falta presupuesto del año del movimiento, la cola
puede mostrar el último importado: bloquear esa aproximación en la exportación.

El comentario del modelo que resume Esfer@ a dinero movido describe el diseño
local. El manual distingue factura, líneas, vencimientos y liquidación. **La
imputación de un movimiento no representa todo el registro oficial.**

`PaymentMatch` permite varias facturas por movimiento, pero la confirmación
revisada rechaza asociar una factura a otro movimiento confirmado. Faltan
aplicaciones parciales con importe por documento/vencimiento. Caixeta puede
renumerar códigos visibles siguiendo la hoja; no son identidad estable. El undo
local no revierte actos remotos; su lista `TRACKED` tampoco incluye tablas de
presupuesto y partidas. Referencias: `api/reconciliation.py`,
`services/statements/store.py`, `services/history.py`.

El nuevo desarrollo corresponde a **`hub/`**; `backend/` es la implementación
anterior sustituida. Las exportaciones actuales de originales ZIP y dossier PDF
no contienen un contrato de importación Esfer@. El dossier incorpora PDF
conciliados confirmados y omite fotos; no presupone expediente completo.

## Cobertura de secretaría

Esfer@ abarca gestión económica, administrativa y académica. Las instrucciones
DOIGC están actualizadas el **1 de julio de 2026**. El ejercicio económico sigue
el año natural. Deben usarse `FAMILIESMATERIAL` y `FAMILIESSORTIDES` conforme al
ejercicio. El comedor delegado tiene presupuesto diferenciado; sin delegación,
usa una cuenta extrapresupuestaria del general. La cobertura académica convive
con SAGA: Esfer@ incluye FP y artes plásticas/diseño de Ley 3/2022; SAGA sigue
para FP LOGSE, compleciones de Orden EDF/74/2025 y adultos. Fuente: [DOIGC,
apartados 1.3, 1.3.4, 1.3.5 y
3.1](https://documents.espai.educacio.gencat.cat/IPCNormativa/DOIGC/GEST_Economica_administrativa.pdf).

Esta matriz es una **clasificación para implementar**, no una declaración de
que cualquier fichero de secretaría deba subirse. Concretar para el centro
`required`, `optional`, `external_system` o `not_applicable`, con fuente y
destino. Un destino desconocido debe quedar bloqueado en el plan.

| Información | Destino a resolver | Estado de Cosecre y ampliación necesaria |
| --- | --- | --- |
| Presupuesto, partidas, finalistas y centros de coste | Gestión económica y configuración | Importación local; faltan IDs, tipo de presupuesto y estados completos |
| Proveedores y aportadores | Maestros económicos | Datos en documentos y lectura WIP; crear maestro y correspondencias |
| Facturas, tiques y gastos simplificados | Circuito de gasto pertinente | Registro/originales; faltan líneas fiscales, vencimientos y clase oficial |
| Abonos, anulaciones y correcciones | Circuito vinculado al original | Añadir relaciones y estados propios |
| Pagos, cobros, reservas y obligaciones | Gasto, ingreso y tesorería | Extractos/matches locales; faltan aplicaciones parciales/remotas |
| Familias, subvenciones, donaciones y otros ingresos | Aportador, finalidad y derecho de cobro | Un movimiento positivo no es registro completo de ingreso |
| Bancos, Caixeta, tarjetas y traspasos | Cuentas/cajas y tesorería | Mapear cuentas y evitar duplicar ingreso/gasto |
| Impuestos y liquidación/cierre anual | Fiscalidad, presupuesto e informes; presentación tributaria externa | Sin dominio fiscal o proceso anual completo |
| Factura electrónica y contratación | Flujo oficial y archivo contractual | PDF/foto/solicitud no acreditan recepción electrónica ni contrato |
| Correspondencia | Registre de correspondència | Sin equivalente; `Request` no es asiento oficial |
| Certificados y diligencias | Generación, registro y firma | Sin dominio; mantener número, estado, firmante y persona |
| Matrícula, ficha, tutores/contactos y servicios | Esfer@, con RALC/GEDAC | Sin modelo; resolver identidad y propiedad del dato |
| Expedientes y traslado | Archivo, custodia y petición/respuesta | Sin modelo; procesos por enseñanza con firma y lotes |
| Currículos, grupos y evaluación | Catálogos y procesos académicos | Sin modelo; reglas por enseñanza y curso |
| Personal y dedicación | Datos oficiales, revisión y firma | Usuarios locales no acreditan plantilla o cargo oficial |
| Inventario, actas, títulos, becas y archivo | Determinar aplicación y archivo de cada proceso | Sin destino automático verificado; no inventar importador Esfer@ |
| Conversaciones y propuestas de IA | Cosecre | Exportar solo campos pertinentes al registro oficial |

El catálogo de módulos procede de la [introducción
oficial](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/gacademica/index).
Un módulo no prueba que exista API o admita cargar originales.

## Procesos económicos

### Presupuesto y elegibilidad de operaciones

El manual describe un presupuesto por año y tipo General/Menjador. La estructura
base aporta partidas y el centro configura subpartidas; si existen, la dotación
se lleva a ellas y no al padre. Los centros de coste distribuyen actividad por
proyecto/departamento; no son partidas ni códigos finalistas. Fuente:
[Dotació](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc1/ap11)
y [Centres de cost](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc1/ap14).

El circuito de estados es elaboración → provisional → aprobado → liquidado
pendiente → liquidado aprobado → validado y cerrado. En elaboración no se
registran ingresos/gastos; provisional requiere equilibrio y tiene plazo
configurable. La liquidación bloquea operaciones; algunos estados intermedios
permiten volver a aprobado. El cierre validado no tiene corrección ordinaria
descrita. Fuente: [Estats del
pressupost](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc1/ap12).

Cambiar dotaciones de un presupuesto aprobado puede requerir modificación
formal de dirección y consejo escolar. Una modificación en curso restringe otras
modificaciones y pasos de estado. Cosecre no concede saldo por aumentar un dato
local. Fuente: [Modificació del
pressupost](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc1/ap13).

Las cuentas extrapresupuestarias tienen estructura e identidad propias. No usan
centro de coste; una cuenta propia debe cumplir condiciones de saldo/movimientos
para subdividirse o desactivarse. No convertirlas en partidas ordinarias.
[Comptes extrapressupostaris](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc1/ap15).

El DOIGC consultado exige aprobación antes del 31 de enero y validación/cierre de
la liquidación antes del 31 de marzo. Los remanentes afectados/disponibles y la
pestaña Romanent alimentan la declaración responsable; comprobar las
instrucciones del ejercicio. Fuente: [DOIGC, 1.3 y
1.3.3](https://documents.espai.educacio.gencat.cat/IPCNormativa/DOIGC/GEST_Economica_administrativa.pdf).

### Proveedores y aportadores

Son maestros del centro, activos o inactivos, con NIF único y tratamiento de
identidades extranjeras. El alta individual de proveedor incluye identidad,
dirección y configuración de retención cuando procede; permite contactos y
cuentas bancarias. Un proveedor inactivo no admite nuevas facturas/reservas.
El aportador es un catálogo paralelo, no un alumno o usuario Cosecre por defecto.
Fuente: [Proveïdors i
aportadors](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc2/ap21).

Diseño de Cosecre: resolver identidad por documento fiscal e ID remoto y revisar
conflictos de nombre/país. Conservar el IBAN con origen; no deducir que pertenece
al centro por aparecer en una factura. El alta de maestro debe ser dependencia
explícita del lote, con campos propios y comprobación posterior.

### Facturas y vencimientos

Registrar requiere presupuesto provisional/aprobado, proveedor, número externo
único para ese proveedor, fechas documental/contable, concepto, líneas y
vencimientos. La referencia la genera Esfer@; el número interno opcional es
único. La fecha contable pertenece al ejercicio y a período fiscal abierto.
El total cuadra con líneas de base + IVA − IRPF y con vencimientos; los pagos
parciales se aplican a vencimientos. Se validan saldos y, al marcar pago, banco o
caja. No se borran vencimientos pagados: se anulan por su circuito. Fuente:
[Gestió de la despesa, 2.4.2.3 a
2.4.2.8](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc2/ap24).

Diseño de Cosecre: documentar separadamente **obligación → vencimiento → pago**.
Permitir factura pendiente sin movimiento bancario. No usar un match o texto
«pagado» para liquidar automáticamente. La cuenta, método e importe aplicado
requieren correspondencia explícita. Los ajustes de redondeo deben conservar su
origen y cuadrar con el documento revisado.

### Gasto simplificado y reservas

El gasto simplificado es un circuito excepcional de pequeñas compras justificadas
con tique y sin factura. El manual menciona límite configurable de 300 € y también
redacta «inferior» a esa cantidad: verificar configuración y borde antes de
codificarlo. Incluye fecha contable, reparto y vencimientos; una compra pequeña
con factura no cambia automáticamente de circuito.
[Despesa simplificada](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc2/ap22).

Las reservas anticipan obligaciones y bloquean disponibilidad presupuestaria.
Su ejecución por facturas/gastos reduce el saldo; «reserva liquidada» no significa
dinero pagado. No exportar una solicitud de compra como reserva sin resolver
proveedor, presupuesto y autorización del circuito.
[Reserves](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc2/ap23).

### Anulaciones y abonos

El manual limita la anulación de facturas al ejercicio y a facturas no incluidas
en impuestos liquidados. Otros supuestos pueden necesitar abonos, incluso
parciales o de años anteriores, y compensaciones con crédito del proveedor.
Fuente: [Gestió de la
despesa](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc2/ap24).

Diseño de Cosecre: relacionar el corrector con el original y preservar ambos.
Un importe bancario positivo no permite decidir abono frente a ingreso. Leer
estado del registro, vencimientos y fiscalidad antes de proponer corrección;
no anular o crear compensaciones automáticamente para resolver un error local.

### Ingresos y cobros

El ingreso ordinario identifica aportador, números/referencia, fechas, concepto,
imputación, bases/IVA y vencimientos. Total de líneas y vencimientos deben
coincidir; cobro y devolución tienen operaciones propias. Las devoluciones pueden
ser parciales y de operaciones anteriores. Una cuenta extrapresupuestaria no usa
centro de coste. Fuente: [Gestió de
l'ingrés](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc2/ap26).

El ingreso simplificado se describe para importes pequeños sin desglose de IVA,
con límite configurable. El vencimiento aparece cobrado por defecto en el manual:
el adaptador debe establecer y verificar el estado expresamente. «No cobrable»
no equivale a «todavía pendiente».
[Ingrés simplificat](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc2/ap25).

Diseño de Cosecre: distinguir derecho de cobro, aportación prevista, dinero
recibido y devolución. Resolver familias, subvenciones y finalidad antes de
imputar; incorporar cobros parciales y agrupados, sin convertir todos los
movimientos positivos en nuevos ingresos.

### Tesorería y conciliación

Bancos y cajas son entidades seleccionables para cobros/pagos, con saldo y
estado; las cajas además tienen responsable. Mapear cada cuenta o Caixeta a su
entidad remota, no a una partida. Fuente: [Comptes bancaris i
caixes](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc3/ap31).

Una transferencia entre banco/caja del centro es tesorería, no ingreso y gasto
presupuestarios nuevos. Conciliación, saldo provisional, arqueo y acta son
operaciones distintas. No corregir una diferencia creando asientos ficticios.
[Gestió de la tresoreria](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc3/ap32).
La regularización de saldo se solicita y el administrador acepta o rechaza;
no es un fallback del exportador.
[Regularització de saldo](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc8/ap86).

### Impuestos e informes

La configuración del centro determina IVA, prorrata y centros de coste, además
de visibilidad de anulados y otras opciones. Leerla antes de comparar listas.
[Paràmetres del centre](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc7/ap71).

Las liquidaciones fiscales tienen orden de trimestres y actuaciones propias.
Obtener PDF no liquida el período ni acredita presentación a la Administración
Tributaria. IVA/IRPF, prorrata, solicitud de devolución y cobro necesitan estados
separados. No fijar tasas, exenciones o calendarios actuales a partir de un manual
formativo; comprobar norma y situación del centro al implementar.
[Liquidacions d'impostos](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc4/ap41).

Los informes oficiales incluyen tesorería, presupuesto, liquidación, arqueo y
traspaso de dirección. Un PDF parecido de Cosecre no los sustituye.
[Gestió d'informes](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc5/ap51).
El diario, libros y extractos sirven para conciliar referencias y cantidades.
El manual llama `Exporta CSV` a una salida descrita como Excel: inspeccionar
extensión, separador, formato y codificación reales. **Son salidas de Esfer@,
no evidencia de un importador inverso.**
[Consultes i extraccions](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc5/ap52).

### Factura electrónica

El manual describe recepción/validación formal antes de registrar o rechazar.
Es una integración corporativa específica, no una API genérica de contabilidad.
[Descripció](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc6/ap61).
El circuito comprueba NIF destinatario; proveedor, número, fecha y total pueden
estar bloqueados desde el documento electrónico. Si falta proveedor, su alta y
el registro son pasos separados. La recepción no implica contabilización/pago.
[Accés i registre](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc6/ap62).

El DOIGC actual refiere la recepción desde GeFACT. Verificar la situación vigente
del centro antes de copiar nombres o flujo de un manual antiguo.
[DOIGC, 1.5](https://documents.espai.educacio.gencat.cat/IPCNormativa/DOIGC/GEST_Economica_administrativa.pdf).
Buscar una factura ya recibida por su referencia antes de crear otra desde un PDF.

### Apertura y primer año en Esfer@

Las excepciones de primer año corresponden al **primer año del centro en
Esfer@**, no a instalar Cosecre.
[Descripció del primer any](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc9/ap91).
El remanente anterior y saldos bancarios/de caja se introducen mediante sus
procedimientos; no simular ingresos para reproducir el saldo.
[Romanent](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc9/ap93)
y [Saldos iniciales](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc9/ap94).

El procedimiento específico de pendientes de proveedor/aportador trata importe
pendiente, fecha histórica y fecha contable inicial mediante E.OP1, con reglas
excepcionales de impuestos. No es un método universal para pendientes
interanuales ni para cualquier migración de Cosecre. Resolver con administración
el caso de pagos previos y la fecha de corte antes de aplicarlo.
[Factures pendents](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc9/ap95)
y [Ingressos pendents](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc9/ap96).

## Procesos administrativos y académicos

### Correspondencia

Separar ejercicio, contacto y tema del movimiento de entrada/salida. El sistema
asigna número y tipo; se informa fecha de recepción, fecha documental, asunto,
observaciones, remitente/destinatario, indicación de adjuntos, acción de
seguimiento y distribución interna. Contactos y temas se dan de baja; los
asientos se anulan. El manual describe extracción a Excel. **Documents adjunts
Sí/No no demuestra carga binaria.** Fuente: [Registre de
correspondència](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/gest_adm/reg_correspon).

Diseño de Cosecre: entidad `CorrespondenceEntry` con dirección, fechas separadas,
contacto/tema resueltos, número remoto y estado. Relacionarla con adjuntos y
solicitudes cuando proceda, sin reutilizar `Request.id` como número oficial.
No registrar automáticamente cada mensaje de una conversación.

### Certificados

Esfer@ permite certificados de matrícula, matrícula anterior, calificaciones y
otros genéricos. La búsqueda identifica alumno o personal; algunos contenidos
deben completarse. El manual indica salida RTF y exportación CSV del registro.
Un certificado erróneo conserva su número y registro; se pueden anotar entrega
y observaciones. Fuente:
[Certificats](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/gest_adm/certif).

Diseño de Cosecre: distinguir petición, generación, archivo, firma cuando aplique,
entrega y error. Un DOCX/PDF editado o una tarea de impresión no demuestra
registro ni entrega. Conservar fichero emitido y hash.

### Matrícula e identidad del alumnado

La ficha reúne ámbitos personal y académico; recibe datos de RALC, matrícula,
evaluación y configuración. Usar `IdRALC` para resolver personas y alumno,
centro, enseñanza y curso para identificar matrícula; no deduplicar por nombre.
Fuente: [Fitxa de
l'alumne](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/mat/fda/index).

La admisión/preinscripción parte de plaza asignada por GEDAC. Las altas descritas
son individuales; los datos registrales están bloqueados hasta matricular.
Guardarla también registra la matrícula en RALC. Requiere currículo y puede
requerir régimen/turno, repetición, escolarización compartida y medidas de
diversidad configuradas. Completar ficha y tutores es otro paso.
[Matrícula de admisión o
preinscripción](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/mat/mat_pre).

La continuidad admite procesos individuales y lotes; el manual indica que para
ESO/bachillerato no se formaliza hasta el día siguiente a la firma de evaluación.
Confirmar la condición en la versión activa antes de programar.
[Matrícula por
continuidad](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/mat/mat_cont).

El ámbito personal admite revisión de datos, tutores/contactos, transporte,
comedor, campos libres y situaciones relevantes.
[Ámbito personal](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/mat/fda/fda-ap/index).
Los campos libres son configuración del centro, no un depósito arbitrario de
Cosecre. Resolver campo oficial, finalidad, permisos y origen antes de transferir.

### Expedientes y custodia

El expediente se organiza por enseñanza. Los resultados consolidados se corrigen
mediante diligencias: a acta si proceden de evaluación propia en Esfer@, o a
expediente para otras procedencias, incluidas migraciones SAGA. El apoyo
administrativo puede preparar; secretaría/dirección firma y solo entonces queda
completa. Fuente:
[Expedients](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/gest_adm/exp).

El archivo describe lotes diferidos, con solicitados, efectuados y no efectuados;
excluye evaluaciones parciales. **Finalizado no significa que todos los elementos
hayan tenido éxito.**
[Arxiu d'expedients](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/gest_adm/arx_exp).

La página de petición añade que el archivo ahora es automático al dar de baja
matrícula: comprobar esta diferencia antes de repetir el circuito manual. Para
origen Esfer@ se usa centro custodio y petición telemática; para origen externo,
procedencia y gestión manual. Dirección firma y la petición queda pendiente de
respuesta. Fuente: [Petició de
documentació](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/gest_adm/peticio_documentacio/peticio_doc).

Diseño de Cosecre: registrar pasos/resultados por alumno y enseñanza, origen,
custodio y destino. No reducir traslado a subir PDF ni completarlo al crear la
petición. La respuesta y recepción necesitan estados/adaptadores propios.

### Currículos, evaluaciones y personal

La matrícula necesita currículo de centro por enseñanza/nivel; puede haber
varias opciones para optativas, religión o idiomas. Resolver códigos vigentes,
sin extrapolar configuración entre enseñanzas.
[Currículum del
centre](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/curric/ccentre).

Evaluaciones parciales y finales tienen circuitos diferentes. Incorporar
resultados requiere contratos y comprobación de estados, documentos y firmas;
este adaptador no está implementado. Consultar
[evaluaciones parciales](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/avaluacions/ap/index)
y [finales](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/avaluacions/af/index).

Los datos oficiales del personal proceden del Departament; los errores se
canalizan a servicios territoriales. La dedicación pasa por elaboración,
revisión, pendiente de firma y firma de dirección. No sobrescribir identidad
o vínculo laboral a partir de usuarios locales.
[Dades del personal](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/personal/personal1).

Los permisos Esfer@ dependen de la función en el centro; dirección puede conceder
permisos extraordinarios temporales completos o de lectura. Ser administrador
de Cosecre no los otorga.
[Autoritzacions del personal](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/configuracions/apc).

### Extracciones y colas

Publicacions define extracciones con campos, ámbito, disponibilidad, formato y
filtros; ejecutarlas genera otro resultado. Se describen PDF, XLS y RTF y cola
separada. La salida ayuda a comprobar datos; **no prueba importación inversa**.
[Extraccions](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/pub/ext)
y [Cua d'extraccions](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mgad1/pub/ext_cua).

Diseño de Cosecre: guardar lote, ámbito, filtros, fecha, estado, recuentos,
fallos y fichero. No declarar éxito al recibir la solicitud ni confundir cola
de documentos con cola de alta de registros.

## Uso de la integración local

Esta sección describe **WIP observado**, no capacidad garantizada en una
instalación publicada. Los archivos/recetas deben existir en el checkout.

### Procedimiento de lectura

1. Abrir Cosecre Desktop con Hub y cuenta autorizados. El módulo local permite
   `admin` y `administratiu`; la web y profesor no exponen Esfer@. Comprobar
   roles en código, no en un README antiguo.
2. Un `admin` configura los ajustes compartidos en **Configuració → General →
   Esfer@**; `administratiu` puede configurar su acceso personal. `access_url` exige HTTPS;
   HTTP solo para pruebas locales. `centre` es una etiqueta. El adaptador usa
   `https://formacio.bfgh.aplicacions.ensenyament.gencat.cat/bfgh/gestioeconomica/#/`.
   No inferir URL productiva sustituyendo el nombre del servidor.
3. Abrir **Eines → Esfer@ → Navegador** e identificarse en GICAR con acceso propio.
   `submitted` solo significa formulario enviado; comprobar portal y consulta
   efectiva. Segundo factor, CAPTCHA o login cambiado requieren intervención
   en el circuito de autenticación.
4. Seleccionar centro **en Esfer@** y verificar código externo, no solo nombre.
5. Abrir **Resum i dades** y consultar presupuestos. Elegir por ID, tipo y año;
   consultar proveedores o facturas del presupuesto seleccionado.
6. Comprobar centro devuelto, error, truncamiento, fecha de lectura y filtros.
   Búsqueda visual y páginas de 25 filas usan registros ya cargados. La suma de
   facturas cargadas no anuladas no es balance oficial.
7. Si caduca sesión, cambia centro o JSON, descartar resultado, recuperar
   contexto y repetir lectura; no reutilizar catálogo del centro anterior.

### Contrato de consulta

`frontend/src/sfera/contract.ts` solo admite
`query({dataset: 'budgets' | 'suppliers' | 'invoices', budgetId?})`.
El proceso principal verifica cuenta, contexto y presupuesto del centro.

| Dataset | Método/ruta bajo `/bfgh/AppJava/bfgh_gesteco/services` | Alcance |
| --- | --- | --- |
| `budgets` | `GET /pressupost/centre` | Presupuestos del centro activo |
| `suppliers` | `GET /proveidor/cerca` | Proveedores del centro activo |
| `invoices` | `POST /factura/cerca/filtre` | Año contable y presupuesto, excluyendo gasto simplificado |

El POST de búsqueda es una lectura específica. No clasificar todo POST como
escritura ni todo GET como inocuo; mantener operaciones conocidas. El adaptador
solo admite el origen/ruta de formación. Los códigos `G/M`, `A/T` o `T/F`
observados no son un catálogo universal.

El resultado tiene campos permitidos, presupuestos, centro, ID presupuesto,
`totalRows`, `truncated`, `completedAt`, `error` y trazas. Limita respuesta a
12 MB, filas mostradas a 10.000 y cadenas a 2.000 caracteres. `totalRows` cuenta
respuesta recibida, sin garantizar universo del portal. No incluye líneas
fiscales/vencimientos completos. Los datos no se persisten en Hub/localStorage.
Contexto y cabeceras internas de AngularJS se usan en memoria, sin transporte
arbitrario hacia el renderer/agentes. Cabeceras numéricas se convierten a texto.

`desktop/SFERA.md` declara exploración anterior sobre AngularJS 1.5.7 y versión
12.40.2_B000: lectura `GET /factura/{id}` y observación de
`PUT /factura/validate` y `PUT /factura/desa`. No se han comprobado escrituras
en esta revisión. Son servicios internos observados, **no una API pública
contratada**. No usar el DTO sintético directamente para exportaciones
productivas; el ensayo conectado de formación lo remapea y requiere revisar
implementación y autorización.

### Ensayo conectado de formación

El WIP añadido durante la revisión incorpora `SferaInvoiceBridge` con
`catalog(budgetId?)`, `prepare({budgetId, bankId, movements})` y `create(planId)`.
La pantalla **Prova d'extractes**, ruta `/eines/sfera/prova-extractes`, puede
invocar escrituras reales en formación. No confundirla con el simulador sin red.

`desktop/src/main/sfera/invoices.ts` remapea datos ficticios a catálogos reales
y realiza búsqueda previa, `PUT /factura/validate`, `PUT /factura/desa` y
relectura. `portal.ts` restringe el origen a formación. El código observado fija
2026, hasta dos facturas pequeñas pendientes sin pago y tratamiento fiscal
simplificado; rechaza centros configurados para liquidar IVA. **No se ejecutó
este ensayo ni se confirmó su efecto remoto en esta revisión documental.**

Las escrituras van como `fetch` del mismo origen dentro de la página del portal,
no con su `$http`. El interceptor `responseError` de `AppClient` (en
`libs_concat.js`) solo trata el 401. Cualquier otro error lo resuelve como
`undefined`, con lo que se pierden el estado y el cuerpo de la respuesta.

Observación del 2026-10-12 (formación, un centro de prueba): `PUT /factura/validate`
responde 405 `HTTP method PUT is not supported by this URL` (HTML genérico del
contenedor) cuando el servidor falla al procesar el cuerpo. El error de un `PUT`
acaba en la página de error, que no admite `PUT`. El 405 **no** significa que
falte el método: oculta un error de datos. Pasa igual con el transporte del
portal y con cuerpo `{}`.

Al quitar solo `centreCost` de la línea del portal se reproduce el 405. Basta
`{id}` en `partidaPressupost`, `centreCost` y `compteBancari`. El centro de coste
sale de `centreCostDesglosPartida` de la partida (`/partidaPressupost/cerca/filtre/{id}/DESPESA`).
Las facturas manuales observadas usan `tipusPagament` `TR` (transferencia) o `R`.
Con línea + `centreCost` + venciment `TR`, validate responde 200 `{}`. Un
duplicado responde 200 `{"numDocExtern":true}`.
`validate` no comprueba longitudes, pero `desa` falla con el mismo 405 genérico
si un campo supera su columna. Los límites son los `maxlength` del formulario:
número de factura (`identificadorDocProveidor`) 20, número interno 20,
descripción 100, descripción del venciment 200 y observaciones 500. Las 307
facturas del centro observado no pasan de 20 caracteres en el número. El ensayo
usa `CSC-POC-xxxxxx-M001` (19) y comprueba los límites antes de enviar.
`SFERA_PROBE_ALLOW_VALIDATE=1` deja pasar solo `/factura/validate` en
`scripts/probe-sfera.mjs`, que además registra cabeceras y estado de las escrituras.

Los planes están en memoria. El UUID por preparación modifica el número de
factura: repetir el mismo plan y preparar otro lote son casos diferentes.
La comprobación de relectura revisada contrasta presupuesto, proveedor y total;
no todas las fechas, líneas, impuestos o vencimientos. Este código no sustituye
idempotencia persistente por documento ni las validaciones propuestas más abajo.

### Sesiones y comandos

El navegador usa `WebContentsView`, sandbox y aislamiento, sin Node o preload
de Cosecre en el portal. Particiones y credenciales se separan por Hub, cuenta y
herramienta. Contraseñas cifradas con `safeStorage`; se rechaza Linux `basic_text`.
Hub solo guarda `access_url`/`centre` en `AppSetting` de `cosecre-sfera`, sin
secretos. Los tokens del Hub no autentican en Esfer@.

Navegador y datos conservan el portal oculto al alternar; salir de ambos destruye
contexto activo conservando cookies. Borrar sesión y eliminar credenciales son
acciones distintas. Autologin reconoce un formulario GICAR concreto; no garantiza
autenticación en cualquier popup. La URL visible puede contener parámetros
transitorios: sanearlos en evidencias.

| Comando existente | Uso y condiciones |
| --- | --- |
| `just setup`, `just dev`, `just app` | Dependencias, servicios y escritorio; consultar justfile actual |
| `just check`, `just build` | Comprobación y construcción de clientes |
| `just test` | Pruebas Hub con gestión Python `uv` |
| `just check-sfera` | Receta WIP con fixtures locales aislados y tests de ajustes; dejar `SFERA_CHECK_PORTAL` sin definir para evitar remoto opcional |
| `just check-sfera-poc` | Receta WIP para simulador de facturas sin red; también se incluye en `check-sfera`. No prueba alta conectada |
| `just explore-sfera` | Investigación WIP sobre copia de perfil autenticado y servicios reales; revisar autorización y contexto antes de ejecutar |

`scripts/sfera-research-steps.mjs` fija centro, presupuesto, ejercicio y versión;
no es una herramienta general de exportación ni un check rutinario. Evidencias
y perfiles en `output/playwright/sfera/`, ignorados por Git, pueden contener
datos privados. La cobertura sintética no demuestra compatibilidad productiva o
registro contable.

## Datos y contratos que necesita el backend

Esta sección es **diseño propuesto**. Usar entidades actuales como origen sin
atribuirles semántica oficial que aún no representan.

### Correspondencia de campos

| Origen Cosecre | Uso posible | Validación o ampliación necesaria |
| --- | --- | --- |
| `Document.internal_doc_number` | Referencia propia estable | ID y código remotos independientes |
| `num_factura`, `data_factura`, `tipus_document` | Número, fecha y clase documental | Conservar original; clase oficial y fecha contable adicionales |
| `proveidor`, `cif_proveidor`, dirección | Resolver tercero | Maestro, tipo de identidad, país, estado e ID remoto; no unir por nombre |
| `cif_proveit` | Destinatario | No confundir NIF del proveedor con el del centro |
| `compte_corrent` | IBAN detectado | Puede ser del proveedor; no identifica automáticamente tesorería del centro |
| `import_value` | Total extraído | Faltan bases, tipos/cuotas IVA, IRPF y líneas; no suponer impuesto cero |
| `descripcio`, `descripcio_compra`, transcripción | Concepto y apoyo documental | Separar texto original y explicación local; transferir solo campos pertinentes |
| `data_pagament`, `pagament`, `metode_pagament` | Indicio de pago | No acreditan vencimiento liquidado; comprobar aplicación, cuenta e importe |
| `pressupost_afectat` | Cuenta/bolsa local | No es partida ni ID presupuesto; General, Material i Sortides, Menjador, Caixeta y Targeta Prepagament necesitan mapping |
| `Partida.codi`, `codi_finalista`, `codi_pare` | Estructura presupuestaria | Código externo no es ID remoto; centro, ejercicio y tipo de presupuesto |
| `MovementPartida.import_assignat` | Apoyo al reparto | No reconstruye líneas de factura; exigir importes explícitos y revisados |
| `BankMovement`, `PaymentMatch` | Evidencia de pago | Aplicaciones por documento/vencimiento e importes parciales |
| `validat`, `sheet_state`, `sheet_snapshot` | Revisión/sincronización local | Estado remoto separado; resolver conflicto hoja/Hub antes del plan |
| `Upload`, `file_link`, Drive | Original/evidencia | Hash, disponibilidad y permisos; comprobar soporte de adjuntos en destino |
| `Request`, solicitante/responsable | Procedencia y revisión interna | No equivalen a tercero, contacto o cargo Esfer@ |

Referencias consolidadas: `hub/src/cosecre_hub/models.py`,
`hub/src/cosecre_hub/schemas/documents.py`,
`hub/src/cosecre_hub/api/documents/register.py`,
`hub/src/cosecre_hub/api/reconciliation.py` y
`hub/src/cosecre_hub/api/partides/models.py`. `validat=True` en la oficina no
comprueba toda la completitud fiscal exigible por el destino.

El registro usa `float`; el nuevo contrato debe calcular con `Decimal` o
céntimos enteros y serializar importes inequívocos. Mantener original, redondeo
y regla de total por línea. OCR o salida del modelo no son datos fiscales
confirmados. Documentos de tipo presupuesto, albarán, recibo u otros necesitan
clasificación: no convertirlos en facturas por estar validados.

### Entidades propuestas

| Entidad | Contenido mínimo |
| --- | --- |
| `SferaContext` | Entorno/origen, código/ID centro, NIF, ID/tipo presupuesto, ejercicio, versión/capacidades y usuario/rol verificados |
| `RemoteMapping` | Sistema, entorno, centro, entidad, UUID local, ID/código remoto, clave externa, última lectura y fingerprint |
| `Counterparty` | Proveedor/aportador, documento fiscal, identidad/país, contacto, estado y bancos pertinentes |
| `AccountingDocument` | Operación, número/referencias, fechas separadas, moneda, total, líneas/impuestos y relación original/abono |
| `AccountingLine` | Partida/subpartida, finalista, centro de coste, base, IVA/retención, total y reserva cuando aplique |
| `DueDate`, `PaymentApplication` | Fecha, importe, método/cuenta, estado y aplicación parcial de movimiento a vencimiento |
| `IncomeRecord`, `CollectionApplication` | Aportador, concepto, imputación, fechas, derecho de cobro, vencimientos y cobros |
| `AdministrativeRecord` | Contrato específico de correspondencia, certificado, matrícula, custodia, diligencia o dedicación |
| `ExportBatch`, `ExportItem`, `ExportAttempt` | Plan congelado, autorización, dependencias, estados, intentos, IDs remotos y evidencia saneada |

El mismo ID numérico o código puede existir en formación, producción o varios
centros. Toda correspondencia incluye contexto. Migrar presupuesto por año a
presupuesto por centro, entorno, tipo y ejercicio antes de soportar varios; no
mezclar dimensiones mediante etiquetas. Un mapeo caducado debe revalidarse.

### Ejemplo sintético de contrato propio

Es un **borrador Cosecre**, no payload de un servicio Esfer@. IDs y códigos son
ficticios; el adaptador transformará el objeto después de verificar su contrato.

```json
{
  "schema_version": 1,
  "entity": "supplier_invoice",
  "source_uuid": "00000000-0000-4000-8000-000000000001",
  "source_ref": "DOC-SYNTHETIC-001",
  "context": {
    "environment": "training",
    "centre_code": "00000000",
    "remote_budget_id": 901,
    "budget_type": "general",
    "financial_year": 2026
  },
  "document_number": "SYNTHETIC-2026-001",
  "document_date": "2026-10-10",
  "accounting_date": "2026-10-12",
  "supplier_mapping_ref": "supplier-synthetic-01",
  "currency": "EUR",
  "lines": [{
    "partida_mapping_ref": "partida-synthetic-01",
    "base": "100.00",
    "vat_rate": "21.00",
    "vat_amount": "21.00",
    "withholding_amount": "0.00",
    "total": "121.00"
  }],
  "total": "121.00",
  "due_dates": [{"date": "2026-11-10", "amount": "121.00", "state": "pending"}],
  "payment_applications": [],
  "review_state": "draft"
}
```

`source_uuid` se asigna una vez y se persiste; `source_ref` es referencia legible.
El 21 % es dato sintético, no tipo por defecto. Un borrador sin cuotas/retenciones
verificadas queda incompleto. Este ejemplo no inventa ID de proveedor, partida o
cuenta a partir de un número de fila de la hoja.

## Protocolo propuesto de exportación

Esta sección define el comportamiento que se deberá implementar; **no existe
todavía una cola o servicio de exportación**.

### Preparar y comprobar

1. Resolver obligación/destino por entidad. Separar factura, abono, gasto
   simplificado, ingreso, transferencia y acto administrativo.
2. Resolver/integrar cambios pendientes de hoja y Hub. Capturar revisión/hash de
   datos y originales. Una edición posterior invalida el plan afectado.
3. Leer contexto y catálogos completos. Resolver terceros, presupuesto, partidas,
   impuestos, cuentas y dependencias. Si falta maestro, proponer alta explícita
   con sus requisitos, sin fusionarlo por similitud.
4. Comprobar duplicados locales/remotos con UUID propio y clave candidata de
   entorno, centro, tipo, tercero, número, fecha y total. Coincidencia parcial
   es conflicto; ni importe ni hash de PDF bastan. Leer detalle si hay candidato.
5. Validar identidad, fechas, precisión, totales, reparto, referencias, estados,
   capacidad y límites. Conservar errores por campo y origen, sin efectos remotos.
6. Usar validación del portal solo cuando su semántica esté comprobada. No asumir
   que un endpoint llamado `validate` carece de efectos. Fijar versión/capacidad.
7. Mostrar acciones, dependencias, centro/entorno, importes, pagos separados,
   advertencias y errores bloqueantes. Asociar autorización vigente a hash y
   alcance del plan concreto; los cambios materiales requieren nueva revisión.

### Ejecutar y verificar

El **Hub** conserva dominio, permisos, plan y diario. Un **runner desktop** usa
la sesión personal autorizada mediante operaciones tipadas y adaptadores por
entorno/versión. Una integración oficial con autenticación de servicio podría
sustituir este transporte. El Hub actual carece de sesión Esfer@; no poner
credenciales en `AppSetting` ni enviar tokens Cosecre al portal.

Ejecutar maestros antes de documentos y documentos antes de aplicaciones de
pago/cobro. Pagos/firmas solo si alcance autorizado y capacidad verificada los
incluyen. Comprobar contexto, revisión y permisos antes de cada operación.
Serializar escrituras de la misma sesión/contexto; no asumir atomicidad del lote.

Tras guardar, releer por ID y comparar tercero, número, fechas, líneas,
impuestos, total, presupuesto y estado. Conservar ID/código generado. En
pagos/cobros comprobar aplicación, vencimiento y cuenta. En procesos diferidos
o firmados comprobar resultado de cada elemento y firma pertinente.

### Estados y recuperación

| Estado propuesto | Significado y transición |
| --- | --- |
| `draft` | Borrador; preflight lleva a `blocked` o `ready` |
| `blocked` | Datos, referencias o permisos incompletos; corregir y preparar de nuevo |
| `ready` | Plan validado; autorización vigente lo lleva a `approved` |
| `approved` | Hash/acciones autorizadas; runner reclama y pasa a `executing` |
| `executing` | Intento persistido antes de llamada; falta resultado confirmado |
| `succeeded` | Escritura y relectura coincidentes |
| `uncertain` | Timeout, respuesta perdida o cliente cerrado; consultar antes de repetir |
| `reconciled` | Lectura posterior confirma que operación incierta se realizó |
| `conflict` | Discrepancia o identidad ambigua; revisar sin sobrescribir |
| `failed` | Solo cuando se confirma ausencia de efecto remoto y fallo; reintento sujeto a contexto/plan vigentes |
| `cancelled` | Elemento no ejecutado; no anula registros ya creados |

Si el runner muere en `executing`, recuperar como incierto. Persistir intento
antes de la llamada y después resultado, duración, ID y evidencia saneada.
Bloquear ejecución concurrente y usar idempotencia local; no asumir soporte de
idempotencia o ETag en Esfer@. Continuar lotes por pendientes dejando confirmados
intactos. Cancelar no hace rollback; revertir requiere circuito oficial y nueva
operación trazable.

### API propuesta del Hub

Implementado el 2026-10-12 para `supplier_invoice` en `hub/src/cosecre_hub/api/sfera/`
(trabajo local, sin desplegar):

- `GET /api/v1/sfera/capabilities`: qué se verificó, dónde y cuándo.
- `POST /api/v1/sfera/export-plans`: recibe el contrato propio con contexto e IDs
  remotos explícitos.
- `GET /api/v1/sfera/export-plans` y `GET /api/v1/sfera/export-plans/{id}`.
- `POST /api/v1/sfera/export-plans/{id}/approve`: con `plan_hash`.
- `POST /api/v1/sfera/export-plans/{id}/items/{item}/claim`: crea el intento
  antes de la llamada; serializa por entorno y centro.
- `POST /api/v1/sfera/export-plans/{id}/items/{item}/result`: solo el intento
  vigente; `failed` exige `no_effect_confirmed`; un éxito exige relectura
  coincidente y crea `SferaRemoteMapping`.
- `POST /api/v1/sfera/export-plans/{id}/items/{item}/recover`: `executing` pasa
  a `uncertain`.
- `POST /api/v1/sfera/export-plans/{id}/items/{item}/reconcile`.
- `POST /api/v1/sfera/export-plans/{id}/cancel`.

El preflight bloquea lo no verificado: líneas sin centro de coste, longitudes,
IVA o IRPF distintos de cero, formas de pago distintas de `TR`/`R`, centros que
liquidan IVA y producción. Los duplicados se buscan por proveedor + número en el
plan, en otros planes activos y en los mapeos del mismo entorno y centro.

El runner (`window.cosecreDesktop.sferaExport.run(planId, itemId)`) solo recibe
IDs. Toma el payload del Hub y comprueba antes de escribir el centro, el
presupuesto, el ejercicio y los límites contra la sesión. Si ya existe una
factura igual, la marca como `uncertain`. Tras un fallo de `desa`, relee para
confirmar si se guardó.

Añadidos después:

- `POST /api/v1/sfera/preflight`: las mismas comprobaciones, sin guardar nada.
- `DELETE /api/v1/sfera/export-plans/{id}`: solo si ningún elemento se ha
  reclamado; si no, el diario se conserva y hay que cancelar.
- `DELETE /api/v1/sfera/export-plans/{id}/items/{item}`: antes de aprobar; da un
  nuevo hash y vuelve a comprobar el plan.

El escritorio expone también `sferaExport.reconcile(planId, itemId)`, que lee el
portal y concilia, y `sferaExport.diagnose()`. Este último es de solo lectura y
comprueba:

- sesión y presupuesto;
- liquidación de IVA;
- centros de coste por partida;
- bancos y proveedores;
- búsqueda de facturas;
- capacidad del Hub;
- una factura sintética pasada por el preflight.

**Prueba end-to-end con Hub local.** Arrancar `hub` con `COSECRE_PORT=8011` y una
BD temporal. Lanzar `scripts/probe-sfera.mjs` con `SFERA_PROBE_HUB_URL`,
`SFERA_PROBE_HUB_TOKEN`, `SFERA_PROBE_HUB_USER` y
`SFERA_PROBE_ALLOW_INVOICE_WRITES=1`: la copia temporal del perfil apunta al Hub
local y reindexa la credencial GICAR cifrada. Crear y aprobar el plan por API y
ejecutar `sferaExport.run` desde la ventana.

Diseño original de las rutas, que siguen el principio de acciones cerradas, sin
transporte HTTP ni JavaScript arbitrarios hacia el portal.

| Ruta propuesta | Responsabilidad |
| --- | --- |
| `POST /api/v1/sfera/export-plans` | Preparar y validar IDs origen con contexto esperado |
| `GET /api/v1/sfera/export-plans/{id}` | Acciones, problemas, diff, revisión y hash |
| `POST /api/v1/sfera/export-plans/{id}/approve` | Registrar autorización/alcance del plan concreto |
| `POST /api/v1/sfera/export-plans/{id}/execute` | Encolar para runner disponible; no aceptar URLs o secretos |
| `GET /api/v1/sfera/export-jobs/{id}` | Estado global/por elemento, intentos y errores saneados |
| `POST /api/v1/sfera/export-jobs/{id}/reconcile` | Resolver resultados inciertos/discrepancias mediante lectura |
| `POST /api/v1/sfera/export-jobs/{id}/cancel` | Cancelar pendientes sin fingir reversión |

El runner reclama con lease y verifica cuenta/centro. Un lease vencido puede
dejar una petición en curso en el runner anterior: pasar a `uncertain`, bloquear
nueva escritura y conciliar antes de reclamar el elemento. Comprobar claim y
lease vigentes antes de cada llamada, con fencing local para impedir que un
runner antiguo continúe; esto no cancela una llamada ya enviada al portal.
Registrar desconexión/expiración y publicar capacidades por entidad/acción/entorno
y fecha de prueba.
Ausencia de runner es estado esperado, no permiso para convertir Hub en proxy
de sesión. Conservar tanto permisos locales como permisos reales del destino.

## Casuísticas de aceptación

Son **condiciones propuestas para pruebas de Cosecre**. Los circuitos que las
motivan se describen arriba. Usar fixtures sintéticos; probar persistencia,
relectura y recuperación, no solo el constructor del payload.

| Caso | Resultado esperado antes de habilitar exportación |
| --- | --- |
| Formación/producción comparten IDs | Mappings separados y ningún cambio implícito de entorno |
| Ajustes indican un centro y sesión otro | Bloqueo por identidad real, no por etiqueta |
| General y Menjador en el mismo año | Presupuestos/partidas separados; importar uno no reemplaza otro |
| NIF del Excel o destinatario distinto | Bloquear discrepancia; señal `nif_matches` no basta |
| Partida retirada, padre o ejercicio nuevo | Resolver hoja elegible del catálogo actual y no ID antiguo |
| Finalista o centro de coste ausentes | Dependencia/revisión; cuenta bancaria no los sustituye |
| Fecha documental, contable y pago en años distintos | Conservar cada fecha y resolver pendientes; no cambiar original |
| Factura pendiente sin movimiento | Registrar obligación completa sin pago ficticio |
| Dos movimientos pagan parcialmente una factura | Aplicaciones/vencimientos por importe; primer match no liquida todo |
| Un movimiento paga varias facturas | Registros individuales y reparto explícito, sin repetir total |
| Pago incluye factura y comisión | Conceptos separados; no alterar total fiscal para cuadrar banco |
| Movimiento repartido entre partidas | Importes revisados; no trasladar reparto igual automático |
| Varias bases, IVA/IRPF y redondeos | Totales por línea/cuotas; no rellenar cero por falta de datos |
| Tique sin datos fiscales suficientes | Circuito y evidencia correspondientes; no inventar factura |
| Abono entra como importe positivo | Vincular corrector; no crear ingreso por signo |
| Devolución parcial o corrección ya pagada | Releer estado; circuito permitido, sin borrar para cuadrar |
| Banco → Caixeta o recarga de tarjeta | Traspaso conciliado; compra final y recarga no duplican gasto |
| Reembolso a persona que adelantó dinero | Separar proveedor original, solicitante y perceptor |
| Familias, subvención o fondo afectado | Clasificación por finalidad/tercero y catálogo vigente |
| Cobro agrupado, parcial o remesa devuelta | Derechos/aplicaciones individualizados con incidencias |
| Retención o liquidación fiscal | Estado independiente de factura, pago y presentación externa |
| Factura electrónica ya recibida | Buscar referencia/identidad antes de crear duplicado desde PDF |
| Apertura y saldos de sistema anterior | Fecha de corte, pendientes y remanente; sin movimientos ficticios |
| Presupuesto se cierra durante lote | Detener pendientes y conservar confirmados; nueva preparación |
| Hoja y Hub en conflicto | Resolver revisión antes del plan aunque documento esté validado |
| OCR confunde número/NIF/fecha/IBAN | Error por campo con original; no alta de maestro inferida |
| Nombre parecido, NIF distinto o extranjero | Identidades separadas y documento explícito |
| Igual número en proveedores distintos | Matching contextual; no falso duplicado |
| Igual tercero/número con importe distinto | Conflicto; sin duplicar ni sobrescribir silenciosamente |
| Respuesta perdida tras guardar | `uncertain`; releer/corresponder antes de reintentar |
| Reinicio, doble clic o dos runners | Un trabajo activo y recuperación persistente |
| Cambia centro/usuario/rol | Invalidar lectura/plan; no continuar con catálogo anterior |
| Respuesta truncada o sin detalle | No certificar cobertura ni ausencia de duplicados |
| Cambia DOM/JSON/catálogo | Deshabilitar capacidad con diagnóstico; sin payload arbitrario |
| Correspondencia anulada/certificado erróneo | Conservar número/historial, sin renumerar |
| Matrícula/currículo/enseñanza no elegibles | Requisito específico; sin crear ficha fuera del circuito |
| Diligencia/petición pendiente de firma | Pendiente; sin éxito final ni firma por rol local |
| Lote académico finalizado con fallos | Resultado por alumno; continuar solo elementos elegibles |
| Baja ya archivó expediente | Leer estado antes de pedir otro archivo |
| Undo local/borrado en Sheets/cancelación | Conservar mappings y señalar divergencia; no fingir reversión |

Para anticipos, compensaciones y movimientos retroactivos, una
[nota territorial de cierre 2019](https://serveiseducatius.xtec.cat/vallesoccidental3/seminari-secretaria/tancament-exercici-2019/)
describe crédito del proveedor y advierte sobre arqueos tras cambios. Es contexto
histórico para plantear pruebas, no instrucción vigente ni código de 2026.

## Plan de desarrollo

1. **Contexto y cobertura.** Identificar centro, enseñanzas, entornos y circuitos;
   resolver destinos obligatorios, comedor/presupuestos e instrucciones vigentes
   del Portal de centre. Consultar posibilidad de integración oficial.
2. **Lectura y modelos.** Versionar/validar WIP de acceso en su tarea propia.
   Ampliar catálogos/detalle; migrar presupuesto por contexto y crear mappings,
   líneas fiscales, vencimientos y aplicaciones parciales. Evitar importes cero
   y duplicados silenciosos. El resumen actual no habilita escritura.
3. **Preparación.** Implementar DTO propio, revisión de campos, snapshot, plan
   sin efectos, duplicados y diario persistente; pruebas negativas y recuperación.
4. **Factura pendiente.** Verificar contrato en entorno de pruebas autorizado,
   con maestro/catálogos resueltos. Registrar entidad autorizada, releer detalle,
   demostrar recuperación sin duplicados y ausencia de pago implícito antes de
   habilitar producción.
5. **Ampliación económica.** Maestros, gasto simplificado, abonos, ingresos,
   pagos/cobros, tesorería, impuestos y cierre por capacidades independientes.
   Un botón exportar no debe facturar indiscriminadamente cada movimiento.
6. **Administración y academia.** Contratos por correspondencia, certificados,
   ficha/matrícula, expedientes y personal, con identidad, autorización oficial,
   firma y resultados por lote.

Una capacidad está lista cuando tiene requisitos/formato verificados, prueba
positiva/negativa, confirmación por relectura, recuperación ante respuesta perdida
y evidencia saneada. Un simulador que devuelve 200 solo acredita su lógica.
Registrar entorno, versión y fecha para que otro agente pueda valorar vigencia.

## Fuentes y actualización

Consulta pública: **12 de octubre de 2026**. Ateneu académico se identifica como
octubre de 2022, v1.3; los materiales económicos no deben considerarse actuales
por la fecha de rastreo del buscador. El DOIGC es mutable: verificar fecha interior
en futuras revisiones. Reglas vigentes del centro, ejercicio y enseñanza
prevalecen sobre ejemplos formativos anteriores.

El [índice económico oficial](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/index)
y el [índice académico y administrativo](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/gacademica/index)
permiten localizar los procedimientos. Cada proceso anterior enlaza su fuente
primaria. Se resume el contenido necesario y se remite al manual para detalle.

No se ha identificado en las fuentes consultadas un contrato externo actual de
API ni plantilla universal de importación hacia Esfer@. **No demuestra que no
exista integración restringida**: obtener del Departament autenticación,
formatos, permisos, límites, versionado y entorno de pruebas antes de comprometer
transporte estable. Las extracciones CSV/Excel descritas son dirección de salida.

### Comprobaciones pendientes en el centro

- URL productiva/versión, documentación restringida del Portal de centre y posible
  API/importación autorizada con sus condiciones.
- Estructura del ejercicio, finalistas, centros de coste, presupuestos y cuentas,
  incluyendo cambios de catálogo anual; no fijar códigos históricos en el adaptador.
- Semántica/efectos de cada servicio interno antes de habilitarlo, campos
  obligatorios, adjuntos, límites, errores y formato de validación.
- Duplicados, pagos parciales, abonos, pendientes y cierre en entorno autorizado.
- Enseñanzas concretas, permisos/cargos, firmas, archivo automático y lotes.

### Mantener esta referencia

Al incorporar capacidad, actualizar estado con commit/pruebas, retirar WIP
correspondiente y añadir contrato/límites. Al revisar fuentes conservar
fecha/versión y ajustar casos afectados. Describir evidencia saneada sin copiar
datos privados a Git. Mantener separados hechos oficiales, comportamiento de
código, observaciones anteriores y diseño.
