# -*- coding: utf-8 -*-
"""Stock de un sector: los movimientos, uno por fila, estilo origen → destino · ticket.

Pedido de dirección (14/09/2026):
  · cada sector muestra SÓLO lo suyo (el sector sale del tanque, no de un texto);
  · cada movimiento tiene su ID;
  · el período se elige por año, por semana o por fechas — nunca "últimos 30 días";
  · todo en toneladas (litros × densidad del producto), nunca kilolitros;
  · los grupos se llaman por su nombre (Materia prima / Insumos / Producto terminado)
    y el que no tiene movimientos no se muestra.

Sale de produccion.v_movimiento_sector.
"""

import io

import pandas as pd
import streamlit as st

from . import periodo as _per
from .kpis import _FRAGMENT, _TTL, _kpi, _n, _rerun_fragment

# el código del grupo nunca se muestra: se muestra el nombre
_GRUPO_LBL = {"MP": "Materia prima", "INSUMO": "Insumos", "PT": "Producto terminado", "OTRO": "Otros"}
_TIPOS = {"Todos": None, "⬇️ Entradas": "ENTRADA", "⬆️ Salidas": "SALIDA"}


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _movs(_cf, sector, desde, hasta):
    sql = ("SELECT id_mov, momento, fecha, tanque, producto, grupo, tipo, origen, destino, ticket, "
           "tickets_detalle, contraparte, kg, litros, kg_neto, referencia, fuente_dato, usuario, "
           "es_ajuste_sistema, observacion "
           "FROM produccion.v_movimiento_sector WHERE sector = %s AND fecha BETWEEN %s AND %s "
           "ORDER BY momento DESC, id_mov DESC")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector, desde, hasta))
        for c in ("kg", "litros", "kg_neto"):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
        df["es_ajuste_sistema"] = df["es_ajuste_sistema"].fillna(False).astype(bool)
        return df
    except Exception:
        return None


def invalidar():
    _movs.clear()


# ------------------------------------------------------------------ helpers
def _tn(x):
    """Toneladas con un decimal; vacío si es cero."""
    if x is None or pd.isna(x) or float(x) == 0:
        return ""
    return f"{float(x) / 1000.0:,.1f}"


def _tabla_director(df):
    ent = df["kg_neto"].map(lambda v: v if v > 0 else 0)
    sal = df["kg_neto"].map(lambda v: -v if v < 0 else 0)
    return pd.DataFrame({
        "ID": df["id_mov"].map(lambda i: "" if pd.isna(i) else f"{int(i)}"),
        "FECHA": df["momento"].map(lambda t: pd.to_datetime(t).strftime("%d/%m/%Y %H:%M") if not pd.isna(t) else ""),
        "#TICKET": df["ticket"].fillna(""),
        "PRODUCTO": df["producto"].fillna(""),
        "ORIGEN": df["origen"].fillna(""),
        "DESTINO": df["destino"].fillna(""),
        "ENTRADA TN": ent.map(_tn),
        "SALIDA TN": sal.map(_tn),
        "REF.": df["referencia"].fillna(""),
        "QUIÉN": df["usuario"].fillna(""),
    })


def _resumen_producto(df):
    ent = df["kg_neto"].map(lambda v: v if v > 0 else 0)
    sal = df["kg_neto"].map(lambda v: -v if v < 0 else 0)
    r = pd.DataFrame({"PRODUCTO": df["producto"].fillna("—"),
                      "TIPO": df["grupo"].fillna("OTRO").map(lambda g: _GRUPO_LBL.get(g, g)),
                      "ENTRADAS TN": ent, "SALIDAS TN": sal, "NETO TN": df["kg_neto"].fillna(0)})
    g = r.groupby("PRODUCTO", as_index=False).agg({
        "TIPO": lambda s: " · ".join(sorted({x for x in s if x})),
        "ENTRADAS TN": "sum", "SALIDAS TN": "sum", "NETO TN": "sum"})
    g = g.sort_values("NETO TN", ascending=False)
    for c in ("ENTRADAS TN", "SALIDAS TN", "NETO TN"):
        g[c] = g[c].map(lambda x: f"{float(x) / 1000.0:,.1f}")
    return g


