# -*- coding: utf-8 -*-
"""SOL-0036 · podio de secciones más usadas / últimas usadas en la portada clásica.

Dos parches en app.py (idempotentes desde el original, count==1 cada ancla):
  1. Portada: el bloque "Accesos" pasa a pintar primero las destacadas (uso_secciones.destacadas)
     y abajo el resto en orden fijo; radio para elegir el criterio (no ADMIN).
  2. Registro: al entrar a una sección (después del guardia de permisos y la cookie de sección)
     se inserta una fila en produccion.fact_uso_seccion.
"""
import io, sys

P = sys.argv[1] if len(sys.argv) > 1 else "app_carga/app.py"
s = io.open(P, encoding="utf-8", newline="").read()

ANCLA1 = """    st.markdown('<div class="section-title">Accesos</div>', unsafe_allow_html=True)

    tiles = [t for t in _TILES_LANDING if puede_seccion(t[3])]

    for i in range(0, len(tiles), 3):
        cols = st.columns(3)
        for col, (icon, tit, desc, sec, key, prim) in zip(cols, tiles[i:i+3]):
            with col:
                with st.container(border=True):
                    st.markdown(f'<div class="tile-h">{icon} {tit}</div><div class="tile-d">{desc}</div>',
                                unsafe_allow_html=True)
                    if st.button("Entrar", type="primary", use_container_width=True, key=key):
                        go_to(sec)
    st.stop()
"""
NUEVO1 = """    def _render_tiles(_tiles):
        for i in range(0, len(_tiles), 3):
            cols = st.columns(3)
            for col, (icon, tit, desc, sec, key, prim) in zip(cols, _tiles[i:i+3]):
                with col:
                    with st.container(border=True):
                        st.markdown(f'<div class="tile-h">{icon} {tit}</div><div class="tile-d">{desc}</div>',
                                    unsafe_allow_html=True)
                        if st.button("Entrar", type="primary", use_container_width=True, key=key):
                            go_to(sec)

    # ---- SOL-0036: hasta 3 accesos destacados arriba (más usadas / últimas usadas).
    # El resto queda en el orden fijo de siempre (no se reordena toda la grilla a
    # propósito: una grilla que se mueve rompe la memoria muscular). ADMIN: sin podio.
    try:
        import uso_secciones as _uso
        _uso_modo, _uso_dest, tiles = _uso.destacadas(_lab_conn, USR, _TILES_LANDING, puede_seccion)
    except Exception:
        _uso, _uso_modo, _uso_dest = None, "FIJO", []
        tiles = [t for t in _TILES_LANDING if puede_seccion(t[3])]
    if _uso_dest:
        st.markdown('<div class="section-title">%s</div>' % _uso.TITULOS.get(_uso_modo, "Destacadas"),
                    unsafe_allow_html=True)
        _render_tiles(_uso_dest)

    st.markdown('<div class="section-title">Accesos</div>', unsafe_allow_html=True)
    _render_tiles(tiles)
    if _uso is not None:
        try:
            _uso.selector_modo(_lab_conn, USR)
        except Exception:
            pass
    st.stop()
"""

ANCLA2 = """# ---- Recordar la sección actual (cookie): si la página se recarga, vuelve acá ----
if st.session_state.get("_sec_cookie") != st.session_state.section:
    _auth.set_section_cookie(st.session_state.section)
    st.session_state._sec_cookie = st.session_state.section
"""
NUEVO2 = ANCLA2 + """
# ---- SOL-0036: registrar la ENTRADA a la sección (alimenta "más usadas" en la portada) ----
try:
    import uso_secciones as _uso
    _uso.registrar_uso(_lab_conn, USR, st.session_state.section)
except Exception:
    pass
"""

crlf = "\\r\\n" in s
for A, N in ((ANCLA1, NUEVO1), (ANCLA2, NUEVO2)):
    if crlf:
        A, N = A.replace("\\n", "\\r\\n"), N.replace("\\n", "\\r\\n")
    assert s.count(A) == 1, "ancla no encontrada o ambigua (%d)" % s.count(A)
    s = s.replace(A, N, 1)
io.open(P, "w", encoding="utf-8", newline="").write(s)
print("OK crlf=%s" % crlf)
