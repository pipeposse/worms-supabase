# -*- coding: utf-8 -*-
"""Disposición final de LÍQUIDOS y de SÓLIDOS — lo que entra día a día, evaluado,
y los resultados del mes (comparación mensual, proyección, semana del mes, por
cliente). Pedido de dirección: dejar de ser un selector genérico de "productos
evaluables" y volver a la vista de siempre: los camiones que van entrando, a
simple vista, y una sección de resultados.

Los dos tipos comparten la lógica; cambia el producto base de portería:
  LIQUIDOS -> 'DISPOSICION FINAL DE LIQUIDOS' (laboratorio lo evalúa: calidad y
              aceptado/rechazado por camión)
  SOLIDOS  -> 'EFLUENTES SOLIDOS' + 'RESIDUOS' (barro, pellets, decomiso,
              residuos industriales… no se evalúan en lab)

render(cat, tipo)  con tipo = "LIQUIDOS" | "SOLIDOS"
"""
import calendar as _cal
from datetime import date, timedelta

import pandas as pd
import streamlit as st

_TIPOS = {
    "LIQUIDOS": {
        "titulo": "💧 Disposición final de líquidos",
        "sub": "Efluentes líquidos que entran para disposición final: cada camión, su "
               "evaluación de laboratorio y los resultados del mes.",
        "bases": ("DISPOSICION FINAL DE LIQUIDOS",),
        "grad": "linear-gradient(90deg,#1e3a8a,#0284c7)",
        "color": "#0284c7",
        "evalua": True,
    },
    "SOLIDOS": {
        "titulo": "🪨 Disposición final de sólidos",
        "sub": "Efluentes sólidos y residuos que entran para disposición final (barro, "
               "pellets, decomisos, residuos industriales…): día a día y resultados del mes.",
        "bases": ("EFLUENTES SOLIDOS", "RESIDUOS"),
        "grad": "linear-gradient(90deg,#78350f,#b45309)",
        "color": "#b45309",
        "evalua": False,
    },
}


def _tn(kg):
    try:
        return float(kg) / 1000.0
    except Exception:
        return 0.0


def _datos(cat, bases, d1, d2):
    df = cat(
        "SELECT transaccion, fecha_entrada, hora_e, patente_chasis, cliente, transporte, "
        "       procedencia, producto, producto_base, ABS(COALESCE(peso_neto,0)) AS kg, "
        "       evaluado, lab_calidad, lab_rechazado, lab_num_muestra, estado_camion "
        "FROM produccion.v_transacciones_limpias "
        "WHERE upper(COALESCE(producto_base,'')) = ANY(%s) "
        "  AND fecha_entrada IS NOT NULL AND fecha_entrada >= %s AND fecha_entrada <= %s "
        "ORDER BY fecha_entrada, hora_e",
        (list(bases), d1.isoformat(), d2.isoformat()))
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["kg"] = pd.to_numeric(df["kg"], errors="coerce").fillna(0.0)
    df["tn"] = df["kg"] / 1000.0
    df["fecha"] = pd.to_datetime(df["fecha_entrada"]).dt.date
    df["mes"] = pd.to_datetime(df["fecha_entrada"]).dt.to_period("M").astype(str)
    df["dia"] = pd.to_datetime(df["fecha_entrada"]).dt.day
    df["ev"] = df["evaluado"].astype(str).str.upper().eq("SI")
    df["rech"] = df["lab_rechazado"].astype(str).str.upper().str.contains("RECHAZ", na=False)
    return df


def _proyeccion(df_mes, hoy):
    """(acumulado a hoy, proyección fin de mes, día de hoy, días del mes)."""
    if df_mes.empty:
        return 0.0, 0.0, hoy.day, _cal.monthrange(hoy.year, hoy.month)[1]
    acum = float(df_mes["tn"].sum())
    dias_mes = _cal.monthrange(hoy.year, hoy.month)[1]
    dia = max(1, hoy.day)
    return acum, acum / dia * dias_mes, dia, dias_mes


