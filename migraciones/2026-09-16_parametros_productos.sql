-- ============================================================================
-- 2026-09-16 · PARÁMETROS · productos líquidos, calidades y sus límites
--
-- La planilla de parámetros de dirección puesta en la portada, sin planilla. Dos vistas:
--
-- 1) v_parametro_producto: dim_maestro_parametro normalizado contra dim_producto, con la
--    familia, la calidad y si el parámetro define calidad o sólo se registra.
--
--    En casi todas las familias la CALIDAD ES EL PRODUCTO: AG-A, AG-B, AG-C y AG-D son
--    cuatro productos del maestro y el parámetro decide cuál es. Lo mismo ARE, BORRA,
--    GLICERINA y SEBO. La columna `calidad` sale del sufijo del código.
--
--    Los códigos del maestro no son los de dim_producto, así que se mapean a mano y a la
--    vista (FUEL_OIL→FUEL, SODA CAUSTICA→SODA, AN-ARE-A→ARE-A-ANIMAL, AN-BORRA→BORRA-ANIMAL,
--    AN-BORRA-PES→BORRA-PES, AN-AG-PES→AG-PES, GLICERINA-A..D→GLICERINA-FE).
--
--    especificacion = 'SI' NO es un límite: significa que el análisis se hace y queda
--    registrado pero no define la calidad. Se expone como define_calidad = false para que
--    la pantalla escriba "se mide" y no se confunda con un dato faltante.
--
-- 2) v_calidad_afe: la familia AFE es la excepción. El maestro tiene un solo AFE-S y la
--    calidad A/B/C/D la pone laboratorio con el azufre y el fósforo del tanque, vía
--    fn_categoria_afe: índice = máx(azufre/50, fósforo/150), ≤0,80 A, ≤0,90 B, ≤1,00 C,
--    por encima D, sin análisis NO EVALUADO. Como máx(a,b) ≤ k equivale a a ≤ k Y b ≤ k,
--    los límites por columna son exactos: A = azufre ≤ 40 Y fósforo ≤ 120, B = 45 y 135,
--    C = 50 y 150.
--
--    Los límites de la vista están verificados contra fn_categoria_afe en los bordes (ver
--    el control al final). Si alguien toca la función y no la vista, ese control lo caza.
-- ============================================================================

DROP VIEW IF EXISTS produccion.v_parametro_producto;
CREATE VIEW produccion.v_parametro_producto AS
WITH m AS (
  SELECT btrim(p.producto) AS producto, p.rubro, p.corriente, btrim(p.descripcion) AS descripcion,
         btrim(p.parametro) AS parametro, btrim(p.especificacion) AS especificacion
    FROM produccion.dim_maestro_parametro p
), c AS (
  SELECT m.*,
    CASE
      WHEN m.producto ~ '^GLICERINA-[A-D]$'                THEN 'GLICERINA-FE'
      WHEN upper(replace(m.producto,'_','-')) = 'FUEL-OIL'  THEN 'FUEL'
      WHEN upper(m.producto) = 'SODA CAUSTICA'              THEN 'SODA'
      WHEN m.producto = 'AN-AG-PES'                         THEN 'AG-PES'
      WHEN m.producto = 'AN-ARE-A'                          THEN 'ARE-A-ANIMAL'
      WHEN m.producto = 'AN-BORRA'                          THEN 'BORRA-ANIMAL'
      WHEN m.producto = 'AN-BORRA-PES'                      THEN 'BORRA-PES'
      ELSE upper(replace(m.producto,'_','-'))
    END AS codigo_producto,
    CASE
      WHEN m.rubro = 'INSUMO' AND m.corriente = 'QUIMICO' THEN 'INSUMOS QUIMICOS'
      ELSE split_part(regexp_replace(m.producto, '^AN-', ''), '-', 1)
    END AS familia,
    CASE
      WHEN m.rubro = 'INSUMO' AND m.corriente = 'QUIMICO'           THEN NULL
      WHEN m.producto ~ '^SEBO-[A-C]-[12](RA|DA)$'                  THEN substring(m.producto from 6)
      WHEN regexp_replace(m.producto,'^AN-','') ~ '^[A-Z]+-[A-E]$'  THEN right(m.producto, 1)
      ELSE NULL
    END AS calidad
  FROM m
)
SELECT c.familia, c.producto, c.calidad, c.descripcion, c.rubro, c.corriente,
       c.parametro, c.especificacion,
       upper(btrim(c.especificacion)) <> 'SI' AS define_calidad,
       c.codigo_producto,
       COALESCE(d.es_liquido, true) AS es_liquido,
       d.nombre_producto, d.rotulo_oficial, d.densidad_g_ml,
       c.familia = 'AFE' AS calidad_la_define_lab
  FROM c
  LEFT JOIN produccion.dim_producto d ON d.codigo_producto = c.codigo_producto AND d.activo;

GRANT SELECT ON produccion.v_parametro_producto TO PUBLIC;

DROP VIEW IF EXISTS produccion.v_calidad_afe;
CREATE VIEW produccion.v_calidad_afe AS
SELECT * FROM (VALUES
  (1, 'A',           'hasta 0,80',          40.0::numeric, 120.0::numeric, 'la mejor: sale a exportación sin reparos'),
  (2, 'B',           'de 0,81 a 0,90',      45.0,          135.0,          'buena: exportable'),
  (3, 'C',           'de 0,91 a 1,00',      50.0,          150.0,          'al límite: revisar antes de embarcar'),
  (4, 'D',           'por encima de 1,00',  NULL::numeric, NULL::numeric,  'fuera de especificación: no se exporta así'),
  (5, 'NO EVALUADO', 'sin análisis',        NULL,          NULL,           'laboratorio todavía no le tomó azufre ni fósforo')
) v(orden, calidad, indice, azufre_max_ppm, fosforo_max_ppm, que_significa);

GRANT SELECT ON produccion.v_calidad_afe TO PUBLIC;

-- Control 1: los límites de v_calidad_afe tienen que coincidir con fn_categoria_afe, que es
-- la que realmente clasifica. En el límite da la letra; un pelo por encima da la siguiente.
--   A → A, A, B, A · B → B, B, C, B · C → C, C, D, C
SELECT c.calidad,
       produccion.fn_categoria_afe(c.azufre_max_ppm, 0)                 AS en_el_limite_de_azufre,
       produccion.fn_categoria_afe(0, c.fosforo_max_ppm)                AS en_el_limite_de_fosforo,
       produccion.fn_categoria_afe(c.azufre_max_ppm + 0.1, 0)           AS un_pelo_por_encima,
       produccion.fn_categoria_afe(c.azufre_max_ppm, c.fosforo_max_ppm) AS ambos_al_limite
  FROM produccion.v_calidad_afe c WHERE c.azufre_max_ppm IS NOT NULL ORDER BY c.orden;

-- Control 2: productos líquidos dados de alta que todavía no tienen parámetros en el maestro.
-- Hoy son 10, y el que importa es AFE-M (Maní): se mueve, se exporta y no tiene contra qué
-- compararlo el laboratorio.
SELECT d.codigo_producto, d.nombre_producto, d.tipo_producto
  FROM produccion.dim_producto d
 WHERE d.activo AND d.es_liquido
   AND NOT EXISTS (SELECT 1 FROM produccion.v_parametro_producto v
                    WHERE v.codigo_producto = d.codigo_producto)
 ORDER BY 1;
