# -*- coding: utf-8 -*-
"""Stock MEDIDO + libro de PRODUCCIÓN › REACTOR y PRODUCCIÓN › PILETAS.

Cada sector con su regla de negocio (≠ Exportación, que sigue en stock_cc):

REACTOR (pedido de dirección 23/09/2026, «worms - produccion - reactor - stock.docx»)
  · Filtros: primero MATERIA PRIMA, después INSUMO, después PRODUCTO TERMINADO (grupo =
    dim_producto.tipo_producto: MP / INSUMO / FINAL), fechas, ticket, «➕ Más», 🔍 Buscar.
  · Stock medido de ACOPIO y de PROCESO (grupo físico «Reactores (Proceso)» = proceso).
  · Regla: saldo inicial (corte físico) + ingresos (portería, producto de cada reacción)
    − egresos (consumo por fórmula al cerrar la reacción, ODV).

PILETAS (24/09/2026)
  · Todo lo que hay es materia prima: los filtros son por familia (AFE · Ácidos grasos ·
    Otros). Ubicación: PILETAS o CÓNICOS BACHAS (el sector Bachas está en construcción y
    sus cónicos se ven acá).

Para los dos: solapas «Consolidado del sector» y «Ficha por producto», cuenta corriente con
el formato de la planilla de Fer (FECHA · ORIGEN / DESTINO · N° TICKET · UM · INGRESO ·
EGRESO · SALDO · COMENTARIO) en KL por defecto, «📊 Indicadores» y «🔔 Notificaciones»
debajo de los filtros, sin leyendas.

Fuentes:
  · producto de cada tanque y stock medido → produccion.v_acopio_sector (dim_tanque.id_producto_principal
    + última medición de fact_stock_tanque) y la cuenta con produccion.fn_cuenta_grado(producto, azufre, fósforo);
  · grupo → dim_producto.tipo_producto (Reactor) o la familia del código (Piletas);
  · productos habilitados por tanque → produccion.dim_tanque_producto_permitido;
  · libro (cuenta corriente) → produccion.v_stock_cuenta_sector; saldo inicial → fn_stock_saldo_a.
"""

import io
from datetime import date

import pandas as pd
import streamlit as st

import cache_rev as _cache_rev

from .kpis import _FRAGMENT, _TTL, _rerun_fragment
from .stock_cc import (_UM, _ar, _cat_de, _catalogo, _cerrar_corte, _cuenta_corriente_producto, _cuentas_de,
                       _fecha_txt, _hora_planta, _nombre_cuenta, _notificaciones, _primer_dia_habil, _producto_de,
                       _texto_saldo_inicial, invalidar)

_TIPO_A_GRUPO = {"MP": "MP", "INSUMO": "INSUMO", "FINAL": "PT"}
_UMS = ("KL", "TN")          # la planilla de Fer está en KL: es la unidad por defecto


def _grupo_reactor(prod, tipo):
    return _TIPO_A_GRUPO.get(str(tipo or ""), "OTRO")


def _grupo_piletas(prod, tipo):
    """AFE-* · ácidos grasos AG-A…AG-E · el resto (AG-PES es aceite de pescado, no ácido graso)."""
    import re as _re
    p = str(prod or "").upper()
    if p.startswith("AFE"):
        return "AFE"
    if _re.match(r"^AG-[A-E]$", p):
        return "AG"
    return "OTRO"


_CONF = {
    "REACTORES": dict(
        grupos=(("MP", "🧱 Materia prima"), ("INSUMO", "🧪 Insumo"), ("PT", "✅ Producto terminado")),
        grupo_ui={"MP": "MATERIA PRIMA", "INSUMO": "INSUMO", "PT": "PRODUCTO TERMINADO", "OTRO": "OTRO"},
        grupo_fn=_grupo_reactor,
        ubicaciones=("ACOPIO", "PROCESO"), ubi_label="Acopio / proceso",
        ubic_fn=lambda gf: "PROCESO" if "proceso" in str(gf or "").lower() else "ACOPIO",
        titulo_ind="MATERIA PRIMA E INSUMOS · TOTALES", archivo="stock_reactor"),
    "PILETAS": dict(
        grupos=(("AFE", "🛢️ AFE"), ("AG", "🧴 Ácidos grasos"), ("OTRO", "📦 Otros")),
        grupo_ui={"AFE": "AFE", "AG": "ÁCIDOS GRASOS", "OTRO": "OTROS"},
        grupo_fn=_grupo_piletas,
        ubicaciones=("PILETAS", "CÓNICOS BACHAS"), ubi_label="Piletas / cónicos",
        ubic_fn=lambda gf: "CÓNICOS BACHAS" if "bacha" in str(gf or "").lower() else "PILETAS",
        titulo_ind="STOCK MEDIDO · TOTALES", archivo="stock_piletas"),
}
SECTORES = tuple(_CONF)


