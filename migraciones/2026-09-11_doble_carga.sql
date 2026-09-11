-- ============================================================================
-- Doble carga: "hay que confirmar muchas veces cada operación y después
-- aparecen cargadas varias veces"  (dirección, 11/09/2026)
-- worms-prod · aplicada
--
-- CAUSA (medida, no supuesta)
-- Un click en Guardar dispara un rerun de TODA la app: cada pantalla hace
-- cat.clear() —que vacía la caché del proceso entero, para todos los usuarios—
-- y después st.rerun(), así que se vuelven a pedir todas las queries de la
-- sección. Entre el click y el redibujo pasan entre 7 y 10 segundos. En ese
-- tiempo el botón no cambia de aspecto y el indicador de "corriendo" de
-- Streamlit estaba OCULTO por CSS: la persona no tiene ninguna señal de que
-- algo pasó, y vuelve a apretar. Cada apretada entra como una carga.
--
-- Además, en varias pantallas los campos NO se vacían al guardar, así que el
-- segundo click manda exactamente el mismo dato.
--
-- ALCANCE (produccion.fn_duplicados_carga(60, 180)):
--   129 filas de más en 8 tablas en 60 días. Lo peor:
--   · fact_evaluacion_interna  36 de más, con un grupo de 23 idénticas en 10 s
--   · fact_desg_envio          18 de más (una carga entró 19 veces)
--   · fact_desg_decant         16 de más
--   · fact_stock_tanque        47 de más en 45 grupos (mediciones repetidas)
--   En fact_evaluacion_interna eso es 36 de 141: UNA DE CADA CUATRO mediciones
--   de reacción de los últimos 4 meses era una repetición.
--
-- QUÉ SE HIZO
--   1. Interfaz (inject_global_css): mientras la app trabaja, los botones no
--      aceptan clicks y se ve que está trabajando. Es el arreglo de fondo.
--   2. eval_interna.py: los campos se vacían al guardar y hay un seguro por
--      contenido (si es idéntico a lo último guardado, avisa en vez de repetir).
--   3. Esto: el candado en la base, por si algo se escapa igual.
--   4. Limpieza de las 36 evaluaciones repetidas (anuladas, no borradas).
--
-- LO QUE NO SE TOCÓ
-- Las repeticiones históricas de fact_stock_tanque, fact_desg_*, fact_despacho
-- y fact_param_tanque_hist siguen ahí: esas tablas no tienen columna anulado y
-- borrar filas de producción sin que lo pida alguien no corresponde. En
-- fact_stock_tanque no distorsionan el stock (el panel toma la última medición
-- física, y la repetida tiene el mismo valor): son ruido en el historial. Los
-- dos despachos duplicados ya estaban ANULADOS por la gente.
-- ============================================================================

-- ---------------------------------------------------------- 1. diagnóstico
-- Detector genérico, para volver a medir cuando haga falta:
--   SELECT * FROM produccion.fn_duplicados_carga(60, 180) WHERE filas_de_mas > 0;
-- (definición completa aplicada en la migración fn_duplicados_carga)

-- ---------------------------------------------------------- 2. dónde anotar
CREATE TABLE IF NOT EXISTS produccion.log_doble_carga (
    id_log      bigserial PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    tabla       text        NOT NULL,
    id_usuario  bigint,
    segundos    numeric,
    huella      jsonb
);
COMMENT ON TABLE produccion.log_doble_carga IS
    'Cada vez que el candado descarta un insert repetido. Sirve para medir si la corrección '
    'de la interfaz alcanzó: si esto deja de crecer, el problema se resolvió arriba.';

-- ---------------------------------------------------------- 3. el candado
CREATE OR REPLACE FUNCTION produccion.fn_evitar_doble_carga()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_ts_col  text := TG_ARGV[0];
    v_pk_col  text := TG_ARGV[1];
    v_seg     int  := coalesce(TG_ARGV[2]::int, 90);
    v_huella  jsonb;
    v_prev    timestamptz;
    v_sql     text;
BEGIN
    -- La huella es la fila entera salvo su identidad y sus marcas de tiempo:
    -- dos filas con la misma huella son literalmente la misma carga.
    v_huella := to_jsonb(NEW) - v_pk_col - v_ts_col - 'actualizado_en' - 'creado_en';

    v_sql := format(
        'SELECT max(%1$I) FROM produccion.%2$I t '
        'WHERE %1$I >= now() - ($1 || '' seconds'')::interval '
        '  AND (to_jsonb(t) - %3$L - %4$L - ''actualizado_en'' - ''creado_en'') = $2',
        v_ts_col, TG_TABLE_NAME, v_pk_col, v_ts_col);
    EXECUTE v_sql INTO v_prev USING v_seg, v_huella;

    IF v_prev IS NULL THEN
        RETURN NEW;
    END IF;

    INSERT INTO produccion.log_doble_carga (tabla, id_usuario, segundos, huella)
    VALUES (TG_TABLE_NAME,
            nullif(v_huella->>'id_usuario', '')::bigint,
            round(extract(epoch FROM (now() - v_prev))::numeric, 1),
            v_huella);
    RETURN NULL;     -- se descarta en silencio: para quien carga, ya estaba guardado
END;
$$;

-- Los nombres de PK están verificados uno por uno: fact_desg_envio y
-- fact_desg_decant usan "id", no id_envio/id_decant. Con el nombre equivocado el
-- id queda dentro de la huella, toda fila es única y el candado no dispara nunca.
DROP TRIGGER IF EXISTS tg_doble_carga ON produccion.fact_evaluacion_interna;
CREATE TRIGGER tg_doble_carga BEFORE INSERT ON produccion.fact_evaluacion_interna
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_evitar_doble_carga('ts', 'id_eval', '90');

DROP TRIGGER IF EXISTS tg_doble_carga ON produccion.fact_desg_envio;
CREATE TRIGGER tg_doble_carga BEFORE INSERT ON produccion.fact_desg_envio
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_evitar_doble_carga('ts', 'id', '90');

DROP TRIGGER IF EXISTS tg_doble_carga ON produccion.fact_desg_decant;
CREATE TRIGGER tg_doble_carga BEFORE INSERT ON produccion.fact_desg_decant
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_evitar_doble_carga('ts', 'id', '90');

DROP TRIGGER IF EXISTS tg_doble_carga ON produccion.fact_decant_purga;
CREATE TRIGGER tg_doble_carga BEFORE INSERT ON produccion.fact_decant_purga
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_evitar_doble_carga('ts', 'id_purga', '90');

DROP TRIGGER IF EXISTS tg_doble_carga ON produccion.fact_stock_tanque;
CREATE TRIGGER tg_doble_carga BEFORE INSERT ON produccion.fact_stock_tanque
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_evitar_doble_carga('creado_en', 'id_stock', '60');

-- Probado con rollback en las cinco tablas: la primera fila entra, la idéntica
-- se descarta y queda anotada, y una con un valor distinto pasa normalmente.

-- ---------------------------------------------------------- 4. limpieza
-- (ejecutada una sola vez; queda como registro de qué se corrigió)
-- Se anularon 36 evaluaciones internas repetidas conservando la primera de cada
-- grupo, con el motivo en observaciones y un evento por fila en aud_eventos.
