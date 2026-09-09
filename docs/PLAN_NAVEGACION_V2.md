# Sistema WORMS · Plan de migración a la navegación por áreas y sectores

Fuente: `Sistema WORMS.xlsx` (Fernando, 28/08/2026) — 5 hojas, 56 imágenes y 38 cuadros de texto leídos completos — cruzado con el código real de `app_carga` (app.py 472 KB + 45 módulos) y la base `worms-prod`.

---

## 1. Qué pide el director (lo que dice el Excel, no sólo el resumen)

**Objetivo declarado (Hoja de Inicio):** "centralizar la información, que todos veamos la misma información y eliminar los canales excesivos de comunicación". Hojas azules = sistema actual comentado; amarillas = propuesta.

### 1.1 Raíz
- Nuevo título: **SISTEMA WORMS ARGENTINA** → dos tarjetas: **ADMINISTRACIÓN** y **PRODUCCIÓN**. Razón textual: *"mantener el mismo esquema que propusimos en el servidor y simplificar las autorizaciones"*.
- La portada actual "no es panel de producción porque incluye adm y cierres mensuales".
- Marcado para **eliminar** de la portada: línea de portería (→ va a sección Portería), expander "PCs intentando subir" (eliminar), niveles WeDo (→ sección Stock). Los 5 KPI actuales: "mantener la idea de pantallazo general pero de manera diferente".

### 1.2 Área Producción (al entrar)
- Header **ÁREA PRODUCCIÓN** + 5 indicadores: **1** acopio disponible en tanques, sólidos y piletas · **2** descargas pendientes/en proceso (*"no sólo los líquidos"*) · **3** personal en planta · **4** sectores activos · **5** tickets pendientes de análisis. Nota: *"¿qué indicadores queremos ver? Lo validamos con Eugenia, Pablo y Fernando"*.
- Tarjetas **Centro de Planificación** y **Reportes**, luego grilla de **14 sectores** (Reactor, Bachas, Piletas, Exportación, Disp. Final Líquidos, Disp. Final Sólidos, Sólidos, NFU, Compost & Fertilizante, Taller & Mantenimiento, Laboratorio, Portería, Intendencia, Logística) y una tarjeta roja **Panel de Control** (*"capacidad total ocupada de la planta y no mucho más"*, gráfico de barras horizontal de % capacidad de acopio por producto usando la planilla de parámetros).
- Autorizaciones: panel general → Pablo, Eugenia, Fernando. Sectores → los mismos + supervisores.

