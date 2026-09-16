# -*- coding: utf-8 -*-
"""Stock consolidado de toda la planta — pantalla de dirección.

Cada sector tiene su cuenta corriente y ve sólo lo suyo: ésa es la regla y no se toca. Pero
dirección necesita el número de la empresa entera, y necesita que no se le escape nada. Esta
pantalla suma los cuatro sectores que tienen tanques (Exportación, Reactores, Piletas y Bachas)
con exactamente la misma lógica: saldo inicial del primer día hábil tomado de la medición física,
ingresos, egresos y saldo, producto por producto.

Tres cosas que esta pantalla NO esconde, porque son justamente por donde se escapa el stock:

  · Lo que no pasa por ningún tanque. Hay consumos de producción cargados desde planificación
    sin tanque asignado: se consumen de verdad pero no descuentan de ningún lado. Se muestran
    aparte y no se mezclan con el libro, porque parte de esa mercadería ya se descontó por otro
    movimiento y sumarla dos veces sería peor que no sumarla.
  · Lo que falta asentar. Un saldo inicial negativo significa que el libro registró más entradas
    de las que los tanques pueden explicar: mercadería que entró pesada y se movió a otro sector
    sin que nadie cargara la salida.
  · Lo interno contra lo externo. En el consolidado un traspaso entre sectores entra y sale, así
    que se netea solo; lo que le importa a dirección es cuánto entró de afuera por portería y
    cuánto salió de la planta por una ODV. Los dos números van separados.

Unidad: TN por defecto (litros × densidad del producto), con opción de verlo en KL.
"""

import io

import pandas as pd
import streamlit as st

from . import periodo as _per
from .kpis import _FRAGMENT, _TTL, _kpi, _n, _rerun_fragment
from .stock_cc import _UM, _q

_COLS = ("id_mov, momento, fecha, sector, sector_nombre, cuenta, cuenta_nombre, calidad, "
         "corriente_nombre, producto, producto_codigo, grupo, tipo, origen, destino, ticket, "
         "contraparte, kg_neto, litros_neto, referencia, observacion, tanque, es_ajuste_sistema")


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _movs(_cf, desde, hasta):
    """Todos los movimientos de stock de los sectores con tanque, en una sola consulta."""
    sql = (f"SELECT {_COLS} FROM produccion.v_stock_cuenta_sector v "
           "WHERE v.fecha BETWEEN %s AND %s AND v.es_stock "
           "AND v.sector IN (SELECT codigo FROM produccion.dim_sector_nav "
           "                  WHERE activo AND patron_tanques IS NOT NULL) "
           "ORDER BY v.momento, v.id_mov")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(desde, hasta))
        for c in ("kg_neto", "litros_neto"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        df["es_ajuste_sistema"] = df["es_ajuste_sistema"].fillna(False).astype(bool)
        df["cuenta"] = df["cuenta"].fillna("(sin producto)")
        return df
    except Exception:
        return None


@st.cache_data(ttl=_TTL, show_spinner=False)
def _saldo_inicial(_cf, desde):
    sql = ("SELECT sector, sector_nombre, cuenta, cuenta_nombre, calidad, corriente_nombre, "
           "kg_neto, litros_neto, base_fecha, base_fuente "
           "FROM produccion.fn_stock_saldo_todos(%s)")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(desde,))
        for c in ("kg_neto", "litros_neto"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        df["cuenta"] = df["cuenta"].fillna("(sin producto)")
        return df
    except Exception:
        return None


@st.cache_data(ttl=_TTL, show_spinner=False)
def _medido(_cf):
    """Lo que hoy miden los tanques, por sector y por producto."""
    sql = ("SELECT sector, cuenta, tanques, tanques_con_producto, tanques_con_producto_txt, tn, kl "
           "FROM produccion.v_stock_medido_cuenta")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn)
        for c in ("tn", "kl"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        return df
    except Exception:
        return pd.DataFrame(columns=["sector", "cuenta", "tanques", "tanques_con_producto",
                                     "tanques_con_producto_txt", "tn", "kl"])


@st.cache_data(ttl=_TTL, show_spinner=False)
def _sin_tanque(_cf, desde, hasta):
    """Lo que se consume o se produce sin pasar por ningún tanque: no descuenta de nada."""
    sql = ("SELECT sector, sector_nombre, id_mov, fecha, producto, producto_codigo, grupo, tipo, "
           "ticket, kg_neto, litros_neto, fuente_dato, op, observacion "
           "FROM produccion.v_stock_sin_tanque WHERE fecha BETWEEN %s AND %s ORDER BY fecha DESC")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(desde, hasta))
        for c in ("kg_neto", "litros_neto"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=_TTL, show_spinner=False)
