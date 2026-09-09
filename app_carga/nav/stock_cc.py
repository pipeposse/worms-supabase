# -*- coding: utf-8 -*-
"""Cuenta corriente de stock (Fase 5) — vista STOCK de un sector.

Tabla STOCK del Excel de dirección: Materia Prima / Insumos / Producto Terminado,
un desplegable de producto y, por producto, la cuenta corriente

    FECHA · #TICKET · CC · CLIENTE/PROVEEDOR · ESTADO · SECTOR · INGRESO KG · EGRESO KG · SALDO

Nadie la tipea: sale de produccion.v_cuenta_corriente_producto (ledger de stock
cruzado con portería y con el sector del tanque, más el ledger simple de los
sectores sin tanques). El saldo es el acumulado del producto en toda la planta;
"Sólo este sector" filtra las filas, no el saldo.
"""

import io
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from .kpis import _FRAGMENT, _TTL, _kpi, _n, _rerun_fragment

GRUPOS = [("MP", "🛢️ Materia Prima"), ("INSUMO", "⚗️ Insumos"), ("PT", "📦 Producto Terminado")]
_GRUPO_LBL = dict(GRUPOS)
_RANGOS = {"30 días": 30, "90 días": 90, "12 meses": 365, "Todo": None}


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _productos(_cf):
    """(producto, grupo, ultimo_mov, saldo_actual) por producto; un producto puede estar en más de un grupo."""
    sql = ("SELECT producto, grupo, max(momento) AS ultimo, count(*) AS n "
           "FROM produccion.v_cuenta_corriente_producto GROUP BY producto, grupo")
    try:
        with _cf() as conn:
            return pd.read_sql_query(sql, conn)
    except Exception:
        return None


@st.cache_data(ttl=_TTL, show_spinner=False)
def _cuenta(_cf, producto, dias):
    sql = ("SELECT momento, fecha, grupo, ticket, op, cc, contraparte, estado, tipo, origen, sector, tanque_label, "
           "ingreso_kg, egreso_kg, kg_neto, saldo_kg, observacion, ref "
           "FROM produccion.v_cuenta_corriente_producto WHERE producto = %s")
    params = [producto]
    if dias:
        sql += " AND fecha >= %s"
        params.append(date.today() - timedelta(days=int(dias)))
    sql += " ORDER BY momento DESC, ref DESC"
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=tuple(params))
        for c in ("ingreso_kg", "egreso_kg", "kg_neto", "saldo_kg"):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
        return df
    except Exception:
        return None


def invalidar():
    _productos.clear(); _cuenta.clear()


# ------------------------------------------------------------------ helpers
def _filtro_sector(df, sec):
    """Filas del producto que pasaron por este sector: por nombre (ledger simple) o por el
    patrón de sectores de tanque del sector de gestión (dim_sector_nav.patron_tanques)."""
    s = df["sector"].fillna("")
    m = s == sec.get("nombre_ui")
    pat = sec.get("patron_tanques")
    if pat:
        try:
            m = m | s.str.match(pat)
        except Exception:
            pass
    return df[m]


def _fmt_kg(x):
    return "" if x is None or pd.isna(x) or float(x) == 0 else f"{float(x):,.0f}"


