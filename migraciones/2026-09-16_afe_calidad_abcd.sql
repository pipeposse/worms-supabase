-- =====================================================================================
-- El AFE se lleva por calidad: V-AFE-S-A, -B, -C, -D
-- 16/09/2026
--
-- La regla YA EXISTÍA y ya se usa en el brief de dirección: produccion.fn_categoria_afe
-- gradúa por azufre (límite 50 ppm) y fósforo (límite 150 ppm), tomando el peor de los dos:
--     hasta 0,80 del límite -> A ; 0,90 -> B ; 1,00 -> C ; por encima -> D ; sin datos -> SIN LAB
-- Acá se la engancha al código de cuenta del stock, tomando azufre y fósforo DEL TANQUE,
-- que es como está armada la exportación.
--
--  1. fn_cuenta_grado(producto, azufre, fosforo) -> la cuenta con su calidad
--  2. v_stock_cuenta_sector -> cada movimiento con la calidad del tanque en el que está
--  3. v_producto_sector / v_cuenta_sector -> el catálogo también por calidad
--  4. fn_stock_cerrar_saldo_inicial -> el saldo inicial del mes, por calidad
--
-- Un tanque sin análisis queda en la cuenta sin grado (V-AFE-S), para que se vea que falta lab.
-- =====================================================================================

CREATE OR REPLACE FUNCTION produccion.fn_cuenta_grado(p text, s numeric, f numeric)
RETURNS TABLE(cuenta text, cuenta_nombre text, calidad text, corriente text, corriente_nombre text)
LANGUAGE sql STABLE AS $$
  SELECT cp.cuenta || COALESCE('-' || g.gr, ''),
         cp.cuenta_nombre || COALESCE(' calidad ' || g.gr, ''),
         COALESCE(g.gr, cp.calidad), cp.corriente, cp.corriente_nombre
    FROM produccion.fn_cuenta_partes(p) cp
    LEFT JOIN LATERAL (
      SELECT CASE WHEN upper(COALESCE(p,'')) LIKE 'AFE%'
                   AND produccion.fn_categoria_afe(s, f) IN ('A','B','C','D')
                  THEN produccion.fn_categoria_afe(s, f) END AS gr) g ON true;
$$;

CREATE OR REPLACE VIEW produccion.v_stock_cuenta_sector AS
WITH pr AS (
  SELECT DISTINCT ON (produccion.fn_prod_label(p.codigo_producto))
         produccion.fn_prod_label(p.codigo_producto) AS label,
         p.codigo_producto, COALESCE(p.densidad_g_ml, 0.92) AS densidad,
         cp.cuenta, cp.cuenta_nombre, cp.calidad, cp.corriente, cp.corriente_nombre
    FROM produccion.dim_producto p
    LEFT JOIN LATERAL produccion.fn_cuenta_partes(p.codigo_producto) cp ON true
   ORDER BY produccion.fn_prod_label(p.codigo_producto), p.codigo_producto
), tq AS (
  SELECT t.nombre, t.azufre, t.fosforo, produccion.fn_categoria_afe(t.azufre, t.fosforo) AS cat_afe
    FROM produccion.vw_tanque_panel t
), m AS (
  SELECT mv.*, c.codigo_producto AS producto_codigo, c.corriente, c.densidad,
         c.cuenta AS cuenta_base, c.cuenta_nombre AS cuenta_nombre_base,
         c.calidad AS calidad_base, c.corriente_nombre,
         CASE WHEN COALESCE(c.codigo_producto, '') LIKE 'AFE%'
                   AND tq.cat_afe IN ('A','B','C','D') THEN tq.cat_afe END AS grado_afe
    FROM produccion.v_movimiento_sector mv
    LEFT JOIN pr c ON c.label = mv.producto
    LEFT JOIN tq ON tq.nombre = mv.tanque
)
SELECT m.id_mov, m.momento, m.fecha, m.sector, m.sector_nombre, m.tanque, m.producto, m.grupo,
       m.tipo, m.origen, m.destino, m.ticket, m.tickets_detalle, m.contraparte,
       m.kg, m.litros, m.kg_neto, m.litros_neto, m.referencia, m.fuente_dato, m.usuario,
       m.es_ajuste_sistema, m.observacion,
       m.producto_codigo, m.corriente, m.densidad,
       COALESCE(m.grado_afe, m.calidad_base) AS calidad,
       COALESCE(m.cuenta_base, m.producto) || COALESCE('-' || m.grado_afe, '') AS cuenta,
       COALESCE(m.cuenta_nombre_base, m.producto) || COALESCE(' calidad ' || m.grado_afe, '') AS cuenta_nombre,
       COALESCE(m.corriente_nombre, '—') AS corriente_nombre,
       EXISTS (SELECT 1 FROM produccion.v_producto_sector ps
                WHERE ps.sector = m.sector
                  AND ps.cuenta = COALESCE(m.cuenta_base, m.producto)) AS es_del_sector
  FROM m;

