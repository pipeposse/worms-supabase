# -*- coding: utf-8 -*-
"""Bandeja HOY (Fase 6): el trabajo pendiente como una cola, no como un mapa.

La navegación por área → sector → vista contesta *dónde estoy*. Esta pantalla
contesta *qué falta hacer*, que es lo que alguien necesita saber al entrar:

    🔴 AHORA      RE-409 · faltan 12 de 16 pasos      [Cargar paso →]
    🟡 HOY        15 AFE aprobados sin tanque          [Asignar →]
    ⚪ REVISAR    101 tickets de laboratorio           [Ver →]

Cada fila sale de produccion.v_pendientes y su botón abre el lugar exacto donde
se resuelve — la misma navegación de siempre, pero traída al frente. Una fila
desaparece cuando el dato de abajo cambia; las que no tienen resolución natural
(un desvío ya mirado) se marcan vistas en fact_pendiente_resuelto.

QUIÉN VE QUÉ: se filtra por ``puede_seccion`` sobre la columna ``seccion``. El
operario de INICIAR ve sus pasos y sus OP; el supervisor ve además desvíos y
planificación. No hay roles hardcodeados acá.
"""

import pandas as pd
import streamlit as st

from . import state as _st
from .kpis import _FRAGMENT, _TTL, _kpi, _rerun_fragment

# Tipos que no se resuelven solos: se pueden marcar como vistos.
MARCABLES = ("DESVIO", "ALERTA", "TANQUES_LLENOS", "OP_SIN_FORMULA", "MUESTRA_FALTA",
             "AFE_SIN_TANQUE", "CAMION", "OP_SIN_CIERRE_HIST")

# Etiqueta del botón según lo que hay que hacer con la fila.
_ACCION = {
    "PASO":           "Cargar paso",
    "OP_ARRANCAR":    "Arrancar",
    "OP_SIN_FORMULA": "Asignar fórmula",
    "OP_SIN_EVENTO":  "Ver la OP",
    "DESVIO":         "Ver desvíos",
    "LAB_VALIDAR":    "Ver en Laboratorio",
    "OP_SIN_CIERRE":  "Cargar acopio",
    "OP_SIN_CIERRE_HIST": "Ver órdenes",
    "MUESTRA_FALTA":  "Ver la cola del lab",
    "LAB_CONCILIAR":  "Confirmar",
    "AFE_SIN_TANQUE": "Asignar tanques",
    "CAMION":         "Ver portería",
    "ALERTA":         "Ver panel",
    "TANQUES_LLENOS": "Ver tanques",
    "MOV_DUPLICADO":  "Ver el tanque",
}
# El punto de la banda se dibuja con CSS, no con emoji: ⚪ sale como una bola con
# degradado según la fuente del sistema y ensucia justo donde el color significa algo.
_BANDAS = [(1, "var(--bad)", "AHORA", "bad"), (2, "var(--warn)", "HOY", "warn"),
           (3, "var(--line-3)", "PARA REVISAR", "")]
# Ojo: lleva un 50% adentro, así que se arma con .format() y no con %s.
_PUNTO = ("<span style='display:inline-block;width:8px;height:8px;border-radius:50%;"
          "background:{};flex:none'></span>")

# Vista de Seguimiento por sector (igual que plan_semanal: las etiquetas de INICIAR mandan).
_SEGUIMIENTO = {
    "PILETAS":     ("INICIAR", {"iniciar_view": "♻️ Recuperación AG"}),
    "EXPORTACION": ("INICIAR", {"iniciar_view": "🚢 Exportación"}),
}
_SEG_DEFAULT = ("INICIAR", {"iniciar_view": "👷 Iniciar producción"})


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _leer(_cf):
    sql = ("SELECT tipo, ref, marca, prioridad, titulo, detalle, seccion, vista, sector_nav, "
           "id_batch, op, cuando, n FROM produccion.v_pendientes "
           "WHERE NOT resuelto ORDER BY prioridad, cuando NULLS LAST")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn)
        df["prioridad"] = pd.to_numeric(df["prioridad"], errors="coerce").fillna(3).astype(int)
        return df
    except Exception:
        return None


def _marcar(conectar, USR, tipo, ref, marca):
    with conectar(int(USR["id_usuario"])) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO produccion.fact_pendiente_resuelto (tipo, ref, marca, id_usuario) "
                        "VALUES (%s,%s,%s,%s) ON CONFLICT (tipo, ref, marca) DO NOTHING",
                        (tipo, ref, marca or "", int(USR["id_usuario"])))
        audit.log("I", "fact_pendiente_resuelto", 0, {"tipo": tipo, "ref": ref, "marca": marca or ""})


