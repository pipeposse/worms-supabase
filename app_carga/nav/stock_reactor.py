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
from .stock_cc import (_UM, _cat_de, _catalogo, _cerrar_corte, _col, _comentario, _consolidado,
                       _contraparte, _fecha_txt, _hora_planta, _movs, _nombre_cuenta, _notificaciones,
                       _primer_dia_habil, _producto_de, _q, _saldo_inicial, _texto_saldo_inicial, _ticket,
                       invalidar)

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


def _ficha_cc(w, s_ini, fecha_ini, um, com_ini=""):
    """Cuenta corriente con el formato de la planilla (imagen del pedido): el saldo inicial es
    el primer renglón (entra como INGRESO y abre el SALDO), después cada movimiento."""
    cols = ["FECHA", "ORIGEN / DESTINO", "N° TICKET", "UM", "INGRESO", "EGRESO", "SALDO", "COMENTARIO"]
    cab = {"FECHA": f"{fecha_ini:%d/%m/%Y}", "ORIGEN / DESTINO": "SALDO INICIAL", "N° TICKET": "", "UM": um,
           "INGRESO": _q(s_ini, "") if s_ini > 0 else "", "EGRESO": _q(-s_ini, "") if s_ini < 0 else "",
           "SALDO": _n1(s_ini), "COMENTARIO": com_ini}
    if w.empty:
        return pd.DataFrame([cab], columns=cols)
    ing = w["_val"].map(lambda x: x if x > 0 else 0.0)
    egr = w["_val"].map(lambda x: -x if x < 0 else 0.0)
    saldo = s_ini + (ing - egr).cumsum()
    cuerpo = pd.DataFrame({
        "FECHA": w["momento"].map(_fecha_txt).values,
        "ORIGEN / DESTINO": _contraparte(w),
        "N° TICKET": _ticket(w),
        "UM": um,
        "INGRESO": ing.map(lambda x: _q(x, "")).values,
        "EGRESO": egr.map(lambda x: _q(x, "")).values,
        "SALDO": saldo.map(_n1).values,
        "COMENTARIO": _comentario(w, con_tk=True),
    })
    return pd.concat([pd.DataFrame([cab]), cuerpo], ignore_index=True)[cols]


def _medido_col(um):
    return ("act_l", 1000.0) if um == "KL" else ("act_tn", 1.0)


def _por_producto(tq, um, nombre_de, conf):
    """STOCK MEDIDO POR PRODUCTO: lo medido en cada ubicación y el total de cada cuenta."""
    u1, u2 = conf["ubicaciones"]
    cols = ["GRUPO", "PRODUCTO", "TANQUES", f"{u1} ({um})", f"{u2} ({um})", f"TOTAL ({um})"]
    if tq.empty:
        return pd.DataFrame(columns=cols)
    c, d = _medido_col(um)
    t = tq.assign(_m=tq[c] / d)
    g = (t.pivot_table(index=["grupo", "cuenta"], columns="ubicacion", values="_m", aggfunc="sum", fill_value=0.0)
         .reindex(columns=[u1, u2], fill_value=0.0))
    n = t.groupby(["grupo", "cuenta"])["tanque"].count()
    g = g.join(n.rename("n")).reset_index()
    _ord = {k: i for i, (k, _) in enumerate(conf["grupos"])}
    g["_o"] = g["grupo"].map(_ord).fillna(len(_ord))
    g = g.sort_values(["_o", "cuenta"])
    return pd.DataFrame({
        "GRUPO": g["grupo"].map(lambda x: conf["grupo_ui"].get(x, x)).values,
        "PRODUCTO": g["cuenta"].map(nombre_de).values,
        "TANQUES": g["n"].astype(int).values,
        f"{u1} ({um})": g[u1].map(_n1).values,
        f"{u2} ({um})": g[u2].map(_n1).values,
        f"TOTAL ({um})": (g[u1] + g[u2]).map(_n1).values,
    })[cols]


