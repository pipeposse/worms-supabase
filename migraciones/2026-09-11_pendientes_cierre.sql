-- ============================================================================
-- FASE 7 · ítem 3 — LA ORDEN QUE SE CIERRA SIN DECIR CUÁNTO SALIÓ
--                                          · aplicada en worms-prod 2026-09-11
-- ----------------------------------------------------------------------------
-- 3 de las 20 OP del mes están FINALIZADAS con kg_obtenido NULL. No es que el
-- operario no complete un campo: hay DOS caminos para terminar una orden y sólo
-- uno pide el producto final.
--   · "🏁 Acopio final" (app.py) sí valida: sin kilos no deja guardar.
--   · "Confirmar decantación" (decantacion.py) marca FINALIZADO y genera los
--     movimientos de stock, pero nunca escribe kg_obtenido.
-- Las 3 OP huérfanas pasaron por el segundo camino, y las cerraron supervisores.
--
-- Decisión: NO rellenar kg_obtenido con el valor de la fórmula, aunque el dato
-- esté ahí en el momento del cierre. Sería comparar la fórmula contra sí misma y
-- daría rendimiento perfecto siempre — inventar un dato de control es peor que no
-- tenerlo. El kilo real lo carga una persona con la medición del tanque o el
-- ticket de pesada; hasta entonces la deuda se ve en la bandeja.
--
-- Al mirarlo en 120 días aparecieron 21 órdenes así, no 3: el bloque se separó a
-- produccion.v_pendientes_op_cierre y se agrupa, porque 21 filas sueltas romperían
-- la bandeja. Esa vista chica es además donde se tocan los cambios de acá en más,
-- en vez de reescribir v_pendientes entera por un UNION.
-- ============================================================================
CREATE OR REPLACE VIEW produccion.v_pendientes AS
WITH op AS MATERIALIZED (
    SELECT b.id_batch, b.identificador_unidad AS op, b.sector, b.estado, b.fecha,
           b.id_formula, b.version_pasos, b.esperando_validacion_lab,
           b.plan_inicio_ts, b.inicio_ts, b.tipo_proceso,
           COALESCE(s.codigo, 'REACTORES')  AS sector_nav,
           COALESCE(s.nombre_ui, b.sector)  AS sector_ui,
           (SELECT max(l.ts) FROM produccion.fact_batch_estado_log l WHERE l.id_batch = b.id_batch) AS ult_evento
    FROM produccion.fact_batch_proceso b
    LEFT JOIN produccion.dim_sector_nav s ON s.sector_batch = b.sector
    WHERE NOT b.anulado
      AND b.estado IN ('PLANIFICADO', 'REACCION', 'REPOSO', 'DECANTACION')
),
en_curso AS (SELECT * FROM op WHERE estado <> 'PLANIFICADO'),
inst AS MATERIALIZED (
    SELECT i.id_batch, i.orden, i.etapa, i.descripcion, i.hecho, i.hora_esperada
    FROM produccion.v_op_instructivo i
    WHERE i.id_batch IN (SELECT id_batch FROM en_curso)
),
pasos AS (
    SELECT id_batch, count(*) AS total, count(*) FILTER (WHERE hecho) AS hechos
    FROM inst GROUP BY id_batch
),
prox AS (
    SELECT DISTINCT ON (id_batch) id_batch, orden, etapa, descripcion, hora_esperada
    FROM inst WHERE NOT hecho ORDER BY id_batch, orden
),
desvio AS MATERIALIZED (
    SELECT d.id_batch, count(*) AS n,
           string_agg(DISTINCT split_part(d.variable, ' · ', 1), ', ') AS variables
    FROM produccion.v_desvio_op d
    WHERE d.fuera_tolerancia AND d.id_batch IN (SELECT id_batch FROM op)
    GROUP BY d.id_batch
),
ale AS MATERIALIZED (SELECT tipo, severidad, mensaje FROM produccion.v_alertas_planta),
lab AS MATERIALIZED (
    SELECT tiene_respaldo, confianza, dias_desde_pedido, estado_guardado
    FROM produccion.v_ticket_lab_conciliado
    WHERE estado_guardado = 'PENDIENTE'
),
base AS (
    SELECT 'PASO'::text AS tipo,
           'PASO:' || o.id_batch AS ref,
           p.hechos::text AS marca,
           CASE WHEN px.hora_esperada IS NOT NULL AND px.hora_esperada < now() THEN 1 ELSE 2 END AS prioridad,
           o.op || ' · faltan ' || (p.total - p.hechos) || ' de ' || p.total || ' pasos' AS titulo,
           COALESCE('Próximo: ' || px.etapa || ' — ' || px.descripcion, 'Seguí el instructivo desde el paso ' || px.orden)
             || CASE WHEN px.hora_esperada IS NOT NULL
                     THEN ' · esperado ' || to_char(px.hora_esperada AT TIME ZONE 'America/Argentina/Buenos_Aires', 'HH24:MI')
                          || CASE WHEN px.hora_esperada < now() THEN ' (atrasado)' ELSE '' END
                     ELSE '' END AS detalle,
           'INICIAR'::text AS seccion, 'SEGUIMIENTO'::text AS vista,
           o.sector_nav, o.id_batch, o.op, COALESCE(px.hora_esperada, o.inicio_ts) AS cuando,
           (p.total - p.hechos) AS n
    FROM en_curso o
    JOIN pasos p ON p.id_batch = o.id_batch AND p.total > p.hechos
    LEFT JOIN prox px ON px.id_batch = o.id_batch

    UNION ALL
    SELECT 'OP_ARRANCAR', 'OP:' || o.id_batch, o.estado,
           CASE WHEN o.fecha < CURRENT_DATE THEN 1 ELSE 2 END,
           o.op || ' · planificada sin arrancar',
           o.sector_ui || ' · ' || to_char(o.fecha, 'DD/MM')
             || CASE WHEN o.plan_inicio_ts IS NOT NULL
                     THEN ' ' || to_char(o.plan_inicio_ts AT TIME ZONE 'America/Argentina/Buenos_Aires', 'HH24:MI') ELSE '' END
             || CASE WHEN o.fecha < CURRENT_DATE THEN ' · era para ' || (CURRENT_DATE - o.fecha) || ' día(s) atrás' ELSE '' END,
           'INICIAR', 'SEGUIMIENTO', o.sector_nav, o.id_batch, o.op,
           COALESCE(o.plan_inicio_ts, o.fecha::timestamptz), 1
    FROM op o
    WHERE o.estado = 'PLANIFICADO' AND o.fecha <= CURRENT_DATE

    UNION ALL
    SELECT 'OP_SIN_FORMULA', 'OPF:' || o.id_batch, '',
           3, o.op || ' · sin fórmula asignada',
           'Sin fórmula no hay instructivo ni desvíos. Asignala en el Centro de Planificación · '
             || o.sector_ui || ' · ' || o.estado,
           'PLANIFICACION', 'PLAN', o.sector_nav, o.id_batch, o.op,
           COALESCE(o.inicio_ts, o.fecha::timestamptz), 1
    FROM op o
    WHERE o.id_formula IS NULL AND o.tipo_proceso IS DISTINCT FROM 'RECUPERACION'

    UNION ALL
    SELECT 'OP_SIN_EVENTO', 'OPE:' || o.id_batch,
           to_char(o.ult_evento, 'YYYYMMDDHH24'),
           CASE WHEN o.ult_evento < now() - interval '12 hours' THEN 1 ELSE 3 END,
           o.op || ' · sin movimientos hace ' || round(extract(epoch FROM (now() - o.ult_evento)) / 3600) || ' h',
           o.sector_ui || ' · en ' || o.estado || ' desde el último registro',
           'INICIAR', 'SEGUIMIENTO', o.sector_nav, o.id_batch, o.op, o.ult_evento, 1
    FROM en_curso o
    WHERE o.ult_evento IS NOT NULL AND o.ult_evento < now() - interval '6 hours'

    UNION ALL
    -- Terminada pero sin decir cuánto salió: sin esto no hay rendimiento posible.
    -- Vive en su propia vista (v_pendientes_op_cierre): las de la última semana una
    -- por una, las anteriores agrupadas, para no llenar la bandeja con 21 filas.
    SELECT tipo, ref, marca, prioridad, titulo, detalle, seccion, vista,
           sector_nav, id_batch, op, cuando, n
    FROM produccion.v_pendientes_op_cierre

    UNION ALL
    SELECT 'DESVIO', 'DES:' || d.id_batch, d.n::text,
           1, o.op || ' · ' || d.n || ' variable(s) fuera de tolerancia',
           d.variables || ' · lo formulado contra lo que cargó el operario',
           'ANALISIS', 'DESVIOS', o.sector_nav, o.id_batch, o.op,
           COALESCE(o.inicio_ts, o.fecha::timestamptz), d.n
    FROM desvio d
    JOIN op o ON o.id_batch = d.id_batch

    UNION ALL
    SELECT 'LAB_VALIDAR', 'LAB:' || o.id_batch, '',
           1, o.op || ' · espera validación de laboratorio',
           o.sector_ui || ' · el proceso no avanza hasta que el lab confirme',
           'LAB', NULL, o.sector_nav, o.id_batch, o.op, o.ult_evento, 1
    FROM en_curso o
    WHERE o.esperando_validacion_lab

    UNION ALL
    SELECT 'MUESTRA_FALTA', 'MFALTA', n::text,
           CASE WHEN viejo > 14 THEN 2 ELSE 3 END,
           n || ' muestras sin resultado',
           'Pedidas por producción y todavía sin ningún análisis que las respalde'
             || CASE WHEN viejo IS NOT NULL THEN ' · la más vieja hace ' || round(viejo) || ' días' ELSE '' END,
           'LAB', NULL, 'LABORATORIO', NULL, NULL, now(), n
    FROM (SELECT count(*) AS n, max(dias_desde_pedido) AS viejo FROM lab WHERE NOT tiene_respaldo) t
    WHERE n > 0

    UNION ALL
    SELECT 'LAB_CONCILIAR', 'LABCONC', n::text, 3,
           n || ' análisis probables sin confirmar',
           'El lab midió ese tanque cerca del pedido, pero con otro producto: hay que confirmar a mano si corresponde',
           'LAB', NULL, 'LABORATORIO', NULL, NULL, now(), n
    FROM (SELECT count(*) AS n FROM lab WHERE tiene_respaldo AND confianza = 'BAJA') t
    WHERE n > 0

    UNION ALL
    SELECT 'AFE_SIN_TANQUE', 'AFETK', n::text, 2,
           n || ' tickets de AFE aprobados sin tanque asignado',
           'Materia prima evaluada que todavía no se asignó a un tanque',
           'TANQUES', NULL, 'PORTERIA', NULL, NULL, now(), n
    FROM (SELECT count(*) AS n
          FROM (SELECT DISTINCT regexp_replace(l.ticket, '\.0+$', '') AS tk
                FROM produccion.lab_evaluaciones l
                WHERE l.fecha >= now() - interval '7 days'
                  AND upper(btrim(COALESCE(l.producto_lab,''))) = 'AFE'
                  AND COALESCE(l.ticket,'') <> ''
                  AND upper(COALESCE(l.rechazado,'')) NOT IN ('RECHAZADO','REMUESTREO')) le
          WHERE NOT EXISTS (SELECT 1 FROM produccion.fact_asignacion_afe a
                            WHERE a.ticket = le.tk AND a.estado = 'CONFIRMADO')) a
    WHERE n > 0

    UNION ALL
    SELECT 'CAMION', 'CAM', n::text, 2,
           n || ' camión(es) adentro de planta',
           'Entraron y todavía no salieron',
           'LAB', NULL, 'PORTERIA', NULL, NULL, now(), n
    FROM (SELECT count(*) AS n FROM produccion.v_transacciones_limpias
          WHERE fecha_entrada >= CURRENT_DATE - 1 AND fecha_salida IS NULL AND estado_camion = 'ADENTRO') c
    WHERE n > 0

    UNION ALL
    SELECT 'ALERTA', 'ALE:' || md5(a.mensaje), '', 1,
           a.mensaje, 'Alerta de planta · ' || a.tipo,
           'ESTADO', NULL, NULL, NULL, NULL, now(), 1
    FROM ale a
    WHERE a.severidad = 'alta' AND a.tipo <> 'LAB'

    UNION ALL
    SELECT 'TANQUES_LLENOS', 'TKFULL', n::text, 3,
           n || ' tanque(s) al límite de capacidad',
           'Sin lugar para descargar: revisar antes de que llegue el próximo camión',
           'TANQUES', NULL, NULL, NULL, NULL, now(), n
    FROM (SELECT count(*) AS n FROM ale WHERE tipo = 'TANQUE') t
    WHERE n > 0
)
SELECT b.*,
       (r.id_res IS NOT NULL) AS resuelto,
       r.ts AS resuelto_ts
FROM base b
LEFT JOIN produccion.fact_pendiente_resuelto r
       ON r.tipo = b.tipo AND r.ref = b.ref AND r.marca = COALESCE(b.marca, '');