### 1.3 Dentro de un sector (Reactores como modelo)
- Header **SECTOR REACTORES** + 5 indicadores del sector: acopio disponible del sector · acopio de MP a procesar · procesos activos · personal en planta · % cumplimiento de planificación.
- Tarjetas: **Planificación · Desvíos · Formulación** (las tres que pediste) y además **Stock, Panel de Producción, Seguimiento Producción, Orden Producción, Laboratorio, Acopio, Taller & Mant., Reportes, RRHH, Inventario**.
- **Formulación**: tabla por fórmula (F101, F102…) con `FECHA ACTUALIZACION · #FORMULA · ITEM · DESCRIPCION · ACIDEZ · P · S`: fila MP (V-AG-C 50 % · 200 ppm · 100 ppm), filas insumo (glicerina, potasa, fuel oil), filas "REVISION DE TEMP Y ACIDEZ" hora a hora (50→40→35→25→15→13 % a 80 °C) y DECANTACION. *"Cada MP tiene su formulación en tiempo, insumos y demás. Se aplica a la planificación como desplegable."*
- **Planificación**: tabla semanal `# OP · DIA · FECHA · SEMANA · PROCESO · FORMULACION · HORA INICIO · HORA FIN · RESPONSABLE` + botón **Cargar** por fila. *"Se carga un día antes por si hay que cambiar. Al cargar impacta en el sector y en la PARTE 1 de Seguimiento Producción."* Estados a sumar: No iniciado / Iniciado / Finalizado. "Orden del día" = las filas de hoy.
- **Seguimiento Producción** (3 partes): **P1** orden del día · **P2** el operario aprieta *Orden Producción* y se despliega el **instructivo** (13 pasos: caldera, carga MP 30 t, glicerina 10 t, potasa 10 t, validar temp 80°, inicio RX 40 t, 6 revisiones temp/acidez, decantación) con botón **Cargar** por paso → pide *hora inicio/fin* (pasos 1-6) o *TEMP y ACIDEZ* (revisiones) · **P3** indicadores por RX: # RX, estado (a tiempo / fuera de crono / detenida), etapa, responsable. *"Esto genera la base de lo que realmente sucedió y se cruza contra la formulación. El Q de MP e insumo lo sacamos del stock. Así calculamos los desvíos."*
- **Desvíos**: por OP → `# RX · FECHA · SEM · variable (V-AG-C, GLICERINA, POTASA, TIEMPO RX, ARE-B) · DESVIO ±%`. Y "Stock proyectado vs stock real (radares)" desde seguimiento vs planificación.
- **Stock del sector**: botones Materia Prima / Insumos / Producto Terminado → **cuenta corriente** por producto (`FECHA · #TICKET · CC · CLIENTE/PROVEEDOR · ESTADO · SECTOR · INGRESO KG · EGRESO KG · SALDO`) + Descargar Excel. Desplegable de MP/insumos (V-ARE-A, A-ARE-A, V-AG-C, GLICERINA A/B, POTASA…). Pregunta abierta: *"¿cómo gestiono el stock? saldo − fórmula (impacta al terminar el proceso) − ajuste por desvío"*. Ver planilla Excel con Fer.
- **Laboratorio del sector**: sólo lo del sector; el supervisor busca por producto/ticket; la lista debe mostrar producto **con su calidad**. Indicadores generales de lab: análisis por día, finalizados, pendientes; *"el objetivo es evaluar el 100 % de los ingresos"* (ese indicador va en Portería).

### 1.4 Comentarios sobre lo actual (hoja azul)
- "Producción en planta" → renombrar **Producción Sector** (*"planta es la totalidad de sectores"*). El selector de proceso/opciones "no es el lugar"; la máquina de etapas está *"bien planteada, debería ser el INPUT del estado de la RX"*.
- Ingresos: sacar el gráfico por hora; dejar listado. Disponibilidad de descarga: varias piezas marcadas ✗. Laboratorio: *"no tiene la funcionalidad que dice tener"* — cada sector consulta lo suyo, el general sólo Pablo/Eugenia/Nico/Fernando.
- Notas: 1) armar planilla de stock para reflejar en el sistema · 2) armar panel de control general.

---

## 2. Qué ya existe y qué falta (contra código y base)

