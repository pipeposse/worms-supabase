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

-- Multi-sector: lista de sectores accesibles por usuario (JSONB).
-- Si está vacío, se asume que el usuario puede ver todos los sectores activos.
ALTER TABLE dim_usuario
  ADD COLUMN IF NOT EXISTS sectores JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Migración suave: si tiene `sector` y no tiene `sectores`, copiar el default
UPDATE dim_usuario
   SET sectores = jsonb_build_array(sector)
 WHERE sector IS NOT NULL
   AND (sectores IS NULL OR sectores = '[]'::jsonb);

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

-- Config de corrientes: cuáles se deben evaluar en laboratorio (editable desde Supabase).
CREATE TABLE IF NOT EXISTS dic_corriente_config (
    corriente  TEXT PRIMARY KEY,
    evaluable  BOOLEAN NOT NULL DEFAULT FALSE
);

-- Tabla de mapeo de productos según se declaran en portería / origen.
-- producto = nombre crudo (puede traer typos / variantes); producto_base = código normalizado;
-- corriente = clasificación (vegetal/animal/insumo/solido/efluente_liquido/sin_declarar).
CREATE TABLE IF NOT EXISTS porteria_limpieza (
    producto      TEXT PRIMARY KEY,
    producto_base TEXT NOT NULL,
    corriente     TEXT NOT NULL
);

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

-- Etapas POR proceso: cada proceso (PRODUCCION_ARE, DESGOMADO_ACUOSO,
-- RECUPERACION, BACHAS, ...) tiene su propia secuencia de etapas, orden y
-- duración estimada. proceso_key = tipo_proceso (reactores) o sector (resto).
CREATE TABLE IF NOT EXISTS dic_proceso_etapa (
    proceso_key          TEXT NOT NULL,
    etapa                TEXT NOT NULL REFERENCES dic_etapa_proceso(codigo),
    orden                SMALLINT NOT NULL,
    duracion_target_min  INTEGER,
    duracion_min_min     INTEGER,
    duracion_max_min     INTEGER,
    PRIMARY KEY (proceso_key, etapa)
);

-- Duración estimada por (sector, proceso, etapa)
-- Permite saber si una corrida tardó más o menos de lo esperado.
CREATE TABLE IF NOT EXISTS dic_etapa_duracion (
    sector              TEXT NOT NULL REFERENCES dic_sector(codigo),
    tipo_proceso        TEXT NOT NULL REFERENCES dic_tipo_proceso(codigo),
    etapa               TEXT NOT NULL REFERENCES dic_etapa_proceso(codigo),
    duracion_target_min INTEGER NOT NULL CHECK (duracion_target_min > 0),
    duracion_min_min    INTEGER NOT NULL CHECK (duracion_min_min  > 0),
    duracion_max_min    INTEGER NOT NULL CHECK (duracion_max_min  > duracion_min_min),
    PRIMARY KEY (sector, tipo_proceso, etapa)
);

-- Reglas por sector: qué modos de operación admite.
CREATE TABLE IF NOT EXISTS dic_sector_config (
    sector               TEXT PRIMARY KEY REFERENCES dic_sector(codigo),
    permite_normal       BOOLEAN NOT NULL DEFAULT TRUE,
    permite_recuperacion BOOLEAN NOT NULL DEFAULT FALSE
);

-- Productos permitidos por (sector, proceso, modo, rol) usando patrón LIKE.
-- rol = 'MP' (entrada) | 'FINAL' (salida).
CREATE TABLE IF NOT EXISTS dic_proceso_producto (
    id              BIGSERIAL PRIMARY KEY,
    sector          TEXT NOT NULL REFERENCES dic_sector(codigo),
    tipo_proceso    TEXT,            -- NULL si el sector no usa proceso (ej. BACHAS)
    tipo_operacion  TEXT,            -- 'NORMAL' | 'RECUPERACION' | NULL (cualquiera)
    rol             TEXT NOT NULL CHECK (rol IN ('MP','FINAL')),
    patron          TEXT NOT NULL    -- ej. 'ARE-%', 'AG-%', 'SEBO%', 'AFE-S'
);
CREATE INDEX IF NOT EXISTS ix_proc_prod ON dic_proceso_producto(sector, tipo_proceso, rol);

-- Consumos teóricos de insumos por TN según (proceso, insumo).
-- Para PRODUCCION_ARE vienen del Excel; DESGOMADO_ACUOSO es bajo (~8.7 L fuel/TN).
-- base_referencia = AG_INPUT (TN de materia prima) o PRODUCTO_OUTPUT (TN de producto generado)
CREATE TABLE IF NOT EXISTS dic_consumo_proceso (
    tipo_proceso     TEXT NOT NULL REFERENCES dic_tipo_proceso(codigo),
    codigo_insumo    TEXT NOT NULL REFERENCES dic_insumo(codigo),
    consumo_por_tn   DOUBLE PRECISION NOT NULL CHECK (consumo_por_tn > 0),
    unidad_consumo   TEXT NOT NULL DEFAULT 'kg',
    base_referencia  TEXT NOT NULL DEFAULT 'AG_INPUT',
    nota             TEXT,
    PRIMARY KEY (tipo_proceso, codigo_insumo)
);

