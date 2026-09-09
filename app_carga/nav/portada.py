# -*- coding: utf-8 -*-
"""Portada v2: raíz (Administración / Producción), área Producción con la grilla de
sectores, área Administración con sus accesos. Fase 0: estructura + redirección a
las secciones clásicas. Los indicadores del área (Fase 1) y el home de cada sector
(Fase 2) se enchufan acá sin tocar app.py.

Todo lo que se muestra pasa por ``puede_seccion`` de app.py: la navegación nueva
no abre ninguna puerta que la clásica tuviera cerrada.
"""

from datetime import date

import streamlit as st

from . import state as _st
from .sectores import sectores_nav, sector_por_codigo

# Secciones clásicas que viven en ADMINISTRACIÓN (Fernando: "se incluyeron las
# secciones adm y cierres mensuales"). Todo lo demás es PRODUCCIÓN.
ADMIN_SECS = ("CIERRES", "DIRECCION", "ISCC", "CHAT", "ADMIN")
# Soporte es para todos: se muestra al pie de cualquier área.
SOPORTE_SEC = "MEJORAS"

# Tarjetas fijas del área Producción (además de la grilla de sectores).
_PROD_FIJAS = [
    ("🗓️", "Centro de Planificación", "Planificá la producción de la semana y generá las órdenes que ejecuta cada sector.", "PLANIFICACION"),
    ("📊", "Reportes", "Análisis de reacciones, brief semanal y desvíos.", "ANALISIS"),
]
_PANEL_CONTROL = ("🎛️", "Panel de Control", "Capacidad total ocupada de la planta, reacciones en curso y alertas.", "ESTADO")


# ------------------------------------------------------------------ helpers de UI
def _hero(titulo, USR, sub=None, icono="🏭"):
    hoy = date.today().strftime("%d/%m/%Y")
    sub = sub or f"Hola <b>{USR['nombre_full']}</b> — todo el proceso de la planta en un solo lugar."
    st.markdown(
        f"""<div class="worms-hero"><div class="glow"></div>
        <h1>{icono} {titulo}</h1><p>{sub}</p>
        <span class="chip">👤 {USR['rol'].title()} · 📅 {hoy}</span></div>""",
        unsafe_allow_html=True)


def _tile(col, icono, titulo, desc, key, on_click, disabled=False, label="Entrar", tipo="primary", atenuado=False):
    with col:
        with st.container(border=True):
            op = ' style="opacity:.55"' if atenuado else ""
            st.markdown(f'<div class="tile-h"{op}>{icono} {titulo}</div><div class="tile-d"{op}>{desc or ""}</div>',
                        unsafe_allow_html=True)
            st.button(label, type=tipo, use_container_width=True, key=key,
                      disabled=disabled, on_click=on_click)


def _grid(items, por_fila=3):
    """items = lista de dicts(icono, titulo, desc, key, on_click, disabled, label, tipo, atenuado)."""
    for i in range(0, len(items), por_fila):
        cols = st.columns(por_fila)
        for col, it in zip(cols, items[i:i + por_fila]):
            _tile(col, **it)


def _bc_cb(area, volver_portada):
    def _cb():
        _st.set_nav(area, rerun=False)
        if volver_portada:
            st.session_state.section = None
    return _cb


def breadcrumb(ctx, mostrar_raiz=True, volver_portada=False):
    """Migas: Sistema › Área › Sector. En la portada navega entre niveles; arriba de
    una sección (``volver_portada=True``) además sale de la sección."""
    nav = _st.get_nav()
    partes = []
    if mostrar_raiz:
        partes.append(("🏭 Sistema", _bc_cb(None, volver_portada)))
    if nav["area"]:
        ic, nm = _st.AREAS[nav["area"]]
        partes.append((f"{ic} {nm.title()}", _bc_cb(nav["area"], volver_portada)))
    if nav["sector"]:
        sec = sector_por_codigo(ctx["conn_factory"], nav["sector"])
        if sec:
            partes.append((f"{sec['icono']} {sec['nombre_ui']}", None))
    if not partes:
        return
    cols = st.columns([1] * len(partes) + [max(1, 6 - len(partes))])
    for col, (lbl, fn) in zip(cols, partes):
        with col:
            if fn is None:
                st.markdown(f"**{lbl}**")
            else:
                st.button(lbl, key=f"nav_bc_{lbl}", on_click=fn, use_container_width=True)


