# -*- coding: utf-8 -*-
"""Fase 4b · carga_por_id.py: despliega el instructivo de la OP (op_instructivo.py) debajo del
encabezado de la producción. Si la fórmula no tiene pasos, sólo muestra un aviso."""
import shutil, sys
from datetime import datetime
path = sys.argv[1]
raw = open(path, "rb").read(); crlf = b"\r\n" in raw
src = raw.decode("utf-8").replace("\r\n", "\n")
old = '''    st.markdown(_stepper(estado), unsafe_allow_html=True)
    _banner_corriente(b["corriente"])
'''
new = '''    st.markdown(_stepper(estado), unsafe_allow_html=True)
    _banner_corriente(b["corriente"])
    # ---- Instructivo paso a paso de la fórmula (Fase 4b): corre en su propio fragment ----
    try:
        import op_instructivo as _opi
        _opi.render(USR, cat, conectar, id_batch)
    except Exception as _e:
        st.caption(f"Instructivo no disponible: {_e}")
'''
assert src.count(old) == 1, src.count(old)
src = src.replace(old, new, 1)
bak = path + ".bak_instructivo_" + datetime.now().strftime("%Y%m%d_%H%M"); shutil.copy2(path, bak)
open(path, "wb").write((src.replace("\n", "\r\n") if crlf else src).encode("utf-8"))
print("OK", bak)
