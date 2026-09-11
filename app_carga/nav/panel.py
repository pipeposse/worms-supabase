# -*- coding: utf-8 -*-
"""Panel de Control · capacidad de la planta.

Pedido textual de dirección (Sistema WORMS.xlsx, hoja "Produccion Planta"):

    "MOSTRARIA POR PRODUCTO UN GRAFICO DE BARRA CON % DE CAPACIDAD DE ACOPIO"
    "USAR LA PLANILLA DE PARAMETROS"
    "MOSTRARIA LA CAPACIDAD TOTAL OCUPADA DE LA PLANTA Y NO MUCHO MAS"

Esa última línea es la que manda: esta pantalla contesta UNA pregunta —¿cuánto
lugar queda y dónde se está por acabar?— y no intenta ser un tablero general.
Todo lo demás (alertas, reacciones, estado de planta) sigue viviendo en la
sección Panel de Control clásica, a un botón de acá.

Los datos salen de ``produccion.v_capacidad_ocupada_producto``, que ya cruza la
capacidad declarada de cada tanque (la "planilla de parámetros" cargada en
``dim_tanque``) contra la última medición física. Las barras se dibujan en HTML:
sin librería de gráficos, sin rerun y con los mismos tokens de color del
sistema, así el rojo de un producto al límite significa lo mismo acá que en la
bandeja HOY.
"""

import pandas as pd
import streamlit as st

from .kpis import _FRAGMENT, _TTL, _kpi

# Umbrales de ocupación. Por encima de LLENO no entra un camión más.
_LLENO, _APRETADO = 90.0, 75.0
_MIN_KL = 1.0          # tanques de menos de 1 kL (soda, gasoil) no ordenan la lista


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _capacidad(_cf):
    try:
        with _cf() as conn:
            return pd.read_sql_query(
                "SELECT producto, tanques, cap_kl, act_kl, libre_kl, pct_ocupado, incluye_piletas "
                "FROM produccion.v_capacidad_ocupada_producto "
                "WHERE cap_kl > 0 ORDER BY pct_ocupado DESC, cap_kl DESC", conn)
    except Exception:
        return None


@st.cache_data(ttl=_TTL, show_spinner=False)
def _evaluados(_cf):
    """% de ingresos evaluados por laboratorio. El objetivo declarado es 100%."""
    try:
        with _cf() as conn:
            df = pd.read_sql_query(
                "SELECT ventana, ingresos, evaluados, sin_evaluar, pct_evaluado, peor_corriente "
                "FROM produccion.v_kpi_ingresos_evaluados", conn)
        return {r["ventana"]: r for _, r in df.iterrows()} if not df.empty else {}
    except Exception:
        return {}


def invalidar():
    _capacidad.clear(); _evaluados.clear()


# ------------------------------------------------------------------ dibujo
def _estado(pct):
    if pct >= _LLENO:
        return "bad"
    if pct >= _APRETADO:
        return "warn"
    return ""


def _barra(producto, pct, act, cap, libre, tanques, piletas):
    """Una fila: nombre · barra horizontal · kL. El ancho es el % ocupado."""
    cls = _estado(pct)
    color = {"bad": "var(--bad)", "warn": "var(--warn)"}.get(cls, "var(--accent)")
    ancho = max(0.6, min(100.0, pct))
    det = f"{tanques} tanque{'s' if tanques != 1 else ''}" + (" + piletas" if piletas else "")
    return (
        '<div class="cap-row">'
        f'<div class="cap-n" title="{det}">{producto}</div>'
        f'<div class="cap-t"><div class="cap-f" style="width:{ancho:.4g}%;background:{color}"></div></div>'
        f'<div class="cap-p{" " + cls if cls else ""}">{pct:.0f}%</div>'
        f'<div class="cap-k">{act:,.0f} / {cap:,.0f} kL<span>libre {libre:,.0f}</span></div>'
        '</div>'
    ).replace(",", ".")


