-- ============================================================================
-- FASE 7 · ítem 4 — EL INDICADOR DE PERSONAL QUE NO TENÍA DATOS
--                                          · aplicada en worms-prod 2026-09-11
--   migraciones: personal_activo + kpis_personal_activo
-- ----------------------------------------------------------------------------
-- "Personal en planta" es uno de los cinco indicadores que pidió dirección, y
-- salía de fact_presencia: 3 marcas en TODA la historia. El KPI mostraba logins
-- como sustituto, que no es lo mismo ni se le parece. Un indicador que nadie
-- alimenta es peor que no tenerlo: enseña a desconfiar del tablero entero.
--
-- En vez de insistir con que la gente fiche (ya se probó y no pasó), se deriva de
-- lo que YA registran al trabajar: cada carga, medición o cambio de estado deja un
-- id_usuario y un momento. Si alguien cargó un paso del instructivo del Reactor
-- hace veinte minutos, está trabajando en el Reactor — no hace falta que lo declare.
--
-- El indicador se renombra a "Personas trabajando" porque eso es lo que mide:
-- trabajo registrado, no presencia física. La marca manual sigue valiendo y suma
-- como una fuente más. De 0 personas detectadas a 3, con sector y actividad.
-- ============================================================================
CREATE OR REPLACE VIEW produccion.v_personal_activo AS
WITH ev AS (
    SELECT l.id_usuario, b.sector AS sector_batch, NULL::text AS sector_nav, l.ts AS momento, 'produccion'::text AS que
    FROM produccion.fact_batch_estado_log l
    JOIN produccion.fact_batch_proceso b ON b.id_batch = l.id_batch
    WHERE l.ts >= now() - interval '14 hours' AND l.id_usuario IS NOT NULL
    UNION ALL
    SELECT m.id_usuario, b.sector, NULL, m.actualizado_en, 'instructivo'
    FROM produccion.fact_paso_medicion m
    JOIN produccion.fact_batch_proceso b ON b.id_batch = m.id_batch
    WHERE m.actualizado_en >= now() - interval '14 hours' AND m.id_usuario IS NOT NULL
    UNION ALL
    SELECT i.id_usuario, b.sector, NULL, i.creado_en, 'carga'
    FROM produccion.fact_batch_insumo i
    JOIN produccion.fact_batch_proceso b ON b.id_batch = i.id_batch
    WHERE i.creado_en >= now() - interval '14 hours' AND i.id_usuario IS NOT NULL
    UNION ALL
    SELECT t.id_usuario, NULL, NULL, t.creado_en, 'tanques'
    FROM produccion.fact_stock_tanque t
    WHERE t.creado_en >= now() - interval '14 hours' AND t.id_usuario IS NOT NULL
    UNION ALL
    SELECT s.id_usuario, NULL, s.sector_nav, s.creado_en, 'stock'
    FROM produccion.fact_stock_sector s
    WHERE s.creado_en >= now() - interval '14 hours' AND s.id_usuario IS NOT NULL
    UNION ALL
    SELECT r.id_usuario, 'RECUPERACION', 'PILETAS', r.actualizado_en, 'recuperacion'
    FROM produccion.fact_recuperacion_ticket r
    WHERE r.actualizado_en >= now() - interval '14 hours' AND r.id_usuario IS NOT NULL
    UNION ALL
    SELECT a.id_usuario, NULL, 'PORTERIA', a.actualizado_en, 'asignacion'
    FROM produccion.fact_asignacion_afe a
    WHERE a.actualizado_en >= now() - interval '14 hours' AND a.id_usuario IS NOT NULL
    UNION ALL
    SELECT p.id_usuario, NULL, p.sector, COALESCE(p.salida_ts, now()), 'presencia'
    FROM produccion.fact_presencia p
    WHERE p.salida_ts IS NULL AND p.creado_en >= now() - interval '14 hours'
)
SELECT ev.id_usuario, u.nombre_full, u.rol,
       COALESCE(ev.sector_nav, s.codigo) AS sector_nav,
       max(ev.momento) AS ultimo,
       round(extract(epoch FROM (now() - max(ev.momento))) / 60.0) AS hace_min,
       string_agg(DISTINCT ev.que, ', ') AS actividades,
       count(*) AS registros
FROM ev
LEFT JOIN produccion.dim_usuario u ON u.id_usuario = ev.id_usuario
LEFT JOIN produccion.dim_sector_nav s ON s.sector_batch = ev.sector_batch
GROUP BY ev.id_usuario, u.nombre_full, u.rol, COALESCE(ev.sector_nav, s.codigo);

COMMENT ON VIEW produccion.v_personal_activo IS
  'Quién registró trabajo en las últimas 14 horas y en qué sector, derivado de lo que la gente ya carga (estados, instructivo, insumos, tanques, stock, recuperación, portería) más la marca manual de presencia. Mide trabajo registrado, no presencia física.';

-- v_sector_actividad_hoy.personal_presente y v_kpi_area_produccion.personal_presente
-- pasan a leer esta vista (ver migración kpis_personal_activo, aplicada junto con ésta).
