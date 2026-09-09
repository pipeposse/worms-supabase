-- ============================================================================
-- NAVEGACIÓN V2 · FASE 3 · FORMULACIÓN POR PASOS   · aplicada en worms-prod 2026-09-09
-- ----------------------------------------------------------------------------
-- Dirección (Sistema WORMS.xlsx, tabla FORMULACIÓN): cada fórmula tiene un
-- instructivo paso a paso — caldera, carga de MP, carga de cada insumo, validar
-- temperatura, inicio de reacción, revisiones de acidez/temperatura hora a hora
-- (50→40→35→25→15→13 % a 80 °C), decantación — con el valor esperado de cada paso.
-- Es lo que el operario va a ver al apretar "Orden Producción" (Fase 4) y contra
-- lo que se calculan los desvíos.
--
-- dic_formula sigue siendo la fórmula (insumos por TN, rendimiento, tiempos).
-- dic_formula_paso es su instructivo. Las cantidades van POR TN DE MP CARGADA,
-- igual que dic_formula.insumos, así el instructivo escala con cada OP.
-- Cada publicación guarda un snapshot (dic_formula_paso_version): una OP en
-- curso puede seguir con la versión con la que arrancó.
-- ============================================================================
CREATE TABLE IF NOT EXISTS produccion.dic_formula_paso (
    id_paso        bigserial PRIMARY KEY,
    id_formula     integer      NOT NULL REFERENCES produccion.dic_formula(id_formula) ON DELETE CASCADE,
    orden          smallint     NOT NULL,
    etapa          text         NOT NULL,   -- CALDERA · CARGA_MP · CARGA_INSUMO · VALIDAR_TEMP · INICIO_RX · REVISION · REPOSO · DECANTACION · EN_TANQUE · OTRO
    descripcion    text,
    codigo_insumo  text,                    -- código de dic_insumo (CARGA_INSUMO) o de la MP (CARGA_MP)
    cant_por_tn    numeric(12,4),           -- cantidad por TN de MP cargada
    unidad         text,                    -- KG | L
    acidez_esp     numeric(6,2),            -- % esperado (REVISION)
    temp_esp       numeric(6,1),            -- °C esperado (VALIDAR_TEMP / REVISION)
    tol_acidez     numeric(6,2)  NOT NULL DEFAULT 3,
    tol_temp       numeric(6,1)  NOT NULL DEFAULT 4,
    tol_cant_pct   numeric(5,2)  NOT NULL DEFAULT 3,
    offset_min     integer,                 -- minutos desde el inicio de la producción
    duracion_min   integer,
    captura        text         NOT NULL DEFAULT 'HORAS'
                   CHECK (captura IN ('HORAS','MEDICION','CANTIDAD','NINGUNA')),
    activo         boolean      NOT NULL DEFAULT true,
    creado_en      timestamptz  NOT NULL DEFAULT now(),
    actualizado_en timestamptz  NOT NULL DEFAULT now(),
    id_usuario     integer,
    CONSTRAINT dic_formula_paso_orden_uk UNIQUE (id_formula, orden)
);
COMMENT ON TABLE produccion.dic_formula_paso IS
  'Instructivo paso a paso de una fórmula (valor esperado por paso; cantidades por TN de MP cargada). '
  'captura = qué carga el operario en ese paso: HORAS (inicio/fin), MEDICION (temp y acidez), CANTIDAD (kg/L), NINGUNA.';

ALTER TABLE produccion.dic_formula
    ADD COLUMN IF NOT EXISTS version_pasos        integer     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pasos_actualizado_en timestamptz;

CREATE TABLE IF NOT EXISTS produccion.dic_formula_paso_version (
    id_version  bigserial PRIMARY KEY,
    id_formula  integer     NOT NULL REFERENCES produccion.dic_formula(id_formula) ON DELETE CASCADE,
    version     integer     NOT NULL,
    pasos       jsonb       NOT NULL,        -- snapshot de los pasos publicados
    nota        text,
    id_usuario  integer,
    creado_en   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT dic_formula_paso_version_uk UNIQUE (id_formula, version)
);

