# -*- coding: utf-8 -*-
"""La OP nace con fórmula.

De las 6 OP de la semana del 11/09/2026, 4 tenían id_formula NULL — no porque
nadie completara el campo, sino porque el formulario de alta NO TIENE el campo:
el INSERT de fact_batch_proceso nunca escribió id_formula. Sin fórmula no hay
instructivo, y sin instructivo no hay desvíos: el circuito que pidió dirección
se corta en el primer eslabón.

Se resuelve con un UPDATE inmediatamente después del INSERT (no se toca el INSERT,
que tiene ON CONFLICT DO UPDATE con lista explícita de columnas), aislado en un
savepoint como el bloque de MP de más abajo: si algo falla, el alta se guarda igual.

Criterio: se asigna sólo si el match es ÚNICO por (sector, tipo_proceso, MP,
producto buscado), donde la fórmula puede declarar '*' o NULL como comodín (la 13,
ARE-B, usa '*'). No se usa es_default porque en la base está en true para las 15
fórmulas activas, así que no discrimina. Si hay ambigüedad no se asigna nada y la
OP aparece en la bandeja HOY como "sin fórmula asignada" para que un humano elija.
"""
import io, sys

P = sys.argv[1] if len(sys.argv) > 1 else "app_carga/app.py"
s = io.open(P, encoding="utf-8", newline="").read()

ANCLA = """                            id_b = cur.fetchone()[0]
"""
NUEVO = """                            id_b = cur.fetchone()[0]
                            # --- Fórmula de la OP: sin esto no hay instructivo ni desvíos ---
                            # Sólo si el match es único; si hay ambigüedad queda NULL y la
                            # bandeja HOY la marca como "sin fórmula asignada".
                            try:
                                cur.execute("SAVEPOINT sp_formula")
                                cur.execute(
                                    "UPDATE fact_batch_proceso b SET id_formula = c.id_formula "
                                    "FROM (SELECT f.id_formula, count(*) OVER () AS n FROM dic_formula f "
                                    "      WHERE f.activo AND f.sector = %s AND f.tipo_proceso = %s "
                                    "        AND (%s::text IS NULL OR f.codigo_mp IS NULL OR f.codigo_mp IN ('*', %s)) "
                                    "        AND (%s::text IS NULL OR f.codigo_pf IS NULL OR f.codigo_pf IN ('*', %s))) c "
                                    "WHERE b.id_batch = %s AND b.id_formula IS NULL AND c.n = 1",
                                    (sector, tipo_proceso_sel, p_ini, p_ini, p_buscado, p_buscado, id_b))
                                cur.execute("RELEASE SAVEPOINT sp_formula")
                            except Exception:
                                cur.execute("ROLLBACK TO SAVEPOINT sp_formula")
"""
crlf = "\\r\\n" in s
A, N = (ANCLA.replace("\\n", "\\r\\n"), NUEVO.replace("\\n", "\\r\\n")) if crlf else (ANCLA, NUEVO)
assert s.count(A) == 1, "ancla no encontrada o ambigua (%d)" % s.count(A)
io.open(P, "w", encoding="utf-8", newline="").write(s.replace(A, N, 1))
print("OK crlf=%s" % crlf)
