-- ============================================================================
-- NAVEGACIÓN V2 · FASE 5 · CUENTA CORRIENTE DE STOCK + SECTORES SIN TANQUES   · aplicada en worms-prod 2026-09-09
-- ----------------------------------------------------------------------------
-- Dirección (tabla STOCK del Excel): por producto, una cuenta corriente
--   FECHA · #TICKET · CC · CLIENTE/PROVEEDOR · ESTADO · SECTOR · INGRESO KG · EGRESO KG · SALDO
-- separada en Materia Prima / Insumos / Producto Terminado, con desplegable de producto.
-- Sale del ledger que ya existe (reporting.v_movimientos_stock) cruzado con portería
-- (cliente / procedencia del ticket) y con el sector del tanque.
--
-- Sectores sin tanques (Sólidos, Disp. Final Sólidos, NFU, Compost): un ledger
-- simple por sector (fact_stock_sector) para que dejen de estar "sin dato":
-- alimenta la cuenta corriente, el KPI de sólidos del área, la actividad del
-- sector y su home.
-- ============================================================================
ALTER TABLE produccion.dim_sector_nav ADD COLUMN IF NOT EXISTS stock_simple boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN produccion.dim_sector_nav.stock_simple IS 'Sector sin tanques: lleva su stock en fact_stock_sector (home simple con carga de movimientos).';
UPDATE produccion.dim_sector_nav SET stock_simple = true, tiene_datos = true, actualizado_en = now()
 WHERE codigo IN ('SOLIDOS', 'DF_SOLIDOS', 'NFU', 'COMPOST');

