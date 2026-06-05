# Contexto de negocio (entrena a Vanna como "documentation")

## Reglas generales
- Consultar SIEMPRE las vistas del esquema `reporting`. Nunca tablas de `public` ni de `produccion`.
- Zona horaria: America/Argentina/Buenos_Aires.
- "Ayer" = `fecha = current_date - 1`. "Hoy" = `current_date`. "Este mes" = `date_trunc('month', fecha) = date_trunc('month', current_date)`.
- Pesos en kilogramos. Porcentajes en columnas `prc_*` / `lab_prc_*`.

## reporting.v_camiones (portería / pesaje de camiones) — TIENE DATOS
- Una fila por transacción de pesaje. Datos desde 2025-08-13, ~15.000+ filas, actualizado al día.
- "Categoría" del camión = `producto` (detalle) o `producto_base` (agrupado, preferible para agrupar).
- "Procedencia" = `procedencia`. Destino = `destino`.
- `corriente` (EN MINÚSCULAS, valores exactos): `vegetal`, `animal`, `insumo`, `efluente_liquido`, `solido`, `sin_declarar`. Siempre comparar en minúsculas (o usar `lower(corriente)`).
  - **"insumos"** que entran (ácido, gasoil, glicerina, fuel, nafta, soda, metanol) → `corriente = 'insumo'`.
  - "efluentes (líquidos)" → `corriente = 'efluente_liquido'`. "sólidos / residuos / tierra / pellets" → `corriente = 'solido'`.
- `fecha_entrada` / `fecha_salida` son `date`.
- `peso_neto_kg`: SIEMPRE positivo (valor absoluto). Usar este para sumar/promediar pesos.
- `sentido`: ENTRADA o SALIDA (según el signo original del pesaje). La mayoría son ENTRADA.
  Para "kg ingresados" usar `WHERE sentido = 'ENTRADA'`.
- Trae lab cruzado: `lab_producto`, `lab_calidad`, `lab_rechazado`, `lab_prc_acidez`, `lab_prc_agua`.
- Procedencias frecuentes: ARROYO SECO, ALVEAR, CAPITAN BERMUDEZ, RAMALLO, PUERTO SAN MARTIN, ALBARELLOS, VILLA GOBERNADOR GALVEZ.

## reporting.v_laboratorio (análisis de laboratorio) — TIENE DATOS
- Una fila por muestra. Datos desde 2026-03-18.
- `producto`: EFLUENTE, AFE, AG, ARE, BORRA, SEBO, GLICERINA, FONDO_TK, EMULSION.
- `corriente`: VEGETAL o ANIMAL (puede ser NULL).
- `calidad`: A, B, C, D, E, G, S, SG, UNICA, LIQUIDO, etc.
- `estado`: ya normalizado a ACEPTADO, RECHAZADO o REMUESTREO.
- `empleado`: analista que cargó la muestra.
- Métricas: `prc_acidez`, `prc_agua`, `prc_sedimentos`, `densidad_g_ml`, `ppm_azufre`, `ppm_fosforo`,
  glicerina `gli_*`, efluente `eflu_*`, borra `borra_*`, sebo `sebo_indice_yodo`.
- Muchas métricas son NULL según el producto; AVG ya ignora NULLs.

## reporting.v_produccion (cargas de producción en reactores) — TIENE DATOS
- Una fila por corrida (reacción/bacha). `proceso` = PRODUCCION_ARE o DESGOMADO_ACUOSO.
- PRODUCCION_ARE: de AG-C o un sebo (+ glicerina + catalizador NaOH/POTASIO) se obtiene ARE; `producto_obtenido` = ARE-A / ARE-B / ARE-A-ANIMAL.
- DESGOMADO_ACUOSO: de AFE-SG se obtiene AFE-S (calidad UNICA). La merma es relevante acá.
- Dimensiones: `proceso`, `reactor` (REACTOR 1 / REACTOR 2), `corriente` (VEGETAL/ANIMAL), `producto_inicial`, `producto_obtenido`, `calidad`, `catalizador`, `etapa`, `cargado_por`.
- Cantidades en TN, kg y litros. **Usar `*_tn` por defecto** (mp_tn, producido_tn, merma_tn); también `mp_kg`/`mp_lts`, `producido_kg`/`producido_lts`.
- `rendimiento_pct` = producido/mp*100 (en ARE supera 100% porque se agrega glicerina; la merma aplica sobre todo a desgomado).
- Insumos/química: `fuel_oil` (combustible — en REACTORES siempre es fuel oil; ARE en kg, DESGOMADO en L), `naoh_kg`, `glicerina_fresca_lts`, `glicerina_recup_lts`, `agua_lts`.
- Calidad/proceso: `acidez_inicial`, `acidez_final`, `densidad_final`, `pct_ays`, `horas`.
- `etapa`: EN_TANQUE = acopio final (corrida cerrada). `fecha` es `date`.

## Diccionario (sinónimos para interpretar mejor las preguntas)
- "reacción", "corrida", "batch", "tanda", "carga", "producción" → filas de `reporting.v_produccion`.
- "ARE" → `proceso='PRODUCCION_ARE'`. "desgomado" / "AFE" → `proceso='DESGOMADO_ACUOSO'`.
- "producido / obtenido / salió / se hizo" → `producido_tn`. "procesado / materia prima / entró al reactor" → `mp_tn`.
- "rinde / rendimiento" → `rendimiento_pct`. "merma / pérdida" → `merma_tn` o `merma_pct`.
- "fuel / fuel oil / combustible" → `fuel_oil`. "soda / NaOH" → `naoh_kg`. "glicerina" → `glicerina_fresca_lts` / `glicerina_recup_lts`.
- "reactor 1/2" → `reactor`. "acidez final" → `acidez_final`. "calidad" → `calidad`.
- Ruteo de vistas: producción/cargas → `reporting.v_produccion`; camiones/pesaje/portería → `reporting.v_camiones`; análisis/calidad de laboratorio → `reporting.v_laboratorio`.

