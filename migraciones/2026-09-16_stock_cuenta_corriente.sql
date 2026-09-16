-- =====================================================================================
-- Stock por sector con el modelo de dirección: cuenta corriente por producto
-- 16/09/2026
--
--  1. fn_cuenta_partes(producto)  -> el código de cuenta: corriente + producto + calidad
--                                    (V-AFE-S, V-AG-E, A-ARE-A). Una sola regla para toda la app.
--  2. v_producto_sector           -> qué productos maneja cada sector: los de SUS tanques.
--                                    Es lo que impide que un sector vea stock ajeno.
--  3. v_stock_cuenta_sector       -> cada movimiento con su cuenta y la marca es_del_sector.
--  4. fact_stock_saldo_inicial    -> el stock del PRIMER DÍA HÁBIL de cada mes, por producto.
--  5. fn_stock_cerrar_saldo_inicial -> lo calcula y lo graba (medición de tanques).
--  6. fn_stock_saldo_a            -> el saldo a una fecha, corriendo desde el corte más cercano.
--  7. cron stock_corte_mensual    -> lo cierra solo el primer día hábil, 03:30 ART.
--
-- Todo idempotente: se puede volver a correr.
-- =====================================================================================

-- 1 ----------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION produccion.fn_cuenta_partes(p text)
RETURNS TABLE(cuenta text, cuenta_nombre text, calidad text, corriente text, corriente_nombre text)
LANGUAGE sql STABLE AS $$
  WITH d AS (
    SELECT dp.codigo_producto, dp.corriente,
           COALESCE(NULLIF(btrim(dp.rotulo_oficial), ''), dp.codigo_producto) AS rotulo_oficial,
           (SELECT m.calidad FROM produccion.dim_maestro_producto m
             WHERE upper(m.codigo_oficial) = upper(dp.codigo_producto) AND m.activo
             ORDER BY (upper(COALESCE(m.rotulo_oficial,'')) = upper(COALESCE(dp.rotulo_oficial,''))) DESC,
                      (m.calidad IS NULL), m.id
             LIMIT 1) AS cal
      FROM produccion.dim_producto dp
     WHERE upper(dp.codigo_producto) = upper(btrim(p))
     LIMIT 1
  ), c AS (
    SELECT d.*,
      CASE d.corriente WHEN 'VEGETAL' THEN 'V-' WHEN 'ANIMAL' THEN 'A-' ELSE '' END AS pfx,
      CASE WHEN d.rotulo_oficial ~* '^AN-' THEN regexp_replace(d.rotulo_oficial, '^AN-', '', 'i')
           ELSE d.rotulo_oficial END AS base,
      CASE WHEN d.cal IS NULL OR upper(d.cal) IN ('ACEPTADO','RECHAZADO','SIN DATO','UNICA','LIQUIDO')
           THEN NULL ELSE d.cal END AS grado
    FROM d
  ), x AS (
    SELECT c.*, (c.grado IS NOT NULL
                 AND c.base !~* ('-' || c.grado || '$')
                 AND c.base !~* '-([A-E]|1RA|2DA|P[0-9])$') AS agregar
    FROM c
  )
  SELECT x.pfx || x.base || CASE WHEN x.agregar THEN '-' || upper(x.grado) ELSE '' END,
         x.base || CASE WHEN x.agregar THEN ' calidad ' || upper(x.grado) ELSE '' END,
         CASE WHEN x.agregar THEN upper(x.grado)
              ELSE COALESCE(upper(substring(x.base from '-([A-Ea-e])$')), upper(x.grado)) END,
         x.corriente,
         CASE x.corriente WHEN 'VEGETAL' THEN 'Vegetal' WHEN 'ANIMAL' THEN 'Animal'
              WHEN 'INSUMO' THEN 'Insumo' ELSE COALESCE(initcap(x.corriente), '—') END
  FROM x;
$$;

-- 2 ----------------------------------------------------------------------------------
CREATE OR REPLACE VIEW produccion.v_producto_sector AS
SELECT a.sector,
       (produccion.fn_cuenta_partes(a.producto_codigo)).cuenta AS cuenta,
       a.producto_codigo,
       count(*)::int AS tanques,
       count(*) FILTER (WHERE a.activo AND a.condicion <> 'FUERA DE USO')::int AS tanques_en_uso
  FROM produccion.v_acopio_sector a
 WHERE a.producto_codigo IS NOT NULL
 GROUP BY 1, 2, 3;
COMMENT ON VIEW produccion.v_producto_sector IS
 'Productos que maneja cada sector (los de sus tanques). Filtra que un sector no vea stock de productos ajenos.';