CREATE TABLE IF NOT EXISTS produccion.fact_stock_sector (
    id_mov        bigserial PRIMARY KEY,
    sector_nav    text        NOT NULL REFERENCES produccion.dim_sector_nav(codigo),
    producto      text        NOT NULL,
    tipo          text        NOT NULL CHECK (tipo IN ('ENTRADA', 'SALIDA', 'AJUSTE')),
    kg            numeric(14,2) NOT NULL,          -- siempre positivo; el signo lo da tipo (AJUSTE puede ser negativo)
    fecha         date        NOT NULL DEFAULT CURRENT_DATE,
    ticket        text,                            -- ticket de balanza / remito
    contraparte   text,                            -- cliente o proveedor
    observacion   text,
    id_usuario    integer,
    anulado       boolean     NOT NULL DEFAULT false,
    creado_en     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fact_stock_sector_idx ON produccion.fact_stock_sector (sector_nav, producto, fecha);
COMMENT ON TABLE produccion.fact_stock_sector IS
  'Ledger simple de stock para sectores sin tanques (sólidos, NFU, compost…): entradas, salidas y ajustes en kg por producto.';

CREATE OR REPLACE VIEW produccion.v_stock_sector_saldo AS
SELECT sector_nav, producto,
       SUM(CASE tipo WHEN 'ENTRADA' THEN kg WHEN 'SALIDA' THEN -kg ELSE kg END) AS saldo_kg,
       count(*) AS movimientos, max(fecha) AS ultimo_mov
FROM produccion.fact_stock_sector WHERE NOT anulado
GROUP BY sector_nav, producto;

-- ---------------------------------------------------------------- cuenta corriente unificada
CREATE OR REPLACE VIEW produccion.v_cuenta_corriente_producto AS
WITH led AS (
    SELECT m.momento, m.momento::date AS fecha, m.producto,
           CASE m.rol WHEN 'MP' THEN 'MP' WHEN 'INSUMO' THEN 'INSUMO' WHEN 'CATALIZADOR' THEN 'INSUMO'
                      WHEN 'PRODUCTO_FINAL' THEN 'PT' WHEN 'SUBPRODUCTO' THEN 'PT'
                      ELSE COALESCE(CASE dp.tipo_producto WHEN 'FINAL' THEN 'PT' ELSE dp.tipo_producto END, 'OTRO') END AS grupo,
           COALESCE(m.ticket_porteria, m.identificador_prod, m.ticket_mov) AS ticket,
           m.identificador_prod AS op,
           COALESCE(tx.cliente, tx.transporte) AS cc,
           COALESCE(tx.procedencia, tx.destino_final) AS contraparte,
           m.estado_mov AS estado, m.tipo_movimiento AS tipo, m.origen,
           COALESCE(dt.sector, m.fuente) AS sector,
           m.tanque_label,
           GREATEST(m.kg_neto, 0) AS ingreso_kg, GREATEST(-m.kg_neto, 0) AS egreso_kg, m.kg_neto,
           m.observaciones AS observacion, m.ticket_mov AS ref
    FROM reporting.v_movimientos_stock m
    LEFT JOIN produccion.dim_tanque dt
           ON dt.codigo = m.tanque_label OR dt.nombre = m.tanque_label
           OR (dt.id_tanque::text || ' · ' || dt.nombre) = m.tanque_label
    LEFT JOIN produccion.dim_producto dp ON dp.codigo_producto = m.producto
    LEFT JOIN LATERAL (
        SELECT t.cliente, t.transporte, t.procedencia, t.destino_final
        FROM produccion.v_transacciones_limpias t
        WHERE m.ticket_porteria IS NOT NULL
          AND regexp_replace(CAST(t.transaccion AS text), '\.0+$', '') = regexp_replace(m.ticket_porteria, '\.0+$', '')
        ORDER BY t.fecha_entrada DESC NULLS LAST LIMIT 1) tx ON true
    WHERE m.estado_mov = 'EJECUTADO' AND COALESCE(m.kg_neto, 0) <> 0
    UNION ALL
    SELECT ((f.fecha + (f.creado_en AT TIME ZONE 'America/Argentina/Buenos_Aires')::time)::timestamp AT TIME ZONE 'America/Argentina/Buenos_Aires')::timestamptz,
           f.fecha, f.producto,
           COALESCE(CASE dp.tipo_producto WHEN 'FINAL' THEN 'PT' ELSE dp.tipo_producto END, 'MP'),
           f.ticket, NULL, f.contraparte, f.contraparte, 'EJECUTADO', f.tipo, 'stock_sector',
           s.nombre_ui, NULL,
           CASE WHEN f.tipo = 'ENTRADA' OR (f.tipo = 'AJUSTE' AND f.kg > 0) THEN abs(f.kg) ELSE 0 END,
           CASE WHEN f.tipo = 'SALIDA'  OR (f.tipo = 'AJUSTE' AND f.kg < 0) THEN abs(f.kg) ELSE 0 END,
           CASE f.tipo WHEN 'ENTRADA' THEN f.kg WHEN 'SALIDA' THEN -f.kg ELSE f.kg END,
           f.observacion, 'SS-' || f.id_mov
    FROM produccion.fact_stock_sector f
    JOIN produccion.dim_sector_nav s ON s.codigo = f.sector_nav
    LEFT JOIN produccion.dim_producto dp ON dp.codigo_producto = f.producto
    WHERE NOT f.anulado
)
SELECT led.*,
       SUM(kg_neto) OVER (PARTITION BY producto ORDER BY momento, ref ROWS UNBOUNDED PRECEDING) AS saldo_kg
FROM led;

-- ---------------------------------------------------------------- sectores simples: actividad y KPI
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
),
ss_hoy AS (
    SELECT sector_nav, count(*) AS n FROM produccion.fact_stock_sector
    WHERE NOT anulado AND fecha = CURRENT_DATE GROUP BY sector_nav
)
SELECT s.codigo, s.nombre_ui, s.icono, s.orden, s.tiene_datos, s.sector_gestion, s.sector_batch, s.seccion_clasica,
       COALESCE(b.activos, 0)      AS procesos_activos,
       COALESCE(b.planificados, 0) AS procesos_planificados,
       COALESCE(lg.n, 0) + COALESCE(b.hoy, 0) + COALESCE(ss.n, 0)
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
LEFT JOIN ss_hoy ss ON ss.sector_nav = s.codigo
LEFT JOIN pres   p  ON p.sector = s.codigo
LEFT JOIN pres   p2 ON p2.sector = s.sector_batch AND s.sector_batch <> s.codigo
WHERE s.activo;

