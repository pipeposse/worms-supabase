-- 2026-09-15 · Stock por sector = lo medido, no el libro.
--
-- Diagnóstico (Exportación, 15/09): la pantalla Stock del sector mostraba el saldo del
-- libro de movimientos (v_cuenta_corriente_producto): AFE-S 7.853.259 kg, cuando lo
-- medido en los 49 tanques de las plataformas es 1.031 t (964,6 t de AFE-S). Tres causas:
--   1. Los 3.492 movimientos "Ajuste por reconciliación" traen litros y kg NULL → el libro
--      en kg nunca se recuadra contra la medición física.
--   2. Los trasvases internos (cónico → base plana → reactor) no se registran: los cónicos
--      de 20-38 m³ acumulan 2.000 t de ingresos de portería sin salida.
--   3. Las salidas por despacho no matcheaban dim_tanque (la vista los buscaba por
--      tanque_label, que viene NULL) → caían en sector 'TANQUE' y el filtro "Sólo este
--      sector" las escondía: el sector veía sólo ingresos.
-- Además: 160 despachos de exportación en estado PLANIFICADO desde el 26/08 (2.379 t) que
-- nadie confirmó, y 11 movimientos de prueba del 02-04/06 (MS-00000001..11) con productos
-- que no existen en el maestro.
--
-- Decisión (misma que stock-panel-fisico, 14/07): el stock que se muestra es la ÚLTIMA
-- MEDICIÓN FÍSICA de cada tanque; el libro sirve para listar movimientos, con el saldo
-- anclado a esa medición (la fila más reciente = lo medido).

BEGIN;

-- 1) Una fila por tanque activo con su sector de navegación, producto y última medición.
CREATE OR REPLACE VIEW produccion.v_stock_tanque_fisico AS
WITH ult AS (
    SELECT DISTINCT ON (s.id_tanque)
           s.id_tanque, s.id_producto, s.kg, s.litros, s.nivel_pct, s.medido_en
    FROM produccion.fact_stock_tanque s
    ORDER BY s.id_tanque, s.medido_en DESC, s.creado_en DESC, s.id_stock DESC
)
SELECT t.id_tanque, t.codigo, t.nombre, t.sector AS sector_tanque, t.capacidad_litros,
       n.codigo AS sector_nav, n.nombre_ui AS sector_nombre,
       COALESCE(dp.codigo_producto, dp2.codigo_producto) AS producto,
       COALESCE(dp.nombre_producto, dp2.nombre_producto) AS producto_nombre,
       u.kg AS kg_medido, u.litros AS litros_medido, u.nivel_pct, u.medido_en,
       (u.medido_en IS NULL OR u.medido_en < now() - interval '2 days') AS medicion_vieja
FROM produccion.dim_tanque t
LEFT JOIN ult u ON u.id_tanque = t.id_tanque
LEFT JOIN LATERAL (
    SELECT s.codigo, s.nombre_ui FROM produccion.dim_sector_nav s
    WHERE s.activo AND s.patron_tanques IS NOT NULL AND t.sector ~ s.patron_tanques
    ORDER BY s.orden LIMIT 1) n ON true
LEFT JOIN produccion.dim_producto dp  ON dp.id_producto  = u.id_producto
LEFT JOIN produccion.dim_producto dp2 ON dp2.id_producto = t.id_producto_principal
WHERE t.activo;

COMMENT ON VIEW produccion.v_stock_tanque_fisico IS
 'Última medición física por tanque activo, con el sector de navegación (dim_sector_nav.patron_tanques) y el producto medido (o el principal del tanque). Es la verdad del stock; el libro de movimientos NO.';