| Pedido | Ya existe (reusable) | Falta |
|---|---|---|
| Raíz Admin/Producción | `section` + `puede_seccion` + `secciones_app` por usuario; cookie de sección | Un nivel de "área" arriba de `section`; flag por usuario |
| Grilla 14 sectores | `dim_sector_gestion` (4: Reactores, Piletas, Bachas, Exportación), `dic_sector` (7) | 10 sectores sin fila ni datos (NFU, Compost, Sólidos, DF Sólidos, Intendencia, Logística, Taller, Portería, Lab, Reactor ya) |
| KPI 1 acopio disponible | tanques: `vw_stock_tanque_actual` + capacidad (`disponibilidad_descarga` ya calcula kL libres); piletas: `v_stock_total` provisorios | **sólidos: no hay dato** |
| KPI 2 descargas pendientes | líquidos: `fact_asignacion_afe` vs `produccion.transacciones` | estado de descarga por ticket para no-líquidos (**dato nuevo**) |
| KPI 3 personal en planta | `dim_usuario.ultimo_login` (6 logins hoy) | **no hay registro de presencia** |
| KPI 4 sectores activos | `fact_batch_proceso.estado` por sector (hoy sólo REACTORES tiene batches) | actividad de sectores sin batch |
| KPI 5 tickets pendientes | `fact_ticket_lab` PENDIENTE (97 hoy) — ya está en portada | — |
| Planificación semanal | `fact_batch_proceso` estado PLANIFICADO (Centro de Planificación), `gestion_semanal` (objetivos TN por semana ISO), `_render_cronogramas`, `plan_dia_reactor` (**vacía**) | grilla semanal por OP con hora inicio/fin, responsable, estado; botón Cargar → instructivo |
| Formulación | `dic_formula` (14, con `insumos`, `horas_proceso`, `parametros`, default por sector/MP/PF), `dic_proceso_etapa` (19 etapas, targets de duración), `dic_etapa_duracion`, selector de fórmula en Planificación | **pasos con valor esperado** (acidez/temp por hora, kg por insumo, tolerancia, offset de tiempo), fecha de actualización/versión |
| Seguimiento por pasos | máquina de estados INICIAR (Arrancar→Reacción→Reposo→Decantar→Listo), `fact_etapa_evento` (204 eventos, inicio/fin), `v_perf_reaccion_etapa` | captura de **mediciones por paso** (temp, acidez, kg) contra esperado |
| Desvíos | `performance_section` (tiempos vs crono), `_desvio_cronograma`, Dirección → 📉 Desvíos (stock), `aplicar_desvios*.py` | desvío por variable de fórmula (MP, insumos, tiempo RX, PF) por OP |
| Cuenta corriente stock | `v_movimientos_stock`, `stock_section` (libro mayor), `informe_stock`, Excel | vista con el layout del director (ingreso/egreso/saldo por producto, CC cliente) |
| Capacidad por producto | `v_capacidad_acopio_producto`, "Poco espacio para…" en Disponibilidad | barra horizontal % ocupado en Panel de Control |
| Lab por sector | `LAB` con 8 vistas, filtros | filtro por sector del usuario + producto·calidad en la fila |

---

## 3. Decisión: ¿página gemela o secciones en el mismo lugar?

**Ninguna de las dos en su forma pura. Recomendación: una capa de navegación nueva dentro de la misma app, detrás de un flag por usuario, que envuelve las secciones existentes sin duplicarlas.**

Por qué no una app gemela: habría que mantener dos copias de 2,3 MB de Python; la sesión/cookie/permisos se parten; cada fix hay que hacerlo dos veces; y el día del corte es un big-bang. Por qué no "ir creando secciones ahí mismo" a secas: la portada actual ya tiene 15 tiles y no admite un tercer nivel sin convertirse en la lista que Fernando quiere sacar.

Cómo queda:

```
st.session_state.nav = {"area": "PRODUCCION"|"ADMIN", "sector": "REACTORES"|None, "vista": "PLAN"|"DESVIOS"|...}
st.session_state.section  ← se sigue usando tal cual (contrato intacto para los 45 módulos)
```

- `nav/` (paquete nuevo): `router.py` (resuelve `nav` → llama al `render(...)` existente con `contexto=`/`sector=`), `portada.py` (raíz + área Producción + KPIs), `sector.py` (home de sector: KPIs + tarjetas), `kpis.py` (queries cacheadas).
- Cada tarjeta nueva es un **wrapper de 5-20 líneas** que fija filtros y llama al módulo actual: Planificación → `planificacion.render(..., sector=)`; Formulación → `formulas_section.render(..., sector=)`; Desvíos → `performance_section` + nueva vista; Lab → `LAB` con filtro; Stock → `stock_section`. Los módulos ya aceptan `contexto=` (`disponibilidad_descarga`, `asignacion_afe`, `gestion_semanal`): es el patrón a extender.
- **Flag `prefs.nav_v2`** (ya hay `get_pref/set_pref` sobre `dim_usuario.prefs`): se activa primero para Fernando, Eugenia y Pablo; el resto ve la portada clásica. Un botón "Vista clásica / Vista nueva" en la sidebar. Cuando la nueva cubre el 100 % de los tiles, se invierte el default y a las 2 semanas se borra la clásica.
- Un usuario de un solo sector (`_LOCKED_ONE`) cae directo en su sector, sin raíz ni área.

