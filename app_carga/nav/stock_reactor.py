# -*- coding: utf-8 -*-
"""Stock de PRODUCCIÓN › REACTOR: su propia regla de negocio (≠ Exportación).

Pedido de dirección (23/09/2026, «worms - produccion - reactor - stock.docx»):
  · Filtros con el mismo diseño que Exportación, adaptados a Reactor: primero MATERIA PRIMA,
    después INSUMO, después PRODUCTO TERMINADO (desplegables, uno o varios, vacío = todos);
    fechas, ticket, «➕ Más» y 🔍 Buscar.
  · Stock MEDIDO de acopio y de proceso (lo que miden hoy los tanques) y ficha por producto.
  · Solapas: «Consolidado del sector» y «Ficha por producto» (desplegable de todos).
  · Sin indicadores en pantalla: un botón «📊 Indicadores» debajo de los filtros los muestra
    en un desplegable. Sin leyendas: los avisos van a «🔔 Notificaciones».
  · Cuenta corriente con el formato de la planilla de Fer: FECHA · ORIGEN / DESTINO ·
    N° TICKET · UM · INGRESO · EGRESO · SALDO · COMENTARIO, en KL por defecto.

Regla de stock del reactor: saldo inicial (corte físico del mes) + ingresos (portería,
producto de cada reacción) − egresos (consumo por fórmula al cerrar la reacción, ODV).
El desvío contra lo medido se ve por producto en la ficha.

Fuentes:
  · producto de cada tanque y stock medido → produccion.v_acopio_sector (dim_tanque.id_producto_principal
    + última medición) y la cuenta con produccion.fn_cuenta_grado(producto, azufre, fósforo);
  · grupo MP / INSUMO / PT → dim_producto.tipo_producto (MP / INSUMO / FINAL) vía v_cuenta_sector;
  · productos habilitados por tanque → produccion.dim_tanque_producto_permitido;
  · libro (cuenta corriente) → produccion.v_stock_cuenta_sector; saldo inicial → fn_stock_saldo_a.
"""

import io
from datetime import date

import pandas as pd
import streamlit as st

import cache_rev as _cache_rev

from .kpis import _FRAGMENT, _TTL, _rerun_fragment
from .stock_cc import (_UM, _cat_de, _cerrar_corte, _col, _consolidado, _contraparte, _movs,
                       _notificaciones, _primer_dia_habil, _q, _saldo_inicial, invalidar)

_GRUPOS = (("MP", "🧱 Materia prima"), ("INSUMO", "🧪 Insumo"), ("PT", "✅ Producto terminado"))
_GRUPO_UI = {"MP": "MATERIA PRIMA", "INSUMO": "INSUMO", "PT": "PRODUCTO TERMINADO", "OTRO": "OTRO"}
_TIPO_A_GRUPO = {"MP": "MP", "INSUMO": "INSUMO", "FINAL": "PT"}
_UMS = ("KL", "TN")          # la planilla de Fer está en KL: es la unidad por defecto


