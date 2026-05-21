# Contexto de negocio (entrena a Vanna como "documentation")

## Reglas generales
- Consultar SIEMPRE las vistas del esquema `reporting`. Nunca tablas de `public` ni de `produccion`.
- Zona horaria: America/Argentina/Buenos_Aires.
- "Ayer" = `fecha = current_date - 1`. "Hoy" = `current_date`. "Este mes" = `date_trunc('month', fecha) = date_trunc('month', current_date)`.
- Pesos en kilogramos. Porcentajes en columnas `prc_*` / `lab_prc_*`.

## reporting.v_camiones (portería / pesaje de camiones) — TIENE DATOS
- Una fila por transacción de pesaje. Datos desde 2025-08-13, ~15.000+ filas, actualizado al día.
- "Categoría" del camión = `producto` (detalle) o `producto_base` (agrupado, preferible para agrupar).
- "Procedencia" = `procedencia`. Destino = `destino`. `corriente` = VEGETAL/ANIMAL.
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

## Comparaciones
- Para comparar dos procedencias/productos: agrupar por la dimensión y filtrar con `IN (...)`.
