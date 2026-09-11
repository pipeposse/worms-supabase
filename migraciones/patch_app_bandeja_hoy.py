# -*- coding: utf-8 -*-
"""Bandeja HOY arriba de cualquier sección clásica.

Los 6 usuarios anclados a una sola sección (los que entran todos los días) nunca
ven la navegación v2: activo() devuelve False para ellos a propósito. El banner es
la forma de que el trabajo pendiente les llegue igual, sin cambiarles la pantalla.
Va debajo de las migas y arriba del contenido de la sección.

Sólo para ellos: para todos los demás la bandeja ya es la portada del área Producción,
y repetirla arriba de cada sección sería ruido.
"""
import io, sys

P = sys.argv[1] if len(sys.argv) > 1 else "app_carga/app.py"
s = io.open(P, encoding="utf-8", newline="").read()

ANCLA = """if st.session_state.get("show_chg_pin"):
"""
NUEVO = """# ---- Bandeja HOY para los usuarios anclados a UNA sección ----
# Son los que entran todos los días (Maximiliano, Leandro, Laboratorio) y los únicos que
# nunca ven la navegación v2: activo() devuelve False con locked_one. Para el resto la
# bandeja es la portada del área, así que acá sería ruido repetido.
if _LOCKED_ONE:
    try:
        import nav as _nav
        _nav.banner_hoy({"USR": USR, "conn_factory": _lab_conn, "conectar": conectar,
                         "puede_seccion": puede_seccion})
    except Exception:
        pass

if st.session_state.get("show_chg_pin"):
"""
crlf = "\\r\\n" in s
A, N = (ANCLA.replace("\\n", "\\r\\n"), NUEVO.replace("\\n", "\\r\\n")) if crlf else (ANCLA, NUEVO)
assert s.count(A) == 1, "ancla no encontrada o ambigua (%d)" % s.count(A)
io.open(P, "w", encoding="utf-8", newline="").write(s.replace(A, N, 1))
print("OK crlf=%s" % crlf)