-- 2) La cuenta corriente resuelve el tanque por id (no por etiqueta) → el sector de las
--    salidas por despacho / decantación / ajuste manual queda bien. Se agrega id_tanque al final.
CREATE OR REPLACE VIEW produccion.v_cuenta_corriente_producto AS
WITH led AS (
    SELECT m.momento,
           m.momento::date AS fecha,
           m.producto,
           CASE m.rol
               WHEN 'MP' THEN 'MP' WHEN 'INSUMO' THEN 'INSUMO' WHEN 'CATALIZADOR' THEN 'INSUMO'
               WHEN 'PRODUCTO_FINAL' THEN 'PT' WHEN 'SUBPRODUCTO' THEN 'PT'
               ELSE COALESCE(CASE dp.tipo_producto WHEN 'FINAL' THEN 'PT' ELSE dp.tipo_producto END, 'OTRO')
           END AS grupo,
           COALESCE(m.ticket_porteria, m.identificador_prod, m.ticket_mov) AS ticket,
           m.identificador_prod AS op,
           COALESCE(tx.cliente, tx.transporte) AS cc,
           COALESCE(tx.procedencia, tx.destino_final) AS contraparte,
           m.estado_mov AS estado,
           m.tipo_movimiento AS tipo,
           m.origen,
           CASE WHEN m.origen = 'efluente_porteria' THEN 'Piletas (efluentes)'
                ELSE COALESCE(dt.sector, m.fuente) END AS sector,
           COALESCE(m.tanque_label, dt.codigo) AS tanque_label,
           GREATEST(m.sentido * COALESCE(m.kg, 0), 0)   AS ingreso_kg,
           GREATEST(-m.sentido * COALESCE(m.kg, 0), 0)  AS egreso_kg,
           m.sentido * COALESCE(m.kg, 0)                AS kg_neto,
           m.observaciones AS observacion,
           m.ticket_mov AS ref,
           m.id_tanque
    FROM produccion.fact_movimiento_stock m
    LEFT JOIN produccion.dim_tanque dt
           ON dt.id_tanque = m.id_tanque
           OR (m.id_tanque IS NULL AND (dt.codigo = m.tanque_label OR dt.nombre = m.tanque_label
                                        OR (dt.id_tanque::text || ' · ' || dt.nombre) = m.tanque_label))
    LEFT JOIN produccion.dim_producto dp ON dp.codigo_producto = m.producto
    LEFT JOIN LATERAL (
        SELECT t.cliente, t.transporte, t.procedencia, t.destino_final
        FROM produccion.v_transacciones_limpias t
        WHERE m.ticket_porteria IS NOT NULL
          AND regexp_replace(t.transaccion::text, '\.0+$', '') = regexp_replace(m.ticket_porteria, '\.0+$', '')
        ORDER BY t.fecha_entrada DESC NULLS LAST LIMIT 1) tx ON true
    WHERE m.anulado IS NOT TRUE
      AND m.estado_mov = 'EJECUTADO'
      AND COALESCE(m.kg, 0) <> 0
    UNION ALL
    SELECT ((f.fecha + (f.creado_en AT TIME ZONE 'America/Argentina/Buenos_Aires')::time) AT TIME ZONE 'America/Argentina/Buenos_Aires'),
           f.fecha, f.producto,
           COALESCE(CASE dp.tipo_producto WHEN 'FINAL' THEN 'PT' ELSE dp.tipo_producto END, 'MP'),
           f.ticket, NULL, f.contraparte, f.contraparte, 'EJECUTADO', f.tipo, 'stock_sector',
           s.nombre_ui, NULL,
           CASE WHEN f.tipo = 'ENTRADA' OR (f.tipo = 'AJUSTE' AND f.kg > 0) THEN abs(f.kg) ELSE 0 END,
           CASE WHEN f.tipo = 'SALIDA'  OR (f.tipo = 'AJUSTE' AND f.kg < 0) THEN abs(f.kg) ELSE 0 END,
           CASE f.tipo WHEN 'ENTRADA' THEN f.kg WHEN 'SALIDA' THEN -f.kg ELSE f.kg END,
           f.observacion, 'SS-' || f.id_mov, NULL
    FROM produccion.fact_stock_sector f
    JOIN produccion.dim_sector_nav s ON s.codigo = f.sector_nav
    LEFT JOIN produccion.dim_producto dp ON dp.codigo_producto = f.producto
    WHERE NOT f.anulado
)
SELECT momento, fecha, producto, grupo, ticket, op, cc, contraparte, estado, tipo, origen, sector,
       tanque_label, ingreso_kg, egreso_kg, kg_neto, observacion, ref,
       sum(kg_neto) OVER (PARTITION BY producto ORDER BY momento, ref ROWS UNBOUNDED PRECEDING) AS saldo_kg,
       id_tanque
FROM led;

-- 3) Despachos planificados sin confirmar, por sector de navegación (para avisarlo en la pantalla).
CREATE OR REPLACE VIEW produccion.v_despachos_sin_confirmar_sector AS
SELECT n.codigo AS sector_nav, m.producto, count(*) AS movimientos,
       sum(COALESCE(m.kg, 0)) AS kg, min(m.momento)::date AS desde, max(m.momento)::date AS hasta
FROM produccion.fact_movimiento_stock m
JOIN produccion.dim_tanque t ON t.id_tanque = m.id_tanque
JOIN LATERAL (
    SELECT s.codigo FROM produccion.dim_sector_nav s
    WHERE s.activo AND s.patron_tanques IS NOT NULL AND t.sector ~ s.patron_tanques
    ORDER BY s.orden LIMIT 1) n ON true
WHERE m.anulado IS NOT TRUE AND m.estado_mov = 'PLANIFICADO' AND m.tipo_movimiento = 'SALIDA'
GROUP BY n.codigo, m.producto;

-- 4) Movimientos de prueba del 02-04/06 (sin usuario, productos fuera del maestro): anulados.
UPDATE produccion.fact_movimiento_stock
   SET anulado = true,
       observaciones = COALESCE(observaciones, '') || ' · anulado 15/09/2026: movimiento de prueba (producto fuera del maestro, sin usuario)'
 WHERE id_mov_stock BETWEEN 1 AND 11 AND id_usuario IS NULL AND anulado IS NOT TRUE
   AND producto IN ('Ácido Graso A','Ácido Graso C','Ácido Graso D','Ácido Graso E','AFE Soja','AFE Soja con goma',
                    'ARE Vegetal B','Glicerina cruda','Ácido sulfúrico','Metilato de sodio','Soda cáustica');

COMMIT;
