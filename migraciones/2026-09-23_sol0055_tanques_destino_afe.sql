-- ============================================================================
-- 2026-09-23 · SOL-0055 · "Al cargar un AFE(SG) sólo me aparecen algunos tanques"
--
-- SIN CAMBIOS DE DATOS NI DE ESQUEMA. El arreglo va en la app (asignacion_afe.py y
-- lab_carga.py). Acá, qué pasaba y los controles.
--
-- Hay DOS tablas de "qué producto puede ir en qué tanque":
--   · dim_tanque_producto           — la que mantiene Admin → Tanques (441 filas).
--   · dim_tanque_producto_permitido — una tabla vieja que ninguna pantalla escribe
--                                     (397 filas), pero que cuatro pantallas leían.
-- Se fueron separando: 206 habilitaciones están sólo en la primera y 162 sólo en la
-- segunda. La asignación de descarga del AFE leía sólo la vieja: para AFE-SG tenía
-- 5 tanques, cuando la habilitación real tiene 42 de los 47 tanques de Exportación.
--
-- Arreglo: la asignación (y el tanque sugerido en la carga de laboratorio) toman un
-- tanque como candidato si está habilitado en CUALQUIERA de las dos tablas o es su
-- producto principal. Para AFE-SG en Exportación: de 5 tanques a 42.
--
-- Los 5 de Exportación que siguen sin ofrecerse para AFE-SG, y por qué:
--   Base plana vieja 9 y 20  — tanques de EMULSIÓN; no corresponde.
--   Base plana nueva 12, Tanque N° 1 100 m3, Tanque N° 2 100 m3 — habilitados para
--   AFE-S y AG-E pero no para AFE-SG. Si tienen que recibir AFE-SG, se habilita en
--   Admin → Tanques y aparecen solos.
-- ============================================================================

-- Control 1: tanques de Exportación que ofrece la asignación para AFE-SG (id 2).
-- Antes: 5. Ahora: 42.
SELECT count(*) AS ofrecidos
  FROM produccion.dim_tanque t
 WHERE t.sector ~ '^Plataforma' AND COALESCE(t.activo,true)
   AND COALESCE(t.condicion,'EN USO') <> 'FUERA DE USO' AND COALESCE(t.uso,'ACOPIO') = 'ACOPIO'
   AND (t.id_producto_principal = 2
        OR EXISTS (SELECT 1 FROM produccion.dim_tanque_producto tp WHERE tp.id_tanque = t.id_tanque AND tp.id_producto = 2)
        OR EXISTS (SELECT 1 FROM produccion.dim_tanque_producto_permitido pp WHERE pp.id_tanque = t.id_tanque AND pp.id_producto = 2));

-- Control 2: los que quedan afuera para AFE-SG en Exportación, con lo que sí tienen habilitado.
SELECT t.nombre, t.sector, p.codigo_producto AS principal,
       (SELECT string_agg(p2.codigo_producto, ', ' ORDER BY p2.codigo_producto)
          FROM produccion.dim_tanque_producto tp JOIN produccion.dim_producto p2 ON p2.id_producto = tp.id_producto
         WHERE tp.id_tanque = t.id_tanque) AS habilitados
  FROM produccion.dim_tanque t LEFT JOIN produccion.dim_producto p ON p.id_producto = t.id_producto_principal
 WHERE t.sector ~ '^Plataforma' AND COALESCE(t.activo,true) AND COALESCE(t.condicion,'EN USO') <> 'FUERA DE USO'
   AND COALESCE(t.id_producto_principal,0) <> 2
   AND NOT EXISTS (SELECT 1 FROM produccion.dim_tanque_producto tp WHERE tp.id_tanque = t.id_tanque AND tp.id_producto = 2)
   AND NOT EXISTS (SELECT 1 FROM produccion.dim_tanque_producto_permitido pp WHERE pp.id_tanque = t.id_tanque AND pp.id_producto = 2)
 ORDER BY t.nombre;

-- Pendiente estructural, para hacer con tiempo: retirar dim_tanque_producto_permitido y
-- dejar una sola habilitación. Dependen de ella 5 vistas y la función fn_tanque_sugerido;
-- hay que migrarlas antes de tocar la tabla. Mientras tanto las dos se leen juntas.
SELECT (SELECT count(*) FROM produccion.dim_tanque_producto_permitido pp
         WHERE NOT EXISTS (SELECT 1 FROM produccion.dim_tanque_producto tp
                            WHERE tp.id_tanque = pp.id_tanque AND tp.id_producto = pp.id_producto)) AS solo_en_permitido,
       (SELECT count(*) FROM produccion.dim_tanque_producto tp
         WHERE NOT EXISTS (SELECT 1 FROM produccion.dim_tanque_producto_permitido pp
                            WHERE pp.id_tanque = tp.id_tanque AND pp.id_producto = tp.id_producto)) AS solo_en_habilitado;
