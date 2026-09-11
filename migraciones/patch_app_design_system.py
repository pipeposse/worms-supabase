# -*- coding: utf-8 -*-
"""Reemplaza inject_global_css() por el sistema de diseño "panel de instrumentos".

Idempotente: si ya está aplicado, no hace nada. Corta entre el comentario de
cabecera del bloque de diseño y el comentario del vigía de recarga, así que no
depende del contenido del CSS viejo.

    python migraciones/patch_app_design_system.py app_carga/app.py
"""
import io
import sys

INICIO_VIEJO = "# ===== Design system global (look premium)"
INICIO_NUEVO = "# ===== Sistema de diseño — panel de instrumentos"
FIN = "# Vigía de recarga:"


def main(destino, fuente_css):
    src = io.open(destino, encoding="utf-8").read()
    nuevo = io.open(fuente_css, encoding="utf-8").read().rstrip() + "\n\n\n"

    # Re-aplicable: si ya está el bloque nuevo, se reemplaza por la versión actual
    # del CSS (fuente única en _css_panel_instrumentos.py) en vez de no hacer nada.
    i = src.find(INICIO_NUEVO)
    if i < 0:
        i = src.find(INICIO_VIEJO)
    j = src.find(FIN)
    if i < 0 or j < 0 or j <= i:
        print("ERROR: no encontré los anclajes (%s / %s)" % (i, j))
        return 1

    out = src[:i] + nuevo + src[j:]
    io.open(destino, "w", encoding="utf-8").write(out)
    print("ok: %d bytes -> %d bytes" % (len(src), len(out)))
    return 0


if __name__ == "__main__":
    destino = sys.argv[1] if len(sys.argv) > 1 else "app_carga/app.py"
    fuente = sys.argv[2] if len(sys.argv) > 2 else "migraciones/_css_panel_instrumentos.py"
    sys.exit(main(destino, fuente))
