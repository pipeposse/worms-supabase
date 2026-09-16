-- =====================================================================================
-- Por qué un tanque quedó NO EVALUADO
-- 16/09/2026
--
-- Casi todos los tanques tienen evaluación: 50 de 53 tanques de familia AFE en uso. Los que
-- caen en NO EVALUADO son la excepción, así que la vista ahora explica el motivo en vez de
-- sólo listarlos: hace cuánto se dio de alta el tanque, cuántos ingresos tiene cargados
-- (sin contar ajustes del sistema), con qué método se midió y si la medición quedó justo al
-- tope de la capacidad — señal de que se cargó como "lleno" en lugar de medirse.
-- =====================================================================================

DROP VIEW IF EXISTS produccion.v_stock_sin_evaluar;
CREATE VIEW produccion.v_stock_sin_evaluar AS
WITH tq AS (
  SELECT a.sector, a.id_tanque, a.tanque, a.grupo_fisico, a.producto_codigo, a.producto,
         a.act_tn, a.act_l, a.cap_l, a.ultima_medicion, a.metodo_medicion
    FROM produccion.v_acopio_sector a
   WHERE a.activo AND a.condicion <> 'FUERA DE USO' AND COALESCE(a.act_l,0) > 0
     AND a.producto_codigo LIKE 'AFE%'
     AND a.azufre IS NULL AND a.fosforo IS NULL
), ult AS (
  SELECT DISTINCT ON (v.tanque) v.tanque, v.ticket, v.fecha, v.contraparte
    FROM produccion.v_stock_cuenta_sector v
   WHERE NOT v.es_ajuste_sistema AND v.kg_neto > 0
   ORDER BY v.tanque, v.fecha DESC, v.id_mov DESC
)
SELECT tq.sector, tq.tanque, tq.grupo_fisico, tq.producto, tq.producto_codigo,
       tq.act_tn AS tn, tq.ultima_medicion, tq.metodo_medicion,
       u.ticket AS ultimo_ticket, u.fecha AS fecha_ultimo_ingreso,
       u.contraparte AS ultimo_proveedor,
       (current_date - u.fecha) AS dias_desde_el_ingreso,
       t.creado_en::date AS tanque_dado_de_alta,
       (current_date - t.creado_en::date) AS dias_de_alta,
       (SELECT count(*) FROM produccion.fact_movimiento_stock m
         WHERE m.id_tanque = tq.id_tanque AND COALESCE(m.anulado,false) = false
           AND m.tipo_movimiento <> 'AJUSTE')::int AS movimientos_reales,
       (COALESCE(tq.cap_l,0) > 0 AND abs(tq.act_l - tq.cap_l) < 1) AS medicion_al_tope
  FROM tq
  LEFT JOIN ult u ON u.tanque = tq.tanque
  LEFT JOIN produccion.dim_tanque t ON t.id_tanque = tq.id_tanque;
COMMENT ON VIEW produccion.v_stock_sin_evaluar IS
 'Stock en tanque que laboratorio todavia no califico (cuenta NO EVALUADO), con el motivo: alta del tanque, ingresos cargados, metodo de medicion y si quedo justo al tope de capacidad.';
