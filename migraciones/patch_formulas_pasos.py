# -*- coding: utf-8 -*-
"""Fase 3 · pestaña "📑 Pasos (instructivo)" en formulas_section.py.
Si se entra desde la tarjeta Formulación del sector (nav vista=FORMULACION) la pestaña va primera;
en la vista clásica el orden de siempre no cambia."""
import shutil, sys
from datetime import datetime
path = sys.argv[1]
raw = open(path, "rb").read(); crlf = b"\r\n" in raw
src = raw.decode("utf-8").replace("\r\n", "\n")
old = '''    t_list, t_edit, t_new, t_cond = st.tabs(["📋 Todas las fórmulas", "✏️ Editar / default", "➕ Nueva fórmula", "🧮 Condicionales"])
'''
new = '''    _tabs = ["📋 Todas las fórmulas", "✏️ Editar / default", "➕ Nueva fórmula", "🧮 Condicionales", "📑 Pasos (instructivo)"]
    if (st.session_state.get("nav") or {}).get("vista") == "FORMULACION":
        _tabs = [_tabs[-1]] + _tabs[:-1]        # desde la tarjeta Formulación del sector: el instructivo primero
    _tobj = dict(zip(_tabs, st.tabs(_tabs)))
    t_list, t_edit, t_new, t_cond, t_pasos = (_tobj[n] for n in
        ["📋 Todas las fórmulas", "✏️ Editar / default", "➕ Nueva fórmula", "🧮 Condicionales", "📑 Pasos (instructivo)"])
    with t_pasos:
        try:
            import formula_pasos as _fp
            _fp.render(USR, cat, conectar)
        except Exception as _e:
            st.error(f"No se pudo cargar el instructivo: {_e}")
'''
assert src.count(old) == 1, src.count(old)
src = src.replace(old, new, 1)
bak = path + ".bak_pasos_" + datetime.now().strftime("%Y%m%d_%H%M"); shutil.copy2(path, bak)
open(path, "wb").write((src.replace("\n", "\r\n") if crlf else src).encode("utf-8"))
print("OK", bak)