---

## 4. Robustez: por qué "refresca demasiado" y qué se cambia

Diagnóstico sobre el código real:

1. **`st.cache_data.clear()` global después de cada escritura** — 27 veces en app.py, 34 en planificacion.py, 15 en despachos. `cache_data` es global al proceso: cuando un operario guarda, se vacía la caché de **todos** los usuarios y el próximo rerun de cada uno vuelve a pegarle a Supabase con cada `cat(...)` de la sección. Es la causa principal de la sensación de "recarga todo".
2. **Rerun de página entera por widget**: sólo 1 `on_click=`, 8 `st.form`, 36 `st.rerun()` en app.py. Cada click ejecuta los 472 KB de arriba a abajo. Fragmentos: sólo el armador de Despachos los usa.
3. **"Reinicia la página"**: al cortarse el websocket (Streamlit Cloud duerme, WiFi de planta, celular en background) se pierde `session_state`; la cookie recupera usuario y sección, pero no el sub-estado (pestaña, filtros, borrador). El chunk viejo tras deploy ya está mitigado por `autorecarga.py`.

Qué se hace (transversal, empieza en la Fase 0):

| Herramienta | Uso | Efecto |
|---|---|---|
| **Invalidación por dominio** en vez de `clear()`: `cat(sql, params, rev=REV["tanques"])`, con `REV` en `st.cache_resource` (dict compartido) y `bump("tanques")` tras cada escritura | reemplaza los 76 `clear()` | una escritura sólo invalida su dominio; las demás queries siguen cacheadas |
| **`st.fragment`** (Streamlit 1.44 lo soporta) con `st.rerun(scope="fragment")` | cada bloque de KPIs, cada tarjeta de sector, cada tabla editable | un click redibuja sólo el bloque |
| **Callbacks `on_click`/`on_change`** en vez de `if st.button(): … st.rerun()` | todos los botones nuevos | un rerun por acción en vez de dos |
| **Componentes propios con contrato `rev`** (patrón ya probado en `formulador/` y `ajuste_mp/`: React/HTML embebido, cero reruns hasta "Guardar") | instructivo paso a paso del operario, grilla semanal de planificación, editor de formulación | la pantalla más usada por operarios no rerunea nunca mientras carga |
| **`st.query_params`** `?area=PRODUCCION&sector=REACTORES&vista=PLAN&op=1001` | router | F5, link compartido por WhatsApp o reconexión vuelven exactamente al mismo lugar; complementa la cookie |
| **Borrador en base** (ya existe `plan_borrador` para Planificación) | instructivo del operario y formulario de OP | si se cae el websocket, no se pierde lo cargado |
| **`app.py` como router**: portada y sectores en `nav/`, sin código nuevo en app.py | estructura | cada rerun parsea menos; los módulos se importan sólo cuando se entran |
| Hosting sin "sleep" (Render/Railway/VPS chico) y pins `streamlit==1.44.1 + pyarrow` | infra | elimina el reinicio por app dormida en Streamlit Cloud |

Regla para todo lo nuevo: **ninguna pantalla nueva llama a `st.cache_data.clear()` ni a `st.rerun()` sin scope.**

---

## 5. Fases (cada una deployable sola, sin tocar lo que funciona)

