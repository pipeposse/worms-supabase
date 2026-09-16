-- =====================================================================================
-- AFE sin calidad no existe: es NO EVALUADO, y se puede ir a buscar el ticket
-- 16/09/2026
--
--  1. fn_cuenta_grado -> la familia AFE SIEMPRE lleva calidad. Si laboratorio todavía no la
--     evaluó, la cuenta es -NE (NO EVALUADO). Nunca queda una cuenta AFE sin grado.
--  2. v_stock_cuenta_sector -> lo mismo en cada movimiento.
--  3. v_stock_sin_evaluar -> qué hay esperando laboratorio: tanque, TN, y el ticket y el
--     proveedor del último ingreso, para ir a buscar la muestra.
-- =====================================================================================

CREATE OR REPLACE FUNCTION produccion.fn_cuenta_grado(p text, s numeric, f numeric)
RETURNS TABLE(cuenta text, cuenta_nombre text, calidad text, corriente text, corriente_nombre text)
LANGUAGE sql STABLE AS $$
  SELECT cp.cuenta || COALESCE('-' || g.gr, ''),
         cp.cuenta_nombre || COALESCE(' calidad ' || g.et, ''),
         COALESCE(g.et, cp.calidad), cp.corriente, cp.corriente_nombre
    FROM produccion.fn_cuenta_partes(p) cp
    LEFT JOIN LATERAL (
      SELECT CASE WHEN produccion.fn_categoria_afe(s, f) IN ('A','B','C','D')
                  THEN produccion.fn_categoria_afe(s, f) ELSE 'NE' END AS gr,
             CASE WHEN produccion.fn_categoria_afe(s, f) IN ('A','B','C','D')
                  THEN produccion.fn_categoria_afe(s, f) ELSE 'NO EVALUADO' END AS et
       WHERE upper(COALESCE(p,'')) LIKE 'AFE%') g ON true;
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
    LEFT JOIN pr c ON c.label = mv.producto
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

CREATE OR REPLACE VIEW produccion.v_stock_sin_evaluar AS
WITH tq AS (
  SELECT a.sector, a.id_tanque, a.tanque, a.grupo_fisico, a.producto_codigo, a.producto,
         a.act_tn, a.act_l, a.ultima_medicion, a.lab_actualizado_en
    FROM produccion.v_acopio_sector a
   WHERE a.activo AND a.condicion <> 'FUERA DE USO' AND COALESCE(a.act_l,0) > 0
     AND a.producto_codigo LIKE 'AFE%'
     AND a.azufre IS NULL AND a.fosforo IS NULL
), ult AS (
  SELECT DISTINCT ON (v.tanque) v.tanque, v.ticket, v.fecha, v.contraparte, v.kg_neto
    FROM produccion.v_stock_cuenta_sector v
   WHERE NOT v.es_ajuste_sistema AND v.kg_neto > 0
   ORDER BY v.tanque, v.fecha DESC, v.id_mov DESC
)
SELECT tq.sector, tq.tanque, tq.grupo_fisico, tq.producto, tq.producto_codigo,
       tq.act_tn AS tn, tq.ultima_medicion,
       u.ticket AS ultimo_ticket, u.fecha AS fecha_ultimo_ingreso,
       u.contraparte AS ultimo_proveedor,
       (current_date - u.fecha) AS dias_desde_el_ingreso
  FROM tq LEFT JOIN ult u ON u.tanque = tq.tanque;
COMMENT ON VIEW produccion.v_stock_sin_evaluar IS
 'Stock en tanque que laboratorio todavia no califico (cuenta NO EVALUADO), con el ticket del ultimo ingreso para ir a buscar la muestra.';

-- Despues de correr esto hay que rehacer el corte para que las cuentas queden con calidad:
-- SELECT * FROM produccion.fn_stock_cerrar_saldo_inicial(NULL, current_date, NULL);
