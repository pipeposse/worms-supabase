# -*- coding: utf-8 -*-
"""Fase 4a · carga_por_id.py: si la planificación semanal dejó `pp_sel_id_batch` en session_state,
el selector "¿En qué producción vas a trabajar?" arranca parado en esa OP."""
import shutil, sys
from datetime import datetime
path = sys.argv[1]
raw = open(path, "rb").read(); crlf = b"\r\n" in raw
src = raw.decode("utf-8").replace("\r\n", "\n")
old = '''    sel = st.selectbox("¿En qué producción vas a trabajar?", opts, key="pp_sel")
'''
new = '''    # Llegada desde la planificación semanal (botón Cargar): preseleccionar esa OP
    _pre = st.session_state.pop("pp_sel_id_batch", None)
    if _pre is not None:
        _ids = act["id_batch"].astype(int).tolist()
        if int(_pre) in _ids:
            st.session_state["pp_sel"] = opts[_ids.index(int(_pre))]
    sel = st.selectbox("¿En qué producción vas a trabajar?", opts, key="pp_sel")
'''
assert src.count(old) == 1, src.count(old)
src = src.replace(old, new, 1)
bak = path + ".bak_presel_" + datetime.now().strftime("%Y%m%d_%H%M"); shutil.copy2(path, bak)
open(path, "wb").write((src.replace("\n", "\r\n") if crlf else src).encode("utf-8"))
print("OK", bak)