### Fase 0 — Cimientos (sin cambio visible)  · ~1 semana
- `nav/router.py` + `st.query_params` + flag `prefs.nav_v2` + toggle en sidebar.
- `REV` por dominio y helper `cat(..., rev=)`; migrar los `clear()` de app.py y planificacion.py (los demás módulos, al tocarlos).
- `dim_sector_gestion`: agregar los 10 sectores con `icono`, `orden`, `activo`, `tiene_datos` (los sin datos se muestran atenuados con "próximamente"). Nombres exactos de la grilla del director.
- Permisos: `areas_app` derivado de `secciones_app` (Admin/Cierres/Dirección → ADMINISTRACIÓN; el resto → PRODUCCIÓN); sector visible = `dim_usuario.sectores`.
- **Criterio de salida**: con el flag apagado la app es byte a byte la misma; con el flag prendido se ve la raíz nueva vacía que redirige a la clásica.

### Fase 1 — Raíz + Área Producción  · ~1-2 semanas
- Raíz: SISTEMA WORMS ARGENTINA → Administración / Producción (Administración = tiles actuales de Admin, Cierres, Dirección, Consultas IA, Mejoras).
- Producción: 5 KPIs en un `st.fragment` con `ttl=60`:
  1. **Acopio disponible**: tanques (kL libres y % ocupado, de `disponibilidad_descarga`), piletas (`v_stock_total` PILETAS), sólidos → "sin dato" hasta Fase 5.
  2. **Descargas**: tickets del día sin asignación a tanque (líquidos) + tickets de familias no líquidas sin registro de descarga → contador "sin registrar".
  3. **Personal en planta**: nueva tabla `fact_presencia` (id_usuario, sector, ts_entrada, ts_salida) alimentada por un botón "Estoy en planta / Me retiro" en el home del operario; hasta que exista, se muestra "logins últimas 10 h" con etiqueta explícita.
  4. **Sectores activos**: sectores con batch en estado activo hoy ∪ sectores con presencia registrada.
  5. **Tickets pendientes de análisis**: el actual.
- Tarjetas Centro de Planificación / Reportes (→ ANALISIS + brief) / grilla de 14 sectores / Panel de Control (→ `ESTADO` + nueva barra horizontal % capacidad por producto desde `v_capacidad_acopio_producto` y `vw_stock_tanque_actual`).
- Lo que Fernando marcó ✗ (línea de portería, PCs, WeDo) se **mueve** a Portería y Stock, no se borra.
- Validar los 5 indicadores con Eugenia, Pablo y Fernando antes de la Fase 2 (él mismo lo pide).

### Fase 2 — Sector Reactores como piloto (wrappers)  · ~1 semana
- Home de sector: 5 KPIs de sector + tarjetas. Planificación → Centro de Planificación filtrado; Seguimiento → INICIAR renombrado "Producción Sector"; Desvíos → `performance_section`; Formulación → `formulas_section` filtrado; Stock → `stock_section` filtrado; Laboratorio → LAB con filtro de sector y columna producto·calidad; Reportes → ANALISIS.
- Sin lógica nueva: sólo filtros por `sector`. Es la fase que demuestra que la estructura funciona con datos reales.