-- ---------------------------------------------------------------- vista para UI / instructivo
CREATE OR REPLACE VIEW produccion.v_formula_instructivo AS
SELECT f.id_formula, f.nombre AS formula, f.sector, f.tipo_proceso, f.codigo_mp, f.codigo_pf,
       f.es_default, f.version_pasos, f.pasos_actualizado_en,
       p.id_paso, p.orden, p.etapa, p.descripcion, p.codigo_insumo, p.cant_por_tn, p.unidad,
       p.acidez_esp, p.temp_esp, p.tol_acidez, p.tol_temp, p.tol_cant_pct,
       p.offset_min, p.duracion_min, p.captura
FROM produccion.dic_formula f
JOIN produccion.dic_formula_paso p ON p.id_formula = f.id_formula AND p.activo
WHERE f.activo
ORDER BY f.sector, f.tipo_proceso, f.id_formula, p.orden;

-- ---------------------------------------------------------------- publicar una versión (atómico)
CREATE OR REPLACE FUNCTION produccion.fn_formula_pasos_publicar(
    p_id_formula integer, p_pasos jsonb, p_usuario integer, p_nota text DEFAULT NULL)
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE v_version integer;
BEGIN
    -- p_pasos: [{orden, etapa, descripcion, codigo_insumo, cant_por_tn, unidad, acidez_esp, temp_esp,
    --           tol_acidez, tol_temp, tol_cant_pct, offset_min, duracion_min, captura}, ...]
    DELETE FROM produccion.dic_formula_paso WHERE id_formula = p_id_formula;
    INSERT INTO produccion.dic_formula_paso
        (id_formula, orden, etapa, descripcion, codigo_insumo, cant_por_tn, unidad, acidez_esp, temp_esp,
         tol_acidez, tol_temp, tol_cant_pct, offset_min, duracion_min, captura, id_usuario)
    SELECT p_id_formula,
           COALESCE((x->>'orden')::smallint, (row_number() OVER ())::smallint),
           COALESCE(NULLIF(btrim(x->>'etapa'), ''), 'OTRO'),
           NULLIF(btrim(x->>'descripcion'), ''),
           NULLIF(btrim(x->>'codigo_insumo'), ''),
           NULLIF(x->>'cant_por_tn', '')::numeric,
           NULLIF(btrim(x->>'unidad'), ''),
           NULLIF(x->>'acidez_esp', '')::numeric,
           NULLIF(x->>'temp_esp', '')::numeric,
           COALESCE(NULLIF(x->>'tol_acidez', '')::numeric, 3),
           COALESCE(NULLIF(x->>'tol_temp', '')::numeric, 4),
           COALESCE(NULLIF(x->>'tol_cant_pct', '')::numeric, 3),
           NULLIF(x->>'offset_min', '')::integer,
           NULLIF(x->>'duracion_min', '')::integer,
           COALESCE(NULLIF(upper(btrim(x->>'captura')), ''), 'HORAS'),
           p_usuario
    FROM jsonb_array_elements(p_pasos) AS x;

    UPDATE produccion.dic_formula
       SET version_pasos = version_pasos + 1, pasos_actualizado_en = now(), actualizado_en = now()
     WHERE id_formula = p_id_formula
    RETURNING version_pasos INTO v_version;

    INSERT INTO produccion.dic_formula_paso_version (id_formula, version, pasos, nota, id_usuario)
    SELECT p_id_formula, v_version,
           COALESCE(jsonb_agg(to_jsonb(p) - 'id_paso' - 'id_formula' - 'creado_en' - 'actualizado_en' - 'id_usuario'
                              ORDER BY p.orden), '[]'::jsonb),
           p_nota, p_usuario
    FROM produccion.dic_formula_paso p WHERE p.id_formula = p_id_formula;
    RETURN v_version;
END $$;

-- ---------------------------------------------------------------- semilla: pasos iniciales de una fórmula
-- PRODUCCION_ARE → la plantilla de dirección (caldera, MP, insumos, validar 80 °C, inicio RX,
-- 6 revisiones 50/40/35/25/15/13 % a 80 °C, decantación). Otros procesos → una fila por etapa
-- de dic_proceso_etapa más la carga de cada insumo. Devuelve el jsonb (NO publica).
CREATE OR REPLACE FUNCTION produccion.fn_formula_pasos_semilla(p_id_formula integer)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE f record; pasos jsonb := '[]'::jsonb; n int := 0; k text; v jsonb; e record; t int := 0; i int;
        acid numeric[] := ARRAY[50,40,35,25,15,13];
