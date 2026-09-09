-- ============================================================================
-- NAVEGACIÓN V2 · FASE 4b · INSTRUCTIVO DEL OPERARIO Y DESVÍOS POR OP   · aplicada en worms-prod 2026-09-09
-- ----------------------------------------------------------------------------
-- Dirección (SEGUIMIENTO PRODUCCIÓN, partes 2 y 3): el operario aprieta "Orden
-- Producción", el sistema despliega el instructivo de la fórmula y en cada paso
-- carga hora inicio/fin, o temperatura y acidez, o la cantidad. "Esto genera la
-- base de lo que realmente sucedió y se cruza contra la formulación: así
-- calculamos los desvíos."
--
--   fact_paso_medicion      lo que cargó el operario en cada paso de la OP
--   v_op_instructivo        pasos de la OP (versión congelada de la fórmula × kg de la OP)
--                           + lo real + desvío por paso
--   fn_op_congelar_version  fija la versión del instructivo al arrancar la OP
--   v_desvio_op             una fila por OP y variable (MP, cada insumo, acidez, temp,
--                           tiempo de cada etapa): esperado, real, desvío, fuera de tolerancia
-- ============================================================================
CREATE TABLE IF NOT EXISTS produccion.fact_paso_medicion (
    id_medicion    bigserial PRIMARY KEY,
    id_batch       integer     NOT NULL REFERENCES produccion.fact_batch_proceso(id_batch) ON DELETE CASCADE,
    orden          smallint    NOT NULL,
    etapa          text,
    inicio_ts      timestamptz,
    fin_ts         timestamptz,
    temp_c         numeric(6,1),
    acidez_pct     numeric(6,2),
    cantidad       numeric(14,3),
    unidad         text,
    observacion    text,
    id_usuario     integer,
    creado_en      timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fact_paso_medicion_uk UNIQUE (id_batch, orden)
);
COMMENT ON TABLE produccion.fact_paso_medicion IS
  'Lo que el operario cargó en cada paso del instructivo de una OP (hora inicio/fin, temperatura y acidez, o cantidad). Se cruza contra dic_formula_paso para los desvíos.';

CREATE OR REPLACE FUNCTION produccion.fn_op_congelar_version(p_id_batch integer)
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE v integer;
BEGIN
    UPDATE produccion.fact_batch_proceso b
       SET id_formula = COALESCE(b.id_formula, NULLIF(b.parametros_proceso->>'formula_id','')::integer),
           version_pasos = COALESCE(b.version_pasos,
                                    (SELECT f.version_pasos FROM produccion.dic_formula f
                                      WHERE f.id_formula = COALESCE(b.id_formula, NULLIF(b.parametros_proceso->>'formula_id','')::integer)))
     WHERE b.id_batch = p_id_batch
    RETURNING version_pasos INTO v;
    RETURN v;
END $$;
COMMENT ON FUNCTION produccion.fn_op_congelar_version(integer) IS
  'Fija en la OP la versión del instructivo con la que arranca (si no la tenía). Idempotente.';

