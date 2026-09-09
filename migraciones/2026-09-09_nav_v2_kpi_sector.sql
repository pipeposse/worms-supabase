-- ============================================================================
-- NAVEGACIÓN V2 · FASE 2 · INDICADORES POR SECTOR   · aplicada en worms-prod 2026-09-09
-- ----------------------------------------------------------------------------
-- Los 5 indicadores que pidió dirección para el home de cada sector
-- (Sistema WORMS.xlsx, hoja Produccion, fila 126):
--   1. Acopio disponible del sector        → tanques cuyo grupo (vw_tanque_panel.sector)
--                                            matchea patron_tanques del sector
--   2. Acopio de materia prima a procesar  → TN en esos tanques con producto tipo MP
--   3. Procesos activos                    → v_sector_actividad_hoy
--   4. Personal en planta (del sector)     → v_sector_actividad_hoy (fact_presencia)
--   5. % de cumplimiento de planificación  → vw_gestion_semanal, semana ISO actual,
--                                            objetivo vs real del sector de gestión
-- ============================================================================
ALTER TABLE produccion.dim_sector_nav ADD COLUMN IF NOT EXISTS patron_tanques text;
COMMENT ON COLUMN produccion.dim_sector_nav.patron_tanques IS
  'Regex (POSIX, ~*) sobre vw_tanque_panel.sector: qué tanques cuentan como acopio de este sector.';

UPDATE produccion.dim_sector_nav SET patron_tanques = v.p, actualizado_en = now()
FROM (VALUES
    ('REACTORES',   '^(Reactores|Consumibles Reactores)'),
    ('BACHAS',      '^Bachas'),
    ('PILETAS',     '^Piletas'),
    ('EXPORTACION', '^Plataforma')
) AS v(codigo, p)
WHERE produccion.dim_sector_nav.codigo = v.codigo;

CREATE OR REPLACE VIEW produccion.v_kpi_sector AS
WITH tk AS (
    SELECT s.codigo,
           count(*) AS tanques_n,
           count(*) FILTER (WHERE COALESCE(p.capacidad_litros,0) - COALESCE(p.litros_actual,0) >= 5000) AS tanques_con_espacio,
           SUM(COALESCE(p.capacidad_litros,0)) / 1000.0 AS cap_kl,
           SUM(COALESCE(p.litros_actual,0)) / 1000.0 AS act_kl,
           SUM(GREATEST(COALESCE(p.capacidad_litros,0) - COALESCE(p.litros_actual,0), 0)) / 1000.0 AS libre_kl,
           SUM(COALESCE(p.kg_actual,0)) FILTER (WHERE d.tipo_producto = 'MP')     / 1000.0 AS mp_tn,
           SUM(COALESCE(p.kg_actual,0)) FILTER (WHERE d.tipo_producto = 'FINAL')  / 1000.0 AS pf_tn,
           SUM(COALESCE(p.kg_actual,0)) FILTER (WHERE d.tipo_producto = 'INSUMO') / 1000.0 AS insumo_tn,
           COALESCE(string_agg(DISTINCT d.codigo_producto, ', ') FILTER (WHERE d.tipo_producto = 'MP' AND COALESCE(p.kg_actual,0) > 0), '') AS mp_productos
    FROM produccion.dim_sector_nav s
    JOIN produccion.vw_tanque_panel p ON s.patron_tanques IS NOT NULL AND p.sector ~* s.patron_tanques
    LEFT JOIN produccion.dim_producto d ON d.id_producto = p.id_producto_principal
    WHERE p.activo AND COALESCE(p.condicion, 'EN USO') <> 'FUERA DE USO'
    GROUP BY s.codigo
),
gs AS (  -- semana ISO actual, objetivo vs real del sector de gestión
    SELECT sector,
           SUM(COALESCE(tn_objetivo,0)) AS tn_objetivo,
           SUM(COALESCE(tn_real,0))     AS tn_real,
           bool_or(COALESCE(tiene_objetivo,false)) AS tiene_objetivo,
           bool_or(COALESCE(plan_cerrado,false))   AS plan_cerrado
    FROM produccion.vw_gestion_semanal
    WHERE anio = EXTRACT(ISOYEAR FROM CURRENT_DATE)::int
      AND semana = EXTRACT(WEEK FROM CURRENT_DATE)::int
    GROUP BY sector
)
SELECT a.codigo, a.nombre_ui, a.icono, a.orden, a.tiene_datos, a.sector_gestion, a.sector_batch, a.seccion_clasica,
       a.procesos_activos, a.procesos_planificados, a.eventos_hoy, a.personal_presente,
       tk.tanques_n, tk.tanques_con_espacio, tk.cap_kl, tk.act_kl, tk.libre_kl,
       tk.mp_tn, tk.pf_tn, tk.insumo_tn, tk.mp_productos,
       gs.tn_objetivo, gs.tn_real, gs.tiene_objetivo, gs.plan_cerrado,
       CASE WHEN gs.tn_objetivo > 0 THEN 100.0 * gs.tn_real / gs.tn_objetivo END AS pct_cumplimiento,
       EXTRACT(WEEK FROM CURRENT_DATE)::int AS semana_iso
FROM produccion.v_sector_actividad_hoy a
LEFT JOIN tk ON tk.codigo = a.codigo
LEFT JOIN gs ON gs.sector = a.sector_gestion;
