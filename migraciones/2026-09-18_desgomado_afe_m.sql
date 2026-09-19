-- ============================================================================
-- 2026-09-18 · DESGOMADO ACUOSO · habilitar AFE-M y que la reacción termine en AFE-M
--
-- Pedido: "en DESGOMADO ACUOSO hay que habilitar desgomar AFE-M, que termine siendo
-- la reacción AFE-M".
--
-- Había dos cosas rotas, una de datos y una de código.
--
-- 1) DATOS. La tabla que dice qué productos son válidos en cada proceso
--    (dic_proceso_producto) no tenía al maní en el desgomado acuoso: como materia
--    prima sólo aceptaba AFE-SG y AFE-G, y como producto final AFE-S y AFE-G. El maní
--    no aparecía para elegir. Eso se arregla acá.
--
-- 2) CÓDIGO (planificacion.py, ya corregido). El producto final del desgomado estaba
--    escrito al revés:
--
--        _dcod_fin = 'AFE-G' if str(mp).upper().startswith('AFE-G') else 'AFE-S'
--
--    O sea: cualquier cosa que no fuera girasol terminaba dando AFE-S. Aun habilitando
--    el maní en la tabla, desgomar AFE-M hubiera producido AFE de soja.
--
--    La regla real es más simple: el desgomado saca la goma y el agua, no cambia el
--    origen del aceite. El girasol sigue siendo girasol y el maní sigue siendo maní. La
--    única excepción es la soja CON goma (AFE-SG), que al desgomarse pasa a ser soja sin
--    goma (AFE-S). Quedó escrito así, y si algún día entra un producto que no tiene un
--    final propio registrado, la pantalla ofrece los finales habilitados del proceso en
--    lugar de forzar uno que no corresponde.
--
-- La pantalla de desgomado (desgomado.py) no necesitó cambios: ya toma el producto del
-- batch y no tiene ningún código fijo.
-- ============================================================================

BEGIN;

INSERT INTO produccion.dic_proceso_producto (sector, tipo_proceso, tipo_operacion, rol, patron, activo)
SELECT 'REACTORES', 'DESGOMADO_ACUOSO', 'PRODUCCION', v.rol, 'AFE-M', true
  FROM (VALUES ('MP'), ('FINAL')) AS v(rol)
 WHERE NOT EXISTS (
   SELECT 1 FROM produccion.dic_proceso_producto d
    WHERE d.sector = 'REACTORES' AND d.tipo_proceso = 'DESGOMADO_ACUOSO'
      AND d.rol = v.rol AND d.patron = 'AFE-M');

COMMIT;

-- Control 1: qué se puede desgomar y qué se puede producir ahora.
-- Esperado · MP: AFE-G, AFE-M, AFE-SG · FINAL: AFE-G, AFE-M, AFE-S
SELECT rol, string_agg(patron, ', ' ORDER BY patron) AS productos
  FROM produccion.dic_proceso_producto
 WHERE sector = 'REACTORES' AND tipo_proceso = 'DESGOMADO_ACUOSO' AND COALESCE(activo,true)
 GROUP BY rol ORDER BY rol;

-- Control 2: la regla nueva de producto final, y cuántos tanques pueden recibirlo.
-- Esperado · AFE-SG → AFE-S (52 tanques) · AFE-G → AFE-G (43) · AFE-M → AFE-M (44)
WITH mp AS (SELECT unnest(ARRAY['AFE-SG','AFE-G','AFE-M']) AS entra)
SELECT mp.entra AS materia_prima,
       CASE WHEN mp.entra = 'AFE-SG' THEN 'AFE-S' ELSE mp.entra END AS sale,
       (SELECT count(*)
          FROM produccion.dim_tanque_producto tp
          JOIN produccion.dim_producto p ON p.id_producto = tp.id_producto
          JOIN produccion.dim_tanque t   ON t.id_tanque   = tp.id_tanque
         WHERE COALESCE(t.activo,true)
           AND COALESCE(t.condicion,'') <> 'FUERA DE USO'
           AND p.codigo_producto = CASE WHEN mp.entra = 'AFE-SG' THEN 'AFE-S' ELSE mp.entra END
       ) AS tanques_habilitados
  FROM mp ORDER BY 1;

-- Pendiente a definir con planta, no se toca a ciegas: la tabla de salidas de
-- decantación (dic_decantacion_proceso) para DESGOMADO_ACUOSO tiene cargadas dos
-- salidas fijas — AFE_S → 'AFE-S' y FONDO_TANQUE → 'FONDO-TK'. Es decir que la pantalla
-- de decantación de un batch de maní va a seguir nombrando AFE-S. Hay que decidir si el
-- desgomado de maní necesita su propia salida (AFE_M → 'AFE-M') o si la salida tiene que
-- salir del producto del batch en lugar de estar fija por proceso.
SELECT * FROM produccion.dic_decantacion_proceso
 WHERE tipo_proceso = 'DESGOMADO_ACUOSO' ORDER BY 1;
