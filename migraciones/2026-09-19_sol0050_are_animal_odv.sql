-- ============================================================================
-- 2026-09-19 · SOL-0050 · "Agregar ARE-AN en las órdenes de venta"
--
-- SIN CAMBIOS DE DATOS NI DE ESQUEMA. El ARE animal YA se puede vender: existe como
-- producto (ARE-A-ANIMAL, rótulo AN-ARE-A), está activo, tiene densidad y tiene dos
-- tanques asignados con stock — Tanque 5 (39.779 L) y Tanque 10 (16.252 L) — y de hecho
-- se cargaron dos órdenes suyas el 17/09. El arreglo va en la app.
--
-- Por qué no aparece en la pantalla de la semana (la de la captura). Esa lista de
-- materias primas no es un catálogo: se arma con los productos que aparecen en las
-- órdenes CONFIRMADAS o CARGADAS del período. Las dos únicas órdenes de ARE animal son
-- la #58 y la #59, las dos ANULADAS el 17/09 por el problema del selector de estado
-- (SOL-0043). Por eso el ARE animal no figura: no hay ninguna orden viva suya. Al
-- restaurarlas — la decisión que quedó pendiente en SOL-0043 — aparece solo.
--
-- El problema de fondo, que sí se arregla. Los cuatro máximos de la especificación
-- estaban fijos en el código con los valores de la exportación de AG-E:
--
--     acidez 5,0 · agua+sedimento 2,0 · azufre 50 · fósforo 150
--
-- Esa es la especificación del AG-E, no la del producto que se vende. El ARE animal sale
-- de reactores con 154-177 ppm de azufre y 8,5-10,8 % de acidez: contra los máximos del
-- AG-E, una orden de ARE animal aparece como un desvío de más del 200 %, pide motivo
-- obligatorio, deshabilita el botón de guardar hasta escribirlo y dispara la aprobación
-- de dirección. La salida era teclear los cuatro números a mano cada vez: en la #58 y la
-- #59 figuran 12 · 2 · 300 · 300, escritos a mano.
--
-- Ahora los máximos de una orden salen del producto, en este orden:
--   1. lo que se usó la última vez para ESE producto (una orden no anulada);
--   2. el techo del maestro de calidad del producto ('<= 10,0');
--   3. la especificación de exportación, como hasta hoy.
-- Nunca se inventa un número: si el maestro mide el parámetro pero no lo limita, queda
-- el valor de exportación y la pantalla dice de dónde sale cada máximo. Se siguen
-- pudiendo pisar a mano, y lo que se deje es lo que propone la orden siguiente.
--
-- Para el ARE animal eso da hoy: acidez 10,0 y agua+sedimento 2,0 de su propia
-- especificación; azufre y fósforo quedan en los de exportación porque el maestro los
-- mide pero no los limita. En cuanto se restaure la orden #59, los máximos pasan a ser
-- los 12 · 2 · 300 · 300 que ya se habían usado.
--
-- OJO con el ARE-B: su maestro dice azufre '> 250' y fósforo '> 200'. Eso es un PISO que
-- define la calidad B, no un máximo de venta. Se toman sólo los techos ('<='); usar ese
-- piso como máximo sería al revés.
-- ============================================================================

-- Control 1: el ARE animal está listo para venderse (producto, densidad, tanques).
SELECT p.codigo_producto, p.rotulo_oficial, p.activo, p.densidad_g_ml,
       (SELECT count(*) FROM produccion.dim_tanque t
         WHERE t.id_producto_principal = p.id_producto AND COALESCE(t.activo,true)) AS tanques,
       (SELECT round(sum(COALESCE(v.litros_actual,0)))
          FROM produccion.vw_tanque_panel v JOIN produccion.dim_tanque t ON t.id_tanque = v.id_tanque
         WHERE t.id_producto_principal = p.id_producto) AS litros
  FROM produccion.dim_producto p WHERE p.codigo_producto = 'ARE-A-ANIMAL';

-- Control 2: por qué no figura en la semana — sus únicas órdenes están anuladas.
SELECT d.id_despacho, d.titulo, d.cliente, d.fecha_despacho, d.estado,
       d.spec_acidez_max, d.spec_ays_max, d.spec_azufre_max, d.spec_fosforo_max
  FROM produccion.fact_despacho d WHERE d.producto_codigo = 'ARE-A-ANIMAL' ORDER BY 1;

-- Control 3: los máximos que la pantalla va a proponer para cada producto que se vende.
-- 'techo del maestro' cuando la especificación del producto lo limita; vacío cuando lo
-- mide pero no lo limita (ahí queda el valor de exportación).
WITH v AS (
  SELECT codigo_producto, parametro, especificacion,
         CASE WHEN btrim(especificacion) LIKE '<=%'
              THEN replace(replace(btrim(substring(btrim(especificacion) from 3)), '.', ''), ',', '.')::numeric
         END AS techo
    FROM produccion.v_parametro_producto
   WHERE parametro IN ('% ACIDEZ', '% H2O - SEDIMENTO & Gomas', 'PPM AZUFRE', 'PPM FOSFORO'))
SELECT codigo_producto,
       max(techo) FILTER (WHERE parametro = '% ACIDEZ')                   AS acidez,
       max(techo) FILTER (WHERE parametro = '% H2O - SEDIMENTO & Gomas')  AS agua_sed,
       max(techo) FILTER (WHERE parametro = 'PPM AZUFRE')                 AS azufre,
       max(techo) FILTER (WHERE parametro = 'PPM FOSFORO')                AS fosforo
  FROM v
 WHERE codigo_producto IN ('AG-E','ARE-A','ARE-B','ARE-A-ANIMAL','AFE-S','AFE-M')
 GROUP BY 1 ORDER BY 1;

-- Control 4: la última especificación usada por producto, que es la que se propone.
SELECT DISTINCT ON (d.producto_codigo)
       d.producto_codigo, d.id_despacho, d.fecha_despacho, d.estado,
       d.spec_acidez_max, d.spec_ays_max, d.spec_azufre_max, d.spec_fosforo_max
  FROM produccion.fact_despacho d
 WHERE COALESCE(d.estado,'') <> 'ANULADO'
 ORDER BY d.producto_codigo, d.id_despacho DESC;

-- Pendiente aparte, para cargar con laboratorio: el maestro de calidad del ARE animal
-- mide el azufre y el fósforo pero no los limita, igual que el AFE Maní no tiene ningún
-- parámetro cargado. Mientras siga así, esos dos máximos salen de la especificación de
-- exportación, que no es la del producto.
SELECT codigo_producto, parametro, especificacion
  FROM produccion.v_parametro_producto
 WHERE codigo_producto = 'ARE-A-ANIMAL' AND parametro IN ('PPM AZUFRE','PPM FOSFORO');