# ------------------------------------------------------------------ navegación
def _ir(ctx, area, sector, seccion):
    """Fija el lugar en la URL y entra a la sección clásica que hoy cubre esa tarjeta."""
    def _cb():
        _st.set_nav(area, sector, rerun=False)
        st.session_state.section = seccion
    return _cb


def _areas_permitidas(ctx):
    puede = ctx["puede_seccion"]
    adm = any(puede(s) for s in ADMIN_SECS)
    prod = any(puede(s) for s in ctx["secciones"] if s not in ADMIN_SECS and s != SOPORTE_SEC)
    return prod, adm


# ------------------------------------------------------------------ pantallas
def _raiz(ctx):
    USR = ctx["USR"]
    _hero("SISTEMA WORMS ARGENTINA", USR)
    prod, adm = _areas_permitidas(ctx)
    items = []
    if adm:
        items.append(dict(icono="👷", titulo="ADMINISTRACIÓN", desc="Cierres mensuales, dirección, ISCC, consultas IA y administración de usuarios.",
                          key="nav_area_admin", on_click=lambda: _st.set_nav("ADMIN", rerun=False)))
    if prod:
        items.append(dict(icono="🧪", titulo="PRODUCCIÓN", desc="Sectores de planta, planificación, reportes y panel de control.",
                          key="nav_area_prod", on_click=lambda: _st.set_nav("PRODUCCION", rerun=False)))
    if not items:
        st.info("No tenés secciones habilitadas. Pedile al administrador que te dé acceso.")
        return
    _grid(items, por_fila=2)
    _pie_soporte(ctx)


def _area_admin(ctx):
    USR, puede = ctx["USR"], ctx["puede_seccion"]
    _hero("ADMINISTRACIÓN", USR, icono="👷")
    tiles = [t for t in ctx["tiles"] if t["sec"] in ADMIN_SECS and puede(t["sec"])]
    _grid([dict(icono=t["icono"], titulo=t["titulo"], desc=t["desc"], key=f"nav_adm_{t['sec']}",
                on_click=_ir(ctx, "ADMIN", None, t["sec"])) for t in tiles])
    _pie_soporte(ctx)


