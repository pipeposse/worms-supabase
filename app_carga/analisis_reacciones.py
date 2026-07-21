"""🔬 Análisis de reacciones — sección de home (semana a semana).

Cruza produccion.v_perf_reaccion (tiempos reales vs cronograma, capacidad, rendimiento)
con produccion.v_reaccion_lab_final (lab del producto final: DESGOMADO desde los tickets
finales de pesada ya analizados; ARE por evaluación ASIGNADA por id de procesos_lab).

KPIs de la semana con delta vs la semana anterior + gráficos de eficiencia (Altair)
+ asignador de evaluación de laboratorio para las ARE.

render(USR, cat, conectar)
"""
import altair as alt
import pandas as pd
import streamlit as st

C_PRI = "#4f46e5"   # indigo (marca)
C_SEC = "#8b5cf6"   # violeta
C_OK = "#16a34a"
C_BAD = "#dc2626"
C_AMB = "#d97706"
C_MUT = "#94a3b8"

_NUMS = ["espera_arranque_h", "reaccion_h", "reposo_h", "decantacion_h", "ciclo_proceso_h",
         "prog_proceso_h", "desvio_proceso_h", "prog_reaccion_h", "desvio_h", "max_kg",
         "formula_kg", "mp_kg", "real_kg", "utilizacion_pct", "capacidad_perdida_kg",
         "rendimiento_pct", "acidez_pct", "agua_pct", "azufre_ppm", "fosforo_ppm", "densidad"]


def _cargar(cat):
    df = cat("SELECT p.id_batch, p.ident, p.etiqueta, p.tipo, p.tipo_proceso, p.reactor, p.producto, "
             "p.fecha, p.inicio_local, p.fin_local, p.espera_arranque_h, p.reaccion_h, p.reposo_h, "
             "p.decantacion_h, p.ciclo_proceso_h, p.prog_proceso_h, p.desvio_proceso_h, "
             "p.prog_reaccion_h, p.desvio_h, p.reaccion_confiable, "
             "p.max_kg, p.formula_kg, p.mp_kg, p.real_kg, p.utilizacion_pct, p.capacidad_perdida_kg, "
             "p.rendimiento_pct, p.tiempos_confiables, "
             "l.fuente_lab, l.id_procesos_lab, l.acidez_pct, l.agua_pct, l.azufre_ppm, l.fosforo_ppm, l.densidad "
             "FROM produccion.v_perf_reaccion p "
             "LEFT JOIN produccion.v_reaccion_lab_final l ON l.id_batch = p.id_batch "
             "ORDER BY p.fecha, p.id_batch")
    if df is None or df.empty:
        return None
    for c in _NUMS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["tiempos_confiables"] = df["tiempos_confiables"].fillna(False).astype(bool)
    df["reaccion_confiable"] = df["reaccion_confiable"].fillna(False).astype(bool)
    df["semana"] = df["fecha"].dt.to_period("W").dt.start_time
    df["sem_lbl"] = df["semana"].map(
        lambda s: f"S{pd.Timestamp(s).isocalendar()[1]} · {pd.Timestamp(s):%d/%m}" if pd.notna(s) else "—")

    def _sub(r):
        if r.get("tipo") == "ARE":
            _p = str(r.get("producto") or "").upper()
            return "ARE animal" if ("ANIMAL" in _p or "(AN)" in _p) else "ARE vegetal"
        return r.get("tipo")
    df["subtipo"] = df.apply(_sub, axis=1)
    return df


def _kpi(col, label, val, delta=None, help_=None, inverso=False):
    col.metric(label, val, delta, help=help_,
               delta_color=("inverse" if inverso else "normal") if delta is not None else "off")


def _fmt_delta(cur, prev, unit="", dec=1):
    if cur is None or prev is None or pd.isna(cur) or pd.isna(prev):
        return None
    d = cur - prev
    return f"{d:+,.{dec}f}{unit} vs sem. ant."


