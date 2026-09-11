-- ============================================================================
-- FASE 7 · ítem 1 — RECONCILIAR LABORATORIO: lo pedido contra lo entregado
--                                          · aplicada en worms-prod 2026-09-11
-- ----------------------------------------------------------------------------
-- El problema (medido 11/09/2026): el laboratorio cargó 1.230 evaluaciones en 30
-- días y produccion.fact_ticket_lab tiene 0 evaluados de 117. No es que el lab no
-- trabaje: son dos tablas que hablan del mismo hecho y nunca se miran. Resultado:
-- una cola de 102 "pendientes" que sólo crece, y un contador falso en la bandeja HOY.
--
-- Tres caminos para atar un pedido con su resultado, en orden de confianza:
--   CODIGO    el lab escribió el código del ticket (F30, R101) en lab_evaluaciones.ticket.
--             Ya pasa hoy, a mano, en 20 de los 31 tickets de producto final.
--   PORTERIA  el ticket nació de un pesaje de balanza y el lab evaluó ese mismo ticket.
--   TANQUE    el ticket salió de un tanque y el lab midió ESE tanque en la ventana
--             [-12 h, +96 h] del pedido. Es inferencia, no identidad: por eso queda
--             en confianza MEDIA (si además coincide la familia de producto) o BAJA.
--
-- Cobertura sobre los 102 pendientes de hoy: 54 reconciliables (31 tanque, 20 código,
-- 3 portería). Los otros 48 son muestras que realmente faltan — y ése, no 102, es el
-- número que tiene que ver un supervisor.
--
-- La vista es la verdad calculada y no toca datos. La función materializa el cierre
-- sólo para confianza ALTA y MEDIA; lo inferido flojo queda propuesto, nunca cerrado
-- solo. Revertir: UPDATE ... SET estado='PENDIENTE', evaluado_en=NULL WHERE conciliado_via IS NOT NULL.
-- ============================================================================
ALTER TABLE produccion.fact_ticket_lab ADD COLUMN IF NOT EXISTS id_lab_evaluacion bigint;
ALTER TABLE produccion.fact_ticket_lab ADD COLUMN IF NOT EXISTS conciliado_via    text;
ALTER TABLE produccion.fact_ticket_lab ADD COLUMN IF NOT EXISTS conciliado_en     timestamptz;
COMMENT ON COLUMN produccion.fact_ticket_lab.conciliado_via IS
  'Cómo se ató este pedido a su resultado: CODIGO (el lab escribió el código del ticket), PORTERIA (mismo ticket de balanza) o TANQUE (el lab midió ese tanque en la ventana del pedido).';

CREATE INDEX IF NOT EXISTS ix_lab_eval_ticket  ON produccion.lab_evaluaciones (ticket);
CREATE INDEX IF NOT EXISTS ix_lab_eval_tanque1 ON produccion.lab_evaluaciones (id_tanque_1);

