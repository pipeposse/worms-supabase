# -*- coding: utf-8 -*-
"""El botón para probar la navegación nueva vivía sólo en la barra lateral, que no se
dibuja en la portada clásica (corta con st.stop() antes). Se agrega a la portada."""
import io, sys
P = "app_carga/app.py"
s = io.open(P, encoding="utf-8", newline="").read()

ANCLA = """        if _nav_ok:
            st.stop()
    _hoy_txt = date.today().strftime("%d/%m/%Y")
"""
NUEVO = """        if _nav_ok:
            st.stop()
    # El toggle de la barra lateral no se ve acá (la portada corta antes): botón propio.
    try:
        import nav as _nav
        _c_nav_1, _c_nav_2 = st.columns([3, 1.4])
        with _c_nav_2:
            _nav.sidebar_toggle(USR, _lab_conn)
    except Exception:
        pass
    _hoy_txt = date.today().strftime("%d/%m/%Y")
"""
crlf = "\r\n" in s
if crlf:
    ANCLA, NUEVO = ANCLA.replace("\n", "\r\n"), NUEVO.replace("\n", "\r\n")
assert s.count(ANCLA) == 1, "ancla no encontrada (%d)" % s.count(ANCLA)
io.open(P, "w", encoding="utf-8", newline="").write(s.replace(ANCLA, NUEVO))
print("OK crlf=%s" % crlf)
