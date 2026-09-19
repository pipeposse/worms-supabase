-- ============================================================================
-- 2026-09-19 · SOL-0049 · Cambiar el producto terminado en los desgomados de AFE-M
--
-- Pedido: "Cambiar producto terminado en procesos que se inician con AFE M. Producto
-- inicial AFE M, producto final AFE M".
--
-- El arreglo va en la app. Acá quedan los controles y, al final, la corrección de las
-- dos reacciones que ya están cargadas mal — que conviene hacer DESDE LA PANTALLA, no
-- con este SQL (ver por qué al pie).
--
-- Qué pasaba. La regla del producto final del desgomado estaba escrita al revés y daba
-- AFE-S para todo lo que no fuera girasol; se corrigió el 18/09, pero sólo para las
-- reacciones NUEVAS. Las que ya existían quedaron con AFE-S como producto terminado y
-- no había forma de cambiarlo: el producto final se elegía al planificar y después no
-- se podía tocar desde ningún lado.
--
-- Eso deja la reacción sin poder cerrarse. La pantalla de tickets finales ofrece sólo
-- los tickets que laboratorio evaluó como el producto terminado de la reacción: con
-- AFE-S, el ticket 6787 (AFE / M, 11.000 kg, 16/09) no aparecía. Por eso se intentó
-- cargarlo a mano — y por ahí tampoco servía: el alta manual también lo guardaba como
-- AFE-S, porque toma el producto de la reacción.
--
-- Son dos reacciones, las dos de maní y las dos ya terminadas:
--     RE-412 (15/09) — 6.740 kg de AFE-M → 6.403 kg en Cónico 1 como AFE-S
--     RE-413 (15/09) — 5.260 kg de AFE-M → 4.997 kg en Cónico 1 como AFE-S
-- Es decir 11.400 kg de AFE de maní que hoy figuran como AFE de soja en el Cónico 1.
--
-- Lo que se agregó a la app:
--  · En la ficha de reacción, pestaña "Tickets finales": "✏️ Cambiar el producto
--    terminado". Ofrece los productos finales habilitados para el proceso, avisa
--    cuántos kilos ya asentados van a cambiar de producto y en qué tanque, pide
--    confirmación, y corrige de una sola vez la reacción, sus movimientos de stock y
--    sus tickets ya asignados. Queda auditado con usuario y hora.
--  · El mismo panel en la pantalla de desgomado NUNCA se llegó a ver: se lo llamaba con
--    un argumento que la función no aceptaba, el error caía en un `except` y sólo
--    quedaba un cartelito gris "No se pudieron cargar los tickets finales". Ahora
--    funciona.
-- ============================================================================

-- Control 1: las reacciones de desgomado cuya materia prima no coincide con el producto
-- terminado. Regla: el desgomado devuelve lo mismo que entró, salvo AFE-SG que da AFE-S.
-- Esperado hoy: RE-412 y RE-413.
SELECT b.id_batch, b.identificador_unidad AS reaccion, b.estado,
       (SELECT string_agg(DISTINCT m.producto, ', ') FROM produccion.fact_movimiento_stock m
         WHERE m.id_batch = b.id_batch AND m.rol = 'MP' AND NOT COALESCE(m.anulado,false)) AS entro,
       dp.codigo_producto AS sale_hoy,
       (SELECT round(sum(m.kg)) FROM produccion.fact_movimiento_stock m
         WHERE m.id_batch = b.id_batch AND m.rol = 'PRODUCTO_FINAL'
           AND NOT COALESCE(m.anulado,false)) AS kg_asentados,
       (SELECT string_agg(DISTINCT dt.nombre, ', ') FROM produccion.fact_movimiento_stock m
          JOIN produccion.dim_tanque dt ON dt.id_tanque = m.id_tanque
         WHERE m.id_batch = b.id_batch AND m.rol = 'PRODUCTO_FINAL'
           AND NOT COALESCE(m.anulado,false)) AS en_tanque
  FROM produccion.fact_batch_proceso b
  LEFT JOIN produccion.dim_producto dp ON dp.id_producto = b.id_producto_buscado
 WHERE b.tipo_proceso = 'DESGOMADO_ACUOSO' AND NOT COALESCE(b.anulado,false)
   AND EXISTS (SELECT 1 FROM produccion.fact_movimiento_stock m
                WHERE m.id_batch = b.id_batch AND m.rol = 'MP'
                  AND NOT COALESCE(m.anulado,false)
                  AND upper(m.producto) NOT IN (dp.codigo_producto, 'AFE-SG'))
 ORDER BY b.id_batch;

