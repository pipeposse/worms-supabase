# -*- coding: utf-8 -*-
"""Stock del sector: el modelo de stock de dirección, sin nada más.

Una cuenta por producto, con su código oficial (V-AFE-S-A, V-AG-C…), y por cada cuenta una
cuenta corriente: saldo inicial, ingresos, egresos y saldo corriendo fila por fila. Arriba, el
saldo consolidado de todas las cuentas a la fecha. El Q sale del libro de movimientos de la
planta (produccion.v_stock_cuenta_sector), que atribuye cada movimiento a un sector por el
tanque: cada sector ve lo suyo y nada más.

El saldo inicial es la medición física de los tanques del sector el primer día hábil del mes
(produccion.fact_stock_saldo_inicial); la cuenta corriente corre desde ahí.

Filtros (dirección, 23/09/2026): producto y sector (uno o varios, vacío = todos), fecha
desde/hasta con calendario, N° de ticket, y «➕ Más» con el resto. El resultado aparece al
apretar BUSCAR. Sin indicadores. Cada producto se muestra con su código oficial y el nombre
de la planilla de parámetros («V-AFE-S-A · AFE Soja»).
(Base: rediseño del 21/09/2026, "hiper simplista, robusta, con códigos oficiales".)
"""

import io
from datetime import date

import pandas as pd
import streamlit as st

import cache_rev as _cache_rev   # caché que una escritura invalida (no sólo el TTL)

from .kpis import _FRAGMENT, _TTL, _kpi, _n, _rerun_fragment

_UM = {"TN": ("kg_neto", 1000.0), "KL": ("litros_neto", 1000.0)}   # lo usa stock_consolidado
_COLS = ("id_mov, momento, fecha, cuenta, tipo, origen, destino, ticket, tickets_detalle, "
         "kg_neto, litros_neto, referencia, es_ajuste_sistema, observacion, tanque, sector, es_stock, "
         "producto_codigo, usuario")
_TODOS = "TODOS"


# ------------------------------------------------------------------ datos
@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _movs(_cf, sector, desde, hasta):
    """`sector`: un código o una tupla de códigos (para comparar sectores)."""
    _secs = list(sector) if isinstance(sector, (list, tuple)) else [sector]
    sql = (f"SELECT {_COLS} FROM produccion.v_stock_cuenta_sector "
           "WHERE sector = ANY(%s) AND fecha BETWEEN %s AND %s ORDER BY momento, id_mov")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(_secs, desde, hasta))
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


@_cache_rev.cachear(ttl=600, show_spinner=False)
def _catalogo(_cf):
    """Cuenta → código de producto, y código → nombre de la planilla de parámetros
    (dim_producto.nombre_producto). Para mostrar «V-AFE-S-A · AFE Soja»."""
    try:
        with _cf() as conn:
            c = pd.read_sql_query("SELECT DISTINCT cuenta, producto_codigo FROM produccion.v_cuenta_sector "
                                  "WHERE cuenta IS NOT NULL", conn)
            p = pd.read_sql_query("SELECT codigo_producto, nombre_producto FROM produccion.dim_producto", conn)
        return (dict(zip(c["cuenta"].astype(str), c["producto_codigo"].astype(str))),
                dict(zip(p["codigo_producto"].astype(str), p["nombre_producto"].fillna("").astype(str))))
    except Exception:
        return {}, {}


@_cache_rev.cachear(ttl=600, show_spinner=False)
def _sectores(_cf):
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT codigo, nombre_ui FROM produccion.dim_sector_nav "
                                   "WHERE COALESCE(activo,true) AND NOT COALESCE(en_construccion,false) "
                                   "ORDER BY nombre_ui", conn)
        return dict(zip(df["codigo"].astype(str), df["nombre_ui"].astype(str)))
    except Exception:
        return {}


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _cuentas_de(_cf, sectores):
    """Todas las cuentas con movimiento o saldo en esos sectores (para el desplegable)."""
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT DISTINCT cuenta FROM produccion.v_stock_cuenta_sector "
                                   "WHERE sector = ANY(%s) AND cuenta IS NOT NULL ORDER BY 1",
                                   conn, params=(list(sectores),))
        return df["cuenta"].astype(str).tolist()
    except Exception:
        return []


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _tanques_de(_cf, sectores):
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT DISTINCT tanque FROM produccion.v_stock_cuenta_sector "
                                   "WHERE sector = ANY(%s) AND tanque IS NOT NULL ORDER BY 1",
                                   conn, params=(list(sectores),))
        return df["tanque"].astype(str).tolist()
    except Exception:
        return []


