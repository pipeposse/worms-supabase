-- ============================================================================
-- NAVEGACIÓN V2 · FASE 6 · BANDEJA "HOY": el trabajo pendiente como una cola
--                                          · aplicada en worms-prod 2026-09-11
-- ----------------------------------------------------------------------------
-- Diagnóstico (11/09/2026): el sistema ya SABE qué falta hacer, pero no lo empuja.
--   · RE-409 en reacción con 3 variables fuera de tolerancia y 4 de 16 pasos cargados.
--   · RE-407 y RE-408 12 h en reposo, creadas sin fórmula (4 de las 6 OP de la semana).
--   · 101 tickets de lab pendientes, 15 AFE sin tanque, 34 filas en v_alertas_planta.
-- Nada de eso tenía pantalla propia: había que ir a buscarlo sector por sector, y
-- nadie va. Lo que está en el camino del operario se usa (el instructivo de RE-409);
-- lo que exige navegar, no (los desvíos de esa misma OP, sin mirar).
--
-- v_pendientes unifica todo en filas ACCIONABLES (una por OP, no una por paso) con
-- prioridad (1 urgente · 2 hoy · 3 revisar), la sección clásica que lo resuelve y el
-- sector. Sin tablas de datos nuevas: todo sale de lo que ya existe.
--
-- Quién ve qué: la columna `seccion` se filtra con puede_seccion() de app.py. Un
-- operario de INICIAR ve sus pasos y sus OP; el supervisor ve además desvíos y
-- planificación. No hay roles hardcodeados en la bandeja.
--
-- fact_pendiente_resuelto oculta lo que no tiene resolución natural (un desvío ya
-- mirado). La columna `marca` es un fingerprint del estado: si el estado cambia
-- (aparece otro desvío), la marca cambia y el pendiente REAPARECE solo.
--
-- Costo: v_op_instructivo / v_desvio_op / v_alertas_planta son caras y se tocaban
-- 3 veces; con CTEs MATERIALIZED la vista baja de 643 ms a ~240 ms (caliente). El
-- módulo la cachea 60 s, así que se paga una vez por minuto y por proceso. Si algún
-- día pesa, el próximo paso es materializar v_op_instructivo por OP activa, no
-- seguir optimizando esta vista.
-- ============================================================================
CREATE TABLE IF NOT EXISTS produccion.fact_pendiente_resuelto (
    id_res      bigserial PRIMARY KEY,
    tipo        text        NOT NULL,
    ref         text        NOT NULL,
    marca       text        NOT NULL DEFAULT '',   -- fingerprint del estado al marcar
    id_usuario  integer,
    nota        text,
    ts          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tipo, ref, marca)
);
COMMENT ON TABLE produccion.fact_pendiente_resuelto IS
  'Pendientes marcados como vistos en la bandeja HOY. marca = fingerprint del estado: si cambia, el pendiente reaparece.';

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
base AS (
    -- 1 · pasos del instructivo sin cargar (una fila por OP, no una por paso)
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
    -- 2 · OP planificada que ya debería haber arrancado
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
    -- 3 · OP sin fórmula: rompe el circuito (sin instructivo no hay desvíos)
    SELECT 'OP_SIN_FORMULA', 'OPF:' || o.id_batch, '',
           3, o.op || ' · sin fórmula asignada',
           'Sin fórmula no hay instructivo ni desvíos. Asignala en el Centro de Planificación · '
             || o.sector_ui || ' · ' || o.estado,
           'PLANIFICACION', 'PLAN', o.sector_nav, o.id_batch, o.op,
           COALESCE(o.inicio_ts, o.fecha::timestamptz), 1
    FROM op o
    WHERE o.id_formula IS NULL AND o.tipo_proceso IS DISTINCT FROM 'RECUPERACION'

    UNION ALL
    -- 4 · proceso en curso sin novedades hace rato
    SELECT 'OP_SIN_EVENTO', 'OPE:' || o.id_batch,
           to_char(o.ult_evento, 'YYYYMMDDHH24'),
           CASE WHEN o.ult_evento < now() - interval '12 hours' THEN 1 ELSE 3 END,
           o.op || ' · sin movimientos hace ' || round(extract(epoch FROM (now() - o.ult_evento)) / 3600) || ' h',
           o.sector_ui || ' · en ' || o.estado || ' desde el último registro',
           'INICIAR', 'SEGUIMIENTO', o.sector_nav, o.id_batch, o.op, o.ult_evento, 1
    FROM en_curso o
    WHERE o.ult_evento IS NOT NULL AND o.ult_evento < now() - interval '6 hours'

    UNION ALL
    -- 5 · desvíos fuera de tolerancia sin revisar
    SELECT 'DESVIO', 'DES:' || d.id_batch, d.n::text,
           1, o.op || ' · ' || d.n || ' variable(s) fuera de tolerancia',
           d.variables || ' · lo formulado contra lo que cargó el operario',
           'ANALISIS', 'DESVIOS', o.sector_nav, o.id_batch, o.op,
           COALESCE(o.inicio_ts, o.fecha::timestamptz), d.n
    FROM desvio d
    JOIN op o ON o.id_batch = d.id_batch

    UNION ALL
    -- 6 · esperando validación de laboratorio
    SELECT 'LAB_VALIDAR', 'LAB:' || o.id_batch, '',
           1, o.op || ' · espera validación de laboratorio',
           o.sector_ui || ' · el proceso no avanza hasta que el lab confirme',
           'LAB', NULL, o.sector_nav, o.id_batch, o.op, o.ult_evento, 1
    FROM en_curso o
    WHERE o.esperando_validacion_lab

    UNION ALL
    -- 7 · agregados de planta (una fila cada uno, no una por ítem)
    SELECT 'TICKETS_LAB', 'TKLAB', n::text, 3,
           n || ' tickets de laboratorio pendientes',
           'Muestras cargadas esperando resultado' ||
             CASE WHEN viejo IS NOT NULL THEN ' · el más viejo del ' || to_char(viejo, 'DD/MM') ELSE '' END,
           'LAB', NULL, 'LABORATORIO', NULL, NULL, viejo, n
    FROM (SELECT count(*) AS n, min(creado_en) AS viejo FROM produccion.fact_ticket_lab WHERE estado = 'PENDIENTE') t
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
    -- 8 · alertas de planta de severidad alta (LAB ya sale por LAB_VALIDAR)
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

COMMENT ON VIEW produccion.v_pendientes IS
  'Bandeja HOY: todo el trabajo pendiente de la planta como filas accionables (prioridad 1 urgente, 2 hoy, 3 revisar). seccion = la clásica que lo resuelve (filtrar con puede_seccion); vista = vista nav a la que ir.';
