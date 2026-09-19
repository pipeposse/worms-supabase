-- ============================================================================
-- 2026-09-19 · SOL-0051 · Instructivo de la reacción: "Confirmar paso 3 no responde"
--              y "reacciones frenadas"
--
-- El arreglo va en la app (op_instructivo.py y carga_por_id.py). Acá: lo que se
-- encontró en la base, y UNA corrección de datos (horas corridas 3 h) que hay que
-- correr a mano — está al final.
--
-- Qué se encontró.
--
--  1) El paso 3 (POTASIO, 125 kg) de RE-416 SÍ se guardó: fact_paso_medicion lo tiene
--     a las 20:52:23 del 18/09 con usuario euge, y la vista lo da como hecho. Lo que
--     falló es el primer click. La cantidad era un campo suelto seguido de un botón:
--     el operario escribe los kg y va derecho a "Confirmar"; al salir del campo, ese
--     campo dispara un redibujo y el click del botón cae en el medio y se descarta.
--     Los kg quedan en pantalla, el paso sigue azul, y parece que el botón no anda. El
--     segundo click sí entra. Es el mismo patrón que en exportación ("tuve que hacerlo
--     dos veces").
--     Arreglo: cada paso es un formulario: el campo no dispara nada y el botón manda
--     valor y click juntos. Después de confirmar, queda un recibo con la hora y con lo
--     que se releyó de la base ("el paso figura como hecho"), un aviso en la esquina, y
--     el selector salta solo al próximo paso pendiente (antes quedaba clavado en el que
--     se acababa de confirmar; por eso hay revisiones cargadas en la "hora 4" con las
--     horas 1 a 3 vacías).
--
--  2) Lo mismo en "GUARDAR MEDICIÓN" durante la reacción (acidez y temperatura). Si
--     ese click se pierde, la medición no se guarda, la acidez nunca "baja" y la
--     reacción no pasa a reposo: eso es una reacción frenada. También va en formulario,
--     con recibo.
--
--  3) Las horas del instructivo estaban corridas 3 horas. "Inicio ahora" / "Fin ahora"
--     tomaban la hora del servidor (UTC) y la base la guardaba como hora Argentina:
--     el paso 1 de RE-416 figura 16:34 y se cargó a las 13:34. Son 8 registros en 5
--     reacciones, todos con 3,00 h exactas de diferencia contra la hora real de carga.
--     Arreglo en la app: hora local de planta. Los registros viejos se corrigen abajo.
--
--  4) El bloque del instructivo decía correr en su propio fragmento pero el decorador
--     había quedado sobre otra función: cada confirmación redibujaba TODA la pantalla
--     de Producción en planta. Ahora redibuja sólo el instructivo.
-- ============================================================================

-- Control 1: el paso 3 de RE-416 está guardado y hecho.
SELECT m.id_batch, m.orden, m.cantidad, m.actualizado_en, u.nombre, v.hecho
  FROM produccion.fact_paso_medicion m
  JOIN produccion.v_op_instructivo v ON v.id_batch = m.id_batch AND v.orden = m.orden
  LEFT JOIN produccion.dim_usuario u ON u.id_usuario = m.id_usuario
 WHERE m.id_batch = 230 AND m.orden = 3;

-- Control 2: horas corridas (inicio o fin 3 h DESPUÉS de la hora en que se guardó,
-- cosa imposible salvo por el corrimiento). Esperado antes de corregir: 8 filas.
SELECT id_batch, orden, etapa, inicio_ts, fin_ts, actualizado_en,
       round(extract(epoch from (inicio_ts - actualizado_en))/3600.0, 2) AS h_ini,
       round(extract(epoch from (fin_ts - actualizado_en))/3600.0, 2) AS h_fin
  FROM produccion.fact_paso_medicion
 WHERE inicio_ts > actualizado_en + interval '2 minutes'
    OR fin_ts   > actualizado_en + interval '2 minutes'
 ORDER BY actualizado_en;

-- Corrección: se restan las 3 h SÓLO a los que tienen exactamente ese corrimiento
-- (±2 min) — una hora cargada a mano en el futuro no se toca.
BEGIN;
UPDATE produccion.fact_paso_medicion
   SET inicio_ts = inicio_ts - interval '3 hours'
 WHERE inicio_ts > actualizado_en + interval '2 minutes'
   AND abs(extract(epoch from (inicio_ts - actualizado_en)) - 10800) < 120;
UPDATE produccion.fact_paso_medicion
   SET fin_ts = fin_ts - interval '3 hours'
 WHERE fin_ts > actualizado_en + interval '2 minutes'
   AND abs(extract(epoch from (fin_ts - actualizado_en)) - 10800) < 120;
COMMIT;

-- Control posterior: tiene que dar 0.
SELECT count(*) AS siguen_corridos
  FROM produccion.fact_paso_medicion
 WHERE inicio_ts > actualizado_en + interval '2 minutes'
    OR fin_ts   > actualizado_en + interval '2 minutes';
