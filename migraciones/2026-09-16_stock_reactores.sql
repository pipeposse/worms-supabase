-- =====================================================================================
-- Stock de un sector de proceso (Reactor, Bachas, Piletas)
-- 16/09/2026
--
-- Es la misma pantalla de Exportación, pero un sector de proceso no embarca: produce. Así que
-- su stock son sus movimientos de producción — materia prima, insumos y producto final.
--
--  1. v_stock_cuenta_sector: el movimiento se engancha al producto por rótulo, por NOMBRE del
--     producto o por alias. Los procesos viejos escriben "Glicerina fresca", "Glicerina
--     recuperada" y "POTASIO" en vez del código, y eso abría cuentas duplicadas en Reactores
--     (128 movimientos y 609 TN colgados de cuentas sueltas).
--  2. v_cuenta_sector: un INSUMO con tanque en uso en el sector es del sector. El ácido
--     sulfúrico, la soda, la potasa, el gasoil, el cloruro y el agua ácida no están en el
--     maestro como "usa_reactor", pero se consumen ahí.
--     Se agrega tipo_producto para poder separar materia prima / insumo / producto final.
-- =====================================================================================

CREATE OR REPLACE VIEW produccion.v_stock_cuenta_sector AS
WITH base AS (
  SELECT p.codigo_producto, COALESCE(p.densidad_g_ml, 0.92) AS densidad,
         cp.cuenta, cp.cuenta_nombre, cp.calidad, cp.corriente, cp.corriente_nombre,
         produccion.fn_prod_label(p.codigo_producto) AS label, p.nombre_producto
    FROM produccion.dim_producto p
    LEFT JOIN LATERAL produccion.fn_cuenta_partes(p.codigo_producto) cp ON true
), claves AS (
  SELECT upper(btrim(label)) AS k, 1 AS prio, b.* FROM base b
  UNION ALL SELECT upper(btrim(nombre_producto)), 2, b.* FROM base b WHERE nombre_producto IS NOT NULL
  UNION ALL SELECT upper(btrim(codigo_producto)), 3, b.* FROM base b
  UNION ALL SELECT 'POTASIO', 4, b.* FROM base b WHERE b.codigo_producto = 'POTASA-CAUSTICA'
), pr AS (
  SELECT DISTINCT ON (k) k, codigo_producto, densidad, cuenta, cuenta_nombre, calidad,
         corriente, corriente_nombre
    FROM claves ORDER BY k, prio, codigo_producto
), tq AS (
  SELECT t.nombre,
         CASE WHEN produccion.fn_categoria_afe(t.azufre, t.fosforo) IN ('A','B','C','D')
              THEN produccion.fn_categoria_afe(t.azufre, t.fosforo) ELSE 'NE' END AS cat_afe
    FROM produccion.vw_tanque_panel t
), m AS (
  SELECT mv.*, c.codigo_producto AS producto_codigo, c.corriente, c.densidad,
         c.cuenta AS cuenta_base, c.cuenta_nombre AS cuenta_nombre_base,
         c.calidad AS calidad_base, c.corriente_nombre,
         CASE WHEN COALESCE(c.codigo_producto, '') LIKE 'AFE%' THEN COALESCE(tq.cat_afe, 'NE') END AS grado_afe
    FROM produccion.v_movimiento_sector mv
    LEFT JOIN pr c ON c.k = upper(btrim(mv.producto))
    LEFT JOIN tq ON tq.nombre = mv.tanque
)
SELECT m.id_mov, m.momento, m.fecha, m.sector, m.sector_nombre, m.tanque, m.producto, m.grupo,
       m.tipo, m.origen, m.destino, m.ticket, m.tickets_detalle, m.contraparte,
       m.kg, m.litros, m.kg_neto, m.litros_neto, m.referencia, m.fuente_dato, m.usuario,
       m.es_ajuste_sistema, m.observacion,
       m.producto_codigo, m.corriente, m.densidad,
       COALESCE(CASE WHEN m.grado_afe = 'NE' THEN 'NO EVALUADO' ELSE m.grado_afe END,
                m.calidad_base) AS calidad,
       COALESCE(m.cuenta_base, m.producto) || COALESCE('-' || m.grado_afe, '') AS cuenta,
       COALESCE(m.cuenta_nombre_base, m.producto)
         || COALESCE(' calidad ' || CASE WHEN m.grado_afe = 'NE' THEN 'NO EVALUADO'
                                         ELSE m.grado_afe END, '') AS cuenta_nombre,
       COALESCE(m.corriente_nombre, '—') AS corriente_nombre,
       EXISTS (SELECT 1 FROM produccion.v_producto_sector ps
                WHERE ps.sector = m.sector
                  AND ps.cuenta = COALESCE(m.cuenta_base, m.producto)) AS es_del_sector
  FROM m;

-- v_cuenta_sector: insumos del sector + tipo_producto (ver 2026-09-16_del_sector.sql para el resto)
-- El cambio es la línea:
--   OR (dp.tipo_producto = 'INSUMO' AND u.tanques_en_uso > 0)
-- y la columna dp.tipo_producto al final del SELECT.
