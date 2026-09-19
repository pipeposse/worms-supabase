-- ============================================================================
-- 2026-09-19 · SOL-0043 · Exportación: "no sé si se guardó", cargas dobles, tickets
--              asignados a órdenes anuladas
--
-- SIN CAMBIOS DE ESQUEMA. El arreglo va en la app (despachos_section.py y guardado.py).
-- Acá queda lo que se encontró en la base, las consultas de control y una reparación
-- de datos que NO se corrió: hay que decidirla con planta (ver al final).
--
-- Qué se encontró, con fecha y hora, en la base:
--
--  1) Carga doble de una formulación. El 17/09 a las 19:11:06 se guardó la ODV 58
--     (VIROQUE ENERGY, ISO TANK, 8 contenedores, Tanque 10, 205.000 L) y 24 segundos
--     después, a las 19:11:30, la ODV 59, idéntica. Lo mismo el 03/09 con las ODV 42 y
--     43 (QUIMICA ATLANTICA). No es que la primera no se guardara: se guardó, pero la
--     pantalla no cambiaba. El recibo de guardado aparece ARRIBA del armador y el botón
--     Guardar está al FINAL de una pantalla larga; la formulación seguía cargada en
--     pantalla, así que se volvía a apretar.
--     Arreglo: después de guardar el armador queda vacío y muestra el recibo; el
--     recibo además tira un aviso en la esquina de la ventana (se ve esté donde esté
--     el scroll); y si igual se aprieta dos veces, la segunda NO crea otra orden: si
--     el mismo usuario guardó una orden igual (título, fecha, producto, contenedores)
--     hace menos de 15 minutos, se pisa esa y el recibo dice "ya estaba guardada, no se
--     duplicó".
--
--  2) Tres anulaciones seguidas el 17/09: ODV 59 a las 19:19, ODV 58 a las 19:21 y
--     ODV 57 (CARGAS / VIKA) a las 19:48. El selector "Cambiar estado" tenía una sola
--     key para todas las órdenes: el estado elegido para una (ANULADO) quedaba puesto
--     al pasar a la siguiente, y "Aplicar" la anulaba también. Se anuló la duplicada
--     (58) y de paso la original (59) y otra más (57).
--     Arreglo: selector y botón con key por orden; "Aplicar" deshabilitado si no se
--     cambió nada; anular pide una confirmación explícita que dice qué va a pasar.
--
--  3) Tickets asignados a órdenes anuladas. El 18/09 a las 19:33 se asignaron 8
--     tickets (184,3 TN) a la ODV 59 y a las 19:40 otros 4 (89,4 TN) a la ODV 57, las
--     dos ANULADAS. La vista de tickets ofrecía las anuladas igual que las vivas. Una
--     orden anulada no genera salida de stock: esos 12 camiones salieron de planta y
--     no se descontaron de ningún tanque.
--     Arreglo: la vista de tickets no ofrece órdenes anuladas y muestra el estado de
--     cada una en el selector.
--
--  4) "Se borra pero no surge efecto" / "no da el OK": en toda la sección el mensaje
--     de guardado se mostraba y el redibujo inmediato se lo llevaba (cambio de estado,
--     borrado, renombrar, confirmar, quitar tickets, cierre parcial, medición y
--     parámetros de tanque, cierre desde el monitor de baja). Ahora cada acción deja un
--     recibo que sobrevive al redibujo, con la hora y con lo que se comprobó releyendo
--     la base ("estado leído de la base: ANULADO", "ya no está en la base", etc.).
--
--  5) "Descarga semanal no funciona correctamente": sin síntoma concreto no se pudo
--     reproducir. Falta saber qué se apretó y qué se vio.
-- ============================================================================

-- Control 1: órdenes duplicadas (mismo título, fecha, producto y contenedores, del
-- mismo usuario, creadas con menos de 15 minutos de diferencia). Esperado hoy:
-- 42/43 (03/09) y 58/59 (17/09). Con el arreglo de la app no deberían aparecer más.
SELECT a.id_despacho AS primera, b.id_despacho AS repetida, a.titulo, a.cliente,
       a.creado_por, a.creado_en, b.creado_en - a.creado_en AS diferencia,
       a.estado AS estado_primera, b.estado AS estado_repetida
  FROM produccion.fact_despacho a
  JOIN produccion.fact_despacho b
    ON b.id_despacho > a.id_despacho
   AND b.creado_por = a.creado_por AND b.titulo = a.titulo
   AND b.fecha_despacho = a.fecha_despacho AND b.producto_codigo = a.producto_codigo
   AND b.n_contenedores = a.n_contenedores
   AND b.creado_en - a.creado_en < interval '15 minutes'
 ORDER BY a.id_despacho;

-- Control 2: tickets colgados de órdenes anuladas (camiones que salieron sin salida de
-- stock). Esperado hoy: ODV 57 con 4 tickets / 89,4 TN y ODV 59 con 8 / 184,3 TN.
-- Después de la reparación de abajo tiene que dar 0 filas.
SELECT d.id_despacho, d.titulo, d.cliente, d.fecha_despacho, d.estado,
       count(a.id_dt) AS tickets, round(coalesce(sum(a.kg),0)/1000.0, 1) AS tn,
       (SELECT count(*) FROM produccion.fact_movimiento_stock m
         WHERE m.id_despacho = d.id_despacho AND m.origen = 'despacho') AS movimientos_stock
  FROM produccion.fact_despacho d
  JOIN produccion.fact_despacho_ticket a ON a.id_despacho = d.id_despacho
 WHERE COALESCE(d.estado,'') = 'ANULADO'
 GROUP BY 1,2,3,4,5 ORDER BY 1;

-- ----------------------------------------------------------------------------
-- REPARACIÓN PENDIENTE DE DECISIÓN (no se corrió). Planta asignó los tickets el 18/09
-- a las ODV 57 y 59, es decir que las considera las órdenes reales; la 58 es la
-- duplicada. Volverlas a CONFIRMADO hace que el trigger regenere la salida de stock
-- con los kg pesados: 57 → 89,4 TN repartidas en sus 6 líneas (Base plana nueva 5, 8,
-- 15, 18, 19 y Tanque 11); 59 → 184,3 TN del Tanque 10 (ARE-A-ANIMAL). Tocar el stock
-- de esos tanques es una decisión de planta, no de la app.
--
-- BEGIN;
-- UPDATE produccion.fact_despacho SET estado = 'CONFIRMADO', actualizado_en = now()
--  WHERE id_despacho IN (57, 59) AND estado = 'ANULADO';
-- -- la 58 se puede dejar anulada (queda como constancia) o borrar del todo:
-- -- DELETE FROM produccion.fact_despacho WHERE id_despacho = 58 AND estado = 'ANULADO';
-- COMMIT;
--
-- Control posterior: la 57 y la 59 con movimientos de stock y las TN de sus tickets.
-- SELECT d.id_despacho, d.estado,
--        (SELECT count(*) FROM produccion.fact_movimiento_stock m
--          WHERE m.id_despacho = d.id_despacho AND m.origen = 'despacho') AS movimientos,
--        (SELECT round(coalesce(sum(m.kg),0)/1000.0,1) FROM produccion.fact_movimiento_stock m
--          WHERE m.id_despacho = d.id_despacho AND m.origen = 'despacho') AS tn_descontadas
--   FROM produccion.fact_despacho d WHERE d.id_despacho IN (57, 58, 59) ORDER BY 1;