def _cuentas(_cf):
    sql = ("SELECT sector, cuenta, descripcion, rol, del_sector, producto_codigo "
           "FROM produccion.v_cuenta_sector")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn)
        df["descripcion"] = df["descripcion"].fillna("")
        return df
    except Exception:
        return pd.DataFrame(columns=["sector", "cuenta", "descripcion", "rol", "del_sector",
                                     "producto_codigo"])


def invalidar():
    _movs.clear(); _saldo_inicial.clear(); _medido.clear(); _sin_tanque.clear(); _cuentas.clear()


# ------------------------------------------------------------------ armado
def _es_externo(origen):
    """Un ingreso es de afuera cuando vino pesado por portería; el resto es movimiento interno."""
    return str(origen or "").startswith("Portería")


def _por(v, ini, med, um, clave):
    """Saldo inicial, ingresos, egresos y saldo final agrupados por lo que se pida
    (sector, cuenta, o los dos), con lo que miden los tanques al lado."""
    mov = (v.groupby(clave, dropna=False, as_index=False)
           .agg(ING=("_ing", "sum"), EGR=("_egr", "sum"), ODV=("_odv", "sum"),
                EXT=("_ext", "sum"), N=("id_mov", "count"))
           if not v.empty else pd.DataFrame(columns=clave + ["ING", "EGR", "ODV", "EXT", "N"]))
    base = (ini.groupby(clave, dropna=False, as_index=False).agg(INI=("_val", "sum"))
            if not ini.empty else pd.DataFrame(columns=clave + ["INI"]))
    g = mov.merge(base, on=clave, how="outer")
    if med is not None and not med.empty:
        _m = med.copy()
        _m["MED"] = _m["tn"] if um == "TN" else _m["kl"]
        _k = [c for c in clave if c in _m.columns]
        if _k:
            _a = {"MED": ("MED", "sum")}
            if "tanques_con_producto" in _m.columns:
                _a["TQ"] = ("tanques_con_producto", "sum")
            g = g.merge(_m.groupby(_k, as_index=False).agg(**_a), on=_k, how="outer")
    for c in ("ING", "EGR", "ODV", "EXT", "INI", "MED", "N", "TQ"):
        if c not in g.columns:
            g[c] = 0.0
        g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0.0)
    g["FIN"] = g["INI"] + g["ING"] - g["EGR"]
    g["DIF"] = g["FIN"] - g["MED"]
    return g


def _tabla_sector(g, um):
    g = g.sort_values("FIN", ascending=False)
    out = pd.DataFrame({
        "SECTOR": g["sector_nombre"].fillna(g["sector"]).fillna("(sin sector)"),
        f"SALDO INICIAL {um}": g["INI"].map(lambda x: _q(x, "0.0")),
        f"ENTRÓ DE AFUERA {um}": g["EXT"].map(_q),
        f"INGRESOS {um}": g["ING"].map(_q),
        f"SALIÓ POR ODV {um}": g["ODV"].map(_q),
        f"EGRESOS {um}": g["EGR"].map(_q),
        f"SALDO FINAL {um}": g["FIN"].map(lambda x: _q(x, "0.0")),
        f"MIDEN LOS TANQUES {um}": g["MED"].map(lambda x: _q(x, "0.0")),
        f"DIFERENCIA {um}": g["DIF"].map(lambda x: f"{float(x):+,.1f}"),
        "MOVIMIENTOS": g["N"].map(lambda x: f"{int(x):,}".replace(",", ".")),
    })
    tot = pd.DataFrame([{
        "SECTOR": "TOTAL PLANTA",
        f"SALDO INICIAL {um}": f"{g['INI'].sum():,.1f}",
        f"ENTRÓ DE AFUERA {um}": f"{g['EXT'].sum():,.1f}",
        f"INGRESOS {um}": f"{g['ING'].sum():,.1f}",
        f"SALIÓ POR ODV {um}": f"{g['ODV'].sum():,.1f}",
        f"EGRESOS {um}": f"{g['EGR'].sum():,.1f}",
        f"SALDO FINAL {um}": f"{g['FIN'].sum():,.1f}",
        f"MIDEN LOS TANQUES {um}": f"{g['MED'].sum():,.1f}",
        f"DIFERENCIA {um}": f"{g['DIF'].sum():+,.1f}",
        "MOVIMIENTOS": f"{int(g['N'].sum()):,}".replace(",", "."),
    }])
    return pd.concat([out, tot], ignore_index=True)