BEGIN
    SELECT * INTO f FROM produccion.dic_formula WHERE id_formula = p_id_formula;
    IF NOT FOUND THEN RETURN pasos; END IF;

    IF f.tipo_proceso = 'PRODUCCION_ARE' THEN
        n := n + 1; pasos := pasos || jsonb_build_object('orden', n, 'etapa', 'CALDERA', 'descripcion', 'Encendido de caldera', 'captura', 'HORAS', 'offset_min', 0, 'duracion_min', 20);
        n := n + 1; pasos := pasos || jsonb_build_object('orden', n, 'etapa', 'CARGA_MP', 'descripcion', 'Carga de materia prima', 'codigo_insumo', NULLIF(f.codigo_mp, '*'), 'cant_por_tn', 1000, 'unidad', 'KG', 'captura', 'CANTIDAD', 'offset_min', 20, 'duracion_min', 45);
        FOR k, v IN SELECT * FROM jsonb_each(COALESCE(f.insumos, '{}'::jsonb)) LOOP
            n := n + 1;
            pasos := pasos || jsonb_build_object('orden', n, 'etapa', 'CARGA_INSUMO', 'descripcion', 'Carga de ' || k,
                                                 'codigo_insumo', k, 'cant_por_tn', (v->>'cant')::numeric,
                                                 'unidad', COALESCE(v->>'un', 'KG'), 'captura', 'CANTIDAD', 'offset_min', 20, 'duracion_min', 45);
        END LOOP;
        n := n + 1; pasos := pasos || jsonb_build_object('orden', n, 'etapa', 'VALIDAR_TEMP', 'descripcion', 'Validar temperatura antes de arrancar', 'temp_esp', 80, 'captura', 'MEDICION', 'offset_min', 50);
        n := n + 1; pasos := pasos || jsonb_build_object('orden', n, 'etapa', 'INICIO_RX', 'descripcion', 'Inicio de reacción', 'codigo_insumo', NULLIF(f.codigo_pf, '*'), 'captura', 'HORAS', 'offset_min', 80, 'duracion_min', 360);
        FOR i IN 1..6 LOOP
            n := n + 1;
            pasos := pasos || jsonb_build_object('orden', n, 'etapa', 'REVISION', 'descripcion', 'Revisión de temperatura y acidez · hora ' || i,
                                                 'acidez_esp', acid[i], 'temp_esp', 80, 'captura', 'MEDICION', 'offset_min', 80 + 60 * i);
        END LOOP;
        n := n + 1; pasos := pasos || jsonb_build_object('orden', n, 'etapa', 'DECANTACION', 'descripcion', 'Decantación', 'captura', 'HORAS', 'offset_min', 440, 'duracion_min', 180);
        RETURN pasos;
    END IF;

    -- otros procesos: etapas del proceso + carga de insumos después de la primera etapa
    FOR e IN SELECT * FROM produccion.dic_proceso_etapa WHERE proceso_key = f.tipo_proceso ORDER BY orden LOOP
        n := n + 1;
        pasos := pasos || jsonb_build_object('orden', n, 'etapa', e.etapa, 'descripcion', initcap(replace(e.etapa, '_', ' ')),
                                             'captura', 'HORAS', 'offset_min', t, 'duracion_min', e.duracion_target_min);
        t := t + COALESCE(e.duracion_target_min, 0);
        IF e.orden = 1 THEN
            n := n + 1;
            pasos := pasos || jsonb_build_object('orden', n, 'etapa', 'CARGA_MP', 'descripcion', 'Carga de materia prima', 'codigo_insumo', NULLIF(f.codigo_mp, '*'), 'cant_por_tn', 1000, 'unidad', 'KG', 'captura', 'CANTIDAD', 'offset_min', t);
            FOR k, v IN SELECT * FROM jsonb_each(COALESCE(f.insumos, '{}'::jsonb)) LOOP
                n := n + 1;
                pasos := pasos || jsonb_build_object('orden', n, 'etapa', 'CARGA_INSUMO', 'descripcion', 'Carga de ' || k,
                                                     'codigo_insumo', k, 'cant_por_tn', (v->>'cant')::numeric,
                                                     'unidad', COALESCE(v->>'un', 'KG'), 'captura', 'CANTIDAD', 'offset_min', t);
            END LOOP;
        END IF;
    END LOOP;
    RETURN pasos;
END $$;