### Fase 3 — Formulación por pasos  · ~1-2 semanas
- Tabla nueva `produccion.dic_formula_paso` (id_formula, orden, etapa, descripcion, codigo_insumo, kg_esperado, acidez_esp, temp_esp, tol_acidez, tol_temp, tol_kg_pct, offset_min, captura = HORAS|MEDICION|NINGUNA). Versionado con `dic_formula_version` (fecha_actualizacion, usuario) para que una OP en curso siga con la versión con la que arrancó.
- Seed automático desde `dic_proceso_etapa` + `dic_formula.insumos` (F101 = 13 pasos como en el Excel).
- Editor como componente propio (grilla, sin reruns); vista de sólo lectura con el layout exacto del director (FECHA ACT · #FORMULA · ITEM · DESCRIPCION · ACIDEZ · P · S).
- Planificación ya usa `_selector_formula`: pasa a listar por MP el desplegable pedido.

### Fase 4 — Planificación semanal → OP → Seguimiento por pasos → Desvíos  · ~2-3 semanas
- Vista `v_plan_semanal` sobre `fact_batch_proceso` PLANIFICADO + columnas nuevas `hora_plan_inicio`, `hora_plan_fin`, `responsable_plan`, `estado_plan` (NO_INICIADO/INICIADO/FINALIZADO), `semana_iso`. Grilla semanal (componente propio) con botón **Cargar** por fila y "Orden del día" = filas de hoy. Regla del director: se cierra el día anterior; cambios posteriores quedan auditados.
- **Cargar** abre el instructivo (componente propio): un paso por pantalla, valor esperado de la fórmula, captura hora inicio/fin (pasos de carga) o temp+acidez (revisiones) → `fact_etapa_evento` (ya existe) + nueva `fact_paso_medicion` (id_batch, orden, ts, valor_1, valor_2, kg, id_usuario). Cada confirmación es un commit; la máquina de estados actual sigue siendo la fuente del estado de la RX ("input del estado", como dijo él).
- **Desvíos** = `v_desvio_op`: real (mediciones + consumo de stock vía `v_movimientos_stock`) vs esperado (`dic_formula_paso`) por variable, en % y con estado Abierto/Aceptado por el supervisor. Alimenta `v_alertas_planta` (motor push ya existente) y el KPI "% cumplimiento de planificación" del sector.
- Parte 3 del seguimiento: # RX · a tiempo/fuera de crono/detenida · etapa · responsable, reusando `_desvio_cronograma` y `v_estado_planta`.

### Fase 5 — Stock, cuenta corriente y sectores sin datos  · ~2 semanas
- Cuenta corriente por producto (MP / Insumos / PT) con el layout del director sobre `v_movimientos_stock` + Excel; desplegable por familia. Cerrar con Fer la pregunta abierta "saldo − fórmula − ajuste por desvío": propuesta = el consumo se descuenta al **finalizar** la OP con lo formulado, y el desvío aceptado genera el ajuste (ya hay `fact_despacho_real` como precedente).
- Sólidos / DF Sólidos / NFU / Compost: carga mínima (stock en piso por producto + estado de descarga por ticket) para que los KPI 1 y 2 dejen de decir "sin dato".
- Replicar el home de sector a Bachas, Piletas, Exportación (misma fase 2, sólo filtros). Taller & Mant. → Repuestos; Portería → Ingresos + Disponibilidad de descarga (sin gráfico por hora) + "% ingresos evaluados"; Intendencia / Logística / RRHH → tarjeta atenuada hasta definir contenido.

### Fase 6 — Corte  · ~1 semana
- `nav_v2` default para todos; portada clásica queda como "Vista clásica" 2 semanas; después se borra el bloque de tiles de app.py.
- Documentar en `docs/GUIA.md` y actualizar SOP del operador.

---

## 6. Riesgos y decisiones abiertas

- **Datos que no existen** (personal, sólidos, descargas no líquidas): los KPI se muestran igual con etiqueta "sin dato" o "estimado"; no se inventa un número. Esto hay que decirlo explícitamente al director: el indicador aparece en la Fase 1, el dato real en la Fase 5.
- **14 sectores vs 4 de gestión**: `gestion_semanal` y el brief semanal siguen sobre los 4 sectores de gestión; los 14 son sectores de **navegación**. No mezclar (una unidad de gestión sigue siendo Sector + Producto).
- **Formulación con pasos por hora** presupone que el desgomado y las bachas también se describen así; hoy sólo ARE tiene targets por etapa. Empezar por ARE (F101) y dejar `captura=NINGUNA` para el resto.
- **Componentes propios**: la inversión inicial es mayor que un `data_editor`, pero es lo único que resuelve de raíz el rerun en las pantallas de carga (ya está demostrado en Despachos). El instructivo del operario es el primer candidato porque es la pantalla que se usa con guantes puestos.
- **Nombres**: usar los del director tal cual en la UI (Producción Sector, Seguimiento Producción, Orden Producción, Panel de Control) y mapear internamente a los códigos actuales; no renombrar tablas ni claves de `section`.