-- Consumos por SECTOR (para sectores sin proceso, ej. BACHAS).
CREATE TABLE IF NOT EXISTS dic_consumo_sector (
    sector           TEXT NOT NULL REFERENCES dic_sector(codigo),
    codigo_insumo    TEXT NOT NULL REFERENCES dic_insumo(codigo),
    consumo_por_tn   DOUBLE PRECISION NOT NULL CHECK (consumo_por_tn > 0),
    unidad_consumo   TEXT NOT NULL DEFAULT 'kg',
    nota             TEXT,
    PRIMARY KEY (sector, codigo_insumo)
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
  ADD COLUMN IF NOT EXISTS catalizador_tipo         TEXT,
  -- Estimados calculados al armar (snapshot del momento de carga)
  ADD COLUMN IF NOT EXISTS estimado_glicerina_kg    DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS estimado_naoh_kg         DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS estimado_potasio_kg      DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS estimado_fuel_kg         DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS estimado_are_kg          DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS q_ag_planeado_kg         DOUBLE PRECISION,
  -- Glicerina real (solo PRODUCCION_ARE) · cargar SIEMPRE en kg; L se derivan por densidad
  ADD COLUMN IF NOT EXISTS gli_fresca_lts           DOUBLE PRECISION,   -- legacy, calculado por la app
  ADD COLUMN IF NOT EXISTS gli_fresca_kg            DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS gli_fresca_pct           DOUBLE PRECISION,   -- % glicerol de la fresca
  ADD COLUMN IF NOT EXISTS gli_recup_lts            DOUBLE PRECISION,   -- legacy, calculado por la app
  ADD COLUMN IF NOT EXISTS gli_recup_kg             DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS gli_pct_real             DOUBLE PRECISION,   -- % glicerol de la recuperada
  ADD COLUMN IF NOT EXISTS gli_pura_total_kg        DOUBLE PRECISION,   -- pura = fresca*%+recup*%
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
-- Duración real de la etapa cargada manualmente en minutos (lo que dijo el operador)
ALTER TABLE fact_etapa_evento
  ADD COLUMN IF NOT EXISTS duracion_real_min INTEGER;
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

-- catalizador válido
ALTER TABLE fact_batch_proceso DROP CONSTRAINT IF EXISTS chk_batch_catalizador;
ALTER TABLE fact_batch_proceso
  ADD CONSTRAINT chk_batch_catalizador
  CHECK (catalizador_tipo IS NULL OR catalizador_tipo IN ('NAOH','POTASIO'));

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

-- ===========================================================================
-- LITROS (REACTORES/BACHAS van en litros, kg derivado) + ticket porteria +
-- insumos evaluables + tipo de salida en decantacion + catalizador/decantacion
-- ===========================================================================
ALTER TABLE fact_batch_proceso ADD COLUMN IF NOT EXISTS litros_inicial   NUMERIC;
ALTER TABLE fact_batch_proceso ADD COLUMN IF NOT EXISTS litros_obtenido  NUMERIC;
ALTER TABLE fact_batch_proceso ADD COLUMN IF NOT EXISTS ticket_porteria  TEXT;  -- desgomado: peso de exportacion->proceso
ALTER TABLE fact_batch_proceso ADD COLUMN IF NOT EXISTS tanque_destino   TEXT;  -- a qué tanque fue el producto final
ALTER TABLE dic_insumo              ADD COLUMN IF NOT EXISTS evaluable    BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE fact_salida_decantacion ADD COLUMN IF NOT EXISTS tipo_salida  TEXT;  -- GLICERINA_RECUP / FONDO_TANQUE / AGUA_PROCESO

-- Catalizadores: NAOH genera glicerina recuperada; POTASIO (KOH) no, y reduce uso de glicerina
CREATE TABLE IF NOT EXISTS dic_catalizador (
    codigo                 TEXT PRIMARY KEY,
    descripcion            TEXT NOT NULL,
    genera_glicerina_recup BOOLEAN NOT NULL DEFAULT TRUE,
    reduce_glicerina       BOOLEAN NOT NULL DEFAULT FALSE,
    nota                   TEXT
);

-- Decantaciones permitidas por proceso (glicerina recup solo ARE, fondo solo desgomado, agua bachas)
CREATE TABLE IF NOT EXISTS dic_decantacion_proceso (
    proceso_key     TEXT NOT NULL,
    tipo_salida     TEXT NOT NULL,
    label           TEXT NOT NULL,
    codigo_producto TEXT,
    PRIMARY KEY (proceso_key, tipo_salida)
);

-- Evaluaciones de insumos (acido sulfurico, soda caustica, gasoil, etc.)
CREATE TABLE IF NOT EXISTS fact_evaluacion_insumo (
    id_eval_insumo BIGSERIAL PRIMARY KEY,
    codigo_insumo  TEXT NOT NULL REFERENCES dic_insumo(codigo),
    fecha          DATE NOT NULL DEFAULT CURRENT_DATE,
    mediciones     JSONB NOT NULL DEFAULT '{}'::jsonb,
    observaciones  TEXT,
    id_usuario     BIGINT REFERENCES dim_usuario(id_usuario),
    creado_en      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    anulado        BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_eval_insumo ON fact_evaluacion_insumo(codigo_insumo, fecha);

-- ===========================================================================
--  Import procesos ARE + carga futura íntegra (corriente, params finales, NaOH L/kg)
-- ===========================================================================
ALTER TABLE fact_batch_proceso
  ADD COLUMN IF NOT EXISTS corriente        TEXT,                 -- VEGETAL / ANIMAL (al inicio del armado)
  ADD COLUMN IF NOT EXISTS acidez_final_pct DOUBLE PRECISION,     -- lo define laboratorio; queda en el batch
  ADD COLUMN IF NOT EXISTS densidad_final   DOUBLE PRECISION,     -- gr/cm3 final
  ADD COLUMN IF NOT EXISTS porc_ays         DOUBLE PRECISION,     -- % Agua y Sedimentos
  ADD COLUMN IF NOT EXISTS naoh_lts         DOUBLE PRECISION,     -- NaOH en litros
  ADD COLUMN IF NOT EXISTS naoh_kg          DOUBLE PRECISION;     -- NaOH en kg (= lts * densidad soda)

ALTER TABLE dic_insumo
  ADD COLUMN IF NOT EXISTS densidad_g_ml DOUBLE PRECISION;        -- kg/L para convertir litros<->kg

-- Preferencias de UI por usuario (columnas visibles por tabla, etc.)
ALTER TABLE dim_usuario
  ADD COLUMN IF NOT EXISTS prefs JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Vista de reacciones con cada líquido en litros Y kg (conversión por densidad).
CREATE OR REPLACE VIEW v_reacciones_lkg AS
SELECT
  b.id_batch, b.identificador_unidad AS ticket, b.fecha, b.sector, b.tipo_proceso, b.corriente,
  bu.nombre_ui AS reactor,
  pi.codigo_producto AS producto_inicial, po.codigo_producto AS producto_obtenido, b.calidad_final,
  COALESCE(b.kg_inicial,     b.litros_inicial * pi.densidad_g_ml)        AS ag_kg,
  COALESCE(b.litros_inicial, b.kg_inicial / NULLIF(pi.densidad_g_ml,0))  AS ag_lts,
  COALESCE(b.kg_obtenido,    b.litros_obtenido * po.densidad_g_ml)        AS are_kg,
  COALESCE(b.litros_obtenido, b.kg_obtenido / NULLIF(po.densidad_g_ml,0)) AS are_lts,
  COALESCE(b.gli_fresca_kg,  b.gli_fresca_lts * 1.25) AS gli_fresca_kg,
  COALESCE(b.gli_fresca_lts, b.gli_fresca_kg / 1.25)  AS gli_fresca_lts,
  COALESCE(b.gli_recup_kg,   b.gli_recup_lts * 1.25)  AS gli_recup_kg,
  COALESCE(b.gli_recup_lts,  b.gli_recup_kg / 1.25)   AS gli_recup_lts,
  b.naoh_kg, b.naoh_lts,
  NULLIF((b.insumos->>'fuel_l'),'')::numeric                  AS fuel_lts,
  round((NULLIF((b.insumos->>'fuel_l'),'')::numeric)*0.95, 2) AS fuel_kg,
  b.acidez_oleico_pct AS acidez_inicial, b.acidez_final_pct, b.densidad_final, b.porc_ays,
  b.tiempo_estimado_horas AS horas, b.inicio_ts, b.fin_ts, b.etapa_actual,
  round((COALESCE(b.kg_obtenido,0)/1000.0)::numeric,2) AS tn_are,
  round((COALESCE(b.kg_inicial,0)/1000.0)::numeric,2)  AS tn_ag
FROM fact_batch_proceso b
LEFT JOIN dim_producto pi ON pi.id_producto = b.id_producto_inicial
LEFT JOIN dim_producto po ON po.id_producto = b.id_producto_obtenido
LEFT JOIN dim_bien_uso  bu ON bu.id_bien_uso = b.id_bien_uso
WHERE NOT b.anulado AND b.sector IN ('REACTORES','BACHAS');

-- ===========================================================================
--  Limpieza de tablas/vistas/columnas OBSOLETAS o DUPLICADAS (idempotente).
--  Se ejecuta al final para dejar el esquema en el estado vigente aunque los
--  CREATE de arriba sigan presentes por histórico. NO toca transacciones / procesos_lab.
-- ===========================================================================
DROP VIEW  IF EXISTS v_batch_activo          CASCADE;
DROP VIEW  IF EXISTS v_kpi_produccion_diaria CASCADE;
DROP VIEW  IF EXISTS v_alertas_lab           CASCADE;
ALTER TABLE fact_batch_proceso DROP COLUMN IF EXISTS id_reactor;
ALTER TABLE fact_batch_proceso DROP COLUMN IF EXISTS id_tanque;
-- modelo viejo de laboratorio normalizado (hoy: procesos_lab raw + fact_evaluacion_interna)
DROP TABLE IF EXISTS fact_parametro_valor   CASCADE;
DROP TABLE IF EXISTS fact_analisis_lab      CASCADE;
DROP TABLE IF EXISTS dim_parametro_lab      CASCADE;
DROP TABLE IF EXISTS dic_tipo_parametro     CASCADE;
DROP TABLE IF EXISTS dic_estado_analisis    CASCADE;
-- portería vieja (hoy: transacciones raw)
DROP TABLE IF EXISTS dim_camion             CASCADE;
-- agregados/metas viejos nunca usados
DROP TABLE IF EXISTS fact_produccion_diaria CASCADE;
DROP TABLE IF EXISTS ref_meta_produccion    CASCADE;
-- muestras viejas (hoy: fact_evaluacion_interna)
DROP TABLE IF EXISTS fact_muestra_proceso   CASCADE;
-- dimensiones duplicadas
DROP TABLE IF EXISTS dim_reactor            CASCADE;  -- duplica dim_bien_uso

-- ===========================================================================
--  Tanques (stock por material). dim_tanque + M:N dim_tanque_producto.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS dim_tanque (
  id_tanque              SERIAL PRIMARY KEY,
  codigo                 TEXT UNIQUE NOT NULL,
  nombre                 TEXT NOT NULL,
  sector                 TEXT NOT NULL,
  posee_radar            BOOLEAN NOT NULL DEFAULT FALSE,
  variacion_nivel        TEXT,                       -- ALTA / MEDIA / BAJA
  metodo_medicion        TEXT,                       -- Manual / Inaccesible / NULL
  capacidad_litros       NUMERIC,
  id_producto_principal  BIGINT REFERENCES dim_producto(id_producto),
  producto_principal_txt TEXT,
  otros_productos_txt    TEXT,
  activo                 BOOLEAN NOT NULL DEFAULT TRUE,
  creado_en              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS dim_tanque_producto (
  id_tanque    BIGINT NOT NULL REFERENCES dim_tanque(id_tanque) ON DELETE CASCADE,
  id_producto  BIGINT NOT NULL REFERENCES dim_producto(id_producto),
  es_principal BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (id_tanque, id_producto)
);

-- Mediciones de stock por tanque (manual, con timestamp + usuario). Último = stock vigente.
CREATE TABLE IF NOT EXISTS fact_stock_tanque (
  id_stock      SERIAL PRIMARY KEY,
  id_tanque     BIGINT NOT NULL REFERENCES dim_tanque(id_tanque),
  id_producto   BIGINT REFERENCES dim_producto(id_producto),
  medido_en     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  litros        NUMERIC,
  kg            NUMERIC,
  nivel_pct     NUMERIC,
  id_usuario    BIGINT REFERENCES dim_usuario(id_usuario),
  observaciones TEXT,
  creado_en     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_stock_tanque_tk ON fact_stock_tanque (id_tanque, medido_en DESC);

CREATE OR REPLACE VIEW v_stock_tanque_ultimo AS
SELECT DISTINCT ON (t.id_tanque)
  t.id_tanque, t.codigo, t.nombre, t.sector, t.capacidad_litros,
  pp.codigo_producto AS producto_principal,
  s.id_stock, s.medido_en, s.litros, s.kg, s.nivel_pct,
  p.codigo_producto AS producto_medido, s.observaciones, u.nombre AS cargado_por
FROM dim_tanque t
LEFT JOIN dim_producto pp ON pp.id_producto = t.id_producto_principal
LEFT JOIN fact_stock_tanque s ON s.id_tanque = t.id_tanque
LEFT JOIN dim_producto p ON p.id_producto = s.id_producto
LEFT JOIN dim_usuario u ON u.id_usuario = s.id_usuario
WHERE t.activo
ORDER BY t.id_tanque, s.medido_en DESC NULLS LAST;

-- =============================================================================
--  2026-05-31 · Fuente insumo/MP (ticket vs tanque), ticket lab automatico,
--  cronograma de evaluacion, parametros por proceso/tanque, maquina de estados,
--  motor de reglas, decantacion y cronograma diario. Todo idempotente.
--  (Refleja las migraciones aplicadas a worms-prod el 2026-05-31.)
-- =============================================================================
SET search_path TO produccion, public;

-- --- Equivalencia insumo (consumible) -> producto almacenable en tanque -------
ALTER TABLE produccion.dic_insumo
  ADD COLUMN IF NOT EXISTS id_producto_equiv BIGINT REFERENCES produccion.dim_producto(id_producto);
COMMENT ON COLUMN produccion.dic_insumo.id_producto_equiv IS
  'Producto almacenable equivalente: permite ubicar tanques que contienen este insumo para la carga por fuente=TANQUE.';

-- --- Libro mayor de movimientos de tanque + stock actual ----------------------
CREATE TABLE IF NOT EXISTS produccion.fact_movimiento_tanque (
  id_movimiento BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_tanque     BIGINT NOT NULL REFERENCES produccion.dim_tanque(id_tanque),
  id_producto   BIGINT REFERENCES produccion.dim_producto(id_producto),
  tipo          TEXT NOT NULL CHECK (tipo IN ('IN','OUT','AJUSTE')),
  litros        NUMERIC,
  kg            NUMERIC,
  ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  id_batch      BIGINT REFERENCES produccion.fact_batch_proceso(id_batch) ON DELETE SET NULL,
  id_usuario    BIGINT,
  origen        TEXT NOT NULL DEFAULT 'PROCESO',
  observaciones TEXT,
  creado_en     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_mov_tanque_tanque_ts ON produccion.fact_movimiento_tanque(id_tanque, ts);
CREATE INDEX IF NOT EXISTS ix_mov_tanque_batch     ON produccion.fact_movimiento_tanque(id_batch);

CREATE OR REPLACE VIEW produccion.vw_stock_snapshot_ultimo AS
SELECT DISTINCT ON (id_tanque)
       id_tanque, id_producto, medido_en, litros, kg, nivel_pct
FROM produccion.fact_stock_tanque
ORDER BY id_tanque, medido_en DESC;

CREATE OR REPLACE VIEW produccion.vw_stock_tanque_actual AS
SELECT t.id_tanque, t.codigo, t.nombre, t.sector, t.capacidad_litros, t.id_producto_principal,
       s.medido_en AS ultima_medicion,
       COALESCE(s.litros,0) + COALESCE(m.delta_litros,0) AS litros_actual,
       COALESCE(s.kg,0)     + COALESCE(m.delta_kg,0)     AS kg_actual,
       CASE WHEN t.capacidad_litros IS NOT NULL AND t.capacidad_litros>0
            THEN ROUND((COALESCE(s.litros,0)+COALESCE(m.delta_litros,0))/t.capacidad_litros*100,1) END AS nivel_pct_actual
FROM produccion.dim_tanque t
LEFT JOIN produccion.vw_stock_snapshot_ultimo s ON s.id_tanque = t.id_tanque
LEFT JOIN LATERAL (
   SELECT SUM(CASE mv.tipo WHEN 'OUT' THEN -1 ELSE 1 END * COALESCE(mv.litros,0)) AS delta_litros,
          SUM(CASE mv.tipo WHEN 'OUT' THEN -1 ELSE 1 END * COALESCE(mv.kg,0))     AS delta_kg
   FROM produccion.fact_movimiento_tanque mv
   WHERE mv.id_tanque = t.id_tanque AND (s.medido_en IS NULL OR mv.ts > s.medido_en)
) m ON TRUE
WHERE t.activo;

-- --- Cola de laboratorio + linea de insumo/MP con fuente ----------------------
CREATE SEQUENCE IF NOT EXISTS produccion.seq_ticket_lab;

CREATE TABLE IF NOT EXISTS produccion.fact_ticket_lab (
  id_ticket       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ticket_lab      TEXT NOT NULL UNIQUE,
  id_batch        BIGINT REFERENCES produccion.fact_batch_proceso(id_batch) ON DELETE CASCADE,
  id_batch_insumo BIGINT,
  rol             TEXT NOT NULL CHECK (rol IN ('INSUMO','MP','FINAL','SUBPRODUCTO')),
  codigo_insumo   TEXT REFERENCES produccion.dic_insumo(codigo),
  id_producto     BIGINT REFERENCES produccion.dim_producto(id_producto),
  fuente          TEXT NOT NULL CHECK (fuente IN ('TICKET','TANQUE','DECANTACION')),
  ticket_porteria TEXT,
  id_tanque       BIGINT REFERENCES produccion.dim_tanque(id_tanque),
  cantidad        NUMERIC,
  unidad          TEXT,
  estado          TEXT NOT NULL DEFAULT 'PENDIENTE' CHECK (estado IN ('PENDIENTE','EVALUADO','ANULADO')),
  mediciones      JSONB NOT NULL DEFAULT '{}'::jsonb,
  evaluado_en     TIMESTAMPTZ,
  id_usuario_lab  BIGINT,
  creado_en       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ticket_lab_estado ON produccion.fact_ticket_lab(estado);
CREATE INDEX IF NOT EXISTS ix_ticket_lab_batch  ON produccion.fact_ticket_lab(id_batch);

CREATE TABLE IF NOT EXISTS produccion.fact_batch_insumo (
  id_batch_insumo BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_batch        BIGINT NOT NULL REFERENCES produccion.fact_batch_proceso(id_batch) ON DELETE CASCADE,
  rol             TEXT NOT NULL DEFAULT 'INSUMO' CHECK (rol IN ('INSUMO','MP')),
  codigo_insumo   TEXT REFERENCES produccion.dic_insumo(codigo),
  id_producto     BIGINT REFERENCES produccion.dim_producto(id_producto),
  cantidad        NUMERIC NOT NULL CHECK (cantidad >= 0),
  unidad          TEXT,
  fuente          TEXT NOT NULL CHECK (fuente IN ('TICKET','TANQUE')),
  ticket_porteria TEXT,
  id_tanque       BIGINT REFERENCES produccion.dim_tanque(id_tanque),
  ticket_lab      TEXT,
  id_ticket       BIGINT REFERENCES produccion.fact_ticket_lab(id_ticket),
  id_movimiento   BIGINT REFERENCES produccion.fact_movimiento_tanque(id_movimiento) ON DELETE SET NULL,
  id_usuario      BIGINT,
  anulado         BOOLEAN NOT NULL DEFAULT FALSE,
  creado_en       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_bi_identidad CHECK ((rol='INSUMO' AND codigo_insumo IS NOT NULL) OR (rol='MP' AND id_producto IS NOT NULL)),
  CONSTRAINT chk_bi_fuente CHECK ((fuente='TICKET' AND ticket_porteria IS NOT NULL AND id_tanque IS NULL)
                               OR (fuente='TANQUE' AND id_tanque IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_batch_insumo_batch ON produccion.fact_batch_insumo(id_batch);

CREATE OR REPLACE FUNCTION produccion.fn_batch_insumo_carga()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = produccion, public, pg_temp AS $$
DECLARE v_prod_id bigint; v_unidad text; v_densidad double precision;
        v_kg numeric; v_litros numeric; v_ticket text; v_id_ticket bigint;
BEGIN
  IF new.rol='INSUMO' THEN
    SELECT i.unidad, i.id_producto_equiv INTO v_unidad, v_prod_id FROM produccion.dic_insumo i WHERE i.codigo=new.codigo_insumo;
    new.unidad := COALESCE(new.unidad, v_unidad);
  ELSE
    v_prod_id := new.id_producto; new.unidad := COALESCE(new.unidad,'KG');
  END IF;

  v_ticket := 'TL-' || lpad(nextval('produccion.seq_ticket_lab')::text, 8, '0');
  INSERT INTO produccion.fact_ticket_lab
    (ticket_lab, id_batch, id_batch_insumo, rol, codigo_insumo, id_producto, fuente, ticket_porteria, id_tanque, cantidad, unidad)
  VALUES (v_ticket, new.id_batch, new.id_batch_insumo, new.rol, new.codigo_insumo, new.id_producto,
          new.fuente, new.ticket_porteria, new.id_tanque, new.cantidad, new.unidad)
  RETURNING id_ticket INTO v_id_ticket;
  new.ticket_lab := v_ticket; new.id_ticket := v_id_ticket;

  IF new.fuente='TANQUE' THEN
    SELECT p.densidad_g_ml INTO v_densidad FROM produccion.dim_producto p WHERE p.id_producto=v_prod_id;
    IF upper(COALESCE(new.unidad,'KG'))='L' THEN
      v_litros := new.cantidad; v_kg := CASE WHEN v_densidad IS NOT NULL THEN new.cantidad*v_densidad END;
    ELSE
      v_kg := new.cantidad; v_litros := CASE WHEN v_densidad IS NOT NULL AND v_densidad>0 THEN new.cantidad/v_densidad END;
    END IF;
    INSERT INTO produccion.fact_movimiento_tanque (id_tanque, id_producto, tipo, litros, kg, id_batch, id_usuario, origen, observaciones)
    VALUES (new.id_tanque, v_prod_id, 'OUT', v_litros, v_kg, new.id_batch, new.id_usuario, 'PROCESO',
            'Consumo batch '||new.id_batch||' ('||COALESCE(new.codigo_insumo,(SELECT codigo_producto FROM produccion.dim_producto WHERE id_producto=new.id_producto))||')')
    RETURNING id_movimiento INTO new.id_movimiento;
  END IF;
  RETURN new;
END $$;
DROP TRIGGER IF EXISTS trg_batch_insumo_carga ON produccion.fact_batch_insumo;
CREATE TRIGGER trg_batch_insumo_carga BEFORE INSERT ON produccion.fact_batch_insumo
  FOR EACH ROW EXECUTE FUNCTION produccion.fn_batch_insumo_carga();

CREATE OR REPLACE FUNCTION produccion.fn_batch_insumo_post()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = produccion, public, pg_temp AS $$
BEGIN
  UPDATE produccion.fact_ticket_lab SET id_batch_insumo=new.id_batch_insumo WHERE id_ticket=new.id_ticket;
  IF new.rol='INSUMO' THEN
    UPDATE produccion.fact_batch_proceso b
       SET insumos = jsonb_set(COALESCE(b.insumos,'{}'::jsonb), ARRAY[new.codigo_insumo],
                       to_jsonb(COALESCE((b.insumos->>new.codigo_insumo)::numeric,0) + new.cantidad))
     WHERE b.id_batch=new.id_batch;
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS trg_batch_insumo_post ON produccion.fact_batch_insumo;
CREATE TRIGGER trg_batch_insumo_post AFTER INSERT ON produccion.fact_batch_insumo
  FOR EACH ROW EXECUTE FUNCTION produccion.fn_batch_insumo_post();

-- --- Cronograma de evaluacion interna (slots automaticos al iniciar) ----------
CREATE TABLE IF NOT EXISTS produccion.dic_cronograma_eval (
  tipo_proceso  TEXT PRIMARY KEY REFERENCES produccion.dic_tipo_proceso(codigo),
  cadencia      TEXT NOT NULL CHECK (cadencia IN ('HORARIA','UNICA')),
  etapa         TEXT REFERENCES produccion.dic_etapa_proceso(codigo),
  activo        BOOLEAN NOT NULL DEFAULT TRUE,
  observaciones TEXT
);
CREATE TABLE IF NOT EXISTS produccion.fact_eval_programada (
  id_prog       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_batch      BIGINT NOT NULL REFERENCES produccion.fact_batch_proceso(id_batch) ON DELETE CASCADE,
  tipo_proceso  TEXT,
  etapa         TEXT,
  secuencia     INT NOT NULL,
  programado_ts TIMESTAMPTZ NOT NULL,
  estado        TEXT NOT NULL DEFAULT 'PENDIENTE' CHECK (estado IN ('PENDIENTE','REALIZADA','OMITIDA')),
  id_eval       BIGINT REFERENCES produccion.fact_evaluacion_interna(id_eval),
  creado_en     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (id_batch, secuencia)
);
CREATE INDEX IF NOT EXISTS ix_eval_prog_batch ON produccion.fact_eval_programada(id_batch, estado);

CREATE OR REPLACE FUNCTION produccion.fn_generar_cronograma_eval()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = produccion, public, pg_temp AS $$
DECLARE v_cad text; v_etapa text; v_n int; k int;
BEGIN
  IF new.inicio_ts IS NULL THEN RETURN new; END IF;
  IF tg_op='UPDATE' AND old.inicio_ts IS NOT NULL THEN RETURN new; END IF;
  IF new.tipo_proceso IS NULL THEN RETURN new; END IF;
  SELECT cadencia, etapa INTO v_cad, v_etapa FROM produccion.dic_cronograma_eval WHERE tipo_proceso=new.tipo_proceso AND activo;
  IF v_cad IS NULL THEN RETURN new; END IF;
  IF EXISTS (SELECT 1 FROM produccion.fact_eval_programada WHERE id_batch=new.id_batch) THEN RETURN new; END IF;
  IF v_cad='UNICA' THEN v_n := 1; ELSE v_n := greatest(1, ceil(COALESCE(new.tiempo_estimado_horas,0))::int + 1); END IF;
  FOR k IN 0 .. v_n-1 LOOP
    INSERT INTO produccion.fact_eval_programada (id_batch, tipo_proceso, etapa, secuencia, programado_ts)
    VALUES (new.id_batch, new.tipo_proceso, COALESCE(v_etapa,new.etapa_actual), k+1, new.inicio_ts + make_interval(hours => k));
  END LOOP;
  RETURN new;
END $$;
DROP TRIGGER IF EXISTS trg_cronograma_eval ON produccion.fact_batch_proceso;
CREATE TRIGGER trg_cronograma_eval AFTER INSERT OR UPDATE OF inicio_ts, tipo_proceso, tiempo_estimado_horas
  ON produccion.fact_batch_proceso FOR EACH ROW EXECUTE FUNCTION produccion.fn_generar_cronograma_eval();

-- --- Parametros iniciales por proceso + derivar corriente/proceso de la MP ----
CREATE TABLE IF NOT EXISTS produccion.dic_proceso_parametros (
  tipo_proceso        TEXT PRIMARY KEY REFERENCES produccion.dic_tipo_proceso(codigo),
  temp_inicial_c      NUMERIC,
  tiempo_total_horas  NUMERIC,
  acidez_objetivo_pct NUMERIC,
  calidad_objetivo    TEXT REFERENCES produccion.dic_calidad(codigo),
  observaciones       TEXT
);

CREATE OR REPLACE FUNCTION produccion.fn_derivar_desde_mp()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = produccion, public, pg_temp AS $$
DECLARE v_codigo text; v_corriente text; v_tipo text;
BEGIN
  IF new.id_producto_inicial IS NULL THEN RETURN new; END IF;
  SELECT codigo_producto, corriente INTO v_codigo, v_corriente FROM produccion.dim_producto WHERE id_producto=new.id_producto_inicial;
  IF v_corriente IS NOT NULL THEN new.corriente := v_corriente; END IF;
  IF new.tipo_proceso IS NULL AND new.sector IS NOT NULL THEN
    SELECT pp.tipo_proceso INTO v_tipo FROM produccion.dic_proceso_producto pp
     WHERE pp.rol='MP' AND pp.sector=new.sector AND pp.tipo_proceso IS NOT NULL AND v_codigo LIKE pp.patron
     ORDER BY length(pp.patron) DESC LIMIT 1;
    IF v_tipo IS NOT NULL THEN new.tipo_proceso := v_tipo; END IF;
  END IF;
  RETURN new;
END $$;
DROP TRIGGER IF EXISTS trg_derivar_desde_mp ON produccion.fact_batch_proceso;
CREATE TRIGGER trg_derivar_desde_mp BEFORE INSERT OR UPDATE OF id_producto_inicial, sector
  ON produccion.fact_batch_proceso FOR EACH ROW EXECUTE FUNCTION produccion.fn_derivar_desde_mp();

CREATE OR REPLACE VIEW produccion.vw_batch_operario AS
SELECT b.id_batch, b.fecha, b.sector, b.tipo_proceso AS area_proceso, b.corriente,
       pi.codigo_producto AS mp_codigo, pi.nombre_producto AS mp_nombre, b.kg_inicial, b.litros_inicial,
       b.ticket_porteria, b.tanque_destino,
       pb.codigo_producto AS resultado_estimado_codigo, pb.nombre_producto AS resultado_estimado_nombre,
       b.calidad_buscada, b.estimado_are_kg, b.estimado_glicerina_kg,
       COALESCE(pp.tiempo_total_horas, b.tiempo_estimado_horas) AS tiempo_total_horas,
       pp.temp_inicial_c, pp.acidez_objetivo_pct, b.inicio_ts,
       CASE WHEN b.inicio_ts IS NOT NULL
            THEN b.inicio_ts + make_interval(hours => COALESCE(pp.tiempo_total_horas, b.tiempo_estimado_horas)::int) END AS fin_estimado_ts,
       b.etapa_actual
FROM produccion.fact_batch_proceso b
LEFT JOIN produccion.dim_producto pi ON pi.id_producto = b.id_producto_inicial
LEFT JOIN produccion.dim_producto pb ON pb.id_producto = b.id_producto_buscado
LEFT JOIN produccion.dic_proceso_parametros pp ON pp.tipo_proceso = b.tipo_proceso
WHERE NOT b.anulado;

-- --- Reversa de stock + anulacion de tickets/slots al anular un batch ---------
CREATE OR REPLACE FUNCTION produccion.fn_anular_batch()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = produccion, public, pg_temp AS $$
BEGIN
  IF new.anulado AND NOT old.anulado THEN
    IF NOT EXISTS (SELECT 1 FROM produccion.fact_movimiento_tanque WHERE id_batch=new.id_batch AND origen='REVERSA') THEN
      INSERT INTO produccion.fact_movimiento_tanque (id_tanque, id_producto, tipo, litros, kg, id_batch, id_usuario, origen, observaciones)
      SELECT id_tanque, id_producto, 'IN', litros, kg, id_batch, new.id_usuario_anula, 'REVERSA', 'Reversa por anulacion batch '||new.id_batch
      FROM produccion.fact_movimiento_tanque WHERE id_batch=new.id_batch AND tipo='OUT' AND origen='PROCESO';
    END IF;
    UPDATE produccion.fact_ticket_lab SET estado='ANULADO' WHERE id_batch=new.id_batch AND estado='PENDIENTE';
    UPDATE produccion.fact_eval_programada SET estado='OMITIDA' WHERE id_batch=new.id_batch AND estado='PENDIENTE';
  END IF;
  RETURN new;
END $$;
DROP TRIGGER IF EXISTS trg_anular_batch ON produccion.fact_batch_proceso;
CREATE TRIGGER trg_anular_batch AFTER UPDATE OF anulado ON produccion.fact_batch_proceso
  FOR EACH ROW EXECUTE FUNCTION produccion.fn_anular_batch();

-- --- Parametros de lab por tanque + auto-update desde procesos_lab ------------
CREATE TABLE IF NOT EXISTS produccion.fact_param_tanque (
  id_param             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_tanque            BIGINT NOT NULL REFERENCES produccion.dim_tanque(id_tanque) ON DELETE CASCADE,
  id_producto          BIGINT NOT NULL REFERENCES produccion.dim_producto(id_producto),
  corriente            TEXT,
  evaluado             BOOLEAN NOT NULL DEFAULT FALSE,
  ultima_evaluacion_ts TIMESTAMPTZ,
  id_procesos_lab      BIGINT,
  acidez_pct           NUMERIC, agua_pct NUMERIC, sedimentos_pct NUMERIC,
  densidad_g_ml        NUMERIC, ppm_azufre NUMERIC, ppm_fosforo NUMERIC,
  parametros_extra     JSONB NOT NULL DEFAULT '{}'::jsonb,
  actualizado_en       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (id_tanque, id_producto)
);
CREATE INDEX IF NOT EXISTS ix_param_tanque_tanque   ON produccion.fact_param_tanque(id_tanque);
CREATE INDEX IF NOT EXISTS ix_param_tanque_evaluado ON produccion.fact_param_tanque(evaluado);

CREATE OR REPLACE FUNCTION produccion.fn_lab_actualiza_param_tanque()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = produccion, public, pg_temp AS $$
DECLARE v_ids text[] := ARRAY[new.id_tanque_1, new.id_tanque_2]; v_raw text; v_idt bigint; v_prod bigint; v_extra jsonb;
BEGIN
  v_extra := jsonb_strip_nulls(jsonb_build_object(
      'color',new.color,'hkf_pct',new.prc_hkf*100,'hexano_pct',new.prc_hexano_impurezas*100,
      'gli_glicerol',new.gli_glicerol,'gli_humedad',new.gli_humedad,'gli_ays',new.gli_ays,
      'borra_grasa',new.borra_prc_grasa,'eflu_ph',new.eflu_ph,
      'sebo_iodo',new.sebo_indice_yodo_gyodo_gmuestra,'temp',new.temp_celcius));
  FOREACH v_raw IN ARRAY v_ids LOOP
    IF v_raw IS NULL OR btrim(v_raw)='' THEN CONTINUE; END IF;
    IF v_raw !~ '^\d+$' THEN CONTINUE; END IF;
    v_idt := v_raw::bigint;
    IF NOT EXISTS (SELECT 1 FROM produccion.dim_tanque WHERE id_tanque=v_idt) THEN CONTINUE; END IF;
    SELECT dpl.id_producto INTO v_prod FROM produccion.dic_producto_lab dpl
      WHERE dpl.lab_producto=new.producto_lab AND (dpl.lab_calidad IS NULL OR dpl.lab_calidad=new.calidad_final_lab)
      ORDER BY (dpl.lab_calidad=new.calidad_final_lab) DESC NULLS LAST LIMIT 1;
    IF v_prod IS NULL THEN SELECT id_producto_principal INTO v_prod FROM produccion.dim_tanque WHERE id_tanque=v_idt; END IF;
    IF v_prod IS NULL THEN CONTINUE; END IF;
    INSERT INTO produccion.fact_param_tanque
      (id_tanque,id_producto,corriente,evaluado,ultima_evaluacion_ts,id_procesos_lab,
       acidez_pct,agua_pct,sedimentos_pct,densidad_g_ml,ppm_azufre,ppm_fosforo,parametros_extra,actualizado_en)
    VALUES (v_idt,v_prod,new.corriente,TRUE,COALESCE(new.fecha,now())::timestamptz,new.id,
       new.prc_acidez*100,new.prc_agua*100,new.prc_sedimentos*100,new.densidad__g_ml,new.ppm_azufre,new.ppm_fosforo,v_extra,now())
    ON CONFLICT (id_tanque,id_producto) DO UPDATE SET
       corriente=COALESCE(excluded.corriente, produccion.fact_param_tanque.corriente),
       evaluado=TRUE, ultima_evaluacion_ts=excluded.ultima_evaluacion_ts, id_procesos_lab=excluded.id_procesos_lab,
       acidez_pct=excluded.acidez_pct, agua_pct=excluded.agua_pct, sedimentos_pct=excluded.sedimentos_pct,
       densidad_g_ml=excluded.densidad_g_ml, ppm_azufre=excluded.ppm_azufre, ppm_fosforo=excluded.ppm_fosforo,
       parametros_extra=produccion.fact_param_tanque.parametros_extra || excluded.parametros_extra, actualizado_en=now();
  END LOOP;
  RETURN new;
END $$;
DROP TRIGGER IF EXISTS trg_lab_param_tanque ON produccion.procesos_lab;
CREATE TRIGGER trg_lab_param_tanque AFTER INSERT OR UPDATE ON produccion.procesos_lab
  FOR EACH ROW EXECUTE FUNCTION produccion.fn_lab_actualiza_param_tanque();

CREATE OR REPLACE VIEW produccion.vw_param_tanque_actual AS
SELECT pt.id_tanque, t.codigo, t.nombre, t.sector, p.codigo_producto, p.nombre_producto,
       pt.corriente, pt.evaluado, pt.ultima_evaluacion_ts,
       pt.acidez_pct, pt.agua_pct, pt.sedimentos_pct, pt.densidad_g_ml, pt.ppm_azufre, pt.ppm_fosforo, pt.parametros_extra
FROM produccion.fact_param_tanque pt
JOIN produccion.dim_tanque t ON t.id_tanque=pt.id_tanque
JOIN produccion.dim_producto p ON p.id_producto=pt.id_producto;

-- --- Maquina de estados del batch + log + checklist + caldera -----------------
ALTER TABLE produccion.fact_batch_proceso
  ADD COLUMN IF NOT EXISTS estado TEXT NOT NULL DEFAULT 'CARGA'
    CHECK (estado IN ('CARGA','REACCION','REPOSO','DECANTACION','FINALIZADO','FRENADA','ANULADA')),
  ADD COLUMN IF NOT EXISTS caldera_encendida_ts    TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS esperando_validacion_lab BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS ticket_validacion_lab    TEXT,
  ADD COLUMN IF NOT EXISTS validado_lab             BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS id_usuario_estado BIGINT,
  ADD COLUMN IF NOT EXISTS motivo_estado     TEXT;
COMMENT ON COLUMN produccion.fact_batch_proceso.caldera_encendida_ts IS
  'Prendido de caldera. Debe ser >= 1h antes del inicio de reaccion para llegar a 80 C.';

CREATE TABLE IF NOT EXISTS produccion.fact_batch_estado_log (
  id_log          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_batch        BIGINT NOT NULL REFERENCES produccion.fact_batch_proceso(id_batch) ON DELETE CASCADE,
  estado_anterior TEXT, estado_nuevo TEXT NOT NULL,
  ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  id_usuario      BIGINT, motivo TEXT
);
CREATE INDEX IF NOT EXISTS ix_estado_log_batch ON produccion.fact_batch_estado_log(id_batch, ts);

CREATE OR REPLACE FUNCTION produccion.fn_log_estado_batch()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = produccion, public, pg_temp AS $$
BEGIN
  IF tg_op='INSERT' OR new.estado IS DISTINCT FROM old.estado THEN
    INSERT INTO produccion.fact_batch_estado_log (id_batch, estado_anterior, estado_nuevo, id_usuario, motivo)
    VALUES (new.id_batch, CASE WHEN tg_op='UPDATE' THEN old.estado END, new.estado,
            COALESCE(new.id_usuario_estado, new.id_usuario_carga), new.motivo_estado);
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS trg_log_estado_batch ON produccion.fact_batch_proceso;
CREATE TRIGGER trg_log_estado_batch AFTER INSERT OR UPDATE OF estado ON produccion.fact_batch_proceso
  FOR EACH ROW EXECUTE FUNCTION produccion.fn_log_estado_batch();

CREATE TABLE IF NOT EXISTS produccion.fact_batch_checklist (
  id_checklist           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_batch               BIGINT NOT NULL UNIQUE REFERENCES produccion.fact_batch_proceso(id_batch) ON DELETE CASCADE,
  mp_ok                  BOOLEAN NOT NULL DEFAULT FALSE,
  insumos_ok             BOOLEAN NOT NULL DEFAULT FALSE,
  temperatura_inicial_ok BOOLEAN NOT NULL DEFAULT FALSE,
  parametros_ok          BOOLEAN NOT NULL DEFAULT FALSE,
  corriente_ok           BOOLEAN NOT NULL DEFAULT FALSE,
  caldera_encendida_ok   BOOLEAN NOT NULL DEFAULT FALSE,
  id_usuario             BIGINT NOT NULL,
  confirmado_en          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE OR REPLACE FUNCTION produccion.fn_checklist_confirma()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = produccion, public, pg_temp AS $$
BEGIN
  IF new.mp_ok AND new.insumos_ok AND new.temperatura_inicial_ok AND new.parametros_ok
     AND new.corriente_ok AND new.caldera_encendida_ok THEN
    UPDATE produccion.fact_batch_proceso b
       SET id_usuario_estado=new.id_usuario, motivo_estado='Checklist de carga confirmado',
           caldera_encendida_ts=COALESCE(b.caldera_encendida_ts, now()),
           inicio_ts=COALESCE(b.inicio_ts, now()), estado='REACCION'
     WHERE b.id_batch=new.id_batch AND b.estado='CARGA';
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS trg_checklist_confirma ON produccion.fact_batch_checklist;
CREATE TRIGGER trg_checklist_confirma AFTER INSERT OR UPDATE ON produccion.fact_batch_checklist
  FOR EACH ROW EXECUTE FUNCTION produccion.fn_checklist_confirma();

-- --- Motor de reglas: evaluacion interna -> accion ----------------------------
CREATE TABLE IF NOT EXISTS produccion.dic_regla_evaluacion (
  id_regla      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tipo_proceso  TEXT NOT NULL REFERENCES produccion.dic_tipo_proceso(codigo),
  parametro     TEXT NOT NULL,
  operador      TEXT NOT NULL CHECK (operador IN ('<=','>=','<','>','=')),
  valor         NUMERIC NOT NULL,
  accion        TEXT NOT NULL CHECK (accion IN ('PASAR_A_REPOSO','PASAR_A_REPOSO_Y_VALIDAR','PASAR_A_DECANTACION','FRENAR')),
  activo        BOOLEAN NOT NULL DEFAULT TRUE,
  observaciones TEXT
);

CREATE OR REPLACE FUNCTION produccion.fn_aplicar_reglas_eval()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = produccion, public, pg_temp AS $$
DECLARE v_tipo text; v_estado text; r record; v_val numeric; v_match boolean; v_ticket text;
BEGIN
  SELECT tipo_proceso, estado INTO v_tipo, v_estado FROM produccion.fact_batch_proceso WHERE id_batch=new.id_batch;
  IF v_tipo IS NULL THEN RETURN NULL; END IF;
  FOR r IN SELECT * FROM produccion.dic_regla_evaluacion WHERE tipo_proceso=v_tipo AND activo AND new.mediciones ? parametro LOOP
    v_val := (new.mediciones->>r.parametro)::numeric;
    v_match := CASE r.operador WHEN '<=' THEN v_val<=r.valor WHEN '>=' THEN v_val>=r.valor
                               WHEN '<' THEN v_val<r.valor WHEN '>' THEN v_val>r.valor WHEN '=' THEN v_val=r.valor END;
    IF NOT COALESCE(v_match,false) THEN CONTINUE; END IF;
    IF r.accion='PASAR_A_REPOSO_Y_VALIDAR' AND v_estado='REACCION' THEN
      SELECT ticket_lab INTO v_ticket FROM produccion.fact_ticket_lab WHERE id_batch=new.id_batch AND rol='MP' ORDER BY id_ticket LIMIT 1;
      UPDATE produccion.fact_batch_proceso SET estado='REPOSO', esperando_validacion_lab=true, ticket_validacion_lab=v_ticket,
             id_usuario_estado=new.id_usuario,
             motivo_estado='Regla '||r.parametro||' '||r.operador||' '||r.valor||': reposo + validacion lab '||COALESCE(v_ticket,'(sin ticket MP)')
       WHERE id_batch=new.id_batch;
    ELSIF r.accion='PASAR_A_REPOSO' AND v_estado='REACCION' THEN
      UPDATE produccion.fact_batch_proceso SET estado='REPOSO', id_usuario_estado=new.id_usuario,
             motivo_estado='Regla '||r.parametro||' '||r.operador||' '||r.valor WHERE id_batch=new.id_batch;
    ELSIF r.accion='PASAR_A_DECANTACION' THEN
      UPDATE produccion.fact_batch_proceso SET estado='DECANTACION', id_usuario_estado=new.id_usuario,
             motivo_estado='Regla '||r.parametro||' '||r.operador||' '||r.valor WHERE id_batch=new.id_batch;
    ELSIF r.accion='FRENAR' THEN
      UPDATE produccion.fact_batch_proceso SET estado='FRENADA', id_usuario_estado=new.id_usuario,
             motivo_estado='Regla automatica '||r.parametro||' '||r.operador||' '||r.valor WHERE id_batch=new.id_batch;
    END IF;
  END LOOP;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS trg_aplicar_reglas_eval ON produccion.fact_evaluacion_interna;
CREATE TRIGGER trg_aplicar_reglas_eval AFTER INSERT ON produccion.fact_evaluacion_interna
  FOR EACH ROW EXECUTE FUNCTION produccion.fn_aplicar_reglas_eval();

CREATE OR REPLACE FUNCTION produccion.fn_validar_lab_batch()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = produccion, public, pg_temp AS $$
BEGIN
  IF new.estado='EVALUADO' AND (tg_op='INSERT' OR old.estado IS DISTINCT FROM new.estado) THEN
    UPDATE produccion.fact_batch_proceso SET validado_lab=true, esperando_validacion_lab=false
     WHERE ticket_validacion_lab=new.ticket_lab AND esperando_validacion_lab;
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS trg_validar_lab_batch ON produccion.fact_ticket_lab;
CREATE TRIGGER trg_validar_lab_batch AFTER INSERT OR UPDATE OF estado ON produccion.fact_ticket_lab
  FOR EACH ROW EXECUTE FUNCTION produccion.fn_validar_lab_batch();

CREATE OR REPLACE FUNCTION produccion.fn_frenar_reaccion(p_id_batch bigint, p_id_usuario bigint, p_motivo text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SET search_path = produccion, public, pg_temp AS $$
BEGIN
  UPDATE produccion.fact_batch_proceso SET estado='FRENADA', id_usuario_estado=p_id_usuario,
         motivo_estado=COALESCE(p_motivo,'Frenada por supervision')
   WHERE id_batch=p_id_batch AND estado IN ('REACCION','REPOSO');
END $$;

-- --- Decantacion: ticket de lab por producto final y subproductos -------------
ALTER TABLE produccion.fact_salida_decantacion
  ADD COLUMN IF NOT EXISTS ticket_lab TEXT,
  ADD COLUMN IF NOT EXISTS id_ticket  BIGINT REFERENCES produccion.fact_ticket_lab(id_ticket);

CREATE OR REPLACE FUNCTION produccion.fn_decantacion_ticket()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = produccion, public, pg_temp AS $$
DECLARE v_final bigint; v_rol text; v_ticket text; v_id bigint;
BEGIN
  SELECT id_producto_obtenido INTO v_final FROM produccion.fact_batch_proceso WHERE id_batch=new.id_batch;
  v_rol := CASE WHEN v_final IS NOT NULL AND new.id_producto=v_final THEN 'FINAL' ELSE 'SUBPRODUCTO' END;
  v_ticket := 'TL-' || lpad(nextval('produccion.seq_ticket_lab')::text, 8, '0');
  INSERT INTO produccion.fact_ticket_lab (ticket_lab, id_batch, rol, id_producto, fuente, cantidad, unidad)
  VALUES (v_ticket, new.id_batch, v_rol, new.id_producto, 'DECANTACION', new.kg, 'KG') RETURNING id_ticket INTO v_id;
  UPDATE produccion.fact_salida_decantacion SET ticket_lab=v_ticket, id_ticket=v_id WHERE id_salida=new.id_salida;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS trg_decantacion_ticket ON produccion.fact_salida_decantacion;
CREATE TRIGGER trg_decantacion_ticket AFTER INSERT ON produccion.fact_salida_decantacion
  FOR EACH ROW EXECUTE FUNCTION produccion.fn_decantacion_ticket();

-- --- Cronograma diario de reactores + cumplimiento + serie de mediciones ------
CREATE TABLE IF NOT EXISTS produccion.plan_dia_reactor (
  id_plan          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  fecha            DATE NOT NULL,
  id_bien_uso      BIGINT REFERENCES produccion.dim_bien_uso(id_bien_uso),
  reactor_label    TEXT,
  id_batch         BIGINT REFERENCES produccion.fact_batch_proceso(id_batch),
  caldera_plan_ts  TIMESTAMPTZ,
  reaccion_plan_ts TIMESTAMPTZ,
  observaciones    TEXT,
  creado_en        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_plan_dia_fecha ON produccion.plan_dia_reactor(fecha);

CREATE OR REPLACE VIEW produccion.vw_batch_tiempos AS
SELECT b.id_batch, b.fecha, b.sector, b.tipo_proceso, b.estado, b.caldera_encendida_ts,
       min(l.ts) FILTER (WHERE l.estado_nuevo='REACCION')    AS t_reaccion,
       min(l.ts) FILTER (WHERE l.estado_nuevo='REPOSO')      AS t_reposo,
       min(l.ts) FILTER (WHERE l.estado_nuevo='DECANTACION') AS t_decantacion,
       min(l.ts) FILTER (WHERE l.estado_nuevo='FINALIZADO')  AS t_finalizado,
       min(l.ts) FILTER (WHERE l.estado_nuevo='FRENADA')     AS t_frenada
FROM produccion.fact_batch_proceso b
LEFT JOIN produccion.fact_batch_estado_log l ON l.id_batch=b.id_batch
GROUP BY b.id_batch, b.fecha, b.sector, b.tipo_proceso, b.estado, b.caldera_encendida_ts;

CREATE OR REPLACE VIEW produccion.vw_cumplimiento_cronograma AS
WITH dur AS (
  SELECT t.*,
         round(extract(epoch FROM (t.t_reposo      - t.t_reaccion))/60)::int AS reaccion_min,
         round(extract(epoch FROM (t.t_decantacion - t.t_reposo))/60)::int    AS reposo_min,
         round(extract(epoch FROM (t.t_finalizado  - t.t_decantacion))/60)::int AS decantacion_min,
         round(extract(epoch FROM (t.t_reaccion    - t.caldera_encendida_ts))/60)::int AS caldera_anticipacion_min
  FROM produccion.vw_batch_tiempos t)
SELECT d.id_batch, d.fecha, d.sector, d.tipo_proceso, d.estado,
       p.caldera_plan_ts, d.caldera_encendida_ts,
       CASE WHEN d.caldera_encendida_ts IS NULL THEN 'SIN_DATO' WHEN p.caldera_plan_ts IS NULL THEN 'SIN_PLAN'
            WHEN d.caldera_encendida_ts <= p.caldera_plan_ts THEN 'EN_HORARIO' ELSE 'FUERA_HORARIO' END AS caldera_cumplimiento,
       d.caldera_anticipacion_min, (d.caldera_anticipacion_min >= 60) AS caldera_ok_80c,
       p.reaccion_plan_ts, d.t_reaccion AS reaccion_real_ts,
       CASE WHEN d.t_reaccion IS NULL THEN 'SIN_DATO' WHEN p.reaccion_plan_ts IS NULL THEN 'SIN_PLAN'
            WHEN d.t_reaccion <= p.reaccion_plan_ts THEN 'EN_HORARIO' ELSE 'FUERA_HORARIO' END AS inicio_cumplimiento,
       d.reaccion_min, dr.duracion_target_min AS reaccion_target_min,
       d.reposo_min,   dp.duracion_target_min AS reposo_target_min,
       d.decantacion_min, dd.duracion_target_min AS decantacion_target_min
FROM dur d
LEFT JOIN produccion.plan_dia_reactor p ON p.id_batch=d.id_batch
LEFT JOIN produccion.dic_etapa_duracion dr ON dr.tipo_proceso=d.tipo_proceso AND dr.etapa='REACCION'
LEFT JOIN produccion.dic_etapa_duracion dp ON dp.tipo_proceso=d.tipo_proceso AND dp.etapa='REPOSANDO'
LEFT JOIN produccion.dic_etapa_duracion dd ON dd.tipo_proceso=d.tipo_proceso AND dd.etapa='DECANTACION';

CREATE OR REPLACE VIEW produccion.vw_evaluacion_interna_serie AS
SELECT ei.id_batch, ei.etapa, ei.ts, ei.id_usuario, kv.key AS parametro,
       CASE WHEN jsonb_typeof(kv.value)='number' THEN (kv.value)::numeric END AS valor
FROM produccion.fact_evaluacion_interna ei
CROSS JOIN LATERAL jsonb_each(ei.mediciones) kv
WHERE NOT ei.anulado;

-- --- Permisos de lectura para el chat IA (rol read-only) ----------------------
GRANT SELECT ON
  produccion.fact_movimiento_tanque, produccion.fact_batch_insumo, produccion.fact_ticket_lab,
  produccion.fact_eval_programada, produccion.dic_cronograma_eval, produccion.dic_proceso_parametros,
  produccion.fact_param_tanque, produccion.fact_batch_estado_log, produccion.fact_batch_checklist,
  produccion.dic_regla_evaluacion, produccion.plan_dia_reactor,
  produccion.vw_stock_tanque_actual, produccion.vw_stock_snapshot_ultimo, produccion.vw_batch_operario,
  produccion.vw_param_tanque_actual, produccion.vw_batch_tiempos, produccion.vw_cumplimiento_cronograma,
  produccion.vw_evaluacion_interna_serie
TO ai_readonly;