def _tabla_producto(g, um, nombres, sectores_de):
    g = g.sort_values("FIN", ascending=False)
    out = pd.DataFrame({
        "CUENTA": g["cuenta"].fillna("(sin producto)"),
        "PRODUCTO": [nombres.get(c, "") for c in g["cuenta"]],
        "EN QUÉ SECTORES": [sectores_de.get(c, "—") for c in g["cuenta"]],
        f"SALDO INICIAL {um}": g["INI"].map(lambda x: _q(x, "0.0")),
        f"ENTRÓ DE AFUERA {um}": g["EXT"].map(_q),
        f"INGRESOS {um}": g["ING"].map(_q),
        f"SALIÓ POR ODV {um}": g["ODV"].map(_q),
        f"EGRESOS {um}": g["EGR"].map(_q),
        f"SALDO FINAL {um}": g["FIN"].map(lambda x: _q(x, "0.0")),
        f"MIDEN LOS TANQUES {um}": g["MED"].map(lambda x: _q(x, "0.0")),
        "TANQUES": g["TQ"].map(lambda x: "—" if not x else f"{int(x)}"),
    })
    tot = pd.DataFrame([{
        "CUENTA": "TOTAL", "PRODUCTO": f"{len(g)} producto(s)", "EN QUÉ SECTORES": "",
        f"SALDO INICIAL {um}": f"{g['INI'].sum():,.1f}",
        f"ENTRÓ DE AFUERA {um}": f"{g['EXT'].sum():,.1f}",
        f"INGRESOS {um}": f"{g['ING'].sum():,.1f}",
        f"SALIÓ POR ODV {um}": f"{g['ODV'].sum():,.1f}",
        f"EGRESOS {um}": f"{g['EGR'].sum():,.1f}",
        f"SALDO FINAL {um}": f"{g['FIN'].sum():,.1f}",
        f"MIDEN LOS TANQUES {um}": f"{g['MED'].sum():,.1f}",
        "TANQUES": f"{int(g['TQ'].sum())}",
    }])
    return pd.concat([out, tot], ignore_index=True)


def _matriz(gsp, um):
    """Dónde está cada producto: saldo final por sector, una fila por producto."""
    m = gsp.pivot_table(index="cuenta", columns="sector_nombre", values="FIN",
                        aggfunc="sum", fill_value=0.0)
    m = m.loc[m.abs().sum(axis=1).sort_values(ascending=False).index]
    m["TOTAL"] = m.sum(axis=1)
    out = m.reset_index().rename(columns={"cuenta": "CUENTA"})
    for c in out.columns[1:]:
        out[c] = out[c].map(lambda x: _q(x, "—"))
    return out


# ------------------------------------------------------------------ paneles
def _panel_sin_tanque(st_df, um, div):
    """Consumos y producciones que no descuentan de ningún tanque."""
    if st_df is None or st_df.empty:
        st.caption("✅ Todos los movimientos del período pasaron por un tanque: no hay consumos "
                   "de producción cargados sin tanque asignado.")
        return 0.0
    d = st_df.copy()
    d["_val"] = d["kg_neto"] / div if um == "TN" else d["litros_neto"] / div
    _tn = float(d["_val"].abs().sum())
    g = (d.groupby(["sector_nombre", "grupo", "producto"], dropna=False, as_index=False)
         .agg(N=("id_mov", "count"), V=("_val", "sum"),
              TK=("ticket", lambda s: int(s.notna().sum()))))
    g = g.sort_values("V", key=lambda s: s.abs(), ascending=False)
    with st.expander(f"🕳️ {_tn:,.1f} {um} que no pasan por ningún tanque "
                     f"({len(d)} movimiento(s) en {g['sector_nombre'].nunique()} sector(es))",
                     expanded=False):
        st.dataframe(pd.DataFrame({
            "SECTOR": g["sector_nombre"].fillna("(sin sector)"),
            "QUÉ ES": g["grupo"].map({"MP": "Materia prima", "INSUMO": "Insumo",
                                      "PT": "Producto final"}).fillna("Otro"),
            "PRODUCTO": g["producto"].fillna(""),
            "MOVIMIENTOS": g["N"].map(lambda x: f"{int(x)}"),
            f"CANTIDAD {um}": g["V"].map(lambda x: f"{float(x):+,.1f}"),
            "CON TICKET DE PESADA": g["TK"].map(lambda x: f"{int(x)}" if x else "— ninguno"),
        }), hide_index=True, use_container_width=True,
            column_config={"PRODUCTO": st.column_config.TextColumn(width="medium")})
        st.caption("Son consumos cargados desde planificación con la orden de producción pero sin "
                   "tanque: la mercadería se usó de verdad y no se descontó de ningún lado. **No "
                   "están sumados en el libro de arriba a propósito**: parte de esa mercadería ya "
                   "se descontó con otro movimiento que sí tiene tanque, así que sumarla también "
                   "acá la contaría dos veces. La corrección va en la carga — la producción tiene "
                   "que decir de qué tanque salió —, y hasta que se haga, este número es el "
                   "tamaño de la duda.")
    return _tn


