# -*- coding: utf-8 -*-
"""Stock de un sector: los movimientos, uno por fila, estilo origen → destino · ticket.

Pedido de dirección (14/09/2026): "quiero ver los movimientos de stock de exportación;
cada sector tiene que mostrar sólo lo suyo". Antes esta pantalla salía de
v_cuenta_corriente_producto, que resolvía el sector por el TEXTO del tanque: los
despachos y las decantaciones no traen ese texto, así que Exportación no veía ninguna
salida y se mezclaban movimientos de otros sectores.

Ahora sale de produccion.v_movimiento_sector, donde el sector se resuelve por el tanque
(dato duro) y cada fila ya dice de dónde salió y a dónde fue:

    FECHA · TICKET · PRODUCTO · ORIGEN → DESTINO · ENTRADA KG · SALIDA KG · REF · QUIÉN

Los ajustes automáticos de medición (reconciliación con los sensores) quedan escondidos
detrás de un tilde: no son movimientos de mercadería.
"""

import io
from datetime import date

import pandas as pd
import streamlit as st

from .kpis import _FRAGMENT, _TTL, _kpi, _n, _rerun_fragment

GRUPOS = [("TODOS", "Todo"), ("MP", "🛢️ Materia Prima"), ("INSUMO", "⚗️ Insumos"), ("PT", "📦 Producto Terminado")]
_GRUPO_LBL = dict(GRUPOS)
_RANGOS = {"30 días": 30, "90 días": 90, "12 meses": 365, "Todo": None}
_TIPOS = {"Todos": None, "⬇️ Entradas": "ENTRADA", "⬆️ Salidas": "SALIDA"}


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _movs(_cf, sector, dias):
    sql = ("SELECT momento, fecha, tanque, producto, grupo, tipo, origen, destino, ticket, tickets_detalle, "
           "contraparte, kg, litros, kg_neto, referencia, fuente_dato, usuario, es_ajuste_sistema, observacion "
           "FROM produccion.v_movimiento_sector WHERE sector = %s")
    params = [sector]
    if dias:
        sql += " AND fecha >= current_date - %s"
        params.append(int(dias))
    sql += " ORDER BY momento DESC, id_mov DESC"
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=tuple(params))
        for c in ("kg", "litros", "kg_neto"):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
        df["es_ajuste_sistema"] = df["es_ajuste_sistema"].fillna(False).astype(bool)
        return df
    except Exception:
        return None


def invalidar():
    _movs.clear()


# ------------------------------------------------------------------ helpers
def _fmt_kg(x):
    return "" if x is None or pd.isna(x) or float(x) == 0 else f"{float(x):,.0f}"


def _tabla_director(df):
    ent = df["kg_neto"].map(lambda v: v if v > 0 else 0)
    sal = df["kg_neto"].map(lambda v: -v if v < 0 else 0)
    return pd.DataFrame({
        "FECHA": df["momento"].map(lambda t: pd.to_datetime(t).strftime("%d/%m/%Y %H:%M") if not pd.isna(t) else ""),
        "#TICKET": df["ticket"].fillna(""),
        "PRODUCTO": df["producto"].fillna(""),
        "ORIGEN": df["origen"].fillna(""),
        "DESTINO": df["destino"].fillna(""),
        "ENTRADA KG": ent.map(_fmt_kg),
        "SALIDA KG": sal.map(_fmt_kg),
        "LITROS": df["litros"].map(_fmt_kg),
        "REF.": df["referencia"].fillna(""),
        "QUIÉN": df["usuario"].fillna(""),
    })


def _resumen_producto(df):
    ent = df["kg_neto"].map(lambda v: v if v > 0 else 0)
    sal = df["kg_neto"].map(lambda v: -v if v < 0 else 0)
    r = pd.DataFrame({"PRODUCTO": df["producto"].fillna("—"), "GRUPO": df["grupo"].fillna(""),
                      "ENTRADAS KG": ent, "SALIDAS KG": sal, "NETO KG": df["kg_neto"].fillna(0)})
    g = r.groupby("PRODUCTO", as_index=False).agg({
        "GRUPO": lambda s: " · ".join(sorted({x for x in s if x})),
        "ENTRADAS KG": "sum", "SALIDAS KG": "sum", "NETO KG": "sum"})
    g = g.sort_values("NETO KG", ascending=False)
    for c in ("ENTRADAS KG", "SALIDAS KG", "NETO KG"):
        g[c] = g[c].map(lambda x: f"{float(x):,.0f}")
    return g


