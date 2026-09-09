# -*- coding: utf-8 -*-
"""Navegación v2 · área → sector → vista (Sistema WORMS.xlsx, dirección 28/08/2026).

Capa de navegación NUEVA que convive con la portada clásica sin tocarla:

    Raíz  →  ADMINISTRACIÓN | PRODUCCIÓN  →  sector (14)  →  vista

* Se activa POR USUARIO con la preferencia ``prefs.nav_v2`` (jsonb de dim_usuario).
  Con el flag apagado app.py se comporta byte a byte igual que antes.
* ``st.session_state.section`` sigue siendo el contrato de las 45 secciones:
  esta capa sólo decide A QUÉ sección ir y con qué contexto (área / sector).
* El lugar (área, sector, vista) vive en ``st.query_params`` — un F5, un link
  pegado en WhatsApp o una reconexión del websocket vuelven al mismo punto —
  y se copia a ``st.session_state["nav"]``.

Uso desde app.py (dos hooks de 6 líneas, ver docs/PLAN_NAVEGACION_V2.md):

    import nav
    if nav.activo(USR, _lab_conn):
        nav.render_landing(USR, ctx)   # reemplaza la portada clásica
        st.stop()

    nav.sidebar_toggle(USR, _lab_conn)  # botón Vista nueva / Vista clásica
"""

from .state import (  # noqa: F401
    AREAS, get_nav, set_nav, nav_activo_pref, set_nav_pref, activo,
)
from .portada import render_landing, sidebar_toggle, breadcrumb  # noqa: F401
from .sectores import sectores_nav  # noqa: F401