CREATE OR REPLACE VIEW produccion.v_producto_sector AS
SELECT a.sector, (produccion.fn_cuenta_grado(a.producto_codigo, a.azufre, a.fosforo)).cuenta AS cuenta,
       a.producto_codigo,
       count(*)::int AS tanques,
       count(*) FILTER (WHERE a.activo AND a.condicion <> 'FUERA DE USO')::int AS tanques_en_uso
  FROM produccion.v_acopio_sector a WHERE a.producto_codigo IS NOT NULL
 GROUP BY 1,2,3;

CREATE OR REPLACE VIEW produccion.v_cuenta_sector AS
WITH tq AS (
  SELECT a.sector, (produccion.fn_cuenta_grado(a.producto_codigo, a.azufre, a.fosforo)).cuenta AS cuenta,
         a.producto_codigo, count(*)::int AS tanques,
         count(*) FILTER (WHERE a.activo AND a.condicion <> 'FUERA DE USO')::int AS tanques_en_uso
    FROM produccion.v_acopio_sector a WHERE a.producto_codigo IS NOT NULL
   GROUP BY 1,2,3
), mv AS (
  SELECT v.sector, v.cuenta, max(v.producto_codigo) AS producto_codigo,
         count(*)::int AS movimientos,
         count(*) FILTER (WHERE v.destino LIKE 'ODV%')::int AS salidas_odv,
         COALESCE(sum(-v.kg_neto) FILTER (WHERE v.destino LIKE 'ODV%'), 0)/1000.0 AS tn_odv,
         COALESCE(sum(v.kg_neto)  FILTER (WHERE v.kg_neto > 0), 0)/1000.0 AS tn_entradas,
         COALESCE(sum(-v.kg_neto) FILTER (WHERE v.kg_neto < 0), 0)/1000.0 AS tn_salidas,
         min(v.fecha) AS desde, max(v.fecha) AS hasta
    FROM produccion.v_stock_cuenta_sector v WHERE NOT v.es_ajuste_sistema
   GROUP BY 1,2
)
SELECT COALESCE(t.sector, m.sector) AS sector,
       COALESCE(t.cuenta, m.cuenta) AS cuenta,
       dp.nombre_producto AS descripcion,
       COALESCE(t.tanques, 0) AS tanques, COALESCE(t.tanques_en_uso, 0) AS tanques_en_uso,
       COALESCE(m.movimientos, 0) AS movimientos, COALESCE(m.salidas_odv, 0) AS salidas_odv,
       COALESCE(m.tn_odv, 0) AS tn_odv, COALESCE(m.tn_entradas, 0) AS tn_entradas,
       COALESCE(m.tn_salidas, 0) AS tn_salidas, m.desde, m.hasta,
       CASE WHEN COALESCE(m.salidas_odv,0) > 0    THEN 'EXPORTA'
            WHEN COALESCE(t.tanques_en_uso,0) > 0 THEN 'ACOPIO'
            WHEN COALESCE(t.tanques,0) > 0        THEN 'TANQUE FUERA DE USO'
            ELSE 'HISTORICO' END AS rol
  FROM tq t FULL JOIN mv m ON m.sector = t.sector AND m.cuenta = t.cuenta
  LEFT JOIN produccion.dim_producto dp
         ON upper(dp.codigo_producto) = upper(COALESCE(t.producto_codigo, m.producto_codigo));

-- El corte de saldo inicial también por calidad: ver el cuerpo completo en
-- 2026-09-16_stock_cuenta_corriente.sql; acá sólo cambia el JOIN de fn_cuenta_partes a
-- fn_cuenta_grado(a.producto_codigo, a.azufre, a.fosforo).
