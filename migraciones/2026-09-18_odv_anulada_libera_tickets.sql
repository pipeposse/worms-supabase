-- ============================================================================
-- 2026-09-18 · Los tickets de exportación quedaban atrapados en órdenes de venta anuladas
--
-- Reporte: no aparecían tickets de expo que ya habían cerrado pesada, ni siquiera
-- después de tocar los botones de recarga.
--
-- Qué pasaba. La pantalla ofrece para imputar los tickets de portería que todavía no
-- están asignados a ninguna orden de venta. Ese control preguntaba solamente si el
-- ticket estaba asignado — no si la orden que lo tenía seguía viva. Al anular una ODV,
-- sus movimientos de stock se revierten, pero los tickets quedaban enganchados a ella
-- para siempre. Como fact_despacho_ticket tiene un único por id_transaccion, ese ticket
-- no se podía asignar a ninguna otra orden nunca más, y el INSERT con
-- ON CONFLICT DO NOTHING lo dejaba pasar en silencio: la pantalla decía "0 de N
-- asignados" sin explicar por qué.
--
-- La ODV 59 (VIROQUE ENERGY / EEUU, anulada el 17/09) tenía 8 tickets así: 184,3 TN de
-- ácido graso ya pesado y salido de planta que no se podían imputar a ningún lado.
--
-- Esta migración libera los que quedaron atrapados. El arreglo de fondo va en la app,
-- en tres puntos: el listado de candidatos ignora las asignaciones que cuelgan de una
-- ODV anulada, anular una ODV suelta sus tickets en el momento y lo informa, y al
-- asignar se libera primero cualquier retención de una ODV anulada.
-- ============================================================================

-- Control previo: qué tickets están atrapados y en qué órdenes.
SELECT d.id_despacho, d.titulo, d.cliente, d.fecha_despacho, d.estado,
       count(*) AS tickets,
       round((sum(abs(a.kg))/1000.0)::numeric, 1) AS tn,
       string_agg(a.ticket::text, ', ' ORDER BY a.ticket) AS lista
  FROM produccion.fact_despacho d
  JOIN produccion.fact_despacho_ticket a ON a.id_despacho = d.id_despacho
 WHERE COALESCE(d.estado,'') = 'ANULADO'
 GROUP BY 1,2,3,4,5;

-- Liberación. La pesada existió y el camión salió: el ticket tiene que poder imputarse
-- a otra orden. La orden anulada no lo necesita — no genera movimientos de stock.
DELETE FROM produccion.fact_despacho_ticket a
 USING produccion.fact_despacho d
 WHERE d.id_despacho = a.id_despacho
   AND COALESCE(d.estado,'') = 'ANULADO';

-- Control posterior: tiene que dar 0.
SELECT count(*) AS siguen_atrapados
  FROM produccion.fact_despacho_ticket a
  JOIN produccion.fact_despacho d ON d.id_despacho = a.id_despacho
 WHERE COALESCE(d.estado,'') = 'ANULADO';

-- Control: los tickets de salida libres que ahora ofrece la pantalla.
-- Esperado tras la corrida del 18/09: 12 tickets — los 8 de la ODV 59
-- (75598, 75599, 75606, 75608, 75648, 75649, 75655, 75656) más los 4 que nunca se
-- habían asignado (75670, 75672, 75673, 75674).
SELECT p.ticket, p.fecha, p.producto, p.destino, p.patente, p.kg
  FROM produccion.v_porteria_ticket p
  LEFT JOIN produccion.fact_despacho_ticket a ON a.id_transaccion = p.id_transaccion
  LEFT JOIN produccion.fact_despacho dd ON dd.id_despacho = a.id_despacho
 WHERE (a.id_transaccion IS NULL OR COALESCE(dd.estado,'') = 'ANULADO')
   AND p.clase = 'SALIDA'
   AND p.fecha BETWEEN current_date - 7 AND current_date + 7
 ORDER BY p.fecha, p.ticket;
