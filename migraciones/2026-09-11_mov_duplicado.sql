-- ============================================================================
-- Confirmaciones duplicadas en el ledger de stock
-- worms-prod · 2026-09-11 · aplicada
--
-- QUÉ PASÓ
-- El ticket 6653 de Recuperación AG entró CINCO veces con los mismos 6.580 kg
-- al tanque 73, las cinco dentro del mismo segundo (09:23:41.82 → 09:23:42.52).
-- Es un doble clic: la lógica de "reemplazar el ingreso anterior" anula sólo lo
-- que existía al abrir la transacción, así que los cinco inserts simultáneos no
-- se vieron entre sí y ninguno anuló a los otros. Resultado: 26.320 kg fantasma
-- de AG-C en el tanque 4.
--
-- Barrida completa de fact_movimiento_stock: es el único caso en toda la tabla
-- (12.000+ filas, 9 orígenes). No hay un problema sistémico, hay un agujero.
--
-- QUÉ SE HIZO
--   1. Se anularon las 4 filas sobrantes (12779..12782), se conservó la primera
--      (12778). Anuladas, no borradas, y con el motivo escrito en observaciones
--      + un evento por fila en aud_eventos.
--   2. Índice único parcial para que el circuito no pueda repetirlo.
--   3. Vista de detección + fila en la bandeja HOY para los circuitos que el
--      índice no cubre (lab_sync, asignacion_afe, despacho, decantacion), donde
--      un ticket SÍ puede legítimamente generar más de un movimiento y por eso
--      no se puede poner un índice: al menos que se vea el mismo día.
--
-- LO QUE FALTA (del lado de la app, no de la base)
-- El botón de confirmar en Recuperación AG sigue sin lock: ahora el segundo
-- clic va a chocar contra el índice y levantar una excepción. Hay que envolver
-- el INSERT en un try y tratar la violación de unicidad como "ya estaba hecho".
-- ============================================================================

-- ---------------------------------------------------------------- 1. limpieza
-- (ejecutada una sola vez; queda acá como registro de lo que se corrigió)
-- WITH dup AS (
--   SELECT id_mov_stock,
--          row_number() OVER (PARTITION BY origen, ticket_porteria, id_tanque, tipo_movimiento
--                             ORDER BY creado_en, id_mov_stock) AS rn
--   FROM produccion.fact_movimiento_stock
--   WHERE NOT anulado AND origen = 'recuperacion_ag'
--     AND regexp_replace(coalesce(ticket_porteria,''), '\.0+$', '') = '6653'
-- ), upd AS (
--   UPDATE produccion.fact_movimiento_stock m
--      SET anulado = true,
--          observaciones = coalesce(m.observaciones,'')
--            || ' | anulado 2026-09-11: confirmacion duplicada (doble clic), se conserva un solo ingreso'
--     FROM dup d
--    WHERE m.id_mov_stock = d.id_mov_stock AND d.rn > 1
--   RETURNING m.id_mov_stock, m.kg
-- )
-- INSERT INTO produccion.aud_eventos (id_usuario, operacion, tabla, pk_valor, cambios)
-- SELECT 1, 'U', 'fact_movimiento_stock', id_mov_stock::text,
--        jsonb_build_object('anulado','true','motivo','confirmacion_duplicada_ticket_6653','kg', kg::text)
-- FROM upd;

-- ---------------------------------------------------------------- 2. candado
-- Sólo para los circuitos donde un ticket equivale a UN movimiento. No se
-- extiende a lab_sync / despacho / asignacion_afe: ahí un mismo ticket puede
-- partirse en varias descargas al mismo tanque y el índice rompería la carga.
CREATE UNIQUE INDEX IF NOT EXISTS ux_mov_stock_ticket_unico
    ON produccion.fact_movimiento_stock (
        origen,
        regexp_replace(ticket_porteria, '\.0+$', ''),
        id_tanque,
        tipo_movimiento
    )
    WHERE NOT anulado
      AND ticket_porteria IS NOT NULL
      AND id_tanque IS NOT NULL
      AND origen IN ('recuperacion_ag', 'cambio_categoria');

COMMENT ON INDEX produccion.ux_mov_stock_ticket_unico IS
    'Un ticket de portería no puede generar dos ingresos vigentes al mismo tanque '
    'en los circuitos de confirmación (recuperacion_ag, cambio_categoria). '
    'Creado 2026-09-11 tras el duplicado x5 del ticket 6653.';

-- ---------------------------------------------------------------- 3. detección
CREATE OR REPLACE VIEW produccion.v_movimiento_duplicado AS
SELECT m.origen,
       regexp_replace(m.ticket_porteria, '\.0+$', '')      AS ticket,
       m.id_tanque,
       max(m.tanque_label)                                  AS tanque,
       max(m.producto)                                      AS producto,
       m.tipo_movimiento,
       count(*)                                             AS veces,
       (count(*) - 1)                                       AS sobrantes,
       round(sum(m.kg) - max(m.kg))                         AS kg_de_mas,
       min(m.creado_en)                                     AS primero,
       max(m.creado_en)                                     AS ultimo,
       round(extract(epoch FROM (max(m.creado_en) - min(m.creado_en))))::int AS segundos,
       array_agg(m.id_mov_stock ORDER BY m.creado_en)       AS ids
FROM produccion.fact_movimiento_stock m
WHERE NOT m.anulado
  AND coalesce(m.ticket_porteria, '') <> ''
  AND m.id_tanque IS NOT NULL
GROUP BY m.origen, regexp_replace(m.ticket_porteria, '\.0+$', ''), m.id_tanque, m.tipo_movimiento
HAVING count(*) > 1;

COMMENT ON VIEW produccion.v_movimiento_duplicado IS
    'Un mismo ticket cargado más de una vez al mismo tanque: kg fantasma en el ledger. '
    'Alimenta el pendiente MOV_DUPLICADO de la bandeja HOY.';

-- ---------------------------------------------------------------- 4. bandeja
CREATE OR REPLACE VIEW produccion.v_pendientes_mov_duplicado AS
SELECT 'MOV_DUPLICADO'::text                                   AS tipo,
       'MDUP:' || d.origen || ':' || d.ticket                  AS ref,
       d.veces::text                                           AS marca,
       1                                                       AS prioridad,
       'Ticket ' || d.ticket || ' cargado ' || d.veces || ' veces en ' || coalesce(d.tanque, 'un tanque') AS titulo,
       replace(to_char(d.kg_de_mas, 'FM999G999G999'), ',', '.')
         || ' kg de más en el stock de ' || coalesce(d.producto, 'ese producto')
         || ' · las ' || d.veces || ' cargas entraron en ' || d.segundos
         || CASE WHEN d.segundos = 1 THEN ' segundo' ELSE ' segundos' END
         || ' desde ' || d.origen || ' — hay que anular las que sobran'  AS detalle,
       'TANQUES'::text                                         AS seccion,
       NULL::text                                              AS vista,
       NULL::text                                              AS sector_nav,
       NULL::bigint                                            AS id_batch,
       NULL::text                                              AS op,
       d.ultimo                                                AS cuando,
       d.sobrantes                                             AS n
FROM produccion.v_movimiento_duplicado d;

-- v_pendientes suma el bloque con un UNION ALL contra v_pendientes_mov_duplicado
-- (ver 2026-09-11_pendientes_cierre.sql para la definición completa de la vista).
