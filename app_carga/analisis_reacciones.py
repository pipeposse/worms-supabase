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
         "rendimiento_pct", "acidez_pct", "agua_pct", "azufre_ppm", "densidad"]


def _cargar(cat):
    df = cat("SELECT p.id_batch, p.ident, p.etiqueta, p.tipo, p.tipo_proceso, p.reactor, p.producto, "
             "p.fecha, p.inicio_local, p.fin_local, p.espera_arranque_h, p.reaccion_h, p.reposo_h, "
             "p.decantacion_h, p.ciclo_proceso_h, p.prog_proceso_h, p.desvio_proceso_h, "
             "p.prog_reaccion_h, p.desvio_h, p.reaccion_confiable, "
             "p.max_kg, p.formula_kg, p.mp_kg, p.real_kg, p.utilizacion_pct, p.capacidad_perdida_kg, "
             "p.rendimiento_pct, p.tiempos_confiables, "
             "l.fuente_lab, l.id_procesos_lab, l.acidez_pct, l.agua_pct, l.azufre_ppm, l.densidad "
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
    _tipo = c_tipo.selectbox("Tipo", ["Todas", "ARE", "DESGOMADO"], key="anr_tipo")
    _wk = next(s for s in _sems if _lbl[s] == _sel)
    if _tipo != "Todas":
        df = df[df["tipo"] == _tipo]
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
        _t = dfw[["ident", "producto", "fuente_lab", "acidez_pct", "agua_pct", "azufre_ppm"]].copy()
        _t["Lab"] = _t["fuente_lab"].map({"TICKETS": "🎫 tickets", "ASIGNADO": "🧪 asignado"}).fillna("❌ sin lab")
        st.dataframe(_t.drop(columns=["fuente_lab"]).rename(
                         columns={"ident": "ID", "producto": "Producto", "acidez_pct": "Acidez %",
                                  "agua_pct": "Agua %", "azufre_ppm": "Azufre ppm"}),
                     hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="%.2f")
                                    for c in ("Acidez %", "Agua %")})

    # ---------- asignar evaluación de lab a ARE ----------
    with st.expander("🧪 Asignar evaluación de laboratorio al producto final", expanded=False):
        st.caption("Los **desgomados** toman el lab automáticamente de los tickets finales de pesada; "
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
                _mu = cat("SELECT id, fecha, producto_lab, calidad_final_lab AS calidad, "
                          "prc_acidez, prc_agua, ppm_azufre "
                          "FROM produccion.procesos_lab WHERE producto_lab=%s "
                          "ORDER BY (CASE WHEN calidad_final_lab=%s THEN 0 ELSE 1 END), "
                          "fecha DESC NULLS LAST, id DESC LIMIT 30",
                          (str(_lab_prod), (str(_lab_cal) if _lab_cal else "")))
                if _mu is None or _mu.empty:
                    st.warning(f"No hay muestras de {_lab_prod} en procesos_lab.")
                else:
                    def _fmt_mu(r):
                        try:
                            _f = pd.to_datetime(r["fecha"]).strftime("%d/%m/%y")
                        except Exception:
                            _f = "—"
                        _cal = f"-{r['calidad']}" if pd.notna(r["calidad"]) and str(r["calidad"]).strip() else ""
                        _aci = f" · acidez {float(r['prc_acidez']):.2f}%" if pd.notna(r["prc_acidez"]) else ""
                        _agu = f" · agua {float(r['prc_agua']):.2f}%" if pd.notna(r["prc_agua"]) else ""
                        return f"#{int(r['id'])} · {_f} · {r['producto_lab']}{_cal}{_aci}{_agu}"
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
                            _chk = cat("SELECT id, fecha, producto_lab, calidad_final_lab AS calidad, "
                                       "prc_acidez, prc_agua FROM produccion.procesos_lab WHERE id=%s",
                                       (int(_id_lab),))
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