# ------------------------------------------------------------------ datos
@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _tanques(_cf, sector):
    """Un renglón por tanque en uso del sector: su producto (cuenta oficial), grupo, ubicación
    (acopio / proceso) y lo que mide hoy. `permitidos` = lo que la planilla habilita."""
    sql = """
        SELECT a.id_tanque, a.tanque_codigo, a.tanque, a.grupo_fisico, a.producto_codigo,
               (produccion.fn_cuenta_grado(a.producto_codigo, a.azufre, a.fosforo)).cuenta AS cuenta,
               dp.tipo_producto, dp.nombre_producto,
               a.act_tn, a.act_l, a.cap_l, a.pct_ocupado, a.ultima_medicion, a.confianza,
               ARRAY(SELECT p.codigo_producto FROM produccion.dim_tanque_producto_permitido pp
                     JOIN produccion.dim_producto p ON p.id_producto = pp.id_producto
                     WHERE pp.id_tanque = a.id_tanque ORDER BY 1) AS permitidos
        FROM produccion.v_acopio_sector a
        LEFT JOIN produccion.dim_producto dp ON dp.codigo_producto = a.producto_codigo
        WHERE a.sector = %s AND a.activo AND a.condicion <> 'FUERA DE USO'
        ORDER BY a.grupo_fisico, a.tanque"""
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector,))
        for c in ("act_tn", "act_l", "cap_l", "pct_ocupado"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        df["cuenta"] = df["cuenta"].fillna(df["producto_codigo"]).fillna("(sin producto)")
        df["ultima_medicion"] = _hora_planta(df["ultima_medicion"])
        return df
    except Exception:
        return None


@_cache_rev.cachear(ttl=600, show_spinner=False)
def _productos(_cf):
    """Código de producto → (nombre de la planilla, tipo MP / INSUMO / FINAL)."""
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT codigo_producto, nombre_producto, tipo_producto "
                                   "FROM produccion.dim_producto", conn)
        return {str(r.codigo_producto): (str(r.nombre_producto or ""), str(r.tipo_producto or ""))
                for r in df.itertuples()}
    except Exception:
        return None


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _repetidas(_cf, sector):
    """Tanques cuya medición es EXACTAMENTE la misma hace días (valor arrastrado, no medido)."""
    sql = """
        SELECT s.id_tanque, s.medido_en::date AS dia, max(s.litros) AS litros
          FROM produccion.fact_stock_tanque s
          JOIN produccion.v_acopio_sector a ON a.id_tanque = s.id_tanque
         WHERE a.sector = %s AND a.activo AND s.litros IS NOT NULL AND s.medido_en > now() - interval '20 days'
         GROUP BY 1, 2"""
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector,))
    except Exception:
        return {}
    if df is None or df.empty or not {"id_tanque", "dia", "litros"} <= set(df.columns):
        return {}
    out = {}
    for tq, g in df.sort_values("dia").groupby("id_tanque"):
        vals = pd.to_numeric(g["litros"], errors="coerce").tolist()
        dias = g["dia"].tolist()
        if not vals or not vals[-1]:
            continue
        i = len(vals) - 1
        while i > 0 and vals[i - 1] == vals[-1]:
            i -= 1
        if len(vals) - i >= 5:                     # 5 días o más con el mismo número
            out[int(tq)] = (pd.to_datetime(dias[i]).date(), float(vals[-1]))
    return out


# ------------------------------------------------------------------ helpers
def _n1(x):
    x = round(float(x), 1)
    return f"{(x if x != 0 else 0.0):,.1f}"


def _medido_col(um):
    return ("act_l", 1000.0) if um == "KL" else ("act_tn", 1.0)


