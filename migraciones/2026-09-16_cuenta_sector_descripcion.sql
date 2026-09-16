-- =====================================================================================
-- Stock: están todos los productos, con una columna que dice qué es cada uno
-- 16/09/2026
--
--  1. v_cuenta_sector  -> catálogo de cuentas por sector: descripción del producto y qué
--                         papel juega ahí (sale por ODV / sólo acopio / histórico).
--                         Es la columna DESCRIPCIÓN y el filtro de la pantalla.
--  2. fn_stock_cerrar_saldo_inicial -> ahora el corte también abre cuenta para los productos
--                         que se movieron en el mes y hoy no están en ningún tanque, así el
--                         libro cierra en cero para ellos en vez de quedar en negativo.
--  3. fn_stock_saldo_a -> deja de filtrar por producto del sector: están todos.
-- =====================================================================================

CREATE OR REPLACE VIEW produccion.v_cuenta_sector AS
WITH tq AS (
  SELECT a.sector, (produccion.fn_cuenta_partes(a.producto_codigo)).cuenta AS cuenta,
         a.producto_codigo,
         count(*)::int AS tanques,
         count(*) FILTER (WHERE a.activo AND a.condicion <> 'FUERA DE USO')::int AS tanques_en_uso
    FROM produccion.v_acopio_sector a WHERE a.producto_codigo IS NOT NULL
   GROUP BY 1,2,3
), mv AS (
  SELECT v.sector, v.cuenta,
         max(v.producto_codigo) AS producto_codigo,
         count(*)::int AS movimientos,
         count(*) FILTER (WHERE v.destino LIKE 'ODV%')::int AS salidas_odv,
         COALESCE(sum(-v.kg_neto) FILTER (WHERE v.destino LIKE 'ODV%'), 0)/1000.0 AS tn_odv,
         COALESCE(sum(v.kg_neto)  FILTER (WHERE v.kg_neto > 0), 0)/1000.0 AS tn_entradas,
         COALESCE(sum(-v.kg_neto) FILTER (WHERE v.kg_neto < 0), 0)/1000.0 AS tn_salidas,
         min(v.fecha) AS desde, max(v.fecha) AS hasta
    FROM produccion.v_stock_cuenta_sector v
   WHERE NOT v.es_ajuste_sistema
   GROUP BY 1,2
)
SELECT COALESCE(t.sector, m.sector) AS sector,
       COALESCE(t.cuenta, m.cuenta) AS cuenta,
       dp.nombre_producto AS descripcion,
       COALESCE(t.tanques, 0) AS tanques,
       COALESCE(t.tanques_en_uso, 0) AS tanques_en_uso,
       COALESCE(m.movimientos, 0) AS movimientos,
       COALESCE(m.salidas_odv, 0) AS salidas_odv,
       COALESCE(m.tn_odv, 0) AS tn_odv,
       COALESCE(m.tn_entradas, 0) AS tn_entradas,
       COALESCE(m.tn_salidas, 0) AS tn_salidas,
       m.desde, m.hasta,
       CASE WHEN COALESCE(m.salidas_odv,0) > 0    THEN 'EXPORTA'
            WHEN COALESCE(t.tanques_en_uso,0) > 0 THEN 'ACOPIO'
            WHEN COALESCE(t.tanques,0) > 0        THEN 'TANQUE FUERA DE USO'
            ELSE 'HISTORICO' END AS rol
  FROM tq t
  FULL JOIN mv m ON m.sector = t.sector AND m.cuenta = t.cuenta
  LEFT JOIN produccion.dim_producto dp
         ON upper(dp.codigo_producto) = upper(COALESCE(t.producto_codigo, m.producto_codigo));
COMMENT ON VIEW produccion.v_cuenta_sector IS
 'Catalogo de cuentas por sector: que es cada producto y si sale por ODV o solo esta acopiado. Alimenta la columna DESCRIPCION y el filtro de Stock.';
