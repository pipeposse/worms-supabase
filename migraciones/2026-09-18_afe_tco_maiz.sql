-- ============================================================================
-- 2026-09-18 · SOL-0046 · El AFE de maíz pasa a la familia AFE (AFE-TCO)
--
-- Pedido de laboratorio: "falta una categoría de calidad nueva. Producto base AFE,
-- corriente vegetal, calidad final TCO → AFE-TCO".
--
-- Lo que pasaba: el producto YA existía, con el código "TCO" y el nombre "AFE Maíz".
-- Pero estaba colgado afuera de la familia AFE, como un producto suelto con calidad
-- única, así que en el formulario de laboratorio no había manera de cargarlo como AFE.
-- Encima el comentario del código decía que la variante "M" era maíz cuando en realidad
-- es maní (se había corregido en el diccionario en 09/2026 pero no en la lista del
-- formulario). Entre las dos cosas, el maíz no tenía dónde cargarse.
--
-- El producto nunca se usó: 0 movimientos de stock, 0 tanques designados, 0 camiones por
-- balanza, 0 evaluaciones de laboratorio. Por eso se puede renombrar el código sin
-- romper historia, en vez de dar de alta un producto nuevo y quedarse con dos.
--
-- Consecuencia buscada: al empezar el código con "AFE", el maíz entra solo en todo lo
-- que ya funciona para la familia — la pantalla de asignación de tanque de AFE, y el
-- grado A/B/C/D que sale del azufre y el fósforo del tanque. Las cuentas de stock van a
-- ser V-AFE-TCO-A, -B, -C, -D y V-AFE-TCO-NE mientras laboratorio no lo haya medido.
--
-- Los parámetros propios del maíz se mantienen como estaban (acidez <= 13,0 ·
-- agua+sedimento+gomas <= 2,0 · fósforo <= 500): son distintos de los de la soja y no
-- se tocan.
-- ============================================================================

BEGIN;

UPDATE produccion.dim_producto
   SET codigo_producto = 'AFE-TCO', rotulo_oficial = 'AFE-TCO', actualizado_en = now()
 WHERE codigo_producto = 'TCO';

-- Laboratorio deja de elegir "TCO / calidad UNICA" y pasa a elegir "AFE / calidad TCO",
-- igual que AFE/S, AFE/SG, AFE/G, AFE/AL, AFE/P y AFE/M.
UPDATE produccion.dic_producto_lab
   SET lab_producto = 'AFE', lab_calidad = 'TCO',
       notas = 'maíz (TCO) — SOL-0046: pasa a la familia AFE'
 WHERE lab_producto = 'TCO' AND lab_calidad = 'UNICA';

UPDATE produccion.dim_maestro_producto
   SET codigo_oficial = 'AFE-TCO', nombre = 'AFE-TCO', rotulo_oficial = 'AFE-TCO'
 WHERE codigo_oficial = 'TCO';

UPDATE produccion.dim_maestro_parametro SET producto = 'AFE-TCO' WHERE btrim(producto) = 'TCO';

-- El maíz no tiene precio propio: se sigue valorizando a AG-C, como estaba.
UPDATE produccion.dim_precio_map SET codigo_producto = 'AFE-TCO' WHERE codigo_producto = 'TCO';

COMMIT;

-- Control. Resultado esperado:
--   resuelve AFE/TCO al producto      → 34
--   codigo y nombre                   → AFE-TCO · AFE Maíz · rótulo AFE-TCO
--   azufre 35 / fósforo 90            → V-AFE-TCO-A
--   azufre 48 / fósforo 140           → V-AFE-TCO-C
--   sin evaluar                       → V-AFE-TCO-NE
--   queda algún TCO suelto            → 0 en productos · 0 en laboratorio · 0 en parámetros
SELECT 'resuelve AFE/TCO al producto' t, produccion.fn_resolver_producto_lab('AFE','TCO')::text v
UNION ALL SELECT 'codigo y nombre', d.codigo_producto||' · '||d.nombre_producto||' · rótulo '||d.rotulo_oficial
  FROM produccion.dim_producto d WHERE d.id_producto = produccion.fn_resolver_producto_lab('AFE','TCO')
UNION ALL SELECT 'azufre 35 / fosforo 90',  (produccion.fn_cuenta_grado('AFE-TCO',35,90)).cuenta
UNION ALL SELECT 'azufre 48 / fosforo 140', (produccion.fn_cuenta_grado('AFE-TCO',48,140)).cuenta
UNION ALL SELECT 'sin evaluar',             (produccion.fn_cuenta_grado('AFE-TCO',NULL,NULL)).cuenta
UNION ALL SELECT 'queda algun TCO suelto',
  (SELECT count(*)::text FROM produccion.dim_producto WHERE codigo_producto='TCO')
  ||' en productos · '||(SELECT count(*)::text FROM produccion.dic_producto_lab WHERE lab_producto='TCO')
  ||' en parametros: '||(SELECT count(*)::text FROM produccion.dim_maestro_parametro WHERE btrim(producto)='TCO');
