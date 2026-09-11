-- ============================================================================
-- FASE 7 · ítem 2 — DE DÓNDE SALIÓ LA MATERIA PRIMA DE CADA OP
--                                          · aplicada en worms-prod 2026-09-11
--   migraciones: op_origen_mp + op_origen_mp_match_tanque
-- ----------------------------------------------------------------------------
-- Ninguna de las 20 OP del mes tenía ticket de balanza. La primera lectura fue
-- "nadie completa el campo"; la real es otra: sólo 2 de 14 OP toman MP
-- directamente de portería. Las otras 12 la toman de un TANQUE, donde el ticket
-- de balanza no aplica — ese material entró días antes y casi siempre viene de
-- varios camiones. La meta "80 % de OP con ticket" era inalcanzable Y equivocada.
--
-- La trazabilidad no es un campo, es una cadena:
--     OP → línea de MP → (ticket directo | tanque → camiones que lo llenaron)
--
-- Para el tramo del tanque esto es ORIGEN PROBABLE, no un lote identificado: se
-- listan las entradas al tanque anteriores al consumo, de la más nueva hacia
-- atrás, hasta cubrir los kg consumidos. Si el tanque tenía saldo previo mezclado
-- (lo normal), el lote exacto no existe y la vista no lo inventa.
--
-- tanque_label viene en TRES formatos según quién escribió el movimiento:
--   "Tanque 4"      (recuperacion_ag) → nombre
--   "RXA-TANQUE-4"  (lab_sync)        → código      ← por acá entra la MP de camión
--   "49 · Cónico 7" (asignacion_afe)  → id · nombre
-- El join sólo por nombre dejaba fuera a lab_sync y hundía la cobertura.
--
-- Resultado: 0 % → 75 % de OP trazadas (15 de 20) sin cargar un dato nuevo.
-- Las 5 que faltan usan "Tanque materia prima 3/4" (Reactores Proceso), que NUNCA
-- registraron una entrada: se llenan por trasvase interno desde acopio y ese
-- movimiento no existe en el sistema. Ahí la cadena se corta de verdad, y para
-- cerrarla hay que registrar el trasvase — no hay nada que inferir.
-- ============================================================================
CREATE OR REPLACE VIEW produccion.v_op_origen_mp AS
WITH mp AS (
    SELECT i.id_batch_insumo, i.id_batch, b.identificador_unidad AS op, b.fecha AS fecha_op,
           b.creado_en AS momento_op, b.sector, b.tipo_proceso,
           p.codigo_producto AS producto, i.cantidad AS kg, i.fuente, i.id_tanque,
           i.ticket_porteria AS ticket_directo, t.nombre AS tanque
    FROM produccion.fact_batch_insumo i
    JOIN produccion.fact_batch_proceso b ON b.id_batch = i.id_batch AND NOT b.anulado
    LEFT JOIN produccion.dim_producto p ON p.id_producto = i.id_producto
    LEFT JOIN produccion.dim_tanque  t ON t.id_tanque = i.id_tanque
    WHERE i.rol = 'MP' AND NOT i.anulado
),
ent AS (
    SELECT DISTINCT dt.id_tanque, m.momento, m.ticket_porteria, m.producto, m.kg_neto
    FROM reporting.v_movimientos_stock m
    JOIN produccion.dim_tanque dt
      ON dt.codigo = m.tanque_label
      OR dt.nombre = m.tanque_label
      OR (dt.id_tanque::text || ' · ' || dt.nombre) = m.tanque_label
    WHERE m.tipo_movimiento = 'ENTRADA'
      AND COALESCE(m.ticket_porteria, '') <> ''
      AND COALESCE(m.kg_neto, 0) > 0
      AND m.estado_mov = 'EJECUTADO'
),
cad AS (
    SELECT mp.id_batch_insumo, e.ticket_porteria, e.momento, e.kg_neto,
           SUM(e.kg_neto) OVER (PARTITION BY mp.id_batch_insumo ORDER BY e.momento DESC
                                ROWS UNBOUNDED PRECEDING) AS acum,
           mp.kg AS kg_consumidos
    FROM mp
    JOIN ent e ON e.id_tanque = mp.id_tanque AND e.momento <= mp.momento_op
    WHERE mp.fuente = 'TANQUE' AND mp.id_tanque IS NOT NULL
),
cubre AS (
    SELECT id_batch_insumo,
           string_agg(DISTINCT ticket_porteria, ', ') AS tickets_probables,
           count(DISTINCT ticket_porteria) AS n_tickets,
           max(kg_consumidos) - SUM(kg_neto) AS kg_sin_cubrir,
           min(momento) AS entrada_mas_vieja, max(momento) AS entrada_mas_nueva
    FROM (SELECT *, COALESCE(LAG(acum) OVER (PARTITION BY id_batch_insumo ORDER BY momento DESC), 0) AS acum_prev
          FROM cad) x
    WHERE acum_prev < kg_consumidos          -- incluye la entrada que cruza el umbral
    GROUP BY id_batch_insumo
)
SELECT mp.id_batch, mp.op, mp.fecha_op, mp.sector, mp.tipo_proceso,
       mp.id_batch_insumo, mp.producto, mp.kg, mp.fuente, mp.tanque, mp.ticket_directo,
       c.tickets_probables, c.n_tickets, GREATEST(c.kg_sin_cubrir, 0) AS kg_sin_cubrir,
       c.entrada_mas_vieja, c.entrada_mas_nueva,
       CASE
         WHEN COALESCE(mp.ticket_directo, '') <> '' THEN 'TICKET'
         WHEN c.tickets_probables IS NOT NULL       THEN 'TANQUE_TRAZADO'
         WHEN mp.id_tanque IS NOT NULL              THEN 'TANQUE_SIN_TRAZA'
         ELSE 'SIN_ORIGEN'
       END AS origen,
       COALESCE(NULLIF(mp.ticket_directo, ''), c.tickets_probables) AS tickets
FROM mp
LEFT JOIN cubre c ON c.id_batch_insumo = mp.id_batch_insumo;

COMMENT ON VIEW produccion.v_op_origen_mp IS
  'De dónde salió la materia prima de cada OP. origen: TICKET (pesaje directo de balanza), TANQUE_TRAZADO (los camiones que llenaron ese tanque antes del consumo — probable, no lote identificado), TANQUE_SIN_TRAZA (el tanque no tiene entradas con ticket) o SIN_ORIGEN.';

CREATE OR REPLACE VIEW produccion.v_op_trazabilidad AS
SELECT id_batch, op, fecha_op, sector, tipo_proceso,
       count(*) AS lineas_mp,
       count(*) FILTER (WHERE origen = 'TICKET')            AS con_ticket,
       count(*) FILTER (WHERE origen = 'TANQUE_TRAZADO')    AS con_tanque_trazado,
       count(*) FILTER (WHERE origen IN ('TANQUE_SIN_TRAZA','SIN_ORIGEN')) AS sin_origen,
       string_agg(DISTINCT tickets, ' · ') FILTER (WHERE tickets IS NOT NULL) AS tickets,
       (count(*) FILTER (WHERE origen IN ('TICKET','TANQUE_TRAZADO')) = count(*)) AS trazada
FROM produccion.v_op_origen_mp
GROUP BY 1,2,3,4,5;

COMMENT ON VIEW produccion.v_op_trazabilidad IS
  'Una fila por OP: trazada = todas sus líneas de materia prima tienen origen identificado (ticket de balanza o tanque con entradas trazadas).';
