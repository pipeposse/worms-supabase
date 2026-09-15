-- =====================================================================================
-- La palabra "despacho" no se muestra en ningún lado: ODV
-- 16/09/2026
--
-- Quedaba escrita en DATOS, no en el código: las observaciones de cada movimiento de
-- stock las escriben dos funciones de la base. Se corrigen las funciones y las 368 filas
-- que ya estaban cargadas. El código interno origen='despacho' NO se toca: nunca se
-- muestra y la sincronización de las órdenes depende de él.
-- =====================================================================================

-- 1 · las funciones que escriben la observación de cada movimiento
DO $do$
DECLARE r record; src text; nuevo text;
BEGIN
  FOR r IN SELECT p.oid, p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'produccion'
              AND p.proname IN ('fn_despacho_sync_stock','fn_mov_stock_espejo_tanque')
  LOOP
    src   := pg_get_functiondef(r.oid);
    nuevo := replace(replace(replace(src, '''Despacho ''', '''ODV '''),
                             '''Despacho''', '''ODV'''),
                     ''' linea ''', ''' línea ''');
    IF nuevo <> src THEN
      EXECUTE nuevo;
      RAISE NOTICE 'corregida %', r.proname;
    END IF;
  END LOOP;
END
$do$;

-- 2 · lo ya cargado
UPDATE produccion.fact_movimiento_stock
   SET observaciones = replace(observaciones, 'Despacho ', 'ODV ')
 WHERE observaciones ILIKE '%despacho %';
UPDATE produccion.fact_movimiento_stock
   SET observaciones = replace(observaciones, ' linea ', ' línea ')
 WHERE observaciones LIKE 'ODV % linea %';
UPDATE produccion.fact_despacho
   SET observaciones = replace(replace(observaciones, 'Despacho ', 'ODV '), 'despacho ', 'ODV ')
 WHERE observaciones ILIKE '%despacho%';

-- 3 · el destino de cada salida en el libro de movimientos
DO $do$
DECLARE src text; nuevo text;
BEGIN
  src   := pg_get_viewdef('produccion.v_movimiento_sector'::regclass, true);
  nuevo := replace(src, '''Orden de venta ''', '''ODV ''');
  IF nuevo <> src THEN
    EXECUTE 'CREATE OR REPLACE VIEW produccion.v_movimiento_sector AS ' || nuevo;
  END IF;
END
$do$;

-- control: tiene que dar 0
-- SELECT count(*) FROM produccion.fact_movimiento_stock WHERE observaciones ILIKE '%despacho%';
