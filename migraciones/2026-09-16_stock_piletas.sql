-- ============================================================================
-- 2026-09-16 · Stock de PILETAS (recuperación de AG)
--
-- Pedido: "replicá la misma sección de stock en piletas; usualmente sólo vamos a ver
-- recuperación de AG con sus tickets de pesadas y tanques asignados".
--
-- 1) El efluente líquido que entra por portería para DISPOSICIÓN FINAL no es stock del
--    sector: son camiones que se vuelcan en las piletas de tratamiento y no vuelven a
--    salir como mercadería. Estaban entrando a la cuenta corriente como 53.942 TN de
--    ingresos sin un solo egreso, y por eso el saldo inicial de Piletas daba -10.967 TN.
--    Se marcan con es_stock = false: se siguen viendo (sector Piletas, Disp. Final
--    Líquidos, laboratorio), pero no forman parte del libro de stock ni del saldo inicial.
--
-- 2) es_del_sector comparaba una cuenta SIN calidad (V-AFE-S) contra las cuentas CON
--    calidad del sector (V-AFE-S-A), así que daba false para todo. Se compara por
--    producto, que es lo que define si el producto es del sector.
--
-- 3) v_stock_medido_cuenta: qué tanques tiene asignados hoy cada cuenta y cuánto miden.
--    Es lo que permite mostrar "entró el ticket 6766 al Tanque X10 y el tanque hoy mide X"
--    y comparar el libro contra la planta producto por producto.
--
-- Después de aplicar: el saldo inicial de Piletas queda en -237,6 TN. Ese número YA NO es
-- un artefacto: son 290,9 TN que entraron pesadas por portería a tanques de Piletas en
-- septiembre (AFE-S 249,4 · AFE-SG 36,0 · AG-C 5,5) y se movieron a otro sector sin que
-- nadie asentara la salida. La pantalla lo muestra como lo que es, no lo esconde.
-- ============================================================================

-- 1 + 2 ----------------------------------------------------------------------
DO $$
DECLARE d text := pg_get_viewdef('produccion.v_stock_cuenta_sector'::regclass, true);
BEGIN
  d := regexp_replace(d,
        'ps\.sector = m\.sector AND ps\.cuenta = COALESCE\(m\.cuenta_base, m\.producto\)',
        'ps.sector = m.sector AND ps.producto_codigo = m.producto_codigo');
  d := regexp_replace(d, 'AS es_del_sector\s*FROM m;',
        'AS es_del_sector, (m.fuente_dato <> ''efluente_porteria'') AS es_stock FROM m;');
  IF d NOT LIKE '%es_stock%' THEN RAISE EXCEPTION 'no se pudo agregar es_stock'; END IF;
  IF d LIKE '%m.cuenta_base, m.producto))%' THEN RAISE EXCEPTION 'no se pudo corregir es_del_sector'; END IF;
  EXECUTE 'CREATE OR REPLACE VIEW produccion.v_stock_cuenta_sector AS ' || d;
END $$;

-- El saldo inicial y el arrastre sólo cuentan lo que es stock.
DO $$
DECLARE f text;
BEGIN
  SELECT pg_get_functiondef(p.oid) INTO f FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
   WHERE n.nspname = 'produccion' AND p.proname = 'fn_stock_cerrar_saldo_inicial';
  f := replace(f, 'WHERE v.fecha >= v_fecha AND v.fecha <= current_date AND NOT v.es_ajuste_sistema',
                  'WHERE v.fecha >= v_fecha AND v.fecha <= current_date AND NOT v.es_ajuste_sistema AND v.es_stock');
  IF f NOT LIKE '%AND v.es_stock%' THEN RAISE EXCEPTION 'cerrar_saldo_inicial sin parchear'; END IF;
  EXECUTE f;

  SELECT pg_get_functiondef(p.oid) INTO f FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
   WHERE n.nspname = 'produccion' AND p.proname = 'fn_stock_saldo_a';
  f := replace(f, 'WHERE v.sector = p_sector AND NOT v.es_ajuste_sistema',
                  'WHERE v.sector = p_sector AND NOT v.es_ajuste_sistema AND v.es_stock');
  IF f NOT LIKE '%AND v.es_stock%' THEN RAISE EXCEPTION 'saldo_a sin parchear'; END IF;
  EXECUTE f;
END $$;

-- 3 --------------------------------------------------------------------------
DROP VIEW IF EXISTS produccion.v_stock_medido_cuenta;
CREATE VIEW produccion.v_stock_medido_cuenta AS
SELECT a.sector,
       cp.cuenta,
       count(*)::int                                            AS tanques,
       count(*) FILTER (WHERE COALESCE(a.act_l,0) > 0)::int      AS tanques_con_producto,
       string_agg(a.tanque, ', ' ORDER BY a.tanque)              AS tanques_txt,
       string_agg(a.tanque, ', ' ORDER BY a.act_l DESC)
         FILTER (WHERE COALESCE(a.act_l,0) > 0)                  AS tanques_con_producto_txt,
       COALESCE(SUM(a.act_tn), 0)::numeric                       AS tn,
       COALESCE(SUM(a.act_l), 0)::numeric / 1000.0               AS kl
  FROM produccion.v_acopio_sector a
  JOIN LATERAL produccion.fn_cuenta_grado(a.producto_codigo, a.azufre, a.fosforo) cp ON true
 WHERE a.producto_codigo IS NOT NULL AND a.activo AND a.condicion <> 'FUERA DE USO'
 GROUP BY a.sector, cp.cuenta;

GRANT SELECT ON produccion.v_stock_medido_cuenta TO PUBLIC;

-- Limpieza: el corte viejo de Piletas tenía la cuenta del efluente (-10.967,9 TN).
DELETE FROM produccion.fact_stock_saldo_inicial WHERE cuenta = 'DISPOSICION FINAL DE LIQUIDOS';

-- Y se rehace el corte de todos los sectores con la regla nueva.
SELECT * FROM produccion.fn_stock_cerrar_saldo_inicial(NULL, current_date, NULL);

-- Control: los cuatro sectores tienen que cerrar en 0,00.
--   saldo inicial + movimientos del mes = lo que miden los tanques hoy
-- BACHAS 99,2 · EXPORTACION 1.171,5 · PILETAS 81,1 · REACTORES 988,8
