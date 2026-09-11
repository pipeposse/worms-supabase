-- ============================================================================
-- % de ingresos evaluados por laboratorio
-- worms-prod · 2026-09-11 · aplicada
--
-- Pedido textual de dirección (Sistema WORMS.xlsx, hoja Producción, indicadores
-- de laboratorio): "el objetivo es evaluar el 100% de los ingresos" — y aclara
-- que ese indicador va en Portería.
--
-- La app ya lo calculaba, pero en pandas y sólo dentro de la vista Ingresos del
-- día. Acá queda como vista para que cualquier pantalla lea el MISMO número.
-- Respeta las mismas reglas configurables que usa app.py:
--   · dic_corriente_config.evaluable      (qué corrientes se evalúan)
--   · dic_producto_base_config            (ej. GANADO no se evalúa aunque su
--                                          corriente sí)
-- Sin esas dos exclusiones el porcentaje da mucho peor de lo real, porque mete
-- en el denominador camiones que nunca se analizan.
--
-- Medición al crear la vista: 76% a 7 días, 81% a 30 días. Lo que falta es casi
-- todo vegetal (58%).
-- ============================================================================
CREATE OR REPLACE VIEW produccion.v_kpi_ingresos_evaluados AS
WITH evaluable AS (
    SELECT t.fecha_entrada,
           t.corriente,
           upper(coalesce(t.evaluado, '')) = 'SI' AS evaluado
    FROM produccion.v_transacciones_limpias t
    WHERE t.fecha_entrada >= CURRENT_DATE - 30
      AND t.corriente IN (SELECT c.corriente FROM produccion.dic_corriente_config c WHERE c.evaluable)
      AND upper(coalesce(t.producto_base, '')) NOT IN (
            SELECT upper(p.producto_base) FROM produccion.dic_producto_base_config p WHERE NOT p.evaluable)
)
SELECT ventana,
       count(*)                                     AS ingresos,
       count(*) FILTER (WHERE evaluado)             AS evaluados,
       count(*) FILTER (WHERE NOT evaluado)         AS sin_evaluar,
       round(100.0 * count(*) FILTER (WHERE evaluado) / nullif(count(*), 0), 1) AS pct_evaluado,
       (SELECT string_agg(x.corriente || ' ' || x.pct || '%', ' · ' ORDER BY x.pct)
          FROM (SELECT e2.corriente,
                       round(100.0 * count(*) FILTER (WHERE e2.evaluado) / nullif(count(*), 0)) AS pct
                FROM evaluable e2
                WHERE e2.fecha_entrada >= CURRENT_DATE - 30
                GROUP BY e2.corriente
                HAVING round(100.0 * count(*) FILTER (WHERE e2.evaluado) / nullif(count(*), 0)) < 100) x
       )                                            AS peor_corriente
FROM (
    SELECT 'HOY'::text AS ventana, e.* FROM evaluable e WHERE e.fecha_entrada = CURRENT_DATE
    UNION ALL
    SELECT '7D', e.* FROM evaluable e WHERE e.fecha_entrada >= CURRENT_DATE - 7
    UNION ALL
    SELECT '30D', e.* FROM evaluable e
) q
GROUP BY ventana;

COMMENT ON VIEW produccion.v_kpi_ingresos_evaluados IS
    'Porcentaje de ingresos evaluados por laboratorio (hoy / 7 días / 30 días), con las mismas '
    'reglas de evaluabilidad que usa la sección Ingresos. Pedido de dirección: evaluar el 100%.';

-- El Panel de Control (nav/panel.py) lo muestra junto a la capacidad de acopio.
-- v_capacidad_ocupada_producto ya existía y no se tocó: es la que alimenta las
-- barras horizontales por producto que pidió el Excel.
