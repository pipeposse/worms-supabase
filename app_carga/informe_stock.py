# -*- coding: utf-8 -*-
"""Informe de stock por producto y calidad (Centro de Planificación).

Tres niveles, la misma cuenta en todos:

    STOCK DISPONIBLE = MEDIDO − COMPROMETIDO

  · MEDIDO       = la última medición física del tanque.
  · COMPROMETIDO = lo designado en despachos CONFIRMADOS que todavía no terminaron
                   de pesar en portería (regla: un despacho retiene el 100% de sus
                   líneas hasta que pesa todos sus contenedores).
  · DISPONIBLE   = lo que realmente se puede usar/vender hoy.

El código del producto ya trae la calidad (AG-C, ARE-B, AFE-S), así que
"producto_calidad" es una sola columna y no hace falta cruzar nada.
Todo se descarga en un Excel de 3 hojas o en CSV.
"""
import io as _io

import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")


SPEC_S, SPEC_P = 50.0, 150.0     # spec de venta AG-E: define la banda A/B/C/D
_BCOL = {"A": "#166534", "B": "#1d4ed8", "C": "#b45309", "D": "#b91c1c", "SIN LAB": "#94a3b8"}
_BDESC = {"A": "excelente", "B": "bueno", "C": "justo", "D": "fuera de spec",
          "SIN LAB": "sin análisis"}
_BEMO = {"A": "🟢", "B": "🔵", "C": "🟠", "D": "🔴", "SIN LAB": "⚪"}
_BORD = ["A", "B", "C", "D", "SIN LAB"]


def _banda(s_, p_):
    """Banda de calidad contra la spec de venta — la misma regla que Balance y Despachos."""
    _s = None if (s_ is None or pd.isna(s_) or float(s_) <= 0) else float(s_)
    _p = None if (p_ is None or pd.isna(p_) or float(p_) <= 0) else float(p_)
    if _s is None and _p is None:
        return "SIN LAB"
    ic = max((_s / SPEC_S) if _s is not None else 0.0,
             (_p / SPEC_P) if _p is not None else 0.0)
    if ic <= 0.80:
        return "A"
    if ic <= 0.90:
        return "B"
    if ic <= 1.00:
        return "C"
    return "D"


def _n(v, dec=0):
    try:
        if v is None or pd.isna(v):
            return "—"
        return ("{:,.%df}" % dec).format(float(v))
    except Exception:
        return "—"


def _datos(cat):
    """Tanques con medido/comprometido/disponible + a qué despachos está comprometido."""
    tk = cat("SELECT id_tanque, nombre, sector, producto_principal, producto_rotulo, "
             "capacidad_litros, "
             "COALESCE(litros_actual,0) AS medido_l, COALESCE(kg_actual,0) AS medido_kg, "
             "COALESCE(litros_comprometido,0) AS comp_l, "
             "COALESCE(densidad,0.91) AS densidad, densidad_fuente, "
             "ultima_medicion, fuente_medicion, "
             "acidez, fosforo, azufre, agua_sedimento, condicion "
             "FROM produccion.vw_tanque_panel "
             "WHERE activo AND producto_principal IS NOT NULL "
             "ORDER BY producto_principal, nombre")
    dc = cat("SELECT c.id_tanque, c.id_despacho, c.litros_comprometido AS litros, "
             "d.titulo, d.cliente, d.destino, d.fecha_despacho, d.estado, "
             "c.n_tickets, c.n_contenedores "
             "FROM produccion.vw_despacho_comprometido c "
             "JOIN produccion.fact_despacho d ON d.id_despacho = c.id_despacho "
             "WHERE c.litros_comprometido > 0")
    return tk, dc


