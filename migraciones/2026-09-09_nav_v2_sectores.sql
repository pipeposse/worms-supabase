-- ============================================================================
-- NAVEGACIÓN V2 · FASE 0 · SECTORES DE NAVEGACIÓN   · aplicada en worms-prod 2026-09-09
-- ----------------------------------------------------------------------------
-- Fernando propuso (Sistema WORMS.xlsx, 28/08/2026) que el área Producción se
-- navegue por 14 sectores. Hoy la app tiene 4 "sectores de gestión"
-- (dim_sector_gestion: Reactores, Piletas, Bachas, Exportación) sobre los que
-- se miden objetivos, brief y desvíos en TN. Son cosas distintas:
--
--   * sector de GESTIÓN  = unidad sobre la que se planifica y se mide (4).
--   * sector de NAVEGACIÓN = tarjeta por la que un usuario entra a trabajar (14).
--
-- Esta tabla NO toca dim_sector_gestion ni dic_sector: es una capa de
-- navegación. Cada sector de navegación puede apuntar a un sector de gestión
-- (para heredar KPIs y filtros) y a un código de dic_sector (para filtrar
-- fact_batch_proceso). Los sectores sin datos todavía se muestran atenuados.
-- ============================================================================
CREATE TABLE IF NOT EXISTS produccion.dim_sector_nav (
    codigo          text        PRIMARY KEY,           -- clave estable para query params (?sector=REACTORES)
    nombre_ui       text        NOT NULL,              -- nombre tal cual en la grilla del director
    icono           text        NOT NULL DEFAULT '🏭',
    orden           smallint    NOT NULL,
    activo          boolean     NOT NULL DEFAULT true, -- aparece en la grilla
    tiene_datos     boolean     NOT NULL DEFAULT false,-- false = tarjeta atenuada "próximamente"
    sector_gestion  text        REFERENCES produccion.dim_sector_gestion(codigo),
    sector_batch    text,                              -- código en dic_sector / fact_batch_proceso.sector
    seccion_clasica text,                              -- sección de la app clásica que hoy cubre este sector
    descripcion     text,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    actualizado_en  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE produccion.dim_sector_nav IS
  'Sectores de NAVEGACIÓN del área Producción (14, según Sistema WORMS.xlsx de dirección). '
  'No reemplaza a dim_sector_gestion (4 unidades de gestión sobre las que se mide en TN): '
  'cada tarjeta apunta al sector de gestión y al código de batch que le corresponde.';

INSERT INTO produccion.dim_sector_nav
    (codigo, nombre_ui, icono, orden, activo, tiene_datos, sector_gestion, sector_batch, seccion_clasica, descripcion)
VALUES
    ('REACTORES',     'Reactor',                 '⚙️', 10, true, true,  'REACTORES',   'REACTORES',    'INICIAR',      'Producción ARE y desgomado acuoso en reactores.'),
    ('BACHAS',        'Bachas',                  '🛢️', 20, true, true,  'BACHAS',      'BACHAS',       'INICIAR',      'Tratamiento térmico y termoquímico en bachas.'),
    ('PILETAS',       'Piletas',                 '🌊', 30, true, true,  'PILETAS',     'RECUPERACION', 'RECUPERACION', 'Recuperación de AG en piletas.'),
    ('EXPORTACION',   'Exportación',             '🚢', 40, true, true,  'EXPORTACION', 'EXPO',         'STOCK',        'Despachos y contenedores de exportación.'),
    ('DF_LIQUIDOS',   'Disp. Final Líquidos',    '💧', 50, true, false, NULL,          NULL,           'LAB',          'Ingresos de disposición final de líquidos.'),
    ('DF_SOLIDOS',    'Disp. Final Sólidos',     '🗑️', 60, true, false, NULL,          NULL,           NULL,           'Ingresos de disposición final de sólidos.'),
    ('SOLIDOS',       'Sólidos',                 '🧱', 70, true, false, NULL,          NULL,           NULL,           'Acopio y proceso de sólidos.'),
    ('NFU',           'NFU',                     '♻️', 80, true, false, NULL,          NULL,           NULL,           'Neumáticos fuera de uso.'),
    ('COMPOST',       'Compost & Fertilizante',  '🌱', 90, true, false, NULL,          NULL,           NULL,           'Compost y fertilizantes.'),
    ('TALLER',        'Taller & Mantenimiento',  '🔧', 100, true, true, NULL,          NULL,           'REPUESTOS',    'Pañol de repuestos y mantenimiento.'),
    ('LABORATORIO',   'Laboratorio',             '🧪', 110, true, true, NULL,          NULL,           'LAB',          'Evaluaciones de laboratorio.'),
    ('PORTERIA',      'Portería',                '🚧', 120, true, true, NULL,          NULL,           'LAB',          'Ingresos de camiones y disponibilidad de descarga.'),
    ('INTENDENCIA',   'Intendencia',             '🧹', 130, true, false, NULL,         NULL,           NULL,           'Intendencia de planta.'),
    ('LOGISTICA',     'Logística',               '🚚', 140, true, false, NULL,         NULL,           NULL,           'Logística interna y de despachos.')
ON CONFLICT (codigo) DO UPDATE SET
    nombre_ui = EXCLUDED.nombre_ui, icono = EXCLUDED.icono, orden = EXCLUDED.orden,
    sector_gestion = EXCLUDED.sector_gestion, sector_batch = EXCLUDED.sector_batch,
    seccion_clasica = EXCLUDED.seccion_clasica, descripcion = EXCLUDED.descripcion,
    actualizado_en = now();

-- Misma política que el resto de las dimensiones del esquema produccion
-- (dim_sector_gestion sólo tiene grants para postgres): la app entra con el
-- rol de servicio; no se agregan grants ni RLS acá.
