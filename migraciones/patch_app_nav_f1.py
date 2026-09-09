# -*- coding: utf-8 -*-
"""Fase 1 · el hook de la portada pasa `conectar` (escrituras con auditoría) al ctx de nav."""
import os, shutil, sys
from datetime import datetime
path = sys.argv[1]
raw = open(path, "rb").read(); crlf = b"\r\n" in raw
src = raw.decode("utf-8").replace("\r\n", "\n")
old = '''                "USR": USR, "conn_factory": _lab_conn, "puede_seccion": puede_seccion,
                "secciones": [s for s, _ in SECCIONES_APP],'''
new = '''                "USR": USR, "conn_factory": _lab_conn, "conectar": conectar,
                "puede_seccion": puede_seccion,
                "secciones": [s for s, _ in SECCIONES_APP],'''
assert src.count(old) == 1, src.count(old)
src = src.replace(old, new, 1)
bak = path + ".bak_nav_f1_" + datetime.now().strftime("%Y%m%d_%H%M"); shutil.copy2(path, bak)
open(path, "wb").write((src.replace("\n", "\r\n") if crlf else src).encode("utf-8"))
print("OK", bak)
