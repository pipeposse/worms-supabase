-- ============================================================================
-- NAVEGACIÓN V2 · FASE 1 · INDICADORES DEL ÁREA PRODUCCIÓN   · aplicada en worms-prod 2026-09-09
-- ----------------------------------------------------------------------------
-- Los 5 indicadores que pidió dirección para el pantallazo del área
-- (Sistema WORMS.xlsx, 28/08/2026):
--   1. Acopio disponible en tanques, sólidos y piletas
--   2. Descargas pendientes / en proceso (no sólo los líquidos)
--   3. Personal en planta
--   4. Sectores activos
--   5. Tickets pendientes de análisis
--
-- Fuentes: 1 → vw_tanque_panel (piletas = tipo_tanque 'Pileta'; sólidos = tanques
-- en KG, hoy casi sin datos). 2 → camiones ADENTRO en v_transacciones_limpias
-- (entraron y no salieron: eso es lo que hay en planta por descargar, de cualquier
-- producto) + AFE evaluados sin tanque asignado. 3 → fact_presencia (NUEVA: el
-- operario marca "Estoy en planta" / "Me retiro"); mientras no se use, se muestra
-- la cantidad de logins de las últimas 10 h con esa etiqueta. 4 → actividad de hoy
-- por sector de navegación. 5 → fact_ticket_lab PENDIENTE (el de siempre).
-- ============================================================================

-- ---------------------------------------------------------------- 3. presencia
CREATE TABLE IF NOT EXISTS produccion.fact_presencia (
    id_presencia  bigserial PRIMARY KEY,
    id_usuario    integer     NOT NULL REFERENCES produccion.dim_usuario(id_usuario),
    sector        text,                                -- código de dim_sector_nav (o NULL = general)
    entrada_ts    timestamptz NOT NULL DEFAULT now(),
    salida_ts     timestamptz,
    origen        text        NOT NULL DEFAULT 'APP',  -- APP | AUTO (cierre automático)
    creado_en     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fact_presencia_salida_chk CHECK (salida_ts IS NULL OR salida_ts >= entrada_ts)
);
CREATE INDEX IF NOT EXISTS fact_presencia_usuario_idx ON produccion.fact_presencia (id_usuario, entrada_ts DESC);
CREATE INDEX IF NOT EXISTS fact_presencia_abierta_idx ON produccion.fact_presencia (entrada_ts DESC) WHERE salida_ts IS NULL;
COMMENT ON TABLE produccion.fact_presencia IS
  'Quién está en planta: el usuario marca entrada/salida desde la portada del área Producción. '
  'Una presencia sin salida se considera cerrada a las 14 h (v_presencia_actual).';

CREATE OR REPLACE VIEW produccion.v_presencia_actual AS
SELECT p.id_presencia, p.id_usuario, u.nombre, u.nombre_full, u.rol,
       COALESCE(p.sector, u.sector) AS sector, p.entrada_ts,
       EXTRACT(EPOCH FROM (now() - p.entrada_ts)) / 3600.0 AS horas
FROM produccion.fact_presencia p
JOIN produccion.dim_usuario u ON u.id_usuario = p.id_usuario
WHERE p.salida_ts IS NULL
  AND p.entrada_ts > now() - interval '14 hours';

