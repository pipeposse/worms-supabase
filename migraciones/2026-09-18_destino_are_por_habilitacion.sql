-- ============================================================================
-- 2026-09-18 · "Habilitar TK 11 para acopio de ARE A-B" y "habilitar TK 10 para
--               producción de ARE animal": no daba la opción en el Centro de Planificación
--
-- SIN CAMBIOS DE DATOS. Los dos tanques ya estaban habilitados correctamente. El arreglo
-- es de la pantalla y va en planificacion.py; acá quedan las consultas de verificación.
--
-- Qué pasaba. El selector "Tanque destino ARE final" del Centro de Planificación pedía:
--
--     WHERE COALESCE(t.activo,true)
--       AND (p.codigo_producto = 'ARE-B' OR t.sector ILIKE 'Exporta%')
--
-- Dos errores en una línea:
--
--  1) Filtraba por el producto PRINCIPAL del tanque, no por los productos habilitados.
--     La habilitación existe desde siempre en dim_tanque_producto y está bien cargada:
--     el Tanque 11 figura habilitado para ARE-A (principal), ARE-A-ANIMAL y ARE-B, y el
--     Tanque 10 para ARE-A-ANIMAL. Esta pantalla no la miraba. De ahí los dos pedidos de
--     "habilitar": los tanques ya estaban habilitados, la pantalla no lo leía.
--
--  2) Pedía 'ARE-B' fijo en lugar del producto final que la reacción va a producir. Una
--     Rx de ARE animal no ofrecía ningún tanque de Reactores.
--
--  Y de paso: `t.sector ILIKE 'Exporta%'` nunca matcheó nada. Los tanques de exportación
--  tienen sector 'Plataforma 1 (BPV)', 'Plataforma 2 (BPN)' y 'Plataforma central'. Era
--  código muerto, y por eso el selector terminaba mostrando sólo dos tanques. Se quitó:
--  los tanques de plataforma que sí reciben ARE ya están en la habilitación.
--
-- Ahora la pantalla ofrece los tanques habilitados para el producto final elegido, con el
-- principal primero, y si no hay ninguno lo dice y manda a Admin → Tanques. Habilitar un
-- tanque para otro producto pasa a ser un cambio de datos, no de código.
-- ============================================================================

-- Verificación 1: qué tanques ofrece ahora cada producto final de reactores.
-- Esperado: ARE-B 13 tanques (incluye Tanque 11) · ARE-A-ANIMAL 5 (incluye Tanque 10) ·
--           ARE-A 4 · POLIGLICEROL 0 (nadie lo habilitó todavía).
WITH prod AS (SELECT unnest(ARRAY['ARE-A','ARE-A-ANIMAL','ARE-B','POLIGLICEROL']) AS cod)
SELECT prod.cod AS producto_final,
       count(t.id_tanque) AS tanques_ofrecidos,
       string_agg(t.nombre || CASE WHEN COALESCE(tp.es_principal,false) THEN ' (principal)' ELSE '' END,
                  ' · ' ORDER BY COALESCE(tp.es_principal,false) DESC, t.sector, t.nombre) AS lista
  FROM prod
  LEFT JOIN (produccion.dim_tanque_producto tp
             JOIN produccion.dim_producto p ON p.id_producto = tp.id_producto
             JOIN produccion.dim_tanque t   ON t.id_tanque   = tp.id_tanque
                  AND COALESCE(t.activo,true)
                  AND COALESCE(t.condicion,'') <> 'FUERA DE USO')
         ON p.codigo_producto = prod.cod
 GROUP BY 1 ORDER BY 1;

-- Verificación 2: los dos tanques del reporte, con todo lo que tienen habilitado.
SELECT t.nombre, t.sector, p.codigo_producto, tp.es_principal
  FROM produccion.dim_tanque t
  JOIN produccion.dim_tanque_producto tp ON tp.id_tanque = t.id_tanque
  JOIN produccion.dim_producto p ON p.id_producto = tp.id_producto
 WHERE t.nombre IN ('Tanque 10','Tanque 11')
 ORDER BY t.nombre, tp.es_principal DESC, p.codigo_producto;

-- Pendiente aparte, para revisar con planta: dim_tanque.id_producto_principal y el
-- es_principal de dim_tanque_producto no siempre coinciden. El Tanque 10 tiene
-- ARE-A-ANIMAL como principal en dim_tanque y AG-C como principal en la habilitación, y
-- producto_principal_txt (texto libre, que no lee nadie) dice otra cosa más. Conviene
-- elegir una sola fuente; la habilitación es la que usan las pantallas.
SELECT t.nombre, t.sector,
       pp.codigo_producto AS principal_en_dim_tanque,
       ph.codigo_producto AS principal_en_habilitacion,
       t.producto_principal_txt AS texto_libre
  FROM produccion.dim_tanque t
  LEFT JOIN produccion.dim_producto pp ON pp.id_producto = t.id_producto_principal
  LEFT JOIN produccion.dim_tanque_producto tph
         ON tph.id_tanque = t.id_tanque AND tph.es_principal
  LEFT JOIN produccion.dim_producto ph ON ph.id_producto = tph.id_producto
 WHERE COALESCE(t.activo,true)
   AND COALESCE(pp.codigo_producto,'') <> COALESCE(ph.codigo_producto,'')
 ORDER BY t.sector, t.nombre;
