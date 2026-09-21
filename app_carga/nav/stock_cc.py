# -*- coding: utf-8 -*-
"""Stock del sector: el modelo de stock de dirección, sin nada más.

Una cuenta por producto, con su código oficial (V-AFE-S-A, V-AG-C…), y por cada cuenta una
cuenta corriente: saldo inicial, ingresos, egresos y saldo corriendo fila por fila. Arriba, el
saldo consolidado de todas las cuentas a la fecha. El Q sale del libro de movimientos de la
planta (produccion.v_stock_cuenta_sector), que atribuye cada movimiento a un sector por el
tanque: cada sector ve lo suyo y nada más.

El saldo inicial es la medición física de los tanques del sector el primer día hábil del mes
(produccion.fact_stock_saldo_inicial); la cuenta corriente corre desde ahí.

Tres filtros y ninguno más: producto, fecha y número de ticket. Todo en TN. Sin leyendas.
(Rediseño pedido por dirección el 21/09/2026: "hiper simplista, robusta, con códigos
oficiales, sin texto de más, ni filtros de más".)
"""

import io
from datetime import date

import pandas as pd
import streamlit as st

import cache_rev as _cache_rev   # caché que una escritura invalida (no sólo el TTL)

from .kpis import _FRAGMENT, _TTL, _kpi, _n, _rerun_fragment

_UM = {"TN": ("kg_neto", 1000.0), "KL": ("litros_neto", 1000.0)}   # lo usa stock_consolidado
_COLS = ("id_mov, momento, fecha, cuenta, tipo, origen, destino, ticket, tickets_detalle, "
         "kg_neto, litros_neto, referencia, es_ajuste_sistema, observacion, tanque, sector, es_stock")
_TODOS = "TODOS"