-- KPI del área: sólidos = tanques en KG + saldos de los sectores simples
CREATE OR REPLACE VIEW produccion.v_kpi_area_produccion AS
WITH tk AS (
    SELECT p.*, t.unidad_stock
    FROM produccion.vw_tanque_panel p
    JOIN produccion.dim_tanque t ON t.id_tanque = p.id_tanque
    WHERE p.activo AND COALESCE(p.condicion, 'EN USO') <> 'FUERA DE USO'
),
tq AS (
    SELECT count(*) AS n,
           count(*) FILTER (WHERE COALESCE(capacidad_litros,0) - COALESCE(litros_actual,0) >= 5000) AS n_con_espacio,
           SUM(COALESCE(capacidad_litros,0)) AS cap_l, SUM(COALESCE(litros_actual,0)) AS act_l,
           SUM(GREATEST(COALESCE(capacidad_litros,0) - COALESCE(litros_actual,0), 0)) AS libre_l,
           SUM(COALESCE(kg_actual,0)) AS kg
    FROM tk WHERE COALESCE(tipo_tanque,'') <> 'Pileta' AND COALESCE(unidad_stock,'L') = 'L'
),
pi AS (
    SELECT count(*) AS n, SUM(COALESCE(capacidad_litros,0)) AS cap_l, SUM(COALESCE(litros_actual,0)) AS act_l,
           SUM(GREATEST(COALESCE(capacidad_litros,0) - COALESCE(litros_actual,0), 0)) AS libre_l
    FROM tk WHERE COALESCE(tipo_tanque,'') = 'Pileta'
),
so AS (
    SELECT (SELECT count(*) FROM tk WHERE COALESCE(unidad_stock,'L') = 'KG')
         + (SELECT count(*) FROM produccion.v_stock_sector_saldo WHERE saldo_kg > 0) AS n,
           (SELECT COALESCE(SUM(kg_actual),0) FROM tk WHERE COALESCE(unidad_stock,'L') = 'KG')
         + (SELECT COALESCE(SUM(saldo_kg),0) FROM produccion.v_stock_sector_saldo) AS kg
),
cam AS (
    SELECT count(*) AS n,
           COALESCE(json_object_agg(corriente, n ORDER BY n DESC) FILTER (WHERE corriente IS NOT NULL), '{}'::json) AS por_corriente
    FROM (SELECT COALESCE(corriente, 'sin_declarar') AS corriente, count(*) AS n
          FROM produccion.v_transacciones_limpias
          WHERE fecha_entrada >= CURRENT_DATE - 1 AND fecha_salida IS NULL AND estado_camion = 'ADENTRO'
          GROUP BY 1) x
),
afe AS (
    SELECT count(*) AS n
    FROM (SELECT DISTINCT regexp_replace(l.ticket, '\.0+$', '') AS tk
          FROM produccion.lab_evaluaciones l
          WHERE l.fecha >= now() - interval '7 days'
            AND upper(btrim(COALESCE(l.producto_lab,''))) = 'AFE'
            AND COALESCE(l.ticket,'') <> ''
            AND upper(COALESCE(l.rechazado,'')) NOT IN ('RECHAZADO','REMUESTREO')) le
    WHERE NOT EXISTS (SELECT 1 FROM produccion.fact_asignacion_afe a WHERE a.ticket = le.tk AND a.estado = 'CONFIRMADO')
),
pers AS (
    SELECT (SELECT count(*) FROM produccion.v_presencia_actual) AS presentes,
           (SELECT count(*) FROM produccion.dim_usuario WHERE activo AND ultimo_login > now() - interval '10 hours') AS logins_10h
),
sec AS (
    SELECT count(*) FILTER (WHERE procesos_activos > 0 OR eventos_hoy > 0 OR personal_presente > 0) AS activos,
           count(*) FILTER (WHERE tiene_datos) AS con_datos, count(*) AS total,
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
