"""Análisis AFE (Centro de Planificación) — todos los AFE que entran, camión por camión.

  - Tabla por día y por camión con los parámetros principales (acidez, fósforo, azufre),
    filtrable por fecha, semana y proveedor; descargable en Excel y en imagen PNG.
  - AFEs SIN analizar por laboratorio, por semana, con carga rápida de parámetros
    (escribe en produccion.lab_evaluaciones, el mismo canal que usa Laboratorio).

La acidez viene de Access con unidades mezcladas (fracción o %): se normaliza asumiendo
que valores < 0.2 son fracción (×100) y el resto ya es %.
"""
import io as _io

import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")
_DIAS = {0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves", 4: "viernes", 5: "sábado", 6: "domingo"}
CAL_AFE_OPTS = ["", "S", "SG", "G", "P", "AL", "M", "FUERA DE ESPECIFICACION"]


def _norm_acidez(v):
    if v is None or pd.isna(v):
        return None
    v = float(v)
    if v < 0.2:
        v = v * 100.0
    return v if v <= 100.0 else None


def _datos(cat, d1, d2):
    df = cat(
        "SELECT p.id_transaccion, p.fecha, to_char(p.fecha,'IYYY·\"S\"IW') AS semana, "
        "COALESCE(p.procedencia,'—') AS proveedor, p.ticket, abs(p.kg) AS kg, p.producto, "
        "l.prc_acidez, l.ppm_azufre, l.ppm_fosforo, l.calidad_final_lab, "
        "l.rechazado, l.conclusion, l.patente_chasis, l.prc_sedimentos, l.empleado "
        "FROM produccion.v_porteria_ticket p "
        "LEFT JOIN LATERAL (SELECT pl.prc_acidez, pl.ppm_azufre, pl.ppm_fosforo, "
        "         pl.calidad_final_lab, pl.rechazado, pl.conclusion, pl.patente_chasis, "
        "         pl.prc_sedimentos, pl.empleado "
        "  FROM produccion.procesos_lab pl "
        "  WHERE btrim(pl.ticket)=p.ticket::text AND COALESCE(pl.anulado,false)=false "
        "  ORDER BY pl.fecha DESC NULLS LAST LIMIT 1) l ON true "
        "WHERE p.familia='AFE' AND p.clase IN ('OTRO','INGRESO') AND p.kg IS NOT NULL "
        "AND p.fecha BETWEEN %s AND %s", (d1, d2))
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    for _c in ("kg", "prc_acidez", "ppm_azufre", "ppm_fosforo"):
        df[_c] = pd.to_numeric(df[_c], errors="coerce")
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["dia"] = df["fecha"].dt.dayofweek.map(_DIAS)
    df["acidez"] = [(_norm_acidez(v)) for v in df["prc_acidez"]]
    df["tiene_lab"] = df["ppm_azufre"].notna() | df["ppm_fosforo"].notna() | pd.Series(df["acidez"]).notna()
    # Rechazado = el laboratorio lo marcó RECHAZADO o le puso calidad FUERA DE
    # ESPECIFICACION. Ese camión NO descargó: no es stock ni es calidad de lo que entró.
    _re = df["rechazado"].astype(str).str.upper().str.strip()
    _ca = df["calidad_final_lab"].astype(str).str.upper().str.strip()
    df["es_rechazado"] = _re.str.startswith("RECHAZ") | (_ca == "FUERA DE ESPECIFICACION")
    df["es_remuestreo"] = _re.str.startswith("REMUESTREO")
    return df


def _tabla_vista(df):
    v = df.sort_values("fecha", ascending=False).copy()
    v["Lab"] = v["tiene_lab"].map({True: "✅", False: "❌ sin lab"})
    v["tn"] = (v["kg"] / 1000.0).round(2)
    v = v.rename(columns={"fecha": "Fecha", "dia": "Día", "semana": "Semana",
                          "proveedor": "Proveedor", "ticket": "Ticket", "tn": "TN",
                          "acidez": "Acidez %", "ppm_fosforo": "Fósforo ppm",
                          "ppm_azufre": "Azufre ppm", "calidad_final_lab": "Calidad"})
    return v[["Fecha", "Día", "Semana", "Proveedor", "Ticket", "TN", "Acidez %",
              "Fósforo ppm", "Azufre ppm", "Calidad", "Lab"]]


def _excel_bytes(v):
    buf = _io.BytesIO()
    x = v.copy()
    x["Fecha"] = pd.to_datetime(x["Fecha"]).dt.strftime("%d/%m/%Y")
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        x.to_excel(w, sheet_name="AFEs", index=False)
        ws = w.sheets["AFEs"]
        for i, c in enumerate(x.columns):
            ws.column_dimensions[chr(65 + i)].width = max(12, min(28, int(x[c].astype(str).str.len().max() or 10) + 2))
    return buf.getvalue()


def _imagen_bytes(v, max_filas=60):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = v.head(max_filas).copy()
    x["Fecha"] = pd.to_datetime(x["Fecha"]).dt.strftime("%d/%m")
    for c in ("Acidez %", "Fósforo ppm", "Azufre ppm"):
        x[c] = x[c].map(lambda z: ("%.1f" % z) if pd.notna(z) else "—")
    x["TN"] = x["TN"].map(lambda z: ("%.2f" % z) if pd.notna(z) else "—")
    x = x.fillna("—").astype(str)
    fig, ax = plt.subplots(figsize=(13, 0.32 * (len(x) + 2) + 1))
    ax.axis("off")
    tb = ax.table(cellText=x.values, colLabels=list(x.columns), loc="center", cellLoc="center")
    tb.auto_set_font_size(False)
    tb.set_fontsize(8)
    tb.scale(1, 1.25)
    for j in range(len(x.columns)):
        tb[0, j].set_facecolor("#0f766e")
        tb[0, j].set_text_props(color="white", fontweight="bold")
    ax.set_title("AFEs ingresados — parámetros por camión", fontsize=11, fontweight="bold", pad=8)
    buf = _io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def render(USR, cat, conectar):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#065f46,#0d9488);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>🔬 Análisis AFE</div>"
        "<div style='color:#ccfbf1;font-size:.88rem;margin-top:3px'>Cada camión de AFE que entró, "
        "con su acidez, fósforo y azufre — y los que laboratorio todavía no midió.</div></div>",
        unsafe_allow_html=True)
    if USR.get("rol") not in ROLES_DIRECCION and "PLANIFICACION" not in (USR.get("secciones_app") or []):
        st.warning("Sección exclusiva de dirección.")
        return

    hoy = pd.Timestamp.today().date()
    f1, f2, f3, f4 = st.columns([1, 1, 1.4, 1.2])
    d1 = f1.date_input("Desde", hoy - pd.Timedelta(days=28), key="aafe_d1", format="DD/MM/YYYY")
    d2 = f2.date_input("Hasta", hoy, key="aafe_d2", format="DD/MM/YYYY")
    df = _datos(cat, d1, d2)
    if df.empty:
        st.info("No hay ingresos de AFE en ese rango.")
        return
    _sems = sorted(df["semana"].unique().tolist(), reverse=True)
    f_sem = f3.multiselect("Semana", _sems, key="aafe_sem")
    _provs = sorted(df["proveedor"].unique().tolist())
    f_prov = f4.multiselect("Proveedor", _provs, key="aafe_prov")
    _nrech_tot = int(df["es_rechazado"].sum())
    # OJO: las etiquetas van SIN el contador. Si el número viaja en la opción, al cambiar
    # (un rechazo nuevo) el valor guardado en sesión deja de existir entre las opciones y
    # Streamlit tira StreamlitAPIException. El contador va en el caption.
    f_lab = st.radio(
        "Vista", ["Todos", "✅ Con análisis", "❌ Sin análisis", "🚫 Rechazados"],
        horizontal=True, key="aafe_lab",
        help="Los rechazados nunca entran en el análisis (no descargaron). Esta opción "
             "los muestra solos, con el motivo del laboratorio y el detalle por proveedor.")
    if _nrech_tot:
        st.caption("🚫 %d camión(es) rechazado(s) en el rango de fechas elegido." % _nrech_tot)
    if f_sem:
        df = df[df["semana"].isin(f_sem)]
    if f_prov:
        df = df[df["proveedor"].isin(f_prov)]
    if f_lab.startswith("✅"):
        df = df[df["tiene_lab"]]
    elif f_lab.startswith("❌"):
        df = df[~df["tiene_lab"]]
    if df.empty:
        st.info("Ningún camión cumple los filtros.")
        return

    # Vista dedicada: SOLO los rechazados (con los mismos filtros de fecha/semana/proveedor)
    if f_lab.startswith("🚫"):
        _seccion_rechazados(df[df["es_rechazado"]].copy(), d1, d2, solo=True)
        return

    # Los RECHAZADOS salen del análisis: no descargaron, así que no son ni volumen
    # ingresado ni calidad de lo que entró. Van completos a su propia sección.
    _rech = df[df["es_rechazado"]].copy()
    df = df[~df["es_rechazado"]]
    if df.empty:
        st.warning("Con estos filtros **todos los camiones están rechazados** (%d). "
                   "El detalle está abajo, en Rechazados." % len(_rech))
        _seccion_rechazados(_rech, d1, d2)
        return

    # a qué recorte corresponden los KPIs (los filtros activos, explícitos)
    _fil = ["📅 %s → %s" % (d1.strftime("%d/%m/%y"), d2.strftime("%d/%m/%y"))]
    _fil.append("🗓️ " + (", ".join(f_sem) if f_sem else "todas las semanas del rango"))
    _fil.append("🚚 " + (", ".join(f_prov) if f_prov else "todos los proveedores (%d)"
                         % df["proveedor"].nunique()))
    if not f_lab.startswith("Todos"):
        _fil.append(f_lab)
    _fil.append("🚫 sin los rechazados" + (" (%d)" % len(_rech) if len(_rech) else ""))
    st.markdown("<div style='background:#f0fdfa;border:1px solid #99f6e4;border-radius:10px;"
                "padding:6px 12px;margin:2px 0 8px;font-size:.85rem;color:#134e4a'>"
                "<b>KPIs calculados sobre:</b> " + " · ".join(_fil) + "</div>",
                unsafe_allow_html=True)

    _kg = float(df["kg"].sum())
    def _pond(col):
        d = df[pd.notna(df[col])]
        return (float((d[col] * d["kg"]).sum() / d["kg"].sum()) if not d.empty and d["kg"].sum() > 0 else None)
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Camiones", len(df),
              help="Camiones que efectivamente ingresaron. Los rechazados no cuentan acá: "
                   "están en su propia sección, más abajo.")
    k2.metric("Toneladas", "%.0f" % (_kg / 1000.0))
    k3.metric("Con lab", "%.0f %%" % (100.0 * df["tiene_lab"].mean()))
    _sp = _pond("ppm_azufre"); _pp = _pond("ppm_fosforo")
    k4.metric("S pond.", ("%.1f ppm" % _sp) if _sp is not None else "—")
    k5.metric("P pond.", ("%.1f ppm" % _pp) if _pp is not None else "—")

    v = _tabla_vista(df)
    st.dataframe(v, hide_index=True, use_container_width=True,
                 column_config={
                     "Fecha": st.column_config.DatetimeColumn(format="DD/MM/YY"),
                     "TN": st.column_config.NumberColumn(format="%.2f"),
                     "Acidez %": st.column_config.NumberColumn(format="%.2f"),
                     "Fósforo ppm": st.column_config.NumberColumn(format="%.1f"),
                     "Azufre ppm": st.column_config.NumberColumn(format="%.1f")})
    st.caption("Acidez normalizada (Access mezcla fracción y %%: < 0.2 se toma como fracción ×100).")

    b1, b2 = st.columns(2)
    b1.download_button("⬇️ Descargar Excel (.xlsx)", _excel_bytes(v),
                       file_name="afes_%s_%s.xlsx" % (d1, d2),
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    try:
        _png = _imagen_bytes(v)
        b2.download_button("🖼️ Descargar imagen (PNG%s)" % (" · primeras 60 filas" if len(v) > 60 else ""),
                           _png, file_name="afes_%s_%s.png" % (d1, d2), mime="image/png",
                           use_container_width=True)
    except Exception as _e:
        b2.caption("No se pudo generar la imagen: %s" % _e)

    st.markdown("---")
    _seccion_rechazados(_rech, d1, d2)

    st.markdown("---")
    render_sin_lab(USR, cat, conectar)


def _seccion_rechazados(r, d1, d2, solo=False):
    """Camiones de AFE rechazados por laboratorio: por qué y de quién.

    solo=True cuando es la vista dedicada (el usuario eligió 🚫 Rechazados arriba)."""
    st.markdown(("### 🚫 Camiones rechazados" if solo else "#### 🚫 Camiones rechazados"))
    if r is None or r.empty:
        st.success("✅ Ningún camión rechazado en el período y los filtros elegidos.")
        return
    st.caption("Rechazados por laboratorio: el camión llegó, se muestreó y **no descargó** "
               "(por eso pesa casi 0 t). Quedan fuera del análisis de arriba — no son "
               "volumen ingresado ni calidad de lo que entró — pero son el mejor termómetro "
               "de qué proveedor está mandando material fuera de especificación.")
    _kg = float(r["kg"].fillna(0).sum())
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Camiones rechazados", int(len(r)))
    m2.metric("Proveedores", int(r["proveedor"].nunique()))
    m3.metric("Kg que no entraron", "%.0f kg" % _kg,
              help="Peso registrado en portería. Un rechazado suele pesar casi 0 porque "
                   "entra y sale cargado: lo que se ve es la diferencia de báscula.")
    _pm = r[pd.notna(r["ppm_fosforo"])]
    m4.metric("Fósforo medio", ("%.0f ppm" % _pm["ppm_fosforo"].mean()) if not _pm.empty else "—",
              help="Promedio simple del fósforo de los camiones rechazados. Es el motivo "
                   "más frecuente de rechazo en AFE.")

    _porp = (r.groupby("proveedor")
              .agg(camiones=("ticket", "count"),
                   fosforo_medio=("ppm_fosforo", "mean"),
                   azufre_medio=("ppm_azufre", "mean"),
                   ultimo=("fecha", "max"))
              .reset_index().sort_values("camiones", ascending=False))
    st.markdown("**Por proveedor**")
    st.dataframe(_porp.rename(columns={"proveedor": "Proveedor", "camiones": "Camiones",
                                       "fosforo_medio": "Fósforo medio ppm",
                                       "azufre_medio": "Azufre medio ppm",
                                       "ultimo": "Último rechazo"}),
                 hide_index=True, use_container_width=True,
                 column_config={"Fósforo medio ppm": st.column_config.NumberColumn(format="%.0f"),
                                "Azufre medio ppm": st.column_config.NumberColumn(format="%.1f"),
                                "Último rechazo": st.column_config.DatetimeColumn(format="DD/MM/YY")})

    if solo:
        _sem = (r.groupby("semana")
                 .agg(camiones=("ticket", "count"),
                      fosforo_medio=("ppm_fosforo", "mean"))
                 .reset_index().sort_values("semana"))
        if len(_sem) > 1:
            st.markdown("**Rechazos por semana**")
            st.bar_chart(_sem.set_index("semana")["camiones"], use_container_width=True)

    st.markdown("**Detalle camión por camión**")
    v = r.sort_values("fecha", ascending=False).copy()
    v["Motivo del lab"] = [str(c).strip() if (pd.notna(c) and str(c).strip()) else "— sin nota —"
                           for c in v["conclusion"]]
    v = v.rename(columns={"fecha": "Fecha", "dia": "Día", "semana": "Semana",
                          "proveedor": "Proveedor", "ticket": "Ticket",
                          "acidez": "Acidez %", "ppm_fosforo": "Fósforo ppm",
                          "ppm_azufre": "Azufre ppm", "prc_sedimentos": "Sed. %",
                          "calidad_final_lab": "Calidad", "rechazado": "Estado",
                          "patente_chasis": "Patente", "empleado": "Analista"})
    _cols = ["Fecha", "Día", "Semana", "Proveedor", "Ticket", "Patente", "Acidez %",
             "Fósforo ppm", "Azufre ppm", "Sed. %", "Calidad", "Estado", "Motivo del lab",
             "Analista"]
    _cols = [c for c in _cols if c in v.columns]
    st.dataframe(v[_cols], hide_index=True, use_container_width=True,
                 column_config={"Fecha": st.column_config.DatetimeColumn(format="DD/MM/YY"),
                                "Acidez %": st.column_config.NumberColumn(format="%.2f"),
                                "Fósforo ppm": st.column_config.NumberColumn(format="%.1f"),
                                "Azufre ppm": st.column_config.NumberColumn(format="%.1f"),
                                "Sed. %": st.column_config.NumberColumn(format="%.2f")})
    try:
        st.download_button("⬇️ Descargar rechazados (.xlsx)", _excel_bytes(v[_cols]),
                           file_name="afe_rechazados_%s_%s.xlsx" % (d1, d2),
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="aafe_rech_dl")
    except Exception as _e:
        st.caption("No se pudo generar el Excel: %s" % _e)


def render_sin_lab(USR, cat, conectar, key="pl"):
    """AFEs sin análisis de laboratorio, por semana, con carga rápida. Se usa acá y en Laboratorio."""
    st.markdown("#### 🚨 AFEs sin analizar por laboratorio")
    st.caption("Crítico: sin análisis no se puede clasificar el AFE-S (bueno/malo) ni proyectar la "
               "exportación. Elegí un camión y cargá los parámetros acá mismo: queda como una "
               "evaluación de laboratorio normal (canal `lab_evaluaciones`).")
    hoy = pd.Timestamp.today().date()
    df = _datos(cat, hoy - pd.Timedelta(days=56), hoy)
    if df.empty:
        st.info("Sin ingresos de AFE en las últimas 8 semanas.")
        return
    pend = df[~df["tiene_lab"]].copy()
    if pend.empty:
        st.success("✅ Todos los AFE de las últimas 8 semanas tienen análisis.")
        return
    _g = pend.groupby("semana").agg(camiones=("ticket", "count"), t=("kg", lambda s: s.sum() / 1000.0)).reset_index()
    _g = _g.sort_values("semana", ascending=False)
    c1, c2 = st.columns([1, 2])
    c1.metric("Camiones sin lab (8 sem)", int(len(pend)), "%.0f t" % (pend["kg"].sum() / 1000.0))
    c2.dataframe(_g.rename(columns={"semana": "Semana", "camiones": "Camiones", "t": "t"}).round(1),
                 hide_index=True, use_container_width=True, height=160)

    pend = pend.sort_values("fecha", ascending=False)
    _lbl = {int(r["id_transaccion"]): "%s · %s · tk %s · %s · %.2f t" % (
        r["fecha"].strftime("%d/%m"), r["semana"], r["ticket"], r["proveedor"], (r["kg"] or 0) / 1000.0)
        for _, r in pend.iterrows()}
    sel = st.selectbox("Camión a evaluar", pend["id_transaccion"].tolist(),
                       format_func=lambda i: _lbl.get(int(i), str(i)), key="aafe_qsel_%s" % key)
    r = pend[pend["id_transaccion"] == sel].iloc[0]
    q1, q2, q3, q4 = st.columns(4)
    _ac = q1.number_input("Acidez %", min_value=0.0, max_value=100.0, value=None, step=0.1,
                          format="%.2f", key="aafe_qac_%s" % key)
    _fo = q2.number_input("Fósforo (ppm)", min_value=0.0, value=None, step=1.0, key="aafe_qfo_%s" % key)
    _az = q3.number_input("Azufre (ppm)", min_value=0.0, value=None, step=0.5, key="aafe_qaz_%s" % key)
    _cal = q4.selectbox("Calidad", CAL_AFE_OPTS, key="aafe_qcal_%s" % key)
    if st.button("💾 Guardar evaluación rápida", type="primary", key="aafe_qgo_%s" % key,
                 disabled=(_ac is None and _fo is None and _az is None)):
        try:
            with conectar(int(USR["id_usuario"])) as (conn, _a):
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO produccion.lab_evaluaciones "
                        "(tipo_formulario, usuario_app, ticket, producto, producto_lab, "
                        " calidad_final_lab, corriente, empleado, prc_acidez, ppm_azufre, ppm_fosforo) "
                        "VALUES ('AFE', %s, %s, %s, 'AFE', %s, 'VEGETAL', %s, %s, %s, %s) RETURNING id",
                        (str(USR.get("nombre") or "app"), str(r["ticket"]),
                         (str(r["producto"]) if pd.notna(r["producto"]) else "AFE"),
                         (_cal or None), str(USR.get("nombre") or "app"),
                         (float(_ac) if _ac is not None else None),
                         (float(_az) if _az is not None else None),
                         (float(_fo) if _fo is not None else None)))
                    _nid = cur.fetchone()[0]
                _a.log("I", "lab_evaluaciones", int(_nid),
                       {"ticket": str(r["ticket"]), "rapida_afe": True})
            st.success("Evaluación cargada para el ticket %s. Ya cuenta en Balance y Análisis AFE."
                       % r["ticket"])
            cat.clear()
            st.rerun()
        except Exception as e:
            st.error("No se pudo guardar: %s" % e)
