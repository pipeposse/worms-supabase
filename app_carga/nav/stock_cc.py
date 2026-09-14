# -*- coding: utf-8 -*-
"""Stock de un sector: los movimientos, uno por fila, estilo origen → destino · ticket.

Pedido de dirección (14/09/2026):
  · cada sector muestra SÓLO lo suyo (el sector sale del tanque, no de un texto);
  · cada movimiento tiene su ID;
  · el período se elige por año, por semana o por fechas — nunca "últimos 30 días";
  · todo en toneladas (litros × densidad del producto), nunca kilolitros;
  · los grupos se llaman por su nombre (Materia prima / Insumos / Producto terminado)
    y el que no tiene movimientos no se muestra;
  · los movimientos se pueden ver AGRUPADOS POR REFERENCIA — en Exportación, la orden
    de venta — y al hacer click en una referencia se abre todo su desglose.

Sale de produccion.v_movimiento_sector. Dos cosas NO se muestran, por pedido de
dirección: los ajustes automáticos de medición (reconciliación con los sensores,
no es mercadería) y, en Exportación, las entradas de materia prima a los tanques
de plataforma (eso es recepción, se ve en Ingresos / Asignación AFE).
"""

import io

import pandas as pd
import streamlit as st

from . import periodo as _per
from .kpis import _FRAGMENT, _TTL, _kpi, _n, _rerun_fragment

# el código del grupo nunca se muestra: se muestra el nombre
_GRUPO_LBL = {"MP": "Materia prima", "INSUMO": "Insumos", "PT": "Producto terminado", "OTRO": "Otros"}
_TIPOS = {"Todos": None, "⬇️ Entradas": "ENTRADA", "⬆️ Salidas": "SALIDA"}

# Los tanques de plataforma son de Exportación, pero también RECIBEN materia prima
# (AFE-S, AFE-SG, AG-C que llegan por portería y se asignan a un tanque). Esa entrada
# es recepción de materia prima, no exportación: se ve en Ingresos / Asignación AFE.
_SIN_ENTRADA_MP = {"EXPORTACION"}
_GRUPOS_MP = ("MP", "INSUMO")


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


