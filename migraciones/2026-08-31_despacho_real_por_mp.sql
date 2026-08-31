-- ============================================================================
-- KG REALES POR MATERIA PRIMA DE UN DESPACHO   ·  aplicada en worms-prod 2026-08-31
-- ----------------------------------------------------------------------------
-- fact_despacho_linea guarda lo FORMULADO: los litros que se planificó sacar de
-- cada tanque. fact_despacho_ticket guarda lo REAL PESADO en portería, pero por
-- CONTENEDOR: la balanza no informa de qué tanque cargó cada camión, así que no
-- se puede repartir sola por materia prima.
--
-- Falta el dato del medio: cuántos kg de cada materia prima entraron de verdad.
-- Eso lo sabe quien despachó y hasta ahora no tenía dónde anotarlo. Contra los
-- tickets, los despachos formulados dan 2.000 a 5.000 kg de diferencia.
--
-- Esta tabla NO pisa la formulación: convive con ella (misma lógica
-- PLANIFICADO -> EJECUTADO que ya usa el stock).
-- ============================================================================
CREATE TABLE IF NOT EXISTS produccion.fact_despacho_real (
    id_despacho      bigint      NOT NULL
                     REFERENCES produccion.fact_despacho(id_despacho) ON DELETE CASCADE,
    producto_codigo  text        NOT NULL,
    kg_real          numeric(14,2) NOT NULL CHECK (kg_real >= 0),
    nota             text,
    id_usuario       integer,
    creado_en        timestamptz NOT NULL DEFAULT now(),
    actualizado_en   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fact_despacho_real_pk PRIMARY KEY (id_despacho, producto_codigo)
);

COMMENT ON TABLE  produccion.fact_despacho_real IS
  'Kg REALES cargados de cada materia prima en un despacho. No reemplaza a '
  'fact_despacho_linea (lo formulado): convive con ella. Se carga a mano desde '
  'Despachos -> Semanal, porque los tickets de portería pesan por contenedor y '
  'no discriminan producto.';
COMMENT ON COLUMN produccion.fact_despacho_real.kg_real IS
  'Kg efectivamente cargados de ese producto. 0 = se cargó y dio cero (distinto '
  'de no tener fila, que significa "sin ajustar, vale lo formulado").';

CREATE INDEX IF NOT EXISTS ix_fact_despacho_real_desp
    ON produccion.fact_despacho_real (id_despacho);

-- ----------------------------------------------------------------------------
-- Por despacho x materia prima: formulado, real y EFECTIVO.
-- "Efectivo" es lo que hay que mostrar y sumar en todos lados: el real cuando
-- alguien lo ajustó, y si no, lo formulado.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW produccion.v_despacho_mp AS
WITH form AS (
    SELECT l.id_despacho,
           l.producto_codigo,
           SUM(l.litros)                                                    AS litros_form,
           SUM(l.litros * COALESCE(l.densidad, p.densidad_g_ml, 0.9))       AS kg_form
      FROM produccion.fact_despacho_linea l
      LEFT JOIN produccion.dim_producto p ON p.codigo_producto = l.producto_codigo
     GROUP BY l.id_despacho, l.producto_codigo
), llaves AS (
    SELECT id_despacho, producto_codigo FROM form
    UNION
    SELECT id_despacho, producto_codigo FROM produccion.fact_despacho_real
)
SELECT k.id_despacho,
       k.producto_codigo,
       COALESCE(f.kg_form, 0)::numeric(14,2)                 AS kg_formulado,
       COALESCE(f.litros_form, 0)::numeric(14,2)             AS litros_formulado,
       r.kg_real::numeric(14,2)                              AS kg_real,
       COALESCE(r.kg_real, f.kg_form, 0)::numeric(14,2)      AS kg_efectivo,
       (r.id_despacho IS NOT NULL)                           AS ajustado,
       (COALESCE(r.kg_real, f.kg_form, 0) - COALESCE(f.kg_form, 0))::numeric(14,2)
                                                             AS kg_dif,
       r.nota, r.id_usuario, r.actualizado_en
  FROM llaves k
  LEFT JOIN form f USING (id_despacho, producto_codigo)
  LEFT JOIN produccion.fact_despacho_real r USING (id_despacho, producto_codigo);

COMMENT ON VIEW produccion.v_despacho_mp IS
  'Por despacho y materia prima: kg formulados, kg reales cargados a mano (si '
  'los hay) y kg EFECTIVOS = real si fue ajustado, si no el formulado. Incluye '
  'materias primas que sólo existen en el ajuste (entró algo que no estaba '
  'formulado) y las que sólo existen en la formulación.';

-- ----------------------------------------------------------------------------
-- Control: el ajuste por materia prima contra lo que pesó la balanza.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW produccion.v_despacho_real_vs_ticket AS
SELECT d.id_despacho,
       d.titulo, d.fecha_despacho, d.estado, d.n_contenedores,
       COALESCE(m.kg_formulado, 0)::numeric(14,2)  AS kg_formulado,
       COALESCE(m.kg_efectivo, 0)::numeric(14,2)   AS kg_efectivo,
       COALESCE(m.ajustes, 0)                      AS mp_ajustadas,
       COALESCE(t.kg_tickets, 0)::numeric(14,2)    AS kg_tickets,
       COALESCE(t.n_tickets, 0)                    AS n_tickets,
       (COALESCE(m.kg_efectivo, 0) - COALESCE(t.kg_tickets, 0))::numeric(14,2)
                                                   AS kg_dif_vs_ticket
  FROM produccion.fact_despacho d
  LEFT JOIN (SELECT id_despacho,
                    SUM(kg_formulado) AS kg_formulado,
                    SUM(kg_efectivo)  AS kg_efectivo,
                    COUNT(*) FILTER (WHERE ajustado) AS ajustes
               FROM produccion.v_despacho_mp
              GROUP BY id_despacho) m ON m.id_despacho = d.id_despacho
  LEFT JOIN (SELECT id_despacho,
                    SUM(kg) AS kg_tickets,
                    COUNT(*) AS n_tickets
               FROM produccion.fact_despacho_ticket
              GROUP BY id_despacho) t ON t.id_despacho = d.id_despacho;

COMMENT ON VIEW produccion.v_despacho_real_vs_ticket IS
  'Control del ajuste por materia prima contra la balanza: kg efectivos de la '
  'mezcla vs kg pesados en portería. La diferencia grande significa que los kg '
  'por materia prima no cierran con lo que realmente salió.';