def invalidar():
    _leer.clear()


def visibles(df, puede, sector=None):
    """Filas que este usuario puede resolver. Sin ``seccion`` = visible para todos."""
    if df is None or df.empty:
        return df
    ok = df["seccion"].isna() | df["seccion"].map(lambda s: bool(s) and puede(s))
    out = df[ok]
    if sector:
        out = out[out["sector_nav"].fillna("") == sector]
    return out


def hay_pendientes(ctx):
    """¿Este usuario tiene algo pendiente que pueda resolver? Decide si el área abre
    en la bandeja o directo en el mapa de sectores (una bandeja vacía como portada
    sería un clic de más para llegar a cualquier lado)."""
    try:
        v = visibles(_leer(ctx["conn_factory"]), ctx["puede_seccion"])
        return v is not None and not v.empty
    except Exception:
        return False


def contar(df):
    """(urgentes, hoy, revisar) de un df ya filtrado."""
    if df is None or df.empty:
        return 0, 0, 0
    p = df["prioridad"]
    return int((p == 1).sum()), int((p == 2).sum()), int((p == 3).sum())


# ------------------------------------------------------------------ navegación
def _ir(fila):
    """Abre donde se resuelve la fila: vista de nav si la tiene, sección clásica si no."""
    tipo = fila["tipo"]
    sector = fila.get("sector_nav") or None
    vista = fila.get("vista") or None
    seccion = fila.get("seccion") or None
    id_batch = fila.get("id_batch")

    if vista == "SEGUIMIENTO":
        sec_cl, presets = _SEGUIMIENTO.get(sector, _SEG_DEFAULT)
        if id_batch is not None and not pd.isna(id_batch):
            st.session_state["pp_sel_id_batch"] = int(id_batch)   # carga_por_id.py preselecciona la OP
        for k, v in presets.items():
            st.session_state[k] = v
        _st.set_nav("PRODUCCION", sector, "SEGUIMIENTO", rerun=False)
        st.session_state.section = sec_cl
    elif tipo in ("MUESTRA_FALTA", "LAB_CONCILIAR"):
        _st.set_nav("PRODUCCION", None, "LABCONC", rerun=False)
        st.session_state.section = None
    elif vista in ("PLAN", "DESVIOS", "STOCK") and sector:
        _st.set_nav("PRODUCCION", sector, vista, rerun=False)
        st.session_state.section = None
    else:
        _st.set_nav("PRODUCCION", sector, None, rerun=False)
        st.session_state.section = seccion
    st.rerun()


# ------------------------------------------------------------------ pantalla
_SEP = ("<div style='height:1px;background:var(--line);"
        "margin:2px 0 2px;opacity:.9'></div>")


def _fila(ctx, r, compacta=False, sep=False):
    """Una línea de la bandeja. NO es una tarjeta: la tarjeta es la banda entera.

    Siete filas, cada una en su caja con su propio aire, daban tres pantallas de
    rectángulos iguales y un hueco enorme entre el texto y el botón. Una bandeja se
    lee como una lista: renglones al hilo, separados por una línea fina, con la
    acción al costado. El ✓ es terciario (sin caja) para que no compita con la
    acción, que es lo único que tiene que resaltar.
    """
    USR, conectar = ctx["USR"], ctx.get("conectar")
    key = f"{r['tipo']}_{r['ref']}".replace(":", "_").replace(".", "_")
    if sep:
        st.markdown(_SEP, unsafe_allow_html=True)
    marcable = (not compacta) and r["tipo"] in MARCABLES and conectar is not None
    c1, c2, c3 = st.columns([7, 2.1, 0.5] if not compacta else [7, 2.3, 0.01],
                            vertical_alignment="center")
    with c1:
        st.markdown(
            f"<div style='font-weight:700;font-size:0.94rem;line-height:1.3'>{r['titulo']}</div>"
            f"<div style='color:var(--muted);font-size:0.84rem;margin-top:1px;"
            f"line-height:1.35'>{r['detalle'] or ''}</div>",
            unsafe_allow_html=True)
    if c2.button(_ACCION.get(r["tipo"], "Abrir") + " →", key=f"nav_hoy_go_{key}",
                 use_container_width=True, type=("primary" if r["prioridad"] == 1 else "secondary")):
        _ir(r)
    if marcable:
        if c3.button("✓", key=f"nav_hoy_ok_{key}", type="tertiary",
                     help="Ya lo miré: sacarlo de la bandeja. Si el estado cambia, vuelve a aparecer."):
            try:
                _marcar(conectar, USR, r["tipo"], r["ref"], r.get("marca"))
                invalidar()
                _rerun_fragment()
            except Exception as e:
                st.error(f"No se pudo marcar: {e}")