# ------------------------------------------------------------------ datos
@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _movs(_cf, sector, desde, hasta):
    sql = (f"SELECT {_COLS} FROM produccion.v_stock_cuenta_sector "
           "WHERE sector = %s AND fecha BETWEEN %s AND %s ORDER BY momento, id_mov")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector, desde, hasta))
        for c in ("kg_neto", "litros_neto"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        df["es_ajuste_sistema"] = df["es_ajuste_sistema"].fillna(False).astype(bool)
        df["es_stock"] = df["es_stock"].fillna(True).astype(bool) if "es_stock" in df.columns else True
        df["cuenta"] = df["cuenta"].fillna("(sin producto)")
        return df
    except Exception:
        return None


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _saldo_inicial(_cf, sector, desde):
    """Saldo con el que arranca el período, por cuenta (produccion.fn_stock_saldo_a: el último
    corte del mes más los movimientos entre el corte y `desde`)."""
    sql = ("SELECT cuenta, kg_neto, litros_neto, base_fecha, base_fuente "
           "FROM produccion.fn_stock_saldo_a(%s, %s)")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector, desde))
        for c in ("kg_neto", "litros_neto"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        df["cuenta"] = df["cuenta"].fillna("(sin producto)")
        return df
    except Exception:
        return None


def _cerrar_corte(conectar, USR, sector, fecha):
    """Graba el saldo inicial del mes: la foto física de los tanques del sector."""
    with conectar(int(USR["id_usuario"])) as (conn, _audit):
        with conn.cursor() as cur:
            cur.execute("SELECT r_cuentas, r_tn FROM produccion.fn_stock_cerrar_saldo_inicial(%s, %s, %s)",
                        (sector, fecha, int(USR["id_usuario"])))
            return cur.fetchone()


def invalidar():
    _movs.clear(); _saldo_inicial.clear()


# ------------------------------------------------------------------ helpers
def _col(df, nombre, defecto=None):
    if nombre in df.columns:
        return df[nombre]
    return pd.Series([defecto] * len(df), index=df.index)


def _q(x, cero="—"):
    """La cantidad, con un decimal. Cero se escribe, no se deja en blanco."""
    if x is None or pd.isna(x) or abs(float(x)) < 0.05:
        return cero
    return f"{float(x):,.1f}"


def _primer_dia_habil(d):
    d = date(d.year, d.month, 1)
    while d.weekday() >= 5:
        d = d.fromordinal(d.toordinal() + 1)
    return d


def _contraparte(v):
    """ORIGEN / DESTINO en una sola columna: la contraparte del movimiento, nunca el tanque.
    En un ingreso es de dónde vino (portería · proveedor, la reacción, otro sector); en un
    egreso, a dónde fue (la ODV · cliente, el sector que lo tomó). El tanque va en TK / ACOPIO."""
    out = []
    for val, tipo, o, d in zip(v["_val"], v["tipo"].fillna(""), v["origen"].fillna(""), v["destino"].fillna("")):
        if tipo == "AJUSTE":
            out.append("AJUSTE")
        elif val > 0:
            out.append(o or "—")
        else:
            out.append(d or "—")
    return out


def _filas(v, saldo_ini, con_cuenta):
    """Las filas de la cuenta corriente. El saldo corre sobre TODAS las filas de `v`; si
    después se filtra por ticket, cada fila conserva el saldo real del libro en ese punto."""
    ing = v["_val"].map(lambda x: x if x > 0 else 0.0)
    egr = v["_val"].map(lambda x: -x if x < 0 else 0.0)
    saldo = saldo_ini + (ing - egr).cumsum()
    f = pd.DataFrame({
        "ID": v["id_mov"].map(lambda i: "" if pd.isna(i) else f"{int(i)}"),
        "FECHA": v["momento"].map(lambda t: pd.to_datetime(t).strftime("%d/%m/%Y %H:%M") if not pd.isna(t) else ""),
        "CUENTA": v["cuenta"].fillna(""),
        "ORIGEN / DESTINO": _contraparte(v),
        "TK / ACOPIO": _col(v, "tanque", "").fillna("").replace("", "—"),
        "N° TICKET": v["ticket"].fillna(""),
        "INGRESO": ing.map(lambda x: _q(x, "")),
        "EGRESO": egr.map(lambda x: _q(x, "")),
        "SALDO": saldo.map(lambda x: f"{float(x):,.1f}"),
        "COMENTARIO": [(o or r or "") for o, r in zip(v["observacion"].fillna(""), v["referencia"].fillna(""))],
    })
    return f if con_cuenta else f.drop(columns=["CUENTA"])


def _cuenta_corriente(v, saldo_ini, fecha_ini, comentario_ini="", con_cuenta=False, mascara=None):
    cols = ["ID", "FECHA"] + (["CUENTA"] if con_cuenta else []) + \
           ["ORIGEN / DESTINO", "TK / ACOPIO", "N° TICKET", "INGRESO", "EGRESO", "SALDO", "COMENTARIO"]
    filas = pd.DataFrame(columns=cols) if v.empty else _filas(v, saldo_ini, con_cuenta)
    if mascara is not None and not v.empty:
        filas = filas[mascara.values]
    cab = pd.DataFrame([{
        "ID": "", "FECHA": f"{fecha_ini:%d/%m/%Y}", "CUENTA": "", "ORIGEN / DESTINO": "SALDO INICIAL",
        "TK / ACOPIO": "", "N° TICKET": "", "INGRESO": "", "EGRESO": "",
        "SALDO": f"{float(saldo_ini):,.1f}", "COMENTARIO": comentario_ini,
    }])
    return pd.concat([cab, filas], ignore_index=True)[cols]


def _consolidado(v, ini):
    """SALDO CONSOLIDADO: una fila por cuenta, con su código oficial y el saldo a la fecha.
    Están todas las cuentas del sector (con saldo o con movimiento), en orden alfabético."""
    mov = (v.groupby("cuenta", as_index=False).agg(ING=("_ing", "sum"), EGR=("_egr", "sum"))
           if not v.empty else pd.DataFrame({"cuenta": [], "ING": [], "EGR": []}))
    base = (ini.groupby("cuenta", as_index=False).agg(INI=("_val", "sum"))
            if not ini.empty else pd.DataFrame({"cuenta": [], "INI": []}))
    g = mov.merge(base, on="cuenta", how="outer")
    for c in ("ING", "EGR", "INI"):
        g[c] = pd.to_numeric(g.get(c), errors="coerce").fillna(0.0)
    g["FIN"] = g["INI"] + g["ING"] - g["EGR"]
    g = g.sort_values("cuenta").reset_index(drop=True)
    out = pd.DataFrame({"CUENTA": g["cuenta"], "SALDO TN": g["FIN"].map(lambda x: _q(x, "0.0"))})
    tot = pd.DataFrame([{"CUENTA": "TOTAL", "SALDO TN": f"{g['FIN'].sum():,.1f}"}])
    return pd.concat([out, tot], ignore_index=True), g


def _ir_stock_clasico(ctx):
    def _cb():
        st.session_state.section = "STOCK"
    return _cb


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def _movimientos(ctx, sec):
    cod = sec["codigo"]
    cf = ctx["conn_factory"]
    hoy = date.today()
    corte = _primer_dia_habil(hoy)

    # ---- filtros: producto, fecha, ticket. Nada más. ----
    k_desde, k_hasta = f"stk_desde_{cod}", f"stk_hasta_{cod}"
    st.session_state.setdefault(k_desde, corte)
    st.session_state.setdefault(k_hasta, hoy)
    c1, c2, c3, c4 = st.columns([1.6, 1, 1, 1.2])
    desde = c2.date_input("Desde", key=k_desde, format="DD/MM/YYYY")
    hasta = c3.date_input("Hasta", key=k_hasta, format="DD/MM/YYYY")
    if hasta < desde:
        desde, hasta = hasta, desde
    ticket = c4.text_input("N° ticket", key=f"stk_tk_{cod}", placeholder="Ticket / ID")

    df = _movs(cf, cod, desde, hasta)
    ini = _saldo_inicial(cf, cod, desde)
    if df is None or ini is None:
        st.caption("Sin conexión a la base en este momento.")
        return

    col, div = _UM["TN"]
    v = df[~df["es_ajuste_sistema"] & df["es_stock"]].copy()
    if "sector" in v.columns:                       # red de seguridad: sólo este sector
        v = v[v["sector"] == cod]
    v["_val"] = v[col] / div
    v["_ing"] = v["_val"].map(lambda x: x if x > 0 else 0.0)
    v["_egr"] = v["_val"].map(lambda x: -x if x < 0 else 0.0)
    ini = ini.copy()
    ini["_val"] = ini[col] / div

    ctas = sorted(set(v["cuenta"].dropna()) | set(ini["cuenta"].dropna()))
    k_c = f"stk_cta_{cod}"
    if st.session_state.get(k_c) not in [_TODOS] + ctas:
        st.session_state[k_c] = _TODOS
    cta = c1.selectbox("Producto", [_TODOS] + ctas, key=k_c)

    if cta != _TODOS:
        v = v[v["cuenta"] == cta]
        ini = ini[ini["cuenta"] == cta]
    if v.empty and float(ini["_val"].abs().sum()) == 0:
        st.info(f"Sin movimientos de {sec['nombre_ui']} entre {desde:%d/%m/%Y} y {hasta:%d/%m/%Y}.")
        return

    # ---- indicadores ----
    s_ini = float(ini["_val"].sum())
    s_ing, s_egr = float(v["_ing"].sum()), float(v["_egr"].sum())
    s_fin = s_ini + s_ing - s_egr
    _u = "<span style='font-size:1rem;font-weight:700;'> TN</span>"
    st.markdown('<div class="kpi-grid">'
                + _kpi("SALDO INICIAL", f"{_n(s_ini,1)}{_u}", f"{desde:%d/%m/%Y}", "")
                + _kpi("INGRESOS", f"{_n(s_ing,1)}{_u}", "", "")
                + _kpi("EGRESOS", f"{_n(s_egr,1)}{_u}", "", "")
                + _kpi("SALDO", f"{_n(s_fin,1)}{_u}", f"{hasta:%d/%m/%Y}", "warn" if s_fin < 0 else "ok")
                + '</div>', unsafe_allow_html=True)

    # ---- SALDO CONSOLIDADO ----
    st.markdown(f"<div class='section-title' style='margin:10px 0 2px'>SALDO CONSOLIDADO · {hasta:%d/%m/%Y}</div>",
                unsafe_allow_html=True)
    rep, g = _consolidado(v, ini)
    st.dataframe(rep, hide_index=True, use_container_width=False, width=420,
                 height=min(520, 40 + 35 * len(rep)),
                 column_config={"CUENTA": st.column_config.TextColumn(width="medium"),
                                "SALDO TN": st.column_config.TextColumn(width="small")})

    # ---- CUENTA CORRIENTE ----
    _bf = ini["base_fecha"].dropna() if "base_fecha" in ini.columns else pd.Series([], dtype=object)
    _com_ini = (f"medición de tanques al {pd.to_datetime(_bf.iloc[0]):%d/%m/%Y}" if len(_bf)
                else "arrastre del libro (sin corte cargado)")
    titulo = f"CUENTA CORRIENTE · {cta}" if cta != _TODOS else f"CUENTA CORRIENTE · {sec['nombre_ui'].upper()}"
    st.markdown(f"<div class='section-title' style='margin:14px 0 2px'>{titulo}</div>", unsafe_allow_html=True)
    w = v.sort_values(["momento", "id_mov"])
    m = None
    if ticket.strip():
        q = ticket.strip().lower()
        m = w["id_mov"].astype(str).str.contains(q, regex=False)
        for c in ("ticket", "tickets_detalle"):
            m = m | w[c].fillna("").astype(str).str.lower().str.contains(q, regex=False)
    tabla = _cuenta_corriente(w, s_ini, desde, _com_ini, con_cuenta=(cta == _TODOS), mascara=m)
    st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(620, 40 + 35 * len(tabla)),
                 column_config={"ORIGEN / DESTINO": st.column_config.TextColumn(width="medium"),
                                "TK / ACOPIO": st.column_config.TextColumn(width="small"),
                                "COMENTARIO": st.column_config.TextColumn(width="medium")})

    # ---- acciones: Excel y corte del mes. Sin texto. ----
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        rep.to_excel(xw, index=False, sheet_name="SALDO CONSOLIDADO")
        for c in [x for x in g["cuenta"].tolist() if pd.notna(x)][:40]:
            hoja = str(c)[:28].replace("/", "-").replace("\\", "-").replace(":", "-")
            _w = v[v["cuenta"] == c].sort_values(["momento", "id_mov"])
            _si = float(ini.loc[ini["cuenta"] == c, "_val"].sum())
            _cuenta_corriente(_w, _si, desde, _com_ini).to_excel(xw, index=False, sheet_name=hoja)
    b1, b2, _ = st.columns([1.3, 1.3, 2.4])
    b1.download_button("⬇️ Excel", buf.getvalue(),
                       file_name=f"stock_{cod.lower()}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"nav_mv_xls_{cod}", use_container_width=True)
    conectar = ctx.get("conectar")
    if conectar is not None and ctx["puede_seccion"]("STOCK"):
        if b2.button(f"🔄 Recalcular saldo inicial {corte:%d/%m}", key=f"nav_mv_corte_{cod}",
                     use_container_width=True):
            try:
                row = _cerrar_corte(conectar, ctx["USR"], cod, hoy)
                invalidar()
                st.toast(f"Saldo inicial recalculado: {int(row[0])} cuenta(s), {float(row[1]):,.1f} TN.")
                _rerun_fragment()
            except Exception as e:
                st.error(f"No se pudo recalcular el saldo inicial: {e}")


def render_stock(ctx, sec):
    c1, c2 = st.columns([3, 1.2])
    c1.markdown(f"<div class='section-title' style='margin:6px 0'>📦 STOCK · {sec['nombre_ui'].upper()}</div>",
                unsafe_allow_html=True)
    if ctx["puede_seccion"]("STOCK"):
        c2.button("📋 Stock clásico (físico por tanque)", key="nav_cc_clasico", use_container_width=True,
                  on_click=_ir_stock_clasico(ctx))
    _movimientos(ctx, sec)