def _por_tanque(tq, nombre_de, conf):
    cols = ["TK / ACOPIO", "PRODUCTO", "GRUPO", "MEDIDO (TN)", "MEDIDO (KL)", "CAPACIDAD (KL)", "% OCUPADO",
            "ÚLTIMA MEDICIÓN"]
    if tq.empty:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame({
        "TK / ACOPIO": tq["tanque"].values,
        "PRODUCTO": tq["cuenta"].map(nombre_de).values,
        "GRUPO": tq["grupo"].map(lambda x: conf["grupo_ui"].get(x, x)).values,
        "MEDIDO (TN)": tq["act_tn"].map(_n1).values,
        "MEDIDO (KL)": (tq["act_l"] / 1000.0).map(_n1).values,
        "CAPACIDAD (KL)": (tq["cap_l"] / 1000.0).map(_n1).values,
        "% OCUPADO": [f"{(a / c * 100.0):.0f} %" if c else "sin capacidad" for a, c in zip(tq["act_l"], tq["cap_l"])],
        "ÚLTIMA MEDICIÓN": tq["ultima_medicion"].map(lambda t: _fecha_txt(t) or "—").values,
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
    nom_prod = {k: v[0] for k, v in prods.items()}
    nom_prod.update({k: v for k, v in _nom_cat.items() if v and k not in nom_prod})

    def nombre_de(c):
        return _nombre_cuenta(c, cta_prod, nom_prod)

    def grupo_de(c):
        pr = _producto_de(c, cta_prod, prods)
        return conf["grupo_fn"](pr, (prods.get(pr) or ("", ""))[1])

    _ordg = {k: i for i, (k, _) in enumerate(GR)}

    def orden_cta(c):
        return (_ordg.get(grupo_de(c), len(_ordg)), str(c))

    tq_all = tq_all.copy()
    tq_all["grupo"] = [conf["grupo_fn"](p_, t_) for p_, t_ in zip(tq_all["producto_codigo"], tq_all["tipo_producto"])]
    tq_all["ubicacion"] = tq_all["grupo_fisico"].map(conf["ubic_fn"])

    # desplegables: los productos que hoy tienen tanque en el sector, por grupo
    en_uso = sorted(set(tq_all["cuenta"].astype(str)))
    grp_tq = dict(zip(tq_all["cuenta"].astype(str), tq_all["grupo"]))
    por_grupo = {g: [c for c in en_uso if grp_tq.get(c) == g] for g, _ in GR}
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
    sel = [c for g, _ in GR for c in ((fa.get("grupos") or {}).get(g) or [])]
    _ubi = prop.get("Ubicación") if prop.get("Ubicación") in (U1, U2) else None
    _tqf = prop.get("Tanque") if prop.get("Tanque") not in (None, "", "(todos)") else None

    # ---- stock medido (hoy) ----
    tq = tq_all.copy()
    if sel:
        tq = tq[tq["cuenta"].isin(sel)]
    if _ubi:
        tq = tq[tq["ubicacion"] == _ubi]
    if _tqf:
        tq = tq[tq["tanque"] == _tqf]

    # ---- libro ----
    df = _movs(cf, (cod,), desde, hasta)
    ini = _saldo_inicial(cf, cod, desde)
    if df is None or ini is None:
        _notificaciones(slot_not, ["Sin conexión a la base en este momento: volvé a apretar Buscar."])
        return
    v = df[df["es_stock"] & ~df["es_ajuste_sistema"]].copy()   # los ajustes automáticos son de 0 kg
    v = v[(v["kg_neto"] != 0) | (v["litros_neto"] != 0)]     # asignaciones de 0 kg: no son movimientos
    v["_val"] = v[col] / div
    ini = ini.copy()
    ini["_val"] = pd.to_numeric(ini[col], errors="coerce").fillna(0.0) / div
    if sel:
        v = v[v["cuenta"].isin(sel)]
        ini = ini[ini["cuenta"].isin(sel)]
    libro = v.copy()                                        # saldo real: sin los filtros secundarios
    if _tqf:
        v = v[_col(v, "tanque", "").fillna("").astype(str) == _tqf]
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
    com_ini = _texto_saldo_inicial(ini, desde)

    # saldo del libro vs. medido, por cuenta
    s_libro = (ini.groupby("cuenta")["_val"].sum()
               .add(libro.groupby("cuenta")["_val"].sum(), fill_value=0.0))
    mc, md = _medido_col(um)
    s_med = (tq_all.assign(_m=tq_all[mc] / md).groupby("cuenta")["_m"].sum())

    # ---- 📊 Indicadores (sólo al apretar) ----
    with c_ind.popover("📊 Indicadores", use_container_width=True):
        _titulo(conf["titulo_ind"], 0)
        t = tq_all.assign(_m=tq_all[mc] / md)
        filas = []
        for g, _ in GR:
            x = t[t["grupo"] == g]
            filas.append({"GRUPO": GUI.get(g, g), "PRODUCTOS": x["cuenta"].nunique(), "TANQUES": len(x),
                          f"{U1} ({um})": _n1(x.loc[x["ubicacion"] == U1, "_m"].sum()),
                          f"{U2} ({um})": _n1(x.loc[x["ubicacion"] == U2, "_m"].sum()),
                          f"TOTAL ({um})": _n1(x["_m"].sum())})
        filas.append({"GRUPO": "TOTAL SECTOR", "PRODUCTOS": t["cuenta"].nunique(), "TANQUES": len(t),
                      f"{U1} ({um})": _n1(t.loc[t["ubicacion"] == U1, "_m"].sum()),
                      f"{U2} ({um})": _n1(t.loc[t["ubicacion"] == U2, "_m"].sum()),
                      f"TOTAL ({um})": _n1(t["_m"].sum())})
        st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)

    # ---- 🔔 Notificaciones ----
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
    _neg = sorted(ini.loc[ini["_val"] < -0.05, "cuenta"].dropna().astype(str).unique().tolist())
    if _neg:
        avisos.append("Arrancan el período en negativo: **" + ", ".join(_neg) + "**.")
    avisos.append(f"Saldo inicial al {desde:%d/%m/%Y}: {com_ini}.")
    _notificaciones(slot_not, avisos)

    tab_c, tab_f = st.tabs(["📦 Consolidado del sector", "🗂️ Ficha por producto"])

    # ---- Consolidado ----
    cons = _consolidado(v, ini, um, nombre_de, desde, orden=orden_cta)
    with tab_c:
        _titulo("STOCK MEDIDO POR PRODUCTO", 6)
        _tabla(_por_producto(tq, um, nombre_de, conf), PRODUCTO=st.column_config.TextColumn(width="large"))
        for ubi in (U1, U2):
            if _ubi and _ubi != ubi:
                continue
            _titulo(f"STOCK MEDIDO · {ubi}")
            _tabla(_por_tanque(tq[tq["ubicacion"] == ubi], nombre_de, conf),
                   PRODUCTO=st.column_config.TextColumn(width="large"))
        _titulo("SALDO CONSOLIDADO POR PRODUCTO")
        _tabla(cons, PRODUCTO=st.column_config.TextColumn(width="medium"),
               COMENTARIO=st.column_config.TextColumn(width="medium"), UM=st.column_config.TextColumn(width="small"))

    # ---- Ficha por producto ----
    todas = [c for g, _ in GR for c in por_grupo[g]]
    todas += sorted((set(ini.loc[ini["_val"].abs() >= 0.05, "cuenta"].dropna().astype(str))
                     | set(libro["cuenta"].dropna().astype(str))) - set(todas), key=orden_cta)
    if sel:
        todas = [c for c in todas if c in sel]
    with tab_f:
        if not todas:
            _tabla(_ficha_cc(v.iloc[0:0], 0.0, desde, um, com_ini))
        else:
            k_c = f"{key}_cta"
            if st.session_state.get(k_c) not in todas:
                st.session_state[k_c] = todas[0]
            cta = st.selectbox("Producto", todas, key=k_c, label_visibility="collapsed",
                               format_func=lambda c: f"{GUI.get(grupo_de(c), 'OTRO')} · {nombre_de(c)}")
            x = tq_all[tq_all["cuenta"] == cta]
            med = float(s_med.get(cta, 0.0))
            lib = float(s_libro.get(cta, 0.0))
            _tabla(pd.DataFrame([{
                "PRODUCTO": nombre_de(cta), "GRUPO": GUI.get(grupo_de(cta), "OTRO"),
                "TANQUES": len(x),
                f"{U1} ({um})": _n1(x.loc[x["ubicacion"] == U1, mc].sum() / md),
                f"{U2} ({um})": _n1(x.loc[x["ubicacion"] == U2, mc].sum() / md),
                f"MEDIDO ({um})": _n1(med), f"LIBRO ({um})": _n1(lib), f"DESVÍO ({um})": f"{med - lib:+,.1f}",
            }]), PRODUCTO=st.column_config.TextColumn(width="large"))
            if not x.empty:
                _tabla(_por_tanque(x, nombre_de, conf).drop(columns=["PRODUCTO", "GRUPO"]))
            _titulo(f"CUENTA CORRIENTE · {nombre_de(cta)}")
            w = v[v["cuenta"] == cta].sort_values(["momento", "id_mov"])
            s_ini = float(ini.loc[ini["cuenta"] == cta, "_val"].sum())
            _tabla(_ficha_cc(w, s_ini, desde, um, com_ini), alto_max=620,
                   **{"ORIGEN / DESTINO": st.column_config.TextColumn(width="medium"),
                      "COMENTARIO": st.column_config.TextColumn(width="medium")})

    # ---- Excel y corte del mes ----
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        _por_producto(tq, um, nombre_de, conf).to_excel(xw, index=False, sheet_name="STOCK MEDIDO")
        _por_tanque(tq, nombre_de, conf).to_excel(xw, index=False, sheet_name="TANQUES")
        cons.to_excel(xw, index=False, sheet_name="SALDO CONSOLIDADO")
        for c in todas[:40]:
            hoja = str(c)[:28].replace("/", "-").replace("\\", "-").replace(":", "-")
            _w = v[v["cuenta"] == c].sort_values(["momento", "id_mov"])
            _ficha_cc(_w, float(ini.loc[ini["cuenta"] == c, "_val"].sum()), desde, um, com_ini).to_excel(
                xw, index=False, sheet_name=hoja)
    b1, b2, _ = st.columns([1.3, 1.3, 2.4])
    b1.download_button("⬇️ Descargar Excel", buf.getvalue(),
                       file_name=f"{conf['archivo']}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
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
