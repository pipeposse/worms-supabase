-- =====================================================================================
-- Un producto que no es del sector no se cuenta como su stock
-- 16/09/2026
--
-- La emulsión aparecía en Exportación porque dos tanques de Plataforma 1 (Base plana vieja
-- 9 y 20) quedaron designados EMULSION en el maestro de tanques — antes eran AG-D. La
-- asignación automática de portería hizo lo correcto según su regla (manda cada camión al
-- tanque designado para ese producto), así que el problema es la designación, no el algoritmo.
--
-- Mientras eso no se corrija en planta, v_cuenta_sector.del_sector marca qué cuentas son del
-- sector y cuáles están ahí de prestado. La regla no la invento: un producto es del sector si
--   · el sector lo despachó alguna vez por ODV, o
--   · el maestro de productos se lo asigna (es_exportacion / usa_piletas / usa_bachas / usa_reactor).
-- Se evalúa por PRODUCTO, no por calidad, para que AFE-S NO EVALUADO no quede afuera.
--
-- En la pantalla el filtro arranca en "Del sector" y "Todos" sigue estando a un clic.
-- =====================================================================================

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
), u AS (
  SELECT COALESCE(t.sector, m.sector) AS sector,
         COALESCE(t.cuenta, m.cuenta) AS cuenta,
         COALESCE(t.producto_codigo, m.producto_codigo) AS producto_codigo,
         COALESCE(t.tanques, 0) AS tanques, COALESCE(t.tanques_en_uso, 0) AS tanques_en_uso,
         COALESCE(m.movimientos, 0) AS movimientos, COALESCE(m.salidas_odv, 0) AS salidas_odv,
         COALESCE(m.tn_odv, 0) AS tn_odv, COALESCE(m.tn_entradas, 0) AS tn_entradas,
         COALESCE(m.tn_salidas, 0) AS tn_salidas, m.desde, m.hasta
    FROM tq t FULL JOIN mv m ON m.sector = t.sector AND m.cuenta = t.cuenta
), pr AS (
  SELECT sector, producto_codigo, sum(salidas_odv) AS odv_producto FROM u GROUP BY 1,2
)
SELECT u.sector, u.cuenta, dp.nombre_producto AS descripcion,
       u.tanques, u.tanques_en_uso, u.movimientos, u.salidas_odv,
       u.tn_odv, u.tn_entradas, u.tn_salidas, u.desde, u.hasta,
       CASE WHEN u.salidas_odv > 0    THEN 'EXPORTA'
            WHEN u.tanques_en_uso > 0 THEN 'ACOPIO'
            WHEN u.tanques > 0        THEN 'TANQUE FUERA DE USO'
            ELSE 'HISTORICO' END AS rol,
       (COALESCE(pr.odv_producto, 0) > 0
        OR CASE u.sector
             WHEN 'EXPORTACION' THEN COALESCE(dp.es_exportacion, false)
             WHEN 'PILETAS'     THEN COALESCE(dp.usa_piletas,   false)
             WHEN 'BACHAS'      THEN COALESCE(dp.usa_bachas,    false)
             WHEN 'REACTORES'   THEN COALESCE(dp.usa_reactor,   false)
             ELSE true END) AS del_sector,
       u.producto_codigo
  FROM u
  LEFT JOIN pr ON pr.sector = u.sector AND pr.producto_codigo IS NOT DISTINCT FROM u.producto_codigo
  LEFT JOIN produccion.dim_producto dp ON upper(dp.codigo_producto) = upper(u.producto_codigo);

-- Para ver qué quedó dentro y fuera de cada sector:
-- SELECT sector, del_sector, string_agg(cuenta, ', ' ORDER BY cuenta)
--   FROM produccion.v_cuenta_sector GROUP BY 1,2 ORDER BY 1,2 DESC;