-- ---------------------------------------------------------------- 4. actividad por sector
CREATE OR REPLACE VIEW produccion.v_sector_actividad_hoy AS
WITH pres AS (
    SELECT sector, count(*) AS n FROM produccion.v_presencia_actual GROUP BY sector
),
batch AS (
    SELECT b.sector,
           count(*) FILTER (WHERE b.estado IN ('REACCION','REPOSO','DECANTACION')) AS activos,
           count(*) FILTER (WHERE b.estado = 'PLANIFICADO') AS planificados,
           count(*) FILTER (WHERE b.fecha = CURRENT_DATE) AS hoy
    FROM produccion.fact_batch_proceso b
    WHERE NOT b.anulado
      AND (b.estado IN ('REACCION','REPOSO','DECANTACION','PLANIFICADO') OR b.fecha = CURRENT_DATE)
    GROUP BY b.sector
),
log_hoy AS (
    SELECT b.sector, count(*) AS n
    FROM produccion.fact_batch_estado_log l
    JOIN produccion.fact_batch_proceso b ON b.id_batch = l.id_batch
    WHERE l.ts::date = CURRENT_DATE
    GROUP BY b.sector
)
SELECT s.codigo, s.nombre_ui, s.icono, s.orden, s.tiene_datos, s.sector_gestion, s.sector_batch, s.seccion_clasica,
       COALESCE(b.activos, 0)      AS procesos_activos,
       COALESCE(b.planificados, 0) AS procesos_planificados,
       COALESCE(lg.n, 0) + COALESCE(b.hoy, 0)
         + CASE s.codigo
             WHEN 'PILETAS'     THEN (SELECT count(*) FROM produccion.fact_recuperacion_ticket r
                                      WHERE r.fecha_ticket = CURRENT_DATE AND NOT COALESCE(r.anulado, false))
             WHEN 'EXPORTACION' THEN (SELECT count(*) FROM produccion.fact_despacho d
                                      WHERE d.fecha_despacho = CURRENT_DATE AND COALESCE(d.estado,'') NOT IN ('ANULADO','ANULADA'))
             WHEN 'LABORATORIO' THEN (SELECT count(*) FROM produccion.lab_evaluaciones e WHERE e.fecha::date = CURRENT_DATE)
             WHEN 'PORTERIA'    THEN (SELECT count(*) FROM produccion.v_transacciones_limpias t WHERE t.fecha_entrada = CURRENT_DATE)
             WHEN 'TALLER'      THEN (SELECT count(*) FROM produccion.fact_repuesto_movimiento m
                                      WHERE m.fecha = CURRENT_DATE AND NOT COALESCE(m.anulado, false))
             ELSE 0 END          AS eventos_hoy,
       COALESCE(p.n, 0) + COALESCE(p2.n, 0) AS personal_presente
FROM produccion.dim_sector_nav s
LEFT JOIN batch  b  ON b.sector = s.sector_batch
LEFT JOIN log_hoy lg ON lg.sector = s.sector_batch
LEFT JOIN pres   p  ON p.sector = s.codigo
LEFT JOIN pres   p2 ON p2.sector = s.sector_batch AND s.sector_batch <> s.codigo
WHERE s.activo;