def invalidar():
    _movs.clear(); _saldo_inicial.clear(); _cuentas_de.clear(); _tanques_de.clear()


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
        "COMENTARIOS": [(o or r or "") for o, r in zip(v["observacion"].fillna(""), v["referencia"].fillna(""))],
    })
    return f if con_cuenta else f.drop(columns=["CUENTA"])


def _cuenta_corriente(v, saldo_ini, fecha_ini, comentario_ini="", con_cuenta=False, mascara=None):
    cols = ["ID", "FECHA"] + (["CUENTA"] if con_cuenta else []) + \
           ["ORIGEN / DESTINO", "TK / ACOPIO", "N° TICKET", "INGRESO", "EGRESO", "SALDO", "COMENTARIOS"]
    filas = pd.DataFrame(columns=cols) if v.empty else _filas(v, saldo_ini, con_cuenta)
    if mascara is not None and not v.empty:
        filas = filas[mascara.values]
    cab = pd.DataFrame([{
        "ID": "", "FECHA": f"{fecha_ini:%d/%m/%Y}", "CUENTA": "", "ORIGEN / DESTINO": "SALDO INICIAL",
        "TK / ACOPIO": "", "N° TICKET": "", "INGRESO": "", "EGRESO": "",
        "SALDO": f"{float(saldo_ini):,.1f}", "COMENTARIOS": comentario_ini,
    }])
    return pd.concat([cab, filas], ignore_index=True)[cols]


def _sin_tz(serie):
    t = pd.to_datetime(serie, utc=True, errors="coerce")
    return t.dt.tz_convert("America/Argentina/Buenos_Aires").dt.tz_localize(None).values


def _consolidado(v, ini, um, nombre_de):
    """SALDO CONSOLIDADO POR PRODUCTO (dirección, 23/09): el libro de todos los productos
    elegidos, en orden de fecha, con el saldo corriendo por producto.
    FECHA · PRODUCTO · ORIGEN / DESTINO · N° TICKET · UM · INGRESO · EGRESO · SALDO · COMENTARIO."""
    cols = ["FECHA", "PRODUCTO", "ORIGEN / DESTINO", "N° TICKET", "UM", "INGRESO", "EGRESO", "SALDO", "COMENTARIO"]
    partes = []
    for c in sorted(set(v["cuenta"].dropna()) | set(ini["cuenta"].dropna())):
        w = v[v["cuenta"] == c].sort_values(["momento", "id_mov"])
        s0 = float(ini.loc[ini["cuenta"] == c, "_val"].sum())
        if w.empty and abs(s0) < 0.05:
            continue
        partes.append(pd.DataFrame([{"_t": pd.Timestamp.min, "_c": c, "FECHA": "SALDO INICIAL",
                                     "PRODUCTO": nombre_de(c), "ORIGEN / DESTINO": "", "N° TICKET": "",
                                     "UM": um, "INGRESO": "", "EGRESO": "", "SALDO": f"{s0:,.1f}",
                                     "COMENTARIO": ""}]))
        if w.empty:
            continue
        ing = w["_val"].map(lambda x: x if x > 0 else 0.0)
        egr = w["_val"].map(lambda x: -x if x < 0 else 0.0)
        saldo = s0 + (ing - egr).cumsum()
        partes.append(pd.DataFrame({
            "_t": _sin_tz(w["momento"]),
            "_c": c,
            "FECHA": w["momento"].map(lambda t: pd.to_datetime(t).strftime("%d/%m/%Y %H:%M") if not pd.isna(t) else "").values,
            "PRODUCTO": nombre_de(c),
            "ORIGEN / DESTINO": _contraparte(w),
            "N° TICKET": w["ticket"].fillna("").values,
            "UM": um,
            "INGRESO": ing.map(lambda x: _q(x, "")).values,
            "EGRESO": egr.map(lambda x: _q(x, "")).values,
            "SALDO": saldo.map(lambda x: f"{float(x):,.1f}").values,
            "COMENTARIO": [(o or r or "") for o, r in zip(w["observacion"].fillna(""), w["referencia"].fillna(""))],
        }))
    if not partes:
        return pd.DataFrame(columns=cols)
    out = pd.concat(partes, ignore_index=True).sort_values(["_t", "_c"], kind="stable")
    return out[cols].reset_index(drop=True)


def _ir_stock_clasico(ctx):
    def _cb():
        st.session_state.section = "STOCK"
    return _cb


# ------------------------------------------------------------------ pantalla
def _cat_de(cf):
    """La barra de filtros compartida (filtros_stock) lee con cat(sql, params)."""
    def _cat(sql, params=None):
        with cf() as conn:
            return pd.read_sql_query(sql, conn, params=params)
    return _cat


