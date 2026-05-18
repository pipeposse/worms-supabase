-- =============================================================================
--  worms_supabase / 01_schema / schema.sql
--  PostgreSQL (Supabase). Idempotente: se puede correr varias veces sin daño.
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS produccion;
SET search_path TO produccion, public;

-- ===========================================================================
-- USUARIOS (login + auditoría no-falsificable)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS dim_usuario (
    id_usuario   BIGSERIAL PRIMARY KEY,
    nombre       TEXT NOT NULL UNIQUE,             -- ej. 'sosa', 'euge', 'felipe'
    nombre_full  TEXT NOT NULL,                    -- ej. 'José Sosa'
    pin_hash     TEXT NOT NULL,                    -- sha256 del PIN (4-6 dígitos)
    rol          TEXT NOT NULL DEFAULT 'OPERADOR', -- OPERADOR / SUPERVISOR / ADMIN
    sector       TEXT,                             -- sector default (FK abajo)
    activo       BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ultimo_login TIMESTAMPTZ
);

-- ===========================================================================
-- DICCIONARIOS (códigos cerrados)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS dic_estado_analisis (
    codigo TEXT PRIMARY KEY, descripcion TEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS dic_corriente (
    codigo TEXT PRIMARY KEY, descripcion TEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS dic_tipo_parametro (
    codigo TEXT PRIMARY KEY, descripcion TEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS dic_unidad (
    codigo TEXT PRIMARY KEY, descripcion TEXT NOT NULL,
    magnitud TEXT NOT NULL, es_estandar BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS dic_sector (
    codigo TEXT PRIMARY KEY, nombre_ui TEXT NOT NULL,
    color_hex TEXT, unidad_principal TEXT NOT NULL DEFAULT 'TN',
    activo BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS dic_calidad (
    codigo TEXT PRIMARY KEY, descripcion TEXT NOT NULL,
    orden SMALLINT NOT NULL DEFAULT 0, activo BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS dic_turno (
    codigo TEXT PRIMARY KEY, activo BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS dic_insumo (
    codigo      TEXT PRIMARY KEY,                 -- 'acido_kg','soda_kg','metanol_kg'
    descripcion TEXT NOT NULL,
    unidad      TEXT NOT NULL REFERENCES dic_unidad(codigo),
    activo      BOOLEAN NOT NULL DEFAULT TRUE
);

-- FK pendiente de dim_usuario.sector
ALTER TABLE dim_usuario
  DROP CONSTRAINT IF EXISTS dim_usuario_sector_fk;
ALTER TABLE dim_usuario
  ADD CONSTRAINT dim_usuario_sector_fk
  FOREIGN KEY (sector) REFERENCES dic_sector(codigo);

-- ===========================================================================
-- DIMENSIONES
-- ===========================================================================
CREATE TABLE IF NOT EXISTS dim_producto (
    id_producto      BIGSERIAL PRIMARY KEY,
    codigo_producto  TEXT NOT NULL UNIQUE,
    nombre_producto  TEXT NOT NULL,
    variante         TEXT,
    corriente        TEXT NOT NULL REFERENCES dic_corriente(codigo),
    tipo_producto    TEXT NOT NULL,
    usa_piletas      BOOLEAN NOT NULL DEFAULT FALSE,
    usa_bachas       BOOLEAN NOT NULL DEFAULT FALSE,
    usa_reactor      BOOLEAN NOT NULL DEFAULT FALSE,
    es_exportacion   BOOLEAN NOT NULL DEFAULT FALSE,
    usa_sales        BOOLEAN NOT NULL DEFAULT FALSE,
    requiere_ag      BOOLEAN NOT NULL DEFAULT FALSE,
    requiere_are     BOOLEAN NOT NULL DEFAULT FALSE,
    es_mezcla        BOOLEAN NOT NULL DEFAULT FALSE,
    activo           BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actualizado_en   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dim_parametro_lab (
    id_parametro       BIGSERIAL PRIMARY KEY,
    codigo_parametro   TEXT NOT NULL UNIQUE,
    nombre_display     TEXT NOT NULL,
    unidad             TEXT NOT NULL REFERENCES dic_unidad(codigo),
    rango_min          DOUBLE PRECISION,
    rango_max          DOUBLE PRECISION,
    aplica_a_corriente JSONB NOT NULL DEFAULT '[]'::jsonb,
    aplica_a_productos JSONB NOT NULL DEFAULT '[]'::jsonb,
    tipo_parametro     TEXT NOT NULL REFERENCES dic_tipo_parametro(codigo),
    es_critico         BOOLEAN NOT NULL DEFAULT FALSE,
    activo             BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS dim_tanque (
    id_tanque   BIGSERIAL PRIMARY KEY,
    codigo      TEXT NOT NULL UNIQUE,
    tipo        TEXT NOT NULL,                    -- TANQUE/PILETA/BACHA/REACTOR
    capacidad_l DOUBLE PRECISION,
    sector      TEXT REFERENCES dic_sector(codigo),
    activo      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS dim_camion (
    id_camion        BIGSERIAL PRIMARY KEY,
    patente_chasis   TEXT NOT NULL,
    patente_acoplado TEXT,
    transportista    TEXT,
    activo           BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_camion_patentes
  ON dim_camion(patente_chasis, COALESCE(patente_acoplado,''));

-- ===========================================================================
-- REFERENCIAS
-- ===========================================================================
CREATE TABLE IF NOT EXISTS ref_conversion_unidades (
    id_conversion  BIGSERIAL PRIMARY KEY,
    unidad_origen  TEXT NOT NULL REFERENCES dic_unidad(codigo),
    unidad_destino TEXT NOT NULL REFERENCES dic_unidad(codigo),
    factor         DOUBLE PRECISION NOT NULL,
    contexto       TEXT NOT NULL DEFAULT 'GLOBAL',
    vigente_desde  DATE NOT NULL DEFAULT CURRENT_DATE,
    vigente_hasta  DATE,
    notas          TEXT,
    UNIQUE (unidad_origen, unidad_destino, contexto, vigente_desde)
);

CREATE TABLE IF NOT EXISTS ref_meta_produccion (
    id_meta        BIGSERIAL PRIMARY KEY,
    anio           SMALLINT NOT NULL,
    mes            SMALLINT,
    sector         TEXT NOT NULL REFERENCES dic_sector(codigo),
    id_producto    BIGINT REFERENCES dim_producto(id_producto),
    meta_tn        DOUBLE PRECISION NOT NULL,
    tipo           TEXT NOT NULL DEFAULT 'mensual',
    es_provisoria  BOOLEAN NOT NULL DEFAULT FALSE,
    notas          TEXT,
    creado_en      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_meta_unica
  ON ref_meta_produccion(anio, mes, sector, COALESCE(id_producto::text,'-'), tipo);

-- ===========================================================================
-- HECHOS · todas las tablas tienen `creado_por` (FK lógica a dim_usuario.nombre)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS fact_analisis_lab (
    id_analisis           BIGSERIAL PRIMARY KEY,
    fecha                 DATE NOT NULL,
    ticket                TEXT,
    num_muestra           TEXT,
    id_producto           BIGINT NOT NULL REFERENCES dim_producto(id_producto),
    calidad_final_lab     TEXT REFERENCES dic_calidad(codigo),
    estado_analisis       TEXT NOT NULL DEFAULT 'PENDIENTE_REVISION'
                          REFERENCES dic_estado_analisis(codigo),
    id_usuario_carga      BIGINT NOT NULL REFERENCES dim_usuario(id_usuario),
    temperatura_celsius   DOUBLE PRECISION,
    conclusion            TEXT,
    id_tanque_1           BIGINT REFERENCES dim_tanque(id_tanque),
    id_tanque_2           BIGINT REFERENCES dim_tanque(id_tanque),
    id_camion             BIGINT REFERENCES dim_camion(id_camion),
    num_cisterna          TEXT,
    creado_en             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    id_usuario_modif      BIGINT REFERENCES dim_usuario(id_usuario),
    actualizado_en        TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_lab_unique
  ON fact_analisis_lab(fecha, COALESCE(ticket,''), COALESCE(num_muestra,''), id_producto);
CREATE INDEX IF NOT EXISTS ix_lab_fecha    ON fact_analisis_lab(fecha);
CREATE INDEX IF NOT EXISTS ix_lab_producto ON fact_analisis_lab(id_producto);
CREATE INDEX IF NOT EXISTS ix_lab_estado   ON fact_analisis_lab(estado_analisis);

CREATE TABLE IF NOT EXISTS fact_parametro_valor (
    id_valor          BIGSERIAL PRIMARY KEY,
    id_analisis       BIGINT NOT NULL REFERENCES fact_analisis_lab(id_analisis) ON DELETE CASCADE,
    id_parametro      BIGINT NOT NULL REFERENCES dim_parametro_lab(id_parametro),
    valor             DOUBLE PRECISION NOT NULL,
    unidad_original   TEXT NOT NULL REFERENCES dic_unidad(codigo),
    valor_convertido  DOUBLE PRECISION,
    unidad_convertida TEXT REFERENCES dic_unidad(codigo),
    fuera_de_rango    BOOLEAN NOT NULL DEFAULT FALSE,
    motivo_fuera_rango TEXT,
    UNIQUE (id_analisis, id_parametro)
);

-- (fact_efluente eliminado del proyecto · efluentes vienen de otra fuente)

CREATE TABLE IF NOT EXISTS fact_produccion_diaria (
    id_produccion             BIGSERIAL PRIMARY KEY,
    fecha                     DATE NOT NULL,
    id_producto               BIGINT NOT NULL REFERENCES dim_producto(id_producto),
    sector                    TEXT NOT NULL REFERENCES dic_sector(codigo),
    cantidad_procesada_kg     DOUBLE PRECISION NOT NULL DEFAULT 0,
    cantidad_procesada_tn     DOUBLE PRECISION GENERATED ALWAYS AS (cantidad_procesada_kg/1000.0) STORED,
    cantidad_obtenida_kg      DOUBLE PRECISION,
    cantidad_obtenida_tn      DOUBLE PRECISION GENERATED ALWAYS AS (cantidad_obtenida_kg/1000.0) STORED,
    calidad_dominante         TEXT REFERENCES dic_calidad(codigo),
    prc_aceptados             DOUBLE PRECISION,
    prc_rechazados            DOUBLE PRECISION,
    creado_en                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (fecha, id_producto, sector)
);

CREATE TABLE IF NOT EXISTS fact_batch_proceso (
    id_batch              BIGSERIAL PRIMARY KEY,
    fecha                 DATE NOT NULL,
    sector                TEXT NOT NULL REFERENCES dic_sector(codigo),
    turno                 TEXT REFERENCES dic_turno(codigo),
    id_usuario_carga      BIGINT NOT NULL REFERENCES dim_usuario(id_usuario),
    id_tanque             BIGINT REFERENCES dim_tanque(id_tanque),
    id_producto_inicial   BIGINT REFERENCES dim_producto(id_producto),
    kg_inicial            DOUBLE PRECISION,
    id_producto_obtenido  BIGINT NOT NULL REFERENCES dim_producto(id_producto),
    kg_obtenido           DOUBLE PRECISION NOT NULL CHECK (kg_obtenido >= 0),
    kg_merma              DOUBLE PRECISION GENERATED ALWAYS AS (
                              COALESCE(kg_inicial,0) - COALESCE(kg_obtenido,0)
                          ) STORED,
    horas_trabajadas      DOUBLE PRECISION CHECK (horas_trabajadas IS NULL OR horas_trabajadas >= 0),
    calidad_final         TEXT REFERENCES dic_calidad(codigo),
    insumos               JSONB NOT NULL DEFAULT '{}'::jsonb,
    observaciones         TEXT,
    creado_en             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_batch_fecha ON fact_batch_proceso(fecha);
CREATE INDEX IF NOT EXISTS ix_batch_sector ON fact_batch_proceso(sector);
CREATE INDEX IF NOT EXISTS ix_batch_pobt ON fact_batch_proceso(id_producto_obtenido);

-- ===========================================================================
-- AUDIT TRAIL · siempre lleva id_usuario (FK), no string libre
-- ===========================================================================
CREATE TABLE IF NOT EXISTS aud_eventos (
    id_evento     BIGSERIAL PRIMARY KEY,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    id_usuario    BIGINT NOT NULL REFERENCES dim_usuario(id_usuario),
    operacion     CHAR(1) NOT NULL,            -- I/U/D
    tabla         TEXT NOT NULL,
    pk_valor      TEXT,
    cambios       JSONB
);
CREATE INDEX IF NOT EXISTS ix_aud_tabla_ts  ON aud_eventos(tabla, ts);
CREATE INDEX IF NOT EXISTS ix_aud_usuario_ts ON aud_eventos(id_usuario, ts);

-- ===========================================================================
-- VISTAS para dashboard
-- ===========================================================================
DROP VIEW IF EXISTS v_kpi_produccion_diaria;
CREATE OR REPLACE VIEW v_kpi_produccion_diaria AS
SELECT f.fecha, f.sector, p.codigo_producto, p.corriente,
       f.cantidad_procesada_tn, f.cantidad_obtenida_tn,
       f.prc_aceptados, f.prc_rechazados, f.calidad_dominante
FROM fact_produccion_diaria f
JOIN dim_producto p ON p.id_producto = f.id_producto;

CREATE OR REPLACE VIEW v_alertas_lab AS
SELECT a.fecha, p.codigo_producto, par.codigo_parametro, par.nombre_display,
       v.valor, v.unidad_original, par.rango_min, par.rango_max,
       v.motivo_fuera_rango, u.nombre AS cargado_por, a.id_analisis
FROM fact_parametro_valor v
JOIN fact_analisis_lab a   ON a.id_analisis = v.id_analisis
JOIN dim_parametro_lab par ON par.id_parametro = v.id_parametro
JOIN dim_producto p        ON p.id_producto = a.id_producto
JOIN dim_usuario u         ON u.id_usuario = a.id_usuario_carga
WHERE v.fuera_de_rango = TRUE
  AND a.fecha >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY a.fecha DESC;

CREATE OR REPLACE VIEW v_audit_resumen AS
SELECT u.nombre AS usuario, u.nombre_full,
       e.tabla, e.operacion, COUNT(*) AS eventos,
       MIN(e.ts) AS primero, MAX(e.ts) AS ultimo
FROM aud_eventos e JOIN dim_usuario u ON u.id_usuario = e.id_usuario
GROUP BY 1,2,3,4 ORDER BY ultimo DESC;

-- ===========================================================================
-- ANULACIÓN (soft delete) · v2 · idempotente
-- ===========================================================================
ALTER TABLE fact_batch_proceso
  ADD COLUMN IF NOT EXISTS anulado          BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS motivo_anulacion TEXT,
  ADD COLUMN IF NOT EXISTS id_usuario_anula BIGINT REFERENCES dim_usuario(id_usuario),
  ADD COLUMN IF NOT EXISTS anulado_en       TIMESTAMPTZ;

-- Índices para listar rápido lo NO anulado
CREATE INDEX IF NOT EXISTS ix_batch_no_anulado ON fact_batch_proceso(fecha) WHERE NOT anulado;

-- ===========================================================================
-- TIPO OPERACIÓN + RANGOS · v3 · idempotente
-- ===========================================================================
-- Tipo operación: NORMAL = consume materia prima · RECUPERACION = solo saca producto
ALTER TABLE fact_batch_proceso
  ADD COLUMN IF NOT EXISTS tipo_operacion     TEXT NOT NULL DEFAULT 'NORMAL',
  ADD COLUMN IF NOT EXISTS fuera_de_rango     BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS motivo_fuera_rango TEXT;

ALTER TABLE fact_batch_proceso
  DROP CONSTRAINT IF EXISTS chk_batch_tipo_operacion;
ALTER TABLE fact_batch_proceso
  ADD CONSTRAINT chk_batch_tipo_operacion
  CHECK (tipo_operacion IN ('NORMAL','RECUPERACION'));

-- En RECUPERACION no debe haber producto inicial ni kg inicial
ALTER TABLE fact_batch_proceso
  DROP CONSTRAINT IF EXISTS chk_batch_recup_sin_mp;
ALTER TABLE fact_batch_proceso
  ADD CONSTRAINT chk_batch_recup_sin_mp
  CHECK (
    tipo_operacion <> 'RECUPERACION'
    OR (id_producto_inicial IS NULL AND (kg_inicial IS NULL OR kg_inicial = 0))
  );

-- En NORMAL la materia prima es obligatoria
ALTER TABLE fact_batch_proceso
  DROP CONSTRAINT IF EXISTS chk_batch_normal_con_mp;
ALTER TABLE fact_batch_proceso
  ADD CONSTRAINT chk_batch_normal_con_mp
  CHECK (
    tipo_operacion <> 'NORMAL'
    OR (id_producto_inicial IS NOT NULL AND kg_inicial IS NOT NULL AND kg_inicial > 0)
  );

-- Si fuera de rango, motivo obligatorio (≥5 chars)
ALTER TABLE fact_batch_proceso
  DROP CONSTRAINT IF EXISTS chk_batch_motivo_rango;
ALTER TABLE fact_batch_proceso
  ADD CONSTRAINT chk_batch_motivo_rango
  CHECK (NOT fuera_de_rango OR (motivo_fuera_rango IS NOT NULL AND length(trim(motivo_fuera_rango)) >= 5));

-- Rangos de kg típicos por producto (para validación UI)
ALTER TABLE dim_producto
  ADD COLUMN IF NOT EXISTS rango_kg_min DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS rango_kg_max DOUBLE PRECISION;
-- (CHECK de tipo_producto se aplica desde seed.sql tras la migración INTERMEDIO→MP)

-- Identificador de unidad (n° de bacha / n° de pileta / n° de ticket) que
-- los Excel viejos guardaban como texto libre. Opcional.
-- Drop view primero porque depende de b.* (expandido por Postgres como columnas fijas).
DROP VIEW IF EXISTS v_batch_activo;

-- Bienes de uso (equipos físicos: reactores y futuros)
CREATE TABLE IF NOT EXISTS dim_bien_uso (
    id_bien_uso BIGSERIAL PRIMARY KEY,
    codigo      TEXT NOT NULL UNIQUE,
    nombre_ui   TEXT NOT NULL,
    tipo        TEXT NOT NULL DEFAULT 'REACTOR',   -- REACTOR | BACHA | PILETA | OTRO
    activo      BOOLEAN NOT NULL DEFAULT TRUE
);

-- Parámetros específicos por reactor (capacidad y consumos formulados por TN)
ALTER TABLE dim_bien_uso
  ADD COLUMN IF NOT EXISTS capacidad_max_l            DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS consumo_fuel_kg_x_tn       DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS consumo_naoh_kg_x_tn       DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS consumo_potasio_kg_x_tn    DOUBLE PRECISION;

-- Constantes químicas globales (PMa, PMg, densidades, factor de exceso)
CREATE TABLE IF NOT EXISTS dic_constante_proceso (
    codigo       TEXT PRIMARY KEY,
    descripcion  TEXT NOT NULL,
    valor        DOUBLE PRECISION NOT NULL,
    unidad       TEXT
);

-- Tipos de proceso principales (PRODUCCION_ARE, DESGOMADO_ACUOSO)
CREATE TABLE IF NOT EXISTS dic_tipo_proceso (
    codigo      TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL,
    activo      BOOLEAN NOT NULL DEFAULT TRUE
);

-- Etapas dentro de un proceso (armado → reacción → ... → en tanque)
CREATE TABLE IF NOT EXISTS dic_etapa_proceso (
    codigo      TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL,
    orden       SMALLINT NOT NULL,
    activo      BOOLEAN NOT NULL DEFAULT TRUE
);

-- Catálogo de parámetros (acidez, temperatura, ppm fósforo, etc.)
CREATE TABLE IF NOT EXISTS dic_parametro_proceso (
    codigo      TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL,
    unidad      TEXT NOT NULL,
    aplica_a    JSONB NOT NULL DEFAULT '[]'::jsonb,   -- lista de tipo_proceso donde se usa
    activo      BOOLEAN NOT NULL DEFAULT TRUE
);

-- Densidad para conversión kg ↔ litros por producto (opcional)
ALTER TABLE dim_producto
  ADD COLUMN IF NOT EXISTS densidad_g_ml DOUBLE PRECISION;

-- Columnas extras en fact_batch_proceso
ALTER TABLE fact_batch_proceso
  ADD COLUMN IF NOT EXISTS identificador_unidad     TEXT,
  ADD COLUMN IF NOT EXISTS materias_primas_extras   JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS id_bien_uso              BIGINT REFERENCES dim_bien_uso(id_bien_uso),
  ADD COLUMN IF NOT EXISTS tipo_proceso             TEXT REFERENCES dic_tipo_proceso(codigo),
  ADD COLUMN IF NOT EXISTS etapa_actual             TEXT REFERENCES dic_etapa_proceso(codigo),
  ADD COLUMN IF NOT EXISTS inicio_ts                TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS fin_ts                   TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS tiempo_estimado_horas    DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS parametros_proceso       JSONB NOT NULL DEFAULT '{}'::jsonb,
  -- Inputs iniciales para fórmula de carga
  ADD COLUMN IF NOT EXISTS acidez_oleico_pct        DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS glicerol_pct             DOUBLE PRECISION,
  -- Estimados calculados al armar (snapshot del momento de carga)
  ADD COLUMN IF NOT EXISTS estimado_glicerina_kg    DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS estimado_naoh_kg         DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS estimado_potasio_kg      DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS estimado_fuel_kg         DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS estimado_are_kg          DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS q_ag_planeado_kg         DOUBLE PRECISION,
  -- Glicerina real (solo PRODUCCION_ARE)
  ADD COLUMN IF NOT EXISTS gli_fresca_lts           DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS gli_fresca_kg            DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS gli_recup_lts            DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS gli_recup_kg             DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS gli_pct_real             DOUBLE PRECISION,
  -- Agua (solo DESGOMADO_ACUOSO)
  ADD COLUMN IF NOT EXISTS agua_lts                 DOUBLE PRECISION;

-- En REACTORES el producto obtenido y la calidad solo se conocen en la etapa
-- EN_TANQUE; al crear la reacción todavía no hay producto definido. Se hace
-- nullable y se valida a nivel app cuando corresponde.
ALTER TABLE fact_batch_proceso ALTER COLUMN id_producto_obtenido DROP NOT NULL;
ALTER TABLE fact_batch_proceso ALTER COLUMN kg_obtenido          DROP NOT NULL;

-- Target vs real: el operador define qué producto/calidad APUNTA a producir
-- al armar la reacción. Al cerrar en EN_TANQUE se compara con el real.
ALTER TABLE fact_batch_proceso
  ADD COLUMN IF NOT EXISTS id_producto_buscado BIGINT REFERENCES dim_producto(id_producto),
  ADD COLUMN IF NOT EXISTS calidad_buscada     TEXT REFERENCES dic_calidad(codigo);
ALTER TABLE fact_batch_proceso DROP CONSTRAINT IF EXISTS fact_batch_proceso_kg_obtenido_check;
ALTER TABLE fact_batch_proceso
  ADD CONSTRAINT fact_batch_proceso_kg_obtenido_check
  CHECK (kg_obtenido IS NULL OR kg_obtenido >= 0);

-- Eventos de etapa: registra cada vez que se entra/sale de una etapa,
-- con horas hombre dedicadas. Una reacción tiene varios eventos.
CREATE TABLE IF NOT EXISTS fact_etapa_evento (
    id_evento_etapa  BIGSERIAL PRIMARY KEY,
    id_batch         BIGINT NOT NULL REFERENCES fact_batch_proceso(id_batch) ON DELETE CASCADE,
    etapa            TEXT NOT NULL REFERENCES dic_etapa_proceso(codigo),
    inicio_ts        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fin_ts           TIMESTAMPTZ,
    horas_hombre     DOUBLE PRECISION,
    observaciones    TEXT,
    id_usuario       BIGINT NOT NULL REFERENCES dim_usuario(id_usuario),
    creado_en        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_etapa_evento_batch ON fact_etapa_evento(id_batch, inicio_ts);

-- Evaluaciones internas (NO son las de laboratorio).
-- El operador toma muestra y anota acidez, ppm fósforo, temperatura, etc.
CREATE TABLE IF NOT EXISTS fact_evaluacion_interna (
    id_eval          BIGSERIAL PRIMARY KEY,
    id_batch         BIGINT NOT NULL REFERENCES fact_batch_proceso(id_batch) ON DELETE CASCADE,
    etapa            TEXT REFERENCES dic_etapa_proceso(codigo),
    ts               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mediciones       JSONB NOT NULL DEFAULT '{}'::jsonb,
    observaciones    TEXT,
    id_usuario       BIGINT NOT NULL REFERENCES dim_usuario(id_usuario),
    anulado          BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_eval_int_batch ON fact_evaluacion_interna(id_batch, ts);

-- Salidas de decantación: glicerina, fondo de tanque, etc. y a dónde se deriva.
CREATE TABLE IF NOT EXISTS fact_salida_decantacion (
    id_salida        BIGSERIAL PRIMARY KEY,
    id_batch         BIGINT NOT NULL REFERENCES fact_batch_proceso(id_batch) ON DELETE CASCADE,
    id_producto      BIGINT NOT NULL REFERENCES dim_producto(id_producto),
    kg               DOUBLE PRECISION,
    lts              DOUBLE PRECISION,
    glicerol_pct     DOUBLE PRECISION,   -- solo si producto es glicerina
    destino_tanque   TEXT,
    observaciones    TEXT,
    id_usuario       BIGINT NOT NULL REFERENCES dim_usuario(id_usuario),
    creado_en        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Gasto extraordinario: cuando se gastó MÁS de lo formulado (fuel, glicerina,
-- potasio, soda, etc.) con motivo. Insumo viene del catálogo dic_insumo.
CREATE TABLE IF NOT EXISTS fact_gasto_extra (
    id_gasto_extra   BIGSERIAL PRIMARY KEY,
    id_batch         BIGINT NOT NULL REFERENCES fact_batch_proceso(id_batch) ON DELETE CASCADE,
    codigo_insumo    TEXT NOT NULL REFERENCES dic_insumo(codigo),
    cantidad         DOUBLE PRECISION NOT NULL CHECK (cantidad > 0),
    motivo           TEXT NOT NULL CHECK (length(trim(motivo)) >= 5),
    id_usuario       BIGINT NOT NULL REFERENCES dim_usuario(id_usuario),
    creado_en        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_gasto_extra_batch ON fact_gasto_extra(id_batch);

-- Tabla de muestras intermedias: el operador toma muestras durante la reacción
-- (acidez por muestra, ppm fósforo, % goma, etc.). Muchas filas por id_batch.
CREATE TABLE IF NOT EXISTS fact_muestra_proceso (
    id_muestra        BIGSERIAL PRIMARY KEY,
    id_batch          BIGINT NOT NULL REFERENCES fact_batch_proceso(id_batch) ON DELETE CASCADE,
    ts                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    etapa             TEXT REFERENCES dic_etapa_proceso(codigo),
    mediciones        JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {codigo_param: valor, ...}
    observaciones     TEXT,
    id_usuario_carga  BIGINT NOT NULL REFERENCES dim_usuario(id_usuario),
    anulado           BOOLEAN NOT NULL DEFAULT FALSE,
    creado_en         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_muestra_batch ON fact_muestra_proceso(id_batch, ts);

-- fin_ts no puede ser anterior a inicio_ts
ALTER TABLE fact_batch_proceso DROP CONSTRAINT IF EXISTS chk_batch_horarios;
ALTER TABLE fact_batch_proceso
  ADD CONSTRAINT chk_batch_horarios
  CHECK (inicio_ts IS NULL OR fin_ts IS NULL OR fin_ts >= inicio_ts);

ALTER TABLE dim_producto
  DROP CONSTRAINT IF EXISTS chk_producto_rango_coherente;
ALTER TABLE dim_producto
  ADD CONSTRAINT chk_producto_rango_coherente
  CHECK (rango_kg_min IS NULL OR rango_kg_max IS NULL OR rango_kg_min <= rango_kg_max);

-- Vista: lo activo (NO anulado) consolidado para reporting / dashboards
CREATE OR REPLACE VIEW v_batch_activo AS
SELECT b.*, p.codigo_producto AS producto_obtenido, u.nombre AS cargado_por
FROM fact_batch_proceso b
JOIN dim_producto p ON p.id_producto = b.id_producto_obtenido
JOIN dim_usuario u  ON u.id_usuario  = b.id_usuario_carga
WHERE NOT b.anulado;

-- v_efluente_activo eliminada · efluente fuera del proyecto

-- Limpieza idempotente de objetos de efluente que pudieran existir en BDs viejas
DROP VIEW IF EXISTS v_efluente_activo CASCADE;
DROP TABLE IF EXISTS fact_efluente CASCADE;
ALTER TABLE fact_produccion_diaria
  DROP COLUMN IF EXISTS cant_efluentes_procesados,
  DROP COLUMN IF EXISTS ph_promedio_efluentes;