def render(cat, tipo="LIQUIDOS"):
    cfg = _TIPOS[tipo]
    k = "df_%s" % tipo.lower()
    st.markdown(
        "<div style='background:%s;border-radius:14px;padding:14px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.3rem;font-weight:900'>%s</div>"
        "<div style='color:#e0f2fe;font-size:.86rem;margin-top:3px'>%s</div></div>"
        % (cfg["grad"], cfg["titulo"], cfg["sub"]), unsafe_allow_html=True)

    hoy = date.today()
    c1, c2, c3 = st.columns([1, 1, 2])
    d1 = c1.date_input("Desde", value=date(hoy.year, 1, 1), key=k + "_d1", format="DD/MM/YYYY")
    d2 = c2.date_input("Hasta", value=hoy, key=k + "_d2", format="DD/MM/YYYY")
    df = _datos(cat, cfg["bases"], d1, d2)
    if df.empty:
        st.info("Sin ingresos de %s en el rango." % cfg["titulo"].split(" ", 1)[1])
        return
    _clis = sorted(df["cliente"].dropna().astype(str).str.strip().unique().tolist())
    cli_sel = c3.multiselect("Cliente (vacío = todos)", _clis, key=k + "_cli")
    if cli_sel:
        df = df[df["cliente"].astype(str).str.strip().isin(cli_sel)]
        if df.empty:
            st.info("Sin ingresos para esos clientes.")
            return

    # ================= KPIs del momento =================
    mes_act = pd.Period(hoy, freq="M").strftime("%Y-%m")
    mes_ant = (pd.Period(hoy, freq="M") - 1).strftime("%Y-%m")
    d_hoy = df[df["fecha"] == hoy]
    d_mes = df[df["mes"] == mes_act]
    d_ant = df[df["mes"] == mes_ant]
    acum, proy, dia, dias_mes = _proyeccion(d_mes, hoy)
    ant_tot = float(d_ant["tn"].sum())
    ant_mismo_dia = float(d_ant[d_ant["dia"] <= dia]["tn"].sum())
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("🚛 Hoy", "%d viajes" % len(d_hoy), "%.1f TN" % float(d_hoy["tn"].sum()),
              delta_color="off")
    k2.metric("Mes a hoy (%s)" % hoy.strftime("%b"), "%.1f TN" % acum, "%d viajes" % len(d_mes),
              delta_color="off")
    k3.metric("Proyección fin de mes", "%.0f TN" % proy,
              help="Ritmo diario del mes (%.1f TN/día) × %d días." % (acum / dia if dia else 0, dias_mes))
    if ant_mismo_dia > 0:
        k4.metric("vs mismo día del mes anterior", "%+.0f%%" % ((acum / ant_mismo_dia - 1) * 100),
                  "%.1f TN al día %d" % (ant_mismo_dia, dia), delta_color="off")
    else:
        k4.metric("Mes anterior completo", "%.1f TN" % ant_tot)
    if cfg["evalua"]:
        _ev = int(df["ev"].sum())
        _rc = int(df["rech"].sum())
        k5.metric("🧪 Evaluados", "%d / %d" % (_ev, len(df)),
                  ("%d rechazado(s)" % _rc) if _rc else "sin rechazos",
                  delta_color=("inverse" if _rc else "off"))
    else:
        _pb = df.groupby("producto_base")["tn"].sum().sort_values(ascending=False)
        k5.metric("Por tipo", " · ".join("%s %.0f" % (i.title(), v) for i, v in _pb.items()) or "—")

    # ================= Día a día =================
    st.markdown("### 📅 Día a día")
    _n_dias = st.slider("Últimos días a mostrar", 7, 60, 21, step=1, key=k + "_nd")
    _desde_dd = d2 - timedelta(days=_n_dias - 1)
    dd = df[df["fecha"] >= _desde_dd]
    if dd.empty:
        st.info("Sin ingresos en los últimos %d días." % _n_dias)
    else:
        _agg = {"viajes": ("tn", "size"), "tn": ("tn", "sum")}
        if cfg["evalua"]:
            _agg["evaluados"] = ("ev", "sum")
            _agg["rechazados"] = ("rech", "sum")
        por_dia = dd.groupby("fecha").agg(**_agg).reset_index().sort_values("fecha")
        try:
            import altair as alt
            _pd = por_dia.copy()
            _pd["fecha"] = pd.to_datetime(_pd["fecha"])
            _bars = (alt.Chart(_pd).mark_bar(color=cfg["color"], cornerRadiusTopLeft=3,
                                              cornerRadiusTopRight=3)
                     .encode(x=alt.X("fecha:T", title=None, axis=alt.Axis(format="%d/%m")),
                             y=alt.Y("tn:Q", title="TN"),
                             tooltip=[alt.Tooltip("fecha:T", format="%d/%m"),
                                      alt.Tooltip("tn:Q", format=".1f"), "viajes:Q"]))
            _txt = (alt.Chart(_pd).mark_text(dy=-7, fontSize=10, fontWeight="bold")
                    .encode(x="fecha:T", y="tn:Q", text=alt.Text("tn:Q", format=".0f")))
            st.altair_chart((_bars + _txt).properties(height=240), use_container_width=True)
        except Exception:
            st.bar_chart(por_dia.set_index("fecha")["tn"])

        _v = por_dia.sort_values("fecha", ascending=False).copy()
        _v["Día"] = pd.to_datetime(_v["fecha"]).dt.strftime("%a %d/%m")
        _v["TN"] = _v["tn"].round(1)
        _cols = ["Día", "viajes", "TN"]
        _ren = {"viajes": "Viajes"}
        if cfg["evalua"]:
            _v["Evaluados"] = _v.apply(lambda r: "%d / %d" % (int(r["evaluados"]), int(r["viajes"])), axis=1)
            _v["Rechazados"] = _v["rechazados"].astype(int)
            _cols += ["Evaluados", "Rechazados"]
        cA, cB = st.columns([1.15, 2])
        cA.dataframe(_v[_cols].rename(columns=_ren), hide_index=True, use_container_width=True,
                     height=min(520, 38 * (len(_v) + 1)))

        # detalle de un día
        _dias = sorted(dd["fecha"].unique().tolist(), reverse=True)
        _dsel = cB.selectbox("Camiones del día", _dias, key=k + "_dsel",
                             format_func=lambda d: pd.Timestamp(d).strftime("%A %d/%m/%Y"))
        det = dd[dd["fecha"] == _dsel].sort_values("hora_e")
        _t = pd.DataFrame({
            "Hora": det["hora_e"].astype(str).str[:5],
            "Patente": det["patente_chasis"].fillna("—"),
            "Cliente": det["cliente"].fillna("—"),
            "Transporte": det["transporte"].fillna("—"),
            "Procedencia": det["procedencia"].fillna("—"),
            "TN": det["tn"].round(2),
        })
        if cfg["evalua"]:
            _t["Lab"] = det.apply(
                lambda r: ("❌ RECHAZADO" if r["rech"] else
                           ("✅ %s" % (r["lab_calidad"] or "OK")) if r["ev"] else "⏳ sin evaluar"), axis=1)
        else:
            _t.insert(1, "Producto", det["producto"].fillna(det["producto_base"]))
        cB.dataframe(_t, hide_index=True, use_container_width=True, height=min(520, 38 * (len(_t) + 1)))
        cB.caption("%d camiones · %.1f TN%s" % (
            len(det), float(det["tn"].sum()),
            (" · %d sin evaluar" % int((~det["ev"]).sum())) if cfg["evalua"] and (~det["ev"]).any() else ""))

    # ================= Resultados =================
    st.markdown("### 📊 Resultados")
    tot_mes = df.groupby("mes")["tn"].sum().reset_index().sort_values("mes")
    tot_mes["TN"] = tot_mes["tn"].round(1)
    r1, r2 = st.columns([1.2, 1])
    r1.markdown("**TN por mes**")
    r1.bar_chart(tot_mes, x="mes", y="TN", use_container_width=True, color=cfg["color"])

    r2.markdown("**Por cliente (rango elegido)**")
    by_cli = (df.dropna(subset=["cliente"]).groupby("cliente")
              .agg(Viajes=("tn", "size"), TN=("tn", "sum")).sort_values("TN", ascending=False))
    by_cli["TN"] = by_cli["TN"].round(1)
    by_cli["TN/viaje"] = (by_cli["TN"] / by_cli["Viajes"]).round(2)
    r2.dataframe(by_cli.reset_index(), hide_index=True, use_container_width=True, height=300)

    # --- comparación mensual acumulada con proyección ---
    st.markdown("**Comparación entre meses — acumulado día 1 → fin de mes (línea punteada = proyección del mes en curso)**")
    meses_disp = sorted(df["mes"].unique())
    default_meses = meses_disp[-4:] if len(meses_disp) > 4 else meses_disp
    meses_sel = st.multiselect("Meses a comparar", meses_disp, default=default_meses, key=k + "_meses")
    if meses_sel:
        try:
            import altair as alt
            d2_ = df[df["mes"].isin(meses_sel)]
            diario = d2_.groupby(["mes", "dia"])["tn"].sum().reset_index()
            diario["acum"] = diario.groupby("mes")["tn"].cumsum()
            diario["tipo"] = "real"
            proy_rows = []
            if mes_act in meses_sel and not d_mes.empty:
                dm = diario[diario["mes"] == mes_act].sort_values("dia")
                acum_hoy = float(dm["acum"].iloc[-1])
                ritmo = acum_hoy / dia if dia else 0
                proy_rows.append({"mes": mes_act + " (proy)", "dia": int(dm["dia"].iloc[-1]),
                                  "acum": acum_hoy, "tipo": "proyeccion"})
                for dd_ in range(int(dm["dia"].iloc[-1]) + 1, dias_mes + 1):
                    proy_rows.append({"mes": mes_act + " (proy)", "dia": dd_, "acum": ritmo * dd_,
                                      "tipo": "proyeccion"})
            plot_df = pd.concat([diario, pd.DataFrame(proy_rows)], ignore_index=True) if proy_rows else diario
            ch = (alt.Chart(plot_df).mark_line()
                  .encode(x=alt.X("dia:Q", title="día del mes"),
                          y=alt.Y("acum:Q", title="TN acumuladas"),
                          color=alt.Color("mes:N", title="mes"),
                          strokeDash=alt.StrokeDash("tipo:N", title="",
                                                    scale=alt.Scale(domain=["real", "proyeccion"],
                                                                    range=[[1, 0], [6, 4]])),
                          tooltip=["mes:N", "dia:Q", alt.Tooltip("acum:Q", format=".1f")])
                  .properties(height=340))
            st.altair_chart(ch, use_container_width=True)
        except Exception as _e:
            st.caption("No se pudo dibujar la comparación: %s" % _e)

    # --- misma semana del mes ---
    st.markdown("**Misma semana del mes, entre meses**")
    dsem = df.copy()
    dsem["sem_mes"] = ((dsem["dia"] - 1) // 7 + 1).clip(upper=5)
    _sem_hoy = min(5, (hoy.day - 1) // 7 + 1)
    s1, s2 = st.columns(2)
    sem_sel = s1.selectbox("Semana del mes", [1, 2, 3, 4, 5], index=_sem_hoy - 1, key=k + "_sem",
                           help="1 = días 1-7 · 2 = 8-14 · 3 = 15-21 · 4 = 22-28 · 5 = 29-31.")
    meses_sem = s2.multiselect("Meses", meses_disp, default=default_meses, key=k + "_semm")
    dsem = dsem[(dsem["sem_mes"] == sem_sel) & (dsem["mes"].isin(meses_sem))]
    if not dsem.empty:
        tot_sem = (dsem.groupby("mes").agg(TN=("tn", "sum"), viajes=("tn", "size"))
                   .reindex(sorted(meses_sem)).fillna(0).reset_index())
        tot_sem["TN"] = tot_sem["TN"].round(1)
        st.bar_chart(tot_sem, x="mes", y="TN", use_container_width=True, color=cfg["color"])

    if not cfg["evalua"]:
        st.markdown("**Por producto (qué sólido entra)**")
        by_prod = (df.groupby(["producto_base", "producto"]).agg(Viajes=("tn", "size"), TN=("tn", "sum"))
                   .sort_values("TN", ascending=False).reset_index())
        by_prod["TN"] = by_prod["TN"].round(1)
        st.dataframe(by_prod.rename(columns={"producto_base": "Tipo", "producto": "Producto"}),
                     hide_index=True, use_container_width=True, height=300)

    _exp = df[["transaccion", "fecha_entrada", "hora_e", "patente_chasis", "cliente", "transporte",
               "procedencia", "producto", "tn", "evaluado", "lab_calidad", "lab_rechazado"]]
    st.download_button("⬇️ Descargar CSV (%s a %s)" % (d1.strftime("%d/%m"), d2.strftime("%d/%m")),
                       _exp.to_csv(index=False).encode("utf-8-sig"),
                       file_name="disposicion_final_%s_%s_%s.csv" % (tipo.lower(), d1, d2),
                       mime="text/csv", key=k + "_csv")