def _tabla_director(df):
    return pd.DataFrame({
        "FECHA": df["momento"].map(lambda t: pd.to_datetime(t).strftime("%d/%m/%Y %H:%M") if not pd.isna(t) else ""),
        "#TICKET": df["ticket"].fillna(""),
        "CC": df["cc"].fillna(""),
        "CLIENTE / PROVEEDOR": df["contraparte"].fillna(""),
        "ESTADO": df["estado"].fillna("") + " · " + df["tipo"].fillna(""),
        "SECTOR": df["sector"].fillna("") + df["tanque_label"].map(lambda t: f" · {t}" if isinstance(t, str) and t else ""),
        "INGRESO KG": df["ingreso_kg"].map(_fmt_kg),
        "EGRESO KG": df["egreso_kg"].map(_fmt_kg),
        "SALDO": df["saldo_kg"].map(lambda x: "" if pd.isna(x) else f"{float(x):,.0f}"),
        "OBS.": df["observacion"].fillna(""),
    })


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def _cuenta_corriente(ctx, sec, grupo, producto):
    cf = ctx["conn_factory"]
    c1, c2, c3 = st.columns([1.4, 1.4, 0.6])
    rango = c1.radio("Período", list(_RANGOS), index=1, horizontal=True, key=f"nav_cc_rango_{producto}",
                     label_visibility="collapsed")
    solo = c2.toggle(f"Sólo {sec['nombre_ui']}", value=bool(sec.get("stock_simple")), key=f"nav_cc_solo_{producto}",
                     help="El saldo es de toda la planta; el filtro sólo esconde movimientos de otros sectores.")
    if c3.button("↻", key=f"nav_cc_ref_{producto}", use_container_width=True, help="Releer ahora"):
        invalidar(); _rerun_fragment()

    df = _cuenta(cf, producto, _RANGOS[rango])
    if df is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    if df.empty:
        st.info("Sin movimientos ejecutados de este producto en el período.")
        return
    saldo = float(df.iloc[0]["saldo_kg"] or 0)      # el más reciente (orden DESC)
    v = _filtro_sector(df, sec) if solo else df
    ing, egr = float(v["ingreso_kg"].sum()), float(v["egreso_kg"].sum())
    k1 = _kpi("Saldo actual", f"{_n(saldo)}<span style='font-size:1rem;font-weight:700;'> kg</span>",
              f"{producto} · toda la planta · al {pd.to_datetime(df.iloc[0]['momento']).strftime('%d/%m %H:%M')}",
              "bad" if saldo < 0 else "ok")
    k2 = _kpi("Ingresos", f"{_n(ing)}<span style='font-size:1rem;font-weight:700;'> kg</span>",
              f"{int((v['ingreso_kg'] > 0).sum())} movimientos · {rango}", "")
    k3 = _kpi("Egresos", f"{_n(egr)}<span style='font-size:1rem;font-weight:700;'> kg</span>",
              f"{int((v['egreso_kg'] > 0).sum())} movimientos · {rango}", "")
    k4 = _kpi("Neto del período", f"{ing - egr:+,.0f}<span style='font-size:1rem;font-weight:700;'> kg</span>",
              ("sólo este sector" if solo else "toda la planta"), "warn" if ing - egr < 0 else "")
    st.markdown(f'<div class="kpi-grid">{k1}{k2}{k3}{k4}</div>', unsafe_allow_html=True)
    if saldo < 0:
        st.warning("Saldo negativo: hay consumos registrados sin las entradas correspondientes (compras / descargas "
                   "no cargadas en el ledger). No es un error de la vista: falta cargar movimientos.")
    if solo and v.empty:
        st.info(f"Este producto no tiene movimientos en {sec['nombre_ui']} en el período; sacá el filtro para ver toda la planta.")
        return
    tabla = _tabla_director(v)
    st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(560, 60 + 35 * len(tabla)))
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        tabla.to_excel(xw, index=False, sheet_name=str(producto)[:30])
    st.download_button("⬇️ Descargar Excel", buf.getvalue(),
                       file_name=f"cc_{str(producto).replace(' ', '_')}_{date.today():%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"nav_cc_xls_{producto}")
    st.caption("CC y cliente/proveedor vienen del ticket de portería; los movimientos internos (decantación, consumo de OP, "
               "ledger de sector) no tienen ticket de balanza y muestran la OP o el remito. "
               "SALDO = acumulado del producto en toda la planta hasta ese movimiento.")


def _ir_stock_clasico(ctx):
    def _cb():
        st.session_state.section = "STOCK"
    return _cb


def render_stock(ctx, sec):
    cf, puede = ctx["conn_factory"], ctx["puede_seccion"]
    c1, c2 = st.columns([3, 1.2])
    c1.markdown(f"<div class='section-title' style='margin:6px 0'>📦 Stock · {sec['nombre_ui']} · cuenta corriente por producto</div>",
                unsafe_allow_html=True)
    if puede("STOCK"):
        c2.button("📋 Stock clásico (movimientos, físico)", key="nav_cc_clasico", use_container_width=True,
                  on_click=_ir_stock_clasico(ctx))

    prods = _productos(cf)
    if prods is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    # El valor elegido se recuerda en session_state (nav_cc_grupo / nav_cc_prod_<grupo>) y se
    # inyecta ANTES de crear el widget: pasarlo como index= cambia la identidad del widget en
    # cada rerun y Streamlit descarta la selección (pitfall clásico).
    keys = [g for g, _ in GRUPOS]
    if "nav_cc_grupo_rd" not in st.session_state:
        st.session_state["nav_cc_grupo_rd"] = st.session_state.get("nav_cc_grupo", "MP")
    grupo = st.radio("Grupo", keys, horizontal=True, format_func=lambda g: _GRUPO_LBL.get(g, g),
                     key="nav_cc_grupo_rd", label_visibility="collapsed")
    st.session_state["nav_cc_grupo"] = grupo
    pg = prods[prods["grupo"] == grupo].sort_values(["ultimo"], ascending=False) if not prods.empty else prods
    opciones = pg["producto"].tolist()
    if not opciones:
        st.info(f"Todavía no hay movimientos ejecutados de {_GRUPO_LBL[grupo]}.")
        return
    # Preselección: lo que ya venía elegido si sigue en el grupo; si no, el de movimiento más reciente.
    wk, mk = f"nav_cc_prod_{grupo}", f"nav_cc_prod_mem_{grupo}"
    if wk not in st.session_state:
        st.session_state[wk] = st.session_state.get(mk) if st.session_state.get(mk) in opciones else opciones[0]
    elif st.session_state[wk] not in opciones:
        st.session_state[wk] = opciones[0]
    producto = st.selectbox("Producto", opciones, key=wk,
                            format_func=lambda p: f"{p}  ·  {int(pg.loc[pg['producto'] == p, 'n'].iloc[0])} mov.")
    st.session_state[mk] = producto
    _cuenta_corriente(ctx, sec, grupo, producto)
