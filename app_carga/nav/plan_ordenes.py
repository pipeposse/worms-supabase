# -*- coding: utf-8 -*-
"""Planificación de Exportación: las ÓRDENES DE VENTA del período.

Exportación no planifica reacciones: planifica órdenes de venta (lo que antes la app
llamaba "despachos" — dirección no quiere leer esa palabra). Cada orden tiene su
cliente, su destino, los contenedores comprometidos, los tanques de los que se carga
y los tickets de portería de cada camión.

Fuente: produccion.fact_despacho + fact_despacho_linea + fact_despacho_ticket.
"""

import io

import pandas as pd
import streamlit as st

import cache_rev as _cache_rev   # caché que una escritura invalida (no sólo el TTL)

from . import periodo as _per
from . import state as _st
from .kpis import _FRAGMENT, _TTL, _kpi, _n, _rerun_fragment

_ESTADO_UI = {"BORRADOR": "📝 Borrador", "CONFIRMADO": "✅ Confirmada",
              "DESPACHADO": "🚚 Cargada", "ANULADO": "✖ Anulada"}


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _leer(_cf, desde, hasta):
    sql = """
        SELECT d.id_despacho AS id, d.titulo, d.cliente, d.destino, d.producto_codigo AS producto,
               d.tipo_carga, d.fecha_despacho AS fecha, d.semana_iso, d.anio, d.estado,
               d.n_contenedores, d.litros_por_contenedor, d.booking,
               COALESCE(l.tanques, 0) AS tanques, COALESCE(l.litros, 0) AS litros_plan,
               COALESCE(t.camiones, 0) AS camiones, COALESCE(t.kg, 0) AS kg_tickets,
               COALESCE(m.kg_mov, 0) AS kg_movimientos
        FROM produccion.fact_despacho d
        LEFT JOIN (SELECT id_despacho, count(*) AS tanques, sum(litros) AS litros
                     FROM produccion.fact_despacho_linea GROUP BY 1) l ON l.id_despacho = d.id_despacho
        LEFT JOIN (SELECT id_despacho, count(*) AS camiones, sum(kg) AS kg
                     FROM produccion.fact_despacho_ticket GROUP BY 1) t ON t.id_despacho = d.id_despacho
        LEFT JOIN (SELECT id_despacho, sum(kg) AS kg_mov
                     FROM produccion.fact_movimiento_stock
                    WHERE id_despacho IS NOT NULL AND NOT anulado GROUP BY 1) m ON m.id_despacho = d.id_despacho
        WHERE d.fecha_despacho BETWEEN %s AND %s
        ORDER BY d.fecha_despacho DESC, d.id_despacho DESC
    """
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(desde, hasta))
        for c in ("litros_plan", "kg_tickets", "kg_movimientos"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        return df
    except Exception:
        return None


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _tickets(_cf, id_orden):
    try:
        with _cf() as conn:
            return pd.read_sql_query(
                "SELECT ticket, empresa, fecha, producto, destino, patente, kg, nro_contenedor, precinto "
                "FROM produccion.fact_despacho_ticket WHERE id_despacho = %s ORDER BY ticket",
                conn, params=(int(id_orden),))
    except Exception:
        return None


def _invalidar():
    _leer.clear(); _tickets.clear()


def _tn(x):
    return "" if x is None or pd.isna(x) or float(x) == 0 else f"{float(x)/1000.0:,.1f}"


def _ir_armado():
    """Abre el armado de la orden de venta en el Centro de Planificación."""
    st.session_state["pl_grupo_sc"] = "🚢 Exportación"
    st.session_state["pl_grupo"] = "🚢 Exportación"
    st.session_state.section = "PLANIFICACION"


@_FRAGMENT
def _grilla(ctx, sec, desde, hasta, etiqueta):
    df = _leer(ctx["conn_factory"], desde, hasta)
    if df is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    c1, c2 = st.columns([3, 1.2])
    ver_anul = c1.toggle("Ver anuladas", value=False, key="nav_ov_anul")
    if c2.button("↻", key="nav_ov_ref", use_container_width=True, help="Releer ahora"):
        _invalidar(); _rerun_fragment()
    v = df if ver_anul else df[df["estado"] != "ANULADO"]

    cont = int(pd.to_numeric(v["n_contenedores"], errors="coerce").fillna(0).sum())
    k1 = _kpi("Órdenes de venta", str(len(v)), f"{etiqueta}", "")
    k2 = _kpi("Contenedores", str(cont), f"{int(v['camiones'].sum())} camiones con ticket de portería", "")
    k3 = _kpi("Cargado", f"{_n(v['kg_movimientos'].sum()/1000)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              "salidas de tanque registradas en el stock", "")
    k4 = _kpi("Pesado en balanza", f"{_n(v['kg_tickets'].sum()/1000)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              "suma de los tickets de portería de los camiones", "")
    st.markdown(f'<div class="kpi-grid">{k1}{k2}{k3}{k4}</div>', unsafe_allow_html=True)

    if v.empty:
        st.info(f"No hay órdenes de venta en {etiqueta}.")
        return
    tabla = pd.DataFrame({
        "ID": v["id"], "ORDEN": v["titulo"].fillna(""), "FECHA": v["fecha"].map(lambda d: pd.to_datetime(d).strftime("%d/%m/%Y")),
        "SEM": v["semana_iso"], "CLIENTE": v["cliente"].fillna(""), "DESTINO": v["destino"].fillna(""),
        "PRODUCTO": v["producto"].fillna(""), "CONT.": v["n_contenedores"].fillna(0).astype(int),
        "TANQUES": v["tanques"].astype(int), "CAMIONES": v["camiones"].astype(int),
        "CARGADO TN": v["kg_movimientos"].map(_tn), "BALANZA TN": v["kg_tickets"].map(_tn),
        "ESTADO": v["estado"].map(lambda e: _ESTADO_UI.get(e, e)),
    })
    st.dataframe(tabla, hide_index=True, use_container_width=True)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        tabla.to_excel(xw, index=False, sheet_name="Órdenes de venta")
    st.download_button("⬇️ Descargar Excel", buf.getvalue(),
                       file_name=f"ordenes_venta_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="nav_ov_xls")

    # detalle de una orden: los camiones y sus tickets
    ids = v["id"].tolist()
    lbl = {int(r["id"]): f"#{int(r['id'])} · {r['titulo'] or ''} · {r['cliente'] or ''}" for _, r in v.iterrows()}
    sel = st.selectbox("Ver los camiones de una orden", ids, format_func=lambda i: lbl.get(int(i), str(i)),
                       key="nav_ov_sel")
    tk = _tickets(ctx["conn_factory"], sel)
    if tk is None or tk.empty:
        st.caption("Esta orden todavía no tiene tickets de portería asignados.")
    else:
        tk["kg"] = pd.to_numeric(tk["kg"], errors="coerce")
        det = pd.DataFrame({
            "#TICKET": tk["ticket"], "FECHA": tk["fecha"].map(lambda d: pd.to_datetime(d).strftime("%d/%m/%Y") if pd.notna(d) else ""),
            "EMPRESA": tk["empresa"].fillna(""), "PATENTE": tk["patente"].fillna(""),
            "CONTENEDOR": tk["nro_contenedor"].fillna(""), "PRECINTO": tk["precinto"].fillna(""),
            "TN": tk["kg"].map(_tn),
        })
        st.dataframe(det, hide_index=True, use_container_width=True)
        st.caption(f"{len(det)} camión(es) · {_n(float(tk['kg'].sum() or 0)/1000)} TN pesadas en balanza.")


def render_plan_ordenes(ctx, sec):
    c1, c2 = st.columns([3, 1.4])
    c1.markdown("<div class='section-title' style='margin:6px 0'>🗓️ Planificación · Exportación · órdenes de venta</div>",
                unsafe_allow_html=True)
    if ctx["puede_seccion"]("PLANIFICACION"):
        c2.button("🚢 Armar orden de venta", key="nav_ov_armar", use_container_width=True, on_click=_ir_armado,
                  help="Centro de Planificación: arma la orden, elige tanques y asigna los tickets de portería.")
    desde, hasta, etiqueta = _per.selector("plan_EXPORTACION")
    _grilla(ctx, sec, desde, hasta, etiqueta)
    st.caption("CARGADO = salidas de tanque registradas en el libro de stock. BALANZA = suma de los tickets de "
               "portería de los camiones de esa orden. Las dos tienen que parecerse; si no, mirá Desvíos.")