-- 3 ----------------------------------------------------------------------------------
CREATE OR REPLACE VIEW produccion.v_stock_cuenta_sector AS
WITH pr AS (
  SELECT DISTINCT ON (produccion.fn_prod_label(p.codigo_producto))
         produccion.fn_prod_label(p.codigo_producto) AS label,
         p.codigo_producto, COALESCE(p.densidad_g_ml, 0.92) AS densidad,
         cp.cuenta, cp.cuenta_nombre, cp.calidad, cp.corriente, cp.corriente_nombre
    FROM produccion.dim_producto p
    LEFT JOIN LATERAL produccion.fn_cuenta_partes(p.codigo_producto) cp ON true
   ORDER BY produccion.fn_prod_label(p.codigo_producto), p.codigo_producto
)
SELECT m.*,
       c.codigo_producto AS producto_codigo, c.corriente, c.densidad, c.calidad,
       COALESCE(c.cuenta, m.producto) AS cuenta,
       COALESCE(c.cuenta_nombre, m.producto) AS cuenta_nombre,
       COALESCE(c.corriente_nombre, '—') AS corriente_nombre,
       EXISTS (SELECT 1 FROM produccion.v_producto_sector ps
                WHERE ps.sector = m.sector AND ps.cuenta = COALESCE(c.cuenta, m.producto)) AS es_del_sector
  FROM produccion.v_movimiento_sector m
  LEFT JOIN pr c ON c.label = m.producto;

-- 4 ----------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.fact_stock_saldo_inicial (
  id bigserial PRIMARY KEY,
  sector text NOT NULL, fecha date NOT NULL, cuenta text NOT NULL,
  cuenta_nombre text, calidad text, corriente text,
  kg numeric NOT NULL DEFAULT 0, litros numeric NOT NULL DEFAULT 0,
  fuente text NOT NULL DEFAULT 'MEDICION_TANQUES',
  tanques_n integer, observacion text, id_usuario bigint,
  creado_en timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fact_stock_saldo_inicial_uq UNIQUE (sector, fecha, cuenta),
  CONSTRAINT fact_stock_saldo_inicial_fuente_check
    CHECK (fuente IN ('MEDICION_TANQUES','MANUAL','AJUSTE_DIRECCION'))
);
CREATE INDEX IF NOT EXISTS fact_stock_saldo_inicial_idx
  ON produccion.fact_stock_saldo_inicial (sector, fecha DESC);

-- 5 ----------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION produccion.fn_primer_dia_habil(p_fecha date DEFAULT NULL)
RETURNS date LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE extract(isodow FROM d)::int WHEN 6 THEN d + 2 WHEN 7 THEN d + 1 ELSE d END
    FROM (SELECT date_trunc('month', COALESCE(p_fecha, current_date))::date AS d) s;
$$;

DROP FUNCTION IF EXISTS produccion.fn_stock_cerrar_saldo_inicial(text,date,bigint);
CREATE FUNCTION produccion.fn_stock_cerrar_saldo_inicial(
  p_sector text DEFAULT NULL, p_fecha date DEFAULT NULL, p_id_usuario bigint DEFAULT NULL)
RETURNS TABLE(r_sector text, r_fecha date, r_cuentas integer, r_tn numeric)
LANGUAGE plpgsql AS $$
DECLARE v_fecha date := produccion.fn_primer_dia_habil(COALESCE(p_fecha, current_date));
BEGIN
  INSERT INTO produccion.fact_stock_saldo_inicial
        (sector, fecha, cuenta, cuenta_nombre, calidad, corriente, kg, litros, fuente, tanques_n,
         observacion, id_usuario)
  WITH med AS (
    SELECT a.sector, cp.cuenta, cp.cuenta_nombre, cp.calidad, cp.corriente,
           SUM(a.act_l * a.densidad) AS kg, SUM(a.act_l) AS litros, COUNT(*)::int AS tanques
      FROM produccion.v_acopio_sector a
      JOIN LATERAL produccion.fn_cuenta_partes(a.producto_codigo) cp ON true
     WHERE a.activo AND a.condicion <> 'FUERA DE USO' AND COALESCE(a.act_l,0) > 0
       AND (p_sector IS NULL OR a.sector = p_sector)
     GROUP BY 1,2,3,4,5
  ), mov AS (
    SELECT v.sector, v.cuenta, SUM(v.kg_neto) AS kg, SUM(v.litros_neto) AS litros
      FROM produccion.v_stock_cuenta_sector v
     WHERE v.fecha >= v_fecha AND v.fecha <= current_date
       AND NOT v.es_ajuste_sistema AND v.es_del_sector
       AND (p_sector IS NULL OR v.sector = p_sector)
     GROUP BY 1,2
  )
  SELECT m.sector, v_fecha, m.cuenta, m.cuenta_nombre, m.calidad, m.corriente,
         m.kg - COALESCE(mv.kg, 0), m.litros - COALESCE(mv.litros, 0),
         'MEDICION_TANQUES', m.tanques,
         CASE WHEN v_fecha = current_date
              THEN 'Corte del dia: medicion fisica de los tanques del sector'
              ELSE 'Corte reconstruido: medicion de hoy menos los movimientos desde el ' ||
                   to_char(v_fecha, 'DD/MM/YYYY') END,
         p_id_usuario
    FROM med m LEFT JOIN mov mv ON mv.sector = m.sector AND mv.cuenta = m.cuenta
  ON CONFLICT (sector, fecha, cuenta) DO UPDATE
     SET kg = EXCLUDED.kg, litros = EXCLUDED.litros, cuenta_nombre = EXCLUDED.cuenta_nombre,
         calidad = EXCLUDED.calidad, corriente = EXCLUDED.corriente, fuente = EXCLUDED.fuente,
         tanques_n = EXCLUDED.tanques_n, observacion = EXCLUDED.observacion,
         id_usuario = EXCLUDED.id_usuario, creado_en = now();

  RETURN QUERY
  SELECT s.sector, s.fecha, COUNT(*)::integer, ROUND(SUM(s.kg)/1000.0, 1)
    FROM produccion.fact_stock_saldo_inicial s
   WHERE s.fecha = v_fecha AND (p_sector IS NULL OR s.sector = p_sector)
   GROUP BY s.sector, s.fecha;