def _ir_stock_clasico(ctx):
    def _cb():
        st.session_state.section = "STOCK"
    return _cb


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def _movimientos(ctx, sec):
    cod = sec["codigo"]
    desde, hasta, etiqueta = _per.selector(f"stk_{cod}")

    df = _movs(ctx["conn_factory"], cod, desde, hasta)
    if df is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    ajustes_n = int(df["es_ajuste_sistema"].sum())

    # Los grupos salen de los datos: si el sector no movió insumos, no hay pestaña de insumos.
    reales = df[~df["es_ajuste_sistema"]]
    presentes = [g for g in ("MP", "INSUMO", "PT", "OTRO") if (reales["grupo"] == g).any()]
    opciones = (["TODOS"] + presentes) if len(presentes) > 1 else presentes

    f1, f2, f3, f4 = st.columns([1.8, 1.3, 1.6, 0.5])
    grupo = "TODOS"
    if opciones:
        k_g = f"nav_mv_grupo_{cod}"
        if st.session_state.get(k_g) not in opciones:
            st.session_state[k_g] = opciones[0]
        grupo = f1.radio("Tipo", opciones, horizontal=True, key=k_g, label_visibility="collapsed",
                         format_func=lambda g: "Todo" if g == "TODOS" else _GRUPO_LBL.get(g, g))
    tipo = f2.radio("Movimiento", list(_TIPOS), index=0, horizontal=True,
                    key=f"nav_mv_tipo_{cod}", label_visibility="collapsed")
    busca = f3.text_input("Buscar", key=f"nav_mv_q_{cod}", placeholder="ID, ticket, cliente, tanque, producto…",
                          label_visibility="collapsed")
    if f4.button("↻", key=f"nav_mv_ref_{cod}", use_container_width=True, help="Releer ahora"):
        invalidar(); _rerun_fragment()
    ver_aj = False
    if ajustes_n:
        ver_aj = st.toggle(f"Ver ajustes automáticos de medición ({ajustes_n})", value=False, key=f"nav_mv_aj_{cod}",
                           help="Reconciliación contra los sensores: no es mercadería que entró o salió.")

    v = df if ver_aj else reales
    if grupo and grupo != "TODOS":
        v = v[v["grupo"] == grupo]
    if tipo and _TIPOS[tipo]:
        v = v[v["tipo"] == _TIPOS[tipo]]
    if busca.strip():
        q = busca.strip().lower()
        m = v["id_mov"].astype(str).str.contains(q, regex=False)
        for c in ("ticket", "tickets_detalle", "contraparte", "tanque", "producto", "origen", "destino", "referencia"):
            m = m | v[c].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        v = v[m]

    ing = float(v["kg_neto"].map(lambda x: x if x > 0 else 0).sum())
    egr = float(v["kg_neto"].map(lambda x: -x if x < 0 else 0).sum())
    k1 = _kpi("Entradas", f"{_n(ing/1000)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"{int((v['kg_neto'] > 0).sum())} movimientos · {etiqueta}", "")
    k2 = _kpi("Salidas", f"{_n(egr/1000)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"{int((v['kg_neto'] < 0).sum())} movimientos · {etiqueta}", "")
    k3 = _kpi("Neto del período", f"{(ing-egr)/1000:+,.1f}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"sólo {sec['nombre_ui']}", "warn" if ing - egr < 0 else "ok")
    k4 = _kpi("Movimientos", str(len(v)),
              (f"{ajustes_n} ajustes de medición escondidos" if (ajustes_n and not ver_aj) else "en la tabla de abajo"), "")
    st.markdown(f'<div class="kpi-grid">{k1}{k2}{k3}{k4}</div>', unsafe_allow_html=True)

    if v.empty:
        st.info(f"Sin movimientos de {sec['nombre_ui']} en {etiqueta} con esos filtros.")
        return
    tabla = _tabla_director(v)
    st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(620, 60 + 35 * len(tabla)))
    with st.expander(f"Resumen por producto ({v['producto'].nunique()})", expanded=False):
        st.dataframe(_resumen_producto(v), hide_index=True, use_container_width=True)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        tabla.to_excel(xw, index=False, sheet_name="Movimientos")
        _resumen_producto(v).to_excel(xw, index=False, sheet_name="Por producto")
    st.download_button("⬇️ Descargar Excel", buf.getvalue(),
                       file_name=f"stock_{cod.lower()}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"nav_mv_xls_{cod}")
    st.caption("Cada fila es un movimiento de stock de este sector y de ningún otro, con su ID del libro de stock. "
               "El ticket es el de portería; en una orden de venta se muestra el primero y cuántos más la acompañan "
               "(la lista completa está en el buscador y en el Excel). Todo en toneladas: los litros se pasan a kilos "
               "con la densidad del producto.")


def render_stock(ctx, sec):
    puede = ctx["puede_seccion"]
    c1, c2 = st.columns([3, 1.2])
    c1.markdown(f"<div class='section-title' style='margin:6px 0'>📦 Stock · {sec['nombre_ui']} · movimientos</div>",
                unsafe_allow_html=True)
    if puede("STOCK"):
        c2.button("📋 Stock clásico (físico por tanque)", key="nav_cc_clasico", use_container_width=True,
                  on_click=_ir_stock_clasico(ctx))
    _movimientos(ctx, sec)