@_FRAGMENT
def _cola(ctx, sector=None):
    df = _leer(ctx["conn_factory"])
    if df is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    v = visibles(df, ctx["puede_seccion"], sector)
    u, h, rv = contar(v)

    k1 = _kpi("Para ahora", str(u), "atrasado o fuera de tolerancia", "bad" if u else "ok")
    k2 = _kpi("Para hoy", str(h), "el trabajo del día", "warn" if h else "")
    k3 = _kpi("Para revisar", str(rv), "no urgente, pero no se resuelve solo", "")
    st.markdown(f'<div class="kpi-grid">{k1}{k2}{k3}</div>', unsafe_allow_html=True)

    if v is None or v.empty:
        st.success("No hay nada pendiente para vos en este momento. 👌")
        st.caption("La bandeja muestra sólo lo que podés resolver con tus accesos.")
        return

    for pri, color, titulo, _cls in _BANDAS:
        grupo = v[v["prioridad"] == pri]
        if grupo.empty:
            continue
        st.markdown(f"<div class='section-title' style='margin:18px 0 6px'>{_PUNTO.format(color)}"
                    f"{titulo} · {len(grupo)}</div>", unsafe_allow_html=True)
        # Una sola tarjeta por banda, con las filas al hilo adentro.
        with st.container(border=True):
            for _i, (_, r) in enumerate(grupo.iterrows()):
                _fila(ctx, r, sep=(_i > 0))


def render_hoy(ctx):
    """Bandeja completa (vista HOY del área Producción)."""
    from .portada import _hero, _pie_soporte
    USR = ctx["USR"]
    _hero("HOY EN PLANTA", USR, icono="📋",
          sub="Lo que falta hacer ahora mismo, en una sola lista. Cada fila abre el lugar donde se resuelve.")
    df = _leer(ctx["conn_factory"])
    sector = None
    if df is not None and not df.empty:
        from .sectores import sectores_nav
        secs = sectores_nav(ctx["conn_factory"])
        con_pend = [s for s in df["sector_nav"].dropna().unique().tolist()]
        if len(con_pend) > 1:
            nombres = {r["codigo"]: f"{r['icono']} {r['nombre_ui']}" for _, r in secs.iterrows()}
            opciones = ["TODOS"] + [c for c in con_pend if c in nombres]
            if "nav_hoy_sector" not in st.session_state:
                st.session_state["nav_hoy_sector"] = "TODOS"
            sel = st.radio("Sector", opciones, horizontal=True, key="nav_hoy_sector",
                           format_func=lambda c: "🏭 Toda la planta" if c == "TODOS" else nombres.get(c, c),
                           label_visibility="collapsed")
            sector = None if sel == "TODOS" else sel
    _cola(ctx, sector)
    st.divider()
    c1, c2 = st.columns([1.4, 3])
    c1.button("🏭 Sectores de planta →", key="nav_hoy_sectores", use_container_width=True,
              on_click=lambda: _st.set_nav("PRODUCCION", None, "SECTORES", rerun=False),
              help="La grilla de los 14 sectores, indicadores del área y accesos de siempre.")
    c2.caption("Prioridad: 🔴 lo atrasado o fuera de tolerancia · 🟡 lo del día · ⚪ lo que conviene mirar. "
               "Las filas se van solas cuando el trabajo se hace; ✓ es para las que ya miraste (si cambia el estado, vuelven).")
    _pie_soporte(ctx)


def banner(ctx, maximo=3):
    """Resumen compacto para arriba de una sección clásica (usuarios anclados a una sola).

    Deliberadamente chico: lo urgente, hasta ``maximo`` filas, sin filtros ni KPIs.
    Devuelve True si dibujó algo."""
    df = _leer(ctx["conn_factory"])
    v = visibles(df, ctx["puede_seccion"])
    if v is None or v.empty:
        return False
    urgente = v[v["prioridad"] <= 2]
    if urgente.empty:
        return False
    u, h, _ = contar(v)
    resumen = " · ".join(x for x in ((f"{u} para ahora" if u else ""), (f"{h} para hoy" if h else "")) if x)
    with st.expander(f"📋 Tu trabajo pendiente — {resumen}", expanded=bool(u)):
        for _, r in urgente.head(maximo).iterrows():
            _fila(ctx, r, compacta=True)
        if len(urgente) > maximo:
            st.caption(f"…y {len(urgente) - maximo} más.")
    return True
