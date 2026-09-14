-- ============================================================================
-- SOL-0036 · Secciones más usadas / últimas usadas arriba de la portada
--                                          · aplicada en worms-prod 2026-09-14
-- ----------------------------------------------------------------------------
-- Cada ENTRADA a una sección de app_carga deja una fila (id_usuario, seccion, ts).
-- La portada clásica lee v_uso_seccion_usuario y destaca hasta 3 accesos arriba
-- (más usados en 30 días o últimos usados, según prefs.orden_secciones). Los
-- ADMIN quedan afuera. Ver app_carga/uso_secciones.py.
-- De paso queda medido qué secciones usa cada uno (hasta hoy se infería a mano).
-- ============================================================================
CREATE TABLE IF NOT EXISTS produccion.fact_uso_seccion (
    id          bigserial PRIMARY KEY,
    id_usuario  bigint      NOT NULL,
    seccion     text        NOT NULL,
    ts          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_uso_seccion_usr_ts ON produccion.fact_uso_seccion (id_usuario, ts DESC);
COMMENT ON TABLE produccion.fact_uso_seccion IS 'SOL-0036: una fila por entrada a una sección de app_carga (no por rerun).';

CREATE OR REPLACE VIEW produccion.v_uso_seccion_usuario AS
SELECT id_usuario, seccion,
       count(*) FILTER (WHERE ts >= now() - interval '30 days') AS usos_30d,
       count(*)                                                 AS usos_total,
       max(ts)                                                  AS ultimo_uso
FROM produccion.fact_uso_seccion
GROUP BY id_usuario, seccion;
