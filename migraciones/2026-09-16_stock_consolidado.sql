-- ============================================================================
-- 2026-09-16 · Stock consolidado de toda la planta (pantalla de dirección)
--
-- Cada sector sigue viendo sólo lo suyo. Esto es para dirección: los cuatro sectores
-- con tanques sumados con la misma lógica de cuenta corriente, y lo que se está
-- escapando puesto a la vista.
--
-- 1) fn_stock_saldo_todos(fecha): el saldo inicial de todos los sectores con tanque en
--    una sola llamada. Es fn_stock_saldo_a repetida por sector, así que el número del
--    consolidado es exactamente la suma de los números que ve cada sector.
--
-- 2) v_stock_sin_tanque: los movimientos de stock que NO pasan por ningún tanque.
--    Hoy son 82 movimientos (515,9 TN) cargados desde planificación con la orden de
--    producción pero sin tanque asignado: materia prima e insumos que Reactores consume
--    de verdad y que no descuentan de ningún lado. Se atribuyen al sector por el sector
--    del batch (fact_batch_proceso.sector → dim_sector_nav.sector_batch).
--
--    OJO: la pantalla los muestra aparte y NO los suma al libro, a propósito. De los 17
--    que tienen ticket de portería, 3 tienen además un movimiento con tanque del mismo
--    ticket, así que parte de esa mercadería ya se descontó y sumarla también acá la
--    contaría dos veces. La corrección va en la carga: la producción tiene que decir de
--    qué tanque salió. Hasta entonces, el número es el tamaño de la duda.
--
-- Fuera de alcance por decisión de dirección (16/09): los sólidos que pasan por balanza
-- y no tienen sistema de stock (compost, residuos, decomiso, alimento balanceado, ganado,
-- tierra, barrido). Se cuentan en portería, no en stock.
-- ============================================================================

CREATE OR REPLACE FUNCTION produccion.fn_stock_saldo_todos(p_fecha date)
RETURNS TABLE(sector text, sector_nombre text, cuenta text, cuenta_nombre text, calidad text,
              corriente_nombre text, kg_neto numeric, litros_neto numeric,
              base_fecha date, base_fuente text)
LANGUAGE sql STABLE AS $$
  SELECT s.codigo, s.nombre_ui, f.cuenta, f.cuenta_nombre, f.calidad, f.corriente_nombre,
         f.kg_neto, f.litros_neto, f.base_fecha, f.base_fuente
    FROM produccion.dim_sector_nav s
    CROSS JOIN LATERAL produccion.fn_stock_saldo_a(s.codigo, p_fecha) f
   WHERE s.activo AND s.patron_tanques IS NOT NULL;
$$;

DROP VIEW IF EXISTS produccion.v_stock_sin_tanque;
CREATE VIEW produccion.v_stock_sin_tanque AS
SELECT s.codigo AS sector, s.nombre_ui AS sector_nombre,
       m.id_mov_stock AS id_mov, m.momento, m.momento::date AS fecha,
       produccion.fn_prod_label(COALESCE(m.producto, m.codigo_insumo)) AS producto,
       COALESCE(m.producto, m.codigo_insumo) AS producto_codigo,
       CASE m.rol WHEN 'MP' THEN 'MP' WHEN 'INSUMO' THEN 'INSUMO' WHEN 'CATALIZADOR' THEN 'INSUMO'
            WHEN 'PRODUCTO_FINAL' THEN 'PT' WHEN 'SUBPRODUCTO' THEN 'PT' ELSE 'OTRO' END AS grupo,
       m.tipo_movimiento AS tipo, m.ticket_porteria AS ticket,
       COALESCE(m.sentido::int, 1)::numeric * COALESCE(m.kg, 0)     AS kg_neto,
       COALESCE(m.sentido::int, 1)::numeric * COALESCE(m.litros, 0) AS litros_neto,
       m.origen AS fuente_dato, b.identificador_unidad AS op, m.observaciones AS observacion
  FROM produccion.fact_movimiento_stock m
  LEFT JOIN produccion.fact_batch_proceso b ON b.id_batch = m.id_batch
  LEFT JOIN produccion.dim_sector_nav s ON s.sector_batch = b.sector AND s.activo
 WHERE COALESCE(m.anulado, false) = false AND COALESCE(m.estado_mov, '') <> 'ANULADO'
   AND m.id_tanque IS NULL AND m.origen <> 'efluente_porteria';

GRANT SELECT ON produccion.v_stock_sin_tanque TO PUBLIC;

-- Control: el consolidado tiene que ser la suma exacta de lo que ve cada sector.
--   saldo inicial + movimientos del mes = lo que miden los tanques hoy, en cada sector y en el total
-- BACHAS 99,2 · EXPORTACION 1.171,5 · PILETAS 81,1 · REACTORES 988,8 → PLANTA 2.340,6 TN
