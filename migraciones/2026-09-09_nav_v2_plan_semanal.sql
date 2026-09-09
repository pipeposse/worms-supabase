-- ============================================================================
-- NAVEGACIÓN V2 · FASE 4a · PLANIFICACIÓN SEMANAL POR OP   · aplicada en worms-prod 2026-09-09
-- ----------------------------------------------------------------------------
-- Dirección (Sistema WORMS.xlsx, tabla PLANIFICACIÓN): # OP · DÍA · FECHA · SEMANA ·
-- PROCESO · FORMULACIÓN · HORA INICIO · HORA FIN · RESPONSABLE, botón "Cargar" por
-- fila, estados No iniciado / Iniciado / Finalizado, y la "orden del día" = las
-- filas de hoy. La OP ya existe: es fact_batch_proceso (el Centro de Planificación
-- la crea en estado PLANIFICADO). Sólo faltaban los campos del plan.
--
-- Las columnas nuevas son NULL-ables y la vista hace COALESCE con lo que ya se
-- guarda en parametros_proceso (inicio_programado, tiempo_horas, formula_id),
-- así nada de lo existente cambia de comportamiento.
-- ============================================================================
ALTER TABLE produccion.fact_batch_proceso
    ADD COLUMN IF NOT EXISTS plan_inicio_ts   timestamptz,
    ADD COLUMN IF NOT EXISTS plan_fin_ts      timestamptz,
    ADD COLUMN IF NOT EXISTS responsable_plan text,
    ADD COLUMN IF NOT EXISTS id_formula       integer REFERENCES produccion.dic_formula(id_formula),
    ADD COLUMN IF NOT EXISTS version_pasos    integer;   -- versión del instructivo con la que arrancó (se fija al arrancar, Fase 4b)

COMMENT ON COLUMN produccion.fact_batch_proceso.plan_inicio_ts IS 'Hora de inicio planificada (grilla semanal). Si es NULL se usa parametros_proceso->inicio_programado.';
COMMENT ON COLUMN produccion.fact_batch_proceso.responsable_plan IS 'Responsable asignado en la planificación semanal (nombre tal cual se muestra).';

CREATE OR REPLACE VIEW produccion.v_plan_semanal AS
WITH b AS (
    SELECT b.*,
           COALESCE(b.plan_inicio_ts,
                    (NULLIF(b.parametros_proceso->>'inicio_programado','')::timestamp
                       AT TIME ZONE 'America/Argentina/Buenos_Aires'),
                    b.inicio_ts,
                    (b.fecha::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires')) AS p_ini,
           COALESCE(b.id_formula, NULLIF(b.parametros_proceso->>'formula_id','')::integer) AS f_id,
           COALESCE(NULLIF(b.parametros_proceso->>'tiempo_horas','')::numeric, b.tiempo_estimado_horas) AS horas_plan
    FROM produccion.fact_batch_proceso b
    WHERE NOT COALESCE(b.anulado, false)
),
fin_real AS (
    SELECT id_batch, max(ts) AS fin_ts
    FROM produccion.fact_batch_estado_log WHERE estado_nuevo = 'FINALIZADO' GROUP BY id_batch
)
SELECT b.id_batch,
       b.identificador_unidad                          AS op,
       b.sector                                        AS sector_batch,
       s.codigo                                        AS sector_nav,
       b.tipo_proceso                                  AS proceso,
       bu.nombre_ui                                    AS equipo,
       b.p_ini                                         AS plan_inicio,
       COALESCE(b.plan_fin_ts, b.p_ini + COALESCE(b.horas_plan, 0) * interval '1 hour') AS plan_fin,
       (b.p_ini AT TIME ZONE 'America/Argentina/Buenos_Aires')::date AS fecha_plan,
       EXTRACT(ISOYEAR FROM (b.p_ini AT TIME ZONE 'America/Argentina/Buenos_Aires'))::int AS anio_iso,
       EXTRACT(WEEK    FROM (b.p_ini AT TIME ZONE 'America/Argentina/Buenos_Aires'))::int AS semana_iso,
       EXTRACT(ISODOW  FROM (b.p_ini AT TIME ZONE 'America/Argentina/Buenos_Aires'))::int AS dia_iso,
       b.f_id                                          AS id_formula,
       COALESCE(f.nombre, b.parametros_proceso->>'formula_nombre') AS formula,
       f.version_pasos                                 AS formula_version_actual,
       b.version_pasos                                 AS version_pasos_op,
       COALESCE(b.responsable_plan, u.nombre_full)     AS responsable,
       b.responsable_plan,
       b.kg_inicial,
       b.estado,
       CASE WHEN b.estado = 'PLANIFICADO' THEN 'NO_INICIADO'
            WHEN b.estado = 'FINALIZADO'  THEN 'FINALIZADO'
            ELSE 'INICIADO' END                        AS estado_plan,
       b.inicio_ts                                     AS real_inicio,
       COALESCE(b.fin_ts, fr.fin_ts)                   AS real_fin,
       b.creado_en
FROM b
LEFT JOIN produccion.dim_sector_nav s ON s.sector_batch = b.sector
LEFT JOIN produccion.dim_bien_uso  bu ON bu.id_bien_uso = b.id_bien_uso
LEFT JOIN produccion.dic_formula   f  ON f.id_formula = b.f_id
LEFT JOIN produccion.dim_usuario   u  ON u.id_usuario = b.id_usuario_carga
LEFT JOIN fin_real fr ON fr.id_batch = b.id_batch;