# ------------------------------------------------------------------ datos
@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _tanques(_cf, sector):
    """Un renglón por tanque en uso del sector: su producto (cuenta oficial), grupo, ubicación
    (acopio / proceso) y lo que mide hoy. `permitidos` = lo que la planilla habilita."""
    sql = """
        SELECT a.tanque_codigo, a.tanque, a.grupo_fisico, a.producto_codigo,
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
        df["grupo"] = df["tipo_producto"].map(_TIPO_A_GRUPO).fillna("OTRO")
        df["ubicacion"] = df["grupo_fisico"].fillna("").str.contains("proceso", case=False).map(
            {True: "PROCESO", False: "ACOPIO"})
        df["cuenta"] = df["cuenta"].fillna(df["producto_codigo"]).fillna("(sin producto)")
        return df
    except Exception:
        return None


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _cuentas(_cf, sector):
    """Cuenta → (grupo, nombre de la planilla), para todas las cuentas del sector."""
    sql = ("SELECT c.cuenta, c.tipo_producto, c.tanques_en_uso, dp.nombre_producto "
           "FROM produccion.v_cuenta_sector c "
           "LEFT JOIN produccion.dim_producto dp ON upper(dp.codigo_producto) = upper(c.producto_codigo) "
           "WHERE c.sector = %s AND c.cuenta IS NOT NULL")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector,))
        df["grupo"] = df["tipo_producto"].map(_TIPO_A_GRUPO).fillna("OTRO")
        df["tanques_en_uso"] = pd.to_numeric(df["tanques_en_uso"], errors="coerce").fillna(0).astype(int)
        return df
    except Exception:
        return None


# ------------------------------------------------------------------ helpers
def _n1(x):
    return f"{float(x):,.1f}"


def _ficha_cc(w, s_ini, fecha_ini, um):
    """Cuenta corriente con el formato de la planilla (imagen del pedido): el saldo inicial es
    el primer renglón (entra como INGRESO y abre el SALDO), después cada movimiento."""
    cols = ["FECHA", "ORIGEN / DESTINO", "N° TICKET", "UM", "INGRESO", "EGRESO", "SALDO", "COMENTARIO"]
    cab = {"FECHA": f"{fecha_ini:%d/%m/%Y}", "ORIGEN / DESTINO": "SALDO INICIAL", "N° TICKET": "", "UM": um,
           "INGRESO": _q(s_ini, "") if s_ini > 0 else "", "EGRESO": _q(-s_ini, "") if s_ini < 0 else "",
           "SALDO": _n1(s_ini), "COMENTARIO": ""}
    if w.empty:
        return pd.DataFrame([cab], columns=cols)
    ing = w["_val"].map(lambda x: x if x > 0 else 0.0)
    egr = w["_val"].map(lambda x: -x if x < 0 else 0.0)
    saldo = s_ini + (ing - egr).cumsum()
    cuerpo = pd.DataFrame({
        "FECHA": w["momento"].map(lambda t: pd.to_datetime(t).strftime("%d/%m/%Y %H:%M") if not pd.isna(t) else "").values,
        "ORIGEN / DESTINO": _contraparte(w),
        "N° TICKET": w["ticket"].fillna("").values,
        "UM": um,
        "INGRESO": ing.map(lambda x: _q(x, "")).values,
        "EGRESO": egr.map(lambda x: _q(x, "")).values,
        "SALDO": saldo.map(_n1).values,
        "COMENTARIO": [(o or r or "") for o, r in zip(w["observacion"].fillna(""), w["referencia"].fillna(""))],
    })
    return pd.concat([pd.DataFrame([cab]), cuerpo], ignore_index=True)[cols]


def _medido_col(um):
    return ("act_l", 1000.0) if um == "KL" else ("act_tn", 1.0)


def _por_producto(tq, um, nombre_de):
    """STOCK MEDIDO POR PRODUCTO: acopio, proceso y total de cada cuenta."""
    cols = ["GRUPO", "PRODUCTO", "TANQUES", f"ACOPIO ({um})", f"PROCESO ({um})", f"TOTAL ({um})"]
    if tq.empty:
        return pd.DataFrame(columns=cols)
    c, d = _medido_col(um)
    t = tq.assign(_m=tq[c] / d)
    g = (t.pivot_table(index=["grupo", "cuenta"], columns="ubicacion", values="_m", aggfunc="sum", fill_value=0.0)
         .reindex(columns=["ACOPIO", "PROCESO"], fill_value=0.0))
    n = t.groupby(["grupo", "cuenta"])["tanque"].count()
    g = g.join(n.rename("n")).reset_index()
    g["_o"] = g["grupo"].map({"MP": 0, "INSUMO": 1, "PT": 2}).fillna(3)
    g = g.sort_values(["_o", "cuenta"])
    return pd.DataFrame({
        "GRUPO": g["grupo"].map(_GRUPO_UI).values,
        "PRODUCTO": g["cuenta"].map(nombre_de).values,
        "TANQUES": g["n"].astype(int).values,
        f"ACOPIO ({um})": g["ACOPIO"].map(_n1).values,
        f"PROCESO ({um})": g["PROCESO"].map(_n1).values,
        f"TOTAL ({um})": (g["ACOPIO"] + g["PROCESO"]).map(_n1).values,
    })[cols]


def _por_tanque(tq, nombre_de):
    cols = ["TK / ACOPIO", "PRODUCTO", "GRUPO", "MEDIDO (TN)", "MEDIDO (KL)", "CAPACIDAD (KL)", "% OCUPADO",
            "ÚLTIMA MEDICIÓN"]
    if tq.empty:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame({
        "TK / ACOPIO": tq["tanque"].values,
        "PRODUCTO": tq["cuenta"].map(nombre_de).values,
        "GRUPO": tq["grupo"].map(_GRUPO_UI).values,
        "MEDIDO (TN)": tq["act_tn"].map(_n1).values,
        "MEDIDO (KL)": (tq["act_l"] / 1000.0).map(_n1).values,
        "CAPACIDAD (KL)": (tq["cap_l"] / 1000.0).map(_n1).values,
        "% OCUPADO": [f"{(a / c * 100.0):.0f} %" if c else "—" for a, c in zip(tq["act_l"], tq["cap_l"])],
        "ÚLTIMA MEDICIÓN": tq["ultima_medicion"].map(
            lambda t: pd.to_datetime(t).strftime("%d/%m/%Y %H:%M") if not pd.isna(t) else "—").values,
    })[cols]


def _tabla(df, alto_max=560, **cc):
    st.dataframe(df, hide_index=True, use_container_width=True, height=min(alto_max, 40 + 35 * max(len(df), 1)),
                 column_config=cc or None)


def _titulo(txt, arriba=12):
    st.markdown(f"<div class='section-title' style='margin:{arriba}px 0 2px'>{txt}</div>", unsafe_allow_html=True)


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def pantalla(ctx, sec):
    import filtros_stock as _fs
    cod = sec["codigo"]
    cf = ctx["conn_factory"]
    hoy = date.today()
    corte = _primer_dia_habil(hoy)
    key = f"stkrx_{cod}"

    ctas = _cuentas(cf, cod)
    tq_all = _tanques(cf, cod)
    if ctas is None or tq_all is None:
        st.warning("Sin conexión a la base en este momento: volvé a entrar en unos segundos.")
        return
    nom = dict(zip(ctas["cuenta"].astype(str), ctas["nombre_producto"].fillna("").astype(str)))
    nom.update({str(c): str(n) for c, n in zip(tq_all["cuenta"], tq_all["nombre_producto"].fillna("")) if n})
    grp = dict(zip(ctas["cuenta"].astype(str), ctas["grupo"]))
    grp.update(dict(zip(tq_all["cuenta"].astype(str), tq_all["grupo"])))

    def nombre_de(c):
        n = nom.get(str(c), "")
        return f"{c} · {n}" if n else str(c)

    # desplegables: los productos que hoy tienen tanque en el sector, por grupo
    en_uso = sorted(set(tq_all["cuenta"].astype(str)))
    por_grupo = {g: [c for c in en_uso if grp.get(c) == g] for g, _ in _GRUPOS}
    etq = {c: nombre_de(c) for c in set(en_uso) | set(nom)}

    st.session_state.setdefault(f"{key}_desde", corte)
    st.session_state.setdefault(f"{key}_hasta", hoy)
    tanques_nom = sorted(tq_all["tanque"].dropna().astype(str).unique().tolist())

    def _mas():
        out = {}
        out["Unidad"] = st.radio("Unidad", list(_UMS), horizontal=True, key=f"{key}_um")
        out["Ubicación"] = st.selectbox("Acopio / proceso", ["(todos)", "ACOPIO", "PROCESO"], key=f"{key}_ubi")
        out["Tanque"] = st.selectbox("TK / Acopio", ["(todos)"] + tanques_nom, key=f"{key}_tq")
        out["Tipo"] = st.selectbox("Tipo de movimiento", ["(todos)", "Ingresos", "Egresos"], key=f"{key}_tipo")
        out["Origen/Destino"] = st.text_input("Origen / destino contiene", key=f"{key}_od",
                                              placeholder="proveedor, reacción RE-…, ODV, cliente…")
        out["Usuario"] = st.text_input("Usuario", key=f"{key}_usr", placeholder="quien cargó el movimiento")
        return out

    f, apretado = _fs.barra(_cat_de(cf), key=key, titulo=None, campos=("fecha", "tk"),
                            grupos=[(g, etq_g, por_grupo[g]) for g, etq_g in _GRUPOS],
                            multi=True, extras_fn=_mas, buscar=True, etiquetas=etq)

    k_ap = f"{key}_aplicado"
    if apretado or k_ap not in st.session_state:     # al entrar: todo el sector, sin filtros
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
    col, div = _UM[um]
    sel = [c for g, _ in _GRUPOS for c in ((fa.get("grupos") or {}).get(g) or [])]

    # ---- stock medido (hoy) ----
    tq = tq_all.copy()
    if sel:
        tq = tq[tq["cuenta"].isin(sel)]
    if prop.get("Ubicación") in ("ACOPIO", "PROCESO"):
        tq = tq[tq["ubicacion"] == prop["Ubicación"]]
    if prop.get("Tanque") not in (None, "", "(todos)"):
        tq = tq[tq["tanque"] == prop["Tanque"]]

    # ---- libro ----
    df = _movs(cf, (cod,), desde, hasta)
    ini = _saldo_inicial(cf, cod, desde)
    if df is None or ini is None:
        _notificaciones(slot_not, ["Sin conexión a la base en este momento: volvé a apretar Buscar."])
        return
    v = df[df["es_stock"] & ~df["es_ajuste_sistema"]].copy()   # los ajustes automáticos son de 0 kg
    v["_val"] = v[col] / div
    ini = ini.copy()
    ini["_val"] = pd.to_numeric(ini[col], errors="coerce").fillna(0.0) / div
    if sel:
        v = v[v["cuenta"].isin(sel)]
        ini = ini[ini["cuenta"].isin(sel)]
    libro = v.copy()                                        # saldo real: sin los filtros secundarios
    if prop.get("Tanque") not in (None, "", "(todos)"):
        v = v[_col(v, "tanque", "").fillna("").astype(str) == prop["Tanque"]]
    if prop.get("Tipo") == "Ingresos":
        v = v[v["_val"] > 0]
    elif prop.get("Tipo") == "Egresos":
        v = v[v["_val"] < 0]
    if (prop.get("Origen/Destino") or "").strip():
        q = prop["Origen/Destino"].strip().lower()
        v = v[pd.Series(_contraparte(v), index=v.index).str.lower().str.contains(q, regex=False)]
    if (prop.get("Usuario") or "").strip():
        q = prop["Usuario"].strip().lower()
        v = v[_col(v, "usuario", "").fillna("").astype(str).str.lower().str.contains(q, regex=False)]
    if fa["tk"]:
        q = fa["tk"].strip().lower()
        m = v["id_mov"].astype(str).str.contains(q, regex=False)
        for c in ("ticket", "tickets_detalle", "referencia"):
            m = m | v[c].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        v = v[m]

    # saldo del libro vs. medido, por cuenta
    s_libro = (ini.groupby("cuenta")["_val"].sum()
               .add(libro.groupby("cuenta")["_val"].sum(), fill_value=0.0))
    mc, md = _medido_col(um)
    s_med = (tq_all.assign(_m=tq_all[mc] / md).groupby("cuenta")["_m"].sum())

    # ---- 📊 Indicadores (sólo al apretar) ----
    with c_ind.popover("📊 Indicadores", use_container_width=True):
        _titulo("MATERIA PRIMA E INSUMOS · TOTALES", 0)
        t = tq_all.assign(_m=tq_all[mc] / md)
        filas = []
        for g, _ in _GRUPOS:
            x = t[t["grupo"] == g]
            filas.append({"GRUPO": _GRUPO_UI[g], "PRODUCTOS": x["cuenta"].nunique(), "TANQUES": len(x),
                          f"ACOPIO ({um})": _n1(x.loc[x["ubicacion"] == "ACOPIO", "_m"].sum()),
                          f"PROCESO ({um})": _n1(x.loc[x["ubicacion"] == "PROCESO", "_m"].sum()),
                          f"TOTAL ({um})": _n1(x["_m"].sum())})
        filas.append({"GRUPO": "TOTAL SECTOR", "PRODUCTOS": t["cuenta"].nunique(), "TANQUES": len(t),
                      f"ACOPIO ({um})": _n1(t.loc[t["ubicacion"] == "ACOPIO", "_m"].sum()),
                      f"PROCESO ({um})": _n1(t.loc[t["ubicacion"] == "PROCESO", "_m"].sum()),
                      f"TOTAL ({um})": _n1(t["_m"].sum())})
        st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)

    # ---- 🔔 Notificaciones ----
    avisos = []
    fuera = [r for _, r in tq_all.iterrows()
             if len(r["permitidos"] or []) and r["producto_codigo"] not in (r["permitidos"] or [])]
    for r in fuera:
        avisos.append(f"**{r['tanque']}** tiene **{r['cuenta']}**; la planilla lo habilita para "
                      f"{', '.join(r['permitidos'])}.")
    for _, r in tq_all[(tq_all["cap_l"] > 0) & (tq_all["act_l"] > tq_all["cap_l"] * 1.02)].iterrows():
        avisos.append(f"**{r['tanque']}** mide {r['act_l'] / 1000:,.1f} KL con capacidad de "
                      f"{r['cap_l'] / 1000:,.1f} KL: revisar medición o capacidad.")
    _bf = ini["base_fecha"].dropna() if "base_fecha" in ini.columns else pd.Series([], dtype=object)
    if not len(_bf):
        avisos.append("Todavía no hay saldo inicial cargado para el período: el saldo es el arrastre del libro.")
    _neg = sorted(ini.loc[ini["_val"] < -0.05, "cuenta"].dropna().astype(str).unique().tolist())
    if _neg:
        avisos.append("Arrancan en negativo: **" + ", ".join(_neg) + "**.")
    _notificaciones(slot_not, avisos)

    tab_c, tab_f = st.tabs(["📦 Consolidado del sector", "🗂️ Ficha por producto"])

    # ---- Consolidado ----
    with tab_c:
        _titulo("STOCK MEDIDO POR PRODUCTO", 6)
        _tabla(_por_producto(tq, um, nombre_de), PRODUCTO=st.column_config.TextColumn(width="large"))
        for ubi in ("ACOPIO", "PROCESO"):
            x = tq[tq["ubicacion"] == ubi]
            if prop.get("Ubicación") in ("ACOPIO", "PROCESO") and prop["Ubicación"] != ubi:
                continue
            _titulo(f"STOCK MEDIDO · {ubi}")
            _tabla(_por_tanque(x, nombre_de), PRODUCTO=st.column_config.TextColumn(width="large"))
        _titulo("SALDO CONSOLIDADO POR PRODUCTO")
        cons = _consolidado(v, ini, um, nombre_de)
        _tabla(cons, PRODUCTO=st.column_config.TextColumn(width="medium"),
               COMENTARIO=st.column_config.TextColumn(width="medium"), UM=st.column_config.TextColumn(width="small"))

    # ---- Ficha por producto ----
    todas = [c for g, _ in _GRUPOS for c in por_grupo[g]]
    todas += sorted((set(ini.loc[ini["_val"].abs() >= 0.05, "cuenta"].dropna().astype(str))
                     | set(libro["cuenta"].dropna().astype(str))) - set(todas))
    if sel:
        todas = [c for c in todas if c in sel]
    with tab_f:
        if not todas:
            _tabla(_ficha_cc(v.iloc[0:0], 0.0, desde, um))
        else:
            k_c = f"{key}_cta"
            if st.session_state.get(k_c) not in todas:
                st.session_state[k_c] = todas[0]
            cta = st.selectbox("Producto", todas, key=k_c, label_visibility="collapsed",
                               format_func=lambda c: f"{_GRUPO_UI.get(grp.get(c, 'OTRO'), 'OTRO')} · {nombre_de(c)}")
            x = tq_all[tq_all["cuenta"] == cta]
            med = float(s_med.get(cta, 0.0))
            lib = float(s_libro.get(cta, 0.0))
            _tabla(pd.DataFrame([{
                "PRODUCTO": nombre_de(cta), "GRUPO": _GRUPO_UI.get(grp.get(cta, "OTRO"), "OTRO"),
                "TANQUES": len(x),
                f"ACOPIO ({um})": _n1(x.loc[x["ubicacion"] == "ACOPIO", mc].sum() / md),
                f"PROCESO ({um})": _n1(x.loc[x["ubicacion"] == "PROCESO", mc].sum() / md),
                f"MEDIDO ({um})": _n1(med), f"LIBRO ({um})": _n1(lib), f"DESVÍO ({um})": f"{med - lib:+,.1f}",
            }]), PRODUCTO=st.column_config.TextColumn(width="large"))
            if not x.empty:
                _tabla(_por_tanque(x, nombre_de).drop(columns=["PRODUCTO", "GRUPO"]))
            _titulo(f"CUENTA CORRIENTE · {cta}")
            w = v[v["cuenta"] == cta].sort_values(["momento", "id_mov"])
            s_ini = float(ini.loc[ini["cuenta"] == cta, "_val"].sum())
            _tabla(_ficha_cc(w, s_ini, desde, um), alto_max=620,
                   **{"ORIGEN / DESTINO": st.column_config.TextColumn(width="medium"),
                      "COMENTARIO": st.column_config.TextColumn(width="medium")})

    # ---- Excel y corte del mes ----
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        _por_producto(tq, um, nombre_de).to_excel(xw, index=False, sheet_name="STOCK MEDIDO")
        _por_tanque(tq, nombre_de).to_excel(xw, index=False, sheet_name="TANQUES")
        cons.to_excel(xw, index=False, sheet_name="SALDO CONSOLIDADO")
        for c in todas[:40]:
            hoja = str(c)[:28].replace("/", "-").replace("\\", "-").replace(":", "-")
            _w = v[v["cuenta"] == c].sort_values(["momento", "id_mov"])
            _ficha_cc(_w, float(ini.loc[ini["cuenta"] == c, "_val"].sum()), desde, um).to_excel(
                xw, index=False, sheet_name=hoja)
    b1, b2, _ = st.columns([1.3, 1.3, 2.4])
    b1.download_button("⬇️ Descargar Excel", buf.getvalue(),
                       file_name=f"stock_reactor_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"{key}_xls", use_container_width=True)
    conectar = ctx.get("conectar")
    if conectar is not None and ctx["puede_seccion"]("STOCK"):
        if b2.button(f"🔄 Recalcular saldo inicial {corte:%d/%m}", key=f"{key}_corte", use_container_width=True):
            try:
                row = _cerrar_corte(conectar, ctx["USR"], cod, hoy)
                invalidar(); _tanques.clear(); _cuentas.clear()
                st.toast(f"Saldo inicial recalculado: {int(row[0])} cuenta(s), {float(row[1]):,.1f} TN.")
                _rerun_fragment()
            except Exception as e:
                st.error(f"No se pudo recalcular el saldo inicial: {e}")