## Comparaciones
- Para comparar dos procedencias/productos: agrupar por la dimensión y filtrar con `IN (...)`.

## reporting.v_tanques (stock por tanque) — TIENE DATOS
- Una fila por tanque. `litros` = stock actual (medición real); `kg` y `tn` se derivan por densidad del producto.
- `fuente_medicion`: 'WeDo' (sensor radar automático, ~cada 20 min) o 'Manual' (carga a mano).
- `tipo_tanque`: Base plana, Cónico, Cilíndrico, Pileta, ISO container, Calefaccionado.
- `sector` = ubicación (Plataforma 1 (BPV), Plataforma 2 (BPN), Exportación, Reactores (Acopio), etc.).
- `producto` = producto principal asignado. `nivel_pct` = % de llenado. `capacidad_litros` = capacidad nominal.
- "Stock total" → SUM(`tn`) o SUM(`litros`). "Tanques con sensor / WeDo" → `fuente_medicion='WeDo'`.

## reporting.v_tanque_variacion (variación diaria de stock) — TIENE DATOS (desde que se conectó el sensor)
- Una fila por tanque y día (`fecha`). `variacion_intradia` = cierre−apertura del día; `variacion_vs_dia_anterior` = cierre de hoy − cierre de ayer.
- Litros positivos = ingresó producto; negativos = salió. `fuente`: WeDo, Manual o Mixto.

## Sinónimos de tanques
- "stock / cuánto hay / volumen en tanque" → `litros` (o `tn`). "lleno / llenado / nivel" → `nivel_pct`.
- "por sensor / automático / wedo / radar" → `fuente_medicion='WeDo'`. "a mano / manual" → `fuente_medicion='Manual'`.
- "base plana / cónico / pileta / iso / calefaccionado" → `tipo_tanque`. "capacidad" → `capacidad_litros`.

## Glosario CRÍTICO (evitar resultados vacíos)
- "worms" / "la planta" / "la fábrica" / "la empresa" / "la operación" se refieren a TODO el negocio. NO son un filtro: nunca uses esas palabras en un WHERE/ILIKE.
- "insumos" / "materia prima" / "MP" / "lo que entró/ingresó" = camiones de ENTRADA en `reporting.v_camiones` (filtro `sentido='ENTRADA'`). El material es la columna `producto`. Para "lista de insumos" usá `SELECT DISTINCT producto ... WHERE sentido='ENTRADA'`.
- "lo que salió / despachos / ventas" = `sentido='SALIDA'`.
- No inventes filtros de texto (ILIKE) salvo que la pregunta nombre explícitamente un valor de una columna (un producto, una procedencia, un cliente).

## reporting.v_movimientos_stock (libro de movimientos) — un ticket por movimiento
- Una fila por movimiento de stock (`ticket_mov` = MS-xxxxxxxx). `estado_mov`: PLANIFICADO (lo creó dirección), EJECUTADO (lo confirmó el operario, afecta stock), ANULADO.
- `rol`: MP, INSUMO, CATALIZADOR, PRODUCTO_FINAL, SUBPRODUCTO. `fuente`: TANQUE, PORTERIA, REACTOR.
- `kg_neto`/`litros_neto` ya traen el signo y SÓLO cuentan los EJECUTADO (+ ingreso, − egreso). `identificador_prod` liga al ID de producción.

## reporting.v_tanque_stock_estimado (mejor estimación de stock por tanque)
- `litros_estimado` = última medición física (`litros_medido`) + movimientos EJECUTADOS desde esa medición (`delta_litros_ejecutado`). Da stock cuasi-real aun en tanques medidos 1 vez al día.
- `fuente_medicion`: SENSOR (WeDo) o MANUAL. `antiguedad_min`: minutos desde la última medición física. `cadencia_sensor_min`: cada cuánto reporta el sensor.
- `confianza`: ALTA (sensor fresco), MEDIA (medición vieja pero con movimientos recientes), BAJA, SIN_DATO. `movs_pendientes`/`litros_pendientes`: movimientos PLANIFICADOS sin confirmar.

## Sinónimos de stock/movimientos
- "movimientos / trazabilidad / de dónde salió / a dónde fue" → `reporting.v_movimientos_stock`.
- "stock real / actual / estimado / cuánto hay ahora con lo que se movió" → `reporting.v_tanque_stock_estimado` (`litros_estimado`).
- "confianza / qué tan actualizado está el tanque" → `confianza`, `antiguedad_min`.

## reporting.v_reconciliacion_stock (control físico vs libro)
- Una fila por lectura física reconciliada. `litros_medido` (sensor/manual) vs `litros_esperado` (libro = lectura previa + movimientos). `discrepancia_litros` = medido − esperado.
- `severidad`: OK (dentro de umbral) o ALERTA (posible movimiento no registrado, fuga o drift). `ajuste_ticket` = ticket MS del AJUSTE posteado cuando hay ALERTA.
- "tanques con problemas / descuadres / fugas / discrepancias" → filtrar `severidad='ALERTA'`.
