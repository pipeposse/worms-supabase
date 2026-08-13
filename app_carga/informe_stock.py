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


def _n(v, dec=0):
    try:
        if v is None or pd.isna(v):
            return "—"
        return ("{:,.%df}" % dec).format(float(v))
    except Exception:
        return "—"


def _datos(cat):
    """Tanques con medido/comprometido/disponible + a qué despachos está comprometido."""
    tk = cat("SELECT id_tanque, nombre, sector, producto_principal, capacidad_litros, "
             "COALESCE(litros_actual,0) AS medido_l, COALESCE(kg_actual,0) AS medido_kg, "
             "COALESCE(litros_comprometido,0) AS comp_l, "
             "COALESCE(densidad,0.91) AS densidad, ultima_medicion, fuente_medicion, "
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
            _dec = 1 if ("(t)" in str(c) or "%" in str(c)) else 0
            x[c] = x[c].map(lambda v: _n(v, _dec))
        else:
            x[c] = x[c].astype(str).str.slice(0, 42)
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


def _excel(res, det, desp, porde=None):
    buf = _io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        res.to_excel(w, sheet_name="Resumen", index=False)
        det.to_excel(w, sheet_name="Detalle por tanque", index=False)
        if porde is not None and not porde.empty:
            porde.to_excel(w, sheet_name="Por despacho", index=False)
        if desp is not None and not desp.empty:
            desp.to_excel(w, sheet_name="Despacho x tanque", index=False)
        for _sh, _df in (("Resumen", res), ("Detalle por tanque", det),
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


def render(USR, cat, conectar=None):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#1e3a8a,#0891b2);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>📦 Informe de stock por "
        "producto y calidad</div>"
        "<div style='color:#e0f2fe;font-size:.88rem;margin-top:3px'>Qué hay de cada producto, "
        "en qué tanque, cuánto está comprometido en despachos y cuánto queda realmente "
        "disponible.</div></div>", unsafe_allow_html=True)
    if USR.get("rol") not in ROLES_DIRECCION and "PLANIFICACION" not in (USR.get("secciones_app") or []):
        st.warning("Sección exclusiva de dirección.")
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
    tk["prod_cal"] = tk["producto_principal"].astype(str).str.strip()

    # a qué despachos está comprometido cada tanque (texto compacto)
    _por_tk = {}
    if dc is not None and not dc.empty:
        dc = dc.copy()
        dc["litros"] = pd.to_numeric(dc["litros"], errors="coerce").fillna(0.0)
        for _t, _g in dc.groupby("id_tanque"):
            _por_tk[int(_t)] = " · ".join(
                "#%d %s (%s L)" % (int(r["id_despacho"]), str(r["titulo"] or "—"),
                                   _n(r["litros"]))
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
              "%s L" % _n(d["medido_l"].sum()))
    k2.metric("🔒 Comprometido", "%s t" % _n(d["comp_t"].sum(), 1),
              "%s L" % _n(d["comp_l"].sum()),
              help="En despachos confirmados que todavía no terminaron de pesar.")
    k3.metric("✅ Disponible", "%s t" % _n(d["disp_t"].sum(), 1),
              "%s L" % _n(d["disp_l"].sum()))
    k4.metric("Productos · tanques", "%d · %d" % (d["prod_cal"].nunique(), len(d)))
    st.caption("**Disponible = Medido − Comprometido.** *Medido* es la última medición física "
               "del tanque; *comprometido* es lo designado en despachos **confirmados** que "
               "aún no pesaron todos sus contenedores (se libera solo al completarse).")

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
                              "medido_l": "Medido (L)", "comp_l": "Comprometido (L)",
                              "disp_l": "Disponible (L)", "medido_t": "Medido (t)",
                              "comp_t": "Comprometido (t)", "disp_t": "Disponible (t)"})
    _colres = ["Producto · calidad", "Tanques", "Medido (L)", "Comprometido (L)",
               "Disponible (L)", "Medido (t)", "Comprometido (t)", "Disponible (t)",
               "% compr."]
    _tot = {"Producto · calidad": "TOTAL", "Tanques": int(res["Tanques"].sum())}
    for _c in _colres[2:]:
        _tot[_c] = float(res[_c].sum()) if _c != "% compr." else (
            100.0 * res["Comprometido (L)"].sum() / max(res["Medido (L)"].sum(), 1e-9))
    res_v = pd.concat([res[_colres], pd.DataFrame([_tot])], ignore_index=True)
    st.dataframe(res_v, hide_index=True, use_container_width=True,
                 column_config={
                     "Medido (L)": st.column_config.NumberColumn(format="%.0f"),
                     "Comprometido (L)": st.column_config.NumberColumn(format="%.0f"),
                     "Disponible (L)": st.column_config.NumberColumn(format="%.0f"),
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
        "medido_l": "Medido (L)", "comp_l": "Comprometido (L)", "disp_l": "Disponible (L)",
        "medido_t": "Medido (t)", "disp_t": "Disponible (t)",
        "capacidad_litros": "Capacidad (L)", "despachos": "Comprometido en",
        "acidez": "Acidez %", "fosforo": "Fósforo ppm", "azufre": "Azufre ppm",
        "agua_sedimento": "AyS %", "ultima_medicion": "Últ. medición",
        "fuente_medicion": "Medidor", "condicion": "Condición"})
    _coldet = ["Producto · calidad", "Tanque", "Sector", "Medido (L)", "Comprometido (L)",
               "Disponible (L)", "Medido (t)", "Disponible (t)", "Capacidad (L)",
               "Comprometido en", "Acidez %", "Fósforo ppm", "Azufre ppm", "AyS %",
               "Medidor", "Últ. medición", "Condición"]
    st.dataframe(det_v[_coldet], hide_index=True, use_container_width=True,
                 column_config={
                     "Medido (L)": st.column_config.NumberColumn(format="%.0f"),
                     "Comprometido (L)": st.column_config.NumberColumn(format="%.0f"),
                     "Disponible (L)": st.column_config.NumberColumn(format="%.0f"),
                     "Medido (t)": st.column_config.NumberColumn(format="%.2f"),
                     "Disponible (t)": st.column_config.NumberColumn(format="%.2f"),
                     "Capacidad (L)": st.column_config.NumberColumn(format="%.0f"),
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
                    d.set_index("id_tanque")["densidad"].get(int(r["id_tanque"]), 0.91)), axis=1) / 1000.0
            porde = (_dc.groupby(["id_despacho", "titulo", "cliente", "fecha_despacho"])
                        .agg(Litros=("litros", "sum"), Toneladas=("_t", "sum"),
                             Tanques=("id_tanque", "nunique"),
                             _tk=("n_tickets", "max"), _cont=("n_contenedores", "max"))
                        .reset_index().sort_values("Litros", ascending=False))
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
            _colpd = ["Despacho", "Título", "Cliente", "Fecha", "Litros", "Toneladas",
                      "Tanques", "Productos", "Avance", "Falta"]
            _totpd = {"Despacho": "TOTAL", "Título": "", "Cliente": "", "Fecha": None,
                      "Litros": float(porde["Litros"].sum()),
                      "Toneladas": float(porde["Toneladas"].sum()),
                      "Tanques": int(porde["Tanques"].sum()), "Productos": "",
                      "Avance": "", "Falta": int(porde["Falta"].sum())}
            porde_v = pd.concat([porde[_colpd], pd.DataFrame([_totpd])], ignore_index=True)
            st.dataframe(porde_v, hide_index=True, use_container_width=True,
                         column_config={
                             "Litros": st.column_config.NumberColumn(format="%.0f"),
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
                "destino": "Destino", "fecha_despacho": "Fecha", "litros": "Litros",
                "estado": "Estado"})
            desp_v["Avance"] = desp_v.apply(
                lambda r: "%d/%d tickets" % (int(r["n_tickets"] or 0),
                                             int(r["n_contenedores"] or 0)), axis=1)
            desp_v = desp_v[["Producto · calidad", "Despacho", "Título", "Cliente", "Destino",
                             "Fecha", "Tanque", "Litros", "Avance", "Estado"]] \
                .sort_values(["Producto · calidad", "Despacho", "Litros"],
                             ascending=[True, True, False])
            st.dataframe(desp_v, hide_index=True, use_container_width=True,
                         column_config={
                             "Litros": st.column_config.NumberColumn(format="%.0f"),
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
    c1, c2, c3 = st.columns(3)
    try:
        c1.download_button("📊 Excel completo (4 hojas)",
                           _excel(res_v, det_v[_coldet], desp_v, _porde),
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
        _cold_png = ["Producto · calidad", "Tanque", "Medido (L)", "Comprometido (L)",
                     "Disponible (L)", "Comprometido en"]
        p3.download_button("🖼️ PNG · Detalle por tanque",
                           _png(det_v[_cold_png], "Stock por tanque"),
                           file_name="stock_detalle_%s.png" % _hoy, mime="image/png",
                           use_container_width=True)
    except Exception as e:
        p3.caption("No se pudo generar la imagen: %s" % e)
    st.caption("El **Excel** trae cuatro hojas: Resumen, Detalle por tanque, Por despacho y "
               "Despacho × tanque. Los **PNG** son para pegar en un mensaje o informe (las "
               "primeras 45 filas). Los CSV usan codificación compatible con Excel en español.")