def _tabla_por_ref(df):
    """Una fila por REFERENCIA (en Exportación, la orden de venta)."""
    d = df.copy()
    d["_ref"] = d["referencia"].fillna("").astype(str).str.strip()
    d.loc[d["_ref"] == "", "_ref"] = "— sin referencia"
    d["_ent"] = d["kg_neto"].map(lambda v: v if v > 0 else 0)
    d["_sal"] = d["kg_neto"].map(lambda v: -v if v < 0 else 0)
    g = d.groupby("_ref", as_index=False).agg(
        _desde=("momento", "min"), _hasta=("momento", "max"), _n=("id_mov", "size"),
        _prods=("producto", lambda s: len({x for x in s if x})),
        _tks=("ticket", lambda s: len({str(x) for x in s if x and str(x) != "nan"})),
        _ent=("_ent", "sum"), _sal=("_sal", "sum"), _neto=("kg_neto", "sum"))
    g = g.sort_values("_hasta", ascending=False)

    def _rango(r):
        a = pd.to_datetime(r["_desde"]); b = pd.to_datetime(r["_hasta"])
        if pd.isna(a):
            return ""
        if pd.isna(b) or a.date() == b.date():
            return a.strftime("%d/%m/%Y")
        return "%s → %s" % (a.strftime("%d/%m"), b.strftime("%d/%m/%Y"))

    return pd.DataFrame({
        "REF.": g["_ref"],
        "FECHA": g.apply(_rango, axis=1),
        "MOVIM.": g["_n"].astype(int),
        "PRODUCTOS": g["_prods"].astype(int),
        "TICKETS": g["_tks"].astype(int),
        "ENTRADA TN": g["_ent"].map(_tn),
        "SALIDA TN": g["_sal"].map(_tn),
        "NETO TN": g["_neto"].map(lambda x: "" if float(x) == 0 else f"{float(x) / 1000.0:+,.1f}"),
    }).reset_index(drop=True), g["_ref"].tolist()


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

    # Los ajustes automáticos de medición (reconciliación contra los sensores) NO son
    # mercadería que entró o salió: no se muestran nunca. El stock físico real de cada
    # tanque se mira en Stock clásico.
    df = df[~df["es_ajuste_sistema"]]
    _mp_fuera = 0
    if cod in _SIN_ENTRADA_MP:
        _mask_mp = (df["tipo"] == "ENTRADA") & (df["grupo"].isin(_GRUPOS_MP))
        _mp_fuera = int(_mask_mp.sum())
        df = df[~_mask_mp]
    if df.empty:
        st.info(f"Sin movimientos de {sec['nombre_ui']} en el período elegido.")
        return

    # Los grupos salen de los datos: si el sector no movió insumos, no hay pestaña de insumos.
    reales = df
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
    _VISTAS = ["🧾 Por referencia", "📄 Uno por uno"]
    busca = f3.text_input("Buscar", key=f"nav_mv_q_{cod}", placeholder="ID, ticket, cliente, tanque, producto…",
                          label_visibility="collapsed")
    if f4.button("↻", key=f"nav_mv_ref_{cod}", use_container_width=True, help="Releer ahora"):
        invalidar(); _rerun_fragment()
    v = df
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
    k4 = _kpi("Movimientos", str(len(v)), "en la tabla de abajo", "")
    st.markdown(f'<div class="kpi-grid">{k1}{k2}{k3}{k4}</div>', unsafe_allow_html=True)

    if v.empty:
        st.info(f"Sin movimientos de {sec['nombre_ui']} en {etiqueta} con esos filtros.")
        return
    if _mp_fuera:
        st.caption(f"ℹ️ {_mp_fuera} entrada(s) de materia prima a tanques de plataforma no se "
                   f"muestran acá: son recepción de AFE/AG por portería, no exportación. "
                   f"Se ven en **Ingresos** y en **Asignación AFE**.")

    tabla = _tabla_director(v)

    # Agrupar por REF sólo tiene sentido cuando una referencia junta varios
    # movimientos: en Exportación una orden de venta son 10-14 asientos, en
    # Piletas cada camión trae su propia referencia y agrupar no agrupa nada.
    _refs_n = int(v["referencia"].fillna("").astype(str).str.strip().replace("", pd.NA).nunique())
    _agrupa = bool(_refs_n) and (len(v) / max(1, _refs_n)) >= 1.5
    _k_vista = f"nav_mv_vista_{cod}"
    if st.session_state.get(_k_vista) not in _VISTAS:
        st.session_state[_k_vista] = _VISTAS[0] if _agrupa else _VISTAS[1]
    _vista = st.radio("Ver", _VISTAS, horizontal=True, key=_k_vista, label_visibility="collapsed",
                      help="Por referencia: una fila por orden de venta (o por comprobante), con "
                           "el desglose al hacer click. Uno por uno: cada asiento del libro de stock.")

    _agrup = None
    if _vista.startswith("🧾"):
        _tg, _orden_refs = _tabla_por_ref(v)
        _agrup = _tg
        _sel_ref = None
        try:
            _ev = st.dataframe(_tg, hide_index=True, use_container_width=True,
                               height=min(620, 60 + 35 * len(_tg)), key=f"nav_mv_tabref_{cod}",
                               on_select="rerun", selection_mode="single-row")
            _rows = list(getattr(getattr(_ev, "selection", None), "rows", None) or [])
            if _rows:
                _sel_ref = str(_tg.iloc[_rows[0]]["REF."])
        except Exception:
            st.dataframe(_tg, hide_index=True, use_container_width=True,
                         height=min(620, 60 + 35 * len(_tg)))
        if _sel_ref is None and len(_tg):
            _sel_ref = st.selectbox("Referencia", _tg["REF."].tolist(), key=f"nav_mv_selref_{cod}",
                                    help="👆 También podés hacer click en una fila de la tabla.")
            st.caption("👆 Hacé click en una referencia para ver su desglose.")
        if _sel_ref:
            _r = v["referencia"].fillna("").astype(str).str.strip()
            _det = v[_r == _sel_ref] if _sel_ref != "— sin referencia" else v[_r == ""]
            _ent_d = float(_det["kg_neto"].map(lambda x: x if x > 0 else 0).sum())
            _egr_d = float(_det["kg_neto"].map(lambda x: -x if x < 0 else 0).sum())
            st.markdown(
                f"<div style='background:#f1f5f9;border-left:5px solid #0ea5e9;border-radius:10px;"
                f"padding:8px 14px;margin:10px 0 6px'>"
                f"<b style='font-size:1.05rem'>{_sel_ref}</b>"
                f"<span style='color:#475569;font-size:.85rem'> · {len(_det)} movimiento(s) · "
                f"{_det['producto'].nunique()} producto(s) · entradas {_n(_ent_d/1000)} TN · "
                f"salidas {_n(_egr_d/1000)} TN</span></div>", unsafe_allow_html=True)
            st.dataframe(_tabla_director(_det), hide_index=True, use_container_width=True,
                         height=min(520, 60 + 35 * len(_det)))
            _tkd = sorted({str(x) for x in _det["tickets_detalle"].fillna("").tolist() if x} |
                          {str(x) for x in _det["ticket"].fillna("").tolist() if x})
            if _tkd:
                st.caption("Tickets de portería: %s" % ", ".join(_tkd[:40]))
    else:
        st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(620, 60 + 35 * len(tabla)))

    with st.expander(f"Resumen por producto ({v['producto'].nunique()})", expanded=False):
        st.dataframe(_resumen_producto(v), hide_index=True, use_container_width=True)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        tabla.to_excel(xw, index=False, sheet_name="Movimientos")
        if _agrup is None:
            _agrup, _ = _tabla_por_ref(v)
        _agrup.to_excel(xw, index=False, sheet_name="Por referencia")
        _resumen_producto(v).to_excel(xw, index=False, sheet_name="Por producto")
    st.download_button("⬇️ Descargar Excel", buf.getvalue(),
                       file_name=f"stock_{cod.lower()}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"nav_mv_xls_{cod}")
    st.caption("**Por referencia**: una fila por orden de venta / comprobante, con todos sus asientos "
               "adentro (click para abrir). **Uno por uno**: cada movimiento del libro de stock con su ID. "
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
