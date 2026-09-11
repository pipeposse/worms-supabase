# -*- coding: utf-8 -*-
"""La OP hereda el ticket de balanza de su materia prima.

Las 20 OP del último mes tenían `ticket_porteria` NULL, pero NO porque nadie
completara el campo: `ticket_porteria_v` sólo se asigna dentro de la rama
DESGOMADO_ACUOSO (línea ~5765). Para PRODUCCION_ARE y el resto quedaba None
siempre, aunque el operario hubiera elegido tickets de portería como fuente.

El dato ya existe: `fuente_mp_combinada()` devuelve las fuentes elegidas y se
guardan en `mp_fuentes` para TODAS las ramas. Sólo hay que copiarlo a la OP
antes del INSERT. Cero UI nueva, cero fricción.

Alcance real: cubre las OP cuya MP viene de portería (~15 %). Las que toman de
tanque no tienen ticket propio a propósito — ese material entró días antes y
suele venir de varios camiones; para ésas la trazabilidad es la cadena
OP → tanque → tickets del tanque, que resuelve produccion.v_op_origen_mp.
"""
import io, sys

P = sys.argv[1] if len(sys.argv) > 1 else "app_carga/app.py"
s = io.open(P, encoding="utf-8", newline="").read()

ANCLA = """            if errs:
                for e in errs: st.error(e)
"""
NUEVO = """            # La OP hereda el ticket de balanza de su MP (lo eligió el operario en la
            # fuente; hasta ahora sólo se guardaba en la rama de desgomado).
            if not ticket_porteria_v:
                _tks = []
                for _f in mp_fuentes.values():
                    for _p in (_f if isinstance(_f, list) else [_f]):
                        if isinstance(_p, dict) and _p.get("ticket"):
                            _tks.append(str(_p["ticket"]))
                ticket_porteria_v = "; ".join(dict.fromkeys(_tks)) or None

            if errs:
                for e in errs: st.error(e)
"""
crlf = "\\r\\n" in s
A, N = (ANCLA.replace("\\n", "\\r\\n"), NUEVO.replace("\\n", "\\r\\n")) if crlf else (ANCLA, NUEVO)
assert s.count(A) == 1, "ancla no encontrada o ambigua (%d)" % s.count(A)
io.open(P, "w", encoding="utf-8", newline="").write(s.replace(A, N, 1))
print("OK crlf=%s" % crlf)