-- Control 2: el ticket que no aparecía, y con qué producto lo evaluó laboratorio.
SELECT regexp_replace(tx.transaccion::text,'\.0+$','') AS ticket,
       tx.lab_producto, tx.lab_calidad, tx.evaluado,
       round(abs(tx.peso_neto)) AS kg, tx.fecha_entrada
  FROM produccion.v_transacciones_limpias tx
 WHERE regexp_replace(tx.transaccion::text,'\.0+$','') = '6787';

-- Control 3: qué hay hoy en el Cónico 1 y de qué reacción vino.
SELECT b.identificador_unidad AS reaccion, m.producto, round(m.kg) AS kg, round(m.litros) AS litros,
       to_char(m.momento AT TIME ZONE 'America/Argentina/Buenos_Aires','DD/MM HH24:MI') AS cuando
  FROM produccion.fact_movimiento_stock m
  JOIN produccion.fact_batch_proceso b ON b.id_batch = m.id_batch
 WHERE m.id_tanque = 43 AND m.rol = 'PRODUCTO_FINAL' AND NOT COALESCE(m.anulado,false)
 ORDER BY m.momento DESC;

-- ----------------------------------------------------------------------------
-- CORRECCIÓN DE LAS DOS REACCIONES. Preferible hacerla desde la pantalla: ficha de
-- RE-412 y RE-413 → pestaña "🏁 Tickets finales" → "✏️ Cambiar el producto terminado"
-- → AFE-M. Hace exactamente lo mismo que esto, pero queda auditado con usuario y hora,
-- y muestra los kilos que cambian antes de confirmar. Este SQL es el respaldo.
--
-- Mueve 11.400 kg del Cónico 1 de AFE-S a AFE-M. No inventa stock ni cambia kilos:
-- sólo corrige con qué nombre están anotados.
--
-- BEGIN;
-- UPDATE produccion.fact_batch_proceso
--    SET id_producto_buscado = (SELECT id_producto FROM produccion.dim_producto
--                                WHERE codigo_producto = 'AFE-M')
--  WHERE id_batch IN (227, 228);
-- UPDATE produccion.fact_movimiento_stock
--    SET id_producto = (SELECT id_producto FROM produccion.dim_producto
--                        WHERE codigo_producto = 'AFE-M'),
--        producto = 'AFE-M'
--  WHERE id_batch IN (227, 228) AND rol = 'PRODUCTO_FINAL' AND NOT COALESCE(anulado,false);
-- UPDATE produccion.fact_batch_ticket_final SET producto = 'AFE-M'
--  WHERE id_batch IN (227, 228) AND NOT COALESCE(anulado,false);
-- COMMIT;
--
-- Control posterior: las dos tienen que quedar entrando y saliendo AFE-M, y el Control 1
-- de arriba tiene que dar 0 filas.
-- SELECT b.identificador_unidad, dp.codigo_producto AS sale, round(sum(m.kg)) AS kg
--   FROM produccion.fact_batch_proceso b
--   JOIN produccion.dim_producto dp ON dp.id_producto = b.id_producto_buscado
--   LEFT JOIN produccion.fact_movimiento_stock m ON m.id_batch = b.id_batch
--        AND m.rol = 'PRODUCTO_FINAL' AND NOT COALESCE(m.anulado,false)
--  WHERE b.id_batch IN (227, 228) GROUP BY 1, 2 ORDER BY 1;

-- Aparte, para mirar con planta: la salida de RE-413 se asentó OCHO veces (siete quedaron
-- anuladas y una viva) y la de RE-410 cuatro. Es el mismo patrón de doble carga de la
-- pantalla de desgomado que ya se corrigió en exportación y en el instructivo: el click
-- se pierde, no cambia nada en pantalla y se vuelve a apretar.
SELECT b.identificador_unidad AS reaccion, count(*) AS veces_asentada,
       count(*) FILTER (WHERE COALESCE(m.anulado,false)) AS anuladas
  FROM produccion.fact_movimiento_stock m
  JOIN produccion.fact_batch_proceso b ON b.id_batch = m.id_batch
 WHERE m.rol = 'PRODUCTO_FINAL' AND b.tipo_proceso = 'DESGOMADO_ACUOSO'
 GROUP BY 1 HAVING count(*) > 2 ORDER BY 2 DESC;