-- ---------------------------------------------------------------- pasos de la OP + lo real
CREATE OR REPLACE VIEW produccion.v_op_instructivo AS
WITH b AS (
    SELECT b.id_batch, b.identificador_unidad AS op, b.sector, b.tipo_proceso, b.estado, b.kg_inicial,
           COALESCE(b.id_formula, NULLIF(b.parametros_proceso->>'formula_id','')::integer) AS f_id,
           b.version_pasos, b.inicio_ts, b.plan_inicio_ts
    FROM produccion.fact_batch_proceso b
    WHERE NOT COALESCE(b.anulado, false)
),
congelada AS (   -- versión fijada al arrancar
    SELECT b.id_batch, v.version, p.*
    FROM b
    JOIN produccion.dic_formula_paso_version v ON v.id_formula = b.f_id AND v.version = b.version_pasos
    CROSS JOIN LATERAL jsonb_to_recordset(v.pasos) AS p(
        orden int, etapa text, descripcion text, codigo_insumo text, cant_por_tn numeric, unidad text,
        acidez_esp numeric, temp_esp numeric, tol_acidez numeric, tol_temp numeric, tol_cant_pct numeric,
        offset_min int, duracion_min int, captura text)
),
vigente AS (     -- sin versión fijada (o versión inexistente): la actual
    SELECT b.id_batch, f.version_pasos AS version, p.orden, p.etapa, p.descripcion, p.codigo_insumo, p.cant_por_tn, p.unidad,
           p.acidez_esp, p.temp_esp, p.tol_acidez, p.tol_temp, p.tol_cant_pct, p.offset_min, p.duracion_min, p.captura
    FROM b
    JOIN produccion.dic_formula f ON f.id_formula = b.f_id
    JOIN produccion.dic_formula_paso p ON p.id_formula = b.f_id AND p.activo
    WHERE NOT EXISTS (SELECT 1 FROM congelada c WHERE c.id_batch = b.id_batch)
),
pasos AS (SELECT * FROM congelada UNION ALL SELECT * FROM vigente),
mp_real AS (
    SELECT id_batch, SUM(cantidad) AS kg
    FROM produccion.fact_batch_insumo WHERE rol = 'MP' AND NOT COALESCE(anulado, false) GROUP BY id_batch
)
SELECT b.id_batch, b.op, b.sector, b.tipo_proceso, b.estado, b.kg_inicial, b.f_id AS id_formula,
       p.version, p.orden, p.etapa, p.descripcion, p.codigo_insumo, p.unidad, p.captura,
       p.cant_por_tn, p.cant_por_tn * COALESCE(b.kg_inicial, 0) / 1000.0 AS cant_esperada,
       p.acidez_esp, p.temp_esp, p.tol_acidez, p.tol_temp, p.tol_cant_pct, p.offset_min, p.duracion_min,
       COALESCE(b.inicio_ts, b.plan_inicio_ts) + COALESCE(p.offset_min, 0) * interval '1 minute' AS hora_esperada,
       m.id_medicion, m.inicio_ts, m.fin_ts, m.temp_c, m.acidez_pct, m.observacion, m.id_usuario, m.actualizado_en,
       -- cantidad real: lo que cargó el operario; para la MP, si no cargó nada, lo que ya registra la producción
       COALESCE(m.cantidad, CASE WHEN p.etapa = 'CARGA_MP' THEN mr.kg END) AS cantidad_real,
       CASE p.captura
            WHEN 'HORAS'    THEN m.fin_ts IS NOT NULL
            WHEN 'MEDICION' THEN (m.temp_c IS NOT NULL OR m.acidez_pct IS NOT NULL)
            WHEN 'CANTIDAD' THEN COALESCE(m.cantidad, CASE WHEN p.etapa = 'CARGA_MP' THEN mr.kg END) IS NOT NULL
            ELSE m.id_medicion IS NOT NULL END AS hecho,
       CASE WHEN m.inicio_ts IS NOT NULL AND m.fin_ts IS NOT NULL
            THEN EXTRACT(EPOCH FROM (m.fin_ts - m.inicio_ts)) / 60.0 END AS duracion_real_min,
       m.acidez_pct - p.acidez_esp AS desvio_acidez,
       m.temp_c - p.temp_esp AS desvio_temp,
       CASE WHEN p.cant_por_tn > 0 AND COALESCE(b.kg_inicial, 0) > 0
            THEN 100.0 * (COALESCE(m.cantidad, CASE WHEN p.etapa = 'CARGA_MP' THEN mr.kg END) - p.cant_por_tn * b.kg_inicial / 1000.0)
                 / (p.cant_por_tn * b.kg_inicial / 1000.0) END AS desvio_cant_pct,
       (   (m.acidez_pct IS NOT NULL AND p.acidez_esp IS NOT NULL AND abs(m.acidez_pct - p.acidez_esp) > COALESCE(p.tol_acidez, 3))
        OR (m.temp_c IS NOT NULL AND p.temp_esp IS NOT NULL AND abs(m.temp_c - p.temp_esp) > COALESCE(p.tol_temp, 4))
        OR (p.cant_por_tn > 0 AND COALESCE(b.kg_inicial, 0) > 0
            AND COALESCE(m.cantidad, CASE WHEN p.etapa = 'CARGA_MP' THEN mr.kg END) IS NOT NULL
            AND abs(100.0 * (COALESCE(m.cantidad, CASE WHEN p.etapa = 'CARGA_MP' THEN mr.kg END) - p.cant_por_tn * b.kg_inicial / 1000.0)
                    / (p.cant_por_tn * b.kg_inicial / 1000.0)) > COALESCE(p.tol_cant_pct, 3))
       ) AS fuera_tolerancia
FROM b
JOIN pasos p ON p.id_batch = b.id_batch
LEFT JOIN produccion.fact_paso_medicion m ON m.id_batch = b.id_batch AND m.orden = p.orden
LEFT JOIN mp_real mr ON mr.id_batch = b.id_batch
ORDER BY b.id_batch, p.orden;

