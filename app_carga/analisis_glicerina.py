# -*- coding: utf-8 -*-
"""Análisis Glicerina (Centro de Planificación) — todos los ingresos de glicerina,
camión por camión. Mismo concepto que Análisis AFE:

  - Tabla por día y por camión con los parámetros del lab (glicerol, MONG, AyS,
    humedad, ceniza), tipo (fresca/recuperada), calidad A–D y descuento aplicado;
    filtrable por fecha, semana, origen y clase; Excel y PNG.
  - Resumen de TN por calidad y por tipo.
  - Camiones rechazados en su propia sección (fuera del análisis).
  - Glicerinas SIN analizar por laboratorio, con carga rápida de parámetros
    (escribe en produccion.lab_evaluaciones, el mismo canal que usa Laboratorio).

El glicerol viene con unidades mezcladas (fracción o %): valores <= 1 se toman
como fracción (×100) — la misma regla que usa el trigger de parámetros de tanque.
"""
import io as _io

import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")
_DIAS = {0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves", 4: "viernes", 5: "sábado", 6: "domingo"}
CAL_GLI_OPTS = ["", "A", "B", "C", "D"]
CAL_LBL = {"A": "A (fresca)", "B": "B (fresca)", "C": "C (recuperada)", "D": "D (FE)"}
TIPOS_GLI = ["", "FRESCA", "RECUPERADA"]


def _cal_params(glicerol, sedimento):
    """Calidad DESDE LOS PARÁMETROS — esto es lo que manda, más allá de la letra
    que haya tipeado el laboratorio: A >80 · B 70–80 · C 60–80 con sedimento ≤10 ·
    D sed>10 o ≤60. None si no hay glicerol medido."""
    try:
        g = float(glicerol)
    except (TypeError, ValueError):
        return None
    if pd.isna(g):
        return None
    if g > 80:
        return "A"
    if g > 70:
        return "B"
    if g > 60:
        try:
            sd = float(sedimento)
        except (TypeError, ValueError):
            sd = None
        if sd is not None and not pd.isna(sd) and sd > 10:
            return "D"
        return "C"
    return "D"


def _cal_norm(cal, tipo, glicerol):
    """Toda calidad se lleva a la letra A/B/C/D (idioma único con el laboratorio).

    Legacy: F/E y FUERA DE ESPECIFICACIÓN son la actual D (FE); EN ESPECIFICACIÓN
    y UNICA se derivan del tipo (RECUPERADA→C) o del glicerol según el maestro."""
    c = str(cal or "").strip().upper()
    if c in ("A", "B", "C", "D"):
        return c
    if c.startswith("F/E") or c.startswith("FUERA"):
        return "D"
    if not c:
        return None
    t = str(tipo or "").strip().upper()
    if t == "RECUPERADA":
        return "C"
    try:
        g = float(glicerol)
    except (TypeError, ValueError):
        return None
    if pd.isna(g):
        return None
    if g > 80:
        return "A"
    if g > 70:
        return "B"
    if g > 60:
        return "C"
    return "D"
_CLASE_LBL = {"INGRESO": "Ingreso", "OTRO": "Compra", "INTERNO": "Interno"}


def _norm_glicerol(v):
    if v is None or pd.isna(v):
        return None
    v = float(v)
    if v <= 1.0:
        v = v * 100.0
    return v if v <= 100.0 else None


def _datos(cat, d1, d2):
    df = cat(
        "SELECT p.id_transaccion, p.fecha, to_char(p.fecha,'IYYY·\"S\"IW') AS semana, "
        "COALESCE(p.procedencia,'—') AS proveedor, p.ticket, abs(p.kg) AS kg, "
        "p.producto, p.clase, "
        "l.gli_glicerol, l.gli_ays, l.gli_mong, l.gli_humedad, l.gli_ceniza, l.gli_tipo, "
        "l.prc_sedimentos, "
        "l.calidad_final_lab, l.rechazado, l.conclusion, l.patente_chasis, l.empleado, "
        "l.descuento_pct "
        "FROM produccion.v_porteria_ticket p "
        "LEFT JOIN LATERAL (SELECT pl.gli_glicerol, pl.gli_ays, pl.gli_mong, pl.gli_humedad, "
        "         pl.gli_ceniza, pl.gli_tipo, pl.prc_sedimentos, pl.calidad_final_lab, "
        "         pl.rechazado, pl.conclusion, pl.patente_chasis, pl.empleado, pl.descuento_pct "
        "  FROM produccion.procesos_lab pl "
        "  WHERE btrim(pl.ticket)=p.ticket::text AND COALESCE(pl.anulado,false)=false "
        "  ORDER BY (upper(COALESCE(pl.producto_lab,'')) LIKE '%%GLICER%%') DESC, "
        "           pl.fecha DESC NULLS LAST LIMIT 1) l ON true "
        "WHERE upper(COALESCE(p.producto,'')) LIKE '%%GLICER%%' AND p.kg IS NOT NULL "
        "AND p.fecha BETWEEN %s AND %s", (d1, d2))
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    for _c in ("kg", "gli_glicerol", "gli_ays", "gli_mong", "gli_humedad", "gli_ceniza",
               "prc_sedimentos", "descuento_pct"):
        df[_c] = pd.to_numeric(df[_c], errors="coerce")
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["dia"] = df["fecha"].dt.dayofweek.map(_DIAS)
    df["glicerol"] = [_norm_glicerol(v) for v in df["gli_glicerol"]]
    df["clase"] = df["clase"].astype(str).map(lambda c: _CLASE_LBL.get(c, c))
    df["tipo"] = (df["gli_tipo"].astype(str).str.upper().str.strip()
                  .map(lambda t: t if t in ("FRESCA", "RECUPERADA") else None))
    df["tiene_lab"] = (pd.Series(df["glicerol"]).notna() | df["gli_mong"].notna()
                       | df["gli_ays"].notna() | df["calidad_final_lab"].notna())
    # LA CALIDAD LA DEFINEN LOS PARÁMETROS (glicerol + sedimento). La letra del
    # lab vale de respaldo cuando no hay parámetros y de contraste cuando sí los
    # hay: si no coincide, discrepa=True y la fila se marca. "FE" ya no es
    # rechazo sino la calidad D — rechazado es sólo lo que el lab marcó RECHAZADO.
    df["cal_param"] = [_cal_params(g, sd) for g, sd in
                       zip(df["glicerol"], df["prc_sedimentos"])]
    df["cal_lab"] = [_cal_norm(c, t, g) for c, t, g in
                     zip(df["calidad_final_lab"], df["gli_tipo"], df["glicerol"])]
    df["cal"] = df["cal_param"].where(df["cal_param"].notna(), df["cal_lab"])
    df["discrepa"] = (df["cal_param"].notna() & df["cal_lab"].notna()
                      & (df["cal_param"] != df["cal_lab"]))
    df["cal_lbl"] = df["cal"].map(CAL_LBL)
    _re = df["rechazado"].astype(str).str.upper().str.strip()
    df["es_rechazado"] = _re.str.startswith("RECHAZ")
    return df


def _tabla_vista(df):
    v = df.sort_values("fecha", ascending=False).copy()
    v["Lab"] = v["tiene_lab"].map({True: "✅", False: "❌ sin lab"})
    v["tn"] = (v["kg"] / 1000.0).round(2)
    v["Tipo"] = v["tipo"].map(lambda t: t.lower() if isinstance(t, str) else "—")
    v["Calidad"] = [
        ((CAL_LBL.get(c, c) + (" ⚠️" if d else "")) if pd.notna(c)
         else ("s/clasificar" if t else "—"))
        for c, d, t in zip(v["cal"], v["discrepa"], v["tiene_lab"])]
    v = v.rename(columns={"fecha": "Fecha", "dia": "Día", "semana": "Semana",
                          "proveedor": "Origen", "ticket": "Ticket", "clase": "Clase",
                          "tn": "TN", "glicerol": "Glicerol %", "gli_ays": "AyS %",
                          "gli_mong": "MONG %", "gli_humedad": "Humedad %",
                          "gli_ceniza": "Ceniza %", "descuento_pct": "Descuento %"})
    return v[["Fecha", "Día", "Semana", "Origen", "Ticket", "Clase", "TN", "Tipo",
              "Glicerol %", "MONG %", "AyS %", "Humedad %", "Ceniza %", "Calidad",
              "Descuento %", "Lab"]]


def _excel_bytes(v, hoja="Glicerinas"):
    buf = _io.BytesIO()
    x = v.copy()
    if "Fecha" in x.columns:
        x["Fecha"] = pd.to_datetime(x["Fecha"]).dt.strftime("%d/%m/%Y")
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        x.to_excel(w, sheet_name=hoja, index=False)
        ws = w.sheets[hoja]
        for i, c in enumerate(x.columns):
            if i < 26:
                ws.column_dimensions[chr(65 + i)].width = max(
                    12, min(28, int(x[c].astype(str).str.len().max() or 10) + 2))
    return buf.getvalue()


def _imagen_bytes(v, max_filas=60):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = v.head(max_filas).copy()
    x["Fecha"] = pd.to_datetime(x["Fecha"]).dt.strftime("%d/%m")
    for c in ("Glicerol %", "MONG %", "AyS %", "Humedad %", "Ceniza %", "Descuento %"):
        if c in x.columns:
            x[c] = x[c].map(lambda z: ("%.1f" % z) if pd.notna(z) else "—")
    x["TN"] = x["TN"].map(lambda z: ("%.2f" % z) if pd.notna(z) else "—")
    x = x.fillna("—").astype(str)
    fig, ax = plt.subplots(figsize=(14, 0.32 * (len(x) + 2) + 1))
    ax.axis("off")
    tb = ax.table(cellText=x.values, colLabels=list(x.columns), loc="center", cellLoc="center")
    tb.auto_set_font_size(False)
    tb.set_fontsize(7.5)
    tb.scale(1, 1.25)
    for j in range(len(x.columns)):
        tb[0, j].set_facecolor("#7c2d92")
        tb[0, j].set_text_props(color="white", fontweight="bold")
    ax.set_title("Glicerinas ingresadas — parámetros por camión",
                 fontsize=11, fontweight="bold", pad=8)
    buf = _io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _brief_calidades():
    """Mini brief de las 4 calidades según la convención acordada con el laboratorio.
    OJO: el HTML va en UNA sola línea — con saltos e indentación, st.markdown lo
    renderiza como bloque de código."""
    _cards = [
        ("A", "fresca", "#15803d", "Glicerol &gt; 80 %"),
        ("B", "fresca", "#0369a1", "Glicerol 70–80 %"),
        ("C", "recuperada", "#b45309", "Glicerol 60–80 % · sedimento ≤ 10 %"),
        ("D", "FE · fuera de spec", "#b91c1c", "Sedimento &gt; 10 % o glicerol ≤ 60 %"),
    ]
    _h = "".join(
        "<div style='flex:1;min-width:150px;background:%s0d;border:1px solid %s44;"
        "border-left:5px solid %s;border-radius:10px;padding:7px 12px'>"
        "<span style='font-weight:900;color:%s;font-size:1rem'>%s</span>"
        "<span style='color:#475569;font-size:.8rem'> (%s)</span>"
        "<div style='color:#0f172a;font-size:.8rem;margin-top:2px'>%s</div></div>"
        % (c, c, c, c, l, t, p) for l, t, c, p in _cards)
    _html = ("<div style='display:flex;gap:8px;flex-wrap:wrap;margin:0 0 10px'>" + _h + "</div>"
             "<div style='color:#64748b;font-size:.76rem;margin:-4px 0 10px'>Convención única "
             "con laboratorio (maestro de productos): la calidad la definen el <b>% de "
             "glicerol</b> y el <b>sedimento</b>; el tipo (fresca / recuperada) acompaña "
             "entre paréntesis. D = la vieja «FE / fuera de especificación» — descarga "
             "igual, pero con descuento. <b>Mandan los parámetros:</b> si la letra que "
             "cargó el lab no coincide con glicerol/sedimento, la sección clasifica por "
             "parámetros y marca la fila con ⚠️.</div>")
    assert "\n" not in _html
    st.markdown(_html, unsafe_allow_html=True)


def render(USR, cat, conectar):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#581c87,#9d174d);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>🧪 Análisis Glicerina</div>"
        "<div style='color:#fbcfe8;font-size:.88rem;margin-top:3px'>Cada ingreso de glicerina, "
        "con su glicerol, MONG, AyS, tipo y calidad — y los que laboratorio todavía no midió."
        "</div></div>", unsafe_allow_html=True)
    if USR.get("rol") not in ROLES_DIRECCION and "PLANIFICACION" not in (USR.get("secciones_app") or []):
        st.warning("Sección exclusiva de dirección.")
        return

    _brief_calidades()

    hoy = pd.Timestamp.today().date()
    f1, f2, f3, f4 = st.columns([1, 1, 1.3, 1.3])
    d1 = f1.date_input("Desde", hoy - pd.Timedelta(days=90), key="agli_d1", format="DD/MM/YYYY")
    d2 = f2.date_input("Hasta", hoy, key="agli_d2", format="DD/MM/YYYY")
    df = _datos(cat, d1, d2)
    if df.empty:
        st.info("No hay ingresos de glicerina en ese rango.")
        return
    _sems = sorted(df["semana"].unique().tolist(), reverse=True)
    f_sem = f3.multiselect("Semana", _sems, key="agli_sem")
    _provs = sorted(df["proveedor"].unique().tolist())
    f_prov = f4.multiselect("Origen", _provs, key="agli_prov")
    g1, g2 = st.columns([2.2, 1.8])
    with g1:
        f_lab = st.radio("Vista", ["Todos", "✅ Con análisis", "❌ Sin análisis", "🚫 Rechazados"],
                         horizontal=True, key="agli_lab")
    _clases = sorted(df["clase"].unique().tolist())
    f_cls = g2.multiselect("Clase de movimiento", _clases, key="agli_cls", placeholder="todas",
                           help="Compra = camión de afuera · Interno = movimiento interno de planta.")
    _nrech_tot = int(df["es_rechazado"].sum())
    if _nrech_tot:
        st.caption("🚫 %d camión(es) rechazado(s) en el rango elegido." % _nrech_tot)
    if f_sem:
        df = df[df["semana"].isin(f_sem)]
    if f_prov:
        df = df[df["proveedor"].isin(f_prov)]
    if f_cls:
        df = df[df["clase"].isin(f_cls)]
    if f_lab.startswith("✅"):
        df = df[df["tiene_lab"]]
    elif f_lab.startswith("❌"):
        df = df[~df["tiene_lab"]]
    if df.empty:
        st.info("Ningún ingreso cumple los filtros.")
        return

    if f_lab.startswith("🚫"):
        _seccion_rechazados(df[df["es_rechazado"]].copy(), d1, d2, solo=True)
        return

    _rech = df[df["es_rechazado"]].copy()
    df = df[~df["es_rechazado"]]
    if df.empty:
        st.warning("Con estos filtros **todos los ingresos están rechazados** (%d)." % len(_rech))
        _seccion_rechazados(_rech, d1, d2)
        return

    _fil = ["📅 %s → %s" % (d1.strftime("%d/%m/%y"), d2.strftime("%d/%m/%y"))]
    _fil.append("🗓️ " + (", ".join(f_sem) if f_sem else "todas las semanas del rango"))
    _fil.append("🚚 " + (", ".join(f_prov) if f_prov else "todos los orígenes (%d)"
                         % df["proveedor"].nunique()))
    if f_cls:
        _fil.append("📦 " + ", ".join(f_cls))
    if not f_lab.startswith("Todos"):
        _fil.append(f_lab)
    if len(_rech):
        _fil.append("🚫 sin los rechazados (%d)" % len(_rech))
    st.markdown("<div style='background:#faf5ff;border:1px solid #e9d5ff;border-radius:10px;"
                "padding:6px 12px;margin:2px 0 8px;font-size:.85rem;color:#581c87'>"
                "<b>KPIs calculados sobre:</b> " + " · ".join(_fil) + "</div>",
                unsafe_allow_html=True)

    _kg = float(df["kg"].sum())

    def _pond(col):
        d = df[pd.notna(df[col])]
        return (float((d[col] * d["kg"]).sum() / d["kg"].sum())
                if not d.empty and d["kg"].sum() > 0 else None)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Ingresos", len(df))
    k2.metric("Toneladas", "%.0f" % (_kg / 1000.0))
    k3.metric("Con lab", "%.0f %%" % (100.0 * df["tiene_lab"].mean()))
    _gp = _pond("glicerol")
    k4.metric("Glicerol pond.", ("%.1f %%" % _gp) if _gp is not None else "—",
              help="Promedio ponderado por kg del %% de glicerol de los ingresos con análisis.")
    _mp = _pond("gli_mong")
    k5.metric("MONG pond.", ("%.2f %%" % _mp) if _mp is not None else "—")

    # ---- resumen por calidad y por tipo
    r1, r2 = st.columns(2)
    _cal = df.copy()
    _cal["Calidad"] = _cal["cal_lbl"].where(
        _cal["cal_lbl"].notna(),
        _cal["tiene_lab"].map({True: "s/clasificar", False: "— sin lab"}))
    _byc = (_cal.groupby("Calidad")
                .agg(Ingresos=("ticket", "count"), TN=("kg", lambda s: round(s.sum() / 1000.0, 1)))
                .reset_index().sort_values("Calidad"))
    _byc["% del total"] = (100.0 * _byc["TN"] / max(_kg / 1000.0, 0.001)).round(0)
    r1.markdown("**TN por calidad** _(A y B fresca · C recuperada · D = FE, fuera de spec)_")
    r1.dataframe(_byc, hide_index=True, use_container_width=True)
    _tip = df.copy()
    _tip["Tipo"] = _tip["tipo"].fillna("— sin dato").str.lower()
    _byt = (_tip.groupby("Tipo")
                .agg(Ingresos=("ticket", "count"), TN=("kg", lambda s: round(s.sum() / 1000.0, 1)))
                .reset_index().sort_values("TN", ascending=False))
    r2.markdown("**TN por tipo** _(fresca / recuperada, según laboratorio)_")
    r2.dataframe(_byt, hide_index=True, use_container_width=True)

    _dis = df[df["discrepa"]]
    if not _dis.empty:
        st.warning("⚠️ **%d ticket(s) donde la letra del laboratorio NO coincide con los "
                   "parámetros.** Acá mandan los parámetros — corregí el registro del lab "
                   "para que todos hablemos el mismo idioma." % len(_dis))
        _dv = _dis.sort_values("fecha", ascending=False)
        _dv = pd.DataFrame({
            "Fecha": _dv["fecha"], "Ticket": _dv["ticket"].astype(str),
            "Origen": _dv["proveedor"],
            "Lab dice": _dv["cal_lab"].map(lambda c: CAL_LBL.get(c, c)),
            "Parámetros dicen": _dv["cal_param"].map(lambda c: CAL_LBL.get(c, c)),
            "Glicerol %": _dv["glicerol"], "Sedimento %": _dv["prc_sedimentos"]})
        st.dataframe(_dv, hide_index=True, use_container_width=True,
                     column_config={
                         "Fecha": st.column_config.DatetimeColumn(format="DD/MM/YY"),
                         "Glicerol %": st.column_config.NumberColumn(format="%.1f"),
                         "Sedimento %": st.column_config.NumberColumn(format="%.2f")})

    v = _tabla_vista(df)
    st.dataframe(v, hide_index=True, use_container_width=True,
                 column_config={
                     "Fecha": st.column_config.DatetimeColumn(format="DD/MM/YY"),
                     "TN": st.column_config.NumberColumn(format="%.2f"),
                     "Glicerol %": st.column_config.NumberColumn(format="%.1f"),
                     "MONG %": st.column_config.NumberColumn(format="%.2f"),
                     "AyS %": st.column_config.NumberColumn(format="%.2f"),
                     "Humedad %": st.column_config.NumberColumn(format="%.2f"),
                     "Ceniza %": st.column_config.NumberColumn(format="%.2f"),
                     "Calidad": st.column_config.TextColumn(
                         "Calidad", help="Definida por los PARÁMETROS (glicerol + sedimento). "
                                         "⚠️ = la letra que cargó el lab no coincide: mandan "
                                         "los parámetros."),
                     "Descuento %": st.column_config.NumberColumn(
                         format="%.1f", help="Descuento al precio del ticket por mala calidad "
                                             "(cargado por el lab o en 💸 Descuentos.")})
    st.caption("Glicerol normalizado (valores ≤ 1 se toman como fracción ×100).")

    b1, b2 = st.columns(2)
    b1.download_button("⬇️ Descargar Excel (.xlsx)", _excel_bytes(v),
                       file_name="glicerinas_%s_%s.xlsx" % (d1, d2),
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    try:
        _png = _imagen_bytes(v)
        b2.download_button("🖼️ Descargar imagen (PNG%s)" % (" · primeras 60 filas" if len(v) > 60 else ""),
                           _png, file_name="glicerinas_%s_%s.png" % (d1, d2), mime="image/png",
                           use_container_width=True)
    except Exception as _e:
        b2.caption("No se pudo generar la imagen: %s" % _e)

    st.markdown("---")
    _seccion_rechazados(_rech, d1, d2)

    st.markdown("---")
    render_sin_lab(USR, cat, conectar)


def _seccion_rechazados(r, d1, d2, solo=False):
    st.markdown(("### 🚫 Ingresos rechazados" if solo else "#### 🚫 Ingresos rechazados"))
    if r is None or r.empty:
        st.success("✅ Ningún ingreso de glicerina rechazado en el período y filtros elegidos.")
        return
    st.caption("Rechazados por laboratorio: quedan fuera del análisis de arriba, pero muestran "
               "qué origen está mandando glicerina fuera de especificación.")
    m1, m2, m3 = st.columns(3)
    m1.metric("Rechazados", int(len(r)))
    m2.metric("Orígenes", int(r["proveedor"].nunique()))
    _gm = r[pd.notna(r["glicerol"])]
    m3.metric("Glicerol medio", ("%.1f %%" % _gm["glicerol"].mean()) if not _gm.empty else "—")
    v = r.sort_values("fecha", ascending=False).copy()
    v["Motivo del lab"] = [str(c).strip() if (pd.notna(c) and str(c).strip()) else "— sin nota —"
                           for c in v["conclusion"]]
    v["tn"] = (v["kg"] / 1000.0).round(2)
    v["Calidad"] = v["cal_lbl"].fillna("s/clasificar")
    v = v.rename(columns={"fecha": "Fecha", "semana": "Semana", "proveedor": "Origen",
                          "ticket": "Ticket", "tn": "TN", "glicerol": "Glicerol %",
                          "gli_mong": "MONG %", "gli_ays": "AyS %",
                          "rechazado": "Estado",
                          "patente_chasis": "Patente", "empleado": "Analista"})
    _cols = [c for c in ["Fecha", "Semana", "Origen", "Ticket", "Patente", "TN", "Glicerol %",
                         "MONG %", "AyS %", "Calidad", "Estado", "Motivo del lab", "Analista"]
             if c in v.columns]
    st.dataframe(v[_cols], hide_index=True, use_container_width=True,
                 column_config={"Fecha": st.column_config.DatetimeColumn(format="DD/MM/YY"),
                                "Glicerol %": st.column_config.NumberColumn(format="%.1f"),
                                "MONG %": st.column_config.NumberColumn(format="%.2f"),
                                "AyS %": st.column_config.NumberColumn(format="%.2f")})
    try:
        st.download_button("⬇️ Descargar rechazados (.xlsx)", _excel_bytes(v[_cols], "Rechazados"),
                           file_name="glicerina_rechazados_%s_%s.xlsx" % (d1, d2),
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="agli_rech_dl")
    except Exception as _e:
        st.caption("No se pudo generar el Excel: %s" % _e)


def render_sin_lab(USR, cat, conectar, key="pl"):
    """Glicerinas sin análisis de laboratorio, con carga rápida (canal lab_evaluaciones)."""
    st.markdown("#### 🚨 Glicerinas sin analizar por laboratorio")
    st.caption("Sin análisis no hay calidad A–D ni tipo (fresca/recuperada), y el ingreso no se "
               "puede valorizar bien. Elegí un ingreso y cargá los parámetros acá mismo: queda "
               "como una evaluación de laboratorio normal (canal `lab_evaluaciones`).")
    hoy = pd.Timestamp.today().date()
    df = _datos(cat, hoy - pd.Timedelta(days=120), hoy)
    if df.empty:
        st.info("Sin ingresos de glicerina en los últimos 120 días.")
        return
    pend = df[~df["tiene_lab"]].copy()
    if pend.empty:
        st.success("✅ Todas las glicerinas de los últimos 120 días tienen análisis.")
        return
    c1, c2 = st.columns([1, 2])
    c1.metric("Sin lab (120 días)", int(len(pend)), "%.0f t" % (pend["kg"].sum() / 1000.0))
    _g = (pend.groupby("semana")
              .agg(ingresos=("ticket", "count"), t=("kg", lambda s: s.sum() / 1000.0))
              .reset_index().sort_values("semana", ascending=False))
    c2.dataframe(_g.rename(columns={"semana": "Semana", "ingresos": "Ingresos", "t": "t"}).round(1),
                 hide_index=True, use_container_width=True, height=160)

    pend = pend.sort_values("fecha", ascending=False)
    _lbl = {int(r["id_transaccion"]): "%s · %s · tk %s · %s · %.2f t" % (
        r["fecha"].strftime("%d/%m"), r["semana"], r["ticket"], r["proveedor"], (r["kg"] or 0) / 1000.0)
        for _, r in pend.iterrows()}
    sel = st.selectbox("Ingreso a evaluar", pend["id_transaccion"].tolist(),
                       format_func=lambda i: _lbl.get(int(i), str(i)), key="agli_qsel_%s" % key)
    r = pend[pend["id_transaccion"] == sel].iloc[0]
    q1, q2, q3, q4 = st.columns(4)
    _gl = q1.number_input("Glicerol %", min_value=0.0, max_value=100.0, value=None, step=0.5,
                          format="%.1f", key="agli_qgl_%s" % key)
    _mo = q2.number_input("MONG %", min_value=0.0, max_value=100.0, value=None, step=0.1,
                          format="%.2f", key="agli_qmo_%s" % key)
    _ay = q3.number_input("AyS %", min_value=0.0, max_value=100.0, value=None, step=0.05,
                          format="%.2f", key="agli_qay_%s" % key)
    _hu = q4.number_input("Humedad %", min_value=0.0, max_value=100.0, value=None, step=0.05,
                          format="%.2f", key="agli_qhu_%s" % key)
    q5, q6, q7, q8 = st.columns(4)
    _sd = q5.number_input("Sedimento %", min_value=0.0, max_value=100.0, value=None, step=0.5,
                          format="%.1f", key="agli_qsd_%s" % key,
                          help="Define C vs D en la franja 60–80 de glicerol.")
    _tp = q6.selectbox("Tipo", TIPOS_GLI, key="agli_qtp_%s" % key)
    _cal = q7.selectbox("Calidad", CAL_GLI_OPTS, key="agli_qcal_%s" % key,
                        format_func=lambda c: CAL_LBL.get(c, c or "— (por parámetros)"),
                        help="La define el glicerol + sedimento. Si la dejás vacía se guarda "
                             "la que dan los parámetros.")
    _dc = q8.number_input("Descuento al ticket (%)", min_value=0.0, max_value=100.0, value=None,
                          step=0.5, format="%.1f", key="agli_qdc_%s" % key,
                          help="Cuánto descontarle al precio del ticket por mala calidad.")
    _sug = _cal_params(_gl, _sd)
    if _sug:
        if _cal and _cal != _sug:
            st.warning("Elegiste **%s** pero por parámetros corresponde **%s** — se guarda "
                       "lo que elijas, con la discrepancia marcada en el análisis."
                       % (CAL_LBL.get(_cal, _cal), CAL_LBL.get(_sug, _sug)))
        else:
            st.caption("Por parámetros corresponde **%s**." % CAL_LBL.get(_sug, _sug))
    if st.button("💾 Guardar evaluación rápida", type="primary", key="agli_qgo_%s" % key,
                 disabled=(_gl is None and _mo is None and _ay is None and not _cal)):
        try:
            with conectar(int(USR["id_usuario"])) as (conn, _a):
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO produccion.lab_evaluaciones "
                        "(tipo_formulario, usuario_app, ticket, producto, producto_lab, "
                        " calidad_final_lab, gli_tipo, empleado, gli_glicerol, gli_mong, "
                        " gli_ays, gli_humedad, prc_sedimentos, descuento_pct) "
                        "VALUES ('GLICERINA', %s, %s, %s, 'GLICERINA', %s, %s, %s, %s, %s, %s, "
                        "%s, %s, %s) RETURNING id",
                        (str(USR.get("nombre") or "app"), str(r["ticket"]),
                         (str(r["producto"]) if pd.notna(r["producto"]) else "GLICERINA"),
                         ((_cal or _sug) or None), (_tp or None),
                         str(USR.get("nombre") or "app"),
                         (float(_gl) if _gl is not None else None),
                         (float(_mo) if _mo is not None else None),
                         (float(_ay) if _ay is not None else None),
                         (float(_hu) if _hu is not None else None),
                         (float(_sd) if _sd is not None else None),
                         (float(_dc) if _dc is not None else None)))
                    _nid = cur.fetchone()[0]
                _a.log("I", "lab_evaluaciones", int(_nid),
                       {"ticket": str(r["ticket"]), "rapida_glicerina": True})
            st.success("Evaluación cargada para el ticket %s. Ya cuenta en Análisis Glicerina."
                       % r["ticket"])
            cat.clear()
            st.rerun()
        except Exception as e:
            st.error("No se pudo guardar: %s" % e)