def _por_producto(tq, um, nombre_de, conf):
    """SALDO CONSOLIDADO = lo MEDIDO hoy: GRUPO · PRODUCTO · <ubicación 1> · <ubicación 2> · TOTAL."""
    u1, u2 = conf["ubicaciones"]
    cols = ["GRUPO", "PRODUCTO", f"{u1} ({um})", f"{u2} ({um})", f"TOTAL ({um})"]
    if tq.empty:
        return pd.DataFrame(columns=cols)
    c, d = _medido_col(um)
    t = tq.assign(_m=tq[c] / d)
    g = (t.pivot_table(index=["grupo", "cuenta"], columns="ubicacion", values="_m", aggfunc="sum", fill_value=0.0)
         .reindex(columns=[u1, u2], fill_value=0.0)).reset_index()
    _ord = {k: i for i, (k, _) in enumerate(conf["grupos"])}
    g["_o"] = g["grupo"].map(_ord).fillna(len(_ord))
    g = g.sort_values(["_o", "cuenta"])
    return pd.DataFrame({
        "GRUPO": g["grupo"].map(lambda x: conf["grupo_ui"].get(x, x)).values,
        "PRODUCTO": g["cuenta"].map(nombre_de).values,
        f"{u1} ({um})": g[u1].map(_ar).values,
        f"{u2} ({um})": g[u2].map(_ar).values,
        f"TOTAL ({um})": (g[u1] + g[u2]).map(_ar).values,
    })[cols]


def _tabla(df, alto_max=560, **cc):
    st.dataframe(df, hide_index=True, use_container_width=True, height=min(alto_max, 40 + 35 * max(len(df), 1)),
                 column_config=cc or None)