-- ---------------------------------------------------------------- desvíos por OP y variable
CREATE OR REPLACE VIEW produccion.v_desvio_op AS
WITH i AS (SELECT * FROM produccion.v_op_instructivo),
b AS (
    SELECT DISTINCT ON (i.id_batch) i.id_batch, i.op, i.sector, i.tipo_proceso, i.estado, s.codigo AS sector_nav,
           f.nombre AS formula, i.version,
           (SELECT (COALESCE(x.inicio_ts, x.plan_inicio_ts) AT TIME ZONE 'America/Argentina/Buenos_Aires')::date
              FROM produccion.fact_batch_proceso x WHERE x.id_batch = i.id_batch) AS fecha
    FROM i
    LEFT JOIN produccion.dim_sector_nav s ON s.sector_batch = i.sector
    LEFT JOIN produccion.dic_formula f ON f.id_formula = i.id_formula
)
SELECT b.*, EXTRACT(WEEK FROM b.fecha)::int AS semana_iso, EXTRACT(ISOYEAR FROM b.fecha)::int AS anio_iso,
       d.orden, d.variable, d.unidad, d.esperado, d.real, d.desvio, d.desvio_pct, d.tolerancia, d.fuera_tolerancia, d.medido
FROM b
JOIN LATERAL (
    -- cantidades (MP e insumos)
    SELECT i.orden, COALESCE(i.codigo_insumo, i.etapa) AS variable, i.unidad,
           i.cant_esperada AS esperado, i.cantidad_real AS real,
           i.cantidad_real - i.cant_esperada AS desvio, i.desvio_cant_pct AS desvio_pct,
           i.tol_cant_pct || ' %' AS tolerancia,
           (i.cantidad_real IS NOT NULL AND abs(COALESCE(i.desvio_cant_pct, 0)) > COALESCE(i.tol_cant_pct, 3)) AS fuera_tolerancia,
           i.cantidad_real IS NOT NULL AS medido
    FROM i WHERE i.id_batch = b.id_batch AND i.captura = 'CANTIDAD' AND i.cant_por_tn > 0
    UNION ALL
    -- acidez
    SELECT i.orden, 'ACIDEZ · ' || COALESCE(i.descripcion, i.etapa), '%', i.acidez_esp, i.acidez_pct,
           i.desvio_acidez, CASE WHEN i.acidez_esp > 0 THEN 100.0 * i.desvio_acidez / i.acidez_esp END,
           '± ' || i.tol_acidez || ' pts',
           (i.acidez_pct IS NOT NULL AND abs(i.desvio_acidez) > COALESCE(i.tol_acidez, 3)),
           i.acidez_pct IS NOT NULL
    FROM i WHERE i.id_batch = b.id_batch AND i.acidez_esp IS NOT NULL
    UNION ALL
    -- temperatura
    SELECT i.orden, 'TEMP · ' || COALESCE(i.descripcion, i.etapa), '°C', i.temp_esp, i.temp_c,
           i.desvio_temp, CASE WHEN i.temp_esp > 0 THEN 100.0 * i.desvio_temp / i.temp_esp END,
           '± ' || i.tol_temp || ' °C',
           (i.temp_c IS NOT NULL AND abs(i.desvio_temp) > COALESCE(i.tol_temp, 4)),
           i.temp_c IS NOT NULL
    FROM i WHERE i.id_batch = b.id_batch AND i.temp_esp IS NOT NULL
    UNION ALL
    -- tiempo de cada etapa con duración prevista
    SELECT i.orden, 'TIEMPO · ' || COALESCE(i.descripcion, i.etapa), 'min', i.duracion_min::numeric, i.duracion_real_min,
           i.duracion_real_min - i.duracion_min,
           CASE WHEN i.duracion_min > 0 THEN 100.0 * (i.duracion_real_min - i.duracion_min) / i.duracion_min END,
           '± 15 %',
           (i.duracion_real_min IS NOT NULL AND i.duracion_min > 0
            AND abs(100.0 * (i.duracion_real_min - i.duracion_min) / i.duracion_min) > 15),
           i.duracion_real_min IS NOT NULL
    FROM i WHERE i.id_batch = b.id_batch AND i.captura = 'HORAS' AND i.duracion_min IS NOT NULL
) d ON true;

-- ============================================================================
-- Complemento (misma fecha): cantidades FIJAS por OP en el instructivo
-- (glicerina fresca/recuperada en ARE, KOH/fuel fijos por reactor no van por TN).
--   ALTER TABLE dic_formula_paso ADD COLUMN cant_fija numeric(14,3);
--   v_formula_instructivo / v_op_instructivo recreadas con cant_fija;
--   cant_esperada = COALESCE(cant_fija, cant_por_tn × kg_inicial / 1000);
--   fn_formula_pasos_publicar acepta cant_fija; fn_formula_pasos_semilla marca
--   como fija todo insumo GLICERINA% en PRODUCCION_ARE.
-- Aplicado en worms-prod como migración nav_v2_formula_paso_cant_fija (ver historial
-- de migraciones de Supabase para el SQL completo). Fórmula 13 (ARE-B) publicada v2.
-- ============================================================================
