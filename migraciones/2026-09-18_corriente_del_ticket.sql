-- ============================================================================
-- 2026-09-18 · SOL-0044 · La corriente de un ticket la define laboratorio, no portería
--
-- Reporte (Eugenia, RE-415): dos tickets de AG descargados directo en el reactor
-- (6793 y 6794) no se podían imputar — "no son compatibles por no contar con la
-- corriente" — aunque en la carga de laboratorio figuran bien: corriente VEGETAL,
-- clasificación AG-C.
--
-- Qué pasaba. La pantalla del reactor tomaba la corriente del ticket de PORTERÍA
-- (v_transacciones_limpias.corriente), que sale de mapear a mano el texto que el
-- portero escribe en el producto (porteria_limpieza). Ahí "AG" a secas está cargado
-- en las tres corrientes —vegetal, animal y sin_declarar— porque por el nombre solo
-- no se puede saber: AG vegetal y AG de pescado se escriben igual. Estos dos tickets
-- cayeron en sin_declarar. Cuando la carga combina ticket + tanque, el control de
-- "no mezclar corrientes" comparaba SIN_DECLARAR contra VEGETAL, las tomaba como
-- distintas y deshabilitaba el botón de guardar.
--
-- No era un caso aislado: desde el 01/07 hay 267 tickets evaluados con sin_declarar,
-- de los cuales 108 son AG-C por 775,6 TN — justo la materia prima del reactor.
--
-- Cómo se resuelve. Si el laboratorio evaluó el ticket, ya eligió un producto, y ese
-- producto tiene corriente en el maestro. Esa es la fuente autoritativa. Portería queda
-- como respaldo y sólo cuando declaró vegetal o animal de verdad. Todo lo demás
-- (sin_declarar, sólido, insumo, efluente) devuelve NULL = SIN DATO, que es distinto de
-- tener una corriente en conflicto: un ticket sin declarar ya no puede chocar con nada.
--
-- Va como función y no como vista a propósito: la primera versión era una vista que
-- envolvía v_transacciones_limpias, y al joinearla contra la misma vista el listado de
-- tickets pasaba a escanear el libro de portería dos veces y se iba en timeout. Estas
-- funciones sólo pegan contra dic_producto_lab (31 filas) y dim_producto (50), así que
-- se pueden llamar por fila sin costo: el listado de tickets de AG-C sigue en ~270 ms.
-- ============================================================================

-- La corriente que el laboratorio le asignó a un ticket, vía el producto que eligió.
CREATE OR REPLACE FUNCTION produccion.fn_corriente_lab(p_lab_producto text, p_lab_calidad text)
RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT upper(dp.corriente)
    FROM produccion.dic_producto_lab dl
    JOIN produccion.dim_producto dp ON dp.id_producto = dl.id_producto
   WHERE upper(btrim(dl.lab_producto)) = upper(btrim(COALESCE(p_lab_producto,'')))
     AND upper(btrim(dl.lab_calidad))  = upper(btrim(COALESCE(p_lab_calidad,'')))
     AND upper(COALESCE(dp.corriente,'')) IN ('VEGETAL','ANIMAL')
   LIMIT 1;
$$;

-- Manda el laboratorio; portería sólo si declaró vegetal o animal. El resto: NULL.
CREATE OR REPLACE FUNCTION produccion.fn_corriente_ticket(
  p_lab_producto text, p_lab_calidad text, p_corriente_porteria text)
RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    produccion.fn_corriente_lab(p_lab_producto, p_lab_calidad),
    CASE WHEN upper(btrim(COALESCE(p_corriente_porteria,''))) IN ('VEGETAL','ANIMAL')
         THEN upper(btrim(p_corriente_porteria)) END);
$$;

GRANT EXECUTE ON FUNCTION produccion.fn_corriente_lab(text,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION produccion.fn_corriente_ticket(text,text,text) TO PUBLIC;

-- Control: los dos tickets del reporte tienen que pasar de sin_declarar a VEGETAL.
SELECT regexp_replace(t.transaccion::text,'\.0+$','') AS ticket,
       t.lab_producto, t.lab_calidad,
       t.corriente AS antes,
       produccion.fn_corriente_ticket(t.lab_producto, t.lab_calidad, t.corriente) AS ahora
  FROM produccion.v_transacciones_limpias t
 WHERE regexp_replace(t.transaccion::text,'\.0+$','') IN ('6793','6794');

-- Control: cuánto se destraba en total desde julio.
SELECT count(*) FILTER (WHERE upper(COALESCE(t.corriente,'')) NOT IN ('VEGETAL','ANIMAL')
                          AND produccion.fn_corriente_ticket(t.lab_producto, t.lab_calidad, t.corriente) IS NOT NULL)
         AS tickets_recuperados,
       count(*) FILTER (WHERE produccion.fn_corriente_ticket(t.lab_producto, t.lab_calidad, t.corriente) IS NULL)
         AS siguen_sin_dato
  FROM produccion.v_transacciones_limpias t
 WHERE t.lab_fecha IS NOT NULL AND t.fecha_entrada >= date '2026-07-01';