CREATE OR REPLACE VIEW produccion.v_ticket_lab_conciliado AS
WITH tk AS (
    SELECT t.id_ticket, t.ticket_lab, t.id_batch, t.rol, t.fuente, t.ticket_porteria,
           t.id_tanque, t.estado, t.creado_en, t.evaluado_en, t.conciliado_via,
           -- creado_en es timestamptz y lab_evaluaciones.fecha es hora local sin zona:
           -- se normaliza explícito para no depender del TimeZone de la conexión.
           (t.creado_en AT TIME ZONE 'America/Argentina/Buenos_Aires') AS pedido_local,
           COALESCE(t.codigo_insumo, p.codigo_producto) AS producto
    FROM produccion.fact_ticket_lab t
    LEFT JOIN produccion.dim_producto p ON p.id_producto = t.id_producto
    WHERE COALESCE(t.estado, '') <> 'ANULADO'
),
cand AS (
    SELECT tk.id_ticket, l.id AS id_lab, 1 AS prio, 'CODIGO'::text AS via, l.fecha, l.producto_lab, l.calidad_final_lab, l.rechazado
    FROM tk JOIN produccion.lab_evaluaciones l
      ON COALESCE(tk.ticket_lab, '') <> '' AND l.ticket = tk.ticket_lab

    UNION ALL
    SELECT tk.id_ticket, l.id, 2, 'PORTERIA', l.fecha, l.producto_lab, l.calidad_final_lab, l.rechazado
    FROM tk JOIN produccion.lab_evaluaciones l
      ON tk.ticket_porteria IS NOT NULL
     AND regexp_replace(l.ticket, '\.0+$', '') = regexp_replace(tk.ticket_porteria, '\.0+$', '')

    UNION ALL
    SELECT tk.id_ticket, l.id, 3, 'TANQUE', l.fecha, l.producto_lab, l.calidad_final_lab, l.rechazado
    FROM tk JOIN produccion.lab_evaluaciones l
      ON tk.id_tanque IS NOT NULL
     AND l.id_tanque_1 ~ '^[0-9]+ · '
     AND split_part(l.id_tanque_1, ' · ', 1)::int = tk.id_tanque
     AND l.fecha BETWEEN tk.pedido_local - interval '12 hours'
                     AND tk.pedido_local + interval '96 hours'
),
mejor AS (
    -- Una evaluación PUEDE respaldar dos tickets (dos OP que cargaron del mismo tanque
    -- el mismo día): eso es correcto, no se deduplica del lado de la evaluación.
    SELECT DISTINCT ON (id_ticket) *
    FROM cand ORDER BY id_ticket, prio, fecha
)
SELECT tk.id_ticket, tk.ticket_lab, tk.id_batch, b.identificador_unidad AS op,
       tk.rol, tk.fuente, tk.producto, tk.ticket_porteria, tk.id_tanque,
       tk.estado AS estado_guardado, tk.creado_en, tk.conciliado_via,
       m.id_lab, m.via, m.fecha AS fecha_lab, m.producto_lab,
       m.calidad_final_lab, m.rechazado,
       (m.id_lab IS NOT NULL) AS tiene_respaldo,
       -- la familia que informa el lab (AFE, AG, ARE) contra el código del ticket (AFE-SG)
       (m.producto_lab IS NOT NULL AND tk.producto IS NOT NULL
        AND upper(tk.producto) LIKE upper(btrim(m.producto_lab)) || '%') AS coincide_producto,
       CASE
         WHEN m.id_lab IS NULL THEN NULL
         WHEN m.via IN ('CODIGO', 'PORTERIA') THEN 'ALTA'
         WHEN m.producto_lab IS NOT NULL AND tk.producto IS NOT NULL
              AND upper(tk.producto) LIKE upper(btrim(m.producto_lab)) || '%' THEN 'MEDIA'
         ELSE 'BAJA'
       END AS confianza,
       CASE WHEN m.id_lab IS NOT NULL
            THEN round(extract(epoch FROM (m.fecha - tk.pedido_local)) / 3600.0, 1)
       END AS horas_respuesta,
       round(extract(epoch FROM (now() - tk.creado_en)) / 86400.0, 1) AS dias_desde_pedido
FROM tk
LEFT JOIN mejor m ON m.id_ticket = tk.id_ticket
LEFT JOIN produccion.fact_batch_proceso b ON b.id_batch = tk.id_batch;

COMMENT ON VIEW produccion.v_ticket_lab_conciliado IS
  'Cada pedido de laboratorio con el resultado que lo responde, si existe. confianza ALTA = identidad (código de ticket o ticket de balanza); MEDIA = mismo tanque y misma familia de producto en la ventana del pedido; BAJA = mismo tanque, producto distinto. Sin respaldo = la muestra realmente falta.';

-- Materializa el cierre. Sólo ALTA y MEDIA: lo inferido flojo se propone, no se cierra.
CREATE OR REPLACE FUNCTION produccion.fn_ticket_lab_conciliar(p_min_confianza text DEFAULT 'MEDIA')
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE n integer;
BEGIN
    WITH c AS (
        SELECT id_ticket, id_lab, via, fecha_lab
        FROM produccion.v_ticket_lab_conciliado
        WHERE tiene_respaldo
          AND estado_guardado = 'PENDIENTE'
          AND (confianza = 'ALTA' OR (p_min_confianza = 'MEDIA' AND confianza = 'MEDIA'))
    ), u AS (
        UPDATE produccion.fact_ticket_lab t
           SET estado = 'EVALUADO',
               evaluado_en = (c.fecha_lab AT TIME ZONE 'America/Argentina/Buenos_Aires'),
               id_lab_evaluacion = c.id_lab,
               conciliado_via = c.via,
               conciliado_en = now()
          FROM c WHERE c.id_ticket = t.id_ticket
        RETURNING 1)
    SELECT count(*) INTO n FROM u;
    RETURN n;
END $$;

COMMENT ON FUNCTION produccion.fn_ticket_lab_conciliar(text) IS
  'Cierra los pedidos de lab que tienen respaldo con confianza suficiente. Devuelve cuántos cerró. Reversible: UPDATE fact_ticket_lab SET estado=''PENDIENTE'', evaluado_en=NULL, conciliado_via=NULL WHERE conciliado_via IS NOT NULL.';