-- ---------------------------------------------------------------- 1+2+5. una fila con todo
CREATE OR REPLACE VIEW produccion.v_kpi_area_produccion AS
WITH tk AS (
    SELECT p.*, t.unidad_stock
    FROM produccion.vw_tanque_panel p
    JOIN produccion.dim_tanque t ON t.id_tanque = p.id_tanque
    WHERE p.activo AND COALESCE(p.condicion, 'EN USO') <> 'FUERA DE USO'
),
tq AS (  -- tanques líquidos (no piletas)
    SELECT count(*) AS n,
           count(*) FILTER (WHERE COALESCE(capacidad_litros,0) - COALESCE(litros_actual,0) >= 5000) AS n_con_espacio,
           SUM(COALESCE(capacidad_litros,0)) AS cap_l,
           SUM(COALESCE(litros_actual,0)) AS act_l,
           SUM(GREATEST(COALESCE(capacidad_litros,0) - COALESCE(litros_actual,0), 0)) AS libre_l,
           SUM(COALESCE(kg_actual,0)) AS kg
    FROM tk WHERE COALESCE(tipo_tanque,'') <> 'Pileta' AND COALESCE(unidad_stock,'L') = 'L'
),
pi AS (  -- piletas
    SELECT count(*) AS n,
           SUM(COALESCE(capacidad_litros,0)) AS cap_l,
           SUM(COALESCE(litros_actual,0)) AS act_l,
           SUM(GREATEST(COALESCE(capacidad_litros,0) - COALESCE(litros_actual,0), 0)) AS libre_l
    FROM tk WHERE COALESCE(tipo_tanque,'') = 'Pileta'
),
so AS (  -- sólidos: lo poco que hoy se lleva en KG
    SELECT count(*) AS n, SUM(COALESCE(kg_actual,0)) AS kg FROM tk WHERE COALESCE(unidad_stock,'L') = 'KG'
),
cam AS (  -- camiones adentro (entraron, no salieron): lo que hay en planta por descargar
    SELECT count(*) AS n,
           COALESCE(json_object_agg(corriente, n ORDER BY n DESC) FILTER (WHERE corriente IS NOT NULL), '{}'::json) AS por_corriente
    FROM (SELECT COALESCE(corriente, 'sin_declarar') AS corriente, count(*) AS n
          FROM produccion.v_transacciones_limpias
          WHERE fecha_entrada >= CURRENT_DATE - 1 AND fecha_salida IS NULL AND estado_camion = 'ADENTRO'
          GROUP BY 1) x
),
afe AS (  -- AFE evaluados por lab en la semana que todavía no tienen tanque asignado
    SELECT count(*) AS n
    FROM (SELECT DISTINCT regexp_replace(l.ticket, '\.0+$', '') AS tk
          FROM produccion.lab_evaluaciones l
          WHERE l.fecha >= now() - interval '7 days'
            AND upper(btrim(COALESCE(l.producto_lab,''))) = 'AFE'
            AND COALESCE(l.ticket,'') <> ''
            AND upper(COALESCE(l.rechazado,'')) NOT IN ('RECHAZADO','REMUESTREO')) le
    WHERE NOT EXISTS (SELECT 1 FROM produccion.fact_asignacion_afe a
                      WHERE a.ticket = le.tk AND a.estado = 'CONFIRMADO')
),
pers AS (
    SELECT (SELECT count(*) FROM produccion.v_presencia_actual) AS presentes,
           (SELECT count(*) FROM produccion.dim_usuario WHERE activo AND ultimo_login > now() - interval '10 hours') AS logins_10h
),
sec AS (
    SELECT count(*) FILTER (WHERE procesos_activos > 0 OR eventos_hoy > 0 OR personal_presente > 0) AS activos,
           count(*) FILTER (WHERE tiene_datos) AS con_datos,
           count(*) AS total,
           COALESCE(string_agg(nombre_ui, ' · ' ORDER BY orden)
                    FILTER (WHERE procesos_activos > 0 OR eventos_hoy > 0 OR personal_presente > 0), '') AS nombres
    FROM produccion.v_sector_actividad_hoy
),
lab AS (
    SELECT (SELECT count(*) FROM produccion.fact_ticket_lab WHERE estado = 'PENDIENTE') AS tickets_pend,
           (SELECT count(*) FROM produccion.fact_batch_proceso WHERE esperando_validacion_lab AND NOT anulado) AS esp_valid,
           (SELECT count(*) FROM produccion.lab_evaluaciones WHERE fecha::date = CURRENT_DATE) AS evaluados_hoy
)
SELECT now() AS calculado_en,
       tq.n AS tanques_n, tq.n_con_espacio AS tanques_con_espacio,
       tq.cap_l / 1000.0 AS tanques_cap_kl, tq.act_l / 1000.0 AS tanques_act_kl, tq.libre_l / 1000.0 AS tanques_libre_kl,
       tq.kg / 1000.0 AS tanques_tn,
       pi.n AS piletas_n, pi.cap_l / 1000.0 AS piletas_cap_kl, pi.act_l / 1000.0 AS piletas_act_kl, pi.libre_l / 1000.0 AS piletas_libre_kl,
       so.n AS solidos_n, so.kg / 1000.0 AS solidos_tn,
       cam.n AS camiones_adentro, cam.por_corriente AS camiones_por_corriente,
       afe.n AS afe_sin_tanque,
       pers.presentes AS personal_presente, pers.logins_10h AS personal_logins_10h,
       sec.activos AS sectores_activos, sec.con_datos AS sectores_con_datos, sec.total AS sectores_total, sec.nombres AS sectores_activos_nombres,
       lab.tickets_pend AS tickets_lab_pend, lab.esp_valid AS esperando_validacion, lab.evaluados_hoy AS lab_evaluados_hoy
FROM tq, pi, so, cam, afe, pers, sec, lab;

-- ---------------------------------------------------------------- Panel de Control: capacidad por producto
CREATE OR REPLACE VIEW produccion.v_capacidad_ocupada_producto AS
SELECT COALESCE(NULLIF(btrim(p.producto_principal), ''), '(sin producto)') AS producto,
       count(*) AS tanques,
       SUM(COALESCE(p.capacidad_litros,0)) / 1000.0 AS cap_kl,
       SUM(COALESCE(p.litros_actual,0)) / 1000.0 AS act_kl,
       SUM(GREATEST(COALESCE(p.capacidad_litros,0) - COALESCE(p.litros_actual,0), 0)) / 1000.0 AS libre_kl,
       CASE WHEN SUM(COALESCE(p.capacidad_litros,0)) > 0
            THEN 100.0 * SUM(COALESCE(p.litros_actual,0)) / SUM(COALESCE(p.capacidad_litros,0)) ELSE NULL END AS pct_ocupado,
       bool_or(COALESCE(p.tipo_tanque,'') = 'Pileta') AS incluye_piletas
FROM produccion.vw_tanque_panel p
WHERE p.activo AND COALESCE(p.condicion, 'EN USO') <> 'FUERA DE USO'
GROUP BY 1
ORDER BY cap_kl DESC;