def render(USR, cat, conectar):
    st.subheader("🔬 Análisis de reacciones")
    st.caption("La semana bajo la lupa: toneladas, desvíos contra el tiempo estimado, laboratorio del "
               "producto final y eficiencia real de los reactores. Cada KPI compara contra la semana anterior.")

    df = _cargar(cat)
    if df is None:
        st.info("Todavía no hay reacciones finalizadas para analizar.")
        return

    # ---------- selector de semana ----------
    _sems = sorted(df["semana"].dropna().unique(), reverse=True)
    _lbl = {s: (f"Semana {pd.Timestamp(s).isocalendar()[1]} · "
                f"{pd.Timestamp(s):%d/%m} – {(pd.Timestamp(s) + pd.Timedelta(days=6)):%d/%m/%Y}")
            for s in _sems}
    c_sel, c_tipo = st.columns([2, 1])
    _sel = c_sel.selectbox("Semana", [_lbl[s] for s in _sems], key="anr_sem")
    _tipo = c_tipo.selectbox("Tipo", ["Todas", "ARE vegetal", "ARE animal", "DESGOMADO"], key="anr_tipo")
    _wk = next(s for s in _sems if _lbl[s] == _sel)
    if _tipo != "Todas":
        df = df[df["subtipo"] == _tipo]
    dfw = df[df["semana"] == _wk]
    _prev_wk = pd.Timestamp(_wk) - pd.Timedelta(days=7)
    dfp = df[df["semana"] == _prev_wk]
    if dfw.empty:
        st.info("No hay reacciones finalizadas esa semana con ese filtro.")
        return

    def _agg(d):
        if d is None or d.empty:
            return {}
        _pf = d[d["real_kg"].fillna(0) > 0]
        _cf = d[d["reaccion_confiable"] & d["desvio_h"].notna()]
        _lab = d[d["fuente_lab"].notna()]
        return {
            "n": len(d),
            "mp": d["mp_kg"].sum(skipna=True) / 1000.0,
            "pf": _pf["real_kg"].sum() / 1000.0,
            "rend": (100.0 * _pf["real_kg"].sum() / _pf["formula_kg"].sum()
                     if _pf["formula_kg"].sum() else None),
            "util": (100.0 * d["formula_kg"].sum(skipna=True) / d["max_kg"].sum(skipna=True)
                     if d["max_kg"].sum(skipna=True) else None),
            "perd": d["capacidad_perdida_kg"].sum(skipna=True) / 1000.0,
            "dsv": (_cf["desvio_h"].median() if not _cf.empty else None),
            "aci": (_lab["acidez_pct"].mean() if not _lab.empty else None),
            "lab_n": len(_lab),
        }

    a, p = _agg(dfw), _agg(dfp)

    # ---------- KPIs ----------
    k = st.columns(4)
    _kpi(k[0], "Reacciones", a["n"], (f"{a['n']-p['n']:+d} vs sem. ant." if p else None))
    _kpi(k[1], "MP procesada (TN)", f"{a['mp']:,.1f}", _fmt_delta(a["mp"], p.get("mp") if p else None, " TN"))
    _kpi(k[2], "Producto final (TN)", f"{a['pf']:,.1f}", _fmt_delta(a["pf"], p.get("pf") if p else None, " TN"),
         help_="Σ real obtenido (cierre → tickets → kg_obtenido). Solo reacciones con real registrado.")
    _kpi(k[3], "Rendimiento (%)", (f"{a['rend']:.0f}%" if a["rend"] is not None else "—"),
         _fmt_delta(a["rend"], p.get("rend") if p else None, " pp", 0),
         help_="Real obtenido / formulado, sobre reacciones con dato real.")
    k = st.columns(4)
    _kpi(k[0], "Utilización reactores", (f"{a['util']:.0f}%" if a["util"] is not None else "—"),
         _fmt_delta(a["util"], p.get("util") if p else None, " pp", 0),
         help_="Formulado / máximo a reactor lleno. Capacidad no usada = producción perdida.")
    _kpi(k[1], "Capacidad no usada (TN)", f"{a['perd']:,.1f}",
         _fmt_delta(a["perd"], p.get("perd") if p else None, " TN"), inverso=True,
         help_="TN que se dejaron de formular por no cargar al máximo.")
    _kpi(k[2], "Desvío vs plan (h, mediana)", (f"{a['dsv']:+.1f}" if a["dsv"] is not None else "—"),
         _fmt_delta(a["dsv"], p.get("dsv") if p else None, " h"), inverso=True,
         help_="Reacción real (inicio → fin de reacción) − duración Reacción del cronograma. "
               "El reposo y la decantación NO cuentan; el fin real de acopio se agregará más adelante. "
               "+ = más lento.")
    _kpi(k[3], "Con lab del producto final", f"{a['lab_n']}/{a['n']}",
         help_="Desgomados: tickets finales analizados. ARE: evaluación asignada (abajo).")

    # ---------- la semana por tipo: ⚗️ ARE vs 🫧 DESGOMADO ----------
    st.markdown("#### La semana por tipo de reacción")
    _EMO = {"ARE vegetal": "⚗️🌱", "ARE animal": "⚗️🐄", "DESGOMADO": "🫧"}
    _sub_order = [t for t in ["ARE vegetal", "ARE animal", "DESGOMADO"] if t in set(dfw["subtipo"])]
    if not _sub_order:
        _sub_order = ["ARE vegetal", "DESGOMADO"]
    _cols = st.columns(len(_sub_order))
    for _tt, _colc in zip(_sub_order, _cols):
        _emoji = _EMO.get(_tt, "🔬")
        _dt = dfw[dfw["subtipo"] == _tt]
        _dp2 = dfp[dfp["subtipo"] == _tt]
        with _colc:
            with st.container(border=True):
                st.markdown(f"##### {_emoji} {_tt}")
                if _dt.empty:
                    st.caption("Sin reacciones esta semana.")
                    continue
                _at, _pt = _agg(_dt), _agg(_dp2)
                m = st.columns(3)
                _kpi(m[0], "Reacciones", _at["n"],
                     (f"{_at['n']-_pt['n']:+d}" if _pt else None))
                _kpi(m[1], "MP (TN)", f"{_at['mp']:,.1f}", _fmt_delta(_at["mp"], _pt.get("mp") if _pt else None))
                _kpi(m[2], "Final (TN)", f"{_at['pf']:,.1f}", _fmt_delta(_at["pf"], _pt.get("pf") if _pt else None))
                m = st.columns(3)
                _kpi(m[0], "Rendimiento", (f"{_at['rend']:.0f}%" if _at["rend"] is not None else "—"),
                     _fmt_delta(_at["rend"], _pt.get("rend") if _pt else None, " pp", 0))
                _kpi(m[1], "Desvío (h)", (f"{_at['dsv']:+.1f}" if _at["dsv"] is not None else "—"),
                     _fmt_delta(_at["dsv"], _pt.get("dsv") if _pt else None, " h"), inverso=True)
                _kpi(m[2], "Acidez", (f"{_at['aci']:.2f}%" if _at["aci"] is not None else "—"),
                     _fmt_delta(_at["aci"], _pt.get("aci") if _pt else None, " pp", 2), inverso=True)

    # ---------- calidad ARE por reacción: acidez · azufre · fósforo ----------
    _qa = df[(df["tipo"] == "ARE")
             & (df["acidez_pct"].notna() | df["azufre_ppm"].notna() | df["fosforo_ppm"].notna())].copy()
    if not _qa.empty:
        st.markdown("#### ⚗️ Calidad ARE por reacción — acidez · azufre · fósforo")
        st.caption("Barras = **acidez %** (eje izquierdo) · líneas = **azufre** y **fósforo** en ppm "
                   "(eje derecho). Las reacciones de la semana elegida van en color pleno; las anteriores "
                   "en gris, para comparar de un vistazo. Se muestran las últimas 20 ARE con lab.")
        _qa = _qa.sort_values(["fecha", "id_batch"]).tail(20)
        _qa["es_sem"] = _qa["semana"] == _wk
        _ord = list(_qa["ident"])
        _ql = _qa.melt(id_vars=["ident"], value_vars=["azufre_ppm", "fosforo_ppm"],
                       var_name="Parámetro", value_name="ppm").dropna(subset=["ppm"])
        _ql["Parámetro"] = _ql["Parámetro"].map({"azufre_ppm": "Azufre (ppm)",
                                                 "fosforo_ppm": "Fósforo (ppm)"})
        _qb = alt.Chart(_qa).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("ident:N", sort=_ord, title=None),
            y=alt.Y("acidez_pct:Q", title="Acidez (%)"),
            color=alt.condition(alt.datum.es_sem, alt.value(C_PRI), alt.value(C_MUT)),
            opacity=alt.condition(alt.datum.es_sem, alt.value(0.9), alt.value(0.45)),
            tooltip=["ident", "etiqueta", "sem_lbl", "fuente_lab",
                     alt.Tooltip("acidez_pct:Q", title="Acidez %", format=".2f"),
                     alt.Tooltip("azufre_ppm:Q", title="Azufre ppm", format=",.0f"),
                     alt.Tooltip("fosforo_ppm:Q", title="Fósforo ppm", format=",.0f")],
        )
        _qp = alt.Chart(_ql).mark_line(strokeWidth=2.5,
                                       point=alt.OverlayMarkDef(size=70, filled=True)).encode(
            x=alt.X("ident:N", sort=_ord, title=None),
            y=alt.Y("ppm:Q", title="ppm", axis=alt.Axis(orient="right")),
            color=alt.Color("Parámetro:N",
                            scale=alt.Scale(domain=["Azufre (ppm)", "Fósforo (ppm)"],
                                            range=[C_AMB, C_OK]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["ident", "Parámetro", alt.Tooltip("ppm:Q", format=",.0f")],
        )
        st.altair_chart(alt.layer(_qb, _qp).resolve_scale(y="independent").properties(height=320),
                        use_container_width=True)

    st.divider()

    # ---------- proyección (fórmula) vs real vs máximo por reacción ----------
    st.markdown("### 🎯 Proyección vs real por reacción — ¿dónde falla la fórmula?")
    st.caption("Por reacción: **TN proyectadas por la fórmula** vs **TN reales** (desgomados por tickets finales — "
               "AFE-S/AFE-G — · ARE por carga manual) vs el **máximo teórico** si se cargara el reactor a tope. "
               "El desvío muestra dónde la fórmula sobre/subestima; el aprovechamiento, cuánto se dejó sobre la mesa.")
    _fc1, _fc2 = st.columns(2)
    _wk_opts = (df.dropna(subset=["semana"]).sort_values("semana", ascending=False)
                  .drop_duplicates("sem_lbl")["sem_lbl"].tolist())
    _wsel = _fc1.multiselect("Semanas (vacío = todas)", _wk_opts, default=[], key="anr_pvr_wk")
    _tsel = _fc2.multiselect("Tipo de reacción (vacío = todos)", ["ARE vegetal", "ARE animal", "DESGOMADO"], default=[], key="anr_pvr_tp")
    _fbase = df.copy()
    if _tsel:
        _fbase = _fbase[_fbase["subtipo"].isin(_tsel)]
    if _wsel:
        _fbase = _fbase[_fbase["sem_lbl"].isin(_wsel)]
    _pv = _fbase[(_fbase["real_kg"].fillna(0) > 0) & (_fbase["formula_kg"].fillna(0) > 0)].copy()
    if _pv.empty:
        st.info("No hay reacciones con proyección y real cargados para comparar todavía.")
    else:
        _pv["_form_tn"] = _pv["formula_kg"] / 1000.0
        _pv["_real_tn"] = _pv["real_kg"] / 1000.0
        _pv["_max_tn"] = _pv["max_kg"] / 1000.0
        _pv["_desv_tn"] = _pv["_real_tn"] - _pv["_form_tn"]
        _pv["_desv_pct"] = (_pv["real_kg"] / _pv["formula_kg"] - 1.0) * 100.0
        _pv["_aprov_pct"] = (_pv["real_kg"] / _pv["max_kg"] * 100.0).where(_pv["max_kg"] > 0)
        _pv["_fuente"] = _pv["fuente_lab"].map({"TICKETS": "🎫 tickets", "TICKET_REACCION": "🎫 ticket=ID",
                                               "ASIGNADO": "🧪 manual"}).fillna("—")
        _pv = _pv.sort_values(["fecha", "id_batch"])
        _order = list(_pv["ident"])

        k = st.columns(4)
        k[0].metric("Reacciones", len(_pv))
        k[1].metric("TN reales", f"{_pv['_real_tn'].sum():,.1f}")
        _dm = _pv["_desv_pct"].mean()
        k[2].metric("Desvío medio fórmula", f"{_dm:+.1f}%",
                    help="Real vs proyectado por fórmula. + = la fórmula subestimó · − = sobreestimó.")
        _am = _pv["_aprov_pct"].mean()
        k[3].metric("Aprovechamiento vs máx.", f"{_am:.0f}%",
                    help="Real / máximo teórico (reactor a tope). Lo que falta es capacidad no usada + merma.")

        st.markdown("**Máximo posible · Proyectado por fórmula · Real** (TN por reacción)")
        _ml = _pv.melt(id_vars=["ident", "tipo", "producto", "_fuente"],
                       value_vars=["_max_tn", "_form_tn", "_real_tn"], var_name="Serie", value_name="TN")
        _ml["Serie"] = _ml["Serie"].map({"_max_tn": "Máximo posible", "_form_tn": "Proyectado (fórmula)",
                                         "_real_tn": "Real"})
        _h = max(260, 64 * len(_pv))
        st.altair_chart(
            alt.Chart(_ml).mark_bar().encode(
                y=alt.Y("ident:N", sort=_order, title=None),
                yOffset=alt.YOffset("Serie:N", sort=["Máximo posible", "Proyectado (fórmula)", "Real"]),
                x=alt.X("TN:Q", title="Toneladas de producto final"),
                color=alt.Color("Serie:N", scale=alt.Scale(
                    domain=["Máximo posible", "Proyectado (fórmula)", "Real"],
                    range=[C_MUT, C_AMB, C_OK]), legend=alt.Legend(orient="top", title=None)),
                tooltip=["ident", "tipo", "producto", "_fuente", "Serie",
                         alt.Tooltip("TN:Q", format=",.2f")],
            ).properties(height=_h), use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Desvío de la fórmula** — Real − Proyectado (TN)")
            st.caption("🔴 la fórmula prometió de más (real quedó corto) · 🟢 la fórmula quedó corta (real superó).")
            _pv["_col"] = _pv["_desv_tn"].map(lambda v: "Real < fórmula" if v < 0 else "Real ≥ fórmula")
            st.altair_chart(
                alt.Chart(_pv).mark_bar(cornerRadius=3).encode(
                    y=alt.Y("ident:N", sort=_order, title=None),
                    x=alt.X("_desv_tn:Q", title="Desvío (TN)"),
                    color=alt.Color("_col:N", scale=alt.Scale(domain=["Real < fórmula", "Real ≥ fórmula"],
                                                              range=[C_BAD, C_OK]), legend=None),
                    tooltip=["ident", "producto",
                             alt.Tooltip("_form_tn:Q", title="Proyectado (TN)", format=",.2f"),
                             alt.Tooltip("_real_tn:Q", title="Real (TN)", format=",.2f"),
                             alt.Tooltip("_desv_tn:Q", title="Desvío (TN)", format="+,.2f"),
                             alt.Tooltip("_desv_pct:Q", title="Desvío %", format="+.1f")],
                ).properties(height=_h), use_container_width=True)
        with c2:
            st.markdown("**Aprovechamiento vs máximo** — Real / máximo teórico (%)")
            st.caption("Cuánto del máximo (reactor a tope) se obtuvo. Meta de referencia 90%.")
            _base = alt.Chart(_pv).encode(y=alt.Y("ident:N", sort=_order, title=None))
            st.altair_chart(
                (_base.mark_bar(cornerRadius=3, color=C_PRI).encode(
                    x=alt.X("_aprov_pct:Q", title="% del máximo", scale=alt.Scale(domain=[0, 110])),
                    tooltip=["ident", "producto",
                             alt.Tooltip("_real_tn:Q", title="Real (TN)", format=",.2f"),
                             alt.Tooltip("_max_tn:Q", title="Máximo (TN)", format=",.2f"),
                             alt.Tooltip("_aprov_pct:Q", title="Aprovechado %", format=".0f")])
                 + alt.Chart(pd.DataFrame({"y": [90]})).mark_rule(color=C_OK, strokeDash=[6, 4]).encode(x="y:Q")
                 ).properties(height=_h), use_container_width=True)

        _tab = pd.DataFrame({
            "Reacción": _pv["ident"], "Tipo": _pv["tipo"], "Producto": _pv["producto"],
            "Fuente real": _pv["_fuente"],
            "Proyect. fórmula (TN)": _pv["_form_tn"].round(2), "Real (TN)": _pv["_real_tn"].round(2),
            "Desvío (TN)": _pv["_desv_tn"].round(2), "Desvío %": _pv["_desv_pct"].round(1),
            "Rendim. %": _pv["rendimiento_pct"].round(1),
            "Máx. posible (TN)": _pv["_max_tn"].round(2), "Aprovechado %": _pv["_aprov_pct"].round(0),
        }).sort_values("Desvío %")
        st.dataframe(_tab, hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="%.2f")
                                    for c in ["Proyect. fórmula (TN)", "Real (TN)", "Desvío (TN)", "Máx. posible (TN)"]}
                     | {"Desvío %": st.column_config.NumberColumn(format="%+.1f%%"),
                        "Rendim. %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=120,
                                                                     help="Real / proyectado por fórmula."),
                        "Aprovechado %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100,
                                                                         help="Real / máximo teórico (reactor a tope).")})
        st.caption("Ordenado por desvío (arriba, donde la fórmula más sobreestimó). Barras: rendimiento (vs fórmula) "
                   "y aprovechamiento (vs máximo).")

    # ---------- comparación semanal: proyectado vs real vs máximo ----------
    _wcmp = _fbase[(_fbase["real_kg"].fillna(0) > 0) & (_fbase["formula_kg"].fillna(0) > 0)].copy()
    if not _wcmp.empty:
        st.markdown("#### 📅 Comparación semanal — proyectado vs real vs máximo")
        _wk2 = (_wcmp.groupby(["semana", "sem_lbl"], as_index=False)
                     .agg(n=("id_batch", "count"), form=("formula_kg", "sum"),
                          real=("real_kg", "sum"), mx=("max_kg", "sum")))
        _wk2 = _wk2.sort_values("semana").tail(12)
        _wk2["Proyectado"] = _wk2["form"] / 1000.0
        _wk2["Real"] = _wk2["real"] / 1000.0
        _wk2["Máximo"] = _wk2["mx"] / 1000.0
        _wk2["Desvío %"] = (_wk2["real"] / _wk2["form"] - 1.0) * 100.0
        _wk2["Aprov. %"] = (_wk2["real"] / _wk2["mx"] * 100.0).where(_wk2["mx"] > 0)
        _wl = _wk2.melt(id_vars=["sem_lbl"], value_vars=["Máximo", "Proyectado", "Real"],
                        var_name="Serie", value_name="TN")
        cwa, cwb = st.columns([1.5, 1])
        with cwa:
            st.altair_chart(
                alt.Chart(_wl).mark_bar().encode(
                    x=alt.X("sem_lbl:N", sort=list(_wk2["sem_lbl"]), title=None),
                    xOffset=alt.XOffset("Serie:N", sort=["Máximo", "Proyectado", "Real"]),
                    y=alt.Y("TN:Q", title="TN producto final"),
                    color=alt.Color("Serie:N", scale=alt.Scale(domain=["Máximo", "Proyectado", "Real"],
                                                               range=[C_MUT, C_AMB, C_OK]),
                                    legend=alt.Legend(orient="top", title=None)),
                    tooltip=["sem_lbl", "Serie", alt.Tooltip("TN:Q", format=",.1f")],
                ).properties(height=280), use_container_width=True)
        with cwb:
            st.altair_chart(
                alt.Chart(_wk2).mark_line(point=True, strokeWidth=2.5, color=C_BAD).encode(
                    x=alt.X("sem_lbl:N", sort=list(_wk2["sem_lbl"]), title=None),
                    y=alt.Y("Desvío %:Q", title="Desvío fórmula %"),
                    tooltip=["sem_lbl", alt.Tooltip("Desvío %:Q", format="+.1f")],
                ).properties(height=280)
                + alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=C_MUT, strokeDash=[4, 4]).encode(y="y:Q"),
                use_container_width=True)
        _wtab = pd.DataFrame({
            "Semana": _wk2["sem_lbl"], "Reacc.": _wk2["n"],
            "Proyect. (TN)": _wk2["Proyectado"].round(1), "Real (TN)": _wk2["Real"].round(1),
            "Máximo (TN)": _wk2["Máximo"].round(1), "Desvío %": _wk2["Desvío %"].round(1),
            "Aprov. %": _wk2["Aprov. %"].round(0),
        })
        st.dataframe(_wtab, hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="%.1f")
                                    for c in ["Proyect. (TN)", "Real (TN)", "Máximo (TN)"]}
                     | {"Desvío %": st.column_config.NumberColumn(format="%+.1f%%"),
                        "Aprov. %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)})

    st.divider()

    # ---------- gráfico 1: TN por semana (tendencia) ----------
    g1, g2 = st.columns(2)
    _tr = (df.groupby(["semana", "sem_lbl"], as_index=False)
             .agg(MP=("mp_kg", lambda s: s.sum() / 1000.0),
                  Final=("real_kg", lambda s: s.fillna(0).clip(lower=0).sum() / 1000.0)))
    _tr = _tr.sort_values("semana").tail(12)
    _trl = _tr.melt(id_vars=["semana", "sem_lbl"], value_vars=["MP", "Final"],
                    var_name="Serie", value_name="TN")
    with g1:
        st.markdown("**Toneladas por semana** — MP procesada vs producto final")
        st.altair_chart(
            alt.Chart(_trl).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                x=alt.X("sem_lbl:N", sort=list(_tr["sem_lbl"]), title=None),
                xOffset="Serie:N",
                y=alt.Y("TN:Q", title="TN"),
                color=alt.Color("Serie:N", scale=alt.Scale(domain=["MP", "Final"],
                                                           range=[C_PRI, C_OK]), legend=alt.Legend(orient="top")),
                tooltip=["sem_lbl", "Serie", alt.Tooltip("TN:Q", format=",.1f")],
            ).properties(height=260), use_container_width=True)

    # ---------- gráfico 2: utilización semanal ----------
    _ut = (df.groupby(["semana", "sem_lbl"], as_index=False)
             .agg(for_kg=("formula_kg", "sum"), max_kg=("max_kg", "sum")))
    _ut["Utilización"] = (100.0 * _ut["for_kg"] / _ut["max_kg"]).where(_ut["max_kg"] > 0)
    _ut = _ut.sort_values("semana").tail(12)
    with g2:
        st.markdown("**Utilización de reactores por semana** — meta 90%")
        _base = alt.Chart(_ut).encode(x=alt.X("sem_lbl:N", sort=list(_ut["sem_lbl"]), title=None))
        st.altair_chart(
            (_base.mark_area(opacity=0.15, color=C_PRI).encode(y=alt.Y("Utilización:Q", title="%"))
             + _base.mark_line(color=C_PRI, point=alt.OverlayMarkDef(color=C_PRI)).encode(
                 y="Utilización:Q",
                 tooltip=["sem_lbl", alt.Tooltip("Utilización:Q", format=".0f")])
             + alt.Chart(pd.DataFrame({"y": [90]})).mark_rule(color=C_OK, strokeDash=[6, 4]).encode(y="y:Q")
             ).properties(height=260), use_container_width=True)

    # ---------- gráfico 3: desvío por reacción de la semana ----------
    g3, g4 = st.columns(2)
    _dw = dfw[dfw["reaccion_confiable"] & dfw["desvio_h"].notna()].copy()
    with g3:
        st.markdown("**Desvío vs tiempo estimado** — reacción real vs programada, por reacción (h)")
        st.caption("📐 Se mide **hasta el fin de reacción** (pase a reposo); reposo/decantación no cuentan. "
                   "El fin real de acopio se sumará más adelante.")
        if _dw.empty:
            st.caption("Sin reacciones con tiempo de reacción confiable esta semana (etapa avanzada a los "
                       "clicks). Corregí inicio/fin de reacción en Performance → ✏️ para que se llene.")
        else:
            _dw["color"] = _dw["desvio_h"].map(lambda v: "Más lento" if v > 0 else "Más rápido")
            st.altair_chart(
                alt.Chart(_dw).mark_bar(cornerRadius=3).encode(
                    y=alt.Y("ident:N", sort="-x", title=None),
                    x=alt.X("desvio_h:Q", title="h vs Reacción del cronograma"),
                    color=alt.Color("color:N", scale=alt.Scale(domain=["Más lento", "Más rápido"],
                                                               range=[C_BAD, C_OK]), legend=None),
                    tooltip=["ident", "etiqueta",
                             alt.Tooltip("reaccion_h:Q", title="Reacción real (h)", format=".1f"),
                             alt.Tooltip("prog_reaccion_h:Q", title="Reacción prog. (h)", format=".1f"),
                             alt.Tooltip("desvio_h:Q", title="Desvío (h)", format="+.1f")],
                ).properties(height=max(180, 34 * len(_dw))), use_container_width=True)

    # ---------- gráfico 4: mapa de eficiencia ----------
    with g4:
        st.markdown("**Mapa de eficiencia** — utilización vs rendimiento (tamaño = TN de MP)")
        _ef = dfw[dfw["utilizacion_pct"].notna()].copy()
        _ef["Rend"] = _ef["rendimiento_pct"]
        if _ef.empty:
            st.caption("Sin datos de capacidad esta semana.")
        else:
            _pts = alt.Chart(_ef).mark_circle(opacity=0.85).encode(
                x=alt.X("utilizacion_pct:Q", title="Utilización %", scale=alt.Scale(domain=[0, 110])),
                y=alt.Y("Rend:Q", title="Rendimiento %"),
                size=alt.Size("mp_kg:Q", legend=None, scale=alt.Scale(range=[80, 900])),
                color=alt.Color("tipo:N", scale=alt.Scale(domain=["ARE", "DESGOMADO"],
                                                          range=[C_PRI, C_AMB]), legend=alt.Legend(orient="top")),
                tooltip=["ident", "etiqueta", "reactor",
                         alt.Tooltip("utilizacion_pct:Q", title="Utilización %", format=".0f"),
                         alt.Tooltip("Rend:Q", title="Rendimiento %", format=".0f"),
                         alt.Tooltip("mp_kg:Q", title="MP (kg)", format=",.0f")])
            _r1 = alt.Chart(pd.DataFrame({"x": [90]})).mark_rule(color=C_MUT, strokeDash=[4, 4]).encode(x="x:Q")
            _r2 = alt.Chart(pd.DataFrame({"y": [100]})).mark_rule(color=C_MUT, strokeDash=[4, 4]).encode(y="y:Q")
            st.altair_chart((_pts + _r1 + _r2).properties(height=280), use_container_width=True)
            st.caption("Arriba-derecha = reactor lleno y rendimiento pleno. Sin punto = falta cerrar el real en Terminadas.")

    # ---------- comparativa entre semanas ----------
    st.divider()
    st.markdown("### 📊 Comparativa entre semanas — ⚗️ ARE vs 🫧 DESGOMADO")
    st.caption("Evolución semanal de los indicadores clave, separada por tipo (últimas 12 semanas). "
               "Acidez = promedio del lab del producto final; desvío = mediana vs Reacción del cronograma.")
    _rows_cmp = []
    for (_s, _lblc, _t), _g in df.groupby(["semana", "sem_lbl", "tipo"]):
        _a3 = _agg(_g)
        _rows_cmp.append({"semana": _s, "Semana": _lblc, "Tipo": _t, "Reacciones": _a3["n"],
                          "MP (TN)": round(_a3["mp"], 1), "Final (TN)": round(_a3["pf"], 1),
                          "Rendimiento %": (round(_a3["rend"], 0) if _a3["rend"] is not None else None),
                          "Acidez %": (round(_a3["aci"], 2) if _a3["aci"] is not None else None),
                          "Desvío (h)": (round(_a3["dsv"], 1) if _a3["dsv"] is not None else None)})
    _cmp = pd.DataFrame(_rows_cmp)
    if not _cmp.empty:
        _ult = sorted(_cmp["semana"].unique())[-12:]
        _cmp = _cmp[_cmp["semana"].isin(_ult)].sort_values(["semana", "Tipo"])
        _ord_sem = list(dict.fromkeys(_cmp.sort_values("semana")["Semana"]))
        _sc_tipo = alt.Scale(domain=["ARE", "DESGOMADO"], range=[C_PRI, C_AMB])

        def _mini_cmp(col, campo, titulo, bar=False, fmt=",.1f"):
            _d = _cmp.dropna(subset=[campo])
            with col:
                st.markdown(f"**{titulo}**")
                if _d.empty:
                    st.caption("Sin datos todavía.")
                    return
                _enc = dict(
                    x=alt.X("Semana:N", sort=_ord_sem, title=None),
                    y=alt.Y(f"{campo}:Q", title=None),
                    color=alt.Color("Tipo:N", scale=_sc_tipo, legend=alt.Legend(orient="top", title=None)),
                    tooltip=["Semana", "Tipo", "Reacciones", alt.Tooltip(f"{campo}:Q", format=fmt)],
                )
                if bar:
                    _ch = alt.Chart(_d).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                        xOffset="Tipo:N", **_enc)
                else:
                    _ch = (alt.Chart(_d).mark_line(point=True).encode(**_enc))
                st.altair_chart(_ch.properties(height=220), use_container_width=True)

        _cc1, _cc2 = st.columns(2)
        _mini_cmp(_cc1, "MP (TN)", "Toneladas de MP por semana", bar=True)
        _mini_cmp(_cc2, "Rendimiento %", "Rendimiento (%) por semana", fmt=",.0f")
        _cc3, _cc4 = st.columns(2)
        _mini_cmp(_cc3, "Acidez %", "Acidez del producto final (%)", fmt=",.2f")
        _mini_cmp(_cc4, "Desvío (h)", "Desvío vs plan (h, mediana)", bar=True)
        with st.expander("📋 Tabla comparativa semana a semana", expanded=False):
            st.dataframe(_cmp.drop(columns=["semana"]), hide_index=True, use_container_width=True,
                         column_config={c: st.column_config.NumberColumn(format="%.1f")
                                        for c in ("MP (TN)", "Final (TN)", "Rendimiento %", "Desvío (h)")}
                                       | {"Acidez %": st.column_config.NumberColumn(format="%.2f")})

    # ---------- laboratorio del producto final ----------
    st.divider()
    st.markdown("### 🧪 Laboratorio del producto final")
    _lw = dfw[dfw["fuente_lab"].notna()].copy()
    g5, g6 = st.columns([1.4, 1])
    with g5:
        if _lw.empty:
            st.caption("Ninguna reacción de la semana tiene lab del producto final todavía.")
        else:
            _ll = _lw.melt(id_vars=["ident", "fuente_lab"],
                           value_vars=["acidez_pct", "agua_pct"],
                           var_name="Parámetro", value_name="Valor").dropna(subset=["Valor"])
            _ll["Parámetro"] = _ll["Parámetro"].map({"acidez_pct": "Acidez %", "agua_pct": "Agua %"})
            st.altair_chart(
                alt.Chart(_ll).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                    x=alt.X("ident:N", title=None),
                    xOffset="Parámetro:N",
                    y=alt.Y("Valor:Q", title="%"),
                    color=alt.Color("Parámetro:N", scale=alt.Scale(domain=["Acidez %", "Agua %"],
                                                                   range=[C_SEC, "#0ea5e9"]),
                                    legend=alt.Legend(orient="top")),
                    tooltip=["ident", "Parámetro", alt.Tooltip("Valor:Q", format=".2f"), "fuente_lab"],
                ).properties(height=240), use_container_width=True)
    with g6:
        _ids_w = tuple(int(x) for x in dfw["id_batch"].tolist())
        _tks = cat("SELECT t.id_batch, string_agg(t.ticket || "
                   "CASE WHEN v.tx IS NULL THEN ' ❌' WHEN v.con_lab THEN ' ✅' ELSE ' ⚠️' END, "
                   "' · ' ORDER BY t.ticket) AS tickets "
                   "FROM produccion.fact_batch_ticket_final t "
                   "LEFT JOIN (SELECT transaccion::text AS tx, "
                   "  bool_or(lab_num_muestra IS NOT NULL OR lab_prc_acidez IS NOT NULL) AS con_lab "
                   "  FROM produccion.v_transacciones_limpias GROUP BY transaccion::text) v "
                   "  ON v.tx = t.ticket::text "
                   "WHERE t.id_batch IN %s AND NOT COALESCE(t.anulado,false) "
                   "GROUP BY t.id_batch", (_ids_w,))
        _t = dfw[["id_batch", "ident", "producto", "fuente_lab", "acidez_pct", "agua_pct",
                  "azufre_ppm", "fosforo_ppm"]].copy()
        if _tks is not None and not _tks.empty:
            _t = _t.merge(_tks, on="id_batch", how="left")
        else:
            _t["tickets"] = None
        _t["Lab"] = _t["fuente_lab"].map({"TICKETS": "🎫 tickets", "ASIGNADO": "🧪 asignado",
                                          "TICKET_REACCION": "🏷️ ticket=ID"}).fillna("❌ sin lab")
        _t["Tickets finales"] = _t["tickets"].fillna("—")
        st.dataframe(_t.drop(columns=["fuente_lab", "id_batch", "tickets"]).rename(
                         columns={"ident": "ID", "producto": "Producto", "acidez_pct": "Acidez %",
                                  "agua_pct": "Agua %", "azufre_ppm": "Azufre ppm",
                                  "fosforo_ppm": "Fósforo ppm"}),
                     hide_index=True, use_container_width=True,
                     column_config={**{c: st.column_config.NumberColumn(format="%.2f")
                                       for c in ("Acidez %", "Agua %")},
                                    "Tickets finales": st.column_config.TextColumn(
                                        help="Tickets finales de pesada asignados a la reacción: "
                                             "✅ evaluado por lab · ⚠️ pesado sin evaluación · "
                                             "❌ no está en balanza.")})

    # ---------- asignar evaluación de lab a ARE ----------
    with st.expander("🎫 Tickets finales por reacción — ¿se evaluaron?", expanded=False):
        st.caption("La calidad de un desgomado sale de la **evaluación de sus tickets finales de pesada**. "
                   "Acá ves cada ticket de la reacción y si laboratorio lo analizó. Si hay **más de un "
                   "ticket evaluado, el resultado final pondera por kg** automáticamente. "
                   "⚠️ pesado sin evaluación = pedile el análisis a laboratorio (ese fue el caso de RE-349, "
                   "ticket 5690); ❌ sin tickets = falta cargar el ticket final (caso RE-348).")
        _rx = cat("SELECT b.id_batch, b.identificador_unidad AS ident, et.etiqueta, "
                  "dp.codigo_producto AS producto, l.fuente_lab, l.n_tickets, l.n_con_lab "
                  "FROM produccion.fact_batch_proceso b "
                  "LEFT JOIN produccion.v_reaccion_lab_final l ON l.id_batch=b.id_batch "
                  "LEFT JOIN produccion.v_reaccion_etiqueta et ON et.id_batch=b.id_batch "
                  "LEFT JOIN produccion.dim_producto dp ON dp.id_producto=b.id_producto_buscado "
                  "WHERE b.estado='FINALIZADO' AND b.sector='REACTORES' "
                  "AND COALESCE(b.anulado,false)=false ORDER BY b.id_batch DESC LIMIT 60")
        if _rx is None or _rx.empty:
            st.info("No hay reacciones finalizadas.")
        else:
            def _res_tk(r):
                _n = int(r["n_tickets"]) if pd.notna(r["n_tickets"]) else 0
                _e = int(r["n_con_lab"]) if pd.notna(r["n_con_lab"]) else 0
                if _n == 0:
                    return "❌ sin tickets finales"
                if _e == 0:
                    return f"⚠️ {_n} ticket(s), NINGUNO evaluado"
                return f"✅ {_e}/{_n} evaluados"
            _rops = _rx.apply(lambda r: f"{r['ident']} · {r['producto'] or '?'} · {_res_tk(r)}", axis=1).tolist()
            _rs = st.selectbox("Reacción", _rops, key="anr_tk_sel")
            _rr = _rx.iloc[_rops.index(_rs)]
            _det = cat("SELECT t.ticket, t.kg, (vx.tx IS NOT NULL) AS en_balanza, vx.num_muestra, "
                       "vx.acidez, vx.agua, vx.azufre "
                       "FROM produccion.fact_batch_ticket_final t "
                       "LEFT JOIN (SELECT transaccion::text AS tx, max(lab_num_muestra) AS num_muestra, "
                       "  avg(lab_prc_acidez) AS acidez, avg(lab_prc_agua) AS agua, "
                       "  avg(lab_ppm_azufre) AS azufre FROM produccion.v_transacciones_limpias "
                       "  GROUP BY transaccion::text) vx ON vx.tx = t.ticket::text "
                       "WHERE t.id_batch=%s AND NOT COALESCE(t.anulado,false) ORDER BY t.ticket",
                       (int(_rr["id_batch"]),))
            if _det is None or _det.empty:
                st.error(f"**{_rr['ident']} no tiene tickets finales cargados.** Cargalos en la ficha de la "
                         "reacción (🏁 Tickets finales) o el lab quedará vacío para siempre.")
            else:
                for c in ("kg", "acidez", "agua", "azufre"):
                    _det[c] = pd.to_numeric(_det[c], errors="coerce")
                def _est(r):
                    if not bool(r["en_balanza"]):
                        return "❌ no está en balanza"
                    if pd.notna(r["num_muestra"]) or pd.notna(r["acidez"]) or pd.notna(r["agua"]):
                        return "✅ evaluado"
                    return "⚠️ pesado SIN evaluación"
                _det["Estado"] = _det.apply(_est, axis=1)
                st.dataframe(_det.rename(columns={"ticket": "Ticket", "kg": "Kg", "num_muestra": "Muestra",
                                                  "acidez": "Acidez %", "agua": "Agua %",
                                                  "azufre": "Azufre ppm"}).drop(columns=["en_balanza"]),
                             hide_index=True, use_container_width=True,
                             column_config={"Kg": st.column_config.NumberColumn(format="%.0f"),
                                            **{c: st.column_config.NumberColumn(format="%.2f")
                                               for c in ("Acidez %", "Agua %")}})
                _ev = _det[_det["Estado"] == "✅ evaluado"]
                if len(_ev) > 1:
                    _w = _ev["kg"].fillna(0)
                    _pa = (_ev["acidez"] * _w).sum() / _w[_ev["acidez"].notna()].sum()                         if _w[_ev["acidez"].notna()].sum() else None
                    st.caption(f"Ponderado por kg sobre {len(_ev)} tickets evaluados"
                               + (f" → acidez final **{_pa:.2f}%**." if _pa else "."))
                elif _ev.empty:
                    st.warning("Ningún ticket de esta reacción fue evaluado por laboratorio → por eso figura "
                               "**sin lab**. Pedí el análisis o asignale una muestra a mano (expander de abajo).")

    with st.expander("🧪 Asignar evaluación de laboratorio al producto final", expanded=False):
        st.caption("Si laboratorio cargó una muestra con **ticket = identificador de la reacción** (ej. RE-348), se usa sola 🏷️ — sin asignar nada. "
                   "Los **desgomados** también toman lab de los tickets finales de pesada; "
                   "las **ARE** (o un desgomado sin ticket analizado) se asignan acá. La lista solo "
                   "muestra muestras de `procesos_lab` **del producto final de la reacción** "
                   "(ARE → ARE · AFE-S/AFE-G → AFE), las de calidad exacta primero.")
        _sin = cat("SELECT b.id_batch, b.identificador_unidad AS ident, et.etiqueta, b.tipo_proceso, "
                   "dp.codigo_producto AS producto, dl.lab_producto, dl.lab_calidad, "
                   "l.fuente_lab, l.id_procesos_lab "
                   "FROM produccion.fact_batch_proceso b "
                   "LEFT JOIN produccion.v_reaccion_lab_final l ON l.id_batch=b.id_batch "
                   "LEFT JOIN produccion.v_reaccion_etiqueta et ON et.id_batch=b.id_batch "
                   "LEFT JOIN produccion.dim_producto dp ON dp.id_producto=b.id_producto_buscado "
                   "LEFT JOIN produccion.dic_producto_lab dl ON dl.id_producto=b.id_producto_buscado "
                   "WHERE b.estado='FINALIZADO' AND b.sector='REACTORES' "
                   "AND COALESCE(b.anulado,false)=false ORDER BY b.id_batch DESC LIMIT 60")
        if _sin is None or _sin.empty:
            st.info("No hay reacciones finalizadas.")
        else:
            def _estado_lab(r):
                if r["fuente_lab"] == "TICKET_REACCION":
                    return f"🏷️ auto: ticket con su ID (muestra {int(r['id_procesos_lab'])})"
                if pd.notna(r["id_procesos_lab"]):
                    return f"🧪 muestra {int(r['id_procesos_lab'])}"
                if r["fuente_lab"] == "TICKETS":
                    return "🎫 tickets"
                return "❌ sin lab"
            _ops = _sin.apply(lambda r: f"{r['ident']} · {r['producto'] or '?'} · {_estado_lab(r)}", axis=1).tolist()
            _s = st.selectbox("Reacción", _ops, key="anr_asig_sel")
            _rb = _sin.iloc[_ops.index(_s)]
            _lab_prod = _rb["lab_producto"] or (str(_rb["producto"] or "").split("-")[0] or None)
            _lab_cal = _rb["lab_calidad"]
            if not _lab_prod:
                st.warning("Esta reacción no tiene producto final definido; no puedo filtrar muestras.")
            else:
                _bq = st.text_input("🔍 Buscar muestra por ticket / nº / id",
                                    key=f"anr_asig_q_{int(_rb['id_batch'])}",
                                    placeholder="ej: RE-348 · 5690 · 424 (vacío = últimas 30)")
                _flt, _par = "", [str(_lab_prod)]
                if _bq.strip():
                    _flt = "AND (ticket ILIKE %s OR num_muestra::text ILIKE %s OR id::text = %s) "
                    _par += [f"%{_bq.strip()}%", f"%{_bq.strip()}%", _bq.strip()]
                _par += [str(_rb["ident"] or ""), (str(_lab_cal) if _lab_cal else "")]
                _mu = cat("SELECT id, ticket, num_muestra, fecha, producto_lab, "
                          "calidad_final_lab AS calidad, prc_acidez, prc_agua, ppm_azufre "
                          "FROM produccion.procesos_lab WHERE producto_lab=%s "
                          "AND COALESCE(anulado,false)=false "
                          + _flt +
                          "ORDER BY (CASE WHEN ticket ILIKE %s THEN 0 ELSE 1 END), "
                          "(CASE WHEN calidad_final_lab=%s THEN 0 ELSE 1 END), "
                          "fecha DESC NULLS LAST, id DESC LIMIT 30",
                          tuple(_par))
                if _mu is None or _mu.empty:
                    st.warning(f"No hay muestras de {_lab_prod}"
                               + (f" que coincidan con «{_bq.strip()}»" if _bq.strip() else " en procesos_lab")
                               + ".")
                else:
                    def _fmt_mu(r):
                        try:
                            _f = pd.to_datetime(r["fecha"]).strftime("%d/%m/%y")
                        except Exception:
                            _f = "—"
                        _tk = (str(r["ticket"]).strip() if pd.notna(r["ticket"]) and str(r["ticket"]).strip()
                               else (f"muestra {r['num_muestra']}" if pd.notna(r["num_muestra"]) else "sin ticket"))
                        _cal = f"-{r['calidad']}" if pd.notna(r["calidad"]) and str(r["calidad"]).strip() else ""
                        _aci = f" · acidez {float(r['prc_acidez']):.2f}%" if pd.notna(r["prc_acidez"]) else ""
                        _agu = f" · agua {float(r['prc_agua']):.2f}%" if pd.notna(r["prc_agua"]) else ""
                        return f"🎫 {_tk} · {_f} · {r['producto_lab']}{_cal}{_aci}{_agu} · #{int(r['id'])}"
                    _mops = _mu.apply(_fmt_mu, axis=1).tolist() + ["🔎 Otro id (manual)…"]
                    _cur = int(_rb["id_procesos_lab"]) if pd.notna(_rb["id_procesos_lab"]) else None
                    _ix = next((i for i, (_, r) in enumerate(_mu.iterrows()) if _cur and int(r["id"]) == _cur), 0)
                    _ms = st.selectbox(f"Muestra de laboratorio ({_lab_prod}"
                                       + (f", calidad {_lab_cal} primero)" if _lab_cal else ")"),
                                       _mops, index=_ix, key=f"anr_asig_mu_{int(_rb['id_batch'])}")
                    if _ms == "🔎 Otro id (manual)…":
                        _id_lab = int(st.number_input("Id de la muestra", min_value=0, step=1,
                                                      key=f"anr_asig_id_{int(_rb['id_batch'])}"))
                        if _id_lab > 0:
                            _chk = cat("SELECT id, ticket, num_muestra, fecha, producto_lab, "
                                       "calidad_final_lab AS calidad, prc_acidez, prc_agua "
                                       "FROM produccion.procesos_lab WHERE id=%s", (int(_id_lab),))
                            if _chk is None or _chk.empty:
                                st.error(f"No existe la muestra id {_id_lab}."); _id_lab = 0
                            else:
                                st.dataframe(_chk, hide_index=True, use_container_width=True)
                    else:
                        _id_lab = int(_mu.iloc[_mops.index(_ms)]["id"])
                    if _id_lab and st.button(f"💾 Asignar muestra #{_id_lab} a {_rb['ident']}", type="primary",
                                             key=f"anr_asig_save_{int(_rb['id_batch'])}"):
                        try:
                            with conectar(int(USR["id_usuario"])) as (conn, audit):
                                with conn.cursor() as cur:
                                    cur.execute("INSERT INTO produccion.fact_batch_lab_final "
                                                "(id_batch, id_procesos_lab, id_usuario) VALUES (%s,%s,%s) "
                                                "ON CONFLICT (id_batch) DO UPDATE SET "
                                                "id_procesos_lab=EXCLUDED.id_procesos_lab, "
                                                "id_usuario=EXCLUDED.id_usuario, creado_en=now()",
                                                (int(_rb["id_batch"]), int(_id_lab), int(USR["id_usuario"])))
                                audit.log("U", "fact_batch_lab_final", int(_rb["id_batch"]),
                                          {"id_procesos_lab": int(_id_lab)})
                            cat.clear()
                            st.success(f"Muestra #{_id_lab} asignada a {_rb['ident']}."); st.rerun()
                        except Exception as e:
                            st.exception(e)

    # ---------- detalle de la semana ----------
    with st.expander("📋 Detalle de las reacciones de la semana", expanded=False):
        _d = dfw[["ident", "etiqueta", "tipo", "reactor", "producto", "mp_kg", "real_kg",
                  "utilizacion_pct", "rendimiento_pct", "reaccion_h", "prog_reaccion_h",
                  "desvio_h", "acidez_pct"]].copy()
        for c in ("mp_kg", "real_kg"):
            _d[c] = _d[c] / 1000.0
        _d = _d.rename(columns={"ident": "ID", "etiqueta": "Reacción", "tipo": "Tipo", "reactor": "Reactor",
                                "producto": "Producto", "mp_kg": "MP (TN)", "real_kg": "Final (TN)",
                                "utilizacion_pct": "Utilización %", "rendimiento_pct": "Rendimiento %",
                                "reaccion_h": "Reacción real (h)", "prog_reaccion_h": "Reacción prog. (h)",
                                "desvio_h": "Δ (h)", "acidez_pct": "Acidez %"})
        st.dataframe(_d, hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="%.1f")
                                    for c in ("MP (TN)", "Final (TN)", "Utilización %", "Rendimiento %",
                                              "Reacción real (h)", "Reacción prog. (h)", "Δ (h)", "Acidez %")})