def _ir_stock_clasico(ctx):
    def _cb():
        st.session_state.section = "STOCK"
    return _cb


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def _movimientos(ctx, sec):
    cod = sec["codigo"]
    c1, c2, c3, c4 = st.columns([1.6, 1.2, 1.6, 0.5])
    rango = c1.radio("Período", list(_RANGOS), index=1, horizontal=True,
                     key=f"nav_mv_rango_{cod}", label_visibility="collapsed")
    tipo = c2.radio("Tipo", list(_TIPOS), index=0, horizontal=True,
                    key=f"nav_mv_tipo_{cod}", label_visibility="collapsed")
    busca = c3.text_input("Buscar", key=f"nav_mv_q_{cod}", placeholder="ticket, cliente, tanque, producto…",
                          label_visibility="collapsed")
    if c4.button("↻", key=f"nav_mv_ref_{cod}", use_container_width=True, help="Releer ahora"):
        invalidar(); _rerun_fragment()

    df = _movs(ctx["conn_factory"], cod, _RANGOS[rango])
    if df is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    ajustes_n = int(df["es_ajuste_sistema"].sum())
    g1, g2 = st.columns([2.2, 1.4])
    keys = [g for g, _ in GRUPOS]
    grupo = g1.radio("Grupo", keys, horizontal=True, format_func=lambda g: _GRUPO_LBL.get(g, g),
                     key=f"nav_mv_grupo_{cod}", label_visibility="collapsed")
    ver_aj = g2.toggle(f"Ver ajustes de medición ({ajustes_n})", value=False, key=f"nav_mv_aj_{cod}",
                       help="Reconciliación automática contra los sensores: no es mercadería que entró o salió.")

    v = df if ver_aj else df[~df["es_ajuste_sistema"]]
    if grupo != "TODOS":
        v = v[v["grupo"] == grupo]
    if tipo and _TIPOS[tipo]:
        v = v[v["tipo"] == _TIPOS[tipo]]
    if busca.strip():
        q = busca.strip().lower()
        cols = ["ticket", "tickets_detalle", "contraparte", "tanque", "producto", "origen", "destino", "referencia"]
        m = pd.Series(False, index=v.index)
        for c in cols:
            m = m | v[c].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        v = v[m]

    ing = float(v["kg_neto"].map(lambda x: x if x > 0 else 0).sum())
    egr = float(v["kg_neto"].map(lambda x: -x if x < 0 else 0).sum())
    k1 = _kpi("Entradas", f"{_n(ing/1000)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"{int((v['kg_neto'] > 0).sum())} movimientos · {rango.lower()}", "")
    k2 = _kpi("Salidas", f"{_n(egr/1000)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"{int((v['kg_neto'] < 0).sum())} movimientos · {rango.lower()}", "")
    k3 = _kpi("Neto del período", f"{(ing-egr)/1000:+,.1f}<span style='font-size:1rem;font-weight:700;'> TN</span>",
              f"sólo {sec['nombre_ui']}", "warn" if ing - egr < 0 else "ok")
    k4 = _kpi("Movimientos", str(len(v)),
              (f"{ajustes_n} ajustes de medición escondidos" if (ajustes_n and not ver_aj) else "en la tabla de abajo"), "")
    st.markdown(f'<div class="kpi-grid">{k1}{k2}{k3}{k4}</div>', unsafe_allow_html=True)

    if v.empty:
        st.info(f"Sin movimientos de {sec['nombre_ui']} con esos filtros.")
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
                       file_name=f"stock_{cod.lower()}_{date.today():%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"nav_mv_xls_{cod}")
    st.caption("Cada fila es un movimiento de stock de este sector y de ningún otro. El ticket es el de portería; "
               "en un despacho se muestra el primero y cuántos más lo acompañan (la lista completa está en el buscador "
               "y en el Excel). ORIGEN → DESTINO: tanque, proveedor de portería, OP de producción o despacho con su cliente.")


def render_stock(ctx, sec):
    puede = ctx["puede_seccion"]
    c1, c2 = st.columns([3, 1.2])
    c1.markdown(f"<div class='section-title' style='margin:6px 0'>📦 Stock · {sec['nombre_ui']} · movimientos</div>",
                unsafe_allow_html=True)
    if puede("STOCK"):
        c2.button("📋 Stock clásico (físico por tanque)", key="nav_cc_clasico", use_container_width=True,
                  on_click=_ir_stock_clasico(ctx))
    _movimientos(ctx, sec)
