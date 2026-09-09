# -*- coding: utf-8 -*-
"""Fase 0 · hooks de la navegación v2 en app_carga/app.py.

Tres inserciones y un traslado mecánico (los tiles de la portada pasan a una
lista módulo-nivel para que la portada nueva y la clásica usen LA MISMA lista).
Cada paso exige coincidencia exacta y única; si algo no coincide, no escribe nada.

Uso:  python patch_app_nav_v2.py app_carga/app.py
"""
import re
import shutil
import sys
from datetime import datetime

path = sys.argv[1]
raw = open(path, "rb").read()
CRLF = b"\r\n" in raw
src = raw.decode("utf-8").replace("\r\n", "\n")
orig = src


def once(s, needle):
    n = s.count(needle)
    assert n == 1, f"esperaba 1 coincidencia, hay {n}:\n{needle[:120]!r}"


# ------------------------------------------------------------------ 1) tiles → módulo-nivel
tiles_start = "    tiles = [\n        (\"👷\", \"Producción en planta\""
tiles_end = "    tiles = [t for t in tiles if puede_seccion(t[3])]\n"
once(src, tiles_start)
once(src, tiles_end)
i0 = src.index(tiles_start)
i1 = src.index(tiles_end) + len(tiles_end)
bloque = src[i0:i1]
# des-indentar 4 espacios y renombrar a _TILES_LANDING (sin el filtro, que queda en la portada clásica)
lineas = bloque.splitlines(keepends=True)
assert all(l.startswith("    ") or l.strip() == "" for l in lineas), "indentación inesperada en el bloque de tiles"
lineas = [l[4:] if l.startswith("    ") else l for l in lineas]
bloque_mod = "".join(lineas)
assert bloque_mod.endswith("tiles = [t for t in tiles if puede_seccion(t[3])]\n")
bloque_mod = bloque_mod[: -len("tiles = [t for t in tiles if puede_seccion(t[3])]\n")]
bloque_mod = bloque_mod.replace("tiles = [\n", "_TILES_LANDING = [\n", 1)
bloque_mod = bloque_mod.replace("tiles.append(", "_TILES_LANDING.append(")
assert "tiles" not in bloque_mod.replace("_TILES_LANDING", ""), "quedó una referencia suelta a `tiles`"
bloque_mod = ("# ---- Accesos de la portada (misma lista para la vista clásica y la navegación v2) ----\n"
              + bloque_mod + "\n")
src = src[:i0] + "    tiles = [t for t in _TILES_LANDING if puede_seccion(t[3])]\n" + src[i1:]

# insertar la lista antes del `if st.session_state.section is None:` de la portada
anchor_landing = "\n\nif st.session_state.section is None:\n    if st.session_state.get(\"_sec_cookie\"):\n"
once(src, anchor_landing)
src = src.replace(anchor_landing, "\n\n" + bloque_mod + anchor_landing.lstrip("\n"), 1)

# ------------------------------------------------------------------ 2) hook portada
anchor_hook = ("if st.session_state.section is None:\n"
               "    if st.session_state.get(\"_sec_cookie\"):\n"
               "        _auth.set_section_cookie(None)\n"
               "        st.session_state._sec_cookie = None\n")
once(src, anchor_hook)
hook = anchor_hook + '''    # ---- Navegación v2 (flag por usuario: dim_usuario.prefs.nav_v2) ----
    # Raíz Administración / Producción → sectores. Con el flag apagado, esta portada
    # es exactamente la de siempre. Ver docs/PLAN_NAVEGACION_V2.md.
    try:
        import nav as _nav
        _nav_on = _nav.activo(USR, _lab_conn, locked_one=_LOCKED_ONE)
    except Exception:
        _nav_on = False
    if _nav_on:
        try:
            _nav.render_landing({
                "USR": USR, "conn_factory": _lab_conn, "puede_seccion": puede_seccion,
                "secciones": [s for s, _ in SECCIONES_APP],
                "tiles": [{"icono": i, "titulo": t, "desc": d, "sec": s}
                          for (i, t, d, s, _k, _p) in _TILES_LANDING],
            })
            _nav_ok = True
        except Exception as _e:
            _nav_ok = False
            st.warning("La navegación nueva falló y se muestra la portada clásica: %s" % _e)
        if _nav_ok:
            st.stop()
'''
src = src.replace(anchor_hook, hook, 1)

# ------------------------------------------------------------------ 3) hook sidebar (toggle)
anchor_sb = ('        if st.button("← Cambiar de sección", use_container_width=True, key="sb_back"):\n'
             '            st.session_state.section = None\n'
             '            st.rerun()\n')
once(src, anchor_sb)
src = src.replace(anchor_sb, anchor_sb + '''        try:
            import nav as _nav
            _nav.sidebar_toggle(USR, _lab_conn)
        except Exception:
            pass
''', 1)

# ------------------------------------------------------------------ 4) migas al lado del botón Inicio
anchor_home = ('_hcol1, _hcol2 = st.columns([1, 4])\n'
               'with _hcol1:\n'
               '    if st.button("🏠 Inicio", key="btn_home_top", use_container_width=True,\n'
               '                 help="Volver a la pantalla principal"):\n'
               '        st.session_state.section = None\n'
               '        st.rerun()\n')
once(src, anchor_home)
src = src.replace(anchor_home, anchor_home + '''with _hcol2:
    # Migas de la navegación v2 (sólo si el usuario la tiene activa y entró por un área)
    try:
        import nav as _nav
        if _nav.activo(USR, _lab_conn, locked_one=_LOCKED_ONE) and _nav.get_nav()["area"]:
            _nav.breadcrumb({"conn_factory": _lab_conn}, mostrar_raiz=True, volver_portada=True)
    except Exception:
        pass
''', 1)

# ------------------------------------------------------------------ escribir
assert src != orig
bak = path + ".bak_nav_v2_" + datetime.now().strftime("%Y%m%d_%H%M")
shutil.copy2(path, bak)
out = src.replace("\n", "\r\n") if CRLF else src
open(path, "wb").write(out.encode("utf-8"))
print("OK · backup:", bak, "· bytes:", len(orig), "→", len(src))