def _titulo(txt, arriba=12):
    st.markdown(f"<div class='section-title' style='margin:{arriba}px 0 2px'>{txt}</div>", unsafe_allow_html=True)


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def pantalla(ctx, sec):
    """Una sola pantalla, igual en todos los sectores (dirección, 25/09/2026):
    filtros → SALDO CONSOLIDADO (lo MEDIDO hoy) → CUENTA CORRIENTE POR PRODUCTO (el LIBRO)."""
    import filtros_stock as _fs
    cod = sec["codigo"]
    conf = _CONF.get(cod, _CONF["REACTORES"])
    GR = conf["grupos"]
    GUI = conf["grupo_ui"]
    U1, U2 = conf["ubicaciones"]
    cf = ctx["conn_factory"]
    hoy = date.today()
    corte = _primer_dia_habil(hoy)
    key = f"stkrx_{cod}"

    prods = _productos(cf)
    tq_all = _tanques(cf, cod)
    if prods is None or tq_all is None:
        st.warning("Sin conexión a la base en este momento: volvé a entrar en unos segundos.")
        return
    cta_prod, _nom_cat = _catalogo(cf)

    def nombre_de(c):
        return _nombre_cuenta(c, cta_prod, {})

    def grupo_de(c):
        pr = _producto_de(c, cta_prod, prods)
        return conf["grupo_fn"](pr, (prods.get(pr) or ("", ""))[1])

    _ordg = {k: i for i, (k, _) in enumerate(GR)}

    def orden_cta(c):
        return (_ordg.get(grupo_de(c), len(_ordg)), str(c))

    tq_all = tq_all.copy()
    tq_all["grupo"] = [conf["grupo_fn"](p_, t_) for p_, t_ in zip(tq_all["producto_codigo"], tq_all["tipo_producto"])]
    tq_all["ubicacion"] = tq_all["grupo_fisico"].map(conf["ubic_fn"])
    _ubic_tq = dict(zip(tq_all["tanque"].astype(str), tq_all["ubicacion"]))
    ubic_de = lambda t: _ubic_tq.get(str(t), "")   # noqa: E731

    # desplegables por grupo: los productos con tanque en el sector + los que tienen movimientos
    en_uso = sorted(set(tq_all["cuenta"].astype(str)) | set(_cuentas_de(cf, (cod,))), key=orden_cta)
    por_grupo = {g: [c for c in en_uso if grupo_de(c) == g] for g, _ in GR}
    etq = {c: nombre_de(c) for c in en_uso}

    st.session_state.setdefault(f"{key}_desde", corte)
    st.session_state.setdefault(f"{key}_hasta", hoy)
    tanques_nom = sorted(tq_all["tanque"].dropna().astype(str).unique().tolist())

    def _mas():
        out = {}
        out["Unidad"] = st.radio("Unidad", list(_UMS), horizontal=True, key=f"{key}_um")
        out["Ubicación"] = st.selectbox(conf["ubi_label"], ["(todos)", U1, U2], key=f"{key}_ubi")
        out["Tanque"] = st.selectbox("TK / Acopio", ["(todos)"] + tanques_nom, key=f"{key}_tq")
        out["Tipo"] = st.selectbox("Tipo de movimiento", ["(todos)", "Ingresos", "Egresos"], key=f"{key}_tipo")
        out["Origen/Destino"] = st.text_input("Origen / destino contiene", key=f"{key}_od",
                                              placeholder="proveedor, reacción RE-…, ODV, cliente…")
        out["Usuario"] = st.text_input("Usuario", key=f"{key}_usr", placeholder="quien cargó el movimiento")
        return out

    f, apretado = _fs.barra(_cat_de(cf), key=key, titulo=None, campos=("fecha", "tk"),
                            grupos=[(g, etq_g, por_grupo[g]) for g, etq_g in GR if por_grupo[g]],
                            multi=True, extras_fn=_mas, buscar=True, etiquetas=etq)
    k_ap = f"{key}_aplicado"
    if apretado or k_ap not in st.session_state:     # al entrar: todo el sector, sin apretar Buscar
        st.session_state[k_ap] = f
    fa = st.session_state[k_ap]

    c_ind, c_not, _ = st.columns([1.3, 1.3, 3.4])
    slot_not = c_not.container()

    desde = fa["desde"] or corte
    hasta = fa["hasta"] or hoy
    if hasta < desde:
        desde, hasta = hasta, desde
    prop = fa.get("propios") or {}
    um = prop.get("Unidad") or "KL"
    sel = [c for g, _ in GR for c in ((fa.get("grupos") or {}).get(g) or [])]
    _ubi = prop.get("Ubicación") if prop.get("Ubicación") in (U1, U2) else None
    _tqf = prop.get("Tanque") if prop.get("Tanque") not in (None, "", "(todos)") else None
    mc, md = _medido_col(um)

    # ---- SALDO CONSOLIDADO = MEDIDO hoy ----
    tq = tq_all.copy()
    if sel:
        tq = tq[tq["cuenta"].isin(sel)]
    if _ubi:
        tq = tq[tq["ubicacion"] == _ubi]
    if _tqf:
        tq = tq[tq["tanque"] == _tqf]
    cons = _por_producto(tq, um, nombre_de, conf)
    _titulo(f"SALDO CONSOLIDADO · medido al {hoy:%d/%m/%Y}", 8)
    k_c = f"{key}_cta"
    ev = st.dataframe(cons, hide_index=True, use_container_width=True, key=f"{key}_cons",
                      height=min(600, 38 + 35 * max(len(cons), 1)), on_select="rerun", selection_mode="single-row",
                      column_config={"PRODUCTO": st.column_config.TextColumn(width="medium"),
                                     "GRUPO": st.column_config.TextColumn(width="small")})
    try:
        _rows = ev.selection.rows
    except Exception:
        _rows = []
    if _rows and 0 <= _rows[0] < len(cons) and st.session_state.get(f"{key}_sel_prev") != _rows[0]:
        st.session_state[f"{key}_sel_prev"] = _rows[0]
        st.session_state[k_c] = str(cons.iloc[_rows[0]]["PRODUCTO"])

    # ---- 📊 Indicadores (sólo al apretar) ----
    with c_ind.popover("📊 Indicadores", use_container_width=True):
        _titulo(conf["titulo_ind"], 0)
        t = tq_all.assign(_m=tq_all[mc] / md)
        filas = []
        for g, _ in GR:
            x = t[t["grupo"] == g]
            filas.append({"GRUPO": GUI.get(g, g), "PRODUCTOS": x["cuenta"].nunique(), "TANQUES": len(x),
                          f"{U1} ({um})": _ar(x.loc[x["ubicacion"] == U1, "_m"].sum()),
                          f"{U2} ({um})": _ar(x.loc[x["ubicacion"] == U2, "_m"].sum()),
                          f"TOTAL ({um})": _ar(x["_m"].sum())})
        filas.append({"GRUPO": "TOTAL SECTOR", "PRODUCTOS": t["cuenta"].nunique(), "TANQUES": len(t),
                      f"{U1} ({um})": _ar(t.loc[t["ubicacion"] == U1, "_m"].sum()),
                      f"{U2} ({um})": _ar(t.loc[t["ubicacion"] == U2, "_m"].sum()),
                      f"TOTAL ({um})": _ar(t["_m"].sum())})
        st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)

    # ---- 🔔 Notificaciones (sólo sobre la medición) ----
    avisos = []
    for _, r in tq_all.iterrows():
        _pm = list(r["permitidos"] or [])
        if _pm and r["producto_codigo"] not in _pm:
            avisos.append(f"**{r['tanque']}** tiene **{r['cuenta']}**; la planilla lo habilita para "
                          f"{', '.join(_pm)}.")
    for _, r in tq_all[(tq_all["cap_l"] > 0) & (tq_all["act_l"] > tq_all["cap_l"] * 1.02)].iterrows():
        avisos.append(f"**{r['tanque']}** mide {r['act_l'] / 1000:,.1f} KL con capacidad de "
                      f"{r['cap_l'] / 1000:,.1f} KL: revisar medición o capacidad.")
    for _, r in tq_all[(tq_all["cap_l"] <= 0) & (tq_all["act_l"] > 0)].iterrows():
        avisos.append(f"**{r['tanque']}** no tiene capacidad cargada (mide {r['act_l'] / 1000:,.1f} KL).")
    _rep = _repetidas(cf, cod)
    for _, r in tq_all.iterrows():
        _x = _rep.get(int(r["id_tanque"])) if pd.notna(r.get("id_tanque")) else None
        if _x:
            avisos.append(f"**{r['tanque']}** marca exactamente {_x[1]:,.0f} L todos los días desde el "
                          f"{_x[0]:%d/%m}: parece un valor arrastrado, no una medición.")

    # ---- CUENTA CORRIENTE POR PRODUCTO = LIBRO ----
    _titulo("CUENTA CORRIENTE POR PRODUCTO", 16)
    todas = [c for c in en_uso if (not sel or c in sel)]
    if not todas:
        st.dataframe(pd.DataFrame(columns=["FECHA", "ORIGEN / DESTINO", "UBICACIÓN", "N° TICKET", "UM", "INGRESO",
                                           "EGRESO", "SALDO", "COMENTARIOS"]), hide_index=True, use_container_width=True)
        _notificaciones(slot_not, avisos)
        return
    if st.session_state.get(k_c) not in todas:
        st.session_state[k_c] = todas[0]
    cta = st.selectbox("Producto", todas, key=k_c, label_visibility="collapsed",
                       format_func=lambda c: f"{GUI.get(grupo_de(c), 'OTRO')} · {nombre_de(c)}")
    tabla, ini = _cuenta_corriente_producto(cf, [cod], cta, desde, hasta, um, fa, prop, ubic_de=ubic_de)
    if tabla is None:
        st.warning("Sin conexión a la base en este momento: volvé a apretar Buscar.")
        return
    st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(640, 40 + 35 * len(tabla)),
                 column_config={"ORIGEN / DESTINO": st.column_config.TextColumn(width="medium"),
                                "UBICACIÓN": st.column_config.TextColumn(width="small"),
                                "N° TICKET": st.column_config.TextColumn(width="medium"),
                                "COMENTARIOS": st.column_config.TextColumn(width="large")})
    avisos.append(f"Saldo inicial de la cuenta corriente al {desde:%d/%m/%Y}: {_texto_saldo_inicial(ini, desde)}.")
    _notificaciones(slot_not, avisos)

    # ---- Excel y corte del mes ----
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        cons.to_excel(xw, index=False, sheet_name="SALDO CONSOLIDADO")
        tabla.to_excel(xw, index=False, sheet_name=str(cta)[:28].replace("/", "-"))
    b1, b2, _ = st.columns([1.3, 1.3, 2.4])
    b1.download_button("⬇️ Descargar Excel", buf.getvalue(),
                       file_name=f"{conf['archivo']}_{cta}_{hoy:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"{key}_xls", use_container_width=True)
    conectar = ctx.get("conectar")
    if conectar is not None and ctx["puede_seccion"]("STOCK"):
        if b2.button(f"🔄 Recalcular saldo inicial {corte:%d/%m}", key=f"{key}_corte", use_container_width=True):
            try:
                row = _cerrar_corte(conectar, ctx["USR"], cod, hoy)
                invalidar(); _tanques.clear(); _repetidas.clear()
                st.toast(f"Saldo inicial recalculado: {int(row[0])} cuenta(s), {float(row[1]):,.1f} TN.")
                _rerun_fragment()
            except Exception as e:
                st.error(f"No se pudo recalcular el saldo inicial: {e}")
