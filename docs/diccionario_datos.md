# Diccionario de datos · `produccion` (PostgreSQL en Supabase)

## Convención general

- Schema: `produccion`
- Cada tabla operativa lleva `id_usuario_carga` (FK a `dim_usuario`) → audit no falsificable
- Catálogos cerrados: tablas `dic_*`
- Maestros: tablas `dim_*`
- Configuración versionada: tablas `ref_*`
- Hechos: tablas `fact_*`
- Auditoría: `aud_eventos`

## Catálogos cerrados (`dic_*`)

| Tabla | Códigos posibles |
|---|---|
| `dic_estado_analisis` | `ACEPTADO`, `RECHAZADO`, `FUERA_ESPECIFICACION`, `PENDIENTE_REVISION` |
| `dic_corriente` | `VEGETAL`, `ANIMAL`, `INSUMO`, `NFU`, `OTRO` |
| `dic_tipo_parametro` | `COMPOSICION`, `FISICOQUIMICO`, `QUIMICO`, `EFLUENTE`, `VISCOSIDAD`, `TEXTURA` |
| `dic_unidad` | `KG`, `TN`, `G`, `L`, `ML`, `PCT`, `PPM`, `MS_CM`, `MG_O2_L`, `G_ML`, `GI_GMU`, `C`, `H`, `ADIM` |
| `dic_sector` | `ARE`, `DESGOMADO`, `BACHAS`, `RECUPERACION`, `EFLUENTES`, `LABORATORIO`, `EXPO` |
| `dic_calidad` | `A`, `B`, `C`, `SG`, `RECH` |
| `dic_turno` | `mañana`, `tarde`, `noche` |
| `dic_insumo` | `acido_kg`, `soda_kg`, `metanol_kg`, `catalizador_kg`, `floculante_kg`, `kg_glicerina`, `fuel_l` |

## Usuarios y auditoría

### `dim_usuario`
- `id_usuario` (PK)
- `nombre` UNIQUE — login (ej. `sosa`)
- `nombre_full` — para mostrar
- `pin_hash` — SHA-256
- `rol` — `OPERADOR` / `SUPERVISOR` / `ADMIN`
- `sector` (FK a `dic_sector`) — default
- `activo` (BOOL)
- `creado_en`, `ultimo_login`

### `aud_eventos`
- `id_evento`, `ts`, `id_usuario` (FK), `operacion` (`I/U/D`), `tabla`, `pk_valor`, `cambios` (JSONB)
- Vista `v_audit_resumen`: agregado por usuario / tabla / operación

## Maestros (`dim_*`)

### `dim_producto`
- `codigo_producto` UNIQUE (ej. `AFE-S`, `ARE(V)-B`)
- `corriente` FK
- Flags: `usa_piletas`, `usa_bachas`, `usa_reactor`, `es_exportacion`, `usa_sales`, `requiere_ag`, `requiere_are`, `es_mezcla`

### `dim_parametro_lab`
- `codigo_parametro` UNIQUE (ej. `prc_acidez`)
- `unidad` FK estándar
- `rango_min`, `rango_max`
- `aplica_a_corriente` JSONB (array de corrientes)
- `aplica_a_productos` JSONB (array de codigos)
- `tipo_parametro` FK
- `es_critico` BOOL

### `dim_tanque`, `dim_camion`
- Maestros físicos. Códigos únicos.

## Referencias (`ref_*`)

### `ref_conversion_unidades`
- `unidad_origen → unidad_destino`, `factor`, `contexto` (`GLOBAL` o codigo_producto)
- Versionado por `vigente_desde`/`vigente_hasta`

### `ref_meta_produccion`
- `(anio, mes, sector, id_producto, tipo)` UK con NULL = aplica al sector entero
- `meta_tn` (siempre TN)

## Hechos (`fact_*`)

### `fact_analisis_lab`
Cabecera del análisis. UK = `(fecha, ticket, num_muestra, id_producto)`.
Lleva `id_usuario_carga`.

### `fact_parametro_valor`
Long format. Una fila por (análisis, parámetro). UK = `(id_analisis, id_parametro)`.
- `valor`, `unidad_original`
- `valor_convertido`, `unidad_convertida` (a unidad estándar)
- `fuera_de_rango` BOOL
- `motivo_fuera_rango` TEXT (obligatorio si fuera_de_rango)

### `fact_efluente`
Tabla segregada para efluentes. Lleva `id_usuario_carga`.

### `fact_batch_proceso`
Una fila por batch (reactor / desgomado / bachas / piletas). Insumos en `JSONB`.
- `kg_merma` GENERATED `kg_inicial - kg_obtenido`
- Lleva `id_usuario_carga`.

### `fact_produccion_diaria`
Rollup diario.
- `cantidad_procesada_tn` GENERATED `cantidad_procesada_kg / 1000`
- UK = `(fecha, id_producto, sector)`

## Vistas

| Vista | Devuelve |
|---|---|
| `v_kpi_produccion_diaria` | producción TN x día x sector x producto (con corriente) |
| `v_alertas_lab` | parámetros fuera de rango últimos 30 días + quién cargó |
| `v_audit_resumen` | conteo de eventos por usuario / tabla / operación |