def _panel_sin_asentar(g, um):
    """Los saldos iniciales negativos: mercadería que entró y se movió sin cargar la salida."""
    d = g[g["INI"] < -0.05].sort_values("INI")
    if d.empty:
        st.caption("✅ Ningún producto arranca el período en negativo: no hay salidas sin cargar "
                   "arrastradas de meses anteriores.")
        return 0.0
    _tn = float(-d["INI"].sum())
    with st.expander(f"⚖️ Faltan asentar {_tn:,.1f} {um} de movimientos en {len(d)} producto(s)",
                     expanded=False):
        st.dataframe(pd.DataFrame({
            "SECTOR": d["sector_nombre"].fillna(d["sector"]),
            "CUENTA": d["cuenta"].fillna("(sin producto)"),
            f"ARRANCÓ EN {um}": d["INI"].map(lambda x: _q(x, "0.0")),
            f"ENTRÓ {um}": d["ING"].map(_q),
            f"SALIÓ {um}": d["EGR"].map(_q),
            f"MIDEN LOS TANQUES {um}": d["MED"].map(lambda x: _q(x, "0.0")),
        }), hide_index=True, use_container_width=True)
        st.caption("El saldo inicial se reconstruye desde la medición física de los tanques, así "
                   "que un arranque negativo es un número con sentido: el libro registró más "
                   "entradas de las que los tanques pueden explicar. En la planta eso es "
                   "mercadería que entró pesada por portería a un tanque y se movió a otro sector "
                   "sin que nadie asentara la salida. Es lo que hay que corregir en la carga.")
    return _tn


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def _consolidado(ctx):
    desde, hasta, etiqueta = _per.selector("stk_cons")

    c1, c2, c3 = st.columns([0.9, 2.4, 0.5])
    um = c1.radio("Unidad", list(_UM), horizontal=True, key="stk_cons_um",
                  label_visibility="collapsed",
                  help="Toneladas (los litros se pasan con la densidad del producto) o kilolitros.")
    c2.caption(f"Exportación · Reactores · Piletas · Bachas — {etiqueta}")
    if c3.button("↻", key="stk_cons_ref", use_container_width=True, help="Releer ahora"):
        invalidar(); _rerun_fragment()

    col, div = _UM[um]
    df = _movs(ctx["conn_factory"], desde, hasta)
    ini = _saldo_inicial(ctx["conn_factory"], desde)
    if df is None or ini is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    med = _medido(ctx["conn_factory"])
    cuentas = _cuentas(ctx["conn_factory"])

    ajustes_n = int(df["es_ajuste_sistema"].sum())
    v = df[~df["es_ajuste_sistema"]].copy()
    v["_val"] = v[col] / div
    v["_ing"] = v["_val"].map(lambda x: x if x > 0 else 0.0)
    v["_egr"] = v["_val"].map(lambda x: -x if x < 0 else 0.0)
    # lo que entró de afuera (pesado en portería) y lo que salió de la planta (por una ODV):
    # los traspasos entre sectores entran y salen, así que en el consolidado se netean solos.
    v["_ext"] = [i if _es_externo(o) else 0.0 for i, o in zip(v["_ing"], v["origen"])]
    v["_odv"] = [e if str(d or "").startswith("ODV") else 0.0
                 for e, d in zip(v["_egr"], v["destino"])]
    ini = ini.copy()
    ini["_val"] = ini[col] / div

    if v.empty and float(ini["_val"].abs().sum()) == 0:
        st.info(f"Sin movimientos de stock en {etiqueta}.")
        return

    _nom = {}
    for x in (v, ini):
        if not x.empty:
            _nom.update(dict(zip(x["cuenta"], x["cuenta_nombre"].fillna(""))))
    _sec_de = {}
    for c, s in pd.concat([x[["cuenta", "sector_nombre"]] for x in (v, ini) if not x.empty],
                          ignore_index=True).drop_duplicates().itertuples(index=False):
        _sec_de.setdefault(c, []).append(s)
    _sec_de = {c: ", ".join(sorted(x for x in s if x)) or "—" for c, s in _sec_de.items()}

    g_sec = _por(v, ini, med, um, ["sector", "sector_nombre"])
    g_cta = _por(v, ini, med, um, ["cuenta"])
    g_sp = _por(v, ini, med, um, ["sector", "sector_nombre", "cuenta"])

    # ---------------- indicadores ----------------
    s_ini, s_ing, s_egr = float(g_sec["INI"].sum()), float(g_sec["ING"].sum()), float(g_sec["EGR"].sum())
    s_fin, s_med = s_ini + s_ing - s_egr, float(g_sec["MED"].sum())
    s_ext, s_odv = float(g_sec["EXT"].sum()), float(g_sec["ODV"].sum())
    n_tq = int(g_sec["TQ"].sum())
    _u = f"<span style='font-size:1rem;font-weight:700;'> {um}</span>"
    _dif = s_fin - s_med
    _falta = float(-g_sp.loc[g_sp["INI"] < 0, "INI"].sum())

    k0 = _kpi("Existencia de planta", f"{_n(s_med,1)}{_u}",
              f"medido hoy en {n_tq} tanque(s) de {int(g_sec['sector'].nunique())} sectores", "")
    k1 = _kpi("Saldo inicial", f"{_n(s_ini,1)}{_u}", f"con lo que arranca {etiqueta}", "")
    k2 = _kpi("Entró de afuera", f"{_n(s_ext,1)}{_u}",
              f"pesado en portería · {_n(s_ing - s_ext,1)} {um} de traspasos entre sectores", "")
    k3 = _kpi("Salió de la planta", f"{_n(s_odv,1)}{_u}",
              f"por ODV · {_n(s_egr - s_odv,1)} {um} a proceso o a otro sector", "")
    k4 = _kpi("Saldo final", f"{_n(s_fin,1)}{_u}",
              (f"cierra contra los tanques" if abs(_dif) < 0.1
               else f"{_dif:+,.1f} {um} contra lo que miden los tanques"),
              "ok" if abs(_dif) < 0.1 else "bad")
    k5 = _kpi("Falta asentar", f"{_n(_falta,1)}{_u}",
              "salidas cargadas de menos" if _falta >= 0.05 else "nada pendiente",
              "bad" if _falta >= 0.05 else "ok")
    st.markdown(f'<div class="kpi-grid">{k0}{k1}{k2}{k3}{k4}{k5}</div>', unsafe_allow_html=True)

    _b = ini["base_fecha"].dropna() if "base_fecha" in ini.columns else []
    _bf = pd.to_datetime(_b.iloc[0]).date() if len(_b) else None
    st.caption((f"Saldo inicial del **{_bf:%d/%m/%Y}** (primer día hábil del mes), tomado de la "
                "medición física de los tanques de cada sector; el libro corre desde ahí. "
                if _bf is not None else
                "Todavía no hay saldo inicial cargado en algún sector: lo que se muestra es el "
                "arrastre del libro, así que no cierra contra los tanques. ")
               + "«Entró de afuera» es lo que pesó portería y «Salió de la planta» lo que se "
                 "embarcó por una ODV: un traspaso entre sectores entra en uno y sale del otro, "
                 "así que en el consolidado se netea solo."
               + (f" Quedan afuera {ajustes_n} ajustes automáticos de medición." if ajustes_n else ""))

    # ---------------- por sector ----------------
    st.markdown("<div class='section-title' style='margin:12px 0 2px'>Sector por sector</div>",
                unsafe_allow_html=True)
    st.dataframe(_tabla_sector(g_sec, um), hide_index=True, use_container_width=True,
                 height=min(420, 60 + 35 * (len(g_sec) + 1)))

    # ---------------- lo que se escapa ----------------
    st.markdown("<div class='section-title' style='margin:12px 0 2px'>Lo que se escapa</div>",
                unsafe_allow_html=True)
    _panel_sin_asentar(g_sp, um)
    stq = _sin_tanque(ctx["conn_factory"], desde, hasta)
    _panel_sin_tanque(stq, um, div)
    _mal = cuentas[~cuentas["del_sector"].fillna(True).astype(bool)] if not cuentas.empty else cuentas
    if _mal is not None and not _mal.empty:
        _l = sorted(f"{r.cuenta} en {r.sector}" for r in _mal.itertuples())
        with st.expander(f"🏷️ {len(_l)} producto(s) están en un sector que no los trabaja "
                         "(el tanque quedó designado así)", expanded=False):
            st.dataframe(pd.DataFrame({
                "SECTOR": _mal["sector"], "CUENTA": _mal["cuenta"],
                "QUÉ ES": _mal["descripcion"].fillna(""),
                "PAPEL": _mal["rol"].fillna(""),
            }).sort_values(["SECTOR", "CUENTA"]), hide_index=True, use_container_width=True)
            st.caption("Suman al consolidado igual — la mercadería está ahí de verdad —, pero el "
                       "tanque está designado con un producto que ese sector no trabaja. Corregir "
                       "la designación hace que el stock del sector deje de mostrar cosas ajenas.")

    # ---------------- por producto ----------------
    st.markdown("<div class='section-title' style='margin:14px 0 2px'>Producto por producto, "
                "toda la planta</div>", unsafe_allow_html=True)
    rep = _tabla_producto(g_cta, um, _nom, _sec_de)
    st.dataframe(rep, hide_index=True, use_container_width=True,
                 height=min(560, 60 + 35 * len(rep)),
                 column_config={"EN QUÉ SECTORES": st.column_config.TextColumn(width="medium")})

    # ---------------- dónde está cada producto ----------------
    mat = _matriz(g_sp, um)
    st.markdown("<div class='section-title' style='margin:14px 0 2px'>Dónde está cada producto "
                f"(saldo final en {um})</div>", unsafe_allow_html=True)
    st.dataframe(mat, hide_index=True, use_container_width=True,
                 height=min(520, 60 + 35 * len(mat)))

    # ---------------- Excel ----------------
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        _tabla_sector(g_sec, um).to_excel(xw, index=False, sheet_name="POR SECTOR")
        rep.to_excel(xw, index=False, sheet_name="POR PRODUCTO")
        mat.to_excel(xw, index=False, sheet_name="SECTOR x PRODUCTO")
        _d = g_sp[g_sp["INI"] < -0.05].sort_values("INI")
        if not _d.empty:
            pd.DataFrame({
                "SECTOR": _d["sector_nombre"], "CUENTA": _d["cuenta"],
                f"ARRANCO EN {um}": _d["INI"].round(1), f"ENTRO {um}": _d["ING"].round(1),
                f"SALIO {um}": _d["EGR"].round(1), f"MIDEN LOS TANQUES {um}": _d["MED"].round(1),
            }).to_excel(xw, index=False, sheet_name="FALTA ASENTAR")
        if stq is not None and not stq.empty:
            _s = stq.copy()
            _s[f"CANTIDAD {um}"] = (_s["kg_neto"] if um == "TN" else _s["litros_neto"]) / div
            _s[["sector_nombre", "fecha", "id_mov", "grupo", "producto", "tipo", "ticket", "op",
                f"CANTIDAD {um}", "observacion"]].to_excel(xw, index=False, sheet_name="SIN TANQUE")
        if not v.empty:
            v[["id_mov", "fecha", "sector_nombre", "cuenta", "cuenta_nombre", "origen", "destino",
               "tanque", "ticket", "contraparte", "_val", "observacion"]] \
                .rename(columns={"_val": f"CANTIDAD {um}"}) \
                .to_excel(xw, index=False, sheet_name="LIBRO COMPLETO")
    st.download_button("⬇️ Descargar Excel (sectores, productos, matriz y libro completo)",
                       buf.getvalue(),
                       file_name=f"stock_consolidado_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key="stk_cons_xls")


def render(ctx):
    st.markdown("<div class='section-title' style='margin:6px 0'>🧮 Stock consolidado · toda la "
                "planta</div>", unsafe_allow_html=True)
    _consolidado(ctx)
    st.caption("Los cuatro sectores con tanques (Exportación, Reactores, Piletas y Bachas) sumados "
               "con la misma lógica que su cuenta corriente: el saldo inicial es el stock del "
               "primer día hábil del mes medido en los tanques, y contra ese número corre el "
               "libro. Los sólidos que no tienen sistema de stock (compost, residuos, decomiso, "
               "ganado, tierra) no están acá: se cuentan en portería, no en stock. Esta pantalla "
               "es de dirección; cada sector sigue viendo sólo lo suyo.")