END;
$$;

-- 6 ----------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION produccion.fn_stock_saldo_a(p_sector text, p_fecha date)
RETURNS TABLE(cuenta text, cuenta_nombre text, calidad text, corriente_nombre text,
              kg_neto numeric, litros_neto numeric, base_fecha date, base_fuente text)
LANGUAGE sql STABLE AS $$
  WITH base AS (
    SELECT s.fecha AS f FROM produccion.fact_stock_saldo_inicial s
     WHERE s.sector = p_sector ORDER BY abs(s.fecha - p_fecha), s.fecha DESC LIMIT 1
  ), ini AS (
    SELECT s.cuenta, s.cuenta_nombre, s.calidad, s.corriente, s.kg, s.litros
      FROM produccion.fact_stock_saldo_inicial s, base
     WHERE s.sector = p_sector AND s.fecha = base.f
  ), mov AS (
    SELECT v.cuenta, v.cuenta_nombre, v.calidad, v.corriente_nombre,
           SUM(v.kg_neto)     * CASE WHEN (SELECT f FROM base) > p_fecha THEN -1 ELSE 1 END AS kg,
           SUM(v.litros_neto) * CASE WHEN (SELECT f FROM base) > p_fecha THEN -1 ELSE 1 END AS l
      FROM produccion.v_stock_cuenta_sector v, base
     WHERE v.sector = p_sector AND NOT v.es_ajuste_sistema AND v.es_del_sector
       AND (CASE WHEN base.f IS NULL    THEN v.fecha < p_fecha
                 WHEN base.f <= p_fecha THEN v.fecha >= base.f AND v.fecha < p_fecha
                 ELSE                        v.fecha >= p_fecha AND v.fecha < base.f END)
     GROUP BY 1,2,3,4
  ), u AS (
    SELECT COALESCE(m.cuenta, i.cuenta) AS cuenta,
           COALESCE(m.cuenta_nombre, i.cuenta_nombre) AS cuenta_nombre,
           COALESCE(m.calidad, i.calidad) AS calidad,
           COALESCE(m.corriente_nombre,
                    CASE i.corriente WHEN 'VEGETAL' THEN 'Vegetal' WHEN 'ANIMAL' THEN 'Animal'
                         WHEN 'INSUMO' THEN 'Insumo' ELSE COALESCE(initcap(i.corriente), '—') END) AS corriente_nombre,
           COALESCE(i.kg, 0) + COALESCE(m.kg, 0) AS kg,
           COALESCE(i.litros, 0) + COALESCE(m.l, 0) AS l
      FROM mov m FULL JOIN ini i ON i.cuenta = m.cuenta
  )
  SELECT u.cuenta, u.cuenta_nombre, u.calidad, u.corriente_nombre, u.kg, u.l,
         (SELECT f FROM base),
         (SELECT CASE WHEN f IS NULL THEN 'LIBRE' WHEN f > p_fecha THEN 'CORTE_POST' ELSE 'CORTE' END FROM base)
    FROM u
   WHERE u.cuenta IS NOT NULL
     AND EXISTS (SELECT 1 FROM produccion.v_producto_sector ps
                  WHERE ps.sector = p_sector AND ps.cuenta = u.cuenta);
$$;

-- 7 ----------------------------------------------------------------------------------
SELECT cron.unschedule('stock_corte_mensual')
 WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'stock_corte_mensual');
SELECT cron.schedule('stock_corte_mensual', '30 6 1-3 * *',
$cron$
select produccion.fn_stock_cerrar_saldo_inicial(NULL, (now() AT TIME ZONE 'America/Argentina/Buenos_Aires')::date, NULL)
 where (now() AT TIME ZONE 'America/Argentina/Buenos_Aires')::date
     = produccion.fn_primer_dia_habil((now() AT TIME ZONE 'America/Argentina/Buenos_Aires')::date)
$cron$);

-- Primer cierre (ya ejecutado el 15/09/2026):
-- SELECT * FROM produccion.fn_stock_cerrar_saldo_inicial(NULL, current_date, NULL);