def _png(df, titulo, max_filas=45):
    """Imagen PNG de una tabla, para pegar en WhatsApp o en un informe."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = df.head(max_filas).copy()
    for c in x.columns:
        if pd.api.types.is_numeric_dtype(x[c]):
            _dec = 2 if ("(kL)" in str(c) or str(c) == "kL") else (
                1 if ("(t)" in str(c) or "%" in str(c)) else 0)
            x[c] = x[c].map(lambda v: _n(v, _dec))
        else:
            # matplotlib no tiene glifos para los emoji: se sacan o salen cuadraditos
            x[c] = (x[c].astype(str)
                    .str.replace(r"[\U0001F300-\U0001FAFF\u26A0\uFE0F\u2B1C\u2705]",
                                 "", regex=True)
                    .str.strip().str.slice(0, 42))
    x = x.fillna("—").astype(str)
    _w = max(9.0, min(22.0, 1.15 * len(x.columns)))
    fig, ax = plt.subplots(figsize=(_w, 0.34 * (len(x) + 2) + 1.1))
    ax.axis("off")
    tb = ax.table(cellText=x.values, colLabels=list(x.columns), loc="center",
                  cellLoc="center")
    tb.auto_set_font_size(False)
    tb.set_fontsize(8)
    tb.scale(1, 1.28)
    for j in range(len(x.columns)):
        tb[0, j].set_facecolor("#1e3a8a")
        tb[0, j].set_text_props(color="white", fontweight="bold")
    for i in range(1, len(x) + 1):
        if str(x.iloc[i - 1, 0]).strip().upper() == "TOTAL":
            for j in range(len(x.columns)):
                tb[i, j].set_facecolor("#e2e8f0")
                tb[i, j].set_text_props(fontweight="bold")
    ax.set_title("%s · %s" % (titulo, pd.Timestamp.today().strftime("%d/%m/%Y %H:%M")),
                 fontsize=11, fontweight="bold", pad=10)
    buf = _io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _excel(res, det, desp, porde=None, bandas=None):
    buf = _io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        res.to_excel(w, sheet_name="Resumen", index=False)
        if bandas is not None and not bandas.empty:
            bandas.to_excel(w, sheet_name="Por calidad (banda)", index=False)
        det.to_excel(w, sheet_name="Detalle por tanque", index=False)
        if porde is not None and not porde.empty:
            porde.to_excel(w, sheet_name="Por despacho", index=False)
        if desp is not None and not desp.empty:
            desp.to_excel(w, sheet_name="Despacho x tanque", index=False)
        for _sh, _df in (("Resumen", res), ("Por calidad (banda)", bandas),
                         ("Detalle por tanque", det),
                         ("Por despacho", porde), ("Despacho x tanque", desp)):
            if _df is None or _df.empty:
                continue
            ws = w.sheets[_sh]
            ws.freeze_panes = "A2"
            for i, c in enumerate(_df.columns):
                _len = max([len(str(c))] + [len(str(x)) for x in _df[c].head(200)])
                ws.column_dimensions[chr(65 + i) if i < 26
                                     else "A" + chr(65 + i - 26)].width = max(11, min(34, _len + 2))
    return buf.getvalue()


def _tabla_bandas(dd):
    """Por banda: tanques, litros/t, %, parámetros ponderados por kg y dónde está."""
    dd = dd.copy()
    dd["banda"] = [(_banda(a, b)) for a, b in zip(dd["azufre"], dd["fosforo"])]
    dd["_kg"] = dd["medido_l"] * dd["densidad"]
    _tot_l = float(dd["medido_l"].sum()) or 1.0
    filas = []
    for b in _BORD:
        g = dd[dd["banda"] == b]
        if g.empty:
            continue
        _kg = float(g["_kg"].sum()) or 1.0

        def _pond(col):
            v = g[pd.notna(g[col]) & (g[col] > 0)]
            return (float((v[col] * v["_kg"]).sum() / float(v["_kg"].sum()))
                    if not v.empty and float(v["_kg"].sum()) > 0 else None)

        _tks = " · ".join("%s (%s kL)" % (r["nombre"], _n(r["medido_l"], 2))
                          for _, r in g.sort_values("medido_l", ascending=False).iterrows())
        filas.append({
            "Banda": "%s %s · %s" % (_BEMO[b], b, _BDESC[b]),
            "_b": b,
            "Tanques": int(len(g)),
            "Medido (kL)": float(g["medido_l"].sum()),
            "Medido (t)": float(g["medido_t"].sum()),
            "% del total": 100.0 * float(g["medido_l"].sum()) / _tot_l,
            "Comprometido (kL)": float(g["comp_l"].sum()),
            "Disponible (kL)": float(g["disp_l"].sum()),
            "Acidez %": _pond("acidez"),
            "Fósforo ppm": _pond("fosforo"),
            "Azufre ppm": _pond("azufre"),
            "AyS %": _pond("agua_sedimento"),
            "En qué tanques": _tks,
        })
    return pd.DataFrame(filas)


def _barra_bandas(tb):
    """Barra apilada de % por banda (HTML sin estado: no puede colgarse)."""
    if tb is None or tb.empty:
        return ""
    _seg = "".join(
        "<div title='%s: %s%% · %s kL' style='width:%.4f%%;background:%s'></div>"
        % (r["_b"], _n(r["% del total"], 0), _n(r["Medido (kL)"], 2),
           max(0.0, float(r["% del total"])), _BCOL.get(r["_b"], "#94a3b8"))
        for _, r in tb.iterrows())
    _leg = " ".join(
        "<span style='color:%s;font-weight:700'>%s %s %s%%</span>"
        % (_BCOL.get(r["_b"], "#94a3b8"), _BEMO.get(r["_b"], ""), r["_b"],
           _n(r["% del total"], 0)) for _, r in tb.iterrows())
    return ("<div style='display:flex;height:16px;border-radius:8px;overflow:hidden;"
            "border:1px solid #e2e8f0;margin:2px 0 4px'>%s</div>"
            "<div style='font-size:.8rem'>%s</div>" % (_seg, _leg))


def _vista_rapida(d):
    """Lo que se mira todos los días: cuánto AFE-S y cuánto AG-E hay de cada banda."""
    st.markdown("##### ⚡ Vista rápida por calidad — AFE-S y AG-E")
    st.caption("Banda contra la **spec de venta** (S ≤ 50 · P ≤ 150), la misma que usan Balance "
               "y el armador de despachos: 🟢 **A** excelente (S≤40 y P≤120) · 🔵 **B** bueno "
               "(S≤45 y P≤135) · 🟠 **C** justo (cumple sin margen) · 🔴 **D** fuera de spec "
               "(sólo entra mezclado) · ⚪ sin análisis.")
    _tabs = st.tabs(["🔵 AFE-S", "🟠 AG-E", "🧪 Todos los AFE"])
    for _t, _fil, _tit in ((_tabs[0], lambda x: x["prod_cal"] == "AFE-S", "AFE-S"),
                           (_tabs[1], lambda x: x["prod_cal"] == "AG-E", "AG-E"),
                           (_tabs[2], lambda x: x["prod_cal"].str.startswith("AFE"),
                            "todos los AFE")):
        with _t:
            dd = d[_fil(d)]
            if dd.empty:
                st.info("No hay tanques de %s con los filtros actuales." % _tit)
                continue
            tb = _tabla_bandas(dd)
            if tb.empty:
                st.info("Sin datos de calidad para %s." % _tit)
                continue
            m1, m2, m3 = st.columns(3)
            m1.metric("Medido", "%s t" % _n(dd["medido_t"].sum(), 1),
                      "%s kL en %d tanques" % (_n(dd["medido_l"].sum(), 2), len(dd)))
            _ab = float(tb[tb["_b"].isin(["A", "B"])]["Medido (kL)"].sum())
            _cd = float(tb[tb["_b"].isin(["C", "D"])]["Medido (kL)"].sum())
            _tt = float(tb["Medido (kL)"].sum()) or 1.0
            m2.metric("🟢🔵 A + B", "%.0f %%" % (100.0 * _ab / _tt), "%s kL" % _n(_ab, 2),
                      help="El stock que sostiene la exportación: absorbe AG-E sin pasarse "
                           "de la spec.")
            m3.metric("🟠🔴 C + D", "%.0f %%" % (100.0 * _cd / _tt), "%s kL" % _n(_cd, 2),
                      help="El que hay que colocar mezclado con los buenos.")
            st.markdown(_barra_bandas(tb), unsafe_allow_html=True)
            _cols = ["Banda", "Tanques", "Medido (kL)", "Medido (t)", "% del total",
                     "Comprometido (kL)", "Disponible (kL)", "Acidez %", "Fósforo ppm",
                     "Azufre ppm", "AyS %", "En qué tanques"]
            st.dataframe(tb[_cols], hide_index=True, use_container_width=True,
                         column_config={
                             "Medido (kL)": st.column_config.NumberColumn(format="%.2f"),
                             "Medido (t)": st.column_config.NumberColumn(format="%.1f"),
                             "Comprometido (kL)": st.column_config.NumberColumn(format="%.2f"),
                             "Disponible (kL)": st.column_config.NumberColumn(format="%.2f"),
                             "% del total": st.column_config.ProgressColumn(
                                 "% del total", format="%.0f%%", min_value=0, max_value=100),
                             "Acidez %": st.column_config.NumberColumn(format="%.2f"),
                             "Fósforo ppm": st.column_config.NumberColumn(format="%.1f"),
                             "Azufre ppm": st.column_config.NumberColumn(format="%.1f"),
                             "AyS %": st.column_config.NumberColumn(format="%.2f"),
                             "En qué tanques": st.column_config.TextColumn(
                                 "En qué tanques", width="large",
                                 help="Tanques de esa banda, del que más tiene al que menos.")},
                         height=min(38 * (len(tb) + 1) + 6, 300))
            st.caption("Los parámetros son el **promedio ponderado por kg** de esa banda. "
                       "Pasá el mouse por *En qué tanques* para ver la lista completa.")
            st.session_state["_ifs_bandas_%s" % _tit] = tb


def render(USR, cat, conectar=None):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#1e3a8a,#0891b2);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>📦 Informe de stock por "
        "producto y calidad</div>"
        "<div style='color:#e0f2fe;font-size:.88rem;margin-top:3px'>Qué hay de cada producto, "
        "en qué tanque, cuánto está comprometido en despachos y cuánto queda realmente "
        "disponible.</div></div>", unsafe_allow_html=True)
    _secs = USR.get("secciones_app") or []
    if (USR.get("rol") not in ROLES_DIRECCION
            and "PLANIFICACION" not in _secs and "INICIAR" not in _secs):
        # también se muestra en Producción en planta (INICIAR): es lectura, sin acciones
        st.warning("No tenés acceso a esta sección.")
        return

    tk, dc = _datos(cat)
    if tk is None or tk.empty:
        st.info("No hay tanques activos con producto asignado.")
        return
    tk = tk.copy()
    for c in ("capacidad_litros", "medido_l", "medido_kg", "comp_l", "densidad",
              "acidez", "fosforo", "azufre", "agua_sedimento"):
        tk[c] = pd.to_numeric(tk[c], errors="coerce").fillna(0.0)
    tk["disp_l"] = (tk["medido_l"] - tk["comp_l"]).clip(lower=0.0)
    tk["medido_t"] = tk["medido_l"] * tk["densidad"] / 1000.0
    tk["comp_t"] = tk["comp_l"] * tk["densidad"] / 1000.0
    tk["disp_t"] = tk["disp_l"] * tk["densidad"] / 1000.0
    # unidades VISIBLES en kL (2 dec). Va después de calcular disponible y toneladas;
    # los ratios (% compr., % del total) y los ponderados no cambian con la escala.
    for _ckl in ("medido_l", "comp_l", "disp_l", "capacidad_litros"):
        tk[_ckl] = tk[_ckl] / 1000.0
    # el nombre visible es el RÓTULO OFICIAL: trae la calidad (GLICERINA-C (recuperada))
    tk["prod_cal"] = (tk["producto_rotulo"].fillna(tk["producto_principal"])
                        .astype(str).str.strip())

    # a qué despachos está comprometido cada tanque (texto compacto)
    _por_tk = {}
    if dc is not None and not dc.empty:
        dc = dc.copy()
        dc["litros"] = pd.to_numeric(dc["litros"], errors="coerce").fillna(0.0) / 1000.0  # kL
        for _t, _g in dc.groupby("id_tanque"):
            _por_tk[int(_t)] = " · ".join(
                "#%d %s (%s kL)" % (int(r["id_despacho"]), str(r["titulo"] or "—"),
                                    _n(r["litros"], 2))
                for _, r in _g.sort_values("litros", ascending=False).iterrows())
    tk["despachos"] = tk["id_tanque"].map(lambda i: _por_tk.get(int(i), ""))

    # ---------- filtros ----------
    f1, f2, f3 = st.columns([2, 2, 1.4])
    _prods = sorted(tk["prod_cal"].unique().tolist())
    _fp = f1.multiselect("Producto · calidad", _prods, key="ifs_prod", placeholder="todos")
    _secs = sorted(tk["sector"].fillna("—").unique().tolist())
    _fs = f2.multiselect("Sector", _secs, key="ifs_sec", placeholder="todos")
    _solo = f3.checkbox("Sólo con stock", value=True, key="ifs_solo",
                        help="Oculta los tanques vacíos (medido = 0).")
    d = tk
    if _fp:
        d = d[d["prod_cal"].isin(_fp)]
    if _fs:
        d = d[d["sector"].fillna("—").isin(_fs)]
    if _solo:
        d = d[d["medido_l"] > 0]
    if d.empty:
        st.info("Ningún tanque cumple los filtros.")
        return

    # ---------- KPIs ----------
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Medido", "%s t" % _n(d["medido_t"].sum(), 1),
              "%s kL" % _n(d["medido_l"].sum(), 2))
    k2.metric("🔒 Comprometido", "%s t" % _n(d["comp_t"].sum(), 1),
              "%s kL" % _n(d["comp_l"].sum(), 2),
              help="En despachos confirmados que todavía no terminaron de pesar.")
    k3.metric("✅ Disponible", "%s t" % _n(d["disp_t"].sum(), 1),
              "%s kL" % _n(d["disp_l"].sum(), 2))
    k4.metric("Productos · tanques", "%d · %d" % (d["prod_cal"].nunique(), len(d)))
    st.caption("**Volúmenes en kL** (1 kL = 1.000 L) · **t = kL × densidad**: se usa la "
               "densidad medida por el **laboratorio en cada tanque** y, si no hay o es "
               "implausible, la del maestro del producto (columnas *Dens.* y *Dens. fuente* "
               "en el detalle). **Disponible = Medido − Comprometido.** *Medido* es la última medición física "
               "del tanque; *comprometido* es lo designado en despachos **confirmados** que "
               "aún no pesaron todos sus contenedores (se libera solo al completarse).")

    # ---------- 0 · vista rápida por calidad (AFE y AG-E) ----------
    _vista_rapida(d)

    # ---------- 1 · resumen por producto·calidad ----------
    st.markdown("##### 1 · Resumen por producto · calidad")
    res = (d.groupby("prod_cal")
             .agg(Tanques=("id_tanque", "count"),
                  medido_l=("medido_l", "sum"), comp_l=("comp_l", "sum"),
                  disp_l=("disp_l", "sum"), medido_t=("medido_t", "sum"),
                  comp_t=("comp_t", "sum"), disp_t=("disp_t", "sum"))
             .reset_index().sort_values("medido_t", ascending=False))
    res["% compr."] = (100.0 * res["comp_l"] / res["medido_l"].replace(0, pd.NA)).fillna(0.0)
    res = res.rename(columns={"prod_cal": "Producto · calidad",
                              "medido_l": "Medido (kL)", "comp_l": "Comprometido (kL)",
                              "disp_l": "Disponible (kL)", "medido_t": "Medido (t)",
                              "comp_t": "Comprometido (t)", "disp_t": "Disponible (t)"})
    _colres = ["Producto · calidad", "Tanques", "Medido (kL)", "Comprometido (kL)",
               "Disponible (kL)", "Medido (t)", "Comprometido (t)", "Disponible (t)",
               "% compr."]
    _tot = {"Producto · calidad": "TOTAL", "Tanques": int(res["Tanques"].sum())}
    for _c in _colres[2:]:
        _tot[_c] = float(res[_c].sum()) if _c != "% compr." else (
            100.0 * res["Comprometido (kL)"].sum() / max(res["Medido (kL)"].sum(), 1e-9))
    res_v = pd.concat([res[_colres], pd.DataFrame([_tot])], ignore_index=True)
    st.dataframe(res_v, hide_index=True, use_container_width=True,
                 column_config={
                     "Medido (kL)": st.column_config.NumberColumn(format="%.2f"),
                     "Comprometido (kL)": st.column_config.NumberColumn(format="%.2f"),
                     "Disponible (kL)": st.column_config.NumberColumn(format="%.2f"),
                     "Medido (t)": st.column_config.NumberColumn(format="%.1f"),
                     "Comprometido (t)": st.column_config.NumberColumn(format="%.1f"),
                     "Disponible (t)": st.column_config.NumberColumn(format="%.1f"),
                     "% compr.": st.column_config.ProgressColumn(
                         "% comprometido", format="%.0f%%", min_value=0, max_value=100)},
                 height=min(38 * (len(res_v) + 1) + 6, 460))

    # ---------- 2 · detalle por tanque ----------
    st.markdown("##### 2 · Detalle: en qué tanque está cada producto")
    det = d.sort_values(["prod_cal", "medido_l"], ascending=[True, False]).copy()
    det["ultima_medicion"] = pd.to_datetime(det["ultima_medicion"], errors="coerce", utc=True)
    try:
        det["ultima_medicion"] = (det["ultima_medicion"]
                                  .dt.tz_convert("America/Argentina/Buenos_Aires")
                                  .dt.tz_localize(None))
    except Exception:
        pass
    det_v = det.rename(columns={
        "prod_cal": "Producto · calidad", "nombre": "Tanque", "sector": "Sector",
        "medido_l": "Medido (kL)", "comp_l": "Comprometido (kL)", "disp_l": "Disponible (kL)",
        "medido_t": "Medido (t)", "disp_t": "Disponible (t)",
        "capacidad_litros": "Capacidad (kL)", "despachos": "Comprometido en",
        "acidez": "Acidez %", "fosforo": "Fósforo ppm", "azufre": "Azufre ppm",
        "agua_sedimento": "AyS %", "ultima_medicion": "Últ. medición",
        "fuente_medicion": "Medidor", "condicion": "Condición",
        "densidad": "Dens.", "densidad_fuente": "Dens. fuente"})
    _coldet = ["Producto · calidad", "Tanque", "Sector", "Medido (kL)", "Comprometido (kL)",
               "Disponible (kL)", "Medido (t)", "Disponible (t)", "Dens.", "Dens. fuente",
               "Capacidad (kL)",
               "Comprometido en", "Acidez %", "Fósforo ppm", "Azufre ppm", "AyS %",
               "Medidor", "Últ. medición", "Condición"]
    st.dataframe(det_v[_coldet], hide_index=True, use_container_width=True,
                 column_config={
                     "Medido (kL)": st.column_config.NumberColumn(format="%.2f"),
                     "Comprometido (kL)": st.column_config.NumberColumn(format="%.2f"),
                     "Disponible (kL)": st.column_config.NumberColumn(format="%.2f"),
                     "Medido (t)": st.column_config.NumberColumn(format="%.2f"),
                     "Disponible (t)": st.column_config.NumberColumn(format="%.2f"),
                     "Dens.": st.column_config.NumberColumn(
                         format="%.3f", help="kg/L usados para pasar de kL a t."),
                     "Dens. fuente": st.column_config.TextColumn(
                         "Dens. fuente", width="small",
                         help="lab = densidad medida del tanque · maestro = la del producto "
                              "en el maestro · default = 0,91 (sin dato)."),
                     "Capacidad (kL)": st.column_config.NumberColumn(format="%.0f"),
                     "Acidez %": st.column_config.NumberColumn(format="%.2f"),
                     "Fósforo ppm": st.column_config.NumberColumn(format="%.1f"),
                     "Azufre ppm": st.column_config.NumberColumn(format="%.1f"),
                     "AyS %": st.column_config.NumberColumn(format="%.2f"),
                     "Comprometido en": st.column_config.TextColumn(
                         "Comprometido en", width="medium",
                         help="Despachos confirmados que retienen ese stock."),
                     "Últ. medición": st.column_config.DatetimeColumn(format="DD/MM/YY HH:mm")},
                 height=min(38 * (len(det_v) + 1) + 6, 520))

    # ---------- 3 · comprometido por despacho ----------
    desp_v = pd.DataFrame()
    if dc is not None and not dc.empty:
        _ids = set(int(x) for x in d["id_tanque"])
        _dc = dc[dc["id_tanque"].astype(int).isin(_ids)].copy()
        if not _dc.empty:
            _pm = d.set_index("id_tanque")["prod_cal"].to_dict()
            _nm = d.set_index("id_tanque")["nombre"].to_dict()
            _dc["Producto · calidad"] = _dc["id_tanque"].map(lambda i: _pm.get(int(i), "—"))
            _dc["Tanque"] = _dc["id_tanque"].map(lambda i: _nm.get(int(i), str(i)))
            st.markdown("##### 3 · Comprometido por despacho — **cuánto retiene cada uno**")
            _dc["_t"] = _dc.apply(
                lambda r: float(r["litros"]) * float(
                    d.set_index("id_tanque")["densidad"].get(int(r["id_tanque"]), 0.91)), axis=1)
            porde = (_dc.groupby(["id_despacho", "titulo", "cliente", "fecha_despacho"])
                        .agg(kL=("litros", "sum"), Toneladas=("_t", "sum"),
                             Tanques=("id_tanque", "nunique"),
                             _tk=("n_tickets", "max"), _cont=("n_contenedores", "max"))
                        .reset_index().sort_values("kL", ascending=False))
            porde["Productos"] = porde["id_despacho"].map(
                lambda i: " · ".join(sorted(set(
                    _dc[_dc["id_despacho"] == i]["id_tanque"]
                    .map(lambda t: d.set_index("id_tanque")["prod_cal"].get(int(t), "—"))))))
            porde["Avance"] = porde.apply(
                lambda r: "%d/%d tickets" % (int(r["_tk"] or 0), int(r["_cont"] or 0)), axis=1)
            porde["Falta"] = porde.apply(
                lambda r: max(0, int(r["_cont"] or 0) - int(r["_tk"] or 0)), axis=1)
            porde = porde.rename(columns={"id_despacho": "Despacho", "titulo": "Título",
                                          "cliente": "Cliente",
                                          "fecha_despacho": "Fecha"})
            _colpd = ["Despacho", "Título", "Cliente", "Fecha", "kL", "Toneladas",
                      "Tanques", "Productos", "Avance", "Falta"]
            _totpd = {"Despacho": "TOTAL", "Título": "", "Cliente": "", "Fecha": None,
                      "kL": float(porde["kL"].sum()),
                      "Toneladas": float(porde["Toneladas"].sum()),
                      "Tanques": int(porde["Tanques"].sum()), "Productos": "",
                      "Avance": "", "Falta": int(porde["Falta"].sum())}
            porde_v = pd.concat([porde[_colpd], pd.DataFrame([_totpd])], ignore_index=True)
            st.dataframe(porde_v, hide_index=True, use_container_width=True,
                         column_config={
                             "kL": st.column_config.NumberColumn(format="%.2f"),
                             "Toneladas": st.column_config.NumberColumn(format="%.2f"),
                             "Fecha": st.column_config.DateColumn(format="DD/MM/YY"),
                             "Falta": st.column_config.NumberColumn(
                                 "Faltan pesar", format="%d",
                                 help="Contenedores que faltan pesar. Cuando llega a 0, ese "
                                      "despacho libera todo el stock que retiene.")})
            st.caption("**Cuánto retiene cada despacho.** Mientras le falte pesar aunque sea un "
                       "contenedor, retiene el 100% de sus líneas. Al completar los tickets en "
                       "*Despachos → Tickets de portería*, ese stock vuelve a estar disponible.")
            st.markdown("**Apertura despacho × tanque**")
            desp_v = _dc.rename(columns={
                "id_despacho": "Despacho", "titulo": "Título", "cliente": "Cliente",
                "destino": "Destino", "fecha_despacho": "Fecha", "litros": "kL",
                "estado": "Estado"})
            desp_v["Avance"] = desp_v.apply(
                lambda r: "%d/%d tickets" % (int(r["n_tickets"] or 0),
                                             int(r["n_contenedores"] or 0)), axis=1)
            desp_v = desp_v[["Producto · calidad", "Despacho", "Título", "Cliente", "Destino",
                             "Fecha", "Tanque", "kL", "Avance", "Estado"]] \
                .sort_values(["Producto · calidad", "Despacho", "kL"],
                             ascending=[True, True, False])
            st.dataframe(desp_v, hide_index=True, use_container_width=True,
                         column_config={
                             "kL": st.column_config.NumberColumn(format="%.2f"),
                             "Fecha": st.column_config.DateColumn(format="DD/MM/YY"),
                             "Avance": st.column_config.TextColumn(
                                 "Avance", help="Contenedores ya pesados en portería sobre el "
                                                "total: al completarse, el stock se libera.")})
            st.caption("Estos litros están **en el tanque** pero ya tienen dueño: no se pueden "
                       "usar para una orden de venta nueva.")

    # ---------- descargas ----------
    st.divider()
    st.markdown("##### ⬇️ Descargar")
    _hoy = pd.Timestamp.today().strftime("%Y%m%d")
    _porde = locals().get("porde_v")
    _bandas = pd.concat(
        [(st.session_state.get("_ifs_bandas_%s" % _t2, pd.DataFrame()).assign(Producto=_t2))
         for _t2 in ("AFE-S", "AG-E")], ignore_index=True) \
        if any(st.session_state.get("_ifs_bandas_%s" % _t2) is not None
               for _t2 in ("AFE-S", "AG-E")) else pd.DataFrame()
    if not _bandas.empty:
        _bandas = _bandas[["Producto", "Banda", "Tanques", "Medido (kL)", "Medido (t)",
                           "% del total", "Comprometido (kL)", "Disponible (kL)", "Acidez %",
                           "Fósforo ppm", "Azufre ppm", "AyS %", "En qué tanques"]]
    c1, c2, c3 = st.columns(3)
    try:
        c1.download_button("📊 Excel completo",
                           _excel(res_v, det_v[_coldet], desp_v, _porde, _bandas),
                           file_name="stock_producto_calidad_%s.xlsx" % _hoy,
                           mime="application/vnd.openxmlformats-officedocument."
                                "spreadsheetml.sheet",
                           use_container_width=True, type="primary")
    except Exception as e:
        c1.caption("No se pudo generar el Excel: %s" % e)
    c2.download_button("⬇️ Resumen (CSV)", res_v.to_csv(index=False).encode("utf-8-sig"),
                       file_name="stock_resumen_%s.csv" % _hoy, mime="text/csv",
                       use_container_width=True)
    c3.download_button("⬇️ Detalle por tanque (CSV)",
                       det_v[_coldet].to_csv(index=False).encode("utf-8-sig"),
                       file_name="stock_detalle_%s.csv" % _hoy, mime="text/csv",
                       use_container_width=True)

    if not _bandas.empty:
        try:
            st.download_button("🖼️ PNG · Stock por calidad (AFE-S y AG-E)",
                               _png(_bandas.drop(columns=["En qué tanques"]),
                                    "Stock por calidad"),
                               file_name="stock_por_calidad_%s.png" % _hoy, mime="image/png")
        except Exception as e:
            st.caption("No se pudo generar la imagen de calidad: %s" % e)
    p1, p2, p3 = st.columns(3)
    try:
        p1.download_button("🖼️ PNG · Resumen", _png(res_v, "Stock por producto y calidad"),
                           file_name="stock_resumen_%s.png" % _hoy, mime="image/png",
                           use_container_width=True)
    except Exception as e:
        p1.caption("No se pudo generar la imagen: %s" % e)
    if _porde is not None and not _porde.empty:
        try:
            p2.download_button("🖼️ PNG · Por despacho",
                               _png(_porde, "Stock comprometido por despacho"),
                               file_name="comprometido_despacho_%s.png" % _hoy,
                               mime="image/png", use_container_width=True)
        except Exception as e:
            p2.caption("No se pudo generar la imagen: %s" % e)
    try:
        _cold_png = ["Producto · calidad", "Tanque", "Medido (kL)", "Comprometido (kL)",
                     "Disponible (kL)", "Comprometido en"]
        p3.download_button("🖼️ PNG · Detalle por tanque",
                           _png(det_v[_cold_png], "Stock por tanque"),
                           file_name="stock_detalle_%s.png" % _hoy, mime="image/png",
                           use_container_width=True)
    except Exception as e:
        p3.caption("No se pudo generar la imagen: %s" % e)
    st.caption("El **Excel** trae las hojas: Resumen, Por calidad (banda), Detalle por tanque, "
               "Por despacho y Despacho × tanque. Los **PNG** son para pegar en un mensaje o informe (las "
               "primeras 45 filas). Los CSV usan codificación compatible con Excel en español.")