@_FRAGMENT
def _movimientos(ctx, sec):
    import filtros_stock as _fs
    cod = sec["codigo"]
    cf = ctx["conn_factory"]
    hoy = date.today()
    corte = _primer_dia_habil(hoy)
    key = f"stkcc_{cod}"

    secs_nav = _sectores(cf)
    cta_prod, nom_prod = _catalogo(cf)

    def nombre_de(c):
        """«V-AFE-S-A · AFE Soja»: código oficial + nombre de la planilla de parámetros."""
        n = nom_prod.get(cta_prod.get(str(c), ""), "")
        return f"{c} · {n}" if n else str(c)

    # Sector: arranca en el de la pantalla; se pueden sumar otros para comparar.
    st.session_state.setdefault(f"{key}_sec", [cod])
    st.session_state.setdefault(f"{key}_desde", corte)
    st.session_state.setdefault(f"{key}_hasta", hoy)
    _secs_sel = tuple(st.session_state.get(f"{key}_sec") or [cod])
    _ctas = _cuentas_de(cf, _secs_sel)
    _etq = {c: nombre_de(c) for c in _ctas}
    _etq.update(secs_nav)

    def _mas():
        out = {}
        out["Unidad"] = st.radio("Unidad", list(_UM), horizontal=True, key=f"{key}_um")
        out["Tipo"] = st.selectbox("Tipo de movimiento", ["(todos)", "Ingresos", "Egresos"], key=f"{key}_tipo")
        out["Tanque"] = st.selectbox("TK / Acopio", ["(todos)"] + _tanques_de(cf, _secs_sel), key=f"{key}_tq")
        out["Origen/Destino"] = st.text_input("Origen / destino contiene", key=f"{key}_od",
                                              placeholder="proveedor, cliente, ODV, reactor, sector…")
        out["Usuario"] = st.text_input("Usuario", key=f"{key}_usr", placeholder="quien cargó el movimiento")
        out["Ajustes"] = st.checkbox("Incluir ajustes automáticos de medición", key=f"{key}_aj", value=False)
        return out

    f, apretado = _fs.barra(_cat_de(cf), key=key, titulo=None,
                            campos=("prod", "sec", "fecha", "tk"),
                            catalogos={"prod": _ctas, "sec": list(secs_nav)},
                            multi=True, extras_fn=_mas, buscar=True, etiquetas=_etq)

    k_ap = f"{key}_aplicado"
    if apretado:
        st.session_state[k_ap] = f
    fa = st.session_state.get(k_ap)
    if not fa:
        st.info("Elegí los filtros y apretá **🔍 Buscar**.")
        return

    desde = fa["desde"] or corte
    hasta = fa["hasta"] or hoy
    if hasta < desde:
        desde, hasta = hasta, desde
    secs = list(fa["sec"] or [cod])
    prop = fa.get("propios") or {}
    um = prop.get("Unidad") or "TN"
    col, div = _UM[um]

    df = _movs(cf, tuple(secs), desde, hasta)
    inis = [_saldo_inicial(cf, s_, desde) for s_ in secs]
    if df is None or any(x is None for x in inis):
        st.caption("Sin conexión a la base en este momento.")
        return
    ini = pd.concat(inis, ignore_index=True) if inis else pd.DataFrame(columns=["cuenta", "kg_neto", "litros_neto"])

    v = df[df["es_stock"]].copy()
    if not prop.get("Ajustes"):
        v = v[~v["es_ajuste_sistema"]]
    v = v[v["sector"].isin(secs)] if "sector" in v.columns else v   # red de seguridad
    v["_val"] = v[col] / div
    ini = ini.copy()
    ini["_val"] = pd.to_numeric(ini[col], errors="coerce").fillna(0.0) / div

    # ---- filtros ----
    if fa["prod"]:
        v = v[v["cuenta"].isin(fa["prod"])]
        ini = ini[ini["cuenta"].isin(fa["prod"])]
    if prop.get("Tipo") == "Ingresos":
        v = v[v["_val"] > 0]
    elif prop.get("Tipo") == "Egresos":
        v = v[v["_val"] < 0]
    if prop.get("Tanque") not in (None, "", "(todos)"):
        v = v[_col(v, "tanque", "").fillna("").astype(str) == prop["Tanque"]]
    if (prop.get("Origen/Destino") or "").strip():
        q = prop["Origen/Destino"].strip().lower()
        v = v[pd.Series(_contraparte(v), index=v.index).str.lower().str.contains(q, regex=False)]
    if (prop.get("Usuario") or "").strip():
        q = prop["Usuario"].strip().lower()
        v = v[_col(v, "usuario", "").fillna("").astype(str).str.lower().str.contains(q, regex=False)]
    # el ticket filtra las FILAS pero el saldo sigue siendo el real del libro
    m_tk = None
    if fa["tk"]:
        q = fa["tk"].strip().lower()
        m_tk = v["id_mov"].astype(str).str.contains(q, regex=False)
        for c in ("ticket", "tickets_detalle", "referencia"):
            m_tk = m_tk | v[c].fillna("").astype(str).str.lower().str.contains(q, regex=False)

    _secs_txt = ", ".join(secs_nav.get(x, x) for x in secs)
    if v.empty and float(ini["_val"].abs().sum()) == 0:
        st.info(f"Sin movimientos para estos filtros · {_secs_txt} · {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}.")
        return

    # ---- SALDO CONSOLIDADO POR PRODUCTO ----
    st.markdown(f"<div class='section-title' style='margin:10px 0 2px'>SALDO CONSOLIDADO POR PRODUCTO · "
                f"{_secs_txt} · {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}</div>", unsafe_allow_html=True)
    cons = _consolidado(v, ini, um, nombre_de)
    if m_tk is not None:
        _keep = set(v.loc[m_tk, "ticket"].fillna("").astype(str)) | set(v.loc[m_tk, "referencia"].fillna("").astype(str))
        cons = cons[(cons["FECHA"] == "SALDO INICIAL") | cons["N° TICKET"].astype(str).isin(_keep)
                    | cons["COMENTARIO"].astype(str).isin(_keep)]
    st.dataframe(cons, hide_index=True, use_container_width=True, height=min(560, 40 + 35 * len(cons)),
                 column_config={"PRODUCTO": st.column_config.TextColumn(width="medium"),
                                "ORIGEN / DESTINO": st.column_config.TextColumn(width="medium"),
                                "COMENTARIO": st.column_config.TextColumn(width="medium"),
                                "UM": st.column_config.TextColumn(width="small")})

    # ---- CUENTA CORRIENTE DEL PRODUCTO ----
    ctas = sorted(set(v["cuenta"].dropna()) | set(ini.loc[ini["_val"].abs() >= 0.05, "cuenta"].dropna()))
    if not ctas:
        return
    st.markdown("<div class='section-title' style='margin:14px 0 2px'>CUENTA CORRIENTE DEL PRODUCTO</div>",
                unsafe_allow_html=True)
    k_c = f"{key}_cta"
    if st.session_state.get(k_c) not in ctas:
        st.session_state[k_c] = ctas[0]
    cta = st.selectbox("Producto", ctas, key=k_c, label_visibility="collapsed", format_func=nombre_de)
    w = v[v["cuenta"] == cta].sort_values(["momento", "id_mov"])
    s_ini_cta = float(ini.loc[ini["cuenta"] == cta, "_val"].sum())
    _bf = ini["base_fecha"].dropna() if "base_fecha" in ini.columns else pd.Series([], dtype=object)
    _com_ini = (f"medición de tanques al {pd.to_datetime(_bf.iloc[0]):%d/%m/%Y}" if len(_bf)
                else "arrastre del libro (sin corte cargado)")
    mw = m_tk.loc[w.index] if m_tk is not None else None
    tabla = _cuenta_corriente(w, s_ini_cta, desde, _com_ini, con_cuenta=False, mascara=mw)
    st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(620, 40 + 35 * len(tabla)),
                 column_config={"ORIGEN / DESTINO": st.column_config.TextColumn(width="medium"),
                                "TK / ACOPIO": st.column_config.TextColumn(width="small"),
                                "COMENTARIOS": st.column_config.TextColumn(width="medium")})

    # ---- Excel y corte del mes ----
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        cons.to_excel(xw, index=False, sheet_name="SALDO CONSOLIDADO")
        for c in ctas[:40]:
            hoja = str(c)[:28].replace("/", "-").replace("\\", "-").replace(":", "-")
            _w = v[v["cuenta"] == c].sort_values(["momento", "id_mov"])
            _si = float(ini.loc[ini["cuenta"] == c, "_val"].sum())
            _cuenta_corriente(_w, _si, desde, _com_ini).to_excel(xw, index=False, sheet_name=hoja)
    b1, b2, _ = st.columns([1.3, 1.3, 2.4])
    b1.download_button("⬇️ Excel", buf.getvalue(),
                       file_name=f"stock_{'_'.join(secs).lower()}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"nav_mv_xls_{cod}", use_container_width=True)
    conectar = ctx.get("conectar")
    if conectar is not None and ctx["puede_seccion"]("STOCK") and secs == [cod]:
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