def _area_produccion(ctx):
    USR, puede = ctx["USR"], ctx["puede_seccion"]
    _hero("ÁREA PRODUCCIÓN", USR, icono="🏭")

    # --- Indicadores del área: Fase 1 (a validar con Eugenia, Pablo y Fernando) ---
    kpis = ctx.get("render_kpis_area")
    if callable(kpis):
        kpis(ctx)
    else:
        st.caption("Indicadores del área: próximamente (acopio disponible · descargas pendientes · "
                   "personal en planta · sectores activos · tickets pendientes de análisis).")

    # --- Planificación / Reportes / Panel de Control ---
    fijas = [dict(icono=i, titulo=t, desc=d, key=f"nav_prod_{s}", on_click=_ir(ctx, "PRODUCCION", None, s))
             for (i, t, d, s) in _PROD_FIJAS if puede(s)]
    i, t, d, s = _PANEL_CONTROL
    if puede(s):
        fijas.append(dict(icono=i, titulo=t, desc=d, key=f"nav_prod_{s}", on_click=_ir(ctx, "PRODUCCION", None, s)))
    if fijas:
        _grid(fijas, por_fila=3)

    # --- Grilla de sectores (14) ---
    st.markdown('<div class="section-title">Sectores</div>', unsafe_allow_html=True)
    df = sectores_nav(ctx["conn_factory"])
    items = []
    for _, r in df.iterrows():
        sec_cl = r.get("seccion_clasica")
        habil = bool(sec_cl) and puede(sec_cl)
        sin_datos = not bool(r.get("tiene_datos"))
        if not sec_cl:
            lbl, dis, tipo = "Próximamente", True, "secondary"
        elif not habil:
            lbl, dis, tipo = "Sin acceso", True, "secondary"
        else:
            lbl, dis, tipo = "Entrar", False, "primary"
        items.append(dict(icono=r["icono"], titulo=r["nombre_ui"], desc=r.get("descripcion") or "",
                          key=f"nav_sec_{r['codigo']}", disabled=dis, label=lbl, tipo=tipo,
                          atenuado=sin_datos or dis,
                          on_click=(_ir(ctx, "PRODUCCION", r["codigo"], sec_cl) if habil else None)))
    _grid(items, por_fila=3)

    # --- Todo lo que hoy existe y todavía no tiene tarjeta propia: no se pierde nada ---
    cubiertas = set(df["seccion_clasica"].dropna().tolist()) | {s for (_, _, _, s) in _PROD_FIJAS} | {_PANEL_CONTROL[3]}
    resto = [t for t in ctx["tiles"] if t["sec"] not in ADMIN_SECS and t["sec"] != SOPORTE_SEC
             and t["sec"] not in cubiertas and puede(t["sec"])]
    if resto:
        with st.expander(f"Otros accesos ({len(resto)}) — vista clásica", expanded=False):
            _grid([dict(icono=t["icono"], titulo=t["titulo"], desc=t["desc"], key=f"nav_resto_{t['sec']}",
                        on_click=_ir(ctx, "PRODUCCION", None, t["sec"])) for t in resto])
    _pie_soporte(ctx)


def _pie_soporte(ctx):
    if ctx["puede_seccion"](SOPORTE_SEC):
        st.divider()
        st.button("🛠️ Mejoras y problemas — ¿algo no anda o falta?", key="nav_soporte",
                  on_click=_ir(ctx, _st.get_nav()["area"], None, SOPORTE_SEC))


# ------------------------------------------------------------------ entrada
def render_landing(ctx):
    """Portada con la navegación nueva. ``ctx``: USR, conn_factory, puede_seccion,
    secciones (códigos), tiles (dicts icono/titulo/desc/sec), render_kpis_area (opcional)."""
    nav = _st.get_nav()
    prod, adm = _areas_permitidas(ctx)
    # Un solo área habilitada: no tiene sentido mostrar la raíz.
    if nav["area"] is None and (prod != adm):
        _st.set_nav("PRODUCCION" if prod else "ADMIN", rerun=False)
        nav = _st.get_nav()
    if nav["area"] is None:
        _raiz(ctx)
        return
    breadcrumb(ctx)
    if nav["area"] == "ADMIN":
        _area_admin(ctx)
    else:
        _area_produccion(ctx)


def sidebar_toggle(USR, conn_factory, roles=("ADMIN", "SUPERVISOR")):
    """Botón Vista nueva / Vista clásica. Fase 0: sólo admin y supervisores lo ven;
    el flag queda guardado en dim_usuario.prefs.nav_v2 para ese usuario."""
    if USR.get("rol") not in roles:
        return
    on = _st.nav_activo_pref(USR, conn_factory)

    def _toggle():
        _st.set_nav_pref(USR, conn_factory, not on)
        _st.clear_nav_qp()
        st.session_state.section = None

    st.button("↩️ Volver a la vista clásica" if on else "🧭 Probar la navegación nueva",
              key="nav_toggle", use_container_width=True, on_click=_toggle,
              help="Navegación por áreas y sectores (propuesta de dirección). Sólo cambia cómo se entra a las secciones.")