_CSS = """
<style>
.cap-wrap{display:flex; flex-direction:column; gap:2px; border:1px solid var(--line);
          border-radius:8px; padding:12px 14px; background:var(--surface);}
.cap-row{display:grid; grid-template-columns:150px 1fr 44px 132px; align-items:center;
         gap:12px; padding:5px 0; border-bottom:1px solid var(--line);}
.cap-row:last-child{border-bottom:0;}
.cap-n{font-size:.84rem; font-weight:600; color:var(--ink); overflow:hidden;
       text-overflow:ellipsis; white-space:nowrap;}
.cap-t{height:9px; background:var(--surface-2); border-radius:2px; overflow:hidden;}
.cap-f{height:100%; border-radius:2px;}
.cap-p{font-family:'Barlow Condensed',sans-serif; font-size:1.15rem; font-weight:700;
       text-align:right; color:var(--ink); line-height:1;}
.cap-p.warn{color:var(--warn);} .cap-p.bad{color:var(--bad);}
.cap-k{font-size:.74rem; color:var(--muted); text-align:right; line-height:1.25;}
.cap-k span{display:block; color:var(--faint); font-size:.7rem;}
@media (max-width:740px){
  .cap-row{grid-template-columns:96px 1fr 38px; gap:8px;}
  .cap-k{display:none;}
}
</style>
"""


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def _panel(ctx):
    cf = ctx["conn_factory"]
    df = _capacidad(cf)
    if df is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    if df.empty:
        st.info("Todavía no hay capacidad cargada en los tanques. Se toma de la planilla de parámetros "
                "(capacidad declarada en Tanques).")
        return

    for c in ("cap_kl", "act_kl", "libre_kl", "pct_ocupado"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["tanques"] = pd.to_numeric(df["tanques"], errors="coerce").fillna(0).astype(int)

    cap, act = float(df["cap_kl"].sum()), float(df["act_kl"].sum())
    pct = (act / cap * 100.0) if cap else 0.0
    libre = cap - act
    llenos = df[df["pct_ocupado"] >= _LLENO]
    apretados = df[(df["pct_ocupado"] >= _APRETADO) & (df["pct_ocupado"] < _LLENO)]

    ev = _evaluados(cf)
    e7 = ev.get("7D")

    k1 = _kpi("Capacidad ocupada", f"{pct:.0f}<span style='font-size:1.1rem;font-weight:700;'>%</span>",
              f"{act:,.0f} kL de {cap:,.0f} kL declarados".replace(",", "."),
              _estado(pct))
    k2 = _kpi("Lugar libre", f"{libre:,.0f}".replace(",", "."),
              "kilolitros para descargar en toda la planta",
              "bad" if libre <= 0 else ("warn" if pct >= _APRETADO else "ok"))
    k3 = _kpi("Productos al límite", str(len(llenos)),
              (f"sin lugar: {', '.join(llenos['producto'].head(3))}" if len(llenos)
               else (f"{len(apretados)} apretado(s) por encima del {_APRETADO:.0f}%" if len(apretados)
                     else "ninguno por encima del 90%")),
              "bad" if len(llenos) else ("warn" if len(apretados) else "ok"))
    if e7 is not None:
        pev = float(e7["pct_evaluado"] or 0)
        k4 = _kpi("Ingresos evaluados", f"{pev:.0f}<span style='font-size:1.1rem;font-weight:700;'>%</span>",
                  f"últimos 7 días · {int(e7['sin_evaluar'])} sin analizar (objetivo 100%)",
                  "ok" if pev >= 95 else ("warn" if pev >= 80 else "bad"))
    else:
        k4 = _kpi("Ingresos evaluados", "—", "sin dato de portería en este momento", "")
    st.markdown(f'<div class="kpi-grid">{k1}{k2}{k3}{k4}</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-title">Capacidad de acopio por producto</div>', unsafe_allow_html=True)
    grandes = df[df["cap_kl"] >= _MIN_KL]
    chicos = df[df["cap_kl"] < _MIN_KL]
    filas = "".join(_barra(r["producto"], r["pct_ocupado"], r["act_kl"], r["cap_kl"],
                           r["libre_kl"], r["tanques"], bool(r["incluye_piletas"]))
                    for _, r in grandes.iterrows())
    st.markdown(_CSS + f'<div class="cap-wrap">{filas}</div>', unsafe_allow_html=True)
    st.caption("Capacidad declarada de cada tanque (planilla de parámetros) contra la última medición "
               "física. Un producto por encima del 90% no admite otro camión; por encima del 75% conviene "
               "mirarlo antes de comprometer una descarga.")
    if not chicos.empty:
        with st.expander(f"Recipientes chicos ({len(chicos)}) — menos de 1 kL", expanded=False):
            st.markdown(_CSS + '<div class="cap-wrap">' + "".join(
                _barra(r["producto"], r["pct_ocupado"], r["act_kl"], r["cap_kl"],
                       r["libre_kl"], r["tanques"], bool(r["incluye_piletas"]))
                for _, r in chicos.iterrows()) + '</div>', unsafe_allow_html=True)

    if ev.get("HOY") is not None and e7 is not None and e7["peor_corriente"]:
        h = ev["HOY"]
        st.caption(f"Ingresos evaluados hoy: {int(h['evaluados'])} de {int(h['ingresos'])} "
                   f"({float(h['pct_evaluado'] or 0):.0f}%). Por corriente, lo que no llega al 100%: "
                   f"{e7['peor_corriente']}. Las muestras del día suelen cargarse con unas horas de "
                   f"atraso: el número de 7 días es el que hay que mirar.")


def render_panel(ctx):
    from .portada import _hero, _pie_soporte
    _hero("PANEL DE CONTROL", ctx["USR"], icono="🎛️",
          sub="Cuánto lugar queda en la planta y dónde se está por acabar. "
              "El resto del estado de planta está en el panel clásico.")
    _panel(ctx)
    if ctx["puede_seccion"]("ESTADO"):
        st.markdown('<div class="section-title">Más detalle</div>', unsafe_allow_html=True)
        from . import state as _stt
        def _ir_estado():
            _stt.set_nav("PRODUCCION", None, None, rerun=False)
            st.session_state.section = "ESTADO"
        st.button("🎛️ Panel de Control clásico — alertas, reacciones y estado de planta →",
                  key="nav_panel_estado", on_click=_ir_estado)
    _pie_soporte(ctx)
